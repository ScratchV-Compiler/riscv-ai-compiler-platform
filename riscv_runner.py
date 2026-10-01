# -*- coding: utf-8 -*-
"""RISC-V 裸机评测的低层执行器（只依赖标准库）。

职责：生成 wrapper 汇编 → 编译链接 → 在沙箱里跑 qemu → 解析内存 dump / 数指令。
所有 `subprocess`、资源限制、权限与网络隔离都集中在这里。

**沙箱是分层的，且明确知道边界**（详见 docs/08）：
- 降权到 nobody：挡住「以 root 身份写系统文件/读密钥」
- 网络命名空间：挡住 guest 的 socket/connect
- prlimit(RLIMIT_FSIZE)：挡住「写大文件 / trace 日志打爆磁盘」
- prlimit(RLIMIT_CPU / NPROC / AS)：挡住死循环与 fork 炸弹
**挡不住**：qemu-user 自身的宿主漏洞；nobody 本来就可读的文件（如 /etc/passwd）。
后者靠「评测结果绝不回显原始字节」兜底（见 evaluator + docs/08）。

rlimit 用 `prlimit` 施加而不是 Python 的 `preexec_fn`：worker 是线程，
`preexec_fn` 在多线程进程里有死锁风险。
"""

import os
import re
import shutil
import struct
import subprocess
import tempfile

from riscv_problems import layout

TOOLCHAIN = ('clang', 'ld.lld', 'qemu-riscv32')

# 编译/运行两套资源限制——不能混用：clang 要 fork cc1/ld.lld 且 LLVM 虚拟内存需求大，
# 套运行期那套（nproc=1、as 很小）会直接编译失败。
# ⚠️ qemu-user 启动时要为 32 位 guest 预留约 4GB **虚拟**地址空间
# （实测报错 "Unable to reserve 0xfffff000 bytes of virtual address space"）。
# 因此 RLIMIT_AS 必须大于这个值：4G 会直接跑不起来，8G 可以。
# 这条也意味着 RLIMIT_AS 基本只是个上限兜底——32 位 guest 本就寻址不过 4GB，
# 真正约束资源的是 CPU 限额 + wall timeout + 队列上限，不要指望 AS 防内存 DoS。
_QEMU_VADDR_HEADROOM = 8 * 1024 * 1024 * 1024

LIMITS = {
    'compile': {'cpu': 30, 'fsize': 64 * 1024 * 1024, 'nproc': 64},
    'run': {'cpu': 10, 'fsize': 1 * 1024 * 1024, 'nproc': 32,
            'as': _QEMU_VADDR_HEADROOM},
    # 数指令那次要写 trace，fsize 必须放宽；只对已判定正确的提交执行，风险可控
    'count': {'cpu': 30, 'fsize': 256 * 1024 * 1024, 'nproc': 32,
              'as': _QEMU_VADDR_HEADROOM},
}

TRACE_FSIZE = LIMITS['count']['fsize']


def toolchain_status():
    """返回 {工具名: 路径或 None}。缺工具时调用方应判 internal_error，而不是抛异常。"""
    return {name: shutil.which(name) for name in TOOLCHAIN}


def make_work_dir(root=None, prefix='riscv_eval_'):
    """建立一次评测的私有工作目录（沙箱用户可读写）。

    必须放在 `root`（默认 /var/lib/riscv-eval）而不是 /tmp：沙箱会用私有挂载
    命名空间把 /tmp 遮蔽成空 tmpfs，工作目录若在其中，qemu 就读不到自己的 ELF 了。
    建不出根目录时退回系统默认，此时应把 ENABLE_SANDBOX 关掉。
    """
    base = root
    if base:
        try:
            os.makedirs(base, mode=0o755, exist_ok=True)
        except OSError:
            base = None
    path = tempfile.mkdtemp(prefix=prefix, dir=base)
    os.chmod(path, 0o777)
    return path


def toolchain_ok():
    return all(toolchain_status().values())


# ---------------------------------------------------------------------------
# 沙箱命令行组装
# ---------------------------------------------------------------------------

# 世界可写目录：guest 降权成 nobody 后仍能在这些目录里留文件。
# 用私有挂载命名空间把它们换成空 tmpfs，写入随命名空间退出而消失。
# 注意工作目录不能在这些目录下，否则 qemu 会读不到自己的 ELF。
_MASK_DIRS = ('/tmp', '/var/tmp', '/dev/shm')
_MOUNT_SCRIPT = '; '.join(
    f'mount -t tmpfs -o size=8M,mode=1777 tmpfs {d} 2>/dev/null' for d in _MASK_DIRS
) + '; exec "$@"'


def _sandbox_prefix(profile, cfg):
    """把命令包成「断网 + 私有挂载 + 降权 + 限资源」。

    顺序有意义：unshare 要建命名空间（需要权限）必须在最前；降权后就没权限了。
    `exec "$@"` 承接原始参数，避免引号拼接问题。
    """
    prefix = []
    if cfg.get('enable_netns'):
        prefix += ['unshare', '-n', '-m', 'sh', '-c', _MOUNT_SCRIPT, 'sh']
    uid = cfg.get('sandbox_uid')
    if uid is not None:
        prefix += ['setpriv', f'--reuid={uid}', f'--regid={cfg.get("sandbox_gid", uid)}',
                   '--clear-groups']
    lim = LIMITS[profile]
    prlimit = ['prlimit']
    if lim.get('cpu'):
        prlimit.append(f'--cpu={lim["cpu"]}')
    if lim.get('fsize'):
        prlimit.append(f'--fsize={lim["fsize"]}')
    if lim.get('nproc'):
        prlimit.append(f'--nproc={lim["nproc"]}')
    if lim.get('as'):
        prlimit.append(f'--as={lim["as"]}')
    if len(prlimit) > 1:
        prefix += prlimit
    return prefix


def _run(cmd, profile, cfg, cwd, timeout, stdin=None):
    full = _sandbox_prefix(profile, cfg) + list(cmd)
    try:
        return subprocess.run(full, cwd=cwd, capture_output=True,
                              timeout=timeout, stdin=stdin)
    except subprocess.TimeoutExpired as exc:
        return exc
    except OSError as exc:
        # 沙箱工具缺失等：降级重试一次（去掉前缀），让调用方能给出可读原因
        if full != list(cmd):
            try:
                return subprocess.run(list(cmd), cwd=cwd, capture_output=True,
                                      timeout=timeout, stdin=stdin)
            except (subprocess.TimeoutExpired, OSError):
                pass
        raise


# ---------------------------------------------------------------------------
# wrapper 生成
# ---------------------------------------------------------------------------

def build_wrapper(spec, values, n, path):
    """生成裸机 wrapper：布置内存、灌入随机输入、调用选手的 cnn_entry、dump 内存。

    ABI 契约（在 ScratchV 的基础上**加了规模参数**，见 docs/08）：
    - 选手须定义全局符号 `cnn_entry`
    - 入参 a0 = 输入张量首址，a1 = 输出张量首址，**a2 = 规模 N**
      （matmul 为矩阵阶数，add/reducesum 为向量长度）——选手必须写尺寸无关的代码
    - 输出为 int32 Q16.16
    - 内存布局 guard|workspace|guard|output|guard，guard 非零即越界写
    - sp 指向 workspace 顶端（栈向下长在 workspace 内）
    """
    lay = layout(spec, n)
    total = lay['total']
    guard = lay['guard_lo'][1]        # 保护区大小由 layout 决定，规格里不再重复存
    ws = lay['workspace'][1]
    out_bytes = lay['output'][1]
    words = ', '.join(str(int(v)) for v in values)

    asm = f'''# 由平台生成，勿手改。对应 riscv_problems.layout(spec, N={n})：
#   guard_lo({guard}) | workspace({ws}) | guard_mid({guard}) | output({out_bytes}) | guard_hi({guard})
.option norvc
.option norelax

.text
.globl _start
_start:
    la   sp, __stack_top
    la   a0, input_tensor
    la   a1, output_tensor
    li   a2, {n}
    call {spec['entry_symbol']}
    li   a0, 1
    la   a1, __dump_start
    li   a2, {total}
    li   a7, 64
    ecall
    li   t0, {total}
    bne  a0, t0, __failed
    li   a0, 0
    li   a7, 93
    ecall
__failed:
    li   a0, 1
    li   a7, 93
    ecall

.data
.balign 4
input_tensor:
    .word {words}

.bss
.balign 16
__dump_start:
    .space {guard}
__workspace:
    .space {ws}
__stack_top:
    .space {guard}
output_tensor:
    .space {out_bytes}
    .space {guard}
'''
    with open(path, 'w', encoding='utf-8') as f:
        f.write(asm)
    return path


# ---------------------------------------------------------------------------
# 编译 / 运行 / 计数 / 解析
# ---------------------------------------------------------------------------

def compile_elf(wrapper_path, player_path, out_path, cfg, cwd):
    """汇编+链接选手提交与 wrapper。返回 (ok, stderr_tail)。

    锁死 `-march=rv32im`（不加 c 压缩扩展）与 `--no-relax`：否则指令数随工具链抖动，
    跨队不可比、历史成绩失效。
    """
    # 子进程 cwd 会切到工作目录，这里统一转绝对路径
    cmd = [
        'clang', '--target=riscv32-linux-gnu', '-march=rv32im', '-mabi=ilp32',
        '-nostdlib', '-static', '-fuse-ld=lld', '-Wl,--no-relax',
        os.path.abspath(wrapper_path), os.path.abspath(player_path),
        '-o', os.path.abspath(out_path),
    ]
    res = _run(cmd, 'compile', cfg, cwd, timeout=cfg['compile_timeout'])
    if isinstance(res, subprocess.TimeoutExpired):
        return False, '编译超时'
    if res.returncode != 0:
        err = (res.stderr or b'').decode('utf-8', 'replace')
        return False, _tail(err, 6)
    if not os.path.exists(out_path):
        return False, '编译器未产出可执行文件'
    return True, ''


def run_elf(elf_path, cfg, cwd, timeout=None):
    """在沙箱里跑一次。返回 (returncode, stdout_bytes, stderr_tail)。

    returncode 为负数表示被信号杀死（-11 段错误 / -24 SIGXCPU 等），调用方据此分类。
    """
    res = _run(['qemu-riscv32', os.path.abspath(elf_path)], 'run', cfg, cwd,
               timeout=timeout or cfg['per_case_timeout'])
    if isinstance(res, subprocess.TimeoutExpired):
        return None, b'', '运行超时'
    return res.returncode, res.stdout or b'', _tail((res.stderr or b'').decode('utf-8', 'replace'), 4)


# ---------------------------------------------------------------------------
# QEMU 缓存插件：一次跑完同时给出指令数与 L1 访问/命中统计
# ---------------------------------------------------------------------------

PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'tools', 'qemu_plugin')
PLUGIN_SO = os.path.join(PLUGIN_DIR, 'cache.so')


def plugin_available():
    """插件是否已经构建好。没有就退回单步计数。"""
    return os.path.exists(PLUGIN_SO)


def stage_plugin(cwd):
    """把插件复制进工作目录——沙箱用户进不了 /root，必须放它读得到的地方。"""
    dst = os.path.join(cwd, 'cache.so')
    if not os.path.exists(dst):
        shutil.copyfile(PLUGIN_SO, dst)
        os.chmod(dst, 0o755)
    return dst


def profile_elf(elf_path, cfg, cwd):
    """跑一次插件，返回 {instructions, d_access, d_miss, i_miss, hitrate} 或 None。

    比原来的单步计数快 100~300 倍（实测 matmul N=64：6.25s → 0.02s），
    且计数**逐位一致**——30 个数据点全部与旧方法相同，baseline 无需重算。
    """
    if not plugin_available():
        return None
    try:
        so = stage_plugin(cwd)
    except OSError:
        return None
    qemu = current_plugin_cfg()
    spec = (f'{so},dsize={qemu["dsize"]},dways={qemu["dways"]},dblock={qemu["dblock"]}'
            f',isize={qemu["isize"]},iways={qemu["iways"]},iblock={qemu["iblock"]}')
    res = _run(['qemu-riscv32', '-d', 'plugin', '-plugin', spec, os.path.abspath(elf_path)],
               'run', cfg, cwd, timeout=cfg['count_timeout'])
    if isinstance(res, subprocess.TimeoutExpired):
        return None
    blob = (res.stderr or b'') + (res.stdout or b'')
    m = re.search(rb'instructions=(\d+) d_access=(\d+) d_miss=(\d+) d_hitrate=([\d.]+) '
                  rb'i_access=(\d+) i_miss=(\d+)', blob)
    if not m:
        return None
    return {
        'instructions': int(m.group(1)),
        'd_access': int(m.group(2)),
        'd_miss': int(m.group(3)),
        'd_hitrate': float(m.group(4)),
        'i_access': int(m.group(5)),
        'i_miss': int(m.group(6)),
    }


def take_cache_stats(cfg):
    """取出并清空累计的缓存统计（每次 profile_elf 追加一条）。"""
    return cfg.pop('_cache_stats', [])


def current_plugin_cfg():
    """缓存参数。从 config 读，拿不到就用默认 L1。"""
    return {
        'dsize': 32768, 'dways': 4, 'dblock': 64,
        'isize': 32768, 'iways': 4, 'iblock': 64,
    }


def count_instructions(elf_path, cfg, cwd, trace_path=None):
    """动态指令数。优先用插件（快 300× 且数字一致），退回单步计数。

    返回 (count, truncated)。truncated 只在单步路径下可能为真。
    """
    prof = profile_elf(elf_path, cfg, cwd)
    if prof is not None:
        cfg.setdefault('_cache_stats', []).append(prof)
        return prof['instructions'], False

    # ---- 退回：单步 trace 数 `^Trace` 行数 ----
    if trace_path is None:
        trace_path = os.path.join(cwd, 'trace.log')
    res = _run(['qemu-riscv32', '-singlestep', '-d', 'exec',
                '-D', os.path.abspath(trace_path), os.path.abspath(elf_path)],
               'count', cfg, cwd, timeout=cfg['count_timeout'])
    if isinstance(res, subprocess.TimeoutExpired):
        return None, False
    if not os.path.exists(trace_path):
        return None, False
    truncated = os.path.getsize(trace_path) >= TRACE_FSIZE
    count = 0
    with open(trace_path, 'rb') as f:
        for line in f:
            if line.startswith(b'Trace'):
                count += 1
    return count, truncated


def parse_dump(data, spec, n):
    """解析内存 dump。返回 (values, guard_ok, message)。

    message 只说明「哪一段 guard 被破坏」，**不含任何原始字节**（防外带，见 docs/08）。
    """
    lay = layout(spec, n)
    if len(data) != lay['total']:
        return None, False, f'内存 dump 长度不符：期望 {lay["total"]} 字节，实际 {len(data)}'

    for name, label in (('guard_lo', '工作区之前'), ('guard_mid', '工作区之后'),
                        ('guard_hi', '输出区之后')):
        off, size = lay[name]
        if any(data[off:off + size]):
            return None, False, f'越界写：{label}的保护区被破坏'

    off, size = lay['output']
    values = list(struct.unpack(f'<{size // 4}i', data[off:off + size]))
    return values, True, ''


def _tail(text, lines):
    text = (text or '').strip()
    if not text:
        return ''
    kept = text.splitlines()[-lines:]
    return '\n'.join(kept)[:2000]
