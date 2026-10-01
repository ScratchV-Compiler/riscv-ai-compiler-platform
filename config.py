# -*- coding: utf-8 -*-
"""平台配置加载器。

「可切换」的项统一放在仓根 `platform.yaml`，本模块负责：
  1. 读取 YAML 并与内置默认值深合并（缺项有兜底）；
  2. 支持环境变量覆盖（PLATFORM_<路径点转下划线大写>）；
  3. 暴露 `PLATFORM`（嵌套 dict）与 Flask 用的 `Config` 类。

改 `platform.yaml` 或环境变量后重启服务生效。
"""
import copy
import os
from datetime import timedelta
from typing import Any

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBMISSIONS_DIR = os.path.join(BASE_DIR, 'submissions')
TEST_DATA_DIR = os.path.join(BASE_DIR, 'test_data')
DATA_DIR = os.path.join(BASE_DIR, 'data')

os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
os.makedirs(TEST_DATA_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# demo / 初始数据（方案 B：运行时仍走 SQLite，仅演示数据来自 CSV）
DEMO_SUBMISSIONS_CSV = os.path.join(DATA_DIR, 'demo_submissions.csv')

# 配置文件路径（可用 PLATFORM_CONFIG 指定）
CONFIG_PATH = os.environ.get('PLATFORM_CONFIG') or os.path.join(BASE_DIR, 'platform.yaml')


# ---------------------------------------------------------------------------
# 内置默认值（platform.yaml 的最小兜底）
# ---------------------------------------------------------------------------

DEFAULTS = {
    'active_problem_set': 'demo',
    'quota': {'daily': 99, 'cooldown_seconds': 5},
    'upload': {
        'max_bytes': 2 * 1024 * 1024,
        'patch_ext': ['.patch', '.diff'],
        'demo_ext': ['.py'],
    },
    'judge': {
        'backend': 'auto',
        'uarch': 'basic',
        'max_instr': 50_000_000,
        'timeout_seconds': 120,
        'tol_lsb': 1,
    },
    'scratchv': {
        'root': '/root/Lab/ScratchV',
        'baseline_ref': '',
        'python': '/usr/bin/python3',
        'verify_tool': '',
        'compute_baseline': True,
        'patch': {'allow': [], 'deny': []},
    },
    'scoring': {'metric': 'cycles', 'policy': 'ratio_vs_baseline', 'cap': 100},
    'contest_problems': [],
}


def _deep_merge(base, override):
    """递归合并：override 覆盖 base，dict 逐层合并，其余类型直接替换。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_file(path):
    if not path or not os.path.exists(path):
        print(f'[config] 未找到配置文件 {path}，使用内置默认值')
        return {}
    with open(path, encoding='utf-8') as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        print(f'[config] 配置文件 {path} 顶层不是映射，已忽略')
        return {}
    return data


PLATFORM = _deep_merge(DEFAULTS, _load_file(CONFIG_PATH))


# ---------------------------------------------------------------------------
# 环境变量覆盖
# ---------------------------------------------------------------------------

_ENV_PATHS = [
    'active_problem_set',
    'quota.daily', 'quota.cooldown_seconds',
    'upload.max_bytes',
    'judge.backend', 'judge.uarch', 'judge.max_instr',
    'judge.timeout_seconds', 'judge.tol_lsb',
    'scratchv.root', 'scratchv.baseline_ref', 'scratchv.python',
    'scratchv.verify_tool', 'scratchv.compute_baseline',
    'scoring.metric', 'scoring.policy', 'scoring.cap',
]


def _coerce(current, raw):
    if isinstance(current, bool):
        return raw.strip().lower() in ('1', 'true', 'yes', 'on')
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    return raw


def _set_path(dotted, value):
    node = PLATFORM
    parts = dotted.split('.')
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _apply_env():
    for dotted in _ENV_PATHS:
        raw = os.environ.get('PLATFORM_' + dotted.upper().replace('.', '_'))
        if raw is None:
            continue
        current = get(dotted)
        try:
            _set_path(dotted, _coerce(current, raw))
        except (TypeError, ValueError):
            print(f'[config] 环境变量覆盖 {dotted}={raw!r} 解析失败，已忽略')


def get(dotted, default=None) -> Any:
    """按点号路径取配置值，如 get('judge.backend')。"""
    node = PLATFORM
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def resolve_path(value):
    """把配置里的相对路径解析为绝对路径（相对本仓根）。"""
    if not value:
        return value
    return value if os.path.isabs(value) else os.path.join(BASE_DIR, value)


_apply_env()


# ---------------------------------------------------------------------------
# Flask 配置
# ---------------------------------------------------------------------------

_DEFAULT_SECRET = 'dev-insecure-riscv-platform-key'
SECRET_KEY = os.environ.get('PLATFORM_SECRET_KEY') or _DEFAULT_SECRET
if SECRET_KEY == _DEFAULT_SECRET:
    print('[config] 警告：未设置 PLATFORM_SECRET_KEY，正在使用开发默认密钥，请勿用于生产。')


class Config:
    SECRET_KEY = SECRET_KEY
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'platform.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(get('upload.max_bytes'))
    UPLOAD_FOLDER = SUBMISSIONS_DIR

    # 评测超时（秒）
    EVAL_TIMEOUT = int(get('judge.timeout_seconds'))

    # ---- P2 身份与组队 ----
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)
    DAILY_QUOTA = int(get('quota.daily'))
    LOGIN_MAX_FAILURES = 5
    LOGIN_LOCK_SECONDS = 15 * 60

    # CSRF（Flask-WTF）
    WTF_CSRF_TIME_LIMIT = None
    WTF_CSRF_HEADERS = ['X-CSRFToken', 'X-CSRF-Token']

    # ---- P3 提交与结果（全部来自 platform.yaml，可切换）----
    ACTIVE_PROBLEM_SET = get('active_problem_set')
    JUDGE_BACKEND = get('judge.backend')
    JUDGE_UARCH = get('judge.uarch')
    JUDGE_MAX_INSTR = int(get('judge.max_instr'))
    JUDGE_TOL_LSB = int(get('judge.tol_lsb'))
    SUBMIT_COOLDOWN = int(get('quota.cooldown_seconds'))
    UPLOAD_PATCH_EXT = get('upload.patch_ext')
    UPLOAD_DEMO_EXT = get('upload.demo_ext')
    SCORING_METRIC = get('scoring.metric')
    SCORING_POLICY = get('scoring.policy')
    SCORING_CAP = int(get('scoring.cap'))
    SCRATCHV_ROOT = get('scratchv.root')
    SCRATCHV_BASELINE_REF = get('scratchv.baseline_ref')
    SCRATCHV_PYTHON = get('scratchv.python')
    SCRATCHV_VERIFY_TOOL = resolve_path(get('scratchv.verify_tool'))
    SCRATCHV_COMPUTE_BASELINE = bool(get('scratchv.compute_baseline'))
    PATCH_ALLOW = get('scratchv.patch.allow') or []
    PATCH_DENY = get('scratchv.patch.deny') or []
    CONTEST_PROBLEMS = get('contest_problems') or []


# 模块级常量，供 evaluator.py 等直接 from config import ...
EVAL_TIMEOUT = Config.EVAL_TIMEOUT
