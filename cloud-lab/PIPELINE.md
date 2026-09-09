# 전체 파이프라인 구성 검토와 인프라 보완

작성일: 2026-09-09 · 상태: 설계 검토, 구현 전

기존 4개 설계서(DESIGN.md, BUILD_AND_ATTACK.md, CLOUD_FORENSICS.md, OPEN_SOURCE.md)의 인프라 구성 완성도를 점검하고, 파이프라인 각 구간의 구체적 입출력·누락 항목·구현 요건을 정리한다.

---

## 1. 인프라 구성 완성도 평가

### 1.1 잘 정의된 항목

| 영역 | 설계서 위치 | 구체성 수준 |
|------|-----------|------------|
| VPC/서브넷 대역 | BUILD 3절 | CIDR·AZ·라우팅까지 구체적 |
| 서버 사양·수명 | BUILD 2절 | 인스턴스 타입·EBS·실행 시간 상한 명시 |
| SG 허용 목록 | BUILD 3.1절 | N01~N09 규칙, 출발→도착·포트·거부 조건 |
| WAF 정책 | BUILD 4.1절 | 관리형 룰셋·rate·경로·Count→Block 전환 절차 |
| Suricata IPS | BUILD 4.2절 | NFQUEUE inline·양방향·alert→drop 승격 절차 |
| 계정 구조 | FORENSICS 2절 | Workload/Security 분리·역할·한계 명시 |
| KMS 키 3종 | FORENSICS 4.2절 | 소유·용도·소비자·제한 사항 |
| IAM 역할 7종 | FORENSICS 4.1절 | 정체성 종류·권한·기록할 근거 |
| 로깅 소스별 계약 | FORENSICS 5.2절 | 10+ 소스, 켤 설정·경로·보존·조사 연결·한계 |
| 예산 산출 | DESIGN 13절 | 항목별 단가·가정·합계·제어 기준 |
| 증거 보관 형식 | DESIGN 7.5절 | S3 디렉터리 구조·manifest 필드·무결성 |
| 구축 순서 | BUILD 8절 | B00~B14 작업·산출물·통과 기준 |
| 검증 게이트 | FORENSICS 11절 | G0~G8 단계별 통과 조건 |
| 대응 플레이북 | DESIGN 9절 | 수집/격리/복구 상태 전이·역할 분리 |

### 1.2 설계는 있으나 구현 사양이 부족한 항목

| 영역 | 현재 상태 | 필요한 보완 |
|------|----------|------------|
| IAM 정책 문서 | 산문으로 권한 범위 기술 | 실제 JSON policy 또는 HCL resource 정의 |
| SG 규칙 세부 | 표로 방향·포트 기술 | ingress/egress rule의 protocol·CIDR·SG ref 명세 |
| S3 버킷 정책 | 역할별 접근 범위 기술 | bucket policy + IAM policy 조합의 구체적 Statement |
| EventBridge 이벤트 | 사건 JSON 예시 1개 | event pattern·detail-type·source 규격 |
| Step Functions ASL | 상태 전이 7단계 기술 | 실제 State Machine 정의 또는 의사 ASL |
| Lambda 함수 | 역할과 트리거만 기술 | 함수별 runtime·handler·환경변수·IAM·timeout 명세 |
| DynamoDB 테이블 | 중복 제어 언급 | 테이블 이름·PK/SK·TTL·GSI 설계 |
| CloudWatch 수집 경로 | "커서로 조회" 기술 | 구체적 log group 이름·filter pattern·수집기 구현 |
| S3 replication | "같은 리전 복제" 기술 | replication rule·filter·destination·IAM 명세 |
| SSM 문서 | "고정 문서 실행" 기술 | 실제 SSM Document 내용·파라미터·output 위치 |
| Elastic 수집 설정 | 소스별 경로 기술 | Fleet policy·integration·ingest pipeline 구성 |
| 경보 수집기 | "30초 주기 ES API" 기술 | 실제 스크립트/서비스·API key 범위·커서 저장 |

### 1.3 완전히 미정의 항목

| 영역 | 상태 |
|------|------|
| OpenTofu 모듈 구조 | 디렉터리 계획만, HCL 파일 0개 |
| provider/backend 설정 | S3 backend 언급만, 구성 없음 |
| bootstrap 스크립트 | OS/Elastic/Agent/WordPress 설치 자동화 없음 |
| WordPress mu-plugin | 감사 로깅용 코드 미작성 |
| Suricata 규칙 선택 | "소수 룰만 drop" 언급, 구체적 SID 목록 없음 |
| Elastic 탐지 규칙 | D01~D08 조건만 기술, KQL/EQL 없음 |
| Velociraptor 수집 프로필 | "고정 프로필" 언급, 아티팩트 목록 없음 |
| Atlas 클라우드 어댑터 | "구현 범위" 언급, 코드·스키마 없음 |
| 비용 알림 코드 | "코드 준비" 언급, Budget/SNS 리소스 없음 |
| 종료/정리 스크립트 | 절차만 기술, 실행 코드 없음 |

---

## 2. 전체 파이프라인 — 7개 구간 상세

전체 데이터 흐름을 7개 구간으로 나누어 각 구간의 입력·처리·출력·구현 상태를 정의한다.

### P1. 로그 생성과 1차 수집

```
[서비스/OS/AWS] → [로컬 저장 + Agent 전송 + S3 전달]
```

| 소스 | 생성 위치 | 1차 저장 | SIEM 전달 | 원본 보존 |
|------|----------|---------|----------|----------|
| Nginx access/error | WEB:/var/log/nginx/ | 로컬 파일 | Elastic Agent → SOC | 사건 수집 시 triage |
| Suricata EVE JSON | WEB:/var/log/suricata/eve.json | 로컬 파일 | Agent Suricata 통합 → SOC | 사건 수집 시 triage |
| Apache access/error | APP:/var/log/apache2/ | 로컬 파일 | Agent → SOC | 사건 수집 시 triage |
| WordPress 감사 JSON | APP:/var/log/wp-audit/ | mu-plugin 출력 | Agent → SOC | 사건 수집 시 triage |
| Linux journal/auth/auditd | WEB,APP:/var/log/ | persistent journal | Agent System 통합 → SOC | 사건 수집 시 triage |
| Elastic Defend | WEB,APP:Agent | Agent 내부 | SOC 직접 | Elastic 인덱스 |
| RDS MySQL 로그 | RDS 서비스 | CloudWatch Logs | CW→수집기→SOC | Security archive 별도 보존 |
| WAF full logs | AWS WAF 서비스 | S3 landing (aws-waf-logs-*) | S3→SQS→수집기→SOC | Security archive 복제 |
| ALB access logs | AWS ALB 서비스 | S3 landing | S3→SQS→수집기→SOC | Security archive 복제 |
| CloudTrail | AWS CloudTrail | Security audit S3 직접 | S3→SQS→수집기→SOC | audit S3 자체가 원본 |
| VPC Flow Logs | AWS VPC | S3 landing | S3→수집기→SOC | Security archive 복제 |
| Route 53 Resolver | AWS DNS | CloudWatch Logs | CW→수집기→SOC | Security archive 별도 보존 |

**구현 요건:**
- [ ] Elastic Agent Fleet policy: System + Suricata + Custom Logs(nginx/apache/wp-audit) 통합
- [ ] Elastic Defend policy: 프로세스·파일·네트워크 수집, Basic 기능 범위 확인
- [ ] auditd 규칙: exec·설정 변경 대상 지정
- [ ] WordPress mu-plugin: 로그인·권한·글·업로드 변경을 JSON 파일로 기록
- [ ] S3→SQS 이벤트 알림: WAF/ALB/Flow landing 버킷에 설정
- [ ] Elastic AWS 통합: S3 input + SQS + CloudWatch Logs input 구성
- [ ] RDS 파라미터: `log_output=FILE`, slow/error/general log CloudWatch export
- [ ] CloudTrail: multi-region, management read/write, 선택 S3 data event

**미정 사항:**
- journal 최대 크기와 rotation
- Suricata EVE 파일 크기 제한
- Agent→SOC TLS 인증서 방식 (self-signed CA vs Fleet enrollment token)
- S3→SQS 전달 지연 측정 기준

### P2. SIEM 정규화와 인덱싱

```
[Agent/SQS 수집기] → [Elastic ingest pipeline] → [ES 인덱스]
```

| 데이터 | Elastic 통합/인덱스 | 핵심 필드 | 보존 기간 |
|--------|-------------------|----------|----------|
| Linux system | logs-system.* | host.name, process.*, user.* | 7일 / 디스크 한도 |
| Suricata | logs-suricata.* | suricata.eve.alert.signature_id, .action | 7일 |
| Nginx/Apache | logs-nginx.*, logs-apache.* | url.path, http.response.status_code | 7일 |
| WordPress 감사 | logs-generic-* (custom) | ea.wp.action, ea.wp.user, ea.wp.object | 7일 |
| Elastic Defend | logs-endpoint.* | process.entity_id, file.hash.* | 7일 |
| WAF | logs-aws.waf-* | aws.waf.action, .rule.id, .http_request | 7일 |
| ALB | logs-aws.elb-* | aws.elb.target_status_code, .trace_id | 7일 |
| CloudTrail | logs-aws.cloudtrail-* | aws.cloudtrail.user_identity.*, .event_name | 7일 |
| VPC Flow | logs-aws.vpcflow-* | source.ip, destination.ip, event.action | 7일 |
| RDS MySQL | logs-aws.cloudwatch-* (custom) | mysql.thread_id, .query (실험 구간) | 7일 |
| DNS Resolver | logs-aws.route53_resolver-* | dns.question.name, source.ip | 7일 |

**구현 요건:**
- [ ] Fleet Server: SOC VM에 자체 호스팅, TLS 9200/8220
- [ ] Elastic 통합 패키지 버전 고정: AWS, System, Suricata, Endpoint Security
- [ ] ILM/ISM policy: hot 7일 → delete, 디스크 watermark 경보
- [ ] ingest pipeline: 타임스탬프 정규화, GeoIP(선택), 필드 보강
- [ ] Kibana space: default 사용, 인덱스 패턴·데이터 뷰 생성

**미정 사항:**
- Elastic 8.x 안정 버전 선택 (현재 로컬은 8.17.0)
- AWS 통합 패키지의 8.x 호환성 검증
- Fleet enrollment 토큰 vs API key 관리
- 커스텀 WordPress 감사 로그의 ingest pipeline 매핑

### P3. 탐지와 경보 생성

```
[ES 인덱스] → [Elastic Security 규칙] → [경보 인덱스]
```

| 규칙 ID | 탐지 조건 | 소스 인덱스 | 심각도 |
|---------|----------|-----------|--------|
| D01 | WAF SQLi/known-bad 일치, 5분 동일 client 집계 | logs-aws.waf-* | low→medium |
| D02 | 앱 로그인 5분 10회 실패 후 10분 성공 | logs-generic-* (wp-audit) | medium |
| D03 | 웹 계보 shell + 파일/예약 변화, 5분 | logs-endpoint.* + logs-system.* | high |
| D04 | Suricata 선정 high rule + drop | logs-suricata.* | medium/high |
| D05 | APP 역할의 비정상 S3/secret 접근 | logs-aws.cloudtrail-* | high(성공) |
| D06 | SG/IAM/로깅 변경 (실험 외) | logs-aws.cloudtrail-* | high |
| D07 | DB 예상 밖 스키마 접근/관리 쿼리 | logs-aws.cloudwatch-* | medium/high |
| D08 | Agent/IPS/canary 5분 이상 단절 | 메타 인덱스 (.fleet-agents-*) | 관측 장애 |

**구현 요건:**
- [ ] 규칙 8종: KQL/EQL 쿼리 + 임계값 + 스케줄 정의
- [ ] D01~D02: threshold rule (동일 client/user 집계)
- [ ] D03: EQL sequence (웹 프로세스 → shell → 파일 변화)
- [ ] D05~D06: custom query + CloudTrail errorCode 필터
- [ ] D08: heartbeat/canary 기반 → ES watcher 또는 transform
- [ ] 정상 기준선 S0 실행 후 임계값 조정
- [ ] 경보 alias 접근용 API key: 최소 권한 (`.alerts-security.*` 읽기)

**미정 사항:**
- Elastic Security 규칙의 Basic 라이선스 실행 범위
- D03 EQL sequence의 process.entry_leader 필드 가용성
- D08 구현 방식 (Elastic watcher vs 외부 heartbeat)
- 경보 suppression/dedup 설정

### P4. 경보 → 사건 생성 (자동화 파이프라인)

```
[ES 경보] → [경보 수집기] → [EventBridge] → [Step Functions] → [사건 레코드]
```

이 구간이 **가장 구현 사양이 부족한 핵심 파이프라인**이다.

#### P4.1 경보 수집기 (SOC VM)

```
[구성]
  실행 위치: SOC EC2의 systemd 서비스 또는 cron
  주기: 30초
  읽기 대상: Kibana alert alias (.alerts-security.alerts-default)
  인증: 제한된 ES API key (alert 읽기만)
  커서 저장: 로컬 파일 또는 DynamoDB

[입력]
  GET .alerts-security.alerts-default/_search
  - sort: @timestamp asc
  - search_after: 저장된 커서
  - size: 100
  - query: status != "closed"

[출력 → EventBridge]
  aws events put-events --entries '[{
    "Source": "evidence-atlas.alert-collector",
    "DetailType": "SecurityAlertCollected",
    "Detail": "{
      \"alert_id\": \"<kibana alert UUID>\",
      \"rule_id\": \"<rule UUID>\",
      \"rule_name\": \"D01-waf-sqli-repeat\",
      \"space_id\": \"default\",
      \"severity\": \"medium\",
      \"detected_at\": \"2026-09-15T10:23:00Z\",
      \"source_indices\": [\"logs-aws.waf-*\"],
      \"signal_fields\": { ... 핵심 필드 요약 ... }
    }"
  }]'

[중복 방지]
  DynamoDB 조건부 쓰기: PK=space#alert_id, SK=playbook_version
  이미 처리된 경보는 건너뜀
```

**구현 요건:**
- [ ] Python 스크립트: `collectors/alert_collector.py`
- [ ] systemd unit 파일: 재시작·로깅·상태 감시
- [ ] ES API key 생성: `.alerts-security.*` 읽기 전용
- [ ] EventBridge bus: `ea-security-events` (Security 계정)
- [ ] cross-account PutEvents 권한: SOC role → Security EventBridge

#### P4.2 사건 생성 판단 (EventBridge → Step Functions)

```
[EventBridge 규칙]
  이벤트 패턴:
    source: ["evidence-atlas.alert-collector"]
    detail-type: ["SecurityAlertCollected"]
    detail.severity: ["high", "critical"]  ← 자동 사건 생성 조건
  대상: Step Functions StartExecution

[medium 이하]
  로그만 기록, 수동 검토 대기열에 추가
  집계 규칙: 5분 내 동일 rule_id 3건 → 자동 사건 승격
```

#### P4.3 Step Functions 워크플로 (핵심)

```
상태 전이: RECEIVED → VALIDATED → COLLECTING → READY/PARTIAL/FAILED
         → ANALYZING → REVIEW_REQUIRED → CLOSED

[State Machine 설계]

1. ValidateInput
   - 사건 JSON 검증 (schema_version, trigger, target 존재)
   - DynamoDB 중복 확인 (case_id + alert_id + playbook_version)
   - 대상 리소스가 허용 목록(태그/ARN)에 있는지 확인
   → 실패: VALIDATION_FAILED 기록 후 종료

2. PreserveMetadata
   - Workload 역할로 AssumeRole
   - 대상 EC2/RDS/IAM/SG의 현재 상태 조회·보존
   - Security S3에 pre-response.json 저장
   → 실패: METADATA_PARTIAL, 수집 계속

3. CollectAWSLogs
   - CloudTrail: 경보 전후 15분 원본 조회·보존
   - WAF/ALB: 해당 시간 구간 S3 객체 참조 기록
   - 기타: 정책·secret metadata·RDS 설정 보존
   → 병렬 실행, 각 소스별 성공/실패 기록

4. CollectHostEvidence (조건부)
   - target에 instance_id가 있고 수집 프로필이 매치될 때만
   - SSM RunCommand로 고정 Velociraptor offline collector 실행
   - 결과를 staging S3에 업로드
   → 호스트 없는 사건(WAF/IAM)은 건너뜀

5. TakeSnapshot (조건부)
   - 지정 시나리오의 EBS/RDS만
   - EBS: CreateSnapshot → 완료 대기 → Security 계정 복사
   - RDS: CreateDBSnapshot → 완료 대기 → 공유·복사
   → 스냅샷 요청과 완료를 구분

6. VerifyIntegrity
   - staging 객체의 크기·version 확인
   - 별도 worker에서 전체 SHA-256 계산
   - manifest.json 작성
   → 해시 불일치: INTEGRITY_FAILED

7. FinalizeCase
   - staging → final 복사 (고유 키)
   - manifest에 최종 상태·누락 목록 기록
   - READY/PARTIAL 상태로 전환
   - 로컬 Atlas 다운로드 알림
```

**구현 요건:**
- [ ] Step Functions Standard workflow ASL 정의
- [ ] Lambda 함수 5종:
  - `validate_case` — 입력 검증·중복 확인
  - `preserve_metadata` — 대상 상태 보존
  - `collect_aws_logs` — CloudTrail/정책/설정 수집
  - `trigger_host_collection` — SSM 명령 발행
  - `verify_and_finalize` — 해시 검증·manifest 생성
- [ ] DynamoDB 테이블:
  - `ea-cases`: PK=case_id, 상태·시각·대상·manifest 위치
  - `ea-dedup`: PK=space#alert_id#playbook_version, TTL 7일
- [ ] IAM 교차 계정:
  - Security `EACollectionRole` → Workload `EACollectionTarget`
  - Workload target에서 허용: Describe*, SSM SendCommand, EBS CreateSnapshot

**미정 사항:**
- Lambda runtime: Python 3.12 (현재 지원)
- Step Functions timeout: 전체 30분, 스냅샷 대기 15분
- 대용량 triage ZIP의 Lambda 처리 한도 (10GB staging은 Lambda 직접 불가)
- cross-account SSM 명령의 document 이름과 파라미터

### P5. 증거 → 로컬 다운로드 → Atlas 수집

```
[Security S3 최종 증거] → [로컬 다운로드] → [Atlas 어댑터] → [SQLite + ES]
```

#### P5.1 로컬 다운로드

```
[대상]
  D:\DFIR_CASES\CASE-{id}\
    trigger.json
    metadata\pre-response.json
    jobs\JOB-{id}\
      raw\          ← CloudTrail JSON, 정책 JSON, triage ZIP
      parsed\       ← 어댑터 출력 (후처리)
      manifest.json
    snapshots.json

[명령 예시]
  aws s3 sync s3://security-evidence-{id}/cases/CASE-{id}/ D:\DFIR_CASES\CASE-{id}\
    --profile evidence-reader
  python verify_manifest.py D:\DFIR_CASES\CASE-{id}\jobs\JOB-{id}\manifest.json
```

#### P5.2 Atlas 클라우드 어댑터 (신규 개발 필요)

현재 Atlas는 KAPE CSV만 수집한다. AWS 증거를 Atlas에 넣으려면 새 어댑터가 필요하다.

```
[필요한 어댑터]

1. cloudtrail_management
   입력: CloudTrail JSON (management events)
   출력 kind: cloudtrail_api_call
   time_kind: event_recorded (eventTime)
   노드: AWSIdentity, AWSResource, AWSSession
   관계: PERFORMED_API_CALL, ASSUMED_ROLE, ACCESSED_RESOURCE
   핵심 필드: eventID, eventName, userIdentity.arn, sourceIPAddress,
             requestParameters, responseElements, errorCode

2. cloudtrail_data
   입력: CloudTrail JSON (S3 data events)
   출력 kind: cloudtrail_s3_access
   time_kind: event_recorded
   노드: S3Object (bucket + key + versionId)
   관계: READ_OBJECT, WROTE_OBJECT

3. waf_log
   입력: WAF full log JSON
   출력 kind: waf_request
   time_kind: event_recorded (timestamp)
   노드: WAFRule, HTTPRequest
   관계: MATCHED_RULE, BLOCKED_BY
   핵심 필드: action, ruleGroupList, httpRequest.clientIp

4. alb_log
   입력: ALB access log (space-delimited)
   출력 kind: alb_request
   time_kind: event_recorded
   노드: HTTPRequest (trace_id로 WAF/APP 연결 후보)
   관계: ROUTED_TO (target IP:port)

5. linux_triage
   입력: Velociraptor offline collector ZIP 내부 JSON/CSV
   출력 kind: linux_process, linux_connection, linux_file_change 등
   time_kind: 각 아티팩트별 정의
   노드: LinuxProcess, LinuxFile, NetworkConnection
   관계: PROCESS_EXECUTED, FILE_MODIFIED, CONNECTED_TO

6. rds_log
   입력: RDS MySQL error/slow/general log (CloudWatch export)
   출력 kind: rds_query, rds_connection
   time_kind: event_recorded
   노드: DBSession (thread_id + connection_id)
   관계: EXECUTED_QUERY, DB_CONNECTED_FROM

7. aws_config_snapshot
   입력: metadata observer의 주기적 상태 JSON
   출력 kind: config_snapshot
   time_kind: observed_at (조회 시각, 생성 시각 아님)
   노드: AWSResource (instance/ENI/SG/role)
   관계: HAD_CONFIGURATION_AT

8. case_manifest
   입력: manifest.json
   출력: Case 노드, CollectionJob 노드, 소스 파일 등록
   관계: HAS_COLLECTION_JOB, COLLECTED_FROM
```

**Atlas 코어 변경 사항:**
- [ ] `classify()` 확장: JSON 형식 입력 지원 (현재 CSV만)
- [ ] 새 `time_kind` 추가: `api_event_time`, `observed_at`, `request_time`
- [ ] 새 노드 라벨: `AWSIdentity`, `AWSResource`, `AWSSession`, `S3Object`, `WAFRule`, `HTTPRequest`, `DBSession`, `CollectionJob`
- [ ] 새 관계 타입: 위 어댑터별 정의
- [ ] 다중 호스트 식별: instance_id + host.id + IP의 유효 기간 연결
- [ ] 사건 가져오기 CLI: `python -m dfir_graph import-case D:\DFIR_CASES\CASE-{id}\`

### P6. Atlas 분석과 AI 검토

```
[Atlas SQLite/ES] → [시간축 + 관계 그래프] → [AI 가설] → [분석가 검토]
```

이 구간은 기존 Atlas 기능 확장이다.

| 기능 | 현재 상태 | 클라우드 포렌식 추가 |
|------|----------|-------------------|
| 시간축 | 7 lane, Windows 중심 | AWS API·Linux·RDS·WAF 이벤트 lane 추가 |
| 관계 그래프 | 15 노드·23 관계 | AWS 자원·세션·요청 노드/관계 추가 |
| 근거 묶음 | ±5분·공유 참조 | CloudTrail-WAF-ALB trace ID 연결 |
| AI 가설 | 로컬 Ollama | AWS 사건 맥락 프롬프트 추가 |
| 분석가 검토 | 메모·가설 상태 | 증거 coverage·gap 표시 |
| 보고서 | Markdown/JSON | 사건별 source coverage·정답 비교 |

### P7. 대응과 복구

```
[사건 판단] → [격리/권한 제한] → [복구] → [검증]
```

| 단계 | 자동화 | 수동 검토 |
|------|--------|----------|
| 수집 (P4) | Step Functions 자동 | manifest 확인 |
| 격리 | 지정 시나리오만 자동 | SG 변경·ALB 등록 해제 검증 |
| IAM 대응 | 별도 Lambda | session 취소·정책 변경 검토 |
| 복구 | 저장된 설정 기반 | 변경 충돌·정상 트래픽 확인 |

**구현 요건:**
- [ ] 격리 SG 사전 정의: SSM + S3 endpoint만 허용
- [ ] `playbooks/containment.json`: SG 교체·ALB 등록 해제 절차
- [ ] `playbooks/iam_response.json`: role session 취소·inline deny
- [ ] `playbooks/recovery.json`: 저장 SG 복원·ALB 재등록·연결 검증
- [ ] 모든 대응의 before/after 상태 보존

---

## 3. 비용 최적화 검토

설계서 비용 분석에서 발견한 주의 사항:

| 항목 | 설계 가정 | 실제 위험 |
|------|----------|----------|
| NAT Gateway | $43/월 (730시간 상시) | **최대 단일 비용 항목.** EC2 100시간만 쓰더라도 NAT는 VPC에 있는 한 과금. 미사용 시 삭제 필수 |
| SSM endpoints | $19/월 (2개×730시간) | NAT 없이 SSM 쓰려면 필요하지만, NAT가 있으면 endpoint 없이도 SSM 가능. 중복 비용 주의 |
| ALB | $22/월 (730시간 상시) | EC2 중지해도 ALB 과금 계속. 일상 종료 시 삭제→재생성 고려 |
| 공인 IPv4 | $3.65/월 | NAT에 연결된 EIP. NAT 삭제 시 EIP도 해제 필요 |

**권장 최적화:**
1. **운영 모드 분리**: 작업 중에만 NAT/ALB/endpoints 생성, 종료 시 삭제
2. **NAT vs endpoints 선택**: 둘 다 유지하지 않고 상황별 선택
   - 설치/업데이트: NAT 사용 (임시)
   - 운영/수집: SSM endpoints만 (NAT 삭제)
3. **RDS 7일 자동 재시작**: 장기 중단 시 snapshot 후 삭제→재생성

---

## 4. 구현 우선순위 제안

설계를 구현으로 전환할 때의 순서:

### Phase A: 로컬 준비 (AWS 리소스 생성 전)

```
1. toolchain.lock.json 작성 — 모든 도구 버전·해시 고정
2. OpenTofu foundation 모듈 — S3 state/evidence, KMS, Budget
3. OpenTofu lab 모듈 — VPC/SG/ALB/NAT/endpoints 기본 골격
4. bootstrap 스크립트 — Elastic/Agent/Suricata/WordPress 설치 자동화
5. WordPress 감사 mu-plugin 작성
6. 경보 수집기 스크립트 초안
7. Atlas 클라우드 어댑터 스키마 정의 (코드 전)
```

### Phase B: 최소 인프라 (A1~A2)

```
1. Security 계정: S3 + KMS + CloudTrail → G1 게이트
2. Workload 계정: VPC + SG + SSM → G2 게이트
3. WEB/APP/RDS + WordPress 정상 서비스 → G3~G4 게이트
4. 정상 로그 수집 확인 (P1~P2 검증)
```

### Phase C: 탐지·공격 (A3)

```
1. WAF/Suricata/Defend 설정 → P1 완성
2. Elastic 탐지 규칙 D01~D08 → P3 구현
3. S0 정상 기준선 → B07
4. S1~S5 실제 공격 → B08~B10
```

### Phase D: 포렌식 파이프라인 (A4~A5)

```
1. 경보 수집기 + EventBridge + Step Functions → P4 구현
2. 증거 수집·검증·manifest → P4 완성
3. Atlas 어댑터 구현 → P5 구현
4. 첫 AWS 사건 Atlas 시간축 → P5~P6 검증
```

### Phase E: 대응·평가 (A6~A7)

```
1. 격리·복구 플레이북 → P7 구현
2. AI 사건 평가 → P6 완성
3. 증거 내보내기·AWS 정리 → B14
```

---

## 5. 설계서 간 불일치·보완 필요 사항

| 번호 | 내용 | 관련 문서 | 보완 방향 |
|------|------|----------|----------|
| I-01 | DESIGN 6.1의 경보 수집 주기 30초 vs SIEM 규칙의 스케줄 미정 | DESIGN 6.1, BUILD 6절 | 규칙 실행 주기를 1분으로 하면 수집 30초와 맞지 않음. 규칙 주기 ≤ 수집 주기 필요 |
| I-02 | NAT와 SSM endpoints 동시 사용의 비용 중복 | DESIGN 4.2, FORENSICS 3.1 | NAT 있으면 SSM endpoint 불필요할 수 있음. 모드별 비용 분리 |
| I-03 | CloudTrail data event 범위 미확정 | FORENSICS 5.2, BUILD 5.1 | 실습 S3 + 증거 S3만 선택하면 비용 최소화. 전체 S3는 불필요 |
| I-04 | Elastic 버전 미확정 | BUILD 전체, OPEN_SOURCE 3절 | 8.17.0(로컬)과 AWS 배포 버전 호환 검증 필요 |
| I-05 | WordPress 감사 방식 미확정 | BUILD 1.1 | mu-plugin 직접 작성 vs WP Activity Log 플러그인 검토 |
| I-06 | metadata observer 구현 미정 | FORENSICS 5.4 | Lambda vs SOC cron, 주기·대상·저장 형식 |
| I-07 | Atlas case import CLI 미정의 | DESIGN 8.2 | manifest → Atlas DB 매핑·어댑터 호출 순서 |
| I-08 | 정답 기록 형식 미정 | BUILD 7절 | scenarios/ 디렉터리의 JSON schema 필요 |
| I-09 | S3 replication 필터 규칙 미정 | FORENSICS 6.1 | prefix 기반 vs tag 기반, delete marker 처리 |
| I-10 | Secrets Manager rotation 미언급 | BUILD 4.4 | 앱 DB secret rotation 주기·방식 |

---

## 6. 다음 작업

이 문서의 목적은 설계서 4개를 하나의 파이프라인 관점으로 연결하고, 구현 시작 전에 해결해야 할 gap을 명확히 하는 것이다. 코드 작성은 Phase A의 toolchain lock과 OpenTofu 골격부터 시작한다.
