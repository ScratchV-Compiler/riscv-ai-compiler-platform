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
    BASE_DIR = BASE_DIR      # 项目根目录（评测器按它定位 baseline.json 等）
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

    # ---- 找回密码 ----
    # 一次性重置令牌有效期（秒）与「同一邮箱申请重置」的限频
    RESET_TOKEN_TTL_SECONDS = 30 * 60                # 30 分钟内有效
    RESET_MAX_REQUESTS = 5                           # 窗口内最多申请次数
    RESET_WINDOW_SECONDS = 60 * 60                   # 窗口 1 小时
    # 站点对外基址（用于拼重置链接）；留空则按当前请求 Host 推断。
    # 反向代理下建议显式设置，如 PUBLIC_BASE_URL=https://contest.example.com
    PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL') or ''

    # SMTP。未配置 SMTP_HOST 时 mailer 退回「打印到服务端日志」，便于本地测试。
    SMTP_HOST = os.environ.get('SMTP_HOST') or ''
    SMTP_PORT = int(os.environ.get('SMTP_PORT') or 587)
    SMTP_USER = os.environ.get('SMTP_USER') or ''
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD') or ''
    SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', '1') != '0'   # STARTTLS，默认开启
    SMTP_USE_SSL = os.environ.get('SMTP_USE_SSL') == '1'        # 隐式 SSL（465）
    MAIL_FROM = os.environ.get('MAIL_FROM') or 'no-reply@riscv-contest.local'

    # ---- P3 RISC-V 评测 ----
    # 评测指标：cost = 动态指令数 + MISS_PENALTY × L1 未命中次数
    # α=15 的来历（见 docs/08 §9）：顺序 RISC-V 核（E76/U74/Rocket）L1 命中 2 拍、
    # 未命中约 15~20 拍且**不重叠**（只有一个填充槽）；本平台 kernel 实测 IPC≈0.75，
    # 换算成指令当量 α ≈ 0.75 × 20 ≈ 15。**发布后不得更改**，否则历史成绩失去可比性。
    MISS_PENALTY = int(os.environ.get('PLATFORM_MISS_PENALTY') or 15)

    COMPILE_TIMEOUT = 60          # 汇编+链接超时（秒）
    PER_CASE_TIMEOUT = 15         # 单个用例 qemu 执行超时
    COUNT_TIMEOUT = 60            # 单步数指令超时（单步本身很慢）
    EVAL_TOTAL_BUDGET = 180       # 一次评测总预算，超了判 timeout
    SUBMISSION_MAX_BYTES = 256 * 1024   # 提交源码大小上限
    MAX_QUEUE_DEPTH = 50          # 评测队列深度上限，超了 /api/submit 返回 429
    # 提交间隔限流：同一选手两次**成功**提交之间至少间隔这么久（秒）。
    # 只对成功提交计时——传错文件、后缀不对等无效提交不消耗间隔。
    SUBMIT_INTERVAL_SECONDS = int(os.environ.get('PLATFORM_SUBMIT_INTERVAL') or 120)
    WORKER_COUNT = 0              # 0 = 自动（min(2, cpu)）
    STALE_RUNNING_MINUTES = 15    # 卡在 running 超过这么久就回收为失败

    # 沙箱：评测子进程降权到 SANDBOX_UID 并放进独立网络命名空间。
    # 以非 root 运行时把 ENABLE_SANDBOX 关掉即可降级（本地开发）。
    ENABLE_SANDBOX = os.environ.get('PLATFORM_ENABLE_SANDBOX', '1') != '0'
    SANDBOX_UID = int(os.environ.get('PLATFORM_SANDBOX_UID') or 65534)   # nobody
    SANDBOX_GID = int(os.environ.get('PLATFORM_SANDBOX_GID') or 65534)   # nogroup
    # 评测工作目录的根。**不要设在 /tmp**：沙箱会用私有挂载命名空间把 /tmp 等
    # 世界可写目录遮蔽成空 tmpfs（否则 guest 能往宿主 /tmp 里留文件）。
    EVAL_WORK_ROOT = os.environ.get('PLATFORM_EVAL_WORK_ROOT') or '/var/lib/riscv-eval'

    # CSRF（Flask-WTF）
    WTF_CSRF_TIME_LIMIT = None                       # 与登录会话同生命周期
    WTF_CSRF_HEADERS = ['X-CSRFToken', 'X-CSRF-Token']


# 模块级常量，供 evaluator.py 等直接 from config import EVAL_TIMEOUT
EVAL_TIMEOUT = Config.EVAL_TIMEOUT
