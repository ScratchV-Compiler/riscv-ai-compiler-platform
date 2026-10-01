# -*- coding: utf-8 -*-
"""RISC-V 赛题的**评测规格**（与 `problems.py` 的展示元数据解耦）。

`problems.py` 只管题面怎么展示；这里管怎么评。两者用同一个 `id` 关联。

## 数据点：按规模分级

每题 **10 个数据点**，每个数据点是一个**不同的规模 N**（对齐官方
`stage2数据点.md` 的取法：N 递增，每个点考察不同瓶颈）。

- `add` / `reducesum`：工作量随 N **线性**增长 → N 线性铺开（64 → 4096）
- `matmul`：工作量随 N **立方**增长 → N 必须缓着涨（4 → 64），否则最后几个点
  会把评测时间吃光；4→64 也刚好跨过 L1（三个 16KB 矩阵 ≈ 48KB > 32KB）

**ABI 相应加了参数**：`a2 = N`（matmul 为矩阵阶数，add/reducesum 为向量长度）。
选手必须写**尺寸无关**的代码——这正是"可扩展性"要考的东西。

## 计分：逐点独立

    单点得分 = 分值 × min(1, 该点 baseline 指令数 ÷ 该点本队指令数)   （做对才计）

**baseline 是逐数据点各自的**（N 不同 → 指令数不同），不能用一个数。
做错只丢该点的分；唯一整题级失败是编译不通过。

## 内存布局（一次连续 dump）

    guard_lo (256) | workspace (W) | guard_mid (256) | output (O) | guard_hi (256)

W 与 O 都随 N 缩放。任一 guard 区非零 ⇒ 越界写 ⇒ 该数据点判失败。
`sp` 指向 workspace 顶端（栈向下生长落在 workspace 内）。
"""

DATA_DIR_BASELINE = 'data/baseline.json'
GUARD_BYTES = 256
CASE_COUNT = 10          # 每题数据点个数

# 每个数据点的工作区上限：给足 scratch，但别让 dump 太大
def _workspace_for(n):
    return max(1024, 8 * n)


# 数据点规模梯度
_ADD_SIZES = [64, 128, 256, 512, 1024, 1536, 2048, 2560, 3072, 4096]
_REDUCESUM_SIZES = list(_ADD_SIZES)
# matmul 工作量为 N^3，必须缓涨
_MATMUL_SIZES = [4, 8, 12, 16, 20, 24, 32, 40, 48, 64]


EVAL_SPECS = {
    'add': {
        'kind': 'riscv-asm',
        'kernel': 'add',
        'entry_symbol': 'cnn_entry',
        'file_suffix': '.s',
        'param_meaning': '向量长度 N',
        'data_point_sizes': _ADD_SIZES,
        'points_per_case': 3,               # 10 × 3 = 30
        'full_score': 3 * CASE_COUNT,
        'reference': 'reference/add.c',
        'baseline_file': DATA_DIR_BASELINE,
        'title': '逐元素相加',
        'note': '输入 2N 个 int32（前 N 个 A，后 N 个 B），输出 N 个；C[i] = A[i] + B[i]',
    },
    'matmul-4x4': {
        'kind': 'riscv-asm',
        'kernel': 'matmul',
        'entry_symbol': 'cnn_entry',
        'file_suffix': '.s',
        'param_meaning': '矩阵阶数 N',
        'data_point_sizes': _MATMUL_SIZES,
        'points_per_case': 3,               # 10 × 3 = 30
        'full_score': 3 * CASE_COUNT,
        'reference': 'reference/matmul.c',
        'baseline_file': DATA_DIR_BASELINE,
        'title': 'N×N 定点矩阵乘',
        'note': '输入 2N² 个 int32（A 与 B，均行主序），输出 N² 个；'
                'C[i][j] = Σₖ ((A[i][k]×B[k][j]) >> 16)',
    },
    'reducesum': {
        'kind': 'riscv-asm',
        'kernel': 'reducesum',
        'entry_symbol': 'cnn_entry',
        'file_suffix': '.s',
        'param_meaning': '向量长度 N',
        'data_point_sizes': _REDUCESUM_SIZES,
        'points_per_case': 4,               # 10 × 4 = 40
        'full_score': 4 * CASE_COUNT,
        'reference': 'reference/reducesum.c',
        'baseline_file': DATA_DIR_BASELINE,
        'title': '归约求和',
        'note': '输入 N 个 int32，输出 1 个；out[0] = Σ x[i]',
    },
}


# 数据点个数由规模梯度长度派生，避免两处各写一份
for _spec in EVAL_SPECS.values():
    _spec['case_count'] = len(_spec['data_point_sizes'])


def get_eval_spec(problem_id):
    """取评测规格；非 RISC-V 题（没接评测）返回 None。"""
    return EVAL_SPECS.get(problem_id)


def is_riscv_problem(problem_id):
    return problem_id in EVAL_SPECS


def riscv_problem_ids():
    return list(EVAL_SPECS)


def total_full_score():
    return sum(s['full_score'] for s in EVAL_SPECS.values())


def case_size(spec, idx):
    """第 idx 个数据点的规模 N。"""
    return spec['data_point_sizes'][idx]


def case_elements(spec, n):
    """给定规模 N，算该数据点的 (输入元素数, 输出元素数)。"""
    kernel = spec['kernel']
    if kernel == 'matmul':
        return 2 * n * n, n * n
    if kernel == 'add':
        return 2 * n, n
    if kernel == 'reducesum':
        return n, 1
    raise ValueError(f'未知算子: {kernel}')


def case_label(spec, idx):
    """给该数据点起一个人话标签，用于题面展示。"""
    n = case_size(spec, idx)
    kernel = spec['kernel']
    if kernel == 'matmul':
        return f'{n}×{n}'
    return f'N={n}'


def case_purpose(spec, idx):
    """该数据点考察什么——按规模位置给说明，用于题面表格。"""
    n = case_size(spec, idx)
    kernel = spec['kernel']
    if kernel == 'matmul':
        ws = 3 * n * n * 4
        if n <= 8:
            return '极小规模，验证基本循环与下标寻址'
        if n <= 16:
            return '小规模，寄存器复用开始有意义'
        if n <= 32:
            return f'中等规模（三矩阵约 {ws // 1024}KB，逼近 L1）'
        return f'大规模（三矩阵约 {ws // 1024}KB，超出 L1，访存成为瓶颈）'
    # add / reducesum：线性
    if n <= 256:
        return '小规模，验证基本循环与边界'
    if n <= 1024:
        return '中等规模，循环开销开始可摊薄'
    if n <= 2048:
        return '大规模，展开与访存模式开始重要'
    return '超大规模，贴近缓存与带宽瓶颈'


def layout(spec, n):
    """算出一个数据点（规模 N）的内存布局，返回各区在 dump 里的 (offset, size)。"""
    guard = GUARD_BYTES
    ws = _workspace_for(n)
    _, out_elems = case_elements(spec, n)
    out_bytes = out_elems * 4

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
        'stack_top': guard + ws,
    }
