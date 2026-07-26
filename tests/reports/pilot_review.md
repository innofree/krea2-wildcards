# Pilot v0.1 review

## Run configuration

- Date: 2026-07-26
- Remote: private ComfyUI target (address redacted)
- Model: official Krea 2 Turbo MXFP8
- Encoder / VAE: Qwen3-VL 4B BF16 / Qwen Image VAE
- Sampling: Euler, simple, 8 steps, CFG 1.0
- Resolution: 1024 × 1024
- LoRA: none
- Matrix: 5 representative styles × seeds 1001, 2002, 3003
- Result: 15/15 completed, 15 valid PNG files, final resolved prompts logged

## Findings

| Style | Result | Next action |
| --- | --- | --- |
| `crystal_iris_pastel` | Thin contours, cel separation, large eyes and open pastel space remained stable across all seeds | Advance to combination testing |
| `angular_impact` | Graphic facial color planes were distinct, but the fixed relaxed pose suppressed the requested action and diagonal composition | Retest with a graphic-action-compatible template |
| `prismatic_key_visual` | Luminous game-like character rendering was stable, but plain clothing and neutral background suppressed fantasy and particle cues | Retest with a luminous-game-compatible template |
| `sumi_mist` | Ink wash, paper texture, open space and monochrome treatment were strong and stable across all seeds | Advance to combination testing |
| `minimal_studio` | Editorial realism and fabric were stable, but the pack's full-length composition conflicted with the fixed mid-thigh frame and cropped the head in all seeds | Retest with a full-length editorial template |

## Decision

All five entries move from `generated` to `testing`; none are promoted directly to
`approved`. The pilot verifies the remote deployment and shows strong style responsiveness,
but also demonstrates that a single neutral benchmark is unsuitable for complete packs that
control pose, setting, or framing. Family-compatible templates must precede the full 150-image
run. Three seeds satisfy the pilot minimum but not the five-seed approval minimum. Atomic
linework, coloring, and shading entries can continue using a strict single-axis fixed template.
