"""Draw the application/Coyote boundary and Coyote's generated HBM path."""

import ctypes
import ctypes.util
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WIDTH = 1440
HEIGHT = 1460
PARTS = []


def text(x, y, label, size=23, color="#203047", bold=False):
    weight = "bold" if bold else "normal"
    PARTS.append(
        f'<text x="{x}" y="{y}" font-size="{size}" '
        f'font-weight="{weight}" fill="{color}">{escape(label)}</text>'
    )


def box(x, y, width, height, fill, stroke="#cad5e2"):
    PARTS.append(
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
        f'rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
    )


def arrow(x, start_y, end_y):
    PARTS.append(
        f'<path d="M{x} {start_y} V{end_y}" stroke="#4a607a" '
        'stroke-width="3" fill="none" marker-end="url(#arrow)"/>'
    )


def stage(y, title, detail, fill="#ffffff", stroke="#b3cce0"):
    box(105, y, 690, 75, fill, stroke)
    text(125, y + 30, title, 24, bold=True)
    text(125, y + 58, detail, 20)


def render_png(svg_path):
    # Reuse system SVG rendering libraries without changing the build environment.
    rsvg = ctypes.CDLL(ctypes.util.find_library("rsvg-2"))
    cairo = ctypes.CDLL(ctypes.util.find_library("cairo"))
    gobject = ctypes.CDLL(ctypes.util.find_library("gobject-2.0"))
    rsvg.rsvg_handle_new_from_file.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    rsvg.rsvg_handle_new_from_file.restype = ctypes.c_void_p
    rsvg.rsvg_handle_render_cairo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    rsvg.rsvg_handle_render_cairo.restype = ctypes.c_int
    cairo.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    cairo.cairo_image_surface_create.restype = ctypes.c_void_p
    cairo.cairo_create.argtypes = [ctypes.c_void_p]
    cairo.cairo_create.restype = ctypes.c_void_p
    cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    cairo.cairo_destroy.argtypes = [ctypes.c_void_p]
    cairo.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
    gobject.g_object_unref.argtypes = [ctypes.c_void_p]
    surface = cairo.cairo_image_surface_create(0, WIDTH, HEIGHT)
    context = cairo.cairo_create(surface)
    handle = rsvg.rsvg_handle_new_from_file(str(svg_path).encode(), None)
    assert handle and rsvg.rsvg_handle_render_cairo(handle, context)
    assert cairo.cairo_surface_write_to_png(
        surface, str(svg_path.with_suffix(".png")).encode()
    ) == 0
    gobject.g_object_unref(handle)
    cairo.cairo_destroy(context)
    cairo.cairo_surface_destroy(surface)


def main():
    PARTS.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        '<defs><marker id="arrow" markerWidth="9" markerHeight="9" '
        'refX="8" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" '
        'fill="#4a607a"/></marker></defs>'
        '<rect width="100%" height="100%" fill="#f6f8fc"/>'
        '<g font-family="DejaVu Sans, sans-serif">'
    )
    text(55, 57, "We use Coyote’s HBM interface", 36, bold=True)
    text(55, 96, "Clock and width adapters are already inside Coyote’s generated memory path.", 24)

    box(65, 130, 770, 130, "#e7f3e9", "#6caa7b")
    text(90, 164, "OUR APPLICATION", 19, "#347244", True)
    text(90, 202, "Bitstream storage branch", 27, bold=True)
    text(90, 236, "Supplies destination address, length and payload bytes", 21)
    arrow(450, 260, 337)
    text(480, 293, "Coyote card-memory interface", 20, bold=True)
    text(480, 322, "Requests + 512-bit payload stream", 19)

    box(65, 345, 770, 885, "#e8f1fb", "#6d99c8")
    # Leave the scope heading clear of the incoming connector.
    arrow(450, 385, 405)
    text(90, 378, "COYOTE SHELL — generated infrastructure", 20, "#245d97", True)
    stages = [
        (405, "DMA and address handling", "Turns requests and bytes into AXI memory transactions"),
        (505, "Register slice", "Pipelines the 512-bit application-side interface"),
        (605, "Clock converter", "Safely bridges the application and HBM AXI clocks"),
        (705, "Register slice", "Pipelines the 512-bit HBM-clock-side interface"),
        (805, "Width converter: 512 → 256 bits", "One 64-byte write beat becomes two 32-byte beats"),
        (905, "Register slice / physical crossing", "Adds pipeline stages along the route toward HBM"),
        (1005, "RAMA memory access adapter", "Manages and reorders memory accesses"),
        (1105, "AMD HBM controller", "Schedules transactions on the physical HBM memory"),
    ]
    for index, (y, title, detail) in enumerate(stages):
        if y == 805:
            stage(y, title, detail, "#fff1dc", "#d8993e")
        else:
            stage(y, title, detail)
        if index < len(stages) - 1:
            arrow(450, y + 75, y + 100)

    box(875, 145, 510, 175, "#ffffff")
    text(900, 183, "What we implement", 25, bold=True)
    text(900, 224, "Receive bytes into our ring buffer.", 22)
    text(900, 258, "Send a copy to Coyote for storage.", 22)
    text(900, 292, "Inspect or forward the other copy.", 22)

    box(875, 375, 510, 190, "#ffffff")
    text(900, 415, "What Coyote provides", 25, bold=True)
    text(900, 457, "Memory requests, DMA and adapters.", 22)
    text(900, 491, "Integrates AMD memory and AXI IP.", 22)
    text(900, 535, "We do not add a separate converter.", 22, "#245d97", True)

    box(875, 605, 510, 165, "#ffffff")
    text(900, 645, "Why adapt the interface?", 25, bold=True)
    text(900, 687, "Different clocks: 250 → 450 MHz.*", 22)
    text(900, 721, "Different data widths: 512 → 256 bits.", 22)
    text(900, 751, "Register stages help long routes meet timing.", 19)

    box(875, 805, 510, 200, "#fff1dc", "#d8993e")
    text(900, 845, "Where timing has failed", 25, bold=True)
    text(900, 887, "Converter control → register-slice enable.", 21)
    text(900, 922, "This is inside Coyote’s memory path.", 22)
    text(900, 960, "Networking changes placement and routes;", 20)
    text(900, 989, "the same IP can then miss its clock deadline.", 20)

    box(875, 1045, 510, 185, "#ffffff")
    text(900, 1085, "Present in BOTH designs", 25, bold=True)
    text(900, 1127, "HBM-resident builds use these adapters.", 21)
    text(900, 1162, "Network builds use these adapters too.", 21)
    text(900, 1204, "* Fallback builds use 200 → 350 MHz.", 20)

    arrow(450, 1180, 1280)
    box(105, 1280, 690, 85, "#e4e9f0", "#8293a8")
    text(130, 1318, "PHYSICAL HBM", 25, bold=True)
    text(130, 1350, "Stores the bitstream bytes for later use", 22)
    text(55, 1410, "Write-data path simplified; AXI responses and backpressure run in the reverse direction. Not a placement map.", 19)
    text(55, 1440, "2026-11-08 · Source: Coyote cr_hbm.tcl and our network_base.svh. The highlighted box is existing infrastructure.", 18)
    PARTS.append("</g></svg>")
    svg_path = ROOT / "coyote_hbm_interface.svg"
    svg_path.write_text("\n".join(PARTS) + "\n")
    render_png(svg_path)
    print(svg_path)


if __name__ == "__main__":
    main()
