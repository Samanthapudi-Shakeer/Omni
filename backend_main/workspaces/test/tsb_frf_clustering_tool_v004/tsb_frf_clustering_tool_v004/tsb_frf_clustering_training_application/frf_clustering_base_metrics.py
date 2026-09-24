# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_clustering_base_metrics.py
*  File Description: File providing ACI metrics computation, drive-cluster
*                    mapping, segment scoring, baseline comparison, and
*                    model-registry info helpers shared by clustering engines.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import pandas as pd
import numpy as np


MODEL_NAME = 'model.json'


class FRFClusteringBaseMetrics(object):
    """Mixin providing ACI metrics, drive-cluster mapping, and model-registry helpers"""

    def _get_colors_for_k(self, k):
        """Return cluster color array for k clusters (tab10 for k ≤ 10, HSV otherwise)."""
        if k <= 10:
            return self.generate_colour.get_cluster_colors(k)
        return self.generate_colour.generate_distinct_colors(k)

    @staticmethod
    def _align_shared_feature_data(shared_scaled, orig_to_row, file_indices):
        """Select and order rows of a shared (segment-wide) scaled feature array to match file_indices"""
        if shared_scaled is None or orig_to_row is None:
            return None
        rows = [orig_to_row[oidx] for oidx in file_indices]
        return shared_scaled[rows]

    def _save_drive_cluster_mapping(self, segment_file_dict, file_labels, file_indices, k, k_dir,
                                head_name, original_k=None, name_suffix=None):
        """Save drive-level cluster mapping to CSV."""
        drive_cluster_mapping = []
        for file_idx, original_file_idx in enumerate(file_indices):
            file_data_entry = segment_file_dict['files'][original_file_idx]
            drive_cluster_mapping.append({
                'Drive_name': file_data_entry['filename'],
                'cluster_id': int(file_labels[file_idx])
            })

        if drive_cluster_mapping:
            drive_df = pd.DataFrame(drive_cluster_mapping)
            origk_tag = f'_origk{original_k}' if original_k is not None else ''
            suffix_tag = f'_{name_suffix}' if name_suffix else ''
            drive_path = os.path.join(
                k_dir,
                f'{head_name}_dc{origk_tag}_k{k}{suffix_tag}.csv'
            )
            os.makedirs(os.path.dirname(drive_path), exist_ok=True)
            drive_df.to_csv(drive_path, index=False, encoding='utf-8-sig')
            self.logger.info(f"      Saved drive cluster mapping: {len(drive_df)} drives")

    def _calculate_frequency_aci_metrics(self, frequencywise_data, file_indices, unique_frequencies,
                                    segment_file_dict, file_labels, k, metrics_config,
                                    cluster_means=None):
        """Calculate ACI metrics for all frequencies"""
        frequency_aci_scores = {'aci1': [], 'aci2': [], 'aci3': [], 'aci4': []}
        frequency_metric_records = []
        successful_freq_count = 0
        failed_freq_count = 0

        for freq_idx, frequency in enumerate(unique_frequencies):
            # Extract frequency data
            freq_data = self._extract_frequency_data(
                frequencywise_data, file_indices, segment_file_dict, freq_idx, file_labels
            )

            # Check convex hull
            hull_area = self._check_convex_hull(freq_data['real'], freq_data['imag'])

            if hull_area is None:
                failed_freq_count += 1
                # Create 2D plot if requested
                if metrics_config.individual_frequencies_cluster_assignment_plots and cluster_means is not None:
                    self._create_frequency_2d_plot(
                        freq_data, cluster_means, freq_idx, k, frequency,
                        metrics_config.segment_name, metrics_config.k_dir, metrics_config.head_name,
                        metrics_config.cluster_colors
                    )
                continue

            successful_freq_count += 1

            # Calculate ACI metrics
            aci_results = self._calculate_aci_for_frequency(
                freq_data, k, metrics_config.metrics_to_use
            )

            # Build frequency record
            freq_record = self._build_frequency_record(
                frequency, k, freq_data, aci_results, metrics_config.metrics_to_use
            )
            frequency_metric_records.append(freq_record)

            # Append scores
            self._append_frequency_scores(aci_results, frequency_aci_scores, metrics_config.metrics_to_use)

            # Create plots if requested
            if metrics_config.individual_frequencies_cluster_assignment_plots and cluster_means is not None:
                self._create_frequency_plots(
                    freq_data, cluster_means, freq_idx, k, frequency,
                    metrics_config.segment_name, metrics_config.k_dir, metrics_config.head_name,
                    metrics_config.cluster_colors
                )

        self._log_frequency_processing_summary(
            metrics_config.individual_frequencies_cluster_assignment_plots, successful_freq_count,
            failed_freq_count, len(unique_frequencies)
        )

        return frequency_metric_records, successful_freq_count

    @staticmethod
    def _extract_frequency_data(frequencywise_data, file_indices, segment_file_dict, freq_idx, file_labels):
        """Extract data for a specific frequency — real/imag always from segment_file_dict"""
        freq_real_data = []
        freq_imag_data = []
        freq_gain_data = []
        freq_phase_data = []
        freq_point_labels = []

        for file_idx, original_file_idx in enumerate(file_indices):
            file_data_entry = segment_file_dict['files'][original_file_idx]
            freq_real_data.append(file_data_entry['real'][freq_idx])
            freq_imag_data.append(file_data_entry['imaginary'][freq_idx])
            freq_gain_data.append(file_data_entry['gain'][freq_idx])
            freq_phase_data.append(file_data_entry['phase'][freq_idx])
            freq_point_labels.append(file_labels[file_idx])

        return {
            'real': np.array(freq_real_data),
            'imag': np.array(freq_imag_data),
            'gain': np.array(freq_gain_data),
            'phase': np.array(freq_phase_data),
            'labels': np.array(freq_point_labels)
        }

    def _check_convex_hull(self, real_array, imag_array):
        """Check if convex hull can be created"""
        hull_x, hull_y, hull_area, hull_stats = self.convex_hull_calculater.calculate_convex_hull(
            real_array, imag_array
        )
        return hull_area

    def _calculate_aci_for_frequency(self, freq_data, k, metrics_to_use):
        """Calculate all ACI metrics for a frequency"""
        aci_results = {}

        if 'ACI1' in metrics_to_use:
            aci_results['aci1'] = self.calculate_acis.calculate_evaluation_metric_aci1(
                freq_data['real'], freq_data['imag'], freq_data['gain'], freq_data['phase'],
                freq_data['labels'], k
            )

        if 'ACI2' in metrics_to_use:
            aci_results['aci2'] = self.calculate_acis.calculate_evaluation_metric_aci2(
                freq_data['real'], freq_data['imag'], freq_data['gain'], freq_data['phase'],
                freq_data['labels'], k
            )

        if 'ACI3' in metrics_to_use:
            aci_results['aci3'] = self.calculate_acis.calculate_evaluation_metric_aci3(
                freq_data['real'], freq_data['imag'], freq_data['gain'], freq_data['phase'],
                freq_data['labels'], k
            )

        if 'ACI4' in metrics_to_use:
            aci_results['aci4'] = self.calculate_acis.calculate_evaluation_metric_aci4(
                freq_data['real'], freq_data['imag'], freq_data['gain'], freq_data['phase'],
                freq_data['labels'], k
            )

        return aci_results

    def _build_frequency_record(self, frequency, k, freq_data, aci_results, metrics_to_use):
        """Build frequency metric record"""
        freq_record = {
            'frequency': frequency,
            'k': k,
            'num_points': len(freq_data['real']),
            'convex_hull_area': None,
            'union_fan_area': None,
            'intersection_area': None,
            'uncovered_area': None,
            'excess_fan_area': None,
            'points_in_union': None,
            'points_in_uncovered': None,
            'density': None,
            'dp1': None,
            'ap1': None,
            'ap2': None,
            'aci1_score': None,
            'aci2_score': None,
            'aci3_score': None,
            'aci4_score': None
        }

        # Populate from ACI results
        self._populate_record_from_aci_results(freq_record, aci_results, metrics_to_use)

        return freq_record

    def _populate_record_from_aci_results(self, freq_record, aci_results, metrics_to_use):
        """Populate frequency record from ACI results"""
        if 'ACI1' in metrics_to_use and aci_results.get('aci1'):
            self._update_record_from_aci1(freq_record, aci_results['aci1'])

        if 'ACI2' in metrics_to_use and aci_results.get('aci2'):
            self._update_record_from_aci2(freq_record, aci_results['aci2'])

        if 'ACI3' in metrics_to_use and aci_results.get('aci3'):
            self._update_record_from_aci3(freq_record, aci_results['aci3'])

        if 'ACI4' in metrics_to_use and aci_results.get('aci4'):
            self._update_record_from_aci4(freq_record, aci_results['aci4'])

    @staticmethod
    def _update_record_from_aci1(freq_record, aci1_results):
        """Update record with ACI1 results"""
        freq_record.update({
            'convex_hull_area': aci1_results['convex_hull_area'],
            'union_fan_area': aci1_results['union_fan_area'],
            'intersection_area': aci1_results['intersection_area'],
            'uncovered_area': aci1_results['uncovered_area'],
            'points_in_union': aci1_results['points_in_union'],
            'density': aci1_results['density'],
            'dp1': aci1_results['dp1'],
            'ap1': aci1_results['ap1'],
            'aci1_score': aci1_results['aci1_score']
        })

    @staticmethod
    def _update_record_from_aci2(freq_record, aci2_results):
        """Update record with ACI2 results"""
        if freq_record['convex_hull_area'] is None:
            freq_record.update({
                'convex_hull_area': aci2_results['convex_hull_area'],
                'union_fan_area': aci2_results['union_fan_area'],
                'intersection_area': aci2_results['intersection_area'],
                'uncovered_area': aci2_results['uncovered_area'],
                'points_in_union': aci2_results['points_in_union'],
                'density': aci2_results['density'],
                'dp1': aci2_results['dp1'],
            })
        freq_record['points_in_uncovered'] = aci2_results['points_in_uncovered']
        freq_record['ap2'] = aci2_results['ap2']
        freq_record['aci2_score'] = aci2_results['aci2_score']

    @staticmethod
    def _update_record_from_aci3(freq_record, aci3_results):
        """Update record with ACI3 results"""
        if freq_record['convex_hull_area'] is None:
            freq_record.update({
                'convex_hull_area': aci3_results['convex_hull_area'],
                'union_fan_area': aci3_results['union_fan_area'],
                'intersection_area': aci3_results['intersection_area'],
                'uncovered_area': aci3_results['uncovered_area'],
                'points_in_union': aci3_results['points_in_union'],
                'density': aci3_results['density'],
                'dp1': aci3_results['dp1'],
                'ap1': aci3_results['ap1'],
            })
        freq_record['excess_fan_area'] = aci3_results['excess_fan_area']
        freq_record['aci3_score'] = aci3_results['aci3_score']

    @staticmethod
    def _update_record_from_aci4(freq_record, aci4_results):
        """Update record with ACI4 results"""
        if freq_record['convex_hull_area'] is None:
            freq_record.update({
                'convex_hull_area': aci4_results['convex_hull_area'],
                'union_fan_area': aci4_results['union_fan_area'],
                'intersection_area': aci4_results['intersection_area'],
                'uncovered_area': aci4_results['uncovered_area'],
                'points_in_union': aci4_results['points_in_union'],
                'density': aci4_results['density'],
                'dp1': aci4_results['dp1'],
            })
        if freq_record['points_in_uncovered'] is None:
            freq_record['points_in_uncovered'] = aci4_results['points_in_uncovered']
        if freq_record['ap2'] is None:
            freq_record['ap2'] = aci4_results['ap2']
        freq_record['excess_fan_area'] = aci4_results['excess_fan_area']
        freq_record['aci4_score'] = aci4_results['aci4_score']

    @staticmethod
    def _append_frequency_scores(aci_results, frequency_aci_scores, metrics_to_use):
        """Append frequency scores to collection"""
        if 'ACI1' in metrics_to_use and aci_results.get('aci1'):
            frequency_aci_scores['aci1'].append(aci_results['aci1']['aci1_score'])
        if 'ACI2' in metrics_to_use and aci_results.get('aci2'):
            frequency_aci_scores['aci2'].append(aci_results['aci2']['aci2_score'])
        if 'ACI3' in metrics_to_use and aci_results.get('aci3'):
            frequency_aci_scores['aci3'].append(aci_results['aci3']['aci3_score'])
        if 'ACI4' in metrics_to_use and aci_results.get('aci4'):
            frequency_aci_scores['aci4'].append(aci_results['aci4']['aci4_score'])

    def _create_frequency_2d_plot(self, freq_data, cluster_means, freq_idx,
                                k, frequency, segment_name, k_dir, head_name, cluster_colors):
        """Create 2D plot for frequency (no metrics) using pre-computed cluster means"""
        # Extract per-frequency mean coordinates for all clusters
        freq_cluster_means = cluster_means[:, freq_idx, :]

        self.execute_plot.execute_plot_in_process(
            self.plot_2d.create_2d_frequency_plot,
            freq_data['real'], freq_data['imag'], freq_data['labels'], k,
            frequency, segment_name, k_dir, head_name, cluster_colors, freq_cluster_means
        )

    def _create_frequency_plots(self, freq_data, cluster_means, freq_idx,
                            k, frequency, segment_name, k_dir, head_name, cluster_colors):
        """Create 2D and fan segment plots for frequency using pre-computed cluster means"""
        freq_cluster_means = cluster_means[:, freq_idx, :]

        # 2D plot
        self.execute_plot.execute_plot_in_process(
            self.plot_2d.create_2d_frequency_plot,
            freq_data['real'], freq_data['imag'], freq_data['labels'], k,
            frequency, segment_name, k_dir, head_name, cluster_colors, freq_cluster_means
        )

        # Fan segment plot
        self.execute_plot.execute_plot_in_process(
            self.plot_fan.create_fan_segment_visualization,
            freq_data['real'], freq_data['imag'], freq_data['gain'], freq_data['phase'],
            freq_data['labels'], k, frequency, segment_name, k_dir, head_name, cluster_colors
        )

    def _log_frequency_processing_summary(self, individual_frequencies_cluster_assignment_plots,
                                        successful_freq_count, failed_freq_count, total_frequencies):
        """Log summary of frequency processing"""
        if individual_frequencies_cluster_assignment_plots:
            self.logger.info(f"      Generated 2D cluster plot and fan segment visualization plot per frequency")
        else:
            self.logger.info(f"      Skipped individual frequency plots")
        self.logger.info(f"      ACI calculations: Successful: {successful_freq_count}")
        self.logger.info(f"      ACI calculations: Failed: {failed_freq_count}")
        self.logger.info(f"      ACI calculations: Total Frequencies: {total_frequencies}")

    def _calculate_segment_average_scores(self, successful_freq_count, frequency_metric_records,
                                        metrics_to_use, segment_name, k):
        """Calculate segment-level average ACI scores"""
        if successful_freq_count == 0:
            self.logger.warning(f"      Cannot calculate ACI scores for segment {segment_name} with k={k}")
            self.logger.warning(f"      Convex Hull could not be created for any frequency")
            return {}

        avg_scores = {}

        if 'ACI1' in metrics_to_use:
            aci1_scores = [r['aci1_score'] for r in frequency_metric_records if r.get('aci1_score') is not None]
            if aci1_scores:
                avg_scores['avg_aci1'] = np.mean(aci1_scores)

        if 'ACI2' in metrics_to_use:
            aci2_scores = [r['aci2_score'] for r in frequency_metric_records if r.get('aci2_score') is not None]
            if aci2_scores:
                avg_scores['avg_aci2'] = np.mean(aci2_scores)

        if 'ACI3' in metrics_to_use:
            aci3_scores = [r['aci3_score'] for r in frequency_metric_records if r.get('aci3_score') is not None]
            if aci3_scores:
                avg_scores['avg_aci3'] = np.mean(aci3_scores)

        if 'ACI4' in metrics_to_use:
            aci4_scores = [r['aci4_score'] for r in frequency_metric_records if r.get('aci4_score') is not None]
            if aci4_scores:
                avg_scores['avg_aci4'] = np.mean(aci4_scores)

        return avg_scores

    def _log_segment_scores(self, k, avg_scores, metrics_to_use):
        """Log segment-level average scores"""
        metrics_log = []
        if 'ACI1' in metrics_to_use and 'avg_aci1' in avg_scores:
            metrics_log.append(f"ACI1={avg_scores['avg_aci1']:.4f}")
        if 'ACI2' in metrics_to_use and 'avg_aci2' in avg_scores:
            metrics_log.append(f"ACI2={avg_scores['avg_aci2']:.4f}")
        if 'ACI3' in metrics_to_use and 'avg_aci3' in avg_scores:
            metrics_log.append(f"ACI3={avg_scores['avg_aci3']:.4f}")
        if 'ACI4' in metrics_to_use and 'avg_aci4' in avg_scores:
            metrics_log.append(f"ACI4={avg_scores['avg_aci4']:.4f}")
        metrics_text = ", ".join(metrics_log)

        self.logger.info(f"      k={k}: {metrics_text}")

    def _plot_aci_scores(self, segment_aci_scores, segment_name, dataset_dir, k1_baseline,
                        opt_dict, metrics_to_use, head_name):
        """Plot ACI scores vs k"""
        try:
            self.execute_plot.execute_plot_in_process(
                self.plot_metrics.plot_aci_scores_vs_k,
                segment_aci_scores, f"{segment_name}_{os.path.basename(dataset_dir)}",
                dataset_dir, k1_baseline,
                opt_dict.get('aci1'), opt_dict.get('aci2'),
                opt_dict.get('aci3'), opt_dict.get('aci4'),
                metrics_to_use, head_name
            )
            self.logger.info(f"  Generated ACI scores vs k plot")
        except Exception:
            self.logger.error(f"  Error creating ACI scores vs k plot")

    def _compare_with_baseline(self, segment_aci_scores, k1_baseline, segment_name,
                            dataset_dir, metrics_to_use, head_name):
        """Compare with k=1 baseline"""
        if segment_aci_scores:
            comparison_results = self.compare_k1_baseline.compare_with_k1_baseline(
                segment_aci_scores, k1_baseline, f"{segment_name}_{os.path.basename(dataset_dir)}", metrics_to_use
            )
            if comparison_results:
                comparison_df = pd.DataFrame.from_dict(comparison_results, orient='index')
                csv_path = os.path.join(dataset_dir, f'{head_name}_k1_comparison.csv')
                os.makedirs(os.path.dirname(csv_path), exist_ok=True)
                comparison_df.to_csv(csv_path, index_label='k', encoding='utf-8-sig')
                self.logger.info(f"  Saved k=1 comparison results")

    def _collect_model_registry_info(self, dataset_type, trained_models, models_base_dir,
                                    head_name, segment_name, freq_min, freq_max, opt_dict,
                                    group_label=None, merge_outcomes=None):
        """Collect model paths for registry.

        When group_label is set (baseline separation active), all model and normalization stat
        paths are rooted under <models_base_dir>/<head_name>/<segment_name>/<group_label>/.
        merge_outcomes, when provided, is {k: outcome_dict} from _run_merge_on_result, used to
        build the merged model registry and to gate model-path substitution in optimal_k_info.
        """
        model_registry_info = []
        merged_model_registry_info = []
        optimal_k_info = None

        if dataset_type == 'train' and trained_models:
            segment_models_base = self._build_segment_models_base(
                models_base_dir, head_name, segment_name, group_label
            )

            for k, model in trained_models.items():
                model_path = os.path.join(segment_models_base, f'k_{k}', MODEL_NAME)
                merge_outcome = (merge_outcomes or {}).get(k)
                model_registry_info.append({
                    'head_name': head_name,
                    'segment': segment_name,
                    'cluster_count': k,
                    'trained_model_path': os.path.abspath(model_path),
                    'merged_cluster_count': merge_outcome['k_merged'] if merge_outcome else None,
                    'merged_model_path': os.path.abspath(merge_outcome['model_path'])
                                         if merge_outcome else None,
                })

            merged_model_registry_info = self._build_merged_model_registry_info(
                head_name, segment_name, merge_outcomes, group_label=group_label
            )

            # Collect optimal k info
            optimal_k_info = self._build_optimal_k_info(
                head_name, segment_name, freq_min, freq_max, opt_dict,
                segment_models_base, group_label=group_label, merge_outcomes=merge_outcomes
            )

        return model_registry_info, optimal_k_info, merged_model_registry_info

    @staticmethod
    def _build_merged_model_registry_info(head_name, segment_name, merge_outcomes, group_label=None):
        """Build registry entries for every post-merge model.json produced for this segment."""
        if not merge_outcomes:
            return []
        entries = []
        for outcome in merge_outcomes.values():
            entry = {
                'head_name': head_name,
                'segment': segment_name,
                'cluster_count': outcome['k_merged'],
                'trained_model_path': os.path.abspath(outcome['model_path']),
            }
            if group_label is not None:
                entry['group'] = group_label
            entries.append(entry)
        return entries

    @staticmethod
    def _build_optimal_k_info(head_name, segment_name, freq_min, freq_max, opt_dict,
                            segment_models_base, group_label=None, merge_outcomes=None):
        """Build optimal k information dictionary.

        segment_models_base is the pre-computed base directory (already group-aware when set).
        group_label, if provided, is stored in the returned dict for use by the output config
        generator when building group-separated inference config structures.
        opt_dict may contain both ACI keys (aci1-4) and centroid keys (correlation/rmse/dtw).
        """
        info = {
            'head_name': head_name,
            'segment': segment_name,
            'segment_tuple': (freq_min, freq_max),
            'optimal_k_aci1': opt_dict.get('aci1', 1),
            'optimal_k_aci2': opt_dict.get('aci2', 1),
            'optimal_k_aci3': opt_dict.get('aci3', 1),
            'optimal_k_aci4': opt_dict.get('aci4', 1),
            'model_path_aci1': os.path.abspath(
                os.path.join(segment_models_base, f'k_{opt_dict.get("aci1", 1)}', MODEL_NAME)
            ) if opt_dict.get('aci1', 1) > 1 else None,
            'model_path_aci2': os.path.abspath(
                os.path.join(segment_models_base, f'k_{opt_dict.get("aci2", 1)}', MODEL_NAME)
            ) if opt_dict.get('aci2', 1) > 1 else None,
            'model_path_aci3': os.path.abspath(
                os.path.join(segment_models_base, f'k_{opt_dict.get("aci3", 1)}', MODEL_NAME)
            ) if opt_dict.get('aci3', 1) > 1 else None,
            'model_path_aci4': os.path.abspath(
                os.path.join(segment_models_base, f'k_{opt_dict.get("aci4", 1)}', MODEL_NAME)
            ) if opt_dict.get('aci4', 1) > 1 else None,
        }
        FRFClusteringBaseMetrics._add_centroid_paths_to_info(
            info, opt_dict, segment_models_base, merge_outcomes=merge_outcomes
        )
        if group_label is not None:
            info['group'] = group_label
        return info

    @staticmethod
    def _add_centroid_paths_to_info(info, opt_dict, segment_models_base, merge_outcomes=None):
        """Extend info dict with centroid metric optimal k, model paths, and is_merged."""
        merge_outcomes = merge_outcomes or {}
        for metric_lower, metric_name in (('correlation', 'Correlation'),
                                           ('rmse', 'RMSE'), ('wasserstein', 'Wasserstein')):
            opt_k = opt_dict.get(metric_lower)
            if opt_k is None:
                continue
            FRFClusteringBaseMetrics._set_centroid_metric_paths(
                info, metric_lower, metric_name, opt_k, segment_models_base, merge_outcomes
            )

    @staticmethod
    def _set_centroid_metric_paths(info, metric_lower, metric_name, opt_k, segment_models_base,
                                    merge_outcomes):
        """Populate one centroid metric's optimal_k/model_path/is_merged.

        Substitutes the merged model path only when a merge exists for opt_k and its
        post-merge score beat the pre-merge score for this specific metric.
        """
        info[f'optimal_k_{metric_lower}'] = opt_k
        has_model = opt_k > 1
        model_path = os.path.abspath(
            os.path.join(segment_models_base, f'k_{opt_k}', MODEL_NAME)
        ) if has_model else None
        is_merged = False
        outcome = merge_outcomes.get(opt_k)
        if has_model and outcome and outcome['is_better'].get(metric_name):
            model_path = outcome['model_path']
            is_merged = True
        info[f'model_path_{metric_lower}'] = model_path
        info[f'is_merged_{metric_lower}'] = is_merged
