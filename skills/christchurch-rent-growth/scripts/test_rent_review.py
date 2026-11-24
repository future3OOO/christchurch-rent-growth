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

    def setUp(self):
        sleeper = patch.object(rent_review.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_interpolated_weights_two_gap_limit_and_transport_errors(self):
        def series(gaps):
            return [{"month": str(i), "median": None if i in gaps else 400 + i * 5,
                     "lodged_bonds": None if i in gaps else 3 + (i // 2) * 3} for i in range(13)]
        monthly = series({3, 7})
        points = rent_review.weighted_windows(monthly, 2)
        self.assertEqual(monthly[3]["estimate"], {"median": 415, "lodged_bonds": 7.5})
        self.assertIsNone(monthly[3]["lodged_bonds"])
        self.assertEqual(points[0]["estimated_months"], ["3", "7"])
        self.assertIsNotNone(points[0]["weighted_monthly_medians"])
        pair = series({5, 6})
        rent_review.weighted_windows(pair, 2)
        self.assertEqual([pair[i]["estimate"]["median"] for i in (5, 6)], [425, 430])
        three = rent_review.weighted_windows(series({0, 3, 7}), 2)
        self.assertIsNone(three[0]["weighted_monthly_medians"])
        self.assertIsNotNone(three[1]["weighted_monthly_medians"])
        self.assertIsNone(rent_review.weighted_windows(series({2, 4, 6}), 2)[0]["weighted_monthly_medians"])
        bad = series({5})
        bad[5]["request_error"] = "HTTP 500"
        self.assertIsNone(rent_review.weighted_windows(bad, 2)[0]["weighted_monthly_medians"])
        self.assertNotIn("estimate", bad[5])

    def test_retry_resumes_and_city_cache_serves_other_categories(self):
        self.failure = None
        original = self.response
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            def interrupted(req, timeout):
                calls.append(req.full_url)
                if "period-ending=2025-02" in req.full_url and "num-months=12" in req.full_url:
                    raise HTTPError(req.full_url, 503, "unavailable", None, None)
                return original(req, timeout)
            with patch.object(self, "response", interrupted), self.assertRaisesRegex(SystemExit, "2025-02.*503"):
                self.run_report(temp)
            with patch.object(self, "response", wraps=original) as resumed:
                self.run_report(temp)
            retried = [call.args[0].full_url for call in resumed.call_args_list]
            self.assertFalse(set(retried).intersection(url for url in calls if "num-months=1&" in url))
            self.assertTrue(any("num-months=12" in url for url in retried))
            from contextlib import closing
            import sqlite3
            with closing(sqlite3.connect(Path(temp)/"cache"/"responses.sqlite")) as db, patch.object(
                    rent_review, "publication", return_value=(rent_review.date(2025,2,1),"release-1")):
                data = rent_review.MarketData("test-key", Path(temp), [], db)
                city = {"definition":"TA2019","area_labels":["Christchurch City"],"codes":"060"}
                with patch("urllib.request.urlopen") as network:
                    missing = data.period(city, rent_review.date(2025,2,1), 1, "Flat", "2")
                    self.assertIsNone(missing["median"])
                    network.assert_not_called()
                data.release = "release-2"
                with patch("urllib.request.urlopen", wraps=original) as network:
                    data.period(city, rent_review.date(2025,2,1), 1, "House", "3")
                    data.period(city, rent_review.date(2024,3,1), 1, "House", "3")
                    self.assertEqual(network.call_count, 1)

    def test_resume_fallback_pdf_after_monthly_service_error(self):
        self.failure = None
        original = self.response
        def unavailable(req, timeout):
            if all(token in req.full_url for token in ("TA2019", "num-months=1&", "period-ending=2025-01")):
                raise HTTPError(req.full_url, 503, "unavailable", None, None)
            return original(req, timeout)
        with tempfile.TemporaryDirectory() as project:
            with patch.object(self, "response", unavailable):
                out = self.run_report(project)
            self.assertEqual(json.loads((out / "summary.json").read_text())["markets"][0]["chart_measure"], "arithmetic_mean")
            with patch.object(self, "response", wraps=original) as network:
                self.run_report(project)
                self.assertEqual(network.call_count, 1)
            self.assertEqual(json.loads((out / "summary.json").read_text())["markets"][0]["chart_measure"], "weighted_monthly_medians")
            with self.assertRaisesRegex(SystemExit, "report already exists"):
                self.run_report(project)

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
        if query["area-definition"] == ["TA2019"]:
            self.assertNotIn("dwelling-type", query)
            self.assertNotIn("num-bedrooms", query)
        else:
            self.assertEqual(query["dwelling-type"], ["House"])
            self.assertEqual(query["num-bedrooms"], ["3"])
        if query["num-months"] == ["1"]:
            end = rent_review.date.fromisoformat(query["period-ending"][0] + "-01")
            last = rent_review.shift(end, 1) - rent_review.timedelta(days=1)
            definition = query["area-definition"][0]
            local = definition != "TA2019"
            label = self.group_name if definition == "user-defined" else "Burwood" if local else "Christchurch City"
            rows = [{"area": label, "dwell": "House", "nBedrms": "3",
                     "med": 800 if end.month == 2 else 600, "nLodged": 30 if end.month == 2 else 6}]
            if local and (self.failure == "no-months" or self.failure == "gap" and end.year == 2024 and end.month == 2
                          or self.failure == "latest-gap" and end.year == 2025 and end.month == 2):
                rows = []
            if not local and self.failure == "city-gap" and end == rent_review.date(2025, 2, 1):
                rows = []
            payload = {"periodCovered": f"{end}/{last}", "areaDefinition": definition.upper().replace("-", ""),
                       "items": rows}
            return io.BytesIO(json.dumps(payload).encode())
        self.assertEqual(query["num-months"], ["12"])
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
        with patch.dict(rent_review.os.environ, {"MBIE_MARKET_RENT_API_KEY": "test-key", "MBIE_RENT_CACHE_DIR": str(Path(project)/"cache")}), \
             patch.object(rent_review, "publication", return_value=(rent_review.date(2025, 2, 1), "release-1")), \
             patch("urllib.request.urlopen", self.response):
            return rent_review.main(args)

    def report_summary(self, *options):
        with tempfile.TemporaryDirectory() as project:
            output = self.run_report(project, *options)
            self.assertTrue((output / "rent_review.pdf").is_file())
            self.assertTrue((output / "rent_review.png").is_file())
            return json.loads((output / "summary.json").read_text())

    def test_monthly_coverage_selects_one_measure_for_both_markets(self):
        for self.failure, expected in [(None, "weighted_monthly_medians"), ("gap", "arithmetic_mean"), ("latest-gap", "arithmetic_mean"),
                                       ("no-months", "arithmetic_mean"), ("city-gap", "arithmetic_mean")]:
            with self.subTest(coverage=self.failure):
                summary = self.report_summary()
                local, city = summary["markets"]
                self.assertAlmostEqual(summary["recommended_change_pct"], (local["chart_change_pct"] + city["chart_change_pct"]) / 2)
                self.assertEqual(local["chart_measure"], expected)
                self.assertEqual(city["chart_measure"], expected)
                if expected == "arithmetic_mean":
                    self.assertAlmostEqual(summary["recommended_change_pct"], 8)
                self.assertAlmostEqual(city["points"][0]["weighted_monthly_medians"], (800*30 + 600*66)/96)
                if self.failure == "gap":
                    self.assertIsNone(local["points"][0]["weighted_monthly_medians"])
                    self.assertAlmostEqual(local["chart_change_pct"], 8)
                    self.assertIsNotNone(local["points"][1]["weighted_monthly_medians"])
                if self.failure == "no-months":
                    self.assertAlmostEqual(local["chart_change_pct"], 8)

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
        self.assertEqual(len(summary["requests"]), 5 + 26)

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
        self.assertEqual(len(calls), 5 + 26)
        self.assertEqual(calls[1], calls[2])
        self.assertEqual(len(set(calls)), 4 + 26)
        self.assertEqual(len(summary["requests"]), 4 + 26)

    def test_persistent_server_error_names_period_and_writes_no_report(self):
        calls = []
        def unavailable(request, timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 503, "Service Unavailable", None, None)

        with tempfile.TemporaryDirectory() as project, patch.object(self, "response", unavailable):
            with self.assertRaisesRegex(SystemExit, "2025-01.*503"):
                self.run_report(project)
            self.assertEqual(len(calls), 2 * (26 + 1))
            self.assertEqual(calls[::2], calls[1::2])
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
