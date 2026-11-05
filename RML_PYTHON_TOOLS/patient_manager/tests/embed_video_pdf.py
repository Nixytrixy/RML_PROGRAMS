"""
embed_video_pdf: Embed a video (e.g. .avi) directly inside a PDF page as a
playable clip, using a Screen annotation + Rendition action (ISO 32000-1
section 13.2) — not a hyperlink and not a file attachment. Clicking the
poster frame on the page plays the video in place.

IMPORTANT: this multimedia mechanism is only honored by Adobe Acrobat /
Adobe Reader. Other viewers (browsers, Preview, SumatraPDF, etc.) will show
the poster image but cannot play the embedded clip — that is a limitation
of the PDF spec's multimedia framework, not of this script.

AVI is not a web-safe codec for Acrobat's player, so the source video is
first transcoded to H.264/MP4 (via a pip-installable ffmpeg, no system
install required).

Usage (CLI):
    python embed_video_pdf.py input.avi -o output.pdf [--autoplay]
Usage (no args): opens file pickers, matching this folder's other tools.

Usage (from another script):
    from embed_video_pdf import embed_avi_as_pdf
    embed_avi_as_pdf("clip.avi", "clip.pdf", autoplay=False)
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Optional

import cv2
import pikepdf
from pikepdf import Dictionary, Name, String


def name():
    return "Embed Video In PDF"


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def convert_to_mp4(video_path: str | Path, mp4_path: str | Path, crf: int = 23) -> Path:
    """Transcode any OpenCV/ffmpeg-readable video to H.264/AAC MP4 (Acrobat-compatible)."""
    video_path = Path(video_path)
    mp4_path = Path(mp4_path)
    mp4_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        _ffmpeg_exe(), "-y", "-i", str(video_path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf),
        "-movflags", "+faststart",
        "-an",
        str(mp4_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not mp4_path.exists():
        raise RuntimeError(f"ffmpeg failed to convert {video_path} -> {mp4_path}:\n{result.stderr}")
    return mp4_path


def extract_poster_frame(video_path: str | Path, poster_path: str | Path,
                          at_seconds: float = 0.0) -> tuple[Path, int, int]:
    """Grab one frame from the video and save it as a JPEG poster image.
    Returns (poster_path, width, height)."""
    video_path = Path(video_path)
    poster_path = Path(poster_path)
    poster_path.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for poster frame: {video_path}")
    try:
        if at_seconds > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, at_seconds * 1000.0)
        ok, frame = cap.read()
        if not ok:
            # Fall back to the first frame if seeking failed (e.g. very short clip).
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Could not read a frame from: {video_path}")
        h, w = frame.shape[:2]
        cv2.imwrite(str(poster_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return poster_path, w, h
    finally:
        cap.release()


def build_video_pdf(mp4_path: str | Path, poster_path: str | Path, poster_size: tuple[int, int],
                     output_pdf: str | Path, autoplay: bool = False,
                     margin: float = 36.0) -> Path:
    """Build a one-page PDF with the given MP4 embedded as a playable Screen annotation,
    shown at its poster image's aspect ratio, centered on a Letter page."""
    mp4_path = Path(mp4_path)
    poster_path = Path(poster_path)
    output_pdf = Path(output_pdf)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = 612.0, 792.0  # Letter, points
    poster_w, poster_h = poster_size
    avail_w, avail_h = page_w - 2 * margin, page_h - 2 * margin
    scale = min(avail_w / poster_w, avail_h / poster_h, 1.0)
    draw_w, draw_h = poster_w * scale, poster_h * scale
    rect_x0 = (page_w - draw_w) / 2.0
    rect_y0 = (page_h - draw_h) / 2.0
    rect = [rect_x0, rect_y0, rect_x0 + draw_w, rect_y0 + draw_h]

    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(page_w, page_h))

    # --- Poster image XObject (JPEG bytes embedded directly via DCTDecode) ---
    poster_bytes = poster_path.read_bytes()
    img_obj = pikepdf.Stream(pdf, poster_bytes)
    img_obj.Type = Name.XObject
    img_obj.Subtype = Name.Image
    img_obj.Width = poster_w
    img_obj.Height = poster_h
    img_obj.ColorSpace = Name.DeviceRGB
    img_obj.BitsPerComponent = 8
    img_obj.Filter = Name.DCTDecode
    img_ref = pdf.make_indirect(img_obj)

    # --- Appearance stream (Form XObject) that draws the poster at annotation size ---
    ap_content = f"q {draw_w:.2f} 0 0 {draw_h:.2f} 0 0 cm /Im0 Do Q".encode("latin-1")
    ap_stream = pikepdf.Stream(pdf, ap_content)
    ap_stream.Type = Name.XObject
    ap_stream.Subtype = Name.Form
    ap_stream.BBox = [0, 0, draw_w, draw_h]
    ap_stream.Resources = Dictionary(XObject=Dictionary(Im0=img_ref))
    ap_ref = pdf.make_indirect(ap_stream)

    # --- Embedded MP4 data as a real embedded file stream ---
    mp4_bytes = mp4_path.read_bytes()
    ef_stream = pikepdf.Stream(pdf, mp4_bytes)
    ef_stream.Type = Name.EmbeddedFile
    ef_stream.Subtype = Name("/video#2Fmp4")  # "video/mp4", '/' escaped per PDF name syntax
    ef_stream.Params = Dictionary(Size=len(mp4_bytes))
    ef_ref = pdf.make_indirect(ef_stream)

    filespec = pdf.make_indirect(Dictionary(
        Type=Name.Filespec,
        F=String(mp4_path.name),
        UF=String(mp4_path.name),
        EF=Dictionary(F=ef_ref),
    ))

    media_clip = pdf.make_indirect(Dictionary(
        Type=Name.MediaClip,
        S=Name.MCD,
        CT=String("video/mp4"),
        D=filespec,
        P=Dictionary(TF=String("TEMPACCESS")),
    ))

    play_params = Dictionary(
        Type=Name.MediaPlayParams,
        V=150,
        C=True,   # show Acrobat's built-in playback controls
        A=autoplay,
        RC=1,
    )

    screen_params = Dictionary(
        Type=Name.MediaScreenParams,
        W=3,  # play within the Screen annotation's own rectangle
    )

    rendition = pdf.make_indirect(Dictionary(
        Type=Name.Rendition,
        S=Name.MR,
        C=media_clip,
        P=play_params,
        MH=screen_params,
    ))

    # Screen annotation is created first (as an indirect object) so its Rendition
    # action can reference the annotation back via /AN.
    screen_annot = pdf.make_indirect(Dictionary(
        Type=Name.Annot,
        Subtype=Name.Screen,
        Rect=rect,
        P=page.obj,
        F=4,  # Print flag off would hide it; 4 = Print (kept visible/printable)
        AP=Dictionary(N=ap_ref),
    ))

    rendition_action = Dictionary(
        Type=Name.Action,
        S=Name.Rendition,
        R=rendition,
        OP=0,  # 0 = play
        AN=screen_annot,
    )
    screen_annot.A = rendition_action

    if autoplay:
        # Play automatically once the page becomes visible; stop when it isn't.
        stop_action = Dictionary(
            Type=Name.Action,
            S=Name.Rendition,
            R=rendition,
            OP=1,  # 1 = stop
            AN=screen_annot,
        )
        screen_annot.AA = Dictionary(PV=rendition_action, PI=stop_action)

    page.obj.Annots = pdf.make_indirect([screen_annot])

    pdf.save(output_pdf)
    return output_pdf


def embed_avi_as_pdf(avi_path: str | Path, output_pdf: Optional[str | Path] = None,
                      autoplay: bool = False, poster_at_seconds: float = 0.0,
                      keep_intermediate: bool = False) -> Path:
    """End-to-end: AVI -> H.264 MP4 -> poster frame -> single-page PDF with the
    video embedded as a playable (Adobe Acrobat/Reader only) Screen annotation."""
    avi_path = Path(avi_path)
    if output_pdf is None:
        output_pdf = avi_path.with_suffix(".pdf")
    output_pdf = Path(output_pdf)

    work_dir = output_pdf.parent / f".{avi_path.stem}_embed_tmp"
    work_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = work_dir / f"{avi_path.stem}.mp4"
    poster_path = work_dir / f"{avi_path.stem}_poster.jpg"

    try:
        print(f"Converting to H.264 MP4: {avi_path.name} -> {mp4_path.name}")
        convert_to_mp4(avi_path, mp4_path)

        print("Extracting poster frame...")
        _, poster_w, poster_h = extract_poster_frame(avi_path, poster_path, at_seconds=poster_at_seconds)

        print(f"Building PDF: {output_pdf}")
        build_video_pdf(mp4_path, poster_path, (poster_w, poster_h), output_pdf, autoplay=autoplay)
    finally:
        if not keep_intermediate:
            for f in (mp4_path, poster_path):
                if f.exists():
                    f.unlink()
            try:
                work_dir.rmdir()
            except OSError:
                pass

    print(f"Done: {output_pdf}")
    return output_pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="Path to the source .avi (or other video) file")
    parser.add_argument("-o", "--output", help="Output PDF path (default: same name, .pdf)")
    parser.add_argument("--autoplay", action="store_true", help="Play automatically when the page opens")
    parser.add_argument("--poster-at", type=float, default=0.0, help="Seconds into the video to grab the poster frame")
    parser.add_argument("--keep-intermediate", action="store_true", help="Keep the converted MP4/poster files")
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output

    if not input_path:
        from tkinter import Tk
        from tkinter.filedialog import askopenfilename, asksaveasfilename
        root = Tk()
        root.withdraw()
        input_path = askopenfilename(title="Select video file to embed",
                                      filetypes=[("Video files", "*.avi *.mp4 *.mov *.mkv"), ("All files", "*.*")])
        if not input_path:
            print("No file selected. Exiting.")
            return
        if not output_path:
            output_path = asksaveasfilename(title="Save PDF as", defaultextension=".pdf",
                                             filetypes=[("PDF files", "*.pdf")],
                                             initialfile=str(Path(input_path).with_suffix(".pdf").name))
            if not output_path:
                print("No output selected. Exiting.")
                return

    embed_avi_as_pdf(input_path, output_path, autoplay=args.autoplay, poster_at_seconds=args.poster_at,
                      keep_intermediate=args.keep_intermediate)


if __name__ == "__main__":
    main()
