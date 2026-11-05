# -*- coding: utf-8 -*-
"""v4.2.2 R3 步③：三段行级血缘门的执行型牙齿（业主 2026-11-03 第二轮裁示点名的六条负测）。

业主裁示一的原话是判据的出处：

  「不接受当前 identity_plus_local_digest 作为发布级来源证明……它证明了两件独立的事实，
   但没证明最关键的桥梁：本地这串字节确实来自该 Commons 文件的某个具体修订。」
  「不能按 source_file_title 把多条资产折叠成一个 declared 对象……现在 Twin Peaks 的三行里，
   酒店行的错误被标题级汇总掩盖，intra_manifest_consistent=false 不足以替代逐行阻断。」

因此这里每条负测都要求「被点名的那一行」和「被点名的那个码」同时出现——被别的码拦下＝不算证。
约定：本文件不写发布树产物，全部落临时目录；核验路径必须一次网络都不发（最后一条用真断开的
socket 证明，不是靠读源码字符串）。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import socket
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import local_media_gate as lmg        # noqa: E402
import prepare_media as pm            # noqa: E402
from PIL import Image                  # noqa: E402

# 2026-11-04 现场从正式 run 的 asset-manifest.json 读出的 7 条坏值（不是手打）；
# 生成器 .temp/v422_honest_map/ZH_RELEASE_3/tools/add_r3e_url_teeth.py 把它们内嵌进来，
# 修复账见 R3E_SOURCE_URL_FIX_applied.json。发布树测试不许依赖 .temp，
# 所以值进文件本身，.temp 路径只当出处写在注释里。
R3E_BAD_SOURCE_URL_SAMPLES = [
 {
  "row": "assets/section/monterey_hotels.jpg",
  "declared": "https://upload.wikimedia.org/wikipedia/commons/9/95/Cannery_Row%2C_Monterey_5_2017-11-21.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "authority": "https://upload.wikimedia.org/wikipedia/commons/9/95/Cannery_Row%2C_Monterey_5_2017-11-21.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "page": "https://commons.wikimedia.org/wiki/File:Cannery_Row,_Monterey_5_2017-11-21.jpg"
 },
 {
  "row": "assets/section/monterey_food.jpg",
  "declared": "https://upload.wikimedia.org/wikipedia/commons/0/0d/Cannery_Row%2C_Monterey_4_2017-11-21.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "authority": "https://upload.wikimedia.org/wikipedia/commons/0/0d/Cannery_Row%2C_Monterey_4_2017-11-21.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "page": "https://commons.wikimedia.org/wiki/File:Cannery_Row,_Monterey_4_2017-11-21.jpg"
 },
 {
  "row": "assets/section/big_sur_cafes.jpg",
  "declared": "https://upload.wikimedia.org/wikipedia/commons/d/d5/The_Big_Sur_Roadhouse.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "authority": "https://upload.wikimedia.org/wikipedia/commons/d/d5/The_Big_Sur_Roadhouse.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "page": "https://commons.wikimedia.org/wiki/File:The_Big_Sur_Roadhouse.jpg"
 },
 {
  "row": "assets/section/big_sur_sights.jpg",
  "declared": "https://upload.wikimedia.org/wikipedia/commons/6/68/McWay_Falls_Big_Sur_May_2011_001.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "authority": "https://upload.wikimedia.org/wikipedia/commons/6/68/McWay_Falls_Big_Sur_May_2011_001.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "page": "https://commons.wikimedia.org/wiki/File:McWay_Falls_Big_Sur_May_2011_001.jpg"
 },
 {
  "row": "assets/section/santa_barbara_hotels.jpg",
  "declared": "https://upload.wikimedia.org/wikipedia/commons/3/39/Hotel_Santa_Barbara%2C_State_Street_and_Cota_Street%2C_Santa_Barbara%2C_CA_%2853925929967%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "authority": "https://upload.wikimedia.org/wikipedia/commons/3/39/Hotel_Santa_Barbara%2C_State_Street_and_Cota_Street%2C_Santa_Barbara%2C_CA_%2853925929967%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "page": "https://commons.wikimedia.org/wiki/File:Hotel_Santa_Barbara,_State_Street_and_Cota_Street,_Santa_Barbara,_CA_(53925929967).jpg"
 },
 {
  "row": "assets/section/santa_barbara_food.jpg",
  "declared": "https://upload.wikimedia.org/wikipedia/commons/9/9d/Lower_State%2C_Santa_Barbara%2C_CA_-_panoramio_%2821%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "authority": "https://upload.wikimedia.org/wikipedia/commons/9/9d/Lower_State%2C_Santa_Barbara%2C_CA_-_panoramio_%2821%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "page": "https://commons.wikimedia.org/wiki/File:Lower_State,_Santa_Barbara,_CA_-_panoramio_(21).jpg"
 },
 {
  "row": "assets/editorial/la_grand_central_market.jpg",
  "declared": "https://upload.wikimedia.org/wikipedia/commons/8/80/Grand_Central_Market%2C_Los_Angeles.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "authority": "https://upload.wikimedia.org/wikipedia/commons/8/80/Grand_Central_Market%2C_Los_Angeles.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
  "page": "https://commons.wikimedia.org/wiki/File:Grand_Central_Market,_Los_Angeles.jpg"
 }
]

TITLE = "File:San Francisco Panorama from Twin Peaks 2013.jpg"
PAGE_URL = "https://commons.wikimedia.org/wiki/File:San_Francisco_Panorama_from_Twin_Peaks_2013.jpg"
ORIGINAL_URL = ("https://upload.wikimedia.org/wikipedia/commons/c/ce/"
                "San_Francisco_Panorama_from_Twin_Peaks_2013.jpg")
PAGE_ID = 29729584
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"


def write_jpeg(path: Path, width: int, height: int, seed: int = 7, quality: int = 92) -> bytes:
    """造一张有真实纹理的图；返回字节是为了让「同一份字节」在测试里可显式复算。"""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(0, width, 3):
            pixels[x, y] = ((x * seed + y) % 256, (y * 3 + x) % 256, (x + y + seed) % 251)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=quality, subsampling=0)
    return path.read_bytes()


def reencode(blob: bytes, width: int, height: int, seed: int = 3) -> bytes:
    """同尺寸但不同字节：派生链摘要必须把它读成「不是那一串」，而不是读成「差不多」。"""
    handle = io.BytesIO()
    with Image.open(io.BytesIO(blob)) as image:
        image.convert("RGB").resize((width, height)).save(handle, format="JPEG", quality=60 + seed,
                                                           subsampling=0)
    return handle.getvalue()


class LineageFixture:
    """一棵最小 run：两行共用同一张 Commons 图（Twin Peaks 的形状），各自有独立血缘。"""

    def __init__(self, tmp: Path):
        self.root = tmp
        self.policy = lmg.source_snapshot_policy()
        rows = []
        # 两行各自的采集宽度不同：Commons 的缩略档是按宽度出字节的，同一张图同一宽度只会有一份字节，
        # 所以「同标题同宽度却两串 prepared」本身就是 Twin Peaks 三条复用行的真实缺陷（桥梁至多成立一条）。
        for name, rel, slot, role, category, seed, size in (
                ("tp_hero.jpg", "assets/editorial/tp_hero.jpg", "hero", "route_hero", "EDITORIAL", 7, (800, 600)),
                ("tp_hotels.jpg", "assets/section/tp_hotels.jpg", "destination_atmosphere",
                 "destination_atmosphere", "SECTION", 11, (760, 570))):
            rows.append(self._row(name, rel, slot, role, category, seed, size))
        self.manifest = {"schema_version": 1, "assets": rows}
        self.manifest_bytes = (json.dumps(self.manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        (self.root / "asset-manifest.json").write_bytes(self.manifest_bytes)
        # 三张面孔（R3E）：真实 run 就是这个形状——outputs 由构建投影、media_prepared 由派生复制，
        # 两格都从根清单取值。夹具不给这两份，面孔核对就只在测试里「缺件跳过」，等于没验。
        (self.root / "outputs").mkdir(parents=True, exist_ok=True)
        (self.root / "outputs" / "asset-manifest.json").write_bytes(self.manifest_bytes)
        # R3F（业主 2026-11-04 第 6／7 条）：链条面孔必须带 run 相对的 entries[].source 与
        # entries[].renditions[].relpath，并且交付档真的要落在登记点名的位置。夹具不给这两格，
        # 路径门就只在测试里「扫空」——扫空不等于通过，等于没验。
        entries = []
        for r in rows:
            name = Path(r["local_file"]).name
            tier_rows = []
            for tier in r["renditions"]:
                file_name = Path(str(tier["relpath"])).name
                dest = self.root / "assets" / "renditions" / file_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(Path(str(tier["relpath"])).read_bytes())
                tier_rows.append({"label": tier["label"], "width": tier["width"],
                                  "height": tier["height"], "bytes": tier["bytes"],
                                  "relpath": "assets/renditions/%s" % file_name,
                                  "delivered_sha256": tier["delivered_sha256"]})
            entries.append({"local_file": r["local_file"], "slot": r["slot"],
                            "source_asset_url": r["source_asset_url"],
                            "source": "media_prepared/originals/%s" % name,
                            "source_sha256": r["source_sha256"],
                            "declared_sha256": r["source_sha256"],
                            "renditions": tier_rows})
        chain = {"status": "PASS", "assets": len(rows), "entries": entries}
        (self.root / "media_prepared").mkdir(parents=True, exist_ok=True)
        self.chain_bytes = (json.dumps(chain, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        (self.root / "media_prepared" / "media-manifest.json").write_bytes(self.chain_bytes)
        # run 自己的输入声明也进夹具：这一格的四个字段是构建／交付门取文件的地方，
        # 夹具没有它，「run 相对＋落在 run 内」就只测了链条面一张孔。
        (self.root / "evidence").mkdir(parents=True, exist_ok=True)
        (self.root / "evidence" / "cross_source_review.json").write_bytes(
            b'{"rows": []}\n')
        (self.root / "scope.json").write_bytes(b'{"selected_destinations": [{"id": "tp"}]}\n')
        (self.root / "route_corridors.json").write_bytes(b'{"corridors": []}\n')
        self.run_manifest = {"run_id": "lineage_fixture",
                             "source_evidence_path": "evidence/cross_source_review.json",
                             "scope_path": "scope.json",
                             "route_corridors_path": "route_corridors.json",
                             "asset_manifest_path": "asset-manifest.json",
                             "source_verification_snapshot_path": "evidence/media-source-snapshot.json"}
        self.run_manifest_bytes = (json.dumps(self.run_manifest, ensure_ascii=False, indent=1)
                                   + "\n").encode("utf-8")
        (self.root / "manifest.json").write_bytes(self.run_manifest_bytes)
        # 声明了就必须在盘上：source_verification_snapshot_path 指向的这份先落一个占位，
        # validate() 每次用真正要判的那份覆盖它（门判的是「这一格指的文件在不在 run 内」）。
        self.snapshot_path = self.root / "evidence" / "media-source-snapshot.json"
        self.snapshot_path.write_bytes(b'{"placeholder": true}\n')

    def _row(self, name, rel, slot, role, category, seed, size):
        prepared = self.root / "media_prepared" / "originals" / name
        blob = write_jpeg(prepared, size[0], size[1], seed=seed)
        report = pm.prepare_asset(prepared, self.root / "prepared_out", slot=slot)
        primary = pm.primary_rendition(report["renditions"])
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(primary["relpath"]).read_bytes())
        return {"local_file": rel, "category": category, "display_role": role, "slot": report["slot"],
                "source_provider": "wikimedia_commons", "source_file_title": TITLE,
                "source_page_id": PAGE_ID, "source_page": PAGE_URL, "source_asset_url": ORIGINAL_URL,
                "author": "Tuxyso", "license": "CC BY-SA 3.0", "license_url": LICENSE_URL,
                "source_sha256": hashlib.sha256(blob).hexdigest(),
                "source_width": report["source_width"], "source_height": report["source_height"],
                "delivered_sha256": primary["delivered_sha256"],
                "delivered_width": primary["width"], "delivered_height": primary["height"],
                "transform": primary["transform"], "sha256": primary["delivered_sha256"],
                "renditions": [primary]}

    def row(self, index: int) -> dict:
        return self.manifest["assets"][index]

    def record(self, index: int, **overrides) -> dict:
        entry = self.row(index)
        prepared = self.root / "media_prepared" / "originals" / Path(entry["local_file"]).name
        record = {"asset_row_id": entry["local_file"], "status": "CURRENT_REVISION_RECOLLECTED",
                  "source_file_title": TITLE, "source_page_id": PAGE_ID, "source_page_url": PAGE_URL,
                  "original_url": ORIGINAL_URL, "revision_id": 1174790454,
                  "revision_timestamp": "2026-03-02T18:52:01Z",
                  "original_sha1": "acafd015ca3e0f112dedb98f0aea462b7da645aa",
                  "original_width": 26069, "original_height": 3038,
                  "author": entry["author"], "license_short_name": entry["license"],
                  "license_url": LICENSE_URL,
                  "acquisition_url": "%s/thumb/c/ce/%s/%dpx-%s" % (
                      ORIGINAL_URL.rsplit("/", 2)[0], Path(entry["local_file"]).stem,
                      int(entry["source_width"]), Path(entry["local_file"]).stem),
                  "requested_width": int(entry["source_width"]),
                  "returned_width": int(entry["source_width"]),
                  "returned_height": int(entry["source_height"]),
                  "acquisition_sha256": hashlib.sha256(prepared.read_bytes()).hexdigest(),
                  "retrieved_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "transform_recipe": lmg.BRIDGE_RECIPE_NONCE,
                  "prepared_sha256": hashlib.sha256(prepared.read_bytes()).hexdigest(),
                  "delivered_sha256": entry["delivered_sha256"],
                  "producer_version": self.policy["producer_version"]}
        record.update(overrides)
        return record

    def snapshot(self, records, **overrides) -> dict:
        snapshot = {"schema_version": str(self.policy["schema_version_supported"]),
                    "producer": "scripts/local_media_gate.py::build_source_verification_snapshot",
                    "producer_version": self.policy["producer_version"],
                    "verified_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "api_endpoint": self.policy["api_endpoint"], "batch_size": self.policy["batch_size"],
                    "user_agent": self.policy["user_agent"],
                    "asset_manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest().upper(),
                    "records_expected": len(records), "records": records,
                    "status": self.policy["complete_status_value"]}
        snapshot.update(overrides)
        snapshot["snapshot_sha256"] = lmg.snapshot_canonical_digest(snapshot)
        return snapshot

    def validate(self, snapshot):
        # 判之前把这份快照落到它自己声明的位置：run 相对路径的面板上，
        # 「声明的路径有实物」与「只有内存里有」是两件事（业主 R3F 第 4 条最后一项）。
        self.snapshot_path.write_bytes((json.dumps(snapshot, ensure_ascii=False, indent=1)
                                        + "\n").encode("utf-8"))
        return lmg.validate_source_identities(self.manifest, base_dir=self.root, snapshot=snapshot,
                                              manifest_bytes=self.manifest_bytes, as_of=date.today())

    def good_records(self):
        """两条各自完整、各自接得上的血缘——正对照与负测的公共底。"""
        return [self.record(0), self.record(1)]

    @staticmethod
    def codes_of(exc: ValueError) -> list:
        return [piece.split("|")[0] for piece in str(exc).split("; ")]


class MediaLineageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="media_lineage_test_")
        self.fx = LineageFixture(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def good_records(self):
        return self.fx.good_records()

    # ---- 正对照：三段齐全时门必须是绿的，否则下面的负测只是在演                                  ----
    def test_positive_control_three_sections_pass(self):
        summary = self.fx.validate(self.fx.snapshot(self.good_records()))
        self.assertEqual(summary["commons_asset_rows"], 2)
        self.assertEqual(summary["lineage_bridges_recomputed"], 2)
        self.assertEqual(summary["lineage_chains_replayed"], 2)
        self.assertEqual(summary["network_calls_performed"], 0)
        self.assertEqual(summary["lineage_aggregation_basis"], "asset_row_id")

    # ---- 业主点名 1：同标题不同作者 ⇒ 只准点那一行，别把另一行一起判死，也不许被盖掉            ----
    def test_same_title_different_author_blocks_that_row_only(self):
        fx = self.fx
        fx.row(1)["author"] = "Bernard Gagnon"          # 清单信用行写错，快照记的是 Commons 现值
        fx.manifest_bytes = (json.dumps(fx.manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        (fx.root / "asset-manifest.json").write_bytes(fx.manifest_bytes)
        records = [fx.record(0), fx.record(1, author="Tuxyso")]   # 血缘按现取的那一版记
        with self.assertRaises(ValueError) as caught:
            fx.validate(fx.snapshot(records))
        text = str(caught.exception)
        self.assertIn("MEDIA_SNAPSHOT_IDENTITY_MISMATCH", text)
        self.assertIn("assets/section/tp_hotels.jpg", text, "身份不符必须点到行，不能只报标题")
        self.assertNotIn("assets/editorial/tp_hero.jpg", text,
                         "同标题的另一行没做错，被一起判死＝标题级汇总还没被拆掉")

    # ---- 业主点名 2：同标题不同源路径 ⇒ 行级身份不符                                            ----
    def test_same_title_different_source_path_blocks_that_row(self):
        fx = self.fx
        fx.row(1)["source_asset_url"] = ORIGINAL_URL.replace("/c/ce/", "/4/4e/")
        fx.manifest_bytes = (json.dumps(fx.manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        snapshot = fx.snapshot(fx.good_records())
        with self.assertRaises(ValueError) as caught:
            fx.validate(snapshot)
        text = str(caught.exception)
        self.assertIn("MEDIA_SNAPSHOT_IDENTITY_MISMATCH", text)
        self.assertIn("tp_hotels", text)
        self.assertNotIn("tp_hero.jpg", text)

    # ---- 业主点名 3：pageid 正确但本地字节没有采集桥梁                                          ----
    def test_pageid_right_but_no_acquisition_bridge_blocks(self):
        records = self.good_records()
        records[1]["acquisition_sha256"] = hashlib.sha256(b"some other bytes").hexdigest()
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(records))
        text = str(caught.exception)
        self.assertIn("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING", text,
                      "身份全对但采集字节接不上 prepared ⇒ 只能报这条码，报别的等于没测到桥梁")
        self.assertIn("tp_hotels", text)

    def test_other_bridge_recipe_is_not_allowed(self):
        records = self.good_records()
        records[0]["transform_recipe"] = "DOWNLOADED_ORIGINAL_THEN_RESIZED"
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(records))
        self.assertIn("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING", str(caught.exception))

    # ---- 业主点名 4：revision 正确但派生摘要不符                                                ----
    def test_revision_right_but_derived_digest_mismatch_blocks(self):
        records = self.good_records()
        records[1]["delivered_sha256"] = hashlib.sha256(b"other delivered").hexdigest()
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(records))
        self.assertIn("MEDIA_LINEAGE_DELIVERED_DIGEST_MISMATCH", str(caught.exception))

    def test_delivered_bytes_not_reproducible_from_prepared_breaks_chain(self):
        fx = self.fx
        entry = fx.row(0)
        # 交付字节换成一串「同尺寸、不同来源」的图：摘要与清单声明一起改掉，身份面却全对。
        blob = reencode((fx.root / entry["local_file"]).read_bytes(), entry["delivered_width"],
                        entry["delivered_height"])
        digest = hashlib.sha256(blob).hexdigest()
        (fx.root / entry["local_file"]).write_bytes(blob)
        entry["delivered_sha256"] = digest
        entry["sha256"] = digest
        for tier in entry["renditions"]:
            tier["delivered_sha256"] = digest
            tier["sha256"] = digest
        fx.manifest_bytes = (json.dumps(fx.manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        (fx.root / "asset-manifest.json").write_bytes(fx.manifest_bytes)
        records = fx.good_records()
        records[0]["delivered_sha256"] = digest
        with self.assertRaises(ValueError) as caught:
            fx.validate(fx.snapshot(records))
        self.assertIn("MEDIA_LINEAGE_DERIVATION_CHAIN_BROKEN", str(caught.exception),
                      "从 prepared 重放不出交付字节＝这一行没有派生链，身份再对也不是来源证明")

    # ---- 业主点名 5：一条不符时不生成可用 COMPLETE 快照（生产者整体拒绝）                        ----
    def test_producer_writes_nothing_when_a_row_fails(self):
        with self.assertRaises(ValueError) as caught:
            self._run_producer(bind_row_indices=(0,))
        text = str(caught.exception)
        self.assertIn("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING", text)
        self.assertIn("assets/section/tp_hotels.jpg", text)
        self.assertIn("本趟 1/2 行通过", text,
                      "整体拒绝时要说清「几行通过／共几行」——上一版把通过数写成没通过数，读的人方向都反了")
        self.assertNotIn("status', 'COMPLETE", text)

    def test_producer_returns_complete_snapshot_when_all_rows_bind(self):
        snapshot = self._run_producer(bind_row_indices=(0, 1))
        self.assertEqual(snapshot["status"], self.fx.policy["complete_status_value"])
        self.assertEqual(snapshot["records_expected"], 2)
        self.assertEqual([row["asset_row_id"] for row in snapshot["records"]],
                         ["assets/editorial/tp_hero.jpg", "assets/section/tp_hotels.jpg"])
        self.assertEqual({row["status"] for row in snapshot["records"]}, {"CURRENT_REVISION_RECOLLECTED"})
        self.assertEqual(lmg.snapshot_canonical_digest(snapshot), snapshot["snapshot_sha256"])

    def _run_producer(self, bind_row_indices):
        """用假 requests 跑真生产者函数：延迟导入正好让「构建期不联网」这件事可测。"""
        served_by_width = {}
        for index, entry in enumerate(self.fx.manifest["assets"]):
            prepared = self.fx.root / "media_prepared" / "originals" / Path(entry["local_file"]).name
            width = int(entry["source_width"])
            served_by_width[width] = (prepared.read_bytes() if index in bind_row_indices else
                                      reencode(prepared.read_bytes(), width,
                                               int(entry["source_height"]), seed=5))
        pages = {str(PAGE_ID): {"pageid": PAGE_ID, "title": TITLE,
                                "imageinfo": [{"url": ORIGINAL_URL, "descriptionurl": PAGE_URL,
                                               "timestamp": "2013-11-20T21:57:56Z", "width": 26069,
                                               "height": 3038, "mime": "image/jpeg",
                                               "sha1": "acafd015ca3e0f112dedb98f0aea462b7da645aa",
                                               "extmetadata": {"Artist": {"value": "Tuxyso"},
                                                               "LicenseShortName": {"value": "CC BY-SA 3.0"},
                                                               "LicenseUrl": {"value": LICENSE_URL}}}]}}
        revisions = {str(PAGE_ID): {"pageid": PAGE_ID, "title": TITLE,
                                    "revisions": [{"revid": 1174790454,
                                                   "timestamp": "2026-03-02T18:52:01Z",
                                                   "user": "Rkieferbot"}]}}

        class Resp:
            """假响应要像 requests.Response：生产者按 status_code／headers 分诊（200 才解析、
            429 走限流码、非 2xx 走 HTTP 码）。测试替调用方改接口＝把牙磨平，所以这里补齐字段。"""

            def __init__(self, payload=None, content=b"", status_code=200, headers=None):
                self._payload, self.content = payload, content
                self.status_code = status_code
                self.headers = dict(headers or {})
                self.text = ""

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.headers = {}

            def get(self, url, params=None, timeout=None):
                if params and params.get("prop") == "imageinfo" and "iiurlwidth" in params:
                    width = int(params["iiurlwidth"])
                    return Resp({"query": {"pages": {str(PAGE_ID): dict(
                        pages[str(PAGE_ID)],
                        imageinfo=[dict(pages[str(PAGE_ID)]["imageinfo"][0],
                                        thumburl="%s/thumb/c/ce/x/%dpx-x.jpg" % (ORIGINAL_URL.rsplit("/", 2)[0], width),
                                        thumbwidth=width, thumbheight=600)])}}})
                if params and params.get("prop") == "revisions":
                    return Resp({"query": {"pages": revisions}})
                if params:
                    return Resp({"query": {"pages": pages}})
                token = re.search(r"/(\d+)px-", url)
                if not token or int(token.group(1)) not in served_by_width:
                    raise AssertionError("生产者请求了没登记的字节：%s" % url)
                return Resp(content=served_by_width[int(token.group(1))])

        fake_module = type(sys)("requests")
        fake_module.Session = FakeSession
        original_sleep = time.sleep
        time.sleep = lambda *_a, **_k: None            # 节流是登记值，测试不为此花真时间
        sys.modules["requests"] = fake_module
        try:
            return lmg.build_source_verification_snapshot(
                self.fx.manifest, base_dir=self.fx.root, manifest_bytes=self.fx.manifest_bytes)
        finally:
            time.sleep = original_sleep
            sys.modules.pop("requests", None)

    # ---- 业主点名 6：标题聚合不得掩盖行级冲突                                                   ----
    def test_title_aggregated_snapshot_is_rejected(self):
        aggregated = [self.fx.record(0)]                # 两行只记一条账：按标题折叠
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(aggregated))
        text = str(caught.exception)
        codes = self.fx.codes_of(caught.exception)
        self.assertIn("MEDIA_LINEAGE_TITLE_AGGREGATION_FORBIDDEN", codes,
                      "同标题两行折成一条 ⇒ 必须由这条码点名，而不是笼统一句记录数不对")
        self.assertIn("MEDIA_SNAPSHOT_ASSET_MISSING", codes)
        self.assertIn("assets/section/tp_hotels.jpg", text)

    def test_record_keyed_by_title_has_no_row_anchor(self):
        records = self.good_records()
        records[1]["asset_row_id"] = TITLE              # 退回标题级键
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(records))
        codes = self.fx.codes_of(caught.exception)
        self.assertIn("MEDIA_SNAPSHOT_ROW_KEY_UNAVAILABLE", codes)

    def test_duplicate_row_anchor_blocks(self):
        fx = self.fx
        clone = json.loads(json.dumps(fx.row(0)))
        fx.manifest["assets"].append(clone)             # 同 local_file 第二行
        fx.manifest_bytes = (json.dumps(fx.manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        (fx.root / "asset-manifest.json").write_bytes(fx.manifest_bytes)
        with self.assertRaises(ValueError) as caught:
            fx.validate(fx.snapshot(fx.good_records()))
        self.assertIn("MEDIA_SNAPSHOT_ROW_KEY_UNAVAILABLE", str(caught.exception))

    # ---- 状态闭集：三种状态各自的阻断                                                            ----
    def test_unbound_legacy_row_blocks(self):
        records = self.good_records()
        records[1].update({"status": "UNBOUND_LEGACY", "acquisition_sha256": "", "acquisition_url": ""})
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(records))
        text = str(caught.exception)
        self.assertIn("MEDIA_LINEAGE_ROW_UNBOUND", text)
        self.assertIn("tp_hotels", text)

    def test_unregistered_status_blocks(self):
        records = self.good_records()
        records[0]["status"] = "VERIFIED_ENOUGH"
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(records))
        self.assertIn("MEDIA_LINEAGE_STATUS_UNREGISTERED", str(caught.exception))

    def test_historical_bound_claim_blocked_while_path_unmeasured(self):
        self.assertFalse(self.fx.policy["historical_revision_addressing_verified"],
                         "登记面说这条路没量通，本测试才成立")
        records = self.good_records()
        records[0]["status"] = "EXACT_HISTORICAL_REVISION_BOUND"
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(records))
        self.assertIn("MEDIA_LINEAGE_HISTORICAL_BOUND_NOT_PROVABLE", str(caught.exception))

    def test_missing_section_field_blocks(self):
        records = self.good_records()
        records[0]["revision_timestamp"] = ""
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(records))
        codes = self.fx.codes_of(caught.exception)
        self.assertTrue({"MEDIA_LINEAGE_SECTION_FIELD_MISSING", "MEDIA_LINEAGE_REVISION_IDENTITY_MISSING"}
                        & set(codes), "三段任一段缺件都要有名字：%s" % codes)
        self.assertIn("MEDIA_LINEAGE_SECTION_FIELD_MISSING", codes)

    # ---- 裁 A 的四条硬规则仍然咬得住：缺快照／过期／手改／半份                                   ----
    def test_missing_snapshot_is_not_a_fallback_to_online(self):
        """两种「没有快照」要各有名字：run 没声明，和声明了但 run 内没有实物。

        夹具今天带 manifest.json 的输入声明（R3F 要判那一格），所以「没声明」得现场把那一格摘掉，
        而不是假装夹具从来不长这样——「声明了却指向不在的东西」正是换机断链的形状，单独一条码。
        """
        undeclared = dict(self.fx.run_manifest)
        undeclared.pop("source_verification_snapshot_path")
        (self.fx.root / "manifest.json").write_bytes(
            (json.dumps(undeclared, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        with self.assertRaises(ValueError) as caught:
            lmg.validate_source_identities(self.fx.manifest, base_dir=self.fx.root,
                                           manifest_bytes=self.fx.manifest_bytes, as_of=date.today())
        self.assertIn("MEDIA_SNAPSHOT_PATH_UNDECLARED", str(caught.exception))
        (self.fx.root / "manifest.json").write_bytes(self.fx.run_manifest_bytes)
        self.fx.snapshot_path.unlink()
        with self.assertRaises(ValueError) as caught2:
            lmg.validate_source_identities(self.fx.manifest, base_dir=self.fx.root,
                                           manifest_bytes=self.fx.manifest_bytes, as_of=date.today())
        self.assertIn("MEDIA_SNAPSHOT_MISSING", str(caught2.exception))

    def test_expired_snapshot_blocks(self):
        old = datetime(2026, 1, 1, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        snapshot = self.fx.snapshot(self.good_records(), verified_at_utc=old)
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(snapshot)
        self.assertIn("MEDIA_SNAPSHOT_EXPIRED", str(caught.exception))

    def test_hand_edited_snapshot_blocks(self):
        snapshot = self.fx.snapshot(self.good_records())
        snapshot["records"][0]["author"] = "Somebody Else"
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(snapshot)
        self.assertIn("MEDIA_SNAPSHOT_SELF_DIGEST_MISMATCH", str(caught.exception))

    def test_not_complete_status_blocks(self):
        snapshot = self.fx.snapshot(self.good_records()[:1], records_expected=1, status="PARTIAL")
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(snapshot)
        self.assertIn("MEDIA_SNAPSHOT_NOT_COMPLETE", str(caught.exception))

    def test_old_producer_version_is_not_readable_as_new_contract(self):
        snapshot = self.fx.snapshot(self.good_records(), producer_version="4.2.2-r3-snapshot-1")
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(snapshot)
        self.assertIn("MEDIA_SNAPSHOT_SCHEMA_UNSUPPORTED", str(caught.exception),
                      "旧口径（identity_plus_local_digest）的件不能靠形状相同混进新合同")

    # ---- 「构建期不发网络请求」不能用源码扫描证明：这里真把 socket 断了再跑一遍                  ----
    def test_validator_runs_with_network_cut(self):
        def refuse(*_args, **_kwargs):
            raise AssertionError("核验路径试图联网 ⇒ 业主裁 A 被违反")

        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse):
            summary = self.fx.validate(self.fx.snapshot(self.good_records()))
        self.assertEqual(summary["lineage_chains_replayed"], 2)

    def test_registry_and_code_blocking_codes_are_two_way_closed(self):
        policy = lmg.source_snapshot_policy()
        self.assertEqual(set(policy["blocking_codes"]), set(lmg.SNAPSHOT_BLOCKING_CODES),
                         "登记了代码发不出的码＝给将来留假证据；代码发了没登记的码＝读者查不到这句话是谁说的")

    def test_lineage_field_lists_have_one_holder(self):
        policy = lmg.source_snapshot_policy()
        self.assertNotIn("identity_fields", policy)
        self.assertNotIn("digest_fields", policy)
        sections = policy["lineage_sections"]
        self.assertEqual(sorted(sections), ["actual_acquisition_bytes", "commons_revision_identity",
                                            "local_derivation_chain"])
        union = {f for fields in sections.values() for f in fields}
        self.assertTrue(union <= set(policy["record_fields_required"]))

    def test_gate_module_does_not_import_requests_at_top_level(self):
        source = (SCRIPTS / "local_media_gate.py").read_text(encoding="utf-8")
        head = source.split("def build_source_verification_snapshot", 1)[0]
        self.assertNotIn("import requests", head,
                         "顶层导入 requests 会让「顺手回源」在生成期成为可能")


class FakeResponse:
    """像 requests.Response 的假件：status_code／headers／json 三个面都要能演「远端答不好」的样子。"""

    def __init__(self, payload=None, content=b"", status_code=200, headers=None, bad_json=False):
        self._payload, self.content = payload, content
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.bad_json = bad_json
        self.text = "" if payload is None else "not-json-body"

    def json(self):
        if self.bad_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)


class SourceFetchTests(unittest.TestCase):
    """R3D 裁示 1 的牙齿：三条来源码各被自己点名的码拦下，尝试次数与等待预算只从登记面读。

    「被别的码拦下＝不算证」这条规矩在这里同样成立：限流不许写成 MEDIA_SNAPSHOT_UNREADABLE
    （那是本地快照读不成），裸抛 requests 异常也不许算过——归因写错，事后没人知道那天是 Commons 没答。
    """

    POLICY = lmg.source_snapshot_policy()

    def setUp(self):
        self.waits = []
        self.now_value = [0.0]

    def _sleep(self, seconds):
        self.waits.append(float(seconds))
        self.now_value[0] += float(seconds)

    def _now(self):
        return self.now_value[0]

    def _policy_with(self, **overrides):
        block = json.loads(json.dumps(self.POLICY))     # 独立副本：改的是内存里的登记表，不碰盘上登记面
        block["source_fetch_policy"].update(overrides)
        return block

    def _session(self, outcomes):
        class ScriptedSession:
            def __init__(self):
                self.calls = 0

            def get(self, url, params=None, timeout=None):
                self.calls += 1
                outcome = outcomes[min(self.calls, len(outcomes)) - 1]
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome
        return ScriptedSession()

    def _run(self, outcomes, kind="json", **overrides):
        session = self._session(outcomes)
        value, error = lmg._source_request(session, "https://example.test/api", {"a": 1},
                                           self._policy_with(**overrides), kind=kind,
                                           sleep=self._sleep, now=self._now)
        return value, error, session

    def test_rate_limited_gets_its_own_code(self):
        budget = int(self.POLICY["source_fetch_policy"]["max_total_wait_seconds"])
        attempts = int(self.POLICY["source_fetch_policy"]["max_attempts"])
        _value, error, session = self._run([FakeResponse(status_code=429, headers={"Retry-After": "10"})] * 9)
        self.assertIn("MEDIA_SOURCE_RATE_LIMITED", error)
        self.assertNotIn("MEDIA_SNAPSHOT_UNREADABLE", error, "限流是远端答不好，不许写成「本地快照坏了」")
        self.assertEqual(session.calls, attempts, "尝试次数必须停在登记值")
        self.assertEqual(len(self.waits), attempts - 1)
        self.assertLessEqual(sum(self.waits), budget, "累计等待不许越过登记预算")

    def test_retry_after_is_capped_by_remaining_budget(self):
        # 对端开 10 秒，预算只剩 15 秒：第二次等待必须被钳成剩余量，而不是无限照听。
        _value, error, _session = self._run([FakeResponse(status_code=429,
                                                          headers={"Retry-After": "10"})] * 9,
                                            max_total_wait_seconds=15)
        self.assertIn("MEDIA_SOURCE_RATE_LIMITED", error)
        self.assertEqual(self.waits, [10.0, 5.0])
        self.assertLessEqual(sum(self.waits), 15)

    def test_http_error_gets_its_own_code(self):
        attempts = int(self.POLICY["source_fetch_policy"]["max_attempts"])
        _value, error, session = self._run([FakeResponse(status_code=500)] * 9)
        self.assertIn("MEDIA_SOURCE_HTTP_ERROR", error)
        self.assertNotIn("RATE_LIMITED", error)
        self.assertEqual(session.calls, attempts)

    def test_unreadable_body_gets_its_own_code_and_never_escapes_bare(self):
        _value, error, _session = self._run([FakeResponse(status_code=200, bad_json=True)] * 9)
        self.assertIn("MEDIA_SOURCE_RESPONSE_UNREADABLE", error)
        with self.assertRaises(ValueError) as caught:
            lmg.fetch_source_json(self._session([FakeResponse(status_code=200, bad_json=True)] * 9),
                                  "https://example.test/api", {"a": 1}, self.POLICY,
                                  sleep=self._sleep, now=self._now)
        self.assertIs(type(caught.exception), ValueError,
                      "只许抛登记码的 ValueError；requests 的 JSONDecodeError 裸冒到调用方＝生产者整串 traceback")
        self.assertIn("MEDIA_SOURCE_RESPONSE_UNREADABLE", str(caught.exception))

    def test_socket_failure_becomes_http_code_not_a_raw_exception(self):
        _value, error, session = self._run([ConnectionError("socket closed")] * 9)
        self.assertIn("MEDIA_SOURCE_HTTP_ERROR", error)
        self.assertEqual(session.calls, int(self.POLICY["source_fetch_policy"]["max_attempts"]))

    def test_attempts_and_budget_are_read_from_registry_not_hardcoded(self):
        # 把登记值改成 1／2 次，行为必须跟着变——这是「代码里没有那个 3」的直接证据。
        for attempts in (1, 2):
            self.waits = []
            _value, _error, session = self._run([FakeResponse(status_code=500)] * 9,
                                                max_attempts=attempts)
            self.assertEqual(session.calls, attempts, "登记改到 %d 次，代码却还在按别的次数跑" % attempts)

    def test_missing_fetch_policy_blocks_instead_of_using_defaults(self):
        block = json.loads(json.dumps(self.POLICY))
        block.pop("source_fetch_policy")
        with self.assertRaises(ValueError) as caught:
            lmg._source_request(self._session([FakeResponse(payload={})]), "https://example.test/api",
                                {"a": 1}, block, kind="json", sleep=self._sleep, now=self._now)
        self.assertIn("MEDIA_SNAPSHOT_POLICY_INCOMPLETE", str(caught.exception),
                      "退避参数没有登记处时不许悄悄用内置默认值——那就是第二把尺子")

    def test_success_returns_value_and_waits_nothing(self):
        value, error, session = self._run([FakeResponse(payload={"query": {}})])
        self.assertEqual(value, {"query": {}})
        self.assertIsNone(error)
        self.assertEqual(session.calls, 1)
        self.assertEqual(self.waits, [])


class ProducerCallShapeTests(unittest.TestCase):
    """试点实测抓到一条真缺陷：prop=revisions 配「多标题＋rvlimit」是非法组合，API 直接回 error 对象。

    旧代码不检查 error 对象就往下走，于是每行的 revid 都是 -1，
    「页存在、字节也确实取回了」被记成「说不出是哪一版」。这里钉两件事：
    ① API 的 error 对象必须点名成 MEDIA_SOURCE_RESPONSE_UNREADABLE，不许冒充 MEDIA_SNAPSHOT_UNREADABLE
      （那是本地快照读不成，归因写错比不写更难查）；
    ② 修订号必须一页一请求，且取到的 revid 是真的。
    """

    def test_api_error_object_is_named_and_not_the_snapshot_code(self):
        payload = {"error": {"code": "invalidparammix",
                             "info": "rvlimit may only be used on a single page"}}
        with self.assertRaises(ValueError) as caught:
            lmg.api_payload(payload, "revisions(File:X.jpg)")
        text = str(caught.exception)
        self.assertIn("MEDIA_SOURCE_RESPONSE_UNREADABLE", text)
        self.assertNotIn("MEDIA_SNAPSHOT_UNREADABLE", text, "远端答错≠本地快照坏了")
        self.assertIn("invalidparammix", text, "API 给的错码要带出来，事后才知道是哪条规则撞了")
        policy = lmg.source_snapshot_policy()
        self.assertIn("MEDIA_SOURCE_RESPONSE_UNREADABLE", policy["blocking_codes"],
                      "发出去的码必须先在登记面有定义")

    def test_readable_json_is_not_rejected(self):
        self.assertEqual(lmg.api_payload({"query": {"pages": {}}}, "ok"), {"query": {"pages": {}}})

    def test_revision_is_requested_per_page_with_real_revid(self):
        seen = []

        class RecordingSession:
            def get(self, url, params=None, timeout=None):
                seen.append(dict(params or {}))
                return FakeResponse(payload={"query": {"pages": {"123": {
                    "pageid": 123, "title": (params or {}).get("titles"),
                    "revisions": [{"revid": 987654, "timestamp": "2026-09-11T16:44:48Z",
                                   "user": "SomeBot"}]}}}})

        policy = lmg.source_snapshot_policy()
        got = lmg.commons_page_revision(RecordingSession(), policy, "File:A.jpg", 30)
        self.assertEqual(got["revid"], 987654, "取不到真修订号＝这一行说不出是哪一版，血缘不能记它存在")
        self.assertNotIn("|", seen[-1]["titles"], "修订查询带多标题就不能配 rvlimit（API 会整批拒绝）")
        self.assertEqual(seen[-1]["rvlimit"], "1")


class NormalizeBridgeTests(unittest.TestCase):
    """R3D 新桥：API 给 1920，本地按登记参数确定性归一到声明宽度；永不放大，两次归一必须逐字节相同。"""

    POLICY = lmg.source_snapshot_policy()
    PARAMS = None

    def setUp(self):
        NormalizeBridgeTests.PARAMS = self.POLICY["acquisition_normalize"]
        self.fx = LineageFixture(Path(self._tmp().name))

    @staticmethod
    def _tmp():
        return tempfile.TemporaryDirectory()

    def _wider_acquisition(self, entry):
        prepared = self.fx.root / "media_prepared" / "originals" / Path(entry["local_file"]).name
        declared = int(entry["source_width"])
        blob = reencode(prepared.read_bytes(), declared + 320, int(entry["source_height"] * (declared + 320) / declared))
        return blob, declared

    def test_normalize_is_byte_identical_when_repeated(self):
        blob, declared = self._wider_acquisition(self.fx.row(0))
        first, recipe_a = pm.normalize_acquisition(blob, declared, self.PARAMS)
        second, recipe_b = pm.normalize_acquisition(blob, declared, self.PARAMS)
        self.assertEqual(first, second, "同一串采集字节两次归一得出两份字节＝这条桥不可离线复算")
        self.assertEqual(recipe_a, recipe_b)
        self.assertIn("thumbnail_aspect_preserve(width=%d)" % declared, recipe_a)

    def test_bridge_accepts_normalized_recipe_only_when_it_lands_on_prepared(self):
        blob, declared = self._wider_acquisition(self.fx.row(0))
        prepared_blob, _recipe = pm.normalize_acquisition(blob, declared, self.PARAMS)
        prepared_digest = hashlib.sha256(prepared_blob).hexdigest()
        ok = lmg.bridge_from_acquisition(blob, declared, prepared_digest, self.POLICY)
        self.assertEqual(ok["error"], "")
        self.assertTrue(ok["recipe"].startswith(lmg.BRIDGE_RECIPE_NORMALIZED + "|"), ok["recipe"])
        bad = lmg.bridge_from_acquisition(blob, declared, "0" * 64, self.POLICY)
        self.assertIn("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING", bad["error"])
        # 归一本身照样算得出来（它就是 X），不匹配的是「在盘那份」——错误里必须把两个数都带出来，
        # 否则下一轮没人判断该重派生还是该改登记。
        self.assertEqual(bad["prepared_sha256"], prepared_digest)
        self.assertIn("0" * 16, bad["error"])
        self.assertIn(prepared_digest[:16], bad["error"])

    def test_verbatim_bytes_still_take_the_old_bridge(self):
        blob, declared = self._wider_acquisition(self.fx.row(0))
        digest = hashlib.sha256(blob).hexdigest()
        result = lmg.bridge_from_acquisition(blob, declared, digest, self.POLICY)
        self.assertEqual(result["recipe"], lmg.BRIDGE_RECIPE_NONCE, "逐字相等时不许改写成归一配方")
        self.assertEqual(result["error"], "")

    def test_upscale_is_refused_by_name(self):
        entry = self.fx.row(0)
        declared = int(entry["source_width"])
        narrow = reencode((self.fx.root / "media_prepared" / "originals" / Path(entry["local_file"]).name).read_bytes(),
                          max(declared - 200, 16), 120)
        with self.assertRaises(ValueError) as caught:
            pm.normalize_acquisition(narrow, declared, self.PARAMS)
        self.assertIn("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING", str(caught.exception))
        self.assertIn("禁止放大", str(caught.exception))

    def test_recorded_recipe_not_in_registry_is_named(self):
        entry = self.fx.row(0)
        record = self.fx.record(0)
        record["transform_recipe"] = "COMMONS_ORIGINAL_DOWNLOADED_THEN_MAGIC"
        errors = lmg._row_lineage_errors(entry, record, self.POLICY, entry["local_file"], self.fx.root)
        self.assertTrue(any(e.startswith("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING") and "登记只认" in e
                            for e in errors), errors)

    def test_normalized_recipe_without_acquisition_bytes_is_named(self):
        entry = self.fx.row(0)
        blob, declared = self._wider_acquisition(entry)
        prepared_blob, recipe = pm.normalize_acquisition(blob, declared, self.PARAMS)
        prepared = self.fx.root / "media_prepared" / "originals" / Path(entry["local_file"]).name
        prepared.write_bytes(prepared_blob)
        record = self.fx.record(0)
        record["transform_recipe"] = "%s|%s" % (lmg.BRIDGE_RECIPE_NORMALIZED, recipe)
        record["acquisition_sha256"] = hashlib.sha256(blob).hexdigest()
        record["prepared_sha256"] = hashlib.sha256(prepared_blob).hexdigest()
        record["source_sha256"] = record["prepared_sha256"]
        # 归一桥上 returned_* 记的是「取回那一档的实物」，不是归一后的 prepared（这条正是新对照逼出来的写法）
        with Image.open(io.BytesIO(blob)) as acquired_image:
            record["returned_width"], record["returned_height"] = (int(acquired_image.width),
                                                                   int(acquired_image.height))
        entry["source_sha256"] = record["prepared_sha256"]
        missing = lmg._row_lineage_errors(entry, record, self.POLICY, entry["local_file"], self.fx.root)
        self.assertTrue(any(e.startswith("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING") and "acquisitions" in e
                            for e in missing),
                        "归一桥不留归一前那串字节，三段就只剩两串摘要——这条必须点名")
        lmg.store_acquisition_bytes(self.fx.root, entry["local_file"], blob)
        replayed = lmg._row_lineage_errors(entry, record, self.POLICY, entry["local_file"], self.fx.root)
        self.assertFalse([e for e in replayed if e.startswith("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING")
                          and "acquisitions" in e], replayed)
        self.assertFalse([e for e in replayed
                          if e.startswith("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING")], replayed)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SourceUrlVerbatimTests(unittest.TestCase):
    """R3E（业主 2026-11-04 现场复核）：来源定位符逐字对齐快照，追加出来的第二段查询必须被点名。

    身份路径判据（identity_url_normalization 去 query 只比路径）当初是对的，但它看不见
    「同一个路径上被追加了两遍 utm」——7 行换源资产就是这么出到三张面孔的，而门全绿。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="r3e_url_")
        self.fx = LineageFixture(Path(self._tmp.name))
        self.policy = lmg.source_snapshot_policy()

    def tearDown(self):
        self._tmp.cleanup()

    def test_registration_holds_the_rule_the_code_reads(self):
        rule = self.policy["source_url_verbatim_rule"]
        self.assertEqual(rule["manifest_field"], "source_asset_url")
        self.assertEqual(list(rule["authority_fields"]), ["original_url", "source_page_url"])
        self.assertTrue(set(rule["derived_faces"]) <= {"outputs/asset-manifest.json",
                                                       "media_prepared/media-manifest.json"},
                        "登记的面孔名单换了要人来裁，代码不许自己扩大或缩小")
        for code in ("MEDIA_SOURCE_URL_NOT_VERBATIM", "MEDIA_SOURCE_URL_QUERY_DUPLICATED",
                     "MEDIA_FACE_SOURCE_URL_DIVERGED"):
            self.assertIn(code, self.policy["blocking_codes"], "码没进登记面")
            self.assertIn(code, lmg.SNAPSHOT_BLOCKING_CODES, "码没进代码表")

    def test_the_seven_real_bad_locators_are_all_named(self):
        """七条坏样本原样来自本轮证据件，不手打；每条都要被自己点名的码拦下。"""
        bad = R3E_BAD_SOURCE_URL_SAMPLES
        self.assertEqual(len(bad), 7, "样本数不是业主点名的 7 条")
        named = []
        for sample in bad:
            shape = lmg.source_url_shape_errors(sample["declared"], self.policy, sample["row"],
                                                "source_asset_url")
            codes = [e.split("|")[0] for e in shape]
            self.assertIn("MEDIA_SOURCE_URL_QUERY_DUPLICATED", codes,
                          "%s 的双查询没被形状判据拦下" % sample["row"])
            self.assertGreater(sample["declared"].count("?"),
                               self.policy["source_url_query_shape"]["max_query_segments"])
            verbatim = lmg.source_url_verbatim_errors(
                {"source_asset_url": sample["declared"], "source_page": sample["declared"]},
                {"original_url": sample["authority"], "source_page_url": sample["page"]},
                self.policy, sample["row"])
            self.assertIn("MEDIA_SOURCE_URL_NOT_VERBATIM", [e.split("|")[0] for e in verbatim],
                          "%s 没被逐字判据点名" % sample["row"])
            self.assertIn(sample["row"], " ".join(verbatim), "点名要点到具体哪一行")
            named.append(sample["row"])
        self.assertEqual(len(set(named)), 7, "七行必须各被点名一次，折叠成一条不算点名")

    def _sync_faces(self):
        """改完根清单后把三张面孔重新对齐：让「面孔差异」不替我要测的那条码挡路。

        不这么做的话，改了根行就必然同时制造 MEDIA_FACE_SOURCE_URL_DIVERGED，
        断言会「因为正确的原因通过」或「因为次要的原因失败」——两种都读不出判据。
        """
        self.fx.manifest_bytes = (json.dumps(self.fx.manifest, ensure_ascii=False, indent=1)
                                  + "\n").encode("utf-8")
        (self.fx.root / "asset-manifest.json").write_bytes(self.fx.manifest_bytes)
        (self.fx.root / "outputs" / "asset-manifest.json").write_bytes(self.fx.manifest_bytes)
        chain_path = self.fx.root / "media_prepared" / "media-manifest.json"
        chain = json.loads(chain_path.read_bytes().decode("utf-8"))
        by_local = {r["local_file"]: r for r in self.fx.manifest["assets"]}
        for item in chain["entries"]:
            item["source_asset_url"] = by_local[item["local_file"]]["source_asset_url"]
        chain_path.write_bytes((json.dumps(chain, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))

    def test_positive_control_three_faces_still_pass(self):
        result = self.fx.validate(self.fx.snapshot(self.fx.good_records()))
        self.assertGreaterEqual(result["lineage_rows_checked"], 1)

    def _codes_after_mutating_row0(self, new_url):
        row = self.fx.row(0)
        row["source_asset_url"] = new_url
        self._sync_faces()
        with self.assertRaises(ValueError) as ctx:
            self.fx.validate(self.fx.snapshot(self.fx.good_records()))
        return set(LineageFixture.codes_of(ctx.exception))

    def test_appended_query_breaks_verbatim_and_shape_together(self):
        base = ORIGINAL_URL
        # ① 追加一段但没有第二个 ?：形状判据按登记不拦（它管的是重复查询），
        #    路径与逐字两条判据各自拦下——被别的码拦下不算这条码的证据，反过来也一样。
        codes = self._codes_after_mutating_row0(base + "&x=1")
        self.assertIn("MEDIA_SOURCE_URL_NOT_VERBATIM", codes)
        self.assertNotIn("MEDIA_SOURCE_URL_QUERY_DUPLICATED", codes,
                         "只有一个 ? 时不许被形状判据点名，否则登记里的阈值就成了摆设")
        # ② 业主现场发现的真形状：整串查询被写了两遍（两个 ?）⇒ 两条码同时点名
        doubled = "%s?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original" \
                  "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original" % base
        codes = self._codes_after_mutating_row0(doubled)
        self.assertIn("MEDIA_SOURCE_URL_NOT_VERBATIM", codes)
        self.assertIn("MEDIA_SOURCE_URL_QUERY_DUPLICATED", codes)

    def test_duplicate_param_key_without_second_mark_still_blocks(self):
        errs = lmg.source_url_shape_errors("https://a.example/x?utm_source=k&utm_source=j",
                                          self.policy, "assets/section/x.jpg", "source_asset_url")
        self.assertTrue(any("MEDIA_SOURCE_URL_QUERY_DUPLICATED" in e for e in errs),
                        "同一个参数键出现两次＝拼接痕迹，不能因为它只有一个 ? 就放行")

    def test_page_declaration_equals_source_page_url_passes(self):
        """写文件页是登记承认的另一种声明；但它必须逐字等于快照的 source_page_url。"""
        row = self.fx.row(0)
        row["source_asset_url"] = PAGE_URL
        self._sync_faces()
        self.fx.validate(self.fx.snapshot([self.fx.record(0), self.fx.record(1)]))   # 不抛＝过
        row["source_asset_url"] = PAGE_URL.replace("File:", "File%3A")
        self._sync_faces()
        with self.assertRaises(ValueError) as ctx:
            self.fx.validate(self.fx.snapshot([self.fx.record(0), self.fx.record(1)]))
        self.assertIn("MEDIA_SOURCE_URL_NOT_VERBATIM", LineageFixture.codes_of(ctx.exception))

    def test_marker_limit_and_segments_come_from_registration(self):
        policy = json.loads(json.dumps(self.policy))
        url = "https://a.example/x?utm_source=k&utm_medium=m?utm_source=k"
        self.assertTrue(lmg.source_url_shape_errors(url, policy, "r", "source_asset_url"))
        policy["source_url_query_shape"]["max_query_segments"] = 2
        policy["source_url_query_shape"]["max_marker_hits"] = 2
        self.assertEqual(lmg.source_url_shape_errors(url, policy, "r", "source_asset_url"), [],
                         "把登记放宽到允许两段时行为必须跟着变——变了才证明代码里没有那个字面量 1")

    def test_missing_registration_is_policy_incomplete_not_a_default(self):
        for drop in ("source_url_query_shape", "source_url_verbatim_rule"):
            policy = json.loads(json.dumps(self.policy))
            del policy[drop]
            with self.assertRaises(ValueError) as ctx:
                lmg.source_url_shape_errors("https://x/y", policy, "r", "source_asset_url")
            self.assertIn("MEDIA_SNAPSHOT_POLICY_INCOMPLETE", str(ctx.exception))

    def test_face_divergence_and_missing_face_are_named_per_row(self):
        outputs = json.loads((self.fx.root / "outputs" / "asset-manifest.json")
                             .read_bytes().decode("utf-8"))
        outputs["assets"][0]["source_asset_url"] = ORIGINAL_URL + "?utm_source=k"
        (self.fx.root / "outputs" / "asset-manifest.json").write_bytes(
            (json.dumps(outputs, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        errs = lmg.source_url_face_errors(self.fx.root, self.fx.manifest, self.policy)
        self.assertEqual(len(errs), 1, errs)
        self.assertIn(self.fx.row(0)["local_file"], errs[0])
        self.assertIn("MEDIA_FACE_SOURCE_URL_DIVERGED", errs[0])
        (self.fx.root / "media_prepared" / "media-manifest.json").unlink()
        errs = lmg.source_url_face_errors(self.fx.root, self.fx.manifest, self.policy)
        self.assertTrue(any("不在盘上" in e for e in errs), "缺件必须自己说，不许静悄悄少一格")

    def test_collect_mode_keeps_every_row_finding_instead_of_one_abort(self):
        """V6-S 那把尺子（首异常即停会把已点名的结论挤掉）现在也管血缘段。"""
        row = self.fx.row(0)
        row["source_asset_url"] = ORIGINAL_URL + "?utm_source=k"
        self._sync_faces()
        collected = []
        result = lmg.validate_source_identities(self.fx.manifest, base_dir=self.fx.root,
                                                snapshot=self.fx.snapshot(self.fx.good_records()),
                                                manifest_bytes=self.fx.manifest_bytes,
                                                as_of=date.today(), collect=collected)
        self.assertTrue(collected, "行级结论没交出来，就只剩一条截断的 abort 文本")
        self.assertTrue(any(self.fx.row(0)["local_file"] in e for e in collected),
                        "结论必须点到那一行，不然和「一条 abort」没有区别")
        self.assertTrue(any(e.split("|")[0] == "MEDIA_SOURCE_URL_NOT_VERBATIM" for e in collected),
                        "点名要点到那条被否的判据本身")
        self.assertIsInstance(result, dict)
        with self.assertRaises(ValueError):
            self.fx.validate(self.fx.snapshot(self.fx.good_records()))


# ---- R3F（业主 2026-11-04 第 4／6／7 条）：run 内可解析路径必须 run 相对且落在 run 根内 ----
# 下面两串前缀与 27 个行名是从**改前的正式 run 现场**抄的（账见
# .temp/v422_honest_map/ZH_RELEASE_3/R3F_FIX_STAGING_BASELINE.json 的 defect_face_before），
# 不是编的坏样本：业主点名的三类形状（26 条 candidate_runs 绝对 source／1 条空 source／
# 27 条 .temp staging relpath）都要被这条门逐条点名，点名不了就等于没验。
R3F_LEGACY_CANDIDATE_ROOT = ("D:/文档/项目开发/Travel-Scope/travel-scope-v4.2.2/candidate_runs/"
                             "travel_scope_run_202701_usa_california_v422_001/assets")
R3F_LEGACY_STAGING_RENDITION_ROOT = ("D:/文档/项目开发/Travel-Scope/.temp/v422_honest_map/"
                                     "ZH_RELEASE_3/staging/full_ca_run/assets/renditions")
R3F_LIVE_ROWS = [
    "assets/editorial/sf_golden_gate.jpg", "assets/editorial/sf_palace_fine_arts.jpg",
    "assets/editorial/monterey_lone_cypress.jpg", "assets/editorial/big_sur_bixby_bridge.jpg",
    "assets/editorial/santa_barbara_courthouse.jpg", "assets/editorial/la_griffith_observatory.jpg",
    "assets/editorial/la_hermosa_pier.jpg", "assets/editorial/la_lighthouse_cafe.jpg",
    "assets/editorial/la_angels_flight.jpg", "assets/editorial/la_colorado_bridge.jpg",
    "assets/editorial/la_santa_monica_pier.jpg", "assets/section/sf_food.jpg",
    "assets/section/sf_sights.jpg", "assets/section/monterey_hotels.jpg",
    "assets/section/monterey_food.jpg", "assets/section/monterey_sights.jpg",
    "assets/section/big_sur_hotels.jpg", "assets/section/big_sur_food.jpg",
    "assets/section/big_sur_cafes.jpg", "assets/section/big_sur_sights.jpg",
    "assets/section/santa_barbara_hotels.jpg", "assets/section/santa_barbara_food.jpg",
    "assets/section/santa_barbara_sights.jpg", "assets/section/la_hotels.jpg",
    "assets/section/la_cafes.jpg", "assets/section/la_sights.jpg",
    "assets/editorial/la_grand_central_market.jpg"]
R3F_EMPTY_SOURCE_ROW = "assets/editorial/la_grand_central_market.jpg"
R3F_CODES = ("MEDIA_RUN_PATH_EMPTY", "MEDIA_RUN_PATH_ABSOLUTE", "MEDIA_RUN_PATH_SEPARATOR",
             "MEDIA_RUN_PATH_FORBIDDEN_ROOT", "MEDIA_RUN_PATH_TRAVERSES_OUT",
             "MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT", "MEDIA_RUN_PATH_TARGET_MISSING",
             "MEDIA_RUN_PATH_TARGET_NOT_THE_RECORDED_BYTES", "MEDIA_RUN_PATH_LAYOUT_MISMATCH")


class RunPathSelfContainmentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="media_run_path_test_")
        self.fx = LineageFixture(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)
        self.policy = lmg.source_snapshot_policy()

    def chain_of(self, entries):
        return {"status": "PASS", "assets": len(entries),
                "renditions": sum(len(e.get("renditions") or []) for e in entries),
                "entries": entries}

    def tier_for(self, index: int = 0) -> str:
        """夹具第 index 行实产并装到登记位置的档位文件名。

        第一版用 glob 的第一份当「通用档位」，结果拿 tp_hero 的产物去配 tp_hotels 那一行，
        门报的是摘要不符——那条码没有错，错的是题。每行用它自己那一格。
        """
        chain = json.loads((self.fx.root / "media_prepared" / "media-manifest.json")
                           .read_bytes().decode("utf-8"))
        rel = chain["entries"][index]["renditions"][0]["relpath"]
        name = rel.replace("\\", "/").split("/")[-1]
        self.assertTrue((self.fx.root / rel.replace("\\", "/")).is_file(),
                        "夹具没把档位装到登记位置 %r，下面的对照无从成立" % rel)
        return name

    def tier_name(self) -> str:
        return self.tier_for(0)

    def entry(self, index, source, relpath):
        """拿夹具那一行的真摘要拼一格：摘要不符会另报一条码，这里要的是「只有形状坏」。"""
        row = self.fx.row(index)
        tier = (row["renditions"] or [{}])[0]
        return {"local_file": row["local_file"], "slot": row["slot"],
                "source_asset_url": row["source_asset_url"], "source": source,
                "source_sha256": row["source_sha256"], "declared_sha256": row["source_sha256"],
                "renditions": [{"label": tier.get("label") or "w700", "width": tier.get("width") or 1,
                                "height": tier.get("height") or 1, "bytes": tier.get("bytes") or 0,
                                "relpath": relpath, "delivered_sha256": tier["delivered_sha256"]}]}

    def codes_for(self, entries, run_manifest=None):
        return lmg.run_path_containment_errors(
            self.fx.root, self.policy, run_manifest=run_manifest,
            faces={"media_prepared/media-manifest.json": self.chain_of(entries)})

    @staticmethod
    def codes_only(errors):
        return sorted({e.split("|")[0] for e in errors})

    def test_live_run_counts_match_the_registration(self):
        """测试里的样本数必须等于登记面现场量的数——不然这是「自己造题自己答」的负测。"""
        measured = self.policy["run_relative_path_rule"]["measured_on_live_run_2026_11_04"]
        self.assertEqual(len(R3F_LIVE_ROWS), measured["chain_rows"])
        self.assertEqual(measured["absolute_source_rows"], 26)
        self.assertEqual(measured["empty_source_rows"], [R3F_EMPTY_SOURCE_ROW])
        self.assertEqual(measured["absolute_relpath_rows"], 27)
        self.assertEqual(measured["absolute_relpath_into_temp"], 27)

    def test_the_legacy_absolute_and_staging_shapes_are_all_named(self):
        """业主第 6 条点名的三类形状：26 条绝对 source、1 条空 source、27 条 .temp relpath 全要点名。"""
        rows = self.fx.manifest["assets"]
        entries = []
        for index, row in enumerate(rows):
            source = ("" if index == 0 else
                      "%s/%s" % (R3F_LEGACY_CANDIDATE_ROOT,
                                 row["local_file"].replace("assets/", "")))
            entries.append(self.entry(index, source, "%s/%s--w700.jpg" % (
                R3F_LEGACY_STAGING_RENDITION_ROOT, Path(row["local_file"]).stem)))
        errors, _metrics = self.codes_for(entries)
        codes = self.codes_only(errors)
        for code in ("MEDIA_RUN_PATH_ABSOLUTE", "MEDIA_RUN_PATH_FORBIDDEN_ROOT",
                     "MEDIA_RUN_PATH_EMPTY"):
            self.assertIn(code, codes, codes)
        named = {r for e in errors for r in [row["local_file"] for row in rows] if r in e}
        for row in rows:
            self.assertIn(row["local_file"], named, "行 %s 没被点名 ⇒ 折成一条就等于没验" % row["local_file"])
        staging_named = sum(1 for e in errors if ".temp" in e and "renditions/" in e)
        self.assertGreaterEqual(staging_named, len(entries),
                                "每条 .temp relpath 都要有自己的那一条：%s" % [e[:120] for e in errors])

    def test_each_bad_shape_is_caught_by_the_code_that_names_it(self):
        """一条形状一条码，各自被自己点名的码拦下（被别的码拦下＝不算证）。"""
        good_source = "media_prepared/originals/%s" % Path(self.fx.row(0)["local_file"]).name
        good_rel = "assets/renditions/%s" % self.tier_name()
        cases = [
            ("", good_rel, {"MEDIA_RUN_PATH_EMPTY"}),
            ("C:/elsewhere/originals/x.jpg", good_rel, {"MEDIA_RUN_PATH_ABSOLUTE"}),
            ("candidate_runs/other/x.jpg", good_rel, {"MEDIA_RUN_PATH_FORBIDDEN_ROOT"}),
            ("media_prepared\\originals\\x.jpg", good_rel, {"MEDIA_RUN_PATH_SEPARATOR"}),
            ("media_prepared/originals/../../escape.jpg", good_rel, {"MEDIA_RUN_PATH_TRAVERSES_OUT"}),
            (good_source, "media_prepared/elsewhere/x.jpg", {"MEDIA_RUN_PATH_LAYOUT_MISMATCH"}),
            (good_source, "assets/renditions/never_written.jpg", {"MEDIA_RUN_PATH_TARGET_MISSING"}),
        ]
        for source, rel, want in cases:
            errors, _metrics = self.codes_for([self.entry(0, source, rel)])
            self.assertEqual(self.codes_only(errors), sorted(want),
                             "形状 %r／%r 应只被 %s 拦下，实际=%s（%s）"
                             % (source, rel, sorted(want), self.codes_only(errors),
                                [e[:120] for e in errors]))

    def test_digest_mismatch_is_a_code_of_its_own(self):
        """路径对、文件在、但摘要不是那一行登记的那串 ⇒ 改路径时把字节换了，单独一条码。"""
        row = self.fx.row(0)
        entry = self.entry(0, "media_prepared/originals/%s" % Path(row["local_file"]).name,
                           "assets/renditions/%s" % self.tier_name())
        entry["source_sha256"] = "0" * 64
        errors, _metrics = self.codes_for([entry])
        self.assertEqual(self.codes_only(errors), ["MEDIA_RUN_PATH_TARGET_NOT_THE_RECORDED_BYTES"],
                         [e[:160] for e in errors])

    def test_positive_control_current_fixture_passes_and_counts(self):
        """夹具现在的形状（run 相对＋在根内）必须绿，而且报告要说清扫了多少格。"""
        chain = json.loads((self.fx.root / "media_prepared" / "media-manifest.json")
                           .read_bytes().decode("utf-8"))
        errors, metrics = lmg.run_path_containment_errors(self.fx.root, self.policy)
        self.assertEqual(errors, [], "现行形状不该被拦：%s" % [e[:160] for e in errors])
        faces = self.policy["run_relative_path_rule"]["applies_to_faces"]
        self.assertEqual(metrics["run_path_faces_scanned"], len(faces))
        self.assertGreaterEqual(metrics["run_path_fields_checked"],
                                len(faces["manifest.json"]["fields"]) + len(chain["entries"]) * 2,
                                "面孔与行格都要真扫到；扫空也算 0 错误就是假绿")

    def test_run_manifest_face_absolute_field_blocks_and_names_the_field(self):
        """run 自己的输入声明也在这一条管的范围里（同轮裁定：输入路径也 run 相对）。"""
        bad = dict(self.fx.run_manifest)
        bad["scope_path"] = R3F_LEGACY_STAGING_RENDITION_ROOT + "/scope.json"
        errors, _metrics = self.codes_for(
            [self.entry(0, "media_prepared/originals/%s" % Path(self.fx.row(0)["local_file"]).name,
                        "assets/renditions/%s" % self.tier_name())], run_manifest=bad)
        codes = self.codes_only(errors)
        self.assertIn("MEDIA_RUN_PATH_ABSOLUTE", codes)
        self.assertIn("MEDIA_RUN_PATH_FORBIDDEN_ROOT", codes)
        self.assertTrue(any("scope_path" in e for e in errors),
                        "要点名到具体哪一格：%s" % [e[:120] for e in errors])

    def test_finalizer_rewrites_legacy_shapes_to_the_registered_layout(self):
        """生产者侧唯一实现改的是路径，不是字节（业主第 7 条：不修改任何图片或 HTML 字节）。"""
        row = self.fx.row(0)
        name = Path(row["local_file"]).name
        tier = self.tier_name()
        legacy = self.chain_of([{"local_file": row["local_file"], "slot": row["slot"],
                                 "source": "%s/%s" % (R3F_LEGACY_CANDIDATE_ROOT,
                                                      row["local_file"].replace("assets/", "")),
                                 "source_sha256": row["source_sha256"],
                                 "renditions": [dict(row["renditions"][0],
                                                    relpath="%s/%s" % (
                                                        R3F_LEGACY_STAGING_RENDITION_ROOT, tier))]}])
        before = {p.name: p.read_bytes() for p in (self.fx.root / "assets" / "renditions").glob("*.jpg")}
        fixed = pm.finalize_chain_face(self.fx.root, legacy, verify_files=True)
        entry = fixed["entries"][0]
        self.assertEqual(entry["source"], "media_prepared/originals/%s" % name)
        self.assertEqual(entry["renditions"][0]["relpath"], "assets/renditions/%s" % tier)
        self.assertEqual(fixed["path_form"]["entries_source_rewritten"], 1)
        self.assertEqual({p.name: p.read_bytes()
                          for p in (self.fx.root / "assets" / "renditions").glob("*.jpg")}, before,
                         "改路径不该动任何图片字节")

    def test_finalizer_refuses_to_call_outside_bytes_part_of_the_run(self):
        """绝对值落在 run 外时，序列化只做一件事：把它写成 run 内的登记位置。

        写完之后如果 run 内那一格没有实物，必须按 TARGET_MISSING 阻断——
        「外面那份能读到」不能替代「本 run 有这一份字节」，这正是换机断链的形状。
        """
        row = self.fx.row(0)
        tier = self.tier_for(0)
        legacy = self.chain_of([self.entry(0, "%s/%s" % (R3F_LEGACY_CANDIDATE_ROOT,
                                                        row["local_file"].replace("assets/", "")),
                                           "%s/%s" % (R3F_LEGACY_STAGING_RENDITION_ROOT, tier))])
        removed = self.fx.root / "assets" / "renditions" / tier
        keep = removed.read_bytes()
        removed.unlink()
        self.addCleanup(lambda: removed.write_bytes(keep))
        with self.assertRaises(ValueError) as caught:
            pm.finalize_chain_face(self.fx.root, legacy, verify_files=True)
        message = str(caught.exception)
        self.assertIn("MEDIA_RUN_PATH_TARGET_MISSING", message)
        self.assertNotIn(R3F_LEGACY_STAGING_RENDITION_ROOT.split("/")[0] + ":/", message,
                         "报错里不该留一份「那串绝对值被当成答案」的形状")

    def test_empty_source_row_gets_its_prepared_original_path(self):
        """业主第 3 条：GCM 那种空 source 不是「跳过」，要补成 run 内 prepared 原图那一格。"""
        row = self.fx.row(1)
        name = Path(row["local_file"]).name
        tier = self.tier_for(1)
        legacy = self.chain_of([{"local_file": row["local_file"], "slot": row["slot"],
                                 "source": "", "source_sha256": row["source_sha256"],
                                 "renditions": [dict(row["renditions"][0],
                                                    relpath="%s/%s" % (
                                                        R3F_LEGACY_STAGING_RENDITION_ROOT, tier))]}])
        fixed = pm.finalize_chain_face(self.fx.root, legacy, verify_files=True)
        self.assertEqual(fixed["entries"][0]["source"], "media_prepared/originals/%s" % name)

    def test_thresholds_and_codes_come_from_the_registration(self):
        """禁串与 must 都读登记：把 candidate_runs 从登记里摘掉，同一格就不该再报那条码。"""
        source = "%s/%s" % (R3F_LEGACY_CANDIDATE_ROOT,
                            self.fx.row(0)["local_file"].replace("assets/", ""))
        entries = [self.entry(0, source, "assets/renditions/%s" % self.tier_name())]
        strict, _ = self.codes_for(entries)
        self.assertIn("MEDIA_RUN_PATH_FORBIDDEN_ROOT", self.codes_only(strict))
        loosened = json.loads(json.dumps(self.policy))
        loosened["run_relative_path_rule"]["forbid_substrings"] = ["not-a-real-root-here"]
        loose, _m = lmg.run_path_containment_errors(
            self.fx.root, loosened,
            faces={"media_prepared/media-manifest.json": self.chain_of(entries)})
        self.assertNotIn("MEDIA_RUN_PATH_FORBIDDEN_ROOT", self.codes_only(loose),
                         "阈值若住在代码里，这条测试就白写")
        self.assertIn("MEDIA_RUN_PATH_ABSOLUTE", self.codes_only(loose),
                      "摘掉禁串不该把绝对性也一起放过")

    def test_missing_registration_block_refuses_to_guess(self):
        stripped = json.loads(json.dumps(self.policy))
        stripped.pop("run_relative_path_rule")
        with self.assertRaises(ValueError) as caught:
            lmg.run_path_containment_errors(self.fx.root, stripped)
        self.assertIn("MEDIA_SNAPSHOT_POLICY_INCOMPLETE", str(caught.exception))

    def test_the_nine_run_path_codes_are_registered_and_spoken(self):
        """登记面与代码内的闭集必须一起老：任一边多一条都阻断（这条测试自己也是牙）。"""
        for code in R3F_CODES:
            self.assertIn(code, self.policy["blocking_codes"], "%s 没进登记的 blocking_codes" % code)
            self.assertIn(code, lmg.SNAPSHOT_BLOCKING_CODES, "%s 没进代码里的码表" % code)
        self.assertIn("run_relative_path_rule", lmg.SNAPSHOT_POLICY_KEYS)

    def test_validator_blocks_the_legacy_face_through_the_full_gate(self):
        """走完整道门（不是只单测判据函数）：改前形状要让 validate_source_identities 报同一批码。"""
        row = self.fx.row(0)
        chain_path = self.fx.root / "media_prepared" / "media-manifest.json"
        legacy = self.chain_of([self.entry(
            0, "%s/%s" % (R3F_LEGACY_CANDIDATE_ROOT, row["local_file"].replace("assets/", "")),
            "%s/%s--w700.jpg" % (R3F_LEGACY_STAGING_RENDITION_ROOT,
                                 Path(row["local_file"]).stem))])
        chain_path.write_bytes((json.dumps(legacy, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        with self.assertRaises(ValueError) as caught:
            self.fx.validate(self.fx.snapshot(self.fx.good_records()))
        codes = self.fx.codes_of(caught.exception)
        self.assertIn("MEDIA_RUN_PATH_ABSOLUTE", codes)
        self.assertIn("MEDIA_RUN_PATH_FORBIDDEN_ROOT", codes)
        self.assertIn(row["local_file"], str(caught.exception))
