from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# Local Timezone UTC+5 (Uzbekistan / Tashkent / Samarkand)
TZ_UZB = timezone(timedelta(hours=5))

def now_uzb() -> datetime:
    return datetime.now(TZ_UZB)

# ──────────────────────────────────────────────────────────────────────────────
# Design tokens — Ultra readable, high contrast, auto-fitting fonts
# ──────────────────────────────────────────────────────────────────────────────
CARD_W   = 760
PAD      = 32

WHITE    = (255, 255, 255)
GRAY_BG  = (240, 242, 245)
BLACK    = (15,  23,  42)    # Deep solid black
DARK_LBL = (30,  41,  59)    # Solid dark for labels
GREEN    = (21,  128, 61)    # Deep green
GREEN_D  = (34,  197, 94)

# Overdue / >4 days alert (Red)
RED_TEXT = (185, 28,  28)
RED_BG   = (254, 242, 242)
RED_BD   = (239, 68,  68)

# Warning / 3 days alert (Amber / Yellow)
WARN_TXT = (180, 83,  9)
WARN_BG  = (254, 243, 199)
WARN_BD  = (245, 158, 11)

# Boxes & Dividers
BOX_BG   = (248, 250, 252)
BOX_BD   = (203, 213, 225)
SEP      = (203, 213, 225)
CARD_BD  = (148, 163, 184)

_MONTHS_RU = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/calibrib.ttf", "C:/Windows/Fonts/segoeuib.ttf"]
        if bold else
        ["C:/Windows/Fonts/arial.ttf",   "C:/Windows/Fonts/Arial.ttf", "C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/segoeui.ttf"]
    ) + [
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _get_fitted_font(text: str, max_w: int, max_size: int = 30, min_size: int = 18, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Find the largest font size so text fits within max_w pixels."""
    dummy_img = Image.new("RGB", (10, 10))
    dummy_draw = ImageDraw.Draw(dummy_img)
    for sz in range(max_size, min_size - 1, -1):
        f = _font(sz, bold=bold)
        if dummy_draw.textlength(text, font=f) <= max_w:
            return f
    return _font(min_size, bold=bold)


def _rr(draw: ImageDraw.Draw, box: List[int], r: int,
        fill=None, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def _fmt_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "нет данных"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(TZ_UZB)
    else:
        dt = dt.astimezone(TZ_UZB)
    m = _MONTHS_RU[dt.month - 1]
    return f"{dt.day} {m} · {dt.strftime('%H:%M')}"


def _draw_wash_icon(draw: ImageDraw.Draw, x: int, y: int, color: tuple):
    """Draw a clean car wash shower icon at (x, y)."""
    draw.arc([x, y, x + 18, y + 18], start=180, end=360, fill=color, width=2)
    draw.line([(x + 9, y), (x + 9, y - 5), (x + 20, y - 5)], fill=color, width=2)
    draw.line([(x + 3, y + 20), (x + 1, y + 28)], fill=color, width=2)
    draw.line([(x + 9, y + 20), (x + 9, y + 29)], fill=color, width=2)
    draw.line([(x + 15, y + 20), (x + 17, y + 28)], fill=color, width=2)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def render_card(data: Dict[str, Any]) -> Image.Image:
    """
    Render a garage-entry notification card with local UTC+5 timezone,
    auto-fitted fonts, exit-to-entry duration highlights, and wash banner.
    """
    m_list: List[Dict] = data.get("maintenance") or []
    warn_km = int(data.get("warning_km", 500))

    # Categorize maintenance items
    overdue_items = [m for m in m_list if m.get("remaining_km", 0) < 0]
    warn_items    = [m for m in m_list if 0 <= m.get("remaining_km", 0) <= warn_km]
    normal_items  = [m for m in m_list if m.get("remaining_km", 0) > warn_km]

    # Calculate trip duration between last exit and current entry in UTC+5
    entry_time = data.get("entry_time") or now_uzb()
    last_exit  = data.get("last_exit")

    trip_days = 0.0
    trip_str = ""
    exit_status = "normal"  # normal | yellow | red

    if last_exit:
        t_entry = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=TZ_UZB)
        t_exit  = last_exit if last_exit.tzinfo else last_exit.replace(tzinfo=TZ_UZB)
        delta   = t_entry - t_exit
        trip_days = delta.total_seconds() / 86400.0
        days_int = int(delta.days)
        hours_int = int(delta.seconds // 3600)
        if days_int > 0:
            trip_str = f"{days_int} сут {hours_int} ч"
        else:
            trip_str = f"{hours_int} ч"

        if trip_days >= 4.0:
            exit_status = "red"
        elif trip_days >= 3.0:
            exit_status = "yellow"

    # Name and driver
    raw_name = data.get("name", "Неизвестно")
    drv      = data.get("driver", "Не назначен")

    # Title auto-fitting to card width
    max_title_w = CARD_W - 2 * PAD
    F_title  = _get_fitted_font(raw_name, max_title_w, max_size=28, min_size=18, bold=True)
    F_driver = _get_fitted_font(f"Водитель: {drv}", max_title_w, max_size=23, min_size=17, bold=True)

    F = {
        "online"   : _font(23, bold=True),
        "status"   : _font(21, bold=True),
        "time"     : _font(21, bold=True),
        "alert_t"  : _font(20, bold=True),
        "box_lbl"  : _font(19, bold=True),
        "box_val"  : _font(27, bold=True),
        "box_sub"  : _font(18, bold=True),
        "m_hdr"    : _font(22, bold=True),
        "m_name"   : _font(20, bold=True),
        "m_val"    : _font(20, bold=True),
        "wash_lbl" : _font(21, bold=True),
        "footer"   : _font(19, bold=True),
    }

    # ── Alerts calculation ───────────────────────────────────────────────────
    alert_rows = []

    if exit_status == "red":
        alert_rows.append((
            f"⚠ В РЕЙСЕ БОЛЕЕ 4 СУТОК: {trip_str}\nВыезд был: {_fmt_date(last_exit)}",
            RED_BG, RED_BD, RED_TEXT
        ))
    elif exit_status == "yellow":
        alert_rows.append((
            f"⚠ В РЕЙСЕ БОЛЕЕ 3 СУТОК: {trip_str}\nВыезд был: {_fmt_date(last_exit)}",
            WARN_BG, WARN_BD, WARN_TXT
        ))

    for item in overdue_items:
        rem = item["remaining_km"]
        alert_rows.append((
            f"⚠ ПРОСРОЧЕНО: {item['name']}\nна {abs(rem):,.0f} км ({rem:+,.0f} км)".replace(",", " "),
            RED_BG, RED_BD, RED_TEXT
        ))
    for item in warn_items:
        rem = item["remaining_km"]
        alert_rows.append((
            f"⚠ ТО ПОДОШЛО: {item['name']}\nосталось {rem:,.0f} км".replace(",", " "),
            WARN_BG, WARN_BD, WARN_TXT
        ))

    # ── Height budget calculation ─────────────────────────────────────────────
    H_HEADER = 94
    H_STATUS = 76
    H_BOXES  = 134
    H_ALERTS = len(alert_rows) * 74 if alert_rows else 0

    display_si = (overdue_items + warn_items + normal_items)[:7]
    H_SI_SECTION = (46 + len(display_si) * 38 + 14) if display_si else 0

    H_WASH_SECTION = 64
    H_FOOT = 50

    total_h = (
        PAD + H_HEADER + 16 + H_STATUS + 12
        + H_ALERTS
        + H_BOXES + 20
        + H_WASH_SECTION + 16
        + H_SI_SECTION
        + H_FOOT + PAD
    )

    img  = Image.new("RGB", (CARD_W, total_h), GRAY_BG)
    draw = ImageDraw.Draw(img)

    # Card outer rounded border
    _rr(draw, [0, 0, CARD_W - 1, total_h - 1], r=20, fill=WHITE, outline=CARD_BD, width=3)

    y = PAD

    # ════ 1. HEADER (Vehicle Name + Driver) ═══════════════════════════════════
    draw.text((PAD, y), raw_name, font=F_title, fill=BLACK)
    y += 42
    draw.text((PAD, y), f"Водитель: {drv}", font=F_driver, fill=DARK_LBL)
    y += 40
    draw.line([(PAD, y), (CARD_W - PAD, y)], fill=SEP, width=2)
    y += 16

    # ════ 2. STATUS (online + local timestamp) ════════════════════════════════
    R = 9
    draw.ellipse([PAD, y + 4, PAD + R * 2, y + 4 + R * 2], fill=GREEN_D)
    draw.text((PAD + R * 2 + 10, y), "online", font=F["online"], fill=GREEN)

    entry_str = f"Въезд: {_fmt_date(entry_time)}"
    tw = draw.textlength(entry_str, font=F["time"])
    draw.text((CARD_W - PAD - tw, y), entry_str, font=F["time"], fill=BLACK)
    y += 36

    draw.text((PAD, y), "въехал в гараж", font=F["status"], fill=BLACK)
    y += 34

    # ════ 3. ALERTS (Duration & Overdues) ═════════════════════════════════════
    for text, bg_col, bd_col, txt_col in alert_rows:
        lines = text.split("\n")
        box_h = 66 if len(lines) > 1 else 44
        box_rect = [PAD, y, CARD_W - PAD, y + box_h]
        _rr(draw, box_rect, r=10, fill=bg_col, outline=bd_col, width=2)
        if len(lines) > 1:
            draw.text((PAD + 16, y + 8), lines[0], font=F["alert_t"], fill=txt_col)
            draw.text((PAD + 16, y + 34), lines[1], font=F["alert_t"], fill=txt_col)
        else:
            draw.text((PAD + 16, y + 10), lines[0], font=F["alert_t"], fill=txt_col)
        y += box_h + 12

    # ════ 4. MAIN STAT BOXES (Fuel, Mileage, Last Exit with Color Highlight) ════
    gap = 12
    bw  = (CARD_W - 2 * PAD - 2 * gap) // 3
    by  = y

    # Box 1 – Fuel
    fuel = data.get("fuel")
    if fuel and fuel.get("level") is not None:
        lvl = fuel.get("level", 0)
        pct = fuel.get("pct")
        fval = f"{lvl:.0f} л"
        fsub = f"{pct:.0f}% бака" if pct is not None else ""
    else:
        fval = "нет ДУТ"
        fsub = ""

    # Box 2 – Mileage
    mi = data.get("mileage")
    mval = f"{mi:,.0f} км".replace(",", " ") if mi is not None else "нет данных"
    msub = "одометр"

    # Box 3 – Last Exit (Colored by duration!)
    exval = _fmt_date(last_exit)
    exsub = f"в рейсе: {trip_str}" if trip_str else "выезд"

    if exit_status == "red":
        b3_bg, b3_bd, b3_txt, b3_sub_col = RED_BG, RED_BD, RED_TEXT, RED_TEXT
    elif exit_status == "yellow":
        b3_bg, b3_bd, b3_txt, b3_sub_col = WARN_BG, WARN_BD, WARN_TXT, WARN_TXT
    else:
        b3_bg, b3_bd, b3_txt, b3_sub_col = BOX_BG, BOX_BD, BLACK, DARK_LBL

    # Draw Box 1
    bx1 = PAD
    _rr(draw, [bx1, by, bx1 + bw, by + H_BOXES], r=12, fill=BOX_BG, outline=BOX_BD, width=2)
    draw.text((bx1 + 14, by + 14), "Топливо:", font=F["box_lbl"], fill=DARK_LBL)
    draw.text((bx1 + 14, by + 46), fval, font=F["box_val"], fill=BLACK)
    if fsub:
        draw.text((bx1 + 14, by + 90), fsub, font=F["box_sub"], fill=DARK_LBL)

    # Draw Box 2
    bx2 = PAD + bw + gap
    _rr(draw, [bx2, by, bx2 + bw, by + H_BOXES], r=12, fill=BOX_BG, outline=BOX_BD, width=2)
    draw.text((bx2 + 14, by + 14), "Пробег:", font=F["box_lbl"], fill=DARK_LBL)
    draw.text((bx2 + 14, by + 46), mval, font=F["box_val"], fill=BLACK)
    draw.text((bx2 + 14, by + 90), msub, font=F["box_sub"], fill=DARK_LBL)

    # Draw Box 3 (Highlighted if >= 3 or 4 days)
    bx3 = PAD + 2 * (bw + gap)
    _rr(draw, [bx3, by, bx3 + bw, by + H_BOXES], r=12, fill=b3_bg, outline=b3_bd, width=3 if exit_status != "normal" else 2)
    draw.text((bx3 + 14, by + 14), "Посл. выезд:", font=F["box_lbl"], fill=b3_sub_col)
    draw.text((bx3 + 14, by + 46), exval, font=F["box_val"], fill=b3_txt)
    draw.text((bx3 + 14, by + 90), exsub, font=F["box_sub"], fill=b3_sub_col)

    y = by + H_BOXES + 20

    # ════ 5. CAR WASH BANNER SECTION ═════════════════════════════════════════
    if trip_days >= 4.0:
        wash_bg  = RED_BG
        wash_bd  = RED_BD
        wash_txt = RED_TEXT
        wash_text = "МОЙКА МАШИНЫ: ТРЕБУЕТСЯ ПОМЫТЬ АВТОМОБИЛЬ"
    else:
        wash_bg  = (240, 253, 244)  # Light soft green
        wash_bd  = (134, 239, 172)  # Soft green border
        wash_txt = (21, 128, 61)    # Deep green text
        wash_text = "МОЙКА МАШИНЫ: НЕ ТРЕБУЕТСЯ"

    w_box = [PAD, y, CARD_W - PAD, y + 52]
    _rr(draw, w_box, r=10, fill=wash_bg, outline=wash_bd, width=2)

    # Draw clean wash shower icon
    _draw_wash_icon(draw, PAD + 16, y + 12, wash_txt)
    draw.text((PAD + 52, y + 14), wash_text, font=F["wash_lbl"], fill=wash_txt)
    y += 52 + 18

    # ════ 6. ALL MAINTENANCE INTERVALS SECTION ════════════════════════════════
    if display_si:
        draw.line([(PAD, y), (CARD_W - PAD, y)], fill=SEP, width=2)
        y += 16

        draw.text((PAD, y), "СЕРВИСНЫЕ ИНТЕРВАЛЫ И ТО:", font=F["m_hdr"], fill=BLACK)
        y += 34

        for item in display_si:
            nm  = item.get("name", "ТО")
            rem = item.get("remaining_km", 0)

            if rem < 0:
                val_str = f"{rem:+,.0f} км (ПРОСРОЧЕНО)".replace(",", " ")
                val_col = RED_TEXT
            elif rem <= warn_km:
                val_str = f"{rem:,.0f} км (СКОРО ТО)".replace(",", " ")
                val_col = WARN_TXT
            else:
                val_str = f"через {rem:,.0f} км".replace(",", " ")
                val_col = BLACK

            draw.text((PAD + 8, y), f"• {nm}", font=F["m_name"], fill=BLACK)
            v_width = draw.textlength(val_str, font=F["m_val"])
            draw.text((CARD_W - PAD - v_width - 8, y), val_str, font=F["m_val"], fill=val_col)
            y += 38

        y += 8

    # ════ 7. FOOTER ═══════════════════════════════════════════════════════════
    draw.line([(PAD, y), (CARD_W - PAD, y)], fill=SEP, width=2)
    y += 14

    draw.ellipse([PAD, y + 6, PAD + 12, y + 18], fill=BLACK)
    draw.text(
        (PAD + 22, y),
        f"{data.get('garage_name', 'БКС Гараж')} · Автопарк",
        font=F["footer"],
        fill=BLACK,
    )

    return img


def _build_boxes(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    # Box 1 – Fuel
    fuel = data.get("fuel")
    if fuel and fuel.get("level") is not None:
        lvl = fuel.get("level", 0)
        pct = fuel.get("pct")
        fval = f"{lvl:.0f} л · {pct:.0f}%" if pct is not None else f"{lvl:.0f} л"
    else:
        fval = "нет датчика"

    # Box 2 – Mileage
    mi = data.get("mileage")
    mval = f"{mi:,.0f} км".replace(",", " ") if mi is not None else "нет данных"

    # Box 3 – Last exit
    exval = _fmt_date(data.get("last_exit"))

    return [
        ("Топливо:", fval),
        ("Пробег:",  mval),
        ("Выезд:",   exval),
    ]
