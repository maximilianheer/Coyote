# Option 2 network streaming build handoff

Created 2026-11-07 on hacc-gpu-u55c-01. Status: implementation plan; no images
programmed, builds launched or RDMA payload tests run during this investigation.
This is the authoritative implementation handoff for Option 2. The earlier
`2026-11-07_network_streaming_mvp.md` remains the initial proposal.

Host validation completed after this handoff: [results, commands and reusable
probes](../runs/option2_host_validation_20261107/README.md). 108 NIC loopback
transfers, 45 R06 calls, existing GPU RTL and abstract sampling/credit checks
passed. No live FPGA network test or production NIC→Coyote adapter is implied.

## 1. Objective and fixed choices

Receive a bitstream over physical 100GbE/RoCEv2, store the exact raw bytes in HBM
for later PR, and inspect the bytes while reception is in progress. Compare:

| Image | Function |
| --- | --- |
| `NET_DIAG_HBM` | Small receiver with host-sink and HBM-store diagnostic modes; no CNN/GPU dependency |
| `OPT_12_NET_STREAMING` | Network → HBM plus optimized streaming preprocessing → unchanged OPT_6 CNN |
| `OPT_13_NET_GPU_P2P_R06` | Network → HBM plus immediate PCIe forwarding → R06 GPU inference → autonomous FPGA polling |

One sender, one RC QP, one frame in flight; CPU emulates embedded-core control.
No actual PR, soft-core integration, TCP payload path, raw-packet sniffer input,
multi-client scheduling, hls4ml modifications or repeat FIFO profiling.
The direct GPU branch forwards chunks before the complete frame reaches HBM.
Do not silently substitute full-frame store-then-forward.

## 2. Hardware selection and current readiness

| Role | Selection |
| --- | --- |
| Host | hacc-gpu-u55c-01.inf.ethz.ch |
| Sender | ConnectX-5 Ex, 0000:61:00.0, data1, mlx5_0 port 1, 10.253.74.110 |
| Receiver | hdev device2, U55C, 0000:81:00.0, serial XFL13BA4HVZYA |
| Receiver port | QSFP0; assigned 10.253.74.114, MAC 00:0A:35:0F:52:18 |
| GPU | MI210 GPU0, 0000:03:00.0, matching the accepted R06 comparison |
| CPU placement | Sender thread CPU2 and NUMA0 source allocation; GPU/receiver control CPU64 as in accepted board runs |

Verified: NIC Ethernet link 100Gb/s, MTU9000; RDMA ACTIVE with MTU4096 and IPv4
RoCEv2 GID index3. Resolve the GID by IP/type at runtime and reject a mismatch,
rather than blindly relying on index3. NIC and both MI210s are NUMA0 Gen4×16;
receiver U55C is NUMA1 Gen3×16. libibverbs, ib_write_bw, Vivado2024.2 and ROCm
tools exist. Both U55Cs currently have the XRT base shell and xocl/xclmgmt, not
Coyote. GPU utilization was 0% at inspection; this is not a reservation.

Proposed payload path: NUMA0 RAM → local NIC → external Ethernet fabric →
receiver QSFP0 → HBM and inspection branch. Same-host control/setup does not
make this a software/network loopback: verify NIC and FPGA packet counters.
The route to .114 uses data1; physical FPGA carrier, cabling, VLAN reachability
and actual RoCE interoperability remain unverified. NIC data2 is down/no cable.
NIC global pause is enabled, FEC off; do not infer switch PFC from these facts.
Do not change fabric, NIC settings or eno1 management networking automatically.

Fallback: if QSFP0 is not connected, obtain the site cable/port mapping before
selecting QSFP1 (.115, MAC ...52:1C) and rebuilding for that port. If the local
NIC path cannot be enabled, use a booked remote ConnectX-5 sender. Using the
second local U55C as sender is a later fallback requiring its own network image.
Do not port this MVP to the VCK5000s: this Coyote revision rejects Versal networking.

## 3. Build inputs and dependencies

Source inspected: parent Coyote HEAD `502a94af61107e7b9a54d5b669ca60d2dbc47753`.
Pinned network gitlink: `37b59d3828b003d2d6f7dd9748824a0e39d99167`.
`../hw/services/network` is empty here. Restore that exact submodule revision in
the isolated build checkout; never follow its moving branch. Record full source
hashes and any local changes. If Option 1 uses a different sealed Coyote revision,
reconcile the ABI/configuration explicitly before sharing its components.

Use Vivado/Vitis2024.2 and the established U55C build infrastructure. For all
three images, use the same shell settings:

```
EN_RDMA=1  EN_TCP=0  EN_SNIFFER=0
EN_MEM=1   EN_STRM=1
N_REGIONS=1  N_CARD_AXI=1  N_STRM_AXI=2  N_RDMA_AXI=1
EN_NET_0=1  EN_NET_1=0
PMTU_BYTES=4096  N_OUTSTANDING=32  N_TLB_ACTV=64
HBM_SPLIT=0  BUILD_OPT=1
application clock=250 MHz
```

Verify values in generated package/IP, not just command-line cache entries.
The local CMake derives three memory AXI clients for this configuration (user,
offload and network). RDMA itself uses card memory: preserve generated address
partitioning and verify user allocations cannot overlap network buffers. Report
network HBM contention instead of assuming Option 1's memory throughput transfers.

Option 1 provides: HBM allocation/offload and readback, improved preprocessing
semantics, completion/timestamp helpers, GPU DMA visibility and polling code.
Do not wait for Option 1 benchmarks to implement NET_DIAG_HBM or the NIC sender.
Do not modify another agent's active checkout, generated firmware or sealed runs.
Final iterations must have independent manifests/source snapshots; they may reuse
verified artifacts by hash but must not require a previous iteration directory.

## 4. NIC interoperability adapter

Use libibverbs RC RDMA WRITE, not WRITE_WITH_IMM and not raw Ethernet. Implement
transport in a small readable C++ library alongside the existing GPU transport;
leave inference in the accepted R06 TensorFlow/XLA runtime. A standalone runner
uses the same library for NET_DIAG_HBM and FPGA-only trials.

On this same-host MVP, one controller owns the Coyote context and NIC QP. Exchange
endpoint metadata in memory and serialize it into the run manifest. This avoids
requiring rdma_cm or Coyote's raw-struct TCP handshake. A dedicated NIC worker
posts writes and polls its CQ. Use public getQpair(), writeQpContext() and
doArpLookup() APIs; no network-stack algorithm changes are planned.

Interoperability requirements confirmed from source:

- **UDP destination 4791:** call writeQpContext(4791). Coyote's initRDMA() passes
  its TCP control port (default18488) to this function; do not use that path
  unchanged for a standard NIC. The pinned stack listens on RDMA_DEFAULT_PORT
  0x12B7 and transmits to the configured remote_udp_port.
- **Different address encodings:** the NIC AH uses IPv4-mapped destination GID
  `::ffff:10.253.74.114`. Coyote's internal IPv4 conversion extracts bits127:96;
  use its existing repeated-IPv4 encoding for remote .110, not a verbatim copy
  of the NIC GID. Assert generated register words and packet IPs in diagnostics.
- Use the actual Coyote QPN derived from vfid/ctid. Avoid reserved QPN0/1 by
  keeping placeholder contexts alive if necessary until the real context is >=2.
  Do not assume hdev device2 means Coyote driver device index2: resolve by BDF.
- Configure standard RC RESET→INIT→RTR→RTS with exchanged QPNs and PSNs,
  path MTU4096, port1, IPv4 RoCEv2 SGID, and correctly ordered IPv4 bytes.
  Use finite retries (retry_cnt=3, rnr_retry=3), timeout20 and a 30s trial watchdog.
  Record full WC status/vendor errors. Never mask a failed CQ completion.
- Allocate/register source RAM before timing. Discover Coyote local rkey/address;
  current source initializes its local rkey to zero. Preserve that contract and
  validate the receiver address window independently in the application.
- Program receiver network identity using the matching driver configuration:
  IP hex `0AFD4A72`, MAC hex `000A350F5218`; verify hardware readback and ARP.
- At arm, reset the GPU mailbox and transfer state; grant payload credits only
  after receiver buffers/mappings are ready. No sender writes while unarmed.

ib_write_bw is useful for independent NIC diagnostics, but its setup protocol is
not compatible with Coyote's example. Do not report NIC-loopback results as FPGA
network performance. Wire capture, if needed for diagnosis, is outside timed runs.

## 5. Framing, buffering and credits

Use 64KiB ordered RDMA-write chunks, final chunk shortened to the exact raw byte
count. Transfer raw bytes only; no model header on the wire or in HBM. At arm,
provide trial ID, raw length, HBM base, and GPU base/mailbox addresses as applicable.
Maximum raw length remains 128MiB−64B for compatibility with existing workloads.

Allocate a 256KiB ingress ring with four 64KiB banks. Each posted chunk reserves
one whole bank; initial admission uses one outstanding chunk, then at most four.
Bank allocation is at chunk start, with downstream streaming allowed as beats
arrive; do not wait for a complete frame. Track partial words with tkeep and
validate request address/length against expected ordered offsets. Reconstruct
whole-frame termination from byte counts, not packet/chunk tlast alone.

Each bank has independent HBM and inspection read positions. A slow branch must
not make the other branch consume a beat twice. Free a bank only after both
branches consumed the chunk. Expose cumulative freed chunks to the host; sender
credits are based on that counter, **not NIC RDMA ACK/CQ completion**. The latter
does not prove HBM commit or application consumption. Sender pacing and credit
gaps remain inside measured network-to-verdict timing.

Store-first credit reservation bounds all outstanding application payload even
when GPU/CNN stops. Finite internal queue exhaustion must propagate backpressure;
test burst absorption and downstream stalls explicitly. Use the same credit
window for both main variants. Publish separate one-credit diagnostic results.
Do not presume a hardware rate_limit capability for RC QPs from RAW_PACKET caps.

Zero-length input is a separate control diagnostic: generate padded pixels,
record no network-first timestamp and exclude it from network-latency plots.
For invalid metadata, excess/missing data or timeout: mark the trial invalid,
stop granting credits and quiesce/reset the QP and pipeline before reuse. Do not
grant PR readiness on classifier output alone.

## 6. Receiver RTL and completion routing

Use Coyote example09's incoming WRITE path, `axis_rrsp_recv[0]` with `rq_wr`.
Validate and queue incoming requests. For the HBM branch preserve appropriate
RDMA request fields, change the memory target to STRM_CARD/dest0, and deliver
the matching payload on axis_card_send[0]. Retain the framework's completion
semantics; verify request last flags and actual CQ event granularity in simulation.
Do not interpret each network packet's tlast as the end of an entire transfer.

Provide a real arbiter for sq_wr: HBM-store requests and generated GPU writes.
Demultiplex cq_wr by strm, destination, pid and request origin; count all expected
completions rather than accepting the first acknowledgement as full completion.
HBM-store completion, GPU DMA completion and NIC acknowledgement are distinct.
Only return HBM storage-complete after all corresponding memory transactions.
Discard unsupported remote READs as explicit protocol errors, not phantom GPU
mailbox responses. Keep unused streams safely terminated and count unexpected use.

GPU requests use LOCAL_WRITE/STRM_HOST/dest0, target GPU_raw+64+chunk_offset;
payload uses axis_host_send[0]. The GPU 64B header is initialized before timing,
with raw length matching the armed frame. Preserve exact raw lengths/tkeep at
the tail; final padding in the GPU allocation is initialized outside timing.
Use the existing autonomous LOCAL_READ poller on host stream1, with its own
completion demultiplexing and validated current-trial ready/payload records.

FPGA path synthesizes the preprocessor's existing 64B length header locally,
then emits raw payload beats, zero-filling unused tail lanes as needed by HLS.
Keep raw valid-byte counting separate from padded HLS framing. Preserve the
small-input sample-driven fix, exact 65,536 pixels, fixed-point conversion,
first-pixel launch guard and 32-entry CNN-facing FIFO. Reuse OPT_6's CNN RFs,
FIFO depth map, weights and standard hls4ml firmware; no conv0 specialization.

GPU controller starts inference only after all generated PCIe writes complete
and the established external-DMA visibility protocol succeeds. Reuse R06 cached
ConcreteFunctions for each length; warm/compile before measurement. The poller
can begin after forwarding completes, but cannot publish a valid verdict from
an earlier trial. Keep buffers alive until polling and all DMA drains terminate.

## 7. ABI and measurements

Add a dedicated versioned network ABI, identified by its own signature and schema;
do not masquerade as current GPU ABI4. Provide a shared generated register map for
RTL/C++/Python, event-valid bits, source/schema hashes and rejection of unknown ABI.
Retain names of familiar measurements, but define new semantics explicitly:

| Fields | Required meaning |
| --- | --- |
| Inputs | mode, trial, raw length, HBM base, GPU raw base, mailbox addresses, context, timeout |
| Status | armed, busy, error/code, receive complete, HBM complete, GPU complete, result valid, quiescent |
| Network | first/last accepted application-payload tick; exact bytes, chunks, request counts |
| HBM | first write-data tick, last write-data tick, all-writes-complete tick; bytes and completions |
| FPGA | first/last pixel and CNN input; result-available tick; exact pixel counts |
| GPU | first/last forwarded beat, all-writes-complete; polling start/ready/payload/verdict ticks |
| Backpressure | ingress occupancy peak, branch stalls, no-input cycles, freed-chunk counter |
| Errors | wrong length/address/context, unsolicited input, protocol/CQ failure, timeout, bad mailbox |

Main metric: first accepted RDMA application byte → FPGA verdict acceptance,
all on the same 250MHz receiver clock. Also retain arm time and first-presented
payload time to expose stalls before the first accepted beat. Do not label this
sender-to-verdict or subtract unsynchronized clocks. Capture optional sender-post
to-observed-result with the sender's clock, including polling overhead explicitly.

Report verdict-available and storage-complete independently. Define all-checks-
complete as max(valid verdict, successful complete transfer, HBM completion).
PR-eligible additionally requires the **benign** decision (dataset class0), not
just a valid score. No PR controller is implemented in this experiment.

GPU device spans/kernel sums and host-synchronized fused preprocessing/inference
remain separate diagnostics. Profile outside the latency trial set. Report
observed payload GB/s (100Gb/s is a line rate), NIC/FPGA error counters, pacing,
and resource counts plus device utilization. Existing 4.1/8.5/15.75 GB/s P2P
curves remain predictions until separately measured on this path.

## 8. Gates, ownership and execution order

| Gate | Build agent | Host agent | Pass condition |
| --- | --- | --- | --- |
| G0 | Restore pinned network source; generate consistent config | Confirm board lease, identities and source-buffer allocation | Recorded hashes/config; no assumed Coyote device index |
| G1 | Build NET_DIAG_HBM with native example host sink + HBM store modes | Install matching driver/image; link/ARP/QP and byte tests | Exact received bytes and HBM readback; no unexplained errors |
| G2 | RTL/HLS tests for ring, branches, completions and preprocessing | Develop NIC sender and GPU integration | Boundary/stall/reset tests pass; invalid trials fail closed |
| G3 | Build OPT_12 and OPT_13 concurrently after G1/G2; preserve Option 1 jobs | Prepare workloads, model/runtime hashes and manifests | Timing closure, immutable artifacts and ntfy completion |
| G4 | Deliver artifacts and resource reports | Admission, full sweep and closing controls | Parity/timing/throughput gates and complete evidence |

G1 tests: 64B, 4096B, 4097B, 64KiB, 64KiB+1 and 1MiB; deterministic changing
patterns, repeated transfers and variable receiver stalls. Then 4/16/64MiB and
128MiB−64B transport probes. Confirm the Ethernet path using both NIC and FPGA
counters. RX carrier without bytes is not G1 success. If there is no carrier,
resolve cabling/FEC with site information before attempting CNN builds.

G2 cases: raw sizes 0/1/63/64/65, 65535/65536/65537, 1/2MiB, and
4194240/4194241/4194242; chunk/page boundaries; full ring; independently stalled
branches; completion reordering between destinations; truncated/extra data;
delayed/stale mailbox; reset during activity; idle then reset then consecutive
frames. Require exact pixel and FPGA-logit parity. Ring high-water <= allocated
capacity, no lost/duplicated bytes and no unreleased requests after quiescence.

G4: 520-call admission per final image; 20 warmups + 200 measured calls for each
of the same eight real and four synthetic inputs. GPU numerical tolerances and
verdict checks remain those of accepted R06 (1e-4 tolerances, finite results).
Compare HBM raw bytes outside timed intervals. Opening/closing FPGA controls;
investigate >5% drift. Reuse one credit-window setting across main comparisons.

Build concurrency: NET_DIAG_HBM may use a spare slot while Option 1 builds run;
do not stop/reconfigure Option 1. Respect the established total four-build limit.
Once gated, final two network builds can run concurrently as slots become free.
Board programming/benchmarks serialize under the existing device2 lease.
Attach ntfy monitors on topic coyote-build-sdeheredia to every background build
and final benchmark campaign; distinguish routed success from admission success.

Expected duration after implementation starts: diagnostic software/integration
roughly 1–2 working days plus its 8–20h build attempt; complete two-variant MVP
and results approximately 4–7 working days once shared Option 1 components and
network access are available. Timing recovery/cabling can extend this; these are
estimates, not current ETAs. Performance gains are measured outcomes, not gates.

## 9. Deliverables and entrypoints

- Independent iteration manifests and source/artifact hashes under existing
  `hls4ml/optimize/iterations/` and separate dated `runs/` roots.
- Maintained new network adapter/runner beside `build_campaign/hardware/` and
  `build_campaign/gpu/`; no modifications to archived measured sources.
- Run manifest with pinned network source, device/IP/MAC/QP/MTU settings, model
  identity, CPU/NUMA placement, credit policy, image and driver hashes.
- Raw per-trial events, parity records, diagnostic counters and final status.
- Later report in `reports/optimizations/YYYY-MM-DD_network_streaming_verdict/`:
  real latency/speedup bars; receiver timing lanes; transport/backpressure and
  HBM-ready timing; resources; synthetic and small-input diagnostics appendix.
  Explicitly distinguish first-network-byte timing from Option 1's local start.

Local source references (relative to project root unless ../ prefix):

- `../examples/09_perf_rdma/`: network requests and payload routing.
- `../examples/11_packet_sniffer/`: card-memory allocation and write interfaces;
  its packet capture is not the application's receive source.
- `../sw/src/cThread.cpp`: QP initialization and programming.
- `../sw/include/coyote/cDefs.hpp`: repeated-IPv4 encoding and default control port.
- `../cmake/FindCoyoteHW.cmake`: one-QSFP restriction and generated memory clients.
- `hls4ml/optimize/build_campaign/hardware/gpu/`: existing forwarding/polling ABI.
- `hls4ml/optimize/build_campaign/hardware/common/direct_preprocess.hpp`: optimized
  small-input reference; rewrite maintained additions with readable formatting.

Pinned upstream evidence:

- [Coyote networking documentation](https://fpgasystems.github.io/Coyote/system/dynamic.html).
- [Pinned UDP destination construction](https://github.com/fpgasystems/fpga-network-stack/blob/37b59d3828b003d2d6f7dd9748824a0e39d99167/hls/ib_transport_protocol/ib_transport_protocol.cpp#L2077).
- [Pinned default port](https://github.com/fpgasystems/fpga-network-stack/blob/37b59d3828b003d2d6f7dd9748824a0e39d99167/hls/ib_transport_protocol/ib_transport_protocol.hpp#L52).
- [Pinned IPv4 extraction](https://github.com/fpgasystems/fpga-network-stack/blob/37b59d3828b003d2d6f7dd9748824a0e39d99167/hls/ipv4/ipv4.hpp#L44).
