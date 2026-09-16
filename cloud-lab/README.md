# AWS 관제·증거 수집 준비

현재 상태: **배포 전 로컬 검증 완료 / AWS 미배포 / Atlas AWS 분석은 초기 가져오기 단계**.

- 결과와 검증 한계: [LOCAL_VALIDATION.md](results/LOCAL_VALIDATION.md)
- 실제 현재 구성·배포 순서: [DEPLOYMENT.md](DEPLOYMENT.md)
- 로컬 재현: [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)
- 서버/수집/조사 목표: [DESIGN.md](DESIGN.md), [CLOUD_FORENSICS.md](CLOUD_FORENSICS.md)
- 고정 버전: [artifacts.lock.json](artifacts.lock.json), [toolchain.lock.json](toolchain.lock.json)

`infra`는 3단계 IaC, `bootstrap`은 서버 설치, `application`은 웹/방어 설정, `collectors`는 경보·로그·triage 수집, `siem`은 정책/파서/규칙, `scenarios`는 수행 범위와 예상 증거, `scripts`는 입력·운영·반출 도구다.

과거 설계의 모든 예정 기능이 구현된 것은 아니다. 현재 구현/검증 범위는 위 결과표와 루트 README 체크리스트를 따른다. 사용자의 총 AWS 예산 목표는 $300이며 월간 예산 알림은 지출을 강제로 막지 않는다.
