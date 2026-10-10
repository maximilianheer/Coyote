"""Read-only admission checks for production-path recovery prerequisites."""
import csv
import json
from pathlib import Path
from board_benchmark import sha
from isolation_board import verified_bitstream
from parity_gate import as_float, check_logit, load_tolerances


def verified_board_parity(jobdir, board, output):
    """Require actual 26×10 result rows plus matching build/runtime identities."""
    if jobdir.name not in ('R_O', 'R_S', 'R_SO_T'):
        raise ValueError('Expected a production-path recovery variant')
    bit, source_hash = verified_bitstream(jobdir)
    state = json.loads((output/'status.json').read_text())
    result = json.loads((output/'isolation_validation.json').read_text())
    if (state.get('status')!='passed' or state.get('stage')!='complete' or
        state.get('job')!=jobdir.name or state.get('board_calls')!=260):
        raise RuntimeError('Board validation is not complete')
    if (state.get('source_manifest_sha256')!=source_hash or
        state.get('bitstream_sha256')!=sha(bit) or
        state.get('driver_sha256')!=sha(board/'software/driver/build/coyote_driver.ko')):
        raise RuntimeError('Board validation artifact/source identity mismatch')
    cases_file = board/'diagnostics/runtime_cases.tsv'
    tolerance_file = board/'production_tolerances.json'
    expected = dict(bitstream_sha256=sha(bit),
        library_sha256=sha(jobdir/'host_build/lib/libCoyoteInference.so'),
        coyote_library_sha256=sha(jobdir/'host_build/coyote/libcoyote.so'),
        cases_sha256=sha(cases_file), acceptance_tolerances_sha256=sha(tolerance_file))
    if (result.get('status')!='passed' or result.get('failures') or
        result.get('policy')!='isolation validation against frozen production tolerances' or
        any(result.get(k)!=v for k,v in expected.items())):
        raise RuntimeError('Parity summary/runtime identity mismatch')
    cases = {}
    with cases_file.open() as stream:
        for row in csv.reader(stream,delimiter='\t'):
            if not row or row[0].startswith('#'):continue
            if len(row)!=6:raise RuntimeError('Invalid reference manifest')
            ident,sweep,path,size,digest,bits=row
            if ident in cases or Path(path).stat().st_size!=int(size) or sha(path)!=digest:
                raise RuntimeError('Reference input identity mismatch')
            cases[ident]=dict(id=ident,sweep=sweep,bytes=int(size),sha256=digest,expected_logit_hex=bits)
    if len(cases)!=26 or set(result['inputs'])!={c['sha256'] for c in cases.values()}:
        raise RuntimeError('Incomplete board case grid')
    tolerances = load_tolerances(tolerance_file)
    with (output/'production.csv').open() as stream:rows=list(csv.DictReader(stream))
    if len(rows)!=260:raise RuntimeError('Expected 260 board result rows')
    seen=set();errors={ident:[] for ident in cases}
    for row in rows:
        ident=row['case_id'];trial=int(row['trial']);key=(ident,trial)
        if ident not in cases or trial not in range(10) or key in seen:
            raise RuntimeError('Duplicate/unknown board trial')
        seen.add(key);case=cases[ident]
        if row['sha256']!=case['sha256'] or int(row['expected_logit_hex'],16)!=int(case['expected_logit_hex'],16):
            raise RuntimeError('Board row input/reference mismatch')
        bits=int(row['logit_hex'],16)
        check_logit(bits,int(row['verdict']),case,tolerances[case['sha256']])
        error=abs(as_float(bits)-as_float(int(case['expected_logit_hex'],16)))
        if float(row['logit'])!=as_float(bits) or float(row['abs_error'])!=error:
            raise RuntimeError('Inconsistent board result fields')
        errors[ident].append(error)
    for ident,case in cases.items():
        entry=result['inputs'][case['sha256']]
        if len(errors[ident])!=10 or entry['repetitions']!=10 or entry['max_abs_error']!=max(errors[ident]):
            raise RuntimeError('Board repetitions/error summary mismatch')
    evidence = dict(job=jobdir.name,board_calls=260,source_manifest_sha256=source_hash,
                    board_results_sha256=sha(output/'production.csv'),**expected)
    if jobdir.name=='R_SO_T':
        evidence['passive_captures_sha256']=verified_passive_captures(output,cases,rows,result)
    return evidence


def verified_passive_captures(output, cases, rows, result):
    """Re-decode every saved capture; a passed summary alone is insufficient."""
    from production_timestamps import ABI, read_snapshot
    summary=result.get('passive_timestamps',{})
    if (summary.get('status')!='passed' or summary.get('frames')!=260 or summary.get('abi')!=ABI or
            result.get('runtime_lifecycle')!='one persistent production context'):
        raise RuntimeError('Missing persistent production passive-capture gate')
    path=output/'host_observed.jsonl'
    observations=[json.loads(line) for line in path.read_text().splitlines()]
    if len(observations)!=260 or len(rows)!=260:
        raise RuntimeError('Expected 260 passive captures')
    previous=None
    for observation,row in zip(observations,rows):
        ident=row['case_id'];case=cases[ident]
        if (observation['case_id']!=ident or observation['trial']!=int(row['trial']) or
                observation.get('monitor_error') or observation['raw_bytes']!=case['bytes'] or
                observation['transport_bytes']!=64+case['bytes'] or
                observation['logit_bits']!=int(row['logit_hex'],16) or
                observation['verdict']!=int(row['verdict'])):
            raise RuntimeError('Passive capture does not match production result row')
        registers={int(k):int(v) for k,v in observation['monitor']['registers'].items()}
        capture=read_snapshot(registers.__getitem__,case['bytes'],previous)
        if capture!=dict(observation['monitor'],registers=registers):
            raise RuntimeError('Saved passive capture decoding changed')
        previous=capture['frame_id']
    return sha(path)


def verified_recovery_pair(campaign, board, evidence):
    return {ident:verified_board_parity(campaign/'jobs'/ident,board,evidence/ident)
            for ident in ('R_O','R_S')}
