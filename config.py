import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBMISSIONS_DIR = os.path.join(BASE_DIR, 'submissions')
TEST_DATA_DIR = os.path.join(BASE_DIR, 'test_data')

# 确保目录存在
os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
os.makedirs(TEST_DATA_DIR, exist_ok=True)

class Config:
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'platform.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
    UPLOAD_FOLDER = SUBMISSIONS_DIR
    # 评测超时（秒）
    EVAL_TIMEOUT = 120


# 模块级常量，供 evaluator.py 等直接 from config import EVAL_TIMEOUT
EVAL_TIMEOUT = Config.EVAL_TIMEOUT