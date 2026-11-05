# patient.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

# Only import for type checkers (won't run at runtime, avoids circulars)
if TYPE_CHECKING:
    from runtype import RunType
    import tkinter as tk


def _mk_run():
    # Import lazily at call time, after runtype.py has fully loaded
    from runtype import RunType
    return RunType()


@dataclass
class Patient:
    mrn: str = ""
    name: str = ""
    date: str = ""
    filePath: str = ""
    gender: int = 1        # 1=male, 0=female (kept from MATLAB usage)
    height: float = 0.0    # cm, as of most recent visit
    age: float = 0.0       # years, as of most recent visit

    # NEW: patient-level identity (persisted in patient.json inside the patient's
    # Clin_XXXX/Sport_XXXX folder(s) — see patient_store.py). last_name/first_name are
    # authoritative for folder naming (matches Clin_New.bat/Sport_New.bat's
    # LastName_FirstInitial convention); `name` is kept in sync as "Last, First" for
    # display/backward compatibility with modules (e.g. gait_graph_ui) that only know
    # a single free-text name field.
    last_name: str = ""
    first_name: str = ""
    date_of_birth: str = ""            # ISO YYYY-MM-DD

    # NEW: cached from the most recent visit — see patient_store.PatientRecord for the
    # authoritative per-visit values, these are only a convenience for callers that just
    # want "the current numbers" without loading a specific visit.
    bodyweight_kg: float = 0.0
    leg_length_left_cm: float = 0.0
    leg_length_right_cm: float = 0.0

    # NEW: diagnoses, each a plain dict {"diagnosis": str, "subtype": str, "side":
    # "Left"|"Right"|"Both"|""} -- see diagnosis_widgets.py / admin_catalog.py for
    # the controlled vocabulary these are drawn from (with an "Other" escape hatch).
    diagnoses: list = field(default_factory=list)

    # Bare, Pre, Post, Long — instantiate lazily to avoid circular imports
    latestRun: Optional["RunType"] = field(default_factory=_mk_run)
    previousRun: Optional["RunType"] = field(default_factory=_mk_run)


@dataclass
class VisitContext:
    """
    Passed into an analysis module's main(context=...) when launched from the
    patient-management shell, so the module can skip its own identity/output-location
    prompts. Modules run standalone (context=None) are unaffected.
    """
    patient: Patient
    visit_date: str            # ISO YYYY-MM-DD
    visit_id: str               # DOS folder name, e.g. "20260814"
    visit_dir: Path              # .../Clinical/Smith_J_Clin_0111_0000123456/20260814
    visit_type: str               # "Clin" | "Sport"
    lab_id: str                    # zero-padded 4-digit string, e.g. "0111"
    file_stub: str                  # FILEBASE-style stem matching Clin_New.bat/Sport_New.bat:
                                     # "{visit_type}_{lab_id}_{LastName}_{FirstInitial}_{DOS}"
                                     # — precomputed so no module re-implements this convention
    age_years: Optional[int] = None
    root: Optional["tk.Tk"] = None   # shell's live Tk root; only needed by modules (e.g.
                                      # gait_graph_ui) that must parent a modal Toplevel
