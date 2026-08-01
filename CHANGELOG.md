# Changelog

## v0.4.0

### Added

- 45-style three-seed screening evidence and 16-style two-seed approval extension.
- Strict scorecard validation, contact-sheet review, lifecycle application, and scorecard merge tools.
- Catalog schema v2 projection with two 25-item shards and complete legacy route/lifecycle coverage.
- Fail-fast release orchestration with redacted machine-readable evidence.
- Official animation, camera, fashion, environment, color, and lighting terminology sources.

### Changed

- Promoted 16 additional style packs after five unique seeds; production now contains 21 prompts.
- Classified 29 ineffective candidates as `rejected` pending prompt rewrites.
- Deployed and smoke-tested the 21-item approved-only production artifact.

### Security

- Added Git object/ref/reflog and PNG textual-metadata scanning to the default check gate.

## Unreleased

### Fixed

- Anchored the benchmark subject. Every export rig opened on `exactly one adult woman`, which
  delegated age and ethnicity to the model's prior and rendered a middle-aged Western face
  instead of the intended subject. `common.SUBJECT_IDENTITY` now names it once per prompt and
  all three exporters share it. See plan.md 7.35.
- Made every catalog prompt a subject-free fragment. The built runtime carried 3,366
  `An adult subject/character/model/portrait` openings, so a wildcard draw injected a second
  subject into prompts that already declared their own and the unanchored one won the age and
  ethnicity slot. All 3,765 prompts come from 13 blueprint templates, which now emit
  participial fragments without the per-item `Preserve realistic skin texture ...` boilerplate.
- Repaired seven literal body rewrites in `export_phase6_matrix.py` that silently matched
  nothing. Five broke on the fragmentation; two predated it, leaving two of six preset
  wardrobes without their out-of-frame garment correction on chest-up and waist-up crops
  through the run that promoted preset at 177/200.

### Changed

- Reset 2,167 evaluated items to `generated`. Each verdict recorded an
  `evaluated_prompt_sha256` for a prompt string the rewrite replaced, so the scores no longer
  described their items. `generate_catalog_expansion.py --reset-validation-on-change` demotes
  rather than bypassing the guard that refuses to rewrite an approved item. Production runtime
  is 29 items, the hand-maintained `art_styles` packs.
- Retired plan.md 7.18's `deep_jewel` rule. A 20-item pilot under the anchored rig put all six
  shading pairings in the same saturation band as the control, so the 35 items it had held look
  like an artifact of the old rig rather than a property of the coloring value.
- `phase7-axis-*` Make targets take `REV` (default `v1`) so an axis can be re-run under the
  corrected rig without overwriting its original evidence.

### Added

- `mean_saturation` to the Stage A prefilter, as a measurement and not a gate: `airy_pastel`
  and `limited_two_tone` render near 0.10 by design, so no honest per-frame threshold exists.
- `README_hf_dataset.md`, the card for the `innofree/krea2-wildcards` evidence dataset —
  17,584 review images published to the Hugging Face Hub.
- A test asserting every literal the exporter rewrites still occurs in the catalog, which is
  the check that would have caught all seven dead rewrites.

### Expansion

- Added source-grounded deterministic blueprints for 3,700 entries across 13 content categories.
- Reached the exact 3,750-item catalog target while keeping all new entries at `generated`.
- Added balanced Cartesian compilation, ownership manifests, schema-v2 synchronization, and
  concise dry-run gates.
- Generalized the Impact adapter and release evidence from one style runtime file to the complete
  canonical runtime tree.
- Aligned prose repetition lint with the plan's abstract-quality-word and adjacent-duplicate rules.
- Migrated generated style packs from four to five explicit visual axes and artist candidates to
  eight explicit signature axes while preserving the exact 3,750-item library size.
- Added deterministic stale-generated projection cleanup for blueprint identity changes; evaluated
  stale items remain protected from deletion.
- Added a pinned 300-entry canonical artist research registry with tag-identity evidence kept
  separate from pending native Krea visual-signature observation.

### Changed

- Remote server, account, and account-path configuration now uses ignored environment values.
- Pilot evaluation requires at least 3 seeds and approval requires at least 5 distinct seeds.
- Stored run metadata uses a redacted remote label instead of an API address.
- Promoted five initial style packs to `approved` after the five-seed v0.2 evaluation.

### Added

- Sensitive-record scanning in the standard `make check` workflow.
- Five fixed family-compatible benchmark templates and isolated v0.2 retest output routing.
- Five-seed family retest reports and an optional repeated `--seed` batch extension.
- Production runtime output containing the first five approved prompts.
- Approved-only Impact production deployment with dynamic namespace verification and rollback.
- Machine-readable plan targets and a persistent implementation roadmap.
- Exact same-workflow/prompt/seed reproducibility proof with zero pixel difference.
- Phase 1 official source records for NovelAI, Anima, Danbooru, and Dynamic Prompts.
- Generic resolved-prompt matrix export/execution with offline dry-run, queue guards, resume
  validation, 1024×1024 evidence, and redacted metadata.
- A strict 16-criterion completion evaluator covering content scale, five-seed approvals, functional
  and security stages, structured Phase 6 evidence, duplicate freshness, and deployment smoke.

### Fixed

- Quarantined 20 invalid-template expansion runs and 56 four-axis exploratory runs so neither can
  enter scoring, lifecycle promotion, or production.
- Quarantined a 15-image v0.6 prompt calibration after distinct five-axis combinations converged on
  neutral studio photographs; v0.7 uses concrete frame-level effects without a neutral-lighting
  conflict or duplicated quality suffix.

## 0.1.0 - 2026-07-26

### Added

- Runtime 및 catalog v1 스키마
- 10개 스타일 패밀리의 완성형 스타일 팩 후보 50개
- 승인 상태 기반 runtime YAML compiler
- YAML, 금지 토큰, 중복, 충돌 정적 검사 도구
- Prompt matrix 내보내기 및 benchmark 결과 요약 도구
- ComfyUI 템플릿 6종과 baseline 설정 템플릿
- 원격 Impact Pack 배포·reload·checksum 검증 도구
- Impact 2단계 YAML loader용 호환 runtime adapter
- 공식 Turbo MXFP8 기반 원격 API smoke 및 5×3 pilot runner
- 15장 pilot 결과와 resolved prompt 기록

### Changed

- 대표 스타일 5개를 `generated`에서 `testing`으로 승격
- complete style pack에는 family별 호환 benchmark가 필요함을 평가 정책에 반영
