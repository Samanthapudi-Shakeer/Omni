# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Merging Utility Package
*  File Name: frf_merge_config_loader.py
*  File Description: Standalone config parsing, validation and logging setup
*                    for the FRF cluster-merging utility. Self contained -
*                    no dependency on the training application package.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import ast
import shutil
import logging
import configparser
from io import StringIO
import pandas as pd


VALID_BASELINE_GROUPS = ('phase_lead', 'phase_lag', 'no_resonance')
VALID_DATA_EXTENSIONS = ('.exv', '.xpi', '.xiz')
VALID_MERGE_MODEL_KEYS = frozenset({'name', 'path', 'clusters_combined', 'baseline_group'})


logging.getLogger(__name__).addHandler(logging.NullHandler())


class ConfigValidationError(Exception):
    """Raised when the merge utility config file fails validation."""


class ConfigFileParser(object):
    """Parses .cfg files (ConfigParser + ast.literal_eval), flattened into one dict."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_cfg_file(self, config_path):
        """Parse a .cfg file into a flat dict of Python-typed values."""
        try:
            cfg = configparser.ConfigParser(
                inline_comment_prefixes=('#',), comment_prefixes=('#',), allow_no_value=False
            )
            cfg.optionxform = str
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                raw_text = f.read()
            cfg.read_string(self._normalize_multiline_values(raw_text), source=config_path)
            return self._flatten_sections(cfg)
        except Exception as e:
            error_msg = f"Unexpected error parsing config file: {e}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    @staticmethod
    def _normalize_multiline_values(raw_text):
        """Let a bracketed list/dict value (e.g. merge_models) span multiple lines
        without every continuation line needing to be hand-indented: any raw line
        left unindented while a '[' or '{' opened on an earlier line is still
        outstanding gets forcibly indented, so configparser's own continuation
        rule (an indented line belongs to the previous key) picks it up regardless
        of how the user formatted it - including an unindented closing bracket.
        Full-line comments are passed through untouched and never counted, since
        configparser already recognizes and strips them inside a continuation."""
        normalized_lines = []
        open_brackets = 0
        for line in raw_text.splitlines(keepends=True):
            if line.lstrip().startswith('#'):
                normalized_lines.append(line)
                continue
            if open_brackets > 0 and line.strip() and not line[0].isspace():
                line = '    ' + line
            normalized_lines.append(line)
            open_brackets += line.count('[') + line.count('{')
            open_brackets -= line.count(']') + line.count('}')
            open_brackets = max(open_brackets, 0)
        return ''.join(normalized_lines)

    def _flatten_sections(self, cfg):
        """Flatten every section's key/value pairs into a single dict."""
        config = {}
        for section in cfg.sections():
            for key, value in cfg.items(section):
                config[key] = self._parse_value(value.strip())
        return config

    @staticmethod
    def _parse_value(value):
        """Evaluate a raw string as a Python literal, falling back to plain string."""
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value


class DataDirectoryAnalyzer(object):
    """Detects the data's frequency range from a sample file of a file list
    (same approach as the training application's DataDirectoryAnalyzer)."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def get_min_max_frequency(self, file_list_path):
        """Return (min_freq, max_freq) read from the first file listed in file_list_path."""
        with open(file_list_path, 'r', encoding='utf-8-sig') as f:
            file_paths = [line.strip() for line in f if line.strip()]
        sample_file = file_paths[0]
        self.logger.info(f"Detecting min and max frequency from sample file: {os.path.basename(sample_file)}")
        frequencies = self._read_sample_frequencies(sample_file)
        min_freq, max_freq = frequencies.min(), frequencies.max()
        self.logger.info(f"Detected minimum frequency: {min_freq:.2f} Hz")
        self.logger.info(f"Detected maximum frequency: {max_freq:.2f} Hz")
        return min_freq, max_freq

    def _read_sample_frequencies(self, sample_file):
        """Parse the sample GPLOT file (9-line header, body up to 'END') and return its frequencies."""
        try:
            with open(sample_file, 'r', encoding='utf-8-sig') as f:
                lines = []
                for line in f:
                    if line.strip() == 'END':
                        break
                    lines.append(line)
            df = pd.read_csv(
                StringIO(''.join(lines)), skiprows=9, header=None,
                names=['frequency', 'gain', 'phase'], encoding='utf-8-sig'
            )
            df = df.apply(pd.to_numeric, errors='coerce')
            df.dropna(subset=['frequency'], inplace=True)
        except Exception as e:
            error_msg = f"Could not detect minimum and maximum frequency from {os.path.basename(sample_file)}: {e}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if df.isnull().any().any():
            nan_count = df.isnull().sum().sum()
            error_msg = f"Corrupted file: {sample_file} contains {nan_count} NaN values after numeric conversion"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if len(df) == 0:
            error_msg = f"No valid frequency data in sample file: {os.path.basename(sample_file)}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        return df['frequency'].values


class MergeConfigLoader(object):
    """Loads and validates the FRF merging utility configuration file.

    Required parameters: output_path, data_dir_list, frequency_segment,
    feature_config, baseline_data_separation, merge_models. Optional:
    worst_model_dir_list. Each merge_models entry is self-contained (path,
    clusters_combined, optional name, and - only when baseline_data_separation
    =True - its own baseline_group), so there is no separate positionally
    aligned parameter to keep in sync anymore.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.parser = ConfigFileParser()
        self.data_analyzer = DataDirectoryAnalyzer()

    def load_config(self, config_path):
        """Parse and fully validate the merge utility config file."""
        self._validate_file_path(config_path)
        config = self.parser.parse_cfg_file(config_path)
        self._validate_output_path(config)
        self._validate_data_dir_list(config)
        self._validate_worst_model_dir_list(config)
        self._validate_frequency_segment(config)
        self._validate_feature_config(config)
        self._validate_baseline_data_separation(config)
        self._validate_merge_models(config)
        self.logger.info("Merge utility configuration validated successfully")
        return config

    @staticmethod
    def _validate_file_path(config_path):
        """Confirm the config file exists and has a .cfg extension."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        if os.path.splitext(config_path)[1].lower() != '.cfg':
            raise ConfigValidationError(f"Configuration file must be a .cfg file: {config_path}")

    def _require(self, config, key):
        """Raise if a required key is missing from the parsed config."""
        if key not in config:
            error_msg = f"Missing REQUIRED parameter: '{key}'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        return config[key]

    def _validate_output_path(self, config):
        """Validate output_path: non-empty string, not an existing file."""
        value = self._require(config, 'output_path')
        if not isinstance(value, str) or not value.strip():
            error_msg = "'output_path' must be a non-empty string"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        value = os.path.normpath(value.strip())
        if os.path.exists(value) and os.path.isfile(value):
            error_msg = f"'output_path' points to a file, must be a directory: {value}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        config['output_path'] = value

    def _validate_data_dir_list(self, config):
        """Validate data_dir_list: existing .txt file listing valid data files."""
        value = self._require(config, 'data_dir_list')
        self._validate_file_list_param(value, 'data_dir_list')
        config['data_dir_list'] = value

    def _validate_worst_model_dir_list(self, config):
        """Validate optional worst_model_dir_list; None when absent/empty."""
        value = config.get('worst_model_dir_list')
        if value is None or value == '':
            self.logger.info("No worst_model_dir_list specified. Proceeding with data_dir_list only.")
            config['worst_model_dir_list'] = None
            return
        self._validate_file_list_param(value, 'worst_model_dir_list')
        config['worst_model_dir_list'] = value

    def _validate_file_list_param(self, value, param_name):
        """Shared existence/extension/content validation for *_dir_list params."""
        if not isinstance(value, str) or not value:
            error_msg = f"'{param_name}' must be a non-empty string"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if not os.path.isfile(value):
            error_msg = f"'{param_name}' file does not exist: {value}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if not value.endswith('.txt'):
            error_msg = f"'{param_name}' must be a .txt file, got: {value}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        self._validate_file_list_contents(value, param_name)

    def _validate_file_list_contents(self, path, param_name):
        """Confirm the referenced file list is non-empty and has valid extensions."""
        with open(path, 'r', encoding='utf-8-sig') as f:
            lines = [line.strip() for line in f if line.strip()]
        if not lines:
            error_msg = f"'{param_name}' file list is empty: {path}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        valid_files = sum(1 for line in lines if line.endswith(VALID_DATA_EXTENSIONS))
        if valid_files == 0:
            error_msg = f"'{param_name}' contains no valid data files {VALID_DATA_EXTENSIONS}: {path}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        self.logger.info(f"Validated {param_name}: {path} ({valid_files} data files)")

    def _validate_frequency_segment(self, config):
        """Validate frequency_segment: [freq_min, freq_max], both positive, min < max."""
        value = self._require(config, 'frequency_segment')
        if not isinstance(value, (list, tuple)):
            error_msg = f"'frequency_segment' must be a list [freq_min, freq_max], got: {value!r}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if len(value) != 2:
            error_msg = (f"'frequency_segment' must be a 2-element list [freq_min, freq_max], "
                         f"got {len(value)} element(s): {list(value)}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        freq_min, freq_max = value
        if not all(isinstance(v, (int, float)) for v in (freq_min, freq_max)):
            error_msg = "'frequency_segment' values must be numeric"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if freq_min <= 0 or freq_max <= 0 or freq_min >= freq_max:
            error_msg = (f"'frequency_segment' invalid: ({freq_min}, {freq_max}). "
                         f"Both values must be positive and freq_min < freq_max")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        min_freq_from_data, max_freq_from_data = self.data_analyzer.get_min_max_frequency(config['data_dir_list'])
        self._validate_against_data_limits(freq_min, freq_max, min_freq_from_data, max_freq_from_data)
        config['frequency_segment'] = (float(freq_min), float(freq_max))

    def _validate_against_data_limits(self, freq_min, freq_max, min_freq_from_data, max_freq_from_data):
        """Reject a frequency_segment that falls outside the data's frequency range
        (same four checks as the training application)."""
        prefix = f"Invalid 'frequency_segment' [{freq_min}, {freq_max}]. "
        checks = (
            (freq_min > max_freq_from_data,
             f"Start frequency ({freq_min} Hz) exceeds maximum frequency ({max_freq_from_data:.2f} Hz)"),
            (freq_max > max_freq_from_data,
             f"End frequency ({freq_max} Hz) exceeds maximum frequency ({max_freq_from_data:.2f} Hz)"),
            (freq_min < min_freq_from_data,
             f"Start frequency ({freq_min} Hz) less than minimum frequency ({min_freq_from_data:.2f} Hz)"),
            (freq_max < min_freq_from_data,
             f"End frequency ({freq_max} Hz) less than minimum frequency ({min_freq_from_data:.2f} Hz)"),
        )
        for violated, reason in checks:
            if violated:
                error_msg = prefix + reason
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

    def _validate_feature_config(self, config):
        """Validate feature_config: existing .json file path."""
        value = self._require(config, 'feature_config')
        if not isinstance(value, str) or not value:
            error_msg = "'feature_config' must be a non-empty string path"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if not os.path.isfile(value) or not value.endswith('.json'):
            error_msg = f"'feature_config' must point to an existing .json file: {value}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        config['feature_config'] = value

    def _validate_baseline_data_separation(self, config):
        """Validate baseline_data_separation: required boolean."""
        value = self._require(config, 'baseline_data_separation')
        if not isinstance(value, bool):
            error_msg = (f"'baseline_data_separation' must be a boolean (True or False). "
                         f"Got {type(value).__name__}: {value!r}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        config['baseline_data_separation'] = value

    def _validate_merge_models(self, config):
        """Validate the unified 'merge_models' parameter and resolve it into the
        ordered 'merge_plan' list consumed directly by the orchestrator. Each
        entry carries its own model path, cluster merge groups, resolved display
        name, and (when baseline_data_separation=True) its own baseline_group -
        no separate positionally-aligned parameters to keep in sync."""
        merge_models = self._require(config, 'merge_models')
        if isinstance(merge_models, str):
            error_msg = (f"'merge_models' is not valid Python list/dict syntax")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if not isinstance(merge_models, list):
            error_msg = f"'merge_models' must be a list of dicts. Got {type(merge_models).__name__}: {merge_models!r}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if not merge_models:
            error_msg = "'merge_models' must be a non-empty list - at least one model entry is required"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        baseline_enabled = config['baseline_data_separation']
        merge_plan = [
            self._validate_one_merge_model_entry(entry, idx, baseline_enabled)
            for idx, entry in enumerate(merge_models)
        ]
        self._reject_all_groups_combined(merge_plan)
        self._reject_duplicate_names(merge_plan)
        config['merge_plan'] = merge_plan

    def _validate_one_merge_model_entry(self, entry, idx, baseline_enabled):
        """Validate one merge_models entry and resolve it into a merge_plan dict."""
        if not isinstance(entry, dict):
            error_msg = f"'merge_models[{idx}]' must be a dict. Got {type(entry).__name__}: {entry!r}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        self._validate_no_unknown_keys(entry, idx)
        self._validate_required_keys_present(entry, idx, baseline_enabled)
        model_path = self._validate_model_path(entry, idx)
        cluster_groups = self._validate_entry_clusters_combined(entry, idx)
        baseline_group, group_label = self._validate_entry_baseline_group(entry, idx, baseline_enabled)
        name = self._resolve_entry_name(entry, idx, baseline_enabled, group_label)
        return {
            'name': name,
            'baseline_group': baseline_group,
            'group_label': group_label,
            'model_path': model_path,
            'cluster_groups': cluster_groups,
        }

    def _validate_no_unknown_keys(self, entry, idx):
        """Reject any key not in VALID_MERGE_MODEL_KEYS - catches a misspelled key
        (e.g. 'paths', 'cluster_combined') silently falling back to a missing-key
        or default-value error instead of naming the actual typo."""
        unknown_keys = set(entry) - VALID_MERGE_MODEL_KEYS
        if unknown_keys:
            error_msg = (f"'merge_models[{idx}]' has unrecognised key(s) {sorted(unknown_keys)}. "
                         f"Valid keys are {sorted(VALID_MERGE_MODEL_KEYS)}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    def _validate_required_keys_present(self, entry, idx, baseline_enabled):
        """Collect every missing required key at once - 'path' and 'clusters_combined'
        always, plus 'baseline_group' when baseline_data_separation=True or 'name' when
        it's False - instead of stopping at the first one found, so all of an entry's
        problems can be fixed in a single pass. 'clusters_combined' must be present, but
        an explicit empty list ([]) is still a valid way to request no merges, just a
        re-convergence."""
        required_keys = ['path', 'clusters_combined', 'baseline_group' if baseline_enabled else 'name']
        missing_keys = [key for key in required_keys if entry.get(key) is None]
        if missing_keys:
            error_msg = f"'merge_models[{idx}]' missing required key(s): {missing_keys}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    def _validate_entry_clusters_combined(self, entry, idx):
        """Validate one entry's clusters_combined: non-empty list of >= 2-id tuples,
        no id reused within the same entry. Required key (see
        _validate_required_keys_present); an empty list is rejected too, since a
        merge_models entry with nothing to merge has no purpose."""
        clusters_combined = entry.get('clusters_combined', [])
        if isinstance(clusters_combined, list) and not clusters_combined:
            error_msg = (f"'clusters_combined' in 'merge_models[{idx}]' is an empty list - "
                         f"at least one group of >= 2 cluster ids to merge must be specified")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        self._validate_one_model_groups(clusters_combined, idx)
        return [tuple(g) for g in clusters_combined]

    def _validate_entry_baseline_group(self, entry, idx, baseline_enabled):
        """Validate the 'baseline_group' key: required (string, or tuple/list of
        >= 2 distinct groups to combine) when baseline separation is on, must be
        absent when it's off. The same group (or combo) may legitimately be
        reused across different merge_models entries. Returns
        (raw_value_or_None, resolved_string_label_or_None)."""
        baseline_group = entry.get('baseline_group')
        if not baseline_enabled:
            if baseline_group is not None:
                error_msg = f"'merge_models[{idx}]' has 'baseline_group' but baseline_data_separation=False"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            return None, None
        if baseline_group is None:
            error_msg = f"'merge_models[{idx}]' missing required key 'baseline_group'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if isinstance(baseline_group, str):
            normalised = self._normalise_baseline_string(baseline_group, idx)
            return normalised, normalised
        if isinstance(baseline_group, (tuple, list)):
            normalised = self._normalise_baseline_sublist(baseline_group, idx)
            return tuple(normalised), '_'.join(normalised)
        error_msg = f"'merge_models[{idx}]' 'baseline_group' must be a string or tuple/list"
        self.logger.error(error_msg)
        raise ConfigValidationError(error_msg)

    def _resolve_entry_name(self, entry, idx, baseline_enabled, group_label):
        """Resolve the entry's display/output name. Required in flat mode
        (baseline_data_separation=False) and validated as a non-empty string here
        (presence alone is checked earlier by _validate_required_keys_present).
        Optional in baseline mode, where an omitted name falls back to the
        baseline group label, or a positional default 'model_<n>' if that's absent too."""
        name = entry.get('name')
        if not baseline_enabled:
            if not isinstance(name, str) or not name.strip():
                error_msg = (f"'name' in 'merge_models[{idx}]' must be a non-empty string "
                             f"when baseline_data_separation=False. Got {type(name).__name__}: {name!r}")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            return name.strip()
        if isinstance(name, str) and name.strip():
            return name.strip()
        return group_label if group_label else f"model_{idx + 1}"

    def _normalise_baseline_string(self, item, idx):
        """Validate a single baseline group name entry."""
        normalised = item.strip().lower()
        self._check_valid_group(normalised, idx)
        return normalised

    def _normalise_baseline_sublist(self, item, idx):
        """Validate a combined-group sublist entry (>= 2 distinct groups)."""
        if len(item) < 2:
            error_msg = f"'merge_models[{idx}]' baseline_group sublist needs >= 2 groups"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        normalised_sub, seen_in_item = [], set()
        for sub_item in item:
            if not isinstance(sub_item, str):
                error_msg = f"'merge_models[{idx}]' baseline_group sublist entries must be strings"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            normalised = sub_item.strip().lower()
            self._check_valid_group(normalised, idx)
            if normalised in seen_in_item:
                error_msg = f"'merge_models[{idx}]' baseline_group repeats group '{normalised}'"
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            seen_in_item.add(normalised)
            normalised_sub.append(normalised)
        return normalised_sub

    def _check_valid_group(self, normalised, idx):
        """Ensure a group name is one of the valid baseline groups."""
        if normalised not in VALID_BASELINE_GROUPS:
            error_msg = (f"'merge_models[{idx}]' baseline_group '{normalised}' invalid. "
                         f"Must be one of: {VALID_BASELINE_GROUPS}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)

    def _reject_all_groups_combined(self, merge_plan):
        """Reject any entry whose baseline_group combines all three groups into
        one, which defeats the purpose of separation."""
        for idx, plan_entry in enumerate(merge_plan):
            group = plan_entry['baseline_group']
            if isinstance(group, tuple) and set(group) == set(VALID_BASELINE_GROUPS):
                error_msg = (f"'merge_models[{idx}]' baseline_group combines all three groups "
                             f"into one, which defeats the purpose of separation")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)

    def _reject_duplicate_names(self, merge_plan):
        """Reject the merge plan if two or more entries resolve to the same
        output name (whether from an explicit 'name' or a defaulted
        baseline_group label/position) - resolved names must be unique since
        they are used directly as the output folder name."""
        seen = set()
        for idx, plan_entry in enumerate(merge_plan):
            name = plan_entry['name']
            if name in seen:
                error_msg = (f"'merge_models[{idx}]' resolved name '{name}' is already used by "
                             f"another entry; give each entry a distinct 'name'")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            seen.add(name)

    def _validate_model_path(self, entry, idx):
        """Confirm one merge_models entry's model path exists and points to a .json file."""
        tag = f" in 'merge_models[{idx}]'"
        path = entry.get('path')
        if path is None:
            error_msg = f"'merge_models[{idx}]' missing required key 'path'"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if not isinstance(path, str) or not path.strip():
            error_msg = f"'path'{tag} must be a non-empty string. Got {type(path).__name__}: {path!r}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if not os.path.isfile(path):
            error_msg = f"'path'{tag} file does not exist: {path}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if not path.endswith('.json'):
            error_msg = f"'path'{tag} must be a .json file, got: {path}"
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        return os.path.abspath(path)

    def _validate_one_model_groups(self, groups, model_idx):
        """Validate one model's list of merge-group tuples: well-formed, non-negative
        integers, no cluster id reused across groups for the same model."""
        if not isinstance(groups, list):
            error_msg = (f"'merge_models[{model_idx}]' 'clusters_combined' must be a list of tuples. "
                         f"Got {type(groups).__name__}: {groups!r}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        seen_ids = set()
        for group in groups:
            self._validate_one_group_tuple(group, model_idx, seen_ids)

    def _validate_one_group_tuple(self, group, model_idx, seen_ids):
        """Validate a single merge-group tuple/list of cluster ids."""
        if not isinstance(group, (tuple, list)):
            error_msg = (f"'merge_models[{model_idx}]' clusters_combined group '{group!r}' must be a "
                         f"tuple/list of cluster ids, got {type(group).__name__}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        if len(group) < 2:
            error_msg = (f"'merge_models[{model_idx}]' clusters_combined group '{tuple(group)}' must have "
                         f">= 2 cluster ids, got {len(group)}")
            self.logger.error(error_msg)
            raise ConfigValidationError(error_msg)
        for cluster_id in group:
            if not isinstance(cluster_id, int):
                error_msg = (f"'merge_models[{model_idx}]' clusters_combined group '{tuple(group)}' must "
                             f"contain ints, got {type(cluster_id).__name__}: {cluster_id!r}")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            if cluster_id < 0:
                error_msg = (f"'merge_models[{model_idx}]' clusters_combined group '{tuple(group)}' must "
                             f"contain non-negative ints, got {cluster_id}")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            if cluster_id in seen_ids:
                error_msg = (f"'merge_models[{model_idx}]' cluster id {cluster_id} "
                             f"appears in more than one merge group")
                self.logger.error(error_msg)
                raise ConfigValidationError(error_msg)
            seen_ids.add(cluster_id)


class LoggingManager(object):
    """Sets up file + console logging for the merge utility run."""

    @staticmethod
    def setup_logging(merging_log_dir):
        """Configure root logging to write into merging_log_dir and the console."""
        os.makedirs(merging_log_dir, exist_ok=True)
        log_file = os.path.join(merging_log_dir, 'frf_merging_utility.log')
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8-sig'),
                logging.StreamHandler(),
            ]
        )
        logger = logging.getLogger(__name__)
        logger.info(f"Logging initialized. Log file: {log_file}")
        return logger, log_file


class CleanupManager(object):
    """Manages cleanup operations."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def cleanup_pycache(self):
        """Remove __pycache__ directories."""
        try:
            for root, dirs, files in os.walk('.'):
                for dir_name in dirs[:]:
                    if dir_name == '__pycache__':
                        pycache_path = os.path.join(root, dir_name)
                        shutil.rmtree(pycache_path)
                        dirs.remove(dir_name)
        except Exception as e:
            self.logger.warning(f"Error cleaning up __pycache__ folders: {e}")
