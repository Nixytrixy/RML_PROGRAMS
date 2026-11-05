# patient_db.py
# A SQLite index layered on top of the real patient_store.py (patient.json/visit.json
# + folder tree) persistence. This DB is a DERIVED, REBUILDABLE CACHE -- never the
# source of truth. It exists so patient_manager_ui.py's query-builder screen ("Patient
# Select") can filter patients/visits by attribute without scanning folders/JSON live.
#
# Kept live two ways:
#   - incremental: patient_store.save_patient()/save_visit() call index_patient()/
#     index_visit() after every real write (best-effort, non-fatal -- see those hooks).
#   - full: rebuild_index() rescans everything on disk from scratch. This is the
#     recovery path if the DB file is ever missing, stale, or corrupted.

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date as _date
from pathlib import Path
from typing import Optional

import admin_catalog
import patient_store

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS visit_types (
    code TEXT PRIMARY KEY,
    label TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS genders (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS test_statuses (
    code TEXT PRIMARY KEY,
    label TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS modules (
    slug TEXT PRIMARY KEY,
    module_name TEXT NOT NULL,
    display_name TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS patients (
    mrn TEXT PRIMARY KEY,
    last_name TEXT NOT NULL,
    first_name TEXT NOT NULL,
    gender INTEGER CONSTRAINT fk_patients_gender REFERENCES genders(code),
    date_of_birth TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS patient_folders (
    mrn TEXT NOT NULL CONSTRAINT fk_patient_folders_mrn REFERENCES patients(mrn) ON DELETE CASCADE,
    visit_type TEXT NOT NULL CONSTRAINT fk_patient_folders_visit_type REFERENCES visit_types(code),
    lab_id TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    PRIMARY KEY (mrn, visit_type)
) STRICT;

CREATE TABLE IF NOT EXISTS visits (
    visit_pk INTEGER PRIMARY KEY,
    mrn TEXT NOT NULL CONSTRAINT fk_visits_mrn REFERENCES patients(mrn) ON DELETE CASCADE,
    visit_type TEXT NOT NULL CONSTRAINT fk_visits_visit_type REFERENCES visit_types(code),
    lab_id TEXT NOT NULL,
    dos TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    visit_dir TEXT NOT NULL,
    bodyweight_kg REAL,
    height_cm REAL,
    leg_length_left_cm REAL,
    leg_length_right_cm REAL,
    age_at_visit_years INTEGER,
    mocap_has_data INTEGER NOT NULL DEFAULT 0,
    mocap_has_results INTEGER NOT NULL DEFAULT 0,
    pedobarograph_has_data INTEGER NOT NULL DEFAULT 0,
    pedobarograph_has_results INTEGER NOT NULL DEFAULT 0,
    metabolic_has_data INTEGER NOT NULL DEFAULT 0,
    metabolic_has_results INTEGER NOT NULL DEFAULT 0,
    photos_present INTEGER NOT NULL DEFAULT 0,
    report_photos_present INTEGER NOT NULL DEFAULT 0,
    video_present INTEGER NOT NULL DEFAULT 0,
    documents_present INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (mrn, visit_type, dos)
) STRICT;

CREATE TABLE IF NOT EXISTS tests (
    test_pk INTEGER PRIMARY KEY,
    visit_pk INTEGER NOT NULL CONSTRAINT fk_tests_visit_pk REFERENCES visits(visit_pk) ON DELETE CASCADE,
    test_id TEXT NOT NULL,
    slug TEXT NOT NULL CONSTRAINT fk_tests_slug REFERENCES modules(slug),
    display_name TEXT NOT NULL,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL CONSTRAINT fk_tests_status REFERENCES test_statuses(code),
    output_dir TEXT,
    error TEXT,
    UNIQUE (visit_pk, test_id)
) STRICT;

CREATE TABLE IF NOT EXISTS test_output_files (
    test_pk INTEGER NOT NULL CONSTRAINT fk_test_output_files_test_pk REFERENCES tests(test_pk) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    PRIMARY KEY (test_pk, file_path)
) STRICT;

CREATE TABLE IF NOT EXISTS diagnosis_types (
    name TEXT PRIMARY KEY
) STRICT;

CREATE TABLE IF NOT EXISTS diagnosis_subtypes (
    diagnosis_type TEXT NOT NULL CONSTRAINT fk_diagnosis_subtypes_type REFERENCES diagnosis_types(name) ON DELETE CASCADE,
    name TEXT NOT NULL,
    PRIMARY KEY (diagnosis_type, name)
) STRICT;

CREATE TABLE IF NOT EXISTS patient_diagnoses (
    diagnosis_pk INTEGER PRIMARY KEY,
    mrn TEXT NOT NULL CONSTRAINT fk_patient_diagnoses_mrn REFERENCES patients(mrn) ON DELETE CASCADE,
    diagnosis TEXT NOT NULL,
    subtype TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT ''
) STRICT;
"""

_VISIT_TYPE_SEED = [("Clin", "Clinical"), ("Sport", "Sports Eval")]
_GENDER_SEED = [(1, "Male"), (0, "Female")]
_TEST_STATUS_SEED = [("success", "Success"), ("error", "Error"), ("cancelled", "Cancelled")]

# Relative subfolders (matching patient_store._CLIN_SKELETON/_SPORT_SKELETON) that
# back each modality's has_data/has_results flags. "data"/"results" lists are
# OR'd together -- any non-empty folder in the list sets that flag.
_MODALITY_FOLDERS = {
    "mocap": {
        "data": ["Mocap/Data"],
        "results": ["Mocap/Results", "Mocap/Exported_c3d", "Mocap/V3D", "Mocap/Markerless"],
    },
    "pedobarograph": {
        "data": ["Pedobarograph/Data"],
        "results": ["Pedobarograph/Results", "Pedobarograph/Code"],
    },
    "metabolic": {
        "data": ["Metabolic/Data"],
        "results": ["Metabolic/Results"],
    },
}
# Presence-only (no data/results distinction) modalities -> single relative folder.
_PRESENCE_FOLDERS = {
    "photos": "Photos",
    "report_photos": "Report_Photos",
    "video": "Video",
    "documents": "Documents",
}


def get_db_path() -> Path:
    root = patient_store.get_root_dir()
    if root is not None:
        return root / "patient_index.db"
    # Fallback alongside the saved-root config, matching patient_store's own
    # fallback location when the network share isn't reachable.
    base = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "RML_PYTHON_TOOLS"
    base.mkdir(parents=True, exist_ok=True)
    return base / "patient_index.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_db_path()))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA_SQL)
    _seed_lookup_tables(conn)
    conn.commit()
    return conn


def _seed_lookup_tables(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT OR IGNORE INTO visit_types (code, label) VALUES (?, ?)", _VISIT_TYPE_SEED)
    conn.executemany("INSERT OR IGNORE INTO genders (code, label) VALUES (?, ?)", _GENDER_SEED)
    conn.executemany("INSERT OR IGNORE INTO test_statuses (code, label) VALUES (?, ?)", _TEST_STATUS_SEED)

    try:
        import analysis_registry
        for method in analysis_registry.REGISTRY:
            try:
                mod = importlib_module(method.module_name)
                display_name = mod.name()
            except Exception:
                display_name = method.module_name
            conn.execute(
                "INSERT OR IGNORE INTO modules (slug, module_name, display_name) VALUES (?, ?, ?)",
                (method.slug, method.module_name, display_name),
            )
    except Exception:
        pass  # module seeding is best-effort -- a broken module shouldn't block the DB

    _reseed_diagnosis_catalog(conn)


def _reseed_diagnosis_catalog(conn: sqlite3.Connection) -> None:
    """Unlike the INSERT-OR-IGNORE-only lookup tables above, the diagnosis catalog
    is admin-editable and can SHRINK (a type/subtype can be removed in the Admin
    page), so it needs a full delete-then-reinsert on every connect() to actually
    reflect removals -- not just additive seeding."""
    conn.execute("DELETE FROM diagnosis_subtypes")
    conn.execute("DELETE FROM diagnosis_types")
    for dtype, subtypes in admin_catalog.get_diagnosis_catalog().items():
        conn.execute("INSERT INTO diagnosis_types (name) VALUES (?)", (dtype,))
        for sub in subtypes:
            conn.execute("INSERT INTO diagnosis_subtypes (diagnosis_type, name) VALUES (?, ?)", (dtype, sub))


def importlib_module(name: str):
    import importlib
    return importlib.import_module(name)


def _folder_has_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    for _root, _dirs, files in os.walk(path):
        if files:
            return True
    return False


def _modality_flags(visit_dir: Path) -> dict:
    flags = {}
    for modality, rels in _MODALITY_FOLDERS.items():
        flags[f"{modality}_has_data"] = int(any(_folder_has_files(visit_dir / rel) for rel in rels["data"]))
        flags[f"{modality}_has_results"] = int(any(_folder_has_files(visit_dir / rel) for rel in rels["results"]))
    for key, rel in _PRESENCE_FOLDERS.items():
        flags[f"{key}_present"] = int(_folder_has_files(visit_dir / rel))
    return flags


def index_patient(record: "patient_store.PatientRecord") -> None:
    p = record.patient
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO patients (mrn, last_name, first_name, gender, date_of_birth,
                                      notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(mrn) DO UPDATE SET
                   last_name=excluded.last_name, first_name=excluded.first_name,
                   gender=excluded.gender, date_of_birth=excluded.date_of_birth,
                   notes=excluded.notes, updated_at=excluded.updated_at""",
            (p.mrn, p.last_name, p.first_name, p.gender, p.date_of_birth,
             record.notes, record.created_at, record.updated_at),
        )
        for visit_type, folder in record.type_folders.items():
            conn.execute(
                """INSERT INTO patient_folders (mrn, visit_type, lab_id, folder_path)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(mrn, visit_type) DO UPDATE SET
                       lab_id=excluded.lab_id, folder_path=excluded.folder_path""",
                (p.mrn, visit_type, record.lab_ids.get(visit_type, ""), str(folder)),
            )

        conn.execute("DELETE FROM patient_diagnoses WHERE mrn = ?", (p.mrn,))
        for entry in (p.diagnoses or []):
            conn.execute(
                "INSERT INTO patient_diagnoses (mrn, diagnosis, subtype, side) VALUES (?, ?, ?, ?)",
                (p.mrn, entry.get("diagnosis", ""), entry.get("subtype", ""), entry.get("side", "")),
            )
        conn.commit()
    finally:
        conn.close()


def _mrn_for_visit(visit_dir: Path) -> Optional[str]:
    try:
        with open(visit_dir.parent / "patient.json", "r", encoding="utf-8") as f:
            return json.load(f).get("mrn") or None
    except (OSError, json.JSONDecodeError):
        return None


def index_visit(record: "patient_store.VisitRecord") -> None:
    mrn = _mrn_for_visit(record.visit_dir)
    if not mrn:
        return  # no patient.json to attribute this visit to -- nothing to index

    age_at_visit = None
    try:
        with open(record.visit_dir.parent / "patient.json", "r", encoding="utf-8") as f:
            dob_iso = json.load(f).get("date_of_birth") or ""
        if dob_iso and record.date:
            b = _date.fromisoformat(dob_iso)
            v = _date.fromisoformat(record.date)
            years = v.year - b.year
            if (v.month, v.day) < (b.month, b.day):
                years -= 1
            age_at_visit = max(years, 0)
    except (OSError, json.JSONDecodeError, ValueError):
        pass

    flags = _modality_flags(record.visit_dir)

    conn = connect()
    try:
        conn.execute(
            """INSERT INTO visits (mrn, visit_type, lab_id, dos, visit_date, visit_dir,
                                    bodyweight_kg, height_cm, leg_length_left_cm, leg_length_right_cm,
                                    age_at_visit_years,
                                    mocap_has_data, mocap_has_results,
                                    pedobarograph_has_data, pedobarograph_has_results,
                                    metabolic_has_data, metabolic_has_results,
                                    photos_present, report_photos_present, video_present, documents_present,
                                    notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(mrn, visit_type, dos) DO UPDATE SET
                   lab_id=excluded.lab_id, visit_date=excluded.visit_date, visit_dir=excluded.visit_dir,
                   bodyweight_kg=excluded.bodyweight_kg, height_cm=excluded.height_cm,
                   leg_length_left_cm=excluded.leg_length_left_cm, leg_length_right_cm=excluded.leg_length_right_cm,
                   age_at_visit_years=excluded.age_at_visit_years,
                   mocap_has_data=excluded.mocap_has_data, mocap_has_results=excluded.mocap_has_results,
                   pedobarograph_has_data=excluded.pedobarograph_has_data,
                   pedobarograph_has_results=excluded.pedobarograph_has_results,
                   metabolic_has_data=excluded.metabolic_has_data, metabolic_has_results=excluded.metabolic_has_results,
                   photos_present=excluded.photos_present, report_photos_present=excluded.report_photos_present,
                   video_present=excluded.video_present, documents_present=excluded.documents_present,
                   notes=excluded.notes, updated_at=excluded.updated_at""",
            (mrn, record.visit_type, record.lab_id, record.dos, record.date, str(record.visit_dir),
             record.bodyweight_kg, record.height_cm, record.leg_length_left_cm, record.leg_length_right_cm,
             age_at_visit,
             flags["mocap_has_data"], flags["mocap_has_results"],
             flags["pedobarograph_has_data"], flags["pedobarograph_has_results"],
             flags["metabolic_has_data"], flags["metabolic_has_results"],
             flags["photos_present"], flags["report_photos_present"], flags["video_present"],
             flags["documents_present"],
             record.notes, record.created_at, record.updated_at),
        )
        visit_pk = conn.execute(
            "SELECT visit_pk FROM visits WHERE mrn = ? AND visit_type = ? AND dos = ?",
            (mrn, record.visit_type, record.dos),
        ).fetchone()[0]

        existing_test_ids = {row[0] for row in conn.execute(
            "SELECT test_id FROM tests WHERE visit_pk = ?", (visit_pk,)
        )}
        current_test_ids = {t.get("test_id") for t in record.tests}
        stale = existing_test_ids - current_test_ids
        if stale:
            conn.executemany("DELETE FROM tests WHERE visit_pk = ? AND test_id = ?",
                              [(visit_pk, tid) for tid in stale])

        for test in record.tests:
            conn.execute(
                """INSERT INTO tests (visit_pk, test_id, slug, display_name, run_at, status, output_dir, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(visit_pk, test_id) DO UPDATE SET
                       slug=excluded.slug, display_name=excluded.display_name, run_at=excluded.run_at,
                       status=excluded.status, output_dir=excluded.output_dir, error=excluded.error""",
                (visit_pk, test.get("test_id", ""), test.get("slug", ""), test.get("display_name", ""),
                 test.get("run_at", ""), test.get("status", "success"), test.get("output_dir"), test.get("error")),
            )
            test_pk = conn.execute(
                "SELECT test_pk FROM tests WHERE visit_pk = ? AND test_id = ?",
                (visit_pk, test.get("test_id", "")),
            ).fetchone()[0]
            conn.execute("DELETE FROM test_output_files WHERE test_pk = ?", (test_pk,))
            files = test.get("output_files") or []
            if files:
                conn.executemany(
                    "INSERT OR IGNORE INTO test_output_files (test_pk, file_path) VALUES (?, ?)",
                    [(test_pk, f) for f in files],
                )
        conn.commit()
    finally:
        conn.close()


def rebuild_index() -> dict:
    """Full rescan from the real folders/JSON. Drops and repopulates every table --
    the one-button recovery path for drift or a missing/corrupt DB file."""
    conn = connect()
    try:
        for table in ("test_output_files", "tests", "visits", "patient_diagnoses", "patient_folders", "patients"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()

    patients_count = 0
    visits_count = 0
    for summary in patient_store.list_patients():
        record = patient_store.load_patient(summary)
        index_patient(record)
        patients_count += 1
        for visit in patient_store.list_visits(record):
            index_visit(visit)
            visits_count += 1

    return {"patients": patients_count, "visits": visits_count}
