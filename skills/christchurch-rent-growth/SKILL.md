---
name: christchurch-rent-growth
description: Create bedroom-specific property rental reports comparing a named suburb plus adjoining areas with Christchurch City using Tenancy Services bond data, rolling arithmetic means, annual medians and bond lodgements since a chosen rent-review date.
---

# Property rent review and bond report

Use the production MBIE / Tenancy Services Market Rent API. The default deliverable is a branded PDF comparing the named suburb and its adjoining statistical areas with Christchurch City for the **same bedrooms, dwelling type and dates**. Run `scripts/rent_review.py`; do not rewrite the workflow in each chat.

## Intake

Establish from the user or conversation:

- Property address and the actual suburb supplied by the user.
- Local scope. Start with the named suburb and include areas that share a boundary with it by default. Use suburb-only scope only when explicitly requested.
- Bedroom count and dwelling type. Match the property; use House for a house in both markets. Ask about unclear types or state an appropriate assumption before proceeding.
- **When was the rent last set or increased, or what start date should the comparison use?** Ask at the start if not already known. Accept a user-selected comparison period instead.
- End month. If unspecified, use the latest API-eligible month, two calendar months before the current local month, then validate returned coverage. If unavailable, disclose this and establish an available endpoint.

Bundle missing information into one short question: "When was the rent last increased, or what start month should we compare from? How many bedrooms does the property have?" Ask for the address/type too if needed; never ask again for supplied information. Ask for the current weekly rent in the same intake if it is missing and a dollar recommendation is wanted. A missing current rent does not block the report.

Map an exact increase date to its calendar month. Explain the rolling baseline before running: January 2025 means the **12 months February 2024-January 2025**, not January alone. January 2025-August 2026 gives 20 rolling monthly points; the endpoint change is not an annual growth rate.

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

Use Python 3.10 or newer. Offline lookup uses SQLite. Reports also require Matplotlib and a Market Rent API key.

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

Run the bundled report command for the requested span, inspect its PDF, and link it in the final answer with the findings. This includes requests to calculate rent change for a property. Give figures alone only if explicitly requested. If the runner fails, retry a transient API error; if it still fails, identify the unavailable window. Never rebuild the report by passing a shortened series to the renderer.

## Recommendation and landlord message

Use the Christchurch City arithmetic means in `summary.json` for the selected bedroom count and dwelling type. Calculate the proposed weekly rent as `current weekly rent × latest city mean ÷ baseline city mean`. Round to the nearest $5, with halfway amounts rounded up. Show the user both the unrounded amount and the rounded proposal.

If current rent is missing, deliver the PDF and ask for the current weekly rent. If city growth is zero or negative, or rounding produces no increase, explain the result and omit the increase message.

For an increase, fill in the landlord message below with the property category and comparison dates. Present it in a copyable text block. Keep the rounding explanation outside the message.

```text
We've carried out a rent review for [address], based on MBIE bond lodgement data. We'd recommend increasing the rent from $[current] to $[proposed] per week.

Average rents for [matching property category] across Christchurch City rose around [city change to one decimal]% between [baseline] and [latest] (see attached report).

Please let me know your thoughts, and we'll send the required rent increase notice to the tenants once confirmed.
```

## Verification

After changes run:

```text
"<python>" -m unittest discover -s "<skill-dir>/scripts" -p "test_rent*.py"
"<python>" "<skill-creator-dir>/scripts/quick_validate.py" "<skill-dir>"
```

After API or rendering changes, also run a live smoke report and inspect the PDF.
