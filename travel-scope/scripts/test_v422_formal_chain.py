# -*- coding: utf-8 -*-
"""v4.2.2 ZH-RELEASE-2 步1 — 来源台账正式链的执行型测试（业主 2026-11-03 裁 finding_1）。

业主给的修复方向是逐字钉死的：真生成器必须从正式输入 dataset 携带 `source_evidence_meta`，
**不得**从十列位置面重新推导，**不得**在缺失时回退空列表；正式链是
`input dataset source_evidence_meta → canonical_dataset → source_projection → source_records → DOM`，
并且要**核对输入 SHA**；正式 run 缺这一面应在**生成阶段**阻断；直调 `render_spa_document()`
仍然只算 smoke。

所以本文件分五层咬，每层都只断言「自己点名那条」：
1. 读取层 `extract_source_ledger_face`：只认 dict 键、None≠[]、并且**结构上碰不到**位置面；
2. 装配层 `assemble_source_ledger_face`：正式构建缺面/空账 ⇒ 抛 `SOURCE_LEDGER_FACE_*`，
   非正式 ⇒ 保持 None（不伪造自证）；
3. 渲染层 `apply_reader_profile`：正式构建不许回退空列表，且自证与手上的机器面对不上就阻断；
4. 门禁层 `delivery_gate`：合同 provenance_gate 登记的**五条腿各一条负测**，正对照必须绿；
5. 现场层：拿加州冻结 dataset 走一遍真函数（读→装配→渲染→门），401 行逐段对上。

规则沿用 #113 那一条：被别的门拦下＝不算证。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import os
import pathlib
import sys
import tempfile
import textwrap
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
ROOT = SCRIPTS.parent
RUNS = ROOT.parent / "candidate_runs"
CA_RUN = RUNS / "travel_scope_run_202701_usa_california_v422_001"

import delivery_gate  # noqa: E402
import gen_travel_scope as gen  # noqa: E402
import reader_payload_scope as rps  # noqa: E402
import source_projection as sp  # noqa: E402
import spa_renderer as sr  # noqa: E402
import visual_qa  # noqa: E402

FORMAL = sr.formal_reader_profile()
FACE_KEY = "source_evidence_meta"
FORMAL_ENV = str(((sr.source_ledger_chain().get("formal_build") or {}).get("env")) or "")
FAKE_SHA = hashlib.sha256(b"not-a-run-input").hexdigest()
# 十列位置面：业主明令读者链不许从它推导（它是生成器内部旧表，不是台账）。
POSITIONAL_FACE = "SOURCE_EVIDENCE"
POSITIONAL_FACE_KEY = "source_evidence"


def positional_face_hits(source: str) -> list:
    """结构扫描一段源码：出现「从位置面取值」的任何手法都记一条。

    认四种：裸标识符、属性、以 `source_evidence` 为键的 get/pop、以它为键的下标。
    注释与 docstring 不参与判断——禁令文档里提到被禁的名字是正当的。
    """
    tree = ast.parse(textwrap.dedent(source))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == POSITIONAL_FACE:
            hits.append("name:%s@%d" % (node.id, node.lineno))
        elif isinstance(node, ast.Attribute) and node.attr == POSITIONAL_FACE:
            hits.append("attr:%s@%d" % (node.attr, node.lineno))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("get", "pop") and node.args \
                and isinstance(node.args[0], ast.Constant) \
                and node.args[0].value == POSITIONAL_FACE_KEY:
            hits.append("key:%s()@%d" % (node.func.attr, node.lineno))
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and node.slice.value == POSITIONAL_FACE_KEY:
            hits.append("key:[]@%d" % node.lineno)
    return hits


def string_keys_read(source: str) -> list:
    """一段源码实际从哪些 dict 键取值（get/pop/下标的字符串常量参数）。"""
    tree = ast.parse(textwrap.dedent(source))
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("get", "pop") and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            keys.append(node.args[0].value)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            keys.append(node.slice.value)
    return keys


def reg() -> dict:
    return sp.registry()


def ledger_rows(count: int = 4) -> list:
    """形状从注册表取，不手写词表值（同 test_v422_source_panel.py 的做法）。"""
    table = reg()
    return [{"destination": "旧金山", "name": "测试实体%02d" % i,
             "url": "https://www.example.com/source/%05d" % i,
             "source_provider": "www.example.com",
             "evidence_level": table["levels"][0],
             "verification_status": table["statuses"][0],
             "retrieved_at": "2026-10-20", "cross_source_review": "双重验证属实",
             "notes": "fixture"} for i in range(count)]


def fixture_dataset(rows=None, *, with_provenance: bool = True, input_sha: str = FAKE_SHA) -> dict:
    """撑起读者骨架的最小载荷：只用于验语言档位与来源链，不验内容完整度。"""
    face = ledger_rows() if rows is None else list(rows)
    data = {
        "country": "美国", "artifact_slug": "fixture", "duration_days": 2,
        "routes": [["海岸线", "旧金山 → 洛杉矶", "2天", "Car", 1000, ""]],
        "route_budgets": {"海岸线": {"total_cny": 1000}},
        "destinations": [["旧金山", "San Francisco"]],
        "itinerary": [["海岸线", "Day 1", 1, "住宿", "测试实体00", "37.700,-122.400"]],
        "hotels": [["旧金山", "测试实体00", "", "hotel", "", "", "", "37.700,-122.400", "", ""]],
        "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [], "transport_nodes": [], "budget": [], "practical": [], "worth_it": [],
        "local_chains": [], "packing": [], "local_knowledge": [], "local_apps": [],
        "editorial_media": [], "section_media": [], "map_targets": {},
        "source_evidence": [], FACE_KEY: face,
    }
    if with_provenance:
        data["source_ledger_meta"] = sp.build_provenance(face, input_sha)
    return data


def write_json(path: pathlib.Path, payload) -> bytes:
    """按本项目纪律写字节（LF、UTF-8、无尾随 CR），并返回写下去的字节。"""
    blob = (json.dumps(payload, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    assert blob.count(b"\r\n") == 0
    path.write_bytes(blob)
    return blob


def render(dataset: dict, *, formal_env: bool = False) -> tuple[pathlib.Path, tempfile.TemporaryDirectory]:
    folder = tempfile.TemporaryDirectory()
    out = pathlib.Path(folder.name) / "fixture-travel-guide.html"
    saved = os.environ.get(FORMAL_ENV)
    try:
        if formal_env:
            os.environ[FORMAL_ENV] = "1"
        else:
            os.environ.pop(FORMAL_ENV, None)
        sr.render_spa_document(out, copy.deepcopy(dataset), reader_profile=FORMAL)
    finally:
        if saved is None:
            os.environ.pop(FORMAL_ENV, None)
        else:
            os.environ[FORMAL_ENV] = saved
    return out, folder


def payload_of(html_path: pathlib.Path) -> dict:
    import re
    text = html_path.read_text(encoding="utf-8")
    match = re.search(r'<script id="dataset" type="application/json">(.*?)</script>', text, re.DOTALL)
    assert match, "产物里没有内嵌读者载荷：这份样本无效"
    return json.loads(match.group(1).replace("\\u003c", "<").replace("\\u003e", ">")
                       .replace("\\u0026", "&"))


class FormalEnv(unittest.TestCase):
    """正式构建身份读合同登记的环境名；判据只有一处实现。"""

    def test_env_name_is_read_from_the_contract(self):
        self.assertEqual(FORMAL_ENV, "TRAVEL_SCOPE_FORMAL_RUN",
                         "合同登记的正式信号名变了 ⇒ 生成器/渲染器/门禁读的就不是同一件事")
        saved = os.environ.get(FORMAL_ENV)
        try:
            os.environ[FORMAL_ENV] = "1"
            self.assertTrue(sr.formal_build_declared())
            os.environ[FORMAL_ENV] = "0"
            self.assertFalse(sr.formal_build_declared())
            os.environ.pop(FORMAL_ENV, None)
            self.assertFalse(sr.formal_build_declared())
        finally:
            if saved is None:
                os.environ.pop(FORMAL_ENV, None)
            else:
                os.environ[FORMAL_ENV] = saved

    def test_contract_block_is_registered(self):
        chain = sr.source_ledger_chain()
        for key in ("chain", "forbidden_fallbacks", "formal_build", "provenance_self_declaration",
                    "smoke_call_rule", "provenance_gate"):
            self.assertIn(key, chain, "合同 source_ledger_chain 缺 %s：门读的名单与实现脱节" % key)
        self.assertEqual(list(chain["provenance_self_declaration"]["fields"]),
                         list(sp.PROVENANCE_FIELDS),
                         "自证字段闭集在合同与实现两侧不一致（多一个少一个都算形状漂移）")
        self.assertEqual(chain["machine_face_key"], FACE_KEY)


class ReadLayerTests(unittest.TestCase):
    """读取层：只认 dataset 的 dict 键，None 与 [] 是两件事，且结构上碰不到位置面。"""

    def test_face_is_carried_verbatim_and_input_is_hashed(self):
        rows = ledger_rows(3)
        payload = {FACE_KEY: rows, "source_evidence": [["x", "y"]]}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        face, digest, path = gen.extract_source_ledger_face(payload, raw, "dataset.json")
        self.assertEqual(face, rows)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(path, "dataset.json")

    def test_absent_face_is_none_not_empty_list(self):
        payload = {"source_evidence": [["x", "y"]]}
        raw = json.dumps(payload).encode("utf-8")
        face, _digest, _path = gen.extract_source_ledger_face(payload, raw, "dataset.json")
        self.assertIsNone(face, "缺失被读成空列表＝把「没有这一面」伪装成「有账但零行」")

    def test_non_list_face_is_rejected_by_name(self):
        payload = {FACE_KEY: {"0": "一行"}}
        with self.assertRaises(ValueError) as caught:
            gen.extract_source_ledger_face(payload, b"{}", "dataset.json")
        self.assertTrue(str(caught.exception).startswith("SOURCE_LEDGER_FACE_NOT_LIST"),
                        str(caught.exception)[:120])

    def test_reader_never_derives_from_the_positional_face(self):
        """「不得从十列位置面重新推导」要能被机器检查，不能只写在注释里。

        这把尺子第一版是文本 `assertNotIn("SOURCE_EVIDENCE", source)`：docstring 里提一个
        被禁的词就误报，而真把读取写成属性/下标反而可能看不见。这里改读 AST——只认
        **结构上的取值**（标识符、属性、以那个键做的 get/pop/下标），注释不参与判断。
        """
        source = inspect.getsource(gen.extract_source_ledger_face)
        self.assertEqual(positional_face_hits(source), [],
                         "读取层里出现了位置面的取值（标识符/属性/键）：这一层开始推倒了")
        self.assertEqual(sorted(set(string_keys_read(source))), [FACE_KEY],
                         "读取层从第二个键取值 ⇒ 「唯一来源」这句话已经不成立")
        # 牙齿：五种取值手法各造一条合成源码，同一把尺子必须逐条点名（不碰真函数）。
        synthetic = (
            "def f(payload, holder):\n"
            "    a = SOURCE_EVIDENCE\n"
            "    b = holder.SOURCE_EVIDENCE\n"
            "    c = payload.get(\"source_evidence\")\n"
            "    d = payload.pop(\"source_evidence\", None)\n"
            "    return payload[\"source_evidence\"][0]\n")
        hits = positional_face_hits(synthetic)
        self.assertEqual(len(hits), 5, hits)
        self.assertEqual(len([h for h in hits if h.startswith("key:")]), 3, hits)
        # 尺子不空转也不误伤：普通字符串常量不算取值，别的面键名不算命中。
        self.assertEqual(positional_face_hits("def g():\n    return \"x\"\n"), [])
        self.assertEqual(positional_face_hits("def h(p):\n    return p.get(%r)\n" % FACE_KEY), [])



class AssemblyLayerTests(unittest.TestCase):
    """装配层：正式构建缺面/空账就在生成阶段停住；非正式不伪造自证。"""

    def setUp(self):
        self.saved = (gen.SOURCE_EVIDENCE_META, gen.RUNTIME_INPUT_SHA256,
                      gen.RUNTIME_INPUT_PATH, gen.DEMO_MODE, os.environ.get(FORMAL_ENV))

    def tearDown(self):
        (gen.SOURCE_EVIDENCE_META, gen.RUNTIME_INPUT_SHA256, gen.RUNTIME_INPUT_PATH,
         gen.DEMO_MODE, saved_env) = self.saved
        if saved_env is None:
            os.environ.pop(FORMAL_ENV, None)
        else:
            os.environ[FORMAL_ENV] = saved_env

    def _set(self, face, digest=FAKE_SHA):
        gen.SOURCE_EVIDENCE_META = face
        gen.RUNTIME_INPUT_SHA256 = digest
        gen.RUNTIME_INPUT_PATH = "dataset.json"
        gen.DEMO_MODE = False

    def _formal(self):
        os.environ[FORMAL_ENV] = "1"

    def test_formal_run_without_face_aborts_at_assembly(self):
        self._set(None)
        self._formal()
        with self.assertRaises(ValueError) as caught:
            gen.assemble_source_ledger_face()
        self.assertTrue(str(caught.exception).startswith("SOURCE_LEDGER_FACE_MISSING"),
                        str(caught.exception)[:160])

    def test_formal_run_with_empty_face_aborts(self):
        self._set([])
        self._formal()
        with self.assertRaises(ValueError) as caught:
            gen.assemble_source_ledger_face()
        self.assertTrue(str(caught.exception).startswith("SOURCE_LEDGER_FACE_EMPTY"),
                        str(caught.exception)[:160])

    def test_non_formal_builds_do_not_fabricate_provenance(self):
        os.environ.pop(FORMAL_ENV, None)
        self._set(None)
        self.assertEqual(gen.assemble_source_ledger_face(), (None, None),
                         "没有输入字节却发出一份自证＝伪造血缘")
        self._set([])
        face, provenance = gen.assemble_source_ledger_face()
        self.assertEqual(face, [])
        self.assertIsNone(provenance, "空账也不能带自证出货：0 行的台账指不出任何来源")

    def test_provenance_matches_the_bytes_loaded(self):
        os.environ.pop(FORMAL_ENV, None)
        rows = ledger_rows(5)
        self._set(rows)
        face, provenance = gen.assemble_source_ledger_face()
        self.assertEqual(face, rows)
        self.assertEqual(provenance, {"dataset_rows": 5, "input_sha256": FAKE_SHA,
                                      "ledger_sha256": sp.ledger_digest(rows)})
        self.assertEqual(sp.provenance_problems(provenance, rows), [])

    def test_provenance_needs_a_real_input_digest(self):
        self._set(ledger_rows(2), digest="")
        with self.assertRaises(sp.ProjectionError) as caught:
            gen.assemble_source_ledger_face()
        self.assertEqual(caught.exception.code, "provenance_input_sha_malformed")

    def test_edited_face_breaks_the_digest_not_the_row_count(self):
        """改一格台账文案：行数还是那些，只有摘要能发现——所以摘要必须进自证。"""
        rows = ledger_rows(3)
        declared = sp.build_provenance(rows, FAKE_SHA)
        moved = [dict(row) for row in rows]
        moved[1]["url"] = "https://www.example.com/source/99999"
        codes = [code for code, _ in sp.provenance_problems(declared, moved)]
        self.assertEqual(codes, ["provenance_digest_mismatch"], codes)


class RenderLayerTests(unittest.TestCase):
    """渲染层：正式构建不许把缺台账渲染成空面板；自证不合就阻断。"""

    def setUp(self):
        self.saved_env = os.environ.get(FORMAL_ENV)

    def tearDown(self):
        if self.saved_env is None:
            os.environ.pop(FORMAL_ENV, None)
        else:
            os.environ[FORMAL_ENV] = self.saved_env

    def test_smoke_page_still_gets_a_registered_absent_face(self):
        os.environ.pop(FORMAL_ENV, None)
        data = fixture_dataset(with_provenance=False)
        data.pop(FACE_KEY)
        projected = sr.apply_reader_profile(data, FORMAL)
        self.assertEqual(projected["source_ledger_status"], "absent")
        self.assertEqual(projected["source_records"], [])
        self.assertNotIn(FACE_KEY, projected, "缺失时不许凭空造一个机器面键")

    def test_formal_build_refuses_to_render_an_empty_ledger(self):
        os.environ[FORMAL_ENV] = "1"
        data = fixture_dataset(with_provenance=False)
        data.pop(FACE_KEY)
        with self.assertRaises(ValueError) as caught:
            sr.apply_reader_profile(data, FORMAL)
        self.assertTrue(str(caught.exception).startswith("SOURCE_LEDGER_FACE_MISSING"),
                        str(caught.exception)[:200])

    def test_formal_build_refuses_a_broken_provenance(self):
        os.environ[FORMAL_ENV] = "1"
        data = fixture_dataset()
        data["source_ledger_meta"]["dataset_rows"] = 99
        with self.assertRaises(ValueError) as caught:
            sr.apply_reader_profile(data, FORMAL)
        self.assertTrue(str(caught.exception).startswith("SOURCE_LEDGER_PROVENANCE_BROKEN"),
                        str(caught.exception)[:200])

    def test_direct_render_without_formal_signal_is_smoke_only(self):
        """业主明令：直调 render_spa_document() 仍只算 smoke——它的产物没有血缘自证。"""
        out, folder = render(fixture_dataset(with_provenance=False))
        try:
            payload = payload_of(out)
            self.assertNotIn("source_ledger_meta", payload)
            self.assertEqual(len(payload["source_records"]), 4, "smoke 页面照样要能对账，只是不成交付证据")
        finally:
            folder.cleanup()

    def test_formal_page_ships_the_self_declaration(self):
        data = fixture_dataset()
        out, folder = render(data, formal_env=True)
        try:
            payload = payload_of(out)
            self.assertEqual(payload["source_ledger_meta"], data["source_ledger_meta"])
            self.assertNotIn(FACE_KEY, payload, "审计机器面留在 run 输入里，不进读者载荷")
            self.assertIn(FACE_KEY, payload["reader_profile_dropped_keys"],
                          "机器面被剔掉却没登记＝静默丢弃（#113 的账法）")
            self.assertEqual(len(payload["source_records"]), 4)
            self.assertEqual(payload["source_ledger_status"], "projected")
        finally:
            folder.cleanup()


class GateLegTests(unittest.TestCase):
    """门禁层：合同登记的五条腿，每条都由自己的码拦下；正对照必须一条都不响。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = pathlib.Path(self.tmp.name)
        self.rows = ledger_rows(4)
        self.dataset_path = self.folder / "dataset.json"
        self.dataset_sha = write_json(self.dataset_path, {FACE_KEY: self.rows,
                                                          "country": "美国"}).decode() and \
            hashlib.sha256(self.dataset_path.read_bytes()).hexdigest()
        self.manifest_path = self.folder / "manifest.json"
        write_json(self.manifest_path, {"seal": {"input_sha256": self.dataset_sha}})

    def tearDown(self):
        self.tmp.cleanup()

    def profiles(self, declared, *, rows_count: int = 4):
        payload = {"reader_profile": FORMAL,
                   "source_records": [{"row_index": i} for i in range(rows_count)]}
        if declared is not None:
            payload["source_ledger_meta"] = declared
        return [{"file": "fixture-travel-guide.html", "payload": payload}]

    def run_gate(self, profiles, *, dataset_path=None, manifest_path=None):
        errors: list[str] = []
        warnings: list[str] = []
        chain = delivery_gate._source_ledger_chain(errors)
        legs = delivery_gate._check_zh_formal_ledger_provenance(
            profiles, errors, warnings, chain,
            dataset_path=str(dataset_path if dataset_path is not None else self.dataset_path),
            run_manifest_path=str(manifest_path if manifest_path is not None else self.manifest_path))
        return errors, warnings, legs

    def codes(self, errors) -> set:
        registered = set((sr.source_ledger_chain()["provenance_gate"]["codes"]).values())
        return {str(item).split("|", 1)[0] for item in errors} & registered

    def test_positive_control_all_legs_agree(self):
        declared = sp.build_provenance(self.rows, self.dataset_sha)
        errors, warnings, legs = self.run_gate(self.profiles(declared))
        self.assertEqual(errors, [], errors[:2])
        self.assertEqual(warnings, [], warnings[:2])
        self.assertEqual(legs, {"dataset_leg": True, "manifest_leg": True, "declared": 1})

    def test_leg_absent(self):
        errors, _w, _l = self.run_gate(self.profiles(None))
        self.assertEqual(self.codes(errors), {"SPA_SOURCE_LEDGER_PROVENANCE_ABSENT"}, errors[:2])

    def test_leg_rows(self):
        declared = sp.build_provenance(self.rows, self.dataset_sha)
        declared["dataset_rows"] = 3
        errors, _w, _l = self.run_gate(self.profiles(declared, rows_count=4))
        self.assertEqual(self.codes(errors), {"SPA_SOURCE_LEDGER_PROVENANCE_ROWS_WRONG"}, errors[:2])

    def test_leg_input_sha(self):
        """换掉 dataset 文件里**与台账无关**的一格：行数与摘要都还对，只有输入 SHA 该响。"""
        declared = sp.build_provenance(self.rows, self.dataset_sha)
        write_json(self.dataset_path, {FACE_KEY: self.rows, "country": "美国改过"})
        errors, _w, _l = self.run_gate(self.profiles(declared))
        self.assertEqual(self.codes(errors), {"SPA_SOURCE_LEDGER_INPUT_SHA_MISMATCH"}, errors[:2])

    def test_leg_ledger_digest(self):
        """改一格台账文案：行数没变、输入 SHA 也重新钉过了，**只有摘要这一条腿**还该响。

        第一版让 SHA 腿替它一起报 ⇒ 按「被别的门拦下＝不算证」这条纪律等于没测。
        """
        declared = sp.build_provenance(self.rows, self.dataset_sha)
        edited = [dict(row) for row in self.rows]
        edited[2]["notes"] = "封存后被改写的文案"
        write_json(self.dataset_path, {FACE_KEY: edited, "country": "美国"})
        edited_sha = hashlib.sha256(self.dataset_path.read_bytes()).hexdigest()
        declared["input_sha256"] = edited_sha                  # 钉到新字节：SHA 腿从此一致
        write_json(self.manifest_path, {"seal": {"input_sha256": edited_sha}})
        self.assertEqual(declared["dataset_rows"], len(edited), "行数必须仍然相同，否则测的是 rows 腿")
        self.assertNotEqual(declared["ledger_sha256"], sp.ledger_digest(edited))
        errors, _w, _l = self.run_gate(self.profiles(declared, rows_count=len(edited)))
        self.assertEqual(self.codes(errors), {"SPA_SOURCE_LEDGER_DIGEST_MISMATCH"}, errors[:2])

    def test_leg_seal_sha(self):
        declared = sp.build_provenance(self.rows, self.dataset_sha)
        write_json(self.manifest_path, {"seal": {"input_sha256": FAKE_SHA}})
        errors, _w, _l = self.run_gate(self.profiles(declared))
        self.assertEqual(self.codes(errors), {"SPA_SOURCE_LEDGER_SEAL_SHA_MISMATCH"}, errors[:2])

    def test_missing_cross_check_inputs_is_a_warning_not_a_silent_pass(self):
        declared = sp.build_provenance(self.rows, self.dataset_sha)
        errors, warnings, legs = self.run_gate(self.profiles(declared),
                                               dataset_path=self.folder / "absent.json",
                                               manifest_path=None)
        self.assertEqual(errors, [], errors[:2])
        self.assertTrue(any(item.startswith("SPA_SOURCE_LEDGER_INPUT_SHA_NOT_CROSS_CHECKED")
                            for item in warnings), warnings[:2])
        self.assertEqual(legs["dataset_leg"], False)

    def test_codes_come_from_the_contract(self):
        """登记被删腿 ⇒ 门报「规则未登记」，而不是按代码里记的名单继续放行。"""
        saved = sr.reader_language_contract
        broken = copy.deepcopy(saved())
        gate = broken["source_ledger_chain"]["provenance_gate"]
        gate["codes"] = {k: v for k, v in gate["codes"].items() if k != "seal_sha"}
        sr.reader_language_contract = lambda: broken
        try:
            errors, _w, legs = self.run_gate(self.profiles(
                sp.build_provenance(self.rows, self.dataset_sha)))
        finally:
            sr.reader_language_contract = saved
        self.assertTrue(any(item.startswith("SPA_SOURCE_LEDGER_PROVENANCE_RULE_UNREGISTERED")
                            for item in errors), errors[:2])
        self.assertEqual(legs, {"legs": "unregistered"})

    def test_every_registered_leg_is_reachable(self):
        """闭集自证：合同登记的每个码都必须被自己的用例打到。"""
        seen = set()
        seen |= self.codes(self.run_gate(self.profiles(None))[0])
        declared = sp.build_provenance(self.rows, self.dataset_sha)
        bad_rows = dict(declared, dataset_rows=3)
        seen |= self.codes(self.run_gate(self.profiles(bad_rows))[0])
        write_json(self.dataset_path, {FACE_KEY: self.rows, "country": "美国改过"})
        seen |= self.codes(self.run_gate(self.profiles(declared))[0])
        write_json(self.dataset_path, {FACE_KEY: self.rows, "country": "美国"})
        edited = [dict(row) for row in self.rows]
        edited[0]["url"] = "https://www.example.com/source/00001"
        write_json(self.dataset_path, {FACE_KEY: edited, "country": "美国"})
        seen |= self.codes(self.run_gate(self.profiles(declared))[0])
        write_json(self.dataset_path, {FACE_KEY: self.rows, "country": "美国"})
        write_json(self.manifest_path, {"seal": {"input_sha256": FAKE_SHA}})
        seen |= self.codes(self.run_gate(self.profiles(declared))[0])
        write_json(self.manifest_path, {"seal": {"input_sha256": self.dataset_sha}})
        want = set(sr.source_ledger_chain()["provenance_gate"]["codes"].values())
        self.assertEqual(seen, want, "有一条登记腿没被咬到：%s" % sorted(want - seen))


class VisualQaMeasurementTests(unittest.TestCase):
    """浏览器侧只做实测：自证存在但与运行 dataset 的机器面对不上就报码；缺失交给交付门判身份。"""

    class StubPage:
        def evaluate(self, script):
            return {"present": False, "dom_rows": 0, "stats": {}, "groups": [],
                    "declared_rows": 0, "indices": [], "uids": []}

    def check(self, payload, run_dataset):
        failures: list[str] = []
        result: dict = {}
        visual_qa.check_source_panel(self.StubPage(), payload, failures, result,
                                     profile_state={"is_formal": True}, run_dataset=run_dataset)
        return failures, result["source_panel"]

    def test_absent_declaration_is_recorded_but_not_judged_here(self):
        failures, entry = self.check({"source_records": [], "source_ledger_status": "absent"},
                                     {FACE_KEY: ledger_rows(2)})
        self.assertFalse(entry["ledger_provenance"]["declared_present"])
        self.assertEqual([item for item in failures
                          if item.startswith("SPA_SOURCE_PROVENANCE_WRONG")], [],
                         "「没有自证」是交付门的身份判定，不该由浏览器门替合同加规则")

    def test_wrong_declaration_is_named(self):
        rows = ledger_rows(2)
        declared = sp.build_provenance(rows, FAKE_SHA)
        declared["ledger_sha256"] = "f" * 64
        failures, entry = self.check({"source_records": [], "source_ledger_status": "projected",
                                      "source_ledger_meta": declared}, {FACE_KEY: rows})
        self.assertTrue([item for item in failures
                         if item.startswith("SPA_SOURCE_PROVENANCE_WRONG")], failures[:2])
        self.assertIn("provenance_digest_mismatch",
                      [item["code"] for item in entry["ledger_provenance"]["problems"]])


class RealRunChainTests(unittest.TestCase):
    """现场层：加州冻结 dataset 走真函数（读→装配→渲染→门），401 行逐段对上。"""

    def dataset_path(self) -> pathlib.Path:
        matches = sorted(CA_RUN.rglob("dataset.json"))
        self.assertTrue(matches, "加州 dataset 不在盘上：%s ⇒ 不许静默跳过" % CA_RUN)
        return matches[0]

    def test_input_dataset_actually_carries_the_face(self):
        path = self.dataset_path()
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        rows = payload.get(FACE_KEY)
        self.assertIsInstance(rows, list, "加州输入的机读台账面不见了")
        self.assertGreater(len(rows), 0)
        face, digest, _path = gen.extract_source_ledger_face(payload, raw, str(path))
        self.assertEqual(len(face), len(rows))
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())

    def test_projection_is_zero_drop_for_the_real_run(self):
        path = self.dataset_path()
        payload = json.loads(path.read_bytes().decode("utf-8"))
        rows = payload[FACE_KEY]
        projected = sp.project(rows)
        self.assertEqual(len(projected), len(rows), "投影丢行＝#113 的罪名")
        self.assertEqual([row["row_index"] for row in projected], list(range(len(rows))))

    def test_full_chain_reconciles_and_passes_the_gate(self):
        path = self.dataset_path()
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        face, digest, _ = gen.extract_source_ledger_face(payload, raw, str(path))
        data = fixture_dataset(rows=face, with_provenance=False, input_sha=digest)
        data["source_ledger_meta"] = sp.build_provenance(face, digest)
        data["itinerary"] = payload.get("itinerary") or data["itinerary"]
        out, folder = render(data, formal_env=True)
        try:
            shipped = payload_of(out)
            self.assertEqual(len(shipped["source_records"]), len(face))
            profiles = [delivery_gate._reader_profile_from_bytes(out)]
            errors: list[str] = []
            warnings: list[str] = []
            chain = delivery_gate._source_ledger_chain(errors)
            manifest = self.folder_manifest(digest)
            legs = delivery_gate._check_zh_formal_ledger_provenance(
                profiles, errors, warnings, chain, dataset_path=str(path),
                run_manifest_path=str(manifest))
            self.assertEqual(errors, [], [item[:160] for item in errors[:3]])
            self.assertEqual(warnings, [], warnings[:2])
            self.assertEqual(legs, {"dataset_leg": True, "manifest_leg": True, "declared": 1})
            self.assertEqual(shipped["source_ledger_meta"]["input_sha256"], digest)
        finally:
            folder.cleanup()

    def folder_manifest(self, digest: str) -> pathlib.Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        manifest = pathlib.Path(folder.name) / "manifest.json"
        write_json(manifest, {"seal": {"input_sha256": digest}})
        return manifest

    def test_gate_names_the_real_run_when_the_dataset_moved(self):
        path = self.dataset_path()
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        face, digest, _ = gen.extract_source_ledger_face(payload, raw, str(path))
        data = fixture_dataset(rows=face, with_provenance=False, input_sha=digest)
        data["source_ledger_meta"] = sp.build_provenance(face, digest)
        out, folder = render(data, formal_env=True)
        try:
            tampered_dir = tempfile.TemporaryDirectory()
            self.addCleanup(tampered_dir.cleanup)
            tampered = pathlib.Path(tampered_dir.name) / "dataset.json"
            moved = json.loads(raw.decode("utf-8"))
            moved[FACE_KEY][0]["url"] = "https://www.example.com/moved"
            write_json(tampered, moved)
            errors: list[str] = []
            warnings: list[str] = []
            delivery_gate._check_zh_formal_ledger_provenance(
                [delivery_gate._reader_profile_from_bytes(out)], errors, warnings,
                delivery_gate._source_ledger_chain(errors), dataset_path=str(tampered),
                run_manifest_path="")
            codes = {str(item).split("|", 1)[0] for item in errors}
            self.assertIn("SPA_SOURCE_LEDGER_INPUT_SHA_MISMATCH", codes, errors[:2])
            self.assertIn("SPA_SOURCE_LEDGER_DIGEST_MISMATCH", codes, errors[:2])
        finally:
            folder.cleanup()


class DeliveryGateHygieneTests(unittest.TestCase):
    """门不许删掉自己声明要读的东西（2026-11-03 实测缺陷的门牙）。

    现场证据：加州正式件 10:37 构建完，`outputs/MEDIA_PREFLIGHT.json` 在盘上；10:49 跑完整套门
    之后它没了，而同一次 delivery_gate 的报告里写着「前置 QA 文件无法读取」。原因是陈旧件清扫的
    保护面手抄了五个参数、漏了 `--preflight`——门在同一趟运行里锯掉了自己的一条腿。
    这里两头都咬：被点名的前置件必须活下来（修好了），没被点名的陈旧件照旧得被清掉（没放宽）。
    """

    def _run_gate(self, workdir: pathlib.Path, preflight: pathlib.Path) -> int:
        import subprocess

        import pyc_hygiene as pyc
        argv = pyc.interpreter([sys.executable, str(SCRIPTS / "delivery_gate.py"),
                                "--output-dir", str(workdir / "outputs"), "--mode", "demo",
                                "--preflight", str(preflight), "--report", str(workdir / "report.json")])
        # 口径走 pyc_hygiene 唯一持有者：手抄 env 会让「跑一次给发布树留 .pyc」这条门牙失明
        proc = subprocess.run(argv, cwd=str(SCRIPTS.parent), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=pyc.env())
        return proc.returncode

    def test_named_preflight_survives_the_stale_sweep(self):
        folder = tempfile.TemporaryDirectory()
        try:
            workdir = pathlib.Path(folder.name)
            out = workdir / "outputs"
            out.mkdir()
            preflight = out / "MEDIA_PREFLIGHT.json"
            preflight.write_bytes(b'{"status": "PASS"}\n')
            for stale in ("local-media-report.json", "media-review.txt"):
                (out / stale).write_bytes(b"leftover\n")
            self._run_gate(workdir, preflight)
            self.assertTrue(preflight.is_file(),
                            "被 --preflight 点名的前置件被清扫删掉了：门读不到自己声明要读的文件")
            self.assertFalse((out / "local-media-report.json").is_file(),
                             "未被点名的陈旧件没被清掉＝保护面被开成了通行证")
            self.assertFalse((out / "media-review.txt").is_file(),
                             "未被点名的陈旧件没被清掉＝保护面被开成了通行证")
        finally:
            folder.cleanup()

    def test_protection_is_measured_from_args_not_from_a_hardcoded_list(self):
        """保护面必须由 args 全量算出：手写清单漏一个参数就是漏一条腿，而漏的那条腿永远只在现场红。"""
        source = (SCRIPTS / "delivery_gate.py").read_text(encoding="utf-8")
        start = source.index("protected_paths = {")
        block = source[start:start + 600]
        self.assertIn("vars(args)", block,
                      "protected_paths 又变回手抄参数了（实测漏 --preflight 就是这么来的）")
        tree = ast.parse(source)
        assigned = [node for node in ast.walk(tree)
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "protected_paths" for t in node.targets)]
        self.assertEqual(len(assigned), 1, "protected_paths 有第二处赋值＝两条规则")


class BuildWindowLedgerTests(unittest.TestCase):
    """ZH-RELEASE-2 步6c：正式构建那一段的零调用账本（把推论变成测量）。

    §11 V4 要四项硬零来自执行期拦截器。此前树里只有门禁自己那一趟审计的窗口和测试窗口的账，
    正式构建那一段没有账 ⇒ 「生成时零 Google 调用」从来没被量过。这里咬四件事：
    smoke 不配拥有这份自证；正式窗口写出的账形状来自合同；文件名／档位不在生成器里出现第二遍；
    合同块缺字段时直接抛（不许悄悄按默认名写一份指不到字节的账）。
    """

    def setUp(self):
        self._state = dict(gen.BUILD_WINDOW_STATE)
        self._input_sha = gen.RUNTIME_INPUT_SHA256
        self._input_path = gen.RUNTIME_INPUT_PATH
        self._env = dict(os.environ)
        self.register = sr.zero_call_build_window()

    def tearDown(self):
        gen.BUILD_WINDOW_STATE.clear()
        gen.BUILD_WINDOW_STATE.update(self._state)
        gen.RUNTIME_INPUT_SHA256 = self._input_sha
        gen.RUNTIME_INPUT_PATH = self._input_path
        os.environ.clear()
        os.environ.update(self._env)

    def _formal_env(self) -> None:
        formal = sr.source_ledger_chain().get("formal_build") or {}
        os.environ[str(formal.get("env"))] = str(formal.get("value") or "1")

    def test_smoke_build_writes_no_build_window_ledger(self):
        """没有正式信号就没有「正式构建窗口」这件事——硬写一份等于伪造证据档位。"""
        os.environ.pop(str((sr.source_ledger_chain().get("formal_build") or {}).get("env")), None)
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder)
            gen.BUILD_WINDOW_STATE.update({"output_dir": str(out), "artifacts": [], "argv": []})
            import zero_call_sentinel
            with zero_call_sentinel.guarded("test-window"):
                pass
            self.assertEqual(gen.emit_build_window_ledger(), {},
                             "smoke 构建写出了 build-window 账本：证据档位是伪造出来的")
            self.assertFalse((out / str(self.register["outputs_relpath"])).exists(),
                             "返回值说是空，盘上却落了账本")

    def test_formal_window_ledger_shape_comes_from_the_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder)
            artifact = out / "usa-california-travel-guide.html"
            artifact.write_bytes(b"<html>probe</html>\n")
            gen.BUILD_WINDOW_STATE.update({"output_dir": str(out), "artifacts": [str(artifact)],
                                           "argv": ["--mode", "live"]})
            gen.RUNTIME_INPUT_SHA256 = "A" * 64
            gen.RUNTIME_INPUT_PATH = str(artifact)
            self._formal_env()
            import zero_call_sentinel
            with zero_call_sentinel.guarded(str(self.register["scope_prefix"])):
                pass
            ledger = gen.emit_build_window_ledger()
            path = out / str(self.register["outputs_relpath"])
            self.assertTrue(path.is_file(), "正式窗口没把账本写到合同点名的位置")
            on_disk = json.loads(path.read_bytes().decode("utf-8"))
            self.assertEqual(on_disk["evidence_tier"], self.register["evidence_tier"])
            self.assertTrue(str(on_disk["scope"]).startswith(self.register["scope_prefix"] + ":"),
                            on_disk.get("scope"))
            for field in self.register["binding_fields"]:
                self.assertIn(field, on_disk, "合同登记的绑定字段没进账本：%s" % field)
            self.assertEqual(on_disk["input_sha256"], "A" * 64,
                             "账本没钉在这段构建真读过的输入字节上")
            self.assertEqual(ledger["counts"]["google_billable_api_calls"], 0)
            self.assertEqual(on_disk["artifacts"][0]["path"].replace("\\", "/"),
                             str(artifact).replace("\\", "/"))

    def test_ledger_shape_is_not_duplicated_inside_the_generator(self):
        """文件名／档位只有一个住处（合同）；生成器里再出现一次就是第二面孔，早晚对不上。"""
        source = (SCRIPTS / "gen_travel_scope.py").read_text(encoding="utf-8")
        for token in (str(self.register["outputs_relpath"]), str(self.register["evidence_tier"])):
            self.assertNotIn('"%s"' % token, source,
                             "生成器里硬写了合同登记的形状：%s" % token)

    def test_contract_block_missing_field_raises(self):
        """登记块缺字段 ⇒ 抛，而不是按默认名写一份账（「缺证据不等于没问题」同一条纪律）。"""
        real = sr.ROOT
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / "references").mkdir()
            stub = {"zero_call_build_window": {"outputs_relpath": "x.json"}}
            (root / "references" / "renderer-contract.json").write_bytes(
                json.dumps(stub, ensure_ascii=False).encode("utf-8"))
            sr.ROOT = root
            try:
                with self.assertRaises(ValueError) as caught:
                    sr.zero_call_build_window()
                self.assertIn("zero_call_build_window", str(caught.exception))
            finally:
                sr.ROOT = real


if __name__ == "__main__":
    unittest.main(verbosity=2)
