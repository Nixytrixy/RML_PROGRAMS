# patient_query_app.py
# Standalone "Patient Select" query-builder app -- just the SQL-backed advanced
# search screen from patient_manager_ui.py, runnable on its own without the rest of
# the patient-management shell (no analysis_registry/file_preview_panel dependency).
#
# Reads the same patient_index.db that patient_manager_ui.py keeps in sync (via
# patient_store.py's save_patient/save_visit hooks) -- this program only reads and
# never writes patient.json/visit.json itself. "Rebuild Index" is still offered here
# in case this is run on a machine/share where the index has drifted or is missing.
#
# Run directly: python patient_query_app.py

from __future__ import annotations

import os
import sys

# This file lives in RML_PYTHON_TOOLS/patient_manager/. patient_db.py (imported
# below) dynamically imports the registered "test" tool modules by bare name via
# analysis_registry.py when seeding its lookup tables -- those modules live in
# tests/ alongside this file, so put it (and the shared-utilities dir one level
# up) on sys.path before anything else runs.
_pkg_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_pkg_dir)
for _p in (_root, os.path.join(_pkg_dir, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

import patient_store
import patient_db
import query_builder
import diagnosis_widgets

VISIT_TYPE_LABELS = {"Clin": "Clinical", "Sport": "Sports Eval"}


class _ConditionRow:
    """One Field / Operator / Value row."""

    def __init__(self, parent, on_remove):
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="x", pady=2)
        self._op_codes: list[str] = []
        self._enum_codes: list = []
        self._value_widgets: list[tk.Widget] = []
        self._value_vars: list[tk.StringVar] = []
        self._diagnosis_widget: Optional[diagnosis_widgets.DiagnosisPickerWidget] = None

        self.var_field = tk.StringVar()
        self.field_combo = ttk.Combobox(self.frame, values=[f.label for f in query_builder.FIELD_CATALOG],
                                         textvariable=self.var_field, state="readonly", width=28)
        self.field_combo.pack(side="left", padx=(0, 6))
        self.field_combo.bind("<<ComboboxSelected>>", self._on_field_change)

        self.var_operator = tk.StringVar()
        self.operator_combo = ttk.Combobox(self.frame, textvariable=self.var_operator,
                                            state="readonly", width=12)
        self.operator_combo.pack(side="left", padx=(0, 6))
        self.operator_combo.bind("<<ComboboxSelected>>", self._on_operator_change)

        self.value_container = ttk.Frame(self.frame)
        self.value_container.pack(side="left", padx=(0, 6))

        ttk.Button(self.frame, text="Remove", command=lambda: on_remove(self)).pack(side="left")

        self.field_combo.current(0)
        self._on_field_change()

    def _current_field(self) -> query_builder.Field:
        idx = self.field_combo.current()
        return query_builder.FIELD_CATALOG[idx]

    def _on_field_change(self, _event=None):
        field = self._current_field()
        ops = query_builder.operators_for(field.value_type)
        self._op_codes = [code for code, _label in ops]
        self.operator_combo.configure(values=[label for _code, label in ops])
        self.operator_combo.current(0)
        self._on_operator_change()

    def _current_operator_code(self) -> str:
        idx = self.operator_combo.current()
        return self._op_codes[idx] if 0 <= idx < len(self._op_codes) else self._op_codes[0]

    def _on_operator_change(self, _event=None):
        for w in self._value_widgets:
            w.destroy()
        self._value_widgets = []
        self._value_vars = []
        if self._diagnosis_widget is not None:
            self._diagnosis_widget.destroy()
            self._diagnosis_widget = None

        field = self._current_field()
        op_code = self._current_operator_code()

        if field.value_type == query_builder.DIAGNOSIS:
            self._diagnosis_widget = diagnosis_widgets.DiagnosisPickerWidget(
                self.value_container, include_side=True, for_search=True
            )
            self._diagnosis_widget.pack(side="left")
            return

        if field.value_type == query_builder.BOOL:
            count = 0
        elif op_code == "between":
            count = 2
        else:
            count = 1

        for _ in range(count):
            var = tk.StringVar()
            if field.value_type in (query_builder.ENUM, query_builder.MODULE_RUN):
                conn = patient_db.connect()
                try:
                    options = query_builder.get_enum_values(conn, field.enum_source)
                finally:
                    conn.close()
                self._enum_codes = [code for code, _label in options]
                widget = ttk.Combobox(self.value_container, values=[label for _c, label in options],
                                       textvariable=var, state="readonly", width=16)
                if options:
                    widget.current(0)
            else:
                widget = ttk.Entry(self.value_container, textvariable=var, width=16)
            widget.pack(side="left", padx=(0, 4))
            self._value_widgets.append(widget)
            self._value_vars.append(var)

    def to_condition(self) -> Optional["query_builder.Condition"]:
        field = self._current_field()
        op_code = self._current_operator_code()

        if field.value_type == query_builder.DIAGNOSIS:
            if self._diagnosis_widget is None:
                return None
            v = self._diagnosis_widget.get_value()
            if v["diagnosis"] == "":
                return None
            value = {"diagnosis": v["diagnosis"]}
            if v.get("subtype"):
                value["subtype"] = v["subtype"]
            if v.get("side"):
                value["side"] = v["side"]
            return query_builder.Condition(field.key, op_code, value)

        if field.value_type == query_builder.BOOL:
            return query_builder.Condition(field.key, op_code, None)

        if field.value_type in (query_builder.ENUM, query_builder.MODULE_RUN):
            idx = self._value_widgets[0].current() if self._value_widgets else -1
            if idx < 0:
                return None
            return query_builder.Condition(field.key, op_code, self._enum_codes[idx])

        raw_values = [v.get().strip() for v in self._value_vars]
        if any(not v for v in raw_values):
            return None
        try:
            if field.value_type == query_builder.INTEGER:
                cast_values = [int(v) for v in raw_values]
            elif field.value_type == query_builder.REAL:
                cast_values = [float(v) for v in raw_values]
            else:
                cast_values = raw_values
        except ValueError:
            return None

        value = tuple(cast_values) if op_code == "between" else cast_values[0]
        return query_builder.Condition(field.key, op_code, value)

    def destroy(self):
        self.frame.destroy()


class PatientDetailDialog(tk.Toplevel):
    """Read-only summary -- just enough to confirm a match and jump to the real
    folder. The full editable patient record lives in patient_manager_ui.py."""

    def __init__(self, parent, mrn: str):
        super().__init__(parent)
        self.title(f"Patient {mrn}")
        self.geometry("520x420")
        self.grab_set()

        conn = patient_db.connect()
        try:
            patient = conn.execute(
                "SELECT mrn, last_name, first_name, gender, date_of_birth FROM patients WHERE mrn = ?", (mrn,)
            ).fetchone()
            folders = conn.execute(
                "SELECT visit_type, lab_id, folder_path FROM patient_folders WHERE mrn = ?", (mrn,)
            ).fetchall()
            visits = conn.execute(
                """SELECT visit_type, dos, visit_date, visit_dir, bodyweight_kg, height_cm,
                          mocap_has_data, mocap_has_results, pedobarograph_has_data, pedobarograph_has_results,
                          metabolic_has_data, metabolic_has_results
                   FROM visits WHERE mrn = ? ORDER BY visit_date""",
                (mrn,),
            ).fetchall()
        finally:
            conn.close()

        if patient is None:
            ttk.Label(self, text=f"No record for MRN {mrn}.", padding=16).pack()
            return

        _mrn, last, first, gender, dob = patient
        header = ttk.Frame(self, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text=f"{last}, {first}", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        gender_label = "Male" if gender == 1 else "Female" if gender == 0 else "—"
        ttk.Label(header, text=f"MRN {mrn}   •   DOB {dob or '—'}   •   {gender_label}").pack(anchor="w")

        for visit_type, lab_id, folder_path in folders:
            row = ttk.Frame(header)
            row.pack(fill="x", pady=(6, 0))
            label = VISIT_TYPE_LABELS.get(visit_type, visit_type)
            ttk.Label(row, text=f"{label} folder (Lab ID {lab_id}):").pack(side="left")
            ttk.Button(row, text="Open in Explorer",
                       command=lambda p=folder_path: self._open_path(p)).pack(side="left", padx=6)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=6)
        ttk.Label(self, text="Visits:", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12)

        list_frame = ttk.Frame(self, padding=(12, 4))
        list_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        text = tk.Text(list_frame, yscrollcommand=scrollbar.set, wrap="word", height=12)
        scrollbar.config(command=text.yview)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        for (visit_type, dos, visit_date, visit_dir, weight, height,
             mocap_d, mocap_r, pedo_d, pedo_r, metab_d, metab_r) in visits:
            label = VISIT_TYPE_LABELS.get(visit_type, visit_type)
            flags = []
            if mocap_d or mocap_r:
                flags.append(f"Mocap({'data' if mocap_d else ''}{'+' if mocap_d and mocap_r else ''}{'results' if mocap_r else ''})")
            if pedo_d or pedo_r:
                flags.append(f"Pedobarograph({'data' if pedo_d else ''}{'+' if pedo_d and pedo_r else ''}{'results' if pedo_r else ''})")
            if metab_d or metab_r:
                flags.append(f"Metabolic({'data' if metab_d else ''}{'+' if metab_d and metab_r else ''}{'results' if metab_r else ''})")
            flags_txt = ", ".join(flags) if flags else "(no modality data)"
            text.insert(
                tk.END,
                f"{visit_date} ({label})   weight={weight or '—'}kg  height={height or '—'}cm\n"
                f"    {flags_txt}\n"
                f"    {visit_dir}\n\n",
            )
        text.configure(state="disabled")

        ttk.Button(self, text="Close", command=self.destroy).pack(pady=8)

    @staticmethod
    def _open_path(path):
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("Could not open", f"{path}\n\n{e}")


class PatientQueryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RML Patient Query")
        self.geometry("1000x700")

        patient_store.init_saved_root()
        if not patient_store.structure_available():
            self._prompt_for_root()

        self._rows: list[_ConditionRow] = []
        self._results: list[tuple] = []
        self._build_ui()

    def _prompt_for_root(self):
        default_root = patient_store.get_base_dir("Clin").parent
        messagebox.showwarning(
            "Patient data folder not found",
            f"Couldn't find the patient data folder at:\n{default_root}\n\n"
            "Choose the folder that contains Clinical / Sports_Eval.",
        )
        chosen = filedialog.askdirectory(title="Select the folder containing Clinical / Sports_Eval")
        if chosen:
            patient_store.apply_root(chosen)
            patient_store.save_root(chosen)

    def _build_ui(self):
        container = ttk.Frame(self, padding=20)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Patient Select", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 10))

        top = ttk.Frame(container)
        top.pack(fill="x")
        ttk.Button(top, text="Rebuild Index", command=self._rebuild_index).pack(side="left")

        self.conditions_frame = ttk.LabelFrame(container, text="Conditions (all must match)", padding=10)
        self.conditions_frame.pack(fill="x", pady=10)

        btn_row = ttk.Frame(container)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="+ Add Condition", command=self._add_row).pack(side="left")
        ttk.Button(btn_row, text="Search", command=self._run_search).pack(side="left", padx=8)

        list_frame = ttk.Frame(container)
        list_frame.pack(fill="both", expand=True, pady=10)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Segoe UI", 11))
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<Double-Button-1>", self._on_select)
        self.listbox.bind("<Return>", self._on_select)

        self._add_row()

    def _add_row(self):
        self._rows.append(_ConditionRow(self.conditions_frame, self._remove_row))

    def _remove_row(self, row: _ConditionRow):
        if len(self._rows) == 1:
            return  # keep at least one row
        row.destroy()
        self._rows.remove(row)

    def _rebuild_index(self):
        try:
            counts = patient_db.rebuild_index()
        except Exception as e:
            messagebox.showerror("Rebuild failed", str(e))
            return
        messagebox.showinfo(
            "Index rebuilt",
            f"Indexed {counts['patients']} patient(s) and {counts['visits']} visit(s)."
        )

    def _run_search(self):
        conditions = [c for c in (row.to_condition() for row in self._rows) if c is not None]

        conn = patient_db.connect()
        try:
            self._results = query_builder.run_query(conn, conditions, combine="AND")
        except Exception as e:
            messagebox.showerror("Query failed", str(e))
            return
        finally:
            conn.close()

        self.listbox.delete(0, tk.END)
        for mrn, last, first, dob in self._results:
            self.listbox.insert(tk.END, f"{mrn}   —   {last}, {first}   (DOB {dob or '—'})")
        if not self._results:
            self.listbox.insert(tk.END, "(no matches)")

    def _on_select(self, _event=None):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._results):
            return
        mrn = self._results[sel[0]][0]
        PatientDetailDialog(self, mrn)


if __name__ == "__main__":
    PatientQueryApp().mainloop()
