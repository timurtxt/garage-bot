import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two WGS-84 points."""
    R = 6_371_000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_in_polygon(lat: float, lon: float, poly: List[Tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon; poly = list of (lat, lon)."""
    n, inside, j = len(poly), False, len(poly) - 1
    for i in range(n):
        xi, yi = poly[i][1], poly[i][0]
        xj, yj = poly[j][1], poly[j][0]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _apply_calibration(raw: float, tbl: List[Dict]) -> float:
    """Wialon calculation table: row formula is result = a * raw + b."""
    if not tbl:
        return raw
    sorted_tbl = sorted(tbl, key=lambda p: p.get("x", 0))
    matched = sorted_tbl[0]
    for row in sorted_tbl:
        if raw >= row.get("x", 0):
            matched = row
        else:
            break
    a = matched.get("a", 1.0)
    b = matched.get("b", 0.0)
    return a * raw + b


# ──────────────────────────────────────────────────────────────────────────────
# Exception
# ──────────────────────────────────────────────────────────────────────────────

class WialonError(Exception):
    _CODES = {
        1: "Invalid session", 2: "Invalid service", 3: "Invalid result",
        4: "Invalid input",   5: "Error performing request", 6: "Unknown error",
        7: "Access denied",   8: "Bad credentials",
        9: "Auth server unavailable", 10: "Concurrent requests limit",
    }

    def __init__(self, code: int, reason: str = ""):
        self.code = code
        msg = self._CODES.get(code, f"code {code}")
        super().__init__(f"Wialon [{msg}]" + (f": {reason}" if reason else ""))


# ──────────────────────────────────────────────────────────────────────────────
# Client
# ──────────────────────────────────────────────────────────────────────────────

class WialonClient:
    # All flags to get unit position, last msg, sensors, mileage, counters, service intervals
    _UNIT_FLAGS = 4194303

    def __init__(self, token: str, base_url: str = "https://2.smartgps.uz"):
        self.token = token
        self._api = base_url.rstrip("/") + "/wialon/ajax.html"
        self.sid: Optional[str] = None
        self._http = requests.Session()

    # ── low-level ────────────────────────────────────────────────────────────

    def _call(self, svc: str, params: dict) -> Any:
        data: Dict[str, Any] = {
            "svc": svc,
            "params": json.dumps(params, ensure_ascii=False),
        }
        if self.sid:
            data["sid"] = self.sid
        resp = self._http.post(self._api, data=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, dict) and "error" in result:
            raise WialonError(result["error"], result.get("reason", ""))
        return result

    # ── session ──────────────────────────────────────────────────────────────

    def login(self) -> dict:
        result = self._call("token/login", {"token": self.token})
        self.sid = result["eid"]
        log.info("Wialon login OK user=%s", result.get("user", {}).get("nm", "?"))
        return result

    def ping(self):
        """Keep session alive by re-logging in."""
        try:
            self.login()
        except Exception as e:
            log.warning("Ping/re-login failed: %s", e)

    # ── units ────────────────────────────────────────────────────────────────

    def get_units(self) -> List[dict]:
        result = self._call("core/search_items", {
            "spec": {
                "itemsType": "avl_unit",
                "propName":  "sys_name",
                "propValueMask": "*",
                "sortType": "sys_name",
            },
            "force": 1,
            "flags": self._UNIT_FLAGS,
            "from": 0,
            "to":   0,
        })
        items = result.get("items", [])
        log.debug("Got %d units from Wialon", len(items))
        return items

    # ── geofences ────────────────────────────────────────────────────────────

    def get_zone(self, zone_name: str) -> Tuple[Optional[int], Optional[dict]]:
        """Find geofence by name and fetch full polygon geometry."""
        try:
            result = self._call("core/search_items", {
                "spec": {
                    "itemsType": "avl_resource",
                    "propName":  "sys_name",
                    "propValueMask": "*",
                    "sortType": "sys_name",
                },
                "force": 1,
                "flags": 4097,
                "from": 0,
                "to":   0,
            })
            for res in result.get("items", []):
                res_id = res.get("id")
                for zid, zone in res.get("zl", {}).items():
                    if zone_name.lower() in zone.get("n", "").lower():
                        # Fetch full zone data with polygon points
                        try:
                            zd = self._call("resource/get_zone_data", {
                                "itemId": res_id,
                                "col": [int(zid)],
                                "flags": 0,
                            })
                            if zd and isinstance(zd, list) and len(zd) > 0:
                                full_zone = zd[0]
                                log.info(
                                    "Zone '%s' found (id=%s) in resource '%s' with %d points",
                                    zone_name, zid, res.get("nm"), len(full_zone.get("p", [])),
                                )
                                return int(zid), full_zone
                        except Exception as ze:
                            log.warning("get_zone_data failed: %s, using header", ze)
                        return int(zid), zone
        except Exception as e:
            log.error("Zone search failed: %s", e)
        log.error("Zone '%s' not found", zone_name)
        return None, None

    def is_in_zone(self, lat: float, lon: float, zone: dict) -> bool:
        if not zone:
            return False
        points = zone.get("p", [])
        if not points:
            # Fallback to bounding box if points not loaded
            b = zone.get("b", {})
            if b:
                return (b.get("min_y", 0) <= lat <= b.get("max_y", 0) and
                        b.get("min_x", 0) <= lon <= b.get("max_x", 0))
            return False

        # If points list exists
        if len(points) >= 3:
            poly = [(p.get("y", 0), p.get("x", 0)) for p in points]
            return _point_in_polygon(lat, lon, poly)
        elif len(points) == 1:
            # Circle
            c = points[0]
            r = c.get("r", zone.get("w", 50))
            return _haversine(lat, lon, c.get("y", 0), c.get("x", 0)) <= r
        return False

    # ── unit data extractors ─────────────────────────────────────────────────

    def get_unit_pos(self, unit: dict) -> Optional[Tuple[float, float]]:
        pos = unit.get("pos") or (unit.get("lmsg") or {}).get("pos")
        if pos and pos.get("y") is not None and pos.get("x") is not None:
            return float(pos["y"]), float(pos["x"])
        return None

    def get_mileage(self, unit: dict) -> Optional[float]:
        # 1. cnm_km or cnm
        cnm = unit.get("cnm_km") or unit.get("cnm")
        if cnm and cnm > 0:
            return cnm / 1000 if cnm > 10_000_000 else float(cnm)

        # 2. Last-message params
        params = (unit.get("lmsg") or {}).get("p", {})
        for key in ("mileage", "odometer", "total_mileage", "can_mileage"):
            v = params.get(key)
            if v and float(v) > 0:
                v_flt = float(v)
                return v_flt / 1000 if v_flt > 10_000_000 else v_flt
        return None

    def get_fuel(self, unit: dict) -> Optional[Dict]:
        sensors = unit.get("sens", {})
        params  = (unit.get("lmsg") or {}).get("p", {})

        for sensor in sensors.values():
            nm = sensor.get("n", "").lower()
            tp = sensor.get("t", "").lower()
            if tp == "fuel level" or any(k in nm for k in ("топливо в баке", "топливо", "дут", "бак")):
                p_name = sensor.get("p", "")
                raw = params.get(p_name)
                if raw is None:
                    continue
                try:
                    raw_val = float(raw)
                except (ValueError, TypeError):
                    continue

                # Filter out standard LLS error / disconnected codes (65530..65535) and outliers
                if raw_val >= 65530 or raw_val > 6000 or raw_val < 0:
                    continue

                tbl = sensor.get("tbl", [])
                lvl = _apply_calibration(raw_val, tbl)
                if lvl < 0:
                    lvl = 0.0

                # Max capacity from calibration table or sensor property
                mx = None
                if tbl:
                    # Look at highest X in tbl to find max calibrated volume
                    max_row = max(tbl, key=lambda r: r.get("x", 0))
                    mx_calc = max_row.get("a", 0) * max_row.get("x", 0) + max_row.get("b", 0)
                    if mx_calc > 0:
                        mx = mx_calc
                if not mx or mx <= 0:
                    mx = sensor.get("mx") or 300.0

                # Cap level to maximum tank capacity
                if mx and lvl > mx:
                    lvl = mx

                pct = round(lvl / mx * 100, 1) if mx and mx > 0 else None
                return {
                    "level":     round(lvl, 1),
                    "max":       round(mx, 1) if mx else None,
                    "pct":       min(pct, 100.0) if pct else None,
                    "is_diesel": True,
                }
        return None

    def get_driver(self, unit: dict) -> str:
        # 1 – Driver binding list
        for drv in (unit.get("drvrs") or []):
            if isinstance(drv, dict) and drv.get("nm"):
                return drv["nm"]

        # 2 – Unit name in format: "Name (Driver Name)"
        nm = unit.get("nm", "")
        # Find all occurrences of (...)
        matches = re.findall(r"\(([^)]+)\)", nm)
        if matches:
            # Pick the last match that looks like a person's name (not technical like 'кран', 'миксер', 'помпа')
            for m in reversed(matches):
                if not any(tech in m.lower() for tech in ["кран", "миксер", "помпа", "манипул", "40t", "30t", "бетонасос", "агрегат"]):
                    return m.strip()

        # 3 – Custom fields
        for fld in (unit.get("flds") or {}).values():
            if any(k in fld.get("n", "").lower() for k in ("водитель", "driver")):
                v = fld.get("v", "").strip()
                if v:
                    return v

        return "Не назначен"

    def get_maintenance(self, unit: dict) -> List[Dict]:
        """Return all active maintenance intervals sorted by urgency (overdues first)."""
        si = unit.get("si", {})
        if not si:
            return []

        current_km = self.get_mileage(unit) or 0
        intervals: List[Dict] = []

        for interval in si.values():
            nm = interval.get("n", "ТО").strip()
            im = interval.get("im", 0)  # interval km
            pm = interval.get("pm", 0)  # prev km
            if im > 0:
                next_km = pm + im
                rem = next_km - current_km
                intervals.append({
                    "name": nm,
                    "interval_km": im,
                    "prev_km": pm,
                    "next_km": next_km,
                    "remaining_km": rem,
                })

        # Sort by remaining_km ascending (negative/overdue items first)
        intervals.sort(key=lambda x: x["remaining_km"])
        return intervals
