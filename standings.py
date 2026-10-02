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
- **历史最优**：同一队同一题取**全部有效提交**里的最大值（跨日累计，
  不随结算清零）。名次只增不减，未再次提交的队伍不会被挤出榜单。
- **单题视图的逐点列 = 该队该题总得分最高那次提交的逐点「评测值（代价）」**，
  与「得分」列同源（整行同一次提交）。展示的是**评测指标（代价）**而非换算后的得分，
  且不跨提交拼接、不显示相对全场最优的差距。
- 总分 = 各题得分之和（三题满分 100）
- 每日 05:00（UTC+8）只重置**提交配额**（见 app._team_quota_used）；
  榜单按历史最优实时展示，没有"每日结算定格"这一步。
"""
from datetime import datetime, timedelta, timezone

from models import Submission
from problems import problem_ids, get_problem
from riscv_problems import get_eval_spec, case_label
from scoring import (parse_details, field_best, score_details, per_case_costs)

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
    返回 {columns, rows, total_label}。
    problem = "all" → 按各题总分排名，逐题列出；
    problem = 题目 id → 只按该题排名，只出该列。

    统计范围是**全部历史有效提交**（不按 05:00 结算点裁剪窗口）——
    榜单是跨日累计的，配额重置不影响已取得的成绩。
    """
    ids = problem_ids()
    only = problem if problem in ids else None
    scoring_cols = [only] if only else ids          # 参与计分的题
    display_cols = [] if only else ids              # 表格里逐题展示的列

    query = Submission.query.filter(
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
             "by_cost": {}},
        )
        row["count"] += 1
        if row["last"] is None or sub.created_at > row["last"]:
            row["last"] = sub.created_at
        if sub.problem_id in scoring_cols:
            live_score, _ = score_details(sub.problem_id, details, best)
            score = live_score if live_score is not None else float(sub.score or 0.0)
            # 「得分」= 该队该题**最好的一次提交**（独立计分后取最大）——排名与总分口径。
            # 单题视图的逐点列与它**同源**：整行都取这一次提交的逐点**评测值（代价）**，
            # 不跨提交拼并集，也不额外展示相对 t_best 的差距。
            if sub.problem_id not in row["scores"] or score > row["scores"][sub.problem_id]:
                row["scores"][sub.problem_id] = score
                row["by_cost"][sub.problem_id] = per_case_costs(sub.problem_id, details)

    rows = []
    for row in teams.values():
        total = sum(row["scores"].get(pid, 0.0) for pid in scoring_cols)
        # 逐点列只在单题视图里出现，此时只有该题的提交，直接取该题的"最好提交"。
        best_cost = row["by_cost"].get(only, {}) if only else {}
        rows.append(
            {
                "team": row["team"],
                "scores": {pid: round(row["scores"].get(pid, 0.0), 2) for pid in display_cols},
                "total": round(total, 2),
                # 没打过的数据点用 None（模板显示「—」）——与"打了但得 0 分"区分开。
                # 旧记录（规模分级之前评的）没有 size 字段，会整行显示「—」。
                "by_cost": {n: best_cost.get(n) for n, _ in size_cols},
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

    # 每个数据点列的**全场纪录**（代价最小，即该点最快）——单题榜据此高亮。
    # 用 field_best（全部提交的最小代价）而不是"表内行最小"：展示列是各家
    # "最好那次提交"的快照，行最小可能高于真纪录（纪录由该队另一次提交保持），
    # 那样高亮会谎称"该点代价最小"。高亮只给真正追平纪录的格子。
    best_by_size = {}
    for n, _ in size_cols:
        b = best.get((only, n))
        if b is not None:
            best_by_size[n] = b

    # 每个数据点的**全榜最优代价**（= 参考站 CANNJudge 的 `t_best`：全榜当前最小值，
    # 会随别人的提交下降）。单题榜在列头下方标成一行，当冲榜靶子用。
    tbest_by_size = {}
    for n, _ in size_cols:
        b = best.get((only, n))
        if b is not None:
            tbest_by_size[n] = b

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
        "tbest_by_size": tbest_by_size,
        "best_by_problem": best_by_problem,
        "rows": rows,
        "total_label": "得分" if only else "总分",
        "stage": stage,
        "problem": problem,
        "single": only,
    }
