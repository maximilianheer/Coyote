#!/usr/bin/env python3
"""Regenerate stock hls4ml firmware from a pinned model and full iteration config."""
import argparse, csv, hashlib, json, os
from pathlib import Path
os.environ.setdefault('TF_USE_LEGACY_KERAS', '1')
os.environ.setdefault('CUDA_VISIBLE_DEVICES', '')
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')
os.environ.setdefault('TF_NUM_INTRAOP_THREADS', '4')
os.environ.setdefault('TF_NUM_INTEROP_THREADS', '2')

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def generate(job, repo):
    import numpy as np
    import tensorflow as tf
    import keras, hls4ml
    from qkeras.utils import _add_supported_quantized_objects
    c=json.loads((job/'config/iteration.json').read_text()); hc=c['hls']; mc=c['model']
    if hls4ml.__version__ != hc['version']:
        raise RuntimeError('hls4ml version differs from pinned iteration')
    architecture=job/'config'/mc['architecture']; weights=repo/mc['weights']
    for p,d in [(architecture,mc['architecture_sha256']),(weights,mc['weights_sha256'])]:
        if sha(p)!=d:raise RuntimeError('Model identity changed: '+str(p))
    objects={};_add_supported_quantized_objects(objects)
    model=tf.keras.models.model_from_json(architecture.read_text(),custom_objects=objects)
    model.load_weights(weights)
    # Existing project compatibility shim: select the Keras-v2 hls4ml reader.
    keras.__version__='2.15.0'
    config=hls4ml.utils.config_from_keras_model(model,granularity='name',backend=hc['backend'])
    config['Model']=hc['Model']
    for name, values in hc['LayerName'].items():
        if name not in config['LayerName']:raise ValueError('Unknown layer '+name)
        config['LayerName'][name].update(values)
    inputs=repo/'models/res256/reproducibility/prepared_inputs/x_norm.npy'
    manifest=repo/'models/res256/reproducibility/prepared_inputs/manifest.csv'
    x=np.ascontiguousarray(np.load(inputs),dtype=np.float32)
    rows=list(csv.DictReader((job/'fixtures/production_hls_per_sample.csv').open()))
    samples=list(csv.DictReader(manifest.open()))
    if len(x)!=len(rows) or [r['sample_id'] for r in rows]!=[r['sample_id'] for r in samples]:
        raise RuntimeError('Prepared-input ordering differs from reference logits')
    n=hc['profiling_samples']
    if not 2 <= n <= len(x):raise ValueError('FIFO profiling requires at least two available frames')
    np.save(job/'profile_inputs.npy',x[:n])
    expected=np.asarray([float(r['logit']) for r in rows],dtype=np.float32)
    # The stock testbench requires BOTH files; otherwise it silently uses defaults.
    np.save(job/'profile_predictions.npy',expected[:n].reshape(-1,1))
    if hc['fifo_depth_optimization']:
        from hls4ml.model.optimizer import get_optimizer
        get_optimizer('vitis:fifo_depth_optimization').configure(profiling_fifo_depth=hc['profiling_depth'])
        config['Flows']=['vitis:fifo_depth_optimization']
        from iteration_cosim import configure_batch_fifo_profiling, configure_profile_reuse
        configure_batch_fifo_profiling(hls4ml.backends.get_backend(hc['backend']),job)
        configure_profile_reuse(hls4ml.backends.get_backend(hc['backend']),job)
    (job/'hls_config.json').write_text(json.dumps(config,indent=2)+'\n')
    graph=hls4ml.converters.convert_from_keras_model(model,hls_config=config,output_dir=str(job/'generated'),
        project_name='iteration_model',backend=hc['backend'],io_type=hc['io_type'],part=hc['part'],
        clock_period=hc['clock_period'],clock_uncertainty=hc['clock_uncertainty'],
        input_data_tb=str(job/'profile_inputs.npy'),
        output_data_tb=str(job/'profile_predictions.npy'))
    graph.write()
    if any(layer.name.endswith('_linear') for layer in graph.get_layers()):
        raise RuntimeError('Unexpected unfused linear casts; check explicit precision configuration')
    package=Path(hls4ml.__file__).parent
    (job/'generator_identity.json').write_text(json.dumps({'version':hls4ml.__version__,
        'files':{str(p.relative_to(package)):sha(p) for p in package.rglob('*')
                 if p.is_file() and p.suffix in {'.py','.h','.hpp','.tcl'}}},indent=2)+'\n')
    if hc['fifo_depth_optimization'] and not (job/'generated/fifo_depths.json').is_file():
        raise RuntimeError('Native FIFO pass did not produce its depth report')
    if hc['fifo_depth_optimization']:
        inputs_dat=job/'generated/tb_data/tb_input_features.dat'
        predictions_dat=job/'generated/tb_data/tb_output_predictions.dat'
        results_log=job/'generated/tb_data/rtl_cosim_results.log'
        for path in [inputs_dat,predictions_dat,results_log]:
            if not path.is_file() or len(path.read_text().splitlines())!=n:
                raise RuntimeError('FIFO profiling did not use the selected frame count: '+str(path))
        # hls4ml prints only six significant digits; compare at that print precision.
        actual=np.loadtxt(results_log,ndmin=1).reshape(-1)
        if not np.allclose(actual,expected[:n],rtol=5e-6,atol=1e-6):
            raise RuntimeError('FIFO profiling outputs do not match the selected real inputs')
        (job/'fifo_profile_inputs.json').write_text(json.dumps({'samples':n,
            'sample_ids':[r['sample_id'] for r in rows[:n]],
            'files':{str(p.relative_to(job)):sha(p) for p in [inputs_dat,predictions_dat,results_log]}},indent=2)+'\n')
    resolved={layer.name:{'class':layer.class_name,'reuse_factor':layer.get_attr('reuse_factor'),
        'strategy':layer.get_attr('strategy')} for layer in graph.get_layers()}
    for name,values in hc['LayerName'].items():
        if 'ReuseFactor' in values and resolved[name]['reuse_factor']!=values['ReuseFactor']:
            raise RuntimeError('hls4ml adjusted the requested reuse factor for '+name)
    (job/'resolved_layers.json').write_text(json.dumps(resolved,indent=2)+'\n')
    graph.compile()
    predicted=np.asarray(graph.predict(x)).reshape(-1).astype(np.float32)
    expected=np.asarray([float(r['logit']) for r in rows],dtype=np.float32)
    np.save(job/'generated_logits.npy',predicted)
    result={'status':'passed' if np.array_equal(predicted.view(np.uint32),expected.view(np.uint32)) else 'failed',
        'samples':len(x),'exact_mismatches':int(np.count_nonzero(predicted.view(np.uint32)!=expected.view(np.uint32))),
        'max_abs_error':float(np.max(abs(predicted-expected))),'input_sha256':sha(inputs),
        'input_manifest_sha256':sha(manifest),'reference_sha256':sha(job/'fixtures/production_hls_per_sample.csv'),
        'hls4ml_version':hls4ml.__version__,'tensorflow_version':tf.__version__,'weights_sha256':sha(weights)}
    (job/'model_parity.json').write_text(json.dumps(result,indent=2)+'\n')
    if result['status']!='passed':raise RuntimeError('Regenerated model differs from pinned production logits')
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('repo',type=Path)
    a=p.parse_args();generate(a.job.resolve(),a.repo.resolve())
