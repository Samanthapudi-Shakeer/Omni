# -*- coding: utf-8 -*-
"""
/*********************************************************************
*
*  (C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation
*
*  This file is part of FRF Utility Package
*  File Name: frf_data_list_create.py
*  File Description: Utility script to generate data list from directory with config support
*  All rights reserved.
*
*********************************************************************/
"""

import os
import sys
import argparse
import glob
import re
import configparser
import ast


def extract_component_value(filename, component_prefix):
    """Generic function to extract any component value from filename

    Args:
        filename: Name of the .exv, .xpi or .xiz file
        component_prefix: Prefix to search for (e.g., 'HD', 'CYL', 'T')

    Returns:
        Component value as string or None if not found

    Examples:
        extract_component_value(filename, 'HD') -> 'HD0'
        extract_component_value(filename, 'CYL') -> 'CYL0007BD37'
        extract_component_value(filename, 'T') -> 'T001F'
    """
    # Pattern: _PREFIX followed by alphanumeric value until next underscore
    # For all components (HD, CYL, T), include the prefix in the result
    pattern = rf'_({component_prefix}[A-Z0-9]+)_'

    match = re.search(pattern, filename, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def _validate_list_elements(elements, param):
    """Validate that a list contains only flat string elements.

    Args:
        elements: List to validate
        param: Parameter name (used in error messages)

    Raises:
        ValueError: If any element is a nested list or a non-string type
    """
    for idx, element in enumerate(elements):
        if isinstance(element, list):
            raise ValueError(
                f"Parameter '{param}' contains a nested list at index {idx}.\n"
                f"       Only flat lists of strings are allowed.\n"
                f"       Found: {element}"
            )
        if not isinstance(element, str):
            raise ValueError(
                f"Parameter '{param}' contains non-string element at index {idx}.\n"
                f"       All elements must be strings.\n"
                f"       Found: {element} (type: {type(element).__name__})"
            )


def _parse_filter_param(config, param):
    """Parse and validate a single filter parameter from the config object.

    Args:
        config: ConfigParser object already loaded with the config file
        param: Parameter name to look up (e.g., 'head', 'cylinder', 'temperature')

    Returns:
        List of strings to filter by, or None when the empty-list sentinel [] is used.

    Raises:
        ValueError: On missing, blank, or malformed parameter values
    """
    if not config.has_option('FILE_LIST_PARAMETERS', param):
        raise ValueError(
            f"Missing required parameter '{param}' in config file\n"
            f"       Use {param} = [] for no filtering, or provide a list of values."
        )

    raw = config.get('FILE_LIST_PARAMETERS', param).strip()
    if not raw:
        raise ValueError(
            f"Parameter '{param}' cannot be left blank.\n"
            f"       Use {param} = [] for no filtering, or provide a list of values."
        )

    try:
        parsed_value = ast.literal_eval(raw)
    except (ValueError, SyntaxError) as exc:
        raise ValueError(
            f"Failed to parse '{param}': {raw}\n"
            f"       {exc}\n"
            f'       Expected format: ["value1", "value2"] or []'
        ) from exc

    # Empty list [] means "no filter"
    if isinstance(parsed_value, list) and len(parsed_value) == 0:
        return None

    if isinstance(parsed_value, str):
        return [parsed_value]

    if isinstance(parsed_value, list):
        _validate_list_elements(parsed_value, param)
        return parsed_value

    raise ValueError(
        f"Invalid format for '{param}': {raw}\n"
        f"       Expected a list of strings or []"
    )


def _extract_config_params(config):
    """Extract all required parameters from a loaded ConfigParser object.

    Args:
        config: ConfigParser object already loaded with the config file

    Returns:
        Dictionary with all parsed parameters.

    Raises:
        ValueError: On any missing or invalid parameter
    """
    params = {}

    if not config.has_option('FILE_LIST_PARAMETERS', 'directory_path'):
        raise ValueError("Missing required parameter 'directory_path' in config file")

    params['directory_path'] = config.get('FILE_LIST_PARAMETERS', 'directory_path').strip()

    for param in ['head', 'cylinder', 'temperature']:
        params[param] = _parse_filter_param(config, param)

    output_key = 'file_list_output_path'
    if config.has_option('FILE_LIST_PARAMETERS', output_key):
        raw = config.get('FILE_LIST_PARAMETERS', output_key).strip()
        params[output_key] = raw if raw else None
    else:
        params[output_key] = None

    return params


def parse_config_file(config_path):
    """Parse configuration file and return parameters

    Args:
        config_path: Path to configuration file

    Returns:
        Dictionary with parsed parameters, or None on any error
    """
    result = None
    if os.path.exists(config_path):
        try:
            config = configparser.ConfigParser()
            # Preserve case sensitivity
            config.optionxform = str
            config.read(config_path)
            result = _extract_config_params(config)
        except Exception as exc:
            # ValueError carries user-friendly validation messages; all other
            # exceptions get an additional context prefix.
            prefix = "" if isinstance(exc, ValueError) else "Failed to parse config file: "
            print(f"ERROR: {prefix}{exc}")
    else:
        print(f"ERROR: Configuration file does not exist: {config_path}")

    return result


def _validate_txt_output_path(output_path):
    """Validate a fully-specified .txt output file path.

    Args:
        output_path: Full path ending in '.txt'

    Returns:
        Tuple of (parent_dir, filename)

    Raises:
        ValueError: If the parent directory does not exist or is not a directory
    """
    parent_dir = os.path.dirname(output_path)
    filename = os.path.basename(output_path)

    if not os.path.exists(parent_dir):
        raise ValueError(f"Output directory does not exist: {parent_dir}")

    if not os.path.isdir(parent_dir):
        raise ValueError(f"Output path parent is not a directory: {parent_dir}")

    if os.path.exists(output_path):
        print(f"WARNING: Output file already exists and will be overwritten: {filename}")

    return parent_dir, filename


def _validate_dir_output_path(output_path):
    """Validate a directory-only output path.

    Args:
        output_path: Path to an existing directory

    Returns:
        Tuple of (output_dir, None)

    Raises:
        ValueError: If the path does not exist or is not a directory
    """
    output_dir = os.path.normpath(output_path)

    if not os.path.exists(output_dir):
        raise ValueError(f"Output directory does not exist: {output_dir}")

    if not os.path.isdir(output_dir):
        raise ValueError(f"Output path is not a directory: {output_dir}")

    return output_dir, None


def validate_output_path(output_path):
    """Validate the custom output path

    Args:
        output_path: Custom output path (can be directory or full file path)

    Returns:
        Tuple of (output_dir, output_filename) or (None, None) if invalid
    """
    output_dir, output_filename = None, None

    if output_path:
        try:
            if output_path.endswith('.txt'):
                output_dir, output_filename = _validate_txt_output_path(output_path)
            else:
                output_dir, output_filename = _validate_dir_output_path(output_path)
        except ValueError as exc:
            print(f"ERROR: {exc}")

    return output_dir, output_filename


def _collect_data_files(directory_path):
    """Validate the directory and collect all .exv, .xpi, .xiz files within it.

    Args:
        directory_path: Path to the target directory

    Returns:
        List of matched file paths, or None on validation failure / no files found
    """
    if not os.path.isdir(directory_path):
        if not os.path.exists(directory_path):
            print(f"ERROR: Directory does not exist: {directory_path}")
        else:
            print(f"ERROR: Path is not a directory: {directory_path}")
        return None

    data_files = []
    for ext in ['*.exv', '*.xpi', '*.xiz']:
        data_files.extend(glob.glob(os.path.join(directory_path, ext)))

    if not data_files:
        print(f"WARNING: No data files (.exv, .xpi, .xiz) found in directory: {directory_path}")
        return None

    print(f"Found {len(data_files)} total .exv, .xpi or .xiz files in directory")
    return data_files


def _passes_filters(filename, head_values, cylinder_values, temperature_values):
    """Check whether a single filename passes all active component filters.

    Args:
        filename: Basename of the data file
        head_values: Normalised head filter list, or None for no filter
        cylinder_values: Normalised cylinder filter list, or None for no filter
        temperature_values: Normalised temperature filter list, or None for no filter

    Returns:
        True if the file passes every active filter, False otherwise
    """
    file_head = extract_component_value(filename, 'HD')
    file_cyl = extract_component_value(filename, 'CYL')
    file_temp = extract_component_value(filename, 'T')

    passes_head = (head_values is None) or (file_head and file_head in head_values)
    passes_cyl = (cylinder_values is None) or (file_cyl and file_cyl in cylinder_values)
    passes_temp = (temperature_values is None) or (file_temp and file_temp in temperature_values)

    return passes_head and passes_cyl and passes_temp


def _apply_filters(data_files, head_values, cylinder_values, temperature_values):
    """Normalise filter value cases, log active filters, and return matching files.

    Args:
        data_files: Full list of candidate file paths
        head_values: Raw head filter list, or None
        cylinder_values: Raw cylinder filter list, or None
        temperature_values: Raw temperature filter list, or None

    Returns:
        Filtered list of file paths
    """
    if head_values:
        head_values = [h.upper() for h in head_values]
        print(f"Filtering by HEAD values: {head_values}")
    if cylinder_values:
        cylinder_values = [c.upper() for c in cylinder_values]
        print(f"Filtering by CYLINDER values: {cylinder_values}")
    if temperature_values:
        temperature_values = [t.upper() for t in temperature_values]
        print(f"Filtering by TEMPERATURE values: {temperature_values}")

    return [
        f for f in data_files
        if _passes_filters(os.path.basename(f), head_values, cylinder_values, temperature_values)
    ]


def _resolve_output_path(directory_path, custom_output_dir, custom_output_filename):
    """Determine the final output file path from the available path components.

    Args:
        directory_path: Source data directory (used to derive a default filename)
        custom_output_dir: Custom output directory, or None
        custom_output_filename: Custom output filename, or None

    Returns:
        Normalised absolute path string for the output .txt file
    """
    dir_basename = os.path.basename(os.path.normpath(directory_path))
    output_filename = custom_output_filename or f"{dir_basename}_file_list.txt"

    if custom_output_dir:
        return os.path.normpath(os.path.join(custom_output_dir, output_filename))

    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, output_filename))


def _write_file_list(output_path, absolute_paths):
    """Write the sorted list of absolute paths to the output file.

    Args:
        output_path: Destination file path
        absolute_paths: Sorted list of absolute file path strings

    Returns:
        output_path on success, or None on write failure
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            for path in absolute_paths:
                f.write(f"{path}\n")

        print(f"\nSUCCESS: Generated file list with {len(absolute_paths)} files")
        print(f"Output file: {output_path}")
        return output_path
    except Exception as exc:
        print(f"ERROR: Failed to write output file: {exc}")
        return None


def generate_file_list(directory_path, head_values=None, cylinder_values=None,
                       temperature_values=None, custom_output_dir=None, custom_output_filename=None):
    """Generate text file containing absolute paths of filtered .exv, .xpi, .xiz files

    Args:
        directory_path: Path to directory containing .exv, .xpi or .xiz files
        head_values: Optional list of head values to filter by (e.g., ['HD0', 'HD1'])
        cylinder_values: Optional list of cylinder values to filter by (e.g., ['CYL0007BD37', 'CYL0007BD38'])
        temperature_values: Optional list of temperature values to filter by (e.g., ['T001F', 'T002F'])
        custom_output_dir: Optional custom output directory
        custom_output_filename: Optional custom output filename

    Returns:
        Path to generated text file, or None if error
    """
    data_files = _collect_data_files(directory_path)
    if data_files is None:
        return None

    filtered_files = _apply_filters(data_files, head_values, cylinder_values, temperature_values)

    if not filtered_files:
        print(f"WARNING: No data files found matching the specified filters")
        print(f"Total data files in directory: {len(data_files)}")
        return None

    print(f"Filtered to {len(filtered_files)} files matching all criteria")

    absolute_paths = sorted(os.path.abspath(f) for f in filtered_files)
    output_path = _resolve_output_path(directory_path, custom_output_dir, custom_output_filename)
    return _write_file_list(output_path, absolute_paths)


def main():
    """Entry point for the application"""
    parser = argparse.ArgumentParser(
        description="Generate text file containing absolute paths of filtered .exv, .xpi or .xiz files"
    )

    # Configuration file option (required)
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        metavar='CONFIG_FILE',
        help='Path to configuration file (.cfg) - REQUIRED'
    )

    args = parser.parse_args()

    # Load parameters from config file
    print(f"Loading parameters from configuration file: {args.config}")
    params = parse_config_file(args.config)
    if params is None:
        sys.exit(1)

    directory_path = params['directory_path']
    head_values = params['head']
    cylinder_values = params['cylinder']
    temperature_values = params['temperature']
    file_list_output_path = params.get('file_list_output_path')

    # Validate directory path
    if not directory_path:
        print("ERROR: Directory path cannot be empty")
        sys.exit(1)

    # Validate and parse custom output path (if provided)
    custom_output_dir = None
    custom_output_filename = None

    if file_list_output_path:
        custom_output_dir, custom_output_filename = validate_output_path(file_list_output_path)
        if custom_output_dir is None:
            # Validation failed
            sys.exit(1)

    # Generate file list
    result = generate_file_list(
        directory_path,
        head_values=head_values,
        cylinder_values=cylinder_values,
        temperature_values=temperature_values,
        custom_output_dir=custom_output_dir,
        custom_output_filename=custom_output_filename
    )

    sys.exit(0 if result is not None else 1)


if __name__ == "__main__":
    main()
