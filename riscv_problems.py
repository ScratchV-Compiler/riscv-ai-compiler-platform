# -*- coding: utf-8 -*-
"""RISC-V 赛题的**评测规格**（与 `problems.py` 的展示元数据解耦）。

`problems.py` 只管题面怎么展示；这里管怎么评。两者用同一个 `id` 关联。

## 数据点：按规模分级

每题 **10 个数据点**，每个数据点是一个**不同的规模 N**（对齐官方
`stage2数据点.md` 的取法：规模递增，每个点考察不同瓶颈）。

- `add` / `reducesum`：工作量随 N **线性**增长 → N 线性铺开（64 → 4096）
- `matmul`：工作量随 N **立方**增长 → N 必须缓着涨（4 → 64），否则最后几个点
  会把评测时间吃光；4→64 也刚好跨过 L1（三个 16KB 矩阵 ≈ 48KB > 32KB）
- `fwht` / `winograd` / `spmm`（内测比赛2）：源方案规模远超 qemu 可仿真范围，
  按同样的思路**等比缩小**，保留各点的形状特征（见各自的 `note`）

**ABI**：`a2 = N`。简单题里 matmul 为矩阵阶数、add/reducesum/fwht 为向量长度；
`winograd`/`spmm` 的形状不止一个标量，输入张量**自带 int32 头部**描述形状
（见 `riscv_oracle` 模块 docstring），`a2` 只作规模标量。选手必须写**尺寸无关**的代码。

## 数值类型（`dtype` / `march`）

默认 `int32`（Q16.16 定点，`-march=rv32im`），内测比赛1 三题用它；内测比赛2 的
`fwht`/`winograd`/`spmm` 均为 `float32`（`-march=rv32imf`）。浮点题的期望值比对用
`rtol`/`atol` 容差，而非精确相等。整数题行为与引入 dtype 之前**逐字节等价**。

## 多参数题的形状表（`params_by_size`）

`winograd`/`spmm` 的规模标量 `n` 与完整形状的对应关系存在
`spec['params_by_size'][n]`。`n` 取数据点唯一的一个整数（winograd 为特征图元素数
`batch·H·W·Cin`，spmm 为非零元个数 `nnz`），它同时是 baseline/榜单的 size 键。
该表跨场次共享（`get_eval_spec` 只做浅拷贝）——**只读，不得原地改写**。

## 计分：逐点独立

    单点得分 = 分值 × min(1, 该点 baseline 指令数 ÷ 该点本队指令数)   （做对才计）

**baseline 是逐数据点各自的**（N 不同 → 指令数不同），不能用一个数。
做错只丢该点的分；唯一整题级失败是编译不通过。

## 内存布局（一次连续 dump）

    guard_lo (256) | workspace (W) | guard_mid (256) | output (O) | guard_hi (256)

W 与 O 都随 N 缩放。任一 guard 区非零 ⇒ 越界写 ⇒ 该数据点判失败。
`sp` 指向 workspace 顶端（栈向下生长落在 workspace 内）。自描述题的工作区
按输入元素数给足（避免选手正常用栈被 guard_mid 误判成越界）。
"""

import riscv_oracle as _oracle

DATA_DIR_BASELINE = 'data/baseline.json'
GUARD_BYTES = 256
CASE_COUNT = 10          # 每题数据点个数

# 每个数据点的工作区上限：给足 scratch，但别让 dump 太大。
# 自描述题（winograd/spmm）的 scratch/栈需求随**输入张量**而非规模标量增长，
# 按输入元素数给足，避免选手正常用栈被 guard_mid 误判成越界写。
def _workspace_for(spec, n):
    if spec.get('kernel') in ('winograd', 'spmm'):
        in_elems, _ = case_elements(spec, n)
        return max(8192, 8 * in_elems)
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
    'matmul': {
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
        'title': '定点矩阵乘',
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


# ---------------------------------------------------------------------------
# 内测比赛2 三题（源：《2026 华东师大 AI 编译竞赛》三道赛题）
# 源规模远超 qemu 可仿真范围，这里等比缩小、保留各点形状特征。
# ---------------------------------------------------------------------------

# 赛题一：哈达玛变换。规模即向量长度 N=2^k（源数据点 8 → 4096）。
_FWHT_SIZES = [8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]

# 赛题二：卷积 (batch, H, W, Cin, Cout, K)。规模标量 = batch*H*W*Cin（互异）。
_CONV_CASES = [
    (1, 8, 8, 3, 8, 3),      # 标准小 3×3
    (1, 8, 8, 4, 16, 3),     # 增输出通道
    (1, 8, 8, 5, 8, 5),      # 大核 5×5
    (2, 8, 8, 3, 8, 3),      # batch=2
    (1, 6, 6, 16, 16, 3),    # 中通道
    (1, 5, 5, 24, 24, 3),    # 高通道、小图
    (1, 8, 8, 10, 8, 5),     # 大核 + 中通道
    (1, 5, 5, 32, 16, 3),    # 高输入通道
    (1, 6, 6, 24, 16, 3),    # 类 ResNet 层
    (2, 6, 6, 16, 12, 3),    # 大 batch
]

# 赛题三：稀疏矩阵乘 (M, K, N, 稀疏度, 结构键)。规模标量 = nnz（互异）。
_SPMM_CASES = [
    (128, 128, 1, 0.90, 1),
    (256, 256, 1, 0.95, 2),
    (128, 128, 4, 0.85, 3),
    (512, 256, 1, 0.98, 4),
    (1000, 64, 4, 0.99, 5),
    (120, 300, 1, 0.90, 6),
    (100, 100, 8, 0.80, 7),
    (96, 512, 1, 0.95, 8),
    (64, 64, 8, 0.70, 9),
    (64, 64, 16, 0.50, 10),
]


def _build_conv_params():
    return {b * H * W * Cin: {'batch': b, 'H': H, 'W': W,
                              'Cin': Cin, 'Cout': Cout, 'K': K}
            for (b, H, W, Cin, Cout, K) in _CONV_CASES}


def _build_spmm_params():
    out = {}
    for (M, K, N, sp, key) in _SPMM_CASES:
        nnz = _oracle.spmm_nnz(M, K, sp, key)
        out[nnz] = {'M': M, 'K': K, 'N': N, 'sparsity': sp, 'nnz': nnz, 'key': key}
    return out


_CONV_PARAMS = _build_conv_params()
_SPMM_PARAMS = _build_spmm_params()

EVAL_SPECS['fwht'] = {
    'kind': 'riscv-asm',
    'kernel': 'fwht',
    'entry_symbol': 'cnn_entry',
    'file_suffix': '.s',
    'dtype': 'float32', 'march': 'rv32imf',
    'rtol': 1e-4, 'atol': 1e-3,         # atol 放宽：全抵消时相对误差失去意义
    'param_meaning': '向量长度 N（2 的幂）',
    'data_point_sizes': _FWHT_SIZES,
    'points_per_case': 3,               # 10 × 3 = 30
    'full_score': 3 * CASE_COUNT,
    'reference': 'reference/fwht.c',
    'baseline_file': DATA_DIR_BASELINE,
    'title': '哈达玛变换（蝶形加速）',
    'note': '输入 N 个 float32，输出 N 个；正向 FWHT out = H_N·x，纯加减',
}

EVAL_SPECS['winograd'] = {
    'kind': 'riscv-asm',
    'kernel': 'winograd',
    'entry_symbol': 'cnn_entry',
    'file_suffix': '.s',
    'dtype': 'float32',                 # 源方案要求 FP32（平台为此新增浮点支持）
    'march': 'rv32imf',
    'rtol': 1e-4, 'atol': 1e-4,         # 浮点比对容差（源方案：相对 1e-4）
    'param_meaning': '特征图元素数 batch·H·W·Cin（形状见输入头）',
    'data_point_sizes': sorted(_CONV_PARAMS),
    'points_per_case': 3,               # 10 × 3 = 30
    'full_score': 3 * CASE_COUNT,
    'reference': 'reference/winograd.c',
    'baseline_file': DATA_DIR_BASELINE,
    'title': 'Winograd 卷积加速',
    'note': '输入头 [batch,H,W,Cin,Cout,K] ++ 特征图 ++ 权重；SAME padding、'
            'stride 1、K∈{3,5}；输出 [batch,Cout,H,W]；baseline=直接卷积',
    'params_by_size': _CONV_PARAMS,
}

EVAL_SPECS['spmm'] = {
    'kind': 'riscv-asm',
    'kernel': 'spmm',
    'entry_symbol': 'cnn_entry',
    'file_suffix': '.s',
    'dtype': 'float32', 'march': 'rv32imf',
    'rtol': 1e-4, 'atol': 1e-4,
    'param_meaning': '非零元个数 nnz（形状见输入头）',
    'data_point_sizes': sorted(_SPMM_PARAMS),
    'points_per_case': 4,               # 10 × 4 = 40
    'full_score': 4 * CASE_COUNT,
    'reference': 'reference/spmm.c',
    'baseline_file': DATA_DIR_BASELINE,
    'title': '稀疏矩阵乘法（CSR）',
    'note': '输入头 [M,K,N,nnz]（int32）++ row_ptr[M+1] ++ col_idx[nnz]（int32）'
            '++ values[nnz] ++ B[K*N]（float32）；C[i][j] = Σ values[p]·B[col[p]*N+j]',
    'params_by_size': _SPMM_PARAMS,
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


def _params_for(spec, n):
    """自描述题（winograd/spmm）的完整形状配置。"""
    return (spec.get('params_by_size') or {}).get(n)


def case_elements(spec, n):
    """给定规模 N，算该数据点的 (输入元素数, 输出元素数)。"""
    kernel = spec['kernel']
    if kernel == 'matmul':
        return 2 * n * n, n * n
    if kernel == 'add':
        return 2 * n, n
    if kernel == 'reducesum':
        return n, 1
    if kernel == 'fwht':
        return n, n
    p = _params_for(spec, n)
    if p is None:
        raise ValueError(f'规模 {n} 缺少形状配置（params_by_size）')
    if kernel == 'winograd':
        in_elems = 6 + p['batch'] * p['H'] * p['W'] * p['Cin'] \
            + p['Cout'] * p['Cin'] * p['K'] * p['K']
        return in_elems, p['batch'] * p['Cout'] * p['H'] * p['W']
    if kernel == 'spmm':
        return 4 + (p['M'] + 1) + 2 * p['nnz'] + p['K'] * p['N'], p['M'] * p['N']
    raise ValueError(f'未知算子: {kernel}')


def case_label(spec, idx):
    """给该数据点起一个人话标签，用于题面展示。"""
    n = case_size(spec, idx)
    kernel = spec['kernel']
    if kernel == 'matmul':
        return f'{n}×{n}'
    if kernel == 'winograd':
        p = _params_for(spec, n)
        return f'{p["batch"]}·{p["Cin"]}·{p["H"]}·{p["W"]}→{p["Cout"]}'
    if kernel == 'spmm':
        p = _params_for(spec, n)
        return f'{p["M"]}×{p["K"]}×{p["N"]}'
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
    if kernel == 'fwht':
        if n <= 32:
            return '极小规模，验证蝶形控制流与边界'
        if n <= 256:
            return '小规模，基础蝶形 + 数据置换'
        if n <= 1024:
            return '中等规模，Cache 开始敏感'
        return '大规模，数据置换与分块优化收益显现'
    if kernel == 'winograd':
        p = _params_for(spec, n)
        k = p['K']
        if p['Cout'] * p['Cin'] * k * k <= 108:
            return '小规模，标准直接卷积'
        if k == 5:
            return '大核 5×5，Winograd F(4,3)/F(2,3) 选择'
        if p['H'] <= 6:
            return '特征图小、通道高，计算密度高'
        if p['batch'] > 1:
            return '大 batch，数据复用与并行'
        return '类 ResNet 层，变换开销开始显现'
    if kernel == 'spmm':
        p = _params_for(spec, n)
        if p['M'] != p['K']:
            return '非方阵，长宽比悬殊'
        if p['N'] == 1:
            return f'SpMV，稀疏度 {int(p["sparsity"] * 100)}%'
        return f'SpMM（N={p["N"]}），稀疏度 {int(p["sparsity"] * 100)}%'
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
    ws = _workspace_for(spec, n)
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
