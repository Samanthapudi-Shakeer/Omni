# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_config_validators.py
*  File Description: Validators for inference configuration loader
*  All rights reserved.
*
*********************************************************************/
"""

import os
import logging
from frf_inference_config_utils import transform_head_code, ConfigValidationError


class TrainedModelsPathValidator(object):
    """Validates trained_models_path and post_merging_trained_models_path and builds
    all_models_dict, resolving merge preference (a merged model is used in place of its
    pre-merge counterpart whenever one exists for the same head/[group]/segment/k_label)"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_and_build_all_models_dict(self, config):
        """Validate trained_models_path / post_merging_trained_models_path, then build a
        single all_models_dict with merge preference already resolved"""
        trained_models_path = config.get('trained_models_path')
        root_dir = config.get('root_dir', '')
        hierarchical = config.get('hierarchical_clustering', False)
        baseline = config.get('baseline_data_separation', False)
        expected_head_names = self._get_expected_head_names(config['heads'])

        self._validate_trained_models_path_exists(trained_models_path)
        post_merging_trained_models_path = self._default_post_merging_path(
            config.get('post_merging_trained_models_path'), baseline
        )

        pre_merge_dict = self._build_models_dict(
            trained_models_path, hierarchical, baseline, expected_head_names, root_dir
        )
        merged_dict = self._build_models_dict(
            post_merging_trained_models_path, hierarchical, baseline, expected_head_names, root_dir
        )

        all_models_dict = self._resolve_with_merge_preference(pre_merge_dict, merged_dict, baseline)

        self._log_models_summary(all_models_dict, hierarchical, baseline)
        config['all_models_dict'] = all_models_dict
        return config

    def _validate_trained_models_path_exists(self, trained_models_path):
        """Confirm the parameter is present and non-empty"""
        if trained_models_path is None:
            error_msg = "Missing REQUIRED parameter: 'trained_models_path'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not trained_models_path:
            error_msg = "'trained_models_path' cannot be empty"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    @staticmethod
    def _default_post_merging_path(post_merging_trained_models_path, baseline):
        """Default post_merging_trained_models_path to an empty container matching the
        expected shape when absent — a merge registry may legitimately be empty"""
        if post_merging_trained_models_path is not None:
            return post_merging_trained_models_path
        return {} if baseline else []

    def _build_models_dict(self, models_path_param, hierarchical, baseline,
                           expected_head_names, root_dir):
        """Build {head: {segment_key: {k_label: model_path}}}, or with a group level when
        baseline separation is active {head: {group: {segment_key: {k_label: model_path}}}}"""
        if baseline:
            return self._build_grouped_models_dict(
                models_path_param, hierarchical, expected_head_names, root_dir
            )
        return self._build_flat_models_dict(
            models_path_param, hierarchical, expected_head_names, root_dir
        )

    def _build_flat_models_dict(self, models_path_param, hierarchical,
                                expected_head_names, root_dir):
        """Build the ungrouped dict from a flat list of model paths"""
        if not isinstance(models_path_param, list):
            error_msg = (f"Expected a flat list of model paths (baseline_data_separation=False), "
                         f"got {type(models_path_param).__name__}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        result = {}
        for model_path in models_path_param:
            self._add_parsed_entry(
                result, model_path, hierarchical, None, expected_head_names, root_dir
            )
        return result

    def _build_grouped_models_dict(self, models_path_param, hierarchical,
                                   expected_head_names, root_dir):
        """Build the group-keyed dict from a {group: [model_paths]} dict"""
        if not isinstance(models_path_param, dict):
            error_msg = (f"Expected a dict keyed by group (baseline_data_separation=True), "
                         f"got {type(models_path_param).__name__}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        result = {}
        for group_label, model_paths in models_path_param.items():
            if not isinstance(model_paths, list):
                self.logger.warning(f"Expected list for group '{group_label}', skipping")
                continue
            for model_path in model_paths:
                self._add_parsed_entry(
                    result, model_path, hierarchical, group_label, expected_head_names, root_dir
                )
        return result

    def _add_parsed_entry(self, result, model_path, hierarchical, group_label,
                          expected_head_names, root_dir):
        """Parse a single model path and, if valid, add it to the result dict"""
        abs_path = os.path.join(root_dir, os.path.normpath(model_path))
        if not os.path.exists(abs_path):
            self.logger.warning(f"Model not found: {model_path} -> {abs_path}")
            return

        parsed = self._parse_model_path(
            model_path, hierarchical, group_label is not None, expected_head_names
        )
        if parsed is None:
            return

        head_name, segment_key, k_label = parsed
        if group_label is None:
            result.setdefault(head_name, {}).setdefault(segment_key, {})
            result[head_name][segment_key][k_label] = model_path
        else:
            result.setdefault(head_name, {}).setdefault(group_label, {}) \
                  .setdefault(segment_key, {})
            result[head_name][group_label][segment_key][k_label] = model_path

    def _parse_model_path(self, model_path, hierarchical, under_group, expected_head_names):
        """Parse a trained (or post-merge) model path to extract head, segment, and k_label"""
        try:
            return self._compute_model_path_result(
                model_path, hierarchical, under_group, expected_head_names
            )
        except Exception as e:
            self.logger.warning(f"Error parsing model path '{model_path}': {e}")
            return None

    @staticmethod
    def _strip_merged_component(parts):
        """Remove a trailing 'merged' directory (immediately before model.json) so merged
        and pre-merge paths parse identically from this point on"""
        if len(parts) >= 2 and parts[-2] == 'merged':
            return parts[:-2] + parts[-1:]
        return parts

    def _compute_model_path_result(self, model_path, hierarchical, under_group, expected_head_names):
        """Extract and validate (head_name, segment_key, k_label) from a model path"""
        normalized = os.path.normpath(model_path)
        parts = self._strip_merged_component(normalized.split(os.sep))

        skip = (1 if hierarchical else 0) + (1 if under_group else 0)
        seg_pos = -(3 + skip)
        head_pos = -(4 + skip)

        if len(parts) < abs(head_pos):
            self.logger.warning(f"Path too short to parse: {model_path}")
            return None

        return self._validate_model_path_parts(parts, seg_pos, head_pos, expected_head_names)

    def _validate_model_path_parts(self, parts, seg_pos, head_pos, expected_head_names):
        """Validate parsed path components and build the (head_name, segment_key, k_label) result"""
        k_label = parts[-2]
        segment_dir = parts[seg_pos]
        head_name = parts[head_pos]

        if head_name not in expected_head_names:
            return None

        segment_key = self._build_segment_key(segment_dir)
        if segment_key is None:
            return None

        return head_name, segment_key, k_label

    def _resolve_with_merge_preference(self, pre_merge_dict, merged_dict, baseline):
        """Resolve final model registry, preferring the merged model for any
        (head, [group,] segment_key, k_label) combination where one exists"""
        if baseline:
            return self._merge_grouped_dict(pre_merge_dict, merged_dict)
        return self._merge_flat_dict(pre_merge_dict, merged_dict)

    def _merge_flat_dict(self, pre_merge_dict, merged_dict):
        """Resolve merge preference for {head: {segment_key: {k_label: path}}}"""
        result = {}
        for head_name, segments in pre_merge_dict.items():
            merged_segments = merged_dict.get(head_name, {})
            result[head_name] = {}
            for segment_key, k_label_paths in segments.items():
                merged_k_label_paths = merged_segments.get(segment_key, {})
                result[head_name][segment_key] = self._resolve_k_labels(
                    k_label_paths, merged_k_label_paths
                )
        return result

    def _merge_grouped_dict(self, pre_merge_dict, merged_dict):
        """Resolve merge preference for {head: {group: {segment_key: {k_label: path}}}}"""
        result = {}
        for head_name, groups in pre_merge_dict.items():
            merged_groups = merged_dict.get(head_name, {})
            result[head_name] = {}
            for group_label, segments in groups.items():
                merged_segments = merged_groups.get(group_label, {})
                result[head_name][group_label] = {}
                for segment_key, k_label_paths in segments.items():
                    merged_k_label_paths = merged_segments.get(segment_key, {})
                    result[head_name][group_label][segment_key] = self._resolve_k_labels(
                        k_label_paths, merged_k_label_paths
                    )
        return result

    @staticmethod
    def _resolve_k_labels(pre_merge_k_labels, merged_k_labels):
        """Merge one segment's k_label->path map, preferring the merged path per k_label
        and recording whether each resolved entry came from a merge. The pre-merge path
        is retained even when merged, so the original (pre-merge) cluster count can be
        looked up later for 'origk<N>_k<M>' file naming."""
        resolved = {}
        for k_label, path in pre_merge_k_labels.items():
            if k_label in merged_k_labels:
                resolved[k_label] = {
                    'path': merged_k_labels[k_label],
                    'is_merged': True,
                    'pre_merge_path': path
                }
            else:
                resolved[k_label] = {'path': path, 'is_merged': False, 'pre_merge_path': None}
        for k_label, path in merged_k_labels.items():
            if k_label not in resolved:
                resolved[k_label] = {'path': path, 'is_merged': True, 'pre_merge_path': None}
        return resolved

    def _build_segment_key(self, freq_dir):
        """Build segment key string from a frequency directory name like '9500.00_11500.00Hz'"""
        try:
            freq_parts = freq_dir.replace('Hz', '').split('_')
            freq_min = float(freq_parts[0])
            freq_max = float(freq_parts[1])
            return f"({freq_min}, {freq_max})"
        except Exception:
            self.logger.warning(f"Cannot parse frequency from directory: {freq_dir}")
            return None

    def _log_models_summary(self, all_models_dict, hierarchical, baseline):
        """Log a brief summary of the built all_models_dict"""
        self.logger.info(f"Built all_models_dict for {len(all_models_dict)} heads "
                         f"(hierarchical={hierarchical}, baseline_data_separation={baseline})")
        for head_name, head_data in all_models_dict.items():
            self.logger.info(f"  {head_name}: {len(head_data)} top-level entries")

    def _get_expected_head_names(self, heads_list):
        """Return the canonical head name strings after transformation for combined
        heads, matching the inference application's naming exactly — including the
        keyword-based names (e.g. 'even_number_hds') used when a combined-heads
        group was built from head-selection keyword(s), instead of concatenating
        every individual head code."""
        expected_names = []
        for head_spec in heads_list:
            if isinstance(head_spec, str):
                expected_names.append(head_spec)
            elif isinstance(head_spec, list):
                expected_names.append(self._build_combined_head_name(head_spec))
        return expected_names

    @staticmethod
    def _build_combined_head_name(head_spec):
        """Build the expected head name for a combined-heads group, matching the
        inference application's naming exactly (frf_inference_application.py::
        HeadProcessor._build_combined_head_name). Groups built from head-selection
        keyword(s) use the keyword name(s) (with '_heads' shortened to '_hds')
        instead of the previous 'HD_ALL' shortcut; any manually-typed heads mixed
        in alongside keyword(s) are appended as transformed head codes to keep
        the name unique."""
        keywords_used = getattr(head_spec, 'keywords', [])
        if not keywords_used:
            transformed_codes = [transform_head_code(h) for h in sorted(head_spec)]
            return f"HD_{''.join(transformed_codes)}"

        shortened_keywords = [k.replace('_heads', '_hds') for k in sorted(keywords_used)]
        head_name = '_'.join(shortened_keywords)
        literal_heads = getattr(head_spec, 'literal_heads', [])
        if literal_heads:
            extra_codes = [transform_head_code(h) for h in sorted(literal_heads)]
            head_name = f"{head_name}_{''.join(extra_codes)}"
        return head_name


class IndividualFrequenciesClusterAssignmentPlots(object):
    """Validation checks for individual frequencies cluster assignment plots"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.PLOTS_DEFAULT_VALUE = False

    def validate_individual_frequencies_cluster_assignment_plots(self, config):
        """Validate individual_frequencies_cluster_assignment_plots parameter"""

        if 'individual_frequencies_cluster_assignment_plots' not in config:
            config['individual_frequencies_cluster_assignment_plots'] = self.PLOTS_DEFAULT_VALUE
            self.logger.info(f"No individual_frequencies_cluster_assignment_plots specified")
            return config
        else:
            plot_setting = config['individual_frequencies_cluster_assignment_plots']

        if not isinstance(plot_setting, bool):
            warning_msg = f"'individual_frequencies_cluster_assignment_plots' must be a boolean (True or False)"
            self.logger.warning(warning_msg)
            config['individual_frequencies_cluster_assignment_plots'] = self.PLOTS_DEFAULT_VALUE
            return config

        self.logger.info(f"Validated individual_frequencies_cluster_assignment_plots: {plot_setting}")
        return config


class GenerateInteractiveHtmlPlots(object):
    """Validation checks for generate_interactive_html_plots parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.HTML_PLOTS_DEFAULT_VALUE = True

    def validate_generate_interactive_html_plots(self, config):
        """Validate generate_interactive_html_plots parameter"""

        if 'generate_interactive_html_plots' not in config:
            config['generate_interactive_html_plots'] = self.HTML_PLOTS_DEFAULT_VALUE
            self.logger.info(f"No generate_interactive_html_plots specified")
            self.logger.info(f"Using default: {self.HTML_PLOTS_DEFAULT_VALUE}")
            return config
        else:
            html_plot_setting = config['generate_interactive_html_plots']

        if not isinstance(html_plot_setting, bool):
            warning_msg = (f"'generate_interactive_html_plots' must be a boolean (True or False). "
                           f"Got {type(html_plot_setting).__name__}. "
                           f"Using default: {self.HTML_PLOTS_DEFAULT_VALUE}")
            self.logger.warning(warning_msg)
            config['generate_interactive_html_plots'] = self.HTML_PLOTS_DEFAULT_VALUE
            return config

        self.logger.info(f"Validated generate_interactive_html_plots: {html_plot_setting}")
        return config


class BaselineParametersValidator(object):
    """Validates baseline_data_separation and, when active, baseline_data_filtering —
    matching the training application's simpler (threshold-free, self-contained) design"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.VALID_BASE_GROUPS = {'phase_lead', 'phase_lag', 'no_resonance'}

    def validate_baseline_parameters(self, config):
        """Validate all baseline-separation-related parameters"""
        config = self._validate_baseline_separation_flag(config)
        baseline = config['baseline_data_separation']

        if not baseline:
            self._validate_null_when_disabled(config)
            return config

        config = self._validate_baseline_data_filtering(config)
        return config

    def _validate_baseline_separation_flag(self, config):
        """Validate the baseline_data_separation boolean"""
        if 'baseline_data_separation' not in config:
            error_msg = "Missing REQUIRED parameter: 'baseline_data_separation'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        value = config['baseline_data_separation']
        if not isinstance(value, bool):
            error_msg = (f"'baseline_data_separation' must be a boolean, "
                         f"got {type(value).__name__}: {value!r}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self.logger.info(f"Validated baseline_data_separation: {value}")
        return config

    def _validate_null_when_disabled(self, config):
        """Warn if baseline_data_filtering is unexpectedly non-null when separation is False"""
        if config.get('baseline_data_filtering') is not None:
            self.logger.warning(
                "'baseline_data_filtering' is set but 'baseline_data_separation' is False - "
                "value will be ignored"
            )

    def _validate_baseline_data_filtering(self, config):
        """Validate baseline_data_filtering list/nested-list structure"""
        if 'baseline_data_filtering' not in config or config['baseline_data_filtering'] is None:
            error_msg = ("'baseline_data_filtering' must be provided when "
                         "'baseline_data_separation' is True")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        combination = config['baseline_data_filtering']

        if not isinstance(combination, list) or len(combination) == 0:
            error_msg = "'baseline_data_filtering' must be a non-empty list"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Flatten to collect all individual group names for validation
        all_group_names = []
        for item in combination:
            if isinstance(item, str):
                all_group_names.append(item)
            elif isinstance(item, list):
                all_group_names.extend(self._expand_combination_list_item(item))
            else:
                error_msg = (f"'baseline_data_filtering' items must be strings or lists, "
                             f"got {type(item).__name__}: {item!r}")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        invalid_groups = [g for g in all_group_names if g not in self.VALID_BASE_GROUPS]
        if invalid_groups:
            error_msg = (f"Invalid group names in 'baseline_data_filtering': {invalid_groups}. "
                         f"Valid values: {sorted(self.VALID_BASE_GROUPS)}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self.logger.info(f"Validated baseline_data_filtering: {combination}")
        return config

    def _expand_combination_list_item(self, item):
        """Validate that all sub-items are strings and return the list"""
        for sub_item in item:
            if not isinstance(sub_item, str):
                error_msg = (f"'baseline_data_filtering' sub-items must be strings, "
                             f"got {type(sub_item).__name__}")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
        return item


class FeatureConfigPathValidator(object):
    """Validates the feature_config_path parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_feature_config_path(self, config):
        """Validate feature_config_path is present, a string, and the file exists"""
        if 'feature_config_path' not in config:
            error_msg = "Missing REQUIRED parameter: 'feature_config_path'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        rel_path = config['feature_config_path']

        if not isinstance(rel_path, str) or not rel_path.strip():
            error_msg = (f"'feature_config_path' must be a non-empty string, "
                         f"got {type(rel_path).__name__}: {rel_path!r}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        root_dir = config.get('root_dir', '')
        abs_path = os.path.join(root_dir, os.path.normpath(rel_path))

        if not os.path.exists(abs_path):
            error_msg = (f"'feature_config_path' file not found: "
                         f"{rel_path} → {abs_path}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not os.path.isfile(abs_path):
            error_msg = f"'feature_config_path' is not a file: {abs_path}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Store resolved absolute path for downstream use
        config['feature_config_path_resolved'] = abs_path
        self.logger.info(f"Validated feature_config_path: {rel_path} → {abs_path}")
        return config


class MaxClustersValidator(object):
    """Validates frequency_segments_trained_with_max_clusters parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_max_clusters(self, config):
        """Validate frequency_segments_trained_with_max_clusters is present and well-formed"""
        key = 'frequency_segments_trained_with_max_clusters'

        if key not in config:
            error_msg = f"Missing REQUIRED parameter: '{key}'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        max_clusters = config[key]

        if not isinstance(max_clusters, dict) or not max_clusters:
            error_msg = f"'{key}' must be a non-empty dictionary"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        hierarchical = config.get('hierarchical_clustering', False)

        for segment_key, value in max_clusters.items():
            if not isinstance(segment_key, str):
                error_msg = f"'{key}' segment keys must be strings, got {type(segment_key).__name__}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            self._validate_segment_cluster_value(key, segment_key, value, hierarchical)

        self.logger.info(f"Validated {key}: {len(max_clusters)} segment(s)")
        return config

    def _validate_segment_cluster_value(self, key, segment_key, value, hierarchical):
        """Validate the cluster value for a single segment entry (hierarchical or flat)"""
        if hierarchical:
            # Expect [stage1_max_k, stage2_max_k]
            if not isinstance(value, list) or len(value) != 2:
                error_msg = (f"'{key}[{segment_key}]' must be a list of 2 integers "
                             f"[stage1_max_k, stage2_max_k] when hierarchical_clustering=True, "
                             f"got {value!r}")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            for idx, v in enumerate(value):
                if not isinstance(v, int) or v < 2:
                    error_msg = (f"'{key}[{segment_key}][{idx}]' must be an integer >= 2, "
                                 f"got {v!r}")
                    self.logger.error(error_msg)
                    raise ConfigValidationError(error_msg)
        else:
            # Expect a single int
            if not isinstance(value, int) or value < 2:
                error_msg = (f"'{key}[{segment_key}]' must be an integer >= 2 "
                             f"when hierarchical_clustering=False, got {value!r}")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
