import json
import queue
import threading
from datetime import datetime

from models import db, Submission
from evaluator import run_evaluation

task_queue = queue.Queue()
worker_thread = None
_app = None


def start_worker(flask_app):
    """启动后台 worker。传入 Flask app 以避免循环导入。"""
    global _app, worker_thread
    _app = flask_app
    if worker_thread is None or not worker_thread.is_alive():
        worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        worker_thread.start()


def recover_stale_submissions(reason='评测中断（服务重启），请重新提交。'):
    """启动时清理僵尸态：队列在内存中，重启后 pending/running 无法恢复。"""
    stuck = Submission.query.filter(Submission.status.in_(('pending', 'running'))).all()
    for sub in stuck:
        sub.status = 'finished'
        sub.verdict = 'runtime_error'
        details = sub.parsed_details()
        details.setdefault('backend', 'n/a')
        details['verdict'] = 'runtime_error'
        details['error'] = reason
        sub.details = json.dumps(details, ensure_ascii=False)
    if stuck:
        db.session.commit()
    return len(stuck)


def _evaluate(submission_id):
    submission = db.session.get(Submission, submission_id)
    if submission is None:
        return
    submission.status = 'running'
    db.session.commit()

    try:
        score, details = run_evaluation(
            submission.id,
            submission.team_name,
            submission.problem_id,
            submission.code_path,
        )
    except Exception as exc:  # noqa: BLE001 - 任何异常都必须落终态
        score, details = 0.0, {'verdict': 'runtime_error', 'error': f'评测异常：{exc}'}

    verdict = details.get('verdict') or 'runtime_error'
    submission.verdict = verdict
    submission.score = score or 0.0
    submission.status = 'finished'
    submission.details = json.dumps(details, ensure_ascii=False)
    db.session.commit()


def _worker_loop():
    while True:
        submission_id = task_queue.get()
        try:
            with _app.app_context():
                _evaluate(submission_id)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] evaluation error for submission {submission_id}: {e}")
        finally:
            task_queue.task_done()


def add_task(submission_id):
    task_queue.put(submission_id)
