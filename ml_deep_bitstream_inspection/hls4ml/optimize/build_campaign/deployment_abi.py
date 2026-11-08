"""Decode the deployment CSR ABI without accepting historical signatures."""
import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_suffix('.json')
SCHEMA = json.loads(SCHEMA_PATH.read_text())
SIGNATURE = int(SCHEMA['signature_prefix'], 16)


def identify(signature):
    if signature & ~0xffff != SIGNATURE:
        raise ValueError(f'Unsupported deployment signature: {signature:#018x}')
    variant = signature & 0xffff
    try:
        return SCHEMA['variants'][str(variant)]
    except KeyError as error:
        raise ValueError(f'Unknown deployment variant: {variant}') from error


def decode(registers):
    family = identify(registers[4])
    status = registers[0]
    result = {'family': family, 'status': {
        name: bool(status & (1 << int(bit)))
        for bit, name in SCHEMA['status_bits'].items()
    }}
    valid = registers[7]
    result['events'] = {}
    for pair, name in enumerate(SCHEMA['event_pairs'][family]):
        if name == 'unused':
            continue
        for half, suffix in enumerate(['first', 'last']):
            index = pair * 2 + half
            result['events'][name + '_' + suffix] = (
                registers[16 + index] if valid & (1 << index) else None
            )
    result['counters'] = {
        name: registers[48 + index]
        for index, name in enumerate(SCHEMA['counter_names'][family])
        if name != 'unused'
    }
    return result
