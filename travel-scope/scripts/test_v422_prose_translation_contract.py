# -*- coding: utf-8 -*-
"""MT-C：翻译表 provenance 强制合同的执行型测试（正反例都要跑真代码，不是文本扫描）。

为什么单独立一个文件：MT-B 之前的 `apply_table` 只查「有没有缺项」，来源面写的是
`(table_raw.get("provenance") ...) or "unlabelled translation table"`——缺失或空值都落到一个
**字符串**上，而 `gen_travel_scope.py:453` 只在 `isinstance(..., dict)` 时才把它并进载荷。
两头各自「合理」，合起来就是：读者页可以带着整套没有出处的英文散文出货，台账一片安静。
本文件把那一类形态逐条钉成阻断项，并钉住「不过就一个字节都不写」。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import translate_prose as tp          # noqa: E402
from test_v421_english_source import _placeholder_english          # noqa: E402

RUN = "travel_scope_run_202701_usa_california_v422_001"
EN_TEXT = "An English rendering that stays faithful to the source cell."


def _dataset() -> dict:
    """最小但真会产出若干 prose fragment 的输入（kind 覆盖 poi_note / practical / worth / day_theme）。"""
    return {
        "country": "美国", "country_en": "United States", "artifact_slug": "probe",
        "routes": [["闭环线", "Loop Route", "旧金山 - 洛杉矶", "14天14晚", "纯自驾 (SUV)",
                    "约 25695 元/人", "推荐走内陆再沿海岸南下。"]],
        "destinations": [["旧金山", "San Francisco", "加州旧金山湾区", "金门大桥/艺术宫", "2天",
                          "1月下旬气温10-15℃偶有海雾", "SFO国际机场入境提车20分钟", "是"]],
        "destination_coverage": [], "itinerary": [], "transport": [], "transport_nodes": [],
        "budget": [["1", "第1天", "洛杉矶提车·I-5内陆北上", 500, 200, 100, 100, 100, 1000]],
        "hotels": [["旧金山", "山景酒店", "Hillview Hotel", "精品", 900, "", "",
                    "37.7,-122.4", "", "", "校园公共区域免费漫步"]],
        "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "practical": [["货币结算与汇率口径", "全美境内消费均以美元(USD)结算。"]],
        "worth_it": [["旧金山", "斯坦福大学", "Stanford University", "砂岩罗曼式学术圣殿",
                      "文化学者、摄影爱好者", "2.5-3小时", "工作日上午光线最佳",
                      "校园公共区域免费漫步", "校园平缓开阔", "verified"]],
        "local_chains": [], "packing": [], "local_knowledge": [], "local_apps": [],
        "source_evidence": [], "editorial_media": [], "section_media": [], "map_targets": {},
    }


def _provenance(dataset_sha: str, status: str = "owner_review_pending") -> dict:
    return {
        "method": "controlled_machine_translation_in_agent_session",
        "engine": "qoder-desktop-agent-session",
        "engine_version": "144f34e3-b83b-4550-99e2-4c2d57583c7b",
        "generated_at": "2026-11-01T12:00:00+08:00",
        "language_direction": "zh-CN->en",
        "glossary": "references/prose-glossary.json",
        "glossary_version": "prose-glossary-0.precheck",
        "source_dataset_sha256": dataset_sha,
        "input_snapshot_sha256": "I" * 64,
        "run_dir": RUN,
        "review_status": status,
    }


def _entry_provenance(cn: str, status: str = "owner_review_pending") -> dict:
    base = _provenance("unused")
    return {
        "method": base["method"], "engine": base["engine"],
        "engine_version": base["engine_version"], "generated_at": base["generated_at"],
        "language_direction": base["language_direction"],
        "glossary_version": base["glossary_version"], "review_status": status,
        "source_fragment_sha256": hashlib.sha256(cn.encode("utf-8")).hexdigest().upper(),
    }


def _table(dataset: dict, *, dataset_sha: str, run: str = RUN, statuses: str = "pending",
           drop: str = "", extra_id: str = "", duplicate_cn: bool = False,
           bad_cn_id: str = "", cjk_id: str = "", engine_drift_id: str = "",
           table_status: str = "owner_review_pending", digest: bool = True) -> dict:
    """造一张合规表，再按参数定点破坏**一项**——每条负测只该撞上自己那条码。"""
    entry_status = "owner_review_pending" if statuses == "pending" else statuses
    fragments = tp.collect_fragments(dataset)
    entries = {}
    for fragment in fragments:
        ident = fragment["id"]
        cn = fragment["cn"]
        if ident == extra_id:
            continue
        # 占位英文要过 MT-D2 第 6 步的结构事实对账（同一份构造口，别处不另写一套回声）；
        # cjk_id 那条是故意留汉字的负例，不补事实。
        english = ("还没翻 中文" if ident == cjk_id
                   else _placeholder_english(cn, dataset, base=EN_TEXT))
        entry = {"id": ident, "cn": cn, "en": english, "kind": fragment["kind"],
                 "addresses": fragment["addresses"],
                 "provenance": _entry_provenance(cn, entry_status)}
        if ident == bad_cn_id:
            entry["cn"] = cn + "（被改过的原文）"
        if ident == engine_drift_id:
            entry["provenance"]["engine"] = "some-other-engine"
        if ident == drop:
            continue
        entries[ident] = entry
        if duplicate_cn and ident:
            twin = "f" + hashlib.sha256(("twin" + cn).encode("utf-8")).hexdigest()[:10]
            entries[twin] = {"id": twin, "cn": cn,
                             "en": _placeholder_english(cn, dataset, base=EN_TEXT),
                             "kind": fragment["kind"],
                             "addresses": fragment["addresses"],
                             "provenance": _entry_provenance(cn, entry_status)}
    if extra_id:
        entries[extra_id] = {"id": extra_id, "cn": "陈旧的一条",
                             "en": _placeholder_english("陈旧的一条", dataset, base=EN_TEXT),
                             "kind": "practical_body", "addresses": ["dataset['practical'][9][1]"],
                             "provenance": _entry_provenance("陈旧的一条", entry_status)}
    table = {"schema_version": tp.contract()["table_shape"]["schema_version_value"],
             "run": run, "provenance": _provenance(dataset_sha, table_status),
             "entries": entries}
    if digest:
        table["table_sha256"] = tp.digest_of_table(table)
    return table


class ContractRegistryClosureTests(unittest.TestCase):
    """登记面与实现必须双向闭合：在册的码要真能发出来，代码里用的码与字段必须在册。"""

    SOURCE = (SCRIPTS / "translate_prose.py").read_text(encoding="utf-8")
    RECON_SOURCE = (SCRIPTS / "prose_reconcile.py").read_text(encoding="utf-8")

    def emitted_codes(self) -> set:
        """三种写法都要算：直接 `{"code": "x"}`、把码名当参数传给 _field_problems 的那批，
        以及 MT-D 用**常量**当码名发出去的那批（`{"code": MIXED_OWNER}`）。

        码名里带数字（sha256），字符类漏掉一位就会把两条在册的码误报成「纸面门」——
        这个正则是判据本身，判据写错比门失效更糟，所以配一条自体检：至少要抓到 20 条码。
        常量批必须先解析常量值再入库：只扫字面量的话，MT-D 的三条码会同时「登记了」又「发不出来」，
        而那正是双向闭合测试要抓的形状。
        """
        import re as _re
        codes = set(_re.findall(r'"code":\s*"([a-z0-9_]+)"', self.SOURCE))
        for _missing, _placeholder in _re.findall(
                r'_field_problems\([^()]*?,\s*"([a-z0-9_]+)",\s*("?"|[a-z0-9_"]*)\)', self.SOURCE):
            for value in (_missing, _placeholder):
                if value and value != '""':
                    codes.add(value.strip('"'))
        constants = dict(_re.findall(r'^([A-Z][A-Z0-9_]*)\s*=\s*"([a-z0-9_]+)"', self.SOURCE,
                                     _re.MULTILINE))
        by_constant = set(_re.findall(r'"code":\s*([A-Z][A-Z0-9_]*)', self.SOURCE))
        undefined = sorted(by_constant - set(constants))
        self.assertEqual(undefined, [],
                         "代码把没定义为小写字面量的常量当码名用了：%s——扫描面会漏掉整条码" % undefined)
        return (codes | {constants[name] for name in by_constant}
                | self.reconciliation_codes())

    def reconciliation_codes(self) -> set:
        """MT-D2 第 6 步之后，门会发**别的模块**造的码（validate_table 调 prose_reconcile 的 finding）。

        扫描面只认 translate_prose.py 的话，这 8 条码既不会被测出「发得出」，也不会被测出「在册」——
        两边都看不见的那种漏，比门失效更难发现。所以这里把对账模块的码并入同一个分母，
        并要求每个码名以字面量出现在它自己的实现里。
        """
        import prose_reconcile as pr
        for code in pr.FINDING_CODES.values():
            self.assertIn('"%s"' % code, self.RECON_SOURCE,
                          "%s 由实现发出却没以字面量出现在 %s" % (code, "prose_reconcile.py"))
        return set(pr.FINDING_CODES.values())

    def test_every_registered_blocking_code_is_emitted_by_the_implementation(self):
        reg = tp.contract()
        emitted = self.emitted_codes()
        orphan = [code for code in reg["blocking_findings"] if code not in emitted]
        self.assertEqual(orphan, [], "登记了却发不出来的阻断码（纸面门）：%s" % orphan)

    def test_every_code_the_implementation_emits_is_registered(self):
        reg = tp.contract()
        unregistered = sorted(self.emitted_codes() - set(reg["blocking_findings"]))
        self.assertEqual(unregistered, [], "代码在发但登记面没有的码：%s" % unregistered)
        self.assertGreaterEqual(len(self.emitted_codes()), 20, "扫描面塌了：只抓到这么点码")

    def test_ledger_numbers_agree_with_the_contract(self):
        """总账（data-model）复述的数字必须与合同、与实测账同值。

        两处各写一个数，先过期的那处就成了「看起来是官方数字」的假账——VERSION.md 与 gate 报告
        在本项目里反复出过这种形状，所以复述面也得有牙。
        """
        policy = json.loads((SCRIPTS.parent / "references" / "data-model.json")
                            .read_bytes().decode("utf-8"))
        blk = policy["prose_translation_contract"]
        frozen = tp.contract()["ownership"]["mt_e_table_length_frozen_at"]
        total = str(frozen["total_entries_required"])
        self.assertIn(total, blk["scope"],
                      "总账 scope 没写冻结表长：下一轮就会有人拿交付面观测当 MT-E 的门限")
        self.assertNotIn("本轮实测 357", blk["scope"],
                         "总账还把 357 写成实测覆盖量——那是 seal-42 交付面观测，不是表长")
        complete = [line for line in blk["owner_hard_boundaries"] if "必须完整" in line]
        self.assertEqual(len(complete), 1, "完整性硬边界应当只有一条")
        self.assertIn(total, complete[0], "硬边界里的完整性数字与冻结表长不是同一个数")
        baseline = SCRIPTS.parents[2] / ".temp" / "v422_honest_map" / "MT1_translation" / \
            "artifacts" / "MTD2_DRIFT_BASELINE.json"
        if not baseline.is_file():
            self.skipTest("漂移基线不在盘上：总账复述的实测数字无从核数")
        doc = json.loads(baseline.read_bytes().decode("utf-8"))
        narrative = blk["mt_d2_status_2026_11_01"]["no_drift_measured"]
        for name in ("california", "philippines"):
            for side in ("input_side", "reader_side"):
                self.assertIn(str(doc["runs"][name][side]["pairs"]), narrative,
                              "%s/%s 的分母没在总账里复述：那「双面量过」就是空话" % (name, side))
            self.assertIn("漂移 %d" % doc["runs"][name]["input_side"]["flagged_pairs"], narrative,
                          "总账复述的漂移数与基线不一致（尺子改过却没重跑就会这样）")

    def test_required_field_lists_are_actually_read_by_the_validator(self):
        reg = tp.contract()
        for key in ("table_provenance_required_fields", "entry_required_fields",
                    "entry_provenance_required_fields"):
            self.assertIn('["%s"]' % key, self.SOURCE, "%s 登记了但没人读：这格合同是纸面的" % key)
        self.assertIn("excluded_keys", self.SOURCE,
                      "摘要自排除的键名没从登记面读＝代码里藏了第二份")

    def test_data_model_registers_the_contract_the_code_actually_reads(self):
        """合同文件不能只住在代码里：总账（data-model）必须指着同一份，且指的就是实现读的那份。"""
        policy = json.loads((SCRIPTS.parent / "references" / "data-model.json")
                            .read_bytes().decode("utf-8"))
        block = policy.get("prose_translation_contract") or {}
        self.assertEqual(block.get("registry"), "references/prose-translation-contract.json",
                         "总账没有登记这份合同：下一轮只会去找 english_gap_verdicts")
        self.assertEqual(Path(block["registry"]).name, tp.CONTRACT_PATH.name,
                         "总账指的文件与实现读的不是同一份")
        for key in ("implemented_by", "verified_by", "scope", "write_discipline", "known_limit"):
            self.assertTrue(str(block.get(key) or "").strip(), "总账登记缺格：%s" % key)
        self.assertEqual(len(block["owner_hard_boundaries"]), 6,
                         "业主 MT-C～MT-G 的硬边界应当逐条在册，一格都不能合成一句")

    def test_digest_field_and_shape_fields_are_registered(self):
        reg = tp.contract()
        self.assertEqual(reg["digest_rule"]["excluded_keys"], ["table_sha256"])
        self.assertEqual(tp.self_digest_keys(), ("table_sha256",))
        for field in reg["table_shape"]["required_top_level_fields"]:
            self.assertIn(field, ("schema_version", "run", "provenance", "entries",
                                  "table_sha256"), "顶层必填字段跑出了实现认识的范围：%s" % field)


class ProvenanceBlockingTests(unittest.TestCase):
    def setUp(self):
        self.data = _dataset()
        self.fragments = tp.collect_fragments(self.data)
        self.assertGreater(len(self.fragments), 4, "夹具太小，负测会因「没有 fragment」假绿")
        self.sha = hashlib.sha256(
            (json.dumps(self.data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).hexdigest().upper()

    def _codes(self, table):
        report = tp.validate_table(self.data, table, run_name=RUN,
                                   source_dataset_sha256=self.sha)
        return {item["code"] for item in report["findings"]}, report

    def test_a_compliant_table_passes(self):
        codes, report = self._codes(_table(self.data, dataset_sha=self.sha))
        self.assertEqual(codes, set(), "合规表应当零阻断，实际：%s" % sorted(codes))
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["fragments"], len(self.fragments))
        self.assertEqual(len(report["entry_records"]), len(self.fragments),
                         "合规表的 entry 数与现算 fragment 数不等：夹具或分母漂了")

    def test_missing_provenance_object_blocks(self):
        table = _table(self.data, dataset_sha=self.sha)
        del table["provenance"]
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("provenance_not_object", codes)
        self.assertIn("missing_top_level_field", codes)

    def test_string_provenance_blocks_this_is_the_original_hole(self):
        """旧实现允许 provenance 是一句话；构建侧只认 dict，于是字符串被静默丢掉。"""
        table = _table(self.data, dataset_sha=self.sha)
        table["provenance"] = "machine translation, see chat"
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("provenance_not_object", codes)

    def test_one_missing_provenance_field_blocks(self):
        table = _table(self.data, dataset_sha=self.sha)
        del table["provenance"]["engine_version"]
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("provenance_missing_fields", codes)

    def test_placeholder_value_in_provenance_blocks(self):
        for placeholder in ("TBD", "待补", "n/a", "xxx", "<填这里>"):
            table = _table(self.data, dataset_sha=self.sha)
            table["provenance"]["engine_version"] = placeholder
            table["table_sha256"] = tp.digest_of_table(table)
            codes, _ = self._codes(table)
            self.assertIn("provenance_placeholder_fields", codes,
                          "占位串 %r 被判成有来源了" % placeholder)

    def test_review_status_must_stay_pending_during_candidate(self):
        """owner_reviewed 也在闭集里，所以牙齿是「当前必须等于哪一格」，不是「像不像合法值」。"""
        table = _table(self.data, dataset_sha=self.sha, table_status="owner_reviewed")
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("review_status_not_allowed", codes)
        for entry in table["entries"].values():
            entry["provenance"]["review_status"] = "owner_reviewed"
        table["provenance"]["review_status"] = "owner_review_pending"
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("review_status_not_allowed", codes, "逐条 review_status 自称已复核却没被拦")

    def test_run_dir_must_match_the_dataset_being_written(self):
        table = _table(self.data, dataset_sha=self.sha, run="travel_scope_run_philippines_x")
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("run_dir_mismatch", codes)

    def test_source_dataset_sha_must_be_the_live_bytes(self):
        table = _table(self.data, dataset_sha="" + "0" * 64)
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("source_dataset_sha256_mismatch", codes)


class EntryShapeTests(unittest.TestCase):
    def setUp(self):
        self.data = _dataset()
        self.fragments = tp.collect_fragments(self.data)
        self.sha = hashlib.sha256(
            (json.dumps(self.data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).hexdigest().upper()

    def _codes(self, table):
        report = tp.validate_table(self.data, table, run_name=RUN,
                                   source_dataset_sha256=self.sha)
        return {item["code"] for item in report["findings"]}, report

    def test_bare_string_entries_are_rejected(self):
        legacy = {"schema_version": tp.contract()["table_shape"]["schema_version_value"],
                  "run": RUN, "provenance": _provenance(self.sha),
                  "entries": {f["id"]: EN_TEXT for f in self.fragments}}
        legacy["table_sha256"] = tp.digest_of_table(legacy)
        codes, _ = self._codes(legacy)
        self.assertIn("entry_shape_not_object", codes)
        self.assertIn("fragment_missing_from_table", codes)

    def test_missing_entry_is_a_blocking_finding(self):
        victim = self.fragments[2]["id"]
        table = _table(self.data, dataset_sha=self.sha, drop=victim)
        table["table_sha256"] = tp.digest_of_table(table)
        codes, report = self._codes(table)
        self.assertIn("fragment_missing_from_table", codes)
        self.assertEqual([item["id"] for item in report["missing"]], [victim])

    def test_stale_entry_is_a_blocking_finding(self):
        stale = "f" + hashlib.sha256(b"gone").hexdigest()[:10]
        table = _table(self.data, dataset_sha=self.sha, extra_id=stale)
        table["table_sha256"] = tp.digest_of_table(table)
        codes, report = self._codes(table)
        self.assertIn("stale_entry_id", codes)
        self.assertEqual(report["stale_ids"], [stale])

    def test_duplicate_original_across_two_ids_blocks(self):
        table = _table(self.data, dataset_sha=self.sha, duplicate_cn=True)
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("duplicate_entry_cn", codes)

    def test_english_that_still_contains_hanzi_blocks(self):
        table = _table(self.data, dataset_sha=self.sha, cjk_id=self.fragments[1]["id"])
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("entry_en_contains_cjk", codes)

    def test_id_and_original_must_agree(self):
        victim = self.fragments[0]["id"]
        table = _table(self.data, dataset_sha=self.sha, bad_cn_id=victim)
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        # 改了原文却没换 id ⇒ 两个码都要发：id 与 cn 互推不上，且与数据集原文不等。
        self.assertIn("entry_id_digest_mismatch", codes)
        self.assertIn("entry_cn_mismatch", codes)

    def test_entry_provenance_must_not_drift_from_the_table(self):
        victim = self.fragments[3]["id"]
        table = _table(self.data, dataset_sha=self.sha, engine_drift_id=victim)
        table["table_sha256"] = tp.digest_of_table(table)
        codes, _ = self._codes(table)
        self.assertIn("entry_provenance_inconsistent_with_table", codes)

    def test_duplicate_entry_key_survives_parsing_only_as_a_finding(self):
        """json.loads 静默保留最后一条重复键 ⇒ 只能在解析前的文本里抓。"""
        table = _table(self.data, dataset_sha=self.sha)
        ident = sorted(table["entries"])[0]
        rows = ['"%s": %s' % (key, json.dumps(value, ensure_ascii=False))
                for key, value in table["entries"].items()]
        rows.append('"%s": %s' % (ident, json.dumps(table["entries"][ident],
                                                    ensure_ascii=False)))
        text = ('{"schema_version": %s, "run": %s, "provenance": %s, "entries": {%s}}'
                % (json.dumps(table["schema_version"]), json.dumps(table["run"]),
                   json.dumps(table["provenance"], ensure_ascii=False), ", ".join(rows)))
        self.assertEqual(tp.duplicate_entry_ids(text), [ident],
                         "重复的 entry 键没被抓到：多余项会隐身")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / RUN
            root.mkdir()
            dataset_path = root / "dataset.json"
            dataset_path.write_bytes(json.dumps(self.data, ensure_ascii=False,
                                                indent=2).encode("utf-8"))
            sha = hashlib.sha256(dataset_path.read_bytes()).hexdigest().upper()
            table_path = root / "table.json"
            table_path.write_bytes(text.encode("utf-8"))
            report = tp.apply_table(root, dataset_path, table_path, write=False)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("duplicate_entry_id", codes)
            self.assertEqual(report["status"], "FAIL")
            before = dataset_path.read_bytes()
            with self.assertRaises(ValueError):
                tp.apply_table(root, dataset_path, table_path, write=True)
            self.assertEqual(dataset_path.read_bytes(), before,
                             "重复键表被拒了却还是动了 dataset 字节")


class DigestSelfExclusionTests(unittest.TestCase):
    def setUp(self):
        self.data = _dataset()
        self.sha = hashlib.sha256(
            (json.dumps(self.data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).hexdigest().upper()

    def test_digest_ignores_the_digest_field_itself(self):
        table = _table(self.data, dataset_sha=self.sha, digest=False)
        first = tp.digest_of_table(table)
        table["table_sha256"] = first
        self.assertEqual(tp.digest_of_table(table), first,
                         "摘要字段参与了自己的摘要：下一轮永远复算不上")
        table["table_sha256"] = "F" * 64
        self.assertEqual(tp.digest_of_table(table), first)

    def test_nested_digest_field_is_also_excluded(self):
        table = _table(self.data, dataset_sha=self.sha, digest=False)
        clean = tp.digest_of_table(table)
        table["provenance"]["table_sha256"] = "A" * 64
        self.assertEqual(tp.digest_of_table(table), clean,
                         "只剔顶层的话，往 provenance 里塞同名字段就能绕过自排除规则")


class WriteDisciplineTests(unittest.TestCase):
    def setUp(self):
        self.data = _dataset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / RUN
        self.root.mkdir(parents=True)
        self.dataset_path = self.root / "dataset.json"
        self.dataset_path.write_bytes((json.dumps(self.data, ensure_ascii=False, indent=2)
                                       + "\n").encode("utf-8"))
        self.sha = hashlib.sha256(self.dataset_path.read_bytes()).hexdigest().upper()

    def test_apply_writes_a_dict_provenance_the_builder_can_consume(self):
        table = _table(self.data, dataset_sha=self.sha)
        table_path = self.root / "table.json"
        table_path.write_bytes(json.dumps(table, ensure_ascii=False, indent=2).encode("utf-8"))
        report = tp.apply_table(self.root, self.dataset_path, table_path, write=True)
        self.assertEqual(report["status"], "PASS", report["findings"][:5])
        raw = self.dataset_path.read_bytes()
        written = json.loads(raw.decode("utf-8"))
        self.assertEqual(report["dataset_after_sha256"],
                         hashlib.sha256(raw).hexdigest().upper())
        self.assertNotEqual(report["dataset_before_sha256"], report["dataset_after_sha256"])
        provenance = written["prose_en_provenance"]
        self.assertIsInstance(provenance, dict,
                              "写进 dataset 的来源必须是对象——gen_travel_scope 只认 dict，"
                              "字符串会被静默丢弃")
        self.assertEqual(provenance["table_sha256"], table["table_sha256"])
        self.assertEqual(provenance["entries"], len(tp.collect_fragments(self.data)))
        self.assertEqual(provenance["provenance"]["review_status"], "owner_review_pending")
        self.assertTrue(written["prose_en"], "整份合规的表却什么都没折进去")

    def test_no_partial_write_on_any_blocking_finding(self):
        before = self.dataset_path.read_bytes()
        victim = tp.collect_fragments(self.data)[1]["id"]
        table = _table(self.data, dataset_sha=self.sha, drop=victim)
        table["table_sha256"] = tp.digest_of_table(table)
        table_path = self.root / "table.json"
        table_path.write_bytes(json.dumps(table, ensure_ascii=False, indent=2).encode("utf-8"))
        with self.assertRaises(ValueError):
            tp.apply_table(self.root, self.dataset_path, table_path, write=True)
        self.assertEqual(self.dataset_path.read_bytes(), before,
                         "有阻断项却动了 dataset 字节：禁部分写盘这条失效")

    def test_written_bytes_are_lf_only_unlike_write_text(self):
        table = _table(self.data, dataset_sha=self.sha)
        table_path = self.root / "table.json"
        table_path.write_bytes(json.dumps(table, ensure_ascii=False, indent=2).encode("utf-8"))
        report = tp.apply_table(self.root, self.dataset_path, table_path, write=True)
        raw = self.dataset_path.read_bytes()
        self.assertEqual(report["crlf_in_written_file"], 0)
        self.assertNotIn(b"\r\n", raw, "合同 write_discipline 要求 LF only")
        if os.name == "nt":
            # 把陷阱本身量出来：同一段文本用 write_text 落到盘上就是 CRLF。
            trap = self.root / "trap.json"
            trap.write_text(raw.decode("utf-8"), encoding="utf-8")
            self.assertIn(b"\r\n", trap.read_bytes(),
                          "Windows 的 write_text 仍在翻换行——所以 bytes-only 不是洁癖")
            self.assertNotEqual(hashlib.sha256(trap.read_bytes()).hexdigest().upper(),
                                hashlib.sha256(raw).hexdigest().upper(),
                                "同一份内容两种哈希：这就是「没人改过却哈希变了」的来源")

    def test_tampered_table_digest_is_caught(self):
        table = _table(self.data, dataset_sha=self.sha)
        table["entries"][tp.collect_fragments(self.data)[0]["id"]]["en"] = "改了译文没重算摘要"
        report = tp.validate_table(self.data, table, run_name=RUN,
                                   source_dataset_sha256=self.sha)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("table_sha256_mismatch", codes)


if __name__ == "__main__":
    unittest.main()
