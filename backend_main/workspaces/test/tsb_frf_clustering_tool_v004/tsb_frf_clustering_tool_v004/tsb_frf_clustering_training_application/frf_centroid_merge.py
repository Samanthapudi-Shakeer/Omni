# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_centroid_merge.py
*  File Description: Post-clustering merge operation driven by pairwise
*                    centroid metrics (Correlation, RMSE, DTW).
*  All rights reserved.
*
*********************************************************************/
"""

import os
from itertools import combinations
import numpy as np
import logging
from scipy.signal import find_peaks


_METRIC_ORDER = ('Correlation', 'RMSE', 'Wasserstein')
_MIN_SHARED_RESONANCE_BINS = 2
MERGED_GROUPS = 'Merged Groups: '


class MergeResult(object):
    """Bundles outputs of a successful cluster merge operation."""

    def __init__(self, merged_means, merged_labels, k_merged, annotation,
                 merge_groups=None, label_map=None):
        self.merged_means = merged_means
        self.merged_labels = merged_labels
        self.k_merged = k_merged
        self.annotation = annotation
        self.merge_groups = merge_groups or []
        self.label_map = label_map or {}


class _MergedModelStub(object):
    """Lightweight stand-in for a TimeSeriesKMeans model so ModelManager.save_model can
    serialize post-merge cluster centers without needing a real fitted estimator."""

    def __init__(self, cluster_centers, n_clusters, metric, random_state):
        self.cluster_centers_ = cluster_centers
        self.n_clusters = n_clusters
        self.metric = metric
        self.random_state = random_state


class _UnionFind(object):
    """Path-compressed union-find for connected-component detection."""

    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        """Path-halving find."""
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x, y):
        """Union by root."""
        px, py = self.find(x), self.find(y)
        if px != py:
            self.parent[py] = px


class CentroidClusterMerger(object):
    """Post-clustering merge operation driven by pairwise centroid metric matrices.

    Decision cascade (per spec):
      3 active metrics → unanimous 3-way intersection
                       → union of pairwise (2-way) intersections
                       → priority fallback (Correlation > RMSE > Wasserstein) if empty
      2 active metrics → pairwise intersection
                       → priority fallback if empty
      1 active metric  → that metric directly

    Threshold formula (IQR box-plot, Q3/Q1):
      Correlation (lower is better):
          threshold = Q3;  candidates where score ≥ threshold
      RMSE, Wasserstein (higher is better):
          threshold = Q1;  candidates where score ≤ threshold

    Cascade candidates are computed directly on the full-centroid pairwise
    matrices (the same Correlation/RMSE/Wasserstein matrices used for
    k-selection), with no windowing or slicing of any kind. Candidates are
    further filtered by a resonant frequency gate before union-find
    connected-component merging: each centroid's dominant peak/dip is found
    on its [-1, 1] normalized-then-detrended phase curve (the same shared
    preprocessing as the metrics themselves, via CentroidMetricsCalculator),
    and only pairs sharing a resonant frequency (same direction,
    ≥ _MIN_SHARED_RESONANCE_BINS overlapping bins) are retained. Merged
    centroid = arithmetic mean of the contributing cluster_means (full
    segment).
    """

    def __init__(self, centroid_calculator):
        self.logger = logging.getLogger(__name__)
        self.centroid_calculator = centroid_calculator

    def execute_merge(self, cluster_means, file_labels, matrices, metrics_to_use,
                      unique_frequencies, k):
        """Compute merge candidates directly from the full-centroid matrices and return
        the resulting MergeResult (or None).

        Candidate detection runs directly on the full-segment pairwise matrices
        (the same ones used for k-selection), with no windowing of any kind,
        before the resonance gate is applied.

        Args:
            cluster_means:      np.ndarray (k, n_freq, 2)
            file_labels:        np.ndarray (n_files,) — original cluster assignments
            matrices:           dict {metric_name: np.ndarray (k, k)} — full-segment
                                matrices, both to determine active metrics and to
                                compute merge candidates
            metrics_to_use:     list of metric name strings from config
            unique_frequencies: np.ndarray — frequency axis values (Hz)
            k:                  number of clusters before merging

        Returns:
            MergeResult or None.
        """
        active = [m for m in _METRIC_ORDER if m in metrics_to_use and m in matrices]
        if not active:
            return None
        candidates = self._compute_all_candidates(matrices, active, k)
        bad_pairs, level_label = self._vote_cascade(candidates, active)
        self._log_initial_candidates(bad_pairs, level_label)
        if not bad_pairs:
            return None
        final_pairs, discarded = self._apply_resonance_gate(
            bad_pairs, cluster_means, unique_frequencies, k
        )
        self._log_resonance_gate_result(discarded, final_pairs)
        return self._finalise_merge(final_pairs, level_label, cluster_means, file_labels, k)

    def save_merged_centroids(self, merged_means, merged_dir,
                               unique_frequencies, k_merged, model_manager):
        """Save centroid .txt files for the merged result (no model.json written).

        Args:
            merged_means:       np.ndarray (k_merged, n_freq, 2)
            merged_dir:         destination directory (e.g. k_N/merged/)
            unique_frequencies: frequency axis array
            k_merged:           number of surviving clusters
            model_manager:      ModelManager instance from FRFClusteringBase
        """
        os.makedirs(merged_dir, exist_ok=True)
        model_manager.save_centroid_data_files(
            merged_means, merged_dir, unique_frequencies, k_merged
        )
        self.logger.info(f"    Saved {k_merged} merged centroid files to: {merged_dir}")

    @staticmethod
    def _compute_group_centroid_features(feature_data, file_labels, group):
        """Arithmetic mean of feature_data rows whose file_labels fall in group."""
        member_mask = np.isin(file_labels, group)
        return np.mean(feature_data[member_mask], axis=0)

    def build_merged_model_centroids(self, pre_cluster_centers, merge_result,
                                      feature_data, file_labels):
        """Build post-merge cluster centers in the trained model's own feature space.

        Merged groups are recomputed as the arithmetic mean of their member files'
        scaled features; untouched (size-1) groups are copied through unchanged
        from the pre-merge model.

        Args:
            pre_cluster_centers: np.ndarray (k, n_freq, n_features) — pre-merge model.cluster_centers_
            merge_result:        MergeResult with merge_groups/label_map populated
            feature_data:        np.ndarray (n_files, n_freq, n_features) — scaled training features,
                                  positionally aligned with file_labels
            file_labels:         np.ndarray (n_files,) — pre-merge cluster assignment per file
        """
        n_freq, n_features = feature_data.shape[1], feature_data.shape[2]
        new_centers = np.zeros((merge_result.k_merged, n_freq, n_features))
        for group in merge_result.merge_groups:
            new_id = merge_result.label_map[group[0]]
            if len(group) > 1:
                new_centers[new_id] = self._compute_group_centroid_features(
                    feature_data, file_labels, group
                )
            else:
                new_centers[new_id] = pre_cluster_centers[group[0]]
        return new_centers

    def build_consolidated_model_centroids(self, merge_result, feature_data, file_labels):
        """Build post-merge cluster centers for hierarchical consolidation.

        Every group (merged or not) is recomputed as the arithmetic mean of its
        member files' features under the shared segment-wide normalization, since
        the original per-parent-cluster stage-2 centroids are not on a comparable
        scale and cannot simply be copied through.

        Args:
            merge_result: MergeResult with merge_groups/label_map populated
            feature_data: np.ndarray (n_files, n_freq, n_features) — shared-normalized
                          stage-2 features, positionally aligned with file_labels
            file_labels:  np.ndarray (n_files,) — pre-merge (combined) cluster label per file
        """
        n_freq, n_features = feature_data.shape[1], feature_data.shape[2]
        new_centers = np.zeros((merge_result.k_merged, n_freq, n_features))
        for group in merge_result.merge_groups:
            new_id = merge_result.label_map[group[0]]
            new_centers[new_id] = self._compute_group_centroid_features(
                feature_data, file_labels, group
            )
        return new_centers

    def save_merged_model(self, cluster_centers, k_merged, metric, random_state,
                           merged_dir, model_manager):
        """Save the post-merge model.json (consolidated cluster centers) to merged_dir.

        Args:
            cluster_centers: np.ndarray (k_merged, n_freq, n_features), same feature
                              space as the pre-merge trained model
            k_merged:        number of surviving clusters
            metric, random_state: copied from the pre-merge model (flat case) or the
                              fixed training settings (hierarchical case)
            merged_dir:       destination directory (same one centroid .txt files are saved to)
            model_manager:    ModelManager instance from FRFClusteringBase
        """
        os.makedirs(merged_dir, exist_ok=True)
        model_path = os.path.join(merged_dir, 'model.json')
        stub = _MergedModelStub(cluster_centers, k_merged, metric, random_state)
        model_manager.save_model(stub, model_path, format='json')
        self.logger.info(f"    Saved merged model.json ({k_merged} clusters) to: {model_path}")
        return model_path

    def _compute_all_candidates(self, matrices, active, k):
        """Return dict mapping each active metric name to its bad-pair set."""
        return {m: self._compute_metric_candidates(matrices[m], m, k) for m in active}

    def _compute_metric_candidates(self, matrix, metric, k):
        """Find bad pairs for one metric using the 25%-from-worst threshold."""
        finite_vals = self._get_finite_lower_triangle(matrix, k)
        if not finite_vals:
            return set()
        threshold = self._compute_threshold(finite_vals, metric)
        self.logger.info(f"    {metric} threshold (IQR): {threshold:.6f}")
        return self._extract_pairs_beyond_threshold(matrix, metric, threshold, k)

    @staticmethod
    def _get_finite_lower_triangle(matrix, k):
        """Return list of all finite lower-triangle values from a (k, k) matrix."""
        vals = []
        for i in range(k):
            for j in range(i):
                v = matrix[i, j]
                if np.isfinite(v):
                    vals.append(v)
        return vals

    @staticmethod
    def _compute_threshold(finite_vals, metric):
        """Compute IQR-based threshold for one metric.

        Correlation             (lower=better): threshold = Q3 (75th percentile)
        RMSE, Wasserstein       (higher=better): threshold = Q1 (25th percentile)
        """
        if metric == 'Correlation':
            return float(np.percentile(finite_vals, 75))
        return float(np.percentile(finite_vals, 25))

    @staticmethod
    def _extract_pairs_beyond_threshold(matrix, metric, threshold, k):
        """Return set of (i, j) pairs (i < j) whose score falls on the bad side of threshold."""
        is_correlation = (metric == 'Correlation')
        pairs = set()
        for i in range(k):
            for j in range(i):
                v = matrix[i, j]
                if not np.isfinite(v):
                    continue
                if (is_correlation and v >= threshold) or (not is_correlation and v <= threshold):
                    pairs.add((j, i))
        return pairs

    @staticmethod
    def _shifted_window_bounds(idx, half_window, n):
        """Return (start, end) inclusive indices for a fixed-length window around idx.

        Shifts inward at the array edges instead of truncating, so the window
        spans exactly 2*half_window + 1 indices whenever the segment is large
        enough; half_window is clamped down for segments smaller than that.
        """
        half_window = min(half_window, (n - 1) // 2) if n > 1 else 0
        start = idx - half_window
        end = idx + half_window
        if start < 0:
            end -= start
            start = 0
        elif end > n - 1:
            start -= (end - (n - 1))
            end = n - 1
        return max(start, 0), min(end, n - 1)

    def _vote_cascade(self, candidates, active):
        """Cascade from strictest (unanimous) to most lenient (single metric).

        Stage 1: unanimous intersection across all active metrics.
        Stage 2: union of every pairwise intersection among active metrics.
        Stage 3: priority-ordered single-metric fallback.

        Returns:
            (bad_pairs, level_label): set of (i, j) pairs and a logging label
        """
        if len(active) == 1:
            return candidates[active[0]], active[0]
        result = self._cascade_unanimous(candidates, active)
        if not result[0]:
            result = self._cascade_pairwise_union(candidates, active)
        if not result[0]:
            result = self._cascade_fallback(candidates, active)
        return result

    @staticmethod
    def _cascade_unanimous(candidates, active):
        """Intersection across all active metrics (Stage 1)."""
        intersection = candidates[active[0]]
        for metric in active[1:]:
            intersection = intersection & candidates[metric]
        return intersection, ' ∩ '.join(active)

    @staticmethod
    def _cascade_pairwise_union(candidates, active):
        """Union of every pairwise intersection among active metrics (Stage 2)."""
        union_pairs = set()
        labels = []
        for metric_a, metric_b in combinations(active, 2):
            pair_intersection = candidates[metric_a] & candidates[metric_b]
            if pair_intersection:
                union_pairs |= pair_intersection
                labels.append(f'{metric_a} ∩ {metric_b}')
        label = ' ∪ '.join(labels) if labels else 'pairwise'
        return union_pairs, label

    def _cascade_fallback(self, candidates, active):
        """Priority-ordered single-metric fallback (Stage 3)."""
        fallback = self._get_fallback_metric(active)
        return candidates[fallback], f'{fallback} (fallback)'

    @staticmethod
    def _get_fallback_metric(active):
        """Return highest-priority available fallback: Correlation > RMSE > Wasserstein."""
        for m in _METRIC_ORDER:
            if m in active:
                return m
        return active[0]

    def _log_initial_candidates(self, bad_pairs, level_label):
        """Log metric-cascade merge candidates before resonance gate."""
        if not bad_pairs:
            self.logger.info(f"    No merge candidates from cascade level: {level_label}")
            return
        pairs_str = ', '.join(f'(C{i}, C{j})' for i, j in sorted(bad_pairs))
        self.logger.info(
            f"    Merge candidates at cascade level [{level_label}]: {pairs_str}"
        )

    def _log_resonance_gate_result(self, discarded, final_pairs):
        """Log pairs discarded and surviving after resonance frequency gate."""
        if discarded:
            disc_str = ', '.join(f'(C{i}, C{j})' for i, j in sorted(discarded))
            self.logger.info(f"    Discarded after frequency matching: {disc_str}")
        else:
            self.logger.info("    No pairs discarded by frequency gate")
        if final_pairs:
            final_str = ', '.join(f'(C{i}, C{j})' for i, j in sorted(final_pairs))
            self.logger.info(f"    Final merge candidates: {final_str}")
        else:
            self.logger.info("    No final merge candidates after frequency gate")

    def _compute_resonances(self, detrended_phase, unique_frequencies):
        """Return list with the single dominant resonance (freq_hz, direction, window).

        freq_hz:   Hz value of the most prominent local peak/dip in unique_frequencies
        direction: 'rise' for a local maximum, 'dip' for a local minimum,
                   chosen by topographic prominence rather than raw global
                   extremum so an interior resonance hump is not overridden
                   by a larger residual elsewhere (e.g. a detrend endpoint
                   effect). Falls back to the global extremum when no
                   interior peak/dip exists. Ties favor 'rise'.
        window:    frozenset of the frequency bin(s) immediately neighboring
                   the extremum (one bin left, one bin right), clamped at the
                   array edges so an edge extremum still yields a 2-value window.
        Returns empty list if the signal is flat.
        """
        peak_to_peak = detrended_phase.max() - detrended_phase.min()
        if peak_to_peak == 0.0:
            return []
        idx, direction = self._select_dominant_peak(detrended_phase)
        window = self._build_resonance_window(idx, unique_frequencies)
        return [(unique_frequencies[idx], direction, window)]

    def _select_dominant_peak(self, detrended_phase):
        """Pick the most prominent local peak (rise) or dip; falls back to the global extremum."""
        rise = self._find_most_prominent_peak(detrended_phase)
        dip = self._find_most_prominent_peak(-detrended_phase)
        if rise is None and dip is None:
            max_idx = int(np.argmax(detrended_phase))
            min_idx = int(np.argmin(detrended_phase))
            return self._select_dominant_extremum(detrended_phase, max_idx, min_idx)
        if dip is None or (rise is not None and rise[1] >= dip[1]):
            return rise[0], 'rise'
        return dip[0], 'dip'

    @staticmethod
    def _find_most_prominent_peak(signal):
        """Return (idx, prominence) of the most prominent local peak in signal, or None."""
        peak_indices, properties = find_peaks(signal, prominence=0.0)
        if len(peak_indices) == 0:
            return None
        best = int(np.argmax(properties['prominences']))
        return int(peak_indices[best]), float(properties['prominences'][best])

    @staticmethod
    def _select_dominant_extremum(detrended_phase, max_idx, min_idx):
        """Pick whichever extremum deviates further from zero; ties favor 'rise'."""
        if abs(detrended_phase[min_idx]) > abs(detrended_phase[max_idx]):
            return min_idx, 'dip'
        return max_idx, 'rise'

    @staticmethod
    def _build_resonance_window(idx, unique_frequencies):
        """Build frozenset of the frequency bin(s) neighboring index idx.

        Uses a shifted (not truncated) window so an extremum at the first or
        last bin still yields the full 3-value window instead of a shorter one.
        """
        lo, hi = CentroidClusterMerger._shifted_window_bounds(idx, 1, len(unique_frequencies))
        return frozenset(unique_frequencies[lo:hi + 1])

    def _build_centroid_resonances(self, cluster_means, unique_frequencies, k):
        """Return dict mapping centroid index to its list of (freq_hz, direction, window).

        Peak/dip detection runs on the shared [-1, 1] normalized-then-detrended
        curves (CentroidMetricsCalculator.get_detrended_normalized_curves) — the
        same preprocessing used for Correlation/RMSE/Wasserstein — rather than a
        merge-module-local detrend-only computation.
        """
        curves = self.centroid_calculator.get_detrended_normalized_curves(cluster_means, unique_frequencies)
        return {c: self._compute_resonances(curves[c], unique_frequencies) for c in range(k)}

    @staticmethod
    def _pairs_share_resonance(res_a, res_b):
        """Return True if any resonance in res_a and res_b share direction and >=2 overlapping window bins."""
        for _, dir_a, window_a in res_a:
            for _, dir_b, window_b in res_b:
                if dir_a == dir_b and len(window_a & window_b) >= _MIN_SHARED_RESONANCE_BINS:
                    return True
        return False

    def _log_centroid_resonances(self, resonances, k):
        """Log per-centroid resonance peaks and their sorted frequency windows."""
        for c in range(k):
            res_list = resonances[c]
            self.logger.info(f"    Centroid {c}: {len(res_list)} resonance(s)")
            for freq_hz, direction, window in res_list:
                sorted_window = [round(f, 1) for f in sorted(window)]
                self.logger.info(
                    f"      {direction.capitalize():<4} at {freq_hz:.1f} Hz | "
                    f"window: {sorted_window} Hz ({len(sorted_window)} bins)"
                )

    def _apply_resonance_gate(self, bad_pairs, cluster_means, unique_frequencies, k):
        """Filter bad_pairs, keeping only those whose centroids share a resonant frequency."""
        resonances = self._build_centroid_resonances(cluster_means, unique_frequencies, k)
        self._log_centroid_resonances(resonances, k)
        kept = set()
        discarded = set()
        for pair in bad_pairs:
            i, j = pair
            if self._pairs_share_resonance(resonances[i], resonances[j]):
                kept.add(pair)
            else:
                discarded.add(pair)
        return kept, discarded

    @staticmethod
    def _connected_components(bad_pairs, k):
        """Partition k cluster IDs into connected components via union-find.

        Returns:
            list of sorted lists — each inner list is one connected component
        """
        uf = _UnionFind(k)
        for i, j in bad_pairs:
            uf.union(i, j)
        groups = {}
        for c in range(k):
            root = uf.find(c)
            groups.setdefault(root, []).append(c)
        return [sorted(g) for g in groups.values()]

    def _finalise_merge(self, bad_pairs, level_label, cluster_means, file_labels, k):
        """Build MergeResult when real merges exist, or return None."""
        if not bad_pairs:
            self.logger.info("    No merge candidates remain after resonance frequency gate")
            return None
        self.logger.info(f"    Merge triggered at level: {level_label}")
        merge_groups = self._connected_components(bad_pairs, k)
        if not any(len(g) > 1 for g in merge_groups):
            return None
        return self._build_merge_result(cluster_means, file_labels, merge_groups, k)

    def _build_merge_result(self, cluster_means, file_labels, merge_groups, k):
        """Construct merged means, remapped labels, and annotation string."""
        label_map, k_merged = self._build_label_map(merge_groups)
        merged_means = self._compute_merged_means(
            cluster_means, merge_groups, label_map, k_merged
        )
        merged_labels = np.array([label_map[lbl] for lbl in file_labels], dtype=int)
        annotation = self._build_annotation(merge_groups, label_map)
        self.logger.info(f"    Merge: {k} → {k_merged} clusters. {annotation}")
        sorted_groups = sorted(merge_groups, key=lambda g: g[0])
        return MergeResult(
            merged_means, merged_labels, k_merged, annotation,
            merge_groups=sorted_groups, label_map=label_map
        )

    @staticmethod
    def _build_label_map(merge_groups):
        """Map each old cluster ID to a new contiguous ID.

        Groups are sorted by their minimum member so new IDs are deterministic.

        Returns:
            label_map:  dict {old_id: new_id}
            k_merged:   int — total surviving logical clusters
        """
        sorted_groups = sorted(merge_groups, key=lambda g: g[0])
        label_map = {}
        for new_id, group in enumerate(sorted_groups):
            for old_id in group:
                label_map[old_id] = new_id
        return label_map, len(sorted_groups)

    def _compute_merged_means(self, cluster_means, merge_groups, label_map, k_merged):
        """Build merged cluster_means array using arithmetic-mean centroids."""
        n_freq = cluster_means.shape[1]
        merged_means = np.zeros((k_merged, n_freq, 2))
        for group in merge_groups:
            new_label = label_map[group[0]]
            merged_means[new_label] = self._compute_group_mean(cluster_means, group)
        return merged_means

    @staticmethod
    def _compute_group_mean(cluster_means, group):
        """Arithmetic mean of the contributing cluster_means for one merge group."""
        return np.mean(cluster_means[group], axis=0)

    @staticmethod
    def _build_annotation(merge_groups, label_map):
        """Build the merge annotation string for plot titles.

        Format: 'Merged Groups: [C3, C7] → C2 | [C0, C1] → C0'
        """
        parts = []
        for group in sorted(merge_groups, key=lambda g: g[0]):
            if len(group) < 2:
                continue
            old_str = '[' + ', '.join(f'C{c}' for c in group) + ']'
            new_str = f'C{label_map[group[0]]}'
            parts.append(f'{old_str} → {new_str}')
        if not parts:
            return ''
        return MERGED_GROUPS + ' | '.join(parts)

    def compose_sequential_merges(self, first_result, second_result):
        """Compose two sequential MergeResults into one, expressed entirely in terms of
        the original (pre-first-merge) cluster ids, so the caller's existing single
        reconcile/save step can rebuild the final centroids directly from the original
        per-file features in one pass — never nesting a second 'merged' directory
        inside the first.
        """
        combined_label_map = {
            old_id: second_result.label_map[merged_id]
            for old_id, merged_id in first_result.label_map.items()
        }
        combined_groups = self._groups_from_label_map(combined_label_map, second_result.k_merged)
        annotation = self._combine_pass_annotations(first_result, second_result)
        return MergeResult(
            second_result.merged_means, second_result.merged_labels, second_result.k_merged,
            annotation, merge_groups=combined_groups, label_map=combined_label_map
        )

    @staticmethod
    def _groups_from_label_map(label_map, k_merged):
        """Invert an {old_id: new_id} map into sorted-by-min-member groups, one per new id."""
        groups = {new_id: [] for new_id in range(k_merged)}
        for old_id, new_id in label_map.items():
            groups[new_id].append(old_id)
        return [sorted(members) for _, members in sorted(groups.items())]

    @staticmethod
    def _combine_pass_annotations(first_result, second_result):
        """Combine two merge-pass annotations into one label for plot titles, e.g.
        'First Merge (k=6→4): [C0, C1] → C0 | Second Merge (k=4→3): [C0, C3] → C0'.
        """
        parts = []
        if first_result.annotation:
            groups_str = first_result.annotation.replace(MERGED_GROUPS, '')
            parts.append(
                f'First Merge (k={len(first_result.label_map)}→{first_result.k_merged}): {groups_str}'
            )
        if second_result.annotation:
            groups_str = second_result.annotation.replace(MERGED_GROUPS, '')
            parts.append(
                f'Second Merge (k={first_result.k_merged}→{second_result.k_merged}): {groups_str}'
            )
        return ' | '.join(parts)
