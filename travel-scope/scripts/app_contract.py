"""Configuration-driven validation contract for Travel-Scope local_apps."""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def load_policy(root: Path | None = None) -> dict[str, Any]:
    policy_root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    policy_file = policy_root / "references/local-apps-policy.json"
    if not policy_file.is_file():
        raise FileNotFoundError(f"Missing local apps policy: {policy_file}")
    return json.loads(policy_file.read_text(encoding="utf-8"))


BANNED_URL_HOSTS = {
    "apkpure.com", "apkmirror.com", "apkcombo.com", "aptoide.com",
    "google.com", "www.google.com", "bing.com", "www.bing.com", "baidu.com", "www.baidu.com"
}


def _is_search_or_thirdparty(url: str) -> bool:
    if not url:
        return False
    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    if host in BANNED_URL_HOSTS and "/search" in parsed.path:
        return True
    if any(banned in host for banned in ["apkpure", "apkmirror", "apkcombo", "aptoide"]):
        return True
    return False


def validate_app(app: dict[str, Any], policy: dict[str, Any], as_of_date: str | None = None) -> list[str]:
    errors: list[str] = []
    app_id = str(app.get("app_id") or "").strip()
    if not app_id:
        return ["App 缺少必填 app_id"]

    for name_field in ("name", "name_en", "country"):
        if not str(app.get(name_field) or "").strip():
            errors.append(f"App '{app_id}' 缺少必填字段: {name_field}")

    category = app.get("category")
    allowed_categories = policy.get("app_categories", {})
    if category not in allowed_categories:
        errors.append(f"App '{app_id}' 的 category '{category}' 不在配置分类体系中")

    priority = app.get("priority")
    allowed_priorities = policy.get("priorities", [])
    if priority not in allowed_priorities:
        errors.append(f"App '{app_id}' 的 priority '{priority}' 不合法")

    destinations = app.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        errors.append(f"App '{app_id}' 的 destinations 必须为非空列表")

    use_cases_cn = app.get("use_cases_cn")
    use_cases_en = app.get("use_cases_en")
    if not isinstance(use_cases_cn, list) or not use_cases_cn:
        errors.append(f"App '{app_id}' 的 use_cases_cn 必须为非空列表")
    if not isinstance(use_cases_en, list) or not use_cases_en:
        errors.append(f"App '{app_id}' 的 use_cases_en 必须为非空列表")

    coverage_status = app.get("coverage_status")
    if coverage_status not in policy.get("coverage_statuses", []):
        errors.append(f"App '{app_id}' 的 coverage_status '{coverage_status}' 不合法")

    availability_status = app.get("availability_status")
    allowed_statuses = policy.get("availability_statuses", [])
    if availability_status not in allowed_statuses:
        errors.append(f"App '{app_id}' 的 availability_status '{availability_status}' 不合法")

    limitations_cn = app.get("limitations_cn") or []
    limitations_en = app.get("limitations_en") or []
    if availability_status == "conditional":
        if not limitations_cn or not any(str(x).strip() for x in limitations_cn):
            errors.append(f"App '{app_id}' 状态为 conditional，但缺少 limitations_cn 风险说明")
        if not limitations_en or not any(str(x).strip() for x in limitations_en):
            errors.append(f"App '{app_id}' 状态为 conditional，但缺少 limitations_en 英文风险说明")

    if availability_status == "retired" and priority in ("essential", "recommended"):
        errors.append(f"App '{app_id}' 已退役 (retired)，绝对不得标记为 '{priority}' 正式推荐")

    official_url = str(app.get("official_url") or "").strip()
    ios_url = str(app.get("ios_url") or "").strip()
    android_url = str(app.get("android_url") or "").strip()
    source_url = str(app.get("source_url") or "").strip()

    if not official_url and not ios_url and not android_url:
        errors.append(f"App '{app_id}' 至少必须提供 official_url / ios_url / android_url 之一作为官方入口")

    for label, u in (("official_url", official_url), ("source_url", source_url)):
        if u:
            if not u.startswith(("http://", "https://")):
                errors.append(f"App '{app_id}' 的 {label} 必须以 http:// 或 https:// 开头")
            if _is_search_or_thirdparty(u):
                errors.append(f"App '{app_id}' 的 {label} 命中被禁用的第三方镜像/搜索结果页: {u}")

    ios_pattern = policy.get("store_domain_patterns", {}).get("ios")
    if ios_url and ios_pattern:
        if not re.search(ios_pattern, ios_url):
            errors.append(f"App '{app_id}' 的 ios_url 不符合官方 App Store 域名格式: {ios_url}")

    android_pattern = policy.get("store_domain_patterns", {}).get("android")
    if android_url and android_pattern:
        if not re.search(android_pattern, android_url):
            errors.append(f"App '{app_id}' 的 android_url 不符合官方 Google Play 域名格式: {android_url}")

    verified_at = str(app.get("verified_at") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", verified_at):
        errors.append(f"App '{app_id}' 的 verified_at 格式必须为 YYYY-MM-DD: {verified_at}")
    else:
        freshness_class = str(app.get("freshness_class") or "").strip()
        max_days = policy.get("freshness_max_days", {}).get(freshness_class)
        if max_days is None:
            errors.append(f"App '{app_id}' 的 freshness_class '{freshness_class}' 不在配置中")
        elif as_of_date:
            try:
                v_date = datetime.date.fromisoformat(verified_at)
                r_date = datetime.date.fromisoformat(as_of_date)
                if v_date > r_date:
                    errors.append(f"App '{app_id}' 的 verified_at ({verified_at}) 晚于当前生成基准日期 ({as_of_date})")
                elif (r_date - v_date).days > max_days:
                    errors.append(f"App '{app_id}' 的核验已过期: 距基准日期 {(r_date - v_date).days} 天，超过上限 {max_days} 天")
            except ValueError as exc:
                errors.append(f"App '{app_id}' 日期计算异常: {exc}")

    return errors


def validate_local_apps(apps: list[dict[str, Any]], root: Path | None = None, as_of_date: str | None = None) -> list[str]:
    if not isinstance(apps, list):
        return ["local_apps 必须为列表对象"]
    policy = load_policy(root)
    errors: list[str] = []
    seen_ids: set[str] = set()

    for app in apps:
        if not isinstance(app, dict):
            errors.append(f"local_apps 条目格式错误: {app}")
            continue
        app_id = str(app.get("app_id") or "").strip()
        if app_id in seen_ids:
            errors.append(f"local_apps 存在重复 app_id: '{app_id}'")
        seen_ids.add(app_id)
        errors.extend(validate_app(app, policy, as_of_date))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate local_apps against contract policy")
    parser.add_argument("--data", required=True, help="Path to dataset.json containing local_apps")
    parser.add_argument("--as-of", default=datetime.date.today().isoformat(), help="As-of evaluation date YYYY-MM-DD")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.is_file():
        print(f"Error: {data_path} not found", file=sys.stderr)
        return 1

    content = json.loads(data_path.read_text(encoding="utf-8"))
    apps = content.get("local_apps") or []
    errs = validate_local_apps(apps, as_of_date=args.as_of)
    if errs:
        print(f"FAILED local_apps validation ({len(errs)} errors):", file=sys.stderr)
        for e in errs:
            print(f"- {e}", file=sys.stderr)
        return 1

    print(f"PASS: {len(apps)} local_apps validated successfully against contract policy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
