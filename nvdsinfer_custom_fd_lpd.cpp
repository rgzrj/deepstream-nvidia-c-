#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#include "nvdsinfer_custom_impl.h"

#define MIN_VAL(a, b) ((a) < (b) ? (a) : (b))
#define MAX_VAL(a, b) ((a) > (b) ? (a) : (b))
#define CLIP_VAL(a, minv, maxv) (MAX_VAL(MIN_VAL((a), (maxv)), (minv)))
#define DIVIDE_AND_ROUND_UP(a, b) (((a) + (b)-1) / (b))

// 模型维度结构体
struct FdLpdDimsCHW {
    int c = 0;
    int h = 0;
    int w = 0;
};

// 把 DeepStream 模型的维度数据 → 转换成 你自定义的 CHW 结构体
// 3 维：CHW（通道、高、宽）
static bool dims_to_chw(const NvDsInferDims &dims, FdLpdDimsCHW &chw)
{
    if (dims.numDims < 3) {
        return false;
    }

    const int base = dims.numDims - 3;
    chw.c = dims.d[base];
    chw.h = dims.d[base + 1];
    chw.w = dims.d[base + 2];
    return chw.c > 0 && chw.h > 0 && chw.w > 0;
}

// 打印模型的输出层信息
// const std::vector<...> &layers： → 传入模型所有输出层的列表（一层一层的信息）
static void dump_output_layers(const std::vector<NvDsInferLayerInfo> &layers)
{
    // layers.size()：输出层的数量
    std::cerr << "FD_LPD parser received " << layers.size() << " output layer(s)" << std::endl;
    for (size_t i = 0; i < layers.size(); ++i) {
        FdLpdDimsCHW dims;
        const char *name = layers[i].layerName ? layers[i].layerName : "(null)";
        std::cerr << "  [" << i << "] " << name
                  << " dims.numDims=" << layers[i].inferDims.numDims;
        if (dims_to_chw(layers[i].inferDims, dims)) {
            std::cerr << " chw=" << dims.c << "x" << dims.h << "x" << dims.w;
        }
        std::cerr << std::endl;
    }
}

static int find_layer_exact(const std::vector<NvDsInferLayerInfo> &layers,
                            const std::vector<const char *> &names)
{
    for (size_t i = 0; i < layers.size(); ++i) {
        if (!layers[i].layerName) {
            continue;
        }
        for (const char *name : names) {
            if (std::strcmp(layers[i].layerName, name) == 0) {
                return static_cast<int>(i);
            }
        }
    }
    return -1;
}

// 按【通道数+bbox关键词】智能查找
static int find_layer_by_dims(const std::vector<NvDsInferLayerInfo> &layers,
                              int expected_channels,
                              const char *name_hint)
{
    for (size_t i = 0; i < layers.size(); ++i) {
        FdLpdDimsCHW dims;
        if (!dims_to_chw(layers[i].inferDims, dims)) {
            continue;
        }

        const std::string name = layers[i].layerName ? layers[i].layerName : "";
        // 4. 判断：名字是否匹配
        const bool name_matches = name_hint == nullptr || name.find(name_hint) != std::string::npos;
        if (dims.c == expected_channels && name_matches) {
            return static_cast<int>(i);
        }
    }

    for (size_t i = 0; i < layers.size(); ++i) {
        FdLpdDimsCHW dims;
        if (dims_to_chw(layers[i].inferDims, dims) && dims.c == expected_channels) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

//防止函数重载，使用 extern "C" 来指定 C 语言链接方式
extern "C" bool NvDsInferParseCustomResnet(
    // 1. 模型所有输出层信息（数据+维度+名字）
    std::vector<NvDsInferLayerInfo> const &outputLayersInfo,
    // 2. 模型输入信息（宽/高）
    NvDsInferNetworkInfo const &networkInfo,
    // 3. 检测参数（类别数、置信度阈值）
    NvDsInferParseDetectionParams const &detectionParams,
    // 4. 输出：解析后的车牌检测结果（存到这里）
    std::vector<NvDsInferObjectDetectionInfo> &objectList)
{
    static bool printed_layers = false;
    if (!printed_layers) {
        dump_output_layers(outputLayersInfo);
        printed_layers = true;
    }

    // 1. 找【坐标层bbox】：匹配名字 conv2d_bbox / output_bbox
    int bbox_layer_index = find_layer_exact(outputLayersInfo, {
        "conv2d_bbox",
        "output_bbox",
    });
    // 2. 找【置信度层cov】：匹配名字 conv2d_cov/Sigmoid / output_cov
    int cov_layer_index = find_layer_exact(outputLayersInfo, {
        "conv2d_cov/Sigmoid",
        "output_cov",
    });

    if (bbox_layer_index < 0) {
        bbox_layer_index = find_layer_by_dims(
            outputLayersInfo,
            detectionParams.numClassesConfigured * 4,
            "bbox");
    }
    if (cov_layer_index < 0) {
        cov_layer_index = find_layer_by_dims(
            outputLayersInfo,
            detectionParams.numClassesConfigured,
            "cov");
    }

    if (bbox_layer_index < 0 || cov_layer_index < 0) {
        std::cerr << "FD_LPD parser could not find required output layers: "
                  << "bbox_index=" << bbox_layer_index
                  << ", cov_index=" << cov_layer_index << std::endl;
        dump_output_layers(outputLayersInfo);
        return false;
    }

    FdLpdDimsCHW bbox_dims;         //边界框输出层的张量维度
    FdLpdDimsCHW cov_dims;
    // 调用dims_to_chw：把模型维度转成CHW，失败则退出
    if (!dims_to_chw(outputLayersInfo[bbox_layer_index].inferDims, bbox_dims) ||
        !dims_to_chw(outputLayersInfo[cov_layer_index].inferDims, cov_dims)) {
        std::cerr << "FD_LPD parser failed to read output dimensions" << std::endl;
        return false;
    }

    // 实际要解析的类别数：取【模型输出】和【配置文件】的最小值
    const int num_classes_to_parse = std::min(
        cov_dims.c,
        static_cast<int>(detectionParams.numClassesConfigured));

    // 网格的宽度、高度（模型把图片分成的网格大小）
    const int grid_w = cov_dims.w;
    const int grid_h = cov_dims.h;
    const int grid_size = grid_w * grid_h;
    // 模型训练时的坐标归一化系数（固定值，解码坐标必须用）
    constexpr float bbox_norm_x = 35.0f;
    constexpr float bbox_norm_y = 35.0f;

    // 拿到【置信度层】的原始数据指针（一堆float数字）
    const float *output_cov_buf =
        static_cast<const float *>(outputLayersInfo[cov_layer_index].buffer);
    // 拿到【坐标层】的原始数据指针
    const float *output_bbox_buf =
        static_cast<const float *>(outputLayersInfo[bbox_layer_index].buffer);

    if (!output_cov_buf || !output_bbox_buf) {
        std::cerr << "FD_LPD parser got null output buffer" << std::endl;
        return false;
    }

    // 保证网格“平铺”不会漏掉边角  每个格子的像素宽度
    const int stride_x = DIVIDE_AND_ROUND_UP(networkInfo.width, bbox_dims.w);
    const int stride_y = DIVIDE_AND_ROUND_UP(networkInfo.height, bbox_dims.h);

    // 存储网格所有点的X,Y中心坐标
    std::vector<float> gc_centers_x(grid_w);
    std::vector<float> gc_centers_y(grid_h);

    // 计算X方向所有网格中心点
    for (int i = 0; i < grid_w; ++i) {
        gc_centers_x[i] = static_cast<float>(i * stride_x + 0.5f) / bbox_norm_x;
    }
    for (int i = 0; i < grid_h; ++i) {
        gc_centers_y[i] = static_cast<float>(i * stride_y + 0.5f) / bbox_norm_y;
    }

    for (int c = 0; c < num_classes_to_parse; ++c) {
        const float *output_x1 = output_bbox_buf + (c * 4 * bbox_dims.h * bbox_dims.w);
        const float *output_y1 = output_x1 + grid_size;
        const float *output_x2 = output_y1 + grid_size;
        const float *output_y2 = output_x2 + grid_size;

        // 当前类别的置信度阈值（低于这个值的车牌，直接丢弃）
        const float threshold = detectionParams.perClassPreclusterThreshold[c];
        for (int h = 0; h < grid_h; ++h) {
            for (int w = 0; w < grid_w; ++w) {
                // 计算当前网格点的索引
                const int i = w + h * grid_w;
                // 拿到当前网格点的车牌置信度
                const float confidence = output_cov_buf[c * grid_size + i];
                if (!std::isfinite(confidence) || confidence < threshold) {
                    continue;
                }

                // ===================== 核心：解码真实车牌坐标 =====================
                // 模型输出偏移量 + 网格中心点 → 还原真实坐标
                const float rect_x1 =
                    (output_x1[i] - gc_centers_x[w]) * -bbox_norm_x;
                const float rect_y1 =
                    (output_y1[i] - gc_centers_y[h]) * -bbox_norm_y;
                const float rect_x2 =
                    (output_x2[i] + gc_centers_x[w]) * bbox_norm_x;
                const float rect_y2 =
                    (output_y2[i] + gc_centers_y[h]) * bbox_norm_y;
                if (!std::isfinite(rect_x1) || !std::isfinite(rect_y1) ||
                    !std::isfinite(rect_x2) || !std::isfinite(rect_y2)) {
                    continue;
                }

                // ===================== 坐标裁剪：防止超出图片范围 =====================
                const float left = CLIP_VAL(rect_x1, 0.0f, networkInfo.width - 1);
                const float top = CLIP_VAL(rect_y1, 0.0f, networkInfo.height - 1);
                const float right = CLIP_VAL(rect_x2, 0.0f, networkInfo.width - 1);
                const float bottom = CLIP_VAL(rect_y2, 0.0f, networkInfo.height - 1);
                if (right <= left || bottom <= top) {
                    continue;
                }

                // ===================== 把有效车牌框存入结果 =====================
                NvDsInferObjectDetectionInfo object;
                object.classId = c;
                object.detectionConfidence = confidence;
                object.left = left;
                object.top = top;
                object.width = right - left + 1;
                object.height = bottom - top + 1;
                objectList.push_back(object);
            }
        }
    }

    return true;
}

// 告诉 DeepStream 框架，这是自定义车牌检测解析函数
CHECK_CUSTOM_PARSE_FUNC_PROTOTYPE(NvDsInferParseCustomResnet);
