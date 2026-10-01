# P3 · RISC-V 汇编提交与 qemu 评测

> 文档版本：v1.0（2026-10-01）
> 涉及模块：`evaluator.py`、`riscv_runner.py`、`riscv_oracle.py`、`riscv_problems.py`、`tasks.py`、`app.py`、`third_party/ScratchV`（submodule）
> 相关：`docs/03`（实现记录）、`docs/05` D9 / D11

---

## 一、这是什么

选手提交 **RISC-V 汇编（RV32IM / ilp32）**，平台把它与固定 wrapper 汇编链接后交给
**qemu-riscv32** 真实执行，读出内存 dump，与平台独立算出的参考值比对；
正确性全过之后，用**动态指令数**相对基准计分。

目前开放三道题（均为 RV32IM 汇编 + qemu 真实执行）：

| 题目 | 算子 | 规模梯度 | 每点分值 | 满分 |
|---|---|---|---|---|
| `add` | 逐元素相加 | N = 64 → 4096（线性） | 3 | 30 |
| `matmul-4x4` | N×N 定点矩阵乘 | N = 4 → 64（立方） | 3 | 30 |
| `reducesum` | 全归约求和 | N = 64 → 4096（线性） | 4 | 40 |

三题合计 **100 分**。

**数据点按规模分级**（对齐官方 `stage2数据点.md` 的取法）：每题 10 个数据点，
每个点是**不同的规模 N**，从小到大覆盖"小规模基本正确性 → 中等规模 → 超出 L1 的
访存瓶颈"。matmul 的工作量是 N³，所以 N 必须缓着涨（4→64），否则最后几个点会把
评测时间吃光；4→64 也刚好跨过 L1（三个 16×16 矩阵约 48KB > 32KB）。

选手**必须写尺寸无关的代码**——这正是"可扩展性"要考的东西。

**提交方式有两种，二选一**：上传 `.s` 文件，或直接在提交页**粘贴**汇编代码。
两者同时给出时以**上传的文件**为准（粘贴内容没有文件名，故只对文件做后缀校验）。

验证工具链来自 ScratchV（`third_party/ScratchV`，钉在 upstream main `20b105e8`）。

---

## 二、裸机 ABI（选手要遵守的契约）

沿用 ScratchV 的约定（`third_party/ScratchV/tests/test_standalone_execution.py`）：

| 项 | 约定 |
|---|---|
| 入口符号 | 必须定义**全局符号 `cnn_entry`** |
| 入参 | `a0` = 输入张量首址，`a1` = 输出张量首址，**`a2` = 规模 N** |
| 规模含义 | matmul 为矩阵阶数；add / reducesum 为向量长度 |
| 返回 | 普通 `ret` 即可；wrapper 负责 dump |
| 数值格式 | int32 **Q16.16** 定点 |
| 输入范围 | `[-32768, 32767]`，即 Q16.16 的 [-0.5, 0.5) |
| 栈 | `sp` 已指向工作区顶端，可向下正常使用 |

**内存布局**（`riscv_problems.layout(spec, N)`，一次连续 dump）：

```
guard_lo(256) | workspace(max(1024, 8N)) | guard_mid(256) | output(依 N) | guard_hi(256)
```

工作区与输出区**都随 N 缩放**，任一 guard 区非零 ⇒ 越界写 ⇒ 该数据点判 `invalid`。

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

### 3.2 逐点独立计分

每题 10 个数据点，**每个数据点独立判定、独立给分**：

```
单点得分 = 分值 × min(1, 该点 baseline 指令数 / 本队该点指令数)   （做对才计）
总分     = 10 个数据点之和
```

**baseline 是逐数据点的**——N 不同，指令数自然不同，不能用一个数。
`data/baseline.json` 形如 `{题目: {"by_size": {N: 指令数}}}`。

因此评测**不短路**：某个数据点做错，仍要继续跑完其余 9 个。
做错只丢该点的分，唯一整题级的失败是**编译不通过**（与输入无关，一次不过必然次次不过）。

> 与早期设计的差别：v1.3 用的是「全部用例通过才得分 + 取最差比值」，那是"一票否决"口径；
> v1.4 改成逐点独立（某点失败不再拖累整题）；v1.5 再把数据点改为**规模分级**，
> baseline 随之变成逐数据点的。

全 10 点失败时按失败记录（`error` 非空 → `status='failed'`，不占榜单位次）；
部分通过则按成功记录并计入榜单。整题失败时，若 10 个点的失败原因一致，
`verdict` 沿用该原因（如 `timeout`），否则统一记 `invalid`。

### 3.3 baseline 从哪来

`tools/gen_baseline.py` 把每题的 `reference/*.c` 编成 RV32IM，走**与选手完全相同**的
wrapper + 编译 + 单步计数流水线，产出 `data/baseline.json`。

逐数据点测量。节选（完整值见 `data/baseline.json`）：

| 题目 | 最小规模 | 最大规模 |
|---|---|---|
| `add` | N=64 → 601 | N=4096 → 36,889 |
| `matmul-4x4` | N=4 → 803 | N=64 → 2,404,765 |
| `reducesum` | N=64 → 344 | N=4096 → 20,506 |

参考解是**尺寸无关**的（N 从 `a2` 取），同一份 `.s` 要跑通全部 10 个规模。

该脚本还会顺带**校验参考解本身能通过**（期望输出与 oracle 一致、guard 完好），
所以它同时是一次 oracle ↔ C 参考实现的交叉验证。

> 换了 clang 版本、或改了 `-march` / `-Wl,--no-relax`，都必须重跑本脚本，
> 否则历史成绩与新成绩不可比。

---

## 四、指令计数：QEMU TCG 插件（v1.8 起）

**当前实现**：`tools/qemu_plugin/qemu_cache_plugin.c` —— 一个 QEMU TCG 插件，
在**插件进程内**完成动态指令计数与 L1 数据/指令缓存模拟，只输出一行汇总。

### 为什么换掉原来的单步计数

原做法是 `qemu-riscv32 -singlestep -d exec -D trace.log` 再数 `^Trace` 行数，
慢且完全不建模访存：

| 规模（matmul 参考解） | 单步计数 | 插件 | 提速 |
|---|---|---|---|
| N=16 | 0.10s | 0.01s | 15× |
| N=32 | 0.75s | 0.01s | 93× |
| N=64（平台最大点） | 6.25s | 0.02s | **300×** |

评测总耗时随之下降：matmul 从 **14.1s → 2.2s**。

**关键**：计数**逐位一致**。30 个数据点（三题 × 10 规模）全部与旧方法相同，
所以 `data/baseline.json` **无需重算**。

### 走过的弯路（记录以免重犯）

| 方案 | 结论 |
|---|---|
| `llvm-mca-18` | ✅ 其实**有** RISC-V 调度模型（`sifive-e76`/`e31`/`u74`/`rocket`），`generic-rv32` 才没有。但它是静态直线分析，不认循环次数、不建模缓存 |
| qemu 插件 | ❌ **曾误判为不可用**——依据是"没找到 `/usr/lib/qemu/`"。实际 `-plugin` **已编译进 qemu**，只是插件 `.so` 没随包发布，自己编即可 |
| 静态数汇编行数 | ❌ 不含循环，会被"少写指令但更慢"钻空子 |

---

## 四之二、评测指标：cost = 指令数 + 15 × L1 未命中

**当前指标**（v1.9 起）：

```
代价 cost = 动态指令数 + α × (D-cache 未命中 + I-cache 未命中)      α = 15
```

`α` 的定义是「一次 L1 未命中折合多少条指令」。依据：

| 环节 | 数值 | 来源强度 |
|---|---|---|
| L1 命中延迟 | 2 拍 | 强（E76 / U74 / Rocket 手册一致） |
| L1 未命中（主要命中 L2） | ~15~20 拍 | 中（厂商不公布，取自公开资料 + 教科书惯例） |
| 未命中是否重叠 | **不重叠** —— E76/U74 的 L1 只有**一个未命中填充槽** | 强（手册明确） |
| 本平台 kernel 实测 IPC | 0.67~0.84 | 强（本仓实测） |

顺序核未命中时完全停顿、没有 MLP 掩盖，所以延迟全额暴露：

```
α = IPC × 一次未命中的周期数 ≈ 0.75 × 20 ≈ 15
```

**发布后不得更改**——否则历史成绩失去可比性。改 α 必须同时重算全部 baseline。

> 若目标换成**无 L2 的 MCU**（E31 / HiFive1 类），未命中直冲主存，α 应取 50~100。
> 本项目按"有 L2 的常见核"取 15。

### miss 项的实际占比

因题而异——访存密集的题目占比高得多：

| 题目 | 最大规模 | 指令数 | miss 项 | 占比 |
|---|---|---|---|---|
| `matmul-4x4` | N=64 | 2,404,765 | 11,655 | **0.5%** |
| `add` | N=4096 | 36,889 | 11,625 | **31.5%** |
| `reducesum` | N=4096 | 20,506 | 3,930 | **19.2%** |

> 早先只盯 matmul 得出的"访存可忽略"结论**不适用于 add/reducesum**。

### 换指标后的排序变化

三题各两档实现共 9 组对比：**排序无一改变**，但差距被**压缩**
（add N=4096：1.564× → 1.378×）。原因是这些优化省的是**指令**，
访存模式相同、miss 数几乎一样——加同一个惩罚项会压缩比值。

**要让访存项真正改变排序，需要能改变访存模式的优化（分块/重排），
并且把规模推到 L1 装不下**（matmul 的悬崖在 N=64~96 之间）。

### 附：访存数据（诊断用）

插件顺带给出 L1 命中统计。

matmul 参考解，工作集 vs L1（32KB）：

| N | 三矩阵 | 占 L1 | D 未命中 | 命中率 |
|---|---|---|---|---|
| 32 | 12 KB | 0.4× | 196 | 99.7% |
| 48 | 27 KB | 0.8× | 437 | 99.8% |
| **64（平台最大）** | **48 KB** | **1.5×** | **773** | **99.9%** |
| 96 | 108 KB | 3.4× | 36,118 | 98.0% |
| 128 | 192 KB | 6.0× | 2,131,711 | **49.4%** |

**悬崖在 N=64 与 N=96 之间，而平台最大数据点正好卡在悬崖之前。**

三题各两档实现（共 9 组对比）在"纯指令数"与"指令数 + α×未命中"两种指标下
**排序完全不变**——因为这些优化（循环展开、多累加器）省的是**指令**，
访存模式一模一样，两组实现的未命中数几乎相同。

**因此**：访存数据现在只记进 `details` 作**诊断**（结果页可展示），不参与计分。
要用它计分，前提是先把题目规模推到悬崖之后。

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

三题参考解都是**尺寸无关**的，同一份 `.s` 要跑通全部 10 个规模。
`tools/gen_baseline.py` 每次生成 baseline 时都会顺带校验：
任一所跑不通就整体报错退出。

### 7.2 规模分级 + 逐点计分（10 项，Flask test client + 临时库）

三题参考解各满分（30/30/40，pass 10/10）；各题 10 个规模互不相同且递增；
baseline 覆盖每个数据点的规模；**逐点独立计分**（让第 2/5/9 点判错 → 7/10 通过、
21 分，失败点 0 分、其余满分）；每个数据点用的是**各自的** baseline（互不相同）。

**耗时**（预算 180s）：add 2.4s、matmul 14.1s、reducesum 2.0s。

### 7.3 提交流程端到端（21 项）

未登录 `/submit` → 302 登录；未入队提交被拒；上传与**粘贴**两种方式都能提交；
错误后缀 / 已下线题目 / 空文件 / 空白粘贴均 400；同时给文件与粘贴时**以文件为准**；
轮询到终态；`verdict=accepted`、满分；结果页渲染逐点得分与用例明细。

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
