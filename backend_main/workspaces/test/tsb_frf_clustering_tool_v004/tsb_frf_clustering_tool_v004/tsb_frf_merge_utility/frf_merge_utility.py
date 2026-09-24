# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Merging Utility Package
*  File Name: frf_merge_utility.py
*  File Description: Standalone utility that merges user-specified clusters of
*                    one or more already-trained models and refines the result
*                    with the bounded forward-pass convergence loop. Produces
*                    merging_results/ (plots + drive-cluster-mapping CSVs),
*                    merging_log/ and models/ (new model.json + centroid files)
*                    under a single timestamped output directory. Self
*                    contained - no dependency on the training application
*                    package.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import sys
import gc
import shutil
import argparse
import logging
from datetime import datetime

from frf_merge_config_loader import MergeConfigLoader, ConfigValidationError, LoggingManager, CleanupManager
from frf_merge_data import (
    DataFileLoader, DataFileLoadError, FeatureEngineer, BaselineSeparator, FeatureScaler,
    load_feature_config, validate_segment_availability,
)
from frf_merge_model import (
    ModelIO, ModelLoadError, MergeGroupBuilder, ForwardPassConverger, MODEL_NAME,
    calculate_cluster_means, count_files_by_source,
)
from frf_merge_plotting import ColorGenerator, PlotExecutor, BodePlotter, FrequencyGridPlotter, \
    ConvergencePlotter, save_drive_cluster_mapping


class OutputDirectories(object):
    """Bundles the three top-level output subdirectories for one merge run."""

    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.merge_results_dir = os.path.join(root_dir, 'merging_results')
        self.merging_log_dir = os.path.join(root_dir, 'merging_log')
        self.models_dir = os.path.join(root_dir, 'models')

    def create(self):
        """Create every subdirectory."""
        for path in (self.merge_results_dir, self.merging_log_dir, self.models_dir):
            os.makedirs(path, exist_ok=True)


class ModelMergePipeline(object):
    """Runs the full merge pipeline for a single trained model: predict, build
    the user-specified merge, refine via the forward-pass convergence loop, and
    write plots/model outputs."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.feature_engineer = FeatureEngineer()
        self.model_io = ModelIO()
        self.merge_builder = MergeGroupBuilder()
        self.converger = ForwardPassConverger()
        self.color_gen = ColorGenerator()
        self.plot_executor = PlotExecutor()
        self.bode_plotter = BodePlotter()
        self.grid_plotter = FrequencyGridPlotter()
        self.convergence_plotter = ConvergencePlotter()

    def run(self, plan_entry, model_id, group_segment_dict,
            features_list, feature_weights, out_dirs):
        """Execute one model's merge job; returns a short summary dict."""
        cluster_groups = plan_entry['cluster_groups']

        frequencywise_data, unique_frequencies, file_indices = self.feature_engineer.build_frequencywise_array(
            group_segment_dict, features_list
        )
        scaled = FeatureScaler.normalize_detrend_and_weight(frequencywise_data, feature_weights, unique_frequencies)

        model = self.model_io.load_model(plan_entry['model_path'])
        k = model.n_clusters
        self._validate_cluster_ids(cluster_groups, k, model_id)
        file_labels = model.predict(scaled)

        cluster_means = calculate_cluster_means(group_segment_dict, file_labels, k, unique_frequencies)
        merge_result = self.merge_builder.build_user_merge_result(cluster_means, file_labels, k, cluster_groups)
        cluster_colors = self.color_gen.get_colors_for_k(merge_result.k_merged)

        merge_results_dir = os.path.join(out_dirs.merge_results_dir, model_id)
        merged_dir = merge_results_dir
        self._write_snapshot(
            merge_result, group_segment_dict, file_indices, unique_frequencies, k,
            merged_dir, model_id, cluster_colors
        )

        final_centers, final_labels, deviations = self._run_forward_pass(
            model, merge_result, file_labels, scaled, unique_frequencies, group_segment_dict,
            file_indices, k, merged_dir, model_id, cluster_colors
        )
        self.convergence_plotter.plot_convergence_curve(
            deviations, merge_result.k_merged, k, merge_results_dir, model_id
        )

        final_means = calculate_cluster_means(
            group_segment_dict, final_labels, merge_result.k_merged, unique_frequencies
        )
        self._save_final_model(
            final_centers, final_means, merge_result.k_merged, model, features_list,
            unique_frequencies, os.path.join(out_dirs.models_dir, model_id)
        )
        return {'model_id': model_id, 'orig_k': k, 'merged_k': merge_result.k_merged, 'passes': len(deviations)}

    @staticmethod
    def _validate_cluster_ids(cluster_groups, k, model_id):
        """Confirm every user-specified cluster id is valid for the loaded model's k."""
        for group in cluster_groups:
            for cluster_id in group:
                if cluster_id >= k:
                    error_msg = (f"clusters_combined for model '{model_id}' references cluster id "
                                 f"{cluster_id}, but the loaded model only has k={k} clusters")
                    raise ConfigValidationError(error_msg)

    def _write_snapshot(self, merge_result, group_segment_dict, file_indices, unique_frequencies,
                         k, merged_dir, model_id, cluster_colors):
        """Write the pre-forward-pass merge snapshot: plot suite + drive-mapping CSV."""
        real_counts, worst_counts = count_files_by_source(
            group_segment_dict, merge_result.merged_labels, merge_result.k_merged
        )
        self.plot_executor.execute_plot_in_process(
            self.bode_plotter.create_static_bode_centroids_grid,
            merge_result.merged_means, unique_frequencies, merge_result.k_merged, cluster_colors,
            merged_dir, model_id, merge_result.merged_labels,
            merge_annotation=merge_result.annotation, pre_merge_k=k,
            real_counts=real_counts, worst_counts=worst_counts,
        )
        self.plot_executor.execute_plot_in_process(
            self.bode_plotter.create_bode_centroid_metrics,
            merge_result.merged_means, unique_frequencies, merge_result.k_merged, cluster_colors,
            merged_dir, model_id, merge_result.merged_labels,
            pre_merge_k=k, merge_annotation=merge_result.annotation,
        )
        self.plot_executor.execute_plot_in_process(
            self.grid_plotter.create_frequency_gain_phase_grid,
            group_segment_dict, merge_result.merged_labels, merged_dir,
            merge_result.k_merged, model_id, cluster_colors=cluster_colors, pre_merge_k=k,
        )
        save_drive_cluster_mapping(
            group_segment_dict, merge_result.merged_labels, file_indices, merged_dir,
            original_k=k, k_merged=merge_result.k_merged
        )

    def _run_forward_pass(self, model, merge_result, pre_merge_file_labels, scaled, unique_frequencies,
                           group_segment_dict, file_indices, k, merged_dir, model_id,
                           cluster_colors):
        """Run the bounded forward-pass loop, writing a plot snapshot every iteration."""
        initial_centers = self.merge_builder.build_merged_feature_centers(
            model.cluster_centers_, merge_result.merge_groups, merge_result.label_map,
            merge_result.k_merged, scaled, pre_merge_file_labels
        )

        def on_iteration(pass_num, new_labels, _new_centers):
            """Write this forward-pass iteration's plot snapshot; the new centroids
            themselves aren't needed here, only the reassigned labels."""
            self._write_iteration_snapshot(
                group_segment_dict, new_labels, unique_frequencies, merge_result.k_merged,
                cluster_colors, merged_dir, model_id, pass_num, file_indices, k
            )

        return self.converger.run(
            initial_centers, scaled, merge_result.merged_labels, merge_result.k_merged,
            model.metric, model.random_state, on_iteration=on_iteration
        )

    def _write_iteration_snapshot(self, group_segment_dict, labels, unique_frequencies, k_merged,
                                   cluster_colors, merged_dir, model_id, pass_num,
                                   file_indices, original_k):
        """Write one forward-pass iteration's plot suite + drive-mapping CSV."""
        iter_dir = os.path.join(merged_dir, 'iterations', f'iter_{pass_num:02d}')
        iter_means = calculate_cluster_means(group_segment_dict, labels, k_merged, unique_frequencies)
        real_counts, worst_counts = count_files_by_source(group_segment_dict, labels, k_merged)

        self.plot_executor.execute_plot_in_process(
            self.bode_plotter.create_static_bode_centroids_grid,
            iter_means, unique_frequencies, k_merged, cluster_colors, iter_dir,
            model_id, labels, pre_merge_k=original_k, real_counts=real_counts, worst_counts=worst_counts,
        )
        self.plot_executor.execute_plot_in_process(
            self.bode_plotter.create_bode_centroid_metrics,
            iter_means, unique_frequencies, k_merged, cluster_colors, iter_dir,
            model_id, labels, pre_merge_k=original_k,
        )
        self.plot_executor.execute_plot_in_process(
            self.grid_plotter.create_frequency_gain_phase_grid,
            group_segment_dict, labels, iter_dir, k_merged, model_id,
            cluster_colors=cluster_colors, pre_merge_k=original_k,
        )
        save_drive_cluster_mapping(
            group_segment_dict, labels, file_indices, iter_dir,
            original_k=original_k, k_merged=k_merged
        )

    def _save_final_model(self, final_centers, final_means, k_merged, model, features_list,
                           unique_frequencies, model_out_dir):
        """Persist the converged model.json and both centroid-data-file formats."""
        os.makedirs(model_out_dir, exist_ok=True)
        self.model_io.save_model(
            final_centers, k_merged, model.metric, model.random_state,
            os.path.join(model_out_dir, MODEL_NAME)
        )
        self.model_io.save_centroid_data_files(final_means, model_out_dir, unique_frequencies, k_merged)
        self.model_io.save_model_centroid_data_files(
            final_centers, model_out_dir, unique_frequencies, k_merged, features_list
        )


class FRFMergingApplication(object):
    """Top-level orchestrator: loads config/data, resolves baseline groups and
    model identifiers, and runs the merge pipeline for every planned model."""

    def __init__(self):
        self.config_loader = MergeConfigLoader()
        self.data_loader = DataFileLoader()
        self.feature_engineer = FeatureEngineer()
        self.baseline_separator = BaselineSeparator()
        self.pipeline = ModelMergePipeline()
        self.cleanup_manager = CleanupManager()

    def run(self, config_path):
        """Main entry point: validate config, prepare data once, process every
        planned model, and report where results were written."""
        config = self._load_config(config_path)
        out_dirs = self._setup_output(config)
        logger, log_file = LoggingManager.setup_logging(out_dirs.merging_log_dir)

        try:
            self._execute(config, out_dirs, logger)
        except Exception as e:
            logger.error(f"FATAL ERROR during merge run: {e}")
            raise
        finally:
            gc.collect()

        self.cleanup_manager.cleanup_pycache()

        logger.info("=" * 100)
        logger.info("FRF MERGING UTILITY RUN COMPLETE")
        logger.info(f"Results saved in: {out_dirs.root_dir}")
        logger.info(f"Log file saved at: {log_file}")
        logger.info("=" * 100)

    def _load_config(self, config_path):
        """Load and validate the merge config, exiting cleanly on failure."""
        try:
            return self.config_loader.load_config(config_path)
        except (ConfigValidationError, FileNotFoundError) as e:
            print(f"CONFIG VALIDATION ERROR: {e}")
            sys.exit(1)

    @staticmethod
    def _setup_output(config):
        """Create the timestamped output directory tree."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root_dir = os.path.join(config['output_path'], f'frf_merging_results_{timestamp}')
        out_dirs = OutputDirectories(root_dir)
        out_dirs.create()
        return out_dirs

    def _execute(self, config, out_dirs, logger):
        """Load data once, resolve groups/model ids, then run every planned model."""
        freq_min, freq_max = config['frequency_segment']
        data_list, filenames, num_real_files = self._load_all_data(config, logger)
        validate_segment_availability(data_list, freq_min, freq_max)

        combined_dict = self.feature_engineer.build_segment_file_dict(
            data_list, filenames, freq_min, freq_max, num_real_files=num_real_files
        )
        all_file_indices = list(combined_dict['files'].keys())

        features_list, feature_weights = load_feature_config(config['feature_config'])
        self._write_feature_config_copy(config['feature_config'], out_dirs.models_dir)

        groups = self._resolve_groups(config, combined_dict, all_file_indices, logger)

        for plan_entry in config['merge_plan']:
            model_id = plan_entry['name']
            self._run_one_plan_entry(plan_entry, model_id, groups, features_list, feature_weights,
                                      out_dirs, logger)

    def _load_all_data(self, config, logger):
        """Load data_dir_list (+ optional worst_model_dir_list) into one combined list,
        data_dir files first so num_real_files marks the worst-model boundary."""
        try:
            data_list, filenames = self.data_loader.load_file_list(config['data_dir_list'])
        except DataFileLoadError as e:
            logger.error(str(e))
            raise
        num_real_files = len(data_list)

        if config['worst_model_dir_list']:
            worst_data, worst_filenames = self.data_loader.load_file_list(
                config['worst_model_dir_list'], is_worst_model=True
            )
            data_list += worst_data
            filenames += worst_filenames
            logger.info(f"Combined dataset: {num_real_files} real + {len(worst_data)} worst-model files")
        else:
            num_real_files = None
            logger.info(f"Dataset: {len(data_list)} file(s) (no worst_model_dir_list)")

        return data_list, filenames, num_real_files

    @staticmethod
    def _write_feature_config_copy(feature_config_path, models_dir):
        """Copy the source feature_config.json verbatim into models/."""
        shutil.copy(feature_config_path, os.path.join(models_dir, 'feature_config.json'))

    def _resolve_groups(self, config, combined_dict, all_file_indices, logger):
        """Resolve baseline groups (or a single implicit group) into
        {group_label: (group_segment_dict, group_file_indices)}."""
        if not config['baseline_data_separation']:
            return {None: (combined_dict, all_file_indices)}

        baseline_data_filtering = self._distinct_baseline_groups(config['merge_plan'])
        classified = self.baseline_separator.classify_files(combined_dict, all_file_indices)
        applied = self.baseline_separator.apply_combination(classified, baseline_data_filtering)
        groups = {}
        for label, indices_subset in applied.items():
            group_dict, group_indices = self.baseline_separator.build_group_segment_dict(
                combined_dict, indices_subset
            )
            groups[label] = (group_dict, group_indices)
        logger.info(f"Resolved baseline groups: {list(groups.keys())}")
        return groups

    @staticmethod
    def _distinct_baseline_groups(merge_plan):
        """Deduplicated, order-preserved list of raw baseline_group values (string
        or tuple) referenced across merge_models, for BaselineSeparator.apply_combination.
        Multiple merge_models entries may legitimately share the same baseline_group,
        so only the distinct groups need their data subset built once."""
        seen = set()
        ordered = []
        for entry in merge_plan:
            group = entry['baseline_group']
            if group not in seen:
                seen.add(group)
                ordered.append(group)
        return ordered

    def _run_one_plan_entry(self, plan_entry, model_id, groups, features_list, feature_weights,
                             out_dirs, logger):
        """Run the merge pipeline for one planned model, tolerating a missing/empty group."""
        group_label = plan_entry['group_label']
        if group_label not in groups:
            logger.warning(f"Skipping model '{model_id}': baseline group '{group_label}' is empty")
            return
        group_segment_dict, _ = groups[group_label]
        logger.info(f"Processing model '{model_id}' (group={group_label}, path={plan_entry['model_path']})")
        try:
            summary = self.pipeline.run(
                plan_entry, model_id, group_segment_dict,
                features_list, feature_weights, out_dirs
            )
            logger.info(
                f"Completed model '{model_id}': k={summary['orig_k']} -> "
                f"merged_k={summary['merged_k']} in {summary['passes']} forward pass(es)"
            )
        except ModelLoadError as e:
            logger.error(f"Skipping model '{model_id}': {e}")
        gc.collect()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="FRF Cluster Merging Utility - merge user-specified clusters and re-converge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
USAGE EXAMPLES:
===============================================================================
Basic usage:
  python frf_merge_utility.py --config merge_config.cfg
View this help:
  python frf_merge_utility.py --help
        """
    )
    parser.add_argument(
        '--config', type=str, required=True, metavar='CONFIG_FILE',
        help='Path to configuration file (.cfg) containing merge parameters'
    )
    args = parser.parse_args()

    app = FRFMergingApplication()
    app.run(args.config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger(__name__).warning("Merge run interrupted by user (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        logging.getLogger(__name__).error(f"FATAL ERROR: {e}")
        sys.exit(1)
