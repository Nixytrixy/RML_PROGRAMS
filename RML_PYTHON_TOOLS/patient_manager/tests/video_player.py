# video_player.py
# VLC-backed video playback, in two layers:
#   - EmbeddedVideoPlayer: a plain ttk.Frame (canvas + transport controls) meant to be
#     packed into someone else's window, e.g. a patient_manager_ui.py result tab.
#   - VideoBrowserPlayer: the standalone folder-browser app, built on top of the above.
#
# python-vlc is just a ctypes binding -- `import vlc` needs libvlc.dll/libvlccore.dll
# (and VLC's plugins/ folder) to actually be found on disk. Rather than requiring VLC
# to be installed on the target machine, we vendor those files in vlc_runtime/ (see
# that folder's provenance -- copied from a real VLC install) and point the loader at
# them before importing vlc, both when run from source and when frozen by PyInstaller
# (see rml_tools.spec, which bundles vlc_runtime/ next to the exe). VLC_AVAILABLE lets
# callers (patient_manager_ui.py) degrade gracefully -- e.g. falling back to
# os.startfile -- on the off chance the bundle is missing or a platform mismatch.

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"}


def _bundled_vlc_dir():
    """Directory containing this script (or, when frozen by PyInstaller, the
    extracted bundle root) -- vlc_runtime/ lives alongside either one."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, "vlc_runtime")
    return candidate if os.path.isdir(candidate) else None


_vlc_dir = _bundled_vlc_dir()
if _vlc_dir:
    os.environ["PYTHON_VLC_MODULE_PATH"] = _vlc_dir
    os.environ["PYTHON_VLC_LIB_PATH"] = os.path.join(_vlc_dir, "libvlc.dll")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(_vlc_dir)

try:
    import vlc
    VLC_AVAILABLE = True
except (Exception, SystemExit):
    # python-vlc's find_lib() calls sys.exit(1) (not a normal exception) if
    # PYTHON_VLC_LIB_PATH is set but fails to load -- catch that too so a bad
    # bundle degrades to VLC_AVAILABLE=False instead of killing the app.
    vlc = None
    VLC_AVAILABLE = False


class EmbeddedVideoPlayer(ttk.Frame):
    """Canvas + full transport controls (play/pause/stop, click-to-pause, seek scale,
    skip +/-5s/10s, frame stepping, speed, fullscreen, loop toggle), backed by libvlc.
    f/s/Left/Right frame-step keys are bound to this widget's own canvas (click it
    first to give it focus) rather than any shared window, so they don't fire while
    e.g. typing into an unrelated Entry field elsewhere in the host application."""

    SPEEDS = ["0.25x", "0.5x", "0.75x", "1x", "1.25x", "1.5x", "2x"]

    def __init__(self, parent):
        super().__init__(parent)
        if not VLC_AVAILABLE:
            raise RuntimeError("python-vlc / libvlc is not available")

        self.instance = vlc.Instance("--quiet", "--no-video-title-show")
        self.player = self.instance.media_player_new()

        self.rate = 1.0
        self.user_seeking = False
        self.was_playing_before_seek = False
        self.force_pause_after_seek = False
        # ~16 ms corresponds to ~60 fps; only used as a fallback when the video's
        # real fps isn't known yet (see _get_fps()).
        self.frame_step_ms = 16
        self._fps = None
        self.loop_var = tk.BooleanVar(value=True)
        self.is_fullscreen = False
        self._fs_window = None
        self._fs_canvas = None
        self._after_id = None
        self._destroyed = False

        self.time_var = tk.StringVar(value="00:00")
        self.len_var = tk.StringVar(value="00:00")
        self.scale_var = tk.DoubleVar(value=0)
        self.speed_var = tk.StringVar(value="1x")
        self.status_var = tk.StringVar(value="")

        self._build_ui()
        self._after_id = self.after(200, self._update)

    # ───────── UI ─────────
    def _build_ui(self):
        self.video = tk.Canvas(self, bg="black")
        self.video.pack(fill=tk.BOTH, expand=True)
        self.player.set_hwnd(self.video.winfo_id())

        self.video.bind("<Button-1>", self._on_canvas_click)
        self.video.bind("<KeyPress-space>", lambda e: self.toggle_play_pause())
        self.video.bind("<KeyPress-f>", lambda e: self.step_frame(+1))
        self.video.bind("<KeyPress-s>", lambda e: self.step_frame(-1))
        self.video.bind("<KeyPress-Right>", lambda e: self.step_frame(+1))
        self.video.bind("<KeyPress-Left>", lambda e: self.step_frame(-1))
        self.video.bind("<KeyPress-Escape>", lambda e: self._exit_fullscreen())

        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, pady=(6, 2))

        self.status_label = ttk.Label(row1, textvariable=self.status_var, foreground="#0078D7")
        self.status_label.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_play = ttk.Button(row1, text="▶ Play", command=self.play)
        self.btn_play.pack(side=tk.LEFT)
        ttk.Button(row1, text="⏸ Pause", command=self.pause).pack(side=tk.LEFT, padx=6)
        ttk.Button(row1, text="⏹ Stop", command=self.stop).pack(side=tk.LEFT, padx=6)

        ttk.Label(row1, textvariable=self.time_var).pack(side=tk.LEFT, padx=6)

        self.scale = ttk.Scale(
            row1, from_=0, to=1000, orient="horizontal",
            variable=self.scale_var,
            command=self.on_seek_drag
        )
        self.scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.scale.bind("<ButtonPress-1>", self._on_seek_start)
        self.scale.bind("<ButtonRelease-1>", self._on_seek_end)

        ttk.Label(row1, textvariable=self.len_var).pack(side=tk.LEFT, padx=6)

        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(row2, text="⏪10s", width=6, command=lambda: self.skip(-10)).pack(side=tk.LEFT)
        ttk.Button(row2, text="⏪5s", width=6, command=lambda: self.skip(-5)).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(row2, text="5s⏩", width=6, command=lambda: self.skip(+5)).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(row2, text="10s⏩", width=6, command=lambda: self.skip(+10)).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(row2, text="Speed:").pack(side=tk.LEFT, padx=(12, 2))
        self.speed_box = ttk.Combobox(
            row2, textvariable=self.speed_var, values=self.SPEEDS,
            state="readonly", width=6
        )
        self.speed_box.pack(side=tk.LEFT)
        self.speed_box.bind("<<ComboboxSelected>>", self._on_speed_change)

        ttk.Button(row2, text="⛶ Fullscreen", command=self.toggle_fullscreen).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(row2, text="Loop", variable=self.loop_var).pack(side=tk.LEFT, padx=(12, 0))

    # ───────── Playback ─────────
    def load(self, path: str):
        # Opening a file is what's actually slow here (libvlc has to start
        # decoding before it knows anything, and this project's video files
        # live under a OneDrive-synced folder that may need to download the
        # file first) -- show something immediately instead of a dead black
        # canvas; _update() clears it once the media reports a real length.
        self.status_var.set("Loading…")
        media = self.instance.media_new(path)
        self.player.set_media(media)
        self.player.play()
        self.player.set_rate(self.rate)
        # So arrow/space/f/s keys work right away without an extra click.
        self.video.focus_set()

    def play(self):
        self.player.play()

    def pause(self):
        self.player.set_pause(1)

    def stop(self):
        self.player.stop()
        self.scale_var.set(0)
        self.time_var.set("00:00")
        self._exit_fullscreen()

    def _on_canvas_click(self, _event):
        self.video.focus_set()
        self.toggle_play_pause()

    def toggle_play_pause(self):
        if self.player.is_playing():
            self.pause()
        else:
            self.play()

    def skip(self, seconds):
        t = self.player.get_time()
        if t < 0:
            return
        length = self.player.get_length()
        new_t = max(0, t + seconds * 1000)
        if length > 0:
            new_t = min(new_t, length)
        self.player.set_time(new_t)

    # ───────── Speed / Fullscreen / Loop ─────────
    def _on_speed_change(self, _event=None):
        self.rate = float(self.speed_var.get().rstrip("x"))
        self.player.set_rate(self.rate)

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        # libvlc's own set_fullscreen() targets the video output's own window,
        # which does nothing useful once that output has been embedded into a
        # Tkinter canvas via set_hwnd() -- there's no separate top-level window
        # for it to expand. Instead, build our own fullscreen window and
        # re-point libvlc's video output at it (set_hwnd can be called again on
        # an already-playing player); _exit_fullscreen points it back.
        if self.is_fullscreen:
            return
        self.is_fullscreen = True

        self._fs_window = tk.Toplevel(self)
        self._fs_window.attributes("-fullscreen", True)
        self._fs_window.configure(bg="black")
        self._fs_window.protocol("WM_DELETE_WINDOW", self._exit_fullscreen)

        self._fs_canvas = tk.Canvas(self._fs_window, bg="black", highlightthickness=0)
        self._fs_canvas.pack(fill="both", expand=True)
        self._fs_canvas.bind("<Button-1>", self._on_canvas_click)
        self._fs_canvas.bind("<Double-Button-1>", lambda e: self._exit_fullscreen())
        self._fs_canvas.bind("<KeyPress-Escape>", lambda e: self._exit_fullscreen())
        self._fs_canvas.bind("<KeyPress-space>", lambda e: self.toggle_play_pause())
        self._fs_canvas.bind("<KeyPress-f>", lambda e: self.step_frame(+1))
        self._fs_canvas.bind("<KeyPress-s>", lambda e: self.step_frame(-1))
        self._fs_canvas.bind("<KeyPress-Right>", lambda e: self.step_frame(+1))
        self._fs_canvas.bind("<KeyPress-Left>", lambda e: self.step_frame(-1))

        # Reparenting immediately can land mid-transition (the -fullscreen
        # attribute change is handled asynchronously by Windows) and leave the
        # video surface blank; make sure the window is actually mapped at its
        # final fullscreen size first.
        self._fs_window.update()
        self.after(150, self._attach_fullscreen_output)

    def _attach_fullscreen_output(self):
        if not self.is_fullscreen or self._fs_canvas is None:
            return
        self._reattach_output(self._fs_canvas.winfo_id())
        self._fs_canvas.focus_set()

    def _exit_fullscreen(self):
        if not self.is_fullscreen:
            return
        self.is_fullscreen = False
        # Re-point the video output back to the embedded canvas before tearing
        # down the fullscreen window, so libvlc is never left drawing into a
        # HWND that's about to be destroyed.
        self._reattach_output(self.video.winfo_id())
        if self._fs_window is not None:
            self._fs_window.destroy()
            self._fs_window = None
            self._fs_canvas = None
        self.video.focus_set()

    def _reattach_output(self, hwnd):
        # Just calling set_hwnd() on an already-playing instance can leave the
        # video rendering at its old window's pixel size instead of the new
        # window's -- libvlc's output module only measures the target surface
        # when it (re)initializes. stop()/play() forces that reinitialization
        # against the new hwnd's actual current size, so the picture rescales
        # (e.g. filling the whole screen in fullscreen) instead of staying
        # pinned at its old dimensions inside a bigger black window.
        t = self.player.get_time()
        was_playing = self.player.is_playing()
        self.player.stop()
        self.player.set_hwnd(hwnd)
        self.player.play()
        if t >= 0:
            self.player.set_time(t)
        if not was_playing:
            self.player.set_pause(1)

    # ───────── Seek ─────────
    def _on_seek_start(self, _event):
        self.user_seeking = True
        self.was_playing_before_seek = self.player.is_playing()
        # If it was NOT playing, we must force pause after seek
        self.force_pause_after_seek = not self.was_playing_before_seek
        self.player.set_pause(1)

    def _on_seek_end(self, _event):
        self.user_seeking = False
        self._seek_to_scale()

        if self.force_pause_after_seek:
            # VLC sometimes tries to auto-play after a seek
            self.player.set_pause(1)
        else:
            self.player.set_pause(0)

    def _seek_to_scale(self):
        length = self.player.get_length()
        if length > 0:
            t = int(self.scale_var.get() / 1000 * length)
            self.player.set_time(t)

    def on_seek_drag(self, _value):
        if self.user_seeking:
            self._seek_to_scale()

    # ───────── Update loop ─────────
    def _update(self):
        if self._destroyed:
            return

        t = self.player.get_time()
        L = self.player.get_length()

        if t >= 0:
            self.time_var.set(self._fmt(t))
        if L > 0:
            self.len_var.set(self._fmt(L))
            if not self.user_seeking:
                self.scale_var.set(t / L * 1000)
            if self.status_var.get():
                self.status_var.set("")

        # End-of-clip: loop back to the start if enabled, else stop there. Checked two
        # ways -- t crossing a near-end threshold, and libvlc's own Ended state -- since
        # this polls only every 200ms and playback can reach Ended between two polls
        # without ever landing inside a narrower time window (confirmed in testing:
        # a 50ms window was too tight and could be skipped entirely). set_pause(0)
        # doesn't reliably resume once truly Ended, so use play() instead.
        near_end = L > 0 and t >= L - 300
        if near_end or self.player.get_state() == vlc.State.Ended:
            if self.loop_var.get():
                self.player.set_time(0)
                self.player.play()
            else:
                self.player.set_pause(1)

        self._after_id = self.after(200, self._update)

    # ───────── Frame Step ─────────
    def _get_fps(self):
        """Video's real fps, queried once playback has started and cached from then
        on. libvlc reports 0 before a media has begun decoding, so callers should
        tolerate the frame_step_ms fallback until this becomes available."""
        if not self._fps:
            fps = self.player.get_fps()
            if fps and fps > 0:
                self._fps = fps
        return self._fps

    def step_frame(self, direction):
        """
        Step video by one frame forward (f / Right) or backward (s / Left).
        Always leaves the player paused.

        libvlc's own next_frame() would be the frame-accurate way to do this, but it
        is a confirmed no-op against the libvlc build vendored here -- verified against
        both a synthetic clip and a real H.264 file, get_time() never moved after
        repeated next_frame() calls. So both directions instead seek by one frame's
        worth of time, computed from the video's real fps once known (falling back to
        frame_step_ms before that). This is time-based rather than decoder-exact, but
        it is the reliable option and was confirmed accurate to the millisecond in
        both directions in testing.
        """
        self.player.set_pause(1)

        t = self.player.get_time()
        if t < 0:
            return

        fps = self._get_fps()
        step_ms = round(1000 / fps) if fps else self.frame_step_ms
        new_t = max(0, t + direction * step_ms)
        length = self.player.get_length()
        if length > 0:
            new_t = min(new_t, length)
        self.player.set_time(new_t)

    @staticmethod
    def _fmt(ms):
        s = ms // 1000
        return f"{int(s//60):02d}:{int(s%60):02d}"

    # ───────── Cleanup ─────────
    def destroy(self):
        self._destroyed = True
        self.is_fullscreen = False
        if self._fs_window is not None:
            try:
                self._fs_window.destroy()
            except Exception:
                pass
            self._fs_window = None
            self._fs_canvas = None
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self.player.release()
        except Exception:
            pass
        try:
            self.instance.release()
        except Exception:
            pass
        super().destroy()


class VideoBrowserPlayer:
    """Standalone folder-browser app: pick a folder, pick a file from the list, play it
    in an EmbeddedVideoPlayer filling the right-hand pane."""

    def __init__(self, root):
        self.root = root
        self.root.title("Video Browser Player (Stable)")
        self.root.geometry("1400x850")

        self.files = []
        self.current_index = None
        self.folder_var = tk.StringVar()

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Open Folder", command=self.open_folder).pack(side=tk.LEFT)
        ttk.Label(top, textvariable=self.folder_var).pack(side=tk.LEFT, padx=10)

        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main)
        right = ttk.Frame(main)

        # Initial sizes (adjustable by user)
        main.add(left, weight=0)   # file list pane
        main.add(right, weight=1)  # video pane
        left.config(width=250)
        left.pack_propagate(False)

        self.listbox = tk.Listbox(left, height=26)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-1>", self.play_selected)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        xscroll = ttk.Scrollbar(left, orient="horizontal", command=self.listbox.xview)
        xscroll.pack(fill=tk.X)
        self.listbox.config(xscrollcommand=xscroll.set)

        self.player = EmbeddedVideoPlayer(right)
        self.player.pack(fill=tk.BOTH, expand=True)
        # Rebind so a plain "select in list, click Play" (no double-click) loads+plays
        # the current selection, matching this app's original behavior.
        self.player.btn_play.configure(command=self.play_selected)

    # ───────── Folder / selection ─────────
    def open_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return

        self.folder_var.set(folder)
        self.files.clear()
        self.listbox.delete(0, tk.END)

        for f in sorted(os.listdir(folder)):
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS:
                self.files.append(os.path.join(folder, f))
                self.listbox.insert(tk.END, f)

        if not self.files:
            messagebox.showinfo("No videos", "No video files found.")

    def on_select(self, _):
        sel = self.listbox.curselection()
        if sel:
            self.current_index = sel[0]

    # ───────── Playback ─────────
    def play_selected(self, _event=None):
        if self.current_index is None:
            return
        self.player.load(self.files[self.current_index])


def main():
    root = tk.Tk()
    VideoBrowserPlayer(root)
    root.mainloop()

if __name__ == "__main__":
    main()
