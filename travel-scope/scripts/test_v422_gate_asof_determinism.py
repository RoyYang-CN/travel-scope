# -*- coding: utf-8 -*-
"""回归测试的 as-of 必须自己声明：门不能拿墙钟当基准（业主 2026-11-02 授权一次窄改线＋门牙）。

事故形状（2026-11-02 现场抓到，账在
`.temp/v422_honest_map/MT1_translation/artifacts/SEAL52_INTERNAL_SUITE_CURRENCY_BLOCKER.json`）：
`formal_data_gate.audit()` 里 `as_of_date = str(manifest.get("generated_at") or datetime.date.today().isoformat())`，
而 `scripts/test_v412_regressions.py` 把**盘上夹具**（fixtures/thailand_local_apps.json，
`verified_at` 固定 2026-10-02）原样喂进去却没声明 `generated_at` ⇒ 这条回归量的其实是
「今天离核验日几天」。夹具日期 + 31 天越过 30 天上限的那天，树没动、门没错，套件自己变红，
还连带把在子进程里重跑它的 hygiene 条一起拖红。

本文件把这件事钉成三条机械账：
  1. **扫描**（唯一实现 `scan_scripts()`）：凡是调用 formal_data_gate 的 `audit` / app_contract 的
     `validate_local_apps`、且数据集里真带了非空 `local_apps`（或从 `test_formal_data_gate.fixture`
     继承）的测试文件，必须当场声明确定性 as-of——`generated_at` / `as_of_date=` / 重写 `verified_at`
     三选一。引用 provider 文件时**要看那个文件自己合不合规**（跳一层是查，不是盖章）。
  2. **牙**：合成源码逐案证明扫描器咬得住（漏声明 ⇒ 报；补 generated_at ⇒ 不报；只写 `local_apps: []`
     ⇒ 不适用；别人的 `sfa.audit()` ⇒ 不适用；provider 不合规 ⇒ 报），外加盘上真夹具的日期实验：
     as-of 等于核验日 0 错、等于核验日 +31 天必报错。这一半证明「规则不是空转」。
  3. **诚实性**：被扫到的合规声明不能用「挑一个不报错的日期」蒙——`test_v412_regressions.py` 的
     `AS_OF` 必须**等于夹具自己的 `verified_at`**，否则就是把门挪开而不是把基准写清楚。

为什么不去改夹具日期、不去调 30 天上限：改 `verified_at` ＝伪造核验日期；放大上限＝放宽门换绿。
两者本项目都反复拒过。若哪天 `formal_data_gate.py` 撤掉了 `date.today()` 回退（第 100 行附近的
那条表达式），本门的适用面要同步收窄，别留悬空规则——第 `premise_is_still_true` 那条会红，提醒人来改。
"""
from __future__ import annotations

import ast
import datetime
import json
import re
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
FIXTURE = SCRIPTS.parents[0] / "fixtures" / "thailand_local_apps.json"
GATE = SCRIPTS / "formal_data_gate.py"
# as-of 回退表达式：本门成立的前提。它不在了就该收窄规则，而不是让规则悬空地绿着。
AS_OF_FALLBACK = 'as_of_date = str(manifest.get("generated_at") or datetime.date.today().isoformat())'
FRESHNESS_DAYS = 31          # 夹具核验日 + 这么多天必然越过上限（上限是 30 天）
PROVIDER_MODULE = "test_formal_data_gate"

# 三种确定性 as-of 的**字面**形态（扫描用正则，不用 AST：`manifest["generated_at"] = X`、
# `"generated_at": X`、`validate_local_apps(apps, as_of_date="X")`、`a["verified_at"] = today`
# 分属三种写法，AST 化收益低且会把简单形状漏成假绿）。
AS_OF_MARKERS = {
    "generated_at": re.compile(r"generated_at"),
    "as_of_date": re.compile(r"as_of_date\s*="),
    "verified_at_stamp": re.compile(r"\[\s*[\"']verified_at[\"']\s*\]\s*="),
}
# 非空 local_apps 的两种来源：本文件自己写死／从别处赋值进来。空表（`"local_apps": []`）不触发本门。
EMPTY_LOCAL_APPS = re.compile(r"[\"']local_apps[\"']\s*:\s*\[\s*\]")
NONEMPTY_LOCAL_APPS = re.compile(r"[\"']local_apps[\"']\s*[:=]|local_apps\s*=\s*local_apps")


def import_bindings(tree: ast.AST) -> dict:
    """本地名 → (来源模块, 原名)。只认两条线：from X import name / import X。"""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = (alias.name, "")
    return names


def calls_validate_local_apps(tree: ast.AST, names: dict) -> bool:
    """直接调 app_contract.validate_local_apps＝对象本来就是那批 App 记录，没有名字可猜。
    这一支不看 `local_apps` 字样：测试里常把它装进 self.valid_apps 一类变量名，
    按变量名判适用面会漏成真调用点（本仓的 test_app_contract.py 就是这个形状）。
    `import app_contract` 后的点号形式也要认——不然本文件自己就成了规则的盲区。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and names.get(func.id) == ("app_contract", "validate_local_apps"):
            return True
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                and names.get(func.value.id, ("", ""))[0] == "app_contract" \
                and func.attr == "validate_local_apps":
            return True
    return False


def calls_formal_audit(tree: ast.AST, names: dict) -> bool:
    """只数**真调用**：被调名要来自 `formal_data_gate.audit`（含 `import formal_data_gate` 后的点号形式）。
    别处的 `sfa.audit(path)`、方法名里的 `..._for_audit` 都不算——规则一泛化就会误伤整棵树。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and names.get(func.id) == ("formal_data_gate", "audit"):
            return True
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                and names.get(func.value.id, ("", ""))[0] == "formal_data_gate" and func.attr == "audit":
            return True
    return False


def providers_used(tree: ast.AST, names: dict) -> set:
    """`from test_formal_data_gate import fixture` ⇒ 这个文件的 app 证据由 provider 供，得查 provider。"""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == PROVIDER_MODULE:
            out.add(PROVIDER_MODULE)
    return out


def declares_asof(source: str) -> dict:
    return {key: bool(pattern.search(source)) for key, pattern in AS_OF_MARKERS.items()}


def reaches_the_currency_check(source: str, tree: ast.AST, names: dict) -> bool:
    if calls_validate_local_apps(tree, names):
        return True                                   # 直接量 App 记录：没有名字可猜，必须管
    if not calls_formal_audit(tree, names):
        return False
    if providers_used(tree, names):
        return True
    if EMPTY_LOCAL_APPS.search(source) and not NONEMPTY_LOCAL_APPS.search(
            EMPTY_LOCAL_APPS.sub("", source)):
        return False                       # 只塞了个空表：新鲜度门没有对象，本门不适用
    return bool(NONEMPTY_LOCAL_APPS.search(source))


def scan_source(name: str, source: str, index: dict | None = None) -> dict:
    """单文件判定：applicable（要不要管）＋ compliant（管得住管不住）。

    合规＝**自己**声明了三种确定性基准之一，或者证据来自 provider 且 provider 自己合规（逐跳查，
    不是「引用了 provider 就算过」）。
    """
    tree = ast.parse(source)
    names = import_bindings(tree)
    applicable = reaches_the_currency_check(source, tree, names)
    own = declares_asof(source)
    hop = sorted(providers_used(tree, names))
    hop_ok = []
    for provider in hop:
        row = (index or {}).get(provider)
        if row is None:
            provider_source = (SCRIPTS / (provider + ".py")).read_text(encoding="utf-8")
            row = {"own_markers": declares_asof(provider_source)}
        hop_ok.append({"provider": provider, "provider_declares": row["own_markers"],
                       "provider_compliant": any(row["own_markers"].values())})
    compliant = any(own.values()) or (bool(hop_ok) and all(item["provider_compliant"] for item in hop_ok))
    return {"file": name, "applicable": applicable, "compliant": compliant, "own_markers": own,
            "providers": hop_ok}


def scan_scripts(scripts_dir: Path = SCRIPTS) -> list:
    paths = sorted(scripts_dir.glob("test_*.py"))
    sources = {path.name[:-3]: path.read_text(encoding="utf-8", errors="ignore") for path in paths}
    first_pass = {module: scan_source(module + ".py", source) for module, source in sources.items()}
    final = [scan_source(module + ".py", source, first_pass) for module, source in sorted(sources.items())]
    return [row for row in final if row["applicable"]]


def offenders(rows: list) -> list:
    return ["%s（调了门却没声明 as-of）" % row["file"] for row in rows if not row["compliant"]]


def fixture_verified_at() -> str:
    loaded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    apps = loaded["local_apps"] if isinstance(loaded, dict) and "local_apps" in loaded else loaded
    stamps = sorted({str(row.get("verified_at")) for row in apps})
    if len(stamps) != 1:
        raise SystemExit("夹具核验日期不再统一（%s）⇒ 本文件的基准账要重算" % stamps)
    return stamps[0]


class AsofDeterminismTests(unittest.TestCase):
    """扫描器的适用面与合规面：先证明它咬得住，再让它去扫真树。"""

    RAW_GATE_CALL = ('from formal_data_gate import audit\n'
                     'def test_x():\n'
                     '    data = {"local_apps": [{"app_id": "a", "verified_at": "2026-01-01"}]}\n'
                     '    audit(data, {}, {}, {})\n')

    def test_a_missing_asof_declaration_is_caught(self):
        """牙 1：漏声明 as-of 的文件必须进 offender——否则本门只是装饰。"""
        row = scan_source("synthetic_missing.py", self.RAW_GATE_CALL)
        self.assertTrue(row["applicable"])
        self.assertFalse(row["compliant"])
        self.assertEqual(offenders([row]), ["synthetic_missing.py（调了门却没声明 as-of）"])

    def test_declaring_generated_at_makes_it_compliant(self):
        row = scan_source("synthetic_ok.py",
                          self.RAW_GATE_CALL.replace("audit(data, {}, {}, {})",
                                                     'audit(data, {"generated_at": "2026-01-01"}, {}, {})'))
        self.assertTrue(row["applicable"])
        self.assertTrue(row["compliant"], row["own_markers"])

    def test_explicit_as_of_date_argument_makes_it_compliant(self):
        source = ('from app_contract import validate_local_apps\n'
                  'def test_y():\n'
                  '    data = {"local_apps": [{"app_id": "a", "verified_at": "2026-01-01"}]}\n'
                  '    validate_local_apps(data["local_apps"], as_of_date="2026-01-01")\n')
        row = scan_source("synthetic_asof.py", source)
        self.assertTrue(row["applicable"], "这条没被当成适用面＝扫描器在真树上也会同样漏掉")
        self.assertTrue(row["compliant"])

    def test_empty_local_apps_is_not_applicable(self):
        """只塞空表够不着新鲜度门：把这种文件也判违规，规则就成了一片必须糊过去的噪音。"""
        source = self.RAW_GATE_CALL.replace('[{"app_id": "a", "verified_at": "2026-01-01"}]', "[]")
        row = scan_source("synthetic_empty.py", source)
        self.assertFalse(row["applicable"], row)

    def test_another_modules_audit_is_not_applicable(self):
        """别家的 `audit`（sfa.audit / provenance audit）不该被这条规则管：一泛化就误伤。"""
        source = ('import spa_file_audit as sfa\n'
                  'def test_z():\n'
                  '    sfa.audit("x.html")\n')
        row = scan_source("synthetic_other.py", source)
        self.assertFalse(row["applicable"], row)

    def test_provider_hop_is_checked_not_rubber_stamped(self):
        """从 provider 继承证据＝要查 provider 自己有没有声明；provider 没声明就必须报，不能一跳就绿。"""
        consumer = ('from test_formal_data_gate import fixture\n'
                    'from formal_data_gate import audit\n'
                    'def test_w():\n'
                    '    audit(*fixture())\n')
        good = {"test_formal_data_gate": {"applicable": True,
                                         "own_markers": {"verified_at_stamp": True, "generated_at": False,
                                                         "as_of_date": False}}}
        bad = {"test_formal_data_gate": {"applicable": True,
                                         "own_markers": {"verified_at_stamp": False, "generated_at": False,
                                                        "as_of_date": False}}}
        self.assertTrue(scan_source("synthetic_hop.py", consumer, good)["compliant"])
        self.assertFalse(scan_source("synthetic_hop.py", consumer, bad)["compliant"],
                         "provider 不合规还判绿＝这一跳成了橡皮图章")

    def test_a_validate_local_apps_call_without_as_of_is_caught(self):
        """第二条牙：直接调 validate_local_apps 却不给 as_of_date ⇒ 它在拿墙钟算龄，必须报。"""
        source = ('from app_contract import validate_local_apps\n'
                  'def test_v():\n'
                  '    return validate_local_apps([{"app_id": "a", "verified_at": "2026-01-01"}])\n')
        row = scan_source("synthetic_noasof.py", source)
        self.assertTrue(row["applicable"])
        self.assertFalse(row["compliant"], row)

    def test_the_live_tree_has_no_offenders(self):
        rows = scan_scripts()
        self.assertTrue(rows, "一条适用文件都没扫到＝扫描器坏了（规则空转比没规则更糟）")
        self.assertEqual(offenders(rows), [],
                         "这些测试把 app 证据喂给了门禁却没声明基准日期，下一次日历会自己把它变红：%s"
                         % offenders(rows))

    def test_the_scan_covers_the_real_call_sites(self):
        """适用面要数得出来：只断言「无违规」时，扫不到任何东西也算通过——那是空转不是绿。
        名单来源是现场调用点：test_app_contract（直接调 validate_local_apps）、
        test_formal_data_gate（自己写 verified_at）、test_truth_contracts / test_v411_regressions /
        test_philippines_negative_regressions（从 provider 继承）、test_v412_regressions（本轮补的）。
        反面也钉住：只塞空 local_apps 的 test_v420_regressions 不算违规，规则不该泛化到噪音。"""
        rows = {row["file"]: row for row in scan_scripts()}
        for name in ("test_app_contract.py", "test_formal_data_gate.py", "test_truth_contracts.py",
                     "test_v411_regressions.py", "test_v412_regressions.py",
                     "test_philippines_negative_regressions.py",
                     # 扫描器自己也必须在名单里：它自己就调 validate_local_apps。
                     # 一家子不照自己的镜子，规则就永远只量别人。
                     "test_v422_gate_asof_determinism.py"):
            self.assertIn(name, rows, "%s 把 app 证据喂进了门禁却没被视作适用文件 ⇒ 本门漏覆盖" % name)
        self.assertNotIn("test_v420_regressions.py", rows,
                         "v420 只塞了空 local_apps：把它算进适用面就是给一条没对象的门记账")
        self.assertTrue(rows["test_philippines_negative_regressions.py"]["providers"],
                        "provider 那一跳没被登记＝这条合规是靠盖章不是靠查")

    def test_the_fixed_file_declares_the_fixture_own_date(self):
        """诚实性：补的那一行必须是**夹具自己的核验日**，不是挑一个不报错的日期。"""
        source = (SCRIPTS / "test_v412_regressions.py").read_text(encoding="utf-8")
        match = re.search(r'AS_OF\s*=\s*"(\d{4}-\d{2}-\d{2})"', source)
        self.assertTrue(match, "test_v412_regressions.py 里的 AS_OF 常量不见了：基准日期又被墙钟接管了")
        self.assertEqual(match.group(1), fixture_verified_at(),
                         "声明的 as-of（%s）不等于夹具核验日（%s）⇒ 那是挪门，不是写基准"
                         % (match.group(1), fixture_verified_at()))
        self.assertIn('manifest["generated_at"] = self.AS_OF', source)

    def test_v412_source_does_not_mention_the_wall_clock_as_a_fallback(self):
        """带时区的 generated_at 在这个门上会炸（实测报 15 条 Invalid isoformat string）：
        基准日期必须是纯日期，别用项目里别处通用的 datetime 形式。"""
        source = (SCRIPTS / "test_v412_regressions.py").read_text(encoding="utf-8")
        self.assertNotIn('generated_at"] = f"', source)
        for value in re.findall(r'AS_OF\s*=\s*"([^"]+)"', source):
            self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}$", "%s 不是 YYYY-MM-DD" % value)

    def test_the_freshness_rule_is_real_and_does_not_need_todays_date(self):
        """规则不是空转：同一条夹具，as-of＝核验日 0 错；as-of＝核验日+31 天必然报错。
        用**算出来的日期**而不是今天，所以这条证词明天、明年都成立。"""
        import app_contract
        loaded = json.loads(FIXTURE.read_text(encoding="utf-8"))
        apps = (loaded["local_apps"] if isinstance(loaded, dict) and "local_apps" in loaded else loaded)
        base = fixture_verified_at()
        self.assertEqual(app_contract.validate_local_apps(apps, as_of_date=base), [],
                         "as-of 等于核验日还报错⇒不是日历问题，是真有别的缺陷")
        late = (datetime.date.fromisoformat(base) + datetime.timedelta(days=FRESHNESS_DAYS)).isoformat()
        errors = app_contract.validate_local_apps(apps, as_of_date=late)
        self.assertTrue(errors, "核验日+%d 天仍 0 条⇒新鲜度门松了，本文件的因果链作废（该重判而不是放行）"
                                % FRESHNESS_DAYS)
        self.assertTrue(all("过期" in item for item in errors), errors[:3])

    def test_the_wall_clock_fallback_is_still_the_premise(self):
        """本门的存在前提：门禁仍会在 manifest 缺 generated_at 时回退到 date.today()。
        哪天撤了这行，就同步收窄本扫描的适用面，别留一条谁也说不清为什么还绿着的规则。"""
        body = GATE.read_text(encoding="utf-8")
        self.assertIn(AS_OF_FALLBACK, body,
                      "formal_data_gate.py 的 as-of 回退表达式变了：请重判本文件的适用面并改登记")


if __name__ == "__main__":
    unittest.main()
