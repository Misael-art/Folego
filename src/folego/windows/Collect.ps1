param([string]$DataRoot, $Collector, $HostInfo, $Extended, [string]$Action = 'Sample', $Guard, $Target, $Confirmation, $Policy)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Folego.Core.ps1')
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'O coletor nativo exige Windows.' }
# The UI passes its validated policy; parsing it again on every poll costs ~1 s on the card.
$policy = if ($null -ne $Policy) { $Policy } else { Get-FolegoPolicy }
$notes = New-Object 'Collections.Generic.List[string]'
$sample = $Collector.Read([IO.Path]::GetPathRoot($PSScriptRoot))
if ($null -eq $HostInfo) { try { $HostInfo = Get-FolegoHost } catch { $notes.Add([string]$_) } }
$now = [long][Folego.Windows.Native]::GetTickCount64()
if ($null -eq $Extended -or $now - $Extended.Mono -ge 60000) {
    $Extended = [pscustomobject]@{ Mono = $now; Thermal = @(); DiskQueue = $null; VolumeHealth = 'desconhecida'; Notes = @() }
    $warnings = @()
    try {
        $Extended.Thermal = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -OperationTimeoutSec 3 -ErrorAction Stop | ForEach-Object {
            $temperature = ([double]$_.CurrentTemperature / 10) - 273.15
            $passive = if ($_.PassiveTripPoint -gt 0) { ([double]$_.PassiveTripPoint / 10) - 273.15 } else { $null }
            $critical = if ($_.CriticalTripPoint -gt 0) { ([double]$_.CriticalTripPoint / 10) - 273.15 } else { $null }
            if ($temperature -gt -20 -and $temperature -lt 150) { [pscustomobject]@{ Name = [string]$_.InstanceName; Celsius = $temperature; Passive = $passive; Critical = $critical } }
        })
    } catch { }
    if (-not $Extended.Thermal.Count) {
        # Same zone through the performance class, readable without administrator rights.
        try { $Extended.Thermal = @(Get-FolegoThermalZones) } catch { }
        if (-not $Extended.Thermal.Count) { $warnings += 'Temperatura ACPI indisponível; não foi substituída por uma leitura de CPU/GPU.' }
    }
    try {
        $letter = ([IO.Path]::GetPathRoot($PSScriptRoot)).TrimEnd([char]'\')
        $disk = Get-CimInstance Win32_PerfFormattedData_PerfDisk_LogicalDisk -Filter ("Name='" + $letter + "'") -OperationTimeoutSec 3 -ErrorAction Stop
        if ($null -ne $disk) { $Extended.DiskQueue = $disk.CurrentDiskQueueLength }
    } catch { $warnings += 'Contador de fila do disco indisponível.' }
    try {
        $drive = ([IO.Path]::GetPathRoot($PSScriptRoot)).Substring(0, 1)
        $volume = Get-Volume -DriveLetter $drive -ErrorAction Stop
        $Extended.VolumeHealth = [string]$volume.HealthStatus
    } catch { $warnings += 'Saúde do volume indisponível para este usuário.' }
    $Extended.Notes = $warnings
}
$power = $null; $thermalState = $null
if ($null -ne $HostInfo) {
    try { $power = Get-FolegoPowerState $DataRoot $HostInfo } catch { $notes.Add([string]$_) }
    try { $thermalState = Get-FolegoThermalState $DataRoot $HostInfo } catch { $notes.Add([string]$_) }
}
# Fast thermal reading only while the guard is enabled; otherwise the 60 s detail is enough.
$thermalNow = $null
if ($null -ne $thermalState -and $thermalState.enabled) {
    try {
        $zones = @(Get-FolegoThermalZones)
        if ($zones.Count) { $hot = $zones | Sort-Object Celsius -Descending | Select-Object -First 1; $thermalNow = [pscustomobject]@{ Celsius = $hot.Celsius; Zone = $hot.Name; Mono = $now } }
    } catch { $notes.Add('Leitura térmica rápida indisponível; a guarda não age sem temperatura.') }
} elseif (@($Extended.Thermal).Count) {
    $hot = @($Extended.Thermal) | Sort-Object Celsius -Descending | Select-Object -First 1
    $thermalNow = [pscustomobject]@{ Celsius = [Math]::Round($hot.Celsius, 1); Zone = $hot.Name; Mono = $Extended.Mono }
}
function Assert-Host { if ($null -eq $HostInfo) { throw 'Identifique o host antes de alterar o sistema.' } }
$actionResult = ''; $data = $null; $actionError = ''
try {
switch ($Action) {
    'Economy' { Assert-Host; $actionResult = Invoke-FolegoPower $DataRoot $HostInfo Economy }
    'Restore' { Assert-Host; $actionResult = Invoke-FolegoPower $DataRoot $HostInfo Restore }
    'Reconcile' { Assert-Host; $actionResult = Repair-FolegoPowerReceipt $DataRoot $HostInfo }
    'EnableGuard' {
        if ($null -eq $power) { throw 'Estado de energia indisponível.' }
        if ($power.paused -or ($null -ne $power.receipt -and $power.receipt.state -in @('intended', 'unknown'))) { throw 'Reconcilie o recibo antes de habilitar o guarda.' }
        $power.enabled = $true; Save-FolegoPowerState $DataRoot $HostInfo $power
        $actionResult = 'Guarda por carga habilitado neste hardware. Não detecta queda de tensão.'
    }
    'DisableGuard' {
        if ($null -eq $power) { throw 'Estado de energia indisponível.' }
        $power.enabled = $false; Save-FolegoPowerState $DataRoot $HostInfo $power
        $actionResult = 'Guarda desabilitado. O plano atual não foi trocado; use Restaurar se houver recibo válido.'
    }
    'AutoPower' {
        if ($null -ne $power -and $power.enabled -and -not $power.paused) {
            if ($sample.ExternalPower -eq $true -and $null -ne $power.receipt -and $power.receipt.state -eq 'applied') {
                $actionResult = Invoke-FolegoPower $DataRoot $HostInfo Restore -Automatic
            } elseif ($sample.ExternalPower -eq $false -and $null -ne $sample.BatteryPercent -and $sample.BatteryPercent -le 10) {
                $actionResult = Invoke-FolegoPower $DataRoot $HostInfo Economy -Automatic
            }
        }
    }
    'Fresco' { Assert-Host; $actionResult = Invoke-FolegoThermal $DataRoot $HostInfo Fresco $policy }
    'Contencao' { Assert-Host; $actionResult = Invoke-FolegoThermal $DataRoot $HostInfo Contencao $policy }
    'ThermalRestore' { Assert-Host; $actionResult = Invoke-FolegoThermal $DataRoot $HostInfo Restore $policy }
    'ThermalReconcile' { Assert-Host; $actionResult = Repair-FolegoThermalReceipt $DataRoot $HostInfo }
    'ThermalAdopt' { Assert-Host; $actionResult = Confirm-FolegoThermalBoot $DataRoot $HostInfo $Confirmation }
    'EnableThermalGuard' { Assert-Host; $actionResult = Set-FolegoThermalGuard $DataRoot $HostInfo $true $Confirmation }
    'DisableThermalGuard' { Assert-Host; $actionResult = Set-FolegoThermalGuard $DataRoot $HostInfo $false $null }
    'Consumers' {
        Assert-Host
        $data = Invoke-FolegoProcessTriage $DataRoot $HostInfo $policy
        $lines = @('Janela de ' + $data.ElapsedMs + ' ms. Núcleos = tempo de CPU no intervalo; E/S = leitura+gravação. Nada foi encerrado.')
        if ($data.InstallerActive) { $lines += 'Instalação do Windows em andamento: todos os encerramentos estão bloqueados.' }
        if ($data.Note) { $lines += $data.Note }
        $lines += 'Maiores grupos por executável:'
        foreach ($g in $data.Groups) { $lines += ('  {0} x{1}: {2} núcleos, {3} KB/s' -f $g.name, $g.count, $g.cores, $g.io_kbps) }
        $lines += Get-FolegoSystemLoadReport
        $actionResult = $lines -join "`r`n"
    }
    'EndGentle' { Assert-Host; $actionResult = Invoke-FolegoProcessAction $DataRoot $HostInfo $Target Gentle $Confirmation $policy }
    'EndForce' { Assert-Host; $actionResult = Invoke-FolegoProcessAction $DataRoot $HostInfo $Target Force $Confirmation $policy }
    'StartupList' {
        Assert-Host
        $items = @(Get-FolegoStartupItems $policy)
        $startup = Get-FolegoStartupState $DataRoot $HostInfo
        $commands = @{}; try { $commands = Get-FolegoCommandLines } catch { }
        $lines = @(Compare-FolegoStartupReview $items $startup.review) + @('') + @(Get-FolegoCopilotReport $items $commands)
        $applied = @($startup.receipts | Where-Object { $_.state -eq 'applied' -and $_.action -ne 'Restore' })
        if ($applied.Count) { $lines += ''; $lines += 'Alterações do Fôlego que podem ser restauradas:'; foreach ($r in $applied) { $lines += ('  ' + $r.key + ' (' + $r.action + ', ' + $r.at + ')') } }
        $sequence = $null; try { $sequence = Get-FolegoSequenceState $DataRoot $HostInfo } catch { $lines += ''; $lines += [string]$_ }
        $data = [pscustomobject]@{ Items = $items; Receipts = @($startup.receipts); Sequence = $sequence }
        $actionResult = $lines -join "`r`n"
    }
    'StartupDisable' { Assert-Host; $actionResult = Set-FolegoStartupItem $DataRoot $HostInfo $Target $false $Confirmation $policy }
    'StartupEnable' { Assert-Host; $actionResult = Set-FolegoStartupItem $DataRoot $HostInfo $Target $true $Confirmation $policy }
    'StartupRestore' { Assert-Host; $actionResult = Restore-FolegoStartupItem $DataRoot $HostInfo $Target $Confirmation }
    'StartupReconcile' { Assert-Host; $actionResult = Repair-FolegoStartupReceipts $DataRoot $HostInfo }
    'StartupReview' { Assert-Host; $actionResult = Save-FolegoStartupReview $DataRoot $HostInfo @(Get-FolegoStartupItems $policy) }
    'SequenceAdd' { Assert-Host; $actionResult = Add-FolegoSequenceItem $DataRoot $HostInfo $Target $Confirmation $policy }
    'SequenceRemove' { Assert-Host; $actionResult = Remove-FolegoSequenceItem $DataRoot $HostInfo $Target $Confirmation }
    'SequenceUp' { Assert-Host; $actionResult = Move-FolegoSequenceItem $DataRoot $HostInfo $Target -1 }
    'SequenceDown' { Assert-Host; $actionResult = Move-FolegoSequenceItem $DataRoot $HostInfo $Target 1 }
    'LogonInventory' { $actionResult = (Get-FolegoLogonInventory $policy) -join "`r`n" }
    'SequenceTick' {
        # One step of the serialized logon; the run object lives in the UI between ticks.
        Assert-Host
        $run = $Target; $rules = $policy.windows.sequence
        if ($null -eq $run.TaskNames) { try { $run.TaskNames = @(Get-FolegoLogonTaskNames) } catch { $run.TaskNames = @() } }
        $disk = $null; try { $disk = Get-FolegoDiskBusy } catch { }
        $celsius = $null; try { $hot = @(Get-FolegoThermalZones) | Sort-Object Celsius -Descending | Select-Object -First 1; if ($null -ne $hot) { $celsius = $hot.Celsius } } catch { }
        $reading = [pscustomobject]@{ Cpu = $sample.CpuPercent; DiskBusy = $(if ($null -ne $disk) { $disk.Busy } else { $null }); DiskQueue = $(if ($null -ne $disk) { $disk.Queue } else { $null }); Celsius = $celsius; TasksRunning = @(Get-FolegoRunningTasks $run.TaskNames) }
        $decision = Step-FolegoSequence $run $reading $rules $now
        switch ($decision.Action) {
            'launch' {
                $outcome = Invoke-FolegoSequenceLaunch $DataRoot $HostInfo $decision.Key $policy
                Save-FolegoSequenceResult $DataRoot $HostInfo $decision.Key $outcome.State $outcome.Detail
                $run.Results = @(@($run.Results) + @([pscustomobject]@{ Key = $decision.Key; State = $outcome.State; Detail = $outcome.Detail }))
                $actionResult = 'Sequência: ' + $decision.Key + ' → ' + $outcome.State + ' (' + $outcome.Detail + ')'
            }
            'skip' {
                $detail = 'sem janela de calma em ' + [int]($rules.item_timeout_seconds / 60) + ' min: ' + ($decision.Reasons -join ', ') + '; não iniciado sob estresse'
                Save-FolegoSequenceResult $DataRoot $HostInfo $decision.Key 'skipped' $detail
                $run.Results = @(@($run.Results) + @([pscustomobject]@{ Key = $decision.Key; State = 'skipped'; Detail = $detail }))
                $actionResult = 'Sequência: ' + $decision.Key + ' adiado — ' + $detail
            }
            default { $actionResult = 'Sequência: ' + $decision.Action + $(if ($decision.Key) { ' ' + $decision.Key } else { '' }) + $(if ($decision.Reasons.Count) { ' — ' + ($decision.Reasons -join ', ') } else { '' }) }
        }
        $data = [pscustomobject]@{ Decision = $decision; Reading = $reading }
    }
    'Processes' {
        $actionResult = 'Amostra de RAM e tempo acumulado de CPU; não é percentual instantâneo. Sem fechar/processar agentes.' + "`r`n"
        $actionResult += (Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 25 Id, ProcessName, @{n='RAM_MiB';e={[Math]::Round($_.WorkingSet64 / 1MB)}}, @{n='CPU_s_acumulada';e={$_.CPU}} | Format-Table -AutoSize | Out-String)
    }
    'Temps' {
        $lines = @('Somente arquivos diretamente nas pastas temporárias conhecidas, até 1000 por pasta. Sem recursão, exclusão, limpeza ou inferência de abandono.')
        foreach ($path in @([IO.Path]::GetTempPath(), (Join-Path ([Environment]::GetFolderPath('Windows')) 'Temp')) | Select-Object -Unique) {
            try {
                $items = @(Get-ChildItem -LiteralPath $path -File -ErrorAction Stop | Select-Object -First 1000)
                $lines += $path
                $lines += ('{0} arquivos amostrados; {1:N1} MiB. Diretórios e itens inacessíveis não estão contabilizados.' -f $items.Count, (($items | Measure-Object Length -Sum).Sum / 1MB))
            } catch { $lines += ($path + ': leitura parcial/indisponível; não é zero.') }
        }
        $actionResult = $lines -join "`r`n"
    }
    'Events' {
        try {
            $events = @(Get-WinEvent -FilterHashtable @{LogName='System';Id=@(41,6008)} -MaxEvents 12 -ErrorAction Stop)
            $actionResult = 'Eventos de corte/reinício; registram o incidente e não comprovam sua causa.' + "`r`n" + ($events | Select-Object TimeCreated, Id, ProviderName | Format-Table -AutoSize | Out-String)
        } catch { $actionResult = 'Sem leitura de eventos disponível: ' + [string]$_ }
    }
}
} catch { $actionError = [string]$_.Exception.Message }
# Automatic thermal guard: opt-in, hysteresis, budget and the same receipts as manual use.
if ($null -ne $Guard -and $null -ne $thermalState -and $thermalState.enabled -and -not $thermalState.paused -and $Action -eq 'Sample') {
    $celsius = if ($null -ne $thermalNow -and $thermalNow.Mono -eq $now) { $thermalNow.Celsius } else { $null }
    $level = Get-FolegoThermalProfile $thermalState $HostInfo
    $decision = Step-FolegoThermalGuard $Guard $celsius $policy.windows.thermal $level $now
    if ($decision -ne 'None') {
        $trigger = [pscustomobject]@{ celsius = $celsius; zone = $thermalNow.Zone; window = @($Guard.Recent | Select-Object -Last 6 | ForEach-Object { $_.Celsius }); from = $level }
        try { $actionResult = 'Guarda térmica: ' + (Invoke-FolegoThermal $DataRoot $HostInfo $decision $policy -Automatic -Trigger $trigger) }
        catch { $notes.Add('Guarda térmica não trocou o perfil: ' + [string]$_) }
    }
}
try { $activePlan = Get-FolegoActivePlan } catch { $activePlan = 'indisponível'; $notes.Add([string]$_) }
$processor = $null
try { $processor = Get-FolegoThermalValues $activePlan } catch { $notes.Add('Limites do processador ilegíveis: ' + [string]$_) }
if ($null -ne $HostInfo) {
    try { $power = Get-FolegoPowerState $DataRoot $HostInfo } catch { $notes.Add([string]$_) }
    try { $thermalState = Get-FolegoThermalState $DataRoot $HostInfo } catch { $notes.Add([string]$_) }
}
return [pscustomobject]@{ Sample = $sample; HostInfo = $HostInfo; Extended = $Extended; Power = $power; Plan = $activePlan; Action = $Action; Result = $actionResult; Notes = @($notes); Thermal = $thermalState; ThermalNow = $thermalNow; Processor = $processor; Data = $data; Error = $actionError }
