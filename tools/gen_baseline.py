#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线生成 baseline 指令数（开发期跑，**不在评测运行路径上**）。

做法：把参考解编译成 RV32IM，走**与选手提交完全相同**的 wrapper + 编译 + 单步计数
流水线，这样 baseline 与选手成绩可比。换了 clang 版本或改了 -march 参数都要重跑本脚本。

    .venv/bin/python tools/gen_baseline.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import riscv_oracle          # noqa: E402
import riscv_problems        # noqa: E402
import riscv_runner          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCE_DIR = os.path.join(ROOT, 'reference')

# 与评测一致；这里直接给常量，避免在 app context 外依赖 current_app
CFG = {
    'compile_timeout': 60, 'per_case_timeout': 15, 'count_timeout': 60,
    'enable_netns': True, 'sandbox_uid': 65534, 'sandbox_gid': 65534,
}


def build_reference_asm(source_rel):
    """把 reference/<x>.c 编成 RV32IM 汇编，返回 .s 路径。"""
    src = os.path.join(ROOT, source_rel)
    asm = os.path.splitext(src)[0] + '.s'
    subprocess.run([
        'clang', '--target=riscv32-linux-gnu', '-march=rv32im', '-mabi=ilp32',
        '-O2', '-S', src, '-o', asm,
    ], check=True)
    return asm


def measure(problem_id, spec, asm_path):
    """在多个 seed 上测指令数，确认与输入无关（有依赖则说明实现数据相关，需人工干预）。"""
    work = riscv_runner.make_work_dir('/var/lib/riscv-eval', prefix='riscv_baseline_')
    try:
        player = os.path.join(work, 'player.s')
        shutil.copyfile(asm_path, player)
        os.chmod(player, 0o644)

        counts = []
        # 抽 3 个 seed 验证「指令数与输入无关」即可，不必跑满 10 个数据点
        for idx in range(3):
            seed = 1000 + idx
            values = riscv_oracle.make_input(seed, spec)
            expected = riscv_oracle.reference(values, spec)

            wrapper = riscv_runner.build_wrapper(spec, values, os.path.join(work, f'w{idx}.s'))
            elf = os.path.join(work, f'e{idx}.elf')
            ok, err = riscv_runner.compile_elf(wrapper, player, elf, CFG, work)
            if not ok:
                raise SystemExit(f'参考解编译失败：{err}')

            rc, out, serr = riscv_runner.run_elf(elf, CFG, work)
            got, guard_ok, msg = riscv_runner.parse_dump(out, spec)
            if rc != 0 or not guard_ok or got != expected:
                raise SystemExit(
                    f'参考解本身没通过（seed={seed}, rc={rc}, guard={guard_ok}）：{msg or "输出不符"}\n'
                    f'  期望 {expected}\n  实际 {got}')

            count, trunc = riscv_runner.count_instructions(elf, CFG, work, os.path.join(work, 't.log'))
            if trunc or count is None:
                raise SystemExit('参考解指令数统计失败或被截断')
            counts.append(count)

        if len(set(counts)) != 1:
            print(f'  ⚠️ {problem_id}: 不同 seed 下指令数不一致 {counts}，'
                  f'参考解行为与输入相关，请人工确认')
        return counts[0], counts
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    status = riscv_runner.toolchain_status()
    if not all(status.values()):
        raise SystemExit(f'工具链不全：{status}')

    out_path = os.path.join(ROOT, riscv_problems.DATA_DIR_BASELINE)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    data = {}
    if os.path.exists(out_path):
        with open(out_path, encoding='utf-8') as f:
            data = json.load(f)

    for problem_id, spec in riscv_problems.EVAL_SPECS.items():
        # 每题的参考解在 spec['reference'] 里指定，如 reference/add.c
        asm = build_reference_asm(spec['reference'])
        count, all_counts = measure(problem_id, spec, asm)
        data[problem_id] = {
            'baseline_instructions': count,
            'reference': os.path.relpath(asm, ROOT),
            'measured_counts': all_counts,
            'march': 'rv32im', 'no_relax': True,
        }
        print(f'{problem_id}: baseline = {count} 条指令（各 seed: {all_counts}）')

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'已写入 {out_path}')


if __name__ == '__main__':
    main()
