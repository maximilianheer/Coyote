"""Predeclared configurations, descriptor oracle and ABI5/ABI6 validation."""

import math
import struct

import numpy as np

CONFIGURATIONS = [
    dict(key="OPT10", variant=10, setting=0, label="Previous HBM gather", primary=True),
    dict(key="SCAN", variant=14, setting=0, label="Sequential scan", primary=True),
    *[
        dict(
            key=f"GROUP{group}",
            variant=15,
            setting=group,
            label=f"Coalesced group {group}",
            primary=group == 4,
        )
        for group in [1, 2, 4, 8]
    ],
    *[
        dict(
            key=f"WINDOW{window}",
            variant=16,
            setting=window,
            label=f"Outstanding {window}",
            primary=window == 128,
        )
        for window in [32, 64, 128]
    ],
    dict(key="GPU_P2P", variant=11, setting=0, label="GPU_P2P", primary=True),
]
IMAGE_IDS = {
    10: "OPT_10_HBM_GATHER_DSP_B2_RF72_RF288",
    11: "OPT_11_HBM_GPU_P2P_R06",
    14: "OPT_14_HBM_SCAN",
    15: "OPT_15_HBM_COALESCED_GATHER",
    16: "OPT_16_HBM_GATHER_OUTSTANDING128",
}
COUNTERS = [
    "reads_issued",
    "words_received",
    "reads_completed",
    "pixel_count",
    "pixel_fifo_current",
    "requested_bytes",
    "peak_outstanding",
    "request_stalls",
    "credit_stalls",
    "response_backpressure",
    "cnn_starvation",
    "cnn_backpressure",
    "pixel_fifo_peak",
    "active_cycles",
    "pixel_producer_backpressure",
    "response_requests_retired",
]


def identify(signature):
    variant = signature & 0xFFFF
    version = (signature >> 16) & 0xFFFF
    assert signature >> 32 == 0x43425954
    assert (version == 5 and variant in [10, 11]) or (
        version == 6 and variant in [14, 15, 16]
    ), hex(signature)
    return variant, version


def effective_setting(variant, setting):
    if variant in [10, 11, 14]:
        assert setting == 0
        return 0
    if variant == 15:
        assert setting in [0, 1, 2, 4, 8]
        return setting or 4
    if variant == 16:
        assert setting in [0, 32, 64, 128]
        return setting or 32
    raise ValueError(variant)


def descriptors(variant, length, setting, base=0):
    """Logical descriptors, including page splits and duplicate suppression."""
    if variant == 14:
        return [
            (base + offset, min(65536, length - offset))
            for offset in range(0, length, 65536)
        ]
    positions = np.arange(65536, dtype=np.int64)
    if length > 65536:
        positions = positions * (length - 1) // 65535
    if variant in [10, 16]:
        return [
            (base + int(word) * 64, 64)
            for word in np.unique(positions[positions < length] // 64)
        ]
    assert variant == 15
    grouping = effective_setting(variant, setting)
    result = []
    covered_end = 0
    for begin_sample in range(0, 65536, grouping):
        group = positions[begin_sample : begin_sample + grouping]
        group = group[group < length]
        if not len(group):
            continue
        begin = max(int(group[0]) // 64 * 64, covered_end)
        end = int(group[-1]) // 64 * 64 + 64
        while begin < end:
            address = base + begin
            size = min(end - begin, 16384, 2097152 - address % 2097152)
            result.append((address, size))
            begin += size
        covered_end = end
    return result


def expected_counters(variant, length, setting, base=0):
    if variant == 11:
        return dict(bytes_forwarded=length, chunks_completed=(length + 65535) // 65536)
    requests = descriptors(variant, length, setting, base)
    return dict(
        reads_issued=len(requests),
        words_received=sum((size + 63) // 64 for _, size in requests),
        reads_completed=len(requests),
        pixel_count=65536,
        requested_bytes=sum(size for _, size in requests),
        response_requests_retired=len(requests),
    )


def validate(row, configuration, expected, case, gpu_reference=None):
    variant, abi = identify(row["csr_4"])
    assert variant == configuration["variant"]
    assert row["csr_0"] == 10 and row["csr_2"] == row["trial"]
    assert row["csr_7"] & (1 << 8)
    assert row["csr_24"] >= row["csr_6"]
    score_bits = row["csr_40"] & 0xFFFFFFFF
    score = struct.unpack("<f", struct.pack("<I", score_bits))[0]
    assert math.isfinite(score)
    assert (row["csr_40"] >> 32) & 1 == int(score >= 0)
    if variant == 11:
        assert abs(score - gpu_reference) <= 1e-4 + 1e-4 * abs(gpu_reference)
        assert (score >= 0) == (gpu_reference >= 0)
        assert row["csr_48"] == expected["bytes_forwarded"]
        assert row["csr_49"] == expected["chunks_completed"]
    else:
        assert score_bits == case["quantized_bits"], (
            case["id"],
            hex(score_bits),
            hex(case["quantized_bits"]),
        )
        for index, key in enumerate(COUNTERS[:4]):
            assert row[f"csr_{48 + index}"] == expected[key], (
                key,
                row[f"csr_{48 + index}"],
                expected[key],
            )
        if abi == 6:
            effective = effective_setting(variant, configuration["setting"])
            assert row["csr_41"] == effective
            assert row["csr_53"] == expected["requested_bytes"]
            assert row["csr_63"] == expected["response_requests_retired"]
            window = 4 if variant == 14 else 32 if variant == 15 else effective
            assert row["csr_54"] <= window
            assert row["csr_60"] <= 32
            assert all(
                row[f"csr_{key}"] <= row["csr_61"] for key in [55, 56, 57, 58, 59, 62]
            )
    return score
