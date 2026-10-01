import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

TEAM_MAX_SIZE = 3  # 每队人数上限（策划案：每队 1~3 人）

# P3 verdict 文案与徽章类（供模板复用）
VERDICT_LABELS = {
    'pending': '排队中',
    'running': '评测中',
    'accepted': '通过',
    'compile_error': '补丁/编译失败',
    'timeout': '超时',
    'runtime_error': '运行错误',
    'invalid': '正确性未通过',
}
VERDICT_CSS = {
    'pending': 'vbadge-pending',
    'running': 'vbadge-pending',
    'accepted': 'vbadge-accepted',
    'compile_error': 'vbadge-error',
    'timeout': 'vbadge-warn',
    'runtime_error': 'vbadge-error',
    'invalid': 'vbadge-critical',
}
TERMINAL_VERDICTS = ('accepted', 'compile_error', 'timeout', 'runtime_error', 'invalid')


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_name = db.Column(db.String(80), nullable=False)
    problem_id = db.Column(db.String(20), nullable=False)  # 'conv' / 'fwht' / 'add-two-numbers' 等
    code_path = db.Column(db.String(200), nullable=False)   # 上传产物路径（P3 起为补丁文件）
    status = db.Column(db.String(20), default='pending')    # pending, running, finished
    verdict = db.Column(db.String(24), nullable=True)       # P3：终态语义（accepted/…/invalid）
    score = db.Column(db.Float, default=0.0)
    details = db.Column(db.Text, default='')                # 详细结果JSON
    # ---- P3 补丁评测 ----
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    source_name = db.Column(db.String(120), nullable=True)  # 原始上传文件名
    artifact_sha256 = db.Column(db.String(64), nullable=True)
    baseline_ref = db.Column(db.String(40), nullable=True)  # 评测所用冻结基线 commit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def verdict_text(self):
        return VERDICT_LABELS.get(self.verdict or self.status, self.verdict or self.status)

    def parsed_details(self):
        if not self.details:
            return {}
        try:
            value = json.loads(self.details)
            return value if isinstance(value, dict) else {'raw': self.details}
        except (ValueError, TypeError):
            return {'raw': self.details}

    def to_dict(self):
        return {
            'id': self.id,
            'team': self.team_name,
            'problem': self.problem_id,
            'status': self.status,
            'verdict': self.verdict,
            'score': self.score,
            'details': self.parsed_details(),
            'source_name': self.source_name,
            'artifact_sha256': self.artifact_sha256,
            'baseline_ref': self.baseline_ref,
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
