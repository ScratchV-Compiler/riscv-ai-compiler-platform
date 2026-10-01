/* 参考解：全归约求和（裸机 ABI，见 docs/08）。
 *
 * 输入：a0 指向 N 个 int32
 *       a2 = 向量长度 N
 * 输出：a1 指向 1 个 int32，out[0] = Σ in[i]
 *
 * 尺寸无关：N 从 a2 取。输入为 Q16.16 的 [-0.5, 0.5)，
 * N=4096 时求和最大绝对值 4096 × 32768 = 2^27，不溢出 int32。
 */

void cnn_entry(const int *in, int *out, int n)
{
    int acc = 0;

    for (int i = 0; i < n; i++) {
        acc += in[i];
    }
    out[0] = acc;
}
