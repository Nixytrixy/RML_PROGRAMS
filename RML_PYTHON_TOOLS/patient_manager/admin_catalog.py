# admin_catalog.py
# Durable, admin-curated configuration that patient_db.py's SQLite index is NOT
# allowed to be the source of truth for: the diagnosis vocabulary (types/subtypes)
# and the list of "required" fields used by the search UI's completeness check.
# patient_db.py explicitly documents its database as a derived, rebuildable cache --
# rebuild_index() wipes and regenerates everything from the real patient files on
# disk, so anything that can't be derived from those files (like admin-curated
# lists) must live here instead, on the same shared root as patient_index.db.

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import patient_store

_DEFAULT: dict = {"diagnosis_catalog": {}, "required_fields": [], "test_dependencies": {}}


def get_catalog_path() -> Path:
    root = patient_store.get_root_dir()
    if root is not None:
        return root / "clinical_catalog.json"
    base = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "RML_PYTHON_TOOLS"
    base.mkdir(parents=True, exist_ok=True)
    return base / "clinical_catalog.json"


def load_catalog() -> dict:
    try:
        data = patient_store._read_json(get_catalog_path())
    except (OSError, ValueError):
        data = {}
    out = dict(_DEFAULT)
    out.update(data)
    return out


def _save(data: dict) -> None:
    patient_store._atomic_write_json(get_catalog_path(), data)


# ---------------------------------------------------------------------------
# Diagnosis catalog
# ---------------------------------------------------------------------------

def get_diagnosis_catalog() -> dict[str, list[str]]:
    return load_catalog()["diagnosis_catalog"]


def add_diagnosis_type(name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    data = load_catalog()
    data["diagnosis_catalog"].setdefault(name, [])
    _save(data)


def remove_diagnosis_type(name: str) -> None:
    data = load_catalog()
    data["diagnosis_catalog"].pop(name, None)
    _save(data)


def add_subtype(diagnosis_type: str, subtype: str) -> None:
    diagnosis_type = (diagnosis_type or "").strip()
    subtype = (subtype or "").strip()
    if not diagnosis_type or not subtype:
        return
    data = load_catalog()
    subtypes = data["diagnosis_catalog"].setdefault(diagnosis_type, [])
    if subtype not in subtypes:
        subtypes.append(subtype)
    _save(data)


def remove_subtype(diagnosis_type: str, subtype: str) -> None:
    data = load_catalog()
    subtypes = data["diagnosis_catalog"].get(diagnosis_type)
    if subtypes and subtype in subtypes:
        subtypes.remove(subtype)
        _save(data)


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

def get_required_fields() -> list[str]:
    return list(load_catalog()["required_fields"])


def set_required_fields(keys: list[str]) -> None:
    data = load_catalog()
    data["required_fields"] = list(dict.fromkeys(keys))  # dedupe, preserve order
    _save(data)


# ---------------------------------------------------------------------------
# Test dependencies -- ONLY the slug-depends-on-slug graph is admin-managed;
# everything else about a test's inputs/outputs lives in its own Python code
# (analysis_registry.py's module contract, "upstream" preflight fields).
# ---------------------------------------------------------------------------

def get_test_dependencies() -> dict[str, list[str]]:
    """{slug: [prereq_slug, ...]} for every test with at least one admin-declared
    prerequisite. A slug absent from this dict has none."""
    return dict(load_catalog()["test_dependencies"])


def get_prerequisites_for(slug: str) -> list[str]:
    return list(load_catalog()["test_dependencies"].get(slug, []))


def set_prerequisites_for(slug: str, prereq_slugs: list[str]) -> None:
    data = load_catalog()
    deps = data.setdefault("test_dependencies", {})
    cleaned = list(dict.fromkeys(s for s in prereq_slugs if s and s != slug))  # dedupe, no self-deps
    if cleaned:
        deps[slug] = cleaned
    else:
        deps.pop(slug, None)
    _save(data)


def find_dependency_cycle(graph: dict[str, list[str]]) -> Optional[list[str]]:
    """DFS cycle detection over {slug: [prereq_slug, ...]}. Returns the cycle as a
    list of slugs (first repeats last), or None if the graph is acyclic."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    path: list[str] = []

    def visit(slug: str) -> Optional[list[str]]:
        color[slug] = GRAY
        path.append(slug)
        for prereq in graph.get(slug, []):
            state = color.get(prereq, WHITE)
            if state == GRAY:
                cycle_start = path.index(prereq)
                return path[cycle_start:] + [prereq]
            if state == WHITE:
                found = visit(prereq)
                if found:
                    return found
        path.pop()
        color[slug] = BLACK
        return None

    for slug in graph:
        if color.get(slug, WHITE) == WHITE:
            found = visit(slug)
            if found:
                return found
    return None
