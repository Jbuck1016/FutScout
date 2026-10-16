param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'weekly_scrape.bat'
$task = Get-ScheduledTask -TaskName 'MLS-Euro Analytics Scrape'
if ($task.State -eq 'Running') { throw 'Wait for the current scrape to finish.' }
if (-not (Test-Path -LiteralPath $script)) { throw 'Backend scrape entry point is missing.' }
Write-Host "Current action: $($task.Actions.Execute)"
Write-Host "Proposed action: $script"
if (-not $Execute) { Write-Host 'Dry run. Use -Execute from an administrator PowerShell.'; exit 0 }
$backupDirectory = Join-Path $repoRoot 'artifacts\pipeline_audit_20261012'
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$backupPath = Join-Path $backupDirectory 'nightly-task-before.xml'
if (-not (Test-Path -LiteralPath $backupPath)) {
    $saved = [xml](Export-ScheduledTask -TaskName $task.TaskName)
    $saved.Save($backupPath)
}
$action = New-ScheduledTaskAction -Execute $script -WorkingDirectory $repoRoot
Set-ScheduledTask -TaskName $task.TaskName -Action $action | Out-Null
$actual = (Get-ScheduledTask -TaskName $task.TaskName).Actions
if ($actual.Execute -ne $script -or $actual.WorkingDirectory -ne $repoRoot) {
    throw 'Task action verification failed.'
}
Write-Host 'Verified: nightly task now uses the repaired backend. Timing and principal unchanged.'
