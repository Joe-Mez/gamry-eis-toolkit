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


def _data_kw(s: PlotSeries, filled: bool, ms: float, markevery):
    return dict(linestyle="none", marker=s.marker, markersize=ms, markevery=markevery,
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
    top = top_raw / fac
    loc = MaxNLocator(nbins=opts.get("nyquist_nticks", 5), steps=[1, 2, 2.5, 5, 10])
    ticks = loc.tick_values(0, top)
    step = ticks[1] - ticks[0]
    top = float(np.ceil(top / step - 1e-9) * step)
    # extend below zero only for real features (inductive loops), not noise
    thr = -0.03 * top
    ymin = float(np.floor(alli.min() / fac / step) * step) if (alli.min() / fac < thr and not zmax_opt) else 0.0
    xmin = float(np.floor(allr.min() / fac / step) * step) if (allr.min() / fac < thr and not zmax_opt) else 0.0
    ax.set_xlim(xmin, top)
    ax.set_ylim(ymin, top)
    ticks = np.arange(min(xmin, ymin), top + step / 2, step)
    ax.set_xticks(ticks[ticks >= xmin - 1e-12])
    ax.set_yticks(ticks[ticks >= ymin - 1e-12])
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
    top = 90 if pmax > 60 else float(np.ceil(pmax / 10) * 10 + 10)
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


def sample_handles(series: list[PlotSeries], with_line: bool):
    return [Line2D([], [], ls="-" if with_line else "none", color=s.color, lw=1.0,
                   marker=s.marker, ms=4, mfc=s.color, mec=s.color, label=s.label)
            for s in series]


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

def _width(opts, key_default):
    w = opts.get("width", key_default)
    return (WIDTHS_MM.get(w, None) or float(w)) * MM


def _legend_above(ax, handles, opts, ncol=None):
    n = len(handles)
    ncol = ncol or opts.get("legend_ncol") or (n if n <= 3 else int(np.ceil(n / 2)) if n <= 8 else 4)
    return ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.01),
                     ncol=ncol, columnspacing=1.2)


def _place(ax, handles, loc, opts):
    if loc == "above":
        return _legend_above(ax, handles, opts)
    if loc in (None, "none", False):
        return None
    return ax.legend(handles=handles, loc=loc)


def figure_nyquist(series, normalised, opts):
    w = _width(opts, "single")
    fig, ax = plt.subplots(figsize=(w, w))
    o = dict(opts, _markevery=auto_markevery(series, opts, w / MM * 0.8))
    draw_nyquist(ax, series, normalised=normalised, opts=o)
    has_fit = any(s.fit_z is not None for s in series)
    _place(ax, sample_handles(series, has_fit), opts.get("nyquist_legend_loc", "upper left"), opts)
    return fig


def figure_bode(series, normalised, opts):
    w = _width(opts, "single")
    fig, ax = plt.subplots(figsize=(w, w * 0.8))
    o = dict(opts, _markevery=auto_markevery(series, opts, w / MM * 0.75))
    ax2 = draw_bode(ax, series, normalised=normalised, opts=o)
    has_fit = any(s.fit_z is not None for s in series)
    key = bode_key_handles() if has_fit else bode_key_handles()[:2]
    loc = opts.get("bode_legend_loc", "above")
    if loc == "above":
        _legend_above(ax2, sample_handles(series, has_fit) + key, opts)
    else:
        _place(ax2, sample_handles(series, has_fit) + key, loc, opts)
    return fig


def figure_combined(series, normalised, opts):
    """Double-column figure: (a) Nyquist, (b) Bode, equal heights, shared legend on top."""
    has_fit = any(s.fit_z is not None for s in series)
    handles = sample_handles(series, has_fit) + (bode_key_handles() if has_fit else bode_key_handles()[:2])
    n = len(handles)
    rows = 1 if n <= 7 else 2
    W = WIDTHS_MM["double"]
    S = 62.0                       # Nyquist square side (mm) = panel height
    left, gap, bw, bottom = 17.0, 24.0, 72.0, 13.0
    top_pad = 6.0 + 4.5 * rows
    H = bottom + S + top_pad
    fig = plt.figure(figsize=(W * MM, H * MM))
    a = fig.add_axes([left / W, bottom / H, S / W, S / H])
    b = fig.add_axes([(left + S + gap) / W, bottom / H, bw / W, S / H])
    o = dict(opts, _markevery=auto_markevery(series, opts, bw))
    draw_nyquist(a, series, normalised=normalised, opts=o)
    draw_bode(b, series, normalised=normalised, opts=o)
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 1.0),
               ncol=n if rows == 1 else int(np.ceil(n / 2)), columnspacing=1.4)
    for ax, lab in ((a, "(a)"), (b, "(b)")):
        ax.text(0.0, 1.025, lab, transform=ax.transAxes, fontweight="bold", ha="left", va="bottom")
    return fig


def save(fig, base: Path, formats, dpi: int) -> list[Path]:
    base.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for fmt in formats:
        p = base.parent / f"{base.name}.{fmt.lower().lstrip('.')}"
        kw = {}
        if fmt.lower() in ("png", "tif", "tiff", "jpg", "jpeg"):
            kw["dpi"] = dpi
        if fmt.lower() in ("tif", "tiff"):
            kw["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig(p, **kw)
        out.append(p)
    plt.close(fig)
    return out
