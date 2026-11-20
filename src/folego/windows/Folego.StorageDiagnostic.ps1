function Get-FolegoDiagnosticEvents($Disk, [DateTime]$BootUtc, [DateTime]$UntilUtc) {
    $from = $BootUtc
    if ($from -lt $UntilUtc.AddHours(-24)) { $from = $UntilUtc.AddHours(-24) }
    $result = [ordered]@{ source = 'System/disk'; since_utc = $from.ToString('o'); state = 'unavailable'; unverified = $null; matches = @() }
    if ($null -eq $Disk) { return $result }
    try {
        $events = @(Get-WinEvent -FilterHashtable @{
            LogName = 'System'; ProviderName = 'disk'; Id = @(51, 153); StartTime = $from; EndTime = $UntilUtc
        } -MaxEvents 24 -ErrorAction Stop)
    } catch {
        if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound,*') { return $result }
        $events = @()
    }
    $result.state = if ($events.Count -lt 24) { 'available' } else { 'limited' }
    $result.unverified = 0
    foreach ($event in $events) {
        try {
            $xml = [xml]$event.ToXml()
            $fields = @($xml.SelectNodes("/*[local-name()='Event']/*[local-name()='EventData']/*[local-name()='Data']") |
                ForEach-Object { $_.InnerText })
            if ((Test-FolegoDiagnosticEventDevice $fields $Disk.Device) -and $event.TimeCreated.ToUniversalTime() -ge $from) {
                $result.matches += [ordered]@{ id = $event.Id; record = $event.RecordId; at_utc = $event.TimeCreated.ToUniversalTime().ToString('o') }
            } else { $result.unverified++ }
        } catch { $result.unverified++ }
    }
    return $result
}

function Test-FolegoDiagnosticEventDevice([string[]]$Fields, [string]$Device) {
    if ($Device -notmatch '^\\Device\\Harddisk[0-9]+\\DR[0-9]+$') { return $false }
    return $Device -in $Fields
}

function Measure-FolegoDiagnosticMetric($Values, [string]$Unit, [string]$Source, [switch]$Latency) {
    $values = @($Values | Where-Object { $null -ne $_ } | Sort-Object)
    $result = [ordered]@{ state = 'unavailable'; valid_windows = $values.Count; unit = $Unit; source = $Source
        min = $null; median = $null; max = $null }
    if (-not $values.Count) {
        if ($Latency) { $result.state = 'no_activity' }
        return $result
    }
    $low = [int][Math]::Floor(($values.Count - 1) / 2)
    $high = [int][Math]::Floor($values.Count / 2)
    $result.state = 'available'
    $result.min = [Math]::Round([double]$values[0], 3)
    $result.median = [Math]::Round(([double]$values[$low] + [double]$values[$high]) / 2, 3)
    $result.max = [Math]::Round([double]$values[-1], 3)
    return $result
}

function Measure-FolegoDiagnosticOperation($Windows, [string]$Rate, [string]$Latency) {
    $count = @($Windows | Where-Object { $null -ne $_.$Rate })
    $active = @($count | Where-Object { $_.$Rate -gt 0 })
    $latencyValues = @($active | ForEach-Object { if ($null -ne $_.$Latency) { 1000 * $_.$Latency } })
    $idle = $Windows.Count -gt 0 -and $count.Count -eq $Windows.Count -and -not $active.Count
    $operations = $null
    if ($count.Count) {
        $estimate = ($count | ForEach-Object { $_.$Rate * $_.seconds } | Measure-Object -Sum).Sum
        $operations = [Math]::Round($estimate)
    }
    return [ordered]@{
        operations = $operations
        rate = Measure-FolegoDiagnosticMetric @($count | ForEach-Object { $_.$Rate }) 'ops/s' 'PDH PhysicalDisk'
        latency = Measure-FolegoDiagnosticMetric $latencyValues 'ms' 'PDH PhysicalDisk' -Latency:$idle
    }
}

function Save-FolegoStorageDiagnostic([string]$DataRoot, $Report) {
    # Fixed slots bound retention without deleting user files or traversing arbitrary directories.
    $slots = @(0..5 | ForEach-Object {
        $path = Join-Path $DataRoot ('storage-diagnostic-' + $_ + '.json')
        $file = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
        [pscustomobject]@{ Path = $path; LastWrite = if ($null -eq $file) { [DateTime]::MinValue } else { $file.LastWriteTimeUtc } }
    })
    $chosen = $slots | Sort-Object LastWrite, Path | Select-Object -First 1
    Write-FolegoJson $chosen.Path $Report
    return $chosen.Path
}

function Invoke-FolegoStorageDiagnostic([string]$DataRoot, [Threading.ManualResetEventSlim]$Cancel) {
    $userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $mutex = New-Object Threading.Mutex($false, ('Local\Folego.Windows.StorageDiagnostic.' + $userSid))
    $acquired = $false
    try {
        try { $acquired = $mutex.WaitOne(0) }
        catch [Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) { throw 'Já há um diagnóstico de disco em andamento nesta sessão.' }
        return Measure-FolegoStorageDiagnostic $DataRoot $Cancel
    } finally {
        if ($acquired) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

function Get-FolegoNextStorageWindow([long]$Scheduled, [long]$Observed, [int]$IntervalMs) {
    # Leave missed windows missing. Never issue bursts to catch up after a slow read.
    if ($Scheduled + $IntervalMs -le $Observed) { return ($Observed + $IntervalMs) }
    return ($Scheduled + $IntervalMs)
}

function Measure-FolegoStorageDiagnostic([string]$DataRoot, [Threading.ManualResetEventSlim]$Cancel,
    [int]$DurationMs = 36000, [int]$IntervalMs = 3000) {
    if ($Cancel.IsSet) { return }
    $requested = [DateTime]::UtcNow
    $boot = $requested.AddMilliseconds(-[double][Folego.Windows.Native]::GetTickCount64())
    $watch = [Diagnostics.Stopwatch]::StartNew()
    if (-not ('Folego.Windows.DiagnosticDisk' -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot 'StorageDiagnostic.cs') -ErrorAction Stop
    }
    if ($Cancel.IsSet) { return }
    $root = [IO.Path]::GetPathRoot([Environment]::SystemDirectory)
    $native = New-Object Folego.Windows.Native
    $disk = [Folego.Windows.DiagnosticDisk]::Resolve($root)
    $diskNumber = if ($null -ne $disk) { $disk.Number } else { -1 }
    $paths = @('\PhysicalDisk(*)\Disk Reads/sec', '\PhysicalDisk(*)\Disk Writes/sec',
        '\PhysicalDisk(*)\Avg. Disk sec/Read', '\PhysicalDisk(*)\Avg. Disk sec/Write',
        '\PhysicalDisk(*)\Avg. Disk Queue Length', '\Memory\Pages Input/sec',
        '\Memory\Pages Output/sec', '\Memory\Page Reads/sec', '\Memory\Page Writes/sec')
    $windows = New-Object 'Collections.Generic.List[object]'
    $diskMatches = $null -ne $disk
    $self = [Diagnostics.Process]::GetCurrentProcess()
    try {
        $cpuStart = $self.TotalProcessorTime.TotalMilliseconds
        $counters = [Folego.Windows.DiagnosticCounters]::new([string[]]$paths, 5, $diskNumber)
        try {
            $null = $native.Read($root)
            $started = [DateTime]::UtcNow
            $setupMs = $watch.ElapsedMilliseconds
            $samplingCpuStart = $self.TotalProcessorTime.TotalMilliseconds
            $previous = $setupMs
            $next = $setupMs + $IntervalMs
            $deadline = $setupMs + $DurationMs
            while ($next -le $deadline) {
                if ($Cancel.Wait([int][Math]::Max(0, $next - $watch.ElapsedMilliseconds))) { return }
                if ($watch.ElapsedMilliseconds -gt $deadline + $IntervalMs) { break }
                if ($diskMatches) { $diskMatches = $disk.SameAs([Folego.Windows.DiagnosticDisk]::Resolve($root)) }
                $raw = $counters.Read($diskMatches)
                $sample = $native.Read($root)
                $now = $watch.ElapsedMilliseconds
                $seconds = ($now - $previous) / 1000.0
                $windows.Add([pscustomobject]@{
                    seconds = $seconds; reads = $raw[0]; writes = $raw[1]; read_latency = $raw[2]; write_latency = $raw[3]; queue = $raw[4]
                    pages_in = $raw[5]; pages_out = $raw[6]; page_reads = $raw[7]; page_writes = $raw[8]; cpu = $sample.CpuPercent
                    ram = if ($sample.TotalPhysical -gt 0) { $sample.AvailablePhysical / 1MB } else { $null }
                    commit = if ($sample.CommitLimit -gt 0) { $sample.CommitUsed / 1MB } else { $null }
                    limit = if ($sample.CommitLimit -gt 0) { $sample.CommitLimit / 1MB } else { $null }
                })
                $previous = $now
                $next = Get-FolegoNextStorageWindow $next $now $IntervalMs
            }
        } finally { $counters.Dispose() }
        if ($Cancel.IsSet) { return }
        $watch.Stop()
        $cpuEnd = $self.TotalProcessorTime.TotalMilliseconds
        $cpuDelta = [Math]::Max(0, $cpuEnd - $cpuStart)
        $samplingCpu = [Math]::Max(0, $cpuEnd - $samplingCpuStart)
    } finally { $self.Dispose() }
    $finished = [DateTime]::UtcNow
    $diskWindows = if ($diskMatches) { @($windows.ToArray()) } else { @() }
    $limitations = @(
        'Latência por janela ativa; a mediana não é um percentil das operações individuais.'
        'Operações estimadas pela taxa PDH vezes a duração de cada janela válida.'
        'Paginação do sistema inclui arquivos mapeados; estes contadores não isolam o pagefile.'
        'CPU do processo inclui a interface e outros trabalhos do mesmo Fôlego durante a amostra.'
        'Eventos exigem caminho de dispositivo correspondente no boot atual. O histórico anterior pode estar incompleto.'
    )
    if (-not $diskMatches) {
        $disk = $null
        $limitations += 'A associação do volume com um disco único está indisponível ou mudou durante a medição.'
    }
    if ($windows.Count -lt [Math]::Floor($DurationMs / $IntervalMs)) {
        $limitations += 'Uma ou mais janelas foram perdidas por atraso da coleta.'
    }
    $report = [ordered]@{
        schema = 1; requested_utc = $requested.ToString('o'); started_utc = $started.ToString('o'); ended_utc = $finished.ToString('o')
        setup_seconds = $setupMs / 1000.0
        elapsed_seconds = ($previous - $setupMs) / 1000.0
        interval_target_seconds = $IntervalMs / 1000.0
        intervals_seconds = @($windows | ForEach-Object { $_.seconds })
        windows = $windows.Count; process_cpu_ms = [Math]::Round($cpuDelta, 1)
        sampling_process_cpu_ms = [Math]::Round($samplingCpu, 1)
        volume = $root; disk_number = if ($null -ne $disk) { $disk.Number } else { $null }
        disk_source = 'IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS + QueryDosDevice'
        reads = Measure-FolegoDiagnosticOperation @($diskWindows) 'reads' 'read_latency'
        writes = Measure-FolegoDiagnosticOperation @($diskWindows) 'writes' 'write_latency'
        queue = Measure-FolegoDiagnosticMetric @($diskWindows | ForEach-Object { $_.queue }) 'ops' 'PDH PhysicalDisk'
        ram_available = Measure-FolegoDiagnosticMetric @($windows | ForEach-Object { $_.ram }) 'MiB' 'GlobalMemoryStatusEx'
        commit_used = Measure-FolegoDiagnosticMetric @($windows | ForEach-Object { $_.commit }) 'MiB' 'GetPerformanceInfo'
        commit_limit = Measure-FolegoDiagnosticMetric @($windows | ForEach-Object { $_.limit }) 'MiB' 'GetPerformanceInfo'
        cpu = Measure-FolegoDiagnosticMetric @($windows | ForEach-Object { $_.cpu }) '%' 'GetSystemTimes'
        pages_input = Measure-FolegoDiagnosticMetric @($windows | ForEach-Object { $_.pages_in }) 'pages/s' 'PDH Memory'
        pages_output = Measure-FolegoDiagnosticMetric @($windows | ForEach-Object { $_.pages_out }) 'pages/s' 'PDH Memory'
        page_reads = Measure-FolegoDiagnosticMetric @($windows | ForEach-Object { $_.page_reads }) 'ops/s' 'PDH Memory'
        page_writes = Measure-FolegoDiagnosticMetric @($windows | ForEach-Object { $_.page_writes }) 'ops/s' 'PDH Memory'
        events = Get-FolegoDiagnosticEvents $disk $boot $finished
        limitations = $limitations
    }
    if ($Cancel.IsSet) { return }
    $path = Save-FolegoStorageDiagnostic $DataRoot $report
    return [pscustomobject]@{ Report = $report; Path = $path }
}

function Format-FolegoStorageMetric($Metric) {
    switch ($Metric.state) {
        'available' { return ('{0} {1} ({2} janelas)' -f $Metric.median, $Metric.unit, $Metric.valid_windows) }
        'no_activity' { return 'sem operações' }
        default { return 'indisponível' }
    }
}

function Format-FolegoStorageDiagnostic($Outcome) {
    $r = $Outcome.Report
    $disk = if ($null -eq $r.disk_number) { 'disco físico indisponível' } else { 'disco físico ' + $r.disk_number }
    $readOps = if ($null -eq $r.reads.operations) { '?' } else { $r.reads.operations }
    $writeOps = if ($null -eq $r.writes.operations) { '?' } else { $r.writes.operations }
    $events = if ($r.events.state -eq 'unavailable') { 'indisponíveis' } else {
        '{0} correlacionados, {1} sem vínculo com o alvo' -f $r.events.matches.Count, $r.events.unverified
    }
    return (@(
        ('Volume {0} · {1} · {2} s, {3} janelas' -f $r.volume, $disk, $r.elapsed_seconds, $r.windows)
        ('Preparo da medição · {0} s' -f $r.setup_seconds)
        ('Leitura {0} · {1} operações estimadas' -f (Format-FolegoStorageMetric $r.reads.latency), $readOps)
        ('Gravação {0} · {1} operações estimadas' -f (Format-FolegoStorageMetric $r.writes.latency), $writeOps)
        ('Fila média por janela · ' + (Format-FolegoStorageMetric $r.queue))
        ('RAM disponível · {0} | Commit · {1} de {2}' -f (Format-FolegoStorageMetric $r.ram_available),
            (Format-FolegoStorageMetric $r.commit_used), (Format-FolegoStorageMetric $r.commit_limit))
        ('Paginação · entrada {0} | saída {1}' -f (Format-FolegoStorageMetric $r.pages_input), (Format-FolegoStorageMetric $r.pages_output))
        ('Eventos 51/153 · ' + $events)
    ) + @($r.events.matches | ForEach-Object {
        ('Evento {0} · {1:g}' -f $_.id, [DateTimeOffset]::Parse($_.at_utc).LocalDateTime)
    }) + @('Resumo salvo em ' + $Outcome.Path) -join [Environment]::NewLine)
}
