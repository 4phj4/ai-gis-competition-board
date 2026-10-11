"""Conservative public-page collector. Unknown fields stay unknown."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIGISCompetitionBoard/1.0; public-pages-only)"}
KEYWORDS = re.compile(r"竞赛|大赛|挑战赛|黑客松|比赛|hackathon|challenge|contest|competition|GIS", re.I)
NOISE = re.compile(r"结果|获奖|名单|公示|回顾|总结|成绩|培训|讲座|论坛|分享|概况|作品提交列表|webinar|winners|results", re.I)
DATE = re.compile(r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?")
LABELS = {
    "registration_deadline": re.compile(r"报名截止(?:时间|日期)?|注册截止|报名期限|registration deadline|register by", re.I),
    "submission_deadline": re.compile(r"作品提交截止(?:时间|日期)?|提交截止(?:时间|日期)?|submission deadline|submit by", re.I),
}


def clean(value: str) -> str:
    return " ".join(value.split()).strip()


def canonical(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/") or "/", "", "", ""))


def fetch(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=18, allow_redirects=True)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return BeautifulSoup(response.text, "html.parser")


def title_of(soup: BeautifulSoup) -> str:
    h = soup.select_one("h1")
    if h and KEYWORDS.search(clean(h.get_text(" ", strip=True))):
        return clean(h.get_text(" ", strip=True))
    tag = soup.select_one('meta[property="og:title"]')
    if tag and tag.get("content"):
        return clean(tag["content"])
    return clean(soup.title.get_text(" ", strip=True)) if soup.title else ""


def labeled_date(text: str, pattern: re.Pattern) -> str | None:
    for line in re.split(r"[\n。；;]", text):
        if pattern.search(line):
            match = DATE.search(line)
            if match:
                try:
                    return datetime(*map(int, match.groups())).date().isoformat()
                except ValueError:
                    pass
    return None


def discover(source: dict, soup: BeautifulSoup) -> list[tuple[str, str]]:
    if source["mode"] == "single":
        return [(source["url"], source.get("title") or title_of(soup))]
    if source["id"] == "datafountain":
        found = {}
        for card in soup.select(".compt-item"):
            a = next((link for link in card.select('a[href*="/competitions/"]') if clean(link.get_text(" ", strip=True))), None)
            if not a:
                continue
            title = clean(a.get_text(" ", strip=True))
            if not re.search(r"智能体|AI应用|人工智能应用|空间数据|地理信息|遥感应用|GIS|agent|hackathon", title, re.I):
                continue
            dates = DATE.findall(card.get_text(" ", strip=True))
            if dates and datetime(*map(int, dates[-1])).date() < datetime.now(TZ).date():
                continue
            found[canonical(urljoin(source["url"], a["href"]))] = title
        return list(found.items())[:20]
    found = {}
    for a in soup.select("a[href]"):
        url = canonical(urljoin(source["url"], a.get("href", "")))
        if source["path"] not in url or url == canonical(source["url"]):
            continue
        name = clean(a.get_text(" ", strip=True))
        if len(name) < 8:
            continue
        if source["id"] == "modelscope":
            if not re.search(r"黑客松\s+类型|应用开发赛\s+类型", name):
                continue
        elif len(name) > 180:
            continue
        if not KEYWORDS.search(name) or NOISE.search(name):
            continue
        # Exclude navigation and unrelated domains; Tencent's official feed links to WeChat.
        if source["id"] != "tencent" and urlparse(url).netloc != urlparse(source["url"]).netloc:
            continue
        found.setdefault(url, name)
    return list(found.items())[:20]


def extract(source: dict, url: str, listed_title: str, soup: BeautifulSoup) -> dict | None:
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    title = title_of(soup) or listed_title
    if source["id"] == "datafountain":
        title = listed_title
    if source["id"] == "modelscope":
        title = re.split(r"\s+(?:进行中|已结束|未开始)\s+", listed_title, maxsplit=1)[0]
    if source.get("title"):
        title = source["title"]
    if len(title) < 8 or (source["id"] != "datafountain" and not KEYWORDS.search(title)) or NOISE.search(title):
        return None
    content = soup.select_one('.ArticleContent') if source['id'] == 'csgpc' else (soup.select_one('.ck-content') if source['id'] == 'gisera' else None)
    text = (content or soup).get_text("\n", strip=True)
    # Only use dates next to an explicit label; free-floating dates can be publication dates.
    registration = labeled_date(text, LABELS["registration_deadline"])
    submission = labeled_date(text, LABELS["submission_deadline"])
    if source["id"] == "modelscope":
        match = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})\s+\d{1,2}:\d{2}\s+报名截止", listed_title)
        registration = match.group(1) if match else registration
    anchors = []
    for a in soup.select("a[href]"):
        label = clean(a.get_text(" ", strip=True))
        if re.search(r"报名|立即参加|register|sign up", label, re.I):
            link = urljoin(url, a["href"])
            if urlparse(link).scheme in ("http", "https"):
                anchors.append(link)
    registration_url = anchors[0] if anchors else None
    if source["id"] == "modelscope" and "立即报名" in listed_title:
        registration_url = url
    published = None
    for key in ('meta[property="article:published_time"]', 'meta[name="pubdate"]'):
        tag = soup.select_one(key)
        if tag and tag.get("content"):
            published = tag["content"][:10]
            break
    images = ' '.join(img.get('src', '') for img in content.select('img[src]')) if content else ''
    digest = hashlib.sha256((title + "\n" + clean(text)[:12000] + images).encode()).hexdigest()
    return {
        "id": hashlib.sha256(canonical(url).encode()).hexdigest()[:16],
        "title": title[:150], "category": source["category"], "source_id": source["id"],
        "source_name": source["name"], "official_url": url,
        "registration_method": "赛事页提供报名入口" if registration_url and source["id"] == "modelscope" else ("网页入口待核实" if registration_url else "未公布／待核实"),
        "registration_url": registration_url, "registration_deadline": registration,
        "submission_deadline": submission, "major_official": None,
        "major_suggestion": "地理空间相关专业" if source["category"] == "GIS" else "AI 应用开发相关方向",
        "notes": "请核对公告原文中的组队、资格与费用要求。" + (" 国际赛事须逐场核对中国学生参赛与领奖资格。" if source["id"] in ("lablab", "nasa", "grss") else ""),
        "published_at": published, "content_hash": digest,
    }


def run() -> dict:
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    state_path = ROOT / "data" / "state.json"
    previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"items": {}, "last_success_at": None}
    items = previous["items"]
    today = datetime.now(TZ).date().isoformat()
    now = datetime.now(TZ).isoformat(timespec="seconds")
    baseline = not bool(items)
    statuses = []
    success = 0
    for source in sources:
        if source["mode"] == "manual":
            statuses.append({"id": source["id"], "name": source["name"], "url": source["url"], "status": source["status"], "reason": source["reason"], "checked_at": None})
            continue
        count = 0
        errors = []
        try:
            listing = fetch(source["url"])
            if source["id"] == "datafountain" and not listing.select(".compt-item"):
                raise ValueError("公开赛事列表结构未识别，无法判断是否有新赛事")
            links = discover(source, listing)
            if not links and not source.get("allow_empty"):
                raise ValueError("未找到可识别的赛事公告")
            for url, name in links:
                try:
                    detail = listing if canonical(url) == canonical(source["url"]) else fetch(url)
                    item = extract(source, url, name, detail)
                    if not item:
                        continue
                    old = items.get(item["id"])
                    item["first_seen_at"] = old["first_seen_at"] if old else now
                    item["last_checked_at"] = now
                    item["change_type"] = ("baseline" if baseline else "new") if not old else ("changed" if old["content_hash"] != item["content_hash"] else old.get("change_type", "unchanged"))
                    item["changed_at"] = now if item["change_type"] in ("new", "changed") else (old or {}).get("changed_at")
                    if old and old["content_hash"] != item["content_hash"]:
                        details = []
                        for key, label in (("registration_deadline", "报名截止"), ("submission_deadline", "作品提交截止"), ("registration_url", "报名入口")):
                            if old.get(key) != item.get(key):
                                details.append(f"{label}：{old.get(key) or '待核实'} → {item.get(key) or '待核实'}")
                        item["change_details"] = details or ["官方页面正文有变化，提取字段未变化；请核对原文"]
                    else:
                        item["change_details"] = (old or {}).get("change_details", [])
                    items[item["id"]] = item
                    count += 1
                except (requests.RequestException, ValueError) as exc:
                    errors.append(str(exc)[:100])
            if not count and not source.get("allow_empty"):
                raise ValueError("找到链接但没有可验证的赛事详情")
            success += 1
            status = "ok" if not errors else "partial"
            reason = f"读取 {count} 条；{len(errors)} 条详情失败" if errors else (f"读取 {count} 条" if count else "已读取公开列表；当前无仍在赛期且符合方向的条目")
        except (requests.RequestException, ValueError) as exc:
            status, reason = "error", str(exc)[:180]
        statuses.append({"id": source["id"], "name": source["name"], "url": source["url"], "status": status, "reason": reason, "checked_at": now, "coverage": "单页监测" if source["mode"] == "single" else "列表采集"})
    if success:
        previous["last_success_at"] = now
    previous.update({"items": items, "sources": statuses, "last_run_at": now, "baseline_at": previous.get("baseline_at") or (now if baseline and success else None)})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for file in (ROOT / "web").iterdir():
        if file.is_file(): shutil.copyfile(file, dist / file.name)
    (dist / "data.json").write_text(json.dumps({"items": list(items.values()), "sources": statuses, "last_run_at": now, "last_success_at": previous["last_success_at"], "baseline_at": previous["baseline_at"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"items": len(items), "active_sources": success, "last_run_at": now}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
