# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Training Application Package
*  File Name: frf_training_application.py
*  File Description: Main file that clusters frf hard disk data.
*  All rights reserved.
*
*********************************************************************/
"""

import os
import sys
import gc
import warnings
import json
import argparse
import logging
from datetime import datetime
from frf_clustering_utils import FRFDataPreprocessor
from frf_clustering_utils import FeatureConfigManager
from frf_clustering_utils import ClusteringOutputOptions
from frf_config_loader import ConfigLoader
from frf_utils import FrequencySegmentAvailabilityChecker, SegmentSummaryGenerator, BaselineOptions
from frf_utils import LoggingManager, DataFileLoader, ModelRegistryGenerator, CleanupManager
from frf_utils import SegmentModelsContext
from frf_output_config import OutputConfigGenerator
from frf_training_application_processors import SegmentProcessor, HierarchicalSegmentProcessor

warnings.filterwarnings('ignore')


class HeadProcessor(object):
    """Processes a single head or combined heads"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.data_loader = DataFileLoader()
        self.segmentprocessor = SegmentProcessor()
        self.hierarchical_processor = HierarchicalSegmentProcessor()
        self.summary_generator = SegmentSummaryGenerator()
        self.preprocessor = FRFDataPreprocessor()
        self.segment_checker = FrequencySegmentAvailabilityChecker()
        self.feature_config_manager = FeatureConfigManager()

    def process_head(self, head_spec, config, frf_clustering_analysis_dir):
        """Process a single head or combined heads using configuration
        Args:
            head_spec: Either a string (single head) or list of strings (combined heads)
            config: Configuration dictionary
            frf_clustering_analysis_dir: Pre-created analysis directory with timestamp
        """
        # Generate head name and log
        head_name, log_head_name = self._generate_head_names(head_spec)

        self._log_head_processing_header(log_head_name)

        # Setup directories
        head_output_dir, models_base_dir = self._setup_head_directories(
            frf_clustering_analysis_dir, head_name
        )

        try:
            # Load and validate data
            data_list, filenames = self._load_and_validate_head_data(
                head_spec, config['data_dir_list'], head_name
            )

            # Split data
            train_data, train_filenames, validation_data, validation_filenames, \
            train_worst, train_worst_filenames, validation_worst, validation_worst_filenames = \
            self._split_all_data(
                data_list, filenames, config
            )

            # Combine training data
            train_data_combined, train_filenames_combined = self._combine_training_data(
                train_data, train_filenames, train_worst, train_worst_filenames, config
            )

            # Save split info
            self._save_split_info(
                head_output_dir, head_name, data_list, train_data, validation_data,
                train_filenames, validation_filenames, train_worst, validation_worst,
                train_worst_filenames, validation_worst_filenames, config
            )

            # Check frequency segments
            valid_segments_train = self._check_frequency_segments(
                train_data_combined, config['frequency_segments']
            )

            # Process training set
            train_summaries, train_model_registry, train_optimal_k_info, \
                train_merged_registry = self._process_training_set(
                    train_data_combined, train_filenames_combined, valid_segments_train,
                    head_output_dir, models_base_dir, head_name, config,
                    num_real_files=len(train_data)
                )

            # Initialize consolidated summaries
            all_summaries_consolidated = list(train_summaries) if train_summaries else []

            self._process_validation_sets(
                validation_data, validation_filenames, validation_worst, validation_worst_filenames,
                config, head_output_dir, models_base_dir, head_name, all_summaries_consolidated
            )

            # Generate final summary
            if all_summaries_consolidated:
                self.summary_generator.generate_final_segment_summary(
                    all_summaries_consolidated, head_output_dir, config['metric'], head_name
                )
                self.logger.info(f"Generated consolidated final segment summary for all dataset types")

            # Save feature config
            self._save_feature_config(models_base_dir, config)

            self.logger.info("="*60)
            self.logger.info(f"Completed processing for HEAD {head_name}")
            self.logger.info("="*60)

            # Cleanup
            self._cleanup_head_data(
                data_list, filenames, train_data, train_filenames, validation_data, validation_filenames,
                train_worst, train_worst_filenames, validation_worst, validation_worst_filenames,
                train_data_combined, train_filenames_combined, config
            )

            return train_model_registry, train_optimal_k_info, train_merged_registry

        except Exception as e:
            self.logger.error(f"Error during processing for HEAD {head_name}: {e}")
            return [], [], []

    def _generate_head_names(self, head_spec):
        """Generate head name for directories and logging"""
        if isinstance(head_spec, str):
            head_name = head_spec
            log_head_name = head_name
            return head_name, log_head_name
        if isinstance(head_spec, list):
            head_name = self._build_combined_head_name(head_spec)
            log_head_name = f"COMBINED HEADS: {', '.join(sorted(head_spec))}"
            return head_name, log_head_name

        error_msg = f"head_spec must be a string or list, got {type(head_spec).__name__}"
        self.logger.error(error_msg)
        raise TypeError(error_msg)

    def _build_combined_head_name(self, head_spec):
        """Build the output head name for a combined-heads group"""
        keywords_used = getattr(head_spec, 'keywords', [])
        if not keywords_used:
            transformed_codes = [self._transform_head_code(h) for h in sorted(head_spec)]
            return f"HD_{''.join(transformed_codes)}"

        shortened_keywords = [self._shorten_keyword_for_naming(k) for k in sorted(keywords_used)]
        head_name = '_'.join(shortened_keywords)
        literal_heads = getattr(head_spec, 'literal_heads', [])
        if literal_heads:
            extra_codes = [self._transform_head_code(h) for h in sorted(literal_heads)]
            head_name = f"{head_name}_{''.join(extra_codes)}"
        return head_name

    @staticmethod
    def _shorten_keyword_for_naming(keyword):
        """Shorten '_heads' to '_hds' in keyword-derived output names"""
        return keyword.replace('_heads', '_hds')

    @staticmethod
    def _transform_head_code(head):
        """Transform head name: HD0->00, HD15->15, HDA->0A"""
        code = head[2:]
        if len(code) == 1:
            return '0' + code
        else:
            return code

    def _log_head_processing_header(self, log_head_name):
        """Log head processing header"""
        self.logger.info("="*100)
        self.logger.info("FRF CLUSTERING ANALYSIS STARTED")
        self.logger.info(f"HEAD NAME: {log_head_name}")
        self.logger.info("="*100)

    @staticmethod
    def _setup_head_directories(frf_clustering_analysis_dir, head_name):
        """Setup directories for head processing"""
        head_output_dir = os.path.join(frf_clustering_analysis_dir, f'HEAD_{head_name}')
        models_base_dir = os.path.join(frf_clustering_analysis_dir, 'trained_models')
        os.makedirs(head_output_dir, exist_ok=True)
        return head_output_dir, models_base_dir

    def _load_and_validate_head_data(self, head_spec, data_dir_list, head_name):
        """Load and validate data for head"""
        if isinstance(head_spec, str):
            self.logger.info(f"Loading data files for HEAD {head_spec}")
        else:
            self.logger.info(f"Loading data files for COMBINED HEADS: {', '.join(head_spec)}")

        data_list, filenames = self.data_loader.load_data_files_by_head(data_dir_list, head_spec)

        if len(data_list) < self.data_loader.MIN_SAMPLES_EACH_HEAD:
            error_msg = (f"Insufficient data for HEAD {head_name}: {len(data_list)} files. "
                        f"Minimum {self.data_loader.MIN_SAMPLES_EACH_HEAD} required")
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        return data_list, filenames

    def _split_all_data(self, data_list, filenames, config):
        """Split all data into train/validation sets"""
        validation_factor = config['training_validation_split'][1] / 100

        # Split data_dir files
        train_data, train_filenames, validation_data, validation_filenames = \
        self.preprocessor.split_train_validation(
            data_list, filenames, validation_size=validation_factor, random_state=42
        )
        self.logger.info(f"Data dir split: train={len(train_data)}, validation={len(validation_data)}")

        # Handle worst_model_dir files
        if config['worst_model_dir_list'] is not None:
            self.logger.info(f"Loading worst model data files")
            worst_data_list, worst_filenames = self.data_loader.load_worst_model_files(
                config['worst_model_dir_list'], config['frequency_segments']
            )

            train_worst, train_worst_filenames, validation_worst, validation_worst_filenames = \
            self.preprocessor.split_train_validation(
                worst_data_list, worst_filenames, validation_size=validation_factor, random_state=42
            )
            self.logger.info(f"Worst model split: train={len(train_worst)}, validation={len(validation_worst)}")
        else:
            self.logger.info("No worst_model_dir_list provided. Using only data_dir files for training.")
            train_worst = []
            train_worst_filenames = []
            validation_worst = []
            validation_worst_filenames = []

        return (train_data, train_filenames, validation_data, validation_filenames,
                train_worst, train_worst_filenames, validation_worst, validation_worst_filenames)

    def _combine_training_data(self, train_data, train_filenames, train_worst, train_worst_filenames, config):
        """Combine training data from data_dir and worst_model_dir"""
        if config['worst_model_dir_list'] is not None:
            train_data_combined = train_data + train_worst
            train_filenames_combined = train_filenames + train_worst_filenames
            self.logger.info(f"COMBINED training set")
            self.logger.info(f"{len(train_data_combined)} files ({len(train_data)} + {len(train_worst)})")
        else:
            train_data_combined = train_data
            train_filenames_combined = train_filenames
            self.logger.info(f"Training set: {len(train_data_combined)} files")

        return train_data_combined, train_filenames_combined

    @staticmethod
    def _save_split_info(head_output_dir, head_name, data_list, train_data, validation_data,
                        train_filenames, validation_filenames, train_worst, validation_worst,
                        train_worst_filenames, validation_worst_filenames, config):
        """Save train/validation split information"""
        split_info = {
            'head_name': head_name,
            'total_files': len(data_list),
            'total_worst_model_files': len(train_worst) + \
len(validation_worst) if config['worst_model_dir_list'] else 0,
            'train_files': len(train_data),
            'validation_files': len(validation_data),
            'train_filenames': [os.path.abspath(fname) for fname in train_filenames],
            'validation_filenames': [os.path.abspath(fname) for fname in validation_filenames],
            'worst_model_train_files': len(train_worst),
            'worst_model_validation_files': len(validation_worst),
            'worst_model_train_filenames': [os.path.abspath(fname) for fname in train_worst_filenames],
            'worst_model_validation_filenames': [os.path.abspath(fname) for fname in validation_worst_filenames]
        }

        split_info_path = os.path.join(head_output_dir, 'train_val_split.json')
        os.makedirs(os.path.dirname(split_info_path), exist_ok=True)
        with open(split_info_path, 'w', encoding='utf-8-sig') as f:
            json.dump(split_info, f, indent=2)
        del split_info

    def _check_frequency_segments(self, train_data_combined, frequency_segments):
        """Check frequency segment availability"""
        self.logger.info("="*80)
        self.logger.info("Checking frequency segment availability (COMBINED TRAIN SET)...")
        self.logger.info("="*80)
        valid_segments_train = self.segment_checker.check_frequency_segments_availability(
            train_data_combined, frequency_segments
        )
        self.logger.info(f"Found {len(valid_segments_train)} valid segments in combined train set")
        return valid_segments_train

    def _process_training_set(self, train_data_combined, train_filenames_combined, valid_segments_train,
                            head_output_dir, models_base_dir, head_name, config, num_real_files=None):
        """Process training set (normal or hierarchical mode).

        num_real_files: count of files at the start of the combined train set sourced from
        data_dir (real); any remainder is worst-model files, used for the legend breakdown
        on static Bode centroid plots.

        Returns:
            summaries, model_registry, optimal_k_info, merged_registry
        """
        baseline_separation = config.get('baseline_data_separation', False)

        if config.get('hierarchical_clustering', False):
            self.logger.info("="*80)
            self.logger.info("PROCESSING TRAIN SET (HIERARCHICAL MODE)")
            self.logger.info("="*80)
            summaries, registry, optimal_info, merged_registry = \
                self.hierarchical_processor.process_segment_hierarchical(
                    train_data_combined, train_filenames_combined, valid_segments_train,
                    head_output_dir, models_base_dir, head_name, config,
                    dataset_type='train', num_real_files=num_real_files
                )
            return summaries, registry, optimal_info, merged_registry

        self.logger.info("="*80)
        self.logger.info("PROCESSING TRAIN SET")
        self.logger.info("="*80)

        summaries, registry, optimal_info, merged_registry = \
            self.segmentprocessor.process_segment(
                train_data_combined, train_filenames_combined, valid_segments_train,
                head_output_dir, SegmentModelsContext(models_base_dir, head_name),
                config['training_application_stage1_features'],
                config['training_application_stage1_features_weightages'],
                cluster_config=config['no_of_clusters_for_each_segment'],
                dataset_type='train',
                metrics_to_use=config['metric'],
                output_options=ClusteringOutputOptions(
                    individual_frequencies_cluster_assignment_plots=config[
                        'individual_frequencies_cluster_assignment_plots'],
                    generate_interactive_html_plots=config['generate_interactive_html_plots']
                ),
                baseline_options=BaselineOptions(
                    baseline_separation=baseline_separation,
                    baseline_combination=config.get('baseline_data_filtering')
                ),
                num_real_files=num_real_files
            )

        return summaries, registry, optimal_info, merged_registry

    def _process_validation_sets(self, validation_data, validation_filenames, validation_worst,
                                validation_worst_filenames, config, head_output_dir, models_base_dir,
                                head_name, all_summaries_consolidated):
        """Process validation sets"""
        if len(validation_data) == 0 and len(validation_worst) == 0:
            self._log_validation_skipped()
            return

        if config.get('hierarchical_clustering', False):
            self._process_hierarchical_validation(
                validation_data, validation_filenames, validation_worst, validation_worst_filenames,
                config, head_output_dir, models_base_dir, head_name, all_summaries_consolidated
            )
            return

        if len(validation_data) > 0:
            self._process_data_dir_validation(
                validation_data, validation_filenames, config, head_output_dir,
                models_base_dir, head_name, all_summaries_consolidated
            )

        if config['worst_model_dir_list'] is not None and len(validation_worst) > 0:
            self._process_worst_model_validation(
                validation_worst, validation_worst_filenames, config, head_output_dir,
                models_base_dir, head_name, all_summaries_consolidated
            )

    def _process_hierarchical_validation(self, validation_data, validation_filenames,
                                          validation_worst, validation_worst_filenames,
                                          config, head_output_dir, models_base_dir, head_name,
                                          all_summaries_consolidated):
        """Process validation sets for hierarchical clustering mode."""
        if len(validation_data) > 0:
            self._process_hierarchical_validation_set(
                validation_data, validation_filenames, config, head_output_dir,
                models_base_dir, head_name, 'validation_data_dir',
                all_summaries_consolidated,
                num_real_files=len(validation_data)
            )

        if config['worst_model_dir_list'] is not None and len(validation_worst) > 0:
            self._process_hierarchical_validation_set(
                validation_worst, validation_worst_filenames, config, head_output_dir,
                models_base_dir, head_name, 'validation_worst_model',
                all_summaries_consolidated,
                num_real_files=0
            )

    def _process_hierarchical_validation_set(self, data, filenames, config, head_output_dir,
                                              models_base_dir, head_name, dataset_type,
                                              all_summaries_consolidated,
                                              num_real_files=None):
        """Process a single hierarchical validation set."""
        valid_segs = self.segment_checker.check_frequency_segments_availability(
            data, config['frequency_segments']
        )
        summaries, _, _, _ = self.hierarchical_processor.process_segment_hierarchical(
            data, filenames, valid_segs,
            head_output_dir, models_base_dir, head_name, config,
            dataset_type=dataset_type,
            num_real_files=num_real_files
        )
        if summaries:
            all_summaries_consolidated.extend(summaries)

    def _log_validation_skipped(self):
        """Log that validation is skipped"""
        self.logger.info("="*80)
        self.logger.info("VALIDATION SET PROCESSING SKIPPED")
        self.logger.info("="*80)
        self.logger.info("Validation set is empty (100% training split).")
        self.logger.info("All data has been used for training. No validation will be performed.")
        self.logger.info("="*80)

    def _process_data_dir_validation(self, validation_data, validation_filenames, config,
                                    head_output_dir, models_base_dir, head_name, all_summaries_consolidated):
        """Process data_dir validation set"""
        self.logger.info("="*80)
        self.logger.info("Checking frequency segment availability (VALIDATION - DATA_DIR)...")
        self.logger.info("="*80)
        valid_segments_validation_data_dir = self.segment_checker.check_frequency_segments_availability(
            validation_data, config['frequency_segments']
        )
        self.logger.info(f"Found {len(valid_segments_validation_data_dir)} valid segments")

        self.logger.info("="*60)
        self.logger.info("PROCESSING VALIDATION SET - DATA_DIR (Using Pretrained Models)")
        self.logger.info("="*60)

        baseline_separation = config.get('baseline_data_separation', False)

        validation_data_dir_summaries, _, _, _ = self.segmentprocessor.process_segment(
            validation_data, validation_filenames, valid_segments_validation_data_dir,
            head_output_dir, SegmentModelsContext(models_base_dir, head_name),
            config['training_application_stage1_features'],
            config['training_application_stage1_features_weightages'],
            cluster_config=config['no_of_clusters_for_each_segment'],
            dataset_type='validation_data_dir',
            metrics_to_use=config['metric'],
            output_options=ClusteringOutputOptions(
                individual_frequencies_cluster_assignment_plots=config[
                    'individual_frequencies_cluster_assignment_plots'],
                generate_interactive_html_plots=config['generate_interactive_html_plots']
            ),
            baseline_options=BaselineOptions(
                baseline_separation=baseline_separation,
                baseline_combination=config.get('baseline_data_filtering')
            ),
            num_real_files=len(validation_data)
        )

        if validation_data_dir_summaries:
            all_summaries_consolidated.extend(validation_data_dir_summaries)

    def _process_worst_model_validation(self, validation_worst, validation_worst_filenames, config,
                                        head_output_dir, models_base_dir, head_name, all_summaries_consolidated):
        """Process worst_model validation set"""
        self.logger.info("="*80)
        self.logger.info("Checking frequency segment availability (VALIDATION - WORST_MODEL)...")
        self.logger.info("="*80)
        valid_segments_validation_worst = self.segment_checker.check_frequency_segments_availability(
            validation_worst, config['frequency_segments']
        )
        self.logger.info(f"Found {len(valid_segments_validation_worst)} valid segments")

        self.logger.info("="*60)
        self.logger.info("PROCESSING VALIDATION SET - WORST_MODEL (Using Pretrained Models)")
        self.logger.info("="*60)

        baseline_separation = config.get('baseline_data_separation', False)

        validation_worst_summaries, _, _, _ = self.segmentprocessor.process_segment(
            validation_worst, validation_worst_filenames, valid_segments_validation_worst,
            head_output_dir, SegmentModelsContext(models_base_dir, head_name),
            config['training_application_stage1_features'],
            config['training_application_stage1_features_weightages'],
            cluster_config=config['no_of_clusters_for_each_segment'],
            dataset_type='validation_worst_model',
            metrics_to_use=config['metric'],
            output_options=ClusteringOutputOptions(
                individual_frequencies_cluster_assignment_plots=config[
                    'individual_frequencies_cluster_assignment_plots'],
                generate_interactive_html_plots=config['generate_interactive_html_plots']
            ),
            baseline_options=BaselineOptions(
                baseline_separation=baseline_separation,
                baseline_combination=config.get('baseline_data_filtering')
            ),
            num_real_files=0
        )

        if validation_worst_summaries:
            all_summaries_consolidated.extend(validation_worst_summaries)

    def _save_feature_config(self, models_base_dir, config):
        """Save feature configuration (normal or hierarchical)"""
        feature_config_path = os.path.join(models_base_dir, 'feature_config.json')
        os.makedirs(os.path.dirname(feature_config_path), exist_ok=True)

        if config.get('hierarchical_clustering', False):
            self.feature_config_manager.save_feature_config(
                config['training_application_stage1_features'],
                config['training_application_stage1_features_weightages'],
                feature_config_path,
                stage1_features=config['training_application_stage1_features'],
                stage1_weights=config['training_application_stage1_features_weightages'],
                stage2_features=config['training_application_stage2_features'],
                stage2_weights=config['training_application_stage2_features_weightages']
            )
        else:
            self.feature_config_manager.save_feature_config(
                config['training_application_stage1_features'],
                config['training_application_stage1_features_weightages'],
                feature_config_path
            )

    @staticmethod
    def _cleanup_head_data(data_list, filenames, train_data, train_filenames,
                        validation_data, validation_filenames, train_worst, train_worst_filenames,
                        validation_worst, validation_worst_filenames, train_data_combined,
                        train_filenames_combined, config):
        """Cleanup head processing data"""
        del data_list, filenames
        if config['worst_model_dir_list'] is not None:
            del train_worst, train_worst_filenames, validation_worst, validation_worst_filenames
        del train_data, train_filenames, validation_data, validation_filenames
        del train_data_combined, train_filenames_combined
        gc.collect()


class FRFClusteringApplication(object):
    """Main application class that orchestrates the entire FRF clustering analysis"""

    def __init__(self):
        self.config_loader = ConfigLoader()
        self.head_processor = HeadProcessor()
        self.registry_generator = ModelRegistryGenerator()
        self.output_config_generator = OutputConfigGenerator()
        self.cleanup_manager = CleanupManager()
        self.logging_manager = LoggingManager()

    def _process_all_heads(self, config, frf_clustering_analysis_dir, logger):
        """Process each head, accumulating registries.

        Returns (all_models_registry, all_optimal_k_info, all_merged_models_registry).
        """
        all_models_registry = []
        all_optimal_k_info = []
        all_merged_models_registry = []

        # PASS THE ANALYSIS DIR TO EACH HEAD
        for head_spec in config['heads']:
            try:

                head_model_registry, head_optimal_k_info, head_merged_registry = self.head_processor.process_head(
                    head_spec, config, frf_clustering_analysis_dir
                )

                if head_model_registry:
                    all_models_registry.extend(head_model_registry)
                if head_optimal_k_info:
                    all_optimal_k_info.extend(head_optimal_k_info)
                if head_merged_registry:
                    all_merged_models_registry.extend(head_merged_registry)
                # Add explicit cleanup after each head
                del head_model_registry, head_optimal_k_info, head_merged_registry
                gc.collect()
            except Exception:
                logger.warning(f"Failed to process head {head_spec}")
                continue

        return all_models_registry, all_optimal_k_info, all_merged_models_registry

    def run(self, config_path):
        """Main execution method"""

        # STAGE 1: Extract output_path and setup logging
        try:
            output_path = self.config_loader.extract_output_path(config_path)
        except Exception:
            sys.exit(1)

        # CREATE TIMESTAMPED DIRECTORY AT USER-SPECIFIED LOCATION
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        frf_clustering_analysis_dir = os.path.join(
            output_path,
            f'frf_clustering_analysis_{timestamp}'
        )
        try:
            os.makedirs(frf_clustering_analysis_dir, exist_ok=True)
        except Exception:
            print(f"FATAL ERROR: Cannot create FRF Clustering analysis directory: {frf_clustering_analysis_dir}")
            print("Check permissions or disk space")
            sys.exit(1)

        logger, log_file = self.logging_manager.setup_logging(frf_clustering_analysis_dir)

        # STAGE 2: Full config validation
        config = self.config_loader.load_config(config_path)

        all_models_registry, all_optimal_k_info, all_merged_models_registry = self._process_all_heads(
            config, frf_clustering_analysis_dir, logger
        )

        # Generate trained models registry CSV (normal mode only)
        if all_models_registry and not config.get('hierarchical_clustering', False):
            self.registry_generator.generate_trained_models_registry(all_models_registry, frf_clustering_analysis_dir)
            # Generate output config JSON
            self.output_config_generator.generate_output_config(
                config, all_models_registry, all_optimal_k_info, frf_clustering_analysis_dir,
                all_merged_models_registry=all_merged_models_registry
            )
        elif config.get('hierarchical_clustering', False):
            # Generate trained models registry CSV for hierarchical mode
            if all_models_registry:
                self.registry_generator.generate_trained_models_registry(
                    all_models_registry, frf_clustering_analysis_dir
                )
            # Generate input_inference_config.cfg for hierarchical mode
            # all_optimal_k_info contains hierarchical_optimal_info entries (one per segment per head)
            self.output_config_generator.generate_output_config(
                config, all_models_registry, all_optimal_k_info, frf_clustering_analysis_dir,
                all_merged_models_registry=all_merged_models_registry
            )
        else:
            logger.warning("No trained models were generated across all heads")

        self.cleanup_manager.cleanup_pycache()

        logger.info("="*100)
        logger.info("ALL HEAD ANALYSIS COMPLETED SUCCESSFULLY")
        logger.info(f"Results saved in: {frf_clustering_analysis_dir}")
        logger.info(f"Log file saved at: {log_file}")
        logger.info("="*100)


def main():
    """Entry point for the application"""
    parser = argparse.ArgumentParser(
        description="FRF Training Application Tool - Frequency Segment Clustering and Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
USAGE EXAMPLES:
===============================================================================
Basic usage:
  python frf_training_application.py --config frf_config/config.cfg
View this help:
  python frf_training_application.py --help
  python frf_training_application.py -h
View the version information:
  python frf_training_application.py --version
  python frf_training_application.py -v
        """
    )

    parser.add_argument(
        '--version', '-v',
        action='version',
        version='FRF Clustering Training Application V004'
    )

    parser.add_argument(
        '--config',
        type=str,
        required=True,
        metavar='CONFIG_FILE',
        help='Path to configuration file (.cfg) containing analysis parameters'
    )

    args = parser.parse_args()

    app = FRFClusteringApplication()
    app.run(args.config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger = logging.getLogger(__name__)
        logger.warning("="*80)
        logger.warning("ANALYSIS INTERRUPTED BY USER (Ctrl+C)")
        logger.warning("Partial results may be available in output directory")
        logger.warning("="*80)
        sys.exit(1)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error("="*80)
        logger.error(f"FATAL ERROR: {e}")
        logger.error("="*80)
        sys.exit(1)
