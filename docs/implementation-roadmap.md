# Krea2 wildcard implementation roadmap

## Execution policy

`plan.md` is executed in dependency order without routine user approval pauses. Lifecycle
transitions, remote batches, and production deployment use deterministic checks. A failing item is
kept in `testing`, moved to `limited`/`rejected`, or quarantined while unrelated batches continue.
Only missing authority, unknown external queue ownership, unresolved destructive scope, or failed
rollback stops the pipeline.

The reusable operating procedure is registered as the `krea2-wildcard-lifecycle` Codex skill.

## Current inventory

The machine-readable targets live in `catalog/roadmap.yaml`; `make progress` writes the current
report.

| Target | Current | Required |
| --- | ---: | ---: |
| Approved style packs | 150 | 150 |
| Approved artist visual signatures | 0 | 200 |
| Character-design items | 400 | 400 |
| Pose and camera items | 600 | 600 |
| Lighting and background items | 650 | 650 |
| Complete presets | 200 | 200 |
| Total catalog items | 3,750 | 3,750 |

The initial five styles completed five-seed family-compatible evaluation and production deployment.
Subsequent bounded screens and two-seed extensions raised the catalog to exactly 150 approved style
packs. Every approval has five distinct seeds and zero critical failures.
The 3,700 expansion entries are intentionally `generated`: exact content counts are complete, but
none is eligible for production until the three-seed screen and five-distinct-seed approval gate.
The strict completion evaluator currently passes 5 of 16 cross-checked criteria. It counts every
initial-scale category directly, requires the release security stages, rejects stale duplicate and
deployment evidence, and cannot treat a three-seed item as approved.

## Ordered implementation tranches

### A. Execution and safety foundation

1. Separate preview and approved-only production Impact artifacts.
2. Use dynamic expected path counts, exact namespace verification, unique backup suffixes, and
   automatic rollback.
3. Add machine-readable plan progress, evaluation evidence validation, promotion automation,
   queue ownership guards, resumable run journals, and sensitive Git/PNG history checks.
4. Prove Phase 0 reproducibility with duplicate prompt+seed runs and recorded hashes/tolerance.

Production artifact separation, dynamic path verification, backup/rollback, five-item deployment,
reload, and smoke verification are complete. Scorecard validation, lifecycle application,
resumable catalog batches, contact sheets, and sensitive Git/PNG history checks are active gates.
Phase 0 reproducibility is also complete: two
independent runs with the same prompt, workflow, and seed produced identical PNG SHA-256 values
and zero differing pixels.

### B. Schema v2 and lossless migration

1. Introduce namespaced feature, source, evaluation, runtime-route, and lifecycle registries.
2. Support `catalog/items/**/*.yaml` shards of at most 25 items.
3. Project all 3,750 catalog items without changing public wildcard paths.
4. Add reference closure, kind-specific feature cardinality, deterministic staged builds, and
   canonical/Impact equivalence tests.
5. Replace free compatibility strings with canonical feature references and structured rules.

### C. Existing style completion

1. Add fixed templates for the five uncovered style families.
2. Generalize the runner from a hardcoded five-style matrix to catalog-driven batches and resume.
3. Run the remaining 45 candidates at three seeds; add two seeds only for pilot-pass candidates.
4. Automatically score, summarize, and promote or quarantine each candidate.
5. Generate refill style batches until at least 150 styles are approved.

The 45-style, three-seed screen and the 16-style extension are independently verified at 1024x1024.
The 16 candidates completed seeds 4004 and 5005 and were approved only after five-seed aggregation;
no item was approved from only three seeds.

The v0.7 expansion and later refill cycles raised the approved style-pack total to 150. The final
v0.10.2 official screen kept four candidates in testing and rejected four; its two-seed extension
produced exactly five distinct seeds for all four candidates, and all four passed with zero critical
failures. Rejected alternatives remain quarantined and cannot enter the approved-only runtime.

The first expansion attempt exposed two invalid experimental designs. Twenty images made with a
multi-subject/crop-conflicting template are quarantined as invalid-template evidence. A later
56-image partial batch used only four explicit style axes and is quarantined as exploratory evidence.
Neither set is eligible for scoring or lifecycle promotion. The regenerated official style catalog
now fixes five independently reviewable axes: shape, color, surface, atmosphere, and edge. The v0.6
preview and execution canary passed, but a five-style × three-seed calibration exposed another
non-promotable failure: abstract treatment wording and fixed neutral lighting made visibly different
axis combinations converge on nearly identical neutral studio photographs. The v0.7 prompt revision
uses concrete frame-level effects, removes the lighting conflict and duplicated quality suffix, and
must pass a new calibration before the official 150-style screen.

### D. Source and visual-signature catalogs

1. Capture official and domain terminology sources with access date, usage, license note, locator,
   evidence summary, and snapshot hash where available.
2. Normalize canonical visual feature vocabularies and aliases.
3. Build 200+ artist visual signatures with production using visual properties rather than names.
4. Evaluate native-name, visual-signature, and hybrid variants independently; expose approved
   visual signatures by default.

Phase 1 core prompting sources are registered for NovelAI tagging and character axes, the Anima
model card, Danbooru taxonomy implementation, and ComfyUI Dynamic Prompts. Domain-specific
animation, cinematography, fashion, environment, and color/lighting terminology sources are also
registered and referenced by the expansion blueprints.

A pinned CC0 Anima tagger-artifact snapshot now supplies 300 deterministic canonical artist tag
identities and post-count evidence. Identity evidence is deliberately separated from style evidence:
no source tag is treated as proof of visual properties. The queue-guarded 300-artist × 3-seed
native-name matrix completed 900 verified 1024×1024 runs. Thirty contact sheets were reviewed in
three exact partitions, then merged and checked against the full identity deny-list. All 300 registry
records now contain name-free observations on exactly eight axes—linework, face, eyes, body, palette,
light/shading, framing, and ornament. Of these, 172 were stable across the three seeds and 128 were
conservatively marked unstable. No server or account data is stored in the evidence.

### E. Atomic content expansion

The source-grounded static expansion is complete: character and face/eye design; hair;
clothing/fashion; pose/body; camera; lighting/color; backgrounds/spaces; medium/rendering;
effects/atmosphere; atomic linework/coloring/shading; style packs; artist visual signatures; and
presets total exactly 3,700 new entries. Deterministic selection keeps every dimension and template
usage balanced within one, and schema-v2 shards remain bounded at 25 items. Image evaluation now
advances bounded candidate tranches without promoting untested content.

### F. Presets, combinations, and release

1. Compose at least 100 presets only from validated dependency closures.
2. Run single-axis, artist A/B/C, pairwise combination, and random-utility evaluations.
3. Require semantic duplicate rate <= 5%, zero critical preset conflicts, and complete benchmark
   evidence.
4. Build and deploy approved-only production artifacts, verify smoke/queue/checksum/namespace, and
   publish the v1 completion report and package.

## Expected evaluation volume

The 150 approved style-pack criterion is complete. The remaining content approval criterion is 200
artist visual signatures. Canonical artist native observation already covers 300 identities at three
seeds (900 images); the active name-free candidate screen also covers 300 signatures at three seeds,
and pilot-pass candidates receive two additional distinct seeds. At least 200 effective candidates
must pass the combined five-seed score before production. No three-seed item can enter production.

Representative Phase 6 evidence is kept separate from lifecycle approval: four fixed-scene
single-axis cases, an 8-artist native/signature/hybrid A/B/C matrix, 16 pairwise cases for each of
the six required combination types (96 total), 100 preset conflict checks, 20 measured random-utility
samples, and a five-seed Krea2 Turbo benchmark. Every image batch uses at least three distinct seeds,
remains resumable, and is queue-guarded so individual failures do not invalidate completed evidence.
