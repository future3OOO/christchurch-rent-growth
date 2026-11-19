"""Bedroom-specific suburb versus Christchurch rent review from direct annual API aggregates."""
import argparse
import csv
import json
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import christchurch_rent_growth as growth
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

SKILL = Path(__file__).resolve().parent.parent
BASE = "https://api.business.govt.nz/gateway/tenancy-services/market-rent/v2/"


def render(summary: dict, out: Path) -> Path:
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
        values = [p["geometric_mean"] for p in points]
        rates = [(v / values[0] - 1) * 100 for v in values]
        fig.text(left, .865, market["label"], fontsize=12, color=color, weight="bold")
        fig.text(left, .838, f"${values[-1]:.2f}/week", fontsize=21, color=ink, weight="bold")
        fig.text(left, .817, f"{rates[-1]:+.1f}% change from {summary['start_label']}", fontsize=10.5, color=muted)
        for ax, data, endpoint in [(levels, values, f"${values[-1]:.2f}"), (changes, rates, f"{rates[-1]:+.1f}%")]:
            ax.plot(range(len(data)), data, color=color, lw=2.3, marker="o", ms=3.5)
            ax.annotate(endpoint, (len(data) - 1, data[-1]), xytext=(10, 0), textcoords="offset points",
                        color=color, weight="bold", va="center", annotation_clip=False)
        for field, label, precision in [("geometric_mean", "geometric mean", 2), ("median", "median", 0)]:
            first, last = points[0][field], points[-1][field]
            table_rows.append([f"{market['label']} | {label}", f"${first:.{precision}f}",
                               f"${last:.{precision}f}", f"{(last / first - 1) * 100:+.1f}%"])
    levels.set_ylabel("Geometric mean weekly rent", color=muted, labelpad=12)
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
    fig.text(.095, .592, f"Change relative to the rolling 12-month geometric mean ending {summary['start_label']}", fontsize=10, color=muted)
    fig.add_artist(plt.Line2D([.075, .93], [.425, .425], transform=fig.transFigure, color="#dce2dc", lw=1))
    fig.text(.075, .400, "Change from the selected baseline", fontsize=16, weight="bold", color=ink)
    fig.text(.075, .379, summary["window_note"], fontsize=9.5, color=muted)
    table_ax = fig.add_axes([.075, .282, .855, .082])
    table_ax.axis("off")
    table = table_ax.table(cellText=table_rows, cellLoc="right", colWidths=[.46, .21, .21, .12], bbox=[0, 0, 1, 1])
    table.auto_set_font_size(False)
    table.set_fontsize(9)
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
        ax.set_title(f"{market['label']}  {(after / before - 1) * 100:+.1f}%", fontsize=10.5, color=color, loc="left", pad=9)
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
    fig.text(.075, .094, "Reading the comparison", fontsize=10.5, weight="bold", color=ink)
    fig.text(.075, .080, "Each point is exp(lmean) from a direct 12-month API aggregate for the selected property category.\n"
             "The baseline is a full year ending in the selected start month, not a single-month rent.\n"
             "Medians are direct annual API values. Changes can reflect the property mix, not increases on the same homes.",
             va="top", fontsize=9, color=muted, linespacing=1.55)
    fig.text(.075, .030, f"Source: MBIE / Tenancy Services Market Rent API | Retrieved {summary['retrieved_date']}", fontsize=8.5,
             color=muted, url="https://portal.api.business.govt.nz/api/market-rent")
    fig.text(.075, .016, summary["geography_note"], fontsize=8, color=muted)
    pdf = out / "rent_review.pdf"
    fig.savefig(pdf)
    fig.savefig(out / "rent_review.png", dpi=160)
    plt.close(fig)
    return pdf


def annual_row(payload: dict, definition: str, labels: list, end: date, dwelling: str, bedrooms: str) -> dict:
    start, last = growth.shift(end, -11), growth.shift(end, 1) - timedelta(days=1)
    try:
        covered = [date(*map(int, v.split("-"))) for v in payload["periodCovered"].split("/")]
    except (KeyError, TypeError, ValueError, AttributeError):
        growth.fail("invalid API period coverage")
    if covered != [start, last] or payload.get("areaDefinition") != definition:
        growth.fail("API period or geography does not match request")
    items = payload["items"]
    if not all(isinstance(r, dict) for r in items):
        growth.fail("API items must be objects")
    if {r.get("area") for r in items} - {"ALL"} != set(labels):
        growth.fail("API returned missing or unexpected named areas")
    area = "ALL" if len(labels) > 1 else labels[0]
    rows = [r for r in items if r.get("area") == area and r.get("dwell") == dwelling and r.get("nBedrms") == bedrooms]
    if len(rows) != 1:
        growth.fail("expected exactly one unsuppressed aggregate with the requested dwelling and bedroom selection")
    row = rows[0]
    if type(row.get("nLodged")) is not int or row["nLodged"] <= 0:
        growth.fail("missing or suppressed bond count")
    if any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ["lmean", "med"]):
        growth.fail("missing or invalid annual log mean or median")
    try:
        geometric = math.exp(row["lmean"])
    except OverflowError:
        growth.fail("invalid geometric mean")
    if geometric <= 0 or row["med"] <= 0:
        growth.fail("rent statistics must be positive")
    return {"window_start": growth.iso(start), "window_end": growth.iso(end), "lmean": row["lmean"],
            "geometric_mean": geometric, "median": row["med"], "lodged_bonds": row["nLodged"]}


def main(argv=None) -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ["project-dir", "address", "suburb", "area-codes", "start-month", "end-month", "bedrooms"]:
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--dwelling-type", choices=["House", "Flat", "Apartment", "BoardingHouse", "Room", "ALL"], default="House")
    args = parser.parse_args(argv)
    if args.bedrooms not in ["1", "2", "3", "4", "5", "5+", "ALL"]:
        parser.error("bedrooms must be 1, 2, 3, 4, 5, 5+ or ALL")
    try:
        start = date.fromisoformat(args.start_month + "-01")
        end = date.fromisoformat(args.end_month + "-01")
    except ValueError:
        parser.error("dates must use YYYY-MM")
    if start >= end or end > growth.shift(date.today().replace(day=1), -2):
        parser.error("baseline must precede end; end must be at least two calendar months behind the current month")
    codes = args.area_codes.split(",")
    if len(set(codes)) != len(codes) or not all(re.fullmatch(r"\d{6}", c) for c in codes):
        parser.error("area-codes must be unique comma-separated SA2 2019 six-digit codes")
    key = os.environ.get("MBIE_MARKET_RENT_API_KEY")
    if not key:
        try:
            key = json.loads(growth.CREDENTIALS.read_text(encoding="utf-8"))["production"]["primary_key"]
        except (OSError, ValueError, KeyError, TypeError):
            growth.fail("configure api_credentials.json or MBIE_MARKET_RENT_API_KEY")
    if not isinstance(key, str) or not key.strip():
        growth.fail("Market Rent API key is empty or invalid")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", args.address).strip("_")
    out = Path(args.project_dir).resolve() / "outputs" / f"{slug}_{args.dwelling_type}_{args.bedrooms}_{args.start_month}_to_{args.end_month}"
    if (out / "rent_review.pdf").exists():
        growth.fail("report already exists; choose a fresh project directory to preserve its source evidence")
    source = out / "source"
    source.mkdir(parents=True, exist_ok=True)
    evidence = []
    definitions = growth.api_get(BASE, "area-definitions/SAU2019", key, source, evidence)
    lookup = {r["code"]: r["label"] for r in definitions["items"]}
    if not all(c in lookup for c in codes):
        growth.fail("unknown SA2 code")
    labels = [lookup[c] for c in codes]
    city = growth.api_get(BASE, "area-definitions/TA2019", key, source, evidence)
    if {"label": "Christchurch City", "code": "060"} not in city["items"]:
        growth.fail("Christchurch City code could not be verified")
    local_label = args.suburb
    if len(labels) > 1 and all(label.startswith(args.suburb + " ") for label in labels):
        local_label += " " + " + ".join(label[len(args.suburb) + 1:] for label in labels)
    elif labels != [args.suburb]:
        local_label = " + ".join(labels)
    markets = []
    count = (end.year - start.year) * 12 + end.month - start.month + 1
    for label, definition, market_codes, market_labels in [(local_label, "SAU2019", args.area_codes, labels),
                                                           ("Christchurch City", "TA2019", "060", ["Christchurch City"])]:
        points = []
        for offset in range(count):
            month = growth.shift(start, offset)
            params = {
                "period-ending": growth.iso(month), "num-months": 12, "area-definition": definition,
                "area-codes": market_codes, "include-aggregates": "true"}
            if args.dwelling_type != "ALL":
                params["dwelling-type"] = args.dwelling_type
            if args.bedrooms != "ALL":
                params["num-bedrooms"] = args.bedrooms
            payload = growth.api_get(BASE, "statistics", key, source, evidence, **params)
            point = annual_row(payload, definition, market_labels, month, args.dwelling_type, args.bedrooms)
            point["request"] = evidence[-1]
            points.append(point)
            print(label, point["window_end"], f"${point['geometric_mean']:.2f}", flush=True)
        markets.append({"label": label, "definition": definition, "codes": market_codes, "points": points,
                        "geometric_change_pct": (points[-1]["geometric_mean"] / points[0]["geometric_mean"] - 1) * 100})
    bedroom_label = "All bedrooms" if args.bedrooms == "ALL" else args.bedrooms + "-bedroom"
    type_label = "all dwelling types" if args.dwelling_type == "ALL" else args.dwelling_type
    now = datetime.now().astimezone()
    summary = {"address": args.address, "suburb": args.suburb, "bedrooms": args.bedrooms, "dwelling_type": args.dwelling_type,
               "area_labels": labels, "start_label": growth.label(start), "end_label": growth.label(end),
               "baseline_header": "Year to " + start.strftime("%b %Y"), "latest_header": "Year to " + end.strftime("%b %Y"),
               "scope_label": f"{bedroom_label} | {type_label} | {local_label} vs Christchurch City",
               "window_note": f"Equal 12-month windows: {growth.shift(start, -11):%b %Y}-{start:%b %Y} vs {growth.shift(end, -11):%b %Y}-{end:%b %Y}.",
               "geography_note": f"Local: SA2 2019 {args.area_codes}. Christchurch City: TA 2019 060. Provisional bond data.",
               "retrieved_at": now.isoformat(), "retrieved_date": now.strftime("%d %B %Y"),
               "method": "Direct annual exp(lmean) and med; relative geometric change from selected baseline. Randomly rounded nLodged.",
               "requests": evidence, "markets": markets}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (out / "rolling_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["market", "window_start", "window_end", "geometric_mean", "median", "lodged_bonds"])
        for market in markets:
            for p in market["points"]:
                writer.writerow([market["label"]] + [p[k] for k in ["window_start", "window_end", "geometric_mean", "median", "lodged_bonds"]])
    print(render(summary, out))
    return out


if __name__ == "__main__":
    main()
