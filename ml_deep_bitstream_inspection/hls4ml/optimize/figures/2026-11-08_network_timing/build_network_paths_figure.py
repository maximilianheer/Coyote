"""Illustrate payload and verdict paths in the two network benchmark builds."""

import build_hbm_interface_figure as drawing


WIDTH = 1800
HEIGHT = 1810
BLUE = "#27649a"
PURPLE = "#8056a5"
GREEN = "#e7f3e9"
SHELL = "#e8f1fb"
MEMORY = "#e7ebf1"
GPU = "#fff0db"


def label(x, y, value, size=23, bold=False, color="#203047"):
    drawing.text(x, y, value, size, color, bold)


def node(x, y, width, title, detail, fill=SHELL, height=95):
    drawing.box(x, y, width, height, fill)
    title_size = min(25, (width - 40) / (len(title) * 0.63))
    detail_size = min(20, (width - 40) / (len(detail) * 0.56))
    label(x + 20, y + 36, title, title_size, True)
    label(x + 20, y + 72, detail, detail_size)


def edge(points, verdict=False):
    path = "M" + " L".join(f"{x},{y}" for x, y in points)
    color = PURPLE if verdict else BLUE
    marker = "verdict" if verdict else "payload"
    dash = ' stroke-dasharray="10 7"' if verdict else ""
    drawing.PARTS.append(
        f'<path d="{path}" fill="none" stroke="{color}" '
        f'stroke-width="4"{dash} marker-end="url(#{marker})"/>'
    )


def main():
    drawing.WIDTH = WIDTH
    drawing.HEIGHT = HEIGHT
    drawing.PARTS.clear()
    drawing.PARTS.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        '<defs>'
        f'<marker id="payload" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="{BLUE}"/></marker>'
        f'<marker id="verdict" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="{PURPLE}"/></marker>'
        '</defs><rect width="100%" height="100%" fill="#f6f8fc"/>'
        '<g font-family="DejaVu Sans, sans-serif">'
    )
    label(55, 58, "Where the bitstream goes in our networking builds", 37, True)
    label(55, 101, "Two alternative FPGA images: both store the arriving bytes in HBM while checking or forwarding them.", 25)

    node(490, 140, 820, "Remote sender / RDMA NIC", "Sends the raw bitstream over 100GbE using RoCEv2", MEMORY)
    edge([(900, 235), (900, 265)])
    node(490, 265, 820, "FPGA: Ethernet MAC → IPv4 / UDP → RoCE", "Receives packets, handles the protocol and extracts payload bytes")
    edge([(900, 360), (900, 390)])
    node(490, 390, 820, "Coyote receive interface", "Delivers write requests and a 512-bit payload stream to our logic")

    drawing.box(50, 540, 825, 965, "#ffffff", "#b3cce0")
    drawing.box(925, 540, 825, 965, "#ffffff", "#b3cce0")
    label(75, 581, "OPT_12 · Network → FPGA checker", 29, True)
    label(950, 581, "OPT_13 · Network → GPU over P2P", 29, True)
    # The fork here represents alternative builds, not a duplicate network send.
    edge([(900, 485), (900, 510), (462, 510), (462, 532)])
    edge([(900, 485), (900, 510), (1337, 510), (1337, 532)])
    edge([(462, 600), (462, 625)])
    edge([(1337, 600), (1337, 625)])
    node(220, 625, 485, "Our dual-reader ring", "Holds bytes for both consumers", GREEN)
    node(1095, 625, 485, "Our dual-reader ring", "Holds bytes for both consumers", GREEN)

    for center, left, right in [(462, 257, 672), (1337, 1132, 1547)]:
        edge([(center, 720), (center, 750), (left, 750), (left, 795)])
        edge([(center, 720), (center, 750), (right, 750), (right, 795)])

    for x in [80, 955]:
        node(x, 795, 355, "Coyote HBM write path", "DMA + clock / width adapters")
        edge([(x + 177, 890), (x + 177, 950)])
        node(x, 950, 355, "HBM: raw bitstream", "Stored for later use / PR", MEMORY)
        label(x + 10, 1080, "Storage completes separately", 20)
        label(x + 10, 1110, "from verdict availability.", 20)

    node(490, 795, 355, "Our preprocessor", "Samples bytes → valid pixels", GREEN)
    edge([(672, 890), (672, 950)])
    node(490, 950, 355, "hls4ml CNN", "Inference runs on the FPGA", GREEN)
    edge([(672, 1045), (672, 1135)], verdict=True)
    node(490, 1135, 355, "FPGA verdict", "Score + decision timestamp", "#eee6f6")
    drawing.box(80, 1280, 765, 180, "#f0f7f1", "#9dbba3")
    label(100, 1320, "All processing stays on the FPGA", 25, True)
    label(100, 1360, "The CNN consumes pixels before the entire bitstream arrives.", 21)
    label(100, 1396, "The checker consumes the ring’s copy directly.", 21)
    label(100, 1432, "There is no HBM reread on this inspection path.", 21, True)

    node(1365, 795, 355, "Coyote PCIe P2P DMA", "Forwards raw bytes to GPU")
    edge([(1547, 890), (1547, 955)])
    drawing.box(1345, 945, 395, 450, "#fff8ed", "#d9b580")
    node(1365, 965, 355, "GPU memory", "Receives raw bytes via PCIe P2P", GPU)
    edge([(1547, 1060), (1547, 1105)])
    node(1365, 1105, 355, "GPU preprocessing + CNN", "R06: FP32, XLA + ConcreteFunction", GPU)
    edge([(1547, 1200), (1547, 1265)], verdict=True)
    node(1365, 1265, 355, "GPU verdict mailbox", "Ready flag + score / decision", "#eee6f6")
    node(955, 1265, 355, "FPGA verdict poller", "Autonomously reads GPU mailbox", "#eee6f6")
    edge([(1365, 1312), (1310, 1312)], verdict=True)
    label(975, 1223, "Verdict returns over PCIe P2P", 20, True, PURPLE)
    label(950, 1429, "Polling starts after HBM storage and GPU writes complete.", 21)
    label(950, 1464, "GPU execution still uses software coordination.", 21)

    drawing.box(50, 1535, 1700, 110, "#ffffff")
    label(75, 1574, "NET_DIAG_HBM · Transport diagnostic", 25, True)
    label(75, 1613, "Same network front end → Coyote storage path → HBM (or host-memory sink). No CNN or GPU inference.", 23)

    edge([(65, 1680), (140, 1680)])
    label(158, 1688, "Raw bytes / pixels", 21)
    edge([(475, 1680), (550, 1680)], verdict=True)
    label(568, 1688, "Verdict path", 21)
    label(900, 1688, "Blue: Coyote   ·   Green: application logic   ·   Orange: GPU", 20)
    label(55, 1730, "Ring space is released only after BOTH consumers accept the bytes; the slower branch can throttle reception.", 23, True)
    label(55, 1767, "Payload paths shown. RoCE acknowledgements, retransmission buffers and setup/control traffic are omitted for clarity.", 20)
    label(55, 1796, "2026-11-08 · Source: network_base.svh, net_diag.svh and deployment_abi.json. Build architecture; board validation remains pending.", 18)
    drawing.PARTS.append("</g></svg>")
    svg_path = drawing.ROOT / "network_build_bitstream_paths.svg"
    svg_path.write_text("\n".join(drawing.PARTS) + "\n")
    drawing.render_png(svg_path)
    print(svg_path)


if __name__ == "__main__":
    main()
