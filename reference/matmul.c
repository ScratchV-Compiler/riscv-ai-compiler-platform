/* 参考解：N×N Q16.16 定点矩阵乘（裸机 ABI，见 docs/08）。
 *
 * 输入：a0 指向 2N² 个 int32（前 N² 个是 A，后 N² 个是 B，均行主序）
 *       a2 = 矩阵阶数 N
 * 输出：a1 指向 N² 个 int32，C[i][j] = Σₖ ((A[i][k]*B[k][j]) >> 16)
 *
 * 尺寸无关：N 从 a2 取，数据点规模从 4 到 64 都跑同一份代码。
 * 输入为 Q16.16 的 [-0.5, 0.5)，单次乘法不溢出 int32。
 */

void cnn_entry(const int *in, int *out, int n)
{
    const int *a = in;
    const int *b = in + n * n;

    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            int acc = 0;
            for (int k = 0; k < n; k++) {
                acc += (a[i * n + k] * b[k * n + j]) >> 16;
            }
            out[i * n + j] = acc;
        }
    }
}
