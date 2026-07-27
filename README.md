# Krea2 Wildcards

Krea2가 해석하기 쉬운 자연어 시각 표현을 ComfyUI Dynamic Prompts용
wildcard YAML로 컴파일하는 프로젝트입니다. 원본 조사 데이터와 실행 YAML을
분리하며, 이미지 검증을 통과한 `approved` 항목만 기본 런타임 빌드에 포함합니다.

현재 카탈로그는 계획 수량 3,750개를 모두 보유합니다. 기존 완성형 스타일 팩 50개와
source-grounded expansion blueprint에서 결정적으로 생성한 13개 분류 3,700개로
구성됩니다. 다단계 5-seed 검증을 거친 style pack 150개는 `approved`, 효과가 부족한
50개는 `rejected`, 나머지 3,550개는 이미지 검증 전 또는 진행 중인 `generated`입니다.
따라서 현재 preview는 3,700개를 제공하고 production build는 승인된 150개만 포함합니다.

## 빠른 시작

```bash
python3 -m pip install -e '.[dev]'

# generated 후보를 임시 디렉터리에 preview 컴파일
python3 scripts/build_runtime_yaml.py \
  --include-status generated \
  --include-status testing \
  --include-status approved \
  --output build/preview-wildcards

python3 scripts/lint_wildcards.py build/preview-wildcards
python3 scripts/check_duplicates.py catalog
python3 scripts/check_conflicts.py --catalog catalog/compatibility.yaml
python3 scripts/sync_catalog_v2.py
pytest
```

실제 배포용 빌드는 승인 항목만 포함합니다.

```bash
python3 scripts/build_runtime_yaml.py --output wildcards
```

현재는 승인된 150개 항목만 production runtime에 포함됩니다. 승인 항목이 전혀 없는
catalog에서는 위 명령이 빈 배포를 실수로 만드는 대신 실패합니다.

전체 로컬 릴리스 게이트와 승인 전용 artifact 증거는 한 명령으로 재현할 수 있습니다.

```bash
make release
```

## 데이터 흐름

```text
catalog/*.yaml
    <- generate_catalog_expansion.py <- catalog/blueprints/*.yaml
    -> sync_catalog_v2.py -> catalog_v2/
    -> normalize_catalog.py
    -> build_runtime_yaml.py
    -> wildcards/krea2/**/*.yaml
    -> lint_wildcards.py
    -> ComfyUI Dynamic Prompts
```

- `catalog/blueprints/`: 근거가 연결된 시각 어휘와 exact 수량 생성 규칙
- `catalog/`: 출처, 시각 특성, 호환성, 검증 상태를 포함하는 schema-v1 데이터
- `catalog_v2/`: prompt 본문을 복제하지 않는 shard·feature·route·lifecycle projection
- `wildcards/`: ComfyUI가 읽는 문자열 목록 전용 디렉터리
- `templates/`: 조합 순서와 benchmark 입력 템플릿
- `scripts/`: 정규화, 빌드, lint, 충돌 검사, matrix 생성 및 결과 요약
- `tests/`: baseline 설정, 자동 테스트, 생성 결과 보고서

자세한 목표와 단계는 [plan.md](plan.md)를 참고하세요.

## 원격 ComfyUI

benchmark 대상은 비공개 ComfyUI이며, Impact Pack의 wildcard 저장소로 preview
YAML을 배포합니다. 서버 주소, SSH 계정, 계정 홈 경로는 저장소에 기록하지 않고
`KREA2_COMFY_API_URL`, `KREA2_COMFY_SSH_TARGET`,
`KREA2_COMFY_REMOTE_WILDCARD_DIR` 환경변수로만 주입합니다. `.env.example`을
로컬 `.env`로 복사해 실제 값을 채우되 `.env`는 커밋하지 않습니다.

기본 배포 명령은 dry-run이고, `--apply` 또는 `make deploy-preview`를 명시해야
원격 파일을 변경합니다.

```bash
make deploy-preview-dry-run
make deploy-preview
```

Impact adapter는 canonical runtime 디렉터리의 모든 YAML을 단일 호환 bundle로
평탄화합니다. 따라서 확장 분류도 기존 파일과 같은 reload·checksum·정확 namespace
검증 절차를 거칩니다.

연결 확인 결과, 배포 경로, reload 방식 및 다음 benchmark 단계는
[원격 ComfyUI 운영 기록](docs/remote-comfyui.md)에 정리되어 있습니다.

검증은 대표 후보에 seed 3개 이상을 쓰는 pilot과 seed 5개 이상을 쓰는 승인
판정으로 나눕니다. 3-seed 결과만으로는 자동 요약 도구도 `approved`를 추천하지
않습니다. 현재 승인된 style pack 150개는 family-compatible scene에서 5-seed 검증을
완료했습니다. 별도의 canonical artist 300명 native 관찰도 3-seed 900장으로 완료했으며,
172명은 안정적 관찰, 128명은 불안정 관찰로 분리했습니다. name-free artist signature는
3-seed 선별과 추가 2-seed 승인 절차를 진행한 뒤에만 production에 포함됩니다.
