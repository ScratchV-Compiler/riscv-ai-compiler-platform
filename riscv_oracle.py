# -*- coding: utf-8 -*-
"""RISC-V 赛题的可信参考实现（oracle）。

**判据的唯一来源。** 期望输出由本模块纯 Python 算出，独立于选手进程——
选手进程只能通过 write(1) 影响 *dump 出来的字节*，影响不了这里的期望值。

数值口径分两类（按 spec['dtype'] 选）：

- **int32 Q16.16**（内测比赛1 的 `add`/`matmul`/`reducesum`）：各算子按
  「RV32 指令逐步取模 2^32」实现，与真实指令序列逐位对齐（不是先算 Python 大整数
  再截断）。
- **float32**（内测比赛2 的 `fwht`/`winograd`/`spmm`）：输入经 `struct` 往返取整到
  单精度；参考实现**逐次运算取整到 float32**（乘、加各取整一次），与 rv32imf 参考解/
  选手代码的 `fmul.s`+`fadd.s` 语义一致；比对用相对/绝对容差（rtol/atol）。

**尺寸无关**：所有算子都从 spec + 规模 N 取参数，与 ABI 的 `a2 = N` 一致。

## 自描述输入（多参数题）

`winograd`/`spmm` 的形状不止一个标量，输入张量带一个 **int32 头部 / 结构**，
其后才是 float32 数值：

    winograd: [batch, H, W, Cin, Cout, K](int32) ++ 特征图(float) ++ 权重(float)
    spmm:     [M, K, N, nnz] ++ row_ptr[M+1] ++ col_idx[nnz](均 int32)
              ++ values[nnz] ++ B[K*N](均 float32)

规模标量 `n` 与完整形状的对应关系存在 spec['params_by_size'][n]。
"""

import random
import struct

INT32_MASK = 0xFFFFFFFF
INT32_SIGN = 0x80000000

# 输入取值域：Q16.16 的 [-0.5, 0.5)
VALUE_MIN = -32768
VALUE_MAX = 32767

# float32 题（winograd）的输入范围
FLOAT_MIN = -1.0
FLOAT_MAX = 1.0


def s32(x):
    """按 RV32 语义把值截成有符号 32 位（等价于寄存器里的结果）。"""
    x &= INT32_MASK
    return x - 0x100000000 if x & INT32_SIGN else x


def f32(x):
    """把值取整到 IEEE-754 单精度（等价于 `fmul.s`/`fadd.s` 的结果）。"""
    return struct.unpack('<f', struct.pack('<f', x))[0]


def _params(spec, n):
    """取规模标量 n 对应的完整形状配置（仅自描述题需要）。"""
    table = spec.get('params_by_size') or {}
    return table.get(n)


def make_input(seed, spec, n):
    """按 seed 与规模 N 生成输入张量。

    - 整数题：**真正铺满声明的值域** [-32768, 32767]，用带种子的 PRNG，
      保证可复现且覆盖完整值域（早先的线性取模只铺开 2%~7%，放过了边界缺陷）。
    - 浮点题：`[-1, 1]` 均匀取值，且**经 struct 往返取整到 float32**——保证
      oracle 与 guest（wrapper 发射的位型）看到的是同一批数。
    - 自描述题：头部（int32）与结构（row_ptr/col_idx）固定，只有数值随机。

    seed == 0 时（仅简单整数题）返回全 0，供参考——评测不用。
    """
    rng = random.Random(seed)
    kernel = spec.get('kernel')
    if kernel == 'winograd':
        return _make_conv_input(rng, spec, n)
    if kernel == 'spmm':
        return _make_spmm_input(rng, spec, n)

    elems, _ = _elements(spec, n)
    if seed == 0:
        return [0.0] * elems if spec.get('dtype') == 'float32' else [0] * elems
    if spec.get('dtype') == 'float32':
        return [f32(rng.uniform(FLOAT_MIN, FLOAT_MAX)) for _ in range(elems)]
    return [rng.randint(VALUE_MIN, VALUE_MAX) for _ in range(elems)]


def _elements(spec, n):
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
    # 自描述题：形状从 params_by_size 取
    p = _params(spec, n)
    if p is None:
        raise ValueError(f'缺少规模 {n} 的形状配置（params_by_size）')
    if kernel == 'winograd':
        return _conv_shapes(p)
    if kernel == 'spmm':
        return _spmm_shapes(p)
    raise ValueError(f'未知算子: {kernel}')


def _conv_shapes(p):
    in_elems = 6 + p['batch'] * p['H'] * p['W'] * p['Cin'] + p['Cout'] * p['Cin'] * p['K'] * p['K']
    out_elems = p['batch'] * p['Cout'] * p['H'] * p['W']
    return in_elems, out_elems


def _spmm_shapes(p):
    in_elems = 4 + (p['M'] + 1) + 2 * p['nnz'] + p['K'] * p['N']
    out_elems = p['M'] * p['N']
    return in_elems, out_elems


def reference(values, spec, n):
    """参考输出。按 spec['kernel'] 分派，规模为 N。"""
    fn = KERNELS.get(spec.get('kernel'))
    if fn is None:
        raise ValueError(f'未知算子的参考实现: {spec.get("kernel")}')
    return fn(values, n, spec)


def _matmul(values, n, spec):
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


def _add(values, n, spec):
    """逐元素相加：C[i] = s32(A[i] + B[i])。输入 = A(N) 接 B(N)。"""
    if len(values) != 2 * n:
        raise ValueError(f'输入长度应为 {2 * n}，实际 {len(values)}')
    a = values[:n]
    b = values[n:2 * n]
    return [s32(x + y) for x, y in zip(a, b)]


def _reducesum(values, n, spec):
    """全归约：out = s32(sum(values))，N 个元素 → 1 个输出。"""
    if len(values) != n:
        raise ValueError(f'输入长度应为 {n}，实际 {len(values)}')
    acc = 0
    for v in values:
        acc = s32(acc + v)      # 逐步 add，与 RV32 语义一致
    return [acc]


def _fwht(values, n, spec):
    """快速哈达玛变换（正向）：out = H_n · x，N = 2^k，float32。

    标准蝶形：len = 1,2,4,... 每级对 (i+j, i+j+len) 做 u+v / u-v，
    每次加减取整到 float32（与 rv32imf 的 `fadd.s`/`fsub.s` 对齐）。
    蝶形是纯加减、结构固定；换序实现（分块/radix-4）只会带来浮点舍入差，
    由 check_output 的 rtol/atol 吸收。
    """
    if len(values) != n:
        raise ValueError(f'输入长度应为 {n}，实际 {len(values)}')
    a = list(values)
    span = 1
    while span < n:
        for i in range(0, n, 2 * span):
            for j in range(span):
                u = a[i + j]
                v = a[i + j + span]
                a[i + j] = f32(u + v)
                a[i + j + span] = f32(u - v)
        span <<= 1
    return a


def _winograd(values, n, spec):
    """2D 直接卷积（SAME padding、stride 1、K∈{3,5}），float32 语义。

    输入 = [batch,H,W,Cin,Cout,K] ++ 特征图（batch*H*W*Cin） ++ 权重（Cout*Cin*K*K）。
    输出 = batch*Cout*H*W（NCHW，行主序）。

    乘、加各取整到 float32，与 rv32imf 的 `fmul.s`+`fadd.s` 逐次对齐；
    比对的容差（rtol/atol）吸收 Winograd 之类换序实现带来的舍入差。
    """
    p = _params(spec, n)
    batch, H, W, Cin, Cout, K = p['batch'], p['H'], p['W'], p['Cin'], p['Cout'], p['K']
    off = 6
    feat = values[off:off + batch * H * W * Cin]
    off += batch * H * W * Cin
    wt = values[off:off + Cout * Cin * K * K]
    pad = K // 2

    out = []
    for b in range(batch):
        for oc in range(Cout):
            for oh in range(H):
                for ow in range(W):
                    acc = 0.0
                    for c in range(Cin):
                        for kh in range(K):
                            ih = oh - pad + kh
                            if ih < 0 or ih >= H:
                                continue
                            for kw in range(K):
                                iw = ow - pad + kw
                                if iw < 0 or iw >= W:
                                    continue
                                x = feat[((b * H + ih) * W + iw) * Cin + c]
                                w = wt[((oc * Cin + c) * K + kh) * K + kw]
                                acc = f32(acc + f32(x * w))
                    out.append(f32(acc))
    return out


def _spmm(values, n, spec):
    """CSR 稀疏矩阵乘稠密矩阵：C = A · B，float32。

    输入（头部与结构是 int32，数值是 float32）：
        [M,K,N,nnz] ++ row_ptr[M+1] ++ col_idx[nnz] ++ values[nnz] ++ B[K*N]   （后两者 float32）

        C[i][j] = Σ_{p∈row i} values[p] · B[col_idx[p]*N + j]

    乘、加各取整到 float32，与 rv32imf 的 `fmul.s`+`fadd.s` 逐步对齐；
    换序（如稠密 GEMM 回退）带来的舍入差由 rtol/atol 吸收。
    """
    p = _params(spec, n)
    M, K, N, nnz = p['M'], p['K'], p['N'], p['nnz']
    row_ptr = values[4:4 + M + 1]
    off = 4 + M + 1
    cols = values[off:off + nnz]
    off += nnz
    vals = values[off:off + nnz]
    off += nnz
    bmat = values[off:off + K * N]

    out = []
    for i in range(M):
        lo, hi = row_ptr[i], row_ptr[i + 1]
        for j in range(N):
            acc = 0.0
            for q in range(lo, hi):
                acc = f32(acc + f32(vals[q] * bmat[cols[q] * N + j]))
            out.append(f32(acc))
    return out


def _make_conv_input(rng, spec, n):
    """构造卷积题的输入：int32 头部 + float32 特征图 + float32 权重。"""
    p = _params(spec, n)
    batch, H, W, Cin, Cout, K = p['batch'], p['H'], p['W'], p['Cin'], p['Cout'], p['K']
    header = [batch, H, W, Cin, Cout, K]
    feat = [f32(rng.uniform(FLOAT_MIN, FLOAT_MAX))
            for _ in range(batch * H * W * Cin)]
    wt = [f32(rng.uniform(FLOAT_MIN, FLOAT_MAX)) for _ in range(Cout * Cin * K * K)]
    return header + feat + wt


def _make_spmm_input(rng, spec, n):
    """构造稀疏矩阵乘题的输入：头部 + 结构（确定性）+ 随机数值 + 稠密 B。

    **结构（row_ptr/col_idx）只由规模标量 n 决定**（与评测种子无关），因此
    每个数据点的 nnz 稳定，可作为 baseline/榜单的 size 键；只有 values 与 B 随机——
    这保证「预先写死答案」不可能通过。
    """
    p = _params(spec, n)
    M, K, N = p['M'], p['K'], p['N']
    row_ptr, cols = spmm_structure(M, K, p['sparsity'], p['key'])
    nnz = row_ptr[-1]
    if nnz != p['nnz']:
        raise ValueError(f'spmm 规模 {n}: 结构 nnz={nnz} 与 spec 声明 {p["nnz"]} 不符')
    # 头部与 row_ptr/col_idx 是 int32，values 与 B 是 float32——wrapper 按值类型发射。
    vals = [f32(rng.uniform(FLOAT_MIN, FLOAT_MAX)) for _ in range(nnz)]
    bmat = [f32(rng.uniform(FLOAT_MIN, FLOAT_MAX)) for _ in range(K * N)]
    return [M, K, N, nnz] + row_ptr + cols + vals + bmat


def spmm_structure(M, K, sparsity, key):
    """确定性的 CSR 结构（与评测种子无关）：行内非零个数围绕目标密度抖动
    （制造负载不均衡），列下标随机不重复。

    key 通常取规模标量 n，使不同数据点结构各异。返回 (row_ptr, col_idx)。
    """
    srng = random.Random(0xC0FFEE ^ (key * 2654435761 & 0xFFFFFFFF))
    target = max(1, int(round(K * (1.0 - sparsity))))
    row_ptr = [0]
    cols = []
    for _ in range(M):
        c = target
        jitter = max(1, c // 4)
        if srng.random() < 0.5:
            c = max(1, c - srng.randint(0, jitter))
        else:
            c = min(K, c + srng.randint(0, jitter))
        row_ptr.append(row_ptr[-1] + c)
        cols.extend(sorted(srng.sample(range(K), c)))
    return row_ptr, cols


def spmm_nnz(M, K, sparsity, key):
    """该 (M,K,密度,key) 下的非零元个数——写 spec 时用它算 size 键。"""
    return spmm_structure(M, K, sparsity, key)[0][-1]


KERNELS = {
    'matmul': _matmul,
    'add': _add,
    'reducesum': _reducesum,
    'fwht': _fwht,
    'winograd': _winograd,
    'spmm': _spmm,
}


def check_output(got, expected, spec, n=None):
    """比对选手输出与参考输出。

    返回 (ok, message)。**只报位置，不报数值**：

    - 数值：评测输入是固定的（见 docs/08「官方评测用例种子」），一旦回显
      「期望 X，实际 Y」，选手就能逐个套取——提交全 0 拿到第 0 个期望值，
      再据此拿第 1 个……迭代若干次即得该数据点的全部答案。所以这里只说
      **哪个位置不对**。位置不构成泄漏：知道第 k 个错，不等于知道它该是多少。
    - 原始字节：同样绝不回显，否则选手可用 `.incbin` 读宿主文件再借失败信息带出。

    输出长度不在此列——那是题面已公开的信息（如「输出 N 个 int32」），
    不构成答案泄漏，且对排查很有用，故保留。

    比对口径：int32 用 spec['tolerance']（默认 0，精确）；float32 用
    `|g-e| <= atol + rtol*|e|`（默认 rtol=1e-4, atol=1e-4）。
    """
    if len(got) != len(expected):
        return False, f'输出长度不符：期望 {len(expected)} 个数值，实际 {len(got)} 个'

    if spec.get('dtype') == 'float32':
        rtol = spec.get('rtol', 1e-4)
        atol = spec.get('atol', 1e-4)
        for idx, (g, e) in enumerate(zip(got, expected)):
            if abs(g - e) > atol + rtol * abs(e):
                where = _describe_index(idx, spec, n)
                return False, f'第 {idx} 个输出数值不符{where}'
        return True, ''

    tol = spec.get('tolerance', 0)
    for idx, (g, e) in enumerate(zip(got, expected)):
        if abs(g - e) > tol:
            where = _describe_index(idx, spec, n)
            return False, f'第 {idx} 个输出数值不符{where}'
    return True, ''


def _describe_index(idx, spec, n):
    if spec.get('kernel') == 'matmul' and n:
        return f'（行 {idx // n}，列 {idx % n}）'
    return ''
