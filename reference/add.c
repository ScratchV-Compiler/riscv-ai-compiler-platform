/* 参考解：两个长度 64 的向量逐元素相加（裸机 ABI，见 docs/08）。
 *
 * 输入：a0 指向 128 个 int32 —— 前 64 个是 A，后 64 个是 B。
 * 输出：a1 指向 64 个 int32，C[i] = A[i] + B[i]。
 *
 * 长度须与 riscv_problems.VECTOR_LEN 一致。输入落在 Q16.16 的 [-0.5, 0.5)，
 * 单次相加最大 65534，不会溢出 int32。
 */

#define N 64

void cnn_entry(const int *in, int *out)
{
    const int *a = in;
    const int *b = in + N;

    for (int i = 0; i < N; i++) {
        out[i] = a[i] + b[i];
    }
}
