from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

TEAM_MAX_SIZE = 3  # 每队人数上限（策划案：每队 1~3 人）


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_name = db.Column(db.String(80), nullable=False)
    problem_id = db.Column(db.String(20), nullable=False)  # 如 'matmul-4x4'
    code_path = db.Column(db.String(200), nullable=False)   # 存储源码路径
    status = db.Column(db.String(20), default='pending')    # pending, running, success, failed
    score = db.Column(db.Float, default=0.0)
    details = db.Column(db.Text, default='')                # 详细结果JSON
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
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

    membership = db.relationship(
        'TeamMember', backref='user', uselist=False,
        cascade='all, delete-orphan'
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def team(self):
        return self.membership.team if self.membership else None

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


class Team(db.Model):
    """P2 队伍。邀请码为入队/再入队的索引。"""
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
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
            'name': self.name,
            'invite_code': self.invite_code,
            'captain_id': self.captain_id,
            'member_count': self.member_count,
        }


class TeamMember(db.Model):
    """队伍成员。user_id 唯一 = 每人限一队。"""
    __tablename__ = 'team_members'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False, index=True)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
