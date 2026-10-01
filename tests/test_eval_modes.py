# -*- coding: utf-8 -*-
"""评测失败模式。

运行：`python tests/test_eval_modes.py` 或 `python tests/run_all.py`
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

# 让死循环用例快点结束。**必须通过 temp_app(**) 传**——app.config 在导入 app
# 时就从 Config 快照了，之后再改 config.Config 不会生效。
app, _TMP = boot.temp_app(PER_CASE_TIMEOUT=3)
import riscv_oracle
import riscv_problems
ROOT = boot.ROOT
from evaluator import run_evaluation


WORK = tempfile.mkdtemp(prefix='evalcheck_')
def write_src(name, text):
    p = os.path.join(WORK, name)
    with open(p, 'w') as f:
        f.write(text)
    return p

# 各失败用例的汇编
SRC_ZEROS = """.text
.globl cnn_entry
cnn_entry:
    li t0, 0
    li t1, 16
    mv t2, a1
1:  sw t0, 0(t2)
    addi t2, t2, 4
    addi t1, t1, -1
    bnez t1, 1b
    ret
"""
SRC_OOB = """.text
.globl cnn_entry
cnn_entry:
    li t0, 1
    sw t0, 64(a1)
    ret
"""
SRC_LOOP = """.text
.globl cnn_entry
cnn_entry:
1:  j 1b
"""
SRC_SYNTAX = """.text
.globl cnn_entry
cnn_entry:
    this_is_not_an_instruction x0, x0, x0
"""
SRC_NOENTRY = """.text
.globl some_other_symbol
some_other_symbol:
    ret
"""
SRC_INCBIN = """.text
.globl cnn_entry
cnn_entry:
    .incbin "/etc/passwd"
    ret
"""

with app.app_context():
    # ---- 1. 参考解必须 accepted ----
    _, d = run_evaluation(1, 'team-a', 'matmul', os.path.join(ROOT, 'reference/matmul.s'))
    check('参考解 accepted', d['verdict'] == 'accepted', d['message'])
    check('参考解满分', d['score'] == 30.0, f"score={d['score']}")
    # 旧断言（固定 4x4 时代）已失效：规模分级后 baseline 是逐数据点的，
    # 顶层不再有单一 baseline_instructions。改为逐点校验参考解 == 该点基准。
    _cases = d['cases']
    # 注意：比的是 **cost**（代价 = 指令数 + 15×未命中），不是裸指令数——
    # baseline 存的就是代价。参考解跑出的代价应恰好等于各点基准。
    check('参考解在各数据点上的代价都等于该点基准（比值恒为 1）',
          all(c['cost'] == c['baseline'] for c in _cases),
          f"共 {len(_cases)} 点，首点 cost={_cases[0]['cost']} baseline={_cases[0]['baseline']}")

    # ---- 2. 失败模式分类 ----
    cases = [
        ('空文件', write_src('empty.s', ''), 'compile_error'),
        ('语法错误', write_src('syntax.s', SRC_SYNTAX), 'compile_error'),
        ('缺 cnn_entry', write_src('noentry.s', SRC_NOENTRY), 'compile_error'),
        ('越界写', write_src('oob.s', SRC_OOB), 'invalid'),
        ('输出乱填零', write_src('zeros.s', SRC_ZEROS), 'invalid'),
        ('死循环', write_src('loop.s', SRC_LOOP), 'timeout'),
        ('禁止 .incbin', write_src('incbin.s', SRC_INCBIN), 'compile_error'),
    ]
    for label, path, want in cases:
        _, d = run_evaluation(2, 'team-a', 'matmul', path)
        check(f'{label} → {want}', d['verdict'] == want, f"verdict={d['verdict']} msg={d['message'][:60]}")

    # ---- 3. 非 RISC-V 题（LeetCode 三道）应判 unsupported ----
    _, d = run_evaluation(3, 'team-a', 'add-two-numbers', os.path.join(ROOT, 'reference/matmul.s'))
    check('LeetCode 题 → unsupported', d['verdict'] == 'unsupported', d['message'])

    # ---- 4. 关键：硬编码答案必须失败（随机 seed 的意义）----
    # 规模分级后本题有 10 个数据点（4×4 → 64×64）。这里把小数据点（N=4）的答案
    # 写死进汇编：即便 N=4 那点侥幸命中，其余 9 个规模也必然失败。
    spec = riscv_problems.get_eval_spec('matmul')
    N0 = spec['data_point_sizes'][0]                 # 4
    fixed_vals = riscv_oracle.make_input(1, spec, N0)
    fixed_ans = riscv_oracle.reference(fixed_vals, spec, N0)
    body = "\n".join(f"    li t0, {v}\n    sw t0, {i*4}(a1)" for i, v in enumerate(fixed_ans))
    hardcoded = write_src('hardcode.s', f".text\n.globl cnn_entry\ncnn_entry:\n{body}\n    ret\n")
    _, d = run_evaluation(4, 'team-a', 'matmul', hardcoded)
    check('硬编码固定答案 → 拿不到满分',
          d['passed_cases'] <= 1 and d['score'] < spec['full_score'],
          f"verdict={d['verdict']} passed={d['passed_cases']}/{d['total_cases']} score={d['score']}")

    # 反证：把输入固定成 seed=1 也不过多蒙对一个小数据点——规模分级本身
    # 让"写死答案"这条路彻底走不通（这是规模分级带来的额外好处）。
    orig = riscv_oracle.make_input
    riscv_oracle.make_input = lambda seed, s, n: orig(1, s, n)
    _, d2 = run_evaluation(5, 'team-a', 'matmul', hardcoded)
    riscv_oracle.make_input = orig
    check('反证：输入固定后仍只有 N=4 那点能过（规模分级挡住了写死答案）',
          d2['passed_cases'] <= 1,
          f"passed={d2['passed_cases']}/{d2['total_cases']} score={d2['score']}")

boot.finish('评测失败模式')
