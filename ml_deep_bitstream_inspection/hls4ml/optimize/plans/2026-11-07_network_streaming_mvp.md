# Network streaming inspection MVP

Date: 2026-11-07. Status: queued proposal; no builds launched.
Implementation details now live in the [concrete build-agent handoff](2026-11-07_option2_build_handoff.md).
Option 2 follows the HBM-resident plan in `2026-11-07_hbm_resident_inspection.md`.

## Goal and minimum scope

Receive a raw bitstream through the FPGA's RoCEv2 port, retain it in HBM for PR,
and inspect it while reception progresses. Compare FPGA_HLS4ML and GPU_P2P using
the same model/runtime selections and input files as Option 1. One sender, one
queue pair and one bitstream in flight; batch size one. Host software performs
connection setup and emulates embedded-CPU control. No soft CPU, actual PR,
multi-tenant service or general-purpose network deployment stack in this MVP.

## Required work

### Host-specific preflight findings — 2026-11-07

Preferred arrangement is entirely on `hacc-gpu-u55c-01`: local ConnectX-5 sender
through the external Ethernet fabric to U55C device2, plus one local MI210.
This replaces the assumption that an additional server must be reserved.

| Role | Confirmed inventory / proposed selection |
| --- | --- |
| Sender | ConnectX-5 Ex `61:00.0`, data1 / mlx5_0 port1, 10.253.74.110; live 100GbE, Ethernet MTU9000, RDMA MTU4096, RoCEv2 IPv4 GID3, NUMA0 |
| Receiver | U55C device2, 81:00.0, XFL13BA4HVZYA, NUMA1; site-assigned QSFP addresses 10.253.74.114/.115 |
| GPU | MI210 at 03:00.0 or 25:00.0, both NUMA0 Gen4×16; retain the selected R06 GPU consistently |
| Alternative sender | Second U55C device1, a1:00.0, assigned .112/.113; requires its own network image and working QSFP link |

Both U55Cs currently run the XRT base shell, not Coyote. The NIC link is confirmed;
the receiver QSFP link, cabling and switch/VLAN connectivity are not. The route to
.114 uses data1, but routing and site-assigned addresses alone are not proof of
reachability. data2 is down/no cable. Global NIC pause is enabled; PFC and switch
configuration are unverified. Do not change NIC settings or the management path
as part of discovery. No live transport tests or reprogramming have occurred.

Use NUMA0 sender buffers and separate CPU cores for sender and GPU runtime.
Receiver control can retain NUMA1 affinity. This avoids imposing an unnecessary
NUMA crossing on the sender; FPGA→GPU remains cross-NUMA. Record host contention
and sender pacing because the sender and GPU share the machine.

First implementation milestone: deploy a compatible Coyote RDMA diagnostic image,
check CMAC link and ARP, establish one QP, verify exact bytes and measure paced
transport. The installed site Coyote image is hello-world; no ready example09
image was found there. Reuse a compatible diagnostic image if located, otherwise
budget an initial small receiver build before the full two application builds.

Implement a small standard libibverbs sender for the ConnectX-5. Coyote's example
client uses cThread and cannot directly drive this NIC. Adapt the out-of-band
setup for QPN/PSN, IPv4 GID, rkey, destination and MTU; setup may use localhost
TCP while payload travels through the physical NIC/FPGA ports. Installed
ib_write_bw is a diagnostic tool, not a drop-in replacement for this handshake.

### Implementation sequence

1. Verify a sender (another Coyote FPGA or compatible RDMA NIC), QSFP connection,
   routing/switch settings, IP/ARP/QP setup and access to the receiver GPU host.
   Demonstrate correct RoCE transfers before assuming 100GbE payload throughput.
   Existing PCIe/P2P validation does not establish network connectivity.
2. Reuse `../examples/09_perf_rdma`: inbound RDMA WRITE payload is exposed on
   `axis_rrsp_recv[0]`; the example routes it to `axis_host_send[1]` and uses
   `STRM_HOST`. Add an application adapter for HBM writes and the inspection tap.
   Reuse Option 1 card-memory mapping and completion accounting. Enable RDMA,
   card memory and required PCIe streams in new builds.
3. Exchange trial ID, total raw length and destination before payload transmission.
   Use ordered chunks on one QP, with explicit offsets and byte counts. Preserve
   valid-byte masks and distinguish chunk boundaries from the whole bitstream.
   Generate the existing preprocessor header locally; do not store it as raw data.
4. FPGA path: fork accepted payload to HBM and the streaming preprocessor/CNN.
   Use a sequential-stream form of the optimized small-input sample selector:
   cache words, emit all required samples, and drain every network byte. Do not
   replace this with a whole-frame HBM gather after reception.
5. GPU path: fork payload to HBM and GPU PCIe writes as chunks arrive. Retain
   R06 and autonomous verdict polling; enforce GPU visibility before inference.
   Generate the GPU buffer header separately. Do not wait for the full bitstream
   in HBM before forwarding.
6. Use elastic buffers with correct independent branch handshakes; no dropped or
   duplicated beats. Bound in-flight sender chunks using application credits and
   start with controlled pacing. Return credits only after reserved buffering or
   downstream consumption makes further data safe. Validate limits in simulation
   and transport probes before increasing the window/rate. AXI backpressure alone
   is not an unlimited network buffer. Record pacing and occupancy in results.

Proposed separate images: `OPT_12_NET_STREAMING` and `OPT_13_NET_GPU_P2P_R06`.
Include receive/store-only and forwarding diagnostics in these same images.
The stock RoCE engine handles protocol processing; the new application manages
storage, stream branching, framing and completion. The packet sniffer is not the
inspection input: it observes packets rather than the intended application bytes.

## Metrics and report

- Primary common boundary: first accepted RDMA application-payload beat → verdict
  accepted at FPGA. Record receiver arm separately; distinguish this boundary
  from Option 1's local start. Include receiver backpressure in elapsed timing.
- Record first/last received byte, complete valid transfer, HBM write completion,
  preprocessing pixels, CNN/result, GPU P2P and visibility, R06 fused work,
  verdict publication/polling, drain and errors.
- Report both verdict availability and **ready for PR**: accepted verdict plus
  successful complete transfer and HBM storage. A positive classifier output
  alone must not authorize a truncated or failed deployment.
- Optional sender-invocation-to-notification uses one sender clock; do not subtract
  independent server clocks to claim one-way network latency.
- Reuse real-input latency bars, speedup bars and overlap timelines. Add network
  receive/P2P/HBM rates, sender pacing and branch stalls. Show Option 1 versus
  Option 2 with their different starting states and timing origins explicit.
- Separate measured end-to-end GPU latency from speculative 8.5/15.75 GB/s curves.
  At measured ~4.1 GB/s P2P, GPU forwarding can limit network ingress in this MVP.
  Decoupling full-rate ingress through an HBM chunk queue is a later extension.

## Validation and sequence

- Preflight and transport smoke test; resolve missing sender/network access first.
- Simulate chunk framing, partial final beats, pauses, independent branch stalls,
  reset, missing/incorrect-length input, timeout and stale/delayed GPU verdicts.
- Check HBM bytes against sent raw bytes, every sampled pixel against the reference,
  FPGA exact parity and existing GPU tolerance/verdict gates.
- Reject incomplete/errored frames; clear per-trial state before reuse. Test
  consecutive changing frames and supported RoCE recovery behavior explicitly.
- Build the two images concurrently after adapter validation; monitor ntfy topic
  `coyote-build-sdeheredia`. Benchmark sequentially under the device lease.
- Reuse Option 1 admission and 20-warmup/200-measured methodology for the same
  eight real and four synthetic inputs; include short-input boundary diagnostics.
- Capture resources, timing closure, transport-only controls and closing drift.

Estimate after Option 1 components are working and network access is available:
roughly 4–7 additional working days for a validated two-variant MVP and results.
Budget 8–20 hours per RDMA/HBM build attempt; shell timing closure or unavailable
network infrastructure can extend this. FPGA-only smoke results should precede
the full comparison. This is a planning estimate, not a running-job ETA.

## Evidence

- Local Coyote example: `../examples/09_perf_rdma/hw/src/vfpga_top.svh`.
- Card-memory integration reference: `../examples/11_packet_sniffer/` (reuse its
  memory interfaces, not its raw sniffer receive path).
- [Coyote RoCEv2 documentation](https://fpgasystems.github.io/Coyote/system/dynamic.html):
  512-bit streams, out-of-band QP setup and compatibility with commodity NICs.
- Current measured P2P rates and topology limitations: project `MEMORY.md`.
