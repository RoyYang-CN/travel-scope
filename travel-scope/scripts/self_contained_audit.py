# -*- coding: utf-8 -*-
"""V5-D（V0-L11）单文件自包含字节对账：读者要下载的那串字节，必须有人替他数过。

分工是刻意的（§10「一处规则只有一个来源」）：
  * 本模块数文件级事实：file_bytes / 内联文本字节 / 解码图片字节 / 容器开销 / 引用结构
    （死 blob、悬空 asset:// 引用、走文件的图片引用、产物声称的内联上限）。
  * 「按 digest 比对交付字节与 asset-manifest/在盘文件」仍由 local_media_gate.attest_delivered_images
    唯一持有；这里不重算摘要链，否则又长出第二套图片规则（v4.2.1 的四处 CJK 计数就是前车之鉴）。
预算与围栏一律从 references/single-file-delivery-policy.json 读；缺配置即阻断，不猜默认值。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    from gate_producer import write_stamped_report
    import single_file_policy
except ImportError:  # pragma: no cover
    from scripts.gate_producer import write_stamped_report
    from scripts import single_file_policy  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = single_file_policy.POLICY_PATH
POLICY_ID = single_file_policy.POLICY_ID
PRODUCING_CODE = ("scripts/self_contained_audit.py", "scripts/gate_producer.py",
                  "scripts/single_file_policy.py")
PRODUCING_CONFIG = ("references/single-file-delivery-policy.json",)
SEVERITY_ORDER = {"blocking": 0, "advisory": 1}

DATA_URI_RE = re.compile(r"data:(image/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=]{16,})")
BLOB_TABLE_KEY_RE = re.compile(r"\"([0-9a-f]{64})\"\s*:\s*\"data:image")
ASSET_REF_RE = re.compile(r"asset://sha256:([0-9a-f]{64})")
IMG_TAG_RE = re.compile(r"<img\b[^>]*?>", re.IGNORECASE)
SRC_ATTR_RE = re.compile(r"src\s*=\s*[\"']([^\"']*)[\"']", re.IGNORECASE)
MASKED_REF_RE = re.compile(r"MASKED[A-Z0-9_./+-]{0,40}")

SingleFilePolicyError = single_file_policy.SingleFilePolicyError
load_policy = single_file_policy.load_policy
severity = single_file_policy.severity
declared_media_cap = single_file_policy.declared_media_cap


def blocking_findings(findings, policy: dict | None = None) -> list[str]:
    return single_file_policy.split_findings(findings, policy)[0]


def advisory_findings(findings, policy: dict | None = None) -> list[str]:
    return single_file_policy.split_findings(findings, policy)[1]


def account(html_path, policy: dict | None = None) -> dict:
    """将单个交付 HTML 还原成读者要付的字节账单（不判对错，只把事实数出来）。"""
    path = Path(html_path)
    measured: dict = {"html": str(path).replace("\\", "/")}
    if not path.is_file():
        measured.update({"file_missing": True, "file_bytes": 0})
        return measured
    raw = path.read_bytes()
    measured["file_missing"] = False
    measured["file_bytes"] = len(raw)
    measured["file_sha256"] = hashlib.sha256(raw).hexdigest().upper()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        measured["unreadable"] = f"UTF-8 解码失败: {exc}"
        return measured
    measured["unreadable"] = ""

    blobs = DATA_URI_RE.findall(text)
    decoded_sizes = []
    decoded_total = 0
    text_total = 0
    digest_counts: dict[str, int] = {}
    undecodable = 0
    for mime, blob in blobs:
        try:
            data = base64.b64decode(blob)
        except Exception:
            undecodable += 1
            data = b""
        size = len(data)
        decoded_sizes.append(size)
        decoded_total += size
        text_total += len(f"data:{mime};base64,{blob}".encode("utf-8"))
        if size:
            digest = hashlib.sha256(data).hexdigest()
            digest_counts[digest] = digest_counts.get(digest, 0) + 1

    table_keys = set(BLOB_TABLE_KEY_RE.findall(text))
    refs = set(ASSET_REF_RE.findall(text))
    img_tags = IMG_TAG_RE.findall(text)
    srcs = [SRC_ATTR_RE.search(tag).group(1) if SRC_ATTR_RE.search(tag) else "" for tag in img_tags]
    external = sorted({src for src in srcs
                       if src and not src.startswith(("data:", "asset://"))})
    # MASKED 是历史构建里「这张图被抹掉了」的记号，它可能挂在任何前缀上，所以单独扫一遍全文，
    # 不藏在 external 的子集里：抹掉不等于没写，读者仍然会看到一块空位。
    masked = sorted({match.strip() for match in MASKED_REF_RE.findall(text)})[:6]
    cap = declared_media_cap(text)
    cap_bytes = (policy or load_policy())["media_delivery"]["default_max_inline_kb"] * 1024

    measured.update({
        "img_tags": len(img_tags),
        "inline_blob_texts": len(blobs),
        "unique_inline_blobs": len(digest_counts),
        "duplicate_blob_texts": len(blobs) - len(digest_counts),
        "undecodable_blobs": undecodable,
        "blob_text_bytes": text_total,
        "decoded_blob_bytes": decoded_total,
        "container_bytes": len(raw) - text_total,
        "blob_base64_inflation": round(text_total / max(1, decoded_total), 4),
        "largest_decoded_blob": max(decoded_sizes, default=0),
        "blob_table_keys": len(table_keys),
        "asset_refs": len(refs),
        "dead_blobs": sorted(table_keys - refs),
        "dangling_asset_refs": sorted(refs - table_keys),
        "static_src_attributes": len(srcs),
        "static_external_img_refs": external[:12],
        "static_external_img_ref_count": len(external),
        "masked_img_refs": masked[:6],
        "declared_media_cap_kb": cap,
        "registered_max_inline_kb": cap_bytes // 1024,
        "blob_over_registered_cap": [size for size in decoded_sizes if size > cap_bytes],
    })
    # 这里只声明「文件自己写不写外部图」这一件事。读者页运行时还会由 JS 往 <img> 上挂
    # assets/… 路径，那是 DOM 侧的事实，归 visual_qa 的 IMG_RENDERED_* 判——静态扫不到就
    # 假装自包含通过，正是 v4.2.1 那种「门禁读不到读者看到的」的老坑（V0-L07 同族）。
    measured["static_markup_self_contained"] = (len(external) == 0
                                                and not measured["dangling_asset_refs"]
                                                and measured["inline_blob_texts"] > 0)
    return measured


def findings(measured: dict, policy: dict | None = None) -> list[str]:
    """对账单逐条判严重度；advisory 也必须留痕，不许因为『不算违规』就消失。"""
    if policy is None:
        try:
            policy = load_policy()
        except SingleFilePolicyError as exc:
            return [f"SFD_POLICY_MISSING|{exc}"]
    codes: list[str] = []
    budget = policy["budgets"]
    cap_kb = policy["media_delivery"]["default_max_inline_kb"]
    if measured.get("file_missing"):
        return [f"SFD_FILE_MISSING|要审计的交付文件不存在: {measured.get('html')}"]
    if measured.get("unreadable"):
        codes.append(f"SFD_FILE_UNREADABLE|交付文件无法按 UTF-8 读取，字节账单读不出来（未判定不等于通过）: "
                     f"{measured['unreadable']}")
        return codes
    file_bytes = int(measured.get("file_bytes") or 0)
    fence = int(budget["max_delivered_file_bytes"])
    if file_bytes > fence:
        codes.append(
            f"SFD_FILE_BYTES_OVER_FENCE|单文件 {file_bytes:,}B 超过登记围栏 {fence:,}B"
            f"（=1.25×v4.2.1 已接受成品 4,609,946B），读者要多下载 "
            f"{(file_bytes - fence) / 1048576:.2f}MiB；要么解释增长，要么由业主裁决改登记")
    # 交付图总预算由围栏反推（delivered_rendition_ladder.budgets），所以这一条不是「另一套尺寸焦虑」，
    # 而是围栏在图片侧的可执行形式：图片合计超限＝这份产物不可能同时守住围栏与全内联。
    total_budget = int((policy.get("delivered_rendition_ladder") or {}).get(
        "budgets", {}).get("total_delivered_image_decoded_bytes_max") or 0)
    decoded = int(measured.get("decoded_blob_bytes") or 0)
    if total_budget and decoded > total_budget:
        codes.append(
            f"SFD_DELIVERED_TOTAL_OVER_BUDGET|产物内联图片解码字节合计 {decoded:,}B，超过登记总预算 "
            f"{total_budget:,}B（＝围栏 {fence:,}B 减实测容器后 ×3/4）；分母＝这页真带的 "
            f"{measured.get('blob_table_keys', 0)} 段内联图，读者为它们下载 "
            f"{(decoded - total_budget) * 4 // 3:,}B 的超限部分")
    dead = measured.get("dead_blobs") or []
    if dead and float(budget["max_dead_blob_share_of_image_text"]) == 0.0:
        codes.append(
            f"SFD_DEAD_BLOB|{len(dead)}/{measured['blob_table_keys']} 段内联字节进了文件却没有任何 "
            f"asset:// 引用指向它，读者下载了但永远画不出来: {[d[:12] for d in dead[:6]]}")
    dangling = measured.get("dangling_asset_refs") or []
    if dangling:
        codes.append(
            f"SFD_DANGLING_ASSET_REF|{len(dangling)} 处 asset://sha256: 引用在 D.asset_blobs 里没有对应键，"
            f"页面上那张图只能落进 error 兜底: {[d[:12] for d in dangling[:6]]}")
    if measured.get("static_external_img_ref_count"):
        codes.append(
            f"SFD_STATIC_EXTERNAL_IMG_REF|产物自己的标记里有 "
            f"{measured['static_external_img_ref_count']} 个写死的文件图片引用，"
            f"读者单独拿到这个 HTML 时看不到图: {measured['static_external_img_refs'][:5]}")
    if measured.get("masked_img_refs"):
        codes.append(
            f"SFD_MASKED_IMG_REF|{len(measured['masked_img_refs'])} 个被 MASKED 处理的图片引用仍留在产物里: "
            f"{measured['masked_img_refs'][:3]}")
    cap = measured.get("declared_media_cap_kb")
    if cap is None:
        codes.append(
            f"SFD_MEDIA_CAP_UNMARKED|产物没有 <meta name=\"travel-scope-media-cap\">，"
            f"无法知道这次内联用的是哪一档上限（登记值 {cap_kb}KB）")
    elif cap != cap_kb:
        codes.append(
            f"SFD_MEDIA_CAP_DIFFERS|产物自称内联上限 {cap}KB，与登记值 {cap_kb}KB 不一致："
            f"构建参数与配置已经漂移，字节账单不能当作本次配置的结论")
    if measured.get("blob_over_registered_cap"):
        sizes = measured["blob_over_registered_cap"]
        codes.append(
            f"SFD_BLOB_OVER_REGISTERED_CAP|{len(sizes)} 段内联图片解码后超过登记上限 "
            f"{cap_kb}KB（最大 {max(sizes) / 1024:.0f}KB），单文件代价由它决定")
    return codes


def audit(html_path, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    measured = account(html_path, policy)
    found = findings(measured, policy)
    return {"policy_id": policy["id"],
            "status": "PASS" if not blocking_findings(found, policy) else "FAIL",
            "measured": measured,
            "findings": found,
            "blocking": blocking_findings(found, policy),
            "advisory": advisory_findings(found, policy)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Travel-Scope 单文件自包含字节对账（V0-L11）")
    parser.add_argument("--html", action="append", required=True,
                        help="要审计的交付 HTML，可重复；每个都出一张字节账单")
    parser.add_argument("--report", default="", help="盖章报告输出路径")
    args = parser.parse_args(argv)
    payload = {"audits": [audit(path) for path in args.html]}
    payload["status"] = "PASS" if all(item["status"] == "PASS" for item in payload["audits"]) else "FAIL"
    if args.report:
        write = __import__("gate_producer").write_stamped_report(
            args.report, payload, gate_role="self_contained_audit",
            producing_code=list(PRODUCING_CODE), producing_config=list(PRODUCING_CONFIG))
        payload["report_sha256"] = write["sha256"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
