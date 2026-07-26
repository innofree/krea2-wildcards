# Runtime output

이 디렉터리는 `approved` 카탈로그 항목의 컴파일 결과만 저장합니다.

```bash
python3 scripts/build_runtime_yaml.py --output wildcards
```

초기 50개 후보는 아직 `generated` 상태이므로 preview 빌드는 다음과 같이 별도
경로에 생성합니다.

```bash
python3 scripts/build_runtime_yaml.py \
  --include-status generated \
  --output build/preview-wildcards
```
