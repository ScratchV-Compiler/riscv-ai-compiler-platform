# -*- coding: utf-8 -*-
"""赛题元数据。

赛题集由 `platform.yaml` 的 `active_problem_set` 切换：
  * demo   —— 内置的 LeetCode 热题三题（公开演示站的安全桩，提交 .py，评测走保险的 stub）
  * contest—— 真实赛道（补丁改造 ScratchV 编译器），赛题来自 `contest_problems`

对外统一暴露 `PROBLEMS` / `get_problem()` / `problem_ids()`，页面与榜单数据驱动。
"""

import config

# ---------------------------------------------------------------------------
# demo 赛题集（LeetCode 热题 HOT 100 中热度最高的三道中等题）
# ---------------------------------------------------------------------------
DEMO_PROBLEMS = [
    {
        "id": "add-two-numbers",
        "no": 2,
        "code": "LC 2",
        "title": "两数相加",
        "summary": "两个逆序存储的非负整数链表相加，按同样形式返回结果链表。",
        "task": (
            "给你两个非空的链表，表示两个非负的整数。它们每位数字都是按照逆序的方式存储的，"
            "并且每个节点只能存储一位数字。请你将两个数相加，并以相同形式返回一个表示和的链表。"
            "你可以假设除了数字 0 之外，这两个数都不会以 0 开头。"
        ),
        "input": "两个单链表的头节点，节点值为 0–9 的一位数字，按个位在前的逆序存储整数。",
        "output": "返回相加结果链表的头节点。逐节点与参考实现比对，链表结构与每一位数字须完全一致。",
        "scale": "每条链表长度 1–100；每位数字 0–9；结果最多比原链表多一位（最高位进位）。",
        "baseline": "参考 O(max(m, n))：一次遍历、逐位相加并维护进位。",
        "hint": "较短的链表缺失位按 0 处理；遍历结束后若仍有进位，需额外新建一个值为 1 的节点。",
        "formula": "示例：(2 → 4 → 3) 表示 342，(5 → 6 → 4) 表示 465，两者相加得 807，即 (7 → 0 → 8)。",
        "kind": "demo",
    },
    {
        "id": "longest-substring",
        "no": 3,
        "code": "LC 3",
        "title": "无重复字符的最长子串",
        "summary": "在字符串中找出不含重复字符的最长连续子串，返回其长度。",
        "task": "给定一个字符串 s，请你找出其中不含有重复字符的最长子串的长度。",
        "input": "字符串 s，由英文字母、数字、符号和空格组成。",
        "output": "返回最长无重复子串的长度（整数）。与参考实现比对，结果须完全一致。",
        "scale": "0 ≤ s.length ≤ 5 × 10⁴；字符集为 ASCII。",
        "baseline": "参考 O(n) 滑动窗口：用哈希集合或定长数组记录每个字符最近出现的位置。",
        "hint": "用左右指针维护窗口；右指针遇到已出现的字符时，把左指针跳到该字符上一次出现位置的下一位。",
        "formula": '示例：s = "abcabcbb"，答案是 3（"abc"）；s = "bbbbb"，答案是 1（"b"）。',
        "kind": "demo",
    },
    {
        "id": "longest-palindrome",
        "no": 5,
        "code": "LC 5",
        "title": "最长回文子串",
        "summary": "在给定字符串中找出最长的回文子串（正读反读都相同的子串）。",
        "task": "给你一个字符串 s，找到 s 中最长的回文子串。回文串是指正读和反读都相同的字符串。",
        "input": "字符串 s，长度 1–1000，由数字和英文字母组成。",
        "output": "返回最长的回文子串。与参考实现比对须一致；存在多个等长答案时，返回其中任意一个即可。",
        "scale": "1 ≤ s.length ≤ 1000。",
        "baseline": "参考 O(n²) 中心扩展法；进阶可用 O(n) 的 Manacher 算法。",
        "hint": "回文中心可能是单个字符（奇数长度），也可能是两个相邻字符之间（偶数长度），两种中心都要向两侧扩展。",
        "formula": '示例：s = "babad"，答案是 "bab" 或 "aba"；s = "cbbd"，答案是 "bb"。',
        "kind": "demo",
    },
]


def _normalize_contest_problem(raw):
    """把 platform.yaml 里的 contest 赛题补齐展示字段并标记 kind。"""
    p = dict(raw)
    p.setdefault("no", 0)
    p.setdefault("code", (p.get("id") or "")[:4].upper())
    p.setdefault("summary", "")
    p.setdefault("task", p.get("summary", ""))
    p.setdefault("input", "固定 ONNX 模型，确定性输入。")
    p.setdefault("output", "与 NumPy 参考逐元素比对，Q16.16 绝对误差 ≤1 LSB 视为正确。")
    p.setdefault("scale", "单次评测预算受 judge.max_instr 限制。")
    p.setdefault("baseline", "冻结基线版本的实测性能。")
    p.setdefault("hint", "见 platform.yaml 的赛题说明。")
    p.setdefault("formula", "")
    p["kind"] = "patch"
    return p


def _active_problems():
    if config.get("active_problem_set") == "contest":
        return [_normalize_contest_problem(p) for p in (config.get("contest_problems") or [])]
    return list(DEMO_PROBLEMS)


PROBLEMS = _active_problems()
_BY_ID = {p["id"]: p for p in PROBLEMS}


def get_problem(problem_id):
    """按 id 取赛题元数据；不存在返回 None。"""
    return _BY_ID.get(problem_id)


def problem_ids():
    return [p["id"] for p in PROBLEMS]


def is_contest():
    """当前是否为真实（补丁）赛道。"""
    return config.get("active_problem_set") == "contest"


def submit_kind():
    """当前赛道的提交类型：'patch'（补丁）或 'demo'（演示桩）。"""
    return "patch" if is_contest() else "demo"
