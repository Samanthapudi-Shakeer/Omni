* Company names and product names mentioned in this document
  are corporate trademarks or registered trademarks.
* "TM", "(R)", and "(C)" are omitted in this document.
(C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation

=================================================================================================================
[1] Introduction
=================================================================================================================
    - This readme file describes the procedure to use the below package:
        - FRF Merge Utility Package

    - FRF Merge Utility Package is used to manually merge desired clusters that are the result of clustering from FRF Clustering Training Application.

        - This tool outputs a visualization suite that consists of multiple data and centroid visualizations, drive cluster assignment csv and new iteratively updated model.

=================================================================================================================
[2] Package Structure
=================================================================================================================
    - Unzip and extract the "tsb_frf_clustering_tool_v004.zip" package and navigate to the directory having "tsb_frf_clustering_tool_v004".

    - Navigate to the directory "tsb_frf_merge_utility".

    - Following directory structure is present in "tsb_frf_merge_utility" directory.

             tsb_frf_clustering_tool_v004
                ├── [DIR] tsb_frf_merge_utility
                |            ├── [PY] frf_merge_utility.py
                |            ├── [PY] frf_merge_plotting.py
                |            ├── [PY] frf_merge_model.py
                |            ├── [PY] frf_merge_data.py
                |            ├── [PY] frf_merge_config_loader.py
                |            └── [CFG] merge_config.cfg
                ├── [TXT] tsb_frf_merge_utility_readme.txt
                └── [TXT] tsb_frf_clustering_tool_requirements.txt

    - "tsb_frf_merge_utility":
            - Sub-directory includes the utility scripts for manually merging desired clusters that are the result of clustering from "tsb_frf_clustering_training_application".

=================================================================================================================
[3] Execution of Merge Utility Scripts
=================================================================================================================
    - The python scripts provided in the merge utility directory, can be used for manually merging desired clusters.

    - In order to use merge utility, config provided for the merge utility script, "merge_config.cfg" has to be updated.

    - After updating "merge_config.cfg" to the desired configuration, run the following command:
      (frf_hdd) $ python frf_merge_utility.py --config merge_config.cfg

    - Output
        A successful run of the tool generates:

            **Abbreviations**
            {ts} - timestamp
            {ok} - original k (pre-merge, from the loaded model.json)
            {mk} - merged k (post user-merge / post-convergence)
            {NN} - forward-pass iteration number (01, 02, …)
            [one per merge_models entry] - repeats once per resolved {name}

            frf_merging_results_{ts}/
            ├── merging_log/
            │   └── frf_merging_utility.log
            ├── models/
            │   ├── feature_config.json                             [copied once from config]
            │   └── {name}/                                         [one per merge_models entry(from the config file)]
            │       ├── model.json
            │       ├── bode_centroid_0.txt
            │       ├── bode_centroid_{mk-1}.txt
            │       ├── model_centroid_0.txt
            │       └── model_centroid_{mk-1}.txt
            └── merging_results/
                └── {name}/                                         [one per merge_models entry(from the config file)]
                    ├── b_cen_origk{ok}_k{mk}.jpg                   [pre-forward-pass snapshot]
                    ├── b_cen_metrics_origk{ok}_k{mk}.jpg           [pre-forward-pass snapshot]
                    ├── fgp_grid_origk{ok}_k{mk}.jpg                [pre-forward-pass snapshot]
                    ├── dc_origk{ok}_k{mk}.csv                      [pre-forward-pass snapshot]
                    ├── merge_convergence_origk{ok}_k{mk}.jpg       [post-forward-pass, deviation curve]
                    └── iterations/
                        └── iter_{NN}/                              [one per forward pass, until plateau/MAX_FORWARD_PASSES]
                            ├── b_cen_origk{ok}_k{mk}.jpg
                            ├── b_cen_metrics_origk{ok}_k{mk}.jpg
                            ├── fgp_grid_origk{ok}_k{mk}.jpg
                            └── dc_origk{ok}_k{mk}.csv


=================================================================================================================
[4] Assumptions and Constraints
=================================================================================================================

    - Assumptions:

        (1) The data filenames must follow the nomenclature "<drive_name>_<head>_<cylinder>_<temperature>_<use_case>".
        (2) Only three file extensions are supported: ".exv", ".xpi" and ".xiz".
        (3) File extensions are case-sensitive and must be lowercase.
        (4) Head identifiers always start with "HD", cylinder identifiers always start with "CYL" and temperature identifiers always start with "T".
        (5) Every trained model referenced in "merge_models[i].path" is assumed to already be expressed in the same feature space (features + weightages) as the "feature_config".
        (6) When "baseline_data_separation = True", the phase_lead / phase_lag / no_resonance classification is recomputed independently by the merge utility from the currently loaded dataset.
        (7) Cluster ids listed in "clusters_combined" are assumed to be 0-indexed.
        (8) The length of the frequencies and the individual frequencies must be exactly the same throughout the measured data files and the worst model files.

    - Constraints:

        (1) Only "output_path", "data_dir_list", "frequency_segment", "feature_config", "baseline_data_separation" and "merge_models" are required in "merge_config.cfg"; "worst_model_dir_list" is the only optional parameter.
        (2) Only one "frequency_segment" ([freq_min, freq_max]) can be processed per merge run.
        (3) Each "merge_models" entry's resolved output name (explicit "name", else "baseline_group" label, else "model_<n>") must be unique across the whole config file.
        (4) The iterative centroid update runs for a maximum of 30 passes and stops early only once the last 5 passes' reassignment counts all fall within 50 files of each other.
        (5) Only the final (plateaued or 30th-pass) forward-pass result is saved to "model.json" and the centroid text files.
        (6) All "merge_models" entries in one execution are processed against the feature space loaded from "feature_config.json".
        (7) The nomenclature of the output files are updated to shorter names for easier path handling. In place, several abbreviations are used as below:
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
[5] Revision
=================================================================================================================

2026/09/24 - v004 Release
    - Release of the FRF Merge Utility.