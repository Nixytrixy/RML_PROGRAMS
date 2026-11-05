import os
import re
import time
import math
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
import cv2
import numpy as np
from datetime import datetime
from tkinter import Tk, messagebox
from tkinter.filedialog import askdirectory

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:
    try:
        cv2.setLogLevel(0)
    except Exception:
        pass


def name():
    return "Combine Videos"

# ---------------------------
# Helpers
# ---------------------------
def list_avi_files(folder):
    """
    Return a list of file names in the given folder that end with ".avi".

    Args:
        folder (str): The path to the folder to search for AVI files.

    Returns:
        list: A list of file names that end with ".avi".

    Raises:
        FileNotFoundError: If the folder does not exist.
    """
    try:
        return [f for f in os.listdir(folder) if f.lower().endswith(".avi")]
    except FileNotFoundError:
        return []

def base_name_without_plane(fname):
    """
    Strip '-Sagittal.avi' or '-Coronal.avi' and return the base.
    Returns None if it doesn't match the expected pattern.
    """
    m = re.search(r"-(Sagittal|Coronal)\.avi$", fname, re.IGNORECASE)
    if not m:
        return None
    return fname[:m.start()]

def read_all_frames(cap):
    """
    Read all frames from a cv2.VideoCapture into a list.
    Returns (frames_list, fps, frame_size) where frame_size=(w,h).
    """
    fps = cap.get(cv2.CAP_PROP_FPS)
    w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    return frames, fps, (w, h)

def downsample_to_match(frames_long, frames_short_len):
    """
    Downsample a longer list of frames to the length of frames_short_len
    using evenly spaced indices. (0-based indexing, unlike MATLAB.)
    """
    if len(frames_long) == frames_short_len:
        return frames_long
    idxs = np.linspace(0, len(frames_long) - 1, frames_short_len, dtype=int)
    return [frames_long[i] for i in idxs]

def resize_to_same_height(frame, target_h):
    """
    Keep aspect ratio; resize frame to target height.
    """
    h, w = frame.shape[:2]
    if h == target_h:
        return frame
    scale = target_h / float(h)
    new_w = int(round(w * scale))
    return cv2.resize(frame, (new_w, target_h), interpolation=cv2.INTER_AREA)

def combine_side_by_side(f1, f2, target_h=None):
    """
    Combine two frames horizontally. If heights differ, resize both
    to min height (to avoid upscaling). Optionally pass target_h.
    """
    h1, w1 = f1.shape[:2]
    h2, w2 = f2.shape[:2]
    if target_h is None:
        target_h = min(h1, h2)  # avoid upscaling
    f1r = resize_to_same_height(f1, target_h)
    f2r = resize_to_same_height(f2, target_h)
    return np.hstack([f1r, f2r])

def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

# ---------------------------
# Main
# ---------------------------

def preflight_fields(context=None):
    """Inputs choosable before processing starts (see analysis_registry.py).

    "video_dir" is the same key Sport_CreateStills.py uses for its video
    folder — when both tests are selected together, they'll be asked once
    and share the answer instead of prompting for the same folder twice.
    """
    return [
        {"key": "video_dir", "label": "Folder of video files to combine (Folder 1)",
         "type": "dir", "default": ""},
        {"key": "combine_use_second_dir", "label": "Is there another directory?",
         "type": "bool", "default": False},
        {"key": "combine_video_dir_2", "label": "Second folder of video files to combine",
         "type": "dir", "default": "", "depends_on": "combine_use_second_dir"},
    ]


def main(context=None, inputs=None):
    from analysis_registry import make_run_result, default_output_dir

    # Use Tkinter to pick directories (like MATLAB uigetdir)
    root = Tk()
    root.withdraw()

    if inputs is not None:
        viddir1 = inputs.get("video_dir", "")
    else:
        print("Select directory of video files (Folder 1)…")
        viddir1 = askdirectory(title="Select folder of video files to combine (Folder 1)")
    if not viddir1:
        print("No directory selected. Exiting.")
        return make_run_result("cancelled") if context is not None else None

    files1 = list_avi_files(viddir1)
    print(f"Found {len(files1)} AVI files in: {viddir1}")

    files2 = []
    viddir2 = None
    if inputs is not None:
        viddir2 = inputs.get("combine_video_dir_2") or None
        if viddir2:
            files2 = list_avi_files(viddir2)
            print(f"Found {len(files2)} AVI files in: {viddir2}")
    else:
        # Ask if there is another directory (like questdlg)
        use_second = messagebox.askyesno("Second Video Dir", "Is there another directory?")
        if use_second:
            print("Select directory of video files (Folder 2)…")
            viddir2 = askdirectory(initialdir=viddir1, title="Select folder of video files to combine (Folder 2)")
            if viddir2:
                files2 = list_avi_files(viddir2)
                print(f"Found {len(files2)} AVI files in: {viddir2}")

    if context is not None:
        save_dir = str(default_output_dir(context.visit_dir, "combine_videos", visit_type=context.visit_type))
    else:
        print("Select output directory…")
        save_dir = askdirectory(initialdir=viddir1, title="Select save directory")
        if not save_dir:
            print("No save directory selected. Exiting.")
            return None
    ensure_dir(save_dir)
    print(f"Files will be saved to: {save_dir}")

    # Build a mapping from base name -> dict with sagittal and coronal full paths
    candidates = {}

    def ingest(folder, files):
        for f in files:
            base = base_name_without_plane(f)
            if base is None:
                continue
            full = os.path.join(folder, f)
            key = base
            if key not in candidates:
                candidates[key] = {"Sagittal": None, "Coronal": None}
            if f.lower().endswith("-sagittal.avi"):
                candidates[key]["Sagittal"] = full
            elif f.lower().endswith("-coronal.avi"):
                candidates[key]["Coronal"] = full

    ingest(viddir1, files1)
    if viddir2:
        ingest(viddir2, files2)

    # Only keep those that have both planes
    pairs = {k: v for k, v in candidates.items() if v["Sagittal"] and v["Coronal"]}
    if not pairs:
        print("No paired '-Sagittal.avi' and '-Coronal.avi' files found.")
        if context is not None:
            return make_run_result("error", error="No paired '-Sagittal.avi' and '-Coronal.avi' files found.")
        return None

    keys = sorted(pairs.keys())
    eta_log = []
    total = len(keys)
    output_files = []
    pairs_skipped = 0

    print(f"Found {total} paired base names. Starting processing…\n")

    for i, base in enumerate(keys, start=1):
        t0 = time.time()
        sag_path = pairs[base]["Sagittal"]
        cor_path = pairs[base]["Coronal"]

        print(f"[{i}/{total}] {base} started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        cap1 = cv2.VideoCapture(sag_path)
        cap2 = cv2.VideoCapture(cor_path)
        if not cap1.isOpened() or not cap2.isOpened():
            print(f"  Skipping (could not open): {base}")
            cap1.release()
            cap2.release()
            pairs_skipped += 1
            continue

        try:
            # Read all frames
            frames1, fps1, size1 = read_all_frames(cap1)
            frames2, fps2, size2 = read_all_frames(cap2)
        finally:
            cap1.release()
            cap2.release()

        n1 = len(frames1)
        n2 = len(frames2)
        if n1 == 0 or n2 == 0:
            print(f"  Skipping (empty video): {base}")
            pairs_skipped += 1
            continue

        # Match frame counts by downsampling the longer one
        if   n1 > n2: frames1 = downsample_to_match(frames1, n2)
        elif n2 > n1: frames2 = downsample_to_match(frames2, n1)

        num_final = min(len(frames1), len(frames2))
        frames1 = frames1[:num_final]
        frames2 = frames2[:num_final]

        # Output fps = min of both
        out_fps = min(fps1 if fps1 > 0 else 30.0, fps2 if fps2 > 0 else 30.0)

        # Determine output size by combining a sample frame
        test_combined = combine_side_by_side(frames1[0], frames2[0], target_h=None)
        out_h, out_w = test_combined.shape[:2]

        fourcc = cv2.VideoWriter_fourcc(*'MJPG')  # Motion JPEG AVI
        out_path = os.path.join(save_dir, f"{base}_CoronalSagittal.avi")
        writer = cv2.VideoWriter(out_path, fourcc, out_fps, (out_w, out_h))

        if not writer.isOpened():
            print(f"  ERROR: Could not create writer for {out_path}")
            pairs_skipped += 1
            continue

        # Write frames
        for j in range(num_final):
            f1 = frames1[j]
            f2 = frames2[j]
            combined = combine_side_by_side(f1, f2, target_h=test_combined.shape[0])
            writer.write(combined)

        writer.release()
        output_files.append(out_path)

        # ETA logging
        dt = time.time() - t0
        eta_log.append(dt)
        remaining = (total - i) * (sum(eta_log) / len(eta_log))
        etah = int(remaining // 3600)
        etam = int((remaining % 3600) // 60)
        etas = int(remaining % 60)
        print(f"  Saved: {out_path}")
        print(f"  Est. Time Remaining: {etah} hr : {etam} min : {etas} s\n")

    total_time = sum(eta_log)
    H = int(total_time // 3600)
    M = int((total_time % 3600) // 60)
    S = int(total_time % 60)
    print(f"Elapsed Time: {H} hr : {M} min : {S} s")

    if context is not None:
        return make_run_result("success", output_dir=save_dir, output_files=output_files,
                                summary={"pairs_combined": len(output_files), "pairs_skipped": pairs_skipped})
    return None

if __name__ == "__main__":
    main()
