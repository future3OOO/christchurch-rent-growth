#!/usr/bin/env python3
"""District rent growth from the MBIE Market Rent API. Contract: ../SKILL.md."""

import argparse
import csv
import hashlib
import os
import json
import math
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

if sys.version_info < (3, 8):
    sys.exit("Python 3.8 or newer is required; found " + sys.version.split()[0])
try:
    import matplotlib
except ImportError:
    sys.exit("Matplotlib is not installed for " + sys.executable + " (see SKILL.md, Run step 3).")
matplotlib.use("Agg")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
import matplotlib.pyplot as plt  # noqa: E402

API_PATH = "https://api.business.govt.nz/{environment}/tenancy-services/market-rent/v2/"
CREDENTIALS = Path(__file__).resolve().parent.parent / "api_credentials.json"
LOCATION = "Christchurch City"
# The two file layouts MBIE has published; anything else fails rather than being guessed at.
FORMATS = (
    {"month": "TimeFrame", "location": "location", "bonds": "LodgedBonds", "mean": "GeometricMeanRent",
     "date": r"0?1/(?P<m>\d{1,2})/(?P<y>\d{4})"},  # September 2026 release onward
    {"month": "Time Frame", "location": "Location", "bonds": "Lodged Bonds", "mean": "Geometric Mean Rent",
     "date": r"(?P<y>\d{4})-(?P<m>\d{2})-01"},  # August 2026 release and earlier
)
NUMBER = r"\d{1,3}(,\d{3})*(\.\d+)?|\d+(\.\d+)?"
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
REFERENCES = Path(__file__).resolve().parent.parent / "references"


def fail(msg):
    sys.exit("VALIDATION FAILED: " + msg)


def shift(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def label(d):
    return MONTHS[d.month - 1] + " " + str(d.year)


def iso(d):
    return "%04d-%02d" % (d.year, d.month)


def api_get(base: str, path: str, key: str, source: Path, evidence: list, **params) -> dict:
    url = base + path + ("?" + urlencode(params) if params else "")
    request = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": key,
                                                  "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=130) as response:
            raw = response.read()
    except OSError as exc:
        fail("Market Rent API request failed: " + str(exc))
    saved = source / ("%03d.json" % (len(evidence) + 1))
    saved.write_bytes(raw)
    evidence.append({"url": url, "response_file": str(saved),
                     "sha256": hashlib.sha256(raw).hexdigest()})
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        fail("Market Rent API returned invalid JSON")
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        fail("Market Rent API response must contain an items list")
    return payload


def api_period(payload: dict, location: str, end: date, months: int) -> dict:
    start = shift(end, 1 - months)
    last = shift(end, 1) - timedelta(days=1)
    try:
        covered = [date(*map(int, value.split("-"))) for value in payload["periodCovered"].split("/")]
    except (KeyError, TypeError, ValueError, AttributeError):
        fail("API response has invalid periodCovered")
    if covered != [start, last] or payload.get("areaDefinition") != "TA2019":
        fail("API response period or area definition does not match the request")
    if not all(isinstance(row, dict) for row in payload["items"]):
        fail("API statistics items must be objects")
    selected = [row for row in payload["items"] if row.get("area") == location
                and row.get("dwell") == "ALL" and row.get("nBedrms") == "ALL"]
    if len(selected) != 1:
        fail("expected one unsuppressed aggregate for %s, %s (%d months); found %d"
             % (location, iso(end), months, len(selected)))
    row = selected[0]
    n, logmean = row.get("nLodged"), row.get("lmean")
    if type(n) is not int or n <= 0 or type(logmean) not in (int, float) or not math.isfinite(logmean):
        fail("API aggregate has missing, suppressed or invalid nLodged/lmean")
    try:
        mean = math.exp(logmean)
    except OverflowError:
        fail("API lmean overflows the geometric mean")
    if not math.isfinite(mean) or mean <= 0:
        fail("API geometric mean must be finite and positive")
    return {"start": iso(start), "end": iso(end),
            "label": label(start) + " to " + label(end), "lodged_bonds": n,
            "pooled_geometric_mean": mean, "lmean": logmean}


def load(path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        known = [f for f in FORMATS if all(f[k] in header for k in ("month", "location", "bonds", "mean"))]
        if len(known) != 1:
            fail("%s: header matches no known MBIE layout: %s" % (path.name, header))
        fmt = known[0]
        rows, latest = {}, None
        for row in reader:
            found = re.fullmatch(fmt["date"], row[fmt["month"]])
            if not found:
                fail("unexpected %s %r" % (fmt["month"], row[fmt["month"]]))
            d = date(int(found.group("y")), int(found.group("m")), 1)
            latest = d if latest is None else max(latest, d)
            if row[fmt["location"]] == LOCATION:
                if d in rows:
                    fail("duplicate %s row for %s" % (LOCATION, label(d)))
                rows[d] = {"month": label(d), "LodgedBonds": row[fmt["bonds"]],
                           "GeometricMeanRent": row[fmt["mean"]]}
    if not rows:
        fail("%r not found in %s" % (LOCATION, path.name))
    return rows, latest


def positive(row, field, cast):
    if not re.fullmatch(NUMBER, row[field]):
        fail("non-numeric %s=%r for %s" % (field, row[field], row["month"]))
    try:
        value = cast(row[field].replace(",", ""))
    except ValueError:
        fail("%s=%r for %s is not %s" % (field, row[field], row["month"], cast.__name__))
    if not value > 0:
        fail("non-positive %s=%r for %s" % (field, value, row["month"]))
    return value


def analyse(rows, end):
    latest_months = [shift(end, i - 11) for i in range(12)]
    previous_months = [shift(m, -12) for m in latest_months]
    for m in latest_months + previous_months:
        if m not in rows:
            fail("no %s row for %s" % (LOCATION, label(m)))

    def window(months):
        bonds = [positive(rows[m], "LodgedBonds", int) for m in months]
        means = [positive(rows[m], "GeometricMeanRent", float) for m in months]
        pooled = math.exp(sum(n * math.log(g) for n, g in zip(bonds, means)) / sum(bonds))
        return {"start": iso(months[0]), "end": iso(months[-1]),
                "label": label(months[0]) + " to " + label(months[-1]),
                "lodged_bonds": sum(bonds), "pooled_geometric_mean": pooled}

    monthly = []
    for p, m in zip(previous_months, latest_months):
        previous = positive(rows[p], "GeometricMeanRent", float)
        latest = positive(rows[m], "GeometricMeanRent", float)
        monthly.append((m, previous, latest, (latest / previous - 1) * 100))
    before, after = window(previous_months), window(latest_months)
    return {"monthly": monthly, "previous_period": before, "latest_period": after,
            "overall_change_pct": (after["pooled_geometric_mean"] / before["pooled_geometric_mean"] - 1) * 100}


def matches(result, expected):
    close = lambda a, b: math.isclose(a, b, rel_tol=1e-9)  # noqa: E731
    yoy = [m[3] for m in result["monthly"]]
    return (len(yoy) == len(expected["monthly_yoy_pct"])
            and all(close(a, b) for a, b in zip(yoy, expected["monthly_yoy_pct"]))
            and all(result[k]["lodged_bonds"] == expected[k]["lodged_bonds"]
                    and close(result[k]["pooled_geometric_mean"], expected[k]["pooled_geometric_mean"])
                    for k in ("previous_period", "latest_period"))
            and close(result["overall_change_pct"], expected["overall_change_pct"]))


def check_references():
    """Recompute every frozen fixture; proves the calculation, not the live data."""
    references = []
    for spec_path in sorted(REFERENCES.glob("*.json")):
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        rows, latest = load(REFERENCES / spec["csv"])
        if iso(latest) != spec["end_month"] or not matches(analyse(rows, latest), spec):
            fail("regression fixture %s no longer reproduces its expected results" % spec_path.name)
        references.append(spec)
    if not references:
        fail("no regression fixtures found in " + str(REFERENCES))
    return references


LABEL_HEIGHT = 15  # points: 11 pt text plus its white box


def place_label(values, i, dashed_above):
    """Offset (points) and alignment putting a point label where neither line is.

    dashed_above is the dashed line's height above the point, in points."""
    v = values[i]
    neighbours = [values[j] for j in (i - 1, i + 1) if 0 <= j < len(values)]
    if all(v >= n for n in neighbours):
        (dx, dy), ha = (0, 10), "center"   # peak: above
    elif all(v <= n for n in neighbours):
        (dx, dy), ha = (0, -20), "center"  # trough: below
    elif values[i - 1] < v:
        (dx, dy), ha = (-8, 6), "right"    # rising: upper left
    else:
        (dx, dy), ha = (8, 6), "left"      # falling: upper right
    if dy - 2 <= dashed_above <= dy + LABEL_HEIGHT:  # label would sit on the dashed line
        dy = dashed_above + 5 if dy > 0 else dashed_above - LABEL_HEIGHT - 5
    return (dx, dy), ha


def chart(result, release, png, pdf, location=LOCATION):
    months = [m[0] for m in result["monthly"]]
    yoy = [m[3] for m in result["monthly"]]
    overall = result["overall_change_pct"]
    span = len(months)
    comparison = "two-year" if span == 24 else "12-month"
    fig, ax = plt.subplots(figsize=(16, 12) if span == 24 else (12, 9), facecolor="white")
    fig.subplots_adjust(left=0.09, right=0.95, top=0.84, bottom=0.14)
    x = list(range(len(months)))
    ax.plot(x, yoy, color="#1f77b4", marker="o", linewidth=2.2, markersize=7,
            label="Monthly year-on-year change", zorder=3)
    dashed = ax.axhline(overall, color="#ff7f0e", linestyle="--", linewidth=2,
                        label="Overall %s change: %+.1f%%" % (comparison, overall), zorder=2)
    ax.axhline(0, color="grey", linewidth=1, zorder=1)
    low, high = min(yoy + [0, overall]), max(yoy + [0, overall])
    pad = max((high - low) * 0.15, 0.5)
    ax.set_ylim(low - pad, high + pad)
    to_points = 72.0 / fig.dpi
    for i, v in enumerate(yoy):
        dashed_above = (ax.transData.transform((i, overall))[1] - ax.transData.transform((i, v))[1]) * to_points
        offset, ha = place_label(yoy, i, dashed_above)
        ax.annotate("%+.1f%%" % v, (i, v), textcoords="offset points", xytext=offset, ha=ha,
                    fontsize=11, zorder=4,
                    bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.85))
    ax.set_xticks(x)
    ax.set_xticklabels([MONTHS[m.month - 1][:3] + ("\n" + str(m.year) if i == 0 or m.month == 1 else "")
                        for i, m in enumerate(months)], fontsize=11)
    if span == 24:
        ax.axvline(11.5, color="#bbbbbb", linestyle=":", linewidth=1)
    for i, change in enumerate(result.get("annual_changes_pct", [])):
        ax.text(i * 12 + 5.5, 0.975, "Year to %s: pooled annual increase %+.1f%%"
                % (label(months[i * 12 + 11]), change), transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=12, fontweight="bold", color="#444444")
    ax.set_ylabel("Change from same month a year earlier (%)", fontsize=12)
    ax.grid(axis="y", color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.01), frameon=False, fontsize=11)
    fig.suptitle(location + " rent growth", x=0.07, ha="left", y=0.965,
                 fontsize=20, fontweight="bold")
    ax.set_title("Year-on-year change in MBIE geometric mean weekly rent\n%s to %s"
                 % (label(months[0]), label(months[-1])), loc="left", fontsize=13, color="#444444", pad=14)
    fig.text(0.07, 0.03,
             "Source: MBIE / Tenancy Services Market Rent API, %s; retrieved %s. "
             "Annual means are exp(lmean) from separate 12-month API queries. "
             "Overall change compares annual windows ending %s and %s."
             % (location, release, result["previous_period"]["end"], result["latest_period"]["end"]),
             ha="left", va="bottom", fontsize=9.5, color="#555555", wrap=True)
    fig.savefig(str(png), dpi=150)
    fig.savefig(str(pdf))
    plt.close(fig)
    return float(dashed.get_ydata()[0])


def dollars(value):
    return ("$%.2f" % value).replace(".00", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--location", default=LOCATION, help="exact territorial-authority label")
    parser.add_argument("--end-month", help="YYYY-MM; defaults to latest API-eligible month")
    parser.add_argument("--months", type=int, choices=(12, 24), default=12)
    parser.add_argument("--environment", choices=("production", "sandbox"), default="production")
    parser.add_argument("--current-rent", type=float)
    args = parser.parse_args()
    if args.current_rent is not None and (not math.isfinite(args.current_rent) or args.current_rent <= 0):
        fail("--current-rent must be finite and positive")
    eligible = shift(date.today().replace(day=1), -2)
    if args.end_month:
        if not re.fullmatch(r"\d{4}-\d{2}", args.end_month):
            fail("--end-month must be YYYY-MM")
        try:
            end = date.fromisoformat(args.end_month + "-01")
        except ValueError:
            fail("invalid --end-month")
    else:
        end = eligible
    if end > eligible:
        fail("--end-month is newer than the API-eligible month " + iso(eligible))
    project = args.project_dir.resolve()
    if not project.is_dir():
        fail("project directory does not exist: " + str(project))
    key = os.environ.get("MBIE_MARKET_RENT_API_KEY")
    if not key:
        try:
            key = json.loads(CREDENTIALS.read_text(encoding="utf-8"))[args.environment]["primary_key"]
        except (OSError, ValueError, KeyError, TypeError):
            fail("configure api_credentials.json or MBIE_MARKET_RENT_API_KEY")
    if not isinstance(key, str) or not key.strip():
        fail("Market Rent API key is empty or invalid")
    check_references()
    retrieved = datetime.now().astimezone()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", args.location).strip("_")
    out_dir = project / "outputs" / "runs" / retrieved.strftime("%Y-%m-%d") / (
        "%s_%s_%d_months_to_%s" % (slug, args.environment, args.months, iso(end)))
    source = out_dir / "source"
    source.mkdir(parents=True, exist_ok=True)
    base = API_PATH.format(environment="gateway" if args.environment == "production" else "sandbox")
    evidence = []
    areas = api_get(base, "area-definitions/territorial-authority-2019", key, source, evidence)
    selected = [row for row in areas["items"] if isinstance(row, dict) and row.get("label") == args.location]
    if len(selected) != 1 or not isinstance(selected[0].get("code"), str):
        fail("unknown or ambiguous district: " + args.location)
    code = selected[0]["code"]

    def period(period_end, months):
        payload = api_get(base, "statistics", key, source, evidence,
                          **{"period-ending": iso(period_end), "num-months": months,
                             "area-definition": "TA2019", "area-codes": code,
                             "include-aggregates": "true"})
        return api_period(payload, args.location, period_end, months)

    # Direct annual API means avoid pooling monthly figures with rounded counts.
    annual = [period(shift(end, offset), 12) for offset in range(-args.months, 1, 12)]
    monthly_means = {}
    for offset in range(-args.months - 11, 1):
        month_end = shift(end, offset)
        monthly_means[month_end] = period(month_end, 1)["pooled_geometric_mean"]
    monthly = []
    for offset in range(1 - args.months, 1):
        month_end = shift(end, offset)
        previous, latest = monthly_means[shift(month_end, -12)], monthly_means[month_end]
        monthly.append((month_end, previous, latest, (latest / previous - 1) * 100))
    changes = [(b["pooled_geometric_mean"] / a["pooled_geometric_mean"] - 1) * 100
               for a, b in zip(annual, annual[1:])]
    overall = (annual[-1]["pooled_geometric_mean"] / annual[0]["pooled_geometric_mean"] - 1) * 100
    result = {"monthly": monthly, "previous_period": annual[0], "latest_period": annual[-1],
              "overall_change_pct": overall, "annual_changes_pct": changes if args.months == 24 else []}
    proposed = None
    unrounded = None
    if args.current_rent is not None:
        unrounded = args.current_rent * (1 + overall / 100)
        proposed = 5 * math.floor(unrounded / 5 + 0.5)
    stem = "MBIE_%s_%d_Month_Rent_Growth_to_%s_%d" % (slug, args.months, MONTHS[end.month - 1], end.year)
    csv_out, png, pdf = (out_dir / (stem + ext) for ext in (".csv", ".png", ".pdf"))
    json_out = out_dir / (stem + "_summary.json")
    with csv_out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "Month", "Previous", "Latest", "YoY Change %"])
        for i, (m, previous, latest, yoy) in enumerate(monthly, 1):
            writer.writerow([i, label(m), previous, latest, yoy])
    dashed = chart(result, retrieved.strftime("%d %B %Y"), png, pdf, args.location)
    summary = {
        "source": "MBIE Market Rent API v2", "environment": args.environment,
        "retrieved_at": retrieved.isoformat(timespec="seconds"), "data_end_month": iso(end),
        "end_month_selection": "explicit" if args.end_month else "latest eligible month; response dates validated",
        "location": args.location, "area_definition": "TA2019", "area_code": code,
        "dwelling_type": "ALL", "bedrooms": "ALL", "chart_months": args.months,
        "previous_period": annual[0], "latest_period": annual[-1], "annual_periods": annual,
        "annual_changes_pct": changes, "overall_change_pct": overall, "chart_dashed_line_pct": dashed,
        "monthly_yoy_pct": {label(m): yoy for m, _, _, yoy in monthly},
        "method_note": "Geometric means are exp(lmean) from each requested API period. Annual means use "
                       "direct 12-month queries, not pooled rounded monthly means. Monthly points are YoY; "
                       "overall change compares annual means separated by the chart horizon. Counts are randomly rounded.",
        "current_weekly_rent": args.current_rent, "adjusted_weekly_rent_unrounded": unrounded,
        "proposed_weekly_rent": proposed, "requests": evidence,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with csv_out.open(encoding="utf-8", newline="") as fh:
        written = list(csv.DictReader(fh))
    if len(written) != args.months or any(not math.isclose(
            (float(row["Latest"]) / float(row["Previous"]) - 1) * 100,
            float(row["YoY Change %"]), rel_tol=1e-12, abs_tol=1e-12) for row in written):
        fail("analysis CSV does not reproduce monthly YoY values")
    if dashed != overall:
        fail("chart dashed line differs from overall change")
    print("MBIE Market Rent API (%s), %s, data through %s" % (args.environment, args.location, label(end)))
    for window in annual:
        print("%s: %d bonds (randomly rounded), geometric mean $%.4f" %
              (window["label"], window["lodged_bonds"], window["pooled_geometric_mean"]))
    print("Overall %d-month change: %+.4f%%" % (args.months, overall))
    if proposed is not None:
        print("Proposed rent: %s -> %s per week (%+.1f%% gives $%.2f, rounded to nearest $5)"
              % (dollars(args.current_rent), dollars(proposed), overall, unrounded))
    for path in (pdf, png, csv_out, json_out):
        print(path)


if __name__ == "__main__":
    main()
