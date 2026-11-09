# Report review — 2026-11-08

- Reviewed all 15 rendered pages for layout and clipping; inspected standalone
  latency, topology, timeline and resource figures at full resolution.
- Fixed the latency label/alternate-state marker overlap and added an explicit
  verdict legend to the standalone timing figure.
- Numerical checks: 4,800 primary measured calls, 200 per normal workload/variant;
  3,200 real-input calls. Cutoff, boundary, closing/repeat and profiling evidence
  remains separate. Derived medians/p95 match raw calibrated events.
- All recorded scores have correct FPGA verdict bits; trial IDs/status/event
  validity and host/FPGA clock brackets pass. Both 520-call admissions pass.
- All 13 figures export titled PNG/SVG/PDF files; archive contains 39 files.
  PDF text lies within page bounds. Existing R06 report hashes are unchanged.
- **Unresolved physical cause, explicitly disclosed:** up to 9.825% initial-to-
  closing FPGA latency variation after identical-image reprogramming. Same-image
  repeat variation is at most 0.076%; an old-adapter control agrees. The main
  report exposes all three programmed states. No <5% cross-program-stability
  claim is made. Root cause must not be labeled proven clock/PHY calibration.
- Integrated profiling failure is preserved/excluded. Three independent fused
  compute profiles after validated, drained P2P delivery passed.

Automated checks: `data/review.json`. Review status: complete, with the stated
cross-program repeatability limitation retained in the report.
