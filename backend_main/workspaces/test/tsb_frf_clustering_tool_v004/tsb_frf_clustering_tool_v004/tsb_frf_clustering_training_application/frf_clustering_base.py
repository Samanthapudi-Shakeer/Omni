# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_clustering_base.py
*  File Description: Base class containing shared methods for normal and
*                    hierarchical clustering engines.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import pandas as pd
import numpy as np
from tslearn.clustering import TimeSeriesKMeans
import logging
from frf_metric_components import ConvexHullCalculator, CurveProcessor
from frf_metrics import BaselineMetricsCalculator, BaselineComparator, ACIMetricsCalculator, FRFClusterOptimizer
from frf_plots import Plot3DVisualizer, PlotSegmentOverviewVisualizer, PlotMetricsVisualizer
from frf_bode_plots import PlotFrequencyGridVisualizer
from frf_plots_optional import PlotInteractiveBodeVisualizer, Plot2DVisualizer, PlotFanSegmentVisualizer
from frf_clustering_utils import ColorGenerator, FeatureConfigManager
from frf_clustering_utils import MergeContext, MergeFileData, MergeModelSettings
from frf_clustering_utils import ModelManager, PlotExecutor
import time
from frf_centroid_metrics import CentroidMetricsCalculator, CENTROID_METRIC_NAMES, AVG_SCORE_KEYS, CentroidMetricPlotter
from frf_centroid_merge import CentroidClusterMerger, MergeResult
from frf_clustering_base_metrics import FRFClusteringBaseMetrics, MODEL_NAME


MAX_FORWARD_PASSES = 30
CONVERGENCE_PLATEAU_WINDOW = 5
CONVERGENCE_PLATEAU_TOLERANCE = 50


class FRFClusteringBase(FRFClusteringBaseMetrics):
    """Base class providing shared clustering methods used by both normal and hierarchical engines"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.model_save = ModelManager()
        self.calculate_k1_baseline = BaselineMetricsCalculator()
        self.compare_k1_baseline = BaselineComparator()
        self.calculate_acis = ACIMetricsCalculator()
        self.generate_colour = ColorGenerator()
        self.convex_hull_calculater = ConvexHullCalculator()
        self.curve_processor = CurveProcessor()
        self.optimizer = FRFClusterOptimizer()
        self.feature_config_manager = FeatureConfigManager()
        self.execute_plot = PlotExecutor()
        self.centroid_calculator = CentroidMetricsCalculator()
        self.centroid_plotter = CentroidMetricPlotter()
        self.cluster_merger = CentroidClusterMerger(self.centroid_calculator)

        self.plot_3d = Plot3DVisualizer()
        self.plot_overview = PlotSegmentOverviewVisualizer()
        self.plot_2d = Plot2DVisualizer()
        self.plot_fan = PlotFanSegmentVisualizer()
        self.plot_metrics = PlotMetricsVisualizer()
        self.plot_grid = PlotFrequencyGridVisualizer()
        self.plot_interactive_bode = PlotInteractiveBodeVisualizer()

        self.epsilon = 1e-12

    def _create_segment_overview(self, segment_file_dict, segment_name, dataset_dir, head_name):
        """Create segment overview analysis"""
        success, overview_result = self.execute_plot.execute_plot_in_process(
            self.plot_overview.create_segment_overview_analysis,
            segment_file_dict, segment_name, dataset_dir, head_name
        )

        if not success or overview_result is False:
            self.logger.error(f"  Convex hull creation failed for segment overview")
            self.logger.error(f"  Segment {segment_name} will not be processed")
            return False

        self.logger.info(f"  [{os.path.basename(dataset_dir).upper()}] Generated segment overview plot...")

        # 1x2 or 3x2 depending on worst-model presence
        self.execute_plot.execute_plot_in_process(
            self.plot_overview.create_normalization_detrend_overview,
            segment_file_dict, segment_name, dataset_dir, head_name
        )
        self.logger.info(
            f"  [{os.path.basename(dataset_dir).upper()}] Generated normalization+detrend overview plot...")

        return True

    @staticmethod
    def _build_segment_models_base(models_base_dir, head_name, segment_name, group_label=None):
        """Return the segment models base directory, including group_label when baseline separation is active.

        Without group_label: <models_base_dir>/<head_name>/<segment_name>
        With    group_label: <models_base_dir>/<head_name>/<segment_name>/<group_label>
        """
        base = os.path.join(models_base_dir, head_name, segment_name)
        if group_label:
            base = os.path.join(base, group_label)
        return base

    def _scale_frequencywise_data(self, frequencywise_data, feature_weights, unique_frequencies):
        """Scale frequencywise data for clustering via per-file normalize-to-[-1,1] + detrend."""
        return self._normalize_detrend_and_weight(frequencywise_data, feature_weights, unique_frequencies)

    def _normalize_detrend_and_weight(self, frequencywise_data, feature_weights, unique_frequencies):
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

    def _calculate_k1_baseline(self, frequencywise_data, file_indices, unique_frequencies,
                            segment_file_dict, metrics_to_use, dataset_type):
        """Calculate k=1 baseline metrics — skipped when no ACI metrics are configured."""
        aci_metrics = {'ACI1', 'ACI2', 'ACI3', 'ACI4'}
        if not any(m in aci_metrics for m in metrics_to_use):
            self.logger.info(
                f"  [{dataset_type.upper()}] Skipping k=1 baseline — no ACI metrics configured")
            return None
        self.logger.info(f"  [{dataset_type.upper()}] Calculating k=1 baseline metrics...")
        return self.calculate_k1_baseline.calculate_k1_baseline_metrics(
            frequencywise_data, file_indices, unique_frequencies,
            segment_file_dict, metrics_to_use=metrics_to_use
        )

    @staticmethod
    def _add_k1_baseline_to_results(k1_baseline, segment_aci_scores, metrics_to_use):
        """Add k=1 baseline to segment ACI scores"""
        baseline_scores = {}
        if 'ACI1' in metrics_to_use and 'aci1_score' in k1_baseline:
            baseline_scores['avg_aci1'] = k1_baseline['aci1_score']
        if 'ACI2' in metrics_to_use and 'aci2_score' in k1_baseline:
            baseline_scores['avg_aci2'] = k1_baseline['aci2_score']
        if 'ACI3' in metrics_to_use and 'aci3_score' in k1_baseline:
            baseline_scores['avg_aci3'] = k1_baseline['aci3_score']
        if 'ACI4' in metrics_to_use and 'aci4_score' in k1_baseline:
            baseline_scores['avg_aci4'] = k1_baseline['aci4_score']

        if baseline_scores:
            segment_aci_scores[1] = baseline_scores

    @staticmethod
    def _determine_k_values(target_k, num_samples):
        """Determine k values to process"""
        k_values = []
        if target_k and isinstance(target_k, list):
            k_values = [k for k in target_k if k < num_samples]
        elif target_k and isinstance(target_k, int):
            k_values = [target_k] if target_k < num_samples else []

        return k_values

    def _perform_clustering_for_k(self, k, frequencywise_scaled, dataset_type, pretrained_models,
                                models_base_dir, head_name, segment_name, unique_frequencies,
                                segment_file_dict=None, model_save_dir=None, features_list=None):
        """Perform clustering for a specific k value"""
        try:
            if dataset_type == 'train':
                return self._train_new_model(k, frequencywise_scaled, models_base_dir, head_name, segment_name,
                                            unique_frequencies, segment_file_dict=segment_file_dict,
                                            model_save_dir=model_save_dir, features_list=features_list)
            else:
                km, file_labels = self._use_pretrained_model(k, frequencywise_scaled, pretrained_models)
                return km, file_labels, None
        except Exception as e:
            self.logger.warning(f"    Unexpected error in TimeSeriesKMeans for k={k}: {e}")
            return None, None, None

    def _train_new_model(self, k, frequencywise_scaled, models_base_dir, head_name, segment_name,
                        unique_frequencies, segment_file_dict=None, model_save_dir=None,
                        features_list=None, save_outputs=True):
        """Train a new clustering model"""
        self.logger.info(f"    Training new model for k={k}")

        # Validate data
        if not self._validate_scaled_data(frequencywise_scaled, k):
            return None, None, None

        # Create and train model
        km = TimeSeriesKMeans(
            n_clusters=k,
            metric="euclidean",
            random_state=0,
            max_iter=300,
            verbose=0
        )

        start_time = time.time()
        file_labels = km.fit_predict(frequencywise_scaled)
        elapsed_time = time.time() - start_time

        self.logger.info(f"      Clustering completed in {elapsed_time:.2f} seconds")
        self.logger.info(f"      Clustering completed in {km.n_iter_} iterations")

        # Validate results
        self._validate_clustering_results(km, file_labels, k)

        segment_models_dir = None
        if save_outputs:
            segment_models_dir = self._resolve_and_save_model(
                km, k, model_save_dir, models_base_dir, head_name, segment_name,
                unique_frequencies, features_list
            )

        # Calculate cluster means from actual data and save centroid files
        if segment_file_dict is not None:
            cluster_means = self._calculate_cluster_means(
                segment_file_dict, file_labels, k, unique_frequencies
            )
            if segment_models_dir is not None:
                self.model_save.save_centroid_data_files(
                    cluster_means, segment_models_dir, unique_frequencies, k
                )
        else:
            cluster_means = None

        return km, file_labels, cluster_means

    def _resolve_and_save_model(self, km, k, model_save_dir, models_base_dir, head_name,
                                 segment_name, unique_frequencies, features_list):
        """Resolve the model save directory, write model.json and (when features_list is
        given) the model_centroid data files. Returns the resolved directory."""
        # Resolve save directory: use explicit override if provided, otherwise build default path
        if model_save_dir is not None:
            segment_models_dir = model_save_dir
        else:
            segment_models_dir = os.path.join(models_base_dir, head_name, segment_name, f'k_{k}')
        os.makedirs(segment_models_dir, exist_ok=True)

        json_path = os.path.join(segment_models_dir, MODEL_NAME)
        self.model_save.save_model(km, json_path, format='json')
        self.logger.info(f"      Saved model: {json_path}")

        if features_list is not None:
            self.model_save.save_model_centroid_data_files(
                km.cluster_centers_, segment_models_dir, unique_frequencies, k, features_list
            )
        return segment_models_dir

    def _use_pretrained_model(self, k, frequencywise_scaled, pretrained_models):
        """Use pretrained model for prediction"""
        # validation: Use pretrained model
        if pretrained_models and k in pretrained_models:
            km = pretrained_models[k]
            file_labels = km.predict(frequencywise_scaled)
            self.logger.info(f"      Using pretrained model for k={k}")
            return km, file_labels
        else:
            self.logger.warning(f"      Warning: No pretrained model for k={k}, skipping")
            return None, None

    def _validate_scaled_data(self, frequencywise_scaled, k):
        """Validate scaled data before clustering"""
        if np.any(np.isnan(frequencywise_scaled)) or np.any(np.isinf(frequencywise_scaled)):
            self.logger.warning(f"    Scaled data contains NaN or Inf values for k={k}")
            return False

        data_variance = np.var(frequencywise_scaled)
        if data_variance < 1e-10:
            self.logger.warning(f"    Very low variance in scaled data ({data_variance:.2e})")

        return True

    def _validate_clustering_results(self, km, file_labels, k):
        """Validate clustering results"""
        # Check if clustering succeeded
        if hasattr(km, 'n_iter_'):
            if km.n_iter_ >= km.max_iter:
                self.logger.warning(f"      Clustering reached max iterations ({km.max_iter})")

        # Validate cluster assignments
        unique_labels = np.unique(file_labels)
        if len(unique_labels) != k:
            self.logger.warning(f"      Expected {k} clusters, but got {len(unique_labels)} clusters")
            self.logger.warning(f"      Some clusters may be empty")

        # Check cluster sizes
        for label in unique_labels:
            cluster_size = np.sum(file_labels == label)
            if cluster_size == 1:
                self.logger.warning(f"      Cluster {label} has only 1 member")
            elif cluster_size < 3:
                self.logger.warning(f"      Cluster {label} has only {cluster_size} members")

    @staticmethod
    def _calculate_cluster_means(segment_file_dict, file_labels, k, unique_frequencies):
        """Calculate per-cluster arithmetic mean of real and imaginary data from segment_file_dict"""
        n_frequencies = len(unique_frequencies)
        cluster_means = np.zeros((k, n_frequencies, 2))

        for cluster_id in range(k):
            real_sum = np.zeros(n_frequencies)
            imag_sum = np.zeros(n_frequencies)
            count = 0

            for file_idx, (original_file_idx, data) in enumerate(segment_file_dict['files'].items()):
                if file_labels[file_idx] == cluster_id:
                    real_sum += data['real']
                    imag_sum += data['imaginary']
                    count += 1

            if count > 0:
                cluster_means[cluster_id, :, 0] = real_sum / count
                cluster_means[cluster_id, :, 1] = imag_sum / count

        return cluster_means

    @staticmethod
    def _count_files_by_source(segment_file_dict, file_labels, k):
        real_counts = [0] * k
        worst_counts = [0] * k
        for file_idx, file_data in enumerate(segment_file_dict['files'].values()):
            cluster_id = int(file_labels[file_idx])
            if file_data.get('is_worst_model', False):
                worst_counts[cluster_id] += 1
            else:
                real_counts[cluster_id] += 1
        return real_counts, worst_counts

    def _generate_all_plots(self, segment_file_dict, file_labels, segment_name, k_dir, head_name,
                        k, cluster_colors, cluster_means, unique_frequencies,
                        generate_interactive_html_plots=True, merge_annotation=None, original_k=None):
        """Generate all visualization plots"""
        bode_kwargs = {'merge_annotation': merge_annotation} if merge_annotation else {}
        origk_kwargs = {'pre_merge_k': original_k} if original_k is not None else {}

        # Static Bode means grid
        real_counts, worst_counts = self._count_files_by_source(segment_file_dict, file_labels, k)
        self.execute_plot.execute_plot_in_process(
            self.plot_interactive_bode.create_static_bode_centroids_grid,
            cluster_means, unique_frequencies, k, cluster_colors, segment_name, k_dir, head_name,
            file_labels, real_counts=real_counts, worst_counts=worst_counts,
            **bode_kwargs, **origk_kwargs
        )
        self.logger.info(f"      Generated static centroid Bode plots")

        # Bode centroid metrics: raw + trend, detrended, normalized
        self.execute_plot.execute_plot_in_process(
            self.plot_interactive_bode.create_bode_centroid_metrics,
            cluster_means, unique_frequencies, k, cluster_colors, segment_name, k_dir, head_name,
            file_labels, **bode_kwargs, **origk_kwargs
        )
        self.logger.info(f"      Generated Bode centroid metrics plot")

        # Frequency vs gain/phase grid
        self.execute_plot.execute_plot_in_process(
            self.plot_grid.create_frequency_gain_phase_grid,
            segment_file_dict, file_labels, segment_name, k_dir, k, head_name, cluster_colors,
            **origk_kwargs
        )
        self.logger.info(f"      Generated frequency-gain-phase grid")

        # Interactive Bode plots
        if generate_interactive_html_plots:
            self.execute_plot.execute_plot_in_process(
                self.plot_interactive_bode.create_interactive_bode_plots,
                segment_file_dict, file_labels, segment_name, k_dir, k, head_name,
                cluster_colors, cluster_means, **bode_kwargs, **origk_kwargs
            )
            self.logger.info(f"      Generated interactive Bode plots")

        # 3D visualization (static only)
        self.execute_plot.execute_plot_in_process(
            self.plot_3d.create_3d_visualization,
            segment_file_dict, segment_name, k_dir, head_name,
            file_labels, k, cluster_colors, cluster_means, **origk_kwargs
        )
        self.logger.info(f"      Generated 3D visualization")

        # 3D means-only
        self.execute_plot.execute_plot_in_process(
            self.plot_3d.create_3d_centroids_only,
            cluster_means, unique_frequencies, k, cluster_colors, segment_name, k_dir, head_name,
            **origk_kwargs
        )
        self.logger.info(f"      Generated 3D centroid-only plot")

        # Interactive 3D visualization
        if generate_interactive_html_plots:
            self.execute_plot.execute_plot_in_process(
                self.plot_3d.create_interactive_3d_visualization,
                segment_file_dict, segment_name, k_dir, head_name,
                file_labels, k, cluster_colors, cluster_means, **origk_kwargs
            )
            self.logger.info(f"      Generated interactive 3D visualization")

    @staticmethod
    def _build_merge_outcome(merge_result, model_json_path, avg_scores,
                              pre_merge_scores, metrics_to_use):
        """Compare pre- and post-merge centroid scores and package the merge outcome."""
        delta, is_better = FRFClusteringBase._compute_score_delta(
            avg_scores, pre_merge_scores, metrics_to_use
        )
        return {
            'k_merged': merge_result.k_merged,
            'model_path': model_json_path,
            'post_scores': avg_scores or {},
            'delta': delta,
            'is_better': is_better,
        }

    @staticmethod
    def _compute_score_delta(avg_scores, pre_merge_scores, metrics_to_use):
        """Return (delta, is_better) dicts keyed by metric name for common, finite scores"""
        delta, is_better = {}, {}
        if not avg_scores or not pre_merge_scores:
            return delta, is_better
        lower_is_better = {'Correlation'}
        for metric in ('Correlation', 'RMSE', 'Wasserstein'):
            if metric not in metrics_to_use:
                continue
            avg_key = AVG_SCORE_KEYS[metric]
            post = avg_scores.get(avg_key)
            pre = pre_merge_scores.get(avg_key)
            if post is None or pre is None or np.isnan(post) or np.isnan(pre):
                continue
            delta[metric] = post - pre
            is_better[metric] = (post < pre) if metric in lower_is_better else (post > pre)
        return delta, is_better

    def _log_and_save_merge_score_delta(self, delta, k, k_merged, merged_dir, head_name):
        """Log and save the pre- vs post-merge centroid score delta for one k value."""
        if not delta:
            return
        self.logger.info(f"    Merge score delta (k={k} -> {k_merged}): {delta}")
        rows = [{'metric': metric, 'delta_post_minus_pre': value} for metric, value in delta.items()]
        df = pd.DataFrame(rows)
        csv_path = os.path.join(
            merged_dir, f'{head_name}_merge_score_delta_k{k}.csv'
        )
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        self.logger.info(f"    Saved merge score delta CSV: {csv_path}")

    def _compute_merge_passes(self, cluster_means, file_labels, matrices, metrics_to_use,
                               unique_frequencies, k):
        """Run merge pass 1 (execute_merge) and, if it succeeds, pass 2 (_apply_second_pass_merge)"""
        first_pass_result = self.cluster_merger.execute_merge(
            cluster_means, file_labels, matrices, metrics_to_use, unique_frequencies, k
        )
        if first_pass_result is None:
            return None, None
        self.logger.info(
            f"    First-pass merge triggered: {k} -> {first_pass_result.k_merged} clusters"
        )
        composed_result = self._apply_second_pass_merge(
            first_pass_result, metrics_to_use, unique_frequencies
        )
        return first_pass_result, composed_result

    def _run_merge_on_result(self, cluster_means, file_labels, matrices, metrics_to_use,
                              generate_interactive, context, file_data, models_merged_dir=None,
                              feature_data=None, pre_cluster_centers=None, model_settings=None,
                              pre_merge_scores=None, features_list=None):
        """Attempt cluster merge and write merged/ outputs when successful"""
        model_settings = model_settings or MergeModelSettings()
        first_pass_result, composed_result = self._compute_merge_passes(
            cluster_means, file_labels, matrices, metrics_to_use, file_data.unique_frequencies, context.k
        )
        if first_pass_result is None:
            return None, None
        final_merge_result = composed_result if composed_result is not None else first_pass_result

        merged_dir = os.path.join(context.output_dir, 'merged')
        os.makedirs(merged_dir, exist_ok=True)
        context.merged_dir = merged_dir
        snapshot_kwargs = dict(
            file_indices=file_data.file_indices, segment_file_dict=file_data.segment_file_dict,
            unique_frequencies=file_data.unique_frequencies, k=context.k, head_name=context.head_name,
            segment_name=context.segment_name,
            generate_interactive=generate_interactive
        )
        self._write_merge_stage_snapshot(final_merge_result, merged_dir, **snapshot_kwargs)

        return self._write_merge_outputs(
            final_merge_result, models_merged_dir, file_labels, metrics_to_use,
            context, file_data, feature_data=feature_data,
            pre_cluster_centers=pre_cluster_centers, model_settings=model_settings,
            pre_merge_scores=pre_merge_scores, features_list=features_list
        )

    def _write_merge_stage_snapshot(self, merge_result, snapshot_dir, file_indices,
                                     segment_file_dict, unique_frequencies, k, head_name,
                                     segment_name, generate_interactive):
        """Write the final merge result's plain output"""
        os.makedirs(snapshot_dir, exist_ok=True)
        stage_colors = self._get_colors_for_k(merge_result.k_merged)
        self._generate_all_plots(
            segment_file_dict, merge_result.merged_labels, segment_name, snapshot_dir,
            head_name, merge_result.k_merged, stage_colors, merge_result.merged_means,
            unique_frequencies, generate_interactive, merge_result.annotation,
            original_k=k
        )
        self._save_drive_cluster_mapping(
            segment_file_dict, merge_result.merged_labels, file_indices,
            merge_result.k_merged, snapshot_dir, head_name,
            original_k=k
        )

    def _write_merge_outputs(self, merge_result, models_merged_dir, file_labels, metrics_to_use,
                              context, file_data, feature_data=None, pre_cluster_centers=None,
                              model_settings=None, pre_merge_scores=None, features_list=None):
        """Run the forward-pass convergence loop on the final merge grouping"""
        model_settings = model_settings or MergeModelSettings()
        centers, final_merge_result = self._reconcile_merge_result(
            merge_result, feature_data, file_labels, context, file_data,
            pre_cluster_centers, model_settings
        )
        avg_scores, _ = self._compute_and_plot_merged_centroid_metrics(
            final_merge_result.merged_means, file_data.unique_frequencies, metrics_to_use,
            final_merge_result.k_merged, context.k, context.segment_name, context.head_name,
            context.merged_dir
        )
        outcome = self._finalize_merge_model(
            final_merge_result, centers, models_merged_dir, file_data.unique_frequencies,
            feature_data, model_settings, avg_scores, pre_merge_scores, metrics_to_use,
            context, features_list=features_list
        )
        self.logger.info(f"    Merge output written to: {context.merged_dir}")
        return outcome, final_merge_result

    def _fit_combined_forward_pass(self, cluster_means, file_labels, segment_file_dict,
                                    unique_frequencies, k, models_combined_dir, feature_data,
                                    features_list, model_metric='euclidean', model_random_state=0):
        """Run the bounded forward-pass convergence loop directly on a combination's own raw cluster assignments"""
        if models_combined_dir is None:
            return None, None
        identity_result = self._build_identity_merge_result(cluster_means, file_labels, k)
        centers = self._build_merged_centers(identity_result, feature_data, file_labels, None)
        centers, final_labels, _ = self._run_forward_pass_loop(
            centers, feature_data, file_labels, k,
            MergeContext(head_name=None, segment_name=None, dataset_type=None),
            MergeFileData(segment_file_dict, unique_frequencies, None),
            MergeModelSettings(model_metric, model_random_state),
            save_iterations=False, verbose=False
        )
        final_means = self._calculate_cluster_means(
            segment_file_dict, final_labels, k, unique_frequencies
        )
        final_result = MergeResult(final_means, final_labels, k, '')
        self._finalize_combined_model(
            final_result, centers, models_combined_dir, unique_frequencies, features_list
        )
        return final_labels, final_means

    @staticmethod
    def _build_identity_merge_result(cluster_means, file_labels, k):
        """Build a MergeResult representing 'no merge'"""
        merge_groups = [[c] for c in range(k)]
        label_map = {c: c for c in range(k)}
        return MergeResult(cluster_means, file_labels, k, '', merge_groups=merge_groups,
                            label_map=label_map)

    def _finalize_combined_model(self, final_result, centers, models_combined_dir,
                                  unique_frequencies, features_list):
        """Persist combined centroid files and the combined model.json"""
        if models_combined_dir is None:
            return
        self.cluster_merger.save_merged_centroids(
            final_result.merged_means, models_combined_dir, unique_frequencies,
            final_result.k_merged, self.model_save
        )
        if centers is None:
            return
        self.cluster_merger.save_merged_model(
            centers, final_result.k_merged, 'euclidean', 0, models_combined_dir, self.model_save
        )
        if features_list is not None:
            self.model_save.save_model_centroid_data_files(
                centers, models_combined_dir, unique_frequencies, final_result.k_merged, features_list
            )

    def _apply_second_pass_merge(self, first_pass_result, metrics_to_use, unique_frequencies):
        """Re-run the merge criterion once more on the first pass's merged centroids,
        catching pairs that only become mergeable after their neighbours already merged"""
        if not any(m in CENTROID_METRIC_NAMES for m in metrics_to_use):
            return None
        _, matrices = self.centroid_calculator.compute_centroid_metrics(
            first_pass_result.merged_means, unique_frequencies, metrics_to_use
        )
        second_pass_result = self.cluster_merger.execute_merge(
            first_pass_result.merged_means, first_pass_result.merged_labels, matrices,
            metrics_to_use, unique_frequencies, first_pass_result.k_merged
        )
        if second_pass_result is None:
            return None
        self.logger.info(
            f"    Second-pass merge triggered: {first_pass_result.k_merged} -> "
            f"{second_pass_result.k_merged} clusters"
        )
        return self.cluster_merger.compose_sequential_merges(first_pass_result, second_pass_result)

    def _reconcile_merge_result(self, merge_result, feature_data, file_labels,
                                 context, file_data, pre_cluster_centers, model_settings,
                                 save_iterations=True):
        """Run the bounded forward-pass convergence loop on top of merge_result (the
        final merge grouping) and return the converged labels/means, so predict() on
        the saved model.json reproduces these same labels"""
        if feature_data is None:
            return None, merge_result
        centers = self._build_merged_centers(
            merge_result, feature_data, file_labels, pre_cluster_centers
        )
        centers, final_labels, deviations = self._run_forward_pass_loop(
            centers, feature_data, merge_result.merged_labels, merge_result.k_merged,
            context, file_data, model_settings, save_iterations=save_iterations
        )
        self._plot_merge_convergence(
            deviations, merge_result.k_merged, context.k, context.output_dir,
            context.head_name, context.segment_name
        )
        final_means = self._calculate_cluster_means(
            file_data.segment_file_dict, final_labels, merge_result.k_merged, file_data.unique_frequencies
        )
        reconciled = MergeResult(
            final_means, final_labels, merge_result.k_merged, merge_result.annotation,
            merge_result.merge_groups, merge_result.label_map
        )
        return centers, reconciled

    def _build_merged_centers(self, merge_result, feature_data, file_labels, pre_cluster_centers):
        """Build post-merge cluster centers in feature space via a single averaging pass"""
        if pre_cluster_centers is not None:
            return self.cluster_merger.build_merged_model_centroids(
                pre_cluster_centers, merge_result, feature_data, file_labels
            )
        return self.cluster_merger.build_consolidated_model_centroids(
            merge_result, feature_data, file_labels
        )

    def _run_forward_pass_loop(self, initial_centers, feature_data, initial_labels, k_merged,
                                context, file_data, model_settings, save_iterations=True,
                                verbose=True):
        """Bounded iterative nearest-centroid refinement """
        cluster_colors = self._get_colors_for_k(k_merged)
        old_centers, old_labels = initial_centers, initial_labels
        deviations = []
        for pass_num in range(1, MAX_FORWARD_PASSES + 1):
            km = TimeSeriesKMeans(
                n_clusters=k_merged, metric=model_settings.model_metric, init=old_centers,
                n_init=1, max_iter=1, random_state=model_settings.model_random_state, verbose=0
            )
            new_labels = km.fit_predict(feature_data)
            new_centers = km.cluster_centers_
            deviation = int(np.sum(new_labels != old_labels))
            deviations.append(deviation)
            if verbose:
                self.logger.info(
                    f"    Forward pass {pass_num}: {deviation} file(s) reassigned "
                    f"(k_merged={k_merged}, origk={context.k})"
                )
            if save_iterations:
                self._write_forward_pass_iteration_outputs(
                    file_data.segment_file_dict, new_labels, file_data.unique_frequencies, k_merged,
                    cluster_colors, context.merged_dir, context.head_name, context.segment_name, pass_num,
                    file_data.file_indices, original_k=context.k
                )
            old_centers, old_labels = new_centers, new_labels
            if self._deviations_have_plateaued(deviations):
                break
        return old_centers, old_labels, deviations

    @staticmethod
    def _deviations_have_plateaued(deviations):
        """True once the last CONVERGENCE_PLATEAU_WINDOW deviation counts are all within
        CONVERGENCE_PLATEAU_TOLERANCE files of each other."""
        if len(deviations) < CONVERGENCE_PLATEAU_WINDOW:
            return False
        window = deviations[-CONVERGENCE_PLATEAU_WINDOW:]
        return (max(window) - min(window)) <= CONVERGENCE_PLATEAU_TOLERANCE

    def _write_forward_pass_iteration_outputs(self, segment_file_dict, labels, unique_frequencies,
                                               k_merged, cluster_colors, merged_dir, head_name,
                                               segment_name, pass_num, file_indices, original_k=None):
        """Generate the static Bode-centroid, Bode-centroid-metric, and frequency-gain-
        phase plots, plus the drive-cluster-mapping CSV, for one forward-pass iteration —
        all under merged_dir/iterations/iter_{pass_num:02d}/"""
        iter_dir = os.path.join(merged_dir, 'iterations', f'iter_{pass_num:02d}')
        os.makedirs(iter_dir, exist_ok=True)
        origk_kwargs = {'pre_merge_k': original_k} if original_k is not None else {}
        iter_means = self._calculate_cluster_means(
            segment_file_dict, labels, k_merged, unique_frequencies
        )
        real_counts, worst_counts = self._count_files_by_source(segment_file_dict, labels, k_merged)
        self.execute_plot.execute_plot_in_process(
            self.plot_interactive_bode.create_static_bode_centroids_grid,
            iter_means, unique_frequencies, k_merged, cluster_colors, segment_name, iter_dir,
            head_name, labels, real_counts=real_counts, worst_counts=worst_counts, **origk_kwargs
        )
        self.execute_plot.execute_plot_in_process(
            self.plot_interactive_bode.create_bode_centroid_metrics,
            iter_means, unique_frequencies, k_merged, cluster_colors, segment_name, iter_dir,
            head_name, labels, **origk_kwargs
        )
        self.execute_plot.execute_plot_in_process(
            self.plot_grid.create_frequency_gain_phase_grid,
            segment_file_dict, labels, segment_name, iter_dir, k_merged, head_name, cluster_colors,
            **origk_kwargs
        )
        self._save_drive_cluster_mapping(
            segment_file_dict, labels, file_indices, k_merged, iter_dir,
            head_name, original_k=original_k
        )

    def _plot_merge_convergence(self, deviations, k_merged, original_k, output_dir,
                                 head_name, segment_name):
        """Plot the per-pass file-reassignment deviation curve into output_dir (k_dir)."""
        if not deviations:
            return
        self.execute_plot.execute_plot_in_process(
            self.centroid_plotter.plot_convergence_curve,
            deviations, k_merged, original_k, segment_name, output_dir, head_name
        )

    def _finalize_merge_model(self, merge_result, centers, models_merged_dir, unique_frequencies,
                               feature_data, model_settings, avg_scores, pre_merge_scores,
                               metrics_to_use, context, features_list=None):
        """Persist merged centroid files, save the merged model.json, and record the score delta."""
        if models_merged_dir is None:
            return None
        self.cluster_merger.save_merged_centroids(
            merge_result.merged_means, models_merged_dir, unique_frequencies,
            merge_result.k_merged, self.model_save
        )
        if feature_data is None or centers is None:
            return None
        model_json_path = self.cluster_merger.save_merged_model(
            centers, merge_result.k_merged, model_settings.model_metric,
            model_settings.model_random_state, models_merged_dir, self.model_save
        )
        if features_list is not None:
            self.model_save.save_model_centroid_data_files(
                centers, models_merged_dir, unique_frequencies, merge_result.k_merged, features_list
            )
        outcome = self._build_merge_outcome(
            merge_result, model_json_path, avg_scores,
            pre_merge_scores, metrics_to_use
        )
        self._log_and_save_merge_score_delta(
            outcome['delta'], context.k, merge_result.k_merged, context.merged_dir, context.head_name
        )
        return outcome

    def _compute_and_plot_merged_centroid_metrics(self, merged_means, unique_frequencies,
                                                   metrics_to_use, k_merged, original_k,
                                                   segment_name, head_name, merged_dir,
                                                   save_heatmaps=True):
        """Compute pairwise centroid metrics for the merged result and plot a heatmap"""
        if not any(m in CENTROID_METRIC_NAMES for m in metrics_to_use):
            return {}, {}
        avg_scores, matrices = self.centroid_calculator.compute_centroid_metrics(
            merged_means, unique_frequencies, metrics_to_use
        )
        if avg_scores:
            self.logger.info(f"    Merged centroid metrics ({k_merged} clusters): {avg_scores}")
        if matrices and save_heatmaps:
            metric_results_dir = os.path.join(merged_dir, 'metric_results')
            os.makedirs(metric_results_dir, exist_ok=True)
            cluster_labels = [f'Cluster {i}' for i in range(len(merged_means))]
            label = f'origk{original_k}_merged_k{k_merged}'
            self.execute_plot.execute_plot_in_process(
                self.centroid_plotter.plot_centroid_heatmaps,
                matrices, k_merged, segment_name, metric_results_dir,
                head_name, metrics_to_use, label, cluster_labels
            )
        return avg_scores, matrices
