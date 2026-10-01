import hashlib
import json
import os
import time

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_wtf.csrf import CSRFError

from flask_sqlalchemy import SQLAlchemy
import config
from config import Config
from models import (db, Submission, TERMINAL_VERDICTS, VERDICT_CSS,
                    VERDICT_LABELS)
from tasks import add_task, recover_stale_submissions, start_worker
from problems import (PROBLEMS, get_problem, is_contest, problem_ids,
                      submit_kind)
from standings import build_standings, last_reset_utc
from auth import bp as auth_bp, csrf, current_user, login_required, team_required
from seed import seed_demo_submissions, refresh_demo_submissions

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
csrf.init_app(app)
app.register_blueprint(auth_bp)

# 创建数据库表；表为空时导入 demo 数据；demo 数据过期则前移到当前结算窗口
with app.app_context():
    db.create_all()
    _seeded = seed_demo_submissions()
    if _seeded:
        print(f'[seed] 已从 data/demo_submissions.csv 导入 {_seeded} 条演示提交')
    _moved = refresh_demo_submissions()
    if _moved:
        print(f'[seed] 已将 {_moved} 条过期演示提交前移到当前结算窗口')
    _stale = recover_stale_submissions()
    if _stale:
        print(f'[worker] 已将 {_stale} 条中断的提交标记为 runtime_error')

# 启动后台 worker
start_worker(app)


@app.context_processor
def inject_globals():
    """模板全局：当前用户、赛道与 verdict 文案/徽章。"""
    return {
        'current_user': current_user(),
        'submit_kind': submit_kind(),
        'active_problem_set': config.get('active_problem_set'),
        'baseline_ref': Config.SCRATCHV_BASELINE_REF,
        'scoring_metric': Config.SCORING_METRIC,
        'VERDICT_LABELS': VERDICT_LABELS,
        'VERDICT_CSS': VERDICT_CSS,
    }


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _allowed_exts():
    return Config.UPLOAD_PATCH_EXT if submit_kind() == 'patch' else Config.UPLOAD_DEMO_EXT


def _quota_state(team):
    """返回 (used, limit, since)。"""
    since = last_reset_utc()
    used = Submission.query.filter(
        Submission.team_id == team.id, Submission.created_at >= since
    ).count()
    return used, Config.DAILY_QUOTA, since


def _read_text(path, limit=200_000):
    if not path or not os.path.exists(path):
        return ''
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            data = handle.read()
    except OSError:
        return ''
    return data if len(data) <= limit else data[:limit] + '\n…（内容过长，已截断）'


def _terminal(submission):
    return (submission.verdict in TERMINAL_VERDICTS) or submission.status == 'finished'


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
        'standings.html', problems=PROBLEMS, problem=problem, stage=stage,
        standings=data,
    )


@app.route('/help')
def help_page():
    return render_template('help.html', problems=PROBLEMS)


@app.route('/submit')
@team_required
def submit_page():
    user = current_user()
    team = user.team
    used, limit, _ = _quota_state(team)
    problem = request.args.get('problem') or (problem_ids()[0] if problem_ids() else '')
    return render_template(
        'submit.html', problems=PROBLEMS, problem=problem,
        quota={'used': used, 'limit': limit}, kind=submit_kind(),
    )


@app.route('/result/<int:submission_id>')
def result_page(submission_id):
    submission = db.session.get(Submission, submission_id)
    if submission is None:
        abort(404)
    return render_template(
        'result.html', submission=submission, tick=0,
        terminal=_terminal(submission), patch_text=_read_text(submission.code_path),
    )


# ---------------------------------------------------------------------------
# 片段路由（htmx）
# ---------------------------------------------------------------------------

@app.route('/frag/quota')
def frag_quota():
    user = current_user()
    if user is None or user.team is None:
        return render_template('fragments/quota.html', quota=None)
    used, limit, _ = _quota_state(user.team)
    return render_template('fragments/quota.html', quota={'used': used, 'limit': limit})


@app.route('/frag/result/<int:submission_id>')
def frag_result(submission_id):
    submission = db.session.get(Submission, submission_id)
    if submission is None:
        abort(404)
    tick = request.args.get('tick', 0, type=int)
    patch_text = _read_text(submission.code_path)
    return render_template(
        'fragments/result.html', submission=submission, tick=tick,
        terminal=_terminal(submission), patch_text=patch_text,
    )


@app.route('/frag/submit', methods=['POST'])
@team_required
def frag_submit():
    user = current_user()
    team = user.team
    problem_id = (request.form.get('problem') or '').strip()
    upload = request.files.get('patch') or request.files.get('code')

    def fail(message, status):
        return render_template('fragments/submit_feedback.html', ok=False,
                               message=message), status

    problem = get_problem(problem_id)
    if problem is None:
        return fail('请选择一道赛题。', 400)
    if upload is None or not upload.filename:
        return fail('请选择要上传的文件。', 400)

    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in _allowed_exts():
        allowed = '、'.join(_allowed_exts())
        return fail(f'文件类型不支持（{ext or "无扩展名"}），请上传：{allowed}。', 400)

    # 配额
    used, limit, since = _quota_state(team)
    if used >= limit:
        return fail(f'今日配额已用尽（{used}/{limit}），每日 05:00（UTC+8）后恢复。', 409)

    # 软限频：同队两次提交最小间隔
    last = (Submission.query.filter(Submission.team_id == team.id)
            .order_by(Submission.created_at.desc()).first())
    if last and (time.time() - last.created_at.timestamp()) < Config.SUBMIT_COOLDOWN:
        return fail('提交过于频繁，请稍候几秒再试。', 429)

    # 保存产物
    stamp = int(time.time())
    filename = f'sub_{team.id}_{problem_id}_{stamp}{ext}'
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    upload.save(save_path)
    with open(save_path, 'rb') as handle:
        sha = hashlib.sha256(handle.read()).hexdigest()

    submission = Submission(
        team_name=team.name,
        problem_id=problem_id,
        code_path=save_path,
        status='pending',
        team_id=team.id,
        user_id=user.id,
        source_name=upload.filename[:120],
        artifact_sha256=sha,
        baseline_ref=Config.SCRATCHV_BASELINE_REF if submit_kind() == 'patch' else None,
    )
    db.session.add(submission)
    db.session.commit()
    add_task(submission.id)

    return render_template(
        'fragments/submit_feedback.html', ok=True,
        submission=submission, quota={'used': used + 1, 'limit': limit},
    )


# ---------------------------------------------------------------------------
# 只读 API
# ---------------------------------------------------------------------------

@app.route('/api/problems')
def api_problems():
    return jsonify([
        {'id': p['id'], 'no': p['no'], 'code': p['code'], 'title': p['title'],
         'summary': p['summary'], 'full_score': 100}
        for p in PROBLEMS
    ])


@app.route('/api/quota')
def api_quota():
    user = current_user()
    if user is None:
        return jsonify({'error': '请先登录'}), 401
    if user.team is None:
        return jsonify({'used': 0, 'limit': Config.DAILY_QUOTA, 'reset_at': None})
    used, limit, _ = _quota_state(user.team)
    from auth import quota_payload
    return jsonify(quota_payload(user.team))


@app.route('/api/submissions')
def api_submissions():
    query = Submission.query
    team = request.args.get('team')
    if team:
        query = query.filter_by(team_name=team)
    problem = request.args.get('problem')
    if problem:
        query = query.filter_by(problem_id=problem)
    page = max(request.args.get('page', 1, type=int), 1)
    per_page = min(max(request.args.get('per_page', 20, type=int), 1), 100)
    total = query.count()
    items = (query.order_by(Submission.created_at.desc())
             .offset((page - 1) * per_page).limit(per_page).all())
    return jsonify({'total': total, 'page': page, 'items': [s.to_dict() for s in items]})


@app.route('/api/submit', methods=['POST'])
def submit():
    """旧契约（B1 沿用旧名）：登录 + 已入队，产物随 submitted 文件；带 CSRF。"""
    user = current_user()
    if user is None:
        return jsonify({'error': '请先登录'}), 401
    team = user.team
    if team is None:
        return jsonify({'error': '请先组建或加入队伍'}), 403

    problem_id = request.form.get('problem')
    file = request.files.get('code') or request.files.get('patch')
    if not problem_id or get_problem(problem_id) is None or file is None:
        return jsonify({'error': 'Missing fields'}), 400

    used, limit, _ = _quota_state(team)
    if used >= limit:
        return jsonify({'error': '今日配额已用尽'}), 409

    stamp = int(time.time())
    ext = os.path.splitext(file.filename or '')[1].lower() or '.dat'
    save_path = os.path.join(app.config['UPLOAD_FOLDER'],
                             f'sub_{team.id}_{problem_id}_{stamp}{ext}')
    file.save(save_path)
    with open(save_path, 'rb') as handle:
        sha = hashlib.sha256(handle.read()).hexdigest()

    submission = Submission(
        team_name=team.name, problem_id=problem_id, code_path=save_path,
        status='pending', team_id=team.id, user_id=user.id,
        source_name=(file.filename or '')[:120], artifact_sha256=sha,
        baseline_ref=Config.SCRATCHV_BASELINE_REF if submit_kind() == 'patch' else None,
    )
    db.session.add(submission)
    db.session.commit()
    add_task(submission.id)
    return jsonify({'submission_id': submission.id, 'verdict': None,
                    'status': 'pending', 'quota': {'used': used + 1, 'limit': limit}})


@app.route('/api/result/<int:submission_id>')
def get_result(submission_id):
    submission = db.session.get(Submission, submission_id)
    if not submission:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(submission.to_dict())


@app.route('/api/leaderboard/<problem_id>')
def leaderboard(problem_id):
    subs = (Submission.query
            .filter(Submission.problem_id == problem_id,
                    Submission.verdict == 'accepted')
            .order_by(Submission.score.desc()).limit(50).all())
    return jsonify([s.to_dict() for s in subs])


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


@app.errorhandler(CSRFError)
def csrf_error(_e):
    return render_template(
        'error.html', code=400, title='请求校验失败',
        detail='页面停留过久或登录态已过期，本次操作没有生效。'
    ), 400


@app.errorhandler(413)
def too_large(_e):
    return render_template(
        'error.html', code=413, title='文件过大',
        detail='上传文件超过大小限制，请精简后重试。'
    ), 413


@app.errorhandler(500)
def server_error(_e):
    return render_template(
        'error.html', code=500, title='服务器内部错误',
        detail='服务端没能处理这次请求。'
    ), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
