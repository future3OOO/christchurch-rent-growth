---
name: christchurch-rent-growth
description: Create bedroom-specific property rental reports comparing a named suburb plus adjoining areas with Christchurch City using Tenancy Services bond data, rolling arithmetic means, annual medians and bond lodgements since a chosen rent-review date.
---

# Property rent review and bond report

Use the production MBIE / Tenancy Services Market Rent API. The default deliverable is a branded PDF comparing the named suburb and its adjoining statistical areas with Christchurch City for the **same bedrooms, dwelling type and dates**. Run `scripts/rent_review.py`; do not rewrite the workflow in each chat.

## Intake

Use the native question form for missing inputs (`request_user_input_async` in Codex Desktop). Send one batch with a separate field for each missing detail. Use selectors for fixed choices and text entry for addresses, dates and dollar amounts. Wait for submitted answers; a preselected option is not confirmation. If the host has no form, use one short labelled line per missing field.

Use details already supplied in the conversation or verified for the exact property. After a partial reply, ask only for the fields still needed. Keep methodology and repeated scope summaries out of intake.

| Field | Control and prompt |
|---|---|
| Address and suburb | Text: "What is the street address and suburb?" If only one is missing, ask for that part. |
| Bedrooms | Selector: 1, 2, 3, 4, 5, 5+. Keep 5 and 5+ separate. |
| Dwelling type | Selector: House / townhouse, Flat / bedsit, Apartment, Boarding house room, Room. Pass `House`, `Flat`, `Apartment`, `BoardingHouse`, or `Room` respectively. |
| Comparison period | If missing, offer "Past 12 months" and "Since the last rent review". For the latter, ask for the review month if unknown. Accept a custom period or date directly. |
| Current weekly rent | Text: "What is the current weekly rent (NZD)?" Ask when a dollar recommendation is wanted; the report can proceed without it. |

Use `ALL` (All bedrooms or All dwelling types) for an explicitly requested aggregate comparison. For an ambiguous "unit", ask which dwelling category fits. A unit number or a neighbouring listing does not establish the type. Use the confirmed type for both markets and verify it appears with the bedroom count in the PDF heading. [Tenancy Services dwelling definitions](https://www.tenancy.govt.nz/rent-bond-and-bills/market-rent/market-rent-explained/)

Default to the named suburb plus adjoining areas. For "past 12 months", compare the latest eligible end month with the same month a year earlier. The latest eligible month is two calendar months before the current local month; validate returned coverage. For a review date, use its calendar month as the rolling annual baseline. State the actual windows with the result.

## Geography

Use the **named suburb** to select the starting SA2. The address is for verification and the report heading. A point-in-polygon assignment never determines the starting area. For example, a Burwood address inside the Travis Wetlands statistical area still starts from Burwood 325600 when Burwood is the supplied suburb.

The bundled [Christchurch address and rent-area index](references/christchurch-address-index.sqlite) resolves the supplied suburb, optionally verifies the address, and returns the verified API codes and neighbouring areas in one local run:

```text
"<python>" "<skill-dir>/scripts/rent_review.py" --lookup --suburb "Burwood"
```

- An exact Christchurch statistical area name takes precedence. Mairehau uses Mairehau North 321700 and Mairehau South 323100. Richmond uses Richmond North 325900 and Richmond South 326800. Somerfield uses Somerfield East 329100 and Somerfield West 329200. For other suburbs with only partial name matches, present the candidates and confirm the intended grouping. For an unmatched suburb, ask which named area represents the intended market. Use --area-codes only for an explicitly confirmed selection from the matching area names and their adjoining areas.
- By default, include the starting areas and the union of areas sharing a boundary stretch with them. Deduplicate the codes. Point-only contacts are excluded. The lookup flags neighbours outside Christchurch City so their inclusion is visible. Use `--no-include-adjoining` only for an explicit suburb-only or exclusion request. For specific exclusions, also supply the confirmed set with `--area-codes`. Confirming a split suburb selects the starting areas and leaves adjoining areas enabled.
- The bundled [2019 SA2 boundaries and neighbours](references/christchurch-sa2-2019.geojson) support map verification and list shared boundary lengths. The address index is a snapshot of LINZ address data. Confirm unresolved address or suburb discrepancies with the user. The selected market stays anchored to the supplied suburb.
- Christchurch City is TA2019 060. Name the actual combined areas in the summary and use a short local label in the standard PDF.

The website market-rent tool uses NZAD suburb regions. Before treating a website/API difference as an error, match geography, dates, bedrooms, dwelling type, measure and bond population. Website medians are not arithmetic means. Do not assume its bond count means API nLodged or nCurr. An unresolved-boundary warning is not required on the report; label the actual selected areas accurately.

## API and configuration

- Production base: https://api.business.govt.nz/gateway/tenancy-services/market-rent/v2/
- Documentation: https://portal.api.business.govt.nz/api/market-rent
- Authentication header: Ocp-Apim-Subscription-Key; JSON responses.
- Set `MBIE_MARKET_RENT_API_KEY`, or create a local `api_credentials.json` beside this skill with the key under `production.primary_key`. The environment variable takes precedence. Never print keys or include auth headers in evidence.

This is the statistical Market Rent API, not the transactional Tenancy Bond API. Do not substitute sandbox, CSV, invented values or stale periods on failure.

The runner looks up codes locally and queries both markets sequentially in 12-month windows using the selected bedroom and dwelling filters. A multi-area comparison uses the direct area=ALL result when all requested areas are listed. If the breakdown omits an area, request and validate a named aggregate for the same codes. The validated result feeds the standard PDF. Reject missing, duplicate, suppressed, wrong-period or wrong-geography aggregates.

## Run

Use Python 3.10 or newer. Offline lookup uses SQLite. Reports also require Matplotlib and a Market Rent API key. If uv is available, try the report command below with `uv run --offline --with matplotlib python` in place of `"<python>"`. This reuses cached packages. Otherwise select an existing Python that can import Matplotlib before installing anything. The runner writes both the PDF and its PNG preview.

```text
"<python>" "<skill-dir>/scripts/rent_review.py" --project-dir "<project>" --address "90 Aylesford Street, Mairehau, Christchurch 8013" --suburb "Mairehau" --bedrooms 3 --dwelling-type House --start-month 2025-01 --end-month 2026-08
```

Replace all example inputs with the actual selection. Dates use YYYY-MM. Use `--no-include-adjoining` only for an explicitly requested narrower comparison. The same runner and PDF template cover both scopes. Bedrooms accepts 1, 2, 3, 4, 5, 5+ or explicit ALL. Dwelling types: House, Flat, Apartment, BoardingHouse, Room, ALL. The API returns distinct 5 and 5+ rows: do not merge or reinterpret them without confirming their meaning.

Outputs: `<project>/outputs/<address>_<dwelling>_<bedrooms>_<start>_to_<end>_sa2-<scope-id>/`, containing rent_review.pdf, rent_review.png, rolling_comparison.csv, summary.json and source/ raw JSON. Summary evidence includes request URLs, file paths and SHA-256 values. Different area sets have separate output folders. Repeat a completed scope in a fresh project directory to preserve its evidence. Retrieval date is not a dataset release date.

## Calculation contract

- **Primary rent measure:** the arithmetic mean (API field `mean`) from a direct API aggregate for each complete 12-month window.
- **Rolling growth:** (mean_window / mean_baseline - 1) * 100. Keep the selected baseline throughout any user-selected horizon.
- **Median cross-check:** direct API med for that same complete annual window and property selection. Use the combined API row for grouped local areas. Never average monthly or individual-area medians.
- **Endpoint table:** baseline and latest arithmetic means and medians, each with its own percentage change. State exact window dates.
- **Bonds:** direct annual nLodged, not nCurr (active bonds at endpoint). Counts are randomly rounded; totals can differ from summed cells. Label bars "Year to [month/year]" and give the full annual windows. These are not cumulative lodgements since the rent increase or counts of tenants receiving increases.

Do not reconstruct annual or grouped means from rounded counts when a direct aggregate exists. Excluding one-bedroom labels from an otherwise all-bedroom analysis is a separate approximate analysis: the API's bedroom filter does not necessarily recompute the ALL subtotal. Disclose reconstruction and aggregate inconsistencies; never silently use these estimates in the standard report. Unknown-bedroom records are not known two-plus-bedroom properties.

Each bond contributes equally to the annual arithmetic mean. Unusually high or low rents and changes in the mix of properties can move it. Use the direct annual median as a cross-check.

Tenancy Services acknowledges inaccurate bedroom counts among some one-bedroom records, affecting counts and rents. When that category is included, identify its relevance without asserting an unproven cause or silently dropping records. Exclusion does not repair mislabelled larger homes. Provisional data/reclassification may affect remaining groups too.

## Standard PDF

Run the bundled report command for the requested span, inspect its PDF, and link it in the final answer with the findings. This includes requests to calculate rent change for a property. Give figures alone only if explicitly requested. The runner retries temporary server or connection failures on the affected request. If it stops, report the failed window and error. Never rebuild the report by passing a shortened series to the renderer.

## Recommendation and landlord message

Use both markets' unrounded `arithmetic_change_pct` values from `summary.json` for the same bedroom count, dwelling type and dates. Give the selected local market and Christchurch City equal weight: `recommended change (%) = (local change (%) + city change (%)) / 2`. Apply that rate to the tenancy: `proposed weekly rent = current weekly rent * (1 + recommended change / 100)`. Round the resulting rent to the nearest $5, with halfway amounts rounded up. Show the two observed rates, the blended recommendation rate, and the unrounded and rounded rent.

If current rent is missing, deliver the PDF and blended rate and ask for the current weekly rent before quoting a dollar proposal. If the blended rate is zero or negative, or rounding produces no increase, explain the result and omit the increase message.

For an increase, fill in the landlord message below with the property category and comparison dates. Present it in a copyable text block. Keep the rounding explanation outside the message.

```text
We've carried out a rent review for [address], based on MBIE bond lodgement data. We'd recommend increasing the rent from $[current] to $[proposed] per week.

Between [baseline] and [latest], average rents for [bedroom count and dwelling type] changed by [signed local change]% in [local market] and [signed city change]% across Christchurch City. Giving both figures equal weight suggests an adjustment of [blended change]% (see attached report).

Please let me know your thoughts, and we'll send the required rent increase notice to the tenants once confirmed.
```

## Verification

After changes run:

```text
"<python>" -m unittest discover -s "<skill-dir>/scripts" -p "test_rent*.py"
"<python>" "<skill-creator-dir>/scripts/quick_validate.py" "<skill-dir>"
```

After API or rendering changes, also run a live smoke report and inspect the PDF.
