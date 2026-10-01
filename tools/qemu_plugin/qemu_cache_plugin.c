/* QEMU TCG 插件：L1 数据/指令缓存模拟 + 动态指令计数
 *
 * 为什么在**插件内**做模拟：完整访存日志会把磁盘打爆（实测 qemu `-d cpu`
 * 是 603 字节/指令，matmul N=64 要 1.35 GB）。插件在进程内累加，只输出一行汇总，
 * 日志体积与程序规模无关。
 *
 * 附带收益：计数比 `-singlestep -d exec` 快 100~300 倍，且逐位一致
 * （实测 matmul N=16/32/64 三个规模计数完全相同）。
 *
 * 用法：
 *   qemu-riscv32 -d plugin \
 *     -plugin ./cache.so,dsize=32768,dways=4,dblock=64,isize=32768,iways=4,iblock=64 \
 *     <elf>
 *
 * 输出一行：QEMU_CACHE instructions=... d_access=... d_miss=... i_access=... i_miss=...
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "qemu-plugin.h"

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;

/* ---- 集合相联 LRU 缓存 ---- */
typedef struct {
    long nsets, nways, block;
    unsigned long long *tags, *age, tick;
    unsigned long long access, miss;
} Cache;

static Cache D, I;
static unsigned long long n_insn;

static void cache_init(Cache *c, long size, long ways, long block)
{
    c->nways = ways > 0 ? ways : 1;
    c->block = block > 0 ? block : 64;
    c->nsets = size / (c->nways * c->block);
    if (c->nsets < 1) c->nsets = 1;
    c->tags = calloc((size_t)c->nsets * c->nways, sizeof(*c->tags));
    c->age  = calloc((size_t)c->nsets * c->nways, sizeof(*c->age));
}

static void cache_access(Cache *c, unsigned long long addr)
{
    if (!c->tags) return;
    unsigned long long blk = addr / (unsigned long long)c->block;
    long set = (long)(blk % (unsigned long long)c->nsets);
    unsigned long long tag = blk / (unsigned long long)c->nsets;
    unsigned long long base = (unsigned long long)set * c->nways;

    c->access++;
    for (long w = 0; w < c->nways; w++) {
        if (c->age[base + w] && c->tags[base + w] == tag) {
            c->age[base + w] = ++c->tick;       /* 命中 */
            return;
        }
    }
    c->miss++;
    long victim = 0;                             /* 淘汰最久未用 */
    for (long w = 1; w < c->nways; w++)
        if (c->age[base + w] < c->age[base + victim]) victim = w;
    c->tags[base + victim] = tag;
    c->age[base + victim] = ++c->tick;
}

/* ---- 数据访问回调 ---- */
static void mem_cb(unsigned int vcpu, qemu_plugin_meminfo_t info,
                   uint64_t vaddr, void *ud)
{
    (void)vcpu; (void)ud; (void)info;
    cache_access(&D, vaddr);
}

/* ---- 每个 TB 记录自己的指令地址，供 I-cache 在**执行时**使用 ---- */
typedef struct { unsigned long long *addrs; size_t n; } TbInfo;

static void tb_exec_cb(unsigned int vcpu, void *ud)
{
    (void)vcpu;
    TbInfo *t = ud;
    for (size_t i = 0; i < t->n; i++)
        cache_access(&I, t->addrs[i]);
}

static void tb_trans_cb(qemu_plugin_id_t id, struct qemu_plugin_tb *tb)
{
    size_t n = qemu_plugin_tb_n_insns(tb);
    TbInfo *t = malloc(sizeof(TbInfo));
    t->n = n;
    t->addrs = malloc(n * sizeof(unsigned long long));

    for (size_t i = 0; i < n; i++) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i);
        t->addrs[i] = qemu_plugin_insn_vaddr(insn);
        /* 只注册一次 MEM_RW：注册 R 与 W 两次会让每次访存触发两遍 */
        qemu_plugin_register_vcpu_mem_cb(insn, mem_cb, QEMU_PLUGIN_CB_NO_REGS,
                                         QEMU_PLUGIN_MEM_RW, NULL);
        /* 指令数内联累加，几乎零开销 */
        qemu_plugin_register_vcpu_insn_exec_inline(insn, QEMU_PLUGIN_INLINE_ADD_U64,
                                                   &n_insn, 1);
    }
    /* I-cache 按 TB 粒度记账，避免逐指令回调的开销 */
    qemu_plugin_register_vcpu_tb_exec_cb(tb, tb_exec_cb,
                                         QEMU_PLUGIN_CB_NO_REGS, t);
}

static void plugin_exit(qemu_plugin_id_t id, void *p)
{
    (void)id; (void)p;
    char buf[320];
    double dhr = D.access ? 100.0 * (D.access - D.miss) / D.access : 0.0;
    double ihr = I.access ? 100.0 * (I.access - I.miss) / I.access : 0.0;
    snprintf(buf, sizeof(buf),
             "QEMU_CACHE instructions=%llu d_access=%llu d_miss=%llu d_hitrate=%.2f "
             "i_access=%llu i_miss=%llu i_hitrate=%.2f\n",
             n_insn, D.access, D.miss, dhr, I.access, I.miss, ihr);
    qemu_plugin_outs(buf);
    fputs(buf, stderr);
}

QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id,
                                           const qemu_info_t *info,
                                           int argc, char **argv)
{
    long dsize = 32768, dways = 4, dblock = 64;
    long isize = 32768, iways = 4, iblock = 64;
    for (int i = 0; i < argc; i++) {
        if (sscanf(argv[i], "dsize=%ld", &dsize) == 1) continue;
        if (sscanf(argv[i], "dways=%ld", &dways) == 1) continue;
        if (sscanf(argv[i], "dblock=%ld", &dblock) == 1) continue;
        if (sscanf(argv[i], "isize=%ld", &isize) == 1) continue;
        if (sscanf(argv[i], "iways=%ld", &iways) == 1) continue;
        if (sscanf(argv[i], "iblock=%ld", &iblock) == 1) continue;
    }
    cache_init(&D, dsize, dways, dblock);
    cache_init(&I, isize, iways, iblock);
    qemu_plugin_register_vcpu_tb_trans_cb(id, tb_trans_cb);
    qemu_plugin_register_atexit_cb(id, plugin_exit, NULL);
    return 0;
}
