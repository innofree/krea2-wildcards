# Current Work Handoff

이 문서는 Codex 계정 또는 세션을 바꾸더라도 `plan.md`의 작업을 같은 기준으로
이어가기 위한 현재 상태 기록이다. 서버 주소, 사용자명, 개인 홈 경로, 인증정보와
`.env` 값은 기록하지 않는다.

## Resume contract

- 저장소 루트에서 시작하고 `plan.md` 전체를 먼저 읽는다.
- `git status --short`, `git log --oneline -10`, `make progress`로 실제 상태를 다시 확인한다.
- `.env`는 존재 여부와 파일 권한만 확인하며 내용은 출력하지 않는다.
- 원격 큐가 비어 있을 때만 새 작업을 제출한다. 기존 작업은 취소하거나 변경하지 않는다.
- ComfyUI 자체를 재시작하지 않고 Impact wildcard reload 경로만 사용한다.
- 3개 seed 결과는 screen 용도이고, `approved` 승격은 서로 다른 5개 seed 증거가 있어야 한다.
- production은 최종 승격 전까지 `approved` 항목만 포함한다.
- 저장소 문서, 로그, 커밋 메시지에는 서버 주소, 계정, 개인 홈 경로를 남기지 않는다.

## Current checkpoint

- Branch: `main`
- Last committed checkpoint: `adc7d7d`
- 기존 artist signature screen은 300 signatures x 3 seeds, 총 900개 run을 완료했다.
- 기존 screen의 contact sheet 30개에 대한 분할 시각 리뷰 3개가 완료되어 아직
  커밋되지 않은 report 디렉터리에 있다.
- 기존 screen은 사실적인 공통 사진 표현이 강하고 요청한 2D 선화, 눈, 채색,
  장식 축의 발현이 약했다. 이 결과는 실패 진단 증거로 보존하고 점수를 높여
  해석하지 않는다.
- illustrated repair calibration은 5 signatures x 3 seeds, 총 15개 run을 완료했다.
- report 이미지 파일은 Git ignore 대상이며, manifest, scorecard, review, summary 같은
  소형 증거만 의도적으로 커밋한다.

## Uncommitted evidence

- `tests/reports/artist_signature_screen_v0_8/`
  - `manifest.json`
  - `scorecard.csv`
  - `review_part_a.yaml`
  - `review_part_b.yaml`
  - `review_part_c.yaml`
- `tests/reports/artist_signature_illustrated_calibration_v0_8_1/`
  - 15개의 검증된 run과 `manifest.json`, `scorecard.csv`

위 디렉터리를 삭제하거나 기존 screen 위에 새 결과를 덮어쓰지 않는다.

## Exact next actions

1. `make review-artist-signature-illustrated-calibration`을 실행한다.
2. 생성된 calibration contact sheet를 직접 확인한다.
3. 2D illustration 표현과 signature별 시각 축 차이가 충분하면 versioned v0.8.1
   full screen target을 추가하고 300 signatures x 3 seeds를 새 report 경로에 실행한다.
4. calibration이 여전히 사실적이거나 축 차이가 약하면 full screen을 제출하지 않고
   prompt wrapper만 수정한 뒤 소규모 calibration을 반복한다.
5. 기존 v0.8 분할 리뷰는 merge/score하여 실패 진단 summary로 보존하되, repaired
   screen 전에 catalog status를 변경하지 않는다.
6. repaired 3-seed screen을 통과한 signature만 seeds 4004/5005로 확장하고, 정확히
   5-seed 종합 리뷰를 거쳐 최소 200개를 `approved`로 승격한다.
7. 이후 `plan.md` 순서대로 A/B/C, single-axis, pairwise, preset, random, benchmark,
   release, runtime audit, predeploy, deploy, smoke, final strict 검증을 완료한다.

원격 실행이 필요한 셸에서는 `.env` 값을 표시하지 않고 다음처럼 현재 프로세스에만
주입한다.

```sh
set -a
source .env
set +a
```

새 세션의 첫 요청은 다음과 같이 시작한다.

> `plan.md`와 `docs/current-handoff.md`를 모두 읽고, 민감정보를 출력하지 말고,
> Git 상태와 현재 report 증거를 검증한 뒤 Exact next actions부터 승인 게이트 없이
> 계속 진행해줘.
