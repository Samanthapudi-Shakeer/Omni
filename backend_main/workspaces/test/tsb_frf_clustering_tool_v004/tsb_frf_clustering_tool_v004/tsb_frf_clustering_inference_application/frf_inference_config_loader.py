# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_config_loader.py
*  File Description: Configuration loader for inference application
*  All rights reserved.
*
*********************************************************************/
"""

import os
import logging
import json
from frf_inference_config_utils import transform_head_code, ConfigValidationError, DataDirectoryValidator
from frf_inference_config_utils import DataDirectoryAnalyzer, ConfigStructureValidator, ConfigSummaryPrinter
from frf_inference_config_utils import FrequencySegmentValidator, MetricValidator, RootDirValidator, OutputDirValidator
from frf_inference_config_utils import HeadKeywordResolver, KeywordExpandedHeads
from frf_inference_config_validators import TrainedModelsPathValidator, IndividualFrequenciesClusterAssignmentPlots
from frf_inference_config_validators import GenerateInteractiveHtmlPlots, BaselineParametersValidator
from frf_inference_config_validators import FeatureConfigPathValidator, MaxClustersValidator


class HeadsValidator(object):
    """Validates heads parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.data_analyzer = DataDirectoryAnalyzer()
        self.keyword_resolver = HeadKeywordResolver()

    def validate_heads(self, config):
        """Validate heads parameter with automatic combined heads detection"""
        if 'heads' not in config:
            error_msg = "Missing REQUIRED parameter: 'heads'. You must specify which heads to analyze"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        heads = config['heads']

        if not isinstance(heads, list):
            error_msg = f"'heads' must be a list, got {type(heads).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not heads:
            error_msg = "'heads' list cannot be empty"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Expand head-selection keywords (e.g. 'even_number_heads') into literal head names
        heads = self._expand_head_keywords(heads, config['data_dir_list'])
        config['heads'] = heads

        # Detect combined heads format
        combined_heads = any(isinstance(h, list) for h in heads)
        config['combined_heads'] = combined_heads

        if combined_heads:
            self.logger.info("Detected combined heads format in configuration")
            self._validate_combined_heads(heads, config)
        else:
            self.logger.info("Detected individual heads format in configuration")
            self._validate_individual_heads(heads, config)

        return config

    def _expand_head_keywords(self, heads, data_dir_list):
        """Expand any head-selection keywords in 'heads' into literal head names.

        - A bare top-level keyword is replaced with individual heads (flat) -
          to get a combined group from a keyword, wrap it in a list (e.g.
          [['even_number_heads']]), consistent with how any other combined
          group must already be written here.
        - A keyword found inside an explicit list is flattened into that same
          list, alongside any literal heads already in it.
        No deduplication is performed - resolved heads are spliced in exactly
        where the keyword was, so the existing validation below (duplicate
        checks, minimum-heads-per-group, etc.) applies unchanged.
        """
        if not self._contains_head_keyword(heads):
            return heads

        available_heads = self.data_analyzer.get_all_available_heads(data_dir_list)

        expanded = []
        for head_spec in heads:
            if isinstance(head_spec, list):
                expanded.append(self._expand_combo_group(head_spec, available_heads))
            elif self.keyword_resolver.is_keyword(head_spec):
                expanded.extend(self.keyword_resolver.resolve_keyword(head_spec, available_heads))
            else:
                expanded.append(head_spec)

        return expanded

    def _expand_combo_group(self, head_spec, available_heads):
        """Flatten any keyword found inside an explicit combo group into that group,
        remembering which keyword(s) and which manually-typed heads it contains."""
        expanded_group = []
        keywords_used = []
        literal_heads = []
        for item in head_spec:
            if self.keyword_resolver.is_keyword(item):
                expanded_group.extend(self.keyword_resolver.resolve_keyword(item, available_heads))
                keywords_used.append(item)
            else:
                expanded_group.append(item)
                literal_heads.append(item)

        if keywords_used:
            return KeywordExpandedHeads(expanded_group, keywords_used, literal_heads)
        return expanded_group

    def _contains_head_keyword(self, heads):
        """Check whether 'heads' contains a keyword, at the top level or within a list"""
        for head_spec in heads:
            if isinstance(head_spec, list):
                if any(self.keyword_resolver.is_keyword(item) for item in head_spec):
                    return True
            elif self.keyword_resolver.is_keyword(head_spec):
                return True
        return False

    def _validate_individual_heads(self, heads, config):
        """Validate individual heads format"""
        for idx, head in enumerate(heads):
            self._validate_head_string(head, idx)

        # Check for duplicates
        if len(heads) != len(set(heads)):
            duplicates = [head for head in heads if heads.count(head) > 1]
            error_msg = f"Duplicate head names found: {list(set(duplicates))}. Please remove the duplicates"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Verify heads exist in data
        self._verify_heads_in_data(heads, config)
        self.logger.info(f"Validated heads: {heads}")

    def _validate_combined_heads(self, heads, config):
        """Validate combined heads format"""
        all_individual_heads = []
        seen_combinations = []

        for idx, head_spec in enumerate(heads):
            if isinstance(head_spec, str):
                self._process_single_head_in_combined_mode(head_spec, idx, all_individual_heads, seen_combinations)
            elif isinstance(head_spec, list):
                self._process_combined_head_group(head_spec, idx, all_individual_heads, seen_combinations)
            else:
                error_msg = (f"'heads[{idx}]' must be either a string or a list. "
                           f"Got {type(head_spec).__name__}: {head_spec}")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        # Verify all heads exist in data
        self._verify_heads_in_data(all_individual_heads, config)
        self.logger.info(f"Validated heads with combined_heads=True: {heads}")

    def _process_single_head_in_combined_mode(self, head_spec, idx, all_individual_heads, seen_combinations):
        """Process a single head within combined heads mode"""
        self._validate_head_string(head_spec, idx)
        all_individual_heads.append(head_spec)

        # Check for duplicate combinations
        combo_set = frozenset([head_spec])
        if combo_set in seen_combinations:
            error_msg = f"Duplicate head specification found: '{head_spec}' appears multiple times"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        seen_combinations.append(combo_set)

    def _process_combined_head_group(self, head_spec, idx, all_individual_heads, seen_combinations):
        """Process a combined head group (list of heads)"""
        if len(head_spec) < 2:
            error_msg = (f"'heads[{idx}]' is a list but contains less than 2 heads: {head_spec}. "
                       f"Combined heads must have at least 2 head names")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Validate each head in the list
        for individual_head_idx, head in enumerate(head_spec):
            self._validate_head_string_in_list(head, idx, individual_head_idx)
            all_individual_heads.append(head)

        # Check for duplicates within the sublist
        if len(head_spec) != len(set(head_spec)):
            duplicates = [head for head in head_spec if head_spec.count(head) > 1]
            error_msg = f"Duplicate heads within combined group 'heads[{idx}]': {list(set(duplicates))}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Check for duplicate combinations
        combo_set = frozenset(head_spec)
        if combo_set in seen_combinations:
            error_msg = f"Duplicate combination found: {head_spec}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        seen_combinations.append(combo_set)

    def _validate_head_string(self, head, idx):
        """Validate a single head string (common validation logic)"""
        if not isinstance(head, str):
            error_msg = f"'heads[{idx}]' must be a string, got {type(head).__name__}: {head}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if len(head) == 0:
            error_msg = f"Head name: 'heads[{idx}]' cannot be an empty string"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if len(head) != len(head.strip()):
            error_msg = f"Head name:'{head}' has leading/trailing whitespace (spaces, tabs, or newlines)"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not head.startswith('HD'):
            error_msg = f"'heads[{idx}]' = '{head}' does not follow required pattern. Head must start with 'HD'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    def _validate_head_string_in_list(self, head, list_idx, head_idx):
        """Validate a head string within a combined heads list"""
        if not isinstance(head, str):
            error_msg = f"'heads[{list_idx}][{head_idx}]' must be a string, got {type(head).__name__}: {head}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if len(head) == 0:
            error_msg = f"Head name: 'heads[{list_idx}][{head_idx}]' cannot be an empty string"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if len(head) != len(head.strip()):
            error_msg = f"Head name:'{head}' has leading/trailing whitespace"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not head.startswith('HD'):
            error_msg = f"'heads[{list_idx}][{head_idx}]' = '{head}' does not follow pattern. Must start with 'HD'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    def _verify_heads_in_data(self, all_heads, config):
        """Verify that all heads exist in the data directory"""
        if 'data_dir_list' not in config or not config['data_dir_list']:
            return

        available_heads = self.data_analyzer.get_all_available_heads(config['data_dir_list'])
        if not available_heads:
            return

        # Get unique heads from the list
        unique_heads = list(set(all_heads))
        missing_heads = [head for head in unique_heads if head not in available_heads]

        if missing_heads:
            error_msg = (f"Specified heads not found in data_dir_list: {list(set(missing_heads))}. "
                       f"Available heads in data: {available_heads}. "
                       f"Please input head information in config file as per the FRF heads data files")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


class FeatureConfigValidator(object):
    """Loads stage1 (and stage2, if present) features/weightages from feature_config.json
    and derives hierarchical_clustering from their presence"""

    # Keys read directly from feature_config.json
    STAGE1_FEATURE_KEY = 'training_application_stage1_features'
    STAGE1_WEIGHT_KEY = 'training_application_stage1_features_weightages'
    STAGE2_FEATURE_KEY = 'training_application_stage2_features'
    STAGE2_WEIGHT_KEY = 'training_application_stage2_features_weightages'

    ALL_FEATURES = [
        "real", "imaginary", "gain", "phase",
        "mag_gain", "cos_phase", "sin_phase", "unwrapped_phase",
        "slope_mag_gain", "slope_unwrapped_phase", "curvature_gain", "curvature_phase",
        "signed_peak_dev_mag_gain", "signed_peak_dev_unwrapped_phase",
        "moving_magnitude", "moving_unwrapped_phase"
    ]

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def load_features_from_feature_config(self, config):
        """Load stage1 (required) and stage2 (if present) features/weightages from
        feature_config.json into the inference config, and derive hierarchical_clustering
        from whether stage2 keys are present"""
        # Use the resolved path stored by FeatureConfigPathValidator
        feature_config_path = config.get('feature_config_path_resolved')
        if feature_config_path is None:
            # Fallback: resolve from raw path + root_dir
            root_dir = config.get('root_dir', '')
            rel_path = config.get('feature_config_path', '')
            feature_config_path = os.path.join(root_dir, os.path.normpath(rel_path))

        feature_config = self._load_feature_config(feature_config_path)

        stage1_features, stage1_weights = self._extract_stage(
            feature_config, feature_config_path,
            self.STAGE1_FEATURE_KEY, self.STAGE1_WEIGHT_KEY,
            stage_label='stage1', validate_names=True
        )
        config['training_application_stage1_features'] = stage1_features
        config['training_application_stage1_features_weightages'] = stage1_weights

        hierarchical = self._resolve_hierarchical_flag(feature_config, feature_config_path)
        config['hierarchical_clustering'] = hierarchical

        if hierarchical:
            stage2_features, stage2_weights = self._extract_stage(
                feature_config, feature_config_path,
                self.STAGE2_FEATURE_KEY, self.STAGE2_WEIGHT_KEY,
                stage_label='stage2', validate_names=False
            )
            config['training_application_stage2_features'] = stage2_features
            config['training_application_stage2_features_weightages'] = stage2_weights

        self.logger.info(
            f"Loaded features from {feature_config_path} (hierarchical_clustering={hierarchical})"
        )
        return config

    def _resolve_hierarchical_flag(self, feature_config, feature_config_path):
        """hierarchical_clustering is True only when both stage2 keys are present together"""
        has_stage2_features = self.STAGE2_FEATURE_KEY in feature_config
        has_stage2_weights = self.STAGE2_WEIGHT_KEY in feature_config

        if has_stage2_features != has_stage2_weights:
            error_msg = (f"Incomplete stage2 configuration in feature configuration file: "
                         f"{feature_config_path}. Both '{self.STAGE2_FEATURE_KEY}' and "
                         f"'{self.STAGE2_WEIGHT_KEY}' must be present together")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        return has_stage2_features and has_stage2_weights

    def _load_feature_config(self, feature_config_path):
        """Load and return the feature_config.json as a dict"""
        try:
            with open(feature_config_path, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            error_msg = (f"Invalid JSON in feature configuration file: "
                         f"{feature_config_path}. Error: {e}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        except Exception as e:
            error_msg = (f"Error reading feature configuration file: "
                         f"{feature_config_path}. Error: {e}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    def _extract_stage(self, feature_config, feature_config_path,
                        feature_key, weight_key, stage_label, validate_names):
        """Extract, validate, and return one stage's (features, weightages) from feature_config.json"""
        if feature_key not in feature_config:
            error_msg = (f"'{feature_key}' key missing in feature configuration file: "
                         f"{feature_config_path}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if weight_key not in feature_config:
            error_msg = (f"'{weight_key}' key missing in feature configuration file: "
                         f"{feature_config_path}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        features = feature_config[feature_key]
        weights = feature_config[weight_key]

        self._validate_features(features, feature_key, validate_names)
        self._validate_weights(weights, weight_key, len(features))

        self.logger.info(f"  Loaded {stage_label} features: {features} with weightages: {weights}")
        return features, weights

    def _validate_features(self, features, feature_key, validate_names):
        """Validate a stage's feature list read from feature_config.json"""
        if not isinstance(features, list) or not features:
            error_msg = f"'{feature_key}' in feature configuration file must be a non-empty list"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        for i, feature in enumerate(features):
            if not isinstance(feature, str) or not feature.strip():
                error_msg = f"'{feature_key}[{i}]' in feature configuration file must be a non-empty string"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        if len(features) != len(set(features)):
            duplicates = [f for f in features if features.count(f) > 1]
            error_msg = f"Duplicate features found in '{feature_key}': {list(set(duplicates))}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if validate_names:
            invalid_features = [f for f in features if f not in self.ALL_FEATURES]
            if invalid_features:
                error_msg = f"Invalid features in '{feature_key}': {invalid_features}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

    def _validate_weights(self, weights, weight_key, num_features):
        """Validate a stage's weightages list read from feature_config.json"""
        if not isinstance(weights, list) or len(weights) != num_features:
            error_msg = (f"'{weight_key}' in feature configuration file must be a list "
                         f"of length {num_features}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        invalid_idx = next((i for i, w in enumerate(weights)
                            if not isinstance(w, (int, float)) or w <= 0), None)
        if invalid_idx is not None:
            error_msg = (f"'{weight_key}[{invalid_idx}]' = {weights[invalid_idx]!r} is invalid "
                         f"(must be a positive number)")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


class InferenceConfigLoader(object):
    """Main class that orchestrates inference configuration loading and validation"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.structure_validator = ConfigStructureValidator()
        self.root_dir_validator = RootDirValidator()
        self.output_path_validator = OutputDirValidator()
        self.data_dir_validator = DataDirectoryValidator()
        self.freq_segment_validator = FrequencySegmentValidator()
        self.heads_validator = HeadsValidator()
        self.metric_validator = MetricValidator()
        self.trained_models_validator = TrainedModelsPathValidator()
        self.summary_printer = ConfigSummaryPrinter()
        self.feature_config_path_validator = FeatureConfigPathValidator()
        self.feature_config_validator = FeatureConfigValidator()
        self.baseline_params_validator = BaselineParametersValidator()
        self.individual_frequencies_cluster_assignment_plots = IndividualFrequenciesClusterAssignmentPlots()
        self.generate_interactive_html_plots_validator = GenerateInteractiveHtmlPlots()
        self.max_clusters_validator = MaxClustersValidator()

    def extract_output_path(self, config_path):
        """Stage 1: Extract and validate ONLY output_path for logging setup"""
        config_path = os.path.abspath(config_path)

        # Basic checks
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        if not os.path.isfile(config_path):
            raise ConfigValidationError(f"Configuration path is not a file: {config_path}")

        # Parse and validate output_path only
        config = self.structure_validator.validate_config_structure(config_path)
        config = self.output_path_validator.validate_output_path(config)

        return config['output_path']

    def load_config(self, config_path):
        """Load and validate inference configuration file"""
        config_path = os.path.abspath(config_path)

        try:
            self.logger.info("="*80)
            self.logger.info("INFERENCE CONFIGURATION VALIDATION")
            self.logger.info("="*80)
            self.logger.info(f"Loading inference configuration from: {config_path}")

            # 1. Check if file exists
            if not os.path.exists(config_path):
                error_msg = f"Configuration file not found: {config_path}"
                self.logger.error(error_msg)
                raise FileNotFoundError(error_msg)

            if not os.path.isfile(config_path):
                error_msg = f"Configuration path is not a file: {config_path}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            # 2. Validate structure and parse
            config = self.structure_validator.validate_config_structure(config_path)
            self.logger.info("Config Parameters Validation Started")

            # 3. Validate root_dir
            config = self.root_dir_validator.validate_root_dir(config)

            # 4. Validate required parameters
            config = self.data_dir_validator.validate_data_dir_list(config)
            config = self.output_path_validator.validate_output_path(config)

            # 5. Validate frequency segments
            config = self.freq_segment_validator.validate_frequency_segments_inference(config)

            # 6. Validate heads
            config = self.heads_validator.validate_heads(config)

            # 7. Validate metrics
            config = self.metric_validator.validate_metric(config)

            # 8. Validate baseline separation flags
            config = self.baseline_params_validator.validate_baseline_parameters(config)

            # 9. Validate feature_config_path
            config = self.feature_config_path_validator.validate_feature_config_path(config)

            # 10. Load stage1 (and stage2, if present) features/weightages from
            # feature_config.json, deriving hierarchical_clustering from their presence
            config = self.feature_config_validator.load_features_from_feature_config(config)

            # 11. Validate optional plots generation
            config = self.individual_frequencies_cluster_assignment_plots.\
validate_individual_frequencies_cluster_assignment_plots(config)
            config = self.generate_interactive_html_plots_validator.\
validate_generate_interactive_html_plots(config)

            # 12. Validate and build the trained model registry
            config = self.trained_models_validator.validate_and_build_all_models_dict(config)

            # 13. Validate max clusters parameter
            config = self.max_clusters_validator.validate_max_clusters(config)

            # 14. Print summary
            self.summary_printer.print_config_summary(config)

            self.logger.info("Inference configuration validation completed successfully")
            return config

        except Exception as e:
            self.logger.error(f"UNEXPECTED ERROR during config loading: {e}")
            raise ConfigValidationError(f"Unexpected error loading config")
