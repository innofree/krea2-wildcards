# Runtime output

`wildcards/`는 `approved` 카탈로그 항목의 컴파일 결과만 저장한다.

```bash
python3 scripts/build_runtime_yaml.py --output wildcards
```

`build_runtime_yaml.py`는 staging 디렉터리를 만든 뒤 `os.replace`로 출력 경로를
원자 교체한다. 따라서 `wildcards/` 안에 생성물이 아닌 파일을 두면 다음 production
빌드에서 사라진다. 런타임 디렉터리 관련 문서는 이 파일에서 관리한다.

미승인 항목을 포함한 preview 빌드는 별도 경로에 생성한다.

```bash
python3 scripts/build_runtime_yaml.py \
  --include-status generated \
  --include-status testing \
  --include-status approved \
  --output build/preview-wildcards
```

Impact 호환 단일 파일은 컴파일된 런타임을 입력으로 받는다.

```bash
python3 scripts/build_impact_yaml.py \
  --source wildcards \
  --output build/impact-production/krea2_complete_pack.yaml
```
