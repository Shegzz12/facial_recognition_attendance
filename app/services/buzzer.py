"""
buzzer.py
---------
Drives an active buzzer on a GPIO pin to give audible scan feedback.
Safe to import on a non-Pi machine (or with no buzzer wired) — it falls back
to a no-op so the rest of the app keeps working.

Wiring (Raspberry Pi 40-pin header, active buzzer module):
    Buzzer VCC/+  -> Pi Pin 2  (5V)   [or 3V3 for 3.3V modules]
    Buzzer GND/-  -> Pi Pin 9  (GND)
    Buzzer I/O S  -> Pi Pin 12 (GPIO18)

Override via environment variables if needed:
    export BUZZER_GPIO_PIN=18        # BCM numbering
    export BUZZER_ACTIVE_HIGH=1      # 0 if your module sounds when pulled LOW
    export BUZZER_ENABLED=1          # 0 to disable the buzzer entirely

Patterns (each one pre-empts whatever is currently playing):
    beep_success()  3 short beeps, then silence
    beep_error()    one continuous 5-second beep, then silence
    alarm()         repeating beeps that keep going until stop() is called
    stop()          silence now

Ownership: every call takes an ``owner`` string (e.g. "camera" / "rfid") so the
camera scanner stopping its own alert can never silence an alarm the RFID
scanner is still holding, and vice versa.
"""

from __future__ import annotations

import os
import threading

BUZZER_GPIO_PIN = int(os.environ.get("BUZZER_GPIO_PIN", "18"))
BUZZER_ACTIVE_HIGH = os.environ.get("BUZZER_ACTIVE_HIGH", "1") not in ("0", "false", "False")
BUZZER_ENABLED = os.environ.get("BUZZER_ENABLED", "1") not in ("0", "false", "False")

SUCCESS_BEEPS = 3
SUCCESS_ON_SECONDS = 0.12
SUCCESS_OFF_SECONDS = 0.12

ERROR_ON_SECONDS = float(os.environ.get("BUZZER_ERROR_SECONDS", "5.0"))

ALARM_ON_SECONDS = 0.4
ALARM_OFF_SECONDS = 0.25

_backend = None  # "rpi_gpio" | "gpiozero" | None
_gpio = None
_gz_buzzer = None

if BUZZER_ENABLED:
    try:
        import RPi.GPIO as GPIO  # type: ignore

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(BUZZER_GPIO_PIN, GPIO.OUT)
        GPIO.output(BUZZER_GPIO_PIN, GPIO.LOW if BUZZER_ACTIVE_HIGH else GPIO.HIGH)
        _gpio = GPIO
        _backend = "rpi_gpio"
    except Exception as exc:  # pragma: no cover - hardware-dependent
        try:
            from gpiozero import Buzzer  # type: ignore

            _gz_buzzer = Buzzer(BUZZER_GPIO_PIN, active_high=BUZZER_ACTIVE_HIGH)
            _backend = "gpiozero"
        except Exception as exc2:  # pragma: no cover - hardware-dependent
            print(f"[buzzer] not available, continuing without it: {exc} / {exc2}")

BUZZER_AVAILABLE = _backend is not None

_lock = threading.Lock()
_owner: str | None = None
_pattern: str | None = None
_cancel = threading.Event()


def _set_output(on: bool) -> None:
    try:
        if _backend == "rpi_gpio" and _gpio is not None:
            level = (_gpio.HIGH if on else _gpio.LOW) if BUZZER_ACTIVE_HIGH else (
                _gpio.LOW if on else _gpio.HIGH
            )
            _gpio.output(BUZZER_GPIO_PIN, level)
        elif _backend == "gpiozero" and _gz_buzzer is not None:
            if on:
                _gz_buzzer.on()
            else:
                _gz_buzzer.off()
    except Exception as exc:  # pragma: no cover - hardware-dependent
        print(f"[buzzer] output failed: {exc}")


def _play(steps: list[tuple[float, float]], repeat: bool, cancel: threading.Event) -> None:
    try:
        while True:
            for on_seconds, off_seconds in steps:
                _set_output(True)
                if cancel.wait(on_seconds):
                    return
                _set_output(False)
                if off_seconds and cancel.wait(off_seconds):
                    return
            if not repeat:
                return
    finally:
        _set_output(False)
        with _lock:
            global _owner, _pattern
            if _cancel is cancel:
                _owner = None
                _pattern = None


def _start(owner: str, pattern: str, steps: list[tuple[float, float]], repeat: bool) -> None:
    if not BUZZER_AVAILABLE:
        return
    global _cancel, _owner, _pattern
    with _lock:
        # An alarm already sounding for this owner just keeps sounding — restarting
        # it every poll would chop the tone into stutters.
        if repeat and _owner == owner and _pattern == pattern:
            return
        _cancel.set()
        cancel = threading.Event()
        _cancel = cancel
        _owner = owner
        _pattern = pattern
    threading.Thread(target=_play, args=(steps, repeat, cancel), daemon=True).start()


def beep_success(owner: str) -> None:
    """Three short beeps — attendance marked."""
    _start(owner, "success", [(SUCCESS_ON_SECONDS, SUCCESS_OFF_SECONDS)] * SUCCESS_BEEPS, False)


def beep_error(owner: str) -> None:
    """One continuous 5-second beep — not recognized / mark failed."""
    _start(owner, "error", [(ERROR_ON_SECONDS, 0.0)], False)


def alarm(owner: str) -> None:
    """Repeating beeps that keep sounding until stop() — duplicate scan."""
    _start(owner, "alarm", [(ALARM_ON_SECONDS, ALARM_OFF_SECONDS)], True)


def stop(owner: str | None = None) -> None:
    """Silence the buzzer. With an owner, only silences that owner's pattern."""
    if not BUZZER_AVAILABLE:
        return
    global _owner, _pattern
    with _lock:
        if owner is not None and _owner is not None and _owner != owner:
            return
        _cancel.set()
        _owner = None
        _pattern = None
    _set_output(False)


def is_active(owner: str | None = None) -> bool:
    with _lock:
        if owner is None:
            return _pattern is not None
        return _owner == owner and _pattern is not None
