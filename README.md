# 基于deepstream，jetson,海康相机以及英伟达开源的模型来实现的人脸遮挡和车牌号遮挡

# 硬件配置与编译指南

## 一、硬件要求

| 硬件 | 型号 / 规格 | 备注 |
|------|------------|------|
| **开发板** | NVIDIA Jetson Orin / AGX Xavier | 必须支持 DeepStream 和 TensorRT |
| **相机** | 海康工业相机（USB 或 GigE） | 需要 MVS SDK，型号不限 |
| **相机分辨率** | 1440 × 1080 | 代码中可修改 |
| **相机帧率** | 15 FPS | 代码中可修改 |

> 如果没有海康相机，也可以改用普通 USB 摄像头或 RTSP 流，但需要修改 `main.cpp` 中的相机采集部分。

## 二、软件依赖

### 2.1 Jetson 端必须安装

| 软件 | 版本 | 安装方式 |
|------|------|---------|
| **JetPack** | 6.0+ (L4T R36+) | NVIDIA SDK Manager 刷机 |
| **DeepStream** | 7.0 / 7.1 | `sudo apt install deepstream-7.1` |
| **CUDA** | 随 JetPack 自带 | — |
| **TensorRT** | 随 JetPack 自带 | — |
| **GStreamer** | 1.20+ | JetPack 自带 |
| **海康 MVS SDK** | V2.0+ | 海康官网下载 Linux 版 |
| **CMake** | 3.10+ | `sudo apt install cmake` |
| **pkg-config** | — | `sudo apt install pkg-config` |

### 2.2 PC 端（模型转换用）

| 软件 | 用途 |
|------|------|
| **Python 3.8+** | 运行 `caffe2onnx.py` |
| **numpy** | `pip install numpy` |
| **onnx** | `pip install onnx` |

## 三、编译步骤（在 Jetson 上）

### 3.1 确认依赖路径

编译前，先检查以下路径是否与你设备上的一致：

```bash
# DeepStream 路径
ls /opt/nvidia/deepstream/

# MVS SDK 路径
ls /opt/MVS/

# GStreamer
pkg-config --modversion gstreamer-1.0
```

如果路径不同，需要修改以下文件：

| 文件 | 行号 | 配置项 | 修改为 |
|------|------|--------|--------|
| CMakeLists.txt | 17 | `DEEPSTREAM_PATH` | 你的 DeepStream 路径 |
| CMakeLists.txt | 39 | `MVS_PATH` | 你的 MVS SDK 路径 |
| main.cpp | 220 | `model_dir` | 项目的实际路径 |
| main.cpp | 388 | `config-file-path` | `configs/pgie_config_fd_lpd.txt` 的实际路径 |
| main.cpp | 390 | `ll-lib-file` | DeepStream tracker 库路径 |
| configs/pgie_config_fd_lpd.txt | 63 | `onnx-file` | ONNX 模型实际路径 |
| configs/pgie_config_fd_lpd.txt | 64 | `model-engine-file` | TensorRT engine 实际路径 |
| configs/pgie_config_fd_lpd.txt | 65 | `labelfile-path` | labels.txt 实际路径 |
| configs/pgie_config_fd_lpd.txt | 77 | `custom-lib-path` | 编译出的 .so 实际路径 |

### 3.2 编译

```bash
# 1. 进入项目目录
cd /home/nvidia/Desktop/opencv/26.05.23

# 2. 创建 build 目录
mkdir -p build && cd build

# 3. CMake 配置
cmake ..

# 4. 编译
make -j$(nproc)
```

编译产物：
- `build/show` — 主程序
- `build/libnvdsinfer_custom_fd_lpd.so` — 自定义解析器动态库
- `build/pgie_config_fd_lpd.txt` — 自动拷贝的配置文件

### 3.3 构建 TensorRT Engine（一次性）

```bash
# 回到项目根目录
cd /home/nvidia/Desktop/opencv/26.05.23

# 运行 engine 构建脚本
bash build_engine.sh
```

这一步会把 ONNX 模型转换成 TensorRT 引擎文件：
```
fd_lpd_model/fd_lpd.onnx  →  fd_lpd_model/fd_lpd.onnx_b1_gpu0_fp16.engine
```

> ⚠️ 构建 engine 需要 5-10 分钟。不要跳过这一步，否则程序启动后会尝试自动构建 engine，可能因内存不足而失败。

## 四、运行

```bash
cd build
./show
```

按 `Ctrl+C` 退出。

## 五、需要修改路径的代码详解

### 5.1 main.cpp — 模型文件验证路径

```cpp
// 第 220 行
const char *model_dir = "/home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model";
```

**改为你项目实际所在的路径**，比如：
```cpp
const char *model_dir = "/home/yourname/projects/26.05.23/fd_lpd_model";
```

### 5.2 main.cpp — 管道中 nvinfer 配置路径

```cpp
// 第 388 行
"nvinfer config-file-path=/home/nvidia/Desktop/opencv/26.05.23/configs/pgie_config_fd_lpd.txt ! "
```

**改为你实际的 configs 路径**。

### 5.3 main.cpp — 跟踪器库路径

```cpp
// 第 390 行
"nvtracker ll-lib-file=/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so ! "
```

**根据你的 DeepStream 版本调整**，常见路径：
- DeepStream 7.0: `/opt/nvidia/deepstream/deepstream-7.0/lib/libnvds_nvmultiobjecttracker.so`
- DeepStream 7.1: `/opt/nvidia/deepstream/deepstream-7.1/lib/libnvds_nvmultiobjecttracker.so`

可以用以下命令确认：
```bash
find /opt/nvidia/deepstream -name "libnvds_nvmultiobjecttracker.so"
```

### 5.4 CMakeLists.txt — DeepStream 路径

```cmake
# 第 17 行
set(DEEPSTREAM_PATH "/opt/nvidia/deepstream/deepstream-7.1")
```

**改为你安装的版本**，比如：
```cmake
set(DEEPSTREAM_PATH "/opt/nvidia/deepstream/deepstream-7.0")
```

### 5.5 CMakeLists.txt — MVS SDK 路径

```cmake
# 第 39 行
set(MVS_PATH "/opt/MVS")
```

**改为你 MVS SDK 的实际安装路径**。如果不需要海康相机，可以注释掉 MVS 相关配置。

### 5.6 configs/pgie_config_fd_lpd.txt — 模型路径

此文件中有 4 处硬编码路径，全部需要修改：

```ini
onnx-file=/home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/fd_lpd.onnx
model-engine-file=/home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/fd_lpd.onnx_b1_gpu0_fp16.engine
labelfile-path=/home/nvidia/Desktop/opencv/26.05.23/fd_lpd_model/labels.txt
custom-lib-path=/home/nvidia/Desktop/opencv/26.05.23/build/libnvdsinfer_custom_fd_lpd.so
```

**全部改为你项目实际所在的路径。**

## 六、不使用海康相机怎么改

如果你没有海康相机，可以改用：

### 方案 A：读取本地视频文件

把管道中的 `appsrc` 替换为 `filesrc`：
```cpp
// 替换 BuildDeepStreamPipeline() 中的 pipeline_str
"filesrc location=test.mp4 ! qtdemux ! h264parse ! nvv4l2decoder ! mux.sink_0 "
// 后面的 nvstreammux 等保持不变
```

### 方案 B：使用 RTSP 网络流

```cpp
"rtspsrc location=rtsp://your_camera_ip/stream ! rtph264depay ! h264parse ! nvv4l2decoder ! mux.sink_0 "
```

### 方案 C：使用普通 USB 摄像头（v4l2）

```cpp
"v4l2src device=/dev/video0 ! videoconvert ! video/x-raw,format=RGBA ! mux.sink_0 "
```

同时需要在 CMakeLists.txt 中去掉 MVS 相关配置。

## 七、常见问题

### Q1: cmake 报找不到 DeepStream

```
FATAL_ERROR: DeepStream not found
```

**解决**：检查 DeepStream 版本：
```bash
ls /opt/nvidia/deepstream/
# 输出类似：deepstream-7.1
```
然后修正 `CMakeLists.txt` 第 17 行的版本号。

### Q2: 编译时报找不到 MVS SDK

```
WARNING: MVS SDK include not found
```

**解决**：如果不用海康相机，可以在 CMakeLists.txt 中删掉 MVS 相关行。如果需要用，确保 MVS SDK 已正确安装。

### Q3: 运行时找不到 .so 文件

**解决**：设置库搜索路径：
```bash
export LD_LIBRARY_PATH=/opt/nvidia/deepstream/deepstream/lib:$LD_LIBRARY_PATH
```

### Q4: 构建 engine 时内存不足

```
NvMapMemAllocInternalTagged error
```

**解决**：关闭其他程序，或者在 PC 上构建 engine 然后拷贝到 Jetson。

### Q5: 模型文件找不到

**解决**：确保 `fd_lpd_model/` 目录下有这三个文件：
- `fd_lpd.onnx`
- `fd_lpd.onnx_b1_gpu0_fp16.engine`
- `labels.txt`

如果没有 `.onnx` 文件，先在 PC 上运行 `python caffe2onnx.py` 生成。
