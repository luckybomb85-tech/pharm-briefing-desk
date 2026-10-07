# 제약바이오 브리핑 — v1.0

이 저장소의 현재 유일한 운영 기준은 `config/briefing-settings.json`의 **v1.0**이다.

## 운영 원칙
- 아침 검색창: 당일 전체 + 전날 12:00 이후.
- Collector A/B/C/D/WEB을 독립적으로 실행하고 각각 PASS/PARTIAL/FAIL을 기록한다.
- 검색 실패와 정상 0건을 구분한다.
- 후보는 Event 단위로 NEW/UPDATE/DUPLICATE 처리한다.
- 국내 10건은 목표치일 뿐 고정 쿼터가 아니다. 가치 있는 기사는 10건을 넘어도 포함하며 억지로 10건을 채우지 않는다.
- 핵심 야마를 바꾸는 사실만 최소 검증한다.
- v1.0 검증 완료 전 Telegram/Pages/public data 배포는 중지한다.

## 충돌 방지
- 구버전의 국내10/글로벌10/특허5 고정 규칙은 폐기됐다.
- 과거 `data/`는 기록 보존용이며 v1.0 신규 실행의 입력으로 사용하지 않는다.
- 신규 staging final은 반드시 `schema_version=briefing-final-v1.0`을 포함한다.
- Event Map은 반드시 `schema_version=briefing-event-map-v1.0`을 포함한다.
- schema_version이 없거나 다른 산출물은 legacy로 간주하며 v1.0에서 소비하지 않는다.

## 배포
`.github/workflows/publish.yml`은 검증 기간 동안 수동 호출만 가능하고 실제 배포 작업은 하지 않는다.
