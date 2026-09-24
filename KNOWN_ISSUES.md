# Known issues

**Srpski:** Ovo su poznati retki slučajevi koji još nisu rešeni. Većina se tiče neobičnih ulaznih fajlova, ne Gamry DTA fajlova. Ako vam se nešto od ovoga desi, pogledajte kolonu *Workaround*. Ako naiđete na problem koji nije ovde, pošaljite poruku o grešci i DTA fajl.

These are rare cases that are known and not yet fixed. They came out of an independent code review and an adversarial debugging pass (September 2026). Everything else those reviews found was fixed and has a regression test in `tests/test_review_fixes.py`.

Normal Gamry `.DTA` files from EISPOT or EISGALV measurements are not affected by the input issues below. Most of them only apply to hand-made CSV/TXT/XLSX tables.

Severity: **silent** means the program runs but the result can be wrong without a warning. **loud** means it stops or warns.

## Reading data

| # | Issue | Severity | Workaround | Where |
|---|---|---|---|---|
| 1 | **Numbers with thousands separators** (`1,234.5`, `1.234,5`, `1 234,5`) are not parsed. The whole row is dropped without a warning. Plain decimal commas (`1234,5`) work. | silent | Export without thousands separators. Check the point count printed at the start of each run. | `eistool/dta.py` `_num` |
| 2 | **A blank line inside the ZCURVE table** ends the table there. The points after it are lost without a warning. Gamry does not write blank lines, so this only happens after hand-editing. | silent | Do not edit DTA files by hand, or remove the blank line. Check the point count. | `eistool/dta.py` `read_dta` |
| 3 | **UTF-16 files without a byte-order mark** are reported as "no impedance table (ZCURVE) found". UTF-16 with a BOM works. | loud | Re-save the file as UTF-8 or ANSI. | `eistool/dta.py` `_read_text` |
| 4 | **Generic tables must have frequency, Z′, Z″ as the first three columns.** Header names are ignored. A leading index column (`Pt`) is read as the frequency. | silent | Delete extra columns so the first three are frequency, Z′, Z″. | `eistool/dta.py` `read_table` |
| 5 | **Comma-separated CSV that also uses decimal commas** (`1e5,10,5,-0,5`) cannot be split correctly. Values end up in the wrong columns. | silent | Use a semicolon or tab separator with decimal commas. | `eistool/dta.py` `read_table` |
| 6 | **Sign of Z″ in generic tables is guessed.** If more than half of the Z″ values are positive, the column is treated as −Z″ and flipped. A spectrum that is mostly inductive would be flipped by mistake. | silent | Give Z″ with the instrument sign (negative for capacitive). | `eistool/dta.py` `read_table` |

## Circuits and fitting

| # | Issue | Severity | Workaround | Where |
|---|---|---|---|---|
| 7 | **Element names are matched by their first letters.** A name starting with `Ws` or `Wo` is always a finite Warburg, so `Wsig` becomes a two-parameter element. | silent | Use a letter code plus a number, as documented: `R1`, `CPE2`, `W1`. | `eistool/circuits.py` `_TOKEN_RE` |
| 8 | **Large errors are approximate.** Errors come from a linear approximation, so they are symmetric. Above about 30 % they are only a rough guide. The Word table footnote says so. | informational | Treat errors above 30 % as "poorly determined", not as exact confidence intervals. | `eistool/fitting.py` `_standard_errors` |
| 9 | **A CPE exponent sitting exactly at n = 1 is not flagged.** Its error ignores the upper limit. | informational | If n = 1.000, the element behaves as an ideal capacitor. Consider replacing CPE with C. | `eistool/fitting.py` `_standard_errors` |
| 10 | **Nearly redundant circuits get large errors, not "not determined".** Only exact redundancy is reported as "not determined". Near-redundancy shows up through the >50 % error warning. | informational | Read the warning lines in `fit_report.txt`. | `eistool/fitting.py` |

## Output

| # | Issue | Severity | Workaround | Where |
|---|---|---|---|---|
| 11 | **Mixed area normalisation.** If some systems are in Ω cm² and others in Ω, table headers read "Ω cm² or Ω". The unit per row is only visible in the *Area used* column. A warning is printed. | loud | Set `area_cm2` the same way for all systems. | `eistool/report.py` `_param_columns` |
| 12 | **Old results are not cleaned up.** A `--no-fit` run leaves `fit_table.docx`, `fit_results.csv` and `fit_report.txt` from an earlier fit in `results/`. | silent | Delete `results/` before a new analysis, or check the file dates. | `eistool/pipeline.py` `run` |
| 13 | **Legend math in the Word table is simplified.** Sub/superscripts and `\mathregular{}` are converted. Other commands such as `$\alpha$` or `$\times$` appear as the words "alpha" and "times". The figures are not affected. | cosmetic | Type the symbol directly (α, ×) instead of using a math command. | `eistool/report.py` `_add_label` |
| 14 | **More than 8 systems.** Colours repeat after 8. Each system still gets a different colour and marker combination (13 marker shapes). Figures with that many curves are hard to read. | cosmetic | Split into several figures, or set `color:` per system. | `eistool/style.py` |
| 15 | **Unusual config values** that the checks do not cover may still produce an "Unexpected error" message with technical details instead of a plain explanation. | loud | Send the full message. Common mistakes are already explained in plain language. | `eistool/pipeline.py` `load_config`, `collect_systems` |

## Windows

| # | Issue | Severity | Workaround | Where |
|---|---|---|---|---|
| 16 | **Windows may block the launcher the first time** ("Windows protected your PC") because the file came from the internet. | loud | Click **More info**, then **Run anyway**. | `run_eis.bat` |
| 17 | **Conda is found only in standard folders or on PATH.** Miniconda installed somewhere unusual is missed, and the launcher falls back to a normal Python install or reports that Python was not found. | loud | Run from Anaconda Prompt: `conda activate gamry-eis` then `python run_eis.py`. | `run_eis.bat` |
| 18 | **The interactive legend prompt has not been tested on a Windows keyboard.** It was tested on Linux. The rest of the launcher and the full analysis were tested on Windows 11. | untested | If typing at the prompt misbehaves, set `ask_legend: false` and put the legend text in `config.yaml`. | `eistool/pipeline.py` `ask_legends` |

## Reporting a new problem

Open an issue on GitHub, or send the maintainer:

1. the full text shown in the console window
2. `config.yaml`
3. one DTA file that shows the problem

When fixing one of the issues above, add a test to `tests/test_review_fixes.py` and remove the row from this file.
