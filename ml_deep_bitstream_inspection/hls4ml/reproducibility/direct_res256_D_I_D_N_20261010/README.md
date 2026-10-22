# D_I / D_N / R_S reproducibility checkpoint — 2026-10-10

- **D_I:** optimized streaming preprocessing + CNN; first-pixel launch guard.
- **D_N:** measured transport latency/resource floor; no CNN.
- **R_S:** streaming reference with unchanged production CNN firmware/weights; no D_I conv0 specialization. Streaming wrapper + first-pixel guard.
- Package directory name retained for existing links; it now contains all three variants.
- **Checkpoint only:** existing measurements copied; no new builds, board operations, or benchmark trials.
- **Package-local rebuild/replay commands:** statically checked; not independently hardware-validated.
- Active optimization campaigns and the May production packages remain unchanged.

## Contents

| Path | Contents |
| --- | --- |
| [identities.json](identities.json) | Exact measured images and original source identities |
| `sources/designs/` | Required C++/RTL, CNN weights, pristine CNN reference, build configurations |
| `sources/coyote/` | Pinned vendor build/runtime sources; required U55C static platform checkpoint |
| `sources/runtime/`, `sources/production_runtime/`, `sources/driver/` | Production-derived native runtime; standard reset-enabled driver |
| `artifacts/D_I/`, `artifacts/D_N/`, `artifacts/R_S/` | Measured `.bit` images; final routed timing/utilization reports |
| `artifacts/software/` | Measured native libraries/driver; historical host binaries, not portable defaults |
| [inputs/grid.json](inputs/grid.json), [inputs/files.json](inputs/files.json) | Input order, hashes, exact references, real inputs, synthetic recipes |
| `results/benchmarks/` | Original raw CSVs, clocks, warmups, summaries, event tables, figures, environment and command logs |
| `results/parity/`, `results/build/` | Existing board/RTL gates and implementation evidence |
| [replay.py](replay.py), `scripts/`, `checks/` | Minimal preparation, build, admission, collection and analysis path |
| [manifest.json](manifest.json), [provenance.json](provenance.json) | Package checksums; original paths/hashes and adapter provenance |

Original evidence is byte-preserved, including its historical absolute paths. Replay uses package-relative inputs and fresh output directories; those historical paths are not dependencies. Original manifests describe the original attempts, including omitted intermediate/redundant files; `manifest.json` describes this package.

## Existing results

- **D_I board parity:** 520/520 exact checks with the standard driver.
- **R_S board parity:** 260/260; additional persistent benchmark admission 260/260.
- **All three variants:** 12 sizes × (20 warmups + 200 measured) = **2,640 calls each**.
- **Total:** 7,200 measured calls + 720 recorded warmups; smoke/pilot/admission separate.
- Synthetic sizes: **4, 16, 64 MiB, 128 MiB−64 bytes**.
- Eight real sizes: **5,540,996; 12,004,440; 18,876,484; 30,323,588; 34,162,708; 41,278,872; 48,540,364; 55,676,772 bytes**.
- One session/variant; batch 1; HPF; CPU 2 / NUMA 0; PCIe Gen3 ×16; 250 MHz.

Direct variants: calibrated FPGA endpoint. R_S uses a different host-observed endpoint below.

| Synthetic payload | D_I median to FPGA verdict | D_N median to completion |
| --- | ---: | ---: |
| 4 MiB | 0.355210 ms | 0.332693 ms |
| 16 MiB | 1.339785 ms | 1.317789 ms |
| 64 MiB | 5.279096 ms | 5.257416 ms |
| 128 MiB−64 B | 10.531803 ms | 10.510403 ms |

R_S host-observed medians: **1.105847 / 1.344188 / 5.283495 / 10.536761 ms** at the same four synthetic sizes. See [R_S raw trials](results/benchmarks/R_S/full.jsonl) and [summaries](results/benchmarks/R_S/full.summary.csv).

| Routed user wrapper | LUT | FF | BRAM tiles | DSP | URAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| D_I | 67,143 | 86,435 | 354 | 1,328 | 11 |
| D_N | 7,788 | 12,616 | 20 | 0 | 0 |
| R_S | 63,764 | 82,210 | 345 | 1,328 | 11 |

- D_I timing: **WNS +0.044 ns; WHS +0.009 ns**.
- R_S timing: **WNS +0.022 ns; WHS +0.009 ns**; successful route_03 recipe included.
- D_I BRAM **17.56%**, DSP **14.72%**: above the 10% targets.
- D_I−D_N ≈ **21–23 µs** at these sizes; not isolated CNN compute time.
- [Latency figure](results/benchmarks/latency_vs_size.png); [overlap figure](results/benchmarks/overlap_timeline.png).
- GPU lines in the existing figures are PDF references only; no GPU replay is included. [Reference PDF](results/benchmarks/GPU_BASELINE.pdf).

## Measurement contract

**D_I / D_N:**

- Timed start: native host timestamp before per-trial flush/arm/submission.
- Timed end: FPGA verdict/completion, mapped to host time with **32 clock brackets before + 32 after each size**.
- Also retain host-observed DMA completion and verdict readback.
- Exclude file reads, allocation, registration, and input-buffer preparation; upload the full payload each trial.
- Frame: **64-byte length header + payload + 64-byte alignment padding**.
- CSR words: **8/9** first/last payload; **10/11** first/last pixel produced; **12/13** first/last CNN input consumed; **14** score; **15** verdict; **16** DMA acknowledgement.
- FPGA timestamps do not capture first-header arrival. CNN interval includes publication and stalls.
- Preprocessing/CNN intervals overlap; do not sum them. Warmups remain recorded and excluded from primary statistics.
- Preserve ABI v3, source weights, preprocessing, 32-token FIFO and first-pixel launch guard.

**R_S:**

- Production `RawCoyoteOverlay` / `CoyoteInference`; persistent batch-one context.
- Start: Python host timestamp before flush. End: host observes result after blocking `LOCAL_TRANSFER` and result DMA.
- Exact-length input: 64-byte header + payload; four-byte result DMA.
- Host timestamps only; **no internal preprocessing/CNN timestamps**.
- Compare host-observed columns across variants; do not compare R_S host time as if it were a calibrated FPGA verdict timestamp.

## Prerequisites

- **Verify:** Python 3.10+; standard library only.
- **Collect/analyze:** [requirements.txt](requirements.txt); `numactl`, `cmake`, C++17 compiler, Boost headers, pthread, kernel headers.
- **Hardware builds/checks:** licensed Vivado/Vitis HLS **2024.2**, U55C device support, GMP development library, C++ compiler; tools on `PATH`.
- **Board:** U55C, standard Coyote driver, sufficient hugepages for a 128 MiB registered buffer plus runtime overhead; ETH HACC `/opt/hdev/cli/hdev` and authorized programming/module operations.
- Configure hostname, board device/BDF, CPU/NUMA and a shared board lock in a copy of [board.example.json](board.example.json). All board users must honor that lock.
- No training, TensorFlow, model conversion, GPU tools or historical campaign directories required.
- Original runtime binaries target the recorded host/kernel. The `software` command rebuilds for the current host.

## Commands

Run from this package. Place every output directory outside it; use a new directory for each attempt.

```bash
# Read-only verification: hashes, measured identities, trial counts, input recipes.
python3 replay.py verify

# Optional future source builds: NOT executed while making this checkpoint.
# Source the installed 2024.2 tool settings first.
export HLS_INCLUDE=/tools/Xilinx/Vitis/2024.2/include
python3 replay.py build --variant D_I --output /scratch/rebuild_DI --tmux
python3 replay.py build --variant D_N --output /scratch/rebuild_DN --tmux
python3 replay.py build --variant R_S --output /scratch/rebuild_RS --tmux
```

- Each build gets fresh sources/IP/checkpoints; allow concurrent builds only with adequate host RAM.
- Retain the bundled **U55C static platform DCP**: it is a platform input used by the measured builds, not a campaign cache.
- D_I uses the successful `SLICE_X166Y196` boundary-register placement and route directives; target/clocks unchanged.
- D_I mandatory build gates: preprocessing/pristine-CNN parity, control RTL, actual synthesized CNN/preprocessing RTL, **11 consecutive frames**, stalls, **20,000 idle cycles + second reset**.
- R_S build gates: **52 corpus C-simulation calls + 8 boundary references**, eight synthesized-RTL frames, input/output stalls, startup idle + second reset. Original CNN/weights unchanged.
- R_S route recipe: fresh optimized netlist → `Explore` placement → `AlternateReplication` → `MoreGlobalIterations` → `AggressiveExplore`; clocks unchanged.
- Rebuilt images require fresh board admission. No bit-for-bit synthesis, timing closure, or performance equivalence is promised before those runs.

```bash
# Optional future benchmarking; these commands program the board.
# Activate a Python environment with requirements.txt installed.
cp board.example.json /scratch/board.json
# Edit /scratch/board.json for the actual host before running.
python replay.py software --output /scratch/bench_DI
python replay.py benchmark --variant D_I --config /scratch/board.json --output /scratch/bench_DI --tmux

# Start after D_I completes; same board, separate output tree.
python replay.py software --output /scratch/bench_DN
python replay.py benchmark --variant D_N --config /scratch/board.json --output /scratch/bench_DN --tmux

# Optional R_S replay after the other board jobs finish.
python replay.py software --variant R_S --output /scratch/bench_RS
python replay.py benchmark --variant R_S --config /scratch/board.json --output /scratch/bench_RS --tmux
```

- Default images: the packaged measured bitstreams.
- To use a rebuild, add `--build-root /scratch/rebuild_DI` or `/scratch/rebuild_DN`; R_S uses `/scratch/rebuild_RS`.
- `benchmark`: program → admission → smoke → pilot → full sweep → analysis.
- Admission: **520 calls for D_I/D_N; 260 for R_S**.
- D_N admission checks transport/events; it does not perform classification.
- `validate`: same programming/admission path without benchmark trials.
- `--tmux`: tracked job + persistent outcome monitor; ntfy on build/benchmark finish, failure or unexpected termination. No periodic notifications.
- A completed invocation leaves its selected image installed. The last variant run remains installed.
- Failed runs preserve logs and stop; no automatic source edits or unchanged retries.

```bash
# Optional offline preparation or re-analysis; no FPGA access.
python replay.py prepare --output /scratch/checkpoint_inputs
python replay.py analyze --output /scratch/checkpoint_analysis
```

## Checkpoint validation scope

- [x] Existing results/images copied; original campaign retained.
- [x] Checksums, deterministic input recipes, counts, local dependencies and syntax checked.
- [x] Relocated package verification; no executable dependency on dated campaign paths.
- [ ] Packaged commands exercised through fresh synthesis/implementation.
- [ ] Packaged commands exercised through board admission/benchmarking.

The last two items are intentionally pending: **no builds or benchmark replay requested for this checkpoint**.
