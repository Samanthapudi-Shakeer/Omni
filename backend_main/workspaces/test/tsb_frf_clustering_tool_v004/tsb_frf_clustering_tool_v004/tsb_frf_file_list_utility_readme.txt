* Company names and product names mentioned in this document
  are corporate trademarks or registered trademarks.
* "TM", "(R)", and "(C)" are omitted in this document.
(C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation

=================================================================================================================
[1] Introduction
=================================================================================================================
    - This readme file describes the procedure to use the below package:
        - FRF File List Utility Package

    - FRF File List Utility Package is used to create ".txt" files that are given as input for the FRF Clustering Training Application, FRF Clustering Inference Application and FRF Merge Utility.

        - This tool outputs a ".txt" file that contains the absolute paths of the data files present in the "directory_path" provided in the "data_list_config.cfg".

=================================================================================================================
[2] Package Structure
=================================================================================================================
    - Unzip and extract the "tsb_frf_clustering_tool_v004.zip" package and navigate to the directory having "tsb_frf_clustering_tool_v004".

    - Navigate to the directory "tsb_frf_file_list_utility".

    - Following directory structure is present in "tsb_frf_file_list_utility" directory.

             tsb_frf_clustering_tool_v004
                ├── [DIR] tsb_frf_file_list_utility
                |            ├── [PY] frf_data_list_create.py
                |            └── [CFG] data_list_config.cfg
                ├── [TXT] tsb_frf_file_list_utility_readme.txt
                └── [TXT] tsb_frf_clustering_tool_requirements.txt

    - "tsb_frf_file_list_utility":
            - Sub-directory includes the utility script "frf_data_list_create.py" for creating the text file which contains the absolute paths of the data files to be used in configs for "tsb_frf_clustering_training_application", "tsb_frf_clustering_inference_application" and "tsb_frf_merge_utility".

=================================================================================================================
[3] Execution of File List Utility Script
=================================================================================================================
    - The python script provided in the file list utility directory, "frf_data_list_create.py" can be used to create a ".txt" file for the training application, inference applications and merge utility.

    - In order to use "frf_data_list_create.py", config provided for the file list utility script, "data_list_config.cfg" has to be updated.

    - After updating "data_list_config.cfg" to the desired configuration, run the following command:
      (frf_hdd) $ python frf_data_list_create.py --config data_list_config.cfg

    - Output
        A successful run of the tool generates:
        (1) <file_list>.txt: A ".txt" file that contains the absolute paths of the data files present in the directory provided in the "data_list_config.cfg".

=================================================================================================================
[4] Assumptions and Constraints
=================================================================================================================

    (1) The data filenames must follow the nomenclature "<drive_name>_<head>_<cylinder>_<temperature>_<use_case>".
    (2) Only three file extensions are supported: ".exv", ".xpi" and ".xiz".
    (3) File extensions are case-sensitive and must be lowercase.
    (4) Head identifiers always start with "HD", cylinder identifiers always start with "CYL" and temperature identifiers always start with "T".
    (5) Empty list "[]" is used to indicate no filtering for a parameter.
    (6) When multiple filters are specified, they operate with "AND" logic.
    (7) A file must match all active filters to be included in the output.
    (8) "directory_path", "head", "cylinder", "temperature" and "file_list_output_path" must all be present in config file.
    (9) Filter parameters cannot be left empty; must contain either "[]" or a list of values.
    (10) The directory specified in "directory_path" must exist before execution.
    (11) If custom output path is specified, the parent directory must exist.
    (12) The script only processes files in the top-level directory (no recursion).
    (13) If output file already exists, it will be overwritten.
    (14) Output file paths are always sorted alphabetically.

=================================================================================================================
[5] Revision
=================================================================================================================

2026/01/16 - v001 Release
    - Release of the FRF File List Utility.
    - Supports the following functionalities: creation of a ".txt" file containing absolute paths of the data files.

2026/02/13 - v002 Release
    - Release of the FRF File List Utility.

2026/05/25 - v003 Release
    - Release of the FRF File List Utility.

2026/09/24 - v004 Release
    - Release of the FRF File List Utility.