// PL共享8/9维特征提取 + 树分类 / MLP / 真实回波一维CNN。结果协议版本3。
// 不把模型固化在 bitstream 中；PS 每次训练后重新加载 DDR 节点表即可。
#include <stdint.h>
#include <math.h>

static const int MAX_BINS = 65536;
static const int MAX_CLASSES = 64;
static const int MAX_TREES = 128;
static const int MAX_NODES = 16384;
static const int MAX_STEPS = 33;

static uint64_t window_start(const uint32_t *hist, int center,
                             uint32_t ring[41]) {
    uint64_t sum = 0;
    for (int j = 0; j < 41; ++j) {
        uint32_t value = hist[center - 20 + j];
        ring[j] = value;
        sum += value;
    }
    return sum;
}

// 所有查峰区间离边界至少 20 个 bin，无需边界填充。
// 用整数窗口和比较，严格保留 Python 版本的并列取第一个峰规则。
static int find_peak(const uint32_t *hist, int start, int end,
                     uint64_t &maximum) {
    uint32_t ring[41];
    uint64_t sum = window_start(hist, start, ring);
    maximum = sum;
    int best = start, slot = 0;
    for (int center = start + 1; center < end; ++center) {
        uint32_t next = hist[center + 20];
        sum = sum - ring[slot] + next;
        ring[slot] = next;
        slot = (slot == 40) ? 0 : slot + 1;
        if (sum > maximum) { maximum = sum; best = center; }
    }
    return best;
}

static double at_least_one(double value) { return value < 1.0 ? 1.0 : value; }

// 线性SVM与三层小MLP使用同一乘加函数。输入/输出最多64维，
// 按神经元和输入顺序复用运算器，不把976次乘法全部展开成并行硬件。
static void dense_layer(const double parameters[2048], int base,
                        int inputs, int outputs, const double values[144],
                        double next[64], bool relu) {
#pragma HLS INLINE off
    for (int out = 0; out < outputs; ++out) {
        double sum = parameters[base + inputs * outputs + out];
        for (int in = 0; in < inputs; ++in) {
            sum += values[in] * parameters[base + in * outputs + out];
        }
        next[out] = relu && sum < 0 ? 0 : sum;
    }
}

static bool dense_infer(const double *model, int kind, int classes,
                        const float features[9], int feature_count,
                        const uint32_t *hist, int echo, double scores[64]) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION instances=dense_layer limit=1 function
    // 卷积、MLP与CNN全连接共用同一个串行乘加函数和同一份参数RAM。
    // CNN不展开256×4×5个乘法器；通道数固定4，隐藏层固定8。
    double parameters[2048], values[144], next[64];
#pragma HLS RESOURCE variable=parameters core=RAM_1P_BRAM
    int out = int(model[3]);
    if (int(model[0]) != feature_count || classes < 2 || classes > 64) return false;
    if (kind == 2 && (int(model[1]) != 32 || int(model[2]) != 16 || out != (classes == 2 ? 1 : classes))) return false;
    if (kind == 3 && (feature_count != 9 || int(model[1]) != 4 || int(model[2]) != 8 || out != classes)) return false;
    int header = 4 + 2 * feature_count;
    int count = kind == 3 ? header + 24 + 137*8 + 8 + 9*classes : header + feature_count*32 + 32 + 32*16 + 16 + 16*out + out;
    if (count > 2048) return false;
    for (int i=0; i<count; ++i) parameters[i] = model[i];
    for (int i=0; i<feature_count; ++i) {
        if (!(parameters[4+feature_count+i] > 0)) return false;
        values[i] = (double(features[i]) - parameters[4+i]) / parameters[4+feature_count+i];
    }
    int base = header, inputs = feature_count;
    if (kind == 3) {
        if (echo < 1024 || echo+1024 > MAX_BINS) return false;
        double auxiliary[9];
        for (int i=0; i<9; ++i) auxiliary[i]=values[i];
        uint64_t total=0, grouped[256];
        for (int j=0; j<256; ++j) {
            uint64_t sum=0;
            for (int k=0; k<8; ++k) sum+=hist[echo-1024+j*8+k];
            grouped[j]=sum;total+=sum;
        }
        if (total==0) return false;
        float wave[256];
        for (int j=0; j<256; ++j) wave[j]=double(grouped[j])*256.0/double(total);
        for (int i=0; i<128; ++i) values[i]=0;
        for (int j=0; j<256; ++j) {
            double patch[144];
            for (int k=0; k<5; ++k) {
                int at=j+k-2;patch[k]=(at<0 || at>=256) ? 0.0 : double(wave[at]);
            }
            dense_layer(parameters,header,5,4,patch,next,true);
            for (int c=0; c<4; ++c) values[(j/8)*4+c]+=next[c]/8.0;
        }
        for (int i=0; i<9; ++i) values[128+i]=auxiliary[i];
        base+=24;inputs=137;
    }
    int layers = kind == 3 ? 2 : 3;
    for (int layer=0; layer<layers; ++layer) {
        int outputs = kind == 3 ? (layer == 0 ? 8 : classes) : (layer == 0 ? 32 : layer == 1 ? 16 : out);
        dense_layer(parameters, base, inputs, outputs, values, next, layer < layers-1);
        for (int i=0; i<outputs; ++i) values[i] = next[i];
        base += inputs * outputs + outputs;
        inputs = outputs;
    }
    // PL输出logit并完成argmax，PS做softmax展示，避免增加指数硬件。
    for (int c=0; c<classes; ++c) scores[c] = kind == 2 && out == 1 ? (c == 0 ? 0.0 : values[0]) : values[c];
    return true;
}

extern "C" void tdc_accelerator(const uint32_t *hist, const double *model,
                                double *result, int bin_count,
                                int class_count, int tree_count, int node_count,
                                int model_kind, int feature_count,
                                double timing_reference_bin) {
#pragma HLS INTERFACE m_axi port=hist offset=slave bundle=histmem depth=65536 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=model offset=slave bundle=modelmem depth=1114240 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=result offset=slave bundle=resultmem depth=88
#pragma HLS INTERFACE s_axilite port=hist bundle=control offset=0x10
#pragma HLS INTERFACE s_axilite port=model bundle=control offset=0x1c
#pragma HLS INTERFACE s_axilite port=result bundle=control offset=0x28
#pragma HLS INTERFACE s_axilite port=bin_count bundle=control offset=0x34
#pragma HLS INTERFACE s_axilite port=class_count bundle=control offset=0x3c
#pragma HLS INTERFACE s_axilite port=tree_count bundle=control offset=0x44
#pragma HLS INTERFACE s_axilite port=node_count bundle=control offset=0x4c
#pragma HLS INTERFACE s_axilite port=model_kind bundle=control offset=0x54
#pragma HLS INTERFACE s_axilite port=feature_count bundle=control offset=0x5c
#pragma HLS INTERFACE s_axilite port=timing_reference_bin bundle=control offset=0x64
#pragma HLS INTERFACE s_axilite port=return bundle=control
    // result: 0=错误码，1=类别索引，2/3=前峰/回波峰，4=协议版本，
    //         5=维数，6=时移基线，8..16=特征，24..87=各类概率/logit。
    for (int k = 0; k < 88; ++k) result[k] = 0;
    result[0] = 1; result[1] = -1; result[4] = 3;
    result[5] = feature_count; result[6] = timing_reference_bin;
    if (bin_count < 30000 || bin_count > MAX_BINS || class_count < 1 ||
        class_count > MAX_CLASSES || (model_kind != 0 && model_kind != 2 && model_kind != 3) ||
        (feature_count != 8 && feature_count != 9) || !isfinite(timing_reference_bin)) return;
    if (model_kind == 0 && (tree_count < 1 || tree_count > MAX_TREES || node_count < 1 || node_count > MAX_NODES)) return;

    const int reference_end = bin_count - 1024 < 30000 ? bin_count - 1024 : 30000;
    uint64_t reference_height, echo_height;
    int reference = find_peak(hist, 512, reference_end, reference_height);
    int start = reference + 2000;
    int end = reference + 20000 < bin_count - 1024 ? reference + 20000 : bin_count - 1024;
    result[2] = reference;
    result[0] = 2;
    if (reference < 400 || start + 700 >= end) return;
    int echo = find_peak(hist, start, end, echo_height);
    result[3] = echo;
    result[0] = 3;
    if (echo < 400 || echo + 700 >= bin_count) return;
    result[0] = 4;
    if (echo_height < 205) return; // 平滑峰高 <5，即 41bin 窗口和 <205。

    uint64_t reference_area = 0, area150 = 0, area350 = 0;
    uint64_t core = 0, head = 0, tail = 0;
    double weighted_sum = 0;
    for (int i = -150; i <= 150; ++i) reference_area += hist[reference + i];
    for (int i = -350; i <= 350; ++i) {
        uint32_t value = hist[echo + i];
        area350 += value;
        weighted_sum += double(i) * double(value);
        if (i >= -150 && i <= 150) area150 += value;
        if (i >= -50 && i <= 50) core += value;
        if (i >= -250 && i < -50) head += value;
        if (i >= 51 && i <= 250) tail += value;
    }
    // 两遍中心化方差与 Python extract_features 一致，避免改变训练特征定义。
    double denominator = at_least_one(double(area350));
    double mean = weighted_sum / denominator, variance = 0;
    for (int i = -350; i <= 350; ++i) {
        double delta = double(i) - mean;
        variance += delta * delta * double(hist[echo + i]);
    }
    uint32_t ring[41];
    uint64_t sum = window_start(hist, echo - 500, ring);
    int first = -1, last = -1, slot = 0;
    for (int i = 0; i <= 1000; ++i) {
        if (i > 0) {
            uint32_t next = hist[echo - 500 + i + 20];
            sum = sum - ring[slot] + next;
            ring[slot] = next; slot = slot == 40 ? 0 : slot + 1;
        }
        if (2 * sum >= echo_height) { if (first < 0) first = i; last = i; }
    }
    float features[9];
    features[0] = double(area150) / at_least_one(double(reference_area));
    features[1] = double(area350) / at_least_one(double(reference_area));
    features[2] = (double(echo_height) / 41.0) / at_least_one(double(reference_height) / 41.0);
    features[3] = double(core) / denominator;
    features[4] = double(tail) / at_least_one(double(head));
    features[5] = last - first + 1;
    features[6] = sqrt(variance / denominator);
    features[7] = (double(echo_height) / 41.0) / denominator;
    features[8] = double(echo) - timing_reference_bin;
    for (int k = 0; k < feature_count; ++k) result[8 + k] = double(features[k]);

    // model: tree_count 个根节点索引，然后每节点 [feature,left,right,threshold,p0,...]。
    // 阈值和叶概率保持 double；输入先转 float32，与 sklearn 的比较顺序一致。
    double scores[MAX_CLASSES];
    for (int c = 0; c < MAX_CLASSES; ++c) scores[c] = 0;
    if (model_kind != 0) {
        result[0] = 6;
        if (!dense_infer(model,model_kind,class_count,features,feature_count,hist,echo,scores)) return;
        int best = 0;
        for (int c=0; c<class_count; ++c) {
            result[24+c] = scores[c];
            if (scores[c] > scores[best]) best = c;
        }
        result[1] = best; result[0] = 0;
        return;
    }
    int stride = 4 + class_count;
    result[0] = 5;
    for (int t = 0; t < tree_count; ++t) {
        int node = int(model[t]);
        bool reached_leaf = false;
        for (int step = 0; step < MAX_STEPS; ++step) {
            if (node < 0 || node >= node_count) return;
            int offset = tree_count + node * stride;
            int feature = int(model[offset]);
            if (feature == -2) {
                for (int c = 0; c < class_count; ++c) scores[c] += model[offset + 4 + c];
                reached_leaf = true; break;
            }
            if (feature < 0 || feature >= feature_count) return;
            double threshold = model[offset + 3];
            node = int(model[offset + (double(features[feature]) <= threshold ? 1 : 2)]);
        }
        if (!reached_leaf) return;
    }
    int best = 0;
    for (int c = 0; c < class_count; ++c) {
        result[24 + c] = scores[c] / tree_count;
        if (scores[c] > scores[best]) best = c;
    }
    result[1] = best; result[0] = 0;
}
