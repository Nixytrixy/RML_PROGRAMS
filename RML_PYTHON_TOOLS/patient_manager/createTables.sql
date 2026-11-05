-- Reference copy of the SQLite schema used by RML_PYTHON_TOOLS/patient_manager/
-- patient_db.py to index patient/visit metadata for the "Patient Select"
-- advanced-search screen in patient_manager_ui.py.
--
-- This database is a DERIVED, REBUILDABLE CACHE. The real source of truth is the
-- patient folder tree on the network share (see "Folder Tree.txt") plus the
-- patient.json/visit.json files written by patient_store.py. If this DB is ever
-- missing, stale, or corrupted, patient_db.rebuild_index() regenerates it entirely
-- from those real files -- nothing here should ever be treated as authoritative.
--
-- The code's actual source of truth for this schema is the _SCHEMA_SQL constant in
-- RML_PYTHON_TOOLS/patient_manager/patient_db.py -- keep this file in sync with it by hand.

PRAGMA foreign_keys = ON;

-- Lookup/enum tables (also used to populate the query-builder UI's dropdowns)

CREATE TABLE IF NOT EXISTS visit_types (
    code TEXT PRIMARY KEY,
    label TEXT NOT NULL
) STRICT;
-- ('Clin','Clinical'), ('Sport','Sports Eval')

CREATE TABLE IF NOT EXISTS genders (
    code INTEGER PRIMARY KEY,
    label TEXT NOT NULL
) STRICT;
-- (1,'Male'), (0,'Female')  -- matches Patient.gender's existing int convention

CREATE TABLE IF NOT EXISTS test_statuses (
    code TEXT PRIMARY KEY,
    label TEXT NOT NULL
) STRICT;
-- ('success','Success'), ('error','Error'), ('cancelled','Cancelled')

CREATE TABLE IF NOT EXISTS modules (
    slug TEXT PRIMARY KEY,
    module_name TEXT NOT NULL,
    display_name TEXT NOT NULL
) STRICT;
-- seeded from analysis_registry.REGISTRY + each module's name()

-- Core entity tables

CREATE TABLE IF NOT EXISTS patients (
    mrn TEXT PRIMARY KEY,
    last_name TEXT NOT NULL,
    first_name TEXT NOT NULL,
    gender INTEGER REFERENCES genders(code),
    date_of_birth TEXT,                 -- ISO YYYY-MM-DD
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS patient_folders (
    -- a patient may have a Clinical folder, a Sports Eval folder, or both
    mrn TEXT NOT NULL REFERENCES patients(mrn) ON DELETE CASCADE,
    visit_type TEXT NOT NULL REFERENCES visit_types(code),
    lab_id TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    PRIMARY KEY (mrn, visit_type)
) STRICT;

CREATE TABLE IF NOT EXISTS visits (
    visit_pk INTEGER PRIMARY KEY,
    mrn TEXT NOT NULL REFERENCES patients(mrn) ON DELETE CASCADE,
    visit_type TEXT NOT NULL REFERENCES visit_types(code),
    lab_id TEXT NOT NULL,
    dos TEXT NOT NULL,                  -- YYYYMMDD, matches the folder name
    visit_date TEXT NOT NULL,           -- ISO YYYY-MM-DD
    visit_dir TEXT NOT NULL,
    bodyweight_kg REAL,
    height_cm REAL,
    leg_length_left_cm REAL,
    leg_length_right_cm REAL,
    age_at_visit_years INTEGER,         -- derived from patients.date_of_birth at index time

    -- Modality presence, flattened as plain boolean (0/1) columns rather than a
    -- normalized side table, so the query builder's SQL is a flat WHERE clause with
    -- no subqueries for these fields. Only Mocap/Pedobarograph/Metabolic distinguish
    -- "collected" vs "processed", per the folder tree's own Data vs Results notes;
    -- the rest are presence-only.
    mocap_has_data INTEGER NOT NULL DEFAULT 0,
    mocap_has_results INTEGER NOT NULL DEFAULT 0,
    pedobarograph_has_data INTEGER NOT NULL DEFAULT 0,
    pedobarograph_has_results INTEGER NOT NULL DEFAULT 0,
    metabolic_has_data INTEGER NOT NULL DEFAULT 0,      -- Clinical visits only
    metabolic_has_results INTEGER NOT NULL DEFAULT 0,
    photos_present INTEGER NOT NULL DEFAULT 0,
    report_photos_present INTEGER NOT NULL DEFAULT 0,   -- Sports_Eval only
    video_present INTEGER NOT NULL DEFAULT 0,
    documents_present INTEGER NOT NULL DEFAULT 0,

    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (mrn, visit_type, dos)
) STRICT;

CREATE TABLE IF NOT EXISTS tests (
    -- one row per visit.json tests[] entry (written by patient_store.record_test_result)
    test_pk INTEGER PRIMARY KEY,
    visit_pk INTEGER NOT NULL REFERENCES visits(visit_pk) ON DELETE CASCADE,
    test_id TEXT NOT NULL,
    slug TEXT NOT NULL REFERENCES modules(slug),
    display_name TEXT NOT NULL,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL REFERENCES test_statuses(code),
    output_dir TEXT,
    error TEXT,
    UNIQUE (visit_pk, test_id)
) STRICT;

CREATE TABLE IF NOT EXISTS test_output_files (
    test_pk INTEGER NOT NULL REFERENCES tests(test_pk) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    PRIMARY KEY (test_pk, file_path)
) STRICT;
