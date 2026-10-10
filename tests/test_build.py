"""Tests for `codestory.py build`: both players, the shared engine, and the walkthrough payload.

Run from the repository root:
    python -m unittest discover tests -v
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODESTORY = os.path.join(ROOT, "codestory.py")
LOGS = os.path.join(ROOT, "examples", "log-check-scan")


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, CODESTORY, *args], cwd=cwd, capture_output=True, text=True, timeout=300)


def embedded(html, element_id):
    m = re.search(r'<script id="%s" type="application/json">(.*?)</script>' % element_id, html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_story_build_embeds_engine_and_storyboard(self):
        out = os.path.join(self.tmp, "story.html")
        p = run("build", os.path.join(LOGS, "storyboard.json"), "-o", out)
        self.assertEqual(p.returncode, 0, p.stderr)
        html = open(out, encoding="utf-8").read()
        self.assertNotIn('src="engine.js"', html)
        self.assertIn("CodestoryAnim", html)
        self.assertEqual(embedded(html, "storyboard")["schema"], "codestory.storyboard/1")

    def test_walkthrough_build_merges_bundle_and_document(self):
        bundle = os.path.join(self.tmp, "bundle.json")
        p = run("scan", "analyze_logs.py", "--view", "walkthrough", "-o", bundle, cwd=os.path.join(LOGS, "project"))
        self.assertEqual(p.returncode, 0, p.stderr)
        out = os.path.join(self.tmp, "walkthrough.html")
        p = run("build", os.path.join(LOGS, "walkthrough.json"), "--bundle", bundle, "-o", out)
        self.assertEqual(p.returncode, 0, p.stderr)
        html = open(out, encoding="utf-8").read()
        self.assertNotIn('src="engine.js"', html)
        data = embedded(html, "walkthrough")
        self.assertEqual(data["schema"], "codestory.walkthrough-payload/1")
        self.assertEqual(data["mode"], "scan")
        self.assertIn("analyze_logs.py", data["files"])
        self.assertTrue(data["steps"])
        # explanations are keyed by statement ids that exist in the bundle
        for sid in data["explanations"]:
            self.assertIn(sid, data["statements"], sid)

    def test_walkthrough_needs_its_bundle(self):
        p = run("build", os.path.join(LOGS, "walkthrough.json"), "-o", os.path.join(self.tmp, "w.html"))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--bundle", p.stderr + p.stdout)

    def test_walkthrough_rejects_a_story_bundle(self):
        bundle = os.path.join(self.tmp, "story_bundle.json")
        run("scan", "analyze_logs.py", "-o", bundle, cwd=os.path.join(LOGS, "project"))
        p = run("build", os.path.join(LOGS, "walkthrough.json"), "--bundle", bundle, "-o", os.path.join(self.tmp, "w.html"))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--view walkthrough", p.stderr + p.stdout)

    def test_player_scripts_are_not_broken_by_data(self):
        # a storyboard containing "</script>" must not end the data block early
        sb = {"schema": "codestory.storyboard/1", "title": "</script><b>x", "mode": "scan",
              "scenes": [{"id": "a", "phase": "setup", "title": "t", "narration": "</script>"}]}
        src = os.path.join(self.tmp, "sb.json")
        json.dump(sb, open(src, "w"))
        out = os.path.join(self.tmp, "s.html")
        self.assertEqual(run("build", src, "-o", out).returncode, 0)
        html = open(out, encoding="utf-8").read()
        self.assertEqual(embedded(html, "storyboard")["scenes"][0]["narration"], "</script>")


if __name__ == "__main__":
    unittest.main()


class WalkthroughValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bundle = os.path.join(cls.tmp, "bundle.json")
        p = run("scan", "analyze_logs.py", "--view", "walkthrough", "-o", cls.bundle, cwd=os.path.join(LOGS, "project"))
        assert p.returncode == 0, p.stderr

    def build(self, doc, *extra):
        src = os.path.join(self.tmp, "doc.json")
        json.dump(doc, open(src, "w"))
        return run("build", src, "--bundle", self.bundle, "-o", os.path.join(self.tmp, "w.html"), *extra)

    def doc(self, **kw):
        d = {"schema": "codestory.walkthrough/1", "title": "T",
             "explanations": {"analyze_logs.py:21": {"title": "Match the line", "text": "search returns a Match or None."}}}
        d.update(kw)
        return d

    def test_valid_document_builds(self):
        p = self.build(self.doc())
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_unknown_statement_is_rejected_with_a_hint(self):
        p = self.build(self.doc(explanations={"analyze_logs.py:19": {"title": "t", "text": "x"}}))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no such statement", p.stderr)
        self.assertIn("statements in that file start at lines", p.stderr)

    def test_missing_text_and_long_title_are_rejected(self):
        p = self.build(self.doc(explanations={"analyze_logs.py:21": {"title": "x" * 61}}))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("title is 61 characters", p.stderr)
        self.assertIn("text is required", p.stderr)

    def test_unknown_fields_and_note_ids_are_rejected(self):
        p = self.build(self.doc(summary="x", notes={"s9999": "y"}))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("unknown field 'summary'", p.stderr)
        self.assertIn("notes['s9999']", p.stderr)

    def test_grouped_statement_gets_a_note(self):
        p = self.build(self.doc(explanations={"analyze_logs.py:3": {"title": "Import json", "text": "x"}}))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("grouped step", p.stderr)

    def test_force_builds_anyway(self):
        p = self.build(self.doc(explanations={"nope.py:1": {"title": "t", "text": "x"}}), "--force")
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_schema_file_matches_validator(self):
        schema = json.load(open(os.path.join(ROOT, "walkthrough.schema.json")))
        self.assertEqual(schema["$id"], "codestory.walkthrough/1")
        self.assertEqual(set(schema["properties"]), {"schema", "title", "subtitle", "entry", "explanations", "notes"})
        try:
            import jsonschema
        except ImportError:
            return
        for name in ("weather-pipeline", "log-check-scan"):
            jsonschema.validate(json.load(open(os.path.join(ROOT, "examples", name, "walkthrough.json"))), schema)
