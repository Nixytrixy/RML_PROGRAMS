# analysis_registry.py
# Central list of analysis tools shared by the old Analysis.py CLI menu and the new
# patient_manager_ui.py shell.
#
# Step 1 — add it to the suite (required): write a module with name() and
# main(context=None, inputs=None), then add one RegisteredMethod line below.
# This alone makes it show up as a checkbox and run like every other test.
#
# Step 2 — add it to the window (optional, do this if your test has anything
# to ask): when several tests are checked at once, patient_manager_ui.py asks
# for every selected test's inputs up front (one combined form) before
# running any of them — see preflight_ui.run_preflight / run_preflight()
# below. No RegisteredMethod field is needed for this; it's detected
# automatically by hasattr(mod, "preflight_fields") / hasattr(mod,
# "collect_inputs"). Pick whichever of the two hooks fits your input:
#   - preflight_fields(context=None) -> list[dict]: for inputs choosable
#     before processing starts (a folder, a file, a yes/no). Return specs
#     like {"key", "label", "type": "dir"|"file"|"bool"|"text", "default",
#     "filetypes" (for "file"), "depends_on" (optional, another key in your
#     own list — that row is disabled until the named bool field is
#     checked)}. The shared up-front form renders these automatically.
#   - A field can instead be {"type": "upstream", "key", "from_slug",
#     "want": "output_dir"|"output_files"|"latest_file", "pattern" (optional,
#     a glob used only by the no-prior-run fallback below)} to mean "this
#     input is another test's output" — it never shows a row in the form;
#     resolve_upstream_inputs() fills it in automatically, right before your
#     main() runs, from that test's recorded output for this visit if it
#     already ran (this batch or a past session), else from its conventional
#     output location (default_output_dir) as a best-effort fallback. That
#     fallback has NO existence guarantee (e.g. the user force-continued past
#     a missing prerequisite) — treat an empty/None value the same way you'd
#     treat any other missing input (make_run_result("error", ...)), same as
#     Cosmed already does for its own missing-glob-files case. Tests that
#     depend on another test should also be declared in the admin "Test
#     Dependencies" tab, so the shell runs the prerequisite first and warns
#     if it's about to be skipped — see plan_execution_order() below.
#   - collect_inputs(context=None, parent=None, shared=None) -> dict|None:
#     for inputs that need to scan a chosen folder's contents or review a
#     live plot — move your existing prompt code into it. It runs once, up
#     front, before any selected test starts processing. `shared` holds
#     every key already answered by another selected test so far (see
#     "don't ask twice" below); return None to mean "user cancelled."
# Either way, make main() use the `inputs` dict it's given instead of
# prompting when `inputs` is not None (a hook returning None means
# cancelled — treat that as make_run_result("cancelled")). This keeps main()
# working unprompted from a batch run and unchanged when called standalone
# (mod.main(), no context, no inputs — e.g. from Analysis.py's CLI menu).
#
# Don't ask what's already been asked: if your field/input represents the
# same thing as an existing test's (e.g. "the folder of video clips for this
# visit"), give it the *same key* that test already uses (check sibling
# modules' preflight_fields/collect_inputs before inventing a new one).
# Matching key names is the entire sharing mechanism — the up-front form
# collapses same-key fields from different selected tests into one row, and
# collect_inputs sees prior answers via its `shared` argument. A new,
# not-yet-used key just stays private to your test.

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))  # .../RML_PYTHON_TOOLS/patient_manager

# Cosmed_Processing_v8 and the pedobarograph tool live in tests/, alongside this
# file's own package; Analysis.py has historically also inserted the repo-root
# "VO2 Cosmed" folder onto sys.path (a duplicate/backup copy lives there from the
# module's own self-archiving step) — keep that for compatibility. The extra ".."
# below accounts for analysis_registry.py living one level deeper (in
# patient_manager/) than it used to.
for _extra in (
    os.path.join(_HERE, "..", "..", "VO2 Cosmed"),
    os.path.join(_HERE, "tests", "pedobarograph"),
):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)


@dataclass(frozen=True)
class RegisteredMethod:
    module_name: str   # importable module name
    slug: str            # stable short key used in filenames / visit.json


REGISTRY: list[RegisteredMethod] = [
    RegisteredMethod("CombineVideos", "combine_videos"),
    RegisteredMethod("ReformatAnalogForTheia", "reformat_analog_theia"),
    RegisteredMethod("Sport_CreateStills", "sport_create_stills"),
    RegisteredMethod("gait_graph_ui", "gait_graph"),
    RegisteredMethod("SLB_COP_ENTROPY", "slb_cop_entropy"),
    RegisteredMethod("Cosmed_Processing_v8", "cosmed"),
    RegisteredMethod("Novel_Processing_23", "pedobarograph"),
]

REGISTRY_SLUGS = {m.slug for m in REGISTRY}


def _slug_registry_index(slug: str) -> int:
    for i, m in enumerate(REGISTRY):
        if m.slug == slug:
            return i
    return len(REGISTRY)


def load_methods():
    """Import every registered module (lazily, in REGISTRY order) and return the list."""
    return [importlib.import_module(m.module_name) for m in REGISTRY]


def slug_for_module(module_name: str) -> str:
    for m in REGISTRY:
        if m.module_name == module_name:
            return m.slug
    return module_name.lower()


def run_preflight(modules, context=None, parent=None):
    """
    Ask every selected module for its up-front inputs before any of them
    runs. Thin wrapper around preflight_ui.run_preflight (kept as a separate
    module so this file, and everything that only needs load_methods()/
    make_run_result()/etc., doesn't have to import tkinter). See the module
    contract comment at the top of this file for how a test opts in.

    Returns {module.__name__: inputs} or None if the user cancelled.
    """
    from preflight_ui import run_preflight as _run_preflight
    return _run_preflight(modules, context=context, parent=parent)


def make_run_result(status: str, output_dir=None, output_files=None,
                     summary: Optional[dict] = None, error: Optional[str] = None) -> dict:
    """
    Shared shape every module returns from main(context) when context is not None.
    status: "success" | "cancelled" | "error"
    """
    return {
        "status": status,
        "output_dir": str(output_dir) if output_dir else None,
        "output_files": [str(p) for p in (output_files or [])],
        "summary": summary or {},
        "error": error,
    }


# Where a module's output naturally belongs within the real Clin/Sport visit skeleton
# (see patient_store.py / Clin_New.bat / Sport_New.bat), relative to visit_dir. Anything
# not listed falls back to the shared top-level "Results" folder every visit has.
_OUTPUT_SUBFOLDER = {
    "gait_graph": ("Mocap", "Results"),
    "combine_videos": ("Video",),
    "cosmed": ("Metabolic", "Results"),
    "pedobarograph": ("Pedobarograph", "Results"),
    "slb_cop_entropy": ("Mocap", "Results"),  # forceplate/COP analysis -- Mocap-collected per Folder Tree.txt
}

# Where a module's raw INPUT data naturally lives within the skeleton, used to pre-seed
# the "select input folder" dialog when launched with a context. Modules not listed keep
# whatever default they already had — their input source isn't implied by the skeleton
# (e.g. SLB/CombineVideos/Sport_CreateStills draw from equipment-specific locations this
# convention doesn't pin down).
_INPUT_SUBFOLDER = {
    "cosmed": ("Metabolic", "Data"),
    "pedobarograph": ("Pedobarograph", "Data"),
    "reformat_analog_theia": ("Mocap", "Data"),
}


def default_output_dir(visit_dir, module_slug: str, visit_type: Optional[str] = None) -> Path:
    """
    Where a module should save results when launched with a context and it has no
    output-location prompt to ask anymore. Every visit folder is created up front by
    patient_store.add_visit() with the full Clin_New.bat/Sport_New.bat skeleton
    (Results, Mocap/Results, Video, ...), so this always resolves to a folder that
    already exists.
    """
    visit_dir = Path(visit_dir)
    if module_slug == "sport_create_stills":
        if visit_type == "Sport":
            candidate = visit_dir / "Report_Photos"
            if candidate.is_dir():
                return candidate
        return visit_dir / "Photos"
    parts = _OUTPUT_SUBFOLDER.get(module_slug)
    if parts:
        return visit_dir.joinpath(*parts)
    return visit_dir / "Results"


def natural_input_dir(visit_dir, module_slug: str) -> Optional[Path]:
    """Best-guess initialdir for a module's raw-data input picker, based on the real
    visit skeleton. Returns None when there's no confident mapping, or the folder
    doesn't exist (e.g. an older visit created before the skeleton included it)."""
    parts = _INPUT_SUBFOLDER.get(module_slug)
    if not parts:
        return None
    candidate = Path(visit_dir).joinpath(*parts)
    return candidate if candidate.is_dir() else None


def _resolve_upstream_value(spec: dict, context, visit):
    """One "upstream" field's resolved value -- see the module contract comment at
    the top of this file for the field shape and the fallback's caveats."""
    from_slug = spec["from_slug"]
    want = spec.get("want", "output_dir")
    pattern = spec.get("pattern")

    # Prefer the prerequisite's own recorded result for THIS visit -- covers both
    # "ran earlier in this same batch" (record_test_result() already ran, synchronously,
    # before this module's turn) and "ran in a past session". Walk backward so a
    # re-run supersedes an older recorded success.
    for entry in reversed(getattr(visit, "tests", None) or []):
        if entry.get("slug") == from_slug and entry.get("status") == "success":
            if want == "output_files":
                return entry.get("output_files") or []
            if want == "latest_file":
                files = entry.get("output_files") or []
                if pattern:
                    import fnmatch
                    files = [f for f in files if fnmatch.fnmatch(os.path.basename(f), pattern)]
                return files[-1] if files else None
            return entry.get("output_dir")

    # No recorded success -- best-effort fallback to the conventional location.
    # No existence guarantee; see the module contract comment.
    fallback_dir = default_output_dir(context.visit_dir, from_slug, visit_type=context.visit_type)
    if want == "output_dir":
        return str(fallback_dir)
    if not fallback_dir.is_dir():
        return [] if want == "output_files" else None
    matches = sorted(fallback_dir.glob(pattern)) if pattern else []
    if want == "output_files":
        return [str(p) for p in matches]
    return str(matches[-1]) if matches else None


def resolve_upstream_inputs(mod, context, visit) -> dict:
    """{key: resolved_value} for every "upstream" field in mod's own
    preflight_fields(context). Call once per module, right before mod.main() --
    see plan_execution_order()'s caller in patient_manager_ui.py."""
    fields_fn = getattr(mod, "preflight_fields", None)
    if fields_fn is None:
        return {}
    try:
        specs = fields_fn(context) or []
    except Exception:
        specs = []
    return {
        spec["key"]: _resolve_upstream_value(spec, context, visit)
        for spec in specs if spec.get("type") == "upstream"
    }


def plan_execution_order(selected, visit, graph: Optional[dict] = None):
    """Reorder `selected` (already-checked modules, REGISTRY order) so a prerequisite
    that's ALSO selected always runs before its dependent -- ties broken by REGISTRY
    order. Never adds a module the user didn't select.

    graph: {slug: [prereq_slug, ...]}, defaults to admin_catalog.get_test_dependencies().

    Returns (ordered_modules, missing), where `missing` is
    [(dependent_slug, prereq_slug), ...] for every declared prerequisite that is
    neither selected for this run nor already a recorded success in visit.tests --
    callers should confirm with the user ("force continue?") before proceeding
    when `missing` is non-empty.
    """
    if graph is None:
        import admin_catalog
        graph = admin_catalog.get_test_dependencies()

    selected_by_slug = {slug_for_module(m.__name__): m for m in selected}
    prior_success = {
        e.get("slug") for e in (getattr(visit, "tests", None) or []) if e.get("status") == "success"
    }

    edges: dict[str, set] = {slug: set() for slug in selected_by_slug}  # slug -> prereq slugs (selected only)
    missing: list[tuple[str, str]] = []
    for slug in selected_by_slug:
        for prereq in graph.get(slug, []):
            if prereq not in REGISTRY_SLUGS:
                continue  # stale/unknown slug (test renamed/removed) -- ignore, don't raise
            if prereq in selected_by_slug:
                edges[slug].add(prereq)
            elif prereq not in prior_success:
                missing.append((slug, prereq))

    # Kahn's algorithm, selected-subset only, REGISTRY order as the tie-break.
    remaining = set(selected_by_slug)
    ordered_slugs: list[str] = []
    while remaining:
        ready = [
            slug for slug in sorted(remaining, key=lambda s: _slug_registry_index(s))
            if edges[slug] <= (set(ordered_slugs))
        ]
        if not ready:
            # Defensive only -- the admin UI rejects cycles at save time. Don't hang:
            # drain whatever's left in REGISTRY order.
            ready = sorted(remaining, key=lambda s: _slug_registry_index(s))
        for slug in ready:
            ordered_slugs.append(slug)
            remaining.discard(slug)

    ordered_modules = [selected_by_slug[slug] for slug in ordered_slugs]
    return ordered_modules, missing
