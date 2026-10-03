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
from contests import Contest, RUNNING, UPCOMING, ENDED   # noqa: E402
from models import db, Submission     # noqa: E402
import riscv_problems as RP           # noqa: E402

DEFAULT = contests.default_contest().slug


def register(slug, **kw):
    """往注册表里塞一场**测试专用**场次（子进程内有效，不影响真实配置）。"""
    c = Contest(slug=slug,
                title=kw.pop('title', slug), short_title=kw.pop('short_title', slug),
                **kw)
    contests._CONTESTS.append(c)
    contests._BY_SLUG[slug] = c
    contests._SPEC_CACHE.clear()
    return c


TA = register('ta', status=RUNNING)
TB = register('tb', status=RUNNING, eval_overrides={'add': {'points_per_case': 5}})
TU = register('tu', status=UPCOMING)
TE = register('te', status=ENDED)


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
# 4) 生命周期：两道闸
#    - **进入**闸（is_enterable）：未开始 → 整场进不去
#    - **参加**闸（is_open）：已结束可进（只读归档），但不能组队/提交
# ---------------------------------------------------------------------------
with app.test_client() as c:
    check('未开始的场次：首页进不去（403）', c.get('/c/tu/').status_code == 403)
    check('未开始的场次：榜单页也进不去', c.get('/c/tu/standings').status_code == 403)
    check('未开始的场次：提交页也进不去', c.get('/c/tu/submit').status_code == 403)
    r = c.get('/c/tu/api/problems')
    check('未开始的场次：API 被挡（403 + reason=not_started）',
          r.status_code == 403 and (r.get_json() or {}).get('reason') == 'not_started',
          r.get_json())
    check('目录页不给未开始的场次「进入」入口',
          '未开放，暂不能进入' in c.get('/contests').get_data(as_text=True))
    check('已结束的场次：能进（归档可看）', c.get('/c/te/').status_code == 200)

# 已结束：进得去，但**不能参加**（组队 / 提交都被挡）
from auth import create_team, join_team            # noqa: E402
with app.test_client() as c:
    c.post('/api/auth/register',
           json={'email': 'ended@x.edu', 'name': '终', 'password': 'pass12345'})
    r = c.post('/c/te/api/team', json={'name': '收尾队'})
    check('已结束的场次：建队被拒 409（不能参加）',
          r.status_code == 409 and '参加' in (r.get_json() or {}).get('error', ''),
          r.get_json())
    r = c.post('/c/te/api/team/join', json={'invite_code': 'ABCD2345'})
    check('已结束的场次：入队被拒', r.status_code in (404, 409, 410), r.get_json())
    r = c.post('/c/te/api/submit',
               data={'problem': 'add', 'source': '.text\n.globl cnn_entry\ncnn_entry:\n'},
               content_type='multipart/form-data')
    check('已结束的场次：提交被拒（closed）',
          r.status_code == 400 and (r.get_json() or {}).get('reason') == 'closed',
          r.get_json())

with app.app_context():
    from models import User
    u = User.query.filter_by(email='ended@x.edu').first()
    _, e1 = create_team(u, 'te', '收尾队')
    _, e2 = join_team(u, 'te', 'ABCD2345')
    check('create_team 在已结束场次被拒', bool(e1) and '参加' in e1, e1)
    check('join_team 在已结束场次被拒', bool(e2) and '参加' in e2, e2)
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

# ---------------------------------------------------------------------------
# 6) 配额「按人计」（不随换队刷新）；每人每天只能退队一次
# ---------------------------------------------------------------------------
from datetime import datetime                                    # noqa: E402
from auth import user_quota_used, leaves_today, leave_team      # noqa: E402

with app.app_context():
    q_u = User(email='quota@x.edu', name='配额', role='player')
    q_u.set_password('pass12345')
    db.session.add(q_u)
    db.session.commit()
    qid = q_u.id
    now = datetime.utcnow()
    # 同一用户在**两个不同队名**下各交一条 —— 按人计就该算 2
    for tn in ('队甲', '队乙'):
        db.session.add(Submission(contest='ta', user_id=qid, team_name=tn,
                                  problem_id='add', code_path='', status='success',
                                  created_at=now))
    # 一条没有提交人的（老数据）——不计入任何人
    db.session.add(Submission(contest='ta', user_id=None, team_name='别人队',
                              problem_id='add', code_path='', status='success',
                              created_at=now))
    # 同一个人在**别场**的提交——按场次隔离，不该算进 ta
    db.session.add(Submission(contest='tb', user_id=qid, team_name='队甲',
                              problem_id='add', code_path='', status='success',
                              created_at=now))
    db.session.commit()

    check('配额按**人**计：同一用户在 ta 换过两个队名也只累计 1 条/队 → 计 2（且不含无主数据）',
          user_quota_used(q_u, 'ta') == 2, user_quota_used(q_u, 'ta'))
    check('配额仍按场次隔离：ta 的计数不含 tb',
          user_quota_used(q_u, 'tb') == 1, user_quota_used(q_u, 'tb'))

# 每人每天只能退队一次
with app.app_context():
    q_u = User.query.filter_by(email='quota@x.edu').first()
    _, err = create_team(q_u, 'ta', '换队测试队')
    check('建队成功（进行中）', err is None, err)
    _, e1 = leave_team(q_u, 'ta')
    check('第一次退队成功', e1 is None, e1)
    check('退队流水记了 1 条', leaves_today(q_u, 'ta') == 1, leaves_today(q_u, 'ta'))
    _, err2 = create_team(q_u, 'ta', '再建一队')
    check('退队后当天可再建队（限的是"退"不是"入"）', err2 is None, err2)
    _, e2 = leave_team(q_u, 'ta')
    check('同一天第二次退队被拒',
          bool(e2) and '只能退出一次' in e2, e2)

# ---------------------------------------------------------------------------
# 7) 报名机制：需报名的场次要**个人报名**才能组队；未开始的场次也能报名
# ---------------------------------------------------------------------------
from auth import is_enrolled, enroll, unenroll                  # noqa: E402

TR = register('tr', status=RUNNING, requires_registration=True,
              registration_code='TRCODE')
TU2 = register('tu2', status=UPCOMING, requires_registration=True,
               registration_code='TU2CODE')

with app.app_context():
    e_u = User(email='enroll@x.edu', name='报名', role='player')
    e_u.set_password('pass12345')
    db.session.add(e_u)
    db.session.commit()

    check('无需报名的场次：is_enrolled 恒真', is_enrolled(e_u, TA) is True)
    check('需报名的场次：未报名 → is_enrolled False', is_enrolled(e_u, TR) is False)
    _, err = create_team(e_u, 'tr', '未报名队')
    check('未报名不能组队', bool(err) and '报名' in err, err)

    _, err = enroll(e_u, TR)
    check('缺邀请码不能报名', bool(err) and '邀请码' in err, err)
    _, err = enroll(e_u, TR, 'WRONG')
    check('邀请码错误不能报名', bool(err) and '不正确' in err, err)
    _, err = enroll(e_u, TR, 'TRCODE')
    check('邀请码正确 → 报名成功', err is None, err)
    check('报名后 is_enrolled True', is_enrolled(e_u, TR) is True)
    _, err = create_team(e_u, 'tr', '已报名队')
    check('报名后可以组队', err is None, err)
    _, err = unenroll(e_u, TR)
    check('有队伍时不能取消报名（先退队）', bool(err) and '退队' in err, err)

with app.test_client() as c:
    c.post('/api/auth/register',
           json={'email': 'enroll2@x.edu', 'name': '报二', 'password': 'pass12345'})
    r = c.post('/c/tu2/enroll', data={'code': 'TU2CODE'}, follow_redirects=False)
    check('未开始的场次：报名接口放行（302，入口闸例外）', r.status_code == 302, r.status_code)
    check('未开始的场次：场次页仍然锁死（403）', c.get('/c/tu2/').status_code == 403)
    r = c.post('/c/tu2/unenroll', follow_redirects=False)
    check('未开始的场次：也能取消报名', r.status_code == 302, r.status_code)

with app.test_client() as c:
    body = c.get('/contests').get_data(as_text=True)
    check('目录页（首页）同时标出「无需报名」与「需报名」',
          '无需报名' in body and '需报名' in body)

# ---------------------------------------------------------------------------
# 7b) 赛程：配了报名日期 → 报名窗口按日期（而非状态）开关
# ---------------------------------------------------------------------------
from datetime import timedelta                                  # noqa: E402

with app.app_context():
    past = datetime.utcnow() - timedelta(days=1)
    future = datetime.utcnow() + timedelta(days=1)
    closed = register('trc', status=RUNNING, requires_registration=True,
                      registration_end=past)
    notyet = register('trn', status=RUNNING, requires_registration=True,
                      registration_start=future)
    openn = register('tro', status=RUNNING, requires_registration=True,
                     registration_start=past, registration_end=future)
    undated = register('tru', status=RUNNING, requires_registration=True)

    check('报名截止日已过 → 不能报名', closed.registration_open is False)
    check('报名开始日在未来 → 还不能报名', notyet.registration_open is False)
    check('处于报名窗口内 → 可报名', openn.registration_open is True)
    check('未配日期 → 按状态兜底（进行中可报）', undated.registration_open is True)

    e_u = User.query.filter_by(email='enroll@x.edu').first()
    _, e = enroll(e_u, closed)
    check('已截止的场次 enroll 被拒', bool(e) and '截止' in e, e)

# ---------------------------------------------------------------------------
# 8) 需报名的场次：**没报名看不到内容**（不只是"不能参赛"）
# ---------------------------------------------------------------------------
with app.test_client() as c:
    check('需报名的场次：匿名进不去（403）', c.get('/c/tr/').status_code == 403)
    check('需报名的场次：赛题页也看不到', c.get('/c/tr/problems').status_code == 403)
    check('需报名的场次：榜单页也看不到', c.get('/c/tr/standings').status_code == 403)
    r = c.get('/c/tr/api/problems')
    check('需报名的场次：API 挡住（reason=need_enroll）',
          r.status_code == 403 and (r.get_json() or {}).get('reason') == 'need_enroll',
          r.get_json())

with app.app_context():
    eid = User.query.filter_by(email='enroll@x.edu').first().id   # 第 7 节已在 tr 报名

with app.test_client() as c:
    with c.session_transaction() as s:      # 注入登录态（不写库）
        s['uid'] = eid
    check('已报名者可进入该场次内容（200）', c.get('/c/tr/').status_code == 200,
          c.get('/c/tr/').status_code)
    check('已报名者能看到赛题页', c.get('/c/tr/problems').status_code == 200)

# 已结束的场次：报名闸不生效，**对所有人公开**（含匿名）
TER = register('ter', status=ENDED, requires_registration=True)
with app.test_client() as c:
    check('已结束+需报名：匿名也能进（归档公开）', c.get('/c/ter/').status_code == 200)
    check('已结束+需报名：赛题页公开', c.get('/c/ter/problems').status_code == 200)
    check('已结束+需报名：榜单页公开', c.get('/c/ter/standings').status_code == 200)
    body = c.get('/contests').get_data(as_text=True)
    check('目录页把已结束的报名场标为「已结束 · 公开」', '已结束 · 公开' in body)

# ---------------------------------------------------------------------------
# 9) 真实配置：阶段赛程 + 报名邀请码
# ---------------------------------------------------------------------------
from contests import get_contest, beijing, Stage              # noqa: E402

with app.app_context():
    d = get_contest('demo')
    a = get_contest('riscv-ai')
    check('demo 的报名邀请码是 demo', d.registration_code == 'demo', d.registration_code)
    check('两场都是「阶段 1 / 阶段 2」',
          [s.label for s in a.stages] == ['Stage 1', 'Stage 2']
          and [s.label for s in d.stages] == ['Stage 1', 'Stage 2'],
          [s.label for s in a.stages])
    check('Stage 2 = 10.31 08:00 ~ 11.30 08:00（北京）',
          a.stages[1].start_at == beijing(2026, 10, 31, 8, 0)
          and a.stages[1].end_at == beijing(2026, 11, 30, 8, 0),
          (a.stages[1].start_at, a.stages[1].end_at))
    check('Stage 1 = 10.01 08:00 ~ 10.31 08:00（北京）',
          a.stages[0].start_at == beijing(2026, 10, 1, 8, 0)
          and a.stages[0].end_at == beijing(2026, 10, 31, 8, 0))

# ---------------------------------------------------------------------------
# 10) 当前阶段由**日期**推出，拼进状态显示（页面不再有独立「阶段」标签）
# ---------------------------------------------------------------------------
with app.app_context():
    now = datetime.utcnow()
    within = register('tst', status=RUNNING, stages=(
        Stage('Stage 1', now - timedelta(days=1), now + timedelta(days=1)),
        Stage('Stage 2', now + timedelta(days=2), now + timedelta(days=3)),
    ))
    check('处在 Stage 1 → 状态含「Stage 1」',
          within.status_display == '进行中 · Stage 1', within.status_display)
    check('current_stage 命中 Stage 1', within.current_stage.label == 'Stage 1')

    outside = register('tso', status=RUNNING, stages=(
        Stage('Stage 1', now + timedelta(days=5), now + timedelta(days=6)),
    ))
    check('不在任何阶段内 → 只显示状态',
          outside.status_display == '进行中', outside.status_display)
    check('未配阶段的场次 → 只显示状态', TA.status_display == '进行中', TA.status_display)

    check('真实配置：今天（2026-10-03）内测比赛1 显示 Stage 1',
          get_contest('riscv-ai').status_display == '进行中 · Stage 1',
          get_contest('riscv-ai').status_display)

boot.finish('多场次')
