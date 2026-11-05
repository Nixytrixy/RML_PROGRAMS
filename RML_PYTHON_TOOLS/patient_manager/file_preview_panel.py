# file_preview_panel.py
# Sidebar + in-app preview for a test's output files, meant to be packed into a
# patient_manager_ui.py test sub-tab (see PatientDetailPage._build_test_subtab).
#
# Two layers, mirroring video_player.py's own split:
#   - _FileSidebar: scrollable vertical list of file rows (click to select, right-click
#     to reveal in Explorer).
#   - FilePreviewPanel: the public widget -- sidebar on the left, in-app preview of the
#     selected file on the right.
#
# Preview support degrades gracefully per file type -- video needs python-vlc (via
# video_player.VLC_AVAILABLE), images need Pillow, spreadsheets need openpyxl. Pillow
# and openpyxl are imported lazily (on first actual use, not at module load) -- this
# project's whole venv lives under a OneDrive-synced folder, and openpyxl drags in all
# of numpy, which is slow enough to import on a not-yet-hydrated OneDrive path that it
# would otherwise add noticeable delay to every single app launch, not just the rare
# case where someone actually opens a spreadsheet. Anything unsupported (including
# PDFs -- no page-rendering library is installed in this project) falls back to a
# generic info panel with an "Open Externally" button.

from __future__ import annotations

import csv
import json
import os
import subprocess
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox
from typing import Optional

import video_player

Image = None
ImageTk = None
PIL_AVAILABLE = False
_pil_probed = False

openpyxl = None
OPENPYXL_AVAILABLE = False
_openpyxl_probed = False


def _ensure_pil() -> bool:
    global Image, ImageTk, PIL_AVAILABLE, _pil_probed
    if not _pil_probed:
        _pil_probed = True
        try:
            from PIL import Image as _Image, ImageTk as _ImageTk
            Image, ImageTk = _Image, _ImageTk
            PIL_AVAILABLE = True
        except Exception:
            PIL_AVAILABLE = False
    return PIL_AVAILABLE


def _ensure_openpyxl() -> bool:
    global openpyxl, OPENPYXL_AVAILABLE, _openpyxl_probed
    if not _openpyxl_probed:
        _openpyxl_probed = True
        try:
            import openpyxl as _openpyxl
            openpyxl = _openpyxl
            OPENPYXL_AVAILABLE = True
        except Exception:
            OPENPYXL_AVAILABLE = False
    return OPENPYXL_AVAILABLE

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif"}
TABLE_CSV_EXTS = {".csv"}
TABLE_EXCEL_EXTS = {".xlsx", ".xlsm"}
TEXT_EXTS = {".txt", ".json", ".log", ".xml", ".ini", ".md", ".yaml", ".yml"}

MAX_TABLE_ROWS = 1000
MAX_TEXT_BYTES = 500_000


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

class _FileSidebar(tk.Frame):
    """Scrollable vertical list of file rows. Calls on_select(path) when a row is
    clicked; knows nothing about how files get previewed."""

    _BG = "SystemButtonFace"
    _FG = "SystemWindowText"
    _BG_SELECTED = "#0078D7"
    _FG_SELECTED = "white"

    def __init__(self, parent, files: list[str], on_select, width: int = 240):
        super().__init__(parent, width=width, bg=self._BG)
        self.pack_propagate(False)
        self._on_select_cb = on_select
        self._wrap = max(width - 40, 120)
        self._rows: dict[str, tk.Label] = {}
        self._selected_path: Optional[str] = None

        self._canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=self._BG)
        self._vscroll = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)
        self._vscroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._rows_frame = tk.Frame(self._canvas, bg=self._BG)
        self._rows_window = self._canvas.create_window((0, 0), window=self._rows_frame, anchor="nw")

        self._rows_frame.bind("<Configure>", self._on_rows_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind("<Enter>", self._bind_mousewheel)
        self.bind("<Leave>", self._unbind_mousewheel)

        self.set_files(files)

    def set_files(self, files: list[str]):
        for row in self._rows.values():
            row.destroy()
        self._rows.clear()
        self._selected_path = None
        for path in files:
            row = tk.Label(
                self._rows_frame, text=os.path.basename(path), anchor="w", justify="left",
                wraplength=self._wrap, padx=8, pady=6, font=("Segoe UI", 9), cursor="hand2",
                bg=self._BG, fg=self._FG,
            )
            row.pack(fill="x")
            row.bind("<Button-1>", lambda _e, p=path: self._on_row_click(p))
            row.bind("<Button-3>", lambda e, p=path: self._show_context_menu(e, p))
            self._rows[path] = row

    def select(self, path: str):
        if self._selected_path is not None and self._selected_path in self._rows:
            self._rows[self._selected_path].configure(bg=self._BG, fg=self._FG)
        if path in self._rows:
            self._rows[path].configure(bg=self._BG_SELECTED, fg=self._FG_SELECTED)
        self._selected_path = path

    def _on_row_click(self, path: str):
        self.select(path)
        self._on_select_cb(path)

    def _on_rows_frame_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._rows_window, width=event.width)

    # Bind/unbind on the outer frame (not the canvas): the canvas's rows are real
    # child windows (via create_window), so hovering a row fires <Leave> on the
    # canvas immediately -- binding here, on their common ancestor, is what keeps
    # the wheel handler live while the pointer is anywhere over the sidebar.
    def _bind_mousewheel(self, _event=None):
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event=None):
        self._canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _show_context_menu(self, event, path: str):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Show in File Explorer", command=lambda: _reveal_in_explorer(path))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


# ---------------------------------------------------------------------------
# Public panel
# ---------------------------------------------------------------------------

class FilePreviewPanel(ttk.Frame):
    """Sidebar (left) + in-app preview (right) for a list of files. One instance per
    test sub-tab. Video playback reuses a single EmbeddedVideoPlayer across every
    video file selected in this panel; every other file type gets its own preview
    widget, built lazily on first selection and cached by path."""

    def __init__(self, parent, files: list[str], sidebar_width: int = 240):
        super().__init__(parent)
        self._cache: dict[str, tk.Widget] = {}
        self._video_player: Optional[video_player.EmbeddedVideoPlayer] = None

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        self._sidebar = _FileSidebar(paned, files, on_select=self._on_select, width=sidebar_width)
        self._preview_container = ttk.Frame(paned)
        self._preview_container.grid_rowconfigure(0, weight=1)
        self._preview_container.grid_columnconfigure(0, weight=1)

        paned.add(self._sidebar, weight=0)
        paned.add(self._preview_container, weight=1)

        ttk.Label(
            self._preview_container, text="Select a file to preview",
            foreground="#666666", font=("Segoe UI", 10), anchor="center",
        ).grid(row=0, column=0, sticky="nsew")

    def _on_select(self, path: str):
        ext = os.path.splitext(path)[1].lower()
        if ext in video_player.VIDEO_EXTS and video_player.VLC_AVAILABLE:
            self._show_video(path)
        else:
            self._show_cached(path)

    def _show_video(self, path: str):
        if self._video_player is None:
            self._video_player = video_player.EmbeddedVideoPlayer(self._preview_container)
            self._video_player.grid(row=0, column=0, sticky="nsew")
        self._video_player.load(path)
        self._video_player.tkraise()

    def _show_cached(self, path: str):
        # tkraise() only changes stacking order -- a video left playing underneath
        # would keep decoding/playing audio unless explicitly stopped.
        if self._video_player is not None:
            self._video_player.stop()
        widget = self._cache.get(path)
        if widget is None:
            widget = _build_preview_for(self._preview_container, path)
            widget.grid(row=0, column=0, sticky="nsew")
            self._cache[path] = widget
        widget.tkraise()


# ---------------------------------------------------------------------------
# Preview dispatch
# ---------------------------------------------------------------------------

def _build_preview_for(parent, path: str) -> tk.Widget:
    if not os.path.exists(path):
        return _build_fallback_preview(parent, path)

    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in video_player.VIDEO_EXTS:
            return _build_fallback_preview(
                parent, path,
                note="Video preview unavailable (python-vlc/libvlc is not installed on this machine).",
            )
        if ext in IMAGE_EXTS:
            return _build_image_preview(parent, path)
        if ext in TABLE_CSV_EXTS or ext in TABLE_EXCEL_EXTS:
            return _build_table_preview(parent, path)
        if ext in TEXT_EXTS:
            return _build_text_preview(parent, path)
    except Exception as e:
        return _build_fallback_preview(parent, path, note=f"Couldn't preview this file: {e}")

    return _build_fallback_preview(parent, path)  # unknown types, including .pdf


def _preview_pane_size(widget) -> tuple[int, int]:
    widget.update_idletasks()
    w, h = widget.winfo_width(), widget.winfo_height()
    if w < 50 or h < 50:
        w, h = 700, 500
    return w, h


def _build_image_preview(parent, path: str) -> tk.Widget:
    if not _ensure_pil():
        return _build_fallback_preview(parent, path, note="Pillow is not installed; cannot preview images.")
    img = Image.open(path)
    img.load()
    max_w, max_h = _preview_pane_size(parent)
    img.thumbnail((max(max_w - 20, 100), max(max_h - 20, 100)), Image.LANCZOS)
    photo = ImageTk.PhotoImage(img)
    lbl = tk.Label(parent, image=photo, bg="#1e1e1e")
    lbl.image = photo  # keep a reference -- otherwise PhotoImage is GC'd and the Label goes blank
    return lbl


def _read_csv_rows(path: str, max_rows: int):
    with open(path, "r", newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return [], [], False, 0
        rows = []
        total = 0
        for row in reader:
            total += 1
            if len(rows) < max_rows:
                rows.append(row)
        return header, rows, total > len(rows), total


def _read_xlsx_rows(path: str, max_rows: int):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        row_iter = wb.active.iter_rows(values_only=True)
        try:
            header = next(row_iter)
        except StopIteration:
            return [], [], False, 0
        header = ["" if v is None else v for v in header]
        rows = []
        total = 0
        for r in row_iter:
            total += 1
            if len(rows) < max_rows:
                rows.append(["" if v is None else v for v in r])
        return header, rows, total > len(rows), total
    finally:
        wb.close()  # read-only workbooks keep the file locked open otherwise


def _build_table_preview(parent, path: str) -> tk.Widget:
    ext = os.path.splitext(path)[1].lower()
    if ext in TABLE_CSV_EXTS:
        header, rows, truncated, total = _read_csv_rows(path, MAX_TABLE_ROWS)
    else:
        if not _ensure_openpyxl():
            return _build_fallback_preview(parent, path, note="openpyxl is not installed; cannot preview spreadsheets.")
        header, rows, truncated, total = _read_xlsx_rows(path, MAX_TABLE_ROWS)

    if not header and not rows:
        return _build_fallback_preview(parent, path, note="File appears to be empty.")

    container = ttk.Frame(parent)
    col_ids = [str(i) for i in range(len(header))]
    tree = ttk.Treeview(container, columns=col_ids, show="headings")
    for col_id, name in zip(col_ids, header):
        tree.heading(col_id, text=str(name) if name not in (None, "") else f"Column {int(col_id) + 1}")
        tree.column(col_id, width=120, stretch=True)
    for row in rows:
        row = list(row)
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        tree.insert("", "end", values=row[:len(header)])

    vscroll = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
    hscroll = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vscroll.grid(row=0, column=1, sticky="ns")
    hscroll.grid(row=1, column=0, sticky="ew")
    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)

    if truncated:
        note = f"Showing first {MAX_TABLE_ROWS:,} of {total:,} rows"
        ttk.Label(container, text=note, foreground="#666666", font=("Segoe UI", 8)).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

    return container


def _build_text_preview(parent, path: str) -> tk.Widget:
    container = tk.Frame(parent)
    text = tk.Text(container, wrap="word", font=("Consolas", 9))
    vscroll = ttk.Scrollbar(container, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=vscroll.set)
    vscroll.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)

    size = os.path.getsize(path)
    with open(path, "rb") as f:
        raw = f.read(MAX_TEXT_BYTES + 1)
    truncated = len(raw) > MAX_TEXT_BYTES
    content = raw[:MAX_TEXT_BYTES].decode("utf-8", errors="replace")

    if path.lower().endswith(".json") and not truncated:
        try:
            content = json.dumps(json.loads(content), indent=2)
        except (json.JSONDecodeError, ValueError):
            pass

    if truncated:
        text.insert("1.0", f"[Showing first {MAX_TEXT_BYTES // 1000} KB of {size / 1024:.0f} KB "
                            f"-- use Open Externally to see the full file]\n\n")
        text.insert("end", content)
    else:
        text.insert("1.0", content)
    text.configure(state="disabled")
    return container


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _build_fallback_preview(parent, path: str, note: str = "") -> tk.Widget:
    container = ttk.Frame(parent, padding=16)
    exists = os.path.exists(path)

    ttk.Label(container, text=os.path.basename(path), font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))

    if not exists:
        ttk.Label(container, text="File not found (it may have been moved or deleted).",
                  foreground="red").pack(anchor="w", pady=(0, 8))
    else:
        st = os.stat(path)
        modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        ttk.Label(container, text=f"Size: {_human_size(st.st_size)}    Modified: {modified}",
                  font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 8))

    if note:
        ttk.Label(container, text=note, foreground="#666666", font=("Segoe UI", 8),
                  wraplength=420).pack(anchor="w", pady=(0, 8))

    path_row = ttk.Frame(container)
    path_row.pack(fill="x", pady=(0, 12))
    ttk.Label(path_row, text="Path:").pack(side="left")
    entry = ttk.Entry(path_row)
    entry.insert(0, path)
    entry.configure(state="readonly")  # readonly (not disabled) still allows selecting/copying
    entry.pack(side="left", fill="x", expand=True, padx=6)

    if exists:
        ttk.Button(container, text="Open Externally", command=lambda: _open_externally(path)).pack(anchor="w")

    return container


# ---------------------------------------------------------------------------
# File-system actions
# ---------------------------------------------------------------------------

def _open_externally(path: str) -> None:
    try:
        os.startfile(path)
    except Exception as e:
        messagebox.showerror("Could not open", f"{path}\n\n{e}")


def _reveal_in_explorer(path: str) -> None:
    try:
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
    except Exception as e:
        messagebox.showerror("Could not show in File Explorer", f"{path}\n\n{e}")
