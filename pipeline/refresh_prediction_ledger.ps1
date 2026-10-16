param(
    [string]$Season = "2627",
    [string]$Python = "$env:USERPROFILE\anaconda3\python.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$operationLog = Join-Path $logDir ("prediction_ledger_" + [DateTimeOffset]::UtcNow.ToString("yyyyMMdd") + ".log")
Start-Transcript -Path $operationLog -Append | Out-Null

Push-Location $repoRoot
try {
    $pythonExe = (Resolve-Path -LiteralPath $Python).Path
    & $pythonExe pipeline\score_prediction_ledger.py `
        --season $Season --output "artifacts\model_reports\prediction_ledger_${Season}.json"
    if ($LASTEXITCODE -ne 0) { throw "prediction ledger scoring failed" }
    & $pythonExe pipeline\score_shadow_tournament.py `
        --season $Season --output "artifacts\model_reports\shadow_tournament_scorecard_${Season}.json"
    if ($LASTEXITCODE -ne 0) { throw "same-cutoff challenger scorecard failed" }
    Write-Host "Daily prediction ledger refresh complete"
} catch {
    Write-Error ("Daily prediction ledger refresh failed: " + ($_ | Out-String))
    throw
} finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
