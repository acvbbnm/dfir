param(
    [string]$Database = 'data/sba.sqlite',
    [int]$Port = 8765,
    [switch]$WithNeo4j,
    [string]$AIModel,
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not $PythonPath) {
        $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $bundled) { $PythonPath = $bundled }
        else { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
    }
    if (-not (Test-Path -LiteralPath $Database -PathType Leaf)) {
        throw 'Import evidence first. See README.md for the ingest command.'
    }
    if ($WithNeo4j) {
        & $PythonPath scripts/setup_runtime.py --start
        if ($LASTEXITCODE -ne 0) { throw 'Neo4j startup failed.' }
    }
    Write-Host "Viewer: http://127.0.0.1:$Port (Ctrl+C stops the viewer)"
    $viewerArguments = @('-m', 'dfir_graph', '--db', $Database, 'serve', '--port', $Port)
    if ($AIModel) { $viewerArguments += @('--ai-model', $AIModel) }
    & $PythonPath @viewerArguments
    if ($LASTEXITCODE -ne 0) { throw 'Viewer stopped with an error.' }
}
finally { Pop-Location }
