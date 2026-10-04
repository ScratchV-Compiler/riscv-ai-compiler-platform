# -*- coding: utf-8 -*-
"""
赛题元数据（展示用）。

全局题册——每场竞赛从里面**挑选**自己的试卷（见 contests.py）。所有题都跑在同一套
裸机 ABI 上（a0=输入、a1=输出、a2=规模，入口符号 `cnn_entry`）。每题 **10 个数据点**，
逐点独立计分。分场次的卷子与分值：

    内测比赛1：add 10×3 + matmul 10×3 + reducesum 10×4 = 100
    内测比赛2：fwht 10×3 + winograd 10×3 + spmm 10×4     = 100

此处只放"怎么展示"；"怎么评"在 riscv_problems.py（同一 id 关联），
评分口径与安全边界见 docs/08。模板里用注入的 `eval_spec(p.id)` 取分值等评测信息，
不在这里重复一份、以免两边漂移。

`submittable` 标记该题是否开放提交评测。将来若要先上线题面、后接评测，
把新题以 `submittable=False` 加进来即可，页面会自动显示为"暂未开放提交"。
"""

PROBLEMS = [
    {
        "id": "add",
        "no": 1,
        "code": "RV 1",
        "submittable": True,
        "title": "逐元素相加",
        "summary": "把两个等长定点向量逐元素相加，考察最基础的访存与循环展开。",
        "task": (
            "用 RISC-V（RV32IM，ilp32）汇编实现一个裸机函数，把两个等长向量逐元素相加。"
            "数据为 Q16.16 定点整数。向量长度 N 由 a2 传入，"
            "10 个数据点的 N 各不相同（64 → 4096），必须写尺寸无关的代码。"
            "评测机把你的汇编与固定 wrapper 链接后交给 qemu-riscv32 执行，"
            "读出结果与参考实现比对，正确后按代价计分。"
        ),
        "input": (
            "a0 指向输入张量：前 N 个 int32 是向量 A，后 N 个是向量 B。"
            "N 由 a2 给出。取值范围 [-32768, 32767]，即 Q16.16 的 [-0.5, 0.5)，"
            "单次相加不会溢出 int32。"
        ),
        "output": (
            "a1 指向输出张量：N 个 int32，C[i] = A[i] + B[i]。"
            "须定义全局符号 cnn_entry 作为入口；越界写会被保护区检测并判失败。"
        ),
        "formula": (
            "示例：A = [1024, -2048]，B = [512, 2048] → C = [1536, 0]。\n"
            "运行时约定：sp 已就绪，返回即 dump 内存；结果写入 a1 指向的 N×4 字节。"
        ),
    },
    {
        "id": "matmul",
        "no": 2,
        "code": "RV 2",
        "submittable": True,
        "title": "定点矩阵乘",
        "summary": "用 RV32IM 汇编实现 N×N 定点矩阵乘法，考察寄存器复用与循环组织。",
        "task": (
            "用 RISC-V（RV32IM，ilp32）汇编实现一个裸机函数，计算两个 N×N 矩阵的乘积。"
            "数据为 Q16.16 定点整数，按行主序存放。"
            "阶数 N 由 a2 传入，10 个数据点的 N 各不相同（4×4 → 64×64），"
            "必须写尺寸无关的代码。评测机把你的汇编与固定 wrapper 链接后交给 qemu-riscv32 "
            "执行，读出结果与参考实现逐一比对，正确后按代价计分。"
        ),
        "input": (
            "a0 指向输入张量：前 N² 个 int32 是矩阵 A，后 N² 个是矩阵 B（均行主序）。"
            "取值范围 [-32768, 32767]，即 Q16.16 的 [-0.5, 0.5)，单次乘法不会溢出 int32。"
        ),
        "output": (
            "a1 指向输出张量：N² 个 int32，按行主序存放结果。"
            "计算口径 C[i][j] = Σₖ ( (A[i][k] × B[k][j]) >> 16 )，取算术右移。"
            "须定义全局符号 cnn_entry 作为入口；越界写会被保护区检测并判失败。"
        ),
        "formula": (
            "示例：若 A 为单位阵的 Q16.16 表示（对角线 32767），则 C ≈ 32767 × B / 65536。\n"
            "运行时约定：sp 已就绪，返回即 dump 内存；结果写入 a1 指向的 N²×4 字节。"
        ),
    },
    {
        "id": "reducesum",
        "no": 3,
        "code": "RV 3",
        "submittable": True,
        "title": "归约求和",
        "summary": "把定点向量归约成一个和，考察累加链与多累加器拆分。",
        "task": (
            "用 RISC-V（RV32IM，ilp32）汇编实现一个裸机函数，把定点向量的全部元素求和，"
            "输出单个结果。数据为 Q16.16 定点整数。"
            "向量长度 N 由 a2 传入，10 个数据点的 N 各不相同（64 → 4096），"
            "必须写尺寸无关的代码。评测机把你的汇编与固定 wrapper 链接后交给 qemu-riscv32 "
            "执行，读出结果与参考实现比对，正确后按代价计分。"
        ),
        "input": (
            "a0 指向输入张量：N 个 int32。N 由 a2 给出。取值范围 [-32768, 32767]，"
            "即 Q16.16 的 [-0.5, 0.5)；N 最大 4096，求和最大绝对值约 2²⁷，不会溢出 int32。"
        ),
        "output": (
            "a1 指向输出张量：1 个 int32，即全部 N 个元素之和（无需移位）。"
            "须定义全局符号 cnn_entry 作为入口；越界写会被保护区检测并判失败。"
        ),
        "formula": (
            "示例：[1024, 2048, -512] → 2560。\n"
            "运行时约定：sp 已就绪，返回即 dump 内存；结果写入 a1 指向的 4 字节。"
        ),
    },
    {
        "id": "fwht",
        "no": 1,
        "code": "RV 1",
        "submittable": True,
        "title": "哈达玛变换（蝶形加速）",
        "summary": "用 RISC-V（rv32imf）汇编实现快速哈达玛变换（FWHT），考察蝶形数据流与循环组织。",
        "task": (
            "用 RISC-V 汇编（rv32imf，单精度浮点）实现一个裸机函数，对长度 N=2^k 的向量做"
            "正向快速哈达玛变换（FWHT）。数据为 FP32 浮点。"
            "向量长度 N 由 a2 传入，10 个数据点的 N 各不相同（8 → 4096），"
            "必须写尺寸无关的代码。评测机把你的汇编与固定 wrapper 链接后交给 qemu-riscv32 "
            "执行，读出结果与参考实现比对，正确后按代价计分。正确性按容差判定（rtol=1e-4）。"
        ),
        "input": (
            "a0 指向输入张量：N 个 float32。N 由 a2 给出。取值范围 [-1, 1]。"
        ),
        "output": (
            "a1 指向输出张量：N 个 float32，即 out = H_N · x（标准正向 FWHT，纯加减）。"
            "须定义全局符号 cnn_entry 作为入口；越界写会被保护区检测并判失败。"
        ),
        "formula": (
            "蝶形：len = 1,2,4,…，对 (i+j, i+j+len) 做 u+v / u-v。\n"
            "示例：[1, 2, 3, 4] → [10, -2, -4, 0]。"
        ),
    },
    {
        "id": "winograd",
        "no": 2,
        "code": "RV 2",
        "submittable": True,
        "title": "Winograd 卷积加速",
        "summary": "用 RV32IM（+F）汇编实现 2D 卷积，鼓励用 Winograd 变换减少乘法次数。",
        "task": (
            "用 RISC-V 汇编（rv32imf，单精度浮点）实现一个裸机函数，计算 2D 卷积"
            "（SAME padding、stride=1、核大小 K∈{3,5}）。数据为 FP32 浮点。"
            "形状由输入张量头部的 6 个 int32 给出（[batch,H,W,Cin,Cout,K]），"
            "10 个数据点的形状各不相同，必须写尺寸无关的代码。"
            "baseline 是未优化的直接滑窗卷积；Winograd（F(2,3)/F(4,3) 等）可作为优化手段。"
            "正确性按相对/绝对容差判定（rtol=1e-4、atol=1e-4）。"
        ),
        "input": (
            "a0 指向输入张量：头部 6 个 int32 = [batch, H, W, Cin, Cout, K]，"
            "随后是特征图（batch·H·W·Cin 个 float32，NCHW 排布），"
            "再后是权重（Cout·Cin·K·K 个 float32，OIHW 排布）。取值 [-1, 1]。"
            "a2 给出特征图元素数 batch·H·W·Cin（规模标量）。"
        ),
        "output": (
            "a1 指向输出张量：batch·Cout·H·W 个 float32（NCHW）；SAME padding 使输出"
            "空间尺寸保持 H×W。浮点比对容差 rtol=1e-4、atol=1e-4。"
            "须定义全局符号 cnn_entry 作为入口；越界写会被保护区检测并判失败。"
        ),
        "formula": (
            "out[b,oc,oh,ow] = Σ_{c,kh,kw} in[b,c,oh-pad+kh,ow-pad+kw] · w[oc,c,kh,kw]，pad=K//2。\n"
            "编译固定 -march=rv32imf（单精度 F 扩展）、-mabi=ilp32。"
        ),
    },
    {
        "id": "spmm",
        "no": 3,
        "code": "RV 3",
        "submittable": True,
        "title": "稀疏矩阵乘法（CSR）",
        "summary": "用 RISC-V（rv32imf）汇编实现 CSR 稀疏矩阵乘稠密矩阵，考察不规则访存与数据流。",
        "task": (
            "用 RISC-V 汇编（rv32imf，单精度浮点）实现一个裸机函数，计算 CSR 格式稀疏矩阵 "
            "A（M×K）与稠密矩阵 B（K×N）的乘积。数值为 FP32 浮点。"
            "形状由输入张量头部的 4 个 int32 给出（[M,K,N,nnz]），"
            "10 个数据点的形状与稀疏度各不相同，必须写尺寸无关的代码。"
            "正确性按容差判定（rtol=1e-4）。"
        ),
        "input": (
            "a0 指向输入张量：头部 4 个 int32 = [M, K, N, nnz]，随后 row_ptr[M+1]、"
            "col_idx[nnz]（均为 int32），再后是 values[nnz] 与稠密 B[K*N]（均为 float32，"
            "B 行主序、N 列）。数值范围 [-1, 1]。a2 给出非零元个数 nnz（规模标量）。"
        ),
        "output": (
            "a1 指向输出张量：M·N 个 float32，行主序。"
            "计算口径 C[i][j] = Σ_{p∈row i} values[p] × B[col_idx[p]*N + j]。"
            "须定义全局符号 cnn_entry；越界写会被保护区检测并判失败。"
        ),
        "formula": (
            "SpMV（N=1）与 SpMM（N>1）混合考察。\n"
            "示例：C[i][j] 为第 i 行所有非零元与 B 第 j 列对应行逐项乘后累加。"
        ),
    },
]

_BY_ID = {p["id"]: p for p in PROBLEMS}


def get_problem(problem_id):
    """按 id 取赛题元数据；不存在返回 None。"""
    return _BY_ID.get(problem_id)


def problem_ids():
    return [p["id"] for p in PROBLEMS]


def submittable_problems():
    """开放提交评测的题目。"""
    return [p for p in PROBLEMS if p.get("submittable")]
