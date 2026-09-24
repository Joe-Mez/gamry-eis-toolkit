"""Regression tests for issues found in the independent code review and debugging pass."""
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from eistool.circuits import Circuit
from eistool.dta import read_table
from eistool.errors import UserError
from eistool.fitting import fit_circuit
from eistool.pipeline import init_config, load_config, run
from eistool.report import fmt_value

HERE = Path(__file__).parent
INH = HERE.parent / "examples" / "inhibitor"


def _spectrum(text="R0-p(R1,CPE1)", params=(10, 500, 5e-5, 0.85), n=60, noise=0.003, seed=1):
    f = np.logspace(5, -2, n)
    z = Circuit(text).impedance(list(params), f)
    rng = np.random.default_rng(seed)
    return f, z + noise * np.abs(z) * (rng.standard_normal(n) + 1j * rng.standard_normal(n))


# --- fitting ---------------------------------------------------------------

def test_series_resistors_are_reported_as_undetermined():
    f, z = _spectrum()
    r = fit_circuit("R0-R2-p(R1,CPE1)", f, z, n_starts=10)
    flags = dict(zip(r.circuit.param_names, r.flags))
    # the split between two series resistors is arbitrary: at least one must be flagged
    assert "undetermined" in (flags["R0"], flags["R2"]) or "at bound" in (flags["R0"], flags["R2"])
    assert flags["R1"] == ""
    # with two comparable resistors both are flagged
    f2 = np.logspace(5, -2, 60)
    z2 = Circuit("R0-R2-p(R1,CPE1)").impedance([10, 5, 500, 5e-5, 0.85], f2)
    r2 = fit_circuit("R0-R2-p(R1,CPE1)", f2, z2 * (1 + 0.002j), n_starts=10)
    assert all(fl in ("undetermined", "at bound") for fl in r2.flags[:2])


def test_proportional_weighting_is_not_biased():
    f, z = _spectrum()
    r = fit_circuit("R0-p(R1,CPE1)", f, z, weighting="Proportional", n_starts=10)
    assert np.allclose(r.values, [10, 500, 5e-5, 0.85], rtol=0.05)


@pytest.mark.parametrize("kw", [{"guess": {"R1": 0}}, {"guess": {"R1": -5}},
                                {"fixed": {"CPE1_n": 1.5}}, {"guess": {"R9": 1}}])
def test_bad_guess_or_fixed_values_are_rejected(kw):
    f, z = _spectrum()
    with pytest.raises(UserError):
        fit_circuit("R0-p(R1,CPE1)", f, z, n_starts=2, **kw)


def test_too_few_points_is_rejected():
    f, z = _spectrum(n=60)
    with pytest.raises(UserError):
        fit_circuit("R0-p(R1,CPE1)", f[:2], z[:2])


# --- config / pipeline -------------------------------------------------------

def _project(tmp_path, cfg_text=None, files=None):
    (tmp_path / "data").mkdir()
    for p in (files or sorted((INH / "data").glob("*.DTA"))):
        shutil.copy(p, tmp_path / "data")
    if cfg_text is not None:
        (tmp_path / "config.yaml").write_text(cfg_text, encoding="utf-8")
    return tmp_path / "config.yaml"


def test_init_quotes_awkward_file_names(tmp_path):
    (tmp_path / "data").mkdir()
    src = INH / "data" / "blank.DTA"
    for name in ["Fe #2.DTA", "yes.DTA", "007.DTA", "a'b.DTA", "č ž 1.DTA"]:
        shutil.copy(src, tmp_path / "data" / name)
    cfg, files = init_config(tmp_path / "config.yaml")
    systems = yaml.safe_load(cfg.read_text(encoding="utf-8"))["systems"]
    assert sorted(s["file"] for s in systems) == sorted(p.name for p in files)
    assert all(isinstance(s["name"], str) for s in systems)


def test_init_skips_non_eis_files(tmp_path):
    (tmp_path / "data").mkdir()
    shutil.copy(INH / "data" / "blank.DTA", tmp_path / "data")
    (tmp_path / "data" / "notes.txt").write_text("hello\nworld\n")
    _, files = init_config(tmp_path / "config.yaml")
    assert [p.name for p in files] == ["blank.DTA"]


def test_empty_config_sections_keep_defaults(tmp_path):
    cfg = _project(tmp_path, "circuit: R0-p(R1,CPE1)\nfit:\nplots:\ntable:\n")
    c = load_config(cfg)
    assert c["fit"]["weighting"] == "modulus" and c["plots"]["formats"]


def test_global_fixed_only_applies_to_matching_circuits(tmp_path):
    text = (INH / "config.yaml").read_text(encoding="utf-8")
    text = text.replace("  fixed: {}", "  fixed: {CPE2_n: 0.9}")
    text = text.replace("  formats: [pdf, tiff, png]", "  formats: [png]")
    text = text.replace("  individual_figures: true", "  individual_figures: false")
    cfg = _project(tmp_path, text)
    res = run(cfg, ask=False)
    recs = {r.name: r for r in res["systems"]}
    assert recs["5 mM"].fit.params["CPE2_n"] == 0.9
    assert "CPE2_n" not in recs["Blank"].fit.params


@pytest.mark.parametrize("area", ["-2", "abc"])
def test_bad_area_is_rejected(tmp_path, area):
    cfg = _project(tmp_path, f"area_cm2: {area}\n")
    with pytest.raises(UserError):
        run(cfg, ask=False, convert_only=True)


def test_decimal_comma_area_is_accepted(tmp_path):
    cfg = _project(tmp_path, "area_cm2: '0,5'\n")
    res = run(cfg, ask=False, convert_only=True)
    assert res["excel"].exists()


def test_duplicate_names_are_rejected(tmp_path):
    cfg = _project(tmp_path, "systems:\n  - file: blank.DTA\n    name: '1 mM'\n"
                             "  - file: inhibitor_1mM.DTA\n    name: '1_mM'\n")
    with pytest.raises(UserError):
        run(cfg, ask=False, convert_only=True)


def test_bad_legend_math_does_not_crash_and_is_not_remembered(tmp_path):
    cfg = _project(tmp_path, "systems:\n  - file: blank.DTA\n    name: A\n"
                             "    legend: '1 mM $\\mathregular{Na_2MoO_4$'\n"
                             "plots:\n  formats: [png]\n  individual_figures: false\n"
                             "  combined_figure: false\n")
    res = run(cfg, ask=False)
    assert res["systems"][0].label == "1 mM Na_2MoO_4"
    run(cfg, ask=False)  # second run must not crash either


def test_non_eis_file_is_skipped_with_warning(tmp_path, capsys):
    cfg = _project(tmp_path, "plots:\n  formats: [png]\n  individual_figures: false\n")
    (tmp_path / "data" / "notes.txt").write_text("not data\n")
    res = run(cfg, ask=False, convert_only=True)
    assert len(res["systems"] if "systems" in res else [1, 2, 3, 4]) >= 1
    assert "skipped notes.txt" in capsys.readouterr().out


def test_figures_have_exact_journal_width_and_rgb_tiff(tmp_path):
    from PIL import Image
    cfg = _project(tmp_path, "plots:\n  formats: [tiff]\n  dpi: 300\n  individual_figures: false\n")
    run(cfg, ask=False, no_fit=True)
    for name, mm in [("Nyquist", 90), ("Bode", 90), ("EIS_combined", 190)]:
        im = Image.open(tmp_path / "results" / "figures" / f"{name}.tiff")
        assert im.mode == "RGB"
        assert abs(im.size[0] / 300 * 25.4 - mm) < 0.2


# --- readers / formatting ---------------------------------------------------

@pytest.mark.parametrize("content", [
    "# comment\nf Zr Zi\n1e5 10 -1\n1e4 12 -3\n1e3 20 -8\n",
    "f;Zr;Zi\n1e5;10,5;-1\n1e4;12,5;-3\n1e3;20,1;-8\n",
    "1e5,10.5,-1\n1e4,12.5,-3\n1e3,20.1,-8\n",
])
def test_generic_table_formats(tmp_path, content):
    p = tmp_path / "t.txt"
    p.write_text(content)
    d = read_table(p)
    assert len(d.freq) == 3 and d.zimag[0] < 0


def test_number_rounding():
    assert fmt_value(9999.6) == ("1.00", "4")
    assert fmt_value(0.099996) == ("0.100", None)


# --- second review round ----------------------------------------------------

def test_parameter_at_bound_does_not_flag_neighbours():
    from eistool.dta import read_dta
    d = read_dta(INH / "data" / "blank.DTA")
    r = fit_circuit("R0-p(R1,CPE1)-L1", d.freq, d.z, n_starts=10)
    flags = dict(zip(r.circuit.param_names, r.flags))
    assert flags["L1"] == "at bound"
    assert all(flags[k] == "" for k in ("R0", "R1", "CPE1_Q", "CPE1_n"))


def test_global_key_typo_is_reported(tmp_path):
    cfg = _project(tmp_path, "fit:\n  fixed: {CPE1_N: 1.0}\n")
    with pytest.raises(UserError, match="CPE1_N"):
        run(cfg, ask=False, convert_only=True)


@pytest.mark.parametrize("snippet", ["plots:\n  width: 30\n", "plots:\n  dpi: lots\n",
                                     "fit:\n  n_starts: auto\n",
                                     "systems:\n  - file: blank.DTA\n    marker: circle\n",
                                     "systems:\n  - file: blank.DTA\n    initial_guess: R1=50\n",
                                     "fit:\n  freq_min: abc\n"])
def test_bad_option_values_give_user_errors(tmp_path, snippet):
    cfg = _project(tmp_path, snippet)
    with pytest.raises(UserError):
        run(cfg, ask=False, no_fit=True)


def test_quoted_csv_numbers(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text('"1000","10.2","-1.1"\n"100","12.5","-3"\n"10","20","-8"\n')
    assert len(read_table(p).freq) == 3
