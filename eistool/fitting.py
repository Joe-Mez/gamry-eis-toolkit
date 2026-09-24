"""Complex non-linear least-squares fitting of equivalent circuits."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .circuits import Circuit
from .errors import UserError

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
    flags: list = field(default_factory=list)   # per parameter: "", "undetermined", "at bound"
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
    """Weights (denominators) for real and imaginary residuals, from the measured data.

    modulus      : |Z| for both parts (data-modulus weighting; robust default)
    proportional : |Z'| and |Z''| separately, floored at 5 % of |Z| so that points
                   where one part is close to zero do not dominate the fit
    unit         : no weighting
    """
    m = np.abs(z)
    if weighting == "modulus":
        return m, m
    if weighting == "proportional":
        floor = 0.05 * m
        return np.maximum(np.abs(z.real), floor), np.maximum(np.abs(z.imag), floor)
    if weighting == "unit":
        one = np.ones(len(z))
        return one, one
    raise UserError(f"fit weighting must be one of {', '.join(WEIGHTINGS)} (got '{weighting}').")


LOG_BOUND = 15.0  # positive parameters are fitted as log10(value) within +-15 decades


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
    weighting = str(weighting).strip().lower()
    names = circuit.param_names
    guess, fixed = dict(guess or {}), dict(fixed or {})
    for k in list(guess) + list(fixed):
        if k not in names:
            raise UserError(f"Unknown parameter '{k}' for circuit {circuit.text}. "
                            f"Its parameters are: {', '.join(names)}")
    is_exp = np.array([k == "exponent" for k in circuit.param_kinds])
    for src, dct in (("initial_guess", guess), ("fixed", fixed)):
        for k, v in dct.items():
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise UserError(f"{src} value for {k} must be a number (got '{v}').") from None
            if is_exp[names.index(k)]:
                if not 0 <= v <= 1:
                    raise UserError(f"{src} value for {k} must be between 0 and 1 (got {v}).")
            elif v <= 0:
                raise UserError(f"{src} value for {k} must be greater than 0 (got {v}).")
            dct[k] = v

    n = len(freq)
    fixed_mask = np.array([n_ in fixed for n_ in names])
    free = ~fixed_mask
    n_free = int(free.sum())
    if n == 0:
        raise UserError("No data points to fit (check freq_min / freq_max).")
    if 2 * n <= n_free:
        raise UserError(f"Only {n} data points for {n_free} free parameters in {circuit.text}. "
                        f"At least {n_free // 2 + 1} points are needed, more in practice.")

    p0 = initial_guess(circuit, freq, z)
    for k, v in guess.items():
        p0[names.index(k)] = v
    for k, v in fixed.items():
        p0[names.index(k)] = v

    def to_u(p):
        return np.where(is_exp, p, np.log10(np.abs(p)))[free]

    def from_u(u):
        p = p0.copy()
        p[free] = np.where(is_exp[free], u, 10.0 ** u)
        return p

    wr, wi = _weights(z, weighting)

    def resid(u):
        zc = circuit.impedance(from_u(u), freq)
        r = np.concatenate([(zc.real - z.real) / wr, (zc.imag - z.imag) / wi])
        return np.where(np.isfinite(r), r, 1e6)

    lb = np.where(is_exp[free], 0.0, -LOG_BOUND)
    ub = np.where(is_exp[free], 1.0, LOG_BOUND)

    best = None
    if n_free == 0:
        values = p0.copy()
        r0 = resid(np.array([]))
        wssr = float(r0 @ r0)
        dof = 2 * n
        return FitResult(circuit, values, np.full(len(names), np.nan), fixed_mask, wssr / dof,
                         wssr, n, weighting, True, "all parameters fixed",
                         (float(freq.min()), float(freq.max())), [""] * len(names))

    u0 = np.clip(to_u(p0), lb + 1e-9, ub - 1e-9)
    rng = np.random.default_rng(seed)
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

    dof = 2 * n - n_free
    wssr = float(2 * best.cost)
    chi2 = wssr / dof
    values = from_u(best.x)
    stderr, flags = _standard_errors(best, values, free, is_exp, lb, ub, chi2)

    return FitResult(circuit, values, stderr, fixed_mask, chi2, wssr, n, weighting,
                     bool(best.success), str(best.message),
                     (float(freq.min()), float(freq.max())), flags)


def _standard_errors(best, values, free, is_exp, lb, ub, chi2):
    """1-sigma errors from the Jacobian, with honest handling of unidentifiable parameters.

    A parameter is 'undetermined' when it lies along a (near-)null direction of the
    Jacobian: the data cannot tell it apart from other parameters (e.g. two resistors
    in series). Its error is reported as infinite instead of the misleadingly small
    value a pseudo-inverse would give. A parameter pinned at its search bound is
    reported as 'at bound' with no error.
    """
    n_all = len(values)
    stderr = np.full(n_all, np.nan)
    flags = [""] * n_all
    free_idx = np.flatnonzero(free)
    J = np.asarray(best.jac, float)
    x = best.x

    at_bound = np.zeros(len(free_idx), bool)
    for j in range(len(free_idx)):
        if is_exp[free_idx[j]]:
            at_bound[j] = x[j] <= lb[j] + 1e-6          # n stuck at 0 (n = 1 is physical)
        else:
            at_bound[j] = (x[j] <= lb[j] + 1e-3) or (x[j] >= ub[j] - 1e-3)

    # Parameters stuck at a search limit carry (almost) no information: take them out
    # before looking for redundant combinations, or their near-zero columns leak into the
    # null space and wrongly flag well-determined neighbours.
    keep = ~at_bound
    Jk = J[:, keep]
    try:
        _, s, vt = np.linalg.svd(Jk, full_matrices=False)
    except np.linalg.LinAlgError:  # pragma: no cover
        return stderr, flags
    tol = s[0] * 1e-7 if s.size and s[0] > 0 else 0.0
    null = vt[s <= tol] if s.size else np.empty((0, int(keep.sum())))
    undetermined_k = np.zeros(int(keep.sum()), bool)
    pf = values[free_idx][keep]
    exp_f = is_exp[free_idx][keep]
    for v in null:
        involved = np.abs(v) > 1e-3          # part of this redundant combination (not numerical noise)
        # Direction in linear parameter space along which the model does not change.
        dp = np.where(exp_f, v, v * np.log(10) * pf)
        # How far can we move before an involved parameter leaves its physical range
        # (positive values > 0, CPE exponents 0..1)?
        t_lo, t_hi = -np.inf, np.inf
        for k in np.flatnonzero(involved):
            if exp_f[k]:
                a, b = (0 - pf[k]) / dp[k], (1 - pf[k]) / dp[k]
            else:
                a, b = -pf[k] / dp[k], (np.inf if dp[k] > 0 else -np.inf)
            t_lo, t_hi = max(t_lo, min(a, b)), min(t_hi, max(a, b))
        with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
            reach = np.maximum(np.abs(t_lo * dp), np.abs(t_hi * dp))
            rel = np.where(exp_f, reach, reach / np.abs(pf))
        rel = np.nan_to_num(rel, nan=0.0, posinf=np.inf)
        undetermined_k |= involved & (rel > 0.5)
    undetermined = np.zeros(len(free_idx), bool)
    undetermined[keep] = undetermined_k
    good = s > tol
    su = np.full(len(free_idx), np.nan)
    if np.any(good):
        cov = (vt[good].T / s[good] ** 2) @ vt[good] * chi2
        su[keep] = np.sqrt(np.clip(np.diag(cov), 0, None))

    for j, i in enumerate(free_idx):
        if at_bound[j]:
            flags[i] = "at bound"
            continue
        if undetermined[j]:
            flags[i] = "undetermined"
            stderr[i] = np.inf
            continue
        stderr[i] = su[j] if is_exp[i] else values[i] * np.log(10) * su[j]
    return stderr, flags
