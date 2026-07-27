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
- Last committed checkpoint: `5422fa5`
- 기존 v0.8 300-signature screen과 v0.8.1 illustrated calibration은 실패 진단
  증거와 assessment를 포함해 커밋했다. 두 결과 모두 catalog status에 적용하지 않았다.
- v0.8.2 wrapper는 signature 문두 배치, mid-thigh face 확대, signature-controlled
  lighting/composition/ornament를 사용한다.
- v0.8.2 calibration은 5 signatures x 3 seeds, 15개 run과 35/35 feature coverage를
  완료했고 contact sheet 시각 판정에서 full screen 진행 기준을 통과했다.
- v0.8.2 300 signatures x 3 seeds full screen이 versioned report 경로에서 실행 중이다.
- 원격 생성은 최대 queue depth를 `REMOTE_QUEUE_DEPTH`로 관리하며 향후 기본값은 32다.
  시작 전 empty-queue guard와 개별 run 검증은 그대로 유지한다.
- 현재 완료 기준 감사는 4/16이다. 남은 항목은 artist approval, Phase 6 생성 증거,
  production build/runtime audit/deploy/smoke 계열이다.
- report 이미지 파일은 Git ignore 대상이며, manifest, scorecard, review, summary 같은
  소형 증거만 의도적으로 커밋한다.

## Uncommitted evidence

- `tests/reports/artist_signature_screen_v0_8_2/`
  - 실행 중인 full screen의 검증된 partial runs
- `tests/reports/completion_criteria.json`
  - 중간 완료 기준 감사로 갱신된 파일

실행 중인 report를 삭제하거나 기존 versioned screen 위에 다른 matrix 결과를
덮어쓰지 않는다.

## Exact next actions

1. 현재 full-screen 프로세스 상태와 원격 큐를 먼저 확인한다. 실행 중이면 중복
   제출하지 않고 완료까지 관찰한다.
2. 프로세스가 중단됐고 원격 큐가 비어 있을 때만
   `make remote-artist-signature-v0-8-2`로 검증된 run을 resume한다.
3. 900/900 완료 후 `make review-artist-signature-v0-8-2`로 contact sheet 30개를
   만들고 3개 review part로 나눠 실제 이미지를 평가한다.
4. `make score-artist-signature-v0-8-2` 후 `testing >= 200` 게이트를 통과한 경우에만
   `make apply-artist-signature-v0-8-2`를 실행한다.
5. testing 항목만 seeds 4004/5005로 확장하고, 정확히 5-seed 종합 리뷰 후
   `approved >= 200` 게이트를 통과한 경우에만 final catalog apply를 실행한다.
6. 이후 `plan.md` 순서대로 A/B/C, single-axis, pairwise, preset, random, benchmark,
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
