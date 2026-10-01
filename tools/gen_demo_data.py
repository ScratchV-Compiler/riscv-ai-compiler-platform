#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成演示榜单数据（含**逐数据点原始代价**）。

产出 `data/demo_submissions.csv`，比原先多一列 `details`（JSON）。

**关键设计**：演示数据只存**原始代价 cost**，不存分数——分数由榜单按
动态基准（全场最优）现算。这样演示数据走的是和真实提交**完全相同**的链路，
不会出现"演示分数和计分规则对不上"的情况。

每支队伍有一个"能力曲线"：基准效率 + 随规模变化的形状。有的队小规模很强、
大规模崩掉（展开循环不扩展），有的队指令少但访存差（大 N 退化）——
这样逐数据点视图才有东西可看。

    .venv/bin/python tools/gen_demo_data.py
"""
import csv
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import riscv_problems as RP          # noqa: E402

BASELINE = os.path.join(ROOT, 'data', 'baseline.json')
# 指令数/cost 的比例直接从 baseline.json 的 by_size_instructions 推——
# 早先依赖 /tmp 里一个陈旧文件，既是隐患、换编译级别后还会算错
OUT = os.path.join(ROOT, 'data', 'demo_submissions.csv')

MISS_PENALTY = 15

# 队伍能力：(队名, 小N效率, 大N效率, 说明)
#   效率 = 本队代价 ÷ 参考解代价：<1 表示比参考解更快
#   「小N效率 → 大N效率」的走向体现该队的优化在规模上的可扩展性
TEAMS = [
    ('RISC-V 先锋队',   0.84, 0.88),   # 全面强，规模上去也不掉
    ('寄存器分配师',     0.88, 0.93),   # 强，但寄存器复用收益随规模摊薄
    ('指令数屠夫',       0.86, 1.02),   # 指令压得狠、访存没管 → 大 N 退化
    ('流水线突击队',     0.93, 0.97),   # 稳定中等
    ('展开循环小分队',   0.80, 1.28),   # 小 N 极强、大 N 崩（展开不扩展）
    ('定点特工队',       1.04, 1.10),   # 偏弱
    ('编译器摸鱼组',     1.18, 1.25),   # 最弱
]


def load_ratio(pid):
    """返回 (各规模 baseline 代价, 各规模的 指令数/代价 比例)。

    比例用来把 cost 拆回「指令数 + 15×未命中」，使演示数据自洽
    （演示数据里 cost 必须恰好等于 instructions + 15×d_miss）。
    """
    with open(BASELINE, encoding='utf-8') as f:
        data = json.load(f)
    entry = data[pid]
    base = {int(n): c for n, c in entry['by_size'].items()}
    insn = {int(n): c for n, c in entry.get('by_size_instructions', {}).items()}
    ratio = {n: (insn.get(n, 0) / c if c else 0.9) for n, c in base.items()}
    return base, ratio


def make_details(pid, spec, base, ratio, eff_small, eff_large, rng):
    """按能力曲线造一次提交的 details；返回 (details_dict, 总分估算)。"""
    sizes = spec['data_point_sizes']
    lo, hi = min(sizes), max(sizes)
    cases = []
    for i, n in enumerate(sizes):
        # 效率在规模上线性插值（对数刻度更贴近实际，但线性够用）
        t = (n - lo) / (hi - lo) if hi > lo else 0.0
        eff = eff_small + (eff_large - eff_small) * t
        eff *= rng.uniform(0.985, 1.015)          # 一点随机抖动
        cost = max(1, int(base[n] * eff))
        instr = max(1, int(cost * ratio[n]))      # 拆回指令数
        miss = max(0, round((cost - instr) / MISS_PENALTY))
        cost = instr + MISS_PENALTY * miss        # 取整后回代，保证自洽
        cases.append({
            'case': i, 'size': n, 'verdict': 'accepted',
            'points': 0.0,                        # 由榜单现算，这里不填
            'points_max': spec['points_per_case'],
            'instructions': instr, 'cost': cost,
            'd_miss': miss, 'd_access': miss * 2,
            'baseline': None, 'ratio': None, 'detail': '',
        })
    details = {
        'verdict': 'accepted', 'error': None,
        'message': '演示数据', 'problem': pid,
        'full_score': spec['full_score'],
        'cases': cases,
    }
    return details


def main():
    rng = random.Random(20261001)       # 固定种子，可复现
    rows = []
    for pid, spec in RP.EVAL_SPECS.items():
        base, ratio = load_ratio(pid)
        for team, e_small, e_large in TEAMS:
            # 每队每题 1~2 次提交：先来一次略差的，再来一次最终版
            for k in range(rng.randint(1, 2)):
                last = (k == 1)
                jitter = 1.0 if last else rng.uniform(1.05, 1.18)
                d = make_details(pid, spec, base, ratio,
                                 e_small * jitter, e_large * jitter, rng)
                if not last:
                    d['cases'] = [c for c in d['cases']]   # 早的一次也是全套数据点
                rows.append({
                    'team_name': team, 'problem_id': pid, 'status': 'success',
                    'score': 0.0,                    # 由榜单现算
                    'details': json.dumps(d, ensure_ascii=False, separators=(',', ':')),
                })
    rng.shuffle(rows)
    t = 0
    for r in rows:
        t += rng.randint(10, 30)
        r['offset_minutes'] = t
    rows.sort(key=lambda r: r['offset_minutes'])

    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['team_name', 'problem_id', 'status',
                                          'score', 'offset_minutes', 'details'])
        w.writeheader()
        w.writerows(rows)
    print(f'已写入 {OUT}：{len(rows)} 行，{len(TEAMS)} 队，含逐数据点 details')
    print(f'  文件大小 {os.path.getsize(OUT)/1024:.0f} KB')


if __name__ == '__main__':
    main()
