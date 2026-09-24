# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Clustering Inference Application Package
*  File Name: frf_inference_metric_components.py
*  File Description: File that defines the functions used for the calculation of metrics.
*  All rights reserved.
*
*********************************************************************/
"""

import numpy as np
from scipy.spatial import ConvexHull
from shapely.geometry import Polygon
import logging


class CircularStatistics(object):
    """Handles circular statistics calculations for phase data"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def circular_mean_deg(deg):
        """Calculate circular mean in degrees"""
        rad = np.radians(deg)
        c = np.mean(np.cos(rad))
        s = np.mean(np.sin(rad))
        return np.degrees(np.arctan2(s, c))

    def circular_std_deg(self, deg):
        """Calculate circular standard deviation with robust error handling"""
        if len(deg) == 0:
            # self.logger.warning("Empty array provided to circular_std_deg, returning 0")
            return 0

        # Check for NaN or Inf
        if np.any(np.isnan(deg)) or np.any(np.isinf(deg)):
            self.logger.warning("NaN or Inf values in phase data, filtering them out")
            deg = deg[~(np.isnan(deg) | np.isinf(deg))]

        rad = np.radians(deg)
        c = np.mean(np.cos(rad))
        s = np.mean(np.sin(rad))
        R = np.sqrt(c**2 + s**2)

        try:
            std = np.degrees(np.sqrt(-2 * np.log(R)))

            return std

        except Exception:
            self.logger.error(f"Error in circular_std_deg, R={R}")
            return 0


class CoordinateConverter(object):
    """Handles coordinate system conversions"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def gain_phase_to_complex(gain_db, phase_deg):
        """Convert gain (dB) and phase (degrees) to complex coordinates"""
        magnitude = 10 ** (gain_db / 20)
        phase_rad = np.radians(phase_deg)
        real_part = magnitude * np.cos(phase_rad)
        imaginary_part = magnitude * np.sin(phase_rad)
        return real_part, imaginary_part


class CurveProcessor(object):
    """Shared 1-D curve preprocessing: per-curve [-1, 1] min-max normalization and linear
    detrend. Used identically for per-file feature scaling and baseline phase-lead/
    phase-lag/no-resonance classification — the single canonical implementation both share."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def normalize_curve_to_range(curve):
        """Normalize a 1-D curve to [-1, 1] using per-curve min-max scaling.

        Returns an all-zero curve when the curve is constant (max == min).
        """
        c_min = np.min(curve)
        c_max = np.max(curve)
        if c_max - c_min < 1e-10:
            return np.zeros_like(curve, dtype=float)
        return 2.0 * (curve - c_min) / (c_max - c_min) - 1.0

    @staticmethod
    def compute_trend_line(curve, freqs):
        """Compute the degree-1 linear trend line for a 1-D curve."""
        coeffs = np.polyfit(freqs, curve, 1)
        return np.polyval(coeffs, freqs)

    @staticmethod
    def detrend_curve(curve, freqs):
        """Remove the linear trend from a 1-D curve."""
        return curve - CurveProcessor.compute_trend_line(curve, freqs)


class ConvexHullCalculator(object):
    """Handles convex hull calculations and analysis"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def calculate_polygon_perimeter(x_coords, y_coords):
        """Calculate perimeter of a polygon"""
        perimeter = 0
        for i in range(len(x_coords)):
            j = (i + 1) % len(x_coords)
            perimeter += np.sqrt((x_coords[j] - x_coords[i])**2 + (y_coords[j] - y_coords[i])**2)
        return perimeter

    def calculate_convex_hull(self, real_data, imag_data):
        """Calculate convex hull of the data points

        Returns:
            tuple: (hull_x, hull_y, hull_area, coverage_stats) on success
                (None, None, None, None) on failure
        """
        points = np.column_stack((real_data, imag_data))

        # Check if all points are identical
        if np.allclose(points, points[0]):
            # self.logger.warning(error_msg)
            return None, None, None, None

        try:
            hull = ConvexHull(points)
        except Exception:
            # self.logger.error(f"Point statistics: mean={np.mean(points, axis=0)}, std={np.std(points, axis=0)}")
            return None, None, None, None

        hull_points = points[hull.vertices]
        hull_x = hull_points[:, 0]
        hull_y = hull_points[:, 1]
        hull_x = np.append(hull_x, hull_x[0])
        hull_y = np.append(hull_y, hull_y[0])
        hull_area = hull.volume
        data_spread = np.sqrt(np.var(real_data) + np.var(imag_data))
        hull_perimeter = self.calculate_polygon_perimeter(hull_x[:-1], hull_y[:-1])

        coverage_stats = {
            'area': hull_area,
            'perimeter': hull_perimeter,
            'data_spread': data_spread,
            'num_vertices': len(hull.vertices),
            'coverage_rate': 1.0,
            'compactness': hull_area / (hull_perimeter**2) if hull_perimeter > 0 else 0
        }

        return hull_x, hull_y, hull_area, coverage_stats


class FanSegmentCalculator(object):
    """Handles 3-sigma fan segment calculations"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.circular_stats = CircularStatistics()
        self.coordinate_converter = CoordinateConverter()

    def calculate_3sigma_fan_arc(self, gain_data, phase_data, num_points=100):
        """Calculate 3-sigma fan-type arc segment and return polygon coordinates"""
        avg_gain = np.mean(gain_data)
        avg_phase = self.circular_stats.circular_mean_deg(phase_data)
        sigma_gain = np.std(gain_data)
        sigma_phase = self.circular_stats.circular_std_deg(phase_data)

        gain_upper = avg_gain + 3 * sigma_gain
        gain_lower = avg_gain - 3 * sigma_gain
        phase_upper = avg_phase + 3 * sigma_phase
        phase_lower = avg_phase - 3 * sigma_phase

        mag_upper = 10 ** (gain_upper / 20)
        mag_lower = 10 ** (gain_lower / 20)

        avg_real, avg_imag = self.coordinate_converter.gain_phase_to_complex(avg_gain, avg_phase)

        phase_range = np.linspace(np.radians(phase_lower), np.radians(phase_upper), num_points)
        outer_real = mag_upper * np.cos(phase_range)
        outer_imag = mag_upper * np.sin(phase_range)
        inner_real = mag_lower * np.cos(phase_range)
        inner_imag = mag_lower * np.sin(phase_range)

        # Create polygon coordinates for shapely
        fan_coords = np.concatenate([
            np.column_stack([inner_real, inner_imag]),
            np.column_stack([outer_real[::-1], outer_imag[::-1]])
        ])

        return avg_real, avg_imag, outer_real, outer_imag, inner_real, inner_imag, fan_coords

    def create_fan_polygon(self, gain_data, phase_data):
        """Create a Shapely polygon from fan arc coordinates"""

        # Check for NaN or Inf
        if np.any(np.isnan(gain_data)) or np.any(np.isinf(gain_data)):
            valid_mask = ~(np.isnan(gain_data) | np.isinf(gain_data) | np.isnan(phase_data) | np.isinf(phase_data))
            gain_data = gain_data[valid_mask]
            phase_data = phase_data[valid_mask]

        try:
            _, _, _, _, _, _, fan_coords = self.calculate_3sigma_fan_arc(gain_data, phase_data)

            polygon = Polygon(fan_coords)

            if not polygon.is_valid:
                polygon = polygon.buffer(0)

                if not polygon.is_valid:
                    return None

            return polygon

        except Exception:
            return None
