# -*- coding: utf-8 -*-
"""
赛题元数据（只读展示用）。

口径来源：
- 赛题定义与数据规模：ai_compiler_challange/2026/.../赛题.md、stage2数据点.md
- 实测 baseline 数值：技术盘点与Baseline落地指南.md（PoC 实测）
- 平台计分口径：docs/01-前端设计方案.md 2.8 / 5.3（单题百分制相对分，总分 = 各题之和）
"""

PROBLEMS = [
    {
        "id": "fwht",
        "no": 1,
        "code": "FWHT",
        "title": "哈达玛变换的蝶形运算加速",
        "summary": "把标量三重循环的快速哈达玛变换改写成更少动态指令的 RISC-V 代码。",
        "task": (
            "为 ScratchV 实现快速哈达玛变换（FWHT）的代码生成优化。"
            "baseline 是三层嵌套循环的标量实现，没有任何向量化或循环展开；"
            "选手需要压缩每一层蝶形的动态指令数。"
        ),
        "input": "长度 N = 2^k 的一维数组，Q16.16 定点，数值范围 [-1.0, 1.0]，数组起始地址 4 字节对齐。",
        "output": "变换后的数组，逐元素与参考实现比对，Q16.16 绝对误差 ≤ 1 LSB。",
        "scale": "公开集 N = 64 / 128 / 256 与 512 / 1024；隐藏集覆盖 N = 8 … 4096，共 10 个数据点。",
        "baseline": "标量三重循环 FWHT，无向量化、无展开。实测 N=64 时动态指令 5,680、周期 7,022。",
        "hint": "蝶形每层的访存与寄存器复用是主要开销；循环展开与地址增量预计算收益明显。",
        "formula": "a[i+j] = u + v ; a[i+j+len] = u - v",
    },
    {
        "id": "conv",
        "no": 2,
        "code": "CONV",
        "title": "基于 Winograd 算法的卷积加速",
        "summary": "用 Winograd F(m,r) 矩阵变换替代直接卷积，把每个输出 tile 的乘法次数压下来。",
        "task": (
            "为 ScratchV 实现 Winograd 卷积的代码生成优化。"
            "Winograd F(m,r) 把卷积分解为输入变换、核变换、逐元素乘法、输出变换四步，"
            "在 m=4、r=3 时每个输出 tile 的乘法次数从 m²r² 降到 (m+r-1)²。"
        ),
        "input": "特征图 [N, C_in, H, W]（Q16.16，数值范围 [-0.5, 0.5]）；卷积核 [C_out, C_in, K, K]，K ∈ {3, 5}；stride = 1，padding = SAME。",
        "output": "输出特征图 [N, C_out, H, W]，与参考实现比对，Q16.16 绝对误差 ≤ 1 LSB。",
        "scale": "公开集 A：C=3, K=3, 32×32；公开集 B：C=16, K=3, 32×32。隐藏集覆盖 K=3 与 K=5，通道数 3 … 128。",
        "baseline": "直接卷积（逐输出点六重循环、关闭优化）。实测 1×2×9×9 K5 pad2 动态指令 49,147。",
        "hint": "数值必须收在 [-0.5, 0.5]，否则 Q16.16 乘法会因 32 位截断出错；注意变换矩阵的定点化。",
        "formula": "Y = Aᵀ [ (G g Gᵀ) ⊙ (Bᵀ d B) ] A",
    },
    {
        "id": "spmv",
        "no": 3,
        "code": "SPMV",
        "title": "大规模稀疏矩阵乘法的优化",
        "summary": "为 CSR 稀疏矩阵乘设计存储格式与代码生成，N=1 退化为 SpMV，N>1 为 SpMM。",
        "task": (
            "为 ScratchV 实现 CSR 格式稀疏矩阵乘的代码生成优化。"
            "ScratchV 中没有现成的稀疏算子，需要自行设计 CSR 访存与内层累加循环。"
        ),
        "input": "A[M, K] 以 CSR 给出（values / col_indices / row_ptr 三数组），B[K, N] 稠密；均为 Q16.16，数值范围 [-1.0, 1.0]。",
        "output": "C[M, N] 稠密矩阵，与参考实现比对，Q16.16 绝对误差 ≤ 1 LSB。",
        "scale": "公开集 A：256×256、密度 90%；公开集 B：1024×1024、密度 90%。隐藏集含 10000×100 密度 99%、2048×2048 密度 70%、1024×1024 密度 50% 等。",
        "baseline": "标准 CSR 标量双层循环。ScratchV 尚无实测 baseline 数值，需要自行实现。",
        "hint": "行内非零元分布不均，注意负载均衡与不规则访存的预取。",
        "formula": "y[i] = Σ_{j=row_ptr[i]}^{row_ptr[i+1]-1} values[j] × x[col_indices[j]]",
    },
]

_BY_ID = {p["id"]: p for p in PROBLEMS}


def get_problem(problem_id):
    """按 id 取赛题元数据；不存在返回 None。"""
    return _BY_ID.get(problem_id)


def problem_ids():
    return [p["id"] for p in PROBLEMS]
