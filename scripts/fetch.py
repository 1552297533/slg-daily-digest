#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SLG 品类游戏资讯每日爬取脚本（GitHub Actions 版）

数据源（混合模式）：
- Google News RSS
- GameRes 游资网
- TapTap SLG 标签热帖
- 游戏葡萄
- NGA SLG 板块

输出：
- data/YYYY-MM-DD.json
- 更新 data/index.json

注：git add/commit/push 由 GitHub Actions workflow 处理，本脚本不再执行 git 操作。
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

# -------------------------------------------------------------------
# 路径与常量
# -------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
INDEX_FILE = DATA_DIR / "index.json"

CN_TZ = timezone(timedelta(hours=8))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
    "Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

REQUEST_TIMEOUT = 10

# SLG 核心关键词
SLG_CORE_KEYWORDS = [
    "SLG", "策略", "战争", "国战",
    "率土", "三战", "万国", "文明",
    "COK", "征服", "帝国", "三国志战略版", "鸿图",
    "三国", "战略", "君主", "城池", "联盟", "沙盘",
]

# 标题质量评分用核心词（命中越多分越高）
QUALITY_KEYWORDS = [
    "SLG", "策略", "战争", "国战", "率土", "三战",
    "万国", "文明", "COK", "征服", "帝国",
    "三国志战略版", "鸿图", "战略", "联盟",
]


def log(msg: str) -> None:
    print(f"[{datetime.now(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def sleep_random() -> None:
    time.sleep(random.uniform(1.0, 2.0))


def safe_get(url: str, **kwargs: Any) -> requests.Response | None:
    try:
        resp = requests.get(
            url,
            headers=random_headers(),
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        resp.raise_for_status()
        return resp
    except Exception as e:  # noqa: BLE001
        log(f"  请求失败 {url}: {e}")
        return None


def contains_slg_keyword(text: str) -> bool:
    if not text:
        return False
    upper_text = text.upper()
    for kw in SLG_CORE_KEYWORDS:
        if kw.upper() in upper_text:
            return True
    return False


def parse_date(value: Any) -> datetime | None:
    """尽力解析多种日期格式，返回带 +08:00 时区的 datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CN_TZ)
    if isinstance(value, time.struct_time):
        return datetime.fromtimestamp(time.mktime(value), tz=CN_TZ)
    if isinstance(value, str):
        s = value.strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d",
            "%Y年%m月%d日",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=CN_TZ)
            except ValueError:
                continue
    return None


# -------------------------------------------------------------------
# 数据源解析器
# -------------------------------------------------------------------

def fetch_google_news() -> list[dict]:
    items: list[dict] = []
    queries = ["SLG 手游", "SLG 游戏", "策略手游"]
    for q in queries:
        url = (
            f"https://news.google.com/rss/search?q={quote_plus(q)}"
            "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
        try:
            feed = feedparser.parse(url, request_headers=random_headers())
            for entry in feed.entries[:30]:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "").strip()
                if not title or not link:
                    continue
                if not contains_slg_keyword(title):
                    continue
                published = parse_date(
                    getattr(entry, "published_parsed", None)
                    or getattr(entry, "published", None)
                )
                summary_raw = getattr(entry, "summary", "")
                summary = BeautifulSoup(summary_raw, "lxml").get_text(" ", strip=True)
                items.append({
                    "title": title,
                    "url": link,
                    "source": "Google News",
                    "summary": summary[:80],
                    "publishedAt": (published or datetime.now(CN_TZ)).strftime("%Y-%m-%d"),
                    "_published_dt": published,
                    "engagement": None,
                })
            sleep_random()
        except Exception as e:  # noqa: BLE001
            log(f"  Google News 查询失败 {q}: {e}")
    return items


def fetch_gameres() -> list[dict]:
    items: list[dict] = []
    urls = [
        "https://www.gameres.com/news.html",
        "https://www.gameres.com/",
    ]
    for url in urls:
        resp = safe_get(url)
        if resp is None:
            continue
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select("a"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) < 6 or not href:
                continue
            if not contains_slg_keyword(title):
                continue
            full_url = urljoin(url, href)
            if not full_url.startswith("http"):
                continue
            items.append({
                "title": title,
                "url": full_url,
                "source": "GameRes",
                "summary": "",
                "publishedAt": datetime.now(CN_TZ).strftime("%Y-%m-%d"),
                "_published_dt": datetime.now(CN_TZ),
                "engagement": None,
            })
        sleep_random()
    return items


def fetch_taptap() -> list[dict]:
    items: list[dict] = []
    urls = [
        "https://www.taptap.cn/category/8",
        "https://www.taptap.cn/search?type=app&keyword=SLG",
    ]
    for url in urls:
        resp = safe_get(url)
        if resp is None:
            continue
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select("a[href]"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) < 6:
                continue
            if not contains_slg_keyword(title):
                continue
            full_url = urljoin("https://www.taptap.cn", href)
            engagement = None
            engagement_attr = a.find_next(string=re.compile(r"\d+\s*(评论|回帖|赞|热度)"))
            if engagement_attr:
                m = re.search(r"(\d+)", str(engagement_attr))
                if m:
                    engagement = int(m.group(1))
            items.append({
                "title": title,
                "url": full_url,
                "source": "TapTap",
                "summary": "",
                "publishedAt": datetime.now(CN_TZ).strftime("%Y-%m-%d"),
                "_published_dt": datetime.now(CN_TZ),
                "engagement": engagement,
            })
        sleep_random()
    return items


def fetch_youxiputao() -> list[dict]:
    items: list[dict] = []
    url = "https://www.youxiputao.com/"
    resp = safe_get(url)
    if resp is None:
        return items
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    for a in soup.select("a[href]"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or len(title) < 6:
            continue
        if not contains_slg_keyword(title):
            continue
        full_url = urljoin(url, href)
        if not full_url.startswith("http"):
            continue
        items.append({
            "title": title,
            "url": full_url,
            "source": "游戏葡萄",
            "summary": "",
            "publishedAt": datetime.now(CN_TZ).strftime("%Y-%m-%d"),
            "_published_dt": datetime.now(CN_TZ),
            "engagement": None,
        })
    sleep_random()
    return items


def fetch_nga() -> list[dict]:
    """NGA 综合策略 SLG 板块（fid 可能调整，下面给出常见列表）。"""
    items: list[dict] = []
    candidate_urls = [
        "https://bbs.nga.cn/thread.php?fid=-447601",  # 率土之滨
        "https://bbs.nga.cn/thread.php?fid=-7099473",  # 三国志·战略版
        "https://bbs.nga.cn/thread.php?fid=-7099526",  # 鸿图之下
    ]
    for url in candidate_urls:
        resp = safe_get(url)
        if resp is None:
            continue
        try:
            resp.encoding = "gbk"
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:  # noqa: BLE001
            continue
        for a in soup.select("a.topic, a[href*='read.php']"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) < 6:
                continue
            if not contains_slg_keyword(title):
                # NGA 板块本身就是 SLG，放宽过滤
                pass
            full_url = urljoin("https://bbs.nga.cn/", href)
            engagement = None
            sibling = a.find_parent("tr")
            if sibling:
                m = re.search(r"(\d+)\s*/\s*\d+", sibling.get_text(" ", strip=True))
                if m:
                    engagement = int(m.group(1))
            items.append({
                "title": title,
                "url": full_url,
                "source": "NGA",
                "summary": "",
                "publishedAt": datetime.now(CN_TZ).strftime("%Y-%m-%d"),
                "_published_dt": datetime.now(CN_TZ),
                "engagement": engagement,
            })
        sleep_random()
    return items


SOURCE_REGISTRY: list[dict] = [
    {"name": "Google News", "fetcher": fetch_google_news, "weight": 1.0},
    {"name": "GameRes",      "fetcher": fetch_gameres,     "weight": 0.95},
    {"name": "TapTap",       "fetcher": fetch_taptap,      "weight": 0.9},
    {"name": "游戏葡萄",     "fetcher": fetch_youxiputao,  "weight": 0.95},
    {"name": "NGA",          "fetcher": fetch_nga,         "weight": 0.85},
]


# -------------------------------------------------------------------
# 评分与去重
# -------------------------------------------------------------------

def recency_score(published: datetime | None) -> float:
    if published is None:
        return 0.4
    now = datetime.now(CN_TZ)
    delta = now - published
    if delta.total_seconds() < 0:
        return 1.0
    days = delta.total_seconds() / 86400
    if days <= 1:
        return 1.0
    return max(0.0, 1.0 - (days - 1) * 0.2)


def quality_score(title: str) -> float:
    if not title:
        return 0.0
    hits = 0
    upper = title.upper()
    for kw in QUALITY_KEYWORDS:
        if kw.upper() in upper:
            hits += 1
    return min(1.0, hits / 3.0)


def engagement_score(value: int | None) -> float:
    if value is None or value <= 0:
        return 0.5
    # 简单对数归一化
    import math
    return min(1.0, math.log10(value + 1) / 4.0)


def compute_score(item: dict, weight: float) -> float:
    r = recency_score(item.get("_published_dt"))
    q = quality_score(item.get("title", ""))
    e = engagement_score(item.get("engagement"))
    base = r * 0.5 + q * 0.3 + e * 0.2
    return round(base * weight, 4)


def dedup(items: list[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: list[dict] = []
    for it in items:
        url = it.get("url", "")
        title_key = re.sub(r"\s+", "", it.get("title", ""))[:40]
        if url in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(title_key)
        result.append(it)
    return result


# -------------------------------------------------------------------
# 输出
# -------------------------------------------------------------------

def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def write_daily_json(date_str: str, items: list[dict]) -> Path:
    payload = {
        "date": date_str,
        "generatedAt": datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "items": [
            {
                "title": it["title"],
                "url": it["url"],
                "source": it["source"],
                "summary": it.get("summary", "")[:80],
                "publishedAt": it.get("publishedAt", date_str),
                "score": it.get("score", 0.0),
            }
            for it in items
        ],
    }
    out_path = DATA_DIR / f"{date_str}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"已写入 {out_path}")
    return out_path


def update_index(date_str: str) -> None:
    dates: list[str] = []
    if INDEX_FILE.exists():
        try:
            dates = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            if not isinstance(dates, list):
                dates = []
        except Exception:  # noqa: BLE001
            dates = []
    if date_str in dates:
        dates.remove(date_str)
    dates.insert(0, date_str)
    INDEX_FILE.write_text(
        json.dumps(dates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"已更新索引 {INDEX_FILE}（共 {len(dates)} 条）")


# -------------------------------------------------------------------
# 主流程
# -------------------------------------------------------------------

def collect_all() -> list[dict]:
    all_items: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(SOURCE_REGISTRY)) as pool:
        future_map: dict = {}
        for src in SOURCE_REGISTRY:
            fut = pool.submit(_safe_fetch, src["fetcher"], src["name"])
            future_map[fut] = src
        for fut in as_completed(future_map):
            src = future_map[fut]
            try:
                items = fut.result() or []
            except Exception as e:  # noqa: BLE001
                log(f"[{src['name']}] 失败: {e}")
                items = []
            log(f"[{src['name']}] 抓取 {len(items)} 条")
            for it in items:
                it["score"] = compute_score(it, src["weight"])
                all_items.append(it)
    return all_items


def _safe_fetch(fetcher: Callable[[], list[dict]], name: str) -> list[dict]:
    try:
        return fetcher()
    except Exception as e:  # noqa: BLE001
        log(f"[{name}] 异常: {e}")
        traceback.print_exc()
        return []


def main() -> int:
    ensure_data_dir()
    today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    log(f"开始抓取 SLG 资讯 - {today}")

    raw_items = collect_all()
    log(f"原始抓取总数: {len(raw_items)}")

    deduped = dedup(raw_items)
    log(f"去重后: {len(deduped)}")

    deduped.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    top_n = max(3, min(5, len(deduped)))
    top_items = deduped[:top_n]
    log(f"取 Top {len(top_items)} 条")

    for i, it in enumerate(top_items, 1):
        log(f"  #{i} [{it['source']}] {it['title'][:50]}  score={it['score']}")

    if not top_items:
        log("未抓取到任何条目，仍写出空 JSON 以保持产出节奏")

    write_daily_json(today, top_items)
    update_index(today)

    log("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
