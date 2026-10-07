#!/usr/bin/env python3
"""Generate isolated Coyote projects from immutable production sources."""
import hashlib
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
COYOTE = REPO.parent
PACKAGE = REPO/'hls4ml/reproducibility/prod_res256_coyote_accel_downsampler_hls4ml_e2e_20260524'
MODEL = PACKAGE/'sources/generated_project/src/hls/model_wrapper'
HELLO = REPO/'datasets/full_dataset_it1/hw/apps/benign_variants/V01_hello_world_nodbg'
INITIAL = {'H16': (0,0,3,3), 'H8': (0,0,3,1), 'H4': (0,0,1,1),
           'H2': (0,0,1,0), 'H1': (0,0,0,0)}
VARIANTS = {'I': 1, 'U': 2, 'N': 3, 'P': 4, 'C': 5, 'S_I': 6}
VARIANT_FILES = {'I': 'instrumented', 'U': 'uninstrumented', 'N': 'transport_only',
                 'P': 'preprocessing_only', 'C': 'inference_only', 'S_I': 'streaming_instrumented'}
HARDWARE = HERE/'hardware'


def source_manifest(dst):
    files = {}
    for directory in ['hw', 'host', 'reference', 'tests']:
        for path in (dst/directory).rglob('*'):
            if path.is_file(): files[str(path.relative_to(dst))] = sha(path)
    for path in [dst/'csim.cpp']:
        if path.exists(): files[str(path.relative_to(dst))] = sha(path)
    return files


def verify_sources(dst):
    from hbm_clock import verify_hbm_clock_sources
    verify_hbm_clock_sources(dst)
    manifest = json.loads((dst/'source_manifest.json').read_text())
    actual = source_manifest(dst)
    if actual != manifest['files']:
        raise RuntimeError('Source hashes changed since preparation; use a fresh attempt')
    return sha(dst/'source_manifest.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def add_hierarchical_reports(text):
    """Keep ordinary reports and add hierarchy for component cost attribution."""
    if '# optimization hierarchy reports' in text:
        return text
    return re.sub(r'(?m)^(\s*)report_utilization -file "([^"\n]+)\.rpt"',
        lambda m: m[0]+'\n'+m[1]+'# optimization hierarchy reports\n'+m[1]
        +'report_utilization -hierarchical -file "'+m[2]+'_hierarchical.rpt"', text)

def copy_coyote(dst):
    # Copy writable trees: scripts create hw/ip/dev and may populate source-local IP.
    for name in ['cmake', 'scripts', 'hw', 'sw', 'sim']:
        shutil.copytree(COYOTE/name, dst/name, symlinks=False,
                        ignore=shutil.ignore_patterns('__pycache__', '.Xil'), dirs_exist_ok=True)
    t = dst/'scripts/hls/comp_hls.tcl.in'
    s = t.read_text()
    anchor = '                        set_top "$krnl"'
    s = s.replace(anchor, '''                        if {[file isdirectory "${CMAKE_SOURCE_DIR}/$src_dir/hls/$krnl/firmware"]} {
                            file copy -force "${CMAKE_SOURCE_DIR}/$src_dir/hls/$krnl/firmware" "$build_dir/$project\\_config_$i/user\\_c$i\\_$j/hdl/ext/$krnl\\_hls"
                            foreach cpp [glob -nocomplain "$build_dir/$project\\_config_$i/user\\_c$i\\_$j/hdl/ext/$krnl\\_hls/firmware/*.cpp"] {
                                add_files $cpp -cflags "-std=c++14"
                            }
                        }
''' + anchor)
    s = s.replace('-std=c++11', '-std=c++14')
    t.write_text(s)
    # Fail fast on absent IP/module errors rather than continuing to implementation.
    base = dst/'scripts/base.tcl.in'
    base.write_text(base.read_text() + '\nset_param general.maxThreads 8\n')
    for filename in ['synth_shell.tcl.in','synth_user.tcl.in']:
        p=dst/'scripts/synth'/filename
        p.write_text(p.read_text().replace('launch_runs -jobs $cfg(cores)', 'launch_runs -jobs 1'))
    for template in ['scripts/impl/pnr_shell.tcl.in', 'scripts/dyn/flow_app.tcl.in',
                     'scripts/dyn/flow_dyn_ultrascale_plus.tcl.in']:
        p = dst/template
        p.write_text(add_hierarchical_reports(p.read_text()))


def floorplan(rect):
    x0,y0,x1,y1 = rect
    ranges = f'CLOCKREGION_X{x0}Y{y0}:CLOCKREGION_X{x1}Y{y1}'
    # XDC does not execute arbitrary Tcl loops. Procedural narrowing runs in a
    # maintained Tcl script after link_design, before placement/checkpointing.
    s = f'''create_pblock pblock_inst_user_wrapper_0
add_cells_to_pblock [get_pblocks pblock_inst_user_wrapper_0] [get_cells -quiet inst_shell/inst_dynamic/inst_user_wrapper_0]
resize_pblock [get_pblocks pblock_inst_user_wrapper_0] -add {{{ranges}}}
set_property SNAPPING_MODE ON [get_pblocks pblock_inst_user_wrapper_0]
set_property IS_SOFT FALSE [get_pblocks pblock_inst_user_wrapper_0]
'''
    return s


def configure_refinement(jobdir):
    """Attach maintained procedural floorplanning to the generated implementation flow."""
    refinement = jobdir/'hw/floorplan_refine.tcl'
    if not refinement.is_file():
        raise RuntimeError('Missing post-link floorplan refinement source')
    flow = jobdir/'build/flow_dyn.tcl'
    original = flow.read_text()
    anchor = 'eval $cmd\nwrite_checkpoint -force "$dcp_dir/config_0/shell_linked_c0.dcp"'
    if original.count(anchor) != 1:
        raise RuntimeError('Cannot identify unique config-0 post-link floorplan hook')
    (jobdir/'build/flow_dyn_before_refinement.tcl').write_text(original)
    flow.write_text('set_msg_config -id {Designutils 20-1307} -new_severity ERROR\n'+original.replace(anchor,
        'eval $cmd\nsource {'+str(refinement)+'}\n'
        'write_checkpoint -force "$dcp_dir/config_0/shell_linked_c0.dcp"'))
    (jobdir/'floorplan_implementation.json').write_text(json.dumps(dict(
        source_manifest_sha256=sha(jobdir/'source_manifest.json'),
        original_script_sha256=hashlib.sha256(original.encode()).hexdigest(),
        implementation_script_sha256=sha(flow), refinement_sha256=sha(refinement)), indent=2))


def choose_geometry(job, state, root):
    if job in INITIAL: return INITIAL[job], False, False
    successful = [j for j in state['jobs'] if j['id'] in INITIAL and j['status']=='passed']
    if not successful:
        raise RuntimeError('No initial hello-world implementation passed; refinement needs a feasible anchor')
    best = min(successful, key=lambda j:j['artifacts']['partial_bytes'])
    rect = tuple(best['geometry'])
    if job == 'HN':
        x0,y0,x1,y1 = rect
        candidate = ((x0,y0,x0+(x1-x0)//2,y1) if x1>x0 else
                     (x0,y0,x1,y0+(y1-y0)//2) if y1>y0 else rect)
        if root is not None:
            # Failed coarse geometries remain relevant after their jobs are
            # archived/requeued at a different location.
            for manifest in (root/'attempts').glob('*/*/job.json'):
                prior = json.loads(manifest.read_text())
                log = manifest.parent/'app.log'
                if (tuple(prior.get('geometry',[])) == candidate and log.exists()
                        and 'UTLZ-1' in log.read_text(errors='replace')):
                    return rect, True, False
            for previous in state['jobs']:
                log = root/'jobs'/previous['id']/'app.log'
                if (tuple(previous.get('geometry',[])) == candidate and log.exists()
                        and 'UTLZ-1' in log.read_text(errors='replace')):
                    # Keep the feasible BRAM columns; narrow only logic columns.
                    return rect, True, False
        if candidate != rect:return candidate, False, False
        return rect, True, False
    if job == 'HR':
        x0,y0,x1,y1 = rect
        return (x0,y0+1,x1,y1+1), False, False
    if job == 'HE':
        successful += [j for j in state['jobs'] if j['id'] in ('HN','HR') and j['status']=='passed']
        best = min(successful, key=lambda j:j['artifacts']['partial_bytes'])
        return tuple(best['geometry']), best.get('narrow',False), True
    raise ValueError(job)


def prepare(root, job, state):
    dst = root/'jobs'/job['id']
    dst.mkdir(parents=True, exist_ok=False)
    coyote = dst/'coyote'
    copy_coyote(coyote)
    hw = dst/'hw'; hw.mkdir(exist_ok=True)
    ident = job['id']; diagnostic = ident in VARIANTS
    if job.get('hbm_axi_mhz'):
        if not diagnostic:
            raise ValueError('HBM clock fallback only applies to diagnostic builds')
        from hbm_clock import configure_hbm_clock
        configure_hbm_clock(dst, job['hbm_axi_mhz'])
    if diagnostic:
        sw = dst/'host'; sw.mkdir(exist_ok=True)
        shutil.copy2(HERE/'templates/host_bench.cpp', sw/'host_bench.cpp')
        shutil.copy2(HERE/'templates/host_CMakeLists.txt', sw/'CMakeLists.txt')
        src = hw/'src'; src.mkdir(exist_ok=True)
        shutil.copytree(MODEL, src/'hls/model_wrapper', dirs_exist_ok=True)
        kernel = src/'hls/model_wrapper'
        variant = VARIANT_FILES[ident]
        shutil.copy2(HARDWARE/'variants'/f'{variant}.cpp', kernel/'model_wrapper.cpp')
        for header in (HARDWARE/'common').glob('*.hpp'):
            shutil.copy2(header, kernel/header.name)
        api = ('streaming_api.hpp' if ident == 'S_I' else
               'uninstrumented_api.hpp' if ident == 'U' else 'instrumented_api.hpp')
        shutil.copy2(HARDWARE/'common'/api, kernel/'model_wrapper.hpp')
        (src/'hdl').mkdir(exist_ok=True)
        shutil.copy2(HARDWARE/'benchmark_control.sv', src/'hdl')
        shutil.copy2(HARDWARE/'variants'/f'{variant}.svh', src/'hdl/benchmark_variant.svh')
        shutil.copy2(HARDWARE/'vfpga_top.svh', src/'vfpga_top.svh')
        floor = ''
        # The reference uses its original source and prototype, without rewriting.
        shutil.copy2(HERE/'templates/csim.cpp', dst/'csim.cpp')
        (dst/'reference').mkdir()
        for name in ['model_wrapper.cpp', 'model_wrapper.hpp']:
            shutil.copy2(MODEL/name, dst/'reference'/name)
        shutil.copytree(HERE/'tests', dst/'tests',
                        ignore=shutil.ignore_patterns('__pycache__'))

    else:
        shutil.copytree(HELLO, hw/'src', dirs_exist_ok=True)
        shutil.copy2(HARDWARE/'hello_world/vfpga_top.svh', hw/'src/vfpga_top.svh')
        shutil.copytree(HARDWARE/'hello_world/hdl', hw/'src/hdl', dirs_exist_ok=True)
        # The frozen nodbg source accidentally drives TVALID with an RO.
        # Use the maintained benign datapath and omit the now-unused RO module.
        (hw/'src/hdl/ring_oscillator.sv').unlink(missing_ok=True)
        rect, narrow, disable = (tuple(job['geometry_override']),False,False) if 'geometry_override' in job else choose_geometry(ident,state,root)
        job.update(geometry=list(rect), narrow=narrow, disable_expansion=disable)
        (hw/'floorplan.xdc').write_text(floorplan(rect))
        if narrow:
            shutil.copy2(HERE/'implementation/narrow_floorplan.tcl', hw/'floorplan_refine.tcl')
        floor = 'set(FPLAN_PATH "${CMAKE_SOURCE_DIR}/floorplan.xdc")\n'
        if disable:
            for template in ['scripts/impl/pnr_shell.tcl.in','scripts/dyn/flow_app.tcl.in','scripts/dyn/flow_dyn_ultrascale_plus.tcl.in']:
                p=coyote/template
                p.write_text('set_param hd.routingContainmentAreaExpansion false\n'+p.read_text())
    # Every design uses the same maintained, minimal debug infrastructure.
    (hw/'src/hdl').mkdir(exist_ok=True)
    shutil.copy2(HARDWARE/'debug_probe.svh', hw/'src/hdl/debug_probe.svh')
    shutil.copy2(HARDWARE/'init_ip.tcl', hw/'src/init_ip.tcl')
    project='opt_'+ident.lower()
    (hw/'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.5)
set(CYT_DIR "{coyote}")
set(CMAKE_MODULE_PATH "${{CYT_DIR}}/cmake")
find_package(CoyoteHW REQUIRED)
project({project})
set(FDEV_NAME "u55c")
set(N_REGIONS 1)
set(N_CONFIG 1)
set(EN_PR {0 if diagnostic else 1})
set(EN_STRM 1)
set(N_STRM_AXI {1 if diagnostic else 2})
set(EN_MEM {1 if diagnostic else 0})
set(COMP_CORES 8)
set(BUILD_OPT {1 if diagnostic else 0})
{floor}validation_checks_hw()
load_apps(VFPGA_C0_0 "src")
create_hw()
''')
    manifest = {'files': source_manifest(dst), 'production_package': str(PACKAGE),
                'variant': ident, 'attempt': job.get('attempt', 1),
                'maintained_hardware': {str(p.relative_to(HARDWARE)): sha(p)
                    for p in HARDWARE.rglob('*') if p.is_file()},
                'build_scripts': {str(p.relative_to(coyote)): sha(p)
                    for folder in ['scripts', 'cmake']
                    for p in (coyote/folder).rglob('*') if p.is_file()}}
    (dst/'source_manifest.json').write_text(json.dumps(manifest, indent=2))
    job.update(project=project, prepared=True)
    return dst
