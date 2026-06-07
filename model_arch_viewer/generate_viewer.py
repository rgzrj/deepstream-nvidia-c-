#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path


def resolve_path(path_text: str, base_dir: Path) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(path_text)))
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def load_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    defaults = {
        "model_path": "../fd_lpd_model/fd_lpd.onnx",
        "output_dir": "output",
        "detailed": False,
        "generate_both_modes": True,
        "main_html": "fd_lpd_architecture.html",
        "simple_html": "fd_lpd_architecture_simple.html",
        "detailed_html": "fd_lpd_architecture_detailed.html",
        "summary_markdown": "fd_lpd_summary.md",
        "diagram_svg": "fd_lpd_architecture.svg",
        "page_title": "FD-LPD ONNX Neural Network Architecture",
        "max_label_length": 72,
    }
    defaults.update(config)
    return defaults


def require_onnx():
    try:
        import onnx  # type: ignore

        return onnx
    except ModuleNotFoundError:
        print("ERROR: Python package 'onnx' is required.", file=sys.stderr)
        print("Install it on Jetson with:", file=sys.stderr)
        print("  python3 -m pip install --user -r requirements.txt", file=sys.stderr)
        raise SystemExit(1)


def tensor_shape_from_value_info(value_info, tensor_proto) -> str:
    tensor_type = value_info.type.tensor_type
    if not tensor_type.HasField("shape"):
        return "?"

    dims = []
    for dim in tensor_type.shape.dim:
        if dim.dim_value > 0:
            dims.append(str(dim.dim_value))
        elif dim.dim_param:
            dims.append(dim.dim_param)
        else:
            dims.append("?")

    elem_type = tensor_type.elem_type
    try:
        dtype = tensor_proto.DataType.Name(elem_type)
    except Exception:
        dtype = str(elem_type)
    return f"{dtype}[{'x'.join(dims)}]"


def initializer_shape(initializer, tensor_proto) -> str:
    try:
        dtype = tensor_proto.DataType.Name(initializer.data_type)
    except Exception:
        dtype = str(initializer.data_type)
    dims = "x".join(str(v) for v in initializer.dims)
    return f"{dtype}[{dims}]"


def summarize_attribute(attr, attribute_proto) -> str:
    name = attr.name
    attr_type = attr.type
    try:
        type_name = attribute_proto.AttributeType.Name(attr_type)
    except Exception:
        type_name = str(attr_type)

    if attr_type == attribute_proto.FLOAT:
        return f"{name}={attr.f:g}"
    if attr_type == attribute_proto.INT:
        return f"{name}={attr.i}"
    if attr_type == attribute_proto.STRING:
        value = attr.s.decode("utf-8", errors="replace")
        return f"{name}={value}"
    if attr_type == attribute_proto.FLOATS:
        values = ", ".join(f"{v:g}" for v in list(attr.floats)[:8])
        suffix = ", ..." if len(attr.floats) > 8 else ""
        return f"{name}=[{values}{suffix}]"
    if attr_type == attribute_proto.INTS:
        values = ", ".join(str(v) for v in list(attr.ints)[:12])
        suffix = ", ..." if len(attr.ints) > 12 else ""
        return f"{name}=[{values}{suffix}]"
    return f"{name}=<{type_name}>"


def load_model_info(model_path: Path) -> dict:
    onnx = require_onnx()
    model = onnx.load(str(model_path))
    try:
        inferred = onnx.shape_inference.infer_shapes(model)
    except Exception:
        inferred = model

    graph = inferred.graph
    tensor_proto = onnx.TensorProto
    attribute_proto = onnx.AttributeProto

    initializer_names = {init.name for init in graph.initializer}
    initializer_shapes = {
        init.name: initializer_shape(init, tensor_proto) for init in graph.initializer
    }

    value_shapes = {}
    for value_info in list(graph.input) + list(graph.value_info) + list(graph.output):
        value_shapes[value_info.name] = tensor_shape_from_value_info(value_info, tensor_proto)
    value_shapes.update(initializer_shapes)

    inputs = []
    for value_info in graph.input:
        if value_info.name in initializer_names:
            continue
        inputs.append({
            "name": value_info.name,
            "shape": value_shapes.get(value_info.name, "?"),
        })

    outputs = []
    for value_info in graph.output:
        outputs.append({
            "name": value_info.name,
            "shape": value_shapes.get(value_info.name, "?"),
        })

    nodes = []
    producer_by_value = {}
    for idx, node in enumerate(graph.node):
        name = node.name if node.name else f"{node.op_type}_{idx:03d}"
        attrs = [summarize_attribute(attr, attribute_proto) for attr in node.attribute]
        node_info = {
            "idx": idx,
            "name": name,
            "op_type": node.op_type,
            "domain": node.domain or "ai.onnx",
            "inputs": list(node.input),
            "outputs": list(node.output),
            "attrs": attrs,
            "output_shapes": [value_shapes.get(out, "?") for out in node.output],
        }
        nodes.append(node_info)
        for out in node.output:
            producer_by_value[out] = idx

    consumers_by_value = defaultdict(list)
    for node in nodes:
        for inp in node["inputs"]:
            consumers_by_value[inp].append(node["idx"])

    opsets = []
    for opset in model.opset_import:
        domain = opset.domain if opset.domain else "ai.onnx"
        opsets.append(f"{domain}:{opset.version}")

    return {
        "model_path": str(model_path),
        "graph_name": graph.name or model_path.stem,
        "ir_version": model.ir_version,
        "producer_name": model.producer_name or "(unknown)",
        "producer_version": model.producer_version or "",
        "opsets": opsets,
        "inputs": inputs,
        "outputs": outputs,
        "nodes": nodes,
        "node_count": len(nodes),
        "initializer_count": len(graph.initializer),
        "initializer_names": initializer_names,
        "initializer_shapes": initializer_shapes,
        "value_shapes": value_shapes,
        "producer_by_value": producer_by_value,
        "consumers_by_value": consumers_by_value,
        "op_counts": Counter(node["op_type"] for node in nodes),
    }


def clip_label(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def wrap_label(text: str, width: int = 28, max_lines: int = 4) -> list[str]:
    chunks = []
    for raw_line in str(text).splitlines():
        chunks.extend(textwrap.wrap(raw_line, width=width) or [""])
    if len(chunks) > max_lines:
        chunks = chunks[: max_lines - 1] + ["..."]
    return chunks


def svg_text_lines(lines: list[str], x: float, y: float, klass: str = "") -> str:
    css = f' class="{klass}"' if klass else ""
    out = [f'<text x="{x:.1f}" y="{y:.1f}"{css}>']
    for i, line in enumerate(lines):
        dy = 0 if i == 0 else 15
        out.append(f'<tspan x="{x:.1f}" dy="{dy}">{escape(line)}</tspan>')
    out.append("</text>")
    return "".join(out)


def svg_box(x: float, y: float, w: float, h: float, klass: str, lines: list[str]) -> str:
    out = [
        f'<g class="node {klass}">',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" ry="8"/>',
    ]
    out.append(svg_text_lines(lines, x + 12, y + 24))
    out.append("</g>")
    return "\n".join(out)


def svg_edge(x1: float, y1: float, x2: float, y2: float) -> str:
    mid = (x1 + x2) / 2
    return (
        f'<path class="edge" d="M {x1:.1f} {y1:.1f} '
        f'C {mid:.1f} {y1:.1f}, {mid:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}" />'
    )


def svg_shell(width: float, height: float, body: str) -> str:
    return f'''<svg class="arch-svg" xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" role="img">
<defs>
  <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L0,6 L9,3 z" fill="#475569" />
  </marker>
</defs>
<style>
  .arch-svg {{ background: #f8fafc; border: 1px solid #dbe3ef; border-radius: 10px; }}
  .node rect {{ stroke-width: 1.4; }}
  .node text {{ font: 12px ui-monospace, SFMono-Regular, Consolas, monospace; fill: #0f172a; }}
  .input rect {{ fill: #dcfce7; stroke: #16a34a; }}
  .output rect {{ fill: #fee2e2; stroke: #dc2626; }}
  .op rect {{ fill: #e0f2fe; stroke: #0284c7; }}
  .shared rect {{ fill: #ede9fe; stroke: #7c3aed; }}
  .head rect {{ fill: #fef3c7; stroke: #d97706; }}
  .edge {{ fill: none; stroke: #475569; stroke-width: 1.5; marker-end: url(#arrow); opacity: 0.72; }}
</style>
{body}
</svg>'''


def node_ancestors_for_output(output_name: str, info: dict, memo: dict[int, set[int]]) -> set[int]:
    producer = info["producer_by_value"].get(output_name)
    if producer is None:
        return set()

    def visit(node_idx: int) -> set[int]:
        if node_idx in memo:
            return memo[node_idx]
        node = info["nodes"][node_idx]
        result = {node_idx}
        for inp in node["inputs"]:
            parent = info["producer_by_value"].get(inp)
            if parent is not None:
                result.update(visit(parent))
        memo[node_idx] = result
        return result

    return visit(producer)


def op_summary(info: dict, indices: set[int], max_items: int = 6) -> str:
    if not indices:
        return "0 nodes"
    counts = Counter(info["nodes"][idx]["op_type"] for idx in indices)
    parts = [f"{op}:{count}" for op, count in counts.most_common(max_items)]
    if len(counts) > max_items:
        parts.append("...")
    return f"{len(indices)} nodes | " + ", ".join(parts)


def render_simple_svg(info: dict, config: dict) -> str:
    outputs = info["outputs"]
    memo = {}
    output_ancestors = [
        node_ancestors_for_output(out["name"], info, memo) for out in outputs
    ]
    if output_ancestors:
        common = set.intersection(*output_ancestors)
    else:
        common = set()

    branch_sets = []
    for ancestors in output_ancestors:
        branch_sets.append(ancestors - common)

    width = 1180
    row_gap = 145
    height = max(360, 160 + max(1, len(outputs)) * row_gap)
    box_w = 235
    box_h = 92

    input_name = ", ".join(inp["name"] for inp in info["inputs"]) or "input"
    input_shape = "; ".join(inp["shape"] for inp in info["inputs"]) or "?"

    x_input = 40
    x_shared = 330
    x_head = 625
    x_output = 910
    center_y = height / 2 - box_h / 2

    body = []
    body.append(svg_box(
        x_input,
        center_y,
        box_w,
        box_h,
        "input",
        ["INPUT", clip_label(input_name, 32), clip_label(input_shape, 34)],
    ))
    body.append(svg_box(
        x_shared,
        center_y,
        box_w,
        box_h,
        "shared",
        ["SHARED BACKBONE", op_summary(info, common, 4), "common ancestor nodes"],
    ))
    body.append(svg_edge(x_input + box_w, center_y + box_h / 2, x_shared, center_y + box_h / 2))

    if not outputs:
        return svg_shell(width, height, "\n".join(body))

    first_y = height / 2 - ((len(outputs) - 1) * row_gap) / 2 - box_h / 2
    for idx, out in enumerate(outputs):
        y = first_y + idx * row_gap
        branch = branch_sets[idx]
        title = "BBOX HEAD" if "bbox" in out["name"].lower() else "CONFIDENCE HEAD"
        if "sigmoid" in out["name"].lower() or "cov" in out["name"].lower():
            title = "CONFIDENCE HEAD"
        body.append(svg_box(
            x_head,
            y,
            box_w,
            box_h,
            "head",
            [title, op_summary(info, branch, 4), clip_label(out["name"], 34)],
        ))
        body.append(svg_box(
            x_output,
            y,
            box_w,
            box_h,
            "output",
            ["OUTPUT", clip_label(out["name"], 34), clip_label(out["shape"], 34)],
        ))
        body.append(svg_edge(x_shared + box_w, center_y + box_h / 2, x_head, y + box_h / 2))
        body.append(svg_edge(x_head + box_w, y + box_h / 2, x_output, y + box_h / 2))

    return svg_shell(width, height, "\n".join(body))


def compute_detailed_levels(info: dict) -> tuple[dict[str, int], dict[str, str], dict[str, dict]]:
    value_level = {}
    value_source = {}
    items = {}

    for inp in info["inputs"]:
        key = f"input:{inp['name']}"
        value_level[inp["name"]] = 0
        value_source[inp["name"]] = key
        items[key] = {
            "kind": "input",
            "name": inp["name"],
            "shape": inp["shape"],
            "level": 0,
        }

    for init_name in info["initializer_names"]:
        value_level[init_name] = 0

    for node in info["nodes"]:
        parent_levels = []
        for inp in node["inputs"]:
            if inp in info["initializer_names"]:
                continue
            parent_levels.append(value_level.get(inp, 0))
        level = max(parent_levels or [0]) + 1
        key = f"node:{node['idx']}"
        items[key] = {
            "kind": "node",
            "node": node,
            "level": level,
        }
        for out in node["outputs"]:
            value_level[out] = level
            value_source[out] = key

    max_level = max([item["level"] for item in items.values()] or [0])
    for out in info["outputs"]:
        key = f"output:{out['name']}"
        items[key] = {
            "kind": "output",
            "name": out["name"],
            "shape": out["shape"],
            "level": max_level + 1,
        }
    return value_level, value_source, items


def render_detailed_svg(info: dict, config: dict) -> str:
    _, value_source, items = compute_detailed_levels(info)
    levels = defaultdict(list)
    for key, item in items.items():
        levels[item["level"]].append(key)

    for level in levels:
        levels[level].sort(key=lambda k: (items[k]["kind"], k))

    box_w = 215
    box_h = 86
    x_gap = 70
    y_gap = 34
    margin_x = 36
    margin_y = 36
    max_level = max(levels.keys() or [0])
    max_rows = max((len(v) for v in levels.values()), default=1)
    width = margin_x * 2 + (max_level + 1) * box_w + max_level * x_gap
    height = margin_y * 2 + max_rows * box_h + (max_rows - 1) * y_gap

    positions = {}
    for level in range(max_level + 1):
        level_items = levels.get(level, [])
        total_h = len(level_items) * box_h + max(0, len(level_items) - 1) * y_gap
        y_start = max(margin_y, (height - total_h) / 2)
        x = margin_x + level * (box_w + x_gap)
        for row, key in enumerate(level_items):
            positions[key] = (x, y_start + row * (box_h + y_gap))

    edges = []
    for node in info["nodes"]:
        to_key = f"node:{node['idx']}"
        for inp in node["inputs"]:
            if inp in info["initializer_names"]:
                continue
            from_key = value_source.get(inp)
            if from_key and from_key != to_key:
                edges.append((from_key, to_key))

    for out in info["outputs"]:
        out_key = f"output:{out['name']}"
        from_key = value_source.get(out["name"])
        if from_key:
            edges.append((from_key, out_key))

    body = []
    for from_key, to_key in edges:
        if from_key not in positions or to_key not in positions:
            continue
        x1, y1 = positions[from_key]
        x2, y2 = positions[to_key]
        body.append(svg_edge(x1 + box_w, y1 + box_h / 2, x2, y2 + box_h / 2))

    max_label_length = int(config.get("max_label_length", 72))
    for key, item in items.items():
        x, y = positions[key]
        if item["kind"] == "input":
            lines = [
                "INPUT",
                clip_label(item["name"], max_label_length),
                clip_label(item["shape"], max_label_length),
            ]
            body.append(svg_box(x, y, box_w, box_h, "input", lines))
        elif item["kind"] == "output":
            lines = [
                "OUTPUT",
                clip_label(item["name"], max_label_length),
                clip_label(item["shape"], max_label_length),
            ]
            body.append(svg_box(x, y, box_w, box_h, "output", lines))
        else:
            node = item["node"]
            shape = "; ".join(node["output_shapes"]) if node["output_shapes"] else "?"
            lines = [
                f"#{node['idx']} {node['op_type']}",
                clip_label(node["name"], max_label_length),
                clip_label(shape, max_label_length),
            ]
            body.append(svg_box(x, y, box_w, box_h, "op", lines))

    return svg_shell(width, height, "\n".join(body))


def table_rows(rows: list[list[str]]) -> str:
    out = []
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>")
    return "\n".join(out)


def op_counts_table(info: dict) -> str:
    rows = [[op, str(count)] for op, count in info["op_counts"].most_common()]
    return table_rows(rows)


def node_table(info: dict) -> str:
    rows = []
    for node in info["nodes"]:
        rows.append([
            str(node["idx"]),
            node["op_type"],
            node["name"],
            "\n".join(node["inputs"]),
            "\n".join(node["outputs"]),
            "\n".join(node["output_shapes"]),
            "; ".join(node["attrs"]),
        ])
    return table_rows(rows)


def io_table(items: list[dict]) -> str:
    return table_rows([[item["name"], item["shape"]] for item in items])


def render_html(info: dict, config: dict, mode: str, svg: str) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    detailed = mode == "detailed"
    title = config.get("page_title", "ONNX Neural Network Architecture")
    mode_label = "详细版" if detailed else "简介版"
    node_table_html = node_table(info) if detailed else ""

    detail_section = ""
    if detailed:
        detail_section = f"""
<section class="panel">
  <div class="section-head">
    <h2>ONNX 节点明细</h2>
    <input id="nodeFilter" placeholder="搜索 op / 节点名 / tensor 名" oninput="filterRows()" />
  </div>
  <div class="table-wrap">
    <table id="nodeTable">
      <thead>
        <tr><th>#</th><th>Op</th><th>Name</th><th>Inputs</th><th>Outputs</th><th>Output Shapes</th><th>Attributes</th></tr>
      </thead>
      <tbody>
        {node_table_html}
      </tbody>
    </table>
  </div>
</section>
"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)} - {mode_label}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef2f7;
      --panel: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --line: #dbe3ef;
      --accent: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 24px 28px 14px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    .sub {{ color: var(--muted); }}
    main {{ padding: 22px 28px 34px; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .card b {{ display: block; font-size: 21px; }}
    .card span {{ color: var(--muted); }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      margin-top: 16px;
    }}
    .diagram-wrap {{
      overflow: auto;
      max-height: 76vh;
      border-radius: 10px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      min-width: 680px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
      white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
    }}
    th {{
      background: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 12px;
      color: #334155;
      position: sticky;
      top: 0;
    }}
    .table-wrap {{ overflow: auto; max-height: 62vh; }}
    .section-head {{
      display: flex;
      align-items: center;
      gap: 12px;
      justify-content: space-between;
      margin-bottom: 10px;
    }}
    input {{
      width: min(420px, 100%);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
    }}
    code {{
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 4px;
      padding: 1px 5px;
    }}
    .links a {{
      color: var(--accent);
      text-decoration: none;
      margin-right: 14px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <div class="sub">模式：{mode_label} | 生成时间：{escape(generated)} | 模型：<code>{escape(info["model_path"])}</code></div>
    <div class="links">
      <a href="fd_lpd_architecture_simple.html">简介版</a>
      <a href="fd_lpd_architecture_detailed.html">详细版</a>
      <a href="fd_lpd_summary.md">Markdown 摘要</a>
      <a href="fd_lpd_architecture.svg">SVG 图</a>
    </div>
  </header>
  <main>
    <section class="cards">
      <div class="card"><b>{info["node_count"]}</b><span>ONNX 节点</span></div>
      <div class="card"><b>{len(info["op_counts"])}</b><span>Op 类型</span></div>
      <div class="card"><b>{len(info["inputs"])}</b><span>输入</span></div>
      <div class="card"><b>{len(info["outputs"])}</b><span>输出</span></div>
      <div class="card"><b>{info["initializer_count"]}</b><span>权重 tensors</span></div>
    </section>

    <section class="panel">
      <h2>网络架构图</h2>
      <div class="diagram-wrap">
        {svg}
      </div>
    </section>

    <section class="panel">
      <h2>输入</h2>
      <div class="table-wrap">
        <table><thead><tr><th>Name</th><th>Shape</th></tr></thead><tbody>{io_table(info["inputs"])}</tbody></table>
      </div>
    </section>

    <section class="panel">
      <h2>输出</h2>
      <div class="table-wrap">
        <table><thead><tr><th>Name</th><th>Shape</th></tr></thead><tbody>{io_table(info["outputs"])}</tbody></table>
      </div>
    </section>

    <section class="panel">
      <h2>Op 统计</h2>
      <div class="table-wrap">
        <table><thead><tr><th>Op Type</th><th>Count</th></tr></thead><tbody>{op_counts_table(info)}</tbody></table>
      </div>
    </section>

    {detail_section}
  </main>
  <script>
    function filterRows() {{
      const input = document.getElementById('nodeFilter');
      const table = document.getElementById('nodeTable');
      if (!input || !table) return;
      const q = input.value.toLowerCase();
      for (const row of table.tBodies[0].rows) {{
        row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
      }}
    }}
  </script>
</body>
</html>
"""


def markdown_summary(info: dict, config: dict) -> str:
    lines = []
    lines.append(f"# {config.get('page_title', 'ONNX Model Summary')}")
    lines.append("")
    lines.append(f"- Model: `{info['model_path']}`")
    lines.append(f"- Graph: `{info['graph_name']}`")
    lines.append(f"- IR version: `{info['ir_version']}`")
    lines.append(f"- Producer: `{info['producer_name']} {info['producer_version']}`")
    lines.append(f"- Opsets: `{', '.join(info['opsets'])}`")
    lines.append(f"- Nodes: `{info['node_count']}`")
    lines.append(f"- Initializers: `{info['initializer_count']}`")
    lines.append("")

    lines.append("## Inputs")
    lines.append("")
    lines.append("| Name | Shape |")
    lines.append("| --- | --- |")
    for item in info["inputs"]:
        lines.append(f"| `{item['name']}` | `{item['shape']}` |")
    lines.append("")

    lines.append("## Outputs")
    lines.append("")
    lines.append("| Name | Shape |")
    lines.append("| --- | --- |")
    for item in info["outputs"]:
        lines.append(f"| `{item['name']}` | `{item['shape']}` |")
    lines.append("")

    lines.append("## Op Counts")
    lines.append("")
    lines.append("| Op Type | Count |")
    lines.append("| --- | ---: |")
    for op, count in info["op_counts"].most_common():
        lines.append(f"| `{op}` | {count} |")
    lines.append("")

    lines.append("## Generated Files")
    lines.append("")
    lines.append(f"- Main HTML: `{config['main_html']}`")
    lines.append(f"- Simple HTML: `{config['simple_html']}`")
    lines.append(f"- Detailed HTML: `{config['detailed_html']}`")
    lines.append(f"- SVG: `{config['diagram_svg']}`")
    return "\n".join(lines) + "\n"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def generate_outputs(config_path: Path, cli_detailed: str | None = None) -> None:
    config = load_config(config_path)
    base_dir = config_path.parent
    if cli_detailed is not None:
        config["detailed"] = cli_detailed.lower() == "true"

    model_path = resolve_path(config["model_path"], base_dir)
    output_dir = resolve_path(config["output_dir"], base_dir)

    if not model_path.exists():
        raise SystemExit(f"ERROR: ONNX model not found: {model_path}")

    info = load_model_info(model_path)

    selected_mode = "detailed" if bool(config.get("detailed")) else "simple"
    modes_to_write = [(selected_mode, config["main_html"])]
    if config.get("generate_both_modes", True):
        modes_to_write.append(("simple", config["simple_html"]))
        modes_to_write.append(("detailed", config["detailed_html"]))

    selected_svg = None
    for mode, filename in modes_to_write:
        svg = render_detailed_svg(info, config) if mode == "detailed" else render_simple_svg(info, config)
        html = render_html(info, config, mode, svg)
        write_text(output_dir / filename, html)
        if mode == selected_mode:
            selected_svg = svg

    if selected_svg is None:
        selected_svg = render_simple_svg(info, config)
    write_text(output_dir / config["diagram_svg"], selected_svg)
    write_text(output_dir / config["summary_markdown"], markdown_summary(info, config))

    print("Model architecture viewer generated.")
    print(f"  Model:  {model_path}")
    print(f"  Output: {output_dir}")
    print(f"  Main:   {output_dir / config['main_html']}")
    if config.get("generate_both_modes", True):
        print(f"  Simple: {output_dir / config['simple_html']}")
        print(f"  Detail: {output_dir / config['detailed_html']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an ONNX model architecture web viewer.")
    parser.add_argument("--config", default="viewer_config.json", help="Path to viewer config JSON.")
    parser.add_argument(
        "--detailed",
        choices=["true", "false"],
        default=None,
        help="Override config detailed mode. true=detailed, false=simple.",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    generate_outputs(config_path, args.detailed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
