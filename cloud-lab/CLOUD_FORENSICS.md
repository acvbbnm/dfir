# AWS 인프라·관측·증거 파이프라인 상세 설계

> 2026-09-11 구현 보완: [로컬 검증 기록](results/LOCAL_VALIDATION.md)과 [실행·잔여 작업](LOCAL_DEVELOPMENT.md)을 확인한다. 현재 operate 모드는 SSM 계열 3개 + 일반 API 6개로 interface endpoint 총 9개다. 이전 2~3개 기준 비용표는 현재 IaC의 확정 견적이 아니며 실제 단가·실행 시간으로 재산정해야 한다. AWS 배포는 아직 수행하지 않았다.


작성일: 2026-09-09 · 버전: 0.3 · 상태: 배포 전 설계

이 문서는 [전체 계획](DESIGN.md)의 AWS 계정·권한·통신·로깅·증거 보존·조사 파이프라인을 구체화한다. 서비스·DMZ·WAF/IPS/EDR·로그·구축 순서는 [BUILD_AND_ATTACK.md](BUILD_AND_ATTACK.md), 수집·파서 재사용은 [OPEN_SOURCE.md](OPEN_SOURCE.md)를 따른다. 구현과 운영 검증이 끝난 상태를 의미하지 않는다.

## 1. 클라우드 포렌식에서 달라지는 점

클라우드라서 모든 메모리나 로그가 더 빨리 사라지는 것은 아니다. 실행 중 EC2의 RAM은 일반 서버와 같은 휘발성 특성을 가지며, 주요 차이는 자동 교체·중지·종료·관리형 서비스의 접근 제한과 사전 로깅 설정이다. CloudTrail·S3 로그는 호스트 종료 후에도 보존할 수 있지만, 애초에 활성화하지 않은 데이터 이벤트는 사후 생성할 수 없다.

| 대상 | 고객이 확보 가능한 자료 | 흔한 오해·한계 | 초기 설계에서 할 일 |
|---|---|---|---|
| EC2 guest OS | 메모리, 프로세스, 연결, OS 로그, 아티팩트 | 물리 호스트·하이퍼바이저 접근은 없음. SSM/EDR만으로 모든 흔적을 확보하는 것도 아님 | 도구·권한·로그 설정을 배포 전 준비 |
| EC2 RAM | 실행 중 OS 기반 덤프·휘발 정보 | EBS 스냅샷에 포함되지 않음. stop/reboot/terminate 후 이전 RAM 복원 기대 금지 | stop보다 앞선 triage, 메모리는 검증된 선택 프로필 |
| EBS | 디스크 스냅샷, 원본 메타데이터, 복사 볼륨 | snapshot ID는 이미지 파일의 SHA-256이 아님. AWS 관리 키 암호화는 계정 간 공유 제약 | 고객 관리 KMS 키, 스냅샷 완료 확인·보안 계정 소유 복사 |
| instance store | 살아 있는 동안 OS를 통해 수집 | stop/terminate 등에서 데이터 소실. EBS와 별개 | 첫 랩 T3에는 사용하지 않음. 확장 시 별도 수집 |
| S3 | 객체 버전, metadata, 데이터 이벤트, 접근 정보 | EC2 디스크 스냅샷에 포함되지 않음. Versioning은 Object Lock과 다름 | version ID·checksum·선택 데이터 이벤트·보존 정책 |
| RDS | 엔진 로그, 감사 설정, DB snapshot·API 활동 | 일반 RDS OS 메모리·호스트 파일 직접 수집 불가 | 기본 DB는 RDS MySQL. 엔진 로그 export·파라미터·TLS·manual snapshot/copy를 준비 |
| Lambda/Fargate | 서비스 로그·설정·이미지 digest·실행 ID 등 | EC2 수준 메모리·디스크 접근을 동일하게 가정할 수 없음 | 현재 자동화 Lambda만 포함. 대상 서비스 확장은 별도 설계 |
| IAM/STS | API 감사, role session, 권한·trust 정책 | AWS API 사용자와 OS 로그인 사용자·웹 계정은 서로 다름 | 네 종류의 identity namespace를 분리하고 관측된 연결만 저장 |

[instance store 수명](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-store-lifetime.html) · [CloudTrail 기록 종류](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-management-events-with-cloudtrail.html) · [RDS 제약](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/MySQL.Concepts.FeatureSupport.html)

서로 다른 클라우드의 격리·스냅샷·감사 기능을 하나의 API처럼 가정하지 않는다. 공통 계약에는 provider/account/region/resource/native event ID를 두고 이번 구현은 AWS adapter만 지원한다. Azure·GCP 지원은 각 제공자의 증거·권한·보존 의미를 다시 정의해야 한다.

## 2. 증거 신뢰 경계부터 정하는 계정 구조

### 2.1 권장안: Workload와 Security/Evidence 분리

계정 추가는 이 문서의 제안이며 실제 생성·조직 가입·결제 변경은 수행하지 않는다. 배포 전에 두 계정을 사용할 권한과 크레딧 적용을 확인한다.

| 계정 | 리소스 | 권한과 한계 |
|---|---|---|
| Workload | VPC·내부 ALB/WAF·WEB/APP/SOC EC2·RDS·업무 S3·Secrets·원본 로그 landing | 실습 행위와 침해 가정의 대상. SOC 조회 인덱스도 이 계정의 관리자에 대해 독립 증거가 아님 |
| Security/Evidence | 감사·증거 S3, 전용 KMS, EventBridge·Step Functions·Lambda·DynamoDB, 복사 스냅샷 | Workload 역할이 최종 증거 삭제·KMS 비활성화·자동화 수정 권한을 갖지 않음 |
| 개인 PC | 읽기 권한으로 사건 다운로드, Atlas·파서·로컬 AI | 보존 원본의 복사본을 분석하며 작업 이력을 유지 |

Security 계정은 첫 버전에 상시 EC2·VPC·NAT를 만들지 않는다. 자동화 Lambda는 AWS API를 사용하며 고객 VPC에 연결할 필요가 없는 작업으로 구성한다. Workload 호스트 명령은 교차 계정 역할을 거쳐 SSM으로 실행한다. 보안 계정에 SSM 명령 실행용 서버를 추가하지 않는다.

SOC를 Workload 계정에 두는 이유는 단말→Elastic 연결과 300달러 실습 비용을 단순하게 유지하기 위해서다. 따라서 SOC 자체의 위변조까지 완전히 차단했다고 주장하지 않는다. 독립 보관된 AWS 로그·수집 원본·스냅샷과 대조할 수 있도록 한다. 계정 관리자 탈취에 대한 고가용성 관제는 SOC 별도 계정·VPC 전환을 포함하는 후속 범위다.

계정 하나만 사용할 수 있으면 기능 검증 모드로 동일 API 경로를 구현할 수 있다. 그 경우 역할·버킷을 나눠도 계정 관리자에 대한 증거 격리 경계를 검증했다고 표시하지 않는다. 실제 계정 제약 확인 전까지 두 계정 설계의 구현 상태를 완료 처리하지 않는다.

### 2.2 계정과 데이터 흐름

~~~mermaid
flowchart LR
    subgraph W["Workload 계정 · 격리된 실습 VPC"]
      T["시나리오 실행기"] --> ALB["내부 ALB + WAF"]
      ALB --> WEB["Nginx · Suricata IPS"] --> APP["Linux · WordPress"] --> DB["RDS MySQL"]
      WEB -. "이벤트" .-> SOC["Elastic + 경보 수집기"]
      APP -. "이벤트" .-> SOC
      DB -. "이벤트" .-> SOC
      LAND["S3 로그 landing"] --> SOC
      ALB -. "로그" .-> LAND
      SSM["SSM Agent / 전용 endpoints"] --> APP
    end
    subgraph S["Security/Evidence 계정"]
      RAW["S3 감사·로그 archive"]
      STAGE["S3 업로드 staging"] --> VERIFY["manifest 검증"]
      VERIFY --> FINAL["S3 최종 증거"]
      EV["EventBridge"] --> SF["Step Functions + Lambda"]
      SNAP["자체 KMS로 복사한 EBS snapshot"]
    end
    LAND -. "비동기 복제 · 지연 감시" .-> RAW
    CT["양 계정 CloudTrail"] --> RAW
    SOC --> EV
    SF -. "제한된 AssumeRole · SSM" .-> SSM
    APP -. "선택 원본·결과 업로드" .-> STAGE
    SF --> SNAP
    FINAL --> PC["로컬 Atlas · 파서 · AI"]
    RAW --> PC
~~~

로그 생성·전달 경로와 수집 명령의 제어 경로를 분리한다. 모든 화살표는 구현할 IAM·서비스 정책·리전·통신 시험을 가져야 한다.

## 3. 네트워크가 보장하는 것과 보장하지 않는 것

### 3.1 기본 VPC

10.60.0.0/16 예시와 서브넷 표는 전체 DESIGN 4절을 따른다. ALB는 AZ A/C에 걸쳐 배치하고 VM은 AZ A에 두는 소형 실습이다. VPC local route로 서브넷 간 경로가 존재하므로, 이름을 dmz·inner로 붙였다는 이유만으로 접근이 차단되지 않는다. 보안 그룹의 허용 규칙을 실제로 시험한다.

| 경로 | 구성 | 검증 |
|---|---|---|
| 실행기→서비스 | 내부 ALB 80/443 → WEB 8080 → APP 8080 → DB 3306 | 우회 직접 접근은 거부, 정상 요청은 성공 |
| 단말→관제 | 고유 Agent 자격증명, TLS 9200/8220 | 다른 agent 데이터 조회·관리 API는 거부 |
| 관리자→호스트 | Session Manager, 필요한 포트 포워딩 | 인터넷 22/3389/5601/9200 접근 불가 |
| 수집→SSM | Workload ssm·ssmmessages interface endpoints | NAT 경로를 막아도 관리·수집 동작 |
| 수집→S3 | regional S3 gateway endpoint, 지정 bucket/prefix 정책 | 최종 증거 삭제·다른 호스트 staging 접근 거부 |
| 업데이트·API | NAT 1개, 설치/운영 모드별 egress | NAT는 방화벽이나 FQDN allowlist가 아님. 실제 HTTPS 허용 범위를 기록 |
| 교차 계정 제어 | Security 역할→Workload 수집/대응 역할 | VPC peering 없이 AWS API로 수행 |

[SSM endpoint 구성](https://docs.aws.amazon.com/systems-manager/latest/userguide/setup-create-vpc.html) · [NAT·peering 제한](https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-basics.html)

SG는 stateful 허용 규칙, NACL은 subnet 단위 stateless 규칙이다. NACL을 추가하면 응답 포트와 수집 경로까지 영향이 있으므로 기존 연결 차단 수단으로 도입할 때 전용 subnet·영향 범위를 시험한다. 초기 격리는 SG와 사전 검증한 OS 조치를 조합한다.

AWS API는 호스트의 통신 경로와 별개로 호출될 수 있다. 공격자가 외부에 복사한 임시 AWS 자격증명으로 API를 호출하는 경우 호스트 SG 격리만으로 차단되지 않는다. 네트워크 격리와 role session 대응을 분리한다.

### 3.2 DNS·메타데이터·시간

- VPC DNS와 private DNS를 활성화하고 SSM endpoint DNS가 private 주소로 해석되는지 확인한다.
- IMDSv2를 요구하고 instance profile 권한은 서비스별로 분리한다. OS 관리자에게 IMDSv2가 자격증명 접근 차단 수단이라고 가정하지 않는다.
- metadata endpoint 접근은 VPC Flow Logs에 남지 않으므로 host 탐지와 이후 CloudTrail API 사용을 대조한다.
- OS UTC·시간 동기화 상태와 수집 시 offset/부팅 시각을 기록한다. 원본 시간대·정밀도를 유지한다.
- DNS 조사는 VPC의 Route 53 Resolver query logging과 Linux/Defend의 가용 이벤트를 사용한다. Flow Logs가 모든 DNS/IMDS 트래픽을 기록하지 않음을 표시하고 resolver 캐시·전송 지연을 검증한다.

## 4. IAM·KMS·관리 사용자 설계

### 4.1 사람과 워크로드 구분

| 정체성 | 식별·권한 | 기록할 근거 |
|---|---|---|
| 배포자 | 사람의 MFA/연합 로그인·짧은 역할 세션, Workload와 Security 권한 분리 | role/session ARN, 변경 계획, CloudTrail |
| 분석가 | 지정 사건 read, 분석 결과 prefix write | 사건 접근 기록, 보고서 변경 이력 |
| 수집 제어 | Security Lambda의 역할, Workload의 EACollectionRole만 AssumeRole | event/job ID, STS session, SSM command ID |
| 격리 제어 | 별도 EAResponseRole, 허용 host/SG/target 범위 | 변경 전후 JSON과 API 결과 |
| 단말 업로드 | 호스트별 instance profile, 자기 staging prefix만 쓰기 | 업로드 object/version, host metadata, 수집 로그 |
| 로그 수집기 | 지정 SQS·S3·CloudWatch 로그 read, 제한된 ES ingest/alert read | 처리 커서·source object·인덱스 결과 |
| 웹 사용자 | 애플리케이션 계정·세션 | APP 감사 로그, IAM identity로 자동 해석하지 않음 |
| DB 사용자 | MySQL 계정·세션·접속 host | DB 로그, APP 요청 context |

role의 trust policy는 정확한 호출 역할 ARN을 지정한다. resource policy·identity policy·KMS key policy·SCP/permission boundary의 유효 권한을 함께 확인한다. 조건은 해당 API가 지원하는 key에만 적용한다. ExternalId는 필요한 제3자 위임 상황에서 검토하며, 자신이 관리하는 두 계정 사이 모든 문제를 해결하는 필수 토큰처럼 붙이지 않는다.

`iam:PassRole`, 광범위한 AssumeRole, SSM의 임의 셸 문서 실행 권한은 수집 역할에 부여하지 않는다. 수집 대상·문서 버전·collector ID를 제어 코드가 확인한다. EventBridge event.detail의 instance_id를 신뢰된 대상 목록으로 간주하지 않는다.

### 4.2 KMS 소유권

| 키 | 소유 | 용도·소비자 |
|---|---|---|
| workload-ebs | Workload | 최초 EC2 EBS 암호화. snapshot copy 역할에 필요한 제한된 키 사용 |
| evidence-s3 | Security | staging·최종 증거·감사 자료. 작성·검증·읽기 역할별 권한 |
| evidence-ebs | Security | 계정 간 복사한 snapshot의 독립 암호화 |

일반 실행 역할에 키 disable·schedule deletion·정책 변경을 허용하지 않는다. S3 multipart upload에는 암호화 방식에 따라 Decrypt 등 추가 권한이 필요하므로 원칙적으로 쓰기 전용이라는 말만으로 KMS 권한을 생략하지 않는다. 키·bucket·object policy의 동시 성공/실패 시험을 수행한다.

스냅샷 공유와 키 공유는 별도다. Security 계정이 접근할 수 있는 shared snapshot 상태만으로 보존 완료 처리하지 않고, **Security 소유 키로 copy 완료**를 확인한다. [키 공유](https://docs.aws.amazon.com/ebs/latest/userguide/share-kms-key.html) · [스냅샷 복사](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-copy-snapshot.html)

### 4.3 AWS identity 조사 필드

CloudTrail에서 eventID, eventTime, eventSource, eventName, awsRegion, recipientAccountId, userIdentity.type/arn/principalId, sessionContext.sessionIssuer, accessKeyId, sourceIdentity 등 존재하는 값을 원본과 함께 보존한다. sourceIPAddress/userAgent/requestParameters/responseElements/errorCode도 필요한 범위에서 읽는다.

AssumeRole session ARN과 IAM role ARN을 같은 문자열로 합치지 않는다. 호출자가 보고된 IP와 실제 단말을 동일시하지 않는다. accessKeyId는 상관 식별자이며 secret access key·session token을 수집하도록 설계하지 않는다. 삭제된 role의 당시 trust·policy 문서가 현재 조회에서 사라질 수 있으므로 배포·변경 시 구성 기록을 남긴다.

## 5. 로깅을 켜는 단계와 보존 위치

### 5.1 로깅은 서비스 오픈보다 먼저

배포 순서는 Security 저장소/키/정책 → CloudTrail → Workload VPC/roles/EC2 메타데이터 → OS 로깅/Agent → 정상 데이터 → 탐지·시나리오다. 초기 부팅·설치 로그도 별도 저장한다. 로깅 설정을 나중에 켜서 초기 침해 단계를 잃는 구성을 피한다.

### 5.2 소스별 수집 계약

아래 보존 기간과 크기는 초기 설정 목표다. 실제 이벤트량·교육 자료의 민감도·예산으로 조정하고, 변경은 config version에 기록한다.

| 소스 | 반드시 켤 설정 | 경로·보존 | 조사에 쓰는 연결 | 자료가 말해주지 않는 것 |
|---|---|---|---|---|
| CloudTrail 관리 | 양 계정 read/write management, multi-region trail, global service events, digest | Security audit S3에 직접 전달, 30일 이상 또는 선택 사건 보존 | IAM/STS→AWS API→리소스, 변경·수집·대응 이력 | 셸 명령 전체·SQL·파일 내용 |
| CloudTrail 데이터 | 실습 S3 객체와 최종 증거 접근 등 지정 ARN/prefix의 read/write | Security audit, 이벤트량 측정 | 누가 어떤 object/version에 접근했는지 | 사전 활성화 이전의 객체 작업 |
| WAF | full logging, 필요한 차단·허용 이벤트, 민감 header redaction | Workload aws-waf-logs landing→Elastic, Security archive로 복제 | webACL, rule, action, request 필드 | 차단된 요청의 backend 실행, HTTP 전체 본문 |
| ALB | access logging, target·trace 필드 보존 | Workload landing→Elastic, Security archive로 복제 | 요청→target IP/port→유효 host 매핑 | 요청을 처리한 OS 프로세스의 확정 |
| Windows Sysmon (후속 선택) | 1/3/11/22 포함하는 고정 config, 필요한 제외 규칙 | Agent→Elastic, 원본 EVTX triage→Security | ProcessGuid·ParentProcessGuid·파일·연결 | 기본 설치가 모든 event를 수집한다고 가정 불가 |
| Windows Security (후속 선택) | 필요한 audit policy, 4624/4625/4688/4698 등 시나리오별 활성화 | Agent→Elastic, EVTX 보존 | 로그온 ID·SID·실행·작업 | 같은 사용자명이 다른 호스트에서도 같은 계정이라는 보장 |
| PowerShell (후속 선택) | 4104 Script Block, 필요한 4103; 채널 크기 설정 | Agent→Elastic, EVTX triage | 실행 내용과 process/session 후보 | 모든 과거 명령, 암호화·누락된 내용 복구 |
| WEB/WordPress | Nginx/Apache·앱 감사 JSON, request/trace, 계정·action·DB 작업 ID | Agent→Elastic, 파일 triage | HTTP→APP 작업→DB 세션 후보 | 사용자 입력 trace 하나의 신뢰성 |
| Linux WEB/APP | persistent journal, auth, 필요한 auditd exec/file 규칙 | Agent→Elastic, journal/audit 원본 triage | boot ID·audit serial·uid/auid·process/session | shell history만으로 실행 확정 |
| RDS MySQL | error·slow, 실험 구간 general, log_output=FILE·CloudWatch export | CloudWatch→Elastic, Security 사건 원문 보존 | connection/thread ID·DB 사용자·APP 작업 | CloudTrail이 SQL 전체를 대신 기록함 |
| VPC Flow Logs | APP/DB/수집 ENI, ACCEPT/REJECT, 1분 집계 요청, log-status | landing S3→Elastic + Security 복제 | 시간 구간·ENI·5-tuple·허용/거부 | 패킷 본문, 모든 DNS/IMDS 접근, 완전한 무손실 기록 |
| SSM·자동화 | 실행 ID·버전·상태, SSM 결과 S3, Lambda JSON logs | Security manifest + CloudWatch 14일 | 누가 어떤 수집·격리 작업을 했는지 | Session Manager 포트 포워딩의 내부 트래픽 내용 |
| 구성 메타데이터 | apply output, AMI/ENI/EBS/SG/role 매핑, 변경 전후 조회 | Security 구성 archive, 선택 사건 고정 | 사건 당시 IP·SG·KMS·host 관계 | 현재 Describe 값이 곧 과거 값이라는 보장 |

- CloudTrail Event history는 최근 90일 management events 조회용이며 전체 데이터 이벤트 보관소가 아니다. [공식 설명](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/view-cloudtrail-events.html)
- 일반 trail의 기본값만으로 data events가 기록되지 않는다. data event를 로깅하는 bucket과 로그가 저장되는 audit bucket을 구분해 자기 로깅 증폭을 피한다. [데이터 이벤트 선택](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html)
- CloudTrail digest 설정은 digest 생성일 뿐 검증 실행이 아니다. `validate-logs` 등의 별도 결과와 조사 구간을 기록한다. [무결성 검증](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html)
- 후속 Windows 수집을 추가할 때 Sysmon Event ID 3은 기본 비활성화다. 설치 성공·서비스 실행과 조사에 필요한 로깅 활성화를 따로 시험한다. [Sysmon](https://learn.microsoft.com/en-us/sysinternals/downloads/sysmon)
- VPC Flow Logs의 SKIPDATA·집계 구간·미수집 트래픽을 UI에 반영한다. [Flow Logs 한계](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs-limitations.html)

원본 로그의 비밀번호·토큰은 수집 전에 애플리케이션과 로깅 설정에서 기록하지 않도록 설계한다. 확보한 원본을 조용히 수정하지 않고, 보고서·AI 입력에는 별도 마스킹 파생본과 처리 이력을 사용한다.

### 5.3 전달 지연과 회전 용량

Linux journal·웹/앱 감사·Suricata EVE와 RDS CloudWatch 로그에 디스크/보존 한도·rotation을 설정한다. 후속 Windows 수집은 EVTX 256MiB/Sysmon 512MiB를 후보로 별도 검증한다. 이 수치는 실제 구성량에 맞춘 시험 대상이지 모든 호스트의 정답이 아니다.

- 단말 이벤트는 지속 전송하며, 원본 OS/웹/EVE 아티팩트는 사건 수집에서 추가 보존한다.
- WAF S3 전달은 5분 주기를 고려한다. 순서 역전과 늦게 도착한 파일을 허용한다.
- 수집 window가 닫혔다고 S3 로그가 모두 도착했다고 표시하지 않는다. 최종 조사 시 late-arrival 재조회와 coverage 기록을 남긴다.
- Agent가 정지하면 로컬 로그는 rotation까지 남을 수 있지만 전송되지 않은 이벤트가 반드시 복구된다고 보장하지 않는다.

### 5.4 사건 당시의 구성 기록

현재 `DescribeInstances` 결과만으로 과거 IP·ENI·SG·IAM 구성을 복원하지 않는다. 초기안은 Security의 읽기 전용 metadata observer가 Workload의 지정 자원을 실행 중 5분마다 조회하고, 변경된 상태만 고유 S3 객체에 보존한다. 배포·정상 종료·수집·대응 직전에는 추가로 기록한다. 관련 API 변경 이벤트가 들어오면 보강 조회하되 이벤트 전달만으로 완전성을 보장하지 않는다.

객체에는 observed_at, native create/launch time(있는 경우), source API, account/region, response hash, 이전 상태 참조를 기록한다. 5분 사이에 생성·삭제되어 조회에 잡히지 않은 자원은 CloudTrail 증거와 함께 gap으로 표시한다. first_seen/last_seen을 정확한 생성·삭제 시각으로 바꾸지 않는다. 더 촘촘한 구성 이력이 필요한 단계에는 대상 유형을 제한한 AWS Config를 비용 검토 후 추가한다.

관측 대상은 EC2/ENI/EBS·SG/routes·ALB/listener·webACL·IAM role/trust/정책·KMS 상태·RDS/parameter group·S3 version/policy·secret metadata다. API별 read 범위와 개인정보·자격증명 노출을 검토하며 secret/session token을 상태 기록에 넣지 않는다.

## 6. 원본 landing·archive·사건 증거의 분리

### 6.1 객체 소유와 복제

- CloudTrail: 양 계정 trail이 Security의 audit bucket으로 직접 전달한다. source account/trail ARN과 서비스 principal을 제한한다. [다중 계정 로그 보관](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-receive-logs-from-multiple-accounts.html)
- WAF/ALB/Flow: 첫 구현은 Workload 소유 landing bucket으로 수집하고, 그 경로를 Elastic ingest가 읽는다. WAF용 버킷은 서비스 명명 요구를 따른다.
- landing→Security archive는 같은 리전 S3 replication을 사용한다. 양쪽 Versioning·destination ownership·KMS·복제 역할 정책을 검증한다.
- delete marker 복제를 비활성화한다. source 삭제가 이미 복제된 evidence version의 삭제 권한으로 이어지지 않게 한다. [복제 삭제 동작](https://docs.aws.amazon.com/AmazonS3/latest/userguide/delete-marker-replication.html)
- 복제는 즉시·무손실 완료라고 가정하지 않는다. pending/failed와 전송 지연을 감시하고, 복제 전 source 유실은 결손으로 남긴다.
- 운영 로그 archive와 사건용 증거 보존 기간을 구분한다. 모든 bucket은 Block Public Access를 적용한다.

### 6.2 staging에서 최종 증거로

단말은 Security staging bucket의 사전 지정한 호스트별 prefix에 쓰기만 한다. 자체 AWS 자격증명으로 최종 증거·다른 호스트의 파일을 읽거나 삭제할 수 없다. Security 측 수집 제어기가 case/job/host 목록과 size/hash를 대조한 뒤 고유 최종 key에 복사한다.

수집 완료 manifest는 대상 호스트가 혼자 확정하지 않는다. SSM exit 상태, 전송 결과, Security 검증기, 원본 객체 버전·해시가 일치해야 READY가 된다. 악성 endpoint가 거짓 파일을 올릴 가능성은 여전히 있으므로 live collection provenance를 표시하고 스냅샷·AWS 감사와 교차 확인한다.

일반 triage ZIP은 크기가 클 수 있으므로 Lambda가 수십 GiB 전체 파일을 한 번에 다운로드·파싱한다고 설계하지 않는다. 작은 manifest·S3 checksum·object 상태 검증은 Lambda가 수행하고, 전체 파일 해시 재계산·파싱은 크기·시간 한도가 있는 작업 VM 또는 로컬 worker가 담당한다. full validation 전 상태는 UPLOADED_UNVERIFIED다.

S3 checksum을 사용하더라도 multipart composite checksum과 full-object SHA-256을 혼동하지 않는다. 최종 보고서에 독립 계산한 SHA-256과 검사 범위를 남긴다. ZIP 외부 해시, 내부 원본 파일 해시, parser output 해시를 별도 보존한다.

### 6.3 RDS·DNS CloudWatch 로그의 별도 보존 경로

RDS 엔진 로그는 FILE 출력·파라미터·CloudWatch export를 설정하고, Resolver DNS는 지정 log group에 전달한다. Elastic 수집기는 제한된 CloudWatch 읽기 권한으로 조회한다. Security 원본 수집기도 별도 커서로 지정 group/stream의 원문을 S3에 보존한다. query window·event timestamp·ingestion time·eventId·pagination과 late-arrival 재조회를 기록한다. SIEM 문서만 복사한 것을 서비스 원본 보존으로 부르지 않는다.

실행 중 주기적으로 원문을 보존하고 선정 사건의 window를 다시 조회한다. Log group retention 만료 전 export, source/보관 건수·실패 비교가 필요하다. 신규 원본에 parser 결과나 secret 값을 덧씌우지 않는다. [RDS CloudWatch export](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_LogAccess.MySQLDB.PublishtoCloudWatchLogs.html)

## 7. 휘발성 우선순위와 호스트 수명 제어

| 우선순위 | 대상 | 실행 시점 | 실패 시 상태 |
|---|---|---|---|
| P0 | AWS metadata·권한·ENI/EBS/SG와 source 로그 참조 | 대응 변경 전에 즉시 | 대상 검증 실패 시 변경 보류 |
| P1 | 프로세스·연결·세션·열린 파일 등 빠른 상태 | 호스트 stop/reboot 전에 | VOLATILE_UNAVAILABLE, disk-only 가능 |
| P1 확장 | RAM dump | 도구·driver·크기 검증된 선택 시나리오 | 덤프 실패·검증 실패를 수집 완료로 표시하지 않음 |
| P2 | 원본 Linux/웹/EVE·RDS 엔진 로그·선택 객체/정책 | rotation·종료 전에 | PARTIAL, 누락 범위 명시 |
| 병행 | EBS snapshot 요청·완료·Security copy | 살아 있는 디스크 기준, 정책에 따라 P1/P2와 병행 | PENDING/FAILED/SHARED_NOT_COPIED 구별 |
| P3 | 늦게 도착한 WAF/CloudTrail/Flow 로그 | 최초 수집 이후에도 보강 | 조사 범위 coverage 미완료 |

초기 대상은 On-Demand EC2로 고정하고 Spot·Auto Scaling 자동 교체를 사용하지 않는다. 일반 사용자의 인스턴스 종료 권한을 제한하고, 진행 중 사건의 태그/상태를 일상 종료 스크립트가 확인한다. 종료 보호가 모든 API·ASG·관리자 권한을 막는 장치라고 생각하지 않는다.

반드시 종료해야 하는 비용·운영 상황에서는 어떤 휘발 자료를 확보했고 무엇을 포기했는지 기록한다. 비용 상한 때문에 진행 중 수집을 무기한 유지하지 않는다. 메모리를 얻기 위해 항상 중지하거나 하이버네이션시키는 방식은 기본 수집으로 사용하지 않는다.

### 7.1 EBS 보존의 실제 상태 전이

1. 수집 전 volume ID, attachment, filesystem 정보, block device mapping, DeleteOnTermination, KMS key, instance state를 기록한다.
2. 사전에 설정한 workload customer-managed key로 암호화된 모든 대상 EBS를 확인한다. snapshot request token/job과 API 결과를 저장한다.
3. snapshot이 completed인지 확인한다. 다중 볼륨이면 일관성 범위·생성 방식과 시각을 기록한다. 애플리케이션 캐시까지 일관성이 보장된다고 표시하지 않는다.
4. Security copy 역할만 shared snapshot/key를 사용할 수 있게 한다.
5. Security 계정에서 evidence-ebs 키로 복사하고 완료·owner/key를 확인한다.
6. 복사 완료 후 불필요한 임시 공유를 정리한다. 실제 보존 정책에 따라 Workload 원본 snapshot의 수명을 별도 관리한다.
7. 분석은 운영 snapshot을 변경하지 않는 새 작업 복사본에서 수행한다.

암호화된 raw disk의 전체 SHA-256이 필요하면 적절한 도구로 이미지/스트림을 추출·해시해야 한다. snapshot ID·원본 volume ID·API 성공을 같은 수준의 content hash로 보고하지 않는다.

### 7.2 임시 분석 VM과 키 경계

증거 보존용 snapshot은 Security 소유로 유지한다. 1차 랩의 임시 분석 VM은 Workload forensic-a에 생성할 수 있지만, 이 위치를 독립된 보안 계정 분석 환경으로 부르지 않는다. 조사 중인 계정 전체의 관리자 탈취를 가정하면 이 작업 경로를 사용하지 않는다.

선택 사건의 분석용 snapshot 복사본만 제한적으로 제공하고, 최종 증거 키의 관리 권한은 주지 않는다. 새로운 작업 볼륨을 읽기 전용으로 마운트하고 auto-mount/write 여부를 검사한다. 강한 계정 격리 분석이 필요한 단계에서는 Security의 임시 VPC·SSM endpoints·VM 비용을 별도로 산정한다. 원본 triage 파일의 1차 분석은 로컬 격리 환경으로 진행해 이 추가 인프라를 필수로 두지 않는다.

### 7.3 RDS 증거 보존

RDS MySQL은 기본 DB다. DB identifier/resource ID·endpoint·subnet/SG·engine·parameter/option group·backup/retention·KMS를 보존하고, CloudWatch 엔진 로그와 관련 CloudTrail을 먼저 수집한다.

선정 사건만 manual DB snapshot을 만들고 available 상태를 확인한다. 암호화 공유용 고객 관리 키를 사전에 사용하며, 제한된 Security 계정 공유 후 Security 소유 키로 copy 완료를 확인한다. 공유 접수와 독립 사본 완료를 구분한다. RDS snapshot은 EBS에 연결할 이미지가 아니며 필요하면 별도 DB 인스턴스로 복원해 검증한다. 스냅샷만으로 메모리·SQL 이력·조회 결과 전체가 확보되지 않는다.

[공식 snapshot 공유·제약](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_ShareSnapshot.html)

## 8. 수집부터 포렌식 조사까지의 데이터 처리

### 8.1 공통 증거 envelope

~~~json
{
  "schema_version": "1.0",
  "case_id": "CASE-EXAMPLE",
  "collection_job_id": "JOB-EXAMPLE",
  "provider": "aws",
  "account_id": "WORKLOAD_ACCOUNT_ID",
  "region": "ap-northeast-2",
  "resource_id": "i-EXAMPLE",
  "scope": "host-live-root",
  "source": {
    "bucket": "security-evidence-example",
    "key": "cases/CASE-EXAMPLE/raw/audit.log",
    "version_id": "EXAMPLE_VERSION",
    "sha256": "EXAMPLE_SHA256",
    "size_bytes": 0
  },
  "times": {
    "event_time_raw": null,
    "collected_at": "2026-09-09T01:00:00Z",
    "received_at": "2026-09-09T01:02:00Z",
    "parsed_at": null
  },
  "collector": {"name": "velociraptor", "version": "LOCK_AT_A0", "profile_hash": "EXAMPLE"},
  "integrity_status": "UPLOADED_UNVERIFIED",
  "coverage": {"requested": ["linux-audit"], "collected": ["linux-audit"], "missing": []}
}
~~~

API event time, 파일 시스템 메타데이터 시각, 수집 시각, 분석 시각을 합치지 않는다. event_time_raw가 없는 증거 파일에 수집 시각을 실행 시각처럼 채우지 않는다. 스냅샷에는 파일용 SHA 대신 snapshot metadata 계약을 사용한다.

### 8.2 처리 단계

| 단계 | 입력 | 출력·검사 | 재시도 식별 |
|---|---|---|---|
| 로그 수집 | S3 객체·Agent 이벤트 | raw reference, ECS 조회용 이벤트, parse issue | object version / native event ID |
| 경보 수집 | Elastic alert alias | 원본 alert, 독립 case 제어 요청 | space + alert UUID + playbook version |
| 대상 보강 | 경보 resource/session·host와 당시 inventory | verified target 또는 unresolved target, host 없는 사건 허용 | account + region + resource type/ARN + valid time |
| 사건 수집 | resource별 AWS profile·선택 SSM·EBS/RDS API | 작업 상태·출력 위치·도구 이력 | case + host + profile + job |
| 무결성 검사 | ZIP·원본·manifest | VERIFIED/PARTIAL/FAILED와 범위 | original hash + object version |
| 파싱 | EVTX/JSON/CSV/파일 | raw record + normalized fields + parser version | source hash + locator + parser version |
| 외부 탐지 | AWS/Linux/EVE·검토 rule set | Suricata/Sigma/Elastic 결과·원본 locator, Windows는 선택 | engine + ruleset commit + source + match locator |
| 관계 생성 | 검증한 native fields·inventory | edge basis와 후보/관찰 수준 | case + source records + relation rule version |
| AI 분석 | 제한한 evidence bundle | 가설·반증·인용·추가 조사 | bundle hash + model/prompt version |
| 사람 검토 | 사건·가설·증거 | 검토 상태·보고서·선택 대응 | reviewer + time + revision |

원본 보존 저장소, Elastic 관제 인덱스, Atlas 사건 DB는 각각 목적이 다르다. Elastic ILM에서 지웠다고 사건 원본까지 삭제하지 않는다. 동일 source의 여러 파서·재분석 결과는 버전별 파생물로 보존한다.

### 8.3 조사의 실제 연결 예

예시 질문: “웹 취약점이나 잘못된 권한으로 업무 데이터에 접근했고, 방어 정책은 어느 단계에서 작동했는가?”

1. WAF의 요청 검사와 Suricata의 실제 verdict를 확인하고 정상 canary로 관측 결손을 구분한다.
2. ALB target/trace·Nginx/Apache request ID·앱 사용자/작업·응답을 대조한다. 모든 제품의 ID가 같다고 가정하지 않는다.
3. WEB/APP host와 당시 EC2/ENI/IP, Linux boot ID·process entity/시작 시각·audit serial로 실행 후보를 좁힌다.
4. 파일 생성은 audit/Defend·실제 파일 hash·경로·scope로 비교한다. 같은 worker/PID나 가까운 시각만으로 특정 HTTP 요청과 인과를 확정하지 않는다.
5. RDS는 DB 계정·thread/connection ID·엔진 쿼리·앱 결과를 대조한다. general log만으로 SELECT 결과까지 확정하지 않는다.
6. AWS 자료 접근은 role/session·accessKeyId(비밀 키 제외)→CloudTrail eventID/API/resource→S3 object/version 또는 secret metadata로 조사한다.
7. EC2 IMDS에서 자격증명을 가져온 과정이 CloudTrail에 별도 이벤트로 남는다고 가정하지 않는다. SSRF 앱 기록·호스트 관측과 이후 AWS API 활동을 대조하고 중간 증거가 없으면 gap으로 남긴다.
8. 변경 전후 SG·IAM·DB 정책과 실제 요청/연결 결과로 차단을 검증한다. ALB IP나 NAT IP를 바로 공격자 호스트로 확정하지 않는다.
9. AI는 지지·반박 증거와 누락을 제시하고 사람이 별도의 실행 정답과 비교한다.

RDS·S3·IAM·Secrets 사건은 EC2 호스트가 없어도 유효하다. manifest의 resource_type/resource_arn과 대상별 locator를 사용하며 host 필드는 해당될 때만 둔다.

## 9. 수집 환경 자체의 모니터링

공격 경보와 수집 파이프라인 상태는 별도 대시보드로 제공한다.

| 관측 대상 | 지표·상태 | 초기 조사 조건 |
|---|---|---|
| Agent | last seen, 수집 오류, API key 거부, policy revision | 예정 실행 중 5분 이상 heartbeat 없음 |
| OS/웹/EVE/RDS 로그 | 마지막 원본 시각, 채널 설정 hash, rotation·disk 사용량 | 설정 불일치, 빠른 회전, 수집 오류 |
| S3 landing | 주기적 정상 canary의 object 도착 | WAF canary 뒤 15~20분에도 도착하지 않음 |
| S3 archive | replication pending/failed, source·destination version/건수 | 복제 오류 또는 목표 지연 초과 |
| SQS | oldest message, retry count, DLQ, consumer progress | backlog 증가·DLQ 발생 |
| Elastic | ingest lag, parser failures, disk watermark, JVM·index write block | 원본은 도착했는데 조회 이벤트 없음 |
| 사건 자동화 | failed/timed out/retry, 중복 작업, 대상 검증 거부 | 새 snapshot/SSM 비용 작업 반복 |
| 증거 검증 | manifest 누락·해시 불일치·범위 누락 | 완료 표시 금지, PARTIAL/FAILED |
| KMS·IAM | AccessDenied, key 상태·policy drift, 역할 변경 | 수집·해독 불가, 예상치 못한 trust 변경 |
| 비용·자원 | running hours, snapshot/volume count, bytes, ExpiresAt | 사전 설정 상한 초과·기한 지난 자원 |

canary는 정상 요청과 안전한 알려진 이벤트를 주기적으로 발생시키는 시험이다. “로그가 없다”를 “공격이 없다”로 해석하지 않고, 정상 이벤트도 관측되지 않는 상태를 수집 결손으로 구분한다. 임계치는 운영 예정 시간·작업 모드에만 적용한다.

단계별 event_time/received/parsed/alert/case/collected 시간을 기록해 공급자 전달 지연과 우리 처리 지연을 분리한다. AI가 분석한 window에는 source별 coverage와 gap을 같이 보여준다.

## 10. 네트워크 격리·자격증명 대응·증거 보존의 순서

기본 collect-only 모드와 사전 지정한 contain 모드를 둔다. 워크플로는 host 중지보다 메타데이터·휘발 정보 확보를 우선하고, 진행 중 피해를 제한할 필요가 있으면 수집과 격리를 병행한다.

- SG·ALB target 조치는 API 성공 후 실제 새 연결·기존 연결을 시험한다. [기존 연결 추적](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-connection-tracking.html)
- AWS role session 악용이 의심되면 관련 role/session과 권한을 보존하고, scope를 검증한 identity 대응을 별도 수행한다. instance profile을 떼었다고 이미 발급된 토큰이 즉시 모두 무효화됐다고 가정하지 않는다. [역할 세션 취소](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_revoke-sessions.html)
- 수집에 쓰이는 동일 역할을 차단하면 SSM·업로드도 끊길 수 있다. 의심 앱 권한과 증거 수집 권한을 사전에 분리하는 이유다. 영향 받은 호스트 OS 관리자가 수집 권한을 이용할 수 있다는 한계도 명시한다.
- 삭제·KMS disable·로그 중지 권한은 격리 플레이북에 포함하지 않는다.
- 복구는 원래 SG·identity 정책으로 단순 덮어쓰지 않고 이후 변경과 충돌을 확인한다. 모든 대응 단계는 시각·대상·실행자·결과를 남긴다.

## 11. 구축 순서와 배포 전 검증 게이트

| 순서 | 구축·산출물 | 통과해야 다음 단계 진행 |
|---|---|---|
| G0 | 계정·권한·크레딧·대역·도구 버전 결정, OpenTofu validate/plan | 계정별 비용 적용, source·license lock, 대상 범위 확인 |
| G1 | Security S3/KMS/역할/state·CloudTrail | 임의 Workload role의 증거 삭제·키 변경 거부, 감사 로그 도착 |
| G2 | Workload VPC/SG/endpoints/instance roles/EBS key | 허용 통신 성공·우회 통신 거부, SSM/NAT 차단 시험 |
| G3 | Linux·Agent·Suricata·logging config와 inventory | 실제 필요한 event 생성·원본/Elastic 도착·회전 시험 |
| G4 | WordPress·RDS·S3 배치와 정상 workload | request/trace·DB 연결 식별자 기록, 정상 canary |
| G5 | WAF/IPS·CloudTrail data/Flow/DNS/RDS·archive·실제 공격 대조 | 원본·archive 대조, replica 실패 표시, 외부 data event 확인 |
| G6 | 경보→AWS 원본/선택 Linux 수집→manifest→Atlas | 원본부터 인용까지 역추적, 중복·부분 실패 시험 |
| G7 | 스냅샷 계정 간 copy·격리·identity 대응 | 키 소유권·완료 상태·기존 연결·관리 통신·복구 확인 |
| G8 | 분석·AI 평가·내보내기·종료 | source coverage·정답 비교·로컬 재열람·잔여 과금 목록 |

G1의 일부 수신 시험은 G2에서 생성한 제한된 테스트 역할로 확인한다. G1 저장·정책을 먼저 준비하고 최소 테스트 역할을 만든 뒤 시험을 끝내는 순서이며, 역할 없이 시험에 통과했다고 기록하지 않는다.

Terraform/OpenTofu plan은 IAM·수집 의미 검증을 대신하지 않는다. 정책 시뮬레이션과 실제 허용·거부 API 시험, 원본 로그 샘플, 해시·CLI 출력이 있어야 완료 처리한다. 실제 계정 생성·배포는 검토 가능한 계획과 계정별 비용이 준비된 후 진행한다.

## 12. 예산·잔여 제한

전체 DESIGN의 100시간/1개월 가정을 유지한다. 두 계정에서 원본 로그 복제·증거 staging/final·독립 EBS snapshot 사본·추가 KMS 사용으로 저장량이 늘어난다. Linux WEB/APP/SOC와 RDS, 단기 실험 자원의 변경 단가는 BUILD_AND_ATTACK.md 9와 전체 DESIGN 비용표를 적용한다. **$200~250은 계획 범위**이며 상시 관리형 IPS/OpenSearch 비용은 포함하지 않는다. 세금·계정별 크레딧 적용·실제 자료량은 별도다.

저장 제한: 초기 사건 3~5건, host 업로드 10GiB/사건 20GiB, 선택 호스트당 보존 snapshot 2개. source·destination snapshot과 작업 볼륨을 모두 합산해 집계한다. archive의 비현재 버전·staging 미완료 multipart도 비용 목록에 넣는다. 실험을 늘리기 전에 로컬 내보내기와 실제 비용을 확인한다.

보안 계정에 상시 SOC·NAT·대규모 EFS/DataSync를 추가하지 않는다. 향후 구성 시 별도 비용표와 동작 검증이 필요하다. Organizations 가입만으로 교육 크레딧이 다른 계정의 모든 서비스에 적용된다고 가정하지 않는다.

초기 single-region data plane은 서울에 두지만 CloudTrail은 다른 리전·global identity 활동을 관측할 수 있게 설계한다. 비용 통제를 위해 서비스를 한 리전에서 운영하는 것과 감사 범위를 한 리전만으로 제한하는 것은 다른 결정이다.

## 13. 최종 산출물과 미정 값

산출물은 OpenTofu 코드·provider lock, 계정/role/SG/route 표, logging config, 수집 profile·도구 lock, raw 예시·manifest schema, source별 parser/상관 계약, 파이프라인 상태 대시보드, 사건 결과·AI 평가, 종료 점검 보고서다.

배포 전 확정할 값은 실제 계정 ID·크레딧 적용, domain/TLS 선택, OS·Elastic·도구 안정 버전, 실제 IAM API별 ARN/condition, log volume·rotation·retention, 아티팩트별 최소 수집 집합이다. 이 값은 실제 샘플·계정 조건을 확인한 뒤 채우며 지금 배포 완료나 수집 가능 확정으로 표시하지 않는다.

---

## 14. 구현 사양 보완 — EventBridge·Step Functions·DynamoDB

이전 절까지는 "무엇을 수집하고 어떤 순서로 보존하는가"를 정의했다. 이 절은 **자동화 파이프라인의 구체적 입출력 계약**을 보완한다.

### 14.1 EventBridge 이벤트 스키마

경보 수집기(SOC VM)가 Elastic Security 경보를 수집하여 EventBridge에 전달하는 이벤트.

```json
{
  "Source": "evidence-atlas.alert-collector",
  "DetailType": "SecurityAlertCollected",
  "EventBusName": "ea-security-events",
  "Detail": {
    "schema_version": "1.0",
    "alert_id": "<kibana alert UUID>",
    "rule_id": "<detection rule UUID>",
    "rule_name": "D01-waf-sqli-repeat",
    "space_id": "default",
    "severity": "medium",
    "detected_at": "2026-09-15T10:23:00.000Z",
    "source_indices": ["logs-aws.waf-*"],
    "target": {
      "type": "ec2",
      "instance_id": "i-0abc123def456",
      "ip": "10.60.2.10",
      "role_arn": null,
      "rds_id": null
    },
    "signal_fields": {
      "client_ip": "10.60.9.100",
      "matched_rules": ["AWSManagedRulesSQLiRuleSet"],
      "request_path": "/wp-login.php",
      "count": 8
    },
    "collector": {
      "host": "soc-vm",
      "cursor": "1726393380000::alert-uuid-123",
      "collected_at": "2026-09-15T10:23:30.000Z"
    }
  }
}
```

**EventBridge 규칙 — 자동 사건 생성:**

```json
{
  "source": ["evidence-atlas.alert-collector"],
  "detail-type": ["SecurityAlertCollected"],
  "detail": {
    "severity": ["high", "critical"]
  }
}
```

medium 이하는 DynamoDB `ea-alert-queue` 테이블에 기록하고 수동 검토 대기한다. 5분 내 동일 `rule_id`로 3건 이상 집계되면 별도 EventBridge 규칙이 자동 사건으로 승격한다.

### 14.2 Step Functions 상태 기계 정의 (의사 ASL)

```json
{
  "Comment": "EA 증거 수집 워크플로 v1.0",
  "StartAt": "ValidateInput",
  "TimeoutSeconds": 1800,
  "States": {

    "ValidateInput": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:SECURITY_ACCT:function:ea-validate-case",
      "Parameters": {
        "case_id.$": "$.case_id",
        "trigger.$": "$.trigger",
        "target.$": "$.target"
      },
      "ResultPath": "$.validation",
      "Next": "IsValid",
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "RecordFailure" }]
    },

    "IsValid": {
      "Type": "Choice",
      "Choices": [
        { "Variable": "$.validation.status", "StringEquals": "VALID", "Next": "PreserveMetadata" },
        { "Variable": "$.validation.status", "StringEquals": "DUPLICATE", "Next": "SkipDuplicate" }
      ],
      "Default": "RecordFailure"
    },

    "PreserveMetadata": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:SECURITY_ACCT:function:ea-preserve-metadata",
      "Parameters": {
        "case_id.$": "$.case_id",
        "target.$": "$.target",
        "workload_role_arn": "arn:aws:iam::WORKLOAD_ACCT:role/EACollectionTarget"
      },
      "ResultPath": "$.metadata",
      "TimeoutSeconds": 120,
      "Next": "ParallelCollection",
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.metadata_error", "Next": "ParallelCollection" }]
    },

    "ParallelCollection": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "CollectAWSLogs",
          "States": {
            "CollectAWSLogs": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:REGION:SECURITY_ACCT:function:ea-collect-aws-logs",
              "Parameters": {
                "case_id.$": "$.case_id",
                "target.$": "$.target",
                "time_window_minutes": 15
              },
              "End": true,
              "TimeoutSeconds": 300
            }
          }
        },
        {
          "StartAt": "CheckHostTarget",
          "States": {
            "CheckHostTarget": {
              "Type": "Choice",
              "Choices": [
                { "Variable": "$.target.instance_id", "IsPresent": true, "Next": "TriggerHostCollection" }
              ],
              "Default": "SkipHost"
            },
            "TriggerHostCollection": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:REGION:SECURITY_ACCT:function:ea-trigger-host-collection",
              "Parameters": {
                "case_id.$": "$.case_id",
                "instance_id.$": "$.target.instance_id",
                "ssm_document": "EA-VelociraptorOfflineCollect",
                "staging_bucket": "ea-evidence-staging"
              },
              "End": true,
              "TimeoutSeconds": 600
            },
            "SkipHost": { "Type": "Pass", "Result": { "skipped": true, "reason": "no_instance_id" }, "End": true }
          }
        },
        {
          "StartAt": "CheckSnapshotNeeded",
          "States": {
            "CheckSnapshotNeeded": {
              "Type": "Choice",
              "Choices": [
                { "Variable": "$.trigger.scenario", "StringMatches": "S4*", "Next": "TakeSnapshots" },
                { "Variable": "$.trigger.scenario", "StringMatches": "S6*", "Next": "TakeSnapshots" }
              ],
              "Default": "SkipSnapshot"
            },
            "TakeSnapshots": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:REGION:SECURITY_ACCT:function:ea-take-snapshots",
              "End": true,
              "TimeoutSeconds": 900
            },
            "SkipSnapshot": { "Type": "Pass", "Result": { "skipped": true }, "End": true }
          }
        }
      ],
      "ResultPath": "$.collection_results",
      "Next": "VerifyIntegrity",
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.collection_error", "Next": "VerifyIntegrity" }]
    },

    "VerifyIntegrity": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:SECURITY_ACCT:function:ea-verify-finalize",
      "Parameters": {
        "case_id.$": "$.case_id",
        "collection_results.$": "$.collection_results",
        "metadata_error.$": "$.metadata_error"
      },
      "ResultPath": "$.verification",
      "Next": "FinalStatus"
    },

    "FinalStatus": {
      "Type": "Choice",
      "Choices": [
        { "Variable": "$.verification.integrity", "StringEquals": "PASS", "Next": "CaseReady" },
        { "Variable": "$.verification.integrity", "StringEquals": "PARTIAL", "Next": "CasePartial" }
      ],
      "Default": "CaseFailed"
    },

    "CaseReady":   { "Type": "Pass", "Result": "READY",   "ResultPath": "$.final_status", "End": true },
    "CasePartial": { "Type": "Pass", "Result": "PARTIAL", "ResultPath": "$.final_status", "End": true },
    "CaseFailed":  { "Type": "Pass", "Result": "FAILED",  "ResultPath": "$.final_status", "End": true },
    "SkipDuplicate": { "Type": "Pass", "Result": "DUPLICATE", "ResultPath": "$.final_status", "End": true },
    "RecordFailure": { "Type": "Pass", "Result": "VALIDATION_FAILED", "ResultPath": "$.final_status", "End": true }
  }
}
```

### 14.3 Lambda 함수 계약

| 함수 | Runtime | Timeout | Memory | IAM 핵심 권한 | 입력 | 출력 |
|------|---------|---------|--------|-------------|------|------|
| ea-validate-case | Python 3.12 | 30s | 256MB | dynamodb:GetItem/PutItem(ea-dedup), s3:GetObject(allowed-targets) | case_id, trigger, target | {status: VALID/DUPLICATE/INVALID, case_id} |
| ea-preserve-metadata | Python 3.12 | 120s | 512MB | sts:AssumeRole(Workload), ec2:Describe*, rds:Describe*, iam:Get*, s3:PutObject(staging) | case_id, target, workload_role_arn | {preserved: [instance,sg,role,...], errors: []} |
| ea-collect-aws-logs | Python 3.12 | 300s | 512MB | cloudtrail:LookupEvents, s3:GetObject(waf/alb-logs), s3:PutObject(staging) | case_id, target, time_window_minutes | {sources: {cloudtrail: {count,size}, waf: {...}, ...}} |
| ea-trigger-host-collection | Python 3.12 | 600s | 256MB | ssm:SendCommand(Workload), ssm:GetCommandInvocation, s3:PutObject(staging) | case_id, instance_id, ssm_document, staging_bucket | {command_id, status, output_key} |
| ea-verify-finalize | Python 3.12 | 120s | 512MB | s3:GetObject/PutObject/CopyObject(staging→final), dynamodb:UpdateItem(ea-cases) | case_id, collection_results, metadata_error | {integrity: PASS/PARTIAL/FAIL, manifest_key, missing: []} |

### 14.4 DynamoDB 테이블 설계

**ea-cases** — 사건 상태 관리

| 속성 | 타입 | 역할 |
|------|------|------|
| case_id (PK) | S | CASE-{ulid} |
| created_at | S | ISO 8601 |
| status | S | RECEIVED/VALIDATED/COLLECTING/READY/PARTIAL/FAILED/ANALYZING/REVIEW_REQUIRED/CLOSED |
| trigger | M | 원본 EventBridge detail 전체 |
| target | M | {type, instance_id, ip, role_arn, rds_id} |
| manifest_key | S | S3 final 경로 |
| jobs | L | [{job_id, source, status, size_bytes, sha256}] |
| updated_at | S | 마지막 상태 변경 시각 |

GSI: `status-index` (PK=status, SK=created_at) — 상태별 조회용

**ea-dedup** — 경보 중복 방지

| 속성 | 타입 | 역할 |
|------|------|------|
| dedup_key (PK) | S | {space_id}#{alert_id}#{playbook_version} |
| case_id | S | 연결된 사건 ID |
| created_at | S | ISO 8601 |
| ttl | N | Unix epoch + 7일 (DynamoDB TTL) |

**ea-alert-queue** — medium 이하 경보 대기열

| 속성 | 타입 | 역할 |
|------|------|------|
| alert_id (PK) | S | Kibana alert UUID |
| rule_id | S | 탐지 규칙 ID |
| severity | S | low/medium |
| received_at | S | ISO 8601 |
| signal_fields | M | 핵심 필드 요약 |
| promoted | BOOL | 사건으로 승격 여부 |
| ttl | N | Unix epoch + 3일 |

GSI: `rule-time-index` (PK=rule_id, SK=received_at) — 5분 집계 쿼리용

### 14.5 SSM 문서 — Velociraptor 오프라인 수집

```yaml
schemaVersion: "2.2"
description: "EA Velociraptor Offline Collector"
parameters:
  CaseId:
    type: String
    description: "사건 ID"
  StagingBucket:
    type: String
    default: "ea-evidence-staging"
  CollectionProfile:
    type: String
    default: "standard"
    allowedValues: ["minimal", "standard", "full"]
mainSteps:
  - action: aws:runShellScript
    name: runCollector
    inputs:
      runCommand:
        - |
          #!/bin/bash
          set -euo pipefail
          CASE_DIR="/tmp/ea-collect-{{ CaseId }}"
          mkdir -p "$CASE_DIR"
          
          # 사전 설치된 고정 바이너리 실행
          /opt/ea-tools/velociraptor-collector \
            --profile {{ CollectionProfile }} \
            --output-dir "$CASE_DIR" \
            2>&1 | tee "$CASE_DIR/collector.log"
          
          # staging S3로 업로드
          aws s3 cp "$CASE_DIR/" \
            "s3://{{ StagingBucket }}/cases/{{ CaseId }}/host-triage/" \
            --recursive --expected-size $(du -sb "$CASE_DIR" | cut -f1)
          
          # 정리
          rm -rf "$CASE_DIR"
      timeoutSeconds: "300"
```

### 14.6 비용 모드 분리 보완

NAT Gateway와 SSM endpoints의 동시 운용에 따른 이중 비용 문제를 해결하기 위해 운영 모드를 나눈다.

| 모드 | 활성 리소스 | NAT | SSM endpoints | 월 추가비용 |
|------|-----------|-----|---------------|-----------|
| **setup** | EC2+RDS+ALB+NAT | ✅ | ❌ | ~$4.5/hr (NAT) |
| **operate** | EC2+RDS+ALB+endpoints | ❌ | ✅ (ssm, ssmmessages, ec2messages) | ~$2.6/hr (endpoints 3개) |
| **idle** | RDS 중지/삭제 | ❌ | ❌ | EBS+S3만 |

전환 절차:
1. setup→operate: NAT 삭제, EIP 해제, SSM endpoints 생성, private 서브넷 라우팅 변경
2. operate→idle: EC2 중지, ALB 삭제, endpoints 삭제, RDS 7일 이내 재중지 또는 스냅샷 후 삭제
3. idle→setup: NAT 재생성, EIP 할당, EC2/ALB/RDS 재시작

OpenTofu에서 `var.operation_mode` 변수로 리소스 `count`를 제어한다.
