#!/usr/bin/env python
"""Run the EIS workflow.  Usage:  python run_eis.py [config.yaml] [--no-ask] [--convert-only]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eistool.cli import main  # noqa: E402

raise SystemExit(main())
