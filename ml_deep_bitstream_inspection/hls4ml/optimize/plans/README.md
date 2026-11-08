# Deployment experiment plans

| Work | Plan | Status |
| --- | --- | --- |
| Automated builds, benchmarks and reports | [Orchestration specification](2026-11-07_campaign_orchestration_spec.md) | Design only; dedicated background agents; build host hacc-build-03, benchmark host hacc-gpu-u55c-01 |
| Option 1: input already in HBM | [HBM-resident inspection](2026-11-07_hbm_resident_inspection.md) | Assigned to the build-host agent; consult its live campaign for launch status |
| Option 2: receive over RoCE and inspect while streaming | **[Build-agent handoff](2026-11-07_option2_build_handoff.md)** | Concrete plan; diagnostic receiver first; no launches from this investigation |
| Option 2 initial proposal | [Network MVP outline](2026-11-07_network_streaming_mvp.md) | Retained for context; implementation details superseded by the handoff |

Option 2 discovery was performed on hacc-gpu-u55c-01 on 2026-11-07. Its source
and hardware findings are also indexed at the beginning of project MEMORY.md.

[Additional host validation and source probes](../runs/option2_host_validation_20261107/README.md):
NIC loopback, GPU readiness/parity, existing polling RTL and design-model checks.
