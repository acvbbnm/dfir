# 다음 개발자를 위한 인계 — 2026-09-11

작업 레포는 `C:/Users/SBA_USER/Desktop/evidence-atlas`다. 옛 `siem-project/dfir-graph`를 수정하지 않는다. 루트 AGENTS.md·DESIGN.md와 cloud-lab 설계서를 따른다.

사용자는 AWS 계정/프로필 준비 전이므로 로컬 구현·검증부터 진행하도록 지정했다. AWS 리소스 생성·공격·실제 로그 수집은 하지 않았다. 현재 결과는 README 및 results/LOCAL_VALIDATION.md, 재현 절차는 LOCAL_DEVELOPMENT.md에 있다.

## 이번 보완

`44e1908`의 “Phase A 완료” 초안에서 설치 연결, HCL 오류·Provider lock·인증서, SG·route·endpoint, WordPress 설정, SOC 데이터 보존·TLS, 계정별 감사·KMS, Lambda 패키징·실패 처리를 보완했다. 실제 렌더링/모의 동작을 포함한 47개 검사와 세 IaC validate를 통과시켰다. Linux 서비스를 구동한 검증은 아니다.

현재 operate 모드 interface endpoint는 총 9개다. 예전 비용표를 그대로 적용하지 말고 계정 크레딧·실행 시간 기준으로 총 $300 목표를 다시 산정한다.

## 다음 순서

1. 계정 없이 진행할 작업: offline collector의 profile/CLI/출력 manifest 계약, source/version/hash·streaming·원자적 dedup, SIEM 통합 설정과 회귀 검사.
2. 계정 준비 후: AMI·패치·해시·IAM 프로필·예산 입력 확정, Foundation 최초 local state 생성 및 S3 이관, 최소 서비스 구축과 단계별 실제 결과 기록.
3. DB 전용 사용자·정상 seed·DVWA 분리, Fleet Server/Agent 정책, AWS/S3/SQS·CloudWatch 통합.
4. 정상 서비스와 원본↔SIEM 대조 후 공격 시나리오 실행. collector/교차 계정 업로드 계약을 검증한 뒤 collection_enabled 활성화.
5. 기존 Atlas의 ES 뷰어 전환·Sysmon 시간축·MFT 검색 통합 오류는 이번에 변경하지 않았다. 별도 코드 작업으로 유지한다.

상대 AI 수정 전 git diff를 확인하고, 파일 존재·문법 통과만으로 전체 완료 체크하지 않는다.
