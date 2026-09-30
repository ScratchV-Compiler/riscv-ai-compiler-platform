import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBMISSIONS_DIR = os.path.join(BASE_DIR, 'submissions')
TEST_DATA_DIR = os.path.join(BASE_DIR, 'test_data')
DATA_DIR = os.path.join(BASE_DIR, 'data')

# 确保目录存在
os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
os.makedirs(TEST_DATA_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# demo / 初始数据（方案 B：运行时仍走 SQLite，仅演示数据来自 CSV）
DEMO_SUBMISSIONS_CSV = os.path.join(DATA_DIR, 'demo_submissions.csv')

# 会话签名密钥：优先取环境变量，缺失时用开发默认值并告警
_DEFAULT_SECRET = 'dev-insecure-riscv-platform-key'
SECRET_KEY = os.environ.get('PLATFORM_SECRET_KEY') or _DEFAULT_SECRET
if SECRET_KEY == _DEFAULT_SECRET:
    print('[config] 警告：未设置 PLATFORM_SECRET_KEY，正在使用开发默认密钥，请勿用于生产。')


class Config:
    SECRET_KEY = SECRET_KEY
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'platform.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
    UPLOAD_FOLDER = SUBMISSIONS_DIR
    # 评测超时（秒）
    EVAL_TIMEOUT = 120

    # ---- P2 身份与组队 ----
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)  # 登录态有效期
    DAILY_QUOTA = 99                                 # 每队每日提交上限
    LOGIN_MAX_FAILURES = 5                           # 登录失败限频阈值
    LOGIN_LOCK_SECONDS = 15 * 60                     # 锁定时长

    # CSRF（Flask-WTF）
    WTF_CSRF_TIME_LIMIT = None                       # 与登录会话同生命周期
    WTF_CSRF_HEADERS = ['X-CSRFToken', 'X-CSRF-Token']


# 模块级常量，供 evaluator.py 等直接 from config import EVAL_TIMEOUT
EVAL_TIMEOUT = Config.EVAL_TIMEOUT
