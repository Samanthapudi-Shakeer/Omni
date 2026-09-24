# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_plots.py
*  File Description: File used to generate plots for the inference application.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import gc
import traceback
from shapely.geometry import Polygon
from shapely.ops import unary_union
import plotly.graph_objects as go
import plotly.express as px
import logging
from frf_inference_metric_components import ConvexHullCalculator, FanSegmentCalculator, CurveProcessor
from frf_inference_utils import ColorGenerator

LEGEND_POS = 'upper left'
FREQUENCY_HZ = 'Frequency (Hz)'
IMAGINARY_LABEL = 'Imaginary Part'
REAL_LABEL = 'Real Part'
GAIN_LABEL = 'Gain (dB)'
PHASE_LABEL = 'Phase (degrees)'
NORMDET_PHASE_LABEL = 'Normalized [-1, 1] + Detrended Phase'
CLUSTERED_TEMPLATE = '%{text}<br>Real: %{x:.4f}<br>Imaginary: %{y:.4f}<br>Frequency: %{z:.2f} Hz<extra></extra>'
UPPER_RIGHT = 'upper right'

BASELINE_GROUP_ORDER = ('phase_lead', 'phase_lag', 'no_resonance')
BASELINE_GROUP_TITLES = {'phase_lead': 'Phase Lead', 'phase_lag': 'Phase Lag', 'no_resonance': 'No Resonance'}
BASELINE_GROUP_COLORS = {'phase_lead': 'tab:red', 'phase_lag': 'tab:blue', 'no_resonance': 'tab:green'}


class Plot3DVisualizer(object):
    """Handles 3D trajectory visualizations (static and interactive)"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.generate_colour = ColorGenerator()

    def create_interactive_3d_visualization(self, segment_file_dict, segment_name, segment_dir, head_name,
                                            file_labels=None, k=None, cluster_colors=None, cluster_centers=None,
                                            k_label=None):
        """Create interactive 3D visualization using plotly"""
        fig = go.Figure()

        if file_labels is not None:
            self._add_clustered_traces(fig, segment_file_dict, file_labels, k,
                                    cluster_colors, cluster_centers)
            label = f'_{k_label}' if k_label is not None else ''
            plot_name = f'{head_name}_3d_traj_int_c{label}.html'
            title_suffix = 'Clustered (Interactive)'
        else:
            self._add_original_traces(fig, segment_file_dict)
            plot_name = f'{head_name}_3d_traj_int_o.html'
            title_suffix = 'Original Files (Interactive)'

        self._configure_and_save_interactive_plot(fig, segment_file_dict, segment_name,
                                                segment_dir, plot_name, title_suffix)

    def _add_clustered_traces(self, fig, segment_file_dict, file_labels, k,
                            cluster_colors, cluster_centers):
        """Add clustered trajectory traces to the figure"""
        n_clusters = k if k is not None else int(np.max(file_labels)) + 1

        # Use provided cluster_colors or fallback to generated colors
        if cluster_colors is None:
            cluster_colors = self._get_default_cluster_colors(n_clusters)
        else:
            cluster_colors = self._convert_cluster_colors_to_plotly(cluster_colors)

        # Add cluster trajectories
        for cluster_id in range(n_clusters):
            cluster_data = self._collect_cluster_trajectory_data(
                segment_file_dict, file_labels, cluster_id
            )

            if cluster_data['x']:
                self._add_cluster_trace(fig, cluster_data, cluster_id, cluster_colors[cluster_id])

        # Add centroid trajectories if provided
        if cluster_centers is not None:
            self._add_centroid_traces(fig, segment_file_dict, cluster_centers,
                                    n_clusters, cluster_colors, file_labels)

    @staticmethod
    def _get_default_cluster_colors(n_clusters):
        """Get default plotly colors for clusters"""
        if n_clusters <= len(px.colors.qualitative.Set3):
            return px.colors.qualitative.Set3[:n_clusters]
        else:
            return px.colors.qualitative.Plotly[:n_clusters]

    @staticmethod
    def _convert_cluster_colors_to_plotly(cluster_colors):
        """Convert numpy colors to plotly RGB format"""
        return [f'rgb({int(c[0]*255)},{int(c[1]*255)},{int(c[2]*255)})' for c in cluster_colors]

    @staticmethod
    def _collect_cluster_trajectory_data(segment_file_dict, file_labels, cluster_id):
        """Collect trajectory data for a specific cluster"""
        cluster_data = {'x': [], 'y': [], 'z': [], 'names': []}

        for file_idx, (original_idx, data) in enumerate(segment_file_dict['files'].items()):
            if file_labels[file_idx] == cluster_id:
                cluster_data['x'].extend(data['real'])
                cluster_data['x'].append(None)
                cluster_data['y'].extend(data['imaginary'])
                cluster_data['y'].append(None)
                cluster_data['z'].extend(segment_file_dict['frequencies'])
                cluster_data['z'].append(None)
                cluster_data['names'].extend([data['filename']] * len(data['real']) + [None])

        # Remove trailing None values
        if cluster_data['x'] and cluster_data['x'][-1] is None:
            cluster_data['x'] = cluster_data['x'][:-1]
            cluster_data['y'] = cluster_data['y'][:-1]
            cluster_data['z'] = cluster_data['z'][:-1]
            cluster_data['names'] = cluster_data['names'][:-1]

        return cluster_data

    @staticmethod
    def _add_cluster_trace(fig, cluster_data, cluster_id, color):
        """Add a single cluster trace to the figure"""
        fig.add_trace(go.Scatter3d(
            x=cluster_data['x'],
            y=cluster_data['y'],
            z=cluster_data['z'],
            mode='lines',
            marker=dict(size=1, color=color),
            line=dict(color=color, width=1),
            name=f'Cluster {cluster_id}',
            showlegend=True,
            legendgroup=f'cluster_{cluster_id}',
            text=cluster_data['names'],
            hovertemplate=CLUSTERED_TEMPLATE
        ))

    @staticmethod
    def _add_centroid_traces(fig, segment_file_dict, cluster_centers, n_clusters, cluster_colors,
                            file_labels=None):
        """Add centroid trajectory traces to the figure. Empty clusters (no files assigned)
        are kept in the legend but plotted with no data, so their degenerate centroid does
        not skew the visualization."""
        frequencies = segment_file_dict['frequencies']
        cluster_file_counts = None
        if file_labels is not None:
            file_labels_arr = np.asarray(file_labels)
            cluster_file_counts = [int(np.sum(file_labels_arr == cid)) for cid in range(n_clusters)]

        for cluster_id in range(n_clusters):
            is_empty = cluster_file_counts is not None and cluster_file_counts[cluster_id] == 0
            centroid_real = [] if is_empty else cluster_centers[cluster_id, :, 0]
            centroid_imag = [] if is_empty else cluster_centers[cluster_id, :, 1]
            centroid_freq = [] if is_empty else frequencies

            fig.add_trace(go.Scatter3d(
                x=centroid_real,
                y=centroid_imag,
                z=centroid_freq,
                mode='lines',
                line=dict(color=cluster_colors[cluster_id], width=5, dash='dash'),
                name=f'Centroid {cluster_id}',
                showlegend=True,
                legendgroup=f'centroid_{cluster_id}',
                hovertemplate=f'Centroid {cluster_id}<br>Frequency: %{{z:.2f}} Hz<extra></extra>'
            ))

    @staticmethod
    def _add_original_traces(fig, segment_file_dict):
        """Add original file traces to the figure"""
        for file_idx, (original_idx, data) in enumerate(segment_file_dict['files'].items()):
            fig.add_trace(go.Scatter3d(
                x=data['real'],
                y=data['imaginary'],
                z=segment_file_dict['frequencies'],
                mode='lines',
                line=dict(width=2),
                name=data['filename'],
                showlegend=False,
                hovertemplate=f"File: {data['filename']}<br>Frequency: %{{z:.2f}} Hz<extra></extra>"
            ))

    def _configure_and_save_interactive_plot(self, fig, segment_file_dict, segment_name,
                                            segment_dir, plot_name, title_suffix):
        """Configure layout and save the interactive plot"""
        frequencies = segment_file_dict['frequencies']
        freq_min, freq_max = min(frequencies), max(frequencies)

        fig.update_layout(
            title=f'3D Frequency Response Trajectories - {title_suffix}<br>Segment: {segment_name}',
            scene=dict(
                xaxis_title=REAL_LABEL,
                yaxis_title=IMAGINARY_LABEL,
                zaxis_title=FREQUENCY_HZ,
                zaxis=dict(
                    title=FREQUENCY_HZ,
                    tickmode='auto',
                    nticks=10,
                    showgrid=True
                ),
                xaxis=dict(
                    title=REAL_LABEL,
                    tickfont=dict(size=12, family='Arial')
                ),
                yaxis=dict(
                    title=IMAGINARY_LABEL,
                    tickfont=dict(size=12, family='Arial')
                ),
                camera=dict(eye=dict(x=1.5, y=1.5, z=1.5))
            ),
            width=1200,
            height=800,
        )

        save_path = os.path.join(segment_dir, plot_name)
        fig.write_html(save_path, include_plotlyjs=True)
        del fig
        gc.collect()
        self.logger.info(f"  Interactive 3D plot generated: {plot_name}")

    def create_3d_visualization(self, segment_file_dict, segment_name, segment_dir,
                            head_name, file_labels=None, k=None, cluster_colors=None, cluster_centers=None,
                            k_label=None):
        """Create 3D visualization of frequency response curves"""
        fig = plt.figure(figsize=(12, 9))
        ax = fig.add_subplot(111, projection='3d')
        ax.view_init(elev=20, azim=30)

        if file_labels is not None:
            plot_name = self._plot_clustered_3d(ax, segment_file_dict, file_labels, k,
                                                cluster_colors, cluster_centers, head_name, k_label)
            title_suffix = 'Clustered'
        else:
            plot_name = self._plot_original_3d(ax, segment_file_dict, head_name)
            title_suffix = 'Original Files'

        self._finalize_3d_plot(ax, segment_file_dict, segment_name, segment_dir,
                            plot_name, title_suffix, file_labels)

    def _plot_clustered_3d(self, ax, segment_file_dict, file_labels, k, cluster_colors, cluster_centers,
                           head_name, k_label=None):
        """Plot clustered 3D trajectories"""
        n_clusters = k if k is not None else int(np.max(file_labels)) + 1

        if cluster_colors is None:
            cluster_colors = self.generate_colour.generate_distinct_colors(n_clusters)

        self._plot_cluster_trajectories(ax, segment_file_dict, file_labels, cluster_colors)

        if cluster_centers is not None:
            self._plot_centroid_trajectories_static(ax, segment_file_dict, cluster_centers,
                                                    n_clusters, cluster_colors, file_labels)

        label = f'_{k_label}' if k_label is not None else ''
        return f'{head_name}_3d_traj_c{label}.jpg'

    @staticmethod
    def _plot_cluster_trajectories(ax, segment_file_dict, file_labels, cluster_colors):
        """Plot individual cluster trajectories"""
        clusters_added = set()

        for file_idx, (original_idx, data) in enumerate(segment_file_dict['files'].items()):
            frequencies = segment_file_dict['frequencies']
            real_parts = data['real']
            imag_parts = data['imaginary']

            cluster_id = file_labels[file_idx]
            color = cluster_colors[cluster_id]

            label = f'Cluster {cluster_id}' if cluster_id not in clusters_added else None
            if cluster_id not in clusters_added:
                clusters_added.add(cluster_id)

            ax.plot(real_parts, imag_parts, frequencies,
                color=color, alpha=0.7, linewidth=1, label=label)

        return clusters_added

    @staticmethod
    def _plot_centroid_trajectories_static(ax, segment_file_dict, cluster_centers,
                                        n_clusters, cluster_colors, file_labels=None):
        """Plot centroid trajectories on static plot"""
        frequencies = segment_file_dict['frequencies']
        cluster_file_counts = None
        if file_labels is not None:
            file_labels_arr = np.asarray(file_labels)
            cluster_file_counts = [int(np.sum(file_labels_arr == cid)) for cid in range(n_clusters)]

        for cluster_id in range(n_clusters):
            is_empty = cluster_file_counts is not None and cluster_file_counts[cluster_id] == 0
            centroid_real = [] if is_empty else cluster_centers[cluster_id, :, 0]
            centroid_imag = [] if is_empty else cluster_centers[cluster_id, :, 1]
            centroid_freq = [] if is_empty else frequencies

            ax.plot(centroid_real, centroid_imag, centroid_freq,
                color=cluster_colors[cluster_id], linewidth=3, linestyle='--',
                alpha=0.9, label=f'Centroid {cluster_id}')

    def _plot_original_3d(self, ax, segment_file_dict, head_name):
        """Plot original 3D trajectories without clustering"""
        n_files = len(segment_file_dict['files'])
        file_colors = self.generate_colour.generate_distinct_colors(n_files)

        for file_idx, (original_idx, data) in enumerate(segment_file_dict['files'].items()):
            frequencies = segment_file_dict['frequencies']
            real_parts = data['real']
            imag_parts = data['imaginary']
            color = file_colors[file_idx]

            ax.plot(real_parts, imag_parts, frequencies,
                color=color, alpha=0.8, linewidth=1)

        return f'{head_name}_3d_traj_o.jpg'

    @staticmethod
    def _finalize_3d_plot(ax, segment_file_dict, segment_name, segment_dir,
                        plot_name, title_suffix, file_labels):
        """Finalize and save 3D plot"""
        ax.set_xlabel(REAL_LABEL, fontsize=12)
        ax.set_ylabel(IMAGINARY_LABEL, fontsize=12)
        ax.set_zlabel(FREQUENCY_HZ, fontsize=12, labelpad=20)
        ax.zaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x} Hz'))

        frequencies = segment_file_dict['frequencies']
        if frequencies is not None and len(frequencies) > 0:
            freq_min, freq_max = min(frequencies), max(frequencies)
            ax.set_zlim(freq_min, freq_max)

        ax.set_title(f'3D Frequency Response Trajectories - {title_suffix}\nSegment: {segment_name}', fontsize=14)

        if file_labels is not None and len(np.unique(file_labels)) <= 20:
            ax.legend(bbox_to_anchor=(1.05, 1), loc=LEGEND_POS)

        save_path = os.path.join(segment_dir, plot_name)
        plt.savefig(save_path, dpi=100, bbox_inches='tight', pad_inches=0.4)
        plt.close('all')

    def create_3d_centroids_only(self, cluster_centers_denormalized, frequencies, k,
                                 cluster_colors, segment_name, k_dir, head_name, k_label=None,
                                 file_labels=None):
        """Create 3D visualization showing only cluster centroids"""
        fig = plt.figure(figsize=(12, 9))
        ax = fig.add_subplot(111, projection='3d')
        ax.view_init(elev=20, azim=30)

        cluster_file_counts = None
        if file_labels is not None:
            file_labels_arr = np.asarray(file_labels)
            cluster_file_counts = [int(np.sum(file_labels_arr == cid)) for cid in range(k)]

        # Plot each centroid trajectory
        for cluster_id in range(k):
            is_empty = cluster_file_counts is not None and cluster_file_counts[cluster_id] == 0
            centroid_real = [] if is_empty else cluster_centers_denormalized[cluster_id, :, 0]
            centroid_imag = [] if is_empty else cluster_centers_denormalized[cluster_id, :, 1]
            centroid_freq = [] if is_empty else frequencies

            ax.plot(centroid_real, centroid_imag, centroid_freq,
                   color=cluster_colors[cluster_id], linewidth=4,
                   alpha=0.9, label=f'Centroid {cluster_id}')

        ax.set_xlabel(REAL_LABEL, fontsize=12)
        ax.set_ylabel(IMAGINARY_LABEL, fontsize=12)
        ax.set_zlabel(FREQUENCY_HZ, fontsize=12, labelpad=20)
        ax.zaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x} Hz'))

        # Set z-axis limits based on frequency range
        if frequencies is not None and len(frequencies) > 0:
            freq_min, freq_max = min(frequencies), max(frequencies)
            ax.set_zlim(freq_min, freq_max)

        ax.set_title(f'3D Centroid Trajectories\nSegment: {segment_name}, k={k}', fontsize=14)
        ax.legend(bbox_to_anchor=(1.05, 1), loc=LEGEND_POS)

        label = k_label if k_label is not None else f'k{k}'
        plot_name = f'{head_name}_3d_cen_{label}.jpg'
        save_path = os.path.join(k_dir, plot_name)
        plt.savefig(save_path, dpi=100, bbox_inches='tight', pad_inches=0.4)
        plt.close('all')

        self.logger.info(f"      Generated 3D centroids-only plot: {plot_name}")


class PlotSegmentOverviewVisualizer(object):
    """Handles segment overview analysis plots"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.convex_hull_calc = ConvexHullCalculator()
        self.sigma_fan_arc = FanSegmentCalculator()
        self.curve_processor = CurveProcessor()

    def create_segment_overview_analysis(self, segment_file_dict, segment_name, segment_dir, head_name):
        """Create segment overview analysis plot"""
        all_real, all_imag, all_gain, all_phase = [], [], [], []
        for data in segment_file_dict['files'].values():
            all_real.extend(data['real'])
            all_imag.extend(data['imaginary'])
            all_gain.extend(data['gain'])
            all_phase.extend(data['phase'])

        all_real, all_imag = np.array(all_real), np.array(all_imag)
        all_gain, all_phase = np.array(all_gain), np.array(all_phase)

        fig, ax = plt.subplots(figsize=(14, 10))

        # Plot raw data points
        ax.scatter(all_real, all_imag, c='lightblue', alpha=0.6, s=20,
                   label=f'All Data Points ({len(all_real)})', edgecolors='navy', linewidth=0.3)

        # Convex hull
        hull_x, hull_y, hull_area, coverage_stats = self.convex_hull_calc.calculate_convex_hull(all_real, all_imag)

        if hull_area is None:
            # Convex hull creation failed - clean up and return failure
            plt.close('all')
            self.logger.warning(f"  SEGMENT REJECTED: Cannot create convex hull for segment overview - {segment_name}")
            self.logger.warning(f"  All data points may be identical or collinear")
            return False

        ax.plot(hull_x, hull_y, 'k--', linewidth=3, label='Convex Hull')
        ax.fill(hull_x, hull_y, color='yellow', alpha=0.2, label='Convex Hull Area')
        hull_polygon = Polygon(np.column_stack([hull_x[:-1], hull_y[:-1]]))

        # --- Fan segment analysis ---
        coverage_rate = 0.0
        try:
            avg_real, avg_imag, outer_real, outer_imag, inner_real, \
            inner_imag, fan_coords = self.sigma_fan_arc.calculate_3sigma_fan_arc(all_gain, all_phase)

            fan_polygon = Polygon(fan_coords)
            if not fan_polygon.is_valid:
                fan_polygon = fan_polygon.buffer(0)

            # Draw arcs
            ax.plot(outer_real, outer_imag, 'r-', linewidth=3, alpha=0.8, label='3sigma Fan Segment (Outer)')
            ax.plot(inner_real, inner_imag, 'r-', linewidth=3, alpha=0.8, label='3sigma Fan Segment (Inner)')
            ax.plot([outer_real[0], inner_real[0]], [outer_imag[0], inner_imag[0]], 'r-', linewidth=3, alpha=0.8)
            ax.plot([outer_real[-1], inner_real[-1]], [outer_imag[-1], inner_imag[-1]], 'r-', linewidth=3, alpha=0.8)

            # Fill fan polygon
            if fan_polygon.is_valid and not fan_polygon.is_empty:
                x, y = fan_polygon.exterior.xy
                ax.fill(x, y, color='red', alpha=0.2, label='Fan Segment Area')

                # Intersection with hull
                intersection = hull_polygon.intersection(fan_polygon)
                if not intersection.is_empty:
                    if hasattr(intersection, 'exterior'):
                        x, y = intersection.exterior.xy
                        ax.fill(x, y, color='green', alpha=0.4, label='Intersection Area')
                    coverage_rate = intersection.area / fan_polygon.area if fan_polygon.area > 0 else 0

            # Average point
            ax.scatter([avg_real], [avg_imag], c='red', s=100, marker='x', linewidth=3, label='Average Point', zorder=5)

        except Exception as e:
            self.logger.info(f"Fan segment analysis failed: {e}")
            coverage_rate = 0.0

        # Labels and save
        ax.set_xlabel(REAL_LABEL, fontsize=12)
        ax.set_ylabel(IMAGINARY_LABEL, fontsize=12)
        ax.set_title(
            f'Segment Overview Analysis\n{segment_name}\nMean Coverage Rate: {coverage_rate:.3f}, \
s Coverage Rate: {coverage_stats["data_spread"]:.3f}',
            fontsize=14
        )
        ax.grid(True, alpha=0.3)
        ax.legend(bbox_to_anchor=(1.05, 1), loc=LEGEND_POS)
        ax.set_aspect('equal')

        save_path = os.path.join(segment_dir, f'{head_name}_segment_overview.jpg')
        plt.tight_layout()
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close('all')
        self.logger.info(f"  Segment statistical overview saved: {head_name}_segment_overview.jpg")

        return True

    @staticmethod
    def _split_files_by_source(segment_file_dict):
        """Split segment files into (data_dir files, worst-model files) using is_worst_model"""
        real_files, worst_files = [], []
        for data in segment_file_dict['files'].values():
            if data.get('is_worst_model', False):
                worst_files.append(data)
            else:
                real_files.append(data)
        return real_files, worst_files

    @staticmethod
    def _build_overview_row_specs(real_files, worst_files):
        """Build the per-row plotting specs: 1 row (data_dir only) when no worst-model
        files exist, otherwise 3 rows (data_dir / worst model / combined)."""
        real_group = (real_files, 'tab:blue', 'Data dir')
        if not worst_files:
            return [([real_group], '')]
        worst_group = (worst_files, 'tab:red', 'Worst model')
        return [
            ([real_group], ' (Data dir)'),
            ([worst_group], ' (Worst model)'),
            ([real_group, worst_group], ' (Combined)'),
        ]

    def _plot_raw_and_normdet_row(self, ax_raw, ax_norm, freqs, file_groups, title_suffix):
        """Plot one row: raw phase (left) and normalized-to-[-1,1]-then-detrended phase
        (right) for every file in each (files, color, label) group."""
        for files, color, label in file_groups:
            first = True
            for data in files:
                phase = np.asarray(data['phase'])
                normdet = self.curve_processor.detrend_curve(
                    self.curve_processor.normalize_curve_to_range(phase), freqs
                )
                ax_raw.plot(freqs, phase, color=color, alpha=0.5, linewidth=0.8,
                            label=label if first else None)
                ax_norm.plot(freqs, normdet, color=color, alpha=0.5, linewidth=0.8,
                             label=label if first else None)
                first = False

        ax_raw.set_title(f'Raw Phase vs Frequency{title_suffix}', fontsize=12)
        ax_raw.set_xlabel(FREQUENCY_HZ)
        ax_raw.set_ylabel('Phase (deg)')
        ax_raw.grid(True, alpha=0.3)
        ax_raw.legend(loc=UPPER_RIGHT, fontsize=8)

        ax_norm.set_title(f'Normalized [-1, 1] + Detrended Phase vs Frequency{title_suffix}', fontsize=12)
        ax_norm.set_xlabel(FREQUENCY_HZ)
        ax_norm.set_ylabel('Normalized + Detrended Phase')
        ax_norm.grid(True, alpha=0.3)
        ax_norm.legend(loc=UPPER_RIGHT, fontsize=8)

    def create_normalization_detrend_overview(self, segment_file_dict, segment_name, segment_dir, head_name):
        """Raw vs normalized+detrended phase overview"""
        freqs = np.asarray(segment_file_dict['frequencies'])
        real_files, worst_files = self._split_files_by_source(segment_file_dict)
        row_specs = self._build_overview_row_specs(real_files, worst_files)

        n_rows = len(row_specs)
        fig, axes = plt.subplots(n_rows, 2, figsize=(16, 6 * n_rows), squeeze=False)

        for row_idx, (file_groups, title_suffix) in enumerate(row_specs):
            self._plot_raw_and_normdet_row(
                axes[row_idx, 0], axes[row_idx, 1], freqs, file_groups, title_suffix
            )

        fig.suptitle(f'Segment {segment_name} - Raw vs Normalized+Detrended Phase', fontsize=14, fontweight='bold')
        plt.tight_layout(rect=[0, 0, 1, 0.96], h_pad=2.5, w_pad=2.0)

        save_path = os.path.join(segment_dir, f'{head_name}_normalization_detrend_overview.jpg')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close('all')
        self.logger.info(
            f"  Normalization+detrend overview saved: {head_name}_normalization_detrend_overview.jpg")

        return True

    @staticmethod
    def _group_file_records(segment_file_dict, original_indices):
        """Return the file-data dicts for a list of original file indices."""
        return [segment_file_dict['files'][idx] for idx in original_indices]

    def _plot_baseline_curves(self, ax_raw, ax_norm, freqs, files, color):
        """Plot raw and normalized[-1,1]+detrended phase curves for one file list,
        dashing any worst-model file so it stays visually distinct from data_dir files."""
        for data in files:
            phase = np.asarray(data['phase'])
            normdet = self.curve_processor.detrend_curve(
                self.curve_processor.normalize_curve_to_range(phase), freqs
            )
            linestyle = '--' if data.get('is_worst_model', False) else '-'
            ax_raw.plot(freqs, phase, color=color, alpha=0.45, linewidth=0.8, linestyle=linestyle)
            ax_norm.plot(freqs, normdet, color=color, alpha=0.45, linewidth=0.8, linestyle=linestyle)

    @staticmethod
    def _format_baseline_axis(axis, title, ylabel, show_band, less_resonance_band):
        """Apply title, labels and grid to one baseline-separation axis; the normalized+
        detrended row also gets the 0 and +/-less_resonance_band division lines around
        the x-axis that the group split is decided on."""
        axis.set_title(title, fontsize=11)
        axis.set_xlabel(FREQUENCY_HZ)
        axis.set_ylabel(ylabel)
        axis.grid(True, alpha=0.3)
        if show_band:
            axis.axhline(0.0, color='black', linewidth=1.0)
            axis.axhline(less_resonance_band, color='black', linewidth=0.8, linestyle=':')
            axis.axhline(-less_resonance_band, color='black', linewidth=0.8, linestyle=':')

    def _plot_baseline_group_column(self, axes_column, files, freqs, color, title, less_resonance_band):
        """Plot the raw and normalized+detrended rows for a single baseline group column."""
        self._plot_baseline_curves(axes_column[0], axes_column[1], freqs, files, color)
        self._format_baseline_axis(axes_column[0], f'Raw - {title}', PHASE_LABEL, False, less_resonance_band)
        self._format_baseline_axis(axes_column[1], f'Norm + Detrend - {title}',
                                   NORMDET_PHASE_LABEL, True, less_resonance_band)

    def _plot_baseline_combined_column(self, axes_column, segment_file_dict, classified, freqs,
                                       less_resonance_band):
        """Plot all baseline groups overlaid in the final column, with a count legend."""
        for group in BASELINE_GROUP_ORDER:
            files = self._group_file_records(segment_file_dict, classified[group])
            self._plot_baseline_curves(axes_column[0], axes_column[1], freqs, files,
                                       BASELINE_GROUP_COLORS[group])

        total = sum(len(classified[group]) for group in BASELINE_GROUP_ORDER)
        self._format_baseline_axis(axes_column[0], f'Raw - All Groups (n={total})',
                                   PHASE_LABEL, False, less_resonance_band)
        self._format_baseline_axis(axes_column[1], f'Norm + Detrend - All Groups (n={total})',
                                   NORMDET_PHASE_LABEL, True, less_resonance_band)

        handles = [mlines.Line2D([0], [0], color=BASELINE_GROUP_COLORS[group], linewidth=1.5,
                                 label=f'{BASELINE_GROUP_TITLES[group]} ({len(classified[group])})')
                  for group in BASELINE_GROUP_ORDER]
        axes_column[0].legend(handles=handles, loc=UPPER_RIGHT, fontsize=8)
        axes_column[1].legend(handles=handles, loc=UPPER_RIGHT, fontsize=8)

    def create_baseline_group_separation_plot(self, segment_file_dict, classified, segment_name,
                                              segment_dir, head_name, less_resonance_band):
        """2x4 grid of raw and normalized[-1,1]+detrended phase curves showing the
        phase_lead/phase_lag/no_resonance baseline group split"""
        freqs = np.asarray(segment_file_dict['frequencies'])
        fig, axes = plt.subplots(2, 4, figsize=(26, 11))

        for col_idx, group in enumerate(BASELINE_GROUP_ORDER):
            files = self._group_file_records(segment_file_dict, classified[group])
            self._plot_baseline_group_column(
                axes[:, col_idx], files, freqs, BASELINE_GROUP_COLORS[group],
                f'{BASELINE_GROUP_TITLES[group]} (n={len(files)})', less_resonance_band
            )
        self._plot_baseline_combined_column(axes[:, 3], segment_file_dict, classified, freqs,
                                            less_resonance_band)

        fig.suptitle(
            f'Segment {segment_name} - Baseline Group Separation '
            f'(no-resonance band +/-{less_resonance_band})',
            fontsize=14, fontweight='bold')

        plt.tight_layout(rect=[0, 0, 1, 0.96], h_pad=2.5, w_pad=2.0)

        filename = f'{head_name}_baseline_group_separation.jpg'
        save_path = os.path.join(segment_dir, filename)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close('all')
        self.logger.info(f"  Baseline group separation plot saved: {filename}")

        return True


class Plot2DVisualizer(object):
    """Handles 2D frequency plots"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.generate_colour = ColorGenerator()

    def create_2d_frequency_plot(self, real_array, imag_array, labels, k, frequency,
                                 segment_name, k_dir, head_name, cluster_colors=None, centroids=None,
                                 k_label=None):
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
        label = k_label if k_label is not None else f'k{k}'
        save_path = os.path.join(k_dir, f'{head_name}_2d_freq_{freq_str}Hz_{label}.jpg')
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
                                        k, frequency, segment_name, k_dir, head_name, cluster_colors=None,
                                        k_label=None):
        """Create visualization showing fan segments, convex hull, and union"""
        fig, ax = plt.subplots(figsize=(14, 10))

        if cluster_colors is None:
            cluster_colors = self.generate_colour.generate_distinct_colors(k)

        self._plot_convex_hull(ax, real_array, imag_array)
        cluster_polygons = self._plot_cluster_fan_segments(ax, real_array, imag_array, gain_array,
                                                            phase_array, labels, k, cluster_colors)
        self._plot_union_polygon(ax, cluster_polygons)
        self._finalize_fan_plot(ax, frequency, segment_name, k, k_dir, head_name, k_label)

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
    def _finalize_fan_plot(ax, frequency, segment_name, k, k_dir, head_name, k_label=None):
        """Finalize and save fan segment plot"""
        ax.set_xlabel(REAL_LABEL, fontsize=12)
        ax.set_ylabel(IMAGINARY_LABEL, fontsize=12)
        ax.set_title(f'Fan Segments: {frequency:.2f} Hz\nSegment: {segment_name}, k={k}', fontsize=14)
        ax.grid(True, alpha=0.3)
        ax.legend(bbox_to_anchor=(1.05, 1), loc=LEGEND_POS)
        ax.set_aspect('equal')

        plt.tight_layout()
        freq_str = f"{frequency:.2f}".replace('.', '_')
        label = k_label if k_label is not None else f'k{k}'
        save_path = os.path.join(k_dir, f'{head_name}_fan_segments_{freq_str}Hz_{label}.jpg')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close('all')


class PlotMetricsVisualizer(object):
    """Handles ACI metrics visualization plots"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def plot_aci_scores_vs_k(self, segment_aci_scores, segment_name, output_dir, k1_baseline,
                            optimal_k_aci1=None, optimal_k_aci2=None, optimal_k_aci3=None, optimal_k_aci4=None,
                            metrics_to_use=['ACI1', 'ACI2', 'ACI3', 'ACI4'], head_name=None):
        """Plot ACI scores vs k"""
        try:
            ks = sorted([k for k in segment_aci_scores.keys() if isinstance(k, int) and k > 1])

            if len(ks) == 0:
                self.logger.info(f"Warning: No k>1 values to plot for {segment_name}")
                return

            plt.figure(figsize=(10, 6))

            colors = self._get_metric_colors()

            self._plot_aci_values(segment_aci_scores, ks, metrics_to_use, colors)
            self._plot_baselines(k1_baseline, metrics_to_use, colors)
            self._plot_optimal_k_points(segment_aci_scores, metrics_to_use, colors,
                                        optimal_k_aci1, optimal_k_aci2, optimal_k_aci3, optimal_k_aci4)

            self._finalize_aci_plot(ks, segment_name, output_dir, head_name)

        except Exception as e:
            self.logger.info(f"Warning: Failed to plot ACI vs k for {segment_name}: {e}")
            traceback.print_exc()

    @staticmethod
    def _get_metric_colors():
        """Get color mapping for metrics"""
        return {
            'ACI1': '#1f77b4',
            'ACI2': '#ff7f0e',
            'ACI3': '#2ca02c',
            'ACI4': '#d62728'
        }

    @staticmethod
    def _plot_aci_values(segment_aci_scores, ks, metrics_to_use, colors):
        """Plot ACI score lines for all metrics"""
        metric_keys = {
            'ACI1': 'avg_aci1',
            'ACI2': 'avg_aci2',
            'ACI3': 'avg_aci3',
            'ACI4': 'avg_aci4'
        }

        for metric in metrics_to_use:
            if metric in metric_keys:
                values = [segment_aci_scores[k].get(metric_keys[metric], np.nan) for k in ks]
                plt.plot(ks, values, '-o', label=metric, linewidth=2, markersize=8, color=colors[metric])

    @staticmethod
    def _plot_baselines(k1_baseline, metrics_to_use, colors):
        """Plot baseline horizontal lines for all metrics"""
        if not k1_baseline:
            return

        baseline_keys = {
            'ACI1': 'aci1_score',
            'ACI2': 'aci2_score',
            'ACI3': 'aci3_score',
            'ACI4': 'aci4_score'
        }

        for metric in metrics_to_use:
            if metric in baseline_keys:
                baseline_value = k1_baseline.get(baseline_keys[metric], np.nan)
                if not np.isnan(baseline_value):
                    plt.axhline(y=baseline_value, color=colors[metric], linestyle='--',
                            linewidth=2, alpha=0.6, label=f'Baseline (k=1) {metric}')

    def _plot_optimal_k_points(self, segment_aci_scores, metrics_to_use, colors,
                            optimal_k_aci1, optimal_k_aci2, optimal_k_aci3, optimal_k_aci4):
        """Plot optimal k points for all metrics"""
        optimal_k_map = {
            'ACI1': (optimal_k_aci1, 'avg_aci1'),
            'ACI2': (optimal_k_aci2, 'avg_aci2'),
            'ACI3': (optimal_k_aci3, 'avg_aci3'),
            'ACI4': (optimal_k_aci4, 'avg_aci4')
        }
        markers = {'ACI1': 'D', 'ACI2': 's', 'ACI3': '^', 'ACI4': 'v'}
        for metric in metrics_to_use:
            if metric in optimal_k_map:
                optimal_k, score_key = optimal_k_map[metric]
                self._plot_single_optimal_point(segment_aci_scores, metric, optimal_k,
                                            score_key, colors[metric], markers[metric])

    @staticmethod
    def _plot_single_optimal_point(segment_aci_scores, metric, optimal_k,
                                score_key, color, marker):
        """Plot a single optimal k point"""
        if optimal_k is None or optimal_k == 1:
            return
        if optimal_k not in segment_aci_scores:
            return

        optimal_score = segment_aci_scores[optimal_k].get(score_key, np.nan)
        if np.isnan(optimal_score):
            return
        plt.scatter(optimal_k, optimal_score,
                color=color, s=100, marker=marker,
                edgecolors='black', linewidths=2,
                label=f'Optimal k ({metric}) = {optimal_k}', zorder=5)

    def _finalize_aci_plot(self, ks, segment_name, output_dir, head_name):
        """Finalize and save ACI vs k plot"""
        plt.xlabel("k (Number of Clusters)", fontsize=12)
        plt.ylabel("Average Cluster Index (ACI)", fontsize=12)
        plt.title(f"ACI Scores vs k - {segment_name}", fontsize=14)
        plt.xticks(ks)
        plt.legend(loc='best', fontsize=10)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        os.makedirs(output_dir, exist_ok=True)
        plot_path = os.path.join(output_dir, f"{head_name}_aci_scores_vs_k_{segment_name}.jpg")
        plt.savefig(plot_path, bbox_inches='tight', dpi=150)
        plt.close('all')

        self.logger.info(f"  Saved ACI vs k plot: {plot_path}")
