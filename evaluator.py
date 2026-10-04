# -*- coding: utf-8 -*-
"""评测器：把提交编译成 RISC-V 并跑 qemu，判正确性、计分。

对外只有一个入口 `run_evaluation()`，返回 `(score, details)`；
`details['error']` 为 None 表示评测跑完（`tasks.py` 依赖这个契约）。

## 计分（逐点独立）

每题 10 个数据点，**逐点独立判定与计分**：

    单点得分 = 分值 × min(1, 基准指令数 ÷ 本队指令数)    （做对才计，做错该点 0 分）
    总分     = 10 个数据点之和

所以本模块**不短路**：某个数据点错了，仍要继续跑完其余点。
唯一的整题级失败是**编译失败**——它与输入无关，一次编译不过就整题 0 分
（仍会跑完 10 个点？不：编译不通就没法跑，直接返回，`points_earned` 记 0）。

## 设计要点（详见 docs/08）

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
import time

from flask import current_app

import riscv_oracle
import riscv_runner
from contests import get_eval_spec        # 场次感知（contest=None → 默认场次）
from riscv_problems import case_size

# 选手源码里禁止出现的汇编指示符：它们能在**汇编阶段**读宿主任意可读文件
# （.incbin "/etc/passwd"），把编译期变成读取通道。单文件提交用不到它们。
FORBIDDEN_DIRECTIVES = ('.incbin', '.include')


def run_evaluation(submission_id, team_name, problem_id, code_path, contest=None):
    """执行评测，返回 (score, details)。契约见模块 docstring。

    `contest` 为场次（Contest 对象或 slug）；None → 默认场次，与引入多场次前等价。
    评测规格（baseline / 参考解 / 数据点规模）按场次取，因此同一道题在不同场次
    可以跑在不同数据上。
    """
    spec = get_eval_spec(problem_id, contest)
    if spec is None:
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
        return 0.0, _details(verdict, err, error=verdict, problem=problem,
                             full_score=spec['full_score'])

    budget = current_app.config['EVAL_TOTAL_BUDGET']
    cfg = _runner_cfg()
    per_case = spec['points_per_case']
    spec.setdefault('_baselines', _load_baseline(spec, problem))   # {N: 指令数}

    work = riscv_runner.make_work_dir(current_app.config['EVAL_WORK_ROOT'])
    try:
        # 3) 把选手源码搬进工作目录——沙箱用户进不了 /root
        player = os.path.join(work, 'player.s')
        shutil.copyfile(code_path, player)
        os.chmod(player, 0o644)

        # 官方用例种子：优先取场次自带的 seeds，其次部署时经 PLATFORM_EVAL_SEEDS
        # 下发的全局值。跑在固定输入上才能与 baseline 严格可比；未配置则退回随机（开发用）。
        official = spec.get('seeds') or current_app.config.get('EVAL_SEEDS')
        rng = random.Random(random.randrange(2 ** 31))
        cases = []
        earned = 0.0

        for idx in range(spec['case_count']):
            case = {'case': idx, 'seed': None, 'size': None, 'verdict': None,
                    'points': 0.0, 'points_max': per_case, 'instructions': None,
                    'cost': None, 'd_miss': None, 'd_access': None, 'd_hitrate': None,
                    'baseline': None, 'ratio': None, 'detail': ''}
            cases.append(case)

            # 预算兜底：超了就停止评测，**已挣到的分保留**（逐点语义），
            # 剩余数据点记 0 分并说明原因，而不是把整题清零
            if time.time() - started > budget:
                case.update(verdict='skipped', detail='评测总时长超出预算，该数据点未评测')
                continue

            case_seed = (official[idx % len(official)] if official
                         else rng.randrange(2 ** 31))
            case['seed'] = case_seed
            n = case_size(spec, idx)
            case['size'] = n
            case['baseline'] = _baseline_for(spec, problem, n)

            values = riscv_oracle.make_input(case_seed, spec, n)
            expected = riscv_oracle.reference(values, spec, n)
            wrapper = riscv_runner.build_wrapper(
                spec, values, n, os.path.join(work, f'wrapper_{idx}.s'))
            elf = os.path.join(work, f'execute_{idx}.elf')

            ok, cerr = riscv_runner.compile_elf(wrapper, player, elf, cfg, work,
                                                march=spec.get('march', 'rv32im'))
            if not ok:
                # 编译失败与输入无关 → 整题失败，后续数据点必然同样失败
                case.update(verdict='compile_error', detail=cerr)
                return 0.0, _details('compile_error', f'编译失败：{cerr}',
                                     error='compile_error', problem=problem,
                                     cases=cases, full_score=spec['full_score'])

            rc, out, _serr = riscv_runner.run_elf(elf, cfg, work)
            if rc is None:
                case.update(verdict='timeout', detail='运行超时')
                continue
            if rc < 0:
                # SIGXCPU（-24）是"超出 CPU 限额"，语义上就是超时——
                # 否则墙钟超时与 CPU 限额哪个先生效，会决定它被判成
                # timeout 还是 runtime_error，不稳定。
                v = 'timeout' if rc == -24 else 'runtime_error'
                case.update(verdict=v, detail=_signal_message(rc))
                continue
            if rc != 0:
                case.update(verdict='runtime_error', detail=f'退出码 {rc}')
                continue

            got, guard_ok, gmsg = riscv_runner.parse_dump(out, spec, n)
            if not guard_ok:
                case.update(verdict='invalid', detail=gmsg)
                continue

            match, mmsg = riscv_oracle.check_output(got, expected, spec, n)
            if not match:
                case.update(verdict='invalid', detail=mmsg)
                continue

            # 4) 只有该点正确才数指令（单步最慢）
            if time.time() - started > budget:
                case.update(verdict='skipped', detail='评测总时长超出预算，该数据点未数指令')
                continue
            trace = os.path.join(work, f'trace_{idx}.log')
            cfg.pop('_cache_stats', None)          # 清掉上一轮的
            count, truncated = riscv_runner.count_instructions(elf, cfg, work, trace)
            stats = riscv_runner.take_cache_stats(cfg)
            if truncated:
                case.update(verdict='timeout', detail='指令数超出上限')
                continue
            if count is None:
                case.update(verdict='runtime_error', detail='指令计数失败')
                continue

            # 评测指标：cost = 指令数 + α × L1 未命中（α 见 config.MISS_PENALTY）
            penalty = current_app.config['MISS_PENALTY']
            c0 = stats[-1] if stats else None
            n_miss = ((c0['d_miss'] + c0['i_miss']) if c0 else 0)
            cost = count + penalty * n_miss
            ratio = _ratio(case['baseline'], cost)
            pts = round(per_case * ratio, 3)
            earned += pts
            case.update(verdict='accepted', instructions=count, cost=cost,
                        ratio=ratio, points=pts)
            if c0:
                case['d_miss'] = c0['d_miss']
                case['d_access'] = c0['d_access']
                case['d_hitrate'] = c0['d_hitrate']

        score = round(earned, 2)
        passed = sum(1 for c in cases if c['verdict'] == 'accepted')
        return score, _summary(problem, spec, cases, score, passed, started)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _summary(problem, spec, cases, score, passed, started):
    """把逐点结果汇总成给选手看的 details。verdict 反映整体结论。"""
    if passed == spec['case_count']:
        verdict, err = 'accepted', None
        message = (f'全部 {passed}/{spec["case_count"]} 个数据点通过，得分 '
                   f'{score}/{spec["full_score"]}')
    elif passed == 0:
        # 整题 0 分：按失败记录（与既有 standings 口径一致——0 分不占名额）。
        # 归因：10 个数据点都是同一种失败原因时沿用该原因（timeout / 编译失败 …），
        # 混杂则统一记 invalid——否则"全超时"会被笼统说成"结果不正确"。
        reasons = {c['verdict'] for c in cases if c['verdict'] != 'skipped'}
        verdict = reasons.pop() if len(reasons) == 1 else 'invalid'
        err = verdict
        message = (f'没有数据点通过（0/{spec["case_count"]}），得分 '
                   f'0/{spec["full_score"]}')
    else:
        # 部分通过：已挣到的分有效，按成功记录以计入榜单
        verdict, err = 'partial', None
        message = (f'通过 {passed}/{spec["case_count"]} 个数据点，得分 '
                   f'{score}/{spec["full_score"]}')

    return {
        'verdict': verdict,
        'error': err,
        'message': message,
        'problem': problem,
        # baseline 现在是逐数据点的（见 cases[i]['baseline']），顶层不再给单一值
        'baseline_instructions': None,
        'player_instructions': min((c['instructions'] for c in cases
                                    if c['instructions'] is not None), default=None),
        'min_cost': min((c['cost'] for c in cases
                         if c.get('cost') is not None), default=None),
        'score': score,
        'full_score': spec['full_score'],
        'passed_cases': passed,
        'total_cases': spec['case_count'],
        'points_per_case': spec['points_per_case'],
        'cases': cases,
        'timing': {'total_s': round(time.time() - started, 2)},
    }


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

    entry = spec['entry_symbol']
    if entry not in text:
        return False, (f'未找到入口符号 {entry}，请定义全局符号 '
                       f'`{entry}` 作为解题函数'), 'compile_error'
    return True, '', None


def _load_baseline(spec, problem_id):
    """加载**逐数据点**的 baseline：返回 {规模N: 指令数}。

    每个数据点规模不同，指令数自然不同，不能用一个数。缺失时返回 {}，
    该题不判分（但仍跑通、能给出正确性结果）。
    """
    path = spec['baseline_file']
    if not os.path.isabs(path):
        path = os.path.join(current_app.config['BASE_DIR'], path)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    entry = data.get(problem_id, {})
    per_n = entry.get('by_size') if isinstance(entry, dict) else None
    if not isinstance(per_n, dict):
        return {}
    return {int(k): v for k, v in per_n.items()}


def _baseline_for(spec, problem_id, n):
    """取某个规模 N 的 baseline 指令数（缓存到 spec 上，避免每点重读文件）。"""
    cache = spec.setdefault('_baselines', _load_baseline(spec, problem_id))
    return cache.get(n)


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


def _details(verdict, message, error=None, problem=None, cases=None,
             baseline_instructions=None, full_score=None, debug=None):
    d = {
        'verdict': verdict,
        'error': error,
        'message': message,
        'problem': problem,
        'baseline_instructions': baseline_instructions,
        'player_instructions': None,
        'score': 0.0,
        'full_score': full_score,
        'passed_cases': 0,
        'total_cases': None,
        'cases': cases or [],
    }
    if debug:
        d['debug'] = debug[:500]
    return d
