# -*- coding: utf-8 -*-
"""RISC-V 赛题的可信参考实现（oracle）。

**判据的唯一来源。** 评测的期望输出由本模块纯 Python 算出，独立于选手进程——
选手进程只能通过 write(1) 影响 *dump 出来的字节*，影响不了这里的期望值。

数值口径与 ScratchV 的定点约定一致（`third_party/ScratchV/tests/test_standalone_execution.py`）：
Q16.16 定点，`(a * b) >> 16` 用算术右移逐项相乘再求和。
本模块按「一条 mul + 一条 srai + 一条 add」的 RV32 语义**逐步取模 2^32**，
与真实指令序列逐位对齐（不是先算 Python 大整数再截断）。
"""

INT32_MASK = 0xFFFFFFFF
INT32_SIGN = 0x80000000


def s32(x):
    """按 RV32 语义把值截成有符号 32 位（等价于寄存器里的结果）。"""
    x &= INT32_MASK
    return x - 0x100000000 if x & INT32_SIGN else x


def make_input(seed, spec):
    """按 seed 生成输入张量（int32 / Q16.16）。

    沿用 ScratchV 的取值分布：落在 [-32768, 32767]，即 Q16.16 的 [-0.5, 0.5)，
    保证单次乘法不溢出 int32（`mul` 低 32 位即精确），选手无需用 `mulh`。
    """
    n = spec['input_elements']
    if seed == 0:
        return [0] * n
    return [((i * 37 + seed * 17) % 65536) - 32768 for i in range(n)]


def reference(values, spec):
    """参考输出。目前只实现 matmul-4x4；其余算子按 spec['kernel'] 扩展。"""
    kernel = spec.get('kernel', 'matmul-4x4')
    if kernel != 'matmul-4x4':
        raise ValueError(f'未知算子的参考实现: {kernel}')
    return _matmul_4x4(values, spec)


def _matmul_4x4(values, spec):
    """C = A x B，4x4，行主序。

    C[i][j] = sum_k s32( s32(A[i][k] * B[k][j]) >> 16 )
    外层和每步都取模 2^32，与 RV32 寄存器语义一致。
    """
    n = spec['input_elements']
    m = spec['matrix_dim']
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


def check_output(got, expected, spec):
    """比对选手输出与参考输出。

    返回 (ok, message)。message 只含**十进制数值差**，绝不回显原始字节——
    否则选手可用 `.incbin` 读宿主文件、再借失败信息把内容带出来（见 docs/08）。
    """
    if len(got) != len(expected):
        return False, f'输出长度不符：期望 {len(expected)} 个数值，实际 {len(got)} 个'

    tol = spec.get('tolerance', 0)
    for idx, (g, e) in enumerate(zip(got, expected)):
        if abs(g - e) > tol:
            return False, (
                f'第 {idx} 个输出数值不符（行 {idx // spec["matrix_dim"]}，'
                f'列 {idx % spec["matrix_dim"]}）：期望 {e}，实际 {g}'
            )
    return True, ''
