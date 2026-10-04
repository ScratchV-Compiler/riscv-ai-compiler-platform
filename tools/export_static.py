# -*- coding: utf-8 -*-
"""把本平台导出为**纯静态站点**，用于部署到 GitHub Pages。

为什么需要它
------------
GitHub Pages 只能托管静态文件，而本平台是 Flask 动态应用（SQLite + 后台 worker + POST 提交）。
因此这里只导出**只读页面**（首页 / 赛题 / 题目详情 / 排行榜 / 帮助 / 结果页），
并统一把站点内部的绝对路径改写为**扁平相对文件名**——因为 GitHub Pages 的项目页
地址形如 `https://<user>.github.io/<repo>/`，绝对路径 `/static/style.css` 会指到域名根而 404。

做法
----
用 Flask 自带的 test client 渲染各路由（不需要起服务），再对 HTML 做一次 URL 改写；
需要登录/后端的功能页（提交、登录、注册、入队）改为跳转到 `demo-notice.html` 说明页。

用法
----
    python tools/export_static.py            # 产物写到 ./dist
"""
import os
import re
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import app  # noqa: E402  （导入即建库 + 导入 demo 数据，保证静态站有榜单可展示）
from models import Submission  # noqa: E402
import contests  # noqa: E402

OUT_DIR = os.path.join(BASE_DIR, 'dist')

# 需要登录 / 需要后端的页面 → 统一指到说明页（会被加上各场次前缀）
NEEDS_BACKEND_SUFFIXES = {
    '/team': 'demo-notice.html',        # 需登录，匿名访问会被重定向 ⇒ 直接指说明页
    '/team/join': 'demo-notice.html',
    '/submit': 'demo-notice.html',      # 需登录 + 后端
}
NEEDS_BACKEND = {
    '/login': 'login.html',      # 页面本身可静态展示（表单会降级跳说明页）
    '/register': 'register.html',
}


def _cname(c, base):
    """默认场次用不带后缀的文件名，其它场次加 -<slug>，便于根 index.html 指向默认场次。"""
    return f'{base}.html' if c.default else f'{base}-{c.slug}.html'


def index_name(c):
    """场次首页——根 `index.html` 留给「赛事目录」，所以场次一律带 slug 后缀。"""
    return f'index-{c.slug}.html'


def problems_name(c):
    return _cname(c, 'problems')


def problem_name(c, pid):
    return f'problem-{c.slug}-{pid}.html'


def help_name(c):
    return _cname(c, 'help')


def standings_name(c, problem):
    base = 'standings' if c.default else f'standings-{c.slug}'
    return f'{base}.html' if problem == 'all' else f'{base}-{problem}.html'


def frag_name(c, problem):
    base = 'frag-standings' if c.default else f'frag-standings-{c.slug}'
    return f'{base}.html' if problem == 'all' else f'{base}-{problem}.html'


def result_name(c, rid):
    return f'result-{c.slug}-{rid}.html'

DEMO_BANNER = (
    '<div style="background:#fff4d6;border-bottom:1px solid #e6cf95;color:#5b4708;'
    'padding:.5rem 1rem;font-size:.9rem;text-align:center">'
    '📄 <b>静态演示版</b>（GitHub Pages）：页面与榜单为真机平台的离线导出快照；'
    '<b>提交代码 / 注册登录 / 建队入队</b>需要后端服务，此处不可用。'
    '真实平台运行在比赛服务器上。'
    '</div>'
)

DEMO_NOTICE = """<!DOCTYPE html>
<html lang="zh-CN" data-bs-theme="light"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>演示版说明 · RISC-V AI 编译器比赛平台</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="static/style.css"></head>
<body>%s
<div class="container py-5" style="max-width:720px">
  <h1 class="h4 mb-3">该功能在静态演示版中不可用</h1>
  <p class="text-secondary">这里是部署在 GitHub Pages 上的<b>离线快照</b>，只包含只读页面。</p>
  <ul>
    <li>✅ 可浏览：首页、赛题、题目详情、排行榜（含按赛题筛选）、帮助、结果页</li>
    <li>❌ 需要后端：代码提交与评测、注册 / 登录、创建与加入队伍</li>
  </ul>
  <p class="text-secondary">这些功能需要运行中的 Flask 服务 + 数据库 + 后台评测 worker，GitHub Pages 无法承载。</p>
  <a class="btn btn-brand mt-2" href="index.html">返回首页</a>
</div></body></html>
""" % DEMO_BANNER


def build_url_map(results_by_contest):
    """站点内部绝对路径 → 静态文件名。未登记的交给 resolve() 兜底。

    每场次一套 `/c/<slug>/...` 路径；旧的裸路径（`/standings` 等）映射到**默认场次**，
    因为它们会 302 过去。
    """
    m = {
        '/': 'index.html',          # 最外层 = 场次目录
        '/contests': 'index.html',  # 同页的另一个入口
        '/demo-notice.html': 'demo-notice.html',
    }
    for c in contests.all_contests():
        pre = '/c/%s' % c.slug
        pids = contests.contest_problem_ids(c)
        m[pre + '/'] = index_name(c)
        m[pre + '/problems'] = problems_name(c)
        m[pre + '/help'] = help_name(c)
        for pid in pids:
            m['%s/problems/%s' % (pre, pid)] = problem_name(c, pid)
        for p in ['all'] + pids:
            m['%s/standings?problem=%s' % (pre, p)] = standings_name(c, p)
            m['%s/frag/standings?problem=%s' % (pre, p)] = frag_name(c, p)
        m[pre + '/standings'] = standings_name(c, 'all')
        m[pre + '/frag/standings'] = frag_name(c, 'all')
        for rid in results_by_contest.get(c.slug, []):
            m['%s/result/%d' % (pre, rid)] = result_name(c, rid)
        for suf, f in NEEDS_BACKEND_SUFFIXES.items():
            m[pre + suf] = f

    d = contests.default_contest()
    dpids = contests.contest_problem_ids(d)
    # 旧裸路径 → 默认场次产物
    m['/problems'] = problems_name(d)
    m['/standings'] = standings_name(d, 'all')
    m['/help'] = help_name(d)
    m['/frag/standings'] = frag_name(d, 'all')
    m['/api/problems'] = 'api-problems.json'
    for pid in dpids:
        m['/problems/%s' % pid] = problem_name(d, pid)
    for p in ['all'] + dpids:
        m['/standings?problem=%s' % p] = standings_name(d, p)
        m['/frag/standings?problem=%s' % p] = frag_name(d, p)
    for rid in results_by_contest.get(d.slug, []):
        m['/result/%d' % rid] = result_name(d, rid)
    for u, f in NEEDS_BACKEND.items():
        m[u] = f
    return m


def resolve(url, url_map):
    """把一个站点内部 URL 解析成静态文件名；静态资源与外部链接原样返回。"""
    if url.startswith('//') or '://' in url or url.startswith('#') or url.startswith('mailto:'):
        return url
    if not url.startswith('/'):
        return url
    if url.startswith('/static/'):
        return url[1:]                      # /static/x.css → static/x.css
    if url in url_map:
        return url_map[url]
    # /api/... 或场次下的 API：静态站没有后端，指到说明页
    if '/api/' in url or url.startswith('/api/'):
        return 'demo-notice.html'
    return url_map.get('/demo-notice.html')


ATTR_RE = re.compile(r'(href|src|action|hx-get|hx-post)="([^"]*)"')


def rewrite(html, url_map):
    """改写页面内所有 href/src/action/hx-* 的站点内部路径。"""
    def repl(mo):
        attr, raw = mo.group(1), mo.group(2)
        # Jinja 会把查询串里的 & 转义成 &amp;，先还原再匹配，否则 /standings?problem=X&amp;stage=1
        # 这类带参数的 URL 会匹配不上映射表（曾经因此把筛选链接全指到了说明页）
        val = raw.replace('&amp;', '&')
        if attr == 'action' and val.startswith('/api/'):
            # 表单提交在静态站无法处理：改成 GET + 说明页，至少不会 404 得莫名其妙
            return 'action="demo-notice.html"'
        new = resolve(val, url_map)
        return '%s="%s"' % (attr, new.replace('&', '&amp;'))   # 再转义回合法 HTML
    html = ATTR_RE.sub(repl, html)
    # POST 表单在 Pages 上不可用 → 统一降级为 GET
    html = html.replace('method="post"', 'method="get"')
    return html


def pull(client, path, url_map):
    """渲染一个路由（跟随重定向），返回改写后的 HTML。"""
    resp = client.get(path, follow_redirects=True)
    html = resp.get_data(as_text=True)
    return rewrite(html, url_map), resp


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name in os.listdir(OUT_DIR):
        p = os.path.join(OUT_DIR, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)

    with app.app_context():
        results_by_contest = {}
        for r in Submission.query.order_by(Submission.id).all():
            results_by_contest.setdefault(r.contest, []).append(r.id)
        total_subs = sum(len(v) for v in results_by_contest.values())

    url_map = build_url_map(results_by_contest)
    client = app.test_client()

    pages = [('/', 'index.html'),
             ('/login', 'login.html'), ('/register', 'register.html')]
    for c in contests.all_contests():
        pre = '/c/%s' % c.slug
        pids = contests.contest_problem_ids(c)
        pages.append((pre + '/', index_name(c)))
        pages.append((pre + '/problems', problems_name(c)))
        pages.append((pre + '/help', help_name(c)))
        for pid in pids:
            pages.append(('%s/problems/%s' % (pre, pid), problem_name(c, pid)))
        for p in ['all'] + pids:
            pages.append(('%s/standings?problem=%s' % (pre, p), standings_name(c, p)))
            pages.append(('%s/frag/standings?problem=%s' % (pre, p), frag_name(c, p)))
        for rid in results_by_contest.get(c.slug, []):
            pages.append(('%s/result/%d' % (pre, rid), result_name(c, rid)))

    written = 0
    for path, fname in pages:
        if not path.startswith('/'):
            continue
        html, resp = pull(client, path, url_map)
        if resp.status_code != 200:
            print('  [warn] %-46s -> HTTP %s（跳过）' % (path, resp.status_code))
            continue
        # 给每个页面顶部插一条"静态演示版"横幅（说明页自己已经带了）
        if fname != 'demo-notice.html' and '<body>' in html:
            html = html.replace('<body>', '<body>' + DEMO_BANNER, 1)
        with open(os.path.join(OUT_DIR, fname), 'w', encoding='utf-8') as f:
            f.write(html)
        written += 1

    # 说明页 + /api/problems 静态 JSON（前端下拉框可能用到），每场次一份
    with open(os.path.join(OUT_DIR, 'demo-notice.html'), 'w', encoding='utf-8') as f:
        f.write(DEMO_NOTICE)
    with app.test_client() as c:
        for con in contests.all_contests():
            r = c.get('/c/%s/api/problems' % con.slug)
            fname = 'api-problems.json' if con.default else 'api-problems-%s.json' % con.slug
            with open(os.path.join(OUT_DIR, fname), 'w', encoding='utf-8') as f:
                f.write(r.get_data(as_text=True))

    # 静态资源整目录拷贝
    shutil.copytree(os.path.join(BASE_DIR, 'static'), os.path.join(OUT_DIR, 'static'))
    # 关掉 Jekyll（避免 Pages 忽略下划线开头的文件）
    open(os.path.join(OUT_DIR, '.nojekyll'), 'w').close()

    print('导出完成：%d 个页面 + static/ + .nojekyll  ->  %s' % (written, OUT_DIR))
    print('  榜单数据：%d 条演示提交（来自 data/demo_submissions.csv）' % total_subs)


if __name__ == '__main__':
    main()
