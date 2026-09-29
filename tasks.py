import json
import threading
import queue
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


def _evaluate(submission_id):
    submission = Submission.query.get(submission_id)
    if submission is None:
        return
    # 更新状态为 running
    submission.status = 'running'
    db.session.commit()
    # 执行评测
    score, details = run_evaluation(
        submission.id,
        submission.team_name,
        submission.problem_id,
        submission.code_path
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
        except Exception as e:
            print(f"[worker] evaluation error for submission {submission_id}: {e}")
        finally:
            task_queue.task_done()


def add_task(submission_id):
    task_queue.put(submission_id)
