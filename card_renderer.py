from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# ──────────────────────────────────────────────────────────────────────────────
# Design tokens — Ultra readable, huge fonts, compact width so Telegram scales it big
# ──────────────────────────────────────────────────────────────────────────────
CARD_W   = 720
PAD      = 32

WHITE    = (255, 255, 255)
GRAY_BG  = (240, 242, 245)
BLACK    = (15,  23,  42)    # Deep solid black
DARK_LBL = (30,  41,  59)    # Solid dark for labels
GREEN    = (21,  128, 61)    # Deep green
GREEN_D  = (34,  197, 94)

# Overdue alert (Red)
RED_TEXT = (185, 28,  28)
RED_BG   = (254, 242, 242)
RED_BD   = (239, 68,  68)

# Warning alert (Amber / Yellow)
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


def _rr(draw: ImageDraw.Draw, box: List[int], r: int,
        fill=None, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def _fmt_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "нет данных"
    m = _MONTHS_RU[dt.month - 1]
    return f"{dt.day} {m} · {dt.strftime('%H:%M')}"


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def render_card(data: Dict[str, Any]) -> Image.Image:
    """
    Render a garage-entry notification card with huge, highly-legible text.
    """
    m_list: List[Dict] = data.get("maintenance") or []
    warn_km = int(data.get("warning_km", 500))

    # Categorize maintenance items
    overdue_items = [m for m in m_list if m.get("remaining_km", 0) < 0]
    warn_items    = [m for m in m_list if 0 <= m.get("remaining_km", 0) <= warn_km]
    normal_items  = [m for m in m_list if m.get("remaining_km", 0) > warn_km]

    # Huge Fonts
    F = {
        "title"    : _font(34, bold=True),
        "driver"   : _font(25, bold=True),
        "online"   : _font(24, bold=True),
        "status"   : _font(22, bold=True),
        "time"     : _font(22, bold=True),
        "alert_t"  : _font(21, bold=True),
        "box_lbl"  : _font(20, bold=True),
        "box_val"  : _font(30, bold=True),
        "m_hdr"    : _font(23, bold=True),
        "m_name"   : _font(21, bold=True),
        "m_val"    : _font(21, bold=True),
        "footer"   : _font(20, bold=True),
    }

    # ── Alerts calculation ───────────────────────────────────────────────────
    alert_rows = []
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
    H_HEADER = 100
    H_STATUS = 80
    H_BOXES  = 130
    H_ALERTS = len(alert_rows) * 72 if alert_rows else 0

    display_si = (overdue_items + warn_items + normal_items)[:7]
    H_SI_SECTION = (50 + len(display_si) * 40 + 16) if display_si else 0

    H_FOOT = 54

    total_h = (
        PAD + H_HEADER + 18 + H_STATUS + 14
        + H_ALERTS
        + H_BOXES + 24
        + H_SI_SECTION
        + H_FOOT + PAD
    )

    img  = Image.new("RGB", (CARD_W, total_h), GRAY_BG)
    draw = ImageDraw.Draw(img)

    # Card outer rounded border
    _rr(draw, [0, 0, CARD_W - 1, total_h - 1], r=20, fill=WHITE, outline=CARD_BD, width=3)

    y = PAD

    # ════ 1. HEADER (Vehicle Name + Driver) ═══════════════════════════════════
    name = data.get("name", "Неизвестно")
    drv  = data.get("driver", "Не назначен")

    draw.text((PAD, y), name, font=F["title"], fill=BLACK)
    y += 46
    draw.text((PAD, y), f"Водитель: {drv}", font=F["driver"], fill=DARK_LBL)
    y += 44
    draw.line([(PAD, y), (CARD_W - PAD, y)], fill=SEP, width=2)
    y += 18

    # ════ 2. STATUS (online + timestamp) ══════════════════════════════════════
    R = 10
    draw.ellipse([PAD, y + 4, PAD + R * 2, y + 4 + R * 2], fill=GREEN_D)
    draw.text((PAD + R * 2 + 12, y), "online", font=F["online"], fill=GREEN)

    entry_str = _fmt_date(data.get("entry_time", datetime.now()))
    tw = draw.textlength(entry_str, font=F["time"])
    draw.text((CARD_W - PAD - tw, y), entry_str, font=F["time"], fill=BLACK)
    y += 38

    draw.text((PAD, y), "въехал в гараж", font=F["status"], fill=BLACK)
    y += 36

    # ════ 3. ALERTS (Overdue in RED, Warning in YELLOW) ════════════════════════
    for text, bg_col, bd_col, txt_col in alert_rows:
        lines = text.split("\n")
        box_h = 64 if len(lines) > 1 else 46
        box_rect = [PAD, y, CARD_W - PAD, y + box_h]
        _rr(draw, box_rect, r=10, fill=bg_col, outline=bd_col, width=2)
        if len(lines) > 1:
            draw.text((PAD + 16, y + 8), lines[0], font=F["alert_t"], fill=txt_col)
            draw.text((PAD + 16, y + 34), lines[1], font=F["alert_t"], fill=txt_col)
        else:
            draw.text((PAD + 16, y + 10), lines[0], font=F["alert_t"], fill=txt_col)
        y += box_h + 12

    # ════ 4. MAIN STAT BOXES (Fuel, Mileage, Last Exit) ═══════════════════════
    gap = 12
    bw  = (CARD_W - 2 * PAD - 2 * gap) // 3
    by  = y

    boxes = _build_boxes(data)
    for i, (label, value) in enumerate(boxes):
        bx = PAD + i * (bw + gap)
        _rr(draw, [bx, by, bx + bw, by + H_BOXES], r=12, fill=BOX_BG, outline=BOX_BD, width=2)
        draw.text((bx + 14, by + 16), label, font=F["box_lbl"], fill=DARK_LBL)
        draw.text((bx + 14, by + 58), value, font=F["box_val"], fill=BLACK)

    y = by + H_BOXES + 24

    # ════ 5. ALL MAINTENANCE INTERVALS SECTION ════════════════════════════════
    if display_si:
        draw.line([(PAD, y), (CARD_W - PAD, y)], fill=SEP, width=2)
        y += 18

        draw.text((PAD, y), "СЕРВИСНЫЕ ИНТЕРВАЛЫ И ТО:", font=F["m_hdr"], fill=BLACK)
        y += 38

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
            y += 40

        y += 10

    # ════ 6. FOOTER ═══════════════════════════════════════════════════════════
    draw.line([(PAD, y), (CARD_W - PAD, y)], fill=SEP, width=2)
    y += 16

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
