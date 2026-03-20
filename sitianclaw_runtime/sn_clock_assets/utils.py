#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Utility Functions for texp Prediction Pipeline
================================================

Shared utility functions used across all pipeline steps.
"""

import numpy as np
import pandas as pd
from pathlib import Path


# =============================================================================
# Filter Information
# =============================================================================

# Filter physics lookup table
FILTER_PHYSICS = {
    'r-ZTF': {'lambda_c': 642, 'survey': 'ZTF'},
    'g-ZTF': {'lambda_c': 472, 'survey': 'ZTF'},
    'i-ZTF': {'lambda_c': 783, 'survey': 'ZTF'},
    'orange-ATLAS': {'lambda_c': 679, 'survey': 'ATLAS'},
    'cyan-ATLAS': {'lambda_c': 533, 'survey': 'ATLAS'},
    'G-Gaia': {'lambda_c': 673, 'survey': 'GaiaAlerts'},
    'w-P1': {'lambda_c': 620, 'survey': 'Pan-STARRS'},
    'i-P1': {'lambda_c': 753, 'survey': 'Pan-STARRS'},
    'Unknown': {'lambda_c': 600, 'survey': 'Unknown'},
}

# Filter color mapping for visualization
FILTER_COLORS = {
    'ZTF_g': '#4daf4a',      # Green
    'ZTF_r': '#e41a1c',      # Red
    'ZTF_i': '#984ea3',      # Purple
    'ATLAS_o': '#ff7f00',    # Orange
    'ATLAS_c': '#377eb8',    # Cyan/Blue
    'Gaia': '#a65628',       # Brown
    'Pan-STARRS': '#f781bf', # Pink
    'Unknown': '#888888',    # Gray
}


def get_filter_info(filter_name):
    """
    Get filter central wavelength and survey name.

    Args:
        filter_name: Filter string (e.g., 'r-ZTF', 'orange-ATLAS', 'ZTF_g')

    Returns:
        tuple: (wavelength_nm, survey_name)
    """
    if pd.isna(filter_name):
        return 600, 'Unknown'

    f = str(filter_name).lower()

    if 'g' in f and 'ztf' in f:
        return 472, 'ZTF'
    elif 'r' in f and 'ztf' in f:
        return 642, 'ZTF'
    elif 'i' in f and 'ztf' in f:
        return 783, 'ZTF'
    elif 'orange' in f or 'o-atlas' in f or ('o' in f and 'atlas' in f):
        return 679, 'ATLAS'
    elif 'cyan' in f or 'c-atlas' in f or ('c' in f and 'atlas' in f):
        return 533, 'ATLAS'
    elif 'gaia' in f:
        return 673, 'Gaia'
    elif 'p1' in f or 'pan' in f:
        return 620, 'Pan-STARRS'

    return 600, 'Unknown'


def get_filter_color(filter_name):
    """
    Get matplotlib color for filter visualization.

    Args:
        filter_name: Filter string

    Returns:
        str: Hex color code
    """
    if pd.isna(filter_name):
        return '#888888'

    f = str(filter_name).lower()

    if 'g' in f and 'ztf' in f:
        return '#4daf4a'  # Green
    elif 'r' in f and 'ztf' in f:
        return '#e41a1c'  # Red
    elif 'i' in f and 'ztf' in f:
        return '#984ea3'  # Purple
    elif 'orange' in f or 'o-' in f or ('o' in f and 'atlas' in f):
        return '#ff7f00'  # Orange
    elif 'cyan' in f or 'c-' in f or ('c' in f and 'atlas' in f):
        return '#377eb8'  # Cyan/Blue
    elif 'gaia' in f:
        return '#a65628'  # Brown
    elif 'p1' in f or 'pan' in f:
        return '#f781bf'  # Pink

    return '#888888'  # Gray


def get_filter_label(filter_name):
    """
    Get short label for filter (for plotting).

    Args:
        filter_name: Filter string

    Returns:
        str: Short label (e.g., 'g', 'r', 'o', 'c')
    """
    if pd.isna(filter_name):
        return '?'
    f = str(filter_name)
    return f.split('-')[0] if '-' in f else f[:1]


def get_instrument(filter_name):
    """
    Get instrument/survey name from filter string.

    Args:
        filter_name: Filter string

    Returns:
        str: Instrument name (e.g., 'ZTF', 'ATLAS')
    """
    if pd.isna(filter_name):
        return 'Unknown'
    f = str(filter_name).lower()
    if 'ztf' in f:
        return 'ZTF'
    elif 'atlas' in f:
        return 'ATLAS'
    elif 'gaia' in f:
        return 'Gaia'
    elif 'p1' in f or 'pan' in f:
        return 'Pan-STARRS'
    # Try to extract from format like 'g-ZTF'
    parts = str(filter_name).split('-')
    return parts[-1] if len(parts) > 1 else 'Unknown'


# =============================================================================
# Flux/Magnitude Conversions
# =============================================================================

def flux_to_mag(flux_ujy, zeropoint=23.9):
    """
    Convert flux in microJansky to AB magnitude.

    Args:
        flux_ujy: Flux in microJansky
        zeropoint: AB magnitude zeropoint (default 23.9)

    Returns:
        float: AB magnitude (or np.nan if flux <= 0)
    """
    if flux_ujy <= 0:
        return np.nan
    return zeropoint - 2.5 * np.log10(flux_ujy)


def mag_to_flux(mag, zeropoint=23.9):
    """
    Convert AB magnitude to flux in microJansky.

    Args:
        mag: AB magnitude
        zeropoint: AB magnitude zeropoint (default 23.9)

    Returns:
        float: Flux in microJansky
    """
    return 10 ** ((zeropoint - mag) / 2.5)


# =============================================================================
# Statistical Utilities
# =============================================================================

def weighted_average(values, uncertainties):
    """
    Calculate weighted average and its uncertainty.

    Args:
        values: Array of values
        uncertainties: Array of uncertainties

    Returns:
        tuple: (weighted_mean, weighted_std)
    """
    values = np.array(values)
    uncertainties = np.array(uncertainties)

    # Handle zero uncertainties
    uncertainties = np.maximum(uncertainties, 1e-10)

    weights = 1.0 / (uncertainties ** 2)
    weighted_mean = np.average(values, weights=weights)
    weighted_std = 1.0 / np.sqrt(np.sum(weights))

    return weighted_mean, weighted_std


def safe_float(val):
    """
    Safely convert value to float.

    Args:
        val: Value to convert

    Returns:
        float or None if conversion fails
    """
    try:
        return float(val) if pd.notna(val) else None
    except (ValueError, TypeError):
        return None


# =============================================================================
# Time Utilities
# =============================================================================

def parse_mjd_from_iso(date_str):
    """
    Convert ISO date string to MJD.

    Args:
        date_str: Date string (e.g., '2020-01-15 12:30:00')

    Returns:
        float: Modified Julian Date, or None if parsing fails
    """
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        jd = dt.toordinal() + 1721424.5 + (dt.hour + dt.minute/60 + dt.second/3600) / 24
        return jd - 2400000.5
    except (ValueError, AttributeError):
        return None


# =============================================================================
# Cosmology Utilities
# =============================================================================

def calculate_distance_modulus(redshift, H0=70.0):
    """
    Calculate distance modulus from redshift (simple Hubble law).

    Args:
        redshift: Cosmological redshift
        H0: Hubble constant in km/s/Mpc

    Returns:
        float: Distance modulus
    """
    c = 299792.458  # km/s
    d_L = c * redshift / H0 * (1 + redshift / 2)  # Luminosity distance in Mpc

    if d_L <= 0:
        return 35.0  # Default for invalid redshift

    return 5 * np.log10(d_L * 1e6 / 10)
