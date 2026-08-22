import os
import json
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from config import Config
from models import db, Submission
from tasks import add_task, start_worker
import shutil

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# 创建数据库表
with app.app_context():
    db.create_all()

# 启动后台 worker
start_worker()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit():
    team_name = request.form.get('team')
    problem_id = request.form.get('problem')
    file = request.files.get('code')

    if not all([team_name, problem_id, file]):
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)