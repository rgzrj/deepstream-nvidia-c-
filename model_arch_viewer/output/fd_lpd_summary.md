# FD-LPD ONNX Neural Network Architecture

- Model: `D:\python代码\工程\26.05.23\fd_lpd_model\fd_lpd.onnx`
- Graph: `FD_LPD_Redactor`
- IR version: `10`
- Producer: `caffe2onnx `
- Opsets: `ai.onnx:11`
- Nodes: `88`
- Initializers: `164`

## Inputs

| Name | Shape |
| --- | --- |
| `data` | `FLOAT[1x3x270x480]` |

## Outputs

| Name | Shape |
| --- | --- |
| `conv2d_bbox` | `FLOAT[1x16x17x30]` |
| `conv2d_cov/Sigmoid` | `FLOAT[1x4x17x30]` |

## Op Counts

| Op Type | Count |
| --- | ---: |
| `Conv` | 30 |
| `BatchNormalization` | 26 |
| `Relu` | 18 |
| `Add` | 8 |
| `Sigmoid` | 2 |
| `Concat` | 2 |
| `Identity` | 2 |

## Generated Files

- Main HTML: `fd_lpd_architecture.html`
- Simple HTML: `fd_lpd_architecture_simple.html`
- Detailed HTML: `fd_lpd_architecture_detailed.html`
- SVG: `fd_lpd_architecture.svg`
