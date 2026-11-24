# Christchurch rent growth skill

Creates a branded rent-review PDF comparing new-bond rents for the same bedroom count and dwelling type in a Christchurch suburb and its adjoining statistical areas against Christchurch City.

## Install or update

Paste this into your agent:

> Install or update `christchurch-rent-growth` from https://github.com/future3OOO/christchurch-rent-growth/tree/main/skills/christchurch-rent-growth. Use the existing skill directory if installed. Copy all tracked files from that folder on the latest `main` into the skill directory, including scripts, assets and lookup data. Preserve local `api_credentials.json` and the shared response cache. Verify the installation by running `python scripts/rent_review.py --lookup --suburb Burwood` from the installed directory.

For a new install, use `~/.codex/skills/christchurch-rent-growth` for Codex, `~/.claude/skills/christchurch-rent-growth` for Claude Code, or `.agents/skills/christchurch-rent-growth` for a project install. Start a new session after updating.

Use Python 3.10+. Reports also require Matplotlib, internet access and a [Market Rent API key](https://portal.api.business.govt.nz/api/market-rent). Set `MBIE_MARKET_RENT_API_KEY` or store the key in `api_credentials.json` beside `SKILL.md` under `production.primary_key`.

## Report behaviour

- Each point is a rolling 12-month average of monthly medians weighted by bond lodgements. Up to two unpublished months per window can be estimated from surrounding published months. If either market still has an incomplete window, both charts use annual arithmetic means.
- The recommended adjustment gives local and city growth equal weight. With the current rent supplied, the skill recommends a weekly rent rounded to the nearest $5.
- The runner caches validated responses and reuses city data across property categories. After an interruption or a fallback caused by a temporary monthly request error, rerun the same command in the same project directory.

Use the bundled runner to produce the standard PDF. The [skill instructions](skills/christchurch-rent-growth/SKILL.md) give the report command and input options.

The bundled lookup uses [LINZ addresses](https://data.linz.govt.nz/layer/123113-nz-addresses/) and [Stats NZ 2019 statistical areas](https://datafinder.stats.govt.nz/layer/98970-statistical-area-2-2019-generalised/) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
