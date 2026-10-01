# -*- coding: utf-8 -*-
"""评测后端公共工具：verdict 常量、补丁路径面校验。

后端统一签名：

    evaluate(submission_id, team_name, problem_id, artifact_path, meta) -> (score, details)

`details` 必须含 `verdict`（终态）字段，供 worker 落库。
"""
import fnmatch
import re

from models import VERDICT_LABELS, VERDICT_CSS, TERMINAL_VERDICTS  # noqa: F401  (统一从此处导出)

# 补丁中出现的改动路径：优先取 `diff --git a/.. b/..`，回退 `+++ b/..`
_RE_DIFF = re.compile(r'^diff --git a/(?P<a>.+?) b/(?P<b>.+)$', re.M)
_RE_PLUS = re.compile(r'^\+\+\+ b/(?P<p>.+)$', re.M)


def parse_patch_paths(text):
    """从补丁文本解析涉及的路径（去重、保持顺序）。"""
    paths = []
    seen = set()

    def _add(p):
        p = (p or '').strip().strip('"')
        if p and p != '/dev/null' and p not in seen:
            seen.add(p)
            paths.append(p)

    matches = _RE_DIFF.findall(text)
    if matches:
        for _a, b in matches:
            _add(b)
    else:
        for (p,) in _RE_PLUS.findall(text):
            _add(p)
    return paths


def _match_any(path, patterns):
    for pat in patterns or []:
        if fnmatch.fnmatch(path, pat):
            return pat
    return None


def check_scope(paths, allow, deny):
    """校验改动路径面。

    返回 (ok, violations, detail)：violations 为 [(path, reason), ...]。
    规则：命中 deny 直接违规；未命中任何 allow 也违规；两者都没有才算通过。
    """
    violations = []
    for path in paths:
        hit = _match_any(path, deny)
        if hit:
            violations.append((path, f'禁止改动的路径（命中 {hit}）'))
            continue
        if not _match_any(path, allow):
            violations.append((path, '不在允许改动的路径集合内'))
    return (not violations), violations


def verdict_label(verdict):
    return VERDICT_LABELS.get(verdict, verdict)


def verdict_css(verdict):
    return VERDICT_CSS.get(verdict, 'vbadge-pending')
