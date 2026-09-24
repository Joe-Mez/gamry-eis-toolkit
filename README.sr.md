# Gamry EIS alat

**[English: README.md](README.md)**

Jednom komandom od Gamry `.DTA` fajlova dobijate rezultate spremne za objavljivanje:

1. **Izvoz u Excel** za svaki izmereni sistem, sa imenima koja vi zadate
2. **Fit ekvivalentnog kola** koje vi izaberete (po potrebi različito za svaki sistem)
3. **Najkvistov i Bodeov dijagram** po standardima časopisa Elsevier / *Corrosion Science*
4. **Tabela rezultata** u Excelu, CSV-u i Word tabela spremna za rukopis

![Primer](docs/example_combined.png)

*Primer sa simuliranim podacima iz foldera `examples/` (čelik u 1 M HCl sa inhibitorom).*

---

## Šta grafici ispunjavaju

| Zahtev | Kako je rešeno |
|---|---|
| Najkvist u ortonormiranoj skali | Iste granice, isti razmak podeoka i odnos osa 1:1, pa polukrugovi izgledaju kao pravi polukrugovi |
| Bode moduo i fazni ugao na istom grafiku | log \|Z\| na levoj osi (puni markeri), −faza na desnoj osi (prazni markeri) |
| Isti uzorak uvek iste boje | Svaki sistem ima jednu boju i jedan oblik markera na Najkvistu, Bodeu i kombinovanoj slici |
| Program pita šta piše u legendi | Pri pokretanju pita za tekst legende za svaki sistem (Enter zadržava ponuđeno) |
| Linija fita na dijagramima | Puna linija u boji uzorka, u opsegu frekvencija koji je fitovan |
| Tabela | `EIS_results.xlsx` (list *Fit results*), `fit_results.csv`, `fit_table.docx` |
| Standard časopisa | Širina 90 mm (jedna kolona) ili 190 mm (dve kolone), Arial 8 pt, podeoci ka unutra, fontovi ugrađeni u PDF, TIFF 600 dpi, paleta čitljiva za daltoniste i različiti markeri, pa slika radi i u crno-beloj štampi |

## Instalacija (jednom)

Potreban je Python 3.9 ili noviji. Sa **Anaconda / Miniconda** (preporučeno na Windowsu):

```bash
conda env create -f environment.yml
conda activate eis
```

Ili sa pip-om:

```bash
pip install -r requirements.txt
```

## Upotreba

### Windows, bez komandne linije

1. Kopirajte `.DTA` fajlove u folder `data`.
2. Dvaput kliknite na `run_eis.bat`. Prvi put napravi `config.yaml` i otvori ga u Notepadu.
3. U `config.yaml` upišite ime i legendu za svaki sistem i ekvivalentno kolo. Sačuvajte i zatvorite.
4. Ponovo dvaput kliknite na `run_eis.bat`. Program pita za tekst legende, radi fit i sve snima u `results/`.

> Ako piše da `python` nije pronađen, otvorite **Anaconda Prompt**, ukucajte `conda activate eis`, uđite u ovaj folder (`cd`) i pokrenite `python run_eis.py`.

### Komandna linija

```bash
python run_eis.py --init          # pregleda data/ i napravi config.yaml
python run_eis.py                 # sve: pita za legendu, fit, grafici, tabele
python run_eis.py --no-ask        # koristi poslednju legendu, bez pitanja
python run_eis.py --convert-only  # samo DTA -> Excel
python run_eis.py --no-fit        # grafici i Excel bez fita
python run_eis.py --elements      # spisak elemenata kola
```

Probajte prvo na primeru:

```bash
cd examples
python ../run_eis.py
```

## Rezultati

```
results/
├── EIS_results.xlsx       Fit results | All systems | list po sistemu | Info
├── fit_results.csv        ista tabela fita kao CSV
├── fit_table.docx         tabela za rad (tri linije, jedinice, indeksi i eksponenti)
├── fit_report.txt         vrednosti fita sa relativnim greškama i χ²
├── legend_labels.yaml     tekst legende koji ste uneli (pamti se za sledeći put)
└── figures/
    ├── Nyquist.pdf/.tiff/.png          svi sistemi, 90 mm
    ├── Bode.pdf/.tiff/.png             svi sistemi, 90 mm
    ├── EIS_combined.pdf/.tiff/.png     (a) Najkvist (b) Bode, 190 mm
    └── individual/                     Najkvist i Bode za svaki sistem posebno
```

## Ekvivalentna kola

Redna veza je `-`, paralelna je `p(a,b)`. Kola se mogu ugnježdavati.

| Element | Značenje | Parametri |
|---|---|---|
| `R` | otpornik | `R1` |
| `C` | kondenzator | `C1` |
| `L` | induktivnost | `L1` |
| `CPE` ili `Q` | element konstantne faze, Z = 1 / (Q (jω)ⁿ) | `CPE1_Q`, `CPE1_n` |
| `W` | Warburg (polubeskonačna difuzija) | `W1` (σ) |
| `Ws` | konačni Warburg, propusni | `Ws1_R`, `Ws1_T` |
| `Wo` | konačni Warburg, reflektujući | `Wo1_R`, `Wo1_T` |

Česta kola:

| Kolo | Upotreba |
|---|---|
| `R0-p(R1,CPE1)` | jedna vremenska konstanta |
| `R0-p(CPE2,R2-p(R1,CPE1))` | film ili prevlaka plus prenos naelektrisanja (ugnježdeno) |
| `R0-p(R1,CPE1)-p(R2,CPE2)` | dve vremenske konstante redno |
| `R0-p(CPE1,R1-W1)` | prenos naelektrisanja sa difuzijom |

Svako ime elementa je jedna kolona u tabeli, zato isti fizički element neka ima isto ime u svim kolima (npr. uvek `R1` za otpor prenosa naelektrisanja). U `config.yaml` pod `parameter_labels` upišite kako se zove u tabeli (`R_ct`, `Q_dl`...).

### Detalji fita

* Kompleksni nelinearni metod najmanjih kvadrata (SciPy `least_squares`), realni i imaginarni deo zajedno
* Podrazumevano **težinski po modulu** (kao "calc-modulus" u ZView i Gamry Echem Analyst). Postoje i `proportional` i `unit`
* Početne vrednosti se procenjuju iz spektra, pa se proba 40 nasumičnih startova da se izbegnu lokalni minimumi. Možete zadati `initial_guess` ili `fixed` po sistemu
* Greške su standardne greške (1σ) iz Jakobijana, u % od vrednosti. χ² je težinska suma kvadrata podeljena brojem stepeni slobode
* Ako je greška nekog parametra veća od 50 %, program upozorava. To obično znači da kolo ima previše elemenata za te podatke

## Normalizacija na površinu

`area_cm2: auto` čita površinu elektrode iz DTA fajla i daje impedansu u Ω cm². Gamry upisuje 1 cm² ako pri merenju niste uneli pravu površinu, zato **proverite površinu koju program ispiše na početku**. Upišite broj (npr. `area_cm2: 0.785`) da je promenite, i po sistemu, ili `none` za rad u Ω.

## Upotreba sa Claude Code

`CLAUDE.md` objašnjava Claude Code-u kako da koristi ovaj alat. Otvorite folder u Claude Code-u i napišite, na primer: *"Fituj moje DTA fajlove kolom R0-p(R1,CPE1) i nacrtaj Najkvist i Bode"*. Claude će pitati za imena sistema i legendu, pa pokrenuti alat.

## Licenca

MIT
