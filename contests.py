# -*- coding: utf-8 -*-
"""赛事的**场次注册表**（多场竞赛支持的核心）。

## 为什么要这一层

原先平台从数据模型到路由到模板都硬编码「只有一场比赛」：赛题是模块级常量，
提交/队伍/榜单都没有场次维度。现在把「场次（contest）」抽成第一等的隔离单位：

    赛题 + 提交 + 榜单 + 队伍  都按场次隔离；用户账号（User）保持全局。

## 场次怎么定义

**用代码注册**（本模块的 `_CONTESTS` 列表），不做后台管理界面。加一场 = 加一个
`Contest(...)` 并重启。

## 场次与「题册」的关系

全局题册仍是 `problems.PROBLEMS`（展示元数据）与 `riscv_problems.EVAL_SPECS`
（评测规格），它们**不动**。一个场次只负责：

1. **挑选**本场试卷：`problem_ids`（有序；空 = 全部）；
2. 可选地**局部覆盖**某道题的评测规格：`eval_overrides` / `baseline_file` / `seeds`。

第 2 条正是「同一道题、不同数据」的落地方式——例如两届比赛共用 add/matmul/reducesum
三道题，但各自用不同的 baseline 与参考解。**无需复制整份 spec**，只覆盖变化的字段即可。

## 生命周期

每场有 `status`（`upcoming` / `running` / `ended`）与可选起止时间 `start_at` / `end_at`
（朴素 UTC，仅用于展示与倒计时）。**只有 `running` 的场次接受提交**，其余只读展示。

## 与旧代码的兼容

`get_eval_spec(problem_id, contest=None)` 的 `contest=None` 会落到**默认场次**，
与旧的单场行为逐字节等价——这样评测链路（evaluator / standings）的旧调用点可以不改。
"""
from dataclasses import dataclass, field
from datetime import datetime

import riscv_problems as RP
from problems import PROBLEMS

# 默认场次：旧 URL（/standings 等）重定向的落点。恰有一场 `default=True`。
DEFAULT_SLUG = 'riscv-ai'

# 场次状态（只有 RUNNING 接受提交）
UPCOMING = 'upcoming'
RUNNING = 'running'
ENDED = 'ended'

STATUS_LABEL = {
    UPCOMING: '未开始',
    RUNNING: '进行中',
    ENDED: '已结束',
}


@dataclass(frozen=True)
class Contest:
    """一场竞赛。

    - `slug`：URL 段（`/c/<slug>/...`），全局唯一、简短、稳定（发布后别改，会断链）
    - `title` / `short_title`：全称（页脚/标题）与短名（导航/品牌条）
    - `stage_label`：取代模板里硬编码的「Stage 1 · 线上赛」，给这一场起个副标题
    - `status`：见模块 docstring；决定能否提交
    - `start_at` / `end_at`：朴素 UTC，仅展示用（可为 None）
    - `problem_ids`：本场试卷（有序）；空元组 = 用整个题册
    - `default`：默认场次（旧 URL 的落点），全局恰一个
    - `eval_overrides`：{problem_id: {字段: 值}}，局部覆盖该题的评测规格
    - `baseline_file`：本场默认 baseline 路径（相对 BASE_DIR）；None 则用题自带
    - `seeds`：本场官方评测种子（覆盖 config.EVAL_SEEDS）；None 则用全局配置
    """
    slug: str
    title: str
    short_title: str
    stage_label: str
    status: str = RUNNING
    start_at: 'datetime | None' = None
    end_at: 'datetime | None' = None
    problem_ids: tuple = ()
    default: bool = False
    eval_overrides: dict = field(default_factory=dict)
    baseline_file: 'str | None' = None
    seeds: 'tuple | None' = None

    @property
    def is_running(self):
        return self.status == RUNNING

    @property
    def is_open(self):
        """能否**参加**（组队/入队 + 提交）——只有进行中的场次开放。

        未开始不能报名，已结束只读。这是一条口径：参加 = 组队 + 提交，
        两者都用这一个开关，避免出现「能组队却不能交」或反之的错位。
        """
        return self.status == RUNNING

    @property
    def accepts_submissions(self):
        """能否提交——与 `is_open` 同源（只有进行中的场次）。"""
        return self.is_open

    @property
    def status_label(self):
        return STATUS_LABEL.get(self.status, self.status)


# ---------------------------------------------------------------------------
# 注册表（加一场 = 加一条）
# ---------------------------------------------------------------------------

_CONTESTS = [
    Contest(
        slug=DEFAULT_SLUG,
        title='RISC-V AI 编译器挑战赛',
        short_title='RISC-V AI',
        # Stage 1 与 Stage 2 属于**同一场竞赛**；这里只是当前展示的阶段副标题。
        stage_label='Stage 1 · 线上赛',
        status=RUNNING,
        default=True,
        problem_ids=('add', 'matmul', 'reducesum'),
        # 不覆盖任何东西：沿用 riscv_problems.EVAL_SPECS 与 data/baseline.json，
        # 行为与引入多场次之前**逐字节等价**。
    ),
    # ---- 占位场次：演示「多场次 + 同题复用不同数据」这套机制 ----
    # 复用前三道题，但 baseline 换到本场自己的文件（data/contests/demo/baseline.json，
    # 需用 `tools/gen_baseline.py --contest demo` 生成）、并演示局部覆盖。
    # 状态为「未开始」——页面可看，但不能提交（生命周期闸门）。
    Contest(
        slug='demo',
        title='演示场次（多场次机制示例）',
        short_title='演示赛',
        stage_label='演示场 · 筹备中',
        status=UPCOMING,
        problem_ids=('add', 'matmul', 'reducesum'),
        baseline_file='data/contests/demo/baseline.json',
        # 局部覆盖：本场把归约求和每点分值调成 5（仅为演示覆盖语义，非真实数据）
        eval_overrides={'reducesum': {'points_per_case': 5}},
    ),
]

_BY_SLUG = {c.slug: c for c in _CONTESTS}


def get_contest(slug):
    """按 slug 取场次；不存在返回 None。"""
    return _BY_SLUG.get(slug)


def default_contest():
    """默认场次（旧 URL 的落点）。注册表必须恰有一个 default=True。"""
    for c in _CONTESTS:
        if c.default:
            return c
    return _CONTESTS[0]


def all_contests():
    """全部场次（按注册顺序）。"""
    return list(_CONTESTS)


def contest_slugs():
    return [c.slug for c in _CONTESTS]


def contest_problem_ids(contest):
    """本场的试卷（有序题 id）；未指定则用整个题册。"""
    if contest is None:
        contest = default_contest()
    return list(contest.problem_ids) if contest.problem_ids else [p['id'] for p in PROBLEMS]


def contest_problems(contest):
    """本场的试卷**展示元数据**（有序 dict 列表），供模板渲染。"""
    by_id = {p['id']: p for p in PROBLEMS}
    return [by_id[pid] for pid in contest_problem_ids(contest) if pid in by_id]


def get_problem(contest, problem_id):
    """取本场试卷里某道题的展示元数据；不属本场（或不存在）返回 None。"""
    for p in contest_problems(contest):
        if p['id'] == problem_id:
            return p
    return None


def submittable_problems(contest):
    """本场开放提交评分的题（spec 存在且题目标了 submittable）。"""
    return [p for p in contest_problems(contest)
            if p.get('submittable') and get_eval_spec(p['id'], contest)]


# ---------------------------------------------------------------------------
# 场次感知的评测规格
# ---------------------------------------------------------------------------

# (slug, problem_id) -> 合并后的 spec。
#
# **必须按场次分开缓存**：evaluator 会往 spec 上挂 `_baselines`（读一次 baseline 缓存
# 住），若两场共用同一个 dict，一个场次的 baseline 会串到另一个场次去。
_SPEC_CACHE = {}


def get_eval_spec(problem_id, contest=None):
    """取某场次里某道题的**评测规格**；题目不在本场或未接评测则返回 None。

    `contest=None` → 默认场次，行为等价于旧的 `riscv_problems.get_eval_spec`。
    """
    if isinstance(contest, Contest):
        c = contest
    else:
        c = get_contest(contest) if contest else default_contest()
    if c is None:
        c = default_contest()

    # 不在本场试卷里的题一律取不到规格（防跨场次评测）
    if problem_id not in contest_problem_ids(c):
        return None

    key = (c.slug, problem_id)
    cached = _SPEC_CACHE.get(key)
    if cached is not None:
        return cached

    base = RP.EVAL_SPECS.get(problem_id)
    if base is None:
        return None

    spec = dict(base)                                    # 浅拷贝：绝不改动全局题册
    if c.baseline_file:
        spec['baseline_file'] = c.baseline_file
    overrides = c.eval_overrides.get(problem_id, {})
    spec.update(overrides)

    spec['case_count'] = len(spec['data_point_sizes'])   # 派生字段随覆盖重算
    if 'full_score' not in overrides:
        spec['full_score'] = spec['points_per_case'] * spec['case_count']
    if c.seeds is not None:
        spec['seeds'] = list(c.seeds)
    spec.pop('_baselines', None)                          # 别把上一场的 baseline 缓存带进来

    _SPEC_CACHE[key] = spec
    return spec


def specs_for(contest):
    """本场次的 {problem_id: spec}，供模板/工具批量取用。"""
    return {pid: get_eval_spec(pid, contest) for pid in contest_problem_ids(contest)}


def is_riscv_problem(problem_id, contest=None):
    return get_eval_spec(problem_id, contest) is not None


def total_full_score(contest=None):
    """本场满分合计。"""
    return sum((s or {}).get('full_score', 0)
               for s in specs_for(contest if contest is not None else default_contest()).values())
