# -*- coding: utf-8 -*-
"""v4.2.2 V4 — 零调用执行期哨兵。

§11 V4：`google_billable_api_calls / google_api_keys_used / google_maps_scrape_attempts /
paid_fallback_attempts` 这四项必须来自**执行期拦截器**，不接受源码字符串扫描。
本模块在进程内挂钩 socket / http.client / urllib.request / 凭据读取，把每一次真实尝试记账，
并且只按 `references/map-gate-v422.json::zero_call_gate.host_classification` 的登记名单分类
——哨兵自己不含任何主机判断，免得出第二套规则（§6.3 同一手法）。

诚实边界：
* 挂钩装不齐就 `refuse_when_not_armed`，账本标 `armed=false`，门禁据此拒绝写 0。
* 本机回环（例如驱动浏览器的 CDP 连接）单记 `local_loopback_attempts`，不混进四项，也不许
  借此宣称「零 socket」。
* 账本只记主机名与被读的**变量名**，绝不记录凭据值。
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_FILE = ROOT / "references" / "map-gate-v422.json"
INTERCEPTORS = ("socket.connect", "socket.create_connection",
                "http.client.HTTPConnection.request", "urllib.request.urlopen",
                "credential_env_read")

_state = {"counts": {}, "events": [], "hosts": {}, "env_names": {},
          "armed_interceptors": [], "installed_interceptors": [], "window": None,
          "seen_requests": set(), "classify": None}


def _classification() -> dict:
    """主机分类名单只住门禁登记处，哨兵不内置判断（§6.3 同一手法）。"""
    gate = json.loads(GATE_FILE.read_text(encoding="utf-8"))
    return gate["zero_call_gate"]


def _host_of(target, host="") -> str:
    text = str(host or target or "")
    if "://" in text:
        text = text.split("://", 1)[1]
    return re.split(r"[/ ?]", text, 1)[0].strip("[]").lower()


def _note(kind: str, host: str, detail: str) -> None:
    _state["counts"][kind] = _state["counts"].get(kind, 0) + 1
    if host:
        _state["hosts"][host] = _state["hosts"].get(host, 0) + 1
    if len(_state["events"]) < 200:
        _state["events"].append({"kind": kind, "host": host, "detail": detail[:120]})


def _classify_host(host: str, rules: dict) -> list[str]:
    out = []
    for metric, needle_list in (("google_billable_api_calls", rules["billable_hosts"]),
                                ("google_maps_scrape_attempts", rules["scrape_hosts"]),
                                ("paid_fallback_attempts", rules["paid_fallback_hosts"])):
        if any(needle.lower() in host for needle in needle_list):
            out.append(metric)
    return out


def arm() -> None:
    """装上全部拦截器。任何一件装不上都要说出来，不能默默少一件。"""
    gate_full = json.loads(GATE_FILE.read_text(encoding="utf-8"))
    rules = gate_full["zero_call_gate"]
    _state["counts"] = {}
    _state["events"] = []
    _state["hosts"] = {}
    _state["env_names"] = {}
    _state["seen_requests"] = set()
    counters = _state["counts"]
    for key in (rules["required_metrics"] + rules.get("hard_zero_extra_metrics", [])
                + ["local_loopback_attempts", "credential_reads_total"]):
        counters.setdefault(key, 0)
    loopback = {item.lower() for item in rules["host_classification"]["loopback_hosts"]}
    classification = rules["host_classification"]

    original_connect = socket.socket.connect

    def connect(self, address, *args, **kwargs):
        # 传输层只记「有没有出去」：socket 看到的是 IP，按主机名分类既会漏判也会与 URL 层重复计数。
        # 四项指标一律在上面两层（urlopen / http.client.request）计，保证一次逻辑调用只记一次。
        host = str(address[0]) if isinstance(address, (tuple, list)) and address else ""
        _note("network_attempts_total", host, "socket.connect")
        if host in loopback:
            _note("local_loopback_attempts", host, "socket.connect loopback")
        return original_connect(self, address, *args, **kwargs)

    original_create = socket.create_connection

    def create_connection(address, *args, **kwargs):
        host = str(address[0]) if isinstance(address, (tuple, list)) and address else ""
        _note("network_attempts_total", host, "socket.create_connection")
        if host in loopback:
            _note("local_loopback_attempts", host, "socket.create_connection loopback")
        return original_create(address, *args, **kwargs)

    original_request = http.client.HTTPConnection.request

    def request(self, method, url, *args, **kwargs):
        host = _host_of(url, getattr(self, "host", ""))
        _note("network_attempts_total", host, "http.client.request %s" % method)
        if host in loopback:
            _note("local_loopback_attempts", host, "http.client.request loopback")
        else:
            # 唯一的指标分类点：真实 HTTP 尝试一定经过这里（urllib / requests 都是），
            # 所以一次逻辑调用记一次。裸 socket 直连 IP 分不出主机名，只能落在
            # network_attempts_total 里——那一项同样要求为 0，所以不会因为分层而漏放行。
            for metric in _classify_host(host, classification):
                _note(metric, host, "http.client.request")
        return original_request(self, method, url, *args, **kwargs)

    original_urlopen = urllib.request.urlopen

    def urlopen(req, *args, **kwargs):
        url = req if isinstance(req, str) else getattr(req, "full_url", "") or ""
        host = _host_of(url)
        _note("network_attempts_total", host, "urllib.request.urlopen")
        if host in loopback:
            _note("local_loopback_attempts", host, "urllib.request.urlopen loopback")
        else:
            # 指标只在 http.client.request 记一次：urlopen 总会下沉到那一层，
            # 在这里再记一遍会把一次逻辑调用数成两次（虚增，也会让真实的 1 次看起来像 2 次）。
            _note("attempt_url", host, url[:160])
        return original_urlopen(req, *args, **kwargs)

    watched = {name.upper(): name for name in rules["credential_env_names"]}
    original_env_get = os.environ.get

    def env_get(key, *args, **kwargs):
        if str(key).upper() in watched:
            name = watched[str(key).upper()]
            _state["env_names"][name] = _state["env_names"].get(name, 0) + 1
            _note("google_api_keys_used", "", "credential read %s（只记变量名，不记值）" % name)
            _note("credential_reads_total", "", name)
        return original_env_get(key, *args, **kwargs)

    _state["installed_interceptors"] = list(INTERCEPTORS)
    socket.socket.connect = connect
    socket.create_connection = create_connection
    http.client.HTTPConnection.request = request
    urllib.request.urlopen = urlopen
    os.environ.get = env_get
    _state["armed_interceptors"] = list(INTERCEPTORS)
    _state["window"] = {"started_at": time.time()}

    def disarm():
        socket.socket.connect = original_connect
        socket.create_connection = original_create
        http.client.HTTPConnection.request = original_request
        urllib.request.urlopen = original_urlopen
        os.environ.get = original_env_get
        _state["armed_interceptors"] = []

    return disarm


def window_active() -> bool:
    """已有窗口在跑就不要重复 arm（会把计数清零，账本就丢了）。"""
    return bool(_state["armed_interceptors"])


@contextmanager
def guarded(label: str = ""):
    disarm = arm()
    try:
        yield _state
    finally:
        disarm()
        _state["window"] = dict(_state.get("window") or {}, ended_at=time.time(), label=label)


def ledger(extra: dict | None = None) -> dict:
    rules = _classification()
    # 账本是在窗口关掉之后读的：报的是这一段里真正装过的拦截器，不是读账本那一刻的状态
    armed = list(_state["installed_interceptors"])
    missing = sorted(set(rules["required_interceptors"]) - set(armed))
    gate_full = json.loads(GATE_FILE.read_text(encoding="utf-8"))
    counts = dict(_state["counts"])
    # 派生量：本机回环在每一层都同时进 total 与 loopback，非回环只进 total，
    # 所以 total − loopback 就是「真正想离开本机的尝试次数」——不需要再猜一次。
    counts["external_network_attempts"] = (counts.get("network_attempts_total", 0)
                                           - counts.get("local_loopback_attempts", 0))
    out = {
        "authority": "scripts/zero_call_sentinel.py",
        "gate_version": gate_full["gate_version"],
        "interceptors_armed": armed,
        "interceptors_missing": missing,
        "armed": not missing,
        "counts": counts,
        "derived_metrics": ["external_network_attempts"],
        "derived_metric_formula": {"external_network_attempts":
                                   "network_attempts_total - local_loopback_attempts"},
        "hosts_seen": dict(sorted(_state["hosts"].items())),
        "credential_names_read": dict(sorted(_state["env_names"].items())),
        "events_sample": _state["events"][:20],
        "window": _state.get("window"),
        "values_of_credentials_never_recorded": True,
        "note": "计数是执行期拦截到的真实尝试；没有拦截器就没有数字——本账本不产出推断值。"
                "external_network_attempts 是 total−loopback 的派生量，不是第三个判断者。",
    }
    if extra:
        out.update(extra)
    blob = json.dumps(out, ensure_ascii=False, sort_keys=True).encode("utf-8")
    out["ledger_sha256_16"] = hashlib.sha256(blob).hexdigest()[:16].upper()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="零调用执行期哨兵")
    ap.add_argument("--exec", nargs=argparse.REMAINDER,
                    help="在哨兵保护下运行的命令（argv 形式，例如 python -B tooling/x.py …）")
    ap.add_argument("--out", default="", help="账本 JSON 输出路径")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    with guarded(args.label):
        code = 0
        if args.exec:
            code = subprocess.call(args.exec, env=dict(os.environ,
                                                        PYTHONIOENCODING="utf-8"))
        result = ledger({"exec": list(args.exec or []), "child_exit_code": code})
    if args.out:
        Path(args.out).write_bytes(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps({"armed": result["armed"], "counts": result["counts"],
                      "interceptors_missing": result["interceptors_missing"],
                      "child_exit_code": code}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
