# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_config_utils.py
*  File Description: Utility file for training application configuration file.
*  All rights reserved.
*
*********************************************************************/
"""
import os
import re
import logging
import configparser
import ast
import pandas as pd
from io import StringIO


class ConfigValidationError(Exception):
    """Custom exception for configuration validation errors"""
    pass


class DataDirectoryAnalyzer(object):
    """Analyzes data directory to detect heads and frequency ranges"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def get_all_available_heads(self, file_list_path):
        """Automatically detect all available heads from file list"""
        try:
            with open(file_list_path, 'r', encoding='utf-8-sig') as f:
                file_paths = [line.strip() for line in f if line.strip()]
        except Exception as e:
            error_msg = f"Error reading file list: {e}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        heads = set()

        for file_path in file_paths:
            filename = os.path.basename(file_path)
            # Format: P0U62150009661_HD0_CYL0007BD37_T001F_0002.exv
            # Look for pattern: _{head_name}_
            parts = filename.split('_')
            if len(parts) > 1:
                heads.add(parts[1])

        return sorted(list(heads))

    def get_min_max_frequency(self, file_list_path):
        """Detect maximum frequency from any EXV file in the file list"""
        try:
            with open(file_list_path, 'r', encoding='utf-8-sig') as f:
                file_paths = [line.strip() for line in f if line.strip()]
        except Exception as e:
            error_msg = f"Error reading file list: {e}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        sample_file = file_paths[0]

        try:
            self.logger.info(f"Detecting min and max frequency from sample file: {os.path.basename(sample_file)}")

            # Read file until "END" string is encountered
            with open(sample_file, 'r', encoding='utf-8-sig') as f:
                lines = []
                for line in f:
                    if line.strip() == "END":
                        break
                    lines.append(line)

            # Convert lines to dataframe
            df = pd.read_csv(
                StringIO(''.join(lines)),
                skiprows=9,
                header=None,
                names=['frequency', 'gain', 'phase'],
                encoding='utf-8-sig'
            )

            # Convert to numeric
            df = df.apply(pd.to_numeric, errors='coerce')
            df.dropna(subset=['frequency'], inplace=True)

            if df.isnull().any().any():
                nan_count = df.isnull().sum().sum()
                error_msg = f"Corrupted file: {sample_file} contains {nan_count} NaN values after numeric conversion"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            if len(df) == 0:
                error_msg = f"No valid frequency data in sample file: {os.path.basename(sample_file)}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            min_freq = df['frequency'].min()
            max_freq = df['frequency'].max()
            self.logger.info(f"Detected minimum frequency: {min_freq:.2f} Hz")
            self.logger.info(f"Detected maximum frequency: {max_freq:.2f} Hz")

            return min_freq, max_freq

        except Exception as e:
            error_msg = f"Could not detect minimum and maximum frequency from {os.path.basename(sample_file)}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


class ConfigFileParser(object):
    """Parses configuration files using ConfigParser + ast.literal_eval()"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _quote_bare_head_keywords(value):
        """Quote any unquoted head-selection keyword in a 'heads' raw value so it
        parses as a valid Python string literal, e.g. [inner_heads, "HD0"] becomes
        ["inner_heads", "HD0"]. Already-quoted keywords are left untouched."""
        quoted_value = value
        for keyword in HeadKeywordResolver.KEYWORDS:
            pattern = r'(?<!["\'\w])' + re.escape(keyword) + r'(?!["\'\w])'
            quoted_value = re.sub(pattern, f'"{keyword}"', quoted_value)
        return quoted_value

    def parse_cfg_file(self, config_path):
        """Parse .cfg file using ConfigParser and convert values to Python types"""
        try:
            # Create ConfigParser with options for your use case
            cfg = configparser.ConfigParser(
                # Support inline comments
                inline_comment_prefixes=('#',),
                # Support full-line comments
                comment_prefixes=('#',),
                # All keys must have values
                allow_no_value=False
            )

            # Preserve case sensitivity for keys
            cfg.optionxform = str

            # Read the config file
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                cfg.read_file(f)

            config = {}

            # Parse all sections and flatten into single dictionary
            for section in cfg.sections():
                for key, value in cfg.items(section):
                    value = value.strip()

                    # Allow keywords in 'heads' to be given quoted or bare
                    # (e.g. [inner_heads, "HD0"] or ["inner_heads", "HD0"])
                    if key == 'heads':
                        value = self._quote_bare_head_keywords(value)

                    # Convert value to appropriate Python type
                    try:
                        # Try to evaluate as Python literal
                        parsed_value = ast.literal_eval(value)
                        config[key] = parsed_value
                        self.logger.debug(f"Parsed {key} = {parsed_value} (type: {type(parsed_value).__name__})")
                    except (ValueError, SyntaxError):
                        # Fall back to string (for paths, simple strings)
                        config[key] = value
                        self.logger.debug(f"Parsed {key} = {value} (type: str)")

            return config
        except Exception as e:
            error_msg = f"Unexpected error parsing config file: {e}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


class ConfigStructureValidator(object):
    """Validates the basic structure of config files"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.parser = ConfigFileParser()

    def validate_config_structure(self, config_path):
        """Validate that the file is proper CFG format and can be loaded"""
        # Accept .cfg extensions
        file_ext = os.path.splitext(config_path)[1].lower()
        if file_ext not in ['.cfg']:
            error_msg = f"Config file has extension '{file_ext}'. Expected .cfg"
            self.logger.warning(error_msg)
            raise FileNotFoundError(error_msg)

        self.logger.info(f"Config extension is valid (file extension: {file_ext})")

        # Parse the .cfg file
        config = self.parser.parse_cfg_file(config_path)
        self.logger.info(f"Config structure validated")

        return config


class HeadValidatorHelper(object):
    """Helper class for the validation of heads"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_single_head_name(self, head, position_str):
        """Validate a single head name with consistent rules"""

        if not isinstance(head, str):
            error_msg = f"'{position_str}' must be a string, got {type(head).__name__}: {head}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if len(head) == 0:
            error_msg = f"Head name: '{position_str}' cannot be an empty string"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if len(head) != len(head.strip()):
            error_msg = f"Head name:'{head}' has leading/trailing whitespace (spaces, tabs, or newlines)"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not head.startswith('HD'):
            error_msg = f"'{position_str}'='{head}' does not follow required pattern. Head names must start with 'HD'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    def validate_combined_heads(self, config):
        """Validate combined_heads parameter"""
        if 'combined_heads' not in config:
            config['combined_heads'] = False
            self.logger.info("No combined_heads specified. Using default: False")
            return config
        else:
            combined_heads = config['combined_heads']

        if not isinstance(combined_heads, bool):
            error_msg1 = f"'combined_heads' must be a boolean (True or False). "
            error_msg2 = f"Got {type(combined_heads).__name__}"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self.logger.info(f"Validated combined_heads: {combined_heads}")
        return config


class HeadKeywordResolver(object):
    """Resolves head-selection keywords (all_heads, odd_number_heads, etc.) into
    concrete head names based on the heads available in the data directory.

    Keyword resolution only ever returns literal head names (e.g. 'HD0', 'HD1').
    No merging, deduplication, or new validation is performed here - resolved
    heads are spliced into the 'heads' config value in place of the keyword,
    and validated by the existing (unmodified) heads-validation logic, so any
    resulting duplicates or invalid combinations are caught exactly as if the
    user had typed the heads manually.
    """

    KEYWORDS = (
        'all_heads', 'odd_number_heads', 'even_number_heads',
        'outer_heads', 'inner_heads'
    )

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def is_keyword(self, value):
        """Check whether a value is a recognized head-selection keyword"""
        return isinstance(value, str) and value in self.KEYWORDS

    def resolve_keyword(self, keyword, available_heads):
        """Resolve a keyword into a sorted list of concrete head names.

        HD0 is treated as an even head (decimal value 0) and is always one of
        the two 'outer_heads'.
        """
        if not available_heads:
            error_msg = f"Cannot resolve keyword '{keyword}': no heads found in data_dir_list"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if keyword == 'all_heads':
            resolved = list(available_heads)
        elif keyword == 'odd_number_heads':
            resolved = [h for h in available_heads if self._head_to_decimal(h) % 2 == 1]
        elif keyword == 'even_number_heads':
            resolved = [h for h in available_heads if self._head_to_decimal(h) % 2 == 0]
        elif keyword == 'outer_heads':
            resolved = self._get_outer_heads(available_heads)
        else:
            resolved = self._get_inner_heads(available_heads)

        if not resolved:
            error_msg = f"Keyword '{keyword}' resolved to zero heads from available heads: {available_heads}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        resolved = sorted(resolved, key=self._head_to_decimal)
        self.logger.info(f"Resolved keyword '{keyword}' to heads: {resolved}")
        return resolved

    @staticmethod
    def _head_to_decimal(head):
        """Convert HD<hex> style head name to its decimal value"""
        return int(head[2:], 16)

    def _get_outer_heads(self, available_heads):
        """HD0 plus the head with the largest decimal value are the outer heads"""
        if 'HD0' not in available_heads:
            error_msg = "Cannot resolve 'outer_heads': 'HD0' not found in available heads"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        max_head = max(available_heads, key=self._head_to_decimal)
        return list({'HD0', max_head})

    def _get_inner_heads(self, available_heads):
        """All heads other than the outer heads"""
        outer = self._get_outer_heads(available_heads)
        return [h for h in available_heads if h not in outer]


class KeywordExpandedHeads(list):
    """A list of head names produced by expanding one or more head-selection
    keywords. Behaves exactly like a plain list (so every existing isinstance
    check, validation, and iteration works unchanged) while additionally
    remembering which keyword(s) - and which manually-typed heads, if any -
    it was built from, so output naming can use the keyword name(s) instead
    of a synthesized head-code name.
    """

    def __init__(self, heads, keywords, literal_heads=None):
        super().__init__(heads)
        self.keywords = list(keywords)
        self.literal_heads = list(literal_heads) if literal_heads else []


class ConfigSummaryPrinter(object):
    """Prints configuration summary"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def print_config_summary(self, config):
        """Print a formatted summary of the validated configuration"""
        summary = "\n" + "="*80 + "\n"
        summary += "CONFIGURATION SUMMARY\n"
        summary += "="*80 + "\n"
        summary += f"Output Path : {config.get('output_path', 'N/A')}\n"
        summary += f"Data Directory File List : {config.get('data_dir_list', 'N/A')}\n"
        worst_model_status = config.get('worst_model_dir_list', None)
        if worst_model_status is None:
            summary += f"Worst Model Directory File List : Not Provided\n"
        else:
            summary += f"Worst Model Directory File List : {worst_model_status}\n"
        summary += f"Heads : {config.get('heads', [])}\n"
        summary += f"Metrics : {config.get('metric', [])}\n"
        summary += f"Training/Validation Split : {config.get('training_validation_split', [])}\n"
        summary += f"Individual Frequencies Cluster Assignment Plots : \
{config.get('individual_frequencies_cluster_assignment_plots', False)}\n"
        summary += f"Generate Interactive HTML Plots : \
{config.get('generate_interactive_html_plots', True)}\n"

        # Hierarchical clustering summary
        hierarchical = config.get('hierarchical_clustering', False)
        summary += f"Hierarchical Clustering : {hierarchical}\n"
        summary += f"  Stage 1 Features : {config.get('training_application_stage1_features', [])}\n"
        summary += f"  Stage 1 Weightages : {config.get('training_application_stage1_features_weightages', [])}\n"
        if hierarchical:
            summary += f"  Stage 2 Features : {config.get('training_application_stage2_features', [])}\n"
            summary += f"  Stage 2 Weightages : {config.get('training_application_stage2_features_weightages', [])}\n"

        summary += f"\nFrequency Segments:\n"

        if 'frequency_segments_max_clusters' in config:
            hierarchical = config.get('hierarchical_clustering', False)
            for seg, max_k in config['frequency_segments_max_clusters'].items():
                if hierarchical and isinstance(max_k, tuple) and len(max_k) == 2:
                    summary += f"  {seg}: stage1_max_k = {max_k[0]}, stage2_max_k = {max_k[1]}\n"
                else:
                    summary += f"  {seg}: max_k = {max_k}\n"

        summary += f"\nBaseline Trend Data Separation:\n"
        baseline_separation = config.get('baseline_data_separation', False)
        summary += f"  Baseline Data Separation : {baseline_separation}\n"
        if baseline_separation:
            summary += f"  Baseline Data Combination : {config.get('baseline_data_filtering', 'N/A')}\n"

        summary += "="*80

        self.logger.info(summary)


class OptionalParametersValidator(object):
    """Validates optional parameters with defaults"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.SPLIT_DEFAULT_VALUE = [80, 20]
        self.PLOTS_DEFAULT_VALUE = False
        self.HTML_PLOTS_DEFAULT_VALUE = True
        self.ALL_FEATURES = [
            "real", "imaginary", "gain", "phase",
            "mag_gain", "cos_phase", "sin_phase", "unwrapped_phase",
            "slope_mag_gain", "slope_unwrapped_phase", "curvature_gain", "curvature_phase",
            "signed_peak_dev_mag_gain", "signed_peak_dev_unwrapped_phase",
            "moving_magnitude", "moving_unwrapped_phase"
        ]

    def validate_training_validation_split(self, config):
        """Validate training_validation_split parameter"""

        if 'training_validation_split' not in config:
            config['training_validation_split'] = self.SPLIT_DEFAULT_VALUE
            self.logger.warning("No training_validation_split specified. Using default: [80, 20]")
            return config
        else:
            training_split = config['training_validation_split']

        # Validate type
        if not isinstance(training_split, list):
            warning_msg1 = f"'training_validation_split' must be a list. "
            warning_msg2 = f"Got {type(training_split).__name__}. Using default: {self.SPLIT_DEFAULT_VALUE}"
            warning_msg = warning_msg1 + warning_msg2
            self.logger.warning(warning_msg)
            config['training_validation_split'] = self.SPLIT_DEFAULT_VALUE
            training_split = config['training_validation_split']

        # Validate length
        if len(training_split) != 2:
            warning_msg1 = f"'training_validation_split' must contain exactly 2 values [train%, validation%]"
            warning_msg2 = f"Got {len(training_split)} values. Using default: {self.SPLIT_DEFAULT_VALUE}"
            warning_msg = warning_msg1 + warning_msg2
            self.logger.warning(warning_msg)
            config['training_validation_split'] = self.SPLIT_DEFAULT_VALUE
            training_split = config['training_validation_split']

        # Validate element types and ranges
        for i, val in enumerate(training_split):
            if not isinstance(val, int):
                warning_msg1 = f"'training_validation_split[{i}]' must be integer"
                warning_msg2 = f"Got {type(val).__name__}: {val}. Using default: {self.SPLIT_DEFAULT_VALUE}"
                warning_msg = warning_msg1 + warning_msg2
                self.logger.warning(warning_msg)
                config['training_validation_split'] = self.SPLIT_DEFAULT_VALUE
                training_split = config['training_validation_split']
                break

            if val < 0 or val > 100:
                warning_msg1 = f"'training_validation_split[{i}]' = {val} is out of valid range [0, 100]"
                warning_msg2 = f"Using default: {self.SPLIT_DEFAULT_VALUE}"
                warning_msg = warning_msg1 + warning_msg2
                self.logger.warning(warning_msg)
                config['training_validation_split'] = self.SPLIT_DEFAULT_VALUE
                training_split = config['training_validation_split']
                break

        # Validate sum
        total = sum(training_split)
        if total != 100:
            warning_msg1 = f"'training_validation_split' values must sum to 100, got {total} (values: {training_split})"
            warning_msg2 = f"Using default: {self.SPLIT_DEFAULT_VALUE}"
            warning_msg = warning_msg1 + warning_msg2
            self.logger.warning(warning_msg)
            config['training_validation_split'] = self.SPLIT_DEFAULT_VALUE
            training_split = config['training_validation_split']

        # Check that training % is greater than validation %
        if training_split[0] <= training_split[1]:
            warning_msg1 = f"Training % ({training_split[0]}%) must be greater than validation % ({training_split[1]}%)"
            warning_msg2 = f"Using default: {self.SPLIT_DEFAULT_VALUE}"
            warning_msg = warning_msg1 + warning_msg2
            self.logger.warning(warning_msg)
            config['training_validation_split'] = self.SPLIT_DEFAULT_VALUE
            training_split = config['training_validation_split']

        if training_split[1] == 0:
            self.logger.info(f"Validated training_validation_split: {training_split}")
            self.logger.info("NOTE: Validation split is 0%. All data will be used for training only.")
            self.logger.info("      No validation processing will be performed.")
        else:
            self.logger.info(f"Validated training_validation_split: {training_split}")

        return config

    @staticmethod
    def _is_all_features_requested(features):
        """Check if 'all' shorthand is used

        Returns:
            True: features is the string "all" (case-insensitive)
            False: features is a string but not "all"
            None: features is not a string (needs list validation)
        """
        if isinstance(features, str):
            if features.lower() == "all":
                return True
            else:
                return False
        return None

    @staticmethod
    def _all_elements_are_strings(features):
        """Check if all elements in features list are strings"""
        for idx, feature in enumerate(features):
            if not isinstance(feature, str):
                return False

            if len(feature) != len(feature.strip()):
                return False

        return True

    def _all_features_valid(self, features):
        """Check if all features are valid"""
        invalid_features = [feature for feature in features if feature not in self.ALL_FEATURES]
        if invalid_features:
            return False
        return True

    @staticmethod
    def _no_duplicates(features):
        """Check for duplicate features"""
        if len(features) != len(set(features)):
            return False
        return True

    def validate_individual_frequencies_cluster_assignment_plots(self, config):
        """Validate individual_frequencies_cluster_assignment_plots parameter"""

        if 'individual_frequencies_cluster_assignment_plots' not in config:
            config['individual_frequencies_cluster_assignment_plots'] = self.PLOTS_DEFAULT_VALUE
            self.logger.info(f"No individual_frequencies_cluster_assignment_plots specified")
            self.logger.info(f"Using default: {self.PLOTS_DEFAULT_VALUE}")
            return config
        else:
            plot_setting = config['individual_frequencies_cluster_assignment_plots']

        if not isinstance(plot_setting, bool):
            warning_msg1 = f"'individual_frequencies_cluster_assignment_plots' must be a boolean (True or False). "
            warning_msg2 = f"Got {type(plot_setting).__name__}. Using default: {self.PLOTS_DEFAULT_VALUE}"
            warning_msg = warning_msg1 + warning_msg2
            self.logger.warning(warning_msg)
            config['individual_frequencies_cluster_assignment_plots'] = self.PLOTS_DEFAULT_VALUE
            return config

        self.logger.info(f"Validated individual_frequencies_cluster_assignment_plots: {plot_setting}")
        return config

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
            warning_msg1 = f"'generate_interactive_html_plots' must be a boolean (True or False). "
            warning_msg2 = f"Got {type(html_plot_setting).__name__}. Using default: {self.HTML_PLOTS_DEFAULT_VALUE}"
            warning_msg = warning_msg1 + warning_msg2
            self.logger.warning(warning_msg)
            config['generate_interactive_html_plots'] = self.HTML_PLOTS_DEFAULT_VALUE
            return config

        self.logger.info(f"Validated generate_interactive_html_plots: {html_plot_setting}")
        return config

    def validate_hierarchical_clustering(self, config):
        """Validate hierarchical_clustering flag and all stage feature parameters"""

        # hierarchical_clustering is now a mandatory parameter — hard fail if missing
        if 'hierarchical_clustering' not in config:
            error_msg = "Missing REQUIRED parameter: 'hierarchical_clustering'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        hierarchical = config['hierarchical_clustering']

        if not isinstance(hierarchical, bool):
            error_msg = (f"'hierarchical_clustering' must be a boolean (True or False). "
                         f"Got {type(hierarchical).__name__}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Stage 1 parameters are always required regardless of hierarchical flag
        for param in ['training_application_stage1_features',
                      'training_application_stage1_features_weightages']:
            if param not in config:
                error_msg = f"Missing REQUIRED parameter: '{param}'"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        # Validate stage1 features
        config = self._validate_stage_features(config, 'training_application_stage1_features')

        # Validate stage1 weightages
        config = self._validate_stage_weightages(
            config, 'training_application_stage1_features_weightages',
            len(config['training_application_stage1_features']), 'Stage 1'
        )

        if not hierarchical:
            # Stage 2 params are not used — set to None
            config['training_application_stage2_features'] = None
            config['training_application_stage2_features_weightages'] = None
            self.logger.info("Validated hierarchical_clustering: False")
            self.logger.info(f"  Stage 1 features: {config['training_application_stage1_features']}")
            self.logger.info(f"  Stage 1 weightages: {config['training_application_stage1_features_weightages']}")
            return config

        # hierarchical=True: stage 2 parameters are also required
        for param in ['training_application_stage2_features',
                      'training_application_stage2_features_weightages']:
            if param not in config:
                error_msg = (f"Missing REQUIRED parameter: '{param}'. "
                             f"Stage 2 parameters are required when hierarchical_clustering=True")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        # Validate stage2 features
        config = self._validate_stage_features(config, 'training_application_stage2_features')

        # Validate stage2 weightages
        config = self._validate_stage_weightages(
            config, 'training_application_stage2_features_weightages',
            len(config['training_application_stage2_features']), 'Stage 2'
        )

        self.logger.info(f"Validated hierarchical_clustering: True")
        self.logger.info(f"  Stage 1 features: {config['training_application_stage1_features']}")
        self.logger.info(f"  Stage 1 weightages: {config['training_application_stage1_features_weightages']}")
        self.logger.info(f"  Stage 2 features: {config['training_application_stage2_features']}")
        self.logger.info(f"  Stage 2 weightages: {config['training_application_stage2_features_weightages']}")
        return config

    def _validate_stage_features(self, config, param_key):
        """Validate stage features list for hierarchical clustering"""
        features = config[param_key]

        # Handle 'all' shorthand
        all_check = self._is_all_features_requested(features)
        if all_check is True:
            config[param_key] = self.ALL_FEATURES
            return config
        elif all_check is False:
            error_msg = (f"'{param_key}' as string must be 'all'. "
                         f"Got '{features}'")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Must be a non-empty list
        if not isinstance(features, list) or not features:
            error_msg = (f"'{param_key}' must be a non-empty list or 'all'. "
                         f"Got {type(features).__name__}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # All elements must be valid feature strings
        if not self._all_elements_are_strings(features):
            error_msg = f"'{param_key}' contains non-string or whitespace-padded feature names"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not self._all_features_valid(features):
            invalid = [f for f in features if f not in self.ALL_FEATURES]
            error_msg = (f"'{param_key}' contains invalid features: {invalid}. "
                         f"Valid features: {self.ALL_FEATURES}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not self._no_duplicates(features):
            duplicates = [f for f in features if features.count(f) > 1]
            error_msg = f"'{param_key}' contains duplicate features: {list(set(duplicates))}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        return config

    def _validate_stage_weightages(self, config, param_key, num_features, stage_label):
        """Validate stage feature weightages for hierarchical clustering"""
        weights = config[param_key]

        if not isinstance(weights, list):
            error_msg = f"'{param_key}' must be a list. Got {type(weights).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # If empty list, default to all 1.0
        if len(weights) == 0:
            self.logger.info(f"Empty '{param_key}' provided. Using default: all weights = 1.0")
            config[param_key] = [1.0] * num_features
            return config

        if len(weights) != num_features:
            error_msg = (f"'{param_key}' length ({len(weights)}) does not match "
                         f"number of {stage_label} features ({num_features})")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        for i, weight in enumerate(weights):
            if not isinstance(weight, (int, float)):
                error_msg = f"'{param_key}[{i}]' must be numeric. Got {type(weight).__name__}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            if weight <= 0:
                error_msg = f"'{param_key}[{i}]' = {weight} must be positive (>0)"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        return config
