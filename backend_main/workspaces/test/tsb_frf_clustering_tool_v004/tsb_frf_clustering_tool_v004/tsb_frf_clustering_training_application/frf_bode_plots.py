# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_bode_plots.py
*  File Description: File used to generate bode plots for the training application.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import re
import textwrap
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import logging
from frf_clustering_utils import ColorGenerator

LEGEND_POS = 'upper left'
FREQUENCY_HZ = 'Frequency (Hz)'
IMAGINARY_LABEL = 'Imaginary Part'
REAL_LABEL = 'Real Part'
GAIN_LABEL = 'Gain (dB)'
PHASE_LABEL = 'Phase (degrees)'
NORMALIZED_PHASE_LABEL = 'Normalized Phase'
DETRENDED_PHASE_LABEL = 'Detrended Phase (degrees)'

def _compute_legend_params(n_entries):
    """Compute (ncol, fontsize) for a matplotlib legend based on the number of entries"""
    ncol = max(1, (n_entries + 14) // 15)
    fontsize = max(5, 9 - max(0, n_entries - 15) // 5)
    return ncol, fontsize

def _wrap_merge_annotation(annotation, width=160):
    """Wrap a merge annotation"""
    if not annotation:
        return '', 0
    wrapped = textwrap.fill(annotation, width=width, break_long_words=False,
                             break_on_hyphens=False)
    return wrapped, wrapped.count('\n') + 1

def _safe_filename_label(label, max_len=60):
    """Shorten filenames"""
    if not label:
        return label
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', label)
    return safe[:max_len]


class PlotFrequencyGridVisualizer(object):
    """Handles frequency-gain-phase grid visualization"""
    MAX_GRID_WIDTH_PX = 20000
    MIN_SUBPLOT_WIDTH = 1.0

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.generate_colour = ColorGenerator()

    @staticmethod
    def create_line_collection(ax, frequencies, data_arrays, color, alpha=0.6):
        """Create a LineCollection for efficient plotting of many lines"""
        segments = []
        for data in data_arrays:
            points = np.column_stack([frequencies, data])
            segments.append(points)

        lc = LineCollection(segments, colors=color, alpha=alpha, linewidths=1.5)
        ax.add_collection(lc)
        ax.autoscale()

    def create_frequency_gain_phase_grid(self, segment_file_dict, file_labels,
                                        segment_name, k_dir, k, head_name, cluster_colors=None,
                                        k_label=None, pre_merge_k=None):
        """Create 2x(k+1) grid of Frequency vs Gain/Phase plots - OPTIMIZED FOR LARGE DATASETS"""
        try:
            # Use provided cluster_colors or fallback to generated colors
            if cluster_colors is None:
                cluster_colors = self.generate_colour.generate_distinct_colors(k)

            num_files = len(segment_file_dict['files'])
            self.logger.info(f"Creating grid plot for {num_files} files (optimized rendering)")

            frequencies = segment_file_dict['frequencies']

            # Calculate global limits
            global_gain_min, global_gain_max = self._calculate_global_limits(segment_file_dict, 'gain')
            global_phase_min, global_phase_max = self._calculate_global_limits(segment_file_dict, 'phase')

            # Create figure
            fig, axes = self._create_figure_and_axes(k)

            # Plot individual clusters
            self._plot_individual_clusters(axes, segment_file_dict, file_labels, frequencies, k,
                                        cluster_colors, global_gain_min, global_gain_max,
                                        global_phase_min, global_phase_max)

            # Plot combined clusters
            self._plot_combined_clusters(axes, segment_file_dict, file_labels, frequencies, k,
                                        cluster_colors, num_files, global_gain_min, global_gain_max,
                                        global_phase_min, global_phase_max)

            # Set overall title and save
            self._finalize_and_save_plot(fig, k_dir, k, head_name, segment_name, k_label=k_label,
                                         pre_merge_k=pre_merge_k)

            self.logger.info(f"      Saved frequency gain/phase grid plot ({num_files} files)")

        except Exception as e:
            self.logger.error(f"Error creating frequency gain/phase grid plot: {e}")
            plt.close('all')

    @staticmethod
    def _calculate_global_limits(segment_file_dict, data_type):
        """Calculate global min/max for gain or phase across all data"""
        all_values = []
        for data in segment_file_dict['files'].values():
            all_values.extend(data[data_type])

        global_min = min(all_values)
        global_max = max(all_values)

        # Add padding
        padding = (global_max - global_min) * 0.05
        global_min -= padding
        global_max += padding

        return global_min, global_max

    def _create_figure_and_axes(self, k):
        """Create figure with 2 rows and (k+1) columns"""
        ncols = k + 1
        subplot_height = 4
        dpi = 100

        subplot_width = min(5, self.MAX_GRID_WIDTH_PX / dpi / ncols)
        subplot_width = max(subplot_width, self.MIN_SUBPLOT_WIDTH)
        fig_width = subplot_width * ncols
        fig_height = subplot_height * 2

        if fig_width * dpi > self.MAX_GRID_WIDTH_PX:
            dpi = max(40, int(self.MAX_GRID_WIDTH_PX / fig_width))

        self.logger.info(
            f"Creating grid: {fig_width:.1f}x{fig_height:.1f} inches at {dpi} DPI "
            f"({ncols} columns)")

        fig, axes = plt.subplots(2, ncols, figsize=(fig_width, fig_height), dpi=dpi)

        # Ensure axes is 2D array even for k=1
        if k == 1:
            axes = axes.reshape(2, -1)

        return fig, axes

    @staticmethod
    def _collect_cluster_data(segment_file_dict, file_labels, cluster_id, data_type):
        """Collect gain or phase data for a specific cluster"""
        cluster_data = []

        for file_idx, (original_idx, data) in enumerate(segment_file_dict['files'].items()):
            if file_labels[file_idx] == cluster_id:
                cluster_data.append(data[data_type])

        return cluster_data

    @staticmethod
    def _format_subplot(ax, xlabel, ylabel, title, frequencies,
                        global_min, global_max):
        """Format a subplot with labels, title, and limits"""
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(title, fontsize=11, fontweight='bold')
        ax.set_ylim(global_min, global_max)
        ax.set_xlim(frequencies[0], frequencies[-1])
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=9)

    def _plot_cluster_subplot(self, ax, frequencies, cluster_data, color,
                            xlabel, ylabel, title, global_min, global_max, cluster_id):
        """Plot data for a single cluster subplot"""
        if len(cluster_data) > 0:
            self.create_line_collection(ax, frequencies, cluster_data, color)

        title_with_count = f'{title} - Cluster {cluster_id} ({len(cluster_data)} files)'
        self._format_subplot(ax, xlabel, ylabel, title_with_count,
                            frequencies, global_min, global_max)

    def _plot_individual_clusters(self, axes, segment_file_dict, file_labels, frequencies, k,
                                cluster_colors, global_gain_min, global_gain_max,
                                global_phase_min, global_phase_max):
        """Plot individual clusters in the first k columns"""
        for cluster_id in range(k):
            ax_gain = axes[0, cluster_id]
            ax_phase = axes[1, cluster_id]

            # Collect data for this cluster
            cluster_gains = self._collect_cluster_data(segment_file_dict, file_labels,
                                                        cluster_id, 'gain')
            cluster_phases = self._collect_cluster_data(segment_file_dict, file_labels,
                                                        cluster_id, 'phase')

            color = cluster_colors[cluster_id]

            # Plot gain subplot
            self._plot_cluster_subplot(ax_gain, frequencies, cluster_gains, color,
                                    FREQUENCY_HZ, GAIN_LABEL, 'Gain',
                                    global_gain_min, global_gain_max, cluster_id)

            # Plot phase subplot
            self._plot_cluster_subplot(ax_phase, frequencies, cluster_phases, color,
                                    FREQUENCY_HZ, PHASE_LABEL, 'Phase',
                                    global_phase_min, global_phase_max, cluster_id)

    def _plot_combined_clusters(self, axes, segment_file_dict, file_labels, frequencies, k,
                                cluster_colors, num_files, global_gain_min, global_gain_max,
                                global_phase_min, global_phase_max):
        """Plot all clusters together in the last column"""
        ax_gain_combined = axes[0, k]
        ax_phase_combined = axes[1, k]

        # Plot all clusters together
        for cluster_id in range(k):
            cluster_gains = self._collect_cluster_data(segment_file_dict, file_labels,
                                                        cluster_id, 'gain')
            cluster_phases = self._collect_cluster_data(segment_file_dict, file_labels,
                                                        cluster_id, 'phase')

            if len(cluster_gains) > 0:
                color = cluster_colors[cluster_id]

                # Plot data
                self.create_line_collection(ax_gain_combined, frequencies, cluster_gains, color)
                self.create_line_collection(ax_phase_combined, frequencies, cluster_phases, color)

                # Add legend proxy
                ax_gain_combined.plot([], [], color=color, linewidth=2, label=f'Cluster {cluster_id}')
                ax_phase_combined.plot([], [], color=color, linewidth=2, label=f'Cluster {cluster_id}')

        # Format gain combined subplot
        self._format_combined_subplot(ax_gain_combined, FREQUENCY_HZ, GAIN_LABEL,
                                    f'Gain - All Clusters ({num_files} files)',
                                    frequencies, global_gain_min, global_gain_max, k)

        # Format phase combined subplot
        self._format_combined_subplot(ax_phase_combined, FREQUENCY_HZ, PHASE_LABEL,
                                    f'Phase - All Clusters ({num_files} files)',
                                    frequencies, global_phase_min, global_phase_max, k)

    def _format_combined_subplot(self, ax, xlabel, ylabel, title, frequencies,
                                global_min, global_max, k):
        """Format the combined subplot with legend, always visible regardless of cluster count."""
        self._format_subplot(ax, xlabel, ylabel, title, frequencies, global_min, global_max)

        ncol, fontsize = _compute_legend_params(k)
        ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1.0),
                  fontsize=fontsize, framealpha=0.9, borderaxespad=0,
                  ncol=ncol)

    def _finalize_and_save_plot(self, fig, k_dir, k, head_name, segment_name, k_label=None,
                                pre_merge_k=None):
        """Set overall title, adjust layout, and save the plot"""
        wrapped_label, label_lines = _wrap_merge_annotation(k_label)
        title_suffix = f'\n{wrapped_label}' if wrapped_label else ''

        header_line_height_in = 0.32
        header_height = header_line_height_in * (2 + label_lines)
        base_width, base_height = fig.get_size_inches()
        fig.set_size_inches(base_width, base_height + header_height)
        top_frac = base_height / (base_height + header_height)

        fig.suptitle(
            f'Frequency Response Analysis - Head: {head_name}, Segment: {segment_name}, k={k}{title_suffix}',
            fontsize=14, fontweight='bold', y=1.0, va='top')

        plt.tight_layout(rect=[0, 0, 1, top_frac], h_pad=2.5, w_pad=2.0)

        label = _safe_filename_label(k_label) if k_label else f'k{k}'
        origk_tag = f'_origk{pre_merge_k}' if pre_merge_k is not None else ''
        output_path = os.path.join(
            k_dir, f'{head_name}_fgp_grid{origk_tag}_{label}.jpg')

        self.logger.info(f"      Saving grid plot to: {output_path}")
        plt.savefig(output_path, bbox_inches='tight')
        plt.close('all')
