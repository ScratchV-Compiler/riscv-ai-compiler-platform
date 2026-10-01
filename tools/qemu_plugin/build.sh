#!/bin/sh
# 构建 QEMU 缓存插件（tools/qemu_plugin/qemu_cache_plugin.c -> cache.so）
#
# 为什么不把 qemu-plugin.h 放进仓库：该头文件是 **GPL-2.0-or-later**，
# vendor 进来会给本仓库引入 copyleft 依赖。改为按需拉取并缓存。
#
# 版本必须与系统 qemu 匹配——插件加载时 QEMU 会校验 API 版本，
# 不匹配会直接拒绝加载。用 `qemu-riscv32 --version` 确认版本后改这里的 QEMU_TAG。
set -e

QEMU_TAG="${QEMU_TAG:-v6.2.0}"          # 对应 qemu-riscv32 6.2.0
HERE=$(cd "$(dirname "$0")" && pwd)
HDR="$HERE/qemu-plugin.h"
OUT="$HERE/cache.so"

if [ ! -f "$HDR" ]; then
    echo "[build] 拉取 qemu-plugin.h ($QEMU_TAG) ..."
    # GitHub raw 在某些网络下不可达，jsdelivr 是可靠镜像
    curl -sL --noproxy '*' \
        "https://cdn.jsdelivr.net/gh/qemu/qemu@${QEMU_TAG}/include/qemu/qemu-plugin.h" \
        -o "$HDR"
fi

if ! grep -q "qemu_plugin_register_vcpu_mem_cb" "$HDR" 2>/dev/null; then
    echo "[build] 头文件获取失败或不完整: $HDR" >&2
    exit 1
fi

echo "[build] 编译 cache.so ..."
gcc -O2 -fPIC -shared -I"$HERE" -o "$OUT" "$HERE/qemu_cache_plugin.c"
echo "[build] 完成 -> $OUT"

# 自检：加载插件跑一个空程序，能打印统计行才算成功
if command -v qemu-riscv32 >/dev/null 2>&1; then
    TMP=$(mktemp -d)
    printf '.option norvc\n.text\n.globl _start\n_start:\n li a0,0\n li a7,93\n ecall\n' > "$TMP/t.s"
    if clang --target=riscv32-linux-gnu -march=rv32im -mabi=ilp32 -nostdlib -static \
             -fuse-ld=lld -Wl,--no-relax "$TMP/t.s" -o "$TMP/t.elf" 2>/dev/null; then
        if qemu-riscv32 -d plugin -plugin "$OUT" "$TMP/t.elf" 2>&1 | grep -q QEMU_CACHE; then
            echo "[build] 自检通过"
        else
            echo "[build] 警告：插件加载后没有输出，可能与 qemu 版本不匹配" >&2
        fi
    fi
    rm -rf "$TMP"
fi
