# -*- coding: utf-8 -*-
"""RISC-V 赛题的可信参考实现（oracle）。

**判据的唯一来源。** 期望输出由本模块纯 Python 算出，独立于选手进程——
选手进程只能通过 write(1) 影响 *dump 出来的字节*，影响不了这里的期望值。

数值口径：Q16.16 定点，各算子按「RV32 指令逐步取模 2^32」实现，与真实指令
序列逐位对齐（不是先算 Python 大整数再截断）。

**尺寸无关**：所有算子都从 spec + 规模 N 取参数，与 ABI 新增的 `a2 = N` 一致。
"""

import random

INT32_MASK = 0xFFFFFFFF
INT32_SIGN = 0x80000000

# 输入取值域：Q16.16 的 [-0.5, 0.5)
VALUE_MIN = -32768
VALUE_MAX = 32767


def s32(x):
    """按 RV32 语义把值截成有符号 32 位（等价于寄存器里的结果）。"""
    x &= INT32_MASK
    return x - 0x100000000 if x & INT32_SIGN else x


def make_input(seed, spec, n):
    """按 seed 与规模 N 生成输入张量（int32 / Q16.16）。

    **真正铺满声明的值域** [-32768, 32767]。早先用 `(i*37 + seed*17) % 65536`
    只铺开了 2%~7% 的范围，等于把"边界值处理"这一整类缺陷放过去了。
    这里改用带种子的 PRNG，保证可复现且覆盖完整值域。
    """
    elems, _ = _elements(spec, n)
    if seed == 0:
        return [0] * elems
    rng = random.Random(seed)
    return [rng.randint(VALUE_MIN, VALUE_MAX) for _ in range(elems)]


def _elements(spec, n):
    kernel = spec['kernel']
    if kernel == 'matmul':
        return 2 * n * n, n * n
    if kernel == 'add':
        return 2 * n, n
    if kernel == 'reducesum':
        return n, 1
    raise ValueError(f'未知算子: {kernel}')


def reference(values, spec, n):
    """参考输出。按 spec['kernel'] 分派，规模为 N。"""
    fn = KERNELS.get(spec.get('kernel'))
    if fn is None:
        raise ValueError(f'未知算子的参考实现: {spec.get("kernel")}')
    return fn(values, n)


def _matmul(values, n):
    """C = A x B，N×N，行主序。

    C[i][j] = Σₖ s32( s32(A[i][k] * B[k][j]) >> 16 )
    """
    exp_in, _ = _elements({'kernel': 'matmul'}, n)
    if len(values) != exp_in:
        raise ValueError(f'输入长度应为 {exp_in}，实际 {len(values)}')
    a = values[:n * n]
    b = values[n * n:2 * n * n]

    out = []
    for i in range(n):
        for j in range(n):
            acc = 0
            for k in range(n):
                prod = s32(a[i * n + k] * b[k * n + j])   # mul：低 32 位
                acc = s32(acc + (prod >> 16))             # srai 16，再 add
            out.append(acc)
    return out


def _add(values, n):
    """逐元素相加：C[i] = s32(A[i] + B[i])。输入 = A(N) 接 B(N)。"""
    if len(values) != 2 * n:
        raise ValueError(f'输入长度应为 {2 * n}，实际 {len(values)}')
    a = values[:n]
    b = values[n:2 * n]
    return [s32(x + y) for x, y in zip(a, b)]


def _reducesum(values, n):
    """全归约：out = s32(sum(values))，N 个元素 → 1 个输出。"""
    if len(values) != n:
        raise ValueError(f'输入长度应为 {n}，实际 {len(values)}')
    acc = 0
    for v in values:
        acc = s32(acc + v)      # 逐步 add，与 RV32 语义一致
    return [acc]


KERNELS = {
    'matmul': _matmul,
    'add': _add,
    'reducesum': _reducesum,
}


def check_output(got, expected, spec, n=None):
    """比对选手输出与参考输出。

    返回 (ok, message)。message 只含**十进制数值差**，绝不回显原始字节——
    否则选手可用 `.incbin` 读宿主文件、再借失败信息把内容带出来（见 docs/08）。
    """
    if len(got) != len(expected):
        return False, f'输出长度不符：期望 {len(expected)} 个数值，实际 {len(got)} 个'

    tol = spec.get('tolerance', 0)
    for idx, (g, e) in enumerate(zip(got, expected)):
        if abs(g - e) > tol:
            where = _describe_index(idx, spec, n)
            return False, f'第 {idx} 个输出数值不符{where}：期望 {e}，实际 {g}'
    return True, ''


def _describe_index(idx, spec, n):
    if spec.get('kernel') == 'matmul' and n:
        return f'（行 {idx // n}，列 {idx % n}）'
    return ''
