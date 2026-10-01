# -*- coding: utf-8 -*-
"""RISC-V 赛题的**评测规格**（与 `problems.py` 的展示元数据解耦）。

`problems.py` 只管题面怎么展示；这里管怎么评。两者用同一个 `id` 关联。
与 `standings.py` 一样，属于「运行期逻辑」而非「展示数据」。

内存布局（一次连续 dump，与 ScratchV 的 wrapper 同构）：

    guard_lo (256) | workspace (W) | guard_mid (256) | output (O) | guard_hi (256)

任一 guard 区非零 ⇒ 越界写 ⇒ 判失败。
`sp` 指向 **workspace 顶端**（栈向下生长落在 workspace 内）——这是相对 ScratchV
原 wrapper 的一处有意改进：ScratchV 的 `la sp, workspace` 会让栈向下写进 guard_lo，
等于禁止选手使用栈；钉住顶端后选手可以正常用栈，且溢出仍被 guard_lo 捕获。
"""

DATA_DIR_BASELINE = 'data/baseline.json'
GUARD_BYTES = 256

EVAL_SPECS = {
    'matmul-4x4': {
        'kind': 'riscv-asm',
        'kernel': 'matmul-4x4',
        'entry_symbol': 'cnn_entry',
        'file_suffix': '.s',
        'matrix_dim': 4,
        'input_elements': 32,        # A(4x4) 接 B(4x4)，行主序
        'output_elements': 16,       # C(4x4)，行主序
        'workspace_bytes': 1024,
        'guard_bytes': GUARD_BYTES,
        'tolerance': 0,              # 定点整数，要求逐位精确
        'full_score': 100.0,
        'baseline_file': DATA_DIR_BASELINE,
        # 每道题跑几个用例；每个用例一个随机 seed
        'case_count': 2,
        'title': '4x4 定点矩阵乘',
    },
}


def get_eval_spec(problem_id):
    """取评测规格；非 RISC-V 题（如 LeetCode 三道展示题）返回 None。"""
    return EVAL_SPECS.get(problem_id)


def is_riscv_problem(problem_id):
    return problem_id in EVAL_SPECS


def riscv_problem_ids():
    return list(EVAL_SPECS)


def layout(spec):
    """算出一个用例的内存布局，返回各区在 dump 里的 (offset, size)。

    runner 生成 wrapper、评测解析 dump 都从这里取偏移，避免两处各写一份常量。
    """
    guard = spec['guard_bytes']
    ws = spec['workspace_bytes']
    out_bytes = spec['output_elements'] * 4

    guard_lo = (0, guard)
    workspace = (guard, ws)
    guard_mid = (guard + ws, guard)
    output = (guard + ws + guard, out_bytes)
    guard_hi = (guard + ws + guard + out_bytes, guard)

    return {
        'guard_lo': guard_lo,
        'workspace': workspace,
        'guard_mid': guard_mid,
        'output': output,
        'guard_hi': guard_hi,
        'total': guard + ws + guard + out_bytes + guard,
        'stack_top': guard + ws,   # sp 初始值：workspace 顶端
    }
