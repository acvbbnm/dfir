# SIEM 설정 준비

[AWS 구성](../README.md) · [배포·수락 순서](../DEPLOYMENT.md) · [최신 검증 기록](../results/SCENARIO_FIXES.md)

> **2026-09-16:** 격리된 로컬 ES/Kibana에서 설정 API·파서·규칙 검색/집계를 검증했다. AWS 미배포이며 실제 Agent 등록·클라우드 로그 전달·경보 발생은 별도 수락 대상이다.

`prepare.py`는 Elastic 8.19.20에 맞춰 공식 EPR에서 확인한 endpoint 8.19.3, filestream 1.2.0, fleet_server 1.6.1 설정을 렌더링한다. 기본 실행은 JSON 계획만 쓴다. `--apply`는 새 SOC의 인증서/관리자 비밀번호 파일을 명시했을 때에만 API에 전송한다. 기존 로컬 Elasticsearch/Kibana에는 적용하지 않았다.

7일 ILM, 원본 `event.original`, 별도 `ea.raw`, WEB/APP별 로그 경로, Defend, Fleet, 초기 탐지 규칙을 포함한다. auditd/Apache/auth의 비정형 텍스트는 원문 수집까지이며 의미 파서는 별도다. WAF 원문에는 요청 정보가 포함될 수 있어 조사자 전용 접근 권한으로 제한한다.

설정 적용 후 코드가 Linux malware 모드를 detect로 바꾸고 global telemetry를 끈 뒤 API로 재확인한다. EDRComplete의 초기 preset 자체를 탐지 모드로 가정하지 않는다. 에이전트 등록은 그 확인 이후에 한다. 라이선스·커널 호환성과 실제 이벤트 도착은 AWS 수락 검사다. AWS 원본 S3·CloudWatch 수집은 `collectors/cloud_logs.py`와 SOC의 `collectors.sh`로 별도 구성했다. 실제 AWS 권한·전달·시각 대조는 아직 필요하다. 설치 API 키는 7일 만료다.

공식 근거: [Fleet package policy API](https://www.elastic.co/docs/api/doc/kibana/v8/operation/operation-create-package-policy), [Defend API](https://www.elastic.co/docs/solutions/security/configure-elastic-defend/create-an-elastic-defend-policy-using-api), [Elastic Package Registry](https://epr.elastic.co/search?package=endpoint&kibana.version=8.19.20).

## 시나리오 검토 반영 (2026-09-16)

기본 3개와 추가 10개, 총 **13개 규칙**을 생성한다.

| 규칙 범위 | 처리 |
|---|---|
| WAF·Suricata·Endpoint | 원본 방어 도구의 경보 후보 |
| IAM·감사·RDS 공유·EC2 이미지/스냅샷 공유·S3 변경 | provider와 API action에 따른 검토 후보 |
| S3 읽기 | 주체별 5분 100회 임계값 |
| Secret 접근·EC2 생성·Lambda Invoke | 해당 API 호출 검토 후보 |
| WordPress 로그인 실패 | 계정명별 5분 10회 임계값 |

추가 AWS 후보는 medium이며 정상 관리 작업도 포함한다. 전체 D01~D08 상관 구현·악성 판정·자동 차단을 뜻하지 않는다. API 규칙은 `event.ingested`를 시간창 기준으로 쓰며 원본 사건 시각을 보존한다. 일부 S3/Lambda 규칙은 해당 CloudTrail data event 설정과 실제 전달이 전제다.

CloudTrail 정규화는 원문을 수정하지 않고 provider/outcome/principal/session/resource/parameters를 별도 필드에 투영한다. requestParameters는 flattened로 매핑해 서비스별 타입 충돌을 줄인다. 규칙 갱신은 기존 정책을 임의 덮어쓰지 않는다. 기존 스택에는 생성 계획과 현 정책을 대조한 명시적 변경 적용이 필요하다.

관제 로그의 `logs-ea.*`와 Atlas의 `ea-current-records`는 서로 다른 용도다. 전자는 AWS SOC 로그, 후자는 SQLite 증거를 ES로 투영한 별칭이다. 현재 SIEM 로그가 곧바로 Atlas 관계 그래프로 들어가는 자동 연동은 없다.
