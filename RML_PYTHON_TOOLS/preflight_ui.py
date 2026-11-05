# preflight_ui.py
# The shared "ask everything up front" window used when several test modules
# are selected at once from patient_manager_ui.py's checklist. See
# analysis_registry.py's module-contract comment for how a test opts into
# this (preflight_fields / collect_inputs) and how answers get shared instead
# of asked twice.

from __future__ import annotations

import inspect
import tkinter as tk
from tkinter import ttk, filedialog


def _make_var(spec):
    if spec.get("type") == "bool":
        return tk.BooleanVar(value=bool(spec.get("default", False)))
    return tk.StringVar(value=str(spec.get("default", "") or ""))


def _short_path(p, maxlen=52):
    p = str(p)
    if len(p) <= maxlen:
        return p
    return "..." + p[-(maxlen - 3):]


def _build_row(section, row_i, label_text, spec, var, dep_var):
    ttk.Label(section, text=label_text, anchor="w", wraplength=360, justify="left").grid(
        row=row_i, column=0, sticky="w", padx=(0, 8), pady=3)

    field_type = spec.get("type", "text")
    widgets = []

    if field_type == "bool":
        cb = ttk.Checkbutton(section, variable=var)
        cb.grid(row=row_i, column=1, sticky="w", pady=3)
        widgets.append(cb)
    elif field_type in ("dir", "file"):
        # One button that opens the OS folder/file picker directly and shows
        # the chosen path as its own label, instead of a text box the user
        # would otherwise have to type a path into.
        placeholder = f"Choose {'folder' if field_type == 'dir' else 'file'}..."
        display_var = tk.StringVar(value=_short_path(var.get()) if var.get() else placeholder)

        def browse(var=var, spec=spec, display_var=display_var):
            if spec.get("type") == "dir":
                chosen = filedialog.askdirectory(title=spec.get("label", ""), initialdir=var.get() or "")
            else:
                chosen = filedialog.askopenfilename(
                    title=spec.get("label", ""),
                    initialdir=var.get() or "",
                    filetypes=spec.get("filetypes") or [("All files", "*.*")],
                )
            if chosen:
                var.set(chosen)
                display_var.set(_short_path(chosen))

        btn = ttk.Button(section, textvariable=display_var, command=browse)
        btn.grid(row=row_i, column=1, columnspan=2, sticky="we", pady=3)
        widgets.append(btn)
    else:
        entry = ttk.Entry(section, textvariable=var, width=42)
        entry.grid(row=row_i, column=1, sticky="we", pady=3)
        widgets.append(entry)

    section.grid_columnconfigure(1, weight=1)

    if dep_var is not None:
        def sync_state(*_a):
            state = "normal" if dep_var.get() else "disabled"
            for w in widgets:
                try:
                    w.configure(state=state)
                except tk.TclError:
                    pass

        dep_var.trace_add("write", sync_state)
        sync_state()


def _show_combined_form(canonical, module_order, module_field_map, parent):
    """
    canonical: widget_key -> {"spec", "modules": [mod, ...], "orig_key"}
    module_order: modules (in encounter order) that declared preflight_fields
    module_field_map: mod.__name__ -> [(orig_key, widget_key), ...]

    Returns {mod.__name__: {orig_key: value, ...}} or None if cancelled.
    """
    dlg = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
    dlg.title("Run Tests: Pre-flight")
    dlg.grab_set()

    outer = ttk.Frame(dlg, padding=10)
    outer.pack(fill="both", expand=True)

    canvas = tk.Canvas(outer, highlightthickness=0, width=520, height=420)
    scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    scroll_frame = ttk.Frame(canvas)
    scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    varmap = {wk: _make_var(entry["spec"]) for wk, entry in canonical.items()}
    owner_of = {wk: entry["modules"][0] for wk, entry in canonical.items()}

    for mod in module_order:
        owned_keys = [wk for wk in canonical if owner_of[wk] is mod]
        if not owned_keys:
            continue

        section = ttk.LabelFrame(scroll_frame, text=mod.name(), padding=8)
        section.pack(fill="x", padx=4, pady=6)

        row_i = 0
        for orig_key, widget_key in module_field_map[mod.__name__]:
            if owner_of.get(widget_key) is not mod:
                continue
            entry = canonical[widget_key]
            spec = entry["spec"]
            var = varmap[widget_key]

            label_text = spec.get("label", orig_key)
            if len(entry["modules"]) > 1:
                names = ", ".join(m.name() for m in entry["modules"])
                label_text += f"\n(used by: {names})"

            dep_var = None
            depends_on = spec.get("depends_on")
            if depends_on:
                for ok, wk in module_field_map[mod.__name__]:
                    if ok == depends_on:
                        dep_var = varmap[wk]
                        break

            _build_row(section, row_i, label_text, spec, var, dep_var)
            row_i += 1

    cancelled = [True]
    btns = ttk.Frame(dlg, padding=(10, 0, 10, 10))
    btns.pack(fill="x")

    def on_continue():
        cancelled[0] = False
        dlg.destroy()

    def on_cancel():
        cancelled[0] = True
        dlg.destroy()

    ttk.Button(btns, text="Continue", command=on_continue).pack(side="right", padx=4)
    ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="right")
    dlg.protocol("WM_DELETE_WINDOW", on_cancel)

    dlg.wait_window()

    if cancelled[0]:
        return None

    inputs_by_module = {}
    for mod in module_order:
        values = {}
        for orig_key, widget_key in module_field_map[mod.__name__]:
            values[orig_key] = varmap[widget_key].get()
        inputs_by_module[mod.__name__] = values
    return inputs_by_module


def run_preflight(modules, context=None, parent=None):
    """
    Ask every selected module (already-checked `modules`, from
    analysis_registry.load_methods()) for its up-front inputs before any of
    them runs:

      1. One combined form for every module that defines
         preflight_fields(context) -> list[dict].
      2. Then, in `modules` order, each module that defines
         collect_inputs(context=None, parent=None, shared=None) -> dict|None.

    Fields (and collect_inputs answers) that share the same key across
    modules are asked once and reused — see analysis_registry.py's module
    contract comment.

    Returns {module.__name__: inputs_dict}, or None if the user cancelled
    the form or any collect_inputs call returned None (cancelled).
    """
    canonical = {}          # widget_key -> {"spec", "modules", "orig_key"}
    module_field_map = {}   # mod.__name__ -> [(orig_key, widget_key), ...]
    module_order = []       # modules that defined preflight_fields, in encounter order

    for mod in modules:
        fields_fn = getattr(mod, "preflight_fields", None)
        if fields_fn is None:
            continue
        try:
            specs = fields_fn(context) or []
        except Exception:
            specs = []
        if not specs:
            continue

        module_order.append(mod)
        field_map = []
        for spec in specs:
            if spec.get("type") == "upstream":
                # Resolved later, automatically, right before this module's own main()
                # runs (analysis_registry.resolve_upstream_inputs) -- never shown here,
                # since the prerequisite producing it may not have run yet.
                continue
            key = spec["key"]
            if key in canonical and canonical[key]["spec"].get("type") == spec.get("type"):
                canonical[key]["modules"].append(mod)
                widget_key = key
            elif key in canonical:
                # Same key, different type: don't merge — keep this module's
                # field private rather than guess which spec should "win".
                widget_key = f"__{mod.__name__}__{key}"
                canonical[widget_key] = {"spec": spec, "modules": [mod], "orig_key": key}
            else:
                canonical[key] = {"spec": spec, "modules": [mod], "orig_key": key}
                widget_key = key
            field_map.append((key, widget_key))
        module_field_map[mod.__name__] = field_map

    inputs_by_module = {}
    if canonical:
        result = _show_combined_form(canonical, module_order, module_field_map, parent)
        if result is None:
            return None
        inputs_by_module = result

    shared = {}
    for values in inputs_by_module.values():
        for k, v in values.items():
            shared.setdefault(k, v)

    for mod in modules:
        collector = getattr(mod, "collect_inputs", None)
        if collector is None:
            continue
        try:
            accepts_shared = "shared" in inspect.signature(collector).parameters
        except (TypeError, ValueError):
            accepts_shared = False
        if accepts_shared:
            result = collector(context=context, parent=parent, shared=shared)
        else:
            result = collector(context=context, parent=parent)
        if result is None:
            return None
        inputs_by_module[mod.__name__] = result
        for k, v in (result.items() if isinstance(result, dict) else ()):
            shared.setdefault(k, v)

    return inputs_by_module
