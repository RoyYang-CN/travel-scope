# -*- coding: utf-8 -*-
"""v4.2.1 §5.4/§12 media-chain regressions.

Every test here guards a behaviour that the step-14/15 builds got wrong in a way no existing test
could see: a declared rendition that silently stops being delivered, a picture that ships without
a manifest row, and a slot that pays for two renditions in one file.
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import local_media_gate                                      # noqa: E402
import prepare_media                                         # noqa: E402
import spa_renderer                                          # noqa: E402

try:
    from PIL import Image
except ImportError:                                          # pragma: no cover
    Image = None


def _jpeg(path: Path, width: int = 400, height: int = 300) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if Image is not None:
        image = Image.new("RGB", (width, height), (120, 160, 200))
        image.save(path, format="JPEG", quality=60)
    else:                                                    # pragma: no cover
        path.write_bytes(b"\xff\xd8\xff\xd9")
    return path.read_bytes()


class SlotMappingTests(unittest.TestCase):
    """A hero routed to the wrong tier set is bytes the reader never uses."""

    def test_route_hero_maps_to_hero_not_to_the_fallback_slot(self):
        self.assertEqual(prepare_media.slot_for({"display_role": "route_hero"}), "hero")
        self.assertEqual(prepare_media.slot_for({"category": "EDITORIAL"}), "hero")
        self.assertEqual(prepare_media.slot_for({"display_role": "section_cover"}),
                         "destination_atmosphere")

    def test_unknown_slot_is_an_error_not_a_quiet_default(self):
        if Image is None:                                    # pragma: no cover
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src" / "pic.jpg"
            _jpeg(source)
            with self.assertRaises(ValueError) as ctx:
                prepare_media.prepare_asset(source, Path(tmp) / "out", slot="route_hero")
            self.assertIn("MEDIA_SLOT_UNKNOWN", str(ctx.exception))

    def test_prepare_never_distorts_the_picture(self):
        if Image is None:                                    # pragma: no cover
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src" / "pano.jpg"
            _jpeg(source, width=1200, height=140)             # 8.6:1 panorama
            out = prepare_media.prepare_asset(source, Path(tmp) / "renditions",
                                              slot="destination_atmosphere")
            tier = out["renditions"][0]
            # 宽度跟着登记走（V6-C 起交付档由 single-file-delivery-policy.json 决定），
            # 这里不再抄一份 800——抄了就会在下次改档时把「按登记出货」误判成变形。
            registered = prepare_media.slot_tiers("destination_atmosphere")[0]
            self.assertEqual(tier["width"], min(registered[1], 1200),
                             "交付档宽度必须等于登记的 max_width_px")
            self.assertAlmostEqual(tier["height"] / tier["width"], 140.0 / 1200.0, delta=0.01,
                                   msg="宽高比必须保住：8.6:1 全景不许被压进任何方框")
            self.assertLess(tier["aspect_drift"], prepare_media.ASPECT_TOLERANCE)
            self.assertEqual(out["source_width"], 1200)
            self.assertTrue(tier["delivered_sha256"])


class TierDeliveryTests(unittest.TestCase):
    """§5.4.7: a declared rendition must be delivered, and only one rendition per slot."""

    def _layout(self, root: Path):
        (root / "run" / "assets" / "renditions").mkdir(parents=True, exist_ok=True)
        (root / "out" / "assets" / "editorial").mkdir(parents=True, exist_ok=True)
        source = root / "run" / "assets" / "editorial" / "cover.jpg"
        _jpeg(source, 1200, 800)
        wide = root / "run" / "assets" / "renditions" / "cover--w1200.jpg"
        small = root / "run" / "assets" / "renditions" / "cover--w800.jpg"
        _jpeg(wide, 1200, 800)
        _jpeg(small, 800, 533)
        return source, wide, small

    def _dataset(self, tiers):
        return {
            "route_budgets": {}, "duration_days": 3, "country": "测试国",
            "hero_image": "assets/editorial/cover.jpg",
            "editorial_media": [{"route": "R1", "image": "assets/editorial/cover.jpg",
                                 "title": "封面"}],
            "section_media": [], "routes": [["R1", "R1", "c", "1天", "t", 1, "h"]],
            "media_renditions": {"assets/editorial/cover.jpg": tiers},
        }

    def test_inline_delivery_ships_one_rendition_not_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, wide, small = self._layout(root)
            tiers = [{"file": wide.name, "path": "assets/renditions/" + wide.name,
                      "label": "w1200", "width": 1200, "height": 800, "bytes": 1},
                     {"file": small.name, "path": "assets/renditions/" + small.name,
                      "label": "w800", "width": 800, "height": 533, "bytes": 1}]
            adapted = spa_renderer._adapt_spa_dataset(
                self._dataset(tiers), media_delivery_mode="inline",
                assets_dir=root / "out" / "assets", max_inline_kb=400,
                run_asset_dir=root / "run" / "assets")
            blobs = adapted["asset_blobs"]
            self.assertEqual(len(blobs), 1, "单文件里同一槽位只应有一份图片字节")
            self.assertEqual(adapted["editorial_media"][0]["image"],
                             spa_renderer.ASSET_REF_PREFIX + _digest(wide))
            self.assertNotIn("media_renditions", adapted, "档位索引是构建期元数据，不该进读者的文件")
            self.assertNotIn("image", adapted, "根上不该留下 _attach_srcset 的临时键")

    def test_linked_delivery_publishes_the_real_srcset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._layout(root)
            tiers = [{"file": "cover--w1200.jpg", "path": "assets/renditions/cover--w1200.jpg",
                      "label": "w1200", "width": 1200, "height": 800, "bytes": 1},
                     {"file": "cover--w800.jpg", "path": "assets/renditions/cover--w800.jpg",
                      "label": "w800", "width": 800, "height": 533, "bytes": 1}]
            adapted = spa_renderer._adapt_spa_dataset(
                self._dataset(tiers), media_delivery_mode="linked",
                assets_dir=root / "out" / "assets", max_inline_kb=400,
                run_asset_dir=root / "run" / "assets")
            self.assertEqual(len(adapted["editorial_media"][0]["image_srcset"]), 2,
                             "外链交付才需要按端选择的多档 srcset")

    def test_missing_tier_file_is_a_build_failure_not_a_silent_single_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, wide, _small = self._layout(root)
            tiers = [{"file": "cover--gone.jpg", "path": "assets/renditions/cover--gone.jpg",
                      "label": "w1200", "width": 1200, "height": 800, "bytes": 1}]
            with self.assertRaises(ValueError) as ctx:
                spa_renderer._adapt_spa_dataset(
                    self._dataset(tiers), media_delivery_mode="inline",
                    assets_dir=root / "out" / "assets", max_inline_kb=400,
                    run_asset_dir=root / "run" / "assets")
            self.assertIn("IMG_TIER_UNDELIVERABLE", str(ctx.exception))


def _digest(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CoverageReconciliationTests(unittest.TestCase):
    """§5.4.5: the artifact may only ship pictures the manifest registered."""

    def test_unregistered_referenced_image_is_named(self):
        data = {"hero_image": "assets/editorial/cover.jpg",
                "editorial_media": [{"image": "assets/editorial/cover.jpg"},
                                    {"image": "assets/editorial/ghost.jpg"}],
                "section_media": []}
        manifest = {"assets": [{"local_file": "assets/editorial/cover.jpg",
                                "source_sha256": "a", "delivered_sha256": "b",
                                "renditions": []},
                               {"local_file": "assets/editorial/unused.jpg",
                                "source_sha256": "c", "delivered_sha256": "d",
                                "renditions": []}]}
        errors, metrics = local_media_gate.delivery_coverage_check(data, manifest)
        self.assertEqual(metrics["referenced_unregistered"], 1)
        self.assertTrue(any(e.startswith("IMG_UNREGISTERED_IN_MANIFEST") and "ghost.jpg" in e
                            for e in errors))
        self.assertEqual(metrics["manifest_unreferenced"], 1, "多收的图不得伪装成覆盖完成")

    def test_row_without_chain_is_named(self):
        data = {"hero_image": "assets/editorial/cover.jpg", "editorial_media": [],
                "section_media": []}
        manifest = {"assets": [{"local_file": "assets/editorial/cover.jpg", "sha256": "x"}]}
        errors, _ = local_media_gate.delivery_coverage_check(data, manifest)
        self.assertTrue(any(e.startswith("IMG_CHAIN_MISSING") for e in errors),
                        "有条目但无双跳摘要，等于交付字节没有可核对的上游凭据")


class DeliveredByteAttestationTests(unittest.TestCase):
    """A tier the manifest declared is attested; a picture it never declared is not."""

    def _html(self, blob: bytes) -> str:
        # DATA_URI_RE only accepts payloads of 64+ base64 characters, so the fixture bytes have to
        # be long enough to look like a picture rather than a token.
        uri = "data:image/jpeg;base64," + base64.b64encode(blob).decode("ascii")
        return "<html><script>%s</script></html>" % uri

    def test_declared_tier_digest_counts_as_attested(self):
        blob = b"tier-bytes-" * 24
        manifest = {"assets": [{"local_file": "assets/editorial/cover.jpg",
                                "sha256": "not-this", "source_sha256": "src",
                                "delivered_sha256": "not-this",
                                "renditions": [{"label": "w800", "sha256": _sha(blob)}]}]}
        errors, metrics = local_media_gate.attest_delivered_images(self._html(blob),
                                                                   manifest, Path("."))
        self.assertEqual(metrics["inline_attested"], 1)
        self.assertEqual(metrics["inline_unattested"], 0)
        self.assertFalse(any("IMG_DELIVERED_UNATTESTED" in e for e in errors))

    def test_tier_digest_of_an_unchained_entry_is_not_attested(self):
        blob = b"orphan-bytes-" * 24
        manifest = {"assets": [{"local_file": "assets/editorial/cover.jpg", "sha256": "other",
                                "renditions": [{"label": "w800", "sha256": _sha(blob)}]}]}
        errors, metrics = local_media_gate.attest_delivered_images(self._html(blob),
                                                                   manifest, Path("."))
        self.assertEqual(metrics["inline_unattested"], 1,
                         "没有双跳链的条目，其档位摘要不构成凭据")
        self.assertTrue(any(e.startswith("IMG_DELIVERED_UNATTESTED") for e in errors))


def _sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


class ProvenanceTierFileTests(unittest.TestCase):
    """§5.4.3: every declared rendition must exist on disk with the bytes it claims."""

    def test_missing_tier_file_is_reported(self):
        if Image is None:                                    # pragma: no cover
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivered = root / "assets" / "editorial" / "cover.jpg"
            blob = _jpeg(delivered, 1200, 800)
            manifest = {"assets": [{
                "local_file": "assets/editorial/cover.jpg", "sha256": _sha(blob),
                "source_sha256": _sha(blob), "delivered_sha256": _sha(blob),
                "delivered_width": 1200, "delivered_height": 800,
                "source_width": 1200, "source_height": 800,
                "renditions": [{"label": "w800", "file": "cover--w800.jpg",
                                "path": "assets/renditions/cover--w800.jpg",
                                "width": 800, "height": 533, "sha256": "deadbeef"}]}]}
            errors, metrics = local_media_gate.provenance_chain_check(manifest, root)
            self.assertEqual(metrics["tier_missing"], 1)
            self.assertTrue(any(e.startswith("IMG_TIER_FILE_MISSING") for e in errors))

    def test_tier_on_disk_with_wrong_bytes_is_reported(self):
        if Image is None:                                    # pragma: no cover
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivered = root / "assets" / "editorial" / "cover.jpg"
            blob = _jpeg(delivered, 1200, 800)
            tier = _jpeg(root / "assets" / "renditions" / "cover--w800.jpg", 800, 533)
            manifest = {"assets": [{
                "local_file": "assets/editorial/cover.jpg", "sha256": _sha(blob),
                "source_sha256": _sha(blob), "delivered_sha256": _sha(blob),
                "delivered_width": 1200, "delivered_height": 800,
                "renditions": [{"label": "w800", "file": "cover--w800.jpg",
                                "path": "assets/renditions/cover--w800.jpg",
                                "width": 800, "height": 533, "sha256": _sha(b"not-the-bytes")}]}]}
            errors, metrics = local_media_gate.provenance_chain_check(manifest, root)
            self.assertEqual(metrics["tier_hash_broken"], 1)
            self.assertTrue(any(e.startswith("IMG_TIER_HASH_BROKEN") for e in errors))
            del tier


if __name__ == "__main__":
    unittest.main(verbosity=2)
