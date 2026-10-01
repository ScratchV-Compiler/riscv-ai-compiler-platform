# -*- coding: utf-8 -*-
"""动态基准计分。

运行：`python tests/test_scoring_dynamic.py` 或 `python tests/run_all.py`
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
from scoring import (field_best, score_details, build_score_table,
                     case_records)



def mk(problem, counts, points=3.0, ok=True):
    """造一个 details：counts 是每个数据点的指令数。"""
    return {
        'problem': problem,
        'full_score': points * len(counts),
        'cases': [
            {'case': i, 'size': 100 + i, 'verdict': 'accepted' if ok else 'invalid',
             'instructions': c, 'points_max': points, 'ratio': None}
            for i, c in enumerate(counts)
        ],
    }

# ---- 1. field_best 取全场最小 ----
A = mk('add', [1000, 2000])
B = mk('add', [800, 3000])
best = field_best([('add', A), ('add', B)])
check('field_best 取每个数据点的全场最小',
      best == {('add', 100): 800, ('add', 101): 2000}, best)

# ---- 2. 最快者满分，其余按比例 ----
scA, nA = score_details('add', A, best)
scB, nB = score_details('add', B, best)
# A: 点0 3*min(1,800/1000)=2.4 ; 点1 3*min(1,2000/2000)=3.0 → 5.4
# B: 点0 3*1=3.0 ; 点1 3*min(1,2000/3000)=2.0 → 5.0
check('最快者按比例得分（A=5.4 B=5.0）',
      abs(scA-5.4) < 1e-6 and abs(scB-5.0) < 1e-6, f"A={scA} B={scB}")

# ---- 3. 并列公平：指令数完全相同 -> 分数完全相同 ----
C = mk('add', [800, 3000])          # 与 B 完全相同
scC, _ = score_details('add', C, best)
check('相同指令数 -> 相同分数（并列公平）', abs(scC - scB) < 1e-9, f"B={scB} C={scC}")

# ---- 4. 黑马出现后，原领先者分数被压低（动态基准的核心性质）----
room = [('add', A), ('add', B)]
before = build_score_table(_S := [type('S', (), {'id': i, 'problem_id': 'add', 'details': json.dumps(d)})()
                                  for i, d in enumerate((A, B))])[0]
H = mk('add', [400, 1500])          # 黑马：两个点都更快
subs = [type('S', (), {'id': i, 'problem_id': 'add', 'details': json.dumps(d)})()
        for i, d in enumerate((A, B, H))]
after, best2 = build_score_table(subs)
check('黑马出现后基准被拉低', best2[('add',100)] == 400 and best2[('add',101)] == 1500, best2)
check('黑马拿满分，原最快者被压低',
      abs(after[2] - 6.0) < 1e-6 and after[0] < before[0],
      f"黑马={after[2]} A: {before[0]}→{after[0]}")

# ---- 5. 做错的数据点不计分、也不参与基准 ----
D = mk('add', [500, 100], ok=False)
best3 = field_best([('add', D)])
check('做错的点不进基准', best3 == {}, best3)
scD, nD = score_details('add', D, {('add',100):500,('add',101):100})
check('做错的点不计分', scD == 0.0 and nD == 0, f"score={scD} scored={nD}")

# ---- 6. 旧格式（无 cases）返回 None，调用方回退 submission.score ----
check('旧格式无 cases -> None（交调用方兜底）',
      score_details('add', {'problem':'add'}, best) == (None, 0))
check('case_records 对坏数据不炸', case_records(None) == [] and case_records({'cases':[None,1]}) == [])

boot.finish('动态基准计分')
