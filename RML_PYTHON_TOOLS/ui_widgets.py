# ui_widgets.py
# Shared date-masking / age-calculation helpers, lifted out of gait_graph_ui.py
# so every screen (gait_graph_ui, patient_manager_ui, patient_store) uses one
# implementation instead of each reinventing MM/DD/YYYY parsing.

from __future__ import annotations
import tkinter as tk
from datetime import datetime, date
from typing import Optional


def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def mask_mdy_from_digits(digs: str) -> str:
    """
    Takes up to 8 digits and returns a masked MM/DD/YYYY string.
    Examples:
      "0" -> "0"
      "02" -> "02"
      "021" -> "02/1"
      "0214" -> "02/14"
      "02142" -> "02/14/2"
      "02142015" -> "02/14/2015"
    """
    digs = digs[:8]
    if len(digs) <= 2:
        return digs
    if len(digs) <= 4:
        return digs[:2] + "/" + digs[2:]
    return digs[:2] + "/" + digs[2:4] + "/" + digs[4:]


def parse_mdy_masked(s: str) -> Optional[date]:
    """Parse strictly MM/DD/YYYY (masked) once complete."""
    s = (s or "").strip()
    if len(s) != 10:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None


def age_years_int(birth: date, on_date: date) -> int:
    """Whole years, birthday-aware."""
    years = on_date.year - birth.year
    if (on_date.month, on_date.day) < (birth.month, birth.day):
        years -= 1
    return max(years, 0)


def iso_to_mdy(iso: str) -> str:
    """'2026-08-14' -> '08/14/2026'. Returns '' on bad/empty input."""
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return ""
    return d.strftime("%m/%d/%Y")


def mdy_to_iso(mdy: str) -> str:
    """'08/14/2026' -> '2026-08-14'. Returns '' on bad/incomplete input."""
    d = parse_mdy_masked(mdy)
    return d.isoformat() if d else ""


def _cursor_index_for_digit_count(masked: str, digit_count: int) -> int:
    """Index into `masked` right after its `digit_count`-th digit. Used to keep the
    caret sitting on the same logical digit after auto-slashes reflow the string,
    instead of always snapping to the end."""
    if digit_count <= 0:
        return 0
    seen = 0
    for i, ch in enumerate(masked):
        if ch.isdigit():
            seen += 1
            if seen == digit_count:
                return i + 1
    return len(masked)


def _remask_preserving_cursor(entry, var) -> None:
    """Re-derives the masked MM/DD/YYYY text from `var` and, if it changed, rewrites it
    and moves the caret back to a sensible spot. For a forward append (the dominant
    case -- typing a date left-to-right into an empty/partial field), the caret snaps
    to the very end of the reflowed string. For a genuine mid-string edit -- e.g. fixing
    just the day in an already-filled date -- it counts digits so the caret stays near
    the same logical digit instead of jumping to the end.

    The icursor() call is deferred with after_idle(), not called inline: this trace
    fires WHILE the Entry widget is still partway through processing its own keystroke
    (e.g. .insert()), so its on-screen display hasn't caught up with `var` yet even
    though var.set() above already changed the value. Calling icursor() against that
    stale, shorter display silently clamps the target position down to the display's
    OLD length -- which is exactly the "caret ends up behind the digit just typed" bug.
    Waiting for the next idle pass lets the widget finish syncing its display first."""
    raw = var.get()
    cursor = entry.index("insert")
    was_append = cursor >= len(raw) - 1
    digits_before_cursor = len(digits_only(raw[:cursor]))
    digs = digits_only(raw)
    masked = mask_mdy_from_digits(digs)
    if raw != masked:
        var.set(masked)
        target = len(masked) if was_append else _cursor_index_for_digit_count(masked, digits_before_cursor)
        entry.after_idle(lambda: entry.icursor(target))


def attach_mdy_mask(entry, var, on_change=None, call_on_init: bool = False):
    """
    Enforces on a Tkinter Entry/StringVar pair:
      - digits only
      - auto slashes for MM/DD/YYYY
      - max 8 digits (plus slashes)

    call_on_init:
      - False (default): don't call on_change during initial sanitize (prevents build-order crashes)
      - True: call on_change when first attaching
    """
    state = {"in_trace": False}

    def _sync(*_):
        if state["in_trace"]:
            return
        state["in_trace"] = True
        try:
            _remask_preserving_cursor(entry, var)
            if on_change:
                on_change()
        finally:
            state["in_trace"] = False

    var.trace_add("write", _sync)

    if call_on_init:
        _sync()
    else:
        state["in_trace"] = True
        try:
            _remask_preserving_cursor(entry, var)
        finally:
            state["in_trace"] = False


class PlaceholderField:
    """Grey hint text shown in an Entry when it's empty and unfocused. get()/set()
    always deal in the REAL value -- callers never see or write the placeholder
    text itself, so there's no risk of it leaking into saved data."""

    def __init__(self, entry: tk.Entry, var: tk.StringVar, placeholder: str):
        self._entry = entry
        self._var = var
        self._placeholder = placeholder
        self._normal_fg = entry.cget("foreground")
        self._placeholder_fg = "#999999"
        self._showing_placeholder = False

        entry.bind("<FocusIn>", self._on_focus_in)
        entry.bind("<FocusOut>", self._on_focus_out)
        self._show_if_empty()

    def _show_if_empty(self):
        if not self._var.get():
            self._showing_placeholder = True
            self._entry.configure(foreground=self._placeholder_fg)
            self._var.set(self._placeholder)

    def _on_focus_in(self, _event=None):
        if self._showing_placeholder:
            self._showing_placeholder = False
            self._entry.configure(foreground=self._normal_fg)
            self._var.set("")

    def _on_focus_out(self, _event=None):
        self._show_if_empty()

    def get(self) -> str:
        return "" if self._showing_placeholder else self._var.get()

    def set(self, text: str) -> None:
        text = text or ""
        self._showing_placeholder = False
        self._entry.configure(foreground=self._normal_fg)
        if text:
            self._var.set(text)
        else:
            self._var.set("")
            self._show_if_empty()


def attach_placeholder(entry: tk.Entry, var: tk.StringVar, placeholder: str) -> PlaceholderField:
    return PlaceholderField(entry, var, placeholder)
