# -*- coding: utf-8 -*-
"""v4.2.2 ZH-RELEASE-1 · #113 — 读者来源面板的牙齿测试（投影／对账／DOM 三段恒等）。

这一支存在的理由（业主 2026-11-02 裁 Q2-A）：来源面板过去读十列**位置**面、又叠了
`items.slice(0,15)`＋「… N more」的死胡同，于是 CA 174 条、PH 365 条来源记录在读者页面上
根本不存在，统计还印成「0 verified」。门当时说 PASS。

规则（本文件的每条负测都照它写）：「被别的门拦下＝不算证」——所以每一负测都断言
**它点名的那个错误码**出现，并且和同页未篡改的正对照配对（正对照绿＝尺子是活的）。

覆盖：
* `source_projection.project()` 对合成坏行逐个抛出它自己的码（闭集，一条不跳）；
* `reconcile()` 三条腿各断一次；
* `legacy_positional_findings()` 在真实 run 数据上量到的违序事实（与独立表达式互相印证）；
* 真浏览器里：dataset→载荷→DOM 掉一行 ⇒ 对账失败；重新引入 `slice(0,N)` ⇒ 被行数恒等咬住；
  假「0 verified」⇒ 被统计恒等咬住；分组标题数不符 ⇒ 被分组恒等咬住；
* 正式档缺台账＝阻断（不是跳过）。

夹具形状不手写词表值：全部从 references/data-model.json（registry()）取。
"""
from __future__ import annotations

import copy
import json
import pathlib
import re
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
ROOT = SCRIPTS.parent
RUNS = ROOT.parent / "candidate_runs"

from playwright.sync_api import sync_playwright  # noqa: E402

import source_projection as sp  # noqa: E402  (唯一投影判据，本文件不另写一套)
import spa_renderer as sr  # noqa: E402
import visual_qa  # noqa: E402

DEST = "旧金山"
REG = sp.registry()
GOOD_ROW = {
    "destination": DEST, "name": "测试实体一",
    "url": "https://www.example.com/hotel/10001", "source_provider": "www.example.com",
    "evidence_level": REG["levels"][0], "verification_status": REG["statuses"][0],
    "retrieved_at": "2026-10-20", "cross_source_review": "双重验证属实", "notes": "fixture",
}


def row(**over) -> dict:
    """在注册形状上做一次定向破坏：只有被点名的字段是错的，别的都保持合法。"""
    item = dict(GOOD_ROW)
    item.update(over)
    return item


def codes_of(failures) -> list[str]:
    return sorted({str(f).split("|", 1)[0] for f in failures})


def source_meta(count: int = 23, *, statuses=None) -> list[dict]:
    """一份注册形状的来源台账：状态在闭集内轮转，保证投影后分组不止一个。"""
    statuses = statuses or REG["statuses"]
    rows = []
    for index in range(count):
        rows.append(row(name="测试实体%02d" % index,
                        url="https://www.example.com/hotel/%d" % (10000 + index),
                        verification_status=statuses[index % len(statuses)]))
    return rows


def fixture_dataset(*, meta=None, with_meta=True) -> dict:
    count = 23 if meta is None and with_meta else 0
    rows = source_meta(count) if meta is None else meta
    hotels = [[DEST, "测试实体%02d" % i, "Test Entity %02d" % i, "hotel", "", "", "",
               "37.7%02d,-122.4%02d" % (i, i), "", ""] for i in range(23)]
    data = {
        "country": "美国", "artifact_slug": "fixture", "duration_days": 2,
        "routes": [["海岸线", "Coast", "旧金山 → 洛杉矶", "2天", "Car", 1000, ""]],
        "route_budgets": {"海岸线": {"total_cny": 1000}},
        "destinations": [[DEST, "San Francisco"], ["洛杉矶大都会区", "Los Angeles"]],
        "itinerary": [["海岸线", "Day 1", 1, "住宿", "测试实体01", "37.701,-122.401"],
                      ["海岸线", "Day 2", 1, "住宿", "测试实体02", "37.702,-122.402"]],
        "hotels": hotels, "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [], "transport_nodes": [],
        "budget": [["1", "2027-02", "抵达", 500, 200, 100, 100, 100, 1000]],
        "practical": [], "worth_it": [], "local_chains": [], "packing": [],
        "local_knowledge": [], "local_apps": [], "source_evidence": [],
        "editorial_media": [], "section_media": [], "map_targets": {},
    }
    if with_meta:
        data["source_evidence_meta"] = rows
    return data


PAYLOAD_RE = re.compile(r'(<script id="dataset" type="application/json">)(.*?)(</script>)',
                        re.DOTALL)


def read_payload(blob: bytes) -> dict:
    return json.loads(PAYLOAD_RE.search(blob.decode("utf-8")).group(2))


def write_payload(blob: bytes, payload: dict) -> bytes:
    """改载荷必须按渲染器同一套转义写回去，否则页面自己就先坏了（那会被 DS_PARSE 抓走＝不算证）。"""
    text = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    text = text.replace(">", "\\u003e").replace("&", "\\u0026")
    document = blob.decode("utf-8")
    match = PAYLOAD_RE.search(document)
    assert match, "内嵌 dataset 载荷不在了：这个篡改样本无效"
    return (document[:match.start(2)] + text + document[match.end(2):]).encode("utf-8")


def splice(text_before: str, text_after: str, times: int = 1) -> bytes:
    """把 HTML 里内联的 spa-layout.js 换一段：用来重演历史上真实存在过的缺陷形状。

    针子必须**唯一命中**：命中两处就意味着我改的其实不是我要检的那一块（假绿/假红都可能）。
    """
    needle = text_before.encode("utf-8")

    def mutate(html: bytes) -> bytes:
        found = html.count(needle)
        assert found == times, ("针子命中 %d 处，期望 %d 处：%s" % (found, times, text_before))
        return html.replace(needle, text_after.encode("utf-8"))
    return mutate


def render(dataset: dict, *, profile: str = None, mutate=None) -> tuple[pathlib.Path, dict]:
    """渲染成单文件（真渲染器、真档位），返回 (html 路径, 临时目录)。"""
    folder = tempfile.TemporaryDirectory()
    out = pathlib.Path(folder.name) / "fixture-travel-guide.html"
    sr.render_spa_document(out, copy.deepcopy(dataset),
                           reader_profile=profile or sr.formal_reader_profile())
    if mutate:
        out.write_bytes(mutate(out.read_bytes()))
    return out, folder


def gate_page(html_path: pathlib.Path, run_dataset: dict) -> dict:
    """真浏览器跑发布用的那一条检查路径（visual_qa.check_spa_page），不抄近路。"""
    require_engine_or_raise()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            with tempfile.TemporaryDirectory() as shots:
                return visual_qa.check_spa_page(
                    page, html_path, "source-panel", {"width": 1440, "height": 900},
                    pathlib.Path(shots) / "shot.png", run_dataset=run_dataset)
        finally:
            browser.close()


def panel_failures(dataset: dict, *, profile: str = None, mutate=None,
                   run_dataset: dict | None = ...) -> dict:
    """渲染＋检一次；返回 check_spa_page 的整个 result。"""
    run_dataset = dataset if run_dataset is ... else run_dataset
    html_path, folder = render(dataset, profile=profile, mutate=mutate)
    try:
        return gate_page(html_path, run_dataset)
    finally:
        folder.cleanup()


def run_dataset_for(kind: str) -> dict:
    """读真实 run 的 dataset（两地之一）：只读，不改——登记值必须来自量，不来自手打。"""
    matches = sorted((RUNS / kind).glob("*/dataset.json")) if RUNS.is_dir() else []
    if not matches:
        matches = [p for p in RUNS.glob("*/dataset.json") if kind in p.parent.name]
    if not matches:
        raise AssertionError("真实 run dataset 不在盘上（%s）⇒ 本用例不许静默跳过：%s" % (kind, RUNS))
    return json.loads(matches[0].read_bytes().decode("utf-8"))


LAYOUT_JS = ROOT / "assets" / "spa-layout.js"
_ENGINE_ERROR: list[str] = []


def engine_parse_error() -> str:
    """读者引擎在真浏览器里能否解析：这是所有 DOM 用例的**前提**，不是本门要检的判据。

    前提塌了却去断言门的判定，会把「引擎坏了」误报成「门有牙／门焊死」——
    所以这里一次性量出来，让每个 DOM 用例都用同一句可归因的话失败。
    """
    if not _ENGINE_ERROR:
        source = LAYOUT_JS.read_text(encoding="utf-8")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("about:blank")
            verdict = page.evaluate(
                "(s) => { try { new Function(s); return ''; } catch (e) { return String(e).slice(0,160); } }",
                source)
            browser.close()
        _ENGINE_ERROR.append(verdict)
    return _ENGINE_ERROR[0]


def require_engine_or_raise() -> None:
    problem = engine_parse_error()
    if problem:
        raise AssertionError(
            "夹具前提不成立：%s 在 Chromium 里解析不过（%s）⇒ 渲染出来的读者页根本没有 UI，"
            "本用例不去断言来源面板门的判定（引擎坏了不是门的判定）" % (LAYOUT_JS, problem))


class ReaderEnginePremiseTests(unittest.TestCase):
    def test_reader_engine_parses_in_the_browser(self):
        """先把前提钉住：读者引擎语法不过时，这条门先响，别让它伪装成下面十条的「失败」。"""
        self.assertEqual(engine_parse_error(), "", "assets/spa-layout.js 解析失败")


class ProjectionErrorCodeTests(unittest.TestCase):
    """project() 的每个码都要被它自己点名的形状咬住——continue 式容错就是 #113 的成因。"""

    def assert_code(self, record, expected: str, index: int = 0) -> None:
        with self.assertRaises(sp.ProjectionError) as ctx:
            sp.project([record])
        self.assertEqual(ctx.exception.code, expected,
                         "点名 %s 的坏形状却被 %s 拦下＝不算证：%s"
                         % (expected, ctx.exception.code, ctx.exception.detail))
        self.assertEqual(ctx.exception.index, index)

    def test_valid_row_projects_in_order_without_rewriting_text(self):
        rows = source_meta(6)
        projected = sp.project(rows)
        self.assertEqual([r["row_index"] for r in projected], list(range(6)), "投影必须保序零丢弃")
        for src, got in zip(rows, projected):
            self.assertEqual(got["name"], src["name"])
            self.assertEqual(got["url"], src["url"])
        self.assertEqual(len(projected), len(rows))

    def test_non_object_row(self):
        self.assert_code(["a", "b", "c"], "row_not_object")

    def test_missing_field(self):
        missing = {k: v for k, v in GOOD_ROW.items() if k != "retrieved_at"}
        self.assert_code(missing, "missing_field")

    def test_unexpected_field(self):
        self.assert_code(row(evidence_id="evi-0001"), "unexpected_field")

    def test_status_out_of_vocab(self):
        self.assert_code(row(verification_status="definitely_verified"), "status_out_of_vocab")

    def test_level_out_of_vocab(self):
        self.assert_code(row(evidence_level="vibes"), "level_out_of_vocab")

    def test_retrieved_at_not_date(self):
        self.assert_code(row(retrieved_at="2026/10/20 早上"), "retrieved_at_not_date")

    def test_url_not_http(self):
        self.assert_code(row(url="file:///C:/来源.html"), "url_not_http")

    def test_empty_required_field(self):
        self.assert_code(row(name="   "), "empty_field")

    def test_empty_ledger_is_its_own_code(self):
        for empty in ([], None):
            with self.assertRaises(sp.ProjectionError) as ctx:
                sp.project(empty)
            self.assertEqual(ctx.exception.code, "empty_ledger")

    def test_every_documented_code_is_reachable(self):
        """闭集自证：ERROR_CODES 里声明会抛的码，这里必须每个都真抛得出来。"""
        reachable = {"row_not_object": ["x"], "missing_field": {k: v for k, v in GOOD_ROW.items() if k != "notes"},
                     "unexpected_field": row(extra=1), "status_out_of_vocab": row(verification_status="x"),
                     "level_out_of_vocab": row(evidence_level="x"), "url_not_http": row(url="x://y"),
                     "retrieved_at_not_date": row(retrieved_at="x"), "empty_field": row(source_provider=" ")}
        for shape in reachable.values():
            with self.assertRaises(sp.ProjectionError):
                sp.project([shape])
        with self.assertRaises(sp.ProjectionError):
            sp.project([])
        self.assertEqual(set(sp.ERROR_CODES) - set(reachable) - {"empty_ledger"},
                         {"status_label_unregistered", "level_label_unregistered", "registry_missing",
                          "legacy_row_not_list", "legacy_row_too_short", "legacy_id_not_string",
                          "legacy_date_column_not_date"},
                         "码集变了但测试没跟上（新增码必须有形状能抛它，或在本清单里说明它属于注册表面）")

    def test_level_label_unregistered_blocks_registry(self):
        """机器词表不许直接印给读者：等级没有中文显示名就是注册面缺陷。"""
        model = json.loads((ROOT / "references" / "data-model.json").read_bytes().decode("utf-8"))
        model["source_evidence_level_labels"] = {}
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "data-model.json"
            path.write_bytes(json.dumps(model, ensure_ascii=False).encode("utf-8"))
            with self.assertRaises(sp.ProjectionError) as ctx:
                sp.registry(path)
            self.assertEqual(ctx.exception.code, "level_label_unregistered")

    def test_status_label_unregistered_blocks_registry(self):
        """有状态没有中文显示名＝读者面会印 undefined，registry() 必须先拦下来。"""
        model = json.loads((ROOT / "references" / "data-model.json").read_bytes().decode("utf-8"))
        model["source_verification_status_labels"] = {"pending": "待复核"}
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "data-model.json"
            path.write_bytes(json.dumps(model, ensure_ascii=False).encode("utf-8"))
            with self.assertRaises(sp.ProjectionError) as ctx:
                sp.registry(path)
            self.assertEqual(ctx.exception.code, "status_label_unregistered")

    def test_registry_missing_is_fatal_not_a_fallback(self):
        model = json.loads((ROOT / "references" / "data-model.json").read_bytes().decode("utf-8"))
        del model["source_verification_statuses"]
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "data-model.json"
            path.write_bytes(json.dumps(model, ensure_ascii=False).encode("utf-8"))
            with self.assertRaises(sp.ProjectionError) as ctx:
                sp.registry(path)
            self.assertEqual(ctx.exception.code, "registry_missing")


class ReconcileTests(unittest.TestCase):
    def test_three_legs_equal_is_ok(self):
        self.assertTrue(sp.reconcile(dataset_rows=7, projected_rows=7, dom_rows=7)["ok"])

    def test_dataset_to_payload_drop(self):
        report = sp.reconcile(dataset_rows=8, projected_rows=7, dom_rows=7)
        self.assertFalse(report["ok"])
        self.assertIn("count_drift", report["problems"][0])
        self.assertEqual(report["numbers"], {"dataset": 8, "projected": 7, "dom": 7})

    def test_payload_to_dom_drop(self):
        report = sp.reconcile(dataset_rows=8, projected_rows=8, dom_rows=15)
        self.assertFalse(report["ok"])
        self.assertIn("dom=15", report["problems"][0])

    def test_status_bucket_sum_mismatch(self):
        report = sp.reconcile(dataset_rows=4, projected_rows=4, dom_rows=4, status_bucket_total=3)
        self.assertFalse(report["ok"])
        self.assertIn("status_bucket_sum_mismatch", report["problems"][0])

    def test_counts_buckets_are_derived_from_rows(self):
        rows = sp.project(source_meta(9))
        counts = sp.counts(rows)
        self.assertEqual(counts["total"], 9)
        self.assertEqual(sum(counts["by_status"].values()), 9)
        # 9 行按闭集轮转 ⇒ 每个状态各 3 条；这里断言的是「桶和＝总行数」而不是我数出来的数
        self.assertEqual(counts["by_status"][REG["statuses"][0]], 3)
        self.assertEqual(sum(counts["by_level"].values()), 9)


class LegacyPositionalFindingsTests(unittest.TestCase):
    """十列位置面退出读者路径，但它违反注册列序必须被量出来（登记，不拦中文出货）。"""

    def test_synthetic_violations_get_their_own_codes(self):
        columns = list(REG["columns"])
        good = ["evi-0001", "旧金山", "实体", "https://example.com/x", "官方",
                "2026-10-20", "存在", "是", "无", "已核验"]
        findings = sp.legacy_positional_findings([good, 7, ["短"], ["x"] * len(columns)])
        self.assertEqual(findings["rows"], 4)
        self.assertEqual(findings["by_code"]["legacy_row_not_list"], 1, "7 不是列表")
        self.assertEqual(findings["by_code"]["legacy_row_too_short"], 1, '["短"] 列数不足')
        self.assertEqual(findings["by_code"]["legacy_id_not_string"], 0,
                         '["x"]*10 的 id 列是字符串，不得被算成 id 违例')
        self.assertEqual(findings["by_code"]["legacy_date_column_not_date"], 1,
                         '["x"]*10 的 retrieved_at 列不是日期')
        self.assertFalse(findings["clean"])
        self.assertEqual(len(findings["examples"]), 3, "合法行不得进违序样例")
        clean = sp.legacy_positional_findings([good])
        self.assertTrue(clean["clean"], "注册列序内的行不得被报成违序")
        bad_id = list(good)
        bad_id[columns.index("evidence_id")] = 1
        bad_date = list(good)
        bad_date[columns.index("retrieved_at")] = "TripAdvisor / Google Maps"
        measured = sp.legacy_positional_findings([bad_id, bad_date])
        self.assertEqual(measured["by_code"]["legacy_id_not_string"], 1)
        self.assertEqual(measured["by_code"]["legacy_date_column_not_date"], 1)

    def test_real_runs_violate_the_registered_order_and_that_is_measured(self):
        """现场复算：CA 的位置面每一行都在 id 列放了非字符串、在 retrieved_at 列放了非日期。"""
        date_re = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
        columns = list(REG["columns"])
        id_col, date_col = columns.index("evidence_id"), columns.index("retrieved_at")
        data = run_dataset_for("california")
        positional = data.get("source_evidence") or []
        findings = sp.legacy_positional_findings(positional)
        # 独立表达式（不是再调一次实现）与登记面必须给出同一个数
        self.assertEqual(findings["by_code"]["legacy_id_not_string"],
                         sum(1 for r in positional if isinstance(r, list) and not isinstance(r[id_col], str)))
        self.assertEqual(findings["by_code"]["legacy_date_column_not_date"],
                         sum(1 for r in positional if isinstance(r, list) and len(r) >= len(columns)
                             and not date_re.match(str(r[date_col]))))
        self.assertFalse(findings["clean"],
                         "CA 的位置面违序若已被修好，本用例要改成断言它干净，而不是留着当假事实")


class ReaderFaceDomTests(unittest.TestCase):
    """真浏览器：dataset → 载荷 → DOM 三段数量恒等，一条记录都不许静默消失。"""

    @classmethod
    def setUpClass(cls):
        require_engine_or_raise()
        cls.dataset = fixture_dataset()
        cls.result = panel_failures(cls.dataset)
        cls.panel = cls.result["source_panel"]

    def test_positive_control_source_panel_is_reconciled(self):
        """正对照：合法台账的正式页必须过——否则这条门是焊死的红灯。"""
        self.assertEqual(self.panel["reconcile"], {"ok": True, "problems": [],
                                                   "numbers": {"dataset": 23, "projected": 23, "dom": 23}},
                         self.result["failures"])
        self.assertEqual(self.panel["dom_rows"], 23)
        self.assertEqual(self.panel["payload_verified"],
                         sp.counts(sp.project(self.dataset["source_evidence_meta"]))["by_status"][REG["statuses"][0]])
        self.assertEqual(self.panel["dom_stats"]["total"], "23")
        self.assertEqual(codes_of([f for f in self.result["failures"]
                                   if str(f).split("|", 1)[0].startswith(("SPA_SOURCE", "SPA_ZH_FORMAL",
                                                                          "SPA_READER_PROFILE"))]), [])
        # 面板三项检查自己也不能报任何失败（同一套判据，两处都绿）
        fresh: list[str] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                path, folder = render(self.dataset)
                try:
                    page.goto(path.resolve().as_uri(), wait_until="domcontentloaded")
                    page.wait_for_timeout(300)
                    embedded = json.loads(page.evaluate(
                        "() => document.getElementById('dataset').textContent"))
                    state = visual_qa.check_reader_language_profile(page, embedded, fresh, {})
                    visual_qa.check_zh_formal_page(page, embedded, fresh, {})
                    visual_qa.check_source_panel(page, embedded, fresh, {}, profile_state=state,
                                                 run_dataset=self.dataset)
                finally:
                    folder.cleanup()
            finally:
                browser.close()
        self.assertEqual(fresh, [], "正式档证据本身报了失败：%s" % fresh)

    def test_every_row_reaches_the_dom_with_its_identity(self):
        rows = self.panel["dom_groups"]
        self.assertEqual(sum(int(g["rows"]) for g in rows), 23)
        self.assertEqual(sorted(int(g["rows"]) for g in rows), sorted(sp.counts(
            sp.project(self.dataset["source_evidence_meta"]))["by_status"].values()))

    def test_dropping_a_row_between_dataset_and_payload_fails_reconciliation(self):
        def mutate(blob: bytes) -> bytes:
            payload = read_payload(blob)
            dropped = payload["source_records"].pop(7)
            payload["_dropped_for_probe"] = dropped["row_index"]
            return write_payload(blob, payload)

        result = panel_failures(fixture_dataset(), mutate=mutate)
        codes = codes_of(result["failures"])
        self.assertIn("SPA_SOURCE_ROW_COUNT_DRIFT", codes,
                      "掉一行却被别的码拦下＝不算证：%s" % codes)
        drift = [f for f in result["failures"] if f.startswith("SPA_SOURCE_ROW_COUNT_DRIFT")][0]
        self.assertIn("dataset=23", drift)
        self.assertIn("projected=22", drift)
        self.assertIn("dom=22", drift)
        self.assertEqual(result["source_panel"]["reconcile"]["ok"], False)

    def test_slicing_the_group_reintroduces_the_record_drop(self):
        """把当年那把 items.slice(0,15) 装回去：必须被 DOM 行数 vs 载荷行数咬住。

        夹具这一支用 40 条同状态记录，是为了让 15 这个历史上真出现过的上限**确实_cut_得到**
        （分组容量不足 15 时截断不会显形，测试就会变成假绿）。
        """
        dataset = fixture_dataset(meta=source_meta(40, statuses=[REG["statuses"][0]]))
        control = panel_failures(dataset)
        self.assertEqual(control["source_panel"]["dom_rows"], 40, control["failures"])
        before = "items.forEach(r=>body.append(h('div',{'class':'se-row'"
        after = "items.slice(0, 15).forEach(r=>body.append(h('div',{'class':'se-row'"
        result = panel_failures(dataset, mutate=splice(before, after))
        codes = codes_of(result["failures"])
        self.assertIn("SPA_SOURCE_ROW_COUNT_DRIFT", codes,
                      "重新引入截断上限却没被行数恒等拦下＝不算证：%s" % codes)
        panel = result["source_panel"]
        self.assertEqual(panel["dom_rows"], 15, panel["reconcile"])
        self.assertEqual(panel["payload_rows"], 40)
        self.assertEqual(panel["dataset_rows"], 40)
        self.assertIn("SPA_SOURCE_GROUP_BUCKET_WRONG", codes,
                      "整组少掉的行还该被分组恒等看见：%s" % codes)
        self.assertIn("SPA_SOURCE_ROW_IDENTITY_WRONG", codes,
                      "身份集合少了 25 行还该被逐行身份看见：%s" % codes)
        identity = [f for f in result["failures"] if f.startswith("SPA_SOURCE_ROW_IDENTITY_WRONG")][0]
        self.assertIn("投影 40 行、DOM 15 行", identity)
        self.assertIn("SPA_SOURCE_DECLARED_ROWS_LIES", codes,
                      "面板自报 40 行却只渲染 15 行，这条谎也要单独看得见：%s" % codes)

    def test_false_zero_verified_statistic_is_impossible_to_ship(self):
        before = "h('b',{'data-se-count':'verified'},verified.toLocaleString())"
        after = "h('b',{'data-se-count':'verified'},0)"
        result = panel_failures(fixture_dataset(), mutate=splice(before, after))
        codes = codes_of(result["failures"])
        self.assertIn("SPA_SOURCE_STAT_WRONG", codes,
                      "假「0 verified」必须被统计恒等点名，而不是被别的路过：%s" % codes)
        hit = [f for f in result["failures"] if f.startswith("SPA_SOURCE_STAT_WRONG")
               and 'verified' in f][0]
        self.assertIn("页面印 0", hit)
        self.assertEqual(result["source_panel"]["payload_verified"], 8)

    def test_group_summary_must_equal_the_bucket_size(self):
        """分组标题写着 N 条、展开只有 N-1 行：标题数字是读者判断覆盖范围的唯一依据。

        篡改点是「少渲染一行」而不是改标题文本：`h('small',{},items.length+' '+t('items'))`
        这一行在面板之外也出现（资料包分组同款），针子必须唯一命中我要检的那一块。
        """
        before = "items.forEach(r=>body.append(h('div',{'class':'se-row'"
        after = "items.slice(0, Math.max(0, items.length - 1)).forEach(r=>body.append(h('div',{'class':'se-row'"
        dataset = fixture_dataset(meta=source_meta(12, statuses=[REG["statuses"][0], REG["statuses"][1]]))
        control = panel_failures(dataset)
        self.assertEqual(control["source_panel"]["dom_rows"], 12, control["failures"])
        self.assertEqual(codes_of([f for f in control["failures"]
                                   if f.startswith("SPA_SOURCE_GROUP")]), [])
        result = panel_failures(dataset, mutate=splice(before, after))
        codes = codes_of(result["failures"])
        self.assertIn("SPA_SOURCE_GROUP_SUMMARY_WRONG", codes,
                      "分组标题数字撒谎必须被点名：%s" % codes)
        self.assertIn("SPA_SOURCE_GROUP_BUCKET_WRONG", codes,
                      "标题数与分桶数两处都要能看见：%s" % codes)
        wrong = [f for f in result["failures"] if f.startswith("SPA_SOURCE_GROUP_SUMMARY_WRONG")][0]
        self.assertIn("标题写着 '6 项'", wrong, wrong)
        self.assertIn("实际渲染 5 行", wrong, wrong)

    def test_missing_ledger_is_a_failure_on_the_formal_path_not_a_skip(self):
        dataset = fixture_dataset(with_meta=False)
        result = panel_failures(dataset)
        codes = codes_of(result["failures"])
        self.assertIn("SPA_SOURCE_LEDGER_ABSENT", codes,
                      "正式档缺台账必须是阻断，不是跳过：%s" % codes)
        self.assertEqual(result["source_panel"]["ledger_status"], "absent")
        self.assertEqual(result["source_panel"]["payload_rows"], 0)

    def test_absent_ledger_prints_an_explicit_alert_not_an_empty_table(self):
        dataset = fixture_dataset(with_meta=False)
        path, folder = render(dataset)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                try:
                    page.goto(path.resolve().as_uri(), wait_until="domcontentloaded")
                    page.wait_for_timeout(300)
                    alert = page.locator('[data-module="source_evidence"] .src-absent[role="alert"]')
                    self.assertEqual(alert.count(), 1)
                    self.assertIn("source_evidence_meta", alert.inner_text())
                    self.assertEqual(page.locator(".se-row").count(), 0,
                                     "缺失台账却仍渲染表格行＝印空表冒充")
                finally:
                    browser.close()
        finally:
            folder.cleanup()

    def test_projection_failure_is_not_silently_swallowed_by_the_gate(self):
        """台账里混一条未注册形状：构建期就该抛 ProjectionError，而不是少渲染一行后继续出货。"""
        dataset = fixture_dataset(meta=source_meta(6) + [row(evidence_id="evi-0007")])
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder) / "fixture-travel-guide.html"
            with self.assertRaises(sp.ProjectionError) as ctx:
                sr.render_spa_document(out, dataset, reader_profile=sr.formal_reader_profile())
            self.assertEqual(ctx.exception.code, "unexpected_field")
            self.assertFalse(out.exists(), "抛了异常还不许留下半份产物")


if __name__ == "__main__":
    unittest.main(verbosity=2)
