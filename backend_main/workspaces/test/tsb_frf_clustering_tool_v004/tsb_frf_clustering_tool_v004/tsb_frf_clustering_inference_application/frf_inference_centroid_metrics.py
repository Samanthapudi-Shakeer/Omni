# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_centroid_metrics.py
*  File Description: Centroid-based pairwise metrics (Correlation, RMSE, Wasserstein)
*                    for FRF clustering inference evaluation.
*  All rights reserved.
*
*********************************************************************/
"""

import numpy as np
import logging
from scipy.stats import spearmanr, wasserstein_distance
from frf_inference_metric_components import CurveProcessor


CENTROID_METRIC_NAMES = frozenset({'Correlation', 'RMSE', 'Wasserstein'})

AVG_SCORE_KEYS = {
    'Correlation': 'avg_correlation',
    'RMSE':        'avg_rmse',
    'Wasserstein': 'avg_wasserstein',
}

_METRIC_ORDER = ('Correlation', 'RMSE', 'Wasserstein')


class CentroidMetricsCalculator(object):
    """Computes pairwise centroid metrics (Correlation, RMSE, Wasserstein) on centroid phase curves.

    All three metrics operate on phase data derived from cluster_means via
    arctan2(imag, real), consistent with the training application's pipeline
    (frf_centroid_metrics.py::CentroidMetricsCalculator) so inference-time scores
    are computed identically to training.

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
        """Return per-centroid phase curves after [-1, 1] normalization and linear detrend."""
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
