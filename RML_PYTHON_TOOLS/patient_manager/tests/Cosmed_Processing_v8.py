#!/usr/bin/env python3
"""
Cosmed_Processing_v8.py
Metabolic Processing — Python port of Cosmed_Processing_v8.m

Reads Cosmed Omnia exports (REE resting + CPET 6-minute walk) and computes
dimensionless metabolic metrics, steady-state indices, and publication-quality
plots. Outputs PNG/PDF figures and an Excel results table.

Dependencies: numpy pandas matplotlib scipy openpyxl
  pip install numpy pandas matplotlib scipy openpyxl
"""

import os
import glob
import shutil
import re
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import scipy.stats
import openpyxl
import tkinter as tk
from tkinter import filedialog, messagebox


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _to_seconds(val):
    """Convert an Excel time cell to elapsed seconds.

    Cosmed Omnia exports elapsed time as Excel serial fractions (fraction of a
    day: 0.0–1.0). Pandas may also return datetime.time or timedelta objects.
    """
    if val is None:
        return np.nan
    if isinstance(val, float):
        if np.isnan(val):
            return np.nan
        return val * 86400.0          # Excel fraction-of-day → seconds
    if isinstance(val, int):
        return float(val) * 86400.0
    if hasattr(val, 'total_seconds'):  # timedelta
        return val.total_seconds()
    if hasattr(val, 'hour'):           # datetime.time
        return (val.hour * 3600 + val.minute * 60 +
                val.second + getattr(val, 'microsecond', 0) / 1e6)
    if isinstance(val, str):
        parts = val.strip().split(':')
        try:
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except ValueError:
            pass
    return np.nan


def _safe_float(v):
    try:
        f = float(v)
        return np.nan if np.isnan(f) else f
    except (TypeError, ValueError):
        return np.nan


def find_col(header_row, name):
    """Return 0-based column index where header_row == name."""
    row = list(header_row)
    try:
        return next(i for i, v in enumerate(row) if v == name)
    except StopIteration:
        raise ValueError(f"Column '{name}' not found. Available: {[v for v in row if isinstance(v, str)][:15]}")


def movmean(x, n):
    """Centered moving average with min_periods=1 — matches MATLAB movmean(x,n)."""
    return (pd.Series(np.asarray(x, dtype=float))
            .rolling(n, center=True, min_periods=1)
            .mean()
            .values)


def poly1_fit(x, y):
    """Fit a line to (x, y). Returns (callable, R²)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    xm, ym = x[mask], y[mask]
    if len(xm) < 2:
        return lambda t: np.full_like(np.asarray(t, float), np.nan), np.nan
    coeffs = np.polyfit(xm, ym, 1)
    fn = np.poly1d(coeffs)
    ss_res = np.sum((ym - fn(xm)) ** 2)
    ss_tot = np.sum((ym - ym.mean()) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return fn, r2


def pvalue_from_z(z):
    """Two-tailed p-value from z-score (matches MATLAB pvaluefromz)."""
    return float(2.0 * scipy.stats.norm.sf(abs(z)))


def schwartz_ss(test_time, signal, wind=180):
    """Schwartz 2007 steady-state detection.

    Returns arrays (pvalue, ss) of length len(test_time). ss[j]==1 when the
    rolling window centred at j shows no significant monotonic trend (p>=0.1).
    """
    t = np.asarray(test_time, dtype=float)
    s = np.asarray(signal, dtype=float)
    n_pts = len(t)
    pvalue = np.full(n_pts, np.nan)
    ss = np.zeros(n_pts)

    j_start = int(np.argmin(np.abs(t - wind / 2)))
    j_end   = int(np.argmin(np.abs(t - (t[-1] - wind / 2))))

    for j in range(j_start, j_end + 1):
        a = int(np.argmin(np.abs(t - (t[j] - wind / 2))))
        b = int(np.argmin(np.abs(t - (t[j] + wind / 2))))
        seg = s[a:b + 1]
        N = len(seg)
        if N < 2:
            continue
        Q = sum(int(np.sum(seg[k] < seg[k + 1:])) for k in range(N - 1))
        Q_e     = 0.25 * N * (N - 1)
        denom   = N * (N - 1)
        tau     = 4.0 * Q / denom - 1.0
        tau_e   = 4.0 * Q_e / denom - 1.0   # = 0
        tau_sig = (2.0 * (2.0 * N + 5.0)) / (9.0 * denom)
        z       = (tau - tau_e) / tau_sig    # matches MATLAB exactly
        pvalue[j] = pvalue_from_z(z)
        ss[j] = 1.0 if pvalue[j] >= 0.1 else 0.0

    return pvalue, ss


def shadedplot(ax, x, y1, y2, area_color='#FFFF00', line_color='#AAAAAA'):
    """Shaded band between y1 and y2 (port of MATLAB shadedplot)."""
    ax.fill_between(x, y1, y2, color=area_color, alpha=0.5, linewidth=0)
    ax.plot(x, y1, color=line_color, linewidth=1)
    ax.plot(x, y2, color=line_color, linewidth=1)


def input_dialog(root, title, prompts, defaults):
    """Blocking multi-field tkinter input dialog. Returns list of strings."""
    values = list(str(d) for d in defaults)
    cancelled = [False]

    dlg = tk.Toplevel(root)
    dlg.title(title)
    dlg.grab_set()
    dlg.resizable(False, False)

    entries = []
    for i, (prompt, default) in enumerate(zip(prompts, defaults)):
        tk.Label(dlg, text=prompt, anchor='w', width=28).grid(
            row=i, column=0, padx=10, pady=4, sticky='w')
        var = tk.StringVar(value=str(default))
        e = tk.Entry(dlg, textvariable=var, width=28)
        e.grid(row=i, column=1, padx=10, pady=4)
        entries.append(var)

    def on_ok():
        for i, var in enumerate(entries):
            values[i] = var.get()
        dlg.destroy()

    def on_cancel():
        cancelled[0] = True
        dlg.destroy()

    btn = tk.Frame(dlg)
    btn.grid(row=len(prompts), column=0, columnspan=2, pady=10)
    tk.Button(btn, text='OK',     command=on_ok,     width=10).pack(side='left', padx=5)
    tk.Button(btn, text='Cancel', command=on_cancel, width=10).pack(side='left', padx=5)
    dlg.protocol('WM_DELETE_WINDOW', on_cancel)
    root.wait_window(dlg)
    return None if cancelled[0] else values


def _get_signal(df, header_row, name, start_row, valid_mask):
    """Extract one numeric column from df by header name."""
    col = find_col(header_row, name)
    raw = df.iloc[start_row:, col].values[valid_mask]
    return np.array([_safe_float(v) for v in raw], dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def _default_norm_path():
    """Bundled normative Excel file, if present alongside this module."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    norm_candidates = [
        os.path.join(script_dir, 'Norm_Cosmed', 'Cosmed_Normative_Results_2.xlsx'),
        os.path.join(script_dir, '..', 'Norm_Cosmed', 'Cosmed_Normative_Results_2.xlsx'),
    ]
    return next((c for c in norm_candidates if os.path.exists(c)), None)


def preflight_fields(context=None):
    """Inputs choosable before processing starts (see analysis_registry.py)."""
    from analysis_registry import natural_input_dir

    default_initialdir = r'Q:\Goodsam\CTU RML Data'
    if context is not None:
        suggested = natural_input_dir(context.visit_dir, "cosmed")
        default_initialdir = str(suggested) if suggested else str(context.visit_dir)

    fields = [
        {"key": "cosmed_metabolic_dir", "label": "Metabolic data directory",
         "type": "dir", "default": default_initialdir},
        {"key": "cosmed_use_norms", "label": "Load Normative Data?", "type": "bool", "default": True},
    ]
    if not _default_norm_path():
        fields.append({
            "key": "cosmed_norm_path", "label": "Normative Excel file", "type": "file", "default": "",
            "filetypes": [("Excel files", "*.xlsx"), ("All files", "*.*")],
            "depends_on": "cosmed_use_norms",
        })
    return fields


def main(context=None, inputs=None):
    from analysis_registry import make_run_result, default_output_dir, natural_input_dir

    root = tk.Tk()
    root.withdraw()

    # ── User input: directory ─────────────────────────────────────────────────
    if inputs is not None:
        folderdir = inputs.get("cosmed_metabolic_dir", "")
    else:
        default_initialdir = r'Q:\Goodsam\CTU RML Data'
        if context is not None:
            suggested = natural_input_dir(context.visit_dir, "cosmed")
            default_initialdir = str(suggested) if suggested else str(context.visit_dir)
        folderdir = filedialog.askdirectory(
            title='Select Metabolic data directory',
            initialdir=default_initialdir
        )
    if not folderdir:
        print('No directory selected. Exiting.')
        root.destroy()
        return make_run_result("cancelled") if context is not None else None

    metabdir = os.path.dirname(folderdir)
    if context is not None:
        savedir = str(default_output_dir(context.visit_dir, "cosmed", visit_type=context.visit_type))
    else:
        savedir = os.path.join(metabdir, 'Results')
    codedir = os.path.join(metabdir, 'Code')
    os.makedirs(savedir, exist_ok=True)
    os.makedirs(codedir, exist_ok=True)

    try:
        shutil.copy2(os.path.abspath(__file__), codedir)
    except Exception:
        pass

    # ── Auto-find data files ──────────────────────────────────────────────────
    ree_files  = sorted(glob.glob(os.path.join(folderdir, '*REE*')))
    cpet_files = sorted(glob.glob(os.path.join(folderdir, '*CPET Breath by Breath*')))
    dist_files = sorted(glob.glob(os.path.join(folderdir, '*Distance*')))

    missing = []
    if not ree_files:  missing.append('*REE*')
    if not cpet_files: missing.append('*CPET Breath by Breath*')
    if not dist_files: missing.append('*Distance*')
    if missing:
        messagebox.showerror('File Error', f'Could not find files matching: {", ".join(missing)}')
        root.destroy()
        if context is not None:
            return make_run_result("error", error=f'Could not find files matching: {", ".join(missing)}')
        return None

    print(f'Loading REE:  {os.path.basename(ree_files[0])}')
    print(f'Loading CPET: {os.path.basename(cpet_files[0])}')
    print(f'Loading dist: {os.path.basename(dist_files[0])}')

    ree_data  = pd.read_excel(ree_files[0],  header=None, engine='openpyxl')
    cpet_data = pd.read_excel(cpet_files[0], header=None, engine='openpyxl')

    distance_raw  = np.loadtxt(dist_files[0])
    cpet_distance = float(np.atleast_1d(distance_raw).flat[0]) / 3.2808  # feet → m

    lap_distance_ft = 74  # feet per lap

    # ── Patient info ──────────────────────────────────────────────────────────
    if context is not None:
        subj      = context.file_stub
        mrn       = context.patient.mrn
        leg       = (context.patient.leg_length_left_cm + context.patient.leg_length_right_cm) / 2.0
        studydate = context.visit_date
        title_str = context.file_stub
    else:
        use_manual = messagebox.askyesno(
            'Patient Data',
            'Enter patient data manually?\n\n(Yes = manual form,  No = load Flowsheet)'
        )

        if use_manual:
            info = input_dialog(
                root, 'Enter Subject Info',
                ['Subject Study Code:', 'MRN:', 'Left leg length (cm):',
                 'Right leg length (cm):', 'Study Date:'],
                ['Subj_0001', '123456', '50', '50', '1/1/20']
            )
            if info is None:
                root.destroy()
                return None
            leg       = (float(info[2]) + float(info[3])) / 2.0
            subj      = info[0]
            mrn       = info[1]
            studydate = info[4]
        else:
            flow_file = filedialog.askopenfilename(
                parent=root,
                title='Select Flowsheet file',
                filetypes=[('Excel files', '*.xlsx *.xls'), ('All files', '*.*')]
            )
            if not flow_file:
                root.destroy()
                return None
            flowsheet = pd.read_excel(flow_file, header=None, engine='openpyxl').values.tolist()

            def _find_flowsheet(label, offset=1):
                for r, row in enumerate(flowsheet):
                    for c, cell in enumerate(row):
                        if cell == label:
                            return flowsheet[r][c + offset]
                return None

            leg_l     = _safe_float(_find_flowsheet('Leg Length (cm)', 1) or 50)
            leg_r     = _safe_float(_find_flowsheet('Leg Length (cm)', 2) or 50)
            leg       = (leg_l + leg_r) / 2.0
            subj      = str(_find_flowsheet('Subject Study Code') or 'Unknown')
            mrn       = str(_find_flowsheet('MRN') or '0')
            studydate = str(_find_flowsheet('Study Date') or '')

        title_str = f'{subj}_{mrn}'

    # ── Normative data ────────────────────────────────────────────────────────
    if inputs is not None:
        use_norms = bool(inputs.get("cosmed_use_norms", False))
    else:
        use_norms = messagebox.askyesno('Normative Data', 'Load Normative Data?')
    norm_headers    = []
    norm_data_arr   = np.array([])
    norm_data_max   = np.array([])
    norm_data_min   = np.array([])
    norm_data_means = np.array([])
    norm_data_std   = np.array([])

    if use_norms:
        default_norm = _default_norm_path()
        if default_norm:
            norm_path = default_norm
        elif inputs is not None:
            norm_path = inputs.get("cosmed_norm_path", "")
        else:
            norm_path = filedialog.askopenfilename(
                parent=root,
                title='Select normative Excel file',
                filetypes=[('Excel files', '*.xlsx'), ('All files', '*.*')]
            )
        if norm_path:
            try:
                # Normative subjects with no heart rate collected store 'NAN' text
                # in REE_HR/CPET_HR; na_values coerces that to a real NaN so those
                # two columns' stats skip them while every other column still uses
                # their data (np.nanmax/nanmin/nanmean/nanstd skip NaN per-column).
                norm_df = pd.read_excel(norm_path, header=0, engine='openpyxl',
                                         na_values=['NAN'])
                norm_headers    = [str(h).strip() for h in norm_df.columns]
                norm_data_arr   = norm_df.iloc[:, 2:].to_numpy(dtype=float)  # drop Subject, MRN
                norm_data_max   = np.nanmax(norm_data_arr, axis=0)
                norm_data_min   = np.nanmin(norm_data_arr, axis=0)
                norm_data_means = np.nanmean(norm_data_arr, axis=0)
                norm_data_std   = np.nanstd(norm_data_arr, axis=0, ddof=1)
            except (ValueError, KeyError, OSError) as e:
                print(f'Warning: failed to load normative Excel file ({e}) — disabling norm overlays.')
                use_norms = False
        else:
            use_norms = False

    def norm_col(name):
        """0-based index into norm_data columns. Mirrors MATLAB find()-2."""
        return norm_headers.index(name) - 2

    # ── Parse CPET data ───────────────────────────────────────────────────────
    # Row 0: column headers; rows 1–2: metadata; row 3+: breath-by-breath data
    DATA_START = 3

    cpet_hdr = cpet_data.iloc[0, :]

    # Anthropometrics embedded in the header block
    age    = _safe_float(cpet_data.iloc[4, 1])    # MATLAB row 5,  col 2
    height = _safe_float(cpet_data.iloc[5, 1])    # MATLAB row 6,  col 2 (cm)
    mass   = _safe_float(cpet_data.iloc[6, 1])    # MATLAB row 7,  col 2 (kg)
    bmi    = _safe_float(cpet_data.iloc[10, 7])   # MATLAB row 11, col 8

    # Time column
    time_col  = find_col(cpet_hdr, 't')
    raw_times = cpet_data.iloc[DATA_START:, time_col].values
    test_time = np.array([_to_seconds(v) for v in raw_times], dtype=float)
    valid     = ~np.isnan(test_time)
    test_time = test_time[valid]

    cpet_hdr_vals = cpet_hdr.values

    def _cpet(name):
        return _get_signal(cpet_data, cpet_hdr_vals, name, DATA_START, valid)

    cpet_vo2_kg = _cpet('VO2/Kg')
    cpet_vo2    = _cpet('VO2')
    cpet_o2exp  = _cpet('O2exp')
    cpet_rq     = _cpet('RQ')
    cpet_eem    = _cpet('EEm')
    cpet_hr     = _cpet('HR')
    cpet_ees    = cpet_eem / 60.0   # kcal/min → kcal/s

    cpet_vo2_kg_mm = movmean(cpet_vo2_kg, 10)
    cpet_vo2_mm    = movmean(cpet_vo2,    10)
    cpet_o2exp_mm  = movmean(cpet_o2exp,  10)
    cpet_rq_mm     = movmean(cpet_rq,     10)
    cpet_ees_mm    = movmean(cpet_ees,    10)
    cpet_hr_mm     = movmean(cpet_hr,     10)

    # ── Lap detection (MATLAB column 39 = Python column 38) ───────────────────
    col38 = cpet_data.iloc[:, 38].values if cpet_data.shape[1] > 38 else []
    lap_rows  = [i for i, v in enumerate(col38)
                 if isinstance(v, str) and v.lower().startswith('lap')]
    lap_strs  = [str(col38[i]) for i in lap_rows]
    lap_nums  = [int(re.sub(r'[^0-9]', '', s)) for s in lap_strs if re.sub(r'[^0-9]', '', s)]

    if len(lap_rows) > 1:
        lap_times = []
        for l in range(1, len(lap_rows)):
            ti_curr = lap_rows[l]     - DATA_START
            ti_prev = lap_rows[l - 1] - DATA_START
            if 0 <= ti_curr < len(test_time) and 0 <= ti_prev < len(test_time):
                dt = test_time[ti_curr] - test_time[ti_prev]
                if len(lap_nums) > l and (lap_nums[l] - lap_nums[l - 1]) > 1:
                    dt /= (lap_nums[l] - lap_nums[l - 1])
                lap_times.append(dt)
        lap_time_mean = np.nanmean(lap_times) if lap_times else np.nan
        lap_time_sd   = float(np.nanstd(lap_times, ddof=1)) if len(lap_times) > 1 else np.nan
        lv_m = (lap_distance_ft / 3.2808)
        lap_vel_mean = lv_m / lap_time_mean if lap_time_mean > 0 else np.nan
        lap_vel_max  = lv_m / np.nanmin(lap_times) if lap_times else np.nan
        lap_vel_min  = lv_m / np.nanmax(lap_times) if lap_times else np.nan
    else:
        lap_times = []
        lap_time_mean = lap_time_sd = np.nan
        lap_vel_mean = lap_vel_max = lap_vel_min = np.nan

    # ── Parse REE data ────────────────────────────────────────────────────────
    ree_hdr_vals = ree_data.iloc[0, :].values

    phase_col = find_col(ree_hdr_vals, 'Phase')
    rest_start = next(
        (i for i, v in enumerate(ree_data.iloc[:, phase_col].values) if v == 'REST'),
        DATA_START
    )

    ree_time_col  = find_col(ree_hdr_vals, 't')
    raw_ree_times = ree_data.iloc[rest_start:, ree_time_col].values
    ree_time      = np.array([_to_seconds(v) for v in raw_ree_times], dtype=float)
    ree_valid     = ~np.isnan(ree_time)
    ree_time      = ree_time[ree_valid]

    def _ree(name):
        return _get_signal(ree_data, ree_hdr_vals, name, rest_start, ree_valid)

    ree_vo2_kg = _ree('VO2/Kg')
    ree_vo2    = _ree('VO2')
    ree_o2exp  = _ree('O2exp')
    ree_rq     = _ree('RQ')
    ree_eem    = _ree('EEm')
    ree_hr     = _ree('HR')
    ree_ees    = ree_eem / 60.0

    ree_vo2_kg_mm = movmean(ree_vo2_kg, 10)
    ree_vo2_mm    = movmean(ree_vo2,    10)
    ree_o2exp_mm  = movmean(ree_o2exp,  10)
    ree_rq_mm     = movmean(ree_rq,     10)
    ree_ees_mm    = movmean(ree_ees,    10)
    ree_hr_mm     = movmean(ree_hr,     10)

    # ── Schwartz 2007 steady-state ────────────────────────────────────────────
    wind = 180
    print('Computing Schwartz steady-state (CPET)...')
    cpet_pvalue, cpet_ss = schwartz_ss(test_time, cpet_vo2_kg_mm, wind)
    print('Computing Schwartz steady-state (REE)...')
    ree_pvalue, ree_ss   = schwartz_ss(ree_time,  ree_vo2_kg_mm,  wind)

    # ── Interactive steady-state selection ────────────────────────────────────
    def _select_region(signal, title, ylabel):
        """Live-cursor region selector.

        A dotted gray line follows the mouse. Clicking places a permanent
        colored line (orange = first, blue = second). After both clicks the
        selected band is shaded green and the window closes automatically.
        """
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(signal, color='C0')
        ax.set_xlabel('Index')
        ax.set_ylabel(ylabel)
        ax.set_title(f'{title}\nClick 1 of 2')
        fig.tight_layout()

        clicks = []
        placed_colors = ['#E05C00', '#006FE0']   # orange, blue

        # Dotted cursor line — hidden until mouse enters the axes
        cursor_line = ax.axvline(0, color='gray', linewidth=1,
                                 linestyle=':', alpha=0.7)
        cursor_line.set_visible(False)

        def on_move(event):
            if event.inaxes == ax and event.xdata is not None:
                cursor_line.set_xdata([event.xdata, event.xdata])
                cursor_line.set_visible(True)
                fig.canvas.draw_idle()

        def on_click(event):
            if (event.inaxes != ax or event.xdata is None
                    or event.button != 1 or len(clicks) >= 2):
                return
            x = event.xdata
            clicks.append(x)
            ax.axvline(x, color=placed_colors[len(clicks) - 1],
                       linewidth=1.5, linestyle='--',
                       label=f'Click {len(clicks)}')
            ax.legend(fontsize=9)
            if len(clicks) == 2:
                x1, x2 = sorted(clicks)
                ax.axvspan(x1, x2, alpha=0.15, color='green')
                cursor_line.set_visible(False)
                ax.set_title(f'{title}\nSelected: {int(x1)}–{int(x2)}')
            else:
                ax.set_title(f'{title}\nClick 2 of 2')
            fig.canvas.draw_idle()

        cid_move  = fig.canvas.mpl_connect('motion_notify_event', on_move)
        cid_click = fig.canvas.mpl_connect('button_press_event', on_click)

        plt.show(block=False)
        plt.pause(0.1)

        while len(clicks) < 2:
            if not plt.fignum_exists(fig.number):
                break
            plt.pause(0.05)

        plt.pause(0.8)   # brief pause so user can see the shaded result
        fig.canvas.mpl_disconnect(cid_move)
        fig.canvas.mpl_disconnect(cid_click)
        plt.close(fig)
        return clicks

    print('Select CPET steady-state region...')
    pts_cpet = _select_region(cpet_vo2_kg_mm,
                               'CPET: Select steady-state region',
                               'VO2/kg moving mean (mL/min-kg)')
    cx1 = int(np.floor(min(pts_cpet)))
    cx2 = int(np.floor(max(pts_cpet)))
    cx1 = max(0, cx1)
    cx2 = min(len(test_time) - 1, cx2)

    print('Select REE steady-state region...')
    pts_ree = _select_region(ree_vo2_kg_mm,
                              'REE: Select steady-state region',
                              'VO2/kg moving mean (mL/min-kg)')
    rx1 = int(np.floor(min(pts_ree)))
    rx2 = int(np.floor(max(pts_ree)))
    rx1 = max(0, rx1)
    rx2 = min(len(ree_time) - 1, rx2)

    # ── CPET metrics ──────────────────────────────────────────────────────────
    cpet_time_total   = test_time[-1]
    cpet_velocity     = cpet_distance / (cpet_time_total / 60.0)  # m/min
    cpet_velocity_sec = cpet_distance / cpet_time_total            # m/s

    t_c = test_time[cx1:cx2 + 1]

    cpet_vo2_kg_mean = np.nanmean(cpet_vo2_kg_mm[cx1:cx2 + 1])
    cpet_vo2_mean    = np.nanmean(cpet_vo2_mm[cx1:cx2 + 1])
    cpet_o2exp_mean  = np.nanmean(cpet_o2exp_mm)
    cpet_rq_mean     = np.nanmean(cpet_rq_mm[cx1:cx2 + 1])
    cpet_ees_mean    = np.nanmean(cpet_ees_mm)
    cpet_hr_mean     = np.nanmean(cpet_hr_mm[cx1:cx2 + 1])
    cpet_hr_max      = np.nanmax(cpet_hr_mm[cx1:cx2 + 1])
    cpet_hr_min      = np.nanmin(cpet_hr_mm[cx1:cx2 + 1])
    cpet_vo2_kg_max  = np.nanmax(cpet_vo2_kg_mm)

    cpet_vo2_kg_fn,  _ = poly1_fit(t_c, cpet_vo2_kg_mm[cx1:cx2 + 1])
    cpet_vo2_fn,     _ = poly1_fit(t_c, cpet_vo2_mm[cx1:cx2 + 1])
    cpet_rq_fn,      _ = poly1_fit(t_c, cpet_rq_mm[cx1:cx2 + 1])
    cpet_ees_fn,     _ = poly1_fit(t_c, cpet_ees_mm[cx1:cx2 + 1])
    cpet_hr_fn,      _ = poly1_fit(t_c, cpet_hr_mm[cx1:cx2 + 1])

    # ── REE metrics ───────────────────────────────────────────────────────────
    t_r = ree_time[rx1:rx2 + 1]

    ree_vo2_kg_mean = np.nanmean(ree_vo2_kg_mm[rx1:rx2 + 1])
    ree_vo2_mean    = np.nanmean(ree_vo2_mm[rx1:rx2 + 1])
    ree_o2exp_mean  = np.nanmean(ree_o2exp_mm[rx1:rx2 + 1])
    ree_rq_mean     = np.nanmean(ree_rq_mm[rx1:rx2 + 1])
    ree_ees_mean    = np.nanmean(ree_ees_mm[rx1:rx2 + 1])
    ree_hr_mean     = np.nanmean(ree_hr_mm[rx1:rx2 + 1])
    ree_hr_max      = np.nanmax(ree_hr_mm)
    ree_hr_min      = np.nanmin(ree_hr_mm)

    ree_vo2_kg_fn, _ = poly1_fit(ree_time, ree_vo2_kg_mm)
    ree_vo2_fn,    _ = poly1_fit(ree_time, ree_vo2_mm)
    ree_rq_fn,     _ = poly1_fit(ree_time, ree_rq_mm)
    ree_ees_fn,    _ = poly1_fit(ree_time, ree_ees_mm)
    ree_hr_fn,     _ = poly1_fit(ree_time, ree_hr_mm)

    # ── Subtract REE from CPET ────────────────────────────────────────────────
    cpet_vo2_kg_adj      = cpet_vo2_kg_mm - ree_vo2_kg_mean
    cpet_vo2_kg_adj_mean = np.nanmean(cpet_vo2_kg_adj[cx1:cx2 + 1])
    cpet_vo2_adj         = cpet_vo2_mm    - ree_vo2_mean
    cpet_vo2_adj_mean    = np.nanmean(cpet_vo2_adj[cx1:cx2 + 1])
    cpet_vo2_adj_max     = np.nanmax(cpet_vo2_adj[cx1:cx2 + 1])
    cpet_vo2_adj_min     = np.nanmin(cpet_vo2_adj[cx1:cx2 + 1])
    cpet_o2exp_adj       = (cpet_o2exp_mm - ree_o2exp_mean) / mass
    cpet_o2exp_adj_mean  = np.nanmean(cpet_o2exp_adj[cx1:cx2 + 1])
    cpet_ees_adj         = cpet_ees_mm    - ree_ees_mean
    cpet_ees_adj_mean    = np.nanmean(cpet_ees_adj)
    cpet_vo2_kg_adj_max  = np.nanmax(cpet_vo2_kg_adj)

    cpet_vo2_kg_adj_fn, _ = poly1_fit(t_c, cpet_vo2_kg_adj[cx1:cx2 + 1])
    cpet_vo2_adj_fn,    _ = poly1_fit(t_c, cpet_vo2_adj[cx1:cx2 + 1])
    cpet_ees_adj_fn,    _ = poly1_fit(t_c, cpet_ees_adj[cx1:cx2 + 1])

    # ── Dimensionless metrics (Schwartz 2006 / Gilbertson) ────────────────────
    leg_m = leg / 100.0
    g     = 9.81

    cpet_vo2_joule_sec = cpet_vo2_adj_mean * (20.1 / 60.0)          # J/s
    cpet_speed         = cpet_velocity_sec / np.sqrt(g * leg_m)      # dimensionless
    cpet_consumption   = cpet_vo2_joule_sec / (mass * g * np.sqrt(g * leg_m))
    cpet_cost          = (cpet_vo2_joule_sec / cpet_velocity_sec) / (mass * g)
    cpet_cost_sh       = cpet_vo2_kg_adj_mean / cpet_velocity         # mL/kg-m
    cpet_cost_gil      = cpet_ees_adj_mean * 4184.0 / cpet_velocity_sec / g / mass
    cpet_consumption_gil = cpet_vo2_joule_sec / (mass * g * np.sqrt(g * leg_m))

    cpet_consumption_max = (cpet_vo2_adj_max * (20.1 / 60.0)) / (mass * g * np.sqrt(g * leg_m))
    cpet_consumption_min = (cpet_vo2_adj_min * (20.1 / 60.0)) / (mass * g * np.sqrt(g * leg_m))

    if not np.isnan(lap_vel_mean):
        lap_speed_mean = lap_vel_mean / np.sqrt(g * leg_m)
        lap_speed_max  = lap_vel_max  / np.sqrt(g * leg_m)
        lap_speed_min  = lap_vel_min  / np.sqrt(g * leg_m)
    else:
        lap_speed_mean = lap_speed_max = lap_speed_min = np.nan

    # Koop 1989 predicted value
    koop_pred_consume = (1.766 * cpet_speed**3 - 1.166 * cpet_speed**2
                         + 0.394 * cpet_speed + 0.007)

    # ── Norm column indices ───────────────────────────────────────────────────
    if use_norms and norm_headers:
        try:
            cpetrqidx      = norm_col('CPET_RQ')
            cpetvo2kgidx   = norm_col('CPET_VO2_adj(mL/min-kg)')
            cpethridx      = norm_col('CPET_HR')
            reerqidx       = norm_col('REE_RQ')
            reevo2kgidx    = norm_col('REE_VO2(mL/min-kg)')
            reehridx       = norm_col('REE_HR')
            cpetvelidx     = norm_col('CPET_Velocity(m/min)')
            cpetcostshidx  = norm_col('SH_Cost(mL/kg-m)')
            cpetspdidx     = norm_col('CPET_Speed(norm)')
            cpetconsidx    = norm_col('Gil_Consume(norm)')
            cpetcostidx    = norm_col('Gil_Cost(norm)')
        except (ValueError, IndexError):
            print('Warning: some normative column names not found — disabling norm overlays.')
            use_norms = False

    # ── Figure 1: 6-panel metabolic overview ─────────────────────────────────
    print('Generating Figure 1: 6-panel metabolic overview...')
    t_ss  = test_time[cx1:cx2 + 1]
    t_ss_x = np.linspace(t_ss[0], t_ss[-1], 300)
    t_re  = ree_time
    t_re_x = np.linspace(t_re[0], t_re[-1], 300)

    fig1, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig1.set_facecolor('white')

    # ── Panel (0,0): CPET RQ ──────────────────────────────────────────────────
    ax = axes[0, 0]
    if use_norms:
        shadedplot(ax, t_ss,
                   np.full(len(t_ss), norm_data_max[cpetrqidx]),
                   np.full(len(t_ss), norm_data_min[cpetrqidx]))
        ax.text(t_ss[0] + 5, norm_data_max[cpetrqidx] - 0.01, 'Norm Range', fontsize=8)
    ax.plot(t_ss, cpet_rq_mm[cx1:cx2 + 1])
    ax.axhline(1.0, color='k', linestyle='-',  linewidth=0.8)
    ax.axhline(0.8, color='k', linestyle='--', linewidth=0.8)
    ax.axhline(0.7, color='k', linestyle='-.', linewidth=0.8)
    ax.plot(t_ss_x, cpet_rq_fn(t_ss_x), '--r', linewidth=1)
    ax.text(t_ss[-1] - 20, 0.99, 'Carb',    fontsize=8)
    ax.text(t_ss[-1] - 30, 0.81, 'Protein', fontsize=8)
    ax.text(t_ss[-1] - 20, 0.71, 'Fat',     fontsize=8)
    ax.set_title('CPET RQ vs. Time')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('RQ (VO2/O2)')
    ax.set_xlim([t_ss[0], t_ss[-1]])
    rq_slice = cpet_rq_mm[cx1:cx2 + 1]
    ax.set_ylim([min(np.nanmin(rq_slice), 0.7), max(np.nanmax(rq_slice), 1.0)])

    # ── Panel (0,1): CPET VO2/kg (REE-adjusted) ──────────────────────────────
    ax = axes[0, 1]
    if use_norms:
        shadedplot(ax, t_ss,
                   np.full(len(t_ss), norm_data_max[cpetvo2kgidx]),
                   np.full(len(t_ss), norm_data_min[cpetvo2kgidx]))
        ax.text(t_ss[0] + 5, norm_data_max[cpetvo2kgidx] - 0.5, 'Norm Range', fontsize=8)
    ax.plot(t_ss, cpet_vo2_kg_adj[cx1:cx2 + 1])
    ax.plot(t_ss_x, cpet_vo2_kg_adj_fn(t_ss_x), '--r', linewidth=1)
    ax.set_title('CPET VO2 (CPET − REE) vs. Time')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('VO2 (mL/min-kg)')
    ax.set_xlim([t_ss[0], t_ss[-1]])
    if use_norms:
        v2_slice = cpet_vo2_kg_adj[cx1:cx2 + 1]
        ax.set_ylim([min(np.nanmin(v2_slice), norm_data_min[cpetvo2kgidx]),
                     max(np.nanmax(v2_slice), norm_data_max[cpetvo2kgidx])])

    # ── Panel (0,2): CPET HR ─────────────────────────────────────────────────
    ax = axes[0, 2]
    if use_norms:
        pos_hr = norm_data_arr[norm_data_arr[:, cpethridx] > 0, cpethridx]
        hr_norm_min = np.nanmin(pos_hr) if len(pos_hr) > 0 else 0.0
        shadedplot(ax, t_ss,
                   np.full(len(t_ss), norm_data_max[cpethridx]),
                   np.full(len(t_ss), hr_norm_min))
        ax.text(t_ss[0] + 5, norm_data_max[cpethridx] - 3, 'Norm Range', fontsize=8)
    ax.plot(t_ss, cpet_hr_mm[cx1:cx2 + 1])
    ax.plot(t_ss_x, cpet_hr_fn(t_ss_x), '--r', linewidth=1)
    ax.set_title('CPET HR vs. Time')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('HR (bpm)')
    ax.set_xlim([t_ss[0], t_ss[-1]])

    # ── Panel (1,0): REE RQ ──────────────────────────────────────────────────
    ax = axes[1, 0]
    if use_norms:
        shadedplot(ax, t_re,
                   np.full(len(t_re), norm_data_max[reerqidx]),
                   np.full(len(t_re), norm_data_min[reerqidx]))
        ax.text(t_re[0] + 5, 0.99, 'Norm Range', fontsize=8)
    ax.plot(t_re, ree_rq_mm)
    ax.axhline(1.0, color='k', linestyle='-',  linewidth=0.8)
    ax.axhline(0.8, color='k', linestyle='--', linewidth=0.8)
    ax.axhline(0.7, color='k', linestyle='-.', linewidth=0.8)
    ax.plot(t_re_x, ree_rq_fn(t_re_x), '--r', linewidth=1)
    ax.text(t_re[-1] - 70, 0.99, 'Carb',    fontsize=8)
    ax.text(t_re[-1] - 90, 0.81, 'Protein', fontsize=8)
    ax.text(t_re[-1] - 60, 0.72, 'Fat',     fontsize=8)
    ax.set_title('REE RQ vs. Time')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('RQ (VO2/O2)')
    ax.set_xlim([t_re[0], t_re[-1]])
    rr_slice = ree_rq_mm[rx1:rx2 + 1]
    ax.set_ylim([min(np.nanmin(rr_slice), 0.7), max(np.nanmax(rr_slice), 1.0)])

    # ── Panel (1,1): REE VO2/kg ───────────────────────────────────────────────
    ax = axes[1, 1]
    if use_norms:
        shadedplot(ax, t_re,
                   np.full(len(t_re), norm_data_max[reevo2kgidx]),
                   np.full(len(t_re), norm_data_min[reevo2kgidx]))
        ax.text(t_re[0] + 5, norm_data_max[reevo2kgidx] - 1, 'Norm Range', fontsize=8)
    ax.plot(t_re, ree_vo2_kg_mm)
    ax.plot(t_re_x, ree_vo2_kg_fn(t_re_x), '--r', linewidth=1)
    ax.set_title('REE VO2 vs. Time')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('VO2 (mL/min-kg)')
    ax.set_xlim([t_re[0], t_re[-1]])

    # ── Panel (1,2): REE HR ───────────────────────────────────────────────────
    ax = axes[1, 2]
    if use_norms:
        pos_hr_r = norm_data_arr[norm_data_arr[:, reehridx] > 0, reehridx]
        rhr_norm_min = np.nanmin(pos_hr_r) if len(pos_hr_r) > 0 else 0.0
        shadedplot(ax, t_re,
                   np.full(len(t_re), norm_data_max[reehridx]),
                   np.full(len(t_re), rhr_norm_min))
        ax.text(t_re[0] + 5, norm_data_max[reehridx] - 1, 'Norm Range', fontsize=8)
    ax.plot(t_re, ree_hr_mm)
    ax.plot(t_re_x, ree_hr_fn(t_re_x), '--r', linewidth=1)
    ax.set_title('REE HR vs. Time')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('HR (bpm)')

    fig1.suptitle(f'{title_str}\nMetabolic Measurement', fontsize=14, fontweight='bold')
    fig1.text(0.5, 0.01,
              ('CPET = Cardiopulmonary Exercise Testing;  '
               'REE = Resting Energy Expenditure;  RQ = Respiratory Quotient'),
              ha='center', fontsize=9)
    fig1.tight_layout(rect=[0, 0.04, 1, 0.93])
    fig1.savefig(os.path.join(savedir, f'{title_str}_Metab_Figures.png'), dpi=150, bbox_inches='tight')
    fig1.savefig(os.path.join(savedir, f'{title_str}_Metab_Figures.pdf'), bbox_inches='tight')
    plt.close(fig1)

    if not use_norms:
        print('Normative data not loaded — skipping comparison figures.')
    else:
        # ── Figure 2: Net O2 Cost (dimensional) ──────────────────────────────
        print('Generating Figure 2: Net O2 Cost...')
        v_mean = norm_data_means[cpetvelidx]
        c_mean = norm_data_means[cpetcostshidx]
        notex2 = 1.05 if cpet_velocity < v_mean else 0.95
        notey2 = 1.20 if cpet_cost_sh  < c_mean else 0.97

        fig2, ax2 = plt.subplots(figsize=(10, 7))
        fig2.set_facecolor('white')
        ax2.plot(cpet_velocity, cpet_cost_sh, '.r', markersize=20, label=studydate)
        ax2.plot(norm_data_arr[:, cpetvelidx], norm_data_arr[:, cpetcostshidx],
                 '.b', markersize=5, label='Norms')
        ax2.errorbar(norm_data_means[cpetvelidx], norm_data_means[cpetcostshidx],
                     yerr=norm_data_std[cpetcostshidx] * 2,
                     xerr=norm_data_std[cpetvelidx] * 2,
                     fmt='o', label='Mean +/- 2 S.D.')
        ax2.set_xlabel('Velocity (m/min)')
        ax2.set_ylabel(r'Net O$_2$ Cost (mL/kg-m)')
        ax2.set_title(f'{title_str}\nMetabolic Cost', fontweight='bold')
        ax2.legend()
        ax2.annotate(
            f'Velocity: {round(cpet_velocity)}\nCost: {round(cpet_cost_sh, 2)}',
            xy=(cpet_velocity, cpet_cost_sh),
            xytext=(cpet_velocity * notex2, cpet_cost_sh * notey2),
            arrowprops=dict(arrowstyle='->', color='black'), fontsize=12
        )
        fig2.savefig(os.path.join(savedir, f'{title_str}_Metab_Net_O2_Cost.png'),
                     dpi=150, bbox_inches='tight')
        fig2.savefig(os.path.join(savedir, f'{title_str}_Metab_Net_O2_Cost.pdf'),
                     bbox_inches='tight')
        plt.close(fig2)

        # ── Figure 3: Dimensionless Consumption + Cost (2-panel) ─────────────
        print('Generating Figure 3: Dimensionless Consumption + Cost...')
        spd_m = norm_data_means[cpetspdidx];  spd_s = norm_data_std[cpetspdidx]
        con_m = norm_data_means[cpetconsidx]; con_s = norm_data_std[cpetconsidx]
        cst_m = norm_data_means[cpetcostidx]; cst_s = norm_data_std[cpetcostidx]

        def _notex(val, mn, sd):
            if val < mn:
                return 1.15 if val < (mn - sd * 2) else 0.83
            return 0.83 if val > (mn + sd * 2) else 1.15

        def _notey(val, mn, sd):
            if val < mn:
                return 1.20 if val < (mn - sd * 2) else 0.83
            return 0.83 if val > (mn + sd * 2) else 1.05

        fig3, (ax3a, ax3b) = plt.subplots(2, 1, figsize=(9, 11))
        fig3.set_facecolor('white')

        for ax_d, y_subj, y_norms, y_mn, y_sd, ylabel, ytitle, nx, ny in [
            (ax3a, cpet_consumption, norm_data_arr[:, cpetconsidx], con_m, con_s,
             'Net Consumption', 'Dimensionless Metabolic Consumption',
             _notex(cpet_speed, spd_m, spd_s), _notey(cpet_consumption, con_m, con_s)),
            (ax3b, cpet_cost, norm_data_arr[:, cpetcostidx], cst_m, cst_s,
             'Net Cost', 'Dimensionless Metabolic Cost',
             _notex(cpet_speed, spd_m, spd_s), _notey(cpet_cost, cst_m, cst_s)),
        ]:
            ax_d.plot(cpet_speed, y_subj, '.r', markersize=20, label=studydate)
            ax_d.plot(norm_data_arr[:, cpetspdidx], y_norms, '.b', markersize=5, label='Norms')
            ax_d.errorbar(spd_m, y_mn, yerr=y_sd * 2, xerr=spd_s * 2,
                          fmt='o', label='Mean +/- 2 S.D.')
            ax_d.set_xlabel('Speed')
            ax_d.set_ylabel(ylabel)
            ax_d.set_title(f'{title_str}\n{ytitle}')
            ax_d.legend(fontsize=9)
            ax_d.annotate(
                f'Speed: {round(cpet_speed, 2)}\n{ylabel.split()[1]}: {round(y_subj, 2)}',
                xy=(cpet_speed, y_subj),
                xytext=(cpet_speed * nx, y_subj * ny),
                arrowprops=dict(arrowstyle='->', color='black'), fontsize=10
            )

        fig3.tight_layout()
        fig3.savefig(os.path.join(savedir, f'{title_str}_Metab_Net_O2_Dimensionless.png'),
                     dpi=150, bbox_inches='tight')
        fig3.savefig(os.path.join(savedir, f'{title_str}_Metab_Net_O2_Dimensionless.pdf'),
                     bbox_inches='tight')
        plt.close(fig3)

        # ── Figure 4: Standalone Koop curve ──────────────────────────────────
        print('Generating Figure 4: Koop curve...')
        fig4, ax4 = plt.subplots(figsize=(10, 7))
        fig4.set_facecolor('white')
        ax4.plot(cpet_speed, cpet_consumption, '.r', markersize=20, label=studydate)
        ax4.plot(norm_data_arr[:, cpetspdidx], norm_data_arr[:, cpetconsidx],
                 '.b', markersize=5, label='Norms')
        ax4.errorbar(spd_m, con_m, yerr=con_s * 2, xerr=spd_s * 2,
                     fmt='o', label='Mean +/- 2 S.D.')
        ax4.set_xlabel('Speed')
        ax4.set_ylabel('Net Consumption')
        ax4.set_title(f'{title_str}\nDimensionless Metabolic Consumption')
        ax4.legend()
        ax4.annotate(
            f'Speed: {round(cpet_speed, 2)}\nConsume: {round(cpet_consumption, 2)}',
            xy=(cpet_speed, cpet_consumption),
            xytext=(cpet_speed * 1.2, cpet_consumption * 1.2),
            arrowprops=dict(arrowstyle='->', color='black'), fontsize=10
        )
        # fig4.savefig(os.path.join(savedir, f'{title_str}_Koop.png'),
        #              dpi=150, bbox_inches='tight')
        # fig4.savefig(os.path.join(savedir, f'{title_str}_Koop.pdf'), bbox_inches='tight')
        plt.close(fig4)

        # ── Figure 5: Combined Koop + Cost (8.5×11) ──────────────────────────
        print('Generating Figure 5: Combined Metab Results (8.5x11)...')
        koop_diff = cpet_consumption - koop_pred_consume
        koop_pct  = (koop_diff / koop_pred_consume) * 100.0

        fig5 = plt.figure(figsize=(8.5, 11))
        fig5.set_facecolor('white')

        # Top: Koop
        ax5a = fig5.add_subplot(2, 1, 1)
        ax5a.scatter([cpet_speed], [cpet_consumption], s=200, color='r', zorder=5, label=studydate)
        ax5a.plot(norm_data_arr[:, cpetspdidx], norm_data_arr[:, cpetconsidx],
                  '.b', markersize=5, label='Norms')
        ax5a.errorbar(spd_m, con_m, yerr=con_s * 2, xerr=spd_s * 2,
                      fmt='o', label='Mean +/- 2 S.D.')
        ax5a.set_xlabel('Speed')
        ax5a.set_ylabel('Net Consumption')
        ax5a.set_title(f'{title_str}\nDimensionless Metabolic Consumption')
        ax5a.legend(fontsize=9)

        # Annotate observed point
        ax5a.annotate(
            f'Speed: {round(cpet_speed, 2)}\nConsume: {round(cpet_consumption, 2)}',
            xy=(cpet_speed, cpet_consumption),
            xytext=(cpet_speed + 0.05, cpet_consumption + 0.01),
            arrowprops=dict(arrowstyle='->', color='black'), fontsize=10
        )

        # Bottom: Cost
        ax5b = fig5.add_subplot(2, 1, 2)
        ax5b.scatter([cpet_speed], [cpet_cost], s=200, color='r', zorder=5, label=studydate)
        ax5b.plot(norm_data_arr[:, cpetspdidx], norm_data_arr[:, cpetcostidx],
                  '.b', markersize=5, label='Norms')
        ax5b.errorbar(spd_m, cst_m, yerr=cst_s * 2, xerr=spd_s * 2,
                      fmt='o', label='Mean +/- 2 S.D.')
        ax5b.set_xlabel('Speed')
        ax5b.set_ylabel('Net Cost')
        ax5b.set_title(f'{title_str}\nDimensionless Metabolic Cost')
        ax5b.legend(fontsize=9)

        # Widen the gap between panels so the Koop text below doesn't
        # collide with the bottom panel's title, then place it in that gap.
        fig5.subplots_adjust(hspace=0.55)
        gap_y = (ax5a.get_position().y0 + ax5b.get_position().y1) / 2
        fig5.text(0.08, gap_y,
                  (f'Observed Net Consumption:     {round(cpet_consumption, 2)} J/kg·m\n'
                   f'Predicted by Koop (1987):        {round(koop_pred_consume, 2)} J/kg·m\n'
                   f'Additional Energy Cost:            {round(koop_diff, 2)} J/kg·m'
                   f'  ({round(koop_pct, 1)}% higher)'),
                  fontsize=10, color='black', va='center', family='monospace')

        # Smart arrow — adapt vertical offset to point position in axes
        ax5b_ylim = ax5b.get_ylim()
        ax5b_xlim = ax5b.get_xlim()
        y_range = ax5b_ylim[1] - ax5b_ylim[0] if ax5b_ylim[1] != ax5b_ylim[0] else 1.0
        x_range = ax5b_xlim[1] - ax5b_xlim[0] if ax5b_xlim[1] != ax5b_xlim[0] else 1.0
        y_rel = (cpet_cost - ax5b_ylim[0]) / y_range
        if y_rel > 0.66:
            dy_frac, dx_frac = -0.12, 0.06
        elif y_rel < 0.33:
            dy_frac, dx_frac =  0.12, 0.06
        else:
            dy_frac, dx_frac =  0.10, 0.10

        ax5b.annotate(
            f'Speed: {round(cpet_speed, 2)}\nCost: {round(cpet_cost, 2)}',
            xy=(cpet_speed, cpet_cost),
            xytext=(cpet_speed + dx_frac * x_range, cpet_cost + dy_frac * y_range),
            arrowprops=dict(arrowstyle='->', color='black'), fontsize=10
        )

        # HR footer annotations
        fig5.text(0.05, 0.03, f'Rest Avg HR: {round(ree_hr_mean)} bpm', fontsize=10)
        fig5.text(0.65, 0.03, f'Walk Avg HR: {round(cpet_hr_mean)} bpm', fontsize=10)

        fig5.set_size_inches(8.5, 11)
        fig5.savefig(os.path.join(savedir, f'{title_str}_Metab_Results.png'),
                     dpi=150, bbox_inches='tight')
        fig5.savefig(os.path.join(savedir, f'{title_str}_Metab_Results.pdf'),
                     format='pdf', bbox_inches='tight')
        plt.close(fig5)

    # ── Excel results table ───────────────────────────────────────────────────
    print('Writing Excel results...')
    headers_out = [
        'Subject', 'MRN', 'Height(m)', 'Weight(kg)', 'Age(y)', 'BMI',
        'Leg_Length(m)', 'CPET_Distance(m)', 'CPET_Velocity(m/min)',
        'CPET_Speed(norm)', 'REE_HR', 'REE_RQ', 'REE_VO2(mL/min-kg)',
        'REE_EEs(kcal/sec)', 'CPET_HR', 'CPET_RQ', 'CPET_VO2_adj(mL/min-kg)',
        'CPET_EEs_adj(kcal/s)', 'CPET_Consume(J/s)', 'SH_Cost(mL/kg-m)',
        'Gil_Cost(norm)', 'Gil_Consume(norm)'
    ]
    subj_data_out = [
        subj, mrn, height / 100.0, mass, age, bmi, leg / 100.0,
        cpet_distance, cpet_velocity, cpet_speed,
        ree_hr_mean, ree_rq_mean, ree_vo2_kg_mean, ree_ees_mean,
        cpet_hr_mean, cpet_rq_mean, cpet_vo2_kg_adj_mean, cpet_ees_adj_mean,
        cpet_vo2_joule_sec, cpet_cost_sh, cpet_cost, cpet_consumption
    ]

    def _clean(v):
        if isinstance(v, float) and np.isnan(v):
            return None
        return v

    xlsx_path = os.path.join(savedir, f'{title_str}_Metab_Table_Results.xlsx')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sheet1'
    for j, h in enumerate(headers_out, 1):
        ws.cell(row=1, column=j, value=h)
    for j, v in enumerate(subj_data_out, 1):
        ws.cell(row=2, column=j, value=_clean(v))
    if use_norms and len(norm_data_means) > 0:
        ws.cell(row=3, column=1, value='Norm_Means')
        for j, v in enumerate(norm_data_means, 3):     # starts at column C
            ws.cell(row=3, column=j, value=float(v))
        ws.cell(row=4, column=1, value='Norm_StDev')
        for j, v in enumerate(norm_data_std, 3):
            ws.cell(row=4, column=j, value=float(v))
    wb.save(xlsx_path)

    # ── Console summary ------------------------------------------------------------------
    root.destroy()
    print(f'\nAll done! Saved to {savedir}')
    if use_norms:
        print(f'Koop predicted consumption:      {koop_pred_consume:.4f}')
    print(f'Calculated consumption:          {cpet_consumption:.4f}')
    print(f'Overall mean velocity (m/s):     {cpet_velocity_sec:.4f}')
    if not np.isnan(lap_vel_max):
        print(f'Lap velocity max/mean/min (m/s): '
              f'{lap_vel_max:.4f} / {lap_vel_mean:.4f} / {lap_vel_min:.4f}')

    if context is not None:
        output_files = [
            os.path.join(savedir, f'{title_str}_Metab_Figures.png'),
            os.path.join(savedir, f'{title_str}_Metab_Figures.pdf'),
            os.path.join(savedir, f'{title_str}_Metab_Net_O2_Cost.png'),
            os.path.join(savedir, f'{title_str}_Metab_Net_O2_Cost.pdf'),
            os.path.join(savedir, f'{title_str}_Metab_Net_O2_Dimensionless.png'),
            os.path.join(savedir, f'{title_str}_Metab_Net_O2_Dimensionless.pdf'),
            os.path.join(savedir, f'{title_str}_Metab_Results.png'),
            os.path.join(savedir, f'{title_str}_Metab_Results.pdf'),
            xlsx_path,
        ]
        output_files = [p for p in output_files if os.path.exists(p)]
        return make_run_result(
            "success", output_dir=savedir, output_files=output_files,
            summary={
                "CPET_HR": _clean(cpet_hr_mean),
                "REE_HR": _clean(ree_hr_mean),
                "CPET_Consume": _clean(cpet_consumption),
                "CPET_Velocity_m_s": _clean(cpet_velocity_sec),
            },
        )
    return None


def name():
    return "Cosmed Metabolic Processing"


if __name__ == '__main__':
    main()