# Family retest v0.2 review

## Run configuration

- Date: 2026-07-26
- Remote: private ComfyUI target (address redacted)
- Matrix: 5 representative styles × seeds 1001, 2002, 3003
- Result: 15/15 completed as valid 1024 × 1024 PNG files
- Templates: fixed family-compatible scenes with no random option groups
- Critical failures: 0

## Findings

| Style | Result | Next action |
| --- | --- | --- |
| `crystal_iris_pastel` | Pastel cel treatment, layered eyes, visible hands, and open space remained stable | Add two approval seeds |
| `angular_impact` | Dynamic diagonal pose and graphic primary-color composition resolved the v0.1 neutral-pose conflict | Add two approval seeds |
| `prismatic_key_visual` | Fantasy environment, particles, and prismatic hero lighting are strong; all three frames are tighter than requested full length | Add two approval seeds and retain framing note |
| `sumi_mist` | Ink wash, paper grain, mist, shoreline, and negative space remained stable | Add two approval seeds |
| `minimal_studio` | All three images preserve the complete silhouette and fix the head-crop failure; one seed hides a hand in a pocket | Add two approval seeds and retain hand note |

## Five-seed extension and decision

Seeds 4004 and 5005 added 10 valid images without critical failures. The original and extension
scorecards were combined into `approval_scorecard.csv`; `approval_summary.json` reports five
distinct seeds for every style and recommends `approved` for all five entries.

The entries are promoted to `approved`. `prismatic_key_visual` retains a non-blocking limitation:
all five generations preferred a tighter hero frame over the requested full-length composition.
