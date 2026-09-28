#!/usr/bin/env python3
"""Parse README.md and generate a single-file index.html for GitHub Pages.

Usage: python3 scripts/build_site.py
Reads:  <repo>/README.md
Writes: <repo>/index.html  (all CSS/JS inlined, zero external dependencies)
"""
import html
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(REPO, "README.md")
OUT_PATH = os.path.join(REPO, "index.html")

REPO_URL = "https://github.com/cwybruce/awesome-muse-use-cases"

DEFAULT_INVITE_CODE = "YGFC1Y"
DEFAULT_JOIN_URL = "https://muse.ai/join"

# 顶部"推荐阅读"位：设为 None 可隐藏；每日构建会自动带上
FEATURED = {
    "label": "推荐阅读",
    "title": "下一个风口不是更大的模型，是替你办事的 Agent",
    "desc": "Personal Agent 发展脉络梳理 + 短 / 中 / 长期演化路径预测",
    "url": "https://x.com/sycbruce/status/2104549031208996923",
}

# 作者 X 账号：设为 None 可隐藏
AUTHOR_X = {
    "handle": "@sycbruce",
    "url": "https://x.com/sycbruce",
}

# 作者头像：放在 assets/avatar.jpg（换图后重新构建即可）；同时用作标题栏图标
AVATAR_PATH = os.path.join(REPO, "assets", "avatar.jpg")


def avatar_data_uri():
    try:
        import base64
        with open(AVATAR_PATH, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""


# ---------------------------------------------------------------- parsing

def md_inline(s):
    """Convert a small subset of markdown to HTML. Never raises."""
    if not s:
        return ""
    s = html.escape(s, quote=False)
    # markdown links [text](url)
    s = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        s,
    )
    # bare <https://...> urls
    s = re.sub(
        r"&lt;(https?://[^&<>\s]+)&gt;",
        r'<a href="\1" target="_blank" rel="noopener">\1</a>',
        s,
    )
    # bold **text**
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    # dead-link notices like 【链接失效…】 get a styled span;
    # other 【...】 markers (e.g. 【官方】, 【往期回顾】) stay plain text
    s = re.sub("\u3010\u94fe\u63a5\u5931\u6548[^\u3011]{0,80}\u3011",
               lambda m: '<span class="flag">' + m.group(0) + "</span>", s)
    return s


def md_text(s):
    """Strip markdown down to plain text (for search index)."""
    if not s:
        return ""
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1", s)
    s = re.sub(r"[<>]", "", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"[#*_`]", "", s)
    return s.strip()


def classify(group_name, title, tags):
    """Return (kind, badge_label) for color coding."""
    g = group_name or ""
    t = title or ""
    tagstr = " ".join(tags or [])
    blob = g + " " + t
    if "翻车" in blob or "\u26a0" in blob or "#警示" in tagstr:
        return "warning", "翻车警示"
    if "\u3010官方\u3011" in blob or "#官方" in tagstr:
        return "official", "官方"
    if "媒体实测" in g:
        return "media", "媒体实测"
    if "第三方" in blob:
        return "partner", "第三方合作"
    if "用户案例" in g:
        return "case", "用户案例"
    return "case", "收录"


GROUP_ICONS = {
    "用户案例": "\U0001f9d1\u200d\U0001f4bb",
    "动态": "\U0001f4e2",
    "翻车警示": "\u26a0\ufe0f",
    "媒体实测": "\U0001f4f0",
    "延伸资源": "\U0001f517",
}


def parse_readme(text):
    lines = text.split("\n")
    title = "Awesome Muse Use Cases"
    invite_code = DEFAULT_INVITE_CODE
    join_url = DEFAULT_JOIN_URL

    sections = []          # date sections, in file order (already newest-first)
    cur_sec = None
    cur_grp = None
    cur_entry = None       # entry started by ####
    sec_intro_buf = []

    def flush_entry():
        nonlocal cur_entry
        if cur_entry is not None and cur_grp is not None:
            cur_grp["entries"].append(cur_entry)
        cur_entry = None

    def flush_group():
        nonlocal cur_grp
        flush_entry()
        if cur_grp is not None and cur_sec is not None:
            if cur_grp["entries"]:
                cur_sec["groups"].append(cur_grp)
        cur_grp = None

    def flush_section():
        nonlocal cur_sec
        flush_group()
        if cur_sec is not None:
            cur_sec["summary"] = " ".join(sec_intro_buf).strip()
            sec_intro_buf.clear()
            if cur_sec["groups"]:
                sections.append(cur_sec)
        cur_sec = None

    in_header = True       # before the first ## date section
    header_buf = []

    field_re = re.compile(r"^-\s*\*\*(.+?)\*\*\s*[\uff1a:]\s*(.*)$")
    date_sec_re = re.compile(
        r"^##\s+(\d{4}-\d{2}-\d{2})\s*[\uff08(]?\s*([^)\uff09]*)[)\uff09]?\s*$")
    any_h2_re = re.compile(r"^##\s+(?!#)(.*)$")
    h3_re = re.compile(r"^###\s+(?!#)(.*)$")
    h4_re = re.compile(r"^####\s+(?!#)(.*)$")

    for raw in lines:
        line = raw.rstrip()

        m = date_sec_re.match(line)
        if m:
            flush_section()
            in_header = False
            cur_sec = {"date": m.group(1), "label": m.group(2).strip(),
                       "summary": "", "groups": []}
            continue

        m = any_h2_re.match(line)
        if m:
            # non-date ## heading (invite / 收录说明 / ...): close sections
            flush_section()
            if in_header:
                header_buf.append(("h2", m.group(1).strip()))
            else:
                cur_sec = None
            continue

        if in_header:
            header_buf.append(("line", line))
            continue

        if cur_sec is None:
            continue

        m = h3_re.match(line)
        if m:
            flush_group()
            cur_grp = {"name": m.group(1).strip(), "entries": []}
            continue

        m = h4_re.match(line)
        if m:
            flush_entry()
            if cur_grp is None:
                cur_grp = {"name": "收录", "entries": []}
            cur_entry = {"title": m.group(1).strip(), "fields": {}}
            continue

        fm = field_re.match(line)
        if fm and cur_entry is not None:
            cur_entry["fields"][fm.group(1).strip()] = fm.group(2).strip()
            continue

        stripped = line.strip()
        if stripped.startswith("- ") and cur_grp is not None:
            if cur_entry is None:
                # standalone bullet entry (media tests / resources)
                body = stripped[2:].strip()
                bm = re.match(r"^\*\*(.+?)\*\*\s*[\uff1a:]\s*(.*)$", body)
                if bm:
                    btitle, bbody = bm.group(1).strip(), bm.group(2).strip()
                else:
                    btitle = md_text(body)[:42]
                    bbody = body
                cur_grp["entries"].append(
                    {"title": btitle, "fields": {"_body": bbody}})
                continue
            # inside a #### entry but not a field line: extend last field
            if cur_entry["fields"]:
                last = list(cur_entry["fields"].keys())[-1]
                cur_entry["fields"][last] += " " + stripped
            continue

        if stripped and cur_grp is None and cur_entry is None:
            # section intro paragraph (e.g. "今日共收录 …")
            if not stripped.startswith("---"):
                sec_intro_buf.append(stripped)
        elif stripped and cur_entry is not None and not stripped.startswith("-"):
            # continuation of the last field value (multi-line field)
            if cur_entry["fields"]:
                last = list(cur_entry["fields"].keys())[-1]
                cur_entry["fields"][last] += " " + stripped

    flush_section()

    # ---- header: title + intro
    for kind, val in header_buf:
        if kind == "line" and val.startswith("# "):
            title = val[2:].strip()
    intro_paras = []
    for kind, val in header_buf:
        if kind == "line" and val and not val.startswith("#"):
            v = val[2:].strip() if val.startswith("> ") else val.strip()
            if v and v != "---" and not v.startswith("##"):
                intro_paras.append(v)
    intro = " ".join(intro_paras[:2])

    # ---- invite block
    m = re.search(r"邀请码\uff1a\*\*(\S+?)\*\*", text)
    if m:
        invite_code = m.group(1)
    m = re.search(r"https://muse\.ai/join", text)
    if m:
        join_url = m.group(0)

    # ---- normalize entries
    all_tags = set()
    total = 0
    for sec in sections:
        for grp in sec["groups"]:
            norm = []
            for e in grp["entries"]:
                f = e.get("fields", {})
                tags = []
                tagval = f.get("标签", "")
                if tagval:
                    tags = ["#" + t.strip("#*_`.,;；。")
                            for t in re.findall(r"#(\S+)", tagval)]
                    tags = [t for t in tags if len(t) > 1]
                all_tags.update(tags)
                summary = f.get("一句话总结", "") or f.get("_body", "")
                detail = (f.get("做了什么", "") or f.get("发生了什么", "")
                          or f.get("内容", ""))
                if md_text(detail) == md_text(summary):
                    detail = ""
                sources = f.get("来源", "")
                date = f.get("日期", "")
                kind, badge = classify(grp["name"], e["title"], tags)
                norm.append({
                    "title": e["title"],
                    "summary": summary,
                    "detail": detail,
                    "sources": sources,
                    "date": date,
                    "tags": tags,
                    "kind": kind,
                    "badge": badge,
                })
                total += 1
            grp["entries"] = norm

    return {
        "title": title,
        "intro": intro,
        "invite_code": invite_code,
        "join_url": join_url,
        "sections": sections,
        "all_tags": sorted(all_tags),
        "total": total,
    }


# ---------------------------------------------------------------- html gen

def build_card(e):
    search_text = " ".join([
        md_text(e["title"]), md_text(e["summary"]),
        md_text(e["detail"]), md_text(e["date"]),
        " ".join(e["tags"]),
    ])
    search_attr = html.escape(search_text, quote=True).replace("\n", " ")
    tags_attr = html.escape(" ".join(e["tags"]), quote=True)

    summary_html = ('<p class="summary">' + md_inline(e["summary"]) + "</p>"
                    if e["summary"] else "")
    detail_html = ('<div class="detail">' + md_inline(e["detail"]) + "</div>"
                   if e["detail"] else "")
    date_html = ('<span class="date">\U0001f4c5 '
                 + html.escape(md_text(e["date"])) + "</span>"
                 if e["date"] else "")
    sources_html = ""
    if e["sources"]:
        sources_html = ('<span class="sources">\U0001f517 '
                        + md_inline(e["sources"]) + "</span>")
    pills = "".join(
        '<button class="pill" data-tag="' + html.escape(t, quote=True) + '">'
        + html.escape(t) + "</button>"
        for t in e["tags"]
    )
    pills_html = '<div class="taglist">' + pills + "</div>" if pills else ""

    return (
        '<article class="card kind-' + e["kind"] + '" data-search="'
        + search_attr + '" data-tags="' + tags_attr + '">'
        + '<div class="card-head"><h3>' + md_inline(e["title"]) + "</h3>"
        + '<span class="badge badge-' + e["kind"] + '">'
        + html.escape(e["badge"]) + "</span></div>"
        + summary_html + detail_html
        + '<div class="meta">' + date_html + sources_html + "</div>"
        + pills_html
        + "</article>"
    )


def build_section(sec):
    groups_html = []
    for grp in sec["groups"]:
        icon = ""
        for key, em in GROUP_ICONS.items():
            if key in grp["name"]:
                icon = em + " "
                break
        cards = "\n".join(build_card(e) for e in grp["entries"])
        groups_html.append(
            '<section class="group"><h3 class="group-title">' + icon
            + html.escape(grp["name"])
            + '<span class="count">' + str(len(grp["entries"])) + " 条</span></h3>"
            + '<div class="cards">' + cards + "</div></section>"
        )
    label = ("\uff08" + html.escape(sec["label"]) + "\uff09"
             if sec["label"] else "")
    summary = ('<p class="issue-summary">' + md_inline(sec["summary"]) + "</p>"
               if sec["summary"] else "")
    return (
        '<section class="issue"><div class="issue-head">'
        "<h2>\U0001f4c5 " + html.escape(sec["date"]) + label + "</h2>"
        + summary + "</div>"
        + "\n".join(groups_html)
        + "</section>"
    )


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Awesome Muse Use Cases \u00b7 Meta Muse \u771f\u5b9e\u4f7f\u7528\u6848\u4f8b\u5408\u96c6</title>
__FAVICON__
<meta name="description" content="\u6bcf\u65e5\u66f4\u65b0\u7684 Meta Muse \u771f\u5b9e\u4f7f\u7528\u6848\u4f8b\u5408\u96c6">
<style>
:root{
  --bg:#f6f7fb; --card:#ffffff; --text:#1e2433; --muted:#6b7280;
  --line:#e8eaf1; --accent:#4f46e5; --accent-soft:#eef0ff;
  --official:#2563eb; --warning:#dc2626; --media:#7c3aed; --partner:#0d9488;
  --radius:14px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none;word-break:break-all}
a:hover{text-decoration:underline}
.hero{background:linear-gradient(135deg,#312e81 0%,#4f46e5 55%,#7c3aed 100%);color:#fff;padding:56px 20px 44px}
.hero-inner{max-width:960px;margin:0 auto}
.hero h1{margin:0 0 8px;font-size:clamp(26px,5vw,40px);letter-spacing:.5px}
.hero .subtitle{margin:0 0 14px;font-size:17px;opacity:.92}
.hero .intro{margin:0 0 22px;max-width:720px;font-size:14.5px;opacity:.85}
.stats{display:flex;gap:28px;margin:0 0 24px;flex-wrap:wrap}
.stat{display:flex;align-items:baseline;gap:6px}
.stat .num{font-size:34px;font-weight:800}
.stat .lbl{font-size:14px;opacity:.8}
.invite{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.25);
  border-radius:var(--radius);padding:16px 18px;max-width:720px}
.invite-text{font-size:14.5px;margin-bottom:12px}
.invite-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.invite-row code{background:#fff;color:#312e81;font-weight:800;font-size:18px;
  padding:8px 14px;border-radius:8px;letter-spacing:2px}
.btn{border:0;cursor:pointer;border-radius:8px;padding:9px 16px;font-size:14px;font-weight:600}
.btn-copy{background:#fff;color:#312e81}
.btn-join{background:#fbbf24;color:#3b2f04;display:inline-block}
.btn:active{transform:scale(.97)}
.copy-ok{font-size:13px;opacity:0;transition:opacity .3s}
.toolbar{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.94);
  border-bottom:1px solid var(--line);padding:12px 20px}
.toolbar-inner{max-width:960px;margin:0 auto;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#search{flex:1;min-width:200px;padding:10px 14px;border:1px solid var(--line);border-radius:10px;font-size:15px}
#search:focus{outline:2px solid var(--accent);border-color:var(--accent)}
.tagbar{display:flex;gap:8px;flex-wrap:wrap}
.tagfilter{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 13px;
  font-size:13px;cursor:pointer;color:var(--muted)}
.tagfilter.on{background:var(--accent);border-color:var(--accent);color:#fff}
#clearBtn{background:none;border:0;color:var(--muted);cursor:pointer;font-size:13px;display:none}
main{max-width:960px;margin:0 auto;padding:28px 20px 10px}
.issue{margin-bottom:40px}
.issue-head h2{margin:0 0 6px;font-size:22px}
.issue-summary{color:var(--muted);font-size:14px;margin:0 0 4px}
.group{margin:22px 0}
.group-title{font-size:17px;margin:0 0 12px;display:flex;align-items:center;gap:8px}
.group-title .count{font-size:12px;color:var(--muted);font-weight:400;background:var(--accent-soft);
  padding:2px 10px;border-radius:999px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px 14px;position:relative;overflow:hidden;display:flex;flex-direction:column}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent)}
.card.kind-official::before{background:var(--official)}
.card.kind-warning::before{background:var(--warning)}
.card.kind-media::before{background:var(--media)}
.card.kind-partner::before{background:var(--partner)}
.card-head{display:flex;gap:10px;align-items:flex-start;justify-content:space-between;margin-bottom:8px}
.card-head h3{margin:0;font-size:16px;line-height:1.5;flex:1}
.badge{flex:none;font-size:11px;font-weight:700;padding:3px 10px;border-radius:999px;color:#fff;background:var(--accent);white-space:nowrap}
.badge-official{background:var(--official)}
.badge-warning{background:var(--warning)}
.badge-media{background:var(--media)}
.badge-partner{background:var(--partner)}
.summary{margin:0 0 10px;font-size:15px;font-weight:600;color:#111827;
  border-left:3px solid var(--accent);padding-left:10px}
.kind-official .summary{border-color:var(--official)}
.kind-warning .summary{border-color:var(--warning)}
.kind-media .summary{border-color:var(--media)}
.kind-partner .summary{border-color:var(--partner)}
.detail{font-size:14px;color:#374151;margin:0 0 12px}
.meta{display:flex;flex-direction:column;gap:6px;font-size:13px;color:var(--muted);margin-bottom:10px}
.meta .sources{line-height:1.7}
.taglist{display:flex;gap:6px;flex-wrap:wrap;margin-top:auto;padding-top:4px}
.pill{border:1px solid var(--line);background:var(--accent-soft);color:var(--accent);
  border-radius:999px;padding:3px 11px;font-size:12px;cursor:pointer}
.pill:hover{background:var(--accent);color:#fff;border-color:var(--accent)}
.flag{color:var(--warning);font-size:12px;font-weight:600}
.empty{text-align:center;color:var(--muted);padding:60px 20px;font-size:15px}
footer{border-top:1px solid var(--line);margin-top:30px;padding:26px 20px 40px;
  color:var(--muted);font-size:13px;text-align:center;line-height:2}
footer a{color:var(--accent)}
@media (max-width:600px){
  .hero{padding:40px 16px 32px}
  .stats{gap:20px}
  .cards{grid-template-columns:1fr}
}
.featured{background:#fffbeb;border-bottom:1px solid #fde68a}
.featured-inner{max-width:960px;margin:0 auto;padding:14px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.featured-tag{flex:none;font-size:12px;font-weight:800;color:#92400e;background:#fde68a;border-radius:6px;padding:4px 10px}
.featured a.title{font-size:15px;font-weight:700;color:#1f2937;text-decoration:none}
.featured a.title:hover{color:#4f46e5;text-decoration:underline}
.featured .desc{font-size:13px;color:#78716c}
@media (max-width:600px){.featured .desc{display:none}}
.author{margin:0 0 20px;font-size:14px;opacity:.95;display:flex;align-items:center;gap:10px}
.author .avatar{width:36px;height:36px;border-radius:50%;border:2px solid rgba(255,255,255,.55);object-fit:cover}
.author a{color:#fff;font-weight:700;text-decoration:underline;text-underline-offset:3px}
.author a:hover{color:#fbbf24}
</style>
</head>
<body>
<header class="hero">
  <div class="hero-inner">
    <h1>\U0001f916 Awesome Muse Use Cases</h1>
    <p class="subtitle">Meta Muse \u771f\u5b9e\u4f7f\u7528\u6848\u4f8b\u5408\u96c6 \u00b7 \u6bcf\u65e5\u66f4\u65b0</p>
    <p class="intro">__INTRO__</p>
    <div class="author">__AUTHOR_X__</div>
    <div class="stats">
      <div class="stat"><span class="num">__ISSUES__</span><span class="lbl">\u671f\u66f4\u65b0</span></div>
      <div class="stat"><span class="num">__ENTRIES__</span><span class="lbl">\u6761\u6536\u5f55</span></div>
      <div class="stat"><span class="num">__TAGS__</span><span class="lbl">\u4e2a\u6807\u7b7e</span></div>
    </div>
    <div class="invite">
      <div class="invite-text">\U0001f381 \u5feb\u6765\u770b\u770b\u4f60\u7684\u4e2a\u4eba AI \u667a\u80fd\u4f53 Muse\u3002\u5728\u52a0\u5165\u540e\u7684 48 \u5c0f\u65f6\u5185\u901a\u8fc7\u300c\u8bbe\u7f6e\u300d\u5151\u73b0\u6211\u7684\u9080\u8bf7\u7801\uff0c\u6211\u4eec\u5c31\u80fd\u5206\u522b\u83b7\u5f97 <b>10 \u4ebf</b> Muse \u8bcd\u5143\u3002</div>
      <div class="invite-row">
        <code id="inviteCode">__INVITE_CODE__</code>
        <button class="btn btn-copy" onclick="copyCode()">\u590d\u5236\u9080\u8bf7\u7801</button>
        <a class="btn btn-join" href="__JOIN_URL__" target="_blank" rel="noopener">\U0001f449 \u524d\u5f80\u52a0\u5165</a>
        <span class="copy-ok" id="copyOk">\u5df2\u590d\u5236 \u2713</span>
      </div>
    </div>
  </div>
</header>

__FEATURED__

<div class="toolbar">
  <div class="toolbar-inner">
    <input id="search" type="search" placeholder="\U0001f50d \u641c\u7d22\u6848\u4f8b\u2026\uff08\u5982\uff1a\u7701\u94b1\u3001\u822a\u73ed\u3001\u4fdd\u9669\uff09" autocomplete="off">
    <div class="tagbar" id="tagbar">__TAGPILLS__</div>
    <button id="clearBtn" onclick="clearFilters()">\u2715 \u6e05\u9664\u7b5b\u9009</button>
  </div>
</div>

<main id="main">__SECTIONS__</main>
<div class="empty" id="emptyState" hidden>\U0001f636 \u6ca1\u6709\u5339\u914d\u7684\u7ed3\u679c\uff0c\u6362\u4e2a\u5173\u952e\u8bcd\u6216\u6807\u7b7e\u8bd5\u8bd5\uff5e</div>

<footer>
  \u6570\u636e\u6765\u6e90\uff1a\u672c\u4ed3\u5e93 <a href="__REPO_URL__">README.md</a>\uff08\u6bcf\u65e5\u66f4\u65b0\uff09 \u00b7 \u672c\u9875\u9762\u7531 <code>scripts/build_site.py</code> \u81ea\u52a8\u751f\u6210<br>
  \u6700\u540e\u66f4\u65b0\uff1a__BUILD_TIME__ \u00b7 commit <code>__COMMIT__</code><br>
  Muse = Meta \u7684\u4e2a\u4eba AI \u52a9\u624b\uff08\u975e Anthropic Claude\uff09\u00b7 \u54c1\u724c\u8d5e\u52a9\u5185\u5bb9\u5df2\u8fc7\u6ee4
</footer>

<script>
var activeTags = {};
function norm(s){ return (s||"").toLowerCase(); }
function applyFilter(){
  var q = norm(document.getElementById("search").value.trim());
  var tags = Object.keys(activeTags).filter(function(t){ return activeTags[t]; });
  var anyVisible = false;
  document.querySelectorAll(".card").forEach(function(card){
    var text = norm(card.getAttribute("data-search"));
    var cardTags = (card.getAttribute("data-tags")||"").split(" ").filter(Boolean);
    var okQ = !q || text.indexOf(q) !== -1;
    var okT = tags.length === 0 || tags.some(function(t){ return cardTags.indexOf(t) !== -1; });
    var show = okQ && okT;
    card.style.display = show ? "" : "none";
    if (show) anyVisible = true;
  });
  document.querySelectorAll(".group").forEach(function(g){
    var vis = Array.prototype.some.call(g.querySelectorAll(".card"), function(c){ return c.style.display !== "none"; });
    g.style.display = vis ? "" : "none";
  });
  document.querySelectorAll(".issue").forEach(function(s){
    var vis = Array.prototype.some.call(s.querySelectorAll(".card"), function(c){ return c.style.display !== "none"; });
    s.style.display = vis ? "" : "none";
  });
  document.getElementById("emptyState").hidden = anyVisible;
  document.getElementById("clearBtn").style.display = (q || tags.length) ? "" : "none";
}
function toggleTag(btn){
  var t = btn.getAttribute("data-tag");
  activeTags[t] = !activeTags[t];
  btn.classList.toggle("on", !!activeTags[t]);
  applyFilter();
}
function clearFilters(){
  document.getElementById("search").value = "";
  activeTags = {};
  document.querySelectorAll(".tagfilter").forEach(function(b){ b.classList.remove("on"); });
  applyFilter();
}
function copyCode(){
  var code = document.getElementById("inviteCode").textContent.trim();
  function done(){
    var el = document.getElementById("copyOk");
    el.style.opacity = 1;
    setTimeout(function(){ el.style.opacity = 0; }, 1500);
  }
  function fallback(){
    var ta = document.createElement("textarea");
    ta.value = code; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch(e){}
    document.body.removeChild(ta); done();
  }
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(code).then(done, fallback);
  } else { fallback(); }
}
document.getElementById("search").addEventListener("input", applyFilter);
document.querySelectorAll(".tagfilter").forEach(function(b){
  b.addEventListener("click", function(){ toggleTag(b); });
});
document.querySelectorAll(".pill").forEach(function(p){
  p.addEventListener("click", function(){
    var t = p.getAttribute("data-tag");
    var bar = document.querySelector('.tagfilter[data-tag="' + t + '"]');
    if (bar){ toggleTag(bar); }
    else { activeTags[t] = !activeTags[t]; applyFilter(); }
  });
});
</script>
</body>
</html>
"""


def git_commit_hash():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO, capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main():
    with open(README_PATH, encoding="utf-8") as f:
        text = f.read()
    data = parse_readme(text)

    sections_html = "\n".join(build_section(s) for s in data["sections"])
    tagpills = "".join(
        '<button class="tagfilter" data-tag="' + html.escape(t, quote=True)
        + '">' + html.escape(t) + "</button>"
        for t in data["all_tags"]
    )

    cst = timezone(timedelta(hours=8))
    build_time = datetime.now(cst).strftime("%Y-%m-%d %H:%M CST")
    avatar_uri = avatar_data_uri()

    page = PAGE_TEMPLATE
    page = page.replace("__INTRO__", md_inline(data["intro"]) or
                        "一份持续更新的 Meta Muse 真实使用案例合集，每日新增一节。")
    page = page.replace("__ISSUES__", str(len(data["sections"])))
    page = page.replace("__ENTRIES__", str(data["total"]))
    page = page.replace("__TAGS__", str(len(data["all_tags"])))
    page = page.replace("__INVITE_CODE__", html.escape(data["invite_code"]))
    page = page.replace("__JOIN_URL__", html.escape(data["join_url"], quote=True))
    page = page.replace("__TAGPILLS__", tagpills)
    page = page.replace("__SECTIONS__", sections_html)
    if FEATURED:
        featured_html = (
            '<div class="featured"><div class="featured-inner">'
            '<span class="featured-tag">' + html.escape(FEATURED["label"]) + "</span>"
            '<a class="title" href="' + html.escape(FEATURED["url"], quote=True)
            + '" target="_blank" rel="noopener">'
            + html.escape(FEATURED["title"]) + "</a>"
            '<span class="desc">' + html.escape(FEATURED.get("desc", "")) + "</span>"
            "</div></div>"
        )
    else:
        featured_html = ""
    page = page.replace("__FEATURED__", featured_html)
    if AUTHOR_X:
        avatar_img = ('<img class="avatar" src="' + avatar_uri + '" alt="">'
                      if avatar_uri else "")
        author_html = (
            "作者 X：" + avatar_img + '<a href="' + html.escape(AUTHOR_X["url"], quote=True)
            + '" target="_blank" rel="noopener">'
            + html.escape(AUTHOR_X["handle"]) + "</a>"
        )
    else:
        author_html = ""
    page = page.replace("__AUTHOR_X__", author_html)
    page = page.replace("__FAVICON__",
                        '<link rel="icon" href="' + avatar_uri + '">'
                        if avatar_uri else "")
    page = page.replace("__REPO_URL__", REPO_URL)
    page = page.replace("__BUILD_TIME__", build_time)
    page = page.replace("__COMMIT__", git_commit_hash())

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(page)

    print("OK: %d 期, %d 条目, %d 标签 -> %s"
          % (len(data["sections"]), data["total"], len(data["all_tags"]), OUT_PATH))


if __name__ == "__main__":
    main()
