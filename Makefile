.PHONY: preview production impact-production expansion-dry-run expansion-apply catalog-v2-dry-run catalog-v2-apply check matrix artist-native-matrix artist-signature-matrix artist-signature-illustrated-calibration-matrix completion completion-predeploy-strict completion-strict progress test release release-deploy-dry-run release-deploy deploy-preview-dry-run deploy-preview deploy-production-dry-run deploy-production remote-production-smoke finalize-production-deployment finish-production remote-smoke remote-pilot remote-style-refill-calibration remote-generated-screen remote-testing-retest review-style-screen remote-artist-native-dry-run remote-artist-native review-artist-native remote-artist-signature-dry-run remote-artist-signature review-artist-signature score-artist-signature-screen apply-artist-signature-screen remote-artist-signature-illustrated-calibration review-artist-signature-illustrated-calibration remote-artist-signature-retest combine-artist-signature-retest review-artist-signature-retest score-artist-signature-retest apply-artist-signature-retest
.PHONY: runtime-audit phase6-single-axis-matrix phase6-pairwise-matrix phase6-presets-matrix phase6-random-matrix phase6-benchmark-matrix remote-phase6-single-axis remote-phase6-pairwise remote-phase6-presets remote-phase6-random remote-phase6-benchmark review-phase6-single-axis review-phase6-pairwise review-phase6-presets review-phase6-random review-phase6-benchmark score-phase6-single-axis score-phase6-pairwise score-phase6-presets score-phase6-random score-phase6-benchmark
.PHONY: artist-abc-map artist-abc-matrix remote-artist-abc-dry-run remote-artist-abc review-artist-abc score-artist-abc

preview:
	python3 scripts/build_runtime_yaml.py --include-status generated --include-status testing --include-status approved --output build/preview-wildcards
	python3 scripts/build_impact_yaml.py --source build/preview-wildcards --output build/impact-wildcards/krea2_complete_pack.yaml

production:
	python3 scripts/build_runtime_yaml.py --output wildcards

impact-production: production
	python3 scripts/build_impact_yaml.py --source wildcards --output build/impact-production/krea2_complete_pack.yaml

expansion-dry-run:
	python3 scripts/generate_catalog_expansion.py catalog/blueprints

expansion-apply:
	python3 scripts/generate_catalog_expansion.py catalog/blueprints --apply

catalog-v2-dry-run:
	python3 scripts/sync_catalog_v2.py

catalog-v2-apply:
	python3 scripts/sync_catalog_v2.py --apply

check: preview
	python3 scripts/generate_catalog_expansion.py catalog/blueprints
	python3 scripts/normalize_catalog.py catalog
	python3 scripts/lint_wildcards.py build/preview-wildcards
	python3 scripts/check_duplicates.py catalog
	python3 scripts/check_conflicts.py --catalog catalog/compatibility.yaml
	python3 scripts/sync_catalog_v2.py
	python3 scripts/validate_catalog_v2.py
	python3 scripts/check_sensitive_data.py
	python3 scripts/check_sensitive_history.py
	pytest

matrix:
	python3 scripts/export_prompt_matrix.py --output tests/prompt_matrix/styles.jsonl

artist-native-matrix:
	python3 scripts/export_artist_native_matrix.py --output tests/prompt_matrix/artist_native_name.jsonl

artist-signature-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --output tests/prompt_matrix/artist_visual_signature.jsonl

artist-signature-illustrated-calibration-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --limit-signatures 5 --output tests/prompt_matrix/artist_visual_signature_illustrated_calibration.jsonl

completion:
	python3 scripts/check_completion_criteria.py

completion-predeploy-strict:
	python3 scripts/check_completion_criteria.py --stage predeploy --strict --output tests/reports/predeploy_criteria.json

completion-strict:
	python3 scripts/check_completion_criteria.py --strict

progress:
	python3 scripts/check_plan_progress.py --output tests/reports/plan_progress.json

test:
	pytest

release:
	python3 scripts/run_release.py

release-deploy-dry-run:
	python3 scripts/run_release.py --deploy

release-deploy: deploy-production

deploy-preview-dry-run: preview
	python3 scripts/deploy_remote_wildcards.py --source build/impact-wildcards/krea2_complete_pack.yaml --evidence tests/reports/deployments/expansion_preview_v0_10_2-dry-run.json

deploy-preview: preview
	python3 scripts/deploy_remote_wildcards.py --source build/impact-wildcards/krea2_complete_pack.yaml --evidence tests/reports/deployments/expansion_preview_v0_10_2-apply.json --apply

deploy-production-dry-run: impact-production
	python3 scripts/deploy_remote_wildcards.py --evidence tests/reports/deployments/production_v1-dry-run.json

deploy-production:
	python3 scripts/run_release.py
	python3 scripts/audit_runtime_coverage.py --prompt-log tests/reports/phase6_benchmark_v1/runs/KB000001/run.json --overwrite
	python3 scripts/check_completion_criteria.py --stage predeploy --strict --output tests/reports/predeploy_criteria.json
	python3 scripts/deploy_remote_wildcards.py --evidence tests/reports/deployments/production_v1.json --apply

remote-production-smoke:
	python3 scripts/run_remote_benchmark.py --style-id crystal_iris_pastel --seed 6006 --output tests/reports/production_smoke_v1 --submit

finalize-production-deployment:
	python3 scripts/finalize_production_deployment.py --evidence tests/reports/deployments/production_v1.json --smoke-run tests/reports/production_smoke_v1/runs/crystal_iris_pastel_seed_6006/run.json

finish-production: deploy-production
	python3 scripts/run_remote_benchmark.py --style-id crystal_iris_pastel --seed 6006 --output tests/reports/production_smoke_v1 --submit
	python3 scripts/finalize_production_deployment.py --evidence tests/reports/deployments/production_v1.json --smoke-run tests/reports/production_smoke_v1/runs/crystal_iris_pastel_seed_6006/run.json
	python3 scripts/check_completion_criteria.py --strict

remote-smoke:
	python3 scripts/run_remote_benchmark.py --submit

remote-pilot:
	python3 scripts/run_remote_pilot.py --submit

remote-style-refill-calibration:
	python3 scripts/run_remote_catalog_batch.py --catalog catalog/style_expansion.yaml --templates catalog/expansion_templates.yaml --status generated --style-id style_pack_expansion_geometric_slender_limited_duotone_weathered_ink_nocturnal_tension_etched_accent_complete_style --style-id style_pack_expansion_minimal_quiet_jewel_and_gold_fibrous_paper_contemplative_air_etched_accent_complete_style --style-id style_pack_expansion_minimal_quiet_low_contrast_pastel_chalk_matte_nocturnal_tension_etched_accent_complete_style --style-id style_pack_expansion_minimal_quiet_low_contrast_pastel_satin_clean_ceremonial_energy_etched_accent_complete_style --style-id style_pack_expansion_minimal_quiet_low_contrast_pastel_satin_clean_contemplative_air_selective_taper_complete_style --output tests/reports/expansion_style_refill_calibration_v0_10_2 --resume --submit

remote-generated-screen:
	python3 scripts/run_remote_catalog_batch.py --catalog catalog/style_expansion.yaml --templates catalog/expansion_templates.yaml --status generated --output tests/reports/expansion_style_refill_v0_10_2 --resume --submit

remote-testing-retest:
	python3 scripts/run_remote_catalog_batch.py --catalog catalog/style_expansion.yaml --templates catalog/expansion_templates.yaml --status testing --seed 4004 --seed 5005 --output tests/reports/expansion_style_refill_retest_v0_10_2 --resume --submit

review-style-screen:
	python3 scripts/build_contact_sheets.py tests/reports/expansion_style_refill_v0_10_2/scorecard.csv --catalog catalog/style_expansion.yaml --expected-seeds 3 --styles-per-sheet 10 --overwrite

remote-artist-native-dry-run: artist-native-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_native_name.jsonl

remote-artist-native: artist-native-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_native_name.jsonl --output tests/reports/artist_native_screen_v0_7 --resume --submit

review-artist-native:
	python3 scripts/build_artist_native_contact_sheets.py tests/reports/artist_native_screen_v0_7/scorecard.csv --overwrite

remote-artist-signature-dry-run: artist-signature-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature.jsonl

remote-artist-signature: artist-signature-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature.jsonl --output tests/reports/artist_signature_screen_v0_8 --resume --submit

review-artist-signature:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_screen_v0_8/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature.jsonl --expected-seeds 3 --cases-per-sheet 10 --overwrite

score-artist-signature-screen:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_screen_v0_8/review_part_a.yaml tests/reports/artist_signature_screen_v0_8/review_part_b.yaml tests/reports/artist_signature_screen_v0_8/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_screen_v0_8/scorecard.csv --output tests/reports/artist_signature_screen_v0_8/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_screen_v0_8/scorecard.csv tests/reports/artist_signature_screen_v0_8/review.yaml --output tests/reports/artist_signature_screen_v0_8/scored.csv --overwrite
	python3 scripts/summarize_results.py tests/reports/artist_signature_screen_v0_8/scored.csv --output tests/reports/artist_signature_screen_v0_8/summary.json

apply-artist-signature-screen: score-artist-signature-screen
	python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_screen_v0_8/summary.json --catalog catalog/artists.yaml --evaluation-id artist_signature_screen_v0_8 --from-status generated --apply

remote-artist-signature-illustrated-calibration: artist-signature-illustrated-calibration-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_illustrated_calibration.jsonl --output tests/reports/artist_signature_illustrated_calibration_v0_8_1 --resume --submit

review-artist-signature-illustrated-calibration:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_illustrated_calibration_v0_8_1/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_illustrated_calibration.jsonl --expected-seeds 3 --cases-per-sheet 5 --overwrite

remote-artist-signature-retest:
	python3 scripts/export_artist_visual_signature_matrix.py --status testing --seed 4004 --seed 5005 --output tests/prompt_matrix/artist_visual_signature_retest.jsonl
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_retest.jsonl --output tests/reports/artist_signature_retest_v0_8 --resume --submit

combine-artist-signature-retest:
	python3 scripts/select_scorecard_styles.py tests/reports/artist_signature_screen_v0_8/scorecard.csv tests/reports/artist_signature_retest_v0_8/scorecard.csv --output tests/reports/artist_signature_combined_v0_8/pilot_scorecard.csv --overwrite
	python3 scripts/merge_scorecards.py tests/reports/artist_signature_combined_v0_8/pilot_scorecard.csv tests/reports/artist_signature_retest_v0_8/scorecard.csv --output tests/reports/artist_signature_combined_v0_8/scorecard.csv --overwrite

review-artist-signature-retest: combine-artist-signature-retest
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_combined_v0_8/scorecard.csv --expected-seeds 5 --cases-per-sheet 10 --overwrite

score-artist-signature-retest:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_combined_v0_8/review_part_a.yaml tests/reports/artist_signature_combined_v0_8/review_part_b.yaml tests/reports/artist_signature_combined_v0_8/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_combined_v0_8/scorecard.csv --output tests/reports/artist_signature_combined_v0_8/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_combined_v0_8/scorecard.csv tests/reports/artist_signature_combined_v0_8/review.yaml --output tests/reports/artist_signature_combined_v0_8/scored.csv --overwrite
	python3 scripts/summarize_results.py tests/reports/artist_signature_combined_v0_8/scored.csv --output tests/reports/artist_signature_combined_v0_8/summary.json

apply-artist-signature-retest: score-artist-signature-retest
	python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_combined_v0_8/summary.json --catalog catalog/artists.yaml --evaluation-id artist_signature_retest_v0_8 --from-status testing --apply

runtime-audit: impact-production
	python3 scripts/audit_runtime_coverage.py --prompt-log tests/reports/phase6_benchmark_v1/runs/KB000001/run.json --overwrite

artist-abc-map:
	python3 scripts/select_artist_abc_candidates.py --output tests/prompt_matrix/artist_abc_signature_map.yaml --overwrite

artist-abc-matrix: artist-abc-map
	python3 scripts/export_artist_abc_matrix.py --signature-map tests/prompt_matrix/artist_abc_signature_map.yaml --output tests/prompt_matrix/artist_abc.jsonl

remote-artist-abc-dry-run: artist-abc-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_abc.jsonl

remote-artist-abc: artist-abc-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_abc.jsonl --output tests/reports/artist_abc_v1 --resume --submit

review-artist-abc:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_abc_v1/scorecard.csv --matrix tests/prompt_matrix/artist_abc.jsonl --expected-seeds 3 --overwrite

score-artist-abc:
	python3 scripts/apply_artist_abc_review.py tests/reports/artist_abc_v1/scorecard.csv tests/reports/artist_abc_v1/review.yaml --output tests/reports/artist_abc_v1/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py artist-abc tests/reports/artist_abc_v1/scored.csv --matrix tests/prompt_matrix/artist_abc.jsonl --output tests/reports/completion/artist_abc.json --overwrite

phase6-single-axis-matrix:
	python3 scripts/export_phase6_matrix.py single-axis --output tests/prompt_matrix/phase6_single_axis.jsonl

phase6-pairwise-matrix:
	python3 scripts/export_phase6_matrix.py pairwise --output tests/prompt_matrix/phase6_pairwise.jsonl

phase6-presets-matrix:
	python3 scripts/export_phase6_matrix.py presets --output tests/prompt_matrix/phase6_presets.jsonl

phase6-random-matrix:
	python3 scripts/export_phase6_matrix.py random-utility --output tests/prompt_matrix/phase6_random_utility.jsonl

phase6-benchmark-matrix:
	python3 scripts/export_phase6_matrix.py benchmark --output tests/prompt_matrix/phase6_benchmark.jsonl

remote-phase6-single-axis: phase6-single-axis-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_single_axis.jsonl --output tests/reports/phase6_single_axis_v1 --resume --submit

remote-phase6-pairwise: phase6-pairwise-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_pairwise.jsonl --output tests/reports/phase6_pairwise_v1 --resume --submit

remote-phase6-presets: phase6-presets-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_presets.jsonl --output tests/reports/phase6_presets_v1 --resume --submit

remote-phase6-random: phase6-random-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_random_utility.jsonl --output tests/reports/phase6_random_utility_v1 --resume --submit

remote-phase6-benchmark: phase6-benchmark-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_benchmark.jsonl --output tests/reports/phase6_benchmark_v1 --resume --submit

review-phase6-single-axis:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_single_axis_v1/scorecard.csv --matrix tests/prompt_matrix/phase6_single_axis.jsonl --expected-seeds 3 --overwrite

review-phase6-pairwise:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_pairwise_v1/scorecard.csv --matrix tests/prompt_matrix/phase6_pairwise.jsonl --expected-seeds 3 --overwrite

review-phase6-presets:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_presets_v1/scorecard.csv --matrix tests/prompt_matrix/phase6_presets.jsonl --expected-seeds 3 --overwrite

review-phase6-random:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_random_utility_v1/scorecard.csv --matrix tests/prompt_matrix/phase6_random_utility.jsonl --expected-seeds 3 --overwrite

review-phase6-benchmark:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_benchmark_v1/scorecard.csv --matrix tests/prompt_matrix/phase6_benchmark.jsonl --expected-seeds 5 --overwrite

score-phase6-single-axis:
	python3 scripts/merge_visual_reviews.py tests/reports/phase6_single_axis_v1/review_part_a.yaml --expected-scorecard tests/reports/phase6_single_axis_v1/scorecard.csv --output tests/reports/phase6_single_axis_v1/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/phase6_single_axis_v1/scorecard.csv tests/reports/phase6_single_axis_v1/review.yaml --output tests/reports/phase6_single_axis_v1/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py single-axis tests/reports/phase6_single_axis_v1/scored.csv --matrix tests/prompt_matrix/phase6_single_axis.jsonl --output tests/reports/completion/single_axis.json --overwrite

score-phase6-pairwise:
	python3 scripts/merge_visual_reviews.py tests/reports/phase6_pairwise_v1/review_part_a.yaml tests/reports/phase6_pairwise_v1/review_part_b.yaml tests/reports/phase6_pairwise_v1/review_part_c.yaml --expected-scorecard tests/reports/phase6_pairwise_v1/scorecard.csv --output tests/reports/phase6_pairwise_v1/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/phase6_pairwise_v1/scorecard.csv tests/reports/phase6_pairwise_v1/review.yaml --output tests/reports/phase6_pairwise_v1/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py pairwise tests/reports/phase6_pairwise_v1/scored.csv --matrix tests/prompt_matrix/phase6_pairwise.jsonl --output tests/reports/completion/pairwise.json --overwrite

score-phase6-presets:
	python3 scripts/merge_visual_reviews.py tests/reports/phase6_presets_v1/review_part_a.yaml tests/reports/phase6_presets_v1/review_part_b.yaml tests/reports/phase6_presets_v1/review_part_c.yaml --expected-scorecard tests/reports/phase6_presets_v1/scorecard.csv --output tests/reports/phase6_presets_v1/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/phase6_presets_v1/scorecard.csv tests/reports/phase6_presets_v1/review.yaml --output tests/reports/phase6_presets_v1/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py presets tests/reports/phase6_presets_v1/scored.csv --matrix tests/prompt_matrix/phase6_presets.jsonl --output tests/reports/completion/presets.json --overwrite

score-phase6-random:
	python3 scripts/merge_visual_reviews.py tests/reports/phase6_random_utility_v1/review_part_a.yaml tests/reports/phase6_random_utility_v1/review_part_b.yaml --expected-scorecard tests/reports/phase6_random_utility_v1/scorecard.csv --output tests/reports/phase6_random_utility_v1/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/phase6_random_utility_v1/scorecard.csv tests/reports/phase6_random_utility_v1/review.yaml --output tests/reports/phase6_random_utility_v1/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py random-utility tests/reports/phase6_random_utility_v1/scored.csv --matrix tests/prompt_matrix/phase6_random_utility.jsonl --output tests/reports/completion/random_utility.json --overwrite

score-phase6-benchmark:
	python3 scripts/merge_visual_reviews.py tests/reports/phase6_benchmark_v1/review_part_a.yaml --expected-scorecard tests/reports/phase6_benchmark_v1/scorecard.csv --output tests/reports/phase6_benchmark_v1/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/phase6_benchmark_v1/scorecard.csv tests/reports/phase6_benchmark_v1/review.yaml --output tests/reports/phase6_benchmark_v1/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py benchmark tests/reports/phase6_benchmark_v1/scored.csv --matrix tests/prompt_matrix/phase6_benchmark.jsonl --output tests/reports/completion/benchmark.json --overwrite
