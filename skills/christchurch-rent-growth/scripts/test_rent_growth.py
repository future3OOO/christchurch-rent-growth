import io
import json
import math
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import christchurch_rent_growth as growth
import rent_review


class ApiWorkflowTests(unittest.TestCase):
    def response(self, request, timeout):
        query = parse_qs(urlparse(request.full_url).query)
        if request.full_url.endswith('/area-definitions/territorial-authority-2019'):
            payload = {'items': [{'label': 'Selwyn District', 'code': '062'}]}
        else:
            end = date.fromisoformat(query['period-ending'][0] + '-01')
            months = int(query['num-months'][0])
            start = growth.shift(end, 1 - months)
            last = growth.shift(end, 1).replace(day=1)
            last -= timedelta(days=1)
            # Annual means deliberately differ from pooled monthly means.
            logmean = math.log(600 if end.year == 2026 else 500) if months == 12 else math.log(550)
            payload = {'areaDefinition': 'TA2019',
                       'periodCovered': f'{start.year}-{start.month}-1/{last.year}-{last.month}-{last.day}',
                       'items': [{'area': 'Selwyn District', 'dwell': 'ALL', 'nBedrms': 'ALL',
                                  'nLodged': 120, 'lmean': logmean, 'mean': 999}]}
            if self.failure == 'suppressed':
                payload['items'] = []
            elif self.failure == 'wrong-period':
                payload['periodCovered'] = '2020-1-1/2020-12-31'
            elif self.failure == 'duplicate':
                payload['items'] *= 2
        return io.BytesIO(json.dumps(payload).encode())

    def run_workflow(self, project, months=24):
        argv = ['rent-growth', '--project-dir', project, '--location', 'Selwyn District',
                '--end-month', '2026-08', '--months', str(months), '--current-rent', '580']
        with patch.object(sys, 'argv', argv), patch.dict(growth.os.environ, {'MBIE_MARKET_RENT_API_KEY': 'test-key'}), \
                patch.object(growth.urllib.request, 'urlopen', self.response), patch('sys.stdout', new_callable=io.StringIO):
            growth.main()

    def test_annual_api_means_drive_two_year_growth_and_outputs(self):
        self.failure = None
        with tempfile.TemporaryDirectory() as project:
            self.run_workflow(project)
            paths = list(Path(project).rglob('*_summary.json'))
            self.assertEqual(len(paths), 1)
            summary = json.loads(paths[0].read_text())
            self.assertAlmostEqual(summary['overall_change_pct'], 20)
            self.assertAlmostEqual(summary['previous_period']['pooled_geometric_mean'], 500)
            self.assertAlmostEqual(summary['latest_period']['pooled_geometric_mean'], 600)
            self.assertEqual(len(summary['monthly_yoy_pct']), 24)
            self.assertEqual(summary['proposed_weekly_rent'], 695)
            self.assertEqual(summary['location'], 'Selwyn District')
            self.assertEqual(summary['chart_dashed_line_pct'], summary['overall_change_pct'])
            self.assertEqual(len(list(Path(project).rglob('*.png'))), 1)
            self.assertEqual(len(list(Path(project).rglob('*.pdf'))), 1)

    def test_invalid_api_responses_do_not_produce_charts(self):
        for failure in ('suppressed', 'wrong-period', 'duplicate'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as project:
                self.failure = failure
                with self.assertRaisesRegex(SystemExit, 'VALIDATION FAILED'):
                    self.run_workflow(project)
                self.assertEqual(list(Path(project).rglob('*.png')), [])

    def test_twelve_month_report_compares_adjacent_annual_windows(self):
        self.failure = None
        with tempfile.TemporaryDirectory() as project:
            self.run_workflow(project, months=12)
            summary = json.loads(next(Path(project).rglob('*_summary.json')).read_text())
            self.assertEqual(summary['previous_period']['end'], '2025-08')
            self.assertEqual(summary['latest_period']['end'], '2026-08')
            self.assertEqual(len(summary['monthly_yoy_pct']), 12)
            self.assertAlmostEqual(summary['overall_change_pct'], 20)


class RentReviewTests(unittest.TestCase):
    def response(self, request, timeout):
        url = request.full_url
        query = parse_qs(urlparse(url).query)
        if url.endswith("/area-definitions/SAU2019"):
            payload = {"items": [{"label": "Mairehau North", "code": "321700"},
                                  {"label": "Mairehau South", "code": "323100"}]}
        elif url.endswith("/area-definitions/TA2019"):
            payload = {"items": [{"label": "Christchurch City", "code": "060"}]}
        else:
            self.assertEqual(query["num-months"], ["12"])
            self.assertEqual(query["dwelling-type"], ["House"])
            self.assertEqual(query["num-bedrooms"], ["3"])
            end = query["period-ending"][0]
            local = query["area-definition"] == ["SAU2019"]
            latest = end == "2025-02"
            label = "ALL" if local else "Christchurch City"
            row = {"area": label, "dwell": "House", "nBedrms": "3",
                   "lmean": math.log(660 if latest else 600), "med": 650 if latest else 620,
                   "mean": 999, "nLodged": 57 if latest else 69}
            items = [row]
            if local:
                items += [{**row, "area": name} for name in ["Mairehau North", "Mairehau South"]]
            payload = {"areaDefinition": "SAU2019" if local else "TA2019",
                       "periodCovered": "2024-3-1/2025-2-28" if latest else "2024-2-1/2025-1-31",
                       "items": items}
            if self.failure == "wrong-bedroom":
                payload["items"] = [{**r, "nBedrms": "2"} for r in items]
            elif self.failure == "wrong-period":
                payload["periodCovered"] = "2020-1-1/2020-12-31"
        return io.BytesIO(json.dumps(payload).encode())

    def run_report(self, project):
        args = ["--project-dir", project, "--address", "90 Aylesford Street", "--suburb", "Mairehau",
                "--area-codes", "321700,323100", "--bedrooms", "3", "--dwelling-type", "House",
                "--start-month", "2025-01", "--end-month", "2025-02"]
        with patch.dict(rent_review.os.environ, {"MBIE_MARKET_RENT_API_KEY": "test-key"}), \
             patch.object(rent_review.growth.urllib.request, "urlopen", self.response):
            return rent_review.main(args)

    def test_full_report_uses_direct_annual_medians_and_geometric_baseline(self):
        self.failure = None
        with tempfile.TemporaryDirectory() as project:
            output = self.run_report(project)
            summary = json.loads((output / "summary.json").read_text())
            for market in summary["markets"]:
                self.assertEqual(len(market["points"]), 2)
                self.assertAlmostEqual(market["geometric_change_pct"], 10)
                self.assertEqual(market["points"][0]["median"], 620)
                self.assertEqual(market["points"][1]["median"], 650)
                self.assertEqual(market["points"][0]["window_start"], "2024-02")
            self.assertTrue((output / "rent_review.pdf").is_file())
            self.assertTrue((output / "rent_review.png").is_file())

    def test_wrong_scope_or_period_cannot_produce_a_report(self):
        for failure in ["wrong-bedroom", "wrong-period"]:
            self.failure = failure
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as project:
                with self.assertRaisesRegex(SystemExit, "VALIDATION FAILED"):
                    self.run_report(project)
                self.assertEqual(list(Path(project).rglob("*.pdf")), [])


if __name__ == '__main__':
    unittest.main()
