# -*- coding: utf-8 -*-
"""启动时导入 demo / 初始数据（方案 B）。

运行时持久化仍走 SQLite；仅当 `submission` 表为空时，从 `data/demo_submissions.csv`
导入演示榜单数据。时间戳按「最近一次 05:00 结算点 + offset_minutes」落到当天窗口，
保证任何时候启动 demo 都有可展示的榜单，不会因数据过期而空榜。
"""
import csv
import math
import os
from datetime import timedelta

from config import DEMO_SUBMISSIONS_CSV
from models import db, Submission
from standings import last_reset_utc


def refresh_demo_submissions():
    """把已过期的演示数据整体前移到当前结算窗口。

    演示行以 `code_path == ''` 标识（真实提交一定会写入源码路径）。
    启动时若演示数据仍停留在更早的结算日，则整体按整天平移，保证 demo
    任何时候都有可展示的当日榜单；相对时间间隔不变，真实提交不受影响。
    返回被平移的行数（0 表示无需处理）。
    """
    demo = Submission.query.filter_by(code_path='').all()
    if not demo:
        return 0

    since = last_reset_utc()
    latest = max(s.created_at for s in demo)
    delta = since - latest
    if delta.total_seconds() <= 0:
        return 0

    days = math.ceil(delta.total_seconds() / 86400.0)
    shift = timedelta(days=days)
    for s in demo:
        s.created_at = s.created_at + shift
        s.updated_at = (s.updated_at or s.created_at) + shift
    db.session.commit()
    return len(demo)


def seed_demo_submissions():
    """表为空时从 CSV 导入演示提交；返回导入条数。"""
    if Submission.query.count() > 0:
        return 0
    if not os.path.exists(DEMO_SUBMISSIONS_CSV):
        return 0

    since = last_reset_utc()
    count = 0
    with open(DEMO_SUBMISSIONS_CSV, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            offset = int(row.get('offset_minutes') or 0)
            ts = since + timedelta(minutes=offset)
            db.session.add(Submission(
                team_name=(row.get('team_name') or '').strip(),
                problem_id=(row.get('problem_id') or '').strip(),
                code_path='',
                status=(row.get('status') or 'success').strip(),
                score=float(row.get('score') or 0),
                details='',
                created_at=ts,
                updated_at=ts,
            ))
            count += 1
    db.session.commit()
    return count
