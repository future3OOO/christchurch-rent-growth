import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import rent_review


class RentReviewTests(unittest.TestCase):
    BURWOOD_CODES = "325600,326200,324000,321300,324600"
    group_codes = BURWOOD_CODES
    group_labels = ["Burwood", "Otakaro-Avon River Corridor", "Travis Wetlands", "Prestons", "Shirley East"]
    group_name = "Burwood and adjoining areas"

    def test_report_requires_an_explicit_dwelling_type(self):
        with tempfile.TemporaryDirectory() as project, patch("urllib.request.urlopen") as network:
            with self.assertRaises(SystemExit) as error:
                rent_review.main(["--project-dir", project, "--address", "Unit 2", "--suburb", "Burwood",
                                  "--bedrooms", "2", "--start-month", "2025-01", "--end-month", "2025-02"])
            self.assertEqual(error.exception.code, 2)
            network.assert_not_called()

    def test_offline_lookup_runs_without_matplotlib(self):
        result = subprocess.run([sys.executable, "-E", "-S", rent_review.__file__, "--lookup",
                                 "--suburb", "Burwood"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["area_codes"], self.BURWOOD_CODES)

    def test_lookup_uses_named_burwood_even_when_address_point_is_in_travis_wetlands(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch("urllib.request.urlopen") as network:
            rent_review.main(["--lookup", "--suburb", "Burwood", "--address",
                              "280 Beach Road, Burwood"])
        network.assert_not_called()
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["base_areas"], ["Burwood"])
        self.assertEqual(result["area_codes"], "325600,326200,324000,321300,324600")
        self.assertEqual(result["address_matches"], ["280 Beach Road, Burwood, Christchurch"])

    def test_lookup_flags_postal_suburb_discrepancy_without_reselecting_market(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rent_review.main(["--lookup", "--suburb", "Edgeware", "--address", "280 Beach Road, Edgeware", "--no-include-adjoining"])
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["area_codes"], "325300")
        self.assertEqual(result["address_suburbs"], ["Burwood"])
        self.assertTrue(result["address_suburb_mismatch"])

    def test_default_somerfield_scope_includes_both_starting_areas_and_all_neighbours(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rent_review.main(["--lookup", "--suburb", "Somerfield"])
        scope = json.loads(stdout.getvalue())
        self.assertEqual(scope["base_areas"], ["Somerfield East", "Somerfield West"])
        self.assertEqual(scope["area_codes"], "329100,329200,327600,330300,328700,330600,329700,329500,328200")

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
            named = self.group_name
            spaced = f"{named} ({self.group_codes})"
            mapping, = query["user-defined-area-mappings"]
            self.assertIn(self.failure, ("missing-area", "named-unavailable", "invalid-named"))
            self.assertIn(mapping, (spaced, f"{named}({self.group_codes})"))
            if self.failure == "named-unavailable" or latest and mapping == spaced:
                raise HTTPError(url, 500, "Internal Server Error", None, None)
            label = named
        else:
            local = definition == "SAU2019"
            codes, = query["area-codes"]
            self.assertIn(codes, ("325600", self.group_codes) if local else ("060",))
            label = "Burwood" if codes == "325600" else "ALL" if local else "Christchurch City"
        row = {"area": label, "dwell": "House", "nBedrms": "3",
               "lmean": math.log(660 if latest else 600), "med": 650 if latest else 620,
               "mean": 675 if latest else 625, "nLodged": 57 if latest else 69}
        items = [row]
        if definition == "SAU2019" and codes == self.group_codes:
            names = self.group_labels.copy()
            if self.failure in ("missing-area", "named-unavailable", "invalid-named"):
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
        elif self.failure == "invalid-named" and definition == "user-defined":
            payload["items"][0]["area"] = "Unrequested geography"
        return io.BytesIO(json.dumps(payload).encode())

    def run_report(self, project, *options):
        args = ["--project-dir", project, "--address", "280 Beach Road", "--suburb", "Burwood",
                "--bedrooms", "3", "--dwelling-type", "House",
                "--start-month", "2025-01", "--end-month", "2025-02", *options]
        with patch.dict(rent_review.os.environ, {"MBIE_MARKET_RENT_API_KEY": "test-key"}), \
             patch("urllib.request.urlopen", self.response):
            return rent_review.main(args)

    def report_summary(self, *options):
        with tempfile.TemporaryDirectory() as project:
            output = self.run_report(project, *options)
            self.assertTrue((output / "rent_review.pdf").is_file())
            self.assertTrue((output / "rent_review.png").is_file())
            return json.loads((output / "summary.json").read_text())

    def test_full_report_uses_direct_annual_medians_and_arithmetic_baseline(self):
        self.failure = None
        for market in self.report_summary()["markets"]:
            self.assertEqual(len(market["points"]), 2)
            self.assertEqual([p["arithmetic_mean"] for p in market["points"]], [625, 675])
            self.assertAlmostEqual(market["arithmetic_change_pct"], 8)
            self.assertEqual(market["points"][0]["median"], 620)
            self.assertEqual(market["points"][1]["median"], 650)
            self.assertEqual(market["points"][0]["window_start"], "2024-02")

    def test_missing_individual_area_uses_a_direct_named_aggregate_for_the_same_codes(self):
        self.failure = "missing-area"
        summary = self.report_summary("--suburb", "Burwood (Christchurch City)")
        local, city = summary["markets"]
        self.assertEqual(local["codes"], self.BURWOOD_CODES)
        self.assertEqual([point["median"] for point in local["points"]], [620, 650])
        self.assertTrue(all("user-defined-area-mappings" in p["request"]["url"] for p in local["points"]))
        self.assertTrue(all("area-definition=TA2019" in p["request"]["url"] for p in city["points"]))
        self.assertEqual(len(summary["requests"]), 5)

    def test_split_suburb_suffix_does_not_enter_the_named_mapping(self):
        self.failure = "missing-area"
        self.group_codes = "321700,323100"
        self.group_labels = ["Mairehau North", "Mairehau South"]
        self.group_name = "Mairehau North and South"
        report = self.report_summary("--no-include-adjoining", "--suburb", "Mairehau (Christchurch City)",
                                     "--address", "90 Aylesford Street")
        self.assertEqual(report["markets"][0]["codes"], self.group_codes)
        self.assertEqual(report["markets"][0]["points"][-1]["median"], 650)

    def test_both_scopes_can_run_in_the_same_project(self):
        self.failure = None
        with tempfile.TemporaryDirectory() as project:
            adjoining = self.run_report(project)
            local = self.run_report(project, "--no-include-adjoining")
            self.assertNotEqual(local, adjoining)
            for folder, codes in ((local, "325600"), (adjoining, self.BURWOOD_CODES)):
                self.assertTrue((folder / "rent_review.pdf").is_file())
                summary = json.loads((folder / "summary.json").read_text())
                self.assertEqual(summary["markets"][0]["codes"], codes)
            with self.assertRaisesRegex(SystemExit, "report already exists"):
                self.run_report(project)

    def test_transient_server_failure_retries_only_the_failed_window(self):
        self.failure = None
        original = self.response
        calls = []
        def interrupted(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 2:
                raise HTTPError(request.full_url, 500, "Internal Server Error", None, None)
            return original(request, timeout)

        with patch.object(self, "response", interrupted):
            summary = self.report_summary()
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[1], calls[2])
        self.assertEqual(len(set(calls)), 4)
        self.assertEqual(len(summary["requests"]), 4)

    def test_persistent_server_error_names_period_and_writes_no_report(self):
        calls = []
        def unavailable(request, timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 503, "Service Unavailable", None, None)

        with tempfile.TemporaryDirectory() as project, patch.object(self, "response", unavailable):
            with self.assertRaisesRegex(SystemExit, "2025-01.*503"):
                self.run_report(project)
            self.assertEqual(len(calls), 2)
            self.assertFalse(list(Path(project).rglob("*.pdf")))

    def test_invalid_or_unavailable_aggregate_cannot_produce_a_report(self):
        for failure in ("wrong-bedroom", "wrong-period", "named-unavailable", "invalid-named"):
            self.failure = failure
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as project:
                with self.assertRaisesRegex(SystemExit, "VALIDATION FAILED"):
                    self.run_report(project)
                self.assertEqual(list(Path(project).rglob("*.pdf")), [])


if __name__ == "__main__":
    unittest.main()
