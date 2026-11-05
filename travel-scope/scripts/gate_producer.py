"""Every gate report must say which code and which input produced it.

V0-L17（checklist §10「封存输入、重放和 product fingerprint」）记录的结构性缺口是：
冻结 run 里存的 formal_data_gate / delivery-gate 报告写 PASS，同一输入用现行代码复算却是
FAIL（CA 356／PH 201 条）。当时的报告与今天的复算结果无法区分「谁说的」——报告里没有产出者
身份，所以一个 PASS 可以是任何一版代码、任何一份输入说出来的。这就使 PASS 可伪装。

本模块把「产出者身份」变成报告载荷里的强制字段，并提供唯一的写报告出口：

1. `stamp()` 现场测量产出该报告的**代码与配置**（逐文件 SHA-256）、当且仅当它们都在这一次的
   封存清册里才允许盖章（未入册的代码不得声称是发布产物——这是 V0-L08 的牙齿：product
   fingerprint 过去只校验封条文件本身，不校验代码）。
2. `write_stamped_report()` 是唯一的报告落盘面：盖章 + LF 字节写出。
   Windows 上 `write_text()` 会把 "\n" 翻成 "\r\n"，同一输入在两棵树上得到不同字节，
   「重放字节一致」就成了一句空话；所以这里一律 `write_bytes`。
3. `verify_report()` 反过来复算：报告说自己由哪版代码产的，现行代码是不是那一版；
   封存是不是被重铸过；声明的输入字节还是不是那些字节；戳本身有没有被手改。
   任一不符即给出封闭集 code，绝不返回「大概还行」。

时间戳（`run_at_utc`）与 `argv` 属于运行信息，不进 `identity_sha256`，因此重放比对只看身份，
不看钟。若某处需要整文件字节重放，请比对 `identity_sha256` 而不是报告文件哈希。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

STAMP_VERSION = "gate-producer-stamp-1"
STAMP_KEY = "producer"
ROOT = Path(__file__).resolve().parents[1]

# 封闭集：verify_report 只会产出这些前缀，登记与测试都以此为准。
VERIFY_CODES = (
    "PRODUCER_REPORT_FILE_MISSING",
    "PRODUCER_REPORT_NOT_JSON",
    "PRODUCER_STAMP_ABSENT",
    "PRODUCER_STAMP_NOT_OBJECT",
    "PRODUCER_STAMP_VERSION_UNSUPPORTED",
    "PRODUCER_IDENTITY_DIGEST_DIFFERS",
    "PRODUCER_PRODUCT_MISMATCH",
    "PRODUCER_PRODUCT_VERSION_DIFFERS",
    "PRODUCER_RENDERER_ID_DIFFERS",
    "PRODUCER_SEAL_FILE_MISSING",
    "PRODUCER_SEAL_SHA_DIFFERS",
    "PRODUCER_SEAL_INVENTORY_MISMATCH",
    "PRODUCER_CODE_KEY_MISSING",
    "PRODUCER_CODE_FILE_MISSING",
    "PRODUCER_CODE_UNSEALED",
    "PRODUCER_CODE_DIGEST_DIFFERS",
    "PRODUCER_INPUT_DIGEST_DIFFERS",
    "PRODUCER_INPUTS_NOT_MEASURABLE",
    "PRODUCER_REPORT_BYTES_DIFFER",
    "PRODUCER_ORIGIN_UNREADABLE",
    "PRODUCER_CODE_NOT_MATCHING_SEAL",
    "PRODUCER_UNREGISTERED_CODE",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def origin_seal(root: Path | None = None) -> dict:
    """Read the current seal (product-origin.json) without re-implementing verification."""
    root = Path(root or ROOT).resolve()
    path = root / "product-origin.json"
    if not path.is_file():
        raise ValueError("缺少 product-origin.json：无法确定发布版本与封存身份")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("product-origin.json 无法解析：%s" % exc) from exc
    inventory = sorted(manifest.get("inventory") or [])
    digests = manifest.get("sha256") or {}
    if set(inventory) != set(digests):
        raise ValueError("product-origin.json 的 inventory 与 sha256 清单不一致")
    return {
        "seal_path": path,
        "seal_sha256": _sha256(path),
        "product": manifest.get("product"),
        "version": manifest.get("version"),
        "renderer_id": manifest.get("renderer_id"),
        "sealed_files": len(inventory),
        "inventory": set(inventory),
        "inventory_digests": digests,
    }


def _rel_to_root(path: Path, root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("产出者文件必须位于发布树内，否则封存身份无从谈起：%s" % resolved) from exc


def digest_files(paths, root: Path) -> dict:
    """Measure each file live; keys are release-relative posix paths (stable across machines)."""
    out = {}
    for item in paths:
        path = Path(item)
        if not path.is_absolute():
            path = root / path
        rel = _rel_to_root(path, root)
        if not path.is_file():
            # 报告不能声称由一支不存在的代码产出：含糊的 FileNotFoundError 会让人以为是环境问题。
            raise ValueError("声明的产出者文件不在发布树内，无法盖章：%s" % rel)
        out[rel] = _sha256(path)
    return out


VOLATILE_STAMP_KEYS = ("run_at_utc", "argv", "cwd", "identity_sha256")


def _identity_payload(stamp_body: dict) -> dict:
    """Everything except run-time chatter and the digest itself: this must survive a replay.

    `identity_sha256` 必须排除，否则 stamp() 里「先算后写」与 verify_report 里「对着已写入的戳复算」
    会得到两套键集——冒烟测试第一次跑到干净报告就报了 PRODUCER_IDENTITY_DIGEST_DIFFERS，就是这个坑。
    """
    return {k: v for k, v in stamp_body.items() if k not in VOLATILE_STAMP_KEYS}


def _identity_digest(stamp_body: dict) -> str:
    blob = json.dumps(_identity_payload(stamp_body), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest().upper()


def stamp(gate_role: str, producing_code, producing_config=(), inputs=None,
          root: Path | None = None, now: str | None = None) -> dict:
    """Build the producer block for a report about to be written.

    `inputs` maps a label to a file path; each is measured live so the report can later
    prove *which* dataset it was talking about (V0-L17 需要能区分「同一输入复算」与「换了输入」).
    """
    root = Path(root or ROOT).resolve()
    seal = origin_seal(root)
    code = digest_files(producing_code, root)
    config = digest_files(producing_config, root)
    unsealed = sorted(rel for rel in list(code) + list(config) if rel not in seal["inventory"])
    if unsealed:
        # 未入册的文件不得充当发布门禁的产出者：否则「PASS」可能来自一支从没被封存的代码。
        raise ValueError("产出者代码/配置不在封存清册内，禁止盖章：%s" % ", ".join(unsealed))
    input_digests = {}
    for label, path in sorted((inputs or {}).items()):
        p = Path(path)
        if not p.is_absolute():
            p = root / p
        if not p.is_file():
            raise ValueError("报告声明的输入不存在，无法盖章：%s -> %s" % (label, path))
        input_digests[label] = {"path": str(p), "sha256": _sha256(p),
                                "bytes": p.stat().st_size}
    body = {
        "stamp_version": STAMP_VERSION,
        "gate_role": gate_role,
        "product": seal["product"],
        "product_version": seal["version"],
        "renderer_id": seal["renderer_id"],
        "seal_sha256": seal["seal_sha256"],
        "sealed_files": seal["sealed_files"],
        "producing_code": code,
        "producing_config": config,
        "inputs": input_digests,
        "python": platform.python_version(),
        "argv": list(sys.argv),
        "cwd": str(Path.cwd()),
        "run_at_utc": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    body["identity_sha256"] = _identity_digest(body)
    return body


def collect_inputs(pairs: dict, only_existing: bool = False) -> dict:
    """Keep only inputs the caller actually passed; a claimed-but-absent input stays fatal.

    可选参数为空（""／None）表示「这次没用这个输入」，直接不登记；给了路径就必须量得到，
    否则 stamp() 会拒绝——报告不得声称它看过一份不存在的输入。
    `only_existing=True` 是给「这条输入本来就可能不存在」的场合（比如 demo 档不产 formal gate 报告）：
    不存在的项从登记里去掉，而不是让盖章炸掉——**去掉**是如实记录「这次没看过它」，
    炸掉则是让一个可选证据缺席变成整份报告写不出来。
    """
    kept = {}
    for label, value in pairs.items():
        if not value:
            continue
        if only_existing and not Path(value).is_file():
            continue
        kept[label] = value
    return kept


def stamped(payload: dict, producer: dict) -> dict:
    """Attach the stamp in a canonical position so diffs read the same everywhere."""
    if not isinstance(payload, dict):
        raise TypeError("报告载荷必须是对象，收到 %s" % type(payload).__name__)
    if STAMP_KEY in payload:
        raise ValueError("报告已带 producer 块：请由 write_stamped_report 统一盖章，不得重复")
    return {**payload, STAMP_KEY: producer}


def serialize(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")


def write_stamped_report(path, payload: dict, gate_role: str, producing_code,
                         producing_config=(), inputs=None, root: Path | None = None,
                         now: str | None = None) -> dict:
    """The only sanctioned way to persist a gate report: stamp, then write LF bytes."""
    producer = stamp(gate_role, producing_code, producing_config, inputs, root, now)
    out = stamped(payload, producer)
    blob = serialize(out)
    Path(path).write_bytes(blob)
    return {"path": str(path), "sha256": hashlib.sha256(blob).hexdigest().upper(),
            "bytes": len(blob), STAMP_KEY: producer, "report": out}


def verify_report(path_or_payload, root: Path | None = None, recheck_inputs: bool = True) -> dict:
    """Recompute the report's own claims; never soften a mismatch into a note."""
    root = Path(root or ROOT).resolve()
    findings: list[str] = []
    payload = path_or_payload
    blob = None
    if isinstance(payload, (str, Path)):
        p = Path(payload)
        if not p.is_file():
            return {"report": str(p), "trust": "UNTRUSTED", "self_verdict": "UNTRUSTED",
                    "findings": ["PRODUCER_REPORT_FILE_MISSING|%s" % p], "producer": None}
        blob = p.read_bytes()
        try:
            payload = json.loads(blob.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"report": str(p), "trust": "UNTRUSTED", "self_verdict": "UNTRUSTED",
                    "findings": ["PRODUCER_REPORT_NOT_JSON|%s" % exc], "producer": None}
    if not isinstance(payload, dict):
        return {"report": str(path_or_payload), "trust": "UNTRUSTED", "self_verdict": "UNTRUSTED",
                "findings": ["PRODUCER_STAMP_ABSENT|报告载荷不是对象"], "producer": None}

    body = payload.get(STAMP_KEY)
    if body is None:
        findings.append("PRODUCER_STAMP_ABSENT|报告没有产出者身份块；"
                        "无法确定是哪版代码、哪份输入说的 PASS（V0-L17 的缺口形态）")
    elif not isinstance(body, dict):
        findings.append("PRODUCER_STAMP_NOT_OBJECT|producer 必须是对象，收到 %s"
                        % type(body).__name__)
    else:
        if body.get("stamp_version") != STAMP_VERSION:
            findings.append("PRODUCER_STAMP_VERSION_UNSUPPORTED|stamp_version=%r，现行只认 %r"
                            % (body.get("stamp_version"), STAMP_VERSION))
        if _identity_digest(body) != body.get("identity_sha256"):
            findings.append("PRODUCER_IDENTITY_DIGEST_DIFFERS|身份摘要与声明不符：戳被手改或字段被增删")
        try:
            seal = origin_seal(root)
        except ValueError as exc:
            seal = None
            findings.append("PRODUCER_ORIGIN_UNREADABLE|%s" % exc)
        if seal is not None:
            if body.get("product") != seal["product"]:
                findings.append("PRODUCER_PRODUCT_MISMATCH|%r != %r"
                                % (body.get("product"), seal["product"]))
            if body.get("product_version") != seal["version"]:
                findings.append("PRODUCER_PRODUCT_VERSION_DIFFERS|报告称 %r，现行发布是 %r"
                                % (body.get("product_version"), seal["version"]))
            if body.get("renderer_id") != seal["renderer_id"]:
                findings.append("PRODUCER_RENDERER_ID_DIFFERS|报告称 %r，现行是 %r"
                                % (body.get("renderer_id"), seal["renderer_id"]))
            if body.get("seal_sha256") != seal["seal_sha256"]:
                findings.append("PRODUCER_SEAL_SHA_DIFFERS|报告写于封条 %s，现行封条是 %s"
                                "（封条已重铸：这份报告不再是现行代码的结论，必须重跑）"
                                % (str(body.get("seal_sha256"))[:16], seal["seal_sha256"][:16]))
            if int(body.get("sealed_files") or -1) != seal["sealed_files"]:
                findings.append("PRODUCER_SEAL_INVENTORY_MISMATCH|报告时封存 %s 个文件，现行 %s 个"
                                % (body.get("sealed_files"), seal["sealed_files"]))
        for key in ("producing_code", "producing_config"):
            claimed = body.get(key)
            if not isinstance(claimed, dict) or not claimed:
                findings.append("PRODUCER_CODE_KEY_MISSING|%s 必须是非空对象" % key)
                continue
            for rel, digest in sorted(claimed.items()):
                target = root / rel
                if not target.is_file():
                    findings.append("PRODUCER_CODE_FILE_MISSING|%s 声明了 %s 但文件已不在发布树"
                                    % (key, rel))
                    continue
                if seal is not None and rel not in seal["inventory"]:
                    findings.append("PRODUCER_CODE_UNSEALED|%s 不在封存清册内（未封存的代码不得背书发布结论）"
                                    % rel)
                    continue
                actual = _sha256(target)
                if actual != digest:
                    findings.append("PRODUCER_CODE_DIGEST_DIFFERS|%s 报告写于 %s…，现行是 %s…"
                                    "（改动发生在报告之后：报告的 PASS 不代表现行代码）"
                                    % (rel, str(digest)[:12], actual[:12]))
                sealed = (seal or {}).get("inventory_digests", {}).get(rel)
                if sealed is not None and sealed.upper() != str(digest).upper():
                    # 报告写出的那一刻，工作区代码就已经和封条不同：这份 PASS 不是发布版的结论。
                    findings.append("PRODUCER_CODE_NOT_MATCHING_SEAL|%s 报告声明 %s…，"
                                    "但封条登记的是 %s…（产报告时工作树已与封存版不一致）"
                                    % (rel, str(digest)[:12], sealed[:12]))
        inputs = body.get("inputs")
        if not isinstance(inputs, dict):
            findings.append("PRODUCER_CODE_KEY_MISSING|inputs 必须是对象（可为空，但键必须在）")
        elif recheck_inputs:
            for label, rec in sorted(inputs.items()):
                if not isinstance(rec, dict) or not rec.get("path"):
                    findings.append("PRODUCER_INPUTS_NOT_MEASURABLE|%s 缺少可复算的 path" % label)
                    continue
                p = Path(rec["path"])
                if not p.is_file():
                    findings.append("PRODUCER_INPUTS_NOT_MEASURABLE|%s 指向 %s，文件不存在"
                                    % (label, rec["path"]))
                    continue
                if _sha256(p) != rec.get("sha256"):
                    findings.append("PRODUCER_INPUT_DIGEST_DIFFERS|%s 声明 %s…，现行字节是 %s…"
                                    % (label, str(rec.get("sha256"))[:12], _sha256(p)[:12]))
    if blob is not None and b"\r\n" in blob:
        findings.append("PRODUCER_REPORT_BYTES_DIFFER|报告文件含 CRLF：Windows write_text 漂移，"
                        "同一输入在两台机器上不是同一份字节")
    # 封闭集自证：任何没登记的 code 一律按不可信处理，防止「新加了检查但忘了在册」变成哑检查。
    unknown = sorted({f.split("|", 1)[0] for f in findings} - set(VERIFY_CODES))
    if unknown:
        findings.append("PRODUCER_UNREGISTERED_CODE|verify 产出了未登记的 code：%s"
                        % ", ".join(unknown))

    trust = "TRUSTED" if not findings else "UNTRUSTED"
    return {"report": str(path_or_payload) if isinstance(path_or_payload, (str, Path)) else "in-memory",
            "trust": trust, "self_verdict": trust,
            "stamp_role": (body or {}).get("gate_role"),
            "stamp_version": (body or {}).get("stamp_version"),
            "identity_sha256": (body or {}).get("identity_sha256"),
            "run_at_utc": (body or {}).get("run_at_utc"),
            "findings": findings, "producer": body}


def require_trusted(report_path_or_payload, root: Path | None = None, context: str = "") -> dict:
    """Blocking wrapper for gates that consume another gate's report."""
    result = verify_report(report_path_or_payload, root)
    if result["trust"] != "TRUSTED":
        prefix = "%s: " % context if context else ""
        raise ValueError(prefix + "被消费的门禁报告不可信（§10：PASS 必须能追到产码与输入）；"
                         + "; ".join(result["findings"][:6]))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="复算门禁报告的产出者身份（V0-L17）")
    ap.add_argument("--report", action="append", required=True, dest="reports",
                    help="可重复：要复算的门禁报告 JSON")
    ap.add_argument("--out", default="", help="把复算结果写成 JSON（LF）")
    ap.add_argument("--skill-root", default=str(ROOT))
    args = ap.parse_args()
    root = Path(args.skill_root).resolve()
    rows = []
    bad = 0
    for item in args.reports:
        result = verify_report(item, root)
        rows.append(result)
        if result["trust"] != "TRUSTED":
            bad += 1
    payload = {"stamp_version": STAMP_VERSION, "reports": len(rows), "untrusted": bad,
               "verdict": "PASS" if bad == 0 else "FAIL", "results": rows}
    blob = serialize(payload)
    if args.out:
        Path(args.out).write_bytes(blob)
    print(json.dumps({"verdict": payload["verdict"], "reports": payload["reports"],
                      "untrusted": payload["untrusted"],
                      "findings": [f for r in rows for f in r["findings"]][:40]},
                     ensure_ascii=False, indent=2))
    return 1 if payload["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
