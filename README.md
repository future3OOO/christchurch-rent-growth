# Christchurch rent growth skill

Compare the named Christchurch suburb and its adjoining statistical areas against Christchurch City using Tenancy Services bond data. The standard PDF covers rolling bond-weighted averages of monthly medians and bond lodgements, with an annual arithmetic mean fallback for both markets if either has an incomplete weighted window for the selected bedrooms, dwelling type and dates.

## Lookup data

The bundled index joins Christchurch address records to the 2019 statistical areas. The index metadata records the snapshot date. The companion GeoJSON contains the generalised boundaries and calculated shared boundary lengths.

- Address data from [Toitū Te Whenua Land Information New Zealand](https://data.linz.govt.nz/layer/123113-nz-addresses/).
- Statistical area boundaries from [Stats NZ](https://datafinder.stats.govt.nz/layer/98970-statistical-area-2-2019-generalised/), accessed via [Eagle Technology's archive](https://services.arcgis.com/XTtANUDT8Va4DLwI/ArcGIS/rest/services/nz_statistical_areas_2_archive/FeatureServer/0).

Both datasets are licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).

To refresh addresses, run `python skills/christchurch-rent-growth/scripts/build_lookup.py` with Shapely 2 installed and internet access to LINZ. The script derives the SQLite area records and adjacency lists from the checked-in GeoJSON and replaces the index only after validating the rebuild.

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

Use Python 3.10 or newer. Offline lookups use SQLite from the standard library. PDF reports require Matplotlib and internet access. A [Market Rent API subscription key](https://portal.api.business.govt.nz/api/market-rent) is required. Set `MBIE_MARKET_RENT_API_KEY` in the environment running the report, or create a local `api_credentials.json` beside `SKILL.md` with the key under `production.primary_key`. The repository excludes local credential files.
