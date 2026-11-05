# patient_store.py
# Persistence layer that conforms to the REAL patient-folder convention already used by
# Clin_New.bat / Sport_New.bat: two parallel trees (Clinical, Sports Eval), each patient
# folder named "{LastName}_{FirstInitial}_{Clin|Sport}_{LabID}_{MRN}", with one subfolder
# per Date-of-Service (DOS, YYYYMMDD) visit containing the same skeleton (Documents,
# Metabolic/Mocap/Pedobarograph/Photos/Results/Video, ...) those scripts create.
#
# patient.json / visit.json are new (the .bat files don't write any metadata) and live
# alongside the real folders: patient.json at the primary-folder root, visit.json inside
# each DOS folder. A patient who has been seen both clinically and for a sports eval will
# have TWO primary folders (one per tree, possibly different Lab IDs) — patient.json is
# kept in sync across whichever of the two exist.

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field, replace
from datetime import date as _date, datetime
from pathlib import Path
from typing import Optional

from patient import Patient, VisitContext
import ui_widgets as uw

VISIT_TYPES = ("Clin", "Sport")

# Defaults matching Clin_New.bat / Sport_New.bat's DEFAULT_BASE. Overridable per-session
# via set_base_dir() (e.g. after prompting the user, same fallback the .bat scripts do
# when the Q: drive isn't mounted) or persistently via apply_root()/save_root().
_DEFAULT_ROOT = Path(r"Q:\Goodsam\CTU RML Data")
STRUCTURE_SUBDIRS = {"Clin": "Clinical", "Sport": "Sports_Eval"}
_DEFAULT_BASE_DIRS = {vt: _DEFAULT_ROOT / sub for vt, sub in STRUCTURE_SUBDIRS.items()}
_base_dir_overrides: dict[str, Path] = {}

# Remembers a user-chosen root (containing both STRUCTURE_SUBDIRS folders) across
# launches, so relocating off the default Q: path only has to be done once.
_CONFIG_FILE = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "RML_PYTHON_TOOLS" / "base_dir_config.json"

# Sport_New.bat's Documents templates — copied best-effort, matching that script's own
# non-fatal handling when the source folder isn't reachable.
_SPORT_TEMPLATE_SRC = Path(r"Q:\Goodsam\CTU RML Data\Collection_Files\Sport_RTP")
_SPORT_TEMPLATES = [
    ("Master_Report_Template_v8.xlsm", "Results.xlsm"),
    ("SCORING RESULT NARRATIVE TEMPLATE_v22.docx", "Narrative.docx"),
    ("Sport_XXXX_LNAME_F_DOS_Flowsheet.xlsx", "Flowsheet.xlsx"),
]

_CLIN_SKELETON = [
    "Documents",
    "Metabolic/Data",
    "Mocap/Data", "Mocap/Video", "Mocap/V3D", "Mocap/Results", "Mocap/Exported_c3d",
    "Pedobarograph/Data", "Pedobarograph/Video",
    "Photos", "Results", "Video",
]
_SPORT_SKELETON = [
    "Documents",
    "Mocap/Data", "Mocap/Video", "Mocap/V3D", "Mocap/Results", "Mocap/Markerless", "Mocap/Exported_c3d",
    "Pedobarograph/Data", "Pedobarograph/Video",
    "Photos", "Report_Photos", "Results", "Video",
]
_SKELETONS = {"Clin": _CLIN_SKELETON, "Sport": _SPORT_SKELETON}


# ---------------------------------------------------------------------------
# Base-dir resolution (session-scoped override)
# ---------------------------------------------------------------------------

def set_base_dir(visit_type: str, path) -> None:
    """Override the base folder for a visit type for the rest of this process — e.g.
    after prompting the user because the default Q:\\... path wasn't reachable."""
    _base_dir_overrides[visit_type] = Path(path)


def get_base_dir(visit_type: str) -> Path:
    return _base_dir_overrides.get(visit_type, _DEFAULT_BASE_DIRS[visit_type])


def base_dir_available(visit_type: str) -> bool:
    return get_base_dir(visit_type).is_dir()


def structure_available() -> bool:
    """True if both the Clinical and Sports Eval base folders currently resolve to
    real folders — the combined check run at app startup."""
    return all(base_dir_available(vt) for vt in VISIT_TYPES)


def get_root_dir() -> Optional[Path]:
    """The folder containing both STRUCTURE_SUBDIRS (Clinical, Sports_Eval), i.e. what
    apply_root() was last pointed at — used by patient_db.py to place the SQLite
    index as a sibling of the real patient folders. None if no base dir resolves."""
    for visit_type in VISIT_TYPES:
        base = get_base_dir(visit_type)
        if base.is_dir():
            return base.parent
    return None


def apply_root(root) -> None:
    """Point every visit type's base dir at <root>/<STRUCTURE_SUBDIRS[visit_type]>."""
    root = Path(root)
    for visit_type, subdir in STRUCTURE_SUBDIRS.items():
        set_base_dir(visit_type, root / subdir)


def load_saved_root() -> Optional[Path]:
    try:
        data = _read_json(_CONFIG_FILE)
    except (OSError, json.JSONDecodeError):
        return None
    root = data.get("root_dir")
    return Path(root) if root else None


def save_root(root) -> None:
    _atomic_write_json(_CONFIG_FILE, {"root_dir": str(root)})


def init_saved_root() -> None:
    """Apply a previously-saved root override, if any. Call once at app startup,
    before the first structure_available() check."""
    root = load_saved_root()
    if root:
        apply_root(root)


# ---------------------------------------------------------------------------
# Naming helpers (mirror Clin_New.bat / Sport_New.bat exactly)
# ---------------------------------------------------------------------------

def _clean_component(text: str) -> str:
    """Strip quotes/spaces, matching the .bat's `set "X=!X: =!"` cleaning — no other
    sanitization, since the real system tolerates whatever characters remain."""
    return (text or "").replace('"', "").replace(" ", "")


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def first_initial(first_name: str) -> str:
    cleaned = _clean_component(first_name)
    return cleaned[:1].upper() if cleaned else ""


def format_lab_id(lab_id) -> str:
    """Zero-pad to 4 digits, 1-9999, matching the .bat's Lab Identifier validation."""
    s = str(lab_id).strip()
    if not s.isdigit():
        raise ValueError("Lab Identifier must be numeric.")
    n = int(s)
    if not (1 <= n <= 9999):
        raise ValueError("Lab Identifier must be between 1 and 9999.")
    return f"{n:04d}"


def primary_folder_name(last_name: str, first_name: str, visit_type: str, lab_id: str, mrn: str) -> str:
    last_clean = _capitalize_first(_clean_component(last_name))
    return f"{last_clean}_{first_initial(first_name)}_{visit_type}_{lab_id}_{_clean_component(mrn)}"


def file_base_stem(visit_type: str, lab_id: str, last_name: str, first_name: str, dos: str) -> str:
    last_clean = _capitalize_first(_clean_component(last_name))
    return f"{visit_type}_{lab_id}_{last_clean}_{first_initial(first_name)}_{dos}"


def _display_name(last_name: str, first_name: str) -> str:
    if last_name and first_name:
        return f"{last_name}, {first_name}"
    return last_name or first_name


def _parse_primary_folder_name(name: str) -> Optional[dict]:
    parts = name.split("_")
    if len(parts) < 5:
        return None
    mrn, lab_id, visit_type, fi = parts[-1], parts[-2], parts[-3], parts[-4]
    if visit_type not in VISIT_TYPES:
        return None
    return {"last_name": "_".join(parts[:-4]), "first_initial": fi, "visit_type": visit_type,
            "lab_id": lab_id, "mrn": mrn}


def suggest_next_lab_id(visit_type: str) -> str:
    base = get_base_dir(visit_type)
    max_id = 0
    if base.is_dir():
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            parsed = _parse_primary_folder_name(entry.name)
            if parsed and parsed["lab_id"].isdigit():
                max_id = max(max_id, int(parsed["lab_id"]))
    return f"{min(max_id + 1, 9999):04d}"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class PatientSummary:
    mrn: str
    last_name: str
    first_name: str
    date_of_birth: str = ""
    type_folders: dict = field(default_factory=dict)   # {"Clin": Path, "Sport": Path}


@dataclass
class PatientRecord:
    patient: Patient
    type_folders: dict = field(default_factory=dict)   # {"Clin": Path, "Sport": Path}
    lab_ids: dict = field(default_factory=dict)          # {"Clin": "0111", "Sport": "0203"}
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""


@dataclass
class VisitRecord:
    visit_type: str
    lab_id: str
    dos: str            # YYYYMMDD, matches the folder name
    date: str            # ISO YYYY-MM-DD
    visit_dir: Path
    bodyweight_kg: float = 0.0
    height_cm: float = 0.0
    leg_length_left_cm: float = 0.0
    leg_length_right_cm: float = 0.0
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    tests: list = field(default_factory=list)

    @property
    def visit_id(self) -> str:
        return f"{self.visit_type}_{self.dos}"


# ---------------------------------------------------------------------------
# Low-level I/O
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Patient-level operations
# ---------------------------------------------------------------------------

def list_patients() -> list[PatientSummary]:
    by_mrn: dict[str, PatientSummary] = {}
    for visit_type in VISIT_TYPES:
        base = get_base_dir(visit_type)
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            pfile = entry / "patient.json"
            if not pfile.exists():
                continue
            try:
                data = _read_json(pfile)
            except (OSError, json.JSONDecodeError):
                continue
            mrn = data.get("mrn", "")
            if not mrn:
                continue
            summary = by_mrn.get(mrn)
            if summary is None:
                summary = PatientSummary(
                    mrn=mrn, last_name=data.get("last_name", ""), first_name=data.get("first_name", ""),
                    date_of_birth=data.get("date_of_birth", ""),
                )
                by_mrn[mrn] = summary
            summary.type_folders[visit_type] = entry
    results = list(by_mrn.values())
    results.sort(key=lambda s: (s.last_name.lower(), s.first_name.lower()))
    return results


def load_patient(summary: PatientSummary) -> PatientRecord:
    lab_ids: dict[str, str] = {}
    chosen_data: Optional[dict] = None
    for visit_type, folder in summary.type_folders.items():
        try:
            data = _read_json(folder / "patient.json")
        except (OSError, json.JSONDecodeError):
            continue
        lab_ids[visit_type] = data.get("lab_id", "")
        if chosen_data is None or data.get("updated_at", "") > chosen_data.get("updated_at", ""):
            chosen_data = data

    data = chosen_data or {}
    patient = Patient(
        mrn=data.get("mrn", summary.mrn),
        last_name=data.get("last_name", summary.last_name),
        first_name=data.get("first_name", summary.first_name),
        name=_display_name(data.get("last_name", summary.last_name), data.get("first_name", summary.first_name)),
        gender=data.get("gender", 1),
        date_of_birth=data.get("date_of_birth", summary.date_of_birth),
        bodyweight_kg=data.get("latest_bodyweight_kg", 0.0),
        height=data.get("latest_height_cm", 0.0),
        leg_length_left_cm=data.get("latest_leg_length_left_cm", 0.0),
        leg_length_right_cm=data.get("latest_leg_length_right_cm", 0.0),
        diagnoses=data.get("diagnoses", []),
    )
    return PatientRecord(
        patient=patient, type_folders=dict(summary.type_folders), lab_ids=lab_ids,
        created_at=data.get("created_at", ""), updated_at=data.get("updated_at", ""),
        notes=data.get("notes", ""),
    )


def save_patient(record: PatientRecord) -> None:
    record.updated_at = datetime.now().isoformat(timespec="seconds")
    if not record.created_at:
        record.created_at = record.updated_at
    for visit_type, folder in record.type_folders.items():
        data = {
            "mrn": record.patient.mrn,
            "last_name": record.patient.last_name,
            "first_name": record.patient.first_name,
            "gender": record.patient.gender,
            "date_of_birth": record.patient.date_of_birth,
            "lab_id": record.lab_ids.get(visit_type, ""),
            "latest_bodyweight_kg": record.patient.bodyweight_kg,
            "latest_height_cm": record.patient.height,
            "latest_leg_length_left_cm": record.patient.leg_length_left_cm,
            "latest_leg_length_right_cm": record.patient.leg_length_right_cm,
            "diagnoses": record.patient.diagnoses,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "notes": record.notes,
        }
        _atomic_write_json(folder / "patient.json", data)

    try:
        import patient_db
        patient_db.index_patient(record)
    except Exception:
        pass  # the SQLite index is a best-effort cache -- never block the real save


def ensure_type_folder(record: PatientRecord, visit_type: str, lab_id) -> Path:
    """Return the patient's primary folder for visit_type, creating it (writing
    patient.json there) if this patient doesn't have one yet."""
    existing = record.type_folders.get(visit_type)
    if existing is not None:
        return existing

    lab_id = format_lab_id(lab_id)
    base = get_base_dir(visit_type)
    if not base.is_dir():
        raise FileNotFoundError(
            f"Base folder for {visit_type} visits not found: {base}\n"
            f"Call patient_store.set_base_dir('{visit_type}', <path>) to use an alternate location."
        )
    folder = base / primary_folder_name(
        record.patient.last_name, record.patient.first_name, visit_type, lab_id, record.patient.mrn
    )
    folder.mkdir(parents=True, exist_ok=True)
    record.type_folders[visit_type] = folder
    record.lab_ids[visit_type] = lab_id
    save_patient(record)
    return folder


def create_patient(mrn: str, last_name: str, first_name: str, gender: int, date_of_birth: str,
                    visit_type: str, lab_id, visit_date: str,
                    bodyweight_kg: float, height_cm: float,
                    leg_length_left_cm: float = 0.0, leg_length_right_cm: float = 0.0,
                    diagnoses: Optional[list] = None) -> PatientRecord:
    mrn = (mrn or "").strip()
    # Capitalize first letter only, matching Clin_New.bat/Sport_New.bat's own LastName
    # handling — applied to the stored identity too (not just the folder name) so the
    # UI displays it consistently.
    last_name = _capitalize_first((last_name or "").strip())
    first_name = _capitalize_first((first_name or "").strip())
    if not mrn:
        raise ValueError("MRN is required.")
    if not last_name:
        raise ValueError("Last Name is required.")
    if not first_name:
        raise ValueError("First Name is required.")
    if visit_type not in VISIT_TYPES:
        raise ValueError(f"visit_type must be one of {VISIT_TYPES}.")

    for existing in list_patients():
        if existing.mrn.strip().lower() == mrn.lower():
            raise ValueError(f"A patient with MRN '{mrn}' already exists.")

    now = datetime.now().isoformat(timespec="seconds")
    patient = Patient(
        mrn=mrn, last_name=last_name, first_name=first_name, name=_display_name(last_name, first_name),
        gender=gender, date_of_birth=date_of_birth,
        bodyweight_kg=bodyweight_kg, height=height_cm,
        leg_length_left_cm=leg_length_left_cm, leg_length_right_cm=leg_length_right_cm,
        diagnoses=diagnoses or [],
    )
    record = PatientRecord(patient=patient, created_at=now, updated_at=now)
    ensure_type_folder(record, visit_type, lab_id)
    add_visit(record, visit_type, visit_date, bodyweight_kg, height_cm, leg_length_left_cm, leg_length_right_cm)
    return record


# ---------------------------------------------------------------------------
# Visit-level operations
# ---------------------------------------------------------------------------

def _create_visit_skeleton(visit_dir: Path, visit_type: str, file_stub: str) -> None:
    for rel in _SKELETONS[visit_type]:
        (visit_dir / Path(rel)).mkdir(parents=True, exist_ok=True)
    if visit_type == "Sport":
        docs_dir = visit_dir / "Documents"
        for src_name, suffix in _SPORT_TEMPLATES:
            src = _SPORT_TEMPLATE_SRC / src_name
            if src.exists():
                try:
                    shutil.copy2(src, docs_dir / f"{file_stub}_{suffix}")
                except OSError:
                    pass  # best-effort, mirrors Sport_New.bat's own non-fatal copy failures


def add_visit(record: PatientRecord, visit_type: str, date_iso: str,
              bodyweight_kg: float, height_cm: float,
              leg_length_left_cm: float = 0.0, leg_length_right_cm: float = 0.0,
              notes: str = "", lab_id=None) -> VisitRecord:
    if visit_type not in record.type_folders:
        if lab_id is None:
            raise ValueError(f"Patient has no {visit_type} folder yet; pass lab_id to create one.")
        ensure_type_folder(record, visit_type, lab_id)

    folder = record.type_folders[visit_type]
    dos = date_iso.replace("-", "")
    visit_dir = folder / dos

    if (visit_dir / "visit.json").exists():
        # Same-day visit already exists in this tree — reuse it (mirrors what running
        # Clin_New.bat/Sport_New.bat a second time for the same DOS would do: land in
        # the same folder) rather than silently colliding.
        return load_visit(visit_dir)

    file_stub = file_base_stem(visit_type, record.lab_ids[visit_type],
                                record.patient.last_name, record.patient.first_name, dos)
    _create_visit_skeleton(visit_dir, visit_type, file_stub)

    now = datetime.now().isoformat(timespec="seconds")
    visit = VisitRecord(
        visit_type=visit_type, lab_id=record.lab_ids[visit_type], dos=dos, date=date_iso, visit_dir=visit_dir,
        bodyweight_kg=bodyweight_kg, height_cm=height_cm,
        leg_length_left_cm=leg_length_left_cm, leg_length_right_cm=leg_length_right_cm,
        notes=notes, created_at=now, updated_at=now, tests=[],
    )
    save_visit(visit)

    record.patient.bodyweight_kg = bodyweight_kg
    record.patient.height = height_cm
    record.patient.leg_length_left_cm = leg_length_left_cm
    record.patient.leg_length_right_cm = leg_length_right_cm
    save_patient(record)

    return visit


def list_visits(record: PatientRecord) -> list[VisitRecord]:
    visits = []
    for visit_type, folder in record.type_folders.items():
        if not folder.exists():
            continue
        for entry in sorted(folder.iterdir()):
            if not entry.is_dir() or not (entry.name.isdigit() and len(entry.name) == 8):
                continue
            if not (entry / "visit.json").exists():
                continue
            try:
                visits.append(load_visit(entry))
            except (OSError, json.JSONDecodeError):
                continue
    visits.sort(key=lambda v: (v.date, v.visit_type))
    return visits


def load_visit(visit_dir: Path) -> VisitRecord:
    visit_dir = Path(visit_dir)
    data = _read_json(visit_dir / "visit.json")
    return VisitRecord(
        visit_type=data.get("visit_type", ""),
        lab_id=data.get("lab_id", ""),
        dos=data.get("dos", visit_dir.name),
        date=data.get("date", ""),
        visit_dir=visit_dir,
        bodyweight_kg=data.get("bodyweight_kg", 0.0),
        height_cm=data.get("height_cm", 0.0),
        leg_length_left_cm=data.get("leg_length_left_cm", 0.0),
        leg_length_right_cm=data.get("leg_length_right_cm", 0.0),
        notes=data.get("notes", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        tests=data.get("tests", []),
    )


def save_visit(record: VisitRecord) -> None:
    record.updated_at = datetime.now().isoformat(timespec="seconds")
    if not record.created_at:
        record.created_at = record.updated_at
    data = {
        "visit_type": record.visit_type,
        "lab_id": record.lab_id,
        "dos": record.dos,
        "date": record.date,
        "bodyweight_kg": record.bodyweight_kg,
        "height_cm": record.height_cm,
        "leg_length_left_cm": record.leg_length_left_cm,
        "leg_length_right_cm": record.leg_length_right_cm,
        "notes": record.notes,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "tests": record.tests,
    }
    _atomic_write_json(record.visit_dir / "visit.json", data)

    try:
        import patient_db
        patient_db.index_visit(record)
    except Exception:
        pass  # the SQLite index is a best-effort cache -- never block the real save


def record_test_result(visit: VisitRecord, module_name: str, slug: str, display_name: str,
                        status: str, output_dir=None, output_files=None,
                        summary: Optional[dict] = None, error: Optional[str] = None) -> dict:
    now = datetime.now()
    entry = {
        "test_id": f"{slug}_{now.strftime('%Y%m%dT%H%M%S')}",
        "module": module_name,
        "slug": slug,
        "display_name": display_name,
        "run_at": now.isoformat(timespec="seconds"),
        "status": status,
        "output_dir": str(output_dir) if output_dir else None,
        "output_files": [str(p) for p in (output_files or [])],
        "summary": summary or {},
        "error": error,
    }
    visit.tests.append(entry)
    save_visit(visit)
    return entry


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------

def build_visit_context(patient_record: PatientRecord, visit_record: VisitRecord, root=None) -> VisitContext:
    age_years: Optional[int] = None
    dob_iso = patient_record.patient.date_of_birth
    if dob_iso and visit_record.date:
        try:
            b = _date.fromisoformat(dob_iso)
            v = _date.fromisoformat(visit_record.date)
            age_years = uw.age_years_int(b, v)
        except ValueError:
            age_years = None

    patient_for_context = replace(
        patient_record.patient,
        height=visit_record.height_cm,
        age=float(age_years) if age_years is not None else patient_record.patient.age,
        date=visit_record.date,
        bodyweight_kg=visit_record.bodyweight_kg,
        leg_length_left_cm=visit_record.leg_length_left_cm,
        leg_length_right_cm=visit_record.leg_length_right_cm,
    )

    file_stub = file_base_stem(visit_record.visit_type, visit_record.lab_id,
                                patient_record.patient.last_name, patient_record.patient.first_name,
                                visit_record.dos)

    return VisitContext(
        patient=patient_for_context,
        visit_date=visit_record.date,
        visit_id=visit_record.visit_id,
        visit_dir=visit_record.visit_dir,
        visit_type=visit_record.visit_type,
        lab_id=visit_record.lab_id,
        file_stub=file_stub,
        age_years=age_years,
        root=root,
    )
