# Third-Party Notices

이 프로젝트는 아래 오픈소스/서드파티 소프트웨어를 사용합니다.

## Infrastructure

| 소프트웨어 | 버전 | 라이선스 | 용도 |
|-----------|------|---------|------|
| OpenTofu | 1.8+ | MPL-2.0 | Infrastructure as Code |
| AWS Provider | ~> 5.0 | MPL-2.0 | AWS 리소스 관리 |

## Application Stack

| 소프트웨어 | 버전 | 라이선스 | 용도 |
|-----------|------|---------|------|
| WordPress | 7.1 | GPL-2.0 | 대상 웹 애플리케이션 |
| Nginx | 1.x | BSD-2-Clause | 리버스 프록시 |
| Apache HTTP Server | 2.4 | Apache-2.0 | PHP 애플리케이션 서버 |
| PHP | 8.3 | PHP License | WordPress 런타임 |
| MySQL (RDS) | 8.4 | GPL-2.0 | 데이터베이스 |
| DVWA | latest | GPL-3.0 | 취약 웹 애플리케이션 (교육용) |

## Security & Monitoring

| 소프트웨어 | 버전 | 라이선스 | 용도 |
|-----------|------|---------|------|
| Suricata | 7.x | GPL-2.0 | 네트워크 IPS |
| Elasticsearch | 8.19.20 | Elastic License 2.0 / SSPL | 로그 저장·검색 |
| Kibana | 8.19.20 | Elastic License 2.0 / SSPL | 로그 시각화 |
| Elastic Agent | 8.19.20 | Elastic License 2.0 | 엔드포인트 에이전트 |
| Velociraptor | latest | AGPL-3.0 | 호스트 포렌식 수집 |

## Python Dependencies (Lambda / Collectors)

| 패키지 | 라이선스 | 용도 |
|--------|---------|------|
| boto3 | Apache-2.0 | AWS SDK |
| elasticsearch | Apache-2.0 | ES 클라이언트 |

## 공격 도구 (교육용 — 격리 환경에서만 사용)

| 도구 | 라이선스 | 용도 |
|------|---------|------|
| Nikto | GPL-2.0 | 웹 스캐너 |
| WPScan | WPScan License | WordPress 스캐너 |
| SQLMap | GPL-2.0 | SQL Injection 테스트 |
| Hydra | AGPL-3.0 | 브루트포스 테스트 |
| Gobuster | Apache-2.0 | 디렉토리 열거 |

## 라이선스 고지

각 소프트웨어의 전체 라이선스 텍스트는 해당 프로젝트의 공식 저장소를 참조하세요.

- Elastic License 2.0: https://www.elastic.co/licensing/elastic-license
- SSPL: https://www.mongodb.com/licensing/server-side-public-license
- AGPL-3.0: https://www.gnu.org/licenses/agpl-3.0.html

> 이 프로젝트는 교육/연구 목적의 DFIR 포렌식 실습 환경입니다.
> 모든 공격 도구는 격리된 실습 환경에서만 사용됩니다.
