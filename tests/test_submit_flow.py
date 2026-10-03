# -*- coding: utf-8 -*-
"""提交流程端到端。

运行：`python tests/test_submit_flow.py` 或 `python tests/run_all.py`
用**临时库**，不碰 platform.db。
"""
import os
import sys
import tempfile
import io
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap as boot
from _bootstrap import check

app, _TMP = boot.temp_app()
ROOT = boot.ROOT
import config

def upload(name, content):
    """构造 multipart 形式的文件字段。"""
    return (io.BytesIO(content), name)

def clear_throttle():
    """清空提交间隔限流（模拟『两分钟已过去』）——本测试连续提交，
    必然撞上 v1.15 加的提交间隔。"""
    boot.clear_throttle(_TMP)


REF = open(os.path.join(ROOT, 'reference/matmul.s'), 'rb').read()

import sqlite3
_DB = config.Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')

def clear_throttle():
    """清空提交间隔限流——测试里模拟"两分钟已过去"。
    提交间隔是 v1.15 加的功能，本测试连续提交必然撞上，故每次提交前清掉。"""
    con = sqlite3.connect(_DB)
    con.execute('delete from submit_throttle')
    con.commit(); con.close()

def submit_reset():
    clear_throttle()

def upload(name, content):
    return (io.BytesIO(content), name)

with app.test_client() as c:
    # --- 登录前访问 /submit 应跳登录 ---
    r = c.get('/c/riscv-ai/submit')
    check('/submit 未登录 → 302 到 /login', r.status_code == 302 and '/login' in r.headers.get('Location',''), r.status_code)

    # --- 注册 + 建队 ---
    c.post('/api/auth/register', json={'email':'a@stu.ecnu.edu.cn','name':'甲','password':'pass12345'})
    r = c.post('/c/riscv-ai/api/team', json={'name': '矩阵小队'})
    check('建队 201', r.status_code == 201, r.status_code)

    # --- 提交页 ---
    r = c.get('/c/riscv-ai/submit')
    body = r.get_data(as_text=True)
    check('/submit 200 且默认落到首个可提交题', r.status_code == 200 and '逐元素相加' in body, r.status_code)
    check('提交页含 cnn_entry 约定', 'cnn_entry' in body)

    # --- 未入队的用户提交应被拒 ---
    clear_throttle()
    c2 = app.test_client()
    c2.post('/api/auth/register', json={'email':'b@stu.ecnu.edu.cn','name':'乙','password':'pass12345'})
    r = c2.post('/c/riscv-ai/submit', data={'problem':'matmul','code': upload('k.s', REF)},
                content_type='multipart/form-data')
    check('未入队提交被拒（回提交页）', r.status_code == 302, r.status_code)

    clear_throttle()
    # --- 正常提交 ---
    r = c.post('/c/riscv-ai/submit', data={'problem':'matmul','code': upload('matmul.s', REF)},
               content_type='multipart/form-data')
    check('提交成功 → 302 到结果页', r.status_code == 302 and '/result/' in r.headers.get('Location',''),
          r.headers.get('Location'))
    sub_id = int(r.headers['Location'].rstrip('/').split('/')[-1])

    # --- 后缀不对应被拒 ---
    r = c.post('/c/riscv-ai/api/submit', data={'problem':'matmul','code': upload('x.py', b'print(1)')},
               content_type='multipart/form-data')
    check('错误后缀被拒 400', r.status_code == 400, r.get_json())

    # --- 已下线的题目应被拒 ---
    r = c.post('/c/riscv-ai/api/submit', data={'problem':'add-two-numbers','code': upload('x.s', REF)},
               content_type='multipart/form-data')
    check('已下线题目提交被拒 400', r.status_code == 400, r.get_json())

    clear_throttle()
    # --- 粘贴代码提交 ---
    r = c.post('/c/riscv-ai/submit', data={'problem':'matmul','source': REF.decode()},
               content_type='multipart/form-data')
    check('粘贴代码提交成功 → 302 结果页', r.status_code == 302 and '/result/' in r.headers.get('Location',''),
          r.status_code)
    pid = r.headers.get('Location','').rstrip('/').split('/')[-1]
    d = None
    for _ in range(60):
        d = c.get(f'/c/riscv-ai/api/result/{pid}').get_json()
        if d['status'] in ('success','failed'): break
        time.sleep(1)
    det2 = json.loads(d['details'])
    check('粘贴的参考解同样判 accepted 满分', d['status']=='success' and det2['score']==30.0,
          f"{d['status']} {det2.get('verdict')} {det2.get('score')}")

    # --- 空粘贴 + 无文件 → 拒绝 ---
    r = c.post('/c/riscv-ai/api/submit', data={'problem':'matmul','source':'   \n  '},
               content_type='multipart/form-data')
    check('空白粘贴被拒 400', r.status_code == 400, r.get_json())

    clear_throttle()
    # --- 同时提供文件与粘贴 → 以文件为准（文件是坏的，若粘贴生效就会通过）---
    r = c.post('/c/riscv-ai/api/submit', data={'problem':'matmul','source': REF.decode(),
                                    'code': upload('bad.s', b'.text\n.globl cnn_entry\ncnn_entry:\n  bogus x0,x0,x0\n')},
               content_type='multipart/form-data')
    check('API 提交 201', r.status_code == 201, r.get_json())
    pid3 = r.get_json()['submission_id']
    d3 = None
    for _ in range(60):
        d3 = c.get(f'/c/riscv-ai/api/result/{pid3}').get_json()
        if d3['status'] in ('success','failed'): break
        time.sleep(1)
    det3 = json.loads(d3['details'])
    check('文件与粘贴同时给出 → 以文件为准（判编译失败）', det3['verdict']=='compile_error',
          det3.get('verdict'))

    # --- 空文件被拒 ---
    r = c.post('/c/riscv-ai/api/submit', data={'problem':'matmul','code': upload('e.s', b'')},
               content_type='multipart/form-data')
    check('空文件被拒 400', r.status_code == 400, r.get_json())

    # --- 轮询直到终态 ---
    deadline = time.time() + 90
    data = None
    while time.time() < deadline:
        data = c.get(f'/c/riscv-ai/api/result/{sub_id}').get_json()
        if data['status'] in ('success', 'failed'):
            break
        time.sleep(1)
    check('评测到达终态', data['status'] in ('success','failed'), data['status'])
    check('参考解判为 success', data['status'] == 'success', data['status'])
    det = json.loads(data['details'])
    check('verdict=accepted 且满分', det['verdict']=='accepted' and det['score']==30.0,
          f"verdict={det['verdict']} score={det['score']}")

    # --- 结果页渲染 ---
    r = c.get(f'/c/riscv-ai/result/{sub_id}')
    body = r.get_data(as_text=True)
    check('结果页 200', r.status_code == 200, r.status_code)
    # 结果页显示的是**动态基准**下的实时得分，会低于评测时的快照分
    # （演示队伍的成绩更好、把基准拉高了），所以不能断言固定值
    check('结果页显示得分与用例', '得分：' in body and '用例明细' in body and '动态基准' in body)
    check('结果页不再出现占位字段 cycles', 'cycles' not in body)

    # --- 排行榜应把它算进去 ---
    r = c.get('/c/riscv-ai/standings')
    check('排行榜 200', r.status_code == 200, r.status_code)

boot.finish('提交流程端到端')
