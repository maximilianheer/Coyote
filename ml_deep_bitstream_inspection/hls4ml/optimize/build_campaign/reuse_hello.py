"""Reuse only identical, verified hello-world shell inputs for floorplan trials."""
import json
from pathlib import Path
import re
import shutil
from prepare import sha, verify_sources

SEEDS = ['shell_routed.dcp','shell/shell_synthed.dcp','config_0/user_synthed_c0_0.dcp']

def configuration(jobdir):
    text=(jobdir/'build/base.tcl').read_text()
    return {key:value.replace(str(jobdir),'$JOB')
        for key,value in re.findall(r'^set cfg\(([^)]+)\)\s+(.+)$',text,re.M)
        if key != 'fplan_path'}

def signature(jobdir):
    manifest=json.loads((jobdir/'source_manifest.json').read_text())
    # App RTL, IP creation Tcl, shell HDL, block designs, constraints, and the
    # static checkpoint must match. Generated IP caches are never imported.
    core={}
    for directory in ['hdl','bd','constraints']:
        for path in (jobdir/'coyote/hw'/directory).rglob('*'):
            if path.is_file():core[str(path.relative_to(jobdir/'coyote'))]=sha(path)
    static=jobdir/'coyote/hw/checkpoints/static_routed_locked_u55c.dcp'
    core[str(static.relative_to(jobdir/'coyote'))]=sha(static)
    return dict(app={k:v for k,v in manifest['files'].items() if k.startswith('hw/src/')},
                scripts=manifest['build_scripts'],core=core,configuration=configuration(jobdir))

def try_reuse(jobdir, job):
    # HE changes routing-containment expansion, so it cannot share this seed.
    if job['id'] not in ('H1','HN','HR'):return False
    reference=jobdir.parent/'H2'
    from worker import collect_artifacts
    try:
        progress=json.loads((reference/'progress.json').read_text())
        if progress['status']!='passed':return False
        ref_manifest=verify_sources(reference)
        target_manifest=verify_sources(jobdir)
        collect_artifacts(reference/'build','H2')
        sig=signature(jobdir)
        if sig!=signature(reference):
            print('Hello shell reuse skipped: source/configuration mismatch',flush=True)
            return False
        hashes={name:sha(reference/'build/checkpoints'/name) for name in SEEDS}
    except (FileNotFoundError,KeyError,RuntimeError) as exc:
        print('Hello shell reuse unavailable:',exc,flush=True)
        return False
    for name in SEEDS:
        dst=jobdir/'build/checkpoints'/name
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(reference/'build/checkpoints'/name,dst)
        if sha(dst)!=hashes[name]:raise RuntimeError('Copied shell checkpoint hash mismatch')
    for folder in ['reports/config_0','logs','bitstreams/config_0']:
        (jobdir/'build'/folder).mkdir(parents=True,exist_ok=True)
    (jobdir/'shell_reuse.json').write_text(json.dumps(dict(reference=str(reference),
        reference_manifest_sha256=ref_manifest,target_manifest_sha256=target_manifest,
        source_signature=sig,checkpoint_sha256=hashes,
        scope='Identical common shell/app seeds only; new floorplan implementation and bitgen required'),indent=2))
    print('Verified hello shell reuse:',reference,flush=True)
    return True
