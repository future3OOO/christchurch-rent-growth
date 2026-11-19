import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import rent_review


class RentReviewTests(unittest.TestCase):
    def test_lookup_uses_named_burwood_even_when_address_point_is_in_travis_wetlands(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch.object(rent_review.growth.urllib.request, "urlopen") as network:
            rent_review.main(["--lookup", "--suburb", "Burwood", "--address",
                              "280 Beach Road, Burwood", "--include-adjoining"])
        network.assert_not_called()
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["base_areas"], ["Burwood"])
        self.assertEqual(result["area_codes"], "325600,326200,324000,321300,324600")
        self.assertEqual(result["address_matches"], ["280 Beach Road, Burwood, Christchurch"])

    def response(self, request, timeout):
        url = request.full_url
        query = parse_qs(urlparse(url).query)
        self.assertTrue(urlparse(url).path.endswith("/statistics"))
        self.assertEqual(query["num-months"], ["12"])
        self.assertEqual(query["dwelling-type"], ["House"])
        self.assertEqual(query["num-bedrooms"], ["3"])
        end = query["period-ending"][0]
        definition = query["area-definition"][0]
        latest = end == "2025-02"
        if definition == "user-defined":
            named = "Mairehau North and South"
            spaced = f"{named} (321700,323100)"
            mapping, = query["user-defined-area-mappings"]
            self.assertEqual(self.failure, "missing-area")
            self.assertIn(mapping, (spaced, f"{named}(321700,323100)"))
            if latest and mapping == spaced:
                raise HTTPError(url, 500, "Internal Server Error", None, None)
            label = named
        else:
            local = definition == "SAU2019"
            self.assertEqual(query["area-codes"], ["321700,323100"] if local else ["060"])
            label = "ALL" if local else "Christchurch City"
        row = {"area": label, "dwell": "House", "nBedrms": "3",
               "lmean": math.log(660 if latest else 600), "med": 650 if latest else 620,
               "mean": 999, "nLodged": 57 if latest else 69}
        items = [row]
        if definition == "SAU2019":
            names = ["Mairehau North", "Mairehau South"]
            if self.failure == "missing-area":
                names.pop()
                items[0] = {**row, "med": 100}
            items += [{**row, "area": name} for name in names]
        payload = {"areaDefinition": definition.upper().replace("-", ""),
                   "periodCovered": "2024-3-1/2025-2-28" if latest else "2024-2-1/2025-1-31",
                   "items": items}
        if self.failure == "wrong-bedroom":
            payload["items"] = [{**r, "nBedrms": "2"} for r in items]
        elif self.failure == "wrong-period":
            payload["periodCovered"] = "2020-1-1/2020-12-31"
        return io.BytesIO(json.dumps(payload).encode())

    def run_report(self, project):
        args = ["--project-dir", project, "--address", "90 Aylesford Street", "--suburb", "Mairehau",
                "--bedrooms", "3", "--dwelling-type", "House",
                "--start-month", "2025-01", "--end-month", "2025-02"]
        with patch.dict(rent_review.os.environ, {"MBIE_MARKET_RENT_API_KEY": "test-key"}), \
             patch.object(rent_review.growth.urllib.request, "urlopen", self.response):
            return rent_review.main(args)

    def report_summary(self):
        with tempfile.TemporaryDirectory() as project:
            output = self.run_report(project)
            self.assertTrue((output / "rent_review.pdf").is_file())
            self.assertTrue((output / "rent_review.png").is_file())
            return json.loads((output / "summary.json").read_text())

    def test_full_report_uses_direct_annual_medians_and_geometric_baseline(self):
        self.failure = None
        for market in self.report_summary()["markets"]:
            self.assertEqual(len(market["points"]), 2)
            self.assertAlmostEqual(market["geometric_change_pct"], 10)
            self.assertEqual(market["points"][0]["median"], 620)
            self.assertEqual(market["points"][1]["median"], 650)
            self.assertEqual(market["points"][0]["window_start"], "2024-02")

    def test_missing_individual_area_uses_a_direct_named_aggregate_for_the_same_codes(self):
        self.failure = "missing-area"
        summary = self.report_summary()
        local, city = summary["markets"]
        self.assertEqual(local["codes"], "321700,323100")
        self.assertEqual([point["median"] for point in local["points"]], [620, 650])
        self.assertTrue(all("user-defined-area-mappings" in p["request"]["url"] for p in local["points"]))
        self.assertTrue(all("area-definition=TA2019" in p["request"]["url"] for p in city["points"]))
        self.assertEqual(len(summary["requests"]), 5)

    def test_wrong_scope_or_period_cannot_produce_a_report(self):
        for failure in ["wrong-bedroom", "wrong-period"]:
            self.failure = failure
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as project:
                with self.assertRaisesRegex(SystemExit, "VALIDATION FAILED"):
                    self.run_report(project)
                self.assertEqual(list(Path(project).rglob("*.pdf")), [])


if __name__ == "__main__":
    unittest.main()
