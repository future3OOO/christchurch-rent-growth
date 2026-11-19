---
name: christchurch-rent-growth
description: Create bedroom-specific property rental reports comparing a named suburb or the suburb plus adjoining areas with Christchurch City using Tenancy Services bond data, rolling geometric means, annual medians and bond lodgements since a chosen rent-review date.
---

# Property rent review and bond report

Use the production MBIE / Tenancy Services Market Rent API. The default deliverable is a branded PDF comparing the property's local market with Christchurch City for the **same bedrooms, dwelling type and dates**. Run `scripts/rent_review.py`; do not rewrite the workflow in each chat.

## Intake: ask about the last rent increase first

Establish from the user or conversation:

- Property address and the actual suburb supplied by the user.
- Local scope. Use the named suburb alone by default. Include its adjoining areas when requested. Compare either local scope with Christchurch City.
- Bedroom count and dwelling type. Match the property; use House for a house in both markets. Ask about unclear types or state an appropriate assumption before proceeding.
- **When was the rent last set or increased, or what start date should the comparison use?** Ask at the start if not already known. Accept a user-selected comparison period instead.
- End month. If unspecified, use the latest API-eligible month, two calendar months before the current local month, then validate returned coverage. If unavailable, disclose this and establish an available endpoint.

Bundle missing information into one short question: "When was the rent last increased, or what start month should we compare from? How many bedrooms does the property have?" Ask for the address/type too if needed; never ask again for supplied information. Current weekly rent is needed only for a dollar recommendation.

Map an exact increase date to its calendar month. Explain the rolling baseline before running: January 2025 means the **12 months February 2024-January 2025**, not January alone. January 2025-August 2026 gives 20 rolling monthly points; the endpoint change is not an annual growth rate.

## Geography

Use the **named suburb** to select the starting SA2. The address is for verification and the report heading. A point-in-polygon assignment never determines the starting area. For example, a Burwood address inside the Travis Wetlands statistical area still starts from Burwood 325600 when Burwood is the supplied suburb.

The bundled [Christchurch address and rent-area index](references/christchurch-address-index.sqlite) resolves the supplied suburb, optionally verifies the address, and returns the verified API codes and neighbouring areas in one local run:

```text
"<python>" "<skill-dir>/scripts/rent_review.py" --lookup --suburb "Burwood" --include-adjoining
```

- An exact Christchurch statistical area name takes precedence. Mairehau uses Mairehau North 321700 and Mairehau South 323100. Richmond uses Richmond North 325900 and Richmond South 326800. For other suburbs with only partial name matches, present the candidates and confirm the intended grouping. For an unmatched suburb, ask which named area represents the intended market. Use --area-codes only for an explicitly confirmed selection from the matching area names and their adjoining areas.
- With --include-adjoining, include the starting areas and the union of areas sharing a boundary stretch with them. Deduplicate the codes. Point-only contacts are excluded. The lookup flags neighbours outside Christchurch City so their inclusion is visible. Honor explicit exclusions by supplying the confirmed set through --area-codes without --include-adjoining.
- The bundled [2019 SA2 boundaries and neighbours](references/christchurch-sa2-2019.geojson) support map verification and list shared boundary lengths. The address index is a snapshot of LINZ address data. An unmatched address may need separate verification. Keep the comparison anchored to the confirmed suburb.
- Christchurch City is TA2019 060. Name the actual combined areas in the summary and use a short local label in the standard PDF.

The website market-rent tool uses NZAD suburb regions. Before treating a website/API difference as an error, match geography, dates, bedrooms, dwelling type, measure and bond population. Website medians are not geometric means. Do not assume its bond count means API nLodged or nCurr. An unresolved-boundary warning is not required on the report; label the actual selected areas accurately.

## API and configuration

- Production base: https://api.business.govt.nz/gateway/tenancy-services/market-rent/v2/
- Documentation: https://portal.api.business.govt.nz/api/market-rent
- Authentication header: Ocp-Apim-Subscription-Key; JSON responses.
- Set `MBIE_MARKET_RENT_API_KEY`, or create a local `api_credentials.json` beside this skill with the key under `production.primary_key`. The environment variable takes precedence. Never print keys or include auth headers in evidence.

This is the statistical Market Rent API, not the transactional Tenancy Bond API. Do not substitute sandbox, CSV, invented values or stale periods on failure.

The runner resolves code/label lookups from the bundled index, then requests each rolling endpoint sequentially with num-months=12 and include-aggregates=true. It uses area codes and the selected dwelling/bedroom filters. Exact ALL aggregates are selected only for explicitly requested all-type/all-bedroom scopes. Combined local areas use the direct area=ALL result when all requested areas are listed. If the API omits an individual area from a grouped response, the runner requests a named group with the same SA2 codes for that window and the rest of the local series. It validates the named aggregate and keeps the original PDF. Individual areas use their exact labels. Reject missing, duplicate, suppressed, wrong-period or wrong-geography aggregates.

## Run

Use Python with matplotlib; reuse the current project's suitable environment. Paths and the logo resolve relative to the installed skill, independently of this chat.

```text
"<python>" "<skill-dir>/scripts/rent_review.py" --project-dir "<project>" --address "90 Aylesford Street, Mairehau, Christchurch 8013" --suburb "Mairehau" --include-adjoining --bedrooms 3 --dwelling-type House --start-month 2025-01 --end-month 2026-08
```

Replace all example inputs with the actual selection. Dates use YYYY-MM. Omit --include-adjoining for the suburb-only comparison. The same runner and PDF template cover both scopes. Bedrooms accepts 1, 2, 3, 4, 5, 5+ or explicit ALL. Dwelling types: House, Flat, Apartment, BoardingHouse, Room, ALL. The API returns distinct 5 and 5+ rows: do not merge or reinterpret them without confirming their meaning.

Outputs: `<project>/outputs/<address>_<dwelling>_<bedrooms>_<start>_to_<end>/`, containing rent_review.pdf, rent_review.png, rolling_comparison.csv, summary.json and source/ raw JSON. Summary evidence includes request URLs, file paths and SHA-256 values. A completed run is preserved; use a fresh project directory for reruns. Retrieval date is not a dataset release date.

## Calculation contract

- **Primary rent measure:** exp(lmean) from a direct API aggregate for each complete 12-month window.
- **Rolling growth:** (G_window / G_baseline - 1) * 100. Keep the selected baseline throughout any user-selected horizon.
- **Median cross-check:** direct API med for that same complete annual window and property selection. Use the combined API row for grouped local areas. Never average monthly or individual-area medians.
- **Endpoint table:** baseline and latest geometric means and medians, each with its own percentage change. State exact window dates. Do not switch to arithmetic averages in subsequent explanation.
- **Bonds:** direct annual nLodged, not nCurr (active bonds at endpoint). Counts are randomly rounded; totals can differ from summed cells. Label bars "Year to [month/year]" and give the full annual windows. These are not cumulative lodgements since the rent increase or counts of tenants receiving increases.

Do not reconstruct annual or grouped means from rounded counts when a direct aggregate exists. Excluding one-bedroom labels from an otherwise all-bedroom analysis is a separate approximate analysis: the API's bedroom filter does not necessarily recompute the ALL subtotal. Disclose reconstruction and aggregate inconsistencies; never silently use these estimates in the standard report. Unknown-bedroom records are not known two-plus-bedroom properties.

Geometric means support proportional comparisons and reduce influence from unusually high rents relative to arithmetic means. They do not fix invalid records, hold property mix constant or measure increases on the same homes. Medians provide a cross-check; neither measure is inherently more accurate in every sample.

Tenancy Services acknowledges inaccurate bedroom counts among some one-bedroom records, affecting counts and rents. When that category is included, identify its relevance without asserting an unproven cause or silently dropping records. Exclusion does not repair mislabelled larger homes. Provisional data/reclassification may affect remaining groups too.

## Report design

Use the bundled runner's established single-page style: warm off-white, slate local-market lines, teal city lines, restrained grids, clear figures and readable labels. Include:

1. Address, local grouping, bedrooms/type, baseline and endpoint.
2. Latest geometric means and change from baseline.
3. Rolling 12-month geometric rent lines and a matching growth panel.
4. Baseline/latest annual geometric means and medians with percentage changes.
5. Annual bond-lodgement bars for each market, counts and changes; separate scales keep the suburb visible.
6. Concise methods, source, retrieval date, geography codes and provisional-data notation.

Use assets/company_logo.png at the top right. Crop the transparent margins using the runner's established viewport; show the visible artwork 52 pt high, aligned with the heading, preserving proportions and full resolution. Do not return to the oversized or tiny variants.

Use the available PDF skill's authoring and render/verify workflow. Inspect the actual final PDF for data, dates, endpoint labels, table/bar windows, logo and footer. Adapt layout for long addresses or market labels. Deliver the PDF with concise scope, baseline and geometric changes. When asked only for figures, do not create another chart.

## Owner message, when requested

State the bedroom count and dwelling type explicitly. Explain geometric growth and the median cross-check as different measures, not an arbitrary range of possible increases. Do not claim geometric means are inherently superior. A modest/flat local trend supports only a cautious recommendation, assessed with supplied comparables and tenant retention. Do not invent a recommended dollar rent without necessary inputs. Mention any recommendation once and avoid a repetitive closing summary.

## Verification and legacy mode

After changes run:

```text
"<python>" -m unittest discover -s "<skill-dir>/scripts" -p "test_rent*.py"
"<python>" "<skill-creator-dir>/scripts/quick_validate.py" "<skill-dir>"
```

The rent-review tests check that the named suburb controls the offline selection, direct annual medians/geometric means, arbitrary baseline dates, the same bedroom/type selection in both markets, and rejection of wrong periods/bedrooms. After API/rendering changes also run a live production smoke report and inspect the rendered PDF.

The older scripts/christchurch_rent_growth.py remains for explicitly requested district-wide monthly-YoY reports with 12/24-month horizons. Its old district chart is not the default property report. The frozen August 2026 CSV fixtures test only the legacy calculation; never adjust current API results to match them.
