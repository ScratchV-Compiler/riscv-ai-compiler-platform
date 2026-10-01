/* 参考解：全归约求和（裸机 ABI，见 docs/08）。
 *
 * 输入：a0 指向 64 个 int32。
 * 输出：a1 指向 1 个 int32，out[0] = Σ in[i]。
 *
 * 长度须与 riscv_problems.VECTOR_LEN 一致。输入落在 Q16.16 的 [-0.5, 0.5)，
 * 64 项求和最大绝对值 64 × 32768 = 2^21，不会溢出 int32。
 */

#define N 64

void cnn_entry(const int *in, int *out)
{
    int acc = 0;

    for (int i = 0; i < N; i++) {
        acc += in[i];
    }
    out[0] = acc;
}
