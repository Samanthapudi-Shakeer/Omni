# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_utils.py
*  File Description: Utility file for the inference application.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import numpy as np
import logging
import json
from tslearn.clustering import TimeSeriesKMeans
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import colorsys
from frf_inference_metric_components import CurveProcessor


def resolve_path_with_root_dir(path, root_dir):
    """Resolve relative path with root_dir to get absolute path

    Args:
        path: Relative or absolute path
        root_dir: Root directory to resolve against

    Returns:
        Absolute path
    """
    if path is None:
        return None

    normalized = os.path.normpath(path)

    if os.path.isabs(normalized):
        return normalized

    return os.path.join(root_dir, normalized)


class LoggingManager(object):
    """Manages logging setup for the application"""

    def __init__(self):
        # No need for declaration
        pass

    @staticmethod
    def setup_logging(output_dir):
        """Setup logging to both file and console"""
        logs_dir = os.path.join(output_dir, 'logs')

        # Use safe directory creation
        try:
            os.makedirs(logs_dir, exist_ok = True)
        except Exception as e:
            # Fallback to current directory if logs dir creation fails
            print(f"Warning: Could not create logs directory: {logs_dir}")
            print(f"Falling back to current directory for logs")
            logs_dir = '.'

        log_file = os.path.join(logs_dir, f'frf_inference_application.log')

        try:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file, encoding='utf-8-sig'),
                    logging.StreamHandler()
                ]
            )
        except Exception as e:
            print(f"Error setting up logging: {e}")
            # Fallback to console-only logging
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler()]
            )
            log_file = None

        logger = logging.getLogger(__name__)
        if log_file:
            logger.info(f"Logging initialized. Log file: {log_file}")
        else:
            logger.warning("Logging initialized (console only - file logging failed)")

        return logger, log_file


class ModelManager(object):
    """Handles model saving and loading operations"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def save_model(model, path, format='json'):
        """Save TimeSeriesKMeans model in JSON format"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if format == 'json':
            model_json = {
                'n_clusters': model.n_clusters,
                'metric': model.metric,
                'random_state': model.random_state,
                'cluster_centers_': model.cluster_centers_.tolist()
            }
            with open(path, 'w', encoding='utf-8-sig') as f:
                json.dump(model_json, f)
        else:
            raise ValueError("Unsupported model format: use 'json'")

    def load_model(self, path, format='json'):
        """Load TimeSeriesKMeans model from JSON with Validation"""
        if not os.path.exists(path):
            error_msg = f"Model file not found: {path}"
            self.logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        if os.path.getsize(path) == 0:
            error_msg = f"Model file is empty: {path}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        if format == 'json':
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    model_json = json.load(f)

                # Validate required fields
                required_fields = ['n_clusters', 'cluster_centers_']
                missing_fields = [f for f in required_fields if f not in model_json]

                if missing_fields:
                    error_msg = f"Model file missing required fields: {missing_fields}"
                    self.logger.error(error_msg)
                    raise ValueError(error_msg)

                # Validate cluster centers shape
                centers = np.array(model_json['cluster_centers_'])
                expected_k = model_json['n_clusters']

                # Check for NaN or Inf in cluster centers
                if np.any(np.isnan(centers)) or np.any(np.isinf(centers)):
                    error_msg = "Cluster centers contain NaN or Inf values"
                    self.logger.error(error_msg)
                    raise ValueError(error_msg)

                km = TimeSeriesKMeans(
                    n_clusters=model_json['n_clusters'],
                    metric=model_json.get('metric', 'euclidean'),
                    random_state=model_json.get('random_state', 0)
                )
                km.cluster_centers_ = centers

                self.logger.info(f"  Successfully loaded model: k={expected_k}, centers_shape={centers.shape}")
                return km

            except Exception as e:
                self.logger.error(f"Error loading model from {path}: {e}")
                raise
        else:
            raise ValueError("Unsupported model format: use 'json'")

    @staticmethod
    def peek_n_clusters(path):
        """Read only the 'n_clusters' field from a model.json file, without constructing
        the TimeSeriesKMeans object. Used to determine the numeric k for a trained model
        path before deciding how to label and process it."""
        with open(path, 'r', encoding='utf-8-sig') as f:
            model_json = json.load(f)
        return model_json['n_clusters']


class FeatureNormalizer(object):
    """Handles per-file normalize-to-[-1,1] + detrend + feature-weight scaling for inference"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.curve_processor = CurveProcessor()

    def normalize_detrend_and_weight(self, frequencywise_data, feature_weights, unique_frequencies):
        """Per-file, per-feature min-max normalization to [-1, 1] followed by linear detrend
        with feature_weights applied AFTER the normalize+detrend step"""
        n_files, _, n_features = frequencywise_data.shape
        freqs = np.asarray(unique_frequencies)
        feature_weights_array = np.array(feature_weights)

        frequencywise_scaled = np.empty_like(frequencywise_data)
        for file_idx in range(n_files):
            for feature_idx in range(n_features):
                curve = frequencywise_data[file_idx, :, feature_idx]
                normalized = self.curve_processor.normalize_curve_to_range(curve)
                detrended = self.curve_processor.detrend_curve(normalized, freqs)
                frequencywise_scaled[file_idx, :, feature_idx] = (
                    detrended * feature_weights_array[feature_idx]
                )

        return frequencywise_scaled


class ColorGenerator(object):
    """Generates distinct colors for visualization"""

    def __init__(self):
        # Fixed 10-color palette for k values 1-10 (using tab10 colormap)
        self.FIXED_CLUSTER_COLORS = plt.cm.tab10(np.linspace(0, 1, 10))

    def get_cluster_colors(self, k):
        """Get fixed colors for k clusters.
        Returns colors for clusters 0 to k-1.
        Uses the fixed 10-color palette for k<=10, falls back to distinct colors for k>10.
        """
        if k <= 10:
            return self.FIXED_CLUSTER_COLORS[:k]
        return self.generate_distinct_colors(k)

    @staticmethod
    def generate_distinct_colors(n):
        """Generate n visually distinct colors using HSV color space
        For backward compatibility with non-cluster plots.
        """
        if n <= 10:
            colors = plt.cm.tab10(np.linspace(0, 1, n))
        elif n <= 20:
            colors = plt.cm.tab20(np.linspace(0, 1, n))
        else:
            # Use golden ratio for better color distribution
            golden_ratio = (1 + 5**0.5) / 2
            hues = [(i * golden_ratio) % 1.0 for i in range(n)]

            # Generate colors with varying saturation and lightness for better distinction
            colors = []
            for i, hue in enumerate(hues):
                # Alternate between high and medium saturation
                sat = 0.9 if i % 2 == 0 else 0.7
                # Vary lightness to create more distinction
                light = 0.5 + 0.3 * (i % 3) / 2

                rgb = colorsys.hsv_to_rgb(hue, sat, light)
                colors.append(rgb)

            colors = np.array(colors)

        return colors


class FrequencySegmentAvailabilityChecker(object):
    """Checks frequency segment availability in data"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def check_frequency_segments_availability(self, data_list, frequency_segments):
        """Check if all files have frequencies within the defined segments"""
        self.logger.info(f"{'='*60}")
        self.logger.info(f"FREQUENCY SEGMENT ELIGIBILITY CHECK")

        valid_segments = []

        for seg_idx, (freq_min, freq_max) in enumerate(frequency_segments):
            segment_name = f"({freq_min:.2f}, {freq_max:.2f})"
            self.logger.info(f"Validating segment {seg_idx + 1}/{len(frequency_segments)}: {segment_name} Hz")

            files_with_data = 0
            files_without_data = 0

            for file_idx, df in enumerate(data_list):
                frequencies = df['frequency'].values
                segment_frequencies = frequencies[(frequencies >= freq_min) & (frequencies <= freq_max)]

                if len(segment_frequencies) > 0:
                    files_with_data += 1
                else:
                    files_without_data += 1

            self.logger.info(f"  Files with data: {files_with_data}/{len(data_list)}")

            if files_without_data > 0:
                self.logger.error(f"  REJECTED: {files_without_data} file(s) lack data in this segment")
                self.logger.error(f"  Segment {segment_name} rejected")
            else:
                self.logger.info(f"  ACCEPTED: All files have data in this segment")
                valid_segments.append((freq_min, freq_max))
                self.logger.info(f"  Segment {segment_name} validated")

        # Final summary
        self.logger.info(f"{'='*60}")
        self.logger.info(f"FREQUENCY SEGMENT VALIDATION SUMMARY:")
        self.logger.info(f"  Total segments requested: {len(frequency_segments)}")
        self.logger.info(f"  Valid segments: {len(valid_segments)}")
        self.logger.info(f"  Rejected segments: {len(frequency_segments) - len(valid_segments)}")
        self.logger.info(f"{'='*60}")

        if len(valid_segments) == 0:
            self.logger.error(f"  CRITICAL: No valid frequency segments found!")
            error_msg1 = f"  All {len(frequency_segments)} segments were rejected. "
            error_msg2 = f"  Because not all files contain data in those ranges"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        self.logger.info(f"{'='*60}")

        return valid_segments


class SegmentSummaryGenerator(object):
    """Generates final segment summaries"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def generate_final_segment_summary(self, all_segment_summaries, output_dir, head_name=None):
        """Generate final summary CSV with standardized column structure"""
        if not all_segment_summaries:
            self.logger.warning("No segment summaries to save")
            return None

        final_df = pd.DataFrame(all_segment_summaries)

        # STANDARDIZED COLUMN STRUCTURE
        core_columns = ['head', 'frequency_segment']

        # Baseline-separation group column (present only when baseline_data_separation was used)
        optional_group = ['group']

        # Trained-model identification
        optional_model_id = ['model_label', 'original_k', 'is_merged', 'merged_k']

        # File count
        count_columns = ['n_files']

        final_columns = list(core_columns)

        for col in optional_group + optional_model_id:
            if col in final_df.columns:
                final_columns.append(col)

        final_columns += count_columns

        # Add metric score columns and k=1 baseline columns
        for metric in ['ACI1', 'ACI2', 'ACI3', 'ACI4', 'Correlation', 'RMSE', 'Wasserstein']:
            if metric in final_df.columns:
                final_columns.append(metric)
            baseline_metric = f'k1_baseline_{metric}'
            if baseline_metric in final_df.columns:
                final_columns.append(baseline_metric)

        existing_columns = [col for col in final_columns if col in final_df.columns]

        if len(existing_columns) != len(final_columns):
            missing_columns = set(final_columns) - set(existing_columns)
            self.logger.warning(f"Some expected columns are missing: {missing_columns}")
            self.logger.info(f"Available columns: {list(final_df.columns)}")
            self.logger.info(f"Using columns: {existing_columns}")

        final_df = final_df[existing_columns]

        # Sort: segment first, then group if present, then model label
        sort_cols = ['frequency_segment']
        for col in ['group', 'model_label']:
            if col in final_df.columns:
                sort_cols.append(col)
        final_df = final_df.sort_values(sort_cols)

        summary_path = os.path.join(output_dir, f'{head_name}_inference_summary.csv')

        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        final_df.to_csv(summary_path, index=False, encoding='utf-8-sig')
        return summary_path


class BaselineSeparator(object):
    """Classifies inference files into phase_lead/phase_lag/no_resonance groups using each
    file's own normalized+detrended phase dominant peak — fully self-contained, matching
    the training application's frf_clustering_utils.py::BaselineSeparator exactly. No stored
    meanline file or threshold is needed."""

    LESS_RESONANCE_BAND = 0.25

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.curve_processor = CurveProcessor()

    @staticmethod
    def _dominant_peak_value(curve):
        """Return the signed extremum of the curve that deviates furthest from zero."""
        max_value = float(np.max(curve))
        min_value = float(np.min(curve))
        if abs(min_value) > abs(max_value):
            return min_value
        return max_value

    def classify_files(self, segment_file_dict, file_indices):
        """Classify each file as phase_lead, phase_lag, or no_resonance using its
        normalized+detrended dominant peak

        Args:
            segment_file_dict: dict with 'frequencies' and 'files' keys
            file_indices: list of original file indices

        Returns:
            classified: dict with keys 'phase_lead', 'phase_lag', 'no_resonance',
                        each containing a list of original file indices
        """
        classified = {'phase_lead': [], 'phase_lag': [], 'no_resonance': []}
        frequencies = segment_file_dict['frequencies']

        for original_file_idx in file_indices:
            data = segment_file_dict['files'][original_file_idx]
            phase_values = data['phase']

            normalized = self.curve_processor.normalize_curve_to_range(phase_values)
            normalized_detrended = self.curve_processor.detrend_curve(normalized, frequencies)
            peak_value = self._dominant_peak_value(normalized_detrended)

            if abs(peak_value) <= self.LESS_RESONANCE_BAND:
                classified['no_resonance'].append(original_file_idx)
            elif peak_value > 0.0:
                classified['phase_lead'].append(original_file_idx)
            else:
                classified['phase_lag'].append(original_file_idx)

        self.logger.info(f"  Classification results (no-resonance band=+/-{self.LESS_RESONANCE_BAND}):")
        self.logger.info(f"    Phase Lead   : {len(classified['phase_lead'])} files")
        self.logger.info(f"    Phase Lag    : {len(classified['phase_lag'])} files")
        self.logger.info(f"    No Resonance : {len(classified['no_resonance'])} files")

        return classified

    def apply_combination(self, classified, baseline_data_filtering):
        """Merge classified groups according to baseline_data_filtering config, matching
        the training application's BaselineSeparator.apply_combination exactly: an empty
        'no_resonance' single-group entry is skipped, and any combined (list) group that
        resolves to zero files is skipped."""
        groups = {}

        for item in baseline_data_filtering:
            if isinstance(item, str):
                group_files = classified.get(item, [])
                if len(group_files) == 0 and item == 'no_resonance':
                    self.logger.warning(f"Skipping empty group: '{item}'")
                    continue
                groups[item] = group_files

            elif isinstance(item, list):
                label = '_'.join(item)
                combined_files = []
                for group_name in item:
                    combined_files.extend(classified.get(group_name, []))
                if len(combined_files) == 0:
                    self.logger.warning(f"Combined group '{label}' is empty, skipping.")
                    continue
                groups[label] = combined_files
            else:
                self.logger.warning(f"Unexpected item in baseline_data_filtering: {item!r}")

        return groups

    @staticmethod
    def build_group_segment_dict(segment_file_dict, group_original_indices):
        """Build a subset segment_file_dict containing only files from group_original_indices.

        Args:
            segment_file_dict: Full segment file dict
            group_original_indices: List of original file indices for this group

        Returns:
            (group_segment_dict, group_file_indices) tuple
        """
        group_segment_dict = {
            'files': {},
            'frequencies': segment_file_dict['frequencies']
        }

        group_file_indices = []
        for new_idx, original_idx in enumerate(group_original_indices):
            group_segment_dict['files'][new_idx] = segment_file_dict['files'][original_idx]
            group_file_indices.append(new_idx)

        return group_segment_dict, group_file_indices
