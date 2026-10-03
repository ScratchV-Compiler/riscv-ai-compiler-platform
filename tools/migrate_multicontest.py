#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把**单场次**的旧库迁移成**多场次** schema（一次性）。

## 为什么需要脚本而不是靠 create_all

`db.create_all()` 只建缺失的表，**不会 ALTER 已有表**（见 models.py 的 SubmitThrottle
注释与 docs/08）。而且本次要把 `teams.name` 的全局 UNIQUE 改成 `(contest,name)`、
把 `team_members.user_id` 的唯一改成 `(user_id,contest)`——**SQLite 只能重建表才能改约束**，
`ADD COLUMN` 做不到。所以线上库必须显式迁移。

## 做了什么

- `submission`：加 `contest` 列（旧行填默认场次）+ 索引
- `teams`：加 `contest` 列，唯一约束由 `UNIQUE(name)` 改为 `UNIQUE(contest,name)`
- `team_members`：加 `contest` 列，唯一约束由 `UNIQUE(user_id)` 改为 `UNIQUE(user_id,contest)`
- `submit_throttle`：主键由 `user_id` 改为 `(user_id,contest)`（**节流状态可丢**，直接重建）

## 用法

    .venv/bin/python tools/migrate_multicontest.py                  # 只打印计划（dry-run）
    .venv/bin/python tools/migrate_multicontest.py --apply          # 先自动备份，再迁移
    .venv/bin/python tools/migrate_multicontest.py --apply --db X   # 指定库文件

## 安全约定

- **--apply 前自动备份**到 `<db>.bak-<时间戳>`（`--no-backup` 可跳过，不建议）
- 全程单事务 + `PRAGMA foreign_keys=OFF`；**迁移前后逐表行数必须一致**，否则回滚并非零退出
- **幂等**：已迁移过的库再跑只会报告「无需改动」，不会重复重建
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from contests import DEFAULT_SLUG  # noqa: E402


def _table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _columns(conn, table):
    return {r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _has_unique(conn, table, cols):
    """该表上是否存在**恰好等于** cols 集合的 UNIQUE 约束（按索引模拟）。"""
    want = set(cols)
    for idx in conn.execute(f'PRAGMA index_list({table})').fetchall():
        # idx: (seq, name, unique, origin, partial)
        if not idx[2]:
            continue
        got = [r[2] for r in conn.execute(f'PRAGMA index_info({idx[1]})').fetchall()]
        if set(got) == want and len(got) == len(want):
            return True
    return False


def _count(conn, table):
    return conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


def plan(conn):
    """返回需要执行的动作列表（字符串），空 = 无需迁移。"""
    tables = _table_names(conn)
    actions = []

    if 'submission' in tables and 'contest' not in _columns(conn, 'submission'):
        actions.append('submission: 加 contest 列 + 索引')

    if 'teams' in tables:
        tcols = _columns(conn, 'teams')
        if 'contest' not in tcols or not _has_unique(conn, 'teams', ('contest', 'name')):
            actions.append('teams: 重建表（加 contest；UNIQUE(name) → UNIQUE(contest,name)）')

    if 'team_members' in tables:
        mcols = _columns(conn, 'team_members')
        if 'contest' not in mcols or not _has_unique(conn, 'team_members', ('user_id', 'contest')):
            actions.append('team_members: 重建表（加 contest；UNIQUE(user_id) → UNIQUE(user_id,contest)）')

    if 'submit_throttle' in tables and 'contest' not in _columns(conn, 'submit_throttle'):
        actions.append('submit_throttle: 重建表（加 contest；主键 → (user_id,contest)，节流状态可丢）')

    return actions


def _rebuild_teams(conn):
    conn.execute(f'''
        CREATE TABLE teams_new (
            id INTEGER NOT NULL PRIMARY KEY,
            contest VARCHAR(40) NOT NULL DEFAULT '{DEFAULT_SLUG}',
            name VARCHAR(60) NOT NULL,
            invite_code VARCHAR(12) NOT NULL,
            captain_id INTEGER NOT NULL,
            created_at DATETIME,
            disbanded_at DATETIME,
            UNIQUE (contest, name),
            UNIQUE (invite_code),
            FOREIGN KEY(captain_id) REFERENCES users (id)
        )''')
    conn.execute(f'''
        INSERT INTO teams_new (id, contest, name, invite_code, captain_id, created_at, disbanded_at)
        SELECT id, '{DEFAULT_SLUG}', name, invite_code, captain_id, created_at, disbanded_at
        FROM teams''')
    conn.execute('DROP TABLE teams')
    conn.execute('ALTER TABLE teams_new RENAME TO teams')
    conn.execute('CREATE INDEX ix_teams_contest ON teams (contest)')


def _rebuild_team_members(conn):
    conn.execute(f'''
        CREATE TABLE team_members_new (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            contest VARCHAR(40) NOT NULL DEFAULT '{DEFAULT_SLUG}',
            team_id INTEGER NOT NULL,
            joined_at DATETIME,
            UNIQUE (user_id, contest),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(team_id) REFERENCES teams (id)
        )''')
    conn.execute(f'''
        INSERT INTO team_members_new (id, user_id, contest, team_id, joined_at)
        SELECT id, user_id, '{DEFAULT_SLUG}', team_id, joined_at FROM team_members''')
    conn.execute('DROP TABLE team_members')
    conn.execute('ALTER TABLE team_members_new RENAME TO team_members')
    conn.execute('CREATE INDEX ix_team_members_contest ON team_members (contest)')
    conn.execute('CREATE INDEX ix_team_members_team_id ON team_members (team_id)')


def _rebuild_submit_throttle(conn):
    """节流表只存「上次提交时间」，是短暂状态——重建时丢弃即可。
    最坏后果：某人能立刻再交一次，无实际影响。"""
    conn.execute('DROP TABLE submit_throttle')
    conn.execute(f'''
        CREATE TABLE submit_throttle (
            user_id INTEGER NOT NULL,
            contest VARCHAR(40) NOT NULL DEFAULT '{DEFAULT_SLUG}',
            last_at DATETIME NOT NULL,
            PRIMARY KEY (user_id, contest),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )''')


def _add_submission_column(conn):
    conn.execute(f"ALTER TABLE submission ADD COLUMN contest VARCHAR(40) "
                 f"NOT NULL DEFAULT '{DEFAULT_SLUG}'")
    conn.execute('CREATE INDEX ix_submission_contest ON submission (contest)')


def migrate(conn, actions):
    """在单事务里执行全部动作；任何异常由调用方回滚。"""
    conn.execute('PRAGMA foreign_keys=OFF')
    for a in actions:
        if a.startswith('submission:'):
            _add_submission_column(conn)
        elif a.startswith('teams:'):
            _rebuild_teams(conn)
        elif a.startswith('team_members:'):
            _rebuild_team_members(conn)
        elif a.startswith('submit_throttle:'):
            _rebuild_submit_throttle(conn)


def main():
    ap = argparse.ArgumentParser(description='单场次库 → 多场次 schema')
    ap.add_argument('--db', default=os.path.join(ROOT, 'platform.db'),
                    help='SQLite 库路径（默认 platform.db）')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--apply', action='store_true', help='写入（默认只 dry-run）')
    g.add_argument('--dry-run', action='store_true', help='只打印计划（默认行为）')
    ap.add_argument('--no-backup', action='store_true', help='--apply 时不自动备份（不建议）')
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f'库文件不存在：{args.db}')
        return 1

    conn = sqlite3.connect(args.db)
    try:
        actions = plan(conn)
        if not actions:
            print('无需迁移：schema 已是多场次版本。')
            return 0

        print(f'库：{args.db}')
        print('计划改动：')
        for a in actions:
            print('  -', a)

        # 迁移前后的行数基线（用于一致性校验）
        tables = [t for t in ('submission', 'teams', 'team_members')
                  if t in _table_names(conn)]
        before = {t: _count(conn, t) for t in tables}

        if not args.apply:
            print('\n（dry-run）加 --apply 才会写入。')
            return 0

        if not args.no_backup:
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            bak = f'{args.db}.bak-{stamp}'
            shutil.copy(args.db, bak)
            print(f'\n已备份到：{bak}')

        try:
            conn.execute('BEGIN')
            migrate(conn, actions)
            after = {t: _count(conn, t) for t in tables}
            if after != before:
                raise RuntimeError(f'行数不一致：{before} → {after}')
            conn.commit()
        except Exception as exc:                 # noqa: BLE001
            conn.rollback()
            print(f'\n迁移失败，已回滚：{exc}')
            return 1

        print('\n迁移完成。行数校验通过：')
        for t in tables:
            print(f'  {t}: {before[t]} 行')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
