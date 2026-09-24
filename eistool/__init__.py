"""Gamry EIS toolkit: DTA import, equivalent circuit fitting and publication figures."""
from .circuits import Circuit
from .dta import EISData, read_any, read_dta
from .fitting import FitResult, fit_circuit

__all__ = ["Circuit", "EISData", "FitResult", "fit_circuit", "read_any", "read_dta"]
__version__ = "1.0.0"
