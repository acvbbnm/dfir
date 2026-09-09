# 오픈소스 활용과 AWS DFIR 샘플 재사용 계획

검토일: 2026-09-09 · 상태: 설계 선택, 도구 설치·배포 전

전체 계획은 [DESIGN.md](DESIGN.md), AWS 경계와 증거 파이프라인은 [CLOUD_FORENSICS.md](CLOUD_FORENSICS.md)를 따른다. 모든 신규 작업은 evidence-atlas 저장소에서 진행한다.

## 1. 재사용 원칙

수집 엔진·로그 파서·탐지 규칙·IaC 실행기를 기존 도구로 구성한다. 직접 개발할 부분은 경보와 사건의 계약, 증거 계보, 서로 다른 호스트·요청·프로세스의 관계, 시간 의미, AI 근거 검토와 파이프라인 상태 연결이다.

원본 파일을 분석 도구에 넘기는 것과 분석 결과를 원본 증거로 취급하는 것을 구분한다. 각 도구의 출력은 엔진·규칙·버전·입력 해시가 붙은 파생 결과다. 탐지 결과만 남기고 EVTX·JSON·수집 파일을 삭제하지 않는다.

## 2. 사용자가 지정한 AWS 저장소 검토

- 저장소: [aws-samples/auto-cloud-digital-forensics-incident-response](https://github.com/aws-samples/auto-cloud-digital-forensics-incident-response).
- 검토 커밋: `1937f43cc4a36040c5c159a523b92b85fb903995`.
- 커밋 시각: 2021-06-30. GitHub는 2026-01-22 보관 처리 상태를 표시한다.
- 라이선스: [MIT-0](https://github.com/aws-samples/auto-cloud-digital-forensics-incident-response/blob/1937f43cc4a36040c5c159a523b92b85fb903995/LICENSE).
- README, Lambda Python 파일 4개, 주요 CloudFormation 5개, requirements를 읽었다. 실행·배포·전체 보안감사를 수행한 것은 아니다.

이 샘플은 실행 중 EC2의 선별 수집을 지원하는 동적 인프라에 초점을 둔다. 계정·호스트 목록으로 계정별 처리를 나누고 EFS와 DataSync 등 수집 기반을 준비한다. 완성된 범용 탐지·격리·스냅샷·메모리 분석 제품으로 간주하지 않는다.

### 2.1 코드에서 재사용할 설계

| 원본 | 확인한 역할 | 우리 계획에 반영 |
|---|---|---|
| [StartDFIRParent.py](https://github.com/aws-samples/auto-cloud-digital-forensics-incident-response/blob/1937f43cc4a36040c5c159a523b92b85fb903995/StartDFIRParent/StartDFIRParent.py) | S3 대상 목록을 읽어 계정별 Lambda 호출 | 검증된 사건 JSON을 account/region/host 단위 작업으로 분리. 문자열 목록을 그대로 명령으로 사용하지 않음 |
| [StartDFIRChild.py](https://github.com/aws-samples/auto-cloud-digital-forensics-incident-response/blob/1937f43cc4a36040c5c159a523b92b85fb903995/StartDFIRChild/StartDFIRChild.py) | AssumeRole, 대상 VPC/AZ·SG 탐색, 배포 파라미터 준비 | 임시 자격증명과 대상 메타데이터를 이용한 수집 준비. 현재 계약에 맞게 어댑터 구현 |
| [TargetResources.yaml](https://github.com/aws-samples/auto-cloud-digital-forensics-incident-response/blob/1937f43cc4a36040c5c159a523b92b85fb903995/builddfir/TargetResources.yaml) | EFS·mount target·DataSync agent용 EC2 | 작업별 자원 수명·수집 경로를 참고. 기본 배포에는 이 리소스 묶음을 포함하지 않음 |
| [PrepDataSyncConn.py](https://github.com/aws-samples/auto-cloud-digital-forensics-incident-response/blob/1937f43cc4a36040c5c159a523b92b85fb903995/PrepDataSyncConn/PrepDataSyncConn.py) | DataSync agent 활성화 준비 | 전송 작업 ID·검증·정리 단계가 수집과 별개라는 점을 반영 |
| [BuildDFIRResources.yaml](https://github.com/aws-samples/auto-cloud-digital-forensics-incident-response/blob/1937f43cc4a36040c5c159a523b92b85fb903995/builddfir/BuildDFIRResources.yaml) | DFIR VPC·peering·서비스 endpoints 구성 | 서비스별 실제 통신 경로와 비용을 명시하고 필요한 endpoint만 선택 |

### 2.2 현재 환경에서 바꿀 부분

- CloudFormation의 여러 Lambda가 `python3.8`이다. 현재 지원 런타임과 라이브러리로 검증해야 한다. Python 3.8은 Lambda의 deprecated 항목이다. [공식 런타임 표](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)
- `TargetResources.yaml`에 m5.2xlarge DataSync agent 정의가 여러 개 있고, 다수 서비스 endpoints·CodePipeline·CodeDeploy·CodeCommit 의존이 있다. 자원 조건에 따라 달라지지만, 기존 소형 실습 견적에 전체 배포 비용이 포함되어 있지 않다.
- EFS/DataSync는 현재 소량 수집의 기본 경로에서 제외한다. 후속 Windows 수집에는 EFS를 직접 마운트하는 방식도 적용할 수 없다. [EFS 지원 범위](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AmazonEFS.html)
- 계정·VPC·스택 이름과 대상 목록 형식에 가정이 있다. 현재 계정 구조·명시적 resource ARN·job ID 계약으로 바꿔야 한다.
- 일부 함수의 호출 간 공유 전역 목록, 구분자 기반 입력 처리, 예외 처리와 작업 재시도는 이 프로젝트의 중복·부분 실패 시험 대상으로 재설계한다.
- IAM의 `Resource: '*'`를 일괄 복사하지 않는다. Describe 등 자원 단위 제한이 불가능한 API는 이유를 기록하고, 변경 API는 지원되는 ARN·태그·조건으로 제한한다.

**선택:** 원본 저장소의 고정 커밋을 참조하고 필요한 패턴만 활용한다. 현재 단계에 원본 파일을 vendor하거나 배포 스크립트를 실행하지 않는다. 코드를 실제 복사하면 출처·커밋·라이선스·변경 이유를 해당 파일과 의존 목록에 기록한다.

## 3. 우선 도입할 구성

| 역할 | 도구 | 사용 방식 | 라이선스·확인 사항 |
|---|---|---|---|
| IaC | [OpenTofu](https://github.com/opentofu/opentofu) | VPC·IAM·로그·수집·정리 자원 정의 | MPL-2.0. 아직 IaC 구현이 없어 기존 Terraform 실행기 계획을 변경해도 state 이전은 없음 |
| Windows/Linux 선별 수집 | [Velociraptor](https://github.com/Velocidex/velociraptor) | SSM으로 사전 정의된 offline collector 실행, 결과와 선택 원본 보존 | AGPLv3 기반. 확정 배포물의 LICENSE와 의존 도구 조건 기록 |
| EVTX 파싱 | [EvtxECmd/evtx](https://github.com/EricZimmerman/evtx) | 기존 Atlas CSV 경로 활용, 고정 maps와 버전 사용 | 개별 저장소·배포물의 LICENSE 검증 후 lock 등록 |
| EVTX 탐지·시간축 보조 | [Hayabusa](https://github.com/Yamato-Security/hayabusa) | raw EVTX → JSON/CSV 탐지 결과 → Atlas 외부 탐지 결과 adapter | 현재 main의 LICENSE.txt는 AGPLv3. 오래된 소개의 MIT 표기를 그대로 쓰지 않음 |
| 공통 탐지 규칙 | [SigmaHQ](https://github.com/SigmaHQ/sigma) | 검토한 규칙 일부를 고정하여 적용 | 규칙은 DRL-1.1. 작성자·규칙 ID·수정 이력을 결과 화면에도 보존 |
| Sigma 변환 | [pySigma](https://github.com/SigmaHQ/pySigma), [Elasticsearch backend](https://github.com/SigmaHQ/pySigma-backend-elasticsearch) | 선택 규칙을 Elastic 쿼리로 변환, 필드 pipeline 검증 | core LGPL-2.1, 해당 backend LGPL-3.0. 둘을 같은 라이선스로 표시하지 않음 |
| 검증 시나리오 | [Atomic Red Team](https://github.com/redcanaryco/atomic-red-team) | 검토한 개별 테스트의 탐지 목적·실행·정리 절차 재사용 | MIT. 전체 테스트를 자동 실행하지 않고 사설 랩 범위·외부 의존·영향을 검토 |
| 시간축·관계·AI 근거 | Evidence Atlas | 원본 계보·사건·관계·가설 UI와 보고서 | 이 프로젝트가 직접 개발할 핵심 |

2026-09-09 GitHub API 확인에서 Velociraptor, Hayabusa, OpenTofu, pySigma, 해당 backend, Atomic Red Team은 archive 상태가 아니고 2026년 9월 소스 활동이 확인됐다. 이것이 최신 HEAD의 안정성이나 배포 호환성을 보장하지는 않는다. 설치 시 안정 릴리스 태그·바이너리 해시·rule commit을 고정한다.

### 3.1 무료·소스 공개·오픈소스의 구분

- KAPE 실행 파일은 Kroll EULA를 따르는 별도 제품이다. 기존 KAPE 결과 입력은 유지하되 새 배포 패키지에 실행 파일을 무조건 재배포하지 않는다. 사용할 권한이 있는 사용자가 준비한 도구로 실행하는 선택 경로를 둔다. [KAPE EULA](https://www.kroll.com/en/kape-license-agreement)
- Elastic의 Basic은 기능 구독 등급이다. Elasticsearch/Kibana의 소스 라이선스 선택과 기본 배포물·Defend 기능 조건은 구분한다. 전체 Elastic 스택이 단일 오픈소스 라이선스라고 표시하지 않는다. [Elastic 라이선스 설명](https://www.elastic.co/pricing/faq/licensing)
- Sysmon은 Microsoft 도구이며 별도 사용 조건을 따른다. 이벤트 수집에 유용하다고 오픈소스 목록에 넣지 않는다.
- AWS WAF·S3·Step Functions 등은 AWS 관리형 서비스다. 그 위의 OpenTofu·Lambda 코드 재사용과 AWS 서비스 사용료는 별개다.
- 오픈소스를 적극 활용한다는 방향은 유지하되 모든 구성요소가 오픈소스라고 주장하지 않는다.

도구를 독립 CLI로 실행하고 결과 파일로 연결하는 것을 기본으로 한다. AGPL/LGPL 조건을 회피할 수 있다고 가정하지 않으며, 배포할 소스·수정본·라이선스 고지는 선택 버전별로 확인한다. 아직 배포물을 재배포하지 않는다.

## 4. Velociraptor 수집 설계

### 4.1 상시 수집 서버 없이 시작

`offline`은 실행 중인 OS에서 별도 Velociraptor 서버 연결 없이 수집한다는 의미다. 꺼진 디스크를 수집한다는 뜻이 아니다. [공식 offline collection 구조](https://docs.velociraptor.app/docs/deployment/offline_collections/)

기본 흐름:

1. 관리 환경에서 Windows/Linux별 고정 collector와 artifact 설정을 준비하고 원본 바이너리·설정·포함 도구의 해시를 기록한다.
2. SSM은 허용된 collector ID를 실행한다. 사건 로그에서 가져온 임의 VQL이나 명령을 실행하지 않는다.
3. 빠른 프로세스·연결·사용자 정보와 선택 아티팩트의 파싱 결과를 수집하고, 조사에 필요한 EVTX·하이브 등의 원본도 함께 확보한다.
4. 결과를 별도 작업 볼륨의 collection ZIP에 기록한다. local write·새 프로세스 등 수집이 남기는 흔적을 manifest에 기록한다.
5. 별도 업로드 단계가 instance profile의 임시 자격증명과 제한된 staging prefix를 사용해 S3로 전송한다. 장기 AWS key를 collector에 내장하지 않는다.
6. 보안 계정에서 업로드를 검증한 뒤 사건의 최종 증거 객체와 manifest로 승격한다.
7. 로컬에서 동일 원본을 EvtxECmd/Hayabusa로 추가 처리한다. endpoint 파싱 결과와 독립 재파싱 결과를 구별한다.

Velociraptor 자체 S3 업로드도 가능하지만, 기본안은 업로드·재시도·권한을 공통 수집 wrapper에서 관리한다. Generic collector 방식 등으로 서명된 기본 바이너리와 설정을 분리할 수 있는지 선택 버전에서 검증한다. 재패키징 시 원래 디지털 서명을 그대로 검증할 수 있다고 가정하지 않는다.

### 4.2 실제 연동 전에 통과할 시험

- 최소 Linux 상태 수집 1건·AWS 원본 1건. Windows EVTX는 후속 선택 검증으로 원본·결과·메타데이터 대응 확인.
- 제한된 SSM/업로드 역할과 격리 SG에서 수행.
- 크기 초과·업로드 단절·ZIP 손상·부분 수집 상태 확인.
- collector 출력의 hostname을 AWS instance ID와 독립 대조.
- unpack 시 경로 이탈·압축 폭탄·악성 파일 자동 실행 차단.
- Atlas에 직접 넣을 수 없는 Velociraptor JSON/ZIP을 지원한다고 표시하지 않음. collection manifest adapter를 구현하고 형식 계약 시험 후 활성화.

KAPE는 같은 Windows 원본을 비교 수집하는 선택 경로로 유지한다. 두 수집 결과는 scope·job·tool을 구분하며 하나로 합쳐 원본을 없애지 않는다.

## 5. 탐지 결과를 Atlas와 연결

Hayabusa와 Elastic 탐지는 서로 다른 엔진 결과다. 룰과 필드 매핑이 다르면 동일 건수가 나오는 것을 정답으로 삼지 않는다. 기존 자체 Sigma 엔진을 무조건 확장하기보다, 외부 엔진 결과를 수용하고 비교하는 계층을 먼저 만든다.

### 5.1 결과 계약

필수 필드: case_id, engine/version, input SHA-256, rule ID/title/author/license/commit, result ordinal, host identifier, event locator, observed time, severity, raw result와 처리 오류.

EVTX locator는 원본 파일 해시 + provider/channel/computer + record ID를 기본으로 한다. record ID 단독으로 다른 EVTX·호스트를 연결하지 않는다. 변환 CSV/JSON과 원본 EVTX 사이의 매핑은 검증한 경우에만 연결한다. locator가 부족하면 후보로 표시한다.

기존 도구의 match는 `external_detection`으로 표시한다. 그래프 edge의 basis는 어떤 원본 필드가 일치했는지 따로 기록한다. Hayabusa 요약 한 줄을 새로운 원본 실행 사실로 재생성하지 않는다.

### 5.2 직접 구현할 경계

- 경보 API 조회·중복 억제·사건 계약과 자원 매핑.
- collection ZIP/manifest 입력 및 raw source 계보.
- WAF/ALB/CloudTrail/OS 로그의 시간·계정·호스트 관계.
- Hayabusa·Sigma 결과의 원본 locator와 작성자 표시.
- 수집 실패·전송 지연·분석 미지원 표시.
- AI 인용 검증, 분석가의 가설 상태·반증 기록.

## 6. 후속 도구의 도입 조건

| 후보 | 도입 조건 |
|---|---|
| Volatility 3 | 실제 메모리 이미지·심볼·선택 플러그인 호환 검증 후 사용. VSL 사용자 정의 라이선스를 별도 검토하며 메모리 수집 도구로 표현하지 않음. [프로젝트](https://github.com/volatilityfoundation/volatility3) |
| Plaso | Linux·파일시스템 등 광범위 파싱이 필요해질 때 입력 크기·CPU·시간 의미 손실을 평가. 별도 정규화 adapter 필요. [프로젝트](https://github.com/log2timeline/plaso) |
| Velociraptor 상시 서버 | 호스트 수가 늘고 반복 원격 질의가 실제로 필요할 때. 초기 소형 EC2/RDS 구성에서는 상시 VM 비용을 추가하지 않음 |
| AWS Automated Forensics Orchestrator | 별도 사건 계정·대규모 수집을 확장할 때 공식 구현과 비교. 현재 2021년 샘플과 같은 제품으로 혼동하지 않음. [공식 안내](https://docs.aws.amazon.com/solutions/latest/automated-forensics-orchestrator-for-amazon-ec2/welcome.html) |

## 7. 버전·라이선스 기록과 완료 기준

A0에서 `cloud-lab/toolchain.lock.json`과 `cloud-lab/THIRD_PARTY_NOTICES.md`를 생성한다. 파일 생성 계획은 이 문서와 루트 DESIGN.md 5.6에 등록한다. 현재 값이 정해지지 않은 버전을 임의의 최신값으로 채우지 않는다.

lock에는 이름, upstream URL, release tag, commit, OS/architecture, artifact URL/SHA-256, artifact/rule 설정 해시, license URL/SPDX, 검증 일자와 결과를 기록한다. 예외·미확인 라이선스는 UNKNOWN으로 남겨 배포 패키지 포함을 보류한다.

진행 상태:

- [x] AWS 샘플 고정 커밋과 주요 코드·리소스 검토.
- [x] 오픈소스 우선 구성과 자체 개발 경계 설계.
- [ ] 안정 릴리스·바이너리·규칙 버전 고정.
- [ ] Velociraptor 최소 수집과 독립 해시 검증.
- [ ] EvtxECmd/Hayabusa 결과를 원본 EVTX에 연결.
- [ ] pySigma 쿼리 변환과 실제 Elastic 매칭 대조.
- [ ] 재배포 대상 라이선스·NOTICE 기록과 패키지 검증.

현재 변경은 문서만이다. 소스 clone, 도구 설치, 샘플 배포, AWS 계정 생성 또는 과금 자원 생성은 수행하지 않았다.

## 8. 서비스·방어·중앙 SIEM 재설계에 추가한 재사용

2026-09-09 인프라 재설계에서 정상 서비스·실제 취약점·IPS·AWS 로그 수집 패턴을 추가했다. 아래는 후보 선정과 읽기 검토이며 버전 lock·설치·배포 완료를 뜻하지 않는다.

| 용도 | 재사용 대상 | 검토·변경 범위 |
|---|---|---|
| 정상 회원/게시/자료 서비스 | [WordPress](https://wordpress.org/about/requirements/) | PHP 8.3 이상·MySQL 8.0 이상 요구를 확인. GPLv2 계열과 선택 플러그인의 개별 조건을 lock에 기록 |
| 실제 웹 취약점 | [DVWA](https://github.com/digininja/DVWA) | GPLv3 또는 이후. 별도 FPM 사용자/DB 스키마, SQLi·명령/파일 실행만 먼저 검증. 원본 설정을 무조건 운영 WordPress에 적용하지 않음 |
| AWS SSRF·IAM·S3 실험 | [CloudGoat](https://github.com/RhinoSecurityLabs/cloudgoat) | BSD-3-Clause. ec2_ssrf README·EC2 설정·LICENSE를 읽음. 사설 배치·자원 한정 role·SSM 설치로 바꾼 실험을 구성 |
| 웹 경로 inline IPS | [Suricata](https://docs.suricata.io/en/suricata-8.0.1/ips/setting-up-ipsinline-for-linux.html) | GPLv2 계열 LICENSE 확인. NFQ 빌드·양방향 queue·drop 검증. 외부 rule set의 라이선스/commit은 별도 고정 |
| 중앙 로그 정규화 | [SIEM on Amazon OpenSearch Service](https://github.com/aws-samples/siem-on-amazon-opensearch-service) | README·지원 로그·구성을 확인, MIT-0 표기. 소스별 수집/정규화와 대시보드 설계를 참고. 전체 loader 코드 감사·Elastic 호환 검증·배포는 미완료 |

CloudGoat ec2_ssrf 원본 EC2 구성에는 public IP, IMDS optional, 넓은 S3/CloudWatch 권한, root 실행·cron 재기동이 있다. 이를 정상 서비스에 그대로 적용하지 않는다. 원본 시나리오의 최종 목표와 우리 제한 실험 목표를 구분하고, 실험용 앱/권한/설정 변경 diff를 남긴다. CloudGoat CLI의 Terraform 요구와 OpenTofu 호환을 이미 검증한 것으로 표시하지 않는다. 첫안은 필요한 설정·앱을 고정 커밋에서 검토해 우리 IaC에 선택 이식한다.

사용자 제공 images.jpg는 AWS 서비스/finding·중앙 S3·ETL·SIEM·알림 구성을 검토하는 기준이다. 기존 Elastic을 유지할 경우 OpenSearch 전용 인증·template·loader를 교체 없이 사용할 수 있다고 가정하지 않는다. 두 SIEM을 상시 중복 운영하지 않는다.

Windows EVTX·KAPE·Hayabusa는 기존 지원 자산과 후속 선택 경로다. 첫 AWS 사건은 CloudTrail·정책·S3 객체와 Linux/RDS 로그로 연결하며 Windows 수집을 인프라의 전제 조건으로 두지 않는다.
