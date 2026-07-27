.PHONY: preview production impact-production expansion-dry-run expansion-apply catalog-v2-dry-run catalog-v2-apply check matrix artist-native-matrix completion completion-strict progress test release release-deploy-dry-run release-deploy deploy-preview-dry-run deploy-preview deploy-production-dry-run deploy-production remote-smoke remote-pilot remote-style-refill-calibration remote-generated-screen remote-testing-retest review-style-screen remote-artist-native-dry-run remote-artist-native

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

completion:
	python3 scripts/check_completion_criteria.py

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

release-deploy:
	python3 scripts/run_release.py --apply

deploy-preview-dry-run: preview
	python3 scripts/deploy_remote_wildcards.py --source build/impact-wildcards/krea2_complete_pack.yaml --evidence tests/reports/deployments/expansion_preview_v0_10_2-dry-run.json

deploy-preview: preview
	python3 scripts/deploy_remote_wildcards.py --source build/impact-wildcards/krea2_complete_pack.yaml --evidence tests/reports/deployments/expansion_preview_v0_10_2-apply.json --apply

deploy-production-dry-run: impact-production
	python3 scripts/deploy_remote_wildcards.py

deploy-production: impact-production
	python3 scripts/deploy_remote_wildcards.py --apply

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
