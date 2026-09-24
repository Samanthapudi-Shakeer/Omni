# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_centroid_metrics.py
*  File Description: Centroid-based pairwise metrics (Correlation,
*                    RMSE, DTW) for FRF clustering evaluation and
*                    Heatmap and elbow visualisations for centroid-based
*                    pairwise metrics (Correlation, RMSE, DTW).
*  All rights reserved.
*
*********************************************************************/
"""

import os
import copy
import numpy as np
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import spearmanr, wasserstein_distance
from kneed import KneeLocator
from frf_metric_components import CurveProcessor


CENTROID_METRIC_NAMES = frozenset({'Correlation', 'RMSE', 'Wasserstein'})

_ELBOW_PARAMS = {
    'Correlation': {'curve': 'convex', 'direction': 'decreasing'},
    'RMSE':        {'curve': 'concave', 'direction': 'increasing'},
    'Wasserstein': {'curve': 'concave', 'direction': 'increasing'},
}

AVG_SCORE_KEYS = {
    'Correlation': 'avg_correlation',
    'RMSE':        'avg_rmse',
    'Wasserstein': 'avg_wasserstein',
}

OPT_KEYS = {
    'Correlation': 'correlation',
    'RMSE':        'rmse',
    'Wasserstein': 'wasserstein',
}

_METRIC_ORDER = ('Correlation', 'RMSE', 'Wasserstein')

_METRIC_ORDER = ('Correlation', 'RMSE', 'Wasserstein')

_METRIC_POSITIONS = {
    'Correlation': (0, 0),
    'RMSE':        (0, 1),
    'Wasserstein': (1, 0),
}

_LEGEND_POSITION = (1, 1)

_METRIC_CMAPS = {
    'Correlation': 'RdYlGn_r',
    'RMSE':        'RdYlGn',
    'Wasserstein': 'RdYlGn',
}

_METRIC_LABELS = {
    'Correlation': 'Spearman Correlation\n(lower is better)',
    'RMSE':        'Phase RMSE\n(higher is better)',
    'Wasserstein': 'Wasserstein Distance\n(higher is better)',
}

_SCORE_KEYS = {
    'Correlation': 'avg_correlation',
    'RMSE':        'avg_rmse',
    'Wasserstein': 'avg_wasserstein',
}

_OPT_KEYS = {
    'Correlation': 'correlation',
    'RMSE':        'rmse',
    'Wasserstein': 'wasserstein',
}


class CentroidMetricPlotter(object):
    """Generates heatmap and elbow visualisations for centroid pairwise metrics.

    Two outputs are produced per segment:
    - Per-k heatmap grid  : 2x2 subplot image (3 lower-triangle heatmaps + legend cell).
                            Generated in-loop immediately after each k is processed.
    - Post-loop elbow grid: 2x2 subplot image (3 elbow curves, 1 unused cell).
                            Generated once after all k values have been processed.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _compute_heatmap_layout(k):
        """Compute dynamic figure size and annotation parameters for a kxk heatmap grid.

        Guarantees each cell occupies at least 75 pixels at the save DPI (150 dpi),
        so text annotations never overlap regardless of cluster count.

        Returns:
            figsize:      (width, height) in inches
            ann_font:     annotation font size in points  (4 - 9)
            num_decimals: decimal places for cell values  (1 - 3)
            tick_font:    axis tick-label font size       (5 - 9)
        """
        _min_cell_px = 75
        _save_dpi = 150
        _min_subplot_in = 7.0

        # Subplot must be large enough so every cell is ≥ _min_cell_px pixels
        needed_inches = (k * _min_cell_px) / _save_dpi
        subplot_size = max(_min_subplot_in, needed_inches)
        figsize = (subplot_size * 2.0 + 2.0, subplot_size * 2.0 + 1.5)

        # Annotation font: proportional to actual cell pixel size, clamped 4 - 9
        cell_px = (subplot_size * _save_dpi) / k
        ann_font = max(4, min(9, int(cell_px * 0.7 / 10)))

        # Fewer decimal places for smaller cells to reduce character count
        if ann_font >= 7:
            num_decimals = 3
        elif ann_font >= 5:
            num_decimals = 2
        else:
            num_decimals = 1

        tick_font = max(5, ann_font)
        return figsize, ann_font, num_decimals, tick_font

    def plot_centroid_heatmaps(self, pairwise_matrices, k, segment_name,
                               output_dir, head_name, metrics_to_use, k_label=None,
                               cluster_labels=None):
        """Generate and save a 2x2 heatmap grid for centroid pairwise metrics at one k value.

        Args:
            pairwise_matrices: {metric_name: np.ndarray (k, k)} from CentroidMetricsCalculator
            k:                 number of clusters (used in fallback label)
            segment_name:      frequency segment identifier
            output_dir:        destination directory (metric_results/)
            head_name:         head identifier prefix for the filename
            metrics_to_use:    list of metric name strings from config
            k_label:           optional label string, e.g. 'k3' or 'stage1k2_stage2k3'
            cluster_labels:    optional list of descriptive strings for each centroid,
                               e.g. ['Cluster 0', ...] or ['Parent 0, Sub 0', ...]
        """
        active = [m for m in _METRIC_ORDER if m in metrics_to_use and m in pairwise_matrices]
        if not active:
            return

        figsize, ann_font, num_decimals, tick_font = self._compute_heatmap_layout(k)
        fig, axes = plt.subplots(2, 2, squeeze=False, figsize=figsize)
        for metric in active:
            row, col = _METRIC_POSITIONS[metric]
            self._plot_single_heatmap(axes[row, col], pairwise_matrices[metric], metric,
                                       ann_font, num_decimals, tick_font)

        self._turn_off_unused_cells(axes, active, _LEGEND_POSITION)
        legend_row, legend_col = _LEGEND_POSITION
        if cluster_labels:
            self._render_legend_cell(axes[legend_row, legend_col], cluster_labels)
        else:
            axes[legend_row, legend_col].axis('off')

        label = k_label or f'k{k}'
        fig.suptitle(f'Centroid Pairwise Metrics — {segment_name} ({label})', fontsize=13)
        plt.tight_layout()
        self._save_figure(fig, output_dir,
                          f'{head_name}_cen_heatmap_{label}.jpg')

    def plot_elbow_curves(self, centroid_scores, opt_dict, segment_name,
                          output_dir, head_name, metrics_to_use,
                          k_label=None, x_label='k (Number of Clusters)'):
        """Generate and save a 2x2 elbow curve grid for centroid metrics.

        Args:
            centroid_scores: {k: {avg_correlation: float, avg_rmse: float, avg_dtw: float}}
            opt_dict:        {opt_key: optimal_k} from CentroidMetricsCalculator.select_optimal_k
            segment_name:    frequency segment identifier
            output_dir:      destination directory (metric_results/)
            head_name:       head identifier prefix for the filename
            metrics_to_use:  list of metric name strings from config
            k_label:         optional label for hierarchical stage1_k, e.g. 'stage1k2'
            x_label:         x-axis label; pass 'Total Clusters' for hierarchical mode
        """
        active = [m for m in _METRIC_ORDER if m in metrics_to_use]
        k_values = sorted(k for k in centroid_scores if isinstance(k, int))
        if not active or not k_values:
            return

        fig, axes = plt.subplots(2, 2, squeeze=False, figsize=(14, 10))
        for metric in active:
            row, col = _METRIC_POSITIONS[metric]
            scores = [centroid_scores[k].get(_SCORE_KEYS[metric], np.nan) for k in k_values]
            opt_k = opt_dict.get(_OPT_KEYS[metric])
            self._plot_single_elbow(axes[row, col], k_values, scores, opt_k, metric, x_label)

        self._turn_off_unused_cells(axes, active)

        suffix = f'_{k_label}' if k_label else ''
        fig.suptitle(f'Centroid Metric Elbow Curves — {segment_name}', fontsize=13)
        plt.tight_layout()
        self._save_figure(fig, output_dir,
                          f'{head_name}_cen_elbow{suffix}.jpg')

    def plot_convergence_curve(self, deviations, k_merged, original_k, segment_name,
                                output_dir, head_name):
        """Plot forward-pass iteration number (x-axis) against file-reassignment
        deviation count (y-axis) for the post-merge convergence loop.

        Args:
            deviations:   list of int, one per forward pass — files reassigned vs.
                          the previous pass
            k_merged:     surviving cluster count after merging
            original_k:   pre-merge cluster count, included in the filename so
                          repeated merge events for different original k values
                          don't collide
            segment_name: frequency segment identifier
            output_dir:   destination directory (k_dir)
            head_name:    head identifier prefix for the filename
        """
        iterations = list(range(1, len(deviations) + 1))
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(iterations, deviations, marker='o', linewidth=2, color='tab:blue')
        ax.set_xlabel('Forward Pass Iteration')
        ax.set_ylabel('Drives Reassigned (vs. previous pass)')
        ax.set_title(
            f'Post-Merge Convergence — Segment: {segment_name}, '
            f'k={original_k} → merged k={k_merged}'
        )
        ax.grid(True, alpha=0.3)
        self._save_figure(
            fig, output_dir,
            f'{head_name}_merge_convergence_origk{original_k}_k{k_merged}.jpg'
        )

    def _plot_single_heatmap(self, ax, matrix, metric,
                              ann_font=8, num_decimals=3, tick_font=9):
        """Plot one lower-triangle heatmap on the given axes."""
        masked = self._mask_upper_triangle(matrix)
        cmap = copy.copy(getattr(plt.cm, _METRIC_CMAPS[metric]))
        cmap.set_bad(color='white')

        vmin, vmax = self._get_value_range(masked)
        im = ax.imshow(masked, cmap=cmap, vmin=vmin, vmax=vmax, aspect='auto')
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        k = len(matrix)
        self._annotate_lower_triangle(ax, masked, k, ann_font, num_decimals)
        self._format_heatmap_axes(ax, k, _METRIC_LABELS[metric], tick_font)

    @staticmethod
    def _mask_upper_triangle(matrix):
        """Return a copy of matrix with the upper triangle and diagonal set to NaN."""
        masked = matrix.copy().astype(float)
        masked[np.triu_indices_from(masked, k=0)] = np.nan
        return masked

    @staticmethod
    def _get_value_range(masked):
        """Return (vmin, vmax) for finite values; falls back to (0, 1) when empty."""
        finite = masked[np.isfinite(masked)]
        if finite.size == 0:
            return 0.0, 1.0
        vmin, vmax = float(np.nanmin(finite)), float(np.nanmax(finite))
        if vmin == vmax:
            vmax = vmin + 1.0
        return vmin, vmax

    @staticmethod
    def _annotate_lower_triangle(ax, masked, k, font_size=8, num_decimals=3):
        """Place numeric annotations in each finite lower-triangle cell."""
        fmt = f'{{:.{num_decimals}f}}'
        for i in range(k):
            for j in range(i):
                val = masked[i, j]
                if np.isfinite(val):
                    ax.text(j, i, fmt.format(val), ha='center', va='center',
                            fontsize=font_size, color='black')

    @staticmethod
    def _format_heatmap_axes(ax, k, title, tick_font=9):
        """Set tick labels and title for a heatmap axes."""
        labels = [f'C{i}' for i in range(k)]
        x_rotation = 90 if k > 10 else 0
        ax.set_xticks(range(k))
        ax.set_yticks(range(k))
        ax.set_xticklabels(labels, fontsize=tick_font,
                            rotation=x_rotation, ha='center')
        ax.set_yticklabels(labels, fontsize=tick_font)
        ax.set_title(title, fontsize=10)

    def _plot_single_elbow(self, ax, k_values, scores, opt_k, metric, x_label):
        """Plot one elbow curve with optimal k highlighted."""
        valid_k = [k for k, s in zip(k_values, scores) if not np.isnan(s)]
        valid_s = [s for k, s in zip(k_values, scores) if not np.isnan(s)]

        if not valid_k:
            ax.text(0.5, 0.5, 'No data available', ha='center', va='center',
                    transform=ax.transAxes, fontsize=10)
            ax.set_title(_METRIC_LABELS[metric], fontsize=10)
            return

        ax.plot(valid_k, valid_s, 'o-', linewidth=2, markersize=6, color='steelblue')
        self._mark_optimal_k(ax, opt_k, valid_k, valid_s)
        self._format_elbow_axes(ax, valid_k, metric, x_label)

    @staticmethod
    def _mark_optimal_k(ax, opt_k, valid_k, valid_s):
        """Mark the elbow-selected optimal k with a gold star and dashed vertical line."""
        if opt_k is None or opt_k not in valid_k:
            return
        idx = valid_k.index(opt_k)
        ax.scatter([opt_k], [valid_s[idx]], s=200, marker='*', color='gold',
                   edgecolors='black', linewidths=1.5, zorder=5,
                   label=f'Elbow k={opt_k}')
        ax.axvline(x=opt_k, color='gray', linestyle='--', alpha=0.6)
        ax.legend(fontsize=9)

    @staticmethod
    def _format_elbow_axes(ax, valid_k, metric, x_label):
        """Format axes labels, ticks, grid, and title for an elbow plot."""
        ax.set_xlabel(x_label, fontsize=10)
        ax.set_ylabel(_METRIC_LABELS[metric].split('\n')[0], fontsize=10)
        ax.set_title(_METRIC_LABELS[metric], fontsize=10)
        ax.set_xticks(valid_k)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def _turn_off_unused_cells(axes, active_metrics, exclude=None):
        """Turn off any grid cell not occupied by an active metric or excluded (e.g. legend cell)."""
        occupied = {_METRIC_POSITIONS[m] for m in active_metrics}
        for row in range(2):
            for col in range(2):
                if (row, col) in occupied or (row, col) == exclude:
                    continue
                axes[row, col].axis('off')

    @staticmethod
    def _render_legend_cell(ax, cluster_labels):
        """Render centroid label mapping as a text legend in the 4th (empty) cell."""
        ax.axis('off')
        font_size = max(6, 10 - max(0, len(cluster_labels) - 6))
        lines = ['Centroid Legend', '─' * 22]
        for i, label in enumerate(cluster_labels):
            lines.append(f'  C{i:<3} →  {label}')
        ax.text(0.05, 0.95, '\n'.join(lines),
                transform=ax.transAxes, fontsize=font_size,
                verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle='round', facecolor='lightyellow',
                          edgecolor='goldenrod', alpha=0.85))

    def _save_figure(self, fig, output_dir, filename):
        """Save figure to output_dir/filename and close all figures."""
        os.makedirs(output_dir, exist_ok=True)
        save_path = os.path.join(output_dir, filename)
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close('all')
        self.logger.info(f'  Saved centroid metric plot: {save_path}')


class CentroidMetricsCalculator(object):
    """Computes pairwise centroid metrics (Correlation, RMSE, Wasserstein) on centroid phase curves.

    All three metrics operate on phase data derived from cluster_means via
    arctan2(imag, real), consistent with the existing Bode plot pipeline.

    Correlation — Spearman on [-1, 1] normalized then linearly detrended phase. Lower is better.
                  Constant centroid pair returns 1.0 (worst-case penalty).
    RMSE        — sqrt(mean((a - b)^2)) on [-1, 1] normalized then linearly detrended phase. Higher is better.
    Wasserstein — Earth-mover's distance on [-1, 1] normalized then linearly detrended phase. Higher is better.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.curve_processor = CurveProcessor()

    def compute_centroid_metrics(self, cluster_means, unique_frequencies, metrics_to_use):
        """Compute mean pairwise scores and full pairwise matrices for one k value.

        Args:
            cluster_means:      np.ndarray (k, n_freq, 2) — [...,0]=real, [...,1]=imag
            unique_frequencies: 1-D array-like of frequency values
            metrics_to_use:     list of metric name strings from config

        Returns:
            avg_scores: dict keyed by avg_correlation / avg_rmse / avg_wasserstein
            matrices:   dict keyed by 'Correlation' / 'RMSE' / 'Wasserstein',
                        each value is np.ndarray (k, k) symmetric, NaN on diagonal
        """
        curves = self.get_detrended_normalized_curves(cluster_means, unique_frequencies)
        return self.compute_matrices_from_curves(curves, metrics_to_use)

    def get_detrended_normalized_curves(self, cluster_means, unique_frequencies):
        """Return per-centroid phase curves after [-1, 1] normalization and linear detrend.

        Shared entry point so any consumer (e.g. the merge module's resonance
        gate) uses the identical preprocessing as the full-segment metrics.
        """
        phase_curves = self._extract_phase_curves(cluster_means)
        freqs = np.asarray(unique_frequencies)
        return [self.curve_processor.detrend_curve(
            self.curve_processor.normalize_curve_to_range(p), freqs) for p in phase_curves]

    @staticmethod
    def _extract_phase_curves(cluster_means):
        """Derive per-centroid phase (degrees) curves from real/imaginary centroid data.

        Args:
            cluster_means: np.ndarray (k, n_freq, 2) -- [...,0]=real, [...,1]=imag

        Returns:
            list of 1-D np.ndarray (length n_freq), one phase-in-degrees curve per centroid
        """
        cluster_means = np.asarray(cluster_means)
        return [np.degrees(np.arctan2(cluster_means[i, :, 1], cluster_means[i, :, 0]))
                for i in range(cluster_means.shape[0])]

    def compute_matrices_from_curves(self, curves, metrics_to_use):
        """Compute mean pairwise scores and full pairwise matrices from already-preprocessed curves.

        Args:
            curves:         list of 1-D detrended+normalized phase arrays (one per centroid)
            metrics_to_use: list of metric name strings from config

        Returns:
            avg_scores, matrices — same shape as compute_centroid_metrics
        """
        active = [m for m in _METRIC_ORDER if m in metrics_to_use and m in CENTROID_METRIC_NAMES]
        if not active or len(curves) < 2:
            return {}, {}

        avg_scores, matrices = {}, {}
        self._run_correlation(curves, active, avg_scores, matrices)
        self._run_rmse(curves, active, avg_scores, matrices)
        self._run_wasserstein(curves, active, avg_scores, matrices)
        return avg_scores, matrices

    def select_optimal_k(self, centroid_scores, metrics_to_use):
        """Detect elbow k per centroid metric from accumulated scores across all k values.

        Args:
            centroid_scores: {k: {avg_correlation: float, avg_rmse: float, avg_wasserstein: float}}
            metrics_to_use:  list of metric name strings from config

        Returns:
            opt_dict: {opt_key: optimal_k}  e.g. {'correlation': 3, 'rmse': 5, 'wasserstein': 4}
        """
        active = [m for m in _METRIC_ORDER if m in metrics_to_use and m in CENTROID_METRIC_NAMES]
        k_values = sorted(k for k in centroid_scores if isinstance(k, int))

        opt_dict = {}
        for metric in active:
            scores = [centroid_scores[k].get(AVG_SCORE_KEYS[metric], np.nan) for k in k_values]
            opt_dict[OPT_KEYS[metric]] = self._detect_elbow(k_values, scores, metric)
        return opt_dict

    def _run_correlation(self, phase_curves, active, avg_scores, matrices):
        """Compute Spearman correlation on normalized and detrended phase curves if active."""
        if 'Correlation' not in active:
            return
        matrix, mean_score = self._build_pairwise_matrix(phase_curves, self._spearman_pair)
        avg_scores[AVG_SCORE_KEYS['Correlation']] = mean_score
        matrices['Correlation'] = matrix

    def _run_rmse(self, phase_curves, active, avg_scores, matrices):
        """Compute RMSE on [-1, 1] normalized then linearly detrended phase curves if active."""
        if 'RMSE' not in active:
            return
        matrix, mean_score = self._build_pairwise_matrix(phase_curves, self._rmse_pair)
        avg_scores[AVG_SCORE_KEYS['RMSE']] = mean_score
        matrices['RMSE'] = matrix

    def _run_wasserstein(self, phase_curves, active, avg_scores, matrices):
        """Compute Wasserstein distance on [-1, 1] normalized then linearly detrended phase curves if active."""
        if 'Wasserstein' not in active:
            return
        matrix, mean_score = self._build_pairwise_matrix(phase_curves, self._wasserstein_pair)
        avg_scores[AVG_SCORE_KEYS['Wasserstein']] = mean_score
        matrices['Wasserstein'] = matrix

    def _build_pairwise_matrix(self, curves, pair_fn):
        """Build symmetric (k x k) pairwise score matrix and compute mean.

        Returns:
            matrix:     np.ndarray (k, k) — symmetric, NaN on diagonal and failed pairs
            mean_score: float mean of all finite off-diagonal lower-triangle values
        """
        k = len(curves)
        matrix = np.full((k, k), np.nan)
        pair_scores = []

        for i in range(k):
            for j in range(i + 1, k):
                score = self._safe_pair(curves[i], curves[j], pair_fn)
                matrix[i, j] = score
                matrix[j, i] = score
                if not np.isnan(score):
                    pair_scores.append(score)

        mean_score = float(np.mean(pair_scores)) if pair_scores else np.nan
        return matrix, mean_score

    @staticmethod
    def _safe_pair(a, b, pair_fn):
        """Call pair_fn(a, b) with NaN/Inf and exception safety."""
        try:
            result = pair_fn(a, b)
            value = float(result)
            return value if np.isfinite(value) else np.nan
        except Exception:
            return np.nan

    @staticmethod
    def _spearman_pair(a, b):
        """Spearman correlation for one centroid pair.

        Returns 1.0 when either curve is constant after normalization and detrending —
        penalises degenerate (passthrough) centroids as maximum similarity.
        Uses result[0] for scipy version compatibility.
        """
        if np.std(a) < 1e-10 or np.std(b) < 1e-10:
            return 1.0
        return float(spearmanr(a, b)[0])

    @staticmethod
    def _rmse_pair(a, b):
        """Phase RMSE: sqrt(mean((a-b)^2)) — normalised by sqrt(n_freq)."""
        return float(np.sqrt(np.mean((a - b) ** 2)))

    @staticmethod
    def _wasserstein_pair(a, b):
        """Wasserstein-1 (earth-mover's) distance between two normalized, detrended phase curves."""
        return float(wasserstein_distance(a, b))

    def _detect_elbow(self, k_values, scores, metric):
        """Find the elbow k from a score curve using KneeLocator.

        Falls back to first k (Correlation) or last k (RMSE) when fewer
        than 2 valid points exist or KneeLocator returns None.
        """
        valid_pairs = [(k, s) for k, s in zip(k_values, scores) if not np.isnan(s)]
        if len(valid_pairs) < 2:
            return self._fallback_k(valid_pairs, k_values, metric)
        ks, ss = zip(*valid_pairs)
        return self._run_kneelocator(list(ks), list(ss), metric)

    def _run_kneelocator(self, ks, ss, metric):
        """Run KneeLocator and return the detected knee or a boundary fallback."""
        params = _ELBOW_PARAMS[metric]
        try:
            kneedle = KneeLocator(ks, ss, **params)
            if kneedle.knee is not None:
                return int(kneedle.knee)
        except Exception as exc:
            self.logger.warning(f'  KneeLocator failed for {metric}: {exc}')
        return int(ks[0]) if params['direction'] == 'decreasing' else int(ks[-1])

    @staticmethod
    def _fallback_k(valid_pairs, k_values, metric):
        """Return boundary k when the score curve has fewer than 2 valid points."""
        if valid_pairs:
            return valid_pairs[0][0]
        if not k_values:
            return 1
        return k_values[0] if _ELBOW_PARAMS[metric]['direction'] == 'decreasing' else k_values[-1]
