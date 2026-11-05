# -*- coding: utf-8 -*-
"""v5.0.0 package integrity: the installable ZIP must carry its own seal."""
from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

import build_release_package as pkg


ROOT = Path(__file__).resolve().parents[1]


class V500ReleasePackageTests(unittest.TestCase):
    def test_open_source_license_and_media_notice_are_sealed(self):
        members = set(pkg.package_members(ROOT))
        self.assertIn("LICENSE", members)
        self.assertIn("THIRD_PARTY_NOTICES.md", members)
        notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        image = ROOT / "assets" / "themes" / "city-manhattan-ultra.jpg"
        image_sha1 = hashlib.sha1(image.read_bytes()).hexdigest()
        self.assertIn("CC0 1.0", notice)
        self.assertIn("commons.wikimedia.org/wiki/File:NYC_Manhattan_Skyline.JPG", notice)
        self.assertIn(image_sha1, notice)

    def test_public_source_has_no_developer_specific_absolute_paths(self):
        forbidden = (
            "C:" + "\\Users\\" + "Roy",
            "D:" + "\\文档\\项目开发\\" + "Travel-Scope",
        )
        offenders = []
        for rel in pkg.package_members(ROOT):
            path = ROOT / rel
            try:
                body = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(marker in body for marker in forbidden):
                offenders.append(rel)
        self.assertEqual(offenders, [], "public package exposes developer-specific paths")

    def test_member_authority_is_inventory_plus_origin(self):
        origin = json.loads((ROOT / "product-origin.json").read_text(encoding="utf-8"))
        members = pkg.package_members(ROOT)
        self.assertEqual(set(members), set(origin["inventory"]) | {"product-origin.json"})
        self.assertEqual(len(members), len(origin["inventory"]) + 1)

    def test_two_builds_are_byte_identical_and_self_verifying(self):
        with tempfile.TemporaryDirectory(prefix="v500_package_") as folder:
            first = Path(folder) / "a.zip"
            second = Path(folder) / "b.zip"
            one = pkg.build(first, ROOT)
            two = pkg.build(second, ROOT)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(one["sha256"], two["sha256"])
            self.assertEqual(pkg.verify_archive(first, ROOT)["status"], "PASS")

    def test_missing_origin_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="v500_missing_origin_") as folder:
            good = Path(folder) / "good.zip"
            bad = Path(folder) / "bad.zip"
            pkg.build(good, ROOT)
            with zipfile.ZipFile(good, "r") as source, zipfile.ZipFile(bad, "w") as target:
                for info in source.infolist():
                    if info.filename.endswith("/product-origin.json"):
                        continue
                    target.writestr(info, source.read(info.filename))
            with self.assertRaisesRegex(pkg.PackageError, "member set"):
                pkg.verify_archive(bad, ROOT)

    def test_extra_file_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="v500_extra_") as folder:
            good = Path(folder) / "good.zip"
            bad = Path(folder) / "bad.zip"
            pkg.build(good, ROOT)
            with zipfile.ZipFile(good, "r") as source, zipfile.ZipFile(bad, "w") as target:
                for info in source.infolist():
                    target.writestr(info, source.read(info.filename))
                target.writestr("travel-scope/.temp/extra.txt", b"bad")
            with self.assertRaisesRegex(pkg.PackageError, "member set"):
                pkg.verify_archive(bad, ROOT)


if __name__ == "__main__":
    unittest.main()
