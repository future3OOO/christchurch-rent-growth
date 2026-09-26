---
name: christchurch-rent-growth
description: Use when asked to update, recalculate, verify, or chart Christchurch City rent growth from MBIE / Tenancy Services rental bond data, or to draft a Christchurch rent-review recommendation for a landlord.
---

# Christchurch rent growth

Chart Christchurch City rent growth from the **latest** MBIE / Tenancy Services monthly territorial-authority rental-bond release, and draft the landlord's rent-review message from it. Each release changes the CSV filename, the data end month, and the page's "Last updated" date, so every run rediscovers them from the official page; nothing from an earlier run or another machine is reused.

This skill folder ships everything the run needs; resolve these paths relative to this `SKILL.md`:

- `scripts/christchurch_rent_growth.py` — the whole pipeline: download, freshness checks, calculation, outputs, chart, validation. It fails closed with a `VALIDATION FAILED` or `DOWNLOAD FAILED` line.
- `references/` — frozen regression fixtures the script recomputes before every run (see [Regression fixtures](#regression-fixtures)).

## Run

1. **Ask first**: your opening message asks for the property address and current weekly rent, unless the request already gives both, then waits for the reply. Done when you have both.
2. **Project directory**: the directory the agent session was opened in. Outputs always go to `<project>/runs/<YYYY-MM-DD>/` (local run date), with source evidence in its `source/` subfolder. A same-day re-run replaces that day's outputs.
3. **Interpreter**: find Python 3.8+ that can `import matplotlib`. If none can, create `<project>/runs/.venv`, install `matplotlib` into it, and use its interpreter — `runs/.venv/bin/python` on macOS/Linux, `runs\.venv\Scripts\python.exe` on Windows. Reuse that environment on later runs. If Python or package installation is unavailable, report that blocker.
4. **Execute** with absolute, quoted paths (project paths often contain spaces):
   `"<python>" "<skill-dir>/scripts/christchurch_rent_growth.py" --project-dir "<project>" --current-rent <weekly rent>`
   Done when it prints the release, results, `Proposed rent` line, and four output paths. On any failure line, stop and report it; never build the chart or numbers another way.
5. **Inspect** the PNG against the [chart contract](#chart-contract): no clipped text, no point label touching the line, another label, or the legend, and a legible footer. Fix layout problems in the script, then re-run and re-inspect.
6. **Report** the release, data end month, both periods' lodged bonds and pooled geometric means, the overall change, and the actual output paths (attach the files if the host supports it). The monthly values are on the chart; do not repeat them in a table. End with the [landlord message](#landlord-message).

### When Python cannot download

If the script prints `DOWNLOAD FAILED` (blocked network, missing CA certificates), use any other available tool — curl, a browser, a web download — to save the raw bytes of the official landing page and of the CSV that page links as "By territorial authority", then re-run with `--page-html "<page file>" --csv "<csv file>"` added. The script still takes every freshness value from the saved page. A search snippet, rendered preview, or previously downloaded file is not a substitute; if the current page and CSV cannot both be obtained, stop and report that freshness could not be verified.

## Landlord message

Tell the user the proposed rent is rounded to the nearest $5, quoting the unrounded figure from the `Proposed rent` line; the landlord message itself does not mention rounding. Introduce it as an example message for the landlord that may need adjusting, then give the filled template as plain text inside a `text` code block, so copying it picks up no quote markers or other formatting:

```text
We've carried out a rent review for [property address], based on MBIE bond lodgement data for Christchurch over the past 12 months. We'd recommend increasing the rent from $[current rent] to $[proposed rent] per week.

Christchurch rents have gone up around [X]% over the past 12 months (see attached), so this change brings it more in line with the current market.

Please let me know your thoughts, and we'll send the required 60-day rent increase notice through to the tenants once confirmed.
```

[proposed rent] comes from the script's `Proposed rent` line: current rent × (1 + overall change), rounded to the nearest $5. [X] is the overall 12-month change to one decimal, as in the chart legend. The attachment is the chart PNG. If the overall change is zero or negative, send no increase message; tell the user rents did not rise.

## Freshness evidence

Read from the official page `https://www.tenancy.govt.nz/about-tenancy-services/data-and-statistics/rental-bond-data/` on every run. Values change monthly; the page positions below are what stays fixed.

| Evidence | Where on the page | Use |
|---|---|---|
| Advertised end month | Heading `Rental bond data, <Month Year> to <Month Year>`; the CSV link text must end at the same month | Must equal the latest month in the downloaded CSV |
| Release label | `Last updated <day> <Month> <Year>` line directly below that heading | `<Month> <Year>` in the chart footer and summary |
| CSV URL | The one link whose text starts `By territorial authority` (not the regional or quarterly files) | Download source |
| Provisional-data warning | The `Important:` notice, when present | Recorded in the summary JSON only; not repeated in chat |

The page instructs users to always take the latest file because recent months are revised as bonds are processed; a stale or mismatched file is a failure, never a fallback.

## Source file

MBIE has changed the file layout between releases; the script accepts exactly these two and fails on anything else:

| Releases | Month, location, bonds, mean columns | Month format | Numbers |
|---|---|---|---|
| September 2026 onward | `TimeFrame`, `location`, `LodgedBonds`, `GeometricMeanRent` (UTF-8 with byte-order mark) | `1/07/2026` | plain |
| August 2026 and earlier | `Time Frame`, `Location`, `Lodged Bonds`, `Geometric Mean Rent` (every field quoted) | `2026-06-01` | thousands commas (`"1,101"`) |

Every row is the first of a month; `Christchurch City` must match exactly, once per month, with positive bond counts and means. When MBIE introduces a new layout, add it to `FORMATS` in the script and prove it against that release's independently calculated results rather than loosening the parser.

## Calculation

Latest window: the 12 consecutive months ending at the advertised end month. Previous window: the same 12 months one year earlier.

- Monthly `YoY % = (G_month / G_same_month_previous_year - 1) * 100`, from MBIE's published geometric mean weekly rent.
- Pooled window mean `G = exp(sum(n_m * ln(G_m)) / sum(n_m))`, weighted by monthly `LodgedBonds`.
- `Overall % = (G_latest_window / G_previous_window - 1) * 100`.

The pooled figure is reconstructed from MBIE's published, rounded monthly geometric means; never describe it as a transaction-level geometric mean. Never substitute median rent, an arithmetic mean, an average of monthly YoY values, or an unweighted mean.

## Outputs

In `runs/<YYYY-MM-DD>/`, named `MBIE_Christchurch_Rent_Growth_to_<Month>_<Year>` after the data end month:

- `.pdf` and `.png` — the chart.
- `.csv` — columns `index,Month,Previous,Latest,YoY Change %`; 12 rows, full month labels (`August 2025`), unrounded values.
- `_summary.json` — page and CSV URLs, retrieval method and time, page evidence, release label, source and script SHA-256, both windows' date ranges, lodged bonds and pooled means, overall change, chart dashed-line value, monthly YoY values, method note, provisional-data warning.
- `source/` — the landing page and CSV exactly as analysed.

## Chart contract

- 4:3 white figure. Title **Christchurch City rent growth**; subtitle lines **Year-on-year change in MBIE geometric mean weekly rent** and the latest window's range, e.g. **August 2025 to July 2026**.
- Blue line with circular markers for the 12 monthly YoY values.
- A label on every point, signed to one decimal (`+2.6%`, `-0.4%`), placed where the line is not: above a peak, below a trough, upper-left of a rising point, upper-right of a falling point; a label that would sit on the dashed line moves clear of it.
- Orange dashed horizontal line at the pooled overall change; grey zero baseline; light horizontal gridlines.
- Frameless legend above the plot, right-aligned with its top-right corner and level with the subtitle, clear of the axes, gridlines, line, and point labels. Labels: `Monthly year-on-year change`, `Overall 12-month change: +X.X%`.
- Y-axis **Change from same month a year earlier (%)**; x-axis abbreviated month names only.
- Footer: `Source: MBIE / Tenancy Services, detailed monthly territorial-authority rental bond data, Christchurch City, <release label> release. Overall 12-month geometric mean is pooled from MBIE monthly geometric means weighted by lodged bonds.`

## Checks

The script fails the run, writing no chart from partial or stale data, unless every one holds:

- The CSV link was resolved from the current page, and the page's heading, link text, and CSV all end at the same month.
- The header matches one known layout and every month parses; `Christchurch City` has exactly one row per month and a same-month prior-year row for all 12 months; means and bond counts are positive.
- Every regression fixture reproduces its expected results.
- The analysis CSV has 12 rows and each stored YoY value recomputes from `Previous` and `Latest`.
- The chart's dashed-line value equals the summary JSON's overall change.

## Regression fixtures

Each `references/<release>.json` names a frozen CSV of that release's 24 Christchurch rows (original header and layout kept) and its expected 12 monthly YoY values, both windows' lodged-bond totals and pooled geometric means, and overall change. Before touching live data, the script recomputes every fixture and requires a match; if the live CSV is byte-identical to a fixture's source (same SHA-256), the live results must match it too.

Fixtures prove the code, not the current release, so they come from a release **older** than the live one: every live run is then out-of-sample, the same situation as the next release arriving. The current fixture is the August 2026 release (data to June 2026, older layout), with expected values calculated independently of the script. Live numbers differing from the fixture is expected. Add a fixture only when a release changes the layout or exposes a bug, with its expected values calculated outside the script and reviewed by the user; never generate a fixture from the script's own output.
