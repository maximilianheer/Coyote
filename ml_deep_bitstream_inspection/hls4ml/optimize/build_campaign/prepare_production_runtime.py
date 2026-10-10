#!/usr/bin/env python3
"""Expose an isolation build through the unchanged RawCoyoteOverlay layout."""
import argparse, json
from pathlib import Path
from prepare import sha

def prepare(jobdir, bitstream):
    jobdir=jobdir.resolve();bitstream=bitstream.resolve()
    if not bitstream.is_file():raise RuntimeError('Complete bitstream required')
    library=jobdir/'host_build/lib/libCoyoteInference.so'
    coyote=jobdir/'host_build/coyote/libcoyote.so'
    if not library.is_file() or not coyote.is_file():raise RuntimeError('Missing matching runtime libraries')
    project=jobdir/'runtime_project'
    build=project/'build';build.mkdir(parents=True,exist_ok=True)
    sw=build/'prod_res256_manualA_coyote_accel_cyt_sw'
    hw=build/'prod_res256_manualA_coyote_accel_cyt_hw/bitstreams'
    (sw/'lib').mkdir(parents=True,exist_ok=True);hw.mkdir(parents=True,exist_ok=True)
    for link,target in [(sw/'lib/libCoyoteInference.so',library),(sw/'libCoyote.so',coyote),(hw/'cyt_top.bit',bitstream)]:
        if link.is_symlink():
            if link.resolve()!=target:raise RuntimeError('Preserve prior runtime view before selecting a different artifact')
        elif link.exists():raise RuntimeError('Refusing to replace existing runtime artifact')
        else:link.symlink_to(target)
    (project/'artifact_manifest.json').write_text(json.dumps({str(p):sha(p) for p in [library,coyote,bitstream]},indent=2))
    return project

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('jobdir',type=Path);parser.add_argument('bitstream',type=Path)
    args=parser.parse_args();print(prepare(args.jobdir,args.bitstream))
