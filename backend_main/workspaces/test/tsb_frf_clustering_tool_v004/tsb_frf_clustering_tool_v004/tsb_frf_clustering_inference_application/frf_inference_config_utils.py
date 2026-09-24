# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_config_utils.py
*  File Description: Utility file for inference configuration loader
*  All rights reserved.
*
*********************************************************************/
"""

import os
import re
import ast
import logging
import configparser
import pandas as pd
from io import StringIO
import json


def transform_head_code(head):
    """Transform head name: HD0->00, HD15->15, HDA->0A"""
    code = head[2:]
    if len(code) == 1:
        return '0' + code
    else:
        return code


class ConfigValidationError(Exception):
    """Custom exception for configuration validation errors"""
    pass


class DataValidationError(Exception):
    """Custom exception for data validation errors"""
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
            self.logger.error(f"Error reading file list: {e}")
            return []

        heads = set()

        for file_path in file_paths:
            filename = os.path.basename(file_path)
            # Format: P0U62150009661_HD0_CYL0007BD37_T001F_0002.exv
            # Look for pattern: _{head_name}_
            parts = filename.split('_')
            if len(parts) > 1:
                heads.add(parts[1])

        return sorted(list(heads))

    def get_min_max_frequency_from_data(self, file_list_path):
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


class ConfigFileParser(object):
    """Parses configuration files with multiline Python literals safely"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _is_section_header(line):
        """Check if a line is an INI section header like [SECTION_NAME]"""
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']') and len(stripped) > 2:
            section_name = stripped[1:-1].strip()
            # Section headers contain only alphanumeric, underscores, spaces
            # and do not start with quotes (to distinguish from list items)
            if section_name and not section_name.startswith(('"', "'")):
                return all(c.isalnum() or c in ('_', ' ', '-') for c in section_name)
        return False

    @staticmethod
    def _preprocess_cfg(raw_text: str) -> str:
        """
        Makes the cfg INI-safe:
        - Ensures multiline literals are treated as continuations
        - Removes inline comments after lists/dicts
        - Preserves INI section headers (e.g., [SECTION_NAME])
        """
        processed_lines = []
        for line in raw_text.splitlines():
            stripped = line.rstrip()

            # Remove inline comments safely
            if '#' in stripped:
                stripped = stripped.split('#', 1)[0].rstrip()

            # Empty line
            if not stripped:
                processed_lines.append("")
                continue

            # Preserve INI section headers as-is (do not treat as continuation)
            if ConfigFileParser._is_section_header(stripped):
                processed_lines.append(stripped)
            # Continuation lines (dict/list bodies)
            elif stripped.startswith(("{", "}", "[", "]")):
                processed_lines.append(" " + stripped)
            else:
                processed_lines.append(stripped)

        return "\n".join(processed_lines)

    def parse_cfg_file(self, config_path):
        try:
            with open(config_path, "r", encoding="utf-8-sig") as f:
                raw_text = f.read()

            safe_text = self._preprocess_cfg(raw_text)

            cfg = configparser.ConfigParser(
                allow_no_value=False,
                strict=False,
                inline_comment_prefixes=None,
                comment_prefixes=('#',)
            )

            cfg.optionxform = str
            cfg.read_file(StringIO(safe_text))

            config = {}

            for section in cfg.sections():
                for key, value in cfg.items(section):
                    parsed_value = self._parse_config_value(key, value)
                    config[key] = parsed_value

            return config

        except Exception as e:
            msg = f"Unexpected error parsing config file: {e}"
            self.logger.error(msg)
            raise ConfigValidationError(msg)

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

    def _parse_config_value(self, key, value):
        """Parse a single configuration value"""
        value = value.strip()

        # Remove swallowed section headers (with or without leading space)
        for separator in ["\n[", "\n ["]:
            if separator in value:
                value = value.split(separator, 1)[0].strip()

        # Skip empty values
        if not value:
            self.logger.debug(f"Parsed {key} = '' (empty string)")
            return value

        # Allow head-selection keywords in 'heads' to be given quoted or bare
        # (e.g. [inner_heads, "HD0"] or ["inner_heads", "HD0"])
        if key == 'heads':
            value = self._quote_bare_head_keywords(value)

        # Try parsing with different methods
        parsed_value = self._try_parse_value(value)

        # Log the result
        if isinstance(parsed_value, str):
            self.logger.debug(f"Parsed {key} = {parsed_value} (type: str)")
        else:
            self.logger.debug(f"Parsed {key} = {parsed_value} ({type(parsed_value).__name__})")

        return parsed_value

    @staticmethod
    def _try_parse_value(value):
        """Try to parse value using literal_eval, JSON, or return as string

        Returns:
            Parsed value (could be dict, list, number, or string)
        """
        # Try literal_eval first
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            pass

        # Try JSON parsing
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

        # Fall back to string
        return value


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


class ConfigSummaryPrinter(object):
    """Prints configuration summary"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def print_config_summary(self, config):
        """Print a formatted summary of the validated configuration"""
        summary = self._build_summary_header()
        summary += self._build_basic_config_section(config)
        summary += self._build_heads_section(config)
        summary += "="*80

        self.logger.info(summary)

    @staticmethod
    def _build_summary_header():
        """Build summary header"""
        header = "\n" + "="*80 + "\n"
        header += "INFERENCE CONFIGURATION SUMMARY\n"
        header += "="*80 + "\n"
        return header

    @staticmethod
    def _build_basic_config_section(config):
        """Build basic configuration section"""
        section = ""
        section += f"Data Directory File List: {config.get('data_dir_list', 'N/A')}\n"
        section += f"Frequency Segments for Inference: {config.get('frequency_segments_inference', [])}\n"
        section += f"Metrics: {config.get('metric', [])}\n"
        section += f"Hierarchical Clustering: {config.get('hierarchical_clustering', False)}\n"
        section += f"Baseline Data Separation: {config.get('baseline_data_separation', False)}\n"
        section += (f"Stage 1 Features: "
                    f"{config.get('training_application_stage1_features', ['real', 'imaginary'])}\n")
        section += (f"Stage 1 Feature Weightages: "
                    f"{config.get('training_application_stage1_features_weightages', [1.0])}\n")
        if config.get('hierarchical_clustering', False):
            section += f"Stage 2 Features: {config.get('training_application_stage2_features', [])}\n"
            section += (f"Stage 2 Feature Weightages: "
                        f"{config.get('training_application_stage2_features_weightages', [])}\n")
        if config.get('baseline_data_separation', False):
            section += f"Baseline Data Filtering: {config.get('baseline_data_filtering', 'N/A')}\n"
        section += (f"Individual Frequencies Cluster Assignment Plots: "
                    f"{config.get('individual_frequencies_cluster_assignment_plots', False)}\n")
        section += (f"Generate Interactive HTML Plots: "
                    f"{config.get('generate_interactive_html_plots', True)}\n")
        return section

    def _build_heads_section(self, config):
        """Build heads configuration section"""
        section = ""
        heads_list = config.get('heads', [])
        combined_heads = config.get('combined_heads', False)

        section += f"Heads: {heads_list}\n"
        section += f"Combined Heads Mode: {combined_heads}\n"

        if combined_heads:
            section += self._build_transformed_heads_display(heads_list)

        return section

    @staticmethod
    def _build_transformed_heads_display(heads_list):
        """Build display of transformed head names for combined heads"""
        transformed_heads = []

        for head_spec in heads_list:
            if isinstance(head_spec, str):
                transformed_heads.append(head_spec)
            elif isinstance(head_spec, list):
                head_name = ConfigSummaryPrinter._build_combined_head_name(head_spec)
                transformed_heads.append(f"{head_name} (from {head_spec})")

        return f"Heads (Transformed for Lookup): {transformed_heads}\n"

    @staticmethod
    def _build_combined_head_name(head_spec):
        """Build the display head name for a combined-heads group, matching the
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


class DataDirectoryValidator(object):
    """Validates data directory parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.VALID_EXTENSIONS = ('.exv', '.xpi', '.xiz')

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

        if not data_dir_list or len(data_dir_list.strip()) == 0:
            error_msg = "'data_dir_list' cannot be empty"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        data_dir_list = os.path.normpath(data_dir_list)
        config['data_dir_list'] = data_dir_list

        if not os.path.exists(data_dir_list):
            error_msg = f"'data_dir_list' file does not exist: {data_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not os.path.isfile(data_dir_list):
            error_msg = f"'data_dir_list' must be a file, not a directory: {data_dir_list}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Read and validate file list
        try:
            with open(data_dir_list, 'r', encoding='utf-8-sig') as f:
                file_paths = [line.strip() for line in f if line.strip()]
        except Exception as e:
            error_msg = f"Error reading data_dir_list file: {e}"
            self.logger.error(error_msg)
            raise DataValidationError(error_msg)

        if not file_paths:
            error_msg = f"'data_dir_list' file is empty: {data_dir_list}"
            self.logger.error(error_msg)
            raise DataValidationError(error_msg)

        # Validate that files exist and have valid extensions
        valid_files = 0
        for file_path in file_paths:
            if not os.path.exists(file_path):
                self.logger.warning(f"File in list does not exist: {file_path}")
                continue
            if not file_path.endswith(self.VALID_EXTENSIONS):
                self.logger.warning(f"File in list has invalid extension: {file_path}")
                continue
            valid_files += 1

        if valid_files == 0:
            error_msg = f"'data_dir_list' contains no valid data files (.exv, .xpi, .xiz): {data_dir_list}"
            self.logger.error(error_msg)
            raise DataValidationError(error_msg)

        self.logger.info(f"Validated data_dir_list: {data_dir_list} ({valid_files} valid data files)")
        return config


class RootDirValidator(object):
    """Validates root_dir parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_root_dir(self, config):
        """Validate root_dir parameter"""
        if 'root_dir' not in config:
            error_msg = "Missing REQUIRED parameter: 'root_dir'. A path must be provided"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        else:
            root_dir = config['root_dir']

        # Check if it's empty
        if not root_dir or len(root_dir.strip()) == 0:
            error_msg = "Missing REQUIRED parameter: 'root_dir'. Path must be provided"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Check if it's a string
        if not isinstance(root_dir, str):
            error_msg = f"'root_dir' must be a string, got {type(root_dir).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Strip whitespace
        root_dir = os.path.normpath(root_dir.strip())
        config['root_dir'] = root_dir

        # Check if path points to an existing file (should be directory)
        if os.path.exists(root_dir) and os.path.isfile(root_dir):
            error_msg = f"'root_dir' points to a file, must be a directory: {root_dir}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Check if directory exists and is readable
        if os.path.exists(root_dir):
            if not os.access(root_dir, os.R_OK):
                error_msg = f"'root_dir' directory exists but is not readable: {root_dir}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            self.logger.info(f"Validated root_dir: {root_dir}")
        else:
            error_msg = f"'root_dir' directory does not exist: {root_dir}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        return config


class OutputDirValidator(object):
    """Validates output_path parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_output_path(self, config):
        """Validate output_path parameter using same logic as output_path validation"""
        if 'output_path' not in config:
            error_msg = "Missing REQUIRED parameter: 'output_path'. A path must be provided"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        else:
            output_path = config['output_path']

        # Check if it's empty
        if not output_path or len(output_path.strip()) == 0:
            error_msg = "Missing REQUIRED parameter: 'output_path'. A path must be provided"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Check if it's a string
        if not isinstance(output_path, str):
            error_msg = f"'output_path' must be a string, got {type(output_path).__name__}"
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


class FrequencySegmentValidator(object):
    """Validates frequency segment parameters"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_frequency_segments_inference(self, config):
        """Validate frequency_segments_inference parameter"""
        if 'frequency_segments_inference' not in config:
            error_msg = "Missing REQUIRED parameter: 'frequency_segments_inference'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        freq_segments = config['frequency_segments_inference']

        if not isinstance(freq_segments, list):
            error_msg = f"'frequency_segments_inference' must be a list, got {type(freq_segments).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not freq_segments:
            error_msg = "'frequency_segments_inference' cannot be empty"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        # Validate each segment
        validated_segments = [self._validate_single_segment(seg) for seg in freq_segments]

        # Store as tuples for easier comparison
        config['frequency_segments'] = validated_segments
        self.logger.info(f"Validated {len(validated_segments)} frequency segment(s)")
        return config

    def _validate_single_segment(self, seg):
        """Validate a single frequency segment"""
        if not isinstance(seg, list) or len(seg) != 2:
            error_msg = f"Each frequency segment must be a list of 2 values [start, end], got: {seg}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        start, end = seg

        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            error_msg = f"Frequency values must be numeric, got: {seg}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if start >= end:
            error_msg = f"Start frequency must be less than end frequency: {seg}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if start <= 0 or end <= 0:
            error_msg = f"Frequency values must be positive: {seg}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        return (float(start), float(end))


class MetricValidator(object):
    """Validates metric parameter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # ACI1-4 plus the centroid merge-decision metrics defined in the training
        # application's frf_centroid_metrics.py (CENTROID_METRIC_NAMES)
        self.valid_metrics = ['ACI1', 'ACI2', 'ACI3', 'ACI4', 'Correlation', 'RMSE', 'Wasserstein']

    def validate_metric(self, config):
        """Validate metric parameter"""
        if 'metric' not in config:
            error_msg = "Missing REQUIRED parameter: 'metric'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        else:
            metric = config['metric']

        if not isinstance(metric, list):
            error_msg = f"'metric' must be a list, got {type(metric).__name__}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        if not metric:
            error_msg = "'metric' list cannot be empty"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        for idx, individual_metric in enumerate(metric):
            if not isinstance(individual_metric, str):
                error_msg1 = f"'metric[{idx}]' must be a string, "
                error_msg2 = f"got {type(individual_metric).__name__}: {individual_metric}"
                error_msg = error_msg1 + error_msg2
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            if individual_metric not in self.valid_metrics:
                error_msg = f"Invalid metric: '{individual_metric}'. Must be one of {self.valid_metrics}"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

            if len(individual_metric) != len(individual_metric.strip()):
                error_msg = f"Metric:'{individual_metric}' has leading/trailing whitespace"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

        # Check for duplicates
        if len(metric) != len(set(metric)):
            duplicates = [individual_metric for individual_metric in metric if metric.count(individual_metric) > 1]
            error_msg = f"Duplicate metrics found: {list(set(duplicates))}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

        self.logger.info(f"Validated metrics: {metric}")
        return config
