#!/usr/bin/env python3
"""HBM benchmark figures/PDF, using the archived report's data and conventions."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

os.environ.setdefault('MPLCONFIGDIR', '/tmp/hbm_report_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np

try:
    import reportlab
except ImportError:
    sys.path.append('/usr/lib/python3/dist-packages')
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak

REPO = next(parent for parent in Path(__file__).resolve().parents
            if (parent / 'ML_Based_Deep_Bitstream_Inspection_for_Serverless_FPGAs_Report.pdf').exists())
ARCHIVE = REPO / 'hls4ml/optimize/reports/optimizations/2026-10-22_gpu_opt_xla_concretefunction'
COLORS = {'FPGA_HLS4ML': '#2878B5', 'GPU_P2P': '#E98A25'}
CAPACITY = dict(LUT=1303680, FF=2607360, BRAM_tiles=2016, DSP=9024, URAM=960)


def read_json(path):
    return json.loads(path.read_text())


def resources():
    old = read_json(ARCHIVE / 'data/resources.json')['Resource-optimized streaming']
    result = {'OPT_6 (archived)': dict(wrapper=old['wrapper'], full=old['full_design'])}
    source_root = REPO / 'hls4ml/optimize/runs/hbm_network_20261107'
    for label, name in [('OPT_10 (HBM FPGA)', 'OPT_10_HBM_GATHER_DSP_B2_RF72_RF288'),
                        ('OPT_11 (HBM GPU)', 'OPT_11_HBM_GPU_P2P_R06')]:
        path = source_root / name / 'attempt_01/build/reports/shell_utilization_hierarchical.rpt'
        parsed = dict(source=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for line in path.read_text().splitlines():
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            if cells and cells[0] in ['cyt_top', 'inst_user_wrapper_0']:
                values = dict(LUT=int(cells[4]), FF=int(cells[8]),
                              BRAM_tiles=int(cells[9]) + int(cells[10]) / 2,
                              URAM=int(cells[11]), DSP=int(cells[12]))
                parsed['full' if cells[0] == 'cyt_top' else 'wrapper'] = values
        assert 'wrapper' in parsed and 'full' in parsed
        result[label] = parsed
    return result


class Report:
    def __init__(self, campaign, output):
        self.campaign = campaign
        self.output = output
        self.figures = output / 'figures'
        self.figures.mkdir(exist_ok=True)
        self.rows = read_json(output / 'data/trial_events.json')
        self.stats = read_json(output / 'data/statistics.json')
        self.real = read_json(ARCHIVE / 'data/real_inputs.json')
        self.story = []
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle('CaptionSmall', parent=self.styles['BodyText'], fontSize=9,
                                       leading=12, spaceAfter=10))
        self.catalog = []
        plt.rcParams.update({'font.size': 10, 'axes.spines.top': False,
                             'axes.spines.right': False, 'svg.fonttype': 'none',
                             'pdf.fonttype': 42, 'axes.titleweight': 'bold'})

    def values(self, variant, case):
        return [row for row in self.rows if row['variant'] == variant and row['case_id'] == case]

    def metric(self, variant, case, name='verdict_ms', stat='median'):
        item = next(row for row in self.stats if row['variant'] == variant and row['case_id'] == case)
        return item['metrics'][name][stat]

    def text(self, value, style='BodyText'):
        self.story.append(Paragraph(value, self.styles[style]))
        self.story.append(Spacer(1, 7))

    def table(self, rows, widths=None):
        cells = [[Paragraph(str(cell), self.styles['CaptionSmall']) for cell in row] for row in rows]
        table = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAF0F6')),
                                   ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                   ('LINEBELOW', (0, 0), (-1, 0), 0.6, colors.grey),
                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
        self.story.append(table)
        self.story.append(Spacer(1, 10))

    def figure(self, name, fig, title, caption, page=True):
        # Title belongs to the image so exports remain usable without the PDF.
        fig.suptitle(title, fontsize=14, fontweight='bold', y=0.995)
        fig.tight_layout(rect=(0, 0.02, 1, 0.93))
        for extension in ['png', 'svg', 'pdf']:
            fig.savefig(self.figures / f'{name}.{extension}', dpi=180, bbox_inches='tight')
        if page:
            self.story.append(PageBreak())
        self.text(title, 'Heading1')
        width, height = fig.get_size_inches()
        scale = min(495 / width, 480 / height)
        self.story.append(Image(str(self.figures / f'{name}.png'), width=width * scale, height=height * scale))
        self.story.append(Spacer(1, 10))
        self.text(caption, 'CaptionSmall')
        self.catalog.append(dict(id=name, title=title, caption=caption))
        plt.close(fig)

    def latency(self):
        cases = [row['case_id'] for row in self.real]
        labels = [f"{row['id']}\n{row['input_bytes'] / 2**20:.2f} MiB" for row in self.real]
        fig, ax = plt.subplots(figsize=(10.4, 5.2))
        x = np.arange(len(cases))
        for offset, variant in [(-0.19, 'FPGA_HLS4ML'), (0.19, 'GPU_P2P')]:
            medians = [self.metric(variant, case) for case in cases]
            p95 = [self.metric(variant, case, stat='p95') for case in cases]
            bars = ax.bar(x + offset, medians, 0.36, color=COLORS[variant], label=variant)
            ax.scatter(x + offset, p95, marker='_', s=100, color='black', zorder=4)
            if variant == 'FPGA_HLS4ML':
                for index, (bar, median) in enumerate(zip(bars, medians)):
                    top = max(p95[index], self.metric('FPGA closing', cases[index]),
                              self.metric('FPGA program 3', cases[index]))
                    ax.text(bar.get_x() + bar.get_width() / 2, top + 0.11, f'{median:.2f}',
                            ha='center', va='bottom', fontsize=9)
            else:
                ax.bar_label(bars, fmt='%.2f', padding=4, fontsize=9)
        ax.set_xticks(x, labels)
        ax.set_ylabel('Accepted HBM start → verdict available at FPGA (ms)')
        ax.set_ylim(0, max(self.metric('GPU_P2P', case, stat='p95') for case in cases) * 1.2)
        ax.plot([], [], color='black', marker='_', linestyle='', label='p95 marker')
        for variant, marker, label in [('FPGA closing', 'o', 'FPGA program 2 median'),
                                        ('FPGA program 3', 'D', 'FPGA program 3 median')]:
            ax.scatter(x - 0.19, [self.metric(variant, case) for case in cases], marker=marker,
                       s=35, facecolor='white', edgecolor='#364D63', zorder=5, label=label)
        ax.legend(loc='upper left')
        ax.grid(axis='y', alpha=0.2)
        self.figure('01_real_latency', fig, '1 · Verdict latency with the bitstream already in HBM',
                    'Bars: medians; black ticks: p95; 200 measured trials per workload after 20 warmups. '
                    'The origin is accepted FPGA start, and the endpoint is the FPGA verdict event. '
                    'FPGA bars use the initial program; hollow circles/diamonds show medians after two further identical-image '
                    'programming cycles (200 and 20 trials). The initial-to-closing 5% stability gate failed for several '
                    'workloads; this initialization sensitivity is retained and investigated in Appendix A5. '
                    'HBM preload, file access, GPU compilation and partial reconfiguration are excluded. '
                    'FPGA_HLS4ML is OPT_10 (quantized OPT_6 CNN); GPU_P2P is OPT_11 with R06 XLA compilation + ConcreteFunction FP32.')
        fig, ax = plt.subplots(figsize=(10.4, 4.6))
        ratios = [self.metric('GPU_P2P', case) / self.metric('FPGA_HLS4ML', case) for case in cases]
        bars = ax.bar(x, ratios, color=[COLORS['FPGA_HLS4ML'] if value >= 1 else '#999999' for value in ratios])
        for index, case in enumerate(cases):
            alternatives = [self.metric('GPU_P2P', case) / self.metric(variant, case)
                            for variant in ['FPGA_HLS4ML', 'FPGA closing', 'FPGA program 3']]
            ax.plot([index, index], [min(alternatives), max(alternatives)], color='black', linewidth=1.4)
        ax.plot([], [], color='black', linewidth=1.4, label='Across programmed FPGA states')
        ax.bar_label(bars, labels=[f'{value:.2f}×' for value in ratios], padding=5)
        ax.axhline(1, color='black', linewidth=1, linestyle='--', label='Equal latency')
        ax.set_xticks(x, labels)
        ax.set_ylabel('GPU_P2P median / FPGA_HLS4ML median')
        ax.set_ylim(0, max(ratios) * 1.25)
        ax.legend()
        ax.grid(axis='y', alpha=0.2)
        self.figure('02_real_speedup', fig, '2 · FPGA speedup and the small-input crossover',
                    'Above 1×: FPGA_HLS4ML is faster. Below 1×: GPU_P2P is faster. '
                    'The FPGA requests only the words containing selected pixels, but those small reads have substantial overhead. '
                    'The GPU forwards all bytes; its latency increases with input size. Thin vertical ranges show '
                    'the speedup across three programmed FPGA states, not confidence intervals. Bar labels use the initial state.')

    def topology(self):
        fig, ax = plt.subplots(figsize=(10.4, 6.0))
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 7)
        ax.axis('off')

        def box(x, y, width, height, text, color):
            ax.add_patch(FancyBboxPatch((x, y), width, height, boxstyle='round,pad=0.08',
                                       facecolor=color, edgecolor='#43546A'))
            ax.text(x + width / 2, y + height / 2, text, ha='center', va='center', fontsize=10)

        def arrow(a, b, label='', dashed=False):
            ax.add_patch(FancyArrowPatch(a, b, arrowstyle='-|>', mutation_scale=14,
                                         linestyle='--' if dashed else '-', color='#43546A'))
            if label:
                ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.14, label,
                        ha='center', fontsize=8, bbox=dict(facecolor='white', edgecolor='none', alpha=0.85))

        box(0.5, 5.6, 3.1, 0.8, 'Host CPU + RAM (emulates core)\nPreload and control; NUMA 1', '#ECEFF3')
        box(0.5, 3.9, 3.1, 0.9, 'U55C HBM: complete raw input\n81:00.0 · NUMA 1 · PCIe Gen3 ×16', '#D8EAF7')
        box(0.5, 1.9, 3.1, 1.1, 'OPT_10 selective HBM gather\nPreprocess → streaming CNN\nFPGA verdict timestamp', '#D8EAF7')
        box(5.8, 3.9, 3.3, 0.9, 'MI210 GPU0 · 03:00.0 · NUMA 0\nRaw input · PCIe Gen4 ×16', '#FCE6CE')
        box(5.8, 1.9, 3.3, 1.1, 'R06 XLA + ConcreteFunction\nFP32 preprocessing + inference\nGPU-resident verdict mailbox', '#FCE6CE')
        box(2.9, 0.3, 4.2, 0.7, 'OPT_11 FPGA autonomously polls GPU\nFPGA verdict timestamp', '#E2E8EF')
        arrow((2.05, 5.6), (2.05, 4.8), 'PCIe preload (untimed)', True)
        arrow((2.05, 3.9), (2.05, 3.0), 'Selected 64 B words')
        arrow((3.6, 4.35), (5.8, 4.35), 'OPT_11: full input PCIe P2P')
        arrow((7.45, 3.9), (7.45, 3.0))
        arrow((7.45, 1.9), (6.0, 1.0), 'P2P verdict readback')
        arrow((3.6, 6.0), (8.0, 4.8), 'CPU dispatches TensorFlow (control only)', True)
        ax.text(5, 0, 'Alternatives run separately; no concurrent FPGA/GPU inference.', ha='center', fontsize=9)
        self.figure('03_topology', fig, '3 · HBM-resident benchmark topology',
                    'The host places the raw bitstream in HBM before measurement, emulating an integrated or soft CPU. '
                    'The experiment does not implement an embedded CPU, PR, or fully hostless GPU execution. '
                    'GPU inference remains CPU-dispatched. P2P is between devices attached to different NUMA nodes; '
                    'the drawing shows the logical route, not a verified PCIe-switch diagram. U55C serial: XFL13BA4HVZYA.')

    def timelines(self):
        selected = [self.real[index] for index in [0, 3, 7]]
        fig, axes = plt.subplots(3, 2, figsize=(11.0, 9.0))
        for row_index, case in enumerate(selected):
            for column, variant in enumerate(COLORS):
                rows = self.values(variant, case['case_id'])
                middle = self.metric(variant, case['case_id'])
                row = min(rows, key=lambda item: abs(item['verdict_ms'] - middle))
                ax = axes[row_index, column]
                lanes = [('HBM returns', 'hbm_return_start_ms', 'hbm_return_end_ms', '#65A5CE')]
                if variant == 'FPGA_HLS4ML':
                    lanes += [('Pixel production', 'pixel_start_ms', 'pixel_end_ms', '#4BAE91'),
                              ('CNN input span', 'cnn_start_ms', 'cnn_end_ms', '#8975BD')]
                else:
                    lanes += [('GPU forwarding', 'gpu_forward_start_ms', 'gpu_forward_end_ms', '#E98A25'),
                              ('Framework call', 'gpu_framework_begin_ms', 'gpu_framework_end_ms', '#AA67A2'),
                              ('FPGA poll requests', 'poll_request_start_ms', 'poll_request_end_ms', '#929292')]
                for y, (label, start, end, color) in enumerate(lanes):
                    ax.barh(y, max(row[end] - row[start], 0.0001), left=row[start], height=0.5, color=color)
                ax.axvline(row['verdict_ms'], color='#B32B2B', linestyle='--', label='FPGA verdict')
                ax.set_yticks(range(len(lanes)), [lane[0] for lane in lanes], fontsize=8)
                ax.invert_yaxis()
                ax.set_xlim(0, row['verdict_ms'] * 1.08)
                ax.set_title(f"{case['id']} · {variant}", fontsize=11)
                ax.set_xlabel('Time since accepted FPGA start (ms)')
                ax.grid(axis='x', alpha=0.2)
        handles, labels = axes[-1, -1].get_legend_handles_labels()
        fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(0.5, 0.965),
                   frameon=False, fontsize=9)
        self.figure('04_timelines', fig, '4 · Memory delivery, streaming and GPU work overlap',
                    'Each panel is one measured trial nearest its workload median; panels use their own x-axis limits. '
                    'HBM, pixel and CNN spans overlap and must not be added. The CNN lane shows first-to-last input consumption, '
                    'not compute-only latency. Its output tail ends at the dashed verdict line. GPU framework call includes '
                    'dispatch, fused preprocessing/inference and synchronization; it is not a pure kernel span. '
                    'GPU host-clock events use the affine MMIO calibration; FPGA events share the local counter. '
                    'Polling overlaps waiting for GPU work, rather than adding the entire polling window after it.')

    def traffic(self):
        fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.8))
        x = np.arange(8)
        for offset, variant in [(-0.19, 'FPGA_HLS4ML'), (0.19, 'GPU_P2P')]:
            traffic = [self.values(variant, case['case_id'])[0]['requested_hbm_bytes'] / 2**20 for case in self.real]
            bandwidth = [self.metric(variant, case['case_id'], 'hbm_return_requested_GBps') for case in self.real]
            axes[0].bar(x + offset, traffic, 0.36, color=COLORS[variant], label=variant)
            axes[1].bar(x + offset, bandwidth, 0.36, color=COLORS[variant], label=variant)
        for ax in axes:
            ax.set_xticks(x, [case['id'] for case in self.real])
            ax.grid(axis='y', alpha=0.2)
            ax.legend(fontsize=8)
        axes[0].set_ylabel('Requested HBM payload (MiB)')
        axes[1].set_ylabel('Requested payload / first-to-last HBM return (GB/s)')
        axes[0].set_title('A · Selective versus full-input traffic')
        axes[1].set_title('B · Interface rate including gaps')
        self.figure('05_traffic', fig, '5 · Selective reads save traffic but have lower request efficiency',
                    'All eight real inputs use 65,536 distinct aligned 64-byte requests for FPGA_HLS4ML: 4 MiB requested '
                    'for 64 KiB useful sampled bytes. GPU_P2P requests and forwards the complete raw input. '
                    'The plotted rates include gaps within the first-to-last return interval and are not peak HBM bandwidth. '
                    'Requested/interface payload is distinct from physical HBM-wire traffic, which is not measured. '
                    'PCIe payload for OPT_10 is zero during checking; OPT_11 additionally sends all raw bytes to the GPU plus mailbox reads.')

    def archive_comparison(self):
        with (ARCHIVE / 'data/trial_events.csv').open() as source:
            old = list(csv.DictReader(source))
        fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.7))
        x = np.arange(8)
        for ax, variant, iteration in zip(axes, COLORS, ['OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288', 'OPT_8_GPU_P2P']):
            medians = [np.median([float(row['arm_to_verdict_available_ms']) for row in old
                                  if row['iteration'] == iteration and row['case_id'] == case['case_id']]) for case in self.real]
            assert np.isfinite(medians).all()
            ax.bar(x - 0.19, medians, 0.36, color='#A7B3BE', label='Archived host-fed input')
            ax.bar(x + 0.19, [self.metric(variant, case['case_id']) for case in self.real],
                   0.36, color=COLORS[variant], label='HBM-resident input')
            ax.set_title(variant)
            ax.set_xticks(x, [case['id'] for case in self.real])
            ax.set_ylabel('Local accepted start → FPGA verdict (ms)')
            ax.legend(fontsize=8)
            ax.grid(axis='y', alpha=0.2)
        self.figure('06_archived_comparison', fig, '6 · Deployment comparison: host-fed versus HBM-resident input',
                    'Archived measurements: 2026-10-21 R06 report; new measurements: 2026-11-08. Both use FPGA-local '
                    'accepted start to verdict, but they begin with different input residency and use different transport wrappers. '
                    'This is a deployment comparison, not an isolated causal estimate of HBM acceleration. '
                    'The gather implementation can be slower than the old streaming checker at small sizes; the new GPU forwarding '
                    'path benefits from direct HBM sourcing. Host/file-to-verdict scopes are deliberately excluded.')

    def predictions(self):
        fig, ax = plt.subplots(figsize=(10.5, 5.0))
        sizes = np.array([case['input_bytes'] for case in self.real])
        mib = sizes / 2**20
        tails = []
        for case in self.real:
            tails.append(np.median([row['verdict_ms'] - row['gpu_write_completion_end_ms']
                                    for row in self.values('GPU_P2P', case['case_id'])]))
        for speed, color, style in [(4.1, '#8E8E8E', ':'), (8.5, '#7D65AD', '--'), (15.75, '#609D78', '-.')]:
            ax.plot(mib, sizes / (speed * 1e6) + tails, linestyle=style, color=color,
                    label=f'Hypothetical GPU at {speed:g} GB/s + measured tail')
        ax.axhspan(1.12, 2.147152, color=COLORS['FPGA_HLS4ML'], alpha=0.09,
                   label='Prior FPGA prediction: 2–8 GB/s gather sensitivity')
        for variant in COLORS:
            ax.plot(mib, [self.metric(variant, case['case_id']) for case in self.real],
                    'o-', color=COLORS[variant], label=f'Measured {variant}')
        ax.set_xlabel('Raw input size (MiB)')
        ax.set_ylabel('HBM start → FPGA verdict (ms)')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.2)
        self.figure('07_prediction_scenarios', fig, '7 · Measured results and hypothetical P2P scenarios',
                    'Scenario curves replace the complete-input transfer with raw bytes / assumed rate, then add the new '
                    'measured per-case tail from final GPU-write completion to FPGA verdict. They assume negligible startup and '
                    'enough HBM supply bandwidth. Rates 4.1, 8.5 and 15.75 GB/s are scenarios, not achieved rates; 15.75 GB/s '
                    'is especially optimistic because protocol overhead prevents sustaining the encoded-link ceiling. '
                    'These curves are neither confidence intervals nor guarantees. The earlier 1.12 ms FPGA prediction was too '
                    'optimistic for this gather implementation; the measured selective-read delivery time explains the difference.')

    def resource_plot(self):
        values = resources()
        (self.output / 'data/resources.json').write_text(json.dumps(values, indent=2))
        fig, axes = plt.subplots(2, 5, figsize=(12.0, 7.1))
        labels = ['OPT_6', 'OPT_10', 'OPT_11']
        for row_index, scope in enumerate(['wrapper', 'full']):
            for column, resource in enumerate(CAPACITY):
                ax = axes[row_index, column]
                numbers = [item[scope][resource] for item in values.values()]
                bars = ax.bar(range(3), numbers, color=['#A7B3BE', COLORS['FPGA_HLS4ML'], COLORS['GPU_P2P']])
                ax.bar_label(bars, labels=[f'{value:,.0f}' if value.is_integer() else f'{value:g}' for value in map(float, numbers)],
                             padding=3, fontsize=7)
                ax.set_xticks(range(3), labels, rotation=30, fontsize=8)
                ax.set_title(resource.replace('_tiles', ' tiles'), fontsize=10)
                ax.set_ylim(0, max(max(numbers) * 1.3, 1))
                ax.set_ylabel('Application count' if scope == 'wrapper' else 'Full-design count', fontsize=8)
                secondary = ax.secondary_yaxis('right', functions=(lambda x, c=CAPACITY[resource]: x / c * 100,
                                                                  lambda x, c=CAPACITY[resource]: x * c / 100))
                secondary.set_ylabel('U55C %', fontsize=8)
                secondary.tick_params(labelsize=7)
                ax.tick_params(axis='y', labelsize=7)
        self.figure('08_resources', fig, '8 · Routed resource costs: application and full design',
                    'Top: inst_user_wrapper_0 including checker/transport logic. Bottom: complete routed design including '
                    'the shell. Counts at left; U55C capacity utilization at right. BRAM tiles = RAMB36 + 0.5 × RAMB18. '
                    'OPT_6 is the archived PCIe-streaming checker; OPT_10/11 enable HBM and contain different shell logic. '
                    'Wrapper attribution is reported directly; no unmatched no-op baseline is subtracted. '
                    'The GPU model uses external MI210 resources, which are not counted as FPGA area.')

    def appendix(self):
        self.story.append(PageBreak())
        self.text('Appendix · Synthetic workloads and diagnostics', 'Heading1')
        self.text('The primary comparison uses the same eight real inputs as the earlier report. Established synthetic '
                  'sizes and preprocessing boundaries are supplemental. Synthetic byte patterns differ from real files; '
                  'equal sizes alone do not imply equal request scheduling or identical model outputs.')
        sizes = [4194304, 16777216, 67108864, 134217664]
        cases = [f'synthetic_{size}' for size in sizes]
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.7))
        x = np.arange(4)
        for offset, variant in [(-0.19, 'FPGA_HLS4ML'), (0.19, 'GPU_P2P')]:
            bars = axes[0].bar(x + offset, [self.metric(variant, case) for case in cases], 0.36,
                               color=COLORS[variant], label=variant)
            axes[0].bar_label(bars, fmt='%.2f', padding=3, fontsize=8)
        ratios = [self.metric('GPU_P2P', case) / self.metric('FPGA_HLS4ML', case) for case in cases]
        axes[1].bar(x, ratios, color=COLORS['FPGA_HLS4ML'])
        axes[1].axhline(1, color='black', linestyle='--')
        for ax in axes:
            ax.set_xticks(x, ['4 MiB', '16 MiB', '64 MiB', '128 MiB − 64 B'])
            ax.grid(axis='y', alpha=0.2)
        axes[0].set_ylabel('HBM start → FPGA verdict (ms)')
        axes[0].legend()
        axes[1].set_ylabel('GPU median / FPGA median (×)')
        self.figure('A1_synthetic', fig, 'A1 · Established synthetic latency and FPGA speedup',
                    'Same measurement scope as the real-input figures. The largest case remains 128 MiB − 64 B to retain '
                    'the established GPU transport allocation convention. The 16 MiB point is shown without substituting '
                    'a different test pattern. No old file-to-verdict result is mixed into this HBM-resident experiment.', page=False)
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
        for variant in COLORS:
            rows = [row for row in self.rows if row['variant'] == variant and row['case_id'].startswith('real_')]
            axes[0].scatter([row['bytes'] / 2**20 for row in rows], [row['verdict_ms'] for row in rows],
                            s=6, alpha=0.2, color=COLORS[variant], label=variant)
            for case in self.real:
                values = sorted(row['verdict_ms'] for row in self.values(variant, case['case_id']))
                axes[1].plot(values, np.arange(1, len(values) + 1) / len(values),
                             color=COLORS[variant], alpha=0.6)
        axes[0].set_xlabel('Real input size (MiB)')
        axes[0].set_ylabel('FPGA verdict latency (ms)')
        axes[0].legend()
        axes[1].set_xlabel('FPGA verdict latency (ms)')
        axes[1].set_ylabel('Empirical cumulative fraction per real workload')
        for ax in axes:
            ax.grid(alpha=0.2)
        self.figure('A2_distributions', fig, 'A2 · All measured real-input trials and latency distributions',
                    'Each size contributes 200 unprofiled trials per variant. ECDFs are separate workload distributions, '
                    'not pooled confidence intervals. Blue: FPGA_HLS4ML; orange: GPU_P2P.')
        fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.8), gridspec_kw={'width_ratios': [1.4, 1]})
        ax = axes[0]
        diagnostic_sizes = [4095, 4096, 4097, 1048576, 2097152]
        x = np.arange(len(diagnostic_sizes))
        for offset, variant in [(-0.19, 'FPGA diagnostic'), (0.19, 'GPU diagnostic')]:
            color = COLORS['FPGA_HLS4ML' if variant.startswith('FPGA') else 'GPU_P2P']
            bars = ax.bar(x + offset, [self.metric(variant, f'boundary_{size}') for size in diagnostic_sizes],
                          0.36, label=variant, color=color)
            ax.bar_label(bars, fmt='%.3f', padding=3, fontsize=8)
        ax.set_xticks(x, ['4095 B', '4096 B', '4097 B', '1 MiB', '2 MiB'])
        ax.set_ylabel('HBM start → FPGA verdict (ms)')
        ax.legend(fontsize=8)
        ax.set_title('A · Padding and sample-driven paths', fontsize=10)
        ax = axes[1]
        for offset, variant in [(-0.19, 'FPGA_HLS4ML'), (0.19, 'GPU_P2P')]:
            bars = ax.bar(np.arange(3) + offset,
                          [self.metric(variant, f'smoke_{size}') for size in [4194240, 4194241, 4194242]],
                          0.36, color=COLORS[variant])
            ax.bar_label(bars, fmt='%.3f', padding=3, fontsize=8)
        ax.set_xticks(range(3), ['cutoff − 1 B', 'cutoff', 'cutoff + 1 B'], rotation=15)
        ax.set_ylabel('HBM start → FPGA verdict (ms)')
        ax.set_title('B · Former cutoff: 4,194,241 B', fontsize=10)
        self.figure('A3_small_input', fig, 'A3 · Boundary and small-input preprocessing checks',
                    'Panel A: 20 measured calls per case after two warmups. These cases use newly pinned deterministic random '
                    'patterns and exact hls4ml CPU references; they are separate from the primary input set. '
                    'Panel B: 200 measured calls after 20 warmups for each existing cutoff pattern; every call verifies parity. '
                    'The new gather function generates 65,536 sampled/padded pixels directly rather than scanning '
                    'every raw byte below the former cutoff. No matched old HLS-cycle rerun was available in this '
                    'board campaign, so no isolated small-input speedup is claimed.')

    def validation(self):
        self.story.append(PageBreak())
        self.text('Validation, timing and reproducibility', 'Heading1')
        rows = [['Gate', 'Evidence / outcome']]
        for stage in ['opt10_admission', 'opt11_admission', 'opt11_stale_visibility', 'opt10_diagnostics', 'opt11_diagnostics']:
            status = read_json(self.campaign / stage / 'status.json')
            rows.append([stage, f"{status['status']}; {status['validated_calls']} validated calls"])
        self.table(rows, [170, 325])
        drift = read_json(self.output / 'data/opening_closing_drift.json')
        within = read_json(self.output / 'data/within_program_drift.json')
        self.text(f"Opening/closing control: maximum absolute median change {max(abs(row['fractional_drift']) for row in drift) * 100:.3f}%; "
                  'the 5% cross-program stability gate failed. Correctness, byte counts and clock calibration passed. '
                  f"A second 200-trial repeat without reprogramming changed medians by at most {max(abs(row['fractional_drift']) for row in within) * 100:.3f}%, "
                  'and the old adapter reproduced the same second-program state. This localizes the change to memory '
                  'delivery associated with the programmed state; it does not prove a specific HBM calibration or clock-phase cause. '
                  'The report shows all three programmed states and does not claim cross-program stability. '
                  'A single board lease serialized the runs; no new FPGA build was required.')
        clocks = read_json(self.output / 'data/clock_models.json')
        self.text(f"The affine clock fits use 32 MMIO brackets before and after each workload. Fitted tick bounds span "
                  f"{min(row['ns_per_tick_min'] for row in clocks):.6f}–{max(row['ns_per_tick_max'] for row in clocks):.6f} ns. "
                  'Primary intervals use one FPGA clock, avoiding host-observation delay. GPU host-clock annotations carry '
                  'the alignment uncertainty recorded in data/trial_events.json. The ABI5 signature, status, trial, '
                  'event-valid bits, counts and final drain are checked on every recorded call.')
        self.text('OPT_10 admission requires exact quantized score bits and 65,536 pixels. OPT_11 requires finite '
                  'scores within 1e-4 absolute + 1e-4 relative error of its FP32 CPU model, identical threshold verdict, '
                  'exact raw-byte visibility, and completed forwarding counts. The two models have different precisions; '
                  'their logits are not required to match each other. HBM is verified before and after each workload '
                  'and re-offloaded after readback, because LOCAL_SYNC restores host-access mappings.')
        self.text('Unavailable counters: physical HBM-wire traffic, maximum outstanding requests, aggregate HBM stalls '
                  'and FIFO maximum occupancy. OPT_10 exposes final/current FIFO occupancy only; zero at completion '
                  'must not be interpreted as zero peak. GPU kernel sum and device span come from separate profiled '
                  'calls; unprofiled timing is used for all main latency figures. Fused XLA work is not split into '
                  'invented preprocessing and CNN-only components.')
        self.text('Reproduction: run the maintained hbm/benchmark.py under the board controller and matching driver, '
                  'then hbm/analyze.py followed by hbm/report.py. Raw trials, calibration, commands, source snapshots '
                  'and per-stage logs are in hls4ml/optimize/runs/hbm_benchmark_20261108. This folder preserves '
                  'the old report and uses its input identities, resource conventions, clock model and archived data.')

    def gpu_diagnostics(self):
        profile = read_json(self.campaign / 'opt11_profiles_02/profile_summary.json')
        (self.output / 'data/gpu_profiles.json').write_text(json.dumps(profile, indent=2))
        selected = [row for row in self.real if row['id'] in ['R1', 'R4', 'R8']]
        fig, ax = plt.subplots(figsize=(10.3, 4.8))
        x = np.arange(3)
        for offset, metric, color, label in [(-0.26, 'kernel_sum_ms', '#4A9E83', 'Kernel sum (profiled)'),
                                             (0, 'device_span_ms', '#9472B0', 'First-to-last kernel span (profiled)'),
                                             (0.26, 'framework_ms', '#E98A25', 'Framework synchronized call (unprofiled)')]:
            values = []
            for case in selected:
                if metric == 'framework_ms':
                    values.append(self.metric('GPU_P2P', case['case_id'], metric))
                else:
                    samples = next(row['samples'] for row in profile if row['case_id'] == case['case_id'])
                    values.append(float(np.median([row[metric] for row in samples])))
            bars = ax.bar(x + offset, values, 0.24, color=color, label=label)
            ax.bar_label(bars, fmt='%.3f', padding=3, fontsize=8)
        ax.set_xticks(x, [case['id'] for case in selected])
        ax.set_ylabel('Combined preprocessing + inference time (ms)')
        ax.legend(fontsize=8)
        self.figure('A4_gpu_compute', fig, 'A4 · Fused GPU compute: kernels, device span and framework call',
                    'Kernel sum adds recorded kernel durations; device span runs from first kernel start to last kernel end, '
                    'including intervening device gaps. Both are medians of five separate profiled calls. The synchronized '
                    'framework call is a median of 200 unprofiled hardware-path calls and additionally includes dispatch '
                    'and synchronization overhead. These are different scopes and trial sets. XLA fuses preprocessing '
                    'with model operations, so no artificial preprocessing/inference split is shown. Transport, mailbox '
                    'publication and FPGA polling are outside the compute marker. Profiling starts after one validated '
                    'P2P delivery and drained operation; it does not call the HIP mailbox adapter while tracing. '
                    'This isolates a ROCm profiler/publication interoperability failure encountered in the first '
                    'diagnostic attempt, which is retained in the campaign logs and excluded from reported measurements.')

    def repeatability(self):
        fig, axes = plt.subplots(1, 2, figsize=(11.2, 5.0))
        x = np.arange(8)
        for offset, variant, color, label in [(-0.25, 'FPGA_HLS4ML', '#2878B5', 'Program 1 · 200 trials'),
                                              (0, 'FPGA closing', '#7CA7C4', 'Program 2 · 200 trials'),
                                              (0.25, 'FPGA program 3', '#B5CBDC', 'Program 3 · 20 trials')]:
            axes[0].bar(x + offset, [self.metric(variant, case['case_id']) for case in self.real],
                        0.23, color=color, label=label)
        axes[0].set_ylabel('FPGA median verdict latency (ms)')
        axes[0].legend(fontsize=7)
        drift = read_json(self.output / 'data/within_program_drift.json')
        values = [next(item['fractional_drift'] * 100 for item in drift if item['case_id'] == case['case_id']) for case in self.real]
        axes[1].bar(x, values, color='#4BAE91')
        axes[1].axhline(0, color='black', linewidth=0.8)
        axes[1].axhline(5, color='grey', linestyle='--', label='±5% gate')
        axes[1].axhline(-5, color='grey', linestyle='--')
        axes[1].set_ylabel('Median change on repeat within program 2 (%)')
        axes[1].set_ylim(-5.8, 5.8)
        axes[1].legend(fontsize=8)
        for ax in axes:
            ax.set_xticks(x, [case['id'] for case in self.real])
            ax.grid(axis='y', alpha=0.2)
        self.figure('A5_repeatability', fig, 'A5 · Initialization sensitivity versus within-program repeatability',
                    'Three programming cycles use the identical OPT_10 image and driver. Program 1 and 2 each contain '
                    '200 measured calls after 20 warmups per workload; program 3 contains 20 measured calls after two '
                    'warmups. A second 200-call run in program 2 remains stable. The older transport adapter gives '
                    'the program-2 result too, ruling out the added start-acceptance guard. The shift occurs in the '
                    'first-to-last HBM return interval; the CNN tail and exact outputs remain stable. Physical placement '
                    'logs were captured, but clock/PHY initialization sensitivity remains a hypothesis. This limitation '
                    'must be retained when citing a single median from the main plots.')

    def build(self):
        self.text('HBM-resident bitstream inspection', 'Title')
        self.text('FPGA_HLS4ML versus GPU_P2P', 'Heading1')
        self.text('Report created: 2026-11-08 · Measurements: 2026-11-08 · Host: hacc-gpu-u55c-01.inf.ethz.ch')
        self.text('Question: when the complete raw bitstream is already in FPGA HBM, how soon can the FPGA obtain '
                  'a classification verdict? OPT_10 selectively gathers the sampled bytes and streams them into the '
                  'resource-optimized CNN. OPT_11 forwards all bytes to MI210 and autonomously polls its verdict mailbox.')
        table = [['Input', 'Size (MiB)', 'FPGA median / p95 (ms)', 'GPU median / p95 (ms)', 'FPGA speedup']]
        for case in self.real:
            key = case['case_id']
            a = self.metric('FPGA_HLS4ML', key)
            b = self.metric('GPU_P2P', key)
            table.append([case['id'], f"{case['input_bytes'] / 2**20:.2f}",
                          f"{a:.3f} / {self.metric('FPGA_HLS4ML', key, stat='p95'):.3f}",
                          f"{b:.3f} / {self.metric('GPU_P2P', key, stat='p95'):.3f}", f'{b / a:.2f}×'])
        self.table(table, [38, 65, 145, 145, 102])
        self.text('Read the speedup in either direction: values below 1× favor GPU_P2P. Selective HBM reads reduce '
                  'traffic but do not guarantee lower latency than sequential delivery. The new measurements show '
                  'a crossover, rather than a universal FPGA win. Compilation and cold-start costs are not included.')
        self.text('<b>Reproducibility limitation:</b> identical-image reprogramming changed some FPGA memory-delivery '
                  'medians by more than 5%. Main bars retain the initial run; additional markers and Appendix A5 expose '
                  'the other states. Within-program repeatability and exact classification checks passed.')
        self.latency()
        self.topology()
        self.timelines()
        self.traffic()
        self.archive_comparison()
        self.predictions()
        self.resource_plot()
        self.appendix()
        self.gpu_diagnostics()
        self.repeatability()
        self.validation()
        document = SimpleDocTemplate(str(self.output / 'hbm_resident_verdict_report.pdf'), pagesize=A4,
                                     leftMargin=50, rightMargin=50, topMargin=45, bottomMargin=45,
                                     title='HBM-resident bitstream inspection — 2026-11-08',
                                     author='ML Deep Bitstream Inspection')

        def footer(canvas, doc):
            canvas.setFont('Helvetica', 8)
            canvas.setFillColor(colors.grey)
            canvas.drawString(50, 25, 'HBM-resident inspection · 2026-11-08')
            canvas.drawRightString(A4[0] - 50, 25, str(doc.page))

        document.build(self.story, onFirstPage=footer, onLaterPages=footer)
        (self.output / 'data/figure_catalog.json').write_text(json.dumps(self.catalog, indent=2))
        shutil.copy2(__file__, self.output / 'build_report.py')
        with zipfile.ZipFile(self.output / 'standalone_figures.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.figures.iterdir()):
                archive.write(path, path.relative_to(self.output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('campaign', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    Report(args.campaign.resolve(), args.output.resolve()).build()
