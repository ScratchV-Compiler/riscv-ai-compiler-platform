import os
import time
import secrets
from flask import (Flask, request, jsonify, render_template, abort, flash,
                   redirect, url_for, g, Blueprint)

from config import Config
from models import db, Submission, Enrollment
from tasks import add_task, start_worker, queue_depth, reap_stale_running
from contests import (get_contest, default_contest, all_contests,
                      get_problem, contest_problems, contest_problem_ids,
                      submittable_problems, get_eval_spec, specs_for)
from riscv_problems import case_elements, case_label, case_purpose
from standings import build_standings, last_reset_utc, fmt_local
from scoring import build_score_table, parse_details
import riscv_runner
from auth import (bp as auth_bp, csrf, current_user, login_required,
                  api_login_required, submit_wait_seconds, mark_submitted,
                  format_wait, submission_rows, team_payload, quota_payload,
                  user_quota_used, create_team, join_team, leave_team,
                  restorable_team, restore_team, reset_invite_code,
                  transfer_captain, is_enrolled, enroll, unenroll)
from seed import seed_demo_submissions

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
csrf.init_app(app)
app.register_blueprint(auth_bp)          # 全局账号（登录/注册/找回密码）

# ---------------------------------------------------------------------------
# 场次蓝图：所有**场次相关**的页面/片段/队伍/API 都挂在 /c/<slug>/ 下。
# 账号相关路由保持全局（账号跨场次），留在 auth 蓝图。
# ---------------------------------------------------------------------------

contest_bp = Blueprint('contest', __name__, url_prefix='/c/<slug>')


@contest_bp.url_value_preprocessor
def _pull_contest(endpoint, values):
    """把 URL 里的 slug 解析成场次放进 g，并从视图参数里摘掉。

    未知 slug → 404。这样每个视图函数都不用自己收 slug 参数。
    """
    if values is None:
        return
    c = get_contest(values.pop('slug', None))
    if c is None:
        abort(404)
    g.contest = c


# 报名/取消报名**不受**「未开始进不去」的限制——报名恰恰要能在开赛前做
_ENROLL_ENDPOINTS = {'contest.enroll_page', 'contest.unenroll_page'}


@contest_bp.before_request
def _guard_contest_entry():
    """场次的**进入闸**：两道拦阻，未通过就看不到任何内容。

    1. **未开始**（`is_enterable`）→ 进不去；
    2. **需报名但未报名**（`requires_registration` 且未 `is_enrolled`）→ 也看不到内容。

    进行中/已结束且（无需报名或已报名）才放行。url_value_preprocessor 先于
    before_request 跑，所以这里一定能拿到 g.contest。
    例外：报名/取消报名（`_ENROLL_ENDPOINTS`）放行，否则没法报名。
    """
    c = getattr(g, 'contest', None)
    if c is None:
        return
    if request.endpoint in _ENROLL_ENDPOINTS:
        return
    user = current_user()
    enrolled = is_enrolled(user, c)          # 无需报名的场次恒为 True
    if not c.is_enterable:
        reason = 'not_started'
    elif c.requires_enrollment_to_view and not enrolled:
        reason = 'need_enroll'
    else:
        return
    if '/api/' in request.path:
        msg = (f'本场次（{c.title}）尚未开始，暂不开放' if reason == 'not_started'
               else f'本场次（{c.title}）需要先报名')
        return jsonify({'error': msg, 'reason': reason}), 403
    return render_template('contest_locked.html', contest=c, reason=reason,
                           enrolled=enrolled), 403


# 创建数据库表；表为空且开关打开时导入 demo 数据（方案 B）
with app.app_context():
    db.create_all()
    _seeded = seed_demo_submissions() if app.config['SEED_DEMO'] else 0
    if _seeded:
        print(f'[seed] 已从 data/demo_submissions.csv 导入 {_seeded} 条演示提交', flush=True)

# 启动后台 worker，并回收上次运行残留的卡死记录
start_worker(app)
reap_stale_running(app)
# 清扫上次运行残留的评测工作目录（进程被 kill 时 finally 不会执行，会残留）
_swept = riscv_runner.sweep_stale_workdirs(app.config['EVAL_WORK_ROOT'])
if _swept:
    print(f'[cleanup] 清理了 {_swept} 个陈旧的评测工作目录', flush=True)


@app.context_processor
def inject_context():
    """模板全局：当前用户 + **当前场次** + 绑定到该场次的评测规格查询。

    模板里调的 `eval_spec(p.id)` 因此自动对应当前场次，不必改模板源码。
    非场次页面（如 /contests、登录页）没有 g.contest，落到默认场次。
    """
    c = getattr(g, 'contest', None) or default_contest()
    return {
        'current_user': current_user(),
        'contest': c,
        # 是否**身在某场次内**（目录页/登录页为 False）——决定顶栏与右栏显不显示场次内容
        'in_contest': getattr(g, 'contest', None) is not None,
        'contests': all_contests(),
        'fmt_time': fmt_local,      # 朴素 UTC → UTC+8；None → 「—」（赛程用）
        'eval_spec': lambda pid: get_eval_spec(pid, c),
        'eval_specs': specs_for(c),
        'case_elements': case_elements,
        'case_label': case_label,
        'case_purpose': case_purpose,
    }


# ---------------------------------------------------------------------------
# 场次页面路由
# ---------------------------------------------------------------------------

@contest_bp.route('/')
def index():
    c = g.contest
    preview = build_standings(problem='all', contest=c.slug)
    preview['rows'] = preview['rows'][:5]
    return render_template('index.html', contest=c,
                           problems=contest_problems(c), standings_preview=preview)


@contest_bp.route('/problems')
def problems_page():
    return render_template('problems.html', problems=contest_problems(g.contest))


@contest_bp.route('/problems/<problem_id>')
def problem_page(problem_id):
    c = g.contest
    p = get_problem(c, problem_id)
    if p is None:
        abort(404)
    ids = contest_problem_ids(c)
    i = ids.index(problem_id)
    prev_p = get_problem(c, ids[i - 1]) if i > 0 else None
    next_p = get_problem(c, ids[i + 1]) if i + 1 < len(ids) else None
    return render_template('problem.html', p=p, prev_p=prev_p, next_p=next_p)


@contest_bp.route('/standings')
def standings_page():
    c = g.contest
    problem = request.args.get('problem', 'all')
    if problem not in contest_problem_ids(c):
        problem = 'all'
    stage = request.args.get('stage', 1, type=int)   # 历史参数，接受但忽略
    data = build_standings(problem=problem, stage=stage, contest=c.slug)
    return render_template(
        'standings.html',
        problems=contest_problems(c),
        problem=problem,
        stage=stage,
        standings=data,
    )


@contest_bp.route('/help')
def help_page():
    return render_template('help.html', problems=contest_problems(g.contest))


@contest_bp.route('/result/<int:submission_id>')
def result_page(submission_id):
    c = g.contest
    submission = db.session.get(Submission, submission_id)
    if submission is None or submission.contest != c.slug:
        abort(404)
    details = parse_details(submission)

    # 动态基准：与榜单用同一口径现算，避免结果页与榜单显示两个数。
    # 基准 = 当前窗口内**本场次**全场最优。
    live_score = None
    if details:
        window = Submission.query.filter(
            Submission.contest == c.slug,
            Submission.created_at >= last_reset_utc(),
            Submission.status.in_(('success',)),
        ).all()
        table, _best = build_score_table(window + [submission])
        live_score = table.get(submission.id)

    return render_template('result.html', submission=submission, details=details,
                           live_score=live_score)


# ---------------------------------------------------------------------------
# 场次只读 API
# ---------------------------------------------------------------------------

def _problems_payload(contest):
    return [
        {
            'id': p['id'],
            'contest': contest.slug,
            'no': p['no'],
            'code': p['code'],
            'title': p['title'],
            'summary': p['summary'],
            'full_score': (get_eval_spec(p['id'], contest) or {}).get('full_score'),
            'case_count': (get_eval_spec(p['id'], contest) or {}).get('case_count'),
        }
        for p in contest_problems(contest)
    ]


def _leaderboard_payload(contest, problem_id):
    subs = Submission.query.filter_by(
        contest=contest.slug, problem_id=problem_id, status='success'
    ).order_by(Submission.score.desc()).limit(50).all()
    return [s.to_dict() for s in subs]


@contest_bp.route('/api/problems')
def api_problems():
    return jsonify(_problems_payload(g.contest))


@contest_bp.route('/api/result/<int:submission_id>')
def get_result(submission_id):
    submission = db.session.get(Submission, submission_id)
    if not submission or submission.contest != g.contest.slug:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(submission.to_dict())


@contest_bp.route('/api/leaderboard/<problem_id>')
def leaderboard(problem_id):
    return jsonify(_leaderboard_payload(g.contest, problem_id))


# ---------------------------------------------------------------------------
# 场次提交
# ---------------------------------------------------------------------------

def _create_submission(user, contest, problem_id, file_storage, source_text=None):
    """校验并落库一次提交。返回 (submission, error_message, reason)。

    reason 为机器可读短码（None / 'rate_limited' / 'closed' / ...），调用方据此
    决定 HTTP 状态与提示方式；页面只看 error_message。

    按 D9 收紧：必须登录且已入队，队伍名只从登录态取，不再接受表单传入。
    源码有两种来源：上传的文件，或直接粘贴的文本；同时提供时以文件为准。
    """
    c = contest
    if not c.accepts_submissions:
        return None, f'本场次（{c.title}）{c.status_label}，当前不接受提交', 'closed'
    problem = get_problem(c, problem_id)
    if problem is None:
        return None, '赛题不存在', None
    spec = get_eval_spec(problem_id, c)
    if spec is None:
        return None, '该题暂未开放提交评测', None
    team = user.team_in(c.slug)
    if team is None:
        return None, '请先创建或加入一支队伍', None

    suffix = spec['file_suffix']
    uploaded = file_storage is not None and (file_storage.filename or '').strip()
    if uploaded:
        # 后缀校验只对上传文件有意义；粘贴的内容没有文件名
        if not file_storage.filename.lower().endswith(suffix):
            return None, f'文件类型不符，本赛题请提交 {suffix} 文件', None
        data = file_storage.read()
        origin = file_storage.filename
    elif (source_text or '').strip():
        data = source_text.encode('utf-8')
        origin = '（粘贴的代码）'
    else:
        return None, '请上传源码文件，或直接粘贴代码', None

    max_bytes = app.config['SUBMISSION_MAX_BYTES']
    if not data.strip():
        return None, '提交的源码是空的', None
    if len(data) > max_bytes:
        return None, f'源码过大（{len(data)} 字节，上限 {max_bytes} 字节）', None

    # 提交间隔限流：按选手计。**放在文件校验之后**——传错文件/后缀不对这类
    # 无效提交不该被罚等 2 分钟（它们是本地就能发现的问题）。
    wait = submit_wait_seconds(user, c)
    if wait:
        return None, f'提交过于频繁，请等待 {format_wait(wait)}后再试', 'rate_limited'

    quota = app.config['DAILY_QUOTA']
    used = user_quota_used(user, c)          # 配额**按人计**（换队不刷新）
    if used >= quota:
        return None, f'今日提交次数已用尽（{used}/{quota}）', None

    if queue_depth() >= app.config['MAX_QUEUE_DEPTH']:
        return None, '评测队列繁忙，请稍后重试', None

    # 文件名不含队名/题名，避免路径穿越与特殊字符问题
    filename = f"{int(time.time() * 1000)}_{secrets.token_hex(6)}{suffix}"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    with open(save_path, 'wb') as f:
        f.write(data)

    submission = Submission(
        contest=c.slug,
        user_id=user.id,                     # 配额按人计，须记提交人
        team_name=team.name,
        problem_id=problem_id,
        code_path=save_path,
        status='pending',
    )
    db.session.add(submission)
    db.session.commit()
    add_task(submission.id)
    mark_submitted(user, c)     # 成功提交才计时（按场次）
    return submission, None, None


@contest_bp.route('/submit', methods=['GET', 'POST'])
@login_required
def submit_page():
    c = g.contest
    user = current_user()
    team = user.team_in(c.slug)
    requested = request.values.get('problem')
    problem = get_problem(c, requested) if requested else None
    if problem is None or get_eval_spec(problem['id'], c) is None:
        # 默认落到本场第一道可提交的题（problems.py 里存的是 dict，不是对象）
        paper = contest_problems(c)
        problem = next((p for p in paper if get_eval_spec(p['id'], c)), paper[0])

    if request.method == 'GET':
        spec = get_eval_spec(problem['id'], c) or {}
        return render_template(
            'submit.html', problem=problem, team=team, spec=spec,
            problems=submittable_problems(c),   # 供页面上的赛题切换器
            suffix=spec.get('file_suffix', '.s'),
            entry_symbol=spec.get('entry_symbol', 'cnn_entry'),
            quota=quota_payload(user, c),   # 配额按人计
            wait_seconds=submit_wait_seconds(user, c),
            rate_limited=request.args.get('rate_limited') == '1',
            interval=app.config['SUBMIT_INTERVAL_SECONDS'],
            closed=not c.accepts_submissions,   # 未开始/已结束：只展示说明，不给提交表单
            # 提交页也放一份最近提交 —— 从别处回到本页时能直接点进评测详情，
            # 不必绕到「我的队伍」去翻
            recent=(submission_rows(
                Submission.query.filter_by(contest=c.slug, team_name=team.name)
                .order_by(Submission.created_at.desc()).limit(5).all())
                if team else []),
        )

    submission, err, reason = _create_submission(
        user, c, problem['id'], request.files.get('code'), request.form.get('source'))
    if err:
        flash(err, 'error')
        args = {'problem': problem['id']}
        if reason == 'rate_limited':
            args['rate_limited'] = 1        # 让页面弹出提示框
        return redirect(url_for('contest.submit_page', slug=c.slug, **args))
    flash(f'已提交 #{submission.id}，正在评测', 'success')
    return redirect(url_for('contest.result_page', slug=c.slug,
                            submission_id=submission.id))


def _redirect_back(default_endpoint='contests_page'):
    """报名类操作后回跳：优先回 `next`（只接受站内相对路径）。"""
    nxt = request.form.get('next') or request.args.get('next')
    if nxt and nxt.startswith('/') and not nxt.startswith('//'):
        return redirect(nxt)
    return redirect(url_for(default_endpoint))


@contest_bp.route('/enroll', methods=['POST'])
@login_required
def enroll_page():
    """个人报名（未开始的场次也能报——见入口闸的例外）。"""
    _, err = enroll(current_user(), g.contest, request.form.get('code'))
    flash(err or f'已报名「{g.contest.title}」', 'error' if err else 'success')
    return _redirect_back()


@contest_bp.route('/unenroll', methods=['POST'])
@login_required
def unenroll_page():
    _, err = unenroll(current_user(), g.contest)
    flash(err or f'已取消报名「{g.contest.title}」', 'error' if err else 'success')
    return _redirect_back()


def _api_submit(contest):
    """JSON 提交的共用实现（场次路由与旧 API 别名都用它）。"""
    user = current_user()
    if user is None:
        return jsonify({'error': '请先登录'}), 401
    payload = request.get_json(silent=True) or {}
    problem_id = request.form.get('problem') or payload.get('problem')
    source_text = request.form.get('source') or payload.get('source')
    submission, err, reason = _create_submission(
        user, contest, problem_id, request.files.get('code'), source_text)
    if err:
        status = 429 if reason == 'rate_limited' or '队列繁忙' in err else 400
        return jsonify({'error': err, 'reason': reason}), status
    return jsonify({'submission_id': submission.id, 'status': 'pending'}), 201


@contest_bp.route('/api/submit', methods=['POST'])
def submit():
    """JSON 提交接口。CSRF 由 Flask-WTF 全局校验（X-CSRFToken 头），按 D9 收紧为必须登录。"""
    return _api_submit(g.contest)


# ---------------------------------------------------------------------------
# 场次队伍（逻辑在 auth.py，路由在场次蓝图下）
# ---------------------------------------------------------------------------

@contest_bp.route('/team')
@login_required
def team_page():
    c = g.contest
    user = current_user()
    team = user.team_in(c.slug)
    my_subs = []
    if team:
        my_subs = (Submission.query
                   .filter_by(contest=c.slug, team_name=team.name)
                   .order_by(Submission.created_at.desc())
                   .limit(20).all())   # 经 submission_rows() 整理后再传给模板
    return render_template(
        'team.html', user=user, team=team,
        members=[m.user for m in team.members] if team else [],
        quota=quota_payload(user, c),
        submissions=submission_rows(my_subs),
    )


@contest_bp.route('/team/join')
@login_required
def team_join_page():
    c = g.contest
    user = current_user()
    if user.team_in(c.slug):
        return redirect(url_for('contest.team_page', slug=c.slug))
    return render_template('team_join.html', user=user,
                           restorable=restorable_team(user, c),
                           closed=not c.is_open,
                           needs_enroll=c.requires_registration and not is_enrolled(user, c))


@contest_bp.route('/team/restore', methods=['POST'])
@login_required
def team_restore_page():
    c = g.contest
    team, err = restore_team(current_user(), c)
    if err:
        flash(err, 'error')
        return redirect(url_for('contest.team_join_page', slug=c.slug))
    flash(f'已恢复队伍「{team.name}」，邀请码已更新为 {team.invite_code}', 'success')
    return redirect(url_for('contest.team_page', slug=c.slug))


@contest_bp.route('/team/create', methods=['POST'])
@login_required
def team_create_page():
    c = g.contest
    _, err = create_team(current_user(), c, request.form.get('name'))
    flash(err or '队伍创建成功', 'error' if err else 'success')
    return redirect(url_for('contest.team_page', slug=c.slug))


@contest_bp.route('/team/join', methods=['POST'])
@login_required
def team_join_submit():
    c = g.contest
    _, err = join_team(current_user(), c, request.form.get('invite_code'))
    flash(err or '入队成功', 'error' if err else 'success')
    return redirect(url_for('contest.team_page', slug=c.slug))


@contest_bp.route('/team/leave', methods=['POST'])
@login_required
def team_leave_page():
    c = g.contest
    _, err = leave_team(current_user(), c)
    flash(err or '已退出队伍', 'error' if err else 'success')
    return redirect(url_for('contest.team_page', slug=c.slug))


@contest_bp.route('/team/reset-code', methods=['POST'])
@login_required
def team_reset_code_page():
    c = g.contest
    _, err = reset_invite_code(current_user(), c)
    flash(err or '邀请码已重置', 'error' if err else 'success')
    return redirect(url_for('contest.team_page', slug=c.slug))


@contest_bp.route('/team/transfer', methods=['POST'])
@login_required
def team_transfer_page():
    c = g.contest
    _, err = transfer_captain(current_user(), c, request.form.get('to_user_id'))
    flash(err or '队长已转让', 'error' if err else 'success')
    return redirect(url_for('contest.team_page', slug=c.slug))


@contest_bp.route('/api/me')
@api_login_required
def api_me():
    c = g.contest
    user = current_user()
    team = user.team_in(c.slug)
    return jsonify({
        'user': user.to_dict(),
        'contest': c.slug,
        'team': team_payload(team, with_members=True),
        'quota': quota_payload(user, c),
    })


def _api_team_create(contest):
    team, err = create_team(current_user(), contest,
                            (request.get_json(silent=True) or request.form).get('name'))
    if err:
        return jsonify({'error': err}), 409
    return jsonify({'team': team_payload(team, with_members=True)}), 201


def _api_team_join(contest):
    data = request.get_json(silent=True) or request.form
    team, err = join_team(current_user(), contest, data.get('invite_code'))
    if err:
        status = 404 if '无效' in err else (410 if '已满' in err else 409)
        return jsonify({'error': err}), status
    return jsonify({'team': team_payload(team, with_members=True)}), 200


def _api_team_leave(contest):
    _, err = leave_team(current_user(), contest)
    if err:
        return jsonify({'error': err}), 409
    return '', 204


@contest_bp.route('/api/team', methods=['POST'])
@api_login_required
def api_team_create():
    return _api_team_create(g.contest)


@contest_bp.route('/api/team/join', methods=['POST'])
@api_login_required
def api_team_join():
    return _api_team_join(g.contest)


@contest_bp.route('/api/team/leave', methods=['POST'])
@api_login_required
def api_team_leave():
    return _api_team_leave(g.contest)


# ---------------------------------------------------------------------------
# htmx 片段
# ---------------------------------------------------------------------------

@contest_bp.route('/frag/standings')
def frag_standings():
    c = g.contest
    problem = request.args.get('problem', 'all')
    if problem not in contest_problem_ids(c):
        problem = 'all'
    stage = request.args.get('stage', 1, type=int)
    limit = request.args.get('limit', type=int)

    data = build_standings(problem=problem, stage=stage, contest=c.slug)
    if limit and limit > 0:
        data = dict(data, rows=data['rows'][:limit])
    return render_template('fragments/standings.html', standings=data)


# ---------------------------------------------------------------------------
# 场次目录（全局页）
# ---------------------------------------------------------------------------

# 蓝图必须在**所有** contest_bp 路由定义完之后才能注册（Flask 约束）
app.register_blueprint(contest_bp)


@app.route('/')
@app.route('/contests')
def contests_page():
    """**最外层**：场次目录。`/` 就是这里——先选赛事，再进门。

    同时把「我报了哪些名」带出去，供每场显示 报名 / 已报名 / 无需报名。
    """
    user = current_user()
    enrolled_slugs = set()
    if user is not None:
        enrolled_slugs = {e.contest for e in
                          Enrollment.query.filter_by(user_id=user.id).all()}
    return render_template('contests.html', contests=all_contests(),
                           default_contest=default_contest(),
                           enrolled_slugs=enrolled_slugs)


# ---------------------------------------------------------------------------
# 旧 URL 兼容：页面 302/307 到默认场次；API 原地委派（不重定向，免得打断 JSON 客户端）
# ---------------------------------------------------------------------------

def _to_default(endpoint, **values):
    return redirect(url_for(endpoint, slug=default_contest().slug, **values), 302)


@app.route('/problems')
def legacy_problems():
    return _to_default('contest.problems_page')


@app.route('/problems/<problem_id>')
def legacy_problem(problem_id):
    return _to_default('contest.problem_page', problem_id=problem_id)


@app.route('/standings')
def legacy_standings():
    return _to_default('contest.standings_page', **request.args)


@app.route('/help')
def legacy_help():
    return _to_default('contest.help_page')


@app.route('/result/<int:submission_id>')
def legacy_result(submission_id):
    return _to_default('contest.result_page', submission_id=submission_id)


@app.route('/frag/standings')
def legacy_frag_standings():
    return _to_default('contest.frag_standings', **request.args)


@app.route('/submit', methods=['GET', 'POST'])
def legacy_submit():
    # 307：保住方法与请求体，POST 提交不会在重定向后变成 GET
    return redirect(url_for('contest.submit_page', slug=default_contest().slug,
                            **request.args), 307)


@app.route('/team')
def legacy_team():
    return _to_default('contest.team_page')


@app.route('/team/join')
def legacy_team_join():
    return _to_default('contest.team_join_page')


@app.route('/team/create', methods=['POST'])
def legacy_team_create():
    return redirect(url_for('contest.team_create_page',
                            slug=default_contest().slug), 307)


@app.route('/team/leave', methods=['POST'])
def legacy_team_leave():
    return redirect(url_for('contest.team_leave_page',
                            slug=default_contest().slug), 307)


@app.route('/team/restore', methods=['POST'])
def legacy_team_restore():
    return redirect(url_for('contest.team_restore_page',
                            slug=default_contest().slug), 307)


@app.route('/team/reset-code', methods=['POST'])
def legacy_team_reset_code():
    return redirect(url_for('contest.team_reset_code_page',
                            slug=default_contest().slug), 307)


@app.route('/team/transfer', methods=['POST'])
def legacy_team_transfer():
    return redirect(url_for('contest.team_transfer_page',
                            slug=default_contest().slug), 307)


@app.route('/api/problems')
def legacy_api_problems():
    return jsonify(_problems_payload(default_contest()))


@app.route('/api/result/<int:submission_id>')
def legacy_get_result(submission_id):
    submission = db.session.get(Submission, submission_id)
    if not submission:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(submission.to_dict())


@app.route('/api/leaderboard/<problem_id>')
def legacy_leaderboard(problem_id):
    return jsonify(_leaderboard_payload(default_contest(), problem_id))


@app.route('/api/me')
@api_login_required
def legacy_api_me():
    c = default_contest()
    user = current_user()
    team = user.team_in(c.slug)
    return jsonify({
        'user': user.to_dict(),
        'contest': c.slug,
        'team': team_payload(team, with_members=True),
        'quota': quota_payload(user, c),
    })


@app.route('/api/submit', methods=['POST'])
def legacy_submit_api():
    return _api_submit(default_contest())


@app.route('/api/team', methods=['POST'])
@api_login_required
def legacy_api_team_create():
    return _api_team_create(default_contest())


@app.route('/api/team/join', methods=['POST'])
@api_login_required
def legacy_api_team_join():
    return _api_team_join(default_contest())


@app.route('/api/team/leave', methods=['POST'])
@api_login_required
def legacy_api_team_leave():
    return _api_team_leave(default_contest())


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
