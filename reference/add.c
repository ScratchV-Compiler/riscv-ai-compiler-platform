/* 参考解：两个长度 N 的向量逐元素相加（裸机 ABI，见 docs/08）。
 *
 * 输入：a0 指向 2N 个 int32（前 N 个是 A，后 N 个是 B）
 *       a2 = 向量长度 N
 * 输出：a1 指向 N 个 int32，C[i] = A[i] + B[i]
 *
 * 尺寸无关：N 从 a2 取。输入为 Q16.16 的 [-0.5, 0.5)，
 * 单次相加最大 65534，不溢出 int32。
 */

void cnn_entry(const int *in, int *out, int n)
{
    const int *a = in;
    const int *b = in + n;

    for (int i = 0; i < n; i++) {
        out[i] = a[i] + b[i];
    }
}
