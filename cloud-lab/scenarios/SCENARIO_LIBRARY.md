# 공격 시나리오 라이브러리 — 검토 반영 v1.1

2026-09-16. 기존 36개 제안의 범위는 유지하고 실행 전제·로그·판정 기준을 수정했다. 기계 판독 목록은 [catalog.json](catalog.json), 정답 형식은 [answer.schema.json](schemas/answer.schema.json)이다. AWS 배포·공격 실행은 아직 하지 않았다. 코드/정책이 존재한다는 사실과 AWS 수락 검증을 구분한다.

## 실행 계약

- S0~S6는 기존 준비 검사 ID다. S0 GET 정상 확인, S1 제한된 경로 조회, S2 실패 로그인, S3 WAF marker, S4 수동 endpoint 수집, S5 수동 권한 거부, S6 수동 파이프라인 수락이다. 실제 SQLi/RCE/SSRF 공격 성공을 뜻하지 않는다.
- 본 공격/분석 실험은 N/W/H/C/I/D/E/X/K ID를 사용한다. 각 ID는 전제·합성 대상·한도·기대 효과·실제 로그·규칙·정리 결과를 갖는다. 현재 자동 HTTP 실행기는 S0~S3만 지원한다.
- 모든 실행은 소유한 사설 랩과 명시적 실험 AWS ARN만 대상으로 한다. 중앙 증거·정상 감사 trail·state를 삭제 실험 대상으로 사용하지 않는다. 새 역할은 기본 APP/SOC 관리자 권한을 확대하지 않고 별도 최소 권한 fixture로 만든다.
- 기본 한도는 회당 30분, 새 자원 1개, 합성 데이터다. 실제 요청 수·바이트·비용 상한은 실행 전 별도 명시한다. Budget/cost_guard는 비용 발생을 즉시 막는 장치가 아니다.
- 경보·관측·차단은 별개다. `observed/parsed/detected/blocked/collected` 각각 미평가·성공·실패·예상 미생성·미지원·전달 대기를 기록한다. 앞단 차단으로 생성되지 않은 backend 로그를 미탐으로 세지 않는다.

## 수정한 기술 전제

| 항목 | 적용 기준 |
|---|---|
| C1 IMDS | Flow Logs는 metadata169.254 트래픽을 기록하지 않는다. WEB IPS는 APP→IMDS 경로를 보지 않는다. in-process SSRF에 curl exec를 기대하지 않는다 |
| IMDSv2 | PUT token·후속 헤더 처리가 가능한지 별도 실험 앱에서 확인. GET SSRF만으로 role 탈취 성공을 가정하지 않는다 |
| I1 PassRole | 독립 API/CloudTrail 이벤트가 아니다. RunInstances 등 실제 역할 할당 API의 파라미터와 전후 권한으로 확인 |
| S3/Lambda | 기본 data event는 `ea-scenario-data-<Workload>/synthetic/`만. Lambda는 명시적 `scenario_lambda_arns` 설정 후 `Invoke` 수집. 기본 APP에는 S3 공격 권한 없음 |
| IAM/STS | 양 계정의 서울+us-east-1을 기본 수집. 다른 실험 리전은 수집 설정에도 추가. event 원문의 awsRegion 보존 |
| RDS/EBS/AMI | 각 API·키·공유/copy/restore 조건을 분리. RDS 전용 고객 관리 키가 있으나 외부 grant·공유·복원 실행기는 기본 제공하지 않음 |
| 보존 | 현재 Versioning/KMS/계정 분리. Object Lock·landing 복제는 미구현. 이미 전달된 원본 보존과 trail 중단 이후 누락은 별도 판정 |
| 격리/복구 | SSM/S3 경로 유지, SOC 실시간 Agent 전송 중단 예상. 토큰 만료·재발급 통제 확인 전 session Deny 제거 금지. 응답 JSON은 수동 runbook |
| K5/K8 | 실제 채굴·대형 다수 자원·주 단위 상시 유지 제외. 소형 단기/합성 이벤트 변형 및 종료 검증 |
| K9/K11 | 통제된 DNS 수신처·합성 데이터. 도메인 등록일은 별도 enrichment. 정상 API 남용도 역할/자원/변경/시퀀스 규칙으로 검토 가능 |

## 36개 준비 조건

`조건부`도 실행 완료 표시가 아니다. 전용 fixture·권한·정리 절차가 없는 항목은 실행하지 않는다. 표는 검토 당시 요구사항이며 실제 코드 반영 상태는 [수정 기록](../results/SCENARIO_FIXES.md)을 따른다.

| ID | 준비 상태 | 필요한 조건과 판정 |
|---|---|---|
| N0 | 조건부·우선 | 정상 회원/관리/DB/API 행위와 canary, 시간창·요청 수를 고정. 현재 S0의 GET 2회보다 넓은 기준선이 필요 |
| W1 | 조건부 | DVWA 초기화·인증/보안수준·합성 DB 행 고정. 실제 추가 행 조회와 차단 후 미조회 대조. WAF marker 통과를 SQLi 성공으로 세지 않음 |
| W2 | 조건부 | DVWA 취약 기능·쓰기/실행 권한 확인. 무해한 marker의 파일 hash·프로세스와 연결. 일반 업로드나 HTTP 200만으로 RCE 판정 금지 |
| W3 | 조건부 | 전용 테스트 계정의 실패→성공, 정상 사용자 대조, 집계 규칙. S2의 존재하지 않는 계정 실패만으로 계정 탈취 검증 불가 |
| W4 | 조건부 | 사설 ALB만 대상, 도구/경로/요청 수·시간 한도 고정. 실제 SID와 매칭 입력, 정상 UA 대조 필요 |
| W5 | 전용 환경 | 고정 버전의 별도 취약 앱/플러그인, 정확한 취약점·파일 범위 필요. 인증 우회와 LFI는 별도 변형 |
| H1 | 조건부·기대 로그 수정 | 통제된 사설 수신처·포트별 허용/거부 대조. WEB IPS가 APP egress를 감시한다고 가정하지 않음 |
| H2 | 조건부·수집 확장 | 사용자/관리 권한별 지속성 marker와 제거 확인. cron/systemd/SSH 원본 수집 경로 추가 |
| H3 | 전용 변조 대상 | 합성 로그 파일과 이미 전송한 복사본 대조. 실제 중앙 증거·필수 감사 로그 삭제를 공통 절차에 넣지 않음 |
| C1 | 전용 환경·전제 수정 | 별도 SSRF 앱, IMDS 버전·요청 기능·권한 명시. Flow IMDS 항목 제거, 앱/호스트에서 관측 가능한 근거 선정 |
| C2 | 조건부 | 제한된 역할의 허용/거부 API 대조. principal/session·사용 위치 연결, 글로벌/리전 STS 수집 구분 |
| C3 | 조건부·범위 조정 | 현재는 앱 secret 2개. 제한 횟수의 정상/허용 밖 secret 대조부터 시작; 대량 조회에는 별도 합성 secret·규칙 필요 |
| I1 | 전용 환경·이벤트 수정 | 제한된 실험 role/instance profile/생성 자원 필요. PassRole 독립 이벤트 대신 자원 생성·역할 할당 API의 파라미터 검증 |
| I2 | 전용 환경 | 제한된 다중 버전 실험 정책과 복원 절차. SetDefaultPolicyVersion의 주체·선택 버전·실제 권한 변화 대조 |
| I3 | 전용 권한/자원 | 기본 APP에서 성공 불가. 폐기 가능한 사용자/키/프로필만 대상으로 생성·비활성·삭제 확인 |
| I4 | 전용 환경 | 실험 Lambda·resource policy·제한 principal 필요. 생성/정책 변경과 실행 증거를 분리 |
| D1 | 전용 자료·로그 보완 | 합성 S3 bucket/prefix, 제한 GetObject 권한·data event. 건수·바이트·원본 hash 대조 |
| D2 | 전용 정책 대상 | 비업무 버킷과 지정 계정만 허용. 변경 전/후 policy 및 원복, AccessDenied 대조 |
| D3 | 전용 환경·키 설계 | RDS/EBS/AMI 분리. RDS 고객 관리 키·공유/copy/restore 권한, 수신 계정의 복사 완료 확인 |
| D4 | 전용 앱·로그 보완 | URL 생성과 실제 다운로드를 구분. 앱의 발급 기록·만료/범위·S3 data event 대조; URL 자체는 비밀값으로 다룸 |
| E1 | 전용 trail·판정 수정 | 중앙 원본 파이프라인과 분리한 실험 trail에서 중단/재개. 과거 로그 보존과 미래 로그 누락을 별도 측정 |
| E2 | 전용 flow/DNS 설정 | 실험용 로깅 설정만 제거·복원. 삭제 API 로그와 canary 수집 중단/재개를 대조 |
| E3 | 전용 버킷·판정 수정 | 합성 버전과 lifecycle 정책, 적용/삭제/잔존 증거 확인. 미구현 복제분 보존을 기대하지 않음 |
| X1 | 전용 합성 자료 | 소수 합성 객체·버전, 삭제/덮어쓰기 유형별 복구와 hash 확인. 모든 버전 삭제까지 복구 가능하다고 가정하지 않음 |
| X2 | 전용 폐기 자원 | 삭제용 snapshot/AMI만 허용 목록에 지정. 포렌식 보존본과 Terraform 상태 자원 제외 |
| K1 | 선행 단위 미완료 | C1+D1과 최소 역할 경로 확립 후 조립. 추가 AssumeRole 필요 여부 명시, Capital One 축소 모델로 표현 |
| K2 | 선행 단위 미완료 | W2/H/C1/I1/I3 각각 성공·거부 확인 후 연결. SQLi 데이터 조회가 곧 RCE라는 연결 제거 |
| K3 | 선행 단위 미완료 | K2+전용 E1/E2 및 R05/R07 복구 기준. 원본 보존·수집 공백·실제 격리·접근 복원을 독립 평가 |
| K4 | 전용 자격증명 | 최소 권한 단기 실험 자격증명만 지정. 노출 시각의 독립 정답 기록과 사용 시각 대조; 실제 키를 외부 공개하지 않음 |
| K5 | 축소 설계 필요 | 대형/다수 자원·실제 채굴 제외. 소형 단기 생성 또는 합성 이벤트를 구분하고 한도/정리 검증 |
| K6 | 조건부·증거 보완 | APP의 허용 DB 계정과 합성 데이터 범위. secret 열람과 실제 SQL/덤프 결과·세션 근거 연결 |
| K7 | 전용 환경·키 설계 | 소스/수신 통제 계정·리전, RDS/EBS 분기와 복사본 수명·비용. 공유만으로 유출/보존 완료 판정 금지 |
| K8 | 전용 환경·단기화 | 임시 사용자/Lambda/role/userdata 흔적 목록과 완전 회수. 주 단위 유지 대신 단기 행위·표시된 시간축 재생 |
| K9 | 전용 DNS 수신처 | 통제된 DNS 서버/영역과 합성 payload, 제한된 질의. Resolver 로그·수신 결과 대조, 등록일 enrichment는 별도 |
| K10 | 전용 환경·로그 보완 | SSRF/S3/Lambda 자원·정책 체인을 별도 구성, Invoke data event와 함수 결과 확인 |
| K11 | 전용 테스트 주체 | 실제 SOC 관리자 권한 대신 제한된 테스트 주체. 정상 변경과 비인가 변경을 같은 API로 대조, 규칙/조사 근거 평가 |

## 탐지와 기록

`siem/prepare.py`는 기본3개와 추가10개, 총13개 규칙을 구성한다. IAM/감사 설정·snapshot 속성·S3 변경/다량 읽기·secret 조회·EC2 생성·Lambda 호출·로그인 실패를 조사 후보로 표시한다. 정상 관리도 매칭될 수 있으며, 후보를 악성/유출 확정으로 부르지 않는다. 기존 D01~D08 고급 상관 계획 전체를 구현한 것은 아니다.

AWS API 규칙은 전달 지연을 고려해 `event.ingested`를 실행 시간창 기준으로 사용하고 원래 사건 시각은 `@timestamp`와 원문에 보존한다. S3 읽기 burst는 주체별 5분 100회, 로그인 실패는 계정명별 5분10회다. 이 수치보다 적은 테스트에서 경보를 기대하지 않는다. 실제 쿼리·모드·규칙 버전과 정상 대조를 기록한다. cloud API 후보는 medium review queue로 보낸다. EC2 high/critical 자동 수집과 혼동하지 않는다.

`scenario_runner.py`의 출력은 계획 또는 HTTP 원기록이다. 실행된 원기록만 `scenario_records.py --receipt ... --expectations ... --output ...`로 정답 초안에 변환한다. 기대 파일 예: `{"expected_results":["blocked"],"expected_evidence":{"waf":["CRS 원문"]},"policy_versions":{"waf":"On/검증한 revision"},"detection_rules":["ea-waf-match"]}`. 요청 수와 기대 결과 수를 맞춘다. 변환 결과는 `unreviewed`이며 HTTP403만으로 차단·미도달을 자동 확정하지 않는다.

## 수행 순서

N0 → W1/W3 → W2/H2 무해 marker·수집 → C2/C3 허용/거부 → D1 합성 객체. 정상 원본·SIEM 도착과 단위 효과를 확인한 뒤 K1/K2를 조립한다. K3/K7 및 삭제·변조 실험은 보존·키·복구 검사가 준비된 전용 자원에서 별도로 수행한다.

근거와 원래 문제는 [검토 기록](../results/SCENARIO_REVIEW.md), 반영 결과는 [수정 기록](../results/SCENARIO_FIXES.md)을 따른다. 실제 사건 빈도·평균 공격 시간의 근거 없는 수치는 제거했다. Capital One은 축소 모델의 참고 사례이며 동일 환경 재현으로 주장하지 않는다.

AWS 공식 근거: [IMDS](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html), [Flow 제한](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs-limitations.html), [PassRole](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html), [data events](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html).
