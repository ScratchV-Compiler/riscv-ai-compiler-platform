# -*- coding: utf-8 -*-
"""
排行榜聚合（只读展示逻辑）。

刻意与 evaluator.py / tasks.py 解耦：这里只做"把库里已有成绩聚合成榜单"，
不参与编译、仿真与计分口径实现。
口径（docs/01-前端设计方案.md 5.3）：
- 单题得分 = 100 ×（全场该题最优时间 ÷ 本队该题时间），本处以库中已有 score 为准
- 当日最优：同一队同一题取当日内最大值
- 总分 = 各题得分之和（3 题，满分 300）
- 每日 05:00（UTC+8）为结算点与配额重置点；榜单实时展示
"""
from datetime import datetime, timedelta, timezone

from models import Submission
from problems import problem_ids

UTC8 = timezone(timedelta(hours=8))
RESET_HOUR = 5
VALID_STATUSES = ("success",)  # 当前后端用 success 表示有效提交


def fmt_local(dt):
    """库中存的是朴素 UTC，展示时转成 UTC+8。"""
    if dt is None:
        return "—"
    return dt.replace(tzinfo=timezone.utc).astimezone(UTC8).strftime("%m-%d %H:%M")


def last_reset_utc(now=None):
    """最近一次 05:00（UTC+8）对应的 UTC 朴素时间，用于与库中的 created_at 比较。"""
    now = now or datetime.now(UTC8)
    reset_local = now.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)
    if now < reset_local:
        reset_local -= timedelta(days=1)
    return reset_local.astimezone(timezone.utc).replace(tzinfo=None)


def build_standings(problem="all", stage=1):
    """
    返回 {columns, rows, total_label, since}。
    problem = "all" → 按三题总分排名，三列全出；
    problem = 题目 id → 只按该题排名，只出该列。
    """
    ids = problem_ids()
    only = problem if problem in ids else None
    scoring_cols = [only] if only else ids          # 参与计分的题
    display_cols = [] if only else ids              # 表格里逐题展示的列

    since = last_reset_utc()
    query = Submission.query.filter(
        Submission.created_at >= since,
        Submission.status.in_(VALID_STATUSES),
    )
    if only:
        query = query.filter_by(problem_id=only)

    teams = {}
    for sub in query.all():
        row = teams.setdefault(
            sub.team_name,
            {"team": sub.team_name, "scores": {}, "count": 0, "last": None},
        )
        row["count"] += 1
        if row["last"] is None or sub.created_at > row["last"]:
            row["last"] = sub.created_at
        if sub.problem_id in scoring_cols:
            prev = row["scores"].get(sub.problem_id, 0.0)
            row["scores"][sub.problem_id] = max(prev, float(sub.score or 0.0))

    rows = []
    for row in teams.values():
        total = sum(row["scores"].get(pid, 0.0) for pid in scoring_cols)
        rows.append(
            {
                "team": row["team"],
                "scores": {pid: round(row["scores"].get(pid, 0.0), 2) for pid in display_cols},
                "total": round(total, 2),
                "count": row["count"],
                "last": row["last"],
                "last_str": fmt_local(row["last"]),
            }
        )

    rows.sort(key=lambda r: (-r["total"], r["last"] or datetime.min))
    for i, row in enumerate(rows, 1):
        row["rank"] = i

    return {
        "columns": display_cols,
        "rows": rows,
        "total_label": "得分" if only else "总分",
        "since": since,
        "since_str": fmt_local(since),
        "stage": stage,
        "problem": problem,
        "single": only,
    }
