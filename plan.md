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

`phase6_positive_profile_v3`는 새 seed `[21001, 22002, 23003]`으로 분리해
69/69개 1024×1024 PNG와 고유 image hash를 생성했고, 재실행에서
`complete=69`, `pending=0`을 확인했다. matrix SHA-256은
`132e3eec92458973eb920a16f43abf1957050c5a84e604883e022dadd480a2d3`이다.
v3 review는 통과 11개, 미달 12개, critical failure 0으로 v2의 duplicate
diptych와 대부분의 crown/eyes crop을 해소했다. single-axis camera와
linework/coloring, pairwise coloring·background·pose도 복구됐으나, 정확한
하단 crop 경계, artist-signature 가시성, lighting 우선순위, character garment
cue가 남았고 benchmark lighting은 회귀했다. v3 summary도
`status=failed`, `complete=false`로 보존하며 대량 제출을 계속 차단한다.
v4는 승인된 artist-signature의 8축 visibility ledger를 조합 경로에도 적용하고,
camera landmark와 light source의 우선순위를 문장 선두에서 단일 구체 장면으로
고정하며, 기존과 겹치지 않는 다음 3-seed calibration을 사용한다.

`phase6_positive_profile_v4`는 새 seed `[31001, 32002, 33003]`으로
69/69개 1024×1024 PNG와 고유 image hash를 생성했고, 재실행에서
`complete=69`, `pending=0`을 확인했다. matrix SHA-256은
`9db35968fb9497574e076a690f5523901455935505006f17d9ef7749b5b87e95`이다.
v4 review는 통과 11개, 미달 12개, critical failure 0이었다. 8축 visibility
ledger는 artist-signature의 ornament, textile, palette와 single-view 구성을
실제로 복구했고 character design도 통과시켰다. 남은 실패는 camera의 정확한 하단
경계와 비대칭 배치, pose의 발·지지 다리 또는 contrapposto, cool key와 warm
practical의 색 분리, benchmark의 diagonal division·matte grain·glint
가시성이다. v4 summary는 `status=failed`, `complete=false`로 보존한다.
v5는 통과한 ledger를 유지하면서 마지막 문장에 framing을 다시 고정하고, pose와
character 조합은 full-length, lighting 조합은 눈과 광원 색이 읽히는 waist-up
구도로 분기한다. lighting 및 benchmark는 이전에 통과한 짧은 v2 장면 구조를
재사용하되 새 profile SHA와 겹치지 않는 새 3-seed로 전체 69장을 다시 검증한다.

`phase6_positive_profile_v5`는 새 seed `[41001, 42002, 43003]`으로
69/69개 1024×1024 PNG와 고유 image hash를 생성했고, 재실행에서
`complete=69`, `pending=0`을 확인했다. matrix SHA-256은
`a4aae946eaed19abb1e4394d3aca885667c62fffd2f4cc7c1fcca1ee35d4fae1`이다.
v5 review는 통과 13개, 미달 10개, critical failure 0이었다. 짧은 v2 구조를
되살린 single-axis lighting과 benchmark는 세 seed 모두 통과했고, pairwise
camera는 chest-up profile·asymmetric negative space·counterweight를, pairwise
pose는 full-length·발·지지 다리를 복구했다. scale-aware ledger도 close/thigh
조합의 full-body 문구 충돌을 제거했다. 남은 실패는 single-axis photoreal
camera가 frontal-centered로 회귀한 1개, style pack의 광원 표현이 measured
lighting을 덮는 pairwise 1개, 그리고 preset/random에서 하의 단어가 exact crop을
넓히거나 wide/full 구도를 잘라낸 7개와 contrapposto를 직립시킨 1개다. v5
summary는 `status=failed`, `complete=false`로 보존한다.

v6는 성공한 v5 경로를 그대로 유지하고 세 경로만 구조적으로 수정한다.
single-axis camera는 모든 camera 항목에 동일한 2D storyboard baseline을 적용해
측정 축 외 스타일을 고정한다. pairwise lighting은 style pack의 구조·안료·표면·
분위기·edge를 feature axis에서 다시 합성해 기존 광원 문구를 제거하고, 오른쪽
lighting만 실제 광원을 공급하게 한다. preset/random은 camera scale에 맞춰
out-of-frame 하의 명칭을 prompt 본문에서 제거하거나 보이는 상단 부분으로
변환하며, contrapposto preset은 signature의 body cue 자체를 지지 다리·굽힌
무릎·counter-tilt와 양립하도록 변환한다. 기존과 겹치지 않는 새 3-seed로 69장
전체 calibration을 다시 통과해야 한다.

`phase6_positive_profile_v6`는 seed `[51001, 52002, 53003]`으로 69/69개
1024×1024 PNG와 고유 image hash를 생성했다. matrix SHA-256은
`5417778d50a123973910bdd4a71184d681c94099383274cf3a15d7e9871eb154`이다.
v6 review는 평균 prompt adherence 4.043, critical failure 0까지 개선됐으나
case별 gate에서 5개가 남았다. 실패 항목은 single-axis camera profile 안정성,
pairwise lighting의 실제 광원/재질색 분리, preset 002/005의 compressed
portrait crop, random utility 005의 contrapposto였다. summary는
`status=failed`, `complete=false`로 보존한다.

`phase6_positive_profile_v7`는 seed `[61001, 62002, 63003]`으로 69/69개
1024×1024 PNG와 고유 image hash를 생성했고 matrix SHA-256은
`cd9340643afe36fa2c8086f0f40dcb6be8180075f3e4ddb331b6157f04604ab8`이다.
camera, lighting, compressed portrait crop은 통과권으로 복구됐고 평균 prompt
adherence는 4.261까지 상승했다. 단, random utility 005의 contrapposto가 여전히
직립 정면 자세로 수렴해 summary는 `status=failed`, `complete=false`로 보존한다.

v8과 v9는 동일한 23 case × 3 seed calibration 구조로 contrapposto를 더 강하게
교정했다. v8은 seed `[71001, 72002, 73003]`, v9는 seed
`[81001, 82002, 83003]`을 사용했으며 두 run 모두 69/69개 1024×1024 PNG와 고유
image hash를 생성했다. v8은 contrapposto가 계속 직립으로 수렴했고, v9는
contrapposto를 통과권으로 복구했지만 preset 001의 thigh-up crop이 seed 변경으로
full-body에 가깝게 회귀했다. 두 run은 중간 probe로 보존하고, 후속 profile에서
mid-thigh lock을 별도로 강화했다.

`phase6_positive_profile_v10`는 seed `[91001, 92002, 93003]`으로 69/69개
1024×1024 PNG와 고유 image hash를 생성했고, `batch_size=1`,
`queue_depth=32` provenance를 유지했다. matrix SHA-256은
`ebfb89f25f579af0b5a6a56ebd072cf135423f16a929cc1b0a8af448c01cf823`이며
scored SHA-256은 `710482dfd0de4cf1ac1946bc4720153ba5c6f4ab31e443edb87007b867704aa2`이다.
summary는 `status=passed`, `complete=true`, critical failure 0이고 평균 metrics는
prompt adherence 4.304, style fidelity 4.391, stability 4.913, character quality
4.130, composition quality 4.652, compatibility 4.696, distinctiveness 4.217,
prompt efficiency 4.261이다. 이 v10 prompt-profile SHA-256
`29968f454a9ced61b54391d7dc39c608797c65bd434b0dafe3f36a6a0797cf12`을 Phase 6
대량 실행 기준으로 고정한다.

v11부터 v15까지는 single-axis 대량 검증에서 발견된 회귀를 보정하기 위한 후속
profile calibration이다. v11, v12, v13, v14는 모두 23 case × 3 seed = 69장
calibration을 완료하고 contact-sheet review에서 통과했으나, 이후 full
single-axis matrix에서 low-kneeling pose 계열이 seed 전반에서 standing pose로
수렴하는 문제가 확인되었다. v15는 `single-axis-unstable-pose-exclusion-v3`을
적용해 `pose_low_kneeling_low_crossed_forearm*` 및
`pose_low_kneeling_loosely_clasped*`를 single-axis RHS selection에서 제외했다.
v15 calibration은 seed `[91001, 92002, 93003]`으로 69/69개 1024×1024 PNG와
고유 image hash를 생성했고, `batch_size=1`, `queue_depth=32`,
`remote=private_comfyui` provenance를 유지했다. contact-sheet 전수 review는
23/23 case 통과, critical failure 0이며
`tests/reports/completion/phase6_calibration.json`은 `status=passed`,
`complete=true`이다.

민감정보와 보안 검토는 현재 Phase 6 생성 plan의 완료 gate에서 제외한다. 최종
결과물 산출 후 별도 보안 검토 에이전트가 서버 주소, 계정 식별자, 계정 경로,
비밀값, 배포 산출물 노출 여부를 독립 점검한다. 작업 중에는 로그와 커밋에
비밀값을 쓰지 않는 기본 위생만 유지한다.

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

single-axis full matrix는 v1부터 v6까지 반복했다. v1은 96 case/288 image 중
13 case가 실패했고, v2는 5 case, v3는 `single_axis_pose_006` 1 case,
v4는 low-kneeling 변형 1 case, v5는 다른 low-kneeling 변형 1 case가 실패했다.
각 실패 summary는 `tests/reports/completion/phase6_single_axis_v*_failed.json`에
보존한다. v6는 v15 profile 기준으로 96 case × 3 seed = 288장 원격 생성을
완료했고, 모든 PNG는 1024×1024, 고유 image hash, `remote=private_comfyui`,
`queue_depth=32`였다. contact-sheet 10장 전수 review에서 96/96 case가 통과했고
`tests/reports/completion/single_axis.json`은 `status=passed`,
`complete=true`, `passed_item_ids=96`이다.

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

pairwise matrix는 single-axis 통과 ID만 RHS로 사용할 수 있도록 allow-list gate를
적용한다. v1은 96 case × 3 seed = 288장 원격 생성과 PNG 검증을 완료했으나,
`pairwise_style_pack_background_007`에서 left style pack의 giant fibrous-paper
panel이 background axis를 압도해 adult subject가 누락되는 critical failure가
발생했다. 실패 summary는
`tests/reports/completion/phase6_pairwise_v1_failed.json`에 보존한다. v2는
`style_pack_background` pair type에서
`style_pack_expansion_minimal_quiet_jewel_and_gold_fibrous_paper*` 계열을 제외해
동일 background case를 subject-safe style pack으로 교체했다. v2 원격 matrix는
96 case × 3 seed = 288장, 1024×1024 PNG, 고유 image hash, `queue_depth=32`로
완료했고, contact-sheet review에서 96/96 case가 통과했다.
`tests/reports/completion/pairwise.json`은 `status=passed`, `complete=true`,
`right_item_ids=96`이다.

preset conflict audit v1은 100 preset case × 3 seed = 300장을
`batch_size=1`, `queue_depth=32`, `remote=private_comfyui`로 완료했다.
모든 결과는 1024×1024 PNG와 고유 image hash를 가졌고, contact-sheet 10장
전수 review에서 critical conflict 0건으로 통과했다.
`tests/reports/completion/presets.json`은 `report_type=preset_conflict_audit`,
`presets_tested=100`, `status=passed`, `complete=true`이며 matrix SHA-256은
`dcd3bf6e6b2ec36ed1cac6c54f0897b15a91fb658f534c929a969fa067bdb45d`이다.

random utility v1은 20 random sample case × 3 seed = 60장을 동일한 원격
provenance로 완료했다. contact-sheet 2장 전수 review 결과 sample 20/20이
usable이고 critical failure 0건이었다.
`tests/reports/completion/random_utility.json`은
`report_type=random_utility`, `utility_rate=1.0`, `status=passed`,
`complete=true`이며 matrix SHA-256은
`7d2e8adaab22605e64a2342f4ec905a3378df62b023a86557d9676fd17cac2ac`이다.

Krea2 Turbo benchmark v1은 benchmark case 1개를 seed
`[1001, 2002, 3003, 4004, 5005]` 5개로 실행해 5/5장 1024×1024 PNG와 고유
image hash를 생성했다. review 결과 critical failure 0건, stability 5.0,
composition quality 5.0, compatibility 5.0으로 통과했다.
`tests/reports/completion/benchmark.json`은
`report_type=krea2_turbo_benchmark`, `model=krea2_turbo_mxfp8`,
`status=passed`, `complete=true`이며 matrix SHA-256은
`5622d196b9629f15b05b1728b465619de2e34591f79ab59ce5737064a0d19de8`이다.

predeploy deterministic completion gate는 production runtime manifest 재생성,
Impact-compatible production build, runtime coverage audit, release evidence,
static duplicate audit digest 갱신 후 `tests/reports/completion_criteria.json`
기준 14/14개 통과 상태가 되었다. 민감정보와 보안 검토는 위에서 명시한 대로
최종 결과물 대상 별도 에이전트 범위에 남겨둔다.

production deployment v1은 predeploy strict 14/14 통과 후 production artifact를
원격 wildcard 경로에 backup suffix와 함께 적용했다. evidence에는 private remote
marker만 남기고 실제 endpoint, 계정 식별자, 계정 경로는 기록하지 않았다.
배포 산출물은 `build/impact-production/krea2_complete_pack.yaml`,
artifact SHA-256은
`d6262965c37dae2322666131dcef98979d65df4858cba57af6ec5220bce4a383`,
artifact bytes는 409,926, wildcard path count는 376이다.
`tests/reports/deployments/production_v1.json`은 `status=passed`, `mode=apply`,
`applied=true`, `approved_items=374`이며 checksum match, exact krea2 namespace,
ImpactWildcardProcessor reload, queue empty, smoke completed가 모두 true이다.
post-deployment smoke는 `crystal_iris_pastel` seed 6006으로 완료했고 deployment
nonce와 artifact/manifest SHA-256 binding을 가진 run record를 남겼다. 최종
`tests/reports/completion_criteria.json`은 16/16개 criteria 통과,
`complete=true` 상태다.

---

## Phase 7. 대량 검증

### 7.0 목표

v1.0 런타임에는 complete-scene 항목 374개만 들어갔다. `wildcards-manifest.json`은
`included_statuses: [approved]`이고 파일은 `krea2/style/complete_pack.yaml`과
`krea2/artist_signature/modern.yaml` 2개뿐이다. atomic axis 항목은 런타임에 하나도
없다. Phase 6은 축마다 16 case를 뽑은 표본 검증이었고, 통과한 개별 항목을
`approved`로 승격시키지는 않았다.

Phase 7의 목표는 `generated` 상태 3,325개 중 승격 가능한 3,301개를 축 단위로
승격시켜 런타임에 싣는 것이다. 완료 시 런타임 항목은 374개에서 3,675개로 늘어난다.

| 축                 | 항목        | seed | 이미지       | contact sheet |
| ----------------- | --------- | ---- | --------- | ------------- |
| camera            | 250       | 3    | 750       | 25            |
| lighting          | 250       | 3    | 750       | 25            |
| background        | 400       | 3    | 1,200     | 40            |
| character_design  | 400       | 3    | 1,200     | 40            |
| pose              | 326       | 3    | 978       | 33            |
| linework_coloring | 300       | 3    | 900       | 30            |
| media_rendering   | 150       | 3    | 450       | 15            |
| effect            | 200       | 3    | 600       | 20            |
| hair_design       | 250       | 3    | 750       | 25            |
| fashion           | 500       | 3    | 1,500     | 50            |
| 소계 (atomic axis)  | **3,026** |      | **9,078** | **303**       |
| preset            | 200       | 5    | 1,000     | 34            |
| artist_signature  | 75        | 5    | 375       | 13            |
| **합계**            | **3,301** |      | **10,453** | **350**       |

preset은 하나의 프롬프트가 pose·camera·조명·장소·표정을 동시에 지시하는 완전한 장면
계약이다. Phase 6이 preset을 충돌 audit 대상으로 삼은 이유가 그것이므로, atomic
axis의 3-seed가 아니라 complete-scene family의 5-seed 기준을 적용한다.
`complete_scene_families`에 `preset`을 포함한다.

pose는 350개 중 24개가 Phase 6의
`single-axis-unstable-pose-exclusion`(`SINGLE_AXIS_EXCLUDED_ITEM_PREFIXES`)으로
제외되어 승격 대상이 326개다. 제외된 24개는 anchor에서 불안정으로 판정된 항목이므로
그대로 승격하지 않는다. 별도 pose anchor를 만들어 재검증하거나 `rejected`로 확정하는
판단이 필요하고, 이 결정은 Phase 7 범위 밖에 남긴다.

3-seed tier 없이 전부 5-seed로 진행하면 16,505장이 필요하다. tier 적용으로
6,052장을 줄인다.

### 7.1 실행 순서

축마다 독립 release gate를 통과시켜 실패를 격리한다. Phase 6 single-axis가 anchor
프롬프트를 이미 검증한 6개 축을 먼저 처리해 파이프라인을 확정하고, anchor가 없는
4개 축은 각각 1 case × 3 seed anchor calibration을 먼저 통과시킨다.

```text
1. camera 250            (검증된 anchor, 파이프라인 확정)
2. lighting 250
3. background 400
4. character_design 400
5. pose 326
6. linework_coloring 300     소계 1,926
7. media_rendering 150   (신규 anchor, 최소 규모로 calibration)
8. effect 200
9. hair_design 250
10. fashion 500              소계 1,100
11. preset 200           (complete-scene, 5-seed, 충돌 위험 최대)
12. artist_signature 75  (complete-scene, 5-seed)
```

1번부터 11번까지는 `export_phase7_matrix.py`가 `--axis`로 처리한다. 12번
artist_signature는 `export_artist_visual_signature_matrix.py` 계열의 repair·retest
파이프라인이 이미 존재하므로 그 경로를 재사용하고, Phase 7 exporter에는 넣지 않는다.

### 7.2 배치 평가 설계

Phase 6의 수동 contact-sheet 리뷰를 10,125장에 그대로 적용할 수 없다. 리뷰 비용을
축 단위 배치로 고정하고 3단계로 escalation한다.

**Stage A. 결정론적 prefilter (모델 호출 없음)**

`scripts/audit_phase7_stage_a.py`가 `scorecard.csv`와 `run-state.json`, PNG를 직접
검사한다. seed 전수 완료, job 성공, 1024×1024 정확 일치, 같은 항목의 seed 간
`image_sha256` 상이, 균일·저엔트로피 degenerate 프레임 배제. 걸린 항목은 모델
리뷰로 보내지 않는다.

임계값은 luminance stddev 4.0, luminance level 8개다. Phase 6 single-axis v6의
실제 288장으로 검증했고 96/96 항목이 통과했다. 실제 프레임의 최저값은 stddev
25.35, level 184개로 임계값 대비 각각 6.3배와 23배 여유가 있어 정상 출력에서
오탐이 발생하지 않는다.

**Stage B. contact sheet 배치 리뷰**

한 항목의 seed를 인접 배치하고 시트당 10개 항목 30셀로 묶는다. 시트 1장이 모델
호출 1회이고 항목 10개의 판정을 한 번에 반환한다. 축 하나가 15~50장이므로 축별
리뷰가 독립 배치로 끝나고, 350장을 한 컨텍스트에 담지 않는다. 판정 기준은 Phase 6
리뷰에서 이미 언어화된 항목을 그대로 쓴다. 단일 성인 1인, 얼굴·양눈·양손 판독성,
framing contract 준수, 측정 축 속성의 가시적 반영, critical failure 유무.

배치 인프라는 신규 구현이 아니다. `build_prompt_matrix_contact_sheets.py`가 이미
`--cases-per-sheet 10`, `--expected-seeds 3`으로 `(mode, style_id)` 그룹화와 리뷰
스켈레톤 생성을 지원한다. Phase 7 행의 `mode`가 `mass_axis_<axis>`이므로 축마다
독립된 시트 계열이 생성된다.

단 시트 구성에 `--spread-cases`가 필요하다. 카탈로그가 조합형이라 알파벳 정렬 시
near-duplicate가 인접한다. camera 첫 시트는 10개가 전부 `chest_up`+`clean_profile`
변형이어서, 축이 반응하지 않아도 "일관적"으로 보이고 실패가 가려졌다. stride 배치는
정렬 목록 전체를 걸쳐 뽑으므로 한 시트에 눈에 띄게 다른 항목이 모인다. 시트 수와
항목 전수 보존은 동일하다.

**Stage C. 개별 확대 확인**

Stage B에서 borderline으로 표시된 항목만 전체 해상도로 1 seed 확인한다. 축별 항목
수의 5% 이하로 상한을 둔다. 상한을 넘으면 해당 축은 anchor 문제로 판단하고 승격을
중단한다.

기존 승격 경로에 그대로 접속한다. 자동화는 사람이 채우던 `review.yaml` 위치만
대체하고, 그 뒤 단계는 바뀌지 않는다.

```text
remote 실행  → run-state.json + scorecard.csv (metric 공란)
Stage A      → phase7_<axis>_stage_a.json      (모델 호출 없음)
Stage B / C  → review.yaml                     (배치 리뷰가 사람 리뷰를 대체)
apply_visual_review.py     → scored.csv
summarize_results.py       → summary.json      (recommended_status)
apply_evaluation_summary.py → catalog          (--require-tested-seeds 3)
```

각 단계 산출물이 디스크에 남으므로 축 단위로 중단하고 재개할 수 있다.

Make 타깃은 축을 인자로 받는다.

```bash
make remote-phase7-axis AXIS=camera
make phase7-axis-stage-a AXIS=camera
make phase7-axis-sheets  AXIS=camera
```

이 경로는 합성 입력으로 전 구간을 검증했다. 3-seed 결과가
`recommended_status=approved`로 계산되고, `--require-tested-seeds 3`으로 카탈로그
사본에 적용되며, 적용 후 카탈로그 프롬프트를 변조하면
`evaluated_prompt_sha256 is stale`로 차단된다. 즉 항목별 digest 보호가 실제로
작동한다.

### 7.3 prompt binding

`bind_artist_prompt_evidence.py`는 Phase 7에 쓸 수 없다. 이 스크립트는
`prompt_for_profile()`로 artist signature renderer의 프롬프트를 재구성해 matrix 행과
대조하므로, 다른 renderer로 만든 axis 행은 정의상 통과할 수 없다. 확인 결과 첫 행에서
`resolved prompt does not exactly bind the current catalog body`로 거부된다.

따라서 Phase 7은 `artifact_type: phase7_axis_prompt_binding`이라는 자체 레코드를
사용하고, 두 계층으로 검증한다.

1. `binding_sha256` payload digest — 단순 편집 탐지
2. exporter와 카탈로그에서 재유도 후 전체 문서 비교 — payload digest를 다시 계산한
   편집까지 탐지

`make phase7-axis-stage-a`가 Stage A 전에 이 검증을 실행한다. 항목별 승격 보호는
`apply_evaluation_summary.py`의 `validated_prompt_digest()`가 독립적으로 담당하므로
binding 파일은 증거 기록이고 승격 gate의 유일한 방어선이 아니다.

토큰 예산은 Stage B 350장 약 1.6M, Stage C 상한 약 0.7M으로 전체 2.3M 이내다.
장당 개별 리뷰는 약 22M이므로 배치가 약 10배를 줄인다.

### 7.4 matrix 산출물 취급

Phase 6 matrix는 288행 규모라 저장소에 커밋했지만, Phase 7 matrix는 축 하나가 최대
1,500행이고 10개 축 합계가 수십 MB다. `export_phase7_matrix.py`는 무작위 요소가
없어 같은 카탈로그에서 같은 파일을 재생성하므로 matrix 자체는 커밋하지 않고 build
산출물로 취급한다. 대신 run manifest에 matrix SHA-256을 기록하고, 검증이 필요할 때
재export로 대조한다. 승격 증거의 무결성은 `prompt_binding.json`의 항목별 prompt
digest가 담당한다.

`tests/reports/phase7_*/runs/`의 이미지별 run record도 같은 이유로 커밋하지 않는다.
축 전체로 약 10,453개 파일 36MB인데, `run-state.json`이 모든 job의
`resolved_prompt_sha256`, `workflow_sha256`, `image_sha256`, `prompt_id`를 이미
보유한다. 따라서 증거 체인은 다음과 같이 재구성 가능한 상태로 유지된다.

```text
exporter + catalog  →(결정론적)→ matrix
matrix              →(digest)→   resolved_prompt_sha256 in run-state.json
run-state.json      →(digest)→   image_sha256
```

커밋 대상은 `manifest.json`, `run-state.json`, `scorecard.csv`,
`prompt_binding.json`, Stage A 보고서, review, summary다.

### 7.5 camera 축 v1 차단 사유

camera 축 750장 생성 후 축별 gate가 승격을 차단했다. 원인은 프롬프트 내부 모순이다.

`export_phase6_matrix.py`의 camera 경로는 profile 항목에만
`CAMERA_SUBJECT_CONTRACT`("complete crown, facial profile, and visible profile
eye")를 적용하도록 되어 있고, 조건은 항목 본문에 리터럴 `clean profile`이 있는지
검사한다. 그런데 카탈로그 본문은 `clean side camera position ... preserves the
facial profile`이라고 쓰여 있어 그 문자열이 존재하지 않는다. 250개 camera 항목 중
조건이 발동하는 항목은 0개다. 즉 `CAMERA_SUBJECT_CONTRACT`는 실질적으로 죽은 코드다.

결과적으로 `clean_profile` 항목 42개가 모두 `SUBJECT_CONTRACT`의 "face, and both
eyes clearly readable"을 받는다. profile 뷰는 눈이 하나만 보이므로 두 지시는 양립할
수 없고, 생성은 정면으로 수렴한다.

원해상도 확인 결과:

| 항목 | 요청 | 결과 |
| --- | --- | --- |
| `camera_chest_up_clean_profile_classic_wide_asymmetric_negative_space` | chest-up, profile, 비대칭 배치 | crop만 반영, 정면 얼굴, 중앙 배치 |
| `camera_close_face_clean_profile_classic_wide_thirds_gaze_space` | close-face, profile, thirds 배치 | crop도 미반영(waist-up), 정면 얼굴 |

이 결함은 Phase 6 증거에도 존재한다. `phase6_single_axis.jsonl`의 camera 16개 중
profile 항목이 5개이고 5개 모두 동일하게 잘못된 contract를 받았는데, single-axis
review는 96/96 통과로 기록됐다. 즉 표본 review가 이 모순을 잡지 못했다.

`rear_three_quarter` 42개는 본문이 "face still readable through a natural turn"으로
자체 완화하고 있어 hard conflict는 아니지만, "both eyes clearly readable"이 정면으로
편향시키는 tension이 남는다. 이는 배치 review로 확인할 사항이다.

profile 판정을 실제 카탈로그 표현(`clean side camera position`, `facial profile`)에
맞추고 `CAMERA_SUBJECT_CONTRACT`를 적용하는 1차 수정을 적용했다. 판정은 id 기준 42개와
정확히 일치하고 과다 발동이 없으며, 나머지 208개 프롬프트는 byte 단위로 불변이다.
camera는 이 수정으로 검증된 anchor 축에서 빠져 Phase 7 profile(`phase7_mass_axis_v2`)로
이동했고 Phase 6 digest는 보존된다.

**그러나 1차 수정만으로는 부족하다.** profile 항목 4개 × 3 seed = 12장 calibration
결과 여전히 정면으로 렌더된다. 750장 재생성 전에 12장으로 확인해 차단했다.

전체 프롬프트를 문장 단위로 분해하면 뒤쪽 지시가 3번 문장의 profile 요구를 덮는다.

* `FINISH`: "keep the face, **eyes**, visible hands, joints..." — 복수 eyes
* 종결 `Final camera lock—make a tight chest-up **portrait**` — view angle 미언급

더 큰 결함은 종결 lock 자체다. `_framing_contract()`는 본문에서 crop 키워드를
substring으로 찾고 실패하면 기본값 "eye-level mid-thigh inspection frame ... the
complete crown, **both eyes**, shoulders..."로 떨어진다. camera 카탈로그의 8개 crop 중
3개는 대응 분기가 없다.

| crop | 항목 | 종결 lock |
| --- | --- | --- |
| `close_face` | 32 | 기본값 mid-thigh (오류) |
| `head_shoulders` | 31 | 기본값 mid-thigh (오류) |
| `vertical_full_scene` | 31 | 기본값 mid-thigh (오류) |
| `chest_up`·`full_length`·`thigh_up`·`waist_up`·`wide_environmental` | 156 | 정상 |

**250개 중 94개(38%)가 crop과 무관한 종결 lock을 받고, 그 94개 전부가 "both eyes"를
요구한다.** v1에서 `camera_close_face_clean_profile_*`이 close-face가 아니라
waist-up으로 렌더된 원인이 이것이다.

이 결함은 camera에 국한된다. 다른 9개 축은 `SINGLE_AXIS_FRAMING`·
`PHASE7_AXIS_FRAMING`의 고정 문자열을 넘기므로 전부 정상 매핑되고, preset은 200개 중
0개가 기본값에 걸린다. camera만 항목 본문을 `framing_value`로 넘긴다.

따라서 camera 승격은 다음을 요구한다.

1. `close_face`, `head_shoulders`, `vertical_full_scene` 종결 lock 분기 추가
2. 종결 lock과 `FINISH`를 view-aware로 만들어 profile 항목에서 "both eyes" 제거
3. calibration 재통과 후 750장 재생성

Phase 6 로직을 직접 수정하지 않고 Phase 7에서 override로 주입해야 하므로
`_profiled_prompt()`에 framing contract override가 필요하다. 이는 artist signature가
v0.8.3에서 v0.8.8까지 거친 것과 같은 수준의 반복 보정 작업이다.

### 7.6 lighting 축 calibration 통과

camera 사례 이후, 축마다 본 실행 전에 4항목 × 3 seed = 12장 calibration을 먼저
통과시킨다. 12장으로 750장을 지킨다.

lighting은 구조적으로 camera와 다르다. `single_axis_prompt()`의 lighting 분기는
`PROVEN_VISIBILITY_FINISH`로 조기 반환하므로 `_framing_contract()`를 거치지 않는다.
따라서 camera를 망친 종결 lock과 crop 매핑 결함이 존재하지 않는다. 사전 점검 결과
다른 9개 축과 preset 200개 모두 고정 framing 문자열을 사용해 기본값에 걸리지 않는다.

Phase 6에서 실패 원인이던 조명-얼굴 판독성 충돌도 확인했다. `silhouette`, `backlit`,
`rim` 표현은 250개 중 0개다. `behind`가 42개(`back_edge` 계열) 있으나 본문이
"arriving from behind as a controlled edge light **with a separate soft facial
fill**"로 얼굴 판독성을 자체 처리한다.

calibration 4항목(`broad_window frontal_three_quarter`, `cloud_scattered
back_edge`, `large_diffused_key high_side`, `practical_cluster low_bounce`)은
12/12장이 key 방향, 색온도, 그림자 경도에서 눈에 보이게 구분됐다. `large_diffused_key
high_side`는 softbox가 프레임에 실제로 보일 정도로 축이 강하게 반영됐다. 단일 성인
1인, 얼굴·양눈·양손·양발 판독성, 전신 framing이 12/12 만족이다.

미결 판정 기준 하나를 기록한다. `large_diffused_key` 계열은 조명 기구가 프레임에
보인다. anchor의 "uncluttered neutral studio cyclorama"는 배경을 가리키므로 기구
노출을 실패로 볼지는 배치 review에서 판정하고, 임의로 통과시키지 않는다. seed 간
기구 위치 변동도 stability 점수에 반영한다.

### 7.7 lighting 축 v1 승격 결과

750/750장 생성, Stage A 250/250 통과, binding 검증 통과 후 25장 spread 시트로 250개
전수 배치 리뷰를 수행했다. 결과는 통과 211개, 미달 39개(16%)다.

실패는 무작위가 아니라 특정 sub-attribute 조합에 집중된다.

| 조합 | 미달/전체 | 비율 |
| --- | --- | --- |
| `focused_beam` + `neutral_daylight` | 9/9 | 100% |
| `practical_cluster` + `back_edge` + `warm_key_cool_fill` | 4/4 | 100% |
| `focused_beam` + `frontal_three_quarter` | 8/9 | 89% |
| `focused_beam` 전체 | 18/36 | 50% |
| `overhead_skylight` 전체 | 15/35 | 43% |
| **전체** | **39/250** | **16%** |

`focused_beam`은 beam 경계가 보이지 않고 평면적으로 렌더된다. 단 `high_side`나
색온도 대비(`warm_key_cool_fill`, `cool_key_warm_practical`)와 결합하면 정상 표현된다.
즉 실패 조건은 방향 대비와 색 대비가 모두 없는 경우다.
`practical_cluster back_edge warm_key_cool_fill`은 warm key가 표현되지 않고 cool이
얼굴을 지배한다.

Stage C를 발동했다. `weak_face` 14개가 축 항목의 5% 상한을 넘겼으므로
`overhead_skylight_low_bounce` 3개를 원해상도로 확인했다. 결과는 판정을 양방향으로
교정했다.

* `case_195`, `case_211`: 시트 판정이 맞았다. 얼굴이 해골처럼 렌더되고 눈이 검은
  구멍이며 양손이 뭉개진다. character quality critical failure다.
* `case_200`: 얼굴은 판독 가능했고 시트 판정이 틀렸다. 실제 문제는 방향성 조명이
  전혀 없는 완전 평면 렌더와 손 붕괴였다. 판정을 `weak_axis`로 교정했다.

즉 5% 초과는 anchor 문제가 아니라 `overhead_skylight_low_bounce` 계열(20개 중 8개
미달)의 해부 품질 문제다. 따라서 축 전체를 중단하지 않고 해당 항목만 거부했다.

승격은 정책이 계산했다. `weak_axis`는 `prompt_adherence` 3으로 최소 4에 미달하고,
`weak_face`는 critical failure로 처리해 둘 다 `rejected`가 된다. `summarize_results.py`
결과는 approved 211, rejected 39로 리뷰 판정과 정확히 일치했다.

`catalog/lighting.yaml`은 blueprint 생성기가 관리하는 파일이라 상태 변경이 `make check`
에서 `managed output changed outside the generator`로 차단됐다. 작가 파이프라인과 동일하게
`refresh_generation_manifest.py`로 validation-only 변경을 manifest에 반영해야 한다. 이
단계를 축별 gate에 포함한다.

런타임은 374개에서 585개로 늘었고 `krea2/lighting/complete.yaml`이 추가됐다.

### 7.8 background 축 calibration 통과

사전 구조 점검에서 substring 스캔이 `crowd` 50개와 `silhouette` 50개를 위험으로
표시했으나 실제 문장은 "without **crowd**ing the figure", "leaving the
**silhouette** unobstructed"였다. 둘 다 피사체를 보호하는 문구이고 모순이 아니다.
Phase 6 camera 버그가 발동하지 않는 substring 검사였던 것과 대칭으로, 이번에는
과다 발동하는 substring 검사였다. 두 경우 모두 실제 문장을 읽어야 한다는 결론이
같다.

background는 `SINGLE_AXIS_FRAMING`이 `Use an eye-level full-length camera.`이므로
종결 lock이 full-length로 정확히 매핑되고 기본값 fallthrough가 400개 중 0개다.
`_background_axis_anchor()`가 두 문장을 추가해 Phase 6 pairwise v1의 실패
(배경이 피사체를 압도)를 직접 방어한다. 구조물을 난간·기둥·벤치·화분·수목 같은
비인간 객체로 한정하고, 측정 대상 성인을 유일한 인간 형상으로 고정한다.

calibration 4항목(`coastal_overlook clear_depth_layers`, `glasshouse_corridor
leading_path`, `riverbank_path flanking_verticals`, `transit_concourse
repeated_recession`)은 12/12장이 장면 계열, depth 구조, 색 팔레트에서 명확히
구분됐다. `flanking_verticals`는 수직 쌍이 피사체를 감싸는 형태로,
`repeated_recession`은 열주의 반복 후퇴로 각각 명세대로 표현됐다. 12장 전부
비인간 구조물만 사용하고 추가 인물이 없어 anchor 두 문장이 의도대로 작동했다.

### 7.9 background 축 v1 승격 결과

1,200/1,200장 생성, Stage A 400/400 통과, 40장 spread 시트로 400개 전수 리뷰를
완료했다. 결과는 통과 399, 미달 1로 통과율 99.75%다. lighting의 84.4%보다 현저히
높다.

리뷰는 네 구간으로 나눠 진행했다. 1구간 시트 1~5(50개), 2구간 시트 6~15(100개),
3구간 시트 16~25(100개), 4구간 시트 26~40(150개)이며 2~4구간은 전부 100% 통과했다.

유일한 미달은 `coastal_overlook_clear_depth_layers_clear_still_natural_green_earth`
의 팔레트 미표현이다. 같은 `natural_green_earth` 팔레트를 쓰는 시트 3의 10개 항목이
모두 정상 표현됐으므로 계열 문제가 아니라 개별 예외다.

다만 `coastal_overlook` 계열은 `natural_green_earth`를 일관되게 약하게 표현한다.
암반과 바다가 지배하는 장면에 식생이 적어 장면 특성상 타당하므로, 녹색이 전경
식생에 존재하는 경우는 통과로 판정하고 완전 무채색인 경우만 미달로 본다.

400개 전부에서 anchor 두 문장이 작동했다. 구조물이 난간·기둥·벤치·화분·수목 같은
비인간 객체로 한정되고 추가 인물이 없으며 피사체가 배경에 묻히지 않는다.

depth sub-attribute 7종이 모두 시각적으로 구분된다. `elevated_horizon`은 수평선이
높게 앉고, `low_horizon`은 낮게 앉는다. `leading_path`는 바닥 대각선으로,
`flanking_verticals`는 좌우 수직 쌍으로, `centered_opening`은 중앙 개구로,
`repeated_recession`은 반복 구조물의 후퇴로, `open_gaze_side`는 한쪽이 열린 구성으로
나타난다. atmosphere 5종(`clear_still`, `crisp_visibility`, `faint_depth_haze`,
`delicate_particles`, `soft_ambient_diffusion`)과 palette 4종도 각각 분리된다.

승격은 정책이 계산했다. `summarize_results.py` 결과가 approved 399, rejected 1로
리뷰 판정과 정확히 일치했다. `refresh_generation_manifest.py`로 validation-only
변경을 반영하고 런타임을 재빌드해 585개에서 984개로 늘었으며
`krea2/environment/complete.yaml`이 추가됐다. runtime coverage는 988/988 경로
통과다.

**리뷰 판정은 `tests/reports/phase7_background_v1/review_parts/sNNN.json`에 시트
단위로 영속화한다.** lighting 리뷰는 세션 임시 디렉터리에만 있어 세션이 끊기면
소실되는 구조였다. 저장소에 쌓으면 구간을 나눠 진행하고 재개할 수 있다.

구간을 나누는 이유가 하나 더 있다. lighting에서 25시트를 연속 리뷰한 뒤 후반부
`case_200`을 오판했고 Stage C가 이를 교정했다. 구간을 나누면 그런 오판 자체가 줄어든다.

구간 분할은 리뷰 품질에도 기여했다. lighting에서 25시트를 연속 리뷰한 뒤 후반부
`case_200`을 오판했고 Stage C가 이를 교정했다. background는 구간을 나눠 400개를
판정했고 Stage C 발동이 필요한 borderline이 나오지 않았다.

### 7.10 character_design 축 calibration과 시트 밀도

사전 구조 점검은 통과했다. 종결 lock이 full-length로 정확히 매핑되고 기본값
fallthrough가 400개 중 0개이며 위험 용어도 없다. 실루엣 8종이 각 50개로 균등하다.

calibration 12장의 시트 판정에서는 `asymmetric_urban`, `compact_balanced`,
`soft_rounded` 세 항목이 모두 유사한 베이지 드레이프 로브로 수렴해 보였고
seam/closure 모티프가 전혀 보이지 않았다. 그러나 Stage C 원해상도 확인에서 판정이
뒤집혔다.

* `asymmetric_urban ... botanical_seams`: 비대칭 offset 레이어가 뚜렷하고, 가슴
  중앙에 곡선 seam과 **잎 모양 클로저**가 명확히 존재한다.
* `compact_balanced ... modular_utility`: 허리에 **사각 모듈형 탭 클로저**가 있고
  각진 턱선도 구분된다.

즉 seam/closure 모티프와 얼굴 기하는 정상 표현되지만 contact sheet 해상도로는
판독할 수 없다. 원인을 측정으로 특정했다.

| 시트 밀도 | 시트 높이 | 표시 배율 | 셀 폭 | 400개 시트 수 |
| --- | --- | --- | --- | --- |
| 10 항목 | 3,376px | 0.59 | 161px | 40 |
| 8 항목 | 2,716px | 0.74 | 200px | 50 |
| 6 항목 | 2,056px | 0.97 | 265px | 67 |
| **5 항목** | **1,726px** | **1.00** | **272px** | **80** |
| 4 항목 | 1,396px | 1.00 | 272px | 100 |

시트 폭은 seed 3열로 고정이므로 셀 폭은 표시 축소에만 좌우된다. 5항목이 축소가
사라지는 최대 밀도이고 셀 폭이 10항목의 1.7배다. 4항목으로 더 줄여도 셀은 커지지
않고 시트 수만 늘어난다. 따라서 character_design은 `CASES_PER_SHEET=5`로 80시트를
사용한다.

lighting과 background는 측정 대상이 조명 방향·색온도·장면 구조처럼 큰 특징이어서
10항목 시트로 충분했다. character_design은 seam과 클로저처럼 작은 특징이 판정
대상이므로 밀도를 낮춘다. 축의 특징 크기에 따라 시트 밀도를 정한다.

남은 위험 하나를 기록한다. 실루엣 8종 중 `practical_athletic`은 스포츠웨어로 명확히
구분되고 `asymmetric_urban`도 비대칭이 뚜렷하지만, `compact_balanced`와
`soft_rounded`는 원해상도에서도 일반적인 드레이프 형태로 수렴한다. 전수 리뷰에서
실루엣별 통과율을 집계해 정책이 미달 항목을 거부하도록 한다.

### 7.11 축별 완료 gate

축 하나를 승격할 때마다 다음을 모두 통과해야 다음 축으로 넘어간다.

* Stage A 전수 통과, Stage C 상한 미초과
* `prompt_binding.json` 재유도 검증 통과
* atomic axis는 `--require-tested-seeds 3`, complete-scene은 `5`를
  `--allow-recommendation`과 함께 명시한 승격 적용
* `refresh_generation_manifest.py`로 validation-only 변경 반영
* matrix SHA-256을 run manifest에 기록
* production 런타임 재빌드 후 `manifest_catalog_item_ids_match`
* `make check` 전체 통과
* `runtime_coverage` unresolved wildcard 0건

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
  minimum_pilot_seeds: 2
  minimum_approval_seeds: 3
  minimum_prompt_adherence: 4
  minimum_style_fidelity: 3
  minimum_stability: 3
  minimum_compatibility: 3
  maximum_critical_failures: 0
  complete_scene_approval_seeds: 5
  complete_scene_families: [artist_signature, preset, style_pack, 그리고 10개 art style family]
```

seed 기준은 두 단계로 나눈다. complete-scene family는 하나의 프롬프트로 모든 축을
동시에 지시하므로 seed 간 분산이 크고, 기존 5-seed 기준을 그대로 유지한다. atomic
axis family는 Phase 6에서 3-seed로 이미 검증된 anchor 장면에 단일 속성만 바꿔
얹으므로 분산이 anchor에 의해 지배된다. 따라서 atomic axis는 3-seed 승인을
기준으로 삼는다. 이 완화 없이는 3,325개 항목 승격에 16,625장이 필요해 실행이
불가능하다.

`scripts/summarize_results.py`는 family를 모르는 채 flat 정책으로 추천 상태만
계산한다. 실제 tier 집행은 두 곳에서 이루어진다. `apply_evaluation_summary.py`
호출마다 `--require-tested-seeds`와 `--allow-recommendation`을 명시하고,
`tests/test_catalog.py`가 complete-scene family 승인 항목이 5-seed 미만으로
내려가지 않는지 불변식으로 검사한다.

### 상태 정의

Pilot은 서로 다른 seed 2개 이상, atomic axis 승인은 3개 이상, complete-scene
family 승인은 5개 이상으로 진행한다. 승인 seed 수에 미달하면서 점수 기준은
통과한 결과는 `testing`으로 유지한다.

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
