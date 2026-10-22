#!/usr/bin/env python3
"""Summarize report-ineligible runtime investigations without selecting report inputs."""
import argparse,csv,json,statistics
from pathlib import Path

def main(root):
    index=json.loads((root/'index.json').read_text());rows=[];diagnostics=[]
    for e in index:
        if 'result' not in e or not Path(e['result']).is_file():continue
        result=json.loads(Path(e['result']).read_text())
        for r in result['measurements']:rows.append(dict(revision=e['id'],case_id=r['case_id'],input_bytes=r['input_bytes'],median_ms=r['median_ms'],p95_ms=r['p95_ms'],ratio_to_0_165_reference=r['median_ms']/.165,max_abs_error=r['max_abs_error'],first_call_seconds=r['first_call_seconds'],scope=r['scope'],report_eligible=False))
        p=Path(e['result']).with_name('profiles.json')
        if p.exists():
            for r in json.loads(p.read_text()):
                samples=r['samples'];diagnostics.append(dict(revision=e['id'],case_id=r['case_id'],kernel_sum_ms=statistics.median(x['kernel_sum_ms'] for x in samples),device_span_ms=statistics.median(x['device_span_ms'] for x in samples),host_diagnostic_ms=statistics.median(x['host_diagnostic_ms'] for x in samples),kernels=statistics.median(x['kernels'] for x in samples),unexpected_cpu_gather_copy=any(c['name']=='CopyDeviceToHost' and 'Gather' in c.get('to','') for c in r['copies'])))
    for name,data in [('summary.csv',rows),('diagnostics.csv',diagnostics)]:
        if data:
            with (root/name).open('w') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    text=['# GPU runtime iteration results','','These experiments are excluded from preprocessing-v2 reports. FP32 model and batch one are unchanged. GPU_BASELINE 0.165 ms is a reference with incomplete model/sample/timestamp provenance. Ratios are not claims of matched replication.','','| Revision | 4 MiB combined ms | Largest combined ms | Completed cases | Result |','| --- | ---: | ---: | ---: | --- |']
    for e in index:
        vals={r['case_id']:r['median_ms'] for r in rows if r['revision']==e['id']}
        text.append('| '+e['id']+' | '+(f"{vals['synthetic_4194304']:.4f}" if 'synthetic_4194304' in vals else '—')+' | '+(f"{vals['synthetic_134217664']:.4f}" if 'synthetic_134217664' in vals else '—')+' | '+str(len(vals))+' | '+('passed' if e['returncode']==0 else 'failed; retained log')+' |')
    text+=['','Combined timing: GPU input already available, host call through final scalar synchronization, without profiler. First-call/compilation cost is recorded separately. Kernel sums and first-to-last-kernel spans come from separate profiled diagnostics.','', 'No experiment is automatically adopted into either PDF. Hardware-path validation and an explicit later report choice are separate.']
    text += ['', 'Interpretation and stopping criteria:', '', '- CPU affinity/thread changes alone did not fix the delay. One TensorFlow graph reduced dispatch gaps; XLA fused preprocessing and reduced the graph to 23 GPU kernels.', '- R06 joint device spans are 0.188 ms at 4 MiB and 0.196 ms at the largest input, about 14–19% above the 0.165 ms reference. Its complete host call remains 0.432/0.421 ms; these are different timing scopes, not a claim of exact replication.', '- R08 failed largest-input correctness. The isolated ONNX/MIGraphX int64-index path had 45,053 wrong pixels; exact int32 indices restored parity. See diagnostics/onnx_preprocess{,_int32}. R09 covers only two representative sizes and has not passed board admission.', '- R09 is faster for 4 MiB but slower at the largest size. TensorFlow XLA was selected for hardware validation because it retains the existing framework and has consistent compute latency across the 15 tested workloads.', '- R10 then changes standard ONNX preprocessing to sample uint8 bytes before casting only the selected pixels to FP32. All 12 normal campaign workloads pass score/verdict parity; host-completed compute medians are 0.213–0.249 ms. Unlike TensorFlow uint8 Gather, this ONNX path executes entirely in one MIGraphX GPU partition. It has not undergone full boundary/board admission or GPU_HOST/P2P end-to-end measurement.', '- First-call compilation is outside steady-state timing and recorded per case. Static input-length specialization is a deployment tradeoff; an unseen length requires compilation/warmup.', '- Stop further runtime changes once the selected candidate passes hardware admission and timestamp/drift gates: gross CPU-fallback and graph-dispatch problems are explained, device execution is near the reference, and the corrected standard alternative now gives 0.21–0.25 ms host-completed compute. The 0.165 ms reference lacks exact model/sample/timing provenance, so remaining differences do not justify forcing numerical equivalence. No arbitrary numeric target is used.']
    hardware=root/'hardware_xla_concrete/summary.json'
    if hardware.exists():
        h=json.loads(hardware.read_text());text+=['', 'Hardware-path campaign: `hardware_xla_concrete/`; status '+h['status']+'. CPU64/NUMA1 matches preprocessing-v2; standalone R06 used CPU0–7/NUMA0.', '', '| Variant | 4 MiB host in-memory ms | Largest host in-memory ms |', '| --- | ---: | ---: |']
        for ident in ['OPT_1_STREAMING','OPT_7_GPU_HOST','OPT_8_GPU_P2P']:
            vals={r['case_id']:r['host_observed_ms']['median'] for r in h['rows'] if r['iteration']==ident and r['scope']=='resident'}
            text.append('| '+ident+' | '+f"{vals['synthetic_4194304']:.4f}"+' | '+f"{vals['synthetic_134217664']:.4f}"+' |')
        text+=['', 'Maximum baseline drift: '+f"{max(abs(x['relative_change']) for x in h['baseline_drift'])*100:.3f}%"+'. All experimental hardware data remain excluded from both refreshed PDFs.']
    (root/'RESULTS.md').write_text('\n'.join(text)+'\n')
    print('\n'.join(text))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);main(p.parse_args().root)
