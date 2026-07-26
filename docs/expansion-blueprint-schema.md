# Catalog expansion blueprint schema

The expansion compiler turns authored visual vocabularies into deterministic schema-v1 catalog
items. It never creates source research or prompt content itself. Blueprint authors remain
responsible for evidence quality and natural-language accuracy.

## Command contract

Validate every YAML file below the default blueprint directory without writing anything:

```bash
python3 scripts/generate_catalog_expansion.py catalog/blueprints
```

The default dry-run prints only the generated item count and output-file count. Add `--json` when
the full planned manifest is needed. Apply the validated compilation explicitly:

```bash
python3 scripts/generate_catalog_expansion.py catalog/blueprints --apply
```

Defaults are `catalog/` for catalog outputs, `catalog/sources.yaml` for source validation, and
`build/catalog-generation-manifest.json` for the combined ownership manifest. `--output`,
`--sources`, and `--manifest` override these paths. The compiler does not read `.env`, contact a
remote service, or generate runtime YAML.

## Blueprint directory format

Every `*.yaml` file under the supplied directory has the following shape. A directory may contain
multiple files, and each file may contain multiple collections.

```yaml
schema_version: 1
collections:
  - id: character_design
    kind: character_design
    output_file: character_designs.yaml
    family: character_design
    runtime:
      file: krea2/character/design_language.yaml
      path_prefix: [krea2, character, design_language]
    source_refs:
      - internal_taxonomy_v1
    target_count: 300
    dimensions:
      - id: silhouette
        values:
          - id: refined_elongated
            text: a refined elongated adult silhouette with balanced proportions
          - id: compact_grounded
            text: a compact grounded adult silhouette with a stable center of gravity
      - id: palette
        values:
          - id: mineral_muted
            text: a muted mineral palette with quiet blue and warm ivory accents
          - id: warm_earth
            text: a warm earth palette built from clay, olive, cream, and brown
    templates:
      - id: complete_design
        text: >-
          An adult subject has {silhouette} with {palette}. Preserve realistic skin texture,
          coherent hands, believable fabric, natural proportions, cinematic depth, and a frame
          free of text, logos, and watermarks.
    prompt_overrides:
      character_design_refined_elongated_mineral_muted_complete_design: >-
        Place three tall light bars behind the adult figure and keep their boundaries visible.
    compatibility:
      avoid: [chibi_proportions]
```

All fields except `prompt_overrides` are required. `compatibility.avoid` may be empty. IDs use
lowercase `snake_case`. `output_file` is one safe `.yaml` filename relative to the output catalog
directory; reserved metadata files and nested or parent paths are rejected. The runtime file must
be a safe `krea2/...yaml` path, and its suffix-free parts must exactly equal
`runtime.path_prefix`.

Each `source_refs` entry must exist in the configured source catalog. Every dimension has one or
more unique `{id, text}` values. Every template must reference every dimension exactly once, may not
reference unknown placeholders, and may not use conversions or format specifications. Templates
are ordinary Python-style named placeholders, not Dynamic Prompts choice syntax.

`prompt_overrides` is an optional mapping from an exact selected generated item ID to an authored
natural-language suffix. It is intended for evidence-led retests where one rejected combination
needs more observable wording without changing every item that shares a dimension value. Unknown,
unselected, unsafe, or overlong IDs fail compilation. The final template plus suffix still passes
all prose, repetition, duplicate, and 600-character checks.

## Prose rules

Dimension text and rendered prompts use trimmed English natural-language prose. The compiler
rejects unresolved braces, pipes, underscore tag syntax, artist tags, score tags, legacy `BREAK,`
delimiters, NovelAI emphasis syntax, youth-coded subjects, prohibited names, and non-prose rendering
tags. Final prompts must not exceed 600 characters or end in a comma. Abstract quality words such
as `beautiful`, `best`, `masterpiece`, `quality`, `detailed`, `polished`, `exquisite`, `stunning`,
`professional`, and `perfect` may appear at most once, and directly adjacent duplicate words are
rejected. Repeated structural nouns such as `light`, `depth`, or `subject` remain valid when the
sentence needs them. Prompts may not duplicate another prompt after whitespace, case, and
trailing-punctuation normalization.

Prompt fragments should describe observable shape, material, light, color, space, pose, or camera
properties. Put incompatibilities in `compatibility.avoid`; do not express them as negative prompt
stacks. Subject-bearing templates should explicitly use an adult subject and retain realistic skin,
coherent anatomy, believable fabric, natural proportions, cinematic depth, and text/logo/watermark
constraints.

## Deterministic selection

The candidate product is:

```text
len(templates) × product(len(dimension.values))
```

Compilation fails when that product is smaller than `target_count`. The compiler assigns every
dimension value and prose template a balanced quota: usage counts differ by at most one. It then
uses SHA-256 ranks over collection, partial-combination, axis, and value IDs to solve each Cartesian
extension deterministically. Partial tuples may repeat only within the capacity left by later axes;
the final tuples are unique. The result contains exactly `target_count` items regardless of input
YAML mapping order.

Generated item IDs join the collection ID, selected dimension-value IDs, and template ID. IDs are
limited to 180 characters so they remain safe as benchmark run-directory components. Any ID
collision or duplicate normalized prompt aborts the entire compilation before a write.

## Generated schema-v1 item

Each output item contains the current required v1 fields:

```yaml
sample_item_id:
  family: character_design
  visual_axes: [silhouette_refined_elongated, palette_mineral_muted]
  feature_axes:
    silhouette: [refined_elongated]
    palette: [mineral_muted]
  prompt: An adult subject has ...
  compatibility:
    avoid: [chibi_proportions]
  source_refs: [internal_taxonomy_v1]
  runtime:
    file: krea2/character/design_language.yaml
    path: [krea2, character, design_language, sample_item_id]
  validation:
    model: krea2_turbo
    tested_seeds: 0
    status: generated
  generation:
    collection_id: character_design
    kind: character_design
    template_id: complete_design
```

`visual_axes` preserves current flat-v1 compatibility. `feature_axes` preserves the selected value
under its declared dimension for deterministic schema-v2 synchronization. New and rewritten
eligible entries start at `generated` with zero tested seeds; the compiler never grants approval.
On a later deterministic compilation, an unchanged managed item preserves its existing validation
record. A changed item may be reset only when its previous status is `generated` or `rejected`.
Rewriting a `testing`, `approved`, `limited`, or `deprecated` item is refused so reviewed evidence
cannot be silently invalidated.

## Safe apply and manifest

Existing schema-v1 output files are merged and unrelated items are preserved. Generated item-ID or
prompt collisions fail. On subsequent runs, the prior generator manifest identifies owned items;
the compiler replaces only those items, preserves validation for body-identical items, and refuses
to proceed if a managed file changed outside the generator, if a protected evaluated body changes,
or if a prior managed output disappears from the blueprint set.

Every output and the manifest are staged and replaced atomically per file, with the manifest written
last. The combined manifest contains:

- raw SHA-256 records for every blueprint file and a deterministic combined digest;
- total generated count;
- output-relative paths, final hashes, total and generated counts, collection IDs, and owned item IDs;
- collection ID, kind, output file, exact item count, Cartesian product size, and output hash.

All recorded paths are relative. The manifest contains no prompt prose, environment values, remote
configuration, account names, or absolute filesystem paths.
