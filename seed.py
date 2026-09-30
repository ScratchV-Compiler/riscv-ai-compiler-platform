# -*- coding: utf-8 -*-
"""启动时导入 demo / 初始数据（方案 B）。

运行时持久化仍走 SQLite；仅当 `submission` 表为空时，从 `data/demo_submissions.csv`
导入演示榜单数据。时间戳按「最近一次 05:00 结算点 + offset_minutes」落到当天窗口，
保证任何时候启动 demo 都有可展示的榜单，不会因数据过期而空榜。
"""
import csv
import os
from datetime import timedelta

from config import DEMO_SUBMISSIONS_CSV
from models import db, Submission
from standings import last_reset_utc


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
