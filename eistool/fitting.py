"""Complex non-linear least-squares fitting of equivalent circuits."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .circuits import Circuit

WEIGHTINGS = ("modulus", "proportional", "unit")


@dataclass
class FitResult:
    circuit: Circuit
    values: np.ndarray
    stderr: np.ndarray            # absolute standard errors (nan when fixed or undetermined)
    fixed: np.ndarray             # bool mask
    chi2: float                   # weighted sum of squares / degrees of freedom
    wssr: float                   # weighted sum of squared residuals
    n_points: int
    weighting: str
    success: bool
    message: str
    freq_range: tuple = (np.nan, np.nan)
    extra: dict = field(default_factory=dict)

    @property
    def params(self) -> dict:
        return dict(zip(self.circuit.param_names, self.values))

    @property
    def rel_error_pct(self) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return 100 * self.stderr / np.abs(self.values)

    def predict(self, freq) -> np.ndarray:
        return self.circuit.impedance(self.values, freq)


# ---------------------------------------------------------------------------
# Initial guesses
# ---------------------------------------------------------------------------

def _top_level_series_elements(circuit: Circuit) -> set[str]:
    t = circuit.tree
    if t.kind == "element":
        return {t.name}
    if t.kind == "series":
        return {c.name for c in t.children if c.kind == "element"}
    return set()


def initial_guess(circuit: Circuit, freq, z) -> np.ndarray:
    """Physically sensible starting values estimated from the spectrum."""
    freq = np.asarray(freq)
    hi, lo = np.argmax(freq), np.argmin(freq)
    r_hf = max(float(np.real(z[hi])), 1e-6)
    r_lf = float(np.real(z[lo]))
    r_span = max(r_lf - r_hf, abs(z[lo]) * 0.5, 1e-3)
    ipk = int(np.argmax(-np.imag(z)))
    f_pk = float(freq[ipk]) if -np.imag(z[ipk]) > 0 else float(np.sqrt(freq.max() * freq.min()))

    series_top = _top_level_series_elements(circuit)
    n_other_r = sum(1 for e in circuit.elements if e.etype == "R" and e.name not in series_top)
    r_each = r_span / max(n_other_r, 1)

    g = []
    for e in circuit.elements:
        if e.etype == "R":
            g.append(r_hf if e.name in series_top else r_each)
        elif e.etype == "C":
            g.append(1 / (2 * np.pi * f_pk * r_each))
        elif e.etype == "CPE":
            g += [1 / (2 * np.pi * f_pk * r_each), 0.85]
        elif e.etype == "L":
            g.append(1e-6)
        elif e.etype == "W":
            w0 = 2 * np.pi * freq[lo]
            g.append(max(abs(np.imag(z[lo])) * np.sqrt(w0), 1e-3))
        elif e.etype in ("Ws", "Wo"):
            g += [r_each, 1 / (2 * np.pi * freq[lo])]
    return np.array(g, dtype=float)


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------

def _weights(z: np.ndarray, weighting: str):
    if weighting == "modulus":
        m = np.abs(z)
        return m, m
    if weighting == "proportional":
        return np.maximum(np.abs(z.real), 1e-12), np.maximum(np.abs(z.imag), 1e-12)
    if weighting == "unit":
        one = np.ones(len(z))
        return one, one
    raise ValueError(f"weighting must be one of {WEIGHTINGS}")


def fit_circuit(circuit: Circuit | str, freq, z, *, guess: dict | None = None,
                fixed: dict | None = None, weighting: str = "modulus",
                n_starts: int = 40, seed: int = 0) -> FitResult:
    """Fit `circuit` to complex impedance `z` measured at `freq` (Hz).

    guess  : optional {param_name: value} starting values
    fixed  : optional {param_name: value} parameters held constant
    """
    if isinstance(circuit, str):
        circuit = Circuit(circuit)
    freq = np.asarray(freq, float)
    z = np.asarray(z, complex)
    names = circuit.param_names
    guess, fixed = dict(guess or {}), dict(fixed or {})
    for k in list(guess) + list(fixed):
        if k not in names:
            raise KeyError(f"Unknown parameter '{k}'. Parameters of {circuit.text}: {names}")

    p0 = initial_guess(circuit, freq, z)
    for k, v in guess.items():
        p0[names.index(k)] = float(v)
    fixed_mask = np.array([n in fixed for n in names])
    for k, v in fixed.items():
        p0[names.index(k)] = float(v)
    is_exp = np.array([k == "exponent" for k in circuit.param_kinds])
    free = ~fixed_mask

    def to_u(p):
        return np.where(is_exp, p, np.log10(np.abs(p)))[free]

    def from_u(u):
        p = p0.copy()
        pf = np.where(is_exp[free], u, 10.0 ** u)
        p[free] = pf
        return p

    wr, wi = _weights(z, weighting)

    def resid(u):
        zc = circuit.impedance(from_u(u), freq)
        r = np.concatenate([(zc.real - z.real) / wr, (zc.imag - z.imag) / wi])
        return np.where(np.isfinite(r), r, 1e6)

    lb = np.where(is_exp[free], 0.0, -15.0)
    ub = np.where(is_exp[free], 1.0, 15.0)
    u0 = np.clip(to_u(p0), lb + 1e-9, ub - 1e-9)

    rng = np.random.default_rng(seed)
    best = None
    for k in range(max(n_starts, 1)):
        if k == 0:
            us = u0
        else:
            span = 2.0 if k < n_starts // 2 else 3.0
            us = u0 + np.where(is_exp[free], 0, rng.uniform(-span, span, u0.size))
            us = np.where(is_exp[free], rng.uniform(0.5, 1.0, u0.size), us)
            us = np.clip(us, lb + 1e-9, ub - 1e-9)
        try:
            r = least_squares(resid, us, bounds=(lb, ub), method="trf",
                              x_scale="jac", max_nfev=4000)
        except Exception:  # pragma: no cover - numerical failure on a bad start
            continue
        if best is None or r.cost < best.cost:
            best = r
    if best is None:
        raise RuntimeError("Fit failed for every starting point")

    n = len(freq)
    n_free = int(free.sum())
    dof = max(2 * n - n_free, 1)
    wssr = float(2 * best.cost)
    chi2 = wssr / dof
    values = from_u(best.x)

    stderr = np.full(len(names), np.nan)
    try:
        J = best.jac
        cov = np.linalg.pinv(J.T @ J) * chi2
        su = np.sqrt(np.clip(np.diag(cov), 0, None))
        pf = values[free]
        stderr[free] = np.where(is_exp[free], su, pf * np.log(10) * su)
    except Exception:  # pragma: no cover
        pass

    return FitResult(circuit, values, stderr, fixed_mask, chi2, wssr, n, weighting,
                     bool(best.success), str(best.message),
                     (float(freq.min()), float(freq.max())))
