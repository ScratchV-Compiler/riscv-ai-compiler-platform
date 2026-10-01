# -*- coding: utf-8 -*-
"""RISC-V 赛题的**评测规格**（与 `problems.py` 的展示元数据解耦）。

`problems.py` 只管题面怎么展示；这里管怎么评。两者用同一个 `id` 关联。
与 `standings.py` 一样，属于「运行期逻辑」而非「展示数据」。

## 计分模型（逐点独立）

每题 **10 个数据点**，每个数据点独立判定与计分：

    单点得分 = 分值 × min(1, 基准指令数 ÷ 本队指令数)   （该点做对才计，做错该点得 0）

总分 = 10 个数据点之和。三题分值分配（合计 100）：

    add        10 × 3 = 30
    matmul-4x4 10 × 3 = 30
    reducesum  10 × 4 = 40

某一点做错**只丢该点的分**，不影响其他点——所以评测必须跑完全部数据点，
不能短路（见 evaluator `_evaluate_riscv_asm`）。

## 内存布局（一次连续 dump，与 ScratchV 的 wrapper 同构）

    guard_lo (256) | workspace (W) | guard_mid (256) | output (O) | guard_hi (256)

任一 guard 区非零 ⇒ 越界写 ⇒ 该数据点判失败。
`sp` 指向 **workspace 顶端**（栈向下生长落在 workspace 内）——这是相对 ScratchV
原 wrapper 的一处有意改进：ScratchV 的 `la sp, workspace` 会让栈向下写进 guard_lo，
等于禁止选手使用栈；钉住顶端后选手可以正常用栈，且溢出仍被 guard_lo 捕获。
"""

DATA_DIR_BASELINE = 'data/baseline.json'
GUARD_BYTES = 256
WORKSPACE_BYTES = 1024
CASE_COUNT = 10          # 每题数据点个数
VECTOR_LEN = 64          # add / reducesum 的向量长度

# 每题分值分配：points_per_case × CASE_COUNT = full_score
EVAL_SPECS = {
    'add': {
        'kind': 'riscv-asm',
        'kernel': 'add',
        'entry_symbol': 'cnn_entry',
        'file_suffix': '.s',
        'vector_len': VECTOR_LEN,
        'input_elements': 2 * VECTOR_LEN,   # A(64) 接 B(64)
        'output_elements': VECTOR_LEN,      # C[i] = A[i] + B[i]
        'output_shape': [VECTOR_LEN],
        'workspace_bytes': WORKSPACE_BYTES,
        'guard_bytes': GUARD_BYTES,
        'tolerance': 0,
        'case_count': CASE_COUNT,
        'points_per_case': 3,               # 10 × 3 = 30
        'full_score': 3 * CASE_COUNT,
        'reference': 'reference/add.c',
        'baseline_file': DATA_DIR_BASELINE,
        'title': '逐元素相加',
    },
    'matmul-4x4': {
        'kind': 'riscv-asm',
        'kernel': 'matmul-4x4',
        'entry_symbol': 'cnn_entry',
        'file_suffix': '.s',
        'matrix_dim': 4,
        'input_elements': 32,               # A(4x4) 接 B(4x4)，行主序
        'output_elements': 16,              # C(4x4)，行主序
        'output_shape': [4, 4],
        'workspace_bytes': WORKSPACE_BYTES,
        'guard_bytes': GUARD_BYTES,
        'tolerance': 0,
        'case_count': CASE_COUNT,
        'points_per_case': 3,               # 10 × 3 = 30
        'full_score': 3 * CASE_COUNT,
        'reference': 'reference/matmul.c',
        'baseline_file': DATA_DIR_BASELINE,
        'title': '4x4 定点矩阵乘',
    },
    'reducesum': {
        'kind': 'riscv-asm',
        'kernel': 'reducesum',
        'entry_symbol': 'cnn_entry',
        'file_suffix': '.s',
        'vector_len': VECTOR_LEN,
        'input_elements': VECTOR_LEN,       # 64 个待归约元素
        'output_elements': 1,               # 全归约为 1 个值
        'output_shape': [1],
        'workspace_bytes': WORKSPACE_BYTES,
        'guard_bytes': GUARD_BYTES,
        'tolerance': 0,
        'case_count': CASE_COUNT,
        'points_per_case': 4,               # 10 × 4 = 40
        'full_score': 4 * CASE_COUNT,
        'reference': 'reference/reducesum.c',
        'baseline_file': DATA_DIR_BASELINE,
        'title': '归约求和',
    },
}


def get_eval_spec(problem_id):
    """取评测规格；非 RISC-V 题（没接评测）返回 None。"""
    return EVAL_SPECS.get(problem_id)


def is_riscv_problem(problem_id):
    return problem_id in EVAL_SPECS


def riscv_problem_ids():
    return list(EVAL_SPECS)


def total_full_score():
    return sum(s['full_score'] for s in EVAL_SPECS.values())


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
