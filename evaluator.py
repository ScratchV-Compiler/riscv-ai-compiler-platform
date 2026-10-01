# -*- coding: utf-8 -*-
"""评测门面：按配置选择后端，统一 run_evaluation 接口。

后端由 `platform.yaml` 的 `judge.backend` 决定：
  * auto            —— 有可用 ScratchV 环境则用 scratchv_patch，否则回退 stub
  * scratchv_patch  —— 真实：补丁改造 ScratchV 编译器 + 固定赛题
  * stub            —— 离线确定性桩（demo 赛道 / 本地联调）

返回 (score, details_dict)；details 必含 `verdict`。
"""
import config
import problems
from backends import scratchv_patch, stub


def choose_backend():
    name = str(config.get('judge.backend', 'auto') or 'auto').strip()
    if name == 'auto':
        # demo 赛道只做确定性桩评测（安全，不执行选手代码）；
        # contest 赛道在有 ScratchV 环境时走真实补丁评测。
        if problems.is_contest() and scratchv_patch.available():
            return 'scratchv_patch'
        return 'stub'
    return name


def run_evaluation(submission_id, team_name, problem_id, code_path, meta=None):
    """评测一个提交，返回 (score, details)。"""
    backend = choose_backend()
    if backend == 'scratchv_patch':
        return scratchv_patch.evaluate(submission_id, team_name, problem_id, code_path, meta)
    return stub.evaluate(submission_id, team_name, problem_id, code_path, meta)
