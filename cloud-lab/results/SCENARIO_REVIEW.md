# 시나리오·문서 정합성 검토 — 2026-09-15~16

> 이 문서는 수정 전 상태의 검토 기록이다. 이후 반영 결과는 [SCENARIO_FIXES.md](SCENARIO_FIXES.md)를 따른다. 원래 초안은 `.runtime/scenario-review/SCENARIO_LIBRARY.before.md`에 보존했다.

Claude의 [SCENARIO_LIBRARY.md](../scenarios/SCENARIO_LIBRARY.md)는 웹 → 호스트 → IAM → 데이터 → 대응을 연결하는 **36개 제안 목록**으로 유용하다. 다만 현재 코드로 실행하고 탐지율을 측정할 수 있는 명세는 아니다. 일부 AWS 로그 전제가 틀렸고, 필요한 실험 자원·권한·규칙·수집 범위가 빠져 있다. 기존 코드와 이전 문서의 문제도 함께 발견했으며, 아래 지적을 모두 새 초안의 잘못으로 돌리지 않는다.

원본 시나리오 문서와 `design.pdf`는 수정하지 않았다. AWS 배포·공격·자원 변경 없이 정적 대조, 스키마 검증, 오프라인 실행계획 생성만 수행했다.

## 검토 범위와 실제 결과

- 검토 시작 시 저장소 Markdown **18개, 4,194줄**을 목록화·텍스트 스캔했다. 주요 설계·실행·시나리오 조항을 실제 코드와 대조했다. 문서별 경로·해시는 [검증 원자료](scenario-review.json)에 있다. 보고서와 README 링크 추가 전의 스냅샷이다.
- 루트 `design.pdf` **5페이지**의 추출 텍스트와 렌더링을 확인했다. 과거 온프레미스 SIEM 문서를 현재 AWS 실행 기준으로 사용하지 않았다.
- Terraform **34파일**을 파싱하고, 현재 S0~S6 JSON·정답 스키마·플레이북 4개·수집기·SIEM 등록 코드·WAF/IPS/호스트 설정을 대조했다. 전 코드에 대한 형식 검증이나 AWS 권한 시뮬레이션을 완료했다는 뜻은 아니다.
- 신규 ID **36/36이 현재 answer 스키마에서 거부**됐다. 같은 최소 입력의 S0 대조군은 통과했다.
- 생성한 S0 오프라인 계획은 `executed=false`다. 정답 스키마에 직접 넣으면 필수 필드/행동 형식 오류가 발생한다. 계획에 실행 시각이 없는 것은 정상이며, 계획·HTTP 결과와 최종 정답 기록의 계약을 분리해야 한다.
- 이전 [최종 로컬 검사](LOCAL_VALIDATION.md)의 고유 **142개 통과**는 유지되는 기능 기준선이다. 이번 36개 시나리오가 AWS에서 성공·차단·탐지됐다는 결과는 **0개**이며, 아직 미실행이다.

## 실행 전에 해결할 주요 항목

P1은 해당 시나리오의 실행·증거·탐지·복구 판정을 막는 문제, P2는 조건·계약·문서 정확성을 고쳐야 하는 문제다. 운영 중 침해가 발견됐다는 의미가 아니다.

### R01 · P1 · 객체 접근/삭제와 Lambda 실행 로그가 설정되지 않았다

대상: D1, D4, X1, K1, K7의 객체 경로, K10. 근거: [cloudtrail.tf](../infra/foundation/cloudtrail.tf) L100~132의 두 trail 모두 management event만 선택한다. `data_resource`/`advanced_event_selector`가 없다.

`GetObject`, `PutObject`, `DeleteObject`, Lambda `Invoke`는 data event 수집 설정이 필요하다. K10의 `InvokeFunction`도 CloudTrail 기대 이벤트명 `Invoke`로 바로잡아야 한다. [AWS data event 문서](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html)

수정: 합성 자료용 전용 S3 bucket/prefix와 실험 Lambda ARN에만 선택자를 추가하고 정상 1회 읽기·쓰기·삭제·호출로 원본→SIEM 도착을 먼저 검증한다. 관리 이벤트가 보인다는 이유로 객체 유출 증거도 있다고 판정하지 않는다. 추가 로그량·비용도 실행계획에 포함한다.

### R02 · P1 · 글로벌 IAM/STS 로그를 수집기가 놓친다

대상: I1~I4, C2, K2~K4, K8, K11. 근거: [configure_collectors.py](../bootstrap/configure_collectors.py) L11과 [collect_aws_logs/handler.py](../infra/automation/lambda_src/collect_aws_logs/handler.py) L20, L65. 기본 생성 설정은 Workload의 `ap-northeast-2` prefix와 조회 클라이언트만 사용한다. Security 계정 자체의 감사 로그도 이 SOC 기본 소스 목록에 없다.

Multi-region trail이 있어도 소비자가 서울 경로만 읽으면 전체 수집이 아니다. IAM 및 글로벌 STS 이벤트는 `us-east-1` 경로를 고려해야 하고, regional STS는 사용한 리전에서 수집한다. [CloudTrail 글로벌 서비스](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-concepts.html), [STS 감사 리전](https://docs.aws.amazon.com/IAM/latest/UserGuide/cloudtrail-integration.html)

수정: 계정·리전 목록을 수집 계약으로 만들고 서울+글로벌 이벤트 리전+선정 실험 리전을 다룬다. 원문의 `awsRegion`을 보존한다. IAM 이벤트를 EC2 instance ID 하나로 필터링해 누락하지 않도록 principal/session/resource 기준의 수집도 필요하다. 같은 시각 서울 EC2와 글로벌 IAM fixture가 함께 가져와지는 회귀 검사를 추가한다.

### R03 · P1 · SSRF/IMDS 탐지 전제가 실제 센서와 맞지 않는다

대상: C1, K1, K2, K10, 라이브러리 L57·100·123. 현재 EC2는 [ec2.tf](../infra/lab/ec2.tf) L29~30 등에서 IMDSv2 required/hop limit 1이다.

- VPC Flow Logs는 `169.254.169.254` 메타데이터 트래픽을 기록하지 않는다. C1의 Flow=A를 제거해야 한다. [AWS Flow Logs 제한](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs-limitations.html)
- [web.sh](../bootstrap/web.sh) L57~63의 NFQUEUE는 WEB의 ALB↔8080 경로만 다룬다. APP→IMDS나 APP 외부 통신을 그 센서로 볼 수 있다고 가정할 수 없다.
- auditd의 exec 규칙은 별도 `curl` 프로세스가 생성될 때의 증거다. 앱 내부 HTTP 라이브러리로 발생한 SSRF에 `curl` 실행 로그를 요구하면 안 된다.
- IMDSv2는 token을 얻는 PUT와 후속 요청의 헤더가 필요하다. URL만 지정하는 GET SSRF와 동일한 조건이 아니다. “IMDSv2이므로 항상 안전” 또는 “SSRF면 무조건 탈취” 모두 부정확하다. [AWS IMDSv2 동작](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html)

수정: 별도 실험 앱의 요청 메서드·헤더 기능, metadata 설정, 역할 권한을 명시한다. IMDSv1 비교와 IMDSv2 방어/조건부 접근을 별도 변형으로 나눈다. K1은 사고에서 착안한 축소 모델로 이름 붙이고, 당시 환경과 동일한 재현이라고 단정하지 않는다. EC2 역할의 임시 자격증명 사용과 추가 `AssumeRole`은 서로 다른 단계로 기록한다.

### R04 · P1 · 관측 로그를 경보·차단으로 표시했다

대상: 라이브러리 L115~127 커버리지 표 및 모든 K 체인. 근거: [siem/prepare.py](../siem/prepare.py) L68~70에 자동 등록되는 규칙은 `ea-waf-match`, `ea-suricata-alert`, `ea-endpoint-alert` **3개**다. D01~D08의 로그인 연쇄·IAM/S3·DB·센서 단절 상관 조건은 [PIPELINE.md](../PIPELINE.md) L148~162의 설계/미완료 항목이다.

CloudTrail·Flow·RDS는 기록원이다. 로그가 생성되어도 별도 규칙이 없으면 A=경보라고 채울 수 없다. 기본 WAF는 ModSecurity이므로 WAF와 ModSec을 독립 탐지 계층 두 개로 중복 집계해서도 안 된다. AWS WAF의 KnownBadInputs를 기본 ModSecurity CRS와 같은 규칙으로 취급하지 않는다.

추가로 [eventbridge.tf](../infra/automation/eventbridge.tf) L26~38은 활성화된 경우 high/critical **EC2**만 자동 수집한다. WAF 기본 규칙은 medium이고, IAM/S3 등 비 EC2는 review queue에 남는다. “모든 체인이 자동 사건→Atlas로 이어진다”는 현재 기능이 아니다. 이를 우회하려고 경보의 심각도나 target을 임의 승격하면 안 된다.

수정: 관측/파싱/경보/차단/증거수집을 각각 평가하고 규칙 ID·버전·쿼리·입력 필드·시간창을 연결한다. host 없는 클라우드 사건 경로도 별도 수락 검사로 추가한다.

### R05 · P1 · 불변 보존·복제·감사 지속성을 구현한 것으로 가정했다

대상: E1~E3, K3, 라이브러리 L80~84. Terraform 전수 파싱 결과 S3 Object Lock과 S3 replication 리소스는 **0개**다. 현재 CloudTrail 버킷은 Security 계정 소유·Versioning·KMS이며, ALB/Flow의 landing은 Workload에 있다.

버전 보관은 Object Lock에 의한 삭제 방지와 다르다. [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html) 현재 구조는 이미 전달된 로그의 계정 경계를 강화하지만, Workload trail의 수집이 중단된 뒤 미래 로그까지 자동 보존하지는 않는다. Security 계정의 자체 trail도 Workload 전체를 독립 감시하는 Organizations trail을 대신하지 않는다.

수정: E1의 성공 기준을 “중단 API의 관측, 전달 중단·지연 식별, 기존 버전 보존, 재개 후 확인”으로 나누고 실제 배치된 경계까지만 주장한다. CloudTrail Event history에는 별도 trail 없이도 최근 관리 이벤트가 제공되지만, 객체 data event나 장기 원본 보존을 대신하지 않는다. [Event history 범위](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/view-cloudtrail-events.html), [Trail 로깅 중단](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-turning-off-logging.html)

E1~E3의 변경 대상은 정상 감사 파이프라인과 별도로 만든 합성 trail/log bucket이어야 한다. 보존 장치를 더 도입한다면 retention·키·삭제 권한·복제 지연·복구 결과를 확인한 뒤 기대표를 갱신한다.

### R06 · P1 · RDS snapshot 공유 경로가 현재 암호화와 맞지 않는다

대상: D3, K7. 근거: [rds.tf](../infra/lab/rds.tf) L48~60은 암호화가 켜져 있지만 `kms_key_id`를 지정하지 않는다. 기본 AWS 관리 RDS 키로 암호화된 snapshot은 그대로 타 계정에 공유할 수 없다. [AWS RDS snapshot 공유 제한](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_ShareSnapshot.html)

수정: RDS·EBS·AMI를 별도 분기로 정의한다. RDS는 실험용 고객 관리 키 또는 고객 관리 키로 재암호화한 복사본, 소스/수신 계정의 제한된 권한, 수신 측 copy/restore를 설계한다. “공유됨”과 “수신 계정 소유 복사 완료”를 분리한다. 현재 수집 state machine에는 실제 snapshot 생성·교차 계정 copy worker가 없으므로, 해당 경로를 이미 자동 포렌식 수집으로 구현했다고 표시하지 않는다.

### R07 · P1 · 격리·복구 판정이 재접근 또는 수집 단절을 놓칠 수 있다

대상: K3, 기존 S6. [recovery.json](../playbooks/recovery.json) L22~28은 세션 거부 정책을 삭제한다. [iam_response.json](../playbooks/iam_response.json)의 취소는 `TokenIssueTime` 조건부 Deny이다. AWS의 설명을 근거로 한 추론으로, 만료 전 토큰에 적용된 Deny를 제거하고 원래 권한이 남으면 해당 토큰이 다시 허용될 가능성이 있다. 단순 삭제를 복구 성공 조건으로 두면 안 된다. [AWS 역할 세션 취소 방식](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_revoke-sessions.html)

수정: 영향을 받는 토큰의 최장 유효기간·전파 시간을 고려해 Deny를 유지하고 재발급 경로도 통제한다. 기존 토큰의 실제 자원 접근 거부와 새 정상 세션의 허용을 모두 재검증한다. `GetCallerIdentity` 성공만으로 권한 사용 가능 여부를 판정하지 않는다.

또한 [containment.json](../playbooks/containment.json) L44는 Agent→SOC 통신 유지를 기대하지만 [security_groups.tf](../infra/lab/security_groups.tf) L226~247의 격리 SG는 endpoint443과 S3만 허용한다. SOC9200/8220으로 새 연결을 유지할 수 없다. SSM 기반 수집을 유지하는 정책인지 SOC 예외를 두는 정책인지 확정하고, 기존 연결 유지 여부도 검사해야 한다. ALB 등록 해제/재등록은 실제 target인 WEB에만 적용한다. APP은 같은 절차를 무조건 수행하지 않는다. 이 JSON들은 현재 실행기가 아니라 플레이북 설계다.

### R08 · P2 · 신규 ID와 기존 실행 기록 계약이 충돌한다

대상: 신규 36개 전부. [answer.schema.json](../scenarios/schemas/answer.schema.json) L11은 `^S[0-6]$`만 허용한다. 최소 정답 입력의 ID만 바꾼 대조 검사에서 S0 통과, N0/W/H/C/I/D/E/X/K 계열 36개 모두 거부됐다.

[scenario_runner.py](../scripts/scenario_runner.py) L82 이후의 결과는 `target` 단일 문자열과 배열 형태 `actions`를 갖는 HTTP 기록이다. 최종 정답 계약의 `targets`, 객체형 행동, `expected_evidence`로 변환하는 단계는 없다. 이는 기존 구현 측 보완점이다. [test_schemas.py](../tests/test_schemas.py)는 현재 신규 ID나 생성된 정답 기록을 실질 검증하지 않는다.

수정: ID 목록/패턴과 스키마 버전을 관리하고 S0~S6 호환성을 유지한다. 계획, 실행 원기록, 검토된 정답을 구분한다. 실행하지 않은 계획에 가짜 실행 시각을 채우지 않는다. 실제 생성한 최종 정답 문서를 JSON Schema/시간 형식 검증기로 검사한다.

### R09 · P2 · “기존 환경에서 가능”에 권한·아티팩트 조건이 빠졌다

- APP 역할은 [iam.tf](../infra/lab/iam.tf) L43~53에서 두 앱 secret만 읽는다. I3·D2·E1~E3·X1~X2·K8의 성공 권한을 기본 제공하지 않는다. 현 상태는 주로 권한 거부 대조에 적합하며, 성공 재현은 전용 실험 role/정책/대상을 추가해야 한다.
- W2의 웹 RCE는 곧 root 권한을 의미하지 않는다. `/etc` systemd·root SSH key 변경을 같은 권한으로 기대하지 않는다. 정상 WordPress의 코드 소유권/업로드 PHP 제한과 DVWA의 취약 경로도 구분한다.
- [linux-triage.yaml](../collectors/linux-triage.yaml) L24~28의 선택 로그/`/etc/crontab`만으로 H2의 `cron.d`, 사용자 crontab, systemd unit, `authorized_keys` 원본을 모두 수집할 수 없다. 계정별 대상·원본·메타데이터·크기 한도를 추가해야 한다.
- C2의 CloudTrail source IP를 EC2의 IP로 고정하지 않는다. endpoint/NAT 경로와 자격증명 사용 위치를 구분하고 principal/session 및 관련 네트워크 근거를 함께 본다. IP 하나로 출발 인스턴스를 확정하지 않는다.
- K6은 APP에서 정상 앱 DB 계정으로 접속하면 원래 허용된 호스트·계정과 같을 수 있다. “예상 밖 호스트 접속”만으로 앱 우회를 검증할 수 없다. 합성 데이터 범위, 쿼리/세션·프로세스 증거를 따로 정한다.

### R10 · P2 · 웹/IPS/DB 경보 기대치를 실제 규칙에 맞춰야 한다

근거: [local.rules](../application/suricata/local.rules) L5~20, [rds.tf](../infra/lab/rds.tf) L25~38.

- SID9000001은 `UNION`/`SELECT` 문자열 조건이다. 모든 SQLi나 현재 S3의 OR 형태 marker가 이 규칙에 매칭되는 것은 아니다.
- SID9000002는 `/etc/passwd` 문자열, SID9000003은 응답의 `system(` 문자열이다. PHP가 실행된 응답에 PHP 소스가 반드시 포함되지 않으므로 W2 업로드/RCE 성공과 SID 발화를 동일시하지 않는다.
- SID9000004/5는 sqlmap/nikto UA 조건이다. wpscan/gobuster/모든 스캔에 대응하는 일반 행위 탐지 규칙이 아니다.
- SID9000006의 집계 키는 ALB 출처 IP다. 공격자별 실패 횟수와 다르다. N0 정상 트래픽이 섞인 부하도 넣어 오탐을 확인해야 한다.
- RDS는 slow query 1초 기준, general log OFF이다. 짧은 SQLi 조회나 일반 덤프의 SQL 원문/쿼리량이 모두 기록된다고 기대할 수 없다. 관측용 쿼리/감사 프로필과 실행 구간을 명시한다.

### R11 · P1/P2 · 영향 시나리오의 한도·복구·근거를 구체화해야 한다

K5의 “대형/다수 EC2 + 실제 채굴 + 과금 폭증”, K8의 “주 단위 잠복”은 현재 총 $300 목표와 기본 실행 범위를 벗어난다. [cost_guard.py](../scripts/cost_guard.py)는 비용 조회·경고 도구이며 자원을 자동 중단시키는 상한 장치가 아니다.

수정: K5는 허용된 소형 1대 또는 거부 대조/합성 이벤트로 시작하고, 실제 생성 수·수명·비용 한도와 종료 확인을 계약에 넣는다. 실제 채굴은 필수 성공 조건에서 제외한다. K8은 여러 지속성 흔적을 단기 생성·발견·회수하고, 장기 시간축은 합성 데이터임을 표시해 재생한다.

D2/E1~E3/X1~X2는 폐기 가능한 합성 자료와 실험 자원에만 적용한다. K7 수신 계정은 사용자가 통제하는 지정 계정이어야 한다. K9는 통제된 DNS 수신처와 합성 데이터, 크기·횟수 한도를 사용한다. Resolver 로그만으로 도메인의 신규 등록 여부를 알 수 있다고 쓰지 않는다.

라이브러리 L96의 “1위·평균 9~17분”, K5의 “최다”는 모집단·시기·원문 통계 연결이 없다. 출처를 특정하거나 정량 표현을 빼야 한다. L110·137의 “정상 API는 이상탐지만 가능”도 과도하다. API 이름+역할/자원 허용 목록+변경 전후+시퀀스 규칙으로도 탐지 조건을 만들 수 있다. ATT&CK ID 전체의 최신 적합성 인증은 이번 검토 범위에 포함하지 않았다.

## 36개 시나리오별 판정

아래 판정은 실행 결과가 아니라 **현재 코드 대비 구현 준비도**다. 공통으로 R04/R08의 규칙·정답 계약 보완이 필요하다. `조건부`도 AWS 배포·정상 수집 확인 전에는 실행 완료가 아니다. `전용 환경`은 신규 실험 리소스/정책이 필요하다는 뜻이다.

| ID | 판정 | 실행 전에 필요한 것 / 핵심 판정 기준 |
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

I1의 별도 수정: `iam:PassRole`은 API가 아닌 권한 검사여서 독립 CloudTrail 이벤트가 없다. 실제 자원을 생성/변경한 API와 역할 할당 필드에서 확인해야 한다. [AWS PassRole 감사 설명](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html)

## 문서 사이의 실행 기준 충돌

| 항목 | 발견한 차이 | 필요한 정리 |
|---|---|---|
| S0~S6 의미 | BUILD_AND_ATTACK L227~233은 S1 SQLi/S2 RCE/S3 IPS/S4 SSRF. PDF p4는 정찰/로그인/SQLi/웹셸 순서. 현재 JSON은 S1 제한 조회/S2 실패 로그인/S3 WAF marker/S4 수집 점검 | 현재 S0~S6를 준비 검사로 정의하고 본 공격 N/W/H/...와 매핑. 기존 실행 기록의 ID 의미를 소급 변경하지 않음 |
| 사설 서브넷 | BUILD_AND_ATTACK L80~87은 WEB 10.60.20/APP30/DB40/관리50/test60. vpc.tf L14~19는 WEB2/APP3/DB4·14/관리5/test9 | 실제 IaC/outputs 기준의 단일 표로 통일. 실행기 허용 대역도 함께 대조 |
| health 경로 | BUILD_AND_ATTACK L100 `/healthz`, 실제 Nginx·bootstrap `/health` | 단일 경로와 ALB health check 대조 |
| WAF | 구 설계 그림/표는 AWS WAF 기본, 실제 기본은 ModSecurity/CRS·AWS WAF 선택 비활성 | 제품별 정책명·로그 소스·모드명 분리. AWS Count와 ModSec DetectionOnly 명시 |
| IPS 장애 정책 | BUILD_AND_ATTACK L133은 fail-closed 검증 모드, web.sh L57~63은 `--queue-bypass` fail-open | 구현된 모드/예정 모드 분리. NFQUEUE 실제 drop·센서 중단 검증은 아직 필요 |
| 로그 전달/인덱스 | PIPELINE은 S3→SQS/Elastic AWS package·logs-aws.* 설계. 현재 cloud_logs.py L64는 polling·logs-ea.aws-ea | 설계 목표와 현재 구현의 소스·필드·인덱스 계약 분리. 기존 쿼리 그대로 실행하지 않음 |
| 버전 | THIRD_PARTY_NOTICES L16·28~30은 WordPress6.x/Elastic8.17, artifact/toolchain lock은 WP7.1/Elastic8.19.20 | 채택 버전·라이선스 고지·설치 소스를 lock과 대조 |
| 운영 비용 | 이전 문서의 NAT/endpoint 시간 가정과 현재 setup/operate/idle 및 추가 endpoint가 혼재 | 실제 운영 모드별 IaC 자원 수·시간으로 배포 직전 재견적. 과거 합계만으로 $300 이하 확정 금지 |
| Atlas/대응 완료 범위 | 목표 설계는 클라우드 사건·snapshot·자동 격리/복구까지 포함. 현재는 제한된 수집과 offline cloud-import | 준비·구현·로컬 검증·AWS 수락을 별도 상태로 표시 |

## 수정·실행 순서 제안

1. **계약 정리:** 시나리오 카탈로그 ID/버전, S0~S6 의미, 자원 허용 목록, 사전 조건, 요청/자원/시간/비용 한도, cleanup·원복 검증을 확정한다.
2. **관측 통로 보완:** R01/R02 data event·다중 계정/리전 수집, R04 규칙/필드·host 없는 사건, R09 아티팩트 범위를 먼저 보완한다. 정상 canary→원본→SIEM→증거 묶음 도착을 통과시킨다.
3. **첫 실행 묶음:** N0 → W1/W3 → W2와 H2의 무해한 marker/수집 → C2/C3의 제한 API·권한 거부 → D1 합성 객체 접근. 각 단계마다 실제 결과와 방어 후 결과를 비교한다. W4는 소량으로 별도 추가한다.
4. **대표 체인:** 먼저 웹→호스트의 근거 연결, 이후 전용 C1/I1 환경을 붙여 K1/K2를 조립한다. 모든 K 체인을 동시에 구축하지 않는다.
5. **대응/고급 실험:** R05~R07 보존·키·격리/복구가 준비된 뒤 K3/D3/K7. 삭제/정책 변경/비용 영향 변형은 전용 자원과 회수 절차가 준비된 것만 선택한다.

각 실행의 최소 산출물은 `run_id`, UTC 행위 시각, 계정/리전/자원·주체/세션, 정책/도구 버전, 실행 원기록, 실제 효과, 기대 소스·지연 한도, 규칙/경보 ID, 원본 위치/version/hash, 누락 이유, 정리/복구 결과다. 비밀키·secret 값·presigned URL은 일반 Git 결과에 포함하지 않는다.

커버리지에는 `관측 → 파싱 → 경보 → 차단 → 수집`을 따로 기록한다. 앞단 차단으로 생성되지 않은 backend 이벤트, 미지원 센서, 전송 지연, 수집 실패, 규칙 미탐을 구분한다. 공격 전제가 실패한 행위를 성공한 공격의 FN으로 집계하지 않는다. loud/quiet 비교도 실제 효과와 정책·데이터 조건을 맞추어야 한다.

**검토 결론:** 범위를 늘린 방향은 유지하되, 먼저 관측·권한·정답 계약을 고쳐 대표 체인 하나를 끝까지 검증해야 한다. 현재 상태는 “36개 설계 초안 검토 완료”이며 “36개 공격·탐지 검증 완료”가 아니다. 이 보고서의 수정 제안은 아직 코드에 적용하지 않았다.
