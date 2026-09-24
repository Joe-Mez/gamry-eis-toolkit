"""Equivalent circuit definitions.

Circuit strings use a simple, widely used notation (same as impedance.py):

    -        elements in series            R0-C1
    p(a,b)   elements in parallel          p(R1,CPE1)

Nesting is allowed:  R0-p(R1-p(R2,CPE2),CPE1)

Element types (the number after the letters is just an index you choose):

    R    resistor                     Z = R
    C    capacitor                    Z = 1 / (j w C)
    L    inductor                     Z = j w L
    CPE  constant phase element       Z = 1 / (Q (j w)^n)      (Q is an alias: Q1 == CPE1)
    W    semi-infinite Warburg        Z = sigma * (1 - j) / sqrt(w)
    Ws   finite Warburg, short (transmissive)   Z = R tanh(sqrt(j w T)) / sqrt(j w T)
    Wo   finite Warburg, open (reflective)      Z = R coth(sqrt(j w T)) / sqrt(j w T)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Element library
# ---------------------------------------------------------------------------
# For each element type: parameter suffixes, whether each parameter is strictly
# positive (fitted in log space) or bounded, a default guess, and units.
# Units are given for raw data ("ohm") and for area-normalised data ("ohm cm2").

ELEMENTS = {
    "R": {
        "params": [""],
        "units": {"raw": ["Ω"], "area": ["Ω cm²"]},
        "describe": "Resistor",
    },
    "C": {
        "params": [""],
        "units": {"raw": ["F"], "area": ["F cm⁻²"]},
        "describe": "Capacitor",
    },
    "L": {
        "params": [""],
        "units": {"raw": ["H"], "area": ["H cm²"]},
        "describe": "Inductor",
    },
    "CPE": {
        "params": ["_Q", "_n"],
        "units": {"raw": ["S sⁿ", "–"], "area": ["S sⁿ cm⁻²", "–"]},
        "describe": "Constant phase element",
    },
    "W": {
        "params": [""],
        "units": {"raw": ["Ω s⁻½"], "area": ["Ω cm² s⁻½"]},
        "describe": "Semi-infinite Warburg (sigma)",
    },
    "Ws": {
        "params": ["_R", "_T"],
        "units": {"raw": ["Ω", "s"], "area": ["Ω cm²", "s"]},
        "describe": "Finite-length Warburg, short (transmissive)",
    },
    "Wo": {
        "params": ["_R", "_T"],
        "units": {"raw": ["Ω", "s"], "area": ["Ω cm²", "s"]},
        "describe": "Finite-length Warburg, open (reflective)",
    },
}

_TOKEN_RE = re.compile(r"(CPE|Ws|Wo|Q|R|C|L|W)(\w*)")


def _canonical_type(prefix: str) -> str:
    return "CPE" if prefix in ("CPE", "Q") else prefix


def _element_impedance(etype: str, p: list[float], w: np.ndarray) -> np.ndarray:
    jw = 1j * w
    if etype == "R":
        return np.full_like(w, p[0], dtype=complex)
    if etype == "C":
        return 1.0 / (jw * p[0])
    if etype == "L":
        return jw * p[0]
    if etype == "CPE":
        return 1.0 / (p[0] * jw ** p[1])
    if etype == "W":
        return p[0] * (1 - 1j) / np.sqrt(w)
    if etype == "Ws":
        s = np.sqrt(jw * p[1])
        return p[0] * np.tanh(s) / s
    if etype == "Wo":
        s = np.sqrt(jw * p[1])
        return p[0] / (s * np.tanh(s))
    raise ValueError(f"Unknown element type {etype}")


# ---------------------------------------------------------------------------
# Parser -> tree
# ---------------------------------------------------------------------------

@dataclass
class Node:
    kind: str                      # "series", "parallel" or "element"
    children: list = field(default_factory=list)
    name: str = ""                 # element name, e.g. "CPE1"
    etype: str = ""                # canonical element type, e.g. "CPE"


class CircuitSyntaxError(ValueError):
    pass


class _Parser:
    def __init__(self, text: str):
        self.s = re.sub(r"\s+", "", text)
        self.i = 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def parse(self) -> Node:
        node = self.series()
        if self.i != len(self.s):
            raise CircuitSyntaxError(
                f"Unexpected character '{self.s[self.i]}' at position {self.i} in '{self.s}'")
        return node

    def series(self) -> Node:
        items = [self.term()]
        while self.peek() in ("-", "+"):
            self.i += 1
            items.append(self.term())
        return items[0] if len(items) == 1 else Node("series", items)

    def term(self) -> Node:
        if self.s.startswith("p(", self.i):
            self.i += 2
            items = [self.series()]
            while self.peek() == ",":
                self.i += 1
                items.append(self.series())
            if self.peek() != ")":
                raise CircuitSyntaxError(f"Missing ')' in '{self.s}'")
            self.i += 1
            if len(items) < 2:
                raise CircuitSyntaxError("p(...) needs at least two branches")
            return Node("parallel", items)
        if self.peek() == "(":
            self.i += 1
            node = self.series()
            if self.peek() != ")":
                raise CircuitSyntaxError(f"Missing ')' in '{self.s}'")
            self.i += 1
            return node
        m = _TOKEN_RE.match(self.s, self.i)
        if not m:
            raise CircuitSyntaxError(
                f"Cannot read an element at position {self.i} of '{self.s}'. "
                "Use R, C, L, CPE (or Q), W, Ws, Wo followed by an index, e.g. R1, CPE1.")
        self.i = m.end()
        prefix, idx = m.group(1), m.group(2)
        etype = _canonical_type(prefix)
        name = ("CPE" if etype == "CPE" else prefix) + idx
        return Node("element", name=name, etype=etype)


# ---------------------------------------------------------------------------
# Public circuit object
# ---------------------------------------------------------------------------

class Circuit:
    """A parsed equivalent circuit that can compute impedance."""

    def __init__(self, text: str):
        self.text = text.strip()
        self.tree = _Parser(self.text).parse()
        self.elements: list[Node] = []
        self._collect(self.tree)
        names = [e.name for e in self.elements]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise CircuitSyntaxError(f"Element names must be unique, repeated: {sorted(dup)}")
        self.param_names: list[str] = []
        self.param_types: list[str] = []   # element type for each param
        self.param_kinds: list[str] = []   # "log" (positive) or "exponent" (0..1)
        self._slices = {}
        for e in self.elements:
            start = len(self.param_names)
            for suf in ELEMENTS[e.etype]["params"]:
                self.param_names.append(e.name + suf)
                self.param_types.append(e.etype)
                self.param_kinds.append("exponent" if (e.etype == "CPE" and suf == "_n") else "log")
            self._slices[e.name] = slice(start, len(self.param_names))

    def _collect(self, node: Node):
        if node.kind == "element":
            self.elements.append(node)
        else:
            for c in node.children:
                self._collect(c)

    def units(self, normalised: bool) -> list[str]:
        key = "area" if normalised else "raw"
        out = []
        for e in self.elements:
            out.extend(ELEMENTS[e.etype]["units"][key])
        return out

    def impedance(self, params, freq) -> np.ndarray:
        w = 2 * np.pi * np.asarray(freq, dtype=float)
        params = np.asarray(params, dtype=float)
        return self._z(self.tree, params, w)

    def _z(self, node: Node, p, w):
        if node.kind == "element":
            return _element_impedance(node.etype, list(p[self._slices[node.name]]), w)
        zs = [self._z(c, p, w) for c in node.children]
        if node.kind == "series":
            return np.sum(zs, axis=0)
        return 1.0 / np.sum([1.0 / z for z in zs], axis=0)

    def __repr__(self):
        return f"Circuit('{self.text}', params={self.param_names})"


def describe_elements() -> str:
    lines = []
    for k, v in ELEMENTS.items():
        pars = ", ".join((k + "1" + s) for s in v["params"])
        lines.append(f"  {k:<4} {v['describe']:<45} parameters: {pars}")
    return "\n".join(lines)
