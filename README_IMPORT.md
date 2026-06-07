# 项目精华文件学习指南

本文档用于回答一个核心问题：

> 当前 `26.05.23` 项目里，哪些文件最值得学习？哪些内容对计算机视觉、AI 部署、Jetson 开发、电赛实战最有帮助？

结论先说在前面：这个项目最有价值的地方，不只是“能做人脸遮蔽”，而是它包含了一条比较完整的端侧 AI 视觉工程链路：

```text
工业相机采集
  -> 图像格式转换
  -> GStreamer / DeepStream 视频流
  -> TensorRT 模型推理
  -> 自定义后处理 parser
  -> 检测框 metadata
  -> OSD 遮蔽显示
  -> Jetson 端部署和调参
```

这条链路非常适合未来打电赛。电赛中真正困难的往往不是“模型跑通一次”，而是把相机、模型、嵌入式设备、实时处理、调参、异常排查整合成一个稳定系统。

## 一、最值得学习的文件排序

### 1. main.cpp

文件位置：

```text
main.cpp
```

学习价值：最高。

这是整个项目的主程序，也是最接近电赛实战的文件。

它包含：

1. 海康工业相机初始化。
2. 相机曝光、增益、Gamma、帧率设置。
3. 相机图像回调 `ImageCallBack`。
4. 将相机图像封装成 `GstBuffer`。
5. 通过 `appsrc` 把自定义图像输入送入 GStreamer。
6. 创建 DeepStream 管道。
7. 接入 `nvinfer` 进行模型推理。
8. 接入 `nvtracker` 进行目标跟踪。
9. 接入 `nvdsosd` 进行遮蔽绘制。
10. 通过 pad probe 读取 DeepStream metadata。
11. 将检测框绘制成实心遮蔽块。

重点学习内容：

#### 1. 相机采集

`InitHikCamera()` 负责相机初始化。

你可以从这里学到：

1. 工业相机如何枚举。
2. 如何创建相机句柄。
3. 如何设置连续采集模式。
4. 如何设置像素格式。
5. 如何注册图像回调。
6. 如何开始取流。

这对电赛很重要。很多比赛项目需要接 USB 摄像头、工业相机、深度相机、热成像相机等设备。相机输入稳定，是整个视觉系统的第一步。

#### 2. 曝光和图像质量调参

`ConfigureCameraImageQuality()` 负责设置：

```text
AcquisitionFrameRate
ExposureAuto
ExposureTime
GainAuto
Gain
Gamma
BalanceWhiteAuto
```

这一段非常值得学。因为很多视觉算法效果不好，并不是模型问题，而是图像质量问题。

之前项目里出现过：

```text
窗户外面能看清，但是人整个是黑的
```

这就是典型的曝光问题：相机自动曝光被窗外强光影响，室内人脸变暗，模型自然难以检测。

电赛启发：

1. 视觉算法前，先保证图像质量。
2. 光照不稳定时，自动曝光不一定可靠。
3. 曝光、增益、Gamma 会直接影响识别率。
4. 实战中要学会用工程手段提升模型效果。

#### 3. 图像回调到 GStreamer appsrc

`ImageCallBack()` 是海康相机数据进入 AI 管道的入口。

它做了：

1. 接收相机图像指针。
2. 创建 `GstBuffer`。
3. 将相机图像复制到 buffer。
4. 设置时间戳和帧间隔。
5. 推入 `appsrc`。

这部分很有工程价值。因为很多 AI 框架示例只会读取视频文件或 RTSP，但比赛中经常要把“自己的图像源”塞进处理管道。

你要重点理解：

```cpp
gst_buffer_new_allocate
gst_buffer_map
memcpy
GST_BUFFER_PTS
GST_BUFFER_DURATION
gst_app_src_push_buffer
```

这是一条从相机 SDK 到 GStreamer 的桥。

#### 4. DeepStream 管道

`BuildDeepStreamPipeline()` 中的 pipeline 是整套 AI 视频处理链路：

```text
appsrc
  ! queue
  ! videoconvert
  ! nvvideoconvert
  ! nvstreammux
  ! nvinfer
  ! nvtracker
  ! nvmultistreamtiler
  ! nvvideoconvert
  ! nvdsosd
  ! nveglglessink
```

你要理解每个模块的作用：

| 模块 | 作用 |
| --- | --- |
| `appsrc` | 自定义图像输入源 |
| `queue` | 缓冲上下游，降低阻塞 |
| `videoconvert` | CPU 图像格式转换 |
| `nvvideoconvert` | NVIDIA 硬件/GPU 图像格式转换 |
| `nvstreammux` | 将视频帧打包成 DeepStream batch |
| `nvinfer` | 调用 TensorRT engine 进行 AI 推理 |
| `nvtracker` | 对检测目标做跟踪 |
| `nvmultistreamtiler` | 多路画面整理，这里只有一路 |
| `nvdsosd` | 绘制检测框、文字、遮蔽块 |
| `nveglglessink` | Jetson 上显示画面 |

电赛启发：

这就是边缘端 AI 视觉系统的骨架。以后换成人脸识别、目标检测、装甲板识别、缺陷检测、交通标志识别，本质上都是类似结构。

#### 5. 遮蔽逻辑

`RedactionOsdSinkPadProbe()` 是遮蔽效果真正发生的地方。

它读取 DeepStream 的检测结果：

```text
NvDsBatchMeta
NvDsFrameMeta
NvDsObjectMeta
```

然后修改：

```text
rect_params
text_params
```

将检测框变成实心色块。

这个点非常关键：

```text
nvinfer 只负责检测
nvdsosd 才负责画出来
pad probe 负责修改 metadata
```

之前模型已经能运行但没有遮蔽效果，就是因为少了 `nvdsosd + pad probe` 这一步。

电赛启发：

AI 模型输出只是系统的一部分。你还需要后处理、显示、控制、执行动作。模型本身不会自动完成业务逻辑。

### 2. nvdsinfer_custom_fd_lpd.cpp

文件位置：

```text
nvdsinfer_custom_fd_lpd.cpp
```

学习价值：非常高。

这是模型后处理 parser。很多人只会调用模型，但不会看模型输出，也不会把 tensor 转成可用检测框。这个文件就是从“会跑模型”到“懂模型部署”的关键。

它编译后生成：

```text
build/libnvdsinfer_custom_fd_lpd.so
```

DeepStream 配置中通过下面两项调用它：

```ini
parse-bbox-func-name=NvDsInferParseCustomResnet
custom-lib-path=/home/nvidia/Desktop/opencv/26.05.23/build/libnvdsinfer_custom_fd_lpd.so
```

重点学习内容：

#### 1. 模型输出不是直接的框

该模型输出：

```text
conv2d_bbox: FLOAT[1x16x17x30]
conv2d_cov/Sigmoid: FLOAT[1x4x17x30]
```

含义大致是：

1. `conv2d_bbox` 是 bbox 回归输出。
2. `conv2d_cov/Sigmoid` 是类别置信度输出。
3. `17x30` 是特征图网格。
4. `4` 是类别数。
5. bbox 通道数 `16 = 4 classes * 4 bbox coordinates`。

这类输出不是普通的：

```text
[x1, y1, x2, y2, score, class]
```

所以必须手写 parser。

#### 2. 层查找

文件中有：

```cpp
find_layer_exact
find_layer_by_dims
```

作用是找到 bbox 输出层和 confidence 输出层。

它优先按名字找：

```text
conv2d_bbox
conv2d_cov/Sigmoid
```

也兼容旧名字：

```text
output_bbox
output_cov
```

如果名字不匹配，还可以按 tensor 维度兜底。

电赛启发：

模型部署中，经常会遇到“模型输出层名字变了”的问题。不能只会照抄 demo，要学会从 tensor 名字、shape、语义去排查。

#### 3. bbox 解码

`NvDsInferParseCustomResnet()` 是核心函数。

它负责：

1. 遍历类别。
2. 遍历特征图网格。
3. 读取每个位置的 confidence。
4. 和阈值比较。
5. 根据 bbox 输出计算矩形框。
6. 将框写入 `objectList`。

写入 `objectList` 后，DeepStream 才能知道哪里有目标。

这就是“模型 tensor -> 检测框 metadata”的过程。

#### 4. 异常框过滤

代码中有：

```cpp
std::isfinite
right <= left
bottom <= top
CLIP_VAL
```

这些用于过滤：

1. NaN。
2. Inf。
3. 反向框。
4. 超出图像边界的框。

之前项目运行一段时间出现过：

```text
cudaErrorIllegalAddress
```

可能就和异常框、GPU 后处理、tracker/OSD 收到非法数据有关。

电赛启发：

工程系统必须防御异常数据。比赛现场环境复杂，传感器和模型输出都可能不稳定，鲁棒性非常重要。

### 3. configs/pgie_config_fd_lpd.txt

文件位置：

```text
configs/pgie_config_fd_lpd.txt
```

学习价值：非常高。

这是 DeepStream 的 `nvinfer` 配置文件。它看起来只是配置，但实际上决定了模型能不能正常部署。

核心配置：

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

重点学习内容：

#### 1. 模型路径

```ini
onnx-file
model-engine-file
labelfile-path
```

任何一个路径不对，模型就无法加载。

之前项目中多次报错，本质都是路径、库、模型文件、配置不匹配。

#### 2. 输出层名字

```ini
output-blob-names=conv2d_bbox;conv2d_cov/Sigmoid
```

这个必须和 ONNX 输出一致。

如果 ONNX 输出叫：

```text
output_bbox
output_cov
```

但配置写：

```text
conv2d_bbox
conv2d_cov/Sigmoid
```

parser 就可能找不到输出。

电赛启发：

部署模型时，必须会检查输入输出名字和 shape。不能只看模型文件是否存在。

#### 3. 阈值调参

```ini
[class-attrs-all]
pre-cluster-threshold=0.2
topk=20
nms-iou-threshold=0.5
```

这些会影响识别精度。

调参原则：

| 现象 | 调整 |
| --- | --- |
| 漏检多 | 降低 `pre-cluster-threshold` |
| 误检多 | 提高 `pre-cluster-threshold` |
| 同一目标多个框 | 调整 `nms-iou-threshold` |
| 输出太乱 | 提高阈值或降低 `topk` |

电赛启发：

模型效果不是固定的。部署阶段的阈值、NMS、ROI、图像质量，都会影响最终结果。

### 4. caffe2onnx.py

文件位置：

```text
caffe2onnx.py
```

学习价值：高。

这个文件用于把 NVIDIA 原始 Caffe 模型转换成 ONNX。

为什么重要：

原始项目下载下来是 Caffe 模型：

```text
fd_lpd.caffemodel
fd_lpd.prototxt
```

但是当前 Jetson 上 TensorRT 10.7 的 `trtexec` 只支持 ONNX，不再支持老 Caffe 参数：

```text
--deploy
--model
```

所以必须转成：

```text
fd_lpd.onnx
```

重点学习内容：

1. 如何读取 Caffe `prototxt`。
2. 如何解析 Caffe 权重。
3. 如何创建 ONNX 节点。
4. 如何保存 ONNX 模型。
5. 如何做 ONNX shape inference。
6. 如何修正输出层名字。

关键映射：

```python
parser_output_names = {
    'output_bbox': 'conv2d_bbox',
    'output_cov': 'conv2d_cov/Sigmoid',
}
```

这段很重要，因为它解决了 parser 输出名匹配问题。

电赛启发：

未来你可能会遇到：

1. PyTorch 转 ONNX。
2. ONNX 转 TensorRT。
3. 模型输出名不对。
4. shape 不匹配。
5. 某些算子不支持。

这个文件能帮你建立“模型格式转换”的经验。

### 5. build_engine.sh

文件位置：

```text
build_engine.sh
```

学习价值：高。

它负责用 TensorRT 构建 engine：

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

为什么有价值：

1. 它体现了端侧部署中的模型加速流程。
2. ONNX 是通用模型格式。
3. TensorRT engine 是 Jetson 上真正高效运行的格式。
4. FP16 是边缘设备常用加速方式。

之前出现过运行时构建 engine 导致：

```text
NvMapMemAllocInternalTagged error 12
```

解决思路就是提前构建 engine，而不是在实时视频管道运行时构建。

电赛启发：

比赛现场时间紧，设备算力有限。一定要提前准备好 engine，不要现场临时转换模型。

### 6. model_arch_viewer/generate_viewer.py

文件位置：

```text
model_arch_viewer/generate_viewer.py
```

学习价值：中高。

这是后面新增的 ONNX 网络架构查看器。

它会读取：

```text
fd_lpd_model/fd_lpd.onnx
```

然后生成：

```text
fd_lpd_architecture.html
fd_lpd_architecture_simple.html
fd_lpd_architecture_detailed.html
fd_lpd_architecture.svg
fd_lpd_summary.md
```

重点学习内容：

1. 如何用 Python 读取 ONNX。
2. 如何遍历 ONNX graph。
3. 如何读取 node、op、input、output、shape。
4. 如何统计网络结构。
5. 如何生成可视化网页。

电赛启发：

真正理解模型时，不能只知道“它是一个模型”。你要知道：

1. 输入尺寸是多少。
2. 输出 tensor 是什么。
3. 网络有几个分支。
4. bbox head 和 confidence head 在哪里。
5. 输出 shape 为什么是那样。

### 7. model_arch_viewer/output/fd_lpd_architecture_detailed.html

文件位置：

```text
model_arch_viewer/output/fd_lpd_architecture_detailed.html
```

学习价值：高，适合观察模型结构。

它不是代码，但非常适合学习网络结构。

从该页面可以看到：

```text
Input: data FLOAT[1x3x270x480]
Output 1: conv2d_bbox FLOAT[1x16x17x30]
Output 2: conv2d_cov/Sigmoid FLOAT[1x4x17x30]
Nodes: 88
```

Op 统计：

```text
Conv: 30
BatchNormalization: 26
Relu: 18
Add: 8
Sigmoid: 2
Concat: 2
Identity: 2
```

这说明模型大致是：

```text
输入图像
  -> 卷积/BN/ReLU 主干
  -> 残差 Add
  -> 两个检测分支
  -> bbox 输出
  -> confidence 输出
```

这对理解目标检测模型很有帮助。

### 8. CMakeLists.txt

文件位置：

```text
CMakeLists.txt
```

学习价值：中高。

这个文件负责把项目编译起来。

它链接了：

1. GStreamer。
2. CUDA。
3. DeepStream。
4. 海康 MVS SDK。
5. 自定义 parser 动态库。

重点学习内容：

1. 如何配置 DeepStream include 和 lib。
2. 如何配置 CUDA。
3. 如何配置 MVS SDK。
4. 如何生成主程序 `show`。
5. 如何生成动态库 `libnvdsinfer_custom_fd_lpd.so`。
6. 如何链接 `nvds_infer`、`nvds_meta`、`MvCameraControl`。

电赛启发：

很多嵌入式/视觉项目不是 Python 一把梭，最后经常要 C++、CMake、SDK、动态库。会 CMake 是很重要的工程能力。

### 9. README.md

文件位置：

```text
README.md
```

学习价值：高，适合复盘。

它记录了：

1. 项目结构。
2. 运行方法。
3. 主要代码作用。
4. 调试过程中遇到的问题。
5. 解决办法。
6. 常用排查命令。
7. 调参建议。

建议你隔一段时间再读一次。你会发现很多当时觉得“只是报错”的问题，其实都是视觉工程中的常见坑。

## 二、模型文件如何看

### fd_lpd_model/fd_lpd.prototxt

这是原始 Caffe 网络结构。

可以学习：

1. Caffe 网络定义方式。
2. 卷积层、BN、ReLU、Concat 的原始结构。
3. 模型输入输出设计。

但不建议一开始就硬啃它。更建议配合 ONNX 架构图看。

### fd_lpd_model/fd_lpd.caffemodel

这是 Caffe 权重文件。

它不是文本学习材料，主要作用是被 `caffe2onnx.py` 读取并转换。

### fd_lpd_model/fd_lpd.onnx

这是转换后的 ONNX 模型。

它是现代 AI 部署中很重要的格式。

建议用：

```text
model_arch_viewer/output/fd_lpd_architecture_detailed.html
```

来观察它，而不是直接读二进制文件。

### fd_lpd_model/labels.txt

类别标签文件。

虽然很小，但它告诉你模型输出类别含义。当前模型主要关心：

```text
class 0: face
class 1: license plate
```

类别 2 和类别 3 在配置里被高阈值过滤掉。

## 三、可以少看的文件

以下内容学习价值较低，可以暂时忽略：

```text
build/
build/CMakeFiles/
build/Makefile
build/cmake_install.cmake
build/show
.codex_tmp/
.claude/
```

原因：

1. `build/` 大多是编译产物。
2. `show` 是二进制可执行文件，不适合阅读。
3. `CMakeFiles` 是 CMake 自动生成内容。
4. `.codex_tmp` 是临时依赖目录。
5. `.claude` 与项目核心视觉链路无关。

日志文件如：

```text
word文档.odt
word111文档.odt
```

可以作为排障复盘材料看，但不是核心学习文件。

## 四、推荐学习路线

### 第一阶段：理解整体系统

先看：

```text
README.md
main.cpp
```

目标：

1. 知道相机数据怎么进入程序。
2. 知道 DeepStream 管道怎么串起来。
3. 知道遮蔽效果在哪里实现。

建议重点画出这条链路：

```text
海康相机 -> ImageCallBack -> appsrc -> nvinfer -> parser -> nvdsosd -> 显示
```

### 第二阶段：理解模型部署

再看：

```text
configs/pgie_config_fd_lpd.txt
build_engine.sh
CMakeLists.txt
```

目标：

1. 知道模型路径怎么配置。
2. 知道 ONNX 如何变成 TensorRT engine。
3. 知道自定义 parser 动态库如何接入。
4. 知道 C++ 项目如何链接 DeepStream、CUDA、相机 SDK。

### 第三阶段：理解模型输出

再看：

```text
nvdsinfer_custom_fd_lpd.cpp
model_arch_viewer/output/fd_lpd_architecture_detailed.html
```

目标：

1. 知道模型输出 shape 是什么。
2. 知道 bbox 和 confidence 怎么解码。
3. 知道 parser 如何把 tensor 转成检测框。
4. 知道异常框为什么要过滤。

### 第四阶段：理解模型转换

最后看：

```text
caffe2onnx.py
fd_lpd_model/fd_lpd.prototxt
```

目标：

1. 知道为什么 Caffe 要转 ONNX。
2. 知道输出层命名为什么重要。
3. 知道模型格式转换可能遇到的问题。

## 五、对电赛最有帮助的能力点

### 1. 相机工程能力

来自：

```text
main.cpp
```

能力包括：

1. 接工业相机。
2. 设置曝光。
3. 设置帧率。
4. 处理图像格式。
5. 解决画面过暗、过曝、帧率过高问题。

比赛迁移方向：

1. 机器人视觉。
2. 自动瞄准。
3. 目标跟踪。
4. 智能巡检。
5. 交通识别。

### 2. 实时视频流能力

来自：

```text
main.cpp
GStreamer pipeline
```

能力包括：

1. 使用 `appsrc` 自定义输入。
2. 使用 `queue` 做缓冲。
3. 使用 `nvvideoconvert` 做硬件转换。
4. 控制帧率和延迟。

比赛迁移方向：

1. 实时检测。
2. 实时追踪。
3. 低延迟视觉控制。
4. 边缘端视频处理。

### 3. AI 模型部署能力

来自：

```text
caffe2onnx.py
build_engine.sh
configs/pgie_config_fd_lpd.txt
```

能力包括：

1. Caffe 转 ONNX。
2. ONNX 转 TensorRT。
3. FP16 推理。
4. engine 文件管理。
5. 输出层匹配。

比赛迁移方向：

1. Jetson 部署 YOLO。
2. 部署分类模型。
3. 部署分割模型。
4. 部署自训练模型。

### 4. 后处理能力

来自：

```text
nvdsinfer_custom_fd_lpd.cpp
```

能力包括：

1. 读取模型输出 tensor。
2. 解码 bbox。
3. 过滤低置信度目标。
4. 过滤异常框。
5. 输出 DeepStream 检测结果。

比赛迁移方向：

1. 自定义 YOLO parser。
2. 自定义关键点检测后处理。
3. 自定义分割 mask 后处理。
4. 自定义姿态估计后处理。

### 5. 调参和排障能力

来自：

```text
README.md
configs/pgie_config_fd_lpd.txt
main.cpp
```

能力包括：

1. 从日志定位问题。
2. 判断是模型问题、路径问题、配置问题还是图像问题。
3. 调整阈值、曝光、Gamma、帧率。
4. 处理 CUDA、TensorRT、DeepStream 报错。

比赛迁移方向：

这几乎是所有电赛项目都会用到的能力。

## 六、这个项目里最值得记住的经验

### 经验 1：模型跑起来不等于业务完成

之前模型已经能加载、parser 已经能看到输出，但是没有遮蔽效果。

原因是：

```text
nvinfer 只负责检测，不负责遮蔽。
```

最终还需要：

```text
nvdsosd + pad probe
```

来实现业务逻辑。

### 经验 2：图像质量会直接影响 AI 效果

人脸太黑时，模型识别效果差。

解决不是先换模型，而是先调：

```text
ExposureTime
Gain
Gamma
```

### 经验 3：模型输出名和配置必须匹配

ONNX 输出：

```text
conv2d_bbox
conv2d_cov/Sigmoid
```

配置也必须写：

```ini
output-blob-names=conv2d_bbox;conv2d_cov/Sigmoid
```

否则 parser 可能找不到输出。

### 经验 4：不要在实时管道里临时构建 engine

Jetson 资源有限，实时推流时构建 engine 容易内存爆。

正确做法：

```bash
./build_engine.sh
cd build
./show
```

### 经验 5：后处理必须做异常保护

parser 中过滤：

```text
NaN
Inf
反向框
越界框
```

可以减少长时间运行时的不稳定。

### 经验 6：配置文件也是核心代码

`pgie_config_fd_lpd.txt` 虽然不是 C++，但它决定了：

1. 用哪个模型。
2. 用哪个 engine。
3. 用哪个 parser。
4. 输出层叫什么。
5. 阈值是多少。
6. NMS 怎么做。

AI 工程里，配置文件和代码一样重要。

## 七、如果未来打电赛，可以如何复用这个项目

### 方向 1：换成 YOLO 目标检测

保留：

```text
main.cpp 的相机采集和 DeepStream 管道
build_engine.sh 的 engine 构建思路
CMakeLists.txt 的工程结构
```

替换：

```text
模型文件
pgie_config
custom parser
labels
```

可做项目：

1. 交通标志识别。
2. 装甲板检测。
3. 物体抓取定位。
4. 缺陷检测。

### 方向 2：加控制输出

在检测结果基础上加入：

```text
串口
GPIO
CAN
PWM
```

可做项目：

1. 检测目标后控制舵机。
2. 跟踪目标后控制小车。
3. 识别手势后控制设备。
4. 视觉定位后控制机械臂。

### 方向 3：做实时视频分析系统

保留 DeepStream 管道，增加：

```text
保存视频
RTSP 推流
截图
报警
目标计数
轨迹记录
```

可做项目：

1. 智能监控。
2. 人流统计。
3. 车流统计。
4. 安全检测。

### 方向 4：训练自己的模型

保留部署链路，替换模型。

你需要学习：

1. 数据采集。
2. 数据标注。
3. 模型训练。
4. 导出 ONNX。
5. TensorRT 加速。
6. parser 或后处理适配。

这个项目已经提供了部署端模板。

## 八、最终推荐重点

如果只选 5 个最值得深入的文件：

```text
1. main.cpp
2. nvdsinfer_custom_fd_lpd.cpp
3. configs/pgie_config_fd_lpd.txt
4. caffe2onnx.py
5. build_engine.sh
```

如果只选 3 个最适合电赛的文件：

```text
1. main.cpp
2. nvdsinfer_custom_fd_lpd.cpp
3. configs/pgie_config_fd_lpd.txt
```

如果只选 1 个最应该反复看的文件：

```text
main.cpp
```

因为它把相机、视频流、模型推理、遮蔽显示、Jetson 运行全串起来了。

## 九、一句话总结

这个文件夹的精华不是某一个单独模型，而是一套完整的边缘 AI 视觉工程模板。它包含了从相机采集到模型部署、从 TensorRT 加速到 DeepStream 后处理、从图像调参到异常排查的全过程。未来打电赛时，这套经验可以迁移到目标检测、机器人视觉、智能小车、机械臂识别、交通识别、缺陷检测、实时监控等很多方向。
