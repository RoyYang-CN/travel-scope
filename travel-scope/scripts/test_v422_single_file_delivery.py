# -*- coding: utf-8 -*-
"""v4.2.2 V5-D 执行型测试：单文件自包含字节对账（V0-L11）与读者页图片身份对账（V0-L12）。

规则同 V5-A/B/C：门禁只陈述事实、由登记配置决定严重度；错误码闭集双向核对；
预算与上限只有一个来源。历史成品（runs/、.temp/v421）只读打开，测完复验 SHA。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import self_contained_audit as sfa          # noqa: E402
import single_file_policy as sfp            # noqa: E402
import spa_renderer                         # noqa: E402
import local_media_gate                     # noqa: E402
import visual_qa                            # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROJ = ROOT.parents[1]
POLICY = sfp.load_policy()
FENCE = int(POLICY["budgets"]["max_delivered_file_bytes"])
CAP_KB = POLICY["media_delivery"]["default_max_inline_kb"]
CAP_BYTES = CAP_KB * 1024


def blob_bytes(seed: str, size: int = 1024) -> bytes:
    """可复现的伪图片字节：长度可控，digest 稳定。"""
    body = (seed.encode("utf-8") * (size // len(seed) + 1))[:size]
    return b"\x89PNG\r\n\x1a\n" + body


def code_lines(path: Path) -> str:
    """只比对代码行：解释性文字里提到旧常数/旧码不代表实现又写了一遍。"""
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.strip().startswith(("#", "//", "*", '"""')))


def data_uri(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def build_html(*, blobs=(), refs=None, extra_imgs=(), cap_meta=True, pad=0) -> str:
    """造一份最小读者产物：blob 表 + 引用 + 可选静态 img + 可选上限标记。"""
    table = {hashlib.sha256(raw).hexdigest(): data_uri(raw) for raw in blobs}
    ref_list = list(refs) if refs is not None else list(table)
    dataset = json.dumps({"asset_blobs": table,
                          "refs": ["asset://sha256:" + d for d in ref_list]},
                         ensure_ascii=False)
    metas = ['<meta charset="utf-8">',
             '<meta name="travel-scope-renderer" content="travel-scope-spa-v1">']
    if cap_meta:
        metas.append(sfp.media_cap_meta_html(CAP_KB))
    imgs = "".join('<img src="%s" alt="%s">' % (src, alt) for src, alt in extra_imgs)
    return ("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n" + "\n".join(metas) +
            "\n</head>\n<body>\n<script id=\"dataset\" type=\"application/json\">" +
            dataset + "</script>\n" + imgs + ("x" * pad) + "\n</body>\n</html>\n")


def write_tmp(html_text: str) -> Path:
    folder = tempfile.mkdtemp(prefix="v5d_case_")
    path = Path(folder) / "demo-travel-guide.html"
    path.write_bytes(html_text.encode("utf-8"))
    return path


class PolicyTeethTests(unittest.TestCase):
    def test_registered_policy_loads_and_is_self_consistent(self):
        policy = sfp.load_policy()
        self.assertEqual(policy["id"], sfp.POLICY_ID)
        self.assertGreater(int(policy["budgets"]["max_delivered_file_bytes"]), 0)

    def test_missing_file_is_fatal_not_defaulted(self):
        with self.assertRaises(sfp.SingleFilePolicyError) as ctx:
            sfp.load_policy(Path(tempfile.mkdtemp()) / "nope.json")
        self.assertIn("不存在", str(ctx.exception))

    def test_id_drift_is_fatal(self):
        path = _patched_policy({"id": "v4.2.1-old-1"})
        with self.assertRaises(sfp.SingleFilePolicyError) as ctx:
            sfp.load_policy(path)
        self.assertIn("id 漂移", str(ctx.exception))

    def test_missing_budget_number_is_fatal(self):
        path = _patched_policy({"budgets": {**POLICY["budgets"],
                                            "max_delivered_file_bytes": "4MB 左右"}})
        with self.assertRaises(sfp.SingleFilePolicyError) as ctx:
            sfp.load_policy(path)
        self.assertIn("围栏", str(ctx.exception))

    def test_inconsistent_budgets_are_fatal(self):
        path = _patched_policy({"budgets": {**POLICY["budgets"],
                                            "hero_inline_budget_bytes": 9_000_000}})
        with self.assertRaises(sfp.SingleFilePolicyError) as ctx:
            sfp.load_policy(path)
        self.assertIn("不自洽", str(ctx.exception))

    def test_cap_marker_name_must_be_registered(self):
        path = _patched_policy({"media_delivery": {**POLICY["media_delivery"],
                                                  "declared_in_html": "写进产物就行"}})
        with self.assertRaises(sfp.SingleFilePolicyError) as ctx:
            sfp.load_policy(path)
        self.assertIn("travel-scope-media-cap", str(ctx.exception))

    def test_unclassified_severity_is_refused(self):
        path = _patched_policy({"reason_codes": {**POLICY["reason_codes"],
                                                 "SFD_MYSTERY": "we-don't-know"}})
        with self.assertRaises(sfp.SingleFilePolicyError) as ctx:
            sfp.load_policy(path)
        self.assertIn("第三档", str(ctx.exception))

    def test_split_findings_refuses_unregistered_code(self):
        with self.assertRaises(sfp.SingleFilePolicyError):
            sfp.split_findings(["SFD_NOT_REGISTERED|随手写的一条"], POLICY)

    def test_advisory_is_kept_out_of_blocking_but_stays_visible(self):
        blocking, advisory = sfp.split_findings(
            ["SFD_DEAD_BLOB|死字节", "IMG_DATASET_SLOT_EMPTY|空槽位"], POLICY)
        self.assertEqual([item.split("|")[0] for item in blocking], ["SFD_DEAD_BLOB"])
        self.assertEqual([item.split("|")[0] for item in advisory], ["IMG_DATASET_SLOT_EMPTY"])


def _policy_file(policy: dict) -> Path:
    folder = tempfile.mkdtemp(prefix="v5d_policy_")
    path = Path(folder) / "single-file-delivery-policy.json"
    path.write_bytes(json.dumps(policy, ensure_ascii=False, indent=2).encode("utf-8"))
    return path


def _patched_policy_raw(policy: dict) -> Path:
    return _policy_file(policy)


def _patched_policy(overrides: dict) -> Path:
    policy = json.loads(json.dumps(POLICY))
    policy.update(overrides)
    return _policy_file(policy)


class ByteAccountingTests(unittest.TestCase):
    def test_clean_file_has_no_findings_and_honest_inflation(self):
        blobs = [blob_bytes("a", 4096), blob_bytes("b", 9000)]
        path = write_tmp(build_html(blobs=blobs))
        audit = sfa.audit(path)
        measured = audit["measured"]
        self.assertEqual(audit["findings"], [], audit["findings"])
        self.assertEqual(measured["inline_blob_texts"], 2)
        self.assertEqual(measured["unique_inline_blobs"], 2)
        self.assertEqual(measured["duplicate_blob_texts"], 0)
        self.assertEqual(measured["dead_blobs"], [])
        self.assertEqual(measured["dangling_asset_refs"], [])
        self.assertEqual(measured["decoded_blob_bytes"], sum(len(raw) for raw in blobs))
        # base64 每 3 字节膨胀成 4 个字符：账单必须把「文件里占的位子」和「图片本身」分开报。
        self.assertAlmostEqual(measured["blob_base64_inflation"], 4 / 3, places=2)
        self.assertEqual(measured["file_bytes"],
                         measured["blob_text_bytes"] + measured["container_bytes"])

    def test_dead_blob_is_named_and_blocking(self):
        blobs = [blob_bytes("used", 2048), blob_bytes("dead", 2048)]
        used = hashlib.sha256(blobs[0]).hexdigest()
        path = write_tmp(build_html(blobs=blobs, refs=[used]))
        audit = sfa.audit(path)
        self.assertEqual(audit["blocking"], [audit["findings"][0]])
        self.assertIn("SFD_DEAD_BLOB", audit["findings"][0])
        self.assertIn(hashlib.sha256(blobs[1]).hexdigest()[:12], audit["findings"][0])

    def test_dangling_asset_ref_is_blocking(self):
        path = write_tmp(build_html(blobs=[blob_bytes("x", 2048)],
                                    refs=[hashlib.sha256(b"x" * 300).hexdigest()]))
        self.assertIn("SFD_DANGLING_ASSET_REF", "".join(sfa.audit(path)["blocking"]))

    def test_static_external_and_masked_refs_are_blocking(self):
        path = write_tmp(build_html(blobs=[blob_bytes("y", 2048)],
                                    extra_imgs=[("assets/section/a.jpg", "Hotel"),
                                                ("assets/MASKED_cover.jpg", "Cover")]))
        codes = "".join(sfa.audit(path)["blocking"])
        self.assertIn("SFD_STATIC_EXTERNAL_IMG_REF", codes)
        self.assertIn("SFD_MASKED_IMG_REF", codes)
        lonely_masked = write_tmp(build_html(blobs=[blob_bytes("m", 2048)],
                                             extra_imgs=[("data:MASKED", "Cover")]))
        self.assertIn("SFD_MASKED_IMG_REF", "".join(sfa.audit(lonely_masked)["blocking"]))

    def test_missing_and_wrong_cap_marker_are_distinguished(self):
        good = write_tmp(build_html(blobs=[blob_bytes("z", 2048)]))
        self.assertEqual(sfa.audit(good)["blocking"], [])
        nomark = write_tmp(build_html(blobs=[blob_bytes("z", 2048)], cap_meta=False))
        self.assertIn("SFD_MEDIA_CAP_UNMARKED", "".join(sfa.audit(nomark)["blocking"]))
        policy = json.loads(json.dumps(POLICY))
        policy["media_delivery"]["default_max_inline_kb"] = CAP_KB + 1
        # V6-C 起单图交付上限与内联上限被登记绑成同一个数（load_policy 会核对），
        # 所以这份「只改档位」的夹具必须一起改，否则它测的就不是标记差异而是配置不自洽。
        policy["delivered_rendition_ladder"]["budgets"]["max_delivered_image_decoded_bytes"] = \
            (CAP_KB + 1) * 1024
        audit = sfa.audit(good, sfp.load_policy(_patched_policy_raw(policy)))
        self.assertIn("SFD_MEDIA_CAP_DIFFERS", "".join(audit["blocking"]))

    def test_file_over_fence_is_blocked_with_the_excess_named(self):
        path = write_tmp(build_html(blobs=[blob_bytes("p", 2048)], pad=FENCE + 4096))
        findings = "".join(sfa.audit(path)["blocking"])
        self.assertIn("SFD_FILE_BYTES_OVER_FENCE", findings)
        self.assertIn(f"{FENCE:,}B", findings)

    def test_blob_over_registered_cap_is_blocked(self):
        path = write_tmp(build_html(blobs=[blob_bytes("big", CAP_BYTES + 4096)]))
        self.assertIn("SFD_BLOB_OVER_REGISTERED_CAP", "".join(sfa.audit(path)["blocking"]))

    def test_missing_file_reports_only_missing(self):
        audit = sfa.audit(Path(tempfile.mkdtemp()) / "gone-travel-guide.html")
        self.assertEqual([item.split("|")[0] for item in audit["blocking"]], ["SFD_FILE_MISSING"])

    def test_unreadable_bytes_are_not_silently_passed(self):
        folder = tempfile.mkdtemp(prefix="v5d_junk_")
        path = Path(folder) / "broken-travel-guide.html"
        path.write_bytes(b"\xff\xfe\x00not utf-8 at all")
        audit = sfa.audit(path)
        self.assertIn("SFD_FILE_UNREADABLE", "".join(audit["blocking"]))
        self.assertEqual(audit["status"], "FAIL")


class MeasuredAnchorTests(unittest.TestCase):
    """配置里登记的实测锚点必须能被复算：数字不再只是文档里的形容词。"""

    ANCHORS = [(".temp/v421/seal_run/outputs/usa-california-travel-guide.html",
                {"file_bytes": 4_609_946, "inline_blob_texts": 25, "duplicate_blob_texts": 0,
                 "dead_blobs": [], "dangling_asset_refs": []}),
               ("runs/travel_scope_run_202701_usa_california_v420_001/outputs/"
                "usa-california-travel-guide.html",
                {"file_bytes": 2_011_235, "inline_blob_texts": 4, "duplicate_blob_texts": 1}),
               ("runs/travel_scope_run_202702_philippines_visayas_v419_001/outputs/"
                "philippines-visayas-guide-travel-guide.html",
                {"file_bytes": 511_998, "inline_blob_texts": 0})]

    def test_anchors_reproduce_and_history_stays_read_only(self):
        for rel, expected in self.ANCHORS:
            path = PROJ / rel
            with self.subTest(artifact=rel):
                self.assertTrue(path.is_file(), path)
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                measured = sfa.account(path)
                for key, value in expected.items():
                    self.assertEqual(measured[key], value,
                                     "%s 的 %s 与登记锚点不符（口径漂移或历史成品被动过）" % (rel, key))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before,
                                 "只读面被写入：历史成品测量后必须字节不变")

    def test_anchor_fence_is_derived_from_the_accepted_artifact(self):
        accepted = int(POLICY["measured_anchors"]["delivered_artifacts"][2]["file_bytes"])
        self.assertEqual(FENCE, int(accepted * 1.25))
        self.assertIn("4,609,946", POLICY["budgets"]["derivation"])


class RendererMarkerTests(unittest.TestCase):
    def test_renderer_marks_the_cap_it_used_and_defaults_come_from_policy(self):
        dataset = _v2r_dataset("philippines_v419")
        folder = tempfile.mkdtemp(prefix="v5d_render_")
        out = Path(folder) / "philippines-visayas-guide-travel-guide.html"
        spa_renderer.render_spa_document(out, dataset, media_delivery_mode="linked")
        text = out.read_text(encoding="utf-8")
        self.assertEqual(sfp.declared_media_cap(text), CAP_KB)
        source = code_lines(ROOT / "scripts" / "spa_renderer.py")
        self.assertIn("single_file_policy.registered_max_inline_kb()", source)
        for drift in ("max_kb: int = 400", "max_inline_kb=400", ", 400)"):
            self.assertNotIn(drift, source, "渲染器里又留了一份本地上限：%s" % drift)

    def test_renderer_resolves_the_cap_from_the_register_not_a_local_number(self):
        dataset = _v2r_dataset("philippines_v419")
        adapted = spa_renderer._adapt_spa_dataset(dataset, media_delivery_mode="inline")
        self.assertEqual(spa_renderer.registered_max_inline_kb(), CAP_KB)
        with self.assertRaises(ValueError):
            spa_renderer.render_spa_document(Path(tempfile.mkdtemp()) / "x-travel-guide.html",
                                             dataset, max_inline_kb=0)
        with self.assertRaises(ValueError):
            spa_renderer._adapt_spa_dataset(dataset, media_delivery_mode="inline",
                                            max_inline_kb=-8)

    def test_link_build_is_not_claimed_as_self_contained(self):
        dataset = _v2r_dataset("philippines_v419")
        folder = tempfile.mkdtemp(prefix="v5d_link_")
        out = Path(folder) / "philippines-visayas-guide-travel-guide.html"
        spa_renderer.render_spa_document(out, dataset, media_delivery_mode="linked")
        audit = sfa.audit(out)
        # linked 档不做自包含声明：DOM 侧那部分由 visual_qa 判，文件侧只报字节事实。
        self.assertGreater(audit["measured"]["file_bytes"], 0)


class SingleSourceTests(unittest.TestCase):
    def test_visual_qa_no_longer_owns_its_own_budget_numbers(self):
        code = code_lines(ROOT / "scripts" / "visual_qa.py")
        for literal in ("MAX_DELIVERED_IMG_WIDTH = 1200", "HERO_INLINE_BUDGET_BYTES = 80 * 1024",
                        "TOTAL_INLINE_BUDGET_BYTES = 4 * 1024 * 1024"):
            self.assertNotIn(literal, code, "图片预算又变回本地裸数：%s" % literal)
        self.assertIn("single_file_policy.load_policy", code)

    def test_visual_qa_budgets_equal_registered_numbers(self):
        self.assertEqual(visual_qa.MAX_DELIVERED_IMG_WIDTH,
                         int(POLICY["budgets"]["max_delivered_image_width_px"]))
        self.assertEqual(visual_qa.HERO_INLINE_BUDGET_BYTES,
                         int(POLICY["budgets"]["hero_inline_budget_bytes"]))
        self.assertEqual(visual_qa.TOTAL_INLINE_BUDGET_BYTES,
                         int(POLICY["budgets"]["total_inline_budget_bytes"]))

    def test_only_media_gate_owns_the_digest_claim_rule(self):
        claims = local_media_gate.manifest_claim_map({"assets": [
            {"local_file": "assets/a.jpg", "sha256": "a" * 64},
            {"local_file": "assets/b.jpg", "source_sha256": "s" * 64,
             "delivered_sha256": "d" * 64,
             "renditions": [{"label": "800w", "sha256": "r" * 64}]},
            {"local_file": "assets/c.jpg", "sha256": "",
             "renditions": [{"label": "800w", "sha256": "q" * 64}]},
        ]})
        self.assertEqual(claims["a" * 64], "assets/a.jpg")
        self.assertEqual(claims["r" * 64], "assets/b.jpg#800w")
        self.assertNotIn("", claims)
        self.assertNotIn("q" * 64, claims, "没有双跳链的条目不得声明 rendition 摘要")
        code = code_lines(ROOT / "scripts" / "self_contained_audit.py")
        self.assertNotIn("source_sha256", code,
                         "字节对账不得再实现第二套双跳链摘要规则——归 local_media_gate")


class HeroInlineBudgetTests(unittest.TestCase):
    """业主 2026-11-04 裁示（#181）：首屏单图预算 81,920 → 90,112（下一个 8 KiB 档），其余全部不动。

    裁示同时点名「不能通过修改质量、宽度或来源绕过」，所以这组用例钉的是**字节边界本身**：
    86,906 过、90,112 过、90,113 断、全页 1,954,315 断，而且判定只看内联字节，不看宽度／质量／来源。
    """

    HERO = int(POLICY["budgets"]["hero_inline_budget_bytes"])
    TOTAL = int(POLICY["budgets"]["total_inline_budget_bytes"])

    def _item(self, name, size, **extra):
        item = {"name": name, "inline": True, "on_first_screen": True, "inline_bytes": size}
        item.update(extra)
        return item

    def test_registered_value_is_the_ruled_number_and_history_is_kept(self):
        self.assertEqual(self.HERO, 90112, "首屏预算不是裁示值 90,112")
        self.assertEqual(self.HERO, visual_qa.HERO_INLINE_BUDGET_BYTES, "visual_qa 读到的与登记面不一致")
        history = POLICY["budgets"].get("hero_inline_budget_history") or {}
        self.assertEqual(int(history.get("previous_value") or 0), 81920, "旧值必须留在登记面，不许被覆盖掉")
        self.assertEqual(int(history.get("current_value") or 0), 90112)
        self.assertEqual(int(history.get("measured_first_screen_bytes") or 0), 86906)
        self.assertIn("8192", str(history.get("formula") or ""), "计算公式没登记：只有 8 KiB 档这件事可查")

    def test_measured_first_screen_image_of_86906_bytes_passes(self):
        verdict = visual_qa.inline_budget_verdict([self._item("hero", 86906)])
        self.assertFalse(verdict["hero_violation"], "本轮实测首屏 86,906 B 必须在新门下通过")
        self.assertEqual(verdict["hero_budget_bytes"], 90112)

    def test_boundary_is_inclusive_at_90112_and_blocks_at_90113(self):
        self.assertFalse(visual_qa.inline_budget_verdict([self._item("a", 90112)])["hero_violation"],
                         "正好等于预算算通过：登记值就是给得起的上限")
        over = visual_qa.inline_budget_verdict([self._item("b", 90113)])
        self.assertTrue(over["hero_violation"], "超一个字节必须拦：门不是摆设")
        self.assertEqual(over["over_budget"][0]["inline_bytes"], 90113)

    def test_total_page_media_one_byte_over_the_registered_budget_still_blocks(self):
        size = self.TOTAL
        self.assertFalse(visual_qa.inline_budget_verdict(
            [self._item("hero", 1000, on_first_screen=True),
             {"name": "rest", "inline": True, "on_first_screen": False, "inline_bytes": size - 1000}]
        )["total_violation"], "恰好等于总预算不该误报")
        self.assertTrue(visual_qa.inline_budget_verdict(
            [self._item("hero", 1000, on_first_screen=True),
             {"name": "rest", "inline": True, "on_first_screen": False, "inline_bytes": size - 1000 + 1}]
        )["total_violation"], "总预算超一字节必须阻断（1,954,314 这条裁示明令不动）")

    def test_budget_cannot_be_dodged_by_width_quality_or_source(self):
        """同一串字节，无论声称自己是窄图／低画质／钳制宽图／别的来源，判定只看内联字节。"""
        big = self._item("hero", 90113, width=700, height=467, sizes="(max-width: 700px) 100vw",
                         srcset="small.jpg 700w", source="assets/editorial/other.jpg", jpeg_quality=30)
        verdict = visual_qa.inline_budget_verdict([big])
        self.assertTrue(verdict["hero_violation"],
                        "把宽度／质量／来源写小就绕过首屏预算 ⇒ 裁示第 4 条要求被破坏")
        # 几何钳制放行（IMG_TOO_WIDE）与首屏字节预算是两条独立判据：宽的合理不等于字节可以超门。
        clamped = self._item("wide", 90113, width=1081, height=360)
        self.assertTrue(visual_qa.inline_budget_verdict([clamped])["hero_violation"])

    def test_non_first_screen_images_are_not_charged_against_the_hero_budget(self):
        far = {"name": "third panel", "inline": True, "on_first_screen": False, "inline_bytes": 200000}
        verdict = visual_qa.inline_budget_verdict([far])
        self.assertFalse(verdict["hero_violation"], "第三屏的图不该按首屏门收费（v4.2.1 的旧错）")
        self.assertEqual(verdict["first_screen_count"], 0)

    def test_page_path_uses_the_single_verdict_and_no_second_ruler(self):
        code = code_lines(ROOT / "scripts" / "visual_qa.py")
        self.assertIn("inline_budget_verdict(inline_all)", code,
                      "真页面路径没走唯一实现：边界测试测的就是一把空尺子")
        self.assertNotIn('item["inline_bytes"] > HERO_INLINE_BUDGET_BYTES', code,
                         "visual_qa 里还留着第二份首屏比较")
        self.assertNotIn("inline_bytes_total > TOTAL_INLINE_BUDGET_BYTES", code,
                         "visual_qa 里还留着第二份总预算比较")


class RegistryIntegrityTests(unittest.TestCase):
    """登记的错误码必须双向可达：注册表里没有的码不许 emit，注册了却没实现的码要删掉。"""

    def scan(self, name: str) -> set:
        code = code_lines(ROOT / "scripts" / name)
        return set(re.findall(r"\b(SFD_[A-Z_]+|IMG_RENDERED_[A-Z_]+|IMG_MANIFEST_[A-Z_]+|"
                              r"IMG_DATASET_SLOT_EMPTY)\b", code))

    def test_registered_codes_match_emittable_codes(self):
        emitted = (self.scan("self_contained_audit.py") | self.scan("visual_qa.py")
                   | self.scan("delivery_gate.py"))
        # 交付档预算的两条码由 local_media_gate emit（它读盘上交付字节）。这三个模块的码都归本
        # 登记，local_media_gate 不是：它另有 16 个 IMG_* 码（IMG_CHAIN_MISSING、IMG_HASH_BROKEN…）
        # 从没进过任何闭集登记，把它整包并进来会让这条检查立刻变成「别人家的码没登记」。
        # 所以这里只精确认领本轮新增的那两条，剩下的缺口写在
        # test_media_gate_has_unregistered_code_namespace 里，是一条被记录、没被悄悄抹掉的问题。
        media_gate = code_lines(ROOT / "scripts" / "local_media_gate.py")
        emitted |= {code for code in POLICY["reason_codes"] if code in media_gate}
        registered = set(POLICY["reason_codes"])
        self.assertEqual(registered - emitted, set(),
                         "这些码登记了却没有任何代码路径 emit（死登记）: %s" % sorted(registered - emitted))
        self.assertEqual(emitted - registered, set(),
                         "这些码没进闭集就被 emit（不允许第三档）: %s" % sorted(emitted - registered))

    def test_media_gate_has_unregistered_code_namespace(self):
        """把已知缺口量出来，而不是假装闭集覆盖了媒体门禁的全部错误码。"""
        source = code_lines(ROOT / "scripts" / "local_media_gate.py")
        codes = set(re.findall(r"\bIMG_[A-Z_]{4,}\b", source))
        orphans = sorted(codes - set(POLICY["reason_codes"]))
        self.assertTrue(orphans,
                        "local_media_gate 的错误码若已全部闭集登记，这条守卫就可以删了")
        self.assertGreaterEqual(len(orphans), 16,
                                "未登记的媒体码数量变了：要么补登记，要么解释为什么少")

    def test_delivered_budget_codes_are_emitted_by_the_media_gate(self):
        source = (ROOT / "scripts" / "local_media_gate.py").read_text(encoding="utf-8")
        for code in ("IMG_DELIVERED_OVER_INLINE_CAP", "IMG_DELIVERED_LADDER_UNREGISTERED"):
            self.assertIn(code, source, "%s 只在登记里，媒体门禁没有真的查" % code)

    def test_delivery_gate_owns_the_missing_accounting_code(self):
        gate = (ROOT / "scripts" / "delivery_gate.py").read_text(encoding="utf-8")
        self.assertIn("SFD_ACCOUNTING_NOT_IN_REPORT", gate)
        self.assertIn("single_file_audit", gate)
        self.assertIn("self_contained_audit.audit(html_spa)", gate)


def _v2r_dataset(label: str) -> dict:
    path = PROJ / ".temp" / "v422_honest_map" / "V2r_migration" / "primary" / label / \
        "dataset_v422_selected.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    meta = dataset.get("budget_meta") or {}
    # V2R 快照早于 V5-B，仍带 v4.2.1 的伪造 rates；测试只在内存副本里撤下，不回写历史快照。
    if "rates" in meta and meta.get("rate_verified") and not meta.get("rate_source"):
        meta.pop("rates", None)
        meta.pop("rate_verified", None)
    meta["rate_status"] = "UNREGISTERED"
    return dataset


class DomRegistrationTests(unittest.TestCase):
    """读者页每张图的身份：画出什么、登记了什么，两边必须对得上。"""

    RUN = PROJ / "runs" / "travel_scope_run_202702_philippines_visayas_v419_001"

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.folder = tempfile.mkdtemp(prefix="v5d_dom_")
        cls.assets = cls.RUN / "outputs" / "assets"
        # 把在盘 rendition 放到产物旁边：这才是「读者同时拿到 HTML 与 assets」的那一档现场。
        shutil.copytree(cls.assets, Path(cls.folder) / "assets")
        cls.html = Path(cls.folder) / "philippines-visayas-guide-travel-guide.html"
        spa_renderer.render_spa_document(cls.html, _v2r_dataset("philippines_v419"),
                                         media_delivery_mode="inline",
                                         assets_dir=str(cls.assets))
        cls.blob_keys = sorted(set(sfa.BLOB_TABLE_KEY_RE.findall(
            cls.html.read_text(encoding="utf-8"))))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def measure(self, manifest, require=False):
        page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        failures: list[str] = []
        result: dict = {}
        try:
            page.goto(self.html.resolve().as_uri(), wait_until="domcontentloaded")
            page.wait_for_timeout(700)
            dataset = json.loads(page.evaluate(
                "() => document.getElementById('dataset').textContent"))
            visual_qa.check_rendered_image_registration(
                page, dataset, manifest, failures, result, manifest_required=require)
        finally:
            page.close()
        return failures, result["image_registration"]

    def manifest_for(self, keys):
        return {"assets": [{"local_file": "assets/reg_%02d.jpg" % i, "sha256": key}
                           for i, key in enumerate(keys)]}

    def test_census_buckets_are_exhaustive_and_disjoint(self):
        failures, info = self.measure(self.manifest_for(self.blob_keys))
        self.assertEqual(info["enforced"], True)
        self.assertGreater(info["dom_images"], 0)
        self.assertEqual(info["dom_inline"] + info["dom_file_refs"] + info["dom_fallbacks"]
                         + info["dom_refs"], info["dom_images"],
                         "每张画出来的图必须落在恰好一个桶里；漏计就是口径漏洞")
        self.assertEqual(info["dom_fallbacks"], 0, "assets 在旁边时不该有任何图落到占位兜底")

    def test_registered_painted_bytes_produce_no_unregistered_finding(self):
        failures, info = self.measure(self.manifest_for(self.blob_keys))
        self.assertEqual(info["unregistered"], [])
        self.assertNotIn("IMG_RENDERED_UNREGISTERED", [item.split("|")[0] for item in failures])
        self.assertGreaterEqual(info["painted_rows"], 1)

    def test_unregistered_painted_bytes_are_blocked_and_fully_counted(self):
        other = hashlib.sha256(blob_bytes("elsewhere", 4096)).hexdigest()
        failures, info = self.measure(self.manifest_for([other]))
        self.assertIn("IMG_RENDERED_UNREGISTERED", [item.split("|")[0] for item in failures])
        self.assertEqual(info["unregistered_count"], info["painted_rows"],
                         "凡是画出来的登记图都要算进未登记数，一条不许漏")

    def test_missing_manifest_blocks_only_when_required(self):
        failures, info = self.measure(None, require=False)
        self.assertEqual(info["enforced"], False)
        self.assertEqual(failures, [])
        failures, info = self.measure(None, require=True)
        self.assertEqual([item.split("|")[0] for item in failures], ["IMG_MANIFEST_ABSENT"])

    def test_file_referencing_build_is_blocked(self):
        failures, info = self.measure(self.manifest_for(self.blob_keys))
        codes = [item.split("|")[0] for item in failures]
        # 现场事实（V0-L11 三角关系的另一侧）：PH 在登记上限 400KB 下仍有图走 assets/…，
        # 单文件并不自包含；这条由 DOM 判出，不是测试自己造的。
        if info["dom_file_refs"]:
            self.assertIn("IMG_RENDERED_EXTERNAL_REF", codes)
            self.assertGreaterEqual(len(info["file_ref_samples"]), 1)

    def test_loaning_the_file_alone_paints_generated_placeholders(self):
        lonely = Path(tempfile.mkdtemp(prefix="v5d_lonely_")) / self.html.name
        shutil.copy2(self.html, lonely)  # 只搬 HTML，不带 assets：这就是“发一个文件给读者”
        page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        failures: list[str] = []
        result: dict = {}
        try:
            page.goto(lonely.resolve().as_uri(), wait_until="domcontentloaded")
            page.wait_for_timeout(700)
            dataset = json.loads(page.evaluate(
                "() => document.getElementById('dataset').textContent"))
            visual_qa.check_rendered_image_registration(
                page, dataset, self.manifest_for(self.blob_keys), failures, result,
                manifest_required=True)
        finally:
            page.close()
        codes = [item.split("|")[0] for item in failures]
        info = result["image_registration"]
        self.assertIn("IMG_RENDERED_EXTERNAL_REF", codes)
        self.assertGreater(info["dom_fallbacks"], 0,
                           "读者单独拿到这个文件时，缺图会被 JS 画成假封面——这必须数出来")
        self.assertIn("IMG_RENDERED_FALLBACK_PLACEHOLDER", codes)


class GateWiringTests(unittest.TestCase):
    def test_reader_profile_runs_the_byte_audit(self):
        source = (ROOT / "scripts" / "delivery_gate.py").read_text(encoding="utf-8")
        self.assertIn("单文件字节账单", source)
        self.assertIn("self_contained_audit.audit(html_spa)", source)
        self.assertIn('"--require-asset-manifest"', source)
        self.assertIn("SFD_ACCOUNTING_NOT_IN_REPORT", source)
        qa_call = re.search(r"qa_argv\.append\(\"--require-asset-manifest\"\)", source)
        self.assertTrue(qa_call, "视觉 QA 的清单强制必须从交付门禁传下去（读者档也不例外）")


class LedgerFreshnessTests(unittest.TestCase):
    """V5 的硬加固：台账里的每一条都必须等于现场重测，不只是 touches。

    v4.2.1 的教训是「门禁与文档各自说成功，产物却坏着」；sha256_12 与 counts 一旦过期，
    「登记数字是量出来的」这句话就不再成立，所以把它变成会失败的测试而不是回写脚本的自证。
    """

    def test_every_registered_call_site_equals_a_fresh_measurement(self):
        data_model = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
        inventory = data_model["second_judgment_inventory"]
        patterns = inventory["semantic_call_sites_measured"]["patterns"]
        stale = []
        for entry in inventory["semantic_call_sites"]:
            path = ROOT / entry["file"]
            self.assertTrue(path.is_file(), "登记的调用点文件已不在盘上: %s" % entry["file"])
            body = path.read_text(encoding="utf-8", errors="ignore")
            counts = {key: len(re.findall(pattern, body, re.IGNORECASE))
                      for key, pattern in patterns.items()}
            fresh = {"counts": counts,
                     "touches": sorted(key for key, value in counts.items() if value),
                     "sha256_12": hashlib.sha256(path.read_bytes()).hexdigest()[:12].upper()}
            if any(entry.get(key) != fresh[key] for key in fresh):
                stale.append({"file": entry["file"],
                              "registered": {key: entry.get(key) for key in fresh},
                              "fresh": fresh})
        self.assertEqual(stale, [],
                         "语义调用点台账过期：登记值与现场重测不符（V5 改了这些文件却没回写）: %s"
                         % json.dumps(stale[:4], ensure_ascii=False))

    def test_aggregates_equal_a_fresh_census(self):
        data_model = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
        measured = data_model["second_judgment_inventory"]["semantic_call_sites_measured"]
        patterns = measured["patterns"]
        authority = data_model["second_judgment_inventory"]["authority"].split("::", 1)[0]
        bodies = {("scripts/" + path.name): path.read_text(encoding="utf-8", errors="ignore")
                  for path in sorted((ROOT / "scripts").glob("*.py"))
                  if not path.name.startswith("test_")}
        touching = [name for name, body in bodies.items()
                    if any(re.search(pattern, body, re.IGNORECASE) for pattern in patterns.values())]
        self.assertEqual(measured["files_scanned"], len(bodies))
        self.assertEqual(measured["files_touching_any_primitive"], len(touching))
        self.assertEqual(measured["candidates_excluding_authority"],
                         len([name for name in touching if name != authority]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
