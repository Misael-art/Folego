# Local preferences and read-only Delivery Optimization telemetry for Windows.
$script:FolegoPerformanceKeys = @('delivery', 'indexing', 'edge', 'logon', 'effects', 'storage')

function Get-FolegoPerformanceSettings([string]$DataRoot) {
    $settings = [ordered]@{ schema = 1 }
    foreach ($key in $script:FolegoPerformanceKeys) { $settings[$key] = $true }
    $path = Join-Path $DataRoot 'windows-performance.json'
    if (-not (Test-Path -LiteralPath $path -ErrorAction Stop)) { return $settings }
    $saved = Read-FolegoJson $path
    $schema = Get-FolegoValue $saved schema
    if (($schema -isnot [int] -and $schema -isnot [long]) -or $schema -ne 1) {
        throw 'As preferências de desempenho têm um formato desconhecido.'
    }
    foreach ($key in $script:FolegoPerformanceKeys) {
        $property = $saved.PSObject.Properties[$key]
        if ($null -eq $property) { continue }
        if ($property.Value -isnot [bool]) { throw 'As preferências de desempenho estão inválidas.' }
        $settings[$key] = $property.Value
    }
    return $settings
}

function Set-FolegoPerformanceOption([string]$DataRoot, [string]$Key, [bool]$Enabled) {
    if ($Key -notin $script:FolegoPerformanceKeys) { throw 'Opção de desempenho desconhecida.' }
    $settings = Get-FolegoPerformanceSettings $DataRoot
    if ($settings[$Key] -ne $Enabled) {
        $settings[$Key] = $Enabled
        Write-FolegoJson (Join-Path $DataRoot 'windows-performance.json') $settings
    }
    return $settings
}

function Get-FolegoDeliverySnapshot {
    try {
        if ((Get-Service -Name DoSvc -ErrorAction Stop).Status -ne 'Running') { return $null }
        $rows = @(Get-DeliveryOptimizationStatus -ErrorAction Stop | Select-Object -First 129)
    } catch { return $null }

    $jobs = @{}
    $observedAt = [DateTime]::UtcNow.ToString('o')
    $partial = $rows.Count -gt 128
    $active = 0
    foreach ($row in @($rows | Select-Object -First 128)) {
        if ((Get-FolegoValue $row Status) -eq 'Downloading') { $active++ }
        $id = [string](Get-FolegoValue $row FileId)
        $priority = [string](Get-FolegoValue $row Priority)
        $bytes = 0L
        if (-not $id -or $jobs.ContainsKey($id) -or
            -not [long]::TryParse([string](Get-FolegoValue $row TotalBytesDownloaded), [ref]$bytes) -or $bytes -lt 0) {
            $partial = $true
            continue
        }
        $jobs[$id] = [pscustomobject]@{ Bytes = $bytes; Priority = $priority }
    }
    return [pscustomobject]@{ AtUtc = $observedAt; Jobs = $jobs; Active = $active; Partial = $partial }
}

function Measure-FolegoDeliveryActivity($Before, $After, $Enabled) {
    $result = [ordered]@{
        state = 'unavailable'; source = 'Get-DeliveryOptimizationStatus'
        before_utc = $null; after_utc = $null; downloading_before = $null; downloading_after = $null
        matched_jobs = $null; downloaded_bytes = $null; background_bytes = $null; unclassified_bytes = $null
    }
    if ($Enabled -eq $false) { $result.state = 'disabled'; return $result }
    if ($null -eq $Before -or $null -eq $After) { return $result }

    $result.before_utc = $Before.AtUtc; $result.after_utc = $After.AtUtc
    $result.downloading_before = $Before.Active; $result.downloading_after = $After.Active
    $result.matched_jobs = 0
    $partial = $Before.Partial -or $After.Partial -or $Before.Jobs.Count -ne $After.Jobs.Count
    $downloaded = [decimal]0; $background = [decimal]0; $unclassified = [decimal]0
    foreach ($id in $Before.Jobs.Keys) {
        $old = $Before.Jobs[$id]; $new = $After.Jobs[$id]
        if ($null -eq $new -or $new.Bytes -lt $old.Bytes) {
            $partial = $true
            continue
        }
        $result.matched_jobs++
        $delta = $new.Bytes - $old.Bytes
        $downloaded += $delta
        if ($old.Priority -eq 'Background' -and $new.Priority -eq 'Background') { $background += $delta }
        elseif ($old.Priority -ne 'Foreground' -or $new.Priority -ne 'Foreground') { $unclassified += $delta }
    }
    $result.state = if ($partial) { 'partial' } else { 'available' }
    if ($result.matched_jobs -gt 0 -or -not $partial) {
        $result.downloaded_bytes = $downloaded
        $result.background_bytes = $background
        $result.unclassified_bytes = $unclassified
    }
    return $result
}

function Format-FolegoDeliveryActivity($Data) {
    if ($null -eq $Data -or $Data.state -eq 'unavailable') { return 'Downloads do Windows · dados indisponíveis' }
    if ($Data.state -eq 'disabled') { return 'Downloads do Windows · medição desligada' }
    if ($null -eq $Data.downloaded_bytes) { return 'Downloads do Windows · amostra parcial, sem transferências comparáveis' }
    $note = if ($Data.state -eq 'partial') { ' · amostra parcial' } else { '' }
    if ($Data.unclassified_bytes -gt 0) { $note += ' · parte sem prioridade identificada' }
    return ('Downloads do Windows · {0:N2} MiB observados ({1:N2} MiB em segundo plano){2}' -f
        ($Data.downloaded_bytes / 1MB), ($Data.background_bytes / 1MB), $note)
}
