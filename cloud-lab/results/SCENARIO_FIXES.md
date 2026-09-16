# 시나리오 검토 수정 결과 — 2026-09-16

[수정 전 검토](SCENARIO_REVIEW.md)의 R01~R11을 코드와 실행 문서에 반영했다. 배포하거나 공격을 수행한 결과가 아니다. 별도 실험 자원/공격 실행기, 자동 대응, 전체 D01~D08 상관 분석을 새로 완성했다고 표시하지 않는다.

| 항목 | 반영 내용 | AWS에서 확인할 조건 |
|---|---|---|
| R01 데이터 이벤트 | 합성 S3 버킷·synthetic/ 한정 read/write data selector, 선택 Lambda ARN의 Invoke selector와 입력 검증 | 합성 객체/API canary 도착·비용; Lambda는 대상 목록을 설정한 경우만 |
| R02 리전/계정 누락 | SOC와 사건 원본 수집에서 Workload/Security × 서울/us-east-1, 선택 추가 리전 지원. 읽기 IAM 경로 동기화. EC2 ID만으로 LookupEvents 필터링하지 않음 | 실제 AssumeRole/KMS/원본·관리 조회 권한; 추가 리전은 SOC와 automation 입력을 일치시킴 |
| R03 IMDS/PassRole 전제 | Flow IMDS 기대 제거, APP egress와 WEB 센서 분리, IMDSv2 조건·PassRole 실제 API로 교정 | 전용 SSRF/IAM fixture는 별도 준비 |
| R04 경보 혼동 | SIEM13개 규칙(기본3+추가10), CloudTrail 파생 필드·집계 keyword 매핑, 늦은 전달에 ingest 시각 사용 | 정상/의심 대조·실제 경보 전달. 새 API 후보는 medium review queue; 악성/유출 확정 아님 |
| R05 보존 과장 | Versioning/KMS/계정 분리와 Object Lock/복제/감사 지속성을 명확히 구분 | 복제/Object Lock 미구현. 별도 실험 trail/로그 버킷으로만 중단·삭제 시험 |
| R06 RDS 키 | RDS 전용 고객 관리 KMS 키와 출력, 기본 AWS 관리 키 의존 제거 | 공유/copy/restore에는 지정 수신 계정·grant·전용 실행 절차가 추가로 필요 |
| R07 격리·복구 | SSM/S3 유지·Agent 전달 단절 예상, 실제 ALB target만 등록 조작. 토큰 최장 만료/전파·재발급 통제 전 Deny 제거 금지 | 수동 runbook의 실제 통신·기존/새 세션 자원 API 검증. 자동 대응 실행기 미구현 |
| R08 기록 계약 | 신규36+기존7 ID 허용, 계획/HTTP 원기록/정답 구분, 기대값과 정책 버전이 있는 실행 원기록만 변환. 시각 검증·해시·미평가 상태 보존 | 실행 후 독립 증거로 실제 효과·차단·경보 판정 |
| R09 권한·원본 | 36개 준비 조건 카탈로그, 기본 역할과 전용 실험 권한 구분. cron/systemd/authorized_keys 원본 수집 추가 | Agent·SSM 등록, 권한별 파일 접근/누락 확인 |
| R10 탐지 조건 | 실제 SID 문자열/센서 범위·RDS slow log 한계·계정명 집계 명시, 관측→파싱→경보→차단→수집 분리 | 입력과 규칙 임계값을 맞춘 정상/공격 대조 |
| R11 영향/문서 충돌 | K5 채굴/대형 다수 자원과 K8 주 단위 유지 요구 제거. 전용 합성 대상·시간/자원 한도, S ID·CIDR·health·WAF·인덱스·버전·비용 표 정정 | 실행 전 소유 계정/리전/ARN·요청·비용 한도·원복 기록 |

## 검증

최종 검사 결과는 [정적·회귀 원자료](scenario-fix-validation.json)와 [실제 서비스 검사](scenario-service-validation.json)에 기록했다. **cloud-lab 72개 + Atlas 79개 = 고유151개 통과**, OpenTofu foundation/lab/automation init(backend 비활성)·validate·fmt도 통과했다. 기존 [9월15일 검증](LOCAL_VALIDATION.md)은 당시 기준선으로 보존한다.

실제 Elasticsearch/Kibana 8.19.20에서 13개 규칙을 등록하고, API 규칙9개의 양성/다른 서비스 음성 fixture 검색과 principal 집계를 확인했다. S3 읽기100건·WordPress 실패10건의 실제 keyword 집계가 통과했다. Velociraptor 0.77.2는 cron/systemd/authorized_keys의 무해한 원본을 ZIP에 수집하고 재실행 시 같은 해시를 유지했다. 실제 AWS 이벤트나 Agent 커널 동작을 대신하는 결과는 아니다.

이 과정에서 `/api/fleet/settings`로 설정한 주소가 실제 Fleet 기본 호스트에 반영되지 않는 문제도 수정했다. 지원되는 생성 API로 등록하고 GET으로 주소·default 값을 재확인한다. [Elastic Fleet 호스트 API](https://www.elastic.co/docs/api/doc/kibana/v8/operation/operation-post-fleet-server-hosts)

## 배포 시 적용

1. foundation에서 합성 버킷과 data event를 생성한다. 정상 앱/SOC 역할에 광범위한 공격 권한을 추가하지 않는다.
2. 실험 Lambda가 준비된 경우에만 배포 설정의 `scenario_lambda_arns`에 최대5개 정확한 Workload `ea-scenario-*` ARN을 지정한다. 비어 있으면 Lambda data event는 비활성이다.
3. 타 리전 실험에는 `audit_extra_regions`를 지정한다. 입력 생성기가 lab/automation 양쪽으로 전달한다. 기본 수집은 두 계정의 서울+us-east-1이다.
4. 기존 ES가 있는 경우 타입 변경이 포함된 템플릿과 인덱스를 대조하고 새 데이터 스트림/rollover를 준비한다. 운영 인덱스 매핑을 자동 강제 덮어쓰지 않는다. 신규 스택은 생성된13개 규칙을 사용한다.
5. N0 정상 수집을 먼저 검증한 뒤 W/H/C/D 단위 실험을 실행한다. 새 카탈로그36개는 자동 공격 실행기가 아니며 준비 조건을 생략하지 않는다.

`design.pdf`는 이전 스냅샷으로 원본 보존했다. 최신 실행 기준은 Markdown/JSON이다. CloudTrail digest의 서명 검증, RAM/대용량 수집, RDS/ALB/DNS의 완전한 사건 수집, host 없는 자동 사건, Atlas IAM/STS 관계 분석, 자동 대응 및 AI 정확도는 기존 로드맵의 후속 범위다.
