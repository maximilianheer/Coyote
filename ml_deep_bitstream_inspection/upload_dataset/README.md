# Upload Dataset

This directory is the publishable subset of the Coyote deep-bitstream
inspection datasets. It contains the inputs and source context needed for ML
experiments without the much larger Vivado build trees and intermediate files
from `../datasets/`.

## Contents

| Dataset | Bitstreams |
| --- | ---: |
| `full_dataset_it1` | 150 |
| `full_dataset_it2` | 150 |
| `full_dataset_it3` | 146 |
| `full_dataset_it4_big_ro` | 78 |
| **Total** | **524** |

Each populated iteration follows this layout:

```text
full_dataset_*/
└── artifacts/
    ├── bitstreams/
    │   └── config_NNN/
    │       └── vfpga_cNNN_0.bin
    ├── sources/
    │   ├── apps/
    │   └── floorplans/
    ├── manifest.csv
    ├── manifest_available.csv
    ├── reports_raw.csv
    └── dropped_samples.csv          # present where applicable
```

The `.bin` files are Xilinx/Coyote partial-bitstream samples and are stored with
Git LFS. Source snapshots and CSV files are ordinary Git objects.

## Manifests

`manifest.csv` is the primary sample index. Its fields identify the class,
application or ring-oscillator variant, floorplan, tool version, relative
bitstream path, timing and validation status, resource counts, and SHA-256 file
hash. The large-RO iteration adds target-device and target-LUT fields.

Resolve a manifest bitstream path relative to the iteration's
`artifacts/bitstreams/` directory. For example, a value of
`config_000/vfpga_c000_0.bin` refers to:

```text
artifacts/bitstreams/config_000/vfpga_c000_0.bin
```

The other CSV files provide:

- `manifest_available.csv`: samples whose artifacts were available when the
  dataset was packaged.
- `reports_raw.csv`: collected implementation and resource-report data.
- `dropped_samples.csv`: samples excluded from iterations where applicable.

## Downloading the data

A normal Git LFS clone downloads all bitstreams automatically:

```bash
git clone https://github.com/maximilianheer/Coyote.git
```

To clone without downloading large LFS objects initially:

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone \
  https://github.com/maximilianheer/Coyote.git
```

Then download the entire upload dataset:

```bash
cd Coyote
git lfs pull --include="ml_deep_bitstream_inspection/upload_dataset/**"
```

Or download one iteration only:

```bash
git lfs pull \
  --include="ml_deep_bitstream_inspection/upload_dataset/full_dataset_it4_big_ro/**"
```

## Integrity checks

Confirm that all expected LFS objects are present:

```bash
git lfs fsck
find ml_deep_bitstream_inspection/upload_dataset \
  -type f -name '*.bin' | wc -l
```

The second command should report `524` after all four iterations are fetched.
Individual bitstreams can be checked against the `file_hash` column using
`sha256sum`.

## Excluded material

This publication intentionally excludes:

- Vivado build and checkpoint directories
- Synthesis, implementation, and batch logs
- `.Xil` and tool-cache directories
- Job-control state and temporary files
- Complete hardware project copies

Those files are regeneration intermediates rather than ML dataset inputs. The
original frozen dataset-generation trees remain under `../datasets/` in the
research workspace.
