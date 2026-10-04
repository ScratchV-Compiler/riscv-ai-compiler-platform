/* 参考解：2D 直接卷积（SAME padding、stride=1、K∈{3,5}），FP32（裸机 ABI，见 docs/08）。
 *
 * 输入：a0 指向输入张量：
 *       头部 6 个 int32 = [batch, H, W, Cin, Cout, K]
 *       随后特征图（batch·H·W·Cin 个 float，NCHW 排布）
 *       再后权重（Cout·Cin·K·K 个 float，OIHW 排布）
 *       a2 = batch·H·W·Cin（规模标量，本参考解从头部读取，未用）
 * 输出：a1 指向 batch·Cout·H·W 个 float（NCHW）；SAME padding 使输出空间尺寸为 H×W
 *
 * **baseline = 未优化的直接滑窗卷积**（6 层循环，无分块/向量化）；选手可用
 * Winograd 变换（F(2,3)/F(4,3)…）减少乘法次数。尺寸无关：形状从输入头读取。
 *
 * 编译固定 -march=rv32imf（单精度 F 扩展）、-mabi=ilp32。
 */

void cnn_entry(const void *vin, void *vout, int scale)
{
    (void)scale;
    const int *hdr = (const int *)vin;
    int batch = hdr[0], H = hdr[1], W = hdr[2];
    int Cin = hdr[3], Cout = hdr[4], K = hdr[5];
    const float *feat = (const float *)(hdr + 6);
    const float *wt = feat + batch * H * W * Cin;
    float *out = (float *)vout;
    int pad = K / 2;

    for (int b = 0; b < batch; b++) {
        for (int oc = 0; oc < Cout; oc++) {
            for (int oh = 0; oh < H; oh++) {
                for (int ow = 0; ow < W; ow++) {
                    float acc = 0.0f;
                    for (int c = 0; c < Cin; c++) {
                        for (int kh = 0; kh < K; kh++) {
                            int ih = oh - pad + kh;
                            if (ih < 0 || ih >= H) {
                                continue;
                            }
                            for (int kw = 0; kw < K; kw++) {
                                int iw = ow - pad + kw;
                                if (iw < 0 || iw >= W) {
                                    continue;
                                }
                                float x = feat[((b * H + ih) * W + iw) * Cin + c];
                                float w = wt[((oc * Cin + c) * K + kh) * K + kw];
                                acc += x * w;
                            }
                        }
                    }
                    out[((b * Cout + oc) * H + oh) * W + ow] = acc;
                }
            }
        }
    }
}
