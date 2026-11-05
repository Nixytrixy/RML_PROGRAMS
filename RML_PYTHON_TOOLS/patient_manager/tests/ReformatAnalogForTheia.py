#!/usr/bin/env python3
#!/usr/bin/env python3
# Reformat analog C3D files into Theia-friendly structure.
# Exports: ReformatAnalogForThea()

from pathlib import Path
import shutil

def name():
    return "Reformat Analog For Theia"

def _ask_dir(title, init=None):
    try:
        import tkinter as tk
        from tkinter import filedialog
        tk.Tk().withdraw()
        d = filedialog.askdirectory(title=title, initialdir=init or "")
        return Path(d) if d else None
    except Exception:
        p = input(f"{title}\nPath: ").strip()
        return Path(p) if p else None

def _default_initial_dir(context=None):
    from analysis_registry import natural_input_dir
    default_initial = r'Q:\Goodsam\CTU RML Data'
    if context is not None:
        suggested = natural_input_dir(context.visit_dir, "reformat_analog_theia")
        default_initial = str(suggested) if suggested else str(context.visit_dir)
    return default_initial


def preflight_fields(context=None):
    """Inputs choosable before processing starts (see analysis_registry.py)."""
    return [
        {"key": "reformat_analog_dir", "label": "Directory of analog c3d files",
         "type": "dir", "default": _default_initial_dir(context)},
        {"key": "reformat_parent_dir", "label": "Parent directory of markerless c3d files",
         "type": "dir", "default": ""},
    ]


def collect_inputs(context=None, parent=None, shared=None):
    """
    Runs after the up-front form: with both directories already known (from
    preflight_fields, via `shared`), scan analog_dir once and resolve every
    distinct filename pattern's subject/action index choice now, so main()
    can process every file without further console prompts. Needs a live
    console (launch via python.exe, not pythonw.exe) since these are plain
    input() calls — same requirement as the original inline prompts.
    """
    shared = shared or {}
    analog_dir = shared.get("reformat_analog_dir")
    parent_dir = shared.get("reformat_parent_dir")
    analog_dir = Path(analog_dir) if analog_dir else _ask_dir('Select directory of analog c3d files',
                                                               _default_initial_dir(context))
    if not analog_dir:
        return None
    parent_dir = Path(parent_dir) if parent_dir else _ask_dir(
        'Select the parent directory of markerless c3d files', str(analog_dir))
    if not parent_dir:
        return None

    all_files = [p for p in analog_dir.rglob('*') if p.is_file()]
    keep_files = []
    skip_files = []
    groups = {}  # underscore-count -> tokens, for prompting once per distinct pattern
    for p in all_files:
        us = [i for i, c in enumerate(p.name) if c == '_']
        if len(us) < 2:
            skip_files.append(p)
            continue
        keep_files.append(p)
        n = len(us)
        if n not in groups:
            name = p.name
            groups[n] = [name[:us[0]]] + [name[us[j - 1] + 1:us[j]] for j in range(1, len(us))]

    if skip_files:
        print("Files without at least two underscores (will be skipped unless cancelled):")
        for p in skip_files:
            print(f"  - {p.name}")
        ans = input("Issue with the files above. [S]kip all or [C]ancel? ").lower()
        if not ans.startswith('s'):
            return None

    group_choices = {}
    for n, parts in sorted(groups.items()):
        print(f"\nFilenames with {n} underscores use tokens:")
        for i, t in enumerate(parts, 1):
            print(f"{i}: {t}")
        subj_idx = int(input("Choose the subject index: ")) - 1
        act_idx = int(input("Choose the action index: ")) - 1
        group_choices[n] = (subj_idx, act_idx)

    return {
        "analog_dir": analog_dir,
        "parent_dir": parent_dir,
        "files": keep_files,
        "group_choices": group_choices,
    }


def main(context=None, inputs=None):
    # NOTE: context is accepted for interface consistency with the other analysis modules
    # (see analysis_registry.py), but mostly unused here — the input() prompts below
    # disambiguate which underscore-separated filename token is the "subject"/"action",
    # which is a filename-naming-convention question, not something a Patient/VisitContext
    # can answer. Needs a live console (launch via python.exe, not pythonw.exe) since these
    # are plain input() calls.
    from analysis_registry import make_run_result

    if inputs is not None:
        analog_dir = inputs["analog_dir"]
        parent_dir = inputs["parent_dir"]
        files = inputs["files"]
        group_choices = inputs["group_choices"]
    else:
        analog_dir = _ask_dir('Select directory of analog c3d files', _default_initial_dir(context))
        if not analog_dir:
            return make_run_result("cancelled") if context is not None else None
        parent_dir = _ask_dir('Select the parent directory of markerless c3d files', str(analog_dir))
        if not parent_dir:
            return make_run_result("cancelled") if context is not None else None
        files = [p for p in analog_dir.rglob('*') if p.is_file()]
        group_choices = None

    dest_root = parent_dir / 'Analog_data'

    prev_len = None
    subj_idx = act_idx = None
    output_files = []

    for p in files:
        name = p.name
        us = [i for i, c in enumerate(name) if c == '_']
        if len(us) < 2:
            if group_choices is not None:
                continue  # already resolved to "skip" up front
            ans = input(f"Issue with {name}. [S]kip or [C]ancel and start over? ").lower()
            if ans.startswith('s'): continue
            break

        # tokens between underscores (up to the last underscore), like MATLAB's 'a'
        parts = [name[:us[0]]] + [name[us[j-1]+1:us[j]] for j in range(1, len(us))]

        if group_choices is not None:
            subj_idx, act_idx = group_choices[len(us)]
        elif prev_len != len(us):
            for i, t in enumerate(parts, 1): print(f"{i}: {t}")
            subj_idx = int(input("Choose the subject index: ")) - 1
            act_idx  = int(input("Choose the action index: ")) - 1
            prev_len = len(us)

        action = parts[act_idx]
        dest = dest_root / action
        dest.mkdir(parents=True, exist_ok=True)

        # copy then rename to tail starting after the second-to-last underscore
        tmp = dest / name
        shutil.copy2(p, tmp)
        new_name = name[us[-2] + 1:]  # matches MATLAB: fname(under_ind(end-1)+1:end)
        final_path = dest / new_name
        tmp.rename(final_path)
        output_files.append(final_path)

    if context is not None:
        return make_run_result("success", output_dir=dest_root, output_files=output_files,
                                summary={"files_processed": len(output_files)})
    return None

if __name__ == "__main__":
    main()
