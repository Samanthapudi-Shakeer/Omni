# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_application.py
*  File Description: Main file for inference using pre-trained clustering models
*  All rights reserved.
*
*********************************************************************/
"""

import os
import sys
import gc
import warnings
import argparse
import logging
import shutil
from datetime import datetime
from frf_inference_config_loader import InferenceConfigLoader
from frf_inference_utils import LoggingManager, FrequencySegmentAvailabilityChecker, SegmentSummaryGenerator
from frf_inference_data_utils import DataFileLoader
from frf_inference_segment_processor import SegmentProcessor, InferenceOptions

warnings.filterwarnings('ignore')


class HeadProcessor(object):
    """Processes a single head for inference"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.data_loader = DataFileLoader()
        self.segmentprocessor = SegmentProcessor()
        self.summary_generator = SegmentSummaryGenerator()
        self.segment_checker = FrequencySegmentAvailabilityChecker()

    def process_head_inference(self, head_spec, config, frf_inference_analysis_dir):
        """Process inference for a single head or combined heads

        Args:
            head_spec: Either a string (single head) or list of strings (combined heads)
            config: Configuration dictionary
            frf_inference_analysis_dir: Base output directory

        Returns:
            List of inference summaries
        """
        frequency_segments = config['frequency_segments']
        metrics_to_use = config['metric']
        data_dir = config['data_dir_list']
        individual_frequencies_cluster_assignment_plots = config['individual_frequencies_cluster_assignment_plots']
        generate_interactive_html_plots = config['generate_interactive_html_plots']
        hierarchical = config.get('hierarchical_clustering', False)
        baseline_separation = config.get('baseline_data_separation', False)
        baseline_data_filtering = config.get('baseline_data_filtering', None)
        root_dir = config.get('root_dir', '')

        if hierarchical:
            features_list = config['training_application_stage2_features']
            feature_weights = config['training_application_stage2_features_weightages']
        else:
            features_list = config['training_application_stage1_features']
            feature_weights = config['training_application_stage1_features_weightages']

        # Generate head name for logging and directories
        head_name, log_head_name = self._generate_head_names(head_spec)

        self.logger.info("="*100)
        self.logger.info("FRF INFERENCE ANALYSIS STARTED")
        self.logger.info(f"HEAD NAME: {log_head_name}")
        self.logger.info("="*100)

        # Create head output directory
        head_output_dir = os.path.join(frf_inference_analysis_dir, f'HEAD_{head_name}')
        os.makedirs(head_output_dir, exist_ok=True)

        try:
            # Load data files
            self.logger.info(f"Loading EXV, XPI and XIZ files for HEAD {head_spec}")

            data_list, filenames = self.data_loader.load_data_files_by_head(data_dir, head_spec)

            # Check frequency segment availability
            self.logger.info("="*80)
            self.logger.info("Checking frequency segment availability (INFERENCE DATA)...")
            self.logger.info("="*80)
            valid_segments_inference = self.segment_checker.check_frequency_segments_availability(
                data_list, frequency_segments
            )

            self.logger.info(f"Found {len(valid_segments_inference)} valid segments in inference data")

            # Process segments (all trained model combinations)
            self.logger.info("="*80)
            self.logger.info("PROCESSING INFERENCE SET")
            self.logger.info("="*80)

            options = InferenceOptions(
                baseline_separation=baseline_separation,
                baseline_data_filtering=baseline_data_filtering,
                individual_frequencies_cluster_assignment_plots=individual_frequencies_cluster_assignment_plots,
                generate_interactive_html_plots=generate_interactive_html_plots
            )

            all_models_dict = config['all_models_dict']

            if head_name not in all_models_dict:
                self.logger.warning(f"No models found for head {head_name} in all_models_dict")
                return []

            inference_summaries = self.segmentprocessor.process_segment_inference_all_mode(
                data_list, filenames, valid_segments_inference,
                head_output_dir, head_name, features_list, feature_weights,
                all_models_dict[head_name], metrics_to_use, root_dir,
                options=options
            )

            # Generate summary CSV
            if inference_summaries:
                self.summary_generator.generate_final_segment_summary(
                    inference_summaries, head_output_dir, head_name
                )
                self.logger.info(f"Generated inference summary for HEAD {head_name}")

            self.logger.info("="*60)
            self.logger.info(f"Completed inference for HEAD {head_name}")
            self.logger.info("="*60)

            del data_list, filenames
            gc.collect()

            return inference_summaries

        except Exception as e:
            self.logger.error(f"Error during inference for HEAD {head_name}: {e}")
            return []

    def _generate_head_names(self, head_spec):
        """Generate head name for directories and lookups, matching the training
        application's naming exactly (frf_training_application.py::_generate_head_names),
        including keyword-based names (e.g. 'even_number_hds') for combined-heads
        groups built from head-selection keyword(s)."""
        if isinstance(head_spec, str):
            head_name = head_spec
            log_head_name = head_name
            return head_name, log_head_name

        head_name = self._build_combined_head_name(head_spec)
        log_head_name = f"COMBINED HEADS: {', '.join(sorted(head_spec))}"
        return head_name, log_head_name

    def _build_combined_head_name(self, head_spec):
        """Build the output head name for a combined-heads group.

        When the group was built from head-selection keyword(s) (e.g.
        'even_number_heads', 'all_heads'), the keyword name(s) are used as the
        output name directly (with '_heads' shortened to '_hds'), replacing the
        previous hardcoded 'HD_ALL' shortcut. Any manually-typed heads mixed in
        alongside the keyword(s) are appended as transformed head codes to keep
        the name unique. Groups with no keyword involved keep the original
        transformed-head-code naming.
        """
        keywords_used = getattr(head_spec, 'keywords', [])
        if not keywords_used:
            return self._build_concatenated_head_name(head_spec)

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

    def _build_concatenated_head_name(self, head_spec):
        """Transform and concatenate head codes: HD0->00, HD15->15, HDA->0A"""
        transformed_codes = [self._transform_head_code(h) for h in sorted(head_spec)]
        concatenated = ''.join(transformed_codes)
        return f"HD_{concatenated}"


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


class FRFInferenceApplication(object):
    """Main application class that orchestrates the entire FRF inference analysis"""

    def __init__(self):
        self.config_loader = InferenceConfigLoader()
        self.head_processor = HeadProcessor()
        self.cleanup_manager = CleanupManager()
        self.logging_manager = LoggingManager()

    def run(self, config_path):
        """Main execution method"""

        # STAGE 1: Extract output_dir and setup logging
        try:
            output_dir = self.config_loader.extract_output_path(config_path)
        except Exception:
            sys.exit(1)

        # CREATE TIMESTAMPED DIRECTORY AT USER-SPECIFIED LOCATION
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        frf_inference_analysis_dir = os.path.join(
            output_dir,
            f'frf_inference_analysis_{timestamp}'
        )
        try:
            os.makedirs(frf_inference_analysis_dir, exist_ok=True)
        except Exception:
            print(f"FATAL ERROR: Cannot create FRF Inference analysis directory: {frf_inference_analysis_dir}")
            print("Check permissions or disk space")
            sys.exit(1)

        logger, log_file = self.logging_manager.setup_logging(frf_inference_analysis_dir)

        # STAGE 2: Full config validation
        config = self.config_loader.load_config(config_path)

        # Process each head (supports both single and combined heads)
        for head_spec in config['heads']:
            try:
                self.head_processor.process_head_inference(
                    head_spec, config, frf_inference_analysis_dir
                )
            except Exception:
                logger.warning(f"Failed to process head {head_spec}")
                continue

        self.cleanup_manager.cleanup_pycache()

        logger.info("="*100)
        logger.info("ALL HEAD INFERENCE COMPLETED SUCCESSFULLY")
        logger.info(f"Results saved in: {frf_inference_analysis_dir}")
        logger.info(f"Log file saved at: {log_file}")
        logger.info("="*100)


def main():
    """Entry point for the application"""
    parser = argparse.ArgumentParser(
        description="FRF Inference Application Tool - Cluster Prediction using Pre-trained Models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
INFERENCE CONFIGURATION FILE:
===============================================================================
The inference application uses "input_inference_config.cfg" generated by the training
application. Before running inference application, user must edit "INFERENCE_APPLICATION_REQUIRED_PARAMETER".

EXAMPLE USAGE:
===============================================================================
1. Run inference against every trained model:
   python frf_inference_application.py --config frf_inference_config/input_inference_config.cfg

2. View version information:
   python frf_inference_application.py --version
   python frf_inference_application.py -v

3. View this help:
   python frf_inference_application.py --help
   python frf_inference_application.py -h
        """
    )

    parser.add_argument(
        '--version', '-v',
        action='version',
        version='FRF Clustering Inference Application V004'
    )

    parser.add_argument(
        '--config',
        type=str,
        required=True,
        metavar='CONFIG_FILE',
        help='Path to input_inference_config.cfg file generated by training application'
    )

    args = parser.parse_args()

    app = FRFInferenceApplication()
    app.run(args.config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger = logging.getLogger(__name__)
        logger.warning("="*80)
        logger.warning("INFERENCE INTERRUPTED BY USER (Ctrl+C)")
        logger.warning("Partial results may be available in output directory")
        logger.warning("="*80)
        sys.exit(1)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error("="*80)
        logger.error(f"FATAL ERROR")
        logger.error("="*80)
        sys.exit(1)
