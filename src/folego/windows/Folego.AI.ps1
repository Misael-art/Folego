# Read-only fallback from Codex rollout logs. This feed lacks verified account identity.
function ConvertTo-FolegoCodexObservation($Record, [DateTimeOffset]$Now) {
    $payload = Get-FolegoValue $Record payload
    if ((Get-FolegoValue $Record type) -cne 'event_msg' -or (Get-FolegoValue $payload type) -cne 'token_count') { return }
    $limits = Get-FolegoValue $payload rate_limits
    $limitId = Get-FolegoValue $limits limit_id
    $timestamp = [string](Get-FolegoValue $Record timestamp)
    $at = [DateTimeOffset]::MinValue
    if ($null -eq $limits -or ($limitId -and $limitId -cne 'codex') -or
        $timestamp -notmatch '(?:Z|[+-]\d{2}:\d{2})$' -or
        -not [DateTimeOffset]::TryParse($timestamp, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$at) -or
        $at -gt $Now -or $at.AddMinutes(15) -le $Now) { return }
    $windows = foreach ($name in @('primary', 'secondary')) {
        $window = Get-FolegoValue $limits $name
        $used = Get-FolegoValue $window used_percent
        if (($used -isnot [int] -and $used -isnot [long] -and $used -isnot [double]) -or -not ($used -ge 0 -and $used -le 100)) { continue }
        $reset = $null
        $resetSeconds = Get-FolegoValue $window resets_at
        if ($null -ne $resetSeconds) {
            if (-not (Test-FolegoInt $resetSeconds)) { continue }
            try { $reset = [DateTimeOffset]::FromUnixTimeSeconds([long]$resetSeconds) } catch { continue }
        }
        $label = if ($name -eq 'primary') { 'Principal' } else { 'Secundária' }
        $minutes = Get-FolegoValue $window window_minutes
        if ((Test-FolegoInt $minutes) -and $minutes -gt 0 -and $minutes -le 43200) {
            $period = if ($minutes % 1440 -eq 0) { ([string]($minutes / 1440) + ' d') } elseif ($minutes % 60 -eq 0) { ([string]($minutes / 60) + ' h') } else { ([string]$minutes + ' min') }
            $label += ' · ' + $period
        }
        [pscustomobject]@{ Label = $label; Remaining = 100.0 - $used; Reset = $reset }
    }
    [pscustomobject]@{ Observed = $at; Windows = @($windows) }
}
function Test-FolegoQuotaDirectory([IO.DirectoryInfo]$Directory) {
    while ($null -ne $Directory) {
        if (-not $Directory.Exists -or ($Directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return $false }
        $Directory = $Directory.Parent
    }
    return $true
}
function Read-FolegoCodexObservations([IO.FileInfo]$File, [DateTimeOffset]$Now) {
    if ($File.Attributes -band [IO.FileAttributes]::ReparsePoint) { return }
    $stream = [IO.File]::Open($File.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        $count = [int][Math]::Min(262144L, $stream.Length)
        $offset = $stream.Seek(-$count, [IO.SeekOrigin]::End)
        $reader = [IO.BinaryReader]::new($stream)
        $lines = [Text.Encoding]::UTF8.GetString($reader.ReadBytes($count)) -split [char]10
    } finally { $stream.Dispose() }
    # Ignore the cut head and the unfinished tail of a log still being written.
    $first = if ($offset -gt 0) { 1 } else { 0 }
    for ($index = $first; $index -lt $lines.Count - 1; $index++) {
        $line = $lines[$index].TrimStart([char]0xFEFF)
        if ($line.Length -gt 65536 -or -not $line.Contains('"rate_limits"')) { continue }
        try { $record = $line | ConvertFrom-Json -ErrorAction Stop } catch { continue }
        ConvertTo-FolegoCodexObservation $record $Now
    }
}
function Get-FolegoCodexQuota([string]$Root, [DateTimeOffset]$Now = [DateTimeOffset]::UtcNow) {
    if (-not $Root) { $Root = $env:CODEX_HOME }
    if (-not $Root) { $Root = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
    if ($Root -notmatch '^[A-Za-z]:\\') { throw 'O perfil de registros precisa estar em um caminho local absoluto.' }
    $rootPath = [IO.Path]::GetPathRoot($Root)
    if ([IO.DriveInfo]::new($rootPath).DriveType -ne [IO.DriveType]::Fixed) { throw 'O volume do perfil de registros não é fixo local.' }
    $sessions = Join-Path ([IO.Path]::GetFullPath($Root)) 'sessions'
    $days = @($Now.UtcDateTime.Date, $Now.UtcDateTime.Date.AddDays(-1), $Now.LocalDateTime.Date, $Now.LocalDateTime.Date.AddDays(-1))
    $folders = @($days | ForEach-Object { $_.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture).Replace('-', '\') } | Select-Object -Unique)
    $candidates = foreach ($day in $folders) {
        $folder = [IO.DirectoryInfo]::new((Join-Path $sessions $day))
        if (-not (Test-FolegoQuotaDirectory $folder)) { continue }
        $files = @($folder.EnumerateFiles('rollout-*.jsonl') | Select-Object -First 49)
        if ($files.Count -gt 48) { throw 'Os registros do dia ultrapassaram o limite da consulta local.' }
        $files | Where-Object { $_.LastWriteTimeUtc -ge $Now.UtcDateTime.AddMinutes(-15) -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }
    }
    $observations = foreach ($file in ($candidates | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 6)) {
        try { Read-FolegoCodexObservations $file $Now } catch [IO.FileNotFoundException] { }
    }
    $observations | Sort-Object Observed -Descending | Select-Object -First 1
}
function Format-FolegoCodexQuota($Observation, [DateTimeOffset]$Now) {
    if ($null -eq $Observation -or $Observation.Observed -gt $Now -or $Observation.Observed.AddMinutes(15) -le $Now) {
        return 'Cota indisponível · nenhuma observação local recente.'
    }
    $lines = foreach ($window in $Observation.Windows) {
        if ($null -ne $window.Reset -and $window.Reset -le $Now) { continue }
        $reset = if ($null -eq $window.Reset) { 'Reposição indisponível' } else { 'Reposição informada: ' + $window.Reset.LocalDateTime.ToString('g') }
        '{0} · {1:0.##}% disponível · {2}' -f $window.Label, $window.Remaining, $reset
    }
    if (-not $lines) { $lines = @('Cota indisponível · aguardando uma nova observação de uso.') }
    return (@(('Registros locais do Codex · observado às ' + $Observation.Observed.LocalDateTime.ToString('g')), '') + $lines) -join [Environment]::NewLine
}
