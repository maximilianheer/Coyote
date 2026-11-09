#!/usr/bin/env python3
"""Adapt the original Coyote slide to highlight standalone inspection and PR.

Retain editable Coyote blocks and icons, enlarge the FPGA at paper scale,
and highlight networking, HBM staging, checker verdict, and PR admission.
PDF export uses LibreOffice or can be done manually in PowerPoint.
"""

import argparse
from copy import deepcopy
from pathlib import Path
import subprocess

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "coyote-figure.pptx"
OUTPUT = ROOT / "paper/figures/coyote_network_standalone.pptx"
BLUE = "2D7C99"
HIGHLIGHT = "2166A5"


def remove(shape):
    element = shape._element
    element.getparent().remove(element)


def find(shapes, shape_id):
    for shape in shapes:
        if shape.shape_id == shape_id:
            return shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            result = find(shape.shapes, shape_id)
            if result is not None:
                return result
    return None


def label(slide, name, text, x, y, width, height, size=12, color=BLUE):
    shape = slide.shapes.add_textbox(
        Inches(x), Inches(y), Inches(width), Inches(height)
    )
    shape.name = name
    frame = shape.text_frame
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    for index, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = line
        paragraph.alignment = PP_ALIGN.CENTER
        paragraph.font.name = "Arial"
        paragraph.font.size = Pt(size)
        paragraph.font.color.rgb = RGBColor.from_string(color)
    return shape


def arrow(slide, name, x1, y1, x2, y2, width=2, color=BLUE, head=True):
    shape = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    shape.name = name
    shape.line.color.rgb = RGBColor.from_string(color)
    shape.line.width = Pt(width)
    if head:
        endpoint = OxmlElement("a:tailEnd")
        endpoint.set("type", "triangle")
        shape._element.spPr.get_or_add_ln().append(endpoint)
    return shape



def highlight_path(slide, name, points):
    for index, (start, end) in enumerate(zip(points, points[1:])):
        arrow(slide, f"{name} segment {index + 1}", *start, *end,
              width=2.5, color=HIGHLIGHT, head=index == len(points) - 2)


def emphasize_inspection_path(slide, presentation):
    """Use the page width for the FPGA and emphasize the admission sequence.

    Preserve original Coyote blocks and icons. Move the small source card above
    the FPGA so that it no longer consumes a separate column at paper scale.
    The highlighted sequence is logical: the checker emits a verdict, while
    the PR controller loads the accepted raw bitstream from HBM.
    """
    # Remove old routing arrows and decorative arrows that conflict with the
    # explicitly directed inspection/admission sequence.
    for shape_id in (225, 226, 227, 228, 235, 236, 301, 302):
        shape = find(slide.shapes, shape_id)
        if shape is not None:
            remove(shape)
    old_names = {"Bitstream enters through network", "Network ingress label",
                 "Network input staged in HBM"}
    for shape in list(slide.shapes):
        if shape.name in old_names:
            remove(shape)

    boundary = find(slide.shapes, 203)
    boundary.width = Inches(7.85)
    for shape_id in (232, 233):
        block = find(slide.shapes, shape_id)
        block.width = Inches(1.38)
        block.line.color.rgb = RGBColor.from_string(HIGHLIGHT)
        block.line.width = Pt(2.2)
    find(slide.shapes, 232).height = Inches(0.98)
    network = find(slide.shapes, 233)
    network.top = Inches(1.50)
    network.height = Inches(1.21)
    network.text_frame.clear()
    label(slide, "100G networking heading", "100G\nnetworking",
          6.49, 1.54, 1.31, 0.50, size=13, color="000000")
    label(slide, "Network protocols", "RoCE v2 / TCP",
          6.49, 2.09, 1.31, 0.24, size=11, color="000000")
    network_icon = find(slide.shapes, 234)
    network_icon.left = Inches(7.02)
    network_icon.top = Inches(2.38)
    network_icon.width = Inches(0.26)
    network_icon.height = Inches(0.27)
    hbm_icon = find(slide.shapes, 238)
    hbm_icon.left = Inches(6.88)
    hbm_icon.top = Inches(0.61)
    hbm_icon.width = Inches(0.53)
    hbm_icon.height = Inches(0.214)
    for shape in slide.shapes:
        if shape.name == "HBM heading":
            shape.left = Inches(6.49)
            shape.width = Inches(1.31)
            shape.top = Inches(0.31)
            for paragraph in shape.text_frame.paragraphs:
                paragraph.font.size = Pt(14)
                paragraph.font.bold = True
        elif shape.name == "Staged raw bitstream":
            shape.left = Inches(6.49)
            shape.top = Inches(0.87)
            shape.width = Inches(1.31)
            shape.height = Inches(0.32)
            for paragraph in shape.text_frame.paragraphs:
                paragraph.font.size = Pt(11)

    checker = find(slide.shapes, 243)
    checker.width = Inches(2.15)
    checker.line.color.rgb = RGBColor.from_string(HIGHLIGHT)
    checker.line.width = Pt(2.2)
    for paragraph in checker.text_frame.paragraphs:
        for run in paragraph.runs:
            run.font.bold = True
    arbitration = find(slide.shapes, 224)
    arbitration.left = Inches(4.97)
    arbitration.width = Inches(1.00)
    for paragraph in arbitration.text_frame.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(12)

    # Leave a clear lane through the service header for the HBM arrow.
    find(slide.shapes, 222).text_frame.clear()
    label(slide, "Dynamic services heading", "Dynamic Layer: Services",
          1.30, 1.34, 3.15, 0.26, size=13, color="000000")

    # Lower the original FPGA as a unit, then place the source above it.
    source_names = {"Compact user bitstream source", "User bitstream label",
                    "Graphic 238", "Graphic 241"}
    for shape in slide.shapes:
        if shape.name not in source_names:
            shape.top += Inches(0.85)
    by_name = {shape.name: shape for shape in slide.shapes}
    card = by_name["Compact user bitstream source"]
    card.left, card.top = Inches(5.22), Inches(0.13)
    card.width, card.height = Inches(2.62), Inches(0.58)
    card.line.color.rgb = RGBColor.from_string(HIGHLIGHT)
    for name, x in (("Graphic 238", 5.34), ("Graphic 241", 5.79)):
        icon = by_name[name]
        icon.left, icon.top = Inches(x), Inches(0.24)
        icon.width = icon.height = Inches(0.34)
    source_label = by_name["User bitstream label"]
    source_label.left, source_label.top = Inches(6.22), Inches(0.27)
    source_label.width, source_label.height = Inches(1.53), Inches(0.25)

    # Route highlighted arrows through gaps between the retained blocks.
    highlight_path(slide, "User bitstream to 100G networking",
                   [(7.84, 0.42), (8.20, 0.42), (8.20, 2.95), (7.84, 2.95)])
    highlight_path(slide, "100G networking to HBM",
                   [(7.15, 2.35), (7.15, 2.093)])
    highlight_path(slide, "HBM to partial bitstream checker",
                   [(6.456, 1.55), (6.22, 1.55), (6.22, 2.035),
                    (4.68, 2.035), (4.68, 2.50)])
    highlight_path(slide, "Checker verdict to admission",
                   [(3.65, 3.455), (3.65, 3.76)])
    # Preserve the shield and reject branch; emphasize the accepted branch.
    accepted_arrow = find(slide.shapes, 247)
    accepted_arrow.line.color.rgb = RGBColor.from_string(HIGHLIGHT)
    accepted_arrow.line.width = Pt(2.5)
    accepted = find(slide.shapes, 249)
    accepted.line.color.rgb = RGBColor.from_string(HIGHLIGHT)
    accepted.line.width = Pt(2.2)
    highlight_path(slide, "Accepted staged bitstream to selected vFPGA PR",
                   [(5.39, 4.00), (6.12, 4.00), (6.12, 5.30),
                    (4.10, 5.30), (4.10, 5.88), (3.97, 5.88)])
    label(slide, "PR path label", "Accepted bitstream\nfrom HBM → PR",
          6.25, 4.35, 1.50, 0.55, size=10, color=HIGHLIGHT)
    target = find(slide.shapes, 253)
    target.line.color.rgb = RGBColor.from_string(HIGHLIGHT)
    target.line.width = Pt(2.2)
    label(slide, "Highlighted path legend", "Highlighted: inspection and PR admission sequence",
          0.25, 0.28, 4.72, 0.25, size=11, color=HIGHLIGHT)
    presentation.slide_width = Inches(8.40)
    presentation.slide_height = Inches(6.55)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soffice", help="Optional LibreOffice executable for PDF export")
    args = parser.parse_args()

    presentation = Presentation(SOURCE)
    slide = presentation.slides[0]
    # The source stores its vector icons only in Microsoft's SVG extension.
    # Also expose the same SVG relationship through the standard blip slot so
    # LibreOffice can render it. The original SVG data stays unchanged.
    for blip in slide._element.xpath(".//a:blip"):
        svg_refs = blip.xpath(".//*[@r:embed]")
        if not blip.get(qn("r:embed")) and svg_refs:
            blip.set(qn("r:embed"), svg_refs[0].get(qn("r:embed")))
    # Preserve all FPGA objects and the original user-bitstream artwork.
    # IDs 202, 204--217 belong to the CPU and PCIe path. ID 8 is a blank mask.
    removed_ids = {8, 202, *range(204, 218)}
    for shape in list(slide.shapes):
        if shape.shape_id in removed_ids:
            remove(shape)

    user_group = find(slide.shapes, 305)
    # This old downward submission arrow pointed into the removed CPU driver.
    remove(find(user_group.shapes, 240))

    # Translate the original FPGA layout as a whole without rescaling or
    # changing relative positions, connector routing, fonts, or colors.
    for shape in slide.shapes:
        if shape.shape_id != 305:
            shape.left -= Inches(5.70)
            shape.top -= Inches(1.10)
    # Reuse the two original SVG icons in a compact source card. Scaling the
    # whole original group also shrinks its text, so lay out these objects
    # individually and keep the label consistent with the networking label.
    source_icons = [deepcopy(find(user_group.shapes, shape_id)._element)
                    for shape_id in (239, 242)]
    remove(user_group)
    card = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(8.50), Inches(1.30),
        Inches(1.60), Inches(1.20)
    )
    card.name = "Compact user bitstream source"
    card.fill.background()
    card.line.color.rgb = RGBColor.from_string("000000")
    card.line.width = Pt(1.0)
    for element, x in zip(source_icons, (8.78, 9.35)):
        slide.shapes._spTree.insert_element_before(element, "p:extLst")
        icon = slide.shapes[-1]
        icon.left = Inches(x)
        icon.top = Inches(1.45)
        icon.width = Inches(0.45)
        icon.height = Inches(0.45)
    label(slide, "User bitstream label", "User bitstream",
          8.56, 2.04, 1.48, 0.28, size=12, color="000000")
    presentation.slide_width = Inches(10.30)
    presentation.slide_height = Inches(5.70)

    arrow(slide, "Bitstream enters through network", 8.50, 1.90, 7.40, 1.90)
    label(slide, "Network ingress label", "Network", 7.46, 1.49, 1.05, 0.28)

    # Keep the original HBM rectangle, fill, and memory icon. Repack only
    # its internal label/icon to make room for the staging annotation.
    hbm = find(slide.shapes, 232)
    hbm.text_frame.clear()
    hbm_icon = find(slide.shapes, 238)
    hbm_icon.left = Inches(6.70)
    hbm_icon.top = Inches(0.56)
    hbm_icon.width = Inches(0.45)
    hbm_icon.height = Inches(0.182)
    label(slide, "HBM heading", "HBM", 6.48, 0.29, 0.88, 0.23,
          size=12, color="000000")
    label(slide, "Staged raw bitstream", "Staged\nbitstream", 6.48, 0.76, 0.88, 0.29,
          size=9, color="000000")
    arrow(slide, "Network input staged in HBM", 6.92, 1.28, 6.92, 1.09, width=1.25)

    emphasize_inspection_path(slide, presentation)

    slide.notes_slide.notes_text_frame.text = (
        "Adaptation of coyote-figure.pptx for Section 5. Blue arrows highlight "
        "the logical sequence: user bitstream, 100G networking, HBM staging, "
        "checker verdict, and PR of an accepted user region. PR reads the raw "
        "bitstream from HBM, not from the CNN output. Original FPGA "
        "objects, layout, services, checker, allow/reject branches, icons, TLBs, "
        "and vFPGA regions are retained. CPU/PCIe submission is removed; the "
        "original user and binary icons are arranged in a compact source card, "
        "with input entering through the network. HBM "
        "retains the raw bitstream. Allow PR requires acceptance and complete "
        "input reception. XDMA is retained as original shell context, not as "
        "the submission path. This is a proposed standalone architecture; the "
        "reported measurements remain host-submitted. Edit in PowerPoint and "
        "export to PDF after manual changes."
    )
    presentation.save(OUTPUT)
    print(f"Saved editable original-object derivative: {OUTPUT}")
    if args.soffice:
        subprocess.run([
            args.soffice,
            "-env:UserInstallation=file:///tmp/paper-coyote-lo-profile",
            "--headless", "--convert-to", "pdf", "--outdir", str(OUTPUT.parent),
            str(OUTPUT),
        ], check=True)
        subprocess.run([
            "pdftoppm", "-singlefile", "-scale-to", "2200", "-png",
            str(OUTPUT.with_suffix(".pdf")), str(OUTPUT.with_suffix("")),
        ], check=True)


if __name__ == "__main__":
    main()
