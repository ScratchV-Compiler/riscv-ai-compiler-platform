/* 参考解：快速哈达玛变换（FWHT，裸机 ABI，见 docs/08）。
 *
 * 输入：a0 指向 N 个 float32
 *       a2 = 向量长度 N（2 的幂，8 → 4096）
 * 输出：a1 指向 N 个 float32，out = H_N · x（标准正向 FWHT）
 *
 * 尺寸无关：N 从 a2 取。数据为 FP32 浮点，取值 [-1, 1]。
 * 编译固定 -march=rv32imf（单精度 F 扩展）、-mabi=ilp32。
 */

void cnn_entry(const float *in, float *out, int n)
{
    for (int i = 0; i < n; i++) {
        out[i] = in[i];
    }

    for (int span = 1; span < n; span <<= 1) {
        for (int i = 0; i < n; i += 2 * span) {
            for (int j = 0; j < span; j++) {
                float u = out[i + j];
                float v = out[i + j + span];
                out[i + j] = u + v;
                out[i + j + span] = u - v;
            }
        }
    }
}
