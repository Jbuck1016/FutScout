param(
    [string]$AsOf,
    [string]$Season = "2627",
    [int]$ModelRunId = 4,
    [string]$Artifact = "artifacts\models\v2-field-tilt-box-entries-poisson-2324-2425-2526-20260914t205131z.pkl",
    [string]$Python = "$env:USERPROFILE\anaconda3\python.exe",
    [int]$Simulations = 10000,
    [switch]$Execute,
    [switch]$PublishSite,
    [switch]$SkipDashboard
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$operationLog = Join-Path $logDir ("shadow_weekly_" + [DateTimeOffset]::UtcNow.ToString("yyyyMMdd") + ".log")
Start-Transcript -Path $operationLog -Append | Out-Null
$forecastKind = "thursday_frozen"
if ($SkipDashboard -and $PublishSite) { throw "-SkipDashboard cannot be combined with -PublishSite" }
$leagues = @(
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1"
)

Push-Location $repoRoot
try {
    $pythonExe = (Resolve-Path -LiteralPath $Python).Path
    if (-not $AsOf) {
        $now = [DateTimeOffset]::UtcNow
        $daysSinceThursday = (([int]$now.DayOfWeek - [int][DayOfWeek]::Thursday) + 7) % 7
        # DateTimeOffset.Date returns DateTime; keep both sides of the
        # comparison explicitly UTC DateTimeOffset values.
        $utcNoon = [DateTimeOffset]::new($now.UtcDateTime.Date.AddHours(12))
        $thursday = $utcNoon.AddDays(-$daysSinceThursday)
        if ($thursday -gt $now) { $thursday = $thursday.AddDays(-7) }
        $AsOf = ([DateTimeOffset]$thursday).ToString("yyyy-MM-ddTHH:mm:ssZ")
    }
    $parsedAsOf = [DateTimeOffset]::Parse($AsOf).ToUniversalTime()
    if ($parsedAsOf.DayOfWeek -ne [DayOfWeek]::Thursday) {
        throw "A frozen weekly shadow snapshot must use a real Thursday as-of instant"
    }
    if ($parsedAsOf -gt [DateTimeOffset]::UtcNow.AddMinutes(5)) {
        throw "Refusing to backfill a future frozen snapshot; run at or after its real as-of instant"
    }
    $freezeDelay = [DateTimeOffset]::UtcNow - $parsedAsOf
    if ($freezeDelay.TotalMinutes -lt 0 -or $freezeDelay.TotalMinutes -gt 30) {
        throw "Thursday-frozen forecasts must actually run within 30 minutes of their cutoff; retrospective runs must not masquerade as frozen"
    }
    $asOfUtc = $parsedAsOf.ToString("yyyy-MM-ddTHH:mm:ssZ")
    $stamp = $parsedAsOf.ToString("yyyyMMddTHHmmssZ")
    $artifactPath = (Resolve-Path -LiteralPath $Artifact).Path
    $artifactMeta = Get-Content -LiteralPath ([System.IO.Path]::ChangeExtension($artifactPath, ".json")) -Raw | ConvertFrom-Json
    $fixturePath = Join-Path $repoRoot "artifacts\fixtures\${Season}_football_data.json"
    $immutableFixturePath = Join-Path $repoRoot "artifacts\fixtures\${Season}_football_data_${stamp}.json"
    $predictionPath = Join-Path $repoRoot "artifacts\predictions\${Season}_${forecastKind}_${stamp}.json"
    $readinessPath = Join-Path $repoRoot "artifacts\data_quality\forecast_readiness_${Season}_${forecastKind}_${stamp}.json"
    $driftPath = Join-Path $repoRoot "artifacts\data_quality\model_feature_drift_${Season}.json"
    $driftReviewPath = Join-Path $repoRoot "pipeline\reviewed_model_feature_drift_policy_v2.json"
    $scorePath = Join-Path $repoRoot "artifacts\model_reports\shadow_history_${Season}.json"
    $tournamentPath = Join-Path $repoRoot "artifacts\predictions\research\${Season}_${stamp}_tournament.json"
    $tournamentAuditPath = Join-Path $repoRoot "artifacts\data_quality\shadow_tournament_${Season}_${stamp}.json"

    & $pythonExe pipeline\sync_future_fixtures.py --season $Season --output $fixturePath --execute
    if ($LASTEXITCODE -ne 0) { throw "fixture sync failed" }
    $evaluationThrough = $parsedAsOf.AddDays(7)
    $fixtureManifest = Get-Content -LiteralPath $fixturePath -Raw | ConvertFrom-Json
    $evaluationFixtures = @($fixtureManifest.fixtures | Where-Object {
        $kickoff = [DateTimeOffset]::Parse([string]$_.kickoff_at).ToUniversalTime()
        $kickoff -gt $parsedAsOf -and $kickoff -le $evaluationThrough
    })
    if ($evaluationFixtures.Count -eq 0) {
        Write-Host ("No top-five fixtures fall inside the seven-day scoring horizon " +
            "({0} through {1}); treating this Thursday as a successful no-op." -f `
            $parsedAsOf.ToString("yyyy-MM-dd"), $evaluationThrough.ToString("yyyy-MM-dd"))
        Write-Host "No immutable prediction slate was created, persisted, published, or counted."
        return
    }
    if (Test-Path -LiteralPath $predictionPath) {
        $existingPrediction = Get-Content -LiteralPath $predictionPath -Raw | ConvertFrom-Json
        $forecastFixturePath = if ($existingPrediction.fixture_manifest) {
            [string]$existingPrediction.fixture_manifest
        } else {
            $fixturePath
        }
    } else {
        if (-not (Test-Path -LiteralPath $immutableFixturePath)) {
            Copy-Item -LiteralPath $fixturePath -Destination $immutableFixturePath
        }
        $forecastFixturePath = $immutableFixturePath
    }
    & $pythonExe pipeline\archive_history.py --season $Season --execute
    if ($LASTEXITCODE -ne 0) { throw "current match archive failed" }
    & $pythonExe pipeline\build_ml_features.py --season $Season `
        --observation-schema-version 2 --feature-schema-version 2 `
        --defer-unverified-results --execute
    if ($LASTEXITCODE -ne 0) { throw "current model feature refresh failed" }
    & $pythonExe pipeline\audit_live_ingestion.py --strict
    if ($LASTEXITCODE -ne 0) { throw "live ingestion coverage audit failed" }
    & $pythonExe pipeline\audit_model_feature_drift.py `
        --current-season $Season --artifact $artifactPath --output $driftPath
    if ($LASTEXITCODE -ne 0) { throw "feature drift audit failed" }

    $drift = Get-Content -LiteralPath $driftPath -Raw | ConvertFrom-Json
    if ($drift.decision -eq "block_and_investigate") {
        if (-not (Test-Path -LiteralPath $driftReviewPath)) {
            throw "feature drift is blocked and no reviewed exception exists"
        }
        $review = Get-Content -LiteralPath $driftReviewPath -Raw | ConvertFrom-Json
        $allowed = @($review.allowed_severe_features)
        $unexpected = @($drift.severe_features | Where-Object { $_ -notin $allowed })
        $unsafeSevere = @($drift.severe_features | Where-Object {
            $metric = $drift.features.$_
            $limit = if ($_ -like "elo_*") {
                [double]$review.maximum_absolute_standardized_mean_shift.elo
            } else {
                [double]$review.maximum_absolute_standardized_mean_shift.calendar
            }
            [Math]::Abs([double]$metric.standardized_mean_shift) -gt $limit -or
            [Math]::Abs([double]$metric.missing_rate_change) -gt [double]$review.maximum_absolute_missing_rate_change
        })
        if ($review.review_decision -ne "approved_for_shadow_with_monitoring" -or
            $review.scope -ne "private_shadow_only" -or $unexpected.Count -gt 0 -or $unsafeSevere.Count -gt 0) {
            throw "feature drift requires a new human review before shadow persistence"
        }
        Write-Host "Accepted reviewed calendar/Elo drift policy for private shadow monitoring"
    }

    if (Test-Path -LiteralPath $predictionPath) {
        $existing = Get-Content -LiteralPath $predictionPath -Raw | ConvertFrom-Json
        if ($existing.as_of -ne $parsedAsOf.ToString("yyyy-MM-ddTHH:mm:ss+00:00") -or
            $existing.model_version -ne $artifactMeta.model_version -or
            $existing.forecast_kind -ne $forecastKind) {
            throw "existing immutable snapshot identity does not match the requested run"
        }
        Write-Host "Reusing immutable frozen snapshot: $predictionPath"
    } else {
        & $pythonExe pipeline\freeze_shadow_tournament.py `
            --primary-artifact $artifactPath --season $Season --as-of $asOfUtc `
            --fixtures-file $forecastFixturePath --prediction-output $predictionPath
        if ($LASTEXITCODE -ne 0) { throw "complete same-cutoff tournament freeze failed" }
    }
    if (-not (Test-Path -LiteralPath $tournamentPath)) {
        throw "frozen primary snapshot exists without a same-cutoff tournament manifest"
    }
    & $pythonExe pipeline\audit_frozen_tournament.py `
        --tournament $tournamentPath --output $tournamentAuditPath
    if ($LASTEXITCODE -ne 0) { throw "frozen tournament integrity and point-in-time audit failed" }

    foreach ($league in $leagues) {
        & $pythonExe pipeline\run_league_simulation.py `
            --model-run-id $ModelRunId --predictions-file $predictionPath `
            --league $league --season $Season --as-of $asOfUtc `
            --forecast-kind $forecastKind --simulations $Simulations
        if ($LASTEXITCODE -ne 0) { throw "local simulation failed for $league" }
    }
    & $pythonExe pipeline\audit_forecast_readiness.py `
        --predictions-file $predictionPath --simulations-dir artifacts\simulations --output $readinessPath
    if ($LASTEXITCODE -ne 0) { throw "forecast readiness audit failed" }
    $readiness = Get-Content -LiteralPath $readinessPath -Raw | ConvertFrom-Json
    if (-not $readiness.ready_for_private_review -or -not $readiness.ready_for_persistence) {
        throw "forecast bundle did not pass private persistence readiness"
    }
    if (-not $SkipDashboard) {
        & $pythonExe pipeline\build_model_review_dashboard.py `
            --predictions-file $predictionPath --readiness-report $readinessPath `
            --output dashboard\model-review-data.js
        if ($LASTEXITCODE -ne 0) { throw "local model review page failed" }
    }

    if ($Execute) {
        & $pythonExe pipeline\generate_match_predictions.py `
            --artifact $artifactPath --model-run-id $ModelRunId --season $Season --as-of $asOfUtc `
            --forecast-kind $forecastKind --fixtures-file $forecastFixturePath --output $predictionPath --reuse-output --execute
        if ($LASTEXITCODE -ne 0) { throw "private frozen prediction persistence failed" }
        foreach ($league in $leagues) {
            & $pythonExe pipeline\run_league_simulation.py `
                --model-run-id $ModelRunId --predictions-file $predictionPath `
                --league $league --season $Season --as-of $asOfUtc `
                --forecast-kind $forecastKind --simulations $Simulations --execute
            if ($LASTEXITCODE -ne 0) { throw "private simulation persistence failed for $league" }
        }
    }

    $frozenFiles = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "artifacts\predictions") `
        -Filter "${Season}_${forecastKind}_*.json" -File | Sort-Object Name)
    if ($frozenFiles.Count -gt 0) {
        $scoreArgs = @("pipeline\score_prediction_history.py")
        foreach ($file in $frozenFiles) {
            $scoreArgs += @("--predictions-file", $file.FullName)
        }
        $scoreArgs += @("--output", $scorePath)
        & $pythonExe @scoreArgs
        if ($LASTEXITCODE -ne 0) { throw "shadow history scoring failed" }
    }

    if (-not $SkipDashboard) {
        & $pythonExe pipeline\build_model_lab_dashboard.py `
            --artifact $artifactPath --predictions-file $predictionPath --drift-report $driftPath `
            --shadow-report $scorePath --output dashboard\model-lab-data.js
        if ($LASTEXITCODE -ne 0) { throw "model lab bundle failed" }
    }

    if ($PublishSite) {
        & $pythonExe pipeline\publish_dashboard_data.py --file dashboard/model-review-data.js --file dashboard/model-lab-data.js --message "Refresh weekly shadow forecasts $stamp" --execute
        if ($LASTEXITCODE -ne 0) { throw "isolated dashboard publication failed" }
    }

    Write-Host "Weekly shadow cycle complete: $predictionPath"
    Write-Host "Persistence enabled: $($Execute.IsPresent)"
    Write-Host "Site publication enabled: $($PublishSite.IsPresent)"
} catch {
    Write-Error ("Weekly shadow cycle failed: " + ($_ | Out-String))
    throw
} finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
