# Report index

Report folders use `YYYY-MM-DD_description`, with the report date first.
PDF creation dates determine the prefix where available; the HTML U55C report
and FIFO evidence retain their original campaign dates. Measurement dates can
differ from report dates and remain documented inside each report.

| Date | Report | Scope |
| --- | --- | --- |
| 2026-10-22 | [GPU XLA + ConcreteFunction](optimizations/2026-10-22_gpu_opt_xla_concretefunction/gpu_opt_xla_concretefunction_report.pdf) | Current R06 GPU comparison; FPGA verdict availability |
| 2026-10-21 | [Verdict availability, preprocessing-v2](optimizations/2026-10-21_focused_verdict_availability/focused_verdict_availability_report.pdf) | Earlier GPU runtime; same CSR14 endpoint |
| 2026-10-21 | [Focused checker comparison, preprocessing-v2](optimizations/2026-10-21_focused_hls4ml_checker_gpu_preprocess_v2/focused_hls4ml_checker_report.pdf) | Host-completion endpoint |
| 2026-10-21 | [Full benchmarks, preprocessing-v2](optimizations/2026-10-21_final_benchmarks_gpu_preprocess_v2/final_fpga_gpu_benchmark_report.pdf) | Full benchmark results |
| 2026-10-21 | [Original focused checker comparison](optimizations/2026-10-21_focused_hls4ml_checker/focused_hls4ml_checker_report.pdf) | Historical GPU runtime; retains stale marker |
| 2026-10-20 | [Original full benchmarks](optimizations/2026-10-20_final_benchmarks/final_fpga_gpu_benchmark_report.pdf) | Campaign began October 19; retains stale marker |
| 2026-10-13 | [Streaming optimization benchmarks](optimizations/streaming_optimization_benchmarks_20261013.pdf) | Existing standalone PDF |
| 2026-10-12 | [Streaming optimization results](optimizations/streaming_optimization_results_20261012.pdf) | Existing standalone PDF |
| 2026-10-11 | [Native FIFO sweep](optimizations/2026-10-11_native_fifo_sweep/) | CSVs and plots |
| 2026-10-09 | [U55C checker comparison](2026-10-09_u55c02/REPORT.md) | Historical D_I / D_N / R_S comparison; measurements October 9–10 |

The [path migration record](report_path_migration_2026-10-22.json) maps previous
folder names to current names. Historical PDFs, figures and measurement data
were not regenerated during this move. Path references in source and Markdown
were updated; their original versions and evidence manifests are preserved in
`.before_date_prefix/` within affected report folders. Renamed ZIP/tar bundles
remain byte-identical and retain their original internal paths.

The new R06 report reuses existing measurements. Its folder contains the PDF,
titled standalone figures, exported data, validation, and regeneration code.
