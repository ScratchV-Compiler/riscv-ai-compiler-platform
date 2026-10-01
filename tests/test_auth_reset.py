# -*- coding: utf-8 -*-
"""找回密码。

运行：`python tests/test_auth_reset.py` 或 `python tests/run_all.py`
用**临时库**，不碰 platform.db。
"""
import contextlib
import io
import re
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap as boot
from _bootstrap import check

app, _TMP = boot.temp_app()
import config
import json as _json
from models import db, PasswordReset, User



def extract_reset_path(out):
    m = re.search(r'(/reset-password\?token=[A-Za-z0-9_\-]+)', out)
    return m.group(1) if m else None


with app.test_client() as c:
    # --- 准备账号 ---
    r = c.post('/api/auth/register', json={
        'email': 'dupe@stu.ecnu.edu.cn', 'name': '张三', 'password': 'oldpass123'})
    check('注册 201', r.status_code == 201, r.status_code)
    r = c.post('/api/auth/logout')
    check('登出 204', r.status_code == 204)

    # --- 申请重置（已注册邮箱）：令牌只进日志，不进响应 ---
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = c.post('/api/auth/forgot-password', json={'email': 'dupe@stu.ecnu.edu.cn'})
    body = r.get_json() or {}
    check('申请重置 200', r.status_code == 200, r.status_code)
    check('响应为统一文案(防枚举)', '如果该邮箱已注册' in body.get('message', ''), body.get('message', '')[:60])
    path = extract_reset_path(buf.getvalue())
    check('令牌写入服务端日志/控制台', path is not None, buf.getvalue().strip()[:120])
    check('响应体不含令牌', path.split('token=')[1] not in r.get_data(as_text=True) if path else False)

    # --- 未注册邮箱：同样 200 同文案，且不发信 ---
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        r = c.post('/api/auth/forgot-password', json={'email': 'nobody@stu.ecnu.edu.cn'})
    check('未注册邮箱同样 200 同文案',
          r.status_code == 200 and '如果该邮箱已注册' in (r.get_json() or {}).get('message', ''))
    check('未注册邮箱不生成令牌/不发信', extract_reset_path(buf2.getvalue()) is None)

    # --- 令牌以哈希入库，不存明文 ---
    raw = path.split('token=')[1]
    with app.app_context():
        rec = PasswordReset.query.first()
        stored = rec.token_hash
    check('令牌入库为 sha256 摘要', stored != raw and len(stored) == 64, stored[:16] + '…')
    check('库中查不到明文令牌', PasswordReset.query.filter_by(token_hash=raw).first() is None)

    # --- 页面 GET 校验令牌 ---
    r = c.get(path)
    check('重置页 GET 200', r.status_code == 200, r.status_code)
    r = c.get('/reset-password?token=garbage')
    check('坏令牌 GET 跳回找回页', r.status_code == 302, r.status_code)

    # --- 两次密码不一致 ---
    r = c.post('/reset-password', data={'token': raw, 'password': 'newpass123', 'password2': 'x'})
    check('两次密码不一致 400', r.status_code == 400, r.status_code)

    # --- 太短 ---
    r = c.post('/api/auth/reset-password', json={'token': raw, 'password': 'short'})
    check('密码过短 400', r.status_code == 400, r.status_code)

    # --- 正常重置 ---
    r = c.post('/reset-password', data={'token': raw, 'password': 'newpass123', 'password2': 'newpass123'})
    check('重置成功 302 -> /login', r.status_code == 302 and '/login' in r.headers.get('Location', ''), r.status_code)

    # --- 新密码可登录、旧密码失效 ---
    r = c.post('/api/auth/login', json={'email': 'dupe@stu.ecnu.edu.cn', 'password': 'newpass123'})
    check('新密码登录 200', r.status_code == 200, r.status_code)
    c.post('/api/auth/logout')
    r = c.post('/api/auth/login', json={'email': 'dupe@stu.ecnu.edu.cn', 'password': 'oldpass123'})
    check('旧密码登录 401', r.status_code == 401, r.status_code)

    # --- 令牌一次性 ---
    r = c.post('/api/auth/reset-password', json={'token': raw, 'password': 'another123'})
    check('令牌复用被拒 410', r.status_code == 410, (r.get_json() or {}).get('reason'))

    # --- 过期令牌 ---
    from datetime import datetime, timedelta
    with app.app_context():
        u = User.query.filter_by(email='dupe@stu.ecnu.edu.cn').first()
        import hashlib
        expired = hashlib.sha256(b'expired-token').hexdigest()
        db.session.add(PasswordReset(user_id=u.id, token_hash=expired,
                                     expires_at=datetime.utcnow() - timedelta(minutes=1)))
        db.session.commit()
    r = c.post('/api/auth/reset-password', json={'token': 'expired-token', 'password': 'whatever1'})
    check('过期令牌被拒 410', r.status_code == 410, (r.get_json() or {}).get('reason'))

    # --- 重置后解除登录锁定 ---
    for _ in range(5):
        c.post('/api/auth/login', json={'email': 'dupe@stu.ecnu.edu.cn', 'password': 'wrongwrong'})
    r = c.post('/api/auth/login', json={'email': 'dupe@stu.ecnu.edu.cn', 'password': 'newpass123'})
    check('连错 5 次后触发锁定 429', r.status_code == 429, r.status_code)
    buf3 = io.StringIO()
    with contextlib.redirect_stdout(buf3):
        c.post('/api/auth/forgot-password', json={'email': 'dupe@stu.ecnu.edu.cn'})
    p2 = extract_reset_path(buf3.getvalue())
    c.post('/api/auth/reset-password', json={'token': p2.split('token=')[1], 'password': 'fresh12345'})
    r = c.post('/api/auth/login', json={'email': 'dupe@stu.ecnu.edu.cn', 'password': 'fresh12345'})
    check('重置成功后锁定被解除', r.status_code == 200, r.status_code)
    c.post('/api/auth/logout')

    # --- 申请限频 ---
    last = None
    for i in range(config.Config.RESET_MAX_REQUESTS + 1):
        last = c.post('/api/auth/forgot-password', json={'email': 'rate@stu.ecnu.edu.cn'})
    check(f'第 {config.Config.RESET_MAX_REQUESTS + 1} 次申请被限频 400',
          last.status_code == 400 and '频繁' in (last.get_json() or {}).get('error', ''),
          (last.get_json() or {}).get('error'))

    # --- 页面：登录页有入口；找回页可渲染 ---
    r = c.get('/login')
    check('登录页含「忘记密码？」入口', '忘记密码' in r.get_data(as_text=True))
    r = c.get('/forgot-password')
    check('找回页 GET 200', r.status_code == 200, r.status_code)

    # --- 已登录访问找回页跳转 ---
    c.post('/api/auth/login', json={'email': 'dupe@stu.ecnu.edu.cn', 'password': 'fresh12345'})
    r = c.get('/forgot-password')
    check('已登录访问找回页 -> 302', r.status_code == 302, r.status_code)
    c.post('/api/auth/logout')

    # --- CSRF 开：无 token 的 POST 被拒 ---
    app.config['WTF_CSRF_ENABLED'] = True
    r = c.post('/api/auth/forgot-password', json={'email': 'dupe@stu.ecnu.edu.cn'})
    check('CSRF 开启: 无 token POST 400', r.status_code == 400, r.status_code)

boot.finish('找回密码')
