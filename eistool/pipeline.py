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

from matplotlib.colors import is_color_like
from matplotlib.markers import MarkerStyle

from . import plotting, report
from .circuits import Circuit, CircuitSyntaxError
from .dta import SUPPORTED, EISData, _num, read_any
from .errors import UserError
from .fitting import WEIGHTINGS, FitResult, fit_circuit
from .style import MARKERS, PALETTE, WIDTHS_MM, apply_style

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
        "marker_size": 3.5,
        "marker_every": 1,
        "fit_linewidth": 1.0,
        "formats": ["pdf", "tiff", "png"],
        "dpi": 1000,
        "nyquist_max": None,
        "nyquist_zoom": True,
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


def _merge(base: dict, over) -> dict:
    """Recursive merge. A section left empty in config.yaml (None) keeps the defaults."""
    out = dict(base)
    for k, v in (over or {}).items():
        if v is None and isinstance(out.get(k), dict):
            continue
        if isinstance(out.get(k), dict) and not isinstance(v, dict):
            if k == "fit" and v is False:
                out[k] = dict(out[k], enabled=False)
                continue
            raise UserError(f"'{k}:' in config.yaml must contain indented settings, not '{v}'.")
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
    try:
        user = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        raise UserError(
            f"config.yaml could not be read{where}: {getattr(e, 'problem', e)}.\n"
            "Tip: put text with special characters in single quotes, e.g. "
            "legend: '1 mM $\\mathregular{Na_2MoO_4}$'") from None
    if not isinstance(user, dict):
        raise UserError("config.yaml must contain settings like 'circuit: R0-p(R1,CPE1)'.")
    cfg = _merge(DEFAULTS, user)

    pc = cfg["plots"]
    if isinstance(pc.get("formats"), str):
        pc["formats"] = [f.strip() for f in re.split(r"[,\s]+", pc["formats"]) if f.strip()]
    w = pc.get("width")
    if isinstance(w, str):
        if w.strip().lower() not in WIDTHS_MM:
            raise UserError(f"plots: width must be single, onehalf, double or a number in mm (got '{w}').")
        pc["width"] = w.strip().lower()
    if not isinstance(pc.get("width"), str):
        try:
            pc["width"] = float(pc.get("width"))
        except (TypeError, ValueError):
            raise UserError(f"plots: width must be single, onehalf, double or a number in mm "
                            f"(got '{pc.get('width')}').") from None
        if not 40 <= pc["width"] <= 300:
            raise UserError(f"plots: width must be between 40 and 300 mm (got {pc['width']:g}).")
    for sect, key, lo in (("plots", "dpi", 72), ("fit", "n_starts", 1)):
        try:
            v = float(cfg[sect].get(key))
            if v != int(v) or v < lo:
                raise ValueError
            cfg[sect][key] = int(v)
        except (TypeError, ValueError):
            raise UserError(f"{sect}: {key} must be a whole number of at least {lo} "
                            f"(got '{cfg[sect].get(key)}').") from None
    for key in ("font_size", "marker_size", "fit_linewidth"):
        try:
            pc[key] = float(pc.get(key))
        except (TypeError, ValueError):
            raise UserError(f"plots: {key} must be a number (got '{pc.get(key)}').") from None
    wt = str(cfg["fit"].get("weighting", "modulus")).strip().lower()
    if wt not in WEIGHTINGS:
        raise UserError(f"fit: weighting must be one of {', '.join(WEIGHTINGS)} (got '{wt}').")
    cfg["fit"]["weighting"] = wt
    return cfg


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", name).strip("_") or "system"


def _log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------------------

def _parse_area(value, data: EISData, where: str):
    if isinstance(value, str) and value.strip().lower() == "auto":
        return data.area
    if value in (None, False, 0) or (isinstance(value, str) and value.strip().lower() in ("none", "no", "off", "")):
        return None
    a = _num(value) if isinstance(value, str) else float(value)
    if not np.isfinite(a) or a <= 0:
        raise UserError(f"{where}: area_cm2 must be a positive number, 'auto' or 'none' (got '{value}').")
    return a


def _freq(value, where: str, key: str):
    if value is None:
        return None
    v = _num(value) if isinstance(value, str) else value
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = float("nan")
    if not np.isfinite(v) or v <= 0:
        raise UserError(f"{where}: {key} must be a frequency in Hz (got '{value}').")
    return v


def _param_dict(value, where: str, key: str) -> dict:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise UserError(f"{where}: {key} must look like {{R1: 50, CPE1_n: 0.9}} (got '{value}').")
    return value


def _for_circuit(params: dict, circuit: Circuit) -> dict:
    """Keep only the global initial_guess / fixed entries that exist in this circuit."""
    return {k: v for k, v in (params or {}).items() if k in circuit.param_names}


def collect_systems(cfg: dict, base: Path) -> list[SystemRecord]:
    data_dir = (base / cfg["data_folder"]).resolve()
    if not data_dir.is_dir():
        raise UserError(f"Data folder not found: {data_dir}")
    entries = cfg.get("systems")
    if not entries:
        files = sorted(p for p in data_dir.iterdir() if p.suffix.lower() in SUPPORTED)
        if not files:
            raise UserError(f"No data files found in {data_dir}. Put your .DTA files there.")
        entries = [{"file": p.name, "name": p.stem} for p in files]
    if not isinstance(entries, list):
        raise UserError("'systems:' in config.yaml must be a list of entries starting with '- file:'.")

    fitc = cfg["fit"]
    global_guess = _param_dict(fitc.get("initial_guess"), "fit", "initial_guess")
    global_fixed = _param_dict(fitc.get("fixed"), "fit", "fixed")
    all_params: set = set()
    recs, skipped = [], []
    for i, e in enumerate(entries):
        if isinstance(e, str):
            e = {"file": e}
        if not isinstance(e, dict) or not e.get("file"):
            raise UserError(f"System entry {i + 1} in config.yaml has no 'file:'.")
        fname = str(e["file"])
        path = data_dir / fname
        if not path.exists():
            raise UserError(f"File not found: {path}\nCheck the spelling in config.yaml "
                            "(put names with special characters in single quotes).")
        try:
            data = read_any(path)
        except Exception as ex:  # not an EIS file, empty, unreadable
            skipped.append(f"{fname}: {ex}")
            continue
        name = str(e.get("name") if e.get("name") is not None else path.stem)
        where = f"System '{name}'"

        circuit_text = str(e.get("circuit") or cfg["circuit"])
        try:
            circuit = Circuit(circuit_text)
        except CircuitSyntaxError as ex:
            raise UserError(f"{where}: circuit '{circuit_text}' is not valid. {ex}") from None

        color = str(e.get("color") or PALETTE[len(recs) % len(PALETTE)])
        if not is_color_like(color):
            raise UserError(f"{where}: color '{color}' is not a colour (use e.g. '#0072B2' or 'black').")
        marker = str(e.get("marker") or MARKERS[len(recs) % len(MARKERS)])
        try:
            MarkerStyle(marker)
        except (ValueError, TypeError):
            raise UserError(f"{where}: marker '{marker}' is not valid (use o s ^ D v p h < > P X * d).") from None

        all_params.update(circuit.param_names)
        label = e.get("legend")
        recs.append(SystemRecord(
            name=name,
            label=str(label) if label not in (None, "") else name,
            data=data,
            circuit=circuit_text,
            color=color,
            marker=marker,
            area_used=_parse_area(e.get("area_cm2", cfg.get("area_cm2", "auto")), data, where),
            guess={**_for_circuit(global_guess, circuit),
                   **_param_dict(e.get("initial_guess"), where, "initial_guess")},
            fixed={**_for_circuit(global_fixed, circuit), **_param_dict(e.get("fixed"), where, "fixed")},
            freq_min=_freq(e.get("freq_min", fitc.get("freq_min")), where, "freq_min"),
            freq_max=_freq(e.get("freq_max", fitc.get("freq_max")), where, "freq_max"),
        ))

    for msg in skipped:
        _log(f"WARNING: skipped {msg}")
    if not recs:
        raise UserError("None of the data files could be read as impedance (EIS) data.")
    for key, dct in (("initial_guess", global_guess), ("fixed", global_fixed)):
        unknown = sorted(set(dct) - all_params)
        if unknown:
            raise UserError(f"fit: {key} lists {', '.join(unknown)}, which is not a parameter of any "
                            f"circuit. Parameters in use: {', '.join(sorted(all_params))}")

    seen, seen_safe = {}, {}
    for r in recs:
        k, ks = r.name.casefold(), _safe(r.name).casefold()
        if k in seen or ks in seen_safe:
            other = seen.get(k) or seen_safe.get(ks)
            raise UserError(f"Two systems are both called '{r.name}' (or names that give the same "
                            f"file name: '{other}'). Give every system a different name in config.yaml.")
        seen[k], seen_safe[ks] = r.name, r.name
    if len(recs) > len(PALETTE):
        _log(f"Note: {len(recs)} systems but {len(PALETTE)} colours. Colours repeat after "
             f"{len(PALETTE)}; each system still has a different colour and marker combination. "
             "Figures with this many curves are hard to read, consider splitting them.")
    return recs


def label_problem(text: str) -> str | None:
    """Return an error message if matplotlib cannot draw this legend text."""
    import matplotlib.pyplot as plt
    fig = plt.figure()
    try:
        fig.text(0, 0, text)
        fig.canvas.draw()
        return None
    except Exception as e:
        lines = [ln.strip() for ln in str(e).splitlines() if ln.strip()]
        return lines[-1] if lines else type(e).__name__
    finally:
        plt.close(fig)


def _escape_math(text: str) -> str:
    """Plain-text fallback for a legend whose $...$ math cannot be drawn."""
    t = re.sub(r"\\math(?:regular|rm|it|bf|sf)\{", "", text)
    return t.replace("$", "").replace("{", "").replace("}", "").replace("\\", "")


def ask_legends(recs: list[SystemRecord], saved_path: Path, interactive: bool):
    """Legend text: last typed answer is remembered unless config.yaml was edited since."""
    saved = {}
    if saved_path.exists():
        try:
            saved = yaml.safe_load(saved_path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, UnicodeDecodeError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
    config_labels = {r.name: r.label for r in recs}
    for r in recs:
        prev = saved.get(r.name)
        if isinstance(prev, dict) and prev.get("config") == r.label and prev.get("legend"):
            if not label_problem(str(prev["legend"])):
                r.label = str(prev["legend"])
    if interactive:
        _log("\nLegend text for each system (press Enter to keep the value in brackets).")
        _log("Tekst legende za svaki sistem (Enter zadržava vrednost u zagradama).")
        _log("Math is allowed, e.g.  1 mM $\\mathregular{Na_2MoO_4}$\n")
        for r in recs:
            while True:
                try:
                    ans = input(f"  {r.name} [{r.label}]: ").strip()
                except EOFError:
                    ans = ""
                candidate = ans or r.label
                problem = label_problem(candidate)
                if not problem:
                    r.label = candidate
                    break
                _log(f"    Cannot draw this text ({problem}). Check the $...$ part and try again.")
                _log("    Ovaj tekst ne može da se nacrta. Proverite deo između $ znakova.")
                if not ans:  # the default itself is broken: fall back to plain text
                    r.label = _escape_math(candidate)
                    break
    for r in recs:
        problem = label_problem(r.label)
        if problem:
            _log(f"WARNING: legend for '{r.name}' has invalid math ({problem}); shown as plain text.")
            r.label = _escape_math(r.label)
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
        if m.sum() < 3:
            raise UserError(f"System '{r.name}': only {int(m.sum())} data points between freq_min "
                            f"and freq_max ({r.freq_min} to {r.freq_max} Hz). Widen the range.")
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
        for n, v, e, u, fx, fl in zip(r.fit.circuit.param_names, r.fit.values, r.fit.rel_error_pct,
                                      units, r.fit.fixed, r.fit.flags):
            if fx:
                tag = "  (fixed)"
            elif fl == "undetermined":
                tag = "  ± ∞  (cannot be determined from these data)"
            elif fl == "at bound":
                tag = "  (hit the search limit, value not meaningful)"
            else:
                tag = f"  ± {e:.2f} %" if np.isfinite(e) else ""
            lines.append(f"    {n:<10} = {v:12.4e}  {u:<12}{tag}")
        lines.append(f"    chi²       = {r.fit.chi2:12.4e}   ({r.fit.weighting} weighting, "
                     f"{r.fit.n_points} points)")
        bad = [n for n, e, fl, fx in zip(r.fit.circuit.param_names, r.fit.rel_error_pct,
                                          r.fit.flags, r.fit.fixed)
               if not fx and (fl or (np.isfinite(e) and e > 50))]
        if bad:
            lines.append(f"    WARNING: {', '.join(bad)} not well determined. The circuit may have "
                         "more elements than these data support. Try a simpler circuit, fix a value, "
                         "or limit the frequency range.")
    text = "\n".join(lines)
    _log(text.replace("ⁿ", "^n").replace("∞", "inf"))  # Windows console fonts
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
    font = apply_style(pc.get("font"), float(pc.get("font_size", 8)))
    interactive = ask and pc.get("ask_legend", True) and sys.stdin.isatty()
    ask_legends(recs, out / "legend_labels.yaml", interactive)

    fitting_on = cfg["fit"].get("enabled", True) and not no_fit
    summary = ""
    if fitting_on:
        _log("\nFitting ...")
        fit_all(recs, cfg)
        summary = print_fit_summary(recs)
        (out / "fit_report.txt").write_text(summary.strip() + "\n", encoding="utf-8")

    normalised = all(r.area_used for r in recs)
    if not normalised and any(r.area_used for r in recs):
        _log("WARNING: some systems are area-normalised (Ω cm²) and some are not (Ω). "
             "Set area_cm2 the same way for all systems to compare them.")

    # Tables first, so a problem while drawing can never lose the fit results.
    tc = cfg["table"]
    table = report.fit_table(recs, tc.get("parameter_labels")) if fitting_on else None
    xlsx = report.write_workbook(out / "EIS_results.xlsx", recs, table)
    _log(f"\nExcel written: {xlsx}")
    if table is not None:
        table.to_csv(out / "fit_results.csv", index=False, encoding="utf-8-sig")
        d = report.write_docx_table(out / "fit_table.docx", recs, tc.get("parameter_labels"),
                                    bool(tc.get("show_errors", True)), tc.get("caption"), font)
        if d:
            _log(f"Word table written: {d}")

    series = make_series(recs)
    figdir = out / "figures"
    fmts, dpi = pc.get("formats") or ["pdf", "png"], int(pc.get("dpi", 1000))
    files = []
    files += plotting.save(plotting.figure_nyquist(series, normalised, pc), figdir / "Nyquist", fmts, dpi)
    zoom = plotting.nyquist_zoom_limit(series) if pc.get("nyquist_zoom", True) and not pc.get("nyquist_max") else None
    if zoom:
        files += plotting.save(plotting.figure_nyquist(series, normalised, dict(pc, nyquist_max=zoom, nyquist_legend_loc="best")),
                               figdir / "Nyquist_zoom", fmts, dpi)
        _log("One system is >10x larger than the others: also wrote Nyquist_zoom (smaller systems visible).")
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
    _log(f"Figures ({font} font) written to {figdir}")

    results.update(excel=xlsx, figures=files, systems=recs, table=table, summary=summary)
    return results


# ---------------------------------------------------------------------------

def _q(text: str) -> str:
    """YAML single-quoted scalar: safe for #, :, $, backslashes, yes/no, numbers..."""
    return "'" + str(text).replace("'", "''") + "'"


def init_config(config_path: Path, data_folder: str = "data"):
    """Write a config.yaml listing every readable EIS file found in the data folder."""
    base = config_path.resolve().parent
    data_dir = base / data_folder
    candidates = sorted(p for p in data_dir.iterdir() if p.suffix.lower() in SUPPORTED) if data_dir.exists() else []
    files = []
    for p in candidates:
        try:
            read_any(p)
            files.append(p)
        except Exception as ex:
            _log(f"Not included (not readable as EIS data): {p.name}  [{ex}]")
    template = (Path(__file__).parent / "config_template.yaml").read_text(encoding="utf-8")
    if files:
        items = "\n".join(
            f"  - file: {_q(p.name)}\n    name: {_q(p.stem)}\n    legend: {_q(p.stem)}" for p in files)
    else:
        items = "  - file: 'sample1.DTA'\n    name: 'Sample 1'\n    legend: 'Sample 1'"
    text = template.replace("{{SYSTEMS}}", items.rstrip() + "\n").replace("{{DATA_FOLDER}}", _q(data_folder))
    config_path.write_text(text, encoding="utf-8")
    return config_path, files
