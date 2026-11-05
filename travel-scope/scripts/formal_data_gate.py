"""Cross-artifact truth gate for formal Travel-Scope Live runs.
Version: V4.0.12
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from map_contract import audit_map_targets, parse_coords, target_key
except ImportError:  # pragma: no cover
    from scripts.map_contract import audit_map_targets, parse_coords, target_key

try:  # v4.2.2 V4-B：地图发布门禁（严重性分类 + 零调用账本），历史夹具不强制
    import map_gate_v422
    import zero_call_sentinel
except ImportError:  # pragma: no cover
    import scripts.map_gate_v422 as map_gate_v422
    import scripts.zero_call_sentinel as zero_call_sentinel

try:  # v4.2.2 V5-A：报告必须带产出者身份（V0-L17）
    import gate_producer
except ImportError:  # pragma: no cover
    import scripts.gate_producer as gate_producer

try:  # v4.2.2 V5-B：汇率契约唯一登记处（V0-L05）
    import budget_contract
except ImportError:  # pragma: no cover
    import scripts.budget_contract as budget_contract

try:
    from app_contract import validate_local_apps
except ImportError:  # pragma: no cover
    from scripts.app_contract import validate_local_apps

try:
    from provenance_contract import audit_run_provenance
except ImportError:  # pragma: no cover
    from scripts.provenance_contract import audit_run_provenance

try:  # ZH-RELEASE-1（业主 2026-11-02 裁 Q2-A）：读者来源面只有投影这一个实现，判据不在本文件重写
    import source_projection
except ImportError:  # pragma: no cover
    import scripts.source_projection as source_projection

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "references/run-quality-policy.json").read_text(encoding="utf-8"))
CURRENT_VERSION = "5.0.0"

# V5-A（V0-L17）：这份报告的结论由下面这些**已封存**的代码与配置得出。
# 列不全＝报告可能来自一支没人复核过的组合；列了未入册的文件＝盖章直接被拒（gate_producer.stamp）。
PRODUCING_CODE = ("scripts/formal_data_gate.py", "scripts/gate_producer.py", "scripts/map_contract.py",
                  "scripts/map_gate_v422.py", "scripts/data_model.py", "scripts/zero_call_sentinel.py",
                  "scripts/app_contract.py", "scripts/provenance_contract.py",
                  "scripts/budget_contract.py", "scripts/source_projection.py")
PRODUCING_CONFIG = ("references/run-quality-policy.json", "references/data-model.json",
                    "references/map-gate-v422.json", "references/map-link-selection.json",
                    "references/provenance-policy.json", "references/budget-policy.json")
BUDGET_POLICY = budget_contract.load_policy()




def _read(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _day_number(value: Any) -> int | None:
    match = re.fullmatch(r"Day\s+(\d+)", str(value).strip(), re.I)
    return int(match.group(1)) if match else None


def _corridor_signature(route: list[Any]) -> str:
    return re.sub(r"\s+", "", str(route[2] if len(route) > 2 else "")).casefold()


def _direct_url(value: Any, *, schedule: bool = False) -> bool:
    val_str = str(value or "").strip()
    parsed = urlsplit(val_str)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    query = parse_qs(parsed.query)
    if any(key.lower() in {"q", "query", "keyword", "search"} for key in query):
        return False
    if any(token in parsed.path.casefold() for token in ("/search", "/maps/search")):
        return False
    # V4.0.5: Disallow synthetic / patterned entity URLs like /entity/0001, /entity/1.html
    if re.search(r"/entity/\d+(\.html)?$", parsed.path.casefold()):
        return False
    # V4.0.8: Disallow sequential numbered patterns like -0001, /dest-0001, my-kuala-lumpur-0001
    if re.search(r"(?:^|/|[-_])[a-z0-9]+[-_]\d{3,6}(?:\.html)?$", parsed.path.casefold()):
        return False
    if re.search(r"[-_/]000\d+(?:\.html)?$", parsed.path.casefold()):
        return False
    if schedule and parsed.path in {"", "/"} and not parsed.query:
        return False

    # V4.0.7: Disallow unencoded Chinese characters concatenated directly into path
    if re.search(r"[\u4e00-\u9fff]", parsed.path):
        return False

    # V4.0.7 / V4.1.0: Platform-specific pattern verification (G10 anti-synthetic gate)
    hostname = parsed.hostname.lower()
    if "/food-and-dining/" in parsed.path.casefold():
        return False
    if "hotels.ctrip.com" in hostname:
        # Real Ctrip hotel pages must have numeric ID, e.g. /hotels/741779.html, /hotel/37899675.html or /hotels/detail/741779.html
        if not re.search(r"/(?:hotels|hotel)/(?:detail/)?\d+\.html", parsed.path.casefold()):
            return False
    elif "you.ctrip.com" in hostname and "/sight/" in parsed.path.casefold():
        # Real Ctrip sight pages must have district and sight numeric ID, e.g. /sight/manzhouli319/61401.html
        if not re.search(r"/sight/[a-zA-Z0-9]+/\d+\.html", parsed.path.casefold()):
            return False
    elif "dianping.com" in hostname and "/shop/" in parsed.path.casefold():
        # Real Dianping pages must have shop ID
        if not re.search(r"/shop/[a-zA-Z0-9]+", parsed.path.casefold()):
            return False
    elif "tripadvisor." in hostname:
        # G10: Real TripAdvisor entity pages must have BOTH geo ID (-g\d+) and detail ID (-d\d+)
        if not (re.search(r"-g\d+", parsed.path) and re.search(r"-d\d+", parsed.path)):
            return False
        if not re.search(r"/(?:Hotel|Restaurant|Attraction)_Review-g\d+-d\d+", parsed.path, re.I):
            return False
    elif "padi.com" in hostname:
        # G10: Real PADI dive site pages must follow /dive-site/<country>/<site-slug>/ or /dive-shop/
        if "/dive-" in parsed.path.casefold():
            if "/dive-sites/" in parsed.path.casefold():
                return False
            if not re.search(r"/dive-(?:site|shop)/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+", parsed.path.casefold()):
                return False
    elif "booking.com" in hostname:
        # G10: Real Booking hotel page must follow /hotel/{country_code}/{slug}.html
        if "/hotel/" in parsed.path.casefold():
            if not re.search(r"/hotel/[a-z]{2}/[a-zA-Z0-9_-]+\.html", parsed.path.casefold()):
                return False

    return True



def _coord_equal(left: Any, right: Any, tolerance: float = 0.00005) -> bool:
    a, b = parse_coords(left), parse_coords(right)
    return bool(a and b and abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance)


def _audit_translations(data: dict[str, Any], errors: list[str], *, base_dir: str | Path | None = None) -> None:
    # 1. 检查是否存在包含未翻译词项的文件
    if base_dir:
        for fname in ("untranslated.json", "untranslated_by_kind.json"):
            for cand in (Path(base_dir) / fname, Path(base_dir).parent / fname, Path(base_dir).parent / "outputs" / fname):
                if cand.is_file():
                    try:
                        content = json.loads(cand.read_text(encoding="utf-8"))
                        count = len(content) if isinstance(content, (list, dict)) else 0
                        if count > 0:
                            errors.append(f"存在未翻译词项文件 {fname} (共 {count} 条未完成翻译，严禁直接放行)")
                    except Exception:
                        pass

    # 2. 检查数据中的英文内容是否包含荒谬重复占位词或套话
    banned_tokens = POLICY.get("translation_rules", {}).get("banned_synthetic_phrases", [])
    disallowed_patterns = [
        re.compile(r"\bSpot\s+Spot\b", re.I),
        re.compile(r"\b\d+\s+days?\s+\d+\s+Spot\b", re.I),
    ]
    for banned in banned_tokens:
        disallowed_patterns.append(re.compile(r"\b" + re.escape(banned) + r"\b", re.I))

    def scan_obj(obj: Any, path: str = ""):
        if isinstance(obj, str):
            for pat in disallowed_patterns:
                if pat.search(obj):
                    errors.append(f"发现违规机器生成/占位符套话 ({path}): {pat.pattern} -> '{obj[:80]}'")
                    break
        elif isinstance(obj, dict):
            for k, v in obj.items():
                scan_obj(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for idx, elem in enumerate(obj):
                scan_obj(elem, f"{path}[{idx}]")

    scan_obj(data.get("routes"), "routes")
    scan_obj(data.get("itinerary"), "itinerary")
    scan_obj(data.get("editorial_media"), "editorial_media")
    scan_obj(data.get("section_media"), "section_media")


def registered_reader_face_key() -> str:
    """读者来源面的键名只有一个登记处：references/data-model.json::source_evidence_reader_face。

    按字节读（同 scripts/source_projection.py::registry 的理由）：负样本测试会全局 patch
    Path.read_text，判定表在那种环境里重新读盘会假报「配置缺失」。
    """
    model = json.loads((ROOT / "references" / "data-model.json").read_bytes().decode("utf-8"))
    key = str(model.get("source_evidence_reader_face") or "").strip()
    if not key:
        raise source_projection.ProjectionError(
            "registry_missing",
            "references/data-model.json 缺少 source_evidence_reader_face（读者来源面唯一登记处）")
    return key


def transport_visible_pairs(data: dict[str, Any]) -> set[tuple[str, str]]:
    """交通枢纽在读者页是**看得见**的实体（交通表里的节点），所以它们是来源台账的合法主体。

    旧的位置面循环靠 provider 白名单（权威点评目录/订房平台直达/专业潜水机构）才没碰到枢纽行；
    投影面按 evidence_level 取值域之后枢纽行进入了检查范围，因此必须把「它住在哪张读者表里」
    写清楚，而不是假装枢纽是虚构实体。
    """
    pairs: set[tuple[str, str]] = set()
    for row in data.get("transport_nodes") or []:
        if isinstance(row, dict):
            pairs.add((str(row.get("destination") or "").strip(),
                       str(row.get("name") or "").strip()))
        elif isinstance(row, list) and len(row) > 1:
            pairs.add((str(row[0]).strip(), str(row[1]).strip()))
    return pairs


def project_reader_source_face(rows: list[Any], *, reg: dict | None,
                               errors: list[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """机器面 → 读者面：逐行走唯一投影实现，不认识的形状＝带码的错误，绝不 continue。

    一条不认的记录被跳过，就是 #113 里「读者页少 174/365 条来源而门说 PASS」的成因；
    这里把跳过换成立册的错误码清册，谁被咬住一目了然。
    """
    projected: list[dict[str, Any]] = []
    codes: dict[str, int] = {}
    samples: list[str] = []
    seen_samples: set[str] = set()
    bad_rows = 0
    for index, record in enumerate(rows):
        try:
            projected.append(source_projection.project([record], reg=reg)[0])
        except source_projection.ProjectionError as exc:
            bad_rows += 1
            codes[exc.code] = codes.get(exc.code, 0) + 1
            sample = "%s: %s" % (exc.code, exc.detail)
            if sample not in seen_samples and len(samples) < 8:
                seen_samples.add(sample)
                samples.append("row[%s] %s" % (exc.index, sample))
        except Exception as exc:  # noqa: BLE001 非投影异常不得被当成形状问题吞掉
            bad_rows += 1
            codes["projection_unclassified"] = codes.get("projection_unclassified", 0) + 1
            if len(samples) < 8:
                samples.append("row[%d] projection_unclassified: %r" % (index, exc))
    if codes:
        errors.append(
            "READER_SOURCE_FACE_INVALID|读者来源面（data-model.json::source_evidence_reader_face "
            "指向的那一面）共 %d 行，其中 %d 行是未注册形状（%d 种码）："
            "%s；错误码闭集见 scripts/source_projection.py::ERROR_CODES，词表见 "
            "references/data-model.json（source_verification_statuses / source_evidence_levels）。"
            "不认识的形状不许继续往下走"
            % (len(rows), bad_rows, len(codes), "; ".join(samples)))
    return projected, codes


def audit_reader_source_face(data: dict[str, Any], visible_names: set[tuple[str, str]],
                             errors: list[str], warnings: list[str]) -> dict[str, Any]:
    """读者来源面：投影校验＋两项今天真会阻断的检查＋十列位置面的违序清点（登记不拦）。"""
    report: dict[str, Any] = {"reader_face": None, "rows": 0, "projected_rows": 0,
                              "shape_codes": {}, "url_findings": 0, "orphan_findings": 0,
                              "orphan_resolved_by_transport_nodes": 0,
                              "legacy_positional": None}
    try:
        reg = source_projection.registry()
    except source_projection.ProjectionError as exc:
        errors.append("SOURCE_PROJECTION_REGISTRY_MISSING|%s" % exc.detail)
        reg = None
    try:
        key = registered_reader_face_key()
    except source_projection.ProjectionError as exc:
        errors.append("SOURCE_PROJECTION_REGISTRY_MISSING|%s" % exc.detail)
        key = None
    report["reader_face"] = key
    if key is None or reg is None:
        return report
    rows = list(data.get(key) or [])
    report["rows"] = len(rows)
    if not rows:
        # 台账缺失在数据门里记成看得见的事实：正式交付由 visual_qa 的正式档路径硬阻断
        # （SPA_SOURCE_LEDGER_ABSENT），这里不假装有东西可投影。
        warnings.append(
            "READER_SOURCE_FACE_ABSENT|%s 为空：这份 run 的读者页没有来源台账可发"
            "（正式档交付会被 visual_qa 以 SPA_SOURCE_LEDGER_ABSENT 阻断）" % key)
    else:
        projected, codes = project_reader_source_face(rows, reg=reg, errors=errors)
        report["shape_codes"] = codes
        report["projected_rows"] = len(projected)
        hub_pairs = transport_visible_pairs(data)
        for row in projected:
            # 两项检查今天就在这段里阻断，跑法不变，只是对象换成投影行：
            # ① URL 反伪造（_direct_url）② 孤儿实体（(destination, name) 必须在读者看得见的表里）。
            if row["verification_status"] != "verified":
                continue
            if row["evidence_level"] != "direct_entity":
                continue
            url = str(row["url"])
            if url and not _direct_url(url):
                report["url_findings"] += 1
                errors.append(
                    "READER_SOURCE_URL_NOT_DIRECT|读者来源面实体 %s/%s 标了 verified+direct_entity，"
                    "但 URL 不符合直达规范或有算法合成特征：%s（读者页每条链接都印得出来，"
                    "伪造 URL 在读者层面可见）" % (row["destination"], row["name"], url))
            pair = (row["destination"], row["name"])
            if pair in visible_names:
                continue
            if pair in hub_pairs:
                report["orphan_resolved_by_transport_nodes"] += 1
                continue
            report["orphan_findings"] += 1
            errors.append(
                "READER_SOURCE_ORPHAN_ENTITY|读者来源面有无法追溯的实体证据（疑似虚构或已从实体表"
                "删除后残留）：%s/%s；它既不在五张实体表里，也不在交通节点表里"
                % (row["destination"], row["name"]))
        counts = source_projection.counts(projected)
        report["counts"] = counts
    # 十列位置面已退出读者路径，但它违反注册列序是**实测事实**，登记在此、不拦中文正式出货。
    legacy = source_projection.legacy_positional_findings(data.get("source_evidence") or [], reg=reg)
    report["legacy_positional"] = legacy
    if not legacy["clean"]:
        warnings.append(
            "LEGACY_POSITIONAL_FACE_VIOLATES_REGISTERED_ORDER|十列位置面 source_evidence 与 "
            "references/data-model.json::source_evidence_columns 的注册列序不符（共 %d 行，按码计数 %s）；"
            "该面已不在读者路径上（读者面＝source_evidence_meta 的校验投影），故只登记不阻断"
            % (legacy["rows"], json.dumps(legacy["by_code"], ensure_ascii=False)))
    return report


def audit(data: dict[str, Any], manifest: dict[str, Any], scope: dict[str, Any],
          corridors: dict[str, Any], asset_manifest: dict[str, Any] | None = None, *,
          base_dir: str | Path | None = None,
          zero_call_ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """§11 V4：零调用四项只能来自执行期拦截器，所以这一层保证每次审计都在哨兵窗口里。

    调用方给了生成期账本就用它（强证据）；没给就现场装一个窗口，记的是『这一趟审计本身
    没有外联』（弱证据），并在报告里把证据档位写清楚——不把弱证据冒充成生成期证明。
    """
    if zero_call_sentinel.window_active():
        return _audit_body(data, manifest, scope, corridors, asset_manifest,
                           base_dir=base_dir, zero_call_ledger=zero_call_ledger)
    disarm = zero_call_sentinel.arm()
    try:
        return _audit_body(data, manifest, scope, corridors, asset_manifest,
                           base_dir=base_dir, zero_call_ledger=zero_call_ledger,
                           self_window=True)
    finally:
        disarm()


def _audit_body(data: dict[str, Any], manifest: dict[str, Any], scope: dict[str, Any],
                corridors: dict[str, Any], asset_manifest: dict[str, Any] | None = None, *,
                base_dir: str | Path | None = None,
                zero_call_ledger: dict[str, Any] | None = None,
                self_window: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    _audit_translations(data, errors, base_dir=base_dir)
    if base_dir:
        errors.extend(audit_run_provenance(Path(base_dir), manifest=manifest, root=ROOT))
    if str(manifest.get("skill_version") or "") != CURRENT_VERSION:
        errors.append(f"运行 manifest skill_version 必须为 {CURRENT_VERSION}，当前 {manifest.get('skill_version') or '缺失'}")
    gen_cmd = str(manifest.get("generation_command") or "")
    for m in re.finditer(r"travel-scope-v(\d+\.\d+\.\d+)", gen_cmd):
        if m.group(1) != CURRENT_VERSION:
            errors.append(f"manifest generation_command 引用了旧版本 travel-scope-v{m.group(1)}，应为 {CURRENT_VERSION}: {gen_cmd}")
            break
    intake = manifest.get("intake") or {}
    missing_intake = [key for key in POLICY["required_intake_fields"] if not str(intake.get(key, "")).strip()]
    if missing_intake:
        errors.append(f"manifest 缺少 Q0-Q8 原始需求字段: {missing_intake}")
    profile = manifest.get("destination_profile") or {}
    missing_profile = [key for key in POLICY["required_destination_profile_fields"] if not profile.get(key)]
    if missing_profile:
        errors.append(f"manifest 缺少目的地画像字段: {missing_profile}")
    if profile.get("map_region") not in {"international", "mainland_china"}:
        errors.append(f"未知地图区域: {profile.get('map_region')}")
    try:
        expected_days = int(intake.get("q2_days"))
    except (TypeError, ValueError):
        expected_days = 0
        errors.append("Q2 行程天数必须是正整数")

    routes = list(data.get("routes") or [])
    if len(routes) < POLICY["country_run_min_routes"]:
        errors.append(f"国家级行程至少需要 {POLICY['country_run_min_routes']} 条候选路线，当前 {len(routes)} 条")
    # V4.2.0: 路线节点拓扑拆分校验
    for r in routes:
        if len(r) > 2:
            nodes = [n.strip() for n in re.split(r"→|->|\s+-\s+|—", str(r[2] or "")) if n.strip()]
            if len(nodes) < 2:
                errors.append(f"路线 '{r[0]}' 走廊节点拓扑未有效拆分 (仅解析出 {len(nodes)} 个节点: '{r[2]}')，必须使用标准箭头 ' → ' 或连字符 ' - ' 隔开至少 2 个城市节点")

    # V4.2.0: 编辑大图与路线名强一致性门禁
    valid_route_set = {str(r[0]).strip() for r in routes if r}
    orphaned_media = []
    for idx, m in enumerate(data.get("editorial_media") or []):
        if isinstance(m, dict):
            m_route = str(m.get("route") or "").strip()
            if m_route and m_route not in valid_route_set:
                orphaned_media.append(f"大图 '{m.get('title') or idx}' 绑定路线 '{m_route}'")
    if orphaned_media:
        errors.append(f"发现编辑大图路线名与候选路线脱钩 (孤儿率 {len(orphaned_media)}/{len(data.get('editorial_media') or [])}): {orphaned_media[:3]}")

    # V5-B（V0-L05）：旧检查要求 budget_meta.rates.USD 必须是正浮点数——那等于逼着生成器
    # 编一个 0.14 出来交差。现在汇率规则全部交给唯一登记处 references/budget-policy.json，
    # 门禁复算 dataset 与发布产物两处（兜底常数回到 JS 里也算违约）。
    errors.extend(budget_contract.findings_for(data, root=ROOT, policy=BUDGET_POLICY))

    # V4.2.0: 海外地图目标 Google URL 汉字硬性拦截门禁
    # v4.2.1 在这里也抄了一份「海外 Google URL 严禁汉字」的扫描，和 map_contract 同一件事两处判定，
    # 结果一改规则就得记着改两个地方。§6.3.3 已被 v4.2.2 撤回（登记：map-link-selection.json::
    # query_rules.local_name_query_decision「海外地图 URL 含本地文字自 v4.2.2 起不再是地图错误」，
    # 业主 2026-10-30 按 V1R 裁决），本副本连同 v4.2.1 版一起删除，由 test_v420_regressions 的
    # 「只允许一处判定」用例钉住不再复发。

    signatures = [_corridor_signature(route) for route in routes]
    if len(set(signatures)) != len(signatures):
        errors.append("候选路线走廊重复，路线切换只是改名")

    itinerary = list(data.get("itinerary") or [])
    by_route: dict[str, dict[int, list[list[Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in itinerary:
        if not isinstance(row, list) or len(row) < 6:
            errors.append("ITINERARY 存在字段不足记录")
            continue
        day = _day_number(row[1])
        if day is None:
            errors.append(f"无法识别日序: {row[1]}")
            continue
        by_route[str(row[0])][day].append(row)
    route_names = [str(route[0]) for route in routes if route]
    for route_name in route_names:
        days = by_route.get(route_name, {})
        if expected_days and set(days) != set(range(1, expected_days + 1)):
            errors.append(f"路线 {route_name} 日程不完整: {sorted(days)}")
        transfers = sum(any(str(row[3]).strip() == "交通" for row in rows) for rows in days.values())
        doubles = sum(sum(str(row[3]).strip() == "交通" for row in rows) > 1 for rows in days.values())
        pace = str(intake.get("q8_pace", "moderate")).strip().lower()
        pace = {"紧凑": "compact", "适中": "moderate", "宽松": "relaxed"}.get(pace, pace)
        limits = POLICY["pace"].get(pace)
        if not limits:
            errors.append(f"未知 Q8 行程节奏: {intake.get('q8_pace')}")
        elif expected_days:
            ratio = transfers / expected_days
            if ratio > limits["max_transfer_day_ratio"]:
                errors.append(f"路线 {route_name} 换宿/跨区日比例 {ratio:.1%} 超过 {pace} 上限 {limits['max_transfer_day_ratio']:.0%}")
            if doubles > limits["max_double_transfer_days"]:
                errors.append(f"路线 {route_name} 有 {doubles} 天发生多次跨区交通")

    corridor_rows = list(corridors.get("corridors") or [])
    if len(corridor_rows) < len(routes):
        errors.append("路线走廊证据少于交付路线数量")
    for row in corridor_rows:
        if float(row.get("continuity", 0)) < POLICY["route_continuity_min_percent"]:
            errors.append(f"路线走廊 {row.get('corridor_id') or row.get('name')} 连续性不足 100%")
        if any(not edge.get("documented") for edge in row.get("edge_audit") or []):
            errors.append(f"路线走廊 {row.get('corridor_id') or row.get('name')} 存在未证明交通边")

    selected = scope.get("selected_destinations") or scope.get("destinations") or []
    canonical = {str(item.get("name", "")).strip() for item in selected if isinstance(item, dict) and str(item.get("status", "")).lower() not in {"excluded", "排除", "候选但排除"}}
    data_destinations = {str(row[0]).strip() for row in data.get("destinations") or [] if isinstance(row, list) and row}
    poi_destinations = {str(row[0]).strip() for key in ("hotels", "restaurants", "cafes", "attractions", "dive_sites") for row in data.get(key) or [] if isinstance(row, list) and row}
    if not data_destinations.issubset(canonical):
        errors.append(f"dataset 目的地超出正式范围: {sorted(data_destinations - canonical)}")
    if not poi_destinations.issubset(data_destinations):
        errors.append(f"POI 目的地未进入 dataset.destinations: {sorted(poi_destinations - data_destinations)}")

    # V4.0.11: Route Claims Verification
    route_claim_rules = POLICY.get("route_claim_rules", {})
    enforce_title_subset = route_claim_rules.get("enforce_title_corridor_subset", True)
    disallow_off_media = route_claim_rules.get("disallow_off_corridor_media", True)
    min_hero_media = route_claim_rules.get("min_exclusive_hero_media_per_route", 3)

    corridor_map: dict[str, dict[str, Any]] = {}
    for c_row in corridor_rows:
        c_name = str(c_row.get("name") or c_row.get("route_name") or "").strip()
        corridor_map[c_name] = c_row

    known_dest_names: set[str] = set()
    for item in selected:
        if isinstance(item, dict):
            for f in ("name", "name_en", "slug"):
                v = str(item.get(f) or "").strip()
                if len(v) >= 2:
                    known_dest_names.add(v)

    for route in routes:
        r_name = str(route[0] if route else "").strip()
        c_info = corridor_map.get(r_name)
        if not c_info:
            continue
        c_seq = [str(s).strip() for s in c_info.get("corridor_sequence") or []]
        c_seq_set = set(c_seq)
        for s in c_seq:
            # Also find matching items in scope to get english names
            for item in selected:
                if isinstance(item, dict) and str(item.get("name") or "").strip() == s:
                    for f in ("name_en", "slug"):
                        v = str(item.get(f) or "").strip()
                        if v:
                            c_seq_set.add(v)

        if enforce_title_subset:
            for dest in known_dest_names:
                if dest in r_name and dest not in c_seq_set:
                    errors.append(f"路线 {r_name} 标题声称包含目的地 '{dest}'，但实际走廊 sequence {c_seq} 中不包含该目的地，违反 route_claims 契约")

        if disallow_off_media:
            route_editorial = [m for m in (data.get("editorial_media") or []) if isinstance(m, dict) and str(m.get("route") or "").strip() == r_name]
            for m in route_editorial:
                m_dest = str(m.get("destination") or "").strip()
                if m_dest and m_dest not in c_seq_set:
                    errors.append(f"路线 {r_name} 错误绑定了走廊外目的地 ({m_dest}) 的媒体大图 ({m.get('image')})")

        if min_hero_media:
            exclusive = [m for m in (data.get("editorial_media") or []) if isinstance(m, dict) and (str(m.get("route") or "").strip() == r_name or (str(m.get("destination") or "").strip() in c_seq_set and not str(m.get("route") or "").strip()))]
            if len(exclusive) < min_hero_media:
                errors.append(f"路线 {r_name} 专属大图仅 {len(exclusive)} 张，低于要求的最低 {min_hero_media} 张")

    visible_names = {(str(row[0]).strip(), str(row[1]).strip()) for key in ("hotels", "restaurants", "cafes", "attractions", "dive_sites") for row in data.get(key) or [] if isinstance(row, list) and len(row) > 1}
    evidence_meta = list(data.get("source_evidence_meta") or [])
    valid_evidence: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in evidence_meta:
        if not isinstance(item, dict):
            errors.append("source_evidence_meta 存在非对象记录")
            continue
        key = (str(item.get("destination") or "").strip(), str(item.get("name") or "").strip())
        level = str(item.get("evidence_level") or "")
        sp = str(item.get("source_provider") or "").strip()
        if " / " in sp and ("TAT" in sp or "Michelin" in sp or "TripAdvisor" in sp):
            errors.append(f"单个来源不得声明为多方联合验证: {key} / {sp}")
        if level not in {"direct_entity", "direct_schedule", "official_area_reference", "search_candidate"}:
            errors.append(f"来源证据等级无效: {key} / {level or '空'}")

        # V4.0.11: Disallow verified status when scraping is blocked / captcha / HTTP error
        http_code = str(item.get("http_status") or item.get("status_code") or "").strip()
        crawl_st = str(item.get("crawl_status") or item.get("scraping_status") or "").lower()
        if item.get("verification_status") == "verified":
            if http_code in {"403", "429", "404", "500", "502", "503"} or item.get("scraping_blocked") is True or any(w in crawl_st for w in ("captcha", "blocked", "challenge", "forbidden")):
                errors.append(f"来源证据 {key} 存在反爬阻断或请求失败 (status={http_code}, crawl={crawl_st})，严禁标记为 verified，必须标记为 pending")
            if level == "direct_entity" and not _direct_url(item.get("url")):
                errors.append(f"来源证据 {key} 标记为 verified 但其 URL 结构不符合实体级直达规范或存在算法合成特征: {item.get('url')}")

        if item.get("verification_status") == "verified" and level == "direct_entity" and _direct_url(item.get("url")):
            # V4.0.8: Disallow domain-category mismatch (e.g. MyRapid or transit operators for hotels/food)
            url_host = urlsplit(str(item.get("url") or "")).hostname or ""
            disallowed_map = POLICY.get("evidence_rules", {}).get("disallowed_domains_by_category", {})
            
            # Determine category of this POI
            poi_cat = None
            for cat_name in ("hotels", "restaurants", "cafes", "attractions", "dive_sites"):
                if any(isinstance(r, list) and len(r) > 1 and str(r[0]).strip() == key[0] and str(r[1]).strip() == key[1] for r in data.get(cat_name) or []):
                    poi_cat = "accommodation" if cat_name == "hotels" else ("food" if cat_name in ("restaurants", "cafes") else "sights")
                    break
            
            disallowed_hosts = disallowed_map.get(poi_cat, []) if poi_cat else []
            if any(dh in url_host.lower() for dh in disallowed_hosts):
                errors.append(f"POI {key} ({poi_cat}) 来源域名角色错配: {url_host} 属于交通/非对应行业域名")
            else:
                valid_evidence[key].append(item)
    evidenced_names = set(valid_evidence)
    missing_evidence = sorted(visible_names - evidenced_names)
    if missing_evidence:
        errors.append(f"POI 缺少实体级直达来源证据 ({len(missing_evidence)}): {missing_evidence[:10]}")

    # V4.1.4 → ZH-RELEASE-1（业主 2026-11-02 裁 Q2-A）：读者来源面的检查面换成投影。
    # 这一段的形状原本是「遍历十列位置面 + `if not isinstance(row, list) or len(row) < 10: continue`」，
    # 实测 CA 189/189、PH 380/380 行里只有列数够的进得来，而进来的行又靠位置面第四/五列的
    # provider 中文标签过滤；读者真正看到的面（source_evidence_meta）一条都没被检查过。
    # 现在：未注册形状＝带码错误，两项检查跑在投影行上，位置面的违序量成登记事实。
    reader_face_report = audit_reader_source_face(data, visible_names, errors, warnings)

    # V4.0.9: Detect arithmetic progression / synthetic sequential ID patterns across URLs of the same domain
    if POLICY.get("evidence_rules", {}).get("disallow_arithmetic_progression_ids", True):
        domain_numeric_ids: dict[str, list[int]] = defaultdict(list)
        for item in evidence_meta:
            if isinstance(item, dict) and item.get("url"):
                parsed = urlsplit(str(item["url"]))
                # Extract trailing pure numeric ID from path like /hotels/204902.html or /entity/12345
                match = re.search(r"/(\d{4,9})(?:\.html)?$", parsed.path)
                if match and parsed.hostname:
                    domain_numeric_ids[parsed.hostname.lower()].append(int(match.group(1)))

        for host, num_ids in domain_numeric_ids.items():
            if len(num_ids) >= 4:
                sorted_ids = sorted(set(num_ids))
                if len(sorted_ids) >= 4:
                    diffs = [b - a for a, b in zip(sorted_ids, sorted_ids[1:])]
                    # Check if diffs are constant (arithmetic progression like +173 or +281)
                    diff_counts = Counter(diffs)
                    most_common_diff, count = diff_counts.most_common(1)[0]
                    if count >= 3 and most_common_diff > 0:
                        errors.append(f"域名 {host} 提取的数字 ID 呈现明显的规律等差递增步长 (+{most_common_diff})，判定为批量算法合成 URL: {sorted_ids[:6]}")

    provider_api_used = manifest.get("provider_api_used") is True
    google_pids = data.get("google_place_ids") or {}
    for name, pid in google_pids.items():
        pid_str = str(pid or "").strip()
        if not pid_str:
            continue
        if not provider_api_used:
            errors.append(f"未调用供应商 API 时严禁伪造 Place ID: {name} -> {pid_str}")
        elif pid_str.startswith(("ChIJ_th_", "ChIJ_fake", "ChIJ_mock", "ChIJ_synth")):
            errors.append(f"禁止使用合成/虚构 Place ID: {name} -> {pid_str}")

    map_errors, map_metrics = audit_map_targets(data, base_dir=base_dir, require_exact=True)
    errors.extend(map_errors)

    # --- v4.2.2 §8/§9 地图门禁：blocking 进 errors，exposed 进 warnings（逐项、不删、不拖垮整批）
    map_gate_v422_report = None
    try:
        _gate_cfg = map_gate_v422.load_gate()
        _selection = json.loads((Path(__file__).resolve().parents[1]
                                 / "references" / "map-link-selection.json")
                                .read_text(encoding="utf-8"))
        ledger = zero_call_ledger
        ledger_source = "generation_phase" if ledger else None
        if ledger is None and self_window:
            ledger = zero_call_sentinel.ledger(
                {"scope": "audit() 自身执行窗口：只证明这一趟审计没有外联",
                 "evidence_tier": "self_check_weak"})
            ledger_source = "self_check_window"
        map_gate_v422_report = map_gate_v422.evaluate(
            data, _gate_cfg, _selection, ledger=ledger,
            payload_kind="audit")
        if map_gate_v422_report.get("zero_call") is not None:
            map_gate_v422_report["zero_call"]["evidence_tier"] = ledger_source
        errors.extend(map_gate_v422_report["blocking"])
        warnings.extend(map_gate_v422_report["exposed"])
        # unclassified 已在 evaluate 内部并入 blocking（更严的一侧说话），这里只核对没丢
        if map_gate_v422_report["unclassified"] and not any(
                item.startswith("GATE_UNCLASSIFIED_SEVERITY|")
                for item in map_gate_v422_report["blocking"]):
            errors.append("GATE_UNCLASSIFIED_HANDLING_BROKEN|有 %d 条未分级 finding 却"
                          "没进入 blocking" % len(map_gate_v422_report["unclassified"]))
    except map_gate_v422.MapGateConfigError as exc:
        errors.append("MAP_GATE_V422_CONFIG_INVALID|%s" % exc)

    canonical_coords: dict[tuple[str, str], str] = {}
    for module in ("hotels", "restaurants", "cafes"):
        for row in data.get(module) or []:
            if isinstance(row, list) and len(row) > 5:
                rating_val = str(row[5] or "").strip()
                if any(plat in rating_val.lower() for plat in ("booking", "agoda", "tripadvisor", "dive_center", "dianping", "ctrip", "meituan")):
                    errors.append(f"{module} 点位 {row[1] if len(row) > 1 else ''} 评分列包含平台标签 ({rating_val})，属于来源错位，评分列须为数字或'—'")
                if len(row) > 1:
                    p_name = str(row[1] or "")
                    if re.search(r"\((?:restaurant|hotel|attraction)\s+rating\)", p_name, re.I):
                        errors.append(f"{module} 实体名吞入平台类别标签: '{p_name}'")

    for module, coord_index in (("hotels", 7), ("restaurants", 7), ("cafes", 7), ("attractions", 6), ("dive_sites", 6)):
        for row in data.get(module) or []:
            if isinstance(row, list) and len(row) > coord_index:
                canonical_coords[(str(row[0]).strip(), str(row[1]).strip())] = str(row[coord_index]).strip()
    unique_name_coords: dict[str, set[str]] = defaultdict(set)
    name_destinations: dict[str, set[str]] = defaultdict(set)
    for (_, poi_name), coords in canonical_coords.items():
        unique_name_coords[poi_name].add(coords)
    for destination, poi_name in canonical_coords:
        name_destinations[poi_name].add(destination)
    for route_name, days in by_route.items():
        route_poi_counts: Counter[str] = Counter()
        for day, rows in days.items():
            for row in rows:
                if str(row[3]).strip() == "交通":
                    continue
                poi_name_str = str(row[4]).strip()
                route_poi_counts[poi_name_str] += 1
                candidates = unique_name_coords.get(poi_name_str) or set()
                if len(candidates) != 1:
                    errors.append(f"行程点无法唯一绑定 POI: {route_name} Day {day} / {row[4]}")
                elif not _coord_equal(row[5], next(iter(candidates))):
                    errors.append(f"行程坐标与 POI 实体不一致: {route_name} Day {day} / {row[4]}")
        repeated = [p for p, count in route_poi_counts.items() if count > 1]
        if repeated:
            errors.append(f"路线 {route_name} 存在重复安排的实体景点/体验: {repeated}")

        daily_bases: list[str] = []
        for day in sorted(days):
            bases = [next(iter(name_destinations[str(row[4]).strip()])) for row in days[day]
                     if str(row[3]).strip() != "交通" and len(name_destinations.get(str(row[4]).strip()) or set()) == 1]
            if bases:
                daily_bases.append(Counter(bases).most_common(1)[0][0])
        base_changes = sum(left != right for left, right in zip(daily_bases, daily_bases[1:]))
        pace = {"紧凑": "compact", "适中": "moderate", "宽松": "relaxed"}.get(str(intake.get("q8_pace", "moderate")).strip().lower(), str(intake.get("q8_pace", "moderate")).strip().lower())
        limits = POLICY["pace"].get(pace)
        if limits and expected_days and base_changes / expected_days > limits["max_transfer_day_ratio"]:
            errors.append(f"路线 {route_name} 按每日实际目的地推导的换宿比例 {base_changes / expected_days:.1%} 超过 {pace} 上限")
        
        # Consecutive accommodation city change check
        consecutive_city_changes = 0
        max_consecutive_city_changes = 0
        for left, right in zip(daily_bases, daily_bases[1:]):
            if left != right:
                consecutive_city_changes += 1
                max_consecutive_city_changes = max(max_consecutive_city_changes, consecutive_city_changes)
            else:
                consecutive_city_changes = 0
        max_allowed_consecutive = limits.get("max_consecutive_city_changes", 2) if limits else 2
        if max_consecutive_city_changes > max_allowed_consecutive:
            errors.append(f"路线 {route_name} {pace} 节奏连续更换住宿城市达到 {max_consecutive_city_changes} 天，超过上限 {max_allowed_consecutive} 天")

        # V4.0.7: Base change transit edge enforcement (Disallow teleportation without explicit intercity transit)
        if POLICY.get("itinerary_rules", {}).get("enforce_base_deduction_transit_check", True):
            sorted_days = sorted(days)
            for idx in range(len(sorted_days) - 1):
                d_curr, d_next = sorted_days[idx], sorted_days[idx + 1]
                if idx < len(daily_bases) and idx + 1 < len(daily_bases):
                    base_curr, base_next = daily_bases[idx], daily_bases[idx + 1]
                    if base_curr != base_next:
                        # Check if either day has a transit entry connecting or mentioning base_curr and base_next
                        has_transit = any(
                            str(row[3]).strip() == "交通"
                            for day_key in (d_curr, d_next)
                            for row in days.get(day_key, [])
                        )
                        if not has_transit:
                            errors.append(f"路线 {route_name} 在 Day {d_curr} ({base_curr}) 至 Day {d_next} ({base_next}) 发生跨城转移，但日程中缺失显式连接交通")

    for module in POLICY["required_content_modules"]:
        if not data.get(module):
            errors.append(f"必需内容模块为空: {module}")

    depth = str(intake.get("q7_depth", "standard")).strip().lower()
    depth_aliases = {
        "精简": "concise", "concise": "concise", "shallow": "concise", "light": "concise",
        "标准": "standard", "standard": "standard", "medium": "standard", "moderate": "standard",
        "深度": "deep", "deep": "deep", "in-depth": "deep",
        "超级深度": "ultra", "ultra": "ultra", "ultra-deep": "ultra", "super-deep": "ultra",
    }
    depth = depth_aliases.get(depth, depth)
    depth_rule = POLICY["research_depth"].get(depth)
    if not depth_rule:
        errors.append(f"未知 Q7 研究深度: {intake.get('q7_depth')}")
    else:
        tier1_destinations: set[str] = set()
        tier2_destinations: set[str] = set()
        for item in selected:
            if not isinstance(item, dict):
                continue
            d_name = str(item.get("name") or "").strip()
            t_val = str(item.get("tier") or "").strip().lower()
            r_val = str(item.get("role") or "").strip().lower()
            if t_val in {"1", "tier1", "tier_1", "t1", "tier-1"}:
                tier1_destinations.add(d_name)
            elif t_val in {"2", "tier2", "tier_2", "t2", "tier-2"}:
                tier2_destinations.add(d_name)
            elif any(hub in r_val for hub in ("gateway", "hub", "metropolis", "core", "capital")):
                tier1_destinations.add(d_name)

        for route_name, days in by_route.items():
            daily_bases = []
            for day in sorted(days):
                bases = [next(iter(name_destinations[str(row[4]).strip()])) for row in days[day]
                         if str(row[3]).strip() != "交通" and len(name_destinations.get(str(row[4]).strip()) or set()) == 1]
                if bases:
                    daily_bases.append(Counter(bases).most_common(1)[0][0])
            for d, base_count in Counter(daily_bases).items():
                if base_count >= 3 and d not in tier2_destinations:
                    tier1_destinations.add(d)

        poi_keys = ("hotels", "restaurants", "cafes", "attractions", "dive_sites")
        counts_by_destination = Counter(
            str(row[0]).strip()
            for key in poi_keys
            for row in data.get(key) or []
            if isinstance(row, list) and row
        )
        for destination in sorted(data_destinations):
            is_t1 = destination in tier1_destinations
            tier_name = "tier1" if is_t1 else "tier2"
            tier_label = "Tier 1" if is_t1 else "Tier 2"
            tier_min_rules = depth_rule.get(f"{tier_name}_min_poi") or {}

            count = counts_by_destination[destination]
            min_dest_total = tier_min_rules.get("total", depth_rule.get("min_visible_poi_per_destination", 0))
            if count < min_dest_total:
                errors.append(f"{depth} 模式 {tier_label} 目的地 {destination} 的可见 POI 仅 {count} 个，最低要求 {min_dest_total} 个")

            for category in ("hotels", "restaurants", "cafes", "attractions"):
                cat_min = tier_min_rules.get(category, 0)
                if cat_min > 0:
                    cat_count = sum(
                        1 for row in data.get(category) or []
                        if isinstance(row, list) and row and str(row[0]).strip() == destination
                    )
                    if cat_count < cat_min:
                        errors.append(f"{depth} 模式 {tier_label} 目的地 {destination} 的 {category} 仅 {cat_count} 个，最低要求 {cat_min} 个")

            for category in depth_rule.get("required_poi_categories", []):
                if not any(isinstance(row, list) and row and str(row[0]).strip() == destination for row in data.get(category) or []):
                    errors.append(f"{depth} 模式目的地 {destination} 缺少必需类别: {category}")

        if (profile.get("scope_type") in {"country", "custom_area", "province", "region"}) and len(data_destinations) >= 3:
            total_run_min = int(depth_rule.get("total_run_min_poi", 0))
            if len(visible_names) < total_run_min:
                errors.append(f"{depth} 模式全案可见 POI 总数仅 {len(visible_names)} 个，最低要求 {total_run_min} 个")

        if len(data.get("editorial_media") or []) < depth_rule["min_editorial_images"]:
            errors.append(f"{depth} 模式人文/风景媒体不足 {depth_rule['min_editorial_images']} 张")
        if depth_rule["section_media_required"] and not (data.get("image_collection") or {}).get("section_media_required"):
            errors.append(f"{depth} 模式必须启用 section_media_required")
        if depth_rule["section_media_required"] and not data.get("section_media"):
            errors.append("目的地栏目图片为空")
        section_media = list(data.get("section_media") or [])
        if section_media:
            # 分母＝展开后的 (destination, module) 槽位数，不是「当前声明了几行」：
            # 登记面 media-policy.json::designed_no_photo_state.ratio_lock.rule 与业主 2026-11-04 裁示 B 都是这个口径。
            # 用 len(section_media) 的话，把两个同类别槽位合并成一行（合法的复用）会自己缩小分母，
            # 实测加州合并三组后 2 个无图槽位被量成 11.8%>10%——复用被尺子当成缺图率上升。
            try:
                import local_media_gate as _lmg
            except ImportError:      # 与 delivery_gate 同一套导入姿势：脚本面与包面都认
                from scripts import local_media_gate as _lmg
            slots, no_photo = _lmg.section_slot_denominator(section_media)
            denominator = slots or len(section_media)
            ratio = no_photo / float(denominator)
            maximum = float(depth_rule.get("max_designed_no_photo_ratio", 1))
            if ratio > maximum:
                errors.append(f"{depth} 模式设计缺图状态占比 {ratio:.1%} 超过上限 {maximum:.0%}，必须补充已核验氛围/类别图片")
        completed_passes = set(manifest.get("research_passes") or [])
        missing_passes = [item for item in depth_rule["research_passes"] if item not in completed_passes]
        if missing_passes:
            errors.append(f"{depth} 模式缺少研究阶段证据: {missing_passes}")
        pass_evidence = manifest.get("research_pass_evidence") or {}
        empty_evidence = [item for item in depth_rule["research_passes"] if not pass_evidence.get(item)]
        if empty_evidence:
            errors.append(f"{depth} 模式研究阶段缺少可审计证据: {empty_evidence}")
        if base_dir:
            pass_files = {
                "route_critical_facts": Path(base_dir) / "evidence/route_critical_facts.json",
                "material_dynamic_facts": Path(base_dir) / "evidence/material_dynamic_facts.json",
                "cross_source_review": Path(base_dir) / "evidence/cross_source_review.json",
            }
            pass_hashes: dict[str, str] = {}
            min_bytes = int(POLICY.get("evidence_rules", {}).get("min_pass_evidence_file_bytes", 500))
            for p_name, p_file in pass_files.items():
                if p_file.is_file():
                    p_bytes = p_file.read_bytes()
                    if len(p_bytes) < min_bytes:
                        errors.append(f"研究阶段证据文件 {p_file.name} 仅 {len(p_bytes)} 字节，低于 {min_bytes} 字节下限，属于空壳摘要")
                    p_hash = hashlib.sha256(p_bytes).hexdigest()
                    if p_hash in pass_hashes.values():
                        colliding = [k for k, h in pass_hashes.items() if h == p_hash]
                        errors.append(f"研究阶段证据文件 {p_file.name} 与 {colliding} 内容哈希完全重复，严禁复制空壳套用")
                    pass_hashes[p_name] = p_hash
        try:
            candidate_count = int(profile.get("candidate_pool_count", 0))
        except (TypeError, ValueError):
            candidate_count = 0
        if profile.get("scope_type") == "country" and candidate_count < depth_rule["candidate_pool_target"] and not str(profile.get("candidate_pool_exception", "")).strip():
            errors.append(f"{depth} 模式国家候选池仅 {candidate_count} 个，低于目标 {depth_rule['candidate_pool_target']} 且未说明覆盖例外")
        assets = (asset_manifest or {}).get("assets") or []
        if not assets:
            errors.append("正式媒体 asset-manifest 为空")
        if any(item.get("verification_status") != "verified" for item in assets):
            errors.append("asset-manifest 存在未完成人工视觉复核的媒体")

        # V4.0.11: Check for media timestamp time travel (> current generation year/month)
        all_media_items = list(data.get("editorial_media") or []) + list(data.get("section_media") or []) + list(assets)
        for m in all_media_items:
            if isinstance(m, dict):
                for t_field in ("retrieved_at", "checked_at"):
                    t_val = str(m.get(t_field) or "").strip()
                    if re.match(r"^202[7-9]", t_val) or re.match(r"^20[3-9]\d", t_val):
                        errors.append(f"媒体资源 {m.get('image') or m.get('asset_path') or m.get('title')} 的 {t_field} ({t_val}) 晚于当前生成运行时间，存在时空穿越")
        minimum_sources = int(depth_rule.get("min_independent_direct_sources", 1))
        insufficient = sorted(key for key in visible_names if len({str(urlsplit(str(item.get('url') or '')).hostname or item.get('source_provider') or '') for item in valid_evidence.get(key, [])}) < minimum_sources)
        if insufficient:
            errors.append(f"{depth} 模式实体独立直达来源不足 {minimum_sources} 个 ({len(insufficient)}): {insufficient[:10]}")
        if depth_rule.get("cross_source_review_required"):
            reviewed = set()
            for item in valid_evidence.values():
                for record in item:
                    if record.get("cross_source_review") == "pass":
                        reviewed.add((str(record.get("destination") or "").strip(), str(record.get("name") or "").strip()))
            missing_review = sorted(visible_names - reviewed)
            if missing_review:
                errors.append(f"{depth} 模式缺少逐实体交叉来源复核 ({len(missing_review)}): {missing_review[:10]}")

    node_names = {
        str((row.get("name") if isinstance(row, dict) else row[1]) or "").strip()
        for row in data.get("transport_nodes") or []
        if (isinstance(row, dict) and row.get("name")) or (isinstance(row, list) and len(row) > 1)
    }
    node_coords: dict[str, str] = {}
    for node in data.get("transport_nodes") or []:
        if isinstance(node, dict):
            node_coords[str(node.get("name") or "").strip()] = str(node.get("coords") or "").strip()
        elif isinstance(node, list) and len(node) > 4:
            node_coords[str(node[1]).strip()] = str(node[4]).strip()
    transport_edges: dict[str, tuple[str, str]] = {}
    edge_departures: dict[tuple[str, str], tuple[str, str]] = {}
    for row in data.get("transport") or []:
        if not isinstance(row, list) or len(row) < 24:
            errors.append(f"交通记录字段不足，无法验证地图端点: {row}")
            continue
        frequency = str(row[5]).strip()
        status = str(row[16]).strip()
        departures = f"{row[22]}|{row[23]}".strip("|")

        # V4.1.1: Verify departure & arrival GPS coordinates in row[6] and row[7] (P0-3)
        coord_origin = parse_coords(str(row[6]).strip())
        if not coord_origin:
            errors.append(f"交通记录出发地坐标无效或列错位: {row[0]} -> '{row[6]}'")
        coord_dest = parse_coords(str(row[7]).strip())
        if not coord_dest:
            errors.append(f"交通记录目的地坐标无效或列错位: {row[0]} -> '{row[7]}'")

        # V4.1.1: Route name structure check (must contain '→' delimiter)
        if "→" not in str(row[0]):
            errors.append(f"交通路线名称未包含规范 '→' 起止点连接符: '{row[0]}'")

        # G2: Duration validity check
        dur = str(row[4] if len(row) > 4 else "").strip()
        if not dur or dur in {"0", "0h", "0m", "0分", "0小时"}:
            errors.append(f"交通耗时无效或为0: {row[0]} -> '{dur}'")

        # G2: Distinct endpoints check
        ep_origin, ep_dest = str(row[12]).strip(), str(row[13]).strip()
        if ep_origin and ep_dest and ep_origin.casefold() == ep_dest.casefold():
            errors.append(f"交通始发与终到端点相同: {row[0]} ({ep_origin})")

        # G2: Anti-bidirectional symmetric timetable check
        if ep_origin and ep_dest and POLICY.get("transport_rules", {}).get("disallow_bidirectional_symmetric_timetables", True):
            rev_key = (ep_dest.casefold(), ep_origin.casefold())
            if rev_key in edge_departures:
                rev_name, rev_deps = edge_departures[rev_key]
                if departures and departures == rev_deps and len(departures.split(",")) >= 2:
                    errors.append(f"交通时刻表对向路线伪造完全镜像对称时刻: {row[0]} 与 {rev_name} 发车时刻完全一致 ({departures})，违反真实运营常理")
            edge_departures[(ep_origin.casefold(), ep_dest.casefold())] = (str(row[0]).strip(), departures)

        # V4.0.9: Self-drive mode cannot have scheduled departures or published_reference
        transport_mode = str(intake.get("q4_transport") or "").strip().lower()
        is_self_drive = transport_mode in {"self_drive", "自驾", "租车自驾"}
        is_drive_row = any(w in str(row[1] or "") for w in ("自驾", "租车", "drive", "car rental")) or is_self_drive
        if is_drive_row:
            if departures:
                errors.append(f"自驾/租车路线严禁伪造固定发车时刻班次: {row[0]} -> {departures}")
            if status in {"published_reference", "exact_date_verified"}:
                errors.append(f"自驾/租车路线状态必须为 on_demand，不得标注公共交通班次状态 ({status}): {row[0]}")
            if str(row[14] if len(row) > 14 else "").strip() in {"否", "No", "no", "false"}:
                errors.append(f"自驾路线交通记录不得标注为不适合自驾: {row[0]}")

        if status == "on_demand" and departures:
            errors.append(f"按需交通不应伪造时刻: {row[0]}")
        if any(word in frequency for word in ("随叫随到", "预约出行")) and status == "published_reference":
            errors.append(f"按需交通误标为已发布班次: {row[0]}")
        travel_time = str(intake.get("q1_time") or "").strip()
        is_future_year = any(y in travel_time for y in ("2027", "2028", "2029"))
        if is_future_year and status == "exact_date_verified":
            errors.append(f"未发布的未来班次不得标注 exact_date_verified，须标为当前参考并注明出发前复核: {row[0]}")
        if status in {"exact_date_verified", "published_reference", "current_reference_schedule"} and departures:
            if not _direct_url(row[20], schedule=True):
                errors.append(f"已展示班次但缺少具体官方时刻表页面: {row[0]}")
            if not str(row[17] or row[18]).strip() or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(row[19]).strip()):
                errors.append(f"已展示班次但缺少有效期或核验日期: {row[0]}")
            schedule_evidence = [item for item in evidence_meta if isinstance(item, dict) and item.get("evidence_level") == "direct_schedule" and item.get("verification_status") == "verified" and str(item.get("name") or "").strip() == str(row[0]).strip() and _direct_url(item.get("url"), schedule=True)]
            if not schedule_evidence:
                errors.append(f"已展示班次但缺少 direct_schedule 结构化证据: {row[0]}")

        # V4.0.11: Historical reference schedule check
        if POLICY.get("transport_rules", {}).get("enforce_historical_reference_marking", True):
            eff_cn = str(row[17] if len(row) > 17 else "").strip()
            eff_en = str(row[18] if len(row) > 18 else "").strip()
            t_url = str(row[20] if len(row) > 20 else "").strip()
            is_old_schedule = "2023" in eff_cn or "2023" in eff_en or "2023" in t_url or re.search(r"202[0-3]", t_url)
            if is_old_schedule:
                if not any(k in eff_cn for k in ("历史参考", "历史时刻", "非当前")):
                    errors.append(f"交通记录 {row[0]} 引用 2023 或更早历史日程，严禁虚标为当前参考时刻，必须明确标注为【历史参考时刻 · 临近出行必须官方复核】")
        for endpoint in (str(row[12]).strip(), str(row[13]).strip()):
            if not endpoint or "→" in endpoint or "->" in endpoint:
                errors.append(f"交通地图端点不是具体站点/机场/港口: {row[0]} / {endpoint or '空'}")
            elif endpoint not in node_names:
                errors.append(f"交通地图端点未进入 transport_nodes: {row[0]} / {endpoint}")
        transport_edges[str(row[0]).strip()] = (str(row[12]).strip(), str(row[13]).strip())
    for route_name, days in by_route.items():
        for day, rows in days.items():
            for row in rows:
                if str(row[3]).strip() != "交通":
                    continue
                edge = transport_edges.get(str(row[4]).strip())
                if not edge:
                    errors.append(f"行程交通未绑定 transport 实体: {route_name} Day {day} / {row[4]}")
                elif not any(_coord_equal(row[5], node_coords.get(endpoint)) for endpoint in edge):
                    errors.append(f"行程交通坐标未绑定任一核验端点: {route_name} Day {day} / {row[4]}")

    budget_rules = POLICY.get("budget_rules") or {}
    require_indep = budget_rules.get("require_independent_route_budgets", False)
    require_card_match = budget_rules.get("require_route_budget_card_match", False)

    budget_rows = data.get("budget") or []
    calc_sum = 0
    if budget_rows:
        lodging_tot, food_tot, tr_tot, act_tot, oth_tot, day_tot = 0, 0, 0, 0, 0, 0
        for b_row in budget_rows:
            if isinstance(b_row, list):
                if len(b_row) >= 9:
                    idx = 3
                elif len(b_row) >= 8:
                    idx = 2
                else:
                    continue
                try:
                    c_lod = int(float(b_row[idx]))
                    c_foo = int(float(b_row[idx+1]))
                    c_tra = int(float(b_row[idx+2]))
                    c_act = int(float(b_row[idx+3]))
                    c_oth = int(float(b_row[idx+4]))
                    c_day = int(float(b_row[idx+5]))
                    if c_lod + c_foo + c_tra + c_act + c_oth != c_day:
                        errors.append(f"预算每日明细之和与日合计不符: Day {b_row[0]} ({c_lod}+{c_foo}+{c_tra}+{c_act}+{c_oth} != {c_day})")
                    lodging_tot += c_lod
                    food_tot += c_foo
                    tr_tot += c_tra
                    act_tot += c_act
                    oth_tot += c_oth
                    day_tot += c_day
                except (ValueError, TypeError):
                    pass
        calc_sum = lodging_tot + food_tot + tr_tot + act_tot + oth_tot
        if calc_sum != day_tot:
            errors.append(f"预算分类总计 ({calc_sum}) 与日合计总额 ({day_tot}) 不平衡")

    # V4.0.5 Route budget independence & card match check
    if routes:
        route_card_budgets = []
        for r in routes:
            if isinstance(r, list) and len(r) > 5:
                try:
                    b_num = int(float(re.sub(r"[^\d.]", "", str(r[5]))))
                    route_card_budgets.append((str(r[0]), b_num))
                except (ValueError, TypeError):
                    pass

        # Check card match with detailed budget
        if require_card_match and route_card_budgets and calc_sum:
            rec_name, rec_budget = route_card_budgets[0]
            if abs(rec_budget - calc_sum) > budget_rules.get("max_subtotal_tolerance_cny", 0.0):
                errors.append(f"路线方案卡标称预算 ({rec_name}: {rec_budget}元) 与每日预算明细总额 ({calc_sum}元) 不符，存在计算断层")

        # Check independent budgets per route
        if require_indep and len(routes) > 1:
            route_budgets = data.get("route_budgets")
            if not isinstance(route_budgets, dict) or len(route_budgets) < len(routes):
                errors.append(f"包含 {len(routes)} 条不同走廊路线，但未提供独立的 route_budgets 路线明细预算核算")
            elif isinstance(route_budgets, dict):
                # V4.1.1: Multi-route budget reconciliation & anti-cloning check (P1-6)
                seen_detail_hashes = {}
                for r_name, r_items in route_budgets.items():
                    if isinstance(r_items, list):
                        detail_hash = hashlib.sha256(json.dumps(r_items, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
                        if detail_hash in seen_detail_hashes:
                            prev_route = seen_detail_hashes[detail_hash]
                            errors.append(f"路线预算明细异常克隆：路线 '{r_name}' 与路线 '{prev_route}' 逐日预算明细完全一致，违反独立核算契约")
                        else:
                            seen_detail_hashes[detail_hash] = r_name
                        card_b = next((b for name, b in route_card_budgets if name == r_name), None)
                        if card_b is not None and require_card_match:
                            try:
                                r_sum = sum(float(b_row[-1]) for b_row in r_items if isinstance(b_row, list) and len(b_row) > 0 and str(b_row[-1]).replace(".", "", 1).isdigit())
                                if abs(r_sum - card_b) > budget_rules.get("max_subtotal_tolerance_cny", 0.0):
                                    errors.append(f"路线方案卡标称预算 ({r_name}: {card_b}元) 与 route_budgets 逐日明细总额 ({r_sum:.0f}元) 不符")
                            except (ValueError, TypeError):
                                pass
                    elif isinstance(r_items, dict):
                        # V4.1.8: schema object with total_cny
                        if "total_cny" not in r_items:
                            errors.append(f"路线 '{r_name}' route_budgets 对象缺少必需字段 total_cny: {r_items}")
                        else:
                            tot = float(r_items["total_cny"])
                            card_b = next((b for name, b in route_card_budgets if name == r_name), None)
                            if card_b is not None and require_card_match and abs(tot - card_b) > budget_rules.get("max_subtotal_tolerance_cny", 0.0):
                                errors.append(f"路线方案卡标称预算 ({r_name}: {card_b}元) 与 route_budgets total_cny ({tot:.0f}元) 不符")
                    elif not isinstance(r_items, (int, float)):
                        errors.append(f"路线 '{r_name}' route_budgets 存在未知数据结构: {type(r_items)}")

    exact_dates_confirmed = manifest.get("exact_dates_confirmed") is True
    if not exact_dates_confirmed:
        invented = [row[1] for row in data.get("budget") or [] if isinstance(row, list) and len(row) > 1 and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(row[1]))]
        if invented:
            errors.append("用户只确认月份时不得补造具体日期")
    else:
        # V4.1.4: exact_dates_confirmed=true 必须与 intake 的具体日期口径一致，不得只给月份却声称已确认具体日期
        q1_time = str(intake.get("q1_time") or "")
        has_specific_dates = bool(re.search(r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}", q1_time)) or bool(re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", q1_time))
        if not has_specific_dates:
            errors.append("exact_dates_confirmed=true 但 intake.q1_time 未含具体日期（仅月份），口径矛盾，必须改为 false")

    # V4.0.12: Local Apps Contract Verification
    local_apps = data.get("local_apps")
    if local_apps is None:
        errors.append("dataset.json 缺少顶层必填字段: local_apps")
    else:
        as_of_date = str(manifest.get("generated_at") or datetime.date.today().isoformat())
        app_errs = validate_local_apps(local_apps, as_of_date=as_of_date)
        errors.extend(app_errs)
        depth_rules = POLICY.get("research_depth", {}).get(depth, {})
        min_apps = depth_rules.get("min_local_apps", 0)
        req_priorities = depth_rules.get("required_app_priorities", [])
        active_apps = [a for a in local_apps if isinstance(a, dict) and a.get("availability_status") not in ("retired", "pending")]
        if len(active_apps) < min_apps:
            errors.append(f"{depth} 模式要求至少推荐 {min_apps} 款已核验在地工具，当前仅 {len(active_apps)} 款")
        for req_p in req_priorities:
            if not any(a.get("priority") == req_p for a in active_apps):
                errors.append(f"{depth} 模式要求必须包含 priority='{req_p}' 的在地工具")

    local_apps_count = len([a for a in (data.get('local_apps') or []) if isinstance(a, dict) and a.get('availability_status') not in ('retired', 'pending')])

    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "warnings": warnings,
            "metrics": {"routes": len(routes), "itinerary_routes": len(by_route), "poi_count": len(visible_names),
                        "source_coverage_percent": round(100 * len(evidenced_names & visible_names) / len(visible_names), 1) if visible_names else 100,
                        "source_projection": reader_face_report,
                        "research_depth": depth, "editorial_media": len(data.get('editorial_media') or []), "section_media": len(data.get('section_media') or []),
                        "local_apps": local_apps_count, "map_targets": map_metrics,
                        "map_gate_v422": ({
                            "applicable": map_gate_v422_report["applicability"],
                            "enforced": map_gate_v422_report["enforced"],
                            "blocking": len(map_gate_v422_report["blocking"]),
                            "exposed": len(map_gate_v422_report["exposed"]),
                            "unclassified": len(map_gate_v422_report["unclassified"]),
                            "code_tally": map_gate_v422_report["code_tally"],
                            "batch_verdict": map_gate_v422_report["batch_verdict"],
                            "zero_call": ((map_gate_v422_report.get("zero_call") or {}))}
                           if map_gate_v422_report else {"applicable": False,
                                                         "reason": "GATE_CONFIG_UNREADABLE"})}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a formal Travel-Scope run across data, route, scope and media evidence")
    parser.add_argument("--data", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--corridors", required=True)
    parser.add_argument("--asset-manifest", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--zero-call-ledger", default="",
                        help="生成期零调用账本（zero_call_sentinel 产出）。不传则本门禁只证明"
                             "『审计过程自己没联网』，并在报告里把这个弱的证据范围写清楚。")
    args = parser.parse_args()
    data_path = Path(args.data)
    ledger = (json.loads(Path(args.zero_call_ledger).read_text(encoding="utf-8"))
              if args.zero_call_ledger else None)

    result = audit(_read(args.data), _read(args.manifest), _read(args.scope),
                   _read(args.corridors),
                   _read(args.asset_manifest) if args.asset_manifest else None,
                   base_dir=data_path.parent, zero_call_ledger=ledger)
    metrics = result.get("metrics") or {}
    block = metrics.get("map_gate_v422") if isinstance(metrics, dict) else None
    if isinstance(block, dict):
        block["zero_call_evidence_tier"] = (block.get("zero_call") or {}).get("evidence_tier")
    # V5-A：报告（含 stdout）一律带产出者身份；落盘走 gate_producer 唯一的 LF 出口。
    inputs = gate_producer.collect_inputs({
        "data": args.data, "manifest": args.manifest, "scope": args.scope,
        "corridors": args.corridors, "asset_manifest": args.asset_manifest,
        "zero_call_ledger": args.zero_call_ledger})
    candidates = [Path(args.report)] if args.report else [
        cand for cand in (data_path.parent / "outputs" / "formal_data_gate.json",
                          data_path.parent / "formal_data_gate.json")
        if cand.parent.is_dir()]
    if candidates:
        result = gate_producer.write_stamped_report(
            candidates[0], result, gate_role="formal_data_gate",
            producing_code=list(PRODUCING_CODE), producing_config=list(PRODUCING_CONFIG),
            inputs=inputs)["report"]
    else:
        result = gate_producer.stamped(result, gate_producer.stamp(
            "formal_data_gate", PRODUCING_CODE, PRODUCING_CONFIG, inputs))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
