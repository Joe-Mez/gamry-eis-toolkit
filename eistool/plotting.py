"""Nyquist and Bode figures for publication."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import LogLocator, MaxNLocator, NullFormatter  # noqa: E402

from .style import MM, WIDTHS_MM  # noqa: E402


@dataclass
class PlotSeries:
    label: str
    color: str
    marker: str
    freq: np.ndarray
    z: np.ndarray                      # complex, possibly area-normalised
    fit_freq: np.ndarray | None = None
    fit_z: np.ndarray | None = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_PREFIX = [(1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, "")]


def _scale_for(maxval: float, allow_prefix: bool = True):
    if not allow_prefix:
        return 1.0, ""
    for f, p in _PREFIX:
        if maxval >= 2 * f:
            return f, p
    return 1.0, ""


def _unit(prefix: str, normalised: bool) -> str:
    return prefix + r"$\Omega$" + (r" cm$^{2}$" if normalised else "")


def _every(n_points: int, step) -> list[int]:
    """Indices for thinned markers that always keep the first and last points."""
    step = max(int(step or 1), 1)
    idx = list(range(0, n_points, step))
    if idx[-1] != n_points - 1:
        if n_points - 1 - idx[-1] < max(step // 2, 1) and len(idx) > 1:
            idx[-1] = n_points - 1   # replace a too-close neighbour instead of crowding
        else:
            idx.append(n_points - 1)
    return idx


def _data_kw(s: PlotSeries, filled: bool, ms: float, markevery):
    return dict(linestyle="none", marker=s.marker, markersize=ms,
                markevery=_every(len(s.freq), markevery),
                markeredgewidth=0.8, markeredgecolor=s.color,
                markerfacecolor=s.color if filled else "white", color=s.color, zorder=3)


def auto_markevery(series, opts, axis_mm: float) -> int:
    me = opts.get("marker_every", "auto")
    if me not in (None, "auto"):
        return max(int(me), 1)
    ms_mm = opts.get("marker_size", 4) * 25.4 / 72
    fmin = min(s.freq.min() for s in series)
    fmax = max(s.freq.max() for s in series)
    decades = max(np.log10(fmax / fmin), 1e-9)
    npts = max(len(s.freq) for s in series)
    pts_per_dec = (npts - 1) / decades
    spacing = axis_mm / max(np.ceil(decades), 1) / pts_per_dec
    return max(1, int(np.ceil(1.15 * ms_mm / spacing)))


def _mirror_ticks(ax, x=True, y=True):
    ax.tick_params(which="both", top=x, right=y)


# ---------------------------------------------------------------------------
# Nyquist
# ---------------------------------------------------------------------------

def draw_nyquist(ax, series: list[PlotSeries], *, normalised: bool, opts: dict):
    ms = opts.get("marker_size", 4)
    me = opts.get("_markevery", 1)
    zmax_opt = opts.get("nyquist_max")

    allr = np.concatenate([s.z.real for s in series])
    alli = np.concatenate([-s.z.imag for s in series])
    top_raw = float(zmax_opt) if zmax_opt else max(allr.max(), alli.max()) * 1.04
    fac, pre = _scale_for(top_raw, opts.get("unit_prefix", True))

    for s in series:
        ax.plot(s.z.real / fac, -s.z.imag / fac, **_data_kw(s, True, ms, me), label=s.label)
        if s.fit_z is not None:
            ax.plot(s.fit_z.real / fac, -s.fit_z.imag / fac, "-", color=s.color,
                    lw=opts.get("fit_linewidth", 1.0), zorder=4)

    # Orthonormal axes: same limits, same ticks, equal aspect ratio.
    # Extend below zero only for real features (inductive loops, negative Z'), not noise.
    top = top_raw / fac
    thr = -0.03 * top
    xlo = allr.min() / fac if (allr.min() / fac < thr and not zmax_opt) else 0.0
    ylo = alli.min() / fac if (alli.min() / fac < thr and not zmax_opt) else 0.0
    lo = min(xlo, ylo, 0.0)
    loc = MaxNLocator(nbins=opts.get("nyquist_nticks", 5), steps=[1, 2, 2.5, 5, 10])
    ticks = loc.tick_values(lo, top)
    step = ticks[1] - ticks[0]
    top = float(np.ceil(top / step - 1e-9) * step)
    xmin = float(np.floor(xlo / step) * step)
    ymin = float(np.floor(ylo / step) * step)
    ax.set_xlim(xmin, top)
    ax.set_ylim(ymin, top)
    ticks = np.arange(min(xmin, ymin), top + step / 2, step)
    ax.set_xticks(ticks[ticks >= xmin - 1e-9 * step])
    ax.set_yticks(ticks[ticks >= ymin - 1e-9 * step])
    ax.set_aspect("equal", adjustable="box")
    _mirror_ticks(ax)

    ax.set_xlabel(r"$\mathit{Z}$' (" + _unit(pre, normalised) + ")")
    ax.set_ylabel(r"$-\mathit{Z}$'' (" + _unit(pre, normalised) + ")")


# ---------------------------------------------------------------------------
# Bode (modulus and phase on the same graph)
# ---------------------------------------------------------------------------

def draw_bode(ax, series: list[PlotSeries], *, normalised: bool, opts: dict):
    ms = opts.get("marker_size", 4)
    me = opts.get("_markevery", 1)
    ax2 = ax.twinx()
    for s in series:
        ax.plot(s.freq, np.abs(s.z), **_data_kw(s, True, ms, me), label=s.label)
        ax2.plot(s.freq, -np.degrees(np.angle(s.z)), **_data_kw(s, False, ms, me))
        if s.fit_z is not None:
            lw = opts.get("fit_linewidth", 1.0)
            ax.plot(s.fit_freq, np.abs(s.fit_z), "-", color=s.color, lw=lw, zorder=4)
            ax2.plot(s.fit_freq, -np.degrees(np.angle(s.fit_z)), "-", color=s.color, lw=lw, zorder=4)

    ax.set_xscale("log")
    ax.set_yscale("log")
    for a, axis in ((ax, ax.xaxis), (ax, ax.yaxis)):
        axis.set_major_locator(LogLocator(base=10, numticks=15))
        axis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10), numticks=15))
        axis.set_minor_formatter(NullFormatter())

    fmin = min(s.freq.min() for s in series)
    fmax = max(s.freq.max() for s in series)
    ax.set_xlim(10 ** np.floor(np.log10(fmin) + 1e-9), 10 ** np.ceil(np.log10(fmax) - 1e-9))
    zmin = min(np.abs(s.z).min() for s in series)
    zmax = max(np.abs(s.z).max() for s in series)
    ax.set_ylim(10 ** np.floor(np.log10(zmin)), 10 ** np.ceil(np.log10(zmax)))

    pmax = max(np.nanmax(-np.degrees(np.angle(s.z))) for s in series)
    pmin = min(np.nanmin(-np.degrees(np.angle(s.z))) for s in series)
    if pmax > 90:
        top = float(np.ceil(pmax / 10) * 10 + 10)
    elif pmax > 60:
        top = 90.0
    else:
        top = float(np.ceil(pmax / 10) * 10 + 10)
    bot = 0 if pmin >= -2 else float(np.floor(pmin / 10) * 10)
    ax2.set_ylim(bot, top)
    ax2.yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 1.5, 2, 3, 5, 10]))
    ax2.tick_params(which="both", direction="in")
    ax.tick_params(which="both", top=True, right=False)

    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel(r"|$\mathit{Z}$| (" + _unit("", normalised) + ")")
    ax2.set_ylabel("−Phase angle (°)")
    return ax2


def bode_key_handles():
    return [
        Line2D([], [], ls="none", marker="o", ms=4, mfc="black", mec="black", label=r"|$\mathit{Z}$|"),
        Line2D([], [], ls="none", marker="o", ms=4, mfc="white", mec="black", mew=0.8,
               label="−Phase"),
        Line2D([], [], ls="-", color="black", lw=1.0, label="Fit"),
    ]


def sample_handles(series: list[PlotSeries], with_line: bool, ms: float = 4):
    return [Line2D([], [], ls="-" if with_line else "none", color=s.color, lw=1.0,
                   marker=s.marker, ms=ms, mfc=s.color, mec=s.color, label=s.label)
            for s in series]


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

def _width_mm(opts, key_default="single") -> float:
    w = opts.get("width", key_default)
    if isinstance(w, str):
        return float(WIDTHS_MM[w.strip().lower()])
    return float(w)


def _ncol(n: int, opts) -> int:
    return int(opts.get("legend_ncol") or (n if n <= 3 else int(np.ceil(n / 2)) if n <= 8 else 4))


def _mm(fig, bbox) -> tuple[float, float, float, float]:
    """Display-space bbox -> (x0, y0, x1, y1) in mm from the figure's lower-left corner."""
    k = 25.4 / fig.dpi
    return bbox.x0 * k, bbox.y0 * k, bbox.x1 * k, bbox.y1 * k


class _Layout:
    """Place axes in millimetres so the saved figure is exactly the journal width.

    Margins grow automatically if tick labels or axis labels would be cut off, and the
    height grows to make room for a legend placed above the axes.
    """

    def __init__(self, width_mm, left=15.0, right=4.0, bottom=12.0, top=3.0):
        self.W, self.left, self.right, self.bottom, self.top = width_mm, left, right, bottom, top
        self.fig = plt.figure(figsize=(width_mm * MM, 60 * MM))

    def place(self, axes_rows, aspect, legend_builder=None, fixed_height=None):
        """axes_rows: list of (axes, twin_or_None, width_weight). All axes share one row.

        aspect: height / width of each axes box (or None with fixed_height in mm).
        legend_builder(ncol) -> legend artist placed above the axes (or None).
        """
        fig = self.fig
        gap = 24.0 if len(axes_rows) > 1 else 0.0
        leg_h = 0.0
        for _ in range(3):
            usable = self.W - self.left - self.right - gap * (len(axes_rows) - 1)
            weights = [w for _, _, w in axes_rows]
            widths = [usable * w / sum(weights) for w in weights]
            heights = [fixed_height or wd * aspect for wd in widths]
            ah = max(heights)
            H = self.bottom + ah + self.top + leg_h
            fig.set_size_inches(self.W * MM, H * MM)
            x = self.left
            for (ax, twin, _), wd, ht in zip(axes_rows, widths, heights):
                pos = [x / self.W, self.bottom / H, wd / self.W, ht / H]
                ax.set_position(pos)
                if twin is not None:
                    twin.set_position(pos)
                x += wd + gap
            fig.canvas.draw()
            r = fig.canvas.get_renderer()
            need_left = need_right = need_bottom = 0.0
            for ax, twin, _ in axes_rows:
                for a in (ax, twin):
                    if a is None:
                        continue
                    x0, y0, x1, _ = _mm(fig, a.get_tightbbox(r))
                    need_left = max(need_left, -x0)
                    need_right = max(need_right, x1 - self.W)
                    need_bottom = max(need_bottom, -y0)
            changed = False
            if need_left > 0.2:
                self.left += need_left + 0.8
                changed = True
            if need_right > 0.2:
                self.right += need_right + 0.8
                changed = True
            if need_bottom > 0.2:
                self.bottom += need_bottom + 0.8
                changed = True
            if legend_builder is not None:
                new_h = self._fit_legend(legend_builder)
                if abs(new_h - leg_h) > 0.2:
                    leg_h = new_h
                    changed = True
            if not changed:
                break
        return fig

    def _fit_legend(self, builder) -> float:
        fig = self.fig
        ncol = None
        leg = builder(ncol)
        n_items = len(leg.legend_handles)
        ncol = leg._ncols
        while True:
            fig.canvas.draw()
            x0, y0, x1, y1 = _mm(fig, leg.get_window_extent(fig.canvas.get_renderer()))
            if x1 - x0 <= self.W - 2 or ncol <= 1:
                return (y1 - y0) + 2.0
            leg.remove()
            ncol -= 1
            leg = builder(ncol)
            if ncol > n_items:
                ncol = n_items


def figure_nyquist(series, normalised, opts):
    W = _width_mm(opts)
    lay = _Layout(W, left=15, right=4, bottom=12, top=3)
    ax = lay.fig.add_axes([0.1, 0.1, 0.8, 0.8])
    o = dict(opts, _markevery=auto_markevery(series, opts, W * 0.8))
    draw_nyquist(ax, series, normalised=normalised, opts=o)
    has_fit = any(s.fit_z is not None for s in series)
    handles = sample_handles(series, has_fit, opts.get("marker_size", 4))
    loc = opts.get("nyquist_legend_loc", "upper left")
    builder = None
    if loc == "above":
        builder = lambda nc: ax.legend(handles=handles, loc="lower center",  # noqa: E731
                                       bbox_to_anchor=(0.5, 1.01), ncol=nc or _ncol(len(handles), opts),
                                       columnspacing=1.2)
    elif loc not in (None, "none", False):
        ax.legend(handles=handles, loc=loc)
    return lay.place([(ax, None, 1)], 1.0, builder)


def nyquist_zoom_limit(series) -> float | None:
    """If one sample dwarfs the others (>10x), return a zoom limit that shows the rest."""
    tops = sorted((max(s.z.real.max(), (-s.z.imag).max()) for s in series), reverse=True)
    if len(tops) < 2 or tops[0] < 10 * tops[1]:
        return None
    return tops[1] * 1.08


def figure_bode(series, normalised, opts):
    W = _width_mm(opts)
    lay = _Layout(W, left=15, right=14, bottom=12, top=3)
    ax = lay.fig.add_axes([0.1, 0.1, 0.7, 0.7])
    o = dict(opts, _markevery=auto_markevery(series, opts, W * 0.7))
    ax2 = draw_bode(ax, series, normalised=normalised, opts=o)
    has_fit = any(s.fit_z is not None for s in series)
    key = bode_key_handles() if has_fit else bode_key_handles()[:2]
    handles = sample_handles(series, has_fit, opts.get("marker_size", 4)) + key
    loc = opts.get("bode_legend_loc", "above")
    builder = None
    if loc == "above":
        builder = lambda nc: ax2.legend(handles=handles, loc="lower center",  # noqa: E731
                                        bbox_to_anchor=(0.5, 1.01), ncol=nc or _ncol(len(handles), opts),
                                        columnspacing=1.2)
    elif loc not in (None, "none", False):
        ax2.legend(handles=handles, loc=loc)
    return lay.place([(ax, ax2, 1)], 0.8, builder)


def figure_combined(series, normalised, opts):
    """Double-column figure: (a) Nyquist, (b) Bode, equal heights, shared legend on top."""
    has_fit = any(s.fit_z is not None for s in series)
    handles = (sample_handles(series, has_fit, opts.get("marker_size", 4))
               + (bode_key_handles() if has_fit else bode_key_handles()[:2]))
    n = len(handles)
    W = WIDTHS_MM["double"]
    lay = _Layout(W, left=16, right=14, bottom=12, top=4)
    a = lay.fig.add_axes([0.1, 0.1, 0.3, 0.3])
    b = lay.fig.add_axes([0.5, 0.1, 0.3, 0.3])
    o = dict(opts, _markevery=auto_markevery(series, opts, 75))
    draw_nyquist(a, series, normalised=normalised, opts=o)
    b2 = draw_bode(b, series, normalised=normalised, opts=o)
    for ax, lab in ((a, "(a)"), (b, "(b)")):
        ax.text(0.0, 1.025, lab, transform=ax.transAxes, fontweight="bold", ha="left", va="bottom")

    def builder(nc):
        return b2.legend(handles=handles, loc="upper center", ncol=nc or (n if n <= 7 else int(np.ceil(n / 2))),
                         bbox_to_anchor=(0.5, 1.0), bbox_transform=lay.fig.transFigure,
                         columnspacing=1.4, borderaxespad=0.3)

    # Nyquist box square; Bode box the same height and 1.2x wider.
    def side():
        return (W - lay.left - lay.right - 24.0) / 2.2

    fig = lay.place([(a, None, 1.0), (b, b2, 1.2)], None, None, fixed_height=side())
    leg = builder(None)
    ncol = leg._ncols
    while True:
        fig.canvas.draw()
        x0, y0, x1, y1 = _mm(fig, leg.get_window_extent(fig.canvas.get_renderer()))
        if x1 - x0 <= W - 2 or ncol <= 1:
            break
        leg.remove()
        ncol -= 1
        leg = builder(ncol)
    lay.top = 4.0 + (y1 - y0) + 3.0
    for _ in range(2):
        lay.place([(a, None, 1.0), (b, b2, 1.2)], None, None, fixed_height=side())
    return fig


def save(fig, base: Path, formats, dpi: int) -> list[Path]:
    """Save at the exact figure size (no cropping). TIFF is written as RGB with LZW."""
    import io

    from PIL import Image

    base.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for fmt in formats:
        ext = str(fmt).lower().lstrip(".")
        p = base.parent / f"{base.name}.{ext}"
        if ext in ("tif", "tiff"):
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=dpi, bbox_inches=None, facecolor="white")
            buf.seek(0)
            Image.open(buf).convert("RGB").save(p, compression="tiff_lzw", dpi=(dpi, dpi))
        elif ext in ("png", "jpg", "jpeg"):
            fig.savefig(p, dpi=dpi, bbox_inches=None, facecolor="white")
        else:
            fig.savefig(p, bbox_inches=None)
        out.append(p)
    plt.close(fig)
    return out
