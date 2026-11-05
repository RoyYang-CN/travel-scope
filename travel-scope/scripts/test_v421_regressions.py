"""Executable regressions for the Travel-Scope v4.2.1 contract.

v4.2.1 is a gate-execution release. Every test here asserts that a check runs on
the path that actually ships, because v4.2.0's failures were all assertions that
existed but were unreachable.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import run_seal
import visual_qa

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent


def _source(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


class GateReachabilityTests(unittest.TestCase):
    """§1: the shipped renderer is the SPA; assertions must live on its path."""

    def test_spa_path_carries_the_reader_visible_assertions(self):
        body = _source("visual_qa.py")
        start = body.index("def check_spa_page(")
        end = body.index("def main() -> int:")
        spa_block = body[start:end]
        for marker in ("#topbar", ".route-line .rl-node", ".day summary", "#lang-btn",
                       "SPA_EN_POI_SUB", "SPA_HTML_LANG_STALE"):
            self.assertIn(marker, spa_block, f"check_spa_page 缺少 {marker} 断言")
        # The map/image contracts live in helpers, but only count when the shipped
        # path actually calls them.
        self.assertIn("check_embedded_map_contract(dataset, failures, result)", spa_block)
        self.assertIn("check_embedded_image_supply(page, failures, result, dataset)", spa_block)
        helpers_start = body.index("def check_embedded_map_contract(")
        helpers_end = body.index("def check_spa_page(")
        helpers = body[helpers_start:helpers_end]
        for code in ("MAP_TARGET_PLACEHOLDER", "IMG_SRCSET_ABSENT"):
            self.assertIn(code, helpers, f"SPA 调用的契约函数缺少 {code}")

    def test_spa_viewport_matrix_covers_mobile_and_desktop(self):
        self.assertEqual(len(visual_qa.SPA_VIEWPORTS), 6)
        widths = sorted(viewport[0] for viewport in visual_qa.SPA_VIEWPORTS)
        self.assertIn(360, widths)
        self.assertIn(1440, widths)

    def test_missing_spa_artifact_is_a_failure_not_a_skip(self):
        body = _source("visual_qa.py")
        self.assertIn("SPA_ARTIFACT_MISSING", body)
        self.assertNotIn('"label": "spa-all", "status": "SKIP"', body)

    def test_report_status_is_derived_not_hardcoded(self):
        body = _source("visual_qa.py")
        self.assertNotIn('{"status": "PASS", "html_sha256"', body)
        self.assertIn('"status": status', body)

    def test_delivery_gate_scans_the_spa_english_state(self):
        gate = _source("delivery_gate.py")
        self.assertIn("_check_spa_english_mode", gate)
        self.assertIn("spa-en-text.txt", gate)
        self.assertIn("english_text_check", gate)
        # §15.1.1: attesting the seal file is not attesting the release body.
        self.assertIn("verify_release_product()", gate)

    def test_map_placeholder_and_self_reference_codes_exist(self):
        for code in ("MAP_TARGET_PLACEHOLDER", "MAP_SOURCE_SELFREFERENTIAL",
                     "MAP_LEVEL_NAME_MISMATCH", "MAP_HREF_NUMERIC_CITY",
                     "MAP_PLACE_ID_SYNTHETIC"):
            self.assertIn(code, _source("visual_qa.py"))


class MapContractRegexTests(unittest.TestCase):
    """§14: an underscore slug must never satisfy a ChIJ place-id check."""

    def test_strict_regex_rejects_synthetic_slug(self):
        self.assertTrue(visual_qa.STRICT_PLACE_ID_RE.match("ChIJAbcdefghijklmnopqrst"))
        self.assertIsNone(visual_qa.STRICT_PLACE_ID_RE.match("ChIJ_shangrila_mactan"))
        self.assertIsNotNone(visual_qa.SYNTHETIC_PLACE_ID_RE.match("ChIJ_shangrila_mactan"))

    def test_placeholder_detector_matches_manufactured_venue_names(self):
        self.assertIsNotNone(visual_qa.MAP_PLACEHOLDER_SEGMENT_RE.search("California Venue"))
        self.assertIsNone(visual_qa.MAP_PLACEHOLDER_SEGMENT_RE.search("The Beverly Hills Hotel"))

    def test_query_segments_are_decoded(self):
        segments = visual_qa._map_query_segments(
            "https://www.google.com/maps/search/?api=1&query=39%2C%20California%2C%20California")
        self.assertEqual(segments, ["39", "California", "California"])
        self.assertTrue(visual_qa.MAP_NUMERIC_SEGMENT_RE.match("39"))


class SealTests(unittest.TestCase):
    """§13.2: seal the input, then prove nothing was edited behind our back."""

    def _run_dir(self, root: Path) -> Path:
        run = root / "run"
        (run / "outputs").mkdir(parents=True)
        (run / "evidence").mkdir()
        dataset = {"country": "测试国", "map_targets": {"k": {"canonical_name": "Real Name"}}}
        (run / "dataset.json").write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
        (run / "scope.json").write_text('{"selected_destinations": [{"name": "A"}]}', encoding="utf-8")
        (run / "route_corridors.json").write_text('{"corridors": []}', encoding="utf-8")
        (run / "asset-manifest.json").write_text('{"assets": []}', encoding="utf-8")
        (run / "evidence" / "map_verification.json").write_text('{"a": 1}', encoding="utf-8")
        artifact = run / "outputs" / "guide.html"
        artifact.write_text("<html>sealed</html>", encoding="utf-8")
        manifest = {"run_id": "unit", "seal_history": []}
        (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run

    def test_seal_then_untouched_state_verifies(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self._run_dir(Path(folder))
            seal = run_seal.seal_inputs(
                run / "manifest.json", run / "dataset.json", run,
                "python scripts/gen_travel_scope.py", "4.2.1", "split-v1", "spa-v1",
                generation_argv=["scripts/gen_travel_scope.py"])
            self.assertEqual(seal["input_sha256"], run_seal.file_sha256(run / "dataset.json"))
            run_seal.record_build(run / "manifest.json", {"guide.html": run / "outputs" / "guide.html"})
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(run_seal.verify_seal(run, manifest), [])

    def test_out_of_band_dataset_edit_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self._run_dir(Path(folder))
            run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                 "cmd", "4.2.1", "split-v1", "spa-v1", generation_argv=["gen"])
            run_seal.record_build(run / "manifest.json", {"guide.html": run / "outputs" / "guide.html"})
            (run / "dataset.json").write_text('{"country": "测试国", "map_targets": {}}', encoding="utf-8")
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            errors = run_seal.verify_seal(run, manifest)
            self.assertTrue(any("dataset.json 在封存后被改动" in error for error in errors))

    def test_delivered_html_edit_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self._run_dir(Path(folder))
            run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                 "cmd", "4.2.1", "split-v1", "spa-v1", generation_argv=["gen"])
            run_seal.record_build(run / "manifest.json", {"guide.html": run / "outputs" / "guide.html"})
            (run / "outputs" / "guide.html").write_text("<html>edited after delivery</html>", encoding="utf-8")
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            errors = run_seal.verify_seal(run, manifest)
            self.assertTrue(any("产物在封存后被改动" in error for error in errors))

    def test_evidence_edit_is_detected_through_collect_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self._run_dir(Path(folder))
            run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                 "cmd", "4.2.1", "split-v1", "spa-v1", generation_argv=["gen"])
            (run / "evidence" / "map_verification.json").write_text('{"a": 2}', encoding="utf-8")
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            errors = run_seal.verify_seal(run, manifest)
            self.assertTrue(any("采集阶段证据在封存后被改动" in error and "evidence/map_verification.json" in error
                                for error in errors), errors)

    def test_gate_report_written_after_seal_is_not_called_tampering(self):
        """A re-run gate must be allowed to write its report without breaking the input seal."""
        with tempfile.TemporaryDirectory() as folder:
            run = self._run_dir(Path(folder))
            run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                 "cmd", "4.2.1", "split-v1", "spa-v1", generation_argv=["gen"])
            (run / "evidence" / "media_audit.json").write_text('{"status": "PASS"}', encoding="utf-8")
            (run / "evidence" / "media_audit.json").write_text('{"status": "FAIL"}', encoding="utf-8")
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            errors = run_seal.verify_seal(run, manifest)
            self.assertFalse([e for e in errors if "采集阶段证据" in e], errors)

    def test_build_writes_its_own_release_fingerprint(self):
        """product_fingerprint must be written by the build, not inherited from an old run."""
        with tempfile.TemporaryDirectory() as folder:
            run = self._run_dir(Path(folder))
            run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                 "cmd", "4.2.1", "split-v1", "spa-v1", generation_argv=["gen"],
                                 product_fingerprint="a" * 64)
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["product_fingerprint"], "a" * 64)
            self.assertEqual(manifest["seal"]["product_fingerprint"], "a" * 64)
            gen = _source("gen_travel_scope.py")
            self.assertIn("product_fingerprint=file_sha256(release_root", gen)

    def test_reseal_requires_reason_and_blocks_silent_change(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self._run_dir(Path(folder))
            run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                 "cmd", "4.2.1", "split-v1", "spa-v1", generation_argv=["gen"])
            (run / "dataset.json").write_text('{"country": "改了", "map_targets": {}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                     "cmd", "4.2.1", "split-v1", "spa-v1", generation_argv=["gen"])
            with self.assertRaises(ValueError):
                run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                     "cmd", "4.2.1", "split-v1", "spa-v1",
                                     generation_argv=["gen"], allow_reseal=True, reason="   ")
            seal = run_seal.seal_inputs(run / "manifest.json", run / "dataset.json", run,
                                        "cmd", "4.2.1", "split-v1", "spa-v1",
                                        generation_argv=["gen"], allow_reseal=True, reason="补采 POI 名后重建")
            history = json.loads((run / "manifest.json").read_text(encoding="utf-8"))["seal_history"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["supersede_reason"], "补采 POI 名后重建")
            self.assertNotEqual(seal["input_sha256"], history[0]["input_sha256"])

    def test_record_build_refuses_unsealed_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self._run_dir(Path(folder))
            with self.assertRaises(ValueError):
                run_seal.record_build(run / "manifest.json", {"guide.html": run / "outputs" / "guide.html"})

    def test_missing_seal_is_reported_not_ignored(self):
        errors = run_seal.verify_seal(Path("."), {})
        self.assertTrue(errors)


class ReleaseSealTests(unittest.TestCase):
    """§15.1.3: resealing is a controlled, single-predicate operation."""

    def test_reseal_and_verify_share_the_release_predicate(self):
        import reseal_product
        import verify_product
        self.assertIs(reseal_product.release_file_paths, verify_product.release_file_paths)

    def test_approval_note_is_mandatory(self):
        with self.assertRaises(ValueError):
            reseal_product_reject_short_approval()

    def test_version_cannot_decrease(self):
        import reseal_product
        self.assertEqual(reseal_product._version_tuple("4.2.1"), (4, 2, 1))
        with self.assertRaises(ValueError):
            reseal_product._version_tuple("4.2.100")


def reseal_product_reject_short_approval() -> None:
    import reseal_product
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "references").mkdir()
        for name in ("renderer-contract.json", "version-policy.json", "provenance-policy.json"):
            (root / "references" / name).write_text("{}", encoding="utf-8")
        (root / "SKILL.md").write_text("x", encoding="utf-8")
        reseal_product.reseal(root, "4.9.0", "短")


class WorkbookDeterminismTests(unittest.TestCase):
    """§13.2.3: the container must not carry wall-clock noise."""

    def test_normalize_freezes_core_props_and_zip_dates(self):
        import gen_travel_scope
        from datetime import datetime

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "book.xlsx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("docProps/core.xml",
                                 "<cp:coreProperties><dcterms:created>2020-01-01T00:00:00Z</dcterms:created>"
                                 "<dcterms:modified>2020-01-01T00:00:00Z</dcterms:modified></cp:coreProperties>")
                archive.writestr("xl/workbook.xml", "<workbook/>")
            stamp = datetime(2026, 10, 25, 19, 17, 4)
            gen_travel_scope._normalize_xlsx_bytes(path, stamp)
            first = path.read_bytes()
            gen_travel_scope._normalize_xlsx_bytes(path, stamp)
            self.assertEqual(first, path.read_bytes())
            with zipfile.ZipFile(path) as frozen:
                info = frozen.getinfo("docProps/core.xml")
                self.assertEqual(info.date_time, (2026, 10, 25, 19, 17, 4))
                core = frozen.read("docProps/core.xml").decode("utf-8")
                self.assertIn("2026-10-25T19:17:04Z", core)
                self.assertNotIn("2020-01-01", core)

    def test_seal_timestamp_reads_pinned_env_and_rejects_garbage(self):
        import os
        import gen_travel_scope
        original = os.environ.get(gen_travel_scope.SEAL_TIMESTAMP_ENV)
        try:
            os.environ[gen_travel_scope.SEAL_TIMESTAMP_ENV] = "2026-10-25T19:17:04+08:00"
            self.assertEqual(gen_travel_scope._seal_timestamp().isoformat(), "2026-10-25T19:17:04+08:00")
            os.environ[gen_travel_scope.SEAL_TIMESTAMP_ENV] = "not-a-time"
            with self.assertRaises(ValueError):
                gen_travel_scope._seal_timestamp()
        finally:
            if original is None:
                os.environ.pop(gen_travel_scope.SEAL_TIMESTAMP_ENV, None)
            else:
                os.environ[gen_travel_scope.SEAL_TIMESTAMP_ENV] = original


class ProductIntegrityTests(unittest.TestCase):
    def test_release_body_verifies_after_step_changes(self):
        import verify_product
        result = verify_product.verify(ROOT)
        self.assertEqual(result["version"], "5.0.0")
        self.assertGreaterEqual(len(result["inventory"]), 97)
        self.assertIn("scripts/run_seal.py", result["inventory"])
        self.assertIn("scripts/replay_build.py", result["inventory"])
        self.assertIn("scripts/reseal_product.py", result["inventory"])
        # v4.2.2 V1：新增的发布文件必须真的进封面，否则“改了代码但没重封”会静默通过。
        for v422_release_file in ("scripts/map_link_selector.py",
                                  "references/map-link-selection.json",
                                  "scripts/test_v422_map_honest_contract.py"):
            self.assertIn(v422_release_file, result["inventory"],
                          "%s 未进入 product-origin 封面：必须先 reseal_product 再跑测试"
                          % v422_release_file)


class ImageAttestationTests(unittest.TestCase):
    """SS5: delivered image bytes must be reconcilable with the manifest digests, for all entries."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "assets" / "editorial").mkdir(parents=True)
        self.good = self.root / "assets" / "editorial" / "good.jpg"
        self.lied = self.root / "assets" / "editorial" / "lied.jpg"
        self.good.write_bytes(b"\xff\xd8\xff\xe0" + b"good-bytes" * 40)
        self.lied.write_bytes(b"\xff\xd8\xff\xe1" + b"shipped-bytes" * 40)
        self.entries = [
            {"local_file": "assets/editorial/good.jpg",
             "sha256": hashlib.sha256(self.good.read_bytes()).hexdigest()},
            {"local_file": "assets/editorial/lied.jpg", "sha256": "0" * 64},
        ]
        self.manifest = {"assets": self.entries}

    def tearDown(self):
        self.tmp.cleanup()

    def test_digest_sweep_names_every_mismatch_not_just_the_first(self):
        import local_media_gate
        rows = local_media_gate.asset_digest_sweep(self.manifest, self.root)
        self.assertEqual(len(rows), 2, "sweep must cover every asset")
        stale = [r["local_file"] for r in rows if not r["matches_claim"]]
        self.assertEqual(stale, ["assets/editorial/lied.jpg"])

    def test_delivered_blob_that_matches_disk_but_not_manifest_is_called_stale(self):
        import local_media_gate
        blob = "data:image/jpeg;base64," + base64.b64encode(self.lied.read_bytes()).decode("ascii")
        html_text = f"<img src=\"{blob}\"><img src=\"{blob}\">"
        errors, metrics = local_media_gate.attest_delivered_images(html_text, self.manifest, self.root)
        self.assertEqual(metrics["inline_unique_images"], 1)
        self.assertEqual(metrics["inline_digest_stale"], 1)
        self.assertEqual(metrics["inline_attested"], 0)
        codes = {e.split("|", 1)[0] for e in errors}
        self.assertIn("IMG_MANIFEST_DIGEST_STALE", codes, errors)
        self.assertIn("IMG_INLINE_DUPLICATE", codes, "same bitmap pasted twice must be named")

    def test_orphan_delivered_blob_is_unattested_not_silently_forgiven(self):
        import local_media_gate
        blob = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe2" + b"orphan-bytes" * 40).decode("ascii")
        errors, metrics = local_media_gate.attest_delivered_images(f"<img src=\"{blob}\">", self.manifest, self.root)
        self.assertEqual(metrics["inline_unattested"], 1)
        self.assertTrue(any(e.startswith("IMG_DELIVERED_UNATTESTED") for e in errors), errors)

    def test_attested_blob_passes(self):
        import local_media_gate
        blob = "data:image/jpeg;base64," + base64.b64encode(self.good.read_bytes()).decode("ascii")
        errors, metrics = local_media_gate.attest_delivered_images(f"<img src=\"{blob}\">", self.manifest, self.root)
        self.assertEqual(errors, [])
        self.assertEqual(metrics["inline_attested"], 1)

    def test_renderer_inlines_each_bitmap_once(self):
        import spa_renderer
        body = Path(spa_renderer.__file__).read_text(encoding="utf-8")
        self.assertIn("_embed_media_as_asset_ref", body)
        self.assertIn("adapted[\"asset_blobs\"]", body)
        js = (ROOT / "assets" / "spa-layout.js").read_text(encoding="utf-8")
        self.assertIn("function assetUrl(value)", js)
        self.assertGreaterEqual(js.count("assetUrl("), 5, "every image read site must resolve references")

    def test_visual_qa_loads_the_deliverable_without_its_assets_folder(self):
        body = _source("visual_qa.py")
        start = body.index("def check_standalone_images(")
        end = body.index("def main() -> int:")
        self.assertIn("SPA_IMAGES_NOT_SELF_CONTAINED", body[start:end])
        # defined but unreachable is the v4.2.0 failure mode, so assert the shipped path calls it
        self.assertIn("check_standalone_images(", body[end:])
        self.assertIn("shutil.copy2(spa_html, lonely)", body[end:])


class DegradedTierGateTests(unittest.TestCase):
    """SS11.5: an explicitly labelled coordinate target is a decision, not an entity-type violation."""

    def _targets(self, level, entity_type, name=""):
        return {"A|测试点": {"canonical_name": name, "destination": "A", "country": "Country Z",
                             "entity_type": entity_type, "target_level": level,
                             "coords": "1.0,2.0", "display_name_cn": "测试点",
                             "unnamed_reason": "no_verified_english_name",
                             "google_url": "https://www.google.com/maps/search/?api=1&query=1.0,2.0",
                             "apple_url": "https://maps.apple.com/?q=1.0,2.0"}}

    def _errors(self, targets):
        import map_contract
        data = {"map_region": "international", "hotels": [["A", "测试点", "", "", "1.0,2.0"]],
                "restaurants": [], "cafes": [], "attractions": [], "map_targets": targets}
        return map_contract.audit_map_targets(data, require_exact=True)[0]

    def test_unnamed_coordinate_poi_is_not_demanded_to_be_named_entity(self):
        errors = self._errors(self._targets("unnamed_coordinate", "coordinate_landmark"))
        self.assertFalse([e for e in errors if "必须标记为 named_entity" in e], errors)

    def test_plain_coordinate_landmark_poi_is_still_rejected(self):
        errors = self._errors(self._targets("verified_coordinate", "coordinate_landmark", name="Test Place"))
        self.assertTrue([e for e in errors if "必须标记为 named_entity" in e], errors)


if __name__ == "__main__":
    unittest.main()
