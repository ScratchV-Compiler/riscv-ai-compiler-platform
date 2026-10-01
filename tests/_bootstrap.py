# -*- coding: utf-8 -*-
"""测试共享引导：临时数据库 + 应用实例 + 结果收集。

**不引入 pytest**——本仓运行时依赖已经很克制，测试也不该拖进新依赖。
每个测试模块都能单独跑（`python tests/test_xxx.py`），也能被 `run_all.py` 汇总。

关键约定：
- 一律用**临时库**，绝不碰 `platform.db`（那是线上数据）
- 一律把 `WTF_CSRF_ENABLED` 关掉做功能测试；CSRF 本身由专项用例验证
- `check()` 收集结果，`report()` 打印汇总并返回退出码
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_PASS, _FAIL = [], []


def check(name, cond, detail=''):
    """记录一项断言。detail 只在需要时打印，便于定位失败。"""
    (_PASS if cond else _FAIL).append(name)
    mark = 'PASS' if cond else 'FAIL'
    line = f'[{mark}] {name}'
    if detail and (not cond or os.environ.get('VERBOSE')):
        line += f'  -> {detail}'
    print(line, flush=True)
    return bool(cond)


def report(title=''):
    """打印汇总；返回进程退出码（0 = 全过）。"""
    total = len(_PASS) + len(_FAIL)
    print(f'\n==== {len(_PASS)} passed, {len(_FAIL)} failed'
          f'{f"  ({title})" if title else ""} ====', flush=True)
    if _FAIL:
        print('失败项:', _FAIL, flush=True)
    return 1 if _FAIL else 0


def finish(title=''):
    """报告并退出——让每个测试模块都能独立运行。"""
    sys.exit(report(title))


def temp_app(**config_overrides):
    """建临时库、应用测试专用配置，导入并返回 Flask app。

    必须在**导入 app 之前**改 config —— `app.py` 在导入时就 `create_all()` 了。
    """
    os.chdir(ROOT)                      # app 内部有相对路径
    os.environ.setdefault('PLATFORM_SECRET_KEY', 'test-secret')

    tmp = tempfile.mkdtemp(prefix='riscv_test_')
    import config
    config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(tmp, 'test.db')
    config.Config.UPLOAD_FOLDER = os.path.join(tmp, 'submissions')
    os.makedirs(config.Config.UPLOAD_FOLDER, exist_ok=True)
    for k, v in config_overrides.items():
        setattr(config.Config, k, v)

    import app as appmod
    appmod.app.config['WTF_CSRF_ENABLED'] = False
    return appmod.app, tmp


def ref_src(problem_id):
    """参考解编译后的 .s 路径（由 tools/gen_baseline.py 生成）。"""
    import riscv_problems as RP
    return os.path.join(ROOT, RP.get_eval_spec(problem_id)['reference'].replace('.c', '.s'))


def clear_throttle(tmp):
    """清空提交间隔限流——测试里模拟「两分钟已过去」。

    提交间隔是 v1.15 加的功能，连续提交的测试必然撞上它。
    """
    import sqlite3
    con = sqlite3.connect(os.path.join(tmp, 'test.db'))
    con.execute('delete from submit_throttle')
    con.commit()
    con.close()
