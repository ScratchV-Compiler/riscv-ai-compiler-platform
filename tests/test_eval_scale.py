# -*- coding: utf-8 -*-
"""规模分级与逐点计分。

运行：`python tests/test_eval_scale.py` 或 `python tests/run_all.py`
用**临时库**，不碰 platform.db。
"""
import os
import sys
import tempfile
import io
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap as boot
from _bootstrap import check

app, _TMP = boot.temp_app()
import riscv_oracle
import riscv_problems as RP
from evaluator import run_evaluation
ROOT = boot.ROOT


def ref_src(pid):
    return os.path.join(ROOT, RP.get_eval_spec(pid)['reference'].replace('.c', '.s'))

with app.app_context():
    # ---- 规格自检 ----
    check('三题各 10 个数据点', all(s['case_count'] == 10 for s in RP.EVAL_SPECS.values()))
    check('分值 30/30/40 合计 100',
          (RP.EVAL_SPECS['add']['full_score'], RP.EVAL_SPECS['matmul']['full_score'],
           RP.EVAL_SPECS['reducesum']['full_score']) == (30, 30, 40)
          and RP.total_full_score() == 100)
    sizes_ok = all(
        s['data_point_sizes'] == sorted(s['data_point_sizes'])
        and len(set(s['data_point_sizes'])) == 10
        for s in RP.EVAL_SPECS.values())
    check('各题 10 个规模互不相同且递增', sizes_ok,
          {k: v['data_point_sizes'] for k, v in RP.EVAL_SPECS.items()})

    # ---- baseline 逐点 ----
    bl = json.load(open(os.path.join(ROOT, RP.DATA_DIR_BASELINE), encoding='utf-8'))
    ok_bl = all(set(bl[k]['by_size'].keys()) == {str(n) for n in s['data_point_sizes']}
                for k, s in RP.EVAL_SPECS.items())
    check('baseline 覆盖每个数据点的规模', ok_bl,
          {k: len(v['by_size']) for k, v in bl.items()})

    # ---- 参考解逐点满分（含耗时）----
    for pid in ('add', 'matmul', 'reducesum'):
        t0 = time.time()
        score, d = run_evaluation(1, 'team-a', pid, ref_src(pid))
        dt = time.time() - t0
        full = RP.EVAL_SPECS[pid]['full_score']
        sizes = [c['size'] for c in d['cases']]
        check(f'{pid} 参考解满分 {full}',
              score == full and d['verdict'] == 'accepted' and d['passed_cases'] == 10,
              f"score={score}/{full} passed={d['passed_cases']} 耗时={dt:.1f}s 规模={sizes}")

    # ---- 逐点独立性：让第 2/5/9 个数据点判错 ----
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

boot.finish('规模分级与逐点计分')
