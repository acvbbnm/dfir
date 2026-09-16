# AWS 관제·포렌식 자동화 — 전체 프로젝트 설계

> 2026-09-16 실행 기준: [시나리오 v1.1](scenarios/SCENARIO_LIBRARY.md)·[수정/지원 범위](results/SCENARIO_FIXES.md). 아래의 SQS·landing 복제·snapshot copy·host 없는 자동 사건·고급 상관·대응 실행기는 후속 목표이며 현재 구현 완료를 뜻하지 않는다. S0~S6는 준비 검사, N/W/H/C/I/D/E/X/K는 본 실험 ID다.


> **2026-09-15 구현/검증 대조:** 이 문서의 장기 목표와 과거 후보 구성을 현재 완료 상태로 해석하지 않는다. 현재 기준선은 [DEPLOYMENT.md](DEPLOYMENT.md), 수행된 검사는 [LOCAL_VALIDATION.md](results/LOCAL_VALIDATION.md)다. ModSecurity 기본·내부 ALB·선택 test-a 실행기·초기 Atlas 오프라인 import까지 준비했으며 AWS 수락/전체 분석·대응은 미완료다.

> 2026-09-11 구현 보완: [로컬 검증 기록](results/LOCAL_VALIDATION.md)과 [실행·잔여 작업](LOCAL_DEVELOPMENT.md)을 확인한다. 현재 operate 모드는 SSM 계열 3개 + 일반 API 6개로 interface endpoint 총 9개다. 이전 2~3개 기준 비용표는 현재 IaC의 확정 견적이 아니며 실제 단가·실행 시간으로 재산정해야 한다. AWS 배포는 아직 수행하지 않았다.


작성일: 2026-09-09 · 버전: 설계안 0.3 · 상태: 인프라 재설계, AWS 배포 전

서비스와 방어 인프라부터 구축한 뒤 실제 정상·공격 로그를 SIEM으로 관리하고, 선정 사건의 포렌식 조사로 연결한다. Windows 아티팩트 수집을 선행 목표로 삼았던 0.2안의 서버·DB·시나리오 결정을 교체한다.

서버·서비스·DMZ·통신 정책·WAF/IPS/EDR·로그·경보·B00~B14 실행 순서는 [BUILD_AND_ATTACK.md](BUILD_AND_ATTACK.md)가 상세 기준이다. 증거·계정 경계는 [CLOUD_FORENSICS.md](CLOUD_FORENSICS.md), OSS 검토는 [OPEN_SOURCE.md](OPEN_SOURCE.md)를 따른다. 문서 작성은 구축·시험 완료를 의미하지 않는다.

## 1. 목표와 완료의 의미

1. WordPress 기반 회원·게시판·자료실을 실제 구동하고 RDS에 데이터를 저장한다.
2. DMZ·APP·DB·관리·실행기 구간의 허용·거부를 검증한다.
3. WAF 요청 차단, Suricata inline 패킷 차단, endpoint 탐지, IAM·DB 권한 제한을 구분해 설정한다.
4. 서비스·방어·AWS 로그를 중앙 수집하고 SIEM 규칙·대시보드·경보를 검증한다.
5. DVWA 웹 취약점과 CloudGoat 기반 AWS 권한 악용을 직접 수행해 실제 성공·차단·실패를 기록한다.
6. 선정 경보를 사건으로 만들고 AWS 원본 로그·구성·객체·필요한 EC2/RDS 증거를 보존한다.
7. Atlas가 시간축·관계 근거·공백을 보여주고, 로컬 AI의 가설을 사람이 원본으로 검토한다.
8. 격리·권한 제한·복구·내보내기·잔여 과금까지 검증한다.

공격 성공은 실제 응답·데이터·프로세스·파일·권한 변화로 판정한다. 경보 발생과 공격 성공, 알림 발송과 차단 성공을 각각 구분한다.

## 2. 기본 결정과 범위

| 항목 | 기본안 |
|---|---|
| 예산 | 총 $300 상한 목표, 1차 $200~250 계획 범위 |
| 수명 | 1개월 보관/네트워크, 핵심 EC2·RDS 각 최대 100시간 |
| 계정 | Workload / Security-Evidence 2계정 권장, 크레딧 적용 확인 |
| 리전 | 서울, 서비스 단일 리전·CloudTrail multi-region |
| WEB | Ubuntu·Nginx·Suricata NFQUEUE |
| APP | Ubuntu·Apache·PHP-FPM·WordPress |
| DB | private RDS MySQL 8.4 계열, Single-AZ |
| 실험 | DVWA 별도 가상호스트/OS·DB 사용자, CloudGoat 단기 전용 APP |
| 관제 | Workload private EC2의 Elasticsearch·Kibana·Fleet |
| endpoint | EC2의 Elastic Agent/Defend·auditd, RDS에는 설치 안 함 |
| 관리 | SSM, 최소 IAM 역할, API/정책 변경 감사 |
| 분석 | 로컬 Evidence Atlas·Ollama, AWS 원본별 어댑터 확장 |
| 원본 | 서비스별 landing → Security archive, CloudTrail은 Security 직접 전달 |
| 대응 | EventBridge·Step Functions·Lambda·SSM, 수집/격리/권한 제한 분리 |
| 규모 | 실행 노드 단일 AZ, ALB·DB subnet group은 2개 AZ |

기본 공격 대상은 사설망의 내부 ALB와 허용된 실험용 AWS 리소스다. 공개 서비스 시연은 정상 트래픽용 별도 노출 정책으로 다룬다. Linux로 바꾸는 것 자체가 클라우드 보안 설계는 아니다. IAM·STS·S3·Secrets Manager·RDS의 서로 다른 접근·로깅·보존 경계가 필수 조사 대상이다.

## 3. 전체 구성

~~~mermaid
flowchart TB
    U["정상 사용자 / 공격 실행기"] -->|"HTTPS"| ALB["Internal ALB"]
    WAF["AWS WAF · 선택 비활성"] -. "정책 연결" .-> ALB
    ALB --> WEB["DMZ: Suricata inline · Nginx"]
    WEB --> APP["APP: WordPress / 분리한 실험 앱"]
    APP -->|"TLS"| DB["RDS MySQL"]
    APP --> SM["Secrets Manager"]
    B["자료 배치 역할"] --> DATA["업무 S3"]
    LOG["WAF·ALB·Flow·DNS·CloudTrail"] --> S3["로그 S3 / Security archive"]
    DB --> CW["CloudWatch Logs"]
    WEB -. "EVE·OS·웹" .-> ES["Elastic SIEM"]
    APP -. "앱 감사·Defend·OS" .-> ES
    S3 -->|"polling 수집기 (SQS 후속)"| ES
    CW --> ES
    ES --> CASE["Security: 사건·수집·대응"]
    CASE --> EVID["증거 S3 · 구성 이력<br/>선택 EBS/RDS snapshot copy"]
    EVID --> ATLAS["Evidence Atlas · 로컬 AI · 분석가"]
~~~

사용자가 제시한 images.jpg의 중앙 로그 수집 구조를 적용한다. AWS 서비스 로그와 finding을 구분해 수집하고 중앙 원본·정규화·SIEM을 연결한다. 기본 SIEM은 Elastic 하나다. 참고 그림의 OpenSearch용 Lambda·대시보드를 그대로 Elastic 호환으로 간주하지 않는다.

## 4. 서비스·네트워크·방어

### 4.1 서버와 서비스

WEB t3.medium/20GB, APP t3.medium/30GB, SOC t3.xlarge/100GB, RDS db.t4g.micro/20GB로 시작한다. APP은 회원·게시·자료 업로드를 제공하고 별도 자료 배치가 지정 S3 prefix에 게시글/자료를 내보낸다. DB secret은 Secrets Manager에서 제한된 역할로 읽는다.

정상 WordPress와 DVWA는 OS 사용자·가상호스트·DB 스키마·계정을 분리한다. CloudGoat의 취약 IAM/SSRF 실험은 별도 단기 인스턴스·role에서 수행한다. 정상 서비스와 실험용 취약 설정을 실행 기록에서 구분한다. 프로그램·AMI·도구·룰 버전과 해시는 배포 전에 잠근다.

### 4.2 DMZ와 통신

VPC 10.60.0.0/16 내 ingress(2AZ)·WEB DMZ·APP·DB(2AZ)·관리·test·forensic·scenario-app 서브넷을 둔다. subnet 명칭이 아닌 SG 허용 목록으로 격리를 구현한다.

필수 통신은 test→ALB443→WEB8080→APP8080→RDS3306/TLS다. test/WEB→RDS, test→APP 직접 연결을 거부한다. Agent는 SOC9200/8220 TLS로, 관리 대상은 SSM443으로 연결한다. DB subnet은 IGW/NAT 기본 경로가 없다. 설치/API용 NAT 1개, S3 gateway endpoint, ssm/ssmmessages interface endpoints를 둔다.

HTTPS는 내부 DNS·인증서 신뢰까지 구현한다. ALB 뒤 실험 HTTP 구간은 IPS 본문 검사를 위한 명시적 평문 구간이며 운영 민감 데이터 환경의 완성된 전송 암호화로 평가하지 않는다.

### 4.3 방어 정책

| 통제 | 검사/허용 조건 | 실행·검증 |
|---|---|---|
| ModSecurity/CRS 기본 | CRS + Nginx Host/경로/로그인 rate | DetectionOnly→On, backend 미도달 대조; AWS WAF는 선택 비교 |
| DMZ/SG | 계층별 source SG와 필요한 포트만 허용 | 정상 흐름 성공·우회 직접 연결 거부 |
| Suricata IPS | WEB의 ALB HTTP 양방향을 NFQUEUE로 전달 | alert→선정 drop, EVE verdict·정상 서비스·센서 장애 시험 |
| endpoint | 웹 계보·파일·cron/systemd·접속 변화 | Agent/Defend·auditd, 실제 가용 기능과 정상 대조군 |
| 앱 | 최소 OS/웹 권한, 정상 uploads 실행 금지, 감사 이벤트 | 로그인·권한·파일 변화와 권한 거부 |
| IAM | 지정 secret/object·작업만 허용, 기본 IMDSv2 | 정상 허용·다른 자원 접근 거부, 실험 role 별도 |
| DB | 스키마별 사용자·TLS·비관리자 앱 계정 | DB 연결·실제 SQL·TLS·권한 거부 |
| evidence | Security 소유 버킷/키·삭제 권한 분리 | 다른 workload role의 수정/삭제 거부 |

Suricata 기본안은 웹 경로의 host inline IPS이며 VPC 전체 경계 IPS가 아니다. 전용 AWS Network Firewall은 검사 subnet·대칭 routing·별도 비용을 검증하는 단기 비교 단계다. 탐지와 실제 차단을 같은 기능으로 표시하지 않는다.

## 5. 로그 수집과 관제

### 5.1 수집 계약

WAF/ALB/Flow와 CloudTrail은 원본 S3를 수집하고 현재 polling·중복 방지·실패 시 커서 유지로 처리한다(SQS 전달은 후속 목표). RDS 엔진 로그와 Resolver DNS는 CloudWatch Logs에서 읽는다. WEB/APP의 HTTP·앱 감사·Suricata EVE·OS/Defend 이벤트는 Agent로 전달하고 조사용 원본을 별도로 보존한다.

CloudTrail management는 IAM/STS·Secrets·SG·RDS API를, 선택한 S3 data event는 객체 접근을 다룬다. SQL은 RDS 엔진 로그, OS 실행은 endpoint 로그가 담당한다. 소스별 미수집 범위·전송 지연·rotation을 표시한다.

ES 7일/용량 한도, 운영 원본 30일/상한, 선정 사건 별도 보존을 초기값으로 한다. CloudWatch cursor·eventId·겹침 재조회·late arrival와 S3 bucket/key/version·내용 hash를 보존한다. 원본 수정 없이 파생 정규화를 만든다.

### 5.2 SIEM 및 경보

기존 Elastic과 호환되는 지원 버전·AWS/Suricata/System/Defend 패키지를 함께 고정한다. 최신 통합 패키지가 기존 ES/Kibana 8.x에서 동작한다고 가정하지 않는다. Basic 기능과 유료 endpoint 대응은 설치 환경에서 구분한다.

BUILD_AND_ATTACK.md의 D01~D08은 WAF 반복, 로그인 실패 후 성공, 웹 계보와 파일 변화, IPS drop, 잘못된 object/secret 접근, IAM/SG 변경, DB 변화, 수집 장애를 다룬다. 규칙의 실제 필드·정상 기준선·TP/FP/FN·처리 지연을 검증한다.

WAF·IPS는 inline 차단을 수행하고 SIEM은 상관·사건 판단을 담당한다. WAF의 S3 전달을 기다려 실시간 요청 차단을 구현하지 않는다. AWS 경보는 host가 없어도 사건으로 만들어야 한다. 호스트 격리와 역할 권한 제한은 별도 플레이북이다.

### 5.3 중앙 수집 그림의 적용

[SIEM on Amazon OpenSearch Service](https://github.com/aws-samples/siem-on-amazon-opensearch-service)의 source별 수집·정규화·대시보드 구성을 검토한다. 원본 S3·처리 계층·조회 인덱스 분리 원칙을 활용한다. Security Hub·GuardDuty·Firehose·GeoIP·SNS는 필요한 소스·평가·수신처가 있을 때 추가한다. 이 서비스들이 모두 기본 비용에 포함되어 있거나 이미 배포되었다고 표시하지 않는다.

## 6. 경보 연동과 사건 모델

### 6.1 유료 커넥터를 필수로 두지 않는 연동

SOC VM의 경보 수집기가 제한된 ES API key로 지정한 Kibana space의 alert alias를 읽는다. 초기 주기는 30초다. EventBridge PutEvents로 자체 이벤트를 발행하며, EventBridge가 Elastic의 경보를 자동으로 발견한다고 가정하지 않는다. [Elastic 경보 alias 조회](https://www.elastic.co/docs/solutions/security/detect-and-alert/query-alert-indices)

- 경보 UUID, rule ID, space, 탐지 시각, 원본 문서 참조를 보존한다.
- 커서와 겹치는 조회 구간을 사용하고 재시작 후 누락 여부를 대조한다. 페이지 제한으로 경보가 누락되지 않게 한다.
- DynamoDB 조건부 쓰기로 space + alert UUID + playbook version의 중복 실행을 제어한다.
- 재시도되는 AWS API 작업도 기존 command/snapshot/job ID를 먼저 확인한다. 워크플로 엔진의 실행 보장만으로 모든 외부 작업이 중복 방지된다고 가정하지 않는다.
- 경보 원문과 사건 생성 판단은 다른 객체로 보존한다.

### 6.2 사건과 수집 요청의 계약

아래 JSON은 구조 예시이며 실제 계정·호스트 ID가 아니다.

~~~json
{
  "schema_version": "1.0",
  "case_id": "CASE-20260909-001",
  "trigger": {
    "source": "elastic-security",
    "space_id": "default",
    "alert_id": "example-alert-uuid",
    "rule_id": "example-rule-uuid",
    "raw_alert_object": "s3://evidence-bucket/cases/CASE-20260909-001/trigger.json"
  },
  "target": {
    "account_id": "EXAMPLE_ACCOUNT",
    "region": "ap-northeast-2",
    "instance_id": "i-EXAMPLE",
    "host_id": "example-host-id"
  },
  "window": {
    "start_utc": "2026-09-09T01:00:00Z",
    "end_utc": "2026-09-09T01:30:00Z"
  },
  "collection_profile": "aws-case-v1",
  "response_mode": "collect_only",
  "playbook_version": "1.0"
}
~~~

원본 사건 시각을 적재 시각으로 대체하지 않는다.

조사 범위는 경보 전후 15분을 초기값으로 시작하고 늦은 로그를 재조회한다. JSON의 target은 EC2 사례 예시다. 실제 계약은 account/region/resource_type/resource_arn을 사용하며 IAM·S3·Secrets·RDS 사건에는 instance_id/host_id가 없어도 유효하다. AWS 원본을 host 형식에 억지로 맞추지 않는다.

WAF 경보처럼 대상 host가 확인되지 않으면 클라우드 로그 중심 사건만 생성한다. backend를 IP·시간 유사성만으로 골라 자동 격리하지 않는다. 호스트 ID·EC2 메타데이터·당시 ALB target 관계를 통해 대상을 확인한 경우에만 호스트 수집으로 확장한다.

### 6.3 관계를 연결하는 키

| 대상 | 식별 기준 | 주의점 |
|---|---|---|
| AWS 호스트 | account + region + instance_id | IP 재사용과 중지·시작 후 변경 고려 |
| OS 호스트 | host.id, 수집 도구의 machine 정보, 등록 시 EC2 매핑 | 단말 보고값과 AWS 제어 영역 기록을 대조 |
| HTTP 요청 | 요청 ID와 trace ID의 전파·기록, target 정보 | WAF request ID와 ALB trace ID를 동일 값이라고 가정하지 않음 |
| 프로세스 | host + ProcessGuid/entity ID, 또는 PID + 시작 시각 + 부팅/세션 정보 | PID 단독 연결 금지 |
| 계정 | SID/UID, 호스트·도메인 범위 | 같은 이름의 다른 계정 구분 |
| 파일 | 호스트·수집 범위·경로·해시 및 관찰 시각 | 같은 경로만으로 같은 파일 확정 금지 |
| 증거 | case + collection job + 원본 파일 SHA-256 | 수집 파일, 파싱 결과, 원본 행 ID를 역추적 |

ALB가 추가·갱신하는 X-Amzn-Trace-Id를 WEB과 APP에서 기록한다. client가 제공한 값이 보존될 수 있으므로 trace 값 하나를 신뢰 근거로 삼지 않는다. CloudTrail·WAF·APP의 다른 식별자 간 대응은 실제 샘플에서 확인한 매핑만 구현한다. [ALB 요청 추적](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-request-tracing.html)

## 7. 증거 수집과 보관

### 7.1 수집 단계

Step Functions Standard가 다음 작업을 관리한다. 실행 상태와 각 외부 작업의 ID를 사건 기록에 남긴다.

1. 사건 생성, 입력 검증, 중복 요청 확인.
2. AWS 계정·리전·Project·허용 resource ARN/type·프로필 확인. EC2가 필요한 작업에만 instance ID 요구.
3. 역할/session·정책·S3 객체/version·secret metadata·RDS 설정과 관련 EC2/ENI/EBS/SG를 변경 전 보존. Security 제어 역할이 제한된 Workload 역할로 조회한다.
4. AWS 로그·객체 원본을 보존하고 필요할 때 EC2 휘발 정보/EBS 또는 RDS 엔진 로그/DB snapshot 수집으로 분기한다.
5. EC2에는 Linux triage, RDS에는 서비스 API·엔진 로그 프로필을 사용한다. Windows/KAPE는 후속 선택 경로다.
6. 각 작업의 완료·타임아웃·부분 실패 확인. 스냅샷 요청 접수와 완료를 구분.
7. Security staging으로 업로드하고 별도 크기 제한 worker에서 전체 해시를 재계산해 manifest를 작성한다. 대용량 ZIP 전체를 Lambda 한 번에 처리하지 않는다. EBS는 Security 소유 키로 snapshot copy 완료를 확인한다.
8. 증거 준비 완료를 기록하고 로컬 분석기에서 내려받을 수 있게 함.

상태는 RECEIVED → VALIDATED → COLLECTING → READY/PARTIAL/FAILED → ANALYZING → REVIEW_REQUIRED → CLOSED로 관리한다. 격리 상태는 사건 처리 상태와 별도 필드로 기록한다. 부분 수집은 실패 목록을 표시하고 성공한 자료만 우선 분석할 수 있게 한다.

### 7.2 AWS 서비스 프로필

- IAM/STS: role/session·trust·정책·CloudTrail 원본과 변경 전후 상태.
- S3: 지정 object/version·metadata·실제 수집 내용의 hash·접근 data events.
- Secrets Manager: secret ARN/version metadata·접근 감사. 비밀 값의 일괄 수집은 하지 않는다.
- RDS: DB identifier/resource ID·parameter/option group·SG/KMS·엔진 CloudWatch 로그·선택 manual snapshot. guest OS 수집·EBS 마운트를 적용하지 않는다.
- 암호화 RDS snapshot은 고객 관리 키와 제한 공유를 사용하고 Security 소유 키로 copy 완료를 확인한다. 분석이 필요하면 별도 RDS로 복원하며 EBS 분석 VM에 연결하지 않는다. [RDS snapshot 공유](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_ShareSnapshot.html)
- Windows EVTX/KAPE는 기존 지원 자산으로 유지하되 초기 AWS 인프라·첫 사건의 필수 조건에서 제외한다.

### 7.3 Linux 프로필

초기에는 고정한 Linux Velociraptor profile로 WEB/APP의 journal/auth/auditd·웹 로그·프로세스·연결·지정 변경 파일을 수집한다. RDS는 이 호스트 프로필의 대상이 아니다. auditd는 필요한 규칙부터 도입한다. Linux 전용 아티팩트는 KAPE 지원을 가정하지 않으며, Atlas 어댑터와 시간 의미 검증을 별도로 구현한다.

### 7.4 스냅샷에서 증거까지

EBS 스냅샷은 EBS 서비스에 보존되는 디스크 시점 복사본이다. 사용자 S3 증거 버킷에 자동으로 파일 형태가 생기지 않는다. 증거 버킷에는 snapshot ID, volume ID, 생성·완료 시각, KMS 정보와 관련 사건을 기록한다.

Workload의 스냅샷은 고객 관리 키를 사용하고 Security 계정 소유 키로 복사 완료해야 독립 보관으로 표시한다. 기본 분석은 로컬 triage 원본부터 수행한다. 디스크 분석할 때만 선택한 분석용 스냅샷 복사본으로 새 볼륨을 만들어 같은 AZ의 임시 분석 VM에 연결한다. Workload의 forensic subnet 분석기는 계정 전체 관리자 탈취에 대한 독립 분석 환경이 아니며 이 한계와 Security 임시 분석 환경 확장 조건은 CLOUD_FORENSICS.md 7.2를 따른다. 운영 원본 볼륨을 분석기에 직접 연결하지 않는다. 자동 마운트·쓰기 동작을 통제하고, 분석용 복사본을 읽기 전용으로 접근했는지 작업 이력으로 남긴다. 추출한 아티팩트는 해시를 계산해 S3 증거에 보관한다.

EBS 스냅샷은 RAM·instance-store 전체·S3 객체·DB 서비스 상태를 통합한 시스템 스냅샷이 아니다. 실행 중인 파일시스템의 일관성과 수집 도구가 남긴 변경을 기록한다. SSM 불통일 때 디스크 수집이 성공해도 휘발 정보 누락을 명시한다.

### 7.5 보관 형식과 무결성

~~~text
evidence-bucket/
  cases/CASE-.../
    trigger.json
    metadata/pre-response.json
    jobs/JOB-.../
      raw/
      parsed/
      manifest.json
      collection-log.jsonl
    snapshots.json
    analysis/
    response/
    report/
~~~

manifest에는 case/job/host/scope, 수집 시작·종료, 원본 경로, 파일 크기, SHA-256, S3 version ID, 도구·설정·파서 버전, 수집 오류를 넣는다. 원본 로그 시각, 수집 시각, 적재 시각을 분리한다. S3 ETag를 파일 SHA-256으로 사용하지 않는다.

버킷은 외부 공개를 차단하고 TLS·암호화를 사용한다. raw AWS 로그 버킷은 소스별 prefix와 서비스 쓰기 권한을 분리하며, WAF용 버킷 이름은 요구되는 aws-waf-logs- 접두사를 따른다. 증거 버킷은 Versioning, 고유 객체 키, 삭제 권한 분리와 사건별 보존 기록을 기본으로 한다.

endpoint의 수집 역할은 자기 업로드 범위에 쓰기만 허용하고, 기존 증거 삭제·전체 증거 조회 권한은 부여하지 않는다. 수집 대상이 이미 침해되었을 수 있으므로 endpoint가 계산한 해시만으로 내용의 진실성까지 보증하지 않는다. AWS 제어 영역 기록·스냅샷·독립 검증 해시를 함께 확인한다.

Object Lock은 후속 보존 정책 실험으로 둔다. 제한된 예산의 기본 배포에 해제 불가능한 장기 Compliance 보존을 설정하지 않는다. 보존 잠금을 추가하면 종료 시점 비용과 삭제 가능 시점을 문서화한다. [Object Lock 동작](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)

## 8. Evidence Atlas와 AI 개발

### 8.1 현재 상태와 선행 작업

실제 개발 위치는 C:/Users/SBA_USER/Desktop/evidence-atlas이며 GitHub 저장소는 https://github.com/sasumm25-lab/dfir 이다. siem-project/dfir-graph는 이전 경로다.

현재 문서에서 확인되는 자산은 KAPE CSV 적재, 원본·해시 보존, 시간축·관계 그래프, Sigma 엔진, SQLite→ES 동기화, 로컬 AI 연결 코드다. AWS 경보 연동, 원격 수집, CloudTrail/WAF 원본 어댑터, 다중 호스트 상관은 이번 계획의 개발 범위다.

현재 README가 기록한 Sysmon 시간축 오류와 MFT/USN 검색 연결 문제는 별도 회귀 보완으로 추적한다. AWS 구축을 Windows 수집 완성에 종속시키지 않는다. DESIGN.md 안에도 Phase 4 완료/미완료 표현이 섞여 있으므로 실제 통합 시험 결과로 정리한다. 기존 75개 단위 테스트 기록만으로 새 클라우드 흐름이 검증되었다고 판단하지 않는다.

### 8.2 추가할 기능

| 기능 | 결과 |
|---|---|
| 사건 가져오기 | manifest 검증, 경보·호스트·수집 범위 등록 |
| 외부 도구 결과 | Linux collection 계보·Suricata/Sigma 탐지 locator, Windows 외부 파서는 후속 선택 |
| 클라우드 로그 어댑터 | WAF/ALB/CloudTrail 원본과 파싱된 관계를 함께 보존 |
| Linux·RDS 어댑터 | WEB/APP 로그와 RDS CloudWatch 원본·resource/time 연결 |
| 다중 호스트 식별 | instance/host/ENI/IP의 유효 기간과 출처 표시 |
| 사건 시간축 | 전체 시간순 화면, 호스트별 구간, 경보 위치, 수집 공백 |
| 관계 탐색 | 선택 이벤트 주변 관계, edge basis, 원본 행·파일 이동 |
| 분석가 검토 | 메모·가설 상태·증거 인용·검토 이력 |
| 결과 내보내기 | Markdown/JSON 보고서와 사건 요약 |

CloudTrail/WAF JSON을 CSV로 바꾸면서 원본을 버리지 않는다. 원본 JSON 파일·객체의 해시와 record locator를 별도로 보존하고, 새 입력 어댑터에서 그 계보를 유지한다. 지원하지 않는 형식은 미지원으로 명시한다.

현행 Atlas의 최상위 원칙을 유지한다: raw_json 보존, time_kind 의미 보존, C/VSS 및 사건 범위 분리, 인과 확정 금지. 신규 파일·어댑터·CLI 계약은 Atlas DESIGN.md 섹션 5에 먼저 반영한다.

로컬 증거 저장 후보는 D:/DFIR_CASES다. 2026-09-09 읽기 점검에서 D: 여유 공간 약 711GiB, C: 약 53GiB를 확인했다. 실제 폴더는 아직 만들지 않았다. 1차 로컬 보관 한도는 150GiB로 제안하며 다운로드 전 여유 공간·선택 사건 크기를 다시 검사한다. 압축 원본을 해시한 뒤 파싱은 별도 작업 디렉터리와 권한이 제한된 실행 환경에서 수행한다.

### 8.3 AI 역할

AI는 검색·정규화된 사건 증거 묶음을 읽고 다음을 작성한다.

- 관찰된 사실과 각각의 evidence ID.
- 가능한 설명과 그 설명을 지지하는 근거.
- 반대되는 근거·시간상 모순·누락된 자료.
- 다음 조사에서 확인할 자료.

출력은 unreviewed_hypotheses로 저장한다. 인용 ID 존재 검증과 추론의 사실성 검증을 구분한다. 로그에 포함된 문장은 명령으로 실행하지 않고, AI에 AWS 변경 권한이나 단말 셸 권한을 부여하지 않는다. 민감 원본을 클라우드 AI로 전송하지 않고 로컬 Ollama를 사용한다.

검증 가능한 관계의 예는 “같은 trace가 기록됨”, “이벤트에 부모 ProcessGuid가 명시됨”이다. 시각·계정·경로 유사성만 있는 연결은 후보로 표시한다. 증거가 부족하면 결론을 보류하는 결과도 정상 출력이다.

## 9. 대응 플레이북

### 9.1 초기 정책

| 상황 | 기본 동작 |
|---|---|
| WAF 요청 검사 경보 | 클라우드 로그 수집과 사건 기록, 호스트 자동 격리 없음 |
| 확인된 실습 호스트의 단말 경보 | 사전 정의된 triage 수집 |
| 사전 지정한 격리 검증 시나리오 | 수집·보존과 함께 제한된 격리 플레이북 실행 |
| 알 수 없는 호스트·계정·태그 | 자동 실행 보류, 대상을 확인할 수 없는 이유 기록 |
| AI가 의심 가설 제시 | 분석가 검토 대상으로 저장 |

### 9.2 격리와 복구

격리는 단순히 SG 변경 API가 성공한 것으로 완료 처리하지 않는다.

1. 모든 ENI·원래 SG·ALB target 상태·필요한 관리 경로를 보존한다.
2. 해당 시나리오의 정책에 따라 ALB 대상 등록 해제와 격리 SG 적용을 수행한다.
3. SSM endpoint, 지정 S3 경로, 필요시 Elastic 관리 통신만 유지한다. 불특정 인터넷 HTTPS를 관리 경로로 남겨두지 않는다.
4. 대상→DB, 대상→실습 서버, 기존 연결·새 연결을 각각 검증한다.
5. SG 변경으로 기존 tracked connection이 계속될 수 있으면 OS 방화벽 등 사전에 검증한 보완 조치를 실행하고 결과를 기록한다.
6. 관리 통신이 끊기거나 목표 연결이 남으면 PARTIAL_CONTAINMENT로 기록한다.
7. 복구는 저장된 설정과 이후 변경 여부를 확인해 적용하고, 정상 요청과 Agent 연결을 다시 검사한다.

보안 그룹 변경만으로 기존 추적 연결이 즉시 종료되지 않을 수 있다. [EC2 connection tracking](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-connection-tracking.html)

복구용 SSM 경로와 제한 시간 후 롤백은 실습 전 정상 호스트로 시험한다. 타임아웃이 피해 호스트의 무조건 자동 재연결로 이어지지 않도록, 네트워크 검증용 시나리오와 실제 의심 사건의 정책을 구분한다.

### 9.3 역할과 실행 권한

| 역할 | 허용 범위 |
|---|---|
| 배포자 | 프로젝트 OpenTofu 리소스 생성·변경, 별도 사람 인증 |
| 경보 수집기 | 지정 ES 경보 읽기, 지정 EventBridge bus에 발행 |
| 수집 제어 Lambda | 허용 태그·리소스 조회, 고정 SSM 문서 실행, EBS 스냅샷 관리 |
| 수집 대상 | SSM 통신, 자기 작업 업로드 경로에 쓰기 |
| 증거 검증기 | 지정 staging 읽기, 해시 검증과 최종 manifest 기록 |
| 분석가·로컬 동기화 | 지정 사건 증거 읽기, 분석 결과 쓰기 |
| 대응 실행기 | 지정 실습 호스트·SG·ALB target 변경, 복구 기록 |

수집과 격리 권한을 분리하고, AI와 단순 경보 텍스트가 IAM 대상·명령을 결정하지 못하게 한다. 최초 데모의 통지는 사건 대시보드와 실행 상태로 제공한다. Slack/Jira 발신은 수신처·인증이 정해진 뒤 추가하는 선택 연동이다.

## 10. 공격·방어·관제 검증

S0~S6는 준비 검사이며 실제 공격 검증은 N0/W1~W5/H1~H3/C1~C3/I1~I4/D1~D4/E1~E3/X1~X2/K1~K11 카탈로그를 따른다. 이전 번호의 의미를 새 실행 기록에 사용하지 않는다.

실제 성공과 방어 차단의 대조 결과·정상 대조군·정책 revision을 함께 기록한다. CloudGoat 경로와 웹 침해가 실제로 연결되지 않으면 별도 사건으로 평가한다. 실행 정답은 AI에 주지 않는다.

F1 중복 경보/재시작, F2 SSM·로그 수집 부분 실패, F3 hash/사건 혼입, F4 기존 연결·관리 경로 손실, F5 로그 속 지시문·허위 인용을 추가 검증한다. 실제 공격은 소유한 사설 랩과 지정 AWS 실험 자원에 한정한다.

### 10.1 목표 지표

다음 값은 실습 합격 목표이며 측정 결과가 아니다.

| 지표 | 목표·측정 방식 |
|---|---|
| 단말 이벤트→경보 | 저부하 기준 2분 이내를 목표, event/ingest/alert 시각 분리 |
| WAF 로그 전달→경보 | 5분 전달 주기를 고려해 15분 이내 목표, 실제 지연 기록 |
| 경보→사건 | ES 경보 생성 이후 1분 이내 목표 |
| 기본 triage | 지정한 소규모 프로필에서 15분 이내 목표, 파일량 함께 기록 |
| 무결성 | 필수 파일의 해시 검증 통과, 실패 시 완료 상태 금지 |
| 재시도 | 동일 경보·동일 파일 재전송 후 중복 사건·중복 레코드 없음 |
| 근거 추적 | 모든 보고서 사실 주장에 존재하는 원본 근거 연결 |
| 인과 표현 | 확정되지 않은 관계를 자동 확정으로 표시하지 않음 |
| 격리 | 정의한 차단 대상의 기존·새 연결 시험과 관리 경로 시험 통과 |
| 비용 | 누적 사용료·남은 리소스·보존 기한을 설명 가능 |

최소 S0~S6를 반복하고 정상·의심 사건을 함께 비교한다. 오탐률·수집 성공률·AI 오류율은 분모와 표본 수를 공개하며, 작은 데모에서 얻은 수치를 운영 수준 성능으로 일반화하지 않는다.

## 11. 구현 순서와 완료 기준

일정은 1인이 진행하는 초기 추정이다. 실습 인프라는 로컬 준비가 된 뒤 생성한다. 기간이 늘어나면 클라우드 종료 후 확보한 증거로 개발을 계속한다.

| 단계 | 작업 | 완료 기준 |
|---|---|---|
| A0 | 인프라·웹/DB·방어 정책·OSS·예산 준비 | B00~B01, 버전·권한·구축 순서 구체화 |
| A1 | 계정·VPC·DMZ·SG·TLS·IAM·감사·SSM | B02, 실제 연결 허용/거부·감사 기록 |
| A2 | WordPress·RDS·자료 배치·정상 서비스 | B03~B04, 서비스 결과·DB/TLS/권한 시험 |
| A3 | 중앙 로그·WAF/IPS/EDR·정상/공격·SIEM | B05~B11, S0~S5·D01~D08 실제 결과 |
| A4 | 경보→AWS 사건→선택 host/DB 증거 보존 | B12, 중복·부분 실패·hash·원본 계보 |
| A5 | Atlas AWS·Linux·RDS 자원/시간축 연동 | 로그부터 원본·자원·session·관계 근거 이동 |
| A6 | 네트워크·IAM/DB 대응·복구 | B13/S6, 실제 차단과 정상 회복 |
| A7 | AI 평가·보고서·내보내기·정리 | B14, 정답 비교·source coverage·잔여 비용 |

A0~A7의 구체 작업은 BUILD_AND_ATTACK.md의 B00~B14를 따른다. 기존 22~35일은 단순 초안 추정이며 실제 웹/IPS/권한 실험 구현을 분해한 뒤 다시 산정한다. 클라우드 compute는 누적 100시간을 계획하고 로컬 개발·분석 기간과 분리한다.

첫 구축 목표는 **정상 서비스·모든 필수 로그 → 실제 공격/차단 결과 → SIEM 경보**다. 이후 첫 포렌식 연결은 **D1의 AWS 객체 접근 사건 → 원본 CloudTrail·권한·객체/version 보존 → Atlas 시간축**으로 만들고 W2/H2 Linux host 증거를 추가한다.

## 12. 코드와 문서 배치

아래는 이 evidence-atlas 저장소에서 사용할 구조다. cloud-lab에는 DESIGN.md, BUILD_AND_ATTACK.md, CLOUD_FORENSICS.md, OPEN_SOURCE.md, PIPELINE.md를 작성했고 OpenTofu·수집기·플레이북 코드는 아직 없다.

~~~text
evidence-atlas/
  DESIGN.md            # 전체 확장·코어 변경의 최상위 기준
  README.md            # Atlas 및 AWS 실습 진행 체크리스트
  cloud-lab/
    DESIGN.md          # AWS 구축부터 수집·분석·대응·종료까지
    BUILD_AND_ATTACK.md # 서버·서비스·DMZ·WAF/IPS/EDR·로그·B00~B14
    CLOUD_FORENSICS.md # 계정·권한·로깅·증거·모니터링 계약
    OPEN_SOURCE.md    # AWS 샘플 검토와 도구·라이선스 선택
    PIPELINE.md       # 전체 파이프라인 7구간 검토·인프라 Gap·구현 우선순위
    TASKS.md          # 167개 세부 작업 목록 (Phase A~E, 게이트 G0~G8 매핑)
    toolchain.lock.json # A0 생성 예정: 버전·해시·규칙 lock
    THIRD_PARTY_NOTICES.md # A0 생성 예정: 실제 채택물 고지
    infra/
      foundation/      # S3 증거·로그, 상태 저장, KMS, 예산
      lab/             # VPC, EC2, ALB/WAF, NAT, endpoints
      automation/      # EventBridge, Step Functions, Lambda, DynamoDB, SSM
    bootstrap/         # OS, Elastic, Agent, WEB/APP/DB 설정
    application/       # 3계층 실습 서비스
    collectors/        # 경보·metadata observer, 고정 수집 프로필, manifest
    playbooks/         # 수집, 격리, 복구 상태 정의
    scenarios/         # 정상·의심·실패 재현과 별도 정답 기록
    scripts/           # 시작·중지·내보내기·정리
    tests/             # 계약, 중복, 대상 범위, 재시도 시험
    results/           # 실행별 결과와 검증 증거의 참조
  dfir_graph/          # 사건 import, 어댑터, 관계·시간축·AI 검토
  tests/               # 형식·시간 의미·범위·UI·근거 시험
~~~

OpenTofu state는 원격 S3에 보관하고 암호화·잠금·접근 권한을 설정한다. Security foundation과 Workload lab은 계정별 role/provider·state로 분리한다. 과거 AWS 샘플의 전체 CloudFormation 자원을 그대로 실행하지 않는다. state, 비밀번호, API key, 원본 증거는 Git에 커밋하지 않는다. foundation과 일시 실행 lab을 구분해 실습 종료가 증거 버킷 삭제로 연결되지 않게 한다. 증거·로그 버킷의 force_destroy는 기본 false다.

evidence-atlas 루트 README의 AWS 체크리스트를 전체 진행 상황의 출처로 사용한다. 상세 시험 결과는 cloud-lab/results에 명령·실제 출력·이미지 경로·탐지 결과 순서로 기록한다. Atlas 내부 기능 완료 기준도 같은 저장소의 README/DESIGN과 일치시킨다.

## 13. 예산과 자원 수명

### 13.1 1개월 보관·핵심 서버 100시간 실행

2026-09-09 개략 견적은 과거 기록이다. 실제 배포 전 최신 서울 리전 온디맨드 단가를 확인한다. 할인·무료 티어·크레딧 차감은 계산에서 제외한다. 기본 서버는 Linux이며 RDS MySQL Single-AZ를 별도로 계산한다. 계산상 한 달은 730시간이다.

현재 비용 산정은 모드별 실제 자원으로 다시 계산한다. setup은 NAT1+공인IPv4, operate는 NAT 없이 interface endpoint9개×1AZ, idle은 NAT/interface endpoint0개다. 내부 ALB·EBS·RDS 저장/백업·KMS(RDS 전용 키 포함)·S3/CloudTrail data events·선택 TEST EC2의 시간/건수는 별도다. 이 문서의 과거 단가로 새 합계를 확정하지 않는다. 배포 직전 선택 리전·서비스 수량·실행 시간으로 다시 견적하고 $300 목표와 대조한다.


**300달러 이하를 보장하는 견적은 아니다.** 자료량·CPU 사용·배포 기간에 따라 달라지고, 세금·유료 XDR 라이선스·도메인·유료 모델 API는 포함하지 않는다. 데이터 전송·S3·스냅샷 항목은 정액 요금이 아닌 작업 범위에 대한 예비비다.

이전 개략 견적보다 SSM 전용 연결·임시 분석 작업과 교차 계정 증거 보관을 명시적으로 추가했다. 핵심 EC2·RDS 상시 실행 비용은 100시간 실습과 별도로 계산한다. 계획 예산은 이 상시 운영을 포함하지 않는다. RDS 중지 후 7일 자동 재시작·burst CPU·backup·Secrets 비용도 추적한다. 교차 계정 크레딧 적용과 실제 보관량은 배포 전 확인한다.

단가 근거: [EC2·EBS·NAT 서울 요금표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-2/index.csv), [ALB 서울 요금표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSELB/current/ap-northeast-2/index.csv), [VPC 서울 요금표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonVPC/current/ap-northeast-2/index.json), [WAF 요금](https://aws.amazon.com/waf/pricing/), [RDS 서울 요금표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/ap-northeast-2/index.csv).

### 13.2 예산 제어

- 크레딧 차감 전 사용료를 기준으로 $100/$180/$220/$250 알림을 설정하는 코드를 준비한다.
- $180에서는 실제 잔액과 남은 시나리오를 검토하고, $220에서는 새로운 대규모 수집·장기 실행을 중단하는 운영 기준을 둔다.
- $250 이전에 증거 내보내기와 실행 자원 정리를 마치는 것을 목표로 한다. $50은 과금 지연·잔여 보관·세금 등 여유다.
- 모든 생성 자원에 Project, Owner, Environment, ExpiresAt을 기록한다.
- 실행 시간 상한, 작업 VM 수, 수집 크기, 스냅샷 수에 코드상의 제한을 둔다. 예산 알림과 별개로 동작한다.
- 첫 기본값은 동시 수집 1건, 호스트당 업로드 10GiB·사건당 20GiB, 동시 분석 VM 1대·최대 실행 2시간, 호스트당 보존 스냅샷 최대 2개다. 초과 요청은 원인과 미수집 항목을 표시하고 기존 증거를 삭제하지 않는다. 큰 디스크·메모리 수집은 별도 프로필과 비용 계산으로 확장한다.
- AWS Budgets 알림은 과금 차단 장치가 아니며 갱신 지연이 있다. 비용 알림만으로 지출 상한을 보장하지 않는다. [AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)
- 실제 크레딧의 사용 가능 서비스·만료일을 배포 전에 확인한다. Marketplace 제품 비용까지 AWS 크레딧이 적용된다고 가정하지 않는다. [AWS 크레딧 조건](https://aws.amazon.com/awscredits/)

### 13.3 일상 종료와 프로젝트 종료

**일상 종료:** 새 시나리오 중지 → 진행 중 수집 완료/부분 상태 기록 → 수집 지연분 반영 → 앱·Elastic 정상 종료 → EC2 및 RDS 중지. EBS, NAT, ALB, endpoints 등은 계속 과금됨을 종료 출력에 표시한다.

**여러 날 쉬는 경우:** manifest와 상태 저장 확인 → 일시 실행 lab을 축소/재생성 가능한 형태로 정리. ALB/NAT/endpoints 삭제 후 재생성에 따른 DNS·라우팅·Agent 재접속을 시험한다.

**프로젝트 종료:** 필요한 증거를 로컬에 내려받아 해시·재열람 확인 → 사건 보존 정책에 따라 불필요한 임시 VM·볼륨·스냅샷 제거 → ALB/NAT/endpoints·공인 IP 등 정리 → CloudTrail/WAF/Flow Logs·자동화의 신규 생성 중지 → 보존 버킷·state·KMS 등 남긴 자원과 삭제 예정일 기록.

수집 파일만 내보냈는지, 전체 디스크 이미지까지 보존했는지를 명시한다. 파일 일부만 내보낸 상태를 전체 스냅샷 보존과 동일하게 표시하지 않는다. 증거 삭제는 보존 범위와 검증 결과에 따라 수행한다.

종료 검증은 EC2 목록만으로 끝내지 않는다. 볼륨·EBS/RDS 스냅샷·RDS 재시작·EIP·ALB·NAT·endpoints·버킷 버전·CloudWatch·Secrets·KMS·예약 작업을 점검하고, 비용 데이터가 갱신된 뒤 잔여 사용량을 대조한다.

## 14. 확장 순서

| 후속 확장 | 시작 조건 |
|---|---|
| CloudTrail·WAF·Linux 관계 고도화 | 첫 AWS 사건 완주, 시간·자원·session 식별자 계약 검증 |
| Windows/KAPE 수집 비교 | AWS 핵심 서비스·관제 검증 후 필요할 때 별도 endpoint로 추가 |
| 메모리 수집·분석 | 드라이버·도구·저장소·처리 시간 검증 |
| Slack/Jira 연동 | 사건 상태·통지 내용·수신처 확정 |
| 클라우드에 Atlas 뷰어 배치 | 인증·사건 접근 권한·ES 조회 경로·운영 비용 검증 |
| Security 계정의 별도 분석 VPC·SOC | 기본 증거 계정 경계 검증 후, 운영상 필요·추가 NAT/endpoint/VM 비용 확인 |
| 유료 EDR/XDR 기능 비교 | 라이선스 비용·대체 경로·평가 항목 확정 |

AWS 공식 Automated Forensics Orchestrator는 수집·격리·조사·보고서 흐름을 비교하는 참고 자료로 사용한다. 전체 엔터프라이즈 배포를 이 예산에 그대로 포함하지 않는다. [공식 구성 소개](https://docs.aws.amazon.com/solutions/latest/automated-forensics-orchestrator-for-amazon-ec2/welcome.html)

## 15. 착수 시 확인할 사항

현재 설계는 아래 값이 미정이어도 작성할 수 있으며, 실제 배포 전에는 구체적인 값으로 채운다.

- Workload/Security 계정 ID와 사용 가능 여부, 크레딧 잔액·만료일·계정 간 적용 제한.
- VPC 대역 충돌 여부와 사용할 AZ·리소스 한도.
- 선택한 Elastic 안정 버전·Basic 기능·패키지 호환성.
- WordPress·DVWA·CloudGoat·Suricata·Elastic·Velociraptor·Sigma 버전·라이선스·해시. Windows/KAPE 파서는 후속 선택 연동.
- D:의 현재 여유 공간 재확인, 사례당 예상 자료량과 보존 기간.
- HTTPS 공개 시연을 선택할 경우 도메인·인증서·허용 IP.

현재 단계에서 실제 AWS 리소스, 비용 알림, 자동 실행 예약, 외부 메시지 연동은 생성하지 않았다.
