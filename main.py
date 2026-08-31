import asyncio
import collections
import io
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

from card_renderer import render_card
from db import Database
from wialon_client import WialonClient

load_dotenv(encoding="utf-8")

# ──────────────────────────────────────────────────────────────────────────────
# 1. Config & Group Routing
# ──────────────────────────────────────────────────────────────────────────────
TG_TOKEN      = os.environ["TELEGRAM_TOKEN"]
WIALON_TOKEN  = os.environ["WIALON_TOKEN"]

raw_all_chats = (
    os.environ.get("TELEGRAM_CHAT_ID")
    or os.environ.get("ALL_CHAT_IDS")
    or "-5389418758,-5571984920"
)
ALL_CHAT_IDS = [cid.strip() for cid in raw_all_chats.split(",") if cid.strip()]

raw_violation_chats = (
    os.environ.get("VIOLATIONS_CHAT_ID")
    or os.environ.get("VIOLATION_CHAT_ID")
    or os.environ.get("VIOLATIONS_CHAT_IDS")
    or os.environ.get("VIOLATION_CHAT_IDS")
    or "-1002069499094"
)
VIOLATION_CHAT_IDS = [cid.strip() for cid in raw_violation_chats.split(",") if cid.strip()]

ZONE_NAME     = os.getenv("GARAGE_ZONE_NAME",    "БКС Гараж")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL",    "10"))
WARN_KM       = int(os.getenv("MAINTENANCE_WARN_KM", "300"))
WIALON_URL    = os.getenv("WIALON_URL", "https://2.smartgps.uz")
PORT          = int(os.getenv("PORT", "10000"))

TZ_UZB = timezone(timedelta(hours=5))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("garage_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Live activity log for web status
RECENT_LOGS = collections.deque(maxlen=30)
STATS = {
    "started_at": datetime.now(TZ_UZB).strftime("%Y-%m-%d %H:%M:%S"),
    "last_poll": "never",
    "cycles": 0,
    "units_in_garage": 0,
    "total_units": 0,
    "last_entry": "none",
}

def record_activity(msg: str):
    ts = datetime.now(TZ_UZB).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    RECENT_LOGS.append(line)
    log.info("%s", msg)


# ──────────────────────────────────────────────────────────────────────────────
# Проверка нарушений
# ──────────────────────────────────────────────────────────────────────────────

def has_violations(data: dict) -> bool:
    m_list = data.get("maintenance") or []
    warn_km = int(data.get("warning_km", 300))
    for m in m_list:
        try:
            rem = float(m.get("remaining_km", 999999))
            if rem <= float(warn_km):
                return True
        except (ValueError, TypeError):
            continue

    last_exit = data.get("last_exit")
    entry_time = data.get("entry_time") or datetime.now(TZ_UZB)
    if last_exit:
        try:
            t_entry = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=TZ_UZB)
            t_exit  = last_exit if last_exit.tzinfo else last_exit.replace(tzinfo=TZ_UZB)
            delta   = t_entry - t_exit
            trip_days = delta.total_seconds() / 86400.0

            name_lower = str(data.get("name", "")).lower()
            is_mixer = "миксер" in name_lower or "mixer" in name_lower
            wash_days_limit = 6.0 if is_mixer else 4.0
            warn_days_limit = wash_days_limit - 1.0

            if trip_days >= warn_days_limit:
                return True
        except Exception:
            pass

    return False


# ──────────────────────────────────────────────────────────────────────────────
# Health check HTTP server with Live Diagnostics
# ──────────────────────────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        
        logs_str = "\n".join(reversed(RECENT_LOGS)) if RECENT_LOGS else "No events yet"
        body = (
            "=== Garage Bot 24/7 Status ===\n"
            f"Started: {STATS['started_at']} (UTC+5)\n"
            f"Last Poll: {STATS['last_poll']}\n"
            f"Cycles Completed: {STATS['cycles']}\n"
            f"Fleet: {STATS['units_in_garage']} in garage / {STATS['total_units']} total\n"
            f"All-Events Groups: {ALL_CHAT_IDS}\n"
            f"Violations Groups: {VIOLATION_CHAT_IDS}\n"
            f"Zone: {ZONE_NAME} | Poll: {POLL_INTERVAL}s | Warn: {WARN_KM} km\n\n"
            "--- Recent Live Events ---\n"
            f"{logs_str}\n"
        )
        self.wfile.write(body.encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server():
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        log.info("Health-check server on port %d", PORT)
        server.serve_forever()
    except Exception as e:
        log.warning("HTTP server error: %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# Card sending
# ──────────────────────────────────────────────────────────────────────────────

async def send_card(bot: Bot, data: dict) -> None:
    img = render_card(data)
    is_violation = has_violations(data)

    car_name = data.get("name", "ТС")
    caption = f"{car_name}"

    target_chats = list(dict.fromkeys(ALL_CHAT_IDS))
    if is_violation and VIOLATION_CHAT_IDS:
        for v_cid in VIOLATION_CHAT_IDS:
            if v_cid not in target_chats:
                target_chats.append(v_cid)

    record_activity(f"Sending card for '{car_name}' (viol={is_violation}) to {target_chats}")

    for chat_id in target_chats:
        try:
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            await bot.send_photo(chat_id=chat_id, photo=buf, caption=caption)
            record_activity(f"SUCCESS: Card sent to {chat_id}")
        except Exception as te:
            record_activity(f"ERROR sending to {chat_id}: {te}")


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    record_activity("=== Garage Bot starting ===")

    http_thread = threading.Thread(target=start_health_server, daemon=True)
    http_thread.start()

    bot    = Bot(token=TG_TOKEN)
    wialon = WialonClient(WIALON_TOKEN, base_url=WIALON_URL)
    db     = Database()

    try:
        wialon.login()
    except Exception as exc:
        record_activity(f"CRITICAL: Wialon login failed: {exc}")
        return

    zone_id, zone = wialon.get_zone(ZONE_NAME)
    if zone is None:
        record_activity(f"CRITICAL: Zone '{ZONE_NAME}' not found")
        return
    record_activity(f"Geofence OK: '{zone.get('n')}' (id={zone_id})")

    in_garage: set[int] = db.get_garage_state()
    is_initial_run = len(in_garage) == 0

    ping_tick = 0

    while True:
        try:
            now_time = datetime.now(TZ_UZB)
            STATS["last_poll"] = now_time.strftime("%H:%M:%S")
            STATS["cycles"] += 1

            ping_tick += 1
            if ping_tick % 10 == 0:
                wialon.ping()

            units   = wialon.get_units()
            STATS["total_units"] = len(units)
            current: set[int] = set()

            for unit in units:
                uid = unit.get("id")
                pos = wialon.get_unit_pos(unit)

                if not pos or pos[0] is None:
                    continue

                lat, lon = pos

                if wialon.is_in_zone(lat, lon, zone):
                    current.add(uid)

                    if uid not in in_garage:          # ← ВЪЕЗД В ГАРАЖ
                        record_activity(f"ENTRY DETECTED: {unit.get('nm')} (id={uid})")
                        STATS["last_entry"] = f"{unit.get('nm')} at {now_time.strftime('%H:%M:%S')}"
                        
                        if not is_initial_run:
                            try:
                                last_exit_dt = None
                                if hasattr(wialon, "get_last_exit_from_wialon"):
                                    try:
                                        last_exit_dt = wialon.get_last_exit_from_wialon(uid, zone, days_back=5)
                                    except Exception as we:
                                        log.warning("Wialon exit lookup warning: %s", we)
                                if not last_exit_dt:
                                    last_exit_dt = db.get_last_exit(uid)

                                card_data = {
                                    "name"       : unit.get("nm", "Неизвестно"),
                                    "driver"     : wialon.get_driver(unit),
                                    "entry_time" : now_time,
                                    "last_exit"  : last_exit_dt,
                                    "fuel"       : wialon.get_fuel(unit),
                                    "mileage"    : wialon.get_mileage(unit),
                                    "maintenance": wialon.get_maintenance(unit),
                                    "warning_km" : WARN_KM,
                                    "garage_name": ZONE_NAME,
                                }
                                await send_card(bot, card_data)
                            except TelegramError as te:
                                record_activity(f"Telegram error: {te}")
                            except Exception as ce:
                                record_activity(f"Card error for '{unit.get('nm')}': {ce}")

                        db.record_entry(uid, unit.get("nm", ""), dt=now_time)

                else:
                    if uid in in_garage:              # ← ВЫЕЗД ИЗ ГЕОЗОНЫ
                        record_activity(f"EXIT DETECTED: {unit.get('nm')} (id={uid})")
                        db.record_exit(uid, unit.get("nm", ""), dt=now_time)

            in_garage = current
            STATS["units_in_garage"] = len(in_garage)
            db.save_garage_state(current)
            if is_initial_run:
                record_activity(f"Initial sync: {len(in_garage)} units inside recorded in DB")
                is_initial_run = False

        except Exception as exc:
            record_activity(f"Poll error: {exc}")
            try:
                wialon.login()
                zone_id, zone = wialon.get_zone(ZONE_NAME)
            except Exception as re_exc:
                record_activity(f"Re-login failed: {re_exc}")

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
