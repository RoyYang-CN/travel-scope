# -*- coding: utf-8 -*-
"""§MT-D2 缓存卫生：全量命令跑完后发布树仍必须零 .pyc——这条只能由「子进程继承同一个口径」成立。

业主 2026-11-01 实测：`python -B -m pytest -p no:cacheprovider scripts -q` 全绿，却在
`scripts/__pycache__` 留下 20 个 .pyc。原因不在 pytest 本体（-B 让它自己不写），而在**测试内部再起的
子进程**：`delivery_gate.py` 调 validate_output/visual_qa/usage_report、`test_v412/418` 调
gen_travel_scope，那些子进程用裸 `python scripts/x.py` 起，既没有 `-B` 也没有
PYTHONDONTWRITEBYTECODE ⇒ 它们 import 发布模块时就把 .pyc 写进封册之外的字节。
所以「缓存为 0」从来不是主进程的属性，是**整棵调用链**的属性。

本模块是这件事的唯一实现：
  · `env()` 给所有子进程注入 PYTHONDONTWRITEBYTECODE=1（可再叠加变量）；
  · `interpreter()` 把 `-B` 补进 argv（两处都做，因为登记口径要能被只读命令复现）；
  · `measure()` 现场数缓存（绝对值，不是差值）——沿用「缓存要量绝对值」那条教训。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_VAR = "PYTHONDONTWRITEBYTECODE"
CACHE_DIR_NAMES = ("__pycache__", ".pytest_cache")


def env(base: dict | None = None, **extra: str) -> dict:
    """子进程环境：必带 PYTHONDONTWRITEBYTECODE=1，其余原样继承。"""
    merged = dict(os.environ if base is None else base)
    merged[ENV_VAR] = "1"
    merged.update(extra)
    return merged


def env_without_no_bytecode_guard(base: dict | None = None, **extra: str) -> dict:
    """刻意**不带** PYTHONDONTWRITEBYTECODE 的环境：只给缓存卫生测试复现业主那条命令用。

    复现事故的条件必须真的裸——如果复现用的一环也带上护栏，那条测试就永远只能证明「护栏在时很干净」。
    这是本模块唯一的豁免出口，所以调用点必须写清理由；AST 扫描认「走过 pyc.env*」而不是认某个函数名，
    就是为了这个豁免面可枚举、可数，而不是散落在各处的手抄 dict。
    """
    merged = dict(os.environ if base is None else base)
    merged.pop(ENV_VAR, None)
    merged.update(extra)
    return merged


def interpreter(argv: list) -> list:
    """给 `python scripts/x.py …` 或 `python -m pytest …` 形态的 argv 在解释器后补 `-B`。

    只看紧跟解释器的那一格：`-B` 是解释器开关，出现在脚本参数里（比如某个脚本自己的 `--b` 参数）
    不算已经带上，硬要在那里找就会把「没带」误判成「带过」。
    """
    out = list(argv)
    if len(out) < 1:
        return out
    if len(out) > 1 and out[1] == "-B":
        return out
    return [out[0], "-B"] + out[1:]


def measure(root: Path = ROOT) -> dict:
    """缓存绝对值：目录数 + .pyc 文件数 + 清单。调用前后各量一次才谈「有没有残留」。"""
    root = Path(root)
    dirs = sorted(str(p.relative_to(root).as_posix()) for name in CACHE_DIR_NAMES
                  for p in root.rglob(name))
    files = sorted(str(p.relative_to(root).as_posix()) for p in root.rglob("*.pyc"))
    return {"cache_dirs": dirs, "pyc_files": files,
            "abscount": len(dirs) + len(files),
            "measured_at": str(root)}


def is_clean(root: Path = ROOT) -> bool:
    return measure(root)["abscount"] == 0


if __name__ == "__main__":
    import json
    print(json.dumps(measure(), ensure_ascii=True, indent=1))
