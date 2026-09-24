# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_metrics.py
*  File Description: File that defines all metric functions.
*  All rights reserved.
*
*********************************************************************/
"""

import logging
import numpy as np
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from frf_inference_metric_components import ConvexHullCalculator, FanSegmentCalculator


class BaselineMetricsCalculator(object):
    """Calculates k=1 baseline metrics for comparison"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.aci_calculator = ACIMetricsCalculator()

    def calculate_k1_baseline_metrics(self, frequencywise_data, file_indices, unique_frequencies,
                            segment_file_dict, metrics_to_use=['ACI1', 'ACI2', 'ACI3', 'ACI4']):
        """Calculate baseline metrics for k=1 (no clustering) for comparison"""
        try:
            frequency_aci_scores = {'aci1': [], 'aci2': [], 'aci3': [], 'aci4': []}
            successful_freq_count, failed_freq_count = self._process_all_frequencies(
                frequencywise_data, file_indices, unique_frequencies,
                segment_file_dict, metrics_to_use, frequency_aci_scores
            )

            self._log_baseline_processing_summary(successful_freq_count, failed_freq_count,
                                                len(unique_frequencies))

            # Early validation check
            if successful_freq_count == 0:
                self.logger.warning("      Cannot calculate k=1 baseline")
                self.logger.warning("      Convex Hull could not be created for any frequency")
                return None

            # Calculate and return baseline metrics
            baseline_metrics = self._calculate_baseline_averages(frequency_aci_scores, metrics_to_use)

            if baseline_metrics:
                self._log_baseline_metrics(baseline_metrics, metrics_to_use)
            else:
                self.logger.warning(" Could not calculate k=1 baseline metrics")

            return baseline_metrics

        except Exception as e:
            self.logger.error(f"Error calculating k=1 baseline metrics: {e}")
            return None

    def _process_all_frequencies(self, frequencywise_data, file_indices, unique_frequencies,
                                segment_file_dict, metrics_to_use, frequency_aci_scores):
        """Process each frequency and collect ACI scores"""
        successful_freq_count = 0
        failed_freq_count = 0

        for freq_idx, frequency in enumerate(unique_frequencies):
            freq_data = self._extract_frequency_data(
                frequencywise_data, file_indices, segment_file_dict, freq_idx
            )

            if not self._is_convex_hull_valid(freq_data['real'], freq_data['imag']):
                failed_freq_count += 1
                continue

            successful_freq_count += 1
            self._calculate_and_append_aci_scores(
                freq_data, metrics_to_use, frequency_aci_scores
            )

        return successful_freq_count, failed_freq_count

    @staticmethod
    def _extract_frequency_data(frequencywise_data, file_indices, segment_file_dict, freq_idx):
        """Extract real, imaginary, gain, and phase data for a specific frequency"""
        freq_real_data = []
        freq_imag_data = []
        freq_gain_data = []
        freq_phase_data = []

        for file_idx, original_file_idx in enumerate(file_indices):
            file_data_entry = segment_file_dict['files'][original_file_idx]
            freq_real_data.append(file_data_entry['real'][freq_idx])
            freq_imag_data.append(file_data_entry['imaginary'][freq_idx])
            freq_gain_data.append(file_data_entry['gain'][freq_idx])
            freq_phase_data.append(file_data_entry['phase'][freq_idx])

        return {
            'real': np.array(freq_real_data),
            'imag': np.array(freq_imag_data),
            'gain': np.array(freq_gain_data),
            'phase': np.array(freq_phase_data)
        }

    @staticmethod
    def _is_convex_hull_valid(real_array, imag_array):
        """Check if convex hull can be created for the given data"""
        hull_calculator = ConvexHullCalculator()
        hull_x, hull_y, hull_area, hull_stats = hull_calculator.calculate_convex_hull(
            real_array, imag_array
        )
        return hull_area is not None

    def _calculate_and_append_aci_scores(self, freq_data, metrics_to_use, frequency_aci_scores):
        """Calculate ACI metrics for a frequency and append to scores"""
        # For k=1, all points belong to one cluster
        freq_labels = np.zeros(len(freq_data['real']), dtype=int)

        aci_results = self._calculate_all_aci_metrics(
            freq_data, freq_labels, metrics_to_use
        )

        self._append_aci_scores(aci_results, frequency_aci_scores, metrics_to_use)

    def _calculate_all_aci_metrics(self, freq_data, freq_labels, metrics_to_use):
        """Calculate all requested ACI metrics"""
        aci_results = {}

        if 'ACI1' in metrics_to_use:
            aci_results['aci1'] = self.aci_calculator.calculate_evaluation_metric_aci1(
                freq_data['real'], freq_data['imag'], freq_data['gain'],
                freq_data['phase'], freq_labels, k=1
            )

        if 'ACI2' in metrics_to_use:
            aci_results['aci2'] = self.aci_calculator.calculate_evaluation_metric_aci2(
                freq_data['real'], freq_data['imag'], freq_data['gain'],
                freq_data['phase'], freq_labels, k=1
            )

        if 'ACI3' in metrics_to_use:
            aci_results['aci3'] = self.aci_calculator.calculate_evaluation_metric_aci3(
                freq_data['real'], freq_data['imag'], freq_data['gain'],
                freq_data['phase'], freq_labels, k=1
            )

        if 'ACI4' in metrics_to_use:
            aci_results['aci4'] = self.aci_calculator.calculate_evaluation_metric_aci4(
                freq_data['real'], freq_data['imag'], freq_data['gain'],
                freq_data['phase'], freq_labels, k=1
            )

        return aci_results

    @staticmethod
    def _append_aci_scores(aci_results, frequency_aci_scores, metrics_to_use):
        """Append ACI scores to the collection"""
        if 'ACI1' in metrics_to_use and aci_results.get('aci1'):
            frequency_aci_scores['aci1'].append(aci_results['aci1']['aci1_score'])

        if 'ACI2' in metrics_to_use and aci_results.get('aci2'):
            frequency_aci_scores['aci2'].append(aci_results['aci2']['aci2_score'])

        if 'ACI3' in metrics_to_use and aci_results.get('aci3'):
            frequency_aci_scores['aci3'].append(aci_results['aci3']['aci3_score'])

        if 'ACI4' in metrics_to_use and aci_results.get('aci4'):
            frequency_aci_scores['aci4'].append(aci_results['aci4']['aci4_score'])

    def _log_baseline_processing_summary(self, successful_freq_count, failed_freq_count, total_frequencies):
        """Log summary of baseline processing"""
        self.logger.info(f"      k=1 baseline: Successful: {successful_freq_count}")
        self.logger.info(f"      k=1 baseline: Failed: {failed_freq_count}")
        self.logger.info(f"      k=1 baseline: Total Frequencies: {total_frequencies}")

    @staticmethod
    def _calculate_baseline_averages(frequency_aci_scores, metrics_to_use):
        """Calculate average ACI scores for baseline"""
        baseline_metrics = {'k': 1}

        if 'ACI1' in metrics_to_use and frequency_aci_scores['aci1']:
            baseline_metrics['aci1_score'] = np.mean(frequency_aci_scores['aci1'])

        if 'ACI2' in metrics_to_use and frequency_aci_scores['aci2']:
            baseline_metrics['aci2_score'] = np.mean(frequency_aci_scores['aci2'])

        if 'ACI3' in metrics_to_use and frequency_aci_scores['aci3']:
            baseline_metrics['aci3_score'] = np.mean(frequency_aci_scores['aci3'])

        if 'ACI4' in metrics_to_use and frequency_aci_scores['aci4']:
            baseline_metrics['aci4_score'] = np.mean(frequency_aci_scores['aci4'])

        # Check if any metrics were calculated
        has_metrics = any(key in baseline_metrics for key in ['aci1_score', 'aci2_score', 'aci3_score', 'aci4_score'])

        return baseline_metrics if has_metrics else None

    def _log_baseline_metrics(self, baseline_metrics, metrics_to_use):
        """Log calculated baseline metrics"""
        log_msg = " k=1 baseline:"
        log_parts = []

        if 'ACI1' in metrics_to_use and 'aci1_score' in baseline_metrics:
            log_parts.append(f" ACI1={baseline_metrics['aci1_score']:.4f}")

        if 'ACI2' in metrics_to_use and 'aci2_score' in baseline_metrics:
            log_parts.append(f" ACI2={baseline_metrics['aci2_score']:.4f}")

        if 'ACI3' in metrics_to_use and 'aci3_score' in baseline_metrics:
            log_parts.append(f" ACI3={baseline_metrics['aci3_score']:.4f}")

        if 'ACI4' in metrics_to_use and 'aci4_score' in baseline_metrics:
            log_parts.append(f" ACI4={baseline_metrics['aci4_score']:.4f}")

        log_msg += "".join(log_parts)
        self.logger.info(log_msg)


class BaselineComparator(object):
    """Compares clustering results with k=1 baseline"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def compare_with_k1_baseline(self, segment_aci_scores, k1_baseline, segment_name,
                                metrics_to_use=['ACI1', 'ACI2', 'ACI3', 'ACI4']):
        """Compare clustering results with k=1 baseline and log improvements"""
        if not k1_baseline:
            self.logger.warning(f"No k=1 baseline available for comparison in segment {segment_name}")
            return {}

        baseline_scores = self._extract_baseline_scores(k1_baseline, metrics_to_use)
        self._log_baseline_summary(baseline_scores, metrics_to_use, segment_name)

        comparison_results = self._compare_all_clusters(
            segment_aci_scores, baseline_scores, metrics_to_use
        )

        return comparison_results

    @staticmethod
    def _extract_baseline_scores(k1_baseline, metrics_to_use):
        """Extract baseline scores for all metrics"""
        return {
            'aci1': k1_baseline.get('aci1_score', np.nan) if 'ACI1' in metrics_to_use else np.nan,
            'aci2': k1_baseline.get('aci2_score', np.nan) if 'ACI2' in metrics_to_use else np.nan,
            'aci3': k1_baseline.get('aci3_score', np.nan) if 'ACI3' in metrics_to_use else np.nan,
            'aci4': k1_baseline.get('aci4_score', np.nan) if 'ACI4' in metrics_to_use else np.nan
        }

    def _log_baseline_summary(self, baseline_scores, metrics_to_use, segment_name):
        """Log baseline comparison header and values"""
        self.logger.info(f" K=1 vs Clustering Comparison for segment {segment_name}:")

        log_parts = []
        if 'ACI1' in metrics_to_use and not np.isnan(baseline_scores['aci1']):
            log_parts.append(f"ACI1: {baseline_scores['aci1']:.4f}")

        if 'ACI2' in metrics_to_use and not np.isnan(baseline_scores['aci2']):
            log_parts.append(f"ACI2: {baseline_scores['aci2']:.4f}")

        if 'ACI3' in metrics_to_use and not np.isnan(baseline_scores['aci3']):
            log_parts.append(f"ACI3: {baseline_scores['aci3']:.4f}")

        if 'ACI4' in metrics_to_use and not np.isnan(baseline_scores['aci4']):
            log_parts.append(f"ACI4: {baseline_scores['aci4']:.4f}")

        log_msg = " Baseline (k=1) - " + ", ".join(log_parts)
        self.logger.info(log_msg)

    def _compare_all_clusters(self, segment_aci_scores, baseline_scores, metrics_to_use):
        """Compare all cluster configurations with baseline"""
        comparison_results = {}

        for k in sorted(segment_aci_scores.keys()):
            if k == 1:
                continue

            cluster_scores = self._extract_cluster_scores(segment_aci_scores[k], metrics_to_use)
            comparison_data = self._calculate_improvements(cluster_scores, baseline_scores, metrics_to_use)

            if comparison_data:
                comparison_results[k] = comparison_data
                self._log_cluster_comparison(k, comparison_data, metrics_to_use)

        return comparison_results

    @staticmethod
    def _extract_cluster_scores(cluster_data, metrics_to_use):
        """Extract cluster scores for all metrics"""
        return {
            'aci1': cluster_data.get('avg_aci1', np.nan) if 'ACI1' in metrics_to_use else np.nan,
            'aci2': cluster_data.get('avg_aci2', np.nan) if 'ACI2' in metrics_to_use else np.nan,
            'aci3': cluster_data.get('avg_aci3', np.nan) if 'ACI3' in metrics_to_use else np.nan,
            'aci4': cluster_data.get('avg_aci4', np.nan) if 'ACI4' in metrics_to_use else np.nan
        }

    def _calculate_improvements(self, cluster_scores, baseline_scores, metrics_to_use):
        """Calculate improvement metrics for all ACI scores"""
        comparison_data = {}

        metric_handlers = {
            'ACI1': ('aci1', 'cluster_aci1', 'aci1_improvement', 'aci1_%_improvement'),
            'ACI2': ('aci2', 'cluster_aci2', 'aci2_improvement', 'aci2_%_improvement'),
            'ACI3': ('aci3', 'cluster_aci3', 'aci3_improvement', 'aci3_%_improvement'),
            'ACI4': ('aci4', 'cluster_aci4', 'aci4_improvement', 'aci4_%_improvement')
        }

        for metric in metrics_to_use:
            if metric in metric_handlers:
                score_key, cluster_key, imp_key, pct_key = metric_handlers[metric]
                self._add_metric_improvement(
                    comparison_data, cluster_scores[score_key],
                    baseline_scores[score_key], cluster_key, imp_key, pct_key
                )

        return comparison_data

    @staticmethod
    def _add_metric_improvement(comparison_data, cluster_score, baseline_score,
                                cluster_key, improvement_key, percent_key):
        """Add improvement data for a single metric"""
        if not np.isnan(baseline_score) and not np.isnan(cluster_score):
            improvement = cluster_score - baseline_score
            percent_improvement = (improvement / abs(baseline_score)) * 100 if baseline_score != 0 else float('inf')

            comparison_data.update({
                cluster_key: cluster_score,
                improvement_key: improvement,
                percent_key: percent_improvement
            })

    def _log_cluster_comparison(self, k, comparison_data, metrics_to_use):
        """Log comparison results for a cluster configuration"""
        log_parts = []

        metric_keys = {
            'ACI1': ('cluster_aci1', 'aci1_improvement', 'aci1_%_improvement'),
            'ACI2': ('cluster_aci2', 'aci2_improvement', 'aci2_%_improvement'),
            'ACI3': ('cluster_aci3', 'aci3_improvement', 'aci3_%_improvement'),
            'ACI4': ('cluster_aci4', 'aci4_improvement', 'aci4_%_improvement')
        }

        for metric in metrics_to_use:
            if metric in metric_keys:
                cluster_key, imp_key, pct_key = metric_keys[metric]
                if cluster_key in comparison_data:
                    log_parts.append(
                        f"{metric}: {comparison_data[cluster_key]:.4f} "
                        f"({comparison_data[imp_key]:+.4f}, {comparison_data[pct_key]:+.1f}%)"
                    )

        self.logger.info(f" k={k} - " + ", ".join(log_parts))


class ACIMetricsCalculator(object):
    """Calculates ACI1, ACI2, ACI3, and ACI4 metrics"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.hull_calculator = ConvexHullCalculator()
        self.fan_calculator = FanSegmentCalculator()

    def calculate_evaluation_metric_aci1(self, real_array, imag_array, gain_array,
                                         phase_array, labels, k):
        """Calculate ACI1 metric
        ACI1 = [ (3) - ( dp1 + ap1 ) ] / (2)
        """
        try:
            # Component 1: Convex hull area
            _, _, convex_hull_area, _ = self.hull_calculator.calculate_convex_hull(real_array, imag_array)
            if convex_hull_area is None:
                # self.logger.warning(f"Convex hull calculation failed, skipping ACI1 calculation")
                return None

            # Component 2: Union of fan segments area
            cluster_polygons = []

            for cluster_id in range(k):
                cluster_mask = labels == cluster_id

                cluster_gain = gain_array[cluster_mask]
                cluster_phase = phase_array[cluster_mask]
                fan_polygon = self.fan_calculator.create_fan_polygon(cluster_gain, cluster_phase)

                if fan_polygon and fan_polygon.is_valid:
                    cluster_polygons.append(fan_polygon)

            union_polygon = unary_union(cluster_polygons)
            union_fan_area = union_polygon.area

            # Component 3: Intersection area
            hull_x, hull_y, _, _ = self.hull_calculator.calculate_convex_hull(real_array, imag_array)
            convex_hull_polygon = Polygon(np.column_stack([hull_x[:-1], hull_y[:-1]]))
            intersection_polygon = convex_hull_polygon.intersection(union_polygon)
            intersection_area = intersection_polygon.area

            # Component 4: Uncovered area
            uncovered_area = convex_hull_area - intersection_area

            # Density calculation
            points = [Point(real, img) for real, img in zip(real_array, imag_array)]
            points_in_union = sum(1 for point in points if union_polygon.contains(point))
            density = points_in_union / union_fan_area if union_fan_area > 0 else 0

            # Penalties
            dp1 = 100 / density if density > 0 else float('inf')
            ap1 = 0.5 * uncovered_area

            # ACI1 Formula = [ (3) - ( dp1 + ap1 ) ] / (2)
            coverage_efficiency = intersection_area - dp1 - ap1
            aci1_score = coverage_efficiency/union_fan_area

            return {
                'convex_hull_area': convex_hull_area,
                'union_fan_area': union_fan_area,
                'intersection_area': intersection_area,
                'uncovered_area': uncovered_area,
                'points_in_union': points_in_union,
                'density': density,
                'dp1': dp1,
                'ap1': ap1,
                'coverage_efficiency': coverage_efficiency,
                'aci1_score': aci1_score
            }

        except Exception:
            self.logger.error(f"Error calculating ACI1 metric")
            return None

    def calculate_evaluation_metric_aci2(self, real_array, imag_array, gain_array,
                                         phase_array, labels, k):
        """Calculate ACI2 metric
        ACI2 = [ (3) - ( dp1 + ap2 ) ] / (2)
        """
        try:
            # Component 1: Convex hull area
            _, _, convex_hull_area, _ = self.hull_calculator.calculate_convex_hull(real_array, imag_array)
            if convex_hull_area is None:
                # self.logger.warning(f"Convex hull calculation failed, skipping ACI2 calculation")
                return None

            # Component 2: Union of fan segments area
            cluster_polygons = []

            for cluster_id in range(k):
                cluster_mask = labels == cluster_id

                cluster_gain = gain_array[cluster_mask]
                cluster_phase = phase_array[cluster_mask]
                fan_polygon = self.fan_calculator.create_fan_polygon(cluster_gain, cluster_phase)

                if fan_polygon and fan_polygon.is_valid:
                    cluster_polygons.append(fan_polygon)

            union_polygon = unary_union(cluster_polygons)
            union_fan_area = union_polygon.area

            # Component 3: Intersection area
            hull_x, hull_y, _, _ = self.hull_calculator.calculate_convex_hull(real_array, imag_array)
            convex_hull_polygon = Polygon(np.column_stack([hull_x[:-1], hull_y[:-1]]))
            intersection_polygon = convex_hull_polygon.intersection(union_polygon)
            intersection_area = intersection_polygon.area

            # Component 4: Uncovered area
            uncovered_area = convex_hull_area - intersection_area

            # Points for penalty calculations
            points = [Point(real, img) for real, img in zip(real_array, imag_array)]

            # Density penalty (dp1)
            points_in_union = sum(1 for point in points if union_polygon.contains(point))
            density = points_in_union / union_fan_area if union_fan_area > 0 else 0
            dp1 = 100 / density if density > 0 else float('inf')

            # Area penalty 2 (ap2) - Points in uncovered region weighted by area
            uncovered_polygon = convex_hull_polygon.difference(intersection_polygon)
            points_in_uncovered = sum(1 for point in points if uncovered_polygon.contains(point))

            # ap2 Formula = ( points_in_uncovered / points_in_union ) * uncovered_area
            if points_in_union > 0:
                ap2 = (points_in_uncovered / points_in_union) * uncovered_area
            else:
                ap2 = 0

            # ACI2 Formula = [ (3) - ( dp1 + ap2 ) ] / (2)
            coverage_efficiency = intersection_area - dp1 - ap2
            aci2_score = coverage_efficiency / union_fan_area

            return {
                'convex_hull_area': convex_hull_area,
                'union_fan_area': union_fan_area,
                'intersection_area': intersection_area,
                'uncovered_area': uncovered_area,
                'points_in_union': points_in_union,
                'points_in_uncovered': points_in_uncovered,
                'density': density,
                'dp1': dp1,
                'ap2': ap2,
                'coverage_efficiency': coverage_efficiency,
                'aci2_score': aci2_score
            }

        except Exception:
            self.logger.error(f"Error calculating ACI2 metric")
            return None

    def calculate_evaluation_metric_aci3(self, real_array, imag_array, gain_array,
                                         phase_array, labels, k):
        """Calculate ACI3 metric
        ACI3 = [ (3) - ( dp1 + ap1 + ( (2) - (3) ) ) ] / (2)
        """
        try:
            # Component 1: Convex hull area
            _, _, convex_hull_area, _ = self.hull_calculator.calculate_convex_hull(real_array, imag_array)
            if convex_hull_area is None:
                # self.logger.warning(f"Convex hull calculation failed, skipping ACI3 calculation")
                return None

            # Component 2: Union of fan segments area
            cluster_polygons = []

            for cluster_id in range(k):
                cluster_mask = labels == cluster_id

                cluster_gain = gain_array[cluster_mask]
                cluster_phase = phase_array[cluster_mask]
                fan_polygon = self.fan_calculator.create_fan_polygon(cluster_gain, cluster_phase)

                if fan_polygon and fan_polygon.is_valid:
                    cluster_polygons.append(fan_polygon)

            union_polygon = unary_union(cluster_polygons)
            union_fan_area = union_polygon.area

            # Component 3: Intersection area
            hull_x, hull_y, _, _ = self.hull_calculator.calculate_convex_hull(real_array, imag_array)
            convex_hull_polygon = Polygon(np.column_stack([hull_x[:-1], hull_y[:-1]]))
            intersection_polygon = convex_hull_polygon.intersection(union_polygon)
            intersection_area = intersection_polygon.area

            # Component 4: Uncovered area
            uncovered_area = convex_hull_area - intersection_area

            # Excess fan area
            excess_fan_area = union_fan_area - intersection_area

            # Density calculation
            points = [Point(real, img) for real, img in zip(real_array, imag_array)]
            points_in_union = sum(1 for point in points if union_polygon.contains(point))
            density = points_in_union / union_fan_area if union_fan_area > 0 else 0

            # Penalties
            dp1 = 100 / density if density > 0 else float('inf')
            ap1 = 0.5 * uncovered_area

            # ACI3 Formula = [ (3) - ( dp1 + ap1 + ( (2) - (3) ) ) ] / (2)
            if union_fan_area > 0:
                aci3_score = (intersection_area - (dp1 + ap1 + excess_fan_area)) / union_fan_area
            else:
                aci3_score = float('-inf')

            return {
                'convex_hull_area': convex_hull_area,
                'union_fan_area': union_fan_area,
                'intersection_area': intersection_area,
                'uncovered_area': uncovered_area,
                'excess_fan_area': excess_fan_area,
                'points_in_union': points_in_union,
                'density': density,
                'dp1': dp1,
                'ap1': ap1,
                'aci3_score': aci3_score
            }

        except Exception:
            self.logger.error(f"Error calculating ACI3 metric")
            return None

    def calculate_evaluation_metric_aci4(self, real_array, imag_array, gain_array,
                                         phase_array, labels, k):
        """Calculate ACI4 metric
        ACI4 = [ (3) - ( dp1 + ap2 + ( (2) - (3) ) ) ] / (2)
        """
        try:
            # Component 1: Convex hull area
            _, _, convex_hull_area, _ = self.hull_calculator.calculate_convex_hull(real_array, imag_array)
            if convex_hull_area is None:
                # self.logger.warning(f"Convex hull calculation failed, skipping ACI4 calculation")
                return None

            # Component 2: Union of fan segments area
            cluster_polygons = []

            for cluster_id in range(k):
                cluster_mask = labels == cluster_id

                cluster_gain = gain_array[cluster_mask]
                cluster_phase = phase_array[cluster_mask]
                fan_polygon = self.fan_calculator.create_fan_polygon(cluster_gain, cluster_phase)

                if fan_polygon and fan_polygon.is_valid:
                    cluster_polygons.append(fan_polygon)

            union_polygon = unary_union(cluster_polygons)
            union_fan_area = union_polygon.area

            # Component 3: Intersection area
            hull_x, hull_y, _, _ = self.hull_calculator.calculate_convex_hull(real_array, imag_array)
            convex_hull_polygon = Polygon(np.column_stack([hull_x[:-1], hull_y[:-1]]))
            intersection_polygon = convex_hull_polygon.intersection(union_polygon)
            intersection_area = intersection_polygon.area

            # Component 4: Uncovered area
            uncovered_area = convex_hull_area - intersection_area

            # Excess fan area
            excess_fan_area = union_fan_area - intersection_area

            # Points for penalty calculations
            points = [Point(r, i) for r, i in zip(real_array, imag_array)]

            # Density penalty (dp1)
            points_in_union = sum(1 for point in points if union_polygon.contains(point))
            density = points_in_union / union_fan_area if union_fan_area > 0 else 0
            dp1 = 100 / density if density > 0 else float('inf')

            # Area penalty 2 (ap2)
            uncovered_polygon = convex_hull_polygon.difference(intersection_polygon)
            points_in_uncovered = sum(1 for point in points if uncovered_polygon.contains(point))

            if points_in_union > 0:
                ap2 = (points_in_uncovered / points_in_union) * uncovered_area
            else:
                ap2 = 0

            # ACI4 Formula = [ (3) - ( dp1 + ap2 + ( (2) - (3) ) ) ] / (2)
            if union_fan_area > 0:
                aci4_score = (intersection_area - (dp1 + ap2 + excess_fan_area)) / union_fan_area
            else:
                aci4_score = float('-inf')

            return {
                'convex_hull_area': convex_hull_area,
                'union_fan_area': union_fan_area,
                'intersection_area': intersection_area,
                'uncovered_area': uncovered_area,
                'excess_fan_area': excess_fan_area,
                'points_in_union': points_in_union,
                'points_in_uncovered': points_in_uncovered,
                'density': density,
                'dp1': dp1,
                'ap2': ap2,
                'aci4_score': aci4_score
            }

        except Exception:
            self.logger.error(f"Error calculating ACI4 metric")
            return None
