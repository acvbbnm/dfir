# AWS 관제·포렌식 실험 환경

Evidence Atlas에서 조사할 실제 클라우드 증거를 만드는 환경이다. 인프라 구축 → 정상/의심 활동 → SIEM 경보 → 사건별 증거 수집 → 반출 → Atlas 분석을 목표로 한다.

> **2026-09-16:** 로컬 회귀·일부 Linux 서비스 검증 완료, **AWS 미배포**. 계정/프로필·배포 역할·AMI·견적과 실제 AWS 수락 검사는 남아 있다. 전체 진행 상태는 [루트 README](../README.md)를 따른다.

## 현재 코드가 구성하는 환경

Security/Workload 두 계정, 서울 리전, Workload VPC `10.60.0.0/16`을 기준으로 한다.

| 계층 | 구성 |
|---|---|
| 요청 경로 | 선택 SSM 테스트 호스트 → 내부 ALB:443 → WEB:8080 → APP:8080 → 비공개 RDS:3306 |
| WEB | Ubuntu 24.04, Nginx, ModSecurity v3/CRS, Suricata NFQUEUE, Velociraptor |
| APP·DB | Apache/PHP-FPM, WordPress 7.1, 별도 DVWA 2.5 가상 호스트·사용자, RDS MySQL 8.4 계열/TLS |
| SOC | Elasticsearch/Kibana/Fleet 8.19.20, 로그 정책·수집기·13개 탐지 후보 규칙 |
| Security | 중앙 CloudTrail 원본, S3 증거 staging/final, KMS, DynamoDB, EventBridge/SQS/Step Functions/Lambda |

AWS WAF와 자동 증거 수집은 기본 비활성이다. ModSecurity는 초기 DetectionOnly, Suricata는 초기 alert 규칙이다. Agent 등록·커널 이벤트·실제 차단은 배포 후 확인해야 한다. 설치 코드가 있다는 이유로 현재 방어 중이라고 표시하지 않는다.

## 먼저 읽을 문서

| 목적 | 문서 |
|---|---|
| 최신 수정·검증·남은 조건 | [SCENARIO_FIXES.md](results/SCENARIO_FIXES.md) — cloud-lab 72개 + Atlas 79개 = 151개 |
| 실제 배포 순서 | [DEPLOYMENT.md](DEPLOYMENT.md) — 계정 입력 → foundation → lab → automation → 수락 → 반출/정리 |
| 로컬 검사 재현 | [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) |
| 서버·방어 정책·구축 작업 | [BUILD_AND_ATTACK.md](BUILD_AND_ATTACK.md) |
| 전체 설계·클라우드 증거 | [DESIGN.md](DESIGN.md), [CLOUD_FORENSICS.md](CLOUD_FORENSICS.md) |
| SIEM 적용 범위 | [siem/README.md](siem/README.md) |
| 시나리오 조건 | [SCENARIO_LIBRARY.md](scenarios/SCENARIO_LIBRARY.md), [catalog.json](scenarios/catalog.json) |
| OSS·고정 버전 | [OPEN_SOURCE.md](OPEN_SOURCE.md), [artifacts.lock.json](artifacts.lock.json), [toolchain.lock.json](toolchain.lock.json) |
| 이전 기준선 | [LOCAL_VALIDATION.md](results/LOCAL_VALIDATION.md) — 2026-09-15의 142개 검사 기록 |

설계 문서는 목표 범위를 포함한다. 현재 실행 기준은 DEPLOYMENT와 최신 검증 기록으로 확인한다.

## 구현 범위와 후속 작업

- `infra`: foundation/lab/automation의 3단계 IaC. `bootstrap`·`application`: 서버·웹/DB·방어 설정.
- `collectors`·`siem`: 경보/원본 로그/Linux triage 수집과 정책·파서·규칙. 로그 관측, 경보, 차단, 사건 수집은 각각 확인한다.
- `scenarios`: S0~S3 제한 HTTP 준비 검사, S4~S6 수동 수락 절차, 별도 36개 실험 명세·준비 조건. 36개 자동 공격 실행기는 아니다.
- `scripts`: 배포 입력·운영 계획·실행 원기록·증거 반출/검증. `playbooks`의 containment/iam_response/recovery는 수동 runbook 설계이며 대응 실행기는 없다.
- Atlas는 검증된 사건 묶음의 **오프라인 cloud-import**를 초기 구현했다. 실제 AWS IAM/STS 관계 분석·SIEM 자동 전달·RAM/대용량 수집·digest 서명 검증은 후속 범위다.

## 비용과 종료

총 AWS 예산 목표는 **$300**이며 확정 견적이 아니다. 실제 리전·자원·가동 기간·크레딧을 확인한 후 배포한다.

- `setup`: NAT 활성. `operate`: NAT 대신 단일 AZ의 interface endpoint 9개. `idle`: 둘 다 제거.
- **idle은 EC2/RDS 정지가 아니다.** 서버 중지는 별도 작업이며 ALB·디스크·증거 저장 등의 잔여 비용이 있다.
- 종료 전 전체 사건과 PARTIAL 원본을 반출·검증한다. 증거 보관 계층은 실험 서버와 함께 일괄 삭제하지 않는다.
- 월간 예산 알림과 `cost_guard.py`는 강제 지출 상한이 아니다. 실제 종료 순서는 [DEPLOYMENT.md](DEPLOYMENT.md)를 따른다.
