#!/usr/bin/env python3
"""Accept preprocessing-v2, publish both reports, then launch separately recorded experiments."""
import argparse,hashlib,json,os,shutil,subprocess,sys,time,zipfile
from pathlib import Path

def read(p):return json.loads(p.read_text())
def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def notice(message):
    subprocess.run(['curl','-fsS','--max-time','15','-d',message,'https://ntfy.sh/coyote-build-sdeheredia'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def main(statefile):
    s=read(statefile);root=Path(s['root']);repo=Path(s['repo']);base=repo/'hls4ml/optimize/build_campaign';workflow=root/'workflow.json'
    state=dict(status='running',stage='waiting_measurements',pid=os.getpid(),started_at=time.time());save(workflow,state)
    def stage(name):state.update(stage=name,heartbeat=time.time());save(workflow,state)
    def command(name,args,env=None):
        stage(name)
        with (root/'logs'/f'{name}.log').open('w') as f:subprocess.run(args,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    try:
        while True:
            current=read(root/'status.json')
            if current['status'] in ['passed','failed']:break
            stage('waiting_'+current.get('active','measurements')+'_'+current.get('stage',''))
            time.sleep(10)
        recheck=None
        if current['status']=='failed':
            if not current.get('error','').startswith('Baseline drift exceeds 5%'):raise RuntimeError(current)
            initial=read(root/'summary.json');names={x['case_id'] for x in initial['baseline_drift'] if abs(x['relative_change'])>.05}
            recheck=root/'rechecks/matched_01';recheck.mkdir(parents=True)
            for name in ['jobs','logs','diagnostics']:(recheck/name).mkdir()
            shutil.copytree(root/'tooling',recheck/'tooling',ignore=shutil.ignore_patterns('__pycache__'))
            (recheck/'software').symlink_to(root/'software',target_is_directory=True)
            cfg=read(root/'campaign.json');cfg.update(profile_enabled=False,parent_campaign=str(root),full_cases=len(names),software_files={});save(recheck/'campaign.json',cfg)
            selected=[line for line in (root/'cases.tsv').read_text().splitlines() if line.split('\t')[0] in names]
            for name in ['cases.tsv','pilot.tsv']:(recheck/name).write_text('\n'.join(selected)+'\n')
            shutil.copy2(root/'admission.tsv',recheck/'admission.tsv')
            p=recheck/'tooling/final_benchmark.py';text=p.read_text().replace("modes=['admission','pilot','full']+(['profile'] if i['kind']=='gpu' else [])","modes=['admission','pilot','full']")
            text=text.replace("if image['kind']!='gpu':continue","if image['kind']!='gpu' or not cfg.get('profile_enabled',True):continue")
            p.write_text(text);save(recheck/'status.json',dict(status='prepared',stage='matched_drift_recheck'))
            save(root/'diagnostics/pre_recheck_summary.json',initial)
            command('seal_recheck',['python3',str(p),'seal',str(recheck)])
            notice('Preprocessing-v2: baseline drift requires a matched workload recheck; original evidence retained. No FPGA builds.')
            command('matched_recheck',['python3',str(p),'run',str(recheck)])
        args=['python3',str(base/'accept_benchmark.py'),str(root)]
        if recheck:args+=['--recheck',str(recheck)]
        command('accept_measurements',args)
        for report in map(Path,s['reports']):
            command('report_'+('full' if report.name.startswith('final') else 'focused'),[str(repo/'ml_baseline/.venv/bin/python'),str(report/'build_report.py')])
            pdf=next(report.glob('*.pdf'));info=subprocess.check_output(['pdfinfo',str(pdf)],text=True)
            (report/'data/pdfinfo.txt').write_text(info)
            text=subprocess.check_output(['pdftotext',str(pdf),'-'],text=True)
            assert 'preprocessing-v2' in text or 'preprocessing-v2' in text.lower()
            if report.name.startswith('focused'):
                for forbidden in ['4,194,240','4,194,241','4,194,242','HOST_TO_GPU','FPGA_P2P_GPU','resident']:assert forbidden not in text,forbidden
            bundle=report.with_name(report.name+'_bundle.zip')
            with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
                for p in sorted(report.rglob('*')):
                    if p.is_file() and '__pycache__' not in p.parts:z.write(p,str(p.relative_to(report.parent)))
            with zipfile.ZipFile(bundle) as z:assert z.testzip() is None
        stage('reports_generated_pending_visual_review')
        notice('Preprocessing-v2: all-five-variant measurements accepted; full and focused PDFs generated in new folders. Visual review pending. Later runtime investigation stays separate.')
        stage('runtime_investigation')
        command('runtime_investigation',['python3',str(base/'gpu/investigate_runtime.py'),str(root),s['experiments']])
        state.update(status='awaiting_review',stage='reports_and_experiments_ready',finished_at=time.time());save(workflow,state)
    except BaseException as e:
        state.update(status='failed',error=str(e),finished_at=time.time());save(workflow,state);notice('Preprocessing-v2 workflow needs diagnosis: '+str(e));raise
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('statefile',type=Path);main(p.parse_args().statefile)
