# 구현 작업 세분화 목록

작성일: 2026-09-09  
기준 문서: DESIGN.md, BUILD_AND_ATTACK.md, CLOUD_FORENSICS.md, OPEN_SOURCE.md, PIPELINE.md

게이트(G0~G8), 빌드 단계(B00~B14), 구현 Phase(A~E)를 하나로 통합한 세부 작업 목록이다.  
각 작업은 **독립적으로 완료 확인이 가능한 단위**로 분해했다.

---

## Phase A: 로컬 준비 (AWS 리소스 생성 전)

> 게이트: G0 · 빌드: B00~B01  
> 목표: 코드·도구·구조를 확정하고, `tofu plan`까지 로컬에서 통과

### A-1. 프로젝트 구조 생성

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-1-1 | cloud-lab/ 하위 디렉터리 생성 (infra/, bootstrap/, application/, collectors/, playbooks/, scenarios/, scripts/, tests/, results/) | 빈 디렉터리 + .gitkeep | `ls -R cloud-lab/` |
| A-1-2 | .gitignore 추가 — state, tfvars, secrets, .terraform, __pycache__ | cloud-lab/.gitignore | 금지 패턴 확인 |
| A-1-3 | cloud-lab/README.md — 디렉터리별 역할 설명 | README.md | 문서 확인 |

### A-2. 도구 버전 고정

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-2-1 | OpenTofu 버전 확정, 로컬 설치 확인 | `tofu --version` 출력 기록 | 버전 일치 |
| A-2-2 | AWS provider 버전 확정 (hashicorp/aws ~> 5.x) | required_providers 블록 | `tofu init` 성공 |
| A-2-3 | OS 이미지 확정 — Ubuntu 24.04 LTS AMI ID (ap-northeast-2) | variables.tf의 ami_id | AWS CLI로 AMI 존재 확인 |
| A-2-4 | Elastic Stack 버전 확정 (8.17.x) | toolchain.lock.json | 로컬 버전과 호환 확인 |
| A-2-5 | Suricata 버전 확정 (7.x) | toolchain.lock.json | PPA 설치 가능 확인 |
| A-2-6 | WordPress 6.x + PHP 8.3 + MySQL 8.4 호환 확인 | toolchain.lock.json | 공식 호환 매트릭스 대조 |
| A-2-7 | DVWA, CloudGoat 버전·commit hash 고정 | toolchain.lock.json | git ls-remote 확인 |
| A-2-8 | Velociraptor offline collector 버전·SHA-256 | toolchain.lock.json | 공식 릴리스 대조 |
| A-2-9 | Hayabusa, pySigma, SigmaHQ 규칙 버전 고정 | toolchain.lock.json | 릴리스 해시 대조 |
| A-2-10 | toolchain.lock.json 최종 작성 | cloud-lab/toolchain.lock.json | JSON schema 검증 |
| A-2-11 | THIRD_PARTY_NOTICES.md 초안 — 라이선스별 채택물 정리 | cloud-lab/THIRD_PARTY_NOTICES.md | 라이선스 종류 누락 없음 |

### A-3. OpenTofu Foundation 모듈

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-3-1 | backend 설정 — S3 + DynamoDB lock (Security 계정) | infra/foundation/backend.tf | `tofu init` 성공 (로컬 backend로 대체 테스트) |
| A-3-2 | provider 설정 — Security/Workload 두 계정 assume role | infra/foundation/providers.tf | `tofu validate` |
| A-3-3 | S3 증거 버킷 (staging + final) — versioning, encryption, lifecycle | infra/foundation/s3_evidence.tf | `tofu plan` 리소스 확인 |
| A-3-4 | S3 로그 landing 버킷 (WAF, ALB, Flow) | infra/foundation/s3_logs.tf | plan 확인 |
| A-3-5 | S3 state 버킷 + DynamoDB lock 테이블 | infra/foundation/s3_state.tf | plan 확인 |
| A-3-6 | KMS 키 3종 (workload-ebs, evidence-s3, evidence-ebs) + alias + policy | infra/foundation/kms.tf | plan에서 key policy 확인 |
| A-3-7 | CloudTrail — multi-region, management events, Security S3 전달 | infra/foundation/cloudtrail.tf | plan 확인 |
| A-3-8 | Budget 알림 — $200 경고, $250 위험, $300 상한 | infra/foundation/budget.tf | plan에서 SNS+Budget 확인 |
| A-3-9 | variables.tf — account_id, region, 공통 태그, operation_mode | infra/foundation/variables.tf | 변수 목록 검증 |
| A-3-10 | outputs.tf — 다른 모듈이 참조할 ARN/ID | infra/foundation/outputs.tf | output 목록 검증 |

### A-4. OpenTofu Lab 모듈 (Workload 계정)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-4-1 | VPC + 9개 서브넷 (10.60.0.0/16) + route table | infra/lab/vpc.tf | plan에서 CIDR 확인 |
| A-4-2 | Internet Gateway + NAT Gateway (count by operation_mode) | infra/lab/nat.tf | mode=setup일 때만 NAT 생성 |
| A-4-3 | SG 9종 (N01~N09) 정의 | infra/lab/security_groups.tf | 규칙 수·방향 검증 |
| A-4-4 | SSM endpoints 3종 (count by operation_mode) | infra/lab/endpoints.tf | mode=operate일 때만 생성 |
| A-4-5 | S3 gateway endpoint | infra/lab/endpoints.tf | 항상 생성 확인 |
| A-4-6 | ALB + target group + listener (HTTPS 443 → WEB 8080) | infra/lab/alb.tf | plan 확인 |
| A-4-7 | WAF WebACL + 관리형 룰 3종 + rate limit | infra/lab/waf.tf | plan에서 rule 확인 |
| A-4-8 | EC2 WEB — t3.medium, SG, IAM profile, user_data 참조 | infra/lab/ec2_web.tf | plan 확인 |
| A-4-9 | EC2 APP — t3.medium, SG, IAM profile, user_data 참조 | infra/lab/ec2_app.tf | plan 확인 |
| A-4-10 | EC2 SOC — t3.xlarge, SG, IAM profile, EBS 추가 | infra/lab/ec2_soc.tf | plan 확인 |
| A-4-11 | RDS MySQL 8.4 — db.t4g.micro, subnet group, parameter group, secret | infra/lab/rds.tf | plan 확인 |
| A-4-12 | Secrets Manager — DB 자격증명 | infra/lab/secrets.tf | plan 확인 |
| A-4-13 | IAM 역할 — EC2 instance profiles (WEB/APP/SOC), Lambda roles | infra/lab/iam.tf | plan에서 정책 문서 확인 |
| A-4-14 | variables.tf / outputs.tf | infra/lab/ | 완전성 검증 |

### A-5. OpenTofu Automation 모듈 (Security 계정)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-5-1 | EventBridge bus (ea-security-events) + 규칙 2종 | infra/automation/eventbridge.tf | plan 확인 |
| A-5-2 | Step Functions state machine (ASL JSON) | infra/automation/step_functions.tf + asl/collection.asl.json | plan 확인 |
| A-5-3 | Lambda 함수 5종 — 코드 placeholder + IAM role/policy | infra/automation/lambda.tf | plan에서 5개 함수 확인 |
| A-5-4 | DynamoDB 테이블 3종 (ea-cases, ea-dedup, ea-alert-queue) + GSI | infra/automation/dynamodb.tf | plan에서 테이블·GSI 확인 |
| A-5-5 | SSM 문서 — EA-VelociraptorOfflineCollect | infra/automation/ssm_documents.tf | plan 확인 |
| A-5-6 | IAM 교차 계정 — Security→Workload AssumeRole | infra/automation/iam_cross_account.tf | plan에서 trust policy 확인 |
| A-5-7 | S3 replication 규칙 — landing→Security archive | infra/automation/s3_replication.tf | plan 확인 |
| A-5-8 | variables.tf / outputs.tf | infra/automation/ | 완전성 검증 |

### A-6. Bootstrap 스크립트

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-6-1 | 공통 base — apt update, 시간대, auditd, 기본 보안 | bootstrap/base.sh | shellcheck 통과 |
| A-6-2 | WEB — Nginx 설치, Suricata 설치, NFQUEUE 설정, TLS self-signed | bootstrap/web.sh | shellcheck |
| A-6-3 | APP — Apache + PHP-FPM 8.3, WordPress 다운로드·기본 설정 | bootstrap/app.sh | shellcheck |
| A-6-4 | SOC — Elasticsearch + Kibana 설치, Fleet Server 설정 | bootstrap/soc.sh | shellcheck |
| A-6-5 | Agent 배포 — Elastic Agent 설치·Fleet 등록 (WEB/APP용) | bootstrap/agent.sh | shellcheck |
| A-6-6 | Velociraptor offline collector 설치 — /opt/ea-tools/ | bootstrap/velociraptor.sh | 해시 검증 포함 |

### A-7. 애플리케이션 코드

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-7-1 | WordPress wp-config.php 템플릿 (RDS/Secret 연동) | application/wordpress/wp-config.php.tpl | 변수 치환 확인 |
| A-7-2 | WordPress 감사 mu-plugin — 로그인·글·업로드·권한 변경 JSON 기록 | application/wordpress/mu-plugins/ea-audit.php | PHP lint |
| A-7-3 | Nginx 설정 — reverse proxy + Suricata NFQUEUE + real_ip | application/nginx/default.conf | nginx -t (구문 검증만) |
| A-7-4 | Suricata 설정 — NFQUEUE inline, EVE JSON, 선택 룰 SID 목록 | application/suricata/suricata.yaml + local.rules | 구문 검증 |
| A-7-5 | DVWA 분리 설정 — 별도 vhost, 별도 DB 사용자 | application/dvwa/ | 설정 파일 확인 |
| A-7-6 | 정상 데이터 seed SQL — 20 users, 50 posts, 20 media | application/wordpress/seed.sql | SQL 구문 확인 |

### A-8. 수집기·플레이북 초안

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-8-1 | 경보 수집기 — ES API 폴링·EventBridge 발행·커서 관리 | collectors/alert_collector.py | python -c import, mypy |
| A-8-2 | 경보 수집기 systemd unit 파일 | collectors/alert_collector.service | unit 구문 확인 |
| A-8-3 | metadata observer 초안 — EC2/SG/IAM 주기 조회·S3 저장 | collectors/metadata_observer.py | python -c import |
| A-8-4 | manifest JSON schema 정의 | collectors/schemas/manifest.schema.json | jsonschema 검증 |
| A-8-5 | 수집 플레이북 — collect_only 상태 정의 | playbooks/collect.json | JSON schema |
| A-8-6 | 격리 플레이북 — SG 교체·ALB 해제·SSM 유지 | playbooks/containment.json | JSON schema |
| A-8-7 | IAM 대응 플레이북 — session 취소·inline deny | playbooks/iam_response.json | JSON schema |
| A-8-8 | 복구 플레이북 — SG 복원·ALB 재등록·검증 | playbooks/recovery.json | JSON schema |

### A-9. Lambda 함수 코드

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-9-1 | ea-validate-case — 입력 검증·DynamoDB 중복 확인·대상 허용 확인 | infra/automation/lambda_src/validate_case/ | pytest |
| A-9-2 | ea-preserve-metadata — AssumeRole→Describe*→S3 저장 | infra/automation/lambda_src/preserve_metadata/ | pytest |
| A-9-3 | ea-collect-aws-logs — CloudTrail LookupEvents·S3 원본 참조·저장 | infra/automation/lambda_src/collect_aws_logs/ | pytest |
| A-9-4 | ea-trigger-host-collection — SSM SendCommand·상태 폴링·결과 기록 | infra/automation/lambda_src/trigger_host_collection/ | pytest |
| A-9-5 | ea-verify-finalize — SHA-256 검증·manifest 생성·staging→final 복사 | infra/automation/lambda_src/verify_finalize/ | pytest |
| A-9-6 | 공통 유틸 — S3 helper, DynamoDB helper, 로깅, 에러 처리 | infra/automation/lambda_src/common/ | pytest |
| A-9-7 | Lambda requirements.txt + 패키징 스크립트 | infra/automation/lambda_src/build.sh | 실행 확인 |

### A-10. 시나리오·테스트 프레임

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| A-10-1 | 정답 기록 JSON schema (run_id, target, expected_evidence) | scenarios/schemas/answer.schema.json | jsonschema |
| A-10-2 | S0~S6 시나리오 정의 파일 (공격 없는 구조만) | scenarios/S0.json ~ S6.json | schema 검증 |
| A-10-3 | 통합 테스트 프레임 — 수집기·Lambda 단위 테스트 구조 | tests/conftest.py, tests/test_*.py | pytest 구조 확인 |
| A-10-4 | 시작·중지·내보내기 스크립트 초안 | scripts/start.sh, stop.sh, export.sh, cleanup.sh | shellcheck |

---

## Phase B: 최소 인프라 구축 (A1~A2, B02~B04)

> 게이트: G1~G4 · 빌드: B02~B04  
> 목표: Security 계정 기반 + Workload 네트워크 + 정상 서비스 동작

### B-1. Security 계정 배포 (G1)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| B-1-1 | AWS 계정 2개 확인 — ID·크레딧·MFA | 계정 정보 기록 | 콘솔 로그인 |
| B-1-2 | `tofu apply` foundation — S3/KMS/CloudTrail/Budget | state 파일 | 리소스 생성 확인 |
| B-1-3 | CloudTrail 이벤트 도착 확인 (15분 대기) | S3 JSON 샘플 | 실제 파일 조회 |
| B-1-4 | KMS 키 상태 확인 — Enabled, 정책 검증 | CLI 출력 | `aws kms describe-key` |
| B-1-5 | Budget 알림 동작 확인 | SNS 구독 확인 | 이메일/알림 수신 |
| B-1-6 | Workload 테스트 역할로 증거 삭제 시도 → 거부 확인 | AccessDenied 로그 | CloudTrail 이벤트 |
| B-1-7 | G1 통과 기록 | results/G1.md | 증거 첨부 |

### B-2. Workload 네트워크 배포 (G2)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| B-2-1 | `tofu apply` lab — VPC/서브넷/route/SG/endpoints | state 파일 | 리소스 확인 |
| B-2-2 | SG 허용/거부 매트릭스 시험 — N01~N09 각각 | 연결 테스트 결과 | nc/curl 시험 기록 |
| B-2-3 | SSM 접속 확인 (테스트 EC2 → Session Manager) | SSM 세션 스크린샷 | 실제 접속 |
| B-2-4 | S3 gateway endpoint 동작 확인 | S3 CLI 결과 | private 서브넷에서 S3 접근 |
| B-2-5 | NAT/endpoint 모드 전환 시험 | `tofu plan` diff | mode 변수 변경 후 plan |
| B-2-6 | G2 통과 기록 | results/G2.md | 허용/거부 표 첨부 |

### B-3. 서비스 배포 (G3~G4, B03~B04)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| B-3-1 | RDS 생성 — subnet group, parameter group, secret rotation | RDS 인스턴스 | 연결 성공 |
| B-3-2 | DB 스키마·사용자 생성 (wordpress_user, dvwa_user, readonly_user) | SQL 실행 기록 | 권한 허용/거부 시험 |
| B-3-3 | WEB EC2 배포 + bootstrap 실행 — Nginx + Suricata | 인스턴스 running | curl 응답 |
| B-3-4 | APP EC2 배포 + bootstrap 실행 — Apache + PHP-FPM + WordPress | 인스턴스 running | WordPress 설치 화면 |
| B-3-5 | SOC EC2 배포 + bootstrap 실행 — Elasticsearch + Kibana | 인스턴스 running | Kibana 접속 |
| B-3-6 | WordPress 초기 설정 + seed 데이터 적재 | 20 users, 50 posts | 로그인·글 열람 확인 |
| B-3-7 | ALB → WEB → APP → RDS 전체 경로 동작 확인 | HTTP 200 응답 | 외부→ALB→WordPress 페이지 로드 |
| B-3-8 | TLS 확인 — ALB HTTPS + 내부 평문 | 인증서 정보 | openssl s_client |
| B-3-9 | S3 배치 데이터 업로드 (미디어 20개) | S3 객체 목록 | aws s3 ls |
| B-3-10 | WEB/APP 로그 파일 생성 확인 (Nginx/Apache/journal/auditd) | 로그 샘플 | tail 확인 |
| B-3-11 | G3~G4 통과 기록 | results/G3.md, results/G4.md | 증거 첨부 |

---

## Phase C: 로그 수집·탐지·공격 (A3, B05~B11)

> 게이트: G5 · 빌드: B05~B11  
> 목표: 모든 로그 SIEM 도착 + 탐지 규칙 동작 + 실제 공격 증거

### C-1. SIEM 수집 설정 (B05)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| C-1-1 | Fleet Server 설정 — SOC VM, enrollment token | Fleet UI 접속 | Agent 등록 가능 |
| C-1-2 | Agent 정책 — System + Suricata + Custom Logs | Fleet policy | 통합 목록 |
| C-1-3 | WEB/APP에 Agent 배포·등록 | Agent 2대 online | Fleet UI 확인 |
| C-1-4 | Elastic Defend 정책 설정 — 프로세스·파일·네트워크 | 정책 설정 | 이벤트 도착 |
| C-1-5 | AWS S3 input — WAF logs + ALB logs + VPC Flow | 통합 설정 | 인덱스 데이터 확인 |
| C-1-6 | SQS 큐 생성 + S3 이벤트 알림 연결 | SQS→Elastic 연결 | 메시지 처리 확인 |
| C-1-7 | CloudWatch Logs input — RDS + Route 53 | 통합 설정 | 인덱스 확인 |
| C-1-8 | CloudTrail S3 input | 통합 설정 | 인덱스 확인 |
| C-1-9 | ILM policy — hot 7일 → delete | 정책 설정 | `GET _ilm/policy` |
| C-1-10 | 소스별 원본↔ES 대조 — 10개 소스 각각 1건 이상 | 대조 결과표 | 타임스탬프·필드 비교 |
| C-1-11 | 수집 재처리 중복 확인 — Agent 재시작 후 중복 없음 | 테스트 결과 | doc count 비교 |

### C-2. 방어 계층 설정 (B06)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| C-2-1 | WAF WebACL 활성화 — Count 모드 시작 | WAF 콘솔 | 로그 도착 |
| C-2-2 | Suricata NFQUEUE inline 설정 — iptables 규칙 | WEB 설정 | `iptables -L` |
| C-2-3 | Suricata 규칙 다운로드 + alert 전용 초기 설정 | local.rules | EVE 이벤트 발생 |
| C-2-4 | auditd 규칙 — exec·설정 변경·파일 접근 | audit.rules | auditd 이벤트 확인 |
| C-2-5 | WordPress mu-plugin 배치 + 감사 로그 확인 | /var/log/wp-audit/*.json | 로그인 시 JSON 생성 |
| C-2-6 | 정상 canary 통과 확인 — 모든 방어 계층 활성 상태에서 정상 서비스 | HTTP 200 | 전체 경로 정상 |
| C-2-7 | 정책 hash 기록 — WAF/Suricata/auditd 규칙 버전 | 해시 목록 | sha256sum |

### C-3. 정상 기준선 (B07, S0)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| C-3-1 | S0 실행 — 30분 정상 부하 (로그인·글·업로드·열람·관리) | 트래픽 기록 | 시나리오 스크립트 |
| C-3-2 | 전 계층 로그 도착 확인 — Nginx/Apache/WP/journal/Suricata/Defend | 소스별 count | ES 쿼리 |
| C-3-3 | WAF/ALB/CloudTrail/Flow 로그 도착 확인 | S3 + ES 확인 | 시간 대조 |
| C-3-4 | 기준선 지연 측정 — 이벤트→ES 도착 시간 | 지연 분포 기록 | 타임스탬프 차이 |
| C-3-5 | 오탐 확인 — 탐지 규칙 없는 상태에서 의도치 않은 경보 0건 | 경보 count | Security 앱 확인 |
| C-3-6 | 수집 장애 시험 — Agent 중지 5분→복구 후 재수집 | 빈 구간 + 복구 기록 | 시간 gap 확인 |

### C-4. 공격 수행 (B08~B10, S1~S5)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| C-4-1 | DVWA 분리 배치 — 별도 vhost, 별도 DB, 별도 사용자 | DVWA 접속 가능 | 로그인 화면 |
| C-4-2 | S1 — DVWA SQLi (Count 모드) — 실제 DB 조회 성공 확인 | 쿼리 결과 증거 | HTTP 응답 + DB 행 |
| C-4-3 | S1 — WAF Block 전환 후 동일 요청 → 차단 확인 | WAF 로그 Block | 응답 403 |
| C-4-4 | S2 — 명령 실행 / 파일 업로드 — 실험 파일·프로세스 생성 | 파일 hash + ps 출력 | 호스트 증거 |
| C-4-5 | S3 — IPS drop 전환 후 동일 공격 → Suricata 차단 확인 | EVE drop 이벤트 | backend 미실행 확인 |
| C-4-6 | S3 — WAF Count 상태에서 IPS만 차단 대조 | 계층별 로그 비교 | 어디서 막혔는지 기록 |
| C-4-7 | S4 — CloudGoat ec2_ssrf 이식·SSRF→IMDS→role→S3 접근 | 실제 객체 읽기 성공 | CloudTrail 이벤트 |
| C-4-8 | S4 — 보안 설정 적용 후 동일 경로 차단 확인 | AccessDenied | CloudTrail 거부 |
| C-4-9 | S5 — 제한 역할 secret 열람·SG 변경·DB 접근 성공/거부 대조 | API 성공/거부 쌍 | CloudTrail 대조 |
| C-4-10 | 각 시나리오 정답 기록 작성 | scenarios/S1~S5_answers.json | schema 검증 |

### C-5. 탐지 규칙 배치 (B11, D01~D08)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| C-5-1 | D01 — WAF SQLi/known-bad 반복 (threshold rule) | 규칙 설정 | S1 재현 시 경보 |
| C-5-2 | D02 — 로그인 brute force + 성공 (threshold + EQL) | 규칙 설정 | 테스트 로그인 시 경보 |
| C-5-3 | D03 — 웹 shell + 파일/예약 변화 (EQL sequence) | 규칙 설정 | S2 재현 시 경보 |
| C-5-4 | D04 — Suricata high rule + drop | 규칙 설정 | S3 재현 시 경보 |
| C-5-5 | D05 — APP 역할 비정상 S3/secret 접근 | 규칙 설정 | S4/S5 재현 시 경보 |
| C-5-6 | D06 — SG/IAM/로깅 변경 | 규칙 설정 | S5 재현 시 경보 |
| C-5-7 | D07 — DB 비정상 스키마 접근 | 규칙 설정 | 비인가 쿼리 시 경보 |
| C-5-8 | D08 — Agent/IPS/canary 5분 단절 | 규칙/watcher | 의도적 중단 시 경보 |
| C-5-9 | TP/FP/FN 평가 — 각 규칙별 정답 대비 | 평가 결과표 | 정밀도·재현율 기록 |
| C-5-10 | 경보 alias API key 생성 (.alerts-security.* 읽기 전용) | API key | curl 테스트 |

---

## Phase D: 포렌식 파이프라인 (A4~A5, B12)

> 게이트: G6 · 빌드: B12  
> 목표: 경보→사건→증거 수집→검증→Atlas 시간축

### D-1. 자동화 인프라 배포

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| D-1-1 | `tofu apply` automation — EventBridge/StepFunctions/Lambda/DynamoDB/SSM | state 파일 | 리소스 확인 |
| D-1-2 | Lambda 함수 코드 배포 (ZIP 패키징) | S3 코드 버킷 | 함수 invoke 테스트 |
| D-1-3 | IAM 교차 계정 연결 확인 — Security→Workload AssumeRole | STS 결과 | assume-role 성공 |
| D-1-4 | S3 replication 규칙 활성화 + 복제 확인 | 복제 상태 | 양쪽 객체 대조 |

### D-2. 경보 수집기 배포

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| D-2-1 | SOC VM에 alert_collector.py 배포 + systemd 등록 | 서비스 running | systemctl status |
| D-2-2 | ES API key 생성 + 수집기 설정 | 환경 변수 | 경보 조회 성공 |
| D-2-3 | 수동 테스트 경보 발생 → 수집기가 EventBridge에 전달 확인 | EventBridge 이벤트 | CW Logs 확인 |
| D-2-4 | 중복 경보 처리 확인 — 동일 경보 재전송 시 DynamoDB 중복 거부 | dedup 테이블 항목 | 사건 1건만 |

### D-3. Step Functions 실행 검증

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| D-3-1 | high 경보 → 자동 사건 생성 → Step Functions 시작 | 실행 기록 | 콘솔 확인 |
| D-3-2 | ValidateInput → PreserveMetadata 단계 확인 | staging S3 pre-response.json | 파일 내용 검증 |
| D-3-3 | CollectAWSLogs — CloudTrail 원본 수집 확인 | staging S3 파일 | 이벤트 수·시간 범위 |
| D-3-4 | TriggerHostCollection — SSM 명령 실행·결과 업로드 확인 | staging S3 triage ZIP | 파일 크기·해시 |
| D-3-5 | VerifyIntegrity — SHA-256 검증·manifest 생성 | final S3 manifest.json | 해시 일치 확인 |
| D-3-6 | 전체 워크플로 READY 완료 확인 | DynamoDB ea-cases status=READY | 상태 확인 |
| D-3-7 | 부분 실패 시험 — 호스트 수집 실패 시 PARTIAL 상태 | ea-cases status=PARTIAL | missing 목록 확인 |
| D-3-8 | 중복 사건 거부 시험 | DUPLICATE 상태 | 수집 미실행 |

### D-4. Atlas 클라우드 어댑터

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| D-4-1 | Atlas classify() 확장 — JSON 형식 입력 지원 | dfir_graph/classify.py 수정 | 단위 테스트 |
| D-4-2 | cloudtrail_management 어댑터 | dfir_graph/adapters/cloudtrail.py | 샘플 JSON → 노드·관계 |
| D-4-3 | waf_log 어댑터 | dfir_graph/adapters/waf.py | 샘플 → 노드·관계 |
| D-4-4 | alb_log 어댑터 | dfir_graph/adapters/alb.py | 샘플 → 노드·관계 |
| D-4-5 | linux_triage 어댑터 (Velociraptor 오프라인 결과) | dfir_graph/adapters/linux_triage.py | 샘플 → 노드·관계 |
| D-4-6 | rds_log 어댑터 | dfir_graph/adapters/rds.py | 샘플 → 노드·관계 |
| D-4-7 | aws_config_snapshot 어댑터 | dfir_graph/adapters/aws_config.py | 샘플 → 노드·관계 |
| D-4-8 | case_manifest 어댑터 — Case/Job 노드 생성 | dfir_graph/adapters/case_manifest.py | manifest → Atlas DB |
| D-4-9 | case import CLI — `python -m dfir_graph import-case <path>` | __main__.py 서브커맨드 | 실제 사건 import 성공 |
| D-4-10 | 첫 AWS 사건 시간축 확인 — CloudTrail→WAF→ALB→호스트 연결 | 시간축 스크린샷 | 이벤트 순서·관계 확인 |

---

## Phase E: 대응·평가·종료 (A6~A7, B13~B14)

> 게이트: G7~G8 · 빌드: B13~B14  
> 목표: 격리/복구 실행 + AI 평가 + 증거 내보내기 + AWS 정리

### E-1. 대응 실행 (B13, S6)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| E-1-1 | S6 사건 선정 — high 경보 기반 | 사건 시나리오 | 정답 기록 작성 |
| E-1-2 | 증거 수집 완료 확인 (D-3 반복) | READY 상태 | manifest 확인 |
| E-1-3 | EC2 격리 실행 — SG 교체 + ALB 해제 | 변경 기록 | 새 연결 차단 확인 |
| E-1-4 | 기존 tracked connection 검증 — 연결 지속 여부 | 테스트 결과 | nc/curl 확인 |
| E-1-5 | OS 방화벽 보완 (tracked connection 대응) | iptables 규칙 | 차단 확인 |
| E-1-6 | IAM session 취소 실행 | revoke-sessions 결과 | 토큰 거부 확인 |
| E-1-7 | DB 계정 제한 | 권한 변경 기록 | 쿼리 거부 확인 |
| E-1-8 | SSM 관리 통신 유지 확인 | SSM 세션 | 격리 중 접속 가능 |
| E-1-9 | 복구 실행 — SG 복원·ALB 재등록·정상 트래픽 확인 | 복구 기록 | 서비스 정상 확인 |
| E-1-10 | 대응 전후 상태 before/after 보존 | S3 저장 | 파일 비교 |
| E-1-11 | EBS 스냅샷 cross-account 복사 (해당 시) | 스냅샷 ID | Security 계정 확인 |
| E-1-12 | G7 통과 기록 | results/G7.md | 증거 첨부 |

### E-2. Atlas 분석·AI 평가

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| E-2-1 | S6 사건 Atlas import — 전체 어댑터 실행 | 시간축 + 관계 그래프 | 노드·관계 수 확인 |
| E-2-2 | 시간축 검토 — AWS API·Linux·RDS·WAF 이벤트 정렬 | 시간축 스크린샷 | 순서·빈 구간 확인 |
| E-2-3 | 근거 묶음 확인 — CloudTrail-WAF-ALB trace 연결 | 관계 그래프 | 연결 경로 확인 |
| E-2-4 | AI 가설 생성 — 사건 맥락 프롬프트 | 가설 텍스트 | 근거 유무 확인 |
| E-2-5 | source coverage 계산 — 시나리오별 수집 완성도 | coverage 표 | 정답 대비 % |
| E-2-6 | 정답 비교 — TP/FP/FN 전체 | 최종 평가표 | 분모·표본 수 공개 |
| E-2-7 | AI 오류율 기록 (근거 없는 주장·잘못된 인과) | 오류 목록 | 수동 검증 |

### E-3. 내보내기·종료 (B14)

| # | 작업 | 산출물 | 확인 방법 |
|---|------|--------|----------|
| E-3-1 | 원본 증거 로컬 다운로드 (D:\DFIR_CASES\) | 로컬 파일 | manifest 해시 검증 |
| E-3-2 | Atlas 로컬 재열람 확인 — S3 없이 시간축·그래프 동작 | Atlas UI 스크린샷 | 오프라인 동작 |
| E-3-3 | 사건 결과표 작성 | results/final_report.md | 시나리오별 결과 |
| E-3-4 | 잔여 과금 목록 작성 | 비용 보고서 | AWS Cost Explorer |
| E-3-5 | lab 리소스 정리 — EC2/ALB/NAT/endpoints/RDS 삭제 | `tofu destroy` lab | 리소스 0건 |
| E-3-6 | Security 증거 S3 보존 확인 — foundation은 유지 | S3 버킷 존재 | aws s3 ls |
| E-3-7 | foundation 선택적 정리 (크레딧 소진 시) | 정리 기록 | 잔여 리소스 목록 |
| E-3-8 | G8 통과 기록 | results/G8.md | 증거 첨부 |
| E-3-9 | 최종 Git 커밋 — 모든 결과·설정·코드 | 커밋 | push |

---

## 요약 통계

| Phase | 작업 수 | 로컬/AWS | 예상 특징 |
|-------|---------|---------|----------|
| A (로컬 준비) | 59개 | 로컬 전용 | 코드 작성, AWS 비용 0 |
| B (최소 인프라) | 24개 | AWS 배포 시작 | compute 시간 소비 시작 |
| C (수집·탐지·공격) | 40개 | AWS 운영 | 가장 많은 compute 사용 |
| D (포렌식 파이프라인) | 22개 | AWS + 로컬 개발 | 자동화 핵심 |
| E (대응·평가·종료) | 22개 | AWS + 로컬 | 정리 포함 |
| **합계** | **167개** | | |

Phase A는 AWS 비용 없이 로컬에서 전부 진행 가능하다. 59개 작업 중 OpenTofu 모듈(A-3~A-5)과 Lambda 코드(A-9)가 가장 무거운 작업이다.

## 2026-09-11 로컬 보완 작업

- `infra/modules/bootstrap/main.tf`: EC2에 공통·역할 스크립트와 설정을 함께 전달하고 크기·셸 인용을 검증한다.
- `bootstrap/configure_wordpress.py`: 앱 전용 secret을 읽어 안전하게 PHP 설정을 작성한다. DB 사용자 생성·초기 데이터 적재는 B-3-2/B-3-6이다.
- `tests/test_local_runtime.py`: 실제 렌더링, 설정값 인용, 수집 상태 전이와 아카이브 구성을 회귀 검증한다.
- `scripts/validate_local.py`: AWS API 호출 없이 Python, Bash, OpenTofu 검증을 실행한다.
- `results/LOCAL_VALIDATION.md`: 로컬 검증 결과와 AWS에서 남은 확인 항목을 구분한다.

파일 작성과 `validate` 통과는 AWS `plan`/`apply` 및 G0~G8 통과를 뜻하지 않는다.

- `bootstrap/soc_disk.py`: EBS volume ID 확인, 기존 파일시스템 보존 및 다른 mount 거부.


## 로컬 검증 결과 연결

2026-09-11 실제 검사와 잔여 단계는 [results/LOCAL_VALIDATION.md](results/LOCAL_VALIDATION.md)에 기록했다. `requirements-dev.txt`, `LOCAL_DEVELOPMENT.md`를 추가했다. 표의 항목은 계획이며 파일 작성·문법 통과·AWS 동작 성공을 구분한다.
