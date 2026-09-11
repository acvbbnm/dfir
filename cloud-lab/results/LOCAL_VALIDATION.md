# 로컬 검증 기록 — 2026-09-11

기준: `44e1908`의 AWS 코드 초안에 대한 설치·인프라·실패 처리 보완.

| 검사 | 결과 |
|---|---|
| OpenTofu format | 통과 |
| foundation/lab/automation Provider init | backend 비활성, 모두 통과 |
| foundation/lab/automation validate | 모두 통과 |
| Python·Bash·실제 cloud-config·ZIP 회귀 검사 | 47 passed in 5.49s |
| AWS 인프라 plan/apply | 미수행 — 계정·프로필 준비 전 |
| Linux 서비스 실행·실제 공격·탐지 | 미수행 |

기계 판독 결과: [local-validation.json](local-validation.json). 재현 절차와 구체적인 잔여 작업: [LOCAL_DEVELOPMENT.md](../LOCAL_DEVELOPMENT.md).

## 수정 범위

- 공통·역할별 설치 파일과 설정을 EC2에 함께 전달. upstream IP·셸 인용·gzip 크기 검사.
- WAF 문법, Provider lock, ALB 인증서 placeholder, 최초 state 버킷 생성 순서 보완.
- WEB→APP→RDS 및 Agent→SOC 송신 규칙, DB 전용 route, 제한된 격리 SG 보완.
- NAT 없는 운영 모드에 일반 AWS API endpoint 6개 추가. SSM endpoint와 SG 분리.
- Suricata를 ALB→WEB의 INPUT/OUTPUT 경로에 연결하고 ALB source에 맞춘 규칙 경계 설정.
- WordPress 전용 secret·DB 사용자 분리, 감사 플러그인 배치, 안전한 PHP 설정 직렬화.
- SOC의 지정 EBS만 선택하고 기존 파일시스템 재사용. ES/Kibana TLS·service token 연결.
- 두 계정 CloudTrail의 중앙 보관과 Workload 원본 EBS KMS 키 소유권 보완.
- Lambda ZIP 공통 모듈 포함, IAM action·SSM 문서 계정·AWS 조회 계정 수정.
- 확인 불가능한 대상 거부, SSM 대기 상태 처리, 부분 수집을 READY로 표시하지 않도록 보완.
- 다운로드 해시가 없거나 Agent CA가 없으면 설치를 중단하도록 수정.

## 진행 판정

**로컬 검증을 갖춘 코드 초안**이다. Phase A 전체 완료나 전체 시스템 배포 완료로 판정하지 않는다. A0~A7 및 G0~G8은 실제 근거가 생기기 전까지 미완료다.

다음 단계는 버전·해시/AMI·계정 준비, 최소 서비스 구축, 실제 로그와 정상 기준선, 공격·탐지 대조, 증거 수집·Atlas 연동이다. Fleet, DB 사용자/seed, 생성된 offline collector와 staging 업로드, 원본 로그·manifest·재시도 계약 등은 개발 안내서에 남은 작업으로 기록했다.
