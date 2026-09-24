* Company names and product names mentioned in this document
  are corporate trademarks or registered trademarks.
* "TM", "(R)", and "(C)" are omitted in this document.
(C) Copyright 2026 Toshiba Electronic Devices & Storage Corporation

=================================================================================================================
[1] Introduction
=================================================================================================================
    - This readme file describes the procedure to use the below package:
        - FRF Clustering Training Application

    - FRF Clustering Training Application is used for Training using the Time Series K-Means clustering algorithm on the Frequency Response Functions of MA and VCM data.

        - This tool outputs consolidated training summary for the dataset, bode plot visualizations, cluster plots, drive-wise cluster assignment CSVs and trained models which are used for inference tasks.

=================================================================================================================
[2] Package Structure
=================================================================================================================
    - Unzip and extract the "tsb_frf_clustering_tool_v004.zip" package and navigate to the directory having "tsb_frf_clustering_tool_v004".

    - Navigate to the directory "tsb_frf_clustering_training_application".

    - Following directory structure is present in "tsb_frf_clustering_training_application" directory.

             tsb_frf_clustering_tool_v004
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
                ├── [TXT] tsb_frf_clustering_training_application_readme.txt
                └── [TXT] tsb_frf_clustering_tool_requirements.txt

    - "tsb_frf_clustering_training_application":
            - Directory containing the source code files for execution of the FRF Clustering Training Application.

=================================================================================================================
[3] Execution of FRF Clustering Training Application
=================================================================================================================
    - FRF Clustering Training Application can be executed using the following steps:

        - Modify the "config.cfg" or create a config file using the same structure as provided in sample configs which are necessary for the execution of training application.

        - Set the "output_path" parameter inside "config.cfg" to the desired location where the output directory will be created and populated.

        - The ".txt" file created from the file list utility should be provided to the desired config file.

        - Once the "<spec_config>.cfg" is configured, run the below command:
          (frf_hdd) $ python frf_training_application.py --config frf_config/<spec_config>.cfg

            - Description of the above command:
              python frf_training_application.py --config <Arg1>
              Arg1: Path to the "<spec_config>.cfg" inside the frf_config subdirectory

        - The output directory containing the training results will be created inside the "output_path" specified in the config file, as described below:-

            Outputs:
            A successful run of the tool generates the following directory structures based on the specification provided in the config file:

            **Abbreviations**
            {ts}    - timestamp
            {H}     - head name. For combined heads: "HD_<concatenated 2-digit codes>" when no
                    keyword is used (e.g. HD0+HD1 -> HD_0001), or "<shortened keyword(s)>[_<extra codes>]"
                    when "heads" uses a keyword (all_heads/odd_number_heads/even_number_heads/
                    outer_heads/inner_heads -> "_heads" shortened to "_hds", e.g. "all_hds",
                    "outer_hds_inner_hds", "odd_number_hds_0A")
            {seg}   - segment name, e.g. 200.00_400.00Hz
            {k}     - cluster count
            {pk}    - stage-1 (parent) k
            {sk}    - stage-2 k
            {total} - pk × sk
            {i}     - cluster index (0 … k-1), used both for cluster_{i}/ folders and for the
                    trailing index in bode_centroid_{i}.txt / model_centroid_{i}.txt (0 … k-1)
            {f}     - frequency value with '.' replaced by '_' in filenames, e.g. 300.00 Hz -> 300_00
            {dt}    - dataset type (train / validation_data_dir / validation_worst_model)
            {grp}   - baseline group: phase_lead / phase_lag / no_resonance, or a combined label
                    joining several with "_" (e.g. phase_lead_no_resonance) per baseline_data_filtering
            {origk} - pre-merge cluster count (k, or total_clusters for hierarchical combined) baked
                    into merge-output filenames as "origk{origk}"
            {kmerged}- post-merge cluster count produced by the centroid merge, baked into
                    merge-output filenames as "k{kmerged}"
            [cond]      - only created when individual_frequencies_cluster_assignment_plots = True
            [html cond] - only created when generate_interactive_html_plots = True
            [merge cond]- only created when a centroid-metric merge is triggered (k or total_clusters > 4
                        and the merge criterion fires)
            [normal only] - only created in non-hierarchical mode

            Single Stage Clustering ->
                frf_clustering_analysis_{ts}/
                ├── logs/
                │   └── frf_training_application.log
                ├── trained_models_registry.csv
                ├── input_inference_config.cfg
                ├── trained_models/
                │   ├── feature_config.json
                │   └── {H}/                                             [one per head]
                │       └── {seg}/                                       [one per segment]
                │           └── k_{k}/                                   [one per k value]
                │               ├── model.json
                │               ├── bode_centroid_0.txt ... bode_centroid_{k-1}.txt
                │               ├── model_centroid_0.txt ... model_centroid_{k-1}.txt
                │               └── merged/                              [merge cond]
                │                   ├── model.json
                │                   ├── bode_centroid_0.txt ... bode_centroid_{kmerged-1}.txt
                │                   └── model_centroid_0.txt ... model_centroid_{kmerged-1}.txt
                └── HEAD_{H}/                                            [one per head]
                    ├── {H}_training_summary.csv
                    ├── train_val_split.json
                    └── segment_{seg}/                                   [one per segment]
                        └── {dt}/                                        [train / validation_data_dir / validation_worst_model]
                            ├── {H}_segment_overview.jpg
                            ├── {H}_normalization_detrend_overview.jpg
                            ├── {H}_3d_traj_o.jpg
                            ├── {H}_3d_traj_int_o.html                     [html cond]
                            ├── {H}_aci_scores_vs_k.jpg
                            ├── {H}_k1_comparison.csv
                            ├── metric_results/
                            │   ├── {H}_cen_heatmap_k{k}.jpg                [one per k]
                            │   └── {H}_cen_elbow.jpg
                            └── k_{k}/                                   [one per k value]
                                ├── {H}_b_cen_k{k}.jpg
                                ├── {H}_b_cen_metrics_k{k}.jpg
                                ├── {H}_fgp_grid_k{k}.jpg
                                ├── {H}_int_bg_k{k}.html          [html cond]
                                ├── {H}_int_bp_k{k}.html          [html cond]
                                ├── {H}_3d_traj_c_k{k}.jpg
                                ├── {H}_3d_cen_k{k}.jpg
                                ├── {H}_3d_traj_int_c_k{k}.html            [html cond]
                                ├── {H}_dc_k{k}.csv
                                ├── {H}_2d_freq_{f}Hz_k{k}.jpg              [cond: one per frequency]
                                ├── {H}_fan_segments_{f}Hz_k{k}.jpg         [cond: one per frequency]
                                ├── {H}_merge_convergence_origk{k}_k{kmerged}.jpg   [merge cond]
                                └── merged/                                [merge cond]
                                    ├── {H}_b_cen_origk{k}_k{kmerged}.jpg
                                    ├── {H}_b_cen_metrics_origk{k}_k{kmerged}.jpg
                                    ├── {H}_fgp_grid_origk{k}_k{kmerged}.jpg
                                    ├── {H}_int_bg_origk{k}_k{kmerged}.html  [html cond]
                                    ├── {H}_int_bp_origk{k}_k{kmerged}.html  [html cond]
                                    ├── {H}_3d_traj_c_origk{k}_k{kmerged}.jpg
                                    ├── {H}_3d_cen_origk{k}_k{kmerged}.jpg
                                    ├── {H}_3d_traj_int_c_origk{k}_k{kmerged}.html    [html cond]
                                    ├── {H}_dc_origk{k}_k{kmerged}.csv
                                    ├── {H}_merge_score_delta_k{k}.csv
                                    ├── metric_results/
                                    │   └── {H}_cen_heatmap_origk{k}_merged_k{kmerged}.jpg
                                    └── iterations/
                                        └── iter_{NN}/                     [one per forward pass, NN=01,02,...]
                                            ├── {H}_b_cen_origk{k}_k{kmerged}.jpg
                                            ├── {H}_b_cen_metrics_origk{k}_k{kmerged}.jpg
                                            ├── {H}_fgp_grid_origk{k}_k{kmerged}.jpg
                                            └── {H}_dc_origk{k}_k{kmerged}.csv

            Hierarchical Clustering ->
                frf_clustering_analysis_{ts}/
                ├── logs/
                │   └── frf_training_application.log
                ├── trained_models_registry.csv
                ├── input_inference_config.cfg
                ├── trained_models/
                │   ├── feature_config.json
                │   └── {H}/
                │       └── {seg}/
                │           ├── stage1_k_{pk}/                           [one per stage-1 k value]
                │           │   ├── model.json
                │           │   ├── bode_centroid_0.txt ... bode_centroid_{pk-1}.txt
                │           │   ├── model_centroid_0.txt ... model_centroid_{pk-1}.txt
                │           │   └── cluster_{i}/                         [one per stage-1 cluster]
                │           │       └── stage2_k_{sk}/                   [one per stage-2 k value]
                │           │           ├── model.json
                │           │           ├── bode_centroid_0.txt ... bode_centroid_{sk-1}.txt
                │           │           └── model_centroid_0.txt ... model_centroid_{sk-1}.txt
                │           └── h_combined/                              [sibling of stage1_k_{pk}, NOT nested inside it]
                │               └── stage1_k_{pk}_stage2_k_{sk}/          [one per (pk,sk) combination actually trained]
                │                   ├── model.json                         <- flat, single-stage consolidated model
                │                   ├── bode_centroid_0.txt ... bode_centroid_{total-1}.txt
                │                   ├── model_centroid_0.txt ... model_centroid_{total-1}.txt
                │                   └── merged/                            [merge cond: total_clusters > 4]
                │                       ├── model.json
                │                       ├── bode_centroid_0.txt ... bode_centroid_{kmerged-1}.txt
                │                       └── model_centroid_0.txt ... model_centroid_{kmerged-1}.txt
                └── HEAD_{H}/
                    ├── {H}_training_summary.csv
                    ├── train_val_split.json
                    └── segment_{seg}/
                        └── {dt}/
                            ├── {H}_3d_traj_o.jpg
                            ├── {H}_3d_traj_int_o.html                    [html cond]
                            ├── {H}_segment_overview.jpg
                            ├── {H}_normalization_detrend_overview.jpg
                            ├── {H}_h_k1_comparison.csv
                            ├── metric_results/
                            │   ├── {H}_h_aci1_scores.jpg                 [one per active ACI metric]
                            │   ├── {H}_h_aci2_scores.jpg
                            │   ├── {H}_h_aci3_scores.jpg
                            │   ├── {H}_h_aci4_scores.jpg
                            │   └── stage1_k_{pk}/                        [one per stage-1 k, cond: centroid metrics active]
                            │       ├── {H}_cen_elbow_stage1k{pk}.jpg
                            │       └── {H}_cen_heatmap_stage1k{pk}_stage2k{sk}.jpg  [one per stage2_k combo]
                            └── stage1_k_{pk}/                            [one per stage-1 k value]
                                ├── {H}_b_cen_k{pk}.jpg
                                ├── {H}_b_cen_metrics_k{pk}.jpg
                                ├── {H}_fgp_grid_k{pk}.jpg
                                ├── {H}_int_bg_k{pk}.html          [html cond]
                                ├── {H}_int_bp_k{pk}.html          [html cond]
                                ├── {H}_3d_traj_c_k{pk}.jpg
                                ├── {H}_3d_cen_k{pk}.jpg
                                ├── {H}_3d_traj_int_c_k{pk}.html            [html cond]
                                ├── {H}_dc_k{pk}.csv
                                ├── cluster_{i}/                          [one per stage-1 cluster]
                                │   └── stage2_k_{sk}/                    [one per stage-2 k value]
                                │       ├── {H}_b_cen_k{sk}.jpg
                                │       ├── {H}_b_cen_metrics_k{sk}.jpg
                                │       ├── {H}_fgp_grid_k{sk}.jpg
                                │       ├── {H}_int_bg_k{sk}.html   [html cond]
                                │       ├── {H}_int_bp_k{sk}.html   [html cond]
                                │       ├── {H}_3d_traj_c_k{sk}.jpg
                                │       ├── {H}_3d_cen_k{sk}.jpg
                                │       ├── {H}_3d_traj_int_c_k{sk}.html     [html cond]
                                │       ├── {H}_dc_k{sk}.csv
                                │       ├── {H}_2d_freq_{f}Hz_k{sk}.jpg      [cond: one per frequency]
                                │       └── {H}_fan_segments_{f}Hz_k{sk}.jpg [cond: one per frequency]
                                └── h_combined/                           [shared folder for ALL stage2_k combos of this pk]
                                    ├── {H}_b_cen_s1_k{pk}_s2_k{sk}.jpg               [one per stage2_k]
                                    ├── {H}_b_cen_metrics_s1_k{pk}_s2_k{sk}.jpg
                                    ├── {H}_fgp_grid_s1_k{pk}_s2_k{sk}.jpg
                                    ├── {H}_int_bg_h_s1_k{pk}_s2_k{sk}.html   [html cond]
                                    ├── {H}_int_bp_h_s1_k{pk}_s2_k{sk}.html   [html cond]
                                    ├── {H}_3d_traj_c_k{total}_s1_k{pk}_s2_k{sk}.jpg
                                    ├── {H}_3d_cen_s1_k{pk}_s2_k{sk}.jpg
                                    ├── {H}_3d_traj_int_c_stage1_k{pk}_stage2_k{sk}.html  [html cond]
                                    ├── {H}_dc_k{total}_s1_k{pk}_s2_k{sk}.csv
                                    ├── {H}_2d_freq_{f}Hz_k{total}.jpg                [cond: one per frequency]
                                    ├── {H}_fan_segments_{f}Hz_k{total}.jpg           [cond: one per frequency]
                                    ├── {H}_merge_convergence_origk{total}_k{kmerged}.jpg  [merge cond, one per merged combo]
                                    └── merged/                           [merge cond, shared — filenames disambiguate by k/origk]
                                        ├── {H}_b_cen_origk{total}_k{kmerged}.jpg
                                        ├── {H}_b_cen_metrics_origk{total}_k{kmerged}.jpg
                                        ├── {H}_fgp_grid_origk{total}_k{kmerged}.jpg
                                        ├── {H}_int_bg_origk{total}_k{kmerged}.html  [html cond]
                                        ├── {H}_int_bp_origk{total}_k{kmerged}.html  [html cond]
                                        ├── {H}_3d_traj_c_origk{total}_k{kmerged}.jpg
                                        ├── {H}_3d_cen_origk{total}_k{kmerged}.jpg
                                        ├── {H}_3d_traj_int_c_origk{total}_k{kmerged}.html    [html cond]
                                        ├── {H}_dc_origk{total}_k{kmerged}.csv
                                        ├── {H}_merge_score_delta_k{total}.csv
                                        ├── metric_results/
                                        │   └── {H}_cen_heatmap_origk{total}_merged_k{kmerged}.jpg
                                        └── iterations/
                                            └── iter_{NN}/
                                                ├── {H}_b_cen_origk{total}_k{kmerged}.jpg
                                                ├── {H}_b_cen_metrics_origk{total}_k{kmerged}.jpg
                                                ├── {H}_fgp_grid_origk{total}_k{kmerged}.jpg
                                                └── {H}_dc_origk{total}_k{kmerged}.csv

            Single Stage Clustering + Baseline Data Separation ->
                frf_clustering_analysis_{ts}/
                ├── logs/
                │   └── frf_training_application.log
                ├── trained_models_registry.csv
                ├── input_inference_config.cfg
                ├── trained_models/
                │   ├── feature_config.json
                │   └── {H}/
                │       └── {seg}/
                │           └── {grp}/                                   [phase_lead / phase_lag / no_resonance / combined]
                │               └── k_{k}/                               [one per k value]
                │                   ├── model.json
                │                   ├── bode_centroid_0.txt ... bode_centroid_{k-1}.txt
                │                   ├── model_centroid_0.txt ... model_centroid_{k-1}.txt
                │                   └── merged/                          [merge cond]
                │                       ├── model.json
                │                       ├── bode_centroid_0.txt ... bode_centroid_{kmerged-1}.txt
                │                       └── model_centroid_0.txt ... model_centroid_{kmerged-1}.txt
                └── HEAD_{H}/
                    ├── {H}_training_summary.csv
                    ├── train_val_split.json
                    └── segment_{seg}/
                        └── {dt}/
                            ├── {H}_3d_traj_o.jpg                        [full-segment 3D, all files]
                            ├── {H}_3d_traj_int_o.html                   [html cond]
                            ├── {H}_segment_overview.jpg
                            ├── {H}_baseline_group_separation.jpg        [2x4 raw/normalized+detrended phase grid]
                            └── {grp}/                                   [phase_lead / phase_lag / no_resonance / combined]
                                ├── {H}_3d_traj_o.jpg                    [group-specific 3D]
                                ├── {H}_3d_traj_int_o.html                [html cond]
                                ├── {H}_aci_scores_vs_k.jpg
                                ├── {H}_k1_comparison.csv
                                ├── metric_results/
                                │   ├── {H}_cen_heatmap_k{k}.jpg          [one per k]
                                │   └── {H}_cen_elbow.jpg
                                └── k_{k}/                               [one per k value]
                                    ├── {H}_b_cen_k{k}.jpg
                                    ├── {H}_b_cen_metrics_k{k}.jpg
                                    ├── {H}_fgp_grid_k{k}.jpg
                                    ├── {H}_int_bg_k{k}.html      [html cond]
                                    ├── {H}_int_bp_k{k}.html      [html cond]
                                    ├── {H}_3d_traj_c_k{k}.jpg
                                    ├── {H}_3d_cen_k{k}.jpg
                                    ├── {H}_3d_traj_int_c_k{k}.html        [html cond]
                                    ├── {H}_dc_k{k}.csv
                                    ├── {H}_2d_freq_{f}Hz_k{k}.jpg          [cond: one per frequency]
                                    ├── {H}_fan_segments_{f}Hz_k{k}.jpg     [cond: one per frequency]
                                    ├── {H}_merge_convergence_origk{k}_k{kmerged}.jpg   [merge cond]
                                    └── merged/                            [merge cond]
                                        ├── {H}_b_cen_origk{k}_k{kmerged}.jpg
                                        ├── {H}_b_cen_metrics_origk{k}_k{kmerged}.jpg
                                        ├── {H}_fgp_grid_origk{k}_k{kmerged}.jpg
                                        ├── {H}_int_bg_origk{k}_k{kmerged}.html  [html cond]
                                        ├── {H}_int_bp_origk{k}_k{kmerged}.html  [html cond]
                                        ├── {H}_3d_traj_c_origk{k}_k{kmerged}.jpg
                                        ├── {H}_3d_cen_origk{k}_k{kmerged}.jpg
                                        ├── {H}_3d_traj_int_c_origk{k}_k{kmerged}.html    [html cond]
                                        ├── {H}_dc_origk{k}_k{kmerged}.csv
                                        ├── {H}_merge_score_delta_k{k}.csv
                                        ├── metric_results/
                                        │   └── {H}_cen_heatmap_origk{k}_merged_k{kmerged}.jpg
                                        └── iterations/
                                            └── iter_{NN}/
                                                ├── {H}_b_cen_origk{k}_k{kmerged}.jpg
                                                ├── {H}_b_cen_metrics_origk{k}_k{kmerged}.jpg
                                                ├── {H}_fgp_grid_origk{k}_k{kmerged}.jpg
                                                └── {H}_dc_origk{k}_k{kmerged}.csv

            Hierarchical Clustering + Baseline Data Separation ->
                frf_clustering_analysis_{ts}/
                ├── logs/
                │   └── frf_training_application.log
                ├── trained_models_registry.csv
                ├── input_inference_config.cfg
                ├── trained_models/
                │   ├── feature_config.json
                │   └── {H}/
                │       └── {seg}/
                │           └── {grp}/                                   [phase_lead / phase_lag / no_resonance / combined]
                │               ├── stage1_k_{pk}/                       [one per stage-1 k value]
                │               │   ├── model.json
                │               │   ├── bode_centroid_0.txt ... bode_centroid_{pk-1}.txt
                │               │   ├── model_centroid_0.txt ... model_centroid_{pk-1}.txt
                │               │   └── cluster_{i}/                     [one per stage-1 cluster]
                │               │       └── stage2_k_{sk}/               [one per stage-2 k value]
                │               │           ├── model.json
                │               │           ├── bode_centroid_0.txt ... bode_centroid_{sk-1}.txt
                │               │           └── model_centroid_0.txt ... model_centroid_{sk-1}.txt
                │               └── h_combined/                          [sibling of stage1_k_{pk}]
                │                   └── stage1_k_{pk}_stage2_k_{sk}/      [one per (pk,sk) combination trained]
                │                       ├── model.json
                │                       ├── bode_centroid_0.txt ... bode_centroid_{total-1}.txt
                │                       ├── model_centroid_0.txt ... model_centroid_{total-1}.txt
                │                       └── merged/                      [merge cond: total_clusters > 4]
                │                           ├── model.json
                │                           ├── bode_centroid_0.txt ... bode_centroid_{kmerged-1}.txt
                │                           └── model_centroid_0.txt ... model_centroid_{kmerged-1}.txt
                └── HEAD_{H}/
                    ├── {H}_training_summary.csv
                    ├── train_val_split.json
                    └── segment_{seg}/
                        └── {dt}/
                            ├── {H}_3d_traj_o.jpg                        [full-segment 3D, all files]
                            ├── {H}_3d_traj_int_o.html                    [html cond]
                            ├── {H}_segment_overview.jpg                 [full-segment overview; normalization+
                            │                                              detrend overview is NOT generated here]
                            ├── {H}_baseline_group_separation.jpg
                            └── {grp}/                                   [phase_lead / phase_lag / no_resonance / combined]
                                ├── {H}_3d_traj_o.jpg                    [group-specific 3D]
                                ├── {H}_3d_traj_int_o.html                [html cond]
                                ├── {H}_h_k1_comparison.csv
                                ├── metric_results/
                                │   ├── {H}_h_aci1_scores.jpg             [one per active ACI metric]
                                │   ├── {H}_h_aci2_scores.jpg
                                │   ├── {H}_h_aci3_scores.jpg
                                │   ├── {H}_h_aci4_scores.jpg
                                │   └── stage1_k_{pk}/                    [cond: centroid metrics active]
                                │       ├── {H}_cen_elbow_stage1k{pk}.jpg
                                │       └── {H}_cen_heatmap_stage1k{pk}_stage2k{sk}.jpg  [one per stage2_k combo]
                                └── stage1_k_{pk}/                       [one per stage-1 k value]
                                    ├── {H}_b_cen_k{pk}.jpg
                                    ├── {H}_b_cen_metrics_k{pk}.jpg
                                    ├── {H}_fgp_grid_k{pk}.jpg
                                    ├── {H}_int_bg_k{pk}.html     [html cond]
                                    ├── {H}_int_bp_k{pk}.html     [html cond]
                                    ├── {H}_3d_traj_c_k{pk}.jpg
                                    ├── {H}_3d_cen_k{pk}.jpg
                                    ├── {H}_3d_traj_int_c_k{pk}.html       [html cond]
                                    ├── {H}_dc_k{pk}.csv
                                    ├── cluster_{i}/                     [one per stage-1 cluster]
                                    │   └── stage2_k_{sk}/               [one per stage-2 k value]
                                    │       ├── {H}_b_cen_k{sk}.jpg
                                    │       ├── {H}_b_cen_metrics_k{sk}.jpg
                                    │       ├── {H}_fgp_grid_k{sk}.jpg
                                    │       ├── {H}_int_bg_k{sk}.html  [html cond]
                                    │       ├── {H}_int_bp_k{sk}.html  [html cond]
                                    │       ├── {H}_3d_traj_c_k{sk}.jpg
                                    │       ├── {H}_3d_cen_k{sk}.jpg
                                    │       ├── {H}_3d_traj_int_c_k{sk}.html    [html cond]
                                    │       ├── {H}_dc_k{sk}.csv
                                    │       ├── {H}_2d_freq_{f}Hz_k{sk}.jpg          [cond: one per frequency]
                                    │       └── {H}_fan_segments_{f}Hz_k{sk}.jpg     [cond: one per frequency]
                                    └── h_combined/                       [shared folder for ALL stage2_k combos of this pk]
                                        ├── {H}_b_cen_s1_k{pk}_s2_k{sk}.jpg              [one per stage2_k]
                                        ├── {H}_b_cen_metrics_s1_k{pk}_s2_k{sk}.jpg
                                        ├── {H}_fgp_grid_s1_k{pk}_s2_k{sk}.jpg
                                        ├── {H}_int_bg_h_s1_k{pk}_s2_k{sk}.html  [html cond]
                                        ├── {H}_int_bp_h_s1_k{pk}_s2_k{sk}.html  [html cond]
                                        ├── {H}_3d_traj_c_k{total}_s1_k{pk}_s2_k{sk}.jpg
                                        ├── {H}_3d_cen_s1_k{pk}_s2_k{sk}.jpg
                                        ├── {H}_3d_traj_int_c_stage1_k{pk}_stage2_k{sk}.html  [html cond]
                                        ├── {H}_dc_k{total}_s1_k{pk}_s2_k{sk}.csv
                                        ├── {H}_2d_freq_{f}Hz_k{total}.jpg               [cond: one per frequency]
                                        ├── {H}_fan_segments_{f}Hz_k{total}.jpg          [cond: one per frequency]
                                        ├── {H}_merge_convergence_origk{total}_k{kmerged}.jpg  [merge cond]
                                        └── merged/                       [merge cond]
                                            ├── {H}_b_cen_origk{total}_k{kmerged}.jpg
                                            ├── {H}_b_cen_metrics_origk{total}_k{kmerged}.jpg
                                            ├── {H}_fgp_grid_origk{total}_k{kmerged}.jpg
                                            ├── {H}_int_bg_origk{total}_k{kmerged}.html  [html cond]
                                            ├── {H}_int_bp_origk{total}_k{kmerged}.html  [html cond]
                                            ├── {H}_3d_traj_c_origk{total}_k{kmerged}.jpg
                                            ├── {H}_3d_cen_origk{total}_k{kmerged}.jpg
                                            ├── {H}_3d_traj_int_c_origk{total}_k{kmerged}.html    [html cond]
                                            ├── {H}_dc_origk{total}_k{kmerged}.csv
                                            ├── {H}_merge_score_delta_k{total}.csv
                                            ├── metric_results/
                                            │   └── {H}_cen_heatmap_origk{total}_merged_k{kmerged}.jpg
                                            └── iterations/
                                                └── iter_{NN}/
                                                    ├── {H}_b_cen_origk{total}_k{kmerged}.jpg
                                                    ├── {H}_b_cen_metrics_origk{total}_k{kmerged}.jpg
                                                    ├── {H}_fgp_grid_origk{total}_k{kmerged}.jpg
                                                    └── {H}_dc_origk{total}_k{kmerged}.csv


=================================================================================================================
[4] Assumptions and Constraints
=================================================================================================================
    - Assumptions

        (1) The first file listed in the "directory_path" of the "frf_data_list_config.cfg" is assumed to be correct and used as reference file in the "tsb_frf_clustering_training_application".
        (2) "END" string should be present at the end of data files.
        (3) First 9 rows in the data files have no frequency, gain and phase values / information.
        (4) The length of the frequencies and the individual frequencies must be exactly same throughout the data files and the worst model files.
        (5) The data filenames must follow the nomenclature "<drive_name>_<head>_<cylinder>_<temperature>_<use_case>".

    - Constraints

        (1) The config files are to be stored in the config directory within the application packages.
        (2) Minimum 100 sample files per head should be present for the execution of applications.
        (3) The tool relies on "Plotly" and "Matplotlib" to generate visualizations, which may be slow for very large datasets.
        (4) When in the config, "individual_frequencies_cluster_assignment_plots = True", the application will take longer to run as "2D cluster assignment plots" and "2D fan segment plots" for each frequency is generated separately.
        (5) Performance may degrade with very large numbers of files.
        (6) For a large number of files (>100000), interactive 3D visualization will use large amount of disk space and maybe slow to load.
        (7) For a larger number of files (>200000), interactive 3D visualization may not be created.
        (8) Microsoft Excel cannot open CSV files if the full file path exceeds 259 characters due to Excel's path length limitation in Windows 11 Pro.
        (9) To represent pre and post merge cluster counts, output file names have been updated to contain both "k" values. The original k is represented as "orig<k>" and the merged k is represented after the as "orig<k>_k<merged_k>".
        (10) The iterative centroid update runs for a maximum of 30 passes and stops early only once the last 5 passes' reassignment counts all fall within 50 files of each other.
        (11) Only the final (plateaued or 30th-pass) forward-pass result is saved to "model.json" and the centroid text files.
        (12) The nomenclature of the output files are updated to shorter names for easier path handling. In place, several abbreviations are used as below:
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

2026/01/16 - v001 Release
    - Release of the FRF Clustering Training Application.
    - Supports the following functionalities: input handling, summary csv creation, clustering training results, metric comparisons and static and interactive EDA plots.

2026/02/13 - v002 Release
    - Includes the following modifications:
        a. New parameter "output_path" added in the configuration file, to set the path where the output directory will be generated.
        b. All the paths in the "input_inference_config.cfg" are now recorded as relative paths.
        c. Centroid lines in the Bode plot for each cluster are generated by back-transforming the learned centroid lines from the complex plane, and are saved in .txt format for visualization/representation purposes.

2026/05/29 - v003 Release
    - Includes the following modifications:
        a. New clustering approach "Hierarchical Clustering" added to the training application, which takes a two stage approach for clustering FRF data.
        b. New preprocessing step called "Meanline Data Separation" added to the training application, which is a preprocessing step for segregating the data files into phase lead and phase lag and perform clustering on them individually.
        c. 6 new features relating to second derivation, peak prominence and moving averages added to the training application.
        d. Bode plot centroid only visualization updated to include total file counts for a respective cluster in the legend.
        e. Gain Phase vs Frequency plot updated for higher resolution.
        f. "feature_config.json" updated to include both Stage 1 clustering and Stage 2 clustering features.
        g. "segment_meanline.json" created that stores the meanline used for data separation.

2026/09/24 - v004 Release
    - Includes the following modifications:
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
        m. New parameter called "post_merging_trained_models_path" added to "input_inference_config.cfg", this parameter includes the paths of the models post merging and iterative centroid update.