"""Test suite for Release Provenance and Anti-Contamination Contract (Travel-Scope v4.0.13)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from provenance_contract import audit_run_provenance, load_provenance_policy


class ProvenanceContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_provenance_policy(self):
        policy = load_provenance_policy()
        self.assertEqual(policy["target_version"], "5.0.0")
        self.assertTrue(policy["strict_self_containment"])
        self.assertIn("travel-scope-v4.0.10", policy["banned_path_patterns"])
        self.assertIn("travel-scope-v4.0.11", policy["banned_path_patterns"])
        self.assertIn("evidence/delivery_gate.json", policy["disallowed_legacy_gate_reports"])

    def test_detects_legacy_duplicate_delivery_gate(self):
        evidence_dir = self.run_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "delivery_gate.json").write_text('{"status": "PASS"}', encoding="utf-8")
        manifest = {"skill_version": "5.0.0"}
        errors = audit_run_provenance(self.run_dir, manifest=manifest)
        self.assertTrue(any("evidence/delivery_gate.json" in e for e in errors))

    def test_detects_banned_version_patterns(self):
        manifest = {
            "skill_version": "5.0.0",
            "research_evidence": {
                "source_path": "d:/runs/travel_scope_run_202702_philippines_v410_001/evidence.json"
            }
        }
        errors = audit_run_provenance(self.run_dir, manifest=manifest)
        self.assertTrue(any("v410" in e or "违规历史版本" in e for e in errors))

    def test_detects_escaping_run_directory_paths(self):
        manifest = {
            "skill_version": "5.0.0",
            "output_link": "D:/文档/项目开发/Travel-Scope/runs/other_run/evidence/something.json"
        }
        errors = audit_run_provenance(self.run_dir, manifest=manifest)
        self.assertTrue(any("越界指向外部运行目录" in e for e in errors))

    def test_clean_run_passes_provenance_audit(self):
        manifest = {
            "skill_version": "5.0.0",
            "outputs": {
                "html_path": str(self.run_dir / "outputs/report.html")
            }
        }
        (self.run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        errors = audit_run_provenance(self.run_dir)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
