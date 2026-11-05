# gait_graph_ui.py
# Multi-visit GUI for Gait Graph:
# - Patient info once (MRN, Name, Height, Gender, Birth Date)
# - Any number of Visits (each has Date & auto-computed Age)
# - Each visit lists unique walk names (no Pre/Post duplication)
# - Generate a combined graph with ALL visits (color-coded by visit)
# - Save combined PDF, and/or save per-visit PDFs
#
# Can run standalone (main(), used by the old Analysis.py CLI menu) or be launched
# from the patient-management shell with a VisitContext (main(context=...)), in which
# case the Patient panel is pre-filled/locked from the known patient/visit and results
# are saved under that visit instead of asking for a save folder.

from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Tuple, Optional
import matplotlib.pyplot as plt
from pathlib import Path

from patient import Patient
from gait_graph import Condition, generate_graph_v3d, generate_graph_v3d_multi
from save2pdf import save2pdf
from ui_widgets import (
    parse_mdy_masked as _parse_mdy_masked,
    age_years_int as _age_years_int,
    iso_to_mdy,
    attach_mdy_mask,
)

DISPLAY_ROWS: List[Tuple[str, int]] = [
    ("Bare walk", 0),
    ("Brace walk", 1),
    ("Best walk", 2),
    ("Fast walk", 3),
    ("Other Bare Walk", 12),
    ("Other Brace Walk", 13),
    ("Other Best Walk", 14),
    ("Other Fast Walk", 15),
]

COND_FIELDS = ["Speed (cm/s)", "Stride (cm)"]


def name():
    return "Gait Graph (Multi-Visit GUI)"


class VisitTab:
    """
    Widgets/state for one visit tab. NOTE: "Visit" here means one row of walk
    conditions entered in a single sitting (this module's own long-standing concept),
    which is unrelated to the patient-management shell's one-visit-per-appointment
    concept in patient_store.VisitRecord — don't conflate the two.
    """
    def __init__(self, parent: ttk.Frame, visit_index: int, app: "AppFrame"):
        self.parent = parent
        self.visit_index = visit_index
        self.app = app

        meta = ttk.Frame(parent)
        meta.pack(fill="x", padx=6, pady=6)

        self.var_date = tk.StringVar()
        self.var_age = tk.StringVar()

        ttk.Label(meta, text="Visit Date (MM/DD/YYYY)").grid(row=0, column=0, padx=4, pady=4, sticky="e")
        self.entry_date = ttk.Entry(meta, textvariable=self.var_date, width=14)
        self.entry_date.grid(row=0, column=1, padx=4, pady=4)

        ttk.Label(meta, text="Age (years)").grid(row=0, column=2, padx=4, pady=4, sticky="e")
        self.entry_age = ttk.Entry(meta, textvariable=self.var_age, width=8, state="readonly")
        self.entry_age.grid(row=0, column=3, padx=4, pady=4)

        # Attach digit-only masking to visit date
        self.app._attach_mdy_mask(
            self.entry_date,
            self.var_date,
            on_change=lambda: self.app._recompute_age_for_visit(self, show_error=False),
            call_on_init=False,
        )
        self.entry_date.bind("<FocusOut>", lambda _e: self.app._on_visit_date_focus_out(self))

        table = ttk.LabelFrame(parent, text="Walks / Conditions (leave blank rows to skip)")
        table.pack(fill="both", expand=True, padx=6, pady=6)

        header = ["Type"] + COND_FIELDS
        for j, h in enumerate(header):
            ttk.Label(table, text=h, font=("Segoe UI", 10, "bold")).grid(row=0, column=j, padx=4, pady=4)

        self.entries: List[List[tk.Entry]] = []
        for i, (label, _type_idx) in enumerate(DISPLAY_ROWS):
            ttk.Label(table, text=label, width=28).grid(row=i + 1, column=0, padx=4, pady=2, sticky="w")

            row_entries: List[tk.Entry] = []
            e_speed = ttk.Entry(table, width=16)
            e_speed.grid(row=i + 1, column=1, padx=4, pady=2)
            row_entries.append(e_speed)

            e_stride = ttk.Entry(table, width=16)
            e_stride.grid(row=i + 1, column=2, padx=4, pady=2)
            row_entries.append(e_stride)

            self.entries.append(row_entries)

        self.fig_main = None
        self.fig_backup = None

    def has_any_walk_data(self) -> bool:
        for row_entries in self.entries:
            speed = row_entries[0].get().strip()
            stride = row_entries[1].get().strip()
            if speed or stride:
                return True
        return False

    def build_conditions(self, patient_height_cm: float) -> List[Condition]:
        conds: List[Condition] = [Condition() for _ in range(16)]
        visit_date = self.var_date.get().strip()
        visit_age = self.var_age.get().strip()
        height_str = f"{patient_height_cm:.0f}" if patient_height_cm else ""

        for row, (label, type_idx) in enumerate(DISPLAY_ROWS):
            speed = self.entries[row][0].get().strip()
            stride = self.entries[row][1].get().strip()
            if speed and stride and visit_age and height_str:
                c = Condition(
                    Speed=speed,
                    Stride=stride,
                    Date=visit_date,
                    Age=visit_age,
                    Height=height_str,
                )
                c.name = label
                conds[type_idx] = c
        return conds


class AppFrame(ttk.Frame):
    """
    All of the UI/state that used to live directly on App(tk.Tk). Extracted into a
    Frame so it can be hosted either inside a standalone App(tk.Tk) (context=None) or
    inside a modal Toplevel owned by the patient-management shell (context=VisitContext).
    """
    def __init__(self, parent, context=None):
        super().__init__(parent)
        self.context = context
        self.saved_files: List[Path] = []
        self._build_ui()

    def _build_ui(self):
        pf = ttk.LabelFrame(self, text="Patient")
        pf.pack(fill="x", padx=10, pady=10)

        ctx_patient: Optional[Patient] = self.context.patient if self.context is not None else None

        self.var_mrn = tk.StringVar(value=ctx_patient.mrn if ctx_patient else "")
        self.var_name = tk.StringVar(value=ctx_patient.name if ctx_patient else "")
        self.var_height = tk.StringVar(
            value=(f"{ctx_patient.height:.0f}" if ctx_patient and ctx_patient.height else "")
        )
        self.var_gender = tk.StringVar(
            value=("Female" if (ctx_patient is not None and ctx_patient.gender == 0) else "Male")
        )
        self.var_birth = tk.StringVar(value=(iso_to_mdy(ctx_patient.date_of_birth) if ctx_patient else ""))

        ttk.Label(pf, text="MRN").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        entry_mrn = ttk.Entry(pf, textvariable=self.var_mrn, width=22)
        entry_mrn.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(pf, text="Name").grid(row=0, column=2, padx=5, pady=5, sticky="e")
        entry_name = ttk.Entry(pf, textvariable=self.var_name, width=26)
        entry_name.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(pf, text="Height (cm)").grid(row=0, column=4, padx=5, pady=5, sticky="e")
        entry_height = ttk.Entry(pf, textvariable=self.var_height, width=10)
        entry_height.grid(row=0, column=5, padx=5, pady=5)

        ttk.Label(pf, text="Gender").grid(row=0, column=6, padx=5, pady=5, sticky="e")
        combo_gender = ttk.Combobox(
            pf, values=["Male", "Female"], textvariable=self.var_gender, width=10, state="readonly"
        )
        combo_gender.grid(row=0, column=7, padx=5, pady=5)

        ttk.Label(pf, text="Birth Date (MM/DD/YYYY)").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.entry_birth = ttk.Entry(pf, textvariable=self.var_birth, width=14)
        self.entry_birth.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # Attach digit-only masking to birth date (do not call on_change during init)
        self._attach_mdy_mask(
            self.entry_birth,
            self.var_birth,
            on_change=lambda: self._recompute_ages_all(show_error=False),
            call_on_init=False,
        )
        self.entry_birth.bind("<FocusOut>", lambda _e: self._on_birth_focus_out())

        if ctx_patient is not None:
            # Identity/demographics are already known from the shell's Patient record
            # for this visit — lock them so this screen only edits gait-specific data.
            entry_mrn.configure(state="readonly")
            entry_name.configure(state="readonly")
            entry_height.configure(state="readonly")
            combo_gender.configure(state="disabled")
            self.entry_birth.configure(state="readonly")

        frame_tabs = ttk.Frame(self)
        frame_tabs.pack(fill="both", expand=True, padx=10, pady=10)

        self.nb = ttk.Notebook(frame_tabs)
        self.nb.pack(fill="both", expand=True)

        self.visits: List[VisitTab] = []
        self._add_visit(initial=True)

        if self.context is not None and self.visits:
            self.visits[0].var_date.set(iso_to_mdy(self.context.visit_date))
            self._recompute_age_for_visit(self.visits[0], show_error=False)

        bf = ttk.Frame(self)
        bf.pack(fill="x", padx=10, pady=10)

        ttk.Button(bf, text="Add Visit", command=self._add_visit).pack(side="left", padx=5)
        ttk.Button(bf, text="Remove Visit", command=self._remove_visit).pack(side="left", padx=5)
        ttk.Separator(bf, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Button(bf, text="Generate Combined", command=self.on_generate_combined).pack(side="left", padx=5)
        ttk.Button(bf, text="Save Combined PDF…", command=self.on_save_combined).pack(side="left", padx=5)

        ttk.Separator(bf, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(bf, text="Generate + Save PDFs (All Visits)…", command=self.on_generate_save_all).pack(side="left", padx=5)

        ttk.Button(bf, text="Quit", command=self._on_quit).pack(side="right", padx=5)

        self.fig_combined = None

    # ----- masking hookup -----

    def _attach_mdy_mask(self, entry: ttk.Entry, var: tk.StringVar, on_change=None, call_on_init: bool = False):
        attach_mdy_mask(entry, var, on_change=on_change, call_on_init=call_on_init)

    def _on_quit(self):
        # Works whether this frame is packed directly into a standalone App(tk.Tk)
        # (closes the whole app) or hosted in a modal Toplevel from the shell
        # (closes just that dialog and unblocks the shell's wait_window()).
        self.winfo_toplevel().destroy()

    # ----- date + age validation -----

    def _birth_date(self):
        s = self.var_birth.get().strip()
        if not s:
            return None
        return _parse_mdy_masked(s)

    def _visit_date(self, visit: VisitTab):
        s = visit.var_date.get().strip()
        if not s:
            return None
        return _parse_mdy_masked(s)

    def _recompute_age_for_visit(self, visit: VisitTab, show_error: bool = False) -> bool:
        needs = visit.has_any_walk_data() or bool(visit.var_date.get().strip())
        if not needs:
            visit.var_age.set("")
            return True

        b_txt = self.var_birth.get().strip()
        if len(b_txt) != 10:
            visit.var_age.set("")
            if show_error:
                messagebox.showerror("Birth Date Required", "Enter Birth Date as MM/DD/YYYY (numbers only).")
            return False
        b = self._birth_date()
        if not b:
            visit.var_age.set("")
            if show_error:
                messagebox.showerror("Invalid Birth Date", "Birth Date must be a valid MM/DD/YYYY date.")
            return False

        v_txt = visit.var_date.get().strip()
        if len(v_txt) != 10:
            visit.var_age.set("")
            if show_error:
                messagebox.showerror("Visit Date Required", f"Visit {visit.visit_index} Date must be complete (MM/DD/YYYY).")
            return False
        v = self._visit_date(visit)
        if not v:
            visit.var_age.set("")
            if show_error:
                messagebox.showerror("Invalid Visit Date", f"Visit {visit.visit_index} Date must be a valid MM/DD/YYYY date.")
            return False

        if v < b:
            visit.var_age.set("")
            if show_error:
                messagebox.showerror("Invalid Dates", f"Visit {visit.visit_index} date cannot be before Birth Date.")
            return False

        visit.var_age.set(str(_age_years_int(b, v)))
        return True

    def _recompute_ages_all(self, show_error: bool = False) -> bool:
        if not hasattr(self, "visits"):
            return True

        ok = True
        for v in self.visits:
            if not self._recompute_age_for_visit(v, show_error=show_error):
                ok = False
        return ok

    def _on_birth_focus_out(self):
        s = self.var_birth.get().strip()
        if s and len(s) != 10:
            messagebox.showerror("Birth Date", "Birth Date must be complete: MM/DD/YYYY.")
            return
        if s and not self._birth_date():
            messagebox.showerror("Birth Date", "Birth Date must be a valid MM/DD/YYYY date.")
            return
        self._recompute_ages_all(show_error=False)

    def _on_visit_date_focus_out(self, visit: VisitTab):
        s = visit.var_date.get().strip()
        if s and len(s) != 10:
            messagebox.showerror("Visit Date", f"Visit {visit.visit_index} Date must be complete: MM/DD/YYYY.")
            visit.var_age.set("")
            return
        if s and not self._visit_date(visit):
            messagebox.showerror("Visit Date", f"Visit {visit.visit_index} Date must be a valid MM/DD/YYYY date.")
            visit.var_age.set("")
            return
        self._recompute_age_for_visit(visit, show_error=False)

    # ----- utilities -----

    def _add_visit(self, initial: bool = False):
        idx = len(self.visits) + 1
        frame = ttk.Frame(self.nb)
        vt = VisitTab(frame, idx, self)
        self.visits.append(vt)
        self.nb.add(frame, text=f"Visit {idx}")
        if not initial:
            self.nb.select(frame)

    def _remove_visit(self):
        current = self.nb.index(self.nb.select())
        if len(self.visits) <= 1:
            messagebox.showwarning("Cannot remove", "At least one visit is required.")
            return
        self.nb.forget(current)
        del self.visits[current]
        for i, vt in enumerate(self.visits):
            vt.visit_index = i + 1
            self.nb.tab(i, text=f"Visit {i+1}")

    def _build_patient(self) -> Patient:
        gender_val = 1 if self.var_gender.get() == "Male" else 0
        h_txt = self.var_height.get().strip()
        try:
            height = float(h_txt) if h_txt else 0.0
        except Exception:
            height = 0.0
        return Patient(
            mrn=self.var_mrn.get().strip(),
            name=self.var_name.get().strip(),
            gender=gender_val,
            height=height,
        )

    # ----- actions -----

    def on_generate_combined(self):
        if not self._recompute_ages_all(show_error=True):
            messagebox.showerror("Fix Dates", "Fix Birth/Visit dates (MM/DD/YYYY) before generating.")
            return

        pat = self._build_patient()
        if not pat.mrn:
            messagebox.showerror("Missing MRN", "Please enter patient MRN.")
            return
        if not pat.height:
            messagebox.showerror("Missing Height", "Please enter patient Height (cm).")
            return

        visits_payload: List[Tuple[str, List[Condition]]] = []
        for i, visit in enumerate(self.visits, start=1):
            conds = visit.build_conditions(pat.height)
            if any(c.Speed and c.Stride for c in conds):
                label = visit.var_date.get().strip() or f"Visit {i}"
                visits_payload.append((label, conds))

        if not visits_payload:
            messagebox.showerror("Missing Data", "Please enter at least one visit with some walks.")
            return

        try:
            self.fig_combined, _ = generate_graph_v3d_multi(pat, visits_payload)
        except Exception as e:
            messagebox.showerror("Error", f"Could not generate combined graph:\n{e}")
            return

        plt.show(block=False)
        messagebox.showinfo("Success", "Combined graph generated for all visits.")

    def _resolve_save_dir(self, title: str) -> Optional[Path]:
        if self.context is not None:
            from analysis_registry import default_output_dir
            outdir = Path(default_output_dir(self.context.visit_dir, "gait_graph", visit_type=self.context.visit_type))
            outdir.mkdir(parents=True, exist_ok=True)
            return outdir
        outdir_str = filedialog.askdirectory(title=title)
        return Path(outdir_str) if outdir_str else None

    def on_save_combined(self):
        if not self.fig_combined:
            messagebox.showwarning("Nothing to save", "Please generate the combined graph first.")
            return
        outdir = self._resolve_save_dir("Select folder to save Combined PDF")
        if not outdir:
            return
        mrn = self.var_mrn.get().strip() or "Gait"
        try:
            out_path = outdir / f"{mrn}-GaitGraph-ALL-VISITS.pdf"
            save2pdf(out_path, self.fig_combined, dpi=300)
            self.saved_files.append(out_path)
            messagebox.showinfo("Saved", "Saved combined PDF.")
        except Exception as e:
            messagebox.showerror("Save failed", f"Failed to save PDF:\n{e}")

    def on_generate_save_all(self):
        if not self._recompute_ages_all(show_error=True):
            messagebox.showerror("Fix Dates", "Fix Birth/Visit dates (MM/DD/YYYY) before saving.")
            return

        pat = self._build_patient()
        if not pat.mrn:
            messagebox.showerror("Missing MRN", "Please enter patient MRN.")
            return
        if not pat.height:
            messagebox.showerror("Missing Height", "Please enter patient Height (cm).")
            return

        out = self._resolve_save_dir("Select folder to save PDFs (All Visits)")
        if not out:
            return

        failures: List[str] = []
        saved: List[str] = []

        for i, visit in enumerate(self.visits, start=1):
            conds = visit.build_conditions(pat.height)
            if not any(c.Speed and c.Stride for c in conds):
                continue

            if not visit.var_age.get().strip():
                failures.append(f"Visit {i}: could not compute Age (check Birth/Visit dates)")
                continue

            try:
                fig_main, fig_backup = generate_graph_v3d(pat, conds)
                vdate = visit.var_date.get().strip() or f"Visit{i}"
                main_path = out / f"{pat.mrn}-{vdate}-GaitGraph.pdf"
                backup_path = out / f"{pat.mrn}-{vdate}-SpatialTemporal_Backup.pdf"
                save2pdf(main_path, fig_main, dpi=300)
                save2pdf(backup_path, fig_backup, dpi=300)
                self.saved_files.append(main_path)
                self.saved_files.append(backup_path)
                saved.append(f"Visit {i}")
            except Exception as e:
                failures.append(f"Visit {i}: {e}")

        msg = []
        if saved:
            msg.append("Saved:\n  - " + "\n  - ".join(saved))
        if failures:
            msg.append("\nIssues:\n  - " + "\n  - ".join(failures))
        if not msg:
            msg = ["Nothing saved (no visits had walk data)."]
        messagebox.showinfo("Batch Save", "\n".join(msg))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gait Graph (Multi-Visit, Combined)")
        self.geometry("1100x780")
        self.frame = AppFrame(self, context=None)
        self.frame.pack(fill="both", expand=True)


def collect_inputs(context=None, parent=None, shared=None):
    """
    This test is one continuous interactive session (fill patient/visit
    fields, click Generate, click Save) — clicking Generate/Save does the
    real work immediately, so there's no separate "processing phase" to
    defer the way the other modules do. Its whole session just runs here,
    up front during the batch's preflight pass, instead of waiting for its
    turn in the run loop. Returns the same result dict `main()` used to
    compute inline; `main(context, inputs=...)` just hands it back unchanged.
    """
    from analysis_registry import make_run_result

    if context is None:
        App().mainloop()
        return None

    owns_root = context.root is None
    root = context.root or tk.Tk()
    if owns_root:
        root.withdraw()

    toplevel = tk.Toplevel(root)
    toplevel.title("Gait Graph (Multi-Visit, Combined)")
    toplevel.geometry("1100x780")
    frame = AppFrame(toplevel, context=context)
    frame.pack(fill="both", expand=True)
    toplevel.grab_set()
    toplevel.wait_window()

    if owns_root:
        root.destroy()

    status = "success" if frame.saved_files else "cancelled"
    output_dir = str(frame.saved_files[0].parent) if frame.saved_files else None
    return make_run_result(
        status, output_dir=output_dir, output_files=frame.saved_files,
        summary={"visits": len(frame.visits), "files_saved": len(frame.saved_files)},
    )


def main(context=None, inputs=None):
    # `inputs`, for this module, is the already-computed result dict that
    # collect_inputs produced during the batch's preflight pass (there's no
    # processing left to do by the time main() is called) — see collect_inputs.
    if inputs is not None:
        return inputs
    return collect_inputs(context=context)


if __name__ == "__main__":
    main()
