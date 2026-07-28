REMOTE_QUEUE_DEPTH ?= 32
REMOTE_BATCH_SIZE ?= 1

.PHONY: preview production impact-production expansion-dry-run expansion-apply catalog-v2-dry-run catalog-v2-apply check matrix artist-native-matrix artist-signature-matrix artist-signature-illustrated-calibration-matrix artist-signature-calibration-v0-8-2-matrix artist-signature-v0-8-2-matrix completion completion-predeploy-strict completion-strict progress test release release-deploy-dry-run release-deploy deploy-preview-dry-run deploy-preview deploy-production-dry-run deploy-production remote-production-smoke finalize-production-deployment finish-production remote-smoke remote-pilot remote-style-refill-calibration remote-generated-screen remote-testing-retest review-style-screen remote-artist-native-dry-run remote-artist-native review-artist-native remote-artist-signature-dry-run remote-artist-signature review-artist-signature score-artist-signature-screen apply-artist-signature-screen remote-artist-signature-illustrated-calibration review-artist-signature-illustrated-calibration remote-artist-signature-calibration-v0-8-2 review-artist-signature-calibration-v0-8-2 remote-artist-signature-v0-8-2 review-artist-signature-v0-8-2 score-artist-signature-v0-8-2 apply-artist-signature-v0-8-2 remote-artist-signature-retest combine-artist-signature-retest review-artist-signature-retest score-artist-signature-retest apply-artist-signature-retest remote-artist-signature-retest-v0-8-2 combine-artist-signature-retest-v0-8-2 review-artist-signature-retest-v0-8-2 score-artist-signature-retest-v0-8-2 apply-artist-signature-retest-v0-8-2
.PHONY: runtime-audit phase6-calibration-matrix phase6-calibration-gate remote-phase6-calibration review-phase6-calibration score-phase6-calibration phase6-single-axis-matrix phase6-pairwise-matrix phase6-presets-matrix phase6-random-matrix phase6-benchmark-matrix remote-phase6-single-axis remote-phase6-pairwise remote-phase6-presets remote-phase6-random remote-phase6-benchmark review-phase6-single-axis review-phase6-pairwise review-phase6-presets review-phase6-random review-phase6-benchmark score-phase6-single-axis score-phase6-pairwise score-phase6-presets score-phase6-random score-phase6-benchmark
.PHONY: artist-abc-map artist-abc-matrix remote-artist-abc-dry-run remote-artist-abc review-artist-abc score-artist-abc
.PHONY: prepare-artist-signature-repair-v0-8-3 apply-artist-signature-repair-lifecycle-v0-8-3 artist-signature-repair-v0-8-3-matrix remote-artist-signature-repair-v0-8-3 review-artist-signature-repair-v0-8-3 score-artist-signature-repair-v0-8-3 apply-artist-signature-repair-v0-8-3 artist-signature-testing-pilot-v0-8-3 artist-signature-retest-v0-8-3-matrix remote-artist-signature-retest-v0-8-3 combine-artist-signature-retest-v0-8-3 review-artist-signature-retest-v0-8-3 score-artist-signature-retest-v0-8-3 apply-artist-signature-retest-v0-8-3
.PHONY: artist-signature-repair-framing-calibration-v0-8-4-matrix remote-artist-signature-repair-framing-calibration-v0-8-4 review-artist-signature-repair-framing-calibration-v0-8-4 score-artist-signature-repair-framing-calibration-v0-8-4
.PHONY: artist-signature-repair-single-view-calibration-v0-8-5-matrix remote-artist-signature-repair-single-view-calibration-v0-8-5 review-artist-signature-repair-single-view-calibration-v0-8-5 score-artist-signature-repair-single-view-calibration-v0-8-5
.PHONY: artist-signature-repair-editorial-calibration-v0-8-6-matrix remote-artist-signature-repair-editorial-calibration-v0-8-6 review-artist-signature-repair-editorial-calibration-v0-8-6 score-artist-signature-repair-editorial-calibration-v0-8-6
.PHONY: artist-signature-repair-axis-calibration-v0-8-7-matrix remote-artist-signature-repair-axis-calibration-v0-8-7 review-artist-signature-repair-axis-calibration-v0-8-7 score-artist-signature-repair-axis-calibration-v0-8-7
.PHONY: artist-signature-repair-reinforced-axis-calibration-v0-8-8-matrix remote-artist-signature-repair-reinforced-axis-calibration-v0-8-8 review-artist-signature-repair-reinforced-axis-calibration-v0-8-8 score-artist-signature-repair-reinforced-axis-calibration-v0-8-8
.PHONY: artist-signature-repair-reinforced-axis-v0-8-8-matrix remote-artist-signature-repair-reinforced-axis-v0-8-8 review-artist-signature-repair-reinforced-axis-v0-8-8 score-artist-signature-repair-reinforced-axis-v0-8-8 apply-artist-signature-repair-reinforced-axis-v0-8-8
.PHONY: artist-signature-testing-pilot-v0-8-8 artist-signature-retest-v0-8-8-matrix remote-artist-signature-retest-v0-8-8 combine-artist-signature-retest-v0-8-8 review-artist-signature-retest-v0-8-8 score-artist-signature-retest-v0-8-8 apply-artist-signature-retest-v0-8-8

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
	python3 scripts/export_artist_visual_signature_matrix.py --omit-prompt-digest --output tests/prompt_matrix/artist_visual_signature.jsonl

artist-signature-illustrated-calibration-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --omit-prompt-digest --limit-signatures 5 --output tests/prompt_matrix/artist_visual_signature_illustrated_calibration.jsonl

artist-signature-calibration-v0-8-2-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --omit-prompt-digest --status generated --seed 1001 --seed 2002 --seed 3003 --limit-signatures 5 --output tests/prompt_matrix/artist_visual_signature_calibration_v0_8_2.jsonl

artist-signature-v0-8-2-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --omit-prompt-digest --status generated --seed 1001 --seed 2002 --seed 3003 --output tests/prompt_matrix/artist_visual_signature_v0_8_2.jsonl

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
	python3 scripts/run_remote_benchmark.py --style-id crystal_iris_pastel --seed 6006 --output tests/reports/production_smoke_v1 --deployment-evidence tests/reports/deployments/production_v1.json --submit

finalize-production-deployment:
	python3 scripts/finalize_production_deployment.py --evidence tests/reports/deployments/production_v1.json --smoke-root tests/reports/production_smoke_v1

finish-production:
	@if python3 scripts/finalize_production_deployment.py --quiet --evidence tests/reports/deployments/production_v1.json --smoke-root tests/reports/production_smoke_v1; then \
		echo "Reusing current production deployment and smoke evidence."; \
	else \
		$(MAKE) deploy-production remote-production-smoke finalize-production-deployment; \
	fi
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
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_native_name.jsonl --batch-size $(REMOTE_BATCH_SIZE)

remote-artist-native: artist-native-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_native_name.jsonl --output tests/reports/artist_native_screen_v0_7 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-native:
	python3 scripts/build_artist_native_contact_sheets.py tests/reports/artist_native_screen_v0_7/scorecard.csv --overwrite

remote-artist-signature-dry-run: artist-signature-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature.jsonl --batch-size $(REMOTE_BATCH_SIZE)

remote-artist-signature: artist-signature-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature.jsonl --output tests/reports/artist_signature_screen_v0_8 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_screen_v0_8/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature.jsonl --expected-seeds 3 --cases-per-sheet 10 --overwrite

score-artist-signature-screen:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_screen_v0_8/review_part_a.yaml tests/reports/artist_signature_screen_v0_8/review_part_b.yaml tests/reports/artist_signature_screen_v0_8/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_screen_v0_8/scorecard.csv --output tests/reports/artist_signature_screen_v0_8/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_screen_v0_8/scorecard.csv tests/reports/artist_signature_screen_v0_8/review.yaml --output tests/reports/artist_signature_screen_v0_8/scored.csv --overwrite
	python3 scripts/summarize_results.py tests/reports/artist_signature_screen_v0_8/scored.csv --output tests/reports/artist_signature_screen_v0_8/summary.json

apply-artist-signature-screen: score-artist-signature-screen
	python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_screen_v0_8/summary.json --catalog catalog/artists.yaml --evaluation-id artist_signature_screen_v0_8 --from-status generated --apply

remote-artist-signature-illustrated-calibration: artist-signature-illustrated-calibration-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_illustrated_calibration.jsonl --output tests/reports/artist_signature_illustrated_calibration_v0_8_1 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-illustrated-calibration:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_illustrated_calibration_v0_8_1/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_illustrated_calibration.jsonl --expected-seeds 3 --cases-per-sheet 5 --overwrite

remote-artist-signature-calibration-v0-8-2: artist-signature-calibration-v0-8-2-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_calibration_v0_8_2.jsonl --output tests/reports/artist_signature_calibration_v0_8_2 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-calibration-v0-8-2:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_calibration_v0_8_2/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_calibration_v0_8_2.jsonl --expected-seeds 3 --cases-per-sheet 5 --overwrite

remote-artist-signature-v0-8-2: artist-signature-v0-8-2-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_v0_8_2.jsonl --output tests/reports/artist_signature_screen_v0_8_2 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-v0-8-2:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_screen_v0_8_2/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_v0_8_2.jsonl --expected-seeds 3 --cases-per-sheet 10 --overwrite

score-artist-signature-v0-8-2:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_screen_v0_8_2/review_part_a.yaml tests/reports/artist_signature_screen_v0_8_2/review_part_b.yaml tests/reports/artist_signature_screen_v0_8_2/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_screen_v0_8_2/scorecard.csv --output tests/reports/artist_signature_screen_v0_8_2/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_screen_v0_8_2/scorecard.csv tests/reports/artist_signature_screen_v0_8_2/review.yaml --output tests/reports/artist_signature_screen_v0_8_2/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_v0_8_2.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_screen_v0_8_2/scored.csv --prompt-binding tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json --output tests/reports/artist_signature_screen_v0_8_2/summary.json

apply-artist-signature-v0-8-2: score-artist-signature-v0-8-2
	python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_screen_v0_8_2/summary.json --catalog catalog/artists.yaml --prompt-binding tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json --evaluation-id artist_signature_screen_v0_8_2 --from-status generated --require-exact-source-set --require-tested-seeds 3 --allow-recommendation testing --allow-recommendation rejected --minimum-recommendation testing=200 --apply
	python3 scripts/sync_catalog_v2.py --apply
	python3 scripts/validate_catalog_v2.py

prepare-artist-signature-repair-v0-8-3:
	python3 scripts/prepare_artist_screen_repair_lifecycle.py tests/reports/artist_signature_screen_v0_8_2/summary.json --prompt-binding tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_lifecycle_v0_8_3/summary.json

apply-artist-signature-repair-lifecycle-v0-8-3:
	@if python3 scripts/check_evaluation_applied.py tests/reports/artist_signature_repair_lifecycle_v0_8_3/summary.json --catalog catalog/artists.yaml --evaluation-id artist_signature_screen_v0_8_2_deferred_repair; then \
		echo "Reusing the applied v0.8.2 deferred-repair lifecycle."; \
	else \
		$(MAKE) prepare-artist-signature-repair-v0-8-3 && \
		python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_repair_lifecycle_v0_8_3/summary.json --catalog catalog/artists.yaml --prompt-binding tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json --evaluation-id artist_signature_screen_v0_8_2_deferred_repair --from-status generated --require-exact-source-set --require-tested-seeds 3 --allow-recommendation testing --allow-recommendation generated --minimum-recommendation testing=185 --apply; \
	fi
	python3 scripts/refresh_generation_manifest.py catalog/artists.yaml --apply
	python3 scripts/sync_catalog_v2.py --apply
	python3 scripts/validate_catalog_v2.py

artist-signature-repair-v0-8-3-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --benchmark-profile artist_visual_signature_repair_v0_8_3 --status generated --seed 6101 --seed 6202 --seed 6303 --require-signatures 115 --output tests/prompt_matrix/artist_visual_signature_repair_v0_8_3.jsonl

remote-artist-signature-repair-v0-8-3: artist-signature-repair-v0-8-3-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_repair_v0_8_3.jsonl --output tests/reports/artist_signature_repair_v0_8_3 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-repair-v0-8-3:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_repair_v0_8_3/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_repair_v0_8_3.jsonl --expected-seeds 3 --cases-per-sheet 10 --overwrite

score-artist-signature-repair-v0-8-3:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_repair_v0_8_3/review_part_a.yaml tests/reports/artist_signature_repair_v0_8_3/review_part_b.yaml tests/reports/artist_signature_repair_v0_8_3/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_repair_v0_8_3/scorecard.csv --output tests/reports/artist_signature_repair_v0_8_3/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_repair_v0_8_3/scorecard.csv tests/reports/artist_signature_repair_v0_8_3/review.yaml --output tests/reports/artist_signature_repair_v0_8_3/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_repair_v0_8_3.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_v0_8_3/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_repair_v0_8_3/scored.csv --prompt-binding tests/reports/artist_signature_repair_v0_8_3/prompt_binding.json --output tests/reports/artist_signature_repair_v0_8_3/raw_summary.json
	python3 scripts/prepare_artist_repair_result.py tests/reports/artist_signature_repair_v0_8_3/raw_summary.json --prompt-binding tests/reports/artist_signature_repair_v0_8_3/prompt_binding.json --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_v0_8_3/summary.json

apply-artist-signature-repair-v0-8-3:
	@if python3 scripts/check_evaluation_applied.py tests/reports/artist_signature_repair_v0_8_3/summary.json --catalog catalog/artists.yaml --evaluation-id artist_signature_repair_v0_8_3; then \
		echo "Reusing the applied v0.8.3 repair evaluation."; \
	else \
		$(MAKE) score-artist-signature-repair-v0-8-3 && \
		python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_repair_v0_8_3/summary.json --catalog catalog/artists.yaml --prompt-binding tests/reports/artist_signature_repair_v0_8_3/prompt_binding.json --evaluation-id artist_signature_repair_v0_8_3 --from-status generated --require-exact-source-set --require-tested-seeds 3 --allow-recommendation testing --allow-recommendation generated --apply; \
	fi
	python3 scripts/refresh_generation_manifest.py catalog/artists.yaml --apply
	python3 scripts/sync_catalog_v2.py --apply
	python3 scripts/validate_catalog_v2.py

artist-signature-repair-framing-calibration-v0-8-4-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --benchmark-profile artist_visual_signature_repair_framing_calibration_v0_8_4 --status generated --seed 7101 --seed 7202 --seed 7303 --limit-signatures 5 --require-candidates 115 --require-signatures 5 --output tests/prompt_matrix/artist_visual_signature_repair_framing_calibration_v0_8_4.jsonl

remote-artist-signature-repair-framing-calibration-v0-8-4: artist-signature-repair-framing-calibration-v0-8-4-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_repair_framing_calibration_v0_8_4.jsonl --output tests/reports/artist_signature_repair_framing_calibration_v0_8_4 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-repair-framing-calibration-v0-8-4:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_repair_framing_calibration_v0_8_4/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_repair_framing_calibration_v0_8_4.jsonl --expected-seeds 3 --cases-per-sheet 5 --overwrite

score-artist-signature-repair-framing-calibration-v0-8-4:
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_repair_framing_calibration_v0_8_4/scorecard.csv tests/reports/artist_signature_repair_framing_calibration_v0_8_4/review.yaml --output tests/reports/artist_signature_repair_framing_calibration_v0_8_4/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_repair_framing_calibration_v0_8_4.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_framing_calibration_v0_8_4/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_repair_framing_calibration_v0_8_4/scored.csv --prompt-binding tests/reports/artist_signature_repair_framing_calibration_v0_8_4/prompt_binding.json --output tests/reports/artist_signature_repair_framing_calibration_v0_8_4/summary.json

artist-signature-repair-single-view-calibration-v0-8-5-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --benchmark-profile artist_visual_signature_repair_single_view_calibration_v0_8_5 --status generated --seed 8101 --seed 8202 --seed 8303 --limit-signatures 5 --require-candidates 115 --require-signatures 5 --output tests/prompt_matrix/artist_visual_signature_repair_single_view_calibration_v0_8_5.jsonl

remote-artist-signature-repair-single-view-calibration-v0-8-5: artist-signature-repair-single-view-calibration-v0-8-5-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_repair_single_view_calibration_v0_8_5.jsonl --output tests/reports/artist_signature_repair_single_view_calibration_v0_8_5 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-repair-single-view-calibration-v0-8-5:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_repair_single_view_calibration_v0_8_5/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_repair_single_view_calibration_v0_8_5.jsonl --expected-seeds 3 --cases-per-sheet 5 --overwrite

score-artist-signature-repair-single-view-calibration-v0-8-5:
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_repair_single_view_calibration_v0_8_5/scorecard.csv tests/reports/artist_signature_repair_single_view_calibration_v0_8_5/review.yaml --output tests/reports/artist_signature_repair_single_view_calibration_v0_8_5/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_repair_single_view_calibration_v0_8_5.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_single_view_calibration_v0_8_5/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_repair_single_view_calibration_v0_8_5/scored.csv --prompt-binding tests/reports/artist_signature_repair_single_view_calibration_v0_8_5/prompt_binding.json --output tests/reports/artist_signature_repair_single_view_calibration_v0_8_5/summary.json

artist-signature-repair-editorial-calibration-v0-8-6-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --benchmark-profile artist_visual_signature_repair_editorial_calibration_v0_8_6 --status generated --seed 9101 --seed 9202 --seed 9303 --limit-signatures 5 --require-candidates 115 --require-signatures 5 --output tests/prompt_matrix/artist_visual_signature_repair_editorial_calibration_v0_8_6.jsonl

remote-artist-signature-repair-editorial-calibration-v0-8-6: artist-signature-repair-editorial-calibration-v0-8-6-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_repair_editorial_calibration_v0_8_6.jsonl --output tests/reports/artist_signature_repair_editorial_calibration_v0_8_6 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-repair-editorial-calibration-v0-8-6:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_repair_editorial_calibration_v0_8_6/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_repair_editorial_calibration_v0_8_6.jsonl --expected-seeds 3 --cases-per-sheet 5 --overwrite

score-artist-signature-repair-editorial-calibration-v0-8-6:
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_repair_editorial_calibration_v0_8_6/scorecard.csv tests/reports/artist_signature_repair_editorial_calibration_v0_8_6/review.yaml --output tests/reports/artist_signature_repair_editorial_calibration_v0_8_6/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_repair_editorial_calibration_v0_8_6.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_editorial_calibration_v0_8_6/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_repair_editorial_calibration_v0_8_6/scored.csv --prompt-binding tests/reports/artist_signature_repair_editorial_calibration_v0_8_6/prompt_binding.json --output tests/reports/artist_signature_repair_editorial_calibration_v0_8_6/summary.json

artist-signature-repair-axis-calibration-v0-8-7-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --benchmark-profile artist_visual_signature_repair_axis_calibration_v0_8_7 --status generated --seed 11101 --seed 11202 --seed 11303 --limit-signatures 5 --require-candidates 115 --require-signatures 5 --output tests/prompt_matrix/artist_visual_signature_repair_axis_calibration_v0_8_7.jsonl

remote-artist-signature-repair-axis-calibration-v0-8-7: artist-signature-repair-axis-calibration-v0-8-7-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_repair_axis_calibration_v0_8_7.jsonl --output tests/reports/artist_signature_repair_axis_calibration_v0_8_7 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-repair-axis-calibration-v0-8-7:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_repair_axis_calibration_v0_8_7/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_repair_axis_calibration_v0_8_7.jsonl --expected-seeds 3 --cases-per-sheet 5 --overwrite

score-artist-signature-repair-axis-calibration-v0-8-7:
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_repair_axis_calibration_v0_8_7/scorecard.csv tests/reports/artist_signature_repair_axis_calibration_v0_8_7/review.yaml --output tests/reports/artist_signature_repair_axis_calibration_v0_8_7/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_repair_axis_calibration_v0_8_7.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_axis_calibration_v0_8_7/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_repair_axis_calibration_v0_8_7/scored.csv --prompt-binding tests/reports/artist_signature_repair_axis_calibration_v0_8_7/prompt_binding.json --output tests/reports/artist_signature_repair_axis_calibration_v0_8_7/summary.json

artist-signature-repair-reinforced-axis-calibration-v0-8-8-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --benchmark-profile artist_visual_signature_repair_reinforced_axis_calibration_v0_8_8 --status generated --seed 12101 --seed 12202 --seed 12303 --limit-signatures 5 --require-candidates 115 --require-signatures 5 --output tests/prompt_matrix/artist_visual_signature_repair_reinforced_axis_calibration_v0_8_8.jsonl

remote-artist-signature-repair-reinforced-axis-calibration-v0-8-8: artist-signature-repair-reinforced-axis-calibration-v0-8-8-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_repair_reinforced_axis_calibration_v0_8_8.jsonl --output tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-repair-reinforced-axis-calibration-v0-8-8:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_repair_reinforced_axis_calibration_v0_8_8.jsonl --expected-seeds 3 --cases-per-sheet 5 --overwrite

score-artist-signature-repair-reinforced-axis-calibration-v0-8-8:
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8/scorecard.csv tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8/review.yaml --output tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_repair_reinforced_axis_calibration_v0_8_8.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8/scored.csv --prompt-binding tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8/prompt_binding.json --output tests/reports/artist_signature_repair_reinforced_axis_calibration_v0_8_8/summary.json

artist-signature-repair-reinforced-axis-v0-8-8-matrix:
	python3 scripts/export_artist_visual_signature_matrix.py --benchmark-profile artist_visual_signature_repair_reinforced_axis_v0_8_8 --status generated --seed 13101 --seed 13202 --seed 13303 --require-signatures 115 --output tests/prompt_matrix/artist_visual_signature_repair_reinforced_axis_v0_8_8.jsonl

remote-artist-signature-repair-reinforced-axis-v0-8-8: artist-signature-repair-reinforced-axis-v0-8-8-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_repair_reinforced_axis_v0_8_8.jsonl --output tests/reports/artist_signature_repair_reinforced_axis_v0_8_8 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-signature-repair-reinforced-axis-v0-8-8:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/scorecard.csv --matrix tests/prompt_matrix/artist_visual_signature_repair_reinforced_axis_v0_8_8.jsonl --expected-seeds 3 --cases-per-sheet 10 --overwrite

score-artist-signature-repair-reinforced-axis-v0-8-8:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/review_part_a.yaml tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/review_part_b.yaml tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/scorecard.csv --output tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/scorecard.csv tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/review.yaml --output tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_repair_reinforced_axis_v0_8_8.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/scored.csv --prompt-binding tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/prompt_binding.json --output tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/raw_summary.json
	python3 scripts/prepare_artist_repair_result.py tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/raw_summary.json --prompt-binding tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/prompt_binding.json --catalog catalog/artists.yaml --benchmark-profile artist_visual_signature_repair_reinforced_axis_v0_8_8 --output tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/summary.json

apply-artist-signature-repair-reinforced-axis-v0-8-8:
	@if python3 scripts/check_evaluation_applied.py tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/summary.json --catalog catalog/artists.yaml --evaluation-id artist_signature_repair_reinforced_axis_v0_8_8; then \
		echo "Reusing the applied v0.8.8 reinforced-axis repair evaluation."; \
	else \
		$(MAKE) score-artist-signature-repair-reinforced-axis-v0-8-8 && \
		python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/summary.json --catalog catalog/artists.yaml --prompt-binding tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/prompt_binding.json --evaluation-id artist_signature_repair_reinforced_axis_v0_8_8 --from-status generated --require-exact-source-set --require-tested-seeds 3 --allow-recommendation testing --allow-recommendation generated --apply; \
	fi
	python3 scripts/refresh_generation_manifest.py catalog/artists.yaml --apply
	python3 scripts/sync_catalog_v2.py --apply
	python3 scripts/validate_catalog_v2.py

artist-signature-testing-pilot-v0-8-8:
	python3 scripts/select_artist_testing_pilot.py tests/reports/artist_signature_screen_v0_8_2/scored.csv tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/scored.csv --legacy-binding tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json --repair-binding tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/prompt_binding.json --catalog catalog/artists.yaml --output tests/reports/artist_signature_combined_v0_8_8/pilot_scorecard.csv --overwrite

artist-signature-retest-v0-8-8-matrix: artist-signature-testing-pilot-v0-8-8
	python3 scripts/export_artist_testing_retest_matrix.py tests/reports/artist_signature_combined_v0_8_8/pilot_scorecard.csv --catalog catalog/artists.yaml --output tests/prompt_matrix/artist_visual_signature_retest_v0_8_8.jsonl

remote-artist-signature-retest-v0-8-8: artist-signature-retest-v0-8-8-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_retest_v0_8_8.jsonl --output tests/reports/artist_signature_retest_v0_8_8 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

combine-artist-signature-retest-v0-8-8:
	python3 scripts/select_artist_testing_pilot.py tests/reports/artist_signature_screen_v0_8_2/scored.csv tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/scored.csv --legacy-binding tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json --repair-binding tests/reports/artist_signature_repair_reinforced_axis_v0_8_8/prompt_binding.json --catalog catalog/artists.yaml --output tests/reports/artist_signature_combined_v0_8_8/pilot_scorecard.csv --extension-scorecard tests/reports/artist_signature_retest_v0_8_8/scorecard.csv --extension-matrix tests/prompt_matrix/artist_visual_signature_retest_v0_8_8.jsonl --combined-output tests/reports/artist_signature_combined_v0_8_8/scorecard.csv --overwrite

review-artist-signature-retest-v0-8-8: combine-artist-signature-retest-v0-8-8
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_combined_v0_8_8/scorecard.csv --expected-seeds 5 --cases-per-sheet 10 --overwrite

score-artist-signature-retest-v0-8-8:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_combined_v0_8_8/review_part_a.yaml tests/reports/artist_signature_combined_v0_8_8/review_part_b.yaml tests/reports/artist_signature_combined_v0_8_8/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_combined_v0_8_8/scorecard.csv --output tests/reports/artist_signature_combined_v0_8_8/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_combined_v0_8_8/scorecard.csv tests/reports/artist_signature_combined_v0_8_8/review.yaml --output tests/reports/artist_signature_combined_v0_8_8/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_retest_v0_8_8.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_combined_v0_8_8/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_combined_v0_8_8/scored.csv --prompt-binding tests/reports/artist_signature_combined_v0_8_8/prompt_binding.json --output tests/reports/artist_signature_combined_v0_8_8/summary.json

apply-artist-signature-retest-v0-8-8:
	@if python3 scripts/check_evaluation_applied.py tests/reports/artist_signature_combined_v0_8_8/summary.json --catalog catalog/artists.yaml --evaluation-id artist_signature_retest_v0_8_8; then \
		echo "Reusing the applied v0.8.8 five-seed retest evaluation."; \
	else \
		$(MAKE) score-artist-signature-retest-v0-8-8 && \
		python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_combined_v0_8_8/summary.json --catalog catalog/artists.yaml --prompt-binding tests/reports/artist_signature_combined_v0_8_8/prompt_binding.json --evaluation-id artist_signature_retest_v0_8_8 --from-status testing --require-exact-source-set --require-tested-seeds 5 --allow-recommendation approved --allow-recommendation rejected --minimum-recommendation approved=200 --apply; \
	fi
	python3 scripts/refresh_generation_manifest.py catalog/artists.yaml --apply
	python3 scripts/sync_catalog_v2.py --apply
	python3 scripts/validate_catalog_v2.py

artist-signature-testing-pilot-v0-8-3:
	python3 scripts/select_artist_testing_pilot.py tests/reports/artist_signature_screen_v0_8_2/scored.csv tests/reports/artist_signature_repair_v0_8_3/scored.csv --legacy-binding tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json --repair-binding tests/reports/artist_signature_repair_v0_8_3/prompt_binding.json --catalog catalog/artists.yaml --output tests/reports/artist_signature_combined_v0_8_3/pilot_scorecard.csv --overwrite

artist-signature-retest-v0-8-3-matrix: artist-signature-testing-pilot-v0-8-3
	python3 scripts/export_artist_testing_retest_matrix.py tests/reports/artist_signature_combined_v0_8_3/pilot_scorecard.csv --catalog catalog/artists.yaml --output tests/prompt_matrix/artist_visual_signature_retest_v0_8_3.jsonl

remote-artist-signature-retest-v0-8-3: artist-signature-retest-v0-8-3-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_retest_v0_8_3.jsonl --output tests/reports/artist_signature_retest_v0_8_3 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

combine-artist-signature-retest-v0-8-3:
	python3 scripts/select_artist_testing_pilot.py tests/reports/artist_signature_screen_v0_8_2/scored.csv tests/reports/artist_signature_repair_v0_8_3/scored.csv --legacy-binding tests/reports/artist_signature_screen_v0_8_2/prompt_binding.json --repair-binding tests/reports/artist_signature_repair_v0_8_3/prompt_binding.json --catalog catalog/artists.yaml --output tests/reports/artist_signature_combined_v0_8_3/pilot_scorecard.csv --extension-scorecard tests/reports/artist_signature_retest_v0_8_3/scorecard.csv --extension-matrix tests/prompt_matrix/artist_visual_signature_retest_v0_8_3.jsonl --combined-output tests/reports/artist_signature_combined_v0_8_3/scorecard.csv --overwrite

review-artist-signature-retest-v0-8-3: combine-artist-signature-retest-v0-8-3
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_combined_v0_8_3/scorecard.csv --expected-seeds 5 --cases-per-sheet 10 --overwrite

score-artist-signature-retest-v0-8-3:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_combined_v0_8_3/review_part_a.yaml tests/reports/artist_signature_combined_v0_8_3/review_part_b.yaml tests/reports/artist_signature_combined_v0_8_3/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_combined_v0_8_3/scorecard.csv --output tests/reports/artist_signature_combined_v0_8_3/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_combined_v0_8_3/scorecard.csv tests/reports/artist_signature_combined_v0_8_3/review.yaml --output tests/reports/artist_signature_combined_v0_8_3/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_retest_v0_8_3.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_combined_v0_8_3/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_combined_v0_8_3/scored.csv --prompt-binding tests/reports/artist_signature_combined_v0_8_3/prompt_binding.json --output tests/reports/artist_signature_combined_v0_8_3/summary.json

apply-artist-signature-retest-v0-8-3:
	@if python3 scripts/check_evaluation_applied.py tests/reports/artist_signature_combined_v0_8_3/summary.json --catalog catalog/artists.yaml --evaluation-id artist_signature_retest_v0_8_3; then \
		echo "Reusing the applied v0.8.3 five-seed retest evaluation."; \
	else \
		$(MAKE) score-artist-signature-retest-v0-8-3 && \
		python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_combined_v0_8_3/summary.json --catalog catalog/artists.yaml --prompt-binding tests/reports/artist_signature_combined_v0_8_3/prompt_binding.json --evaluation-id artist_signature_retest_v0_8_3 --from-status testing --require-exact-source-set --require-tested-seeds 5 --allow-recommendation approved --allow-recommendation rejected --minimum-recommendation approved=200 --apply; \
	fi
	python3 scripts/refresh_generation_manifest.py catalog/artists.yaml --apply
	python3 scripts/sync_catalog_v2.py --apply
	python3 scripts/validate_catalog_v2.py

remote-artist-signature-retest:
	python3 scripts/export_artist_visual_signature_matrix.py --status testing --seed 4004 --seed 5005 --output tests/prompt_matrix/artist_visual_signature_retest.jsonl
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_retest.jsonl --output tests/reports/artist_signature_retest_v0_8 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

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

remote-artist-signature-retest-v0-8-2:
	python3 scripts/export_artist_visual_signature_matrix.py --status testing --seed 4004 --seed 5005 --output tests/prompt_matrix/artist_visual_signature_retest_v0_8_2.jsonl
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_visual_signature_retest_v0_8_2.jsonl --output tests/reports/artist_signature_retest_v0_8_2 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

combine-artist-signature-retest-v0-8-2:
	python3 scripts/select_scorecard_styles.py tests/reports/artist_signature_screen_v0_8_2/scorecard.csv tests/reports/artist_signature_retest_v0_8_2/scorecard.csv --output tests/reports/artist_signature_combined_v0_8_2/pilot_scorecard.csv --overwrite
	python3 scripts/merge_scorecards.py tests/reports/artist_signature_combined_v0_8_2/pilot_scorecard.csv tests/reports/artist_signature_retest_v0_8_2/scorecard.csv --output tests/reports/artist_signature_combined_v0_8_2/scorecard.csv --overwrite

review-artist-signature-retest-v0-8-2: combine-artist-signature-retest-v0-8-2
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_signature_combined_v0_8_2/scorecard.csv --expected-seeds 5 --cases-per-sheet 10 --overwrite

score-artist-signature-retest-v0-8-2:
	python3 scripts/merge_visual_reviews.py tests/reports/artist_signature_combined_v0_8_2/review_part_a.yaml tests/reports/artist_signature_combined_v0_8_2/review_part_b.yaml tests/reports/artist_signature_combined_v0_8_2/review_part_c.yaml --expected-scorecard tests/reports/artist_signature_combined_v0_8_2/scorecard.csv --output tests/reports/artist_signature_combined_v0_8_2/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/artist_signature_combined_v0_8_2/scorecard.csv tests/reports/artist_signature_combined_v0_8_2/review.yaml --output tests/reports/artist_signature_combined_v0_8_2/scored.csv --overwrite
	python3 scripts/bind_artist_prompt_evidence.py tests/prompt_matrix/artist_visual_signature_v0_8_2.jsonl --catalog catalog/artists.yaml --output tests/reports/artist_signature_combined_v0_8_2/prompt_binding.json
	python3 scripts/summarize_results.py tests/reports/artist_signature_combined_v0_8_2/scored.csv --prompt-binding tests/reports/artist_signature_combined_v0_8_2/prompt_binding.json --output tests/reports/artist_signature_combined_v0_8_2/summary.json

apply-artist-signature-retest-v0-8-2: score-artist-signature-retest-v0-8-2
	python3 scripts/apply_evaluation_summary.py tests/reports/artist_signature_combined_v0_8_2/summary.json --catalog catalog/artists.yaml --prompt-binding tests/reports/artist_signature_combined_v0_8_2/prompt_binding.json --evaluation-id artist_signature_retest_v0_8_2 --from-status testing --require-exact-source-set --require-tested-seeds 5 --allow-recommendation approved --allow-recommendation rejected --minimum-recommendation approved=200 --apply
	python3 scripts/sync_catalog_v2.py --apply
	python3 scripts/validate_catalog_v2.py

runtime-audit: impact-production
	python3 scripts/audit_runtime_coverage.py --prompt-log tests/reports/phase6_benchmark_v1/runs/KB000001/run.json --overwrite

phase6-calibration-matrix:
	python3 scripts/export_phase6_matrix.py calibration --output tests/prompt_matrix/phase6_calibration_v15.jsonl

remote-phase6-calibration: phase6-calibration-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_calibration_v15.jsonl --output tests/reports/phase6_calibration_v15 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-phase6-calibration:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_calibration_v15/scorecard.csv --matrix tests/prompt_matrix/phase6_calibration_v15.jsonl --expected-seeds 3 --cases-per-sheet 8 --overwrite

score-phase6-calibration:
	python3 scripts/merge_visual_reviews.py tests/reports/phase6_calibration_v15/review_part_a.yaml tests/reports/phase6_calibration_v15/review_part_b.yaml tests/reports/phase6_calibration_v15/review_part_c.yaml --expected-scorecard tests/reports/phase6_calibration_v15/scorecard.csv --output tests/reports/phase6_calibration_v15/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/phase6_calibration_v15/scorecard.csv tests/reports/phase6_calibration_v15/review.yaml --output tests/reports/phase6_calibration_v15/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py calibration tests/reports/phase6_calibration_v15/scored.csv --matrix tests/prompt_matrix/phase6_calibration_v15.jsonl --output tests/reports/completion/phase6_calibration.json --overwrite

phase6-calibration-gate:
	python3 scripts/check_phase6_calibration.py

artist-abc-map:
	python3 scripts/select_artist_abc_candidates.py --output tests/prompt_matrix/artist_abc_signature_map.yaml --overwrite

artist-abc-matrix: artist-abc-map
	python3 scripts/export_artist_abc_matrix.py --signature-map tests/prompt_matrix/artist_abc_signature_map.yaml --output tests/prompt_matrix/artist_abc.jsonl

remote-artist-abc-dry-run: artist-abc-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_abc.jsonl --batch-size $(REMOTE_BATCH_SIZE)

remote-artist-abc: artist-abc-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/artist_abc.jsonl --output tests/reports/artist_abc_v1 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-artist-abc:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/artist_abc_v1/scorecard.csv --matrix tests/prompt_matrix/artist_abc.jsonl --expected-seeds 3 --overwrite

score-artist-abc:
	python3 scripts/merge_artist_abc_reviews.py tests/reports/artist_abc_v1/review_part_a.yaml tests/reports/artist_abc_v1/review_part_b.yaml tests/reports/artist_abc_v1/review_part_c.yaml --expected-scorecard tests/reports/artist_abc_v1/scorecard.csv --output tests/reports/artist_abc_v1/review.yaml --overwrite
	python3 scripts/apply_artist_abc_review.py tests/reports/artist_abc_v1/scorecard.csv tests/reports/artist_abc_v1/review.yaml --output tests/reports/artist_abc_v1/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py artist-abc tests/reports/artist_abc_v1/scored.csv --matrix tests/prompt_matrix/artist_abc.jsonl --output tests/reports/completion/artist_abc.json --overwrite

phase6-single-axis-matrix:
	python3 scripts/export_phase6_matrix.py single-axis --output tests/prompt_matrix/phase6_single_axis.jsonl

phase6-pairwise-matrix: score-phase6-single-axis
	python3 scripts/export_phase6_matrix.py pairwise --single-axis-report tests/reports/completion/single_axis.json --output tests/prompt_matrix/phase6_pairwise.jsonl

phase6-presets-matrix:
	python3 scripts/export_phase6_matrix.py presets --output tests/prompt_matrix/phase6_presets.jsonl

phase6-random-matrix:
	python3 scripts/export_phase6_matrix.py random-utility --output tests/prompt_matrix/phase6_random_utility.jsonl

phase6-benchmark-matrix:
	python3 scripts/export_phase6_matrix.py benchmark --output tests/prompt_matrix/phase6_benchmark.jsonl

remote-phase6-single-axis: phase6-calibration-gate phase6-single-axis-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_single_axis.jsonl --output tests/reports/phase6_single_axis_v6 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

remote-phase6-pairwise: phase6-calibration-gate phase6-pairwise-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_pairwise.jsonl --output tests/reports/phase6_pairwise_v2 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

remote-phase6-presets: phase6-calibration-gate phase6-presets-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_presets.jsonl --output tests/reports/phase6_presets_v1 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

remote-phase6-random: phase6-calibration-gate phase6-random-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_random_utility.jsonl --output tests/reports/phase6_random_utility_v1 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

remote-phase6-benchmark: phase6-calibration-gate phase6-benchmark-matrix
	python3 scripts/run_remote_prompt_matrix.py tests/prompt_matrix/phase6_benchmark.jsonl --output tests/reports/phase6_benchmark_v1 --batch-size $(REMOTE_BATCH_SIZE) --queue-depth $(REMOTE_QUEUE_DEPTH) --resume --submit

review-phase6-single-axis:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_single_axis_v6/scorecard.csv --matrix tests/prompt_matrix/phase6_single_axis.jsonl --expected-seeds 3 --overwrite

review-phase6-pairwise:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_pairwise_v2/scorecard.csv --matrix tests/prompt_matrix/phase6_pairwise.jsonl --expected-seeds 3 --overwrite

review-phase6-presets:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_presets_v1/scorecard.csv --matrix tests/prompt_matrix/phase6_presets.jsonl --expected-seeds 3 --overwrite

review-phase6-random:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_random_utility_v1/scorecard.csv --matrix tests/prompt_matrix/phase6_random_utility.jsonl --expected-seeds 3 --overwrite

review-phase6-benchmark:
	python3 scripts/build_prompt_matrix_contact_sheets.py tests/reports/phase6_benchmark_v1/scorecard.csv --matrix tests/prompt_matrix/phase6_benchmark.jsonl --expected-seeds 5 --overwrite

score-phase6-single-axis:
	python3 scripts/merge_visual_reviews.py tests/reports/phase6_single_axis_v6/review_part_a.yaml --expected-scorecard tests/reports/phase6_single_axis_v6/scorecard.csv --output tests/reports/phase6_single_axis_v6/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/phase6_single_axis_v6/scorecard.csv tests/reports/phase6_single_axis_v6/review.yaml --output tests/reports/phase6_single_axis_v6/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py single-axis tests/reports/phase6_single_axis_v6/scored.csv --matrix tests/prompt_matrix/phase6_single_axis.jsonl --output tests/reports/completion/single_axis.json --overwrite

score-phase6-pairwise:
	python3 scripts/merge_visual_reviews.py tests/reports/phase6_pairwise_v2/review_part_a.yaml tests/reports/phase6_pairwise_v2/review_part_b.yaml tests/reports/phase6_pairwise_v2/review_part_c.yaml --expected-scorecard tests/reports/phase6_pairwise_v2/scorecard.csv --output tests/reports/phase6_pairwise_v2/review.yaml --overwrite
	python3 scripts/apply_visual_review.py tests/reports/phase6_pairwise_v2/scorecard.csv tests/reports/phase6_pairwise_v2/review.yaml --output tests/reports/phase6_pairwise_v2/scored.csv --overwrite
	python3 scripts/summarize_phase6_results.py pairwise tests/reports/phase6_pairwise_v2/scored.csv --matrix tests/prompt_matrix/phase6_pairwise.jsonl --output tests/reports/completion/pairwise.json --overwrite

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
