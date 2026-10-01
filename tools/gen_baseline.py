#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线生成 baseline 指令数（开发期跑，**不在评测运行路径上**）。

数据点按规模分级，所以 baseline 也是**逐数据点**的：
`data/baseline.json` 形如 `{题目: {"by_size": {N: 指令数, ...}}}`。

做法：把每题的参考解编成 RV32IM，走**与选手提交完全相同**的 wrapper + 编译 +
单步计数流水线，逐规模测量。顺带校验参考解本身正确（期望输出与 oracle 一致、
guard 完好），所以本脚本同时是一次 oracle ↔ C 参考实现的交叉验证。

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

# 与平台一致：cost = 指令数 + α × L1 未命中（α 见 config.MISS_PENALTY）
MISS_PENALTY = int(os.environ.get('PLATFORM_MISS_PENALTY') or 15)

# 与评测一致；这里直接给常量，避免在 app context 外依赖 current_app
CFG = {
    'compile_timeout': 90, 'per_case_timeout': 60, 'count_timeout': 300,
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


def measure_problem(problem_id, spec, asm_path):
    """逐数据点测量；返回 {N: 指令数}。顺便验证参考解正确。"""
    work = riscv_runner.make_work_dir('/var/lib/riscv-eval', prefix='riscv_baseline_')
    try:
        player = os.path.join(work, 'player.s')
        shutil.copyfile(asm_path, player)
        os.chmod(player, 0o644)

        by_size = {}
        for idx in range(spec['case_count']):
            n = riscv_problems.case_size(spec, idx)
            seed = 1000 + idx
            values = riscv_oracle.make_input(seed, spec, n)
            expected = riscv_oracle.reference(values, spec, n)

            wrapper = riscv_runner.build_wrapper(spec, values, n,
                                                 os.path.join(work, f'w{idx}.s'))
            elf = os.path.join(work, f'e{idx}.elf')
            ok, err = riscv_runner.compile_elf(wrapper, player, elf, CFG, work)
            if not ok:
                raise SystemExit(f'{problem_id} N={n} 参考解编译失败：{err}')

            rc, out, _ = riscv_runner.run_elf(elf, CFG, work)
            got, guard_ok, msg = riscv_runner.parse_dump(out, spec, n)
            if rc != 0 or not guard_ok or got != expected:
                raise SystemExit(
                    f'{problem_id} N={n} 参考解本身没通过'
                    f'（rc={rc}, guard={guard_ok}）：{msg or "输出不符"}')

            CFG.pop('_cache_stats', None)
            count, trunc = riscv_runner.count_instructions(
                elf, CFG, work, os.path.join(work, f't{idx}.log'))
            if trunc or count is None:
                raise SystemExit(f'{problem_id} N={n} 指令数统计失败或被截断')
            stats = riscv_runner.take_cache_stats(CFG)
            n_miss = (stats[-1]['d_miss'] + stats[-1]['i_miss']) if stats else 0
            cost = count + MISS_PENALTY * n_miss
            by_size[n] = cost
            print(f'    N={n:<6} → 指令 {count:>9} + {MISS_PENALTY}×{n_miss:<6} '
                  f'= 代价 {cost:>10}')
        return by_size
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    status = riscv_runner.toolchain_status()
    if not all(status.values()):
        raise SystemExit(f'工具链不全：{status}')

    out_path = os.path.join(ROOT, riscv_problems.DATA_DIR_BASELINE)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    data = {}

    for problem_id, spec in riscv_problems.EVAL_SPECS.items():
        print(f'{problem_id}:')
        asm = build_reference_asm(spec['reference'])
        by_size = measure_problem(problem_id, spec, asm)
        data[problem_id] = {
            'by_size': by_size,                 # 每点 baseline 是 **cost**，不是裸指令数
            'metric': 'cost = instructions + %d * l1_misses' % MISS_PENALTY,
            'miss_penalty': MISS_PENALTY,
            'reference': os.path.relpath(asm, ROOT),
            'march': 'rv32im', 'no_relax': True,
        }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f'\n已写入 {out_path}')


if __name__ == '__main__':
    main()
