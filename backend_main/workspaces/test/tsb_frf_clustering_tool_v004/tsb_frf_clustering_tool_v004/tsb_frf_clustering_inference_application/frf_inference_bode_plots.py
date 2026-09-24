# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_bode_plots.py
*  File Description: File used to generate bode plots for the inference application.
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
import gc
import plotly.graph_objects as go
import logging
from frf_inference_metric_components import CircularStatistics, CoordinateConverter, CurveProcessor
from frf_inference_utils import ColorGenerator


FREQUENCY_HZ = 'Frequency (Hz)'
IMAGINARY_LABEL = 'Imaginary Part'
REAL_LABEL = 'Real Part'
GAIN_LABEL = 'Gain (dB)'
PHASE_LABEL = 'Phase (degrees)'
NORMALIZED_PHASE_LABEL = 'Normalized Phase'
UPPER_LEFT = 'upper left'


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


class PlotFrequencyGridVisualizer(object):
    """Handles frequency-gain-phase grid visualization"""

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
                                        k_label=None):
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
            self._finalize_and_save_plot(fig, k_dir, k, head_name, segment_name, k_label)

            self.logger.info(f"      Saved frequency gain/phase grid plot ({num_files} files)")

        except Exception:
            self.logger.error(f"Error creating frequency gain/phase grid plot")
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
        subplot_width = 5
        subplot_height = 4
        fig_width = subplot_width * (k + 1)
        fig_height = subplot_height * 2
        dpi = 100

        self.logger.info(f"Creating grid: {fig_width:.1f}x{fig_height:.1f} inches at {dpi} DPI")

        fig, axes = plt.subplots(2, k + 1, figsize=(fig_width, fig_height))

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
        """Format the combined subplot with optional legend"""
        self._format_subplot(ax, xlabel, ylabel, title, frequencies, global_min, global_max)

        if k <= 20:
            ax.legend(loc=UPPER_LEFT, bbox_to_anchor=(1.01, 1.0),
                      fontsize=6, framealpha=0.9, borderaxespad=0)

    def _finalize_and_save_plot(self, fig, k_dir, k, head_name, segment_name, k_label=None):
        """Set overall title, adjust layout, and save the plot"""
        fig.suptitle(f'Frequency Response Analysis - Head: {head_name}, Segment: {segment_name}, k={k}',
                    fontsize=14, fontweight='bold', y=0.998)

        plt.tight_layout(rect=[0, 0, 1, 0.99], h_pad=2.5, w_pad=2.0)

        label = k_label if k_label is not None else f'k{k}'
        output_path = os.path.join(k_dir, f'{head_name}_fgp_grid_{label}.jpg')

        self.logger.info(f"      Saving grid plot to: {output_path}")
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        plt.close('all')


class PlotInteractiveBodeVisualizer(object):
    """Handles interactive Bode plot visualizations using Plotly"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.circular_stats = CircularStatistics()
        self.coordinate_converter = CoordinateConverter()
        self.curve_processor = CurveProcessor()

    @staticmethod
    def _convert_color_to_plotly(matplotlib_color):
        """Convert matplotlib RGB color to plotly rgb string"""
        r, g, b = int(matplotlib_color[0] * 255), int(matplotlib_color[1] * 255), int(matplotlib_color[2] * 255)
        return f'rgb({r},{g},{b})'

    @staticmethod
    def _convert_centroids_to_gain_phase(cluster_centers_denormalized, frequencies):
        """Convert denormalized centroids from (real, imag) to (gain, phase)

        Args:
            cluster_centers_denormalized: Array of shape (k, n_frequencies, 2)
            frequencies: Array of frequency values

        Returns:
            centroid_gains: List of gain arrays, one per cluster
            centroid_phases: List of phase arrays, one per cluster
        """
        k = cluster_centers_denormalized.shape[0]
        centroid_gains = []
        centroid_phases = []

        for cluster_id in range(k):
            gains = []
            phases = []

            for freq_idx in range(len(frequencies)):
                real_part = cluster_centers_denormalized[cluster_id, freq_idx, 0]
                imag_part = cluster_centers_denormalized[cluster_id, freq_idx, 1]

                # Calculate gain (dB)
                magnitude = np.sqrt(real_part**2 + imag_part**2)
                gain_db = 20 * np.log10(magnitude) if magnitude > 0 else -np.inf

                # Calculate phase (degrees)
                phase_deg = np.degrees(np.arctan2(imag_part, real_part))

                gains.append(gain_db)
                phases.append(phase_deg)

            centroid_gains.append(np.array(gains))
            centroid_phases.append(np.array(phases))

        return centroid_gains, centroid_phases

    def _calculate_cluster_statistics(self, segment_file_dict, file_labels, k, frequencies):
        """Calculate mean and std for gain and phase for each cluster

        Returns:
            mean_gains: List of arrays (k clusters)
            std_gains: List of arrays (k clusters)
            mean_phases: List of arrays (k clusters)
            std_phases: List of arrays (k clusters)
        """
        mean_gains = []
        std_gains = []
        mean_phases = []
        std_phases = []

        for cluster_id in range(k):
            # Collect all gains and phases for this cluster
            cluster_gains_list = []
            cluster_phases_list = []

            for file_idx, (original_idx, data) in enumerate(segment_file_dict['files'].items()):
                if file_labels[file_idx] == cluster_id:
                    cluster_gains_list.append(data['gain'])
                    cluster_phases_list.append(data['phase'])

            if len(cluster_gains_list) > 0:
                # Convert lists to arrays for calculations; Shape: (n_files, n_frequencies)
                cluster_gains_array = np.array(cluster_gains_list)
                cluster_phases_array = np.array(cluster_phases_list)

                # Calculate gain statistics (standard mean and std)
                mean_gain = np.mean(cluster_gains_array, axis=0)
                std_gain = np.std(cluster_gains_array, axis=0)

                # Calculate phase statistics (circular mean and std)
                mean_phase = np.array([
                    self.circular_stats.circular_mean_deg(cluster_phases_array[:, freq_idx])
                    for freq_idx in range(len(frequencies))
                ])
                std_phase = np.array([
                    self.circular_stats.circular_std_deg(cluster_phases_array[:, freq_idx])
                    for freq_idx in range(len(frequencies))
                ])

                mean_gains.append(mean_gain)
                std_gains.append(std_gain)
                mean_phases.append(mean_phase)
                std_phases.append(std_phase)
            else:
                # Empty cluster - append zeros
                mean_gains.append(np.zeros(len(frequencies)))
                std_gains.append(np.zeros(len(frequencies)))
                mean_phases.append(np.zeros(len(frequencies)))
                std_phases.append(np.zeros(len(frequencies)))

        return mean_gains, std_gains, mean_phases, std_phases

    @staticmethod
    def _calculate_global_limits(segment_file_dict, value_key):
        all_values = []
        for data in segment_file_dict['files'].values():
            all_values.extend(data[value_key])

        global_min = min(all_values)
        global_max = max(all_values)
        padding = (global_max - global_min) * 0.05

        return global_min - padding, global_max + padding

    def _add_cluster_trajectories(self, fig, segment_file_dict, file_labels,
                                frequencies, k, cluster_colors,
                                value_key, hover_label, hover_unit):
        for cluster_id in range(k):
            cluster_color = self._convert_color_to_plotly(cluster_colors[cluster_id])

            x_values = []
            y_values = []
            filenames = []
            file_count = 0

            for file_idx, (_, data) in enumerate(segment_file_dict['files'].items()):
                if file_labels[file_idx] == cluster_id:
                    file_count += 1
                    x_values.extend(frequencies)
                    x_values.append(None)

                    y_values.extend(data[value_key])
                    y_values.append(None)

                    filenames.extend([data['filename']] * len(frequencies))
                    filenames.append(None)

            if x_values and x_values[-1] is None:
                x_values.pop()
                y_values.pop()

            if x_values:
                fig.add_trace(go.Scatter(
                    x=x_values,
                    y=y_values,
                    mode='lines',
                    name=f'Cluster {cluster_id} ({file_count} files)',
                    line=dict(color=cluster_color, width=1.5),
                    legendgroup=f'cluster_{cluster_id}',
                    showlegend=True,
                    visible=True,
                    text=filenames,
                    hovertemplate=(
                        'File: %{text}<br>'
                        'Frequency: %{x:.2f} Hz<br>'
                        f'{hover_label}: %{{y:.2f}} {hover_unit}<extra></extra>'
                    )
                ))

    def _add_statistical_traces(self, fig, frequencies, k, cluster_colors,
                                centroids, means, stds,
                                hover_label, hover_unit, cluster_file_counts):
        for cluster_id in range(k):
            cluster_color = self._convert_color_to_plotly(cluster_colors[cluster_id])

            if centroids is not None:
                is_empty = cluster_file_counts[cluster_id] == 0
                centroid_freq = [] if is_empty else frequencies
                centroid_vals = [] if is_empty else centroids[cluster_id]

                # Centroid border
                fig.add_trace(go.Scatter(
                    x=centroid_freq,
                    y=centroid_vals,
                    mode='lines',
                    line=dict(color='black', width=7),
                    legendgroup=f'centroid_{cluster_id}',
                    showlegend=False,
                    visible='legendonly',
                    hoverinfo='skip'
                ))

                # Centroid main
                fig.add_trace(go.Scatter(
                    x=centroid_freq,
                    y=centroid_vals,
                    mode='lines',
                    name=f'Centroid {cluster_id} ({cluster_file_counts[cluster_id]} files)',
                    line=dict(color=cluster_color, width=5),
                    legendgroup=f'centroid_{cluster_id}',
                    showlegend=True,
                    visible='legendonly',
                    hovertemplate=(
                        'Frequency: %{x:.2f} Hz<br>'
                        f'Centroid {hover_label}: %{{y:.2f}} {hover_unit}<extra></extra>'
                    )
                ))

            # Mean border
            fig.add_trace(go.Scatter(
                x=frequencies,
                y=means[cluster_id],
                mode='lines',
                line=dict(color='black', width=4, dash='dash'),
                legendgroup=f'stats_{cluster_id}',
                showlegend=False,
                visible='legendonly',
                hoverinfo='skip'
            ))

            # Mean main
            fig.add_trace(go.Scatter(
                x=frequencies,
                y=means[cluster_id],
                mode='lines',
                name=f'Mean and +- 3sigma Cluster {cluster_id}',
                line=dict(color=cluster_color, width=3, dash='dash'),
                legendgroup=f'stats_{cluster_id}',
                showlegend=True,
                visible='legendonly',
                hovertemplate=(
                    'Frequency: %{x:.2f} Hz<br>'
                    f'Mean {hover_label}: %{{y:.2f}} {hover_unit}<extra></extra>'
                )
            ))
            # +3σ / -3σ
            fig.add_trace(go.Scatter(
                x=frequencies,
                y=means[cluster_id] + 3 * stds[cluster_id],
                mode='lines',
                name=f'+3sigma {cluster_id}',
                line=dict(color=cluster_color, width=2, dash='dot'),
                legendgroup=f'stats_{cluster_id}',
                showlegend=False,
                visible='legendonly',
                hovertemplate=(
                    'Frequency: %{x:.2f} Hz<br>'
                    f'+3sigma {hover_label}: %{{y:.2f}} {hover_unit}<extra></extra>'
                )
            ))

            fig.add_trace(go.Scatter(
                x=frequencies,
                y=means[cluster_id] - 3 * stds[cluster_id],
                mode='lines',
                name=f'-3sigma {cluster_id}',
                line=dict(color=cluster_color, width=2, dash='dot'),
                legendgroup=f'stats_{cluster_id}',
                showlegend=False,
                visible='legendonly',
                hovertemplate=(
                    'Frequency: %{x:.2f} Hz<br>'
                    f'-3sigma {hover_label}: %{{y:.2f}} {hover_unit}<extra></extra>'
                )
            ))

    @staticmethod
    def _update_bode_layout(fig, frequencies, y_label,
                            global_min, global_max,
                            title, head_name, segment_name, k):
        fig.update_layout(
            title=(
                f'{title}<br>'
                f'Head: {head_name}, Segment: {segment_name}, k={k}'
            ),
            xaxis=dict(
                title=FREQUENCY_HZ,
                range=[min(frequencies), max(frequencies)],
                showgrid=True
            ),
            yaxis=dict(
                title=y_label,
                range=[global_min, global_max],
                showgrid=True
            ),
            width=1400,
            height=800,
            legend=dict(x=1.02, y=1),
            hovermode='closest'
        )

    def _create_gain_plot(self, segment_file_dict, file_labels, frequencies,
                        k, cluster_colors, centroid_gains, mean_gains, std_gains,
                        segment_name, head_name):

        fig = go.Figure()

        global_min, global_max = self._calculate_global_limits(segment_file_dict, 'gain')

        self._add_cluster_trajectories(
            fig, segment_file_dict, file_labels, frequencies, k,
            cluster_colors, 'gain', 'Gain', 'dB'
        )

        cluster_file_counts = [int(np.sum(file_labels == cluster_id)) for cluster_id in range(k)]
        self._add_statistical_traces(
            fig, frequencies, k, cluster_colors,
            centroid_gains, mean_gains, std_gains,
            'Gain', 'dB', cluster_file_counts
        )

        self._update_bode_layout(
            fig, frequencies, GAIN_LABEL,
            global_min, global_max,
            'Interactive Bode Plot - Gain vs Frequency',
            head_name, segment_name, k
        )

        return fig

    def _create_phase_plot(self, segment_file_dict, file_labels, frequencies,
                        k, cluster_colors, centroid_phases, mean_phases, std_phases,
                        segment_name, head_name):

        fig = go.Figure()

        global_min, global_max = self._calculate_global_limits(segment_file_dict, 'phase')

        self._add_cluster_trajectories(
            fig, segment_file_dict, file_labels, frequencies, k,
            cluster_colors, 'phase', 'Phase', '°'
        )

        cluster_file_counts = [int(np.sum(file_labels == cluster_id)) for cluster_id in range(k)]
        self._add_statistical_traces(
            fig, frequencies, k, cluster_colors,
            centroid_phases, mean_phases, std_phases,
            'Phase', '°', cluster_file_counts
        )

        self._update_bode_layout(
            fig, frequencies, PHASE_LABEL,
            global_min, global_max,
            'Interactive Bode Plot - Phase vs Frequency',
            head_name, segment_name, k
        )

        return fig

    def create_interactive_bode_plots(self, segment_file_dict, file_labels,
                                     segment_name, k_dir, k, head_name,
                                     cluster_colors, cluster_centers_denormalized,
                                     k_label=None):
        """Create two separate interactive Bode plots (gain and phase)"""
        try:
            frequencies = segment_file_dict['frequencies']

            self.logger.info(f"      Creating interactive Bode plots for k={k}")

            # Convert centroids from (real, imag) to (gain, phase) only if available
            if cluster_centers_denormalized is not None:
                centroid_gains, centroid_phases = self._convert_centroids_to_gain_phase(
                    cluster_centers_denormalized, frequencies
                )
            else:
                centroid_gains, centroid_phases = None, None

            # Calculate cluster statistics
            mean_gains, std_gains, mean_phases, std_phases = self._calculate_cluster_statistics(
                segment_file_dict, file_labels, k, frequencies
            )

            # Create gain plot
            fig_gain = self._create_gain_plot(
                segment_file_dict, file_labels, frequencies, k, cluster_colors,
                centroid_gains, mean_gains, std_gains, segment_name, head_name
            )

            # Save gain plot
            label = k_label if k_label is not None else f'k{k}'
            gain_path = os.path.join(k_dir, f'{head_name}_int_bg_{label}.html')
            fig_gain.write_html(gain_path, include_plotlyjs=True)
            del fig_gain
            gc.collect()

            # Create phase plot
            fig_phase = self._create_phase_plot(
                segment_file_dict, file_labels, frequencies, k, cluster_colors,
                centroid_phases, mean_phases, std_phases, segment_name, head_name
            )

            # Save phase plot
            phase_path = os.path.join(k_dir, f'{head_name}_int_bp_{label}.html')
            fig_phase.write_html(phase_path, include_plotlyjs=True)
            del fig_phase
            gc.collect()

        except Exception as e:
            self.logger.error(f"Error creating interactive Bode plots: {e}")

    @staticmethod
    def _build_centroid_legend_label(cluster_id, file_count, real_counts, worst_counts):
        """Build a centroid legend label: total file count, then a real vs worst-model
        breakdown on the line beneath it. Inference has no worst-model-file concept, so
        worst_counts is always zero here — every file is a measured file — but the label
        format matches the training application's bode centroid plot exactly."""
        label = f'Centroid {cluster_id} ({file_count} files)'
        if real_counts is None or worst_counts is None:
            return label
        return f'{label}    Measured: {real_counts[cluster_id]}, Worst: {worst_counts[cluster_id]}'

    def create_static_bode_centroids_grid(self, cluster_centers_denormalized, frequencies,
                                          k, cluster_colors, segment_name, k_dir, head_name,
                                          file_labels, k_label=None):
        """Create static 1x2 grid of Bode plots showing only centroids

        Args:
            cluster_centers_denormalized: Array of shape (k, n_frequencies, 2) with [real, imag]
            frequencies: Array of frequency values
            k: Number of clusters
            cluster_colors: Array of colors for each cluster
            segment_name: Name of frequency segment
            k_dir: Directory to save plot
            head_name: Head identifier
            file_labels: Array of cluster assignments per file
        """
        try:
            cluster_file_counts = [int(np.sum(file_labels == cluster_id)) for cluster_id in range(k)]
            # All inference files are measured (there is no worst-model-file concept here)
            real_counts = cluster_file_counts
            worst_counts = [0] * k
            cluster_legend_labels = [
                self._build_centroid_legend_label(cluster_id, cluster_file_counts[cluster_id],
                                                   real_counts, worst_counts)
                for cluster_id in range(k)
            ]

            # Convert centroids from (real, imag) to (gain, phase)
            centroid_gains, centroid_phases = self._convert_centroids_to_gain_phase(
                cluster_centers_denormalized, frequencies
            )

            # Create 1x2 grid
            fig, axes = plt.subplots(1, 2, figsize=(16, 6))

            # Left subplot: Frequency vs Gain
            ax_gain = axes[0]
            for cluster_id in range(k):
                is_empty = cluster_file_counts[cluster_id] == 0
                plot_freqs = [] if is_empty else frequencies
                plot_gains = [] if is_empty else centroid_gains[cluster_id]
                ax_gain.plot(plot_freqs, plot_gains,
                           color=cluster_colors[cluster_id], linewidth=3,
                           label=cluster_legend_labels[cluster_id], alpha=0.9)

            ax_gain.set_xlabel(FREQUENCY_HZ, fontsize=12)
            ax_gain.set_ylabel(GAIN_LABEL, fontsize=12)
            ax_gain.set_title(f'Centroid Gain vs Frequency\nSegment: {segment_name}, k={k}', fontsize=13)
            ax_gain.grid(True, alpha=0.3)

            # Right subplot: Frequency vs Phase
            ax_phase = axes[1]
            for cluster_id in range(k):
                is_empty = cluster_file_counts[cluster_id] == 0
                label = cluster_legend_labels[cluster_id]
                plot_freqs = [] if is_empty else frequencies
                plot_phases = [] if is_empty else centroid_phases[cluster_id]
                ax_phase.plot(plot_freqs, plot_phases,
                            color=cluster_colors[cluster_id], linewidth=3,
                            label=label, alpha=0.9)

            ax_phase.set_xlabel(FREQUENCY_HZ, fontsize=12)
            ax_phase.set_ylabel(PHASE_LABEL, fontsize=12)
            ax_phase.set_title(f'Centroid Phase vs Frequency\nSegment: {segment_name}, k={k}', fontsize=13)
            ax_phase.grid(True, alpha=0.3)

            # Single shared legend anchored outside the right edge of the rightmost subplot
            handles, labels = ax_gain.get_legend_handles_labels()
            ncol, fontsize = _compute_legend_params(len(labels))
            fig.legend(handles, labels,
                       loc=UPPER_LEFT,
                       bbox_to_anchor=(1.01, 1.0),
                       bbox_transform=ax_phase.transAxes,
                       fontsize=fontsize, framealpha=0.9, borderaxespad=0,
                       ncol=ncol)

            # Overall title
            fig.suptitle(f'Bode Plot - Centroids Only\nHead: {head_name}',
                        fontsize=14, fontweight='bold', y=1.00)

            plt.tight_layout(rect=[0, 0, 1, 0.95])

            label = k_label if k_label is not None else f'k{k}'
            plot_name = f'{head_name}_b_cen_{label}.jpg'
            save_path = os.path.join(k_dir, plot_name)
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            plt.close('all')

            self.logger.info(f"      Generated static Bode centroids grid: {plot_name}")

        except Exception:
            self.logger.error(f"Error creating static Bode centroids grid")
            plt.close('all')

    def _extract_centroid_phase_data(self, cluster_means, unique_frequencies):
        """Extract raw, normalized, normalized-trend and normalized-then-detrended phase arrays"""
        phases = np.degrees(np.arctan2(cluster_means[:, :, 1], cluster_means[:, :, 0]))
        freqs = np.asarray(unique_frequencies)
        raw_phases, trend_lines, normalized, normalized_trend_lines, detrended_normalized = \
            [], [], [], [], []

        for i in range(len(phases)):
            trend = self.curve_processor.compute_trend_line(phases[i], freqs)
            norm = self.curve_processor.normalize_curve_to_range(phases[i])
            norm_trend = self.curve_processor.compute_trend_line(norm, freqs)
            raw_phases.append(phases[i])
            trend_lines.append(trend)
            normalized.append(norm)
            normalized_trend_lines.append(norm_trend)
            detrended_normalized.append(norm - norm_trend)

        return raw_phases, trend_lines, normalized, normalized_trend_lines, detrended_normalized

    @staticmethod
    def _plot_raw_phase_panel(ax, freqs, raw_phases, cluster_colors,
                               cluster_file_counts, k, segment_name, k_display):
        """Plot raw phase for each centroid on ax. Empty clusters are kept in the
        legend but plotted with no data."""
        for cid in range(k):
            color = cluster_colors[cid]
            label = f'Centroid {cid} ({cluster_file_counts[cid]} files)'
            is_empty = cluster_file_counts[cid] == 0
            plot_freqs = [] if is_empty else freqs
            plot_phase = [] if is_empty else raw_phases[cid]
            ax.plot(plot_freqs, plot_phase, color=color, linewidth=2, alpha=0.9, label=label)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(PHASE_LABEL, fontsize=11)
        ax.set_title(f'Raw Phase\nSegment: {segment_name}, {k_display}',
                     fontsize=12)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _plot_normalized_panel(ax, freqs, normalized, cluster_colors, cluster_file_counts,
                               k, segment_name, k_display):
        """Plot normalized phase for each centroid on ax. Empty clusters are skipped."""
        for cid in range(k):
            if cluster_file_counts[cid] == 0:
                continue
            ax.plot(freqs, normalized[cid], color=cluster_colors[cid], linewidth=2, alpha=0.9)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(NORMALIZED_PHASE_LABEL, fontsize=11)
        ax.set_title(f'Centroid Normalized Phase vs Frequency\nSegment: {segment_name}, {k_display}',
                     fontsize=12)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _plot_normalized_with_trend_panel(ax, freqs, normalized, normalized_trend_lines,
                                          cluster_colors, cluster_file_counts, k, segment_name, k_display):
        """Plot normalized phase (solid) and the linear trend fit on it (dashed) for each
        centroid. Empty clusters are skipped."""
        for cid in range(k):
            if cluster_file_counts[cid] == 0:
                continue
            color = cluster_colors[cid]
            ax.plot(freqs, normalized[cid], color=color, linewidth=2, alpha=0.9)
            ax.plot(freqs, normalized_trend_lines[cid], color=color, linewidth=1.5,
                    linestyle='--', alpha=0.7)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(NORMALIZED_PHASE_LABEL, fontsize=11)
        ax.set_title(f'Normalized Phase + Linear Trend (dashed)\nSegment: {segment_name}, {k_display}',
                     fontsize=12)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _plot_detrended_normalized_panel(ax, freqs, detrended_normalized, cluster_colors,
                                         cluster_file_counts, k, segment_name, k_display):
        """Plot normalized-then-detrended phase for each centroid on ax. Empty clusters
        are skipped."""
        for cid in range(k):
            if cluster_file_counts[cid] == 0:
                continue
            ax.plot(freqs, detrended_normalized[cid], color=cluster_colors[cid],
                    linewidth=2, alpha=0.9)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(NORMALIZED_PHASE_LABEL, fontsize=11)
        ax.set_title(f'Centroid Normalized-then-Detrended Phase vs Frequency'
                     f'\nSegment: {segment_name}, {k_display}', fontsize=12)
        ax.grid(True, alpha=0.3)

    def create_bode_centroid_metrics(self, cluster_means, unique_frequencies, k, cluster_colors,
                                     segment_name, output_dir, head_name, file_labels,
                                     k_label=None):
        """Create 1 x 4 static Bode centroid metrics plot. When baseline_separation is
        active, the normalized-then-detrended panel is dropped (1 x 3) since the baseline
        group separation plot already covers that view."""
        try:
            label = k_label if k_label else f'k{k}'
            k_display = k_label if k_label else f'k={k}'
            freqs = np.asarray(unique_frequencies)
            cluster_file_counts = [int(np.sum(file_labels == cid)) for cid in range(k)]

            raw_phases, _, normalized, normalized_trend_lines, detrended_normalized = \
                self._extract_centroid_phase_data(cluster_means, unique_frequencies)

            fig, axes = plt.subplots(1, 4, figsize=(32, 6))
            self._plot_raw_phase_panel(axes[0], freqs, raw_phases,
                                       cluster_colors, cluster_file_counts, k,
                                       segment_name, k_display)
            self._plot_normalized_panel(axes[1], freqs, normalized, cluster_colors,
                                        cluster_file_counts, k, segment_name, k_display)
            self._plot_normalized_with_trend_panel(axes[2], freqs, normalized, normalized_trend_lines,
                                                   cluster_colors, cluster_file_counts, k,
                                                   segment_name, k_display)
            self._plot_detrended_normalized_panel(axes[3], freqs, detrended_normalized, cluster_colors,
                                                  cluster_file_counts, k, segment_name, k_display)

            handles, labels_text = axes[0].get_legend_handles_labels()
            ncol, fontsize = _compute_legend_params(k)
            fig.legend(handles, labels_text, loc=UPPER_LEFT,
                       bbox_to_anchor=(1.01, 1.0), bbox_transform=axes[3].transAxes,
                       fontsize=fontsize, framealpha=0.9, borderaxespad=0, ncol=ncol)

            fig.suptitle(f'Bode Centroid Metrics — Head: {head_name}',
                         fontsize=14, fontweight='bold', y=1.0, va='top')
            plt.tight_layout(rect=[0, 0, 1, 0.94])

            plot_name = f'{head_name}_b_cen_metrics_{label}.jpg'
            plt.savefig(os.path.join(output_dir, plot_name), dpi=150, bbox_inches='tight')
            plt.close('all')
            self.logger.info(f"      Generated bode centroid metrics plot: {plot_name}")

        except Exception as e:
            self.logger.error(f"Error creating bode centroid metrics plot: {e}")
            plt.close('all')
