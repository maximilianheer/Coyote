# Review — 2026-11-09

- **Numerical/evidence review: passed.** See `data/review.json`.
- Reconciled 33,600 measured calls, including 19,200 primary calls; 20 warmups and 200 measured calls per session/cell; equal session weighting; score/verdict references; finite timings; input, weight and archived-source hashes.
- Verified recorded thread affinity, NUMA2 placement, zero-copy input aliasing, GPU exclusion, cache-probe separation and isolated hardware cache-miss evidence.
- Reconciled every statistics-based plotted value and speedup direction where applicable; retained p95 and independent A/B medians. No latency-based selective reruns.
- Inspected all ten rendered PDF pages and all eight standalone figures for clipping, legend placement, axes, titles and scope. Shortened overlong diagnostic axis labels; moved bar legends clear of data. Exports include embedded titles in PNG, SVG and PDF.
- Preserved all failed/rejected preliminary attempts. Native INT8 conversion passed verdict-only admission but failed score-fidelity review; explicitly excluded from primary performance claims.
- Report states the up-to-14.1% session median variation, warmed model/code, non-reserved SMT sibling, and different-host historical accelerator context. No physical explanation for the session shifts is claimed as proven.
- Preprocessing-only and inference-only timings are explicitly independent diagnostics; they are not an additive decomposition of fused total latency.
- No FPGA/GPU was used, no FPGA build was launched, and no networking supervisor was changed for this CPU campaign.

Result: accepted for the stated original-FP32 and frozen-QKeras CPU timing scopes. Native INT8 CPU performance remains unestablished.
