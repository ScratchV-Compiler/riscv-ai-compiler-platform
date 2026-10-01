# -*- coding: utf-8 -*-
"""RISC-V 赛题的可信参考实现（oracle）。

**判据的唯一来源。** 评测的期望输出由本模块纯 Python 算出，独立于选手进程——
选手进程只能通过 write(1) 影响 *dump 出来的字节*，影响不了这里的期望值。

数值口径与 ScratchV 的定点约定一致（`third_party/ScratchV/tests/test_standalone_execution.py`）：
Q16.16 定点。各算子按「RV32 指令逐步取模 2^32」实现，与真实指令序列逐位对齐
（不是先算 Python 大整数再截断）。

当前支持的算子（由 spec['kernel'] 选择）：
- `matmul-4x4`：C = A × B，逐项 (a*b)>>16 后累加
- `add`：两个等长向量逐元素相加
- `reducesum`：全归约求和（N 个元素 → 1 个）
"""

INT32_MASK = 0xFFFFFFFF
INT32_SIGN = 0x80000000


def s32(x):
    """按 RV32 语义把值截成有符号 32 位（等价于寄存器里的结果）。"""
    x &= INT32_MASK
    return x - 0x100000000 if x & INT32_SIGN else x


def make_input(seed, spec):
    """按 seed 生成输入张量（int32 / Q16.16）。

    沿用 ScratchV 的取值分布：落在 [-32768, 32767]，即 Q16.16 的 [-0.5, 0.5)。
    各算子的累加器规模都经过核算，不会溢出 int32（见 build 说明）：
    - add：单次相加 ≤ 65534
    - reducesum：64 项求和 ≤ 2^21
    - matmul：每项先 >>16 再累加，4 项 ≤ 2^17
    """
    n = spec['input_elements']
    if seed == 0:
        return [0] * n
    return [((i * 37 + seed * 17) % 65536) - 32768 for i in range(n)]


def reference(values, spec):
    """参考输出。按 spec['kernel'] 分派。"""
    kernel = spec.get('kernel')
    fn = KERNELS.get(kernel)
    if fn is None:
        raise ValueError(f'未知算子的参考实现: {kernel}')
    return fn(values, spec)


def _matmul_4x4(values, spec):
    """C = A x B，4x4，行主序。

    C[i][j] = sum_k s32( s32(A[i][k] * B[k][j]) >> 16 )
    外层和每步都取模 2^32，与 RV32 寄存器语义一致。
    """
    m = spec['matrix_dim']
    n = spec['input_elements']
    if len(values) != n:
        raise ValueError(f'输入长度应为 {n}，实际 {len(values)}')

    a = values[:m * m]
    b = values[m * m:m * m * 2]

    out = []
    for i in range(m):
        for j in range(m):
            acc = 0
            for k in range(m):
                prod = s32(a[i * m + k] * b[k * m + j])   # mul：低 32 位
                acc = s32(acc + (prod >> 16))             # srai 16，再 add
            out.append(acc)
    return out


def _add(values, spec):
    """逐元素相加：C[i] = s32(A[i] + B[i])。

    输入 = 两个等长向量首尾相接（前 N 个是 A，后 N 个是 B）。
    """
    n = spec['vector_len']
    if len(values) != 2 * n:
        raise ValueError(f'输入长度应为 {2 * n}，实际 {len(values)}')
    a = values[:n]
    b = values[n:2 * n]
    return [s32(x + y) for x, y in zip(a, b)]


def _reducesum(values, spec):
    """全归约：out = s32(sum(values))，N 个元素 → 1 个输出。"""
    n = spec['vector_len']
    if len(values) != n:
        raise ValueError(f'输入长度应为 {n}，实际 {len(values)}')
    acc = 0
    for v in values:
        acc = s32(acc + v)      # 逐步 add，与 RV32 语义一致
    return [acc]


KERNELS = {
    'matmul-4x4': _matmul_4x4,
    'add': _add,
    'reducesum': _reducesum,
}


def check_output(got, expected, spec):
    """比对选手输出与参考输出。

    返回 (ok, message)。message 只含**十进制数值差**，绝不回显原始字节——
    否则选手可用 `.incbin` 读宿主文件、再借失败信息把内容带出来（见 docs/08）。
    """
    if len(got) != len(expected):
        return False, f'输出长度不符：期望 {len(expected)} 个数值，实际 {len(got)} 个'

    tol = spec.get('tolerance', 0)
    shape = spec.get('output_shape')
    for idx, (g, e) in enumerate(zip(got, expected)):
        if abs(g - e) > tol:
            where = _describe_index(idx, shape)
            return False, f'第 {idx} 个输出数值不符{where}：期望 {e}，实际 {g}'
    return True, ''


def _describe_index(idx, shape):
    """把展平下标还原成可读的多维坐标，方便选手定位。"""
    if not shape or len(shape) < 2:
        return ''
    row = idx // shape[1]
    col = idx % shape[1]
    return f'（行 {row}，列 {col}）'
