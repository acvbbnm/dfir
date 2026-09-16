# 배포 전 마지막 로컬 검증 — 2026-09-15

AWS 계정/프로필 준비 전 수행한 검사다. AWS 리소스를 생성하거나 실제 AWS 대상에 요청을 보내지 않았다.

| 검사 | 실제 결과 | 증명하지 않는 범위 |
|---|---|---|
| OpenTofu format, foundation/lab/automation init·validate | 모두 통과; backend 비활성 | 실제 계정의 plan/apply·권한·서비스 가용성 |
| cloud-lab Python·Bash·bootstrap/배포 입력/실패 처리 | **63개 통과** | AWS 통합 동작 |
| 기존 Atlas 및 cloud-import 회귀 검사 | **79개 통과** | AWS 포렌식 분석 기능 완성 |
| Nginx + ModSecurity + CRS | 정상 200, DetectionOnly SQLi 형태 요청 통과, On 403·백엔드 미도달, rate 429 | 실제 ALB 경유·WAF 전체 정확도 |
| Suricata | 실제 설정 검사 통과 | NFQUEUE 차단 verdict·장애 시 동작 |
| Apache/PHP-FPM·WordPress·DVWA·MySQL 8.4.11 | HTTP 정상, 검증된 TLS, plaintext/잘못된 CA 거부, DB 권한 분리, seed 재실행 | 실제 RDS·DB 감사 전체 |
| Elasticsearch/Kibana 8.19.20 | 실제 정책 API, 원문 보존 파서, WAF 요청 ID, Defend 탐지 모드 확인 | Fleet/Agent 등록·커널 EDR·전체 경보 전달 |
| Velociraptor 0.77.2 | 실제 프로세스/로그 ZIP 수집·재시도 | AWS SSM·교차 계정 업로드·메모리 수집 |
| 실제 ZIP → Atlas | **17소스, 125레코드, 18시간 관찰, 2공유 요청**, 반복 입력 신규 0 | IAM/STS·EC2·RDS 관계 모델·AWS 자동 사건 연동 |

명령/출력: [정적·회귀 검사 JSON](local-validation.json), [실제 Linux 서비스 검사 JSON](linux-validation.json).
Atlas 79개와 신규 실행기/입력 검사 4개를 함께 실행한 최종 터미널 결과는 `83 passed in 4.41s`였다. cloud-lab 63개에는 그 4개가 포함된다. 합산 고유 검사는 142개다.

로컬 증거는 `.runtime/local-proof/atlas-roundtrip/`에 있다. manifest의 계정·버킷·버전은 **LOCAL_DOCKER_REHEARSAL_NOT_AWS**로 명시한 fixture다. 원본 ZIP SHA-256은 `cb05c703d22184cb27faab4cf75ce0e89cb3308675c8bc248703a063187268cc`다. 개인정보/실제 조사 증거 및 자격증명은 Git에 넣지 않는다.

## 발견 후 수정한 문제

- EC2 설치 파일이 user-data 한도를 넘음 → 버전이 고정된 S3 bootstrap bundle과 해시 검증 loader로 변경. 역할별 의존성을 분리해 순환 참조 제거.
- ModSecurity 패키지 설정 경로·요청 ID 연결, WordPress/DVWA TLS 및 PHP 실행 환경, seed 로그 소유권 보완.
- Alert polling의 페이지/재시도·원자적 사건 중복 방지, source/version/hash·부분 수집 처리 보완.
- 실제 구성에 없는 포트/사용자/취약점 경로를 시나리오에서 제거. S0~S3는 제한된 HTTP 점검, S4~S6는 수동 수락 검사로 명시.
- Atlas에 검증된 증거 묶음 가져오기와 WAF 공유 참조를 추가. 시각대가 없는 WAF 시각에 UTC를 임의 부여하지 않는다.

## AWS로 넘어갈 때 남는 확인

계정/프로필·배포 역할, 실제 Ubuntu AMI·지역 가용성·총비용 견적, 실제 AWS plan이 필요하다. 이후 SSM/IAM/KMS, 계정 간 로그·증거 전달, Agent/IPS 동작과 누락/지연을 단계별 확인한다. `collection_enabled=false`, AWS WAF 비활성이 기본이다.

Atlas의 AWS 전용 엔터티·세션 상관분석, 전체 SIEM 연동, 메모리·대용량 수집, CloudTrail digest 서명 검증, RDS/ALB/DNS 증거의 완전한 사건 수집, 자동 격리·복구 실행 및 AI 정확도 평가는 미완료다. 기존 MFT 검색 문제도 별도다. **로컬 마지막 검증 완료가 전체 프로젝트 완료를 뜻하지 않는다.**
