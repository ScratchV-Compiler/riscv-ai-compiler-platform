# QEMU 缓存插件

用一个 QEMU TCG 插件同时完成**动态指令计数**与**L1 缓存模拟**，替代原先的
`qemu-riscv32 -singlestep -d exec` 数 trace 行数的做法。

## 为什么

原先的计数方式要单步执行、每次执行写一行日志：

| 规模（matmul 参考解） | 单步计数 | 插件 | 提速 |
|---|---|---|---|
| N=16 | 0.10s | 0.01s | 15× |
| N=32 | 0.75s | 0.01s | 93× |
| N=64 | 6.25s | 0.02s | **300×** |

而且**计数逐位一致**——30 个数据点（三题 × 10 规模）全部与旧方法相同，
所以 `data/baseline.json` **不需要重算**。

顺带拿到了访存数据（原先完全拿不到）：完整访存日志会把磁盘打爆
（qemu `-d cpu` 是 603 字节/指令，matmul N=64 要 **1.35 GB**），
而插件在**进程内**做缓存模拟，只输出一行汇总，日志体积与程序规模无关。

## 构建

```sh
sh tools/qemu_plugin/build.sh
```

需要 `gcc`。脚本会拉取头部文件（见下）并编译 `cache.so`，最后自检一次。

### 关于 `qemu-plugin.h`

该头文件属于 QEMU，许可证是 **GPL-2.0-or-later**。本仓库**不 vendor** 它
（避免引入 copyleft 依赖），改由构建脚本从 jsdelivr 按 `QEMU_TAG` 拉取并缓存。

**版本必须与系统 qemu 匹配**：QEMU 加载插件时会校验 API 版本，不匹配直接拒绝。
先 `qemu-riscv32 --version` 确认，再改脚本里的 `QEMU_TAG`。

## 用法

```sh
qemu-riscv32 -d plugin \
  -plugin ./cache.so,dsize=32768,dways=4,dblock=64,isize=32768,iways=4,iblock=64 \
  <elf>
```

输出一行（同时走 QEMU 日志与 stderr）：

```
QEMU_CACHE instructions=2404765 d_access=528388 d_miss=773 d_hitrate=99.90
           i_access=2404765 i_miss=4 i_hitrate=100.00
```

## 实现要点（踩过的坑）

1. **`qemu_plugin_outs()` 需要 `-d plugin` 才显示**，否则会误以为插件没工作。
   所以同时也 `fputs(stderr)` 一份。
2. **给同一指令注册 R 和 W 两个回调会双重计数**（实测 256 次 `sw` 被统计成 512）。
   正确做法是只注册一次 `QEMU_PLUGIN_MEM_RW`，用 `qemu_plugin_mem_is_store()` 区分。
3. **I-cache 不要逐指令回调**（每条指令一次函数调用，会毁掉速度优势）。
   改为按 TB 记账：翻译时记录该 TB 的指令地址，执行时一次性记入。
4. 插件 `.so` 必须**对沙箱用户（nobody）可读**。评测时会被复制进工作目录
   （`/var/lib/riscv-eval/...`，权限 0777），因为 `/root` 是 0700、沙箱进不去。

## 缓存模型

集合相联 + LRU 淘汰，参数 `size / ways / block` 可配。默认 L1：32KB / 4 路 / 64B。

**注意**：这是**功能级**模型，不是周期精确模型——它给的是命中/未命中计数，
不含延迟、预取、写回开销。用它做计分前请先读 `docs/08` 里关于
「当前题目规模下访存并非瓶颈」的实测结论。
