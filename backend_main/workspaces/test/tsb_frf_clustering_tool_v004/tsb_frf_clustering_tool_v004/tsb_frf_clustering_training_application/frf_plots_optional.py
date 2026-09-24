# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_plots_optional.py
*  File Description: Interactive Bode, 2D frequency, and fan-segment plot visualizers.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import gc
from shapely.geometry import Polygon
from shapely.ops import unary_union
import plotly.graph_objects as go
import logging
from frf_metric_components import CircularStatistics, CoordinateConverter, CurveProcessor
from frf_metric_components import ConvexHullCalculator, FanSegmentCalculator
from frf_clustering_utils import ColorGenerator
from frf_bode_plots import (_compute_legend_params, _wrap_merge_annotation, _safe_filename_label,
                            FREQUENCY_HZ, GAIN_LABEL, PHASE_LABEL, NORMALIZED_PHASE_LABEL)
from frf_plots import LEGEND_POS, REAL_LABEL, IMAGINARY_LABEL


UPPER_LEFT = 'upper left'


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
    def _convert_centroids_to_gain_phase(cluster_centers_denormalized, frequencies):
        """Convert denormalized centroids from (real, imag) to (gain, phase)"""
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
        """Calculate mean and std for gain and phase for each cluster"""
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

            # Centroid border
            fig.add_trace(go.Scatter(
                x=frequencies,
                y=centroids[cluster_id],
                mode='lines',
                line=dict(color='black', width=7),
                legendgroup=f'centroid_{cluster_id}',
                showlegend=False,
                visible='legendonly',
                hoverinfo='skip'
            ))

            # Centroid main
            fig.add_trace(go.Scatter(
                x=frequencies,
                y=centroids[cluster_id],
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
                                     merge_annotation=None, pre_merge_k=None):
        """Create two separate interactive Bode plots (gain and phase)"""
        try:
            frequencies = segment_file_dict['frequencies']

            self.logger.info(f"      Creating interactive Bode plots for k={k}")

            # Convert centroids from (real, imag) to (gain, phase)
            centroid_gains, centroid_phases = self._convert_centroids_to_gain_phase(
                cluster_centers_denormalized, frequencies
            )

            # Calculate cluster statistics
            mean_gains, std_gains, mean_phases, std_phases = self._calculate_cluster_statistics(
                segment_file_dict, file_labels, k, frequencies
            )

            origk_tag = f'_origk{pre_merge_k}' if pre_merge_k is not None else ''

            # Create gain plot
            fig_gain = self._create_gain_plot(
                segment_file_dict, file_labels, frequencies, k, cluster_colors,
                centroid_gains, mean_gains, std_gains, segment_name, head_name
            )

            if merge_annotation:
                existing = fig_gain.layout.title.text or ''
                fig_gain.update_layout(title=f'{existing}<br>{merge_annotation}')

            # Save gain plot
            gain_path = os.path.join(
                k_dir, f'{head_name}_int_bg{origk_tag}_k{k}.html')
            fig_gain.write_html(gain_path, include_plotlyjs=True)
            del fig_gain
            gc.collect()

            # Create phase plot
            fig_phase = self._create_phase_plot(
                segment_file_dict, file_labels, frequencies, k, cluster_colors,
                centroid_phases, mean_phases, std_phases, segment_name, head_name
            )

            if merge_annotation:
                existing = fig_phase.layout.title.text or ''
                fig_phase.update_layout(title=f'{existing}<br>{merge_annotation}')

            # Save phase plot
            phase_path = os.path.join(
                k_dir, f'{head_name}_int_bp{origk_tag}_k{k}.html')
            fig_phase.write_html(phase_path, include_plotlyjs=True)
            del fig_phase
            gc.collect()

        except Exception:
            self.logger.error(f"Error creating interactive Bode plots")

    @staticmethod
    def _build_centroid_legend_label(cluster_id, file_count, real_counts, worst_counts):
        """Build a centroid legend label: total file count, then a real vs worst-model
        breakdown on the line beneath it. Falls back to a single line when the breakdown
        isn't available."""
        label = f'Centroid {cluster_id} ({file_count} files)'
        if real_counts is None or worst_counts is None:
            return label
        return f'{label}    Measured: {real_counts[cluster_id]}, Worst: {worst_counts[cluster_id]}'

    def create_static_bode_centroids_grid(self, cluster_centers_denormalized, frequencies,
                                          k, cluster_colors, segment_name, k_dir, head_name,
                                          file_labels, merge_annotation=None, pre_merge_k=None,
                                          real_counts=None, worst_counts=None):
        """Create static 1x2 grid of Bode plots showing only centroids"""
        try:
            cluster_file_counts = [int(np.sum(file_labels == cluster_id)) for cluster_id in range(k)]
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
                ax_gain.plot(frequencies, centroid_gains[cluster_id],
                           color=cluster_colors[cluster_id], linewidth=3,
                           label=cluster_legend_labels[cluster_id], alpha=0.9)

            ax_gain.set_xlabel(FREQUENCY_HZ, fontsize=12)
            ax_gain.set_ylabel(GAIN_LABEL, fontsize=12)
            wrapped_annotation, ann_lines = _wrap_merge_annotation(merge_annotation)
            ann_suffix = f'\n{wrapped_annotation}' if wrapped_annotation else ''
            ax_gain.set_title(
                f'Centroid Gain vs Frequency\nSegment: {segment_name}, k={k}',
                fontsize=13)
            ax_gain.grid(True, alpha=0.3)

            # Right subplot: Frequency vs Phase
            ax_phase = axes[1]
            for cluster_id in range(k):
                label = cluster_legend_labels[cluster_id]
                ax_phase.plot(frequencies, centroid_phases[cluster_id],
                             color=cluster_colors[cluster_id], linewidth=3,
                             alpha=0.9, label=label)

            ax_phase.set_xlabel(FREQUENCY_HZ, fontsize=12)
            ax_phase.set_ylabel(PHASE_LABEL, fontsize=12)
            ax_phase.set_title(
                f'Centroid Phase vs Frequency\nSegment: {segment_name}, k={k}',
                fontsize=13)
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
            header_line_height_in = 0.32
            header_height = header_line_height_in * (2 + ann_lines)
            base_width, base_height = fig.get_size_inches()
            fig.set_size_inches(base_width, base_height + header_height)
            top_frac = base_height / (base_height + header_height)

            fig.suptitle(f'Bode Plot - Centroids Only\nHead: {head_name}{ann_suffix}',
                        fontsize=14, fontweight='bold', y=1.0, va='top')

            plt.tight_layout(rect=[0, 0, 1, top_frac])

            origk_tag = f'_origk{pre_merge_k}' if pre_merge_k is not None else ''
            plot_name = f'{head_name}_b_cen{origk_tag}_k{k}.jpg'
            save_path = os.path.join(k_dir, plot_name)
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            plt.close('all')

            self.logger.info(f"      Generated static Bode centroids grid: {plot_name}")

        except Exception as e:
            self.logger.error(f"Error creating static Bode centroids grid: {e}")
            plt.close('all')

    def create_hierarchical_combined_interactive_bode_plots(self, combined_segment_file_dict, combined_file_labels,
                                                            combined_means, frequencies, parent_k, stage2_k,
                                                            segment_name, output_dir, head_name, cluster_colors):
        """Create interactive Bode plots for hierarchical combined clusters"""
        try:
            total_global_clusters = parent_k * stage2_k

            self.logger.info(f"      Creating hierarchical combined interactive Bode plots")
            self.logger.info(f"      Total global clusters: {total_global_clusters}")

            # Convert means from (real, imag) to (gain, phase)
            cluster_mean_gains, cluster_mean_phases = self._convert_centroids_to_gain_phase(
                combined_means, frequencies
            )

            # Calculate cluster statistics
            stat_mean_gains, std_gains, stat_mean_phases, std_phases = self._calculate_cluster_statistics(
                combined_segment_file_dict, combined_file_labels, total_global_clusters, frequencies
            )

            # Create gain plot
            fig_gain = self._create_gain_plot(
                combined_segment_file_dict, combined_file_labels, frequencies,
                total_global_clusters, cluster_colors, cluster_mean_gains, stat_mean_gains, std_gains,
                segment_name, head_name
            )

            # Update title for hierarchical plot
            fig_gain.update_layout(
                title=f'Interactive Bode Plot - Gain vs Frequency<br>Hierarchical: \
Stage 1 k={parent_k} — Stage 2 k={stage2_k} = {total_global_clusters} \
Clusters<br>Head: {head_name}, Segment: {segment_name}'
            )

            # Save gain plot
            gain_name = f'{head_name}_int_bg_h_s1_k{parent_k}_s2_k{stage2_k}.html'
            gain_path = os.path.join(output_dir, gain_name)
            fig_gain.write_html(gain_path, include_plotlyjs=True)
            del fig_gain
            gc.collect()

            # Create phase plot
            fig_phase = self._create_phase_plot(
                combined_segment_file_dict, combined_file_labels, frequencies,
                total_global_clusters, cluster_colors, cluster_mean_phases, stat_mean_phases, std_phases,
                segment_name, head_name
            )

            # Update title for hierarchical plot
            fig_phase.update_layout(
                title=f'Interactive Bode Plot - Phase vs Frequency<br>Hierarchical: \
Stage 1 k={parent_k} — Stage 2 k={stage2_k} = {total_global_clusters} \
Clusters<br>Head: {head_name}, Segment: {segment_name}'
            )

            # Save phase plot
            phase_name = f'{head_name}_int_bp_h_s1_k{parent_k}_s2_k{stage2_k}.html'
            phase_path = os.path.join(output_dir, phase_name)
            fig_phase.write_html(phase_path, include_plotlyjs=True)
            del fig_phase
            gc.collect()

            self.logger.info(f"      Saved hierarchical combined interactive Bode plots")

        except Exception as e:
            self.logger.error(f"Error creating hierarchical combined interactive Bode plots: {e}")

    def create_hierarchical_combined_static_bode_means(self, combined_means, frequencies,
                                                       parent_k, stage2_k, cluster_colors,
                                                       output_dir, head_name,
                                                       combined_file_labels,
                                                       real_counts=None, worst_counts=None):
        """Create static Bode means grid for hierarchical combined clusters"""
        try:
            total_global_clusters = parent_k * stage2_k
            cluster_file_counts = [int(np.sum(combined_file_labels == cluster_id))
                                   for cluster_id in range(total_global_clusters)]
            cluster_legend_labels = [
                self._build_centroid_legend_label(cluster_id, cluster_file_counts[cluster_id],
                                                   real_counts, worst_counts)
                for cluster_id in range(total_global_clusters)
            ]

            # Convert means from (real, imag) to (gain, phase)
            mean_gains, mean_phases = self._convert_centroids_to_gain_phase(
                combined_means, frequencies
            )

            # Create 1x2 grid
            fig, axes = plt.subplots(1, 2, figsize=(16, 6))

            # Left subplot: Frequency vs Gain
            ax_gain = axes[0]
            for cluster_id in range(total_global_clusters):
                ax_gain.plot(frequencies, mean_gains[cluster_id],
                        color=cluster_colors[cluster_id], linewidth=3,
                        label=cluster_legend_labels[cluster_id], alpha=0.9)

            ax_gain.set_xlabel(FREQUENCY_HZ, fontsize=12)
            ax_gain.set_ylabel(GAIN_LABEL, fontsize=12)
            ax_gain.set_title(f'Centroid Gain vs Frequency\nStage 1 k={parent_k} — Stage 2 k={stage2_k}', fontsize=13)
            ax_gain.grid(True, alpha=0.3)

            # Right subplot: Frequency vs Phase
            ax_phase = axes[1]
            for cluster_id in range(total_global_clusters):
                ax_phase.plot(frequencies, mean_phases[cluster_id],
                            color=cluster_colors[cluster_id], linewidth=3,
                            label=cluster_legend_labels[cluster_id], alpha=0.9)

            ax_phase.set_xlabel(FREQUENCY_HZ, fontsize=12)
            ax_phase.set_ylabel(PHASE_LABEL, fontsize=12)
            ax_phase.set_title(f'Centroid Phase vs Frequency\nStage 1 k={parent_k} — Stage 2 k={stage2_k}', fontsize=13)
            ax_phase.grid(True, alpha=0.3)

            # Single shared legend anchored outside the right edge of the rightmost subplot
            handles, labels = ax_gain.get_legend_handles_labels()
            ncol, fontsize = _compute_legend_params(total_global_clusters)
            fig.legend(handles, labels,
                       loc=UPPER_LEFT,
                       bbox_to_anchor=(1.01, 1.0),
                       bbox_transform=ax_phase.transAxes,
                       fontsize=fontsize, framealpha=0.9, borderaxespad=0,
                       ncol=ncol)

            plt.tight_layout(rect=[0, 0, 1, 0.88])

            title = f'Bode Plot - Centroids Only\nHierarchical: \
Stage 1 k={parent_k} — Stage 2 k={stage2_k}\nHead: {head_name}'
            fig.suptitle(title, fontsize=14, fontweight='bold', y=1.03)

            plot_name = f'{head_name}_b_cen_s1_k{parent_k}_s2_k{stage2_k}.jpg'
            save_path = os.path.join(output_dir, plot_name)
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            plt.close('all')

            self.logger.info(f"      Generated hierarchical combined static Bode centroid grid")

        except Exception as e:
            self.logger.error(f"Error creating hierarchical combined static Bode centroid grid: {e}")
            plt.close('all')

    @staticmethod
    def _plot_raw_phase_panel(ax, freqs, raw_phases, cluster_colors,
                               cluster_file_counts, k, segment_name, k_display):
        """Plot raw phase for each centroid on ax."""
        for cid in range(k):
            color = cluster_colors[cid]
            label = f'Centroid {cid} ({cluster_file_counts[cid]} files)'
            ax.plot(freqs, raw_phases[cid], color=color, linewidth=2, alpha=0.9, label=label)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(PHASE_LABEL, fontsize=11)
        ax.set_title(f'Raw Phase\nSegment: {segment_name}, {k_display}',
                     fontsize=12)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _plot_normalized_panel(ax, freqs, normalized, cluster_colors, k, segment_name, k_display):
        """Plot normalized phase for each centroid on ax."""
        for cid in range(k):
            ax.plot(freqs, normalized[cid], color=cluster_colors[cid], linewidth=2, alpha=0.9)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(NORMALIZED_PHASE_LABEL, fontsize=11)
        ax.set_title(f'Centroid Normalized Phase vs Frequency\nSegment: {segment_name}, {k_display}',
                     fontsize=12)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _plot_normalized_with_trend_panel(ax, freqs, normalized, normalized_trend_lines,
                                          cluster_colors, k, segment_name, k_display):
        """Plot normalized phase (solid) and the linear trend fit on it (dashed) for each centroid."""
        for cid in range(k):
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
                                         k, segment_name, k_display):
        """Plot normalized-then-detrended phase for each centroid on ax."""
        for cid in range(k):
            ax.plot(freqs, detrended_normalized[cid], color=cluster_colors[cid],
                    linewidth=2, alpha=0.9)
        ax.set_xlabel(FREQUENCY_HZ, fontsize=11)
        ax.set_ylabel(NORMALIZED_PHASE_LABEL, fontsize=11)
        ax.set_title(f'Centroid Normalized-then-Detrended Phase vs Frequency'
                     f'\nSegment: {segment_name}, {k_display}', fontsize=12)
        ax.grid(True, alpha=0.3)

    def create_bode_centroid_metrics(self, cluster_means, unique_frequencies, k, cluster_colors,
                                     segment_name, output_dir, head_name, file_labels,
                                     k_label=None, pre_merge_k=None, merge_annotation=None):
        """Create 1 x 4 static Bode centroid metrics plot"""
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
            self._plot_normalized_panel(axes[1], freqs, normalized, cluster_colors, k,
                                        segment_name, k_display)
            self._plot_normalized_with_trend_panel(axes[2], freqs, normalized, normalized_trend_lines,
                                                   cluster_colors, k, segment_name, k_display)
            self._plot_detrended_normalized_panel(axes[3], freqs, detrended_normalized, cluster_colors,
                                                  k, segment_name, k_display)

            handles, labels_text = axes[0].get_legend_handles_labels()
            ncol, fontsize = _compute_legend_params(k)
            fig.legend(handles, labels_text, loc=UPPER_LEFT,
                       bbox_to_anchor=(1.01, 1.0), bbox_transform=axes[3].transAxes,
                       fontsize=fontsize, framealpha=0.9, borderaxespad=0, ncol=ncol)

            wrapped_annotation, ann_lines = _wrap_merge_annotation(merge_annotation)
            ann_suffix = f'\n{wrapped_annotation}' if wrapped_annotation else ''

            header_line_height_in = 0.32
            header_height = header_line_height_in * (2 + ann_lines)
            base_width, base_height = fig.get_size_inches()
            fig.set_size_inches(base_width, base_height + header_height)
            top_frac = base_height / (base_height + header_height)

            fig.suptitle(f'Bode Centroid Metrics — Head: {head_name}{ann_suffix}',
                         fontsize=14, fontweight='bold', y=1.0, va='top')
            plt.tight_layout(rect=[0, 0, 1, top_frac])

            origk_tag = f'_origk{pre_merge_k}' if pre_merge_k is not None else ''
            plot_name = f'{head_name}_b_cen_metrics{origk_tag}_{label}.jpg'
            plt.savefig(os.path.join(output_dir, plot_name), dpi=150, bbox_inches='tight')
            plt.close('all')
            self.logger.info(f"      Generated bode centroid metrics plot: {plot_name}")

        except Exception as e:
            self.logger.error(f"Error creating bode centroid metrics plot: {e}")
            plt.close('all')


class Plot2DVisualizer(object):
    """Handles 2D frequency plots"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.generate_colour = ColorGenerator()

    def create_2d_frequency_plot(self, real_array, imag_array, labels, k, frequency,
                                 segment_name, k_dir, head_name, cluster_colors=None, centroids=None):
        """Create 2D plot for individual frequency with cluster colors and centroids"""
        fig, ax = plt.subplots(figsize=(12, 10))

        # Use provided cluster_colors or fallback to generated colors
        if cluster_colors is None:
            cluster_colors = self.generate_colour.generate_distinct_colors(k)

        # Plot each cluster
        for cluster_id in range(k):
            cluster_mask = labels == cluster_id
            if np.any(cluster_mask):
                ax.scatter(real_array[cluster_mask], imag_array[cluster_mask],
                          c=[cluster_colors[cluster_id]], label=f'Cluster {cluster_id}',
                          alpha=0.7, s=60, edgecolors='black', linewidth=0.8)

        # Plot centroids if provided
        if centroids is not None:
            for cluster_id in range(k):
                centroid_real = centroids[cluster_id, 0]
                centroid_imag = centroids[cluster_id, 1]
                ax.scatter(centroid_real, centroid_imag,
                          c=[cluster_colors[cluster_id]], marker='D', s=100,
                          linewidths=2, edgecolors='black',
                          label=f'Centroid {cluster_id}', zorder=10)

        ax.set_xlabel(REAL_LABEL, fontsize=12)
        ax.set_ylabel(IMAGINARY_LABEL, fontsize=12)
        ax.set_title(f'2D Plot for Frequency {frequency:.2f} Hz\nSegment: {segment_name}, k={k}', fontsize=14)
        ax.grid(True, alpha=0.3)
        ax.legend(bbox_to_anchor=(1.05, 1), loc=LEGEND_POS)
        ax.set_aspect('equal')

        plt.tight_layout()

        freq_str = f"{frequency:.2f}".replace('.', '_')
        save_path = os.path.join(k_dir, f'{head_name}_2d_freq_{freq_str}Hz_k{k}.jpg')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close('all')


class PlotFanSegmentVisualizer(object):
    """Handles fan segment visualization plots"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.generate_colour = ColorGenerator()
        self.convex_hull_calculater = ConvexHullCalculator()
        self.sigma_fan_arc = FanSegmentCalculator()

    def create_fan_segment_visualization(self, real_array, imag_array, gain_array, phase_array, labels,
                                        k, frequency, segment_name, k_dir, head_name, cluster_colors=None):
        """Create visualization showing fan segments, convex hull, and union"""
        fig, ax = plt.subplots(figsize=(14, 10))

        if cluster_colors is None:
            cluster_colors = self.generate_colour.generate_distinct_colors(k)

        self._plot_convex_hull(ax, real_array, imag_array)
        cluster_polygons = self._plot_cluster_fan_segments(ax, real_array, imag_array, gain_array,
                                                            phase_array, labels, k, cluster_colors)
        self._plot_union_polygon(ax, cluster_polygons)
        self._finalize_fan_plot(ax, frequency, segment_name, k, k_dir, head_name)

    def _plot_convex_hull(self, ax, real_array, imag_array):
        """Plot convex hull of all data points"""
        hull_x, hull_y, hull_area, _ = self.convex_hull_calculater.calculate_convex_hull(real_array, imag_array)
        ax.plot(hull_x, hull_y, 'k--', linewidth=2, label='Convex Hull', alpha=0.7)
        ax.fill(hull_x, hull_y, color='lightgray', alpha=0.3, label='Convex Hull Area')

    def _plot_cluster_fan_segments(self, ax, real_array, imag_array, gain_array,
                                phase_array, labels, k, cluster_colors):
        """Plot individual cluster fan segments and collect polygons"""
        cluster_polygons = []

        for cluster_id in range(k):
            cluster_mask = labels == cluster_id
            if not np.any(cluster_mask) or np.sum(cluster_mask) < 3:
                continue

            cluster_data = self._extract_cluster_data(real_array, imag_array, gain_array,
                                                    phase_array, cluster_mask)

            self._plot_cluster_points(ax, cluster_data['real'], cluster_data['imag'],
                                    cluster_colors[cluster_id], cluster_id)

            fan_polygon = self._plot_fan_segment(ax, cluster_data['gain'], cluster_data['phase'],
                                                cluster_colors[cluster_id])

            if fan_polygon:
                cluster_polygons.append(fan_polygon)

        return cluster_polygons

    @staticmethod
    def _extract_cluster_data(real_array, imag_array, gain_array, phase_array, cluster_mask):
        """Extract data for a specific cluster"""
        return {
            'real': real_array[cluster_mask],
            'imag': imag_array[cluster_mask],
            'gain': gain_array[cluster_mask],
            'phase': phase_array[cluster_mask]
        }

    @staticmethod
    def _plot_cluster_points(ax, cluster_real, cluster_imag, color, cluster_id):
        """Plot cluster data points"""
        ax.scatter(cluster_real, cluster_imag, c=[color],
                label=f'Cluster {cluster_id}', alpha=0.7, s=50,
                edgecolors='black', linewidth=0.5)

    def _plot_fan_segment(self, ax, cluster_gain, cluster_phase, color):
        """Plot fan segment for a cluster and return polygon"""
        try:
            _, _, outer_real, outer_imag, inner_real, inner_imag, fan_coords = \
                self.sigma_fan_arc.calculate_3sigma_fan_arc(cluster_gain, cluster_phase)

            # Plot fan segment boundary
            ax.plot(outer_real, outer_imag, color=color, linewidth=2, alpha=0.8)
            ax.plot(inner_real, inner_imag, color=color, linewidth=2, alpha=0.8)
            ax.plot([outer_real[0], inner_real[0]], [outer_imag[0], inner_imag[0]],
                color=color, linewidth=2, alpha=0.8)
            ax.plot([outer_real[-1], inner_real[-1]], [outer_imag[-1], inner_imag[-1]],
                color=color, linewidth=2, alpha=0.8)

            # Fill fan segment
            fan_polygon = self.sigma_fan_arc.create_fan_polygon(cluster_gain, cluster_phase)
            if fan_polygon and fan_polygon.is_valid:
                x, y = fan_polygon.exterior.xy
                ax.fill(x, y, color=color, alpha=0.2)
                return fan_polygon

        except Exception as e:
            self.logger.warning(f"Could not plot fan segment: {e}")

        return None

    def _plot_union_polygon(self, ax, cluster_polygons):
        """Plot union of all cluster polygons"""
        if not cluster_polygons:
            return

        try:
            union_polygon = unary_union(cluster_polygons)
            self._draw_union_boundary(ax, union_polygon)
        except Exception as e:
            self.logger.warning(f"Could not plot union polygon: {e}")

    def _draw_union_boundary(self, ax, union_polygon):
        """Draw the boundary of the union polygon"""
        if hasattr(union_polygon, 'exterior'):
            self._draw_single_polygon(ax, union_polygon)
            return

        if hasattr(union_polygon, 'geoms'):
            self._draw_multi_polygon(ax, union_polygon)

    @staticmethod
    def _draw_single_polygon(ax, polygon):
        """Draw a single polygon boundary"""
        x, y = polygon.exterior.xy
        ax.plot(x, y, 'r-', linewidth=3, label='Union of Fan Segments', alpha=0.8)

    @staticmethod
    def _draw_multi_polygon(ax, multi_polygon):
        """Draw multiple polygon boundaries"""
        for geom in multi_polygon.geoms:
            if hasattr(geom, 'exterior'):
                x, y = geom.exterior.xy
                ax.plot(x, y, 'r-', linewidth=3, alpha=0.8)

    @staticmethod
    def _finalize_fan_plot(ax, frequency, segment_name, k, k_dir, head_name):
        """Finalize and save fan segment plot"""
        ax.set_xlabel(REAL_LABEL, fontsize=12)
        ax.set_ylabel(IMAGINARY_LABEL, fontsize=12)
        ax.set_title(f'Fan Segments: {frequency:.2f} Hz\nSegment: {segment_name}, k={k}', fontsize=14)
        ax.grid(True, alpha=0.3)
        ax.legend(bbox_to_anchor=(1.05, 1), loc=LEGEND_POS)
        ax.set_aspect('equal')

        plt.tight_layout()
        freq_str = f"{frequency:.2f}".replace('.', '_')
        save_path = os.path.join(k_dir, f'{head_name}_fan_segments_{freq_str}Hz_k{k}.jpg')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close('all')
