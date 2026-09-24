# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_segment_processor.py
*  File Description: Segment processor classes for optimal and all-mode inference
*  All rights reserved.
*
*********************************************************************/
"""

import os
import gc
from frf_inference_utils import resolve_path_with_root_dir
from frf_inference_segment_utility import SegmentProcessingContext, SegmentFeaturesConfig
from frf_inference_segment_utility import SegmentExtendedConfig, ProcessedSegmentData, SegmentProcessorBase


class InferenceOptions(object):
    """Groups optional inference configuration parameters to reduce method signatures"""

    def __init__(self, baseline_separation=False, baseline_data_filtering=None,
                 individual_frequencies_cluster_assignment_plots=False,
                 generate_interactive_html_plots=True):
        self.baseline_separation = baseline_separation
        self.baseline_data_filtering = baseline_data_filtering
        self.individual_frequencies_cluster_assignment_plots = individual_frequencies_cluster_assignment_plots
        self.generate_interactive_html_plots = generate_interactive_html_plots


class SegmentProcessor(SegmentProcessorBase):
    """Processes frequency segments for inference (single-stage clustering, 'all' mode only)"""

    def process_segment_inference_all_mode(self, data_list, filenames, valid_segments,
                                   head_output_dir, head_name, features_list, feature_weights,
                                   head_all_models_dict, metrics_to_use, root_dir,
                                   options=None):
        """Process segments in 'all' inference mode (all trained model combinations)"""
        if options is None:
            options = InferenceOptions()

        all_summaries = []

        for segment in valid_segments:
            freq_min, freq_max = segment
            segment_key = f"({freq_min}, {freq_max})"
            segment_name = f"{freq_min:.2f}_{freq_max:.2f}Hz"

            if not options.baseline_separation and segment_key not in head_all_models_dict:
                self.logger.warning(f"No models found for segment {segment_key}")
                continue

            self._log_segment_header(segment_name)
            features_config = SegmentFeaturesConfig(features_list, feature_weights)
            extended_config = SegmentExtendedConfig(
                baseline_separation=options.baseline_separation,
                baseline_data_filtering=options.baseline_data_filtering or []
            )
            context = SegmentProcessingContext(
                data_list, filenames, freq_min, freq_max, segment_name, segment_key,
                head_output_dir, head_name, features_config,
                metrics_to_use, root_dir,
                extended_config=extended_config
            )
            segment_summaries = self._process_single_segment_all_mode(
                context, head_all_models_dict,
                options.individual_frequencies_cluster_assignment_plots,
                options.generate_interactive_html_plots
            )

            all_summaries.extend(segment_summaries)

        return all_summaries

    def _process_single_segment_all_mode(self, context, head_all_models_dict,
                                         individual_frequencies_cluster_assignment_plots,
                                         generate_interactive_html_plots=True):
        """Process a single segment for all trained model combinations"""
        segment_dir = os.path.join(context.head_output_dir, f'segment_{context.segment_name}')
        os.makedirs(segment_dir, exist_ok=True)

        segment_file_dict = self.preprocessor.collect_segment_data_for_frequencywise_clustering(
            context.data_list, context.filenames, context.freq_min, context.freq_max
        )
        frequencywise_data, unique_frequencies, file_indices = self.preprocessor.create_frequencywise_array(
            segment_file_dict, context.features_list, segment_name=context.segment_name
        )
        # Full-segment overview and 3D plot
        success, overview_result = self.execute_plot.execute_plot_in_process(
            self.inference_engine.plot_overview.create_segment_overview_analysis,
            segment_file_dict, context.segment_name, segment_dir, context.head_name
        )
        if not success or overview_result is False:
            self.logger.error(
                f"  SEGMENT SKIPPED: Cannot create convex hull for segment overview "
                f"- {context.segment_name}"
            )
            del segment_file_dict, frequencywise_data
            gc.collect()
            return []

        self.logger.info(f"  Generated segment overview plot")
        if not context.baseline_separation:
            self.execute_plot.execute_plot_in_process(
                self.inference_engine.plot_overview.create_normalization_detrend_overview,
                segment_file_dict, context.segment_name, segment_dir, context.head_name
            )
            self.logger.info(f"  Generated normalization+detrend overview plot")
        self.execute_plot.execute_plot_in_process(
            self.inference_engine.plot_3d.create_3d_visualization,
            segment_file_dict, context.segment_name, segment_dir, context.head_name, None, None
        )
        if generate_interactive_html_plots:
            self.execute_plot.execute_plot_in_process(
                self.inference_engine.plot_3d.create_interactive_3d_visualization,
                segment_file_dict, context.segment_name, segment_dir, context.head_name
            )
        self.logger.info(f"  Generated 3D original data visualization")
        processed_data = ProcessedSegmentData(
            frequencywise_data, file_indices, unique_frequencies,
            segment_file_dict, segment_dir, context.filenames
        )
        segment_summaries = self._dispatch_all_mode_processing(
            context, processed_data, head_all_models_dict,
            individual_frequencies_cluster_assignment_plots,
            generate_interactive_html_plots
        )

        del segment_file_dict, frequencywise_data
        gc.collect()

        return segment_summaries

    def _dispatch_all_mode_processing(self, context, processed_data, head_all_models_dict,
                                       individual_frequencies_cluster_assignment_plots,
                                       generate_interactive_html_plots=True):
        """Dispatch all-mode processing to the appropriate handler based on context flags"""
        if context.baseline_separation:
            return self._process_all_mode_baseline(
                context, processed_data, head_all_models_dict,
                individual_frequencies_cluster_assignment_plots,
                generate_interactive_html_plots
            )

        if context.segment_key not in head_all_models_dict:
            self.logger.warning(f"No models for segment {context.segment_key}")
            return []

        segment_k_models = head_all_models_dict[context.segment_key]
        self.logger.info(f"Processing k labels: {sorted(segment_k_models.keys())}")
        return self._process_all_k_values(
            processed_data, context, segment_k_models,
            individual_frequencies_cluster_assignment_plots,
            generate_interactive_html_plots
        )

    def _process_all_mode_baseline(self, context, processed_data, head_all_models_dict,
                                   individual_frequencies_cluster_assignment_plots,
                                   generate_interactive_html_plots=True):
        """Handle all-mode inference when baseline separation is active"""
        classified = self.baseline_separator.classify_files(
            processed_data.segment_file_dict, processed_data.file_indices
        )

        self.execute_plot.execute_plot_in_process(
            self.inference_engine.plot_overview.create_baseline_group_separation_plot,
            processed_data.segment_file_dict, classified, context.segment_name,
            processed_data.segment_dir, context.head_name,
            self.baseline_separator.LESS_RESONANCE_BAND
        )

        groups = self.baseline_separator.apply_combination(
            classified, context.baseline_data_filtering
        )

        all_summaries = []
        for group_label, group_original_indices in groups.items():
            self.logger.info("="*60)
            self.logger.info(f"  [ALL MODE] Processing group '{group_label}' "
                             f"({len(group_original_indices)} files)")
            self.logger.info("="*60)

            group_summaries = self._process_all_mode_baseline_group(
                context, processed_data, group_label, group_original_indices,
                head_all_models_dict, individual_frequencies_cluster_assignment_plots,
                generate_interactive_html_plots
            )
            all_summaries.extend(group_summaries)

        return all_summaries

    def _process_all_mode_baseline_group(self, context, processed_data, group_label,
                                         group_original_indices, head_all_models_dict,
                                         individual_frequencies_cluster_assignment_plots,
                                         generate_interactive_html_plots=True):
        """Process a single baseline group for all-mode inference"""
        if len(group_original_indices) == 0:
            self.logger.warning(f"  Group '{group_label}' is empty, skipping")
            return []

        group_segment_dict, group_frequencywise_data, group_processed_data = \
            self._build_baseline_group_data(
                context, processed_data, group_label, group_original_indices,
                generate_interactive_html_plots
            )

        segment_k_models = self._resolve_baseline_group_models(
            context, group_label, head_all_models_dict
        )
        if segment_k_models is None:
            del group_segment_dict, group_frequencywise_data
            gc.collect()
            return []

        self.logger.info(f"  Group '{group_label}' k labels: {sorted(segment_k_models.keys())}")
        summaries = self._process_all_k_values(
            group_processed_data, context, segment_k_models,
            individual_frequencies_cluster_assignment_plots,
            generate_interactive_html_plots,
            group_label=group_label
        )

        del group_segment_dict, group_frequencywise_data
        gc.collect()
        return summaries

    def _build_baseline_group_data(self, context, processed_data, group_label,
                                   group_original_indices, generate_interactive_html_plots):
        """Build the group's segment dict, frequencywise data, and processed-data container,
        generating the group's 3D/overview plots along the way"""
        group_segment_dict, group_file_indices = \
            self.baseline_separator.build_group_segment_dict(
                processed_data.segment_file_dict, group_original_indices
            )

        group_frequencywise_data, _, _ = self.preprocessor.create_frequencywise_array(
            group_segment_dict, context.features_list, context.segment_name
        )

        group_dir = os.path.join(processed_data.segment_dir, group_label)
        os.makedirs(group_dir, exist_ok=True)

        self.execute_plot.execute_plot_in_process(
            self.inference_engine.plot_3d.create_3d_visualization,
            group_segment_dict, context.segment_name, group_dir, context.head_name, None, None
        )
        if generate_interactive_html_plots:
            self.execute_plot.execute_plot_in_process(
                self.inference_engine.plot_3d.create_interactive_3d_visualization,
                group_segment_dict, context.segment_name, group_dir, context.head_name
            )

        success, overview_result = self.execute_plot.execute_plot_in_process(
            self.inference_engine.plot_overview.create_segment_overview_analysis,
            group_segment_dict, context.segment_name, group_dir, context.head_name
        )
        if not success or overview_result is False:
            self.logger.warning(
                f"  Group overview failed for '{group_label}' in {context.segment_name}. "
                f"Continuing with inference."
            )

        group_processed_data = ProcessedSegmentData(
            group_frequencywise_data, group_file_indices,
            processed_data.unique_frequencies,
            group_segment_dict, group_dir, context.filenames
        )

        return group_segment_dict, group_frequencywise_data, group_processed_data

    def _resolve_baseline_group_models(self, context, group_label, head_all_models_dict):
        """Look up the trained k_label models for a baseline group/segment_key,
        or None if none are found"""
        if group_label not in head_all_models_dict:
            self.logger.warning(
                f"  No models for group '{group_label}' in all_models_dict, skipping"
            )
            return None

        group_models = head_all_models_dict[group_label]
        if context.segment_key not in group_models:
            self.logger.warning(
                f"  No models for {group_label}/{context.segment_key}, skipping"
            )
            return None

        return group_models[context.segment_key]

    def _process_all_k_values(self, processed_data, context, k_label_models,
                              individual_frequencies_cluster_assignment_plots,
                              generate_interactive_html_plots=True,
                              group_label=None):
        """Process inference for every trained k_label. Former-hierarchical combinations
        are already resolved (at training time) to a single flat model.json per k_label,
        so there is exactly one prediction path regardless of how the model was trained."""
        segment_summaries = []

        # Calculate k=1 baseline once for this segment (or baseline group)
        k1_baseline = self.inference_engine.calculate_segment_k1_baseline(
            processed_data.frequencywise_data, processed_data.file_indices,
            processed_data.unique_frequencies, processed_data.segment_file_dict,
            context.metrics_to_use
        )

        for k_label in sorted(k_label_models.keys()):
            entry = k_label_models[k_label]
            model_path = resolve_path_with_root_dir(entry['path'], context.root_dir)

            self.logger.info(
                f"  Processing {k_label}" + (' (merged)' if entry['is_merged'] else '') + "..."
            )

            try:
                k_value = self.inference_engine.model_load.peek_n_clusters(model_path)

                # When a merged model is used, also peek the pre-merge model's cluster
                # count so merged output filenames can show 'origk<N>_k<M>'
                orig_k_value = None
                if entry['is_merged'] and entry.get('pre_merge_path'):
                    pre_merge_path = resolve_path_with_root_dir(entry['pre_merge_path'], context.root_dir)
                    orig_k_value = self.inference_engine.model_load.peek_n_clusters(pre_merge_path)

                # Create parameters dictionary
                process_params = {
                    'frequencywise_data': processed_data.frequencywise_data,
                    'file_indices': processed_data.file_indices,
                    'unique_frequencies': processed_data.unique_frequencies,
                    'filenames': processed_data.filenames,
                    'segment_name': context.segment_name,
                    'segment_dir': processed_data.segment_dir,
                    'segment_file_dict': processed_data.segment_file_dict,
                    'head_name': context.head_name,
                    'feature_weights': context.feature_weights,
                    'k_value': k_value,
                    'k_label': k_label,
                    'is_merged': entry['is_merged'],
                    'orig_k_value': orig_k_value,
                    'model_path': model_path,
                    'metrics_to_use': context.metrics_to_use,
                    'k1_baseline': k1_baseline,
                    'individual_frequencies_cluster_assignment_plots': individual_frequencies_cluster_assignment_plots,
                    'generate_interactive_html_plots': generate_interactive_html_plots,
                    'group_label': group_label
                }

                summary = self._process_single_k_value(process_params)

                if summary:
                    segment_summaries.append(summary)

            except Exception as e:
                self.logger.error(f"Error processing {k_label} for segment \
{context.segment_name}: {e}", exc_info=True)
                continue

        return segment_summaries

    def _process_single_k_value(self, process_params):
        """Process inference for a single trained model (identified by k_label)"""
        # Extract parameters from dictionary
        frequencywise_data = process_params['frequencywise_data']
        file_indices = process_params['file_indices']
        unique_frequencies = process_params['unique_frequencies']
        segment_name = process_params['segment_name']
        segment_dir = process_params['segment_dir']
        segment_file_dict = process_params['segment_file_dict']
        head_name = process_params['head_name']
        feature_weights = process_params['feature_weights']
        k_value = process_params['k_value']
        k_label = process_params['k_label']
        is_merged = process_params['is_merged']
        orig_k_value = process_params.get('orig_k_value')
        model_path = process_params['model_path']
        metrics_to_use = process_params['metrics_to_use']
        k1_baseline = process_params['k1_baseline']
        individual_frequencies_cluster_assignment_plots = process_params.get(
            'individual_frequencies_cluster_assignment_plots', False
        )
        generate_interactive_html_plots = process_params.get(
            'generate_interactive_html_plots', True
        )

        # Build inference_params dictionary for the inference engine
        inference_params = {
            'frequencywise_data': frequencywise_data,
            'file_indices': file_indices,
            'unique_frequencies': unique_frequencies,
            'segment_name': segment_name,
            'inference_dir': segment_dir,
            'segment_file_dict': segment_file_dict,
            'head_name': head_name,
            'feature_weights': feature_weights,
            'optimal_k': k_value,
            'k_label': k_label,
            'is_merged': is_merged,
            'orig_k_value': orig_k_value,
            'model_path': model_path,
            'current_metric': None,
            'metrics_to_use': metrics_to_use,
            'k1_baseline': k1_baseline,
            'individual_frequencies_cluster_assignment_plots': individual_frequencies_cluster_assignment_plots,
            'generate_interactive_html_plots': generate_interactive_html_plots
        }

        # Call inference engine with dictionary parameter
        result = self.inference_engine.perform_inference_clustering(inference_params)
        inference_results, segment_aci_scores = result

        # Build summary
        group_label = process_params.get('group_label')
        summary = self._build_k_value_summary(
            head_name, segment_name, k_label, k_value, segment_file_dict,
            segment_aci_scores, metrics_to_use, group_label=group_label, is_merged=is_merged,
            orig_k_value=orig_k_value
        )

        return summary
