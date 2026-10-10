#!/usr/bin/env python3
"""Compare 256 constant inputs on the existing D_I board; diagnostic only."""
import argparse,csv,json,os,subprocess,sys,time
from pathlib import Path
from prepare import HERE,MODEL,sha
from worker import save

def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--library',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    env=os.environ.copy();env['OMP_NUM_THREADS']='1'
    state=dict(status='running',stage='compile',started_at=time.time(),scope='diagnostic; no benchmark acceptance')
    save(out/'status.json',state)
    try:
        source=HERE/'tests/constant_pixel_csim.cpp'
        command=['g++','-O1','-std=c++14','-Wno-unknown-pragmas','-I/tools/Xilinx/Vitis/2024.2/include','-I'+str(MODEL),
            '-DWEIGHTS_DIR="'+str(MODEL/'firmware/weights')+'"',str(source),str(MODEL/'firmware/prod_res256_manualA_coyote_accel.cpp'),
            '/usr/lib/x86_64-linux-gnu/libgmp.so.10','-pthread','-o',str(out/'reference')]
        with (out/'compile.log').open('w') as log:subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        state['stage']='reference';save(out/'status.json',state)
        with (out/'reference.log').open('w') as log:subprocess.run([str(out/'reference'),str(out/'reference.csv')],cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        reference=list(csv.DictReader((out/'reference.csv').open()));assert len(reference)==256
        # Established production-board reference anchors, not self-generated acceptance.
        cases=HERE.parent/'runs/board_benchmark_20261008_130137/diagnostics/runtime_cases.tsv'
        known={line.split('\t')[0]:line.split('\t')[5] for line in cases.read_text().splitlines()}
        for byte in [0,128,255]:assert int(reference[byte]['logit_hex'],16)==int(known['raw_'+str(byte)],16)
        inputs=out/'inputs';inputs.mkdir();rows=[]
        for row in reference:
            byte=int(row['raw_byte']);path=inputs/f'constant_{byte:03d}.bin';path.write_bytes(bytes([byte])*65536)
            rows.append('\t'.join([f'constant_{byte:03d}','diagnostic',str(path),'65536',sha(path),row['logit_hex']]))
        (out/'cases.tsv').write_text('\n'.join(rows)+'\n')
        save(out/'source_manifest.json',dict(test_sha256=sha(source),library_sha256=sha(args.library),reference_sha256=sha(out/'reference.csv'),cases_sha256=sha(out/'cases.tsv')))
        state['stage']='board';save(out/'status.json',state)
        command=[sys.executable,str(HERE/'runtime_benchmark.py'),str(out/'cases.tsv'),str(out/'observations.csv'),str(out/'clock.csv'),'7','1','0','--library',str(args.library.resolve()),'--diagnostic']
        with (out/'board.log').open('w') as log:rc=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
        if rc not in [0,2]:raise RuntimeError('Board diagnostic did not complete: '+str(rc))
        observed=list(csv.DictReader((out/'observations.csv').open()))
        if len(observed)!=256:raise RuntimeError('Incomplete constant sweep')
        ref_by_bits={}
        for row in reference:ref_by_bits.setdefault(int(row['logit_hex'],16),[]).append(int(row['raw_byte']))
        matches=[]
        for row in observed:
            byte=int(row['case_id'].split('_')[-1]);bits=int(row['csr_26'])&0xffffffff
            matches.append(dict(input_byte=byte,actual_hex=f'{bits:08x}',expected_hex=reference[byte]['logit_hex'],matching_reference_bytes=ref_by_bits.get(bits,[])))
        save(out/'mapping.json',dict(scope='exact logit matches only; collisions do not prove pixel mapping',entries=matches))
        state.update(status='completed',stage='complete',board_calls=256,exact_matches=sum(int(r['actual_hex'],16)==int(r['expected_hex'],16) for r in matches),mapped_to_any_constant=sum(bool(r['matching_reference_bytes']) for r in matches))
    except Exception as error:state.update(status='failed',error=str(error))
    state['finished_at']=time.time();save(out/'status.json',state);print(json.dumps(state),flush=True)
    return 0 if state['status']=='completed' else 1
if __name__=='__main__':raise SystemExit(main())
