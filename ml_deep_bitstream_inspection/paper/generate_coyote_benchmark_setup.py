#!/usr/bin/env python3
"""Figure 4 drawing in Figure 3's Coyote style, using its original vector icons."""

import re
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from matplotlib.path import Path as VectorPath
from matplotlib.patches import Rectangle
from matplotlib.transforms import Affine2D
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from generate_background_figure import Diagram, plt, svg_path

SOURCE = Path(__file__).resolve().parent.parent / "coyote-figure.pptx"
BLACK = "000000"
OUTLINE = "042433"
TEAL = "2D7C99"
MEMORY = "C9E5A8"
SOFTWARE = "E6B784"
GRAY = "D9D9D9"


def box(d, name, x, y, width, height, fill=None, dashed=False):
    shape = d.slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(width), Inches(height)
    )
    shape.name = name
    if fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(fill)
    else:
        shape.fill.background()
    shape.line.color.rgb = RGBColor.from_string(OUTLINE if dashed else BLACK)
    shape.line.width = Pt(1.25)
    if dashed:
        dash = OxmlElement("a:prstDash")
        dash.set("val", "dash")
        shape._element.spPr.get_or_add_ln().append(dash)
    d.axis.add_patch(Rectangle(
        (x, y), width, height, facecolor=f"#{fill}" if fill else "none",
        edgecolor=f"#{OUTLINE}" if dashed else "black", linewidth=1.25,
        linestyle=(0, (5, 4)) if dashed else "solid",
    ))


def text(d, name, content, x, y, width, height, size=16, bold=False, color=BLACK):
    d.text(name, content, x, y, width, height, size=size, bold=bold, color=color)


def icon(d, name, number, x, y, width):
    """Convert the original Office SVG to editable paths without rasterizing.

The selected source icons use paths, rectangles, circles, lines and translated
containers. Unsupported geometry fails explicitly instead of silently vanishing.
"""
    with ZipFile(SOURCE) as archive:
        root = ET.fromstring(archive.read(f"ppt/media/image{number}.svg"))
    view = root.get("viewBox")
    if view:
        left, top, span, _ = map(float, view.split())
    else:
        left, top, span = 0.0, 0.0, float(root.get("width"))
    normalize = Affine2D().translate(-left, -top).scale(96 / span)

    def walk(node, tx=0.0, ty=0.0, fill="black", stroke="none"):
        fill = node.get("fill", fill)
        stroke = node.get("stroke", stroke)
        transform = node.get("transform")
        if transform:
            match = re.fullmatch(r"translate\(([-.\d]+)[ ,]+([-.\d]+)\)", transform)
            if not match:
                raise ValueError(f"Unsupported icon transform: {transform}")
            tx += float(match[1])
            ty += float(match[2])
        tag = node.tag.rsplit("}", 1)[-1]
        path = None
        if tag == "path":
            path = svg_path(node.get("d"))
        elif tag == "circle":
            path = Affine2D().scale(float(node.get("r"))).translate(
                float(node.get("cx")), float(node.get("cy"))
            ).transform_path(VectorPath.unit_circle())
        elif tag == "rect":
            path = Affine2D().scale(float(node.get("width")), float(node.get("height"))).translate(
                float(node.get("x", 0)), float(node.get("y", 0))
            ).transform_path(VectorPath.unit_rectangle())
        elif tag == "line":
            path = VectorPath([(float(node.get("x1")), float(node.get("y1"))),
                               (float(node.get("x2")), float(node.get("y2")))])
        elif tag not in {"svg", "g", "style"}:
            raise ValueError(f"Unsupported icon element: {tag}")
        if path is not None:
            path = (Affine2D().translate(tx, ty) + normalize).transform_path(path)
            if fill != "none" and tag != "line":
                color = "000000" if fill == "black" else fill.lstrip("#")
                d.path_group(name + " fill", [path], x, y, width, color)
            if stroke != "none":
                d.path_group(name + " outline", [path], x, y, width, stroke.lstrip("#"), filled=False)
        for child in node:
            walk(child, tx, ty, fill, stroke)

    walk(root)


def fpga_icon(d, x, y, size):
    # Reuse the same native logic-gate FPGA artwork as Figure 3.
    old_count = len(d.axis.patches)
    d.fpga_icon(x, y, size)
    group = d.slide.shapes[-1]
    for shape in group.shapes:
        shape.line.color.rgb = RGBColor(0, 0, 0)
    for patch in list(d.axis.patches)[old_count:]:
        patch.set_edgecolor("black")


def gpu_icon(d, x, y, size):
    outlines = [svg_path("M2 16 L90 16 L90 72 L2 72 Z M9 75 L76 75 L76 84 L9 84 Z"),
                svg_path("M65 29 L83 29 L83 59 L65 59 Z")]
    outlines.append(Affine2D().scale(19).translate(32, 44).transform_path(VectorPath.unit_circle()))
    outlines.append(Affine2D().scale(5).translate(32, 44).transform_path(VectorPath.unit_circle()))
    outlines += [svg_path("M32 25 L32 39 M51 44 L37 44 M32 63 L32 49 M13 44 L27 44"),
                 svg_path("M18 31 L28 40 M46 31 L36 40 M46 57 L36 48 M18 57 L28 48")]
    d.path_group("GPU card and cooling fan", outlines, x, y, size, BLACK, filled=False)


def mailbox_icon(d, x, y, size):
    d.path_group("Verdict mailbox envelope", [svg_path(
        "M4 18 L92 18 L92 78 L4 78 Z M4 18 L48 51 L92 18 M4 78 L33 43 M92 78 L63 43"
    )], x, y, size, BLACK, filled=False)


def draw_setup(save):
    plt.rcParams.update({"font.family": "Liberation Sans", "pdf.fonttype": 42})
    d = Diagram(width=11.0, height=6.65)
    text(d, "Title", "Local inspection versus GPU offloading", 0.3, 0.05, 10.4, 0.4, 23, True)
    box(d, "Host control boundary", 0.45, 0.65, 10.1, 0.85, dashed=True)
    icon(d, "Host processor", 2, 0.62, 0.79, 0.58)
    text(d, "Host CPU label", "Host CPU", 1.30, 0.91, 1.5, 0.30, 19, True)
    box(d, "Host software", 3.05, 0.84, 7.20, 0.48, SOFTWARE)
    text(d, "Host software label", "Preload / start control · CPU dispatches GPU inference",
         3.15, 0.92, 7.0, 0.30, 16)

    box(d, "FPGA device boundary", 0.25, 2.15, 5.4, 4.05, dashed=True)
    fpga_icon(d, 0.58, 2.24, 0.65)
    text(d, "FPGA heading", "U55C FPGA", 1.40, 2.26, 3.65, 0.30, 21, True)
    text(d, "FPGA link", "PCIe Gen3 ×16 · NUMA 1", 1.40, 2.62, 3.65, 0.25, 14)
    box(d, "GPU device boundary", 7.15, 2.15, 3.6, 4.05, dashed=True)
    gpu_icon(d, 7.38, 2.20, 0.58)
    text(d, "GPU heading", "MI210 GPU", 8.16, 2.26, 2.35, 0.30, 21, True)
    text(d, "GPU link", "PCIe Gen4 ×16 · NUMA 0", 7.35, 2.76, 3.20, 0.25, 14)

    d.arrow("Preload control", [(0.8, 1.50), (0.45, 1.65), (0.45, 3.45), (0.70, 3.45)],
            BLACK, dashed=True)
    text(d, "Untimed preload label", "PCIe preload (untimed)", 0.9, 1.70, 3.8, 0.28, 15)
    d.arrow("GPU dispatch control", [(10.2, 1.50), (10.92, 1.65),
                                       (10.92, 4.51), (10.45, 4.51)], BLACK, dashed=True)
    text(d, "GPU dispatch label", "GPU dispatch (control)", 7.3, 1.70, 3.3, 0.28, 15)

    box(d, "HBM storage", 0.70, 3.08, 4.50, 0.77, MEMORY)
    icon(d, "Original HBM memory", 4, 0.88, 3.32, 0.85)
    text(d, "HBM label", "HBM\nComplete bitstream", 1.90, 3.18, 3.05, 0.56, 18)
    box(d, "GPU input storage", 7.45, 3.08, 3.0, 0.77, MEMORY)
    icon(d, "Raw bitstream", 8, 7.59, 3.23, 0.46)
    text(d, "GPU input label", "Complete input", 8.12, 3.29, 2.17, 0.32, 17)
    d.arrow("Full input P2P", [(5.20, 3.46), (7.45, 3.46)], BLACK)
    text(d, "P2P transfer label", "Full input\nPCIe P2P", 5.53, 2.90, 1.50, 0.48, 15)

    d.arrow("Selected reads", [(4.75, 3.85), (4.75, 4.22)], BLACK)
    text(d, "Selected reads label", "Selected 64-byte words", 0.85, 3.94, 3.55, 0.22, 14)
    box(d, "Local CNN checker", 0.70, 4.22, 4.50, 0.83, TEAL)
    icon(d, "Original neural network", 5, 0.83, 4.33, 0.62)
    text(d, "Checker label", "FPGA_HLS4ML\nPreprocess → quantized CNN",
         1.56, 4.33, 3.48, 0.58, 16, color="FFFFFF")
    d.arrow("GPU input to compute", [(8.95, 3.85), (8.95, 4.12)], BLACK)
    box(d, "GPU inference", 7.45, 4.12, 3.0, 0.95, TEAL)
    icon(d, "GPU neural network", 5, 7.57, 4.30, 0.52)
    text(d, "GPU inference label", "GPU_P2P\nFloat preprocess + CNN\nXLA + ConcreteFunction",
         8.12, 4.22, 2.22, 0.72, 12.5, color="FFFFFF")

    d.arrow("Local verdict", [(3.0, 5.05), (3.0, 5.48)], BLACK)
    box(d, "FPGA verdict", 0.70, 5.48, 4.50, 0.53, GRAY)
    icon(d, "Original verdict shield", 6, 0.84, 5.54, 0.40)
    text(d, "FPGA verdict label", "FPGA verdict timestamp\nLocal result / autonomous polling",
         1.38, 5.52, 3.65, 0.43, 14)
    d.arrow("GPU publishes verdict", [(8.95, 5.07), (8.95, 5.48)], BLACK)
    box(d, "GPU verdict mailbox", 7.45, 5.48, 3.0, 0.53, GRAY)
    mailbox_icon(d, 7.60, 5.54, 0.40)
    text(d, "GPU mailbox label", "Verdict mailbox", 8.12, 5.59, 2.14, 0.27, 16)
    d.arrow("P2P verdict return", [(7.45, 5.745), (5.20, 5.745)], BLACK)
    text(d, "P2P verdict label", "P2P verdict\nreadback", 5.53, 5.18, 1.5, 0.48, 15)
    text(d, "Timing scope", "Two paths measured separately; the complete bitstream is locally available before timing.",
         0.3, 6.34, 10.4, 0.25, 14)
    save(d, "benchmark_local_setup", "Figure 4 uses the Figure 3 Coyote style: dashed device boundaries, "
         "green memory blocks, teal checker blocks, gray result blocks, black connectors, Arial text. "
         "CPU, HBM, neural-network, binary and shield geometry is reused from coyote-figure.pptx; "
         "the native FPGA logic-gate symbol matches Figure 3. GPU card and mailbox are editable vector shapes. "
         "All text, icons, blocks and arrows remain editable. The host preloads outside timing and "
         "dispatches GPU inference. FPGA polling is autonomous. Logical routes do not claim a "
         "verified switch topology or fully hostless execution. PowerPoint edits can be exported as PDF.")
