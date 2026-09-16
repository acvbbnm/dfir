# AWS 배포 전 로컬 검증 재현

2026-09-16: AWS는 미배포다. 격리된 Docker Linux에서는 실제 서비스 검증을 수행했다. 최신 결과는 [시나리오 수정 기록](results/SCENARIO_FIXES.md), 이전 기준선은 [검증표](results/LOCAL_VALIDATION.md), 배포 기준은 [DEPLOYMENT.md](DEPLOYMENT.md)를 따른다.

## Python·Bash·OpenTofu

저장소 루트에서 실행한다. Python 3.12 이상, Git Bash, OpenTofu 1.9.0이 필요하다.

```powershell
python -m venv .runtime/dev-venv
.runtime/dev-venv/Scripts/python.exe -m pip install -r cloud-lab/requirements-dev.txt
$tofuPath = (Resolve-Path .runtime/opentofu/tofu.exe).Path
.runtime/dev-venv/Scripts/python.exe -B -X utf8 cloud-lab/scripts/validate_local.py --tofu $tofuPath --bash "C:/Program Files/Git/bin/bash.exe" --report .runtime/local-validation.json
.runtime/dev-venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider -q tests
```

OpenTofu를 `.runtime/opentofu/tofu.exe`에 별도 설치하거나 `$tofuPath`를 실제 설치 파일의 **절대 경로**로 바꾼다. 위 명령은 개인 재실행 결과를 `.runtime`에 남겨 커밋된 과거 검증 기록을 덮어쓰지 않는다. 검증기는 임시 복사본에서 provider init/backend 비활성·validate·Python/Bash/렌더링·Lambda ZIP 검사를 실행한다. 최초 provider 다운로드는 필요하지만 AWS 인증/API/backend를 사용하지 않는다. 기존 state/tfvars/backend/증거는 복사하지 않는다. `.terraform.lock.hcl`은 커밋하고 state는 제외한다.

## 실제 서비스 리허설

`local/Dockerfile`은 고정 Ubuntu 이미지 위에 실제 Nginx/ModSecurity/CRS/Suricata/Apache/PHP를 설치한다. `.runtime/cloud-artifacts`의 파일은 `artifacts.lock.json` 해시와 대조한다. 다음 스크립트는 **준비된 일회성 Linux 컨테이너 내부**에서 실행하도록 되어 있다. 일반 Windows나 실제 운영 호스트에서 바로 실행하지 않는다.

| 파일 | 요구 환경/검사 |
|---|---|
| `rehearse.py` | `/src` 또는 Docker COPY 경로의 설정, `/artifacts/velociraptor`; 실제 WAF 200/403/429·백엔드 미도달·triage ZIP |
| `db_certificates.py` | 별도 local CA/ea-ready-db 인증서 생성; 유효 2일 |
| `rehearse_services.py` | TLS MySQL 8.4.11 `ea-ready-db`, `/artifacts`, `/src`, 전용 합성 DB; TLS/권한/seed |
| `rehearse_http.py` | 위 DB/서비스 초기화 후 실제 Apache/PHP-FPM HTTP/감사 |
| `rehearse_collector.py` | Velociraptor와 위 호스트 파일; 출력 ZIP 재시도 |
| `soc_certificates.py` | 별도 local SOC CA/ea-ready-soc 인증서 생성; 유효 2일 |
| `rehearse_siem.py` | TLS ES/Kibana 8.19.20 `ea-ready-soc`, `/tmp/ea-soc-tls/ca.pem`; 실제 API/파서/정책 |
| `rehearse_scenarios.py` | 위 정책 적용 후 실제 API 이벤트 검색·keyword 집계, Velociraptor 지속성 marker ZIP·재실행 |

리허설의 합성 비밀번호는 격리된 컨테이너 전용이다. ES/Kibana 정책 재실행 receipt는 테스트 컨테이너 `/tmp`에만 쓰고 배포용 자동 갱신으로 사용하지 않는다. host 포트를 공개하지 않고 internal DB 네트워크와 registry 다운로드용 별도 네트워크를 사용했다. 실제 Agent 커널 이벤트와 Suricata drop은 이 리허설에 포함되지 않는다.

수집 ZIP은 다음으로 오프라인 가져오기와 해시·중복·공유 요청을 재현할 수 있다. 출력 경로는 새 디렉터리를 사용한다.

```powershell
python cloud-lab/local/import_rehearsal.py .runtime/local-proof/triage.zip --output .runtime/local-proof/new-roundtrip
```

기존 사용자 컨테이너 `ea-elasticsearch`/`ea-kibana`/`webgoat`는 변경하지 않았다. 이 작업의 `ea-ready-*` 검증 컨테이너만 종료/제거한다. 실제 Linux 검증 출력은 [linux-validation.json](results/linux-validation.json)에 남긴다. 이미지 캐시는 재현용으로 남기며 자동 전체 prune은 하지 않는다.
