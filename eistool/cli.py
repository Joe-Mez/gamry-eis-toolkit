"""Command line interface."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .circuits import describe_elements


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:  # Windows consoles: make Ω, ², ° print correctly
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        prog="run_eis",
        description="Gamry DTA -> Excel, equivalent circuit fit, Nyquist/Bode figures, tables.")
    ap.add_argument("config", nargs="?", default="config.yaml",
                    help="configuration file (default: config.yaml)")
    ap.add_argument("--init", action="store_true",
                    help="create config.yaml listing every file in the data folder")
    ap.add_argument("--data", default="data", help="data folder used with --init (default: data)")
    ap.add_argument("--convert-only", action="store_true",
                    help="only convert DTA files to Excel (no fit, no plots)")
    ap.add_argument("--no-fit", action="store_true", help="plots and Excel without fitting")
    ap.add_argument("--no-ask", action="store_true",
                    help="do not ask for legend text (use config / last used labels)")
    ap.add_argument("--elements", action="store_true", help="list circuit elements and exit")
    a = ap.parse_args(argv)

    if a.elements:
        print("Circuit elements (series: '-', parallel: 'p(a,b)'):\n" + describe_elements())
        return 0

    cfg = Path(a.config)
    if a.init:
        from .pipeline import init_config
        if cfg.exists():
            ans = input(f"{cfg} exists. Overwrite? [y/N]: ").strip().lower() if sys.stdin.isatty() else "n"
            if ans not in ("y", "yes", "d", "da"):
                print("Nothing changed.")
                return 1
        path, files = init_config(cfg, a.data)
        print(f"Wrote {path} with {len(files)} system(s). Edit names, legends and circuit, then run again.")
        return 0

    if not cfg.exists():
        print(f"Config file '{cfg}' not found. Create one with:  python run_eis.py --init")
        return 1

    from .pipeline import run
    run(cfg, ask=not a.no_ask, convert_only=a.convert_only, no_fit=a.no_fit)
    print("\nDone. / Gotovo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
