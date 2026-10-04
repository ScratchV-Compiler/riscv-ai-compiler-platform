# -*- coding: utf-8 -*-
"""发信：密码重置邮件。

配置了 SMTP_HOST 时用 smtplib 发信；未配置（开发/演示环境）时把邮件内容
打印到服务端日志与控制台，管理员可从中取出重置链接转达——不把链接回显到
HTTP 响应里，避免任何访问者都能拿走别人的重置令牌。

返回 True 表示「已投递或已落到日志」，False 表示发信尝试失败（调用方据此
决定是否提示用户稍后再试；无论哪种情况都不影响防枚举的对外文案）。
"""
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


def _build_message(to_email, subject, body):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = current_app.config['MAIL_FROM']
    msg['To'] = to_email
    msg.set_content(body)
    return msg


def mail_configured():
    """是否配置了真实 SMTP 投递。"""
    return bool(current_app.config.get('SMTP_HOST'))


def send_password_reset_email(to_email, reset_url):
    """发送找回密码邮件；未配置 SMTP 时打印到日志。"""
    ttl_min = current_app.config['RESET_TOKEN_TTL_SECONDS'] // 60
    subject = '【RISC-V AI 编译器比赛平台】重置密码'
    body = (
        f'你好，\n\n'
        f'我们收到了重置此邮箱账号密码的请求。请在 {ttl_min} 分钟内打开下面的链接设置新密码：\n\n'
        f'{reset_url}\n\n'
        f'链接仅可使用一次，且会随本次重置失效。\n'
        f'如果这不是你本人的操作，请忽略本邮件，你的密码不会改变。\n'
    )

    if not mail_configured():
        # 开发/演示退回：链接只写服务端日志，便于本地取用与测试
        current_app.logger.warning(
            '[mailer] 未配置 SMTP，重置链接仅打印到日志：to=%s url=%s', to_email, reset_url
        )
        print(f'[mailer] 未配置 SMTP。发给 {to_email} 的重置链接：{reset_url}')
        return True

    msg = _build_message(to_email, subject, body)
    try:
        host = current_app.config['SMTP_HOST']
        port = current_app.config['SMTP_PORT']
        if current_app.config['SMTP_USE_SSL']:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as s:
                _login_and_send(s, msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                if current_app.config['SMTP_USE_TLS']:
                    s.starttls(context=ssl.create_default_context())
                _login_and_send(s, msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        # 失败不抛给用户（防枚举），记日志交由运维排查
        current_app.logger.error('[mailer] 发送重置邮件失败 to=%s: %s', to_email, exc)
        return False


def _login_and_send(smtp, msg):
    user = current_app.config['SMTP_USER']
    if user:
        smtp.login(user, current_app.config['SMTP_PASSWORD'])
    smtp.send_message(msg)
