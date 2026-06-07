# Jetson DeepStream 人脸/车牌遮蔽项目说明

本文档用于记录当前项目的代码结构、运行方式、关键文件作用、调试过程中遇到的问题，以及对应解决办法。

当前项目基于 NVIDIA 开源示例 [redaction_with_deepstream](https://github.com/NVIDIA-AI-IOT/redaction_with_deepstream) 改造。原始项目使用 Caffe 模型进行人脸和车牌检测，并通过 DeepStream 的 `nvdsosd` 将检测框绘制成实心色块，从而达到遮蔽效果。本项目在 Jetson 上使用海康相机作为输入，并将原 Caffe 模型转换为 ONNX，再由 TensorRT 生成 engine 后运行。

## 当前目标

本项目的目标是：

1. 从海康工业相机实时采集图像。
2. 将图像送入 DeepStream GStreamer 管道。
3. 使用 NVIDIA 开源的人脸/车牌检测模型进行推理。
4. 将检测到的人脸和车牌区域遮蔽。
5. 在 Jetson 上实时显示处理结果。

当前状态：

1. 相机图像可以正常采集。
2. ONNX 模型和 TensorRT engine 可以正常加载。
3. 自定义 parser 可以正常解析模型输出。
4. `nvdsosd` 已经接入，能够实现人脸遮蔽效果。
5. 识别精度仍受原始示例模型能力限制，后续可通过调参或换模型继续提升。

## 项目路径要求

Jetson 上项目路径要求为：

```bash
/home/nvidia/Desktop/opencv/26.05.23
```

代码和配置里大量路径都指向该目录，尤其是 `configs/pgie_config_fd_lpd.txt` 里的模型路径、engine 路径、自定义 parser 动态库路径。

当前目录结构应类似：

```text
/home/nvidia/Desktop/opencv/26.05.23/
├── configs/
│   └── pgie_config_fd_lpd.txt
├── fd_lpd_model/
│   ├── fd_lpd.caffemodel
│   ├── fd_lpd.prototxt
│   ├── fd_lpd.onnx
│   ├── fd_lpd.onnx_b1_gpu0_fp16.engine
│   └── labels.txt
├── build/
│   ├── show
│   ├── libnvdsinfer_custom_fd_lpd.so
│   └── pgie_config_fd_lpd.txt
├── main.cpp
├── nvdsinfer_custom_fd_lpd.cpp
├── caffe2onnx.py
├── build_engine.sh
├── CMakeLists.txt
└── README.md
```

注意：

1. `fd_lpd_model` 是模型目录，里面的文件名要和配置文件一致。
2. `configs/pgie_config_fd_lpd.txt` 必须存在，并且路径要和 `main.cpp` 里的 `nvinfer config-file-path` 对应。
3. `build/libnvdsinfer_custom_fd_lpd.so` 是本项目编译出来的自定义 parser 库，`pgie_config_fd_lpd.txt` 必须指向它。
4. `.claude` 和临时日志文件不是运行必需内容。

## 一键运行流程

首次部署到 Jetson 后，推荐按下面顺序执行。

### 1. 进入项目目录

```bash
cd /home/nvidia/Desktop/opencv/26.05.23
```

### 2. 如 ONNX 不存在，先转换模型

如果 `fd_lpd_model/fd_lpd.onnx` 已经存在，可以跳过此步。

```bash
python3 caffe2onnx.py
```

该脚本会读取：

```text
fd_lpd_model/fd_lpd.prototxt
fd_lpd_model/fd_lpd.caffemodel
```

并输出：

```text
fd_lpd_model/fd_lpd.onnx
```

### 3. 构建 TensorRT engine

```bash
chmod +x build_engine.sh
./build_engine.sh
```

输出文件：

```text
fd_lpd_model/fd_lpd.onnx_b1_gpu0_fp16.engine
```

说明：

不要依赖 `./show` 运行时自动构建 engine。Jetson 在实时相机输入、DeepStream 管道运行、TensorRT 构建同时进行时，容易出现 `NvMapMemAlloc` 内存错误。应先用 `build_engine.sh` 单独构建 engine，再运行主程序。

### 4. 编译项目

```bash
mkdir -p build
cd build
cmake ..
make -j$(nproc)
```

编译完成后应得到：

```text
build/show
build/libnvdsinfer_custom_fd_lpd.so
```

### 5. 运行

```bash
cd /home/nvidia/Desktop/opencv/26.05.23/build
./show
```

正常情况下会看到类似日志：

```text
Verifying model files...
OK: /home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/fd_lpd.onnx
OK: /home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/fd_lpd.onnx_b1_gpu0_fp16.engine
OK: /home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/labels.txt

Load new model ... successfully
Pipeline started, press Ctrl+C to exit.
First frame received: 1440x1080
FD_LPD parser received 2 output layer(s)
Redaction OSD: total=... face=... plate=...
```

如果 `Redaction OSD` 中 `face` 大于 0，说明 DeepStream 已经检测到人脸并进入遮蔽逻辑。

## 整体数据流程

项目运行时的数据流如下：

```text
海康相机
  ↓
ImageCallBack
  ↓
GStreamer appsrc
  ↓
videoconvert / nvvideoconvert
  ↓
nvstreammux
  ↓
nvinfer
  ↓
自定义 parser: NvDsInferParseCustomResnet
  ↓
DeepStream object metadata
  ↓
nvtracker
  ↓
nvmultistreamtiler
  ↓
nvdsosd + RedactionOsdSinkPadProbe
  ↓
nveglglessink 显示
```

关键点：

1. `nvinfer` 只负责推理，不负责遮蔽。
2. 自定义 parser 负责把模型输出转换成 DeepStream 检测框。
3. `nvdsosd` 前的 pad probe 负责把检测框画成实心遮挡块。
4. 如果没有 `nvdsosd` 和 pad probe，即使模型检测成功，也不会出现遮蔽效果。

## 文件作用详解

### main.cpp

`main.cpp` 是主程序，负责相机采集、GStreamer 管道创建、DeepStream 推理和遮蔽显示。

主要功能包括：

1. 初始化 GStreamer。
2. 检查模型文件和 engine 文件是否存在。
3. 构建 DeepStream 管道。
4. 初始化海康相机。
5. 将相机图像推入 `appsrc`。
6. 在 `nvdsosd` 前读取检测框 metadata。
7. 将检测到的人脸/车牌区域改成实心色块。
8. 运行主循环并显示结果。

#### 全局变量

```cpp
void* g_hCamera = nullptr;
MV_CC_DEVICE_INFO_LIST g_stDeviceList = {0};
GstElement* g_pipeline = nullptr;
GstElement* g_appsrc = nullptr;
GMainLoop* g_loop = nullptr;
```

作用：

1. `g_hCamera` 保存海康相机句柄。
2. `g_stDeviceList` 保存枚举到的相机设备列表。
3. `g_pipeline` 保存 GStreamer pipeline。
4. `g_appsrc` 是自定义输入源，海康相机数据通过它进入 DeepStream。
5. `g_loop` 是 GStreamer 主循环。

#### 相机参数

```cpp
static constexpr int kCameraWidth = 1440;
static constexpr int kCameraHeight = 1080;
static constexpr int kCameraFps = 15;
```

作用：

1. 固定当前相机输入分辨率为 `1440x1080`。
2. 将实际推流帧率限制为 `15fps`。
3. 减轻 Jetson 上 `nvvideoconvert`、`nvinfer`、`nvdsosd` 的压力。

之前日志里出现过 `6900 frames / 90s`，实际接近 77fps，远高于配置中声明的 30fps，容易导致长时间运行后 GPU 处理压力和缓存压力过大。因此加入了相机帧率设置和回调节流。

#### ConfigureCameraImageQuality

```cpp
static void ConfigureCameraImageQuality()
```

作用：

1. 设置相机采集帧率。
2. 关闭自动曝光。
3. 手动设置曝光时间。
4. 关闭自动增益。
5. 设置增益。
6. 开启 Gamma。
7. 设置白平衡自动模式。

当前主要参数：

```text
AcquisitionFrameRate = 15
ExposureAuto = Off
ExposureTime = 20000 us
Gain = 8
Gamma = 0.70
BalanceWhiteAuto = Continuous
```

为什么要这样做：

之前画面中窗外能看清，但人是黑的。这通常是相机自动曝光被窗外强光影响，导致室内主体曝光不足。手动提高曝光和增益后，可以让室内人脸更容易被模型检测到。

如果画面仍然偏暗，可以尝试：

```text
ExposureTime: 20000 -> 30000
Gain: 8 -> 12 或 16
Gamma: 0.70 -> 0.60 或 0.50
```

如果运动拖影明显，则降低 `ExposureTime`，适当提高 `Gain`。

#### ImageCallBack

```cpp
static void __stdcall ImageCallBack(...)
```

作用：

1. 接收海康相机 SDK 回调传来的图像数据。
2. 将图像复制到 `GstBuffer`。
3. 设置 `PTS` 和 `duration`。
4. 推入 `appsrc`。

关键修正：

1. 增加 `g_appsrc == nullptr` 保护，避免管道未准备好时推流。
2. 增加实际推流节流，确保最多向 DeepStream 推 `15fps`。
3. 增加 `gst_buffer_new_allocate` 和 `gst_buffer_map` 失败检查。

这些保护用于减少长时间运行中的缓冲堆积、空指针、内存压力问题。

#### InitHikCamera

```cpp
bool InitHikCamera()
```

作用：

1. 枚举 USB/GigE 海康相机。
2. 创建相机句柄。
3. 打开相机。
4. 设置连续采集模式。
5. 设置像素格式为 `BGR8_Packed`。
6. 应用曝光、增益、Gamma 等图像参数。
7. 注册图像回调。
8. 开始采集。

注意：

当前 `appsrc` caps 设置为：

```text
video/x-raw, format=BGR, width=1440, height=1080, framerate=15/1
```

因此相机输出格式必须和 `BGR` 匹配，否则颜色、亮度、通道顺序可能异常。

#### VerifyModelFiles

```cpp
static bool VerifyModelFiles()
```

作用：

程序启动前检查关键模型文件：

```text
fd_lpd_model/fd_lpd.onnx
fd_lpd_model/fd_lpd.onnx_b1_gpu0_fp16.engine
fd_lpd_model/labels.txt
```

为什么要检查 engine：

DeepStream 如果找不到 engine，可能会尝试运行时自动构建 engine。Jetson 上运行时构建容易触发内存错误，所以程序启动前强制检查 engine 文件是否存在。如果不存在，先运行 `build_engine.sh`。

#### BuildDeepStreamPipeline

```cpp
bool BuildDeepStreamPipeline()
```

作用：

使用 `gst_parse_launch` 构建完整 DeepStream 管道。

当前管道核心结构：

```text
appsrc
  ! queue
  ! videoconvert
  ! video/x-raw,format=RGBA
  ! nvvideoconvert
  ! video/x-raw(memory:NVMM),format=NV12
  ! nvstreammux
  ! nvinfer
  ! nvtracker
  ! nvmultistreamtiler
  ! nvvideoconvert
  ! video/x-raw(memory:NVMM),format=RGBA
  ! nvdsosd
  ! nveglglessink
```

各元素作用：

1. `appsrc`: 接收海康相机回调输入。
2. `queue`: 防止上下游阻塞，降低卡顿影响。
3. `videoconvert`: CPU 侧颜色格式转换。
4. `nvvideoconvert`: NVIDIA 硬件/ GPU 侧格式转换。
5. `nvstreammux`: 将输入帧封装成 DeepStream batch。
6. `nvinfer`: 调用 TensorRT engine 进行检测推理。
7. `nvtracker`: 对检测目标进行跟踪，让遮蔽框更稳定。
8. `nvmultistreamtiler`: 将画面整理成输出画布。
9. `nvdsosd`: 根据 metadata 绘制矩形、文本、背景块。
10. `nveglglessink`: Jetson 上屏幕显示。

关键新增点：

```text
nvvideoconvert ! video/x-raw(memory:NVMM),format=RGBA ! nvdsosd name=redaction-osd display-text=0
```

没有 `nvdsosd` 时，即使检测成功，画面上也不会有遮蔽效果。

#### RedactionOsdSinkPadProbe

```cpp
static GstPadProbeReturn RedactionOsdSinkPadProbe(...)
```

这是实现遮蔽效果的关键函数。

作用：

1. 从当前 `GstBuffer` 中取出 `NvDsBatchMeta`。
2. 遍历每一帧的 `NvDsFrameMeta`。
3. 遍历每个检测目标的 `NvDsObjectMeta`。
4. 读取目标框 `rect_params`。
5. 隐藏文本。
6. 将检测框设置为实心背景色。

当前规则：

```text
class_id = 0: 人脸，绘制肤色块
其他 class_id: 绘制黑色块
```

代码中设置：

```cpp
rect_params->border_width = 0;
rect_params->has_bg_color = 1;
rect_params->bg_color.alpha = 1.0;
```

这表示：

1. 不画边框。
2. 开启矩形背景填充。
3. 填充不透明。

同时日志会统计检测情况：

```text
Redaction OSD: total=... face=... plate=... make=... model=... face_conf=... plate_conf=...
```

这个日志用于判断精度问题：

1. `face=0`: 当前帧没有检测到人脸。
2. `face>0` 但画面没遮蔽: OSD 或显示链路可能有问题。
3. `face_conf` 很低: 模型对当前画面信心低，可能需要调曝光、阈值或换模型。

### nvdsinfer_custom_fd_lpd.cpp

该文件编译成：

```text
build/libnvdsinfer_custom_fd_lpd.so
```

这是 DeepStream `nvinfer` 使用的自定义 bbox parser。

为什么需要它：

模型输出不是标准 YOLO/SSD 格式，DeepStream 默认 parser 不知道如何把输出 tensor 转换成检测框。因此必须提供自定义解析函数。

配置文件中指定：

```ini
parse-bbox-func-name=NvDsInferParseCustomResnet
custom-lib-path=/home/nvidia/Desktop/opencv/26.05.23/build/libnvdsinfer_custom_fd_lpd.so
```

#### dims_to_chw

作用：

将 DeepStream 输出 tensor 的 `NvDsInferDims` 转成 `C x H x W` 形式。

模型输出包括：

```text
conv2d_bbox: 16 x 17 x 30
conv2d_cov/Sigmoid: 4 x 17 x 30
```

含义：

1. `conv2d_bbox`: bbox 回归输出。
2. `conv2d_cov/Sigmoid`: 分类置信度输出。
3. 4 个类别分别是 face、license_plate、make、model。

#### dump_output_layers

作用：

第一次运行 parser 时打印模型输出层名字和维度。

正常日志：

```text
FD_LPD parser received 2 output layer(s)
  [0] conv2d_bbox dims.numDims=3 chw=16x17x30
  [1] conv2d_cov/Sigmoid dims.numDims=3 chw=4x17x30
```

这条日志很重要。如果输出名或维度不对，说明 ONNX 转换或配置文件还存在问题。

#### find_layer_exact / find_layer_by_dims

作用：

查找 bbox 输出层和 confidence 输出层。

优先按名字找：

```text
conv2d_bbox
conv2d_cov/Sigmoid
```

也兼容旧名字：

```text
output_bbox
output_cov
```

如果名字不匹配，则根据输出通道数兜底查找：

1. bbox 输出通道数为 `num_classes * 4`，当前是 `4 * 4 = 16`。
2. confidence 输出通道数为 `num_classes`，当前是 `4`。

这样可以减少因为 ONNX 输出名变化导致 parser 完全失效的概率。

#### NvDsInferParseCustomResnet

这是 DeepStream 会调用的核心 parser 函数。

作用：

1. 找到 bbox 和 confidence 输出层。
2. 根据网格大小计算每个 cell 的中心点。
3. 读取每个类别、每个网格位置的置信度。
4. 根据阈值过滤低置信度目标。
5. 将 bbox 回归值转换为 `left/top/width/height`。
6. 过滤异常框。
7. 将结果写入 `objectList`，供 DeepStream 后续 tracker 和 OSD 使用。

关键安全处理：

1. 跳过 `NaN/Inf` 置信度。
2. 跳过 `NaN/Inf` 坐标。
3. 将坐标裁剪到网络输入范围。
4. 跳过反向框，例如 `right <= left` 或 `bottom <= top`。

这些处理用于降低运行中出现 `cudaErrorIllegalAddress`、tracker 异常或 OSD 绘制异常的概率。

### configs/pgie_config_fd_lpd.txt

这是 DeepStream `nvinfer` 的配置文件。

关键配置：

```ini
onnx-file=/home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/fd_lpd.onnx
model-engine-file=/home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/fd_lpd.onnx_b1_gpu0_fp16.engine
labelfile-path=/home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/labels.txt
network-mode=2
num-detected-classes=4
output-blob-names=conv2d_bbox;conv2d_cov/Sigmoid
parse-bbox-func-name=NvDsInferParseCustomResnet
custom-lib-path=/home/nvidia/Desktop/opencv/26.05.23/build/libnvdsinfer_custom_fd_lpd.so
cluster-mode=2
```

说明：

1. `onnx-file`: ONNX 模型路径。
2. `model-engine-file`: TensorRT engine 路径。
3. `labelfile-path`: 类别标签文件。
4. `network-mode=2`: FP16 推理。
5. `num-detected-classes=4`: 模型输出 4 类。
6. `output-blob-names`: 必须和 ONNX 输出层名一致。
7. `parse-bbox-func-name`: 自定义 parser 函数名。
8. `custom-lib-path`: 自定义 parser 动态库路径。
9. `cluster-mode=2`: 使用 NMS 聚类。

阈值配置：

```ini
[class-attrs-all]
pre-cluster-threshold=0.2
topk=20
nms-iou-threshold=0.5
```

调参建议：

1. 漏检多: 可以尝试 `pre-cluster-threshold=0.15`。
2. 误检多: 可以尝试 `pre-cluster-threshold=0.3` 或 `0.4`。
3. 框重叠严重: 可以调 `nms-iou-threshold`。
4. 检测太多导致遮蔽错乱: 可以降低 `topk` 或提高阈值。

当前只关心类别 0 和 1：

```text
class 0: face
class 1: license_plate
```

类别 2 和 3 设置了较高阈值：

```ini
[class-attrs-2]
pre-cluster-threshold=1.2

[class-attrs-3]
pre-cluster-threshold=1.2
```

这样可以基本过滤掉 make/model 两类，避免它们参与遮蔽。

### caffe2onnx.py

该脚本用于将原始 Caffe 模型转换为 ONNX。

输入：

```text
fd_lpd_model/fd_lpd.prototxt
fd_lpd_model/fd_lpd.caffemodel
```

输出：

```text
fd_lpd_model/fd_lpd.onnx
```

为什么需要它：

Jetson 当前环境中的 TensorRT 版本为 10.7，`trtexec --help` 中只显示支持 `--onnx`，不再支持旧 Caffe 参数：

```text
--deploy
--model
```

因此原始 Caffe 模型不能直接用 TensorRT 10.7 构建 engine，需要先转换为 ONNX。

关键修正：

脚本中将原始输出名映射为 parser 需要的名字：

```python
parser_output_names = {
    'output_bbox': 'conv2d_bbox',
    'output_cov': 'conv2d_cov/Sigmoid',
}
```

这样生成的 ONNX 输出为：

```text
conv2d_bbox: [1, 16, 17, 30]
conv2d_cov/Sigmoid: [1, 4, 17, 30]
```

该命名必须和 `pgie_config_fd_lpd.txt` 中的：

```ini
output-blob-names=conv2d_bbox;conv2d_cov/Sigmoid
```

保持一致。

### build_engine.sh

该脚本用于提前生成 TensorRT engine。

核心命令：

```bash
/usr/src/tensorrt/bin/trtexec \
    --onnx="${ONNX_FILE}" \
    --saveEngine="${ENGINE_FILE}" \
    --fp16
```

输入：

```text
fd_lpd_model/fd_lpd.onnx
```

输出：

```text
fd_lpd_model/fd_lpd.onnx_b1_gpu0_fp16.engine
```

为什么单独写脚本：

1. 避免 DeepStream 运行时自动构建 engine。
2. 避免相机实时推流和 TensorRT 构建同时抢内存。
3. 便于确认 ONNX 是否能被 TensorRT 正常解析。
4. 构建成功后，`./show` 可以直接反序列化 engine，启动更快、更稳定。

### CMakeLists.txt

该文件负责构建整个项目。

构建目标：

```text
show
libnvdsinfer_custom_fd_lpd.so
```

主要依赖：

1. GStreamer。
2. GStreamer appsrc。
3. CUDA。
4. DeepStream。
5. 海康 MVS SDK。

关键路径：

```cmake
set(DEEPSTREAM_PATH "/opt/nvidia/deepstream/deepstream-7.1")
set(MVS_PATH "/opt/MVS")
```

如果 `/opt/nvidia/deepstream/deepstream-7.1` 不存在，CMake 会尝试查找 `/opt/nvidia/deepstream/deepstream-*`。

主程序链接库包括：

```text
nvdsgst_meta
nvds_meta
nvdsgst_helper
nvds_utils
MvCameraControl
pthread
dl
```

自定义 parser 链接：

```text
nvds_infer
```

### fd_lpd_model 目录

该目录保存模型相关文件。

```text
fd_lpd.caffemodel
fd_lpd.prototxt
fd_lpd.onnx
fd_lpd.onnx_b1_gpu0_fp16.engine
labels.txt
```

说明：

1. `fd_lpd.caffemodel`: 原始 Caffe 权重。
2. `fd_lpd.prototxt`: 原始 Caffe 网络结构。
3. `fd_lpd.onnx`: 转换后的 ONNX 模型。
4. `fd_lpd.onnx_b1_gpu0_fp16.engine`: TensorRT engine。
5. `labels.txt`: 类别标签。

运行时真正使用的是：

```text
fd_lpd.onnx_b1_gpu0_fp16.engine
labels.txt
```

`fd_lpd.onnx` 用于构建 engine，`caffemodel/prototxt` 用于重新转换 ONNX。

## 调试过程中遇到的问题和解决办法

### 问题 1: 原始 Caffe 模型不能直接构建 TensorRT engine

现象：

使用类似命令：

```bash
/usr/src/tensorrt/bin/trtexec \
  --deploy=fd_lpd.prototxt \
  --model=fd_lpd.caffemodel
```

无法正常使用。

排查：

在 Jetson 上执行：

```bash
/usr/src/tensorrt/bin/trtexec --help | grep -Ei "deploy|model|caffe|onnx"
```

发现 TensorRT 10.7 的 `trtexec` 只显示 ONNX 相关参数，不再显示 Caffe 的 `--deploy` 和 `--model`。

原因：

当前 Jetson 环境使用 TensorRT 10.7，旧 Caffe parser 支持已经不可用。

解决：

编写并使用 `caffe2onnx.py` 将 Caffe 模型转换为 ONNX，然后使用 ONNX 构建 TensorRT engine。

### 问题 2: DeepStream 报找不到 `libnvdsparsebbox.so`

现象：

日志中出现：

```text
ERROR: Could not open lib: /opt/nvidia/deepstream/deepstream-7.1/lib/libnvdsparsebbox.so
NvDsInfer Error: NVDSINFER_CUSTOM_LIB_FAILED
```

原因：

原始配置或旧代码中依赖了旧版本 DeepStream 的 custom bbox parser 动态库，但 DeepStream 7.1 环境中该库不存在。

解决：

不再依赖 `libnvdsparsebbox.so`，改为本项目自己编译：

```text
build/libnvdsinfer_custom_fd_lpd.so
```

并在配置文件中设置：

```ini
custom-lib-path=/home/nvidia/Desktop/opencv/26.05.23/build/libnvdsinfer_custom_fd_lpd.so
parse-bbox-func-name=NvDsInferParseCustomResnet
```

### 问题 3: 模型输出层名称和 parser 不匹配

现象：

模型能加载，但 parser 找不到 bbox 或 confidence 输出层。

原因：

原始 Caffe 或转换后的 ONNX 输出名可能是：

```text
output_bbox
output_cov
```

而 NVIDIA parser 或当前配置期望：

```text
conv2d_bbox
conv2d_cov/Sigmoid
```

解决：

在 `caffe2onnx.py` 中统一输出层命名，并在 `pgie_config_fd_lpd.txt` 中同步：

```ini
output-blob-names=conv2d_bbox;conv2d_cov/Sigmoid
```

同时在 `nvdsinfer_custom_fd_lpd.cpp` 中做了兼容，既能按新名字找，也能按旧名字找，还能按 tensor 维度兜底查找。

### 问题 4: 自动构建 engine 时出现内存错误

现象：

日志中出现大量：

```text
NvMapMemAllocInternalTagged error 12
NvMapMemHandleAlloc error 0
```

或者 DeepStream 运行时尝试自动构建 engine。

原因：

在 Jetson 上运行 `./show` 时，相机采集、GStreamer 管道、DeepStream 推理、TensorRT engine 构建同时进行，容易导致内存压力过大。

解决：

新增 `build_engine.sh`，先单独运行：

```bash
./build_engine.sh
```

生成 engine 后再运行：

```bash
cd build
./show
```

同时 `main.cpp` 中 `VerifyModelFiles` 会检查 engine 是否存在，避免运行时自动构建。

### 问题 5: 图像很黑，人脸不可见

现象：

相机图像能采集，窗户外面能看清，但室内的人基本是黑的。

原因：

相机自动曝光被窗外强光影响，导致室内主体曝光不足。模型看到的人脸区域太暗，识别精度会明显下降。

解决：

在 `main.cpp` 中增加 `ConfigureCameraImageQuality`：

1. 关闭自动曝光。
2. 手动设置曝光时间。
3. 设置增益。
4. 开启 Gamma。
5. 限制帧率。

当前参数：

```text
ExposureTime = 20000
Gain = 8
Gamma = 0.70
```

如果仍偏暗，可继续提高曝光或增益。

### 问题 6: 运行一段时间后出现 `cudaErrorIllegalAddress`

现象：

程序运行一段时间后报错：

```text
cudaErrorIllegalAddress
Preprocessor transform input data failed
Failed to queue input batch for inferencing
```

可能原因：

1. 相机实际推流帧率过高，超过 DeepStream 管道处理能力。
2. parser 产生了异常 bbox，例如 NaN、Inf、反向框。
3. tracker 或 OSD 收到非法框后触发后续 GPU 错误。

解决：

1. 将相机推流限制为 `15fps`。
2. 在 `ImageCallBack` 中做时间节流。
3. 在 parser 中过滤 NaN、Inf、反向框、非法框。
4. appsrc 设置 `max-bytes`，减少缓存堆积。

### 问题 7: 模型可以运行，但没有任何遮蔽效果

现象：

模型成功加载，parser 也打印了输出层信息，但画面没有遮蔽块。

原因：

`nvinfer` 只负责检测，它不会自动遮蔽人脸。NVIDIA 原始 redaction 示例是在 `nvdsosd` 的 sink pad 上读取检测框 metadata，然后修改 `rect_params`，把目标框画成实心色块。

解决：

在管道中加入：

```text
nvdsosd name=redaction-osd display-text=0
```

并添加：

```cpp
RedactionOsdSinkPadProbe
```

该函数将检测框设置为实心填充：

```cpp
rect_params->has_bg_color = 1;
rect_params->bg_color.alpha = 1.0;
```

现在检测到的人脸可以被遮蔽。

### 问题 8: 识别精度不高

现象：

遮蔽功能已经有效，但检测人脸的稳定性和准确率不高。

原因：

1. NVIDIA 原始项目说明该模型是示例网络，训练数据有限。
2. 该模型并不是高精度生产级人脸检测模型。
3. 光照、角度、距离、模糊、曝光都会影响检测效果。
4. Caffe 转 ONNX 后虽然输出正常，但模型能力上限不会提高。

当前改进：

1. 改善相机曝光和 Gamma。
2. 加入 detection confidence 日志。
3. 保留阈值可调入口。

后续如果误检多：

```ini
pre-cluster-threshold=0.2 -> 0.3 或 0.4
```

如果漏检多：

```ini
pre-cluster-threshold=0.2 -> 0.15
```

如果想明显提高精度，建议换用更强的人脸检测模型，或者重新训练/微调当前模型。

## 常用排查命令

### 检查 DeepStream 路径

```bash
ls -l /opt/nvidia/deepstream/
readlink -f /opt/nvidia/deepstream/deepstream
```

### 检查 TensorRT 是否支持 Caffe

```bash
/usr/src/tensorrt/bin/trtexec --help | grep -Ei "deploy|model|caffe|onnx"
```

如果只看到 `--onnx`，说明不能直接使用 Caffe 构建 engine。

### 检查 parser 动态库是否存在

```bash
ls -l /home/nvidia/Desktop/opencv/26.05.23/build/libnvdsinfer_custom_fd_lpd.so
nm -D /home/nvidia/Desktop/opencv/26.05.23/build/libnvdsinfer_custom_fd_lpd.so | grep NvDsInferParseCustomResnet
```

应能看到：

```text
NvDsInferParseCustomResnet
```

### 检查 engine 是否存在

```bash
ls -lh /home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/*.engine
```

### 检查配置文件关键路径

```bash
grep -nE "onnx-file|model-engine-file|labelfile-path|output-blob-names|custom-lib-path|parse-bbox-func-name" \
  /home/nvidia/Desktop/opencv/26.05.23/configs/pgie_config_fd_lpd.txt
```

### 重新编译

```bash
cd /home/nvidia/Desktop/opencv/26.05.23/build
cmake ..
make -j$(nproc)
```

### 重新运行

```bash
cd /home/nvidia/Desktop/opencv/26.05.23/build
./show
```

## 关键日志如何理解

### 模型和 parser 正常

```text
Load new model ... successfully
FD_LPD parser received 2 output layer(s)
  [0] conv2d_bbox dims.numDims=3 chw=16x17x30
  [1] conv2d_cov/Sigmoid dims.numDims=3 chw=4x17x30
```

说明：

1. engine 能加载。
2. 输出层名称正确。
3. parser 能获取模型输出。

### 检测和遮蔽正常

```text
Redaction OSD: total=1 face=1 plate=0 make=0 model=0 face_conf=0.423..0.423
```

说明：

1. 当前 batch 中检测到 1 个目标。
2. 其中 1 个是人脸。
3. OSD pad probe 已经拿到 metadata。
4. 画面上应出现遮蔽块。

### 一直没有检测到人脸

```text
Redaction OSD: total=0 face=0 plate=0 make=0 model=0
```

可能原因：

1. 人脸太小。
2. 人脸太暗。
3. 人脸角度太偏。
4. 阈值太高。
5. 模型本身精度不足。
6. parser 输出框有问题。

优先处理：

1. 改善相机曝光。
2. 缩短距离。
3. 正对人脸测试。
4. 临时降低 `pre-cluster-threshold`。

## 精度调参建议

当前配置：

```ini
pre-cluster-threshold=0.2
topk=20
nms-iou-threshold=0.5
```

建议按现象调整：

| 现象 | 建议 |
| --- | --- |
| 漏检人脸 | 降低 `pre-cluster-threshold` 到 `0.15` |
| 误检太多 | 提高 `pre-cluster-threshold` 到 `0.3` 或 `0.4` |
| 同一人脸多个框 | 降低 `nms-iou-threshold` |
| 框太乱 | 提高阈值，降低 `topk` |
| 人脸太暗 | 提高曝光/增益，调整 Gamma |
| 远处人脸检测不到 | 降低相机分辨率缩放损失，或换更强模型 |

注意：

阈值不是越低越好。降低阈值会增加召回，但也会增加误检。提高阈值会减少误检，但也会增加漏检。

## 已知限制

1. 原始 NVIDIA 模型是示例模型，精度有限。
2. Caffe 转 ONNX 不会提升模型能力，只是解决 TensorRT 10.7 不支持 Caffe 的问题。
3. 当前遮蔽方式是矩形实心块，不是马赛克或模糊。
4. 当前输入尺寸固定为 `1440x1080`，如果换相机或分辨率，需要同步修改 `main.cpp` 中的 caps 和 streammux 尺寸。
5. 当前使用 `nveglglessink` 做屏幕显示，如果要保存视频，需要额外增加编码和文件输出。
6. 当前只针对 Jetson 上的 `/home/nvidia/Desktop/opencv/26.05.23` 路径配置，迁移目录时要同步修改配置文件和代码中的绝对路径。

## 后续可改进方向

### 低成本改进

1. 根据 `Redaction OSD` 日志调 `pre-cluster-threshold`。
2. 调整相机曝光、增益、Gamma。
3. 根据场景固定 ROI，只检测画面中可能出现人脸的区域。
4. 对遮蔽框做适当扩大，避免只遮住一部分脸。

### 中等成本改进

1. 将遮蔽从纯色矩形改成马赛克或模糊。
2. 增加输出视频保存功能。
3. 增加命令行参数配置相机分辨率、帧率、阈值。
4. 将绝对路径改为相对路径或配置文件路径。

### 高收益改进

1. 更换更强的人脸检测模型。
2. 用实际场景数据重新训练或微调模型。
3. 使用更现代的 ONNX 检测模型，减少对旧 Caffe 结构和 custom parser 的依赖。
4. 使用 DeepStream 原生支持更好的模型格式和 parser。

## 最终结论

本项目最初的问题不是单一 bug，而是多个兼容性问题叠加：

1. 原始模型是 Caffe，但当前 TensorRT 只支持 ONNX。
2. 原始 custom parser 路径在 DeepStream 7.1 中不匹配。
3. ONNX 输出层名字和 parser 预期不一致。
4. 运行时自动构建 engine 导致 Jetson 内存压力过大。
5. 相机自动曝光导致画面过暗。
6. 缺少 `nvdsosd` 和 pad probe，导致有检测但没有遮蔽效果。

最终解决路径是：

1. Caffe 转 ONNX。
2. 统一输出层名称。
3. 自己实现并编译 custom parser。
4. 提前构建 TensorRT engine。
5. 调整相机曝光和帧率。
6. 加入 `nvdsosd` 和 `RedactionOsdSinkPadProbe`。
7. 增加检测统计日志，方便后续调精度。

当前项目已经可以完成 Jetson 上海康相机实时输入、人脸检测、人脸遮蔽和屏幕显示。

## 附加项目: ONNX 网络架构查看器

项目中新增了一个子项目：

```text
model_arch_viewer/
```

该工具用于读取：

```text
fd_lpd_model/fd_lpd.onnx
```

并生成浏览器可打开的神经网络架构页面。

### 主要文件

```text
model_arch_viewer/
├── generate_viewer.py
├── viewer_config.json
├── requirements.txt
├── run.sh
├── run_windows.ps1
└── README.md
```

### 配置方式

修改：

```text
model_arch_viewer/viewer_config.json
```

其中：

```json
"detailed": false
```

表示主页面使用简介版。

```json
"detailed": true
```

表示主页面使用详细版。

如果：

```json
"generate_both_modes": true
```

脚本会同时生成简介版和详细版页面。

### Jetson 运行

```bash
cd /home/nvidia/Desktop/opencv/26.05.23/model_arch_viewer
chmod +x run.sh
./run.sh
```

如果缺少 `onnx` 包：

```bash
python3 -m pip install --user -r requirements.txt
./run.sh
```

### 输出文件

默认输出到：

```text
model_arch_viewer/output/
```

包含：

```text
fd_lpd_architecture.html
fd_lpd_architecture_simple.html
fd_lpd_architecture_detailed.html
fd_lpd_architecture.svg
fd_lpd_summary.md
```

其中：

1. `fd_lpd_architecture.html`: 根据 `viewer_config.json` 中的 `detailed` 选择简介版或详细版。
2. `fd_lpd_architecture_simple.html`: 简介版，适合看整体主干和两个输出头。
3. `fd_lpd_architecture_detailed.html`: 详细版，适合查看每个 ONNX 节点、op、输入输出 tensor 和 shape。
4. `fd_lpd_architecture.svg`: 架构图 SVG。
5. `fd_lpd_summary.md`: 模型结构摘要。
