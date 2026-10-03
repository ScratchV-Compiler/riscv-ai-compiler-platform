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
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contests              # noqa: E402
import riscv_oracle          # noqa: E402
import riscv_problems        # noqa: E402
import riscv_runner          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 与平台一致：cost = 指令数 + α × L1 未命中（α 见 config.MISS_PENALTY）
MISS_PENALTY = int(os.environ.get('PLATFORM_MISS_PENALTY') or 15)

# 官方评测用例种子：与 evaluator 取同一处环境变量，确保 baseline 与评测
# **跑在同一批输入上**。未配置时退回 seed=1000+idx（开发用）。
_SEEDS_RAW = os.environ.get('PLATFORM_EVAL_SEEDS') or ''
EVAL_SEEDS = [int(x) for x in _SEEDS_RAW.replace(' ', '').split(',') if x] or None

# 参考解的编译优化级别 —— 用 PLATFORM_REFERENCE_OPT 覆盖。
#
# 取 -O0：官方《赛题baseline.md》写明 baseline「不包含任何手动的向量化、算法变换
# 或数据流优化」，并要求选手**在此基础上超越**。本仓进一步连编译器的自动优化都
# 不开，让 baseline 成为真正的**朴素起点**。
#
# 代价：从 -O2 降到 -O0，参考解会慢 2.3~3.4 倍（实测 add 2.33× / matmul 3.28× /
# reducesum 3.39×）。所谓「开优化就能白拿」的部分现在留给选手。
REFERENCE_OPT = os.environ.get('PLATFORM_REFERENCE_OPT') or '-O0'

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
        REFERENCE_OPT, '-fno-builtin', '-S', src, '-o', asm,
    ], check=True)
    return asm


def measure_problem(problem_id, spec, asm_path, seeds=None):
    """逐数据点测量；返回 {N: 指令数}。顺便验证参考解正确。"""
    seeds = seeds if seeds is not None else EVAL_SEEDS
    work = riscv_runner.make_work_dir('/var/lib/riscv-eval', prefix='riscv_baseline_')
    try:
        player = os.path.join(work, 'player.s')
        shutil.copyfile(asm_path, player)
        os.chmod(player, 0o644)

        by_size = {}
        by_size_insn = {}       # 同一规模的裸指令数（供演示数据推导 指令:代价 比例）
        for idx in range(spec['case_count']):
            n = riscv_problems.case_size(spec, idx)
            seed = seeds[idx % len(seeds)] if seeds else 1000 + idx
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
            by_size_insn[n] = count
            print(f'    N={n:<6} → 指令 {count:>9} + {MISS_PENALTY}×{n_miss:<6} '
                  f'= 代价 {cost:>10}')
        return by_size, by_size_insn
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description='逐数据点生成 baseline')
    ap.add_argument('--contest', default=None,
                    help='场次 slug（默认场次可省略）——按该场次的试卷与规格测量')
    args = ap.parse_args()

    contest = contests.get_contest(args.contest) if args.contest else contests.default_contest()
    if contest is None:
        raise SystemExit(f'未知场次：{args.contest}')

    status = riscv_runner.toolchain_status()
    if not all(status.values()):
        raise SystemExit(f'工具链不全：{status}')

    out_rel = contest.baseline_file or riscv_problems.DATA_DIR_BASELINE
    out_path = os.path.join(ROOT, out_rel)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    data = {}

    print(f'场次：{contest.slug}（{contest.title}）→ {out_rel}')
    seeds = list(contest.seeds) if contest.seeds else EVAL_SEEDS
    for problem_id, spec in contests.specs_for(contest).items():
        if spec is None:
            continue
        print(f'{problem_id}:')
        asm = build_reference_asm(spec['reference'])
        by_size, by_insn = measure_problem(problem_id, spec, asm, seeds=seeds)
        data[problem_id] = {
            'by_size': by_size,                 # 每点 baseline 是 **cost**，不是裸指令数
            'by_size_instructions': by_insn,
            'metric': 'cost = instructions + %d * l1_misses' % MISS_PENALTY,
            'miss_penalty': MISS_PENALTY,
            'reference': os.path.relpath(asm, ROOT),
            'march': 'rv32im', 'no_relax': True, 'opt': REFERENCE_OPT,
        }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f'\n已写入 {out_path}')


if __name__ == '__main__':
    main()
