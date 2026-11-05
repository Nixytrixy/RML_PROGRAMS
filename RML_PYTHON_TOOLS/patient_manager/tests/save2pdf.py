"""
save2pdf: Save a matplotlib Figure to PDF with tight cropping.

Usage:
    from save2pdf import save2pdf
    save2pdf("out.pdf", fig, dpi=300)
"""

from pathlib import Path
from typing import Optional
import matplotlib.figure

def save2pdf(pdf_file: str | Path,
             fig: Optional[matplotlib.figure.Figure] = None,
             dpi: int = 150) -> None:
    import matplotlib.pyplot as plt

    pdf_path = Path(pdf_file)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if fig is None:
        fig = plt.gcf()

    # Similar to MATLAB print -dpdf with tight margins
    fig.savefig(str(pdf_path), format="pdf", dpi=dpi, bbox_inches="tight")
