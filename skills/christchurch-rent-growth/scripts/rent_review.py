"""Compare rolling rents for a Christchurch neighbourhood and the city using MBIE bond data."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import time
import unicodedata
import urllib.request
from http.client import IncompleteRead
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or newer is required.")

SKILL = Path(__file__).resolve().parent.parent
BASE = "https://api.business.govt.nz/gateway/tenancy-services/market-rent/v2/"
CREDENTIALS = SKILL / "api_credentials.json"
MONTHS = ("January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")


def fail(msg: str) -> None:
    sys.exit("VALIDATION FAILED: " + msg)


def shift(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def month_label(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.year}"


def iso(d: date) -> str:
    return "%04d-%02d" % (d.year, d.month)


RELEASE_PAGE = "https://www.tenancy.govt.nz/about-tenancy-services/data-and-statistics/rental-bond-data/"

def publication():
    """Identify the monthly release; a dated token limits reuse if the release notice is unavailable."""
    today = date.today()
    try:
        with urllib.request.urlopen(RELEASE_PAGE, timeout=8) as response:
            page = response.read().decode("utf-8")
        match = re.search(r"Rental bond data,[^<]+ to (\w+) (\d{4})</h2>.*?Last updated (\d{1,2} \w+ \d{4})", page, re.S)
        if match and match[1] in MONTHS:
            return date(int(match[2]), MONTHS.index(match[1]) + 1, 1), match[3]
    except (OSError, IncompleteRead, UnicodeDecodeError):
        pass
    return shift(today, -2), today.isoformat()


class TemporaryRequestFailure(SystemExit):
    """Retryable API request still unavailable after the same-request retry."""


class MarketData:
    """Cache validated MBIE responses by exact query, shared across report directories."""
    def __init__(self, key, source, evidence, db):
        self.key, self.source, self.evidence, self.db = key, source, evidence, db
        self.latest, self.release = publication()
        db.execute("CREATE TABLE IF NOT EXISTS responses (url TEXT PRIMARY KEY, stamp TEXT, fetched TEXT, "
                   "digest TEXT, body BLOB)")

    def read(self, params, definition, labels, month, dwelling, bedrooms):
        url = BASE + "statistics?" + urlencode(sorted(params.items()))
        stamp = self.release if month >= shift(self.latest, -1) else "historical"
        alternate = url
        mapping = params.get("user-defined-area-mappings", "")
        if " (" in mapping:
            compact = {**params, "user-defined-area-mappings": mapping.replace(" (", "(")}
            alternate = BASE + "statistics?" + urlencode(sorted(compact.items()))
        cached = self.db.execute("SELECT url,fetched,digest,body FROM responses WHERE url IN (?,?) AND stamp=?",
                                 (url, alternate, stamp)).fetchone()
        if cached and hashlib.sha256(cached[3]).hexdigest() == cached[2]:
            url, fetched, digest, raw = cached
        else:
            cached = None
            request = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": self.key, "Accept": "application/json"})
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(request, timeout=130) as response:
                        raw = response.read()
                    break
                except (OSError, IncompleteRead) as exc:
                    reason = exc.reason if isinstance(exc, URLError) else exc
                    transient = (isinstance(exc, HTTPError) and exc.code in (429, 500, 502, 503, 504)
                                 or isinstance(reason, (TimeoutError, ConnectionError, IncompleteRead)))
                    message = f"VALIDATION FAILED: Market Rent API request failed for {definition} window ending {iso(month)}: {exc}"
                    if not transient:
                        fail(message)
                    if attempt:
                        raise TemporaryRequestFailure(f"{message}. Rerun the same command to resume.") from exc
                    time.sleep(1)
            fetched = datetime.now().astimezone().isoformat()
            digest = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            fail("Market Rent API returned invalid JSON")
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            fail("Market Rent API response must contain an items list")
        partial = False
        try:
            if params["num-months"] == 12:
                result = annual_row(payload, definition, labels, month, dwelling, bedrooms)
            else:
                row = period_row(payload, definition, labels, month, dwelling, bedrooms, 1) or {}
                median, count = row.get("med"), row.get("nLodged")
                if median is not None and (type(median) not in (int, float) or not math.isfinite(median) or median <= 0):
                    fail(f"invalid median for {iso(month)}")
                if count is not None and (type(count) is not int or count < 0):
                    fail(f"invalid bond count for {iso(month)}")
                result = {"month": iso(month), "median": median, "lodged_bonds": count}
        except IncompleteAreaBreakdown:
            partial = True
        if not cached:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO responses VALUES(?,?,?,?,?)", (url, stamp, fetched, digest, raw))
        saved = self.source / (digest + ".json")
        if not saved.exists() or hashlib.sha256(saved.read_bytes()).hexdigest() != digest:
            with tempfile.NamedTemporaryFile(dir=self.source, delete=False) as tmp:
                tmp.write(raw)
            os.replace(tmp.name, saved)
        evidence = {"url": url, "response_file": str(saved), "sha256": digest, "retrieved_at": fetched, "cached": bool(cached)}
        self.evidence.append(evidence)
        if partial:
            raise IncompleteAreaBreakdown()
        result["request"] = evidence
        return result

    def period(self, market, month, months, dwelling, bedrooms):
        definition = market["definition"]
        labels = market["area_labels"]
        params = {"period-ending": iso(month), "num-months": months, "include-aggregates": "true"}
        if definition != "TA2019":
            if dwelling != "ALL":
                params["dwelling-type"] = dwelling
            if bedrooms != "ALL":
                params["num-bedrooms"] = bedrooms
        if len(labels) == 1 or (months == 12 and not market.get("use_named_group")):
            try:
                return self.read({**params, "area-definition": definition, "area-codes": market["codes"]},
                                 definition, labels, month, dwelling, bedrooms)
            except IncompleteAreaBreakdown:
                market["use_named_group"] = True
        group = market["group"]
        params["area-definition"] = "user-defined"
        for space in (" ", ""):
            params["user-defined-area-mappings"] = f"{group}{space}({market['codes']})"
            try:
                return self.read(params, "USERDEFINED", [group], month, dwelling, bedrooms)
            except SystemExit as exc:
                error = exc.__context__
                if not space or not isinstance(error, HTTPError) or error.code != 500:
                    raise


def weighted_windows(monthly, count):
    """Use only published neighbours for estimates, with a two-month budget per rolling year."""
    usable = [m["median"] is not None and bool(m["lodged_bonds"]) for m in monthly]
    for i, m in enumerate(monthly):
        if (m["median"] is not None and m["lodged_bonds"] is not None) or "request_error" in m:
            continue
        left, right = i - 1, i + 1
        while left >= 0 and i - left <= 2 and not usable[left]:
            left -= 1
        while right < len(monthly) and right - i <= 2 and not usable[right]:
            right += 1
        if (left < 0 or right >= len(monthly) or right - left > 3
                or any("request_error" in item for item in monthly[left + 1:right])):
            continue
        fraction = (i - left) / (right - left)
        estimate = {}
        for field in ("median", "lodged_bonds"):
            if m[field] is None:
                lo, hi = monthly[left][field], monthly[right][field]
                estimate[field] = lo + (hi - lo) * fraction
        m["estimate"] = estimate
    points = []
    for i in range(count):
        window = monthly[i:i + 12]
        rents = [m.get("estimate", {}).get("median", m["median"]) for m in window]
        weights = [m.get("estimate", {}).get("lodged_bonds", m["lodged_bonds"]) for m in window]
        estimated = [m["month"] for m in window if "estimate" in m]
        value = None
        if len(estimated) <= 2 and None not in rents and None not in weights and sum(weights) > 0:
            value = math.fsum(r * w for r, w in zip(rents, weights)) / sum(weights)
        points.append({"window_start": window[0]["month"], "window_end": window[-1]["month"],
                       "weighted_monthly_medians": value, "estimated_months": estimated if value is not None else []})
    return points

def percent_change(value: float, baseline: float) -> float:
    return (value / baseline - 1) * 100


def render(summary: dict, out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import StrMethodFormatter

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "text.parse_math": False})
    paper, ink, muted = "#fcfbf8", "#263b3b", "#697773"
    fig = plt.figure(figsize=(12, 16), facecolor=paper)
    fig.text(.075, .963, "Rental market comparison", fontsize=25, weight="bold", color=ink)
    fig.text(.075, .936, summary["address"], fontsize=12, color=muted)
    fig.text(.075, .915, summary["scope_label"], fontsize=11, color=muted)
    fig.text(.075, .894, f"Baseline: {summary['start_label']} | Rolling comparison through {summary['end_label']}", fontsize=11, color=muted)
    height = 52
    width = height * 666 / 1039
    logo = fig.add_axes([(.93 * 864 - width) / 864, 1 - (23.3 + height) / 1152, width / 864, height / 1152])
    logo.imshow(plt.imread(SKILL / "assets/company_logo.png"), interpolation="none", resample=False)
    logo.set_xlim(198, 864)
    logo.set_ylim(1283, 244)
    logo.set_axis_off()

    levels = fig.add_axes([.095, .625, .765, .17])
    changes = fig.add_axes([.095, .475, .765, .105], sharex=levels)
    colors = ["#73849b", "#267b70"]
    table_rows = [["Area / measure", summary["baseline_header"], summary["latest_header"], "Change"]]
    for market, color, left in zip(summary["markets"], colors, [.075, .52]):
        points = market["points"]
        field = market["chart_measure"]
        weighted = field == "weighted_monthly_medians"
        values = [p[field] for p in points]
        rates = [percent_change(v, values[0]) if v is not None and values[0] is not None else None for v in values]
        fig.text(left, .865, market["label"], fontsize=12, color=color, weight="bold")
        fig.text(left, .838, f"${values[-1]:.2f}/week" if values[-1] is not None else "Incomplete window",
                 fontsize=21, color=ink, weight="bold")
        description = "Bond-weighted monthly medians" if weighted else "Annual mean (fallback)"
        if weighted and points[-1].get("estimated_months"):
            description += " (includes estimates)"
        fig.text(left, .815, description, fontsize=10.5, color=color)
        growth = f"{rates[-1]:+.1f}% from {summary['start_label']}" if rates[-1] is not None else "Change unavailable"
        fig.text(left, .799, growth, fontsize=9, color=muted)
        for ax, data, fmt in [(levels, values, "${:.2f}"), (changes, rates, "{:+.1f}%")]:
            ax.plot(range(len(data)), data, color=color, lw=2.3, marker="o", ms=3.5)
            if data[-1] is not None:
                ax.annotate(fmt.format(data[-1]), (len(data) - 1, data[-1]), xytext=(10, 0), textcoords="offset points",
                            color=color, weight="bold", va="center", annotation_clip=False)
        measures = ([("weighted_monthly_medians", "Weighted monthly medians", 2), ("arithmetic_mean", "Annual mean", 2)]
                    if weighted else [("arithmetic_mean", "Annual mean", 2), ("median", "Annual median", 0)])
        for key, label, precision in measures:
            first, last = points[0][key], points[-1][key]
            table_rows.append([f"{market['label']} | {label}",
                               f"${first:.{precision}f}" if first is not None else "Unavailable",
                               f"${last:.{precision}f}" if last is not None else "Unavailable",
                               f"{percent_change(last, first):+.1f}%" if None not in (first, last) else "Unavailable"])
    levels.set_ylabel("Weekly rent", color=muted, labelpad=12)
    levels.yaxis.set_major_formatter(StrMethodFormatter("${x:,.0f}"))
    levels.tick_params(axis="x", labelbottom=False, length=0)
    levels.margins(y=.18)
    changes.set_ylabel("Change (%)", color=muted, labelpad=12)
    changes.axhline(0, color="#a8b1ac", lw=.8)
    changes.margins(y=.25)
    dates = [date.fromisoformat(p["window_end"] + "-01") for p in summary["markets"][0]["points"]]
    step = max(1, math.ceil(len(dates) / 10))
    ticks = sorted(set(range(0, len(dates), step)) | {len(dates) - 1})
    labels = [dates[i].strftime("%b\n%Y") if i == 0 or dates[i].year != dates[ticks[n - 1]].year
              else dates[i].strftime("%b") for n, i in enumerate(ticks)]
    changes.set_xticks(ticks, labels)
    changes.set_xlabel("End month of each rolling 12-month window", fontsize=10, color=muted, labelpad=10)
    fig.text(.095, .592, f"Change relative to the charted measure for the year ending {summary['start_label']}", fontsize=10, color=muted)
    fig.add_artist(plt.Line2D([.075, .93], [.425, .425], transform=fig.transFigure, color="#dce2dc", lw=1))
    fig.text(.075, .400, "Change from the selected baseline", fontsize=16, weight="bold", color=ink)
    fig.text(.075, .379, summary["window_note"], fontsize=9.5, color=muted)
    table_ax = fig.add_axes([.075, .282, .855, .082])
    table_ax.axis("off")
    table = table_ax.table(cellText=table_rows, cellLoc="right", colWidths=[.53, .18, .18, .11], bbox=[0, 0, 1, 1])
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#dce2dc")
        cell.set_linewidth(.4)
        cell.set_facecolor("#eef1ec" if row == 0 else paper)
        cell.get_text().set_color(ink if row == 0 else muted)
        if row == 0:
            cell.get_text().set_weight("bold")
        if col == 0:
            cell.get_text().set_ha("left")

    fig.text(.075, .254, "Bond lodgements in the selected property category", fontsize=16, weight="bold", color=ink)
    fig.text(.075, .235, "Each bar covers 12 months; these are not cumulative bonds since the baseline. Counts are rounded.", fontsize=9.5, color=muted)
    bond_axes = []
    for market, color, left in zip(summary["markets"], colors, [.095, .55]):
        ax = fig.add_axes([left, .132, .34, .075])
        bond_axes.append(ax)
        before, after = market["points"][0]["lodged_bonds"], market["points"][-1]["lodged_bonds"]
        ax.bar([0, 1], [before, after], color=["#c5cfce", color], width=.48)
        for x, n in enumerate([before, after]):
            ax.text(x, n + max(before, after) * .04, f"{n:,}", ha="center", fontsize=10, color=ink)
        ax.set_ylim(0, max(before, after) * 1.38)
        ax.set_xticks([0, 1], [summary["baseline_header"], summary["latest_header"]])
        ax.set_title(f"{market['label']}  {percent_change(after, before):+.1f}%", fontsize=10.5, color=color, loc="left", pad=9)
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    for ax in [levels, changes] + bond_axes:
        ax.set_facecolor(paper)
        ax.grid(axis="y", color="#e3e7e1", lw=.7)
        ax.set_axisbelow(True)
        ax.tick_params(colors=muted, labelsize=9)
        ax.tick_params(axis="y", length=0)
        for side in ["top", "right", "left"]:
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color("#d3dbd4")
    local = summary["markets"][0]["points"]
    before, after = local[0]["lodged_bonds"], local[-1]["lodged_bonds"]
    if min(before, after) < 20:
        fig.text(.075, .111, f"Small local sample: {before} and {after} reported bonds. A few lettings can materially change the average.",
                 fontsize=9.5, color=ink)
    fig.text(.075, .094, "Reading the comparison", fontsize=10.5, weight="bold", color=ink)
    estimates = [(m["label"], row) for m in summary["markets"] for row in m["monthly_inputs"]
                 if m["chart_measure"] == "weighted_monthly_medians" and row.get("estimate")]
    detail = "If a window remains incomplete, both lines use the annual mean."
    if len(estimates) == 1:
        label, row = estimates[0]
        values = {**row, **row["estimate"]}
        detail = (f"{label}, {row['month']}: median ${values['median']:,.2f}, weight {values['lodged_bonds']:g} "
                  "(includes interpolation).")
    elif estimates:
        detail = f"Estimates used in {len(estimates)} market-months. See monthly_inputs.csv for months and weights."
    fig.text(.075, .080, "Multiply each monthly median by its bond weight and divide the sum of products by the total weight.\n"
             "Published counts are rounded. Up to two missing months per year may use interpolation between published months.\n"
             + detail, va="top", fontsize=9, color=muted, linespacing=1.55)
    fig.text(.075, .030, f"Source: MBIE / Tenancy Services Market Rent API | Retrieved {summary['retrieved_date']}", fontsize=8.5,
             color=muted, url="https://portal.api.business.govt.nz/api/market-rent")
    fig.text(.075, .016, summary["geography_note"], fontsize=8, color=muted)
    pdf = out / "rent_review.pdf"
    fig.savefig(out / "rent_review.png", dpi=160)
    with tempfile.NamedTemporaryFile(dir=out, suffix=".pdf", delete=False) as tmp:
        staged_pdf = Path(tmp.name)
    try:
        fig.savefig(staged_pdf)
        os.replace(staged_pdf, pdf)
    finally:
        staged_pdf.unlink(missing_ok=True)
    plt.close(fig)
    return pdf


class IncompleteAreaBreakdown(ValueError):
    """The area-code response omitted part of a requested group."""


def period_row(payload: dict, definition: str, labels: list, end: date, dwelling: str, bedrooms: str,
               months: int) -> dict | None:
    start, last = shift(end, 1 - months), shift(end, 1) - timedelta(days=1)
    try:
        covered = [date(*map(int, v.split("-"))) for v in payload["periodCovered"].split("/")]
    except (KeyError, TypeError, ValueError, AttributeError):
        fail("invalid API period coverage")
    if covered != [start, last] or payload.get("areaDefinition") != definition:
        fail("API period or geography does not match request")
    items = payload["items"]
    if not all(isinstance(r, dict) for r in items):
        fail("API items must be objects")
    returned = {r.get("area") for r in items} - {"ALL"}
    expected = set(labels)
    if definition == "SAU2019" and len(expected) > 1 and returned < expected:
        raise IncompleteAreaBreakdown()
    if not items and months == 1:
        return None
    if not items:
        fail(f"No published aggregate for {', '.join(labels)}, {dwelling}, {bedrooms} bedrooms, window ending {iso(end)}")
    if returned != expected:
        fail("API returned missing or unexpected named areas")
    area = "ALL" if len(labels) > 1 else labels[0]
    rows = [r for r in items if r.get("area") == area and r.get("dwell") == dwelling and r.get("nBedrms") == bedrooms]
    if not rows and months == 1:
        return None
    if len(rows) != 1:
        fail("expected exactly one unsuppressed aggregate with the requested dwelling and bedroom selection")
    return rows[0]

def annual_row(payload: dict, definition: str, labels: list, end: date, dwelling: str, bedrooms: str) -> dict:
    row = period_row(payload, definition, labels, end, dwelling, bedrooms, 12)
    if type(row.get("nLodged")) is not int or row["nLodged"] <= 0:
        fail("missing or suppressed bond count")
    if any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ["mean", "med"]):
        fail("missing or invalid annual arithmetic mean or median")
    if row["mean"] <= 0 or row["med"] <= 0:
        fail("non-positive annual rent")
    return {"window_start": iso(shift(end, -11)), "window_end": iso(end), "arithmetic_mean": row["mean"],
            "median": row["med"], "lodged_bonds": row["nLodged"]}


def lookup_key(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                            if not unicodedata.combining(c)).split())


def local_market(suburb: str, address: str, area_codes: str | None, include_adjoining: bool) -> dict:
    index = SKILL / "references/christchurch-address-index.sqlite"
    with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as db:
        areas = {code: (name, neighbours.split(",") if neighbours else [], in_city)
                 for code, name, neighbours, in_city in
                 db.execute("SELECT code, name, adjoining_codes, in_christchurch_city FROM areas ORDER BY code")}
        address_rows = set()
        prefix = lookup_key(address.split(",", 1)[0])
        if prefix:
            alternate = re.sub(r"\bsaint\b", "st", prefix.replace("’", "").replace("'", ""))
            for variant in {prefix, alternate}:
                lower = variant + ","
                address_rows.update(db.execute(
                    "SELECT full_address, suburb FROM address_lookup WHERE lookup_key = ? "
                    "OR (lookup_key >= ? AND lookup_key < ?)", (variant, lower, variant + "-")))

    suburb_key = lookup_key(suburb).removesuffix(" (christchurch city)")
    if not suburb_key:
        raise ValueError("supply a suburb name")
    names = {code: lookup_key(name).removesuffix(" (christchurch city)")
             for code, (name, _, in_city) in areas.items() if in_city}
    exact = [code for code, name in names.items() if name == suburb_key]
    candidates = exact or [code for code, name in names.items()
                           if name.startswith((suburb_key + " ", suburb_key + "-"))]
    if not candidates:
        raise ValueError(f"no statistical area matches {suburb!r}; confirm the intended suburb area by name")
    requested = area_codes.split(",") if area_codes else []
    established = {"mairehau": ["321700", "323100"], "richmond": ["325900", "326800"],
                   "somerfield": ["329100", "329200"]}
    if requested:
        if len(set(requested)) != len(requested) or any(code not in areas for code in requested):
            raise ValueError("area-codes must be unique known SA2 2019 codes")
        base = [code for code in requested if code in candidates]
        if not base:
            raise ValueError("area-codes must include a statistical area matching the supplied suburb")
    else:
        base = candidates
        if not exact:
            base = established.get(suburb_key, [])
            if set(base) != set(candidates):
                options = ", ".join(f"{areas[code][0]} ({code})" for code in candidates)
                raise ValueError(f"confirm the statistical area grouping for {suburb}: {options}")
    neighbours = list(dict.fromkeys(code for start in base for code in areas[start][1] if code not in base))
    if set(requested) - set(base + neighbours):
        raise ValueError("area-codes must match the suburb or its adjoining statistical areas")
    codes = list(dict.fromkeys((requested or base) + (neighbours if include_adjoining else [])))
    base_areas = [areas[code][0] for code in base]
    label = base_areas[0].removesuffix(" (Christchurch City)") if len(base) == 1 else suburb.strip()
    if len(base) > 1 and suburb_key in established and not set(codes) - set(base):
        directions = [name.removesuffix(" (Christchurch City)").rsplit(" ", 1)[-1] for name in base_areas]
        label += " " + " + ".join(directions)
    if set(codes) - set(base):
        label += " + adjoining areas"
    address_suburbs = sorted({name for _, name in address_rows if name})
    return {"label": label, "base_areas": base_areas, "area_codes": ",".join(codes),
            "area_labels": [areas[code][0] for code in codes],
            "outside_christchurch_city": [areas[code][0] for code in codes if not areas[code][2]],
            "address_matches": sorted(name for name, _ in address_rows),
            "address_suburbs": address_suburbs,
            "address_suburb_mismatch": bool(address_suburbs) and
            all(lookup_key(name) != suburb_key for name in address_suburbs)}


def main(argv=None) -> Path | None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suburb", required=True, help="Named suburb used to select the starting statistical area")
    parser.add_argument("--lookup", action="store_true", help="Print the local market selection without calling the rent API")
    parser.add_argument("--include-adjoining", action=argparse.BooleanOptionalAction, default=True,
                        help="Include areas sharing a boundary with the suburb (default: included)")
    parser.add_argument("--area-codes", help="Explicitly confirmed selection for an ambiguous suburb or custom neighbour list")
    report_flags = ("project-dir", "address", "start-month", "end-month", "bedrooms")
    for flag in report_flags:
        parser.add_argument("--" + flag)
    parser.add_argument("--dwelling-type", choices=["House", "Flat", "Apartment", "BoardingHouse", "Room", "ALL"])
    args = parser.parse_args(argv)
    try:
        local = local_market(args.suburb, args.address or "", args.area_codes, args.include_adjoining)
    except (ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    if args.lookup:
        print(json.dumps(local, indent=2))
        return None
    missing = [f"--{flag}" for flag in (*report_flags, "dwelling-type") if not getattr(args, flag.replace("-", "_"))]
    if missing:
        parser.error("the following arguments are required for a report: " + ", ".join(missing))
    if args.bedrooms not in ["1", "2", "3", "4", "5", "5+", "ALL"]:
        parser.error("bedrooms must be 1, 2, 3, 4, 5, 5+ or ALL")
    try:
        start = date.fromisoformat(args.start_month + "-01")
        end = date.fromisoformat(args.end_month + "-01")
    except ValueError:
        parser.error("dates must use YYYY-MM")
    if start >= end or end > shift(date.today(), -2):
        parser.error("baseline must precede end; end must be at least two calendar months behind the current month")

    if importlib.util.find_spec("matplotlib") is None:
        fail("install Matplotlib to generate the rental comparison PDF")
    if local["address_suburb_mismatch"]:
        print("Address index lists this street address in " + ", ".join(local["address_suburbs"])
              + f". The selected comparison uses {args.suburb}.", file=sys.stderr)
    key = os.environ.get("MBIE_MARKET_RENT_API_KEY")
    if not key:
        try:
            key = json.loads(CREDENTIALS.read_text(encoding="utf-8"))["production"]["primary_key"]
        except (OSError, ValueError, KeyError, TypeError):
            fail("configure api_credentials.json or MBIE_MARKET_RENT_API_KEY")
    if not isinstance(key, str) or not key.strip():
        fail("Market Rent API key is empty or invalid")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", args.address).strip("_")
    local_label, codes, labels = local["label"], local["area_codes"], local["area_labels"]
    scope = ",".join(sorted(codes.split(",")))
    suffix = hashlib.sha256(scope.encode("ascii")).hexdigest()[:12]
    report_name = f"{slug}_{args.dwelling_type}_{args.bedrooms}_{args.start_month}_to_{args.end_month}"
    out = Path(args.project_dir).resolve() / "outputs" / f"{report_name}_sa2-{suffix}"
    retry_months = out / ".retry-monthly-requests"
    if (out / "rent_review.pdf").exists() and not retry_months.exists():
        fail("report already exists; choose a fresh project directory to preserve its source evidence")
    source = out / "source"
    source.mkdir(parents=True, exist_ok=True)
    evidence = []
    markets = []
    count = (end.year - start.year) * 12 + end.month - start.month + 1
    cache = Path(os.environ.get("MBIE_RENT_CACHE_DIR", Path.home() / ".cache" / "christchurch-rent-growth"))
    cache.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(cache / "responses.sqlite", timeout=30)) as db:
        data = MarketData(key, source, evidence, db)
        for label, definition, market_codes, market_labels in [(local_label, "SAU2019", codes, labels),
                                                               ("Christchurch City", "TA2019", "060", ["Christchurch City"])]:
            group = re.sub(r" \(Christchurch City\)", "", label, flags=re.IGNORECASE)
            market = {"label": label, "definition": definition, "codes": market_codes, "area_labels": market_labels,
                      "group": re.sub(r"[(),]", "", group).replace(" + ", " and ")}
            monthly = []
            for offset in range(-11, count):
                month = shift(start, offset)
                try:
                    entry = data.period(market, month, 1, args.dwelling_type, args.bedrooms)
                except TemporaryRequestFailure as exc:
                    entry = {"month": iso(month), "median": None, "lodged_bonds": None, "request_error": str(exc)}
                    print(exc, file=sys.stderr)
                monthly.append(entry)
            market["monthly_inputs"] = monthly
            market["points"] = weighted_windows(monthly, count)
            markets.append(market)
        complete = all(p["weighted_monthly_medians"] is not None for m in markets for p in m["points"])
        measure = "weighted_monthly_medians" if complete else "arithmetic_mean"
        for market in markets:
            points = market["points"]
            for i, point in enumerate(points):
                if not complete or i in (0, count - 1):
                    point.update(data.period(market, shift(start, i), 12, args.dwelling_type, args.bedrooms))
            market["arithmetic_change_pct"] = percent_change(points[-1]["arithmetic_mean"], points[0]["arithmetic_mean"])
    for market in markets:
        points = market["points"]
        market["chart_measure"] = measure
        market["chart_change_pct"] = percent_change(points[-1][measure], points[0][measure])
    bedroom_label = "All bedrooms" if args.bedrooms == "ALL" else args.bedrooms + "-bedroom"
    type_label = "all dwelling types" if args.dwelling_type == "ALL" else args.dwelling_type
    now = datetime.now().astimezone()
    summary = {"address": args.address, "suburb": args.suburb, "bedrooms": args.bedrooms, "dwelling_type": args.dwelling_type,
               "area_labels": labels, "local_selection": local, "start_label": month_label(start), "end_label": month_label(end),
               "baseline_header": "Year to " + start.strftime("%b %Y"), "latest_header": "Year to " + end.strftime("%b %Y"),
               "scope_label": f"{bedroom_label} | {type_label} | {local_label} vs Christchurch City",
               "window_note": f"Equal 12-month windows: {shift(start, -11):%b %Y}-{start:%b %Y} vs {shift(end, -11):%b %Y}-{end:%b %Y}.",
               "geography_note": f"Local: SA2 2019 {codes}. Christchurch City: TA 2019 060. Provisional bond data.",
               "retrieved_at": now.isoformat(), "retrieved_date": now.strftime("%d %B %Y"),
               "method": "Rolling bond-weighted average of monthly medians; report-wide annual mean fallback.",
               "recommended_change_pct": sum(m["chart_change_pct"] for m in markets) / 2,
               "requests": evidence, "markets": markets}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (out / "rolling_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        fields = ["window_start", "window_end", "arithmetic_mean", "median", "lodged_bonds", "weighted_monthly_medians"]
        writer.writerow(["market", *fields, "chart_measure"])
        for market in markets:
            for point in market["points"]:
                writer.writerow([market["label"], *(point.get(k) for k in fields), market["chart_measure"]])
    with (out / "monthly_inputs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["market", "month", "published_median", "published_lodgements", "estimated_median",
                         "estimated_weight", "request_error"])
        for market in markets:
            for m in market["monthly_inputs"]:
                est = m.get("estimate", {})
                writer.writerow([market["label"], m["month"], m["median"], m["lodged_bonds"],
                                 est.get("median"), est.get("lodged_bonds"), m.get("request_error")])
    pending = [f"{market['label']} {row['month']}" for market in markets for row in market["monthly_inputs"]
               if "request_error" in row]
    if pending:
        retry_months.write_text("\n".join(pending) + "\n", encoding="utf-8")
    print(render(summary, out))
    if not pending:
        retry_months.unlink(missing_ok=True)
    print(f"50/50 recommended change: {summary['recommended_change_pct']:+.2f}%")
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
