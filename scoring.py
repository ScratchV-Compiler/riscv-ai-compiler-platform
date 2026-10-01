# -*- coding: utf-8 -*-
"""动态基准计分（对齐官方策划案口径）：**基准 = 全场最优**。

    某队得分 = 基准 ÷ 该队成绩 × 满分
    基准 = 所有参赛队伍中该数据点的最优（最小）**代价**

「成绩」是 cost 而非裸指令数：cost = 指令数 + α × L1 未命中（α 见 config.MISS_PENALTY）。
旧记录（换指标前评的）没有 cost 字段，退回用 instructions 充当，等价于 α=0。

## 为什么必须实时算，而不是评测时算

基准依赖"全场最优"，而全场最优随时间变化。如果评测时就把分数固定下来：
先提交的队伍拿 100 分，后提交的队伍用**完全相同**的代码只能拿更低的分——
这既不公平，也让人无法理解。所以：

- **评测器**只负责产出**原始数据**（每个数据点的动态指令数），落进 `details`
- **分数在读取时**（榜单、结果页）用当前全场最优现算

## 与"固定基准"的差别

固定基准（早期实现）+ `min(1, 基准/本队)` 会**封顶**：只要比参考解快就都是满分。
实测八人场：区分指数 D = **0.000**（全部 100 分）。动态基准下 D ≈ 0.59。
"""

import json

from riscv_problems import get_eval_spec


def parse_details(sub):
    """把 Submission.details 解析成 dict；坏数据返回 None。"""
    if not sub.details:
        return None
    try:
        d = json.loads(sub.details)
    except (ValueError, TypeError):
        return None
    return d if isinstance(d, dict) else None


def case_records(details):
    """从 details 里取出可计分的数据点记录。

    只认新格式（含 size / instructions / points_max）；旧格式返回空列表，
    调用方会退回 submission.score。
    """
    if not details:
        return []
    out = []
    for c in details.get('cases') or []:
        if not isinstance(c, dict):
            continue
        n = c.get('size')
        cnt = c.get('instructions')
        pmax = c.get('points_max')
        if n is None or pmax is None:
            continue
        # 指标是 cost；旧记录没有该字段则退回 instructions（等价 α=0）
        measure = c.get('cost')
        if measure is None:
            measure = cnt
        out.append({'size': n, 'instructions': cnt, 'cost': measure,
                    'points_max': pmax, 'verdict': c.get('verdict')})
    return out


def field_best(submissions):
    """算出全场最优：{(problem_id, N): 最小指令数}。

    只统计**做对**的数据点。输入是 (problem_id, details) 的迭代。
    """
    best = {}
    for problem_id, details in submissions:
        for c in case_records(details):
            if c['verdict'] != 'accepted' or not c['cost']:
                continue
            key = (problem_id, c['size'])
            cur = best.get(key)
            if cur is None or c['cost'] < cur:
                best[key] = c['cost']
    return best


def score_details(problem_id, details, best, spec=None):
    """按动态基准算一次提交的得分；返回 (score, scored_points)。

    score 可能低于评测时的快照分——因为随着全场变强，基准被拉高了。
    """
    recs = case_records(details)
    if not recs:
        return None, 0
    total = 0.0
    scored = 0
    for c in recs:
        if c['verdict'] != 'accepted' or not c['cost']:
            continue
        base = best.get((problem_id, c['size']))
        if not base:
            continue
        total += c['points_max'] * min(1.0, base / c['cost'])
        scored += 1
    return round(total, 2), scored


def per_case_points(problem_id, details, best):
    """按动态基准算**每个数据点**的得分；返回 {规模N: 得分}。

    榜单选中单题时用它把 10 个数据点铺成 10 列——逐点得分能看出
    「哪几个规模做得好、哪个规模崩了」，比只看合计分有信息量得多。
    """
    out = {}
    for c in case_records(details):
        if c['verdict'] != 'accepted' or not c['cost']:
            continue
        base = best.get((problem_id, c['size']))
        if not base:
            continue
        out[c['size']] = round(c['points_max'] * min(1.0, base / c['cost']), 3)
    return out


def full_score_of(details, spec=None):
    """该提交所属题目的满分（优先取 details 里记的，退回规格）。"""
    if details and details.get('full_score') is not None:
        return details['full_score']
    if spec:
        return spec['full_score']
    return None


def build_score_table(submissions):
    """给定一批 Submission，返回 {submission_id: 动态得分}。

    对没有新格式数据（或没有可用数据点）的提交，**不放进表**——
    调用方用 submission.score 兜底。
    """
    parsed = [(s.id, s.problem_id, parse_details(s)) for s in submissions]
    best = field_best([(pid, d) for _, pid, d in parsed])
    table = {}
    for sid, pid, d in parsed:
        sc, scored = score_details(pid, d, best)
        if sc is not None and scored > 0:
            table[sid] = sc
    return table, best
