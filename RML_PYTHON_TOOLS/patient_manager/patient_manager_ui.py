# patient_manager_ui.py
# Patient-management shell: search/create patients, view their visit history, and
# launch tests from analysis_registry against a known patient/visit context so those
# tools don't have to re-ask for identity/demographics.
#
# The on-disk layout conforms to the lab's existing Clin_New.bat / Sport_New.bat
# convention (see patient_store.py) — a patient can have a Clinical folder tree, a
# Sports Eval folder tree, or both, each under its own Lab Identifier.
#
# Run directly: python patient_manager_ui.py   (use python.exe, not pythonw.exe --
# ReformatAnalogForTheia's disambiguation prompts need a live console; see
# analysis_registry.py / that module's docstring for details.)

from __future__ import annotations

import os
import sys

# This file lives in RML_PYTHON_TOOLS/patient_manager/. Shared cross-tool utilities
# (ui_widgets.py, runtype.py) stay one level up in RML_PYTHON_TOOLS/, and the
# per-modality "test" tools analysis_registry.py launches by bare module name
# (gait_graph_ui, Cosmed_Processing_v8, etc.) live in tests/ alongside this file.
# Put both on sys.path so every existing bare `import X` below keeps resolving
# exactly as it did before the reorg -- no import lines needed to change.
_pkg_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_pkg_dir)
for _p in (_root, os.path.join(_pkg_dir, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import date
from pathlib import Path
from typing import Optional

import patient_store
import patient_db
import query_builder
import analysis_registry
import ui_widgets
import file_preview_panel
import admin_catalog
import diagnosis_widgets

VISIT_TYPE_LABELS = {"Clin": "Clinical", "Sport": "Sports Eval"}
VISIT_TYPE_CODES = {v: k for k, v in VISIT_TYPE_LABELS.items()}


class PatientManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RML Clinical Tools")
        self.geometry("1200x800")

        patient_store.init_saved_root()
        if not patient_store.structure_available():
            self.withdraw()
            self.wait_window(FolderStructureSetupDialog(self))
            self.deiconify()

        # Persistent bar docked as the top row of the window's content area (native
        # OS title bar stays untouched). Only shown once a patient is loaded.
        self.header_var = tk.StringVar(value="")
        self.header = ttk.Frame(self, padding=(12, 8))
        ttk.Label(self.header, textvariable=self.header_var, font=("Segoe UI", 13, "bold")).pack(side="left")

        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)

        self.patient_index: list[patient_store.PatientSummary] = []
        self.refresh_patient_index()

        self.current_page: Optional[ttk.Frame] = None
        self.show_page(QuerySearchPage)

    def refresh_patient_index(self):
        self.patient_index = patient_store.list_patients()

    def set_header(self, text: Optional[str]):
        if text:
            self.header_var.set(text)
            self.header.pack(fill="x", side="top", before=self.container)
        else:
            self.header.pack_forget()

    def show_page(self, page_cls, **kwargs):
        if self.current_page is not None:
            self.current_page.destroy()
        self.set_header(None)
        page = page_cls(self.container, self, **kwargs)
        page.pack(fill="both", expand=True)
        self.current_page = page


def _ensure_base_dir_or_prompt(visit_type: str) -> bool:
    """If the default Clinical/Sports Eval base folder isn't reachable, prompt the
    user for an alternate root (mirrors Clin_New.bat/Sport_New.bat's own fallback).
    Returns True once a usable base dir is set, False if the user backed out."""
    if patient_store.base_dir_available(visit_type):
        return True
    label = VISIT_TYPE_LABELS[visit_type]
    default_path = patient_store.get_base_dir(visit_type)
    messagebox.showwarning(
        "Base folder not found",
        f"The default {label} folder isn't reachable:\n{default_path}\n\n"
        "Choose the folder where patient folders should be created."
    )
    chosen = filedialog.askdirectory(title=f"Select root folder for {label} patients")
    if not chosen:
        return False
    patient_store.set_base_dir(visit_type, chosen)
    return True


class FolderStructureSetupDialog(tk.Toplevel):
    """Shown once at startup when neither the default nor a previously-saved patient
    data folder is reachable (e.g. the Q: network drive isn't mounted on this machine).
    Lets the user point at an existing folder, create a fresh one, or bail out and
    fall back on the lazy per-visit-type prompt (_ensure_base_dir_or_prompt) instead."""

    def __init__(self, parent: tk.Tk):
        super().__init__(parent)
        self.title("Locate Patient Data Folder")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.grab_set()

        default_root = patient_store.get_base_dir("Clin").parent
        subdirs = ", ".join(patient_store.STRUCTURE_SUBDIRS.values())
        msg = (
            "The patient data folder structure could not be found at:\n"
            f"{default_root}\n\n"
            f"That root folder should contain these subfolders: {subdirs} "
            "(one per visit type, each holding the patient folders).\n\n"
            "Locate it if it's just been moved (e.g. a different drive letter), "
            "or create a new one to get started."
        )
        ttk.Label(self, text=msg, wraplength=420, justify="left", padding=16).pack()

        btns = ttk.Frame(self, padding=(16, 0, 16, 16))
        btns.pack(fill="x")
        ttk.Button(btns, text="Locate Existing Folder…", command=self._locate).pack(fill="x", pady=4)
        ttk.Button(btns, text="Create New Folder Structure…", command=self._create_new).pack(fill="x", pady=4)
        ttk.Button(btns, text="Continue Without (limited)", command=self._skip).pack(fill="x", pady=4)

        self.update_idletasks()
        self._center_on(parent)

    def _center_on(self, parent: tk.Tk):
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    @staticmethod
    def _missing_subdirs(root: Path) -> list[str]:
        return [sub for sub in patient_store.STRUCTURE_SUBDIRS.values() if not (root / sub).is_dir()]

    def _finish(self, root: Path):
        patient_store.apply_root(root)
        patient_store.save_root(root)
        self.destroy()

    def _locate(self):
        chosen = filedialog.askdirectory(title="Select the folder containing Clinical / Sports_Eval", parent=self)
        if not chosen:
            return
        root = Path(chosen)
        missing = self._missing_subdirs(root)
        if missing:
            if not messagebox.askyesno(
                "Folders not found",
                f"'{root}' doesn't have: {', '.join(missing)}.\n\nCreate the missing folder(s) here?",
                parent=self,
            ):
                return
            try:
                for sub in missing:
                    (root / sub).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Could not create folder", str(e), parent=self)
                return
        self._finish(root)

    def _create_new(self):
        chosen = filedialog.askdirectory(
            title="Select a location for the new patient data folder structure", parent=self
        )
        if not chosen:
            return
        root = Path(chosen)
        try:
            for sub in patient_store.STRUCTURE_SUBDIRS.values():
                (root / sub).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Could not create folder", str(e), parent=self)
            return
        self._finish(root)

    def _skip(self):
        self.destroy()


# ---------------------------------------------------------------------------
# Patient search page (field/operator/value query builder)
# ---------------------------------------------------------------------------

class _ConditionRow:
    """One Field / Operator / Value row inside QuerySearchPage."""

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

        default_idx = next(
            (i for i, f in enumerate(query_builder.FIELD_CATALOG) if f.key == "first_name"), 0
        )
        self.field_combo.current(default_idx)
        self._on_field_change()

    def _current_field(self) -> query_builder.Field:
        idx = self.field_combo.current()
        return query_builder.FIELD_CATALOG[idx]

    def _on_field_change(self, _event=None):
        field = self._current_field()
        ops = query_builder.operators_for(field.value_type)
        self._op_codes = [code for code, _label in ops]
        self.operator_combo.configure(values=[label for _code, label in ops])
        default_op_idx = self._op_codes.index("contains") if field.value_type == query_builder.TEXT else 0
        self.operator_combo.current(default_op_idx)
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

    def set_condition(self, cond: "query_builder.Condition"):
        """Pre-fill this row from an existing Condition (used by AdminPage's
        'View Patients' pending-diagnosis shortcut)."""
        idx = next((i for i, f in enumerate(query_builder.FIELD_CATALOG) if f.key == cond.field_key), None)
        if idx is None:
            return
        self.field_combo.current(idx)
        self._on_field_change()
        if cond.operator_key in self._op_codes:
            self.operator_combo.current(self._op_codes.index(cond.operator_key))
        self._on_operator_change()
        field = self._current_field()
        if field.value_type == query_builder.DIAGNOSIS and self._diagnosis_widget is not None:
            self._diagnosis_widget.set_value(cond.value)

    def destroy(self):
        self.frame.destroy()


class QuerySearchPage(ttk.Frame):
    def __init__(self, parent, app: PatientManagerApp, preset_condition: Optional["query_builder.Condition"] = None):
        super().__init__(parent, padding=20)
        self.app = app
        self._rows: list[_ConditionRow] = []
        self._results: list[tuple] = []
        self._lacking_results: list[tuple] = []
        self._display_rows: list[tuple[str, Optional[str]]] = []

        ttk.Label(self, text="Patient Search", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 10))

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Button(top, text="New Patient", command=self._new_patient).pack(side="left")
        ttk.Button(top, text="Rebuild Index", command=self._rebuild_index).pack(side="left", padx=8)
        ttk.Button(top, text="Admin", command=lambda: self.app.show_page(AdminPage)).pack(side="left", padx=8)

        self.conditions_frame = ttk.LabelFrame(self, text="Conditions (all must match)", padding=10)
        self.conditions_frame.pack(fill="x", pady=10)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="+ Add Condition", command=self._add_row).pack(side="left")
        ttk.Button(btn_row, text="Search", command=self._run_search).pack(side="left", padx=8)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill="both", expand=True, pady=10)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Segoe UI", 11))
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<Double-Button-1>", self._on_select)
        self.listbox.bind("<Return>", self._on_select)

        self._add_row()
        if preset_condition is not None:
            self._rows[0].set_condition(preset_condition)
        elif self._rows[0]._value_widgets:
            self._rows[0]._value_widgets[0].focus_set()

        self._rebuild_index(silent=True)
        self._run_search()

    def _new_patient(self):
        self.app.show_page(NewPatientPage)

    def _rebuild_index(self, silent: bool = False):
        try:
            counts = patient_db.rebuild_index()
        except Exception as e:
            messagebox.showerror("Rebuild failed", str(e))
            return
        if not silent:
            messagebox.showinfo(
                "Index rebuilt",
                f"Indexed {counts['patients']} patient(s) and {counts['visits']} visit(s)."
            )

    def _add_row(self):
        self._rows.append(_ConditionRow(self.conditions_frame, self._remove_row))

    def _remove_row(self, row: _ConditionRow):
        if len(self._rows) == 1:
            return  # keep at least one row
        row.destroy()
        self._rows.remove(row)

    def _run_search(self):
        conditions = [c for c in (row.to_condition() for row in self._rows) if c is not None]
        required_keys = set(admin_catalog.get_required_fields())

        conn = patient_db.connect()
        try:
            self._results = query_builder.run_query(conn, conditions, combine="AND")
            lacking_sql = query_builder.build_lacking_data_query(
                conditions, required_keys, exclude_mrns=[r[0] for r in self._results], combine="AND"
            )
            self._lacking_results = conn.execute(*lacking_sql).fetchall() if lacking_sql else []
        except Exception as e:
            messagebox.showerror("Query failed", str(e))
            return
        finally:
            conn.close()

        self.listbox.delete(0, tk.END)
        self._display_rows = []
        for mrn, last, first, dob in self._results:
            self.listbox.insert(tk.END, f"{mrn}   —   {last}, {first}   (DOB {dob or '—'})")
            self._display_rows.append(("row", mrn))
        if not self._results and not self._lacking_results:
            self.listbox.insert(tk.END, "(no matches)")
            self._display_rows.append(("none", None))
        if self._lacking_results:
            self.listbox.insert(tk.END, "——— these people lack data for this query ———")
            self.listbox.itemconfig(
                self.listbox.size() - 1, foreground="#888888", selectbackground=self.listbox.cget("background")
            )
            self._display_rows.append(("divider", None))
            for mrn, last, first, dob in self._lacking_results:
                self.listbox.insert(tk.END, f"{mrn}   —   {last}, {first}   (DOB {dob or '—'})")
                self._display_rows.append(("row", mrn))

    def _on_select(self, _event=None):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._display_rows):
            return
        kind, mrn = self._display_rows[sel[0]]
        if kind != "row" or mrn is None:
            return
        self.app.refresh_patient_index()
        summary = next((s for s in self.app.patient_index if s.mrn == mrn), None)
        if summary is None:
            messagebox.showerror("Not found", f"Patient MRN {mrn} is in the index but not on disk anymore.")
            return
        record = patient_store.load_patient(summary)
        self.app.show_page(PatientDetailPage, patient_record=record)


# ---------------------------------------------------------------------------
# Admin page
# ---------------------------------------------------------------------------

class AdminPage(ttk.Frame):
    def __init__(self, parent, app: PatientManagerApp):
        super().__init__(parent, padding=20)
        self.app = app

        ttk.Button(self, text="< Back to Search", command=lambda: self.app.show_page(QuerySearchPage)).pack(anchor="w")
        ttk.Label(self, text="Admin", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(10, 10))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._build_diagnoses_tab()
        self._build_required_fields_tab()
        self._build_test_dependencies_tab()

    # ----- Diagnoses tab -----

    def _build_diagnoses_tab(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text="Diagnoses")

        ttk.Label(tab, text="Diagnosis Catalog", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        tree_frame = ttk.Frame(tab)
        tree_frame.pack(fill="both", expand=True, pady=(4, 8))
        self.catalog_tree = ttk.Treeview(tree_frame, show="tree")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=scrollbar.set)
        self.catalog_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_row = ttk.Frame(tab)
        btn_row.pack(fill="x", pady=(0, 12))
        self.var_new_type = tk.StringVar()
        entry_new_type = ttk.Entry(btn_row, textvariable=self.var_new_type, width=20)
        entry_new_type.pack(side="left", padx=(0, 4))
        self._new_type_field = ui_widgets.attach_placeholder(entry_new_type, self.var_new_type, "new diagnosis name")
        ttk.Button(btn_row, text="Add Type", command=self._add_type).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Remove Selected", command=self._remove_selected_catalog_item).pack(side="left", padx=4)
        self.var_new_subtype = tk.StringVar()
        entry_new_subtype = ttk.Entry(btn_row, textvariable=self.var_new_subtype, width=20)
        entry_new_subtype.pack(side="left", padx=(16, 4))
        self._new_subtype_field = ui_widgets.attach_placeholder(entry_new_subtype, self.var_new_subtype, "new subtype name")
        ttk.Button(btn_row, text="Add Subtype to Selected Type", command=self._add_subtype).pack(side="left", padx=4)

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=8)

        ttk.Label(tab, text="Pending Other Submissions", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.pending_frame = ttk.Frame(tab)
        self.pending_frame.pack(fill="both", expand=True, pady=(4, 0))

        self._refresh_catalog_tree()
        self._refresh_pending()

    def _refresh_catalog_tree(self):
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        for dtype, subtypes in sorted(admin_catalog.get_diagnosis_catalog().items()):
            type_id = self.catalog_tree.insert("", "end", text=dtype, open=True, tags=("type",), values=(dtype,))
            for sub in sorted(subtypes):
                self.catalog_tree.insert(type_id, "end", text=sub, tags=("subtype",), values=(dtype, sub))

    def _add_type(self):
        name = self._new_type_field.get().strip()
        if not name:
            return
        admin_catalog.add_diagnosis_type(name)
        patient_db.connect().close()
        self._new_type_field.set("")
        self._refresh_catalog_tree()

    def _add_subtype(self):
        sel = self.catalog_tree.selection()
        subtype = self._new_subtype_field.get().strip()
        if not sel or not subtype:
            messagebox.showinfo(
                "Pick a diagnosis type",
                "Select a diagnosis type (or one of its subtypes) in the list, then enter a subtype to add."
            )
            return
        item = self.catalog_tree.item(sel[0])
        dtype = item["text"] if "type" in item["tags"] else item["values"][0]
        admin_catalog.add_subtype(dtype, subtype)
        patient_db.connect().close()
        self._new_subtype_field.set("")
        self._refresh_catalog_tree()

    def _remove_selected_catalog_item(self):
        sel = self.catalog_tree.selection()
        if not sel:
            return
        item = self.catalog_tree.item(sel[0])
        if "type" in item["tags"]:
            if not messagebox.askyesno("Remove diagnosis type", f"Remove '{item['text']}' and all its subtypes?"):
                return
            admin_catalog.remove_diagnosis_type(item["text"])
        else:
            dtype, sub = item["values"]
            admin_catalog.remove_subtype(dtype, sub)
        patient_db.connect().close()
        self._refresh_catalog_tree()

    def _refresh_pending(self):
        for w in self.pending_frame.winfo_children():
            w.destroy()
        conn = patient_db.connect()
        try:
            pending = query_builder.get_pending_diagnosis_submissions(conn)
        finally:
            conn.close()
        if not pending:
            ttk.Label(self.pending_frame, text="(none)", foreground="#666666").pack(anchor="w")
            return
        for diagnosis, subtype in pending:
            row = ttk.Frame(self.pending_frame)
            row.pack(fill="x", pady=2)
            label = diagnosis if not subtype else f"{diagnosis} — {subtype}"
            ttk.Label(row, text=label, width=40).pack(side="left")
            ttk.Button(row, text="Approve",
                       command=lambda d=diagnosis, s=subtype: self._approve_pending(d, s)).pack(side="left", padx=4)
            ttk.Button(row, text="View Patients",
                       command=lambda d=diagnosis, s=subtype: self._view_patients(d, s)).pack(side="left", padx=4)

    def _approve_pending(self, diagnosis, subtype):
        if subtype:
            admin_catalog.add_subtype(diagnosis, subtype)
        else:
            admin_catalog.add_diagnosis_type(diagnosis)
        patient_db.connect().close()
        self._refresh_catalog_tree()
        self._refresh_pending()

    def _view_patients(self, diagnosis, subtype):
        value = {"diagnosis": diagnosis}
        if subtype:
            value["subtype"] = subtype
        cond = query_builder.Condition("diagnosis", "has", value)
        self.app.show_page(QuerySearchPage, preset_condition=cond)

    # ----- Required Fields tab -----

    def _build_required_fields_tab(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text="Required Fields")

        ttk.Label(
            tab,
            text="Fields marked Required will split search results into matches and a\n"
                 "second \"lacks data\" list for anyone missing that field.",
            foreground="#666666",
        ).pack(anchor="w", pady=(0, 8))

        lists_frame = ttk.Frame(tab)
        lists_frame.pack(fill="both", expand=True)

        avail_col = ttk.Frame(lists_frame)
        avail_col.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(avail_col, text="Available").pack(anchor="w")
        self.available_listbox = tk.Listbox(avail_col, exportselection=False)
        self.available_listbox.pack(fill="both", expand=True)

        btn_col = ttk.Frame(lists_frame)
        btn_col.pack(side="left", padx=4)
        ttk.Button(btn_col, text="Add →", command=self._add_required_field).pack(pady=20)
        ttk.Button(btn_col, text="← Remove", command=self._remove_required_field).pack()

        req_col = ttk.Frame(lists_frame)
        req_col.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(req_col, text="Required").pack(anchor="w")
        self.required_listbox = tk.Listbox(req_col, exportselection=False)
        self.required_listbox.pack(fill="both", expand=True)

        self._eligible_fields = [
            f for f in query_builder.FIELD_CATALOG
            if f.value_type in (query_builder.TEXT, query_builder.INTEGER, query_builder.REAL,
                                 query_builder.DATE, query_builder.ENUM, query_builder.DIAGNOSIS)
        ]
        self._refresh_required_lists()

    def _refresh_required_lists(self):
        required_keys = admin_catalog.get_required_fields()
        self.available_listbox.delete(0, tk.END)
        self.required_listbox.delete(0, tk.END)
        self._available_keys: list[str] = []
        self._required_keys: list[str] = []
        for f in self._eligible_fields:
            if f.key in required_keys:
                self.required_listbox.insert(tk.END, f.label)
                self._required_keys.append(f.key)
        for f in self._eligible_fields:
            if f.key not in required_keys:
                self.available_listbox.insert(tk.END, f.label)
                self._available_keys.append(f.key)

    def _add_required_field(self):
        sel = self.available_listbox.curselection()
        if not sel:
            return
        key = self._available_keys[sel[0]]
        required = admin_catalog.get_required_fields()
        if key not in required:
            required.append(key)
            admin_catalog.set_required_fields(required)
        self._refresh_required_lists()

    def _remove_required_field(self):
        sel = self.required_listbox.curselection()
        if not sel:
            return
        key = self._required_keys[sel[0]]
        required = [k for k in admin_catalog.get_required_fields() if k != key]
        admin_catalog.set_required_fields(required)
        self._refresh_required_lists()

    # ----- Test Dependencies tab -----
    # Scoped to ONLY the test-depends-on-test graph (what must run first) --
    # everything else about a test's inputs/outputs is declared in its own
    # Python code (analysis_registry.py's module contract), not admin-managed.

    def _build_test_dependencies_tab(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text="Test Dependencies")

        ttk.Label(
            tab, text="Select a test, then check which other tests must run first for it.",
            foreground="#666666",
        ).pack(anchor="w", pady=(0, 8))

        self.dep_modules = analysis_registry.load_methods()
        self.dep_slugs = [analysis_registry.slug_for_module(m.__name__) for m in self.dep_modules]
        self.dep_names = [m.name() for m in self.dep_modules]

        lists_frame = ttk.Frame(tab)
        lists_frame.pack(fill="both", expand=True)

        left_col = ttk.Frame(lists_frame)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(left_col, text="Tests").pack(anchor="w")
        self.dep_test_listbox = tk.Listbox(left_col, exportselection=False)
        self.dep_test_listbox.pack(fill="both", expand=True)
        for name in self.dep_names:
            self.dep_test_listbox.insert(tk.END, name)
        self.dep_test_listbox.bind("<<ListboxSelect>>", self._on_dep_test_select)

        right_col = ttk.Frame(lists_frame)
        right_col.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(right_col, text="Possible Dependencies").pack(anchor="w")
        self.dep_prereq_listbox = tk.Listbox(right_col, selectmode="multiple", exportselection=False)
        self.dep_prereq_listbox.pack(fill="both", expand=True)

        ttk.Button(tab, text="Save", command=self._save_dep_prerequisites).pack(anchor="w", pady=8)

        ttk.Label(tab, text="Current dependencies", font=("Segoe UI", 10, "bold")).pack(anchor="w")

        # Reserve the remove button's row at the bottom of the tab FIRST, so the
        # tree below it (packed next, fill+expand) can never crowd it out of view.
        self._dep_tree_edges = {}  # tree item id -> (slug, prereq_slug), for direct removal below
        ttk.Button(
            tab, text="Remove Selected Dependency", command=self._remove_selected_dependency
        ).pack(side="bottom", anchor="w", pady=(6, 0))

        tree_frame = ttk.Frame(tab)
        tree_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.dep_summary_tree = ttk.Treeview(tree_frame, show="tree")
        dep_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.dep_summary_tree.yview)
        self.dep_summary_tree.configure(yscrollcommand=dep_scrollbar.set)
        self.dep_summary_tree.pack(side="left", fill="both", expand=True)
        dep_scrollbar.pack(side="right", fill="y")

        if self.dep_names:
            self.dep_test_listbox.selection_set(0)
            self._on_dep_test_select()
        self._refresh_dep_summary()

    def _dep_name_for_slug(self, slug: str) -> str:
        return self.dep_names[self.dep_slugs.index(slug)] if slug in self.dep_slugs else slug

    def _on_dep_test_select(self, _event=None):
        sel = self.dep_test_listbox.curselection()
        if not sel:
            return
        slug = self.dep_slugs[sel[0]]
        self.dep_prereq_listbox.delete(0, tk.END)
        self._dep_prereq_slugs = [s for s in self.dep_slugs if s != slug]
        current = set(admin_catalog.get_prerequisites_for(slug))
        for i, other_slug in enumerate(self._dep_prereq_slugs):
            self.dep_prereq_listbox.insert(tk.END, self._dep_name_for_slug(other_slug))
            if other_slug in current:
                self.dep_prereq_listbox.selection_set(i)

    def _save_dep_prerequisites(self):
        sel = self.dep_test_listbox.curselection()
        if not sel:
            return
        slug = self.dep_slugs[sel[0]]
        chosen = [self._dep_prereq_slugs[i] for i in self.dep_prereq_listbox.curselection()]

        candidate = admin_catalog.get_test_dependencies()
        if chosen:
            candidate[slug] = chosen
        else:
            candidate.pop(slug, None)
        cycle = admin_catalog.find_dependency_cycle(candidate)
        if cycle:
            names = " → ".join(self._dep_name_for_slug(s) for s in cycle)
            messagebox.showerror("Circular Dependency", f"Cannot save: this would create a cycle:\n{names}")
            return

        admin_catalog.set_prerequisites_for(slug, chosen)
        self._refresh_dep_summary()
        messagebox.showinfo("Saved", f"Dependencies updated for {self._dep_name_for_slug(slug)}.")

    def _remove_selected_dependency(self):
        sel = self.dep_summary_tree.selection()
        edge = self._dep_tree_edges.get(sel[0]) if sel else None
        if edge is None:
            messagebox.showinfo(
                "Remove Dependency",
                "Select a prerequisite listed under a test above, then click Remove.",
            )
            return
        slug, prereq = edge
        remaining = [p for p in admin_catalog.get_prerequisites_for(slug) if p != prereq]
        admin_catalog.set_prerequisites_for(slug, remaining)
        self._refresh_dep_summary()
        test_sel = self.dep_test_listbox.curselection()
        if test_sel and self.dep_slugs[test_sel[0]] == slug:
            self._on_dep_test_select()

    def _refresh_dep_summary(self):
        self.dep_summary_tree.delete(*self.dep_summary_tree.get_children())
        self._dep_tree_edges = {}
        graph = admin_catalog.get_test_dependencies()
        if not graph:
            self.dep_summary_tree.insert("", "end", text="(no dependencies configured)")
            return
        for slug, prereqs in graph.items():
            if not prereqs:
                continue
            node = self.dep_summary_tree.insert("", "end", text=self._dep_name_for_slug(slug), open=True)
            for prereq in prereqs:
                child = self.dep_summary_tree.insert(node, "end", text=self._dep_name_for_slug(prereq))
                self._dep_tree_edges[child] = (slug, prereq)


# ---------------------------------------------------------------------------
# New patient page
# ---------------------------------------------------------------------------

class NewPatientPage(ttk.Frame):
    def __init__(self, parent, app: PatientManagerApp):
        super().__init__(parent, padding=20)
        self.app = app
        self._lab_id_user_edited = False

        ttk.Label(self, text="New Patient", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 10))

        form = ttk.Frame(self)
        form.pack(anchor="w")

        self.var_mrn = tk.StringVar()
        self.var_last = tk.StringVar()
        self.var_first = tk.StringVar()
        self.var_gender = tk.StringVar(value="Male")
        self.var_dob = tk.StringVar()
        self.var_weight = tk.StringVar()
        self.var_height = tk.StringVar()
        self.var_leg_l = tk.StringVar()
        self.var_leg_r = tk.StringVar()
        self.var_visit_date = tk.StringVar(value=ui_widgets.iso_to_mdy(date.today().isoformat()))
        self.var_type_label = tk.StringVar(value="Clinical")
        self.var_lab_id = tk.StringVar(value=patient_store.suggest_next_lab_id("Clin"))

        self._row = 0

        def add_row(label, var, mask=False, width=24):
            ttk.Label(form, text=label).grid(row=self._row, column=0, sticky="e", padx=6, pady=4)
            entry = ttk.Entry(form, textvariable=var, width=width)
            entry.grid(row=self._row, column=1, sticky="w", padx=6, pady=4)
            if mask:
                ui_widgets.attach_mdy_mask(entry, var)
            self._row += 1
            return entry

        add_row("MRN:", self.var_mrn)
        add_row("Last Name:", self.var_last)
        add_row("First Name:", self.var_first)

        ttk.Label(form, text="Gender:").grid(row=self._row, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(form, values=["Male", "Female"], textvariable=self.var_gender,
                     width=21, state="readonly").grid(row=self._row, column=1, sticky="w", padx=6, pady=4)
        self._row += 1

        add_row("Date of Birth (MM/DD/YYYY):", self.var_dob, mask=True)
        add_row("Bodyweight (kg):", self.var_weight)
        add_row("Height (cm):", self.var_height)
        add_row("Leg Length Left (cm, optional):", self.var_leg_l)
        add_row("Leg Length Right (cm, optional):", self.var_leg_r)

        ttk.Label(form, text="Visit Type:").grid(row=self._row, column=0, sticky="e", padx=6, pady=4)
        type_combo = ttk.Combobox(form, values=list(VISIT_TYPE_LABELS.values()), textvariable=self.var_type_label,
                                   width=21, state="readonly")
        type_combo.grid(row=self._row, column=1, sticky="w", padx=6, pady=4)
        type_combo.bind("<<ComboboxSelected>>", self._on_type_change)
        self._row += 1

        ttk.Label(form, text="Lab Identifier (1-9999):").grid(row=self._row, column=0, sticky="e", padx=6, pady=4)
        self.entry_lab_id = ttk.Entry(form, textvariable=self.var_lab_id, width=24)
        self.entry_lab_id.grid(row=self._row, column=1, sticky="w", padx=6, pady=4)
        self.entry_lab_id.bind("<KeyRelease>", lambda _e: setattr(self, "_lab_id_user_edited", True))
        self._row += 1

        add_row("First Visit Date (MM/DD/YYYY):", self.var_visit_date, mask=True)

        diag_frame = ttk.LabelFrame(self, text="Diagnoses", padding=10)
        diag_frame.pack(fill="x", pady=(10, 0))
        self.diag_editor = diagnosis_widgets.DiagnosisListEditor(diag_frame)
        self.diag_editor.pack(fill="x")

        btn_row = ttk.Frame(self)
        btn_row.pack(anchor="w", pady=16)
        ttk.Button(btn_row, text="Create Patient", command=self._create).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancel", command=lambda: self.app.show_page(QuerySearchPage)).pack(side="left", padx=6)

    def _on_type_change(self, _event=None):
        if not self._lab_id_user_edited:
            code = VISIT_TYPE_CODES[self.var_type_label.get()]
            self.var_lab_id.set(patient_store.suggest_next_lab_id(code))

    @staticmethod
    def _to_float(var: tk.StringVar) -> float:
        txt = var.get().strip()
        try:
            return float(txt) if txt else 0.0
        except ValueError:
            return 0.0

    def _create(self):
        mrn = self.var_mrn.get().strip()
        last_name = self.var_last.get().strip()
        first_name = self.var_first.get().strip()
        if not mrn or not last_name or not first_name:
            messagebox.showerror("Missing info", "MRN, Last Name, and First Name are required.")
            return
        for existing in self.app.patient_index:
            if existing.mrn.strip().lower() == mrn.lower():
                messagebox.showerror("Duplicate MRN", f"A patient with MRN '{mrn}' already exists.")
                return

        dob_txt = self.var_dob.get().strip()
        dob_iso = ui_widgets.mdy_to_iso(dob_txt)
        if dob_txt and not dob_iso:
            messagebox.showerror("Invalid Date", "Date of Birth must be a valid MM/DD/YYYY date.")
            return
        visit_iso = ui_widgets.mdy_to_iso(self.var_visit_date.get())
        if not visit_iso:
            messagebox.showerror("Invalid Date", "First Visit Date must be a valid MM/DD/YYYY date.")
            return

        visit_type = VISIT_TYPE_CODES[self.var_type_label.get()]
        try:
            lab_id = patient_store.format_lab_id(self.var_lab_id.get())
        except ValueError as e:
            messagebox.showerror("Invalid Lab Identifier", str(e))
            return

        if not _ensure_base_dir_or_prompt(visit_type):
            return

        gender = 1 if self.var_gender.get() == "Male" else 0

        try:
            record = patient_store.create_patient(
                mrn=mrn, last_name=last_name, first_name=first_name, gender=gender, date_of_birth=dob_iso,
                visit_type=visit_type, lab_id=lab_id, visit_date=visit_iso,
                bodyweight_kg=self._to_float(self.var_weight), height_cm=self._to_float(self.var_height),
                leg_length_left_cm=self._to_float(self.var_leg_l), leg_length_right_cm=self._to_float(self.var_leg_r),
                diagnoses=self.diag_editor.get_entries(),
            )
        except (ValueError, FileNotFoundError) as e:
            messagebox.showerror("Could not create patient", str(e))
            return

        self.app.refresh_patient_index()
        self.app.show_page(PatientDetailPage, patient_record=record)


# ---------------------------------------------------------------------------
# Patient detail page
# ---------------------------------------------------------------------------

def _collect_test_files(test: dict) -> list[str]:
    """test['output_files'] plus a shallow (non-recursive) scan of test['output_dir']
    for any extra files not already listed, deduped by normalized absolute path.
    Registered files keep their existing order; extras found on disk are appended,
    sorted by name. A missing recorded file is still included -- the preview panel
    surfaces "File not found" for it rather than silently dropping it."""
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(p: str):
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            ordered.append(p)

    for f in test.get("output_files") or []:
        _add(f)

    output_dir = test.get("output_dir")
    if output_dir and os.path.isdir(output_dir):
        try:
            names = sorted(os.listdir(output_dir))
        except OSError:
            names = []
        for name in names:
            full = os.path.join(output_dir, name)
            if os.path.isfile(full):
                _add(full)

    return ordered


class PatientDetailPage(ttk.Frame):
    def __init__(self, parent, app: PatientManagerApp, patient_record: patient_store.PatientRecord,
                 select_visit_id: Optional[str] = None):
        super().__init__(parent, padding=10)
        self.app = app
        self.record = patient_record

        self._set_header()

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Button(top, text="< Back to Search", command=lambda: self.app.show_page(QuerySearchPage)).pack(side="left")
        ttk.Button(top, text="Add Visit…", command=self._add_visit).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._build_info_tab()
        self._build_visit_tabs(select_visit_id)

    def _set_header(self):
        p = self.record.patient
        age_txt = ""
        if p.date_of_birth:
            try:
                b = date.fromisoformat(p.date_of_birth)
                age_txt = f"   •   Age {ui_widgets.age_years_int(b, date.today())}"
            except ValueError:
                pass
        self.app.set_header(f"{p.last_name}, {p.first_name}   (MRN {p.mrn}){age_txt}")

    # ----- Patient Info tab -----

    def _build_info_tab(self):
        info = ttk.Frame(self.nb, padding=16)
        self.nb.add(info, text="Patient Info")

        p = self.record.patient
        self.var_last = tk.StringVar(value=p.last_name)
        self.var_first = tk.StringVar(value=p.first_name)
        self.var_gender = tk.StringVar(value="Male" if p.gender == 1 else "Female")
        self.var_dob = tk.StringVar(value=ui_widgets.iso_to_mdy(p.date_of_birth))

        row = 0
        ttk.Label(info, text="MRN:").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Label(info, text=p.mrn, font=("Segoe UI", 10, "bold")).grid(row=row, column=1, sticky="w", padx=6, pady=4)
        row += 1

        ttk.Label(info, text="Last Name:").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(info, textvariable=self.var_last, width=30).grid(row=row, column=1, sticky="w", padx=6, pady=4)
        row += 1

        ttk.Label(info, text="First Name:").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(info, textvariable=self.var_first, width=30).grid(row=row, column=1, sticky="w", padx=6, pady=4)
        row += 1

        ttk.Label(info, text="Gender:").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(info, values=["Male", "Female"], textvariable=self.var_gender,
                     width=27, state="readonly").grid(row=row, column=1, sticky="w", padx=6, pady=4)
        row += 1

        ttk.Label(info, text="Date of Birth:").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        entry_dob = ttk.Entry(info, textvariable=self.var_dob, width=14)
        entry_dob.grid(row=row, column=1, sticky="w", padx=6, pady=4)
        ui_widgets.attach_mdy_mask(entry_dob, self.var_dob)
        row += 1

        ttk.Label(info, text="Diagnoses:").grid(row=row, column=0, sticky="ne", padx=6, pady=4)
        diag_frame = ttk.Frame(info)
        diag_frame.grid(row=row, column=1, sticky="w", padx=6, pady=4)
        self.diag_editor = diagnosis_widgets.DiagnosisListEditor(diag_frame, initial=p.diagnoses)
        self.diag_editor.pack(fill="x")
        row += 1

        ttk.Button(info, text="Save Changes", command=self._save_info).grid(row=row, column=0, columnspan=2, pady=12)
        row += 1

        note = ("Note: editing name here updates patient.json only — it does not rename the\n"
                "Clin_XXXX/Sport_XXXX folder(s) already created on disk.")
        ttk.Label(info, text=note, foreground="#666666", font=("Segoe UI", 8)).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 12))
        row += 1

        ttk.Separator(info, orient="horizontal").grid(row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        for visit_type, folder in self.record.type_folders.items():
            label = VISIT_TYPE_LABELS.get(visit_type, visit_type)
            lab_id = self.record.lab_ids.get(visit_type, "")
            ttk.Label(info, text=f"{label} folder (Lab ID {lab_id}):").grid(row=row, column=0, sticky="e", padx=6, pady=4)
            ttk.Button(info, text="Open in Explorer",
                       command=lambda f=folder: self._open_path(f)).grid(row=row, column=1, sticky="w", padx=6, pady=4)
            row += 1

    def _save_info(self):
        last_name = self.var_last.get().strip()
        first_name = self.var_first.get().strip()
        if not last_name or not first_name:
            messagebox.showerror("Missing info", "Last Name and First Name are required.")
            return
        dob_txt = self.var_dob.get().strip()
        dob_iso = ui_widgets.mdy_to_iso(dob_txt)
        if dob_txt and not dob_iso:
            messagebox.showerror("Invalid Date", "Date of Birth must be a valid MM/DD/YYYY date.")
            return
        self.record.patient.last_name = last_name
        self.record.patient.first_name = first_name
        self.record.patient.name = f"{last_name}, {first_name}"
        self.record.patient.gender = 1 if self.var_gender.get() == "Male" else 0
        self.record.patient.date_of_birth = dob_iso
        self.record.patient.diagnoses = self.diag_editor.get_entries()
        patient_store.save_patient(self.record)
        self.app.refresh_patient_index()
        self._set_header()
        messagebox.showinfo("Saved", "Patient info updated.")

    # ----- Visit tabs -----

    def _build_visit_tabs(self, select_visit_id: Optional[str]):
        self.visits = patient_store.list_visits(self.record)
        select_index = None
        for i, visit in enumerate(self.visits):
            tab = ttk.Frame(self.nb, padding=10)
            type_label = VISIT_TYPE_LABELS.get(visit.visit_type, visit.visit_type)
            self.nb.add(tab, text=f"{visit.date} ({type_label})")
            self._build_visit_tab_contents(tab, visit)
            if select_visit_id and visit.visit_id == select_visit_id:
                select_index = i + 1  # +1 for the "Patient Info" tab at index 0
        if select_index is not None:
            self.nb.select(select_index)

    def _build_visit_tab_contents(self, tab, visit: patient_store.VisitRecord):
        meta = ttk.LabelFrame(tab, text="Visit metrics")
        meta.pack(fill="x", pady=(0, 10))

        age_txt = "—"
        if self.record.patient.date_of_birth and visit.date:
            try:
                b = date.fromisoformat(self.record.patient.date_of_birth)
                v = date.fromisoformat(visit.date)
                age_txt = str(ui_widgets.age_years_int(b, v))
            except ValueError:
                pass

        type_label = VISIT_TYPE_LABELS.get(visit.visit_type, visit.visit_type)
        fields = [
            ("Date", visit.date), ("Type", type_label), ("Lab ID", visit.lab_id), ("Age at visit", age_txt),
            ("Bodyweight (kg)", visit.bodyweight_kg), ("Height (cm)", visit.height_cm),
            ("Leg Length L (cm)", visit.leg_length_left_cm), ("Leg Length R (cm)", visit.leg_length_right_cm),
        ]
        for i, (label, value) in enumerate(fields):
            r, c = divmod(i, 4)
            ttk.Label(meta, text=f"{label}:").grid(row=r, column=c * 2, sticky="e", padx=6, pady=4)
            ttk.Label(meta, text=str(value), font=("Segoe UI", 10, "bold")).grid(row=r, column=c * 2 + 1, sticky="w", padx=6, pady=4)

        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(0, 10))
        ttk.Button(actions, text="+ Add Test to this Visit",
                   command=lambda v=visit: self._add_visit(existing_visit=v)).pack(side="left")
        ttk.Button(actions, text="Open Visit Folder",
                   command=lambda v=visit: self._open_path(v.visit_dir)).pack(side="left", padx=8)

        ttk.Label(tab, text="Tests run this visit:", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        if not visit.tests:
            ttk.Label(tab, text="(none yet)").pack(anchor="w", padx=10, pady=6)
            return

        sub = ttk.Notebook(tab)
        sub.pack(fill="both", expand=True, pady=6)
        for test in visit.tests:
            self._build_test_subtab(sub, test)

    def _build_test_subtab(self, sub_notebook, test: dict):
        frame = ttk.Frame(sub_notebook, padding=10)
        label = test.get("display_name") or test.get("module") or "Test"
        sub_notebook.add(frame, text=label)

        status = test.get("status", "unknown")
        ttk.Label(frame, text=f"Status: {status}    Run at: {test.get('run_at', '')}",
                  font=("Segoe UI", 9)).pack(anchor="w")

        if test.get("error"):
            ttk.Label(frame, text=f"Error: {test['error']}", foreground="red", wraplength=500).pack(anchor="w", pady=4)

        summary = test.get("summary") or {}
        if summary:
            sframe = ttk.LabelFrame(frame, text="Summary")
            sframe.pack(fill="x", pady=6)
            for i, (k, v) in enumerate(summary.items()):
                ttk.Label(sframe, text=f"{k}:").grid(row=i, column=0, sticky="e", padx=6, pady=2)
                ttk.Label(sframe, text=str(v)).grid(row=i, column=1, sticky="w", padx=6, pady=2)

        output_dir = test.get("output_dir")
        if output_dir:
            ttk.Button(frame, text="Open Output Folder",
                       command=lambda d=output_dir: self._open_path(d)).pack(anchor="w", pady=(0, 8))

        files = _collect_test_files(test)
        if files:
            panel = file_preview_panel.FilePreviewPanel(frame, files=files)
            panel.pack(fill="both", expand=True, pady=(4, 0))
        else:
            ttk.Label(frame, text="(no output files)", foreground="#666666",
                      font=("Segoe UI", 8)).pack(anchor="w", pady=8)

    @staticmethod
    def _open_path(path):
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("Could not open", f"{path}\n\n{e}")

    def _add_visit(self, existing_visit: Optional[patient_store.VisitRecord] = None):
        AddVisitDialog(self, self.app, self.record, existing_visit=existing_visit)


# ---------------------------------------------------------------------------
# Add Visit dialog
# ---------------------------------------------------------------------------

class AddVisitDialog(tk.Toplevel):
    def __init__(self, parent_page: PatientDetailPage, app: PatientManagerApp,
                 patient_record: patient_store.PatientRecord,
                 existing_visit: Optional[patient_store.VisitRecord] = None):
        super().__init__(parent_page)
        self.app = app
        self.record = patient_record
        self.existing_visit = existing_visit
        self._lab_id_user_edited = False
        self.title("Add Test to Visit" if existing_visit else "Add Visit")
        self.geometry("500x640")
        self.grab_set()
        self._build_ui()

    def _build_ui(self):
        p = self.record.patient

        if self.existing_visit is None:
            form = ttk.LabelFrame(self, text="Visit details", padding=10)
            form.pack(fill="x", padx=10, pady=10)

            self.var_type_label = tk.StringVar(value="Clinical")
            default_code = VISIT_TYPE_CODES[self.var_type_label.get()]
            existing_lab = self.record.lab_ids.get(default_code, "")
            self.var_lab_id = tk.StringVar(value=existing_lab or patient_store.suggest_next_lab_id(default_code))

            self.var_date = tk.StringVar(value=ui_widgets.iso_to_mdy(date.today().isoformat()))
            self.var_weight = tk.StringVar(value=str(p.bodyweight_kg or ""))
            self.var_height = tk.StringVar(value=str(p.height or ""))
            self.var_leg_l = tk.StringVar(value=str(p.leg_length_left_cm or ""))
            self.var_leg_r = tk.StringVar(value=str(p.leg_length_right_cm or ""))

            ttk.Label(form, text="Visit Type:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
            type_combo = ttk.Combobox(form, values=list(VISIT_TYPE_LABELS.values()), textvariable=self.var_type_label,
                                       width=18, state="readonly")
            type_combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)
            type_combo.bind("<<ComboboxSelected>>", self._on_type_change)

            ttk.Label(form, text="Lab Identifier:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
            self.entry_lab_id = ttk.Entry(form, textvariable=self.var_lab_id, width=20)
            self.entry_lab_id.grid(row=1, column=1, sticky="w", padx=6, pady=4)
            self.entry_lab_id.bind("<KeyRelease>", lambda _e: setattr(self, "_lab_id_user_edited", True))
            if existing_lab:
                self.entry_lab_id.configure(state="readonly")

            def add_row(row, label, var, mask=False):
                ttk.Label(form, text=label).grid(row=row, column=0, sticky="e", padx=6, pady=4)
                e = ttk.Entry(form, textvariable=var, width=20)
                e.grid(row=row, column=1, sticky="w", padx=6, pady=4)
                if mask:
                    ui_widgets.attach_mdy_mask(e, var)

            add_row(2, "Visit Date (MM/DD/YYYY):", self.var_date, mask=True)
            add_row(3, "Bodyweight (kg):", self.var_weight)
            add_row(4, "Height (cm):", self.var_height)
            add_row(5, "Leg Length L (cm):", self.var_leg_l)
            add_row(6, "Leg Length R (cm):", self.var_leg_r)
        else:
            type_label = VISIT_TYPE_LABELS.get(self.existing_visit.visit_type, self.existing_visit.visit_type)
            ttk.Label(self, text=f"Adding a test to visit: {self.existing_visit.date} ({type_label})",
                      font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(10, 0))

        checklist_frame = ttk.LabelFrame(self, text="Tests to run", padding=10)
        checklist_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.modules = analysis_registry.load_methods()
        self.check_vars: list[tk.BooleanVar] = []
        for mod in self.modules:
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(checklist_frame, text=mod.name(), variable=var).pack(anchor="w", pady=2)
            self.check_vars.append(var)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=10)
        ttk.Button(btn_row, text="Start", command=self._start).pack(side="left")
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="left", padx=8)

    def _on_type_change(self, _event=None):
        code = VISIT_TYPE_CODES[self.var_type_label.get()]
        existing_lab = self.record.lab_ids.get(code, "")
        if existing_lab:
            self.var_lab_id.set(existing_lab)
            self.entry_lab_id.configure(state="readonly")
            self._lab_id_user_edited = False
        else:
            self.entry_lab_id.configure(state="normal")
            if not self._lab_id_user_edited:
                self.var_lab_id.set(patient_store.suggest_next_lab_id(code))

    @staticmethod
    def _to_float(var: tk.StringVar) -> float:
        txt = var.get().strip()
        try:
            return float(txt) if txt else 0.0
        except ValueError:
            return 0.0

    def _start(self):
        selected = [mod for mod, var in zip(self.modules, self.check_vars) if var.get()]
        if not selected:
            messagebox.showwarning("No tests selected", "Check at least one test to run, or Cancel.")
            return

        if self.existing_visit is None:
            visit_type = VISIT_TYPE_CODES[self.var_type_label.get()]
            try:
                lab_id = patient_store.format_lab_id(self.var_lab_id.get())
            except ValueError as e:
                messagebox.showerror("Invalid Lab Identifier", str(e))
                return
            visit_iso = ui_widgets.mdy_to_iso(self.var_date.get())
            if not visit_iso:
                messagebox.showerror("Invalid Date", "Visit Date must be a valid MM/DD/YYYY date.")
                return

            if visit_type not in self.record.type_folders and not _ensure_base_dir_or_prompt(visit_type):
                return

            try:
                visit = patient_store.add_visit(
                    self.record, visit_type, visit_iso,
                    self._to_float(self.var_weight), self._to_float(self.var_height),
                    self._to_float(self.var_leg_l), self._to_float(self.var_leg_r),
                    lab_id=lab_id,
                )
            except (ValueError, FileNotFoundError) as e:
                messagebox.showerror("Could not create visit", str(e))
                return
            self.app.refresh_patient_index()
        else:
            visit = self.existing_visit

        # Reorder the selected tests so a prerequisite another selected test
        # depends on (admin-managed, see AdminPage's "Test Dependencies" tab)
        # always runs first; warn (with a force-continue option) if a
        # dependency is neither selected nor already satisfied by a past run.
        ordered_selected, missing = analysis_registry.plan_execution_order(
            selected, visit, admin_catalog.get_test_dependencies()
        )
        if missing:
            name_by_slug = {
                analysis_registry.slug_for_module(mod.__name__): mod.name() for mod in self.modules
            }
            lines = "\n".join(
                f"  - {name_by_slug.get(dep, dep)} needs {name_by_slug.get(prereq, prereq)} to run first"
                for dep, prereq in missing
            )
            if not messagebox.askyesno(
                "Missing Prerequisite(s)",
                f"{lines}\n\nThese haven't run for this visit and weren't selected. "
                "Continue anyway? The dependent test(s) may fail or produce incomplete output.",
            ):
                return

        # Close the checklist dialog now; the selected modules take over the UI
        # thread from here (some, e.g. Cosmed/Pedobarograph, need live user
        # interaction — this is a synchronous, sequential run by design, see
        # analysis_registry.py notes on why threading isn't used here).
        self.destroy()

        context = patient_store.build_visit_context(self.record, visit, root=self.app)

        # Ask every selected test for its inputs up front (one combined form,
        # then any test's own remaining prompts), instead of interrupting the
        # run loop below as each test's turn comes up. See analysis_registry.py.
        # Uses the original REGISTRY-order `selected`, not the dependency-sorted
        # `ordered_selected` -- reordering only affects execution order below, not
        # the combined form's section layout.
        collected_inputs = analysis_registry.run_preflight(selected, context=context, parent=self.app)
        if collected_inputs is None:
            messagebox.showinfo("Cancelled", "No tests were run.")
            self.app.show_page(PatientDetailPage, patient_record=self.record, select_visit_id=visit.visit_id)
            return

        results = []
        for mod in ordered_selected:
            slug = analysis_registry.slug_for_module(mod.__name__)
            inputs = dict(collected_inputs.get(mod.__name__) or {})
            # Resolved here, right before this module's own turn, so a prerequisite
            # that ran earlier in this same loop has already recorded its output
            # (patient_store.record_test_result() below is synchronous).
            inputs.update(analysis_registry.resolve_upstream_inputs(mod, context, visit))
            try:
                result = mod.main(context, inputs=inputs)
            except Exception as e:
                result = analysis_registry.make_run_result("error", error=str(e))
            result = result or analysis_registry.make_run_result("success")
            patient_store.record_test_result(
                visit, module_name=mod.__name__, slug=slug, display_name=mod.name(),
                status=result.get("status", "success"),
                output_dir=result.get("output_dir"),
                output_files=result.get("output_files"),
                summary=result.get("summary"),
                error=result.get("error"),
            )
            results.append((mod.name(), result.get("status", "success")))

        summary_lines = "\n".join(f"  - {n}: {s}" for n, s in results)
        messagebox.showinfo("Visit tests complete", f"Finished running:\n{summary_lines}")

        self.app.show_page(PatientDetailPage, patient_record=self.record, select_visit_id=visit.visit_id)


if __name__ == "__main__":
    PatientManagerApp().mainloop()