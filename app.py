import os
import time
import json
import secrets
from flask import (Flask, request, jsonify, render_template, abort, flash,
                   redirect, url_for)

from flask_sqlalchemy import SQLAlchemy
from config import Config
from models import db, Submission
from tasks import add_task, start_worker, queue_depth, reap_stale_running
from problems import PROBLEMS, get_problem, problem_ids
from riscv_problems import get_eval_spec
from standings import build_standings, last_reset_utc
from auth import bp as auth_bp, csrf, current_user, login_required
from seed import seed_demo_submissions

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
csrf.init_app(app)
app.register_blueprint(auth_bp)

# 创建数据库表，并在表为空时导入 demo 数据（方案 B）
with app.app_context():
    db.create_all()
    _seeded = seed_demo_submissions()
    if _seeded:
        print(f'[seed] 已从 data/demo_submissions.csv 导入 {_seeded} 条演示提交')

# 启动后台 worker，并回收上次运行残留的卡死记录
start_worker(app)
reap_stale_running(app)


@app.context_processor
def inject_current_user():
    """模板全局：current_user（未登录为 None）。"""
    return {'current_user': current_user()}


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    preview = build_standings(problem='all', stage=1)
    preview['rows'] = preview['rows'][:5]
    return render_template('index.html', problems=PROBLEMS, standings_preview=preview)


@app.route('/problems')
def problems_page():
    return render_template('problems.html', problems=PROBLEMS)


@app.route('/problems/<problem_id>')
def problem_page(problem_id):
    p = get_problem(problem_id)
    if p is None:
        abort(404)
    ids = problem_ids()
    i = ids.index(problem_id)
    prev_p = get_problem(ids[i - 1]) if i > 0 else None
    next_p = get_problem(ids[i + 1]) if i + 1 < len(ids) else None
    return render_template('problem.html', p=p, prev_p=prev_p, next_p=next_p)


@app.route('/standings')
def standings_page():
    problem = request.args.get('problem', 'all')
    if problem not in problem_ids():
        problem = 'all'
    stage = request.args.get('stage', 1, type=int)
    data = build_standings(problem=problem, stage=stage)
    return render_template(
        'standings.html',
        problems=PROBLEMS,
        problem=problem,
        stage=stage,
        standings=data,
    )


@app.route('/help')
def help_page():
    return render_template('help.html', problems=PROBLEMS)


@app.route('/result/<int:submission_id>')
def result_page(submission_id):
    submission = db.session.get(Submission, submission_id)
    if submission is None:
        abort(404)
    details = None
    if submission.details:
        try:
            details = json.loads(submission.details)
        except ValueError:
            details = None
    return render_template('result.html', submission=submission, details=details)


# ---------------------------------------------------------------------------
# 只读 API
# ---------------------------------------------------------------------------

@app.route('/api/problems')
def api_problems():
    return jsonify([
        {
            'id': p['id'],
            'no': p['no'],
            'code': p['code'],
            'title': p['title'],
            'summary': p['summary'],
            'full_score': 100,
        }
        for p in PROBLEMS
    ])


def _team_quota_used(team_name):
    """本队当日（自上次 05:00 结算起）的提交次数。"""
    return Submission.query.filter(
        Submission.team_name == team_name,
        Submission.created_at >= last_reset_utc(),
    ).count()


def _create_submission(user, problem_id, file_storage, source_text=None):
    """校验并落库一次提交。返回 (submission, error_message)。

    按 D9 收紧：必须登录且已入队，队伍名只从登录态取，不再接受表单传入。
    源码有两种来源：上传的文件，或直接粘贴的文本；同时提供时以文件为准。
    """
    problem = get_problem(problem_id)
    if problem is None:
        return None, '赛题不存在'
    spec = get_eval_spec(problem_id)
    if spec is None:
        return None, '该题暂未开放提交评测'
    if user.team is None:
        return None, '请先创建或加入一支队伍'

    suffix = spec['file_suffix']
    uploaded = file_storage is not None and (file_storage.filename or '').strip()
    if uploaded:
        # 后缀校验只对上传文件有意义；粘贴的内容没有文件名
        if not file_storage.filename.lower().endswith(suffix):
            return None, f'文件类型不符，本赛题请提交 {suffix} 文件'
        data = file_storage.read()
        origin = file_storage.filename
    elif (source_text or '').strip():
        data = source_text.encode('utf-8')
        origin = '（粘贴的代码）'
    else:
        return None, '请上传源码文件，或直接粘贴代码'

    max_bytes = app.config['SUBMISSION_MAX_BYTES']
    if not data.strip():
        return None, '提交的源码是空的'
    if len(data) > max_bytes:
        return None, f'源码过大（{len(data)} 字节，上限 {max_bytes} 字节）'

    quota = app.config['DAILY_QUOTA']
    used = _team_quota_used(user.team.name)
    if used >= quota:
        return None, f'今日提交次数已用尽（{used}/{quota}）'

    if queue_depth() >= app.config['MAX_QUEUE_DEPTH']:
        return None, '评测队列繁忙，请稍后重试'

    # 文件名不含队名/题名，避免路径穿越与特殊字符问题
    filename = f"{int(time.time() * 1000)}_{secrets.token_hex(6)}{suffix}"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    with open(save_path, 'wb') as f:
        f.write(data)

    submission = Submission(
        team_name=user.team.name,
        problem_id=problem_id,
        code_path=save_path,
        status='pending',
    )
    db.session.add(submission)
    db.session.commit()
    add_task(submission.id)
    return submission, None


@app.route('/submit', methods=['GET', 'POST'])
@login_required
def submit_page():
    user = current_user()
    requested = request.values.get('problem')
    problem = get_problem(requested) if requested else None
    if problem is None or get_eval_spec(problem['id']) is None:
        # 默认落到第一道可提交的题（problems.py 里存的是 dict，不是对象）
        problem = next((p for p in PROBLEMS if get_eval_spec(p['id'])), PROBLEMS[0])

    if request.method == 'GET':
        spec = get_eval_spec(problem['id']) or {}
        team = user.team
        return render_template(
            'submit.html', problem=problem, team=team,
            suffix=spec.get('file_suffix', '.s'),
            entry_symbol=spec.get('entry_symbol', 'cnn_entry'),
            quota={'used': _team_quota_used(team.name) if team else 0,
                   'limit': app.config['DAILY_QUOTA']},
        )

    submission, err = _create_submission(
        user, problem['id'], request.files.get('code'), request.form.get('source'))
    if err:
        flash(err, 'error')
        return redirect(url_for('submit_page', problem=problem['id']))
    flash(f'已提交 #{submission.id}，正在评测', 'success')
    return redirect(url_for('result_page', submission_id=submission.id))


@app.route('/api/submit', methods=['POST'])
def submit():
    """JSON 提交接口。CSRF 由 Flask-WTF 全局校验（X-CSRFToken 头），按 D9 收紧为必须登录。"""
    user = current_user()
    if user is None:
        return jsonify({'error': '请先登录'}), 401
    payload = request.get_json(silent=True) or {}
    problem_id = request.form.get('problem') or payload.get('problem')
    source_text = request.form.get('source') or payload.get('source')
    submission, err = _create_submission(user, problem_id, request.files.get('code'), source_text)
    if err:
        status = 429 if '队列繁忙' in err else 400
        return jsonify({'error': err}), status
    return jsonify({'submission_id': submission.id, 'status': 'pending'}), 201


@app.route('/api/result/<int:submission_id>')
def get_result(submission_id):
    submission = Submission.query.get(submission_id)
    if not submission:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(submission.to_dict())


@app.route('/api/leaderboard/<problem_id>')
def leaderboard(problem_id):
    subs = Submission.query.filter_by(problem_id=problem_id, status='success')\
                           .order_by(Submission.score.desc()).limit(50).all()
    return jsonify([s.to_dict() for s in subs])


# ---------------------------------------------------------------------------
# htmx 片段（返回 text/html）
# ---------------------------------------------------------------------------

@app.route('/frag/standings')
def frag_standings():
    problem = request.args.get('problem', 'all')
    if problem not in problem_ids():
        problem = 'all'
    stage = request.args.get('stage', 1, type=int)
    limit = request.args.get('limit', type=int)

    data = build_standings(problem=problem, stage=stage)
    if limit and limit > 0:
        data = dict(data, rows=data['rows'][:limit])
    return render_template('fragments/standings.html', standings=data)


# ---------------------------------------------------------------------------
# 错误页
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_e):
    return render_template(
        'error.html', code=404, title='页面不存在',
        detail='这个地址没有对应的页面。'
    ), 404


@app.errorhandler(500)
def server_error(_e):
    return render_template(
        'error.html', code=500, title='服务器内部错误',
        detail='服务端没能处理这次请求。'
    ), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
