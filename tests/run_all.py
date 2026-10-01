#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑全部测试并汇总。

    .venv/bin/python tests/run_all.py
    .venv/bin/python tests/run_all.py test_eval        # 只跑名字含该串的

每个测试在**独立子进程**里跑：`app` 是模块级单例，同进程里反复初始化会互相污染，
分进程最干净。用**临时库**，不碰 platform.db。
"""

import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY = re.compile(r'==== (\d+) passed, (\d+) failed')


def discover(needle=None):
    names = sorted(f for f in os.listdir(HERE)
                   if f.startswith('test_') and f.endswith('.py'))
    if needle:
        names = [n for n in names if needle in n]
    return names


def main():
    needle = sys.argv[1] if len(sys.argv) > 1 else None
    names = discover(needle)
    if not names:
        print(f'没有匹配的测试{"：" + needle if needle else ""}')
        return 1

    print(f'共 {len(names)} 个测试模块（临时库，不碰 platform.db）\n')
    total_p = total_f = 0
    failed_mods = []
    rows = []
    for name in names:
        t0 = time.time()
        proc = subprocess.run([sys.executable, os.path.join(HERE, name)],
                              capture_output=True, text=True)
        dt = time.time() - t0
        m = SUMMARY.search(proc.stdout or '')
        if m:
            p, f = int(m.group(1)), int(m.group(2))
        else:
            p, f = 0, 1                     # 崩了（语法错/异常）算失败
        total_p += p
        total_f += f
        if f:
            failed_mods.append(name)
        rows.append((name, p, f, dt))

    width = max(len(n) for n, *_ in rows)
    print(f'{"模块":<{width}}  {"通过":>5} {"失败":>5}   {"耗时":>7}')
    print('-' * (width + 24))
    for name, p, f, dt in rows:
        flag = '' if f == 0 else '  ← 失败'
        print(f'{name:<{width}}  {p:>5} {f:>5}   {dt:>6.1f}s{flag}')
    print('-' * (width + 24))
    print(f'{"合计":<{width}}  {total_p:>5} {total_f:>5}')

    if failed_mods:
        print(f'\n失败的模块（单独跑看详细输出）:')
        for n in failed_mods:
            print(f'  .venv/bin/python tests/{n}')
        # 把失败模块的尾巴贴出来，省一次来回
        for n in failed_mods:
            proc = subprocess.run([sys.executable, os.path.join(HERE, n)],
                                  capture_output=True, text=True)
            tail = [l for l in (proc.stdout or '').splitlines() if l.startswith(('[FAIL]', '失败项'))]
            for l in tail[:6]:
                print(f'    {n}: {l}')
    return 1 if total_f else 0


if __name__ == '__main__':
    sys.exit(main())
