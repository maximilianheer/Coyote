#!/usr/bin/env python3
"""Draw the background threat model as editable PowerPoint and vector PDF.

Adapted from slide 4 of the hls4ml talk. Both outputs use the same geometry.
Requires python-pptx, matplotlib, and their dependencies; no raster artwork.
"""

import os
import re
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

os.environ.setdefault("MPLCONFIGDIR", "/tmp/paper-background-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, PathPatch
from matplotlib.path import Path as VectorPath
from matplotlib.transforms import Affine2D
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt


OUTPUT = Path(__file__).resolve().parent / "figures"
WIDTH, HEIGHT = 11.6, 5.35
ICON_SOURCE = OUTPUT.parent.parent / "[hls4ml] ML-Based Deep Bitstream Inspection for Serverless FPGAs .pptx"
INK = "243746"
BLUE = "24627B"
TEAL = "2E7E94"
GREEN = "467944"
RED = "B84D32"
GRAY = "65717C"


def svg_path(data):
    """Read the absolute M/L/C/Z paths used by the supplied Office icons."""
    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", data)
    vertices, codes = [], []
    index = 0
    command = None
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if command == "Z":
            vertices.append((0, 0))
            codes.append(VectorPath.CLOSEPOLY)
            command = None
            continue
        count = {"M": 2, "L": 2, "C": 6}.get(command)
        if count is None:
            raise ValueError(f"Unsupported icon path command: {command}")
        points = list(map(float, tokens[index:index + count]))
        index += count
        vertices.extend(zip(points[::2], points[1::2]))
        code = {"M": VectorPath.MOVETO, "L": VectorPath.LINETO, "C": VectorPath.CURVE4}[command]
        codes.extend([code] * (count // 2))
        if command == "M":
            command = "L"
    return VectorPath(vertices, codes)


def icon_paths(number):
    """Extract vector geometry, preserving the original icon outlines."""
    with ZipFile(ICON_SOURCE) as archive:
        root = ET.fromstring(archive.read(f"ppt/media/image{number}.svg"))
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "path":
            yield svg_path(element.attrib["d"])
        elif tag == "circle":
            transform = Affine2D().scale(float(element.attrib["r"])).translate(
                float(element.attrib["cx"]), float(element.attrib["cy"])
            )
            yield transform.transform_path(VectorPath.unit_circle())
        elif tag == "rect":
            transform = Affine2D().scale(
                float(element.attrib["width"]), float(element.attrib["height"])
            ).translate(float(element.attrib["x"]), float(element.attrib["y"]))
            yield transform.transform_path(VectorPath.unit_rectangle())


class Diagram:
    """Mirror native slide shapes and text with Matplotlib vector objects."""

    def __init__(self, width=WIDTH, height=HEIGHT):
        self.presentation = Presentation()
        self.presentation.slide_width = Inches(width)
        self.presentation.slide_height = Inches(height)
        self.slide = self.presentation.slides.add_slide(
            self.presentation.slide_layouts[6]
        )
        self.figure = plt.figure(figsize=(width, height))
        self.axis = self.figure.add_axes([0, 0, 1, 1])
        self.axis.set_xlim(0, width)
        self.axis.set_ylim(height, 0)
        self.axis.set_axis_off()

    def icon(self, name, number, x, y, size, color):
        self.path_group(name, icon_paths(number), x, y, size, color)

    def path_group(self, name, outlines, x, y, size, color, filled=True):
        """Use editable DrawingML curves in PowerPoint and paths in the PDF."""
        shapes = []
        for outline in outlines:
            shape = self.slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(size), Inches(size)
            )
            if filled:
                shape.fill.solid()
                shape.fill.fore_color.rgb = RGBColor.from_string(color)
                shape.line.fill.background()
            else:
                shape.fill.background()
                shape.line.color.rgb = RGBColor.from_string(color)
                shape.line.width = Pt(1.2)
            properties = shape._element.spPr
            properties.remove(properties.find("{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom"))
            geometry = OxmlElement("a:custGeom")
            for tag in ["avLst", "gdLst", "ahLst", "cxnLst"]:
                geometry.append(OxmlElement(f"a:{tag}"))
            rectangle = OxmlElement("a:rect")
            for key, value in {"l": "0", "t": "0", "r": "r", "b": "b"}.items():
                rectangle.set(key, value)
            geometry.append(rectangle)
            paths = OxmlElement("a:pathLst")
            path = OxmlElement("a:path")
            path.set("w", "96000")
            path.set("h", "96000")
            path.set("stroke", "0" if filled else "1")
            path.set("fill", "norm" if filled else "none")
            for coordinates, code in outline.iter_segments(curves=True):
                tag = {
                    VectorPath.MOVETO: "moveTo", VectorPath.LINETO: "lnTo",
                    VectorPath.CURVE4: "cubicBezTo", VectorPath.CLOSEPOLY: "close",
                }[code]
                segment = OxmlElement(f"a:{tag}")
                if code != VectorPath.CLOSEPOLY:
                    for px, py in zip(coordinates[::2], coordinates[1::2]):
                        point = OxmlElement("a:pt")
                        point.set("x", str(round(px * 1000)))
                        point.set("y", str(round(py * 1000)))
                        segment.append(point)
                path.append(segment)
            paths.append(path)
            geometry.append(paths)
            properties.insert(1, geometry)
            shapes.append(shape)
            positioned = Affine2D().scale(size / 96).translate(x, y).transform_path(outline)
            self.axis.add_patch(PathPatch(
                positioned, facecolor=f"#{color}" if filled else "none",
                edgecolor="none" if filled else f"#{color}", linewidth=1.2,
            ))
        group = self.slide.shapes.add_group_shape(shapes)
        group.name = name

    def fpga_icon(self, x, y, size):
        """Adapt the talk's native logic-gate FPGA symbol (slide 7, group 119)."""
        presentation = Presentation(ICON_SOURCE)
        source = next(shape for shape in presentation.slides[6].shapes if shape.shape_id == 119)
        outlines = []
        # Crop to the chip and pins, excluding a stray line below the source icon.
        left, top, width = 949322, 419570, 1205313
        for shape in source.shapes:
            if shape.top > 1000000:
                continue
            properties = shape._element.spPr
            geometry = properties.find("{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom")
            kind = geometry.get("prst")
            if kind == "rect":
                # Small source rectangles have neither fill nor stroke.
                continue
            if kind == "line":
                outline = VectorPath([(0, 0), (1, 1)], [VectorPath.MOVETO, VectorPath.LINETO])
            elif kind == "bentConnector3":
                outline = VectorPath([(0, 0), (0.5, 0), (0.5, 1), (1, 1)],
                                     [VectorPath.MOVETO] + [VectorPath.LINETO] * 3)
            elif kind == "roundRect":
                outline = svg_path("M.08 0 L.92 0 C.97 0 1 .05 1 .12 L1 .88 C1 .95 .97 1 .92 1 L.08 1 C.03 1 0 .95 0 .88 L0 .12 C0 .05 .03 0 .08 0 Z")
            elif kind == "flowChartDelay":
                outline = svg_path("M0 0 L.5 0 C.776 0 1 .224 1 .5 C1 .776 .776 1 .5 1 L0 1 Z")
            elif kind == "snip2SameRect":
                outline = svg_path("M.18 0 L.82 0 L1 .18 L1 1 L0 1 L0 .18 Z")
            else:
                raise ValueError(f"Unsupported FPGA icon shape: {kind}")
            transform = Affine2D()
            xfrm = properties.xfrm
            if xfrm.get("flipV") == "1":
                transform.scale(1, -1).translate(0, 1)
            if xfrm.get("flipH") == "1":
                transform.scale(-1, 1).translate(1, 0)
            transform.scale(shape.width, shape.height).translate(-shape.width / 2, -shape.height / 2)
            transform.rotate_deg(shape.rotation).translate(shape.left + shape.width / 2, shape.top + shape.height / 2)
            transform.translate(-left, -top).scale(96 / width).translate(0, 24)
            outlines.append(transform.transform_path(outline))
        self.path_group("FPGA logic-gate icon from presentation", outlines, x, y, size, BLUE, filled=False)

    def thermometer(self, x, y, size):
        outer = svg_path("M38 14 C38 0 58 0 58 14 L58 57 C81 72 69 94 48 94 C27 94 15 72 38 57 Z")
        stem = svg_path("M45 26 L51 26 L51 67 C65 72 62 86 48 86 C34 86 31 72 45 67 Z")
        ticks = svg_path("M64 22 L78 22 L78 27 L64 27 Z M64 37 L73 37 L73 42 L64 42 Z M64 52 L78 52 L78 57 L64 57 Z")
        self.path_group("Thermometer outline", [outer], x, y, size, RED, filled=False)
        self.path_group("Thermometer mercury and marks", [stem, ticks], x, y, size, RED)

    def box(self, name, x, y, width, height, fill, edge, linewidth=1.2):
        shape = self.slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(x), Inches(y), Inches(width), Inches(height),
        )
        shape.name = name
        shape.adjustments[0] = 0.10
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(fill)
        shape.line.color.rgb = RGBColor.from_string(edge)
        shape.line.width = Pt(linewidth)
        self.axis.add_patch(FancyBboxPatch(
            (x, y), width, height,
            boxstyle="round,pad=0,rounding_size=0.07",
            facecolor=f"#{fill}", edgecolor=f"#{edge}", linewidth=linewidth,
        ))

    def text(self, name, text, x, y, width, height, size=18, color=INK,
             bold=False, align="center"):
        shape = self.slide.shapes.add_textbox(
            Inches(x), Inches(y), Inches(width), Inches(height)
        )
        shape.name = name
        frame = shape.text_frame
        frame.clear()
        frame.margin_left = frame.margin_right = 0
        frame.margin_top = frame.margin_bottom = 0
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        frame.word_wrap = False
        for index, line in enumerate(text.split("\n")):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = line
            paragraph.alignment = PP_ALIGN.CENTER if align == "center" else PP_ALIGN.LEFT
            paragraph.space_before = paragraph.space_after = Pt(0)
            paragraph.font.name = "Arial"
            paragraph.font.size = Pt(size)
            paragraph.font.bold = bold
            paragraph.font.color.rgb = RGBColor.from_string(color)
        self.axis.text(
            x + width / 2 if align == "center" else x, y + height / 2,
            text, fontsize=size, color=f"#{color}",
            weight="bold" if bold else "normal", ha=align, va="center",
            linespacing=1.15,
        )

    def arrow(self, name, points, color=GRAY, dashed=False, head=True):
        for index, (start, end) in enumerate(zip(points, points[1:])):
            connector = self.slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT,
                Inches(start[0]), Inches(start[1]),
                Inches(end[0]), Inches(end[1]),
            )
            connector.name = f"{name} segment {index + 1}"
            connector.line.color.rgb = RGBColor.from_string(color)
            connector.line.width = Pt(1.7)
            line = connector._element.spPr.get_or_add_ln()
            if dashed:
                dash = OxmlElement("a:prstDash")
                dash.set("val", "dash")
                line.append(dash)
            last = index == len(points) - 2
            if last and head:
                arrowhead = OxmlElement("a:tailEnd")
                arrowhead.set("type", "triangle")
                arrowhead.set("w", "med")
                arrowhead.set("len", "med")
                line.append(arrowhead)
            self.axis.add_patch(FancyArrowPatch(
                start, end, arrowstyle="-|>" if last and head else "-",
                mutation_scale=14, linewidth=1.7, color=f"#{color}",
                linestyle=(0, (4, 3)) if dashed else "solid",
                shrinkA=0, shrinkB=0,
            ))

    def save(self):
        OUTPUT.mkdir(exist_ok=True)
        stem = OUTPUT / "background_threat_model"
        self.presentation.core_properties.title = "Threat model and proposed inspection gate"
        self.presentation.core_properties.subject = "Background figure with reusable assets from the editable hls4ml talk"
        self.slide.notes_slide.notes_text_frame.text = (
            "Adapted from slide 4 of the editable hls4ml talk, with its happy face, "
            "devil face, binary, shield, gears, lightning, and scorpion icons. "
            "The FPGA symbol adapts slide 7 group 119; the thermometer is newly drawn. Icons are "
            "editable grouped freeform shapes; ungroup to edit individual paths. "
            "The complete inspection-to-PR "
            "admission path is proposed; the checker itself is implemented and evaluated. "
            "Dashed red arrows represent physical effects if malicious logic is admitted, "
            "not a direct logical connection or a bypass of inspection. All diagram "
            "objects are editable PowerPoint shapes, text boxes, and connectors. "
            "After editing, export this slide as PDF to update the paper asset."
        )
        # Prevent Office theme effects and autosizing from changing the flat
        # vector style when this editable source is exported from PowerPoint.
        def flatten_theme(shapes):
            for shape in shapes:
                if hasattr(shape, "shapes"):
                    flatten_theme(shape.shapes)
                    continue
                if not shape._element.spPr.xpath("./a:effectLst"):
                    shape._element.spPr.append(OxmlElement("a:effectLst"))
                for effect in shape._element.xpath("./p:style/a:effectRef"):
                    effect.set("idx", "0")
                if shape.has_text_frame:
                    shape.text_frame.auto_size = MSO_AUTO_SIZE.NONE

        flatten_theme(self.slide.shapes)
        self.presentation.save(stem.with_suffix(".pptx"))
        self.figure.savefig(stem.with_suffix(".pdf"))
        self.figure.savefig(stem.with_suffix(".png"), dpi=220)
        plt.close(self.figure)
        print(f"Created editable PowerPoint, vector PDF, and PNG at {stem}")


def main():
    from generate_coyote_benchmark_setup import box, fpga_icon

    plt.rcParams.update({"font.family": "Liberation Sans", "pdf.fonttype": 42})
    d = Diagram()
    box(d, "FPGA boundary", 3.12, 0.12, 8.20, 5.04, dashed=True)
    fpga_icon(d, 3.38, 0.27, 0.90)
    d.text("FPGA label", "FPGA", 4.56, 0.38, 1.45, 0.40,
           size=23, bold=True, color="000000", align="left")

    d.icon("Benign smiling face", 11, 0.40, 1.10, 0.64, "2D7C99")
    d.icon("Benign bitstream icon", 10, 1.34, 1.15, 0.56, "2D7C99")
    d.text("Benign tenant label", "Benign tenant", 0.18, 1.86, 2.10, 0.35,
           size=18, color="000000")
    d.icon("Malicious horned face", 7, 0.40, 3.20, 0.64, RED)
    d.icon("Malicious bitstream icon", 9, 1.34, 3.25, 0.56, RED)
    d.text("Malicious tenant label", "Malicious RO design", 0.08, 3.98, 2.43, 0.40,
           size=17, color=RED)

    d.icon("Inspection shield icon", 8, 4.36, 1.05, 0.68, TEAL)
    box(d, "Inspection", 3.50, 1.94, 2.40, 1.02, "2D7C99")
    d.text("Inspection label", "Bitstream\ninspection", 3.60, 2.03, 2.20, 0.84,
           size=20, color="FFFFFF")
    d.icon("Reconfiguration gears", 12, 8.34, 1.05, 0.70, GREEN)
    box(d, "Partial reconfiguration", 7.30, 1.94, 2.80, 1.02, "C9E5A8")
    d.text("PR label", "Partial\nreconfiguration", 7.40, 2.03, 2.60, 0.84,
           size=20, color="000000")

    d.arrow("Benign submission", [(2.08, 1.47), (2.73, 1.47),
            (2.73, 2.45), (3.50, 2.45)], "000000")
    d.arrow("Malicious submission", [(2.08, 3.57), (2.73, 3.57),
            (2.73, 2.45)], RED, head=False)
    d.arrow("Allow", [(5.90, 2.45), (7.30, 2.45)], GREEN)
    d.text("Allow label", "Allow", 6.08, 2.05, 1.05, 0.30, size=17, color=GREEN)
    d.arrow("Reject", [(4.70, 2.96), (4.70, 3.72)], RED)
    d.text("Rejection label", "Reject / log", 3.65, 3.85, 2.10, 0.40,
           size=19, color=RED)

    d.arrow("Physical effects", [(8.70, 2.96), (8.70, 3.65)], RED, dashed=True)
    d.text("Conditional effects label", "If malicious logic\nis admitted",
           6.95, 3.16, 1.57, 0.48, size=13, color=RED)
    box(d, "Shared resource effects", 6.55, 3.72, 4.48, 1.15, "F9EEEE")
    d.icon("Power stress lightning", 13, 7.04, 3.86, 0.49, RED)
    d.thermometer(8.56, 3.86, 0.49)
    d.icon("Tenant harm scorpion", 14, 10.00, 3.86, 0.49, RED)
    d.text("Power effects label", "Power stress", 6.60, 4.44, 1.37, 0.28, size=15, color=RED)
    d.text("Heat effects label", "Heating", 8.15, 4.44, 1.30, 0.28, size=15, color=RED)
    d.text("Tenant effects label", "Faults / DoS", 9.58, 4.44, 1.38, 0.28, size=15, color=RED)
    d.save()


if __name__ == "__main__":
    main()
