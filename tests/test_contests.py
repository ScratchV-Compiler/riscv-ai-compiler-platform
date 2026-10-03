# -*- coding: utf-8 -*-
"""多场次：隔离 / 同题复用 / 生命周期 / URL 兼容。

覆盖引入多场次后最该守住的几件事：

- 赛题规格按场次取，且**同题在两场可以不同**（局部覆盖），全局题册不被污染
- 提交 / 榜单**严格按场次隔离**（动态基准绝不跨场次相减）
- 一个用户可在不同场次各入一支队伍；队名可跨场次重名
- 生命周期：只有「进行中」的场次接受提交
- URL：未知 slug 404；旧裸路径 302 到默认场次；场次 API 正常

运行：`python tests/test_contests.py` 或 `python tests/run_all.py`
用**临时库**，不碰 platform.db。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap as boot
from _bootstrap import check

app, _TMP = boot.temp_app()

import contests                       # noqa: E402
from contests import Contest, RUNNING, UPCOMING   # noqa: E402
from models import db, Submission     # noqa: E402
import riscv_problems as RP           # noqa: E402

DEFAULT = contests.default_contest().slug


def register(slug, **kw):
    """往注册表里塞一场**测试专用**场次（子进程内有效，不影响真实配置）。"""
    c = Contest(slug=slug,
                title=kw.pop('title', slug), short_title=kw.pop('short_title', slug),
                stage_label=kw.pop('stage_label', slug), **kw)
    contests._CONTESTS.append(c)
    contests._BY_SLUG[slug] = c
    contests._SPEC_CACHE.clear()
    return c


TA = register('ta', status=RUNNING)
TB = register('tb', status=RUNNING, eval_overrides={'add': {'points_per_case': 5}})
TU = register('tu', status=UPCOMING)


def details_json(ns, pmax):
    return json.dumps({'cases': [
        {'size': n, 'verdict': 'accepted', 'cost': 100 + n,
         'instructions': 100 + n, 'points_max': pmax} for n in ns]})


# ---------------------------------------------------------------------------
# 1) 规格按场次取：同题局部覆盖，且不影响全局题册
# ---------------------------------------------------------------------------
base_add = contests.get_eval_spec('add')
check('默认场次的 add 满分 = 30（沿用全局题册）', base_add['full_score'] == 30, base_add['full_score'])
check('全局题册 EVAL_SPECS 未被改写', RP.EVAL_SPECS['add']['full_score'] == 30,
      RP.EVAL_SPECS['add']['full_score'])

spec_add_tb = contests.get_eval_spec('add', TB)
check('覆盖场次里 add 满分随 points_per_case 重算 = 50',
      spec_add_tb['full_score'] == 50, spec_add_tb['full_score'])
check('覆盖只作用于该场次：默认场次仍是 30',
      contests.get_eval_spec('add', TA)['full_score'] == 30)
check('两场拿到的是**不同**的 spec 对象（防 baseline 缓存串场）',
      contests.get_eval_spec('add', TA) is not contests.get_eval_spec('add', TB))
check('spec 结果被缓存（同场次同题返回同一对象）',
      contests.get_eval_spec('add', TA) is contests.get_eval_spec('add', TA))
check('不在本场试卷里的题取不到规格',
      contests.get_eval_spec('add', register('tempty', status=RUNNING, problem_ids=('matmul',))) is None)


# ---------------------------------------------------------------------------
# 2) 榜单 / 提交按场次隔离
# ---------------------------------------------------------------------------
with app.app_context():
    db.session.add(Submission(contest='ta', team_name='OnlyA', problem_id='add',
                              code_path='', status='success',
                              details=details_json([64, 128], 3)))
    db.session.add(Submission(contest='tb', team_name='OnlyB', problem_id='add',
                              code_path='', status='success',
                              details=details_json([64, 128], 5)))
    db.session.commit()

with app.test_client() as c:
    a = c.get('/c/ta/standings').get_data(as_text=True)
    b = c.get('/c/tb/standings').get_data(as_text=True)
    check('ta 榜含 OnlyA 且不含 OnlyB', 'OnlyA' in a and 'OnlyB' not in a)
    check('tb 榜含 OnlyB 且不含 OnlyA', 'OnlyB' in b and 'OnlyA' not in b)

    # API 列表也按场次过滤
    ja = c.get('/c/ta/api/problems').get_json()
    check('ta 的 /api/problems 带 contest 字段', all(p.get('contest') == 'ta' for p in ja))
    check('覆盖场次 tb 的 add 满分透出为 50',
          [p for p in c.get('/c/tb/api/problems').get_json() if p['id'] == 'add'][0]['full_score'] == 50)


# ---------------------------------------------------------------------------
# 3) 用户可在不同场次各入一支队伍；队名可跨场次重名
# ---------------------------------------------------------------------------
code_a = None
with app.test_client() as c:
    c.post('/api/auth/register',
           json={'email': 'multi@x.edu', 'name': '多场侠', 'password': 'pass12345'})
    r1 = c.post('/c/ta/api/team', json={'name': '同名队'})
    r2 = c.post('/c/tb/api/team', json={'name': '同名队'})   # 同队名，不同场次
    check('在场次 ta 建队成功', r1.status_code == 201, r1.get_json())
    check('同一用户在场次 tb 再建一支队成功（每场限一队，不是全局限一队）',
          r2.status_code == 201, r2.get_json())
    check('两支队名相同但属于不同场次', '同名队' in c.get('/c/ta/team').get_data(as_text=True)
          and '同名队' in c.get('/c/tb/team').get_data(as_text=True))

    # 同一用户在同一场次不能建第二支队
    r3 = c.post('/c/ta/api/team', json={'name': '另一队'})
    check('同一场次内不能建第二支队', r3.status_code == 409, r3.get_json())
    code_a = r1.get_json()['team']['invite_code']

# 注意：test client 的 `with` 会**保留请求上下文**，嵌套两个 client 会让 g 串场——
# 所以乙的检查放在独立的一层，不嵌在上面的 with 里。
with app.test_client() as c2:
    c2.post('/api/auth/register',
            json={'email': 'mate2@x.edu', 'name': '乙', 'password': 'pass12345'})
    bad = c2.post('/c/tb/api/team/join', json={'invite_code': code_a})
    check('拿 ta 的邀请码在 tb 入队被拒', bad.status_code in (404, 409), bad.get_json())
    good = c2.post('/c/ta/api/team/join', json={'invite_code': code_a})
    check('拿 ta 的邀请码在 ta 入队成功', good.status_code == 200, good.get_json())


# ---------------------------------------------------------------------------
# 4) 生命周期：只有「进行中」接受提交
# ---------------------------------------------------------------------------
with app.test_client() as c:
    c.post('/api/auth/register',
           json={'email': 'life@x.edu', 'name': '生', 'password': 'pass12345'})
    c.post('/c/tu/api/team', json={'name': '未开赛队'})
    r = c.post('/c/tu/api/submit', data={'problem': 'add', 'source': '.text\n.globl cnn_entry\ncnn_entry:\n'},
               content_type='multipart/form-data')
    check('未开始的场次拒绝提交 400', r.status_code == 400, r.get_json())
    check('拒绝原因 = closed（生命周期闸门，而非题目不存在）',
          (r.get_json() or {}).get('reason') == 'closed', r.get_json())

# 未开始的场次**不许参加**：组队与入队都要挡住（不只是提交）
from auth import create_team, join_team            # noqa: E402
with app.test_client() as c:
    c.post('/api/auth/register',
           json={'email': 'closed@x.edu', 'name': '未开', 'password': 'pass12345'})
    r = c.post('/c/tu/api/team', json={'name': '提前组队'})
    check('未开始的场次：建队被拒 409',
          r.status_code == 409 and '参加' in (r.get_json() or {}).get('error', ''),
          r.get_json())
    r = c.post('/c/tu/api/team/join', json={'invite_code': 'ABCD2345'})
    check('未开始的场次：入队被拒', r.status_code in (404, 409, 410), r.get_json())

with app.app_context():
    from models import User
    u = User.query.filter_by(email='closed@x.edu').first()
    _, e1 = create_team(u, 'tu', '提前组队')
    _, e2 = join_team(u, 'tu', 'ABCD2345')
    check('create_team 在未开始场次被拒', bool(e1) and '参加' in e1, e1)
    check('join_team 在未开始场次被拒', bool(e2) and '参加' in e2, e2)
    _, e3 = create_team(u, 'ta', '正常队名')
    check('进行中的场次不受影响：建队成功', e3 is None, e3)


# ---------------------------------------------------------------------------
# 4b) 提交间隔（节流）按场次独立计时
# ---------------------------------------------------------------------------
from auth import submit_wait_seconds, mark_submitted   # noqa: E402
from models import User                                 # noqa: E402

with app.app_context():
    u = User(email='throttle@x.edu', name='节流', role='player')
    u.set_password('pass12345')
    db.session.add(u)
    db.session.commit()
    uid = u.id

    check('初始时两场都可提交',
          submit_wait_seconds(u, 'ta') == 0 and submit_wait_seconds(u, 'tb') == 0)
    mark_submitted(u, 'ta')                       # 在 ta 交一次
    check('在 ta 交完后，ta 被限流', submit_wait_seconds(u, 'ta') > 0)
    check('在 ta 交完后，tb **不受影响**（每场各自计时）',
          submit_wait_seconds(u, 'tb') == 0,
          f"tb wait={submit_wait_seconds(u, 'tb')}")
    mark_submitted(u, 'tb')
    check('两场各自独立计时：ta、tb 都被限流',
          submit_wait_seconds(u, 'ta') > 0 and submit_wait_seconds(u, 'tb') > 0)


# ---------------------------------------------------------------------------
# 5) URL：未知 slug 404；旧裸路径 302 到默认场次
# ---------------------------------------------------------------------------
with app.test_client() as c:
    check('未知 slug → 404', c.get('/c/does-not-exist/standings').status_code == 404)
    r = c.get('/standings')
    check('旧 /standings → 302 到默认场次',
          r.status_code == 302 and r.headers.get('Location', '').endswith('/c/%s/standings' % DEFAULT),
          r.headers.get('Location'))
    r = c.get('/problems')
    check('旧 /problems → 302 到默认场次',
          r.status_code == 302 and '/c/%s/problems' % DEFAULT in r.headers.get('Location', ''),
          r.headers.get('Location'))
    check('默认场次 /c/<slug>/ 正常 200', c.get('/c/%s/' % DEFAULT).status_code == 200)
    check('场次目录页 200 且列出多场', c.get('/contests').status_code == 200
          and 'ta' in c.get('/contests').get_data(as_text=True))
    # 最外层 = 场次目录：`/` 直接是目录（不是重定向进第一场）
    r = c.get('/')
    body = r.get_data(as_text=True)
    check('根 / 就是场次目录（200，非 302）', r.status_code == 200, r.status_code)
    check('根 / 列出多个场次（而非直接进第一场）',
          '全部场次' in body and 'ta' in body and 'tb' in body)
    # 场次内的导航/右栏只在**进入某场后**才出现（目录页不该把默认场次当「当前场次」）
    check('目录页不显示场次内导航（本场首页/评分口径）',
          '本场首页' not in body and '评分口径' not in body)
    inside = c.get('/c/%s/' % DEFAULT).get_data(as_text=True)
    check('进入场次后才出现场次内导航与场次右栏',
          '本场首页' in inside and '本场次' in inside)

boot.finish('多场次')
