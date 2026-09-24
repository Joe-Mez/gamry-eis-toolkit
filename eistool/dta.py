"""Reader for Gamry .DTA impedance files (and simple CSV/TXT/XLSX tables)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class EISData:
    """Impedance spectrum of one measured system.

    zreal / zimag are in ohm (raw instrument values). zimag keeps the
    instrument sign convention (negative for capacitive behaviour).
    """
    path: Path
    freq: np.ndarray
    zreal: np.ndarray
    zimag: np.ndarray
    area: float | None = None          # cm², from the DTA header if present
    header: dict = field(default_factory=dict)
    extra: pd.DataFrame | None = None  # all columns from the Gamry table

    @property
    def z(self) -> np.ndarray:
        return self.zreal + 1j * self.zimag

    @property
    def zmod(self) -> np.ndarray:
        return np.abs(self.z)

    @property
    def phase_deg(self) -> np.ndarray:
        return np.degrees(np.angle(self.z))


# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1250", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _num(s: str) -> float:
    """Parse a number that may use a decimal comma (European Windows locale)."""
    s = str(s).strip().strip("\"").strip("'").strip().replace("\u2212", "-")
    if not s:
        return np.nan
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def _find_col(cols: list[str], *candidates: str) -> int | None:
    low = [c.strip().lower() for c in cols]
    for cand in candidates:
        if cand.lower() in low:
            return low.index(cand.lower())
    return None


def read_dta(path: str | Path) -> EISData:
    """Read a Gamry DTA file and return the ZCURVE impedance table."""
    path = Path(path)
    lines = _read_text(path).splitlines()

    header: dict = {}
    tables: dict[str, tuple[list[str], list[list[str]]]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] and parts[1].strip().upper() == "TABLE":
            name = parts[0].strip().upper()
            cols = lines[i + 1].split("\t")[1:] if i + 1 < len(lines) else []
            j = i + 2  # skip the column-name row
            if j < len(lines):  # skip the unit row ("#  s  Hz  ohm ...") if present
                first = (lines[j].split("\t") + ["", ""])[1]
                if not np.isfinite(_num(first)):
                    j += 1
            rows = []
            while j < len(lines) and lines[j].startswith("\t") and lines[j].strip():
                rows.append(lines[j].split("\t")[1:])
                j += 1
            tables[name] = ([c.strip() for c in cols], rows)
            i = j
            continue
        if len(parts) >= 2 and parts[0] and not parts[0].startswith(" "):
            header[parts[0].strip().upper()] = (parts[2] if len(parts) >= 3 else parts[1]).strip()
        i += 1

    table_name = next((n for n in ("ZCURVE", "ZCURVE1") if n in tables), None)
    if table_name is None:
        cand = [n for n in tables if n.startswith("Z")]
        if not cand:
            raise ValueError(
                f"{path.name}: no impedance table (ZCURVE) found. "
                f"Tables in file: {list(tables) or 'none'}. Is this an EIS measurement?")
        table_name = cand[0]

    cols, rows = tables[table_name]
    if not rows:
        raise ValueError(f"{path.name}: the impedance table is empty (was the measurement aborted?)")
    data = np.array([[_num(v) for v in r[: len(cols)]] + [np.nan] * (len(cols) - len(r))
                     for r in rows], dtype=float)
    df = pd.DataFrame(data, columns=cols)

    fi = _find_col(cols, "Freq", "Frequency")
    ri = _find_col(cols, "Zreal", "Z'", "Zre")
    ii = _find_col(cols, "Zimag", "Z''", "Zim")
    if None in (fi, ri, ii):
        raise ValueError(f"{path.name}: could not find Freq/Zreal/Zimag columns in {cols}")

    freq, zr, zi = data[:, fi], data[:, ri], data[:, ii]
    ok = np.isfinite(freq) & np.isfinite(zr) & np.isfinite(zi) & (freq > 0)
    if ok.sum() < 3:
        raise ValueError(f"{path.name}: only {int(ok.sum())} valid impedance points")

    area = None
    if "AREA" in header:
        a = _num(header["AREA"])
        area = a if np.isfinite(a) and a > 0 else None

    return _sorted(EISData(path, freq[ok], zr[ok], zi[ok], area, header, df[ok].reset_index(drop=True)))


def _split(line: str, sep: str | None) -> list[str]:
    return line.split(sep) if sep else line.split()


def read_table(path: str | Path) -> EISData:
    """Read a generic table with columns: frequency, Z', Z'' (header and comment lines allowed).

    Separators: tab, semicolon, comma or spaces (decimal commas are fine with tab/semicolon/
    space separators). Z'' may be the instrument value (negative for capacitive) or -Z''
    (positive); it is taken as -Z'' when most values are positive.
    """
    path = Path(path)
    rows: list[list[float]] = []
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, header=None, dtype=object)
        for rec in df.itertuples(index=False):
            vals = [_num(str(v)) if v is not None else np.nan for v in rec[:3]]
            if len(vals) == 3 and all(np.isfinite(vals)):
                rows.append(vals)
    else:
        lines = [ln.strip() for ln in _read_text(path).splitlines()]
        lines = [ln for ln in lines if ln and not ln.startswith(("#", "%", "//", "!"))]

        def numeric_rows(sep):
            out = []
            for ln in lines:
                vals = [_num(v) for v in _split(ln, sep)[:3]]
                if len(vals) == 3 and all(np.isfinite(vals)):
                    out.append(vals)
            return out

        best = []
        for sep in ("\t", ";", ",", None):
            cand = numeric_rows(sep)
            if len(cand) > len(best):
                best = cand
        rows = best
    if len(rows) < 3:
        raise ValueError(f"{path.name}: expected at least 3 numeric columns (frequency, Z', Z'') "
                         f"and 3 rows, found {len(rows)} usable rows")
    arr = np.array(rows, dtype=float)
    arr = arr[arr[:, 0] > 0]
    freq, zr, zi = arr[:, 0], arr[:, 1], arr[:, 2]
    if np.mean(zi > 0) > 0.5:
        zi = -zi
    return _sorted(EISData(path, freq, zr, zi))


def _sorted(d: EISData) -> EISData:
    order = np.argsort(d.freq)[::-1]  # high -> low frequency, like Gamry
    d.freq, d.zreal, d.zimag = d.freq[order], d.zreal[order], d.zimag[order]
    if d.extra is not None:
        d.extra = d.extra.iloc[order].reset_index(drop=True)
    return d


def read_any(path: str | Path) -> EISData:
    path = Path(path)
    if path.suffix.lower() == ".dta":
        return read_dta(path)
    return read_table(path)


SUPPORTED = (".dta", ".csv", ".txt", ".xlsx")
