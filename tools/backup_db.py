#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""平台数据备份：SQLite 一致性快照 + 提交源码打包 + 校验 + 轮转。

备份对象（缺一不可）：
  - `platform.db`     —— 账号、队伍、提交记录与成绩
  - `submissions/`    —— 选手上传的源码正文（**库里只存路径**，
                         只备份 db 的话成绩还在但再也无法重评）

**为什么不用 cp**：SQLite 在被写入时，文件可能处于「主文件已改、WAL/日志未落」
的中间状态，直接拷会得到损坏或过期的副本。这里用 SQLite 的在线备份 API
（`Connection.backup`），它会在备份过程中对源库加读锁并生成**事务一致**的快照，
服务无需停机。

用法：
    python tools/backup_db.py                     # 备份到默认目录
    python tools/backup_db.py --dest /mnt/bak    # 指定目录
    python tools/backup_db.py --keep 48          # 保留最近 N 份（默认 48）

产物（每次一组，时间戳为 UTC）：
    <ts>.db.gz             一致性快照
    <ts>.submissions.tar.gz 源码打包
    <ts>.manifest.json     校验信息（行数、sha256、大小）

注意：备份含**密码哈希**，产物一律 0600、目录 0700。异地存放前请先加密。
"""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, 'platform.db')
DEFAULT_SUBS = os.path.join(ROOT, 'submissions')
DEFAULT_DEST = '/var/backups/riscv-platform'


def log(msg):
    print(f'[backup] {msg}', flush=True)


def snapshot_db(src, dst):
    """用在线备份 API 生成一致性快照（源库可正在被写入）。"""
    src_conn = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def verify_snapshot(path):
    """校验快照可读且结构完整；返回统计信息。损坏则抛异常。"""
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError(f'快照完整性校验未通过: {integrity}')
        stats = {}
        for table in ('users', 'teams', 'team_members', 'submission'):
            row = conn.execute(
                "select count(*) from sqlite_master where type='table' and name=?",
                (table,)).fetchone()
            stats[table] = (conn.execute(f'select count(*) from {table}').fetchone()[0]
                            if row[0] else None)
        # 关键校验：库里引用的源码文件是否都在
        missing = []
        try:
            rows = conn.execute(
                "select code_path from submission "
                "where code_path is not null and code_path != ''").fetchall()
            for (p,) in rows:
                if p and not os.path.exists(p):
                    missing.append(p)
        except sqlite3.Error:
            pass
        stats['missing_source_files'] = missing
        return stats
    finally:
        conn.close()


def gzip_file(src, dst):
    with open(src, 'rb') as fi, gzip.open(dst, 'wb', compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def pack_submissions(subs_dir, dst_targz):
    """打包 submissions/；目录不存在或为空也要产出（空档位本身也是信息）。"""
    with tarfile.open(dst_targz, 'w:gz') as tar:
        if os.path.isdir(subs_dir):
            tar.add(subs_dir, arcname='submissions')
    n = sum(len(fs) for _, _, fs in os.walk(subs_dir)) if os.path.isdir(subs_dir) else 0
    return n


def rotate(dest, keep):
    """按时间戳保留最近 keep 份，删掉更早的（每次备份三个文件同属一组）。"""
    stamps = sorted({f.split('.')[0] for f in os.listdir(dest)
                     if f.endswith('.manifest.json')})
    removed = []
    for stamp in stamps[:-keep] if keep > 0 else []:
        for suffix in ('.db.gz', '.submissions.tar.gz', '.manifest.json'):
            p = os.path.join(dest, stamp + suffix)
            if os.path.exists(p):
                os.remove(p)
        removed.append(stamp)
    return removed


def main():
    ap = argparse.ArgumentParser(description='平台数据备份')
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--submissions', default=DEFAULT_SUBS)
    ap.add_argument('--dest', default=DEFAULT_DEST)
    ap.add_argument('--keep', type=int, default=48, help='保留最近 N 份（0=不轮转）')
    args = ap.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f'数据库不存在: {args.db}')

    os.makedirs(args.dest, mode=0o700, exist_ok=True)
    os.chmod(args.dest, 0o700)          # 含密码哈希，目录不许他人进入

    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')
    db_gz = os.path.join(args.dest, f'{stamp}.db.gz')
    sub_gz = os.path.join(args.dest, f'{stamp}.submissions.tar.gz')
    man = os.path.join(args.dest, f'{stamp}.manifest.json')

    tmpdir = tempfile.mkdtemp(prefix='backup_')
    try:
        raw = os.path.join(tmpdir, 'snapshot.db')
        log(f'生成一致性快照 {args.db}')
        snapshot_db(args.db, raw)
        stats = verify_snapshot(raw)
        log(f'校验通过: {stats}')
        gzip_file(raw, db_gz)

        n_src = pack_submissions(args.submissions, sub_gz)
        log(f'打包源码 {n_src} 个文件')

        manifest = {
            'created_utc': stamp,
            'db_source': args.db,
            'db_size_bytes': os.path.getsize(args.db),
            'db_gz_sha256': sha256(db_gz),
            'submissions_sha256': sha256(sub_gz),
            'source_files': n_src,
            'counts': stats,
        }
        with open(man, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        for p in (db_gz, sub_gz, man):
            os.chmod(p, 0o600)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if stats['missing_source_files']:
        log(f'⚠️ 有 {len(stats["missing_source_files"])} 个提交引用的源码文件已丢失：'
            f'{stats["missing_source_files"][:5]}')

    removed = rotate(args.dest, args.keep)
    if removed:
        log(f'轮转删除 {len(removed)} 份旧备份: {removed[:3]}{" …" if len(removed) > 3 else ""}')
    log(f'完成 -> {db_gz}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
