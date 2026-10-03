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
from datetime import datetime, timedelta, timezone

_BEIJING = timezone(timedelta(hours=8))


def beijing(y, mo, d, h=0, mi=0):
    """**北京时间** → 存入用的朴素 UTC。配置赛程时用它，免得算错时区：

        start_at=beijing(2026, 11, 1, 9, 0)      # 北京时间 11-01 09:00

    展示时 `standings.fmt_local` 会再转回 UTC+8。
    """
    return (datetime(y, mo, d, h, mi, tzinfo=_BEIJING)
            .astimezone(timezone.utc).replace(tzinfo=None))

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
class Stage:
    """场次内部的一个**阶段**（如 Stage 1 / Stage 2），仅用于**赛程展示**。

    阶段不参与任何闸门（不做「当前阶段」推断）；只把各阶段的时间列出来。
    """
    label: str
    start_at: 'datetime | None' = None
    end_at: 'datetime | None' = None


@dataclass(frozen=True)
class Contest:
    """一场竞赛。

    - `slug`：URL 段（`/c/<slug>/...`），全局唯一、简短、稳定（发布后别改，会断链）
    - `title` / `short_title`：全称（页脚/标题）与短名（导航/品牌条）
    - 没有「阶段副标题」——当前处于哪个阶段由**日期**推出，并拼进**状态**里显示
      （如「进行中 · Stage 1」），见 `status_display`
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
    status: str = RUNNING
    # 起止时间（朴素 UTC，展示时转 UTC+8）。start_at/end_at 是**比赛**起止；
    # registration_start/end 是**报名**起止（只有需报名的场次才用得上）。
    start_at: 'datetime | None' = None
    end_at: 'datetime | None' = None
    registration_start: 'datetime | None' = None
    registration_end: 'datetime | None' = None
    # 阶段（仅展示）：如 Stage 1 / Stage 2 各自的起止。
    stages: tuple = ()
    # 报名**邀请码**：需报名的场次必须配（报名时要填对）。
    registration_code: 'str | None' = None
    problem_ids: tuple = ()
    default: bool = False
    # 是否需要**个人报名**：True → 未报名不能建队/入队（也就不能提交）。
    # False → 无需报名，建队/入队即参赛（与引入报名机制之前一致）。
    requires_registration: bool = False
    eval_overrides: dict = field(default_factory=dict)
    baseline_file: 'str | None' = None
    seeds: 'tuple | None' = None

    @property
    def is_running(self):
        return self.status == RUNNING

    @property
    def is_enterable(self):
        """能否**进入**场次页面。

        未开始 → 进不去（连门都不给，题面/榜单都不提前放）；
        进行中、已结束 → 可进（已结束要能回看归档）。
        这是比 `is_open` 更外一层的闸：先进得去，才谈得上参不参加。
        """
        return self.status != UPCOMING

    @property
    def requires_enrollment_to_view(self):
        """看内容是否**必须先报名**：需报名 **且未结束**。

        已结束的场次对**所有人开放**（归档公开）——比赛结束后报名已无意义，
        题面与榜单应可自由回看。
        """
        return self.requires_registration and self.status != ENDED

    @property
    def registration_open(self):
        """报名窗口。

        - **配了报名起止日期** → 按日期：早于开始不能报，晚于截止不能报；
        - **没配日期** → 按状态兜底：未开始 + 进行中都能报，已结束截止。

        未开始的场次虽然进不去（`is_enterable` 为 False），但可以报名——
        报名入口在**赛事目录页**（`/`），不在场次内页。
        """
        if self.registration_start is None and self.registration_end is None:
            return self.status in (UPCOMING, RUNNING)
        now = datetime.utcnow()
        if self.registration_start and now < self.registration_start:
            return False
        if self.registration_end and now > self.registration_end:
            return False
        return True

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

    @property
    def current_stage(self):
        """当前所处的阶段（按 `stages` 的日期判断）；不在任何阶段内则 None。"""
        if not self.stages:
            return None
        now = datetime.utcnow()
        for st in self.stages:
            if st.start_at and st.end_at and st.start_at <= now <= st.end_at:
                return st
        return None

    @property
    def status_display(self):
        """展示用状态：进行中时带上当前阶段，如「进行中 · Stage 1」。

        当前阶段的**唯一**来源——页面上不再有独立的「阶段」标签。
        """
        st = self.current_stage
        return f'{self.status_label} · {st.label}' if st else self.status_label


# ---------------------------------------------------------------------------
# 注册表（加一场 = 加一条）
# ---------------------------------------------------------------------------

_CONTESTS = [
    Contest(
        slug=DEFAULT_SLUG,
        title='内测比赛1',
        short_title='内测比赛1',
        # Stage 1 与 Stage 2 属于**同一场竞赛**；这里只是当前展示的阶段副标题。
        status=RUNNING,
        default=True,
        # 赛程（北京时间）。整体窗口覆盖两阶段；阶段分列见 stages。
        start_at=beijing(2026, 10, 1, 8, 0),
        end_at=beijing(2026, 11, 30, 8, 0),
        stages=(
            Stage('Stage 1', beijing(2026, 10, 1, 8, 0), beijing(2026, 10, 31, 8, 0)),
            Stage('Stage 2', beijing(2026, 10, 31, 8, 0), beijing(2026, 11, 30, 8, 0)),
        ),
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
        title='内测比赛2',
        short_title='内测比赛2',
        status=RUNNING,
        requires_registration=True,   # 演示「需报名」：未报名不能看内容/组队
        registration_code='demo',     # 报名邀请码
        # 赛程与主赛事相同：10.01–10.31（S1）、10.31–11.30（S2）
        start_at=beijing(2026, 10, 1, 8, 0),
        end_at=beijing(2026, 11, 30, 8, 0),
        stages=(
            Stage('Stage 1', beijing(2026, 10, 1, 8, 0), beijing(2026, 10, 31, 8, 0)),
            Stage('Stage 2', beijing(2026, 10, 31, 8, 0), beijing(2026, 11, 30, 8, 0)),
        ),
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
