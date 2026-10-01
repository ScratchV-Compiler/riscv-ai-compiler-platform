# -*- coding: utf-8 -*-
"""
赛题元数据（展示用）。

当前只有一道题：`matmul-4x4`——手写 RV32IM 汇编实现 4x4 定点矩阵乘，
平台汇编链接后用 qemu-riscv32 真实执行并判分。

此处只放"怎么展示"；"怎么评"在 riscv_problems.py，两者用同一个 id 关联；
评分口径与安全边界见 docs/08。

`submittable` 标记该题是否开放提交评测。将来若要先上线题面、后接评测，
把新题以 `submittable=False` 加进来即可，页面会自动显示为"暂未开放提交"。
"""

PROBLEMS = [
    {
        "id": "matmul-4x4",
        "no": 1,
        "code": "RV 1",
        "submittable": True,          # 开放提交评测（RISC-V + qemu）
        "title": "4x4 定点矩阵乘",
        "summary": "手写 RV32IM 汇编实现 4x4 定点矩阵乘法，用 qemu 跑出真实结果并与参考比对。",
        "task": (
            "用 RISC-V（RV32IM，ilp32）汇编实现一个裸机函数，计算两个 4x4 矩阵的乘积。"
            "数据为 Q16.16 定点整数，按行主序存放。评测机把你的汇编与固定 wrapper 链接后"
            "交给 qemu-riscv32 执行，读出结果与参考实现逐一比对，正确后按指令数计分。"
        ),
        "input": (
            "a0 指向输入张量：前 16 个 int32 是矩阵 A，后 16 个是矩阵 B（均行主序）。"
            "取值范围 [-32768, 32767]，即 Q16.16 的 [-0.5, 0.5)，单次乘法不会溢出 int32。"
        ),
        "output": (
            "a1 指向输出张量：16 个 int32，按行主序存放结果。"
            "计算口径 C[i][j] = Σₖ ( (A[i][k] × B[k][j]) >> 16 )，取算术右移。"
            "须定义全局符号 cnn_entry 作为入口；越界写会被保护区检测并判失败。"
        ),
        "scale": "固定 4x4；每次评测由平台随机生成输入，无法预先写死答案。",
        "baseline": "参考解：三层循环直译，360 条动态指令。",
        "hint": (
            "本题可只用 32 位 mul（无需 mulh）。sp 指向工作区顶端，栈可正常使用。"
            "想拿高分就减少动态指令数：把循环展开、复用寄存器、避免重复取数。"
        ),
        "formula": (
            "示例：若 A 为单位阵的 Q16.16 表示（对角线 32767），则 C ≈ 32767 × B / 65536。\n"
            "运行时约定：sp 已就绪，返回即 dump 内存；结果写入 a1 指向的 64 字节。"
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
