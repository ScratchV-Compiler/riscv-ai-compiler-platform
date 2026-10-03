import json
import os
import threading
import queue
from datetime import datetime, timedelta

from models import db, Submission
from evaluator import run_evaluation

task_queue = queue.Queue()
worker_threads = []
_app = None


def start_worker(flask_app):
    """启动后台 worker 池。传入 Flask app 以避免循环导入。

    评测是 CPU 密集的（编译 + qemu + 单步计数），worker 数不宜超过 CPU 数；
    SQLite 写又是串行的，所以默认取 min(2, cpu)。线程安全：多个 worker 共用
    同一个 Queue；Flask-SQLAlchemy 的 session 按线程隔离，各自 with app_context。
    """
    global _app
    _app = flask_app

    count = flask_app.config.get('WORKER_COUNT') or min(2, os.cpu_count() or 1)
    alive = [t for t in worker_threads if t.is_alive()]
    for _ in range(max(0, count - len(alive))):
        t = threading.Thread(target=_worker_loop, daemon=True)
        t.start()
        alive.append(t)
    worker_threads[:] = alive


def queue_depth():
    """当前排队中的任务数，供限流判断。"""
    return task_queue.qsize()


def reap_stale_running(app, minutes=None):
    """把卡在 running 的陈旧记录收尾，避免永久悬挂（worker 崩溃等情况）。

    正常路径下 evaluator 用 try/finally 保证一定写回终态，这里只是兜底。
    """
    minutes = minutes or app.config.get('STALE_RUNNING_MINUTES', 15)
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    with app.app_context():
        stale = Submission.query.filter(
            Submission.status == 'running',
            Submission.updated_at < cutoff,
        ).all()
        for sub in stale:
            sub.status = 'failed'
            sub.details = json.dumps({
                'verdict': 'internal_error',
                'error': 'internal_error',
                'message': '评测异常中断，请重新提交',
                'score': 0.0,
            }, ensure_ascii=False)
        if stale:
            db.session.commit()
            print(f'[reaper] 回收了 {len(stale)} 条卡在 running 的提交')
    return len(stale)


def _evaluate(submission_id):
    submission = Submission.query.get(submission_id)
    if submission is None:
        return
    # 更新状态为 running
    submission.status = 'running'
    db.session.commit()
    # 执行评测。contest 按提交所属场次取（旧库尚未加列时为 None → 默认场次）。
    score, details = run_evaluation(
        submission.id,
        submission.team_name,
        submission.problem_id,
        submission.code_path,
        contest=getattr(submission, 'contest', None),
    )
    # 更新结果
    submission.status = 'success' if details.get('error') is None else 'failed'
    submission.score = score
    submission.details = json.dumps(details)
    db.session.commit()


def _worker_loop():
    while True:
        submission_id = task_queue.get()
        try:
            with _app.app_context():
                _evaluate(submission_id)
        except Exception as e:                    # noqa: BLE001
            print(f"[worker] evaluation error for submission {submission_id}: {e}")
            # 兜底：绝不让提交卡在 running（evaluator 已 try/finally，这里是双保险）
            try:
                with _app.app_context():
                    sub = db.session.get(Submission, submission_id)
                    if sub is not None and sub.status not in ('success', 'failed'):
                        sub.status = 'failed'
                        sub.score = 0.0
                        sub.details = json.dumps({
                            'verdict': 'internal_error', 'error': 'internal_error',
                            'message': '评测异常中断，请重新提交', 'score': 0.0,
                        }, ensure_ascii=False)
                        db.session.commit()
            except Exception as inner:            # noqa: BLE001
                print(f"[worker] 无法写回提交 {submission_id}: {inner}")
        finally:
            task_queue.task_done()


def add_task(submission_id):
    task_queue.put(submission_id)
