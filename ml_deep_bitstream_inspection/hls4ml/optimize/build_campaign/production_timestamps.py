"""Read-only R_SO_T monitor decoding; call after production result DMA.

These are FPGA cycle intervals including stalls. Preprocessing and CNN overlap.
Host-to-FPGA alignment is a separate acceptance gate, not provided here.
"""
ABI = 0x52534F5400010000
MASK = (1 << 64) - 1
EVENTS = ("in", "pixel_first", "pixel_last", "cnn_first", "verdict")


def read_snapshot(read_csr, raw_bytes, previous_frame=None):
    registers = {}
    native_reader = read_csr
    def read_csr(index):
        value = int(native_reader(index))
        registers[index] = value
        return value
    if read_csr(0) != ABI:
        raise RuntimeError("R_SO_T timestamp ABI mismatch")
    frame = read_csr(2)
    status = read_csr(3)
    events = read_csr(4)
    stamps = {name: read_csr(5+i) for i, name in enumerate(EVENTS)}
    counts = dict(pixels_written=read_csr(10), pixels_read=read_csr(11),
                  raw_bytes=read_csr(12), input_beats=read_csr(13))
    # A new frame during MMIO reads makes the snapshot incoherent.
    if read_csr(2) != frame or read_csr(3) != status:
        raise RuntimeError("timestamp capture changed during readout")
    if status != 2 or events != 31:
        raise RuntimeError(f"incomplete/invalid timestamp capture: {status=}, {events=}")
    if previous_frame is not None and frame != (previous_frame+1) & MASK:
        raise RuntimeError("stale/skipped timestamp frame")
    if counts != dict(pixels_written=65536, pixels_read=65536,
                      raw_bytes=raw_bytes, input_beats=1+(raw_bytes+63)//64):
        raise RuntimeError(f"timestamp counts mismatch: {counts}")
    offset = {name: (value-stamps['in']) & MASK for name, value in stamps.items()}
    # Modular subtraction permits counter rollover; no interval can span half
    # of a 64-bit counter (over a millennium at 250 MHz).
    if not (0 < offset['pixel_first'] <= offset['pixel_last'] <= offset['verdict'] < 1 << 63
            and offset['pixel_first'] <= offset['cnn_first'] <= offset['verdict']):
        raise RuntimeError("invalid timestamp ordering")
    intervals = dict(preprocessing_startup=offset['pixel_first'],
                     preprocessing_elapsed=offset['pixel_last'],
                     cnn_elapsed=offset['verdict']-offset['cnn_first'],
                     cnn_tail=offset['verdict']-offset['pixel_last'],
                     fpga_pipeline=offset['verdict'])
    return dict(frame_id=frame, registers=registers, timestamp_ticks=stamps, counts=counts,
                interval_ticks=intervals)
