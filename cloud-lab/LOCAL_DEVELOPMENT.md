# AWS 배포 전 로컬 개발·검증

2026-09-11: 사용자가 AWS 계정·프로필을 아직 준비하지 않았으며 로컬 구현·검증부터 진행하도록 지정했다. AWS 리소스 생성, 실제 서버 설치, 공격 실행은 수행하지 않았다.

## 재현 방법

Python 3.12 이상, OpenTofu 1.9.0, Bash가 필요하다. Windows에서는 Git Bash의 `bash.exe`를 사용한다. 검증 도구는 PATH를 전역 변경하지 않고 경로로 지정할 수 있다.

```powershell
# evidence-atlas 디렉터리에서 실행
python -m venv .venv-cloud
.venv-cloud/Scripts/python.exe -m pip install -r cloud-lab/requirements-dev.txt
.venv-cloud/Scripts/python.exe -B cloud-lab/scripts/validate_local.py `
  --tofu 'C:/Tools/opentofu/tofu.exe' `
  --bash 'C:/Program Files/Git/bin/bash.exe' `
  --report cloud-lab/results/local-validation.json
```

`--tofu`의 경로는 설치한 위치로 바꾼다. OpenTofu는 공식 릴리스 checksum을 대조하고 설치한다. 이번에 확인한 Windows ZIP 해시는 `toolchain.lock.json`에 기록했다. Provider 버전과 배포 해시는 세 구성의 `.terraform.lock.hcl`로 관리한다. 이 잠금 파일은 커밋 대상이다.

검증 스크립트는 임시 복사본에서 실행한다. private tfvars, backend 설정, 원격 state와 실제 증거를 복사하지 않는다. Provider 최초 설치에는 공식 registry 다운로드가 필요하지만, AWS backend와 AWS API를 사용하지 않는다. Python AWS 통신은 테스트에서 차단한다.

검사 항목:

- OpenTofu format 및 foundation/lab/automation의 `init -backend=false`, `validate`.
- 실제 cloud-config 렌더링·gzip 크기, 모든 필수 설치 파일 전달, 설정값의 셸 인용.
- Bash 구문 검사, WordPress 비밀값의 PHP 데이터 직렬화, 관리자 DB 계정 거부.
- SOC 디스크 재실행 시 데이터 보존, 루트/분할/다른 파일시스템 거부.
- 서버 간 송신 규칙과 DB route·격리 SG 경계.
- SSM 대기·실패 처리, 확인 불가능한 대상 거부, 부분 수집을 READY로 올리지 않는 처리.
- 실제 Archive Provider로 Lambda ZIP 5개 생성·내용·import 검사. 이 fixture의 `plan`은 로컬 ZIP 데이터 소스만 포함한다. AWS 인프라 plan 검증과는 다르다.

## 인프라 입력과 상태 저장소

계정 ID·AMI·사용할 패치 버전은 임의로 채우지 않는다. `toolchain.lock.json`의 `status`는 `partial-local-validation`이며 남은 TODO를 완료로 해석하지 않는다. Elastic 8.17.0은 기존 호환성 후보를 유지했을 뿐, 현재 지원·보안 패치 검토가 완료된 버전이 아니다. Ubuntu APT 패키지는 서명된 저장소에서 설치하고 호스트의 `installed-*.tsv`에 실제 버전을 기록한다.

Foundation은 최초 S3 backend 자체를 만들기 위해 **처음에는 local state**를 사용한다. 계정 연결 후 foundation만 먼저 plan/apply하고, 생성된 `ea-tofu-state-<security-account-id>`와 KMS·DynamoDB를 확인한다. 그 다음 `infra/foundation/backend.tf.example`을 `backend.tf`로 복사하고, private backend 설정을 전달해 `tofu init -migrate-state`로 이동한다. 기존 원격 state가 있는 환경에서는 새 local state로 apply하지 말고 해당 backend를 먼저 연결한다. State와 백업에는 비밀값이 들어가므로 Git에 넣지 않는다.

Lab/automation은 private backend 설정의 실제 `bucket`, `key`, `region`, `dynamodb_table`, `encrypt`를 사용한다. 계정별 state key는 `foundation/terraform.tfstate`, `lab/terraform.tfstate`, `automation/terraform.tfstate`다. 필요에 맞는 backend profile/role도 설정한다. Security provider는 현재 인증 프로필의 계정을 검증하고 Workload는 `EADeployRole`을 assume한다. 이 배포 역할 생성과 크레딧 적용 확인은 AWS 계정 준비 단계다.

`scripts/start.sh [setup|operate|idle]`은 한 단계만 plan한다. `EA_STAGE=foundation|lab|automation`, `EA_TFVARS=<절대 경로>`, 이후 단계의 `EA_BACKEND_CONFIG=<절대 경로>`를 지정한다. 의존성이 있는 세 구성을 한 번에 plan하거나 `init -upgrade`로 lock을 바꾸지 않는다. 이 스크립트는 apply하지 않는다.

## 설치 및 운영 조건

EC2 설치 파일은 cloud-init의 `write_files`와 `runcmd`로 함께 전달한다. private IP를 받아 Nginx upstream을 생성하고 ALB의 HTTPS·trace 헤더를 전달한다. 문서 placeholder를 그대로 서버에 설치하지 않는다. [cloud-init 파일 전달](https://docs.cloud-init.io/en/latest/reference/yaml_examples/write_files.html)

WEB에서 Nginx가 연결을 종료하므로 Suricata는 ALB subnet의 INPUT/OUTPUT 8080을 검사한다. 일반 라우터의 FORWARD 경로를 사용하지 않는다. 초기 custom rule은 alert이며 drop 전환과 장애 시 fail-open 동작은 별도 검증한다. Suricata가 보는 원본 네트워크 주소는 ALB이므로 SID 9000006은 ALB별 집계이고 원래 클라이언트별 로그인 상관관계는 WAF/HTTP/SIEM에서 확인한다. [Suricata NFQUEUE 구성](https://docs.suricata.io/en/suricata-7.0.15/setting-up-ipsinline-for-linux.html)

APP 역할은 WordPress 전용 secret만 읽는다. DB 관리자 secret은 앱에서 읽을 수 없다. `wordpress_user`의 DB 생성·권한 부여는 B-3-2에서 별도로 수행해야 하며, 설치 완료 메시지는 웹사이트와 DB가 이미 정상 연결됐다는 뜻이 아니다. RDS는 TLS 연결을 요구하지만 클라이언트의 CA·호스트명 검증과 계정 권한은 실제 연결로 확인해야 한다. DVWA 분리 설치와 정상 데이터 seed도 남아 있다.

SOC는 지정한 EBS volume ID의 장치를 찾고 기존 ext4를 재사용한다. 임의 NVMe 첫 디스크를 고르거나 재실행 때 강제 포맷하지 않는다. ES·Kibana는 TLS와 Kibana service token을 사용하고 자격증명은 root 전용 파일에 보관한다. Fleet Server 정책·CA 배포·Agent 등록은 Phase C다. Agent 설치는 CA와 검증한 아카이브 해시가 필요하며 `--insecure`를 기본값으로 사용하지 않는다. [Elastic HTTPS 구성](https://www.elastic.co/docs/deploy-manage/security/set-up-basic-security-plus-https), [서비스 계정](https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/service-accounts)

`operate` 모드는 NAT를 없애므로 SSM 외에도 logs/SQS/EventBridge/Secrets Manager/STS/EC2 API endpoint를 제공한다. SSM endpoint SG와 일반 API endpoint SG를 분리해 격리 SG가 일반 API 접근까지 허용하지 않게 한다. 현재 단일 AZ에서 SSM 계열 3개 + 일반 API 6개, 총 9개 interface endpoint가 생성된다. 추가 6개의 비용을 기존 2~3개 기준 예산표에 반영해야 한다. 730시간 상시 보관을 가정하지 말고 실제 가동 시간을 곱해 총 $300 한도 내인지 AWS 준비 단계에서 다시 산정한다. `idle`은 endpoint/NAT 모드이며 EC2·RDS 중지를 의미하지 않는다.

## 자동 수집 활성화 전 남은 작업

`collection_enabled` 기본값은 false다. 다음 계약을 확인한 후 Phase D에서 활성화한다.

1. 생성한 Velociraptor offline collector의 CLI와 프로필·출력 경로를 SSM 문서에 맞추고, 실제 실행·해시·도구 manifest를 검증한다. 일반 upstream 바이너리의 이름을 바꾸는 것으로 offline collector가 되지 않는다.
2. WEB/APP의 AWS CLI 및 지정 staging prefix 업로드 권한, 교차 계정 S3 bucket/KMS 정책, 로그 복제와 SOC의 중앙 CloudTrail 읽기 권한을 연결한다.
3. S3/SQS·CloudWatch/Resolver·Elastic 통합 정책을 배치하고 소스별 실제 원본 한 건 이상과 SIEM 이벤트를 대조한다.
4. CloudTrail LookupEvents 결과는 API 조회 산출물이다. 원본 S3 로그·digest 수집과 source locator를 추가한다.
5. Manifest를 source/job/profile 계약 및 스키마에 맞추고 S3 version ID, 원본 제공 해시와 계산한 해시의 구분, 큰 파일 스트리밍, 부분 실패·재시도·중복의 원자성을 보완한다.
6. 실제 Linux 서비스의 `nginx -t`, `suricata -T`, PHP-FPM·Apache·ES·Kibana 검증, WAF/IPS/EDR의 로그·차단 시험, Atlas import 및 AI 평가를 수행한다.

`validate`와 모의 응답 테스트 통과는 위 항목을 대신하지 않는다. 진행표의 A0~A7 및 G0~G8을 근거 없이 완료 처리하지 않는다.
