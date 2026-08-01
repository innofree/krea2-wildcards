---
name: revalidate-axis
description: Run one Phase 7 catalog axis through the full revalidation pipeline — export matrix, generate on the private ComfyUI box, Stage A prefilter, saturation screen, parallel contact-sheet review, apply verdicts. Use when revalidating an axis after a rig change (e.g. the plan.md 7.35 subject anchor fix), or promoting an axis for the first time. Triggers: "revalidate <axis>", "재검증", "promote the <axis> axis", "run phase 7 on <axis>".
---

# Revalidate one Phase 7 axis

Seven axes need a second pass after the subject anchor fix (plan.md 7.35)
invalidated every prior verdict: `linework_coloring`, `camera`, `preset`,
`background`, `character_design`, `pose`, `lighting`. This is the procedure, with
the parts that have gone wrong before called out.

## Before starting

`KREA2_COMFY_API_URL` must be set — the runner reads it from the environment, not
from a flag. It lives in `.env` (gitignored). Without it the runner fails
immediately.

```bash
export KREA2_COMFY_API_URL="$(grep -oP "(?<=KREA2_COMFY_API_URL=')[^']+" .env)"
```

Check the axis is actually pending. Every axis should be fully `generated` after
the reset; if some items are `approved`, the reset did not reach them and applying
new verdicts will conflict with the old ones.

```bash
python3 -c "
import sys; sys.path.insert(0,'scripts')
from export_phase7_matrix import select_axis_items
for s in ('generated','approved','rejected'):
    try: n = len(select_axis_items('AXIS', statuses={s}))
    except ValueError: n = 0
    print(f'{s:10s} {n}')"
```

## Pipeline

`REV=v2` throughout, UNLESS the axis already has a `_v2` report directory from
before this rig existed — check first:

```bash
ls -d tests/reports/phase7_<axis>_v*
```

`camera` already went through two passes under the broken rig (plan.md 7.26-7.28:
a termination-lock defect, then a repair and recalibration whose final promotion —
144/250 — lives in `phase7_camera_v2/`, not `_v1`). Running this pipeline with
`REV=v2` on camera hits `run_remote_prompt_matrix.py`'s "existing run state does
not match this matrix execution" and refuses to proceed — the resume-mismatch
check is what stops it from silently overwriting that history. Use `REV=v3` for
camera. Every other axis's history stops at `_v1`, so `REV=v2` is free.

Whatever `REV` you land on, it keeps this pass beside the original evidence
instead of overwriting it — the earlier reports are the record of what the broken
rig produced and are still referenced by plan.md and the Hub dataset.

```bash
# 1. Export + generate. Serial and GPU-bound: the runner does an empty-queue
#    preflight, so two axes cannot run at once. ~5s per image.
make remote-phase7-axis AXIS=<axis> REV=v2

# 2. Stage A: deterministic prefilter. Fails the axis outright on a missing seed,
#    failed job, wrong resolution, seed-identical output or flat frame.
make phase7-axis-stage-a AXIS=<axis> REV=v2

# 3. Contact sheets + crib.
make phase7-axis-sheets AXIS=<axis> REV=v2 CATALOG=catalog/<plural>.yaml
```

`CATALOG` is the plural spelling and does not always follow the axis name:
`camera` → `cameras.yaml`, `pose` → `poses.yaml`,
`character_design` → `character_designs.yaml`, `preset` → `presets.yaml`,
`linework_coloring` → `linework_coloring.yaml`, `lighting` → `lighting.yaml`,
`background` → `backgrounds.yaml`.

### 4. Saturation screen before looking at anything

```bash
python3 scripts/screen_axis_saturation.py tests/reports/phase7_<axis>_v2/scorecard.csv \
  --catalog catalog/<plural>.yaml --group-axis coloring \
  --output tests/reports/phase7_<axis>_v2/saturation_screen.json
```

Only meaningful on axes with a `coloring` feature axis. It compares each item to
its own palette group's median, which is the comparison plan.md 7.18 got wrong by
judging absolute saturation: `airy_pastel` sits near 0.10 by design while
`warm_earth` sits near 0.22, so no single threshold separates a real collapse from
a muted palette. Outliers are a shortlist to open at full resolution, never a
verdict.

**Group by the axis that defines the palette.** On the linework_coloring v2 run,
`--group-axis coloring` found 0 outliers across 300 items while `--group-axis
shading` found 12 -- all of them `airy_pastel` items sitting below a median that
the saturated palettes in the same shading group had pulled up. Grouping by
anything other than the palette axis manufactures outliers.

### 5. Review the sheets — parallel

Do NOT page 30 sheets serially. Use the fan-out workflow:

```
Workflow with scriptPath: .claude/workflows/review-axis-sheets.mjs
args: {"axis": "<axis>", "rev": "v2"}
```

One agent per sheet. Each reads its sheet image plus the crib lines for its ten
cases and writes `review_parts/sNNN.json` as `{case_NNN: [verdict, reasoning]}`,
which is the format `build_phase7_review_yaml.py` already consumes.

Verdict is `pass` or `hold`. **`hold` is not `rejected`** — it means "not approved
on this evidence", which covers both a confirmed defect and an attribute that
simply is not readable at sheet density. The distinction matters because
`build_phase7_review_yaml.py` maps `hold` to a score below the policy minimum and
lets `summarize_results.py` decide the recommendation.

### 6. Convert and apply

```bash
python3 scripts/build_phase7_review_yaml.py \
  tests/reports/phase7_<axis>_v2/review/manifest.json \
  tests/reports/phase7_<axis>_v2/review_parts \
  --output tests/reports/phase7_<axis>_v2/review.yaml

make phase7-axis-apply AXIS=<axis> REV=v2 CATALOG=catalog/<plural>.yaml
```

Then the standard gates:

```bash
python3 scripts/sync_catalog_v2.py --apply && python3 scripts/validate_catalog_v2.py
python3 -m pytest -q
```

## The A6000 endpoints are shared, not dedicated

`10.169.10.28:8188` and `:8288` are used interactively by other people/processes
(LoRA + face-detailer workflows have shown up mid-run, unrelated to this
pipeline). `run_remote_prompt_matrix.py` checks `require_empty_queue` right after
the last image completes, before writing `scorecard.csv`/`manifest.json` -- if
someone else queues a job on that endpoint in that window, the shard's images are
all real and verified (`run-state.json` already says `status: completed`) but
`scorecard.csv` is missing. `run_sharded_prompt_matrix.py`'s `merge()` requires
that file per shard and will refuse to fold an incomplete one in.

Recovery: wait for the endpoint's queue to actually clear (`GET /queue`, do not
touch someone else's job), then re-run the exact same
`run_remote_prompt_matrix.py` invocation with `--resume` against that shard's own
output directory alone. All jobs are already in `run-state.json`, so this is a
no-op generation pass that only needs the trailing empty-queue check to pass
before it writes the missing files.

## Traps this pipeline has hit

- **`--spread-cases` is not optional.** These catalogs are combinatorial, so item
  ids sort near-duplicates adjacently: consecutive chunking put a mean of 2.0
  distinct combinations on a `linework_coloring` sheet and the worst sheet held one
  combination ten times. Passing that sheet records ten verdicts having inspected
  one. The Makefile target passes it; a hand-rolled invocation must too.
- **Judge against the crib, not against position.** The crib pairs each alias with
  its actual catalog feature axes. Inferring an attribute from where a case sits on
  the sheet is how plan.md 7.18's rule got recorded.
- **A sheet thumbnail cannot settle saturation or fine linework.** Open the
  original `runs/<test_id>/image_01.png` at full resolution before recording a
  defect. 7.18's holds came from thumbnails.
- **Literal body rewrites break silently.** `export_phase6_matrix.py` reshapes
  catalog bodies by exact string match; when the catalog wording moves, the rewrite
  stops firing and nothing raises. `test_every_body_rewrite_literal_still_occurs_in_the_catalog`
  guards this — if it fails, fix the literal before generating, not after.
- **Excluded axes.** Pass `EXCLUDE_AXES=<axis>` to `phase7-axis-sheets` for
  attributes not readable at sheet density (`accent_light` on `linework_coloring`).
  The crib then marks them excluded so a sheet verdict does not silently claim to
  cover them.

## Scope

One axis per invocation. Generation serialises on the single GPU, so running two
axes concurrently gains nothing and the empty-queue preflight will reject the
second. Review parallelises freely.
