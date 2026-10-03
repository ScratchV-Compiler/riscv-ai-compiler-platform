# -*- coding: utf-8 -*-
"""队伍生命周期：建队 / 入队 / 退队 / 恢复解散的队伍。

重点覆盖**独苗队长退队**这个坑：退队会把队伍标记解散（不删行），
于是邀请码作废、队名仍被 DB 的 unique 约束占着——没有恢复入口的话，
这个人就被永久挡在自己的队名之外。

运行：`python tests/test_team_lifecycle.py` 或 `python tests/run_all.py`
用**临时库**，不碰 platform.db。
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap as boot
from _bootstrap import check

app, _TMP = boot.temp_app()
_DB = os.path.join(_TMP, 'test.db')


def q(sql, *args):
    """直接查库看真状态——比再开一个 test client 可靠（避免会话串扰）。"""
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(sql, args)]
    con.close()
    return rows


def in_team(email):
    return bool(q("select 1 from team_members tm join users u on u.id = tm.user_id "
                  "where u.email = ?", email))


# ---- 建队 → 退队（独苗队长）----
with app.test_client() as c:
    c.post('/api/auth/register',
           json={'email': 'solo@x.edu', 'name': '独行侠', 'password': 'pass12345'})
    code = c.post('/c/riscv-ai/api/team', json={'name': '独苗队'}).get_json()['team']['invite_code']
    check('建队成功并拿到邀请码', bool(code), code)

    c.post('/c/riscv-ai/api/team/leave')
    check('退队后不在任何队伍', not in_team('solo@x.edu'))
    row = q("select disbanded_at, invite_code from teams where name = '独苗队'")[0]
    check('队伍行仍在，但已标记解散', row['disbanded_at'] is not None, row['disbanded_at'])

    # ---- 恢复入口 ----
    body = c.get('/c/riscv-ai/team/join').get_data(as_text=True)
    check('无队伍的队长在建队页看到「恢复」入口',
          '恢复之前的队伍' in body and '独苗队' in body)

    r = c.post('/c/riscv-ai/api/team', json={'name': '独苗队'})
    err = (r.get_json() or {}).get('error', '')
    check('建同名队时提示改用「恢复」而不是干巴巴的「已被占用」',
          r.status_code == 409 and '恢复' in err, err)

    # ---- 恢复 ----
    r = c.post('/c/riscv-ai/team/restore')
    check('恢复成功并跳回队伍页',
          r.status_code == 302 and '/team' in r.headers.get('Location', ''), r.status_code)

    row = q("select disbanded_at, invite_code from teams where name = '独苗队'")[0]
    check('disbanded_at 已清空', row['disbanded_at'] is None)
    check('邀请码已更换（旧码作废且可能已泄露给前队员）',
          row['invite_code'] != code, f"{code} -> {row['invite_code']}")
    check('已重新入队', in_team('solo@x.edu'))
    new_code = row['invite_code']

# ---- 旧码失效、新码可用 ----
with app.test_client() as c2:
    c2.post('/api/auth/register',
            json={'email': 'mate@x.edu', 'name': '队友', 'password': 'pass12345'})
    check('新用户初始无队伍', not in_team('mate@x.edu'))

    r = c2.post('/c/riscv-ai/api/team/join', json={'invite_code': code})
    check('恢复前的旧邀请码已失效', r.status_code == 404, r.get_json())

    r = c2.post('/c/riscv-ai/api/team/join', json={'invite_code': new_code})
    check('新邀请码可正常入队', r.status_code == 200, r.get_json())
    check('队友确实入队', in_team('mate@x.edu'))

    # 非队长不该看到别人的恢复入口
    check('非队长看不到「恢复」入口',
          '恢复之前的队伍' not in c2.get('/c/riscv-ai/team/join').get_data(as_text=True))

boot.finish('队伍生命周期')
