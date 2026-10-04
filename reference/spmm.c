/* 参考解：CSR 稀疏矩阵乘稠密矩阵（裸机 ABI，见 docs/08）。
 *
 * 输入：a0 指向输入张量：
 *       头部 4 个 int32 = [M, K, N, nnz]
 *       随后 row_ptr[M+1]、col_idx[nnz]（均 int32），
 *       再后 values[nnz] 与稠密 B[K*N]（均 float32，B 行主序、N 列）
 *       a2 = 非零元个数 nnz（规模标量，本参考解从头部读取，未用）
 * 输出：a1 指向 M·N 个 float32，行主序
 *       C[i][j] = Σ_{p∈row i} values[p] * B[col_idx[p]*N + j]
 *
 * 尺寸无关：形状从输入头读取，10 个数据点共用同一份代码。
 * 编译固定 -march=rv32imf（单精度 F 扩展）、-mabi=ilp32。
 */

void cnn_entry(const void *vin, void *vout, int scale)
{
    (void)scale;
    const int *hdr = (const int *)vin;
    int M = hdr[0], K = hdr[1], N = hdr[2], nnz = hdr[3];
    const int *row_ptr = hdr + 4;
    const int *col_idx = row_ptr + (M + 1);
    const float *values = (const float *)(col_idx + nnz);
    const float *B = values + nnz;
    float *out = (float *)vout;

    for (int i = 0; i < M; i++) {
        for (int j = 0; j < N; j++) {
            float acc = 0.0f;
            for (int p = row_ptr[i]; p < row_ptr[i + 1]; p++) {
                acc += values[p] * B[col_idx[p] * N + j];
            }
            out[i * N + j] = acc;
        }
    }
}
