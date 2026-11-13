param([string]$DataRoot, $Collector, $HostInfo, $Extended, [string]$Action = 'Sample')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Folego.Core.ps1')
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'O coletor nativo exige Windows.' }
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
        if (-not $Extended.Thermal.Count) { $warnings += 'Nenhuma zona térmica ACPI legível.' }
    } catch { $warnings += 'Temperatura ACPI indisponível; não foi substituída por uma leitura de CPU/GPU.' }
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
$power = $null
if ($null -ne $HostInfo) {
    try { $power = Get-FolegoPowerState $DataRoot $HostInfo } catch { $notes.Add([string]$_) }
}
$actionResult = ''
switch ($Action) {
    'Economy' { if ($null -eq $HostInfo) { throw 'Identifique o host antes de alterar energia.' }; $actionResult = Invoke-FolegoPower $DataRoot $HostInfo Economy }
    'Restore' { if ($null -eq $HostInfo) { throw 'Identifique o host antes de restaurar.' }; $actionResult = Invoke-FolegoPower $DataRoot $HostInfo Restore }
    'Reconcile' { if ($null -eq $HostInfo) { throw 'Identifique o host antes de reconciliar.' }; $actionResult = Repair-FolegoPowerReceipt $DataRoot $HostInfo }
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
try { $activePlan = Get-FolegoActivePlan } catch { $activePlan = 'indisponível'; $notes.Add([string]$_) }
if ($null -ne $HostInfo) { try { $power = Get-FolegoPowerState $DataRoot $HostInfo } catch { $notes.Add([string]$_) } }
return [pscustomobject]@{ Sample = $sample; HostInfo = $HostInfo; Extended = $Extended; Power = $power; Plan = $activePlan; Action = $Action; Result = $actionResult; Notes = @($notes) }
