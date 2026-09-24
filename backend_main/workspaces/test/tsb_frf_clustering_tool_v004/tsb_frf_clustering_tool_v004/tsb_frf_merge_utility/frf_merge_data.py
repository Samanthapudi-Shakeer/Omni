# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Merging Utility Package
*  File Name: frf_merge_data.py
*  File Description: Standalone GPLOT data loading, 16-feature engineering,
*                    baseline separation and normalize+detrend+weight scaling
*                    for the FRF cluster-merging utility. Self contained -
*                    no dependency on the training application package.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import json
import logging
from io import StringIO

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d


EXPECTED_COLUMNS = ['frequency', 'gain', 'phase']
NO_RESONANCE_BAND = 0.25


def gain_phase_to_complex(gain_db, phase_deg):
    """Convert gain (dB) and phase (degrees) to complex (real, imag) coordinates."""
    magnitude = 10 ** (gain_db / 20)
    phase_rad = np.radians(phase_deg)
    return magnitude * np.cos(phase_rad), magnitude * np.sin(phase_rad)


def load_feature_config(path):
    """Load feature_config.json and return (features_list, feature_weights) to use.

    When both stage1 and stage2 keys are present (hierarchical feature config),
    stage2 features/weights are used exclusively, since flat/combined/merged
    trained models are always expressed in the stage2 feature space. Falls back
    to stage1 keys when stage2 is absent (non-hierarchical feature config).
    """
    with open(path, 'r', encoding='utf-8-sig') as f:
        feature_config = json.load(f)

    stage2_features = feature_config.get('training_application_stage2_features')
    stage2_weights = feature_config.get('training_application_stage2_features_weightages')
    if stage2_features:
        return stage2_features, stage2_weights

    stage1_features = feature_config.get('training_application_stage1_features')
    stage1_weights = feature_config.get('training_application_stage1_features_weightages')
    if not stage1_features:
        raise ValueError(f"feature_config.json at '{path}' has no usable feature list")
    return stage1_features, stage1_weights


class DataFileLoadError(Exception):
    """Raised when a data file list cannot be loaded or contains no valid files."""


class DataFileLoader(object):
    """Loads and validates GPLOT-format data files (.exv, .xpi, .xiz) from a file
    list, with no head-based filtering (every listed file is loaded)."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def load_file_list(self, file_list_path, is_worst_model=False):
        """Load, parse and validate every file referenced by file_list_path.

        Returns:
            data_list: list of pandas.DataFrame (frequency, gain, phase)
            filenames: list of absolute file paths, positionally aligned with data_list
        """
        label = 'worst_model_dir_list' if is_worst_model else 'data_dir_list'
        paths = self._read_file_list(file_list_path)
        self.logger.info(f"Found {len(paths)} data files in {label}")

        data_list, filenames, reference_frequencies, stats = self._load_all_files(paths)
        self._log_summary(label, stats)

        if not data_list:
            error_msg = f"No valid data files could be loaded from {label}: {file_list_path}"
            self.logger.error(error_msg)
            raise DataFileLoadError(error_msg)

        return data_list, filenames

    @staticmethod
    def _read_file_list(file_list_path):
        """Read non-empty lines from a file list."""
        with open(file_list_path, 'r', encoding='utf-8-sig') as f:
            return [line.strip() for line in f if line.strip()]

    def _load_all_files(self, paths):
        """Load and cross-validate every file against the first successfully loaded file."""
        data_list, filenames = [], []
        reference_frequencies, reference_count = None, None
        stats = {'total': len(paths), 'successful': 0, 'rejected': 0}

        for path in paths:
            df = self._load_and_validate_one_file(path, reference_frequencies, reference_count, stats)
            if df is None:
                continue
            if reference_frequencies is None:
                reference_frequencies = df['frequency'].values
                reference_count = len(df)
            data_list.append(df)
            filenames.append(os.path.abspath(path))
            stats['successful'] += 1

        return data_list, filenames, reference_frequencies, stats

    def _load_and_validate_one_file(self, path, reference_frequencies, reference_count, stats):
        """Load one file and validate its structure/content; return None on failure."""
        filename = os.path.basename(path)
        df = self._read_gplot_file(path, filename, stats)
        is_valid = (
            df is not None
            and self._validate_shape_and_content(df, filename, stats)
            and self._validate_against_reference(df, filename, reference_frequencies, reference_count, stats)
        )
        return df if is_valid else None

    def _validate_shape_and_content(self, df, filename, stats):
        """Reject wrong column counts or corrupted/empty content; return False on failure."""
        if df.shape[1] != 3:
            self._reject(filename, f"expected 3 columns, got {df.shape[1]}", stats)
            return False
        df[EXPECTED_COLUMNS] = df[EXPECTED_COLUMNS].apply(pd.to_numeric, errors='coerce')
        if df.isnull().any().any() or len(df) == 0:
            self._reject(filename, "corrupted or empty file", stats)
            return False
        return True

    def _validate_against_reference(self, df, filename, reference_frequencies, reference_count, stats):
        """Validate the frequency grid against the reference file, when one exists."""
        if reference_frequencies is None:
            return True
        if self._matches_reference(df, reference_frequencies, reference_count):
            return True
        self._reject(filename, "frequency grid mismatch vs. reference file", stats)
        return False

    def _read_gplot_file(self, path, filename, stats):
        """Read a GPLOT file up to its 'END' marker and parse the 9-line-header body."""
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                lines = []
                for line in f:
                    if line.strip() == 'END':
                        break
                    lines.append(line)
            return pd.read_csv(
                StringIO(''.join(lines)), skiprows=9, header=None,
                names=EXPECTED_COLUMNS, encoding='utf-8-sig'
            )
        except Exception as e:
            self._reject(filename, f"read error: {e}", stats)
            return None

    @staticmethod
    def _matches_reference(df, reference_frequencies, reference_count):
        """Check row count and frequency grid against the reference file."""
        if len(df) != reference_count:
            return False
        return np.array_equal(df['frequency'].values, reference_frequencies)

    def _reject(self, filename, reason, stats):
        """Log and count a rejected file."""
        stats['rejected'] += 1
        self.logger.warning(f"File '{filename}' rejected: {reason}")

    def _log_summary(self, label, stats):
        """Log a one-line loading summary."""
        self.logger.info(
            f"{label} loading summary: {stats['successful']}/{stats['total']} files loaded "
            f"({stats['rejected']} rejected)"
        )


class SegmentAvailabilityError(Exception):
    """Raised when the requested frequency segment isn't covered by every file."""


def validate_segment_availability(data_list, freq_min, freq_max):
    """Confirm every loaded file has at least one data point inside [freq_min, freq_max]."""
    missing = 0
    for df in data_list:
        frequencies = df['frequency'].values
        in_segment = frequencies[(frequencies >= freq_min) & (frequencies <= freq_max)]
        if len(in_segment) == 0:
            missing += 1
    if missing > 0:
        error_msg = (f"Frequency segment ({freq_min}, {freq_max}) is missing from "
                     f"{missing}/{len(data_list)} file(s)")
        raise SegmentAvailabilityError(error_msg)


class FeatureEngineer(object):
    """Builds the 16-feature-per-file segment dictionary and the (n_files, n_freq,
    n_features) frequencywise array used for clustering."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def build_segment_file_dict(self, data_list, filenames, freq_min, freq_max, num_real_files=None):
        """Collect per-file engineered features within [freq_min, freq_max].

        Returns a dict: {'frequencies': ndarray, 'files': {idx: {feature: ndarray, ...}}}
        with the same 16 engineered-feature keys used across the training pipeline,
        plus 'filename' and 'is_worst_model'.
        """
        segment_file_dict = {'frequencies': None, 'files': {}}
        for idx, df in enumerate(data_list):
            mask = (df['frequency'] >= freq_min) & (df['frequency'] <= freq_max)
            segment_df = df[mask].copy()
            if segment_file_dict['frequencies'] is None:
                segment_file_dict['frequencies'] = segment_df['frequency'].values
            is_worst = num_real_files is not None and idx >= num_real_files
            segment_file_dict['files'][idx] = self._build_file_features(
                segment_df, os.path.basename(filenames[idx]), is_worst
            )
        return segment_file_dict

    def _build_file_features(self, segment_df, filename, is_worst_model):
        """Compute the 16 engineered features for a single file's segment slice."""
        frequency_array = segment_df['frequency'].values
        gain_array = segment_df['gain'].values
        phase_array = segment_df['phase'].values
        real_array, imag_array = self._to_complex_arrays(gain_array, phase_array)

        mag_gain_array = 10 ** (gain_array / 20)
        phase_radian_array = np.radians(phase_array)
        cos_phase_array = np.cos(phase_radian_array)
        sin_phase_array = np.sin(phase_radian_array)
        unwrapped_phase_array = np.unwrap(phase_radian_array)

        slope_mag_gain_array = np.gradient(mag_gain_array, frequency_array)
        slope_unwrapped_phase_array = np.gradient(unwrapped_phase_array, frequency_array)
        curvature_gain_array = np.gradient(slope_mag_gain_array, frequency_array)
        curvature_phase_array = np.gradient(slope_unwrapped_phase_array, frequency_array)

        signed_peak_dev_mag_gain_array, signed_peak_dev_unwrapped_phase_array = \
            self._signed_peak_deviations(mag_gain_array, unwrapped_phase_array)
        mag_ma_diff_array, unwrapped_phase_ma_diff_array = \
            self._moving_average_diffs(mag_gain_array, unwrapped_phase_array)

        return {
            'filename': filename,
            'is_worst_model': is_worst_model,
            'real': real_array, 'imaginary': imag_array,
            'gain': gain_array, 'phase': phase_array, 'frequency': frequency_array,
            'mag_gain': mag_gain_array, 'cos_phase': cos_phase_array, 'sin_phase': sin_phase_array,
            'unwrapped_phase': unwrapped_phase_array,
            'slope_mag_gain': slope_mag_gain_array, 'slope_unwrapped_phase': slope_unwrapped_phase_array,
            'curvature_gain': curvature_gain_array, 'curvature_phase': curvature_phase_array,
            'signed_peak_dev_mag_gain': signed_peak_dev_mag_gain_array,
            'signed_peak_dev_unwrapped_phase': signed_peak_dev_unwrapped_phase_array,
            'moving_magnitude': mag_ma_diff_array, 'moving_unwrapped_phase': unwrapped_phase_ma_diff_array,
        }

    @staticmethod
    def _to_complex_arrays(gain_array, phase_array):
        """Vectorised gain/phase -> (real, imag) conversion for a full segment."""
        real_parts, imag_parts = [], []
        for gain_db, phase_deg in zip(gain_array, phase_array):
            real_part, imag_part = gain_phase_to_complex(gain_db, phase_deg)
            real_parts.append(real_part)
            imag_parts.append(imag_part)
        return np.array(real_parts), np.array(imag_parts)

    @staticmethod
    def _signed_peak_deviations(mag_gain_array, unwrapped_phase_array):
        """Signal minus its local moving-average baseline (window = 10% of length, min 5)."""
        window = max(5, len(mag_gain_array) // 10)
        signed_gain = mag_gain_array - uniform_filter1d(mag_gain_array, size=window)
        signed_phase = unwrapped_phase_array - uniform_filter1d(unwrapped_phase_array, size=window)
        return signed_gain, signed_phase

    @staticmethod
    def _moving_average_diffs(mag_gain_array, unwrapped_phase_array):
        """Consecutive-window moving-average difference (fixed window = 5)."""
        window = 5
        mag_moving_avg = uniform_filter1d(mag_gain_array, size=window)
        phase_moving_avg = uniform_filter1d(unwrapped_phase_array, size=window)
        mag_diff = mag_moving_avg - np.roll(mag_moving_avg, 1)
        phase_diff = phase_moving_avg - np.roll(phase_moving_avg, 1)
        mag_diff[0] = 0
        phase_diff[0] = 0
        return mag_diff, phase_diff

    def build_frequencywise_array(self, segment_file_dict, features_list):
        """Build the (n_files, n_frequencies, n_features) array used for clustering.

        Returns (frequencywise_data, unique_frequencies, file_indices).
        """
        unique_frequencies = segment_file_dict['frequencies']
        n_files = len(segment_file_dict['files'])
        n_frequencies = len(unique_frequencies)
        n_features = len(features_list)

        frequencywise_data = np.zeros((n_files, n_frequencies, n_features))
        file_indices = []
        for file_idx, (original_idx, data) in enumerate(segment_file_dict['files'].items()):
            file_indices.append(original_idx)
            for feature_idx, feature_name in enumerate(features_list):
                frequencywise_data[file_idx, :, feature_idx] = data[feature_name]

        self.logger.info(
            f"Built frequencywise array: files={n_files}, frequencies={n_frequencies}, "
            f"features={n_features} ({features_list})"
        )
        return frequencywise_data, unique_frequencies, file_indices


class BaselineSeparator(object):
    """Classifies files into phase_lead/phase_lag/no_resonance groups from their
    normalized+detrended dominant phase peak, and builds combined-group subsets."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def classify_files(self, segment_file_dict, file_indices):
        """Classify each file's dominant phase-peak direction.

        Returns {'phase_lead': [idx, ...], 'phase_lag': [...], 'no_resonance': [...]}.
        """
        classified = {'phase_lead': [], 'phase_lag': [], 'no_resonance': []}
        frequencies = segment_file_dict['frequencies']
        for original_idx in file_indices:
            phase_values = segment_file_dict['files'][original_idx]['phase']
            peak_value = self._dominant_peak_value(phase_values, frequencies)
            classified[self._classify_peak(peak_value)].append(original_idx)

        self.logger.info(
            f"Baseline classification: phase_lead={len(classified['phase_lead'])}, "
            f"phase_lag={len(classified['phase_lag'])}, no_resonance={len(classified['no_resonance'])}"
        )
        return classified

    @classmethod
    def _dominant_peak_value(cls, phase_values, frequencies):
        """Signed extremum of the normalized-then-detrended phase curve."""
        normalized = cls._normalize_to_range(phase_values)
        detrended = cls._detrend(normalized, frequencies)
        max_value, min_value = float(np.max(detrended)), float(np.min(detrended))
        return min_value if abs(min_value) > abs(max_value) else max_value

    @staticmethod
    def _classify_peak(peak_value):
        """Map a signed peak value to its baseline group name."""
        if abs(peak_value) <= NO_RESONANCE_BAND:
            return 'no_resonance'
        return 'phase_lead' if peak_value > 0.0 else 'phase_lag'

    @staticmethod
    def _normalize_to_range(curve):
        """Min-max normalize a 1-D curve to [-1, 1]."""
        c_min, c_max = np.min(curve), np.max(curve)
        if c_max - c_min < 1e-10:
            return np.zeros_like(curve, dtype=float)
        return 2.0 * (curve - c_min) / (c_max - c_min) - 1.0

    @staticmethod
    def _detrend(curve, frequencies):
        """Remove the linear trend from a 1-D curve."""
        coeffs = np.polyfit(frequencies, curve, 1)
        return curve - np.polyval(coeffs, frequencies)

    @staticmethod
    def expected_group_labels(baseline_data_filtering):
        """Group labels apply_combination() would produce for a given config value."""
        labels = []
        for item in baseline_data_filtering:
            labels.append(item if isinstance(item, str) else '_'.join(item))
        return labels

    def apply_combination(self, classified, baseline_data_filtering):
        """Merge classified groups per baseline_data_filtering into {label: [idx, ...]}."""
        groups = {}
        for item in baseline_data_filtering:
            label, file_ids = self._resolve_group(item, classified)
            if file_ids:
                groups[label] = file_ids
            else:
                self.logger.warning(f"Baseline group '{label}' is empty, skipping.")
        return groups

    @staticmethod
    def _resolve_group(item, classified):
        """Resolve one baseline_data_filtering entry into (label, file_indices)."""
        if isinstance(item, str):
            return item, list(classified.get(item, []))
        label = '_'.join(item)
        combined = []
        for sub_group in item:
            combined.extend(classified.get(sub_group, []))
        return label, combined

    @staticmethod
    def build_group_segment_dict(segment_file_dict, original_indices_subset):
        """Build a re-indexed (0..n-1) segment dict/file_indices for one baseline group."""
        group_dict = {'frequencies': segment_file_dict['frequencies'], 'files': {}}
        group_file_indices = []
        for new_idx, original_idx in enumerate(original_indices_subset):
            group_dict['files'][new_idx] = segment_file_dict['files'][original_idx]
            group_file_indices.append(new_idx)
        return group_dict, group_file_indices


class FeatureScaler(object):
    """Per-file, per-feature normalize-to-[-1,1] + linear detrend + weight scaling —
    the same transform order used across the training pipeline for cluster
    reassignment decisions."""

    @staticmethod
    def normalize_detrend_and_weight(frequencywise_data, feature_weights, unique_frequencies):
        """Scale a (n_files, n_freq, n_features) array in place-equivalent fashion."""
        n_files, _, n_features = frequencywise_data.shape
        freqs = np.asarray(unique_frequencies)
        weights = np.array(feature_weights)

        scaled = np.empty_like(frequencywise_data)
        for file_idx in range(n_files):
            for feature_idx in range(n_features):
                curve = frequencywise_data[file_idx, :, feature_idx]
                normalized = FeatureScaler._normalize_curve(curve)
                detrended = FeatureScaler._detrend_curve(normalized, freqs)
                scaled[file_idx, :, feature_idx] = detrended * weights[feature_idx]
        return scaled

    @staticmethod
    def _normalize_curve(curve):
        """Min-max normalize a 1-D curve to [-1, 1]; all-zero when constant."""
        c_min, c_max = np.min(curve), np.max(curve)
        if c_max - c_min < 1e-10:
            return np.zeros_like(curve)
        return 2.0 * (curve - c_min) / (c_max - c_min) - 1.0

    @staticmethod
    def _detrend_curve(curve, freqs):
        """Remove the linear trend from a 1-D curve."""
        coeffs = np.polyfit(freqs, curve, 1)
        return curve - np.polyval(coeffs, freqs)
