# SIEM 설정 준비

`prepare.py`는 Elastic 8.19.20에 맞춰 공식 EPR에서 확인한 endpoint 8.19.3, filestream 1.2.0, fleet_server 1.6.1 설정을 렌더링한다. 기본 실행은 JSON 계획만 쓴다. `--apply`는 새 SOC의 인증서/관리자 비밀번호 파일을 명시했을 때에만 API에 전송한다. 기존 로컬 Elasticsearch/Kibana에는 적용하지 않았다.

7일 ILM, 원본 `event.original`, 별도 `ea.raw`, WEB/APP별 로그 경로, Defend, Fleet, 초기 탐지 규칙을 포함한다. auditd/Apache/auth의 비정형 텍스트는 원문 수집까지이며 의미 파서는 별도다. WAF 원문에는 요청 정보가 포함될 수 있어 조사자 전용 접근 권한으로 제한한다.

설정 적용 후 코드가 Linux malware 모드를 detect로 바꾸고 global telemetry를 끈 뒤 API로 재확인한다. EDRComplete의 초기 preset 자체를 탐지 모드로 가정하지 않는다. 에이전트 등록은 그 확인 이후에 한다. 라이선스·커널 호환성과 실제 이벤트 도착은 AWS 수락 검사다. AWS 원본 S3·CloudWatch 수집은 `collectors/cloud_logs.py`와 SOC의 `collectors.sh`로 별도 구성했다. 실제 AWS 권한·전달·시각 대조는 아직 필요하다. 설치 API 키는 7일 만료다.

공식 근거: [Fleet package policy API](https://www.elastic.co/docs/api/doc/kibana/v8/operation/operation-create-package-policy), [Defend API](https://www.elastic.co/docs/solutions/security/configure-elastic-defend/create-an-elastic-defend-policy-using-api), [Elastic Package Registry](https://epr.elastic.co/search?package=endpoint&kibana.version=8.19.20).

## 시나리오 검토 반영 (2026-09-16)

기본3+추가10=13개 규칙이다. IAM 변경·감사 설정·RDS/EBS/AMI 속성 변경·S3 객체/정책 변경·주체별 S3 읽기5분100회·secret 접근·EC2 생성·Lambda Invoke·로그인 실패5분10회 후보를 만든다. AWS 후보는 medium이며 정상 관리가 포함된다. 전체 D01~D08 상관 구현/악성 판정/자동 차단을 뜻하지 않는다. API규칙은 event.ingested를 시간창 기준으로 쓰며 원본 사건 시각은 보존한다.

CloudTrail 정규화는 원문을 수정하지 않고 provider/outcome/principal/session/resource/parameters를 별도 필드에 투영한다. requestParameters는 flattened로 매핑해 서비스별 타입 충돌을 줄인다. 규칙 갱신은 기존 정책을 임의 덮어쓰지 않는다. 기존 스택에는 생성 계획과 현 정책을 대조한 명시적 변경 적용이 필요하다.
