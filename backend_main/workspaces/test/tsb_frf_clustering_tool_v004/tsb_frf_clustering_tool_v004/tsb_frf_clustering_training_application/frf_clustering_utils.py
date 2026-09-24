# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_clustering_utils.py
*  File Description: Utility file for the Clustering engine.
*  All rights reserved.
*
*********************************************************************/
"""
import time
import multiprocessing as mp
import json
import os
import logging
import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from sklearn.model_selection import train_test_split
from tslearn.clustering import TimeSeriesKMeans
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import colorsys
from frf_metric_components import CoordinateConverter, CurveProcessor
from datetime import datetime


class MergeContext(object):
    """Bundles the head/segment/dataset identity, original (pre-merge) k, and the
    output/merged directories shared across the centroid-merge pipeline."""

    def __init__(self, head_name, segment_name, dataset_type, k=None,
                 output_dir=None, merged_dir=None):
        self.head_name = head_name
        self.segment_name = segment_name
        self.dataset_type = dataset_type
        self.k = k
        self.output_dir = output_dir
        self.merged_dir = merged_dir


class MergeFileData(object):
    """Bundles the per-file data shared across the centroid-merge pipeline."""

    def __init__(self, segment_file_dict, unique_frequencies, file_indices):
        self.segment_file_dict = segment_file_dict
        self.unique_frequencies = unique_frequencies
        self.file_indices = file_indices


class MergeModelSettings(object):
    """Bundles the TimeSeriesKMeans metric/random_state used to rebuild merged models."""

    def __init__(self, model_metric='euclidean', model_random_state=0):
        self.model_metric = model_metric
        self.model_random_state = model_random_state


class FrequencywiseNormData(object):
    """Bundles a frequencywise data array together with its normalization statistics."""

    def __init__(self, freq_data, freq_scaled):
        self.freq_data = freq_data
        self.freq_scaled = freq_scaled


class ClusteringOutputOptions(object):
    """Fflags that control output generation for a clustering run."""

    def __init__(self, individual_frequencies_cluster_assignment_plots=False,
                 generate_segment_overview=True, output_dir_is_final=False,
                 group_label=None, generate_interactive_html_plots=True):
        self.individual_frequencies_cluster_assignment_plots = individual_frequencies_cluster_assignment_plots
        self.generate_segment_overview = generate_segment_overview
        self.output_dir_is_final = output_dir_is_final
        self.group_label = group_label
        self.generate_interactive_html_plots = generate_interactive_html_plots


class HierarchicalRunAccumulators(object):
    """Bundles the mutable accumulators threaded through hierarchical clustering
    across all stage-1 k values."""

    def __init__(self):
        self.hierarchical_entries = []
        self.centroid_scores = {}
        self.merge_outcomes = {}


class StageCombination(object):
    """Bundles the stage1_k, stage2_k, and their product (total_clusters) for one
    hierarchical combination."""

    def __init__(self, parent_k, stage2_k, total_clusters):
        self.parent_k = parent_k
        self.stage2_k = stage2_k
        self.total_clusters = total_clusters


class SharedStage2Data(object):
    """Bundles the shared (segment-wide) stage-2 scaled feature array with its
    original-index-to-row mapping."""

    def __init__(self, shared_scaled_s2, orig_to_row_s2):
        self.shared_scaled_s2 = shared_scaled_s2
        self.orig_to_row_s2 = orig_to_row_s2


class NormalRunAccumulators(object):
    """Bundles the mutable accumulators threaded through flat (single-stage)
    clustering across all k values."""

    def __init__(self, k1_baseline=None):
        self.clustering_results = {'k1_baseline': k1_baseline}
        self.segment_aci_scores = {}
        self.trained_models = {}
        self.centroid_scores = {}
        self.merge_outcomes = {}


class FrequencyClusteringConfig(object):
    """Configuration for frequency-wise clustering operations"""

    def __init__(self, segment_name, segment_dir, models_base_dir, head_name,
                 freq_min, freq_max, feature_weights, dataset_type='train',
                 pretrained_models=None, target_k=None, metrics_to_use=None,
                 output_options=None, features_list=None):
        self.segment_name = segment_name
        self.segment_dir = segment_dir
        self.models_base_dir = models_base_dir
        self.head_name = head_name
        self.freq_min = freq_min
        self.freq_max = freq_max
        self.feature_weights = feature_weights
        self.dataset_type = dataset_type
        self.pretrained_models = pretrained_models
        self.target_k = target_k
        self.metrics_to_use = metrics_to_use if metrics_to_use is not None else ['ACI1', 'ACI2', 'ACI3', 'ACI4']
        self.features_list = features_list

        opts = output_options if output_options is not None else ClusteringOutputOptions()
        self.individual_frequencies_cluster_assignment_plots = opts.individual_frequencies_cluster_assignment_plots
        self.generate_segment_overview = opts.generate_segment_overview
        self.output_dir_is_final = opts.output_dir_is_final
        self.group_label = opts.group_label
        self.generate_interactive_html_plots = opts.generate_interactive_html_plots


class FrequencyACIMetricsConfig(object):
    """Configuration for frequency ACI metrics calculation"""

    def __init__(self, k_dir, segment_name, head_name, metrics_to_use=None,
                 individual_frequencies_cluster_assignment_plots=False, cluster_colors=None):
        self.k_dir = k_dir
        self.segment_name = segment_name
        self.head_name = head_name
        self.metrics_to_use = metrics_to_use if metrics_to_use is not None else ['ACI1', 'ACI2', 'ACI3', 'ACI4']
        self.individual_frequencies_cluster_assignment_plots = individual_frequencies_cluster_assignment_plots
        self.cluster_colors = cluster_colors


class FRFDataPreprocessor(object):
    """Handles data splitting, collection, and array building for FRF analysis"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.convert_gain_phase = CoordinateConverter()

    def split_train_validation(self, data_list, filenames, validation_size=0.2, random_state=42):
        """Split data into training and validation split"""
        total_files = len(data_list)

        # Special case: validation_size = 0 means use all data for training
        if validation_size == 0 or validation_size == 0.0:
            self.logger.info(f"--- Data Split Summary ---")
            self.logger.info(f"  Total files: {total_files}")
            self.logger.info(f"  Training set: {total_files} files (100%)")
            self.logger.info(f"  Validation set: 0 files (0%)")
            self.logger.info(f"  Note: All data will be used for training only")

            # Return all data as training, empty lists for validation
            return data_list, filenames, [], []

        indices = list(range(len(data_list)))

        try:
            train_idx, validation_idx = train_test_split(
                indices, test_size=validation_size, random_state=random_state, shuffle=True
            )
        except Exception:
            error = f"Error during train-validation split"
            self.logger.error(error)
            raise RuntimeError(error)

        train_data = [data_list[idx] for idx in train_idx]
        train_filenames = [filenames[idx] for idx in train_idx]

        validation_data = [data_list[idx] for idx in validation_idx]
        validation_filenames = [filenames[idx] for idx in validation_idx]

        self.logger.info(f"--- Data Split Summary ---")
        self.logger.info(f"  Total files: {total_files}")
        self.logger.info(f"  Training set: {len(train_data)} files")
        self.logger.info(f"  Validation set: {len(validation_data)} files")

        return train_data, train_filenames, validation_data, validation_filenames

    def collect_segment_data_for_frequencywise_clustering(self, data_list, filenames, freq_min, freq_max,
                                                            num_real_files=None):
        """Collect data organized by files for time series clustering"""
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

            # 11 FEATURES
            # (1) real, (2) imaginary (3) gain (4) phase(rad) (5) mag of gain
            # (6) cos(phase) (7) sin(phase) (8) unwrapped phase (9) slope of gain (10) slope of phase

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

            curvature_gain_array = np.gradient(slope_mag_gain_array, frequency_array) # 11
            curvature_phase_array = np.gradient(slope_unwrapped_phase_array, frequency_array) # 12

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

            # First element has no previous window, set to 0
            mag_ma_diff_array[0] = 0
            unwrapped_phase_ma_diff_array[0] = 0

            segment_file_dict['files'][idx] = {
                'filename': os.path.basename(filenames[idx]),
                'is_worst_model': num_real_files is not None and idx >= num_real_files,
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
        """Create time series array for TimeSeriesKMeans"""
        n_files = len(segment_file_dict['files'])

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


class ModelManager(object):
    """Handles model saving and loading operations"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def save_model(model, path, format='json'):
        """Save TimeSeriesKMeans model in JSON format"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if format == 'json':
            model_json = {
                'n_clusters': model.n_clusters,
                'metric': model.metric,
                'random_state': model.random_state,
                'cluster_centers_': model.cluster_centers_.tolist()
            }
            with open(path, 'w', encoding='utf-8-sig') as f:
                json.dump(model_json, f)
        else:
            raise ValueError("Unsupported model format: use 'json'")

    def load_model(self, path, format='json'):
        """Load TimeSeriesKMeans model from JSON with Validation"""
        if not os.path.exists(path):
            error_msg = f"Model file not found: {path}"
            self.logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        if os.path.getsize(path) == 0:
            error_msg = f"Model file is empty: {path}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        if format == 'json':
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    model_json = json.load(f)

                # Validate required fields
                required_fields = ['n_clusters', 'cluster_centers_']
                missing_fields = [f for f in required_fields if f not in model_json]

                if missing_fields:
                    error_msg = f"Model file missing required fields: {missing_fields}"
                    self.logger.error(error_msg)
                    raise ValueError(error_msg)

                # Validate cluster centers shape
                centers = np.array(model_json['cluster_centers_'])
                expected_k = model_json['n_clusters']

                # Check for NaN or Inf in cluster centers
                if np.any(np.isnan(centers)) or np.any(np.isinf(centers)):
                    error_msg = "Cluster centers contain NaN or Inf values"
                    self.logger.error(error_msg)
                    raise ValueError(error_msg)

                km = TimeSeriesKMeans(
                    n_clusters=model_json['n_clusters'],
                    metric=model_json.get('metric', 'euclidean'),
                    random_state=model_json.get('random_state', 0)
                )
                km.cluster_centers_ = centers

                self.logger.info(f"  Successfully loaded model: k={expected_k}, centers_shape={centers.shape}")
                return km

            except Exception:
                self.logger.error(f"Error loading model from {path}")
                raise
        else:
            raise ValueError("Unsupported model format: use 'json'")

    def save_centroid_data_files(self, cluster_means, segment_models_dir, frequencies, k):
        """Save centroid data files - one file per cluster using per-cluster mean real/imag values.

        Each file contains:
        - 9-line header (matching reference file format)
        - Data lines: frequency,centroid_gain,centroid_phase (one line per frequency)
        - END marker

        Args:
            cluster_means: Per-cluster mean real/imag coordinates (shape: k, n_frequencies, 2)
                           where [..., 0] = mean real and [..., 1] = mean imag
            segment_models_dir: Directory to save centroid files
            frequencies: Array of frequency values for the segment
            k: Number of clusters
        """
        try:
            # Create one file for each cluster mean
            for cluster_id in range(k):
                centroid_file_path = os.path.join(segment_models_dir, f'bode_centroid_{cluster_id}.txt')
                timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

                # Prepare header (9 lines)
                header_lines = [
                    f"{timestamp}\n",
                    "3\n",
                    "3\n",
                    "Frequency [Hz]\n",
                    "Centroid Gain [dB]\n",
                    "Centroid Phase[deg]\n",
                    "Caption 1\n",
                    "Caption 2\n",
                    "Caption 3\n"
                ]

                # Write file
                with open(centroid_file_path, 'w', encoding='utf-8-sig') as f:
                    f.writelines(header_lines)

                    for freq_idx, frequency in enumerate(frequencies):
                        real_part = cluster_means[cluster_id, freq_idx, 0]
                        imag_part = cluster_means[cluster_id, freq_idx, 1]

                        magnitude = np.sqrt(real_part**2 + imag_part**2)
                        gain_db = 20 * np.log10(magnitude) if magnitude > 0 else -np.inf
                        phase_deg = np.degrees(np.arctan2(imag_part, real_part))

                        f.write(f"{frequency:.2f},{gain_db:.6f},{phase_deg:.6f}\n")

                    f.write("END\n")

                self.logger.info(f"      Saved bode centroid file: bode_centroid_{cluster_id}.txt \
({len(frequencies)} frequencies)")

        except Exception as e:
            self.logger.error(f"Error saving centroid data files: {e}")
            raise

    def save_model_centroid_data_files(self, cluster_centers, segment_models_dir,
                                        frequencies, k, features_list):
        """Save model-space centroid data files - one file per cluster using the
        normalized feature-space centroid values exactly as stored in model.json.

        Each file contains:
        - Header: timestamp, fixed "3", column count (1 + n_features), column names
          (Frequency [Hz] + each feature name), then one caption per column
        - Data lines: frequency,feature_1,feature_2,...,feature_n (one line per frequency)
        - END marker"""
        try:
            n_features = len(features_list)
            n_columns = 1 + n_features

            # Create one file for each cluster center
            for cluster_id in range(k):
                centroid_file_path = os.path.join(
                    segment_models_dir, f'model_centroid_{cluster_id}.txt'
                )
                timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

                # Prepare header
                header_lines = [f"{timestamp}\n", "3\n", f"{n_columns}\n", "Frequency [Hz]\n"]
                header_lines += [f"{feature_name}\n" for feature_name in features_list]
                header_lines += [f"Caption {i}\n" for i in range(1, n_columns + 1)]

                # Write file
                with open(centroid_file_path, 'w', encoding='utf-8-sig') as f:
                    f.writelines(header_lines)

                    for freq_idx, frequency in enumerate(frequencies):
                        feature_values = cluster_centers[cluster_id, freq_idx, :]
                        values_str = ",".join(f"{value:.6f}" for value in feature_values)
                        f.write(f"{frequency:.2f},{values_str}\n")

                    f.write("END\n")

                self.logger.info(f"      Saved model centroid file: model_centroid_{cluster_id}.txt \
({len(frequencies)} frequencies)")

        except Exception as e:
            self.logger.error(f"Error saving model centroid data files: {e}")
            raise


class ColorGenerator(object):
    """Generates distinct colors for visualization"""

    def __init__(self):
        # Fixed 10-color palette for k values 1-10 (using tab10 colormap) — Stage 1 / normal mode
        self.FIXED_CLUSTER_COLORS = plt.cm.tab10(np.linspace(0, 1, 10))
        # Fixed 10-color palette for Stage 2 sub-clustering (using Set2 colormap — softer pastel tones)
        self.FIXED_STAGE2_COLORS = plt.cm.Set2(np.linspace(0, 1, 8))

    def get_cluster_colors(self, k):
        """Get fixed colors for k clusters (max 10) — Stage 1 / normal mode uses tab10.
        Returns colors for clusters 0 to k-1 from the fixed palette.
        """
        if k > 10:
            raise ValueError(f"k={k} exceeds maximum of 10 clusters")
        return self.FIXED_CLUSTER_COLORS[:k]

    def get_stage2_cluster_colors(self, k):
        """Get fixed colors for k clusters in Stage 2 sub-clustering — uses Set2 palette (max 8).
        Returns colors for clusters 0 to k-1 from the Set2 palette.
        """
        if k > 8:
            # Fall back to generate_distinct_colors for k > 8
            return self.generate_distinct_colors(k)
        return self.FIXED_STAGE2_COLORS[:k]

    @staticmethod
    def generate_distinct_colors(n):
        """Generate n visually distinct colors using HSV color space
        For backward compatibility with non-cluster plots.
        """
        if n <= 10:
            colors = plt.cm.tab10(np.linspace(0, 1, n))
        elif n <= 20:
            colors = plt.cm.tab20(np.linspace(0, 1, n))
        else:
            # Golden-ratio hue spacing gives even distribution across many colors.
            golden_ratio = (1 + 5**0.5) / 2
            hues = [(i * golden_ratio) % 1.0 for i in range(n)]

            sat_levels = (0.55, 0.65, 0.75)
            value_levels = (0.72, 0.82, 0.92)

            colors = []
            for i, hue in enumerate(hues):
                sat = sat_levels[i % 3]
                light = value_levels[(i + 1) % 3]

                rgb = colorsys.hsv_to_rgb(hue, sat, light)
                colors.append(rgb)

            colors = np.array(colors)

        return colors


class PlotExecutor(object):
    """Handles execution of plot generation in separate process with timeout"""

    def __init__(self):
        self.plot_timeout = 1200
        self.logger = logging.getLogger(__name__)

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
            return False, None

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


class FeatureConfigManager(object):
    """Handles saving and loading of feature configuration"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def save_feature_config(self, features_list, feature_weights, path,
                            stage1_features=None, stage1_weights=None,
                            stage2_features=None, stage2_weights=None):
        """Save feature configuration to JSON format.

        In normal (non-hierarchical) mode, saves only:
            'training_application_stage1_features' and
            'training_application_stage1_features_weightages'.

        In hierarchical mode, saves all four stage keys:
            'training_application_stage1_features',
            'training_application_stage1_features_weightages',
            'training_application_stage2_features',
            'training_application_stage2_features_weightages'.

        The generic 'features' and 'feature_weights' top-level keys are intentionally
        omitted — all consumers must use the stage-specific keys.
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)

        if stage1_features is not None:
            # Hierarchical mode — write all four stage keys
            feature_config = {
                'training_application_stage1_features': stage1_features,
                'training_application_stage1_features_weightages': stage1_weights,
                'training_application_stage2_features': stage2_features,
                'training_application_stage2_features_weightages': stage2_weights,
            }
        else:
            # Non-hierarchical mode — write stage1 keys only
            feature_config = {
                'training_application_stage1_features': features_list,
                'training_application_stage1_features_weightages': feature_weights,
            }

        with open(path, 'w', encoding='utf-8-sig') as f:
            json.dump(feature_config, f, indent=2)
        self.logger.info(f"Saved feature configuration: {path}")

    def load_feature_config(self, path):
        """Load feature configuration from JSON format"""
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                feature_config = json.load(f)

            features_list = feature_config['training_application_stage1_features']
            feature_weights = feature_config['training_application_stage1_features_weightages']

            self.logger.info(f"Loaded feature configuration: {path}")
            return features_list, feature_weights

        except Exception:
            self.logger.error(f"Error loading feature configuration from {path}")
            raise


class BaselineSeparator(object):
    """Handles baseline computation and file separation into phase_lead/phase_lag/no_resonance groups"""
    LESS_RESONANCE_BAND = 0.25

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.curve_processor = CurveProcessor()

    @staticmethod
    def _dominant_peak_value(curve):
        """Return the signed extremum of the curve that deviates furthest from zero."""
        max_value = float(np.max(curve))
        min_value = float(np.min(curve))
        if abs(min_value) > abs(max_value):
            return min_value
        return max_value

    def classify_files(self, segment_file_dict, file_indices):
        """Classify each file as phase_lead, phase_lag, or no_resonance using its normalized+detrended dominant peak

        Args:
            segment_file_dict: dict with 'frequencies' and 'files' keys
            file_indices: list of original file indices

        Returns:
            classified: dict with keys 'phase_lead', 'phase_lag', 'no_resonance',
                        each containing a list of original file indices
        """
        classified = {'phase_lead': [], 'phase_lag': [], 'no_resonance': []}
        frequencies = segment_file_dict['frequencies']

        for original_file_idx in file_indices:
            data = segment_file_dict['files'][original_file_idx]
            phase_values = data['phase']

            normalized = self.curve_processor.normalize_curve_to_range(phase_values)
            normalized_detrended = self.curve_processor.detrend_curve(normalized, frequencies)
            peak_value = self._dominant_peak_value(normalized_detrended)

            if abs(peak_value) <= self.LESS_RESONANCE_BAND:
                classified['no_resonance'].append(original_file_idx)
            elif peak_value > 0.0:
                classified['phase_lead'].append(original_file_idx)
            else:
                classified['phase_lag'].append(original_file_idx)

        self.logger.info(f"  Classification results (no-resonance band=+/-{self.LESS_RESONANCE_BAND}):")
        self.logger.info(f"    Phase Lead   : {len(classified['phase_lead'])} files")
        self.logger.info(f"    Phase Lag    : {len(classified['phase_lag'])} files")
        self.logger.info(f"    No Resonance : {len(classified['no_resonance'])} files")

        return classified

    def apply_combination(self, classified, combination_config):
        """Merge classified groups according to baseline_data_filtering config"""
        groups = {}

        for item in combination_config:
            if isinstance(item, str):
                group_files = classified.get(item, [])
                if len(group_files) == 0 and item == 'no_resonance':
                    self.logger.warning(f"Skipping empty group: '{item}'")
                    continue
                groups[item] = group_files

            elif isinstance(item, list):
                label = '_'.join(item)
                combined_files = []
                for group_name in item:
                    combined_files.extend(classified.get(group_name, []))
                if len(combined_files) == 0:
                    self.logger.warning(f"Combined group '{label}' is empty, skipping.")
                    continue
                groups[label] = combined_files

        return groups

    @staticmethod
    def build_group_segment_dict(segment_file_dict, original_file_indices_subset):
        """Build a subset segment_file_dict for a specific group

        Args:
            segment_file_dict: full segment dict
            original_file_indices_subset: list of original file indices belonging to this group

        Returns:
            group_segment_dict: new segment_file_dict re-indexed from 0
            group_file_indices: list of new sequential indices (0, 1, 2, ...)
        """
        group_segment_dict = {
            'frequencies': segment_file_dict['frequencies'],
            'files': {}
        }
        group_file_indices = []

        for new_idx, original_file_idx in enumerate(original_file_indices_subset):
            group_segment_dict['files'][new_idx] = segment_file_dict['files'][original_file_idx]
            group_file_indices.append(new_idx)

        return group_segment_dict, group_file_indices
