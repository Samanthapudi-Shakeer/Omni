# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_segment_utility.py
*  File Description: Data containers and shared base class for segment processing
*  All rights reserved.
*
*********************************************************************/
"""

import logging
from frf_inference_clustering import FRFInferenceEngine
from frf_inference_utils import BaselineSeparator
from frf_inference_data_utils import FRFDataPreprocessor, PlotExecution


class SegmentFeaturesConfig(object):
    """Container for feature-related parameters"""
    def __init__(self, features_list, feature_weights):
        self.features_list = features_list
        self.feature_weights = feature_weights


class SegmentExtendedConfig(object):
    """Container for optional baseline-separation parameters"""
    def __init__(self, baseline_separation=False, baseline_data_filtering=None):
        self.baseline_separation = baseline_separation
        self.baseline_data_filtering = baseline_data_filtering or []


class SegmentProcessingContext(object):
    """Container for segment processing parameters"""
    def __init__(self, data_list, filenames, freq_min, freq_max, segment_name,
                 segment_key, head_output_dir, head_name, features_config,
                 metrics_to_use, root_dir, extended_config=None):
        self.data_list = data_list
        self.filenames = filenames
        self.freq_min = freq_min
        self.freq_max = freq_max
        self.segment_name = segment_name
        self.segment_key = segment_key
        self.head_output_dir = head_output_dir
        self.head_name = head_name
        self.features_list = features_config.features_list
        self.feature_weights = features_config.feature_weights
        self.metrics_to_use = metrics_to_use
        self.root_dir = root_dir
        # Fields for baseline-separation support
        ext = extended_config if extended_config is not None else SegmentExtendedConfig()
        self.baseline_separation = ext.baseline_separation
        self.baseline_data_filtering = ext.baseline_data_filtering


class ProcessedSegmentData(object):
    """Container for processed segment data"""
    def __init__(self, frequencywise_data, file_indices, unique_frequencies,
                 segment_file_dict, segment_dir, filenames):
        self.frequencywise_data = frequencywise_data
        self.file_indices = file_indices
        self.unique_frequencies = unique_frequencies
        self.segment_file_dict = segment_file_dict
        self.segment_dir = segment_dir
        self.filenames = filenames


class SegmentProcessorBase(object):
    """Base class providing shared infrastructure and helper methods for segment processing"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.preprocessor = FRFDataPreprocessor()
        self.inference_engine = FRFInferenceEngine()
        self.execute_plot = PlotExecution()
        self.baseline_separator = BaselineSeparator()

    def _log_segment_header(self, segment_name):
        """Log segment processing header"""
        self.logger.info("="*60)
        self.logger.info(f"Processing segment: {segment_name}")
        self.logger.info("="*60)

    def _log_metric_header(self, metric):
        """Log metric processing header"""
        self.logger.info(f"  {'='*60}")
        self.logger.info(f"  Processing METRIC: {metric}")
        self.logger.info(f"  {'='*60}")

    def _log_segment_completion(self, freq_min, freq_max):
        """Log segment completion message"""
        self.logger.info("="*60)
        self.logger.info(f"  - Completed inference for segment [{freq_min:.2f}, {freq_max:.2f}] Hz")
        self.logger.info("="*60)

    def _build_k_value_summary(self, head_name, segment_name, k_label, k_value, segment_file_dict,
                               segment_aci_scores, metrics_to_use, group_label=None, is_merged=False,
                               orig_k_value=None):
        """Build summary dictionary for a k value with standardized structure.

        'original_k' always holds the pre-merge cluster count (the count the model had
        before any merge was applied); when no merge was used this is simply k_value.
        'merged_k' is a convenience column that repeats the merged model's actual
        cluster count only when a merge was used, so it can be scanned/filtered
        directly without cross-referencing 'is_merged'.
        """
        original_k = orig_k_value if is_merged and orig_k_value is not None else k_value
        summary = {
            'head': head_name,
            'frequency_segment': segment_name,
            'model_label': k_label,
            'original_k': original_k,
            'is_merged': is_merged,
            'merged_k': k_value if is_merged else None,
            'n_files': len(segment_file_dict['files'])
        }

        if group_label is not None:
            summary['group'] = group_label

        # Add metric scores
        self._add_metric_scores_to_summary(summary, segment_aci_scores, k_label, metrics_to_use)

        # Add k=1 baseline scores
        self._add_baseline_scores_to_summary(summary, segment_aci_scores, metrics_to_use)

        return summary

    @staticmethod
    def _add_metric_scores_to_summary(summary, segment_aci_scores, k_label, metrics_to_use):
        """Add metric scores to summary based on config"""
        if k_label not in segment_aci_scores:
            return

        scores = segment_aci_scores[k_label]
        metric_mapping = {
            'ACI1': 'avg_aci1',
            'ACI2': 'avg_aci2',
            'ACI3': 'avg_aci3',
            'ACI4': 'avg_aci4',
            'Correlation': 'avg_correlation',
            'RMSE': 'avg_rmse',
            'Wasserstein': 'avg_wasserstein'
        }

        for metric in metrics_to_use:
            if metric in metric_mapping:
                score_key = metric_mapping[metric]
                if score_key in scores:
                    summary[metric] = scores[score_key]

    @staticmethod
    def _add_baseline_scores_to_summary(summary, segment_aci_scores, metrics_to_use):
        """Add k=1 baseline scores to summary"""
        if 1 not in segment_aci_scores:
            return

        baseline_scores = segment_aci_scores[1]
        metric_mapping = {
            'ACI1': ('avg_aci1', 'k1_baseline_ACI1'),
            'ACI2': ('avg_aci2', 'k1_baseline_ACI2'),
            'ACI3': ('avg_aci3', 'k1_baseline_ACI3'),
            'ACI4': ('avg_aci4', 'k1_baseline_ACI4')
        }

        for metric in metrics_to_use:
            if metric in metric_mapping:
                score_key, summary_key = metric_mapping[metric]
                if score_key in baseline_scores:
                    summary[summary_key] = baseline_scores[score_key]
