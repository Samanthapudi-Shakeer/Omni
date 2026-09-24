# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_training_application_processors.py
*  File Description: File containing main processors used in clustering.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import re
import json
import numpy as np
import gc
import logging
from frf_clustering_normal import FRFNormalClusteringEngine
from frf_clustering_hierarchical_s1 import FRFHierarchicalClusteringEngine
from frf_clustering_utils import FRFDataPreprocessor, ModelManager, BaselineSeparator
from frf_clustering_utils import PlotExecutor, FrequencyClusteringConfig, ClusteringOutputOptions
from frf_clustering_base import MODEL_NAME
from frf_utils import HierarchicalStageFeatures, BaselineOptions, HierarchicalFrequencyClusteringConfig
from frf_utils import SegmentClusteringConfig, SegmentContext, SegmentAccumulators
from frf_utils import SegmentModelsContext, ACIOptimalK, CentroidOptimalK


class SegmentProcessor(object):
    """Processor for segmented frequency data clustering"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.preprocessor = FRFDataPreprocessor()
        self.clustering_engine = FRFNormalClusteringEngine()
        self.model_load = ModelManager()
        self.executor = PlotExecutor()
        self.baseline_separator = BaselineSeparator()

    def process_segment(self, data_list, filenames, segments_to_process, output_base_dir,
                        models_context, features_list, feature_weights,
                        cluster_config, dataset_type='train', metrics_to_use=None,
                        output_options=None, baseline_options=None,
                        num_real_files=None):
        """Process frequency segments with TimeSeriesKMeans"""
        if metrics_to_use is None:
            metrics_to_use = ['ACI1', 'ACI2', 'ACI3', 'ACI4']

        models_base_dir = models_context.models_base_dir
        head_name = models_context.head_name
        output_opts = output_options if output_options is not None else ClusteringOutputOptions()
        individual_frequencies_cluster_assignment_plots = \
            output_opts.individual_frequencies_cluster_assignment_plots
        generate_interactive_html_plots = output_opts.generate_interactive_html_plots

        opts = baseline_options if baseline_options is not None else BaselineOptions()
        self.logger.info(f"Processing {dataset_type.upper()} SET: {len(segments_to_process)} frequency segments")

        accumulators = SegmentAccumulators()

        for seg_idx, (freq_min, freq_max) in enumerate(segments_to_process):
            ctx = self._build_segment_context(
                seg_idx, freq_min, freq_max, cluster_config, data_list, filenames,
                features_list, output_base_dir, dataset_type, len(segments_to_process),
                num_real_files=num_real_files
            )

            if not opts.baseline_separation:
                completed = self._process_segment_normal(
                    ctx, models_base_dir, head_name, features_list, feature_weights, dataset_type,
                    metrics_to_use, individual_frequencies_cluster_assignment_plots, accumulators,
                    generate_interactive_html_plots
                )
            else:
                completed = self._process_segment_baseline(
                    ctx, models_base_dir, head_name, features_list, feature_weights,
                    dataset_type, metrics_to_use, individual_frequencies_cluster_assignment_plots,
                    opts, accumulators, generate_interactive_html_plots
                )

            if completed:
                self._log_segment_footer(freq_min, freq_max)

        return (accumulators.summaries, accumulators.model_registry,
                accumulators.optimal_info, accumulators.merged_model_registry)

    def _build_segment_context(self, seg_idx, freq_min, freq_max, cluster_config,
                                data_list, filenames, features_list, output_base_dir,
                                dataset_type, total_segments, num_real_files=None):
        """Collect data and build a SegmentContext for one frequency segment."""
        segment_key = (freq_min, freq_max)
        target_k = cluster_config[segment_key]
        self._log_segment_header(seg_idx, total_segments, dataset_type, freq_min, freq_max)
        segment_name = f"{freq_min:.2f}_{freq_max:.2f}Hz"
        segment_dir = os.path.join(output_base_dir, f'segment_{segment_name}')
        os.makedirs(segment_dir, exist_ok=True)
        segment_file_dict = self.preprocessor.collect_segment_data_for_frequencywise_clustering(
            data_list, filenames, freq_min, freq_max, num_real_files=num_real_files
        )
        self.logger.info(f"  Collected data from {len(segment_file_dict['files'])} files")
        frequencywise_data, unique_frequencies, file_indices = \
            self.preprocessor.create_frequencywise_array(segment_file_dict, features_list, segment_name)
        self._log_array_info(frequencywise_data, unique_frequencies)
        return SegmentContext(segment_name, segment_dir, freq_min, freq_max, target_k,
                            segment_file_dict, frequencywise_data, file_indices, unique_frequencies)

    def _process_segment_normal(self, ctx, models_base_dir, head_name, features_list, feature_weights,
                                dataset_type, metrics_to_use,
                                individual_frequencies_cluster_assignment_plots, accumulators,
                                generate_interactive_html_plots=True):
        """Run the standard (no baseline) clustering path for one segment.
        Returns True if the segment footer should be logged, False if skipped.
        """
        self._create_initial_3d_visualization(
            ctx.segment_file_dict, ctx.segment_name, ctx.segment_dir, dataset_type, head_name,
            generate_interactive_html_plots=generate_interactive_html_plots
        )
        pretrained_models = self._get_pretrained_models(
            dataset_type, ctx.target_k, models_base_dir, head_name, ctx.segment_name
        )
        if self._should_skip_validation_segment(dataset_type, pretrained_models, ctx.segment_name):
            return False

        config = SegmentClusteringConfig(
            segment_name=ctx.segment_name, segment_dir=ctx.segment_dir,
            models_base_dir=models_base_dir, head_name=head_name,
            freq_min=ctx.freq_min, freq_max=ctx.freq_max,
            feature_weights=feature_weights, dataset_type=dataset_type,
            metrics_to_use=metrics_to_use,
            output_options=ClusteringOutputOptions(
                individual_frequencies_cluster_assignment_plots=individual_frequencies_cluster_assignment_plots,
                generate_segment_overview=True, output_dir_is_final=False,
                generate_interactive_html_plots=generate_interactive_html_plots
            ),
            features_list=features_list
        )
        clustering_results = self._perform_segment_clustering(
            ctx.frequencywise_data, ctx.file_indices, ctx.unique_frequencies,
            ctx.segment_file_dict, config, pretrained_models, ctx.target_k
        )
        if not clustering_results.get('clustering_results'):
            self.logger.warning(f"  Segment {ctx.segment_name} was skipped - no clustering results")
            self._cleanup_segment_data(ctx.segment_file_dict, ctx.frequencywise_data)
            return False

        results = clustering_results.get('clustering_results')
        trained_models = clustering_results.get('trained_models')
        opt_k_aci1 = clustering_results.get('opt_k_aci1', 1)
        opt_k_aci2 = clustering_results.get('opt_k_aci2', 1)
        opt_k_aci3 = clustering_results.get('opt_k_aci3', 1)
        opt_k_aci4 = clustering_results.get('opt_k_aci4', 1)
        opt_k_correlation = clustering_results.get('opt_k_correlation')
        opt_k_rmse = clustering_results.get('opt_k_rmse')
        opt_k_wasserstein = clustering_results.get('opt_k_wasserstein')
        model_registry_info = clustering_results.get('model_registry_info', [])
        merged_model_registry_info = clustering_results.get('merged_model_registry_info', [])
        optimal_k_info = clustering_results.get('optimal_k_info')
        segment_aci_scores = clustering_results.get('segment_aci_scores', {})
        centroid_scores = clustering_results.get('centroid_scores', {})
        self._collect_train_outputs(dataset_type, optimal_k_info, model_registry_info,
                                    accumulators.optimal_info, accumulators.model_registry)
        if dataset_type == 'train' and merged_model_registry_info:
            accumulators.merged_model_registry.extend(merged_model_registry_info)
        self._finalize_segment(results, ctx.segment_name, dataset_type, ctx.unique_frequencies,
                            ctx.segment_file_dict, ACIOptimalK(opt_k_aci1, opt_k_aci2, opt_k_aci3, opt_k_aci4),
                            segment_aci_scores, metrics_to_use, accumulators.summaries,
                            centroid_optimal_k=CentroidOptimalK(
                                opt_k_correlation, opt_k_rmse, opt_k_wasserstein),
                            centroid_scores=centroid_scores)
        self._cleanup_segment_data(ctx.segment_file_dict, ctx.frequencywise_data, results,
                                trained_models if dataset_type == 'train' else pretrained_models)
        return True

    def _process_segment_baseline(self, ctx, models_base_dir, head_name, features_list,
                                feature_weights, dataset_type, metrics_to_use,
                                individual_frequencies_cluster_assignment_plots,
                                opts, accumulators, generate_interactive_html_plots=True):
        """Run the baseline-separation clustering path for one segment.
        Returns True if the segment footer should be logged, False if validation fails.
        """
        dataset_dir = os.path.join(ctx.segment_dir, dataset_type)
        os.makedirs(dataset_dir, exist_ok=True)
        self._create_initial_3d_visualization(
            ctx.segment_file_dict, ctx.segment_name, ctx.segment_dir, dataset_type, head_name,
            target_dir=dataset_dir,
            generate_interactive_html_plots=generate_interactive_html_plots
        )
        self.executor.execute_plot_in_process(
            self.clustering_engine.plot_overview.create_segment_overview_analysis,
            ctx.segment_file_dict, ctx.segment_name, dataset_dir, head_name
        )
        classified = self.baseline_separator.classify_files(
            ctx.segment_file_dict, ctx.file_indices
        )

        self.executor.execute_plot_in_process(
            self.clustering_engine.plot_overview.create_baseline_group_separation_plot,
            ctx.segment_file_dict, classified, ctx.segment_name, dataset_dir, head_name,
            self.baseline_separator.LESS_RESONANCE_BAND
        )

        groups = self.baseline_separator.apply_combination(classified, opts.baseline_combination)
        for group_label, group_original_indices in groups.items():
            self.logger.info("="*60)
            self.logger.info(f"  Processing group '{group_label}' ({len(group_original_indices)} files)")
            self.logger.info("="*60)
            if len(group_original_indices) == 0:
                self.logger.warning(f"  Group '{group_label}' is empty, skipping.")
                continue
            self._process_baseline_group(
                group_label, group_original_indices, ctx, models_base_dir, head_name,
                features_list, feature_weights, dataset_type, metrics_to_use,
                individual_frequencies_cluster_assignment_plots, accumulators,
                generate_interactive_html_plots
            )

        self._cleanup_segment_data(ctx.segment_file_dict, ctx.frequencywise_data)
        return True

    def _process_baseline_group(self, group_label, group_original_indices, ctx,
                                models_base_dir, head_name, features_list, feature_weights,
                                dataset_type, metrics_to_use,
                                individual_frequencies_cluster_assignment_plots, accumulators,
                                generate_interactive_html_plots=True):
        """Run clustering for one baseline group within a segment."""
        dataset_dir = os.path.join(ctx.segment_dir, dataset_type)
        group_segment_dict, group_file_indices = self.baseline_separator.build_group_segment_dict(
            ctx.segment_file_dict, group_original_indices
        )
        group_frequencywise_data, _, _ = self.preprocessor.create_frequencywise_array(
            group_segment_dict, features_list, ctx.segment_name
        )
        group_dir = os.path.join(dataset_dir, group_label)
        os.makedirs(group_dir, exist_ok=True)
        self._create_initial_3d_visualization(
            group_segment_dict, ctx.segment_name, group_dir, dataset_type, head_name,
            target_dir=group_dir,
            generate_interactive_html_plots=generate_interactive_html_plots
        )
        pretrained_models = self._get_pretrained_models(
            dataset_type, ctx.target_k, models_base_dir, head_name, ctx.segment_name,
            group_label=group_label
        )
        if self._should_skip_validation_segment(dataset_type, pretrained_models, ctx.segment_name):
            return

        group_config = SegmentClusteringConfig(
            segment_name=ctx.segment_name, segment_dir=group_dir,
            models_base_dir=models_base_dir, head_name=head_name,
            freq_min=ctx.freq_min, freq_max=ctx.freq_max,
            feature_weights=feature_weights, dataset_type=dataset_type,
            metrics_to_use=metrics_to_use,
            output_options=ClusteringOutputOptions(
                individual_frequencies_cluster_assignment_plots=individual_frequencies_cluster_assignment_plots,
                generate_segment_overview=False, output_dir_is_final=True, group_label=group_label,
                generate_interactive_html_plots=generate_interactive_html_plots
            ),
            features_list=features_list
        )
        clustering_results = self._perform_segment_clustering(
            group_frequencywise_data, group_file_indices, ctx.unique_frequencies,
            group_segment_dict, group_config, pretrained_models, ctx.target_k
        )
        if not clustering_results.get('clustering_results'):
            self.logger.warning(f"  Group '{group_label}' in segment {ctx.segment_name} was skipped")
            self._cleanup_segment_data(group_segment_dict, group_frequencywise_data)
            return

        results = clustering_results.get('clustering_results')
        trained_models = clustering_results.get('trained_models')
        opt_k_aci1 = clustering_results.get('opt_k_aci1', 1)
        opt_k_aci2 = clustering_results.get('opt_k_aci2', 1)
        opt_k_aci3 = clustering_results.get('opt_k_aci3', 1)
        opt_k_aci4 = clustering_results.get('opt_k_aci4', 1)
        opt_k_correlation = clustering_results.get('opt_k_correlation')
        opt_k_rmse = clustering_results.get('opt_k_rmse')
        opt_k_wasserstein = clustering_results.get('opt_k_wasserstein')
        model_registry_info = clustering_results.get('model_registry_info', [])
        merged_model_registry_info = clustering_results.get('merged_model_registry_info', [])
        optimal_k_info = clustering_results.get('optimal_k_info')
        segment_aci_scores = clustering_results.get('segment_aci_scores', {})
        centroid_scores = clustering_results.get('centroid_scores', {})
        if model_registry_info:
            for entry in model_registry_info:
                entry['group'] = group_label
        if optimal_k_info:
            optimal_k_info['group'] = group_label
        if dataset_type == 'train' and merged_model_registry_info:
            accumulators.merged_model_registry.extend(merged_model_registry_info)
        self._collect_train_outputs(dataset_type, optimal_k_info, model_registry_info,
                                    accumulators.optimal_info, accumulators.model_registry)
        self._finalize_segment(results, ctx.segment_name, dataset_type, ctx.unique_frequencies,
                            group_segment_dict, ACIOptimalK(opt_k_aci1, opt_k_aci2, opt_k_aci3, opt_k_aci4),
                            segment_aci_scores, metrics_to_use, accumulators.summaries,
                            group_label=group_label,
                            centroid_optimal_k=CentroidOptimalK(
                                opt_k_correlation, opt_k_rmse, opt_k_wasserstein),
                            centroid_scores=centroid_scores)
        self._cleanup_segment_data(group_segment_dict, group_frequencywise_data, results,
                                trained_models if dataset_type == 'train' else pretrained_models)

    def _should_skip_validation_segment(self, dataset_type, pretrained_models, segment_name):
        if dataset_type.startswith('validation') and not pretrained_models:
            self.logger.warning(f"  No pretrained models found for segment {segment_name}")
            return True
        return False

    @staticmethod
    def _collect_train_outputs(dataset_type, optimal_k_info, model_registry_info,
                            all_optimal_k_info, all_model_registry):
        if dataset_type == 'train':
            if optimal_k_info:
                all_optimal_k_info.append(optimal_k_info)
            if model_registry_info:
                all_model_registry.extend(model_registry_info)

    def _finalize_segment(self, results, segment_name, dataset_type, unique_frequencies,
                        segment_file_dict, aci_optimal_k, segment_aci_scores, metrics_to_use,
                        all_segment_summaries, group_label=None, centroid_optimal_k=None,
                        centroid_scores=None):
        if not results:
            return
        centroid_optimal_k = centroid_optimal_k or CentroidOptimalK()

        summary_entry = self._create_segment_summary(
            segment_name, dataset_type, unique_frequencies, segment_file_dict,
            aci_optimal_k, segment_aci_scores, metrics_to_use, group_label=group_label,
            centroid_optimal_k=centroid_optimal_k, centroid_scores=centroid_scores or {}
        )
        all_segment_summaries.append(summary_entry)

        self._log_optimal_k_values(
            aci_optimal_k.aci1, aci_optimal_k.aci2, aci_optimal_k.aci3, aci_optimal_k.aci4,
            metrics_to_use,
            opt_k_correlation=centroid_optimal_k.correlation, opt_k_rmse=centroid_optimal_k.rmse,
            opt_k_wasserstein=centroid_optimal_k.wasserstein
        )

    def _log_segment_header(self, seg_idx, total_segments, dataset_type, freq_min, freq_max):
        """Log segment processing header"""
        self.logger.info("="*60)
        self.logger.info(f"[{dataset_type.upper()}]: Processing segment {seg_idx + 1}/{total_segments}")
        self.logger.info(f"FREQUENCY SEGMENT: {freq_min:.2f}-{freq_max:.2f} Hz")
        self.logger.info("="*60)

    def _log_array_info(self, frequencywise_data, unique_frequencies):
        """Log frequencywise array information"""
        self.logger.info(f"  Time series array created: {frequencywise_data.shape} (Files X Frequencies X Features)")
        self.logger.info(f"  Frequency grid size: {len(unique_frequencies)} unique frequencies")

    def _create_initial_3d_visualization(self, segment_file_dict, segment_name, segment_dir,
                                        dataset_type, head_name, target_dir=None,
                                        generate_interactive_html_plots=True):
        """Create initial 3D visualization.

        Args:
            target_dir: if provided, saves directly here instead of segment_dir/dataset_type/
                        Used during baseline separation to save full-data 3D at segment_dir level.
            generate_interactive_html_plots: if True, also generate the interactive HTML version.
        """
        if target_dir is not None:
            save_dir = target_dir
        else:
            save_dir = os.path.join(segment_dir, dataset_type)
        os.makedirs(save_dir, exist_ok=True)
        self.executor.execute_plot_in_process(
            self.clustering_engine.plot_3d.create_3d_visualization,
            segment_file_dict, segment_name, save_dir, head_name, None, None
        )
        if generate_interactive_html_plots:
            self.executor.execute_plot_in_process(
                self.clustering_engine.plot_3d.create_interactive_3d_visualization,
                segment_file_dict, segment_name, save_dir, head_name
            )

    def _get_pretrained_models(self, dataset_type, target_k, models_base_dir, head_name, segment_name,
                               group_label=None):
        """Get pretrained models for validation.

        When group_label is set, models are loaded from
        <models_base_dir>/<head_name>/<segment_name>/<group_label>/k_<k>/model.json.
        """
        if not dataset_type.startswith('validation'):
            return {}

        self.logger.info(f" Loading pretrained clustering models for segment: {segment_name}")

        segment_models_dir = os.path.join(models_base_dir, head_name, segment_name)
        if group_label:
            segment_models_dir = os.path.join(segment_models_dir, group_label)

        if not os.path.exists(segment_models_dir):
            self.logger.warning(f" Models directory not found: {segment_models_dir}")
            return {}

        return self._load_pretrained_models(segment_models_dir, target_k)

    def _load_pretrained_models(self, segment_models_dir, target_k):
        """Load pretrained models from disk"""
        pretrained_models = {}

        if isinstance(target_k, list):
            k_values_to_load = target_k
        else:
            k_values_to_load = [target_k]

        for k in k_values_to_load:
            k_dir = os.path.join(segment_models_dir, f'k_{k}')
            json_path = os.path.join(k_dir, MODEL_NAME)

            try:
                if os.path.exists(json_path):
                    pretrained_models[k] = self.model_load.load_model(json_path, format='json')
                    self.logger.info(f" Successfully loaded JSON model for k={k} clusters")
                else:
                    self.logger.warning(f" Validation model not loaded for k={k} clusters (not found)")
            except Exception as e:
                self.logger.error(f" Error loading model for k={k}: {e}")

        return pretrained_models

    def _perform_segment_clustering(self, frequencywise_data, file_indices, unique_frequencies,
                                segment_file_dict, seg_config, pretrained_models, target_k):
        """Perform clustering for the segment"""
        # Create FrequencyClusteringConfig from SegmentClusteringConfig
        output_options = ClusteringOutputOptions(
            individual_frequencies_cluster_assignment_plots=seg_config.individual_frequencies_cluster_assignment_plots,
            generate_segment_overview=seg_config.generate_segment_overview,
            output_dir_is_final=seg_config.output_dir_is_final,
            group_label=seg_config.group_label,
            generate_interactive_html_plots=seg_config.generate_interactive_html_plots
        )
        clustering_config = FrequencyClusteringConfig(
            segment_name=seg_config.segment_name,
            segment_dir=seg_config.segment_dir,
            models_base_dir=seg_config.models_base_dir,
            head_name=seg_config.head_name,
            freq_min=seg_config.freq_min,
            freq_max=seg_config.freq_max,
            feature_weights=seg_config.feature_weights,
            dataset_type=seg_config.dataset_type,
            pretrained_models=pretrained_models if seg_config.dataset_type.startswith('validation') else None,
            target_k=target_k,
            metrics_to_use=seg_config.metrics_to_use,
            output_options=output_options,
            features_list=seg_config.features_list
        )

        return self.clustering_engine.perform_frequencywise_clustering(
            frequencywise_data, file_indices, unique_frequencies,
            segment_file_dict, clustering_config
        )

    def _create_segment_summary(self, segment_name, dataset_type, unique_frequencies,
                            segment_file_dict, aci_optimal_k, segment_aci_scores, metrics_to_use,
                            group_label=None, centroid_optimal_k=None, centroid_scores=None):
        """Create segment summary entry"""
        centroid_optimal_k = centroid_optimal_k or CentroidOptimalK()
        summary_entry = {
            'frequency_segment': segment_name,
            'dataset': dataset_type,
            'num_individual_frequencies': len(unique_frequencies),
            'num_files': len(segment_file_dict['files'])
        }

        if group_label is not None:
            summary_entry['group'] = group_label

        # Add ACI metric information
        if 'ACI1' in metrics_to_use:
            summary_entry['optimal_k_ACI1'] = aci_optimal_k.aci1
            summary_entry['ACI1'] = self._get_aci_score(segment_aci_scores, aci_optimal_k.aci1, 'avg_aci1')

        if 'ACI2' in metrics_to_use:
            summary_entry['optimal_k_ACI2'] = aci_optimal_k.aci2
            summary_entry['ACI2'] = self._get_aci_score(segment_aci_scores, aci_optimal_k.aci2, 'avg_aci2')

        if 'ACI3' in metrics_to_use:
            summary_entry['optimal_k_ACI3'] = aci_optimal_k.aci3
            summary_entry['ACI3'] = self._get_aci_score(segment_aci_scores, aci_optimal_k.aci3, 'avg_aci3')

        if 'ACI4' in metrics_to_use:
            summary_entry['optimal_k_ACI4'] = aci_optimal_k.aci4
            summary_entry['ACI4'] = self._get_aci_score(segment_aci_scores, aci_optimal_k.aci4, 'avg_aci4')

        # Add centroid metric information
        centroid_opt_map = {
            'Correlation': ('avg_correlation', centroid_optimal_k.correlation),
            'RMSE': ('avg_rmse', centroid_optimal_k.rmse),
            'Wasserstein': ('avg_wasserstein', centroid_optimal_k.wasserstein),
        }
        cs = centroid_scores or {}
        for metric, (score_key, opt_k) in centroid_opt_map.items():
            if metric in metrics_to_use:
                summary_entry[f'optimal_k_{metric}'] = opt_k
                score = cs.get(opt_k, {}).get(score_key, np.nan) if opt_k else np.nan
                summary_entry[metric] = score

        return summary_entry

    @staticmethod
    def _get_aci_score(segment_aci_scores, optimal_k, score_key):
        """Get ACI score for optimal k"""
        if optimal_k == 1 and 1 in segment_aci_scores:
            return segment_aci_scores[1].get(score_key, np.nan)
        elif optimal_k in segment_aci_scores:
            return segment_aci_scores[optimal_k].get(score_key, np.nan)
        else:
            return np.nan

    def _log_optimal_k_values(self, opt_k_aci1, opt_k_aci2, opt_k_aci3, opt_k_aci4, metrics_to_use,
                               opt_k_correlation=None, opt_k_rmse=None, opt_k_wasserstein=None):
        """Log optimal k values for all active metrics"""
        if 'ACI1' in metrics_to_use:
            self.logger.info(f"  Optimal k (ACI1): {opt_k_aci1}")
        if 'ACI2' in metrics_to_use:
            self.logger.info(f"  Optimal k (ACI2): {opt_k_aci2}")
        if 'ACI3' in metrics_to_use:
            self.logger.info(f"  Optimal k (ACI3): {opt_k_aci3}")
        if 'ACI4' in metrics_to_use:
            self.logger.info(f"  Optimal k (ACI4): {opt_k_aci4}")
        if 'RMSE' in metrics_to_use:
            self.logger.info(f"  Optimal k (RMSE): {opt_k_rmse}")
        if 'Correlation' in metrics_to_use:
            self.logger.info(f"  Optimal k (Correlation): {opt_k_correlation}")
        if 'Wasserstein' in metrics_to_use:
            self.logger.info(f"  Optimal k (Wasserstein): {opt_k_wasserstein}")

    @staticmethod
    def _cleanup_segment_data(segment_file_dict, frequencywise_data,
                            clustering_results=None, models=None):
        """Cleanup segment data"""
        del segment_file_dict, frequencywise_data
        if clustering_results:
            del clustering_results
        if models:
            del models
        gc.collect()

    def _log_segment_footer(self, freq_min, freq_max):
        """Log segment completion footer"""
        self.logger.info("="*60)
        self.logger.info(f"Completed processing for segment [{freq_min:.2f}, {freq_max:.2f}] Hz")
        self.logger.info("="*60)


class HierarchicalSegmentProcessor(object):
    """Processes frequency segments for hierarchical two-stage clustering"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.preprocessor = FRFDataPreprocessor()
        self.clustering_engine = FRFHierarchicalClusteringEngine()
        self.executor = PlotExecutor()
        self.baseline_separator = BaselineSeparator()

    def process_segment_hierarchical(self, data_list, filenames, segments_to_process,
                                    output_base_dir, models_base_dir, head_name, config,
                                    dataset_type='train', num_real_files=None):
        """Process frequency segments with hierarchical two-stage TimeSeriesKMeans"""
        self.logger.info(
            f"Processing {dataset_type.upper()} SET (HIERARCHICAL): "
            f"{len(segments_to_process)} frequency segments")

        baseline_separation = config.get('baseline_data_separation', False)
        baseline_combination = config.get('baseline_data_filtering', None)
        accumulators = SegmentAccumulators()

        for seg_idx, (freq_min, freq_max) in enumerate(segments_to_process):
            ctx = self._build_hierarchical_segment_context(
                seg_idx, freq_min, freq_max, config, data_list, filenames,
                output_base_dir, dataset_type, len(segments_to_process),
                num_real_files=num_real_files
            )

            if not baseline_separation:
                completed = self._process_hierarchical_segment_normal(
                    ctx, models_base_dir, head_name, config, dataset_type, accumulators
                )
            else:
                completed = self._process_hierarchical_segment_baseline(
                    ctx, models_base_dir, head_name, config, dataset_type,
                    baseline_combination, accumulators
                )

            del ctx.segment_file_dict, ctx.frequencywise_data
            gc.collect()

            if completed:
                self.logger.info("="*60)
                self.logger.info(
                    f"Completed hierarchical processing for segment [{freq_min:.2f}, {freq_max:.2f}] Hz")

        return (accumulators.summaries, accumulators.model_registry,
                accumulators.optimal_info, accumulators.merged_model_registry)

    def _build_hierarchical_segment_context(self, seg_idx, freq_min, freq_max, config,
                                            data_list, filenames, output_base_dir,
                                            dataset_type, total_segments, num_real_files=None):
        """Collect data and build a SegmentContext for one hierarchical frequency segment."""
        segment_key = (freq_min, freq_max)
        target_k = config['no_of_clusters_for_each_segment'][segment_key]
        self.logger.info("="*60)
        self.logger.info(
            f"[HIERARCHICAL {dataset_type.upper()}]: Segment {seg_idx+1}/{total_segments}")
        self.logger.info(f"FREQUENCY SEGMENT: {freq_min:.2f}-{freq_max:.2f} Hz")
        self.logger.info("="*60)
        segment_name = f"{freq_min:.2f}_{freq_max:.2f}Hz"
        segment_dir = os.path.join(output_base_dir, f'segment_{segment_name}')
        os.makedirs(segment_dir, exist_ok=True)
        segment_file_dict = self.preprocessor.collect_segment_data_for_frequencywise_clustering(
            data_list, filenames, freq_min, freq_max, num_real_files=num_real_files
        )
        self.logger.info(f"  Collected data from {len(segment_file_dict['files'])} files")
        frequencywise_data_s1, unique_frequencies, file_indices = \
            self.preprocessor.create_frequencywise_array(
                segment_file_dict, config['training_application_stage1_features'], segment_name
            )
        self.logger.info(
            f"  Stage 1 array: {frequencywise_data_s1.shape} (Files X Frequencies X Features)")
        return SegmentContext(segment_name, segment_dir, freq_min, freq_max, target_k,
                            segment_file_dict, frequencywise_data_s1, file_indices, unique_frequencies)

    @staticmethod
    def _build_hier_config(ctx, models_base_dir, head_name, config, dataset_type,
                            segment_dir=None, generate_segment_overview=True,
                            output_dir_is_final=False, group_label=None):
        """Build a HierarchicalFrequencyClusteringConfig for a segment or group."""
        stage_features = HierarchicalStageFeatures(
            stage1_features=config['training_application_stage1_features'],
            stage1_feature_weights=config['training_application_stage1_features_weightages'],
            stage2_features=config['training_application_stage2_features'],
            stage2_feature_weights=config['training_application_stage2_features_weightages']
        )
        output_options = ClusteringOutputOptions(
            individual_frequencies_cluster_assignment_plots=config[
                'individual_frequencies_cluster_assignment_plots'],
            generate_segment_overview=generate_segment_overview,
            output_dir_is_final=output_dir_is_final,
            group_label=group_label,
            generate_interactive_html_plots=config['generate_interactive_html_plots']
        )
        return HierarchicalFrequencyClusteringConfig(
            segment_name=ctx.segment_name,
            segment_dir=segment_dir if segment_dir is not None else ctx.segment_dir,
            models_base_dir=models_base_dir, head_name=head_name,
            freq_min=ctx.freq_min, freq_max=ctx.freq_max,
            stage_features=stage_features,
            feature_weights=config['training_application_stage1_features_weightages'],
            dataset_type=dataset_type, target_k=ctx.target_k,
            metrics_to_use=config['metric'], output_options=output_options
        )

    def _process_hierarchical_segment_normal(self, ctx, models_base_dir, head_name,
                                            config, dataset_type, accumulators):
        """Run the standard (no baseline) hierarchical path for one segment.
        Returns True if the segment footer should be logged, False if clustering failed.
        """
        dataset_dir = os.path.join(ctx.segment_dir, dataset_type)
        os.makedirs(dataset_dir, exist_ok=True)
        self.executor.execute_plot_in_process(
            self.clustering_engine.plot_3d.create_3d_visualization,
            ctx.segment_file_dict, ctx.segment_name, dataset_dir, head_name, None, None
        )
        if config['generate_interactive_html_plots']:
            self.executor.execute_plot_in_process(
                self.clustering_engine.plot_3d.create_interactive_3d_visualization,
                ctx.segment_file_dict, ctx.segment_name, dataset_dir, head_name
            )
        hier_config = self._build_hier_config(
            ctx, models_base_dir, head_name, config, dataset_type,
            generate_segment_overview=True, output_dir_is_final=False
        )
        try:
            opt_dict, opt_scores, winning_combinations = \
                self.clustering_engine.perform_hierarchical_clustering(
                    ctx.frequencywise_data, ctx.file_indices, ctx.unique_frequencies,
                    ctx.segment_file_dict, hier_config
                )
        except Exception as e:
            self.logger.error(f"  Hierarchical clustering failed for segment {ctx.segment_name}: {e}")
            return False

        self._append_hierarchical_summary(
            accumulators.summaries, ctx.segment_name, dataset_type,
            ctx.unique_frequencies, ctx.segment_file_dict, opt_dict, opt_scores, config
        )
        if dataset_type == 'train':
            accumulators.optimal_info.append({
                'head_name': head_name,
                'segment_tuple': (ctx.freq_min, ctx.freq_max),
                'segment_name': ctx.segment_name,
                'models_base_dir': models_base_dir,
                'winning_combinations': winning_combinations
            })
            accumulators.model_registry.extend(
                self._collect_hierarchical_combined_model_registry(
                    models_base_dir, head_name, ctx.segment_name)
            )
            accumulators.merged_model_registry.extend(
                self._collect_hierarchical_merged_model_registry(
                    models_base_dir, head_name, ctx.segment_name)
            )
        return True

    def _process_hierarchical_segment_baseline(self, ctx, models_base_dir, head_name,
                                                config, dataset_type, baseline_combination, accumulators):
        """Run the baseline-separation hierarchical path for one segment.
        Returns True if the segment footer should be logged, False if validation fails.
        """
        dataset_dir = os.path.join(ctx.segment_dir, dataset_type)
        os.makedirs(dataset_dir, exist_ok=True)
        self.executor.execute_plot_in_process(
            self.clustering_engine.plot_3d.create_3d_visualization,
            ctx.segment_file_dict, ctx.segment_name, dataset_dir, head_name, None, None
        )
        if config['generate_interactive_html_plots']:
            self.executor.execute_plot_in_process(
                self.clustering_engine.plot_3d.create_interactive_3d_visualization,
                ctx.segment_file_dict, ctx.segment_name, dataset_dir, head_name
            )
        success, overview_result = self.executor.execute_plot_in_process(
            self.clustering_engine.plot_overview.create_segment_overview_analysis,
            ctx.segment_file_dict, ctx.segment_name, dataset_dir, head_name
        )
        if not success or overview_result is False:
            self.logger.warning(
                f"  Full-data segment overview generation failed for segment {ctx.segment_name}. "
                f"Group-level processing will continue."
            )
        classified = self.baseline_separator.classify_files(
            ctx.segment_file_dict, ctx.file_indices
        )

        self.executor.execute_plot_in_process(
            self.clustering_engine.plot_overview.create_baseline_group_separation_plot,
            ctx.segment_file_dict, classified, ctx.segment_name, dataset_dir, head_name,
            self.baseline_separator.LESS_RESONANCE_BAND
        )

        groups = self.baseline_separator.apply_combination(classified, baseline_combination)
        for group_label, group_original_indices in groups.items():
            self.logger.info("="*60)
            self.logger.info(
                f"  [HIERARCHICAL] Processing group '{group_label}' ({len(group_original_indices)} files)")
            self.logger.info("="*60)
            if len(group_original_indices) == 0:
                self.logger.warning(f"  Group '{group_label}' is empty, skipping.")
                continue
            self._process_hierarchical_group(
                group_label, group_original_indices, ctx,
                models_base_dir, head_name, config, dataset_type, accumulators
            )
        return True

    def _process_hierarchical_group(self, group_label, group_original_indices, ctx,
                                    models_base_dir, head_name, config,
                                    dataset_type, accumulators):
        """Run hierarchical clustering for one baseline group within a segment."""
        dataset_dir = os.path.join(ctx.segment_dir, dataset_type)
        group_segment_dict, group_file_indices = self.baseline_separator.build_group_segment_dict(
            ctx.segment_file_dict, group_original_indices
        )
        group_frequencywise_data_s1, _, _ = self.preprocessor.create_frequencywise_array(
            group_segment_dict, config['training_application_stage1_features'], ctx.segment_name
        )
        group_dir = os.path.join(dataset_dir, group_label)
        os.makedirs(group_dir, exist_ok=True)
        self.executor.execute_plot_in_process(
            self.clustering_engine.plot_3d.create_3d_visualization,
            group_segment_dict, ctx.segment_name, group_dir, head_name, None, None
        )
        if config['generate_interactive_html_plots']:
            self.executor.execute_plot_in_process(
                self.clustering_engine.plot_3d.create_interactive_3d_visualization,
                group_segment_dict, ctx.segment_name, group_dir, head_name
            )
        hier_config = self._build_hier_config(
            ctx, models_base_dir, head_name, config, dataset_type,
            segment_dir=group_dir, generate_segment_overview=False,
            output_dir_is_final=True, group_label=group_label
        )
        try:
            opt_dict, opt_scores, winning_combinations = \
                self.clustering_engine.perform_hierarchical_clustering(
                    group_frequencywise_data_s1, group_file_indices, ctx.unique_frequencies,
                    group_segment_dict, hier_config
                )
        except Exception as e:
            self.logger.error(
                f"  Hierarchical clustering failed for group '{group_label}' "
                f"in segment {ctx.segment_name}: {e}")
            del group_segment_dict, group_frequencywise_data_s1
            gc.collect()
            return

        self._append_hierarchical_summary(
            accumulators.summaries, ctx.segment_name, dataset_type,
            ctx.unique_frequencies, group_segment_dict, opt_dict, opt_scores, config,
            group_label=group_label
        )
        if dataset_type == 'train':
            accumulators.optimal_info.append({
                'head_name': head_name,
                'segment_tuple': (ctx.freq_min, ctx.freq_max),
                'segment_name': ctx.segment_name,
                'models_base_dir': models_base_dir,
                'winning_combinations': winning_combinations,
                'group': group_label
            })
            accumulators.model_registry.extend(
                self._collect_hierarchical_combined_model_registry(
                    models_base_dir, head_name, ctx.segment_name, group_label=group_label)
            )
            accumulators.merged_model_registry.extend(
                self._collect_hierarchical_merged_model_registry(
                    models_base_dir, head_name, ctx.segment_name, group_label=group_label)
            )
        del group_segment_dict, group_frequencywise_data_s1
        gc.collect()

    @staticmethod
    def _append_hierarchical_summary(all_segment_summaries, segment_name, dataset_type,
                                  unique_frequencies, segment_file_dict,
                                  opt_dict, opt_scores, config, group_label=None):
        """Build and append a summary entry for a hierarchical segment or group"""
        summary_entry = {
            'frequency_segment': segment_name,
            'dataset': dataset_type,
            'num_individual_frequencies': len(unique_frequencies),
            'num_files': len(segment_file_dict['files'])
        }
        if group_label is not None:
            summary_entry['group'] = group_label
        metric_lower_map = {
            'ACI1': 'aci1', 'ACI2': 'aci2', 'ACI3': 'aci3', 'ACI4': 'aci4',
            'Correlation': 'correlation', 'RMSE': 'rmse', 'Wasserstein': 'wasserstein',
        }
        for metric in config['metric']:
            mk = metric_lower_map.get(metric)
            if mk:
                summary_entry[f'optimal_k_{metric}'] = opt_dict.get(mk, 1)
                summary_entry[metric] = opt_scores.get(mk, np.nan)
        all_segment_summaries.append(summary_entry)

    @staticmethod
    def _collect_hierarchical_combined_model_registry(models_base_dir, head_name, segment_name,
                                                        group_label=None):
        """Scan trained models directory and collect flat single-stage 'combined' model
        registry entries for one segment.

        Walks every h_combined/*/model.json — each is one flat, single-stage
        consolidated model for a (parent_k, stage2_k) combination, the same entry shape
        as a merged model — so hierarchical training now registers exactly the same
        kind of flat model as normal (non-hierarchical) training, with no nested
        stage1/stage2 structure in the output config.
        """
        segment_base = os.path.join(models_base_dir, head_name, segment_name)
        segment_models_dir = os.path.join(segment_base, group_label) if group_label else segment_base

        h_combined_dir = os.path.join(segment_models_dir, 'h_combined')
        if not os.path.isdir(h_combined_dir):
            return []

        return HierarchicalSegmentProcessor._collect_combined_combo_entries(
            h_combined_dir, head_name, segment_name, group_label
        )

    @staticmethod
    def _collect_combined_combo_entries(h_combined_dir, head_name, segment_name, group_label):
        """Collect combined model.json entries from the h_combined/ directory."""
        entries = []
        for combo_item in sorted(os.listdir(h_combined_dir)):
            combo_dir = os.path.join(h_combined_dir, combo_item)
            model_path = os.path.join(combo_dir, MODEL_NAME)
            if not (os.path.isdir(combo_dir) and os.path.exists(model_path)):
                continue
            entry = {
                'head_name': head_name,
                'segment': segment_name,
                'trained_model_path': os.path.abspath(model_path),
            }
            cluster_count = HierarchicalSegmentProcessor._parse_combined_combo_cluster_count(combo_item)
            if cluster_count is not None:
                entry['cluster_count'] = cluster_count
            if group_label is not None:
                entry['group'] = group_label
            merged_cluster_count, merged_model_path = \
                HierarchicalSegmentProcessor._find_merged_combo_info(h_combined_dir, combo_item)
            entry['merged_cluster_count'] = merged_cluster_count
            entry['merged_model_path'] = merged_model_path
            entries.append(entry)
        return entries

    @staticmethod
    def _parse_combined_combo_cluster_count(combo_item):
        """Parse total cluster count (parent_k * stage2_k) from a
        'stage1_k_{parent_k}_stage2_k_{stage2_k}' combo directory name, so combined
        registry entries carry the same 'cluster_count' field as normal single-stage
        entries. Returns None if the name doesn't match the expected pattern."""
        match = re.match(r'stage1_k_(\d+)_stage2_k_(\d+)$', combo_item)
        if not match:
            return None
        parent_k, stage2_k = int(match.group(1)), int(match.group(2))
        return parent_k * stage2_k

    @staticmethod
    def _find_merged_combo_info(h_combined_dir, combo_item):
        """Look up the 'merged' model nested inside a combined combo's own folder, if
        that (parent_k, stage2_k) combination was actually merged (see
        _resolve_hierarchical_merged_models_dir). Returns (merged_cluster_count,
        merged_model_path), both None when no merge was performed for this
        combination."""
        merged_model_path = os.path.join(
            h_combined_dir, combo_item, 'merged', MODEL_NAME
        )
        if not os.path.exists(merged_model_path):
            return None, None
        try:
            with open(merged_model_path, 'r', encoding='utf-8-sig') as f:
                merged_model_json = json.load(f)
            return merged_model_json.get('n_clusters'), os.path.abspath(merged_model_path)
        except (OSError, ValueError):
            return None, None

    @staticmethod
    def _collect_hierarchical_merged_model_registry(models_base_dir, head_name, segment_name,
                                                     group_label=None):
        """Scan trained models directory and collect post-merge (consolidated) registry entries.

        Walks every h_combined/*/merged/model.json — each is one flat consolidated model for
        a (parent_k, stage2_k) combination that merged.
        """
        segment_base = os.path.join(models_base_dir, head_name, segment_name)
        segment_models_dir = os.path.join(segment_base, group_label) if group_label else segment_base

        h_combined_dir = os.path.join(segment_models_dir, 'h_combined')
        if not os.path.isdir(h_combined_dir):
            return []

        return HierarchicalSegmentProcessor._collect_merged_combo_entries(
            h_combined_dir, head_name, segment_name, group_label
        )

    @staticmethod
    def _collect_merged_combo_entries(h_combined_dir, head_name, segment_name, group_label):
        """Collect merged model.json entries from every combo's nested 'merged/' folder
        under h_combined/."""
        entries = []
        for combo_item in sorted(os.listdir(h_combined_dir)):
            merged_dir = os.path.join(h_combined_dir, combo_item, 'merged')
            model_path = os.path.join(merged_dir, MODEL_NAME)
            if not (os.path.isdir(merged_dir) and os.path.exists(model_path)):
                continue
            entry = {
                'head_name': head_name,
                'segment': segment_name,
                'trained_model_path': os.path.abspath(model_path),
            }
            if group_label is not None:
                entry['group'] = group_label
            entries.append(entry)
        return entries
