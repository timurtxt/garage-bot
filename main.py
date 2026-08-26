import asyncio
import io
import logging
import os
import threading
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
# Config
# ──────────────────────────────────────────────────────────────────────────────
TG_TOKEN      = os.environ["TELEGRAM_TOKEN"]
WIALON_TOKEN  = os.environ["WIALON_TOKEN"]

# Поддержка нескольких групп через запятую
raw_chats     = os.environ.get("TELEGRAM_CHAT_ID", "")
CHAT_IDS      = [cid.strip() for cid in raw_chats.split(",") if cid.strip()]

ZONE_NAME     = os.getenv("GARAGE_ZONE_NAME",    "БКС Гараж")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL",    "10"))
WARN_KM       = int(os.getenv("MAINTENANCE_WARN_KM", "500"))
WIALON_URL    = os.getenv("WIALON_URL", "https://2.smartgps.uz")
PORT          = int(os.getenv("PORT", "10000"))

# Local Uzbekistan Timezone (UTC+5)
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


# ──────────────────────────────────────────────────────────────────────────────
# Health check HTTP server (Supports GET and HEAD for UptimeRobot)
# ──────────────────────────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Garage Bot is running OK 24/7\n")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server():
    """Start lightweight background HTTP server on PORT for cloud health checks."""
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        log.info("Health-check HTTP server listening on port %d", PORT)
        server.serve_forever()
    except Exception as e:
        log.warning("HTTP health server error: %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# Card sending (Sends to ALL configured groups)
# ──────────────────────────────────────────────────────────────────────────────

async def send_card(bot: Bot, data: dict) -> None:
    img = render_card(data)
    for chat_id in CHAT_IDS:
        try:
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            await bot.send_photo(chat_id=chat_id, photo=buf)
            log.info("Card sent for '%s' to group %s", data.get("name"), chat_id)
        except Exception as te:
            log.error("Failed to send card to %s: %s", chat_id, te)


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    log.info("=== Garage Bot starting ===")
    log.info("Groups count: %d (%s)", len(CHAT_IDS), CHAT_IDS)
    log.info("Zone: %s | Poll: %ds | Warn at <= %d km", ZONE_NAME, POLL_INTERVAL, WARN_KM)

    # Start HTTP server in a separate daemon thread for Render health checks
    http_thread = threading.Thread(target=start_health_server, daemon=True)
    http_thread.start()

    bot    = Bot(token=TG_TOKEN)
    wialon = WialonClient(WIALON_TOKEN, base_url=WIALON_URL)
    db     = Database()

    # Login
    try:
        wialon.login()
    except Exception as exc:
        log.critical("Wialon login failed: %s", exc)
        return

    # Find geofence
    zone_id, zone = wialon.get_zone(ZONE_NAME)
    if zone is None:
        log.critical(
            "Zone '%s' not found. Check GARAGE_ZONE_NAME in .env", ZONE_NAME
        )
        return
    log.info("Geofence OK: '%s' (id=%s, points=%d)", zone.get("n"), zone_id, len(zone.get("p", [])))

    # Load saved state
    in_garage: set[int] = db.get_garage_state()
    is_initial_run = len(in_garage) == 0

    ping_tick = 0

    while True:
        try:
            ping_tick += 1
            if ping_tick % 10 == 0:
                wialon.ping()

            units   = wialon.get_units()
            current: set[int] = set()

            for unit in units:
                uid = unit.get("id")
                pos = wialon.get_unit_pos(unit)

                if not pos or pos[0] is None:
                    continue

                lat, lon = pos

                if wialon.is_in_zone(lat, lon, zone):
                    current.add(uid)

                    if uid not in in_garage:          # ← NEW ENTRY
                        log.info("ENTRY: %s (id=%d)", unit.get("nm"), uid)
                        if not is_initial_run:
                            try:
                                card_data = {
                                    "name"       : unit.get("nm", "Неизвестно"),
                                    "driver"     : wialon.get_driver(unit),
                                    "entry_time" : datetime.now(TZ_UZB),
                                    "last_exit"  : db.get_last_exit(uid),
                                    "fuel"       : wialon.get_fuel(unit),
                                    "mileage"    : wialon.get_mileage(unit),
                                    "maintenance": wialon.get_maintenance(unit),
                                    "warning_km" : WARN_KM,
                                    "garage_name": ZONE_NAME,
                                }
                                await send_card(bot, card_data)
                            except TelegramError as te:
                                log.error("Telegram error: %s", te)
                            except Exception as ce:
                                log.error("Card error for '%s': %s", unit.get("nm"), ce, exc_info=True)

                        db.record_entry(uid, unit.get("nm", ""))

                else:
                    if uid in in_garage:              # ← EXIT
                        log.info("EXIT: %s (id=%d)", unit.get("nm"), uid)
                        db.record_exit(uid, unit.get("nm", ""))

            in_garage = current
            db.save_garage_state(current)
            if is_initial_run:
                log.info("Initial sync done: %d units currently inside garage recorded in DB", len(in_garage))
                is_initial_run = False
            else:
                log.info("Poll cycle OK: %d units in garage", len(in_garage))

        except Exception as exc:
            log.error("Poll error: %s", exc, exc_info=True)
            try:
                wialon.login()
                zone_id, zone = wialon.get_zone(ZONE_NAME)
            except Exception as re_exc:
                log.error("Re-login failed: %s", re_exc)

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
