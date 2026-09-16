# 현재 배포 기준과 수락 순서 — 2026-09-15

이 문서는 구현된 기준선의 운영 순서다. AWS 계정/프로필은 아직 없으며 아래 AWS 명령은 실행하지 않았다. 전체 구상 중 후속 기능은 마지막 표에 남겨둔다.

## 1. 실제 구성

Security/Workload 두 계정, 서울 리전. Workload VPC `10.60.0.0/16`의 **test-a 클라이언트 → 내부 ALB:443 → WEB:8080 → APP:8080 → RDS:3306**이다. 인터넷에서 바로 공격하는 구조가 아니다.

- WEB: Ubuntu 24.04, Nginx, ModSecurity v3/CRS(처음 DetectionOnly), Suricata(NFQUEUE 구성·초기 alert 규칙), Velociraptor.
- APP: Apache/PHP-FPM, WordPress 7.1, Host `dvwa.lab` 전용 DVWA 2.5 가상 호스트·별도 OS 사용자/DB 사용자. APP 8081 경로는 없다.
- RDS: MySQL 8.4 계열, 비공개·TLS 필수. 현재 리전에서 사용할 세부 엔진 버전은 배포 시 확인한다.
- SOC: Elasticsearch/Kibana/Fleet 8.19.20, TLS, 7일 로그 보존. 엔드포인트 Basic 라이선스에서 실제 가능한 기능을 확인한다.
- 선택 테스트 호스트: `enable_test_runner=true`일 때 t3.small, 공인 IP·인바운드 없음, SSM 전용. `/opt/ea/scenario_runner.py`와 ALB 신뢰 인증서가 전달된다. 기본 false.
- Security: CloudTrail 중앙 원본, 증거 staging/final S3, KMS, DynamoDB, EventBridge/SQS/Step Functions/Lambda.
- 설치 설정: Workload의 versioning S3 bootstrap bundle. VersionId와 SHA-256을 검증한 뒤 설치한다. user-data/설정 변경은 서버 교체를 유발할 수 있어 가동 중 plan을 확인한다.

AWS WAF는 기본 비활성이다. `setup`은 NAT, `operate`는 NAT 대신 단일 AZ의 interface endpoint **9개**, `idle`은 둘 다 제거한다. **idle은 EC2/RDS 정지가 아니다.** 기존 3개 endpoint 기준 견적은 사용하지 않는다. 월 730시간 가동을 가정하지 말고 WEB/APP/SOC/선택 TEST, RDS, ALB, NAT 또는 endpoint, EBS/S3/KMS/로그의 실제 기간을 합산한다. 총 $300 목표의 현재 지역 견적·크레딧 적용을 확인하기 전 apply하지 않는다.

## 2. 계정 입력 준비 (현재는 여기 이전)

리포지토리 루트에서 다음 명령은 AWS를 호출하지 않는다.

```powershell
python cloud-lab/scripts/prepare_deployment.py --example --output .runtime/deployment-example
```

생성한 JSON에 두 계정 ID, 메일, 프로필 이름, **Security의 실제 배포 IAM role ARN**, 검토한 Ubuntu 24.04 AMI를 채운다. 비밀번호/액세스 키는 넣지 않는다. 프로필 인증은 AWS CLI/SSO에서 관리한다. Workload `EADeployRole`은 생성되는 정확한 Security 주체 신뢰 정책과 IaC 배포에 필요한 권한을 계정 준비 시 부여한다. 신뢰 정책 생성은 권한 정책/역할 생성 완료를 의미하지 않는다.

```powershell
python cloud-lab/scripts/prepare_deployment.py --config .runtime/deployment-example/deployment.example.json --output .runtime/deploy-foundation
```

이때 foundation 입력만 생성하며 가짜 KMS/버킷 ARN으로 lab 입력을 만들지 않는다. `.runtime`은 Git 제외다. Windows 디렉터리 ACL도 운영자 계정으로 제한한다.

## 3. Foundation → Lab → Automation

1. `AWS_PROFILE`은 Security 프로필. 두 STS 계정 ID와 Workload assume-role을 확인한다. 배포 역할/서비스 quota/AMI·현재 견적·크레딧은 이 단계에서 실제 확인한다.
2. foundation은 최초 local state로 `tofu init -lockfile=readonly`, `tofu plan -var-file=<foundation.tfvars.json> -out=tfplan`을 실행한다. 생성/삭제/권한 범위와 비용을 검토한 저장 plan만 apply한다.
3. 생성된 state 버킷과 잠금을 확인하고 `backend.tf.example`을 `backend.tf`로 복사한다. `tofu init -migrate-state -backend-config=<foundation.backend.hcl>`로 이관 후 원격 state를 확인한다. 기존 환경이면 새 local state로 apply하지 않는다. state/backup에는 비밀값이 있어 Git에 넣지 않는다.
4. `tofu output -json`을 `.runtime/foundation-outputs.json`으로 저장한다. UTF-8로 저장한다. 입력 생성기를 새 출력 디렉터리로 실행한다:

```powershell
python cloud-lab/scripts/prepare_deployment.py --config .runtime/deployment-example/deployment.example.json --foundation-outputs .runtime/foundation-outputs.json --output .runtime/deploy-full
```

5. `scripts/start.sh`에 `EA_STAGE=lab`, `EA_TFVARS`와 `EA_BACKEND_CONFIG` **절대 경로**를 전달해 setup plan을 만든다. 스크립트는 apply하지 않는다. 설치가 끝날 때까지 setup 유지. `cloud-init status --wait`와 `/var/log/cloud-init-output.log`, `installed-*.tsv`, ALB target health를 확인한다.
6. automation도 별도 state와 입력으로 plan/apply한다. `collection_enabled=false`를 유지한다. foundation/lab/automation 출력은 각각 저장한다.

## 4. 서비스·SIEM 기동

APP SSM 세션을 이용한 RDS 원격 포트 포워딩(로컬 13306)을 먼저 연다. `scripts/initialize_database.py --help`에 따라 운영자의 **Workload 프로필**, 출력된 master/WordPress/DVWA secret ARN, 고정한 RDS CA를 지정한다. master secret은 APP에 전달하지 않는다. 그 다음 APP에서 `sudo php /opt/ea-bootstrap/application/wordpress/initialize.php`를 실행한다. 20명/50게시물을 재실행 가능하게 생성하며 관리자 비밀번호는 root 전용 파일에 있다. 미디어 20개 seed는 현재 구현하지 않았다.

DVWA 테이블은 배포 후 `Host: dvwa.lab`의 setup.php에서 초기화한다. 기본 impossible 정책을 유지하고 취약점 실험 세션에서만 수준을 바꾼다. 정상 WordPress에 의도된 취약 플러그인은 없다. WordPress/DVWA의 TLS 연결 패치는 **고정 upstream 파일** 대상으로만 적용하며 버전을 바꾸면 재검증한다.

SOC에서 `/opt/ea-bootstrap/siem/prepare.py --soc https://<SOC-private-IP> --ca <SOC-CA> --output <plan.json>`으로 계획을 확인한 뒤 `--apply --password-file /root/ea-credentials/elastic`을 지정한다. 새 SOC용 생성 절차이며 부분 적용 충돌을 자동 덮어쓰지 않는다. 실패 시 해당 API 결과와 이미 생성된 정책을 확인한다. 생성 직후 Linux malware detect·telemetry false를 API로 확인한다.

Fleet service token, ea-web-v1/ea-app-v1 등록 토큰을 발급하고 CA를 호스트에 배치한다. `bootstrap/agent.sh`의 필수 환경변수는 `FLEET_URL`, `FLEET_CA_FILE`, `AGENT_VERSION`, `AGENT_SHA512`다. Fleet 호스트는 `EA_AGENT_ROLE=fleet`과 FLEET_SERVER_* 값, WEB/APP은 `ENROLLMENT_TOKEN`을 사용한다. token은 Git/user-data에 넣지 않는다. **Agent 아카이브 checksum은 고정했으나 실제 Agent 등록·커널 이벤트 검사는 AWS 수락 작업**이다. NAT 제거 전에 패키지·Agent·정책 다운로드를 마친다.

SOC에서 `sudo bash /opt/ea-bootstrap/collectors.sh`로 경보/클라우드 로그 서비스를 설치한다. API key는 7일 만료이며 만료 전에 명시적으로 교체해야 한다. `systemctl status ea-alert_collector ea-cloud_logs`와 수집 지연/에러를 확인한다.

## 5. 원본·SIEM 대조 후 시나리오

CloudTrail(교차 계정), ALB, VPC flow 원본 S3와 RDS error/slowquery·Resolver DNS CloudWatch를 소스별 최소 1건씩 대조한다. 수집은 재전송 가능 방식이며 rollover를 넘는 완전한 exactly-once 보장은 없다. S3 기본 최근 2일, CloudWatch 최초 24시간/15분 중첩이므로 장기 중단·지연은 backfill 범위 검토가 필요하다. RDS slowquery는 모든 SQL 감사가 아니다.

S0~S3 실행기는 테스트 호스트에서 `/opt/ea/target.txt`의 주소와 `/opt/ea/alb.pem`을 사용한다. 기본은 계획 저장이며 `--execute` 때만 요청한다. `10.60.0.0/16` 밖 주소를 거부하고, 해석한 주소를 고정하며 리다이렉트를 따라가지 않는다. 최대 12회 요청이다. 각 실행은 새 output 파일을 쓴다. 상세 예상 결과는 `scenarios/S0.json`~`S6.json`을 따른다. HTTP 응답은 침해 성공이나 SIEM 탐지 증명이 아니다.

## 6. 증거 수집·반출

고정된 WEB/APP 대상의 수동 사건부터 확인한다. SSM collector 출력·원본 S3 VersionId·생산자/검증기 SHA-256을 대조한다. 지연/누락은 PARTIAL이어야 한다. 그 후에만 자동 수집을 활성화한다. high/critical EC2만 자동 사건 대상이며 나머지는 review SQS에 보존한다. 임의 host.id를 EC2 ID로 간주하지 않는다.

```powershell
python cloud-lab/scripts/evidence_bundle.py download CASE-EXAMPLE .runtime/cases/CASE-EXAMPLE --bucket <final-bucket> --profile <security-profile> --manifest-version <version>
python cloud-lab/scripts/evidence_bundle.py verify .runtime/cases/CASE-EXAMPLE
python -m dfir_graph --db .runtime/cases/example.sqlite cloud-import .runtime/cases/CASE-EXAMPLE
```

Atlas는 이 **오프라인 가져오기** 단계만 초기 구현했다. 부분 증거는 명시적인 `--allow-partial`이 필요하다. 객체 64MiB·사건 256MiB 검증 한도가 있으며 초과 시 staging을 보존하고 범위를 나눠야 한다. 메모리/대용량 worker는 없다. CloudTrail 원본·digest 파일은 보존하지만 digest 서명은 검증하지 않는다. 원본 전달 지연은 최소 30분 grace 범위와 실제 전달 상태를 대조한다.

## 7. 종료·잔여 비용

모든 사건과 PARTIAL 원본까지 목록을 만들어 로컬 반출·해시·재열람을 확인한다. `cleanup.sh`는 지정한 사건 **하나**만 검사하므로 전체 사건 보존을 대신하지 않는다. 그 뒤 automation → lab 순으로 destroy plan을 검토하고 적용한다. RDS 삭제 보호와 final snapshot 정책을 확인한다. foundation은 자동 삭제 대상이 아니다.

짧은 중지는 `session_control.py --outputs <lab-outputs> --profile <workload-profile> --account <workload-id> --action stop`의 계획을 보고 `--execute`로 요청한다. 선택 TEST도 포함한다. `idle` 전환은 별도 plan이다. 중지 후에도 ALB·디스크·스냅샷·S3·KMS·endpoint 등의 잔여 비용과 RDS 자동 재시작 조건을 확인한다. `cost_guard.py`로 프로젝트 시작일부터 두 계정의 크레딧 차감 전 누적 비용을 확인한다. 비용 데이터 지연 때문에 이것도 강제 지출 상한이 아니다.

## 후속 개발/실증

AWS 실제 로그 기반 Atlas 자원·IAM/STS 세션·호스트 관계 모델, RDS/ALB/DNS 사건별 증거 수집 확대, SIEM→Atlas 자동 전달, 메모리/대용량 수집, digest 서명 검증, 격리/IAM 취소/복구 실행 엔진, AI 평가가 남는다. 현재 containment/iam_response/recovery JSON은 설계다. 전체 킬체인 성공·완전 자동 포렌식으로 소개하지 않는다.

## 2026-09-16 시나리오 검토 반영

배포 전 [수정 결과](results/SCENARIO_FIXES.md)를 확인한다. 신규 RDS 고객 관리 키와 합성 S3 버킷/data event 비용을 포함한다. Lambda data event는 `scenario_lambda_arns`에 정확한 대상 목록을 넣은 경우만 생성한다. `audit_extra_regions`는 입력 생성기가 lab/automation에 동일하게 전달한다. 먼저 양 계정의 서울/글로벌 IAM canary를 원본과 SIEM에서 대조한다. S0~S6 준비 검사와 본 실험36개를 혼동하지 않는다.
