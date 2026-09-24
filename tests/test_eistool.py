from pathlib import Path

import numpy as np
import pytest

from eistool.circuits import Circuit, CircuitSyntaxError
from eistool.dta import read_dta
from eistool.fitting import fit_circuit

HERE = Path(__file__).parent
EX = HERE.parent / "examples" / "inhibitor" / "data"
COAT = HERE.parent / "examples" / "coating" / "data"


def test_circuit_simple_values():
    c = Circuit("R0-p(R1,C1)")
    z = c.impedance([10, 100, 1e-5], [1e-6, 1e9])
    assert np.isclose(z[0].real, 110, rtol=1e-6)
    assert np.isclose(z[1].real, 10, rtol=1e-3)


def test_cpe_alias_and_params():
    c = Circuit("R0-p(R1,Q1)")
    assert c.param_names == ["R0", "R1", "CPE1_Q", "CPE1_n"]


def test_bad_circuit():
    with pytest.raises(CircuitSyntaxError):
        Circuit("R0-p(R1")
    with pytest.raises(CircuitSyntaxError):
        Circuit("R0-R0")


def test_real_gamry_file():
    d = read_dta(HERE / "data" / "impedancepy_exampleDataGamry.DTA")
    assert len(d.freq) > 50
    assert d.freq[0] > d.freq[-1]
    assert np.all(d.zimag < 0)
    assert d.area == 1.0


def test_decimal_comma_file():
    d = read_dta(EX / "inhibitor_5mM.DTA")
    assert len(d.freq) == 71
    assert np.isclose(d.freq[0], 1e5)
    assert d.header["TAG"] == "EISPOT"


@pytest.mark.parametrize("name,tag", [
    ("epoxy_1h.DTA", "EISPOT"),          # cp1252, CRLF
    ("epoxy_24h.DTA", "EISPOT"),         # UTF-8 with BOM, LF
    ("epoxy 7 days.DTA", "EISGALV"),     # galvanostatic, no OCV block, spaces in name
    ("epoxy_30d.DTA", "EISPOT"),         # UTF-8, LF, row count on ZCURVE line
])
def test_coating_file_variants(name, tag):
    d = read_dta(COAT / name)
    assert d.header["TAG"] == tag
    assert len(d.freq) == 50
    assert np.isclose(d.area, 3.14)
    assert np.all(np.isfinite(d.zreal)) and np.all(d.zimag < 0)


def test_coating_pipeline_units_and_zoom(tmp_path):
    import shutil
    from eistool.pipeline import run
    ex = COAT.parent
    shutil.copytree(ex / "data", tmp_path / "data")
    shutil.copy(ex / "config.yaml", tmp_path / "config.yaml")
    res = run(tmp_path / "config.yaml", ask=False)
    recs = {r.name: r for r in res["systems"]}
    # fitted in Ω cm² (area 3.14 from the DTA header), pore resistance of the 1 h coating ~ 4 GΩ cm²
    assert np.isclose(recs["1 h"].fit.params["R2"], 4.0e9, rtol=0.05)
    assert np.isclose(recs["30 d"].fit.params["R1"], 2.5e6, rtol=0.2)
    assert (res["output"] / "figures" / "Nyquist_zoom.pdf").exists()


@pytest.mark.parametrize("text,true", [
    ("R0-p(R1,CPE1)", [15, 5000, 5e-5, 0.88]),
    ("R0-p(CPE2,R2-p(R1,CPE1))", [20, 1e-6, 0.9, 600, 8000, 2e-5, 0.8]),
    ("R0-p(R1-W1,C1)", [10, 300, 50, 2e-5]),
])
def test_fit_recovers_parameters(text, true):
    f = np.logspace(5, -2, 71)
    c = Circuit(text)
    rng = np.random.default_rng(3)
    z = c.impedance(true, f)
    z = z + 0.003 * np.abs(z) * (rng.standard_normal(len(f)) + 1j * rng.standard_normal(len(f)))
    r = fit_circuit(c, f, z, n_starts=20)
    assert np.allclose(r.values, true, rtol=0.05)


def test_fixed_parameter():
    f = np.logspace(5, -2, 50)
    c = Circuit("R0-p(R1,CPE1)")
    z = c.impedance([10, 1000, 1e-5, 1.0], f)
    r = fit_circuit(c, f, z, fixed={"CPE1_n": 1.0}, n_starts=5)
    assert r.params["CPE1_n"] == 1.0
    assert np.isclose(r.params["R1"], 1000, rtol=1e-3)


def test_pipeline_runs(tmp_path):
    import shutil
    from eistool.pipeline import init_config, run
    (tmp_path / "data").mkdir()
    for p in EX.glob("*.DTA"):
        shutil.copy(p, tmp_path / "data")
    cfg, files = init_config(tmp_path / "config.yaml")
    assert len(files) == 4
    res = run(cfg, ask=False)
    out = res["output"]
    assert (out / "EIS_results.xlsx").exists()
    assert (out / "figures" / "Nyquist.pdf").exists()
    assert (out / "figures" / "Bode.tiff").exists()
    assert (out / "fit_table.docx").exists()
