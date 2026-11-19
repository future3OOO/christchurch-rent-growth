# Christchurch rent growth skill

An agent skill that compares rents for a property's bedroom count and dwelling type in its local market and Christchurch City using the MBIE / Tenancy Services Market Rent API.

The agent uses the named suburb, property address, bedroom count, dwelling type and rent-review dates to build a branded PDF with rolling 12-month geometric means, annual medians and bond lodgements. The report, PNG, CSV, summary and API evidence are saved under `outputs/`. Ask for a landlord message if you need one.

The local comparison can cover the named suburb alone or the suburb plus areas that share a boundary with it. Both options compare with Christchurch City. The skill resolves the scope locally before requesting rent figures.

## Lookup data

The bundled index joins a 19 November 2026 snapshot of Christchurch address records to the 2019 statistical areas. The companion GeoJSON contains the generalised boundaries and calculated shared boundary lengths.

- Address data from [Toitū Te Whenua Land Information New Zealand](https://data.linz.govt.nz/layer/123113-nz-addresses/).
- Statistical area boundaries from [Stats NZ](https://datafinder.stats.govt.nz/layer/98970-statistical-area-2-2019-generalised/), accessed via [Eagle Technology's archive](https://services.arcgis.com/XTtANUDT8Va4DLwI/ArcGIS/rest/services/nz_statistical_areas_2_archive/FeatureServer/0).

Both datasets are licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).

## Install

Ask your agent:

> Install the skill from https://github.com/future3OOO/christchurch-rent-growth/tree/main/skills/christchurch-rent-growth

Or install it by hand by copying `skills/christchurch-rent-growth/` into your agent's skills folder:

| Agent | Skills folder |
|---|---|
| Codex | `~/.codex/skills/` |
| Claude Code | `~/.claude/skills/` |
| Per project | `.agents/skills/` in the project |

Start a new session after installing, then ask for a Christchurch rent review.

## Requirements

Use Python with Matplotlib installed and internet access. A [Market Rent API subscription key](https://portal.api.business.govt.nz/api/market-rent) is required. Set `MBIE_MARKET_RENT_API_KEY` in the environment running the report, or create a local `api_credentials.json` beside `SKILL.md` with the key under `production.primary_key`. The repository excludes local credential files.
