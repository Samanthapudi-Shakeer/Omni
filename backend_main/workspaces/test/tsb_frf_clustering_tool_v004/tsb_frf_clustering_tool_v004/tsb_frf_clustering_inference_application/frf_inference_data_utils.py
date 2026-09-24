# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_data_utils.py
*  File Description: Data loading, preprocessing and plot execution utilities
*                    for the inference application.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import numpy as np
import logging
from scipy.ndimage import uniform_filter1d
import pandas as pd
from io import StringIO
from frf_inference_metric_components import CoordinateConverter
import time
import multiprocessing as mp


class DataFileLoader(object):
    """Handles loading and validation of EXV, XPI and XIZ data files"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def load_data_files_by_head(self, file_list_path, head_spec):
        """Load all data files (.exv, .xpi, .xiz) for a specific head or combined heads from file list

        Args:
            file_list_path: Path to text file containing data file paths
            head_spec: Either a string (single head) or list of strings (combined heads)

        Returns:
            data_list, filenames
        """
        self.logger.info(f"Loading data files from file list: {file_list_path}")

        head_names = self._normalize_head_spec(head_spec)
        all_files = self._read_file_list(file_list_path)
        data_files = self._collect_matching_files(all_files, head_names)

        data_list, filenames, file_stats = self._process_data_files(data_files)

        self._log_summary(file_stats, head_spec)
        self._validate_results(data_list, head_spec)

        return data_list, filenames

    def get_all_available_heads(self, file_list_path):
        """Automatically detect all available heads from the file list, matching the
        training application's DataDirectoryAnalyzer.get_all_available_heads exactly.
        Used during config validation to resolve head-selection keywords (e.g.
        'even_number_heads') into literal head names."""
        all_files = self._read_file_list(file_list_path)

        heads = set()
        for file_path in all_files:
            filename = os.path.basename(file_path)
            # Format: P0U62150009661_HD0_CYL0007BD37_T001F_0002.exv
            # Look for pattern: _{head_name}_
            parts = filename.split('_')
            if len(parts) > 1:
                heads.add(parts[1])

        return sorted(list(heads))

    def _normalize_head_spec(self, head_spec):
        """Normalize head_spec to list of head names and log appropriately"""
        if isinstance(head_spec, str):
            head_names = [head_spec]
            self.logger.info(f"Processing HEAD: {head_spec}")
        elif isinstance(head_spec, list):
            head_names = head_spec
            self.logger.info(f"Processing COMBINED HEADS: {', '.join(head_names)}")
        else:
            raise ValueError(f"head_spec must be string or list, got {type(head_spec)}")
        return head_names

    def _read_file_list(self, file_list_path):
        """Read file list from path and return list of file paths"""
        try:
            with open(file_list_path, 'r', encoding='utf-8-sig') as f:
                all_files = [line.strip() for line in f if line.strip()]
        except Exception as e:
            error_msg = f"Error reading file list: {e}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        self.logger.info(f"Found {len(all_files)} data files in file list")
        return all_files

    def _collect_matching_files(self, all_files, head_names):
        """Collect files matching any of the head patterns"""
        data_files = []
        for head_name in head_names:
            head_pattern = f"_{head_name}_"
            matching_files = [file for file in all_files if head_pattern in os.path.basename(file)]
            data_files.extend(matching_files)
            self.logger.info(f"Found {len(matching_files)} files matching HEAD pattern: {head_name}")

        # Remove duplicates
        data_files = list(set(data_files))
        self.logger.info(f"Total files for processing: {len(data_files)}")
        return data_files

    def _process_data_files(self, data_files):
        """Process all data files and return validated data"""
        data_list = []
        filenames = []
        file_stats = self._initialize_file_stats(len(data_files))

        expected_columns = ['frequency', 'gain', 'phase']
        first_file_freq_count = None
        first_file_frequencies = None

        for file_idx, path in enumerate(data_files):
            filename = os.path.basename(path)

            df = self._read_single_file(path, filename, expected_columns, file_stats)
            if df is None:
                continue

            if first_file_frequencies is None:
                first_file_frequencies, first_file_freq_count = self._establish_reference(
                    df, filename
                )
            else:
                if not self._validate_against_reference(
                    df, filename, first_file_freq_count, first_file_frequencies, file_stats
                ):
                    continue

            # All validations passed
            data_list.append(df)
            filenames.append(filename)
            file_stats['successful'] += 1

        return data_list, filenames, file_stats

    @staticmethod
    def _initialize_file_stats(total_files):
        """Initialize file statistics dictionary"""
        return {
            'total_files': total_files,
            'successful': 0,
            'failed': 0,
            'empty': 0,
            'validation_errors': 0,
        }

    def _read_single_file(self, path, filename, expected_columns, file_stats):
        """Read and validate a single data file"""
        try:
            # Read file until "END" string is encountered
            with open(path, 'r', encoding='utf-8-sig') as f:
                lines = []
                for line in f:
                    if line.strip() == "END":
                        break
                    lines.append(line)

            # Convert lines to dataframe
            df = pd.read_csv(StringIO(''.join(lines)),
                            skiprows=9,
                            header=None,
                            names=expected_columns,
                            encoding='utf-8-sig')

            # Validate and clean data
            if not self._validate_and_clean_data(df, filename, file_stats):
                return None

            return df

        except Exception:
            file_stats['failed'] += 1
            self.logger.warning(f"Unexpected error reading file '{filename}'")
            return None

    def _validate_and_clean_data(self, df, filename, file_stats):
        if not self._validate_file_structure(df, filename, file_stats):
            return False

        if not self._validate_file_content(df, filename, file_stats):
            return False

        return True

    def _validate_file_structure(self, df, filename, file_stats):
        """Validate row structure of dataframe"""
        if df.shape[1] != 3:
            file_stats['validation_errors'] += 1
            error_msg = f"Invalid row structure: expected 3 columns, got {df.shape[1]}"
            self.logger.warning(f"File '{filename}': {error_msg} - REJECTED")
            return False
        return True

    def _validate_file_content(self, df, filename, file_stats):
        """Validate content of dataframe (numeric conversion and NaN check)"""
        expected_columns = ['frequency', 'gain', 'phase']

        # Convert to numeric
        df[expected_columns] = df[expected_columns].apply(
            pd.to_numeric, errors='coerce'
        )

        # Check for ANY NaN values
        if df.isnull().any().any():
            file_stats['validation_errors'] += 1
            nan_count = df.isnull().sum().sum()
            error_msg = f"Corrupted file: contains {nan_count} NaN values after numeric conversion"
            self.logger.warning(f"File '{filename}': {error_msg} - REJECTED")
            return False

        # Check if empty
        if len(df) == 0:
            file_stats['empty'] += 1
            self.logger.warning(f"File '{filename}' is empty - REJECTED")
            return False

        return True

    def _establish_reference(self, df, filename):
        """Establish reference frequency grid from first file"""
        first_file_frequencies = df['frequency'].values
        first_file_freq_count = len(df)
        self.logger.info(f"Reference file '{filename}': {first_file_freq_count} frequency points")
        self.logger.info("Checking data files against the reference file ...")
        return first_file_frequencies, first_file_freq_count

    def _validate_against_reference(self, df, filename, first_file_freq_count,
                                   first_file_frequencies, file_stats):
        """Validate file against reference frequency grid"""
        # Validate row count matches first file
        if len(df) != first_file_freq_count:
            file_stats['validation_errors'] += 1
            error_msg = f"Number of frequencies count mismatch"
            self.logger.warning(f"File '{filename}': {error_msg} - REJECTED")
            return False

        # Validate frequency grid matches first file
        if not np.array_equal(df['frequency'].values, first_file_frequencies):
            file_stats['validation_errors'] += 1
            error_msg = "Frequency grid does not match reference file"
            self.logger.warning(f"File '{filename}': {error_msg} - REJECTED")
            return False

        return True

    def _log_summary(self, file_stats, head_spec):
        """Log loading summary"""
        self.logger.info(f"{'='*60}")
        if isinstance(head_spec, str):
            self.logger.info(f"FILE LOADING SUMMARY for HEAD {head_spec}:")
        else:
            self.logger.info(f"FILE LOADING SUMMARY for COMBINED HEADS {', '.join(head_spec)}:")
        self.logger.info(f"  Total files found: {file_stats['total_files']}")
        self.logger.info(f"  Successfully loaded: {file_stats['successful']}")

    def _validate_results(self, data_list, head_spec):
        """Validate that at least some files were loaded successfully"""
        if len(data_list) == 0:
            if isinstance(head_spec, str):
                error_msg = f"No valid data files could be loaded for HEAD {head_spec}"
            else:
                error_msg = f"No valid data files could be loaded for COMBINED HEADS: {', '.join(head_spec)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
        self.logger.info(f"{'='*60}")


class FRFDataPreprocessor(object):
    """Handles data collection and array building for FRF inference (reused from training)"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.convert_gain_phase = CoordinateConverter()

    def collect_segment_data_for_frequencywise_clustering(self, data_list, filenames, freq_min, freq_max):
        """Collect data organized by files for time series clustering (SAME AS TRAINING)"""
        segment_file_dict = {
            # Will be set from first file
            'frequencies': None,
            'files': {}
        }

        for idx, df in enumerate(data_list):
            segment_mask = (df['frequency'] >= freq_min) & (df['frequency'] <= freq_max)
            segment_frequencies = df[segment_mask].copy()

            # Set frequencies from first file (same for all files)
            if segment_file_dict['frequencies'] is None:
                segment_file_dict['frequencies'] = segment_frequencies['frequency'].values

            real_parts = []
            imag_parts = []

            for _, row in segment_frequencies.iterrows():
                real_part, imag_part = self.convert_gain_phase.gain_phase_to_complex(row['gain'], row['phase'])
                real_parts.append(real_part)
                imag_parts.append(imag_part)

            # Convert to arrays
            real_array = np.array(real_parts)  # 1
            imag_array = np.array(imag_parts)  # 2
            gain_array = segment_frequencies['gain'].values  # 3
            phase_array = segment_frequencies['phase'].values  # 4
            frequency_array = segment_frequencies['frequency'].values

            # Calculate additional features
            mag_gain_array = 10 ** (gain_array / 20)  # 5

            phase_radian_array = np.radians(phase_array)
            cos_phase_array = np.cos(phase_radian_array)  # 6
            sin_phase_array = np.sin(phase_radian_array)  # 7

            unwrapped_phase_array = np.unwrap(phase_radian_array)  # 8

            slope_mag_gain_array = np.gradient(mag_gain_array, frequency_array)  # 9
            slope_unwrapped_phase_array = np.gradient(unwrapped_phase_array, frequency_array)  # 10

            curvature_gain_array = np.gradient(slope_mag_gain_array, frequency_array)  # 11
            curvature_phase_array = np.gradient(slope_unwrapped_phase_array, frequency_array)  # 12
# Signed peak deviation: signal minus its local baseline
            # Positive where signal spikes upward, negative where it dips downward
            # Window size is 10% of segment length, minimum 5 points
            window = max(5, len(mag_gain_array) // 10)
            signed_peak_dev_mag_gain_array = mag_gain_array - uniform_filter1d(mag_gain_array, size=window) # 13
            signed_peak_dev_unwrapped_phase_array = unwrapped_phase_array - \
uniform_filter1d(unwrapped_phase_array, size=window) # 14

            # Window size
            window = 5

            # Moving average of the signal
            mag_moving_avg = uniform_filter1d(mag_gain_array, size=window)
            unwrapped_phase_moving_avg = uniform_filter1d(unwrapped_phase_array, size=window)

            # Shift the moving average by 1 position to get "next window" mean
            # np.roll shifts the array, then we subtract consecutive means
            mag_ma_diff_array = mag_moving_avg - np.roll(mag_moving_avg, 1) # 15
            unwrapped_phase_ma_diff_array = unwrapped_phase_moving_avg - np.roll(unwrapped_phase_moving_avg, 1) # 16

            # Fix the boundary: first element has no previous window, set to 0
            mag_ma_diff_array[0] = 0
            unwrapped_phase_ma_diff_array[0] = 0

            segment_file_dict['files'][idx] = {
                'filename': os.path.basename(filenames[idx]),
                'real': real_array,
                'imaginary': imag_array,
                'gain': gain_array,
                'phase': phase_array,
                'frequency': frequency_array,
                'mag_gain': mag_gain_array,
                'cos_phase': cos_phase_array,
                'sin_phase': sin_phase_array,
                'unwrapped_phase': unwrapped_phase_array,
                'slope_mag_gain': slope_mag_gain_array,
                'slope_unwrapped_phase': slope_unwrapped_phase_array,
                'curvature_gain': curvature_gain_array,
                'curvature_phase': curvature_phase_array,
                'signed_peak_dev_mag_gain': signed_peak_dev_mag_gain_array,
                'signed_peak_dev_unwrapped_phase': signed_peak_dev_unwrapped_phase_array,
                'moving_magnitude': mag_ma_diff_array,
                'moving_unwrapped_phase': unwrapped_phase_ma_diff_array
            }

        return segment_file_dict

    def create_frequencywise_array(self, segment_file_dict, features_list, segment_name="unknown"):
        """Create time series array for inference (SAME AS TRAINING)"""
        n_files = len(segment_file_dict['files'])

        # Get frequency grid from first file
        unique_frequencies = segment_file_dict['frequencies']
        n_frequencies = len(unique_frequencies)

        n_features = len(features_list)

        self.logger.info(f"Creating frequencywise array for segment {segment_name}:")
        self.logger.info(f"  Files: {n_files}")
        self.logger.info(f"  Frequencies: {n_frequencies}")
        self.logger.info(f"  Features: {n_features}: {features_list}")

        # Create time series array: (n_files, n_frequencies, n_features)
        frequencywise_data = np.zeros((n_files, n_frequencies, n_features))
        file_indices = []

        for file_idx, (original_idx, data) in enumerate(segment_file_dict['files'].items()):
            file_indices.append(original_idx)

            # Map features to their corresponding data
            for feature_idx, feature_name in enumerate(features_list):
                frequencywise_data[file_idx, :, feature_idx] = data[feature_name]

        return frequencywise_data, unique_frequencies, file_indices


class PlotExecution(object):
    """Handles plot execution in subprocess"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.plot_timeout = 1200

    def execute_plot_in_process(self, plot_callable, *args, **kwargs):
        """Execute plot generation in separate process with extended timeout"""
        start_time = time.time()
        attempt = 0

        # Force spawn context
        ctx = mp.get_context('spawn')

        while (time.time() - start_time) < self.plot_timeout:
            attempt += 1
            manager = None

            try:
                result = self.attempt_plot_generation(ctx, plot_callable, args, kwargs, attempt)
                return result

            except KeyboardInterrupt:
                self.logger.warning("Plot generation interrupted by user")
                if manager:
                    try:
                        manager.shutdown()
                    except Exception:
                        pass
                raise

            except Exception as e:
                self.logger.warning(f"Plot generation failed (attempt {attempt}): {e}")
                continue

            finally:
                if manager:
                    self.cleanup_manager(manager)

        # Final timeout message
        self.log_final_timeout(start_time, attempt, plot_callable)
        return False, None

    @staticmethod
    def plot_wrapper(queue, plot_callable, args, kwargs):
        """Wrapper function for capturing plot return values in subprocess

        This must be a module-level function (not nested) to be picklable.

        Args:
            queue: Multiprocessing queue for returning results
            plot_callable: The plot function to execute
            args: Positional arguments for plot_callable
            kwargs: Keyword arguments for plot_callable
        """
        try:
            result = plot_callable(*args, **kwargs)
            queue.put(result)
        except Exception as e:
            queue.put(e)

    def attempt_plot_generation(self, ctx, plot_callable, args, kwargs, attempt):
        """Attempt to generate plot in subprocess"""
        manager = ctx.Manager()
        return_queue = manager.Queue()

        process = ctx.Process(target=self.plot_wrapper, args=(return_queue, plot_callable, args, kwargs))
        process.start()

        # Wait with periodic logging
        timeout_per_attempt = 600
        process_completed = self.wait_for_process(process, timeout_per_attempt)

        if not process_completed:
            self.handle_process_timeout(process, attempt, timeout_per_attempt)
            self.cleanup_manager(manager)
            return None

        return self.handle_process_completion(process, return_queue, manager)

    def wait_for_process(self, process, timeout_per_attempt):
        """Wait for process to complete with periodic logging"""
        elapsed = 0
        check_interval = 100

        while elapsed < timeout_per_attempt:
            process.join(timeout=check_interval)
            if not process.is_alive():
                return True
            elapsed += check_interval
            self.logger.info(f"      Plot generation in progress... {elapsed}s elapsed")

        return False

    def handle_process_timeout(self, process, attempt, timeout_per_attempt):
        """Handle process timeout"""
        self.logger.warning(f"Plot timed out after {timeout_per_attempt}s (attempt {attempt})")
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()

    def handle_process_completion(self, process, return_queue, manager):
        """Handle successful process completion"""
        if process.exitcode == 0:
            try:
                return_value = return_queue.get_nowait()
                # Check if return value is an exception
                if isinstance(return_value, Exception):
                    raise return_value
                self.cleanup_manager(manager)
                return True, return_value
            except Exception:
                # No return value (old-style plot functions)
                self.cleanup_manager(manager)
                return True, None
        else:
            raise RuntimeError(f"Plot process failed with exit code {process.exitcode}")

    @staticmethod
    def cleanup_manager(manager):
        """Safely cleanup manager"""
        if manager:
            try:
                manager.shutdown()
            except Exception:
                pass

    def log_final_timeout(self, start_time, attempt, plot_callable):
        """Log final timeout message"""
        elapsed = time.time() - start_time
        self.logger.warning(f"PLOT GENERATION FAILED: Timeout after {elapsed:.1f}s and {attempt} attempts")
        self.logger.warning(f"Plot function: {plot_callable.__name__}")
