# -*- coding: utf-8 -*-
"""规模分级与逐点计分（多场次）。

运行：`python tests/test_eval_scale.py` 或 `python tests/run_all.py`
用**临时库**，不碰 platform.db。

覆盖两场竞赛各自的卷子：全局题册里现在有 6 道题（内测比赛1 的
add/matmul/reducesum + 内测比赛2 的 fwht/winograd/spmm），本题逐一校验规格、
逐点 baseline 覆盖、参考解满分，并单独验证浮点容差口径。
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap as boot
from _bootstrap import check

app, _TMP = boot.temp_app()
import riscv_oracle
import riscv_problems as RP
import contests
from evaluator import run_evaluation
ROOT = boot.ROOT

PAPERS = (
    ('riscv-ai', 'data/baseline.json', ('add', 'matmul', 'reducesum')),
    ('demo', 'data/contests/demo/baseline.json', ('fwht', 'winograd', 'spmm')),
)


def ref_src(pid):
    return os.path.join(ROOT, RP.get_eval_spec(pid)['reference'].replace('.c', '.s'))


with app.app_context():
    # ---- 全局规格自检 ----
    check('每题各 10 个数据点', all(s['case_count'] == 10 for s in RP.EVAL_SPECS.values()))
    sizes_ok = all(
        s['data_point_sizes'] == sorted(s['data_point_sizes'])
        and len(set(s['data_point_sizes'])) == 10
        for s in RP.EVAL_SPECS.values())
    check('各题 10 个规模互不相同且递增', sizes_ok,
          {k: v['data_point_sizes'] for k, v in RP.EVAL_SPECS.items()})

    # 自描述题：规模标量必须都能映射到形状配置
    for pid in ('winograd', 'spmm'):
        s = RP.EVAL_SPECS[pid]
        check(f'{pid} 的 params_by_size 覆盖全部规模',
              all(n in s['params_by_size'] for n in s['data_point_sizes']))

    # ---- 每场：卷面分值 30/30/40 合计 100 ----
    for slug, _bl, pids in PAPERS:
        c = contests.get_contest(slug)
        got = tuple(contests.get_eval_spec(p, c)['full_score'] for p in pids)
        check(f'{slug} 卷面分值 {got} 合计 100',
              got == (30, 30, 40) and contests.total_full_score(c) == 100, got)

    # ---- 每场：baseline 覆盖每个数据点的规模 ----
    for slug, bl_rel, pids in PAPERS:
        c = contests.get_contest(slug)
        bl = json.load(open(os.path.join(ROOT, bl_rel), encoding='utf-8'))
        ok = all(
            set(bl[p]['by_size']) == {str(n) for n in
                                      contests.get_eval_spec(p, c)['data_point_sizes']}
            for p in pids)
        check(f'{slug} baseline 覆盖每个数据点的规模', ok,
              {p: len(bl[p]['by_size']) for p in pids if p in bl})

    # ---- 每场：参考解逐点满分（含耗时）----
    for slug, _bl, pids in PAPERS:
        for pid in pids:
            t0 = time.time()
            score, d = run_evaluation(1, 'team-a', pid, ref_src(pid), contest=slug)
            dt = time.time() - t0
            full = contests.get_eval_spec(pid, contests.get_contest(slug))['full_score']
            sizes = [c['size'] for c in d['cases']]
            check(f'{slug}/{pid} 参考解满分 {full}',
                  score == full and d['verdict'] == 'accepted' and d['passed_cases'] == 10,
                  f"score={score}/{full} passed={d['passed_cases']} 耗时={dt:.1f}s 规模={sizes}")

    # ---- 逐点独立性：让第 2/5/9 个数据点判错（默认场次的 matmul）----
    orig = riscv_oracle.reference
    calls = {'n': 0}
    def faulty(values, spec, n):
        i = calls['n']; calls['n'] += 1
        out = orig(values, spec, n)
        return [x + 1 for x in out] if i in (2, 5, 9) else out
    riscv_oracle.reference = faulty
    try:
        score, d = run_evaluation(2, 'team-a', 'matmul', ref_src('matmul'))
    finally:
        riscv_oracle.reference = orig
    check('逐点独立计分：7/10 通过 → 21 分',
          d['passed_cases'] == 7 and score == 21.0 and d['verdict'] == 'partial'
          and d['error'] is None,
          f"passed={d['passed_cases']} score={score} verdict={d['verdict']}")
    failed = [c for c in d['cases'] if c['verdict'] != 'accepted']
    check('失败点得 0 分、其余点满分',
          all(c['points'] == 0.0 for c in failed) and len(failed) == 3
          and all(c['points'] == 3.0 for c in d['cases'] if c['verdict'] == 'accepted'),
          f"失败点 {[c['case'] for c in failed]}")

    # ---- 逐点 baseline 确实不同（不是同一个数）----
    _, d = run_evaluation(3, 'team-a', 'add', ref_src('add'))
    bls = [c['baseline'] for c in d['cases']]
    check('每个数据点用各自的 baseline（互不相同且递增）',
          bls == sorted(bls) and len(set(bls)) == 10, bls)

    # ---- 浮点容差口径（winograd）----
    fspec = RP.EVAL_SPECS['winograd']
    check('浮点容差：小偏差通过', riscv_oracle.check_output([1.0], [1.0 + 1e-5], fspec)[0])
    check('浮点容差：大偏差不通过', not riscv_oracle.check_output([1.0], [1.5], fspec)[0])
    check('整数题仍是精确比对', not riscv_oracle.check_output([1], [2], RP.EVAL_SPECS['matmul'])[0])

boot.finish('规模分级与逐点计分')
