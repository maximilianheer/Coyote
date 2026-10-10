"""One correctness policy shared by runtime collection and benchmark analysis."""
import math
import struct


def as_float(bits):
    return struct.unpack('<f', struct.pack('<I', bits & 0xffffffff))[0]


def check_logit(bits, verdict, case, tolerance=None):
    expected = int(case['expected_logit_hex'], 16)
    value, reference = as_float(bits), as_float(expected)
    if not math.isfinite(value) or not math.isfinite(reference):
        raise ValueError('non-finite logit')
    expected_verdict = int(reference >= 0)
    if verdict != expected_verdict or verdict != int(value >= 0):
        raise ValueError('verdict parity')
    if tolerance is None:
        if bits != expected:
            raise ValueError('exact-logit parity: no production tolerance established')
        return
    if (tolerance['sha256'] != case['sha256'] or tolerance['bytes'] != case['bytes'] or
        tolerance['expected_logit_hex'].lower() != case['expected_logit_hex'].lower() or
        tolerance['production_verdict'] != expected_verdict or tolerance['repetitions'] != 10):
        raise ValueError('production tolerance identity/reference mismatch')
    limit = tolerance['max_abs_error']
    if not math.isfinite(limit) or limit < 0 or abs(value-reference) > limit:
        raise ValueError('production-matched logit tolerance')


def load_tolerances(path):
    import json
    data = json.loads(path.read_text())
    if data['status'] != 'passed' or data['policy'] != 'per-input production maximum absolute error; 10 repeats':
        raise ValueError('unvalidated production tolerances')
    return data['inputs']
