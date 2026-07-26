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

1. 5축 style/8축 artist 마이그레이션과 prompt 교정을 반영한 preview를 v0.7 증거로 배포한다.
2. 신규 5축 스타일 팩 150개를 seed 3개씩 실행하고 contact sheet로 전수 검토한다.
3. 통과 후보만 `testing`으로 이동하고 seed 2개를 추가해 서로 다른 seed 5개를 확보한다.
4. 5-seed 통합 점수 기준을 통과한 항목만 `approved`로 승격해 style 150개를 확보한다.
5. canonical artist 300명의 native-name 반응을 seed 3개로 관찰하고 각 8축 시각 특성을
   이름 없는 자연어 시그니처로 작성한다.
6. 시그니처 후보를 5-seed 승인하고 대표 8명은 native/signature/hybrid A/B/C로 비교한다.
7. 단일축·pairwise·preset·random utility·Turbo benchmark 후 strict 완료 판정을 수행한다.
8. 최종 approved-only production을 빌드·배포하고 smoke/queue/checksum/namespace를 확인한다.

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
shard 150개로 3,750개 전체를 표현한다. 첫 공식 원격 tranche는 신규 5축 스타일 150개를
seed 3개씩 실행하는 450장이다. canonical artist는 별도 native 관찰 matrix로 분리한다.
모든 실행은 큐가 비어 있을 때만 시작하고 완료 image·run metadata를 검증하며 resume
가능하게 저장한다.

### Axis migration and v0.6 execution gate

v0.5 첫 expansion template의 다중 피사체·crop 충돌로 생성된 20장은 invalid-template로
격리했다. 이후 시작한 style batch도 명시적 축이 shape/color/surface/atmosphere 네 개뿐인
것을 발견해 큐가 빈 시점에 안전하게 중단했고, 완료된 56장은 four-axis exploratory
증거로만 보존한다. 두 묶음 모두 점수·상태 변경·production 입력에서 제외한다.

공식 style catalog는 edge 축을 더한 정확한 5축으로 재생성했다. artist candidate 구조도
linework/face/eye/body/palette/light-shading/framing/ornament의 정확한 8축으로 재생성했다.
schema-v2 sync는 blueprint identity 변경으로 사라진 generated projection 450개를 안전하게
제거하고 새 450개를 투영하며, 평가된 항목 삭제는 거부한다. 전체는 다시 3,750개이고
static duplicate와 reference closure 검사를 통과했다.

별도의 canonical artist registry는 pinned CC0 snapshot에서 결정적으로 선택한 300개 tag
identity를 기록한다. tag identity 자체는 시각 특성 증거가 아니므로 모든 signature 축은
native Krea 관찰 전까지 pending이다. `run_remote_prompt_matrix.py`는 완전히 해석된 JSONL만
받고 wildcard·접속정보를 거부하며, 기본은 offline dry-run이다. submit 시 각 job 전후로
빈 큐를 확인하고 1024×1024 PNG, 비식별 run record, scorecard, manifest를 검증한다.

v0.6 preview의 한 장 canary는 wildcard resolution, 1인 전신 framing, scene control을
통과했다. 이어 서로 다른 조합 5개를 seed 3개씩 실행했으나, 15장 대부분이 거의 동일한
중립 스튜디오 사진으로 수렴했다. 특히 warm-cool/duotone, ceremonial/nocturnal, surface,
edge 차이가 약해 이 calibration 전체를 scoring에서 제외했다. 원인은 추상적 treatment
표현과 benchmark의 broad neutral lighting 지시가 서로 다른 축 효과를 억제한 것으로
판정했다.

v0.7은 각 축을 set division, 명시적 색, 관찰 가능한 print texture, atmosphere light,
silhouette edge처럼 화면에서 직접 확인 가능한 표현으로 바꾼다. benchmark에서는 고정
조명 색을 제거하고 composition geometry만 고정하며, 중복 quality suffix도 제거한다.
새 catalog prompt 길이는 377–420자이고 static duplicate 0건을 유지한다. 새 preview
reload와 calibration을 통과하기 전에는 150×3 official screen을 시작하지 않는다.

### Style expansion v0.7 결과와 v0.8 refill

v0.7 preview는 checksum, Impact reload, exact namespace 검증과 5개 대표 조합의 3-seed
calibration을 통과했다. 이후 150개 × 3 seed의 450장을 모두 1024 × 1024로 완료하고,
10개 스타일 단위 contact sheet 15장을 세 분할 리뷰로 전수 확인했다. 3-seed screening에서
69개가 품질 기준을 통과해 `testing`, 81개가 `rejected`가 됐으며 critical failure는 0건이다.
통과한 69개에 seed 4004/5005를 더한 138장도 같은 기준을 유지해 모두 5-seed
`approved`가 됐다. 기존 승인 21개와 합친 현재 style pack 승인은 90개다.

v0.8 refill은 실패가 집중된 geometric/minimal shape, limited/pastel color,
satin/weathered surface 및 약한 edge 구분을 화면에서 직접 확인할 수 있는 항목별 문장으로
보강한다. Blueprint `prompt_overrides` 81개와 생성기 수명주기 보호를 사용해 재작성된
81개만 `generated/0`으로 되돌리고, 본문이 동일한 승인 69개는 `approved/5`를 보존한다.
승인된 본문 변경은 생성기가 즉시 거부한다.

첫 v0.8 대표 5개 × 3-seed calibration은 15장 모두 기술적으로 성공했지만 내용 게이트에서
중단했다. Faceted/ornamental 조합은 개선됐으나 minimal은 satin/etched 특성이 거의
사라졌고, rounded는 weathered/ceremonial cue가 약했다. Geometric의 추상적인 outer-edge
표현은 주변에 추가 인물처럼 보이는 실루엣을 만들어 one-subject 제약과 충돌했다. 이
15장은 실패 원인 증거로만 보존하며 screening이나 승인 seed로 재사용하지 않는다.

v0.8.1은 색상 축이 이미 안정적으로 반영된 점을 이용해 중복 색상 보정문을 제거하고,
그 자리에 `glossy satin clothing`, `large peeling ink patches`, `narrow light beams`,
`one shoulder and trouser edge`처럼 물리적으로 관찰 가능한 surface/atmosphere/edge 지시를
넣는다. 최종 generated prompt 최대 길이는 589자이며 승인 69개의 본문과 5-seed 이력은
계속 보존된다. 두 번째 5개 × 3-seed calibration은 faceted, geometric, ornamental,
rounded 대표군을 통과시켰고 추가 인물 문제도 제거했다. Minimal 대표군만 satin sheet와
rim light를 무시해 4개 `testing`, 1개 `rejected` 판정을 받았다.

v0.8.2는 실패한 minimal shape의 25개 보정문만 다시 작성한다. Surface를 피사체 의상
형용사 대신 실제 set sheet/panel로 만들고 edge를 물리적인 rim light 또는 배경과 같은
톤의 특정 shoulder/trouser 경계로 표현한다. 비교 검사는 style 150개 중 정확히 이 25개
본문만 변경되고 승인 69개와 v0.8.1을 통과한 non-minimal 56개가 동일함을 확인한다.
첫 satin delta는 rim light만 개선되고 satin sheet가 약해 실패했다. 이어 fibrous, chalk,
weathered 대표 3개를 각각 3-seed로 확인했으며 weathered만 큰 박리 패치와 firm edge로
통과했다. Fibrous는 재질이 너무 미세했고 chalk soft-bleed는 한 시드에서 추가 사람 형태의
그림자를 만들었다. 이 상태의 기대 하한은 non-minimal 56개와 weathered minimal 5개를
합친 61개라서 목표 60개에 대한 안전 여유가 부족하다.

v0.8.3은 이미 통과한 weathered minimal 5개를 보존하고 satin/fibrous/chalk 20개만 다시
작성한다. 세 재질은 sheet가 아니라 `entire backdrop`의 큰 satin fold, coarse fiber,
powdery chalk stroke로 지정하고, soft bleed는 사람 실루엣이 아닌 단 하나의 soft-edged
background halo로 제한한다. 비교 검사는 정확히 20개 본문만 변경되고 나머지 style 130개가
동일함을 확인한다. 최신 `remote-style-refill-calibration`은 이 세 재질 대표 3개 × 3-seed
delta를 실행하며, 통합 교정은 v0.8.1의 non-minimal 4개, v0.8.2 weathered 1개, 이 delta를
함께 사용한다. 아래 Make target은 v0.8.3 증거 경로를 사용한다.

v0.8.3 delta 9장은 모두 기술적으로 성공했다. Fibrous 대표군은 화면 전체의 거친 종이
섬유가, chalk 대표군은 분말감과 단일 배경 halo가 세 seed에서 반복되어 `testing`을
통과했다. 이전 초크 교정에서 보였던 사람 형태의 중복 그림자는 재발하지 않았다. Satin
대표군은 안정적인 단일 인물과 약한 의상 광택은 유지했지만, 넓고 거울처럼 밝은 배경
주름과 얼굴·손가락의 etched light가 충분히 드러나지 않아 `rejected`로 남겼다. 따라서
공식 refill의 보수적인 기대 통과 풀은 non-minimal 56개, weathered 5개, fibrous/chalk
10개를 합친 71개다.

이어 generated 81개 × seed 1001/2002/3003의 공식 refill 243장을 완료했다. 실행 기록,
PNG, scorecard가 각각 243개이고 81개 스타일의 세 seed가 정확히 대응한다. 모든 PNG는
1024 × 1024이며 실행 메타데이터 민감정보 0건, 종료 후 원격 큐 running/pending 0건을
확인했다. 9개 contact sheet 전수 판정은 28개 `testing`, 53개 `rejected`, critical
failure 0건이었다. 통과 28개에 seed 4004/5005의 56장을 추가해 각 항목을 정확히 다섯
seed로 집계했고, 27개가 `approved`, 한 개가 새 seed에서 halo를 유지하지 못해
`rejected`가 됐다. 기존 승인과 합친 현재 style pack 승인은 117개이며 150개 목표까지
33개가 남았다. 다음 v0.9 refill은 누적 탈락 54개만 실패 노트별로 다시 작성한다.

v0.9는 탈락 54개에만 적용되는 별도 retry profile을 추가했다. Shape, color, surface,
atmosphere, edge를 추상적인 미감 용어가 아니라 화면에서 확인 가능한 물체·재질·광원으로
다시 표현하고, 승인 96개는 본문과 5-seed 이력을 그대로 보호한다. Retry profile은
`generation.prompt_profile`에 기록해 상태가 `generated`나 `testing`으로 바뀐 뒤에도
재컴파일 결과가 되돌아가지 않도록 했다. 이 과정에서 초기 v0.9.1 preview가 상태 전환 후
기존 prompt로 복귀하는 비멱등성 결함을 발견했고, 해당 9장은 실패 진단 증거로만 보존했다.

수정된 v0.9.2 대표 교정에서는 geometric weathered 조합이 거대한 박리 잉크 면과 세로
분할을 안정적으로 재현했다. 남은 두 약점은 항목 단위 retry override로 좁혔다. Minimal
weathered는 프레임 대부분을 덮는 하나의 floor-to-ceiling torn ink mural로, rounded
glazed는 두꺼운 투명 유리 원반과 보이는 테두리·굴절로 명시했다. v0.9.3의 두 대표군 ×
3-seed 결과는 모두 1024 × 1024로 완료되었고, 각 seed에서 단일 인물과 요구한 재질·형태가
반복되어 두 군 모두 `testing` 판정을 받았다. Calibration seed는 승인에 재사용하지 않고,
공식 54개 screen과 그 후의 두 seed extension만 lifecycle 근거로 사용한다.
v0.9.4는 retry override와 조립 template 사이의 중복 마침표만 정규화한 최종 배포
artifact다. Prompt 의미는 v0.9.3과 동일하므로 calibration은 반복하지 않고, 공식 screen과
extension 증거 경로만 v0.9.4로 분리한다.

v0.9.4 공식 screen은 54개 × 3-seed의 162장을 모두 완료했다. Run, PNG, scorecard가
각각 162개이고 모든 이미지는 1024 × 1024, 민감 메타데이터 0건, 종료 큐 0/0이다. 여섯
contact sheet의 분할 전수 리뷰에서 22개가 `testing`, 32개가 `rejected`, critical failure는
0건이었다. Etched face rim이 불투명한 흰 얼굴 패치로 변한 사례와 재질·광원 축이 약한
minimal/rounded 조합은 통과시키지 않았다. 통과 22개에 seed 4004/5005의 44장을 추가해
정확히 5개 seed로 통합했으며, 21개는 `approved`, ornamental soft-bleed 한 개는 새 seed의
halo 불안정으로 `rejected`가 됐다. Style pack 승인은 138개이며 목표까지 12개가 남았다.

v0.10은 실패 원인이 명확한 20개만 다시 연다. 새 `retry_prompt_replacements`는 기존 retry
문장에 보정문을 덧붙이는 대신 항목별 완전 prompt를 제공하며, 승인된 138개 본문과 평가
이력은 생성기가 변경 불가로 보호한다. 대상은 얼굴의 흰 패치를 만든 etched 4개, 재질이
약했던 minimal fibrous 4개와 chalk 4개, 광원·edge가 약했던 satin 8개다. 대표 calibration은
이 네 실패군에서 한 개씩 골라 4개 × 3-seed로 실행한다. 정확히 20개 prompt만 바뀌고
승인 항목 변경은 0건이며, 최대 prompt 길이는 486자로 정적 검증을 통과했다.

첫 v0.10 calibration에서 fibrous paper와 chalk mural 대표는 세 seed 모두 통과했다.
Faceted etched는 얼굴의 흰 패치를 제거했지만 amber-blue 분할이 blue-gray로 수렴했고,
satin ceremonial은 재질은 강해졌으나 세 light box의 수가 흔들렸다. v0.10.1은 이 다섯
prompt만 다시 고쳐 crossed slab을 하나의 solid amber-orange와 하나의 solid cobalt-blue로,
ceremonial set을 검은 간격으로 분리된 세 개의 완전히 보이는 직사각 light-box panel로
고정한다. 나머지 15개 v0.10 prompt는 변경하지 않고 두 실패군 대표만 2개 × 3-seed로
재교정한다. v0.10.1의 여섯 결과는 모두 1024 × 1024로 완료됐고, 세 seed에서 두 색의
교차 slab과 정확히 세 개의 분리된 light-box가 반복되어 두 대표군 모두 `testing` 기준을
통과했다. 따라서 v0.10의 fibrous/chalk와 v0.10.1의 faceted/satin을 합친 네 실패군 전체가
공식 screen 진입 gate를 통과했다.

실행 순서는 다음 자동 게이트로 고정한다.

```bash
make deploy-preview-dry-run
make deploy-preview
make remote-style-refill-calibration  # v0.10.1 잔여 실패군 대표 2개 × seed 3개
# calibration contact sheet를 확인하고 통과한 경우에만 계속한다.
make remote-generated-screen          # v0.10 재작성 20개 × seed 3개
make review-style-screen
# 통과 항목을 testing으로 반영한 뒤:
make remote-testing-retest            # seed 4004, 5005
```

각 제출 전후 runner가 빈 큐를 확인하며 다른 사용자의 작업을 취소하거나 변경하지 않는다.
Calibration은 공식 refill과 별도 디렉터리에 보존하고, 3-seed 결과는 screening에만 사용한다.
승격은 공식 screen과 extension을 합친 5-seed 점수에서만 허용한다. 현재 승인 138개에서
v0.10 대상 중 최소 12개가 추가 승인되면 style pack 150개 목표를 충족한다.

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
