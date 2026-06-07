# Model Architecture Viewer

该子项目用于读取 `fd_lpd_model/fd_lpd.onnx`，并生成可以在浏览器中查看的神经网络架构页面。

## 生成内容

默认输出目录：

```text
model_arch_viewer/output/
```

默认生成：

```text
fd_lpd_architecture.html
fd_lpd_architecture_simple.html
fd_lpd_architecture_detailed.html
fd_lpd_architecture.svg
fd_lpd_summary.md
```

## 配置方式

修改 `viewer_config.json`：

```json
{
  "detailed": false
}
```

含义：

```text
false: 主页面 fd_lpd_architecture.html 使用简介版
true:  主页面 fd_lpd_architecture.html 使用详细版
```

如果 `generate_both_modes` 为 `true`，脚本还会额外生成：

```text
fd_lpd_architecture_simple.html
fd_lpd_architecture_detailed.html
```

这样不用反复修改配置也能同时查看两种模式。

## Jetson 运行

```bash
cd /home/nvidia/Desktop/opencv/26.05.23/model_arch_viewer
chmod +x run.sh
./run.sh
```

如果提示缺少 `onnx`：

```bash
python3 -m pip install --user -r requirements.txt
```

然后重新运行：

```bash
./run.sh
```

## Windows 运行

```powershell
cd D:\DIANSAI\26.05.23\model_arch_viewer
.\run_windows.ps1
```

如果本机没有安装 `onnx`：

```powershell
python -m pip install -r requirements.txt
```

## 查看结果

生成后用浏览器打开：

```text
model_arch_viewer/output/fd_lpd_architecture.html
```

简介版适合看整体结构：

```text
input -> shared backbone -> bbox / confidence head -> outputs
```

详细版适合排查每个 ONNX 节点、输入输出 tensor、op 类型和 shape。
