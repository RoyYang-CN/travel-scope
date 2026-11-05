# -*- coding: utf-8 -*-
"""v4.2.2 V6-R §6：发布树的验证命令必须干净——不留测试缓存，也不靠缓存活着。

业主 2026-10-31 第 6 条：「清除发布树测试缓存，并证明正式验证命令不会重新产生缓存。」

这里刻意不用「树上永远没有缓存」当断言：`.pytest_cache` 是 pytest 自己写的运行痕迹，
只要有人不带 `-p no:cacheprovider` 跑一遍就会回来，把它写成不变式只会制造假红。可复现的
判据是**增量**：正式验证命令（`python -B scripts/verify_product.py`）跑一次，缓存目录集合
必须一个都不多——这条才是「验证命令本身不产缓存」的证明。同一口径也套在跑测试的命令上
（见 test_documented_test_invocation_leaves_no_cache：`-B` 挡不住 pytest 的断言重写缓存，
必须用 PYTHONDONTWRITEBYTECODE=1）。

顺带钉住封册口径：`release_file_paths()` 排除 `__pycache__` / `.pytest_cache` / `.pyc`，
所以缓存既不是发布内容，也不该被当成发布证据。
"""
from __future__ import annotations

import os
import subprocess

import pyc_hygiene as pyc
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
# 子进程标记：本文件的第四条测试会起一个 pytest 跑「自己这个文件」，不加闸门就是无限递归。
# 子进程里遇到它就跳过那条，其余三条照跑——被证明的对象（命令不留痕）不受闸门影响。
CHILD_ENV = "TRAVEL_SCOPE_HYGIENE_CHILD"

import verify_product as vp            # noqa: E402


def cache_dirs(root: Path) -> set[str]:
    found = set()
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        if path.name in ("__pycache__", ".pytest_cache"):
            found.add(path.relative_to(root).as_posix())
        elif any(part == ".pytest_cache" for part in path.parts):
            found.add(path.relative_to(root).as_posix())
    return found


def pyc_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*.pyc")}


class FormalVerificationHygieneTests(unittest.TestCase):
    def test_verify_product_adds_no_cache_directories(self):
        before = cache_dirs(ROOT)
        proc = subprocess.run(pyc.interpreter([sys.executable, str(SCRIPTS / "verify_product.py")]),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=str(ROOT), env=pyc.env())
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        after = cache_dirs(ROOT)
        self.assertEqual(after - before, set(),
                         "正式验证命令自己产生了缓存目录：%s（它应当只读文件、不导入可执行体）"
                         % sorted(after - before))

    def test_seal_inventory_excludes_generated_caches(self):
        inventory = vp.release_file_paths(ROOT)
        self.assertTrue(inventory, "封册清单为空就没有可核对的东西")
        offenders = [name for name in inventory
                     if "__pycache__" in name or ".pytest_cache" in name or name.endswith(".pyc")]
        self.assertEqual(offenders, [], "缓存被当成发布内容封存：%s" % offenders[:5])

    def test_verify_command_does_not_import_release_modules(self):
        """不导入同树模块＝不会写 .pyc；这一条是上一条测试能长期成立的原因，不能只靠 -B。"""
        source = (SCRIPTS / "verify_product.py").read_text(encoding="utf-8")
        for imported in ("import reseal_product", "import visual_qa", "import map_gate_v422",
                         "import spa_renderer", "import delivery_gate"):
            self.assertNotIn(imported, source,
                             "验证命令导入了 %s：它每跑一次就会给发布树写一份 .pyc" % imported)

    def test_every_subprocess_call_site_carries_the_no_bytecode_env(self):
        """根因不在主命令，在**调用链**：任何一处裸 `python scripts/x.py` 都会替整棵树写 .pyc。

        业主 2026-11-01 的复现就是这个形状：`python -B -m pytest …` 全绿，`scripts/__pycache__`
        里却躺了 20 个 .pyc——-B 只管主进程，管不到测试内部再起的子进程。
        所以这条不是「记得加环境变量」的口头约定，是对整棵 scripts/*.py 的 AST 扫描：
        每个 subprocess.run/Popen/check_output/check_call 的源码段里必须走过 `pyc.env*`
        （含那个刻意不带护栏的豁免出口，它也只认这一个名字），漏一处就报出文件与行号。
        pyc_hygiene 自己是唯一豁免文件（它就是这些口径的定义处）。
        """
        import ast
        offenders = []
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.name == pyc.__name__ + ".py":
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:                       # 语法都过不了就更谈不上继承
                offenders.append("%s: SYNTAX %s" % (path.name, exc))
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                        and func.value.id == "subprocess"
                        and func.attr in ("run", "Popen", "check_output", "check_call")):
                    continue
                segment = ast.get_source_segment(source, node) or ""
                if "pyc.env" not in segment:
                    offenders.append("%s:%d %s" % (path.name, node.lineno,
                                                   segment[:60].replace("\n", " ")))
        self.assertEqual(offenders, [],
                         "这些子进程调用没接 pyc.env()，跑一次就会给发布树留 .pyc：%s" % offenders[:6])

    def test_owner_condition_full_command_leaves_zero_caches(self):
        """0 → 业主那条命令 → 仍 0，且**故意不带** PYTHONDONTWRITEBYTECODE。

        复现条件必须比被复现的事故更严：父进程环境里明确摘掉那个变量，只留 `-B`，
        跑的对象专挑会再起子进程的两个模块（gen_travel_scope 与 map_gate_v422）。
        只要还有一处调用点漏了口径，这里就会长出 .pyc——不是靠我记得去看。
        """
        if os.environ.get(CHILD_ENV) == "1":
            self.skipTest("子进程里跳过：被证明的命令已由父进程原样执行过一次")
        start = pyc.measure(ROOT)
        self.assertEqual(start["abscount"], 0,
                         "测试开始前发布树就不干净：%s——先把本轮审计留下的缓存清掉再看这条"
                         % (start["cache_dirs"] + start["pyc_files"])[:4])
        argv = pyc.interpreter([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                                "test_v412_regressions.py", "test_v422_gate_producer.py"])
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=str(SCRIPTS),
                              env=pyc.env_without_no_bytecode_guard(**{CHILD_ENV: "1"}))
        self.assertEqual(proc.returncode, 0, (proc.stdout + proc.stderr)[-600:])
        after = pyc.measure(ROOT)
        self.assertEqual(after["abscount"], 0,
                         "业主形式的命令跑完仍有 %d 项缓存残留：%s"
                         % (after["abscount"], (after["cache_dirs"] + after["pyc_files"])[:6]))

    def test_documented_test_invocation_leaves_no_cache(self):
        """跑测试的那条命令本身也要不脏树——实测口径，不是口头约定。

        2026-10-31 实测：`python -B -m pytest -p no:cacheprovider scripts` 仍然会在
        scripts/__pycache__/ 留下 20 个 .pyc（pytest 的断言重写有自己的写盘路径，不吃 -B）。
        换成 PYTHONDONTWRITEBYTECODE=1 起子进程才真的是零增量。登记命令：

            PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider -q scripts

        封册把缓存排除在发布内容之外，所以它们不会让 verify_product 变红；但「验证命令不留痕」
        这句话要连测试命令一起成立，否则审计看到的是同一棵树被自己的检查越跑越脏。
        """
        if os.environ.get(CHILD_ENV) == "1":
            self.skipTest("子进程里跳过自跑的第四条：被证明的命令已由父进程原样执行过一次")
        before_dirs, before_pyc = cache_dirs(ROOT), pyc_files(ROOT)
        proc = subprocess.run(pyc.interpreter([sys.executable, "-m", "pytest",
                                               "-p", "no:cacheprovider", "-q",
                                               str(Path(__file__).name)]),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              cwd=str(SCRIPTS), env=pyc.env(**{CHILD_ENV: "1"}))
        self.assertEqual(proc.returncode, 0, (proc.stdout + proc.stderr)[-500:])
        new_dirs = cache_dirs(ROOT) - before_dirs
        new_pyc = pyc_files(ROOT) - before_pyc
        self.assertEqual((sorted(new_dirs), sorted(new_pyc)), ([], []),
                         "登记在案的测试命令仍然产生缓存：dirs=%s pyc=%s（应带 "
                         "PYTHONDONTWRITEBYTECODE=1）" % (sorted(new_dirs), sorted(new_pyc)[:5]))


if __name__ == "__main__":
    unittest.main()
