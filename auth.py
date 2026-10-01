# -*- coding: utf-8 -*-
"""P2 身份与组队：注册 / 登录 / 退出 / 建队 / 入队 / 退队。

- 会话：Flask 内置 session（签名 cookie），写 session['uid']。
- CSRF：Flask-WTF CSRFProtect（决策 D6），页面表单带 csrf_token()，API 走 X-CSRFToken 头。
- 限频：内存计数，同一邮箱连续失败 N 次锁定一段时间。
- 存储：SQLite（方案 B）；demo 榜单数据另见 data/demo_submissions.csv。
"""
import functools
import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta

from flask import (Blueprint, current_app, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_wtf.csrf import CSRFProtect

import mailer
from models import (db, User, Team, TeamMember, Submission, PasswordReset,
                    SubmitThrottle, TEAM_MAX_SIZE)
from standings import last_reset_utc

bp = Blueprint('auth', __name__)
csrf = CSRFProtect()

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
STUDENT_RE = re.compile(r'^\d{6,12}$')
_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # 去掉易混的 0/O/1/I/L

# 登录失败限频：email -> {'count': int, 'until': ts}
_failures = {}

# 「找回密码」申请限频：email -> {'count': int, 'window_start': ts}（固定窗口）
_reset_requests = {}


# ---------------------------------------------------------------------------
# 当前用户与装饰器
# ---------------------------------------------------------------------------

def current_user():
    if 'user' not in g:
        uid = session.get('uid')
        g.user = db.session.get(User, uid) if uid else None
    return g.user


def _login_session(user):
    session.clear()
    session['uid'] = user.id
    session.permanent = True


def login_required(view):
    """页面用：未登录跳转 /login?next=…"""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for('auth.login_page', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def api_login_required(view):
    """API 用：未登录返回 401。"""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return jsonify({'error': '请先登录'}), 401
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# 登录限频
# ---------------------------------------------------------------------------

def login_locked_seconds(email):
    rec = _failures.get((email or '').strip().lower())
    if not rec:
        return 0
    remain = rec.get('until', 0) - time.time()
    return int(remain) if remain > 0 else 0


def _record_failure(email):
    key = (email or '').strip().lower()
    rec = _failures.setdefault(key, {'count': 0, 'until': 0})
    rec['count'] += 1
    if rec['count'] >= current_app.config['LOGIN_MAX_FAILURES']:
        rec['until'] = time.time() + current_app.config['LOGIN_LOCK_SECONDS']


def _clear_failures(email):
    _failures.pop((email or '').strip().lower(), None)


def reset_request_retry_after(email):
    """窗口内申请次数已用尽时返回还需等待的秒数；0 表示可以申请。"""
    rec = _reset_requests.get((email or '').strip().lower())
    if not rec:
        return 0
    now = time.time()
    window = current_app.config['RESET_WINDOW_SECONDS']
    elapsed = now - rec['window_start']
    if elapsed >= window or rec['count'] < current_app.config['RESET_MAX_REQUESTS']:
        return 0
    return int(window - elapsed) + 1


def _record_reset_request(email):
    key = (email or '').strip().lower()
    now = time.time()
    window = current_app.config['RESET_WINDOW_SECONDS']
    rec = _reset_requests.get(key)
    if rec is None or now - rec['window_start'] >= window:
        rec = {'count': 0, 'window_start': now}
        _reset_requests[key] = rec
    rec['count'] += 1


# ---------------------------------------------------------------------------
# 提交间隔限流（每选手两次成功提交之间至少间隔 N 秒）
# ---------------------------------------------------------------------------

def submit_wait_seconds(user):
    """还需要等多少秒才能再次提交；0 表示可以提交。"""
    rec = db.session.get(SubmitThrottle, user.id)
    if rec is None:
        return 0
    interval = current_app.config['SUBMIT_INTERVAL_SECONDS']
    elapsed = (datetime.utcnow() - rec.last_at).total_seconds()
    remain = interval - elapsed
    return int(remain) + 1 if remain > 0 else 0


def mark_submitted(user):
    """记录一次成功提交的时间。**只在提交成功时调用**——
    传错文件、后缀不对这类无效提交不该消耗间隔。"""
    now = datetime.utcnow()
    rec = db.session.get(SubmitThrottle, user.id)
    if rec is None:
        db.session.add(SubmitThrottle(user_id=user.id, last_at=now))
    else:
        rec.last_at = now
    db.session.commit()


def format_wait(seconds):
    """把等待秒数说成人话：90 → 「1 分 30 秒」。"""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f'{seconds} 秒'
    m, s = divmod(seconds, 60)
    return f'{m} 分 {s} 秒' if s else f'{m} 分钟'


# ---------------------------------------------------------------------------
# 业务逻辑（页面与 API 共用）
# ---------------------------------------------------------------------------

def create_user(data):
    email = (data.get('email') or '').strip().lower()
    name = (data.get('name') or '').strip()
    password = data.get('password') or ''
    student_id = (data.get('student_id') or '').strip() or None

    if not EMAIL_RE.match(email):
        return None, '邮箱格式不对'
    if not (1 <= len(name) <= 40):
        return None, '请填写真实姓名（1–40 字）'
    if len(password) < 8:
        return None, '密码至少 8 位'
    if student_id and not STUDENT_RE.match(student_id):
        return None, '学号格式不对，应为 6–12 位数字'
    if User.query.filter_by(email=email).first():
        return None, '该邮箱已注册'
    if student_id and User.query.filter_by(student_id=student_id).first():
        return None, '该学号已注册'

    user = User(email=email, name=name, student_id=student_id)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user, None


def authenticate(email, password):
    email = (email or '').strip().lower()
    user = User.query.filter_by(email=email).first()
    if user is None or not user.check_password(password or ''):
        _record_failure(email)
        return None, '邮箱或密码不正确'
    _clear_failures(email)
    return user, None


# ---------------------------------------------------------------------------
# 找回密码：一次性令牌 + 邮件
# ---------------------------------------------------------------------------

RESET_TOKEN_BYTES = 32
# 对外统一文案：邮箱存在与否都回同一句，避免账号枚举（见 docs/05 D11）
RESET_REQUESTED_MSG = '如果该邮箱已注册，我们已发送重置链接，请查收（注意垃圾邮件箱）。'


def _hash_token(raw):
    """令牌只存 sha256 摘要，库里拿不到明文。"""
    return hashlib.sha256((raw or '').encode('utf-8')).hexdigest()


def _find_reset(token):
    if not token:
        return None
    return PasswordReset.query.filter_by(token_hash=_hash_token(token)).first()


def _reset_token_usable(rec):
    return (rec is not None and rec.used_at is None
            and rec.expires_at >= datetime.utcnow())


def request_password_reset(email_raw, request_ip=None):
    """发起找回。返回 (mail_sent, err)。

    邮箱不存在时不报错也不发信，但仍回成功文案——调用方直接用
    RESET_REQUESTED_MSG 提示，不要区分「已发送/未注册」。
    """
    email = (email_raw or '').strip().lower()
    if not EMAIL_RE.match(email):
        return False, '邮箱格式不对'

    retry = reset_request_retry_after(email)
    if retry:
        return False, f'申请过于频繁，请 {(retry + 59) // 60} 分钟后再试'
    _record_reset_request(email)

    user = User.query.filter_by(email=email).first()
    if user is None:
        return True, None

    raw = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    db.session.add(PasswordReset(
        user_id=user.id,
        token_hash=_hash_token(raw),
        expires_at=datetime.utcnow() + timedelta(
            seconds=current_app.config['RESET_TOKEN_TTL_SECONDS']),
        request_ip=(request_ip or '')[:45] or None,
    ))
    db.session.commit()

    if current_app.config.get('PUBLIC_BASE_URL'):
        path = url_for('auth.reset_password_page')
        reset_url = f"{current_app.config['PUBLIC_BASE_URL'].rstrip('/')}{path}?token={raw}"
    else:
        reset_url = url_for('auth.reset_password_page', token=raw, _external=True)
    return mailer.send_password_reset_email(email, reset_url), None


def reset_password(raw_token, new_password):
    """用一次性令牌设置新密码。返回 (user, err, reason)。

    reason 为机器可读短码（None / 'weak' / 'invalid' / 'used' / 'expired' /
    'missing'），供 API 映射 HTTP 状态；页面只用 err 文案。
    """
    if len(new_password or '') < 8:
        return None, '密码至少 8 位', 'weak'
    token = (raw_token or '').strip()
    if not token:
        return None, '链接无效，请重新申请', 'invalid'

    rec = _find_reset(token)
    if rec is None:
        return None, '链接无效或已失效，请重新申请', 'invalid'
    if rec.used_at is not None:
        return None, '该链接已使用过，请重新申请', 'used'
    if rec.expires_at < datetime.utcnow():
        return None, '链接已过期，请重新申请', 'expired'

    user = db.session.get(User, rec.user_id)
    if user is None:
        return None, '账号不存在，请联系管理员', 'missing'

    now = datetime.utcnow()
    user.set_password(new_password)
    rec.used_at = now
    # 密码已变，同账号其余未用令牌一并作废
    (PasswordReset.query
     .filter(PasswordReset.user_id == user.id,
             PasswordReset.used_at.is_(None),
             PasswordReset.id != rec.id)
     .update({'used_at': now}, synchronize_session=False))
    db.session.commit()

    _clear_failures(user.email)   # 新密码正确，解除因连错密码产生的锁定
    return user, None, None


def _gen_invite_code():
    while True:
        code = ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        if not Team.query.filter_by(invite_code=code).first():
            return code


def create_team(user, name):
    name = (name or '').strip()
    if not (1 <= len(name) <= 60):
        return None, '队名需为 1–60 个字符'
    if user.team:
        return None, '你已加入一支队伍，每人只能加入一支队伍'
    if Team.query.filter_by(name=name).first():
        return None, '该队名已被占用，换一个试试'
    team = Team(name=name, invite_code=_gen_invite_code(), captain_id=user.id)
    db.session.add(team)
    db.session.flush()
    db.session.add(TeamMember(user_id=user.id, team_id=team.id))
    db.session.commit()
    return team, None


def join_team(user, invite_code):
    code = (invite_code or '').strip().upper()
    if not code:
        return None, '请输入邀请码'
    if user.team:
        return None, f'你已在队伍「{user.team.name}」，每人只能加入一支队伍'
    team = Team.query.filter_by(invite_code=code, disbanded_at=None).first()
    if team is None:
        return None, '邀请码无效，请向队长确认'
    if team.member_count >= TEAM_MAX_SIZE:
        return None, f'该队已满 {TEAM_MAX_SIZE} 人'
    db.session.add(TeamMember(user_id=user.id, team_id=team.id))
    db.session.commit()
    return team, None


def leave_team(user):
    membership = user.membership
    if membership is None:
        return None, '你还没有加入任何队伍'
    team = membership.team
    if team is None:
        db.session.delete(membership)
        db.session.commit()
        return None, '已退出'
    if team.captain_id == user.id:
        if team.member_count > 1:
            return None, '你是队长，请先转让队长后再退队'
        # 队长的独苗队伍：退队即解散
        team.disbanded_at = datetime.utcnow()
        db.session.delete(membership)
        db.session.commit()
        return team, None
    db.session.delete(membership)
    db.session.commit()
    return team, None


def reset_invite_code(user):
    team = user.team
    if team is None:
        return None, '你还没有加入队伍'
    if team.captain_id != user.id:
        return None, '只有队长可以重置邀请码'
    team.invite_code = _gen_invite_code()
    db.session.commit()
    return team, None


def transfer_captain(user, target_user_id):
    team = user.team
    if team is None:
        return None, '你还没有加入队伍'
    if team.captain_id != user.id:
        return None, '只有队长可以转让队长'
    target = None
    for m in team.members:
        if m.user_id == int(target_user_id or 0):
            target = m
    if target is None:
        return None, '请选择本队成员'
    team.captain_id = target.user_id
    db.session.commit()
    return team, None


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

_STATUS_LABEL = {
    'pending': '排队中', 'running': '评测中',
    'success': '已出分', 'failed': '未通过',
}


def submission_rows(subs):
    """把提交整理成给「我的提交」表用的行（含可读状态与代价）。

    代价取自 details 的逐数据点原始数据——这是选手看自己成绩的入口，
    所以把评测指标一并带出来，不必点进结果页才知道。
    """
    from scoring import parse_details
    rows = []
    for s in subs:
        d = parse_details(s)
        costs = [c.get('cost') for c in (d or {}).get('cases', [])
                 if isinstance(c, dict) and c.get('cost')]
        rows.append({
            'id': s.id,
            'problem_id': s.problem_id,
            'status': s.status,
            'status_label': _STATUS_LABEL.get(s.status, s.status),
            'score': s.score or 0.0,
            'cost': min(costs) if costs else None,
            'passed': (d or {}).get('passed_cases'),
            'total': (d or {}).get('total_cases'),
            'created_at': s.created_at,
        })
    return rows


def team_payload(team, with_members=False):
    if team is None:
        return None
    data = team.to_dict()
    if with_members:
        data['members'] = [
            {'user_id': m.user_id, 'name': m.user.name, 'email': m.user.email,
             'is_captain': m.user_id == team.captain_id}
            for m in team.members
        ]
    return data


def quota_payload(team):
    limit = current_app.config['DAILY_QUOTA']
    if team is None:
        return {'used': 0, 'limit': limit}
    since = last_reset_utc()
    used = Submission.query.filter(
        Submission.team_name == team.name,
        Submission.created_at >= since,
    ).count()
    return {'used': used, 'limit': limit}


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------

def _safe_next(default):
    nxt = request.values.get('next')
    if nxt and nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return default


@bp.route('/register', methods=['GET', 'POST'])
def register_page():
    if request.method == 'GET':
        if current_user():
            return redirect(url_for('auth.team_page'))
        return render_template('register.html')

    data = request.form
    if (data.get('password') or '') != (data.get('password2') or ''):
        flash('两次输入的密码不一致', 'error')
        return render_template('register.html', form=data), 400
    user, err = create_user(data)
    if err:
        flash(err, 'error')
        return render_template('register.html', form=data), 400
    _login_session(user)
    flash(f'注册成功，欢迎 {user.name}', 'success')
    return redirect(_safe_next(url_for('auth.team_join_page')))


@bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'GET':
        if current_user():
            return redirect(url_for('index'))
        return render_template('login.html')

    email = request.form.get('email') or ''
    locked = login_locked_seconds(email)
    if locked:
        flash(f'尝试过于频繁，请 {locked // 60 + 1} 分钟后再试', 'error')
        return render_template('login.html', form=request.form), 429
    user, err = authenticate(email, request.form.get('password') or '')
    if err:
        flash(err, 'error')
        return render_template('login.html', form=request.form), 401
    _login_session(user)
    flash(f'已登录：{user.name}', 'success')
    return redirect(_safe_next(url_for('index')))


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password_page():
    if request.method == 'GET':
        if current_user():
            return redirect(url_for('auth.team_page'))
        return render_template('forgot_password.html')

    email = request.form.get('email') or ''
    _, err = request_password_reset(email, request.remote_addr)
    if err:
        flash(err, 'error')
        return render_template('forgot_password.html', form=request.form), 400
    flash(RESET_REQUESTED_MSG, 'success')
    return redirect(url_for('auth.login_page'))


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password_page():
    token = request.values.get('token') or ''

    if request.method == 'GET':
        if not _reset_token_usable(_find_reset(token)):
            flash('链接无效或已失效，请重新申请', 'error')
            return redirect(url_for('auth.forgot_password_page'))
        return render_template('reset_password.html', token=token)

    if (request.form.get('password') or '') != (request.form.get('password2') or ''):
        flash('两次输入的密码不一致', 'error')
        return render_template('reset_password.html', token=token), 400
    _, err, _reason = reset_password(token, request.form.get('password') or '')
    if err:
        flash(err, 'error')
        return render_template('reset_password.html', token=token), 400
    flash('密码已重置，请用新密码登录', 'success')
    return redirect(url_for('auth.login_page'))


@bp.route('/logout', methods=['POST'])
def logout_page():
    session.clear()
    flash('已退出登录', 'success')
    return redirect(url_for('index'))


@bp.route('/team')
@login_required
def team_page():
    user = current_user()
    team = user.team
    my_subs = []
    used = 0
    if team:
        since = last_reset_utc()
        my_subs = (Submission.query
                   .filter_by(team_name=team.name)
                   .order_by(Submission.created_at.desc())
                   .limit(20).all())   # 经 submission_rows() 整理后再传给模板
        used = Submission.query.filter(
            Submission.team_name == team.name, Submission.created_at >= since
        ).count()
    return render_template(
        'team.html', user=user, team=team,
        members=[m.user for m in team.members] if team else [],
        quota={'used': used, 'limit': current_app.config['DAILY_QUOTA']},
        submissions=submission_rows(my_subs),
    )


@bp.route('/team/join')
@login_required
def team_join_page():
    user = current_user()
    if user.team:
        return redirect(url_for('auth.team_page'))
    return render_template('team_join.html', user=user)


@bp.route('/team/create', methods=['POST'])
@login_required
def team_create_page():
    _, err = create_team(current_user(), request.form.get('name'))
    flash(err or '队伍创建成功', 'error' if err else 'success')
    return redirect(url_for('auth.team_page'))


@bp.route('/team/join', methods=['POST'])
@login_required
def team_join_submit():
    _, err = join_team(current_user(), request.form.get('invite_code'))
    flash(err or '入队成功', 'error' if err else 'success')
    return redirect(url_for('auth.team_page'))


@bp.route('/team/leave', methods=['POST'])
@login_required
def team_leave_page():
    _, err = leave_team(current_user())
    flash(err or '已退出队伍', 'error' if err else 'success')
    return redirect(url_for('auth.team_page'))


@bp.route('/team/reset-code', methods=['POST'])
@login_required
def team_reset_code_page():
    _, err = reset_invite_code(current_user())
    flash(err or '邀请码已重置', 'error' if err else 'success')
    return redirect(url_for('auth.team_page'))


@bp.route('/team/transfer', methods=['POST'])
@login_required
def team_transfer_page():
    _, err = transfer_captain(current_user(), request.form.get('to_user_id'))
    flash(err or '队长已转让', 'error' if err else 'success')
    return redirect(url_for('auth.team_page'))


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

def _payload():
    return request.get_json(silent=True) or request.form


@bp.route('/api/auth/register', methods=['POST'])
def api_register():
    user, err = create_user(_payload())
    if err:
        return jsonify({'error': err}), 400
    _login_session(user)
    return jsonify({'user': user.to_dict()}), 201


@bp.route('/api/auth/login', methods=['POST'])
def api_login():
    data = _payload()
    email = data.get('email') or ''
    locked = login_locked_seconds(email)
    if locked:
        return jsonify({'error': f'尝试过于频繁，请 {locked // 60 + 1} 分钟后再试'}), 429
    user, err = authenticate(email, data.get('password') or '')
    if err:
        return jsonify({'error': err}), 401
    _login_session(user)
    return jsonify({'user': user.to_dict()}), 200


@bp.route('/api/auth/forgot-password', methods=['POST'])
def api_forgot_password():
    _, err = request_password_reset(
        _payload().get('email') or '', request.remote_addr)
    if err:
        return jsonify({'error': err}), 400
    return jsonify({'message': RESET_REQUESTED_MSG}), 200


@bp.route('/api/auth/reset-password', methods=['POST'])
def api_reset_password():
    data = _payload()
    password2 = data.get('password2')
    if password2 is not None and password2 != (data.get('password') or ''):
        return jsonify({'error': '两次输入的密码不一致'}), 400
    _, err, reason = reset_password(data.get('token') or '', data.get('password') or '')
    if err:
        # 令牌不可用（无效/已用/过期）语义上是「资源已不存在」→ 410
        status = 410 if reason in ('invalid', 'used', 'expired') else 400
        return jsonify({'error': err, 'reason': reason}), status
    return jsonify({'message': '密码已重置，请用新密码登录'}), 200


@bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return '', 204


@bp.route('/api/me')
@api_login_required
def api_me():
    user = current_user()
    team = user.team
    return jsonify({
        'user': user.to_dict(),
        'team': team_payload(team, with_members=True),
        'quota': quota_payload(team),
    })


@bp.route('/api/team', methods=['POST'])
@api_login_required
def api_team_create():
    team, err = create_team(current_user(), _payload().get('name'))
    if err:
        return jsonify({'error': err}), 409
    return jsonify({'team': team_payload(team, with_members=True)}), 201


@bp.route('/api/team/join', methods=['POST'])
@api_login_required
def api_team_join():
    team, err = join_team(current_user(), _payload().get('invite_code'))
    if err:
        status = 404 if '无效' in err else (410 if '已满' in err else 409)
        return jsonify({'error': err}), status
    return jsonify({'team': team_payload(team, with_members=True)}), 200


@bp.route('/api/team/leave', methods=['POST'])
@api_login_required
def api_team_leave():
    _, err = leave_team(current_user())
    if err:
        return jsonify({'error': err}), 409
    return '', 204
