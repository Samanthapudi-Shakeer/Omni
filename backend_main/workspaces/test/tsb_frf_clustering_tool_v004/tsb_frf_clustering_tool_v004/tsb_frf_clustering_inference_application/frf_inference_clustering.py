# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_clustering.py
*  File Description: File for inference using pre-trained clustering models
*  All rights reserved.
*
*********************************************************************/
"""

import os
import pandas as pd
import numpy as np
import logging
from frf_inference_metric_components import ConvexHullCalculator
from frf_inference_metrics import BaselineMetricsCalculator, ACIMetricsCalculator
from frf_inference_centroid_metrics import CentroidMetricsCalculator
from frf_inference_plots import Plot3DVisualizer, PlotSegmentOverviewVisualizer, Plot2DVisualizer
from frf_inference_plots import PlotFanSegmentVisualizer
from frf_inference_bode_plots import PlotFrequencyGridVisualizer, PlotInteractiveBodeVisualizer
from frf_inference_utils import FeatureNormalizer, ModelManager, ColorGenerator
from frf_inference_data_utils import PlotExecution
import time


class InferenceResult(object):
    """Container for inference results"""

    def __init__(self, inference_results, segment_aci_scores):
        self.inference_results = inference_results
        self.segment_aci_scores = segment_aci_scores

    def __iter__(self):
        """Allow tuple unpacking for backward compatibility"""
        return iter([self.inference_results, self.segment_aci_scores])


class FRFInferenceEngine(object):
    """Handles inference execution, model loading, and plot generation"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.model_load = ModelManager()
        self.feature_normalizer = FeatureNormalizer()
        self.calculate_k1_baseline = BaselineMetricsCalculator()
        self.calculate_acis = ACIMetricsCalculator()
        self.centroid_metrics_calculator = CentroidMetricsCalculator()
        self.generate_colour = ColorGenerator()
        self.convex_hull_calculater = ConvexHullCalculator()
        self.plot_execute = PlotExecution()

        self.plot_3d = Plot3DVisualizer()
        self.plot_overview = PlotSegmentOverviewVisualizer()
        self.plot_2d = Plot2DVisualizer()
        self.plot_fan = PlotFanSegmentVisualizer()
        self.plot_grid = PlotFrequencyGridVisualizer()
        self.plot_interactive_bode = PlotInteractiveBodeVisualizer()

        self.epsilon = 1e-12

    def perform_inference_clustering(self, inference_params):
        """Perform inference using pre-trained model

        Args:
            inference_params: Dictionary containing all inference parameters

        Returns:
            InferenceResult: Object containing inference_results and segment_aci_scores
        """
        # Extract and setup
        setup_result = self._setup_inference_environment(inference_params)
        if setup_result is None:
            return InferenceResult({}, {})

        k_dir, inference_results, segment_aci_scores = setup_result

        # Handle k=1 case
        if inference_params['optimal_k'] == 1:
            return self._handle_k1_case(inference_params, inference_results, segment_aci_scores)

        # Perform full clustering inference
        return self._perform_full_clustering_inference(
            inference_params, k_dir, inference_results, segment_aci_scores
        )

    def _setup_inference_environment(self, inference_params):
        """Setup inference environment and validate prerequisites

        Returns:
            tuple: (k_dir, inference_results, segment_aci_scores) or None if setup fails
        """
        optimal_k = inference_params['optimal_k']
        current_metric = inference_params['current_metric']
        inference_dir = inference_params['inference_dir']
        unique_frequencies = inference_params['unique_frequencies']
        segment_name = inference_params['segment_name']
        head_name = inference_params['head_name']
        metrics_to_use = inference_params.get('metrics_to_use', ['ACI1', 'ACI2', 'ACI3', 'ACI4'])

        if current_metric is None:
            self.logger.info(f"  [INFERENCE-k{optimal_k}] Processing with metrics: {metrics_to_use}")
        else:
            self.logger.info(f"  [INFERENCE-{current_metric}] Processing with optimal k={optimal_k}")

        # Check for k=1 early and skip normalization
        if optimal_k == 1:
            self.logger.warning(f"  [INFERENCE-{current_metric}] No optimal model found \
for metric {current_metric} in segment {segment_name}")
            self.logger.warning(f"  [INFERENCE-{current_metric}] Optimal k=1 indicates \
clustering was not beneficial for this metric")
            return None

        # Create k-specific directory
        k_label = inference_params.get('k_label') or f'k_{optimal_k}'
        inference_params['k_label'] = k_label
        k_dir = os.path.join(inference_dir, k_label)
        os.makedirs(k_dir, exist_ok=True)

        # Compute the compact label used in every LEAF FILENAME
        inference_params['file_label'] = self._build_file_label(
            k_label, inference_params.get('is_merged', False),
            inference_params.get('orig_k_value'), optimal_k
        )

        # Create segment overview and validate
        if not self._create_segment_overview_if_needed(inference_dir, head_name):
            return None

        # Normalize inference data (per-file normalize-to-[-1,1] + detrend + weight
        frequencywise_scaled = self._normalize_inference_data(
            inference_params['frequencywise_data'],
            inference_params['feature_weights'],
            unique_frequencies,
            optimal_k
        )
        # Store normalized data back in params for later use
        inference_params['frequencywise_scaled'] = frequencywise_scaled

        # Use k=1 baseline calculated once for the whole segment (or baseline group)
        k1_baseline, segment_aci_scores = self._calculate_baseline_metrics(
            inference_params.get('k1_baseline'),
            metrics_to_use,
            current_metric,
            optimal_k
        )

        inference_results = {'k1_baseline': k1_baseline}

        return k_dir, inference_results, segment_aci_scores

    def _handle_k1_case(self, inference_params, inference_results, segment_aci_scores):
        """Handle the special case when k=1

        Returns:
            InferenceResult: Object containing inference_results and segment_aci_scores
        """
        current_metric = inference_params['current_metric']
        self.logger.info(f"  [INFERENCE-{current_metric}] Optimal k=1, no clustering needed")
        self.logger.info(f"  [INFERENCE-{current_metric}] Using baseline metrics as final result")
        return InferenceResult(inference_results, segment_aci_scores)

    def _perform_full_clustering_inference(self, inference_params, k_dir,
                                        inference_results, segment_aci_scores):
        """Perform full clustering inference for k > 1

        Returns:
            InferenceResult: Object containing inference_results and segment_aci_scores
        """
        optimal_k = inference_params['optimal_k']
        frequencywise_scaled = inference_params['frequencywise_scaled']
        model_path = inference_params['model_path']

        # Load model and perform inference
        model, file_labels = self._perform_model_inference(
            frequencywise_scaled, optimal_k, model_path
        )

        if model is None or file_labels is None:
            return InferenceResult({}, {})

        # Store clustering results
        inference_results[optimal_k] = {
            'file_labels': file_labels,
            'cluster_centers': model.cluster_centers_,
            'model': model
        }

        # Process visualizations and metrics
        self._process_clustering_outputs(
            inference_params, k_dir, model, file_labels, segment_aci_scores
        )

        return InferenceResult(inference_results, segment_aci_scores)

    def _process_clustering_outputs(self, inference_params, k_dir, model,
                                    file_labels, segment_aci_scores):
        """Process all clustering outputs: visualizations, mappings, and metrics"""
        optimal_k = inference_params['optimal_k']
        segment_file_dict = inference_params['segment_file_dict']
        unique_frequencies = inference_params['unique_frequencies']
        segment_name = inference_params['segment_name']
        head_name = inference_params['head_name']
        file_indices = inference_params['file_indices']
        current_metric = inference_params['current_metric']
        k_label = inference_params['k_label']
        file_label = inference_params['file_label']
        metrics_to_use = inference_params.get('metrics_to_use', ['ACI1', 'ACI2', 'ACI3', 'ACI4'])
        individual_frequencies_cluster_assignment_plots = inference_params.get(
            'individual_frequencies_cluster_assignment_plots', False
        )
        generate_interactive_html_plots = inference_params.get(
            'generate_interactive_html_plots', True
        )

        # Generate visualizations
        cluster_colors = self.generate_colour.get_cluster_colors(optimal_k)
        cluster_centers_denormalized = self._calculate_cluster_means(
            segment_file_dict, file_labels, optimal_k, unique_frequencies
        )

        self._generate_cluster_visualizations(
            segment_file_dict, unique_frequencies, segment_name, k_dir, head_name,
            file_labels, optimal_k, cluster_colors, cluster_centers_denormalized,
            generate_interactive_html_plots, file_label
        )

        # Save drive cluster mapping
        self._save_drive_cluster_mapping(
            segment_file_dict, file_indices, file_labels, k_dir, head_name, file_label
        )

        # Process frequency ACI calculations
        aci_calc_params = {
            'frequencywise_data': inference_params['frequencywise_data'],
            'file_indices': file_indices,
            'unique_frequencies': unique_frequencies,
            'segment_file_dict': segment_file_dict,
            'file_labels': file_labels,
            'model': model,
            'optimal_k': optimal_k,
            'file_label': file_label,
            'segment_name': segment_name,
            'k_dir': k_dir,
            'head_name': head_name,
            'metrics_to_use': metrics_to_use,
            'current_metric': current_metric,
            'individual_frequencies_cluster_assignment_plots': individual_frequencies_cluster_assignment_plots
        }

        frequency_aci_scores, successful_freq_count = \
            self._process_frequency_aci_calculations(aci_calc_params)

        # Check cluster composition
        self._check_cluster_composition(file_labels, optimal_k)

        # Calculate segment-level scores
        avg_scores = self._calculate_segment_aci_scores(
            frequency_aci_scores, successful_freq_count, metrics_to_use, optimal_k, segment_name
        )

        # Centroid-based metrics (Correlation, RMSE, Wasserstein) are computed once per k
        # from the cluster centroids themselves, independent of the per-frequency ACI loop
        centroid_avg_scores, _ = self.centroid_metrics_calculator.compute_centroid_metrics(
            cluster_centers_denormalized, unique_frequencies, metrics_to_use
        )
        if centroid_avg_scores:
            avg_scores.update(centroid_avg_scores)
            self._log_segment_centroid_scores(centroid_avg_scores, optimal_k)

        if avg_scores:
            segment_aci_scores[k_label] = avg_scores

    def _create_segment_overview_if_needed(self, inference_dir, head_name):
        """Validate segment overview plot exists. Only the 'all' mode layout remains
        (inference_dir IS the segment directory), since optimal mode has been removed."""
        overview_plot_path = os.path.join(inference_dir, f'{head_name}_segment_overview.jpg')

        if not os.path.exists(overview_plot_path):
            self.logger.warning(f"  Segment overview not found at: {overview_plot_path}")
            # Don't fail - it should have been created already
            return False

        return True

    @staticmethod
    def _build_file_label(k_label, is_merged, orig_k_value, k_value):
        """Compute the compact label embedded in every leaf filename.

        - Not merged: abbreviate stage1/stage2 -> s1/s2 and tighten 'k_N' -> 'kN'
          (e.g. 'k_4' -> 'k4'; 'stage1_k_2_stage2_k_3' -> 's1_k2_s2_k3').
        - Merged: always 'origk<orig_k>_k<k_value>', replacing any stage1/stage2
          labeling entirely, matching the training application's merged-file
          naming convention exactly.
        """
        if is_merged and orig_k_value is not None:
            return f'origk{orig_k_value}_k{k_value}'
        return k_label.replace('stage1_k_', 's1_k').replace('stage2_k_', 's2_k').replace('k_', 'k')

    def _normalize_inference_data(self, frequencywise_data, feature_weights,
                                unique_frequencies, optimal_k):
        """Normalize inference data using the training application's per-file
        normalize-to-[-1,1] + detrend + feature-weight pipeline. No statistics are
        loaded from disk — normalization is computed fresh from each file's own curve."""
        self.logger.info(f"  [INFERENCE-k{optimal_k}] Normalizing inference data (per-file, detrend + weight)")

        try:
            frequencywise_scaled = self.feature_normalizer.normalize_detrend_and_weight(
                frequencywise_data, feature_weights, unique_frequencies
            )
            self.logger.info(f"      Applied feature weights: {feature_weights}")
            return frequencywise_scaled

        except Exception as e:
            error_msg = f"Error during inference data normalization: {e}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    def calculate_segment_k1_baseline(self, frequencywise_data, file_indices, unique_frequencies,
                                      segment_file_dict, metrics_to_use):
        """Calculate k=1 baseline metrics once for a segment (or baseline group), so the
        result can be reused across every trained model processed for that segment"""
        self.logger.info("  [INFERENCE] Calculating k=1 baseline metrics for segment...")
        return self.calculate_k1_baseline.calculate_k1_baseline_metrics(
            frequencywise_data, file_indices, unique_frequencies,
            segment_file_dict, metrics_to_use=metrics_to_use
        )

    def _calculate_baseline_metrics(self, k1_baseline, metrics_to_use, current_metric, optimal_k):
        """Build segment ACI scores from the segment's precomputed k=1 baseline metrics"""
        if current_metric is None:
            self.logger.info(f"  [INFERENCE-k{optimal_k}] Using precomputed k=1 baseline metrics...")
        else:
            self.logger.info(f"  [INFERENCE-{current_metric}] Using precomputed k=1 baseline metrics...")

        segment_aci_scores = {}
        if k1_baseline:
            baseline_scores = self._extract_baseline_scores(k1_baseline, metrics_to_use)
            if baseline_scores:
                segment_aci_scores[1] = baseline_scores

        return k1_baseline, segment_aci_scores

    @staticmethod
    def _extract_baseline_scores(k1_baseline, metrics_to_use):
        """Extract baseline scores from k1_baseline based on metrics_to_use"""
        baseline_scores = {}

        if 'ACI1' in metrics_to_use and 'aci1_score' in k1_baseline:
            baseline_scores['avg_aci1'] = k1_baseline['aci1_score']

        if 'ACI2' in metrics_to_use and 'aci2_score' in k1_baseline:
            baseline_scores['avg_aci2'] = k1_baseline['aci2_score']

        if 'ACI3' in metrics_to_use and 'aci3_score' in k1_baseline:
            baseline_scores['avg_aci3'] = k1_baseline['aci3_score']

        if 'ACI4' in metrics_to_use and 'aci4_score' in k1_baseline:
            baseline_scores['avg_aci4'] = k1_baseline['aci4_score']

        return baseline_scores

    def _perform_model_inference(self, frequencywise_scaled, optimal_k, model_path):
        """Load model and perform inference prediction"""
        self.logger.info(f"  [INFERENCE-k{optimal_k}] Loading pre-trained model: k={optimal_k}")

        try:
            model = self.model_load.load_model(model_path, format='json')
            self.logger.info(f"      Successfully loaded model from: {model_path}")
        except Exception as e:
            self.logger.error(f"      Failed to load model: {e}")
            raise RuntimeError(f"Cannot load model from {model_path}")

        try:
            if np.any(np.isnan(frequencywise_scaled)) or np.any(np.isinf(frequencywise_scaled)):
                self.logger.warning(f"    Scaled data contains NaN or Inf values")
                return None, None

            start_time = time.time()
            file_labels = model.predict(frequencywise_scaled)
            elapsed_time = time.time() - start_time

            self.logger.info(f"      Inference completed in {elapsed_time:.2f} seconds")

            # Validate cluster assignments
            unique_labels = np.unique(file_labels)
            if len(unique_labels) != optimal_k:
                self.logger.warning(f"      Expected {optimal_k} clusters, but got {len(unique_labels)} clusters")

            # Check cluster sizes
            for label in unique_labels:
                cluster_size = np.sum(file_labels == label)
                if cluster_size == 1:
                    self.logger.warning(f"      Cluster {label} has only 1 member")
                elif cluster_size < 3:
                    self.logger.warning(f"      Cluster {label} has only {cluster_size} members")

            return model, file_labels

        except Exception as e:
            self.logger.error(f"    Error during inference prediction: {e}")
            return None, None

    def _generate_cluster_visualizations(self, segment_file_dict, unique_frequencies, segment_name,
                                        k_dir, head_name, file_labels, optimal_k, cluster_colors,
                                        cluster_centers_denormalized,
                                        generate_interactive_html_plots=True, k_label=None):
        """Generate all cluster visualization plots"""
        # Create 3D visualization with clusters (static only)
        self.plot_execute.execute_plot_in_process(
            self.plot_3d.create_3d_visualization,
            segment_file_dict, segment_name, k_dir, head_name,
            file_labels, optimal_k, cluster_colors, cluster_centers_denormalized, k_label
        )
        self.logger.info(f"      Generated 3D visualization")

        # Create interactive 3D visualization
        if generate_interactive_html_plots:
            self.plot_execute.execute_plot_in_process(
                self.plot_3d.create_interactive_3d_visualization,
                segment_file_dict, segment_name, k_dir, head_name,
                file_labels, optimal_k, cluster_colors, cluster_centers_denormalized, k_label
            )
            self.logger.info(f"      Generated interactive 3D visualization")

        # Create 3D centroids-only visualization
        self.plot_execute.execute_plot_in_process(
            self.plot_3d.create_3d_centroids_only,
            cluster_centers_denormalized, unique_frequencies, optimal_k, cluster_colors, segment_name, k_dir, head_name,
            k_label, file_labels=file_labels
        )
        self.logger.info(f"      Generated 3D centroids-only plot")

        # Create frequency vs gain and phase grid plot
        self.plot_execute.execute_plot_in_process(
            self.plot_grid.create_frequency_gain_phase_grid,
            segment_file_dict, file_labels, segment_name, k_dir, optimal_k, head_name, cluster_colors, k_label
        )
        self.logger.info(f"      Generated frequency-gain-phase plots")

        # Create interactive Bode plots
        if generate_interactive_html_plots:
            self.plot_execute.execute_plot_in_process(
                self.plot_interactive_bode.create_interactive_bode_plots,
                segment_file_dict, file_labels, segment_name, k_dir, optimal_k, head_name,
                cluster_colors, cluster_centers_denormalized, k_label
            )
            self.logger.info(f"      Generated interactive Bode plots")

        # Create static Bode centroids grid
        self.plot_execute.execute_plot_in_process(
            self.plot_interactive_bode.create_static_bode_centroids_grid,
            cluster_centers_denormalized, unique_frequencies, optimal_k, cluster_colors, segment_name, k_dir, head_name,
            file_labels, k_label
        )
        self.logger.info(f"      Generated static centroid Bode plots")

        # Create bode centroid metrics plot (raw/normalized/detrended phase panels)
        self.plot_execute.execute_plot_in_process(
            self.plot_interactive_bode.create_bode_centroid_metrics,
            cluster_centers_denormalized, unique_frequencies, optimal_k, cluster_colors,
            segment_name, k_dir, head_name, file_labels, k_label
        )
        self.logger.info(f"      Generated bode centroid metrics plot")

    def _save_drive_cluster_mapping(self, segment_file_dict, file_indices, file_labels,
                                    k_dir, head_name, k_label):
        """Save drive cluster mapping CSV, matching the training application's 'dc' naming"""
        drive_cluster_mapping = []
        for file_idx, original_file_idx in enumerate(file_indices):
            file_data_entry = segment_file_dict['files'][original_file_idx]
            drive_cluster_mapping.append({
                'Drive_name': file_data_entry['filename'],
                'cluster_id': int(file_labels[file_idx])
            })

        if drive_cluster_mapping:
            drive_df = pd.DataFrame(drive_cluster_mapping)
            drive_csv = os.path.join(k_dir, f'{head_name}_dc_{k_label}.csv')

            os.makedirs(os.path.dirname(drive_csv), exist_ok=True)
            drive_df.to_csv(drive_csv, index=False, encoding='utf-8-sig')
            self.logger.info(f"      Saved drive cluster mapping: {len(drive_df)} drives")

    def _process_frequency_aci_calculations(self, aci_calc_params):
        """Process ACI calculations for all frequencies

        Args:
            aci_calc_params: Dictionary containing all calculation parameters

        Returns:
            tuple: (frequency_aci_scores, successful_freq_count)
        """
        # Extract parameters
        file_indices = aci_calc_params['file_indices']
        unique_frequencies = aci_calc_params['unique_frequencies']
        segment_file_dict = aci_calc_params['segment_file_dict']
        file_labels = aci_calc_params['file_labels']
        optimal_k = aci_calc_params['optimal_k']
        k_label = aci_calc_params['file_label']
        segment_name = aci_calc_params['segment_name']
        k_dir = aci_calc_params['k_dir']
        head_name = aci_calc_params['head_name']
        metrics_to_use = aci_calc_params['metrics_to_use']
        current_metric = aci_calc_params['current_metric']
        individual_frequencies_cluster_assignment_plots = aci_calc_params.get(
            'individual_frequencies_cluster_assignment_plots', False
        )

        frequency_aci_scores = {'aci1': [], 'aci2': [], 'aci3': [], 'aci4': []}
        successful_freq_count = 0
        failed_freq_count = 0

        for freq_idx, frequency in enumerate(unique_frequencies):
            freq_data = self._extract_frequency_data(
                file_indices, segment_file_dict, freq_idx, file_labels
            )

            # Check convex hull validity
            hull_x, hull_y, hull_area, hull_stats = self.convex_hull_calculater.calculate_convex_hull(
                freq_data['real'], freq_data['imag']
            )

            if hull_area is None:
                failed_freq_count += 1
                if individual_frequencies_cluster_assignment_plots:
                    self._create_frequency_plots(
                        freq_data, optimal_k, frequency,
                        segment_name, k_dir, head_name, k_label
                    )
                continue

            successful_freq_count += 1

            # Calculate ACI metrics
            aci_results = self._calculate_frequency_aci_metrics(
                freq_data, optimal_k, metrics_to_use, current_metric
            )

            # Append scores
            self._append_frequency_aci_scores(aci_results, frequency_aci_scores, metrics_to_use)

            # Create plots if enabled
            if individual_frequencies_cluster_assignment_plots:
                self._create_frequency_plots(
                        freq_data, optimal_k, frequency,
                        segment_name, k_dir, head_name, k_label
                    )

        self._log_aci_processing_summary(
            successful_freq_count, failed_freq_count, len(unique_frequencies),
            individual_frequencies_cluster_assignment_plots
        )

        return frequency_aci_scores, successful_freq_count

    @staticmethod
    def _extract_frequency_data(file_indices, segment_file_dict,
                                freq_idx, file_labels):
        """Extract data for a specific frequency"""
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

    def _calculate_frequency_aci_metrics(self, freq_data, optimal_k, metrics_to_use, current_metric):
        """Calculate ACI metrics for a single frequency"""
        aci_results = {}

        if current_metric is None:
            # 'all' mode - calculate metrics specified in config
            if 'ACI1' in metrics_to_use:
                aci_results['aci1'] = self.calculate_acis.calculate_evaluation_metric_aci1(
                    freq_data['real'], freq_data['imag'], freq_data['gain'],
                    freq_data['phase'], freq_data['labels'], optimal_k
                )

            if 'ACI2' in metrics_to_use:
                aci_results['aci2'] = self.calculate_acis.calculate_evaluation_metric_aci2(
                    freq_data['real'], freq_data['imag'], freq_data['gain'],
                    freq_data['phase'], freq_data['labels'], optimal_k
                )

            if 'ACI3' in metrics_to_use:
                aci_results['aci3'] = self.calculate_acis.calculate_evaluation_metric_aci3(
                    freq_data['real'], freq_data['imag'], freq_data['gain'],
                    freq_data['phase'], freq_data['labels'], optimal_k
                )

            if 'ACI4' in metrics_to_use:
                aci_results['aci4'] = self.calculate_acis.calculate_evaluation_metric_aci4(
                    freq_data['real'], freq_data['imag'], freq_data['gain'],
                    freq_data['phase'], freq_data['labels'], optimal_k
                )
        else:
            # 'optimal' mode - calculate only the current metric
            if current_metric == 'ACI1':
                aci_results['aci1'] = self.calculate_acis.calculate_evaluation_metric_aci1(
                    freq_data['real'], freq_data['imag'], freq_data['gain'],
                    freq_data['phase'], freq_data['labels'], optimal_k
                )
            elif current_metric == 'ACI2':
                aci_results['aci2'] = self.calculate_acis.calculate_evaluation_metric_aci2(
                    freq_data['real'], freq_data['imag'], freq_data['gain'],
                    freq_data['phase'], freq_data['labels'], optimal_k
                )
            elif current_metric == 'ACI3':
                aci_results['aci3'] = self.calculate_acis.calculate_evaluation_metric_aci3(
                    freq_data['real'], freq_data['imag'], freq_data['gain'],
                    freq_data['phase'], freq_data['labels'], optimal_k
                )
            elif current_metric == 'ACI4':
                aci_results['aci4'] = self.calculate_acis.calculate_evaluation_metric_aci4(
                    freq_data['real'], freq_data['imag'], freq_data['gain'],
                    freq_data['phase'], freq_data['labels'], optimal_k
                )

        return aci_results

    @staticmethod
    def _append_frequency_aci_scores(aci_results, frequency_aci_scores, metrics_to_use):
        """Append ACI scores to frequency collections"""
        if aci_results.get('aci1'):
            frequency_aci_scores['aci1'].append(aci_results['aci1']['aci1_score'])
        if aci_results.get('aci2'):
            frequency_aci_scores['aci2'].append(aci_results['aci2']['aci2_score'])
        if aci_results.get('aci3'):
            frequency_aci_scores['aci3'].append(aci_results['aci3']['aci3_score'])
        if aci_results.get('aci4'):
            frequency_aci_scores['aci4'].append(aci_results['aci4']['aci4_score'])

    def _create_frequency_plots(self, freq_data, optimal_k, frequency,
                                segment_name, k_dir, head_name, k_label=None):
        """Create 2D and fan segment plots for a frequency"""
        cluster_colors = self.generate_colour.get_cluster_colors(optimal_k)

        # Compute per-cluster mean real/imag centroids from freq_data (always shape (k, 2))
        freq_centroids_denormalized = self._compute_freq_centroids(freq_data, optimal_k)

        # Create 2D plot
        self.plot_execute.execute_plot_in_process(
            self.plot_2d.create_2d_frequency_plot,
            freq_data['real'], freq_data['imag'], freq_data['labels'], optimal_k,
            frequency, segment_name, k_dir, head_name, cluster_colors, freq_centroids_denormalized,
            k_label
        )

        # Create fan segment visualization
        self.plot_execute.execute_plot_in_process(
            self.plot_fan.create_fan_segment_visualization,
            freq_data['real'], freq_data['imag'], freq_data['gain'], freq_data['phase'],
            freq_data['labels'], optimal_k, frequency, segment_name, k_dir, head_name, cluster_colors,
            k_label
        )

    @staticmethod
    def _compute_freq_centroids(freq_data, k):
        """Compute per-cluster mean real/imag centroid for a single frequency slice.

        Returns:
            np.ndarray of shape (k, 2) where [:, 0] = mean real, [:, 1] = mean imag
        """
        centroids = np.zeros((k, 2))
        for cluster_id in range(k):
            mask = freq_data['labels'] == cluster_id
            if np.any(mask):
                centroids[cluster_id, 0] = np.mean(freq_data['real'][mask])
                centroids[cluster_id, 1] = np.mean(freq_data['imag'][mask])
        return centroids

    @staticmethod
    def _calculate_cluster_means(segment_file_dict, file_labels, k, unique_frequencies):
        """Calculate per-cluster mean of real and imaginary data from segment_file_dict.

        Returns:
            cluster_means: np.ndarray of shape (k, n_frequencies, 2)
                           where [..., 0] = mean real, [..., 1] = mean imag
        """
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

    def _log_aci_processing_summary(self, successful_freq_count, failed_freq_count,
                                    total_frequencies, individual_frequencies_cluster_assignment_plots):
        """Log summary of ACI processing"""
        if individual_frequencies_cluster_assignment_plots:
            self.logger.info(f"      Generated 2D cluster plot and fan segment visualization plot for each frequency")
        else:
            self.logger.info(f"      Skipped individual frequency plots")
        self.logger.info(f"      ACI calculations: Successful: {successful_freq_count}")
        self.logger.info(f"      ACI calculations: Failed: {failed_freq_count}")
        self.logger.info(f"      ACI calculations: Total Frequencies: {total_frequencies}")

    def _check_cluster_composition(self, file_labels, optimal_k):
        """Check for cluster composition issues"""
        if optimal_k <= 1:
            return

        unique_labels = np.unique(file_labels)
        empty_clusters = [i for i in range(optimal_k) if i not in unique_labels]
        small_clusters = []

        for cluster_id in range(optimal_k):
            cluster_size = np.sum(file_labels == cluster_id)
            if 0 < cluster_size < 3:
                small_clusters.append((cluster_id, cluster_size))

        if empty_clusters or small_clusters:
            self.logger.warning(f"      Cluster composition issues for k={optimal_k}:")
            if empty_clusters:
                self.logger.warning(f"        - Empty clusters: {empty_clusters}")
            if small_clusters:
                for cid, size in small_clusters:
                    self.logger.warning(f"        - Small cluster {cid}: {size} members")

    def _calculate_segment_aci_scores(self, frequency_aci_scores, successful_freq_count,
                                    metrics_to_use, optimal_k, segment_name):
        """Calculate segment-level ACI scores from frequency scores"""
        if successful_freq_count == 0:
            self.logger.warning(f"      Cannot calculate ACI scores for segment {segment_name} with k={optimal_k}")
            self.logger.warning(f"      Convex Hull could not be created for any frequency")
            return {}

        avg_scores = {}

        if 'ACI1' in metrics_to_use and frequency_aci_scores['aci1']:
            avg_scores['avg_aci1'] = np.mean(frequency_aci_scores['aci1'])

        if 'ACI2' in metrics_to_use and frequency_aci_scores['aci2']:
            avg_scores['avg_aci2'] = np.mean(frequency_aci_scores['aci2'])

        if 'ACI3' in metrics_to_use and frequency_aci_scores['aci3']:
            avg_scores['avg_aci3'] = np.mean(frequency_aci_scores['aci3'])

        if 'ACI4' in metrics_to_use and frequency_aci_scores['aci4']:
            avg_scores['avg_aci4'] = np.mean(frequency_aci_scores['aci4'])

        if avg_scores:
            self._log_segment_aci_scores(avg_scores, optimal_k)

        return avg_scores

    def _log_segment_aci_scores(self, avg_scores, optimal_k):
        """Log calculated segment ACI scores"""
        metrics_log = []
        if 'avg_aci1' in avg_scores:
            metrics_log.append(f"ACI1={avg_scores['avg_aci1']:.4f}")
        if 'avg_aci2' in avg_scores:
            metrics_log.append(f"ACI2={avg_scores['avg_aci2']:.4f}")
        if 'avg_aci3' in avg_scores:
            metrics_log.append(f"ACI3={avg_scores['avg_aci3']:.4f}")
        if 'avg_aci4' in avg_scores:
            metrics_log.append(f"ACI4={avg_scores['avg_aci4']:.4f}")
        metrics_text = ", ".join(metrics_log)

        self.logger.info(f"      k={optimal_k}: {metrics_text}")

    def _log_segment_centroid_scores(self, centroid_avg_scores, optimal_k):
        """Log calculated segment centroid-based scores (Correlation, RMSE, Wasserstein)"""
        metrics_log = []
        if 'avg_correlation' in centroid_avg_scores:
            metrics_log.append(f"Correlation={centroid_avg_scores['avg_correlation']:.4f}")
        if 'avg_rmse' in centroid_avg_scores:
            metrics_log.append(f"RMSE={centroid_avg_scores['avg_rmse']:.4f}")
        if 'avg_wasserstein' in centroid_avg_scores:
            metrics_log.append(f"Wasserstein={centroid_avg_scores['avg_wasserstein']:.4f}")
        metrics_text = ", ".join(metrics_log)

        self.logger.info(f"      k={optimal_k}: {metrics_text}")
