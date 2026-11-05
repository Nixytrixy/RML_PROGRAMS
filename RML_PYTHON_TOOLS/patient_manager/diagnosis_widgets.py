# diagnosis_widgets.py
# Reusable Tkinter widgets for picking/entering a patient's diagnosis (type +
# subtype + side), drawn from the admin-curated catalog in admin_catalog.py /
# patient_db.py's diagnosis_types/diagnosis_subtypes tables, with an "Other…"
# escape hatch on both the diagnosis and subtype comboboxes that reveals a plain
# text entry. Used by patient_manager_ui.py's NewPatientPage, PatientDetailPage,
# and the Diagnosis search condition row.

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

import patient_db
import query_builder
import ui_widgets

_OTHER = "Other…"
_ANY = "(Any)"
_SIDES_EDIT = ["", "Left", "Right", "Both"]
_SIDES_SEARCH = [_ANY, "Left", "Right", "Both"]


class DiagnosisPickerWidget(ttk.Frame):
    """One diagnosis entry: Diagnosis combo (+Other) / Subtype combo (+Other) /
    optional Side combo. get_value()/set_value() round-trip a plain dict of
    {"diagnosis": str, "subtype": str, "side": str}.

    for_search=True (the search condition row) adds a "(Any)" option -- always
    present, and the default -- to Diagnosis/Subtype/Side, plus inline labels, so
    it's clear what each box means and that leaving it alone matches anything.
    get_value() then returns diagnosis=None for a deliberate "(Any)" (a real,
    meaningful "match any diagnosis" signal -- distinct from diagnosis="", which
    still means "incomplete, e.g. Other left blank"). Patient-editing (for_search
    =False, the default) is unchanged: no "(Any)", every entry needs a real
    diagnosis picked."""

    def __init__(self, parent, include_side: bool = True, for_search: bool = False):
        super().__init__(parent)
        self.include_side = include_side
        self.for_search = for_search

        if for_search:
            ttk.Label(self, text="Diagnosis:").pack(side="left", padx=(0, 2))
        self.var_diagnosis = tk.StringVar()
        self.diagnosis_combo = ttk.Combobox(self, textvariable=self.var_diagnosis,
                                             state="readonly", width=20)
        self.diagnosis_combo.pack(side="left", padx=(0, 4))
        self.diagnosis_combo.bind("<<ComboboxSelected>>", self._on_diagnosis_change)

        self.var_diagnosis_other = tk.StringVar()
        self.diagnosis_other_entry = ttk.Entry(self, textvariable=self.var_diagnosis_other, width=16)
        self._diagnosis_other_field = ui_widgets.attach_placeholder(
            self.diagnosis_other_entry, self.var_diagnosis_other, "input diagnosis"
        )

        if for_search:
            ttk.Label(self, text="Subtype:").pack(side="left", padx=(0, 2))
        self.var_subtype = tk.StringVar()
        self.subtype_combo = ttk.Combobox(self, textvariable=self.var_subtype,
                                           state="readonly", width=18)
        self.subtype_combo.pack(side="left", padx=(0, 4))
        self.subtype_combo.bind("<<ComboboxSelected>>", self._on_subtype_change)

        self.var_subtype_other = tk.StringVar()
        self.subtype_other_entry = ttk.Entry(self, textvariable=self.var_subtype_other, width=16)
        self._subtype_other_field = ui_widgets.attach_placeholder(
            self.subtype_other_entry, self.var_subtype_other, "input subtype"
        )

        self.var_side = tk.StringVar()
        if include_side:
            if for_search:
                ttk.Label(self, text="Side:").pack(side="left", padx=(0, 2))
            sides = _SIDES_SEARCH if for_search else _SIDES_EDIT
            self.side_combo = ttk.Combobox(self, textvariable=self.var_side, values=sides,
                                            state="readonly", width=8)
            self.side_combo.pack(side="left", padx=(0, 4))
            self.side_combo.current(0)

        self._reload_diagnosis_options()
        if self.diagnosis_combo["values"]:
            self.diagnosis_combo.current(0)
        self._on_diagnosis_change()

    def _reload_diagnosis_options(self):
        conn = patient_db.connect()
        try:
            options = query_builder.get_enum_values(conn, "diagnosis_types")
        finally:
            conn.close()
        self._diagnosis_names = [label for _code, label in options]
        prefix = [_ANY] if self.for_search else []
        self.diagnosis_combo.configure(values=prefix + self._diagnosis_names + [_OTHER])

    def _current_diagnosis_text(self) -> str:
        """Resolved diagnosis text for subtype lookups -- "" for (Any)/unset/Other-left-blank."""
        sel = self.var_diagnosis.get()
        if sel == _OTHER:
            return self._diagnosis_other_field.get().strip()
        if self.for_search and sel == _ANY:
            return ""
        return sel

    def _on_diagnosis_change(self, _event=None):
        is_other = self.var_diagnosis.get() == _OTHER
        if is_other:
            self.diagnosis_other_entry.pack(side="left", padx=(0, 4), after=self.diagnosis_combo)
        else:
            self.diagnosis_other_entry.pack_forget()
        self._reload_subtype_options()

    def _reload_subtype_options(self):
        diagnosis = self._current_diagnosis_text()
        subtypes: list[str] = []
        if diagnosis:
            conn = patient_db.connect()
            try:
                subtypes = query_builder.get_diagnosis_subtypes(conn, diagnosis)
            finally:
                conn.close()
        blank = _ANY if self.for_search else ""
        values = [blank] + subtypes + [_OTHER]
        self.subtype_combo.configure(values=values)
        if self.var_subtype.get() not in values:
            self.subtype_combo.current(0)
        self._on_subtype_change()

    def _on_subtype_change(self, _event=None):
        is_other = self.var_subtype.get() == _OTHER
        if is_other:
            self.subtype_other_entry.pack(side="left", padx=(0, 4), after=self.subtype_combo)
        else:
            self.subtype_other_entry.pack_forget()

    def get_value(self) -> dict:
        sel = self.var_diagnosis.get()
        if self.for_search and sel == _ANY:
            diagnosis: Optional[str] = None
        else:
            diagnosis = self._current_diagnosis_text()

        subtype_sel = self.var_subtype.get()
        if self.for_search and subtype_sel == _ANY:
            subtype = ""
        elif subtype_sel == _OTHER:
            subtype = self._subtype_other_field.get().strip()
        else:
            subtype = subtype_sel

        side_sel = self.var_side.get() if self.include_side else ""
        side = "" if (self.for_search and side_sel == _ANY) else side_sel

        return {"diagnosis": diagnosis, "subtype": subtype or "", "side": side or ""}

    def set_value(self, value: dict):
        diagnosis = (value or {}).get("diagnosis")
        subtype = (value or {}).get("subtype", "")
        side = (value or {}).get("side", "")

        if diagnosis in self._diagnosis_names:
            self.var_diagnosis.set(diagnosis)
        elif diagnosis:
            self.var_diagnosis.set(_OTHER)
            self._diagnosis_other_field.set(diagnosis)
        elif self.for_search:
            self.var_diagnosis.set(_ANY)
        else:
            self.var_diagnosis.set(self._diagnosis_names[0] if self._diagnosis_names else "")
        self._on_diagnosis_change()  # reveals/hides Other entry + reloads subtypes

        conn = patient_db.connect()
        try:
            known_subtypes = query_builder.get_diagnosis_subtypes(conn, diagnosis) if diagnosis else []
        finally:
            conn.close()
        if subtype in known_subtypes:
            self.var_subtype.set(subtype)
        elif subtype:
            self.var_subtype.set(_OTHER)
            self._subtype_other_field.set(subtype)
        else:
            self.var_subtype.set(_ANY if self.for_search else "")
        self._on_subtype_change()

        if self.include_side:
            sides = _SIDES_SEARCH if self.for_search else _SIDES_EDIT
            self.var_side.set(side if side in sides else sides[0])


class DiagnosisListEditor(ttk.Frame):
    """Add/remove-rows container around N DiagnosisPickerWidgets (patient-editing
    only -- never for_search, so every row needs a real diagnosis picked)."""

    def __init__(self, parent, initial: Optional[list[dict]] = None):
        super().__init__(parent)
        self._rows: list[tuple[ttk.Frame, DiagnosisPickerWidget]] = []

        self.rows_frame = ttk.Frame(self)
        self.rows_frame.pack(fill="x")

        ttk.Button(self, text="+ Add Diagnosis", command=self._add_row).pack(anchor="w", pady=(4, 0))

        for entry in (initial or []):
            self._add_row(entry)

    def _add_row(self, value: Optional[dict] = None):
        row_frame = ttk.Frame(self.rows_frame)
        row_frame.pack(fill="x", pady=2)
        picker = DiagnosisPickerWidget(row_frame, include_side=True)
        picker.pack(side="left")
        if value:
            picker.set_value(value)
        ttk.Button(row_frame, text="Remove", command=lambda: self._remove_row(row_frame)).pack(side="left", padx=4)
        self._rows.append((row_frame, picker))

    def _remove_row(self, row_frame: ttk.Frame):
        self._rows = [(f, p) for f, p in self._rows if f is not row_frame]
        row_frame.destroy()

    def get_entries(self) -> list[dict]:
        out = []
        for _frame, picker in self._rows:
            value = picker.get_value()
            if value["diagnosis"]:
                out.append(value)
        return out
