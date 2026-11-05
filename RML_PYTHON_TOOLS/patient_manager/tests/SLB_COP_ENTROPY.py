# COP Entropy Analysis
# Author: Sean Brown
# Date: 2025-04-18
# Version: 1.0
# Description: Analyze forceplate signals to calculate COP trajectories for entropy metrics

# Version 2.0 - 2025-04-21
# Added Docstring to each function
# COP trajectory has been updated to center bounding circle to (0, 0) and scale all condition axes to make comparisons easier

# Version 3.0 - 2025-5-12
# Added 95% enclosing circle to COP

# Version 4.0 - 2025-6-2
# Added 95% enclosing ellipse
# Added Excel export for patient reports

# ---------------------- IMPORTS ----------------------
import os
import shutil
import inspect
import pandas as pd
import numpy as np
import miniball
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import ListedColormap
import matplotlib.image as mpimg
import matplotlib.patches as patches
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
from scipy.spatial import ConvexHull
from scipy.signal import decimate
from math import factorial
from collections import Counter
from sklearn.metrics import auc
import tkinter as tk
from tkinter import filedialog, simpledialog
from io import BytesIO
from PIL import Image
from tqdm import tqdm
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Side

# ---------------------- CONFIGURATION ----------------------
EXPECTED_SUFFIXES = {
    "Eyes Open - Right": "SLB_EO_Right_COP.txt",
    "Eyes Closed - Right": "SLB_EC_Right_COP.txt",
    "Eyes Open - Left": "SLB_EO_Left_COP.txt",
    "Eyes Closed - Left": "SLB_EC_Left_COP.txt"
}

ENTROPY_THRESHOLDS = {
    "sample": (0.2, 0.4, 0.7),
    "perm": (0.5, 0.75, 1.0)
}

# ---------------------- UTILITY FUNCTIONS ----------------------
def name(): 
    return "SLB COP Entropy Analysis"
def sanitize_label(label):
    """
    Sanitizes a string label by replacing spaces and dashes with underscores.

    Used to generate safe file names and dictionary keys.

    Parameters
    ----------
    label : str
        The string label to sanitize.

    Returns
    -------
    str
        The sanitized string label.
    """
    return label.replace(" ", "_").replace("-", "_").replace("__", "_")

def load_logo():
    """
    Loads a logo image for use in the analysis.

    This function first attempts to load a logo image from a hardcoded file path.
    If the image is not found, it prompts the user to manually select an image file
    via a file dialog. The function returns the loaded image if successful, or None
    if no image is selected.

    Returns
    -------
    numpy.ndarray or None
        The loaded image as a NumPy array if successful, or None if no image is selected.
    """

    logo_path = r"C:\\Users\sean0096\\OneDrive - Multicare Health System\\Python\\Logo\\MB_logo.png"
    if os.path.exists(logo_path):
        return mpimg.imread(logo_path)
    else:
        print("⚠️ Logo image not found at the hardcoded path.")
        root = tk.Tk()
        root.withdraw()
        user_logo_path = filedialog.askopenfilename(
            title="Select Logo Image",
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp")]
        )
        if user_logo_path:
            print(f"✅ User-selected logo loaded from: {user_logo_path}")
            return mpimg.imread(user_logo_path)
        else:
            print("⚠️ No logo selected. Logo will not be included.")
            return None

def get_subject_info():
    """
    Opens a dialog window to collect subject study code and date of study.

    This function creates a Tkinter dialog window that prompts the user to enter
    the subject study code and the date of the study. The user inputs are collected
    via entry fields and can be submitted by clicking the "Submit" button. The function
    returns the entered subject code and study date, or default values if not provided.

    Returns
    -------
    tuple
        A tuple containing the subject study code and the date of study. If the user
        does not provide an input, default values "Unknown_Subject" and "Unknown_Date"
        are returned.
    """

    info_window = tk.Toplevel()
    info_window.title("Enter Subject Info")

    tk.Label(info_window, text="Subject Study Code:").grid(row=0, column=0, padx=10, pady=5, sticky="e")
    tk.Label(info_window, text="Date of Study (MM/DD/YYYY):").grid(row=1, column=0, padx=10, pady=5, sticky="e")

    code_entry = tk.Entry(info_window)
    date_entry = tk.Entry(info_window)
    code_entry.grid(row=0, column=1, padx=10, pady=5)
    date_entry.grid(row=1, column=1, padx=10, pady=5)

    code_entry.focus()
    info_window.input_ready = False

    def submit():
        info_window.subject_code = code_entry.get().strip() or "Unknown_Subject"
        info_window.study_date = date_entry.get().strip() or "Unknown_Date"
        info_window.input_ready = True
        info_window.destroy()

    tk.Button(info_window, text="Submit", command=submit).grid(row=2, column=0, columnspan=2, pady=10)

    info_window.update_idletasks()
    x = (info_window.winfo_screenwidth() - info_window.winfo_reqwidth()) // 2
    y = (info_window.winfo_screenheight() - info_window.winfo_reqheight()) // 2
    info_window.geometry(f"+{x}+{y}")

    info_window.grab_set()
    info_window.wait_window()

    return getattr(info_window, 'subject_code', "Unknown_Subject"), getattr(info_window, 'study_date', "Unknown_Date")

def find_condition_files(folder, expected_suffixes):
    """
    Finds files in a given folder that match expected suffixes.

    Parameters
    ----------
    folder : str
        The path to the folder containing the files to search.
    expected_suffixes : dict
        A dictionary mapping condition names to expected file suffixes.

    Returns
    -------
    dict
        A dictionary mapping condition names to the matching file paths. If no file
        matches for a given condition, a FileNotFoundError is raised.

    Notes
    -----
    If multiple files match for a given condition, a warning is printed and the first
    match is used.
    """
    files = {}
    for cond, suffix in expected_suffixes.items():
        matched = [f for f in os.listdir(folder) if f.endswith(suffix)]
        if matched:
            files[cond] = os.path.join(folder, matched[0])
            if len(matched) > 1:
                print(f"⚠️ Multiple matches for {cond}, using: {matched[0]}")
        else:
            print(f"❌ Missing: {cond} → {suffix}")
    if len(files) < len(expected_suffixes):
        raise FileNotFoundError("🚫 Missing COP files.")
    return files

def compute_cop(Fx, Fy, Fz, Mx, My, h=0):
    COPx = (-My - Fx * h) / Fz
    COPy = (Mx - Fy * h) / Fz
    return COPx, COPy

# # ---------------------- FILE SELECTION ----------------------
# logo_img = load_logo()
# root = tk.Tk()
# root.withdraw()
# folder_selected = filedialog.askdirectory(title="Select Folder Containing COP Text Files")
# print("\n📂 Selected Folder:", folder_selected)

# files = find_condition_files(folder_selected, EXPECTED_SUFFIXES)
# subject_code, study_date = get_subject_info()
# print(f"\n🧾 Subject Study Code: {subject_code}")
# print(f"📅 Date of Study: {study_date}")

# save_folder = filedialog.askdirectory(title="Select Folder to Save Results")
# print(f"💾 Results will be saved to: {save_folder}")

# # ---------------------- TEMP IMAGE BUFFER FOR PDF ----------------------
# temp_images = {}
# trajectory_info = {}
# entropy_time_series_data = {}

# # ---------------------- CREATE CODE FOLDER AND SAVE SCRIPT ----------------------
# code_dir = os.path.join(folder_selected, "Code")
# os.makedirs(code_dir, exist_ok=True)

# try:
#     current_script_path = inspect.getframeinfo(inspect.currentframe()).filename
#     script_filename = os.path.basename(current_script_path)
#     save_path = os.path.join(code_dir, script_filename)
#     shutil.copy2(current_script_path, save_path)
#     print(f"🧾 Code copied to: {save_path}")
# except Exception as e:
#     print(f"❌ Failed to copy code: {e}")

# # ---------------------- CREATE FIGURE SAVE DIRECTORY ----------------------
# figure_dir = os.path.join(save_folder, "SLB_Figures")
# os.makedirs(figure_dir, exist_ok=True)

# Figure Functions
# ---------------------- MINIMAL ENCLOSING CIRCLE ----------------------
def minimal_enclosing_circle(points):
    # points must be an (N, 2) numpy array
    """
    Compute the center and radius of the minimal enclosing circle (MEC) of a set of 2D points.

    Parameters
    ----------
    points : numpy array of shape (N, 2)
        The 2D points to compute the MEC for.

    Returns
    -------
    center : numpy array of shape (2,)
        The center of the MEC.
    radius : float
        The radius of the MEC.

    Notes
    -----
    This function uses the miniball library to compute the MEC.
    """
    center, radius_squared = miniball.get_bounding_ball(points)
    radius = np.sqrt(radius_squared)
    return center, radius

# ---------------------- FIGURE SAVE FUNCTION ----------------------
def save_figure(fig, condition, name):
    """
    Save a figure to a file in the figure directory.

    Parameters
    ----------
    fig : matplotlib figure
        The figure to save.
    condition : str
        The condition (e.g. 'Eyes Open - Left') to include in the filename.
    name : str
        A descriptive name to include in the filename.

    Returns
    -------
    None
    """
    condition_clean = condition.replace(" - ", "_").replace(" ", "_")
    fig_filename = f"{subject_code}_{condition_clean}_{name}.png"
    fig_path = os.path.join(figure_dir, fig_filename)
    fig.savefig(fig_path, dpi=600)
    print(f"📸 Saved figure to: {fig_path}")

# ---------------------- BAR PLOTS ----------------------
def plot_entropy_bargraph(entropy_dict, title, ylabel, ylim, thresholds, filename=None):
    """
    Plot a bar graph of entropy values for each condition and axis.

    Parameters
    ----------
    entropy_dict : dict
        A dictionary of entropy values for each condition and axis.
    title : str
        The title of the plot.
    ylabel : str
        The label for the y-axis.
    ylim : tuple
        The limits for the y-axis.
    thresholds : tuple
        The thresholds for the low, moderate, and high zones.
    filename : str, optional
        The filename to save the figure to. If None, the figure will not be saved.

    Returns
    -------
    None
    """
    conditions = ['Eyes Open - Left', 'Eyes Closed - Left', 'Eyes Open - Right', 'Eyes Closed - Right']
    axes = ['COPx (ML)', 'COPy (AP)', 'COP Magnitude']
    bar_width = 0.25
    x = np.arange(len(conditions))
    colors = ['#8da0cb', '#e78ac3', '#a6d854']  # Match axes

    fig, ax = plt.subplots(figsize=(12, 6))

    # Background zones
    low, moderate, high = thresholds
    ax.axhspan(0, low, color='red', alpha=0.25)
    ax.axhspan(low, moderate, color='yellow', alpha=0.25)
    ax.axhspan(moderate, ylim[1], color='lightgreen', alpha=0.5)

    for i, axis in enumerate(axes):
        values = [entropy_dict[cond][axis] for cond in conditions]
        positions = x + (i - 1) * bar_width
        bars = ax.bar(positions, values, bar_width, label=axis, color=colors[i], edgecolor='black')
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, height + 0.01, f"{height:.2f}", ha='center', va='bottom', fontsize=8)

    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(conditions, rotation=15)
    ax.set_ylim(ylim)
    ax.legend()

    ax.text(1.01, (0 + low)/2 / ylim[1], 'Low', transform=ax.transAxes, rotation=270, va='center')
    ax.text(1.01, (low + moderate)/2 / ylim[1], 'Moderate', transform=ax.transAxes, rotation=270, va='center')
    ax.text(1.01, (moderate + ylim[1])/2 / ylim[1], 'High', transform=ax.transAxes, rotation=270, va='center')

    for spine in ax.spines.values():
        spine.set_edgecolor('black')

    plt.tight_layout()
    if filename:
        fig_name = f"{subject_code}_{filename}.png"
        fig_path = os.path.join(figure_dir, fig_name)
        fig.savefig(fig_path, dpi=600)
        print(f"📊 Saved bar graph to: {fig_path}")
    plt.show(block=False)
    plt.pause(2)
    plt.close(fig)

def create_combined_pdf(output_path, subject_code, study_date, logo_img=None):
    # Map for arranging subplots
    """
    Creates a combined PDF with subplots for different balance conditions.

    Parameters:
    output_path (str): Path to save the output PDF file.
    subject_code (str): Code representing the subject of the study.
    study_date (str): Date of the study.
    logo_img (Optional[ndarray]): Image array of the logo to be included in the PDF.

    The function arranges four subplots on a 2x2 grid, each representing a different 
    balance condition (Eyes Open/Closed - Left/Right). If the corresponding images are 
    not found in the `temp_images`, a placeholder text "Missing: <Label>" is displayed 
    instead. An optional logo can be added at the bottom left of the PDF. The layout 
    is adjusted to fit the content and saved to the specified output path.
    """

    order = [
        ("Eyes Open - Left", "Left_EO"),
        ("Eyes Open - Right", "Right_EO"),
        ("Eyes Closed - Left", "Left_EC"),
        ("Eyes Closed - Right", "Right_EC")
    ]

    with PdfPages(output_path) as pdf:
        fig, axs = plt.subplots(2, 2, figsize=(8.5, 11))  # Portrait mode

        # Title block
        fig.suptitle("Single Leg Balance Center of Pressure", fontsize=16, y=0.98)
        fig.text(0.5, 0.95, subject_code, ha='center', fontsize=12)
        fig.text(0.5, 0.93, study_date, ha='center', fontsize=10)

        # Add each plot
        for ax, (title, label) in zip(axs.flatten(), order):
            if label not in temp_images:
                ax.axis("off")
                ax.text(0.5, 0.5, f"Missing: {label}", ha='center', va='center')
                continue

            # Show image
            ax.imshow(temp_images[label])
            ax.axis("off")
            ax.set_title(title, fontsize=11)

            # Optional: Add text beneath each figure (example only)
            ax.text(0.5, -0.08,
                    f"COP Distance: ...\nRadius: ...\n# Opposite Foot Touches: ...",
                    transform=ax.transAxes, ha='center', va='top', fontsize=8)

        # Add logo (optional)
        if logo_img is not None:
            fig.figimage(logo_img, xo=30, yo=30, origin='lower', zorder=10, alpha=0.8)

        plt.tight_layout(rect=[0.05, 0.1, 0.95, 0.92])
        pdf.savefig(fig)

        print(f"📄 PDF page created: {output_path}")

# ---------------------- ENTROPY FUNCTIONS ----------------------

# # Store entropy results for summary plots
# sample_entropy_data = {'COPx (ML)': [], 'COPy (AP)': [], 'COP Magnitude': []}
# perm_entropy_data = {'COPx (ML)': [], 'COPy (AP)': [], 'COP Magnitude': []}

def sample_entropy(signal, m=2, r=None):
    """
    Compute the sample entropy of a signal.

    Parameters
    ----------
    signal : array
        The input signal.
    m : int, optional
        The embedding dimension. Defaults to 2.
    r : float, optional
        The tolerance or similarity criterion. Defaults to 0.2 * standard deviation of the signal.

    Returns
    -------
    float
        The sample entropy of the signal.

    Notes
    -----
    The sample entropy is a measure of complexity or irregularity in a signal. It is defined as the negative natural logarithm of the conditional probability that two sequences of length m that are similar within a tolerance r will remain similar at the next point.

    See Also
    --------
    compute_multiscale_entropy

    References
    ----------
    Richman, J. S., & Moorman, J. R. (2000). Physiological time-series analysis using approximate entropy and sample entropy. American Journal of Physiology-Heart and Circulatory Physiology, 278(6), H2039-H2049.
    """
    signal = np.array(signal, dtype=float)
    N = len(signal)
    if r is None:
        r = 0.2 * np.std(signal)

    def _phi(m):
        """
        Compute the probability that two sequences of length m that are similar within a tolerance r will remain similar at the next point.

        Parameters
        ----------
        m : int
            The embedding dimension.

        Returns
        -------
        float
            The probability that two sequences of length m that are similar within a tolerance r will remain similar at the next point.

        Notes
        -----
        This is a helper function for sample_entropy.
        """
        x = np.array([signal[i:i + m] for i in range(N - m + 1)])
        C = np.sum(np.max(np.abs(x[:, None] - x[None, :]), axis=2) <= r, axis=0) - 1
        return np.sum(C) / (N - m + 1)

    try:
        return -np.log(_phi(m + 1) / _phi(m))
    except:
        return np.nan

def compute_perm_entropy(signal, order=3, delay=1, normalize=False):
    """
    Compute the permutation entropy of a signal.

    Parameters
    ----------
    signal : array
        The input signal.
    order : int, optional
        The embedding dimension. Defaults to 3.
    delay : int, optional
        The delay between samples. Defaults to 1.
    normalize : bool, optional
        Whether to normalize the permutation entropy. Defaults to False.

    Returns
    -------
    float
        The permutation entropy of the signal.

    Notes
    -----
    The permutation entropy is a measure of complexity or irregularity in a signal. It is defined as the negative natural logarithm of the probability of a permutation of the signal.

    See Also
    --------
    sample_entropy

    References
    ----------
    Bandt, C., & Pompe, B. (2002). Permutation entropy: A natural complexity measure for time series. Physical Review Letters, 88(17), 174102.
    """

    n = len(signal)
    permutations = []
    for i in range(n - delay * (order - 1)):
        window = signal[i:(i + delay * order):delay]
        perm = tuple(np.argsort(window))
        permutations.append(perm)
    c = Counter(permutations)
    total = sum(c.values())
    probs = np.array(list(c.values())) / total
    pe = -np.sum(probs * np.log(probs))
    if normalize:
        pe /= np.log(factorial(order))
    return pe

def compute_multiscale_entropy(signal, max_scale=10, min_length=50, verbose=False):
    """
    Compute the multiscale entropy of a signal.

    Parameters
    ----------
    signal : array_like
        The signal to compute the multiscale entropy for.
    max_scale : int, optional
        The maximum scale to compute the entropy for. Defaults to 10.
    min_length : int, optional
        The minimum length of the coarse-grained signal at a given scale. If the length is less than this, the entropy will be computed as NaN. Defaults to 50.
    verbose : bool, optional
        Whether to print messages if a scale is skipped. Defaults to False.

    Returns
    -------
    list
        The multiscale entropy of the signal.

    Notes
    -----
    The multiscale entropy of a signal is a measure of its complexity or irregularity at different time scales. It is computed by taking the average of the sample entropies of the coarse-grained signal at each scale.

    See Also
    --------
    sample_entropy

    References
    ----------
    Costa, M., Goldberger, A. L., & Peng, C. K. (2005). Multiscale entropy analysis of biological signals. Physical Review E, 71(2), 021906.
    """
    mse = []
    signal = np.asarray(signal).flatten()
    for scale in range(1, max_scale + 1):
        n = len(signal) // scale
        if n < min_length:
            mse.append(np.nan)
            if verbose:
                print(f"Scale {scale}: Skipped (only {n} samples)")
            continue
        coarse = np.mean(signal[:n * scale].reshape(n, scale), axis=1)
        if np.std(coarse) < 1e-8:
            mse.append(np.nan)
            if verbose:
                print(f"Scale {scale}: Skipped (low variance)")
            continue
        se = sample_entropy(coarse)
        mse.append(se)
    return mse

def mmse(copx, copy, max_scale=10, m=2, r_ratio=0.2, verbose=False):
    """
    Computes the multiscale sample entropy of two signals, copx and copy, as a measure of their complexity or irregularity at different time scales.

    Parameters
    ----------
    copx, copy : array_like
        The two signals to compute the multiscale sample entropy of.
    max_scale : int, optional
        The maximum scale to compute the multiscale sample entropy at. Defaults to 10.
    m : int, optional
        The length of the template to use when computing the sample entropy. Defaults to 2.
    r_ratio : float, optional
        The ratio of the standard deviation of the signal to use as the tolerance when computing the sample entropy. Defaults to 0.2.
    verbose : bool, optional
        Whether to print messages if a scale is skipped. Defaults to False.

    Returns
    -------
    list
        The multiscale sample entropy of the two signals.

    Notes
    -----
    The multiscale sample entropy is a measure of the complexity or irregularity of two signals at different time scales. It is computed by taking the average of the sample entropies of the coarse-grained signals at each scale.

    See Also
    --------
    sample_entropy

    References
    ----------
    Costa, M., Goldberger, A. L., & Peng, C. K. (2005). Multiscale entropy analysis of biological signals. Physical Review E, 71(2), 021906.
    """
    mmse_values = []
    copx = (copx - np.mean(copx)) / np.std(copx)
    copy = (copy - np.mean(copy)) / np.std(copy)
    for scale in range(1, max_scale + 1):
        n = len(copx) // scale
        if n < m + 1:
            mmse_values.append(np.nan)
            if verbose:
                print(f"Scale {scale}: Too few samples ({n})")
            continue
        cg_copx = np.mean(copx[:n*scale].reshape(n, scale), axis=1)
        cg_copy = np.mean(copy[:n*scale].reshape(n, scale), axis=1)
        joint = np.stack((cg_copx, cg_copy), axis=1)
        r = r_ratio * np.std(joint, axis=0).mean()
        N = len(joint)
        count_m, count_m1 = 0, 0
        for i in range(N - m):
            template_m = joint[i:i+m]
            template_m1 = joint[i:i+m+1]
            for j in range(i + 1, N - m):
                window_m = joint[j:j+m]
                window_m1 = joint[j:j+m+1]
                dist_m = np.max(np.abs(template_m - window_m))
                dist_m1 = np.max(np.abs(template_m1 - window_m1))
                if dist_m <= r:
                    count_m += 1
                if dist_m1 <= r:
                    count_m1 += 1
        try:
            mmse_val = -np.log(count_m1 / count_m)
        except:
            mmse_val = np.nan
        mmse_values.append(mmse_val)
    return mmse_values

def plot_entropy_summary(sampen_x, sampen_y, sampen_mag,
                         mse_x, mse_y, mse_mag, mmse,
                         title_suffix=""):
    """
    Visualizes Sample Entropy summary and MSE/MMSE curves with AUC.
    
    Parameters:
    - sampen_x, sampen_y, sampen_mag: Sample entropy values for COPx, COPy, and magnitude
    - mse_x, mse_y, mse_mag: Multiscale entropy values for COPx, COPy, and magnitude
    - mmse: Multivariate multiscale entropy values for COPx & COPy
    - title_suffix: Optional string to tag the plot titles (e.g., trial name)
    """

    scales = np.arange(1, len(mse_x) + 1)

    # Calculate AUCs
    auc_x = auc(scales, mse_x)
    auc_y = auc(scales, mse_y)
    auc_mag = auc(scales, mse_mag)
    auc_mmse = auc(scales, mmse)

    # Create performance scale plot
    fig, ax = plt.subplots(figsize=(10, 2.5))
    zones = [(0, 0.2, 'red'), (0.2, 0.4, 'yellow'), (0.4, 0.7, 'green')]
    for start, end, color in zones:
        ax.axvspan(start, end, color=color, alpha=0.6)

    # Plot entropy values
    ax.plot(sampen_x, 1.2, 'bo', label='SampEn COPx')
    ax.plot(sampen_y, 1.2, 'go', label='SampEn COPy')
    ax.plot(sampen_mag, 1.2, 'ko', label='SampEn COP Magnitude')

    # # Add text labels
    # ax.text(sampen_x, 1.25, f'{sampen_x:.3f}', ha='center', fontsize=9)
    # ax.text(sampen_y, 1.25, f'{sampen_y:.3f}', ha='center', fontsize=9)
    # ax.text(sampen_mag, 1.25, f'{sampen_mag:.3f}', ha='center', fontsize=9)

    # Formatting
    ax.set_xlim(0, 0.7)
    ax.set_ylim(1.1, 1.35)
    ax.set_yticks([])
    ax.set_xlabel("Sample Entropy")
    ax.set_title("Entropy Summary Scale" + title_suffix)
    ax.legend(loc='upper left')
    ax.text(0.1, 1.15, "Low", color='black', ha='center', fontsize=9)
    ax.text(0.3, 1.15, "Moderate", color='black', ha='center', fontsize=9)
    ax.text(0.55, 1.15, "High", color='black', ha='center', fontsize=9)

    plt.tight_layout()
    save_figure(fig, condition, "Sample_Entropy_Summary")
    plt.show(block=False)
    plt.pause(2)
    plt.close(fig)

def plot_permutation_entropy_summary(perm_x, perm_y, perm_mag, title="Permutation Entropy Summary"):
    """
    Visualizes Permutation Entropy for COPx, COPy, and Magnitude on a complexity scale.
    """
    fig, ax = plt.subplots(figsize=(10, 2.5))

    # Color zones (adjust these ranges if needed)
    zones = [(0.0, 0.5, 'red'), (0.5, 0.75, 'yellow'), (0.75, 1.0, 'green')]
    for start, end, color in zones:
        ax.axvspan(start, end, color=color, alpha=0.5)

    # Plot entropy values
    ax.plot(perm_x, 1.2, 'bo', label='COPx (ML)')
    ax.plot(perm_y, 1.2, 'go', label='COPy (AP)')
    ax.plot(perm_mag, 1.2, 'ko', label='COP Magnitude')

    # Annotate values
    # ax.text(perm_x, 1.25, f"{perm_x:.3f}", ha='center')
    # ax.text(perm_y, 1.25, f"{perm_y:.3f}", ha='center')
    # ax.text(perm_mag, 1.25, f"{perm_mag:.3f}", ha='center')

    # Formatting
    ax.set_xlim(0, 1.0)
    ax.set_ylim(1.1, 1.35)
    ax.set_yticks([])
    ax.set_xlabel("Permutation Entropy")
    ax.set_title(title)
    ax.legend(loc='upper left')
    ax.text(0.25, 1.15, "Low", ha='center', fontsize=9)
    ax.text(0.625, 1.15, "Moderate", ha='center', fontsize=9)
    ax.text(0.875, 1.15, "High", ha='center', fontsize=9)

    plt.tight_layout()
    save_figure(fig, condition, "Permutation_Entropy_Summary")
    plt.show(block=False)
    plt.pause(2)
    plt.close(fig)

def get_overlay_auc_text(entropy_data, label_map, metric_name):
    """
    Generates a textual summary of the AUC values for specified entropy metrics across different conditions.

    Args:
        entropy_data (dict): A dictionary containing entropy metrics for various conditions.
        label_map (dict): A mapping from verbose condition names to dictionary keys used in entropy_data.
        metric_name (str): The name of the metric for which the AUC values are to be retrieved.

    Returns:
        str: A formatted string with lines for each condition indicating the AUC value or an error message if data is missing.
    """

    lines = []
    for label in ['Eyes Open-Left', 'Eyes Open-Right', 'Eyes Closed-Left', 'Eyes Closed-Right']:
        key = label_map.get(label, None)
        if key is None:
            lines.append(f"{label}: key not mapped")
        elif key not in entropy_data:
            lines.append(f"{label}: key missing")
        elif metric_name not in entropy_data[key]:
            lines.append(f"{label}: {metric_name} missing")
        else:
            val = entropy_data[key][metric_name]
            lines.append(f"{label}: {val:.2f}")
    return '\n'.join(lines)

def compute_ellipse_metrics(x, y):
    """
    Compute ellipse metrics from a set of 2D points.
 
    Parameters
    ----------
    x, y : array-like
        The x and y coordinates of the points.
    Returns
    -------
    a, b : float
        The lengths of the semi-major and semi-minor axes.
    area : float
        The area of the ellipse.
    angle : float
        The angle of rotation of the ellipse from the x-axis.

    Notes
    -----
    The confidence interval for the ellipse is set to 95%.
    The area calculation is for an ellipse with axes of lengths a and b.
    The angle is in degrees, with positive values indicating a counter-clockwise rotation.
    """
    x_centered = x - np.mean(x)
    y_centered = y - np.mean(y)
    points = np.vstack((x_centered, y_centered)).T
    cov = np.cov(points, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = eigvals.argsort()[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    chi2_val = 5.991  # 95% confidence for 2D
    a = 2 * np.sqrt(chi2_val * eigvals[0])
    b = 2 * np.sqrt(chi2_val * eigvals[1])
    area = np.pi * a * b / 4
    angle = np.degrees(np.arctan2(eigvecs[1, 0], eigvecs[0, 0])) # angle of rotation with no adjustment
    return a, b, area, angle

# Excel Report Table Export Functions
# === Export COP Metrics ===
def export_cop_metrics_excel(trajectory_info, subject_code, save_folder):
    """
    Exports Center of Pressure (COP) metrics to an Excel file.

    This function creates an Excel workbook to store the COP metrics for a given 
    subject. Each metric is categorized under conditions for left and right sides 
    with eyes open and closed. The generated file includes a formatted header, 
    metric values, and styled cells.

    Parameters:
    - trajectory_info (dict): A dictionary containing COP metric data for different conditions.
    - subject_code (str): A unique identifier for the subject.
    - save_folder (str): The directory where the Excel file will be saved.

    The Excel file is saved with the name format: "SLB_COP_<subject_code>.xlsx".
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "COP Metrics"

    # Title and header rows
    ws.merge_cells('A1:E1')
    ws['A1'] = "Single Leg Balance - Center of Pressure"
    ws['A1'].alignment = Alignment(horizontal="left")

    ws.append(["", "Left", "", "Right", ""])
    ws.append(["", "Eyes Open", "Eyes Closed", "Eyes Open", "Eyes Closed"])
    ws.merge_cells('A2:A3')
    ws.merge_cells('B2:C2')
    ws.merge_cells('D2:E2')
    ws['A2'] = "COP = Center\nof Pressure"
    ws['A2'].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Metrics and values
    metric_map = {
        "COP Distance (cm)": "path",
        "COP Radius (cm)": "radius",
        "95% Radius": "radius_95",
        "# Foot Touches": "touches",
        "Ellipse Major Axis (cm)": "ellipse_a",
        "Ellipse Minor Axis (cm)": "ellipse_b",
        "Ellipse Area (cm²)": "ellipse_area",
        "Ellipse Angle (deg)": "adjusted_angle"
    }

    for metric_label, key in metric_map.items():
        row = [metric_label]
        for side in ["Left", "Right"]:
            for eyes in ["Eyes Open", "Eyes Closed"]:
                label = f"{eyes} - {side}".replace(" - ", "_").replace(" ", "_")
                value = trajectory_info.get(label, {}).get(key, "")
                row.append(value)
        ws.append(row)

    # Apply styling AFTER appending all data
    center_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=5):
        for cell in row:
            cell.alignment = center_align
            cell.border = thin_border
            if isinstance(cell.value, (float, int)):
                cell.number_format = '0.0'  # One decimal place

    # Column widths
    ws.column_dimensions["A"].width = 22
    for col in ["B", "C", "D", "E"]:
        ws.column_dimensions[col].width = 12

    for row in ws.iter_rows(min_row=7, max_row=7, min_col=1, max_col=5):
        for cell in row:
            cell.alignment = center_align
            cell.border = thin_border
            if isinstance(cell.value, (float, int)):
                cell.number_format = '0'  # No decimal place

    # Save file
    excel_path = os.path.join(save_folder, f"SLB_COP_{subject_code}.xlsx")
    wb.save(excel_path)
    print(f"📁 COP Excel exported to: {excel_path}")

# === Export Entropy Metrics ===
def export_entropy_metrics_excel(entropy_data, subject_code, save_folder):
    """
    Exports entropy metrics to an Excel file for a given subject.

    This function creates an Excel workbook with entropy metrics data for different
    conditions of a single leg balance task. The workbook includes a formatted sheet
    with headers and styled cells for clear presentation of data.

    Parameters:
    entropy_data (dict): A dictionary containing entropy metrics categorized by condition.
    subject_code (str): A code identifying the subject for which the data is relevant.
    save_folder (str): The folder path where the Excel file will be saved.

    The Excel file includes columns for both eyes open and eyes closed conditions,
    and the left and right sides, with metrics for mediolateral, anteroposterior,
    and total magnitude of center of pressure (COP).

    The file is saved in the specified save folder with the filename format
    "SLB_COP_Entropy_<subject_code>.xlsx".
    """

    wb = Workbook()
    ws = wb.active
    ws.title = "Single Leg Balance - Entropy"

    # Header
    ws.merge_cells('A1:E1')
    ws['A1'] = "Single Leg Balance - Entropy"
    ws['A1'].alignment = Alignment(horizontal="left")

    ws.append(["", "Left", "", "Right", ""])
    ws.append(["", "Eyes Open", "Eyes Closed", "Eyes Open", "Eyes Closed"])
    ws.merge_cells('A2:A3')
    ws.merge_cells('B2:C2')
    ws.merge_cells('D2:E2')
    ws['A2'] = "COP = Center\nof Pressure"
    ws['A2'].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    metric_map = {
        "COP: Mediolateral": "auc_x",
        "COP: Anteroposterior": "auc_y",
        "COP: Total Magnitude": "auc_mag"
    }

    for metric_label, key in metric_map.items():
        row = [metric_label]
        for side in ["Left", "Right"]:
            for eyes in ["Eyes Open", "Eyes Closed"]:
                label = f"{eyes} - {side}".replace(" - ", "_").replace(" ", "_")
                value = entropy_data.get(label, {}).get(key, "")
                row.append(value)
        ws.append(row)

    # Define center alignment
    center_align = Alignment(horizontal="center", vertical="center")

    # Loop through cells in A2:E6
    for row in ws.iter_rows(min_row=2, max_row=6, min_col=1, max_col=5):
        for cell in row:
            cell.alignment = center_align

    # Define thin border style
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Apply border to A2:E6
    for row in ws.iter_rows(min_row=2, max_row=6, min_col=1, max_col=5):
        for cell in row:
            cell.border = thin_border
            if isinstance(cell.value, (float, int)):
                cell.number_format = '0.00'  # Two decimal places

    # Set column widths
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 12

    excel_path = os.path.join(save_folder, f"SLB_COP_Entropy_{subject_code}.xlsx")
    wb.save(excel_path)
    print(f"📁 Entropy Excel exported to: {excel_path}")

# ======================
# ---- PROCESS DATA ----
# ======================
# for condition, file_path in tqdm(files.items(), desc="Processing COP trials", unit="trial"):
#     print(f"\n----- Processing: {condition} -----")

#     # Load data
#     data = pd.read_csv(file_path, sep='\t', skiprows=4)

#     Fx = data.iloc[:, 16].values
#     Fy = data.iloc[:, 17].values
#     Fz = (data.iloc[:, 18].values) * -1
#     Mx = data.iloc[:, 19].values
#     My = (data.iloc[:, 20].values) * -1
#     Mz = data.iloc[:, 21].values
#     Foot_Touches = None
#     if data.shape[1] > 22:
#         Foot_Touches = data.iloc[0, 22] # Foot_Touches is stored as a single cell value (int) in column 23, or left blank for 0

#     # Calculate COP
#     h = 0
#     COPx = (-My - Fx * h) / Fz
#     COPy = (Mx - Fy * h) / Fz
#     valid = np.isfinite(COPx) & np.isfinite(COPy)
#     COPx = COPx[valid]
#     COPy = COPy[valid]

#     # Save raw decimated COP for radius/path metrics
#     COPx_raw = decimate(COPx, 10)
#     COPy_raw = decimate(COPy, 10)
#     # Convert to cm for plotting and distance metrics
#     COPx_raw_cm = COPx_raw * 100
#     COPy_raw_cm = COPy_raw * 100

#     # Normalize for entropy analysis
#     COPx_ds = (COPx_raw - np.mean(COPx_raw)) / np.std(COPx_raw)
#     COPy_ds = (COPy_raw - np.mean(COPy_raw)) / np.std(COPy_raw)

#     # COP magnitude
#     COPmag = np.sqrt(COPx_ds**2 + COPy_ds**2)
#     COPmag -= np.mean(COPmag)
#     COPmag /= np.std(COPmag)

#     # Entropies
#     samp_entropy_x = sample_entropy(COPx_ds)
#     samp_entropy_y = sample_entropy(COPy_ds)
#     samp_entropy_mag = sample_entropy(COPmag)

#     perm_entropy_x = compute_perm_entropy(COPx_ds, normalize=True)
#     perm_entropy_y = compute_perm_entropy(COPy_ds, normalize=True)
#     perm_entropy_COPmag = compute_perm_entropy(COPmag, normalize=True)

#     mse_x = compute_multiscale_entropy(COPx_ds)
#     mse_y = compute_multiscale_entropy(COPy_ds)
#     mse_mag = compute_multiscale_entropy(COPmag)
#     mmse_xy = mmse(COPx_ds, COPy_ds, max_scale=10)

#     auc_x = auc(np.arange(1, len(mse_x) + 1), mse_x)
#     auc_y = auc(np.arange(1, len(mse_y) + 1), mse_y)
#     auc_mag = auc(np.arange(1, len(mse_mag) + 1), mse_mag)
#     auc_mmse = auc(np.arange(1, len(mmse_xy) + 1), mmse_xy)

#     safe_label = condition.replace(" - ", "_").replace(" ", "_")
#     entropy_time_series_data[safe_label] = {
#     "mse_x": mse_x,
#     "mse_y": mse_y,
#     "mse_mag": mse_mag,
#     "mmse": mmse_xy,
#     "sampen_x": samp_entropy_x,
#     "sampen_y": samp_entropy_y,
#     "sampen_mag": samp_entropy_mag,
#     "perm_x": perm_entropy_x,
#     "perm_y": perm_entropy_y,
#     "perm_mag": perm_entropy_COPmag,  
#     "auc_x": auc_x,
#     "auc_y": auc_y,
#     "auc_mag": auc_mag,
#     "auc_mmse": auc_mmse
#     }

#     # COP Path & Radius
#     cop_distances = np.sqrt(np.diff(COPx_raw)**2 + np.diff(COPy_raw)**2)
#     cop_path_length = np.sum(cop_distances) * 100 # Convert to cm
#     cop_points = np.vstack((COPx_raw_cm, COPy_raw_cm)).T
#     cop_center, radius_squared = miniball.get_bounding_ball(cop_points)
#     cop_radius = np.sqrt(radius_squared)

#     # --- 95% Enclosing Circle (remove outliers) ---
#     mean_x = np.mean(COPx_raw_cm)
#     mean_y = np.mean(COPy_raw_cm)
#     center_mean = np.array([mean_x, mean_y])
#     distances = np.linalg.norm(cop_points - center_mean, axis=1)

#     threshold = np.percentile(distances, 95)
#     core_points = cop_points[distances <= threshold]
#     core_center, core_radius_sq = miniball.get_bounding_ball(core_points)
#     core_radius = np.sqrt(core_radius_sq)

#     # COP Trajectory Plot (raw data in meters)
#     fig, ax = plt.subplots(figsize=(6, 6))
#     points = np.array([COPx_raw_cm, COPy_raw_cm]).T.reshape(-1, 1, 2)
#     segments = np.concatenate([points[:-1], points[1:]], axis=1)
#     cmap = ListedColormap(plt.cm.RdYlGn(np.linspace(1, 0, len(COPx_raw))))
#     norm = plt.Normalize(0, len(COPx_raw))
#     lc = LineCollection(segments, cmap=cmap, norm=norm)
#     lc.set_array(np.arange(len(COPx_raw)))
#     lc.set_linewidth(2)
#     ax.add_collection(lc)

#     # Start and end points
#     ax.plot(COPx_raw_cm[0], COPy_raw_cm[0], 'go', markersize=8, label='Start')
#     ax.plot(COPx_raw_cm[-1], COPy_raw_cm[-1], 'ro', markersize=8, label='End')

#     # --- Mean COP position ---
#     mean_x = np.mean(COPx_raw_cm)
#     mean_y = np.mean(COPy_raw_cm)
#     ax.plot(mean_x, mean_y, marker='o', color='darkblue', markersize=8, label='Mean')

#     # Enclosing circle
#     circle = plt.Circle(cop_center, cop_radius, color='blue', fill=False, linestyle='--', label='Enclosing Circle')
#     ax.add_patch(circle)

#     # --- 95% Enclosing Circle (remove outliers) ---
#     center_mean = np.array([mean_x, mean_y])
#     cop_points = np.vstack((COPx_raw_cm, COPy_raw_cm)).T
#     distances = np.linalg.norm(cop_points - center_mean, axis=1)

#     # Get the 95th percentile distance and mask points
#     threshold = np.percentile(distances, 95)
#     core_points = cop_points[distances <= threshold]
#     ellipse_center = np.mean(core_points, axis=0)

#     # Get 95% enclosing circle
#     core_center, core_radius_sq = miniball.get_bounding_ball(core_points)
#     core_radius = np.sqrt(core_radius_sq)

#     # Plot 95% circle
#     circle_95 = plt.Circle(core_center, core_radius, color='black', fill=False, linestyle='-.', label=r'95% Enclosing Circle')
#     ax.add_patch(circle_95)

#     # --- 95% Confidence Ellipse ---
#     a, b, ellipse_area, ellipse_angle = compute_ellipse_metrics(core_points[:, 0], core_points[:, 1])

#     # --- Store all metrics (overwrite-safe and clean) ---
#     trajectory_info[safe_label] = {
#         "COPx": COPx_raw_cm,
#         "COPy": COPy_raw_cm,
#         "path": cop_path_length,
#         "radius": cop_radius,
#         "radius_95": core_radius,
#         "ellipse_center": ellipse_center.tolist(),
#         "ellipse_a": a,
#         "ellipse_b": b,
#         "ellipse_area": ellipse_area,
#         "ellipse_angle": ellipse_angle,
#         "touches": int(Foot_Touches) if Foot_Touches is not None else "None"
#     }

#    # Formatting
#     ax.set_aspect('equal')
#     ax.set_xlabel("ML COP (cm)")
#     ax.set_ylabel("AP COP (cm)")
#     ax.set_title(f"COP Trajectory - {condition}")
#     ax.grid(True)
#     ax.legend(loc='upper right')

#     # Capture current axis limits *after* plotting
#     xlims = ax.get_xlim()
#     ylims = ax.get_ylim()

#     # Add a 1 cm scale bar to the bottom right
#     # --- Fancy scale bar (1 cm) in data coordinates ---
#     scalebar_length_cm = 1.0

#     # Get axis limits
#     x_min, x_max = ax.get_xlim()
#     y_min, y_max = ax.get_ylim()

#     # Position of the scale bar
#     bar_padding_x = 0.05 * (x_max - x_min)
#     bar_padding_y = 0.05 * (y_max - y_min)
#     x_start = x_max - scalebar_length_cm - bar_padding_x
#     x_end = x_max - bar_padding_x
#     y_pos = y_min + bar_padding_y

#     # Draw horizontal bar
#     ax.plot([x_start, x_end], [y_pos, y_pos], 'k-', lw=2)

#     # Add vertical ticks
#     tick_height = 0.05 * (y_max - y_min)  # make them shorter
#     ax.plot([x_start, x_start], [y_pos - tick_height / 2, y_pos + tick_height / 2], 'k-', lw=2)
#     ax.plot([x_end, x_end], [y_pos - tick_height / 2, y_pos + tick_height / 2], 'k-', lw=2)

#     # Add label just above the bar
#     ax.text((x_start + x_end) / 2, y_pos + tick_height * 0.6, '1 cm',
#             ha='center', va='bottom', fontsize=9)
    
#     plt.tight_layout()
#     save_figure(fig, condition, "COP_Trajectory")
#     plt.show(block=False)
#     plt.pause(2)
#     plt.close(fig)

#     # Save trajectory image and metrics
#     buf = BytesIO()
#     fig.savefig(buf, format='png', dpi=600)
#     buf.seek(0)
#     safe_label = condition.replace(" - ", "_").replace(" ", "_")
#     temp_images[safe_label] = Image.open(buf)


#     # Plot Entropy Across Time Scales
#     fig = plt.figure(figsize=(8, 5))
#     plt.plot(mse_x, label='MSE - COPx (ML)')
#     plt.plot(mse_y, label='MSE - COPy (AP)')
#     plt.plot(mse_mag, label='MSE - COP Magnitude')
#     plt.plot(mmse_xy, label='MMSE - COPx & COPy', linestyle='--', marker='o')
#     plt.title(f"Entropy Across Time Scales - {condition}")
#     plt.xlabel("Scale")
#     plt.ylabel("Entropy")
#     plt.legend(loc='upper left')
#     plt.grid(True)
#     plt.tight_layout()
#     save_figure(fig, condition, "Entropy_Time_Scales")
#     label = condition.replace(" ", "").replace("-", "")
#     temp_images[label + "_Entropy"] = fig
#     plt.show(block=False)
#     plt.pause(2)
#     plt.close(fig)

#     # Entropy visual summaries
#     plot_entropy_summary(
#         sampen_x=samp_entropy_x,
#         sampen_y=samp_entropy_y,
#         sampen_mag=samp_entropy_mag,
#         mse_x=mse_x,
#         mse_y=mse_y,
#         mse_mag=mse_mag,
#         mmse=mmse_xy,
#         title_suffix=f" - {condition}"
#     )

#     plot_permutation_entropy_summary(
#         perm_x=perm_entropy_x,
#         perm_y=perm_entropy_y,
#         perm_mag=perm_entropy_COPmag,
#         title=f"Permutation Entropy - {condition}"
#     )

#     # Summary prints
#     print(f"COP Path Length:                {cop_path_length:.2f} cm")
#     print(f"Enclosing Circle Radius:        {cop_radius:.2f} cm")
#     print(f"Sample Entropy - COPx:          {samp_entropy_x:.2f}")
#     print(f"Sample Entropy - COPy:          {samp_entropy_y:.2f}")
#     print(f"Sample Entropy - COP magnitude: {samp_entropy_mag:.2f}")
#     print(f"Permutation Entropy - COPx:     {perm_entropy_x:.2f}")
#     print(f"Permutation Entropy - COPy:     {perm_entropy_y:.2f}")
#     print(f"Permutation Entropy - Mag:      {perm_entropy_COPmag:.2f}")
#     print(f"AUC - MSE COPx:                 {auc_x:.2f}")
#     print(f"AUC - MSE COPy:                 {auc_y:.2f}")
#     print(f"AUC - MSE COP magnitude:        {auc_mag:.2f}")
#     print(f"AUC - MMSE COPx & COPy:         {auc_mmse:.2f}")
#     if Foot_Touches is not None:
#         print(f"Contralateral Foot Touches:     {int(Foot_Touches)}")
#     else: 
#         print("Contralateral Foot Touches:     None")

#     # Store entropy values by condition
#     sample_entropy_data[condition] = {
#         'COPx (ML)': samp_entropy_x,
#         'COPy (AP)': samp_entropy_y,
#         'COP Magnitude': samp_entropy_mag
#     }
#     perm_entropy_data[condition] = {
#         'COPx (ML)': perm_entropy_x,
#         'COPy (AP)': perm_entropy_y,
#         'COP Magnitude': perm_entropy_COPmag
#     }

# # ---- Build tidy summary DataFrame ----
# summary_rows = []
# for condition in entropy_time_series_data:
#     metrics = entropy_time_series_data[condition]
#     traj = trajectory_info.get(condition, {})

#     row = {
#         "Condition": condition.replace("_", " "),
#         "Sample Entropy - COPx (ML)": metrics.get("sampen_x", np.nan),
#         "Sample Entropy - COPy (AP)": metrics.get("sampen_y", np.nan),
#         "Sample Entropy - COP Magnitude": metrics.get("sampen_mag", np.nan),
#         "Permutation Entropy - COPx (ML)": metrics.get("perm_x", np.nan),
#         "Permutation Entropy - COPy (AP)": metrics.get("perm_y", np.nan),
#         "Permutation Entropy - COP Magnitude": metrics.get("perm_mag", np.nan),
#         "AUC - MSE COPx (ML)": metrics.get("auc_x", np.nan),
#         "AUC - MSE COPy (AP)": metrics.get("auc_y", np.nan),
#         "AUC - MSE COP Magnitude": metrics.get("auc_mag", np.nan),
#         "AUC - MMSE": metrics.get("auc_mmse", np.nan),
#         "COP Path Length (cm)": traj.get("path", np.nan),
#         "COP Radius (cm)": traj.get("radius", np.nan),
#         "95% COP Radius (cm)": traj.get("radius_95",np.nan),
#         "# Opposite Foot Touches": traj.get("touches", np.nan),
#         "Ellipse Major Axis (cm)": traj.get("ellipse_a", np.nan),
#         "Ellipse Minor Axis (cm)": traj.get("ellipse_b", np.nan),
#         "Ellipse Area (cm^2)": traj.get("ellipse_area", np.nan),
#         "Ellipse Angle (deg)": traj.get("ellipse_angle", np.nan),
#     }

#     # Add scale-by-scale entropy (1–10)
#     for i in range(10):
#         row[f"MSE_COPx_Scale_{i+1}"] = metrics["mse_x"][i] if i < len(metrics["mse_x"]) else np.nan
#         row[f"MSE_COPy_Scale_{i+1}"] = metrics["mse_y"][i] if i < len(metrics["mse_y"]) else np.nan
#         row[f"MSE_COPmag_Scale_{i+1}"] = metrics["mse_mag"][i] if i < len(metrics["mse_mag"]) else np.nan
#         row[f"MMSE_Scale_{i+1}"] = metrics["mmse"][i] if i < len(metrics["mmse"]) else np.nan

#     summary_rows.append(row)

# entropy_summary_df = pd.DataFrame(summary_rows)
# entropy_summary_df.set_index("Condition", inplace=True)

# # ---- Export to Excel ----
# excel_path = os.path.join(save_folder, f"{subject_code}_Entropy_Summary.xlsx")
# entropy_summary_df.to_excel(excel_path)
# print(f"📁 Excel summary exported to: {excel_path}")

# # Plot sample entropy summary
# plot_entropy_bargraph(
#     sample_entropy_data,
#     title='Sample Entropy by Condition and COP Axis',
#     ylabel='Sample Entropy',
#     ylim=(0, 0.7),
#     thresholds=(0.2, 0.4, 0.7),
#     filename="Sample_Entropy_BarGraph"
# )

# # Plot permutation entropy summary
# plot_entropy_bargraph(
#     perm_entropy_data,
#     title='Permutation Entropy by Condition and COP Axis',
#     ylabel='Permutation Entropy',
#     ylim=(0, 1.0),
#     thresholds=(0.5, 0.75, 1.0),
#     filename="Permutation_Entropy_BarGraph"
# )

# # ---------------------- PDF REPORT: TRAJECTORY GRID ----------------------
# trajectory_order = [
#     "Eyes Open - Left",
#     "Eyes Open - Right",
#     "Eyes Closed - Left",
#     "Eyes Closed - Right"
# ]

# # Determine global axis limits for consistent subplot sizing
# all_copx = np.concatenate([info["COPx"] for info in trajectory_info.values()])
# all_copy = np.concatenate([info["COPy"] for info in trajectory_info.values()])
# x_min, x_max = np.min(all_copx), np.max(all_copx)
# y_min, y_max = np.min(all_copy), np.max(all_copy)

# # Plot trajectory grid
# pdf_path = os.path.join(save_folder, f"{subject_code}_SLB_COP_Results.pdf")
# with PdfPages(pdf_path) as pdf:
#     fig, axs = plt.subplots(2, 2, figsize=(8.5, 11), gridspec_kw={'width_ratios': [1, 1], 'height_ratios': [1, 1]})
#     plt.subplots_adjust(top=0.88, hspace=0.45, wspace=0.3)
#     for ax in axs.flat:
#         ax.set_box_aspect(1)  # Ensures each box is square


#     fig.suptitle("Single Leg Balance Center of Pressure", fontsize=16, y=0.95)
#     fig.text(0.5, 0.91, f"{subject_code}", fontsize=12, ha='center')
#     fig.text(0.5, 0.89, f"{study_date}", fontsize=10, ha='center')

#     # Load and add logo (place in top-right corner)
#     if logo_img is not None:
#         # Resize logo if needed
#         logo_ax = fig.add_axes([0.82, 0.91, 0.15, 0.08], anchor='NW', zorder=10)
#         logo_ax.imshow(logo_img)
#         logo_ax.axis('off')

#     # Precompute maximum radius for consistent limits
#     max_radius = max(info["radius"] for info in trajectory_info.values())

#     for ax, condition in zip(axs.flat, trajectory_order):
#         label = condition.replace(" - ", "_").replace(" ", "_")
#         info = trajectory_info[label]
#         copx = np.array(info["COPx"])
#         copy = np.array(info["COPy"])

#         # Shift everything so the circle center is (0, 0)
#         cop_center, _ = miniball.get_bounding_ball(np.vstack((copx, copy)).T)
#         copx -= cop_center[0]
#         copy -= cop_center[1]

#         # --- Plot COP trajectory ---
#         points = np.array([copx, copy]).T.reshape(-1, 1, 2)
#         segments = np.concatenate([points[:-1], points[1:]], axis=1)
#         cmap = ListedColormap(plt.cm.RdYlGn(np.linspace(1, 0, len(copx))))
#         norm = plt.Normalize(0, len(copx))
#         lc = LineCollection(segments, cmap=cmap, norm=norm)
#         lc.set_array(np.arange(len(copx)))
#         lc.set_linewidth(2)
#         ax.add_collection(lc)

#         # --- Start and end points ---
#         ax.plot(copx[0], copy[0], 'go', markersize=6, label='Start')
#         ax.plot(copx[-1], copy[-1], 'ro', markersize=6, label='End')

#         # --- Mean COP ---
#         mean_x = np.mean(copx)
#         mean_y = np.mean(copy)
#         ax.plot(mean_x, mean_y, marker='o', color='darkblue', markersize=8, label='Mean')

#         # --- Enclosing circle ---
#         cop_points = np.vstack((info["COPx"], info["COPy"])).T
#         cop_center, radius_squared = miniball.get_bounding_ball(cop_points)
#         cop_radius = np.sqrt(radius_squared)
#         circle = plt.Circle((0, 0), cop_radius, color='blue', fill=False, linestyle='--', label='Enclosing Circle')
#         ax.add_patch(circle)

#         # --- 95% Enclosing Circle (Black, Dashed-Dotted) ---
#         cop_points_shifted = np.vstack((copx, copy)).T  # already shifted
#         center_mean = np.mean(cop_points_shifted, axis=0)
#         dists = np.linalg.norm(cop_points_shifted - center_mean, axis=1)
#         threshold = np.percentile(dists, 95)
#         core_points = cop_points_shifted[dists <= threshold]

#         core_center, core_radius_sq = miniball.get_bounding_ball(core_points)
#         core_radius = np.sqrt(core_radius_sq)
#         circle_95 = plt.Circle(core_center, core_radius, edgecolor='black', linestyle='-.', linewidth=1.5, fill=False, label='95% Circle')
#         ax.add_patch(circle_95)

#         # Get ellipse info
#         a = info["ellipse_a"]
#         b = info["ellipse_b"]
#         angle = info["ellipse_angle"]
#         ellipse_center = np.array(info["ellipse_center"])
#         ellipse_center -= cop_center  # Apply the same shift used on COP data

#         ellipse_patch = patches.Ellipse(
#             xy=(ellipse_center[0], ellipse_center[1]),
#             width=a,
#             height=b,
#             angle=angle,
#             edgecolor='purple',
#             linestyle='--',
#             linewidth=1.5,
#             fill=False,
#             label='95% Ellipse'
#         )
#         ax.add_patch(ellipse_patch)

#         # Rotate reference: 0° = aligned with +Y (AP)
#         # Reported angle becomes deviation from vertical
#         adjusted_angle = (angle - 90) % 360  # shift so 0° is AP

#         # Convert to signed angle in range [-180, 180]
#         if adjusted_angle > 180:
#             adjusted_angle -= 360

#         # Flip for left side: internal tilt is positive
#         if "Left" in condition:
#             adjusted_angle = -adjusted_angle
#         trajectory_info[label]["adjusted_angle"] = adjusted_angle

#         # --- Formatting ---
#         ax.set_title(condition, fontsize=10)
#         ax.set_xlabel("ML COP (cm)")
#         ax.set_ylabel("AP COP (cm)")
#         ax.grid(True)

#         lim = np.ceil(max_radius + 0.1)
#         ax.set_xlim(-lim, lim)
#         ax.set_ylim(-lim, lim)

#         # Whole number tick marks and grid
#         ax.set_xticks(np.arange(-lim, lim + 1, 1))
#         ax.set_yticks(np.arange(-lim, lim + 1, 1))
#         ax.grid(True, which='both', linestyle='--', linewidth=0.5)

#         # Add legend centered between rows
#         handles, labels = axs[0, 0].get_legend_handles_labels()
#         fig.legend(handles, labels,
#                 loc='upper center',
#                 bbox_to_anchor=(0.51, 0.55),  # halfway-ish down the page
#                 fontsize=9,
#                 ncol=1,
#                 frameon=True)

#         # --- Descriptive text ---
#         ax.text(0.5, -0.15, f"COP Distance: {info['path']:.1f} cm",
#                 ha='center', va='top', transform=ax.transAxes, fontsize=8)
#         ax.text(0.5, -0.20, f"Radius: {info['radius']:.1f} cm",
#                 ha='center', va='top', transform=ax.transAxes, fontsize=8)
#         ax.text(0.5, -0.25, f"95% Radius: {core_radius:.1f} cm",
#                 ha='center', va='top', transform=ax.transAxes, fontsize=8)
#         ax.text(0.5, -0.30, f"# Opposite Foot Touches: {info['touches']}",
#                 ha='center', va='top', transform=ax.transAxes, fontsize=8)
#         ax.text(0.5, -0.35, f"Ellipse Area: {info['ellipse_area']:.1f} cm²",
#                 ha='center', va='top', transform=ax.transAxes, fontsize=8)
#         ax.text(0.5, -0.40, f"Ellipse Angle: {adjusted_angle:.1f}°",
#                 ha='center', va='top', transform=ax.transAxes, fontsize=8)
#         ax.text(0.5, -0.45, f"Ellipse Axes: {a:.1f}/{b:.1f} cm",
#                 ha='center', va='top', transform=ax.transAxes, fontsize=8)

#     pdf.savefig(fig)
#     # plt.close(fig)
#     # plt.show()
#     plt.show(block=False)
#     plt.pause(2)
#     plt.close(fig)

# print(f"✅Trajectory PDF saved to: {pdf_path}")

# # Plot entropy time series
# entropy_pdf_path = os.path.join(save_folder, f"{subject_code}_Entropy_Scale_Results.pdf")

# with PdfPages(entropy_pdf_path) as pdf:
#     fig, axs = plt.subplots(2, 2, figsize=(8.5, 11), gridspec_kw={'width_ratios': [1, 1], 'height_ratios': [1, 1]})
#     plt.subplots_adjust(top=0.88, hspace=0.4, wspace=0.3)

#     fig.suptitle("Entropy Across Balance Conditions", fontsize=16, y=0.95)
#     fig.text(0.5, 0.91, f"{subject_code}", fontsize=12, ha='center')
#     fig.text(0.5, 0.89, f"{study_date}", fontsize=10, ha='center')

#     if logo_img is not None:
#         logo_ax = fig.add_axes([0.82, 0.91, 0.15, 0.08], anchor='NW', zorder=10)
#         logo_ax.imshow(logo_img)
#         logo_ax.axis('off')

#     entropy_conditions = [
#         "Eyes Open - Left",
#         "Eyes Open - Right",
#         "Eyes Closed - Left",
#         "Eyes Closed - Right"
#     ]

#     # Determine global y-limits across all entropy data
#     all_entropy_vals = []
#     for entry in entropy_time_series_data.values():
#         all_entropy_vals.extend(entry["mse_x"])
#         all_entropy_vals.extend(entry["mse_y"])
#         all_entropy_vals.extend(entry["mse_mag"])
#         all_entropy_vals.extend(entry["mmse"])
#     y_min = 0
#     y_max = max(all_entropy_vals)
#     y_buffer = 0.1 * (y_max - y_min)
#     y_limits = (y_min, y_max + y_buffer)

#     for ax, condition in zip(axs.flat, entropy_conditions):
#         label = condition.replace(" - ", "_").replace(" ", "_")
#         entropy_data = entropy_time_series_data.get(label, None)

#         if entropy_data:
#             mse_x = entropy_data["mse_x"]
#             mse_y = entropy_data["mse_y"]
#             mse_mag = entropy_data["mse_mag"]
#             mmse_xy = entropy_data["mmse"]

#             scale_range = np.arange(1, len(mse_x) + 1)
#             ax.plot(scale_range, mse_x, label='MSE - COPx (ML)')
#             ax.plot(scale_range, mse_y, label='MSE - COPy (AP)')
#             ax.plot(scale_range, mse_mag, label='MSE - COP Magnitude')
#             ax.plot(scale_range, mmse_xy, label='MMSE - COPx & COPy', linestyle='--', marker='o')

#             ax.set_title(condition, fontsize=11)
#             ax.set_xlabel("Scale")
#             ax.set_ylabel("Entropy")
#             ax.grid(True)
#             ax.set_ylim(y_limits)
#             ax.set_ylim(bottom=0) 
#             ax.set_xlim(1,10)
#             ax.set_box_aspect(1)

#             # Add AUCs as a summary below each subplot
#             ax.text(0.5, -0.2,
#                     f"AUC - MSE COPx: {entropy_data['auc_x']:.2f}\n"
#                     f"AUC - MSE COPy: {entropy_data['auc_y']:.2f}\n"
#                     f"AUC - MSE Mag:   {entropy_data['auc_mag']:.2f}\n"
#                     f"AUC - MMSE:      {entropy_data['auc_mmse']:.2f}",
#                     transform=ax.transAxes,
#                     ha='center', va='top', fontsize=7, linespacing=1.2)

#         else:
#             ax.axis('off')
#             ax.text(0.5, 0.5, f"Missing data for {condition}", ha='center', va='center', fontsize=9)

#     # Add legend centered between rows
#     handles, labels = axs[0, 0].get_legend_handles_labels()
#     fig.legend(handles, labels,
#             loc='upper center',
#             bbox_to_anchor=(0.5, 0.52),  # halfway down the page
#             fontsize=9,
#             ncol=1,
#             frameon=True)

#     pdf.savefig(fig)
#     plt.show(block=False)
#     plt.pause(2)
#     plt.close(fig)

# print(f"✅ Entropy time series PDF saved to: {entropy_pdf_path}")

# # ------Plot entropy overlay-----
# overlay_pdf_path = os.path.join(save_folder, f"{subject_code}_Entropy_Overlay_Results.pdf")

# # Map from verbose condition names to safe dictionary keys
# label_map = {
#     "Eyes Open-Left": "Eyes_Open_Left",
#     "Eyes Open-Right": "Eyes_Open_Right",
#     "Eyes Closed-Left": "Eyes_Closed_Left",
#     "Eyes Closed-Right": "Eyes_Closed_Right"
# }

# with PdfPages(overlay_pdf_path) as pdf:
#     fig, axs = plt.subplots(2, 2, figsize=(8.5, 11))
#     plt.subplots_adjust(top=0.9, hspace=0.35, wspace=0.3)

#     fig.suptitle("Entropy Across Conditions", fontsize=16, y=0.95)
#     fig.text(0.5, 0.91, f"{subject_code}", fontsize=12, ha='center')
#     fig.text(0.5, 0.89, f"{study_date}", fontsize=10, ha='center')

#     if logo_img is not None:
#         logo_ax = fig.add_axes([0.82, 0.91, 0.15, 0.08], anchor='NW', zorder=10)
#         logo_ax.imshow(logo_img)
#         logo_ax.axis('off')

#     scale_range = np.arange(1, 11)

#     # Top-left: COPx MSE
#     ax = axs[0, 0]
#     for condition in entropy_conditions:
#         label = condition.replace(" - ", "_").replace(" ", "_")
#         color = "blue" if "Left" in condition else "red"
#         linestyle = "-" if "Eyes Open" in condition else "--"
#         ax.plot(scale_range, entropy_time_series_data[label]["mse_x"],
#                 color=color, linestyle=linestyle)

#     ax.set_title("MSE - COPx (ML)")
#     ax.set_xlabel("Scale")
#     ax.set_ylabel("Entropy")
#     ax.set_ylim(0, y_limits[1])
#     ax.set_xlim(1, 10)
#     ax.set_box_aspect(1)
#     ax.grid(True)

#     auc_text = get_overlay_auc_text(entropy_time_series_data, label_map, "auc_x")
#     ax.text(0.5, -0.20, auc_text, transform=ax.transAxes,
#             ha='center', va='top', fontsize=8, linespacing=1.2)

#     # Top-Right: COPy MSE
#     ax = axs[0, 1]
#     for condition in entropy_conditions:
#         label = condition.replace(" - ", "_").replace(" ", "_")
#         color = "blue" if "Left" in condition else "red"
#         linestyle = "-" if "Eyes Open" in condition else "--"
#         ax.plot(scale_range, entropy_time_series_data[label]["mse_y"],
#                 color=color, linestyle=linestyle)

#     ax.set_title("MSE - COPy (AP)")
#     ax.set_xlabel("Scale")
#     ax.set_ylabel("Entropy")
#     ax.set_ylim(0, y_limits[1])
#     ax.set_xlim(1, 10)
#     ax.set_box_aspect(1)
#     ax.grid(True)

#     auc_text = get_overlay_auc_text(entropy_time_series_data, label_map, "auc_y")
#     ax.text(0.5, -0.20, auc_text, transform=ax.transAxes,
#             ha='center', va='top', fontsize=8, linespacing=1.2)

#     # Bottom-left: COP magnitude MSE
#     ax = axs[1, 0]
#     for condition in entropy_conditions:
#         label = condition.replace(" - ", "_").replace(" ", "_")
#         color = "blue" if "Left" in condition else "red"
#         linestyle = "-" if "Eyes Open" in condition else "--"
#         ax.plot(scale_range, entropy_time_series_data[label]["mse_mag"],
#                 color=color, linestyle=linestyle)

#     ax.set_title("MSE - COP Magnitude")
#     ax.set_xlabel("Scale")
#     ax.set_ylabel("Entropy")
#     ax.set_ylim(0, y_limits[1])
#     ax.set_xlim(1, 10)
#     ax.set_box_aspect(1)
#     ax.grid(True)

#     auc_text = get_overlay_auc_text(entropy_time_series_data, label_map, "auc_mag")
#     ax.text(0.5, -0.20, auc_text, transform=ax.transAxes,
#             ha='center', va='top', fontsize=8, linespacing=1.2)

#     # Bottom-right: MMSE
#     ax = axs[1, 1]
#     for condition in entropy_conditions:
#         label = condition.replace(" - ", "_").replace(" ", "_")
#         color = "blue" if "Left" in condition else "red"
#         linestyle = "-" if "Eyes Open" in condition else "--"
#         ax.plot(scale_range, entropy_time_series_data[label]["mmse"],
#                 color=color, linestyle=linestyle)

#     ax.set_title("MMSE - COPx & COPy")
#     ax.set_xlabel("Scale")
#     ax.set_ylabel("Entropy")
#     ax.set_ylim(0, y_limits[1])
#     ax.set_xlim(1, 10)
#     ax.set_box_aspect(1)
#     ax.grid(True)

#     auc_text = get_overlay_auc_text(entropy_time_series_data, label_map, "auc_mmse")
#     ax.text(0.5, -0.20, auc_text, transform=ax.transAxes,
#             ha='center', va='top', fontsize=8, linespacing=1.2)

#     # Add one legend for the whole figure
#     legend_elements = [
#         Line2D([0], [0], color='blue', linestyle='-', label='Eyes Open - Left'),
#         Line2D([0], [0], color='red', linestyle='-', label='Eyes Open - Right'),
#         Line2D([0], [0], color='blue', linestyle='--', label='Eyes Closed - Left'),
#         Line2D([0], [0], color='red', linestyle='--', label='Eyes Closed - Right'),
#     ]
#     fig.legend(handles=legend_elements,
#            loc='upper center',
#            bbox_to_anchor=(0.5, 0.54),
#            fontsize=10,
#            ncol=1,
#            frameon=True)


#     pdf.savefig(fig)
#     plt.show(block=False)
#     plt.pause(2)
#     plt.close(fig)

# print(f"✅ Entropy overlay summary PDF saved to: {overlay_pdf_path}")

# # === Run excel exports ===
# export_cop_metrics_excel(trajectory_info, subject_code, save_folder)
# export_entropy_metrics_excel(entropy_time_series_data, subject_code, save_folder)

def preflight_fields(context=None):
    """Inputs choosable before processing starts (see analysis_registry.py)."""
    return [
        {"key": "cop_folder", "label": "Folder containing COP text files", "type": "dir", "default": ""},
    ]


def main(context=None, inputs=None):
    from analysis_registry import make_run_result, default_output_dir

        # ---------------------- FILE SELECTION ----------------------
    logo_img = load_logo()
    root = tk.Tk()
    root.withdraw()
    if inputs is not None:
        folder_selected = inputs.get("cop_folder", "")
    else:
        folder_selected = filedialog.askdirectory(title="Select Folder Containing COP Text Files")
    print("\n📂 Selected Folder:", folder_selected)
    if not folder_selected:
        return make_run_result("cancelled") if context is not None else None

    files = find_condition_files(folder_selected, EXPECTED_SUFFIXES)

    if context is not None:
        subject_code = context.file_stub
        study_date = context.visit_date
    else:
        subject_code, study_date = get_subject_info()
    print(f"\n🧾 Subject Study Code: {subject_code}")
    print(f"📅 Date of Study: {study_date}")

    if context is not None:
        save_folder = str(default_output_dir(context.visit_dir, "slb_cop_entropy", visit_type=context.visit_type))
    else:
        save_folder = filedialog.askdirectory(title="Select Folder to Save Results")
        if not save_folder:
            return None
    os.makedirs(save_folder, exist_ok=True)
    print(f"💾 Results will be saved to: {save_folder}")

    # ---------------------- TEMP IMAGE BUFFER FOR PDF ----------------------
    temp_images = {}
    trajectory_info = {}
    entropy_time_series_data = {}

    # ---------------------- CREATE CODE FOLDER AND SAVE SCRIPT ----------------------
    code_dir = os.path.join(folder_selected, "Code")
    os.makedirs(code_dir, exist_ok=True)

    try:
        current_script_path = inspect.getframeinfo(inspect.currentframe()).filename
        script_filename = os.path.basename(current_script_path)
        save_path = os.path.join(code_dir, script_filename)
        shutil.copy2(current_script_path, save_path)
        print(f"🧾 Code copied to: {save_path}")
    except Exception as e:
        print(f"❌ Failed to copy code: {e}")

        # ---------------------- CREATE FIGURE SAVE DIRECTORY ----------------------
    figure_dir = os.path.join(save_folder, "SLB_Figures")
    os.makedirs(figure_dir, exist_ok=True)
    
    sample_entropy_data = {'COPx (ML)': [], 'COPy (AP)': [], 'COP Magnitude': []}
    perm_entropy_data = {'COPx (ML)': [], 'COPy (AP)': [], 'COP Magnitude': []}
        
    for condition, file_path in tqdm(files.items(), desc="Processing COP trials", unit="trial"):
        print(f"\n----- Processing: {condition} -----")

        # Load data
        data = pd.read_csv(file_path, sep='\t', skiprows=4)

        Fx = data.iloc[:, 16].values
        Fy = data.iloc[:, 17].values
        Fz = (data.iloc[:, 18].values) * -1
        Mx = data.iloc[:, 19].values
        My = (data.iloc[:, 20].values) * -1
        Mz = data.iloc[:, 21].values
        Foot_Touches = None
        if data.shape[1] > 22:
            Foot_Touches = data.iloc[0, 22] # Foot_Touches is stored as a single cell value (int) in column 23, or left blank for 0

        # Calculate COP
        h = 0
        COPx = (-My - Fx * h) / Fz
        COPy = (Mx - Fy * h) / Fz
        valid = np.isfinite(COPx) & np.isfinite(COPy)
        COPx = COPx[valid]
        COPy = COPy[valid]

        # Save raw decimated COP for radius/path metrics
        COPx_raw = decimate(COPx, 10)
        COPy_raw = decimate(COPy, 10)
        # Convert to cm for plotting and distance metrics
        COPx_raw_cm = COPx_raw * 100
        COPy_raw_cm = COPy_raw * 100

        # Normalize for entropy analysis
        COPx_ds = (COPx_raw - np.mean(COPx_raw)) / np.std(COPx_raw)
        COPy_ds = (COPy_raw - np.mean(COPy_raw)) / np.std(COPy_raw)

        # COP magnitude
        COPmag = np.sqrt(COPx_ds**2 + COPy_ds**2)
        COPmag -= np.mean(COPmag)
        COPmag /= np.std(COPmag)

        # Entropies
        samp_entropy_x = sample_entropy(COPx_ds)
        samp_entropy_y = sample_entropy(COPy_ds)
        samp_entropy_mag = sample_entropy(COPmag)

        perm_entropy_x = compute_perm_entropy(COPx_ds, normalize=True)
        perm_entropy_y = compute_perm_entropy(COPy_ds, normalize=True)
        perm_entropy_COPmag = compute_perm_entropy(COPmag, normalize=True)

        mse_x = compute_multiscale_entropy(COPx_ds)
        mse_y = compute_multiscale_entropy(COPy_ds)
        mse_mag = compute_multiscale_entropy(COPmag)
        mmse_xy = mmse(COPx_ds, COPy_ds, max_scale=10)

        auc_x = auc(np.arange(1, len(mse_x) + 1), mse_x)
        auc_y = auc(np.arange(1, len(mse_y) + 1), mse_y)
        auc_mag = auc(np.arange(1, len(mse_mag) + 1), mse_mag)
        auc_mmse = auc(np.arange(1, len(mmse_xy) + 1), mmse_xy)

        safe_label = condition.replace(" - ", "_").replace(" ", "_")
        entropy_time_series_data[safe_label] = {
        "mse_x": mse_x,
        "mse_y": mse_y,
        "mse_mag": mse_mag,
        "mmse": mmse_xy,
        "sampen_x": samp_entropy_x,
        "sampen_y": samp_entropy_y,
        "sampen_mag": samp_entropy_mag,
        "perm_x": perm_entropy_x,
        "perm_y": perm_entropy_y,
        "perm_mag": perm_entropy_COPmag,  
        "auc_x": auc_x,
        "auc_y": auc_y,
        "auc_mag": auc_mag,
        "auc_mmse": auc_mmse
        }

        # COP Path & Radius
        cop_distances = np.sqrt(np.diff(COPx_raw)**2 + np.diff(COPy_raw)**2)
        cop_path_length = np.sum(cop_distances) * 100 # Convert to cm
        cop_points = np.vstack((COPx_raw_cm, COPy_raw_cm)).T
        cop_center, radius_squared = miniball.get_bounding_ball(cop_points)
        cop_radius = np.sqrt(radius_squared)

        # --- 95% Enclosing Circle (remove outliers) ---
        mean_x = np.mean(COPx_raw_cm)
        mean_y = np.mean(COPy_raw_cm)
        center_mean = np.array([mean_x, mean_y])
        distances = np.linalg.norm(cop_points - center_mean, axis=1)

        threshold = np.percentile(distances, 95)
        core_points = cop_points[distances <= threshold]
        core_center, core_radius_sq = miniball.get_bounding_ball(core_points)
        core_radius = np.sqrt(core_radius_sq)

        # COP Trajectory Plot (raw data in meters)
        fig, ax = plt.subplots(figsize=(6, 6))
        points = np.array([COPx_raw_cm, COPy_raw_cm]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        cmap = ListedColormap(plt.cm.RdYlGn(np.linspace(1, 0, len(COPx_raw))))
        norm = plt.Normalize(0, len(COPx_raw))
        lc = LineCollection(segments, cmap=cmap, norm=norm)
        lc.set_array(np.arange(len(COPx_raw)))
        lc.set_linewidth(2)
        ax.add_collection(lc)

        # Start and end points
        ax.plot(COPx_raw_cm[0], COPy_raw_cm[0], 'go', markersize=8, label='Start')
        ax.plot(COPx_raw_cm[-1], COPy_raw_cm[-1], 'ro', markersize=8, label='End')

        # --- Mean COP position ---
        mean_x = np.mean(COPx_raw_cm)
        mean_y = np.mean(COPy_raw_cm)
        ax.plot(mean_x, mean_y, marker='o', color='darkblue', markersize=8, label='Mean')

        # Enclosing circle
        circle = plt.Circle(cop_center, cop_radius, color='blue', fill=False, linestyle='--', label='Enclosing Circle')
        ax.add_patch(circle)

        # --- 95% Enclosing Circle (remove outliers) ---
        center_mean = np.array([mean_x, mean_y])
        cop_points = np.vstack((COPx_raw_cm, COPy_raw_cm)).T
        distances = np.linalg.norm(cop_points - center_mean, axis=1)

        # Get the 95th percentile distance and mask points
        threshold = np.percentile(distances, 95)
        core_points = cop_points[distances <= threshold]
        ellipse_center = np.mean(core_points, axis=0)

        # Get 95% enclosing circle
        core_center, core_radius_sq = miniball.get_bounding_ball(core_points)
        core_radius = np.sqrt(core_radius_sq)

        # Plot 95% circle
        circle_95 = plt.Circle(core_center, core_radius, color='black', fill=False, linestyle='-.', label=r'95% Enclosing Circle')
        ax.add_patch(circle_95)

        # --- 95% Confidence Ellipse ---
        a, b, ellipse_area, ellipse_angle = compute_ellipse_metrics(core_points[:, 0], core_points[:, 1])

        # --- Store all metrics (overwrite-safe and clean) ---
        trajectory_info[safe_label] = {
            "COPx": COPx_raw_cm,
            "COPy": COPy_raw_cm,
            "path": cop_path_length,
            "radius": cop_radius,
            "radius_95": core_radius,
            "ellipse_center": ellipse_center.tolist(),
            "ellipse_a": a,
            "ellipse_b": b,
            "ellipse_area": ellipse_area,
            "ellipse_angle": ellipse_angle,
            "touches": int(Foot_Touches) if Foot_Touches is not None else "None"
        }

    # Formatting
        ax.set_aspect('equal')
        ax.set_xlabel("ML COP (cm)")
        ax.set_ylabel("AP COP (cm)")
        ax.set_title(f"COP Trajectory - {condition}")
        ax.grid(True)
        ax.legend(loc='upper right')

        # Capture current axis limits *after* plotting
        xlims = ax.get_xlim()
        ylims = ax.get_ylim()

        # Add a 1 cm scale bar to the bottom right
        # --- Fancy scale bar (1 cm) in data coordinates ---
        scalebar_length_cm = 1.0

        # Get axis limits
        x_min, x_max = ax.get_xlim()
        y_min, y_max = ax.get_ylim()

        # Position of the scale bar
        bar_padding_x = 0.05 * (x_max - x_min)
        bar_padding_y = 0.05 * (y_max - y_min)
        x_start = x_max - scalebar_length_cm - bar_padding_x
        x_end = x_max - bar_padding_x
        y_pos = y_min + bar_padding_y

        # Draw horizontal bar
        ax.plot([x_start, x_end], [y_pos, y_pos], 'k-', lw=2)

        # Add vertical ticks
        tick_height = 0.05 * (y_max - y_min)  # make them shorter
        ax.plot([x_start, x_start], [y_pos - tick_height / 2, y_pos + tick_height / 2], 'k-', lw=2)
        ax.plot([x_end, x_end], [y_pos - tick_height / 2, y_pos + tick_height / 2], 'k-', lw=2)

        # Add label just above the bar
        ax.text((x_start + x_end) / 2, y_pos + tick_height * 0.6, '1 cm',
                ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
        save_figure(fig, condition, "COP_Trajectory")
        plt.show(block=False)
        plt.pause(2)
        plt.close(fig)

        # Save trajectory image and metrics
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=600)
        buf.seek(0)
        safe_label = condition.replace(" - ", "_").replace(" ", "_")
        temp_images[safe_label] = Image.open(buf)


        # Plot Entropy Across Time Scales
        fig = plt.figure(figsize=(8, 5))
        plt.plot(mse_x, label='MSE - COPx (ML)')
        plt.plot(mse_y, label='MSE - COPy (AP)')
        plt.plot(mse_mag, label='MSE - COP Magnitude')
        plt.plot(mmse_xy, label='MMSE - COPx & COPy', linestyle='--', marker='o')
        plt.title(f"Entropy Across Time Scales - {condition}")
        plt.xlabel("Scale")
        plt.ylabel("Entropy")
        plt.legend(loc='upper left')
        plt.grid(True)
        plt.tight_layout()
        save_figure(fig, condition, "Entropy_Time_Scales")
        label = condition.replace(" ", "").replace("-", "")
        temp_images[label + "_Entropy"] = fig
        plt.show(block=False)
        plt.pause(2)
        plt.close(fig)

        # Entropy visual summaries
        plot_entropy_summary(
            sampen_x=samp_entropy_x,
            sampen_y=samp_entropy_y,
            sampen_mag=samp_entropy_mag,
            mse_x=mse_x,
            mse_y=mse_y,
            mse_mag=mse_mag,
            mmse=mmse_xy,
            title_suffix=f" - {condition}"
        )

        plot_permutation_entropy_summary(
            perm_x=perm_entropy_x,
            perm_y=perm_entropy_y,
            perm_mag=perm_entropy_COPmag,
            title=f"Permutation Entropy - {condition}"
        )

        # Summary prints
        print(f"COP Path Length:                {cop_path_length:.2f} cm")
        print(f"Enclosing Circle Radius:        {cop_radius:.2f} cm")
        print(f"Sample Entropy - COPx:          {samp_entropy_x:.2f}")
        print(f"Sample Entropy - COPy:          {samp_entropy_y:.2f}")
        print(f"Sample Entropy - COP magnitude: {samp_entropy_mag:.2f}")
        print(f"Permutation Entropy - COPx:     {perm_entropy_x:.2f}")
        print(f"Permutation Entropy - COPy:     {perm_entropy_y:.2f}")
        print(f"Permutation Entropy - Mag:      {perm_entropy_COPmag:.2f}")
        print(f"AUC - MSE COPx:                 {auc_x:.2f}")
        print(f"AUC - MSE COPy:                 {auc_y:.2f}")
        print(f"AUC - MSE COP magnitude:        {auc_mag:.2f}")
        print(f"AUC - MMSE COPx & COPy:         {auc_mmse:.2f}")
        if Foot_Touches is not None:
            print(f"Contralateral Foot Touches:     {int(Foot_Touches)}")
        else: 
            print("Contralateral Foot Touches:     None")

        # Store entropy values by condition
        sample_entropy_data[condition] = {
            'COPx (ML)': samp_entropy_x,
            'COPy (AP)': samp_entropy_y,
            'COP Magnitude': samp_entropy_mag
        }
        perm_entropy_data[condition] = {
            'COPx (ML)': perm_entropy_x,
            'COPy (AP)': perm_entropy_y,
            'COP Magnitude': perm_entropy_COPmag
    }   

    # ---- Build tidy summary DataFrame ----
    summary_rows = []
    for condition in entropy_time_series_data:
        metrics = entropy_time_series_data[condition]
        traj = trajectory_info.get(condition, {})

        row = {
            "Condition": condition.replace("_", " "),
            "Sample Entropy - COPx (ML)": metrics.get("sampen_x", np.nan),
            "Sample Entropy - COPy (AP)": metrics.get("sampen_y", np.nan),
            "Sample Entropy - COP Magnitude": metrics.get("sampen_mag", np.nan),
            "Permutation Entropy - COPx (ML)": metrics.get("perm_x", np.nan),
            "Permutation Entropy - COPy (AP)": metrics.get("perm_y", np.nan),
            "Permutation Entropy - COP Magnitude": metrics.get("perm_mag", np.nan),
            "AUC - MSE COPx (ML)": metrics.get("auc_x", np.nan),
            "AUC - MSE COPy (AP)": metrics.get("auc_y", np.nan),
            "AUC - MSE COP Magnitude": metrics.get("auc_mag", np.nan),
            "AUC - MMSE": metrics.get("auc_mmse", np.nan),
            "COP Path Length (cm)": traj.get("path", np.nan),
            "COP Radius (cm)": traj.get("radius", np.nan),
            "95% COP Radius (cm)": traj.get("radius_95",np.nan),
            "# Opposite Foot Touches": traj.get("touches", np.nan),
            "Ellipse Major Axis (cm)": traj.get("ellipse_a", np.nan),
            "Ellipse Minor Axis (cm)": traj.get("ellipse_b", np.nan),
            "Ellipse Area (cm^2)": traj.get("ellipse_area", np.nan),
            "Ellipse Angle (deg)": traj.get("ellipse_angle", np.nan),
        }

        # Add scale-by-scale entropy (1–10)
        for i in range(10):
            row[f"MSE_COPx_Scale_{i+1}"] = metrics["mse_x"][i] if i < len(metrics["mse_x"]) else np.nan
            row[f"MSE_COPy_Scale_{i+1}"] = metrics["mse_y"][i] if i < len(metrics["mse_y"]) else np.nan
            row[f"MSE_COPmag_Scale_{i+1}"] = metrics["mse_mag"][i] if i < len(metrics["mse_mag"]) else np.nan
            row[f"MMSE_Scale_{i+1}"] = metrics["mmse"][i] if i < len(metrics["mmse"]) else np.nan

        summary_rows.append(row)

    entropy_summary_df = pd.DataFrame(summary_rows)
    entropy_summary_df.set_index("Condition", inplace=True)

    # ---- Export to Excel ----
    excel_path = os.path.join(save_folder, f"{subject_code}_Entropy_Summary.xlsx")
    entropy_summary_df.to_excel(excel_path)
    print(f"📁 Excel summary exported to: {excel_path}")

    # Plot sample entropy summary
    plot_entropy_bargraph(
        sample_entropy_data,
        title='Sample Entropy by Condition and COP Axis',
        ylabel='Sample Entropy',
        ylim=(0, 0.7),
        thresholds=(0.2, 0.4, 0.7),
        filename="Sample_Entropy_BarGraph"
    )

    # Plot permutation entropy summary
    plot_entropy_bargraph(
        perm_entropy_data,
        title='Permutation Entropy by Condition and COP Axis',
        ylabel='Permutation Entropy',
        ylim=(0, 1.0),
        thresholds=(0.5, 0.75, 1.0),
        filename="Permutation_Entropy_BarGraph"
    )

    # ---------------------- PDF REPORT: TRAJECTORY GRID ----------------------
    trajectory_order = [
        "Eyes Open - Left",
        "Eyes Open - Right",
        "Eyes Closed - Left",
        "Eyes Closed - Right"
    ]

    # Determine global axis limits for consistent subplot sizing
    all_copx = np.concatenate([info["COPx"] for info in trajectory_info.values()])
    all_copy = np.concatenate([info["COPy"] for info in trajectory_info.values()])
    x_min, x_max = np.min(all_copx), np.max(all_copx)
    y_min, y_max = np.min(all_copy), np.max(all_copy)

    # Plot trajectory grid
    pdf_path = os.path.join(save_folder, f"{subject_code}_SLB_COP_Results.pdf")
    with PdfPages(pdf_path) as pdf:
        fig, axs = plt.subplots(2, 2, figsize=(8.5, 11), gridspec_kw={'width_ratios': [1, 1], 'height_ratios': [1, 1]})
        plt.subplots_adjust(top=0.88, hspace=0.45, wspace=0.3)
        for ax in axs.flat:
            ax.set_box_aspect(1)  # Ensures each box is square


        fig.suptitle("Single Leg Balance Center of Pressure", fontsize=16, y=0.95)
        fig.text(0.5, 0.91, f"{subject_code}", fontsize=12, ha='center')
        fig.text(0.5, 0.89, f"{study_date}", fontsize=10, ha='center')

        # Load and add logo (place in top-right corner)
        if logo_img is not None:
            # Resize logo if needed
            logo_ax = fig.add_axes([0.82, 0.91, 0.15, 0.08], anchor='NW', zorder=10)
            logo_ax.imshow(logo_img)
            logo_ax.axis('off')

        # Precompute maximum radius for consistent limits
        max_radius = max(info["radius"] for info in trajectory_info.values())

        for ax, condition in zip(axs.flat, trajectory_order):
            label = condition.replace(" - ", "_").replace(" ", "_")
            info = trajectory_info[label]
            copx = np.array(info["COPx"])
            copy = np.array(info["COPy"])

            # Shift everything so the circle center is (0, 0)
            cop_center, _ = miniball.get_bounding_ball(np.vstack((copx, copy)).T)
            copx -= cop_center[0]
            copy -= cop_center[1]

            # --- Plot COP trajectory ---
            points = np.array([copx, copy]).T.reshape(-1, 1, 2)
            segments = np.concatenate([points[:-1], points[1:]], axis=1)
            cmap = ListedColormap(plt.cm.RdYlGn(np.linspace(1, 0, len(copx))))
            norm = plt.Normalize(0, len(copx))
            lc = LineCollection(segments, cmap=cmap, norm=norm)
            lc.set_array(np.arange(len(copx)))
            lc.set_linewidth(2)
            ax.add_collection(lc)

            # --- Start and end points ---
            ax.plot(copx[0], copy[0], 'go', markersize=6, label='Start')
            ax.plot(copx[-1], copy[-1], 'ro', markersize=6, label='End')

            # --- Mean COP ---
            mean_x = np.mean(copx)
            mean_y = np.mean(copy)
            ax.plot(mean_x, mean_y, marker='o', color='darkblue', markersize=8, label='Mean')

            # --- Enclosing circle ---
            cop_points = np.vstack((info["COPx"], info["COPy"])).T
            cop_center, radius_squared = miniball.get_bounding_ball(cop_points)
            cop_radius = np.sqrt(radius_squared)
            circle = plt.Circle((0, 0), cop_radius, color='blue', fill=False, linestyle='--', label='Enclosing Circle')
            ax.add_patch(circle)

            # --- 95% Enclosing Circle (Black, Dashed-Dotted) ---
            cop_points_shifted = np.vstack((copx, copy)).T  # already shifted
            center_mean = np.mean(cop_points_shifted, axis=0)
            dists = np.linalg.norm(cop_points_shifted - center_mean, axis=1)
            threshold = np.percentile(dists, 95)
            core_points = cop_points_shifted[dists <= threshold]

            core_center, core_radius_sq = miniball.get_bounding_ball(core_points)
            core_radius = np.sqrt(core_radius_sq)
            circle_95 = plt.Circle(core_center, core_radius, edgecolor='black', linestyle='-.', linewidth=1.5, fill=False, label='95% Circle')
            ax.add_patch(circle_95)

            # Get ellipse info
            a = info["ellipse_a"]
            b = info["ellipse_b"]
            angle = info["ellipse_angle"]
            ellipse_center = np.array(info["ellipse_center"])
            ellipse_center -= cop_center  # Apply the same shift used on COP data

            ellipse_patch = patches.Ellipse(
                xy=(ellipse_center[0], ellipse_center[1]),
                width=a,
                height=b,
                angle=angle,
                edgecolor='purple',
                linestyle='--',
                linewidth=1.5,
                fill=False,
                label='95% Ellipse'
            )
            ax.add_patch(ellipse_patch)

            # Rotate reference: 0° = aligned with +Y (AP)
            # Reported angle becomes deviation from vertical
            adjusted_angle = (angle - 90) % 360  # shift so 0° is AP

            # Convert to signed angle in range [-180, 180]
            if adjusted_angle > 180:
                adjusted_angle -= 360

            # Flip for left side: internal tilt is positive
            if "Left" in condition:
                adjusted_angle = -adjusted_angle
            trajectory_info[label]["adjusted_angle"] = adjusted_angle

            # --- Formatting ---
            ax.set_title(condition, fontsize=10)
            ax.set_xlabel("ML COP (cm)")
            ax.set_ylabel("AP COP (cm)")
            ax.grid(True)

            lim = np.ceil(max_radius + 0.1)
            ax.set_xlim(-lim, lim)
            ax.set_ylim(-lim, lim)

            # Whole number tick marks and grid
            ax.set_xticks(np.arange(-lim, lim + 1, 1))
            ax.set_yticks(np.arange(-lim, lim + 1, 1))
            ax.grid(True, which='both', linestyle='--', linewidth=0.5)

            # Add legend centered between rows
            handles, labels = axs[0, 0].get_legend_handles_labels()
            fig.legend(handles, labels,
                    loc='upper center',
                    bbox_to_anchor=(0.51, 0.55),  # halfway-ish down the page
                    fontsize=9,
                    ncol=1,
                    frameon=True)

            # --- Descriptive text ---
            ax.text(0.5, -0.15, f"COP Distance: {info['path']:.1f} cm",
                    ha='center', va='top', transform=ax.transAxes, fontsize=8)
            ax.text(0.5, -0.20, f"Radius: {info['radius']:.1f} cm",
                    ha='center', va='top', transform=ax.transAxes, fontsize=8)
            ax.text(0.5, -0.25, f"95% Radius: {core_radius:.1f} cm",
                    ha='center', va='top', transform=ax.transAxes, fontsize=8)
            ax.text(0.5, -0.30, f"# Opposite Foot Touches: {info['touches']}",
                    ha='center', va='top', transform=ax.transAxes, fontsize=8)
            ax.text(0.5, -0.35, f"Ellipse Area: {info['ellipse_area']:.1f} cm²",
                    ha='center', va='top', transform=ax.transAxes, fontsize=8)
            ax.text(0.5, -0.40, f"Ellipse Angle: {adjusted_angle:.1f}°",
                    ha='center', va='top', transform=ax.transAxes, fontsize=8)
            ax.text(0.5, -0.45, f"Ellipse Axes: {a:.1f}/{b:.1f} cm",
                    ha='center', va='top', transform=ax.transAxes, fontsize=8)

        pdf.savefig(fig)
        # plt.close(fig)
        # plt.show()
        plt.show(block=False)
        plt.pause(2)
        plt.close(fig)

    print(f"✅Trajectory PDF saved to: {pdf_path}")

    # Plot entropy time series
    entropy_pdf_path = os.path.join(save_folder, f"{subject_code}_Entropy_Scale_Results.pdf")

    with PdfPages(entropy_pdf_path) as pdf:
        fig, axs = plt.subplots(2, 2, figsize=(8.5, 11), gridspec_kw={'width_ratios': [1, 1], 'height_ratios': [1, 1]})
        plt.subplots_adjust(top=0.88, hspace=0.4, wspace=0.3)

        fig.suptitle("Entropy Across Balance Conditions", fontsize=16, y=0.95)
        fig.text(0.5, 0.91, f"{subject_code}", fontsize=12, ha='center')
        fig.text(0.5, 0.89, f"{study_date}", fontsize=10, ha='center')

        if logo_img is not None:
            logo_ax = fig.add_axes([0.82, 0.91, 0.15, 0.08], anchor='NW', zorder=10)
            logo_ax.imshow(logo_img)
            logo_ax.axis('off')

        entropy_conditions = [
            "Eyes Open - Left",
            "Eyes Open - Right",
            "Eyes Closed - Left",
            "Eyes Closed - Right"
        ]

        # Determine global y-limits across all entropy data
        all_entropy_vals = []
        for entry in entropy_time_series_data.values():
            all_entropy_vals.extend(entry["mse_x"])
            all_entropy_vals.extend(entry["mse_y"])
            all_entropy_vals.extend(entry["mse_mag"])
            all_entropy_vals.extend(entry["mmse"])
        y_min = 0
        y_max = max(all_entropy_vals)
        y_buffer = 0.1 * (y_max - y_min)
        y_limits = (y_min, y_max + y_buffer)

        for ax, condition in zip(axs.flat, entropy_conditions):
            label = condition.replace(" - ", "_").replace(" ", "_")
            entropy_data = entropy_time_series_data.get(label, None)

            if entropy_data:
                mse_x = entropy_data["mse_x"]
                mse_y = entropy_data["mse_y"]
                mse_mag = entropy_data["mse_mag"]
                mmse_xy = entropy_data["mmse"]

                scale_range = np.arange(1, len(mse_x) + 1)
                ax.plot(scale_range, mse_x, label='MSE - COPx (ML)')
                ax.plot(scale_range, mse_y, label='MSE - COPy (AP)')
                ax.plot(scale_range, mse_mag, label='MSE - COP Magnitude')
                ax.plot(scale_range, mmse_xy, label='MMSE - COPx & COPy', linestyle='--', marker='o')

                ax.set_title(condition, fontsize=11)
                ax.set_xlabel("Scale")
                ax.set_ylabel("Entropy")
                ax.grid(True)
                ax.set_ylim(y_limits)
                ax.set_ylim(bottom=0) 
                ax.set_xlim(1,10)
                ax.set_box_aspect(1)

                # Add AUCs as a summary below each subplot
                ax.text(0.5, -0.2,
                        f"AUC - MSE COPx: {entropy_data['auc_x']:.2f}\n"
                        f"AUC - MSE COPy: {entropy_data['auc_y']:.2f}\n"
                        f"AUC - MSE Mag:   {entropy_data['auc_mag']:.2f}\n"
                        f"AUC - MMSE:      {entropy_data['auc_mmse']:.2f}",
                        transform=ax.transAxes,
                        ha='center', va='top', fontsize=7, linespacing=1.2)

            else:
                ax.axis('off')
                ax.text(0.5, 0.5, f"Missing data for {condition}", ha='center', va='center', fontsize=9)

        # Add legend centered between rows
        handles, labels = axs[0, 0].get_legend_handles_labels()
        fig.legend(handles, labels,
                loc='upper center',
                bbox_to_anchor=(0.5, 0.52),  # halfway down the page
                fontsize=9,
                ncol=1,
                frameon=True)

        pdf.savefig(fig)
        plt.show(block=False)
        plt.pause(2)
        plt.close(fig)

    print(f"✅ Entropy time series PDF saved to: {entropy_pdf_path}")

    # ------Plot entropy overlay-----
    overlay_pdf_path = os.path.join(save_folder, f"{subject_code}_Entropy_Overlay_Results.pdf")

    # Map from verbose condition names to safe dictionary keys
    label_map = {
        "Eyes Open-Left": "Eyes_Open_Left",
        "Eyes Open-Right": "Eyes_Open_Right",
        "Eyes Closed-Left": "Eyes_Closed_Left",
        "Eyes Closed-Right": "Eyes_Closed_Right"
    }

    with PdfPages(overlay_pdf_path) as pdf:
        fig, axs = plt.subplots(2, 2, figsize=(8.5, 11))
        plt.subplots_adjust(top=0.9, hspace=0.35, wspace=0.3)

        fig.suptitle("Entropy Across Conditions", fontsize=16, y=0.95)
        fig.text(0.5, 0.91, f"{subject_code}", fontsize=12, ha='center')
        fig.text(0.5, 0.89, f"{study_date}", fontsize=10, ha='center')

        if logo_img is not None:
            logo_ax = fig.add_axes([0.82, 0.91, 0.15, 0.08], anchor='NW', zorder=10)
            logo_ax.imshow(logo_img)
            logo_ax.axis('off')

        scale_range = np.arange(1, 11)

        # Top-left: COPx MSE
        ax = axs[0, 0]
        for condition in entropy_conditions:
            label = condition.replace(" - ", "_").replace(" ", "_")
            color = "blue" if "Left" in condition else "red"
            linestyle = "-" if "Eyes Open" in condition else "--"
            ax.plot(scale_range, entropy_time_series_data[label]["mse_x"],
                    color=color, linestyle=linestyle)

        ax.set_title("MSE - COPx (ML)")
        ax.set_xlabel("Scale")
        ax.set_ylabel("Entropy")
        ax.set_ylim(0, y_limits[1])
        ax.set_xlim(1, 10)
        ax.set_box_aspect(1)
        ax.grid(True)

        auc_text = get_overlay_auc_text(entropy_time_series_data, label_map, "auc_x")
        ax.text(0.5, -0.20, auc_text, transform=ax.transAxes,
                ha='center', va='top', fontsize=8, linespacing=1.2)

        # Top-Right: COPy MSE
        ax = axs[0, 1]
        for condition in entropy_conditions:
            label = condition.replace(" - ", "_").replace(" ", "_")
            color = "blue" if "Left" in condition else "red"
            linestyle = "-" if "Eyes Open" in condition else "--"
            ax.plot(scale_range, entropy_time_series_data[label]["mse_y"],
                    color=color, linestyle=linestyle)

        ax.set_title("MSE - COPy (AP)")
        ax.set_xlabel("Scale")
        ax.set_ylabel("Entropy")
        ax.set_ylim(0, y_limits[1])
        ax.set_xlim(1, 10)
        ax.set_box_aspect(1)
        ax.grid(True)

        auc_text = get_overlay_auc_text(entropy_time_series_data, label_map, "auc_y")
        ax.text(0.5, -0.20, auc_text, transform=ax.transAxes,
                ha='center', va='top', fontsize=8, linespacing=1.2)

        # Bottom-left: COP magnitude MSE
        ax = axs[1, 0]
        for condition in entropy_conditions:
            label = condition.replace(" - ", "_").replace(" ", "_")
            color = "blue" if "Left" in condition else "red"
            linestyle = "-" if "Eyes Open" in condition else "--"
            ax.plot(scale_range, entropy_time_series_data[label]["mse_mag"],
                    color=color, linestyle=linestyle)

        ax.set_title("MSE - COP Magnitude")
        ax.set_xlabel("Scale")
        ax.set_ylabel("Entropy")
        ax.set_ylim(0, y_limits[1])
        ax.set_xlim(1, 10)
        ax.set_box_aspect(1)
        ax.grid(True)

        auc_text = get_overlay_auc_text(entropy_time_series_data, label_map, "auc_mag")
        ax.text(0.5, -0.20, auc_text, transform=ax.transAxes,
                ha='center', va='top', fontsize=8, linespacing=1.2)

        # Bottom-right: MMSE
        ax = axs[1, 1]
        for condition in entropy_conditions:
            label = condition.replace(" - ", "_").replace(" ", "_")
            color = "blue" if "Left" in condition else "red"
            linestyle = "-" if "Eyes Open" in condition else "--"
            ax.plot(scale_range, entropy_time_series_data[label]["mmse"],
                    color=color, linestyle=linestyle)

        ax.set_title("MMSE - COPx & COPy")
        ax.set_xlabel("Scale")
        ax.set_ylabel("Entropy")
        ax.set_ylim(0, y_limits[1])
        ax.set_xlim(1, 10)
        ax.set_box_aspect(1)
        ax.grid(True)

        auc_text = get_overlay_auc_text(entropy_time_series_data, label_map, "auc_mmse")
        ax.text(0.5, -0.20, auc_text, transform=ax.transAxes,
                ha='center', va='top', fontsize=8, linespacing=1.2)

        # Add one legend for the whole figure
        legend_elements = [
            Line2D([0], [0], color='blue', linestyle='-', label='Eyes Open - Left'),
            Line2D([0], [0], color='red', linestyle='-', label='Eyes Open - Right'),
            Line2D([0], [0], color='blue', linestyle='--', label='Eyes Closed - Left'),
            Line2D([0], [0], color='red', linestyle='--', label='Eyes Closed - Right'),
        ]
        fig.legend(handles=legend_elements,
            loc='upper center',
            bbox_to_anchor=(0.5, 0.54),
            fontsize=10,
            ncol=1,
            frameon=True)


        pdf.savefig(fig)
        plt.show(block=False)
        plt.pause(2)
        plt.close(fig)

    print(f"✅ Entropy overlay summary PDF saved to: {overlay_pdf_path}")

    # === Run excel exports ===
    export_cop_metrics_excel(trajectory_info, subject_code, save_folder)
    export_entropy_metrics_excel(entropy_time_series_data, subject_code, save_folder)

    if context is not None:
        candidate_names = [
            f"{subject_code}_Entropy_Summary.xlsx",
            f"{subject_code}_SLB_COP_Results.pdf",
            f"{subject_code}_Entropy_Scale_Results.pdf",
            f"{subject_code}_Entropy_Overlay_Results.pdf",
            f"SLB_COP_{subject_code}.xlsx",
            f"SLB_COP_Entropy_{subject_code}.xlsx",
        ]
        output_files = [
            os.path.join(save_folder, n) for n in candidate_names
            if os.path.exists(os.path.join(save_folder, n))
        ]
        return make_run_result("success", output_dir=save_folder, output_files=output_files,
                                summary={"conditions_processed": len(files)})
    return None
    