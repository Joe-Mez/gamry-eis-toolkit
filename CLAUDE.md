# Instructions for Claude Code

This repo processes electrochemical impedance spectroscopy (EIS) data from Gamry potentiostats.
The user is usually a corrosion or materials researcher. They may write in Serbian. Reply in
the language they use.

## Workflow the user expects

1. **Import.** DTA files go in `data/`. Run `python run_eis.py --init` to create `config.yaml`
   listing every file. Ask the user what each system is called (`name`) and what the legend
   should say (`legend`), then write those into `config.yaml`.
2. **Fit.** Ask the user for the equivalent circuit if they have not given one. Write it as
   `circuit:` (global) or per system. Syntax: `-` series, `p(a,b)` parallel, elements
   R, C, L, CPE (Q), W, Ws, Wo. Run `python run_eis.py --elements` to list them.
   Keep element names consistent across systems: the same name = the same table column.
3. **Plots.** Always ask the user what the legend should say before the final run, unless they
   already told you. Because Claude Code has no interactive stdin, run with `--no-ask` after
   putting the legend text in `config.yaml`.
4. **Table.** Set `table.parameter_labels` so the Word table shows R_ct, Q_dl, etc.

Then run `python run_eis.py --no-ask` and report the fitted values from `results/fit_report.txt`.
Look at `results/figures/*.png` before saying the figures are done.

## Figure rules (do not break these)

* Nyquist: orthonormal (equal aspect, same limits and ticks on both axes)
* Bode: |Z| and phase on the same graph (twin y-axes), filled markers = |Z|, open = phase
* Each sample keeps the same colour and marker on every figure
* Fit shown as a solid line in the sample colour
* Elsevier / Corrosion Science style: exactly 90 mm or 190 mm wide, Arial 8 pt, PDF + 1000 dpi RGB TIFF

## Check the fit before reporting

* Area: the run prints the electrode area. Gamry's default is 1 cm². Ask the user for the real
  area if the printed value looks like a default and they want Ω cm².
* Parameters reported as "not determined" (± inf), "hit the search limit", errors > 50 % or n outside 0.5 to 1 usually mean the circuit is over-parameterised or the
  wrong model. Say so and suggest a simpler circuit, `fixed` values, or a `freq_min`/`freq_max`
  window (e.g. to drop low-frequency scatter or an inductive tail).
* χ² around 1e-3 or lower is a good fit with modulus weighting.

## Code map

* `eistool/dta.py` Gamry DTA reader (handles decimal commas, OCV blocks, encodings)
* `eistool/circuits.py` circuit parser and impedance of each element
* `eistool/fitting.py` CNLS fit with multi-start, standard errors, χ²
* `eistool/plotting.py` Nyquist, Bode, combined figures
* `eistool/style.py` journal style, colour palette, marker shapes
* `eistool/report.py` Excel workbook, CSV, Word table
* `eistool/pipeline.py` config handling and the end-to-end run
* `tests/` run with `pytest`
