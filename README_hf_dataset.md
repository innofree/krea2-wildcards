---
pretty_name: krea2-wildcards review evidence
license: creativeml-openrail-m
language:
  - en
tags:
  - image
  - human-review
  - qa-evidence
  - prompt-engineering
  - text-to-image
  - synthetic-subject
size_categories:
  - 10K<n<100K
---

# krea2-wildcards — Review Evidence

Human-review contact sheets and their source renders for the
[krea2-wildcards](https://github.com/innofree/krea2-wildcards) prompt library: a project that
compiles researched visual vocabulary — art styles, linework and coloring, poses, lighting, camera
composition, character design — into ComfyUI Dynamic Prompts wildcards for the Krea2 model family.

This dataset isn't the wildcard library itself. It's the photographic evidence a reviewer looked at
when deciding, for each catalog entry, whether a given prompt fragment actually changes the rendered
image the way it's supposed to. 17,584 images, 20.1 GB: 432 contact sheets (each tiling 5–10 generated
cases with the catalog item ID and seed printed under every thumbnail) plus the 17,152 individual
1024×1024 renders each sheet was tiled from.

## Why this exists

Most prompt libraries publish a wordlist and ask you to trust that it works. This one publishes the
evaluation trail instead: every catalog axis (a lighting rig, a linework style, a pose) was rendered
across many seeds, tiled into a contact sheet, and judged pass/hold/reject by a human looking at the
actual pixels. That verdict lives in the GitHub repo's catalog; the sheet and renders behind it live
here, so the verdict is never a black box — anyone can re-open exactly what was judged.

## Contents

| Phase | Runs | Sheets | What was under test |
|---|---:|---:|---|
| Phase 6 — calibration | 13 | 70 | Small anchor probes run before each larger evaluation |
| Phase 6 — single-axis | 6 | 60 | One catalog axis changing at a time, everything else fixed |
| Phase 6 — pairwise | 2 | 20 | Two axes changing together, checking for conflicts between them |
| Phase 6 — presets / random / benchmark | 3 | 13 | Full-scene preset contracts, random-utility sampling, the fixed benchmark case |
| Phase 7 — mass promotion | 12 | 258 | Full-catalog promotion runs per axis (character design, background, camera, lighting, linework/coloring, pose, preset) plus their calibration probes |
| Artist research | 4 | 11 | Artist-signature and art-style-family screening/retest |

## Structure

```
reports/<run_name>/review/
  prompt_matrix_<mode>_<NNN>.png   # the contact sheet image(s)
  manifest.json                    # sheet -> case mapping: which item/seed is in which cell
  crib.txt                         # (3 runs) reviewer's per-case reasoning notes
reports/<run_name>/runs/<style_id>_seed_<seed>/
  image_01.png                     # the original 1024x1024 render behind one sheet cell
  run.json                         # seed, resolved prompt, generation provenance
```

`run_name` matches the report directory in the GitHub repo's `tests/reports/`, so a sheet, the
originals it was tiled from, and the scorecard/summary that judged it are always traceable to the
same run and the same catalog commit.

## The subject

Every image depicts the same fictional benchmark figure — not a real person, and not modeled on one.
She exists purely so that an axis (lighting, coloring, a camera crop) can be judged with everything
else held constant. Wardrobe across the corpus is studio and editorial fashion test clothing:
blazers, blouses, coats, dresses. Because this corpus spans dozens of independent evaluation runs
collected over time, we recommend a scan for scope before relying on any single image outside its
own run's manifest — the description above reflects what the runs were designed to test, not a
frame-by-frame audit of all 17,584 images.

## Known limitation in the early history

Every rig prompt through 2026-08-01 opened on an unanchored "one adult woman" — no age, no
ethnicity specified — which the Krea2 model resolves to a middle-aged Western face by default. The
catalog's actual intended subject is a young Korean woman with an East Asian face. Two consequences
worth knowing before trusting an older verdict in this dataset:

- Every verdict recorded against a sheet from before that date judged its axis on a subject nobody
  had actually specified.
- At least one specific finding — that the `deep_jewel` coloring value only renders saturated when
  paired with `broad_blended_plane` shading, recorded reviewing `phase7_linework_coloring_v1` — did
  not reproduce under a corrected, subject-anchored rig. It looks like an artifact of the old rig's
  photorealism instruction fighting the illustration instruction, not a real property of
  `deep_jewel`.

A subject-anchor fix landed in the GitHub repo on 2026-08-01 (`fix: anchor the benchmark subject and
repair five dead body rewrites`). Sheets and runs from that commit onward reflect the corrected
subject; anything earlier does not. Check a run's `manifest.json` timestamp or the corresponding
commit in the GitHub repo's `tests/reports/` history if the date matters for what you're doing with
a given image.

## Provenance

The GitHub repo's `tests/reports/**/run-state.json` records every image's
`resolved_prompt_sha256`, `workflow_sha256`, and `image_sha256`, and the prompt matrix behind any run
is deterministically re-exportable from the catalog at the matching commit — so every image here is
independently reproducible, not just hash-verifiable.

## License

Released under **CreativeML Open RAIL-M**. This license was chosen over a plain permissive license
(e.g. CC-BY-4.0) because every image is a generative-model output depicting a human figure: RAIL's
use-based restrictions (no use to defame, impersonate, or misrepresent an individual; no unlawful
output) exist specifically for this situation, where a plain attribution license would carry no such
safeguard.

This license covers the redistribution rights we hold over this collection and selection of images.
It does not substitute for the terms of service of the model used to generate them (Krea 2 /
`krea2TurboOfficialComfy_krea2TurboMxfp8`) — those govern the underlying generated content
independently, per this project's own `LICENSE-NOTES.md`, and should be checked separately before
any commercial reuse.

## Citation

If this is useful, please cite the companion repository:

```
Krea2 Wildcards — a source-grounded prompt library for Krea2 / ComfyUI Dynamic Prompts.
https://github.com/innofree/krea2-wildcards
```
