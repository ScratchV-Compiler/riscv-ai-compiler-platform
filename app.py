import os
import time
import json
from flask import Flask, request, jsonify, render_template, abort

from flask_sqlalchemy import SQLAlchemy
from config import Config
from models import db, Submission
from tasks import add_task, start_worker
from problems import PROBLEMS, get_problem, problem_ids
from standings import build_standings

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# 创建数据库表
with app.app_context():
    db.create_all()

# 启动后台 worker
start_worker(app)


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
    return render_template('result.html')


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


@app.route('/api/submit', methods=['POST'])
def submit():
    team_name = request.form.get('team')
    problem_id = request.form.get('problem')
    file = request.files.get('code')

    if not team_name or not problem_id or file is None:
        return jsonify({'error': 'Missing fields'}), 400

    # 保存源码
    filename = f"{team_name}_{problem_id}_{int(time.time())}.py"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)

    # 创建提交记录
    submission = Submission(
        team_name=team_name,
        problem_id=problem_id,
        code_path=save_path,
        status='pending'
    )
    db.session.add(submission)
    db.session.commit()

    # 放入队列
    add_task(submission.id)

    return jsonify({'submission_id': submission.id, 'status': 'pending'})


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
