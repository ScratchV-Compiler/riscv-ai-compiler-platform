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
                    SubmitThrottle, TeamLeaveLog, Enrollment, TEAM_MAX_SIZE)
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

def submit_wait_seconds(user, contest):
    """还需要等多少秒才能**在该场次**再次提交；0 表示可以提交。"""
    slug = _slug(contest)
    rec = db.session.get(SubmitThrottle, (user.id, slug))
    if rec is None:
        return 0
    interval = current_app.config['SUBMIT_INTERVAL_SECONDS']
    elapsed = (datetime.utcnow() - rec.last_at).total_seconds()
    remain = interval - elapsed
    return int(remain) + 1 if remain > 0 else 0


def mark_submitted(user, contest):
    """记录一次成功提交的时间（**该场次**）。**只在提交成功时调用**——
    传错文件、后缀不对这类无效提交不该消耗间隔。"""
    slug = _slug(contest)
    now = datetime.utcnow()
    rec = db.session.get(SubmitThrottle, (user.id, slug))
    if rec is None:
        db.session.add(SubmitThrottle(user_id=user.id, contest=slug, last_at=now))
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


def default_landing_url():
    """登录/注册/退出后落到**默认场次**首页——账号是全局的，但“回家”要落到某一处。"""
    from contests import default_contest
    return url_for('contest.index', slug=default_contest().slug)


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


def _slug(contest):
    """把场次参数（Contest 对象或 slug 字符串）统一成 slug。"""
    return getattr(contest, 'slug', contest)


def _contest_of(contest):
    """把场次参数取成 Contest 对象（用于看状态/标题）。"""
    if hasattr(contest, 'slug'):
        return contest
    from contests import get_contest, default_contest
    return get_contest(contest) or default_contest()


def is_enrolled(user, contest):
    """该用户是否已报名该场次（无需报名的场次一律视为「已报名」）。"""
    if user is None:
        return False
    c = _contest_of(contest)
    if not c.requires_registration:
        return True
    return Enrollment.query.filter_by(user_id=user.id, contest=c.slug).first() is not None


def enroll(user, contest, code=None):
    """个人报名（需**邀请码**）。返回 (ok, err)。

    需报名的场次一律要填对报名邀请码——`.registration_code` 没配就是配置错误，
    直接拒绝（fail closed），别让「要邀请码的场次」意外变成谁都能报。
    """
    if user is None:
        return None, '请先登录'
    c = _contest_of(contest)
    if not c.requires_registration:
        return None, '本场次无需报名，直接组队即可'
    if not c.registration_open:
        return None, f'本场次（{c.title}）{c.status_label}，报名已截止'
    if Enrollment.query.filter_by(user_id=user.id, contest=c.slug).first():
        return None, '你已报名本场次'
    if not c.registration_code:
        return None, '本场次尚未配置报名邀请码，请联系主办方'
    if (code or '').strip() != c.registration_code:
        return None, '报名邀请码不正确，请向主办方确认'
    db.session.add(Enrollment(user_id=user.id, contest=c.slug))
    db.session.commit()
    return c, None


def unenroll(user, contest):
    """取消报名。已有队伍时不允许（先退队）。返回 (ok, err)。"""
    if user is None:
        return None, '请先登录'
    c = _contest_of(contest)
    rec = Enrollment.query.filter_by(user_id=user.id, contest=c.slug).first()
    if rec is None:
        return None, '你还没有报名本场次'
    if user.team_in(c.slug) is not None:
        return None, '你在本场次已有队伍，请先退队再取消报名'
    db.session.delete(rec)
    db.session.commit()
    return c, None


def _join_gate(user, contest):
    """组队/入队的准入闸：**未开始/已结束不许参加**；需报名的场次要**已报名**。
    返回 (contest, err)——err 非空则调用方直接返回错误。"""
    c = _contest_of(contest)
    if not c.is_open:
        return c, f'本场次（{c.title}）{c.status_label}，暂不能参加'
    if c.requires_registration and not is_enrolled(user, c):
        return c, '本场次需要先报名，请先报名再组队'
    return c, None


def _gen_invite_code():
    while True:
        code = ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        if not Team.query.filter_by(invite_code=code).first():
            return code


def create_team(user, contest, name):
    c, err = _join_gate(user, contest)
    if err:
        return None, err
    slug = c.slug
    name = (name or '').strip()
    if not (1 <= len(name) <= 60):
        return None, '队名需为 1–60 个字符'
    if user.team_in(slug):
        return None, '你已在本场次加入一支队伍，每人每场限一队'
    taken = Team.query.filter_by(contest=slug, name=name).first()
    if taken is not None:
        if taken.disbanded_at is not None and taken.captain_id == user.id:
            return None, (f'「{name}」是你此前解散的队伍——'
                          f'若想继续用它，请用「恢复队伍」，队名与历史都会保留')
        return None, '该队名已被占用，换一个试试'
    team = Team(contest=slug, name=name,
                invite_code=_gen_invite_code(), captain_id=user.id)
    db.session.add(team)
    db.session.flush()
    db.session.add(TeamMember(user_id=user.id, contest=slug, team_id=team.id))
    db.session.commit()
    return team, None


def join_team(user, contest, invite_code):
    c, err = _join_gate(user, contest)
    if err:
        return None, err
    slug = c.slug
    code = (invite_code or '').strip().upper()
    if not code:
        return None, '请输入邀请码'
    if user.team_in(slug):
        return None, f'你已在本场次加入队伍「{user.team_in(slug).name}」，每人每场限一队'
    team = Team.query.filter_by(invite_code=code, disbanded_at=None).first()
    if team is None:
        return None, '邀请码无效，请向队长确认'
    if team.contest != slug:
        # 邀请码是全局唯一的，但不属于本场次——别让人拿另一场的码串场入队
        return None, '该邀请码不属于本场次，请向队长确认'
    if team.member_count >= TEAM_MAX_SIZE:
        return None, f'该队已满 {TEAM_MAX_SIZE} 人'
    db.session.add(TeamMember(user_id=user.id, contest=slug, team_id=team.id))
    db.session.commit()
    return team, None


def leaves_today(user, contest):
    """该用户**本场次**当日（自上次 05:00 结算起）已退队次数。"""
    slug = _slug(contest)
    return TeamLeaveLog.query.filter(
        TeamLeaveLog.user_id == user.id,
        TeamLeaveLog.contest == slug,
        TeamLeaveLog.left_at >= last_reset_utc(),
    ).count()


LEAVE_DAILY_LIMIT = 1


def leave_team(user, contest):
    slug = _slug(contest)
    membership = user.membership_in(slug)
    if membership is None:
        return None, '你还没有加入任何队伍'
    # 每人每场每天只能退出一次：防止靠「退队→换队」来回腾挪
    if leaves_today(user, slug) >= LEAVE_DAILY_LIMIT:
        return None, '每人每天只能退出一次队伍，请明天再试'
    team = membership.team
    # 队长在多人的队里必须先转让——这是**会被拒**的情况，别记流水
    if team is not None and team.captain_id == user.id and team.member_count > 1:
        return None, '你是队长，请先转让队长后再退队'

    # 到这里确定真的会退出：记一条退队流水
    _note_leave(user, slug, team.name if team else '')

    if team is None:
        db.session.delete(membership)
        db.session.commit()
        return None, '已退出'
    if team.captain_id == user.id:
        # 队长的独苗队伍：退队即解散
        team.disbanded_at = datetime.utcnow()
    db.session.delete(membership)
    db.session.commit()
    return team, None


def _note_leave(user, slug, team_name):
    """记一条退队流水（供每日退队限频）。"""
    db.session.add(TeamLeaveLog(user_id=user.id, contest=slug,
                                team_name=team_name, left_at=datetime.utcnow()))


def restorable_team(user, contest):
    """该用户可以恢复的队伍：他曾任队长、且已被解散的队（取最近一个）。

    独苗队长退队时队伍会被标记解散（`disbanded_at`）而**不是删除**，
    所以队伍行还在——但邀请码作废、队名也仍占着（DB 有 unique 约束）。
    没有恢复入口的话，这个人就被永久挡在自己的队名之外了。

    只在**同一场次**内恢复：别把上一场的队恢复进这一场。
    """
    slug = _slug(contest)
    if user.team_in(slug):
        return None
    return (Team.query
            .filter(Team.contest == slug,
                    Team.captain_id == user.id, Team.disbanded_at.isnot(None))
            .order_by(Team.disbanded_at.desc())
            .first())


def restore_team(user, contest):
    """恢复一个已解散的队伍。返回 (team, err)。

    - 清掉 disbanded_at，队伍重新可用
    - **邀请码换新的**：旧码已经废了，且可能已泄露给（前）队员
    - 把该用户重新加回成员
    """
    slug = _slug(contest)
    if user.team_in(slug):
        return None, '你已在本场次的一支队伍中'
    team = restorable_team(user, contest)
    if team is None:
        return None, '没有可恢复的队伍'
    team.disbanded_at = None
    team.invite_code = _gen_invite_code()
    db.session.add(TeamMember(user_id=user.id, contest=slug, team_id=team.id))
    db.session.commit()
    return team, None


def reset_invite_code(user, contest):
    team = user.team_in(_slug(contest))
    if team is None:
        return None, '你还没有加入队伍'
    if team.captain_id != user.id:
        return None, '只有队长可以重置邀请码'
    team.invite_code = _gen_invite_code()
    db.session.commit()
    return team, None


def transfer_captain(user, contest, target_user_id):
    team = user.team_in(_slug(contest))
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


def user_quota_used(user, contest):
    """该用户**本场次**当日（自上次 05:00 结算起）的提交次数。

    配额**按人计**（不是按队）：换队不会刷新额度，也就堵掉了
    「刷满配额 → 退队 → 换个队名 → 又有额度」这条路径。
    老提交没有记录提交人（user_id 为 NULL），不计入任何人。
    """
    slug = getattr(contest, 'slug', contest)
    return Submission.query.filter(
        Submission.contest == slug,
        Submission.user_id == user.id,
        Submission.created_at >= last_reset_utc(),
    ).count()


def quota_payload(user, contest):
    limit = current_app.config['DAILY_QUOTA']
    if user is None:
        return {'used': 0, 'limit': limit}
    return {'used': user_quota_used(user, contest), 'limit': limit}


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
            return redirect(default_landing_url())
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
    return redirect(_safe_next(default_landing_url()))


@bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'GET':
        if current_user():
            return redirect(default_landing_url())
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
    return redirect(_safe_next(default_landing_url()))


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password_page():
    if request.method == 'GET':
        if current_user():
            return redirect(default_landing_url())
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
    return redirect(default_landing_url())


# ---------------------------------------------------------------------------
# JSON API（全局账号相关；场次相关的 API 见 app.py 的 contest 蓝图）
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
