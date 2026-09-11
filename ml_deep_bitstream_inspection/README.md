# ML Deep Bitstream Inspection

This directory is the frozen research artifact for deep-learning inspection of
Coyote FPGA partial bitstreams. It groups dataset-generation sources, the
PyTorch ML baseline, and the hls4ml/U55C production flow under one PR surface.

## Layout

| Path | Purpose |
| --- | --- |
| `datasets/` | Frozen dataset-generation iterations and manifests |
| `upload_dataset/` | Publishable dataset subset containing 524 partial bitstreams, CSV manifests, and the matching HDL/HLS source snapshots |
| `ml_baseline/` | PyTorch bitstream classifiers, dataset loader, notebooks, and training scripts |
| `hls4ml/` | YAML-driven hls4ml production pipeline, final results, and reproducibility packages |

The external bitstream vault is not stored here. By default the loader searches
`/mnt/scratch/sdeheredia/coyote_vault_work`; set `COYOTE_DATASET_VAULT` to
reproduce from another vault location.

## Reproducibility

```bash
set -euo pipefail
cd /pub/scratch/sdeheredia/Coyote/ml_deep_bitstream_inspection/ml_baseline
source .venv/bin/activate

cd /pub/scratch/sdeheredia/Coyote/ml_deep_bitstream_inspection/hls4ml
../ml_baseline/.venv/bin/python scripts/hls4ml_run.py --config configs/hls4ml_production/res256_layers7_W8A8_P50_manualA_production.yaml --stages ''
../ml_baseline/.venv/bin/python scripts/hls4ml_run.py --config configs/hls4ml_production/res512_layers7_W8A8_P50_manualA_production.yaml --stages ''
```

Final production summaries live under `hls4ml/artifacts_production/`; packaged
replay manifests live under `hls4ml/reproducibility/`.

## Publishable dataset

`upload_dataset/` is the compact, GitHub-facing form of the generated datasets.
It mirrors the four populated dataset iterations while omitting Vivado build
trees, checkpoints, logs, jobs, and other regeneration intermediates. Each
iteration contains its available `.bin` partial bitstreams under
`artifacts/bitstreams/`, the corresponding source snapshot under
`artifacts/sources/`, and artifact-level CSV manifests.

The 524 `.bin` files are stored with Git LFS. A clone that skipped LFS downloads
can retrieve only this dataset with:

```bash
git lfs pull --include="ml_deep_bitstream_inspection/upload_dataset/**"
```

See [`upload_dataset/README.md`](upload_dataset/README.md) for the layout,
iteration counts, manifest fields, integrity checks, and selective download
examples.
