# -*- coding: utf-8 -*-
"""真实评测后端：补丁改造 ScratchV 编译器 + 固定赛题。

流水线（详见 docs/06-P3提交与结果设计.md §2.5）：
  1. 取冻结基线 commit 到临时目录（`git archive`，对基线仓只读）；
  2. `git apply` 选手补丁（失败 -> compile_error）；
  3. 校验改动路径面（allow/deny，命中 -> compile_error(scope)）；
  4. 用打补丁后的代码仓编译固定 ONNX 赛题，并用可信的 `verify_model`
     仿真 + 与 NumPy 参考比对，得到 max_lsb 与动态指令/周期；
  5. 可选：同机跑未打补丁基线，得到加速比（基线版本可随时切换）；
  6. 按 scoring 策略算分。
"""
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time

import config
from backends.base import check_scope, parse_patch_paths
from problems import get_problem

# 判断后端是否可用（有 ScratchV 仓 + 校验工具 + 指定解释器）
def available():
    root = config.get('scratchv.root')
    verify = config.Config.SCRATCHV_VERIFY_TOOL
    py = config.get('scratchv.python')
    if not (root and os.path.isdir(os.path.join(root, '.git'))):
        return False
    if not (verify and os.path.exists(verify)):
        return False
    if not (py and os.path.exists(py)):
        return False
    return True


def _extract_baseline(ref, dest):
    """用 `git archive` 把冻结基线导出到 dest（不修改基线仓）。"""
    proc = subprocess.run(
        ['git', '-C', config.get('scratchv.root'), 'archive', '--format=tar', ref],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError('取基线失败：' + proc.stderr.decode('utf-8', 'replace')[-800:])
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode='r:') as tar:
        tar.extractall(dest)


def _apply_patch(tree, patch_path):
    cmd = ['git', 'apply', '--unsafe-paths', patch_path]
    check = subprocess.run(['git', 'apply', '--check', '--unsafe-paths', patch_path],
                           cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check.returncode != 0:
        return False, check.stderr.decode('utf-8', 'replace')[-1500:]
    proc = subprocess.run(cmd, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return False, proc.stderr.decode('utf-8', 'replace')[-1500:]
    return True, ''


def _run_verify(tree, model_path, seed, max_instr, tol_lsb, json_path, timeout_s):
    """在指定代码树（SCRATCHV_ROOT=tree）上运行可信校验工具。"""
    env = os.environ.copy()
    env['SCRATCHV_ROOT'] = tree
    env['PYTHONPATH'] = tree + os.pathsep + env.get('PYTHONPATH', '')
    cmd = [
        config.Config.SCRATCHV_PYTHON, config.Config.SCRATCHV_VERIFY_TOOL,
        model_path, '--seed', str(seed), '--max-instr', str(max_instr),
        '--tol-lsb', str(tol_lsb), '--json', json_path, '--quiet',
    ]
    try:
        proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return 'timeout', None, ''
    data = None
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding='utf-8') as handle:
                data = json.load(handle)
        except (ValueError, OSError):
            data = None
    stderr = proc.stderr.decode('utf-8', 'replace')
    if proc.returncode == 2 or (data is None and proc.returncode != 0):
        return 'error', data, stderr
    return ('pass' if proc.returncode == 0 else 'fail'), data, stderr


def _metrics_from(data):
    perf = (data or {}).get('perf') or {}
    return {
        'instructions': perf.get('dynamic_instructions'),
        'cycles': perf.get('total_cycles'),
        'cpi': round(perf.get('cpi', 0.0), 3) if perf.get('cpi') is not None else None,
        'code_size': perf.get('code_size_bytes'),
    }


def _metric_value(metrics, name):
    if not metrics:
        return None
    if name == 'cycles':
        return metrics.get('cycles')
    return metrics.get('instructions')


def _score(patched, baseline, policy, metric, cap):
    if policy == 'gate_only' or not baseline:
        return cap, None
    b = _metric_value(baseline, metric)
    p = _metric_value(patched, metric)
    if not b or not p:
        return cap, None
    ratio = b / p
    return round(cap * min(1.0, ratio), 2), round(ratio, 4)


def evaluate(submission_id, team_name, problem_id, artifact_path, meta=None):
    started = time.time()
    meta = meta or {}
    problem = get_problem(problem_id)
    details = {
        'backend': 'scratchv-patch',
        'problem': problem_id,
        'baseline_ref': config.Config.SCRATCHV_BASELINE_REF,
    }

    if not problem or problem.get('kind') != 'patch':
        details.update(verdict='compile_error', stage='problem',
                       error=f'赛题 {problem_id} 不是补丁赛题。')
        return 0.0, details

    target_model = config.resolve_path(problem.get('target_model'))
    if not target_model or not os.path.exists(target_model):
        details.update(verdict='runtime_error', stage='setup',
                       error=f'固定赛题模型不存在：{target_model}')
        return 0.0, details
    details['target_model'] = os.path.basename(target_model)

    try:
        with open(artifact_path, encoding='utf-8', errors='replace') as handle:
            patch_text = handle.read()
    except OSError as exc:
        details.update(verdict='runtime_error', stage='setup', error=f'读取补丁失败：{exc}')
        return 0.0, details

    # ---- 路径面校验（先于应用，尽早拒绝）----
    paths = parse_patch_paths(patch_text)
    if not paths:
        details.update(verdict='compile_error', stage='apply',
                       error='未能从补丁中解析出任何改动路径，请确认是 git diff / format-patch 产物。')
        return 0.0, details
    details['apply'] = {'files': paths}
    ok, violations = check_scope(paths, config.Config.PATCH_ALLOW, config.Config.PATCH_DENY)
    if not ok:
        details.update(verdict='compile_error', stage='scope',
                       error='补丁改动了不允许的路径：' + '；'.join(f'{p}（{why}）' for p, why in violations))
        return 0.0, details

    workdir = tempfile.mkdtemp(prefix='judge_', dir='/tmp/opencode' if os.path.isdir('/tmp/opencode') else None)
    try:
        base = os.path.join(workdir, 'base')
        os.makedirs(base)
        try:
            _extract_baseline(config.Config.SCRATCHV_BASELINE_REF, base)
        except Exception as exc:  # noqa: BLE001
            details.update(verdict='runtime_error', stage='setup', error=str(exc))
            return 0.0, details

        applied, log = _apply_patch(base, artifact_path)
        if not applied:
            details.update(verdict='compile_error', stage='apply',
                           error='补丁无法应用（可能与冻结基线不一致）。', log_tail=log)
            return 0.0, details

        seed = int(problem.get('seed', 0) or 0)
        max_instr = int(problem.get('max_instr') or config.Config.JUDGE_MAX_INSTR)
        tol = int(config.Config.JUDGE_TOL_LSB)
        timeout_s = int(config.Config.EVAL_TIMEOUT)

        status, data, stderr = _run_verify(
            base, target_model, seed, max_instr, tol,
            os.path.join(workdir, 'patched.json'), timeout_s)

        if status == 'timeout':
            details.update(verdict='timeout', error='评测超时（编译或仿真超过上限）。')
            return 0.0, details
        if status == 'error':
            details.update(verdict='compile_error', stage='compile',
                           error='代码生成/编译失败。', log_tail=stderr[-1500:])
            return 0.0, details

        patched = _metrics_from(data)
        details['correctness'] = {
            'status': (data or {}).get('status'),
            'max_lsb': (data or {}).get('max_lsb'),
            'tol_lsb': tol,
            'output_shape': (data or {}).get('output_shape'),
        }
        details['metrics'] = {'patched': patched, 'baseline': None, 'ratio': {}}

        if status == 'fail':
            details.update(verdict='invalid', error='正确性未通过，成绩无效（一票否决）。')
            details['eval_ms'] = int((time.time() - started) * 1000)
            return 0.0, details

        # ---- 基线（可切换：同机跑未打补丁版本，或用赛题预置值）----
        baseline = None
        source = None
        if config.Config.SCRATCHV_COMPUTE_BASELINE:
            base2 = os.path.join(workdir, 'base_ref')
            os.makedirs(base2, exist_ok=True)
            try:
                _extract_baseline(config.Config.SCRATCHV_BASELINE_REF, base2)
                b_status, b_data, _ = _run_verify(
                    base2, target_model, seed, max_instr, tol,
                    os.path.join(workdir, 'baseline.json'), timeout_s)
                if b_status == 'pass':
                    baseline = _metrics_from(b_data)
                    source = 'computed'
            except Exception:  # noqa: BLE001
                baseline = None
        if baseline is None:
            pre = problem.get('baseline')
            if pre:
                baseline = pre
                source = 'precomputed'

        details['metrics']['baseline'] = baseline
        details['baseline_source'] = source or 'none'

        policy = config.Config.SCORING_POLICY
        metric = config.Config.SCORING_METRIC
        cap = float(config.Config.SCORING_CAP)
        score, ratio = _score(patched, baseline, policy, metric, cap)
        if ratio is not None:
            details['metrics']['ratio'] = {metric: ratio}
        details.update(verdict='accepted', score=score)
        details['eval_ms'] = int((time.time() - started) * 1000)
        return score, details
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
