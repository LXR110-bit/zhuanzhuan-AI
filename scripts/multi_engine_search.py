#!/usr/bin/env python3
"""Multi-engine signal candidate discovery.

This script is intentionally a *candidate discovery* layer for the signal Agent.
It does not promote platform policy findings to confirmed facts. Every output
item defaults to evidence_status=pending_verification until an API, official
page, screenshot/OCR, or manual check confirms it.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote, urlparse, parse_qs
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "multi_search_sources.json"
DEFAULT_OUTPUT = ROOT / "data" / "platform_policy_candidates.json"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize_title(value: str) -> str:
    text = normalize_space(value).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return text


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<script[\s\S]*?</script>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<style[\s\S]*?</style>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return normalize_space(fragment)


def decode_redirect_url(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("url", "u", "target", "r", "redirect", "to"):
        if key in qs and qs[key]:
            candidate = unquote(qs[key][0])
            if candidate.startswith(("http://", "https://")):
                return candidate
    return url


def build_search_url(engine: dict, query: str) -> str:
    return str(engine["url"]).format(keyword=quote_plus(query))


def fetch_url(url: str, timeout: int) -> tuple[int, str]:
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    })
    with urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", 200)
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="replace")
        return status, body


def parse_anchor_results(html_text: str, engine_id: str, max_results: int) -> list[dict]:
    """Generic SERP parser. It intentionally extracts conservative candidates only."""
    results: list[dict] = []
    seen = set()
    anchor_re = re.compile(r"<a\b([^>]*?)href=[\"']([^\"']+)[\"']([^>]*)>([\s\S]*?)</a>", re.I)
    for match in anchor_re.finditer(html_text):
        href = decode_redirect_url(match.group(2).strip())
        if not href.startswith(("http://", "https://")):
            continue
        parsed = urlparse(href)
        domain = parsed.netloc.lower()
        if not domain or any(skip in domain for skip in ("baidu.com", "bing.com", "sogou.com", "so.com", "google.com", "duckduckgo.com")):
            # Search-engine internal links are rarely evidence. Keep WeChat article links when proxied by Sogou below.
            if not (engine_id == "wechat" and "weixin" in href):
                continue
        title = strip_tags(match.group(4))
        if len(normalize_title(title)) < 4:
            continue
        key = href or normalize_title(title)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "title": title[:180],
            "url": href,
            "domain": domain,
            "snippet": "",
        })
        if len(results) >= max_results:
            break
    return results


def candidate_score(item: dict, profile: dict) -> tuple[int, list[str]]:
    text = f"{item.get('title','')} {item.get('snippet','')} {item.get('url','')}".lower()
    title = str(item.get("title") or "")
    domain = str(item.get("domain") or "").lower()
    reasons: list[str] = []
    score = 0

    official_domains = tuple(d.lower() for d in profile.get("official_domains", []))
    trusted_domains = tuple(d.lower() for d in profile.get("trusted_domains", []))
    if any(domain.endswith(d) or d in domain for d in official_domains):
        score += 35
        reasons.append("official_domain")
    elif any(domain.endswith(d) or d in domain for d in trusted_domains):
        score += 20
        reasons.append("trusted_domain")

    policy_hits = [k for k in profile.get("policy_keywords", []) if k.lower() in text]
    ops_hits = [k for k in profile.get("ops_keywords", []) if k.lower() in text]
    include_hits = [k for k in profile.get("include_keywords", []) if k.lower() in text]
    if policy_hits:
        score += min(30, 10 + len(set(policy_hits)) * 5)
        reasons.append("policy_keywords:" + ",".join(sorted(set(policy_hits))[:5]))
    if ops_hits:
        score += min(20, len(set(ops_hits)) * 5)
        reasons.append("ops_keywords:" + ",".join(sorted(set(ops_hits))[:5]))
    if include_hits:
        score += min(15, len(set(include_hits)) * 3)

    if re.search(r"满\s*\d{3,5}\s*减\s*\d{2,5}|\d{3,5}\s*元", title):
        score += 15
        reasons.append("amount_or_threshold")

    irrelevant = [k for k in profile.get("irrelevant_keywords", []) if k.lower() in text]
    if irrelevant:
        score -= 40
        reasons.append("irrelevant:" + ",".join(irrelevant[:3]))

    return max(0, min(100, score)), reasons


def infer_ops_playbook(item: dict) -> dict:
    text = f"{item.get('title','')} {item.get('snippet','')}".lower()
    categories = []
    for key, label in (("显卡", "显卡"), ("台式", "台式机"), ("组装", "组装机"), ("笔记本", "笔记本"), ("电脑", "电脑办公")):
        if key in text and label not in categories:
            categories.append(label)
    if not categories:
        categories = ["电脑办公"]
    return {
        "traffic_intent": "平台补贴/以旧换新刺激下的旧机估价与比价流量",
        "target_categories": categories,
        "landing_page": "电脑办公估价入口前置，突出组装机/显卡/台式机/笔记本快捷估价",
        "copy": [
            "换新前，先查旧电脑还能抵多少钱",
            "旧机估价满门槛？先来这里快速测一测",
            "组装机/显卡/台式机配置填完整，估价更准"
        ],
        "channels": ["App首页/电脑办公品类页", "估价页顶部banner", "Push/短信召回", "搜索词/SEO承接"],
        "metrics": ["估价UV", "估价完成率", "配置填写完整率", "报价页到提交率", "高估值旧机占比"]
    }


def make_candidate(raw: dict, engine_id: str, engine_label: str, query: str, profile: dict) -> dict | None:
    score, reasons = candidate_score(raw, profile)
    if score < int(profile.get("min_score") or 0):
        return None
    key_raw = raw.get("url") or f"{engine_id}:{normalize_title(raw.get('title'))}"
    dedupe_key = hashlib.sha1(key_raw.encode("utf-8")).hexdigest()
    return {
        "title": raw.get("title") or "未命名平台政策线索",
        "summary": raw.get("snippet") or raw.get("title") or "",
        "source": f"multi_search:{engine_id}",
        "engine": engine_label,
        "query": query,
        "url": raw.get("url") or "",
        "domain": raw.get("domain") or "",
        "score": score,
        "score_reasons": reasons,
        "level": profile.get("level") or "B",
        "evidence_status": "pending_verification",
        "evidence_required": ["official_api", "official_url", "screenshot_or_ocr", "manual_check"],
        "ops_playbook": infer_ops_playbook(raw),
        "dedupe_key": dedupe_key,
        "captured_at": now_iso(),
        "publish_time_quality": "search_capture_time",
        "raw": raw,
    }


def dedupe_candidates(items: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for item in items:
        key = item.get("url") or item.get("dedupe_key")
        if not key:
            key = normalize_title(item.get("title"))
        if key not in best or int(item.get("score") or 0) > int(best[key].get("score") or 0):
            best[key] = item
    return sorted(best.values(), key=lambda x: (-int(x.get("score") or 0), x.get("title") or ""))


def load_input_results(path: Path) -> list[dict]:
    data = load_json(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "candidates"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def raw_from_input(item: dict) -> dict:
    url = item.get("url") or item.get("source_url") or item.get("link") or ""
    domain = item.get("domain") or (urlparse(url).netloc if url else "")
    return {
        "title": item.get("title") or item.get("summary") or item.get("name") or "",
        "url": url,
        "domain": domain,
        "snippet": item.get("snippet") or item.get("summary") or item.get("description") or "",
        "input_raw": item,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_FILE))
    parser.add_argument("--profile", default="")
    parser.add_argument("--query", action="append", help="Extra query. Can be repeated.")
    parser.add_argument("--output", default="")
    parser.add_argument("--input", help="Normalize pre-collected search_web/web_fetch results instead of direct fetching.")
    parser.add_argument("--fetch-direct", action="store_true", help="Directly fetch search-engine HTML. Candidate discovery only; may be blocked.")
    parser.add_argument("--dry-run", action="store_true", help="Only print planned engine URLs; no network or output write.")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_json(config_path)
    profile_name = args.profile or config.get("default_profile") or "platform_policy"
    profile = (config.get("profiles") or {}).get(profile_name)
    if not profile:
        raise SystemExit(f"unknown profile: {profile_name}")
    profile = dict(profile)
    profile["min_score"] = int(config.get("min_score") or 40)

    engines = config.get("engines") or {}
    selected_engines = profile.get("engines") or list(engines)
    queries = list(profile.get("queries") or [])
    if args.query:
        queries.extend(args.query)

    planned = []
    for query in queries:
        for engine_id in selected_engines:
            engine = engines.get(engine_id)
            if not engine:
                continue
            planned.append({
                "engine": engine_id,
                "label": engine.get("label") or engine_id,
                "query": query,
                "url": build_search_url(engine, query),
            })

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "mode": "dry_run",
            "profile": profile_name,
            "planned_calls": planned,
            "summary": {"queries": len(queries), "calls": len(planned)},
        }, ensure_ascii=False, indent=2))
        return 0

    raw_results: list[dict] = []
    errors: list[dict] = []
    if args.input:
        for item in load_input_results(Path(args.input)):
            if isinstance(item, dict):
                raw_results.append({"engine_id": item.get("engine") or "search_web", "query": item.get("query") or "input", "raw": raw_from_input(item)})
    elif args.fetch_direct:
        timeout = int(config.get("timeout_seconds") or 12)
        max_results = int(config.get("max_results_per_engine") or 5)
        delay = float(config.get("delay_seconds") or 1.2)
        for call in planned:
            try:
                status, body = fetch_url(call["url"], timeout)
                parsed = parse_anchor_results(body, call["engine"], max_results)
                for raw in parsed:
                    raw_results.append({"engine_id": call["engine"], "query": call["query"], "raw": raw})
                if status >= 400:
                    errors.append({**call, "status": status, "error": "http_status"})
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                errors.append({**call, "error": type(exc).__name__, "message": str(exc)[:300]})
            time.sleep(delay)
    else:
        print(json.dumps({
            "ok": False,
            "error": "no_input_or_fetch_direct",
            "message": "Use --dry-run to generate search tasks, --input to normalize Agent-collected results, or --fetch-direct for optional direct discovery.",
            "planned_calls": planned[:20],
        }, ensure_ascii=False, indent=2))
        return 2

    candidates: list[dict] = []
    for entry in raw_results:
        engine_id = entry["engine_id"]
        engine = engines.get(engine_id, {"label": engine_id})
        candidate = make_candidate(entry["raw"], engine_id, engine.get("label") or engine_id, entry["query"], profile)
        if candidate:
            candidates.append(candidate)

    candidates = dedupe_candidates(candidates)[: int(config.get("max_candidates") or 40)]
    output_path = ROOT / (args.output or config.get("output") or str(DEFAULT_OUTPUT))
    result = {
        "version": "1.0.0",
        "date": today_str(),
        "generated_at": now_iso(),
        "source": "multi_engine_search",
        "profile": profile_name,
        "evidence_status": "candidate_only_pending_verification",
        "items": candidates,
        "errors": errors,
        "summary": {
            "planned_calls": len(planned),
            "raw_results": len(raw_results),
            "candidates": len(candidates),
            "errors": len(errors),
            "fetch_direct": bool(args.fetch_direct),
            "input": args.input or "",
        },
    }
    save_json(output_path, result)
    print(json.dumps({"ok": True, "output": str(output_path), **result["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
