# Evidence Atlas — 확장 설계서

> **목적**: 이 문서는 Evidence Atlas의 현재 아키텍처, 핵심 설계 원칙, 확장 방향을 기술한다.
> 협업하는 AI(Claude, Codex, GPT 등)가 코드를 수정하거나 새 기능을 구현할 때 이 문서를 기준으로 판단한다.
> **최종 갱신**: 2026-09-16 · **현재 버전**: 0.2.0
> 현재 진행 상태의 단일 출처는 [README.md](README.md)다. 아래 초기 구조·실데이터 수치는 당시 기준선이며, 이후 구현 범위는 섹션 5~6을 따른다.

---

## 1. 프로젝트 정체성

Evidence Atlas는 **DFIR(Digital Forensics and Incident Response) 포렌식 증거 그래프 도구**다.

KAPE(Kroll Artifact Parser and Extractor)가 출력한 CSV를 파싱하여:
- 원래 CSV 레코드를 **변형 없이** SQLite에 보존하고
- 레코드 간 **의미 관계**(같은 경로, 같은 계정, 같은 프로세스 등)를 그래프로 모델링하고
- 시간축 위에 **13가지 시각 의미(time_kind)**를 구분하여 배치한다

기존 SIEM(Splunk, ELK)과 **경쟁하는 도구가 아니라**, 포렌식 수집 결과를 관계 중심으로 탐색하는 **분석 계층**이다.

---

## 2. 핵심 설계 원칙 — 변경 불가

아래 원칙은 모든 확장에서 반드시 유지해야 한다. 위반하는 PR은 거부된다.

### 2.1 증거 무결성 (Evidence Integrity)

- 입력 CSV/TXT의 **SHA-256 해시**를 `sources.sha256`에 기록한다
- 원래 CSV 행은 `records.raw_json`에 **원본 그대로** JSON 직렬화하여 보존한다
- 파싱 과정에서 원래 값을 수정·삭제·병합하지 않는다
- 파일 단위 트랜잭션으로 처리하며, 실패한 파일만 재시도한다
- 반복 가져오기 시 동일 해시의 파일은 중복 추가하지 않는다

### 2.2 인과 확정 금지 (No Causal Determination)

- 경로·계정·시각의 공유는 **공유 참조(shared reference)**이지 인과 주장이 아니다
- 그래프 edge의 `basis` 필드에 연결 근거를 명시한다
- "공격", "악성", "실행 확정" 같은 단정적 레이블을 자동 부여하지 않는다
- AI 가설은 `unreviewed_hypotheses` 상태로만 제공하며, 인용 식별자의 존재만 검증한다

### 2.3 시각 의미 보존 (Time Kind Semantics)

시각(timestamp)마다 **의미가 다르다**. 이것이 Evidence Atlas의 핵심 차별점이다.

```
time_kind 13종:
  event_recorded            — 이벤트가 기록된 시각
  prefetch_recorded_run     — Prefetch가 기록한 실행 시각
  amcache_key_write         — Amcache 레지스트리 키 기록 시각 (실행 시각 아님)
  file_last_modified        — 캐시에 기록된 파일 수정 시각 (실행 시각 아님)
  bam_recorded_execution    — BAM의 실행 시각 필드
  userassist_last_executed  — UserAssist의 마지막 실행 시각 필드
  destlist_entry_created    — Jump List 항목 생성 시각
  destlist_entry_modified   — Jump List 항목 수정 시각
  shortcut_container_created  — 바로가기/목록 컨테이너 생성 시각
  shortcut_container_modified — 바로가기/목록 컨테이너 수정 시각
  target_created_metadata   — 바로가기에 저장된 대상 생성 시각
  target_modified_metadata  — 바로가기에 저장된 대상 수정 시각
  target_accessed_metadata  — 바로가기에 저장된 대상 접근 시각
```

모든 새 어댑터는 반드시 `time_kind`를 명시해야 한다. "timestamp"라는 모호한 이름은 허용하지 않는다.

### 2.4 수집 범위 분리 (Scope Isolation)

- C 드라이브와 VSS(Volume Shadow Copy)는 별도 수집 범위(`scope`)다
- 같은 흔적이 두 범위에 있어도 **각각의 출처를 독립 보존**한다
- `\Device\HarddiskVolumeN`을 임의로 `C:`에 매핑하지 않는다
- 사건(case) 간 그래프 참조를 공유하지 않는다

---

## 3. 초기 아키텍처 기준선 (확장 전 v0.2.0)

이 절은 초기 KAPE 구조와 당시 데이터 규모를 보존한다. 현재는 ES 투영, 그래프 UI, Sigma, Sysmon/SRUM, MFT/USN 인덱스, cloud-import 코드가 추가되었다. MFT 검색 통합과 AWS 관계 분석은 미완료다. 현재 사용법은 [docs/USAGE.md](docs/USAGE.md)를 따른다.

### 3.1 모듈 구조

```
dfir_graph/
├── __init__.py      — 버전 (0.2.0)
├── __main__.py      — CLI 진입점 (ingest, stats, search, evidence, export, load-neo4j, analyze, serve)
├── model.py         — 식별자 생성(uid), SHA-256, 경로 정규화, 시각 파싱, 범위 판별
├── store.py         — SQLite 스키마·CRUD (cases, imports, sources, records, nodes, edges, issues)
├── adapters.py      — CSV 헤더 분류(classify) + 10개 어댑터 함수 + Projection 클래스
├── pipeline.py      — 가져오기 오케스트레이션 (파일 목록 → 분류 → 어댑터 호출 → 트랜잭션)
├── timeline.py      — 시간축 인덱스 (7개 lane, 관찰 정렬, 관련 기록 조회)
├── neo4j_io.py      — Neo4j 투영 + JSONL 내보내기
├── analysis.py      — 근거 묶음 생성, Markdown 보고서, 로컬 Ollama 가설
├── filesystem.py    — MFT/USN 디스크 인덱스 (별도 SQLite 테이블, 미통합)
├── viewer.py        — HTTP 서버 (시간축 UI + 분석 보조 API)
└── static/          — 프론트엔드 (timeline.js, index.html, style.css)
```

### 3.2 데이터 흐름

```
KAPE Modules CSV/TXT
       │
       ▼
[1] pipeline.py: 파일 목록 수집 → SHA-256 해시 → 헤더 기반 분류(classify)
       │
       ▼
[2] adapters.py: CSV 행 → records(원본 보존) + nodes/edges(의미 관계)
       │                   Projection 클래스가 observe/node/edge 공통 로직 제공
       ▼
[3] store.py (SQLite): 단일 파일 DB
       │  ├── sources: 파일 메타데이터 + SHA-256
       │  ├── records: 원래 CSV 행 (raw_json)
       │  ├── nodes: 그래프 노드 (15종 라벨)
       │  ├── edges: 그래프 관계 (23종 타입)
       │  └── issues: 파싱 경고/오류
       ▼
[4] timeline.py: records → 시간축 관찰 인덱싱 (7개 lane)
       │
       ├──→ viewer.py: HTTP API + 웹 UI
       ├──→ neo4j_io.py: Neo4j Community 투영 (선택)
       ├──→ analysis.py: 근거 묶음 + 보고서 + AI 가설 (선택)
       └──→ JSONL export: nodes.jsonl + edges.jsonl
```

### 3.3 그래프 스키마

**노드 라벨 15종:**

| 라벨 | 의미 | 생성 어댑터 |
|------|------|------------|
| Case | 사건 | 모든 가져오기 |
| EvidenceSource | CSV 파일 출처 | 모든 가져오기 |
| Host | 호스트 (컴퓨터) | evtxecmd, pecmd |
| Snapshot | 수집 범위 (C/VSS) | 모든 어댑터 |
| Observation | 시간축 관찰 (핵심) | 모든 어댑터 |
| ProcessInstance | 프로세스 인스턴스 (4688) | evtxecmd |
| ProcessReference | 부모 PID 참조 | evtxecmd |
| FilePath | 정규화된 파일 경로 | evtxecmd, pecmd, registry, link |
| Account | 계정 (SID/이름) | evtxecmd, bam |
| IPAddress | IP 주소 | evtxecmd (4624) |
| ScriptBlock | PowerShell 스크립트 블록 | evtxecmd (4104) |
| ExecutableReference | 실행 파일 참조 | pecmd |
| AmcacheEntry | Amcache 항목 | amcache_file |
| ArtifactEntry | 일반 아티팩트 항목 | appcompat, bam, userassist, link |
| ProgramReference | 프로그램 참조 (셸 식별자 포함) | userassist |

**관계 타입 23종:**

| 타입 | from → to | 의미 |
|------|-----------|------|
| HAS_SOURCE | Case → EvidenceSource | 사건에 속한 출처 |
| CONTAINS_OBSERVATION | EvidenceSource → Observation | 출처가 포함한 관찰 |
| OBSERVED_IN | Observation → Snapshot | 관찰의 수집 범위 |
| OF_HOST | Snapshot → Host | 범위의 호스트 |
| RECORDS_CREATION | Observation → ProcessInstance | 4688 프로세스 생성 |
| IMAGE_PATH | ProcessInstance → FilePath | 프로세스 이미지 경로 |
| REQUESTED_CREATION | ProcessReference → ProcessInstance | 부모→자식 참조 |
| REPORTED_TARGET_ACCOUNT | Observation → Account | 로그온 대상 계정 |
| REPORTED_PARENT | ProcessInstance → ProcessReference | 보고된 부모 PID |
| REPORTED_IMAGE_PATH | ProcessReference → FilePath | 부모의 이미지 경로 |
| REPORTED_ACCOUNT | ProcessInstance → Account | 프로세스 실행 계정 |
| REPORTED_SOURCE_ADDRESS | Observation → IPAddress | 로그온 원본 IP |
| RECORDS_SCRIPT_FRAGMENT | Observation → ScriptBlock | 4104 스크립트 블록 |
| REPORTED_SCRIPT_PATH | ScriptBlock → FilePath | 스크립트 경로 |
| RECORDS_EXECUTION_TIME | Observation → ExecutableReference | Prefetch 실행 참조 |
| RECORDS_AMCACHE_ENTRY | Observation → AmcacheEntry | Amcache 항목 기록 |
| AMCACHE_PATH | AmcacheEntry → FilePath | Amcache 보고 경로 |
| RECORDS_SHIMCACHE | Observation → ArtifactEntry | AppCompatCache 기록 |
| RECORDS_BAM_EXECUTION | Observation → ArtifactEntry | BAM 실행 기록 |
| BAM_ACCOUNT | ArtifactEntry → Account | BAM 계정 연결 |
| RECORDS_USERASSIST | Observation → ArtifactEntry | UserAssist 기록 |
| REPORTED_TARGET | ArtifactEntry → (FilePath\|ProgramReference) | 대상 경로/프로그램 |
| RECORDS_LINK_METADATA | Observation → ArtifactEntry | 바로가기/Jump List |

### 3.4 어댑터 목록 (10종)

| 어댑터 이름 | CSV 헤더 패턴 | 생성하는 관찰 kind |
|------------|--------------|-------------------|
| evtxecmd | RecordNumber, TimeCreated, EventId, Provider | process_creation, logon_success, logon_failure, powershell_scriptblock, evtx_other |
| pecmd | SourceFilename, SourceCreated, LastRun, ExecutableName, Hash | prefetch_execution |
| prefetch_timeline_derived | — | (중복 방지, 파일 목록만 기록) |
| amcache_file | ProgramId, SHA1, FullPath, FileKeyLastWriteTimestamp | amcache_file |
| appcompat_cache | ControlSet, CacheEntryPosition, Path, LastModifiedTimeUTC | appcompat_cache |
| bam | HivePath, KeyPath, ValueName, Value | bam_execution |
| userassist | HivePath, Description, ValueName, FolderName, RunCounter, LastExecutedTimestampUtc | userassist_execution |
| lecmd | SourceFile, SourceCreated, SourceModified, TargetCreated, TargetModified, LocalPath | lnk_metadata |
| jlecmd_automatic | SourceFile, EntryName, TargetCreated, TargetModified, LocalPath, Arguments | jumplist_entry |
| jlecmd_custom | (동일) | jumplist_entry |

### 3.5 시간축 7개 lane

```
lane 이름          | 포함 kind                        | CSS 색상
───────────────────┼──────────────────────────────────┼──────────
process            | process_creation                 | #4fc3f7
logon              | logon_success, logon_failure      | #81c784
powershell         | powershell_scriptblock            | #ba68c8
prefetch           | prefetch_execution                | #ffb74d
registry           | amcache_file, appcompat_cache,    | #f28b82
                   | bam_execution, userassist_execution|
links              | lnk_metadata, jumplist_entry      | #a1887f
other              | evtx_other                        | #90a4ae
```

### 3.6 현재 규모 (실 데이터 기준)

| 항목 | 수량 |
|------|------|
| 입력 파일 (SHA-256 추적) | 225개 |
| 파싱한 CSV | 27개 |
| 보존한 CSV 레코드 | 168,537개 |
| 시간축 관찰 | 171,360개 |
| 그래프 노드 | 28,877개 |
| 그래프 관계 | 79,956개 |
| 미지원 파일 (의미 파싱 없음) | 178개 |

### 3.7 기술 스택

| 계층 | 현재 기술 |
|------|----------|
| 언어 | Python 3.11+ (순수 표준 라이브러리, 외부 의존성 최소) |
| 기준 저장소 | SQLite 단일 파일 |
| 그래프 투영 | Neo4j Community 5.26.30 (선택, 재생성 가능) |
| 런타임 | Portable JRE 21 (Neo4j용) |
| 웹 서버 | Python http.server (내장) |
| 프론트엔드 | Vanilla JS + CSS (프레임워크 없음) |
| AI | 로컬 Ollama만 (127.0.0.1:11434 고정) |

---

## 4. 확장 전 약점 분석 (당시 기준선)

아래 표는 확장을 시작한 이유다. 그래프 UI·Sigma 매칭·ES 투영은 이후 구현되었으므로 현재 미구현 목록으로 읽지 않는다. 남은 범위는 README와 섹션 5~6에 기록한다.

| 영역 | 한계 | 영향 |
|------|------|------|
| **저장소 규모** | SQLite ~170K 이벤트, 수백만 행 시 성능 저하 | 대규모 사건/다중 호스트 분석 불가 |
| **검색** | 전문 검색 없음, SQL LIKE 의존 | 자유 텍스트 탐색 비효율 |
| **데이터 소스** | KAPE Modules CSV만 입력 | Sysmon, Linux auditd, 네트워크 로그 등 미지원 |
| **위협 탐지** | Sigma 규칙 매칭 없음 | 알려진 위협 패턴 자동 식별 불가 |
| **그래프 시각화** | 텍스트 목록 기반 UI, 시각적 그래프 없음 | 관계 탐색의 직관성 부족 |
| **다중 호스트** | 단일 호스트 중심 설계 | 횡이동(lateral movement) 분석 어려움 |
| **필드 정규화** | 자체 스키마, ECS/CIM 미적용 | 외부 도구 연동 시 매핑 필요 |

---

## 5. 확장 아키텍처 (TO-BE)

### 5.0 핵심 방향

Evidence Atlas는 SIEM을 대체하지 않는다. **SIEM 위에 올라가는 포렌식 분석 계층**으로 확장한다.

```
                    ┌─────────────────────────────────────────────┐
                    │         Evidence Atlas 분석 계층             │
                    │  (관계 그래프 + time_kind + 근거 보존)        │
                    └──────────────┬──────────────────────────────┘
                                   │ 읽기/쓰기
                    ┌──────────────▼──────────────────────────────┐
                    │         Elasticsearch 백엔드                 │
                    │  (전문 검색 + 집계 + 스케일링)                │
                    └──────────────┬──────────────────────────────┘
                                   │ 수집
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
   KAPE CSV (현재)          Sysmon/EVTX           네트워크 로그
   MFT/USN                 Linux auditd          패킷 캡처
   레지스트리               클라우드 로그           기타 소스
```

### 5.1 Phase 1: Elasticsearch 백엔드 — 동기화·조회 구현, 뷰어 전환 미완료

**목표**: SQLite 단일 파일의 규모 한계를 극복하면서 Evidence Atlas의 고유 모델을 유지한다.

#### 5.1.1 인덱스 설계

```
인덱스 이름                    | 용도
──────────────────────────────┼──────────────────────────
ea-sources-{case_key}          | 파일 출처 메타데이터 + SHA-256
ea-records-{case_key}          | 원래 CSV 레코드 (raw 필드 보존)
ea-nodes-{case_key}            | 그래프 노드
ea-edges-{case_key}            | 그래프 관계
ea-issues-{case_key}           | 파싱 경고/오류
```

`case_key`는 표시용 slug + 원래 case ID(대소문자·Unicode 포함)의 SHA-256이다. 원래 ID는 mapping `_meta.ea_case_id`에도 보관한다. 기존 slug 인덱스는 보존하며 정확한 사건이 일치할 때만 이전 조회를 허용한다. 별도 observations 인덱스는 아직 없고 관찰 속성은 nodes에 저장된다.

동기화는 모든 표를 최대 1,000문서씩 전송하고 각 응답을 검증한다. 부분 실패·응답 누락·refresh 실패는 성공으로 처리하지 않는다. 중단되면 같은 `es-sync`를 다시 실행한다. ES 전체 동기화는 원자적 트랜잭션이 아니며 SQLite 읽기는 한 스냅샷에서 수행한다.

성공한 동기화는 `ea-current-records` 등 `ea-current-{prefix}` 별칭에 현재 투영을 연결한다. Kibana는 이 별칭을 사용하여 보존된 구 인덱스와 신규 인덱스를 중복 집계하지 않는다. 다른 사건의 별칭 연결은 유지한다.

#### 5.1.2 ECS 필드 매핑 전략

Evidence Atlas 고유 필드와 ECS(Elastic Common Schema)를 **병행**한다. 변환이 아니라 추가다.

```json
{
  "@timestamp": "2026-08-31T14:23:01.000000Z",
  "event.kind": "event",
  "event.category": ["process"],
  "process.name": "powershell.exe",
  "process.pid": 4688,

  "ea.time_kind": "event_recorded",
  "ea.time_raw": "2026-08-31T14:23:01.1234567",
  "ea.scope": "C",
  "ea.case_id": "SBA-20260831",
  "ea.record_id": "record:abc123...",
  "ea.source_sha256": "e3b0c44...",
  "ea.adapter": "evtxecmd",
  "ea.adapter_version": "1"
}
```

- `ea.*` 접두어로 Evidence Atlas 고유 필드를 네임스페이스한다
- ECS 필드는 Sigma 규칙 호환성과 Kibana 연동을 위해 병행한다
- 원래 CSV 행은 `ea.raw` 필드에 보존한다 (증거 무결성)

#### 5.1.3 SQLite와의 관계

- SQLite는 **오프라인/단독 실행** 모드로 유지한다
- Elasticsearch는 **온라인/확장** 모드의 백엔드다
- **현재 구현**: 기존 어댑터로 SQLite에 수집한 후 `es-sync`로 ES에 투영한다. ES CLI 조회·검색·집계가 있다.
- **미구현**: `--backend` 선택, ES 직접 수집, ES 기반 시간축/웹 뷰어. 웹 뷰어와 근거 검토는 계속 SQLite를 사용한다.

#### 5.1.4 구현 계획

```
새 파일:
  dfir_graph/es_store.py      — Elasticsearch CRUD (Store와 동일 인터페이스)
  dfir_graph/es_mappings.py   — 인덱스 매핑 + ECS 변환 로직

수정 파일:
  dfir_graph/pipeline.py      — 백엔드 선택 분기 (--backend sqlite|elasticsearch)
  dfir_graph/__main__.py      — CLI 옵션 추가
  dfir_graph/timeline.py      — ES 기반 시간축 쿼리 지원
  dfir_graph/viewer.py        — ES 기반 API 응답 지원

의존성 추가:
  elasticsearch-py (8.x)

환경 변수:
  EA_ES_HOSTS                 — Elasticsearch 호스트 (기본: http://localhost:9200)
  EA_ES_API_KEY               — 인증 키 (선택)
```

### 5.2 Phase 2: 그래프 시각화 UI ✅ 구현·검증 완료 (2026-09-09)

**목표**: 현재 텍스트 목록 기반 관계 탐색을 시각적 그래프로 대체한다.

#### 5.2.1 요구사항

- 선택한 노드에서 1~2홉 관계를 **force-directed 그래프**로 렌더링
- 노드 라벨별 색상 구분 (15종 라벨 × 색상)
- 클릭 시 원래 CSV 레코드와 time_kind 정보 표시
- edge에 `basis`(연결 근거) 표시
- 시간축과 그래프 뷰 간 양방향 네비게이션
- **인과 관계가 아님을 UI에 명시**

#### 5.2.2 기술 선택지

| 옵션 | 장점 | 단점 |
|------|------|------|
| D3.js force-directed | 유연, 표준 | 대규모 노드 성능 |
| Cytoscape.js | 그래프 전용, 레이아웃 풍부 | 번들 크기 |
| vis.js Network | 간편, 물리 시뮬레이션 | 커스텀 어려움 |

권장: **Cytoscape.js** — 그래프 탐색에 특화, DFIR 도구에서 검증된 라이브러리

#### 5.2.3 구현 계획

```
새 파일:
  dfir_graph/static/graph.js   — 그래프 시각화 로직
  dfir_graph/static/graph.css  — 그래프 스타일
  dfir_graph/static/vendor/cytoscape.min.js — 버전 고정 로컬 번들
  dfir_graph/static/vendor/cytoscape.LICENSE — 라이선스
  tests/test_graph.py          — 사건 격리·탐색 제한·원본 회귀 검증
  tests/test_es.py             — ES 사건 격리·부분 실패·변환 회귀 검증

수정 파일:
  dfir_graph/static/index.html — 그래프 탭 추가
  dfir_graph/viewer.py         — /api/graph/neighbors 엔드포인트 추가
  dfir_graph/store.py          — 읽기 전용 1~2홉 탐색 추가
  dfir_graph/static/timeline.js — 시간축과 그래프 선택 연동
  pyproject.toml, .gitignore   — 로컬 번들의 패키징·Git 포함
```

#### 5.2.4 구현 결과와 제한

- 시간순 전체 맵을 유지한다. 요약/연결 탭의 **관계 지도 열기** 또는 참조 노드에서 진입한다.
- `Store.graph_neighbors()`를 추가했다. 기존 `neighborhood()`/CLI는 유지한다. 새 API는 1~2홉 BFS, 사건·양 끝 노드·원본 근거의 사건 일치 검증, 선택적 scope 필터를 적용한다.
- 기본 상한은 노드 100 / 관계 180, API 최대는 200 / 400이다. 잘린 결과는 화면에 명시한다. Case/Host/Snapshot/EvidenceSource 허브는 기본 제외하고 명시적으로 포함할 수 있다.
- 경로·계정 등 공유 참조는 C/VSS를 연결할 수 있지만 관찰을 병합하지 않는다. 선마다 원래 레코드의 host/scope와 basis를 반환하며, 범위 필터는 관계를 펼치기 전에 적용한다.
- 노드·선 선택으로 time_kind, 원본 CSV, 논리 레코드 번호, SHA-256 확인. 관찰에서 시간축 복귀, 중심 변경/이전 중심, 키보드용 목록 탐색을 지원한다. 시각 미확정 관찰은 시간축 복귀 버튼을 비활성화한다.
- Cytoscape.js **3.34.3**, MIT, npm 배포 SHA-512 검증 후 로컬 번들로 포함. CDN 요청 없음. 번들 SHA-256: `5f3b5b529546d5af1fc5628590af033b74511a5b6f789f5f4682845863228b91`.
- 30개 테스트, 실제 SBA 브라우저 흐름, ES 공격 샘플 37,357행의 표별 집계 일치와 원본 레코드 왕복 확인. 그래프 조회는 SQLite를 읽기 전용으로 연다.
- 아직 의미 해석하지 않는 `evtx_other`에는 그래프 연결을 만들어내지 않는다. Sysmon 1/3/11/22 어댑터는 이후 추가되었으며, 과거 DB의 `evtx_other` 행이 자동 재해석된다는 뜻은 아니다.

### 5.3 Phase 3: Sigma 규칙 매칭 ✅ 구현·검증 완료 (2026-09-09)

**목표**: Sigma 규칙으로 알려진 위협 패턴을 자동 식별한다.

#### 5.3.1 설계 원칙

- Sigma 매칭 결과는 **탐지 후보**이지 공격 확정이 아니다
- 매칭 결과에 `basis: "sigma_rule:{rule_id}"` 근거를 명시한다
- 별도 `detections` 테이블에 매칭 결과 저장
- 오탐률/정탐률 판단은 분석자 몫이다

#### 5.3.2 구현 결과

```
새 파일:
  dfir_graph/sigma_engine.py   — Sigma YAML 로딩 + 필드 매핑 + 조건 평가 + 레코드 매칭
  tests/test_sigma.py          — 24개 단위/통합 테스트

새 테이블:
  CREATE TABLE detections (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    rule_id TEXT NOT NULL,
    rule_title TEXT NOT NULL,
    rule_level TEXT NOT NULL,
    rule_file TEXT NOT NULL,
    matched_fields TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    basis TEXT NOT NULL DEFAULT 'sigma_match'
  );

CLI 명령:
  sigma-scan   — SQLite 레코드에 Sigma 규칙 매칭 실행
  sigma-stats  — 탐지 통계 (레벨별, 규칙별)
  sigma-list   — 탐지 결과 목록 (필터: case, level, rule-id)

뷰어 API:
  /api/detections       — 탐지 목록 (case, level, rule 필터)
  /api/detections/stats — 레벨별·규칙별 집계

의존성:
  PyYAML (기존), pySigma 1.5.0 (설치됨, 규칙 로딩 참조만 사용)
```

#### 5.3.3 지원 logsource 매핑

| EA record kind | Sigma logsource | 적용 규칙 수 |
|----------------|----------------|-------------|
| process_creation | category: process_creation | ~1,185 |
| powershell_scriptblock | category: ps_script | ~209 |
| logon_success | service: security (EventID 4624) | ~327 (필터) |
| logon_failure | service: security (EventID 4625) | ~327 (필터) |

#### 5.3.4 검증 결과 (EVTX-ATTACK-SAMPLES)

- 1,494개 규칙 로딩, 134개 레코드 스캔
- **125개 탐지**: critical 1, high 73, medium 40, low 11
- 39개 고유 규칙 매칭 (Credential Dumping, Pass the Hash, PowerShell 악용 등)
- 멱등 실행: 재스캔 시 중복 없음 (`INSERT OR IGNORE`)

### 5.4 Phase 4: 다중 데이터 소스 확장 — 어댑터 추가, 통합 보완 필요 (2026-09-09)

KAPE CSV에 더해 아래 소스를 단계적으로 추가한다.

| 우선순위 | 소스 | 어댑터 이름 | 비고 |
|---------|------|-----------|------|
| 1 | MFT/USN (MFTECmd 출력) | mftecmd_mft, mftecmd_usn | pipeline 저장·CLI/API 코드 추가, 소스 상태 불일치로 검색 통합 미완료 |
| 2 | Sysmon EVTX (EvtxECmd 출력) | evtxecmd (기존 확장) | ✅ EventId 1,3,11,22 추가 |
| 3 | SRUM/SUM (SrumECmd 출력) | srum_network, srum_app | ✅ 네트워크 사용량·앱 실행 이력 |
| 4 | Windows Event Forwarding | wef_evtx | 다중 호스트 수집 (미구현) |
| 5 | Linux auditd | auditd_log | 새 파서 필요 (미구현) |
| 6 | 네트워크 패킷 (Zeek 로그) | zeek_conn, zeek_dns | 네트워크 계층 관계 (미구현) |

#### 5.4.1 구현 결과

**Priority 1 — MFT/USN**: `filesystem.py`의 `ingest_rows()`를 `pipeline.py`에 통합. `classify()`에 MFT/USN CSV 헤더 패턴 추가. CLI 3종(`fs-sources`, `fs-search`, `fs-evidence`)과 뷰어 API 3종(`/api/filesystem/sources`, `/api/filesystem/search`, `/api/filesystem/evidence`) 추가.

**Priority 2 — Sysmon EVTX**: `ingest_evtx()`에 Sysmon 이벤트 4종 추가:
- EventId 1 (Process Create): `sysmon_process_create` — ProcessInstance 노드, 부모 프로세스 참조, 해시·무결성 수준 보존
- EventId 3 (Network Connect): `sysmon_network_connect` — IPAddress 노드, CONNECTED_TO/CONNECTION_SOURCE 엣지
- EventId 11 (File Create): `sysmon_file_create` — 생성 프로세스·대상 파일 경로 연결
- EventId 22 (DNS Query): `sysmon_dns_query` — DNSQuery 노드, 쿼리 이름·결과 보존

새 노드 라벨: `DNSQuery`
새 엣지 타입: `INITIATED_CONNECTION`, `CONNECTED_TO`, `CONNECTION_SOURCE`, `CREATION_PROCESS`, `REPORTS_FILE_CREATION`, `DNS_QUERY_PROCESS`, `REPORTS_DNS_QUERY`, `RECORDS_NETWORK_USAGE`, `RECORDS_APP_USAGE`, `SRUM_ACCOUNT`

**Priority 3 — SRUM**: `ingest_srum_network()`과 `ingest_srum_app()` 어댑터 추가. SrumECmd의 NetworkUsages/AppResourceUseInfo CSV 자동 분류. 네트워크 사용량과 앱 실행 이력을 시간축에 배치.

**Sigma 매칭 확장**: Sysmon 이벤트 4종에 대한 필드 매핑 추가. `network_connection`, `file_event`, `dns_query` 로그소스 카테고리 지원.

**검증**: 2026-09-09에는 75개 테스트가 통과했지만 별도 통합 재현에서 Sysmon 시간축 오류와 MFT 검색 오류가 확인되었다. 2026-09-16에는 새 kind의 시간축 fallback과 cloud-import를 보완한 Atlas 79개 테스트가 통과했다. MFT/USN은 pipeline이 `complete`로 저장하고 FileIndex는 `indexed`만 조회하는 불일치가 남아 검색 통합이 미완료다. 새 소스의 전용 표시·관계 탐색 검증도 구분하며 Phase 4 전체를 완료 처리하지 않는다.

#### 새 어댑터 작성 규칙

```python
def ingest_새어댑터(projection, rows, options):
    """
    모든 어댑터가 따라야 하는 패턴:

    1. projection.observe() 로 시간축 관찰 등록
       - time_kind 반드시 명시 (모호한 'timestamp' 금지)
       - kind는 어댑터별 고유 문자열

    2. projection.node() / projection.edge() 로 의미 관계 생성
       - edge의 basis에 연결 근거 명시
       - 인과 주장 금지

    3. 원래 행(row)은 records.raw_json에 그대로 보존
       - 필드 재해석 결과는 nodes/edges에만 반영

    4. projection.path() 로 파일 경로 참조 생성
       - windows_path() 정규화 적용
       - 드라이브 매핑 임의 추정 금지

    5. projection.account() 로 계정 참조 생성
       - S-1-0-0, 빈값, '-' 는 무시 (meaningful() 사용)
    """
    for i, row in enumerate(rows):
        obs = projection.observe(
            ordinal=i + 1,
            kind='새_kind_이름',
            time_raw=row['시각필드'],
            time_kind='명확한_시각_의미',
            title=row['요약필드'],
            extra={'adapter_specific': row['고유필드']}
        )
        # 의미 관계 생성
        target = projection.path(row['경로필드'])
        if target:
            projection.edge(obs, target, 'RECORDS_새관계', '근거 설명')
```

### 5.5 Phase 5: 다중 호스트 상관 분석

**목표**: 횡이동(lateral movement) 등 다중 호스트에 걸친 공격 경로를 추적한다.

```
새 노드 라벨:
  NetworkConnection  — 네트워크 연결 (src_ip:port → dst_ip:port)
  Session            — 인증 세션 (호스트 간 로그온 연결)

새 관계 타입:
  NETWORK_TO         — 네트워크 연결 방향
  SESSION_ON         — 세션이 존재하는 호스트
  LATERAL_CANDIDATE  — 횡이동 후보 (확정 아님, basis 명시)
```

### 5.6 AWS 관제·포렌식 자동화 실습 — 로컬 구현·검증, AWS 미배포

AWS 실습 인프라와 Evidence Atlas 연동 작업은 모두 이 evidence-atlas 저장소에서 관리한다. siem-project는 이전 SIEM 실습 저장소이며 새 AWS·포렌식 작업 경로로 사용하지 않는다.

- 상세 설계 파일: [cloud-lab/DESIGN.md](cloud-lab/DESIGN.md).
- 상세 인프라·증거 파이프라인: [cloud-lab/CLOUD_FORENSICS.md](cloud-lab/CLOUD_FORENSICS.md).
- 실제 구축·공격·로그 생성 절차: [cloud-lab/BUILD_AND_ATTACK.md](cloud-lab/BUILD_AND_ATTACK.md). B00~B14 작업과 S0~S6 실험, 산출물·완료 기준을 정의한다.
- 오픈소스 채택·고정 커밋 검토: [cloud-lab/OPEN_SOURCE.md](cloud-lab/OPEN_SOURCE.md).
- 버전·해시·라이선스 기록: cloud-lab/toolchain.lock.json, cloud-lab/artifacts.lock.json, cloud-lab/THIRD_PARTY_NOTICES.md. 파일은 생성되었으며 실제 계정·리전·견적 확인은 배포 전 별도 작업이다.
- 계획 갱신: WordPress/RDS·DMZ·WAF·Suricata IPS·Elastic endpoint·중앙 로그부터 구축한다. DVWA/CloudGoat 실제 공격·SIEM 검증 후 AWS/Linux 증거와 Atlas를 연결한다. OpenTofu·Velociraptor·Sigma 등 OSS를 활용하며 Windows는 후속 선택이다. 구현·배포 완료를 의미하지 않는다.
- 코드·문서 구성: cloud-lab/infra, bootstrap, application, collectors, playbooks, scenarios, scripts, tests, results. 상세 파일 배치는 cloud-lab/DESIGN.md 섹션 12를 따른다. 디렉터리 존재는 예정 기능 전체 완료를 의미하지 않는다.
- Atlas 코어 변경: dfir_graph와 tests에서 구현하며, 새 모듈·어댑터·CLI의 세부 계약은 구현 전에 이 섹션에 추가한다.
- 진행 상황의 출처: 이 저장소 README의 AWS A0~A7 체크리스트.
- 현재 상태: 5.7의 배포 전 코드를 구현하고 로컬 회귀·Linux 서비스 검증을 완료했다. AWS 리소스와 자동화는 아직 배포하지 않았다. Atlas AWS 분석은 검증된 증거 묶음의 초기 오프라인 가져오기에 한정된다.
- 원본·시간 의미·범위 분리·인과 확정 금지·로컬 AI 원칙을 동일하게 적용한다.

---

### 5.7 배포 전 준비 구현 — 2026-09-15

- 설치 파일 증가에 대비해 `infra/foundation/bootstrap_artifacts.tf`, `infra/lab/bootstrap_bundles.tf`, `bootstrap/load_bundle.sh.tpl`로 버전 고정 S3 설정 묶음을 전달한다. EC2 user-data는 16 KiB 미만 로더만 포함하고 S3 VersionId/SHA-256을 검증한다.

- 기본 WAF는 WEB의 ModSecurity v3 + OWASP CRS. AWS WAF는 명시적으로 켜는 비교 옵션이다.
- cloud-lab/bootstrap: WAF, DB/서비스 초기화, Fleet/수집기 설치. application: ModSecurity·DVWA·감사 로그 설정.
- cloud-lab/siem: 정책 생성·원본 보존 파서·탐지 규칙. collectors: 고정 Linux triage 프로필과 원본 AWS 로그 수집.
- cloud-lab/scripts/prepare_deployment.py: 계정 설정 예시·단계별 tfvars/backend와 제한된 신뢰 정책 생성. AWS 호출 없이 실행하고 미확정 값을 배포 입력으로 꾸미지 않는다.
- cloud-lab/scripts: 준비 상태 검사, 버전 고정, Linux 리허설, 증거 반출/검증, 배포·종료 runbook.
- cloud-lab/infra/lab/test_runner.tf: test-a의 선택적 SSM 전용 실행 호스트. scripts/scenario_runner.py는 S0~S3의 제한된 사설망 HTTP 점검과 실행 증적을 담당한다.
- cloud-lab/local: AWS와 격리한 Docker Linux 서비스 검증. 기존 컨테이너·볼륨은 변경하지 않는다.
- dfir_graph/cloud.py: manifest 기반 cloud-import CLI. 파일 해시 검증 후 원본 행·source locator·time_kind를 보존하며 사건/자원/요청의 공유 참조만 생성한다.
- tests/test_cloud.py 및 cloud-lab/tests: 변조·부분 실패·재시도·실제 WAF 통과/차단·파서·서비스 계약 검증.
- 로컬 완료와 AWS 배포 가능 판정을 분리한다. 계정/AMI/견적 입력, AWS 연결·수집·차단은 실측 전 완료 처리하지 않는다.

### 5.8 2026-09-16 시나리오 검토 보완

기존 cloud-lab 구현을 보완한다. 새 파일은 `infra/foundation/scenario_data.tf`(합성 S3 자료), `infra/lab/rds_key.tf`(RDS 전용 키), `scripts/scenario_records.py`(실행 원기록→정답), `scenarios/catalog.json`(36개 준비 조건), `tests/test_scenario_contracts.py`(계약 회귀), `local/rehearse_scenarios.py`(실제 ES/Velociraptor 검사), `results/SCENARIO_REVIEW.md`·`SCENARIO_FIXES.md`(근거·반영)다. 경보는 조사 후보이며 인과를 확정하지 않는다. 미구현 공격·대응 실행기를 준비 완료로 표시하지 않는다.

### 5.9 README와 사용 문서 구성 — 2026-09-16

- `README.md`: 현재 목적·실행 진입점·검증 범위·Atlas Phase 1~5 및 AWS A0~A7 진행 상태의 단일 출처.
- `docs/USAGE.md`: 기존 README의 상세 조회·수집·선택 기능 사용법과 날짜가 명시된 과거 검증 기록을 보존한다. 개인 PC 데이터·서비스는 새 clone에 포함되지 않는다.
- `cloud-lab/README.md`, `cloud-lab/siem/README.md`: AWS와 SIEM의 현재 코드 범위 및 배포 수락 조건을 안내한다. 최신 결과를 먼저 연결하며 과거 검증을 현재 완료로 덮어쓰지 않는다.

## 6. 구현 우선순위와 의존 관계

```
Phase 1: Elasticsearch 동기화·조회          구현 (ES 뷰어 전환은 남음)
    │
    ├──→ Phase 2: 그래프 시각화 ✅ 구현·검증 완료
    │
    ├──→ Phase 3: Sigma 규칙 ✅ 구현·검증 완료
    │
    └──→ Phase 4: 다중 데이터 소스 — 어댑터 추가, 검색·통합 보완 필요
              │
              └──→ Phase 5: 다중 호스트 상관 (미착수)
```

**Phase 1의 동기화·조회 구현**: `es_store.py` + `es_mappings.py` 구현, SQLite→ES 동기화, ECS 필드 매핑, CLI 명령 3종 추가. Kibana에서 데이터 뷰 조회 확인 완료.

**Phase 2 (그래프 시각화)**는 SQLite 백엔드에서 구현·검증했다.

**Phase 3 (Sigma 매칭)**은 `sigma_engine.py`로 구현했다. 1,494개 규칙 로딩, process_creation/ps_script/security 로그소스 지원, 공격 샘플 134건에서 125건 탐지 (39개 고유 규칙).

**Phase 4 (다중 소스)**는 MFT/USN 저장, Sysmon EVTX 4종(EventId 1,3,11,22), SRUM 어댑터와 Sigma 필드 매핑을 추가했다. Sysmon 시간축 fallback은 보완했지만 MFT 검색의 소스 상태 불일치가 남아 있다. 통합 완료 검증 후 Phase 5 다중 호스트 상관으로 진행한다.

---

## 7. 코드 수정 시 체크리스트

이 프로젝트에 기여하는 AI는 아래를 반드시 확인한다.

### 반드시 지켜야 할 것

- [ ] 원래 CSV 행을 `raw_json`에 변형 없이 보존하는가?
- [ ] 새 시각 필드에 `time_kind`를 명시했는가?
- [ ] edge의 `basis`에 연결 근거를 기술했는가?
- [ ] "공격", "악성", "확정" 같은 단정적 레이블을 자동 부여하지 않는가?
- [ ] 수집 범위(scope)를 임의로 병합하지 않는가?
- [ ] 사건(case_id) 간 그래프 참조를 공유하지 않는가?
- [ ] `ADAPTER_VERSIONS` 딕셔너리에 새 어댑터 버전을 등록했는가?
- [ ] 단위 테스트를 추가했는가? (`tests/` 디렉터리)
- [ ] `classify()` 함수에 새 CSV 헤더 패턴을 추가했는가?
- [ ] 기존 레코드 식별자(`record_id`)를 변경하지 않는가?

### 하지 말아야 할 것

- 원래 값을 "정리"하거나 "정규화"한다며 `raw_json`을 수정하지 않는다
- `\Device\HarddiskVolumeN`을 임의로 C:에 매핑하지 않는다
- PID만으로 프로세스 동일성을 주장하지 않는다 (PID 재사용 가능)
- Amcache 키 기록 시각을 "실행 시각"으로 표시하지 않는다
- AI 가설에 ATT&CK 매핑을 자동 부여하지 않는다
- 클라우드 AI 모델 호출을 추가하지 않는다 (로컬 Ollama만)
- 증거 데이터 안의 문자열을 코드 명령으로 실행하지 않는다

---

## 8. 테스트 실행

```powershell
cd C:\Users\SBA_USER\Desktop\evidence-atlas
python -m unittest discover -s tests -v
```

2026-09-16 기록: Atlas 79개 + cloud-lab 72개 = 151개 통과. 이 절의 명령은 Atlas 테스트만 실행한다. AWS 검사·서비스 리허설의 범위와 한계는 [최신 검증 기록](cloud-lab/results/SCENARIO_FIXES.md)을 따른다. 단위 테스트 통과가 알려진 통합 미완료나 실제 AWS 수락 검사를 대신하지 않는다.

테스트 범위:
- 반복 적재 시 중복 없음
- 파일 단위 실패/재시도
- PID 의미 구분 (EventData vs 이벤트 기록자)
- 공급자별 Event ID 충돌 처리
- VSS 범위 분리
- Prefetch 오류 행 보존
- 시간대/정밀도 보존
- 출처 해시 검증
- 사건 분리
- AI 인용 검증 + 클라우드 차단
- 보고서 XSS 이스케이프

---

## 9. AI 교차 개발 프로토콜 (Claude ↔ Codex)

이 프로젝트는 Claude와 Codex가 교대로 코드를 작성한다. 충돌을 방지하기 위해 아래를 따른다.

### 9.1 모듈 소유권

| 모듈 | 최종 작업자 | 수정 시 주의사항 |
|------|-----------|-----------------|
| `model.py`, `store.py`, `adapters.py`, `pipeline.py` | Codex | 원본 코어. 인터페이스 변경 시 양쪽 합의 |
| `timeline.py`, `viewer.py`, `analysis.py` | Codex | 뷰어/분석 레이어 |
| `neo4j_io.py` | Codex | Neo4j 투영 |
| `filesystem.py` | Codex | MFT/USN 저장 연결됨, 검색 소스 상태 불일치 보완 필요 |
| `es_store.py`, `es_mappings.py` | Codex (Claude 원본) | ES 동기화 오류·사건 격리 보완, 2026-09-09 |
| `__main__.py` | 공동 | CLI 진입점. 서브커맨드 추가만, 기존 인터페이스 불변 |
| `static/*` | Codex | 프론트엔드 |
| `DESIGN.md` | 공동 | 양쪽 모두 갱신 가능 |

### 9.2 규칙

1. **상대 AI가 수정한 파일을 건드릴 때**: 먼저 `git diff`로 미커밋 변경 확인
2. **새 파일 생성 전**: 이 문서 섹션 5의 구현 계획에서 해당 파일 위치 확인
3. **공통 인터페이스** (`Store.node()`, `Store.edge()`, `Projection` 등): 시그니처를 바꾸면 양쪽 모두 영향. 추가는 자유, 변경은 DESIGN.md에 기록
4. **커밋 메시지**: `dfir: <한국어 설명>` 형식
5. **브랜치**: `main` (독립 레포의 AGENTS.md와 일치)
6. **CLI 실행**: `evidence-atlas/` 루트에서 실행. Python 패키지는 바로 아래 `dfir_graph/`에 있다.
7. **import 검증**: 새 모듈 작성 후 `python -c "from dfir_graph.모듈명 import 클래스명"` 통과 확인

### 9.3 작업 할당 가이드

| 작업 | 추천 담당 | 이유 |
|------|----------|------|
| Phase 2: 그래프 시각화 | Codex | `static/*` 소유, 기존 `viewer.py`/`timeline.py` 숙지 |
| Phase 3: Sigma 매칭 | Claude | ES 백엔드(`es_store.py`) 위에서 쿼리, pySigma 연동 |
| Phase 4: 다중 소스 어댑터 | Codex | `adapters.py` + `pipeline.py` 소유 |
| `filesystem.py` → pipeline 연결 | Codex | 양쪽 모두 Codex 소유 파일 |
| Kibana 대시보드/시각화 | Claude | ES 데이터 뷰 + 인덱스 구조 숙지 |

---

## 10. 파일 위치 참조

```
프로젝트 루트:     C:\Users\SBA_USER\Desktop\evidence-atlas\
소스 코드:         dfir_graph/
테스트:            tests/
정적 파일:         dfir_graph/static/
데이터:            data/ (.gitignore)
런타임:            .runtime/ (.gitignore)
Neo4j 접속 정보:   .runtime/connection.json (.gitignore)
Cypher 예시:       queries/investigate.cypher
```

---

## 11. 용어 사전

| 용어 | 정의 |
|------|------|
| **Observation** | 시간축 위의 하나의 관찰. CSV 한 행에서 여러 관찰이 나올 수 있다 (Prefetch의 PreviousRun). |
| **Record** | 원래 CSV 행 하나. `raw_json`에 변형 없이 보존. |
| **Projection** | adapters.py의 클래스. store/case/source 컨텍스트를 캡슐화하고 observe/node/edge 메서드를 제공. |
| **time_kind** | 시각의 의미를 나타내는 열거형 문자열. "이 시각이 무엇을 의미하는가"를 기록. |
| **scope** | 수집 범위. C 드라이브 또는 VSS0, VSS1 등. |
| **basis** | edge가 왜 만들어졌는지의 근거. 인과 주장이 아닌 공유 참조 사실. |
| **lane** | 시간축 UI의 행. 관찰 kind에 따라 7개 lane으로 분류. |
| **KAPE** | Kroll Artifact Parser and Extractor. Windows 포렌식 아티팩트 수집/파싱 도구. |
| **ECS** | Elastic Common Schema. Elasticsearch의 표준 필드 명명 규칙. |
| **CIM** | Common Information Model. Splunk의 표준 필드 명명 규칙. |
| **Sigma** | 로그 기반 탐지 규칙의 오픈 표준 형식. |
| **DFKG** | Digital Forensic Knowledge Graph. 포렌식 증거의 지식 그래프 모델링 개념. |

---

## 12. 개발 환경 기록 (2026-09-09 당시)

이 절의 실행 서비스·모델·디스크 용량·데이터 수치는 당시 개발 PC 기록이다. 새 clone의 제공 데이터나 현재 실행 상태가 아니며, AWS SOC의 버전은 `cloud-lab/artifacts.lock.json`과 `cloud-lab/DEPLOYMENT.md`를 따른다.

### 12.1 인프라 서비스

| 서비스 | 버전 | 접속 | 시작/중지 |
|--------|------|------|----------|
| Elasticsearch | 8.17.0 | http://127.0.0.1:9200 | `docker compose -f docker-compose.yml up -d` / `down` |
| Kibana | 8.17.0 | http://127.0.0.1:5601 | 위와 동일 (같은 compose) |
| Neo4j Community | 5.26.30 | http://127.0.0.1:17474 / bolt://127.0.0.1:17687 | `./run.ps1 -WithNeo4j` |
| Ollama | 0.33.3 | http://127.0.0.1:11434 | 시스템 트레이에서 자동 실행 |
| Evidence Atlas 뷰어 | 0.2.0 | http://127.0.0.1:8771 (SBA), :8769 (공격 샘플) | `./run.ps1 -Port 8771` |

### 12.2 Docker Compose 설정 (`docker-compose.yml`)

- **ES**: single-node, 보안 비활성화 (로컬 개발), JVM 힙 512MB, 메모리 1GB 제한
- **Kibana**: ES 연결, Node 힙 512MB, 메모리 768MB 제한
- **클러스터 이름**: `evidence-atlas`
- **볼륨**: `es-data` (Docker managed volume)
- 모든 포트는 `127.0.0.1`에만 바인딩 (외부 접속 차단)

### 12.3 Python 의존성

```
neo4j>=5.26,<6          — Neo4j 투영용
elasticsearch>=8.0,<9   — ES 백엔드용 (Phase 1)
pySigma>=0.11           — Sigma 규칙 매칭용 (Phase 3)
```

### 12.4 Sigma 규칙

- **위치**: `vendor/sigma/` (SigmaHQ/sigma shallow clone, .gitignore 제외)
- **규칙 수**: 3,144개 YAML 파일
- **Windows 프로세스 생성**: `vendor/sigma/rules/windows/process_creation/`
- **갱신**: `git -C vendor/sigma pull --ff-only`

### 12.5 로컬 AI 모델

| 모델 | 파라미터 | 크기 | 용도 |
|------|---------|------|------|
| qwen2.5:7b | 7.6B | 4.7GB | 한국어 포렌식 가설 생성 (analysis.py) |

Evidence Atlas에서 사용: `run.ps1 -AIModel 'qwen2.5:7b'` 또는 CLI `analyze --model qwen2.5:7b`

### 12.6 하드웨어 제약

| 항목 | 사양 | 비고 |
|------|------|------|
| CPU | Intel i7-12700 (12세대) | — |
| RAM | 16GB | ES+Kibana+Neo4j+Ollama 동시 실행 시 빡빡함 |
| GPU | GTX 1650 (4GB VRAM) | Ollama 7B 모델까지 GPU 가속 가능 |
| 디스크 | C: 76GB 여유 / D: 714GB 여유 | 대용량 데이터는 D: 활용 권장 |
| OS | Windows 11 Pro | WSL2 활성화 완료 |

### 12.7 세팅 스크립트

전체 환경을 한번에 세팅하는 스크립트:

```powershell
cd C:\Users\SBA_USER\Desktop\evidence-atlas
.\scripts\setup_expansion.ps1           # 전체 세팅
.\scripts\setup_expansion.ps1 -SkipDocker  # Docker 제외
```

### 12.8 구현 상태

| 파일 | 상태 | 설명 |
|------|------|------|
| `dfir_graph/es_store.py` | **✅ 완료** | ESStore 클래스 — SQLite→ES 동기화, 동일 read API, ES 전용 쿼리 |
| `dfir_graph/es_mappings.py` | **✅ 완료** | 5개 인덱스 매핑 + ECS 변환 (`record_to_ecs`) |
| `dfir_graph/__main__.py` | **✅ 수정** | `es-sync`, `es-status`, `es-search`, `sigma-scan`, `sigma-stats`, `sigma-list` CLI 명령 추가 |
| `dfir_graph/sigma_engine.py` | **✅ 완료** | Sigma YAML 로딩 + 필드 매핑 + 조건 평가 + SQLite 매칭 (Phase 3) |
| `dfir_graph/static/graph.js` | **✅ 완료** | 로컬 Cytoscape 관계 지도·근거·시간축 이동 (Phase 2) |
| `dfir_graph/filesystem.py` | **부분 통합** | pipeline 저장 연결됨, 검색의 complete/indexed 상태 불일치 보완 필요 |

### 12.9 ES 인덱스 현황 (2026-09-09 동기화 완료)

| 인덱스 | 문서 수 | 용도 |
|--------|---------|------|
| `ea-records-evtx-attack-samples` | 37,357 | 원본 레코드 + ECS 필드 (`@timestamp`, `event.*`, `process.*`, `user.*`, `ea.*`) |
| `ea-nodes-evtx-attack-samples` | 325 | 그래프 노드 |
| `ea-edges-evtx-attack-samples` | 736 | 그래프 관계 |
| `ea-sources-evtx-attack-samples` | 1 | 파일 출처 메타데이터 |
| `ea-issues-evtx-attack-samples` | 84 | 파싱 경고 |

위 표는 보존한 구 인덱스다. 동일한 문서 수의 SHA-256 접미사 인덱스로 재동기화했다. Kibana 데이터 뷰 "Evidence Atlas Records"는 `ea-current-records` 별칭, 시각 필드는 `@timestamp`로 검증했다. 데이터 뷰 ID와 표시 이름은 유지했다.

### 12.10 ES CLI 사용법

**실행 위치**: 독립 저장소 `evidence-atlas/` 루트. Python 패키지는 `dfir_graph/`이다.

```powershell
# 독립 저장소로 이동
cd C:\Users\SBA_USER\Desktop\evidence-atlas

# SQLite → ES 동기화 (전체 case)
python -m dfir_graph --db data/attack-samples.sqlite es-sync

# 특정 case만 동기화 (기존 인덱스 삭제 후 재생성)
python -m dfir_graph --db data/attack-samples.sqlite es-sync --case EVTX-ATTACK-SAMPLES --drop

# ES 연결 및 인덱스 상태 확인
python -m dfir_graph --db data/attack-samples.sqlite es-status --case EVTX-ATTACK-SAMPLES

# ES 전문 검색
python -m dfir_graph --db data/attack-samples.sqlite es-search "powershell" --case EVTX-ATTACK-SAMPLES
```
