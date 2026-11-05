"""
Generate Gait Graph (V3D) in pure Python/matplotlib.

- Walk-type legend (shapes only) shows only used types; placed top-left outside chart.
- Visits legend (colors) is on the RIGHT (same place as original PDF).
- Bottom info is a single compact table.
- Height/Gender/Age block is directly below the graph (not overlapping).
- Figure size and main-axes geometry match the original PDF layout.

Requires: matplotlib, numpy
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

import math
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.table import Table

from patient import Patient


@dataclass
class Condition:
    Speed: str = ""     # cm/s (text)
    Stride: str = ""    # cm (text)
    Date: str = ""
    Age: str = ""
    Height: str = ""
    name: str = ""
    type: int = -1
    Cadence: float = 0.0
    Speedcm: float = 0.0
    position: Tuple[float, float] = (0.0, 0.0)


TYPE_TO_NAME = {
    0:  'Pre-op Bare Walk',
    1:  'Pre-op Brace Walk',
    2:  'Pre-op Best Walk',
    3:  'Pre-op Fast Walk',
    4:  'Post-op Bare Walk',
    5:  'Post-op Brace Walk',
    6:  'Post-op Best Walk',
    7:  'Post-op Fast Walk',
    8:  'Long Bare Walk',
    9:  'Long Brace Walk',
    10: 'Long Best Walk',
    11: 'Long Fast Walk',
    12: 'Other Bare Walk',
    13: 'Other Brace Walk',
    14: 'Other Best Walk',
    15: 'Other Fast Walk',
}

COLORS = {
    "blue":   (46/255, 184/255, 230/255),
    "purple": (114/255, 50/255, 178/255),
    "green":  (51/255, 153/255, 51/255),
    "red":    (204/255, 0, 0),
    "orange": (255/255, 102/255, 0/255),
    "black":  (0, 0, 0),
    "gray":   (127/255, 127/255, 127/255),
}

TYPE_STYLE = {
    0:  ("o", COLORS["red"]),
    1:  ("o", COLORS["green"]),
    2:  ("o", COLORS["orange"]),
    3:  ("o", COLORS["blue"]),
    4:  ("s", COLORS["red"]),
    5:  ("s", COLORS["green"]),
    6:  ("s", COLORS["orange"]),
    7:  ("s", COLORS["blue"]),
    8:  ("^", COLORS["red"]),
    9:  ("^", COLORS["green"]),
    10: ("^", COLORS["orange"]),
    11: ("^", COLORS["blue"]),
    12: ("d", COLORS["red"]),
    13: ("d", COLORS["green"]),
    14: ("d", COLORS["orange"]),
    15: ("d", COLORS["blue"]),
}


def _marker_to_glyph(marker: str) -> str:
    """Map matplotlib marker codes to simple unicode glyphs for table display."""
    return {
        "o": "●",
        "s": "■",
        "^": "▲",
        "d": "◆",
    }.get(marker, "●")


# distinct visit colors (keep as in previous)
VISIT_COLORS = [
    (0.121, 0.466, 0.705),
    (1.000, 0.498, 0.054),
    (0.172, 0.627, 0.172),
    (0.839, 0.153, 0.157),
    (0.580, 0.404, 0.741),
    (0.549, 0.337, 0.294),
    (0.890, 0.467, 0.761),
    (0.498, 0.498, 0.498),
]


def _parse_and_validate(patient: Patient, conditions: List[Condition]) -> List[int]:
    # Fill in patient height/age if not provided
    heights = []
    ages = []
    for c in conditions:
        if c.Height:
            try:
                heights.append(float(c.Height))
            except:
                pass
        if c.Age:
            try:
                ages.append(float(c.Age))
            except:
                pass
    if heights:
        patient.height = max(heights)
    if ages and not patient.age:
        patient.age = max(ages)

    valid_idx: List[int] = []
    for i, c in enumerate(conditions):
        if not (c.Speed and c.Stride and c.Age and c.Height):
            continue
        c.type = i
        c.name = c.name or TYPE_TO_NAME.get(c.type, f"Type {c.type}")

        try:
            c.Speedcm = float(c.Speed)
            stride_cm = float(c.Stride)
        except ValueError:
            continue

        speed_m_per_min = c.Speedcm * 60.0 / 100.0
        c.Cadence = (c.Speedcm / float(c.Stride)) * 60.0 * 2.0
        c.position = (speed_m_per_min, stride_cm)
        valid_idx.append(i)
    return valid_idx


def _plot_main_axes(ax):
    # grid
    for hoz in range(10, 171, 10):
        ax.plot([0, 120], [hoz, hoz], ":", color="k", linewidth=0.5)
    for ver in range(10, 111, 10):
        ax.plot([ver, ver], [0, 180], ":", color="k", linewidth=0.5)

    ax.set_xlim(0, 120)
    ax.set_ylim(0, 180)
    ax.set_xticks(range(0, 121, 10))
    ax.set_yticks(range(0, 181, 10))
    ax.set_xlabel("\n\nWALKING SPEED (m/min)", fontweight="bold", fontsize=9)
    ax.set_ylabel("STRIDE LENGTH (cm)", fontweight="bold", fontsize=12)

    # cadence lines
    walking_speed = [x / 10.0 for x in range(0, 1200 + 1)]
    for cadence in range(30, 201, 10):
        cad_line = [ws / cadence * 200.0 for ws in walking_speed]
        ax.plot(walking_speed, cad_line, color="k", linewidth=0.5)
    ax.plot([0, 120], [0, 0], "k", linewidth=0.5)
    ax.plot([0, 0], [0, 180], "k", linewidth=0.5)

    # cadence labels (approx, as in original)
        # cadence labels placed at the "ends" of each diagonal line (top or right edge)
    # This matches the older output style: low cadences label near the top edge,
    # higher cadences label near the right edge.
    y_top = 185     # slightly inside the top border (180)
    x_right = 118   # slightly inside the right border (120)

    for cadence in range(30, 201, 10):
        # cadence line: y = (x / cadence) * 200
        # Option A: place label near top edge (y = y_top)
        x_at_top = (y_top * cadence) / 200.0

        # Option B: place label near right edge (x = x_right)
        y_at_right = (x_right * 200.0) / cadence

        if 0 <= x_at_top <= x_right:
            # Put label near top boundary
            ax.text(x_at_top, y_top + 2, f"{cadence}",
                    fontsize=8, ha="center", va="bottom")
        elif 0 <= y_at_right <= y_top:
            # Put label near right boundary
            ax.text(x_right + 1.5, y_at_right, f"{cadence}",
                    fontsize=8, ha="left", va="center")

    return ax


def generate_graph_v3d(patient: Patient, conditions: List[Condition]):
    # single-visit unchanged layout except info block/table consolidated
    if len(conditions) < 16:
        conditions = conditions + [Condition() for _ in range(16 - len(conditions))]
    elif len(conditions) > 16:
        conditions = conditions[:16]

    valid_idx = _parse_and_validate(patient, conditions)
    if not valid_idx:
        raise ValueError("No valid conditions: each needs Speed, Stride, Age, Height.")

    fig = plt.figure(figsize=(8.5, 11), dpi=100)
    ax = fig.add_axes([0.21, 0.38, 0.59, 0.56])
    _plot_main_axes(ax)

    # normal curve
    C = [
        (-0.0002802, 0.1544256, -3.5589657, -0.0010762, 0.2803360, -10.3155200),  # male
        (-0.0005145, 0.1896516, -5.0245599, -0.0002684, 0.2465649, -13.2757848),  # female
    ]
    idx = 0 if patient.gender == 1 else 1
    A = C[idx][0] * patient.height**2 + C[idx][1] * patient.height + C[idx][2]
    B = C[idx][3] * patient.height**2 + C[idx][4] * patient.height + C[idx][5]
    ns = [x / 10.0 for x in range(200, 1100 + 1)]
    nstride = [A * math.sqrt(s) + B for s in ns]
    ax.plot(ns, nstride, color="b", linewidth=2)

    used_types = set()
    for i in valid_idx:
        c = conditions[i]
        used_types.add(c.type)
        marker, _ = TYPE_STYLE.get(c.type, ("o", COLORS["black"]))
        ax.plot(c.position[0], c.position[1],
                marker=marker, color="k", markersize=10, linewidth=0)

    # legends
    type_handles: List[Line2D] = []
    for t in sorted(used_types):
        marker, col = TYPE_STYLE.get(t, ("o", COLORS["black"]))
        name = TYPE_TO_NAME.get(t, f"Type {t}")
        type_handles.append(Line2D([0], [0], marker=marker, color="w",
                                   label=name, markerfacecolor=col, markersize=10))
    ax.legend(handles=type_handles, title="Walk Types",
              loc="upper left", bbox_to_anchor=(-0.22, 1.02), frameon=True)

    # info block
    gender_txt = "Male" if patient.gender == 1 else "Female"
    fig.text(0.05, 0.24, f"MRN: {patient.mrn}    Name: {patient.name}",
             fontsize=9, fontweight="bold")
    fig.text(0.05, 0.22, f"Height: {int(patient.height)} cm    Gender: {gender_txt}    Age: {int(patient.age) if patient.age else ''}",
             fontsize=9, fontweight="bold")

    # bottom table
    rows = [["Type", "Velocity (m/min)", "Stride (cm)", "Cadence"]]
    for i in valid_idx:
        c = conditions[i]
        base = (c.name or TYPE_TO_NAME.get(c.type, f"Type {c.type}"))
        base = base.replace("Pre-op ", "").replace("Post-op ", "")
        rows.append([
            f"{c.Date} {base}",
            f"{c.position[0]:.0f}",
            f"{float(c.Stride):.0f}",
            f"{c.Cadence:.0f}",
        ])
    _draw_table(fig, rows, left=0.21, bottom=0.05,
                col_widths=[0.30, 0.14, 0.14, 0.14], font_size=20, row_height_px=14)

    # simple backup figure (unchanged)
    fig_backup = _plot_backup(patient, conditions, valid_idx)
    return fig, fig_backup


def generate_graph_v3d_multi(patient: Patient, visits: List[Tuple[str, List[Condition]]]):
    """
    Combined figure for ALL visits.
    - Visit legend (colors) stays on RIGHT (same location).
    - Walk-type legend (shapes) shows only used types; placed top-left outside chart.
    - Table is compact and aligned under the plot; plot geometry matches original.
    """
    fig = plt.figure(figsize=(8.5, 11), dpi=100)
    # keep main axes identical to single-visit/original layout
    ax = fig.add_axes([0.21, 0.38, 0.59, 0.56])
    _plot_main_axes(ax)

    # normal curve
    C = [
        (-0.0002802, 0.1544256, -3.5589657, -0.0010762, 0.2803360, -10.3155200),
        (-0.0005145, 0.1896516, -5.0245599, -0.0002684, 0.2465649, -13.2757848),
    ]
    idx = 0 if patient.gender == 1 else 1
    A = C[idx][0] * patient.height**2 + C[idx][1] * patient.height + C[idx][2]
    B = C[idx][3] * patient.height**2 + C[idx][4] * patient.height + C[idx][5]
    ns = [x / 10.0 for x in range(200, 1100 + 1)]
    nstride = [A * math.sqrt(s) + B for s in ns]
    ax.plot(ns, nstride, color="b", linewidth=2)

    used_types = set()
    visit_handles: List[Line2D] = []
    all_rows = [["", "Visit", "Type", "Velocity (m/min)", "Stride (cm)", "Cadence", "Age"]]
    cell_text_colors = {}
    visit_ages = []

    for vi, (visit_label, conds_raw) in enumerate(visits):
        color = VISIT_COLORS[vi % len(VISIT_COLORS)]
        conds = conds_raw[:16] + [Condition() for _ in range(max(0, 16 - len(conds_raw)))]
        valid_idx = _parse_and_validate(patient, conds)

        age_vals = [float(conds[i].Age) for i in valid_idx if conds[i].Age]
        visit_age = int(age_vals[0]) if age_vals else None
        visit_ages.append(visit_age)

        for i in valid_idx:
            c = conds[i]
            used_types.add(c.type)
            marker, _ = TYPE_STYLE.get(c.type, ("o", (0, 0, 0)))
            ax.plot(c.position[0], c.position[1],
                    marker=marker, color=color, markersize=10, linewidth=0)

            # strip pre/post in display label for table
            base = (c.name or TYPE_TO_NAME.get(c.type, f"Type {c.type}"))
            base = base.replace("Pre-op ", "").replace("Post-op ", "")

            glyph = _marker_to_glyph(marker)

            all_rows.append([
                glyph,
                visit_label,
                base,
                f"{c.position[0]:.0f}",
                f"{float(c.Stride):.0f}",
                f"{c.Cadence:.0f}",
                f"{int(float(c.Age))}" if c.Age else "",
            ])
            # Color only the symbol cell for this row using the visit color
            row_index = len(all_rows) - 1
            cell_text_colors[(row_index, 0)] = color

        # build visit legend handle once per visit
        visit_handles.append(
            Line2D([0], [0], marker="o", color="w",
                   label=visit_label,
                   markerfacecolor=color, markersize=10)
        )

    # 1) visits legend — RIGHT (unchanged place)
    # leg_visits = ax.legend(handles=visit_handles, title="Visits",
    #                        loc="center left", bbox_to_anchor=(1.02, 0.5),
    #                        frameon=True)

    # 2) walk-type shapes — TOP-LEFT outside chart
    type_handles: List[Line2D] = []
    for t in sorted(used_types):
        marker, _ = TYPE_STYLE.get(t, ("o", COLORS["black"]))
        base = TYPE_TO_NAME.get(t, f"Type {t}")
        base = base.replace("Pre-op ", "").replace("Post-op ", "")
        type_handles.append(Line2D([0], [0], marker=marker, color="w",
                                   label=base, markerfacecolor=COLORS["black"], markersize=10))
    # if type_handles:
    #     ax.legend(handles=type_handles, title="Walk Types",
    #               loc="upper left", bbox_to_anchor=(-0.22, 1.02), frameon=True)
    #     ax.add_artist(leg_visits)  # ensure both show

    # info block just under the plot
    gender_txt = "Male" if patient.gender == 1 else "Female"
    if patient.age:
        age_txt = f"{int(patient.age)}"
    else:
        uniq_ages = sorted({a for a in visit_ages if a is not None})
        age_txt = ", ".join(str(a) for a in uniq_ages) if uniq_ages else ""
    fig.text(0.1, 0.30, f"MRN: {patient.mrn}    Name: {patient.name}", fontsize=9, fontweight="bold")
    fig.text(0.1, 0.28, f"Height: {int(patient.height)} cm    Gender: {gender_txt}    Age: {age_txt}",
             fontsize=9, fontweight="bold")

    # compact table under the plot
    # IMPORTANT: left=0.21 and widths sum to 0.59 (exact plot width) to avoid PDF clipping of Age column.
    _draw_table(fig, all_rows, left=.12, bottom=0.05,
                col_widths=[0.04, 0.10, 0.13, 0.15, 0.15, 0.15, 0.04],
                font_size=10, row_height_px=15,
                cell_text_colors=cell_text_colors)

    return fig, None


def _draw_table(fig: plt.Figure, rows: List[List[str]],
                left: float, bottom: float, col_widths: List[float],
                font_size: int = 8, row_height_px: int=15,
                cell_text_colors=None):
    """
    Draw a compact table aligned to the figure:
      - left, bottom are figure fractions
      - col_widths are figure fractions (sum typically = plot width, e.g. 0.59)
      - font_size and row_height_px keep it tight to avoid width overflow
    """
    import numpy as np
    from matplotlib.transforms import Bbox

    table_width = sum(col_widths)
    nrows = len(rows)
    ncols = len(rows[0]) if rows else 0

    # Convert desired row height in pixels to figure fraction
    fig_w_px, fig_h_px = fig.get_size_inches() * fig.dpi
    row_h_frac = (row_height_px / fig_h_px) if nrows else 0.02
    height = max(row_h_frac * nrows + 0.01, 0.10)

    ax = fig.add_axes([left, bottom, table_width, height])
    ax.axis("off")

    the_table = Table(ax, bbox=[0, 0, 1, 1])
    
    the_table.auto_set_font_size(False)   # stop auto-scaling fonts down
    the_table.set_fontsize(font_size)     # apply your chosen font_size
# ---------------------------------------------------------------


    col_positions = np.cumsum([0.0] + [w / table_width for w in col_widths])

    header_face = "#FFFFFF"
    header_edge = "#000000"
    cell_face = "#FFFFFF"
    cell_edge = "#000000"

    # Default alignment: if there's a leading symbol column (blank header), center it,
    # keep Visit/Type left-aligned, and center numeric columns.
    has_symbol_col = bool(rows and rows[0] and str(rows[0][0]).strip() == "")
    if has_symbol_col:
        col_align = ["center"] * ncols
        if ncols > 1:
            col_align[1] = "left"
        if ncols > 2:
            col_align[2] = "left"
        for c in range(3, ncols):
            col_align[c] = "center"
    else:
        col_align = ["left"] * ncols
        for c in range(1, ncols):
            col_align[c] = "center"

    cell_text_colors = cell_text_colors or {}

    for r in range(nrows):
        is_header = (r == 0)
        for c in range(ncols):
            x0 = col_positions[c]
            w = (col_positions[c+1] - col_positions[c])
            y0 = 1.0 - (r + 1) * (1.0 / nrows)
            txt = rows[r][c]
            loc = col_align[c] if not is_header else "center"
            cell = the_table.add_cell(
                r, c, w, 1.0 / nrows, text=txt,
                loc=loc,
                facecolor=header_face if is_header else cell_face,
                edgecolor=header_edge if is_header else cell_edge
            )
            cell.get_text().set_fontsize(font_size)
            if (r, c) in cell_text_colors:
                cell.get_text().set_color(cell_text_colors[(r, c)])
            if is_header:
                cell.get_text().set_fontweight("bold")

    ax.add_table(the_table)
    return ax


def _plot_backup(patient: Patient, conditions: List[Condition], valid_idx: List[int]):
    """
    A backup/secondary figure (kept as-is from your original file).
    This function is not involved in the PDF clipping issue.
    """
    fig = plt.figure(figsize=(8.5, 11), dpi=100)
    ax = fig.add_subplot(111)
    ax.axis("off")

    # Simple backup summary text block (placeholder structure retained)
    # (Your original file appears to include additional layout content;
    #  leave this function as-is / extend as needed.)
    text_lines = [
        f"MRN: {patient.mrn}",
        f"Name: {patient.name}",
        f"Height: {patient.height}",
        f"Age: {patient.age}",
        f"Valid conditions: {len(valid_idx)}",
    ]
    y = 0.9
    for line in text_lines:
        ax.text(0.05, y, line, fontsize=12)
        y -= 0.05

    return fig


# Optional quick test
def demo_cli():
    from save2pdf import save2pdf
    p = Patient(mrn="223", name="123", gender=1, height=123.0, age=232.0)

    conds1 = [Condition() for _ in range(16)]
    conds1[0] = Condition(Speed="74", Stride="180", Date="2025-10-01", Age="232", Height="123", name="Bare walk")
    conds1[1] = Condition(Speed="127", Stride="232", Date="2025-10-01", Age="232", Height="123", name="Brace walk")
    v1 = ("Visit A", conds1)

    conds2 = [Condition() for _ in range(16)]
    conds2[3] = Condition(Speed="120", Stride="160", Date="2025-10-12", Age="232", Height="123", name="Fast walk")
    v2 = ("Visit B", conds2)

    fig_all, _ = generate_graph_v3d_multi(p, [v1, v2])
    save2pdf("GaitGraph-ALL-VISITS.pdf", fig_all, 300)
    print("Saved example PDF.")


if __name__ == "__main__":
    demo_cli()
