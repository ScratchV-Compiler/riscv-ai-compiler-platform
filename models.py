from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_name = db.Column(db.String(80), nullable=False)
    problem_id = db.Column(db.String(20), nullable=False)  # 'fwht', 'conv', 'spmv'
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
            'created_at': self.created_at.isoformat(),
        }