# CLAUDE.md — Evidence Atlas

> DFIR 포렌식 증거 그래프 도구. Claude가 이 레포에서 작업할 때 따르는 기준 문서.

## 1. 프로젝트 개요

Evidence Atlas는 KAPE/EvtxECmd 등의 CSV 출력을 파싱하여 원본을 보존하면서 관계 그래프와 시간축으로 탐색하는 DFIR 분석 도구다.

- **GitHub**: https://github.com/sasumm25-lab/dfir
- **설계서**: `DESIGN.md` — 반드시 먼저 읽을 것

## 2. 핵심 원칙 (변경 불가)

1. **증거 무결성** — raw_json 변형 금지, SHA-256 추적
2. **인과 확정 금지** — 공유 참조만 기록, 공격/악성 단정 금지
3. **time_kind 보존** — 13종 시각 의미 구분
4. **수집 범위 분리** — C/VSS 독립 보존

## 3. 현재 진행 상태

| Phase | 상태 | 핵심 파일 |
|-------|------|----------|
| Phase 1: ES 백엔드 | 동기화·조회 완료 / ES 뷰어 전환 미완료 | `es_store.py`, `es_mappings.py` |
| Phase 2: 그래프 시각화 | ✅ 구현·검증 완료 | `static/graph.js`, `static/graph.css` |
| Phase 3: Sigma 매칭 | ✅ 구현·검증 완료 | `sigma_engine.py`, `tests/test_sigma.py` |
| Phase 4: 다중 소스 | 미착수 | — |
| Phase 5: 다중 호스트 | 미착수 | — |

## 4. 교차 개발 (Claude ↔ Codex)

DESIGN.md 섹션 9에 모듈 소유권표와 교차 규칙이 있다. 상대 AI가 작업한 파일을 수정할 때는 먼저 diff를 확인할 것.

## 5. 실행 방법

```powershell
# 이 디렉터리 안에서 실행
python -m dfir_graph --db data/attack-samples.sqlite serve --port 8769
python -m dfir_graph --db data/attack-samples.sqlite es-sync
python -m dfir_graph --db data/attack-samples.sqlite es-status --case EVTX-ATTACK-SAMPLES
```

## 6. 커밋 규칙

- 메시지: `dfir: <한국어 설명>` 형식
- 브랜치: `main`
