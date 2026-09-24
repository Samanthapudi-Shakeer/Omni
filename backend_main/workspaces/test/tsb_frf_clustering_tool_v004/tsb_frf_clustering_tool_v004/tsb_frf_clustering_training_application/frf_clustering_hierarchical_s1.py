# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_clustering_hierarchical_s1.py
*  File Description: Two-stage hierarchical TimeSeriesKMeans clustering engine.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import numpy as np
import pandas as pd
from frf_clustering_utils import FrequencyACIMetricsConfig, HierarchicalRunAccumulators, SharedStage2Data
from frf_clustering_base import FRFClusteringBase, MODEL_NAME
from frf_centroid_metrics import CENTROID_METRIC_NAMES, OPT_KEYS, AVG_SCORE_KEYS
from frf_clustering_hierarchical_s2 import HierarchicalStage2Mixin


class Stage1ClusteringResult(object):
    """Bundles stage-1 model outputs passed to _process_stage1_outputs."""

    def __init__(self, labels, means, km, colors):
        self.labels = labels
        self.means = means
        self.km = km
        self.colors = colors


class FRFHierarchicalClusteringEngine(HierarchicalStage2Mixin, FRFClusteringBase):
    """Handles two-stage hierarchical clustering execution, model management, and plot generation"""

    def perform_hierarchical_clustering(self, frequencywise_data_stage1, file_indices,
                                        unique_frequencies, segment_file_dict, config):
        """Perform two-stage hierarchical TimeSeriesKMeans clustering"""
        setup = self._setup_hierarchical_run(
            frequencywise_data_stage1, file_indices, unique_frequencies, segment_file_dict, config
        )
        if setup is None:
            return {}, {}, {}

        dataset_dir, scaled_s1, k1_baseline, \
            stage1_k_values, stage2_k_values, segment_models_base, \
            shared_scaled_s2, orig_to_row_s2 = setup

        accumulators = HierarchicalRunAccumulators()

        for parent_k in stage1_k_values:
            self.logger.info(f"  [HIERARCHICAL {config.dataset_type.upper()}] Stage 1 k={parent_k}")
            self._process_parent_k(
                parent_k, frequencywise_data_stage1, scaled_s1,
                file_indices, unique_frequencies, segment_file_dict, config,
                dataset_dir, stage2_k_values, segment_models_base, accumulators,
                shared_scaled_s2, orig_to_row_s2
            )

        return self._finalize_hierarchical_run(
            accumulators.hierarchical_entries, k1_baseline, config, dataset_dir,
            accumulators.centroid_scores, all_merge_outcomes=accumulators.merge_outcomes
        )

    def _setup_hierarchical_run(self, frequencywise_data_stage1, file_indices,
                                unique_frequencies, segment_file_dict, config):
        """Prepare output directory, normalization, k=1 baseline, and k-value lists"""
        if config.output_dir_is_final:
            dataset_dir = config.segment_dir
        else:
            dataset_dir = os.path.join(config.segment_dir, config.dataset_type)
        os.makedirs(dataset_dir, exist_ok=True)

        if config.generate_segment_overview:
            if not self._create_segment_overview(segment_file_dict, config.segment_name,
                                                  dataset_dir, config.head_name):
                return None
        else:
            self.logger.info(
                f"  Segment overview skipped for group-level processing of {config.segment_name}")

        group_label = getattr(config, 'group_label', None)
        segment_models_base = self._build_segment_models_base(
            config.models_base_dir, config.head_name, config.segment_name, group_label
        )

        scaled_s1 = self._normalize_stage1(frequencywise_data_stage1, config, unique_frequencies)

        k1_baseline = self._calculate_k1_baseline(
            frequencywise_data_stage1, file_indices, unique_frequencies,
            segment_file_dict, config.metrics_to_use, config.dataset_type
        )

        stage1_k_values, stage2_k_values = self._resolve_k_values(
            config, len(frequencywise_data_stage1)
        )

        shared_scaled_s2, orig_to_row_s2 = self._compute_shared_stage2_normalization(
            segment_file_dict, file_indices, unique_frequencies, config
        )

        return dataset_dir, scaled_s1, k1_baseline, \
            stage1_k_values, stage2_k_values, segment_models_base, \
            shared_scaled_s2, orig_to_row_s2

    def _normalize_stage1(self, frequencywise_data_stage1, config, unique_frequencies):
        """Scale stage 1 data (per-file normalize-to-[-1,1] + detrend)."""
        return self._scale_frequencywise_data(
            frequencywise_data_stage1, config.stage1_feature_weights, unique_frequencies
        )

    def _resolve_k_values(self, config, n_files):
        """Resolve stage1 and stage2 k-value lists from config.target_k."""
        if isinstance(config.target_k, tuple) and len(config.target_k) == 2:
            stage1_k_values = self._determine_k_values(config.target_k[0], n_files)
            stage2_k_values = self._determine_k_values(config.target_k[1], n_files)
        else:
            stage1_k_values = self._determine_k_values(config.target_k, n_files)
            stage2_k_values = stage1_k_values
        self.logger.info(
            f" [{config.dataset_type.upper()}] Performing TimeSeriesKMeans clustering for "
            f"stage1_k={stage1_k_values}, stage2_k={stage2_k_values}"
        )
        return stage1_k_values, stage2_k_values

    def _process_parent_k(self, parent_k, frequencywise_data_stage1, scaled_s1,
                           file_indices, unique_frequencies, segment_file_dict, config,
                           dataset_dir, stage2_k_values, segment_models_base, accumulators,
                           shared_scaled_s2=None, orig_to_row_s2=None):
        """Run the full pipeline for a single stage-1 k value."""
        stage1_k_dir = os.path.join(dataset_dir, f'stage1_k_{parent_k}')
        os.makedirs(stage1_k_dir, exist_ok=True)

        stage1_models_dir = os.path.join(segment_models_base, f'stage1_k_{parent_k}')
        os.makedirs(stage1_models_dir, exist_ok=True)

        km_s1, labels_s1, means_s1 = self._run_stage1_clustering(
            parent_k, scaled_s1, unique_frequencies, segment_file_dict, config, stage1_models_dir
        )
        if km_s1 is None or labels_s1 is None:
            self.logger.warning(f"  Stage 1 k={parent_k} failed, skipping")
            return

        stage1_result = Stage1ClusteringResult(
            labels=labels_s1,
            means=means_s1,
            km=km_s1,
            colors=self._get_colors_for_k(parent_k)
        )
        self._process_stage1_outputs(
            parent_k, frequencywise_data_stage1,
            file_indices, unique_frequencies, segment_file_dict,
            stage1_result, stage1_k_dir, config, accumulators.hierarchical_entries
        )

        stage2_results = self._process_all_stage2_clusters(
            parent_k, labels_s1, file_indices, unique_frequencies, segment_file_dict,
            config, stage1_k_dir, stage2_k_values, segment_models_base
        )

        final_dir = os.path.join(stage1_k_dir, 'h_combined')
        os.makedirs(final_dir, exist_ok=True)
        pk_centroid_scores = {}
        metric_results_stage1_dir = os.path.join(
            dataset_dir, 'metric_results', f'stage1_k_{parent_k}'
        )
        self._process_combined_results(
            parent_k, stage2_k_values, stage2_results,
            file_indices, unique_frequencies, segment_file_dict,
            config, final_dir, accumulators,
            pk_centroid_scores, metric_results_stage1_dir,
            segment_models_base=segment_models_base,
            shared_stage2_data=SharedStage2Data(shared_scaled_s2, orig_to_row_s2)
        )
        self._finalise_pk_centroid_metrics(
            parent_k, pk_centroid_scores, config.metrics_to_use, config.segment_name,
            config.head_name, metric_results_stage1_dir, accumulators.centroid_scores
        )

    def _finalise_pk_centroid_metrics(self, parent_k, pk_centroid_scores, metrics_to_use,
                                       segment_name, head_name, metric_results_stage1_dir,
                                       all_centroid_scores):
        """Run elbow detection for one stage1_k and store results in all_centroid_scores."""
        if not pk_centroid_scores or not any(m in CENTROID_METRIC_NAMES for m in metrics_to_use):
            return
        pk_opt = self.centroid_calculator.select_optimal_k(pk_centroid_scores, metrics_to_use)
        if pk_opt:
            os.makedirs(metric_results_stage1_dir, exist_ok=True)
            self.execute_plot.execute_plot_in_process(
                self.centroid_plotter.plot_elbow_curves,
                pk_centroid_scores, pk_opt, segment_name,
                metric_results_stage1_dir, head_name, metrics_to_use,
                k_label=f'stage1k{parent_k}', x_label='Total Clusters'
            )
        all_centroid_scores[parent_k] = {'scores': pk_centroid_scores, 'opt': pk_opt}

    def _run_stage1_clustering(self, parent_k, scaled_s1, unique_frequencies,
                                segment_file_dict, config, stage1_models_dir):
        """Train or load the stage-1 model and return (km, labels, means)."""
        if config.dataset_type == 'train':
            km_s1, labels_s1, means_s1 = self._train_new_model(
                parent_k, scaled_s1, config.models_base_dir,
                config.head_name, config.segment_name,
                unique_frequencies,
                segment_file_dict=segment_file_dict,
                model_save_dir=stage1_models_dir, features_list=config.stage1_features
            )
            if means_s1 is None:
                means_s1 = self._calculate_cluster_means(
                    segment_file_dict, labels_s1, parent_k, unique_frequencies
                )
            return km_s1, labels_s1, means_s1

        km_s1, labels_s1 = self._load_and_predict_hierarchical_stage1(scaled_s1, config, parent_k)
        if km_s1 is None:
            return None, None, None
        means_s1 = self._calculate_cluster_means(
            segment_file_dict, labels_s1, parent_k, unique_frequencies
        )
        return km_s1, labels_s1, means_s1

    def _process_stage1_outputs(self, parent_k, frequencywise_data_stage1,
                             file_indices, unique_frequencies, segment_file_dict,
                             stage1_result, stage1_k_dir, config, all_hierarchical_entries):
        """Generate stage-1 plots, compute ACI metrics, and record the entry."""
        self._generate_all_plots(
            segment_file_dict, stage1_result.labels, config.segment_name,
            stage1_k_dir, config.head_name, parent_k, stage1_result.colors,
            stage1_result.means, unique_frequencies,
            config.generate_interactive_html_plots
        )
        self._save_drive_cluster_mapping(
            segment_file_dict, stage1_result.labels, file_indices, parent_k,
            stage1_k_dir, config.head_name
        )

        metrics_config_s1 = FrequencyACIMetricsConfig(
            k_dir=stage1_k_dir,
            segment_name=config.segment_name,
            head_name=config.head_name,
            metrics_to_use=config.metrics_to_use,
            individual_frequencies_cluster_assignment_plots=config.individual_frequencies_cluster_assignment_plots,
            cluster_colors=stage1_result.colors
        )
        freq_records_s1, success_count_s1 = self._calculate_frequency_aci_metrics(
            frequencywise_data_stage1, file_indices, unique_frequencies,
            segment_file_dict, stage1_result.labels, parent_k,
            metrics_config_s1, cluster_means=stage1_result.means
        )
        avg_scores_s1 = self._calculate_segment_average_scores(
            success_count_s1, freq_records_s1, config.metrics_to_use,
            config.segment_name, parent_k
        )
        if avg_scores_s1:
            all_hierarchical_entries.append({
                'parent_k': parent_k,
                'stage2_k': None,
                'total_clusters': parent_k,
                'is_parent': True,
                **avg_scores_s1
            })
            self.logger.info(f"  [HIERARCHICAL] Stage 1 k={parent_k} scores recorded")

    def _finalize_hierarchical_run(self, all_hierarchical_entries, k1_baseline, config,
                                    dataset_dir, all_centroid_scores, all_merge_outcomes=None):
        """Select optimal k, emit ACI plots, write baseline CSV, and add centroid winners."""
        opt_dict, opt_scores, winning_combinations = self._select_hierarchical_optimal(
            all_hierarchical_entries, k1_baseline, config.metrics_to_use
        )
        self._plot_hierarchical_aci_scores(
            all_hierarchical_entries, k1_baseline, opt_dict, winning_combinations,
            config.metrics_to_use, dataset_dir, config.segment_name, config.head_name
        )
        self._compare_hierarchical_with_baseline(
            all_hierarchical_entries, k1_baseline, config.metrics_to_use,
            dataset_dir, config.head_name
        )
        self._add_centroid_hierarchical_winners(
            all_centroid_scores, config.metrics_to_use,
            opt_dict, opt_scores, winning_combinations, all_merge_outcomes=all_merge_outcomes
        )
        return opt_dict, opt_scores, winning_combinations

    def _add_centroid_hierarchical_winners(self, all_centroid_scores, metrics_to_use,
                                            opt_dict, opt_scores, winning_combinations,
                                            all_merge_outcomes=None):
        """Find global best centroid winners and merge into opt_dict/opt_scores/winning_combinations."""
        active = [m for m in metrics_to_use if m in CENTROID_METRIC_NAMES]
        all_merge_outcomes = all_merge_outcomes or {}
        for metric in active:
            winner = self._find_best_centroid_winner(all_centroid_scores, metric)
            opt_key = OPT_KEYS[metric]
            if winner is None:
                winning_combinations[opt_key] = None
                continue
            winning_combinations[opt_key] = self._build_winning_combination(
                winner, metric, all_merge_outcomes
            )
            opt_dict[opt_key] = winner['total_clusters']
            opt_scores[opt_key] = winner.get('score', np.nan)
            self.logger.info(
                f"  [HIERARCHICAL] Centroid optimal for {opt_key}: "
                f"parent_k={winner['parent_k']}, total_clusters={winner['total_clusters']}, "
                f"score={winner.get('score', float('nan')):.4f}"
            )

    @staticmethod
    def _build_winning_combination(winner, metric, all_merge_outcomes):
        """Attach merge-model info to a winning combination when the merge beat the pre-merge score."""
        combo = {k: v for k, v in winner.items() if k != 'score'}
        outcome = all_merge_outcomes.get((winner['parent_k'], winner['total_clusters']))
        if outcome and outcome['is_better'].get(metric):
            combo['is_merged'] = True
            combo['merged_model_path'] = outcome['model_path']
        else:
            combo['is_merged'] = False
        return combo

    def _find_best_centroid_winner(self, all_centroid_scores, metric):
        """Return the best-in-direction (parent_k, total_clusters) entry for one centroid metric."""
        # Direction lookup: True = lower is better, False = higher is better
        is_decreasing = {'Correlation': True, 'RMSE': False, 'Wasserstein': False}[metric]
        score_key = AVG_SCORE_KEYS[metric]
        opt_key = OPT_KEYS[metric]
        best_score = None
        best_entry = None

        for parent_k, pk_data in all_centroid_scores.items():
            pk_opt = pk_data.get('opt', {})
            pk_scores_dict = pk_data.get('scores', {})
            total_clusters = pk_opt.get(opt_key)
            if total_clusters is None:
                continue
            score = pk_scores_dict.get(total_clusters, {}).get(score_key)
            if score is None or np.isnan(score):
                continue
            is_better = (best_score is None or
                         (is_decreasing and score < best_score) or
                         (not is_decreasing and score > best_score))
            if is_better:
                best_score = score
                best_entry = {
                    'parent_k': parent_k,
                    'total_clusters': total_clusters,
                    'stage2_k': total_clusters // parent_k,
                    'is_parent': False,
                    'score': score,
                }
        return best_entry

    def _select_hierarchical_optimal(self, all_hierarchical_entries, k1_baseline, metrics_to_use):
        """Select globally optimal cluster count per metric across all hierarchical entries"""
        metric_handlers = {
            'ACI1': ('aci1_score', 'avg_aci1'),
            'ACI2': ('aci2_score', 'avg_aci2'),
            'ACI3': ('aci3_score', 'avg_aci3'),
            'ACI4': ('aci4_score', 'avg_aci4')
        }
        opt_dict = {}
        opt_scores = {}
        winning_combinations = {}

        for metric in ['ACI1', 'ACI2', 'ACI3', 'ACI4']:
            metric_lower = metric.lower()
            if metric not in metrics_to_use:
                opt_dict[metric_lower] = 1
                opt_scores[metric_lower] = np.nan
                winning_combinations[metric_lower] = None
                continue

            baseline_key, avg_key = metric_handlers[metric]
            baseline_score = k1_baseline.get(baseline_key, 0) if k1_baseline else 0

            best_total_clusters = 1
            best_score = baseline_score
            best_entry = None

            for entry in all_hierarchical_entries:
                score = entry.get(avg_key)
                if score is not None and score > baseline_score and score > best_score:
                    best_score = score
                    best_total_clusters = entry['total_clusters']
                    best_entry = entry

            opt_dict[metric_lower] = best_total_clusters
            opt_scores[metric_lower] = best_score

            # Record which (parent_k, stage2_k) combination won for this metric
            if best_entry is None:
                # Baseline (k=1) wins — no clustering was beneficial
                winning_combinations[metric_lower] = None
            else:
                winning_combinations[metric_lower] = {
                    'parent_k': best_entry['parent_k'],
                    'stage2_k': best_entry['stage2_k'],
                    'is_parent': best_entry['is_parent']
                }

            self.logger.info(
                f"  [HIERARCHICAL] Global optimal for {metric}: "
                f"total_clusters={best_total_clusters}, score={best_score:.4f}, "
                f"baseline={baseline_score:.4f}"
            )

        return opt_dict, opt_scores, winning_combinations

    def _plot_hierarchical_aci_scores(self, all_hierarchical_entries, k1_baseline, opt_dict,
                                       winning_combinations, metrics_to_use, dataset_dir,
                                       segment_name, head_name):
        """Generate one ACI plot per metric for hierarchical clustering"""
        try:
            self.execute_plot.execute_plot_in_process(
                self.plot_metrics.plot_hierarchical_aci_scores,
                all_hierarchical_entries, k1_baseline, opt_dict, winning_combinations,
                metrics_to_use, dataset_dir, segment_name, head_name
            )
            self.logger.info(f"  [HIERARCHICAL] Generated unified ACI plots at: {dataset_dir}")
        except Exception as e:
            self.logger.error(f"  [HIERARCHICAL] Error creating unified ACI plots: {e}")

    def _compare_hierarchical_with_baseline(self, all_hierarchical_entries, k1_baseline,
                                             metrics_to_use, dataset_dir, head_name):
        """Save a single unified k=1 comparison CSV covering all hierarchical combinations."""
        if not all_hierarchical_entries or not k1_baseline:
            return

        rows = [
            self._build_baseline_comparison_row(entry, k1_baseline, metrics_to_use)
            for entry in all_hierarchical_entries
        ]

        self._write_hierarchical_comparison_csv(rows, dataset_dir, head_name)

    def _build_baseline_comparison_row(self, entry, k1_baseline, metrics_to_use):
        """Build a single comparison row for hierarchical k=1 baseline CSV."""
        metric_handlers = {
            'ACI1': ('aci1_score', 'avg_aci1'),
            'ACI2': ('aci2_score', 'avg_aci2'),
            'ACI3': ('aci3_score', 'avg_aci3'),
            'ACI4': ('aci4_score', 'avg_aci4')
        }
        stage2_k_value = entry['stage2_k'] if entry['stage2_k'] is not None else 'N/A (parent)'
        row = {
            'parent_k': entry['parent_k'],
            'stage2_k': stage2_k_value,
            'total_clusters': entry['total_clusters'],
            'is_parent': entry['is_parent']
        }
        for metric in metrics_to_use:
            if metric not in metric_handlers:
                continue
            baseline_key, avg_key = metric_handlers[metric]
            score = entry.get(avg_key, np.nan)
            baseline = k1_baseline.get(baseline_key, np.nan)
            row[f'{metric}_score'] = score
            row[f'{metric}_baseline'] = baseline
            row[f'{metric}_vs_baseline'] = self._calculate_baseline_difference(score, baseline)
        return row

    @staticmethod
    def _calculate_baseline_difference(score, baseline):
        """Calculate the difference between score and baseline, handling NaN values."""
        if np.isnan(score) or np.isnan(baseline):
            return np.nan
        return score - baseline

    def _write_hierarchical_comparison_csv(self, rows, dataset_dir, head_name):
        """Write hierarchical comparison rows to CSV file."""
        if not rows:
            return
        csv_path = os.path.join(
            dataset_dir,
            f'{head_name}_h_k1_comparison.csv'
        )
        pd.DataFrame(rows).to_csv(csv_path, index=False, encoding='utf-8-sig')
        self.logger.info(f"  [HIERARCHICAL] Saved unified k=1 comparison CSV: {csv_path}")

    def _load_and_predict_hierarchical_stage1(self, frequencywise_scaled, config, parent_k):
        """Load pretrained stage1 model and predict for validation"""
        group_label = getattr(config, 'group_label', None)
        segment_models_base = self._build_segment_models_base(
            config.models_base_dir, config.head_name, config.segment_name, group_label
        )
        model_path = os.path.join(segment_models_base, f'stage1_k_{parent_k}', MODEL_NAME)
        try:
            km = self.model_save.load_model(model_path)
            labels = km.predict(frequencywise_scaled)
            return km, labels
        except Exception as e:
            self.logger.warning(f"  Could not load stage1 model for k={parent_k}: {e}")
            return None, None
