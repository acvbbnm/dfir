# AWS 서비스·방어·관제 인프라와 구축·공격 계획

> 2026-09-16 실행 기준: [시나리오 v1.1](scenarios/SCENARIO_LIBRARY.md)·[수정/지원 범위](results/SCENARIO_FIXES.md). 아래의 SQS·landing 복제·snapshot copy·host 없는 자동 사건·고급 상관·대응 실행기는 후속 목표이며 현재 구현 완료를 뜻하지 않는다. S0~S6는 준비 검사, N/W/H/C/I/D/E/X/K는 본 실험 ID다.


> **2026-09-15 구현/검증 대조:** 이 문서의 장기 목표와 과거 후보 구성을 현재 완료 상태로 해석하지 않는다. 현재 기준선은 [DEPLOYMENT.md](DEPLOYMENT.md), 수행된 검사는 [LOCAL_VALIDATION.md](results/LOCAL_VALIDATION.md)다. ModSecurity 기본·내부 ALB·선택 test-a 실행기·초기 Atlas 오프라인 import까지 준비했으며 AWS 수락/전체 분석·대응은 미완료다.

> 2026-09-11 구현 보완: [로컬 검증 기록](results/LOCAL_VALIDATION.md)과 [실행·잔여 작업](LOCAL_DEVELOPMENT.md)을 확인한다. 현재 operate 모드는 SSM 계열 3개 + 일반 API 6개로 interface endpoint 총 9개다. 이전 2~3개 기준 비용표는 현재 IaC의 확정 견적이 아니며 실제 단가·실행 시간으로 재산정해야 한다. AWS 배포는 아직 수행하지 않았다.


작성일: 2026-09-09 · 개정안 0.3 · 상태: 설계 제안, 미배포·미검증

이 문서는 서버 구성 → 정상 웹서비스 → 방어 정책 → 로그 수집 → SIEM 탐지 → 실제 공격·차단 검증의 기준이다. 기존 Windows APP·EC2 MySQL 중심 0.2안의 해당 결정을 대체한다. 운영할 서비스와 AWS 권한 경계부터 정하고 포렌식 기능을 뒤에 연결한다. 제시한 용량·임계치·주소는 초기 설계값이며 실제 출력으로 통과 여부를 기록해야 한다.

## 1. 운영할 서비스와 공격 대상

### 1.1 정상 서비스: WordPress 기반 소규모 기업 포털

직접 업무용 웹앱 전체를 새로 개발하지 않고 WordPress를 사용한다. 회사 소개, 공지·게시판, 회원 로그인, 편집자의 글 등록, 관리자의 계정·콘텐츠 관리, 이미지·문서 자료실을 구현한다. 결제·실제 개인정보·메일 발송은 초기 기능에 포함하지 않는다.

| 항목 | 구체적인 구성 |
|---|---|
| WEB | Ubuntu 24.04 LTS, Nginx 역방향 프록시, HTTP 접근·오류 로그, Suricata inline |
| APP | Ubuntu 24.04 LTS, Apache 2.4 + PHP-FPM 8.3 이상, WordPress, 웹 감사 JSON |
| DB | Amazon RDS for MySQL 8.4 계열, Single-AZ, private, gp3 20GB 시작 |
| 업무 데이터 | 가상 회원 20명, 관리자 1명·편집자 2명, 게시글 50개, 이미지·PDF 20개 |
| 객체 저장소 | 업무용 S3 버킷. 별도 배치 역할이 게시글 내보내기와 선정 자료를 reports/에 저장 |
| DB 자격증명 | Secrets Manager의 app-db secret. 시작 시 지정 역할로 조회해 권한 제한 파일에 배치 |
| 정상 활동 | 열람, 정상·실패 로그인, 글 등록·수정, 자료 업로드, 승인된 배치·관리 작업 |

WordPress·PHP·MySQL 조합은 공식 요구사항에 맞춘 후보이며, 정확한 패치와 플러그인·배포 해시는 B01에서 고정한다. 플러그인은 필요한 최소 수만 선정하고 기본 WordPress가 로그인·권한 변경을 모두 구조화해 기록한다고 가정하지 않는다. 감사용 mu-plugin 또는 검증한 감사 플러그인을 별도 산출물로 둔다. [WordPress 요구사항](https://wordpress.org/about/requirements/)

### 1.2 공격 대상은 목적별로 재현 가능하게 구성

- **웹 취약점 검증:** DVWA를 APP의 별도 가상호스트와 PHP-FPM 사용자, 별도 dvwa DB 계정·스키마로 배치한다. WordPress의 정상 코드·업로드 실행 정책을 약화시키지 않는다. SQL Injection·Command Injection·파일 업로드 취약점의 실제 동작을 검증한다. [DVWA](https://github.com/digininja/DVWA)
- **AWS 권한 악용 검증:** CloudGoat ec2_ssrf의 취약 앱·IAM 설계에서 필요한 부분을 검토해 별도 단기 실험 APP에 적용한다. 사설 서브넷·프로젝트 자원 한정 권한으로 수정하며, 정상 APP의 instance profile을 그대로 약화하지 않는다. 원본 전체 배포·장기 관리자 키·계정 전체 권한은 기본안에 포함하지 않는다. [CloudGoat 시나리오](https://github.com/RhinoSecurityLabs/cloudgoat/tree/master/cloudgoat/scenarios/aws/ec2_ssrf)
- 웹 침해와 IAM 악용은 독립 실험부터 시작한다. 실제로 연결된 실행 경로와 증거를 확보한 경우에만 하나의 공격 체인으로 평가한다.
- 공격 도구는 test 서브넷의 실행기에서 소유한 사설 대상과 지정한 실험용 AWS 리소스만 다룬다. DNS가 허용 대상에서 벗어나면 실행을 중단한다.
- 각 실험 종료 시 로그·증거를 먼저 보존하고 앱 파일·DB·IAM·WAF·IPS 정책을 기록된 기준선으로 복구한다.

## 2. 서버·계정·수명

| 구성 | 배치 | 초기 사양 | 실행 계획 |
|---|---|---|---|
| WEB 1대 | Workload / DMZ 서브넷 | t3.medium, 4GiB, gp3 20GB | 최대 100시간 |
| APP 1대 | Workload / APP 서브넷 | t3.medium, 4GiB, gp3 30GB | 최대 100시간 |
| RDS MySQL 1개 | Workload / DB subnet group | db.t4g.micro, gp3 20GB, Single-AZ | 최대 100시간, 성능 부족 시 크기·견적 재검토 |
| SOC 1대 | Workload / 관리 서브넷 | t3.xlarge, 16GiB, gp3 100GB | Elasticsearch·Kibana·Fleet·로그 수집기, 최대 100시간 |
| 실행기 1대 | Workload / test 서브넷 | t3.small, 임시 gp3 | 정상·공격 요청, 총 20시간 초기 상한 |
| CloudGoat 실험 APP | Workload / 실험 APP 서브넷 | 소형 Linux EC2, 임시 | 실험 시간만 생성, 기본 APP과 역할·SG 분리 |
| 분석 작업 VM | 사건에 따라 임시 | Linux, 필요한 복사 볼륨만 | 로컬 분석 불가한 디스크 작업만, 건당 2시간 상한 |
| Security/Evidence 계정 | 저장·제어 전용 | S3·KMS·Step Functions·Lambda·DynamoDB | 상시 SOC·NAT·EFS 없음 |

기본은 서울 1리전, Workload와 Security/Evidence 2계정이다. 크레딧 적용과 두 계정 사용 가능 여부는 배포 전에 확인한다. 단일 계정 대안은 기능 검증에는 쓸 수 있으나 계정 관리자 침해에 대한 독립 증거 보관을 주장하지 않는다.

인프라는 고가용성 운영을 재현하는 구성이 아니다. ALB와 DB subnet group의 2개 AZ 요구를 충족하면서 WEB·APP·SOC·RDS 실행 노드는 한 AZ에 둔다. EDR을 RDS 호스트에 설치할 수 있다고 설계하지 않는다.

## 3. 트래픽과 DMZ

~~~mermaid
flowchart TB
    TEST["test 서브넷<br/>정상 사용자·공격 실행기"] -->|"HTTPS 443"| ALB["내부 ALB · 2 AZ"]
    WAF["AWS WAF"] -. "Web ACL 연결" .-> ALB
    ALB -->|"HTTP 8080"| WEB["DMZ: WEB<br/>Suricata NFQUEUE → Nginx"]
    WEB -->|"HTTP 8080"| APP["APP: Apache · PHP-FPM<br/>WordPress / 실험 가상호스트"]
    APP -->|"TLS 3306"| RDS["DB: RDS MySQL"]
    APP -->|"역할로 지정 secret 조회"| SM["Secrets Manager"]
    BATCH["별도 자료 내보내기 역할"] -->|"지정 prefix"| DATA["S3 업무 자료"]
    APP -. "OS·Defend·웹 감사" .-> SOC["관리 구간: Elastic SIEM"]
    WEB -. "EVE·웹·OS" .-> SOC
    RDS --> CW["CloudWatch Logs"]
    CW --> SOC
    AWSLOG["WAF·ALB·CloudTrail·Flow·DNS"] --> LAND["S3 로그 수집·중앙 보관"]
    LAND -->|"SQS·수집기"| SOC
    SOC -->|"경보"| SOAR["Security: 사건·대응 워크플로"]
    SOAR --> EVID["Security: 증거 S3 / KMS<br/>EBS·RDS 복사 스냅샷"]
    EVID --> ATLAS["로컬 Evidence Atlas"]
~~~

| 서브넷 | 대역 제안 | 라우팅·노출 |
|---|---|---|
| egress-a | 10.60.0.0/24 | NAT 1개와 IGW, 서버 배치 없음 |
| ingress-a / ingress-c | 10.60.10.0/24 · 10.60.11.0/24 | 내부 ALB, 서로 다른 AZ |
| dmz-web-a | 10.60.2.0/24 | WEB, 공인 IP 없음, ALB SG의 요청만 수신 |
| app-a | 10.60.3.0/24 | APP, WEB SG에서만 업무 포트 수신 |
| db-a / db-c | 10.60.4.0/24 · 10.60.14.0/24 | RDS subnet group, IGW/NAT 기본 경로 없음 |
| management-a | 10.60.5.0/24 | SOC, SSM endpoints |
| test-a | 10.60.9.0/24 | 요청 실행기, 직접 APP·RDS 접근 거부 |
| forensic-a | 10.60.70.0/24 | 임시 분석, 기본 업무 접근 거부 |
| scenario-app-a | 10.60.80.0/24 | CloudGoat 단기 실험 자원, 전용 SG·role |

DMZ는 서브넷 이름만으로 생성되는 보안 경계가 아니다. VPC 내부 local 경로가 있으므로 SG의 입·출력 허용 목록으로 계층 간 접근을 제한한다. 기본 NACL은 별도 세부 차단을 중복 구현하지 않고, SG 정책을 실제 연결 시험으로 검증한다. NACL을 변경할 경우 stateless 반환 포트까지 별도 표·시험으로 관리한다.

기본 공격 경로는 내부 ALB다. 인터넷 공개 서비스 시연은 별도 정상 트래픽 프로필에서만 ALB의 노출·허용 IP·인증서를 변경한다. 두 경로의 비용과 정책을 혼합하지 않는다. 내부 HTTPS는 테스트 DNS와 신뢰 가능한 인증서 배포를 B02에서 구현하며 유료 ACM Private CA를 필수로 두지 않는다.

ALB에서 TLS를 종료하고 WEB/APP 간 실험 HTTP를 검사한다. 이 구간은 평문이다. 실제 민감 데이터 운영에 적용하려면 내부 TLS 및 복호화 지점의 검사 방식을 다시 설계해야 한다. RDS 연결은 CA 검증을 포함한 TLS를 정상 기준으로 한다.

### 3.1 보안 그룹 허용 목록

| ID | 출발 → 도착 | 허용 | 그 외 동작 |
|---|---|---|---|
| N01 | test SG → ALB SG | 443 | test → APP/RDS/SOC 직접 연결 거부 |
| N02 | ALB SG → WEB SG | 8080, /health 포함 | WEB의 임의 출처 8080 거부 |
| N03 | WEB SG → APP SG | 8080 | WEB → RDS 3306 거부 |
| N04 | APP SG → RDS SG | 3306 | 외부·WEB·test에서 DB 접근 거부 |
| N05 | WEB/APP Agent → SOC | TLS 9200·8220 | Kibana 5601 직접 공개 없음 |
| N06 | 관리 대상 → SSM endpoints | 443 | SSH/RDP 인터넷 인바운드 없음 |
| N07 | 역할을 가진 대상 → S3 gateway endpoint | 정책으로 지정 bucket/prefix | 증거 삭제·다른 사건 접근 거부 |
| N08 | APP → Secrets Manager regional API | 443, NAT 경로 + IAM 제한 | 다른 secret ARN 읽기 거부 |
| N09 | OS → VPC DNS·시간 동기화 | 지정 resolver/NTP 경로 | DNS 로그와 OS 동기화 상태 측정 |

WEB·APP·SOC 설치용 인터넷 HTTPS는 NAT를 통해 허용하고 실행 모드별 egress를 기록한다. SG는 도메인 필터가 아니므로 443 허용을 특정 사이트만 허용한 것으로 표현하지 않는다. 기본 VPC resolver DNS는 SG만으로 통제되지 않는다는 AWS 특성도 정책 검증에 포함한다. 더 강한 외부 통신 제어는 별도 DNS Firewall/Network Firewall 실험으로 추가한다.

## 4. 방어 정책

### 4.1 WAF: 웹 요청 단위 방어

- AWSManagedRulesCommonRuleSet, KnownBadInputsRuleSet, SQLiRuleSet을 후보로 고정한다. 처음 정상 트래픽으로 개별 규칙 Count를 평가한 뒤 확인한 규칙만 Block으로 전환한다.
- 알 수 없는 Host, 사용하지 않는 메서드, 비공개 설정 파일·백업 경로 접근을 차단한다. XML-RPC 미사용 시 해당 경로를 차단하고 WordPress REST API는 실제 사용 범위로 제한한다.
- /wp-login.php에 출처별 5분 100회 요청을 초기 rate 기준으로 둔다. 이는 로그인 실패 횟수가 아니며 AWS의 근사 rate 제어다. 실제 정상·공격 요청으로 임계치를 조정한다.
- 업로드 용량과 검사 가능한 body 크기·oversize 처리 정책을 구분한다. 파일 업로드 전체를 검사했다고 가정하지 않는다.
- 관리자 경로는 별도 관리 요청 경로·인증을 사용한다. client가 지정한 임의 헤더 하나로 관리자를 신뢰하지 않는다.
- 정책 version·rule ID·action·labels·rate 조건·예외 이유·변경자를 Git과 실행 기록에 남긴다.
- WAF에서 막힌 요청을 서버 침해 성공으로 보고하지 않는다. 실제 backend 미도달과 우회 접근 차단까지 확인한다.

[AWS baseline rule groups](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-baseline.html) · [개별 규칙 Count override](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-rule-group-override-options.html)

### 4.2 IPS: 검사 위치와 차단 조건

기본은 WEB 호스트의 Suricata + NFQUEUE다. ALB가 전달한 8080 트래픽과 그 반환 패킷을 Linux INPUT/OUTPUT의 전용 queue로 보내 Nginx에 도달하기 전에 검사한다. 일반 패킷 캡처만 켜고 IPS라고 표시하지 않는다.

- NFQ 지원 빌드, 양방향 큐 카운터, 실제 EVE alert/drop, 정상 요청 통과를 설치 검사로 남긴다.
- 초기에는 선택 룰을 alert로 평가한다. HTTP 공격 패턴·비정상 프로토콜 등 재현 검증된 소수 룰만 drop으로 승격한다. 룰셋 전체를 일괄 drop으로 바꾸지 않는다.
- 로그는 EVE JSON의 timestamp, flow_id, 5-tuple, signature_id/rev, action, HTTP 메타데이터, stats를 보존한다.
- 이 센서가 보는 네트워크 source는 ALB일 수 있다. ALB 주소를 공격자 주소로 차단하지 않고 WAF·웹 로그의 client 정보와 신뢰 경계를 함께 확인한다.
- 현재 bootstrap은 WEB queue에 `--queue-bypass`를 사용한 fail-open이다. 센서 중단 시 웹 통과와 수집 경보를 별도 검증한다. fail-closed는 후속 선택 모드이며 현재 구현/검증 완료로 표시하지 않는다. SSM/수집 통신은 queue 대상에서 제외한다.
- 검사 범위는 ALB↔WEB 웹 경로다. APP→RDS의 TLS 내용, 다른 ENI, AWS API 호출 전체를 검사하는 VPC 경계 IPS로 주장하지 않는다.
- 전용 네트워크 방화벽 비교 단계에서는 AWS Network Firewall을 단기 생성하고 별도 inspection subnet·대칭 왕복 route를 구성한다. 기본 예산에 상시 endpoint 비용을 넣지 않는다. NAT·VPC local 우회 경로가 검사되는지 먼저 검증한다.

[Suricata host/gateway inline·NFQUEUE](https://docs.suricata.io/en/suricata-8.0.1/ips/setting-up-ipsinline-for-linux.html) · [AWS Network Firewall 구조](https://docs.aws.amazon.com/network-firewall/latest/developerguide/what-is-aws-network-firewall.html) · [요금](https://aws.amazon.com/network-firewall/pricing/)

### 4.3 엔드포인트·애플리케이션

- WEB·APP에 Elastic Agent/Defend를 등록한다. 프로세스·파일·네트워크 수집과 사용할 예방 기능을 선택 버전·Basic 라이선스에서 실측한다. 유료 response action이나 모든 행위 예방을 전제하지 않는다.
- PHP/웹 서비스 사용자에게 root·sudo를 주지 않는다. WordPress 코드는 배포자가 관리하고, runtime은 지정 uploads/cache만 쓴다. 정상 uploads 디렉터리는 PHP 실행 금지다.
- 웹 계보의 shell 실행, 실행 가능 파일 생성, 새로운 cron/systemd 설정, 정상 배치에 없는 외부 접속을 탐지 후보로 삼는다. 이미지 변환·승인 배치·수집 도구 실행을 정상 대조군에 넣는다.
- Linux auditd는 선택한 exec와 앱 설정·예약 작업 변경을 기록하고 journal은 persistent·용량 제한·rotation을 설정한다.
- DVWA와 CloudGoat 실험 정책은 분리한다. 웹 RCE가 성립했다고 root 권한이나 IAM 관리자 권한을 확보한 것으로 취급하지 않는다.
- RDS에는 EDR을 설치하지 않는다. DB 사용자 권한·TLS·엔진 로그·AWS 변경 감사로 관측한다.

[Elastic 구독 기능표](https://www.elastic.co/subscriptions)

### 4.4 IAM·DB·데이터 정책

| 주체 | 정상 권한 | 검증할 거부 |
|---|---|---|
| WEB 역할 | SSM, 자기 수집 upload | DB secret·업무 S3 읽기 |
| APP 역할 | SSM, 지정 app-db secret 읽기, 자기 수집 upload | 다른 secret·IAM 정책 변경·증거 삭제 |
| 자료 배치 역할 | reports/ 지정 객체 작성·필요한 앱 데이터 export | private-fixtures/ 읽기·버킷 정책 변경 |
| WordPress DB 계정 | wordpress 스키마의 필요한 DML, 배포 때만 별도 DDL | 다른 DB·관리 계정·불필요 FILE 권한 |
| DVWA DB 계정 | dvwa 스키마, setup 권한은 실험 초기화 단계 | wordpress 스키마 |
| SOC 수집 역할 | 지정 로그 S3/SQS/CloudWatch read, ES ingest | 업무 데이터·최종 증거 변경 |
| Security 수집·대응 역할 | 태그·ARN 제한 수집·스냅샷·선택 격리 | 실험 외 자원 변경·로그 중지 |

RDS master 계정은 애플리케이션에서 사용하지 않는다. S3 Block Public Access·Versioning, KMS key 관리 권한 분리, 기본 IMDSv2 required를 적용한다. IMDSv1 기반 SSRF 비교는 CloudGoat 전용 실험 인스턴스에서만 설정 변경과 복원 이력을 남긴다.

## 5. 사용자가 제시한 중앙 로그 구조의 반영

참고 그림: images.jpg. 그림의 AWS 서비스 → S3/Firehose → 중앙 S3 → Lambda ETL → OpenSearch → 대시보드/SNS 흐름을 로그 수집 설계에 활용한다. 대응되는 공개 AWS 샘플은 [SIEM on Amazon OpenSearch Service](https://github.com/aws-samples/siem-on-amazon-opensearch-service)다. 현재 README·지원 로그 목록을 확인했으며 전체 코드 감사·배포를 완료한 것은 아니다.

| 그림 구성 | 우리 구성 |
|---|---|
| 여러 계정의 AWS 서비스 로그 | Workload의 WAF·ALB·CloudTrail·Flow·DNS·RDS와 호스트 로그 |
| Security Hub finding 집계 | 선택 단계. 원본 로그를 대신하지 않으며 GuardDuty/Security Hub를 필수 과금 서비스로 먼저 켜지 않음 |
| 중앙 S3 | Security 감사·archive, 필요한 서비스별 Workload landing에서 복제 |
| Firehose | 직접 S3 전달이 없는 소스에서 필요할 때 채택. 모든 로그에 중간 단계를 일괄 추가하지 않음 |
| Lambda es-loader | 파싱·ECS 정규화·중복/실패 처리 설계를 참고. 기존 Elastic과 인증·mapping·배포물을 호환 검증 없이 교체하지 않음 |
| OpenSearch / Kibana | 기본은 기존 Elastic/Kibana 1개. OpenSearch 채택은 별도 대안이며 두 SIEM을 중복 상시 운영하지 않음 |
| GeoIP | 공개 client IP가 있는 경우 선택 보강. 사설 IP 실험에서는 핵심 탐지 근거가 아님 |
| SNS 알림 | 초기 사건 대시보드, 통지 채널은 후속 구성. 알림 전송과 차단 실행을 구분 |

### 5.1 로그별 경로·의미·보존

| 소스 | 켜고 모을 항목 | SIEM 경로 | 경보·조사에 쓰는 것 |
|---|---|---|---|
| WAF | full logs, 허용/차단·rule·labels, 민감 header 제외 설정 | S3→SQS→Elastic AWS 수집 | SQLi/XSS 패턴·rate·차단 근거 |
| ALB | access log, target/status/trace/시간 | S3→SQS→Elastic | WEB 도달 여부, 4xx/5xx·지연 |
| Nginx·Apache | access/error, request ID·client/forwarded·upstream·처리 시간 | Agent→Elastic, 원본 파일 별도 보존 | 어떤 URL·backend·결과인지 |
| WordPress 감사 | 로그인 성공/실패, 사용자·권한·글·업로드 변경, actor·object ID | JSON 파일→Agent→Elastic | 같은 계정의 실패 후 성공·관리 변경 |
| Suricata | EVE alert/drop/http/flow/stats | Agent Suricata 통합→Elastic, 원본 EVE | signature와 실제 IPS verdict·센서 상태 |
| Linux·Defend | auth/journal/auditd, process/file/network, policy revision | Agent→Elastic, 원본 triage·선택 archive | 웹 계보·파일·지속성 변화 |
| RDS MySQL | error, slow, 실험 시간 general; log_output=FILE | CloudWatch Logs→AWS 수집기→Elastic | DB 연결·쿼리·오류·성능, API와 분리 |
| CloudTrail | multi-region read/write 관리 이벤트, 선택 S3 객체 data event | Security audit S3→수집 역할→Elastic | IAM/STS·Secrets·SG·RDS·수집/대응 API |
| VPC Flow Logs | WEB/APP/RDS 관련 ENI의 ACCEPT/REJECT·log-status | S3→수집기 | 허용·거부 연결 관계, 내용은 없음 |
| Route 53 Resolver | VPC query logging | CloudWatch→수집기 | 질의 도메인·출처, 실제 연결 성공은 별도 |
| SSM·SOAR·수집기 | actor·command/job ID·version·exit/error·전후 상태 | CloudWatch 및 Security manifest | 관리 행위와 공격 행위 구분 |

RDS 로그 export는 DB 파라미터와 CloudWatch export를 둘 다 설정해야 한다. 일반 쿼리 로그를 상시 대량 수집하지 않고 실험 구간에 켜며, SELECT 결과나 SQL 실행 성공 전체를 general log 한 줄로 확정하지 않는다. CloudTrail은 SQL 문장을 기록하는 엔진 감사가 아니다. [RDS 로그 게시](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_LogAccess.MySQLDB.PublishtoCloudWatchLogs.html)

ES는 우선 7일·디스크 한도, 운영 로그 원본은 30일·용량 상한, 선정 사건 증거는 별도 보존한다. CloudWatch 경로는 조회 커서·겹침 구간·eventId·늦은 도착을 처리하고 Security 수집기가 사건 원문과 원본 group/stream/event ID를 별도 S3로 보존한다. 모든 로그를 EC2 디스크 수집만으로 보존한다고 설계하지 않는다.

## 6. SIEM 규칙과 경보·차단의 구분

| ID | 초기 탐지 조건·시간창 | 중요도·처리 | 확인할 증거 |
|---|---|---|---|
| D01 | WAF SQLi/known-bad 일치, 5분 동일 client 집계 | 단건 low, 반복 medium. WAF는 자체 정책으로 즉시 차단 | action·rule·backend 도달 |
| D02 | 앱 계정 또는 출처별 5분 10회 실패, 이후 10분 성공 | medium. 사용자·세션 검토, 반복은 정한 rate 정책 | 앱 감사 성공/실패·정상 사용자 대조 |
| D03 | 웹 서비스 계보의 승인되지 않은 shell + 같은 host에서 실행 파일/예약 설정 변화, 5분 | high. 호스트 triage, 지정 실험만 자동 격리 | process entity/start·audit serial·파일 hash |
| D04 | Suricata 선정 high rule + EVE blocked/drop | medium/high. 패킷 차단 기록·서비스 영향 확인 | signature/rev·flow·웹 결과 |
| D05 | APP 역할이 정상 목록 밖 S3 prefix 또는 secret에 접근 | denied는 시도, 성공은 high 조사 | CloudTrail actor/session·resource·errorCode·원본 응답 확인 |
| D06 | 실험 외 SG 확장·IAM trust/policy 변경·로깅 변경 | high. 변경 전후 보존·대상 검토 | CloudTrail eventID·정책 revision·실제 허용 결과 |
| D07 | 지정 DB 계정의 예상 밖 스키마 접근·관리 쿼리 | medium/high. DB 수집, 자동 인스턴스 중지 없음 | 앱 작업·DB thread ID·쿼리/응답 |
| D08 | 예정 운영 중 Agent/IPS/log canary 5분 이상 단절 또는 지속 ingest 오류 | 관측 장애 경보 | heartbeat·queue·DLQ·소스별 지연 |

위 시간·횟수는 정상 부하 기준선 이후 조정할 초기값이다. 시나리오 ID나 테스트용 marker가 들어 있다는 이유만으로 탐지하는 규칙을 평가 성과로 세지 않는다. 결과별 필드와 실제 매칭은 선택한 Elastic 통합 버전의 샘플로 검증한다.

- **즉시 차단:** WAF가 해당 HTTP 요청을, IPS가 해당 패킷/flow를 차단한다. SIEM의 S3 도착을 기다리지 않는다.
- **상관·사건:** SIEM이 여러 소스를 묶어 심각도·사건 후보를 만든다. 원본 event time과 도착 지연을 표시한다.
- **호스트 격리:** 확인된 EC2에만 ALB 등록 해제·격리 SG·필요한 호스트 방화벽을 적용하고 기존/새 연결과 SSM 통신을 검사한다.
- **IAM 대응:** EC2 네트워크 격리와 별도로 해당 역할의 세션·허용 정책을 제한한다. 인스턴스를 껐다고 이미 발급된 자격증명이 즉시 폐기됐다고 판단하지 않는다.
- **DB 대응:** 증거 확보 후 해당 DB 계정/세션·앱 경로를 제한한다. RDS snapshot이 SQL 조회 이력을 대신하지 않는다.
- 초기 자동화는 collect-only가 기본이다. 범위·조건이 고정된 격리 실험에서만 자동 변경을 활성화한다.

대시보드는 서비스 상태, WAF/IPS 차단, endpoint 변화, AWS identity/data 접근, 로그 파이프라인 건강 상태, 사건·대응 이력의 6개 화면으로 구분한다.

## 7. 실제 공격 로그를 만드는 실험

| ID | 수행과 조건 | 성공/차단 판정 | 남겨야 할 로그 |
|---|---|---|---|
| S0 | 정상 GET 2회 | 응답/원문 대조 | 본 공격은 시나리오 라이브러리의 별도 ID 사용 |
| S1 | 허용 경로 3회 조회 | 범위/요청 수 제한 | 본 공격은 시나리오 라이브러리의 별도 ID 사용 |
| S2 | 존재하지 않는 계정 로그인 실패12회 | 로그인 실패 원문; 계정 탈취 아님 | 본 공격은 시나리오 라이브러리의 별도 ID 사용 |
| S3 | SQLi 형태 WAF marker | DetectionOnly/On 대조; DB 유출 아님 | 본 공격은 시나리오 라이브러리의 별도 ID 사용 |
| S4 | 수동 endpoint marker/수집 | SSM·파일·프로세스·원본 ZIP | 본 공격은 시나리오 라이브러리의 별도 ID 사용 |
| S5 | 수동 제한 IAM 권한 거부 | 정확한 API/자원·AccessDenied | 본 공격은 시나리오 라이브러리의 별도 ID 사용 |
| S6 | 수동 사건 수집 파이프라인 수락 | manifest/hash/partial; 자동 격리 아님 | 본 공격은 시나리오 라이브러리의 별도 ID 사용 |

W1/W2와 IPS 변형은 관찰/차단 대조 실험이며 정책 revision과 초기화된 데이터 상태를 함께 기록한다. 앞단에서 차단된 행위의 endpoint 로그가 없는 것은 기대 결과일 수 있다. 없다는 사실만으로 수집 완전성을 판단하지 않고 정상 canary를 같이 확인한다.

정답 기록은 run ID, 허용된 대상, 사전 상태, 요청·실제 응답/변화, 시각, 정책·도구 버전으로 구성한다. AI 입력에는 정답을 넣지 않는다. 원본 증거·인증정보가 포함된 출력은 공개 Git에 저장하지 않고 공유 보고서용 파생본을 별도로 만든다.

## 8. 직접 수행할 구축 순서와 통과 기준

| 작업 | 직접 구축·설정할 것 | 다음 단계 전에 남길 실제 결과 |
|---|---|---|
| B00 | 계정·크레딧·리전·예산·MFA·배포 역할·허용 대상 | 계정별 과금 범위, 총 $300 운영표 |
| B01 | OpenTofu·OS·웹/DB·Agent·규칙·OSS commit/해시 고정 | 호환 조합·라이선스·lock, 로컬 설정 검사 |
| B02 | Security S3/KMS/state·CloudTrail, VPC·서브넷·route·SG·DNS/TLS·SSM | allowed/denied 연결표, 초기 감사·SSM 결과 |
| B03 | RDS subnet/parameter group·TLS·secret·DB 사용자/스키마 | 앱 계정 허용/거부, TLS session, 엔진 로그 도착 |
| B04 | WEB/APP 설치·WordPress seed·역할·업로드 정책·배치 | 로그인·글·업로드·S3 작업 실제 결과 |
| B05 | SOC·Fleet·AWS/S3/SQS/CloudWatch 수집·인덱스/retention | 각 source 원본과 ES 결과 대조·재처리 중복 검사 |
| B06 | WAF·Suricata NFQUEUE·Defend·auditd·앱 감사 설정 | 정책 hash, queue 양방향, 정상 통과·canary |
| B07 | N0 정상 부하·관리 작업·수집 장애 시험 | 정상 기준선·지연·오탐·용량·센서 복구 |
| B08 | DVWA 분리 배치·DB 계정·초기화·W1/W2 | 취약점 실제 성공의 증거, 원본 로그 보존 |
| B09 | WAF Block·IPS drop 대조 W1/IPS | 어디에서 막혔는지·backend 결과·정상 서비스 영향 |
| B10 | CloudGoat 필요한 앱/정책만 이식·C1/C2/C3 | 실제 AWS API 성공/거부와 역할·자원·로그 대응 |
| B11 | D01~D08 실제 필드로 규칙·대시보드·경보 생성 | 정답 대비 TP/FP/FN·단계별 지연 |
| B12 | 경보→사건→AWS 로그·선택 EC2/RDS 증거 수집 | 중복·부분 실패·hash·원본 추적 |
| B13 | K3 격리·권한 제한·복구 후 Atlas 연동 | 실제 차단·회복, 시간축·관계 근거·AI 검토 |
| B14 | 원본 내보내기·재열람·AWS 자원 정리 | source hash, 사건 결과표, 잔여 과금 목록 |

B03/B04의 서비스 로그를 원본에 남기고 B05에서 SIEM 전달까지 대조한다. 실습 공격은 B05~B07의 수집 확인 후 시작한다. Atlas의 기존 Windows 통합 오류 보완은 별도 코드 작업이며 AWS 인프라 설계·구축의 선행 완료 조건으로 두지 않는다.

## 9. 비용·범위의 현실적인 제약

서울 리전 100시간 실행 + 저장/네트워크 최대 730시간 가정이다. 핵심 Linux EC2는 WEB .052 + APP .052 + SOC .208 = 시간당 $0.312, RDS db.t4g.micro MySQL Single-AZ는 시간당 $0.025다. 100시간 합계 $33.70, EBS 150GB × .0912 = $13.68/월, RDS gp3 20GB × .131 = $2.62/월이다. 요금표 확인일은 2026-09-09다.

ALB·NAT·공인 IPv4·SSM endpoints·로그·보관·교차 계정 복사·임시 실험·secret 비용을 포함한 계획 목표는 $200~250이며 총 $300을 상한 목표로 관리한다. 정확한 과금 보장은 아니며 실행 시간·자료량·세금·크레딧 적용을 확인한다. 기본안은 상시 AWS Network Firewall, EKS, managed OpenSearch, 다수 Windows VM, 유료 XDR 구독을 포함하지 않는다.

RDS는 정지 중에도 스토리지 등이 과금되고 최대 7일 뒤 자동 재시작한다. 장기 휴식 시 유지 여부·snapshot·삭제/재구축을 일상 종료 절차에 포함한다. RDS burst CPU 초과 비용, 추가 backup, 로그 export와 CloudWatch API 비용도 추적한다. 730시간 계속 실행하면 핵심 compute만 약 $246이므로 전체를 상시 운영할 예산으로 보지 않는다.

NAT Gateway와 SSM endpoints의 동시 유지에 따른 이중 비용 문제는 운영 모드를 setup/operate/idle로 분리해 해결한다. 구체적인 모드별 리소스·전환 절차는 CLOUD_FORENSICS.md 14.6절에 정의한다.

[EC2 서울 단가](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-2/index.csv) · [RDS 서울 단가](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/ap-northeast-2/index.csv) · [RDS 중지 제약](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html)

현재 작성된 것은 설계다. B00~B14는 미완료이며 AWS 리소스·정책·웹서비스·공격 로그를 생성하지 않았다.
