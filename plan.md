# Krea2 대규모 Wildcard Prompt Library 구축 계획서

## 1. 문서 개요

### 1.1 목적

NovelAI, Anima 및 Danbooru 계열 모델에서 사용되는 다음 프롬프트 요소를 조사·분류하고, 이를 **Krea2가 이해하기 쉬운 자연어 기반 시각 표현으로 변환하여 대규모 ComfyUI wildcard YAML 라이브러리로 구축**한다.

* 작가 및 작화 스타일
* 캐릭터 디자인
* 얼굴과 눈 디자인
* 선화와 채색
* 렌더링 방식
* 의상과 패션
* 포즈와 신체 표현
* 카메라 구도와 앵글
* 조명과 색감
* 배경과 공간 디자인
* 시대, 장르, 매체 표현
* 분위기와 연출 효과

최종 목표는 단순한 태그 모음이 아니라, 다음 조건을 만족하는 **재사용 가능한 프롬프트 생성 시스템**을 만드는 것이다.

1. Krea2 Turbo 및 Krea2 계열 모델에서 안정적으로 동작
2. ComfyUI Dynamic Prompts에서 직접 호출 가능
3. 수천 개 항목을 구조적으로 관리 가능
4. 충돌하는 조합을 최소화
5. 작가 스타일을 단순 이름이 아닌 시각적 특성으로 표현
6. 신규 작가·디자인·스타일을 지속적으로 추가 가능
7. 생성 결과를 기반으로 항목을 평가하고 승격·제외 가능

---

## 2. 리서치 기반 핵심 결론

### 2.1 NovelAI 프롬프트 특성

NovelAI Diffusion은 학습 시 사용된 태그를 직접 인식하도록 설계되어 있으며, 알려진 태그를 사용하면 캐릭터와 이미지 특성을 비교적 일관되게 제어할 수 있다. 공식 권장 태그 순서는 대략 `인원 → 캐릭터 → 작품명 → 기타 속성` 구조이며, 영향력이 큰 작화 스타일 태그는 프롬프트 앞부분에 배치하는 것이 권장된다.

NovelAI 스타일 프롬프트는 다음 계층으로 분석할 수 있다.

```text
Medium
└─ 사용 매체와 제작 기법

Art Style
└─ 전체적인 작화 문법

Coloring
└─ 채색, 명암, 팔레트

Special Effects
└─ 후처리, 질감, 분위기 효과
```

NovelAI의 `{}`와 `[]`는 각각 프롬프트 강조와 약화 용도로 사용된다. 그러나 ComfyUI Dynamic Prompts에서는 `{a|b|c}`가 선택 문법으로 사용되므로, NovelAI의 강조 문법을 그대로 wildcard 템플릿에 복사해서는 안 된다.

### 2.2 Anima 프롬프트 특성

Anima는 Danbooru 스타일 태그, 자연어 캡션, 태그와 자연어의 혼합 입력으로 학습되었다. 작가 태그는 `@artist_name` 형식으로 표현하며, 품질 태그와 작가 태그를 자연어 프롬프트 앞부분에 배치할 수 있다. 자연어만 사용할 때는 최소 두 문장 이상의 구체적인 설명이 권장된다.

Anima는 태그 드롭아웃 방식으로 학습되어 모든 속성을 빠짐없이 작성할 필요는 없으며, 짧고 불명확한 프롬프트보다 핵심 작화 요소가 명시된 상세 프롬프트가 안정적이다.

Anima의 작가 태그는 **조사 및 작화 특성 추출을 위한 원본 데이터**로 활용한다. Krea2 실행 프롬프트에는 다음과 같이 변환한다.

```text
Anima 원본

@artist_name, masterpiece, 1girl, long hair,
soft shading, detailed eyes, colorful background
```

```text
Krea2 변환

An elegant anime illustration with crisp tapered linework,
large glass-like eyes with layered iris highlights,
softly blended skin shading, restrained facial features,
flowing hair strands, and a luminous pastel background.
```

### 2.3 Krea2 프롬프트 특성

Krea2는 스타일, 구도, 미감 및 참조 이미지 기반 제어를 핵심 목표로 설계된 모델이다. 공식 문서는 프롬프트에서 피사체, 배경, 분위기, 스타일 방향을 설명하고 필요하면 스타일 참조 이미지나 무드보드를 함께 사용하는 방식을 권장한다.

Krea2는 NovelAI나 Anima처럼 특정 Danbooru 태그 사전을 공식 프롬프트 문법으로 제시하지 않는다. 따라서 다음과 같은 방식은 피한다.

```text
@artist_a, @artist_b, newest, score_9, 1girl,
looking at viewer, absurdres
```

대신 각 태그가 의미하는 시각적 결과를 자연어로 전개한다.

```text
A polished contemporary anime key visual with thin controlled linework,
highly detailed eyes, compact facial proportions, subtle cel shading,
clean color separation, vivid accent colors, and an airy cinematic composition.
```

Krea2 Turbo는 빠른 스타일 및 프롬프트 탐색에 사용하고, 사용 가능한 경우 Medium 또는 Large에서 최종 스타일을 재검증하는 구조를 권장한다. Krea 공식 문서도 Turbo를 빠른 탐색용으로, Medium과 Large를 일반 작업 및 고품질 결과용으로 구분한다.

### 2.4 ComfyUI Wildcard 특성

ComfyUI Dynamic Prompts는 `.txt`, `.json`, `.yaml` wildcard 파일을 지원한다. 기본 wildcard 호출 형식은 다음과 같다.

```text
__krea2/style/linework__
```

YAML에서는 중첩된 키 구조를 wildcard 경로로 사용할 수 있다.

```yaml
krea2:
  style:
    linework:
      clean_anime:
        - "clean and precise anime linework"
```

호출 예시:

```text
__krea2/style/linework/clean_anime__
```

---

## 3. 핵심 설계 원칙

### 3.1 태그 이식이 아닌 시각 속성 변환

NovelAI와 Anima에서 검증된 태그를 Krea2에 그대로 넣지 않는다.

다음 변환 단계를 적용한다.

```text
원본 태그
→ 태그 의미 조사
→ 이미지에서 나타나는 시각적 특징 분해
→ 모델 독립적인 시각 속성 정의
→ Krea2 자연어 프롬프트로 재작성
→ 생성 테스트
→ 평가 후 wildcard 등록
```

예시:

```text
원본 개념
shoujo manga style
```

```text
분해된 시각 특성
- 가늘고 유려한 선
- 큰 눈과 긴 속눈썹
- 작은 코와 섬세한 턱선
- 꽃잎과 반짝임 장식
- 밝은 파스텔 팔레트
- 감정 중심의 클로즈업 구도
```

```text
Krea2 wildcard 값
delicate shoujo-inspired illustration with graceful tapered linework,
large expressive eyes framed by long eyelashes,
refined facial proportions, luminous pastel coloring,
floating petals, soft sparkles, and an emotionally intimate composition
```

### 3.2 실행 YAML과 메타데이터 분리

ComfyUI가 직접 읽는 runtime YAML에는 문자열 목록만 저장한다.

작가 출처, 평가 점수, 호환성, 테스트 모델 등의 메타데이터는 별도 catalog 파일에 저장한다.

```text
catalog/
└─ 조사·분석·평가 데이터

wildcards/
└─ ComfyUI가 직접 사용하는 실행 데이터
```

이를 분리하지 않으면 ComfyUI가 메타데이터 필드를 wildcard 항목으로 인식하거나, YAML 구조가 불필요하게 복잡해질 수 있다.

### 3.3 단일 속성과 완성형 스타일 팩 병행

두 종류의 wildcard를 동시에 제공한다.

#### Atomic wildcard

하나의 시각적 속성만 표현한다.

```text
thin tapered linework
soft cel shading
muted pastel palette
large reflective irises
```

#### Style pack

서로 호환되는 여러 속성을 하나의 완성형 문자열로 제공한다.

```text
delicate tapered anime linework, compact facial proportions,
large reflective eyes, soft two-step cel shading,
a restrained pastel palette, and airy decorative highlights
```

대규모 무작위 생성에서는 atomic wildcard만 조합하면 충돌 가능성이 높다. 기본 생성에서는 style pack을 사용하고, 세부 실험에서 atomic wildcard를 추가하는 구조가 안정적이다.

### 3.4 긍정형 프롬프트 중심

Krea2 환경에서 네거티브 프롬프트에 의존하지 않도록 설계한다.

잘못된 방식:

```text
no harsh shadows, no thick outlines, no photorealism
```

권장 방식:

```text
soft diffused shadows, delicate narrow outlines,
clearly illustrated anime rendering
```

충돌 방지는 네거티브 프롬프트가 아니라 다음 방식으로 처리한다.

* 상호 배타적인 wildcard 그룹 분리
* 호환성 매트릭스 적용
* 프리셋 단위 조합
* 생성 전 텍스트 검증
* 중복 속성 제거

---

## 4. 목표 산출물

### 4.1 디렉터리 구조

```text
krea2-wildcards/
├── README.md
├── PLAN.md
├── CHANGELOG.md
├── LICENSE-NOTES.md
│
├── catalog/
│   ├── sources.yaml
│   ├── artists.yaml
│   ├── art_styles.yaml
│   ├── character_designs.yaml
│   ├── compatibility.yaml
│   ├── aliases.yaml
│   └── evaluation.yaml
│
├── wildcards/
│   └── krea2/
│       ├── core/
│       │   ├── quality.yaml
│       │   ├── image_type.yaml
│       │   └── detail_level.yaml
│       │
│       ├── style/
│       │   ├── complete_pack.yaml
│       │   ├── medium.yaml
│       │   ├── genre.yaml
│       │   ├── era.yaml
│       │   ├── linework.yaml
│       │   ├── coloring.yaml
│       │   ├── shading.yaml
│       │   ├── rendering.yaml
│       │   ├── texture.yaml
│       │   └── effects.yaml
│       │
│       ├── artist_signature/
│       │   ├── classic.yaml
│       │   ├── modern.yaml
│       │   ├── manga.yaml
│       │   ├── game_illustration.yaml
│       │   └── experimental.yaml
│       │
│       ├── character/
│       │   ├── archetype.yaml
│       │   ├── design_language.yaml
│       │   ├── face.yaml
│       │   ├── eyes.yaml
│       │   ├── hair.yaml
│       │   ├── body_proportion.yaml
│       │   ├── expression.yaml
│       │   └── gesture.yaml
│       │
│       ├── fashion/
│       │   ├── complete_outfit.yaml
│       │   ├── tops.yaml
│       │   ├── bottoms.yaml
│       │   ├── dresses.yaml
│       │   ├── outerwear.yaml
│       │   ├── footwear.yaml
│       │   ├── accessories.yaml
│       │   └── fabric.yaml
│       │
│       ├── pose/
│       │   ├── standing.yaml
│       │   ├── sitting.yaml
│       │   ├── reclining.yaml
│       │   ├── action.yaml
│       │   ├── fashion.yaml
│       │   └── portrait.yaml
│       │
│       ├── camera/
│       │   ├── framing.yaml
│       │   ├── angle.yaml
│       │   ├── lens_language.yaml
│       │   ├── perspective.yaml
│       │   ├── composition.yaml
│       │   └── subject_placement.yaml
│       │
│       ├── lighting/
│       │   ├── source.yaml
│       │   ├── direction.yaml
│       │   ├── softness.yaml
│       │   ├── contrast.yaml
│       │   ├── color.yaml
│       │   └── atmosphere.yaml
│       │
│       ├── environment/
│       │   ├── indoor.yaml
│       │   ├── outdoor.yaml
│       │   ├── fantasy.yaml
│       │   ├── science_fiction.yaml
│       │   ├── urban.yaml
│       │   ├── nature.yaml
│       │   └── simple_background.yaml
│       │
│       └── preset/
│           ├── anime_portrait.yaml
│           ├── fashion_editorial.yaml
│           ├── game_key_visual.yaml
│           ├── manga_cover.yaml
│           ├── cinematic_scene.yaml
│           └── character_sheet.yaml
│
├── templates/
│   ├── anime_portrait.txt
│   ├── full_body_character.txt
│   ├── fashion_editorial.txt
│   ├── game_key_visual.txt
│   ├── manga_cover.txt
│   └── style_benchmark.txt
│
├── scripts/
│   ├── normalize_catalog.py
│   ├── build_runtime_yaml.py
│   ├── lint_wildcards.py
│   ├── check_duplicates.py
│   ├── check_conflicts.py
│   ├── export_prompt_matrix.py
│   └── summarize_results.py
│
└── tests/
    ├── syntax/
    ├── prompt_matrix/
    ├── expected/
    └── reports/
```

### 4.2 초기 규모 목표

| 분류           |      목표 항목 수 |
| ------------ | -----------: |
| 완성형 작화 스타일 팩 |          200 |
| 작가 시각 시그니처   |          300 |
| 매체 및 렌더링     |          150 |
| 선화·채색·명암     |          300 |
| 얼굴·눈·캐릭터 디자인 |          400 |
| 헤어스타일·헤어 디자인 |          250 |
| 의상·패션        |          500 |
| 포즈·제스처       |          350 |
| 카메라·구도       |          250 |
| 조명·색감        |          250 |
| 배경·환경        |          400 |
| 효과·분위기       |          200 |
| 완성형 프리셋      |          200 |
| **초기 총 목표**  | **약 3,750개** |

항목 수보다 다음 기준을 우선한다.

* 의미 중복 제거
* Krea2 반응성 검증
* 서로 다른 결과를 만드는 실효성
* 프롬프트 문장 품질
* 조합 안정성

---

## 5. 데이터 모델

### 5.1 조사용 작가 카탈로그

`catalog/artists.yaml`은 ComfyUI가 직접 읽지 않는 조사용 데이터다.

```yaml
artists:
  artist_internal_id:
    display_name: "Artist Name"
    aliases:
      - "artist_alias"
    source_tags:
      novelai:
        - "artist name"
      anima:
        - "@artist name"
      danbooru:
        - "artist_name"

    source_status:
      novelai_known: true
      anima_known: true
      manually_verified: false

    visual_signature:
      linework:
        - "thin tapered contour lines"
        - "controlled interior detail lines"

      face_design:
        - "compact oval face"
        - "small understated nose"
        - "softly pointed chin"

      eye_design:
        - "large layered irises"
        - "bright lower iris gradient"
        - "multiple geometric catchlights"

      coloring:
        - "clean local colors"
        - "restrained pastel accents"

      shading:
        - "soft two-step cel shading"
        - "minimal facial shadow"

      composition:
        - "character-centered key visual"
        - "decorative negative space"

      recurring_motifs:
        - "floating petals"
        - "fine sparkle particles"

    krea2_prompts:
      signature: >-
        delicate anime illustration with thin tapered contour lines,
        compact refined facial proportions, large layered irises with
        geometric catchlights, clean local colors, soft two-step cel shading,
        restrained pastel accents, and decorative negative space

      portrait: >-
        intimate anime portrait with precise tapered linework,
        a compact oval face, luminous layered eyes, minimal facial shadows,
        soft pastel color accents, and subtle floating particles

    compatibility:
      recommended:
        - "pastel_coloring"
        - "soft_cel_shading"
        - "character_key_visual"

      avoid:
        - "heavy_impasto"
        - "coarse_charcoal"
        - "hard_photorealism"

    validation:
      model: "krea2_turbo"
      tested_seeds: 0
      style_fidelity: null
      prompt_adherence: null
      anatomy_quality: null
      consistency: null
      status: "research"
```

### 5.2 실행용 wildcard YAML

실행 YAML에는 메타데이터를 넣지 않는다.

```yaml
krea2:
  artist_signature:
    refined_pastel_anime:
      - >-
        delicate anime illustration with thin tapered contour lines,
        compact refined facial proportions, large layered irises with
        geometric catchlights, clean local colors, soft two-step cel shading,
        restrained pastel accents, and decorative negative space

      - >-
        polished character illustration with graceful narrow linework,
        luminous expressive eyes, understated facial features,
        softly separated cel shadows, gentle pastel hues,
        and an airy ornamental composition
```

호출:

```text
__krea2/artist_signature/refined_pastel_anime__
```

---

## 6. 프롬프트 분류 체계

### 6.1 작화 스타일

```text
style
├─ medium
├─ drawing tradition
├─ animation style
├─ manga style
├─ game illustration
├─ editorial illustration
├─ concept art
├─ painting
├─ vector art
├─ graphic design
└─ mixed media
```

예시:

```yaml
krea2:
  style:
    medium:
      anime_digital_illustration:
        - "polished digital anime illustration"
        - "high-end digitally painted anime artwork"

      traditional_watercolor:
        - >-
          delicate traditional watercolor illustration with translucent
          pigment layers, visible paper grain, softened edges,
          and naturally pooled color

      ink_and_wash:
        - >-
          expressive ink-and-wash illustration with fluid black contours,
          pale diluted tones, organic brush variation, and open negative space
```

### 6.2 선화

분류 축:

* 굵기
* 선의 압력 변화
* 외곽선과 내부선 차이
* 곡선 또는 각진 형태
* 깨끗함 또는 거친 질감
* 선 밀도
* 펜·붓·연필 특성

```yaml
krea2:
  style:
    linework:
      thin_tapered:
        - >-
          thin tapered linework with subtle pressure variation,
          clean contours, and restrained interior details

      bold_graphic:
        - >-
          bold graphic outlines with strong contour hierarchy,
          simplified interior lines, and confident angular shapes

      rough_pencil:
        - >-
          loose visible pencil construction lines,
          textured graphite edges, and energetic hand-drawn marks
```

### 6.3 얼굴 및 눈 디자인

얼굴과 눈은 하나의 문자열에 모든 요소를 넣지 않고 다음과 같이 분리한다.

```text
face
├─ face shape
├─ jawline
├─ nose
├─ mouth
├─ cheek treatment
└─ facial rendering

eyes
├─ size
├─ shape
├─ iris construction
├─ pupil
├─ eyelashes
├─ catchlight
└─ emotional expression
```

```yaml
krea2:
  character:
    eyes:
      layered_glass_irises:
        - >-
          large glass-like eyes with layered iris gradients,
          crisp dark pupils, multiple controlled catchlights,
          and finely defined upper eyelashes

      narrow_mature_eyes:
        - >-
          narrow mature eyes with restrained highlights,
          sharp upper eyelids, subtle lower lashes,
          and a composed confident gaze
```

### 6.4 채색과 명암

채색은 다음 축으로 분리한다.

* 셀 채색
* 소프트 셀 채색
* 에어브러시 채색
* 페인터리 채색
* 수채화
* 플랫 컬러
* 그라데이션 중심
* 고채도 또는 저채도
* 색조 분리
* 피부 명암
* 머리카락 명암
* 림라이트

```yaml
krea2:
  style:
    shading:
      soft_cel:
        - >-
          soft two-step cel shading with gently feathered transitions,
          clean shadow shapes, and restrained facial contrast

      hard_cel:
        - >-
          crisp hard-edged cel shading with clearly separated light
          and shadow planes, graphic contrast, and minimal gradients

      painterly:
        - >-
          painterly blended shading with visible brush modulation,
          rich color transitions, and softly modeled volume
```

### 6.5 캐릭터 디자인 언어

```text
character design
├─ cute and compact
├─ refined and elegant
├─ mature and angular
├─ heroic
├─ fantasy ornate
├─ futuristic
├─ gothic
├─ street fashion
├─ idol
├─ visual novel
├─ mobile game
└─ animation key visual
```

캐릭터 디자인은 단순히 `cute`, `beautiful` 같은 평가어가 아니라 형태적 특징을 포함해야 한다.

잘못된 항목:

```text
beautiful anime girl
```

권장 항목:

```text
a refined anime character design with an elongated silhouette,
compact facial features, narrow shoulders, a defined waist,
elegant limb proportions, and carefully controlled costume details
```

---

## 7. 작가 스타일 변환 정책

### 7.1 세 가지 작가 스타일 모드

#### Mode A: Native artist name

작가 이름을 그대로 사용한다.

```text
artwork influenced by Artist Name
```

용도:

* Krea2가 해당 이름에 반응하는지 탐색
* 기존 사용자 프롬프트와 호환
* A/B 테스트

리스크:

* 모델이 이름을 모를 수 있음
* 이름만으로 결과를 안정적으로 재현하기 어려움
* 서로 다른 작가 이름을 혼합하면 결과가 평균화될 수 있음
* 모델 버전에 따라 반응이 달라질 수 있음

#### Mode B: Visual signature

작가 이름 없이 시각적 특징만 사용한다.

```text
thin tapered lines, compact facial proportions,
large layered irises, restrained cel shading,
pale pastel colors, and decorative floral framing
```

용도:

* 기본 운영 모드
* 재현성 높은 wildcard
* 모델 독립적인 프롬프트
* 스타일 조합 및 분석

#### Mode C: Hybrid

이름과 시각적 특징을 함께 사용한다.

```text
artwork influenced by Artist Name, expressed through
thin tapered linework, compact facial proportions,
large layered irises, restrained cel shading,
and decorative floral framing
```

용도:

* 이름만 사용했을 때 반응이 약한 경우
* 시각적 특징과 작가 이름의 결합 효과 평가
* 실험용 프리셋

### 7.2 기본 권장안

```text
Production wildcard
→ Visual signature

Experimental wildcard
→ Native artist name

Compatibility test
→ Hybrid
```

작가 이름만으로 구성된 wildcard를 대량 생성하기보다, 한 작가를 최소 다음 8개 축으로 분석한다.

| 축  | 분석 항목              |
| -- | ------------------ |
| 선화 | 굵기, 압력, 외곽선, 내부선   |
| 얼굴 | 형태, 턱, 코, 입        |
| 눈  | 크기, 홍채, 속눈썹, 하이라이트 |
| 신체 | 비율, 실루엣, 손발 표현     |
| 채색 | 팔레트, 채도, 색 분리      |
| 명암 | 셀, 소프트 셀, 페인터리     |
| 구도 | 중심 배치, 여백, 시선 유도   |
| 장식 | 입자, 꽃, 패턴, 배경 모티프  |

---

## 8. 프롬프트 조립 구조

### 8.1 권장 순서

Krea2 프롬프트는 다음 순서로 조립한다.

```text
1. 이미지 유형과 작화 방향
2. 주 피사체
3. 캐릭터 디자인
4. 의상
5. 포즈와 행동
6. 카메라와 구도
7. 배경
8. 조명
9. 색상과 렌더링
10. 분위기와 마감
```

### 8.2 기본 템플릿

```text
__krea2/style/complete_pack__,
an adult woman with __krea2/character/design_language__
and __krea2/character/face__,
wearing __krea2/fashion/complete_outfit__.
She is __krea2/pose/fashion__,
shown in __krea2/camera/framing__
from __krea2/camera/angle__.
The scene takes place in __krea2/environment/indoor__,
illuminated by __krea2/lighting/source__
with __krea2/lighting/softness__.
The image uses __krea2/style/coloring__,
__krea2/style/shading__,
and __krea2/style/effects__.
```

### 8.3 작화 중심 템플릿

```text
__krea2/artist_signature/modern__,
__krea2/style/linework__,
__krea2/style/coloring__,
__krea2/style/shading__.
An adult female character with __krea2/character/eyes__
and __krea2/character/hair__ is
__krea2/pose/portrait__.
The composition uses __krea2/camera/composition__,
__krea2/lighting/atmosphere__,
and __krea2/environment/simple_background__.
```

### 8.4 프리셋 우선 템플릿

대량 랜덤 생성에서는 다음 구조를 기본으로 사용한다.

```text
__krea2/preset/anime_portrait__,
__krea2/character/expression__,
__krea2/camera/framing__,
__krea2/lighting/atmosphere__
```

프리셋에는 이미 호환성이 검증된 작화, 선화, 채색, 구도가 포함된다. 이 구조가 완전한 무작위 atomic 조합보다 실패율이 낮다.

---

## 9. 구축 단계

## Phase 0. 기준 워크플로우 고정

### 작업

* Krea2 체크포인트 버전 고정
* CLIP 또는 텍스트 인코더 버전 고정
* VAE 고정
* sampler 및 scheduler 고정
* steps 고정
* CFG 또는 guidance 고정
* 해상도 및 비율 고정
* LoRA 미적용 baseline 생성
* wildcard 엔진 버전 기록
* 생성된 최종 프롬프트를 PNG metadata 또는 별도 로그에 저장

### 산출물

```text
tests/baseline/workflow.json
tests/baseline/settings.yaml
tests/baseline/reference_prompts.txt
```

### 종료 기준

동일 seed와 동일 프롬프트에서 재현 가능한 baseline 결과가 생성되어야 한다.

### 원격 생성 용량 및 큐 운영

원격 생성 노드는 NVIDIA RTX PRO 6000과 96 GB VRAM을 갖춘 전용
ComfyUI 환경을 기준으로 한다. 이 용량은 calibration 이후의 다중 seed screen,
retest, pairwise, preset 및 random benchmark를 batch 또는 대량 queue로 처리할 수
있는 운영 자원으로 간주한다.

* batch 크기와 동시 queue 깊이는 명시적인 실행 인자로 관리하고 report manifest에 기록한다.
  Prompt matrix는 seed별 증거를 1:1로 유지하기 위해 `batch_size=1`, 기본
  `queue_depth=32`를 사용하고, 처리량은 서로 다른 job의 동시 queue로 확보한다.
* 새 batch를 시작하기 전에 원격 큐에 기존 외부 작업이 없는지 확인한다.
* 실행 도중 생성된 이 계획의 job만 추적하며, 기존 작업을 취소·재정렬·삭제하지 않는다.
* 대량 queue에서도 각 test ID, seed, resolved prompt hash, workflow hash, 이미지 hash 및
  실행 결과를 개별 `run.json`으로 보존한다.
* 중단 후 재개 시 이미 검증된 run은 건너뛰고 누락되거나 불일치한 run만 실패로 처리한다.
* GPU 용량은 seed 수 또는 승인 기준을 줄이는 근거로 사용하지 않는다. screen은 최소
  3개 seed, `approved` 승격은 서로 다른 5개 seed를 그대로 요구한다.
* wildcard 배포 후에는 ComfyUI 전체 재시작 대신 ImpactWildcardProcessor reload를 사용한다.

---

## Phase 1. 원본 태그 및 스타일 데이터 수집

### 수집 대상

1. NovelAI 공식 태그 문서
2. NovelAI 작화 스타일 가이드
3. Anima 모델 카드
4. Anima 작가 태그 자료
5. Danbooru 태그 분류
6. 애니메이션 제작 용어
7. 만화 및 일러스트 제작 용어
8. 게임 캐릭터 디자인 용어
9. 패션 및 촬영 용어
10. 기존 내부 프롬프트와 wildcard

### 수집 데이터 형식

```yaml
source_item:
  source: "anima"
  raw_tag: "@artist_name"
  category: "artist"
  aliases: []
  description: ""
  evidence: []
  notes: ""
  status: "collected"
```

### 주의 사항

* 태그 이름과 시각적 의미를 분리한다.
* 동일 작가의 alias를 하나의 canonical ID로 통합한다.
* 작품명, 캐릭터명, 작가명을 별도 분류한다.
* 작가 태그와 일반 작화 태그를 혼합 저장하지 않는다.
* 출처가 불분명한 커뮤니티 설명은 검증 대기 상태로 저장한다.

---

## Phase 2. 시각 특성 정규화

### 작업

각 태그를 다음 표준 속성으로 분해한다.

```yaml
normalized_signature:
  medium: []
  linework: []
  face_design: []
  eye_design: []
  body_design: []
  coloring: []
  shading: []
  texture: []
  composition: []
  lighting: []
  effects: []
  atmosphere: []
```

### 정규화 규칙

* 태그를 평가어가 아닌 관찰 가능한 형태로 변환
* `beautiful`, `amazing`, `best` 같은 추상 품질어 최소화
* 동일 의미의 표현을 canonical phrase로 통합
* 한 문장에 상충하는 속성을 넣지 않음
* 인물 속성과 전체 이미지 속성을 분리
* 작가 시그니처는 최소 5개 이상의 시각적 축으로 정의
* 실사, 반실사, 2D 일러스트를 명확히 구분
* 카메라 속성과 포즈 속성을 분리

### 예시

```text
원본
detailed eyes
```

```text
정규화 후보
large irises with layered radial detail,
dark defined pupils, a soft lower-iris gradient,
and multiple controlled catchlights
```

---

## Phase 3. Krea2 자연어 변환

### 변환 규칙

1. 완전한 영어 구 또는 문장으로 작성
2. 한 항목은 하나의 주요 목적을 가짐
3. 주어가 필요한 긴 프롬프트는 자연스러운 문장 사용
4. 단순 속성은 명사구 사용
5. 반복 품질어 제거
6. Danbooru 내부 표기 제거
7. underscore 제거
8. Anima의 `@` 접두사 제거
9. NovelAI의 `{}`, `[]`, `::` 강조 구문 제거
10. wildcard 선택 문법과 충돌하는 중괄호 사용 금지
11. Krea2에서 해석하기 어려운 점수 태그 제거
12. 긍정형 시각 표현 사용

### 변환 예시

```text
원본
year 2024, newest, score_9, @artist,
1girl, detailed eyes, soft shading
```

```text
Krea2
a contemporary high-end anime illustration with refined modern character design,
precisely layered expressive eyes, clean controlled linework,
and softly separated cel shading
```

---

## Phase 4. Runtime YAML 컴파일

### 컴파일 정책

`catalog/*.yaml`에서 승인된 항목만 `wildcards/krea2/*.yaml`로 출력한다.

```text
research
→ normalized
→ generated
→ tested
→ approved
→ deprecated
```

`approved` 상태만 runtime wildcard에 포함한다.

### 컴파일러 기능

`build_runtime_yaml.py`에서 다음을 처리한다.

* canonical key 생성
* 중복 문장 제거
* YAML escaping
* multiline scalar 변환
* 빈 값 제거
* 금지 문법 검사
* wildcard 경로 생성
* 정렬
* 출력 파일 분할
* manifest 생성

---

## Phase 5. 정적 검증

### YAML 검증

```bash
python - <<'PY'
from pathlib import Path
import yaml

root = Path("wildcards")

for path in root.rglob("*.yaml"):
    with path.open("r", encoding="utf-8") as f:
        yaml.safe_load(f)

    print(f"OK: {path}")
PY
```

### 필수 검사 항목

* YAML syntax 오류
* 빈 리스트
* 중복 키
* 중복 문자열
* 탭 문자
* 잘못된 들여쓰기
* 비정상 Unicode
* 남아 있는 `@artist`
* 남아 있는 Danbooru underscore
* NovelAI 강조 괄호
* Dynamic Prompt 중괄호 충돌
* 지나치게 긴 문자열
* 상충 속성
* 미성년 연상 표현과 성인 패션 표현의 혼합
* 작품명과 일반 스타일명의 혼합
* 실사와 애니메이션 작화의 비의도적 혼합

### 충돌 규칙 예시

```yaml
conflicts:
  hard_photorealism:
    - flat_anime_cel
    - monochrome_manga_screen_tone

  rough_charcoal:
    - clean_vector_linework
    - glossy_mobile_game_rendering

  chibi_proportions:
    - elongated_fashion_proportions

  simple_white_background:
    - densely_detailed_fantasy_city
```

---

## Phase 6. 생성 검증

### 6.0 Prompt profile calibration gate

전체 Phase 6 대량 실행 전에 실제 single-axis, pairwise, preset, random utility,
Turbo benchmark 생성 경로를 모두 포함하는 23 case × 3 seed, 총 69장 calibration을
수행한다. 모든 case가 품질 gate를 통과하고 현재 prompt-profile SHA-256이 matrix,
scored review, summary에 동일하게 기록되어야 이후 대량 target을 실행할 수 있다.

초기 `phase6_positive_profile_v2` calibration은 69/69개 1024×1024 PNG와
서로 다른 image hash를 생성했고, 동일 명령 재실행에서 `complete=69`,
`pending=0`을 확인했다. matrix SHA-256은
`b6c694463fa46132307e191540e4c828ed8f08016bdcfddbedd94764891669a8`이다.
23개 case 전수 contact-sheet 리뷰 결과는 통과 8개, 미달 15개였고, pairwise
coloring 한 case에서 exactly-one 지시를 어긴 2-person diptych가 발생했다.
주요 미달 원인은 camera face crop과 negative-space 미반영, character design
세부 누락, 조명 silhouette로 인한 얼굴 판독성 저하, preset framing drift,
random utility의 visual-signature·pose·textile 속성 누락이었다. 실패 summary는
`status=failed`, `complete=false`이며 calibration gate가 후속 대량 제출을
의도대로 차단했다. 이 점수와 이미지는 수정하지 않고 v2 실패 근거로 보존한다.
후속 profile은 정확히 한 인물과 얼굴·눈·양손 판독성, 명시적 camera framing,
단일-view 구성, 핵심 축의 구체적 가시 위치를 긍정형 자연어로 강화한 새 버전으로
고정하고, 기존과 겹치지 않는 새 3-seed 69장 calibration을 다시 통과해야 한다.

### 6.1 단일 축 테스트

한 번에 하나의 속성만 변경한다.

```text
고정:
- subject
- seed
- pose
- camera
- background
- lighting

변경:
- linework wildcard
```

다음 테스트에서는 채색만 변경한다.

```text
변경:
- coloring wildcard
```

이를 통해 어떤 wildcard가 실제 결과 차이를 만드는지 확인한다.

Pairwise의 오른쪽 축으로 사용될 character design, pose, lighting, background,
linework/coloring, camera catalog에서 각각 16개 실제 항목을 선택해 총 96 case를
서로 다른 3개 seed로 먼저 검증한다. Pairwise matrix의 `right_item`은 이
single-axis report에서 통과한 ID 집합의 부분집합이어야 한다.

### 6.2 작가 스타일 A/B/C 테스트

동일한 seed와 구도에서 다음 세 가지를 비교한다.

```text
A: 작가 이름만 사용
B: 시각 시그니처만 사용
C: 작가 이름과 시각 시그니처 혼합
```

평가 결과는 다음과 같이 기록한다.

```yaml
evaluation:
  artist_internal_id:
    native_name:
      fidelity: 2
      stability: 2

    visual_signature:
      fidelity: 4
      stability: 5

    hybrid:
      fidelity: 4
      stability: 3

    recommended_mode: "visual_signature"
```

실제 A/B/C 비교는 서로 다른 내부 작가 8개에 `native_name`,
`visual_signature`, `hybrid` 세 모드와 seed `[1001, 2002, 3003]`를
교차해 72개 job으로 수행했다. `batch_size=1`, `queue_depth=32`로 생성한
72개 결과는 모두 1024×1024 PNG와 고유 image hash를 가졌고, 동일 명령
재실행에서 `complete=72`, `pending=0`이었다. matrix SHA-256은
`502894078f3399c633aa81eb6e84fab24dfcd95d2afebe8e6bdb311cf5ab20f9`로
고정했다. 세 partition의 contact-sheet 리뷰를 중복·누락 검증 후 병합한 결과
critical failure 0, 8개 작가 모두 세 모드 coverage와 recommendation 기록을
완료해 `artist_abc_coverage` gate를 통과했다. 기계적 추천은
`visual_signature` 7개, `hybrid` 1개였으며, 육안 판정에서는 한 작가가 세 모드
모두 목표 identity를 충분히 재현하지 못했다. 따라서 이 gate는 모드 비교
coverage를 증명하며 개별 저충실도 모드를 별도 승인한 것으로 해석하지 않는다.

#### 6.2.1 시각 시그니처 screen 복구 및 5-seed gate

v0.8.2 시각 시그니처 full screen은 300개 × seed
`[1001, 2002, 3003]`, 총 900장을 완료했다. 실제 이미지 판정 결과는
`testing` 185개, `rejected` 115개, critical failure 0개였다. 최소
`testing >= 200` 적용 gate는 의도대로 catalog 변경 전에 실행을 거부했으며,
이 screen의 matrix, 개별 run, 이미지 hash, review, scorecard, binding과 summary는
후속 wrapper 결과로 덮어쓰지 않는 원본 근거로 보존한다.

최소 수량을 점수 완화나 임의 승격으로 맞추지 않는다. 다음 복구 절차를 적용한다.

1. v0.8.2 통과 185개는 `testing` 근거로 보존한다.
2. 미통과 115개만 최종 `rejected`로 확정하지 않고 `generated` 상태로 유예한다.
3. 유예된 115개에만 별도 v0.8.3 positive repair wrapper를 적용하고, 새 seed
   `[6101, 6202, 6303]`으로 345개 job을 실행한다.
4. v0.8.3에서도 통과하지 못한 항목은 `generated`로 유지한다. 원본 판정이나
   score를 수정해 통과로 간주하지 않는다.
5. 각 repair 반복의 실제 통과분은 `testing`으로 누적하고 실패분은 `generated`로
   유지한다. 누적 적용은 최소 수량과 무관하게 증거대로 수행하되, v0.8.2 통과분과
   repair 신규 통과분의 합이 `testing >= 200`일 때만 다음 retest 단계로 진행한다.
6. v0.8.3의 115개 × 3-seed 실제 판정은 얼굴·눈의 반복 크롭으로
   `testing 0 / generated 유지 115 / critical 0`이었다. 이 실패 matrix, 이미지,
   review, score 및 catalog 적용 근거는 변경하지 않고 보존한다.
7. 다음 전체 실행 전 v0.8.4 framing-first wrapper를 서로 다른 5개 signature와
   새 seed `[7101, 7202, 7303]`에 먼저 적용한다. wrapper는 정확한 catalog prompt
   본문을 한 번만 포함하고, full-body·camera-far-back·hair-to-shoes margin 지시를
   맨 앞에 배치하며 1,400자와 공백 기준 200단어를 넘지 않는다.
8. v0.8.4 calibration의 15개 이미지 모두에서 머리·얼굴·눈·양손·발이 프레임 안에
   보여야 한다. 하나라도 top/head/face crop이 있으면 전체 115개로 확장하지 않고
   wrapper를 다시 versioning한다. 이 crop gate와 8축 품질 gate를 모두 통과한
   profile만 잔여 `generated` 전체에 서로 다른 새 3개 seed로 실행한다.
   실제 v0.8.4 결과는 crop 0/15였으나 `character sheet` 해석으로 두 style에서
   복수 view가 발생했고 8축 장식 가시성도 부족하여 `testing 0 / rejected 5`,
   critical-failure image 6으로 전체 확장을 거부했다. 후속 v0.8.5는
   `single-view illustration`과 no-lineup/turnaround/panel 제약을 사용하며 다시
   5개 × 새 3-seed calibration을 통과해야 한다.
   실제 v0.8.5는 부정 목록의 `turnaround/crop` 개념이 이미지에 역으로 활성화되어
   상반신 크롭과 배경 인물 실루엣을 만들었고 `testing 0 / rejected 5`,
   critical-failure image 3으로 거부했다. v0.8.6은 부정 개념 목록을 제거하고
   기존 5-seed 결과로 검증된 `full-length editorial`, `eye-level head-to-toe`,
   `generous negative space around the complete silhouette` 긍정 구도만 사용한다.
   실제 v0.8.6은 single subject와 head-to-toe 구도를 15/15에서 복구하고 critical
   failure 0을 달성했으나, 8축 gate는 `testing 1 / rejected 4`였다. v0.8.7은 이
   검증된 editorial scene 문장을 변경하지 않고, feature token을 자연어의 구체적인
   framing 배치와 garment-plus-border ornament 지시로 번역해 나머지 축 가시성만
   보강한다.
   실제 v0.8.7은 단일 full-length 구도와 critical failure 0을 유지하면서
   `testing 3 / rejected 2`로 개선되었다. v0.8.8은 같은 editorial scene과 전체
   feature 번역을 고정하고, 실패한 `layered_intimate`의 배경 종이 레이어 및
   `dry_broken`·`luminous_glaze`의 표면 표현만 더 강한 자연어로 보강한다.
   실제 v0.8.8은 대표 5개 × 3-seed 전부에서 단일 head-to-toe figure, 8축 점수,
   critical failure 0을 만족해 `testing 5 / rejected 0` calibration gate를
   통과했다. 이 wrapper를 immutable full-screen profile로 고정하고, calibration과
   겹치지 않는 새 3개 seed로 잔여 `generated` 115개 전체를 실행한다. 실제
   full-screen은 seed `[13101, 13202, 13303]`, 115개 × 3-seed = 345개 job을
   `batch_size=1`, `queue_depth=32`로 완료했다. 345개 모두 1024×1024 PNG,
   remote success, 서로 다른 image hash를 가졌고 matrix SHA-256은
   `cf153c27a9b4446449b9108dd908dac1c1ed5d9ccc2b791bc94e584bab2081d2`로
   고정되었다. 동일 명령 재실행에서도 `complete=345`, `pending=0`이 확인되어
   중복 제출 없는 resume 조건을 통과했다. 12개 contact sheet 전수 리뷰 결과는
   `testing 40 / rejected 75 / critical failure 0`이었다. 복구 정책에 따라 실패
   75개는 `generated`로 유지하고 통과 40개만 `testing`으로 적용해 누적
   `testing 225 / generated 75`를 달성했다. 동일 evaluation 재적용은 catalog
   변경 0건으로 idempotence를 확인했고, v2 reference closure와 lifecycle 검증도
   통과했다. 따라서 `testing >= 200` gate를 충족해 5-seed retest로 이동한다.
9. retest matrix는 각 항목이 통과한 원래 prompt profile을 그대로 사용한다.
   기존 세 seed에 `[4004, 5005]`를 추가해 항목별로 정확히 서로 다른 5개 seed를
   확보하고, 5-seed 종합 판정 후에만 `approved` 승격을 허용한다. 기존 3-seed
   pilot의 통과 판정과 점수는 immutable 근거로 보존하고, retest review는 신규 두
   seed가 같은 profile의 시각 언어·품질·안정성을 유지하는지 회귀 여부를 판정한다.
   신규 seed가 pilot 품질 범위를 유지하면 기존 대표 metric을 5-seed 판정에
   유지하며, 실제 fidelity/adherence/stability/compatibility 하락이나 critical
   failure가 관찰된 항목만 `rejected`로 판정한다. 이 단계에서 변경 없는 과거
   pilot을 새 기준으로 소급 재심사하거나 최소 수량을 위해 점수를 완화하지 않는다.
   실제 retest는 현재 `testing` 225개에 seed `[4004, 5005]`를 추가해 450개
   extension job을 완료했다. 모든 결과는 1024×1024 PNG, remote success,
   고유 image hash였고 matrix SHA-256은
   `a88015e81b0875410c0bffe807e11987d887175f41cbf57b7816e983a2fea584`로
   고정되었다. 동일 명령 재실행은 `complete=450`, `pending=0`이었다. 기존
   675개 pilot row와 결합한 225개 × 5-seed = 1,125개 이미지 전수 review 결과는
   `approved 224 / rejected 1 / critical failure 0`이었다. 유일한 실제 회귀는
   한 항목의 seed 5005에서 기존 textile echo가 plain two-tone garment로
   사라진 경우였다. 225개 evaluation 적용 후 동일 명령 재실행은 lifecycle
   transition 0건이었고 v2 reference closure 및 lifecycle 검증을 통과했다.

모든 원격 matrix는 `batch_size=1`, 기본 `queue_depth=32`를 유지한다. 시작 전
원격 큐가 비어 있는지 검사하고, 이 계획이 제출하지 않은 작업은 취소·재정렬·삭제하지
않는다.

### 6.3 조합 테스트

단일 축 테스트를 통과한 항목에 대해 조합 테스트를 수행한다.

```text
style pack × character design
style pack × pose
style pack × lighting
style pack × background
artist signature × coloring
artist signature × camera composition
```

모든 전체 조합을 생성하지 않고 pairwise testing 방식으로 대표 조합을 선정한다.

---

## 10. 평가 기준

각 항목을 1점에서 5점으로 평가한다.

| 지표                  | 설명                       |
| ------------------- | ------------------------ |
| Prompt adherence    | 프롬프트 속성이 실제 이미지에 반영되는 정도 |
| Style fidelity      | 목표 작화 특성이 재현되는 정도        |
| Stability           | seed가 바뀌어도 속성이 유지되는 정도   |
| Character quality   | 얼굴, 눈, 손, 신체 품질          |
| Composition quality | 구도와 시선 흐름                |
| Compatibility       | 다른 wildcard와 결합했을 때 안정성  |
| Distinctiveness     | 다른 항목과 명확히 구별되는 정도       |
| Prompt efficiency   | 불필요하게 긴 문장 없이 효과를 내는 정도  |

### 승인 기준

```yaml
approval_policy:
  minimum_pilot_seeds: 3
  minimum_approval_seeds: 5
  minimum_prompt_adherence: 4
  minimum_style_fidelity: 3
  minimum_stability: 3
  minimum_compatibility: 3
  maximum_critical_failures: 0
```

### 상태 정의

Pilot 및 retest는 서로 다른 seed 3개 이상으로 진행한다. `approved` 승격은 서로
다른 seed 5개 이상을 확보한 뒤에만 가능하며, 3-seed screening 결과는 점수 기준을
통과하더라도 `testing`으로 유지한다.

| 상태         | 의미             |
| ---------- | -------------- |
| research   | 조사만 완료         |
| normalized | 시각 특성 분해 완료    |
| generated  | Krea2 문장 생성 완료 |
| testing    | 이미지 테스트 중      |
| approved   | runtime 등록 가능  |
| limited    | 특정 프리셋에서만 사용   |
| rejected   | 효과 없음 또는 품질 저하 |
| deprecated | 이전 버전 호환용      |

---

## 11. 대량 조합 제어

### 11.1 완전 무작위 조합 금지

다음 형태는 조합 수는 많지만 품질 관리가 어렵다.

```text
__linework__,
__coloring__,
__shading__,
__face__,
__body__,
__pose__,
__camera__,
__lighting__,
__background__,
__effect__
```

각 wildcard가 100개씩이면 이론적 조합 수가 과도하게 증가하며 대부분을 검증할 수 없다.

### 11.2 계층적 랜덤 방식

권장 구조:

```text
프리셋 선택
→ 프리셋 내부의 호환 스타일 선택
→ 캐릭터 선택
→ 포즈 선택
→ 카메라 선택
→ 조명 또는 효과 한 가지 변형
```

예시:

```text
__krea2/preset/anime_portrait__,
__krea2/character/expression/subtle__,
__krea2/camera/framing/portrait__,
__krea2/lighting/atmosphere/soft__
```

### 11.3 스타일 패밀리 구성

```yaml
style_families:
  refined_pastel:
    allowed_linework:
      - thin_tapered
      - delicate_clean

    allowed_coloring:
      - pastel
      - luminous_low_contrast

    allowed_shading:
      - soft_cel
      - gentle_gradient

    allowed_effects:
      - floating_petals
      - subtle_sparkles

  graphic_action:
    allowed_linework:
      - bold_graphic
      - angular_ink

    allowed_coloring:
      - high_contrast
      - limited_palette

    allowed_shading:
      - hard_cel
      - dramatic_shadow

    allowed_effects:
      - speed_lines
      - impact_particles
```

---

## 12. 파일 작성 규칙

### 12.1 YAML 키

* 영문 소문자 사용
* `snake_case` 사용
* 의미가 분명한 이름 사용
* 작가 실명 대신 내부 canonical ID 사용 가능
* 파일 경로와 YAML 루트가 중복되지 않도록 통일
* 숫자로 시작하는 키 금지
* 특수문자 최소화

### 12.2 YAML 값

* 실제 프롬프트는 영어로 작성
* 완성형 자연어 구문 사용
* 쉼표로 이어 붙여도 자연스러워야 함
* 한 항목에 하나의 중심 역할만 부여
* 품질어 반복 금지
* 동일 단어 3회 이상 반복 금지
* 모호한 감정 표현보다 시각적 표현 우선
* trailing comma를 값 내부에 넣지 않음

### 12.3 Multiline 사용

긴 스타일 팩은 folded scalar를 사용한다.

```yaml
complete_style:
  - >-
    polished anime illustration with precise tapered linework,
    compact elegant facial proportions, luminous layered eyes,
    soft cel shading, restrained pastel colors,
    and a balanced decorative composition
```

### 12.4 YAML anchor 제한

초기 버전에서는 YAML anchor와 alias를 사용하지 않는다.

```yaml
defaults: &defaults
```

파서와 wildcard 구현체별 동작 차이를 피하기 위해 빌드 스크립트에서 문자열을 직접 확장한다.

---

## 13. 자동화 스크립트 계획

### 13.1 `normalize_catalog.py`

기능:

* 태그 소문자 정규화
* underscore와 공백 alias 통합
* 작가 `@` 접두사 분리
* 중복 alias 병합
* canonical ID 생성
* 카테고리 매핑

### 13.2 `build_runtime_yaml.py`

기능:

* 승인 항목 추출
* 카테고리별 파일 생성
* multiline YAML 출력
* 빈 파일 생성 방지
* manifest 생성

### 13.3 `lint_wildcards.py`

검사:

```text
- YAML syntax
- wildcard path
- empty values
- forbidden tokens
- excessive length
- duplicate phrases
- unresolved variables
```

### 13.4 `check_conflicts.py`

프롬프트에 함께 존재하면 안 되는 속성을 검사한다.

```text
photorealistic + flat manga screen tones
chibi proportions + elongated model proportions
white background + dense environmental scene
hard noon sunlight + soft shadowless studio lighting
```

### 13.5 `export_prompt_matrix.py`

CSV 또는 JSONL 형태의 테스트 프롬프트를 생성한다.

```csv
test_id,seed,style_id,character_id,pose_id,camera_id,prompt
ST001,1001,refined_pastel,adult_elegant,standing_relaxed,eye_level,"..."
ST002,1001,bold_action,adult_elegant,standing_relaxed,eye_level,"..."
```

---

## 14. 버전 관리 정책

### 버전 규칙

```text
v0.1
- 구조 및 초기 테스트

v0.5
- 주요 카테고리 구현
- 자동 빌드 및 lint 적용

v1.0
- 승인된 wildcard 세트
- benchmark 결과 포함

v1.1
- 신규 작가 시그니처 추가

v2.0
- taxonomy 또는 키 구조 변경
```

### 변경 이력

```markdown
## v0.2.0

### Added
- 40 modern anime style signatures
- 25 eye design wildcards

### Changed
- Split `coloring.yaml` into coloring and shading

### Removed
- Deprecated generic quality booster entries

### Fixed
- Duplicate pastel style prompts
- Dynamic Prompt brace conflicts
```

---

## 15. 품질 및 운영 리스크

| 리스크               | 영향              | 대응                        |
| ----------------- | --------------- | ------------------------- |
| Danbooru 태그 직접 이식 | Krea2에서 무반응     | 자연어 시각 특성으로 변환            |
| 작가 이름 과다 혼합       | 스타일 평균화         | 기본 한 명, 최대 두 방향만 실험       |
| atomic 완전 무작위     | 모순된 결과 증가       | style family와 preset 사용   |
| 품질어 과다            | 일반적인 AI 스타일로 수렴 | 구체적인 선·채색·구도 표현           |
| YAML에 메타데이터 혼합    | wildcard 경로 오염  | catalog와 runtime 분리       |
| `{}` 문법 충돌        | 프롬프트 파싱 오류      | NovelAI 강조 문법 제거          |
| 중복 wildcard       | 실질 다양성 감소       | 정규화 후 중복 검사               |
| 프롬프트 과장           | Krea2 해석 분산     | 각 항목의 역할 제한               |
| 모델 버전 변경          | 결과 재현성 저하       | 모델 및 workflow manifest 기록 |
| 작가 출처 불명확         | 관리 및 배포 리스크     | 출처와 alias 별도 기록           |
| 특정 캐릭터 IP 혼입      | 범용성 저하          | 캐릭터명과 작화 스타일 분리           |

---

## 16. 완료 기준

다음 항목이 충족되면 초기 버전을 완료한 것으로 판단한다.

### 기능 기준

* [ ] ComfyUI에서 모든 YAML 로딩 성공
* [ ] 모든 wildcard 경로 정상 치환
* [ ] unresolved wildcard 0건
* [ ] YAML syntax 오류 0건
* [ ] NovelAI 강조 괄호 충돌 0건
* [ ] catalog와 runtime 완전 분리
* [ ] 생성 최종 프롬프트 로그 저장

### 콘텐츠 기준

* [ ] 승인된 작화 스타일 팩 150개 이상
* [ ] 승인된 작가 시그니처 200개 이상
* [ ] 캐릭터 디자인 관련 항목 300개 이상
* [ ] 포즈 및 카메라 항목 300개 이상
* [ ] 조명 및 배경 항목 300개 이상
* [ ] 완성형 프리셋 100개 이상

### 품질 기준

* [ ] 승인 항목 평균 Prompt adherence 4점 이상
* [ ] 승인 항목 평균 Stability 3점 이상
* [ ] 주요 프리셋의 치명적 충돌 0건
* [ ] 동일 의미 중복률 5% 이하
* [ ] 무작위 생성 결과의 사용 가능 비율 측정
* [ ] Krea2 Turbo 기준 benchmark 보고서 작성

---

## 17. 권장 구현 순서

```text
1. runtime YAML 규격 확정
2. catalog 스키마 확정
3. NovelAI 스타일 태그 수집
4. Anima 작가 및 스타일 태그 수집
5. 태그 정규화
6. 시각적 특성 분해
7. Krea2 자연어 변환
8. 작화 스타일 팩 50개 시범 작성
9. 고정 seed benchmark
10. YAML 및 conflict linter 구현
11. 작가 시그니처 확대
12. 캐릭터·의상·포즈·카메라 확대
13. 프리셋 생성
14. 승인 항목 runtime 컴파일
15. v1.0 패키지 생성
```

가장 먼저 대량 생성하지 않는다. 다음 순서로 품질을 확인한다.

```text
50개 고품질 스타일 팩
→ 테스트 및 문장 규칙 확정
→ 300개 확장
→ 자동 평가 체계 적용
→ 3,000개 이상으로 확대
```

---

## 18. 최종 권장 아키텍처

```text
NovelAI / Anima / Danbooru Research
                  │
                  ▼
        Raw Source Catalog
                  │
                  ▼
      Visual Signature Normalizer
                  │
                  ▼
         Krea2 Prompt Compiler
                  │
          ┌───────┴────────┐
          ▼                ▼
   Atomic Wildcards   Complete Style Packs
          │                │
          └───────┬────────┘
                  ▼
        Compatibility Rules
                  │
                  ▼
         Runtime YAML Build
                  │
                  ▼
       ComfyUI Batch Benchmark
                  │
                  ▼
       Evaluation and Approval
                  │
                  ▼
      Production Wildcard Library
```

핵심 원칙은 다음 한 문장으로 정리한다.

> NovelAI와 Anima에서 작가 및 작화 지식을 수집하되, Krea2 실행 단계에서는 태그 이름보다 선화, 얼굴, 눈, 채색, 명암, 구도, 조명과 같은 재현 가능한 시각 속성을 사용한다.
