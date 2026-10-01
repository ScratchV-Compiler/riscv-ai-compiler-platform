# -*- coding: utf-8 -*-
"""
排行榜聚合（只读展示逻辑）。

刻意与 evaluator.py / tasks.py 解耦：这里只做"把库里已有成绩聚合成榜单"，
不参与编译、仿真与计分口径实现。
口径（docs/01-前端设计方案.md 5.3）：
- **动态基准**：基准 = 全场该数据点的最优（最小）指令数；
  某队得分 = 基准 ÷ 本队成绩 × 该点满分（对齐官方策划案口径，见 scoring.py）
- 分数在**读取时**现算——基准随全场水平浮动，写死在评测结果里会造成
  「先提交的拿满分、后提交的同样代码拿低分」
- 当日最优：同一队同一题取当日内最大值
- 总分 = 各题得分之和（三题满分 100）
- 每日 05:00（UTC+8）为结算点与配额重置点；榜单实时展示
"""
from datetime import datetime, timedelta, timezone

from models import Submission
from problems import problem_ids, get_problem
from riscv_problems import get_eval_spec, case_label
from scoring import (parse_details, field_best, score_details,
                     per_case_points, per_case_costs)

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
    problem = "all" → 按各题总分排名，逐题列出；
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

    subs = query.all()
    # 动态基准：分数在**读取时**用当前全场最优现算（见 scoring.py 的说明）。
    # 没有新格式原始数据的提交（旧记录）退回库里存的 score。
    parsed = [(sub, parse_details(sub)) for sub in subs]
    best = field_best([(sub.problem_id, d) for sub, d in parsed])

    # 单题视图：把该题的 10 个数据点铺成 10 列（逐点得分）
    size_cols = []
    if only:
        _spec = get_eval_spec(only)
        if _spec:
            size_cols = [(n, case_label(_spec, i))
                         for i, n in enumerate(_spec['data_point_sizes'])]

    teams = {}
    for sub, details in parsed:
        row = teams.setdefault(
            sub.team_name,
            {"team": sub.team_name, "scores": {}, "count": 0, "last": None,
             "by_size": {}, "by_cost": {}},
        )
        row["count"] += 1
        if row["last"] is None or sub.created_at > row["last"]:
            row["last"] = sub.created_at
        if sub.problem_id in scoring_cols:
            live_score, _ = score_details(sub.problem_id, details, best)
            score = live_score if live_score is not None else float(sub.score or 0.0)
            prev = row["scores"].get(sub.problem_id, 0.0)
            row["scores"][sub.problem_id] = max(prev, score)
            # 逐点得分：同一数据点取该队历次提交里的最高分
            for n, pts in per_case_points(sub.problem_id, details, best).items():
                if pts > row["by_size"].get(n, 0.0):
                    row["by_size"][n] = pts
            # 逐点**代价**（原始评测指标）：同一数据点取历次里的最小代价
            for n, cost in per_case_costs(sub.problem_id, details).items():
                cur = row["by_cost"].get(n)
                if cur is None or cost < cur:
                    row["by_cost"][n] = cost

    rows = []
    for row in teams.values():
        total = sum(row["scores"].get(pid, 0.0) for pid in scoring_cols)
        rows.append(
            {
                "team": row["team"],
                "scores": {pid: round(row["scores"].get(pid, 0.0), 2) for pid in display_cols},
                "total": round(total, 2),
                # 没打过的数据点用 None（模板显示「—」）——与"打了但得 0 分"区分开。
                # 旧记录（规模分级之前评的）没有 size 字段，会整行显示「—」。
                "by_size": {n: (round(row["by_size"][n], 2) if n in row["by_size"] else None)
                            for n, _ in size_cols},
                "by_cost": {n: row["by_cost"].get(n) for n, _ in size_cols},
                "count": row["count"],
                "last": row["last"],
                "last_str": fmt_local(row["last"]),
            }
        )

    rows.sort(key=lambda r: (-r["total"], r["last"] or datetime.min))
    for i, row in enumerate(rows, 1):
        row["rank"] = i

    # 每个题目列的第一名（得分最高）——汇总榜据此高亮。
    # 全 0 的题不高亮（没人得分时"并列第一"没有意义）。
    best_by_problem = {}
    for pid in display_cols:
        vals = [r["scores"].get(pid, 0.0) for r in rows]
        vals = [v for v in vals if v > 0]
        if vals:
            best_by_problem[pid] = max(vals)

    # 每个数据点列的最优（**代价最小**，即该点最快）——单题榜据此高亮
    best_by_size = {}
    for n, _ in size_cols:
        vals = [r["by_cost"][n] for r in rows if r.get("by_cost", {}).get(n) is not None]
        if vals:
            best_by_size[n] = min(vals)

    # 列头显示标题而不是 id —— id 形如 matmul，会与「定点矩阵乘」的题名对不上
    column_labels = {}
    for pid in display_cols:
        _p = get_problem(pid)
        column_labels[pid] = _p["title"] if _p else pid

    return {
        "columns": display_cols,
        "column_labels": column_labels,
        "size_columns": size_cols,
        "best_by_size": best_by_size,
        "best_by_problem": best_by_problem,
        "rows": rows,
        "total_label": "得分" if only else "总分",
        "since": since,
        "since_str": fmt_local(since),
        "stage": stage,
        "problem": problem,
        "single": only,
    }
