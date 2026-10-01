# -*- coding: utf-8 -*-
"""评测器：把提交编译成 RISC-V 并跑 qemu，判正确性、计分。

对外只有一个入口 `run_evaluation()`，返回 `(score, details)`；
`details['error']` 为 None 表示评测本身跑通（`tasks.py` 依赖这个契约）。

设计要点（详见 docs/08）：
- **输入每次随机**：期望输出由 riscv_oracle 现场算，输入张量现场生成并嵌进
  wrapper。选手无法把答案写死——见 D1，这是整个评测的立足点。
- **不回显原始字节**：details 里只给十进制数值差与结论，防止选手用
  `.incbin` 读宿主文件后借失败信息外带（D2）。
- **沙箱**：编译与运行都在降权 + 断网下执行；选手源码先搬进沙箱可读的
  工作目录（/root 是 0700，nobody 根本进不去）。
- 本模块在 import 时**不做任何探测或子进程调用**：`tools/export_static.py`
  会经 app → tasks 导入它，import 期副作用会拖垮静态站构建。
"""

import json
import os
import random
import shutil
import tempfile
import time

from flask import current_app

import riscv_oracle
import riscv_runner
from riscv_problems import get_eval_spec, layout

# 选手源码里禁止出现的汇编指示符：它们能在**汇编阶段**读宿主任意可读文件
# （.incbin "/etc/passwd"），把编译期变成读取通道。单文件提交用不到它们。
FORBIDDEN_DIRECTIVES = ('.incbin', '.include')


def run_evaluation(submission_id, team_name, problem_id, code_path):
    """执行评测，返回 (score, details)。契约见模块 docstring。"""
    spec = get_eval_spec(problem_id)
    if spec is None:
        # 非 RISC-V 题（riscv_problems 里没有评测规格）：暂未开放评测
        return 0.0, _details('unsupported', '该题暂未开放评测', error='unsupported',
                             problem=problem_id)

    try:
        return _evaluate_riscv_asm(spec, problem_id, code_path)
    except Exception as exc:                      # noqa: BLE001 —— 兜底，绝不让任务卡在 running
        return 0.0, _details('internal_error', '评测系统内部错误，请联系管理员',
                             error='internal_error', problem=problem_id,
                             debug=f'{type(exc).__name__}: {exc}')


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _evaluate_riscv_asm(spec, problem_id, code_path):
    problem = problem_id
    started = time.time()

    # 1) 工具链自检：缺工具是平台问题，不是选手问题
    if not riscv_runner.toolchain_ok():
        return 0.0, _details('internal_error', '评测机工具链未就绪，请联系管理员',
                             error='internal_error', problem=problem,
                             debug=str(riscv_runner.toolchain_status()))

    # 2) 源码预检
    ok, err, verdict = _precheck(spec, code_path)
    if not ok:
        return 0.0, _details(verdict, err, error=verdict, problem=problem)

    budget = current_app.config['EVAL_TOTAL_BUDGET']
    cfg = _runner_cfg()

    work = riscv_runner.make_work_dir(current_app.config['EVAL_WORK_ROOT'])
    try:
        # 3) 把选手源码搬进工作目录——沙箱用户进不了 /root
        player = os.path.join(work, 'player.s')
        shutil.copyfile(code_path, player)
        os.chmod(player, 0o644)

        baseline = _load_baseline(spec, problem)

        cases = []
        seed = random.randrange(2 ** 31)
        rng = random.Random(seed)

        for idx in range(spec['case_count']):
            case_seed = rng.randrange(2 ** 31)
            if time.time() - started > budget:
                return 0.0, _details('timeout', '评测超时，请简化实现',
                                     error='timeout', problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)

            case = {'case': idx, 'seed': case_seed}
            cases.append(case)

            values = riscv_oracle.make_input(case_seed, spec)
            expected = riscv_oracle.reference(values, spec)
            wrapper = riscv_runner.build_wrapper(
                spec, values, os.path.join(work, f'wrapper_{idx}.s'))
            elf = os.path.join(work, f'execute_{idx}.elf')

            ok, cerr = riscv_runner.compile_elf(wrapper, player, elf, cfg, work)
            if not ok:
                case.update(verdict='compile_error', detail=cerr)
                return 0.0, _details('compile_error', f'编译失败：{cerr}',
                                     error='compile_error', problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)

            rc, out, _serr = riscv_runner.run_elf(elf, cfg, work)
            if rc is None:
                case.update(verdict='timeout', detail='运行超时')
                return 0.0, _details('timeout', '运行超时（可能存在死循环）',
                                     error='timeout', problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)
            if rc < 0:
                case.update(verdict='runtime_error', detail=f'信号 {-rc}')
                return 0.0, _details('runtime_error', _signal_message(rc),
                                     error='runtime_error', problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)
            if rc != 0:
                case.update(verdict='runtime_error', detail=f'退出码 {rc}')
                return 0.0, _details('runtime_error', f'程序异常退出（退出码 {rc}）',
                                     error='runtime_error', problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)

            got, guard_ok, gmsg = riscv_runner.parse_dump(out, spec)
            if not guard_ok:
                case.update(verdict='invalid', detail=gmsg)
                return 0.0, _details('invalid', gmsg, error='invalid', problem=problem,
                                     seed=seed, baseline_instructions=baseline, cases=cases)

            match, mmsg = riscv_oracle.check_output(got, expected, spec)
            if not match:
                case.update(verdict='invalid', detail=mmsg)
                return 0.0, _details('invalid', f'输出不正确。{mmsg}', error='invalid',
                                     problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)

            # 4) 只有正确性过了才数指令（单步是最慢的一环）
            if time.time() - started > budget:
                return 0.0, _details('timeout', '评测超时（数指令阶段）',
                                     error='timeout', problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)
            trace = os.path.join(work, f'trace_{idx}.log')
            count, truncated = riscv_runner.count_instructions(elf, cfg, work, trace)
            if truncated:
                case.update(verdict='timeout', detail='指令数超出上限')
                return 0.0, _details('timeout', '指令数超出上限（可能存在超长循环）',
                                     error='timeout', problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)
            if count is None:
                case.update(verdict='runtime_error', detail='数指令失败')
                return 0.0, _details('runtime_error', '指令计数失败，请重试',
                                     error='runtime_error', problem=problem, seed=seed,
                                     baseline_instructions=baseline, cases=cases)

            case.update(verdict='accepted', instructions=count,
                        baseline=baseline, ratio=_ratio(baseline, count))

        # 5) 计分：取**最差用例**的加速比，防单用例爆表刷分
        score_per_case = min(c['ratio'] for c in cases)
        score = round(min(1.0, score_per_case) * spec['full_score'], 2)
        worst = min(cases, key=lambda c: c['ratio'])
        detail = {
            'verdict': 'accepted',
            'error': None,
            'message': f'通过 {len(cases)} 个用例，得分 {score}',
            'problem': problem,
            'seed': seed,
            'baseline_instructions': baseline,
            'player_instructions': worst['instructions'],
            'score': score,
            'cases': cases,
            'timing': {'total_s': round(time.time() - started, 2)},
        }
        return score, detail
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _runner_cfg():
    c = current_app.config
    return {
        'compile_timeout': c['COMPILE_TIMEOUT'],
        'per_case_timeout': c['PER_CASE_TIMEOUT'],
        'count_timeout': c['COUNT_TIMEOUT'],
        'enable_netns': c['ENABLE_SANDBOX'],
        'sandbox_uid': c['SANDBOX_UID'] if c['ENABLE_SANDBOX'] else None,
        'sandbox_gid': c['SANDBOX_GID'] if c['ENABLE_SANDBOX'] else None,
    }


def _precheck(spec, code_path):
    """返回 (ok, message, verdict)。"""
    if not code_path or not os.path.exists(code_path):
        return False, '提交的源码文件不存在', 'internal_error'

    size = os.path.getsize(code_path)
    max_bytes = current_app.config['SUBMISSION_MAX_BYTES']
    if size == 0:
        return False, '提交的源码是空文件', 'compile_error'
    if size > max_bytes:
        return False, f'源码过大（{size} 字节，上限 {max_bytes}）', 'compile_error'

    suffix = spec.get('file_suffix', '.s')
    if not code_path.endswith(suffix):
        return False, f'文件类型不符，本赛题请提交 {suffix} 文件', 'compile_error'

    try:
        with open(code_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except UnicodeDecodeError:
        return False, '源码不是 UTF-8 文本', 'compile_error'

    low = text.lower()
    for directive in FORBIDDEN_DIRECTIVES:
        if directive in low:
            return False, (f'源码包含被禁止的指示符 {directive}：'
                           f'单文件提交不允许读取外部文件'), 'compile_error'

    # `call <symbol>` / `jal` 指向的入口必须在源码里定义，否则链接会失败——
    # 这里只做可读性更好的提前提示，真正判定交给链接器
    entry = spec['entry_symbol']
    if entry not in text:
        return False, (f'未找到入口符号 {entry}，请定义全局符号 '
                       f'`{entry}` 作为解题函数'), 'compile_error'
    return True, '', None


def _load_baseline(spec, problem_id):
    """加载 baseline 指令数；缺失时返回 None（该题将不判分，但评测仍跑通）。"""
    path = spec['baseline_file']
    if not os.path.isabs(path):
        path = os.path.join(current_app.config['BASE_DIR'], path)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    entry = data.get(problem_id)
    if isinstance(entry, dict):
        return entry.get('baseline_instructions')
    return entry


def _ratio(baseline, count):
    if not baseline or not count or baseline <= 0:
        return 0.0
    return min(1.0, baseline / count)


def _signal_message(rc):
    sig = -rc
    if sig == 11:
        return '非法内存访问（段错误）'
    if sig == 4:
        return '执行了非法指令'
    if sig == 24:
        return '运行超时（CPU 限额）'
    if sig == 9:
        return '运行被强制终止（内存或资源超限）'
    return f'程序被信号 {sig} 终止'


def _details(verdict, message, error=None, problem=None, seed=None,
             baseline_instructions=None, cases=None, debug=None):
    d = {
        'verdict': verdict,
        'error': error,
        'message': message,
        'problem': problem,
        'seed': seed,
        'baseline_instructions': baseline_instructions,
        'player_instructions': None,
        'score': 0.0,
        'cases': cases or [],
    }
    if debug:
        d['debug'] = debug[:500]
    return d
