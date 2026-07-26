# Evaluation reports

생성 이미지의 수동 또는 자동 평가 원본과 `summarize_results.py`의 요약 결과를
저장합니다. 모델 버전, seed, 최종 확장 prompt와 critical failure 여부를 함께
기록하세요. 서버 IP, SSH 계정, 계정 홈 경로와 API URL은 기록하지 않고 원격 대상은
`private_comfyui` 같은 비식별 이름만 사용합니다.

`static_audit_v0_5.json`은 3,750개 catalog 반영 직후의 exact 수량, global/family
중복 감사, preview path, schema-v2 shard, lint·conflict·보안 gate 결과를 기록합니다.
이미지 품질 승인을 뜻하지 않으며 신규 3,700개는 별도 3-seed/5-seed evidence가
생기기 전까지 `generated` 상태를 유지합니다.
