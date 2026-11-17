# Serialized logon: items the user adopts leave Windows' parallel autostart (the same
# reversible StartupApproved mechanism, with receipts) and Fôlego launches them one at a
# time, each only after a calm reading. No Forms dependency; pure rules first.

function Split-FolegoCommand([string]$Command) {
    # Run-key command -> file + arguments, as the shell would. Environment variables expand.
    $text = [Environment]::ExpandEnvironmentVariables($Command.Trim())
    if (-not $text) { throw 'Comando vazio.' }
    if ($text.StartsWith('"')) {
        $close = $text.IndexOf('"', 1)
        if ($close -lt 2) { throw 'Comando com aspas incompletas.' }
        return [pscustomobject]@{ File = $text.Substring(1, $close - 1); Arguments = $text.Substring($close + 1).Trim() }
    }
    if ($text -match '^(?<file>.+?\.(exe|com|cmd|bat|lnk))(\s+(?<args>.*))?$') { return [pscustomobject]@{ File = $Matches['file']; Arguments = [string]$Matches['args'] } }
    return [pscustomobject]@{ File = $text; Arguments = '' }
}
function Test-FolegoCalm($Reading, $Rules) {
    # Returns the reasons that are NOT calm; empty means calm. Missing readings protect.
    $reasons = @()
    if ($null -eq $Reading.Cpu) { $reasons += 'CPU sem leitura' } elseif ($Reading.Cpu -gt [double]$Rules.cpu_max) { $reasons += ('CPU {0:N0}%' -f $Reading.Cpu) }
    if ($null -eq $Reading.DiskBusy) { $reasons += 'disco sem leitura' } elseif ($Reading.DiskBusy -gt [double]$Rules.disk_busy_max) { $reasons += ('disco {0:N0}% ocupado' -f $Reading.DiskBusy) }
    if ($null -ne $Reading.DiskQueue -and $Reading.DiskQueue -gt [double]$Rules.disk_queue_max) { $reasons += ('fila de disco ' + $Reading.DiskQueue) }
    if ($null -eq $Reading.Celsius) { $reasons += 'temperatura sem leitura' } elseif ($Reading.Celsius -ge [double]$Rules.temp_max_c) { $reasons += ('{0:N0} °C' -f $Reading.Celsius) }
    foreach ($task in @($Reading.TasksRunning)) { if ($task) { $reasons += ('tarefa de logon em execução: ' + $task) } }
    return $reasons
}
function New-FolegoSequenceRun($Keys, [long]$NowMs, $Rules) {
    return [pscustomobject]@{ Keys = @($Keys); Index = 0; CalmStreak = 0; StartMs = $NowMs + 1000 * [long]$Rules.start_after_seconds; LastLaunchMs = 0L; ItemSinceMs = 0L; SettleSinceMs = 0L; Waiting = @(); Done = $false; DoneCalm = $false; Results = @() }
}
function Step-FolegoSequence($Run, $Reading, $Rules, [long]$NowMs) {
    # Pure decision: wait | launch | skip | settle | done. One item at a time, never in parallel.
    # "Done" means every item was handled AND the system settled (calm, no logon task running),
    # or the settle phase timed out; a stuck reading can never block the end of startup.
    if ($Run.Done) { return [pscustomobject]@{ Action = 'done'; Key = ''; Reasons = @() } }
    $key = if ($Run.Index -lt @($Run.Keys).Count) { [string]@($Run.Keys)[$Run.Index] } else { '' }
    if ($NowMs -lt $Run.StartMs) { return [pscustomobject]@{ Action = 'wait'; Key = $key; Reasons = @('aguardando o desktop assentar') } }
    if (-not $key) {
        if ($Run.SettleSinceMs -eq 0) { $Run.SettleSinceMs = $NowMs }
        $reasons = @(Test-FolegoCalm $Reading $Rules); $Run.Waiting = $reasons
        if ($reasons.Count) {
            $Run.CalmStreak = 0
            if ($NowMs - $Run.SettleSinceMs -ge 1000 * [long]$Rules.item_timeout_seconds) { $Run.Done = $true; return [pscustomobject]@{ Action = 'done'; Key = ''; Reasons = $reasons } }
            return [pscustomobject]@{ Action = 'settle'; Key = ''; Reasons = $reasons }
        }
        $Run.CalmStreak++
        if ($Run.CalmStreak -ge [int]$Rules.calm_samples) { $Run.Done = $true; $Run.DoneCalm = $true; return [pscustomobject]@{ Action = 'done'; Key = ''; Reasons = @() } }
        return [pscustomobject]@{ Action = 'settle'; Key = ''; Reasons = @('confirmando calma') }
    }
    if ($Run.ItemSinceMs -eq 0) { $Run.ItemSinceMs = $NowMs }
    $reasons = @(Test-FolegoCalm $Reading $Rules)
    if ($Run.LastLaunchMs -gt 0 -and $NowMs - $Run.LastLaunchMs -lt 1000 * [long]$Rules.gap_seconds) { $reasons += 'intervalo mínimo entre itens' }
    $Run.Waiting = $reasons
    if ($reasons.Count) {
        $Run.CalmStreak = 0
        if ($NowMs - $Run.ItemSinceMs -ge 1000 * [long]$Rules.item_timeout_seconds) {
            $Run.Index++; $Run.ItemSinceMs = 0L
            return [pscustomobject]@{ Action = 'skip'; Key = $key; Reasons = $reasons }
        }
        return [pscustomobject]@{ Action = 'wait'; Key = $key; Reasons = $reasons }
    }
    $Run.CalmStreak++
    if ($Run.CalmStreak -lt [int]$Rules.calm_samples) { return [pscustomobject]@{ Action = 'wait'; Key = $key; Reasons = @('confirmando calma') } }
    $Run.CalmStreak = 0; $Run.Index++; $Run.ItemSinceMs = 0L; $Run.LastLaunchMs = $NowMs
    return [pscustomobject]@{ Action = 'launch'; Key = $key; Reasons = @() }
}

# ------------------------------------------------------------------ state and effects
function Get-FolegoSequenceState([string]$DataRoot, $HostInfo) {
    $state = Read-FolegoJson (Join-Path $DataRoot ('sequence-' + $HostInfo.Id + '.json'))
    if ($null -eq $state) { return [pscustomobject]@{ schema = 1; items = @(); last_run = $null } }
    if (-not (Test-FolegoInt $state.schema) -or $state.schema -ne 1 -or @($state.items).Count -gt 30) { throw 'Sequência de início desconhecida; nada será iniciado por ela.' }
    foreach ($item in @($state.items)) {
        if (-not $item.key -or $item.kind -notin @('run', 'folder') -or -not $item.command) { throw 'Item da sequência inválido; revise o arquivo antes de usar a sequência.' }
    }
    return $state
}
function Save-FolegoSequenceState([string]$DataRoot, $HostInfo, $State) { Write-FolegoJson (Join-Path $DataRoot ('sequence-' + $HostInfo.Id + '.json')) $State }
function Get-FolegoStartupLaunch($Item) {
    # Unredacted launch target: the Run value itself, or the shortcut path in a Startup folder.
    if ($Item.kind -eq 'dword') { return $null }
    if ($Item.scope -like 'Pasta*') {
        $folder = if ($Item.scope -eq 'PastaUsuario') { [Environment]::GetFolderPath('Startup') } else { [Environment]::GetFolderPath('CommonStartup') }
        return (Join-Path $folder $Item.name)
    }
    $keys = @{ HKCU = "HKCU:\$script:FolegoRunSubkey"; HKLM = "HKLM:\$script:FolegoRunSubkey"; HKLM32 = 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run' }
    $values = Get-FolegoRegistryValues $keys[$Item.scope]
    if (-not $values.Contains($Item.name)) { return $null }
    return [string]$values[$Item.name]
}
function Add-FolegoSequenceItem([string]$DataRoot, $HostInfo, [string]$Key, $Confirmation, $Policy) {
    Assert-FolegoConfirmation $Confirmation ('sequence-add:' + $Key) 'Add'
    $state = Get-FolegoSequenceState $DataRoot $HostInfo
    if (@($state.items | Where-Object { $_.key -ceq $Key }).Count) { return 'A entrada já está na sequência.' }
    $item = @(Get-FolegoStartupItems $Policy | Where-Object { $_.key -ceq $Key })
    if ($item.Count -ne 1) { throw 'A entrada mudou ou não existe mais; nada foi alterado.' }
    $item = $item[0]
    if ($item.protected) { throw ('Entrada preservada: ' + $item.protected) }
    if ($item.kind -eq 'dword') { throw 'Tarefas de inicialização de pacotes não podem ser iniciadas pela sequência; use a tela oficial.' }
    $launch = Get-FolegoStartupLaunch $item
    if (-not $launch) { throw 'Comando da entrada ilegível; nada foi alterado.' }
    $receipt = $null; $note = ''
    if ($item.state -eq 'enabled') {
        # Leaving Windows' parallel start is part of what the user confirmed; same receipt as the Startup tab.
        $null = Set-FolegoStartupItem $DataRoot $HostInfo $Key $false (New-FolegoConfirmation ('startup:' + $Key) 'Disable') $Policy
        $receipt = @((Get-FolegoStartupState $DataRoot $HostInfo).receipts | Where-Object { $_.key -ceq $Key -and $_.action -eq 'Disable' -and $_.state -eq 'applied' } | Select-Object -Last 1)[0].id
    } else {
        $own = @((Get-FolegoStartupState $DataRoot $HostInfo).receipts | Where-Object { $_.key -ceq $Key -and $_.action -eq 'Disable' -and $_.state -eq 'applied' } | Select-Object -Last 1)
        if ($own.Count) { $receipt = $own[0].id } else { $note = 'já estava desabilitada fora do Fôlego; ao remover, continua desabilitada' }
    }
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoSequenceState $DataRoot $HostInfo
        $row = [pscustomobject]@{ key = $item.key; name = $item.name; scope = $item.scope; app = $item.app; kind = $(if ($item.scope -like 'Pasta*') { 'folder' } else { 'run' }); command = $launch; receipt = $receipt; note = $note; added_at = [DateTimeOffset]::UtcNow.ToString('o') }
        $state.items = @(@($state.items) + @($row))
        Save-FolegoSequenceState $DataRoot $HostInfo $state
    } finally { $lock.Dispose() }
    return ($item.name + ' entrou na sequência de início: o Windows não o inicia mais em paralelo; o Fôlego o inicia em série, com calma.' + $(if ($note) { ' (' + $note + ')' } else { '' }))
}
function Remove-FolegoSequenceItem([string]$DataRoot, $HostInfo, [string]$Key, $Confirmation, [switch]$KeepAdoptable) {
    Assert-FolegoConfirmation $Confirmation ('sequence-remove:' + $Key) 'Remove'
    $state = Get-FolegoSequenceState $DataRoot $HostInfo
    $row = @($state.items | Where-Object { $_.key -ceq $Key })
    if (-not $row.Count) { return 'A entrada não está na sequência.' }
    if ($row[0].receipt) {
        # Give the item back to Windows first; a blocked restore keeps it in the sequence.
        $null = Restore-FolegoStartupItem $DataRoot $HostInfo $row[0].receipt (New-FolegoConfirmation ('startup-restore:' + $row[0].receipt) 'Restore')
    }
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoSequenceState $DataRoot $HostInfo
        $state.items = @($state.items | Where-Object { $_.key -cne $Key })
        # A user who gives an item back keeps that choice: automatic adoption skips it from now on.
        if (-not $KeepAdoptable) { Set-FolegoValue $state excluded @(@(@(Get-FolegoValue $state excluded @()) + @($Key)) | Select-Object -Unique) }
        Save-FolegoSequenceState $DataRoot $HostInfo $state
    } finally { $lock.Dispose() }
    return ($row[0].name + ' saiu da sequência' + $(if ($row[0].receipt) { ' e voltou a iniciar pelo Windows.' } else { '; o estado no Windows não foi alterado.' }))
}
function Move-FolegoSequenceItem([string]$DataRoot, $HostInfo, [string]$Key, [int]$Offset) {
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoSequenceState $DataRoot $HostInfo
        $items = New-Object 'Collections.Generic.List[object]'; foreach ($i in @($state.items)) { $items.Add($i) }
        $at = -1; for ($n = 0; $n -lt $items.Count; $n++) { if ($items[$n].key -ceq $Key) { $at = $n } }
        $to = $at + $Offset
        if ($at -lt 0 -or $to -lt 0 -or $to -ge $items.Count) { return 'Ordem mantida.' }
        $moving = $items[$at]; $items.RemoveAt($at); $items.Insert($to, $moving)
        $state.items = @($items.ToArray())
        Save-FolegoSequenceState $DataRoot $HostInfo $state
    } finally { $lock.Dispose() }
    return 'Ordem da sequência atualizada.'
}
function Start-FolegoSequenceProcess([string]$File, [string]$Arguments) {
    $directory = if ([IO.Path]::IsPathRooted($File)) { Split-Path $File -Parent } else { [Environment]::GetFolderPath('UserProfile') }
    $process = if ($Arguments) { Start-Process -FilePath $File -ArgumentList $Arguments -WorkingDirectory $directory -PassThru } else { Start-Process -FilePath $File -WorkingDirectory $directory -PassThru }
    if ($null -eq $process) { return $null }
    return $process.Id
}
function Invoke-FolegoSequenceLaunch([string]$DataRoot, $HostInfo, [string]$Key, $Policy) {
    # Revalidate at the act: still adopted, still off in Windows, same command as adopted.
    $state = Get-FolegoSequenceState $DataRoot $HostInfo
    $row = @($state.items | Where-Object { $_.key -ceq $Key })
    if (-not $row.Count) { return [pscustomobject]@{ State = 'skipped'; Detail = 'saiu da sequência' } }
    $row = $row[0]
    $item = @(Get-FolegoStartupItems $Policy | Where-Object { $_.key -ceq $Key })
    if (-not $item.Count) { return [pscustomobject]@{ State = 'skipped'; Detail = 'a entrada não existe mais' } }
    if ($item[0].state -ne 'disabled') { return [pscustomobject]@{ State = 'skipped'; Detail = 'o Windows voltou a iniciá-la sozinho; não será duplicada' } }
    $launch = Get-FolegoStartupLaunch $item[0]
    if ($launch -cne $row.command) { return [pscustomobject]@{ State = 'skipped'; Detail = 'o comando mudou desde a adoção; revise antes de iniciar' } }
    try {
        $parts = if ($row.kind -eq 'folder') { [pscustomobject]@{ File = $launch; Arguments = '' } } else { Split-FolegoCommand $launch }
        $processId = Start-FolegoSequenceProcess $parts.File $parts.Arguments
        return [pscustomobject]@{ State = 'launched'; Detail = ('PID ' + $processId) }
    } catch { return [pscustomobject]@{ State = 'failed'; Detail = [string]$_.Exception.Message } }
}
function Save-FolegoSequenceResult([string]$DataRoot, $HostInfo, [string]$Key, [string]$State, [string]$Detail) {
    $lock = Open-FolegoLock $DataRoot
    try {
        $seq = Get-FolegoSequenceState $DataRoot $HostInfo
        $run = $seq.last_run
        if ($null -eq $run -or $run.boot -ne $HostInfo.Boot) { $run = [pscustomobject]@{ boot = $HostInfo.Boot; at = [DateTimeOffset]::UtcNow.ToString('o'); results = @() } }
        $run.results = @(@(@($run.results) + @([pscustomobject]@{ key = $Key; state = $State; detail = $Detail; at = [DateTimeOffset]::UtcNow.ToString('o') })) | Select-Object -Last 30)
        Set-FolegoValue $seq last_run $run
        Save-FolegoSequenceState $DataRoot $HostInfo $seq
    } finally { $lock.Dispose() }
}
function Get-FolegoDiskBusy {
    # Localized-safe CIM class; _Total over physical disks (the card is the system disk).
    $disk = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'" -OperationTimeoutSec 3 -ErrorAction Stop
    return [pscustomobject]@{ Busy = [double](100 - [Math]::Min(100, [double]$disk.PercentIdleTime)); Queue = [double]$disk.CurrentDiskQueueLength }
}
function Get-FolegoLogonTaskNames {
    # Third-party logon tasks (the SDK's \SteamDeck tasks among them); Microsoft's own are left out.
    return @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.State -ne 'Disabled' -and $_.TaskPath -notlike '\Microsoft\*' -and @($_.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }).Count } | ForEach-Object { $_.TaskPath + $_.TaskName })
}
function Get-FolegoRunningTasks($Names) {
    # Task Scheduler COM reads state in milliseconds; the CIM cmdlet costs seconds per call.
    $running = @()
    if (-not @($Names).Count) { return $running }
    $service = New-Object -ComObject Schedule.Service
    try {
        $service.Connect()
        foreach ($name in @($Names)) {
            $cut = $name.LastIndexOf('\'); $folder = if ($cut -le 0) { '\' } else { $name.Substring(0, $cut) }
            try { if ($service.GetFolder($folder).GetTask($name.Substring($cut + 1)).State -eq 4) { $running += $name } } catch { }
        }
    } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($service) }
    return $running
}
function Get-FolegoLogonInventory($Policy) {
    # Read-only: what else starts at logon. Services and tasks are reported, never changed.
    $lines = @('Outros itens que iniciam com o Windows (somente leitura; o Fôlego não altera serviços nem tarefas):')
    try {
        foreach ($task in @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.State -ne 'Disabled' -and $_.TaskPath -notlike '\Microsoft\*' -and @($_.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }).Count })) {
            $trigger = @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' })[0]
            $lines += ('  Tarefa ' + $task.TaskPath + $task.TaskName + ' — atraso ' + $(if ($trigger.Delay) { $trigger.Delay } else { 'nenhum' }) + ', nível ' + $task.Principal.RunLevel + '; a sequência espera enquanto ela roda.')
        }
    } catch { $lines += '  Tarefas agendadas: leitura indisponível.' }
    try {
        foreach ($service in @(Get-CimInstance Win32_Service -Filter "StartMode='Auto'" -OperationTimeoutSec 5 -ErrorAction Stop | Where-Object { $_.PathName -and $_.PathName -notmatch '(?i)\\Windows\\(system32|SysWOW64)\\(svchost|lsass|services)' -and $_.PathName -notmatch '(?i)^"?[A-Z]:\\Windows\\' })) {
            $advice = if ($service.Name -in @('WinDefend', 'MDCoreSvc', 'WdNisSvc', 'Sense', 'SecurityHealthService')) { 'segurança do Windows; não alterar.' } else { 'com a orquestração ligada, o Fôlego aplica início atrasado (recibo, reversível em Opções).' }
            $lines += ('  Serviço automático ' + $service.Name + ' (' + $service.State + ', ' + (Get-FolegoServiceStart $service.Name) + '): ' + $advice)
        }
    } catch { $lines += '  Serviços: leitura indisponível.' }
    foreach ($task in @(Get-FolegoStartupItems $Policy | Where-Object { $_.kind -eq 'dword' })) { $lines += ('  Pacote ' + $task.name + ': ' + $task.state) }
    return $lines
}

# ------------------------------------------------------------------ default orchestration
# Requested by the user on 17/11/2026: orchestrate logon by default, without asking first,
# showing progress and a completion message. Opt-out and one-click undo live in Options.
function Get-FolegoOrchestrationEnabled([string]$DataRoot, $Policy) {
    $settings = Read-FolegoJson (Join-Path $DataRoot 'settings.json')
    $value = Get-FolegoValue $settings orchestration $null
    if ($value -is [bool]) { return $value }
    return [bool]$Policy.windows.sequence.orchestration_default
}
function Set-FolegoOrchestration([string]$DataRoot, [bool]$Enabled) {
    $settings = Get-FolegoSettings $DataRoot
    Set-FolegoValue $settings orchestration $Enabled
    Write-FolegoJson (Join-Path $DataRoot 'settings.json') $settings
}
function Invoke-FolegoAutoAdoption([string]$DataRoot, $HostInfo, $Policy) {
    # User-scope entries Windows would start in parallel join the sequence, each with a receipt.
    # Disabled, protected, packaged, machine-scope and previously returned entries are left alone.
    $state = Get-FolegoSequenceState $DataRoot $HostInfo
    $excluded = @(Get-FolegoValue $state excluded @())
    $taken = @($state.items | ForEach-Object { $_.key })
    $adopted = @(); $notes = @()
    foreach ($item in @(Get-FolegoStartupItems $Policy)) {
        if ($item.state -ne 'enabled' -or $item.protected -or $item.kind -ne 'binary' -or $item.scope -notin @('HKCU', 'PastaUsuario')) { continue }
        if ($item.key -cin $excluded -or $item.key -cin $taken) { continue }
        try { $null = Add-FolegoSequenceItem $DataRoot $HostInfo $item.key (New-FolegoConfirmation ('sequence-add:' + $item.key) 'Add') $Policy; $adopted += $item.key }
        catch { $notes += ($item.name + ': ' + $_.Exception.Message) }
    }
    return [pscustomobject]@{ Adopted = $adopted; Notes = $notes }
}

# ------------------------------------------------------------------ services (delayed start)
$script:FolegoSecurityServices = @('WinDefend', 'MDCoreSvc', 'WdNisSvc', 'WdBoot', 'WdFilter', 'Sense', 'SecurityHealthService', 'wscsvc', 'mpssvc', 'BFE')
function Get-FolegoServiceStart([string]$Name) {
    $key = 'HKLM:\SYSTEM\CurrentControlSet\Services\' + $Name
    if (-not (Test-Path -LiteralPath $key)) { return $null }
    $values = Get-FolegoRegistryValues $key
    if (-not $values.Contains('Start')) { return $null }
    $delayed = $values.Contains('DelayedAutostart') -and [int]$values['DelayedAutostart'] -eq 1
    switch ([int]$values['Start']) { 2 { if ($delayed) { return 'delayed-auto' } else { return 'auto' } } 3 { return 'demand' } 4 { return 'disabled' } default { return 'other' } }
}
function Set-FolegoServiceStart([string]$Name, [string]$Mode) {
    $exe = Join-Path ([Environment]::GetFolderPath('System')) 'sc.exe'
    $process = Start-Process -FilePath $exe -ArgumentList @('config', $Name, 'start=', $Mode) -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw ('sc.exe config ' + $Name + ' devolveu ' + $process.ExitCode) }
}
function Get-FolegoServiceCandidates {
    # Third-party automatic services outside the Windows folder; security components never.
    return @(Get-CimInstance Win32_Service -Filter "StartMode='Auto'" -OperationTimeoutSec 5 -ErrorAction Stop | Where-Object {
        $_.PathName -and $_.PathName -notmatch '(?i)^"?[A-Z]:\\Windows\\' -and $_.Name -notin $script:FolegoSecurityServices -and $_.PathName -notmatch '(?i)Windows Defender|Microsoft Security Client'
    } | ForEach-Object { [string]$_.Name })
}
function Get-FolegoServiceState([string]$DataRoot, $HostInfo) {
    $state = Read-FolegoJson (Join-Path $DataRoot ('services-' + $HostInfo.Id + '.json'))
    if ($null -eq $state) { return [pscustomobject]@{ schema = 1; attempted = $null; receipts = @() } }
    if (-not (Test-FolegoInt $state.schema) -or $state.schema -ne 1 -or @($state.receipts).Count -gt 60) { throw 'Estado de serviços desconhecido; nada será alterado.' }
    foreach ($r in @($state.receipts)) { if ($r.state -notin @('intended', 'applied', 'unknown', 'restored') -or $r.name -in $script:FolegoSecurityServices) { throw 'Recibo de serviço inválido.' } }
    return $state
}
function Save-FolegoServiceState([string]$DataRoot, $HostInfo, $State) { Write-FolegoJson (Join-Path $DataRoot ('services-' + $HostInfo.Id + '.json')) $State }
function Set-FolegoServiceDelays([string]$DataRoot, $HostInfo, $Names) {
    # Elevated, once: automatic -> automatic (delayed start). Services still start, after the login peak.
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoServiceState $DataRoot $HostInfo
        Set-FolegoValue $state attempted ([DateTimeOffset]::UtcNow.ToString('o'))
        $done = @()
        foreach ($name in @($Names)) {
            if ($name -in $script:FolegoSecurityServices) { continue }
            $original = Get-FolegoServiceStart $name
            if ($original -ne 'auto') { continue }
            $receipt = [pscustomobject]@{ id = [Guid]::NewGuid().ToString(); name = $name; original = $original; target = 'delayed-auto'; state = 'intended'; at = [DateTimeOffset]::UtcNow.ToString('o') }
            $state.receipts = @(@(@($state.receipts) + @($receipt)) | Select-Object -Last 60)
            Save-FolegoServiceState $DataRoot $HostInfo $state
            try {
                Set-FolegoServiceStart $name 'delayed-auto'
                $receipt.state = if ((Get-FolegoServiceStart $name) -eq 'delayed-auto') { 'applied' } else { 'unknown' }
            } catch { $receipt.state = 'unknown' }
            Save-FolegoServiceState $DataRoot $HostInfo $state
            $done += ($name + '=' + $receipt.state)
        }
        Save-FolegoServiceState $DataRoot $HostInfo $state
        return ('Início atrasado: ' + $(if ($done.Count) { $done -join ', ' } else { 'nenhum serviço automático de terceiros a ajustar' }))
    } finally { $lock.Dispose() }
}
function Restore-FolegoServiceDelays([string]$DataRoot, $HostInfo) {
    # Elevated: back to automatic only where the value is still the one Fôlego wrote.
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoServiceState $DataRoot $HostInfo
        $out = @()
        foreach ($r in @($state.receipts | Where-Object { $_.state -in @('applied', 'unknown') })) {
            $current = Get-FolegoServiceStart $r.name
            if ($current -ne $r.target) { $out += ($r.name + ': alterado por outro; preservado'); continue }
            try { Set-FolegoServiceStart $r.name $r.original; $r.state = if ((Get-FolegoServiceStart $r.name) -eq $r.original) { 'restored' } else { 'unknown' } } catch { $r.state = 'unknown' }
            $out += ($r.name + '=' + $r.state)
        }
        Save-FolegoServiceState $DataRoot $HostInfo $state
        return ('Serviços: ' + $(if ($out.Count) { $out -join ', ' } else { 'nada a restaurar' }))
    } finally { $lock.Dispose() }
}
function Save-FolegoSequenceDone([string]$DataRoot, $HostInfo, $Summary) {
    $lock = Open-FolegoLock $DataRoot
    try {
        $seq = Get-FolegoSequenceState $DataRoot $HostInfo
        $run = $seq.last_run
        if ($null -eq $run -or $run.boot -ne $HostInfo.Boot) { $run = [pscustomobject]@{ boot = $HostInfo.Boot; at = [DateTimeOffset]::UtcNow.ToString('o'); results = @() } }
        Set-FolegoValue $run done_at ([DateTimeOffset]::UtcNow.ToString('o'))
        Set-FolegoValue $run summary ([string]$Summary)
        Set-FolegoValue $seq last_run $run
        Save-FolegoSequenceState $DataRoot $HostInfo $seq
    } finally { $lock.Dispose() }
}
function Format-FolegoElapsed([double]$Seconds) {
    $span = [TimeSpan]::FromSeconds([Math]::Max(0, [Math]::Floor($Seconds)))
    if ($span.TotalHours -ge 1) { return ('{0}:{1:00}:{2:00}' -f [int][Math]::Floor($span.TotalHours), $span.Minutes, $span.Seconds) }
    return ('{0:00}:{1:00}' -f $span.Minutes, $span.Seconds)
}
