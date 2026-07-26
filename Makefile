.PHONY: preview production impact-production expansion-dry-run expansion-apply catalog-v2-dry-run catalog-v2-apply check matrix progress test release release-deploy-dry-run release-deploy deploy-preview-dry-run deploy-preview deploy-production-dry-run deploy-production remote-smoke remote-pilot remote-generated-screen remote-testing-retest review-style-screen

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
	python3 scripts/deploy_remote_wildcards.py --source build/impact-wildcards/krea2_complete_pack.yaml

deploy-preview: preview
	python3 scripts/deploy_remote_wildcards.py --source build/impact-wildcards/krea2_complete_pack.yaml --apply

deploy-production-dry-run: impact-production
	python3 scripts/deploy_remote_wildcards.py

deploy-production: impact-production
	python3 scripts/deploy_remote_wildcards.py --apply

remote-smoke:
	python3 scripts/run_remote_benchmark.py --submit

remote-pilot:
	python3 scripts/run_remote_pilot.py --submit

remote-generated-screen:
	python3 scripts/run_remote_catalog_batch.py --status generated --output tests/reports/style_screen_v0_3 --resume --submit

remote-testing-retest:
	python3 scripts/run_remote_catalog_batch.py --status testing --seed 4004 --seed 5005 --output tests/reports/style_retest_v0_4 --resume --submit

review-style-screen:
	python3 scripts/build_contact_sheets.py tests/reports/style_screen_v0_3/scorecard.csv --overwrite
