# 다음 개발자를 위한 인계 — 2026-09-16

작업 경로 `C:/Users/SBA_USER/Desktop/evidence-atlas`, main. `siem-project/dfir-graph`를 수정하지 않는다. AGENTS.md·루트 DESIGN.md를 먼저 읽고 상대 변경은 git diff로 확인한다.

사용자는 AWS 계정/프로필 준비 전 로컬 검증과 시나리오 오류 수정을 요청했다. 2026-09-16 수정 사항은 [SCENARIO_FIXES.md](results/SCENARIO_FIXES.md)를 먼저 읽는다. AWS 미배포다. [결과](results/LOCAL_VALIDATION.md)와 [실제 배포 기준](DEPLOYMENT.md)이 최신이다. 과거 TASKS/설계 표는 모든 항목 완료를 뜻하지 않는다.

- 최종 로컬 cloud-lab 72개, Atlas 79개(고유151개), IaC 3단계 validate 통과. 최신 출력은 results/scenario-fix-validation.json 및 scenario-service-validation.json.
- 실제 Linux WAF·PHP/MySQL TLS·DB 권한 분리·WP seed, 실제 ES/Kibana API·파서·탐지 모드, Velo ZIP 수집 검증.
- ZIP→Atlas는 125레코드/2공유 요청의 **로컬 Linux 검증**. AWS 엔터티·IAM/STS 세션 분석이나 전체 자동 연동은 미완료다. 이를 AWS 지원 완료로 소개하지 말 것.
- 설치 bundle/version/hash, 로그·경보 retry/dedup, CloudTrail 원본/manifest/partial, 오프라인 반출, 입력 생성기·테스트 호스트·S0~S3 제한 실행기를 구현했다.
- 다음은 계정/AMI/견적·실제 plan 확인 → 최소 서비스 → Agent/로그 수락 → 수동 collection → 자동 collection 순서다. 계정이 없다고 기존 PC를 AWS인 것처럼 검사하지 않는다.
- 기본 ModSecurity, AWS WAF off, 자동 수집 off. 전체 예산 목표 $300. endpoint 9개 및 선택 test EC2 비용 포함.
- 메모리·대용량·digest 서명 검증·RDS/ALB/DNS 완전 사건 수집·대응 실행기·AI 평가·Atlas AWS 관계 모델은 별도 후속 작업.
- `design.pdf`는 이번 작업 전부터 나타난 사용자 파일이다. 수정/커밋하지 않았다.

계정 자격증명·원본 증거는 Git 제외. 임시 도구/로컬 증거는 `.runtime`에 보존한다. 배포 판단은 실제 출력 근거로 기록하고 루트 README A0~A7을 추측으로 체크하지 않는다.

- 새 시나리오36개는 catalog의 준비 조건을 따른다. ID를 지원한다고 공격 실행기가 구현된 것은 아니다. 기본 SIEM13개 후보 규칙과 기존 D01~D08 고급 상관 계획을 구분한다.
- 신규 RDS 전용 KMS 키, 합성 S3 data selector, 양 계정/서울+us-east-1 수집을 반영했다. 격리 후 SOC 전송 단절 예상, 세션 만료/재발급 통제 전 Deny 해제 금지.
