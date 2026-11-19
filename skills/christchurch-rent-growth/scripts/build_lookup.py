"""Rebuild the offline address index from LINZ and the bundled SA2 boundaries."""
import argparse
import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from urllib.request import urlopen

from rent_review import SKILL, lookup_key

LINZ_QUERY = ("https://services.arcgis.com/xdsHIIxuCWByZiCB/arcgis/rest/services/"
              "LINZ_NZ_Addresses/FeatureServer/0/query")
PAGE_SIZE = 16000


def linz(**params) -> dict:
    where = "territorial_authority='Christchurch City' AND address_lifecycle='Current'"
    with urlopen(LINZ_QUERY + "?" + urlencode({"f": "json", "where": where, **params}), timeout=45) as response:
        payload = json.load(response)
    if "error" in payload:
        raise ValueError(f"LINZ query failed: {payload['error']}")
    return payload


def build(output: Path) -> None:
    from shapely import points
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    references = SKILL / "references"
    boundaries = json.loads((references / "christchurch-sa2-2019.geojson").read_text(encoding="utf-8"))
    if boundaries["metadata"]["geography"] != "SA2 2019":
        raise ValueError("address index requires the rent API's 2019 SA2 boundaries")
    areas = [feature["properties"] for feature in boundaries["features"]]
    tree = STRtree([shape(feature["geometry"]) for feature in boundaries["features"]])
    rows = []
    count = linz(returnCountOnly="true")["count"]
    if type(count) is not int or count <= 0:
        raise ValueError("LINZ returned an invalid Christchurch address count")
    for offset in range(0, count, PAGE_SIZE):
        page = linz(resultType="standard", resultOffset=offset, resultRecordCount=PAGE_SIZE,
                    orderByFields="OBJECTID", outFields="address_id,full_address,suburb_locality,town_city",
                    returnGeometry="true", outSR=4326)
        features = page["features"]
        if len(features) != min(PAGE_SIZE, count - offset) or page["spatialReference"]["wkid"] != 4326:
            raise ValueError(f"LINZ returned an incomplete or invalid page at offset {offset}")
        coords = [(i, g["x"], g["y"]) for i, feature in enumerate(features)
                  if (g := feature.get("geometry")) and g.get("x") is not None and g.get("y") is not None]
        hits = {i: [] for i, _, _ in coords}
        if coords:
            indices, xs, ys = zip(*coords)
            for index, area in zip(*tree.query(points(xs, ys), predicate="covered_by")):
                hits[indices[index]].append(areas[area]["sa2_code"])
        for i, feature in enumerate(features):
            attrs = feature["attributes"]
            codes = hits.get(i)
            if codes is None:
                status = "missing point"
            elif len(codes) == 1:
                status = "matched"
            else:
                status = "boundary ambiguous" if codes else "outside mapped areas"
            address = attrs["full_address"]
            rows.append((attrs["address_id"], lookup_key(address), address, attrs["suburb_locality"],
                         attrs["town_city"], codes[0] if status == "matched" else None, status))
    if len({row[0] for row in rows}) != count:
        raise ValueError("LINZ query returned duplicate address IDs")
    rows.sort(key=lambda row: row[1])
    with TemporaryDirectory(dir=output.parent) as folder:
        draft = Path(folder) / "index.sqlite"
        with closing(sqlite3.connect(draft)) as db, db:
            db.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE areas (code TEXT PRIMARY KEY, name TEXT NOT NULL,
                                    in_christchurch_city INTEGER NOT NULL, adjoining_codes TEXT NOT NULL);
                CREATE TABLE addresses (address_id INTEGER NOT NULL, lookup_key TEXT PRIMARY KEY,
                    full_address TEXT NOT NULL, suburb TEXT, town TEXT, sa2_code TEXT REFERENCES areas(code),
                    status TEXT NOT NULL) WITHOUT ROWID;
                CREATE VIEW address_lookup AS
                SELECT lookup_key, full_address, suburb, town, status, sa2_code, areas.name AS sa2_name,
                       areas.adjoining_codes FROM addresses LEFT JOIN areas ON addresses.sa2_code=areas.code;
            """)
            db.executemany("INSERT INTO metadata VALUES (?,?)", {
                "address_source": "https://data.linz.govt.nz/layer/123113-nz-addresses/",
                "boundary_source": boundaries["metadata"]["sources"][0],
                "retrieved": date.today().isoformat(),
                "coverage": "Current LINZ address points with territorial authority Christchurch City",
                "address_license": "Land Information New Zealand, CC BY 4.0",
                "boundary_license": boundaries["metadata"]["attribution"],
                "lookup_key": "Lowercase full address, Unicode accents removed, internal spaces normalised",
                "adjoining_codes": "Comma-separated SA2 2019 codes, ordered by shared boundary length",
                "status": "matched, boundary ambiguous, missing point, or outside mapped areas",
            }.items())
            db.executemany("INSERT INTO areas VALUES (?,?,?,?)", [
                (area["sa2_code"], area["api_label"], area["in_christchurch_city"],
                 ",".join(n["sa2_code"] for n in area["adjoining_areas"])) for area in areas
            ])
            db.executemany("INSERT INTO addresses VALUES (?,?,?,?,?,?,?)", rows)
            db.commit()
            db.execute("VACUUM")
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("rebuilt address index failed its integrity check")
        draft.replace(output)
    print(f"Built {output} with {count:,} address records.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SKILL / "references/christchurch-address-index.sqlite")
    build(parser.parse_args().output.resolve())
