"""
Caffe to ONNX converter for FD_LPD_Redactor model.
No Caffe installation required — parses prototxt and caffemodel directly.

This handles NVIDIA/TensorRT's caffe.proto format (field 100 for layers,
field 12 for float data in BlobProto).

Usage:
    python caffe2onnx.py
"""

import re
import sys
import struct
from pathlib import Path
import numpy as np
import onnx
from onnx import helper, numpy_helper, TensorProto


# ═══════════════════════════════════════════════════════════════════════════════
# Binary protobuf wire format reader
# ═══════════════════════════════════════════════════════════════════════════════

class ProtoReader:
    WIRE_VARINT = 0
    WIRE_64BIT = 1
    WIRE_LENGTH = 2
    WIRE_32BIT = 5

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _read_varint(self) -> int:
        result = 0
        shift = 0
        while self.pos < len(self.data):
            byte = self.data[self.pos]
            self.pos += 1
            result |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                return result
            shift += 7
        return result

    def _read_tag(self) -> tuple[int, int]:
        tag = self._read_varint()
        return tag >> 3, tag & 0x07

    def _read_length_delimited(self) -> bytes:
        length = self._read_varint()
        result = self.data[self.pos:self.pos + length]
        self.pos += length
        return result

    def _skip_field(self, wire_type: int):
        if wire_type == self.WIRE_VARINT:
            self._read_varint()
        elif wire_type == self.WIRE_64BIT:
            self.pos += 8
        elif wire_type == self.WIRE_LENGTH:
            length = self._read_varint()
            self.pos += length
        elif wire_type == self.WIRE_32BIT:
            self.pos += 4


# ═══════════════════════════════════════════════════════════════════════════════
# Caffemodel weight reader (NVIDIA/TensorRT format: layers in field 100)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_caffemodel(filepath: str) -> dict[str, list[np.ndarray]]:
    """Parse a .caffemodel binary file and return layer_name -> [weight_blobs]."""
    with open(filepath, 'rb') as f:
        data = f.read()

    reader = ProtoReader(data)
    weights = {}

    while reader.pos < len(data):
        fn, wt = reader._read_tag()

        if fn == 100 and wt == ProtoReader.WIRE_LENGTH:
            # NVIDIA TensorRT caffe.proto: field 100 = LayerParameter
            layer_blob = reader._read_length_delimited()
            name, blobs = _parse_layer_parameter(layer_blob)
            if name and blobs:
                weights[name] = blobs
        elif wt == ProtoReader.WIRE_LENGTH:
            # Skip other length-delimited fields
            reader.pos += reader._read_varint() if False else 0
            reader._skip_field(wt)
        else:
            reader._skip_field(wt)

    return weights


def _parse_layer_parameter(data: bytes) -> tuple[str | None, list[np.ndarray]]:
    """Parse a LayerParameter message. Returns (name, [blob_arrays])."""
    reader = ProtoReader(data)
    name = None
    blobs = []

    while reader.pos < len(data):
        fn, wt = reader._read_tag()

        if fn == 1 and wt == ProtoReader.WIRE_LENGTH:
            name = reader._read_length_delimited().decode('utf-8')
        elif fn == 2 and wt == ProtoReader.WIRE_LENGTH:
            # type field — read but ignore
            reader._read_length_delimited()
        elif fn == 7 and wt == ProtoReader.WIRE_LENGTH:
            # blobs (repeated BlobProto)
            blob_data = reader._read_length_delimited()
            arr = _parse_blob_proto(blob_data)
            if arr is not None and arr.size > 0:
                blobs.append(arr)
        else:
            reader._skip_field(wt)

    return name, blobs


def _parse_blob_proto(data: bytes) -> np.ndarray | None:
    """Parse NVIDIA TensorRT BlobProto format.
    Field 7 = shape sub-message (field 1 = packed bytes)
    Field 12 = raw float data (length-delimited bytes)
    """
    reader = ProtoReader(data)
    float_data = None

    while reader.pos < len(data):
        fn, wt = reader._read_tag()

        if fn == 12 and wt == ProtoReader.WIRE_LENGTH:
            # Raw float data
            raw = reader._read_length_delimited()
            float_data = np.frombuffer(raw, dtype=np.float32)
        elif fn == 7 and wt == ProtoReader.WIRE_LENGTH:
            # Shape sub-message — parse it but just skip
            shape_data = reader._read_length_delimited()
        else:
            reader._skip_field(wt)

    return float_data


# ═══════════════════════════════════════════════════════════════════════════════
# Prototxt parser
# ═══════════════════════════════════════════════════════════════════════════════

def parse_prototxt(filepath: str) -> dict:
    """Parse Caffe prototxt to extract network structure."""
    with open(filepath, 'r') as f:
        text = f.read()

    net = {}
    net['name'] = _re_first(r'name:\s*"([^"]*)"', text) or 'network'
    net['input'] = _re_first(r'input:\s*"([^"]*)"', text) or 'data'
    net['input_dim'] = [int(d) for d in re.findall(r'input_dim:\s*(\d+)', text)]

    layers = []
    # Match layer { ... } blocks (handles nested braces)
    layer_blocks = _split_layer_blocks(text)

    for block in layer_blocks:
        layer = {}
        layer['name'] = _re_first(r'name:\s*"([^"]*)"', block) or ''
        layer['type'] = _re_first(r'type:\s*"([^"]*)"', block) or ''
        layer['bottoms'] = re.findall(r'bottom:\s*"([^"]*)"', block)
        layer['tops'] = re.findall(r'top:\s*"([^"]*)"', block)

        if layer['type'] == 'Convolution':
            cp = {}
            for key in ['num_output', 'kernel_h', 'kernel_w', 'stride_h',
                         'stride_w', 'pad_h', 'pad_w', 'group']:
                val = _re_first(rf'{key}:\s*(\d+)', block)
                if val:
                    cp[key] = int(val)
            cp.setdefault('group', 1)
            layer['convolution_param'] = cp
        elif layer['type'] == 'Scale':
            layer['scale_param'] = {
                'axis': int(a) if (a := _re_first(r'axis:\s*(\d+)', block)) else 1,
                'bias_term': r'bias_term:\s*true' in block,
            }
        elif layer['type'] == 'Eltwise':
            op = _re_first(r'operation:\s*(\w+)', block)
            layer['eltwise_param'] = {'operation': op or 'SUM'}
        elif layer['type'] == 'Concat':
            layer['concat_param'] = {
                'axis': int(a) if (a := _re_first(r'axis:\s*(\d+)', block)) else 1
            }

        layers.append(layer)

    net['layers'] = layers
    return net


def _split_layer_blocks(text: str) -> list[str]:
    """Split prototxt text into individual layer blocks."""
    blocks = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                # Check if this is a layer block
                prefix = text[max(0, i-10):i].strip()
                if prefix.endswith('layer') or text[max(0, i-7):i].strip() == 'layer':
                    start = i + 1
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                blocks.append(text[start:i])
                start = -1
    return blocks


def _re_first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


# ═══════════════════════════════════════════════════════════════════════════════
# ONNX graph builder
# ═══════════════════════════════════════════════════════════════════════════════

def convert_to_onnx(net: dict, weights: dict, output_path: str):
    """Convert parsed network + weights to ONNX model."""
    import onnx
    from onnx import helper, numpy_helper, TensorProto

    nodes = []
    inputs = []
    initializers = []
    tensor_counter = [0]
    BN_EPSILON = 1e-5

    def make_tensor_name(base: str) -> str:
        tensor_counter[0] += 1
        return f"{base}_{tensor_counter[0]}"

    def add_initializer(name: str, data: np.ndarray):
        initializers.append(numpy_helper.from_array(data.astype(np.float32), name=name))

    def conv_output_shape(in_shape, num_output, kh, kw, sh, sw, ph, pw):
        b, c, h, w = in_shape
        oh = (h + 2 * ph - kh) // sh + 1
        ow = (w + 2 * pw - kw) // sw + 1
        return (b, num_output, oh, ow)

    batch, channels, height, width = net['input_dim']
    tensor_shapes = {net['input']: (batch, channels, height, width)}

    # Input
    inputs.append(helper.make_tensor_value_info(
        net['input'], TensorProto.FLOAT, [batch, channels, height, width]
    ))

    blob_map = {net['input']: net['input']}
    parser_output_names = {
        'output_bbox': 'conv2d_bbox',
        'output_cov': 'conv2d_cov/Sigmoid',
    }

    for layer in net['layers']:
        ltype = layer['type']
        lname = layer['name']
        bottom = layer['bottoms'][0] if layer['bottoms'] else net['input']
        top = layer['tops'][0] if layer['tops'] else lname

        in_tensor = blob_map.get(bottom, bottom)
        in_shape = tensor_shapes.get(in_tensor)
        blobs = weights.get(lname, [])

        if ltype == 'Convolution':
            cp = layer.get('convolution_param', {})
            num_o = cp.get('num_output', 0)
            kh = cp.get('kernel_h', 1)
            kw = cp.get('kernel_w', 1)
            sh = cp.get('stride_h', 1)
            sw = cp.get('stride_w', 1)
            ph = cp.get('pad_h', 0)
            pw = cp.get('pad_w', 0)
            group = cp.get('group', 1)

            if not blobs:
                print(f"  WARNING: No weights for '{lname}', skipping")
                continue

            weight = blobs[0]
            # Compute expected weight shape from prototxt
            if in_shape:
                in_c = in_shape[1] // group
                expected_shape = (num_o, in_c, kh, kw)
            else:
                expected_shape = (num_o, -1, kh, kw)

            if weight.ndim == 1 and weight.size == num_o * (in_shape[1] // group if in_shape else 1) * kh * kw:
                weight = weight.reshape(num_o, in_shape[1] // group, kh, kw)
            elif weight.ndim != 4:
                # Try to reshape based on expected shape
                if in_shape:
                    weight = weight.reshape(num_o, in_shape[1] // group, kh, kw)
                else:
                    print(f"  WARNING: Cannot reshape weights for '{lname}'")
                    continue

            w_name = f"{lname}_weight"
            add_initializer(w_name, weight)

            out_name = make_tensor_name(lname)

            if len(blobs) >= 2:
                bias = blobs[1]
                if bias.size == num_o:
                    bias = bias.reshape(num_o)
                b_name = f"{lname}_bias"
                add_initializer(b_name, bias)
                node = helper.make_node(
                    'Conv', inputs=[in_tensor, w_name, b_name],
                    outputs=[out_name], name=lname,
                    kernel_shape=[kh, kw], strides=[sh, sw],
                    pads=[ph, pw, ph, pw], group=group,
                )
            else:
                node = helper.make_node(
                    'Conv', inputs=[in_tensor, w_name],
                    outputs=[out_name], name=lname,
                    kernel_shape=[kh, kw], strides=[sh, sw],
                    pads=[ph, pw, ph, pw], group=group,
                )
            nodes.append(node)

            if in_shape:
                new_shape = conv_output_shape(in_shape, num_o, kh, kw, sh, sw, ph, pw)
                tensor_shapes[out_name] = new_shape
            blob_map[top] = out_name

        elif ltype == 'Scale':
            # NVIDIA DetectNet: Scale layers are fused BatchNorm (gamma*x + beta)
            if not blobs:
                print(f"  WARNING: No weights for scale '{lname}', skipping")
                blob_map[top] = in_tensor
                continue

            gamma = blobs[0]
            beta = blobs[1] if len(blobs) >= 2 else np.zeros_like(gamma)

            # Ensure 1D
            gamma = gamma.reshape(-1)
            beta = beta.reshape(-1)
            zeros = np.zeros_like(gamma, dtype=np.float32)
            ones = np.ones_like(gamma, dtype=np.float32)

            scale_name = f"{lname}_scale"
            bias_name = f"{lname}_B"
            mean_name = f"{lname}_mean"
            var_name = f"{lname}_var"

            add_initializer(scale_name, gamma)
            add_initializer(bias_name, beta)
            add_initializer(mean_name, zeros)
            add_initializer(var_name, ones)

            out_name = make_tensor_name(lname)
            node = helper.make_node(
                'BatchNormalization',
                inputs=[in_tensor, scale_name, bias_name, mean_name, var_name],
                outputs=[out_name], name=lname, epsilon=BN_EPSILON,
            )
            nodes.append(node)

            if in_shape:
                tensor_shapes[out_name] = in_shape
            blob_map[top] = out_name

        elif ltype == 'ReLU':
            out_name = make_tensor_name(lname)
            nodes.append(helper.make_node(
                'Relu', inputs=[in_tensor], outputs=[out_name], name=lname
            ))
            if in_shape:
                tensor_shapes[out_name] = in_shape
            blob_map[top] = out_name

        elif ltype == 'Sigmoid':
            out_name = make_tensor_name(lname)
            nodes.append(helper.make_node(
                'Sigmoid', inputs=[in_tensor], outputs=[out_name], name=lname
            ))
            if in_shape:
                tensor_shapes[out_name] = in_shape
            blob_map[top] = out_name

        elif ltype == 'Eltwise':
            op = layer.get('eltwise_param', {}).get('operation', 'SUM')
            if len(layer['bottoms']) < 2:
                print(f"  WARNING: Eltwise '{lname}' has < 2 inputs")
                blob_map[top] = in_tensor
                continue

            b2 = layer['bottoms'][1]
            in_tensor2 = blob_map.get(b2, b2)

            out_name = make_tensor_name(lname)
            if op == 'SUM':
                nodes.append(helper.make_node(
                    'Add', inputs=[in_tensor, in_tensor2],
                    outputs=[out_name], name=lname
                ))
            elif op == 'MUL':
                nodes.append(helper.make_node(
                    'Mul', inputs=[in_tensor, in_tensor2],
                    outputs=[out_name], name=lname
                ))
            else:
                print(f"  WARNING: Unsupported Eltwise op '{op}'")
                blob_map[top] = in_tensor
                continue

            if in_shape:
                tensor_shapes[out_name] = in_shape
            blob_map[top] = out_name

        elif ltype == 'Concat':
            axis = layer.get('concat_param', {}).get('axis', 1)
            in_tensors = []
            for b in layer['bottoms']:
                bt = blob_map.get(b, b)
                if bt not in in_tensors:
                    in_tensors.append(bt)

            # Concat → intermediate name; Identity → final name (preserved by TensorRT)
            concat_out = make_tensor_name(lname + "_concat")
            nodes.append(helper.make_node(
                'Concat', inputs=in_tensors, outputs=[concat_out],
                name=lname, axis=axis
            ))
            out_name = parser_output_names.get(top, top)
            nodes.append(helper.make_node(
                'Identity', inputs=[concat_out], outputs=[out_name],
                name=lname + "_identity"
            ))

            # Infer output shape
            shapes = [tensor_shapes.get(t) for t in in_tensors if tensor_shapes.get(t)]
            if shapes and len(shapes) == len(in_tensors):
                concat_ch = sum(s[axis] for s in shapes)
                s0 = list(shapes[0])
                s0[axis] = concat_ch
                tensor_shapes[out_name] = tuple(s0)

            for t in layer['tops']:
                blob_map[t] = out_name

        else:
            print(f"  WARNING: Unknown layer type '{ltype}' ('{lname}')")
            blob_map[top] = in_tensor

    # Collect output names
    output_names = ['output_bbox', 'output_cov']
    outputs = []
    for name in output_names:
        tensor_name = blob_map.get(name, parser_output_names.get(name, name))
        shape = tensor_shapes.get(tensor_name)
        if shape:
            outputs.append(helper.make_tensor_value_info(
                tensor_name, TensorProto.FLOAT, list(shape)))
        else:
            outputs.append(helper.make_tensor_value_info(
                tensor_name, TensorProto.FLOAT, None))

    # Build graph
    graph = helper.make_graph(
        nodes=nodes, name=net['name'],
        inputs=inputs, outputs=outputs,
        initializer=initializers,
    )

    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid('', 11)],
        producer_name='caffe2onnx'
    )

    try:
        model = onnx.shape_inference.infer_shapes(model)
    except Exception as e:
        print(f"  Note: shape inference skipped ({e})")

    onnx.save(model, output_path)
    print(f"  Saved ONNX model to: {output_path}")
    return model


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    base = Path(__file__).parent / 'fd_lpd_model'
    prototxt = base / 'fd_lpd.prototxt'
    caffemodel = base / 'fd_lpd.caffemodel'
    onnx_out = base / 'fd_lpd.onnx'

    print("=== Caffe -> ONNX Converter ===")
    print(f"  Prototxt:   {prototxt}")
    print(f"  Caffemodel: {caffemodel}")
    print(f"  Output:     {onnx_out}")

    # Step 1
    print("\n[1/3] Parsing prototxt...")
    net = parse_prototxt(str(prototxt)) #把文本格式的 prototxt 转换成 Python 字典
    print(f"  Network: {net['name']}")
    print(f"  Input:   {net['input']} {net['input_dim']}")
    print(f"  Layers:  {len(net['layers'])}")

    # Step 2
    print("\n[2/3] Parsing caffemodel weights...")
    weights = parse_caffemodel(str(caffemodel)) #返回层的名称和对应的权重数组列表
    print(f"  Weight layers found: {len(weights)}")

    weight_total = sum(sum(b.size for b in blobs) for blobs in weights.values())
    print(f"  Total parameters: {weight_total:,}")

    # Step 3
    print("\n[3/3] Converting to ONNX...")

    """
    把解析好的 Caffe 层结构映射成对应的 ONNX 算子
    把 Caffe 的权重数组转换成 ONNX 的张量格式
    构建完整的 ONNX 计算图并保存到文件
    """
    convert_to_onnx(net, weights, str(onnx_out))

    # Validate
    print("\n=== Validation ===")
    model = onnx.load(str(onnx_out))
    onnx.checker.check_model(model)
    print(f"  ONNX model is valid")
    print(f"  Input:  {[(i.name, [d.dim_value for d in i.type.tensor_type.shape.dim]) for i in model.graph.input]}")
    print(f"  Output: {[(o.name, [d.dim_value for d in o.type.tensor_type.shape.dim]) for o in model.graph.output]}")
    print(f"  Nodes:  {len(model.graph.node)}")
    print(f"  Opset:  {model.opset_import[0].version}")

    print(f"\nDone! File: {onnx_out}")
    print(f"\nBuild TensorRT engine on Jetson:")
    print(f"  trtexec --onnx={onnx_out} \\")
    print(f"    --saveEngine=fd_lpd_b1_fp16.engine --fp16")


if __name__ == '__main__':
    main()
