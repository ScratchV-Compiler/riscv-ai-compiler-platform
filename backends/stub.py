# -*- coding: utf-8 -*-
"""离线确定性桩后端：无 ScratchV 环境时也能量完整跑通"提交→结果"闭环。

用于 demo 赛道（公开演示站，不执行选手代码）与本地联调。判定规则确定、可预期：
  * 空文件                      -> compile_error
  * 含标记 `#FAIL`             -> invalid（正确性未通过）
  * 含标记 `#COMPILE_ERROR`    -> compile_error
  * 含标记 `#TIMEOUT`          -> timeout
  * 含标记 `#SLOW`             -> accepted，加速比 < 1（得分 < 满分）
  * 其余                        -> accepted，满分
"""
import hashlib
import time

from backends.base import verdict_label
from config import get


def _metric_for(content):
    """由内容摘要派生一组稳定的伪指标，保证同文件同结果。"""
    digest = hashlib.sha256(content).hexdigest()[:8]
    n = int(digest, 16)
    instructions = 20000 + n % 30000
    cycles = int(instructions * (1.3 + (n % 50) / 100.0))
    return {
        'instructions': instructions,
        'cycles': cycles,
        'cpi': round(cycles / instructions, 3),
        'code_size': 400 + n % 600,
    }


def evaluate(submission_id, team_name, problem_id, artifact_path, meta=None):
    started = time.time()
    meta = meta or {}
    try:
        with open(artifact_path, 'rb') as handle:
            content = handle.read()
    except OSError as exc:
        return 0.0, {
            'backend': 'stub', 'verdict': 'runtime_error',
            'error': f'读取提交文件失败：{exc}',
        }

    base = {
        'backend': 'stub',
        'problem': problem_id,
        'simulated': True,
        'eval_ms': 0,
    }

    if len(content) == 0:
        base.update(verdict='compile_error', stage='apply',
                    error='提交文件为空，请检查后重新提交。')
        return 0.0, base

    if b'#COMPILE_ERROR' in content:
        base.update(verdict='compile_error', stage='compile',
                    error='（桩）补丁未能通过编译。')
        return 0.0, base

    if b'#TIMEOUT' in content:
        base.update(verdict='timeout', error='（桩）评测超时。')
        return 0.0, base

    patched = _metric_for(content)

    if b'#FAIL' in content:
        base.update(
            verdict='invalid',
            correctness={'status': 'FAIL', 'max_lsb': 125, 'tol_lsb': int(get('judge.tol_lsb', 1))},
            metrics={'patched': patched, 'baseline': None, 'ratio': {}},
            error='（桩）输出与参考不一致。',
        )
        base['eval_ms'] = int((time.time() - started) * 1000)
        return 0.0, base

    # 基线（桩）指标：略快于 patched，制造一个 <1 的加速比以便演示区分
    baseline = {
        'instructions': int(patched['instructions'] * 1.4),
        'cycles': int(patched['cycles'] * (2.0 if b'#SLOW' in content else 1.4)),
        'cpi': patched['cpi'],
        'code_size': patched['code_size'],
    }
    metric = get('scoring.metric', 'cycles')
    cap = float(get('scoring.cap', 100))
    ratio = baseline[metric] / patched[metric] if patched[metric] else 0.0
    score = round(cap * min(1.0, ratio), 2)

    base.update(
        verdict='accepted',
        correctness={'status': 'PASS', 'max_lsb': 0, 'tol_lsb': int(get('judge.tol_lsb', 1))},
        metrics={
            'patched': patched,
            'baseline': baseline,
            'ratio': {
                'instructions': round(baseline['instructions'] / patched['instructions'], 3),
                'cycles': round(baseline['cycles'] / patched['cycles'], 3),
            },
        },
        score=score,
        baseline_source='stub',
    )
    base['eval_ms'] = int((time.time() - started) * 1000)
    return score, base
