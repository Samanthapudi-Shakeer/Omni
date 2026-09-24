# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_clustering_normal.py
*  File Description: Normal (flat) TimeSeriesKMeans clustering engine.
*  All rights reserved.
*
*********************************************************************/
"""

import os
from frf_clustering_utils import FrequencyACIMetricsConfig, FrequencywiseNormData, NormalRunAccumulators
from frf_clustering_utils import MergeContext, MergeFileData, MergeModelSettings
from frf_clustering_base import FRFClusteringBase
from frf_centroid_metrics import CENTROID_METRIC_NAMES


class FRFNormalClusteringEngine(FRFClusteringBase):
    """Handles standard (flat) clustering execution, model management, and plot generation"""

    def perform_frequencywise_clustering(self, frequencywise_data, file_indices,
    unique_frequencies, segment_file_dict, config):
        """Perform TimeSeriesKMeans clustering"""
        setup = self._setup_clustering_run(
            frequencywise_data, file_indices, unique_frequencies, segment_file_dict, config
        )
        if setup is None:
            return self._return_empty_results()

        dataset_dir, group_label, frequencywise_scaled, k1_baseline, k_values = setup

        accumulators = NormalRunAccumulators(k1_baseline)
        metric_results_dir = os.path.join(dataset_dir, 'metric_results')

        if k1_baseline:
            self._add_k1_baseline_to_results(
                k1_baseline, accumulators.segment_aci_scores, config.metrics_to_use
            )

        norm_data = FrequencywiseNormData(
            freq_data=frequencywise_data,
            freq_scaled=frequencywise_scaled
        )

        for k in k_values:
            self.logger.info(f"    [{config.dataset_type.upper()}] Clustering with k={k}")
            self._process_k_value(
                k, norm_data, file_indices, unique_frequencies, segment_file_dict, config,
                dataset_dir, group_label, accumulators, metric_results_dir
            )

        return self._finalize_clustering_run(
            accumulators.clustering_results, accumulators.trained_models,
            accumulators.segment_aci_scores, k1_baseline,
            config, dataset_dir, group_label, accumulators.centroid_scores,
            metric_results_dir, accumulators.merge_outcomes
        )

    def _setup_clustering_run(self, frequencywise_data, file_indices, unique_frequencies,
                            segment_file_dict, config):
        """Prepare output directory, segment overview, scaled data, k=1 baseline, and k-values.

        Returns a tuple of all values needed by the main loop, or None if setup fails.
        """
        if config.output_dir_is_final:
            dataset_dir = config.segment_dir
        else:
            dataset_dir = os.path.join(config.segment_dir, config.dataset_type)
        os.makedirs(dataset_dir, exist_ok=True)

        group_label = getattr(config, 'group_label', None)

        if config.generate_segment_overview:
            if not self._create_segment_overview(segment_file_dict, config.segment_name,
                                                dataset_dir, config.head_name):
                return None
        else:
            self.logger.info(
                f"  Segment overview skipped for group-level processing of {config.segment_name}")

        # Scale the time series data (per-file normalize-to-[-1,1] + detrend)
        frequencywise_scaled = self._scale_frequencywise_data(
            frequencywise_data, config.feature_weights, unique_frequencies
        )

        k1_baseline = self._calculate_k1_baseline(
            frequencywise_data, file_indices, unique_frequencies, segment_file_dict,
            config.metrics_to_use, config.dataset_type
        )

        k_values = self._determine_k_values(config.target_k, len(frequencywise_data))
        self.logger.info(f" [{config.dataset_type.upper()}] Performing TimeSeriesKMeans clustering for k={k_values}")

        return dataset_dir, group_label, frequencywise_scaled, k1_baseline, k_values

    def _resolve_model_save_dir(self, config, group_label, k):
        """Return the model save path for this k, scoped to the group when baseline separation is active."""
        if group_label and config.dataset_type == 'train':
            return os.path.join(
                config.models_base_dir, config.head_name, config.segment_name,
                group_label, f'k_{k}'
            )
        return None

    @staticmethod
    def _resolve_merged_models_dir(config, group_label, k):
        """Build the merged centroid save path for training; returns None during validation."""
        if config.dataset_type != 'train':
            return None
        base = os.path.join(config.models_base_dir, config.head_name, config.segment_name)
        if group_label:
            base = os.path.join(base, group_label)
        return os.path.join(base, f'k_{k}', 'merged')

    def _process_k_value(self, k, norm_data, file_indices, unique_frequencies, segment_file_dict,
                      config, dataset_dir, group_label, accumulators, metric_results_dir):
        """Run clustering, generate plots, and compute ACI and centroid metrics for a single k value."""
        k_dir = os.path.join(dataset_dir, f'k_{k}')
        os.makedirs(k_dir, exist_ok=True)

        model_save_dir = self._resolve_model_save_dir(config, group_label, k)

        km, file_labels, cluster_means = self._perform_clustering_for_k(
            k, norm_data.freq_scaled, config.dataset_type, config.pretrained_models,
            config.models_base_dir, config.head_name, config.segment_name, unique_frequencies,
            segment_file_dict=segment_file_dict,
            model_save_dir=model_save_dir, features_list=config.features_list
        )

        if km is None or file_labels is None:
            self.logger.warning(f"    Skipping k={k} due to clustering failure")
            return

        # For validation, compute cluster means from actual data
        if cluster_means is None:
            cluster_means = self._calculate_cluster_means(
                segment_file_dict, file_labels, k, unique_frequencies
            )

        accumulators.clustering_results[k] = {
            'file_labels': file_labels,
            'cluster_centers': km.cluster_centers_,
            'model': km
        }
        if config.dataset_type == 'train':
            accumulators.trained_models[k] = km

        # Generate fixed colors for this k value - used consistently across all plots
        cluster_colors = self._get_colors_for_k(k)

        self._generate_all_plots(
            segment_file_dict, file_labels, config.segment_name, k_dir, config.head_name, k,
            cluster_colors, cluster_means, unique_frequencies,
            config.generate_interactive_html_plots
        )
        self._save_drive_cluster_mapping(
            segment_file_dict, file_labels, file_indices, k, k_dir, config.head_name
        )
        self._compute_and_record_aci(
            norm_data, file_indices, unique_frequencies, segment_file_dict,
            file_labels, k, cluster_means, cluster_colors,
            k_dir, config, accumulators.segment_aci_scores
        )
        matrices = self._compute_and_record_centroid_metrics(
            cluster_means, unique_frequencies, config.metrics_to_use, k,
            config.segment_name, config.head_name, metric_results_dir, accumulators.centroid_scores
        )
        if k > 4 and matrices:
            models_merged_dir = self._resolve_merged_models_dir(config, group_label, k)
            merge_outcome, _ = self._run_merge_on_result(
                cluster_means, file_labels, matrices, config.metrics_to_use,
                config.generate_interactive_html_plots,
                MergeContext(config.head_name, config.segment_name, config.dataset_type,
                             k=k, output_dir=k_dir),
                MergeFileData(segment_file_dict, unique_frequencies, file_indices),
                models_merged_dir=models_merged_dir,
                feature_data=norm_data.freq_scaled, pre_cluster_centers=km.cluster_centers_,
                model_settings=MergeModelSettings(km.metric, km.random_state),
                pre_merge_scores=accumulators.centroid_scores.get(k), features_list=config.features_list
            )
            if merge_outcome is not None:
                accumulators.merge_outcomes[k] = merge_outcome

    def _compute_and_record_centroid_metrics(self, cluster_means, unique_frequencies,
                                              metrics_to_use, k, segment_name, head_name,
                                              metric_results_dir, centroid_scores):
        """Compute centroid pairwise metrics, store scores, and generate per-k heatmap.

        Returns:
            matrices: dict {metric_name: np.ndarray (k, k)}, or {} when inactive
        """
        if not any(m in CENTROID_METRIC_NAMES for m in metrics_to_use):
            return {}
        avg_scores, matrices = self.centroid_calculator.compute_centroid_metrics(
            cluster_means, unique_frequencies, metrics_to_use
        )
        if avg_scores:
            centroid_scores[k] = avg_scores
        if matrices:
            os.makedirs(metric_results_dir, exist_ok=True)
            cluster_labels = [f'Cluster {i}' for i in range(len(cluster_means))]
            self.execute_plot.execute_plot_in_process(
                self.centroid_plotter.plot_centroid_heatmaps,
                matrices, k, segment_name, metric_results_dir,
                head_name, metrics_to_use, f'k{k}', cluster_labels
            )
        return matrices

    def _compute_and_record_aci(self, norm_data, file_indices, unique_frequencies,
                              segment_file_dict, file_labels, k, cluster_means,
                              cluster_colors, k_dir, config, segment_aci_scores):
        """Build metrics config, calculate frequency ACI, and record average scores."""
        metrics_config = FrequencyACIMetricsConfig(
            k_dir=k_dir,
            segment_name=config.segment_name,
            head_name=config.head_name,
            metrics_to_use=config.metrics_to_use,
            individual_frequencies_cluster_assignment_plots=config.individual_frequencies_cluster_assignment_plots,
            cluster_colors=cluster_colors
        )
        frequency_metric_records, successful_freq_count = self._calculate_frequency_aci_metrics(
            norm_data.freq_data, file_indices, unique_frequencies, segment_file_dict,
            file_labels, k, metrics_config, cluster_means=cluster_means
        )
        avg_scores = self._calculate_segment_average_scores(
            successful_freq_count, frequency_metric_records, config.metrics_to_use,
            config.segment_name, k
        )
        if avg_scores:
            segment_aci_scores[k] = avg_scores
            self._log_segment_scores(k, avg_scores, config.metrics_to_use)

    def _finalize_clustering_run(self, clustering_results, trained_models, segment_aci_scores,
                                k1_baseline, config, dataset_dir, group_label,
                                centroid_scores, metric_results_dir, merge_outcomes=None):
        """Select optimal k, emit plots, write baseline CSV, collect model registry."""
        opt_dict = self.optimizer.select_optimal_cluster(
            segment_aci_scores, k1_baseline, config.segment_name, config.dataset_type,
            config.metrics_to_use
        )
        self._plot_aci_scores(
            segment_aci_scores, config.segment_name, dataset_dir, k1_baseline, opt_dict,
            config.metrics_to_use, config.head_name
        )
        self._compare_with_baseline(
            segment_aci_scores, k1_baseline, config.segment_name, dataset_dir,
            config.metrics_to_use, config.head_name
        )
        centroid_opt_dict = self._finalise_centroid_metrics(
            centroid_scores, config.metrics_to_use, config.segment_name,
            config.head_name, metric_results_dir
        )
        combined_opt_dict = {**opt_dict, **centroid_opt_dict}
        model_registry_info, optimal_k_info, merged_model_registry_info = self._collect_model_registry_info(
            config.dataset_type, trained_models, config.models_base_dir, config.head_name,
            config.segment_name, config.freq_min, config.freq_max, combined_opt_dict,
            group_label=group_label, merge_outcomes=merge_outcomes
        )
        return {
            'clustering_results': clustering_results,
            'trained_models': trained_models,
            'opt_k_aci1': opt_dict.get('aci1', 1),
            'opt_k_aci2': opt_dict.get('aci2', 1),
            'opt_k_aci3': opt_dict.get('aci3', 1),
            'opt_k_aci4': opt_dict.get('aci4', 1),
            'opt_k_correlation': centroid_opt_dict.get('correlation'),
            'opt_k_rmse': centroid_opt_dict.get('rmse'),
            'opt_k_wasserstein': centroid_opt_dict.get('wasserstein'),
            'model_registry_info': model_registry_info,
            'merged_model_registry_info': merged_model_registry_info,
            'optimal_k_info': optimal_k_info,
            'segment_aci_scores': segment_aci_scores,
            'centroid_scores': centroid_scores,
        }

    def _finalise_centroid_metrics(self, centroid_scores, metrics_to_use,
                                    segment_name, head_name, metric_results_dir):
        """Run elbow detection and generate elbow plot for centroid metrics. Returns opt dict."""
        if not centroid_scores or not any(m in CENTROID_METRIC_NAMES for m in metrics_to_use):
            return {}
        centroid_opt_dict = self.centroid_calculator.select_optimal_k(centroid_scores, metrics_to_use)
        if centroid_opt_dict:
            os.makedirs(metric_results_dir, exist_ok=True)
            self.execute_plot.execute_plot_in_process(
                self.centroid_plotter.plot_elbow_curves,
                centroid_scores, centroid_opt_dict, segment_name,
                metric_results_dir, head_name, metrics_to_use
            )
        return centroid_opt_dict

    @staticmethod
    def _return_empty_results():
        """Return empty results when segment is rejected"""
        return {
            'clustering_results': {},
            'trained_models': {},
            'opt_k_aci1': 1, 'opt_k_aci2': 1, 'opt_k_aci3': 1, 'opt_k_aci4': 1,
            'opt_k_correlation': None, 'opt_k_rmse': None, 'opt_k_wasserstein': None,
            'model_registry_info': [], 'merged_model_registry_info': [], 'optimal_k_info': None,
            'segment_aci_scores': {}, 'centroid_scores': {},
        }
