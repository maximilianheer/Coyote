"""Process-local simulation adapter; no installed hls4ml or CNN kernel edits."""
import hashlib
import json
from pathlib import Path


def patch_project(project, script):
    build=project/'build_prj.tcl'
    original=build.read_text()
    marker='    remove_recursive_log_wave\n'
    if original.count(marker)!=1:
        raise RuntimeError('Cannot locate the native post-cosim-setup hook')
    patched=original.replace(marker,
        '    source {'+str(script)+'}\n    iteration_fifo_batch_setup $project_name\n'+marker)
    build.write_text(patched)
    digest=lambda data:hashlib.sha256(data).hexdigest()
    record={'scope':'simulation scripts only; native RTL and FIFO pass unchanged',
        'native_build_tcl_sha256':digest(original.encode()),'batch_build_tcl_sha256':digest(patched.encode()),
        'adapter_sha256':digest(script.read_bytes())}
    (project/'profiling_frontend.json').write_text(json.dumps(record,indent=2)+'\n')


def configure_batch_fifo_profiling(backend, job):
    writer=backend.writer
    original=writer.write_hls
    script=job/'tooling/iteration_templates/fifo_batch.tcl'
    def write(model):
        original(model)
        patch_project(Path(model.config.get_output_dir()),script)
    writer.write_hls=write


def configure_profile_reuse(backend, job):
    """Reuse a verified same-iteration RTL profile; let the native pass choose depths."""
    import shutil
    cache=job/'fifo_profile_cache'
    if not cache.exists():return
    manifest=json.loads((cache/'manifest.json').read_text())
    config=json.loads((job/'config/iteration.json').read_text())
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    if (manifest.get('status')!='passed' or manifest['iteration']!=config['id']
            or manifest['model_weights_sha256']!=config['model']['weights_sha256']
            or manifest['samples']!=config['hls']['profiling_samples']):
        raise RuntimeError('FIFO profile identity does not match this iteration')
    for name,h in manifest['files'].items():
        if digest(cache/name)!=h:raise RuntimeError('Changed profile evidence: '+name)
    native_build=backend.build
    def build(model,**options):
        if not options.get('fifo_opt'):return native_build(model,**options)
        project=Path(model.config.get_output_dir());firmware=project/'firmware'
        actual={str(p.relative_to(firmware)):digest(p) for p in firmware.rglob('*') if p.is_file()}
        if actual!=manifest['firmware']:
            raise RuntimeError('Regenerated profiling firmware differs from validated profile')
        for filename,key in [('tb_input_features.dat','inputs_sha256'),('tb_output_predictions.dat','predictions_sha256')]:
            if digest(project/'tb_data'/filename)!=manifest[key]:
                raise RuntimeError('Profiling test vectors changed: '+filename)
        database=project/(model.config.get_project_name()+'_prj/solution1/.autopilot/db')
        (database/'channel_depth_info').mkdir(parents=True,exist_ok=True)
        shutil.copy2(cache/'channel.zip',database/'channel_depth_info/channel.zip')
        shutil.copy2(cache/'channel_info.csv',database/'channel_info.csv')
        shutil.copy2(cache/'rtl_cosim_results.log',project/'tb_data/rtl_cosim_results.log')
        (project/'profile_reuse.json').write_text(json.dumps({
            'status':'passed','manifest_sha256':digest(cache/'manifest.json'),
            'firmware_exact_match':True,'test_vectors_exact_match':True,
            'selection':'Unmodified native vitis:fifo_depth_optimization parser and depth selection'},indent=2)+'\n')
        print('Reusing verified two-frame native FIFO profile; generated firmware and test vectors match exactly',flush=True)
        return {}
    backend.build=build
