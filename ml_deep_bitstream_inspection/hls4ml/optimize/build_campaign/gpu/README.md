# FP32 GPU transport builds

Campaign: `hls4ml/optimize/runs/gpu_fp32_20261018`.

- OPT_7_GPU_HOST: independent host→GPU and host→FPGA input; host relays FP32 logit to FPGA. Early result is retained until raw input completes.
- OPT_8_GPU_P2P: FPGA forwards raw input into a fine-grained GPU DMA-BUF; FPGA autonomously polls a separate ready cacheline, then reads the immutable result cacheline.
- Original Keras FP32 model, ordinary TensorFlow operations. Native HIP code only allocates/maps memory, transfers data, shares DLPack tensors and publishes a scalar result.
- Existing quantized FPGA iterations and ABI v3 sources remain untouched. New images use ABI v4 variants 10 and 11.

## State and notifications

Each job has `status.json`, stage logs, `rtl_validation/`, `monitor_status.json` and eventually `artifact_manifest.json` and `notification.json`.
Two build sessions and two independent monitor sessions use tmux names `gpu_fp32_{host,p2p}_{build,monitor}`.
Monitors notify `https://ntfy.sh/coyote-build-sdeheredia` on pass, failure or unexpected supervisor exit. Failed delivery retries; a notification is recorded only after HTTP success.
Controllers and hardware sources are snapshotted per campaign/job. Both implementations run concurrently, four threads each.
No board programming or benchmark starts automatically when a build finishes.

## Hardware ABI

All CSR indices are 64-bit words. Registers 0..29 retain their direct ABI v3 meanings; signature register 4 reports version 4 and variant 10/11. The default clock is 250 MHz; check the final timing report.

| CSR | Meaning |
| --- | --- |
| 32, 33 | GPU ready / payload virtual addresses, 64-byte aligned and distinct |
| 34 | Coyote context ID (6 bits) |
| 35 | Gap cycles after an unsuccessful poll response, default 250 |
| 36 | Whole-trial timeout ticks, default 7,500,000,000 (30 seconds) |
| 37 | Poll engine active/draining: must be zero before unmap/rearm |
| 38..41 | First request, last not-ready response, ready observed, payload received ticks |
| 42..44 | Read request count, requested bytes, request-queue stall cycles |
| 45, 46 | Poll error code, engine state |

Mailbox occupies two separate 64-byte records. Ready record words: 32-bit generation, its complement. Generation equals trial ID low32 and must be nonzero. Payload: FP32 logit bits, magic `0x43565234`, full 64-bit trial ID, zero/reserved bytes. Publish immutable payload before ready; reinitialize only after the old transaction drains.

One read is outstanding. Completion requires both stream data and matching CQ. Empty/old generations retry; malformed current payload fails. Timeout stops issuing reads but retains the receive path to drain an accepted read. Reset while DMA is active requires hardware recovery, not ordinary rearm.

Raw transport preserves the existing 64-byte length header, whole-beat padding and 128 MiB maximum transport size (raw maximum 134217664 bytes). The CNN sees only raw bytes, without transport padding/header. Preprocessing pads raw short inputs before inversion.

## Verified preflight versus remaining admission

- Existing D_G image: 21 exact P2P round trips from 64 B through 128 MiB transport.
- Fine-grained DMA-BUF input/publication: 100 board trials using the existing bridge.
- TensorFlow ROCm 2.18.1 on MI210 GPU0: eight boundary cases and 520 software admission calls, including DLPack and the publication helper, compared with FP32 CPU results.
- Both new wrappers: actual Coyote interfaces, startup idle/second reset, consecutive frames, byte/sideband forwarding, stalls, early host verdict, stale polls, CQ/data ordering, invalid trial rejection and timeout/drain simulations. Repeated against each build's generated package before synthesis.
- Autonomous FPGA polling and complete GPU ABI v4 transport still require board admission with the newly built image. Historical D_G verification is not evidence of new-image admission.

## Runtime handoff

Runtime source snapshots, original model configuration and hash-pinned shared weights reference are in each job's `runtime/`; `runtime_manifest.json` seals them independently of hardware sources. Build the adapter using the campaign Python environment and each job's `coyote/sw`:

```bash
cmake -S JOB/runtime -B JOB/runtime_build \
  -DCOYOTE_SW=JOB/coyote/sw -DCMAKE_CXX_COMPILER=/opt/rocm/bin/hipcc \
  -DCMAKE_HIP_COMPILER=/opt/rocm/llvm/bin/clang++ -DCMAKE_HIP_ARCHITECTURES=gfx90a \
  -Dpybind11_DIR=CAMPAIGN/venv/lib/python3.10/site-packages/pybind11/share/cmake/pybind11 \
  -DPYTHON_EXECUTABLE=CAMPAIGN/venv/bin/python
cmake --build JOB/runtime_build -j8
```

After verifying the sealed image, programming it, recording its hash and loading the standard kernel-matched driver, use `runtime/benchmark.py --help`. Set `PYTHONPATH=JOB/runtime_build`, `LD_LIBRARY_PATH=/opt/rocm/lib`, `HIP_VISIBLE_DEVICES=0`; use the same board lock for programming and all runners. Select `--variant host` or `--variant p2p`.

Run `--admission --cases CAMPAIGN/admission.tsv` first: 26 cases × 20 calls. Measured runs require its `result.json`, the same bitstream hash and the 15-case `CAMPAIGN/cases.tsv` manifest. Resident/file scopes are separate; defaults 20 warmups and 200 measured trials. `--profile` is a separate 20-trial diagnostic recording.

Host end-to-end timings and CSR timestamps are collected on every trial. HIP events cover host-to-GPU copy or publication. TensorFlow profiling supplies device preprocessing/inference events; Python enqueue durations are not GPU execution timings. DLPack export may wait for inference; that host wait is included in e2e. Poll-window duration overlaps inference and is not additive overhead. Do not subtract unrelated GPU/FPGA clock values; use correlation and its uncertainty.

The runner validates supplied image hashes syntactically and ties admission evidence to them; the board controller/operator must establish actual programmed-image identity from the sealed programming record. Clock brackets and profiler traces are retained for later analysis.

## GPU_HOST recovery, October 19

The first GPU_HOST implementation failed setup timing by 0.285 ns at the shell/static stream boundary. The P2P image passed. `recover.py JOB PLACEMENT_EVIDENCE.json` reruns placement/routing from GPU_HOST's own optimized checkpoint, using the verified boundary register location from P2P as physical guidance only. Original sources, 250 MHz clocks and failed outputs are preserved. One further physical-optimization/routing pass is allowed if the completed first retry still misses timing; other errors fail immediately.

The current recovery runs on hacc-build-02 in `gpu_host_repair_build`, with `gpu_host_repair_monitor` sending terminal status to ntfy. Its status remains at the usual `jobs/OPT_7_GPU_HOST/status.json`; recovered bitstreams and reports are written under `recovery/host_20261019_101910/`. Evidence and snapshotted controller are retained in the campaign. Timing closure and board validation must still be checked when they finish.
