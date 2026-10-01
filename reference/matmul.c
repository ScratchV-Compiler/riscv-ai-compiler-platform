/* 参考解：4x4 Q16.16 定点矩阵乘（裸机 ABI，见 docs/08）。
 *
 * 用途有两个：
 *   1. 生成 baseline 指令数（tools/gen_baseline.py）
 *   2. 当作"选手提交"跑回归——评测器若能把它判成 accepted，说明链路是通的
 *
 * 数值口径：acc += (a * b) >> 16，按 RV32 的 srai（算术右移）语义，
 * 与 riscv_oracle.py 的逐步取模实现一致。输入范围锁在 Q16.16 的 [-0.5,0.5)，
 * 单次乘法不溢出 int32，故无需 64 位乘法。
 */

void cnn_entry(const int *in, int *out)
{
    const int *a = in;
    const int *b = in + 16;

    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) {
            int acc = 0;
            for (int k = 0; k < 4; k++) {
                acc += (a[i * 4 + k] * b[k * 4 + j]) >> 16;
            }
            out[i * 4 + j] = acc;
        }
    }
}
