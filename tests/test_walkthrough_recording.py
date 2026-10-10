"""Tests for walkthrough recording: statement map, line tracing and the step plan.

Run from the repository root:
    python -m unittest discover tests -v

The weather example needs pandas; its tests are skipped when pandas isn't installed.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODESTORY = os.path.join(ROOT, "codestory.py")
WEATHER = os.path.join(ROOT, "examples", "weather-pipeline", "project")
LOGS = os.path.join(ROOT, "examples", "log-check-scan", "project")
HAS_PANDAS = importlib.util.find_spec("pandas") is not None


def record(cwd, *args, program_args=()):
    out = os.path.join(tempfile.mkdtemp(), "bundle.json")
    cmd = [sys.executable, CODESTORY, *args, "-o", out]
    if program_args:
        cmd += ["--", *program_args]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise AssertionError(f"codestory failed:\n{proc.stderr}")
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


def md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def steps(bundle, **match):
    return [s for s in bundle["plan"]["steps"] if all(s.get(k) == v for k, v in match.items())]


def rows(summary):
    return summary.get("rows") if isinstance(summary, dict) else None


@unittest.skipUnless(HAS_PANDAS, "pandas not installed")
class WeatherRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(WEATHER, "data", "stations.db")
        cls.db_before = md5(cls.db)
        cls.b = record(WEATHER, "run", "main.py", "--view", "walkthrough",
                       program_args=["--date", "2026-10-01", "--full-refresh"])

    def test_bundle_sections(self):
        b = self.b
        self.assertEqual(b["schema"], "codestory.bundle/2")
        self.assertEqual(b["view"], "walkthrough")
        for key in ("sources", "statements", "plan", "lines"):
            self.assertIn(key, b)
        self.assertIn("etl/clean.py", b["sources"])

    def test_safe_mode_still_holds(self):
        self.assertEqual(md5(self.db), self.db_before)
        self.assertFalse(os.path.exists(os.path.join(WEATHER, "output")))

    def test_values_through_drop_invalid(self):
        dropna = steps(self.b, stmt="etl/clean.py:15")[0]
        self.assertEqual(rows(dropna["changes"]["df"]), 582)
        ret = steps(self.b, stmt="etl/clean.py:16")[0]
        self.assertEqual(rows(ret["value"]), 576)
        enter = steps(self.b, type="enter", fn="etl.clean:drop_invalid")[0]
        self.assertEqual(rows(enter["args"]["df"]), 601)

    def test_in_place_change_is_recorded(self):
        conv = steps(self.b, stmt="etl/clean.py:8")[0]
        self.assertTrue(conv["changes"]["df"].get("in_place"))

    def test_calls_return_to_their_call_site(self):
        ids = {s["id"]: s for s in self.b["plan"]["steps"]}
        for r in steps(self.b, type="return"):
            if r.get("to_step"):
                self.assertIn(r["to_step"], ids)
        ret = steps(self.b, type="return", fn="etl.clean:clean")[0]
        self.assertEqual(ids[ret["to_step"]]["stmt"], "main.py:30")
        self.assertEqual(rows(ret["changes"]["readings"]), 552)

    def test_branches(self):
        self.assertEqual(steps(self.b, stmt="etl/load.py:16")[0]["branch"]["taken"], "body")      # --full-refresh
        self.assertEqual(steps(self.b, stmt="main.py:38")[0]["branch"]["taken"], "body")          # 3 anomalies

    def test_short_loop_shown_in_full(self):
        for fn in ("etl.clean:to_celsius", "etl.clean:drop_invalid", "etl.clean:dedupe"):
            self.assertEqual(len(steps(self.b, type="enter", fn=fn)), 1, fn)
        self.assertEqual(steps(self.b, stmt="etl/clean.py:25")[0]["loop"]["iterations"], 3)

    def test_multi_line_statement_is_one_step(self):
        self.assertEqual(len(steps(self.b, stmt="etl/transform.py:13")), 1)

    def test_with_exit_is_not_a_step(self):
        self.assertEqual(len(steps(self.b, stmt="etl/extract.py:13")), 1)

    def test_explain_first_starts_with_data(self):
        first = self.b["plan"]["explain_first"][:3]
        self.assertIn("etl/extract.py:7", first)


class LogCheckerRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = record(LOGS, "run", "analyze_logs.py", "--view", "walkthrough")

    def test_long_loop_collapses(self):
        summary = steps(self.b, type="loop_summary")[0]
        self.assertEqual(summary["iterations"], 200)
        self.assertEqual(summary["changes"]["total"]["len"], 6)
        self.assertEqual(summary["changes"]["errors"]["len"], 6)
        hidden = [s for s in self.b["plan"]["steps"] if s.get("hidden_by") == summary["id"]]
        self.assertTrue(hidden)

    def test_generator_yields_value(self):
        y = [s for s in steps(self.b, type="return", fn="analyze_logs:parse") if s.get("yield")]
        self.assertTrue(y)
        self.assertEqual(y[0]["value"]["len"], 5)

    def test_lambdas_are_not_stepped_into(self):
        self.assertFalse([s for s in self.b["plan"]["steps"] if "<lambda>" in s.get("fn", "")])

    def test_email_blocked(self):
        self.assertTrue(any(e["kind"] == "email" and e.get("handled") == "blocked" for e in self.b["io"]["events"]))


@unittest.skipUnless(HAS_PANDAS, "pandas not installed")
class Scan(unittest.TestCase):
    def test_reading_order(self):
        b = record(WEATHER, "scan", "main.py", "--view", "walkthrough")
        enters = [s["fn"] for s in steps(b, type="enter")]
        self.assertLess(enters.index("etl.transform:enrich"), enters.index("etl.transform:daily_summary"))
        self.assertIn("config:<module>", enters)
        for fn in ("etl.clean:to_celsius", "etl.clean:drop_invalid", "etl.clean:dedupe"):
            self.assertEqual(steps(b, type="enter", fn=fn)[0]["via"], "reference")
        self.assertEqual(steps(b, stmt="main.py:38")[0]["branch"]["taken"], "possible")

    def test_focus_function(self):
        b = record(WEATHER, "scan", "main.py", "--view", "walkthrough", "--focus", "etl.transform:flag_anomalies")
        self.assertEqual([s["type"] for s in b["plan"]["steps"]], ["enter", "statement", "statement", "statement", "return"])


class Edges(unittest.TestCase):
    def test_crash_marks_the_raising_line(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "crash.py"), "w") as fh:
            fh.write(textwrap.dedent("""
                def total(rows):
                    s = 0
                    for r in rows:
                        s += r["b"]
                    return s
                print(total([{"a": 1}]))
            """))
        b = record(d, "run", "crash.py", "--view", "walkthrough")
        self.assertEqual(b["run"]["status"], "error")
        raising = steps(b, stmt="crash.py:5")[0]
        self.assertIn("KeyError", raising["raised"])

    def test_story_view_is_unchanged(self):
        b = record(LOGS, "scan", "analyze_logs.py")
        for key in ("view", "plan", "statements", "sources", "lines"):
            self.assertNotIn(key, b)

    def test_unknown_focus_is_an_error(self):
        proc = subprocess.run([sys.executable, CODESTORY, "scan", "analyze_logs.py", "--view", "walkthrough",
                               "--focus", "nosuch", "-o", os.path.join(tempfile.mkdtemp(), "b.json")],
                              cwd=LOGS, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("nosuch", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
