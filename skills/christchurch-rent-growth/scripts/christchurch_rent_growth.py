#!/usr/bin/env python3
"""Christchurch City rent growth from the latest MBIE / Tenancy Services monthly
territorial-authority rental bond CSV. Contract: ../SKILL.md."""

import argparse
import csv
import hashlib
import html
import json
import math
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

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

PAGE_URL = "https://www.tenancy.govt.nz/about-tenancy-services/data-and-statistics/rental-bond-data/"
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
MONTH_RE = "(" + "|".join(MONTHS) + r") (\d{4})"
REFERENCES = Path(__file__).resolve().parent.parent / "references"


def fail(msg):
    sys.exit("VALIDATION FAILED: " + msg)


def month(name, year):
    return date(int(year), MONTHS.index(name) + 1, 1)


def shift(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def label(d):
    return MONTHS[d.month - 1] + " " + str(d.year)


def iso(d):
    return "%04d-%02d" % (d.year, d.month)


def text_of(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (christchurch-rent-growth)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except OSError as exc:
        sys.exit("DOWNLOAD FAILED: %s: %s\nSave the official page and CSV with another tool and "
                 "pass --page-html and --csv (SKILL.md, 'When Python cannot download')." % (url, exc))


def read_page(page_html):
    """Freshness evidence from the official page; every value changes with each release."""
    headings = []
    for h2 in re.finditer(r"<h2[^>]*>(.*?)</h2>", page_html, re.S):
        found = re.fullmatch("Rental bond data, %s to %s" % (MONTH_RE, MONTH_RE), text_of(h2.group(1)))
        if found:
            headings.append((h2, found))
    if len(headings) != 1:
        fail("expected one 'Rental bond data, <month> to <month>' heading, found %d" % len(headings))
    h2, found = headings[0]
    end = month(found.group(3), found.group(4))

    para = re.search(r"<p[^>]*>(.*?)</p>", page_html[h2.end():], re.S)
    updated = para and re.fullmatch(r"Last updated:? (\d{1,2}) " + MONTH_RE, text_of(para.group(1)))
    if not updated:
        fail("no 'Last updated <day> <month> <year>' line directly under the rental bond data heading")

    links = [(urljoin(PAGE_URL, html.unescape(href)), text_of(body))
             for href, body in re.findall(r'<a\s[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', page_html, re.S)]
    ta_links = [(url, text) for url, text in links if text.startswith("By territorial authority")]
    if len(ta_links) != 1:
        fail("expected one 'By territorial authority' link, found %d" % len(ta_links))
    csv_url, link_text = ta_links[0]
    if not urlparse(csv_url).path.lower().endswith(".csv"):
        fail("'By territorial authority' link is not a CSV: " + csv_url)
    span = re.search("%s to %s" % (MONTH_RE, MONTH_RE), link_text)
    if not span or month(span.group(3), span.group(4)) != end:
        fail("link text %r does not end at the advertised %s" % (link_text, label(end)))

    notice = re.search(r"Important:\s*</span>\s*<div[^>]*>(.*?)</div>", page_html, re.S)
    warning = text_of(notice.group(1)) if notice else None
    if warning is None and "provisional" in text_of(page_html).lower():
        fail("page mentions provisional data but its 'Important:' notice could not be extracted")

    return {"end": end, "last_updated": "%s %s %s" % updated.groups(),
            "release": "%s %s" % (updated.group(2), updated.group(3)),
            "csv_url": csv_url, "link_text": link_text, "warning": warning}


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


def chart(result, release, png, pdf):
    months = [m[0] for m in result["monthly"]]
    yoy = [m[3] for m in result["monthly"]]
    overall = result["overall_change_pct"]
    fig, ax = plt.subplots(figsize=(12, 9), facecolor="white")
    fig.subplots_adjust(left=0.09, right=0.95, top=0.84, bottom=0.14)
    x = list(range(len(months)))
    ax.plot(x, yoy, color="#1f77b4", marker="o", linewidth=2.2, markersize=7,
            label="Monthly year-on-year change", zorder=3)
    dashed = ax.axhline(overall, color="#ff7f0e", linestyle="--", linewidth=2,
                        label="Overall 12-month change: %+.1f%%" % overall, zorder=2)
    ax.axhline(0, color="grey", linewidth=1, zorder=1)
    low, high = min(yoy + [0, overall]), max(yoy + [0, overall])
    pad = (high - low) * 0.15
    ax.set_ylim(low - pad, high + pad)
    to_points = 72.0 / fig.dpi
    for i, v in enumerate(yoy):
        dashed_above = (ax.transData.transform((i, overall))[1] - ax.transData.transform((i, v))[1]) * to_points
        offset, ha = place_label(yoy, i, dashed_above)
        ax.annotate("%+.1f%%" % v, (i, v), textcoords="offset points", xytext=offset, ha=ha,
                    fontsize=11, zorder=4,
                    bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.85))
    ax.set_xticks(x)
    ax.set_xticklabels([MONTHS[m.month - 1][:3] for m in months], fontsize=11)
    ax.set_ylabel("Change from same month a year earlier (%)", fontsize=12)
    ax.grid(axis="y", color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.01), frameon=False, fontsize=11)
    fig.suptitle("Christchurch City rent growth", x=0.07, ha="left", y=0.965,
                 fontsize=20, fontweight="bold")
    ax.set_title("Year-on-year change in MBIE geometric mean weekly rent\n%s to %s"
                 % (label(months[0]), label(months[-1])), loc="left", fontsize=13, color="#444444", pad=14)
    fig.text(0.07, 0.03,
             "Source: MBIE / Tenancy Services, detailed monthly territorial-authority rental bond data, "
             "Christchurch City, %s release. Overall 12-month geometric mean is pooled from MBIE monthly "
             "geometric means weighted by lodged bonds." % release,
             ha="left", va="bottom", fontsize=9.5, color="#555555", wrap=True)
    fig.savefig(str(png), dpi=150)
    fig.savefig(str(pdf))
    plt.close(fig)
    return float(dashed.get_ydata()[0])


def dollars(value):
    return ("$%.2f" % value).replace(".00", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True,
                        help="directory the agent session was opened in; outputs go to runs/<YYYY-MM-DD>/")
    parser.add_argument("--page-html", type=Path, help="fallback: saved copy of the official landing page")
    parser.add_argument("--csv", type=Path, help="fallback: saved 'By territorial authority' CSV from that page")
    parser.add_argument("--current-rent", type=float, help="property's current weekly rent in dollars")
    args = parser.parse_args()
    if args.current_rent is not None and not 0 < args.current_rent < float("inf"):
        fail("--current-rent must be a positive number of dollars, got %r" % args.current_rent)

    references = check_references()
    project = args.project_dir.resolve()
    if not project.is_dir():
        fail("project directory does not exist: " + str(project))
    retrieved = datetime.now().astimezone()
    out_dir = project / "runs" / retrieved.strftime("%Y-%m-%d")
    source = out_dir / "source"
    source.mkdir(parents=True, exist_ok=True)

    page_bytes = args.page_html.read_bytes() if args.page_html else fetch(PAGE_URL)
    page = read_page(page_bytes.decode("utf-8"))
    csv_bytes = args.csv.read_bytes() if args.csv else fetch(page["csv_url"])
    (source / "rental-bond-data.html").write_bytes(page_bytes)
    source_csv = source / Path(urlparse(page["csv_url"]).path).name
    source_csv.write_bytes(csv_bytes)
    source_sha = hashlib.sha256(csv_bytes).hexdigest()

    end = page["end"]
    rows, file_latest = load(source_csv)
    if file_latest != end or max(rows) != end:
        fail("CSV latest month %s (%s: %s) != page-advertised %s"
             % (label(file_latest), LOCATION, label(max(rows)), label(end)))
    result = analyse(rows, end)
    for ref in references:
        if ref["source_sha256"] == source_sha and not matches(result, ref):
            fail("live results differ from fixture %s built from this same file" % ref["csv"])

    proposed = None
    if args.current_rent is not None:  # nearest $5, halves rounded up
        proposed = 5 * math.floor(args.current_rent * (1 + result["overall_change_pct"] / 100) / 5 + 0.5)

    stem = "MBIE_Christchurch_Rent_Growth_to_%s_%d" % (MONTHS[end.month - 1], end.year)
    csv_out, png, pdf = (out_dir / (stem + ext) for ext in (".csv", ".png", ".pdf"))
    json_out = out_dir / (stem + "_summary.json")

    with csv_out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "Month", "Previous", "Latest", "YoY Change %"])
        for i, (m, previous, latest, yoy) in enumerate(result["monthly"], 1):
            writer.writerow([i, label(m), previous, latest, yoy])
    dashed = chart(result, page["release"], png, pdf)

    summary = {
        "landing_page_url": PAGE_URL,
        "csv_url": page["csv_url"],
        "retrieval": "supplied files" if args.page_html or args.csv else "downloaded by script",
        "retrieved_at": retrieved.isoformat(timespec="seconds"),
        "page_link_text": page["link_text"],
        "page_last_updated": page["last_updated"],
        "advertised_end_month": iso(end),
        "release_label": page["release"],
        "source_file": str(source_csv),
        "source_sha256": source_sha,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "location": LOCATION,
        "previous_period": result["previous_period"],
        "latest_period": result["latest_period"],
        "overall_change_pct": result["overall_change_pct"],
        "chart_dashed_line_pct": dashed,
        "monthly_yoy_pct": dict((label(m), yoy) for m, _, _, yoy in result["monthly"]),
        "method_note": "Pooled 12-month geometric means are reconstructed from MBIE's published (rounded) "
                       "monthly geometric means weighted by monthly lodged bonds; not a transaction-level "
                       "geometric mean.",
        "provisional_data_warning": page["warning"],
        "current_weekly_rent": args.current_rent,
        "proposed_weekly_rent": proposed,
    }
    json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    with csv_out.open(encoding="utf-8", newline="") as fh:
        written = list(csv.DictReader(fh))
    if len(written) != 12:
        fail("analysis CSV has %d rows, expected 12" % len(written))
    for row in written:
        recomputed = (float(row["Latest"]) / float(row["Previous"]) - 1) * 100
        if not math.isclose(recomputed, float(row["YoY Change %"]), rel_tol=1e-12, abs_tol=1e-12):
            fail("stored YoY does not recompute for " + row["Month"])
    if json.loads(json_out.read_text(encoding="utf-8"))["overall_change_pct"] != dashed:
        fail("chart dashed line differs from the summary JSON overall change")

    print("Release %s, data to %s (page last updated %s)" % (page["release"], label(end), page["last_updated"]))
    for m, previous, latest, yoy in result["monthly"]:
        print("  %-15s %6.0f -> %6.0f  %+6.2f%%" % (label(m), previous, latest, yoy))
    for key in ("previous_period", "latest_period"):
        period = result[key]
        print("%s: %d bonds, pooled geometric mean %.4f" % (period["label"], period["lodged_bonds"],
                                                            period["pooled_geometric_mean"]))
    print("Overall 12-month change: %+.4f%%" % result["overall_change_pct"])
    if proposed is not None:
        unrounded = args.current_rent * (1 + result["overall_change_pct"] / 100)
        print("Proposed rent: %s -> %s per week (%+.1f%% gives $%.2f, rounded to the nearest $5)"
              % (dollars(args.current_rent), dollars(proposed), result["overall_change_pct"], unrounded))
    for path in (pdf, png, csv_out, json_out):
        print(path)


if __name__ == "__main__":
    main()
