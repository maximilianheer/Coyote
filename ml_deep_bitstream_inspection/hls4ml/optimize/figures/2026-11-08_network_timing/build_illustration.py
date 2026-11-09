"""Generate a schematic explanation from the November 8 build evidence."""
from pathlib import Path
from html import escape
import ctypes
import ctypes.util

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1500, 1110
parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">
<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#52647a"/></marker></defs>
<rect width="1500" height="1110" fill="#f4f7fb"/>
<g font-family="DejaVu Sans, sans-serif" fill="#172b46">''']


def box(x, y, width, height, fill='#ffffff', stroke='#d7e0eb', radius=14):
    parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')


def text(x, y, value, size=22, weight='normal', color='#172b46', anchor='start'):
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{escape(value)}</text>')


def arrow(x1, y1, x2, y2, color='#52647a'):
    parts.append(f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="{color}" stroke-width="3" marker-end="url(#arrow)"/>')


text(40, 55, 'Why the network builds are harder to time', 36, 'bold')
text(40, 91, 'Adding RoCE changes the hardware and its placement—not just where the bytes enter.', 23)

box(40, 120, 700, 310)
box(760, 120, 700, 310)
text(65, 160, 'HBM-resident cases', 27, 'bold', '#1269a3')
text(785, 160, 'Network cases', 27, 'bold', '#b35a13')
text(65, 195, 'The input is already stored when the trial starts.', 20)
text(785, 195, 'The FPGA must receive, store and inspect/forward.', 20)

for x, width, lines in [(70, 165, ['HBM', 'ready bytes']),
                        (280, 195, ['Read / gather', 'or forward']),
                        (520, 185, ['Checker', 'or GPU'])]:
    box(x, 230, width, 83, '#e5f2fc', '#9cc5e1')
    for i, line in enumerate(lines):
        text(x + width / 2, 264 + i * 28, line, 22, anchor='middle')
arrow(238, 271, 274, 271)
arrow(478, 271, 514, 271)
text(65, 359, '2 Coyote HBM interface paths', 24, 'bold')
text(65, 394, 'PCIe shell + 512-to-256-bit HBM converters.', 20)

for x, width, lines in [(785, 125, ['100GbE', 'input']),
                        (945, 250, ['Ethernet / IP / UDP', 'RoCE + CRC + DMA']),
                        (1230, 205, ['HBM storage', '+ inspection /', 'GPU forwarding'])]:
    box(x, 230, width, 100, '#fff0dc', '#e5b67b')
    start = 261 if len(lines) == 3 else 270
    for i, line in enumerate(lines):
        text(x + width / 2, start + i * 26, line, 19, anchor='middle')
arrow(913, 280, 939, 280)
arrow(1198, 280, 1224, 280)
text(785, 367, '3 Coyote HBM interface paths + packet buffers', 23, 'bold')
text(785, 402, 'Same converters; added HBM path and network logic.', 20)

box(40, 450, 1420, 310)
text(65, 492, 'The critical detail: one control signal must reach hundreds of registers', 27, 'bold')
box(80, 563, 270, 95, '#e5f2fc', '#9cc5e1')
text(215, 601, 'HBM width converter', 22, anchor='middle')
text(215, 634, 'control register', 22, 'bold', anchor='middle')
arrow(353, 610, 440, 610, '#c65b30')
parts.append('<path d="M445 545 L445 695" fill="none" stroke="#c65b30" stroke-width="4"/>')
for i in range(6):
    y = 545 + 30 * i
    arrow(445, y, 650, y, '#c65b30')
    box(660, y - 12, 310, 25, '#fff0dc', '#e5b67b', radius=5)
    text(815, y + 6, 'Payload-register enables', 16, anchor='middle')
text(485, 723, 'Fanout + wire length + placement constraints', 18, color='#8e471f')
text(1010, 553, 'Each registered hop has a deadline', 19, 'bold')
text(1010, 593, '450 MHz HBM → 2.22 ns', 25, 'bold', '#1269a3')
text(1010, 634, 'Measured miss: 0.529 ns', 24, 'bold', '#b73838')
text(1010, 671, 'NET_DIAG attempt_06, HBM path_2', 18)
text(1010, 700, 'Path indices shift with RoCE enabled.', 18)
text(65, 744, 'Every hop is checked separately; the entire packet does not have to cross the pipeline in one cycle.', 19)

box(40, 780, 700, 260)
box(760, 780, 700, 260)
text(65, 819, 'More hardware to place and connect', 25, 'bold')
text(65, 851, 'Routed GPU variants; network attempt failed timing', 18)
text(320, 887, 'HBM → GPU', 20, 'bold')
text(520, 887, 'Network → GPU', 20, 'bold')
for y, label, a, b in [(924, 'LUTs', '182k', '330k  (1.8×)'),
                        (961, 'Registers', '282k', '610k  (2.2×)'),
                        (998, 'BRAM tiles', '179.5', '467  (2.6×)')]:
    text(65, y, label, 22)
    text(320, y, a, 22, color='#1269a3')
    text(520, y, b, 22, 'bold', '#b35a13')
text(785, 819, 'How the current fallback adds margin', 25, 'bold')
text(785, 862, 'HBM interface', 22, 'bold')
text(785, 897, '450 MHz: 2.22 ns', 22)
arrow(1015, 889, 1072, 889)
text(1090, 897, '350 MHz: 2.86 ns', 22, 'bold', '#20734e')
text(785, 942, 'Application logic', 22, 'bold')
text(785, 977, '250 MHz: 4.00 ns', 22)
arrow(1015, 969, 1072, 969)
text(1090, 977, '200 MHz: 5.00 ns', 22, 'bold', '#20734e')
text(785, 1018, 'Lower clocks can affect speed; routed timing must pass.', 19)
text(40, 1072, 'Schematic, not a placement map. Slack includes data-path and clock effects. Resource evidence: OPT_11 attempt_01 vs OPT_13 attempt_06.', 17)
text(40, 1098, 'Created 2026-11-08. HBM “paths” are Coyote interfaces, not the physical count of HBM banks.', 17)
parts.append('</g></svg>')
svg = ROOT / 'network_timing_explanation.svg'
svg.write_text('\n'.join(parts) + '\n')

# Use installed system libraries to render the vector source without adding
# Python dependencies to the build environment.
rsvg = ctypes.CDLL(ctypes.util.find_library('rsvg-2'))
cairo = ctypes.CDLL(ctypes.util.find_library('cairo'))
rsvg.rsvg_handle_new_from_file.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
rsvg.rsvg_handle_new_from_file.restype = ctypes.c_void_p
rsvg.rsvg_handle_render_cairo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
rsvg.rsvg_handle_render_cairo.restype = ctypes.c_int
cairo.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
cairo.cairo_image_surface_create.restype = ctypes.c_void_p
cairo.cairo_create.argtypes = [ctypes.c_void_p]
cairo.cairo_create.restype = ctypes.c_void_p
cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
surface = cairo.cairo_image_surface_create(0, WIDTH, HEIGHT)
context = cairo.cairo_create(surface)
handle = rsvg.rsvg_handle_new_from_file(str(svg).encode(), None)
assert handle and rsvg.rsvg_handle_render_cairo(handle, context)
assert cairo.cairo_surface_write_to_png(surface, str(svg.with_suffix('.png')).encode()) == 0
print(svg)
