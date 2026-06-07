#include <algorithm>
#include <iostream>
#include <cstdio>
#include <signal.h>
#include <string.h>
#include <sys/stat.h>
#include <gst/gst.h>
#include <gst/app/gstappsrc.h>
#include "gstnvdsmeta.h"
#include "MvCameraControl.h"

// 海康 SDK 相关全局变量
void*               g_hCamera = nullptr;            //相机句柄
MV_CC_DEVICE_INFO_LIST g_stDeviceList = {0};        //设备列表结构体
bool                g_bExit = false;                //程序退出标志位

// GStreamer 管道相关
//GStreamer 的核心思想是“管道（Pipeline）”，它由一系列叫做 “元件（Element）” 的功能模块组成。
// 每个元件就像一个专门车间，负责完成特定任务，例如：

//数据源 (Source)：负责从文件、网络摄像头或网络流中获取原始数据。

// 解码器 (Decoder)：将压缩的音视频数据（如H.264, AAC）还原为原始数据流。

// 编码器 (Encoder)：将原始数据流压缩成特定格式。

// 输出/渲染 (Sink)：是管道的最终环节，如将视频显示在屏幕上、将音频输出到声卡，或保存为文件。

// 这些“车间”之间的传送带就是 “衬垫 (Pad)” ，分为 src（输出）和 sink（输入）两种。

GstElement*      g_pipeline = nullptr;        //GStreamer 管道，将数据流转化为特定格式
GstElement*      g_appsrc   = nullptr;        //GstAppSrc 元件，用于从应用程序推送数据到管道，接受图像数据流
GMainLoop*       g_loop     = nullptr;        //GLib 主循环，用于处理 GStreamer 事件和回调，管理各个任务正常运行

static constexpr int kCameraWidth = 1440;
static constexpr int kCameraHeight = 1080;
static constexpr int kCameraFps = 15;

//切换工作模式
static bool WarnCameraSetFailed(const char *name, int ret)
{
    // ret在这里指传入海康 SDK 函数返回的原始错误码
    if (ret == MV_OK) {
        return true;
    }

    std::cerr << "WARN: set camera parameter " << name
              << " failed: 0x" << std::hex << ret << std::dec << std::endl;
    return false;
}

// 切换工作模式：触发模式、曝光模式、像素格式
static bool TrySetEnum(const char *name, unsigned int value)
{
    return WarnCameraSetFailed(name, MV_CC_SetEnumValue(g_hCamera, name, value));
}

// 调节图像质量参数：曝光时间、增益、帧率、伽马
static bool TrySetFloat(const char *name, float value)
{
    return WarnCameraSetFailed(name, MV_CC_SetFloatValue(g_hCamera, name, value));
}

// 设置只有开 / 关两种状态的参数：软触发、参数保存、信号反转
static bool TrySetBool(const char *name, bool value)
{
    return WarnCameraSetFailed(name, MV_CC_SetBoolValue(g_hCamera, name, value));
}

static void ConfigureCameraImageQuality()
{
    // 开启帧率控制
    TrySetBool("AcquisitionFrameRateEnable", true);
    if (!TrySetFloat("AcquisitionFrameRate", static_cast<float>(kCameraFps))) {
        TrySetFloat("AcquisitionFrameRateAbs", static_cast<float>(kCameraFps));
    }

    // 关闭自动曝光
    TrySetEnum("ExposureAuto", 0);
    if (!TrySetFloat("ExposureTime", 20000.0f)) {
        TrySetFloat("ExposureTimeAbs", 20000.0f);
    }

    // 关闭自动曝光增益
    TrySetEnum("GainAuto", 0);
    // 手动设置增益值
    TrySetFloat("Gain", 8.0f);

    // 开启 Gamma 校正，并设置为 0.70，Gamma 是调整图像中间亮度的非线性曲线
    TrySetBool("GammaEnable", true);
    TrySetFloat("Gamma", 0.70f);

    // 设置自动白平衡模式为 2（通常是“连续自动白平衡”）
    TrySetEnum("BalanceWhiteAuto", 2);
}

// 图像回调函数：海康取流回调，将图像帧推入 appsrc
static void __stdcall ImageCallBack(unsigned char *pData,           // 图像数据的指针
                                    MV_FRAME_OUT_INFO_EX *pFrameInfo,   // 图像信息（宽、高、大小、像素格式）
                                    void *pUser)                    // 用户自定义指针（这里未使用）
{
    if (pFrameInfo == nullptr || pData == nullptr) return;
    if (g_appsrc == nullptr) return;

    static GstClockTime last_push_time = GST_CLOCK_TIME_NONE;       //上一次推送的时间戳
    const GstClockTime frame_interval = gst_util_uint64_scale(1, GST_SECOND, kCameraFps);       //帧间隔时间（根据设定的帧率计算）
    const GstClockTime now = gst_util_get_timestamp();              //当前时间
    if (last_push_time != GST_CLOCK_TIME_NONE && now - last_push_time < frame_interval) {
        return;
    }
    last_push_time = now;

    //每300帧进行一次输出
    static int frame_count = 0;
    if (frame_count == 0) {
        g_print("First frame received: %dx%d, len=%d, pixel=0x%lx\n",
                pFrameInfo->nWidth, pFrameInfo->nHeight,
                pFrameInfo->nFrameLen, pFrameInfo->enPixelType);
    }
    if (++frame_count % 300 == 0) {
        g_print("Camera: %d frames pushed\n", frame_count);
    }

    // 向 GStreamer 申请一块大小刚好等于一帧图像大小的内存区域，这个区域由 GStreamer 管理
    GstBuffer *buffer = gst_buffer_new_allocate(NULL, pFrameInfo->nFrameLen, NULL);
    if (!buffer) {
        g_printerr("Failed to allocate GstBuffer\n");
        return;
    }

    GstMapInfo map;
    // 将刚才分配的缓冲区buffer映射到用户空间map，这样我们才能往里面写数据
    if (!gst_buffer_map(buffer, &map, GST_MAP_WRITE)) {
        g_printerr("Failed to map GstBuffer\n");
        gst_buffer_unref(buffer);
        return;
    }
    memcpy(map.data, pData, pFrameInfo->nFrameLen);
    // 解除映射，告诉 GStreamer 数据已经写入完毕
    gst_buffer_unmap(buffer, &map);

    static GstClockTime timestamp = 0;、
    // 这一帧的显示时间戳
    GST_BUFFER_PTS(buffer) = timestamp;
    // 这一帧的持续时间
    GST_BUFFER_DURATION(buffer) = gst_util_uint64_scale(1, GST_SECOND, kCameraFps);
    timestamp += GST_BUFFER_DURATION(buffer);

    // 把封装好的 GstBuffer 推送给 g_appsrc 投料口
    GstFlowReturn ret = gst_app_src_push_buffer(GST_APP_SRC(g_appsrc), buffer);
    if (ret != GST_FLOW_OK) {
        g_printerr("Failed to push buffer to appsrc: %d\n", ret);
    }
}

// 初始化海康相机 (USB 枚举方式)
bool InitHikCamera()
{
    // MV_CC_EnumDevices：枚举当前连接到主机的所有海康设备，同时扫描 GigE 网口和 USB 接口
    MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, &g_stDeviceList);
    if (g_stDeviceList.nDeviceNum == 0) {
        std::cerr << "No Hik camera found!" << std::endl;
        return false;
    }

    // 选择第一个设备 (可根据序列号或型号选择)
    MV_CC_DEVICE_INFO *pDevice = g_stDeviceList.pDeviceInfo[0];
    int nRet = MV_CC_CreateHandle(&g_hCamera, pDevice);
    if (nRet != MV_OK) {
        std::cerr << "Create handle failed! Error: 0x" << std::hex << nRet << std::endl;
        return false;
    }

    nRet = MV_CC_OpenDevice(g_hCamera);
    if (nRet != MV_OK) {
        std::cerr << "Open device failed!" << std::endl;
        return false;
    }

    // 设置触发模式为连续采集
    WarnCameraSetFailed("TriggerMode", MV_CC_SetEnumValue(g_hCamera, "TriggerMode", MV_TRIGGER_MODE_OFF));
    // 设置图像格式 (例如 BGR8)，根据实际相机支持选择
    WarnCameraSetFailed("PixelFormat", MV_CC_SetPixelFormat(g_hCamera, PixelType_Gvsp_BGR8_Packed));
    // 配置图像质量（帧率、曝光、增益等）
    ConfigureCameraImageQuality();

    // 注册回调函数
    nRet = MV_CC_RegisterImageCallBackEx(g_hCamera, ImageCallBack, nullptr);
    if (nRet != MV_OK) {
        std::cerr << "Register callback failed!" << std::endl;
        return false;
    }

    // 开始取流
    // 让相机真正开始工作：连续采集图像并不断触发 ImageCallBack
    nRet = MV_CC_StartGrabbing(g_hCamera);
    if (nRet != MV_OK) {
        std::cerr << "Start grabbing failed!" << std::endl;
        return false;
    }

    return true;
}

// 释放海康相机资源
void DeinitHikCamera()
{
    if (g_hCamera) {
        MV_CC_StopGrabbing(g_hCamera);
        MV_CC_CloseDevice(g_hCamera);
        MV_CC_DestroyHandle(g_hCamera);
        g_hCamera = nullptr;
    }
}

// 验证模型文件是否存在
// 检查 3 个模型文件是否存在 + 是否不是空文件
static bool VerifyModelFiles()
{
    const char *model_dir = "/home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model";
    const char *files[] = {
        "fd_lpd.onnx",
        "fd_lpd.onnx_b1_gpu0_fp16.engine",
        "labels.txt"
    };

    // 一个系统结构体，用来保存文件信息
    struct stat st;
    for (const char *fname : files) {
        char path[512];
        snprintf(path, sizeof(path), "%s/%s", model_dir, fname);
        if (stat(path, &st) != 0) {
            std::cerr << "ERROR: Model file not found: " << path << std::endl;
            return false;
        }
        // 文件大小（字节数）为0通常表示文件损坏或未正确生成
        if (st.st_size == 0) {
            std::cerr << "ERROR: Model file is empty: " << path << std::endl;
            return false;
        }
        std::cout << "OK: " << path << " (" << st.st_size << " bytes)" << std::endl;
    }
    return true;
}

// ai组装的实际代码
static GstPadProbeReturn RedactionOsdSinkPadProbe(
            GstPad *pad,                // 挂载探针的 Pad（数据流出口）                                        
            GstPadProbeInfo *info,      // 探针信息，包含当前流过的数据
            gpointer user_data)         // 用户自定义数据（这里未使用）
{
    (void)pad;
    (void)user_data;

    // 从探针信息中提取 GstBuffer 指针
    GstBuffer *buf = static_cast<GstBuffer *>(info->data);
    if (!buf) {
        return GST_PAD_PROBE_OK;
    }

    // NvDsBatchMeta 是 DeepStream 的核心数据结构，存放着一帧或多帧图像中所有推理结果。
    NvDsBatchMeta *batch_meta = gst_buffer_get_nvds_batch_meta(buf);
    if (!batch_meta) {
        return GST_PAD_PROBE_OK;
    }

    guint object_count = 0;                 //本帧检测到的总目标数
    guint class_count[4] = {0, 0, 0, 0};    //每个类别（0=人脸, 1=车牌, 2=车辆品牌, 3=车辆型号）的计数。
    // 每个类别的最小/最大置信度，初始化为极大/极小值方便后续比较
    float min_conf[4] = {1.0e9f, 1.0e9f, 1.0e9f, 1.0e9f};
    float max_conf[4] = {-1.0e9f, -1.0e9f, -1.0e9f, -1.0e9f};
    static guint frame_count = 0;

    //遍历每一帧的元数据
    for (NvDsMetaList *l_frame = batch_meta->frame_meta_list; l_frame != nullptr; l_frame = l_frame->next) {
        NvDsFrameMeta *frame_meta = static_cast<NvDsFrameMeta *>(l_frame->data);
        if (!frame_meta) {
            continue;
        }

        // 遍历这一帧里的所有目标
        for (NvDsMetaList *l_obj = frame_meta->obj_meta_list; l_obj != nullptr; l_obj = l_obj->next) {
            // 一个目标的所有信息
            NvDsObjectMeta *obj_meta = static_cast<NvDsObjectMeta *>(l_obj->data);
            if (!obj_meta) {
                continue;
            }

            ++object_count;
            const int class_id = static_cast<int>(obj_meta->class_id);
            if (class_id >= 0 && class_id < 4) {
                ++class_count[class_id];
                min_conf[class_id] = std::min(min_conf[class_id], obj_meta->confidence);
                max_conf[class_id] = std::max(max_conf[class_id], obj_meta->confidence);
            }

            NvOSD_RectParams *rect_params = &(obj_meta->rect_params);
            NvOSD_TextParams *text_params = &(obj_meta->text_params);

            // 不显示文字标签（类别名、置信度）
            text_params->set_bg_clr = 0;
            text_params->font_params.font_size = 0;

            // 不显示边框，改为用背景色填充整个检测区域
            rect_params->border_width = 0;
            rect_params->has_bg_color = 1;
            rect_params->bg_color.alpha = 1.0;

            // 根据类别设置覆盖颜色
            if (obj_meta->class_id == 0) {
                rect_params->bg_color.red = 0.92;
                rect_params->bg_color.green = 0.75;
                rect_params->bg_color.blue = 0.56;
            } else {
                rect_params->bg_color.red = 0.0;
                rect_params->bg_color.green = 0.0;
                rect_params->bg_color.blue = 0.0;
            }
        }
    }

    if (++frame_count % 300 == 0) {
        // 人脸置信度
        const float face_min = class_count[0] ? min_conf[0] : 0.0f;     
        const float face_max = class_count[0] ? max_conf[0] : 0.0f;
        // 车牌置信度
        const float plate_min = class_count[1] ? min_conf[1] : 0.0f;
        const float plate_max = class_count[1] ? max_conf[1] : 0.0f;
        g_print("Redaction OSD: total=%u face=%u plate=%u make=%u model=%u "
                "face_conf=%.3f..%.3f plate_conf=%.3f..%.3f\n",
                object_count, class_count[0], class_count[1],
                class_count[2], class_count[3],
                face_min, face_max, plate_min, plate_max);
    }

    return GST_PAD_PROBE_OK;
}

// GStreamer 总线消息处理

// bus：GStreamer 管道的消息总线（Bus），所有管道事件都会发送到这个总线上。

// msg：当前收到的消息，包含消息类型和具体内容。

// data：用户自定义数据，这里未使用。

// 返回值 gboolean：TRUE 表示消息已被处理，不需要继续传递。
static gboolean bus_call(GstBus *bus, GstMessage *msg, gpointer data)
{
    switch (GST_MESSAGE_TYPE(msg)) {
        case GST_MESSAGE_EOS:
            g_print("End of stream\n");
            g_main_loop_quit(g_loop);
            break;
        case GST_MESSAGE_ERROR: {
            // 可选的调试信息（通常是内部组件的详细错误源）
            gchar *debug;
            // 包含错误描述的结构体
            GError *error;          
            gst_message_parse_error(msg, &error, &debug);
            g_printerr("GStreamer Error: %s\n", error->message);
            if (debug) g_printerr("Debug info: %s\n", debug);
            g_error_free(error);
            g_free(debug);
            g_main_loop_quit(g_loop);
            break;
        }
        default:
            break;
    }
    return TRUE;
}

// 构建 DeepStream 管道 (使用 appsrc 作为输入)
bool BuildDeepStreamPipeline()
{
    // 管道描述：appsrc → 解码/转换 → redaction 处理 → 显示/输出
    // 整个流水线的施工图纸
    const gchar *pipeline_str =
        "appsrc name=mysource format=time is-live=true do-timestamp=true ! "
        "queue max-size-buffers=3 leaky=downstream ! "
        "videoconvert ! video/x-raw,format=RGBA ! "
        "nvvideoconvert ! video/x-raw(memory:NVMM),format=NV12 ! "
        "mux.sink_0 "
        "nvstreammux name=mux batch-size=1 width=1440 height=1080 live-source=1 "
        "batched-push-timeout=40000 ! "
        "queue max-size-buffers=3 ! "
        "nvinfer config-file-path=/home/nvidia/Desktop/opencv/26.05.23/configs/pgie_config_fd_lpd.txt ! "
        "queue max-size-buffers=3 ! "
        "nvtracker ll-lib-file=/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so ! "
        "queue max-size-buffers=3 ! "
        "nvmultistreamtiler rows=1 columns=1 width=1280 height=720 ! "
        "nvvideoconvert ! video/x-raw(memory:NVMM),format=RGBA ! "
        "nvdsosd name=redaction-osd display-text=0 ! "
        "nveglglessink sync=0";

    GError *parse_error = nullptr;
    // 根据上述“施工图纸”创建完整的 GStreamer 管道对象
    g_pipeline = gst_parse_launch(pipeline_str, &parse_error);
    if (parse_error) {
        g_printerr("Pipeline parse warning/error: %s\n", parse_error->message);
        g_error_free(parse_error);
    }
    if (!g_pipeline) {
        g_printerr("Failed to create pipeline\n");
        return false;
    }

    // 获取 appsrc 元素
    g_appsrc = gst_bin_get_by_name(GST_BIN(g_pipeline), "mysource");
    if (!g_appsrc) {
        g_printerr("Failed to get appsrc element\n");
        return false;
    }

    //  在 OSD 元件上安装探针（Probe）
    GstElement *osd = gst_bin_get_by_name(GST_BIN(g_pipeline), "redaction-osd");
    if (!osd) {
        g_printerr("Failed to get redaction OSD element\n");
        return false;
    }

    GstPad *osd_sink_pad = gst_element_get_static_pad(osd, "sink");
    if (!osd_sink_pad) {
        g_printerr("Failed to get redaction OSD sink pad\n");
        gst_object_unref(osd);
        return false;
    }
    gst_pad_add_probe(osd_sink_pad, GST_PAD_PROBE_TYPE_BUFFER,
                      RedactionOsdSinkPadProbe, nullptr, nullptr);
    gst_object_unref(osd_sink_pad);
    gst_object_unref(osd);

    // 设置 appsrc 的 caps：根据相机输出格式设定
    // 设置投料口的媒体格式（Caps）
    GstCaps *caps = gst_caps_new_simple("video/x-raw",
        "format", G_TYPE_STRING, "BGR",
        "width", G_TYPE_INT, kCameraWidth,
        "height", G_TYPE_INT, kCameraHeight,
        "framerate", GST_TYPE_FRACTION, kCameraFps, 1,
        NULL);
    g_object_set(G_OBJECT(g_appsrc),
        "caps", caps,
        "block", FALSE,
        "max-bytes", static_cast<guint64>(kCameraWidth * kCameraHeight * 3 * 2),
        NULL);
    gst_caps_unref(caps);

    // 设置总线监听
    GstBus *bus = gst_pipeline_get_bus(GST_PIPELINE(g_pipeline));
    gst_bus_add_watch(bus, bus_call, nullptr);
    gst_object_unref(bus);

    return true;
}

// 信号处理，用于优雅退出
// 当用户在终端按下 Ctrl+C，操作系统会向程序发送 SIGINT 信号
static void sigint_handler(int sig)
{
    g_main_loop_quit(g_loop);
}

int main(int argc, char *argv[])
{
    // 初始化 GStreamer
    gst_init(&argc, &argv);

    // 验证模型文件
    std::cout << "Verifying model files..." << std::endl;
    if (!VerifyModelFiles()) {
        std::cerr << "Model file verification failed. Please check the file paths." << std::endl;
        return -1;
    }

    // 构建管道
    if (!BuildDeepStreamPipeline()) {
        return -1;
    }

    // 运行主循环
    // 创建主循环并注册中断信号
    g_loop = g_main_loop_new(NULL, FALSE);
    signal(SIGINT, sigint_handler);

    // 先启动管道，再初始化相机（避免回调推流时管道未就绪）
    gst_element_set_state(g_pipeline, GST_STATE_PLAYING);
    g_print("Pipeline started, press Ctrl+C to exit.\n");

    // 初始化海康相机（回调开始推流）
    if (!InitHikCamera()) {
        gst_element_set_state(g_pipeline, GST_STATE_NULL);
        gst_object_unref(g_pipeline);
        g_main_loop_unref(g_loop);
        return -1;
    }

    g_main_loop_run(g_loop);

    // 清理资源
    gst_element_set_state(g_pipeline, GST_STATE_NULL);
    DeinitHikCamera();
    gst_object_unref(g_pipeline);
    g_main_loop_unref(g_loop);

    return 0;
}
