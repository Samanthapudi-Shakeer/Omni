# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_output_config.py
*  File Description: File that generates "input_inference_config.cfg" that is used
                     as an input config file for the Inference Application.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import logging
import json
from frf_config_utils import HeadKeywordResolver


class OutputConfigWriter(object):
    """Helper class for Output Config Generator, it contains functions that explains the parameters present in
    the "input_inference_config.cfg"
    """

    def __init__(self):
        self.NOTES_HEADER = "#     Notes:\n"
        self.AUTO_GEN = "#     - Auto-generated from training configuration\n"
        self.OPTIONS = "#     Options:\n"
        self.BOOL = "#     Format: True or False\n"
        self.FEATURE_FORMAT = "#     Format: ['real', 'imaginary', 'feature3', ...]\n"
        self.WEIGHT_FORMAT = "#     Format: [weight1, weight2, ...]\n"
        self.POSITIVE_WEIGHTS = "#     - All weights are positive numbers (>0)\n"
        self.RELATIVE_PATH = "#     - All paths are relative to the directory specified in 'root_dir' parameter\n"
        self.ABSOLUTE_PATH = "#     - To get absolute path: os.path.join(root_dir, rel_path)\n"
        self.TRAINED_MODELS = "# trained_models_path (dictionary)\n"

    def _write_root_dir_param(self, f, frf_clustering_analysis_dir):
        """Write root_dir parameter documentation"""
        f.write("# root_dir (string)\n")
        f.write("#     Format: /path/to/output/directory\n")
        f.write("#     Description: Base directory for constructing relative model paths during inference\n")
        f.write(self.NOTES_HEADER)
        f.write("#     - MUST be filled by user before running inference application\n")
        f.write("#     - Should be an path pointing to the parent directory of this analysis folder\n")
        f.write("#     - All relative paths in this config will be resolved as: os.path.join(root_dir, rel_path)\n")
        f.write("#     - If this analysis directory is moved, path should be updated to the new location\n")
        f.write("#     - Path should be without single quotes ('') or double quotes (\"\")\n")
        f.write("#     - Example: If the trained models are in '/data/results/frf_clustering_analysis_<timestamp>/',\n")
        f.write("#                set root_dir = '/data/results/frf_clustering_analysis_<timestamp>'\n")
        f.write(f"root_dir = {frf_clustering_analysis_dir}\n\n")

    def _write_data_dir_list_param(self, f):
        """Write data_dir_list parameter documentation"""
        f.write("# data_dir_list (string)\n")
        f.write("#     Format: /path/to/data_file_list.txt\n")
        f.write("#     Description: Path to text file containing absolute paths to \
.exv, .xpi or .xiz data files for inference\n")
        f.write(self.NOTES_HEADER)
        f.write("#     - Text file must exist and be readable\n")
        f.write("#     - Each line must contain an absolute path to one .exv, .xpi or .xiz file\n")
        f.write("#     - No empty lines, headers, or comments\n")
        f.write("#     - Path provided should be without single quotes ('') or double quotes (\"\")\n")
        f.write("#     - Files must have the individual same frequency values as the training data\n")
        f.write(f"data_dir_list = \n\n")

    def _write_output_path_param(self, f):
        """Write output_path parameter documentation"""
        f.write("# output_path (string)\n")
        f.write("#     Format: /path/to/output/directory\n")
        f.write("#     Description: Directory where inference analysis results will be saved\n")
        f.write(self.NOTES_HEADER)
        f.write("#     - Directory will be created if it doesn't exist\n")
        f.write("#     - Analysis output folder with timestamp will be created inside this directory\n")
        f.write("#     - Path should be without single quotes ('') or double quotes (\"\")\n")
        f.write("#     - Ensure sufficient disk space and write permissions\n")
        f.write("#     Example: /home/user/frf_results or C:\\Users\\user\\frf_results\n")
        f.write(f"output_path = \n\n")

    def _write_frequency_segments_param(self, f, output_config):
        """Write frequency_segments_inference parameter"""
        f.write("# frequency_segments_inference (list of lists)\n")
        f.write("#     Format: [[start_freq1, end_freq1], [start_freq2, end_freq2], ...]\n")
        f.write("#     Description: Defines frequency segments for inferencing\n")
        f.write(self.NOTES_HEADER)
        f.write("#     - Auto-generated from training pipeline\n")
        f.write("#     - Only includes segments where all training files had data\n")
        f.write("#     - Segments are non-overlapping and sorted\n")
        f.write("#     - Same segments used during model training\n")
        f.write(f"frequency_segments_inference = {json.dumps(output_config['frequency_segments_inference'])}\n\n")

    def _write_combined_heads_param(self, f, output_config):
        """Write combined_heads parameter"""
        f.write("# combined_heads (boolean)\n")
        f.write(self.BOOL)
        f.write("#     Description: Whether to analyze combined heads as specified in 'heads' parameter\n")
        f.write(self.OPTIONS)
        f.write("#     - True: Analyze combined heads as per 'heads' list. Must be given \
in the form of list within the main list\n")
        f.write("#     - False: Analyze each head individually as specified in 'heads' list. \
Must be given as a list of strings\n")
        f.write(self.NOTES_HEADER)
        f.write("#     - If True, 'heads' must contain lists of heads to combine within main list\n")
        f.write("#     - If False, 'heads' must contain individual head names as strings\n")
        f.write("#     Example: [['HD0', 'HD15'], 'HD1'] \n")
        f.write(f"combined_heads = {json.dumps(output_config['combined_heads'])}\n\n")

    def _write_heads_param(self, f, output_config):
        """Write heads parameter"""
        f.write("# heads (list or string)\n")
        f.write("#     Format: ['HD0', 'HD1', ...] or [['HD0', 'HD1'], ['HD2', 'HD3']]\n")
        f.write("#     Description: Disk heads that were trained and are available for inference\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write("#     - Head names must start with 'HD' (e.g., HD0, HD1, HDA, HDB)\n")
        f.write("#     - If training used combined heads, they will appear as lists within the main list\n")
        f.write("#     - Inference data must match these head configurations\n")
        f.write("#     - At training time, heads could also be specified using keywords instead of, \
or alongside, literal head names:\n")
        f.write("#         all_heads          : every head available in the training data directory\n")
        f.write("#         odd_number_heads   : heads whose decimal value (HD<hex> converted to decimal) is odd\n")
        f.write("#         even_number_heads  : heads whose decimal value is even (HD0 is even)\n")
        f.write("#         outer_heads        : HD0 plus the head with the largest decimal value\n")
        f.write("#         inner_heads        : all heads other than the outer heads\n")
        f.write(f"heads = {json.dumps(output_config['heads'])}\n\n")

    def _write_metric_param(self, f, output_config):
        """Write metric parameter"""
        f.write("# metric (list)\n")
        f.write("#     Format: ['ACI1'], ['ACI3'], or ['ACI2', 'ACI4']\n")
        f.write("#     Description: Evaluation metrics used during training to determine optimal clusters\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write("#     - At least one metric must be specified\n")
        f.write("#     - Supported metrics: ACI1, ACI2, ACI3, ACI4, Correlation, RMSE, Wasserstein\n")
        f.write("#     - Different metrics may have selected different optimal k values for the same segment\n")
        f.write(f"metric = {json.dumps(output_config['metric'])}\n\n")

    def _write_baseline_params(self, f, output_config):
        """Write baseline_data_separation and, when active, baseline_data_filtering parameters"""
        f.write("# baseline_data_separation (boolean)\n")
        f.write(self.BOOL)
        f.write("#     Description: Whether training data was separated into phase_lead/phase_lag/no_resonance\n")
        f.write("#                  using each file's normalized [-1, 1] + detrended phase curve\n")
        f.write("#                  dominant peak before clustering\n")
        f.write(self.OPTIONS)
        f.write("#     - True: Data was split into groups using the dominant-peak method before clustering\n")
        f.write("#     - False: No separation was applied\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write(f"baseline_data_separation = {json.dumps(output_config['baseline_data_separation'])}\n\n")

        if not output_config['baseline_data_separation']:
            return

        f.write("# baseline_data_filtering (list)\n")
        f.write("#     Format: ['phase_lead', 'phase_lag', 'no_resonance'] or \
[['phase_lead', 'no_resonance'], 'phase_lag']\n")
        f.write("#     Description: Defines how classified groups are combined before clustering.\n")
        f.write("#                  A nested list merges those group names into a single combined group.\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write(f"baseline_data_filtering = {json.dumps(output_config['baseline_data_filtering'])}\n\n")

    def _write_feature_config_path_param(self, f, output_config):
        """Write feature_config_path parameter"""
        f.write("# feature_config_path (string)\n")
        f.write("#     Format: relative/path/to/feature_config.json\n")
        f.write("#     Description: Relative path to the feature configuration JSON file\n")
        f.write("#                  saved during training. Contains the features and weightages\n")
        f.write("#                  used to train the models.\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write("#     - Used by the inference application to verify that the features and\n")
        f.write("#       weightages in this config match those used during training\n")
        f.write("#     - Path is relative to the directory specified in 'root_dir' parameter\n")
        f.write(self.ABSOLUTE_PATH)
        f.write(f"feature_config_path = {json.dumps(output_config['feature_config_path'])}\n\n")

    def _write_max_clusters_param(self, f, output_config):
        """Write frequency_segments_trained_with_max_clusters parameter"""
        is_hierarchical = output_config.get('hierarchical_clustering', False)
        f.write("# frequency_segments_trained_with_max_clusters (dictionary)\n")
        if is_hierarchical:
            f.write("#     Format: {'(start_freq, end_freq)': [stage1_max_k, stage2_max_k], ...}\n")
            f.write("#     Description: Maximum cluster counts trained per stage for each frequency segment\n")
        else:
            f.write("#     Format: {'(start_freq, end_freq)': max_k_value, ...}\n")
            f.write("#     Description: Maximum cluster count trained for each frequency segment\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write("#     - Copied from training config's frequency_segments_max_clusters\n")
        if is_hierarchical:
            f.write("#     - [stage1_max_k, stage2_max_k]: stage 1 models were trained for\n")
            f.write("#       k=2, ..., stage1_max_k; stage 2 models for k=2, ..., stage2_max_k\n")
        else:
            f.write("#     - max_k indicates that models were trained for k=2, k=3, ..., k=max_k\n")
        f.write(f"frequency_segments_trained_with_max_\
clusters = {json.dumps(output_config['frequency_segments_trained_with_max_clusters'], indent=8)}\n\n")

    def _write_trained_models_path_param(self, f, output_config):
        """Write trained_models_path parameter"""
        baseline = output_config.get('baseline_data_separation', False)

        if baseline:
            f.write(self.TRAINED_MODELS)
            f.write("#     Format: {group: [rel_path_to_model1.json, rel_path_to_model2.json, ...], ...}\n")
            f.write("#     Description: Complete registry of all trained model file paths, "
                    "separated by group\n")
            f.write(self.NOTES_HEADER)
            f.write("#     - Auto-generated from training pipeline with baseline separation\n")
            f.write("#     - Keys are group labels from baseline separation\n")
            f.write("#     - Values are lists of relative paths to every trained model.json for that group\n")
            f.write("#     - Includes all k values (2 to max_k) for all segments and heads within each group\n")
            f.write("#     - Hierarchical training contributes one flat single-stage 'combined' model.json\n")
            f.write("#       per (parent_k, stage2_k) combination, alongside stage1-only models — every\n")
            f.write("#       path here predicts directly in one step, there is no stage_1/stage_2 split\n")
            f.write(self.RELATIVE_PATH)
            f.write(self.ABSOLUTE_PATH)
        else:
            f.write("# trained_models_path (list)\n")
            f.write("#     Format: ['./relative/path/to/model1.json', './relative/path/to/model2.json', ...]\n")
            f.write("#     Description: Complete registry of all trained model file paths\n")
            f.write(self.NOTES_HEADER)
            f.write("#     - Auto-generated from training pipeline\n")
            f.write("#     - Contains relative paths to every trained model's JSON file\n")
            f.write("#     - Includes all k values (2 to max_k) for all segments and heads\n")
            f.write("#     - Hierarchical training contributes one flat single-stage 'combined' model.json\n")
            f.write("#       per (parent_k, stage2_k) combination, alongside stage1-only models — every\n")
            f.write("#       path here predicts directly in one step, there is no stage_1/stage_2 split\n")
            f.write("#     - Used for model inventory and validation\n")
            f.write(self.RELATIVE_PATH)
            f.write(self.ABSOLUTE_PATH)
        f.write(f"trained_models_path = {json.dumps(output_config['trained_models_path'], indent=8)}\n\n")

    def _write_post_merging_trained_models_path_param(self, f, output_config):
        """Write post_merging_trained_models_path parameter"""
        baseline = output_config.get('baseline_data_separation', False)
        f.write("# post_merging_trained_models_path (list or dictionary)\n")
        if baseline:
            f.write("#     Format: {group: [rel_path_to_model1.json, rel_path_to_model2.json, ...], ...}\n")
        else:
            f.write("#     Format: ['./relative/path/to/model1.json', './relative/path/to/model2.json', ...]\n")
        f.write("#     Description: Registry of every post-merge (consolidated) model.json produced by "
                "the cluster-merge pipeline\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write("#     - Counterpart to 'trained_models_path', which lists only pre-merge models\n")
        f.write("#     - Only contains models for (segment, k) combinations where a merge actually occurred\n")
        f.write("#     - In hierarchical mode, each entry is a single consolidated model.json covering\n")
        f.write("#       the full (stage1 x stage2) merged cluster set — there is no stage_1/stage_2 split\n")
        f.write(self.RELATIVE_PATH)
        f.write(self.ABSOLUTE_PATH)
        f.write(f"post_merging_trained_models_path = "
                f"{json.dumps(output_config['post_merging_trained_models_path'], indent=8)}\n\n")

    def _write_individual_plots_param(self, f, output_config):
        """Write individual_frequencies_cluster_assignment_plots parameter"""
        f.write("# individual_frequencies_cluster_assignment_plots (boolean)\n")
        f.write(self.BOOL)
        f.write("#     Description: Controls generation of detailed per-frequency \
visualization plots during inference\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write("#     - True: Generate 2D cluster plots and fan segment plots for every individual frequency\n")
        f.write("#     - False: Skip individual frequency plots\n")
        f.write("#     - Individual plots are saved in the inference output directory\n")
        f.write(f"individual_frequencies_cluster_assignment_\
plots = {json.dumps(output_config['individual_frequencies_cluster_assignment_plots'], indent=8)}\n")

    def _write_generate_interactive_html_plots_param(self, f, output_config):
        """Write generate_interactive_html_plots parameter"""
        f.write("\n# generate_interactive_html_plots (boolean)\n")
        f.write(self.BOOL)
        f.write("#     Description: Controls generation of interactive HTML visualization files\n")
        f.write(self.NOTES_HEADER)
        f.write(self.AUTO_GEN)
        f.write("#     - True: Generate interactive HTML Bode plots and 3D trajectory HTML files\n")
        f.write("#     - False: Skip all interactive HTML visualization files\n")
        f.write(f"generate_interactive_html_plots = \
{json.dumps(output_config['generate_interactive_html_plots'], indent=8)}\n")


class OutputConfigGenerator(object):
    """Generates output configuration file"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.outputconfigwriter = OutputConfigWriter()

    def generate_output_config(self, input_config, all_models_registry,
                            all_optimal_k_info, frf_clustering_analysis_dir,
                            all_merged_models_registry=None):
        """Generate input_inference_config.cfg with trained model paths and optimal cluster info"""

        try:
            # Build the output config
            output_config = self._build_output_config_structure(
                input_config, all_models_registry, all_optimal_k_info,
                frf_clustering_analysis_dir, all_merged_models_registry=all_merged_models_registry
            )

            # Save to CFG file
            output_config_path = os.path.join(frf_clustering_analysis_dir, 'input_inference_config.cfg')
            os.makedirs(os.path.dirname(output_config_path), exist_ok=True)

            self._write_config_file(output_config_path, output_config, frf_clustering_analysis_dir)

            self.logger.info(f"   Optimal cluster info for {len(all_optimal_k_info)} segments")
            return frf_clustering_analysis_dir
        except Exception as e:
            self.logger.error(f"Error generating output config: {e}")
            raise

    @staticmethod
    def _build_inference_heads_value(input_config):
        """Build the 'heads' value for the generated inference config, preserving any
        keywords used at training time instead of the fully-expanded literal head
        names. A bare top-level keyword is wrapped in a single-element list when
        combined_heads=True: the inference application auto-detects combined mode
        from list-nesting (it has no separate combined_heads flag), so without this
        wrapping a keyword meant to be combined at training time would instead be
        processed as individual (flat) heads during inference.
        """
        heads_as_configured = input_config.get('heads_as_configured', input_config.get('heads', []))
        if not input_config.get('combined_heads', False):
            return heads_as_configured

        keyword_resolver = HeadKeywordResolver()
        return [[head] if keyword_resolver.is_keyword(head) else head for head in heads_as_configured]

    def _build_output_config_structure(self, input_config, all_models_registry,
                                       all_optimal_k_info, frf_clustering_analysis_dir,
                                       all_merged_models_registry=None):
        """Build the complete output configuration dictionary with relative paths"""
        output_config = {}
        is_hierarchical = input_config.get('hierarchical_clustering', False)
        baseline_separation = input_config.get('baseline_data_separation', False)
        all_merged_models_registry = all_merged_models_registry or []

        # 1. frequency_segments_inference
        output_config['frequency_segments_inference'] = self._build_validated_segments(all_optimal_k_info)

        # 2. data_dir
        output_config['data_dir_list'] = input_config.get('data_dir_list', '')
        output_config['worst_model_dir_list'] = self._get_worst_model_dir(input_config)
        output_config['output_path'] = input_config.get('output_path', '')

        # 3. metric
        output_config['metric'] = input_config.get('metric', ['ACI1', 'ACI2', 'ACI3', 'ACI4'])

        # 4. heads
        output_config['heads'] = self._build_inference_heads_value(input_config)
        output_config['combined_heads'] = input_config.get('combined_heads', False)

        # 5. hierarchical_clustering flag
        output_config['hierarchical_clustering'] = is_hierarchical

        # 6. baseline parameters
        self._add_baseline_config(output_config, input_config, baseline_separation,
                                  frf_clustering_analysis_dir)

        # 7. frequency_segments_trained_with_max_clusters
        output_config['frequency_segments_trained_with_max_clusters'] = input_config.get(
            'frequency_segments_max_clusters', {})

        # 8a. trained_models_path
        output_config['trained_models_path'] = self._build_trained_models_config(
            is_hierarchical, baseline_separation, all_models_registry, frf_clustering_analysis_dir
        )

        # 8b. post_merging_trained_models_path — registry of every post-merge model.json produced
        output_config['post_merging_trained_models_path'] = self._build_post_merging_trained_models_config(
            baseline_separation, all_merged_models_registry, frf_clustering_analysis_dir
        )

        # 9. individual_frequencies_cluster_assignment_plots
        output_config['individual_frequencies_cluster_assignment_plots'] = input_config.get(
            'individual_frequencies_cluster_assignment_plots', False)

        # 10. generate_interactive_html_plots
        output_config['generate_interactive_html_plots'] = input_config.get(
            'generate_interactive_html_plots', True)

        return output_config

    def _add_baseline_config(self, output_config, input_config, baseline_separation,
                             frf_clustering_analysis_dir):
        """Add baseline-related configuration parameters."""
        output_config['baseline_data_separation'] = baseline_separation
        if baseline_separation:
            output_config['baseline_data_filtering'] = input_config.get('baseline_data_filtering')
        models_base_dir = os.path.join(frf_clustering_analysis_dir, 'trained_models')
        feature_config_abs = os.path.join(models_base_dir, 'feature_config.json')
        output_config['feature_config_path'] = self._convert_to_relative_path(
            feature_config_abs, frf_clustering_analysis_dir
        )

    def _build_trained_models_config(self, is_hierarchical, baseline_separation,
                                      all_models_registry, frf_clustering_analysis_dir):
        """Build trained_models_path based on mode."""
        builder = self._select_trained_models_builder(is_hierarchical, baseline_separation)
        if builder is not None:
            return builder(all_models_registry, frf_clustering_analysis_dir)
        return [
            self._convert_to_relative_path(entry['trained_model_path'], frf_clustering_analysis_dir)
            for entry in all_models_registry
        ]

    def _select_trained_models_builder(self, is_hierarchical, baseline_separation):
        """Select the appropriate builder method based on mode flags.

        trained_models_path is now always a flat list (or, under baseline separation,
        a flat list per group) of single-stage model.json paths — hierarchical
        combinations are represented by their flat consolidated 'combined' model, the
        exact same entry shape as normal single-stage training, so builder selection
        depends only on whether baseline-separation grouping is active. is_hierarchical
        is accepted for call-site compatibility but no longer changes this selection.
        """
        del is_hierarchical
        if baseline_separation:
            return self._build_trained_models_path_baseline
        return None

    def _build_post_merging_trained_models_config(self, baseline_separation,
                                                   all_merged_models_registry,
                                                   frf_clustering_analysis_dir):
        """Build post_merging_trained_models_path.

        Merged (consolidated) models are always flat single model.json entries — even in
        hierarchical mode, since merging combines the whole (stage1 x stage2) cluster set
        into one model — so this reuses the flat/baseline builders regardless of mode.
        """
        if baseline_separation:
            return self._build_trained_models_path_baseline(
                all_merged_models_registry, frf_clustering_analysis_dir
            )
        return [
            self._convert_to_relative_path(entry['trained_model_path'], frf_clustering_analysis_dir)
            for entry in all_merged_models_registry
        ]

    @staticmethod
    def _convert_to_relative_path(absolute_path, base_dir):
        """Convert absolute path to relative path from base directory"""
        if absolute_path is None:
            return None

        try:
            # Get relative path from base directory
            rel_path = os.path.relpath(absolute_path, base_dir)
            # Normalize path separators and ensure it starts with ./
            rel_path = os.path.normpath(rel_path)
            if not rel_path.startswith('.'):
                rel_path = os.path.join('.', rel_path)
            return rel_path
        except ValueError:
            # Paths on different drives on Windows, return absolute path
            return absolute_path

    @staticmethod
    def _build_validated_segments(all_optimal_k_info):
        """Build validated segments list from optimal k info (or hierarchical optimal info —
        both entry shapes carry a 'segment_tuple' key)."""
        validated_segments = []
        seen_segments = set()

        for opt_info in all_optimal_k_info:
            segment_tuple = opt_info['segment_tuple']
            segment_key = (segment_tuple[0], segment_tuple[1])
            if segment_key not in seen_segments:
                seen_segments.add(segment_key)
                validated_segments.append([segment_tuple[0], segment_tuple[1]])

        validated_segments.sort(key=lambda x: x[0])
        return validated_segments

    @staticmethod
    def _get_worst_model_dir(input_config):
        """Get worst model directory with fallback to empty string"""
        worst_model_dir = input_config.get('worst_model_dir_list', None)
        return worst_model_dir if worst_model_dir is not None else ''

    def _build_trained_models_path_baseline(self, all_models_registry, frf_clustering_analysis_dir):
        """Build trained_models_path for baseline=True (both hierarchical and
        non-hierarchical — hierarchical entries are now flat single-stage 'combined'
        model entries with the same shape as normal training entries)."""
        result = {}
        for entry in all_models_registry:
            group = entry.get('group')
            if group is None:
                continue
            if group not in result:
                result[group] = []
            rel_path = self._convert_to_relative_path(
                entry['trained_model_path'], frf_clustering_analysis_dir
            )
            result[group].append(rel_path)
        return result

    def _write_config_file(self, output_config_path, output_config, frf_clustering_analysis_dir):
        """Write the configuration to a CFG file"""
        with open(output_config_path, 'w', encoding='utf-8-sig') as f:
            self._write_required_parameters_section(f, frf_clustering_analysis_dir)
            self._write_training_specifications_section(f, output_config)

    def _write_required_parameters_section(self, f, frf_clustering_analysis_dir):
        """Write the INFERENCE_APPLICATION_REQUIRED_PARAMETER section"""
        f.write("[INFERENCE_APPLICATION_REQUIRED_PARAMETER] \n\n")

        self.outputconfigwriter._write_root_dir_param(f, frf_clustering_analysis_dir)
        self.outputconfigwriter._write_data_dir_list_param(f)
        self.outputconfigwriter._write_output_path_param(f)

    def _write_training_specifications_section(self, f, output_config):
        """Write the TRAINING_APPLICATION_SPECIFICATIONS section"""
        f.write("[TRAINING_APPLICATION_SPECIFICATIONS] \n\n")

        self.outputconfigwriter._write_frequency_segments_param(f, output_config)
        self.outputconfigwriter._write_combined_heads_param(f, output_config)
        self.outputconfigwriter._write_heads_param(f, output_config)
        self.outputconfigwriter._write_metric_param(f, output_config)
        self.outputconfigwriter._write_feature_config_path_param(f, output_config)
        self.outputconfigwriter._write_baseline_params(f, output_config)
        self.outputconfigwriter._write_max_clusters_param(f, output_config)
        self.outputconfigwriter._write_trained_models_path_param(f, output_config)
        self.outputconfigwriter._write_post_merging_trained_models_path_param(f, output_config)
        self.outputconfigwriter._write_individual_plots_param(f, output_config)
        self.outputconfigwriter._write_generate_interactive_html_plots_param(f, output_config)
