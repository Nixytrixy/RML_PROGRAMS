#!/usr/bin/env python3
"""
Sport_CreateStills
------------------
Create combined Sagittal+Coronal stills at timestamps (in seconds) specified
by Visual3D event files, WITHOUT using ffmpeg. Uses OpenCV (cv2) to decode and
seek by time, and Pillow (PIL) to save/concat.

Supports ANY task name in the first .c3d line (e.g., "Cut_3.c3d", "Shuffle_1.c3d", "Hop_2.c3d").
Matches those tasks against video bases like "Sport-####_<Task>" (e.g., "Sport-0136_Shuffle_1").

Event files:
  - First .c3d token gives the TASK token (e.g., "Shuffle_1.c3d" -> "Shuffle_1").
  - After the header line "ITEM    X", each subsequent line "idx  time" contributes
    a timestamp (seconds) and we produce an output still for EACH time.

Video filenames supported (case-insensitive; hyphen or underscore before the view):
  Sport-####_<Task>-Sagittal.avi
  Sport-####_<Task>-Coronal.avi
(tolerates 'Sagital'/'Corronal' spellings too)

Public API for launcher:
  - name() -> str
  - main() -> None
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Tuple

# Third-party
try:
    import cv2  # OpenCV for reading/seeking video
except ImportError as e:
    raise ImportError("OpenCV is required. Install with: pip install opencv-python") from e

try:
    from PIL import Image  # image IO / concat
except ImportError as e:
    raise ImportError("Pillow is required. Install with: pip install pillow") from e


# ----------- CONFIG -----------
# Optional: shift timestamps if you need a global offset (in seconds)
TIME_OFFSET_SEC = 0.0
# Fallback FPS-based index rounding when MSEC seek isn't supported: "round", "floor", or "ceil".
FRAME_INDEX_ROUNDING = "round"
# --------------------------------

_METHOD_NAME = "Create Stills from V3D"


def name() -> str:
    """Display name for the launcher menu."""
    return _METHOD_NAME


# ---------- GUI/CLI utils ----------

# Try tkinter GUI; fall back to CLI if unavailable
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    _HAS_TK = True
except Exception:
    _HAS_TK = False


def pick_directory(title: str, initialdir: Optional[str] = None) -> Path:
    """Pick a directory (GUI if possible, else CLI)."""
    if _HAS_TK:
        root = tk.Tk()
        root.withdraw()
        root.update()
        d = filedialog.askdirectory(title=title, initialdir=initialdir or os.getcwd())
        root.destroy()
        if d:
            return Path(d)
    while True:
        p = input(f"{title}\nEnter directory path: ").strip('"').strip()
        if p:
            pp = Path(p)
            if pp.is_dir():
                return pp
        print("Invalid directory. Try again.")


def yes_no(title: str, question: str) -> bool:
    """Yes/No prompt (GUI if possible, else CLI)."""
    if _HAS_TK:
        root = tk.Tk()
        root.withdraw()
        ans = messagebox.askquestion(title, question, icon="question")
        root.destroy()
        return ans == "yes"
    while True:
        resp = input(f"{title}: {question} [y/n]: ").strip().lower()
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


# ---------- Event file parsing (any task; many events) ----------

@dataclass
class EventFileInfo:
    task_token: Optional[str]   # e.g., "Cut_3", "Shuffle_1" (from first .c3d); None if not found
    times_seconds: List[float]  # list of timestamps in seconds (from rows under "ITEM    X")


FIRST_C3D_RX = re.compile(r"(?i)\b([\w.-]+\.c3d)\b")
TASK_FROM_C3D_RX = re.compile(r"(?i)\b([A-Za-z]+[A-Za-z0-9]*[_-]\d+)\b")  # e.g., Cut_3, Shuffle_1, Hop-2
NUM_RX = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

def parse_event_file(event_txt: Path) -> EventFileInfo:
    """
    Parse a Visual3D event file with a general format.

    - TASK TOKEN:
        Take the first .c3d token, then extract a token like "<Word>_<digits>" or "<Word>-<digits>"
        from that c3d name. Examples:
            "Cut_3.c3d"      -> "Cut_3"
            "Shuffle_1.c3d"  -> "Shuffle_1"
            "Hop-2.c3d"      -> "Hop-2"
        If no such token is found, task_token = None.

    - TIMES:
        Look for a line that starts with "ITEM" (case-insensitive). After that line,
        parse subsequent lines of the form: "<index>  <seconds>" until a blank/invalid row.
        If no "ITEM" header is found, fall back to: take ALL numeric tokens in the file
        and use the **last one** as a single timestamp (to preserve legacy behavior).
    """
    with event_txt.open("r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.rstrip("\n") for ln in f]

    # TASK TOKEN from first .c3d line
    task_token: Optional[str] = None
    joined = "\n".join(lines)
    m_c3d = FIRST_C3D_RX.search(joined)
    if m_c3d:
        c3d_name = m_c3d.group(1)
        base = Path(c3d_name).stem  # e.g., "Shuffle_1"
        m_task = TASK_FROM_C3D_RX.search(base)
        if m_task:
            task_token = m_task.group(1)

    # TIMES under "ITEM" header
    times: List[float] = []
    # find the "ITEM" header row
    item_idx = None
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("item"):
            item_idx = i
            break

    if item_idx is not None:
        # parse rows after ITEM header
        for ln in lines[item_idx + 1:]:
            if not ln.strip():
                break
            # Accept either "idx  time" or tab-delimited
            parts = re.split(r"\s+", ln.strip())
            if len(parts) < 2:
                break
            # First should be an integer index, second should be a float seconds
            try:
                _ = int(parts[0])
                t = float(parts[1]) + TIME_OFFSET_SEC
                if t < 0:
                    t = 0.0
                times.append(t)
            except ValueError:
                # Stop on first non-conforming line after ITEM block
                break

    if not times:
        # Fallback to previous behavior: last numeric in file as single timestamp
        nums = NUM_RX.findall(joined)
        if nums:
            t = float(nums[-1]) + TIME_OFFSET_SEC
            if t < 0:
                t = 0.0
            times = [t]

    return EventFileInfo(task_token=task_token, times_seconds=times)


# ---------- Video base indexing & resolution ----------

# We accept either "-" or "_" separating the <Task> from the view word.
# Example filenames matched:
#   Sport-0136_Cut_3-Sagittal.avi
#   Sport-0136_Shuffle_1-Coronal.avi
#   Sport-0136_Hop-2_Sagittal.avi  (underscore before view also tolerated)
BASE_AND_VIEW_RX = re.compile(
    r"(?i)\b(Sport-\d{4})_([^-_]+(?:[-_]\d+)*)[-_].*(sagittal|sagital|coronal|corronal)\b"
)

def detect_view(name: str) -> Optional[str]:
    n = name.lower()
    if "sagittal" in n or "sagital" in n:
        return "sag"
    if "coronal" in n or "corronal" in n:
        return "cor"
    return None


@dataclass
class VideoPair:
    sport_id: str      # e.g., "Sport-0136"
    task_token: str    # e.g., "Cut_3", "Shuffle_1"
    folder: Path
    sagittal: Optional[Path] = None
    coronal: Optional[Path] = None

    @property
    def base_key(self) -> str:
        return f"{self.sport_id}_{self.task_token}"


def enumerate_video_pairs(vid_paths: List[Path]) -> Dict[str, VideoPair]:
    """
    Group videos into pairs keyed by "<SportID>_<TaskToken>".
    """
    pairs: Dict[str, VideoPair] = {}
    for p in vid_paths:
        name = p.name
        if not name.lower().endswith(".avi"):
            continue
        m = BASE_AND_VIEW_RX.search(name)
        if not m:
            continue
        sport_id = m.group(1)           # "Sport-0136"
        task_token = m.group(2)         # "Cut_3", "Shuffle_1", "Hop-2", etc.
        view = m.group(3).lower()       # view word
        key = f"{sport_id}_{task_token}"
        vp = pairs.get(key)
        if vp is None:
            vp = VideoPair(sport_id=sport_id, task_token=task_token, folder=p.parent)
            pairs[key] = vp
        which = detect_view(name)
        if which == "sag":
            vp.sagittal = p
        elif which == "cor":
            vp.coronal = p
    return pairs


def resolve_pair_for_event(
    pairs: Dict[str, VideoPair],
    task_token: Optional[str]
) -> Optional[VideoPair]:
    """
    Resolve which video pair to use for a given event file by TASK token.
    Rules:
      1) If task_token is present (e.g., "Shuffle_1"), pick the ONLY pair whose key endswith "_<task_token>".
      2) If multiple pairs share that task_token (e.g., multiple Sport IDs present), pick the first alphabetically
         and print a note.
      3) If task_token is None and only one pair exists, use it.
      4) Otherwise, ambiguous -> None.
    """
    if task_token:
        matches = [vp for vp in pairs.values() if vp.base_key.lower().endswith("_" + task_token.lower())]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            matches.sort(key=lambda v: v.base_key.lower())
            print(f"[NOTE] Multiple video bases match task '{task_token}': {[m.base_key for m in matches]}. Using {matches[0].base_key}.")
            return matches[0]

    if len(pairs) == 1:
        return next(iter(pairs.values()))
    return None


# ---------- OpenCV helpers (seek by time) ----------

def _round_index(idx: float) -> int:
    if FRAME_INDEX_ROUNDING == "floor":
        import math
        return int(math.floor(idx))
    if FRAME_INDEX_ROUNDING == "ceil":
        import math
        return int(math.ceil(idx))
    return int(round(idx))


def read_frame_at_time(video_path: Path, time_sec: float) -> Image.Image:
    """
    Seek to time_sec and read a frame; return as PIL.Image.
    1) Try MSEC seek (CAP_PROP_POS_MSEC)
    2) Fallback to FPS*seconds index
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    # Try MSEC seek first
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_sec) * 1000.0)
    ok, frame = cap.read()
    if ok and frame is not None:
        cap.release()
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb)

    # Fallback: FPS-based index
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    idx = 0
    if fps and fps > 0:
        idx = _round_index(time_sec * fps)

    if frame_count > 0:
        if idx >= frame_count:
            idx = frame_count - 1
        if idx < 0:
            idx = 0

    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok2, frame2 = cap.read()
    if not ok2 or frame2 is None:
        ok2, frame2 = cap.read()
    cap.release()

    if not ok2 or frame2 is None:
        raise RuntimeError(
            f"Failed to read frame at t={time_sec:.3f}s (approx idx {idx}) from {video_path.name}"
        )

    frame_rgb = cv2.cvtColor(frame2, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame_rgb)


def concat_horizontal(left_img: Image.Image, right_img: Image.Image) -> Image.Image:
    """Concatenate two PIL images horizontally, padding shorter height with black."""
    H = max(left_img.height, right_img.height)

    def pad_h(img: Image.Image) -> Image.Image:
        if img.height == H:
            return img
        new_im = Image.new("RGB", (img.width, H), (0, 0, 0))
        top = (H - img.height) // 2
        new_im.paste(img, (0, top))
        return new_im

    im1p = pad_h(left_img.convert("RGB"))
    im2p = pad_h(right_img.convert("RGB"))
    combined = Image.new("RGB", (im1p.width + im2p.width, H))
    combined.paste(im1p, (0, 0))
    combined.paste(im2p, (im1p.width, 0))
    return combined


# ---------- Internal runner ----------

def _safe_out_name(base: str) -> str:
    """Sanitize a filename stem (keep it simple)."""
    return re.sub(r"[^\w\-]+", "_", base).strip("_")


def preflight_fields(context=None):
    """Inputs choosable before processing starts (see analysis_registry.py).

    "video_dir" is the same key CombineVideos.py uses for its video folder —
    when both tests are selected together, they'll be asked once and share
    the answer instead of prompting for the same folder twice.
    """
    return [
        {"key": "sport_frame_dir", "label": "Directory of frame files", "type": "dir", "default": ""},
        {"key": "video_dir", "label": "Directory of video files", "type": "dir", "default": ""},
        {"key": "sport_use_second_video_dir", "label": "Is there another video directory?",
         "type": "bool", "default": False},
        {"key": "sport_video_dir_2", "label": "Second directory of video files",
         "type": "dir", "default": "", "depends_on": "sport_use_second_video_dir"},
    ]


def _run(context=None, inputs=None):
    from analysis_registry import make_run_result, default_output_dir

    t0 = time.time()
    print("Running Sport_CreateStills (multi-event, any task)...\n")

    # 1) frame files dir
    if inputs is not None:
        framedir = Path(inputs.get("sport_frame_dir", ""))
    else:
        framedir = pick_directory("Pick directory of frame files")

    # enumerate *_event.txt
    event_files = sorted(framedir.glob("*_event.txt"))
    if not event_files:
        print("No *_event.txt files found in the selected frame directory.")
        if context is not None:
            return make_run_result("error", error="No *_event.txt files found in the selected frame directory.")
        return None

    # output base: strip trailing '_event'
    def out_base_for(ef: Path) -> str:
        stem = ef.stem
        return stem[:-6] if stem.endswith("_event") else stem

    # 2) video dirs
    vids2: List[Path] = []
    if inputs is not None:
        viddir = Path(inputs.get("video_dir", ""))
        vids1 = sorted(viddir.glob("*.avi"))
        viddir2_str = inputs.get("sport_video_dir_2") or ""
        if viddir2_str:
            vids2 = sorted(Path(viddir2_str).glob("*.avi"))
    else:
        viddir = pick_directory("Pick directory of video files", initialdir=str(framedir))
        vids1 = sorted(viddir.glob("*.avi"))
        if yes_no("Second Video Dir", "Is there another directory?"):
            viddir2 = pick_directory("Pick second directory of video files", initialdir=str(viddir))
            vids2 = sorted(viddir2.glob("*.avi"))

    all_vids: List[Path] = list(vids1) + list(vids2)
    if not all_vids:
        print("No .avi files found in the selected video directories.")
        if context is not None:
            return make_run_result("error", error="No .avi files found in the selected video directories.")
        return None

    # DEBUG inventory (first up to 10)
    print("\nSample videos discovered:")
    for p in all_vids[:10]:
        print("  -", p.name)

    # 3) build base -> pair map
    pairs = enumerate_video_pairs(all_vids)
    if not pairs:
        print("\nNo videos matched the expected pattern.")
        print("Expected names like: Sport-0136_Shuffle_1-Sagittal.avi and Sport-0136_Shuffle_1-Coronal.avi")
        if context is not None:
            return make_run_result("error", error="No videos matched the expected Sport-####_<Task>-<View>.avi pattern.")
        return None

    # DEBUG grouped bases
    print("\nGrouped bases found:")
    for vp in pairs.values():
        print(f"  - {vp.base_key}: sag={'yes' if vp.sagittal else 'no'}, cor={'yes' if vp.coronal else 'no'}")

    # 4) save dir
    if context is not None:
        photosavedir = default_output_dir(context.visit_dir, "sport_create_stills", visit_type=context.visit_type)
    else:
        photosavedir = pick_directory("Select save directory for images", initialdir=str(viddir))
    ensure_dir(photosavedir)

    # 5) process each event file (may contain multiple timestamps)
    failures: List[str] = []
    output_files: List[Path] = []
    for ef in event_files:
        info = parse_event_file(ef)
        out_base = _safe_out_name(out_base_for(ef))
        if not info.times_seconds:
            print(f"[WARN] {ef.name}: no timestamps found.")
            failures.append(ef.name)
            continue

        vp = resolve_pair_for_event(pairs, info.task_token)
        if not vp:
            bases_list = ", ".join(sorted(v.base_key for v in pairs.values()))
            print(f"[MISS] Could not resolve videos for '{ef.name}' (task={info.task_token}). "
                  f"Available bases: [{bases_list}]")
            failures.append(ef.name)
            continue

        if not (vp.sagittal and vp.coronal):
            print(f"[MISS] Base '{vp.base_key}' missing one view "
                  f"(sag={'present' if vp.sagittal else 'missing'}, "
                  f"cor={'present' if vp.coronal else 'missing'})")
            failures.append(ef.name)
            continue

        print(f"\n{ef.name} -> base {vp.base_key}  ({len(info.times_seconds)} event(s))")
        for idx, tsec in enumerate(info.times_seconds, start=1):
            try:
                img_sag = read_frame_at_time(vp.sagittal, tsec)
                img_cor = read_frame_at_time(vp.coronal, tsec)
            except Exception as e:
                print(f"[WARN] Read failed at t={tsec:.3f}s for {vp.base_key}: {e}")
                failures.append(f"{ef.name} @ {tsec:.3f}s")
                continue

            combined = concat_horizontal(img_sag, img_cor)
            out_path = photosavedir / f"{out_base}_{idx:02d}_Combined.jpeg"
            combined.save(out_path, format="JPEG", quality=95)
            output_files.append(out_path)
            print(f"  Saved: {out_path.name}")

    # 6) report
    if failures:
        print("\nThe following items could not be processed:")
        for m in failures:
            print(f"  - {m}")

    dt = time.time() - t0
    h = int(dt // 3600)
    m = int((dt % 3600) // 60)
    s = int(dt % 60)
    print(f"\nElapsed Time: {h} hr : {m} min : {s} s\n")

    if context is not None:
        return make_run_result("success", output_dir=photosavedir, output_files=output_files,
                                summary={"stills_created": len(output_files), "failures": len(failures)})
    return None


# ---------- Public entry point for launcher ----------

def main(context=None, inputs=None):
    """Entry point expected by the launcher."""
    return _run(context, inputs=inputs)


# ---------- Allow standalone execution ----------

if __name__ == "__main__":
    main()
