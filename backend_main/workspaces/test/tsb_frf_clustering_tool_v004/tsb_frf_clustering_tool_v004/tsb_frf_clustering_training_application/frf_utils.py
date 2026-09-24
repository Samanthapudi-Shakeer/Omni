# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_utils.py
*  File Description: Utility file for the training analysis.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import numpy as np
import logging
import shutil
import pandas as pd
from io import StringIO
from frf_output_config import OutputConfigGenerator
from frf_clustering_utils import ClusteringOutputOptions


class HierarchicalStageFeatures(object):
    """Bundles stage1 and stage2 feature lists and weights for hierarchical clustering"""

    def __init__(self, stage1_features, stage1_feature_weights,
                 stage2_features, stage2_feature_weights):
        self.stage1_features = stage1_features
        self.stage1_feature_weights = stage1_feature_weights
        self.stage2_features = stage2_features
        self.stage2_feature_weights = stage2_feature_weights


class BaselineOptions(object):
    """Bundles baseline separation settings passed to process_segment"""

    def __init__(self, baseline_separation=False, baseline_combination=None):
        self.baseline_separation = baseline_separation
        self.baseline_combination = baseline_combination


class HierarchicalFrequencyClusteringConfig(object):
    """Configuration class for hierarchical clustering"""

    def __init__(self, segment_name, segment_dir, models_base_dir, head_name,
                 freq_min, freq_max, stage_features, feature_weights,
                 dataset_type='train', pretrained_models=None, target_k=None,
                 metrics_to_use=None, output_options=None):
        self.segment_name = segment_name
        self.segment_dir = segment_dir
        self.models_base_dir = models_base_dir
        self.head_name = head_name
        self.freq_min = freq_min
        self.freq_max = freq_max
        self.feature_weights = feature_weights
        self.stage1_features = stage_features.stage1_features
        self.stage1_feature_weights = stage_features.stage1_feature_weights
        self.stage2_features = stage_features.stage2_features
        self.stage2_feature_weights = stage_features.stage2_feature_weights
        self.dataset_type = dataset_type
        self.pretrained_models = pretrained_models
        self.target_k = target_k
        self.metrics_to_use = metrics_to_use if metrics_to_use is not None else ['ACI1', 'ACI2', 'ACI3', 'ACI4']

        opts = output_options if output_options is not None else ClusteringOutputOptions()
        self.individual_frequencies_cluster_assignment_plots = opts.individual_frequencies_cluster_assignment_plots
        self.generate_segment_overview = opts.generate_segment_overview
        self.output_dir_is_final = opts.output_dir_is_final
        self.group_label = opts.group_label
        self.generate_interactive_html_plots = opts.generate_interactive_html_plots


class SegmentClusteringConfig(object):
    """Configuration class for segment processing"""

    def __init__(self, segment_name, segment_dir, models_base_dir, head_name,
                 freq_min, freq_max, feature_weights, dataset_type='train',
                 metrics_to_use=None, output_options=None, features_list=None):
        self.segment_name = segment_name
        self.segment_dir = segment_dir
        self.models_base_dir = models_base_dir
        self.head_name = head_name
        self.freq_min = freq_min
        self.freq_max = freq_max
        self.feature_weights = feature_weights
        self.dataset_type = dataset_type
        self.metrics_to_use = metrics_to_use if metrics_to_use is not None else ['ACI1', 'ACI2', 'ACI3', 'ACI4']
        self.features_list = features_list

        opts = output_options if output_options is not None else ClusteringOutputOptions()
        self.individual_frequencies_cluster_assignment_plots = opts.individual_frequencies_cluster_assignment_plots
        self.generate_segment_overview = opts.generate_segment_overview
        self.output_dir_is_final = opts.output_dir_is_final
        self.group_label = opts.group_label
        self.generate_interactive_html_plots = opts.generate_interactive_html_plots


class SegmentContext(object):
    """Bundles per-segment identity and computed data arrays for a single frequency segment."""

    def __init__(self, segment_name, segment_dir, freq_min, freq_max, target_k,
                 segment_file_dict, frequencywise_data, file_indices, unique_frequencies):
        self.segment_name = segment_name
        self.segment_dir = segment_dir
        self.freq_min = freq_min
        self.freq_max = freq_max
        self.target_k = target_k
        self.segment_file_dict = segment_file_dict
        self.frequencywise_data = frequencywise_data
        self.file_indices = file_indices
        self.unique_frequencies = unique_frequencies


class SegmentAccumulators(object):
    """Accumulates processing results across all segments in a run."""

    def __init__(self):
        self.summaries = []
        self.optimal_info = []
        self.model_registry = []
        self.merged_model_registry = []


class SegmentModelsContext(object):
    """Bundles the models base directory and head name used throughout segment processing."""

    def __init__(self, models_base_dir, head_name):
        self.models_base_dir = models_base_dir
        self.head_name = head_name


class ACIOptimalK(object):
    """Bundles the optimal k values per ACI metric (ACI1-ACI4) for a single segment/group."""

    def __init__(self, aci1=1, aci2=1, aci3=1, aci4=1):
        self.aci1 = aci1
        self.aci2 = aci2
        self.aci3 = aci3
        self.aci4 = aci4


class CentroidOptimalK(object):
    """Bundles the optimal k values per centroid metric (Correlation/RMSE/Wasserstein)
    for a single segment/group."""

    def __init__(self, correlation=None, rmse=None, wasserstein=None):
        self.correlation = correlation
        self.rmse = rmse
        self.wasserstein = wasserstein


class LoggingManager(object):
    """Manages logging setup for the application"""

    def __init__(self):
        # No need for declaration
        pass

    @staticmethod
    def setup_logging(output_dir):
        """Setup logging to both file and console"""
        logs_dir = os.path.join(output_dir, 'logs')

        # Use safe directory creation
        try:
            os.makedirs(logs_dir, exist_ok = True)
        except Exception as e:
            # Fallback to current directory if logs dir creation fails
            print(f"Warning: Could not create logs directory: {logs_dir}")
            print(f"Falling back to current directory for logs")
            logs_dir = '.'

        log_file = os.path.join(logs_dir, f'frf_training_application.log')

        try:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file, encoding='utf-8-sig'),
                    logging.StreamHandler()
                ]
            )
        except Exception as e:
            print(f"Error setting up logging: {e}")
            # Fallback to console-only logging
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler()]
            )
            log_file = None

        logger = logging.getLogger(__name__)
        if log_file:
            logger.info(f"Logging initialized. Log file: {log_file}")
        else:
            logger.warning("Logging initialized (console only - file logging failed)")

        return logger, log_file


class FrequencySegmentAvailabilityChecker(object):
    """Checks frequency segment availability in data"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def check_frequency_segments_availability(self, data_list, frequency_segments):
        """Check if all files have frequencies within the defined segments"""
        self.logger.info(f"{'='*60}")
        self.logger.info(f"FREQUENCY SEGMENT ELIGIBILITY CHECK")

        valid_segments = []

        for seg_idx, (freq_min, freq_max) in enumerate(frequency_segments):
            segment_name = f"({freq_min:.2f}, {freq_max:.2f})"
            self.logger.info(f"Validating segment {seg_idx + 1}/{len(frequency_segments)}: {segment_name} Hz")

            files_with_data = 0
            files_without_data = 0

            for file_idx, df in enumerate(data_list):
                frequencies = df['frequency'].values
                segment_frequencies = frequencies[(frequencies >= freq_min) & (frequencies <= freq_max)]

                if len(segment_frequencies) > 0:
                    files_with_data += 1
                else:
                    files_without_data += 1

            self.logger.info(f"  Files with data: {files_with_data}/{len(data_list)}")

            if files_without_data > 0:
                self.logger.error(f"  REJECTED: {files_without_data} file(s) lack data in this segment")
                self.logger.error(f"  Segment {segment_name} rejected")
            else:
                self.logger.info(f"  ACCEPTED: All files have data in this segment")
                valid_segments.append((freq_min, freq_max))
                self.logger.info(f"  Segment {segment_name} validated")

        # Final summary
        self.logger.info(f"{'='*60}")
        self.logger.info(f"FREQUENCY SEGMENT VALIDATION SUMMARY:")
        self.logger.info(f"  Total segments requested: {len(frequency_segments)}")
        self.logger.info(f"  Valid segments: {len(valid_segments)}")
        self.logger.info(f"  Rejected segments: {len(frequency_segments) - len(valid_segments)}")
        self.logger.info(f"{'='*60}")

        if len(valid_segments) == 0:
            self.logger.error(f"  CRITICAL: No valid frequency segments found!")
            error_msg1 = f"  All {len(frequency_segments)} segments were rejected"
            error_msg2 = f"  Because not all files contain data in those ranges"
            error_msg = error_msg1 + error_msg2
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        self.logger.info(f"{'='*60}")

        return valid_segments


class SegmentSummaryGenerator(object):
    """Generates final segment summaries"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def generate_final_segment_summary(self, all_segment_summaries, output_dir,
                                       metrics_to_use=['ACI1', 'ACI2', 'ACI3', 'ACI4'], head_name=None):
        """Generate final summary CSV with segment-level metrics.

        When baseline separation was active, entries contain a 'group' key.  This column
        is placed immediately after 'frequency_segment' in the output CSV.
        """
        if not all_segment_summaries:
            self.logger.warning("No segment summaries to save")
            return None

        final_df = pd.DataFrame(all_segment_summaries)
        has_group = 'group' in final_df.columns

        final_columns = ['frequency_segment']

        # Insert group right after frequency_segment when baseline separation was active
        if has_group:
            final_columns.append('group')

        final_columns += ['dataset', 'num_individual_frequencies', 'num_files']

        if 'ACI1' in metrics_to_use:
            final_columns.extend(['optimal_k_ACI1', 'ACI1'])

        if 'ACI2' in metrics_to_use:
            final_columns.extend(['optimal_k_ACI2', 'ACI2'])

        if 'ACI3' in metrics_to_use:
            final_columns.extend(['optimal_k_ACI3', 'ACI3'])

        if 'ACI4' in metrics_to_use:
            final_columns.extend(['optimal_k_ACI4', 'ACI4'])

        existing_columns = [col for col in final_columns if col in final_df.columns]

        if len(existing_columns) != len(final_columns):
            missing_columns = set(final_columns) - set(existing_columns)
            self.logger.warning(f"Some expected columns are missing: {missing_columns}")
            self.logger.info(f"Available columns: {list(final_df.columns)}")
            self.logger.info(f"Using columns: {existing_columns}")

        final_df = final_df[existing_columns]

        # Sort by frequency_segment first, then by dataset type
        dataset_order = {'train': 0, 'validation_data_dir': 1, 'validation_worst_model': 2}
        final_df['dataset_sort_key'] = final_df['dataset'].map(dataset_order)
        sort_cols = ['frequency_segment']
        if has_group:
            sort_cols.append('group')
        sort_cols.append('dataset_sort_key')
        final_df = final_df.sort_values(sort_cols)
        final_df = final_df.drop('dataset_sort_key', axis=1)

        summary_path = os.path.join(output_dir, f'{head_name}_training_summary.csv')
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        final_df.to_csv(summary_path, index=False, encoding='utf-8-sig')
        return summary_path


class DataFileLoader(object):
    """Handles loading and validation of data files (.exv, .xpi, .xiz)"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.MIN_SAMPLES_EACH_HEAD = 100
        self.reference_frequencies = None

    def load_data_files_by_head(self, file_list_path, head_spec):
        """Load all data files (.exv, .xpi, .xiz) for a specific head or combined heads from
        the file list with comprehensive validation
        Args:
            file_list_path: Path to text file containing data file paths
            head_spec: Either a string (single head) or list of strings (combined heads)

        Returns:
            data_list, filenames
        """
        self.logger.info(f"Loading data files from file list: {file_list_path}")

        # Determine head names and log
        head_names = self._determine_head_names(head_spec)

        # Read file list
        all_files = self._read_file_list(file_list_path)
        self.logger.info(f"Found {len(all_files)} data files in file list")

        # Collect files matching head patterns
        data_files = self._collect_matching_files(all_files, head_names)
        self.logger.info(f"Total files for processing: {len(data_files)}")

        # Load and validate files
        data_list, filenames, file_stats = self._load_and_validate_files(data_files)

        # Log summary
        self._log_loading_summary(head_spec, file_stats)

        if len(data_list) == 0:
            error_msg = self._build_no_files_error_message(head_spec)
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        self.logger.info(f"Successfully loaded {len(data_list)} files for {self._format_head_spec(head_spec)}")
        self.logger.info(f"{'='*60}")

        return data_list, filenames

    def _determine_head_names(self, head_spec):
        """Determine head names from head specification"""
        if isinstance(head_spec, str):
            self.logger.info(f"Processing HEAD: {head_spec}")
            return [head_spec]
        else:
            self.logger.info(f"Processing COMBINED HEADS: {', '.join(head_spec)}")
            return head_spec

    def _read_file_list(self, file_list_path):
        """Read file list from disk"""
        try:
            with open(file_list_path, 'r', encoding='utf-8-sig') as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            error_msg = f"Error reading file list: {e}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _collect_matching_files(self, all_files, head_names):
        """Collect files matching any of the head patterns"""
        data_files = []
        for head_name in head_names:
            head_pattern = f"_{head_name}_"
            matching_files = [file for file in all_files if head_pattern in os.path.basename(file)]
            data_files.extend(matching_files)
            self.logger.info(f"Found {len(matching_files)} files matching HEAD pattern: {head_name}")

        # Remove duplicates
        return list(set(data_files))

    def _load_and_validate_files(self, data_files):
        """Load and validate all data files"""
        data_list = []
        filenames = []
        file_stats = {
            'total_files': len(data_files),
            'successful': 0,
            'failed': 0,
            'empty': 0,
            'validation_errors': 0,
        }

        expected_columns = ['frequency', 'gain', 'phase']
        first_file_freq_count = None
        first_file_frequencies = None

        for file_idx, path in enumerate(data_files):
            filename = os.path.basename(path)

            # Load file
            df = self._load_single_file(path, filename, file_stats)
            if df is None:
                continue

            # Validate structure
            if not self._validate_file_structure(df, filename, file_stats):
                continue

            # Convert to numeric
            df = self._convert_to_numeric(df, expected_columns, filename, file_stats)
            if df is None:
                continue

            # Check for empty
            if self._is_file_empty(df, filename, file_stats):
                continue

            # Validate against reference
            if first_file_frequencies is None:
                first_file_frequencies, first_file_freq_count = self._set_reference_file(
                    df, filename
                )
                self.reference_frequencies = first_file_frequencies.copy()
            else:
                if not self._validate_against_reference(
                    df, filename, first_file_freq_count, first_file_frequencies, file_stats
                ):
                    continue

            # All validations passed
            data_list.append(df)
            filenames.append(os.path.abspath(path))
            file_stats['successful'] += 1

        return data_list, filenames, file_stats

    def _load_single_file(self, path, filename, file_stats):
        """Load a single data file"""
        try:
            # Read file until "END" string is encountered
            with open(path, 'r', encoding='utf-8-sig') as f:
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
            return df
        except Exception as e:
            file_stats['failed'] += 1
            self.logger.warning(f"Unexpected error reading file '{filename}': {e}")
            return None

    def _validate_file_structure(self, df, filename, file_stats):
        """Validate file has correct column structure"""
        if df.shape[1] != 3:
            file_stats['validation_errors'] += 1
            error_msg = f"Invalid row structure: expected 3 columns, got {df.shape[1]}"
            self.logger.warning(f"File '{filename}': {error_msg} - REJECTED")
            return False
        return True

    def _convert_to_numeric(self, df, expected_columns, filename, file_stats):
        """Convert dataframe columns to numeric"""
        df[expected_columns] = df[expected_columns].apply(
            pd.to_numeric, errors='coerce'
        )

        # Check for ANY NaN values
        if df.isnull().any().any():
            file_stats['validation_errors'] += 1
            nan_count = df.isnull().sum().sum()
            error_msg = f"Corrupted file: contains {nan_count} NaN values after numeric conversion"
            self.logger.warning(f"File '{filename}': {error_msg} - REJECTED")
            return None

        return df

    def _is_file_empty(self, df, filename, file_stats):
        """Check if file is empty"""
        if len(df) == 0:
            file_stats['empty'] += 1
            self.logger.warning(f"File '{filename}' is empty - REJECTED")
            return True
        return False

    def _set_reference_file(self, df, filename):
        """Set the first file as reference"""
        frequencies = df['frequency'].values
        freq_count = len(df)
        self.logger.info(f"Reference file '{filename}': {freq_count} frequency points")
        self.logger.info("Checking data files against the reference file ...")
        return frequencies, freq_count

    def _validate_against_reference(self, df, filename, first_file_freq_count,
                                    first_file_frequencies, file_stats):
        """Validate file against reference file"""
        # Validate row count
        if len(df) != first_file_freq_count:
            file_stats['validation_errors'] += 1
            error_msg = f"Number of frequencies count mismatch"
            self.logger.warning(f"File '{filename}': {error_msg} - REJECTED")
            return False

        # Validate frequency grid
        if not np.array_equal(df['frequency'].values, first_file_frequencies):
            file_stats['validation_errors'] += 1
            error_msg = "Frequency grid does not match reference file"
            self.logger.warning(f"File '{filename}': {error_msg} - REJECTED")
            return False

        return True

    def _log_loading_summary(self, head_spec, file_stats):
        """Log file loading summary"""
        self.logger.info(f"{'='*60}")
        self.logger.info(f"FILE LOADING SUMMARY for {self._format_head_spec(head_spec)}:")
        self.logger.info(f"  Total files found: {file_stats['total_files']}")
        self.logger.info(f"  Successfully loaded: {file_stats['successful']}")

    @staticmethod
    def _format_head_spec(head_spec):
        """Format head specification for logging"""
        if isinstance(head_spec, str):
            return f"HEAD {head_spec}"
        else:
            return f"COMBINED HEADS: {', '.join(head_spec)}"

    @staticmethod
    def _build_no_files_error_message(head_spec):
        """Build error message when no files are loaded"""
        if isinstance(head_spec, str):
            return f"No valid data files could be loaded for HEAD {head_spec}"
        else:
            return f"No valid data files could be loaded for COMBINED HEADS: {', '.join(head_spec)}"

    def load_worst_model_files(self, file_list_path, frequency_segments):
        """Load all data files (.exv, .xpi, .xiz) from worst_model file list (no head filtering)
        Args:
            file_list_path: Path to text file containing worst model data file paths
            frequency_segments: List of (freq_min, freq_max) segments from config; restricts the
                cross-dataset frequency grid validation to only these ranges

        Returns:
            data_list, filenames
        """
        self.logger.info(f"Loading worst model data files from file list: {file_list_path}")

        # Read file list
        all_files = self._read_file_list(file_list_path)
        self.logger.info(f"Found {len(all_files)} data files in worst model file list")

        # Load and validate files
        data_list, filenames, file_stats = self._load_and_validate_worst_model_files(all_files)

        # Log summary
        self._log_worst_model_summary(file_stats)

        if len(data_list) == 0:
            error_msg = f"No valid data files could be loaded from worst_model_dir"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Cross-dataset frequency grid validation (restricted to configured frequency segments)
        self._validate_cross_dataset_frequency_grid(data_list[0], frequency_segments)

        self.logger.info(f"Successfully loaded {len(data_list)}/{len(all_files)} valid worst model data files")
        self.logger.info(f"{'='*60}")

        return data_list, filenames

    def _load_and_validate_worst_model_files(self, all_files):
        """Load and validate worst model files"""
        data_list = []
        filenames = []
        file_stats = {
            'total_files': len(all_files),
            'successful': 0,
            'failed': 0,
            'empty': 0,
            'validation_errors': 0,
        }

        expected_columns = ['frequency', 'gain', 'phase']
        first_file_freq_count = None
        first_file_frequencies = None

        for file_idx, path in enumerate(all_files):
            filename = os.path.basename(path)

            # Load file
            df = self._load_single_file(path, filename, file_stats)
            if df is None:
                continue

            # Validate structure
            if not self._validate_file_structure(df, filename, file_stats):
                continue

            # Convert to numeric
            df = self._convert_to_numeric(df, expected_columns, filename, file_stats)
            if df is None:
                continue

            # Check for empty
            if self._is_file_empty(df, filename, file_stats):
                continue

            # Validate against reference
            if first_file_frequencies is None:
                first_file_frequencies, first_file_freq_count = self._set_reference_file(
                    df, filename
                )
            else:
                if not self._validate_against_reference(
                    df, filename, first_file_freq_count, first_file_frequencies, file_stats
                ):
                    continue

            # All validations passed
            data_list.append(df)
            filenames.append(os.path.abspath(path))
            file_stats['successful'] += 1

        return data_list, filenames, file_stats

    def _log_worst_model_summary(self, file_stats):
        """Log worst model file loading summary"""
        self.logger.info(f"{'='*60}")
        self.logger.info(f"WORST MODEL FILE LOADING SUMMARY:")
        self.logger.info(f"  Total files found: {file_stats['total_files']}")
        self.logger.info(f"  Successfully loaded: {file_stats['successful']}")

    @staticmethod
    def _build_segment_mask(frequencies, frequency_segments):
        """Boolean mask selecting only the points that fall within one of the
        (freq_min, freq_max) segments defined in the config"""
        mask = np.zeros(frequencies.shape, dtype=bool)
        for freq_min, freq_max in frequency_segments:
            mask |= (frequencies >= freq_min) & (frequencies <= freq_max)
        return mask

    def _validate_cross_dataset_frequency_grid(self, first_worst_model_df, frequency_segments):
        """Validate frequency grid compatibility between data_dir and worst_model_dir,
        restricted to the frequency segments defined in the config"""
        if self.reference_frequencies is None:
            return

        self.logger.info(f"Validating frequency grid compatibility between data_dir and worst_model_dir...")
        self.logger.info(f"  Restricting comparison to configured frequency segments: {frequency_segments}")

        first_file_frequencies = first_worst_model_df['frequency'].values

        reference_segment_frequencies = self.reference_frequencies[
            self._build_segment_mask(self.reference_frequencies, frequency_segments)
        ]
        worst_model_segment_frequencies = first_file_frequencies[
            self._build_segment_mask(first_file_frequencies, frequency_segments)
        ]

        if len(worst_model_segment_frequencies) != len(reference_segment_frequencies):
            error_msg = (
                f"Frequency grid mismatch between data_dir and worst_model_dir within configured segments: "
                f"data_dir has {len(reference_segment_frequencies)} frequency points, "
                f"worst_model_dir has {len(worst_model_segment_frequencies)} frequency points"
            )
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        if not np.array_equal(worst_model_segment_frequencies, reference_segment_frequencies):
            error_msg = (
                "Individual frequency values in the data files, within the configured frequency segments, "
                "don't match with the individual frequency values in the worst model files"
            )
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        self.logger.info(f"  Frequency grid validation PASSED")


class CleanupManager(object):
    """Manages cleanup operations"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def cleanup_pycache(self):
        """Remove __pycache__ directories"""
        try:
            for root, dirs, files in os.walk('.'):
                for dir_name in dirs[:]:
                    if dir_name == '__pycache__':
                        pycache_path = os.path.join(root, dir_name)
                        shutil.rmtree(pycache_path)
                        dirs.remove(dir_name)
        except Exception as e:
            self.logger.warning(f"Error cleaning up __pycache__ folders: {e}")


class ModelRegistryGenerator(object):
    """Generates trained models registry"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.relative_path = OutputConfigGenerator()

    def generate_trained_models_registry(self, all_models_registry, frf_clustering_analysis_dir):
        """Generate CSV file with trained models registry with relative paths.

        Every entry (normal single-stage or hierarchical 'combined') now carries a
        'cluster_count' key — hierarchical combinations are flat single-stage models
        just like normal training, so both modes share the same entry shape and sort.

        When baseline separation was active, entries carry a 'group' key; this column is
        placed immediately after 'segment' in the CSV (not at the end).
        """
        if not all_models_registry:
            self.logger.warning("No trained models to register")
            return None

        has_group = 'group' in all_models_registry[0]

        # Convert absolute paths to relative paths
        registry_with_relative_paths = []
        for entry in all_models_registry:
            relative_entry = entry.copy()
            relative_entry['trained_model_path'] = self.relative_path._convert_to_relative_path(
                entry['trained_model_path'], frf_clustering_analysis_dir
            )
            if 'merged_model_path' in relative_entry:
                relative_entry['merged_model_path'] = self.relative_path._convert_to_relative_path(
                    relative_entry['merged_model_path'], frf_clustering_analysis_dir
                )
            registry_with_relative_paths.append(relative_entry)

        # Create DataFrame
        registry_df = pd.DataFrame(registry_with_relative_paths)

        # Ensure 'group' column appears immediately after 'segment', not at the tail
        if has_group and 'group' in registry_df.columns:
            cols = list(registry_df.columns)
            cols.remove('group')
            seg_pos = cols.index('segment')
            cols.insert(seg_pos + 1, 'group')
            registry_df = registry_df[cols]

        # Sort by head/segment/(group)/cluster_count — same flat sort for every mode
        sort_cols = ['head_name', 'segment']
        if has_group:
            sort_cols.append('group')
        if 'cluster_count' in registry_df.columns:
            sort_cols.append('cluster_count')
        registry_df = registry_df.sort_values(sort_cols)

        # Save to CSV
        registry_path = os.path.join(frf_clustering_analysis_dir, 'trained_models_registry.csv')
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)
        registry_df.to_csv(registry_path, index=False, encoding='utf-8-sig')
        self.logger.info(f"   Total models registered: {len(registry_df)}")
        return registry_path
