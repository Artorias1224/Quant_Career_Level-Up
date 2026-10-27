"""核对显式交付记录，生成可离线打开的近期与全量目录。仅用标准库。"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import sys
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parent
CST = timezone(timedelta(hours=8), name="Asia/Shanghai")
DELIVERY = {"task_card_only": "仅任务卡，完整讲义待补", "partial": "部分交付", "complete": "完整文件已交付"}
LEARNING = {"awaiting_feedback": "待学习反馈", "submitted": "已提交，待验收", "needs_revision": "需修改或补学", "passed": "已通过验收"}
KINDS = {"markdown", "html", "pdf", "python", "data", "zip", "other"}
EXTENSIONS = {"markdown": {".md"}, "html": {".html", ".htm"}, "pdf": {".pdf"}, "python": {".py"}, "zip": {".zip"}}


def local_file(value: str) -> Path:
    part = PurePosixPath(value)
    if not value or "\\" in value or ":" in value or part.is_absolute() or ".." in part.parts:
        raise ValueError(f"必须使用根目录内的相对路径：{value}")
    target = (ROOT / part).resolve()
    if not target.is_relative_to(ROOT) or not target.is_file() or target.stat().st_size == 0:
        raise ValueError(f"附件不存在、为空或越出学习目录：{value}")
    return target


def validate(data: dict) -> None:
    if data.get("schema_version") != 1 or data.get("timezone") != "Asia/Shanghai" or data.get("recent_calendar_days") != 10:
        raise ValueError("记录版本、时区或十个自然日窗口不符合约定")
    seen = set()
    for row in data["records"]:
        ident = row["task_id"]
        if not ident or ident in seen:
            raise ValueError(f"重复或空的 task_id：{ident}")
        seen.add(ident)
        first = date.fromisoformat(row["date"])
        last = date.fromisoformat(row["last_delivery_date"])
        if first > last:
            raise ValueError(f"交付日期早于布置日期：{ident}")
        if row["delivery_status"] not in DELIVERY or row["learning_status"] not in LEARNING:
            raise ValueError(f"状态值不符合约定：{ident}")
        if not row["title"] or not row["level"]:
            raise ValueError(f"缺少标题或关卡：{ident}")
        kinds, paths, artifact_dates = set(), set(), []
        for artifact in row["artifacts"]:
            kind, name = artifact["kind"], artifact["path"]
            if kind not in KINDS or name in paths:
                raise ValueError(f"无效类型或重复附件：{name}")
            target = local_file(name)
            if kind in EXTENSIONS and target.suffix.lower() not in EXTENSIONS[kind]:
                raise ValueError(f"扩展名与附件类型不符：{name}")
            if kind in {"html", "markdown", "python"}:
                target.read_text(encoding="utf-8-sig")
            kinds.add(kind)
            paths.add(name)
            artifact_dates.append(date.fromisoformat(artifact["created_on"]))
        if not artifact_dates or max(artifact_dates) != last or min(artifact_dates) < first:
            raise ValueError(f"附件日期与最近实际交付日期不符：{ident}")
        expected, missing = set(row["expected_artifacts"]), set(row["missing_artifacts"])
        if not expected <= KINDS or missing != expected - kinds:
            raise ValueError(f"缺失清单与实际附件不一致：{ident}")
        if (row["delivery_status"] == "complete") != (not missing):
            raise ValueError(f"完整交付状态与缺失附件不一致：{ident}")
        if row["delivery_status"] == "task_card_only" and kinds != {"markdown"}:
            raise ValueError(f"仅任务卡状态与实际附件不符：{ident}")
        if row["learning_status"] in {"submitted", "passed"} and not row["learning_evidence"]:
            raise ValueError(f"提交或通过状态没有学习证据：{ident}")


def link(path: str, label: str) -> str:
    return f'<a href="{quote(path, safe="/")}">{escape(label)}</a>'


def entry(row: dict) -> str:
    attachments = " · ".join(link(a["path"], a["label"]) for a in row["artifacts"])
    missing = "、".join(row["missing_artifacts"]) or "无"
    return (
        '<article><p class="meta">' + escape(row["last_delivery_date"] + " · " + row["level"]) + '</p>'
        '<h3>' + escape(row["title"]) + '</h3><p><strong>交付：</strong>' + DELIVERY[row["delivery_status"]]
        + '。<strong>学习：</strong>' + LEARNING[row["learning_status"]] + '。</p><p>' + attachments
        + '</p><p class="muted">待补附件：' + escape(missing) + '。</p><p><strong>下一步：</strong>'
        + escape(row.get("next_action", "按学习进度继续")) + '</p></article>'
    )


def render(data: dict) -> str:
    now = datetime.now(CST)
    lower = now.date() - timedelta(days=9)
    rows = sorted(data["records"], key=lambda r: (r["last_delivery_date"], r["task_id"]), reverse=True)
    recent = [r for r in rows if lower <= date.fromisoformat(r["last_delivery_date"]) <= now.date()]
    nav = " · ".join(link(p, label) for p, label in [
        ("学习路线.md", "学习路线"), ("个人偏好.md", "个人偏好"), ("学习进度.md", "学习进度"),
        ("定时任务提示词.md", "执行提示词"), ("history.json", "交付记录"),
        ("云端迁移说明.md", "云端迁移说明"), ("云端迁移包.md", "单文件迁移包"),
        ("修订记录/2026-10-27-v4修改.md", "v4 修改记录")])
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>量化职业晋级打怪 · 学习目录</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f7f5ef;color:#26372f;font:17px/1.85 "Microsoft YaHei",sans-serif}}
main{{max-width:960px;margin:auto;padding:48px 28px 64px}}h1,h2,h3{{line-height:1.45}}h1{{font-size:34px;margin:8px 0 16px}}
h2{{font-size:24px;margin-top:38px}}h3{{font-size:20px;margin:8px 0}}a{{color:#146a5b;text-underline-offset:4px;overflow-wrap:anywhere}}
article,.notice{{padding:22px 26px;background:#fff;border:1px solid #d9e0d7;border-radius:12px;margin:18px 0}}
.notice{{border-left:5px solid #ad783b;background:#fff9ed}}.meta,.muted,footer{{color:#627267;font-size:14px}}p{{margin:10px 0}}
nav{{padding:15px 0;border-bottom:1px solid #d9e0d7}}summary{{cursor:pointer;font-weight:bold}}footer{{margin-top:32px}}
@media(max-width:600px){{main{{padding:24px 16px}}h1{{font-size:27px}}article,.notice{{padding:18px}}}}
@media print{{body{{background:white}}main{{max-width:none;padding:0}}article{{break-inside:avoid}}}}
</style></head><body><main><p class="meta">一个贯穿项目 · 按证据晋级 · 每天北京时间 20:30</p>
<h1>量化职业晋级打怪</h1><p>研报经营预期变化的增量信息研究</p><nav>{nav}</nav>
<aside class="notice"><strong>文件交付和学习掌握分别记录。</strong><p>这里只链接真实存在的文件。任务卡不等于完整讲义，材料生成不等于本人掌握。当前关卡与反馈以学习进度为准。</p>
<p>v4 目标为每天北京时间 20:30 云端执行、跨设备查看；本页是可选本机备份。现有任务仍为本机过渡任务，云端迁移尚待完成，请查看上方迁移入口。</p></aside>
<h2>最近十个自然日</h2><p class="muted">{lower.isoformat()} 至 {now.date().isoformat()}，按最近实际文件交付日期展示；缺失日期不补造。</p>
{''.join(entry(r) for r in recent) or '<p>此窗口内没有实际交付记录，可查看下方全量目录。</p>'}
<h2>全部学习单元</h2>{''.join(entry(r) for r in rows) or '<p>尚无实际记录。</p>'}
<footer>目录生成于 {now.strftime('%Y-%m-%d %H:%M:%S')}（Asia/Shanghai）。由 history.json 显式记录生成；不自动判定学习完成。目录页不是完整讲义。</footer>
</main></body></html>'''


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(v for k, v in attrs if k == "href" and v)


def check_links(html: str) -> None:
    parser = Links()
    parser.feed(html)
    for href in parser.hrefs:
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            raise ValueError(f"目录只应链接本地文件：{href}")
        if parsed.path:
            local_file(unquote(parsed.path))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    cli = argparse.ArgumentParser(description=__doc__)
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="只核对记录、文件和已有目录的链接")
    mode.add_argument("--build", action="store_true", help="核对后原子更新离线目录，不改学习状态")
    args = cli.parse_args()
    data = json.loads((ROOT / "history.json").read_text(encoding="utf-8-sig"))
    validate(data)
    page = render(data)
    check_links(page)
    output = ROOT / "index.html"
    if args.build:
        pending = ROOT / "index.pending.html"
        pending.write_text(page, encoding="utf-8")
        pending.replace(output)
        print(f"目录已生成：{output}")
    elif output.exists():
        check_links(output.read_text(encoding="utf-8"))
    count = sum(len(r["artifacts"]) for r in data["records"])
    missing = sum(len(r["missing_artifacts"]) for r in data["records"])
    print(f"核对通过：{len(data['records'])} 个学习单元，{count} 个真实附件，{missing} 个明确待补附件。")
    print("此结果不表示用户已完成，也不验证 PDF 内容或整次自动调度。")


if __name__ == "__main__":
    main()
