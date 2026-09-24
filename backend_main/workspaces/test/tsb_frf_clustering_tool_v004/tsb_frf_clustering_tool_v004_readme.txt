* Company names and product names mentioned in this document
  are corporate trademarks or registered trademarks.
* "TM", "(R)", and "(C)" are omitted in this document.
(C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation

=================================================================================================================
[1] Introduction
=================================================================================================================
    - This readme file describes the procedure to use the below package:
        - tsb_frf_clustering_tool_v004.zip - v004 release

    - This tool contains two applications:
        - FRF Clustering Training Application
        - FRF Clustering Inference Application

    - FRF Clustering Training Application is used for Training using the Time Series K-Means clustering algorithm on the Frequency Response Functions of MA and VCM data

        - This tool outputs consolidated training summary for the dataset, bode plot visualizations, cluster plots, drive-wise cluster assignment CSVs and trained models which are used for inference tasks

    - FRF Clustering Inference Application is used for Inference using the Time Series K-Means clustering algorithm on the Frequency Response Functions of MA and VCM data

        - This tool outputs consolidated training summary for the dataset, bode plot visualizations, cluster plots, drive-wise cluster assignment CSVs

    - FRF Clustering Training Application and FRF Clustering Inference Application work in tandem towards helping design optimal notch filters for HDDs

=================================================================================================================
[2] PC Environment
=================================================================================================================
    - Hardware Requirements.
        - PC running Ubuntu 22.04 LTS (64-bit) OS with minimum 16 GB RAM

    - Software Requirements.
        - Python version = 3.10.12

        Note:
           - Required packages versions are mentioned below
              - DateTime                     6.0
              - configparser                 2.11.0
              - numpy                        1.24.2
              - pandas                       1.5.3
              - scikit-learn                 1.2.2
              - tslearn                      2.11.0
              - matplotlib                   3.11.0
              - scipy                        1.15.3
              - shapely                      2.1.1
              - plotly                       6.2.0
              - h5py                         3.12.1
              - kneed                        0.8.6

=================================================================================================================
[3] Creation of Python Virtual Environment & Installation of Software Dependencies
=================================================================================================================
    - Download python - 3.10 > from https://www.python.org/downloads/

      Note: Ensure to tick the checkbox "Add Python 3.10 > to PATH" during Python 3.10 > installation

    - Check the python version
      $ python -V

    - Creation of python virtual environment for windows:
      - Navigate to a directory where the python virtual environment is intended to be created.

      - Install virtualenv library, which is used to create python virtual environment.
        $ pip install virtualenv

      - Create a python virtual environment named "frf_hdd" in the same directory.
        $ python -m venv frf_hdd

      - To enable the python virtual environment, execute the following command from the same directory where the environment is created.
        - For Windows: $ frf_hdd\Scripts\activate

        - For Linux: $ source frf_hdd/bin/activate

    - Installation of required packages
        - Navigate to the directory with the "tsb_frf_clustering_tool_v004.zip" package and extract using the following command.
          (frf_hdd) $ unzip tsb_frf_clustering_tool_v004.zip

        - Navigate to the directory having tsb_frf_clustering_tool_v004.
          (frf_hdd) $ cd tsb_frf_clustering_tool_v004

        - "tsb_frf_clustering_tool_v004" contains "tsb_frf_clustering_tool_requirements.txt". Install all required packages by executing the following command.
          (frf_hdd) $ pip install -r tsb_frf_clustering_tool_requirements.txt

        - After execution of the above step, the packages that are installed can be verified by executing the following command.
          (frf_hdd) $ pip list

=================================================================================================================
[4] How to Extract package
=================================================================================================================
    - Unzip and extract the "tsb_frf_clustering_tool_v004.zip" package.

    - Navigate to the directory having "tsb_frf_clustering_tool_v004".

    - Following directory structure is present in "tsb_frf_clustering_tool_v004" directory.

             tsb_frf_clustering_tool_v004
                ├── [TXT] tsb_frf_file_list_utility_readme.txt
                ├── [DIR] tsb_frf_file_list_utility
                |            ├── [PY] frf_data_list_create.py
                |            └── [CFG] data_list_config.cfg
                ├── [TXT] tsb_frf_merge_utility_readme.txt
                ├── [DIR] tsb_frf_merge_utility
                |            ├── [PY] frf_merge_utility.py
                |            ├── [PY] frf_merge_plotting.py
                |            ├── [PY] frf_merge_model.py
                |            ├── [PY] frf_merge_data.py
                |            ├── [PY] frf_merge_config_loader.py
                |            └── [CFG] merge_config.cfg
                ├── [TXT] tsb_frf_clustering_training_application_readme.txt
                ├── [DIR] tsb_frf_clustering_training_application
                |            ├── [PY] frf_training_application.py
                |            ├── [PY] frf_training_application_processors.py
                |            ├── [PY] frf_clustering_base.py
                |            ├── [PY] frf_clustering_base_metrics.py
                |            ├── [PY] frf_clustering_normal.py
                |            ├── [PY] frf_clustering_hierarchical_s1.py
                |            ├── [PY] frf_clustering_hierarchical_s2.py
                |            ├── [PY] frf_clustering_utils.py
                |            ├── [PY] frf_config_loader.py
                |            ├── [PY] frf_config_utils.py
                |            ├── [PY] frf_centroid_merge.py
                |            ├── [PY] frf_centroid_metrics.py
                |            ├── [PY] frf_plots.py
                |            ├── [PY] frf_plots_optional.py
                |            ├── [PY] frf_bode_plots.py
                |            ├── [PY] frf_metrics.py
                |            ├── [PY] frf_metric_components.py
                |            ├── [PY] frf_output_config.py
                |            ├── [PY] frf_utils.py
                |            └── [DIR] frf_config
                |                        └── [CFG] config.cfg
                ├── [TXT] tsb_frf_clustering_inference_application_readme.txt
                ├── [DIR] tsb_frf_clustering_inference_application
                |            ├── [PY] frf_inference_application.py
                |            ├── [PY] frf_inference_segment_processor.py
                |            ├── [PY] frf_inference_segment_utility.py
                |            ├── [PY] frf_inference_clustering.py
                |            ├── [PY] frf_inference_centroid_metrics.py
                |            ├── [PY] frf_inference_data_utils.py
                |            ├── [PY] frf_inference_config_loader.py
                |            ├── [PY] frf_inference_config_validators.py
                |            ├── [PY] frf_inference_config_utils.py
                |            ├── [PY] frf_inference_plots.py
                |            ├── [PY] frf_inference_bode_plots.py
                |            ├── [PY] frf_inference_metrics.py
                |            ├── [PY] frf_inference_metric_components.py
                |            ├── [PY] frf_inference_utils.py
                |            └── [DIR] frf_inference_config
                └── [TXT] tsb_frf_clustering_tool_requirements.txt

    - "tsb_frf_file_list_utility":
            - Sub-directory includes the utility script "frf_data_list_create.py" for creating the text file which contains the absolute paths of the data files to be used in configs for "tsb_frf_clustering_training_application", "tsb_frf_clustering_inference_application" and "tsb_frf_merge_utility".

            - To use the utility script "frf_data_list_create.py", "data_list_config.cfg" must be modified according to the requirements.

			- Please refer to "tsb_frf_file_list_utility_readme.txt" for the execution steps of "tsb_frf_file_list_utility" package.

    - "tsb_frf_clustering_training_application":
            - Directory containing the source code files for execution of the FRF Clustering Training Application.

			- Please refer to "tsb_frf_clustering_training_application_readme.txt" for the execution steps of "tsb_frf_clustering_training_application" package.

    - "tsb_frf_clustering_inference_application":
            - Directory containing the source code files for execution of the FRF Clustering Inference Application.

			- Please refer to "tsb_frf_clustering_inference_application_readme.txt" for the execution steps of "tsb_frf_clustering_inference_application" package.

    - "tsb_frf_merge_utility":
            - Sub-directory includes the utility scripts for manually merging clusters based on the specifications given in the config file.

            - To use the "tsb_frf_merge_utility", "merge_utility.cfg" must be modified according to the requirements.

			- Please refer to "tsb_frf_merge_utility_readme.txt" for the execution steps of "tsb_frf_merge_utility" package.

=================================================================================================================
[5] Assumptions and Constraints
=================================================================================================================
    - Assumptions

        (1) The first file listed in the "directory_path" of the "data_list_config.cfg" is assumed to be correct and used as reference file in the "tsb_frf_clustering_training_application" and "tsb_frf_clustering_inference_application".
        (2) "END" string should be present at the end of data files.
        (3) First 9 rows in the data files have no frequency, gain and phase values / information.
        (4) The length of the frequencies and the individual frequencies must be exactly same throughout the measured data files and the worst model files.
        (5) The data filenames must follow the nomenclature "<drive_name>_<head>_<cylinder>_<temperature>_<use_case>".

    - Constraints

        (1) The config files are to be stored in the config directory within the application packages.
        (2) The "input_inference_config.cfg" generated by the "tsb_frf_clustering_training_application" is to be used as the input config for the "tsb_frf_clustering_inference_application".
        (3) Minimum 100 sample files per head should be present for the execution of training application.
        (4) The tool relies on "Plotly" and "Matplotlib" to generate visualizations, which may be slow for very large datasets.
        (5) When in the config, "individual_frequencies_cluster_assignment_plots = True", the application will take longer to run as "2D cluster assignment plots" and "2D fan segment plots" for each frequency are generated separately.
        (6) In "input_inference_config.cfg", only the "INFERENCE_APPLICATION_REQUIRED_PARAMETER" should be updated as per requirements, and the "TRAINING_APPLICATION_SPECIFICATIONS" should be unchanged as they are the specifications generated directly as a result of the training application. If "TRAINING_APPLICATION_SPECIFICATIONS" are changed, then "tsb_frf_clustering_inference_application" will behave unexpectedly.
        (7) Microsoft Excel cannot open CSV files if the full file path exceeds 259 characters due to Excel's path length limitation in Windows 11 Pro.
        (8) The FRF Clustering Tool has been validated for primary functional workflows. While error-handling mechanisms for abnormal scenarios have been implemented, comprehensive validation across all possible edge-case conditions remains ongoing.
        (9) The model's paths provided in the "merge_config.cfg" should be from the same root directory as the feature config path.
        (10) To represent pre and post merge cluster counts, output file names have been updated to contain both "k" values. The original k is represented as "orig<k>" and the merged k is represented after the as "orig<k>_k<merged_k>".
        (11) The iterative centroid update runs for a maximum of 30 passes and stops early only once the last 5 passes' reassignment counts all fall within 50 files of each other.
        (12) Only the final (plateaued or 30th-pass) forward-pass result is saved to "model.json" and the centroid text files.
        (13) The nomenclature of the output files are updated to shorter names for easier path handling. In place, several abbreviations are used as below:
              -------------------------------------
              | Label               | Abbreviation|
              -------------------------------------
              | centroid            | cen         |
              | stage1              | s1          |
              | stage2              | s2          |
              | bode                | b           |
              | drive               | d           |
              | cluster(s)/clustered| c           |
              | frequency           | f           |
              | gain                | g           |
              | phase               | p           |
              | original            | orig/o      |
              | interactive         | int         |
              | trajectories        | traj        |
              | hierarchical        | h           |
              -------------------------------------

=================================================================================================================
[6] OSS Licenses
=================================================================================================================
    (1) DateTime: https://github.com/doublep/datetime/blob/master/LICENSE
    (2) configparser: https://github.com/dzilles/configparser/blob/master/LICENSE
    (3) numpy: https://numpy.org/doc/stable/license.html
    (4) pandas: https://pandas.pydata.org/docs/getting_started/overview.html#license
    (5) scikit-learn: https://github.com/scikit-learn/scikit-learn/blob/main/COPYING
    (6) tslearn: https://github.com/tslearn-team/tslearn/blob/main/LICENSE
    (7) matplotlib: https://matplotlib.org/stable/project/license.html
    (8) scipy: https://github.com/scipy/scipy/blob/main/LICENSE.txt
    (9) shapely: https://github.com/shapely/shapely/blob/main/LICENSE.txt
    (10) plotly: https://github.com/plotly/plotly.js/blob/master/LICENSE
    (11) h5py: https://github.com/h5py/h5py/blob/master/LICENSE
    (12) kneed: https://github.com/arvkevi/kneed/blob/main/LICENSE

=================================================================================================================
[7] Revision
=================================================================================================================

2026/01/16 - v001 Release
    - Supports the following functionalities: input handling, summary csv creation, clustering training results, clustering inferencing results, metric comparisons and static and interactive EDA plots.
    - Includes FRF Clustering Training Application and FRF Clustering Inference Application.

2026/02/13 - v002 Release
    - Includes the following modifications:
      1. "tsb_frf_clustering_training_application" ->
        a. New parameter "output_path" added in the configuration file, to set the path where the output directory will be generated.
        b. All the paths in the "input_inference_config.cfg" are now recorded as relative paths.
        c. Centroid lines in the Bode plot for each cluster are generated by back-transforming the learned centroid lines from the complex plane, and are saved in .txt format for visualization/representation purposes.

      2. "tsb_frf_clustering_inference_application" ->
        a. New parameters "root_dir" and "output_path" added in the configuration file.
        b. "root_dir" is used to set the path to the analysis folder generated from "tsb_frf_clustering_training_application" that contains the trained models.
        c. "output_path" is used to set the path where the output directory will be generated.

2026/05/29 - v003 Release
    - Includes the following modifications:
      1. "tsb_frf_clustering_training_application" ->
        a. New clustering approach "Hierarchical Clustering" added to the training application, which takes a two stage approach for clustering FRF data.
        b. New preprocessing step called "Meanline Data Separation" added to the training application, which is a preprocessing step for segregating the data files into phase lead and phase lag and perform clustering on them individually.
        c. 6 new features relating to second derivation, peak prominence and moving averages added to the training application.
        d. Bode plot centroid only visualization updated to include total file counts for a respective cluster in the legend.
        e. Gain Phase vs Frequency plot updated for higher resolution.
        f. "feature_config.json" updated to include both Stage 1 clustering and Stage 2 clustering features.
        g. "segment_meanline.json" created that stores the meanline used for data separation.

      2. "tsb_frf_clustering_inference_application" ->
        a. New clustering approach "Hierarchical Clustering" added to the inference application, which takes a two stage approach for clustering FRF data.
        b. New preprocessing step called "Meanline Data Separation" added to the inference application, which is a preprocessing step for segregating the data files into phase lead and phase lag and perform clustering on them individually.
        c. 6 new features relating to second derivation, peak prominence and moving averages added to the training application.
        d. Bode plot centroid only visualization updated to include total file counts for a respective cluster in the legend.
        e. Gain Phase vs Frequency plot updated for higher resolution.
        f. Dynamic understanding of the specification used for training application for exact inference application execution.

2026/09/24 - v004 Release
    - Includes the following modifications:
      1. "tsb_frf_clustering_training_application" ->
        a. Preprocessing is updated from standard scaler (mean and standard deviation) to normalization from [-1, 1] + detrending.
        b. "Meanline Data Separation" is updated to "Baseline Data Separation", which is a preprocessing step for segregating the data files into phase lead, phase lag and no resonance sub-groups.
        c. 3 new centroid related metrics are added, these are: Correlation, RMSE and Wasserstein. These are used for centroid merging operations.
        d. 3 new centroid related visualizations are added, namely: Centroid Elbow plot (mean clustering score comparison of new metrics), Centroid Heatmaps (centroid score comparison against each other) and Bode Centroid Metrics (1x4 grid, showing centroids raw -> normalized -> raw detrend lines -> normalization + detrended).
        e. Nomenclature updated to include abbreviations instead of labels.
        f. Keyword support in the configuration file added. These keywords include: all_heads, outer_heads, inner_heads, odd_number_heads, even_number_heads.
        g. New centroid text file added, this centroid file is called "model_centroid_<id>.txt". This file contains the centroid coordinates through the feature space. The previous centroid text file is renamed to "bode_centroid_<id>.txt". This file contains the centroid coordinates through gain and phase feature space for representation on bode plots.
        h. Bode plot centroid only visualization updated to include measured data file counts and worst model data file counts for a respective cluster in the legend.
        i. 2 new data related visualizations added, these include: Segment Normalized and Detrended Plot (representation of segment data pre and post preprocessing) and Baseline Group Separation Plot(segment data post baseline data separation).
        j. Hierarchical Clustering models resolved to single-stage models per Stage 1 x Stage 2 combination. Hierarchical Clustering results are now saved in "h_combined" sub-directory.
        k. New "Cluster Merging Operations" added in the training application which merges clusters based on proximity calculated by centroid metrics and resonance peak comparisons.
        l. New "Iterative Centroid Update" added in the training application used to iteratively update the models after merging operations (each iteration's results are saved).
        m. New parameter called "post_merging_trained_models_path" added to , this parameter includes the paths of the models post merging and iterative centroid update.

      2. "tsb_frf_clustering_inference_application" ->
        a. Preprocessing is updated from standard scaler (mean and standard deviation) to normalization from [-1, 1] + detrending.
        b. "Meanline Data Separation" is updated to "Baseline Data Separation", which is a preprocessing step for segregating the data files into phase lead, phase lag and no resonance sub-groups.
        c. 2 new data related visualizations added, these include: Segment Normalized and Detrended Plot (representation of segment data pre and post preprocessing) and Baseline Group Separation Plot(segment data post baseline data separation).
        d. 1 new centroid related visualization added, namely: Bode Centroid Metrics (1x4 grid, showing centroids raw -> normalized -> raw detrend lines -> normalization + detrended).
        e. 3 new centroid related metrics are added, these are: Correlation, RMSE and Wasserstein.
        f. Nomenclature updated to include abbreviations instead of labels.
        g. Bode plot centroid only visualization updated to include measured data file counts and worst model data file counts for a respective cluster in the legend.
        h. Inference Application to run purely on single stage clustering models.

      3. "frf_merge_utility" ->
        a. A new utility tool for the "frf clustering tool" which helps in manual merging of the clusters based on the models trained using the "tsb_frf_clustering_training_application".