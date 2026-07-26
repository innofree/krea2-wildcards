# 원격 ComfyUI 운영 기록

## 현재 상태

2026-07-26 기준으로 로컬 wildcard 프로젝트와 원격 ComfyUI의 연결을 확인했다.

| 항목 | 확인 결과 |
| --- | --- |
| ComfyUI URL | 비공개 주소, `KREA2_COMFY_API_URL`로 주입 |
| HTTP 및 API | `/`, `/system_stats`, `/object_info`, `/queue` 응답 정상 |
| ComfyUI | `0.28.0` |
| Python / PyTorch | `3.13.13` / `2.12.0+cu130` |
| GPU | NVIDIA RTX PRO 6000 Blackwell Max-Q, VRAM 약 95 GiB |
| 큐 | 확인 당시 실행 및 대기 항목 없음 |
| Krea 2 checkpoint | 9개 확인, 공식 Turbo MXFP8 및 NVFP4 포함 |
| wildcard 노드 | `ImpactWildcardProcessor`, `easy wildcards`, `easy wildcardsMatrix` 확인 |
| SSH | 비공개 계정/호스트, `KREA2_COMFY_SSH_TARGET`로 주입; 비대화형 접속 확인 |

전체 `/history`는 데이터가 매우 크므로 사용하지 않는다. 자동화에서는
`/history?max_items=1` 또는 작업 제출로 받은 `prompt_id`의
`/history/{prompt_id}`만 조회한다.

## 로컬 구축 절차

개발 의존성을 설치하고 preview runtime을 만든 뒤 정적 검사를 실행했다.

```bash
python3 -m pip install -e '.[dev]'
make check
```

검증 결과:

- 당시 generated 스타일 팩 50개(이후 5개가 `approved`로 승격)
- runtime YAML 1개
- 정확·근접 중복 0건
- conflict pair 9개 로딩 성공
- 자동 테스트 9개 통과
- 3개 고정 seed용 matrix 150행 생성 가능

초기 확인 당시에는 승인 전 후보만 존재했으므로 다음 production 빌드가 실패했다.

```bash
python3 scripts/build_runtime_yaml.py --output wildcards
# ERROR: no catalog entries matched status: approved
```

family retest v0.2 이후에는 승인된 5개 항목으로 production 빌드가 성공한다.

## 원격 wildcard 경로

공용 저장소는 다음 논리 경로다. 실제 계정 홈 경로는 기록하지 않는다.

```text
<REMOTE_COMFYUI_ROOT>/models/wildcards
```

Impact Pack 설정의 `custom_wildcards` 경로와 기본 `wildcards` 경로가 모두 이
디렉터리를 가리키는 심볼릭 링크임을 확인했다.

```text
custom_nodes/comfyui-impact-pack/custom_wildcards -> models/wildcards
custom_nodes/comfyui-impact-pack/wildcards        -> models/wildcards
```

배포 파일은 기존 컬렉션과 구분되는 단일 파일명을 사용한다.

```text
models/wildcards/krea2_complete_pack.yaml
```

파일 위치와 무관하게 YAML 내부 키가 wildcard 경로를 결정한다.

```text
__krea2/style/complete_pack/all__
__krea2/style/complete_pack/crystal_iris_pastel__
```

## 안전한 배포와 reload

실제 접속값은 ignored 로컬 파일이나 현재 shell 환경에만 둔다.

```bash
cp .env.example .env
# .env의 placeholder를 실제 값으로 교체
set -a
source .env
set +a
```

`.env`, 서버 IP, SSH 계정 및 계정 홈 경로는 문서·baseline·run metadata에
기록하지 않는다. 새 run metadata는 원격을 `private_comfyui`로만 식별한다.

기본 명령은 `rsync --dry-run`만 수행한다.

```bash
make deploy-preview-dry-run
```

실제 반영은 명시적인 apply 명령으로 수행한다.

```bash
make deploy-preview
```

배포 도구는 다음 순서로 동작한다.

1. 선택한 artifact의 leaf path 수를 동적으로 계산한다.
2. `rsync --checksum`으로 정확한 대상 파일 하나만 전송한다.
3. 기존 대상 파일이 있으면 `.bak`으로 보관한다.
4. 로컬과 원격 파일의 SHA-256을 비교한다.
5. `GET /impact/wildcards/refresh`로 cache를 다시 읽는다.
6. `GET /impact/wildcards/list`에서 계산된 경로와 정확히 같은 namespace를 검증한다.

`rsync --delete`는 사용하지 않는다.

### Impact YAML 호환 계층

현재 서버의 Impact Pack commit `66655153`은 YAML loader가 두 단계보다 깊은
mapping을 완전히 순회하지 않는다. 따라서 프로젝트의 canonical runtime은 변경하지
않고, `build_impact_yaml.py`가 배포 전용 형태로 변환한다.

```yaml
krea2:
  style/complete_pack/crystal_iris_pastel:
    - "..."
```

이 구조는 Impact 내부에서 다음 경로로 등록된다.

```text
__krea2/style/complete_pack/crystal_iris_pastel__
```

2026-07-26 첫 배포 시 canonical 4단계 YAML은 전송 및 checksum 검증에는
성공했지만 loader에 등록되지 않았다. 호환 adapter를 추가해 같은 대상 파일을
교체하도록 수정했다. 이전 전송본은 배포 도구의 `.bak` 정책으로 복구할 수 있다.

## ImpactWildcardProcessor 사용

개별 스타일 benchmark에서는 leaf wildcard를 사용한다.

```text
__krea2/style/complete_pack/crystal_iris_pastel__.
An adult woman stands in a relaxed three-quarter pose against a neutral studio backdrop.
```

- GUI 탐색 시 `mode=populate`를 사용한다.
- 확장 결과를 재현하거나 API로 보낼 때는 populated prompt를 `fixed`로 사용한다.
- `all` 경로는 무작위 탐색용이며 단일 축 benchmark에는 사용하지 않는다.
- baseline에서는 모든 LoRA를 비활성화한다.

## 다음 실행 계획

완료된 연결·배포·smoke·기존 스타일 검증과 3,700개 정적 확장 이후의 순서다.
보안 정리, template 검토, exact content build, schema-v2 projection이 끝났으므로 다음
이미지 실행은 bounded expansion pilot이다.

1. 전체 canonical preview runtime을 단일 Impact-compatible bundle로 빌드·배포한다.
2. 신규 스타일 팩 150개와 작가 시각 시그니처 150개를 seed 3개씩 실행한다.
3. contact sheet 검토와 점수 기준을 통과한 후보만 `testing`으로 이동한다.
4. pilot 통과 후보에 seed 2개를 추가해 총 5개 이상의 서로 다른 seed를 확보한다.
5. `summarize_results.py`로 5-seed 승인 기준과 점수 기준을 함께 검사한다.
6. 통과 항목만 `approved`로 승격하고 production runtime을 빌드·배포한다.
7. 작가 시그니처 200개 승인 목표에 부족한 수량은 다음 bounded tranche로 보충한다.

### 최소 baseline workflow

최근 서버 workflow는 Krea2 Turbo NVFP4를 사용했지만 LoRA 3개와 별도 후처리
분기가 활성화되어 있어 baseline으로 채택하지 않았다. 대신 공식 Turbo 설정을 따라
다음과 같이 고정했다.

- checkpoint: 공식 Krea 2 Turbo MXFP8
- text encoder: `qwen3vl_4b_bf16.safetensors`, type `krea2`
- VAE: `qwen_image_vae.safetensors`
- resolution: 1024 × 1024
- sampler / scheduler: Euler / simple
- steps / CFG: 8 / 1.0
- LoRA: 없음
- prompt expansion: `ImpactWildcardProcessor`, fixed populated text

원격 큐를 변경하지 않는 검증:

```bash
python3 scripts/run_remote_benchmark.py
```

한 장을 실제 제출하고 완료 이미지와 실행 metadata를 회수:

```bash
python3 scripts/run_remote_benchmark.py --submit
```

5개 대표 스타일과 seed 3개의 pilot matrix를 순차 실행:

```bash
python3 scripts/run_remote_pilot.py        # dry-run
python3 scripts/run_remote_pilot.py --submit
```

현재 runner의 family retest가 끝나면
`tests/reports/family_retest_v0_2/scorecard.csv`가 생성된다. 기존
`tests/reports/pilot_scorecard.csv`는 v0.1 기록으로 보존한다.

3개 seed는 pilot 최소 기준일 뿐 승인 기준이 아니다. 승격 전에는 서로 다른 seed
5개 이상과 기존 품질 임계값을 모두 충족해야 한다.

### Family retest v0.2 준비 상태

기존 generic 장면의 충돌을 제거하기 위해 다음 고정 template routing을 추가했다.

| 후보 | Family template |
| --- | --- |
| `crystal_iris_pastel` | refined pastel portrait |
| `angular_impact` | graphic diagonal action |
| `prismatic_key_visual` | luminous fantasy hero |
| `sumi_mist` | open-space mist landscape |
| `minimal_studio` | head-to-toe editorial studio |

각 template는 성인 피사체, 고정 의상·포즈·환경·조명·카메라와 동일한 자연스러운
품질 제약을 사용한다. 선택형 group은 넣지 않아 seed 외의 변수가 임의로 바뀌지
않는다. 실행 결과는 기존 pilot을 덮어쓰지 않고
`tests/reports/family_retest_v0_2/`에 저장한다.

3-seed 15장 pilot과 추가 seed 2개씩의 10장 extension을 완료했다. 총 25개 run은
모두 유효한 1024 × 1024 PNG와 비식별 metadata를 남겼고 종료 후 원격 큐는 비었다.
결과는 `tests/reports/family_retest_v0_2/`에 보존한다.

5-seed 통합 요약에서 다섯 후보 모두 prompt adherence 4.0 이상, style fidelity·
stability·compatibility 5.0, critical failure 0으로 승인 기준을 통과했다. 다섯 항목을
`approved`로 승격했고 production runtime은 5개 prompt를 포함해 정상 빌드된다.
`prismatic_key_visual`이 full-length 지시보다 가까운 hero framing을 일관되게 택한
점은 비차단 제한사항으로 유지한다.

### Production v0.1 deployment

승인된 5개 항목만 포함하는 Impact artifact를 별도로 빌드해 배포했다. 배포 도구는
preview의 고정 path 수를 사용하지 않고 artifact에서 기대 path를 계산한다. 기존 파일은
고유 timestamp suffix로 보관하며 checksum 또는 namespace 검증 실패 시 이전 파일로
rollback한다.

배포 결과는 aggregate를 포함한 6개 `__krea2/` path가 정확히 등록됐고, 별도 seed의
production smoke image가 완료됐으며 종료 후 큐는 비었다. 비식별 deployment evidence는
`tests/reports/deployments/production_v0_1.json`에 기록한다.

### Style expansion v0.4 deployment

나머지 45개 스타일을 seed 3개씩 135장으로 screening하고, pilot 품질 게이트를 통과한
16개에 seed 4004와 5005를 추가해 32장을 생성했다. 모든 이미지는 실제 디코딩 가능한
1024 × 1024 PNG이며 민감 metadata가 없고, 5-seed 통합 점수에서 16개가 승인됐다.
현재 production runtime은 기존 5개를 포함해 승인된 21개 prompt만 포함한다.

전체 로컬 게이트, production build, dry-run, 실제 배포는 `run_release.py`의 fail-fast
순서로 실행했다. aggregate를 포함한 22개 production path의 checksum·reload·정확한
namespace 검증이 통과했으며, 새 승인 항목 `holographic_city`의 별도 production smoke도
성공했다. 비식별 릴리스 증거는 `tests/reports/releases/style_v0_4-production.json`과
`tests/reports/production_smoke_v0_4/`에 보존한다.

### Catalog expansion v0.5 preparation

공식·도메인 출처에 연결된 두 blueprint에서 13개 분류 3,700개 항목을 결정적으로
생성했다. 기존 50개와 합쳐 계획 수량은 정확히 3,750개다. 신규 항목은 모두
`generated`이며 production에는 포함하지 않는다. 축별 선택 빈도 차이는 최대 1,
normalized prompt 중복은 0, 최대 prompt 길이는 600자 이하, 최대 item ID는 180자
이하다. preview compiler와 Impact adapter는 13개 canonical runtime 파일 전체를 하나의
호환 bundle로 처리한다.

schema-v2 projection은 prompt 본문을 복제하지 않고 `legacy_ref`로 연결하며, 25개 상한
shard 150개로 3,750개 전체를 표현한다. 첫 원격 tranche는 신규 스타일 150개와 작가
시그니처 150개, seed 3개씩 총 900장이다. 모든 실행은 큐가 비어 있을 때만 시작하고
완료 image·run metadata를 검증하며 resume 가능하게 저장한다.

## Pilot v0.1 결과

2026-07-26에 대표 5개 스타일 × seed 3개의 15장 pilot을 완료했다. 모든 작업이
1024 × 1024 PNG로 정상 완료됐고 원격 큐는 종료 후 비어 있었다. 각 run에는
wildcard prompt와 catalog 값으로 완전히 확장한 resolved prompt가 함께 기록된다.

핵심 결과:

- `crystal_iris_pastel`, `sumi_mist`: 스타일 반영과 seed 안정성이 강함
- `angular_impact`: 중립 정지 포즈가 action composition과 충돌
- `prismatic_key_visual`: 평상복·중립 배경이 fantasy cue와 충돌
- `minimal_studio`: mid-thigh 지시가 pack 내부 full-length 구성과 충돌해 3장 모두
  머리 상단이 잘림

따라서 전체 150장 generic matrix는 아직 실행하지 않는다. complete style pack은
family별 호환 template로 다시 테스트하고, atomic attribute만 완전히 고정된 단일 축
template를 사용한다. 상세 평가는 `tests/reports/pilot_review.md`에 기록했다.

## 기록 보안 정리

2026-07-26에 다음 실행 전 보안 정리를 완료했다.

- 소스의 원격 기본값을 제거하고 세 환경변수로 전환
- 문서와 baseline의 서버 IP, SSH 계정, 계정 홈 경로를 placeholder로 교체
- 기존 15개 `run.json`에서 API URL을 제거하고 비식별 원격명만 유지
- 새 metadata와 console 준비 로그에 원격 주소를 쓰지 않도록 변경
- `check_sensitive_data.py`를 `make check`에 추가해 재유입을 차단
- seed 정책을 pilot 최소 3개, 승인 최소 5개로 고정
- 정리 당시에는 Git 저장소가 없어 재작성할 commit/reflog가 없음을 확인했고, 이후
  clean 저장소를 초기화해 첫 commit 전 worktree·staged content·보존 이력을 다시 검사
- Git object/ref/reflog와 PNG textual metadata 검사를 기본 gate로 유지
- 로컬 zsh history에서 해당 비공개 endpoint 또는 wildcard 배포 경로를 포함한
  명령 45개를 백업 없이 제거하고 zsh/bash history 잔여 0건 확인

열려 있던 다른 interactive shell은 메모리에 과거 history를 보유할 수 있으므로,
해당 세션이 정리 전 내용을 history 파일에 다시 쓰지 않도록 주의한다.
