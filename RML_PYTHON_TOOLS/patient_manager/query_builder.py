# query_builder.py
# Translates "Patient Select" dropdown conditions (field, operator, value) into a
# parameterized SQL query against patient_db.py's SQLite index. Field and operator
# are always chosen from the fixed whitelists below (never free text), and every
# value is bound as a "?" parameter -- there is no path from user input to raw SQL.

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

import patient_db

TEXT, INTEGER, REAL, DATE, ENUM, BOOL, MODULE_RUN, DIAGNOSIS = (
    "TEXT", "INTEGER", "REAL", "DATE", "ENUM", "BOOL", "MODULE_RUN", "DIAGNOSIS",
)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    table: str            # "p" (patients) or "v" (visits) -- ignored for MODULE_RUN
    column: str
    value_type: str
    enum_source: Optional[str] = None   # lookup table name, for ENUM fields


FIELD_CATALOG: list[Field] = [
    Field("mrn", "MRN", "p", "mrn", TEXT),
    Field("last_name", "Last Name", "p", "last_name", TEXT),
    Field("first_name", "First Name", "p", "first_name", TEXT),
    Field("gender", "Gender", "p", "gender", ENUM, enum_source="genders"),
    Field("date_of_birth", "Date of Birth", "p", "date_of_birth", DATE),

    Field("visit_type", "Visit Type", "v", "visit_type", ENUM, enum_source="visit_types"),
    Field("visit_date", "Visit Date", "v", "visit_date", DATE),
    Field("age_at_visit_years", "Age at Visit (years)", "v", "age_at_visit_years", INTEGER),
    Field("bodyweight_kg", "Bodyweight (kg)", "v", "bodyweight_kg", REAL),
    Field("height_cm", "Height (cm)", "v", "height_cm", REAL),
    Field("leg_length_left_cm", "Leg Length Left (cm)", "v", "leg_length_left_cm", REAL),
    Field("leg_length_right_cm", "Leg Length Right (cm)", "v", "leg_length_right_cm", REAL),

    Field("mocap_has_data", "Mocap Data Collected", "v", "mocap_has_data", BOOL),
    Field("mocap_has_results", "Mocap Results Processed", "v", "mocap_has_results", BOOL),
    Field("pedobarograph_has_data", "Pedobarograph Data Collected", "v", "pedobarograph_has_data", BOOL),
    Field("pedobarograph_has_results", "Pedobarograph Results Processed", "v", "pedobarograph_has_results", BOOL),
    Field("metabolic_has_data", "Metabolic Data Collected", "v", "metabolic_has_data", BOOL),
    Field("metabolic_has_results", "Metabolic Results Processed", "v", "metabolic_has_results", BOOL),
    Field("photos_present", "Photos Present", "v", "photos_present", BOOL),
    Field("report_photos_present", "Report Photos Present", "v", "report_photos_present", BOOL),
    Field("video_present", "Video Present", "v", "video_present", BOOL),
    Field("documents_present", "Documents Present", "v", "documents_present", BOOL),

    Field("module_run", "Test Run (module)", "", "", MODULE_RUN, enum_source="modules"),

    Field("diagnosis", "Diagnosis", "", "", DIAGNOSIS, enum_source="diagnosis_types"),
]
_FIELDS_BY_KEY = {f.key: f for f in FIELD_CATALOG}

# operator key -> (label, sql template using {col} and the right number of "?")
OPERATORS_BY_TYPE = {
    TEXT: [
        ("equals", "equals", "{col} = ?"),
        ("contains", "contains", "{col} LIKE ?"),
        ("starts_with", "starts with", "{col} LIKE ?"),
    ],
    INTEGER: [
        ("eq", "=", "{col} = ?"), ("ne", "!=", "{col} != ?"),
        ("lt", "<", "{col} < ?"), ("le", "<=", "{col} <= ?"),
        ("gt", ">", "{col} > ?"), ("ge", ">=", "{col} >= ?"),
        ("between", "between", "{col} BETWEEN ? AND ?"),
    ],
    REAL: [
        ("eq", "=", "{col} = ?"), ("ne", "!=", "{col} != ?"),
        ("lt", "<", "{col} < ?"), ("le", "<=", "{col} <= ?"),
        ("gt", ">", "{col} > ?"), ("ge", ">=", "{col} >= ?"),
        ("between", "between", "{col} BETWEEN ? AND ?"),
    ],
    DATE: [
        ("on", "on", "{col} = ?"),
        ("before", "before", "{col} < ?"),
        ("after", "after", "{col} > ?"),
        ("between", "between", "{col} BETWEEN ? AND ?"),
    ],
    ENUM: [
        ("is", "is", "{col} = ?"),
        ("is_not", "is not", "{col} != ?"),
    ],
    BOOL: [
        ("is_true", "is true", "{col} = 1"),
        ("is_false", "is false", "{col} = 0"),
    ],
    MODULE_RUN: [
        ("was_run", "was run", None),       # built specially in build_query
        ("was_not_run", "was not run", None),
    ],
    DIAGNOSIS: [
        ("has", "has", None),               # built specially in build_query
        ("does_not_have", "does not have", None),
    ],
}


def field_keys() -> list[str]:
    return [f.key for f in FIELD_CATALOG]


def get_field(key: str) -> Field:
    return _FIELDS_BY_KEY[key]


def operators_for(value_type: str) -> list[tuple[str, str]]:
    return [(code, label) for code, label, _tpl in OPERATORS_BY_TYPE[value_type]]


def get_enum_values(conn: sqlite3.Connection, lookup_table: str) -> list[tuple]:
    if lookup_table == "modules":
        return conn.execute("SELECT slug, display_name FROM modules").fetchall()
    if lookup_table == "diagnosis_types":
        return conn.execute("SELECT name, name FROM diagnosis_types ORDER BY name").fetchall()
    if lookup_table not in ("genders", "visit_types", "test_statuses"):
        raise ValueError(f"Unknown lookup table: {lookup_table!r}")
    return conn.execute(f"SELECT code, label FROM {lookup_table}").fetchall()


def get_diagnosis_subtypes(conn: sqlite3.Connection, diagnosis_type: str) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM diagnosis_subtypes WHERE diagnosis_type = ? ORDER BY name",
        (diagnosis_type,),
    )
    return [r[0] for r in rows]


def get_pending_diagnosis_submissions(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Distinct (diagnosis, subtype) pairs in use on patients that aren't in the
    admin-curated catalog yet -- i.e. free-typed "Other" entries awaiting approval.
    Purely derived from patient_diagnoses; nothing about "pending" is ever stored."""
    return conn.execute(
        """SELECT DISTINCT pd.diagnosis, pd.subtype
           FROM patient_diagnoses pd
           WHERE pd.diagnosis NOT IN (SELECT name FROM diagnosis_types)
              OR (pd.subtype <> '' AND NOT EXISTS (
                    SELECT 1 FROM diagnosis_subtypes ds
                    WHERE ds.diagnosis_type = pd.diagnosis AND ds.name = pd.subtype))
           ORDER BY pd.diagnosis, pd.subtype"""
    ).fetchall()


@dataclass
class Condition:
    field_key: str
    operator_key: str
    value: object = None       # single value, or (low, high) for "between"


def _condition_to_sql(cond: Condition) -> tuple[str, list]:
    """Translate one Condition into a WHERE-clause fragment + its bound params.
    Shared by build_query() and build_lacking_data_query() so the two never drift."""
    field = get_field(cond.field_key)
    op_entries = {code: (label, tpl) for code, label, tpl in OPERATORS_BY_TYPE[field.value_type]}
    if cond.operator_key not in op_entries:
        raise ValueError(f"Operator {cond.operator_key!r} not valid for field {field.key!r}")
    _label, tpl = op_entries[cond.operator_key]

    if field.value_type == MODULE_RUN:
        sub = ("SELECT 1 FROM tests t WHERE t.visit_pk = v.visit_pk AND t.slug = ? "
               "AND t.status = 'success'")
        frag = f"EXISTS ({sub})" if cond.operator_key == "was_run" else f"NOT EXISTS ({sub})"
        return frag, [cond.value]

    if field.value_type == DIAGNOSIS:
        preds = ["pd.mrn = p.mrn"]
        params = []
        if cond.value.get("diagnosis") is not None:
            preds.append("pd.diagnosis = ?")
            params.append(cond.value["diagnosis"])
        if cond.value.get("subtype"):
            preds.append("pd.subtype = ?")
            params.append(cond.value["subtype"])
        if cond.value.get("side"):
            preds.append("pd.side = ?")
            params.append(cond.value["side"])
        sub = f"SELECT 1 FROM patient_diagnoses pd WHERE {' AND '.join(preds)}"
        frag = f"EXISTS ({sub})" if cond.operator_key == "has" else f"NOT EXISTS ({sub})"
        return frag, params

    col = f"{field.table}.{field.column}"

    if field.value_type == BOOL:
        return tpl.format(col=col), []

    if cond.operator_key == "between":
        low, high = cond.value
        return tpl.format(col=col), [low, high]
    if field.value_type == TEXT and cond.operator_key == "contains":
        return tpl.format(col=col), [f"%{cond.value}%"]
    if field.value_type == TEXT and cond.operator_key == "starts_with":
        return tpl.format(col=col), [f"{cond.value}%"]
    return tpl.format(col=col), [cond.value]


def build_query(conditions: list[Condition], combine: str = "AND") -> tuple[str, list]:
    if combine not in ("AND", "OR"):
        raise ValueError("combine must be 'AND' or 'OR'")

    where_parts: list[str] = []
    params: list = []
    for cond in conditions:
        frag, p = _condition_to_sql(cond)
        where_parts.append(frag)
        params.extend(p)

    sql = "SELECT DISTINCT p.mrn, p.last_name, p.first_name, p.date_of_birth FROM patients p JOIN visits v ON v.mrn = p.mrn"
    if where_parts:
        sql += " WHERE " + f" {combine} ".join(where_parts)
    sql += " ORDER BY p.last_name, p.first_name"
    return sql, params


def run_query(conn: sqlite3.Connection, conditions: list[Condition], combine: str = "AND") -> list[tuple]:
    sql, params = build_query(conditions, combine)
    return conn.execute(sql, params).fetchall()


def build_lacking_data_query(
    conditions: list[Condition], required_keys: set[str], exclude_mrns: list[str], combine: str = "AND"
) -> Optional[tuple[str, list]]:
    """People who'd otherwise match every OTHER (non-required-field) condition in
    this search, but are missing a value for a required field this search actually
    references. Returns None if no condition touches a required field at all --
    callers don't need to pre-check."""
    required_conds = [c for c in conditions if c.field_key in required_keys]
    if not required_conds:
        return None

    other_conds = [c for c in conditions if c.field_key not in required_keys]
    other_frags: list[str] = []
    params: list = []
    for cond in other_conds:
        frag, p = _condition_to_sql(cond)
        other_frags.append(frag)
        params.extend(p)
    other_sql = f" {combine} ".join(other_frags) if other_frags else "1=1"

    null_checks = [f"{get_field(c.field_key).table}.{get_field(c.field_key).column} IS NULL" for c in required_conds]

    where = f"({other_sql}) AND ({' OR '.join(null_checks)})"
    if exclude_mrns:
        where += f" AND p.mrn NOT IN ({','.join('?' for _ in exclude_mrns)})"
        params.extend(exclude_mrns)

    sql = (
        "SELECT DISTINCT p.mrn, p.last_name, p.first_name, p.date_of_birth "
        "FROM patients p JOIN visits v ON v.mrn = p.mrn WHERE " + where +
        " ORDER BY p.last_name, p.first_name"
    )
    return sql, params
