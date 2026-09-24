# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Merging Utility Package
*  File Name: frf_merge_model.py
*  File Description: Standalone TimeSeriesKMeans model I/O, user-specified
*                    cluster-merge-group construction, and the bounded
*                    forward-pass convergence loop for the FRF cluster-merging
*                    utility. Self contained - no dependency on the training
*                    application package.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import json
import logging
from datetime import datetime

import numpy as np
from tslearn.clustering import TimeSeriesKMeans


MODEL_NAME = 'model.json'
MAX_FORWARD_PASSES = 30
CONVERGENCE_PLATEAU_WINDOW = 5
CONVERGENCE_PLATEAU_TOLERANCE = 50


class ModelLoadError(Exception):
    """Raised when a trained model.json cannot be loaded or is malformed."""


class ModelIO(object):
    """Loads/saves TimeSeriesKMeans models in the same JSON format used across
    the training pipeline, plus the two centroid-data-file formats."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def load_model(self, path):
        """Load a model.json into a TimeSeriesKMeans instance with cluster_centers_ set."""
        self._validate_model_file(path)
        with open(path, 'r', encoding='utf-8-sig') as f:
            model_json = json.load(f)

        missing = [f for f in ('n_clusters', 'cluster_centers_') if f not in model_json]
        if missing:
            error_msg = f"Model file '{path}' missing required fields: {missing}"
            self.logger.error(error_msg)
            raise ModelLoadError(error_msg)

        centers = np.array(model_json['cluster_centers_'])
        if np.any(np.isnan(centers)) or np.any(np.isinf(centers)):
            error_msg = f"Model file '{path}' cluster centers contain NaN or Inf values"
            self.logger.error(error_msg)
            raise ModelLoadError(error_msg)

        km = TimeSeriesKMeans(
            n_clusters=model_json['n_clusters'],
            metric=model_json.get('metric', 'euclidean'),
            random_state=model_json.get('random_state', 0),
        )
        km.cluster_centers_ = centers
        self.logger.info(f"Loaded model '{path}': k={model_json['n_clusters']}, centers={centers.shape}")
        return km

    @staticmethod
    def _validate_model_file(path):
        """Confirm the model file exists and is non-empty."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        if os.path.getsize(path) == 0:
            raise ModelLoadError(f"Model file is empty: {path}")

    def save_model(self, cluster_centers, n_clusters, metric, random_state, path):
        """Save post-merge cluster centers in the same model.json format."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        model_json = {
            'n_clusters': n_clusters,
            'metric': metric,
            'random_state': random_state,
            'cluster_centers_': np.asarray(cluster_centers).tolist(),
        }
        with open(path, 'w', encoding='utf-8-sig') as f:
            json.dump(model_json, f)
        self.logger.info(f"Saved merged model.json ({n_clusters} clusters) to: {path}")

    def save_centroid_data_files(self, cluster_means, out_dir, frequencies, k):
        """Save one bode_centroid_{id}.txt per cluster from arithmetic-mean real/imag data."""
        os.makedirs(out_dir, exist_ok=True)
        for cluster_id in range(k):
            path = os.path.join(out_dir, f'bode_centroid_{cluster_id}.txt')
            with open(path, 'w', encoding='utf-8-sig') as f:
                f.writelines(self._centroid_header())
                for freq_idx, frequency in enumerate(frequencies):
                    real_part = cluster_means[cluster_id, freq_idx, 0]
                    imag_part = cluster_means[cluster_id, freq_idx, 1]
                    gain_db, phase_deg = self._to_gain_phase(real_part, imag_part)
                    f.write(f"{frequency:.2f},{gain_db:.6f},{phase_deg:.6f}\n")
                f.write("END\n")
        self.logger.info(f"Saved {k} bode centroid file(s) to: {out_dir}")

    def save_model_centroid_data_files(self, cluster_centers, out_dir, frequencies, k, features_list):
        """Save one model_centroid_{id}.txt per cluster from feature-space centroid values."""
        os.makedirs(out_dir, exist_ok=True)
        n_columns = 1 + len(features_list)
        for cluster_id in range(k):
            path = os.path.join(out_dir, f'model_centroid_{cluster_id}.txt')
            with open(path, 'w', encoding='utf-8-sig') as f:
                f.writelines(self._model_centroid_header(features_list, n_columns))
                for freq_idx, frequency in enumerate(frequencies):
                    values = cluster_centers[cluster_id, freq_idx, :]
                    values_str = ",".join(f"{value:.6f}" for value in values)
                    f.write(f"{frequency:.2f},{values_str}\n")
                f.write("END\n")
        self.logger.info(f"Saved {k} model centroid file(s) to: {out_dir}")

    @staticmethod
    def _to_gain_phase(real_part, imag_part):
        """Convert a single (real, imag) point to (gain_dB, phase_deg)."""
        magnitude = np.sqrt(real_part ** 2 + imag_part ** 2)
        gain_db = 20 * np.log10(magnitude) if magnitude > 0 else -np.inf
        phase_deg = np.degrees(np.arctan2(imag_part, real_part))
        return gain_db, phase_deg

    @staticmethod
    def _centroid_header():
        """9-line GPLOT-style header for a bode_centroid_*.txt file."""
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        return [
            f"{timestamp}\n", "3\n", "3\n", "Frequency [Hz]\n", "Centroid Gain [dB]\n",
            "Centroid Phase[deg]\n", "Caption 1\n", "Caption 2\n", "Caption 3\n",
        ]

    @staticmethod
    def _model_centroid_header(features_list, n_columns):
        """Header for a model_centroid_*.txt file (frequency + one column per feature)."""
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        header = [f"{timestamp}\n", "3\n", f"{n_columns}\n", "Frequency [Hz]\n"]
        header += [f"{name}\n" for name in features_list]
        header += [f"Caption {i}\n" for i in range(1, n_columns + 1)]
        return header


class MergeResult(object):
    """Bundles the outputs of building a user-specified cluster merge."""

    def __init__(self, merged_means, merged_labels, k_merged, annotation, merge_groups, label_map):
        self.merged_means = merged_means
        self.merged_labels = merged_labels
        self.k_merged = k_merged
        self.annotation = annotation
        self.merge_groups = merge_groups
        self.label_map = label_map


class MergeGroupBuilder(object):
    """Builds a MergeResult directly from user-specified cluster_groups (no
    centroid-metric candidate detection - the merge is exactly what was requested)."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def build_user_merge_result(self, cluster_means, file_labels, k, cluster_group_tuples):
        """Build the full-partition merge (explicit groups + singleton remainder),
        remapped labels and arithmetic-mean merged centroid means."""
        merge_groups = self._full_partition(k, cluster_group_tuples)
        label_map, k_merged = self._build_label_map(merge_groups)
        merged_means = self._compute_merged_means(cluster_means, merge_groups, label_map, k_merged)
        merged_labels = np.array([label_map[int(lbl)] for lbl in file_labels], dtype=int)
        annotation = self._build_annotation(merge_groups, label_map)
        self.logger.info(f"User-specified merge: {k} -> {k_merged} clusters. {annotation}")
        return MergeResult(merged_means, merged_labels, k_merged, annotation, merge_groups, label_map)

    @staticmethod
    def _full_partition(k, cluster_group_tuples):
        """Complete the user's merge tuples into a full partition of 0..k-1 by
        adding a singleton group for every cluster id not otherwise mentioned."""
        mentioned = set()
        groups = []
        for group in cluster_group_tuples:
            normalised = sorted({int(c) for c in group})
            groups.append(normalised)
            mentioned.update(normalised)
        for cluster_id in range(k):
            if cluster_id not in mentioned:
                groups.append([cluster_id])
        return sorted(groups, key=lambda g: g[0])

    @staticmethod
    def _build_label_map(merge_groups):
        """Map each old cluster id to a new contiguous id, ordered by group's min member."""
        label_map = {}
        for new_id, group in enumerate(merge_groups):
            for old_id in group:
                label_map[old_id] = new_id
        return label_map, len(merge_groups)

    @staticmethod
    def _compute_merged_means(cluster_means, merge_groups, label_map, k_merged):
        """Arithmetic-mean merged centroid (real/imag) array."""
        n_freq = cluster_means.shape[1]
        merged_means = np.zeros((k_merged, n_freq, 2))
        for group in merge_groups:
            new_id = label_map[group[0]]
            merged_means[new_id] = np.mean(cluster_means[group], axis=0)
        return merged_means

    @staticmethod
    def _build_annotation(merge_groups, label_map):
        """Build the 'Merged Groups: [C3, C7] -> C2 | ...' annotation string."""
        parts = []
        for group in merge_groups:
            if len(group) < 2:
                continue
            old_str = '[' + ', '.join(f'C{c}' for c in group) + ']'
            parts.append(f'{old_str} -> C{label_map[group[0]]}')
        return 'Merged Groups: ' + ' | '.join(parts) if parts else ''

    @staticmethod
    def build_merged_feature_centers(pre_cluster_centers, merge_groups, label_map, k_merged,
                                      feature_data, file_labels):
        """Build post-merge cluster centers in the model's own feature space: merged
        groups are the arithmetic mean of their members' scaled features; untouched
        (size-1) groups are copied through unchanged from the pre-merge model."""
        n_freq, n_features = feature_data.shape[1], feature_data.shape[2]
        new_centers = np.zeros((k_merged, n_freq, n_features))
        for group in merge_groups:
            new_id = label_map[group[0]]
            if len(group) > 1:
                member_mask = np.isin(file_labels, group)
                new_centers[new_id] = np.mean(feature_data[member_mask], axis=0)
            else:
                new_centers[new_id] = pre_cluster_centers[group[0]]
        return new_centers


def calculate_cluster_means(segment_file_dict, file_labels, k, unique_frequencies):
    """Per-cluster arithmetic mean of raw real/imaginary data. Shape: (k, n_freq, 2)."""
    n_frequencies = len(unique_frequencies)
    cluster_means = np.zeros((k, n_frequencies, 2))
    for cluster_id in range(k):
        real_sum = np.zeros(n_frequencies)
        imag_sum = np.zeros(n_frequencies)
        count = 0
        for file_idx, data in enumerate(segment_file_dict['files'].values()):
            if file_labels[file_idx] == cluster_id:
                real_sum += data['real']
                imag_sum += data['imaginary']
                count += 1
        if count > 0:
            cluster_means[cluster_id, :, 0] = real_sum / count
            cluster_means[cluster_id, :, 1] = imag_sum / count
    return cluster_means


def count_files_by_source(segment_file_dict, file_labels, k):
    """Per-cluster (real_counts, worst_counts) breakdown for the Bode centroid legend."""
    real_counts = [0] * k
    worst_counts = [0] * k
    for file_idx, file_data in enumerate(segment_file_dict['files'].values()):
        cluster_id = int(file_labels[file_idx])
        if file_data.get('is_worst_model', False):
            worst_counts[cluster_id] += 1
        else:
            real_counts[cluster_id] += 1
    return real_counts, worst_counts


class ForwardPassConverger(object):
    """Bounded iterative nearest-centroid refinement: each pass re-inits a
    TimeSeriesKMeans with the previous pass's centroids and takes exactly one
    Lloyd step, so the outer loop (not tslearn's own internal convergence)
    controls refinement. Stops on a plateaued deviation count or MAX_FORWARD_PASSES."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def run(self, initial_centers, feature_data, initial_labels, k_merged, model_metric,
            model_random_state, on_iteration=None):
        """Run the bounded forward-pass loop.

        Args:
            on_iteration: optional callback(pass_num, new_labels, new_centers) invoked
                          after every pass, e.g. to write per-iteration plot snapshots.

        Returns (final_centers, final_labels, deviations).
        """
        old_centers, old_labels = initial_centers, initial_labels
        deviations = []
        for pass_num in range(1, MAX_FORWARD_PASSES + 1):
            new_centers, new_labels = self._one_lloyd_step(
                old_centers, feature_data, k_merged, model_metric, model_random_state
            )
            deviation = int(np.sum(new_labels != old_labels))
            deviations.append(deviation)
            self.logger.info(
                f"Forward pass {pass_num}: {deviation} file(s) reassigned (k_merged={k_merged})"
            )
            if on_iteration is not None:
                on_iteration(pass_num, new_labels, new_centers)
            old_centers, old_labels = new_centers, new_labels
            if self._has_plateaued(deviations):
                break
        return old_centers, old_labels, deviations

    @staticmethod
    def _one_lloyd_step(old_centers, feature_data, k_merged, model_metric, model_random_state):
        """Fit a single Lloyd iteration initialised at old_centers."""
        km = TimeSeriesKMeans(
            n_clusters=k_merged, metric=model_metric, init=old_centers,
            n_init=1, max_iter=1, random_state=model_random_state, verbose=0,
        )
        new_labels = km.fit_predict(feature_data)
        return km.cluster_centers_, new_labels

    @staticmethod
    def _has_plateaued(deviations):
        """True once the last CONVERGENCE_PLATEAU_WINDOW deviation counts are all
        within CONVERGENCE_PLATEAU_TOLERANCE files of each other."""
        if len(deviations) < CONVERGENCE_PLATEAU_WINDOW:
            return False
        window = deviations[-CONVERGENCE_PLATEAU_WINDOW:]
        return (max(window) - min(window)) <= CONVERGENCE_PLATEAU_TOLERANCE
