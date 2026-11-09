#!/usr/bin/env python3
"""Extract separate fused-compute diagnostic intervals from TensorFlow XPlane."""
import argparse
import json
from pathlib import Path

from tensorflow.core.profiler.protobuf import xplane_pb2


def summarize(root):
    rows = []
    for path in sorted((root / 'profiles').rglob('*.xplane.pb')):
        space = xplane_pb2.XSpace()
        space.ParseFromString(path.read_bytes())
        markers = []
        kernels = []
        copies = []
        for plane in space.planes:
            for line in plane.lines:
                for event in line.events:
                    name = plane.event_metadata[event.metadata_id].name
                    start = line.timestamp_ns + event.offset_ps / 1000
                    end = start + event.duration_ps / 1000
                    stats = {}
                    for value in event.stats:
                        kind = value.WhichOneof('value')
                        stats[plane.stat_metadata[value.metadata_id].name] = (
                            plane.stat_metadata[value.ref_value].name if kind == 'ref_value' else getattr(value, kind))
                    if plane.name == '/host:CPU' and name == 'combined_compute':
                        markers.append((start, end))
                    if 'GPU' in plane.name and 'kernel_details' in stats:
                        kernels.append(dict(name=name, start=start, end=end))
                    if 'GPU' in plane.name and name.startswith('Copy'):
                        copies.append(dict(name=name, start=start, end=end))
        samples = []
        for start, end in markers:
            inside = [kernel for kernel in kernels if kernel['start'] >= start and kernel['end'] <= end]
            assert inside, (path, start, end)
            samples.append(dict(kernel_sum_ms=sum(kernel['end'] - kernel['start'] for kernel in inside) / 1e6,
                                device_span_ms=(max(kernel['end'] for kernel in inside) - min(kernel['start'] for kernel in inside)) / 1e6,
                                host_profiled_ms=(end - start) / 1e6, kernels=len(inside)))
        assert len(samples) == 5, (path, len(samples))
        rows.append(dict(case_id=path.relative_to(root / 'profiles').parts[0], samples=samples,
                         copy_events=copies, kernel_names=sorted({kernel['name'] for kernel in kernels})))
    assert rows
    (root / 'profile_summary.json').write_text(json.dumps(rows, indent=2))
    print('Profiled workload count:', len(rows), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    summarize(parser.parse_args().root.resolve())
