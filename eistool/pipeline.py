"""End-to-end workflow: read -> (fit) -> figures -> Excel/Word tables."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import logging

import numpy as np
import pandas as pd
import yaml

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

from . import plotting, report
from .circuits import Circuit
from .dta import SUPPORTED, EISData, read_any
from .fitting import FitResult, fit_circuit
from .style import MARKERS, PALETTE, apply_style

DEFAULTS = {
    "data_folder": "data",
    "output_folder": "results",
    "area_cm2": "auto",
    "circuit": "R0-p(R1,CPE1)",
    "systems": None,
    "fit": {
        "enabled": True,
        "weighting": "modulus",
        "freq_min": None,
        "freq_max": None,
        "n_starts": 40,
        "initial_guess": {},
        "fixed": {},
    },
    "plots": {
        "ask_legend": True,
        "width": "single",
        "font": "Arial",
        "font_size": 8,
        "marker_size": 4,
        "marker_every": "auto",
        "fit_linewidth": 1.0,
        "formats": ["pdf", "tiff", "png"],
        "dpi": 600,
        "nyquist_max": None,
        "nyquist_legend_loc": "upper left",
        "bode_legend_loc": "above",
        "combined_figure": True,
        "individual_figures": True,
        "unit_prefix": True,
    },
    "table": {
        "show_errors": True,
        "caption": None,
        "parameter_labels": {},
    },
}


@dataclass
class SystemRecord:
    name: str
    label: str
    data: EISData
    circuit: str
    color: str
    marker: str
    area_used: float | None
    guess: dict
    fixed: dict
    freq_min: float | None
    freq_max: float | None
    fit: FitResult | None = None

    @property
    def z_fit_units(self) -> np.ndarray:
        """Measured impedance in the units used for fitting/plotting."""
        return self.data.z * (self.area_used or 1.0)


def _merge(base: dict, over: dict | None) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path) -> dict:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # older Notepad "ANSI" encoding
        text = raw.decode("cp1250", errors="replace")
    user = yaml.safe_load(text) or {}
    return _merge(DEFAULTS, user)


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", name).strip("_") or "system"


def _log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------------------

def collect_systems(cfg: dict, base: Path) -> list[SystemRecord]:
    data_dir = (base / cfg["data_folder"]).resolve()
    entries = cfg.get("systems")
    if not entries:
        files = sorted(p for p in data_dir.iterdir() if p.suffix.lower() in SUPPORTED)
        if not files:
            raise SystemExit(f"No data files found in {data_dir}. Put your .DTA files there.")
        entries = [{"file": p.name, "name": p.stem} for p in files]

    fitc = cfg["fit"]
    recs = []
    for i, e in enumerate(entries):
        if isinstance(e, str):
            e = {"file": e}
        path = data_dir / e["file"]
        if not path.exists():
            raise SystemExit(f"File not found: {path}")
        data = read_any(path)
        name = str(e.get("name") or path.stem)

        area_setting = e.get("area_cm2", cfg.get("area_cm2", "auto"))
        if isinstance(area_setting, str) and area_setting.lower() == "auto":
            area = data.area
        elif area_setting in (None, False, 0) or (isinstance(area_setting, str) and area_setting.lower() in ("none", "no", "off")):
            area = None
        else:
            area = float(area_setting)

        recs.append(SystemRecord(
            name=name,
            label=str(e.get("legend") or name),
            data=data,
            circuit=str(e.get("circuit") or cfg["circuit"]),
            color=str(e.get("color") or PALETTE[i % len(PALETTE)]),
            marker=str(e.get("marker") or MARKERS[i % len(MARKERS)]),
            area_used=area,
            guess=_merge(fitc.get("initial_guess") or {}, e.get("initial_guess")),
            fixed=_merge(fitc.get("fixed") or {}, e.get("fixed")),
            freq_min=e.get("freq_min", fitc.get("freq_min")),
            freq_max=e.get("freq_max", fitc.get("freq_max")),
        ))
    if len(recs) > len(PALETTE):
        _log(f"Note: {len(recs)} systems but {len(PALETTE)} distinct colours; colours repeat "
             "(marker shapes still differ). Consider splitting into several figures.")
    return recs


def ask_legends(recs: list[SystemRecord], saved_path: Path, interactive: bool):
    """Legend text: last typed answer is remembered unless config.yaml was edited since."""
    saved = {}
    if saved_path.exists():
        saved = yaml.safe_load(saved_path.read_text(encoding="utf-8")) or {}
    config_labels = {r.name: r.label for r in recs}
    for r in recs:
        prev = saved.get(r.name)
        if isinstance(prev, dict) and prev.get("config") == r.label and prev.get("legend"):
            r.label = prev["legend"]
    if interactive:
        _log("\nLegend text for each system (press Enter to keep the value in brackets).")
        _log("Tekst legende za svaki sistem (Enter zadržava vrednost u zagradama).")
        _log("Math is allowed, e.g.  1 mM $\\mathregular{Na_2MoO_4}$\n")
        for r in recs:
            try:
                ans = input(f"  {r.name} [{r.label}]: ").strip()
            except EOFError:
                ans = ""
            if ans:
                r.label = ans
    saved.update({r.name: {"legend": r.label, "config": config_labels[r.name]} for r in recs})
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    saved_path.write_text("# Remembered legend text. Delete this file to reset.\n" +
                          yaml.safe_dump(saved, allow_unicode=True, sort_keys=False), encoding="utf-8")


def fit_all(recs: list[SystemRecord], cfg: dict):
    fc = cfg["fit"]
    for r in recs:
        c = Circuit(r.circuit)
        z = r.z_fit_units
        f = r.data.freq
        m = np.ones_like(f, dtype=bool)
        if r.freq_min is not None:
            m &= f >= float(r.freq_min)
        if r.freq_max is not None:
            m &= f <= float(r.freq_max)
        r.fit = fit_circuit(c, f[m], z[m], guess=r.guess, fixed=r.fixed,
                            weighting=fc.get("weighting", "modulus"),
                            n_starts=int(fc.get("n_starts", 40)))


def print_fit_summary(recs: list[SystemRecord]) -> str:
    lines = []
    for r in recs:
        if r.fit is None:
            continue
        units = r.fit.circuit.units(bool(r.area_used))
        lines.append(f"\n{r.name}  ({r.label})   circuit: {r.fit.circuit.text}")
        for n, v, e, u, fx in zip(r.fit.circuit.param_names, r.fit.values, r.fit.rel_error_pct,
                                  units, r.fit.fixed):
            tag = "  (fixed)" if fx else (f"  ± {e:.2f} %" if np.isfinite(e) else "")
            lines.append(f"    {n:<10} = {v:12.4e}  {u:<12}{tag}")
        lines.append(f"    chi²       = {r.fit.chi2:12.4e}   ({r.fit.weighting} weighting, "
                     f"{r.fit.n_points} points)")
        big = [n for n, e in zip(r.fit.circuit.param_names, r.fit.rel_error_pct) if np.isfinite(e) and e > 50]
        if big:
            lines.append(f"    WARNING: large uncertainty for {', '.join(big)}; "
                         "the circuit may have too many elements for this spectrum.")
    text = "\n".join(lines)
    _log(text)
    return text


def make_series(recs: list[SystemRecord]) -> list[plotting.PlotSeries]:
    out = []
    for r in recs:
        ff = fz = None
        if r.fit is not None:
            lo, hi = r.fit.freq_range
            ff = np.logspace(np.log10(hi), np.log10(lo), 300)
            fz = r.fit.predict(ff)
        out.append(plotting.PlotSeries(r.label, r.color, r.marker, r.data.freq, r.z_fit_units, ff, fz))
    return out


# ---------------------------------------------------------------------------

def run(config_path: str | Path, *, ask: bool = True, convert_only: bool = False,
        no_fit: bool = False) -> dict:
    config_path = Path(config_path).resolve()
    base = config_path.parent
    cfg = load_config(config_path)
    out = (base / cfg["output_folder"]).resolve()
    out.mkdir(parents=True, exist_ok=True)

    recs = collect_systems(cfg, base)
    _log(f"Loaded {len(recs)} system(s):")
    for r in recs:
        a = f"{r.area_used:g} cm² (Ω cm²)" if r.area_used else "none (raw Ω)"
        _log(f"  {r.name:<25} {r.data.path.name:<30} {len(r.data.freq):>4} pts  "
             f"{r.data.freq.max():.3g}–{r.data.freq.min():.3g} Hz   area: {a}")

    results = {"output": out}
    if convert_only:
        p = report.write_workbook(out / "EIS_data.xlsx", recs)
        _log(f"\nExcel written: {p}")
        results["excel"] = p
        return results

    pc = cfg["plots"]
    interactive = ask and pc.get("ask_legend", True) and sys.stdin.isatty()
    ask_legends(recs, out / "legend_labels.yaml", interactive)

    fitting_on = cfg["fit"].get("enabled", True) and not no_fit
    summary = ""
    if fitting_on:
        _log("\nFitting ...")
        fit_all(recs, cfg)
        summary = print_fit_summary(recs)
        (out / "fit_report.txt").write_text(summary.strip() + "\n", encoding="utf-8")

    font = apply_style(pc.get("font"), float(pc.get("font_size", 8)))
    normalised = all(r.area_used for r in recs)
    if not normalised and any(r.area_used for r in recs):
        _log("Warning: some systems are area-normalised and some are not; plots use mixed units.")
    series = make_series(recs)
    figdir = out / "figures"
    fmts, dpi = pc.get("formats", ["pdf", "png"]), int(pc.get("dpi", 600))
    files = []
    files += plotting.save(plotting.figure_nyquist(series, normalised, pc), figdir / "Nyquist", fmts, dpi)
    files += plotting.save(plotting.figure_bode(series, normalised, pc), figdir / "Bode", fmts, dpi)
    if pc.get("combined_figure", True):
        files += plotting.save(plotting.figure_combined(series, normalised, pc), figdir / "EIS_combined", fmts, dpi)
    if pc.get("individual_figures", True):
        for r, s in zip(recs, series):
            one = dict(pc, nyquist_max=None)
            files += plotting.save(plotting.figure_nyquist([s], bool(r.area_used), one),
                                   figdir / "individual" / f"{_safe(r.name)}_Nyquist", fmts, dpi)
            files += plotting.save(plotting.figure_bode([s], bool(r.area_used), one),
                                   figdir / "individual" / f"{_safe(r.name)}_Bode", fmts, dpi)
    _log(f"\nFigures ({font} font) written to {figdir}")

    tc = cfg["table"]
    table = report.fit_table(recs, tc.get("parameter_labels")) if fitting_on else None
    xlsx = report.write_workbook(out / "EIS_results.xlsx", recs, table)
    _log(f"Excel written: {xlsx}")
    if table is not None:
        table.to_csv(out / "fit_results.csv", index=False, encoding="utf-8-sig")
        d = report.write_docx_table(out / "fit_table.docx", recs, tc.get("parameter_labels"),
                                    bool(tc.get("show_errors", True)), tc.get("caption"), font)
        if d:
            _log(f"Word table written: {d}")
    results.update(excel=xlsx, figures=files, systems=recs, table=table, summary=summary)
    return results


# ---------------------------------------------------------------------------

def init_config(config_path: Path, data_folder: str = "data"):
    """Write a config.yaml listing every data file found in the data folder."""
    base = config_path.resolve().parent
    data_dir = base / data_folder
    files = sorted(p for p in data_dir.iterdir() if p.suffix.lower() in SUPPORTED) if data_dir.exists() else []
    template = (Path(__file__).parent / "config_template.yaml").read_text(encoding="utf-8")
    if files:
        items = "\n".join(
            f"  - file: {p.name}\n    name: {p.stem}\n    legend: \"{p.stem}\"\n" for p in files)
    else:
        items = "  - file: sample1.DTA\n    name: Sample 1\n    legend: \"Sample 1\"\n"
    text = template.replace("{{SYSTEMS}}", items.rstrip() + "\n").replace("{{DATA_FOLDER}}", data_folder)
    config_path.write_text(text, encoding="utf-8")
    return config_path, files
