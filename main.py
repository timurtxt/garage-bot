import asyncio
import io
import logging
import os
from datetime import datetime

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
CHAT_ID       = os.environ["TELEGRAM_CHAT_ID"]
ZONE_NAME     = os.getenv("GARAGE_ZONE_NAME",    "БКС Гараж")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL",    "60"))
WARN_KM       = int(os.getenv("MAINTENANCE_WARN_KM", "500"))
WIALON_URL    = os.getenv("WIALON_URL", "https://2.smartgps.uz")

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
# Card sending
# ──────────────────────────────────────────────────────────────────────────────

async def send_card(bot: Bot, data: dict) -> None:
    img = render_card(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    caption = f"Въезд в гараж: {data.get('name', 'ТС')}"
    await bot.send_photo(chat_id=CHAT_ID, photo=buf, caption=caption)
    log.info("Card sent for '%s'", data.get("name"))


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    log.info("=== Garage Bot starting ===")
    log.info("Zone: %s | Poll: %ds | Warn at <= %d km", ZONE_NAME, POLL_INTERVAL, WARN_KM)

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
                                    "entry_time" : datetime.now(),
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
