"""Publication style for Elsevier journals (e.g. Corrosion Science).

Elsevier artwork guidance:
  * widths: single column 90 mm, 1.5 column 140 mm, double column 190 mm
  * sans-serif font (Arial/Helvetica), text 7-9 pt at final size
  * vector (PDF/EPS) or TIFF at >= 500 dpi for combination art, 1000 dpi for line art
"""
from __future__ import annotations

import matplotlib as mpl
from matplotlib import font_manager

MM = 1 / 25.4  # inch per mm

WIDTHS_MM = {"single": 90, "onehalf": 140, "double": 190}

# Colour-blind-safe categorical palette (validated for deuteranopia, protanopia,
# tritanopia and contrast on white). Assigned in fixed order, never cycled.
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#882255",
           "#B8860B", "#4B3FA0", "#CC3311", "#008B9A"]

# Secondary encoding: every sample also gets its own marker shape, so the
# figure still reads correctly when printed in greyscale.
MARKERS = ["o", "s", "^", "D", "v", "p", "h", "<"]


def pick_font(preferred: str | None = None) -> str:
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in [preferred, "Arial", "Helvetica", "Liberation Sans", "Nimbus Sans", "DejaVu Sans"]:
        if name and name in available:
            return name
    return "DejaVu Sans"


def apply_style(font: str | None = None, size: float = 8.0) -> str:
    font = pick_font(font)
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [font],
        "font.size": size,
        "axes.labelsize": size,
        "axes.titlesize": size,
        "xtick.labelsize": size - 0.5,
        "ytick.labelsize": size - 0.5,
        "legend.fontsize": size - 1,
        "mathtext.fontset": "custom",
        "mathtext.rm": font,
        "mathtext.it": f"{font}:italic",
        "mathtext.bf": f"{font}:bold",
        "mathtext.default": "regular",
        "axes.linewidth": 0.8,
        "axes.edgecolor": "black",
        "axes.labelcolor": "black",
        "xtick.color": "black",
        "ytick.color": "black",
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.major.size": 3.5,
        "ytick.major.size": 3.5,
        "xtick.minor.size": 2,
        "ytick.minor.size": 2,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "xtick.minor.width": 0.6,
        "ytick.minor.width": 0.6,
        "lines.linewidth": 1.0,
        "lines.markersize": 4,
        "legend.frameon": False,
        "legend.handlelength": 1.8,
        "legend.handletextpad": 0.5,
        "legend.borderaxespad": 0.6,
        "legend.labelspacing": 0.3,
        "axes.unicode_minus": True,
        "pdf.fonttype": 42,   # embed TrueType fonts (editable text, required by publishers)
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "figure.dpi": 150,
    })
    return font
