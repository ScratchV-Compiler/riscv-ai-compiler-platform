from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from contests import DEFAULT_SLUG

db = SQLAlchemy()

TEAM_MAX_SIZE = 3  # 每队人数上限（策划案：每队 1~3 人）


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contest = db.Column(db.String(40), nullable=False, default=DEFAULT_SLUG, index=True)
    # 提交人。配额「按人计」要靠它；老数据没有（None），不计入任何人的配额。
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    team_name = db.Column(db.String(80), nullable=False)
    problem_id = db.Column(db.String(20), nullable=False)  # 如 'matmul'
    code_path = db.Column(db.String(200), nullable=False)   # 存储源码路径
    status = db.Column(db.String(20), default='pending')    # pending, running, success, failed
    score = db.Column(db.Float, default=0.0)
    details = db.Column(db.Text, default='')                # 详细结果JSON
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'contest': self.contest,
            'team': self.team_name,
            'problem': self.problem_id,
            'status': self.status,
            'score': self.score,
            'details': self.details,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class User(db.Model):
    """P2 账号。邮箱必填且唯一（登录账号）；学号可选。"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    student_id = db.Column(db.String(20), unique=True, nullable=True)
    name = db.Column(db.String(40), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='player')  # player / admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 一个用户可在**不同场次**各加入一支队伍（每场一支），故是一对多。
    memberships = db.relationship(
        'TeamMember', backref='user', lazy=True,
        cascade='all, delete-orphan'
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def membership_in(self, contest_slug):
        """该用户在某场次里的成员关系（没有则 None）。

        **必须显式传场次**——不要做成读请求上下文 `g.contest` 的单数属性：
        评测 worker 线程与 CLI 工具都没有请求上下文，那样会**静默取错场次**。
        """
        slug = getattr(contest_slug, 'slug', contest_slug)
        for m in self.memberships:
            if m.contest == slug:
                return m
        return None

    def team_in(self, contest_slug):
        """该用户在某场次里的队伍（没有则 None）。"""
        m = self.membership_in(contest_slug)
        return m.team if m else None

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'student_id': self.student_id,
            'name': self.name,
            'role': self.role,
        }


class PasswordReset(db.Model):
    """一次性密码重置令牌。

    只存 token 的 sha256 摘要：即使数据库泄露也无法直接拿去重置密码。
    重置成功后写 used_at 立即失效；过期时间见 RESET_TOKEN_TTL_SECONDS。
    """
    __tablename__ = 'password_resets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    request_ip = db.Column(db.String(45), nullable=True)

    user = db.relationship('User', backref='password_resets')


class SubmitThrottle(db.Model):
    """提交间隔限流：记录每个选手**在每场**最近一次成功提交的时间。

    主键是 `(user_id, contest)`——**每场各自计时**：在 A 场刚交完，不影响在 B 场
    立刻提交。用户账号是全局的，但节流不该跨场次互相牵连。

    刻意做成独立的表而不是给 Submission 加列——`create_all()` 只创建缺失的表、
    不会 ALTER 既有表，所以加列在老库上会静默失效（见 docs/08 的说明）。
    """
    __tablename__ = 'submit_throttle'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    contest = db.Column(db.String(40), primary_key=True, default=DEFAULT_SLUG)
    last_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Team(db.Model):
    """P2 队伍。邀请码为入队/再入队的索引。

    队伍**按场次隔离**：队名只在同一场次内唯一（`uq_team_contest_name`），
    不同场次可以重名。邀请码仍全局唯一（8 位随机），入队时再校验场次是否匹配。
    """
    __tablename__ = 'teams'
    __table_args__ = (
        db.UniqueConstraint('contest', 'name', name='uq_team_contest_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    contest = db.Column(db.String(40), nullable=False, default=DEFAULT_SLUG, index=True)
    name = db.Column(db.String(60), nullable=False)
    invite_code = db.Column(db.String(12), unique=True, nullable=False, index=True)
    captain_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    disbanded_at = db.Column(db.DateTime, nullable=True)

    members = db.relationship(
        'TeamMember', backref='team', lazy=True,
        cascade='all, delete-orphan'
    )

    @property
    def member_count(self):
        return len(self.members)

    @property
    def is_full(self):
        return self.member_count >= TEAM_MAX_SIZE

    def to_dict(self):
        return {
            'id': self.id,
            'contest': self.contest,
            'name': self.name,
            'invite_code': self.invite_code,
            'captain_id': self.captain_id,
            'member_count': self.member_count,
        }


class TeamMember(db.Model):
    """队伍成员。`(user_id, contest)` 唯一 = 每人每场限一队。"""
    __tablename__ = 'team_members'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'contest', name='uq_member_user_contest'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    contest = db.Column(db.String(40), nullable=False, default=DEFAULT_SLUG, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False, index=True)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)


class Enrollment(db.Model):
    """**个人报名**记录：某人报名了某场次，`(user_id, contest)` 唯一。

    只有 `Contest.requires_registration` 为 True 的场次才用得上；未报名者
    不能建队/入队（也就不能提交）。新表，`create_all()` 会直接建出来。
    """
    __tablename__ = 'enrollments'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'contest', name='uq_enroll_user_contest'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    contest = db.Column(db.String(40), nullable=False, default=DEFAULT_SLUG, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TeamLeaveLog(db.Model):
    """退队流水：用于「每人每场每天只能退出一次队伍」的限频。

    刻意做成**只增不改的独立表**而不是给 Team/TeamMember 加列——`create_all()`
    只建缺失的表、不会 ALTER 既有表，所以给老库加列会静默失效；而新表
    `create_all()` 会直接建出来（这条与 SubmitThrottle 同理）。
    """
    __tablename__ = 'team_leave_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    contest = db.Column(db.String(40), nullable=False, default=DEFAULT_SLUG, index=True)
    team_name = db.Column(db.String(60), nullable=False)
    left_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
