"""
Novel_Processing_23.py
Pedobarograph Post Processing - Python conversion of Novel_Processing_23.m

Added graphs that show a timelapse for the selected foot strikes.
"""

import os
import sys
import shutil
import re
import math
import numpy as np
import scipy.io
import scipy.interpolate
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib import cm
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import warnings
warnings.filterwarnings('ignore')

# Monkey-patch to suppress Python 3.13 / TkAgg TclError on figure close
try:
    import matplotlib.backends._backend_tk as _bktk
    _orig_destroy = _bktk.FigureManagerTk.destroy
    def _safe_destroy(self):
        try:
            _orig_destroy(self)
        except Exception:
            pass
    _bktk.FigureManagerTk.destroy = _safe_destroy
except Exception:
    pass

from sklearn.decomposition import PCA


# ---------------------------------------------------------------------------
# Custom colormap (white for 0-values, then modified jet)
# ---------------------------------------------------------------------------
JET_MOD_CMAP_DATA = [
    [1,1,1],[0.967741935483871,0.967741935483871,1],[0.935483870967742,0.935483870967742,1],
    [0.903225806451613,0.903225806451613,1],[0.870967741935484,0.870967741935484,1],
    [0.838709677419355,0.838709677419355,1],[0.806451612903226,0.806451612903226,1],
    [0.774193548387097,0.774193548387097,1],[0.741935483870968,0.741935483870968,1],
    [0.709677419354839,0.709677419354839,1],[0.67741935483871,0.67741935483871,1],
    [0.645161290322581,0.645161290322581,1],[0.612903225806452,0.612903225806452,1],
    [0.580645161290323,0.580645161290323,1],[0.548387096774194,0.548387096774194,1],
    [0.516129032258065,0.516129032258065,1],[0.483870967741935,0.483870967741935,1],
    [0.451612903225806,0.451612903225806,1],[0.419354838709677,0.419354838709677,1],
    [0.387096774193548,0.387096774193548,1],[0.354838709677419,0.354838709677419,1],
    [0.32258064516129,0.32258064516129,1],[0.290322580645161,0.290322580645161,1],
    [0.258064516129032,0.258064516129032,1],[0.225806451612903,0.225806451612903,1],
    [0.193548387096774,0.193548387096774,1],[0.161290322580645,0.161290322580645,1],
    [0.129032258064516,0.129032258064516,1],[0.0967741935483871,0.0967741935483871,1],
    [0.0645161290322581,0.0645161290322581,1],[0.032258064516129,0.032258064516129,1],
    [0,0,1],[0,0.015625,1],[0,0.03125,1],[0,0.046875,1],[0,0.0625,1],
    [0,0.078125,1],[0,0.09375,1],[0,0.109375,1],[0,0.125,1],[0,0.140625,1],
    [0,0.15625,1],[0,0.171875,1],[0,0.1875,1],[0,0.203125,1],[0,0.21875,1],
    [0,0.234375,1],[0,0.25,1],[0,0.265625,1],[0,0.28125,1],[0,0.296875,1],
    [0,0.3125,1],[0,0.328125,1],[0,0.34375,1],[0,0.359375,1],[0,0.375,1],
    [0,0.390625,1],[0,0.40625,1],[0,0.421875,1],[0,0.4375,1],[0,0.453125,1],
    [0,0.46875,1],[0,0.484375,1],[0,0.5,1],[0,0.515625,1],[0,0.53125,1],
    [0,0.546875,1],[0,0.5625,1],[0,0.578125,1],[0,0.59375,1],[0,0.609375,1],
    [0,0.625,1],[0,0.640625,1],[0,0.65625,1],[0,0.671875,1],[0,0.6875,1],
    [0,0.703125,1],[0,0.71875,1],[0,0.734375,1],[0,0.75,1],[0,0.765625,1],
    [0,0.78125,1],[0,0.796875,1],[0,0.8125,1],[0,0.828125,1],[0,0.84375,1],
    [0,0.859375,1],[0,0.875,1],[0,0.890625,1],[0,0.90625,1],[0,0.921875,1],
    [0,0.9375,1],[0,0.953125,1],[0,0.96875,1],[0,0.984375,1],[0,1,1],
    [0.015625,1,0.984375],[0.03125,1,0.96875],[0.046875,1,0.953125],[0.0625,1,0.9375],
    [0.078125,1,0.921875],[0.09375,1,0.90625],[0.109375,1,0.890625],[0.125,1,0.875],
    [0.140625,1,0.859375],[0.15625,1,0.84375],[0.171875,1,0.828125],[0.1875,1,0.8125],
    [0.203125,1,0.796875],[0.21875,1,0.78125],[0.234375,1,0.765625],[0.25,1,0.75],
    [0.265625,1,0.734375],[0.28125,1,0.71875],[0.296875,1,0.703125],[0.3125,1,0.6875],
    [0.328125,1,0.671875],[0.34375,1,0.65625],[0.359375,1,0.640625],[0.375,1,0.625],
    [0.390625,1,0.609375],[0.40625,1,0.59375],[0.421875,1,0.578125],[0.4375,1,0.5625],
    [0.453125,1,0.546875],[0.46875,1,0.53125],[0.484375,1,0.515625],[0.5,1,0.5],
    [0.515625,1,0.484375],[0.53125,1,0.46875],[0.546875,1,0.453125],[0.5625,1,0.4375],
    [0.578125,1,0.421875],[0.59375,1,0.40625],[0.609375,1,0.390625],[0.625,1,0.375],
    [0.640625,1,0.359375],[0.65625,1,0.34375],[0.671875,1,0.328125],[0.6875,1,0.3125],
    [0.703125,1,0.296875],[0.71875,1,0.28125],[0.734375,1,0.265625],[0.75,1,0.25],
    [0.765625,1,0.234375],[0.78125,1,0.21875],[0.796875,1,0.203125],[0.8125,1,0.1875],
    [0.828125,1,0.171875],[0.84375,1,0.15625],[0.859375,1,0.140625],[0.875,1,0.125],
    [0.890625,1,0.109375],[0.90625,1,0.09375],[0.921875,1,0.078125],[0.9375,1,0.0625],
    [0.953125,1,0.046875],[0.96875,1,0.03125],[0.984375,1,0.015625],[1,1,0],
    [1,0.984375,0],[1,0.96875,0],[1,0.953125,0],[1,0.9375,0],[1,0.921875,0],
    [1,0.90625,0],[1,0.890625,0],[1,0.875,0],[1,0.859375,0],[1,0.84375,0],
    [1,0.828125,0],[1,0.8125,0],[1,0.796875,0],[1,0.78125,0],[1,0.765625,0],
    [1,0.75,0],[1,0.734375,0],[1,0.71875,0],[1,0.703125,0],[1,0.6875,0],
    [1,0.671875,0],[1,0.65625,0],[1,0.640625,0],[1,0.625,0],[1,0.609375,0],
    [1,0.59375,0],[1,0.578125,0],[1,0.5625,0],[1,0.546875,0],[1,0.53125,0],
    [1,0.515625,0],[1,0.5,0],[1,0.484375,0],[1,0.46875,0],[1,0.453125,0],
    [1,0.4375,0],[1,0.421875,0],[1,0.40625,0],[1,0.390625,0],[1,0.375,0],
    [1,0.359375,0],[1,0.34375,0],[1,0.328125,0],[1,0.3125,0],[1,0.296875,0],
    [1,0.28125,0],[1,0.265625,0],[1,0.25,0],[1,0.234375,0],[1,0.21875,0],
    [1,0.203125,0],[1,0.1875,0],[1,0.171875,0],[1,0.15625,0],[1,0.140625,0],
    [1,0.125,0],[1,0.109375,0],[1,0.09375,0],[1,0.078125,0],[1,0.0625,0],
    [1,0.046875,0],[1,0.03125,0],[1,0.015625,0],[1,0,0],[0.984375,0,0],
    [0.96875,0,0],[0.953125,0,0],[0.9375,0,0],[0.921875,0,0],[0.90625,0,0],
    [0.890625,0,0],[0.875,0,0],[0.859375,0,0],[0.84375,0,0],[0.828125,0,0],
    [0.8125,0,0],[0.796875,0,0],[0.78125,0,0],[0.765625,0,0],[0.75,0,0],
    [0.734375,0,0],[0.71875,0,0],[0.703125,0,0],[0.6875,0,0],[0.671875,0,0],
    [0.65625,0,0],[0.640625,0,0],[0.625,0,0],[0.609375,0,0],[0.59375,0,0],
    [0.578125,0,0],[0.5625,0,0],[0.546875,0,0],[0.53125,0,0],[0.515625,0,0],
    [0.5,0,0]
]
JET_MOD_CMAP = ListedColormap(np.array(JET_MOD_CMAP_DATA))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def emptycheck(temp):
    """Return NaN if temp is None or empty array, else return temp."""
    if temp is None:
        return np.nan
    if isinstance(temp, np.ndarray) and temp.size == 0:
        return np.nan
    if isinstance(temp, (list,)) and len(temp) == 0:
        return np.nan
    return temp


def circle_plot(ax, x, y, r, style='-c', label=None):
    """Plot a circle on a 2D axis."""
    th = np.linspace(0, 2 * np.pi, 101)
    xunit = r * np.cos(th) + x
    yunit = r * np.sin(th) + y
    if label:
        ax.plot(xunit, yunit, style, label=label)
    else:
        ax.plot(xunit, yunit, style)


def minboundcircle(x, y):
    """
    Compute the minimum bounding circle of a set of 2D points.
    Returns (center, radius) where center is (cx, cy).
    Uses Welzl's algorithm (iterative approximation via convex hull + simple search).
    """
    pts = np.column_stack([x, y])
    # Use a simple iterative approach: start with centroid, expand
    # This is an approximation using the Ritter algorithm
    cx, cy = np.mean(pts, axis=0)
    r = 0.0
    for _ in range(2):
        for p in pts:
            d = math.hypot(p[0] - cx, p[1] - cy)
            if d > r:
                cx = cx + (p[0] - cx) * (d - r) / (2 * d)
                cy = cy + (p[1] - cy) * (d - r) / (2 * d)
                r = (r + d) / 2
    # Refine: ensure all points are inside
    for p in pts:
        d = math.hypot(p[0] - cx, p[1] - cy)
        if d > r:
            r = d
    return np.array([cx, cy]), r


def emedbarplot(ax, total, hind, mid, fore, title_n, ylabel_n):
    """Bar plot for emed metrics, L and R side by side."""
    data = np.array([
        [round(float(total[0]), 1), round(float(total[1]), 1)],
        [round(float(hind[0]), 1),  round(float(hind[1]), 1)],
        [round(float(mid[0]),  1),  round(float(mid[1]),  1)],
        [round(float(fore[0]), 1),  round(float(fore[1]), 1)],
    ])
    x = np.arange(4)
    width = 0.35
    b1 = ax.bar(x - width/2, data[:, 0], width, label='Left')
    b2 = ax.bar(x + width/2, data[:, 1], width, label='Right')
    ax.set_xticks(x)
    ax.set_xticklabels(['Total', 'L', 'N', 'M'])
    ax.set_title(title_n)
    ax.set_ylabel(ylabel_n)
    total_sum = float(np.nansum(total))
    if total_sum != 0:
        ax.set_ylim([-abs(total_sum) * 0.1, abs(total_sum) * 1.2])
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    # Add value labels
    for bar in b1:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h, f'{h}',
                ha='center', va='top', fontsize=7)
    for bar in b2:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h, f'{h}',
                ha='center', va='top', fontsize=7)
    return b1, b2


def safe_float(s):
    """Convert string to float, return NaN on failure."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return np.nan


# ---------------------------------------------------------------------------
# GUI helper functions (tkinter-based replacements for MATLAB dialogs)
# ---------------------------------------------------------------------------

def questdlg(question, title='Question', options=('Yes', 'No'), default='Yes'):
    """Modal question dialog, returns the selected button string."""
    root = tk.Tk()
    root.withdraw()
    root.lift()
    result = [default]

    dlg = tk.Toplevel(root)
    dlg.title(title)
    dlg.grab_set()
    dlg.resizable(False, False)

    tk.Label(dlg, text=question, padx=20, pady=10).pack()
    btn_frame = tk.Frame(dlg)
    btn_frame.pack(pady=10)

    def make_cmd(opt):
        def cmd():
            result[0] = opt
            dlg.destroy()
        return cmd

    for opt in options:
        tk.Button(btn_frame, text=opt, width=10, command=make_cmd(opt)).pack(side=tk.LEFT, padx=5)

    dlg.protocol('WM_DELETE_WINDOW', lambda: None)
    root.wait_window(dlg)
    root.destroy()
    return result[0]


def inputdlg(prompts, title='Input', defaults=None):
    """Multi-field input dialog. Returns list of strings or None if cancelled."""
    if defaults is None:
        defaults = [''] * len(prompts)
    root = tk.Tk()
    root.withdraw()
    result = [None]

    dlg = tk.Toplevel(root)
    dlg.title(title)
    dlg.grab_set()
    entries = []
    for i, prompt in enumerate(prompts):
        tk.Label(dlg, text=prompt, anchor='w').grid(row=i*2, column=0, sticky='w', padx=10, pady=2)
        e = tk.Entry(dlg, width=40)
        e.insert(0, defaults[i])
        e.grid(row=i*2+1, column=0, padx=10, pady=2)
        entries.append(e)

    def on_ok():
        result[0] = [e.get() for e in entries]
        dlg.destroy()

    def on_cancel():
        dlg.destroy()

    btn_frame = tk.Frame(dlg)
    btn_frame.grid(row=len(prompts)*2, column=0, pady=10)
    tk.Button(btn_frame, text='OK', width=10, command=on_ok).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text='Cancel', width=10, command=on_cancel).pack(side=tk.LEFT, padx=5)
    dlg.protocol('WM_DELETE_WINDOW', on_cancel)
    root.wait_window(dlg)
    root.destroy()
    return result[0]


def listdlg(prompt, options, selection_mode='multiple', title='Select'):
    """
    List selection dialog.
    Returns list of selected 0-based indices (or single index for single mode).
    """
    root = tk.Tk()
    root.withdraw()
    result = [None]

    dlg = tk.Toplevel(root)
    dlg.title(title)
    dlg.grab_set()

    tk.Label(dlg, text=prompt, anchor='w', wraplength=400).pack(padx=10, pady=5)

    frame = tk.Frame(dlg)
    frame.pack(padx=10, pady=5)
    scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL)
    if selection_mode == 'single':
        lb = tk.Listbox(frame, selectmode=tk.SINGLE, yscrollcommand=scrollbar.set,
                        width=50, height=min(20, len(options)+2))
    else:
        lb = tk.Listbox(frame, selectmode=tk.EXTENDED, yscrollcommand=scrollbar.set,
                        width=50, height=min(20, len(options)+2))
    scrollbar.config(command=lb.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    lb.pack(side=tk.LEFT, fill=tk.BOTH)
    for opt in options:
        lb.insert(tk.END, opt)

    def on_ok():
        sel = list(lb.curselection())
        if selection_mode == 'single':
            result[0] = sel[0] if sel else 0
        else:
            result[0] = sel
        dlg.destroy()

    def on_cancel():
        if selection_mode == 'single':
            result[0] = 0
        else:
            result[0] = []
        dlg.destroy()

    btn_frame = tk.Frame(dlg)
    btn_frame.pack(pady=10)
    tk.Button(btn_frame, text='OK', width=10, command=on_ok).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text='Cancel', width=10, command=on_cancel).pack(side=tk.LEFT, padx=5)
    dlg.protocol('WM_DELETE_WINDOW', on_cancel)
    root.wait_window(dlg)
    root.destroy()
    return result[0]


def uigetdir(initial_dir='', title='Select directory'):
    root = tk.Tk()
    root.withdraw()
    d = filedialog.askdirectory(initialdir=initial_dir, title=title)
    root.destroy()
    return d


def uigetfile(initial_dir='', title='Select file', filetypes=None):
    root = tk.Tk()
    root.withdraw()
    if filetypes is None:
        filetypes = [('All files', '*.*')]
    path = filedialog.askopenfilename(initialdir=initial_dir, title=title, filetypes=filetypes)
    root.destroy()
    if path:
        return os.path.basename(path), os.path.dirname(path) + os.sep
    return None, None


# ---------------------------------------------------------------------------
# LST file parsing
# ---------------------------------------------------------------------------

def parse_lst_file(filepath):
    """
    Parse a Novel emed .lst file.
    Returns a list of lists of strings (rows x tokens), similar to MATLAB's
    subj.pedo_data{i} which is a cell array of chars.
    """
    with open(filepath, 'r', errors='replace') as f:
        raw_lines = f.readlines()

    # Skip first line (header), then parse remaining lines as token lists
    pedo_data = []
    for line in raw_lines[1:]:
        # Split by whitespace (tabs, spaces)
        tokens = line.rstrip('\n\r').split()
        pedo_data.append(tokens if tokens else [''])

    return pedo_data


def find_frame_indices(pedo_data):
    """Find row indices of rows containing 'Pict'."""
    frame_rows = []
    for i, row in enumerate(pedo_data):
        for tok in row:
            if 'Pict' in tok:
                frame_rows.append(i)
                break
    return frame_rows


def find_timepic_index(pedo_data):
    """Find row/col index of 'Time/picture' token."""
    for i, row in enumerate(pedo_data):
        for j, tok in enumerate(row):
            if 'Time/picture' in tok:
                return i, j + 1
    return None, None


def extract_matrix_block(pedo_data, row_start, row_end, col_start, col_end):
    """
    Extract a numeric sub-matrix from pedo_data.
    row_end is exclusive; col_end is exclusive (Python-style).
    """
    result = []
    for r in range(row_start, min(row_end, len(pedo_data))):
        row_vals = []
        row = pedo_data[r]
        for c in range(col_start, min(col_end, len(row))):
            row_vals.append(safe_float(row[c]))
        if row_vals:
            result.append(row_vals)
    if not result:
        return np.array([[]])
    # Pad rows to same length
    max_len = max(len(r) for r in result)
    padded = []
    for r in result:
        if len(r) < max_len:
            r = r + [np.nan] * (max_len - len(r))
        padded.append(r)
    return np.array(padded, dtype=float)


def load_file_data(folderdir, fname):
    """
    Load and parse a single .lst file.
    Returns dict with keys: pedo_data, mat_idx, timepic_idx,
    cop_unrot, mpp_unrot, mvp_unrot, ftype (preliminary).
    """
    filepath = os.path.join(folderdir, fname)
    pedo_data = parse_lst_file(filepath)

    # Find frame rows (rows containing 'Pict')
    frame_rows = find_frame_indices(pedo_data)
    frame_rows.sort()

    # mat_idx: [start_row, end_row] for each frame (0-based, exclusive end)
    # MATLAB: mat_idx = [frame_idx(1:end-1,1)+3  frame_idx(2:end,1)-10]
    # In MATLAB 1-based: row+3 means 2 rows later in 0-based = frame_row+3
    # frame_idx(2:end,1)-10 in 1-based = frame_rows[k+1]-10 (1-based) = frame_rows[k+1]-11 (0-based)
    # But since we already converted (skipped header), these are 0-based directly.
    mat_idx = []
    for k in range(len(frame_rows) - 1):
        r_start = frame_rows[k] + 3      # +3 rows from Pict line
        r_end = frame_rows[k + 1] - 10   # 10 rows before next Pict
        mat_idx.append([r_start, r_end])
    # Adjust last entry
    if mat_idx:
        mat_idx[-1][1] = mat_idx[-1][1] + 6

    # Find Time/picture index
    tp_row, tp_col = find_timepic_index(pedo_data)
    timepic_idx = [tp_row, tp_col] if tp_row is not None else [0, 0]

    # COP data: from last frame_rows to len-2, first 6 columns
    if frame_rows:
        cop_start = frame_rows[-1]
        cop_raw = extract_matrix_block(pedo_data, cop_start, len(pedo_data) - 1, 0, 6)
        # Remove rows where col index 1 (force) is NaN
        if cop_raw.ndim == 2 and cop_raw.shape[1] >= 2:
            valid = ~np.isnan(cop_raw[:, 1])
            cop_unrot = cop_raw[valid, :]
        else:
            cop_unrot = cop_raw
    else:
        cop_unrot = np.array([[]])

    # MPP and MVP: second-to-last and last frame blocks
    # MATLAB (1-based): mat_idx{i}(end-1,1):mat_idx{i}(end-1,2)-1, cols 2:end-1
    # Python (0-based): mat_idx[-2][0]:mat_idx[-2][1], cols 1:-1
    if len(mat_idx) >= 2:
        mpp_block = mat_idx[-2]
        mpp_unrot = extract_matrix_block(pedo_data, mpp_block[0], mpp_block[1], 1, 999)
        # Remove last column (the -1 from MATLAB cols 2:end-1)
        if mpp_unrot.ndim == 2 and mpp_unrot.shape[1] > 1:
            mpp_unrot = mpp_unrot[:, :-1]

        mvp_block = mat_idx[-1]
        mvp_unrot = extract_matrix_block(pedo_data, mvp_block[0], mvp_block[1], 1, 999)
        if mvp_unrot.ndim == 2 and mvp_unrot.shape[1] > 1:
            mvp_unrot = mvp_unrot[:, :-1]
    else:
        mpp_unrot = np.array([[]])
        mvp_unrot = np.array([[]])

    # Determine file type from Time/picture value
    ftype = 'unknown'
    if tp_row is not None and tp_col is not None:
        tp_val = safe_float(pedo_data[tp_row][tp_col]) if tp_col < len(pedo_data[tp_row]) else np.nan
        if tp_val == 10:
            if 'step' in fname:
                ftype = 'step'
            else:
                ftype = 'xl'
        elif tp_val == 40:
            ftype = 'static'

    return {
        'pedo_data': pedo_data,
        'mat_idx': mat_idx,
        'timepic_idx': timepic_idx,
        'cop_unrot': cop_unrot,
        'mpp_unrot': mpp_unrot,
        'mvp_unrot': mvp_unrot,
        'ftype': ftype,
    }


# ---------------------------------------------------------------------------
# Plotting utilities
# ---------------------------------------------------------------------------

FOOT_IMAGE_FLIP_Y = True  # Match MATLAB view so row 0 appears at the top.


def apply_foot_image_orientation(ax):
    """Ensure pedobarograph images render with expected vertical orientation."""
    if not FOOT_IMAGE_FLIP_Y:
        return
    y0, y1 = ax.get_ylim()
    if y0 < y1:
        ax.set_ylim(y1, y0)


def plot_mpp_surf_ax(ax, mpp, cop, title_str='', cmap=None, vmin=10, vmax=300):
    """
    Plot MPP as a pcolormesh (top-down view) on the given 2D axis.
    cop: array with columns [frame, force, ?, ?, y_cop, x_cop] (0-indexed)
    """
    if cmap is None:
        cmap = JET_MOD_CMAP
    ax.cla()
    if mpp is not None and mpp.ndim == 2 and mpp.size > 0:
        ax.pcolormesh(mpp, cmap=cmap, vmin=vmin, vmax=vmax, shading='auto')
    if cop is not None and cop.ndim == 2 and cop.shape[0] > 0 and cop.shape[1] >= 6:
        # x_cop = col5, y_cop = col4 (0-indexed)
        xc = cop[:, 5] + 1
        yc = cop[:, 4] + 1
        ax.plot(xc, yc, '-y', linewidth=2)
        ax.plot(xc[0], yc[0], 'og', linewidth=2, markersize=6)
        ax.plot(xc[-1], yc[-1], 'or', linewidth=2, markersize=6)
    apply_foot_image_orientation(ax)
    ax.set_aspect('equal')
    ax.axis('off')
    if title_str:
        ax.set_title(title_str, fontsize=8)


def apply_jet_mod_cmap_to_fig(fig):
    """Apply JET_MOD_CMAP to all axes in a figure (for 3D plots)."""
    for ax in fig.get_axes():
        ax.set_facecolor('white')


# Printable area (inches) that fits within both US Letter and A4 with margins.
PRINT_MAX_PORTRAIT = (7.25, 10.0)
PRINT_MAX_LANDSCAPE = (10.0, 7.25)


def fit_fig_to_page(fig):
    """
    Uniformly scale fig down (never up) so it fits a standard printable page.
    Width and height are scaled by the same factor so plotted data (e.g. equal-aspect
    pressure maps) is never stretched/warped -- only made smaller, with margin left
    on the shorter side if needed.
    """
    w, h = fig.get_size_inches()
    max_w, max_h = PRINT_MAX_LANDSCAPE if w >= h else PRINT_MAX_PORTRAIT
    scale = min(max_w / w, max_h / h, 1.0)
    if scale < 1.0:
        fig.set_size_inches(w * scale, h * scale)
        try:
            fig.tight_layout()
        except Exception:
            pass
    return scale


def save_fig(fig, savepath_base, dpi=150):
    """Save figure as PNG (full size) and PDF (scaled to fit a standard printable page)."""
    fig.savefig(savepath_base + '.png', dpi=dpi, bbox_inches='tight')
    orig_size = fig.get_size_inches().copy()
    fit_fig_to_page(fig)
    fig.savefig(savepath_base + '.pdf', bbox_inches='tight')
    fig.set_size_inches(orig_size)


# ---------------------------------------------------------------------------
# PCA processing
# ---------------------------------------------------------------------------

def apply_pca(mpp_unrot, toewalker=False):
    """
    Apply PCA to nonzero MPP coordinates.
    Returns: pcs (2x2), mu (2,), mpp_unrot_nz, mpp_unrot_coord
    """
    mpp = np.array(mpp_unrot, dtype=float)
    mpp_length, mpp_width = mpp.shape
    # meshgrid: x=cols (width), y=rows (length)
    temp1, temp2 = np.meshgrid(np.arange(1, mpp_width + 1), np.arange(1, mpp_length + 1))
    mpp_unrot_coord = np.column_stack([temp1.ravel(), temp2.ravel(), mpp.ravel()])
    mpp_unrot_nz = mpp_unrot_coord[mpp_unrot_coord[:, 2] > 0, :]

    if toewalker or mpp_unrot_nz.shape[0] < 3:
        pcs = np.eye(2)
        mu = np.array([0.0, 0.0])
    else:
        pca = PCA(n_components=2)
        pca.fit(mpp_unrot_nz[:, :2])
        # MATLAB pca() returns coeff where columns are PCs
        # sklearn returns components_ where rows are PCs
        # So pcs = pca.components_.T  gives the same as MATLAB's coeff
        pcs = pca.components_.T  # (2,2): columns are principal components
        mu = pca.mean_

    return pcs, mu, mpp_unrot_nz, mpp_unrot_coord


def rotate_coords(pcs, mpp_unrot_nz, mpp_unrot_coord):
    """
    Rotate coordinates using PCA matrix.
    MATLAB: coord_nz = (pcs * mpp_unrot_nz[:,[0,1]].T).T
    """
    coord_nz = (pcs @ mpp_unrot_nz[:, :2].T).T
    coord_nz = np.column_stack([coord_nz, mpp_unrot_nz[:, 2]])

    coord_all = (pcs @ mpp_unrot_coord[:, :2].T).T
    coord_all = np.column_stack([coord_all, mpp_unrot_coord[:, 2]])

    return coord_nz, coord_all


def rotate_cop(pcs, cop_unrot):
    """
    Rotate COP data.
    MATLAB: temp = cop_unrot[:,[0,1,4,5]] (1-indexed [1,2,5,6])
            cop_total[:,[2,3]] = (pcs.T @ temp[:,[3,2]].T).T
    Python (0-indexed): cop_unrot[:, [0,1,4,5]]
                        result[:, [2,3]] = (pcs.T @ temp[:,[3,2]].T).T
    """
    temp = cop_unrot[:, [0, 1, 4, 5]].copy()  # frame, force, y_cop, x_cop
    cop_total = np.full((temp.shape[0], 4), np.nan)
    # MATLAB: temp(:,[4 3]) in 1-based = temp[:,[3,2]] in 0-based = [x_cop, y_cop]
    rotated = (pcs.T @ temp[:, [3, 2]].T).T
    cop_total[:, [2, 3]] = rotated
    cop_total[:, :2] = temp[:, :2]
    return cop_total


# ---------------------------------------------------------------------------
# Remeshing
# ---------------------------------------------------------------------------

def remesh_rotated(coord_nz, n_x=100):
    """
    Remesh rotated point cloud to regular grid using griddata.
    Returns mesh_x, mesh_y, mesh_z.
    """
    x = coord_nz[:, 0]
    y = coord_nz[:, 1]
    z = coord_nz[:, 2]

    x_range = np.ptp(x)
    y_range = np.ptp(y)
    if y_range == 0:
        y_range = 1e-6

    proj_x = np.linspace(np.min(x), np.max(x), n_x)
    n_y = int(round(n_x / (x_range / y_range))) if x_range > 0 else n_x
    n_y = max(n_y, 2)
    proj_y = np.linspace(np.min(y), np.max(y), n_y)
    mesh_x, mesh_y = np.meshgrid(proj_x, proj_y)

    try:
        mesh_z = scipy.interpolate.griddata(
            np.column_stack([x, y]), z, (mesh_x, mesh_y), method='linear'
        )
    except Exception:
        mesh_z = np.zeros_like(mesh_x)

    return mesh_x, mesh_y, mesh_z


# ---------------------------------------------------------------------------
# Normative batch processing
# ---------------------------------------------------------------------------

def compute_novel_norm_stats(norm_dir, save_path):
    """
    Process all *_step_*.lst files in norm_dir through the PCA pipeline,
    compute equal-thirds timing/force/area/pressure statistics, and save
    means and SDs to save_path as a .mat file.
    """
    step_files = sorted([
        f for f in os.listdir(norm_dir)
        if f.endswith('.lst') and '_step_' in f
    ])
    if not step_files:
        print('No step files found in norm_dir.')
        return

    print(f'Computing normative stats from {len(step_files)} step files...')

    keys = ['fore', 'mid', 'hind']
    collect = {k: {'time_p': [], 'time_ms': [], 'force_bw': [], 'area': [], 'kpa': []}
               for k in keys}

    for idx, fname in enumerate(step_files):
        if (idx + 1) % 50 == 0 or idx == 0:
            print(f'  Processing file {idx + 1}/{len(step_files)}: {fname}')
        try:
            data = load_file_data(norm_dir, fname)
            mpp_unrot = data['mpp_unrot']
            cop_unrot = data['cop_unrot']

            if mpp_unrot.size == 0 or cop_unrot.size == 0:
                continue

            # PCA — no interactive dialogs
            pcs, mu, mpp_unrot_nz, mpp_unrot_coord = apply_pca(mpp_unrot, toewalker=False)
            coord_nz, coord_all = rotate_coords(pcs, mpp_unrot_nz, mpp_unrot_coord)
            cop_total = rotate_cop(pcs, cop_unrot)

            # Shift to positive quadrant
            shift = np.min(coord_nz[:, :2], axis=0)
            coord_nz[:, :2] -= shift
            cop_total[:, [2, 3]] -= shift

            if coord_nz.shape[0] < 3:
                continue

            # Equal-thirds boundaries
            x_min = np.min(coord_nz[:, 0])
            x_range = np.ptp(coord_nz[:, 0])
            fore_bound = math.floor(x_min + (1/3) * x_range)
            mid_bound_end = math.floor(x_min + (2/3) * x_range) - 1
            mid_idx = list(range(fore_bound + 1, mid_bound_end + 1))
            mid_min = min(mid_idx) if mid_idx else fore_bound + 1
            mid_max = max(mid_idx) if mid_idx else mid_bound_end

            cop_fore = cop_total[cop_total[:, 2] + 1 <= mid_min, :]
            cop_mid  = cop_total[(cop_total[:, 2] + 1 < mid_max) & (cop_total[:, 2] + 1 > mid_min), :]
            cop_hind = cop_total[cop_total[:, 2] + 1 >= mid_max, :]
            mpp_fore = coord_nz[coord_nz[:, 0] < mid_min, :]
            mpp_mid  = coord_nz[(coord_nz[:, 0] <= mid_max) & (coord_nz[:, 0] >= mid_min), :]
            mpp_hind = coord_nz[coord_nz[:, 0] > mid_max, :]

            # Detect COP direction: for heel-toe gait the COP starts at the heel
            # (hind/large-primary end). If early frames are at small primary the PCA
            # placed heel at the small end → swap fore↔hind labels to correct.
            total_frames = cop_total.shape[0]
            if total_frames > 2:
                _nc = max(1, total_frames // 5)
                _x_early = np.nanmean(cop_total[:_nc, 2])
                _x_late  = np.nanmean(cop_total[-_nc:, 2])
                if _x_early < _x_late:  # COP small→large: heel at small primary
                    cop_fore, cop_hind = cop_hind, cop_fore
                    mpp_fore, mpp_hind = mpp_hind, mpp_fore
            if total_frames == 0:
                continue
            total_ms = total_frames * 10

            wt_dummy = 70.0  # placeholder — force %BW uses actual weight; store raw force instead
            for cop_reg, mpp_reg, key in [(cop_fore, mpp_fore, 'fore'),
                                           (cop_mid,  mpp_mid,  'mid'),
                                           (cop_hind, mpp_hind, 'hind')]:
                n = cop_reg.shape[0] if cop_reg.ndim == 2 else 0
                collect[key]['time_ms'].append(n * 10)
                collect[key]['time_p'].append(n / total_frames * 100 if total_frames > 0 else np.nan)
                if cop_reg.ndim == 2 and cop_reg.shape[0] > 0 and cop_reg.shape[1] > 1:
                    collect[key]['force_bw'].append(float(np.nanmax(cop_reg[:, 1])))
                else:
                    collect[key]['force_bw'].append(np.nan)
                collect[key]['area'].append(len(mpp_reg) * 0.25 if mpp_reg.ndim >= 1 else np.nan)
                if mpp_reg.ndim == 2 and mpp_reg.shape[0] > 0 and mpp_reg.shape[1] >= 3:
                    collect[key]['kpa'].append(float(np.nanmax(mpp_reg[:, 2])))
                else:
                    collect[key]['kpa'].append(np.nan)

        except Exception as e:
            print(f'  Warning: skipped {fname} ({e})')
            continue

    # Build output dict (order: fore=M, mid=N, hind=L)
    save_dict = {}
    for metric in ['time_p', 'time_ms', 'force_bw', 'area', 'kpa']:
        vals = [np.array(collect[k][metric]) for k in keys]
        save_dict[f'norm_{metric}_mean'] = np.array([np.nanmean(v) for v in vals])
        save_dict[f'norm_{metric}_std']  = np.array([np.nanstd(v)  for v in vals])

    scipy.io.savemat(save_path, save_dict)
    print(f'Normative stats saved to {save_path}')


# ---------------------------------------------------------------------------
# PDF combining
# ---------------------------------------------------------------------------

def combine_pdfs(savedir, name, dos):
    """Merge all per-figure PDFs into one combined PDF in the specified order."""
    try:
        from pypdf import PdfWriter, PdfReader
    except ImportError:
        print('pypdf not installed — skipping PDF combine (pip install pypdf).')
        return

    order = [
        f'{name}_{dos}_emed_static_pressure.pdf',
        f'{name}_{dos}_emed_xl_strides.pdf',
        f'{name}_{dos}_right_footstrikes.pdf',
        f'{name}_{dos}_left_footstrikes.pdf',
        f'{name}_{dos}_select.pdf',
        f'{name}_{dos}_R_sequence.pdf',
        f'{name}_{dos}_L_sequence.pdf',
        f'{name}_{dos}_emed_graphs.pdf',
    ]

    writer = PdfWriter()
    added = 0
    for pdf_name in order:
        pdf_path = os.path.join(savedir, pdf_name)
        if os.path.exists(pdf_path):
            try:
                reader = PdfReader(pdf_path)
                for page in reader.pages:
                    writer.add_page(page)
                added += 1
            except Exception as e:
                print(f'  Warning: could not merge {pdf_name}: {e}')

    if added == 0:
        print('No PDFs found to combine.')
        return

    combined_path = os.path.join(savedir, f'{name}_{dos}_combined.pdf')
    with open(combined_path, 'wb') as f:
        writer.write(f)
    print(f'Combined PDF saved: {combined_path}  ({added} files merged)')


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def name():
    return "Pedobarograph Processing"


def _default_norm_mat_path():
    return 'Q:\\Goodsam\\CTU RML Data\\Research\\Norm_Study\\Results\\Emed_Normative_Results_4.mat'


def _novel_norm_mat_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, 'Novel_Norm', 'novel_norm_computed.mat')


def preflight_fields(context=None):
    """Inputs choosable before processing starts (see analysis_registry.py).
    Only the pieces answerable before any data is loaded move here -- the
    data-directory picker and the two yes/no prompts below -- so they're
    asked once, up front, in the shared form instead of mid-run. Everything
    that needs the actual file list or a rendered plot (toe-walker/axis/PCA
    decisions, etc.) still happens in collect_inputs(), per that function's
    own docstring."""
    from analysis_registry import natural_input_dir

    default_initial = 'Q:\\Goodsam\\CTU RML Data\\'
    if context is not None:
        suggested = natural_input_dir(context.visit_dir, "pedobarograph")
        default_initial = str(suggested) if suggested else str(context.visit_dir)

    fields = [
        {"key": "pedobarograph_data_dir", "label": "Pedobarograph data directory",
         "type": "dir", "default": default_initial},
        {"key": "pedobarograph_use_norms", "label": "Load Normative Data?", "type": "bool", "default": True},
    ]
    if not os.path.exists(_default_norm_mat_path()):
        fields.append({
            "key": "pedobarograph_norm_path", "label": "Normative MAT file", "type": "file", "default": "",
            "filetypes": [("MAT files", "*.mat")], "depends_on": "pedobarograph_use_norms",
        })
    if not os.path.exists(_novel_norm_mat_path()):
        fields.append({
            "key": "pedobarograph_compute_novel_norm",
            "label": "Novel_Norm stats not yet computed. Compute now (takes a few minutes)?",
            "type": "bool", "default": True,
        })
    return fields


def collect_inputs(context=None, parent=None, shared=None):
    """
    This test's directory/normative-data prompts are followed almost
    immediately by real computation (PCA, region identification) that later
    interactive decisions (toe-walker?, switch axes?, toes up?) need to see
    plotted before they can be answered — the interactive and computational
    parts are threaded through nearly this whole function, with no clean
    boundary to split "gather input" from "process" the way the simpler
    modules do. So, like gait_graph_ui.py, everything past the frontloaded
    fields above (file discovery, the overview plot, and every decision that
    needs to see real data) happens here, up front during the batch's
    preflight pass (before any other selected test starts), instead of being
    split into declarative fields plus a deferred processing step. Returns
    the same result dict `main()` used to compute inline; `main(context,
    inputs=...)` just hands it back unchanged.
    """
    from analysis_registry import make_run_result, default_output_dir, natural_input_dir

    plt.ion()
    shared = shared or {}

    # ------------------------------------------------------------------
    # Data directory -- frontloaded via preflight_fields when launched with
    # a context; falls back to asking directly when run standalone.
    # ------------------------------------------------------------------
    default_initial = 'Q:\\Goodsam\\CTU RML Data\\'
    if context is not None:
        suggested = natural_input_dir(context.visit_dir, "pedobarograph")
        default_initial = str(suggested) if suggested else str(context.visit_dir)
    folderdir = shared.get("pedobarograph_data_dir") or uigetdir(
        default_initial, 'Select pedobarograph data directory')
    if not folderdir:
        print('No directory selected. Exiting.')
        return make_run_result("cancelled") if context is not None else None

    pedodir = os.path.dirname(folderdir)
    if context is not None:
        savedir = str(default_output_dir(context.visit_dir, "pedobarograph", visit_type=context.visit_type))
    else:
        savedir = os.path.join(pedodir, 'Results')
    codedir = os.path.join(pedodir, 'Code')
    os.makedirs(savedir, exist_ok=True)
    os.makedirs(codedir, exist_ok=True)

    # Copy this script to the code directory
    this_script = os.path.abspath(__file__)
    try:
        shutil.copy(this_script, codedir)
    except Exception:
        pass

    # Find .lst files
    filelist = os.listdir(folderdir)
    fname_list = [f for f in filelist if f.endswith('.lst')]
    fname_list.sort()

    if not fname_list:
        print('No .lst files found in selected directory.')
        return make_run_result("error", error="No .lst files found in selected directory.") if context is not None else None

    # ------------------------------------------------------------------
    # Load normative data (legacy COP norms)
    # ------------------------------------------------------------------
    norm = None
    if "pedobarograph_use_norms" in shared:
        ld_norms = 'Yes' if shared["pedobarograph_use_norms"] else 'No'
    else:
        ld_norms = questdlg('Load Normative Data?', 'Normative Data', ['Yes', 'No'], 'Yes')
    if ld_norms == 'Yes':
        default_norm = _default_norm_mat_path()
        try:
            norm_raw = scipy.io.loadmat(default_norm)
            norm = norm_raw
        except Exception:
            norm_path = shared.get("pedobarograph_norm_path")
            if not norm_path:
                fn, fd = uigetfile(pedodir, 'Where is the normative file?', [('MAT files', '*.mat')])
                norm_path = os.path.join(fd, fn) if fn else None
            if norm_path:
                try:
                    norm_raw = scipy.io.loadmat(norm_path)
                    norm = norm_raw
                except Exception:
                    norm = None

    # ------------------------------------------------------------------
    # Load / compute Novel_Norm regional statistics
    # ------------------------------------------------------------------
    script_dir = os.path.dirname(os.path.abspath(__file__))
    novel_norm_dir = os.path.join(script_dir, 'Novel_Norm')
    novel_norm_mat = os.path.join(novel_norm_dir, 'novel_norm_computed.mat')
    novel_norm = None
    if os.path.isdir(novel_norm_dir):
        if os.path.exists(novel_norm_mat):
            try:
                novel_norm = scipy.io.loadmat(novel_norm_mat)
                print('Novel_Norm stats loaded.')
            except Exception:
                novel_norm = None
        else:
            if "pedobarograph_compute_novel_norm" in shared:
                do_compute = 'Yes' if shared["pedobarograph_compute_novel_norm"] else 'No'
            else:
                do_compute = questdlg(
                    'Novel_Norm stats not yet computed.\nCompute now? (takes a few minutes)',
                    'Novel Norm', ['Yes', 'No'], 'Yes')
            if do_compute == 'Yes':
                compute_novel_norm_stats(novel_norm_dir, novel_norm_mat)
                try:
                    novel_norm = scipy.io.loadmat(novel_norm_mat)
                except Exception:
                    novel_norm = None

    # ------------------------------------------------------------------
    # Load subject info
    # ------------------------------------------------------------------
    subj = {}
    if context is not None:
        subj['name'] = context.file_stub
        subj['dos'] = ''.join(re.findall(r'\d+', context.visit_date))
        subj['wt'] = context.patient.bodyweight_kg
    else:
        fs_info = inputdlg(
            ['Subject Study Code:', 'DOS', 'Mass (kg):'],
            'Enter Subject Info',
            ['Subj_0001', 'MMDDYYY', '100']
        )
        if fs_info is None:
            print('Cancelled. Exiting.')
            return None

        subj['name'] = fs_info[0]
        # Extract digits from DOS
        dos_digits = re.findall(r'\d+', fs_info[1])
        subj['dos'] = ''.join(dos_digits)
        subj['wt'] = safe_float(fs_info[2])
    subj['fname'] = fname_list

    # Save initial data
    try:
        scipy.io.savemat(
            os.path.join(savedir, f"{subj['name']}_{subj['dos']}_pedobaro_data.mat"),
            {'subj_name': subj['name'], 'subj_dos': subj['dos'], 'subj_wt': subj['wt']}
        )
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Load all files
    # ------------------------------------------------------------------
    subj['orig'] = {
        'cop_unrot': [],
        'mpp_unrot': [],
        'mvp_unrot': [],
    }
    subj['pedo_data'] = []
    subj['mat_idx'] = []
    subj['timepic_idx'] = []
    subj['ftype'] = []

    print('Loading files...')
    for i, fname in enumerate(fname_list):
        print(f'  Loading {fname}...')
        data = load_file_data(folderdir, fname)
        subj['pedo_data'].append(data['pedo_data'])
        subj['mat_idx'].append(data['mat_idx'])
        subj['timepic_idx'].append(data['timepic_idx'])
        subj['orig']['cop_unrot'].append(data['cop_unrot'])
        subj['orig']['mpp_unrot'].append(data['mpp_unrot'])
        subj['orig']['mvp_unrot'].append(data['mvp_unrot'])
        subj['ftype'].append(data['ftype'])

    # ------------------------------------------------------------------
    # Plot overview figure (all files)
    # ------------------------------------------------------------------
    v = len(fname_list)
    cols_grid = 4
    rows_grid = math.ceil(v / cols_grid)

    fig_overview, axes_ov = plt.subplots(cols_grid, rows_grid, figsize=(16, 10))
    if not isinstance(axes_ov, np.ndarray):
        axes_ov = np.array([[axes_ov]])
    axes_ov_flat = axes_ov.flatten()
    fig_overview.suptitle(f'Pedobarograph - {subj["name"]}', fontsize=12)

    for ct in range(v):
        ax = axes_ov_flat[ct]
        mpp = subj['orig']['mpp_unrot'][ct]
        cop = subj['orig']['cop_unrot'][ct]
        plot_mpp_surf_ax(ax, mpp, cop, title_str=fname_list[ct])

    # Hide unused subplots
    for ct in range(v, len(axes_ov_flat)):
        axes_ov_flat[ct].axis('off')

    fig_overview.tight_layout()
    plt.pause(0.1)

    # ------------------------------------------------------------------
    # Identify file types (user selection)
    # ------------------------------------------------------------------
    xl_sel = listdlg('Select XL files', fname_list, 'multiple', 'Select XL files')
    if xl_sel is None:
        xl_sel = []
    for p in xl_sel:
        subj['ftype'][p] = 'xl'

    left_sel = listdlg('Select left strike files', fname_list, 'multiple', 'Select left strike files')
    if left_sel is None:
        left_sel = []
    for p in left_sel:
        subj['ftype'][p] = 'step-L'

    right_sel = listdlg('Select right strike files', fname_list, 'multiple', 'Select right strike files')
    if right_sel is None:
        right_sel = []
    for p in right_sel:
        subj['ftype'][p] = 'step-R'

    static_sel = listdlg('Select static file', fname_list, 'multiple', 'Select static file')
    if static_sel is None:
        static_sel = []
    for p in static_sel:
        subj['ftype'][p] = 'static'

    plt.close(fig_overview)

    # ------------------------------------------------------------------
    # Step file processing
    # ------------------------------------------------------------------
    has_steps = any('step' in ft for ft in subj['ftype'])

    subj['proc'] = {
        'side': [None, None],
        'fname': [None, None],
        'toewalker': [None, None],
        'R': [None, None],
        'mu': [None, None],
        'fpa': [None, None],
        'mpp': [{}, {}],
        'cop': [{}, {}],
        'force': [{}, {}],
        'force_bw': [{}, {}],
        'area': [{}, {}],
        'kpa': [{}, {}],
        'time': [{}, {}],
        'time_p': [{}, {}],
    }
    subj['orig']['f_indx'] = [None, None]

    if has_steps:
        # ---- Plot left strikes ----
        left_idx = [i for i, ft in enumerate(subj['ftype']) if ft == 'step-L']
        if left_idx:
            v_l = len(left_idx)
            rows_l = math.ceil(v_l / 2)
            cols_l = 2
            fig_l, axes_l = plt.subplots(rows_l, cols_l, figsize=(12, max(4, rows_l * 4)))
            if not isinstance(axes_l, np.ndarray):
                axes_l = np.array([[axes_l]])
            axes_l_flat = axes_l.flatten()
            fig_l.suptitle(f'Pedobarograph - {subj["name"]} Left Strikes', fontsize=12)

            for axnum, ct in enumerate(left_idx):
                ax = axes_l_flat[axnum]
                plot_mpp_surf_ax(ax, subj['orig']['mpp_unrot'][ct],
                                 subj['orig']['cop_unrot'][ct],
                                 title_str=fname_list[ct])
            for axnum in range(len(left_idx), len(axes_l_flat)):
                axes_l_flat[axnum].axis('off')
            fig_l.tight_layout()
            plt.pause(0.1)

            save_fig(fig_l, os.path.join(savedir, f"{subj['name']}_{subj['dos']}_left_footstrikes"))

            # Select representative left
            left_names = [fname_list[i] for i in left_idx]
            sel_l = listdlg('Select representative LEFT', left_names, 'single', 'Select LEFT')
            if sel_l is None:
                sel_l = 0
            subj['orig']['f_indx'][0] = left_idx[sel_l]
            subj['proc']['side'][0] = 'L'
            plt.close(fig_l)

        # ---- Plot right strikes ----
        right_idx = [i for i, ft in enumerate(subj['ftype']) if ft == 'step-R']
        if right_idx:
            v_r = len(right_idx)
            rows_r = math.ceil(v_r / 2)
            cols_r = 2
            fig_r, axes_r = plt.subplots(rows_r, cols_r, figsize=(12, max(4, rows_r * 4)))
            if not isinstance(axes_r, np.ndarray):
                axes_r = np.array([[axes_r]])
            axes_r_flat = axes_r.flatten()
            fig_r.suptitle(f'Pedobarograph - {subj["name"]} Right Strikes', fontsize=12)

            for axnum, ct in enumerate(right_idx):
                ax = axes_r_flat[axnum]
                plot_mpp_surf_ax(ax, subj['orig']['mpp_unrot'][ct],
                                 subj['orig']['cop_unrot'][ct],
                                 title_str=fname_list[ct])
            for axnum in range(len(right_idx), len(axes_r_flat)):
                axes_r_flat[axnum].axis('off')
            fig_r.tight_layout()
            plt.pause(0.1)

            save_fig(fig_r, os.path.join(savedir, f"{subj['name']}_{subj['dos']}_right_footstrikes"))

            right_names = [fname_list[i] for i in right_idx]
            sel_r = listdlg('Select representative RIGHT', right_names, 'single', 'Select RIGHT')
            if sel_r is None:
                sel_r = 0
            subj['orig']['f_indx'][1] = right_idx[sel_r]
            subj['proc']['side'][1] = 'R'
            subj['proc']['fname'] = [
                fname_list[subj['orig']['f_indx'][0]] if subj['orig']['f_indx'][0] is not None else '',
                fname_list[subj['orig']['f_indx'][1]] if subj['orig']['f_indx'][1] is not None else '',
            ]
            plt.close(fig_r)

        # ---- Check toe-walker for each selected file ----
        for i in range(2):
            fidx = subj['orig']['f_indx'][i]
            if fidx is None:
                subj['proc']['toewalker'][i] = 'No'
                continue

            fig_tw, ax_tw = plt.subplots(1, 1, figsize=(6, 8))
            plot_mpp_surf_ax(ax_tw, subj['orig']['mpp_unrot'][fidx],
                             subj['orig']['cop_unrot'][fidx],
                             title_str=fname_list[fidx])
            ax_tw.set_title(fname_list[fidx], fontsize=9)
            fig_tw.tight_layout()
            plt.pause(0.1)

            tw = questdlg('Is this a toe-walker?', 'Toe-Walker?', ['Yes', 'No'], 'No')
            subj['proc']['toewalker'][i] = tw
            plt.close(fig_tw)

        # ---- Apply PCA and process each selected foot ----
        for i in range(2):
            fidx = subj['orig']['f_indx'][i]
            if fidx is None:
                continue

            toewalker = subj['proc']['toewalker'][i] == 'Yes'
            mpp_unrot = subj['orig']['mpp_unrot'][fidx]

            pcs, mu, mpp_unrot_nz, mpp_unrot_coord = apply_pca(mpp_unrot, toewalker)
            subj['proc']['R'][i] = pcs
            subj['proc']['mu'][i] = mu

            coord_nz, coord_all = rotate_coords(pcs, mpp_unrot_nz, mpp_unrot_coord)
            subj['proc']['mpp'][i]['coord_nz'] = coord_nz
            subj['proc']['mpp'][i]['coord'] = coord_all

            cop_total = rotate_cop(pcs, subj['orig']['cop_unrot'][fidx])
            subj['proc']['cop'][i]['total'] = cop_total

            if not toewalker:
                # Show PCA verification plot
                fig_pca, (ax_pca1, ax_pca2) = plt.subplots(1, 2, figsize=(12, 5))
                ax_pca1.scatter(coord_nz[:, 0], coord_nz[:, 1],
                                c=coord_nz[:, 2], cmap=JET_MOD_CMAP, s=5,
                                vmin=10, vmax=300)
                ax_pca1.plot(cop_total[:, 2], cop_total[:, 3], '-k', linewidth=1)
                ax_pca1.set_xlabel('Primary')
                ax_pca1.set_ylabel('Secondary')
                ax_pca1.set_aspect('equal')
                ax_pca1.set_title('Top view')

                ax_pca2.scatter(coord_nz[:, 0], coord_nz[:, 2],
                                c=coord_nz[:, 2], cmap=JET_MOD_CMAP, s=5,
                                vmin=10, vmax=300)
                ax_pca2.set_xlabel('Primary')
                ax_pca2.set_ylabel('Z (kPa)')
                ax_pca2.set_title('Side view')

                fig_pca.suptitle(f'{subj["proc"]["fname"][i]} - PCA Check', fontsize=10)
                fig_pca.tight_layout()
                plt.pause(0.1)

                pcacheck = questdlg('Switch axes?', 'PCA Check', ['Yes', 'No'], 'No')
                plt.close(fig_pca)

                while pcacheck == 'Yes':
                    # Re-run PCA with swapped axes [1, 0]
                    pca = PCA(n_components=2)
                    pca.fit(mpp_unrot_nz[:, [1, 0]])
                    pcs = pca.components_.T
                    mu = pca.mean_
                    subj['proc']['R'][i] = pcs
                    subj['proc']['mu'][i] = mu

                    coord_nz, coord_all = rotate_coords(pcs, mpp_unrot_nz, mpp_unrot_coord)
                    subj['proc']['mpp'][i]['coord_nz'] = coord_nz
                    subj['proc']['mpp'][i]['coord'] = coord_all
                    cop_total = rotate_cop(pcs, subj['orig']['cop_unrot'][fidx])
                    subj['proc']['cop'][i]['total'] = cop_total

                    fig_pca2, (ax_p1, ax_p2) = plt.subplots(1, 2, figsize=(12, 5))
                    ax_p1.scatter(coord_nz[:, 0], coord_nz[:, 1],
                                  c=coord_nz[:, 2], cmap=JET_MOD_CMAP, s=5,
                                  vmin=10, vmax=300)
                    ax_p1.plot(cop_total[:, 2], cop_total[:, 3], '-k', linewidth=1)
                    ax_p1.set_xlabel('Primary')
                    ax_p1.set_ylabel('Secondary')
                    ax_p1.set_aspect('equal')

                    ax_p2.scatter(coord_nz[:, 0], coord_nz[:, 2],
                                  c=coord_nz[:, 2], cmap=JET_MOD_CMAP, s=5,
                                  vmin=10, vmax=300)
                    ax_p2.set_xlabel('Primary')
                    ax_p2.set_ylabel('Z (kPa)')

                    fig_pca2.suptitle(f'{subj["proc"]["fname"][i]} - PCA Check', fontsize=10)
                    fig_pca2.tight_layout()
                    plt.pause(0.1)

                    pcacheck = questdlg('Switch axes?', 'PCA Check', ['Yes', 'No'], 'No')
                    plt.close(fig_pca2)

            # ---- Foot Progression Angle from PCA rotation ----
            # After PCA rotation: small primary coord = forefoot (toes), large = hindfoot (heel).
            # The original image direction that maps to the primary axis [1,0] is pcs[0,:],
            # which therefore points heel-ward.  The toe direction in original image space
            # is therefore -pcs[0,:].
            # FPA = angle of that toe vector from the y-axis (the assumed walking direction).
            # Convention: out-toeing = positive, in-toeing = negative.
            if toewalker:
                subj['proc']['fpa'][i] = np.nan
            else:
                toe_dir = np.array([-pcs[0, 0], -pcs[0, 1]])
                fpa_deg = np.degrees(np.arctan2(toe_dir[0], toe_dir[1]))
                # sklearn PCA direction is arbitrary, so toe_dir can be 180° off.
                # Normalize to ±90° to correct any such flip.
                if fpa_deg > 90:
                    fpa_deg -= 180
                elif fpa_deg < -90:
                    fpa_deg += 180
                # For the left foot the lateral (out-toeing) direction is -x,
                # so negate to keep the convention that positive = out-toeing for both feet.
                if subj['proc']['side'][i] == 'L':
                    fpa_deg = -fpa_deg
                subj['proc']['fpa'][i] = round(fpa_deg, 1)
                fpa_dir = 'Out-toeing' if fpa_deg > 0 else ('In-toeing' if fpa_deg < 0 else 'Neutral')
                print(f"  Foot Progression Angle ({subj['proc']['side'][i]}): "
                      f"{subj['proc']['fpa'][i]:.1f}° ({fpa_dir})")

            # ---- Plot step sequence ----
            framelist = subj['orig']['cop_unrot'][fidx][:, 0].astype(int)
            n_frames = len(framelist)
            step_k = max(1, math.ceil(n_frames / 20))
            b_indices = list(range(0, n_frames, step_k))[:25]  # up to 25 frames

            fig_seq, axes_seq = plt.subplots(5, 5, figsize=(15, 12))
            axes_seq_flat = axes_seq.flatten()

            for framenum, bj in enumerate(b_indices):
                ax_s = axes_seq_flat[framenum]
                frame_num_val = framelist[bj]
                # frame_num_val is 1-based frame index in MATLAB
                frame_0based = int(frame_num_val) - 1  # convert to 0-based
                mat_idx_file = subj['mat_idx'][fidx]
                if 0 <= frame_0based < len(mat_idx_file):
                    r_start = mat_idx_file[frame_0based][0]
                    r_end = mat_idx_file[frame_0based][1]
                    a = extract_matrix_block(subj['pedo_data'][fidx], r_start, r_end, 1, 999)
                    if a.ndim == 2 and a.shape[1] > 2:
                        a_plot = a[:, 1:-1]  # cols 2:end-1 equivalent (1-indexed: cols 2:end)
                    else:
                        a_plot = a
                    if a_plot.size > 0:
                        ax_s.pcolormesh(a_plot, cmap=JET_MOD_CMAP, vmin=10, vmax=300, shading='auto')
                # Plot COP point for this frame
                xc = subj['orig']['cop_unrot'][fidx][bj, 5] + 1
                yc = subj['orig']['cop_unrot'][fidx][bj, 4] + 1
                ax_s.plot(xc, yc, '*k', markersize=5)
                apply_foot_image_orientation(ax_s)
                ax_s.set_aspect('equal')
                ax_s.axis('off')
                ax_s.set_xlabel(str(framenum + 1), fontsize=10)
                for sp in ax_s.spines.values():
                    sp.set_visible(True)
                    sp.set_linewidth(2)

            for axnum in range(len(b_indices), 25):
                axes_seq_flat[axnum].axis('off')

            side_label = subj['proc']['side'][i] if subj['proc']['side'][i] else ''
            seq_title = f'{fname_list[fidx]} - {side_label}'
            fig_seq.suptitle(f'Step Sequence\n{seq_title}', fontsize=12)
            fig_seq.tight_layout()
            plt.pause(0.1)

            save_fig(fig_seq, os.path.join(savedir,
                f"{subj['name']}_{subj['dos']}_{side_label}_sequence"))
            plt.close(fig_seq)

            # ---- Shift data to positive quadrant ----
            shift = np.min(coord_nz[:, :2], axis=0)
            coord_nz[:, :2] -= shift
            cop_total[:, [2, 3]] -= shift
            subj['proc']['mpp'][i]['coord_nz'] = coord_nz
            subj['proc']['mpp'][i]['shift'] = shift
            subj['proc']['cop'][i]['total'] = cop_total

            # ---- Remesh ----
            mesh_x, mesh_y, mesh_z = remesh_rotated(coord_nz, n_x=100)
            subj['proc']['mpp'][i]['mesh'] = {'x': mesh_x, 'y': mesh_y, 'z': mesh_z}

            # ---- Normalize and remesh ----
            max_xy = np.nanmax(coord_nz[:, :2])
            if max_xy == 0:
                max_xy = 1
            norm_coords = coord_nz.copy()
            norm_coords[:, :2] /= max_xy
            subj['proc']['mpp'][i]['norm'] = norm_coords

            mesh_xn, mesh_yn, mesh_zn = remesh_rotated(norm_coords, n_x=100)
            subj['proc']['mpp'][i]['mesh_norm'] = {'x': mesh_xn, 'y': mesh_yn, 'z': mesh_zn}

            # ---- Identify regions ----
            if not toewalker:
                x_min = np.min(coord_nz[:, 0])
                x_range = np.ptp(coord_nz[:, 0])

                # Equal thirds: M (forefoot/metatarsal) | N (midfoot/navicular) | L (hindfoot)
                fore_bound = math.floor(x_min + (1/3) * x_range)   # M/N boundary
                mid_bound_end = math.floor(x_min + (2/3) * x_range) - 1  # N/L boundary

                fore_idx = list(range(math.floor(x_min), fore_bound + 1))
                mid_idx = list(range(fore_bound + 1, mid_bound_end + 1))
                hind_idx = list(range(math.floor(x_min + (2/3) * x_range),
                                       math.ceil(np.max(coord_nz[:, 0])) + 1))

                subj['proc']['cop'][i]['fore_idx'] = fore_idx
                subj['proc']['cop'][i]['mid_idx'] = mid_idx
                subj['proc']['cop'][i]['hind_idx'] = hind_idx

                mid_min = min(mid_idx) if mid_idx else fore_bound + 1
                mid_max = max(mid_idx) if mid_idx else mid_bound_end

                subj['proc']['cop'][i]['fore'] = cop_total[cop_total[:, 2] + 1 <= mid_min, :]
                subj['proc']['cop'][i]['mid'] = cop_total[
                    (cop_total[:, 2] + 1 < mid_max) & (cop_total[:, 2] + 1 > mid_min), :]
                subj['proc']['cop'][i]['hind'] = cop_total[cop_total[:, 2] + 1 >= mid_max, :]

                subj['proc']['mpp'][i]['fore'] = coord_nz[coord_nz[:, 0] < mid_min, :]
                subj['proc']['mpp'][i]['mid'] = coord_nz[
                    (coord_nz[:, 0] <= mid_max) & (coord_nz[:, 0] >= mid_min), :]
                subj['proc']['mpp'][i]['hind'] = coord_nz[coord_nz[:, 0] > mid_max, :]

                max_x = np.nanmax(coord_nz[:, 0])
                max_y = np.nanmax(coord_nz[:, 1])
                subj['proc']['cop'][i]['norm'] = (cop_total + 1) / [1, 1, max_x, max_y]

            else:
                x_min = math.floor(np.min(coord_nz[:, 0]))
                x_max = math.ceil(np.max(coord_nz[:, 0]))
                subj['proc']['cop'][i]['fore_idx'] = list(range(x_min, x_max + 1))
                subj['proc']['cop'][i]['mid_idx'] = []
                subj['proc']['cop'][i]['hind_idx'] = []

                subj['proc']['cop'][i]['fore'] = cop_total.copy()
                subj['proc']['cop'][i]['mid'] = np.array([])
                subj['proc']['cop'][i]['hind'] = np.array([])

                subj['proc']['mpp'][i]['fore'] = coord_nz.copy()
                subj['proc']['mpp'][i]['mid'] = np.array([])
                subj['proc']['mpp'][i]['hind'] = np.array([])

                max_x = np.nanmax(coord_nz[:, 0])
                max_y = np.nanmax(coord_nz[:, 1])
                subj['proc']['cop'][i]['norm'] = (cop_total + 1) / [1, 1, max_x, max_y]

            # ---- Calculate Metrics ----
            # Total
            subj['proc']['force'][i]['total'] = np.nanmax(cop_total[:, 1])
            subj['proc']['force_bw'][i]['total'] = (
                subj['proc']['force'][i]['total'] / (subj['wt'] * 9.81) * 100)
            subj['proc']['area'][i]['total'] = len(coord_nz) * 0.25
            # max kPa from coord[:,1:3] (y and z of rotated coord)
            subj['proc']['kpa'][i]['total'] = np.nanmax(coord_all[:, 1:3]) if coord_all.shape[1] >= 3 else np.nan
            subj['proc']['time'][i]['total'] = cop_total.shape[0] * 10  # ms
            subj['proc']['time_p'][i]['total'] = 100.0

            # Fore
            fore_data = subj['proc']['cop'][i].get('fore', np.array([]))
            mpp_fore = subj['proc']['mpp'][i].get('fore', np.array([]))
            if fore_data.ndim == 2 and fore_data.shape[0] > 0 and fore_data.shape[1] > 1:
                subj['proc']['force'][i]['fore'] = np.nanmax(fore_data[:, 1])
            else:
                subj['proc']['force'][i]['fore'] = np.nan
            subj['proc']['force_bw'][i]['fore'] = (
                subj['proc']['force'][i]['fore'] / (subj['wt'] * 9.81) * 100)
            subj['proc']['area'][i]['fore'] = len(mpp_fore) * 0.25 if mpp_fore.ndim >= 1 else np.nan
            if mpp_fore.ndim == 2 and mpp_fore.shape[0] > 0 and mpp_fore.shape[1] >= 3:
                subj['proc']['kpa'][i]['fore'] = np.nanmax(mpp_fore[:, 1:3])
            else:
                subj['proc']['kpa'][i]['fore'] = np.nan
            subj['proc']['time'][i]['fore'] = (
                fore_data.shape[0] * 10 if fore_data.ndim == 2 else np.nan)
            subj['proc']['time_p'][i]['fore'] = (
                subj['proc']['time'][i]['fore'] / subj['proc']['time'][i]['total'] * 100
                if subj['proc']['time'][i]['total'] > 0 else np.nan)

            if not toewalker:
                mid_data = subj['proc']['cop'][i].get('mid', np.array([]))
                hind_data = subj['proc']['cop'][i].get('hind', np.array([]))
                mpp_mid = subj['proc']['mpp'][i].get('mid', np.array([]))
                mpp_hind = subj['proc']['mpp'][i].get('hind', np.array([]))

                def _max_force(d):
                    return emptycheck(np.nanmax(d[:, 1]) if d.ndim == 2 and d.shape[0] > 0 and d.shape[1] > 1 else None)

                def _max_kpa(d):
                    return emptycheck(np.nanmax(d[:, 1:3]) if d.ndim == 2 and d.shape[0] > 0 and d.shape[1] >= 3 else None)

                subj['proc']['force'][i]['mid'] = emptycheck(_max_force(mid_data))
                subj['proc']['force'][i]['hind'] = emptycheck(_max_force(hind_data))
                subj['proc']['force_bw'][i]['mid'] = emptycheck(
                    subj['proc']['force'][i]['mid'] / (subj['wt'] * 9.81) * 100
                    if not np.isnan(subj['proc']['force'][i]['mid']) else None)
                subj['proc']['force_bw'][i]['hind'] = emptycheck(
                    subj['proc']['force'][i]['hind'] / (subj['wt'] * 9.81) * 100
                    if not np.isnan(subj['proc']['force'][i]['hind']) else None)
                subj['proc']['area'][i]['mid'] = emptycheck(
                    len(mpp_mid) * 0.25 if mpp_mid.ndim >= 1 and mpp_mid.size > 0 else None)
                subj['proc']['area'][i]['hind'] = emptycheck(
                    len(mpp_hind) * 0.25 if mpp_hind.ndim >= 1 and mpp_hind.size > 0 else None)
                subj['proc']['kpa'][i]['mid'] = emptycheck(_max_kpa(mpp_mid))
                subj['proc']['kpa'][i]['hind'] = emptycheck(_max_kpa(mpp_hind))
                subj['proc']['time'][i]['mid'] = emptycheck(
                    mid_data.shape[0] * 10 if mid_data.ndim == 2 else None)
                subj['proc']['time'][i]['hind'] = emptycheck(
                    hind_data.shape[0] * 10 if hind_data.ndim == 2 else None)
                subj['proc']['time_p'][i]['mid'] = emptycheck(
                    subj['proc']['time'][i]['mid'] / subj['proc']['time'][i]['total'] * 100
                    if not np.isnan(subj['proc']['time'][i]['mid']) else None)
                subj['proc']['time_p'][i]['hind'] = emptycheck(
                    subj['proc']['time'][i]['hind'] / subj['proc']['time'][i]['total'] * 100
                    if not np.isnan(subj['proc']['time'][i]['hind']) else None)
            else:
                for key in ['mid', 'hind']:
                    subj['proc']['force'][i][key] = np.nan
                    subj['proc']['force_bw'][i][key] = np.nan
                    subj['proc']['area'][i][key] = np.nan
                    subj['proc']['kpa'][i][key] = np.nan
                    subj['proc']['time'][i][key] = np.nan
                    subj['proc']['time_p'][i][key] = np.nan

        # ---- Main comparison figure ----
        # GridSpec: 2 rows (feet side-by-side, table) x 4 cols (L gantt, L heat, R gantt, R heat)
        fig_main = plt.figure(figsize=(16, 10))
        fig_main.suptitle(f'Pedobarograph\n{subj["name"]}', fontsize=12)
        gs = fig_main.add_gridspec(
            2, 3,
            height_ratios=[6, 2],
            width_ratios=[2, 3, 2],
            hspace=0.4, wspace=0.3,
        )

        def _fmt_val(val, decimals=1):
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return 'N/A'
            return f'{val:.{decimals}f}'

        # Normative time_p for timing chart overlays
        _nn_tp_mean = _nn_tp_std = None
        if novel_norm is not None:
            try:
                _nn_tp_mean = novel_norm['norm_time_p_mean'].flatten()  # [fore, mid, hind]
                _nn_tp_std  = novel_norm['norm_time_p_std'].flatten()
            except Exception:
                pass

        table_data = {}   # keyed by side label ('L' / 'R')
        gantt_data = {}   # COP region masks for combined gantt chart

        for i in range(2):
            fidx = subj['orig']['f_indx'][i]
            if fidx is None:
                continue

            side_label  = subj['proc']['side'][i] or ''
            heat_col = 0 if side_label == 'L' else 2
            toewalker_i = subj['proc']['toewalker'][i] == 'Yes'
            cop_total   = subj['proc']['cop'][i].get('total', np.array([]))
            coord_nz    = subj['proc']['mpp'][i].get('coord_nz', np.array([]))
            mesh        = subj['proc']['mpp'][i].get('mesh', {})
            fpa_val     = subj['proc']['fpa'][i]

            fpa_str = ''
            if fpa_val is not None and not (isinstance(fpa_val, float) and np.isnan(fpa_val)):
                fpa_dir = 'Out' if fpa_val > 0 else ('In' if fpa_val < 0 else 'Neutral')
                fpa_str = f'FPA: {fpa_val:.1f}° ({fpa_dir}-toeing)'

            # Collect COP region masks for the combined gantt chart (both feet)
            if cop_total.ndim == 2 and cop_total.shape[0] > 0:
                _n_frames_g = cop_total.shape[0]
                if toewalker_i:
                    # Toewalker: entire stance is forefoot contact
                    gantt_data[side_label] = {
                        'fore':     np.ones(_n_frames_g, dtype=bool),
                        'mid':      np.zeros(_n_frames_g, dtype=bool),
                        'hind':     np.zeros(_n_frames_g, dtype=bool),
                        'n_frames': _n_frames_g,
                    }
                else:
                    _mid_idx_s = subj['proc']['cop'][i].get('mid_idx', [])
                    if _mid_idx_s:
                        _thr_mn = min(_mid_idx_s)
                        _thr_mx = max(_mid_idx_s)
                    else:
                        _thr_mn = _thr_mx = 0
                    # Interpolate over NaN COP frames to close noise-caused gaps
                    _cop_x = cop_total[:, 2].copy()
                    _valid = ~np.isnan(_cop_x)
                    if np.any(~_valid) and np.any(_valid):
                        _cop_x = np.interp(np.arange(_n_frames_g),
                                           np.where(_valid)[0], _cop_x[_valid])
                    _fore_mask = _cop_x + 1 <= _thr_mn
                    _mid_mask  = (_cop_x + 1 > _thr_mn) & (_cop_x + 1 < _thr_mx)
                    _hind_mask = _cop_x + 1 >= _thr_mx
                    # Match direction convention used in compute_novel_norm_stats:
                    # heel-toe COP starts at heel (hind/large-primary end).
                    # If early frames are at small primary, PCA flipped → swap fore↔hind.
                    _nc_g = max(1, _n_frames_g // 5)
                    if np.nanmean(_cop_x[:_nc_g]) < np.nanmean(_cop_x[-_nc_g:]):
                        _fore_mask, _hind_mask = _hind_mask, _fore_mask
                    gantt_data[side_label] = {
                        'fore':     _fore_mask,
                        'mid':      _mid_mask,
                        'hind':     _hind_mask,
                        'n_frames': _n_frames_g,
                    }

            # ---- Col: Pressure heatmap (toes-up orientation) ----
            ax_heat = fig_main.add_subplot(gs[0, heat_col])
            if mesh and 'x' in mesh:
                mx, my, mz = mesh['x'], mesh['y'], mesh['z']
                mz_plot = np.where(np.isnan(mz), 0, mz)
                # Swap x/y: long axis (primary) runs vertically; apply_foot_image_orientation
                # then flips y so small primary values (toes) end up at top.
                # Use 1D coordinate vectors so C shape matches after transpose.
                x1d = mx[0, :]   # primary axis (long/heel-toe), n_x points
                y1d = my[:, 0]   # secondary axis (width), n_y points
                ax_heat.pcolormesh(y1d, x1d, mz_plot.T, cmap=JET_MOD_CMAP,
                                   vmin=15, vmax=275, shading='auto')
                mz_bin = np.where(np.isnan(mz), 0, (mz > 0).astype(float))
                if mz_bin.any():
                    ax_heat.contour(y1d, x1d, mz_bin.T, levels=[0.5],
                                    colors='white', linewidths=0.8, alpha=0.6)
            else:
                ax_heat.pcolormesh(subj['orig']['mpp_unrot'][fidx],
                                   cmap=JET_MOD_CMAP, vmin=15, vmax=275, shading='auto')
            if cop_total.ndim == 2 and cop_total.shape[0] > 0:
                # Swap COP columns to match transposed orientation
                ax_heat.plot(cop_total[:, 3], cop_total[:, 2],
                             'o-k', linewidth=1.5, markersize=2)
            apply_foot_image_orientation(ax_heat)
            # Left toe walkers: secondary axis is raw sensor x, which is opposite to right foot;
            # flip it so the big toe appears on the anatomically correct (right) side.
            if side_label == 'L' and toewalker_i:
                ax_heat.invert_xaxis()
            ax_heat.set_aspect('equal')
            ax_heat.axis('off')
            ax_heat.set_title(f'{side_label}  {subj["proc"]["fname"][i]}', fontsize=7)
            # Rotation angle below heatmap: negative = internal, positive = external
            if fpa_val is not None and not (isinstance(fpa_val, float) and np.isnan(fpa_val)):
                rot_dir = 'Int. rot.' if fpa_val < 0 else ('Ext. rot.' if fpa_val > 0 else 'Neutral')
                ax_heat.text(0.5, -0.04, f'Rotation: {fpa_val:+.1f}°  ({rot_dir})',
                             transform=ax_heat.transAxes,
                             ha='center', va='top', fontsize=8, clip_on=False)
            else:
                ax_heat.text(0.5, -0.04, 'Toe walker',
                             transform=ax_heat.transAxes,
                             ha='center', va='top', fontsize=8, clip_on=False)

            # Collect table data
            def _tp(key):
                v = subj['proc']['time'][i].get(key, np.nan)
                return v if v is not None else np.nan
            def _tpp(key):
                v = subj['proc']['time_p'][i].get(key, np.nan)
                return v if v is not None else np.nan

            table_data[side_label] = {
                'M':     (_tp('fore'),  _tpp('fore')),
                'N':     (_tp('mid'),   _tpp('mid')),
                'L':     (_tp('hind'),  _tpp('hind')),
                'Total': (_tp('total'), 100.0),
            }

        # ---- Combined Contact Timing Gantt (center column) ----
        # Green bars = normative expected time per region (heel→mid→fore, sequential).
        # Blue bars = left foot actual COP presence per region.
        # Red bars  = right foot actual COP presence per region.
        # Sum of all green bars = 100%; sum of all patient bars = 100%.
        ax_gantt = fig_main.add_subplot(gs[0, 1])
        _gantt_rows = [('M', 'fore', 2), ('N', 'mid', 1), ('L', 'hind', 0)]

        def _gantt_segs(mask, n_frames):
            """Return list of (start_pct, end_pct) for each contiguous True block."""
            padded = np.concatenate([[False], mask, [False]])
            changes = np.diff(padded.astype(int))
            starts = np.where(changes == 1)[0]
            ends   = np.where(changes == -1)[0]
            return [(s / n_frames * 100, e / n_frames * 100)
                    for s, e in zip(starts, ends)]

        # if _nn_tp_mean is not None:
        #     nn_hind = float(_nn_tp_mean[2])
        #     nn_mid  = float(_nn_tp_mean[1])
        # else:
        nn_hind, nn_mid = 29.0, 24.0  # fixed 40/40/20 split
        _norm_spans = {
            'hind': (0,                nn_hind),
            'mid':  (nn_hind,          nn_hind + nn_mid),
            'fore': (nn_hind + nn_mid, 100),
        }
        for _, key, y_pos in _gantt_rows:
            s0, s1 = _norm_spans[key]
            ax_gantt.barh(y_pos, s1 - s0, left=s0,
                          height=0.7, color='green', alpha=0.35, linewidth=0)

        for _side, _color, _yoff in [('L', 'blue', 0.20), ('R', 'red', -0.20)]:
            if _side not in gantt_data:
                continue
            _gd = gantt_data[_side]
            for _, key, y_pos in _gantt_rows:
                for seg_s, seg_e in _gantt_segs(_gd[key], _gd['n_frames']):
                    ax_gantt.barh(y_pos + _yoff, seg_e - seg_s, left=seg_s,
                                  height=0.07, color=_color, alpha=0.9, linewidth=0)

        ax_gantt.set_yticks([0, 1, 2])
        ax_gantt.set_yticklabels(['L', 'N', 'M'], fontsize=9)
        ax_gantt.set_xlim(0, 100)
        ax_gantt.set_ylim(-0.6, 2.6)
        ax_gantt.set_xlabel('% Stance', fontsize=8)
        ax_gantt.spines['top'].set_visible(False)
        ax_gantt.spines['right'].set_visible(False)
        ax_gantt.set_title('Contact Timing\nBlue = L    Red = R    Green = Norm', fontsize=8)

        # ---- Row 1: Comparison table (spans all 4 columns) ----
        ax_tbl = fig_main.add_subplot(gs[1, :])
        ax_tbl.axis('off')

        col_labels = ['Region',
                      'L time (ms)', 'L time (%)',
                      'R time (ms)', 'R time (%)']
        rows_order = ['M', 'N', 'L', 'Total']
        # norm_tp_map: region → index in _nn_tp_mean [fore=0, mid=1, hind=2]
        norm_idx = {'M': 0, 'N': 1, 'L': 2, 'Total': None}

        tbl_rows = []
        for region in rows_order:
            l_vals = table_data.get('L', {}).get(region, (np.nan, np.nan))
            r_vals = table_data.get('R', {}).get(region, (np.nan, np.nan))
            n_i = norm_idx[region]
            if n_i is not None and _nn_tp_mean is not None:
                norm_ann = f'\n(N:{_fmt_val(_nn_tp_mean[n_i])}±{_fmt_val(_nn_tp_std[n_i])}%)'
            else:
                norm_ann = ''
            tbl_rows.append([
                region,
                _fmt_val(l_vals[0], 0),
                _fmt_val(l_vals[1]) + norm_ann,
                _fmt_val(r_vals[0], 0),
                _fmt_val(r_vals[1]) + norm_ann,
            ])

        tbl = ax_tbl.table(
            cellText=tbl_rows, colLabels=col_labels,
            loc='center', cellLoc='center',
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1, 1.8)
        ax_tbl.set_title('Regional Contact Summary  (N = Novel_Norm mean ± SD)',
                          fontsize=8, pad=4)

        fig_main.tight_layout()
        plt.pause(0.1)

        save_fig(fig_main, os.path.join(savedir, f"{subj['name']}_{subj['dos']}_select"))
        plt.close(fig_main)

        # ---- Bar graphs ----
        def _get(d, key, default=np.nan):
            val = d.get(key, default)
            return val if val is not None else default

        fig_bar, axes_bar = plt.subplots(5, 1, figsize=(8, 15))
        fig_bar.suptitle(f'Pedobarograph\n{subj["name"]}', fontsize=12)

        metrics = [
            ('force', 'Max Force', 'Force (N)'),
            ('force_bw', 'Max Normalized Force', 'Force (%BW)'),
            ('area', 'Contact Area', 'Area (cm^2)'),
            ('kpa', 'Max Pressure', 'Pressure (kPa)'),
            ('time_p', 'Contact Time', 'Time (%)'),
        ]
    # in the end we may not know the qualities of th emetrics that are brought to the ending part of this analysis so we may need to be careful about how we access the data for the bar graphs. we should use a helper.

        for m_idx, (metric_key, title_m, ylabel_m) in enumerate(metrics):
            ax_b = axes_bar[m_idx]
            total_lr = [
                _get(subj['proc'][metric_key][0], 'total'),
                _get(subj['proc'][metric_key][1], 'total'),
            ]
            hind_lr = [
                _get(subj['proc'][metric_key][0], 'hind'),
                _get(subj['proc'][metric_key][1], 'hind'),
            ]
            mid_lr = [
                _get(subj['proc'][metric_key][0], 'mid'),
                _get(subj['proc'][metric_key][1], 'mid'),
            ]
            fore_lr = [
                _get(subj['proc'][metric_key][0], 'fore'),
                _get(subj['proc'][metric_key][1], 'fore'),
            ]
            # Replace NaN with 0 for plotting
            total_lr = [0 if np.isnan(v) else v for v in total_lr]
            hind_lr = [0 if np.isnan(v) else v for v in hind_lr]
            mid_lr = [0 if np.isnan(v) else v for v in mid_lr]
            fore_lr = [0 if np.isnan(v) else v for v in fore_lr]
            emedbarplot(ax_b, total_lr, hind_lr, mid_lr, fore_lr, title_m, ylabel_m)

        axes_bar[0].legend(['Left', 'Right'], loc='upper right', fontsize=8)
        fig_bar.tight_layout()
        plt.pause(0.1)

        save_fig(fig_bar, os.path.join(savedir, f"{subj['name']}_{subj['dos']}_emed_graphs"))
        plt.close(fig_bar)

    else:
        print('No step files identified')

    # ------------------------------------------------------------------
    # XL strides
    # ------------------------------------------------------------------
    xl_indices = [i for i, ft in enumerate(subj['ftype']) if ft == 'xl']
    if xl_indices:
        n_xl = len(xl_indices)
        fig_xl, axes_xl = plt.subplots(1, n_xl, figsize=(6 * n_xl, 8))
        if n_xl == 1:
            axes_xl = [axes_xl]
        fig_xl.suptitle('Pedobarograph\nFull Stride', fontsize=12)

        for i, xl_idx in enumerate(xl_indices):
            ax_xl = axes_xl[i]
            mpp = subj['orig']['mpp_unrot'][xl_idx]
            cop = subj['orig']['cop_unrot'][xl_idx]

            if mpp is not None and mpp.ndim == 2 and mpp.size > 0:
                ax_xl.pcolormesh(mpp, cmap=JET_MOD_CMAP, vmin=10, vmax=300, shading='auto')
            apply_foot_image_orientation(ax_xl)

            if cop is not None and cop.ndim == 2 and cop.shape[0] > 0 and cop.shape[1] >= 6:
                xc = cop[:, 5]
                yc = cop[:, 4]
                ax_xl.plot(xc, yc, 'o-y', linewidth=2, markersize=2, label='COP')
                ax_xl.plot(xc[0], yc[0], 'o-g', linewidth=4, markersize=6, label='Start')
                ax_xl.plot(xc[-1], yc[-1], 'o-r', linewidth=4, markersize=6, label='End')

                # Flip view direction based on COP direction
                # If start y < end y, flip (180 deg rotation = invert axes)
                if cop[0, 4] < cop[-1, 4]:
                    ax_xl.invert_xaxis()
                    ax_xl.invert_yaxis()

            ax_xl.set_aspect('equal')
            ax_xl.axis('off')
            ax_xl.set_title(fname_list[xl_idx], fontsize=8)

        axes_xl[-1].legend(['Pressure', 'COP', 'Start', 'End'],
                            loc='lower center', fontsize=8,
                            ncol=4, frameon=False)
        fig_xl.tight_layout()
        plt.pause(0.1)

        save_fig(fig_xl, os.path.join(savedir, f"{subj['name']}_{subj['dos']}_emed_xl_strides"))
        plt.close(fig_xl)

    # ------------------------------------------------------------------
    # Static analysis
    # ------------------------------------------------------------------
    static_indices = [i for i, ft in enumerate(subj['ftype']) if ft == 'static']
    if static_indices:
        static_indx = static_indices[0]
        cop_static = subj['orig']['cop_unrot'][static_indx]
        mpp_static = subj['orig']['mpp_unrot'][static_indx]

        if cop_static.ndim == 2 and cop_static.shape[0] > 0 and cop_static.shape[1] >= 6:
            x_cop = cop_static[:, 5]
            y_cop = cop_static[:, 4]

            center, radius = minboundcircle(x_cop, y_cop)
            static_cop_dist = np.sum(np.hypot(np.diff(x_cop), np.diff(y_cop)))
            static_cop_mean = np.array([np.mean(x_cop), np.mean(y_cop)])

            mpp_size = mpp_static.shape if mpp_static.ndim == 2 else (0, 0)
            perc_lr = np.array([
                np.sum(x_cop < mpp_size[0] / 2) / len(x_cop),
                np.sum(x_cop > mpp_size[0] / 2) / len(x_cop)
            ]) * 100
            perc_ap = np.array([
                np.sum(y_cop < mpp_size[1] / 2) / len(y_cop),
                np.sum(y_cop > mpp_size[1] / 2) / len(y_cop)
            ]) * 100

            fig_st, ax_st = plt.subplots(1, 1, figsize=(8, 10))
            fig_st.suptitle(f'Pedobarograph\n{subj["name"]} Static', fontsize=12)

            if mpp_static.ndim == 2 and mpp_static.size > 0:
                ax_st.pcolormesh(mpp_static, cmap=JET_MOD_CMAP, vmin=10, vmax=300, shading='auto')
            apply_foot_image_orientation(ax_st)

            ax_st.plot(x_cop, y_cop, 'o-y', linewidth=2, markersize=2, label='COP')
            ax_st.plot(x_cop[0], y_cop[0], 'o-g', linewidth=4, markersize=6, label='Start')
            ax_st.plot(x_cop[-1], y_cop[-1], 'o-r', linewidth=4, markersize=6, label='End')
            ax_st.plot(static_cop_mean[0], static_cop_mean[1], 'xk', linewidth=3,
                       markersize=10, label='Mean')

            # Draw bounding circle
            circle_plot(ax_st, center[0], center[1], radius, style='-c', label='Subj Min Bound')

            # Draw normative circle if available
            if norm is not None:
                try:
                    norm_r_mean = float(np.squeeze(norm['radius_mean']))
                    norm_r_std = float(np.squeeze(norm['radius_std']))
                    circle_plot(ax_st, center[0], center[1],
                                norm_r_mean + 2 * norm_r_std, style=':k', label='2 SD Norm Bound')
                except Exception:
                    pass

            ax_st.set_aspect('equal')
            ax_st.axis('off')
            ax_st.legend(loc='upper right', fontsize=8, frameon=True)

            # Ask toes up?
            static_flip = questdlg('Toes up?', 'Static Correction', ['Yes', 'No'], 'Yes')
            if static_flip == 'No':
                ax_st.invert_xaxis()
                ax_st.invert_yaxis()

            # Build text annotation
            dist_str = 'NaN' if np.isnan(static_cop_dist) else f'{round(static_cop_dist * 100) / 100:.2f}'
            rad_str = 'NaN' if np.isnan(radius) else f'{round(radius * 100) / 100:.2f}'
            text_lines = [
                f'COP distance: {dist_str} cm',
            ]
            if norm is not None:
                try:
                    dist_mean = float(np.squeeze(norm['cop_dist_mean']))
                    dist_std = float(np.squeeze(norm['cop_dist_std']))
                    norm_r_mean = float(np.squeeze(norm['radius_mean']))
                    norm_r_std = float(np.squeeze(norm['radius_std']))
                    text_lines.append(
                        f'COP Norm (2 SD): {round(dist_mean*100)/100:.2f} '
                        f'({round(2*dist_std*100)/100:.2f})')
                    text_lines.append(f'Radius: {rad_str} cm')
                    text_lines.append(
                        f'Radius Norm (2 SD): {round(norm_r_mean*100)/100:.2f} '
                        f'({round(2*norm_r_std*100)/100:.2f})')
                except Exception:
                    text_lines.append(f'Radius: {rad_str} cm')
            else:
                text_lines.append(f'Radius: {rad_str} cm')

            # Place textbox
            ax_st.text(0.75, 0.85, '\n'.join(text_lines),
                       transform=ax_st.transAxes, fontsize=9,
                       verticalalignment='top', horizontalalignment='center',
                       bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

            fig_st.tight_layout()
            plt.pause(0.1)

            save_fig(fig_st, os.path.join(savedir,
                f"{subj['name']}_{subj['dos']}_emed_static_pressure"))
            plt.close(fig_st)

    if has_steps:
        print('\n=== Foot Progression Angles ===')
        for i in range(2):
            side = subj['proc']['side'][i]
            fpa = subj['proc']['fpa'][i]
            if side is not None:
                if fpa is None or (isinstance(fpa, float) and np.isnan(fpa)):
                    print(f'  {side}: N/A')
                else:
                    fpa_dir = 'Out-toeing' if fpa > 0 else ('In-toeing' if fpa < 0 else 'Neutral')
                    print(f'  {side}: {fpa:.1f}° ({fpa_dir})')

    combine_pdfs(savedir, subj['name'], subj['dos'])
    print(f'All done! Saved to {savedir}')
    plt.ioff()

    if context is not None:
        prefix = f"{subj['name']}_{subj['dos']}_"
        output_files = sorted(
            os.path.join(savedir, f) for f in os.listdir(savedir)
            if f.startswith(prefix) and (f.endswith('.pdf') or f.endswith('.png'))
        )
        return make_run_result("success", output_dir=savedir, output_files=output_files,
                                summary={"files_loaded": len(fname_list)})
    return None


def main(context=None, inputs=None):
    # `inputs`, for this module, is the already-computed result dict that
    # collect_inputs produced during the batch's preflight pass — see
    # collect_inputs's docstring for why this module can't be split the way
    # the simpler modules are.
    if inputs is not None:
        return inputs
    return collect_inputs(context=context)


if __name__ == '__main__':
    main()
