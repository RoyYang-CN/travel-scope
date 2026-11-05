# -*- coding: utf-8 -*-
"""V5-D：单文件交付的登记值只有一个来源——references/single-file-delivery-policy.json。

渲染器要用的内联上限、visual_qa 要用的图片预算、门禁要用的围栏与错误码，以前各自写常数
（visual_qa.py 里就有 1200 / 80KB / 4MB 三个裸数），改一处忘一处就是 §10 说的「门槛被悄悄降低」。
本模块只读配置并校验它自洽，不判定任何产物——判定在 self_contained_audit / visual_qa。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "references" / "single-file-delivery-policy.json"
POLICY_ID = "v4.2.2-single-file-delivery-1"

REQUIRED_SECTIONS = ("id", "measurement", "media_delivery", "budgets", "reason_codes",
                     "severity_note", "non_goals", "delivered_rendition_ladder")
REQUIRED_BUDGETS = ("max_delivered_file_bytes", "hero_inline_budget_bytes",
                    "total_inline_budget_bytes", "max_delivered_image_width_px",
                    "max_dead_blob_share_of_image_text")
REQUIRED_MEASUREMENT = ("file_bytes", "blob_text_bytes", "decoded_blob_bytes", "container_bytes",
                        "dead_blob", "dangling_asset_ref", "single_implementation")
REQUIRED_LADDER_KEYS = ("ratified_by", "id", "slots", "encode", "budgets", "measured_sweep",
                        "non_goals", "min_delivered_geometry")
# JPEG 编码旗标也是交付档的一部分：它决定在盘字节，也决定读者看到的色彩细节。
# subsampling=2 曾把一张真全景照的 color entropy 压到真实性门下限之下（见登记 encode.note），
# 所以它必须是登记值而不是 prepare_media 里的裸参数。
ALLOWED_SUBSAMPLING = (0, 1, 2)
REQUIRED_ENCODE_KEYS = ("subsampling", "optimize", "progressive", "why_registered",
                        "measured_consequence")
# V6-R：交付几何下限原来是 local_media_gate 里的两个裸数（640/360）。产图模块按宽度等比
# 缩档，遇到 1600×533 这种全景源就会把高度压到 333——自己产出一张注定被门拒掉的图，
# 而且拒的是「读者拿不到这张图」，不是「图有小瑕疵」。下限只有一个来源：登记。
REQUIRED_GEOMETRY_KEYS = ("width_px", "height_px", "ratified_by", "why_registered",
                          "read_by", "measured_consequence")
LADDER_ID = "v4.2.2-delivered-rendition-ladder-4"
# 交付槽位必须与 prepare_media 的 SLOT_RENDITIONS 同集合：登记里有槽位没人产、
# 或产图的模块自己新增槽位没登记，都会让「交付档由登记决定」这句话变成一半真话。
LADDER_SLOTS = ("hero", "destination_atmosphere")
ALLOWED_SEVERITIES = ("blocking", "advisory")
MEDIA_CAP_META_NAME = "travel-scope-media-cap"
MEDIA_CAP_META_RE = re.compile(r"<meta\b[^>]*name\s*=\s*[\"']" + MEDIA_CAP_META_NAME +
                               r"[\"'][^>]*>", re.IGNORECASE)
CAP_CONTENT_RE = re.compile(r"content\s*=\s*[\"']([^\"']*)[\"']", re.IGNORECASE)


class SingleFilePolicyError(ValueError):
    """配置缺失/畸形：宁可不判，也不用一个猜出来的预算给读者放行。"""


def load_policy(path: Path | None = None) -> dict:
    policy_path = Path(path) if path else POLICY_PATH
    if not policy_path.is_file():
        raise SingleFilePolicyError(f"单文件交付配置不存在: {policy_path}")
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SingleFilePolicyError(f"单文件交付配置不是合法 JSON: {exc}") from exc
    missing = [key for key in REQUIRED_SECTIONS if key not in policy]
    if missing:
        raise SingleFilePolicyError(f"单文件交付配置缺少段落 {missing}")
    if policy.get("id") != POLICY_ID:
        raise SingleFilePolicyError(
            f"单文件交付配置 id 漂移：期望 {POLICY_ID}，实际 {policy.get('id')!r}")
    budgets = policy.get("budgets") or {}
    missing = [key for key in REQUIRED_BUDGETS if not isinstance(budgets.get(key), (int, float))]
    if missing:
        raise SingleFilePolicyError(f"budgets 段落缺少数值围栏 {missing}")
    if budgets["max_delivered_file_bytes"] <= 0:
        raise SingleFilePolicyError("budgets.max_delivered_file_bytes 必须是正数")
    if budgets["total_inline_budget_bytes"] <= 0 or budgets["hero_inline_budget_bytes"] <= 0:
        raise SingleFilePolicyError("DOM 侧图片预算必须是正数")
    if budgets["hero_inline_budget_bytes"] > budgets["total_inline_budget_bytes"]:
        raise SingleFilePolicyError("首屏单图预算大于全页图片预算：配置本身不自洽")
    measurement = policy.get("measurement") or {}
    missing = [key for key in REQUIRED_MEASUREMENT if not str(measurement.get(key) or "").strip()]
    if missing:
        raise SingleFilePolicyError(f"measurement 段落缺少口径定义 {missing}")
    media = policy.get("media_delivery") or {}
    cap = media.get("default_max_inline_kb")
    if not isinstance(cap, int) or cap <= 0:
        raise SingleFilePolicyError("media_delivery.default_max_inline_kb 必须是正整数")
    if MEDIA_CAP_META_NAME not in str(media.get("declared_in_html") or ""):
        raise SingleFilePolicyError(
            f"media_delivery.declared_in_html 必须登记产物自称上限的标记（含 {MEDIA_CAP_META_NAME}）")
    codes = policy.get("reason_codes") or {}
    if not codes:
        raise SingleFilePolicyError("reason_codes 为空：错误码必须闭集登记")
    unclassified = [code for code, sev in codes.items() if sev not in ALLOWED_SEVERITIES]
    if unclassified:
        raise SingleFilePolicyError(f"错误码没有登记严重度（不允许第三档）: {unclassified}")
    if not str(policy.get("severity_note") or "").strip():
        raise SingleFilePolicyError("severity_note 未登记：advisory 为什么不算通过必须写清楚")
    _validate_ladder(policy)
    return policy


def _validate_ladder(policy: dict) -> None:
    """交付档登记必须自洽到能被两个模块共用，否则它就只是业主裁决的一句注释。"""
    block = policy["delivered_rendition_ladder"]
    if not isinstance(block, dict):
        raise SingleFilePolicyError("delivered_rendition_ladder 必须是对象")
    missing = [key for key in REQUIRED_LADDER_KEYS if not block.get(key)]
    if missing:
        raise SingleFilePolicyError("delivered_rendition_ladder 缺键 %s" % missing)
    if block["id"] != LADDER_ID:
        raise SingleFilePolicyError(
            "交付档登记 id 漂移：期望 %s，实际 %r" % (LADDER_ID, block["id"]))
    slots = block["slots"]
    if sorted(slots) != sorted(LADDER_SLOTS):
        raise SingleFilePolicyError("交付档槽位与产图模块的槽位集合不一致：%s vs %s"
                                    % (sorted(slots), sorted(LADDER_SLOTS)))
    for slot, spec in slots.items():
        width, quality = spec.get("max_width_px"), spec.get("jpeg_quality")
        if not isinstance(width, int) or width <= 0:
            raise SingleFilePolicyError("交付档 %s 的 max_width_px 必须是正整数" % slot)
        if not isinstance(quality, int) or not 1 <= quality <= 95:
            raise SingleFilePolicyError("交付档 %s 的 jpeg_quality 必须在 1..95" % slot)
        tiers = spec.get("tiers")
        if not isinstance(tiers, list) or not tiers:
            raise SingleFilePolicyError("交付档 %s 没有 tiers 列表：产图模块只按 tiers 出档，"
                                        "槽位上的单个 width/quality 只是摘要" % slot)
        labels = [str(tier.get("label") or "") for tier in tiers]
        if len(labels) != len(set(labels)) or "" in labels:
            raise SingleFilePolicyError("交付档 %s 的 tier label 重复或为空：%s" % (slot, labels))
        for tier in tiers:
            if int(tier.get("max_width_px") or 0) > width:
                raise SingleFilePolicyError(
                    "交付档 %s/%s 宽 %s 超过槽位声明的 max_width_px %s"
                    % (slot, tier.get("label"), tier.get("max_width_px"), width))
        if not str(block.get("tier_count_note") or "").strip():
            raise SingleFilePolicyError("每槽只出一档是本轮的实质改动（第二档在全内联下就是死字节），"
                                        "必须有 tier_count_note 说明，不能默默改掉")
    budgets = block["budgets"]
    encode = block["encode"]
    if not isinstance(encode, dict):
        raise SingleFilePolicyError("交付档 encode 必须是对象：编码旗标和尺寸/质量同属一档")
    missing = [key for key in REQUIRED_ENCODE_KEYS if key not in encode]
    if missing:
        raise SingleFilePolicyError("交付档 encode 缺键 %s（旗标值与它造成的实测后果都要登记）"
                                    % missing)
    if encode["subsampling"] not in ALLOWED_SUBSAMPLING:
        raise SingleFilePolicyError("交付档 encode.subsampling 必须是 %s 之一，实际 %r"
                                    % (ALLOWED_SUBSAMPLING, encode["subsampling"]))
    for key in ("optimize", "progressive"):
        if not isinstance(encode[key], bool):
            raise SingleFilePolicyError("交付档 encode.%s 必须是布尔值" % key)
    geometry = block["min_delivered_geometry"]
    if not isinstance(geometry, dict):
        raise SingleFilePolicyError("交付档 min_delivered_geometry 必须是对象：产图和媒体门"
                                    "共用一把尺寸下限，裸数留在任一侧就是第二套规则")
    missing = [key for key in REQUIRED_GEOMETRY_KEYS if key not in geometry]
    if missing:
        raise SingleFilePolicyError("交付档 min_delivered_geometry 缺键 %s" % missing)
    for key in ("width_px", "height_px"):
        if not isinstance(geometry[key], int) or geometry[key] <= 0:
            raise SingleFilePolicyError("min_delivered_geometry.%s 必须是正整数" % key)
    if not str(geometry.get("ratified_by") or "").strip():
        raise SingleFilePolicyError("min_delivered_geometry.ratified_by 不能为空")
    readers = [str(item) for item in (geometry.get("read_by") or [])]
    if "scripts/prepare_media.py" not in readers or "scripts/local_media_gate.py" not in readers:
        raise SingleFilePolicyError(
            "min_delivered_geometry.read_by 必须同时登记产图模块与媒体门：只登记一侧，"
            "另一侧迟早退回裸数（V0-L11 的老路）")
    cap_bytes = int(policy["media_delivery"]["default_max_inline_kb"]) * 1024
    per_image = int(budgets.get("max_delivered_image_decoded_bytes") or 0)
    if per_image != cap_bytes:
        raise SingleFilePolicyError(
            "交付档单图上限必须等于内联上限 ×1024（%d != %d）：两者不一致就意味着"
            "登记允许一张注定无法内联的交付图，单文件交付在 DOM 侧必破" % (per_image, cap_bytes))
    total = int(budgets.get("total_delivered_image_decoded_bytes_max") or 0)
    fence = int(policy["budgets"]["max_delivered_file_bytes"])
    if total <= 0:
        raise SingleFilePolicyError("交付档总预算必须是正数")
    if total * 4 // 3 >= fence:
        raise SingleFilePolicyError(
            "交付档总预算 %d 按 4/3 内联膨胀后 ≥ 围栏 %d：这条登记本身就会破围栏，"
            "不可能有产物同时满足两条门禁" % (total, fence))
    if int(policy["budgets"]["total_inline_budget_bytes"]) != total:
        raise SingleFilePolicyError(
            "DOM 侧全页图片预算与交付档总预算必须相等（%d != %d）：以前各写 4,194,304 与围栏"
            "反推值两份，谁也没被拿去对账" % (
                int(policy["budgets"]["total_inline_budget_bytes"]), total))
    sweep = block["measured_sweep"]
    rows = sweep.get("rows") or []
    if not rows:
        raise SingleFilePolicyError("交付档登记没有实测档位表：选档必须由测量支撑")
    chosen = sweep.get("chosen")
    chosen_rows = [row for row in rows if row.get("ladder_name") == chosen]
    if not chosen_rows:
        raise SingleFilePolicyError("chosen 档位 %r 不在实测表里" % chosen)
    for row in chosen_rows:
        if row["over_fence"] or not row["self_contained_in_dom"]:
            raise SingleFilePolicyError(
                "chosen 档位 %s 在 %s 上既不自包含或不守围栏，不能当登记值"
                % (chosen, row["run"]))
    for code in ("SFD_DELIVERED_TOTAL_OVER_BUDGET", "IMG_DELIVERED_OVER_INLINE_CAP",
                 "IMG_DELIVERED_LADDER_UNREGISTERED"):
        if code not in (policy.get("reason_codes") or {}):
            raise SingleFilePolicyError("交付档预算错误码 %s 未登记严重度" % code)


def rendition_ladder(policy: dict | None = None) -> dict:
    """产图模块（prepare_media）唯一读取交付档的入口。"""
    block = (policy or load_policy())["delivered_rendition_ladder"]
    return {"slots": {slot: [tuple((str(tier["label"]), int(tier["max_width_px"]),
                                   int(tier["jpeg_quality"])))
                             for tier in spec["tiers"]]
                      for slot, spec in block["slots"].items()},
            "max_delivered_image_decoded_bytes":
                int(block["budgets"]["max_delivered_image_decoded_bytes"]),
            "total_delivered_image_decoded_bytes_max":
                int(block["budgets"]["total_delivered_image_decoded_bytes_max"]),
            "encode": {key: block["encode"][key] for key in ("subsampling", "optimize",
                                                            "progressive")},
            "min_delivered_width_px": int(block["min_delivered_geometry"]["width_px"]),
            "min_delivered_height_px": int(block["min_delivered_geometry"]["height_px"]),
            "ladder_id": block["id"], "ratified_by": block["ratified_by"],
            "authority": "references/single-file-delivery-policy.json::delivered_rendition_ladder"}


def registered_max_inline_kb(policy: dict | None = None) -> int:
    return int((policy or load_policy())["media_delivery"]["default_max_inline_kb"])


def delivered_geometry_floor(policy: dict | None = None) -> tuple[int, int]:
    """交付图的尺寸下限（宽, 高）。产图模块与媒体门都必须从这里取。

    V6-R 之前它只是 local_media_gate 里的 `width < 640 or height < 360` 两个裸数：产图侧看不见它，
    于是等比缩档能产出一张 1000×333 的图，媒体门再把它判成不合规——两侧都"照自己的规则办事"，
    代价是读者拿不到那张照片。登记成一处之后，钳制与判定用的是同一个数。
    """
    geometry = (policy or load_policy())["delivered_rendition_ladder"]["min_delivered_geometry"]
    return int(geometry["width_px"]), int(geometry["height_px"])


def severity(code: str, policy: dict | None = None) -> str:
    policy = policy or load_policy()
    return (policy.get("reason_codes") or {}).get(code, "UNREGISTERED")


def split_findings(findings, policy: dict | None = None) -> tuple[list[str], list[str]]:
    """blocking / advisory 各归各，但两边都留在报告里。"""
    policy = policy or load_policy()
    blocking, advisory = [], []
    for item in findings:
        code = str(item).split("|", 1)[0]
        level = severity(code, policy)
        if level == "blocking":
            blocking.append(item)
        elif level == "advisory":
            advisory.append(item)
        else:
            raise SingleFilePolicyError(
                f"错误码 {code} 没有在闭集登记，不允许当作结论 emit（注册表与实现必须双向核对）")
    return blocking, advisory


def media_cap_meta_html(cap_kb: int) -> str:
    if not isinstance(cap_kb, int) or cap_kb <= 0:
        raise SingleFilePolicyError(f"写进产物的上限标记必须是正整数 KB，收到 {cap_kb!r}")
    return f'<meta name="{MEDIA_CAP_META_NAME}" content="{cap_kb}">'


def declared_media_cap(text: str) -> int | None:
    tag = MEDIA_CAP_META_RE.search(text)
    if not tag:
        return None
    content = CAP_CONTENT_RE.search(tag.group(0))
    if not content:
        return None
    try:
        return int(str(content.group(1)).strip())
    except ValueError:
        return None
