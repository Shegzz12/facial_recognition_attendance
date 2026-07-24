"""
lcd_display.py
--------------
Drives a 16x2 character LCD over I2C (PCF8574 backpack) to show live
attendance-scanning status. Safe to import even if no LCD is attached, or on
a non-Pi dev machine — falls back to a no-op so the rest of the app keeps working.

Wiring (Raspberry Pi 40-pin header):
    LCD VCC -> Pi Pin 4  (5V)
    LCD GND -> Pi Pin 6  (GND)
    LCD SDA -> Pi Pin 3  (GPIO2 / SDA1)
    LCD SCL -> Pi Pin 5  (GPIO3 / SCL1)

Find your LCD's I2C address with: i2cdetect -y 1
Default assumed here is 0x27 (the other common one is 0x3F).
Override via environment variable if needed:
    export LCD_I2C_ADDRESS=0x3f
"""

from __future__ import annotations

import os
import threading

LCD_COLS = 16
LCD_ROWS = 2
LCD_I2C_ADDRESS = int(os.environ.get("LCD_I2C_ADDRESS", "0x27"), 16)
LCD_I2C_PORT = int(os.environ.get("LCD_I2C_PORT", "1"))

_lcd = None
_lcd_lock = threading.Lock()
LCD_AVAILABLE = False

try:
    from RPLCD.i2c import CharLCD

    _lcd = CharLCD(
        i2c_expander="PCF8574",
        address=LCD_I2C_ADDRESS,
        port=LCD_I2C_PORT,
        cols=LCD_COLS,
        rows=LCD_ROWS,
        dotsize=8,
        charmap="A00",
        auto_linebreaks=False,
    )
    LCD_AVAILABLE = True
except Exception as exc:  # pragma: no cover - hardware-dependent
    print(f"[lcd] LCD not available, continuing without it: {exc}")
    _lcd = None
    LCD_AVAILABLE = False


def _pad(text: str) -> str:
    text = (text or "")[:LCD_COLS]
    return text.ljust(LCD_COLS)


def lcd_write(line1: str = "", line2: str = "") -> None:
    """Write two lines to the LCD. No-op if no LCD is attached."""
    if not LCD_AVAILABLE or _lcd is None:
        return
    try:
        with _lcd_lock:
            _lcd.cursor_pos = (0, 0)
            _lcd.write_string(_pad(line1))
            _lcd.cursor_pos = (1, 0)
            _lcd.write_string(_pad(line2))
    except Exception as exc:  # pragma: no cover - hardware-dependent
        print(f"[lcd] write failed: {exc}")


def lcd_clear() -> None:
    if not LCD_AVAILABLE or _lcd is None:
        return
    try:
        with _lcd_lock:
            _lcd.clear()
    except Exception as exc:
        print(f"[lcd] clear failed: {exc}")


def lcd_idle() -> None:
    lcd_write("Attendance Sys", "Ready")


def lcd_scanning() -> None:
    lcd_write("Scanning Faces", "Please Look Up")


def lcd_no_face() -> None:
    lcd_write("Scanning Faces", "No Face Seen")


def lcd_not_recognized() -> None:
    lcd_write("Face Not", "Recognized")


def lcd_marked(full_name: str) -> None:
    # "Attendance Marked" is 17 chars — one over the 16-col display — so this
    # uses "Attendance Mark" (15 chars) to avoid it getting clipped mid-word.
    lcd_write(full_name, "Attendance Mark")


def lcd_already_marked(full_name: str) -> None:
    lcd_write(full_name, "Duplicate Mark")


def lcd_error(message: str) -> None:
    lcd_write("Scan error", message)


def lcd_card_not_recognized() -> None:
    lcd_write("Card Not", "Recognized")


def lcd_card_registered(full_name: str) -> None:
    lcd_write(full_name, "Card Registered")


def lcd_card_already_registered() -> None:
    lcd_write("Card Already", "Registered")