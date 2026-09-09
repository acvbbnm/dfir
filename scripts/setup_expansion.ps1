<#
.SYNOPSIS
    Evidence Atlas 확장 환경 사전 세팅 스크립트
.DESCRIPTION
    1. Docker Desktop 실행 확인
    2. Elasticsearch + Kibana 컨테이너 시작
    3. Python 패키지 설치 (elasticsearch, pySigma)
    4. Sigma 규칙 저장소 클론
    5. Ollama 설치 안내
#>

param(
    [switch]$SkipDocker,
    [switch]$SkipPython,
    [switch]$SkipSigma,
    [switch]$SkipOllama,
    [string]$PythonPath = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "`n=== Evidence Atlas 확장 환경 세팅 ===" -ForegroundColor Cyan
Write-Host "프로젝트: $ProjectRoot`n"

# ── 1. Docker + Elasticsearch + Kibana ──
if (-not $SkipDocker) {
    Write-Host "[1/4] Docker + Elasticsearch + Kibana" -ForegroundColor Yellow

    $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerCmd) {
        Write-Host "  Docker Desktop이 설치되어 있지 않습니다." -ForegroundColor Red
        Write-Host "  https://www.docker.com/products/docker-desktop/ 에서 설치하세요." -ForegroundColor Red
        exit 1
    }

    # Docker Desktop 실행 확인
    $dockerRunning = $false
    try {
        $null = docker info 2>&1
        if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
    } catch {}

    if (-not $dockerRunning) {
        Write-Host "  Docker Desktop을 시작합니다..." -ForegroundColor Gray
        Start-Process "Docker Desktop" -ErrorAction SilentlyContinue
        Write-Host "  Docker 엔진이 준비될 때까지 대기합니다 (최대 90초)..." -ForegroundColor Gray
        $waited = 0
        while ($waited -lt 90) {
            Start-Sleep -Seconds 5
            $waited += 5
            try {
                $null = docker info 2>&1
                if ($LASTEXITCODE -eq 0) { $dockerRunning = $true; break }
            } catch {}
            Write-Host "  ... $waited 초 경과" -ForegroundColor DarkGray
        }
        if (-not $dockerRunning) {
            Write-Host "  Docker 엔진이 시작되지 않았습니다. Docker Desktop을 수동으로 실행한 뒤 다시 시도하세요." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  Docker 엔진 정상" -ForegroundColor Green

    # docker-compose up
    $composeFile = Join-Path $ProjectRoot "docker-compose.yml"
    if (-not (Test-Path $composeFile)) {
        Write-Host "  docker-compose.yml이 없습니다: $composeFile" -ForegroundColor Red
        exit 1
    }

    Write-Host "  Elasticsearch + Kibana 이미지를 가져오고 시작합니다..." -ForegroundColor Gray
    Write-Host "  (첫 실행 시 이미지 다운로드로 5~10분 소요)" -ForegroundColor DarkGray
    docker compose -f $composeFile up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  docker compose up 실패" -ForegroundColor Red
        exit 1
    }

    # ES 헬스체크 대기
    Write-Host "  Elasticsearch 초기화 대기 중..." -ForegroundColor Gray
    $esReady = $false
    $waited = 0
    while ($waited -lt 120) {
        Start-Sleep -Seconds 5
        $waited += 5
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:9200/_cluster/health" -TimeoutSec 3 -ErrorAction Stop
            if ($response.status -in @("green", "yellow")) {
                $esReady = $true
                break
            }
        } catch {}
        Write-Host "  ... $waited 초 경과" -ForegroundColor DarkGray
    }

    if ($esReady) {
        Write-Host "  Elasticsearch 정상 (http://127.0.0.1:9200)" -ForegroundColor Green
        Write-Host "  Kibana: http://127.0.0.1:5601 (초기화에 1~2분 추가 소요)" -ForegroundColor Green
    } else {
        Write-Host "  Elasticsearch가 아직 준비되지 않았습니다. 'docker logs ea-elasticsearch'로 확인하세요." -ForegroundColor Red
    }
} else {
    Write-Host "[1/4] Docker — 건너뜀" -ForegroundColor DarkGray
}

# ── 2. Python 패키지 ──
if (-not $SkipPython) {
    Write-Host "`n[2/4] Python 패키지 설치" -ForegroundColor Yellow

    $packages = @(
        "elasticsearch>=8.0,<9",
        "pySigma>=0.11"
    )

    foreach ($pkg in $packages) {
        Write-Host "  설치: $pkg" -ForegroundColor Gray
        & $PythonPath -m pip install $pkg --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  $pkg 설치 실패" -ForegroundColor Red
        }
    }

    Write-Host "  설치 확인:" -ForegroundColor Gray
    & $PythonPath -m pip show elasticsearch 2>&1 | Select-String "^(Name|Version)"
    & $PythonPath -m pip show pySigma 2>&1 | Select-String "^(Name|Version)"
    Write-Host "  Python 패키지 완료" -ForegroundColor Green
} else {
    Write-Host "`n[2/4] Python 패키지 — 건너뜀" -ForegroundColor DarkGray
}

# ── 3. Sigma 규칙 저장소 ──
if (-not $SkipSigma) {
    Write-Host "`n[3/4] Sigma 규칙 저장소" -ForegroundColor Yellow

    $sigmaDir = Join-Path $ProjectRoot "vendor" "sigma"
    if (Test-Path (Join-Path $sigmaDir ".git")) {
        Write-Host "  이미 클론됨: $sigmaDir" -ForegroundColor Gray
        Write-Host "  최신으로 갱신합니다..." -ForegroundColor Gray
        git -C $sigmaDir pull --ff-only 2>&1 | Select-Object -First 3
    } else {
        Write-Host "  SigmaHQ/sigma 클론 중... (약 1~3분)" -ForegroundColor Gray
        $vendorDir = Join-Path $ProjectRoot "vendor"
        if (-not (Test-Path $vendorDir)) { New-Item -ItemType Directory -Path $vendorDir -Force | Out-Null }
        git clone --depth 1 https://github.com/SigmaHQ/sigma.git $sigmaDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Sigma 클론 실패" -ForegroundColor Red
        }
    }

    if (Test-Path $sigmaDir) {
        $ruleCount = (Get-ChildItem -Path $sigmaDir -Filter "*.yml" -Recurse | Measure-Object).Count
        Write-Host "  Sigma 규칙 $ruleCount 개 사용 가능" -ForegroundColor Green
        Write-Host "  Windows 프로세스 생성 규칙: $(Join-Path $sigmaDir 'rules' 'windows' 'process_creation')" -ForegroundColor Gray
    }
} else {
    Write-Host "`n[3/4] Sigma 규칙 — 건너뜀" -ForegroundColor DarkGray
}

# ── 4. Ollama ──
if (-not $SkipOllama) {
    Write-Host "`n[4/4] Ollama (로컬 AI)" -ForegroundColor Yellow

    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCmd) {
        Write-Host "  Ollama 이미 설치됨: $($ollamaCmd.Source)" -ForegroundColor Green
        try {
            $models = ollama list 2>&1
            Write-Host "  설치된 모델:" -ForegroundColor Gray
            $models | Select-Object -First 10
        } catch {
            Write-Host "  Ollama가 실행 중이 아닙니다. 'ollama serve'로 시작하세요." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Ollama가 설치되어 있지 않습니다." -ForegroundColor Yellow
        Write-Host "  아래에서 Windows 설치 파일을 다운로드하세요:" -ForegroundColor Gray
        Write-Host "  https://ollama.com/download/windows" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  설치 후 실행할 명령:" -ForegroundColor Gray
        Write-Host "    ollama pull phi4-mini          # 경량 모델 (3.8B, ~2.5GB)" -ForegroundColor White
        Write-Host "    ollama pull llama3.2:3b         # 대안 경량 모델 (3B, ~2GB)" -ForegroundColor White
        Write-Host ""
        Write-Host "  Evidence Atlas에서 사용:" -ForegroundColor Gray
        Write-Host "    .\run.ps1 -AIModel 'phi4-mini'" -ForegroundColor White
    }
} else {
    Write-Host "`n[4/4] Ollama — 건너뜀" -ForegroundColor DarkGray
}

# ── 결과 요약 ──
Write-Host "`n=== 세팅 요약 ===" -ForegroundColor Cyan

$summary = @()
if (-not $SkipDocker) {
    try {
        $esInfo = Invoke-RestMethod -Uri "http://127.0.0.1:9200" -TimeoutSec 3 -ErrorAction Stop
        $summary += "  Elasticsearch $($esInfo.version.number) — http://127.0.0.1:9200"
    } catch {
        $summary += "  Elasticsearch — 시작 중 또는 실패"
    }
    $summary += "  Kibana — http://127.0.0.1:5601"
}

try {
    $esVer = & $PythonPath -c "import elasticsearch; print(elasticsearch.__version__)" 2>&1
    $summary += "  elasticsearch-py $esVer"
} catch {}

try {
    $sigmaVer = & $PythonPath -c "import sigma; print(sigma.__version__)" 2>&1
    $summary += "  pySigma $sigmaVer"
} catch {}

$sigmaDir = Join-Path $ProjectRoot "vendor" "sigma"
if (Test-Path $sigmaDir) {
    $summary += "  Sigma 규칙: $sigmaDir"
}

$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) {
    $summary += "  Ollama: 설치됨"
} else {
    $summary += "  Ollama: 수동 설치 필요 (https://ollama.com/download/windows)"
}

$summary | ForEach-Object { Write-Host $_ -ForegroundColor White }

Write-Host "`n컨테이너 관리:" -ForegroundColor Gray
Write-Host "  시작: docker compose -f $(Join-Path $ProjectRoot 'docker-compose.yml') up -d" -ForegroundColor White
Write-Host "  중지: docker compose -f $(Join-Path $ProjectRoot 'docker-compose.yml') down" -ForegroundColor White
Write-Host "  로그: docker logs ea-elasticsearch" -ForegroundColor White
Write-Host ""
