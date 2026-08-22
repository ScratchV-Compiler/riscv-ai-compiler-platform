import threading
import queue
import time
from models import db, Submission
from evaluator import run_evaluation

task_queue = queue.Queue()
worker_thread = None

def start_worker():
    global worker_thread
    if worker_thread is None or not worker_thread.is_alive():
        worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        worker_thread.start()

def _worker_loop():
    while True:
        submission_id = task_queue.get()
        with app.app_context():  # 需要导入 app
            submission = Submission.query.get(submission_id)
            if submission is None:
                continue
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
        task_queue.task_done()

def add_task(submission_id):
    task_queue.put(submission_id)