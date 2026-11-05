# -*- coding: utf-8 -*-
"""v4.2.2 V6-W：英文缺口归因必须是被量出来的，不是被猜出来的。

业主 V6-R 第 5 条要在地图收口后继续处理英文内容缺口，且不许借此放宽英文门。这一轮的缺陷不在
门禁而在**归因**：v4.2.1 起的兜底分支把「登记表没覆盖这一列」一律写成「字符串在 spa-layout.js 里，
不在数据集里」，而那句话从来没被验证过。2026-10-31 对两棵候选逐条回查：被这样标出的 213 条
（加州 204 / 菲律宾 9）全部是数据集里的真实单元格，`assets/spa-layout.js` 里一条都没有。照着旧数字
去改渲染层 I18N，一条缺口也清不掉。

本文件钉住四件事：
  1. 数据里有、RENDERED_COLUMNS 没登记 ⇒ dataset_cell_unregistered，并给出真实地址；
  2. renderer_literal 只有在渲染层文件字节里真量到才允许出现，且带 in_layout_js 实测；
  3. 两边都量不到 ⇒ unattributed（承认口径有洞），不许冒充任一侧的缺陷；
  4. 判定词表与 references/data-model.json::english_gap_verdicts 双向闭合，被撤回的假文案
     不许在发布树里再出现一份。
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent

import translate_prose as tp        # noqa: E402


POLICY = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
REGISTRY = POLICY["english_gap_verdicts"]


def fixture() -> dict:
    """一份最小但形状真实的 dataset：登记的列与没登记的列各留几句。"""
    return {
        "country": "测试国",
        # worth_it[0][3] 在 RENDERED_COLUMNS 里（worth_desc）——这是「可 --apply」的那一面
        "worth_it": [["id", "名", "坐标", "砂岩罗曼式学术圣殿", "文化学者", "1小时",
                      "平日", "步行进入", "小提示"]],
        # transport_nodes 只登记了 0/3/5 三列：第 4 列这句「数据里有、定位器覆盖不到」，
        # 正是被旧兜底分支误标成渲染层字面量的那一类。
        # 行长必须是 6：references/dataset-shape-alias.json 登记 array_arity=6（CA 实测 11 行全是 6 格），
        # 少一格就撞 array_row_arity_mismatch ⇒ dataset_shape_blocked——MT-D2 之前这份夹具能悄悄跑过，
        # 因为还没有任何东西去核对「位置对应成不成立」；形状别名一登记，不合规的夹具自己就该红。
        "transport_nodes": [["区域", "节点名", "坐标", "航站楼", "综合枢纽", "区域门户节点"]],
        "map_targets": {},
        "budget": [["d1", "日期", "机场大巴 · 市中心"]],
    }


class UnregisteredCellTests(unittest.TestCase):
    def test_cell_present_in_data_but_outside_registry_is_not_a_literal(self):
        rows = {row["cn"]: row for row in tp.locate_gaps(fixture(), ["综合枢纽"])}
        row = rows["综合枢纽"]
        self.assertEqual(row["verdict"], "dataset_cell_unregistered")
        self.assertIn("dataset['transport_nodes'][0][4]", row["addresses"])
        self.assertFalse(row["applicable"], "没登记的列不许谎称 --apply 写得到")
        self.assertNotIn("spa-layout.js", row["fix"], "本条的错处就在数据侧，不该指向渲染层文件")

    def test_registered_column_still_resolves_first(self):
        rows = {row["cn"]: row for row in tp.locate_gaps(fixture(), ["砂岩罗曼式学术圣殿"])}
        self.assertEqual(rows["砂岩罗曼式学术圣殿"]["verdict"], "dataset_cell")
        self.assertEqual(rows["砂岩罗曼式学术圣殿"]["addresses"], ["worth_it[0][3]"])

    def test_renderer_joiner_is_stripped_and_a_registered_cell_is_not_demoted(self):
        """DOM 里带渲染层连接符（| 每日主题）时，先认原文，再按「登记过没有」下结论。

        MT-1 前的期望是 dataset_cell_unregistered：那时剥连接符只用于**定位**，认不出已登记，
        于是加州 14 条 `budget[*][2]`（`assets/spa-layout.js` 的 d-theme 槽写的是 `'| ' + planStr`）
        被记成「列没登记、--apply 写不到」。现在整行的规范化形态命中已登记 fragment 就判
        dataset_cell；仍然禁止把这类行说成渲染层字面量。
        """
        rows = {row["cn"]: row for row in tp.locate_gaps(fixture(), ["| 机场大巴 · 市中心"])}
        row = rows["| 机场大巴 · 市中心"]
        self.assertEqual(row["verdict"], "dataset_cell")
        self.assertEqual(row["matched_form"], "whole_row_normalized")
        self.assertEqual(row["component_coverage"], 1.0)
        self.assertEqual(len(row["component_matches"]), 1)
        self.assertIn("budget[0][2]", row["addresses"][0])
        self.assertNotIn("spa-layout.js", json.dumps(row, ensure_ascii=False),
                         "整行本来就是登记过的数据格，任何文案都不许再把它指向渲染层文件")


class CompositeCoverageTests(unittest.TestCase):
    """业主 REVISE 第 1 条：复合文本只有**全覆盖**才算可 --apply，多义也不算。"""

    def test_half_registered_composite_is_not_marked_applicable(self):
        dataset = fixture()
        rows = {row["cn"]: row for row in tp.locate_gaps(
            dataset, ["砂岩罗曼式学术圣殿 · 综合枢纽"])}
        row = rows["砂岩罗曼式学术圣殿 · 综合枢纽"]
        self.assertEqual(row["verdict"], "render_composite",
                         "「已登记片段 · 未登记片段」若判成 dataset_cell，就是假可翻译计数")
        self.assertFalse(row["applicable"])
        self.assertEqual(row["component_coverage"], 0.5)
        self.assertEqual(row["unresolved_parts"], ["综合枢纽"])
        self.assertEqual([hit["segment"] for hit in row["component_matches"]],
                         ["砂岩罗曼式学术圣殿"])

    def test_fully_covered_composite_is_dataset_cell_with_all_components(self):
        rows = {row["cn"]: row for row in tp.locate_gaps(
            fixture(), ["砂岩罗曼式学术圣殿 · 文化学者"])}
        row = rows["砂岩罗曼式学术圣殿 · 文化学者"]
        self.assertEqual(row["verdict"], "dataset_cell")
        self.assertEqual(row["matched_form"], "complete")
        self.assertEqual(row["component_coverage"], 1.0)
        self.assertEqual([hit["segment"] for hit in row["component_matches"]],
                         ["砂岩罗曼式学术圣殿", "文化学者"])
        self.assertEqual(len(set(row["fragment_ids"])), 2, "两个片段要各自回指自己的 fragment id")

    def test_ambiguous_form_is_not_dataset_cell(self):
        """规范化之后同一形态回指两条不同 fragment ⇒ 歧义，宁可判不下结论，也不许挑一条。

        注意歧义只在**规范化形态**上成立才要拦：整行逐字等于某条已登记文本时，翻译本身是
        确定的（prose_en 按内容键写），那种情况本来就是 dataset_cell，不算歧义。
        """
        dataset = fixture()
        dataset["worth_it"] = [["id", "名", "坐标", "·岩堡圣殿·", "文化学者", "1小时",
                               "平日", "步行进入", "小提示"]]
        dataset["routes"] = [["r1", "线", "c", "m", "起点", "终点", "| 岩堡圣殿 |"]]
        forms = tp.registered_fragment_forms(tp.collect_fragments(dataset))
        self.assertGreater(len(forms.get("岩堡圣殿", [])), 1,
                           "夹具没造出多义形态，本条负测就失去意义")
        self.assertNotIn("岩堡圣殿", {f["cn"] for f in tp.collect_fragments(dataset)},
                         "整行必须不是任何登记原文，否则测的是 exact 分支不是歧义")
        rows = {row["cn"]: row for row in tp.locate_gaps(dataset, ["岩堡圣殿"])}
        row = rows["岩堡圣殿"]
        self.assertNotEqual(row["verdict"], "dataset_cell",
                            "多义必须阻断，不能靠取第一条充数")
        self.assertTrue(row["addresses"] or row["verdict"] in
                        ("dataset_cell_unregistered", "unattributed", "render_composite"),
                        "阻断之后要如实说出它落在哪一类，不许静默消失")

    def test_slash_is_never_a_composite_separator(self):
        """`/` 在地址、路线名、专名里是内容：整行没登记就不许靠拆 `/` 拼出一条 dataset_cell。"""
        dataset = fixture()
        dataset["worth_it"] = [["id", "名", "坐标", "渡轮", "A/B 线", "1小时",
                               "平日", "步行进入", "小提示"]]
        rows = {row["cn"]: row for row in tp.locate_gaps(dataset, ["渡轮 / A/B 线"])}
        row = rows["渡轮 / A/B 线"]
        self.assertNotEqual(row["verdict"], "dataset_cell",
                            "两个半句都登记过也不构成整行可译：DOM 里没有这处渲染组合的证据")



class LayoutLiteralTests(unittest.TestCase):
    def test_literal_verdict_requires_the_file_to_contain_it(self):
        layout = tp.layout_js_text()
        self.assertTrue(layout, "assets/spa-layout.js 读不到就不能宣称任何字面量住在它里面")
        candidate = next((lit for lit in ("每日行程", "沿途影像", "核心体验", "住宿")
                          if lit in layout and lit not in json.dumps(fixture(), ensure_ascii=False)),
                         None)
        self.assertIsNotNone(candidate, "夹具与渲染层文件完全重合，测不出这条分支")
        rows = {row["cn"]: row for row in tp.locate_gaps(fixture(), [candidate])}
        self.assertEqual(rows[candidate]["verdict"], "renderer_literal")
        self.assertTrue(rows[candidate]["in_layout_js"])
        self.assertGreater(rows[candidate]["layout_js_bytes"], 0)

    def test_string_in_neither_face_is_unattributed_not_blamed(self):
        rows = {row["cn"]: row for row in tp.locate_gaps(
            fixture(), ["这句话数据与渲染层都不存在"])}
        row = rows["这句话数据与渲染层都不存在"]
        self.assertEqual(row["verdict"], "unattributed")
        self.assertFalse(row["in_layout_js"])
        self.assertEqual(row["addresses"], [])
        self.assertIn("定位口径有洞", row["fix"])


class ClosureTests(unittest.TestCase):
    def test_verdict_vocabulary_matches_registry_both_ways(self):
        self.assertEqual(list(tp.VERDICTS), REGISTRY["verdicts"])
        self.assertEqual(set(REGISTRY["semantics"]), set(tp.VERDICTS),
                         "登记的解释必须逐条对应代码里的判定，多一条少一条都算漂移")
        self.assertEqual(REGISTRY["implemented_by"], "scripts/translate_prose.py::locate_gaps")

    def test_no_gap_is_silently_dropped(self):
        gaps = ["砂岩罗曼式学术圣殿", "综合枢纽", "| 机场大巴 · 市中心",
                "这句话数据与渲染层都不存在", "", "   "]
        rows = tp.locate_gaps(fixture(), gaps)
        expected = [g.strip() for g in gaps if g.strip()]
        self.assertEqual(len(rows), len(expected), "缺口清单与判定行数必须一一对应")
        self.assertTrue(all(row["verdict"] in tp.VERDICTS for row in rows))

    def test_withdrawn_wording_is_gone_from_the_release_tree(self):
        offender = "字符串在 spa-layout.js 里，不在数据集里"
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.name == Path(__file__).name:
                continue        # 本文件要引用被撤回的文案来钉住它不许回来
            self.assertNotIn(offender, path.read_text(encoding="utf-8", errors="ignore"),
                             "%s 又抄回了那句没量过的断言" % path.name)

    def test_history_snapshot_measured_denominators_are_immutable(self):
        """业主 2026-11-01 裁决：`measured_2026_10_31` 是**有效历史快照**，不许改成 352/9。

        这块数字是「MT-B 三条通道上页面之前」的事实，改它就是把历史改写；要更新现状走
        `current_measurement_ref`。所以这条测试钉的是「旧值一个字都不许动」，
        而不是「旧值等于现状」。
        """
        measured = REGISTRY["measured_2026_10_31"]
        self.assertEqual(measured["california"]["gaps"], 373)
        self.assertEqual(measured["philippines"]["gaps"], 16)
        for name in ("california", "philippines"):
            run = measured[name]
            self.assertEqual(run["renderer_literal"], 0,
                             "加州/菲岛实测没有一条渲染层字面量；若非 0，必须重新量并更新登记")
            self.assertEqual(run["unattributed"], 0)
            self.assertIn("reader_payload", run)
            self.assertIn("audit_dataset", run)
            self.assertEqual(run["reader_payload"]["dataset_cell"]
                             + run["reader_payload"]["dataset_cell_unregistered"], run["gaps"])
            self.assertEqual(run["audit_dataset"]["dataset_cell"]
                             + run["audit_dataset"]["dataset_cell_unregistered"], run["gaps"])

    def test_current_pointer_resolves_and_matches_the_post_fix_measurement(self):
        """现状只认指针指向的那个块：CA 352 / PH 9，且判定分类齐、每面合计等于分母。"""
        pointer = REGISTRY.get("current_measurement_ref") or {}
        block_name = str(pointer.get("block") or "")
        self.assertIn(block_name, REGISTRY,
                      "current_measurement_ref 指向了不存在的块 %r：指针断掉时读者与门禁各读一份数" % block_name)
        current = REGISTRY[block_name]
        self.assertNotEqual(block_name, "measured_2026_10_31",
                            "现状指针指回历史快照＝现状从没登记过")
        self.assertEqual(current["california"]["gaps"], 352)
        self.assertEqual(current["philippines"]["gaps"], 9)
        for name in ("california", "philippines"):
            run = current[name]
            for face in ("reader_payload", "audit_dataset"):
                parts = {key: run[face].get(key, 0) for key in
                         ("dataset_cell", "dataset_cell_unregistered", "proper_name")}
                self.assertEqual(sum(parts.values()), run["gaps"],
                                 "%s/%s 三面判定合计 %d ≠ 分母 %d：判定漏了一条就是静默丢弃"
                                 % (name, face, sum(parts.values()), run["gaps"]))
                self.assertEqual(parts["dataset_cell_unregistered"], 0,
                                 "%s/%s 又出现未登记列：MT-B 把列登记补齐了，回到旧状态就是回归"
                                 % (name, face))
            self.assertEqual(run["renderer_literal"], 0)
            self.assertEqual(run["unattributed"], 0)
        self.assertTrue(pointer.get("why_a_pointer_and_not_an_edit"),
                        "为什么要指针而不是改旧值，必须写在登记面里")

    def test_current_block_file_pointers_are_not_history_files(self):
        """现状块里每一格文件指针都得指本轮，不能指回被它取代的那份证据。

        这块登记值本身可以是对的，指针却指着一份 `registered_matches_measurement=false`
        的历史输出——读者按登记面去找物证，找到的是「对不上」那句话，现状等于没有物证。
        历史文件不是不许提，是必须以 `*_history` 出现并写清为什么成了历史。
        """
        current = REGISTRY[str((REGISTRY.get("current_measurement_ref") or {})
                               .get("block") or "")]
        history_paths = set()
        for key in ("measurement_history", "gap_id_migration_history"):
            for row in current.get(key) or []:
                self.assertTrue(str(row.get("why_it_is_history") or "").strip(),
                                "%s 里 %s 没写为什么它变成了历史" % (key, row.get("path")))
                self.assertTrue(str(row.get("sealed_at") or "").startswith("seal-"),
                                "%s 里 %s 没登记它是哪一封的产物" % (key, row.get("path")))
                history_paths.add(Path(str(row.get("path") or "")).name)
        census = current.get("marker_instance_census") or {}
        for row in census.get("evidence_history") or []:
            self.assertTrue(str(row.get("why_it_is_history") or "").strip(),
                            "普查历史 %s 没写为什么" % row.get("path"))
            history_paths.add(Path(str(row.get("path") or "")).name)
        pointers = {"measurement": current.get("measurement"),
                    "gap_id_migration": current.get("gap_id_migration"),
                    "marker_instance_census.evidence": census.get("evidence")}
        for label, path in pointers.items():
            self.assertTrue(str(path or "").startswith(".temp/"),
                            "现状块的 %s 没指向可复核的证据文件：%r" % (label, path))
            self.assertNotIn(Path(str(path)).name, history_paths,
                             "%s 指的文件同时出现在历史清单里：现状与被它取代的那份混成一格" % label)
        self.assertTrue(str(current.get("measurement_pointer_tooth") or "").strip(),
                        "指针与本轮 --out 必须同名这件事得有牙齿写在登记器里，不能只靠这条测试")

    def test_pending_column_todo_list_is_now_dated_history(self):
        """`columns_to_register_next` 不许再当「下一步」存在：列补完后它只会诱导重复登记。"""
        self.assertNotIn("columns_to_register_next", REGISTRY,
                         "「待登记列」还挂着当下一步＝下一轮会去登记已经登记过的列，造出假翻译工作")
        history = [key for key in REGISTRY if key.startswith("columns_to_register_history_")]
        self.assertEqual(len(history), 1, "历史清单应当是有日期的一块，不是散着的文案")
        block = REGISTRY[history[0]]
        self.assertEqual(block["status"], "COMPLETED_SUPERSEDED")
        self.assertTrue(block["superseded_by"], "历史块必须写明这几列现在登记在哪儿")
        self.assertTrue(block["rows"], "历史行数不能抹掉——那是当初决定补哪些列的实测依据")

    def test_gate_word_points_at_the_registered_verdicts(self):
        """交付门禁里那句「怎么定位」也不许再留二分法（要么地址、要么渲染层）。

        报告文案是业主实际读到的东西：旧文案暗示「拿不到地址的一定在渲染层」，正是本轮撤掉的那个
        假归因的口头版本。这里按文本扫，防止它从代码里回来。
        """
        source = (SCRIPTS / "visual_qa.py").read_text(encoding="utf-8")
        self.assertNotIn("会逐条给出数据集地址或标注为渲染层字面量", source,
                         "视觉门的文案又把判定缩回「地址 or 渲染层」两选一")
        for verdict in tp.VERDICTS:
            self.assertIn(verdict, source, "门禁文案必须点名词表里每一种判定：%s 没提" % verdict)
        self.assertIn("data-model.json::english_gap_verdicts", source,
                      "文案要指回唯一登记面，不要在渲染层里再造一份词表")

    def test_registry_forbids_the_green_the_moves(self):
        banned = " ".join(REGISTRY["must_not_be_closed_by"])
        for phrase in ("改回 renderer_literal", "归零", "删英文态", "删数据行"):
            self.assertIn(phrase, banned, "缺口变绿的错误做法必须逐条写进登记：[%s]" % phrase)


class ExactPriorityAndCollisionTests(unittest.TestCase):
    """业主 REVISE 的两颗窄门牙：精确优先要报碰撞，规范化多义要无条件阻断。"""

    def colliding_dataset(self) -> dict:
        dataset = fixture()
        dataset["worth_it"] = [["id", "名", "坐标", "岩堡圣殿", "文化学者", "1小时",
                                "平日", "步行进入", "小提示"]]
        dataset["routes"] = [["r1", "线", "c", "m", "起点", "终点", "| 岩堡圣殿 |"]]
        return dataset

    def test_export_table_holds_both_the_original_and_the_joiner_form(self):
        fragments = tp.collect_fragments(self.colliding_dataset())
        by_id = {f["id"]: f["cn"] for f in fragments}
        self.assertIn("岩堡圣殿", by_id.values(), "整行原文必须是一条独立条目")
        self.assertIn("| 岩堡圣殿 |", by_id.values(),
                      "带连接符的那格是另一条数据，不能被规范化成同一条后只留一份译文")
        self.assertEqual(len({k for k, v in by_id.items() if v in ("岩堡圣殿", "| 岩堡圣殿 |")}), 2)

    def test_exact_original_reports_normalized_collision_instead_of_hiding_it(self):
        dataset = self.colliding_dataset()
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["岩堡圣殿"])}
        row = rows["岩堡圣殿"]
        self.assertEqual(row["verdict"], "dataset_cell")
        self.assertEqual(row["matched_form"], "exact_original")
        self.assertEqual(len(row["fragment_ids"]), 1)
        self.assertEqual(len(row["normalized_collision_fragment_ids"]), 1,
                         "精确命中可以放行，但另一条同形 fragment 必须点名，不许静默隐藏")
        ids = row["fragment_ids"] + row["normalized_collision_fragment_ids"]
        self.assertEqual(len(set(ids)), 2, "两条都要进同一行的账，--apply 才要两份译文")

    def test_deleting_either_colliding_entry_blocks_apply(self):
        """齐表能写；同形碰撞的两条 entry 少任一条都整表阻断（MT-C 之后按合规表来量）。

        第一版夹具用 `{"entries": {id: "英文串"}}`——MT-C 起那种形态整张表都不合规，
        「齐表应当 PASS」这一步会先炸在 entry_shape_not_object 上，测不到它想测的碰撞语义。
        所以这里造真过合同的表；每次破坏都重算 table_sha256，保证撞到的码就是那一条。
        """
        import tempfile
        import test_v421_english_source as base
        dataset = self.colliding_dataset()
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["岩堡圣殿"])}
        required = (rows["岩堡圣殿"]["fragment_ids"]
                    + rows["岩堡圣殿"]["normalized_collision_fragment_ids"])
        self.assertEqual(len(required), 2, "夹具必须造出两条同形 fragment，否则这条牙是空的")

        def case(drop=None):
            """每个 case 用一棵干净的 temp run：成功 apply 会改 dataset 字节，
            拿它继续测「缺项阻断」就会多撞一条 source_dataset_sha256_mismatch，把判据混掉。"""
            folder = tempfile.TemporaryDirectory()
            root = Path(folder.name)
            ds_path = root / "dataset.json"
            ds_path.write_bytes((json.dumps(dataset, ensure_ascii=False, indent=2) + "\n")
                                .encode("utf-8"))
            sha = hashlib.sha256(ds_path.read_bytes()).hexdigest().upper()
            # 分母是 worklist 而不是「采集到的全部」：MT-D2 之后 transport_nodes 的 [0]/[3]
            # 经形状别名迁到 DISPLAY_NAME／CATEGORY_LEXICON，把它们也写进表就会先撞
            # entry_for_blocked_fragment，测不到本条想测的碰撞语义（同 test_v421_english_source 的口径）。
            table = base._compliant_table(tp.prose_translation_worklist(dataset), sha, root.name,
                                          dataset=dataset)
            if drop:
                del table["entries"][drop]
                table["table_sha256"] = tp.digest_of_table(table)
            table_path = root / "table.json"
            table_path.write_bytes(json.dumps(table, ensure_ascii=False,
                                              indent=2).encode("utf-8"))
            return folder, root, ds_path, table_path

        folder, root, ds_path, table_path = case()
        with folder:
            report = tp.apply_table(root, ds_path, table_path, write=True)
            self.assertEqual(report["status"], "PASS", report["findings"][:3])
            self.assertIn("prose_en", json.loads(ds_path.read_bytes().decode("utf-8")))
        for drop in required:
            with self.subTest(drop=drop):
                folder, root, ds_path, table_path = case(drop=drop)
                with folder:
                    bytes_before = ds_path.read_bytes()
                    dry = tp.apply_table(root, ds_path, table_path, write=False)
                    codes = {item["code"] for item in dry["findings"]}
                    self.assertEqual(codes, {"fragment_missing_from_table"},
                                     "只该撞上缺项这一条码，实际：%s" % sorted(codes))
                    with self.assertRaises(ValueError):
                        tp.apply_table(root, ds_path, table_path, write=True)
                    self.assertEqual(ds_path.read_bytes(), bytes_before,
                                     "阻断必须连字节都不留：半表写盘就是部分应用")

    def test_whole_row_ambiguity_is_not_rescued_by_component_split(self):
        """整行规范化多义 ⇒ 直接 ambiguous，即使拆开后每个组件都能唯一回指。"""
        dataset = fixture()
        # 两条不同的已登记格，剥边后都等于整行 ⇒ 整行级多义；
        # 另配两格让「南屿灯塔」「晨雾观测」各自能唯一回指——用来验证组件全覆盖救不了整行多义。
        dataset["worth_it"] = [["id", "名", "坐标", "·南屿灯塔 · 晨雾观测·", "晨雾观测", "1小时",
                                "平日", "步行进入", "小提示"]]
        dataset["routes"] = [["r1", "线", "c", "m", "起点", "终点", "|南屿灯塔 · 晨雾观测|"]]
        dataset["practical"] = [["南屿灯塔", "正文"]]
        forms = tp.registered_fragment_forms(tp.collect_fragments(dataset))
        components = tp.composite_components("南屿灯塔 · 晨雾观测", forms)
        self.assertGreater(len(forms.get("南屿灯塔 · 晨雾观测", [])), 1,
                           "夹具必须造出整行级多义，否则测不到那条回绿路径")
        self.assertEqual(components["status"], "ambiguous",
                         "整行多义不许靠组件全覆盖重新变绿")
        self.assertEqual([c["segment"] for c in components["components"]], [],
                         "既然阻断，就不该再交出组件级命中当遮羞布")
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["南屿灯塔 · 晨雾观测"])}
        self.assertEqual(rows["南屿灯塔 · 晨雾观测"]["verdict"], "render_composite")
        self.assertFalse(rows["南屿灯塔 · 晨雾观测"]["applicable"])

    def test_slash_is_never_stripped_from_the_ends(self):
        """JOINERS 里再也没有 /：`/中文名/` 不得匹配 `中文名`。"""
        self.assertNotIn("/", tp.JOINERS, "剥边就是把两条不同的数据格合成一条")
        self.assertNotIn("中文名", tp.normalized_forms("/中文名/"))
        dataset = fixture()
        dataset["worth_it"] = [["id", "名", "坐标", "中文名", "文化学者", "1小时",
                                "平日", "步行进入", "小提示"]]
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["/中文名/"])}
        self.assertNotEqual(rows["/中文名/"]["verdict"], "dataset_cell",
                            "/中文名/ 要么是另一条数据，要么定位不到，绝不能冒充 中文名")

class ChannelVerdictTests(unittest.TestCase):
    """MT-B2/B3 之后新增的两档判定：专名走显示面，金额/度量走格式化器，两条都不进翻译表。"""

    def test_money_slot_is_a_formatter_scaffold_not_a_prose_cell(self):
        dataset = fixture()
        dataset["transport"] = [["SFO → 市区", "自驾 (SUV)", "25分钟", "约 50-80 元", "25分钟"]]
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["· 约 50-80 元"])}
        row = rows["· 约 50-80 元"]
        self.assertEqual(row["verdict"], "money_scaffold",
                         "PH 那七条价格的根因是 money() 缺语法，把它们算成 prose 缺口就是错归因")
        self.assertIn("dataset['transport'][0][3]", row["addresses"])
        self.assertFalse(row["applicable"], "--apply 写不到格式化器槽，写了也是让散文表冒充金额规则")
        self.assertTrue(any("money()" in f for f in row["formatter"]), row["formatter"])

    def test_measure_slot_holds_distance_in_another_run_and_stays_scaffold(self):
        """同一个槽 CA 放距离、PH 放价格：判定按**槽位**给，不按字符串形状猜。"""
        dataset = fixture()
        dataset["transport"] = [["旧金山 → 蒙特雷", "自驾 (SUV)", "2小时", "190公里", "2小时"]]
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["· 190公里"])}
        self.assertEqual(rows["· 190公里"]["verdict"], "money_scaffold")
        self.assertFalse(rows["· 190公里"]["applicable"])

    def test_proper_name_resolves_through_the_registered_pair(self):
        dataset = fixture()
        dataset["restaurants"] = [["蒙特雷与卡梅尔", "老渔人码头吉罗伊海鲜",
                                   "Old Fishermans Grotto", "码头海鲜"]]
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["老渔人码头吉罗伊海鲜"])}
        row = rows["老渔人码头吉罗伊海鲜"]
        self.assertEqual(row["verdict"], "proper_name")
        self.assertTrue(row["display_source"].startswith("tier1_dataset_pair"), row["display_source"])
        self.assertFalse(row["applicable"], "专名不许走 prose_en，它有自己的显示面与来源账")

    def test_a_name_without_english_source_is_still_the_display_channels_job(self):
        """同行没有英文格 ≠ 这一列没人认领：它是专名列，等的是带来源的 tier2 显示名。"""
        dataset = fixture()
        dataset["restaurants"] = [["蒙特雷与卡梅尔", "老渔人码头吉罗伊海鲜", "", "码头海鲜"]]
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["老渔人码头吉罗伊海鲜"])}
        row = rows["老渔人码头吉罗伊海鲜"]
        self.assertEqual(row["verdict"], "proper_name")
        self.assertIsNone(row["display_source"], "没有英文来源就不许冒充 tier1")
        self.assertEqual(row["channel_state"], "awaiting_tier2_provenance",
                         "该显式 pending 就 pending，但账要记在正确的负责面上")
        self.assertFalse(row["applicable"])

    def test_colliding_display_names_are_not_reported_as_proper_name(self):
        dataset = fixture()
        dataset["transport_nodes"] = [
            {"name": "圣西蒙海滨游客中心", "name_en": "San Simeon Coastal Visitor Center"},
            {"name": "圣西蒙海滨游客中心", "name_en": "San Simeon Highway 1 Visitor Center"}]
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["圣西蒙海滨游客中心"])}
        row = rows["圣西蒙海滨游客中心"]
        self.assertEqual(row["verdict"], "proper_name", "这一列本来就是专名列，判定要认这个负责面")
        self.assertIsNone(row["display_source"], "两条英文相撞时不许替业主挑一条当来源")
        self.assertEqual(row["channel_state"], "blocked_by_collision",
                         "这是「要人工裁决」，跟「等一个机器显示名」是两件事，混记就等于掩盖")
        self.assertFalse(row["applicable"])

    def test_name_only_column_is_a_proper_name_awaiting_a_source_not_an_orphan(self):
        """transport_nodes[n]['place'] 只有中文名：它归专名显示面管，不是「没人认领的列」。"""
        dataset = fixture()
        dataset["transport_nodes"] = [{"place": "圣西蒙 (大苏尔1号公路)",
                                       "name": "圣西蒙海滨游客中心",
                                       "name_en": "San Simeon Highway 1 Visitor Center",
                                       "type": "海岸枢纽"}]
        rows = {r["cn"]: r for r in tp.locate_gaps(dataset, ["圣西蒙 (大苏尔1号公路)"])}
        row = rows["圣西蒙 (大苏尔1号公路)"]
        self.assertEqual(row["verdict"], "proper_name")
        self.assertIsNone(row["display_source"], "同行没有英文格，就不许谎称 tier1")
        self.assertEqual(row["channel_state"], "awaiting_tier2_provenance",
                         "该说的是「等带来源的显示名」，而不是「这一列没人登记」")
        self.assertFalse(row["applicable"], "业主红线：这一格不许靠 prose_en 或词根拼出一个权威名")

    def test_verdict_registry_covers_both_new_channels(self):
        self.assertEqual(set(tp.VERDICTS), set(REGISTRY["verdicts"]))
        for verdict in ("proper_name", "money_scaffold"):
            self.assertIn(verdict, REGISTRY["semantics"])
            self.assertIn("display-name-channel",
                          json.dumps(REGISTRY["semantics"], ensure_ascii=False))


    def test_object_rows_are_collected_once_a_field_is_registered(self):
        """采集器不再对对象行 `continue`：登记了字段名就该收，收不到就是第二个定位盲区。"""
        original = dict(tp.RENDERED_COLUMNS)
        try:
            tp.RENDERED_COLUMNS["transport_nodes"] = {0: "node_region", "node_note": "node_desc"}
            dataset = fixture()
            dataset["transport_nodes"] = [{"node_note": "北部核心国际航空枢纽"}]
            fragments = {f["cn"]: f for f in tp.collect_fragments(dataset, skip_covered=False)}
            self.assertIn("北部核心国际航空枢纽", fragments)
            self.assertEqual(fragments["北部核心国际航空枢纽"]["addresses"],
                             ["transport_nodes[0]['node_note']"])
        finally:
            tp.RENDERED_COLUMNS.clear()
            tp.RENDERED_COLUMNS.update(original)

    def test_labels_owned_by_other_channels_never_become_prose_fragments(self):
        dataset = fixture()
        dataset["category_en"] = {"综合枢纽": "Integrated Hub"}
        dataset["name_pairs"] = {"老渔人码头吉罗伊海鲜": "Old Fishermans Grotto"}
        dataset["machine_translated_display_name"] = {"圣西蒙 (大苏尔1号公路)": "San Simeon (Hwy 1)"}
        names = tp.renderable_names(dataset)
        for label in ("综合枢纽", "老渔人码头吉罗伊海鲜", "圣西蒙 (大苏尔1号公路)"):
            self.assertIn(label, names,
                          "%s 已由别的通道负责，还给它建一条 prose fragment，就是同一条文本两个来源" % label)


if __name__ == "__main__":
    unittest.main()
