# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Merging Utility Package
*  File Name: frf_merge_plotting.py
*  File Description: Standalone plotting (static Bode centroid grid, Bode
*                    centroid metrics, frequency-gain-phase grid, convergence
*                    curve) and drive-cluster-mapping CSV export for the FRF
*                    cluster-merging utility. Self contained - no dependency
*                    on the training application package.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import re
import time
import colorsys
import textwrap
import logging
import multiprocessing as mp

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection


FREQUENCY_HZ = 'Frequency (Hz)'
GAIN_LABEL = 'Gain (dB)'
PHASE_LABEL = 'Phase (degrees)'
NORMALIZED_PHASE_LABEL = 'Normalized Phase'
UPPER_LEFT = 'upper left'


def _compute_legend_params(n_entries):
    """Compute (ncol, fontsize) for a matplotlib legend sized to n_entries."""
    ncol = max(1, (n_entries + 14) // 15)
    fontsize = max(5, 9 - max(0, n_entries - 15) // 5)
    return ncol, fontsize


def _wrap_merge_annotation(annotation, width=160):
    """Wrap a merge annotation for use in a plot title; returns (text, line_count)."""
    if not annotation:
        return '', 0
    wrapped = textwrap.fill(annotation, width=width, break_long_words=False, break_on_hyphens=False)
    return wrapped, wrapped.count('\n') + 1


def _safe_filename_label(label, max_len=60):
    """Sanitize an arbitrary label for use in a filename component."""
    if not label:
        return label
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', label)[:max_len]


class ColorGenerator(object):
    """Generates cluster colors: fixed tab10 palette for k <= 10, distinct HSV
    colors otherwise."""

    def __init__(self):
        self._tab10 = plt.cm.tab10(np.linspace(0, 1, 10))

    def get_colors_for_k(self, k):
        """Return a color array for k clusters."""
        if k <= 10:
            return self._tab10[:k]
        return self._generate_distinct_colors(k)

    @staticmethod
    def _generate_distinct_colors(n):
        """Golden-ratio hue spacing for visually distinct colors when n > 10."""
        if n <= 20:
            return plt.cm.tab20(np.linspace(0, 1, n))
        golden_ratio = (1 + 5 ** 0.5) / 2
        hues = [(i * golden_ratio) % 1.0 for i in range(n)]
        sat_levels, value_levels = (0.55, 0.65, 0.75), (0.72, 0.82, 0.92)
        colors = []
        for i, hue in enumerate(hues):
            rgb = colorsys.hsv_to_rgb(hue, sat_levels[i % 3], value_levels[(i + 1) % 3])
            colors.append(rgb)
        return np.array(colors)


class PlotExecutor(object):
    """Runs a plot function in an isolated subprocess with a timeout/retry loop,
    so a hung or crashed plotting backend can't take the whole run down."""

    def __init__(self, plot_timeout=1200, per_attempt_timeout=600):
        self.plot_timeout = plot_timeout
        self.per_attempt_timeout = per_attempt_timeout
        self.logger = logging.getLogger(__name__)

    def execute_plot_in_process(self, plot_callable, *args, **kwargs):
        """Execute plot_callable(*args, **kwargs) in a spawned subprocess with retries."""
        start_time = time.time()
        attempt = 0
        ctx = mp.get_context('spawn')
        while (time.time() - start_time) < self.plot_timeout:
            attempt += 1
            try:
                return self._attempt(ctx, plot_callable, args, kwargs, attempt)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.logger.warning(f"Plot generation failed (attempt {attempt}): {e}")
        self.logger.warning(f"PLOT GENERATION FAILED after {attempt} attempts: {plot_callable.__name__}")
        return False

    def _attempt(self, ctx, plot_callable, args, kwargs, attempt):
        """Run one subprocess attempt; return True on success, False on timeout."""
        process = ctx.Process(target=self._plot_wrapper, args=(plot_callable, args, kwargs))
        process.start()
        process.join(timeout=self.per_attempt_timeout)
        if process.is_alive():
            self.logger.warning(f"Plot timed out after {self.per_attempt_timeout}s (attempt {attempt})")
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
            return False
        return process.exitcode == 0

    @staticmethod
    def _plot_wrapper(plot_callable, args, kwargs):
        """Module-level-picklable subprocess entry point."""
        plot_callable(*args, **kwargs)


def save_drive_cluster_mapping(segment_file_dict, file_labels, file_indices, out_dir,
                                original_k=None, k_merged=None,
                                name_suffix=None):
    """Save the drive-name -> cluster-id mapping CSV for one plot snapshot."""
    rows = []
    for file_idx, original_file_idx in enumerate(file_indices):
        entry = segment_file_dict['files'][original_file_idx]
        rows.append({'Drive_name': entry['filename'], 'cluster_id': int(file_labels[file_idx])})
    if not rows:
        return
    origk_tag = f'_origk{original_k}' if original_k is not None else ''
    k_tag = f'_k{k_merged}' if k_merged is not None else ''
    suffix_tag = f'_{name_suffix}' if name_suffix else ''
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'dc{origk_tag}{k_tag}{suffix_tag}.csv')
    pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')
    logging.getLogger(__name__).info(f"Saved drive cluster mapping: {path}")


class BodePlotter(object):
    """Static Bode centroid plots: centroids-only grid and the 4-panel raw /
    normalized / normalized+trend / detrended-normalized phase metrics view."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _convert_centroids_to_gain_phase(cluster_means, frequencies):
        """Convert (k, n_freq, 2) real/imag centroids to per-cluster gain/phase arrays."""
        k = cluster_means.shape[0]
        gains, phases = [], []
        for cluster_id in range(k):
            real_part = cluster_means[cluster_id, :, 0]
            imag_part = cluster_means[cluster_id, :, 1]
            magnitude = np.sqrt(real_part ** 2 + imag_part ** 2)
            gain_db = np.where(magnitude > 0, 20 * np.log10(np.where(magnitude > 0, magnitude, 1)), -np.inf)
            phase_deg = np.degrees(np.arctan2(imag_part, real_part))
            gains.append(gain_db)
            phases.append(phase_deg)
        return gains, phases

    @staticmethod
    def _build_centroid_legend_label(cluster_id, file_count, real_counts, worst_counts):
        """Build a centroid legend label with an optional real-vs-worst breakdown line."""
        label = f'Centroid {cluster_id} ({file_count} files)'
        if real_counts is None or worst_counts is None:
            return label
        return f'{label}    Measured: {real_counts[cluster_id]}, Worst: {worst_counts[cluster_id]}'

    def create_static_bode_centroids_grid(self, cluster_means, frequencies, k, cluster_colors,
                                           out_dir, model_id, file_labels,
                                           merge_annotation=None, pre_merge_k=None,
                                           real_counts=None, worst_counts=None):
        """1x2 grid: centroid Gain vs Frequency | centroid Phase vs Frequency."""
        try:
            self._render_static_bode_centroids_grid(
                cluster_means, frequencies, k, cluster_colors, out_dir,
                model_id, file_labels, merge_annotation, pre_merge_k, real_counts, worst_counts
            )
        except Exception as e:
            self.logger.error(f"Error creating static Bode centroids grid: {e}")
            plt.close('all')

    def _render_static_bode_centroids_grid(self, cluster_means, frequencies, k, cluster_colors,
                                            out_dir, model_id, file_labels,
                                            merge_annotation, pre_merge_k, real_counts, worst_counts):
        """Actual rendering logic for create_static_bode_centroids_grid."""
        cluster_file_counts = [int(np.sum(file_labels == cid)) for cid in range(k)]
        legend_labels = [
            self._build_centroid_legend_label(cid, cluster_file_counts[cid], real_counts, worst_counts)
            for cid in range(k)
        ]
        gains, phases = self._convert_centroids_to_gain_phase(cluster_means, frequencies)

        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        ax_gain, ax_phase = axes[0], axes[1]
        for cid in range(k):
            ax_gain.plot(frequencies, gains[cid], color=cluster_colors[cid], linewidth=3,
                         alpha=0.9, label=legend_labels[cid])
            ax_phase.plot(frequencies, phases[cid], color=cluster_colors[cid], linewidth=3,
                          alpha=0.9, label=legend_labels[cid])

        ax_gain.set_xlabel(FREQUENCY_HZ, fontsize=12)
        ax_gain.set_ylabel(GAIN_LABEL, fontsize=12)
        ax_gain.set_title(f'Centroid Gain vs Frequency\nk={k}', fontsize=13)
        ax_gain.grid(True, alpha=0.3)

        ax_phase.set_xlabel(FREQUENCY_HZ, fontsize=12)
        ax_phase.set_ylabel(PHASE_LABEL, fontsize=12)
        ax_phase.set_title(f'Centroid Phase vs Frequency\nk={k}', fontsize=13)
        ax_phase.grid(True, alpha=0.3)

        handles, labels = ax_gain.get_legend_handles_labels()
        ncol, fontsize = _compute_legend_params(len(labels))
        fig.legend(handles, labels, loc=UPPER_LEFT, bbox_to_anchor=(1.01, 1.0),
                   bbox_transform=ax_phase.transAxes, fontsize=fontsize, framealpha=0.9,
                   borderaxespad=0, ncol=ncol)

        wrapped_annotation, ann_lines = _wrap_merge_annotation(merge_annotation)
        self._finalize_figure(fig, f'Bode Plot - Centroids Only\nModel: {model_id}', wrapped_annotation, ann_lines)

        origk_tag = f'_origk{pre_merge_k}' if pre_merge_k is not None else ''
        plot_name = f'b_cen{origk_tag}_k{k}.jpg'
        os.makedirs(out_dir, exist_ok=True)
        plt.savefig(os.path.join(out_dir, plot_name), dpi=150, bbox_inches='tight')
        plt.close('all')
        self.logger.info(f"Generated static Bode centroids grid: {plot_name}")

    @staticmethod
    def _finalize_figure(fig, title, wrapped_annotation, ann_lines):
        """Grow the figure to fit a (possibly wrapped, multi-line) title/annotation."""
        ann_suffix = f'\n{wrapped_annotation}' if wrapped_annotation else ''
        header_line_height_in = 0.32
        header_height = header_line_height_in * (2 + ann_lines)
        base_width, base_height = fig.get_size_inches()
        fig.set_size_inches(base_width, base_height + header_height)
        top_frac = base_height / (base_height + header_height)
        fig.suptitle(f'{title}{ann_suffix}', fontsize=14, fontweight='bold', y=1.0, va='top')
        plt.tight_layout(rect=[0, 0, 1, top_frac])

    @staticmethod
    def _normalize_phase_curve(phase_curve):
        """Min-max normalize a phase curve to [-1, 1]."""
        p_min, p_max = np.min(phase_curve), np.max(phase_curve)
        if p_max - p_min < 1e-10:
            return np.zeros_like(phase_curve)
        return 2.0 * (phase_curve - p_min) / (p_max - p_min) - 1.0

    @staticmethod
    def _compute_trend_line(curve, freqs):
        """Linear trend line fit for a 1-D curve."""
        coeffs = np.polyfit(freqs, curve, 1)
        return np.polyval(coeffs, freqs)

    def _extract_centroid_phase_data(self, cluster_means, unique_frequencies):
        """Raw / trend / normalized / normalized-trend / detrended-normalized phase arrays."""
        phases = np.degrees(np.arctan2(cluster_means[:, :, 1], cluster_means[:, :, 0]))
        freqs = np.asarray(unique_frequencies)
        raw_phases, trend_lines, normalized, normalized_trend_lines, detrended_normalized = \
            [], [], [], [], []
        for i in range(len(phases)):
            trend = self._compute_trend_line(phases[i], freqs)
            norm = self._normalize_phase_curve(phases[i])
            norm_trend = self._compute_trend_line(norm, freqs)
            raw_phases.append(phases[i])
            trend_lines.append(trend)
            normalized.append(norm)
            normalized_trend_lines.append(norm_trend)
            detrended_normalized.append(norm - norm_trend)
        return raw_phases, trend_lines, normalized, normalized_trend_lines, detrended_normalized

    def create_bode_centroid_metrics(self, cluster_means, unique_frequencies, k, cluster_colors,
                                      out_dir, model_id, file_labels,
                                      k_label=None, pre_merge_k=None, merge_annotation=None):
        """1x4 panel plot: Raw Phase+Trend | Normalized | Normalized+Trend | Detrended-Normalized."""
        try:
            self._render_bode_centroid_metrics(
                cluster_means, unique_frequencies, k, cluster_colors, out_dir,
                model_id, file_labels, k_label, pre_merge_k, merge_annotation
            )
        except Exception as e:
            self.logger.error(f"Error creating bode centroid metrics plot: {e}")
            plt.close('all')

    def _render_bode_centroid_metrics(self, cluster_means, unique_frequencies, k, cluster_colors,
                                       out_dir, model_id, file_labels,
                                       k_label, pre_merge_k, merge_annotation):
        """Actual rendering logic for create_bode_centroid_metrics."""
        label = k_label if k_label else f'k{k}'
        k_display = k_label if k_label else f'k={k}'
        freqs = np.asarray(unique_frequencies)
        cluster_file_counts = [int(np.sum(file_labels == cid)) for cid in range(k)]
        raw_phases, trend_lines, normalized, normalized_trend_lines, detrended_normalized = \
            self._extract_centroid_phase_data(cluster_means, unique_frequencies)

        fig, axes = plt.subplots(1, 4, figsize=(32, 6))
        self._plot_raw_phase_panel(axes[0], freqs, raw_phases, trend_lines, cluster_colors,
                                    cluster_file_counts, k, k_display)
        self._plot_normalized_panel(axes[1], freqs, normalized, cluster_colors, k, k_display)
        self._plot_normalized_with_trend_panel(axes[2], freqs, normalized, normalized_trend_lines,
                                                cluster_colors, k, k_display)
        self._plot_detrended_normalized_panel(axes[3], freqs, detrended_normalized, cluster_colors,
                                               k, k_display)

        handles, labels_text = axes[0].get_legend_handles_labels()
        ncol, fontsize = _compute_legend_params(k)
        fig.legend(handles, labels_text, loc=UPPER_LEFT, bbox_to_anchor=(1.01, 1.0),
                   bbox_transform=axes[3].transAxes, fontsize=fontsize, framealpha=0.9,
                   borderaxespad=0, ncol=ncol)

        wrapped_annotation, ann_lines = _wrap_merge_annotation(merge_annotation)
        self._finalize_figure(fig, f'Bode Centroid Metrics - Model: {model_id}', wrapped_annotation, ann_lines)

        origk_tag = f'_origk{pre_merge_k}' if pre_merge_k is not None else ''
        plot_name = f'b_cen_metrics{origk_tag}_{label}.jpg'
        os.makedirs(out_dir, exist_ok=True)
        plt.savefig(os.path.join(out_dir, plot_name), dpi=150, bbox_inches='tight')
        plt.close('all')
        self.logger.info(f"Generated bode centroid metrics plot: {plot_name}")

    @staticmethod
    def _plot_raw_phase_panel(ax, freqs, raw_phases, trend_lines, cluster_colors,
                               cluster_file_counts, k, k_display):
        """Panel 1: raw phase (solid) + linear trend (dashed) per centroid."""
        for cid in range(k):
            color = cluster_colors[cid]
            label = f'Centroid {cid} ({cluster_file_counts[cid]} files)'
            ax.plot(freqs, raw_phases[cid], color=color, linewidth=2, alpha=0.9, label=label)
            ax.plot(freqs, trend_lines[cid], color=color, linewidth=1.5, linestyle='--', alpha=0.7)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(PHASE_LABEL, fontsize=11)
        ax.set_title(f'Raw Phase + Linear Trend (dashed)\n{k_display}', fontsize=12)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _plot_normalized_panel(ax, freqs, normalized, cluster_colors, k, k_display):
        """Panel 2: normalized phase per centroid."""
        for cid in range(k):
            ax.plot(freqs, normalized[cid], color=cluster_colors[cid], linewidth=2, alpha=0.9)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(NORMALIZED_PHASE_LABEL, fontsize=11)
        ax.set_title(f'Centroid Normalized Phase vs Frequency\n{k_display}', fontsize=12)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _plot_normalized_with_trend_panel(ax, freqs, normalized, normalized_trend_lines,
                                           cluster_colors, k, k_display):
        """Panel 3: normalized phase (solid) + its own linear trend (dashed)."""
        for cid in range(k):
            color = cluster_colors[cid]
            ax.plot(freqs, normalized[cid], color=color, linewidth=2, alpha=0.9)
            ax.plot(freqs, normalized_trend_lines[cid], color=color, linewidth=1.5, linestyle='--', alpha=0.7)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(NORMALIZED_PHASE_LABEL, fontsize=11)
        ax.set_title(f'Normalized Phase + Linear Trend (dashed)\n{k_display}', fontsize=12)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _plot_detrended_normalized_panel(ax, freqs, detrended_normalized, cluster_colors,
                                          k, k_display):
        """Panel 4: normalized-then-detrended phase per centroid (metric-computation curve)."""
        for cid in range(k):
            ax.plot(freqs, detrended_normalized[cid], color=cluster_colors[cid], linewidth=2, alpha=0.9)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(NORMALIZED_PHASE_LABEL, fontsize=11)
        ax.set_title(
            f'Centroid Normalized-then-Detrended Phase vs Frequency\n{k_display}',
            fontsize=12
        )
        ax.grid(True, alpha=0.3)


class FrequencyGridPlotter(object):
    """2 x (k+1) grid of per-file Frequency vs Gain/Phase traces, one column per
    cluster plus a combined-clusters column."""

    MAX_GRID_WIDTH_PX = 20000
    MIN_SUBPLOT_WIDTH = 1.0

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _create_line_collection(ax, frequencies, data_arrays, color, alpha=0.6):
        """Efficiently plot many per-file traces via a single LineCollection."""
        segments = [np.column_stack([frequencies, data]) for data in data_arrays]
        lc = LineCollection(segments, colors=color, alpha=alpha, linewidths=1.5)
        ax.add_collection(lc)
        ax.autoscale()

    def create_frequency_gain_phase_grid(self, segment_file_dict, file_labels,
                                          out_dir, k, model_id, cluster_colors=None,
                                          k_label=None, pre_merge_k=None):
        """Create the 2x(k+1) frequency-vs-gain/phase grid plot."""
        try:
            self._render_grid(segment_file_dict, file_labels, out_dir, k,
                               model_id, cluster_colors, k_label, pre_merge_k)
        except Exception as e:
            self.logger.error(f"Error creating frequency gain/phase grid plot: {e}")
            plt.close('all')

    def _render_grid(self, segment_file_dict, file_labels, out_dir, k,
                      model_id, cluster_colors, k_label, pre_merge_k):
        """Actual rendering logic for create_frequency_gain_phase_grid."""
        num_files = len(segment_file_dict['files'])
        frequencies = segment_file_dict['frequencies']
        gain_min, gain_max = self._global_limits(segment_file_dict, 'gain')
        phase_min, phase_max = self._global_limits(segment_file_dict, 'phase')

        fig, axes = self._create_figure_and_axes(k)
        self._plot_individual_clusters(axes, segment_file_dict, file_labels, frequencies, k,
                                        cluster_colors, gain_min, gain_max, phase_min, phase_max)
        self._plot_combined_clusters(axes, segment_file_dict, file_labels, frequencies, k,
                                      cluster_colors, num_files, gain_min, gain_max, phase_min, phase_max)
        self._finalize_and_save(fig, out_dir, k, model_id, k_label, pre_merge_k)
        self.logger.info(f"Saved frequency gain/phase grid plot ({num_files} files)")

    @staticmethod
    def _global_limits(segment_file_dict, data_type):
        """Global min/max (with 5% padding) for gain or phase across all files."""
        all_values = []
        for data in segment_file_dict['files'].values():
            all_values.extend(data[data_type])
        v_min, v_max = min(all_values), max(all_values)
        padding = (v_max - v_min) * 0.05
        return v_min - padding, v_max + padding

    def _create_figure_and_axes(self, k):
        """Create a 2 x (k+1) figure sized within a bounded raster budget."""
        ncols = k + 1
        subplot_height, dpi = 4, 100
        subplot_width = max(min(5, self.MAX_GRID_WIDTH_PX / dpi / ncols), self.MIN_SUBPLOT_WIDTH)
        fig_width, fig_height = subplot_width * ncols, subplot_height * 2
        if fig_width * dpi > self.MAX_GRID_WIDTH_PX:
            dpi = max(40, int(self.MAX_GRID_WIDTH_PX / fig_width))
        fig, axes = plt.subplots(2, ncols, figsize=(fig_width, fig_height), dpi=dpi)
        if k == 1:
            axes = axes.reshape(2, -1)
        return fig, axes

    @staticmethod
    def _collect_cluster_data(segment_file_dict, file_labels, cluster_id, data_type):
        """Collect one data_type array per file belonging to cluster_id."""
        return [
            data[data_type] for file_idx, (_, data) in enumerate(segment_file_dict['files'].items())
            if file_labels[file_idx] == cluster_id
        ]

    @staticmethod
    def _format_subplot(ax, xlabel, ylabel, title, frequencies, v_min, v_max):
        """Apply shared axis labels/limits/grid formatting to a subplot."""
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(title, fontsize=11, fontweight='bold')
        ax.set_ylim(v_min, v_max)
        ax.set_xlim(frequencies[0], frequencies[-1])
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=9)

    def _plot_cluster_subplot(self, ax, frequencies, cluster_data, color, xlabel, ylabel,
                               title, v_min, v_max, cluster_id):
        """Render one cluster's per-file traces into its dedicated subplot."""
        if cluster_data:
            self._create_line_collection(ax, frequencies, cluster_data, color)
        self._format_subplot(ax, xlabel, ylabel, f'{title} - Cluster {cluster_id} ({len(cluster_data)} files)',
                              frequencies, v_min, v_max)

    def _plot_individual_clusters(self, axes, segment_file_dict, file_labels, frequencies, k,
                                   cluster_colors, gain_min, gain_max, phase_min, phase_max):
        """Fill the first k columns with per-cluster gain/phase subplots."""
        for cid in range(k):
            gains = self._collect_cluster_data(segment_file_dict, file_labels, cid, 'gain')
            phases = self._collect_cluster_data(segment_file_dict, file_labels, cid, 'phase')
            color = cluster_colors[cid]
            self._plot_cluster_subplot(axes[0, cid], frequencies, gains, color, FREQUENCY_HZ,
                                        GAIN_LABEL, 'Gain', gain_min, gain_max, cid)
            self._plot_cluster_subplot(axes[1, cid], frequencies, phases, color, FREQUENCY_HZ,
                                        PHASE_LABEL, 'Phase', phase_min, phase_max, cid)

    def _plot_combined_clusters(self, axes, segment_file_dict, file_labels, frequencies, k,
                                 cluster_colors, num_files, gain_min, gain_max, phase_min, phase_max):
        """Fill the final column with every cluster overlaid together."""
        ax_gain, ax_phase = axes[0, k], axes[1, k]
        for cid in range(k):
            gains = self._collect_cluster_data(segment_file_dict, file_labels, cid, 'gain')
            phases = self._collect_cluster_data(segment_file_dict, file_labels, cid, 'phase')
            if not gains:
                continue
            color = cluster_colors[cid]
            self._create_line_collection(ax_gain, frequencies, gains, color)
            self._create_line_collection(ax_phase, frequencies, phases, color)
            ax_gain.plot([], [], color=color, linewidth=2, label=f'Cluster {cid}')
            ax_phase.plot([], [], color=color, linewidth=2, label=f'Cluster {cid}')

        self._format_combined_subplot(ax_gain, GAIN_LABEL, f'Gain - All Clusters ({num_files} files)',
                                       frequencies, gain_min, gain_max, k)
        self._format_combined_subplot(ax_phase, PHASE_LABEL, f'Phase - All Clusters ({num_files} files)',
                                       frequencies, phase_min, phase_max, k)

    def _format_combined_subplot(self, ax, ylabel, title, frequencies, v_min, v_max, k):
        """Format the combined subplot and attach its always-visible legend."""
        self._format_subplot(ax, FREQUENCY_HZ, ylabel, title, frequencies, v_min, v_max)
        ncol, fontsize = _compute_legend_params(k)
        ax.legend(loc=UPPER_LEFT, bbox_to_anchor=(1.01, 1.0), fontsize=fontsize,
                  framealpha=0.9, borderaxespad=0, ncol=ncol)

    @staticmethod
    def _finalize_and_save(fig, out_dir, k, model_id, k_label, pre_merge_k):
        """Set the overall title (growing the figure for a wrapped label) and save."""
        wrapped_label, label_lines = _wrap_merge_annotation(k_label)
        title_suffix = f'\n{wrapped_label}' if wrapped_label else ''
        header_line_height_in = 0.32
        header_height = header_line_height_in * (2 + label_lines)
        base_width, base_height = fig.get_size_inches()
        fig.set_size_inches(base_width, base_height + header_height)
        top_frac = base_height / (base_height + header_height)
        fig.suptitle(f'Frequency Response Analysis - Model: {model_id}, '
                     f'k={k}{title_suffix}', fontsize=14, fontweight='bold', y=1.0, va='top')
        plt.tight_layout(rect=[0, 0, 1, top_frac], h_pad=2.5, w_pad=2.0)

        label = _safe_filename_label(k_label) if k_label else f'k{k}'
        origk_tag = f'_origk{pre_merge_k}' if pre_merge_k is not None else ''
        os.makedirs(out_dir, exist_ok=True)
        output_path = os.path.join(out_dir, f'fgp_grid{origk_tag}_{label}.jpg')
        plt.savefig(output_path, bbox_inches='tight')
        plt.close('all')


class ConvergencePlotter(object):
    """Plots the forward-pass deviation-vs-iteration convergence curve."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def plot_convergence_curve(self, deviations, k_merged, original_k, out_dir, model_id):
        """Line plot of files-reassigned-per-pass across the forward-pass loop."""
        if not deviations:
            return
        try:
            self._render_convergence_curve(deviations, k_merged, original_k, out_dir, model_id)
        except Exception as e:
            self.logger.error(f"Error creating merge convergence plot: {e}")
            plt.close('all')

    @staticmethod
    def _render_convergence_curve(deviations, k_merged, original_k, out_dir, model_id):
        """Actual rendering logic for plot_convergence_curve."""
        iterations = list(range(1, len(deviations) + 1))
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(iterations, deviations, marker='o', linewidth=2, color='tab:blue')
        ax.set_xlabel('Forward Pass Iteration')
        ax.set_ylabel('Drives Reassigned (vs. previous pass)')
        ax.set_title(f'Post-Merge Convergence - k={original_k} -> merged k={k_merged}')
        ax.grid(True, alpha=0.3)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f'merge_convergence_origk{original_k}_k{k_merged}.jpg')
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close('all')
