# P3 · RISC-V 汇编提交与 qemu 评测

> 文档版本：v1.0（2026-10-01）
> 涉及模块：`evaluator.py`、`riscv_runner.py`、`riscv_oracle.py`、`riscv_problems.py`、`tasks.py`、`app.py`、`third_party/ScratchV`（submodule）
> 相关：`docs/03`（实现记录）、`docs/05` D9 / D11

---

## 一、这是什么

选手提交 **RISC-V 汇编（RV32IM / ilp32）**，平台把它与固定 wrapper 汇编链接后交给
**qemu-riscv32** 真实执行，读出内存 dump，与平台独立算出的参考值比对；
正确性全过之后，用**动态指令数**相对基准计分。

目前只开放一道题 `matmul-4x4`（4x4 Q16.16 定点矩阵乘）。

**提交方式有两种，二选一**：上传 `.s` 文件，或直接在提交页**粘贴**汇编代码。
两者同时给出时以**上传的文件**为准（粘贴内容没有文件名，故只对文件做后缀校验）。

验证工具链来自 ScratchV（`third_party/ScratchV`，钉在 upstream main `20b105e8`）。

---

## 二、裸机 ABI（选手要遵守的契约）

沿用 ScratchV 的约定（`third_party/ScratchV/tests/test_standalone_execution.py`）：

| 项 | 约定 |
|---|---|
| 入口符号 | 必须定义**全局符号 `cnn_entry`** |
| 入参 | `a0` = 输入张量首址，`a1` = 输出张量首址 |
| 返回 | 普通 `ret` 即可；wrapper 负责 dump |
| 数值格式 | int32 **Q16.16** 定点 |
| 输入范围 | `[-32768, 32767]`，即 Q16.16 的 [-0.5, 0.5) |
| 栈 | `sp` 已指向工作区顶端，可向下正常使用 |

**内存布局**（`riscv_problems.layout()`，一次连续 dump）：

```
guard_lo(256) | workspace(1024) | guard_mid(256) | output(64) | guard_hi(256)
```

任一 guard 区非零 ⇒ 越界写 ⇒ 判 `invalid`。

> **相对 ScratchV 原 wrapper 的一处有意改进**：ScratchV 用 `la sp, workspace`
> （指向工作区**底部**），栈向下会写进 guard_lo，等于隐式禁止选手用栈；
> 本平台把 `sp` 钉在工作区**顶端**，选手可正常用栈，而栈溢出仍被 guard_lo 捕获。

**编译命令**（锁死，见第四节）：

```
clang --target=riscv32-linux-gnu -march=rv32im -mabi=ilp32 \
      -nostdlib -static -fuse-ld=lld -Wl,--no-relax wrapper.s player.s -o execute.elf
```

---

## 三、判据与计分

### 3.1 正确性（一票否决）

期望输出由 `riscv_oracle.py` 的**纯 Python 参考实现**算出，**独立于选手进程**。
选手进程只能影响自己 `write(1)` 出来的字节，影响不了期望值。

`C[i][j] = Σₖ s32( s32(A[i][k] × B[k][j]) >> 16 )`，逐步取模 2^32，
与真实指令序列（`mul` + `srai` + `add`）逐步对齐，而不是先算大整数再截断。

### 3.2 性能

```
score = min_over_cases( min(1, baseline_instructions / player_instructions) ) × 100
```

取**最差用例**的比值（比取平均更保守，防单用例爆表刷分）。

### 3.3 baseline 从哪来

`tools/gen_baseline.py` 把 `reference/matmul.c` 编成 RV32IM，走**与选手完全相同**的
wrapper + 编译 + 单步计数流水线，产出 `data/baseline.json`。
当前 baseline = **360 条指令**（各 seed 一致）。

> 换了 clang 版本、或改了 `-march` / `-Wl,--no-relax`，都必须重跑本脚本，
> 否则历史成绩与新成绩不可比。

---

## 四、为什么这样数指令

三条路都被堵死，最后用的是第四条：

| 方案 | 状态 |
|---|---|
| `llvm-mca-18` | ❌ 无 RISC-V 调度模型（实测报错 `unable to find instruction-level scheduling information for target triple 'riscv32'`） |
| qemu `-plugin`（libinsn） | ❌ 本机只有 `qemu-user` 包，无 `/usr/lib/qemu/`，无插件库 |
| 静态数汇编行数 | ❌ 不含循环，会被"少写指令但更慢"钻空子 |
| **`qemu-riscv32 -singlestep -d exec -D trace.log`** | ✅ 数 `^Trace` 行数 |

实测该计数**精确**：一个 `2 + 100×2 + 3` 的循环程序恰好 205 行。同一 ELF 连跑三次完全一致。

成本是单步很慢，所以**只在正确性通过后**才做计数（失败短路，省一半以上时间）。

---

## 五、安全模型（分层，且明确边界）

选手提交的是**任意 RISC-V 汇编**，能执行任意 syscall。**qemu-user 不是沙箱**——
guest 的 `ecall` 会被 1:1 翻译成宿主 syscall，以 qemu 进程的身份执行。

### 5.1 已实施

| 层 | 手段 | 挡住的 |
|---|---|---|
| **降权** | `setpriv --reuid=65534 --regid=65534 --clear-groups`（编译与运行都套） | 以 root 写系统文件、读 `/root` 下的一切 |
| **网络** | `unshare -n` 私有网络命名空间 | guest 的 `socket`/`connect`（实测 `ENETUNREACH`） |
| **私有挂载** | `unshare -m` + 把 `/tmp`、`/var/tmp`、`/dev/shm` 换成空 tmpfs | guest 往宿主世界可写目录留文件（实测写入随命名空间消失） |
| **资源** | `prlimit`：`RLIMIT_CPU` / `RLIMIT_FSIZE` / `RLIMIT_NPROC` / `RLIMIT_AS` | 死循环、写大文件打爆磁盘、fork 炸弹 |
| **源码预检** | 拒绝 `.incbin` / `.include` | 汇编阶段读宿主文件（`.incbin "/etc/passwd"`） |
| **不回显** | `details` 只给十进制数值差，绝不回显原始 dump | 组合攻击：读到文件后用失败信息把内容带出来 |
| **随机输入** | 每次评测现生成 seed 与输入张量（**D1**） | 不解题、直接把答案写死 |

### 5.2 明确防不住（不要过度承诺）

- **qemu-user 自身的宿主漏洞**：guest 是"翻译执行"，qemu 若被攻破可能拿到 qemu 的
  uid。本机无容器/VM/gVisor，挡不住，只能靠降权把损失压到 nobody。
- **nobody 本来就可读的文件**（如 `/etc/passwd`）：降权挡不住"读"，只能保证
  "读出来的东西不会从评测结果里漏出去"。
- **资源型 DoS**：单次评测有预算，但很多人同时刷仍会排队。靠 `DAILY_QUOTA`(99)、
  队列深度上限(50)、`EVAL_TOTAL_BUDGET`(180s) 缓解，非根治。
- **内存占用**：`RLIMIT_AS` 基本只是兜底——见下面这个坑。

### 5.3 实测踩到的坑（都已写进代码注释）

1. **`RLIMIT_AS` 必须 > 4GB**。qemu-user 启动时要为 32 位 guest 预留约 4GB **虚拟**
   地址空间，设 512MB（最初的设计值）会直接报
   `Unable to reserve 0xfffff000 bytes of virtual address space`。实测 4G 不行、6G/8G 可以。
   → 这也意味着 AS 限额防内存 DoS 基本无用，真正起作用的是 CPU 限额 + wall timeout。
2. **`/root` 是 0700**，沙箱用户根本进不去 → 选手源码必须先**搬进**工作目录。
3. **工作目录不能设在 `/tmp`**，否则被自身的挂载遮蔽挡掉，qemu 读不到自己的 ELF。
   → 统一放 `/var/lib/riscv-eval`。
4. **`qemu-riscv32 -r` 不是 syscall 白名单**，它是 `QEMU_UNAME`（设 uname 字符串）。
   曾误以为是沙箱开关。
5. **`preexec_fn` 在多线程进程里有死锁风险**（worker 是线程），故 rlimit 一律用
   `prlimit` 施加，而不是 Python 的 `preexec_fn`。
6. **编译与运行要两套 rlimit**：clang 要 fork `cc1`/`ld.lld`，`RLIMIT_NPROC=1` 会直接编译失败。

---

## 六、状态机与失败归类

`status` 仍只用既有四态（`standings.py` 的 `VALID_STATUSES` 与 `result.html` 依赖它），
富信息放 `details`：

```
pending --(worker 取到)--> running --┬--> success  (details.verdict=accepted)
                                     └--> failed   (details.verdict=其它)
```

| `details.verdict` | 触发 | 给选手的话 |
|---|---|---|
| `accepted` | 全部用例通过 | 通过 N 个用例，得分 X |
| `compile_error` | 汇编/链接失败、缺 `cnn_entry`、文件名/大小/`.incbin` 不合法 | 编译失败：… |
| `invalid` | guard 被破坏，或输出数值不符 | 越界写 / 第 k 个数值不符（期望 a，实际 b） |
| `timeout` | 运行超时、CPU 限额、指令数超上限 | 运行超时（可能存在死循环） |
| `runtime_error` | 段错误(-11)、非法指令(-4)、异常退出码 | 非法内存访问 等 |
| `internal_error` | 工具链缺失、评测器自身异常 | 评测系统内部错误 |
| `unsupported` | 提交了展示题（LeetCode 三道） | 该题暂未开放评测 |

用 **负 returncode** 区分被信号杀死（`-11` 段错误、`-24` SIGXCPU），不只看 `!= 0`。
评测器用 `try/except` + `finally` 保证**一定写回终态**，绝不让提交卡在 `running`；
`tasks.py` 在启动时还会回收陈旧的 `running` 记录兜底。

---

## 七、验证记录

### 7.1 参考解回归（先过这关，否则整条链路禁用）

`reference/matmul.s` 当"选手提交"跑：seed 1/7/12345 三个输入下
`rc=0`、guard 完好、输出与参考完全一致、指令数恒为 360。

### 7.2 评测器全量（13 项，Flask test client + 临时库）

参考解 accepted / 满分 / 指令数=baseline；空文件 / 语法错 / 缺 `cnn_entry` / 越界写 /
输出乱填 / 死循环 / `.incbin` 各自的 verdict 正确；LeetCode 题 `unsupported`；
**硬编码固定答案判失败**，且反证：把输入固定成 seed=1 时同一份硬编码确实会"通过"
—— 证明随机 seed 正是拦截它的原因。

### 7.3 提交流程端到端（16 项）

未登录 `/submit` → 302 登录；未入队提交被拒；正常提交 → 302 结果页；
错误后缀 / 展示题 / 空文件均 400；轮询到 `success`；`verdict=accepted`、score=100；
结果页渲染得分与用例明细且不再出现占位字段 `cycles`；排行榜 200。

### 7.4 隔离验证（从 guest 代码内部发起）

一段汇编试图 `openat("/tmp/pwned_by_guest")` + `socket/connect(1.1.1.1:53)`：

- `connect` 返回 **-101 (ENETUNREACH)** ⇒ 断网生效
- `openat` 在命名空间内返回 3（写进了**临时 tmpfs**），但**宿主 `/tmp` 上不存在该文件**
  ⇒ 挂载遮蔽生效

### 7.5 真机烟测

`systemctl restart riscv-platform.service` 后，真实走一遍
注册 → 建队 → 提交 `reference/matmul.s` → 轮询：

```
status=success | verdict=accepted | score=100.0 | 360/360 instructions | 结果页 200
```

（烟测产生的账号/队伍/提交已清理，`platform.db` 复原为 1 用户 / 46 条演示提交。）

---

## 八、运维要点

- **工具链**：`clang`、`ld.lld`、`qemu-riscv32` 必须在 PATH 上（Debian/Ubuntu 装
  `clang lld qemu-user`）。缺工具时评测返回 `internal_error` 而不是崩。
- **以 root 运行**才能用 `unshare`/`setpriv` 降权。以非 root 跑时把
  `PLATFORM_ENABLE_SANDBOX=0` 关掉（本地开发），此时**没有隔离**，不要对外服务。
- **工作目录根** `/var/lib/riscv-eval`（`PLATFORM_EVAL_WORK_ROOT` 可改），
  不要改到 `/tmp`。
- **改了编译参数或换了 clang** ⇒ 重跑 `tools/gen_baseline.py`。
- submodule 更新：`git submodule update --remote third_party/ScratchV`，
  并同步核对 ABI 是否变化。
