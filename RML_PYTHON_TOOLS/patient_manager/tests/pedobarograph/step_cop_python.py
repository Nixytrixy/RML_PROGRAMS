import numpy as np
import os
import sys

from typing import List, Tuple, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, simpledialog
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection

try:
    from stl import mesh as stl_mesh  # numpy-stl
    STL_AVAILABLE = True
except Exception:
    STL_AVAILABLE = False

# =======================
# User-tunable appearance
# =======================

# Placeholder colormaps – you can swap these later
COP_AVG_COLORMAP = plt.cm.viridis  # average COP gradient
COP_STEPS_COLORMAP = plt.cm.plasma  # individual steps (if used)

# Foot surface appearance
FOOT_FACE_COLOR = (0.8, 0.8, 1.0)
FOOT_EDGE_COLOR = "none"

# Line styles
ORTHOTIC_STEP_COLOR = "C0"
BAREFOOT_SD_COLOR = "k"
BAREFOOT_SD_STYLE = "--"

# Scaling factors (shoe)
YSCALE = 33.5
XSCALE = (-9.6, 9.2)  # (medial-negative, lateral-positive)


# =======================
# Utility functions
# =======================

def ask_directory(prompt: str) -> str:
    """
    Ask the user for a directory.
    Falls back to input() if Tk is not available or fails.
    """
    if TK_AVAILABLE:
        try:
            root = tk.Tk()
            root.withdraw()
            path = filedialog.askdirectory(title=prompt)
            root.destroy()
            if path:
                return path
        except Exception:
            pass

    # Fallback
    while True:
        path = input(f"{prompt}\n(Type or paste a folder path): ").strip('"').strip()
        if os.path.isdir(path):
            return path
        print("That path does not exist. Please try again.")


def ask_text(prompt: str, default: str = "") -> str:
    """
    Ask the user for a short text string (e.g., subject ID).
    """
    if TK_AVAILABLE:
        try:
            root = tk.Tk()
            root.withdraw()
            text = simpledialog.askstring("Input", prompt, initialvalue=default)
            root.destroy()
            if text is not None:
                return text
        except Exception:
            pass
    # Fallback
    val = input(f"{prompt} [{default}]: ").strip()
    return val or default


def load_cop_files(folderdir: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray,
                                            str, str, str, str]:
    """
    Load COP txt files from a directory and split into:
    - left/right
    - orthotic/barefoot
    Returns:
      left_orth, right_orth, left_bare, right_bare, and their filenames.
    """
    # Find files matching *COP*.txt
    candidates = [
        f for f in os.listdir(folderdir)
        if f.lower().endswith(".txt") and "cop" in f.lower()
    ]

    if not candidates:
        if TK_AVAILABLE:
            root = tk.Tk()
            root.withdraw()
            files = filedialog.askopenfilenames(
                title="Select COP files", initialdir=folderdir,
                filetypes=[("COP text files", "*COP*.txt"),
                           ("Text files", "*.txt"),
                           ("All files", "*.*")]
            )
            root.destroy()
            if not files:
                print("No COP files selected. Aborting.")
                sys.exit(1)
            paths = list(files)
        else:
            print("No *COP*.txt files found in the directory.")
            print("Please ensure your COP files are present and try again.")
            sys.exit(1)
    else:
        paths = [os.path.join(folderdir, f) for f in candidates]

    left_orth = right_orth = left_bare = right_bare = None
    left_orth_name = right_orth_name = left_bare_name = right_bare_name = ""

    for path in paths:
        name = os.path.basename(path)
        lname = name.lower()
        is_left = "left" in lname
        is_right = "right" in lname
        is_orth = "orthotic" in lname
        is_bare = "barefoot" in lname

        try:
            data = np.loadtxt(path, skiprows=1)

        except Exception as e:
            print(f"Could not load file {name}: {e}")
            continue

        # If first row is header (length > 101 rows), drop the first row
        if data.shape[0] > 101:
            data = data[1:, :]

        if is_left and is_orth:
            left_orth = data
            left_orth_name = name
        elif is_right and is_orth:
            right_orth = data
            right_orth_name = name
        elif is_left and is_bare:
            left_bare = data
            left_bare_name = name
        elif is_right and is_bare:
            right_bare = data
            right_bare_name = name

    # Simple sanity checks
    if left_orth is None or right_orth is None:
        print("Missing orthotic COP data for left or right foot.")
        sys.exit(1)
    if left_bare is None or right_bare is None:
        print("Missing barefoot COP data for left or right foot.")
        sys.exit(1)

    return (left_orth, right_orth, left_bare, right_bare,
            left_orth_name, right_orth_name, left_bare_name, right_bare_name)


def parse_side_cop(data: np.ndarray,
                   xscale: Tuple[float, float],
                   yscale: float,
                   side: str) -> Tuple[List[np.ndarray], np.ndarray, Optional[np.ndarray]]:
    """
    Parse COP data for one side and condition.

    Parameters
    ----------
    data : np.ndarray
        Raw COP matrix (after optional header row removal).
    xscale : (float, float)
        Scaling for x (medial/lateral) from XSCALE.
    yscale : float
        Scaling for y (AP).
    side : {'left', 'right'}
        Side identifier. The MATLAB code treats left and right slightly differently.

    Returns
    -------
    steps : list of (101 x 3) arrays
        Individual foot-strike COP traces (X, Y, Z).
    mean_xy : (101 x 3) array
        Average COP (X, Y, Z).
    sd_xy : (101 x 3) array or None
        Standard deviation COP (X, Y, Z), or None if no SD present.
    """
    n_cols = data.shape[1]
    steps: List[np.ndarray] = []

    has_multiple_steps = n_cols > 6
    has_single_step = n_cols == 6

    x_medial, x_lateral = xscale

    if side.lower() not in ("left", "right"):
        raise ValueError("side must be 'left' or 'right'")

    if has_multiple_steps:
        # col1: index
        # cols2-4: mean
        # cols5-7: SD
        # cols8+: steps in groups of 3 (X,Y,Z)
        for start_col in range(7, n_cols, 3):  # 0-based index: col8 => idx7
            step = np.array(data[:, start_col:start_col + 3], dtype=float)
            # Flip ML axis sign
            step[:, 0] *= -1.0

            if side.lower() == "right":
                # V3D + is medial, but for plotting negative is medial
                mask_pos = step[:, 0] > 0
                mask_neg = step[:, 0] < 0
                step[mask_pos, 0] *= x_lateral
                step[mask_neg, 0] *= abs(x_medial)
            else:
                # Left: after flipping sign, negative = lateral
                mask_neg = step[:, 0] < 0
                mask_pos = step[:, 0] > 0
                step[mask_neg, 0] *= x_lateral
                step[mask_pos, 0] *= abs(x_medial)

            step[:, 1] *= yscale
            steps.append(step)

        # Mean
        mean_xy = np.array(data[:, 1:4], dtype=float)
        mean_xy[:, 0] *= -1.0
        if side.lower() == "right":
            mask_pos = mean_xy[:, 0] > 0
            mask_neg = mean_xy[:, 0] < 0
            mean_xy[mask_pos, 0] *= x_lateral
            mean_xy[mask_neg, 0] *= abs(x_medial)
        else:
            mask_neg = mean_xy[:, 0] < 0
            mask_pos = mean_xy[:, 0] > 0
            mean_xy[mask_neg, 0] *= x_lateral
            mean_xy[mask_pos, 0] *= abs(x_medial)
        mean_xy[:, 1] *= yscale

        # SD
        sd_xy = np.array(data[:, 4:7], dtype=float)
        sd_xy[:, 0] *= -1.0
        if side.lower() == "right":
            mask_pos = sd_xy[:, 0] > 0
            mask_neg = sd_xy[:, 0] < 0
            sd_xy[mask_pos, 0] *= x_lateral
            sd_xy[mask_neg, 0] *= abs(x_medial)
        else:
            mask_neg = sd_xy[:, 0] < 0
            mask_pos = sd_xy[:, 0] > 0
            sd_xy[mask_neg, 0] *= x_lateral
            sd_xy[mask_pos, 0] *= abs(x_medial)
        sd_xy[:, 1] *= yscale

        return steps, mean_xy, sd_xy

    elif has_single_step:
        # cols2-4 as the single step, no SD.
        step = np.array(data[:, 1:4], dtype=float)
        step[:, 0] *= -1.0

        if side.lower() == "right":
            mask_pos = step[:, 0] > 0
            mask_neg = step[:, 0] < 0
            step[mask_pos, 0] *= x_lateral
            step[mask_neg, 0] *= abs(x_medial)
        else:
            mask_neg = step[:, 0] < 0
            mask_pos = step[:, 0] > 0
            step[mask_neg, 0] *= x_lateral
            step[mask_pos, 0] *= abs(x_medial)

        step[:, 1] *= yscale
        return [step], step.copy(), None

    else:
        raise ValueError("Unexpected COP data format: check number of columns.")


# =======================
# STL / Foot mesh helpers
# =======================

def load_foot_mesh(stl_path: str):
    """
    Load the shoe STL as a numpy-stl Mesh.
    Returns (mesh_right, mesh_left) after orientation / mirroring.
    """
    if not STL_AVAILABLE:
        print("Warning: numpy-stl is not installed; foot mesh will not be drawn.")
        return None, None

    if not os.path.isfile(stl_path):
        print(f"Warning: STL file not found at {stl_path}; foot mesh will not be drawn.")
        return None, None

    base_mesh = stl_mesh.Mesh.from_file(stl_path)

    # Make copies for right and left
    mesh_right = base_mesh.copy()
    mesh_left = base_mesh.copy()

    # Right foot orientation (based on your MATLAB transforms)
    v = mesh_right.vectors.reshape(-1, 3)
    v[:, 1] *= -1.0
    v[:, 1] -= v[:, 1].min()  # heel at 0
    v[:, 2] *= -1.0
    v[:, 0] *= -1.0
    mesh_right.vectors = v.reshape(-1, 3, 3)

    # Left foot orientation
    vl = mesh_left.vectors.reshape(-1, 3)
    vl[:, 1] *= -1.0
    vl[:, 1] -= vl[:, 1].min()
    vl[:, 2] *= -1.0
    mesh_left.vectors = vl.reshape(-1, 3, 3)

    return mesh_right, mesh_left


def add_mesh_to_axis(ax, mesh_obj, face_color=FOOT_FACE_COLOR, edge_color=FOOT_EDGE_COLOR):
    """
    Add a numpy-stl mesh to a 3D axis as a Poly3DCollection.
    """
    if mesh_obj is None:
        return

    collection = Poly3DCollection(
        mesh_obj.vectors,
        facecolor=face_color,
        edgecolor=edge_color
    )
    ax.add_collection3d(collection)
    ax.auto_scale_xyz([0, 1], [0, 1], [0, 1])  # adjust limits to fit mesh
    
# =======================
# Plotting helpers
# =======================

def make_avg_cop_line_collection(mean_xy: np.ndarray,
                                 z_height: float = 2.0,
                                 cmap=COP_AVG_COLORMAP) -> Line3DCollection:
    """
    Create a 3D line collection with a color gradient along the COP path.
    """
    n = mean_xy.shape[0]
    xs = mean_xy[:, 0]
    ys = mean_xy[:, 1]
    zs = np.full_like(xs, z_height, dtype=float)

    points = np.stack([xs, ys, zs], axis=1)
    segments = np.stack([points[:-1], points[1:]], axis=1)  # (n-1, 2, 3)

    lc = Line3DCollection(segments, cmap=cmap)
    t = np.linspace(0, 1, n - 1)  # gradient parameter
    lc.set_array(t)
    lc.set_linewidth(2.0)
    
    return lc



def plot_side(ax,
              mesh_obj,
              steps_orth: List[np.ndarray],
              mean_orth: np.ndarray,
              sd_orth: Optional[np.ndarray],
              mean_bare: np.ndarray,
              sd_bare: Optional[np.ndarray],
              side_label: str):
    """
    Plot one side (left or right) with shoe surface, COP paths, and SD envelope.
    """
    # Foot mesh
    add_mesh_to_axis(ax, mesh_obj)

    # Average orthotic COP with gradient
    avg_line = make_avg_cop_line_collection(mean_orth, z_height=2.0)
    ax.add_collection3d(avg_line)

    # Individual orthotic steps
    step_handles = []
    step_labels = []
    for i, step in enumerate(steps_orth, start=1):
        xs = step[:, 0]
        ys = step[:, 1]
        zs = np.ones_like(xs)  # small offset above surface
        h = ax.plot(xs, ys, zs, '-', color=ORTHOTIC_STEP_COLOR, linewidth=1.5)[0]
        step_handles.append(h)
        step_labels.append(f"Orthotic Step {i}")

    # Barefoot 1 SD envelope (mean ± SD) if we have SD
    env_handle = None
    if sd_bare is not None:
        sdplus = mean_bare + sd_bare
        sdminus = mean_bare - sd_bare
        for env in (sdplus, sdminus):
            xs = env[:, 0]
            ys = env[:, 1]
            zs = np.ones_like(xs)
            env_handle = ax.plot(xs, ys, zs, BAREFOOT_SD_STYLE,
                                 color=BAREFOOT_SD_COLOR, linewidth=1.0)[0]

    ax.set_title(f"{side_label} Foot COP")
    ax.set_axis_off()
    ax.set_box_aspect([1, 2, 0.2])  # elongated AP aspect

    # Legend (orthotic steps + barefoot envelope)
    handles = step_handles.copy()
    labels = step_labels.copy()
    if env_handle is not None:
        handles.append(env_handle)
        labels.append("Barefoot 1 SD Env")

    if handles:
        ax.legend(handles, labels, loc="upper left", fontsize=8)


# =======================
# Main pipeline
# =======================

def main():
    print("=== Center of Pressure (COP) Plotter – Python Version ===")

    # 1) Choose COP directory
    folderdir = ask_directory("Select directory of COP files")

    # 2) Choose save directory
    savedir = ask_directory("Select directory to save results")
    os.makedirs(savedir, exist_ok=True)

    # 3) Subject info
    subj_id = ask_text("Enter the Subject ID:", "")
    dos_str = ask_text("Date of Service (e.g., MMDDYYYY or MM/DD/YYYY):", "MMDDYYYY")

    # Flatten DOS digits to make a compact tag (like MATLAB regexp '\d*')
    dos_digits = "".join(ch for ch in dos_str if ch.isdigit())
    subj_dos_short = dos_digits or dos_str.replace("/", "").replace("-", "")

    # 4) Load COP files
    (left_orth_raw, right_orth_raw,
     left_bare_raw, right_bare_raw,
     left_orth_name, right_orth_name,
     left_bare_name, right_bare_name) = load_cop_files(folderdir)

    # 5) Parse each side/condition with scaling
    left_orth_steps, left_orth_mean, left_orth_sd = parse_side_cop(
        left_orth_raw, XSCALE, YSCALE, side="left"
    )
    right_orth_steps, right_orth_mean, right_orth_sd = parse_side_cop(
        right_orth_raw, XSCALE, YSCALE, side="right"
    )
    left_bare_steps, left_bare_mean, left_bare_sd = parse_side_cop(
        left_bare_raw, XSCALE, YSCALE, side="left"
    )
    right_bare_steps, right_bare_mean, right_bare_sd = parse_side_cop(
        right_bare_raw, XSCALE, YSCALE, side="right"
    )

    # 6) Load foot STL (optional)
    # Adjust this if your STL is somewhere else
    stl_path = os.path.join("stls", "10700_Sneaker_v201.stl")
    mesh_right, mesh_left = load_foot_mesh(stl_path)

    # 7) Create figure with two subplots: Left(1), Right(2)
    fig = plt.figure(figsize=(10, 6))
    ax_left = fig.add_subplot(1, 2, 1, projection="3d")
    ax_right = fig.add_subplot(1, 2, 2, projection="3d")

    # Right side plot
    plot_side(
        ax_right,
        mesh_right,
        steps_orth=right_orth_steps,
        mean_orth=right_orth_mean,
        sd_orth=right_orth_sd,
        mean_bare=right_bare_mean,
        sd_bare=right_bare_sd,
        side_label="Right"
    )

    # Left side plot
    plot_side(
        ax_left,
        mesh_left,
        steps_orth=left_orth_steps,
        mean_orth=left_orth_mean,
        sd_orth=left_orth_sd,
        mean_bare=left_bare_mean,
        sd_bare=left_bare_sd,
        side_label="Left"
    )

    # 8) Shared colorbar for the average orthotic COP gradient
    sm = plt.cm.ScalarMappable(cmap=COP_AVG_COLORMAP)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=[ax_left, ax_right], fraction=0.03, pad=0.05)
    cbar.set_label("Average Orthotic COP", fontsize=10, fontweight="bold")
    cbar.set_ticks([0.0, 1.0])
    cbar.set_ticklabels(["Start", "End"])

    fig.suptitle(f"{subj_id}  –  DOS: {dos_str}", fontsize=12)
    fig.patch.set_facecolor("white")

    # 9) Save PNG and PDF
    out_base = f"{subj_id}_{subj_dos_short}_COP"
    png_path = os.path.join(savedir, out_base + ".png")
    pdf_path = os.path.join(savedir, out_base + ".pdf")

    print(f"Saving figure to:\n  {png_path}\n  {pdf_path}")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, dpi=300, bbox_inches="tight")

    print("Done.")


if __name__ == "__main__":
    main()
