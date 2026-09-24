# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_config_loader.py
*  File Description: File responsible for validation of the config.cfg, structure and parameters.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import re
import logging
from frf_config_utils import ConfigSummaryPrinter, ConfigValidationError, HeadValidatorHelper
from frf_config_utils import ConfigStructureValidator, DataDirectoryAnalyzer, OptionalParametersValidator
from frf_config_utils import HeadKeywordResolver, KeywordExpandedHeads

class FrequencySegmentValidator(object):
    """Validates frequency segment parameters"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.analyzer = DataDirectoryAnalyzer()
        self.freq_segment_pattern = re.compile(
            r'^\(\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*\)$'
        )

    def validate_frequency_segments_max_clusters(self, config):
        """Validate frequency_segments_max_clusters parameter with detailed error handling"""
        # Check if parameter exists
        if 'frequency_segments_max_clusters' not in config:
            error_msg = "Missing REQUIRED parameter: 'frequency_segments_max_clusters'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        freq_seg_clusters = config['frequency_segments_max_clusters']

        self._validate_parameter_type(freq_seg_clusters)
        self._validate_parameter_not_empty(freq_seg_clusters)

        # Detect min and max frequency from data
        min_freq_from_data, max_freq_from_data = self.analyzer.get_min_max_frequency(config['data_dir_list'])

        # Read hierarchical flag — already validated and present in config at this point
        is_hierarchical = config.get('hierarchical_clustering', False)

        frequency_segments, no_of_clusters_for_each_segment = self._process_all_segments(
            freq_seg_clusters, min_freq_from_data, max_freq_from_data, is_hierarchical
        )

        # Update config
        config['frequency_segments'] = frequency_segments
        config['no_of_clusters_for_each_segment'] = no_of_clusters_for_each_segment

        self.logger.info(f"Successfully validated {len(frequency_segments)} frequency segment(s)")
        return config


    def _validate_parameter_type(self, freq_seg_clusters):
        """Validate that parameter is a dictionary"""
        if not isinstance(freq_seg_clusters, dict):
            error_msg1 = f"'frequency_segments_max_clusters' must be a dictionary object. "
            error_msg2 = f"Got {type(freq_seg_clusters).__name__}"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


    def _validate_parameter_not_empty(self, freq_seg_clusters):
        """Validate that parameter is not empty"""
        if not freq_seg_clusters:
            error_msg = "'frequency_segments_max_clusters' cannot be empty. At least one segment must be specified"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


    def _process_all_segments(self, freq_seg_clusters, min_freq_from_data, max_freq_from_data,
                              is_hierarchical=False):
        """Process and validate all frequency segments"""
        frequency_segments = []
        no_of_clusters_for_each_segment = {}
        segment_keys_seen = set()

        for key, max_k in freq_seg_clusters.items():
            segment_tuple = self._validate_and_parse_segment_key(key, min_freq_from_data, max_freq_from_data)
            self._validate_no_overlap(segment_tuple, segment_keys_seen)

            k_values = self._validate_and_generate_k_values(key, max_k, is_hierarchical)

            frequency_segments.append(segment_tuple)
            no_of_clusters_for_each_segment[segment_tuple] = k_values
            segment_keys_seen.add(segment_tuple)

            if is_hierarchical:
                stage1_k, stage2_k = max_k
                self.logger.info(
                    f"Validated frequency segment '{key}': "
                    f"stage1 k values from 2 to {stage1_k}, stage2 k values from 2 to {stage2_k}"
                )
            else:
                self.logger.info(f"Validated frequency segment '{key}': k values from 2 to {max_k}")

        return frequency_segments, no_of_clusters_for_each_segment


    def _validate_and_parse_segment_key(self, key, min_freq_from_data, max_freq_from_data):
        """Validate segment key format and extract frequency values"""
        # Validate key format
        if not isinstance(key, str):
            error_msg = f"Frequency segment key must be a string, got {type(key).__name__}: {key}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        match = self.freq_segment_pattern.match(key)
        if not match:
            error_msg = (
                f"Invalid frequency segment format: '{key}'. "
                f"Must be in format '(start, end)' e.g., '(25030.1, 26980.1)' "
                f"with valid numeric values (decimals and negative numbers allowed)."
            )
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        start = float(match.group(1))
        end = float(match.group(2))

        self._validate_frequency_range(key, start, end, min_freq_from_data, max_freq_from_data)

        return (start, end)


    def _validate_frequency_range(self, key, start, end, min_freq_from_data, max_freq_from_data):
        """Validate frequency range values"""
        if start >= end:
            error_msg1 = f"Invalid frequency segment '{key}'. "
            error_msg2 = f"Start frequency ({start}) must be less than end frequency ({end})"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if start <= 0 or end <= 0:
            error_msg = f"Invalid frequency segment '{key}': Frequencies must be +ve (start={start}, end={end})"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self._validate_against_data_limits(key, start, end, min_freq_from_data, max_freq_from_data)


    def _validate_against_data_limits(self, key, start, end, min_freq_from_data, max_freq_from_data):
        """Validate segment against data frequency limits"""
        if start > max_freq_from_data:
            error_msg1 = f"Invalid frequency segment '{key}'. "
            error_msg2 = f"Start frequency ({start} Hz) exceeds maximum frequency ({max_freq_from_data:.2f} Hz)"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if end > max_freq_from_data:
            error_msg1 = f"Invalid frequency segment '{key}'. "
            error_msg2 = f"End frequency ({end} Hz) exceeds maximum frequency ({max_freq_from_data:.2f} Hz)"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if start < min_freq_from_data:
            error_msg1 = f"Invalid frequency segment '{key}'. "
            error_msg2 = f"Start frequency ({start} Hz) less than minimum frequency ({min_freq_from_data:.2f} Hz)"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if end < min_freq_from_data:
            error_msg1 = f"Invalid frequency segment '{key}'. "
            error_msg2 = f"End frequency ({end} Hz) less than minimum frequency ({min_freq_from_data:.2f} Hz)"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


    def _validate_no_overlap(self, segment_tuple, segment_keys_seen):
        """Check for overlapping segments"""
        start, end = segment_tuple

        for existing_seg in segment_keys_seen:
            existing_start, existing_end = existing_seg
            if start < existing_end and end > existing_start:
                error_msg = (f"Overlapping frequency segments detected: '{segment_tuple}' overlaps with "
                        f"'({existing_start}, {existing_end})'. Segments must not overlap")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)


    def _validate_and_generate_k_values(self, key, max_k, is_hierarchical=False):
        """Validate max_k and generate k values.

        When is_hierarchical=False: max_k must be a single int >= 2 and <= MAX_CLUSTERS_CAP.
            Returns list(range(2, max_k + 1)).

        When is_hierarchical=True: max_k must be a tuple (stage1_k, stage2_k) where both
            values are ints >= 2 and <= MAX_CLUSTERS_CAP independently.
            Returns (list(range(2, stage1_k + 1)), list(range(2, stage2_k + 1))).
        """
        if is_hierarchical:
            return self._validate_and_generate_hierarchical_k_values(key, max_k)
        return self._validate_and_generate_flat_k_values(key, max_k)

    def _validate_and_generate_flat_k_values(self, key, max_k):
        """Validate and generate k values for non-hierarchical mode (single integer)."""
        if not isinstance(max_k, int):
            error_msg = f"Invalid max_k value for segment '{key}': {max_k}. Must be an integer"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if max_k < 2:
            error_msg = f"Invalid max_k value for segment '{key}': {max_k}. Must be >= 2 (minimum 2 clusters)"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        return list(range(2, max_k + 1))

    def _validate_and_generate_hierarchical_k_values(self, key, max_k):
        """Validate and generate k values for hierarchical mode (tuple of two integers)."""
        if not isinstance(max_k, tuple) or len(max_k) != 2:
            error_msg = (
                f"Invalid max_k value for segment '{key}' when hierarchical_clustering=True: {max_k}. "
                f"Must be a tuple (stage1_k, stage2_k), e.g. (3, 4)"
            )
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        stage1_k, stage2_k = max_k

        for label, val in [('stage1_k', stage1_k), ('stage2_k', stage2_k)]:
            if not isinstance(val, int):
                error_msg = (
                    f"Invalid {label} value for segment '{key}': {val}. Must be an integer"
                )
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            if val < 2:
                error_msg = (
                    f"Invalid {label} value for segment '{key}': {val}. Must be >= 2 (minimum 2 clusters)"
                )
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        return (list(range(2, stage1_k + 1)), list(range(2, stage2_k + 1)))


class DataDirectoryValidator(object):
    """Validates data directory parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_data_dir_list(self, config):
        """Validate data_dir_list parameter"""
        if 'data_dir_list' not in config:
            error_msg = "Missing REQUIRED parameter: 'data_dir_list'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        else:
            data_dir_list = config['data_dir_list']

        if not isinstance(data_dir_list, str):
            error_msg = f"'data_dir_list' must be a string, got {type(data_dir_list).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if len(data_dir_list)==0:
            error_msg = "'data_dir_list' cannot be empty"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not os.path.exists(data_dir_list):
            error_msg = f"'data_dir_list' file does not exist: {data_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not os.path.isfile(data_dir_list):
            error_msg = f"'data_dir_list' must be a file, not a directory: {data_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Check if it's a .txt file
        if not data_dir_list.endswith('.txt'):
            error_msg = f"'data_dir_list' must be a .txt file, got: {data_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Read and validate file list
        try:
            with open(data_dir_list, 'r', encoding='utf-8-sig') as f:
                file_paths = [line.strip() for line in f if line.strip()]
        except Exception as e:
            error_msg = f"Error reading data_dir_list file list: {e}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not file_paths:
            error_msg = f"'data_dir_list' file list is empty: {data_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Validate that files exist and have valid extensions
        VALID_EXTENSIONS = ('.exv', '.xpi', '.xiz')
        valid_files = 0
        for file_path in file_paths:
            if not os.path.exists(file_path):
                self.logger.warning(f"File in list does not exist: {file_path}")
                continue
            if not file_path.endswith(VALID_EXTENSIONS):
                self.logger.warning(f"File in list has invalid extension: {file_path}")
                continue
            valid_files += 1

        if valid_files == 0:
            error_msg = f"'data_dir_list' file list contains no valid data files (.exv, .xpi, .xiz): {data_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self.logger.info(f"Validated data_dir_list: {data_dir_list} ({valid_files} data files)")

    def validate_worst_model_dir_list(self, config):
        """Validate worst_model_dir_list parameter"""
        if 'worst_model_dir_list' not in config:
            self.logger.warning("No worst_model_dir_list specified. Training will proceed without worst model data.")
            config['worst_model_dir_list'] = None
            return

        worst_model_dir_list = config['worst_model_dir_list']

        # If explicitly set to None or empty string, treat as not provided
        if self._is_empty_or_none(worst_model_dir_list):
            self.logger.warning("worst_model_dir_list is empty. Training will proceed without worst model data.")
            config['worst_model_dir_list'] = None
            return

        self._validate_worst_model_file_path(worst_model_dir_list)
        self._validate_worst_model_file_list(worst_model_dir_list)


    @staticmethod
    def _is_empty_or_none(value):
        """Check if value is None or empty string"""
        return value is None or value == ''


    def _validate_worst_model_file_path(self, worst_model_dir_list):
        """Validate worst model file path"""
        if not isinstance(worst_model_dir_list, str):
            error_msg = f"'worst_model_dir_list' must be a string, got {type(worst_model_dir_list).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if len(worst_model_dir_list) == 0:
            error_msg = "'worst_model_dir_list' cannot be empty"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not os.path.exists(worst_model_dir_list):
            error_msg = f"'worst_model_dir_list' file does not exist: {worst_model_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not os.path.isfile(worst_model_dir_list):
            error_msg = f"'worst_model_dir_list' must be a file, not a directory: {worst_model_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not worst_model_dir_list.endswith('.txt'):
            error_msg = f"'worst_model_dir_list' must be a .txt file, got: {worst_model_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


    def _validate_worst_model_file_list(self, worst_model_dir_list):
        """Validate worst model file list contents"""
        try:
            with open(worst_model_dir_list, 'r', encoding='utf-8-sig') as f:
                file_paths = [line.strip() for line in f if line.strip()]
        except Exception as e:
            error_msg = f"Error reading worst_model_dir_list file list: {e}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not file_paths:
            error_msg = f"'worst_model_dir_list' file list is empty: {worst_model_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        valid_files = self._count_valid_files(file_paths)

        if valid_files == 0:
            error_msg = f"'worst_model_dir_list' file list contains no valid data files: {worst_model_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self.logger.info(f"Validated worst_model_dir_list: {worst_model_dir_list} ({valid_files} data files)")


    def _count_valid_files(self, file_paths):
        """Count valid data files in the file list"""
        VALID_EXTENSIONS = ('.exv', '.xpi', '.xiz')
        valid_files = 0

        for file_path in file_paths:
            if not os.path.exists(file_path):
                self.logger.warning(f"File in list does not exist: {file_path}")
                continue
            if not file_path.endswith(VALID_EXTENSIONS):
                self.logger.warning(f"File in list has invalid extension: {file_path}")
                continue
            valid_files += 1

        return valid_files

    def validate_output_path(self, config):
        """Validate output_path parameter"""
        if 'output_path' not in config:
            error_msg = "Missing REQUIRED parameter: 'output_path'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        else:
          output_path = config['output_path']

        # Check if it's a string
        if not isinstance(output_path, str):
            error_msg = f"'output_path' must be a string, got {type(output_path).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Check if parameter is provided
        if not output_path or len(output_path.strip()) == 0:
            error_msg = "'output_path' cannot be empty. A path must be provided"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Strip whitespace
        output_path = os.path.normpath(output_path.strip())
        config['output_path'] = output_path

        # Check if path points to an existing file (should be directory)
        if os.path.exists(output_path) and os.path.isfile(output_path):
            error_msg = f"'output_path' points to a file, must be a directory: {output_path}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Check if directory exists and is writable, or can be created
        if os.path.exists(output_path):
            if not os.access(output_path, os.W_OK):
                error_msg = f"'output_path' directory exists but is not writable: {output_path}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            self.logger.info(f"Validated output_path: {output_path}")
        else:
            # Try to create the directory to verify permissions
            try:
                os.makedirs(output_path, exist_ok=True)
                self.logger.info(f"Validated output_path: {output_path}")
            except Exception as e:
                error_msg = f"Cannot create output_path directory: {output_path}. Error: {str(e)}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        return config


class HeadsValidator(object):
    """Validates heads parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.data_analyzer = DataDirectoryAnalyzer()
        self.head_helper = HeadValidatorHelper()
        self.keyword_resolver = HeadKeywordResolver()

    def validate_heads(self, config):
        """Validate heads parameter"""
        # Check if parameter exists and is not empty
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

        combined_heads = config['combined_heads']

        # Preserve heads exactly as configured
        config['heads_as_configured'] = heads

        # Expand head-selection keywords (e.g. 'even_number_heads') into literal head names
        heads = self._expand_head_keywords(heads, combined_heads, config['data_dir_list'])
        config['heads'] = heads

        if not combined_heads:
            self._validate_simple_heads(heads, config)
        else:
            self._validate_combined_heads(heads, config)

        return config

    def _expand_head_keywords(self, heads, combined_heads, data_dir_list):
        """Expand any head-selection keywords in 'heads' into literal head names.

        - A bare top-level keyword is replaced with individual heads
          (combined_heads=False) or a single combined group (combined_heads=True).
        - A keyword found inside an explicit combo group (a list) is flattened
          into that same group, alongside any literal heads already in it.
        No deduplication is performed - resolved heads are spliced in exactly
        where the keyword was, so the existing validation below (duplicate
        checks, minimum-heads-per-group, etc.) applies unchanged.

        When combined_heads=True, groups built from keyword(s) are wrapped in
        KeywordExpandedHeads so output naming can use the keyword name(s)
        instead of a synthesized head-code name.
        """
        if not self._contains_head_keyword(heads):
            return heads

        available_heads = self.data_analyzer.get_all_available_heads(data_dir_list)

        expanded = []
        for head_spec in heads:
            if isinstance(head_spec, list):
                expanded.append(self._expand_combo_group(head_spec, available_heads))
            elif self.keyword_resolver.is_keyword(head_spec):
                resolved_heads = self.keyword_resolver.resolve_keyword(head_spec, available_heads)
                if combined_heads:
                    expanded.append(KeywordExpandedHeads(resolved_heads, [head_spec]))
                else:
                    expanded.extend(resolved_heads)
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
        """Check whether 'heads' contains a keyword, at the top level or within a combo group"""
        for head_spec in heads:
            if isinstance(head_spec, list):
                if any(self.keyword_resolver.is_keyword(item) for item in head_spec):
                    return True
            elif self.keyword_resolver.is_keyword(head_spec):
                return True
        return False

    def _validate_simple_heads(self, heads, config):
        """Validate heads when combined_heads is False"""
        # All elements must be strings
        for idx, head in enumerate(heads):
            self.head_helper.validate_single_head_name(head, f"heads[{idx}]")

        # Check for duplicates
        if len(heads) != len(set(heads)):
            duplicates = [h for h in heads if heads.count(h) > 1]
            error_msg = f"Duplicate head names found: {list(set(duplicates))}. Please remove the duplicates"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Check heads exist in data
        self._check_heads_exist_in_data(heads, config['data_dir_list'])

        self.logger.info(f"Validated heads: {heads}")

    def _validate_combined_heads(self, heads, config):
        """Validate heads when combined_heads is True"""
        all_individual_heads = []
        seen_combinations = []

        for idx, head_spec in enumerate(heads):
            if isinstance(head_spec, str):
                self._process_single_head(head_spec, idx, all_individual_heads, seen_combinations)
            elif isinstance(head_spec, list):
                self._process_head_list(head_spec, idx, all_individual_heads, seen_combinations)
            else:
                error_msg = f"'heads[{idx}]' must be either a string or a list"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        # Check all heads exist in data directory
        self._check_heads_exist_in_data(all_individual_heads, config['data_dir_list'])

        self.logger.info(f"Validated heads with combined_heads=True: {heads}")

    def _process_single_head(self, head_spec, idx, all_individual_heads, seen_combinations):
        """Process a single head specification"""
        self.head_helper.validate_single_head_name(head_spec, f"heads[{idx}]")
        all_individual_heads.append(head_spec)

        combo_set = frozenset([head_spec])
        if combo_set in seen_combinations:
            error_msg = f"Duplicate head specification found: '{head_spec}' appears multiple times"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        seen_combinations.append(combo_set)

    def _process_head_list(self, head_spec, idx, all_individual_heads, seen_combinations):
        """Process a list of combined heads"""
        if len(head_spec) < 2:
            error_msg = f"'heads[{idx}]' is a list but contains less than 2 heads"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Validate each head in the list
        for individual_head, head in enumerate(head_spec):
            self.head_helper.validate_single_head_name(head, f"heads[{idx}][{individual_head}]")
            all_individual_heads.append(head)

        # Check for duplicates within the sublist
        if len(head_spec) != len(set(head_spec)):
            duplicates = [h for h in head_spec if head_spec.count(h) > 1]
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

    def _check_heads_exist_in_data(self, heads, data_dir_list):
        """Check if all heads exist in the data directory"""
        available_heads = self.data_analyzer.get_all_available_heads(data_dir_list)

        if available_heads:
            unique_heads = list(set(heads))
            missing_heads = [h for h in unique_heads if h not in available_heads]

            if missing_heads:
                error_msg = (f"Specified heads not found in data_dir_list: {missing_heads}. "
                            f"Available heads in data: {available_heads}. "
                            f"Please input head information in config file as per the input FRF heads data files")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)


class MetricValidator(object):
    """Validates metric parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.valid_metrics = ['ACI1', 'ACI2', 'ACI3', 'ACI4', 'Correlation', 'RMSE', 'Wasserstein']

    def validate_metric(self, config):
        """Validate metric parameter"""
        # Check if parameter exists and is not empty
        if 'metric' not in config:
            error_msg1 = "Missing REQUIRED parameter: 'metric'. "
            error_msg2 = "You must specify which metrics to use or any combination"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        else:
            metric = config['metric']

        if not isinstance(metric, list):
            error_msg = f"'metric' must be a list, got {type(metric).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not metric:
            error_msg = "'metric' list cannot be empty. At least one metric must be specified"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        for idx, individual_metric in enumerate(metric):
            if not isinstance(individual_metric, str):
                error_msg1 = f"'metric[{idx}]' must be a string. "
                error_msg2 = f"Got {type(individual_metric).__name__}: {individual_metric}"
                error_msg = error_msg1 + error_msg2
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            if individual_metric not in self.valid_metrics:
                error_msg = f"Invalid metric: '{individual_metric}'. Must be one of {self.valid_metrics}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            if len(individual_metric)!=len(individual_metric.strip()):
                error_msg = f"Metric:'{individual_metric}' has leading/trailing whitespace"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        # Check for duplicates
        if len(metric) != len(set(metric)):
            duplicates = [m for m in metric if metric.count(m) > 1]
            error_msg = f"Duplicate metrics found: {list(set(duplicates))}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self.logger.info(f"Validated metrics: {metric}")
        return config


class BaseLineSeparationValidator(object):
    """Validates baseline trend data separation parameters"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.VALID_GROUPS = {'phase_lead', 'phase_lag', 'no_resonance'}

    def validate_baseline_data_separation(self, config):
        """Validate baseline_data_separation parameter"""
        if 'baseline_data_separation' not in config:
            config['baseline_data_separation'] = False
            self.logger.info("No baseline_data_separation specified. Using default: False")
            return config

        value = config['baseline_data_separation']

        if not isinstance(value, bool):
            error_msg = (f"'baseline_data_separation' must be a boolean (True or False). "
                         f"Got {type(value).__name__}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self.logger.info(f"Validated baseline_data_separation: {value}")
        return config

    def validate_baseline_data_filtering(self, config):
        """Validate baseline_data_filtering parameter"""
        if 'baseline_data_filtering' not in config:
            error_msg = "Missing REQUIRED parameter: 'baseline_data_filtering' when baseline_data_separation = True"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        combination = config['baseline_data_filtering']

        if not isinstance(combination, list) or len(combination) == 0:
            error_msg = "'baseline_data_filtering' must be a non-empty list"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self._validate_not_all_groups_in_single_sublist(combination)

        normalised_combination = []

        for idx, item in enumerate(combination):
            normalised_item = self._process_combination_item(item, idx)
            normalised_combination.append(normalised_item)

        config['baseline_data_filtering'] = normalised_combination
        self.logger.info(f"Validated baseline_data_filtering: {normalised_combination}")
        return config

    def _validate_not_all_groups_in_single_sublist(self, combination):
        """Check for the [[phase_lead, phase_lag, no_resonance]] case - all three in one sublist."""
        if len(combination) != 1 or not isinstance(combination[0], list):
            return
        inner = [s.lower() for s in combination[0] if isinstance(s, str)]
        if set(inner) == self.VALID_GROUPS:
            error_msg = (
                "'baseline_data_filtering' has all three groups in a single sublist "
                "[[phase_lead, phase_lag, no_resonance]]. This defeats the purpose of separation. "
                "Use a flat list [phase_lead, phase_lag, no_resonance] or a valid nested combination."
            )
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    def _process_combination_item(self, item, idx):
        """Process a single item in the combination list."""
        if isinstance(item, str):
            return self._validate_and_normalize_string_item(item, idx)
        if isinstance(item, list):
            return self._validate_and_normalize_sublist(item, idx)
        error_msg = (f"'baseline_data_filtering[{idx}]' must be a string or list. "
                     f"Got {type(item).__name__}")
        self.logger.error(error_msg)
        raise ConfigValidationError(error_msg)

    def _validate_and_normalize_string_item(self, item, idx):
        """Validate and normalize a string item in baseline_data_filtering."""
        normalised = item.strip().lower()
        if normalised not in self.VALID_GROUPS:
            error_msg = (f"'baseline_data_filtering[{idx}]' = '{item}' is not valid. "
                         f"Must be one of: phase_lead, phase_lag, no_resonance (case-insensitive)")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        return normalised

    def _validate_and_normalize_sublist(self, item, idx):
        """Validate and normalize a sublist in baseline_data_filtering."""
        if len(item) < 2:
            error_msg = (f"'baseline_data_filtering[{idx}]' is a sublist but contains "
                         f"fewer than 2 groups. Use a string for a single group.")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        seen_in_sublist = set()
        normalised_sublist = []
        for sub_idx, sub_item in enumerate(item):
            normalised = self._validate_sublist_item(sub_item, idx, sub_idx, seen_in_sublist)
            seen_in_sublist.add(normalised)
            normalised_sublist.append(normalised)
        return normalised_sublist

    def _validate_sublist_item(self, sub_item, idx, sub_idx, seen_in_sublist):
        """Validate and normalize a single item within a sublist."""
        if not isinstance(sub_item, str):
            error_msg = (f"'baseline_data_filtering[{idx}][{sub_idx}]' must be a string. "
                         f"Got {type(sub_item).__name__}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        normalised = sub_item.strip().lower()
        if normalised not in self.VALID_GROUPS:
            error_msg = (f"'baseline_data_filtering[{idx}][{sub_idx}]' = '{sub_item}' "
                         f"is not valid. Must be one of: phase_lead, phase_lag, no_resonance")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        self._check_duplicate_group(normalised, idx, seen_in_sublist)
        return normalised

    def _check_duplicate_group(self, normalised, idx, seen_in_sublist):
        """Check if a group is repeated within the same sublist."""
        if normalised in seen_in_sublist:
            error_msg = (f"Duplicate group '{normalised}' found within the same sublist "
                         f"'baseline_data_filtering[{idx}]'")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)


class ConfigLoader(object):
    """Main class that orchestrates configuration loading and validation"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.structure_validator = ConfigStructureValidator()
        self.data_dir_validator = DataDirectoryValidator()
        self.freq_segment_validator = FrequencySegmentValidator()
        self.heads_validator = HeadsValidator()
        self.metric_validator = MetricValidator()
        self.optional_validator = OptionalParametersValidator()
        self.baseline_validator = BaseLineSeparationValidator()
        self.summary_printer = ConfigSummaryPrinter()
        self.head_helper = HeadValidatorHelper()

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
        config = self.data_dir_validator.validate_output_path(config)

        return config['output_path']

    def load_config(self, config_path):
        """Load and validate configuration file with comprehensive error handling"""
        config_path = os.path.abspath(config_path)

        try:
            self.logger.info("="*80)
            self.logger.info("CONFIGURATION VALIDATION")
            self.logger.info("="*80)
            self.logger.info(f"Loading configuration from: {config_path}")

            # 1. Check if file exists
            if not os.path.exists(config_path):
                error_msg = f"Configuration file not found: {config_path}"
                self.logger.error(error_msg)
                raise FileNotFoundError(error_msg)

            if not os.path.isfile(config_path):
                error_msg = f"Configuration path is not a file: {config_path}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            # 2. Validate structure
            config = self.structure_validator.validate_config_structure(config_path)
            self.logger.info("Config Parameters Validation Started ...")

            # 3. Validate required parameter: data_dir_list (must be validated first)
            config = self.data_dir_validator.validate_output_path(config)
            self.data_dir_validator.validate_data_dir_list(config)
            self.data_dir_validator.validate_worst_model_dir_list(config)

            # 4. Validate hierarchical_clustering FIRST so segment validator knows the mode
            config = self.optional_validator.validate_hierarchical_clustering(config)

            # 5. Validate and parse frequency_segments_max_clusters (uses hierarchical flag)
            config = self.freq_segment_validator.validate_frequency_segments_max_clusters(config)

            config = self.head_helper.validate_combined_heads(config)
            config = self.heads_validator.validate_heads(config)
            config = self.metric_validator.validate_metric(config)

            # 6. Validate remaining optional parameters
            config = self.optional_validator.validate_training_validation_split(config)
            config = self.optional_validator.validate_individual_frequencies_cluster_assignment_plots(config)
            config = self.optional_validator.validate_generate_interactive_html_plots(config)

            # 7. Validate baseline separation parameters
            config = self.baseline_validator.validate_baseline_data_separation(config)
            if config['baseline_data_separation']:
                config = self.baseline_validator.validate_baseline_data_filtering(config)
            else:
                config['baseline_data_filtering'] = None

            # 8. Print summary
            self.summary_printer.print_config_summary(config)

            self.logger.info("Configuration validation completed successfully")
            return config

        except Exception as e:
            self.logger.error(f"UNEXPECTED ERROR during config loading: {e}")
            raise ConfigValidationError(str(e)) from e
