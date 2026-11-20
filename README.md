# Evidence Atlas

Windows 포렌식 기록을 시간축과 관계 그래프로 탐색하고, 화면에서 발견한 단서를 원본 CSV 행까지 따라가는 도구입니다.

개인 프로젝트 · 아티팩트 수집·저장 모델과 조사 뷰어 설계·구현 · 2026년 9월 로컬 검증

[실데이터 검증 결과](docs/USAGE.md#이-수집본의-검증-결과) · [Windows에서 실행](docs/USAGE.md)

시연에서는 합성 Prefetch 기록을 선택하고 실행 시각과 원본 CSV 행을 확인합니다.

![시간축에서 Prefetch 기록과 원본 행을 확인하는 화면](docs/images/readme-demo.gif)

## 작업 기록

- [아티팩트와 원본 보존](docs/evidence-records.md) · KAPE CSV 가져오기와 원본 행 연결
- [시간축과 관계 그래프](docs/investigation-viewer.md) · 시각 구분과 공유 참조 표시
- [로컬 검증](docs/validation.md) · 반복 가져오기, Sysmon 표시 문제, 회귀 테스트
