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
| Approved style packs | 21 | 150 |
| Approved artist visual signatures | 0 | 200 |
| Character-design items | 400 | 400 |
| Pose and camera items | 600 | 600 |
| Lighting and background items | 650 | 650 |
| Complete presets | 200 | 200 |
| Total catalog items | 3,750 | 3,750 |

The initial five styles completed five-seed family-compatible evaluation and production deployment.
The remaining 45 complete packs completed 135-image screening; 16 pilot-pass styles then completed
32 extension images and are now `approved`. The other 29 showed insufficient individual style
effect and are `rejected` pending rewrites. The catalog therefore has 21 approved styles.
The 3,700 expansion entries are intentionally `generated`: exact content counts are complete, but
none is eligible for production until the three-seed screen and five-distinct-seed approval gate.
The strict completion evaluator currently passes 4 of 16 cross-checked criteria. It counts every
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

The v0.7 expansion and v0.8 refill cycles have raised the approved style-pack total to 117. The
remaining 54 rejected candidates now use a persistent retry prompt profile. Representative v0.9.3
calibration covers the last weak surface treatments at three seeds and passes the screening gate;
the official 54-candidate screen remains separate, and only its two-seed extension can produce the
five distinct seeds required for approval.

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
all registry signatures remain pending until native Krea observation. The candidate signature
structure has exactly eight axes—linework, face, eyes, body, palette, light/shading, framing, and
ornament—and no source tag is treated as proof of those visual properties. A generic resolved-prompt
runner and a 300-artist × 3-seed native-name matrix provide queue-guarded, resumable observation
without storing server or account data.

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

The completion criteria still require 129 more approved style packs and 200 approved artist visual
signatures. The next official bounded tranche screens 150 five-axis style packs at three seeds
(450 images); pilot-pass candidates receive two additional distinct seeds. Canonical artist work
starts with 300 native-name candidates at three seeds (900 observation images), followed by authored,
name-free eight-axis signatures and five-seed approval runs for at least 200 effective candidates.
No three-seed item can enter production.

Representative Phase 6 evidence is kept separate from lifecycle approval: fixed-scene single-axis
comparisons, an 8-artist native/signature/hybrid A/B/C matrix, pairwise coverage of all six required
combination types, at least 100 preset conflict checks, measured random utility, and a Krea2 Turbo
benchmark. Batches remain resumable and queue-guarded so individual failures do not invalidate
completed evidence.
