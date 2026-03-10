# Deploy Intl 40-ETF Composite Risk algorithm to QuantConnect and start backtest (no Python required)
# Uses your QuantConnect API credentials; run from Potomac folder.

$ErrorActionPreference = "Stop"
$BASE_URL = "https://www.quantconnect.com/api/v2"
$USER_ID = 470149
$API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
$SCRIPT_DIR = $PSScriptRoot
if (-not $SCRIPT_DIR) { $SCRIPT_DIR = Get-Location.Path }

function Get-QCHeaders {
    $ts = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $toHash = "${API_TOKEN}:${ts}"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($toHash)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    $hashHex = [BitConverter]::ToString($hash).Replace("-","").ToLowerInvariant()
    $toEncode = "${USER_ID}:${hashHex}"
    $authBytes = [System.Text.Encoding]::UTF8.GetBytes($toEncode)
    $auth = [Convert]::ToBase64String($authBytes)
    return @{
        "Authorization" = "Basic $auth"
        "Timestamp"     = $ts.ToString()
        "Content-Type"  = "application/json"
    }
}

function Invoke-QCApi {
    param([string]$Endpoint, [object]$Body = $null)
    $uri = "$BASE_URL$Endpoint"
    $headers = Get-QCHeaders
    $bodyJson = if ($Body) { $Body | ConvertTo-Json -Depth 100 -Compress } else { "{}" }
    try {
        $r = Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $bodyJson -ContentType "application/json"
    } catch {
        Write-Host "API error: $($_.Exception.Message)"
        if ($_.Exception.Response) {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            Write-Host $reader.ReadToEnd()
        }
        throw
    }
    if (-not $r.success) {
        Write-Host "API returned success=false: $($r | ConvertTo-Json -Depth 5)"
        throw "QuantConnect API error"
    }
    return $r
}

Write-Host "========================================"
Write-Host "  QuantConnect: Create Composite Backtest"
Write-Host "========================================"

$algoPath = Join-Path $SCRIPT_DIR "QuantConnect_Intl40_CompositeRisk_main.py"
if (-not (Test-Path $algoPath)) {
    Write-Host "ERROR: Algorithm file not found: $algoPath"
    exit 1
}
$algoContent = Get-Content -Path $algoPath -Raw -Encoding UTF8

# 1. Create project
Write-Host "`n1. Creating project..."
$projectName = "Intl40_CompositeRisk_" + [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$r = Invoke-QCApi -Endpoint "/projects/create" -Body @{ name = $projectName; language = "Py" }
$projectId = $r.projects[0].projectId
Write-Host "   Project ID: $projectId"

# 2. Upload main.py (content must be JSON-escaped; use raw object for ConvertTo-Json)
Write-Host "2. Uploading main.py..."
$fileBody = @{ projectId = $projectId; name = "main.py"; content = $algoContent }
$r = Invoke-QCApi -Endpoint "/files/create" -Body $fileBody
if (-not $r.success) {
    $r = Invoke-QCApi -Endpoint "/files/update" -Body $fileBody
}
Write-Host "   Uploaded."

# 3. Compile
Write-Host "3. Compiling..."
$r = Invoke-QCApi -Endpoint "/compile/create" -Body @{ projectId = $projectId }
$compileId = $r.compileId
$compiled = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 3
    $r = Invoke-QCApi -Endpoint "/compile/read" -Body @{ projectId = $projectId; compileId = $compileId }
    $state = $r.state
    if ($state -eq "BuildSuccess") {
        Write-Host "   Compiled OK!"
        $compiled = $true
        break
    }
    if ($state -eq "BuildError") {
        Write-Host "   BUILD ERROR:"
        $r.logs | ForEach-Object { Write-Host "     $_" }
        exit 1
    }
}
if (-not $compiled) {
    Write-Host "   Compile timed out."
    exit 1
}

# 4. Start backtest
Write-Host "4. Starting backtest..."
$btName = "Composite_" + [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$r = Invoke-QCApi -Endpoint "/backtests/create" -Body @{
    projectId   = $projectId
    compileId   = $compileId
    backtestName = $btName
}
$backtestId = $r.backtest.backtestId
Write-Host "   Backtest: $btName (ID: $backtestId)"

# 5. Poll until complete
Write-Host "5. Waiting for backtest to complete (this may take several minutes)..."
$url = "https://www.quantconnect.com/terminal/$projectId#open/$backtestId"
for ($i = 0; $i -lt 360; $i++) {
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-QCApi -Endpoint "/backtests/read" -Body @{ projectId = $projectId; backtestId = $backtestId }
    } catch {
        Write-Host "   Poll error: $($_.Exception.Message)"
        continue
    }
    $bt = $r.backtest
    if ($bt.completed) {
        Write-Host "   DONE!"
        $stats = $bt.statistics
        Write-Host "`n--- RESULTS ---"
        Write-Host "CAGR:      $($stats.'Compounding Annual Return')"
        Write-Host "Net Profit: $($stats.'Net Profit')"
        Write-Host "Drawdown:  $($stats.Drawdown)"
        Write-Host "Sharpe:    $($stats.'Sharpe Ratio')"
        Write-Host "`nOpen in browser:"
        Write-Host $url
        # Save result
        $outPath = Join-Path $SCRIPT_DIR "qc_composite_backtest_result.json"
        @{
            project_id = $projectId
            backtest_id = $backtestId
            url = $url
            statistics = $stats
            runtimeStatistics = $bt.runtimeStatistics
        } | ConvertTo-Json -Depth 10 | Set-Content -Path $outPath -Encoding UTF8
        Write-Host "`nResult saved to: $outPath"
        exit 0
    }
    if ($i % 12 -eq 0 -and $i -gt 0) {
        $p = $bt.progress
        Write-Host "   $([math]::Round(100 * $p))% complete..."
    }
}

Write-Host "   Timed out. Open backtest manually:"
Write-Host $url
