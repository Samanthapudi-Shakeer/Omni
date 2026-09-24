# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_clustering_hierarchical_s2.py
*  File Description: Stage-2 clustering, combining, and finalization mixin
*                    for the two-stage hierarchical clustering engine.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import numpy as np
from frf_clustering_utils import FrequencyACIMetricsConfig, FRFDataPreprocessor, FrequencywiseNormData
from frf_clustering_utils import MergeContext, MergeFileData, MergeModelSettings
from frf_clustering_utils import StageCombination, SharedStage2Data
from frf_clustering_base import MODEL_NAME
from frf_centroid_metrics import CENTROID_METRIC_NAMES


class CombinedClusteringResult(object):
    """Bundles combined (stage1 x stage2) clustering outputs shared across finalization methods."""

    def __init__(self, labels, file_indices, segment_dict, means):
        self.labels = labels
        self.file_indices = file_indices
        self.segment_dict = segment_dict
        self.means = means
        self.colors = None
        self.reindexed_file_indices = None


class HierarchicalStage2Mixin(object):
    """Mixin providing stage-2 clustering, combining, and finalization for the hierarchical engine"""

    def _compute_shared_stage2_normalization(self, segment_file_dict, file_indices,
                                              unique_frequencies, config):
        """Compute one segment-wide stage-2 normalization used to build consolidated
        combined/merged models, and to predict through the saved flat combined model
        during validation"""
        raw_data = self._build_combined_frequencywise_data(
            segment_file_dict, file_indices, unique_frequencies, config.stage2_features
        )
        scaled = self._scale_frequencywise_data(
            raw_data, config.stage2_feature_weights, unique_frequencies
        )
        orig_to_row = {orig_idx: row for row, orig_idx in enumerate(file_indices)}
        return scaled, orig_to_row

    def _process_all_stage2_clusters(self, parent_k, labels_s1, file_indices, unique_frequencies,
                                      segment_file_dict, config, stage1_k_dir,
                                      stage2_k_values, segment_models_base):
        """Iterate over every parent cluster and run stage-2 clustering inside each."""
        stage2_results = {}
        for parent_cluster_id in range(parent_k):
            self.logger.info(f"    Stage 2 — parent cluster {parent_cluster_id}/{parent_k - 1}")
            stage2_results[parent_cluster_id] = {}

            cluster_file_indices, cluster_segment_dict = self._filter_cluster_files(
                segment_file_dict, file_indices, labels_s1, parent_cluster_id
            )

            if len(cluster_file_indices) < 2:
                self.logger.warning(
                    f"    Parent cluster {parent_cluster_id} has <2 files, skipping stage 2")
                continue

            stage2_cluster_models_base = os.path.join(
                segment_models_base, f'stage1_k_{parent_k}', f'cluster_{parent_cluster_id}'
            )
            os.makedirs(stage2_cluster_models_base, exist_ok=True)

            self._process_single_parent_cluster(
                parent_k, parent_cluster_id, cluster_file_indices, cluster_segment_dict,
                unique_frequencies, config, stage1_k_dir, stage2_k_values,
                stage2_cluster_models_base, stage2_results
            )

        return stage2_results

    def _process_single_parent_cluster(self, parent_k, parent_cluster_id, cluster_file_indices,
                                    cluster_segment_dict, unique_frequencies, config,
                                    stage1_k_dir, stage2_k_values,
                                    stage2_cluster_models_base, stage2_results):
        """Build stage-2 features, normalize, then run every stage2_k for one parent cluster."""
        preprocessor = FRFDataPreprocessor()
        freq_data_s2, _, cluster_reindexed_file_indices = preprocessor.create_frequencywise_array(
            cluster_segment_dict, config.stage2_features, config.segment_name
        )

        freq_scaled_s2 = self._normalize_stage2(freq_data_s2, config, unique_frequencies)

        stage2_norm = FrequencywiseNormData(
            freq_data=freq_data_s2,
            freq_scaled=freq_scaled_s2
        )

        for stage2_k in stage2_k_values:
            self._process_stage2_for_k(
                parent_k, parent_cluster_id, stage2_k, stage2_norm,
                cluster_file_indices, cluster_reindexed_file_indices,
                cluster_segment_dict, unique_frequencies, config,
                stage1_k_dir, stage2_cluster_models_base, stage2_results
            )

    def _normalize_stage2(self, freq_data_s2, config, unique_frequencies):
        """Scale stage-2 data (per-file normalize-to-[-1,1] + detrend)."""
        return self._scale_frequencywise_data(
            freq_data_s2, config.stage2_feature_weights, unique_frequencies
        )

    def _process_stage2_for_k(self, parent_k, parent_cluster_id, stage2_k, stage2_norm,
                           cluster_file_indices, cluster_reindexed_file_indices,
                           cluster_segment_dict, unique_frequencies, config,
                           stage1_k_dir, stage2_cluster_models_base, stage2_results):
        """Run stage-2 clustering for a single (parent_cluster, stage2_k) pair."""
        if stage2_k > len(cluster_file_indices):
            self._handle_stage2_passthrough(
                parent_cluster_id, stage2_k, cluster_file_indices,
                cluster_segment_dict, unique_frequencies, stage2_results
            )
            return

        self.logger.info(
            f"    Stage 2 — parent_k={parent_k}, cluster={parent_cluster_id}, stage2_k={stage2_k}")

        stage2_output_dir = os.path.join(
            stage1_k_dir, f'cluster_{parent_cluster_id}', f'stage2_k_{stage2_k}'
        )
        os.makedirs(stage2_output_dir, exist_ok=True)

        stage2_models_dir = os.path.join(stage2_cluster_models_base, f'stage2_k_{stage2_k}')
        os.makedirs(stage2_models_dir, exist_ok=True)

        km_s2, labels_s2, means_s2 = self._run_stage2_clustering(
            stage2_k, stage2_norm.freq_scaled, cluster_segment_dict, unique_frequencies,
            config, parent_k, parent_cluster_id, stage2_models_dir
        )
        if km_s2 is None or labels_s2 is None:
            return

        stage2_colors = self.generate_colour.get_stage2_cluster_colors(stage2_k)
        self._generate_all_plots(
            cluster_segment_dict, labels_s2, config.segment_name,
            stage2_output_dir, config.head_name, stage2_k,
            stage2_colors, means_s2, unique_frequencies,
            config.generate_interactive_html_plots
        )
        self._save_drive_cluster_mapping(
            cluster_segment_dict, labels_s2, cluster_reindexed_file_indices, stage2_k,
            stage2_output_dir, config.head_name
        )

        if config.individual_frequencies_cluster_assignment_plots:
            self._compute_stage2_frequency_aci(
                stage2_norm.freq_data, cluster_reindexed_file_indices, unique_frequencies,
                cluster_segment_dict, labels_s2, stage2_k,
                means_s2, stage2_colors, stage2_output_dir, config
            )

        stage2_results[parent_cluster_id][stage2_k] = {
            'labels': labels_s2,
            'means': means_s2,
            'km': km_s2,
            'file_indices': cluster_file_indices,
            'segment_dict': cluster_segment_dict
        }

    def _handle_stage2_passthrough(self, parent_cluster_id, stage2_k, cluster_file_indices,
                                    cluster_segment_dict, unique_frequencies, stage2_results):
        """Store a passthrough (single-cluster) result when stage2_k exceeds cluster size."""
        self.logger.warning(
            f"    Stage2 k={stage2_k} > cluster size {len(cluster_file_indices)} "
            f"for parent cluster {parent_cluster_id} — treating as single-cluster passthrough")
        passthrough_labels = np.zeros(len(cluster_file_indices), dtype=int)
        passthrough_means = self._calculate_cluster_means(
            cluster_segment_dict, passthrough_labels, 1, unique_frequencies
        )

        padded_means = np.tile(passthrough_means[0:1], (stage2_k, 1, 1))
        stage2_results[parent_cluster_id][stage2_k] = {
            'labels': passthrough_labels,
            'means': padded_means,
            'km': None,
            'file_indices': cluster_file_indices,
            'segment_dict': cluster_segment_dict
        }

    def _run_stage2_clustering(self, stage2_k, freq_scaled_s2, cluster_segment_dict,
                                unique_frequencies, config, parent_k, parent_cluster_id,
                                stage2_models_dir):
        """Train or load the stage-2 model and return (km, labels, means)."""
        if config.dataset_type == 'train':
            km_s2, labels_s2, means_s2 = self._train_new_model(
                stage2_k, freq_scaled_s2,
                config.models_base_dir, config.head_name, config.segment_name,
                unique_frequencies,
                segment_file_dict=cluster_segment_dict,
                model_save_dir=stage2_models_dir, features_list=config.stage2_features
            )
            if means_s2 is None:
                means_s2 = self._calculate_cluster_means(
                    cluster_segment_dict, labels_s2, stage2_k, unique_frequencies
                )
            return km_s2, labels_s2, means_s2

        km_s2, labels_s2 = self._load_and_predict_hierarchical_stage2(
            freq_scaled_s2, config, parent_k, parent_cluster_id, stage2_k
        )
        if km_s2 is None:
            return None, None, None
        means_s2 = self._calculate_cluster_means(
            cluster_segment_dict, labels_s2, stage2_k, unique_frequencies
        )
        return km_s2, labels_s2, means_s2

    def _compute_stage2_frequency_aci(self, freq_data_s2, cluster_reindexed_file_indices,
                                       unique_frequencies, cluster_segment_dict, labels_s2,
                                       stage2_k, means_s2,
                                       stage2_colors, stage2_output_dir, config):
        """Run frequency ACI metric calculation for stage-2 individual frequency plots."""
        metrics_config_s2 = FrequencyACIMetricsConfig(
            k_dir=stage2_output_dir,
            segment_name=config.segment_name,
            head_name=config.head_name,
            metrics_to_use=config.metrics_to_use,
            individual_frequencies_cluster_assignment_plots=True,
            cluster_colors=stage2_colors
        )
        self._calculate_frequency_aci_metrics(
            freq_data_s2, cluster_reindexed_file_indices, unique_frequencies,
            cluster_segment_dict, labels_s2, stage2_k,
            metrics_config_s2, cluster_means=means_s2
        )

    def _process_combined_results(self, parent_k, stage2_k_values, stage2_results,
                                   file_indices, unique_frequencies,
                                   segment_file_dict, config, final_dir, accumulators,
                                   pk_centroid_scores, metric_results_stage1_dir,
                                   segment_models_base=None, shared_stage2_data=None):
        """Build, evaluate, and merge combined (stage1 x stage2) results for every stage2_k."""
        for stage2_k in stage2_k_values:
            total_clusters = parent_k * stage2_k
            self.logger.info(
                f"  [HIERARCHICAL] Generating final combined plots: "
                f"stage1_k={parent_k}, stage2_k={stage2_k}, total={total_clusters}")

            combined_labels, combined_file_indices, combined_segment_dict, combined_means = \
                self._build_combined_hierarchical_result(
                    stage2_results, parent_k, stage2_k, segment_file_dict,
                    file_indices, unique_frequencies
                )

            if combined_labels is None:
                self.logger.warning(
                    f"  Could not build combined result for stage2_k={stage2_k}, skipping")
                continue

            combined_result = CombinedClusteringResult(
                labels=combined_labels,
                file_indices=combined_file_indices,
                segment_dict=combined_segment_dict,
                means=combined_means
            )
            self._process_single_combined_result(
                StageCombination(parent_k, stage2_k, total_clusters), combined_result,
                unique_frequencies, segment_file_dict,
                config, final_dir, accumulators,
                pk_centroid_scores, metric_results_stage1_dir,
                segment_models_base=segment_models_base,
                shared_stage2_data=shared_stage2_data,
                stage2_results=stage2_results
            )

    def _process_single_combined_result(self, stage_combo, combined_result,
                                     unique_frequencies,
                                     segment_file_dict, config, final_dir, accumulators,
                                     pk_centroid_scores, metric_results_stage1_dir,
                                     segment_models_base=None, shared_stage2_data=None,
                                     stage2_results=None):
        """Generate all plots and ACI metrics for one combined (parent_k x stage2_k) result,
        then attempt a merge and write its final result (snapshot + forward pass) immediately"""
        parent_k, stage2_k, total_clusters = (
            stage_combo.parent_k, stage_combo.stage2_k, stage_combo.total_clusters
        )
        combined_result.colors = self.generate_colour.generate_distinct_colors(total_clusters)
        combined_result.reindexed_file_indices = list(range(len(combined_result.file_indices)))

        models_combined_dir = self._resolve_hierarchical_combined_models_dir(
            segment_models_base, parent_k, stage2_k
        )
        shared_scaled_s2 = shared_stage2_data.shared_scaled_s2 if shared_stage2_data else None
        orig_to_row_s2 = shared_stage2_data.orig_to_row_s2 if shared_stage2_data else None
        combined_feature_data = self._align_shared_feature_data(
            shared_scaled_s2, orig_to_row_s2, combined_result.file_indices
        )
        combined_result = self._apply_combined_result(
            combined_result, combined_feature_data, unique_frequencies, total_clusters,
            models_combined_dir, config
        )

        self._generate_combined_result_plots(
            stage_combo, combined_result, unique_frequencies, config, final_dir
        )

        self._compute_combined_aci_and_record(
            parent_k, stage2_k, total_clusters, combined_result,
            unique_frequencies,
            segment_file_dict, config, final_dir, accumulators.hierarchical_entries
        )
        matrices = self._compute_combined_centroid_metrics(
            combined_result.means, unique_frequencies, config.metrics_to_use,
            parent_k, stage2_k, total_clusters, config.segment_name, config.head_name,
            metric_results_stage1_dir, pk_centroid_scores
        )

        return self._attempt_combined_merge(
            stage_combo, combined_result, matrices, unique_frequencies, config, final_dir,
            pk_centroid_scores, segment_models_base, stage2_results, combined_feature_data,
            accumulators
        )

    def _generate_combined_result_plots(self, stage_combo, combined_result,
                                         unique_frequencies, config, final_dir):
        """Generate all combined (parent_k x stage2_k) Bode/3D/frequency-grid plots
        and write the drive-cluster-mapping CSV."""
        parent_k, stage2_k, total_clusters = (
            stage_combo.parent_k, stage_combo.stage2_k, stage_combo.total_clusters
        )
        hierarchical_k_label = f's1_k{parent_k}_s2_k{stage2_k}'

        real_counts, worst_counts = self._count_files_by_source(
            combined_result.segment_dict, combined_result.labels, total_clusters
        )
        self.execute_plot.execute_plot_in_process(
            self.plot_interactive_bode.create_hierarchical_combined_static_bode_means,
            combined_result.means, unique_frequencies, parent_k, stage2_k,
            combined_result.colors, final_dir, config.head_name,
            combined_result.labels, real_counts=real_counts, worst_counts=worst_counts
        )
        self.logger.info(f"    Generated combined static Bode centroids")

        self.execute_plot.execute_plot_in_process(
            self.plot_interactive_bode.create_bode_centroid_metrics,
            combined_result.means, unique_frequencies, total_clusters, combined_result.colors,
            config.segment_name, final_dir, config.head_name, combined_result.labels,
            k_label=hierarchical_k_label
        )
        self.logger.info(f"    Generated combined Bode centroid metrics plot")

        self.execute_plot.execute_plot_in_process(
            self.plot_grid.create_frequency_gain_phase_grid,
            combined_result.segment_dict, combined_result.labels, config.segment_name,
            final_dir, total_clusters, config.head_name, combined_result.colors,
            k_label=hierarchical_k_label
        )
        self.logger.info(f"    Generated combined frequency-gain-phase grid")

        if config.generate_interactive_html_plots:
            self.execute_plot.execute_plot_in_process(
                self.plot_interactive_bode.create_hierarchical_combined_interactive_bode_plots,
                combined_result.segment_dict, combined_result.labels, combined_result.means,
                unique_frequencies, parent_k, stage2_k,
                config.segment_name, final_dir, config.head_name, combined_result.colors
            )
            self.logger.info(f"    Generated combined interactive Bode plots")

        self.execute_plot.execute_plot_in_process(
            self.plot_3d.create_3d_visualization,
            combined_result.segment_dict, config.segment_name, final_dir, config.head_name,
            combined_result.labels, total_clusters, combined_result.colors, combined_result.means,
            f's1_k{parent_k}_s2_k{stage2_k}'
        )

        if config.generate_interactive_html_plots:
            self.execute_plot.execute_plot_in_process(
                self.plot_3d.create_interactive_3d_visualization,
                combined_result.segment_dict, config.segment_name, final_dir, config.head_name,
                combined_result.labels, total_clusters, combined_result.colors, combined_result.means,
                name_suffix=f'stage1_k{parent_k}_stage2_k{stage2_k}'
            )

        self.execute_plot.execute_plot_in_process(
            self.plot_3d.create_3d_centroids_only,
            combined_result.means, unique_frequencies, total_clusters,
            combined_result.colors, config.segment_name, final_dir, config.head_name,
            k_label=hierarchical_k_label
        )

        self._save_drive_cluster_mapping(
            combined_result.segment_dict, combined_result.labels,
            combined_result.reindexed_file_indices, total_clusters,
            final_dir, config.head_name,
            name_suffix=hierarchical_k_label
        )

    def _attempt_combined_merge(self, stage_combo, combined_result, matrices, unique_frequencies,
                                 config, final_dir, pk_centroid_scores, segment_models_base,
                                 stage2_results, combined_feature_data, accumulators):
        """Attempt the centroid merge for one combined result and record the outcome, if any."""
        parent_k, stage2_k, total_clusters = (
            stage_combo.parent_k, stage_combo.stage2_k, stage_combo.total_clusters
        )
        if total_clusters <= 4 or not matrices:
            return None
        if not self._all_stage2_metrics_euclidean(stage2_results, parent_k, stage2_k):
            self.logger.warning(
                f"    Skipping merge for stage1_k={parent_k}, stage2_k={stage2_k}: "
                f"one or more contributing stage-2 models were not trained with "
                f"metric='euclidean'. The consolidated-centroid merge treats every "
                f"centroid as an arithmetic mean, which is only valid for that metric."
            )
            return None

        models_merged_dir = self._resolve_hierarchical_merged_models_dir(
            config, segment_models_base, parent_k, stage2_k
        )
        merge_feature_data = combined_feature_data if config.dataset_type == 'train' else None
        outcome, _ = self._run_merge_on_result(
            combined_result.means, combined_result.labels, matrices, config.metrics_to_use,
            config.generate_interactive_html_plots,
            MergeContext(config.head_name, config.segment_name, config.dataset_type,
                         k=total_clusters, output_dir=final_dir),
            MergeFileData(combined_result.segment_dict, unique_frequencies,
                          combined_result.reindexed_file_indices),
            models_merged_dir=models_merged_dir, feature_data=merge_feature_data,
            pre_cluster_centers=None, model_settings=MergeModelSettings('euclidean', 0),
            pre_merge_scores=pk_centroid_scores.get(total_clusters), features_list=config.stage2_features
        )
        if outcome is not None:
            accumulators.merge_outcomes[(parent_k, total_clusters)] = outcome
        return outcome

    def _apply_combined_result(self, combined_result, feature_data, unique_frequencies,
                                total_clusters, models_combined_dir, config):
        """Replace combined_result's raw stage1 x stage2 labels/means with the single-
        stage 'combined' result"""
        if feature_data is None or models_combined_dir is None:
            return combined_result

        if config.dataset_type == 'train':
            labels, means = self._fit_combined_forward_pass(
                combined_result.means, combined_result.labels, combined_result.segment_dict,
                unique_frequencies, total_clusters, models_combined_dir, feature_data,
                config.stage2_features
            )
        else:
            labels, means = self._predict_combined_result(
                combined_result, feature_data, unique_frequencies, total_clusters,
                models_combined_dir
            )

        if labels is None:
            return combined_result
        combined_result.labels = labels
        combined_result.means = means
        return combined_result

    def _predict_combined_result(self, combined_result, feature_data, unique_frequencies,
                                  total_clusters, models_combined_dir):
        """Predict labels for a combination's files using the previously trained flat 'combined' model"""
        model_path = os.path.join(models_combined_dir, MODEL_NAME)
        try:
            km = self.model_save.load_model(model_path)
            labels = km.predict(feature_data)
        except Exception as e:
            self.logger.warning(
                f"  Could not load combined model for prediction ({model_path}): {e}")
            return None, None
        means = self._calculate_cluster_means(
            combined_result.segment_dict, labels, total_clusters, unique_frequencies
        )
        return labels, means

    @staticmethod
    def _all_stage2_metrics_euclidean(stage2_results, parent_k, stage2_k):
        """Return True only if every parent cluster's stage-2 model contributing to this
        (parent_k, stage2_k) combination was trained with metric='euclidean'"""
        if stage2_results is None:
            return True
        for parent_cluster_id in range(parent_k):
            result = stage2_results.get(parent_cluster_id, {}).get(stage2_k)
            if result is None:
                continue
            km = result.get('km')
            if km is not None and getattr(km, 'metric', 'euclidean') != 'euclidean':
                return False
        return True

    @staticmethod
    def _resolve_hierarchical_combined_models_dir(segment_models_base, parent_k, stage2_k):
        """Build the flat single-stage 'h_combined' model directory for one hierarchical
        combination. Lives directly under the segment (a sibling of stage1_k_<k>), not
        nested inside it."""
        if segment_models_base is None:
            return None
        return os.path.join(
            segment_models_base, 'h_combined',
            f'stage1_k_{parent_k}_stage2_k_{stage2_k}'
        )

    @staticmethod
    def _resolve_hierarchical_merged_models_dir(config, segment_models_base, parent_k, stage2_k):
        """Build merged centroid/model save path for hierarchical combined result (training
        only). Nested inside its own combination folder under 'h_combined', reusing the
        same combo path as the flat combined model."""
        if config.dataset_type != 'train':
            return None
        combined_dir = HierarchicalStage2Mixin._resolve_hierarchical_combined_models_dir(
            segment_models_base, parent_k, stage2_k
        )
        if combined_dir is None:
            return None
        return os.path.join(combined_dir, 'merged')

    def _compute_combined_centroid_metrics(self, combined_means, unique_frequencies,
                                            metrics_to_use, parent_k, stage2_k, total_clusters,
                                            segment_name, head_name, metric_results_stage1_dir,
                                            pk_centroid_scores):
        """Compute centroid metrics for one combined (parent_k, stage2_k) result"""
        if not any(m in CENTROID_METRIC_NAMES for m in metrics_to_use):
            return {}
        avg_scores, matrices = self.centroid_calculator.compute_centroid_metrics(
            combined_means, unique_frequencies, metrics_to_use
        )
        if avg_scores:
            pk_centroid_scores[total_clusters] = avg_scores
        if matrices:
            os.makedirs(metric_results_stage1_dir, exist_ok=True)
            k_label = f'stage1k{parent_k}_stage2k{stage2_k}'
            cluster_labels = [
                f'Parent {p}, Sub {s}'
                for p in range(parent_k)
                for s in range(stage2_k)
            ]
            self.execute_plot.execute_plot_in_process(
                self.centroid_plotter.plot_centroid_heatmaps,
                matrices, total_clusters, segment_name, metric_results_stage1_dir,
                head_name, metrics_to_use, k_label, cluster_labels
            )
        return matrices

    def _compute_combined_aci_and_record(self, parent_k, stage2_k, total_clusters,
                                      combined_result,
                                      unique_frequencies,
                                      segment_file_dict, config, final_dir,
                                      all_hierarchical_entries):
        """Calculate ACI metrics on the combined result and append to the entries list."""
        metrics_config_final = FrequencyACIMetricsConfig(
            k_dir=final_dir,
            segment_name=config.segment_name,
            head_name=config.head_name,
            metrics_to_use=config.metrics_to_use,
            individual_frequencies_cluster_assignment_plots=config.individual_frequencies_cluster_assignment_plots,
            cluster_colors=combined_result.colors
        )
        combined_freq_data = self._build_combined_frequencywise_data(
            segment_file_dict, combined_result.file_indices, unique_frequencies,
            config.stage1_features
        )
        freq_records, success_count = self._calculate_frequency_aci_metrics(
            combined_freq_data, combined_result.reindexed_file_indices, unique_frequencies,
            combined_result.segment_dict, combined_result.labels, total_clusters,
            metrics_config_final, cluster_means=combined_result.means
        )
        avg_scores = self._calculate_segment_average_scores(
            success_count, freq_records, config.metrics_to_use,
            config.segment_name, total_clusters
        )
        if avg_scores:
            all_hierarchical_entries.append({
                'parent_k': parent_k,
                'stage2_k': stage2_k,
                'total_clusters': total_clusters,
                'is_parent': False,
                **avg_scores
            })
            self._log_segment_scores(total_clusters, avg_scores, config.metrics_to_use)

    def _load_and_predict_hierarchical_stage2(self, frequencywise_scaled, config,
                                               parent_k, parent_cluster_id, stage2_k):
        """Load pretrained stage2 model and predict for validation"""
        group_label = getattr(config, 'group_label', None)
        segment_models_base = self._build_segment_models_base(
            config.models_base_dir, config.head_name, config.segment_name, group_label
        )
        model_path = os.path.join(
            segment_models_base,
            f'stage1_k_{parent_k}', f'cluster_{parent_cluster_id}',
            f'stage2_k_{stage2_k}', MODEL_NAME
        )
        try:
            km = self.model_save.load_model(model_path)
            labels = km.predict(frequencywise_scaled)
            return km, labels
        except Exception as e:
            self.logger.warning(
                f"  Could not load stage2 model (parent_k={parent_k}, cluster={parent_cluster_id}, "
                f"stage2_k={stage2_k}): {e}")
            return None, None

    @staticmethod
    def _filter_cluster_files(segment_file_dict, file_indices, labels, cluster_id):
        """Filter segment_file_dict to only files assigned to a specific cluster"""
        cluster_file_indices = []
        cluster_segment_dict = {
            'frequencies': segment_file_dict['frequencies'],
            'files': {}
        }
        new_idx = 0
        for file_idx, original_file_idx in enumerate(file_indices):
            if labels[file_idx] == cluster_id:
                cluster_file_indices.append(original_file_idx)
                cluster_segment_dict['files'][new_idx] = segment_file_dict['files'][original_file_idx]
                new_idx += 1

        return cluster_file_indices, cluster_segment_dict

    def _build_combined_hierarchical_result(self, stage2_results, parent_k, stage2_k,
                                             full_segment_dict, full_file_indices, unique_frequencies):
        """Build combined global cluster assignments across all parent clusters for a given stage2_k"""
        total_clusters = parent_k * stage2_k
        n_frequencies = len(unique_frequencies)

        # Check all required parent clusters have results
        for parent_cluster_id in range(parent_k):
            if parent_cluster_id not in stage2_results or \
                    stage2_k not in stage2_results[parent_cluster_id]:
                self.logger.warning(
                    f"  Missing stage2 result for parent_cluster={parent_cluster_id}, "
                    f"stage2_k={stage2_k} — cannot build combined result")
                return None, None, None, None

        combined_labels = np.full(len(full_file_indices), -1, dtype=int)
        combined_means = np.zeros((total_clusters, n_frequencies, 2))

        for parent_cluster_id in range(parent_k):
            result = stage2_results[parent_cluster_id][stage2_k]
            sub_file_indices = result['file_indices']
            sub_labels = result['labels']
            sub_means = result['means']

            # Map sub-labels to global labels
            offset = parent_cluster_id * stage2_k
            for sub_idx, original_file_idx in enumerate(sub_file_indices):
                # Find position of this file in full_file_indices
                if original_file_idx in full_file_indices:
                    global_idx = full_file_indices.index(original_file_idx)
                    combined_labels[global_idx] = int(sub_labels[sub_idx]) + offset

            # Store sub-cluster means at global positions
            for local_c in range(stage2_k):
                global_c = offset + local_c
                combined_means[global_c] = sub_means[local_c]

        # Build combined segment dict (all files, re-indexed)
        combined_segment_dict = {
            'frequencies': full_segment_dict['frequencies'],
            'files': {}
        }
        new_idx = 0
        combined_file_indices_list = []
        for file_idx, original_file_idx in enumerate(full_file_indices):
            if combined_labels[file_idx] >= 0:
                combined_segment_dict['files'][new_idx] = full_segment_dict['files'][original_file_idx]
                combined_file_indices_list.append(original_file_idx)
                new_idx += 1

        # Rebuild labels array aligned to combined_file_indices
        combined_labels_reindexed = np.array([
            combined_labels[full_file_indices.index(oidx)]
            for oidx in combined_file_indices_list
        ])

        return combined_labels_reindexed, combined_file_indices_list, combined_segment_dict, combined_means

    @staticmethod
    def _build_combined_frequencywise_data(segment_file_dict, file_indices,
                                            unique_frequencies, features_list):
        """Build frequencywise data array for the given file_indices and features."""
        n_files = len(file_indices)
        n_freq = len(unique_frequencies)
        n_features = len(features_list)
        data = np.zeros((n_files, n_freq, n_features))

        for new_idx, original_file_idx in enumerate(file_indices):
            file_data = segment_file_dict['files'].get(original_file_idx)
            if file_data is None:
                continue
            for feat_idx, feat_name in enumerate(features_list):
                data[new_idx, :, feat_idx] = file_data[feat_name]

        return data
