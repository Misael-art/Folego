# Active, reversible management: thermal profiles, process triage and startup approval.
# No Forms dependency. Every effect: durable intent -> revalidation -> effect -> readback.
# Nothing here touches EC/SMU/TDP/fans, services, policies or system packages.
$script:SubProcessor = '54533251-82be-4824-96c1-47b60b740d00'
$script:ThrottleMaxSetting = 'bc5038f7-23e0-4960-96da-33abaf5935ec'
$script:BoostModeSetting = 'be337238-0d82-4146-a960-4f3749d470c7'
$script:ThermalActions = @('Fresco', 'Contencao', 'Restore')

function Test-FolegoInt($Value) { return ($Value -is [int] -or $Value -is [long]) }
function Assert-FolegoConfirmation($Confirmation, [string]$Subject, [string]$Mode) {
    # Confirmation objects exist only after an explicit dialog answer in the UI.
    if ($null -eq $Confirmation -or (Get-FolegoValue $Confirmation subject '') -cne $Subject -or (Get-FolegoValue $Confirmation mode '') -cne $Mode) {
        throw 'Confirmação explícita do usuário ausente ou de outro item. Nada foi alterado.'
    }
    $at = [DateTimeOffset]::Parse([string](Get-FolegoValue $Confirmation at ''))
    if ([DateTimeOffset]::UtcNow - $at -gt [TimeSpan]::FromSeconds(120) -or $at -gt [DateTimeOffset]::UtcNow.AddSeconds(5)) {
        throw 'Confirmação expirada. Revise o item novamente; nada foi alterado.'
    }
}
function New-FolegoConfirmation([string]$Subject, [string]$Mode) {
    return [pscustomobject]@{ subject = $Subject; mode = $Mode; at = [DateTimeOffset]::UtcNow.ToString('o') }
}
function Open-FolegoLock([string]$DataRoot) {
    [IO.Directory]::CreateDirectory($DataRoot) | Out-Null
    return [IO.File]::Open((Join-Path $DataRoot 'operation.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
}
function Assert-FolegoSameHost($HostInfo, [switch]$IgnoreBoot) {
    $fresh = Get-FolegoHost
    if ($fresh.Id -ne $HostInfo.Id -or (-not $IgnoreBoot -and $fresh.Boot -ne $HostInfo.Boot)) { throw 'Host/boot mudou. Atualize antes de executar.' }
}
function Get-FolegoRecentRequests($Requests) {
    return @(@($Requests) | Where-Object { $null -ne $_ -and [DateTimeOffset]::Parse([string]$_) -gt [DateTimeOffset]::UtcNow.AddHours(-1) })
}

# ---------------------------------------------------------------- thermal guard
function Get-FolegoPowerSetting([string]$Scheme, [string]$Setting, [bool]$Ac) { return [int][Folego.Windows.Native]::ReadSetting($Scheme, $script:SubProcessor, $Setting, $Ac) }
function Set-FolegoPowerSetting([string]$Scheme, [string]$Setting, [bool]$Ac, [int]$Value) { [Folego.Windows.Native]::WriteSetting($Scheme, $script:SubProcessor, $Setting, $Ac, [uint32]$Value) }
function Update-FolegoActiveScheme([string]$Scheme) { [Folego.Windows.Native]::SetPlan($Scheme) }
function Get-FolegoThermalValues([string]$Scheme) {
    return [pscustomobject]@{
        ac_throttle = Get-FolegoPowerSetting $Scheme $script:ThrottleMaxSetting $true
        dc_throttle = Get-FolegoPowerSetting $Scheme $script:ThrottleMaxSetting $false
        ac_boost = Get-FolegoPowerSetting $Scheme $script:BoostModeSetting $true
        dc_boost = Get-FolegoPowerSetting $Scheme $script:BoostModeSetting $false
    }
}
function Test-FolegoThermalValues($Values) {
    if ($null -eq $Values) { return $false }
    foreach ($name in @('ac_throttle', 'dc_throttle')) { $v = Get-FolegoValue $Values $name; if (-not (Test-FolegoInt $v) -or $v -lt 1 -or $v -gt 100) { return $false } }
    foreach ($name in @('ac_boost', 'dc_boost')) { $v = Get-FolegoValue $Values $name; if (-not (Test-FolegoInt $v) -or $v -lt 0 -or $v -gt 6) { return $false } }
    return $true
}
function Test-FolegoSameThermal($Left, $Right) {
    foreach ($name in @('ac_throttle', 'dc_throttle', 'ac_boost', 'dc_boost')) { if ([int](Get-FolegoValue $Left $name -1) -ne [int](Get-FolegoValue $Right $name -2)) { return $false } }
    return $true
}
function Format-FolegoThermalValues($Values) {
    $boost = @{ 0 = 'desligado'; 1 = 'ligado'; 2 = 'agressivo'; 3 = 'eficiente'; 4 = 'eficiente agressivo'; 5 = 'agressivo garantido'; 6 = 'eficiente agressivo garantido' }
    return ('CPU máx. {0}% tomada / {1}% bateria; turbo {2} / {3}' -f $Values.ac_throttle, $Values.dc_throttle, $boost[[int]$Values.ac_boost], $boost[[int]$Values.dc_boost])
}
function Get-FolegoThermalState([string]$DataRoot, $HostInfo) {
    $state = Read-FolegoJson (Join-Path $DataRoot ('thermal-' + $HostInfo.Id + '.json'))
    if ($null -eq $state) { return [pscustomobject]@{ schema = 1; enabled = $false; paused = $false; receipt = $null; requests = @(); history = @() } }
    if (-not (Test-FolegoInt $state.schema) -or $state.schema -ne 1 -or $state.enabled -isnot [bool] -or $state.paused -isnot [bool] -or @($state.requests).Count -gt 8 -or @($state.history).Count -gt 12) { throw 'Estado térmico desconhecido. Nenhum perfil será trocado.' }
    foreach ($stamp in @($state.requests)) { $null = [DateTimeOffset]::Parse([string]$stamp) }
    $r = $state.receipt
    if ($null -ne $r) {
        if ($r.state -notin @('intended', 'applied', 'unknown', 'restored') -or $r.action -notin $script:ThermalActions -or $r.host_id -ne $HostInfo.Id -or -not $r.boot -or $r.automatic -isnot [bool]) { throw 'Recibo térmico inválido.' }
        $null = [Guid]::Parse($r.id); $null = [Guid]::Parse($r.scheme)
        if (-not (Test-FolegoThermalValues $r.original) -or -not (Test-FolegoThermalValues $r.target) -or -not (Test-FolegoThermalValues $r.previous)) { throw 'Recibo térmico com valores inválidos.' }
    }
    return $state
}
function Save-FolegoThermalState([string]$DataRoot, $HostInfo, $State) { Write-FolegoJson (Join-Path $DataRoot ('thermal-' + $HostInfo.Id + '.json')) $State }
function Get-FolegoThermalProfile($State, $HostInfo) {
    # Normal = no applied receipt. Manual/foreign receipts are never changed automatically.
    $r = $State.receipt
    if ($null -eq $r -or $r.state -eq 'restored') { return 'Normal' }
    if ($r.state -ne 'applied' -or $r.boot -ne $HostInfo.Boot -or -not $r.automatic) { return 'Manual' }
    return [string]$r.action
}
function Invoke-FolegoThermal([string]$DataRoot, $HostInfo, [ValidateSet('Fresco', 'Contencao', 'Restore')][string]$Action, $Policy, [switch]$Automatic, $Trigger) {
    $thermal = $Policy.windows.thermal
    $lock = Open-FolegoLock $DataRoot
    try {
        Assert-FolegoSameHost $HostInfo
        $state = Get-FolegoThermalState $DataRoot $HostInfo
        if ($Automatic -and -not $state.enabled) { throw 'Guarda térmica automática não habilitada.' }
        if ($state.paused -or ($null -ne $state.receipt -and $state.receipt.state -in @('intended', 'unknown'))) { throw 'Resultado térmico anterior incerto. Confira o recibo; não há repetição automática.' }
        $old = $state.receipt
        $applied = $null -ne $old -and $old.state -eq 'applied'
        if ($applied -and $old.boot -ne $HostInfo.Boot) { throw 'Perfil aplicado em outro boot. Revise os valores e adote o recibo manualmente antes de outra troca.' }
        if ($Action -eq 'Restore') {
            if (-not $applied) { throw 'Não há perfil aplicado pelo Fôlego para restaurar.' }
            if ($Automatic -and -not $old.automatic) { throw 'Perfil escolhido manualmente não é desfeito automaticamente.' }
            $scheme = [string]$old.scheme; $original = $old.original; $target = $old.original
        } else {
            $scheme = Get-FolegoActivePlan
            $preset = Get-FolegoValue $thermal.profiles $Action
            $target = [pscustomobject]@{ ac_throttle = [int]$preset.throttle_max; dc_throttle = [int]$preset.throttle_max; ac_boost = [int]$preset.boost_mode; dc_boost = [int]$preset.boost_mode }
            if ($applied) {
                if ($Automatic -and -not $old.automatic) { throw 'Perfil manual preservado; a guarda automática não o substitui.' }
                if ($old.scheme -ne $scheme) { throw 'O plano ativo mudou desde o perfil aplicado. Restaure no plano registrado primeiro.' }
                $original = $old.original
            }
        }
        $current = Get-FolegoThermalValues $scheme
        if (-not (Test-FolegoThermalValues $current)) { throw 'Valores atuais do processador fora do esperado; nada foi alterado.' }
        if ($applied -and -not (Test-FolegoSameThermal $current $old.target)) { throw 'Outro programa alterou os limites do processador depois do Fôlego. Os valores dele foram preservados; o recibo continua para revisão.' }
        if (-not $applied) { $original = $current }
        if (Test-FolegoSameThermal $current $target) { return 'Os limites já estão nesse perfil; nada foi alterado.' }
        $requests = @(Get-FolegoRecentRequests $state.requests)
        if ($requests.Count -ge [int]$thermal.max_switches_per_hour) { throw ('Orçamento de ' + $thermal.max_switches_per_hour + ' trocas térmicas por hora atingido. O perfil atual foi mantido.') }
        $receipt = [pscustomobject]@{ id = [Guid]::NewGuid().ToString(); host_id = $HostInfo.Id; boot = $HostInfo.Boot; scheme = $scheme; action = $Action; automatic = [bool]$Automatic; original = $original; previous = $current; target = $target; state = 'intended'; at = [DateTimeOffset]::UtcNow.ToString('o'); trigger = $Trigger }
        if ($null -ne $old) { Set-FolegoValue $state history @((@($state.history) + @($old)) | Select-Object -Last 12) }
        $state.receipt = $receipt; $state.requests = @($requests) + @($receipt.at)
        Save-FolegoThermalState $DataRoot $HostInfo $state
        try {
            if (-not (Test-FolegoSameThermal (Get-FolegoThermalValues $scheme) $current)) { throw 'Os limites mudaram após registrar a intenção.' }
            Set-FolegoPowerSetting $scheme $script:ThrottleMaxSetting $true $target.ac_throttle
            Set-FolegoPowerSetting $scheme $script:ThrottleMaxSetting $false $target.dc_throttle
            Set-FolegoPowerSetting $scheme $script:BoostModeSetting $true $target.ac_boost
            Set-FolegoPowerSetting $scheme $script:BoostModeSetting $false $target.dc_boost
            if ((Get-FolegoActivePlan) -eq $scheme) { Update-FolegoActiveScheme $scheme }
            if (-not (Test-FolegoSameThermal (Get-FolegoThermalValues $scheme) $target)) { throw 'O Windows não confirmou os limites solicitados.' }
            $receipt.state = if ($Action -eq 'Restore') { 'restored' } else { 'applied' }
            Save-FolegoThermalState $DataRoot $HostInfo $state
        } catch {
            $receipt.state = 'unknown'; $state.paused = $true
            Save-FolegoThermalState $DataRoot $HostInfo $state
            throw
        }
        $verb = if ($Action -eq 'Restore') { 'Valores originais restaurados' } else { 'Perfil ' + $Action + ' confirmado' }
        return ($verb + ' por leitura: ' + (Format-FolegoThermalValues $target) + '. Operação ' + $receipt.id)
    } finally { $lock.Dispose() }
}
function Repair-FolegoThermalReceipt([string]$DataRoot, $HostInfo) {
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoThermalState $DataRoot $HostInfo
        $r = $state.receipt
        if ($null -eq $r) { return 'Não há recibo térmico.' }
        if ($r.boot -ne $HostInfo.Boot) { throw 'Recibo térmico de outro boot: use Adotar recibo após conferir os valores.' }
        $current = Get-FolegoThermalValues $r.scheme
        if (Test-FolegoSameThermal $current $r.target) { $r.state = if ($r.action -eq 'Restore') { 'restored' } else { 'applied' } }
        elseif (Test-FolegoSameThermal $current $r.original) { $r.state = 'restored' }
        elseif (Test-FolegoSameThermal $current $r.previous) { $r.target = $r.previous; $r.state = 'applied'; Set-FolegoValue $r reconciled 'previous-profile-kept' }
        else { throw 'Limites diferentes do original, do anterior e do alvo. Preserve o recibo e revise quem os alterou.' }
        $state.paused = $false
        Save-FolegoThermalState $DataRoot $HostInfo $state
        return 'Recibo térmico reconciliado por leitura; nenhuma troca foi repetida.'
    } finally { $lock.Dispose() }
}
function Confirm-FolegoThermalBoot([string]$DataRoot, $HostInfo, $Confirmation) {
    # Power settings survive reboots. A foreign-boot receipt is adopted only manually,
    # after the user saw the values, and only if nobody changed them since.
    Assert-FolegoConfirmation $Confirmation 'thermal-adopt' 'Adopt'
    $lock = Open-FolegoLock $DataRoot
    try {
        Assert-FolegoSameHost $HostInfo
        $state = Get-FolegoThermalState $DataRoot $HostInfo
        $r = $state.receipt
        if ($null -eq $r -or $r.state -ne 'applied' -or $r.boot -eq $HostInfo.Boot) { throw 'Não há recibo aplicado de outro boot para adotar.' }
        if (-not (Test-FolegoSameThermal (Get-FolegoThermalValues $r.scheme) $r.target)) { throw 'Os limites atuais diferem do recibo; ele foi preservado sem adoção.' }
        Set-FolegoValue $r adopted_from_boot $r.boot; $r.boot = $HostInfo.Boot; $r.automatic = $false
        Save-FolegoThermalState $DataRoot $HostInfo $state
        return 'Recibo adotado neste boot como escolha manual; Restaurar agora pode devolver os valores originais.'
    } finally { $lock.Dispose() }
}
function Set-FolegoThermalGuard([string]$DataRoot, $HostInfo, [bool]$Enabled, $Confirmation) {
    if ($Enabled) { Assert-FolegoConfirmation $Confirmation 'thermal-guard' 'Enable' }
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoThermalState $DataRoot $HostInfo
        if ($Enabled -and ($state.paused -or ($null -ne $state.receipt -and $state.receipt.state -in @('intended', 'unknown')))) { throw 'Reconcilie o recibo térmico antes de habilitar a guarda.' }
        $state.enabled = $Enabled
        Save-FolegoThermalState $DataRoot $HostInfo $state
    } finally { $lock.Dispose() }
    if ($Enabled) { return 'Guarda térmica automática habilitada neste hardware. Amostragem a cada 5 s enquanto ativa.' }
    return 'Guarda térmica desabilitada. Os limites atuais não foram trocados; use Restaurar se houver recibo.'
}
function New-FolegoThermalGuard { return [pscustomobject]@{ Window = @(); CoolStreak = 0; Recent = @() } }
function Step-FolegoThermalGuard($Guard, $Celsius, $Thermal, [string]$Level, [long]$NowMs = 0) {
    # Pure hysteresis. Unknown temperature never triggers an effect and resets evidence.
    if ($null -eq $Celsius) { $Guard.Window = @(); $Guard.CoolStreak = 0; return 'None' }
    $c = [double]$Celsius
    $Guard.Recent = @(@(@($Guard.Recent) + @([pscustomobject]@{ Mono = $NowMs; Celsius = $c })) | Where-Object { $NowMs - $_.Mono -le 600000 } | Select-Object -Last 240)
    $Guard.Window = @(@(@($Guard.Window) + @($c)) | Select-Object -Last ([int]$Thermal.raise_samples))
    $average = $null
    if ($Guard.Window.Count -ge [int]$Thermal.raise_samples) { $average = (@($Guard.Window) | Measure-Object -Average).Average }
    $sustained = $null -ne $average -and $average -ge [double]$Thermal.raise_average_c
    if ($c -lt [double]$Thermal.recover_c) { $Guard.CoolStreak++ } else { $Guard.CoolStreak = 0 }
    switch ($Level) {
        'Normal' { if ($sustained -or $c -ge [double]$Thermal.spike_c) { $Guard.Window = @(); $Guard.CoolStreak = 0; return 'Fresco' } }
        'Fresco' {
            if ($sustained) { $Guard.Window = @(); $Guard.CoolStreak = 0; return 'Contencao' }
            if ($Guard.CoolStreak -ge [int]$Thermal.recover_samples) { $Guard.CoolStreak = 0; return 'Restore' }
        }
        'Contencao' { if ($Guard.CoolStreak -ge [int]$Thermal.recover_samples) { $Guard.CoolStreak = 0; return 'Restore' } }
    }
    return 'None'
}
function Get-FolegoThermalZones {
    # Localized-safe CIM class (pt-BR counters). Kelvin; HighPrecision is tenths of Kelvin.
    return @(Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation -OperationTimeoutSec 3 -ErrorAction Stop | ForEach-Object {
        $k = if ($_.HighPrecisionTemperature -gt 0) { [double]$_.HighPrecisionTemperature / 10 } else { [double]$_.Temperature }
        $celsius = $k - 273.15
        if ($celsius -gt -20 -and $celsius -lt 150) { [pscustomobject]@{ Name = [string]$_.Name; Celsius = [Math]::Round($celsius, 1); Passive = $null; Critical = $null } }
    })
}
function Read-FolegoMonitorCsv([string]$Path) {
    # Replay of the card's light monitor: NUL padding after a reset, decimal commas in
    # the last column and missing rows are tolerated; unreadable temperatures stay null.
    $text = [IO.File]::ReadAllText($Path).Replace([string][char]0, '')
    $rows = @()
    foreach ($line in ($text -split "`r?`n" | Select-Object -Skip 1)) {
        $cells = $line.Split(',')
        if ($cells.Count -lt 8 -or $cells[0] -notmatch '^\d{2}:\d{2}:\d{2}$') { continue }
        $temp = 0.0
        $celsius = if ([double]::TryParse($cells[7], [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$temp)) { $temp } else { $null }
        $rows += [pscustomobject]@{ Time = $cells[0]; Cpu = $cells[1]; Celsius = $celsius }
    }
    return $rows
}
function Invoke-FolegoThermalReplay($Rows, $Thermal, [int]$Budget = 4) {
    # Simulates decisions only. No power API is called.
    $guard = New-FolegoThermalGuard; $level = 'Normal'; $events = @(); $used = 0; $index = 0
    foreach ($row in @($Rows)) {
        $index++
        $decision = Step-FolegoThermalGuard $guard $row.Celsius $Thermal $level ([long]$index * 5000)
        if ($decision -eq 'None') { continue }
        if ($used -ge $Budget) { $events += [pscustomobject]@{ Time = $row.Time; Celsius = $row.Celsius; Decision = $decision; Result = 'budget' }; continue }
        $used++
        $level = if ($decision -eq 'Restore') { 'Normal' } else { $decision }
        $events += [pscustomobject]@{ Time = $row.Time; Celsius = $row.Celsius; Decision = $decision; Result = 'applied' }
    }
    return $events
}

# ---------------------------------------------------------------- processes
function Get-FolegoProcessSnapshot { return @([Folego.Windows.Native]::Processes()) }
function Get-FolegoCommandLines {
    $map = @{}
    foreach ($row in @(Get-CimInstance Win32_Process -Property ProcessId, CommandLine -OperationTimeoutSec 5 -ErrorAction Stop)) { $map[[int]$row.ProcessId] = [string]$row.CommandLine }
    return $map
}
function Test-FolegoSameProcess([int]$ProcessId, [long]$StartTicks) { return [Folego.Windows.Native]::IsSameProcess($ProcessId, $StartTicks) }
function Invoke-FolegoGentleClose([int]$ProcessId) {
    # taskkill without the force switch: WM_CLOSE to the app windows. Console-only processes refuse.
    $exe = Join-Path ([Environment]::GetFolderPath('System')) 'taskkill.exe'
    $process = Start-Process -FilePath $exe -ArgumentList @('/PID', [string]$ProcessId) -WindowStyle Hidden -PassThru -Wait
    return $process.ExitCode
}
function Stop-FolegoProcessForce([int]$ProcessId, [long]$StartTicks) { [Folego.Windows.Native]::TerminateSame($ProcessId, $StartTicks) }
function Test-FolegoInstallerMutex {
    $mutex = $null
    try { if ([Threading.Mutex]::TryOpenExisting('Global\_MSIExecute', [ref]$mutex)) { return $true } }
    catch [UnauthorizedAccessException] { return $true }
    finally { if ($null -ne $mutex) { $mutex.Dispose() } }
    return $false
}
function Protect-FolegoCommandLine([string]$Text) {
    if (-not $Text) { return '' }
    $t = $Text -replace '(?i)(--?(token|api[-_]?key|key|secret|password|passwd|pwd|auth|authorization|cookie|session)[= :]+)("[^"]*"|\S+)', '$1<oculto>'
    $t = $t -replace '(?i)\b(bearer)\s+\S+', '$1 <oculto>'
    $t = $t -replace '\b(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|xox[abpr]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,})', '<oculto>'
    $t = $t -replace '[A-Za-z0-9+/_=-]{40,}', '<oculto>'
    if ($t.Length -gt 180) { $t = $t.Substring(0, 177) + '...' }
    return $t
}
function Get-FolegoProcessRules([string]$DataRoot, $Policy) {
    $rules = $Policy.windows.processes
    $agents = @($rules.agent_names); $protected = @($rules.protected_names)
    $custom = Read-FolegoJson (Join-Path $DataRoot 'process-rules.json')
    if ($null -ne $custom) {
        if (-not (Test-FolegoInt $custom.schema) -or $custom.schema -ne 1) { throw 'process-rules.json com schema desconhecido; triagem bloqueada até revisão.' }
        foreach ($field in @('agent_names', 'protected_names')) {
            foreach ($name in @(Get-FolegoValue $custom $field @())) { if ([string]$name -notmatch '^[A-Za-z0-9._ -]{1,64}$') { throw ('Nome inválido em process-rules.json: ' + $name) } }
        }
        $agents += @(Get-FolegoValue $custom agent_names @()); $protected += @(Get-FolegoValue $custom protected_names @())
    }
    $normalize = { param($items) @($items | ForEach-Object { ([string]$_).ToLowerInvariant() -replace '\.exe$', '' } | Select-Object -Unique) }
    return [pscustomobject]@{ Agents = (& $normalize $agents); Protected = (& $normalize $protected) }
}
function Get-FolegoProcessTree($Rows, [int]$RootPid) {
    # Ancestors (validated by creation time) and descendants of the given process.
    $byPid = @{}; foreach ($row in $Rows) { $byPid[[int]$row.Pid] = $row }
    $set = @{}; $set[$RootPid] = $true
    $cursor = $byPid[$RootPid]; $guard = 0
    while ($null -ne $cursor -and $guard -lt 64) {
        $parent = $byPid[[int]$cursor.ParentPid]
        if ($null -eq $parent -or $parent.Pid -eq $cursor.Pid -or ($parent.StartTicks -gt 0 -and $cursor.StartTicks -gt 0 -and $parent.StartTicks -gt $cursor.StartTicks)) { break }
        $set[[int]$parent.Pid] = $true; $cursor = $parent; $guard++
    }
    # Descendants of the root only (never siblings through a shared ancestor).
    $down = @{}; $down[$RootPid] = $true
    $changed = $true; $rounds = 0
    while ($changed -and $rounds -lt 64) {
        $changed = $false; $rounds++
        foreach ($row in $Rows) {
            if ($down.ContainsKey([int]$row.Pid)) { continue }
            $parent = $byPid[[int]$row.ParentPid]
            if ($null -ne $parent -and $parent.Pid -ne $row.Pid -and $down.ContainsKey([int]$parent.Pid) -and $parent.StartTicks -le $row.StartTicks) { $down[[int]$row.Pid] = $true; $changed = $true }
        }
    }
    foreach ($key in $down.Keys) { $set[$key] = $true }
    return $set
}
function Get-FolegoProcessTriage($First, $Second, [double]$ElapsedMs, $Commands, $Rules, $Context, $Policy) {
    # Pure classification. Name, age, missing parent or low CPU never authorize an effect alone:
    # they only make a row eligible for an explicit, revalidated user confirmation.
    $settings = $Policy.windows.processes
    $before = @{}; foreach ($row in @($First)) { $before[[string]$row.Pid + ':' + $row.StartTicks] = $row }
    $byPid = @{}; foreach ($row in @($Second)) { $byPid[[int]$row.Pid] = $row }
    $installerNames = @('msiexec', 'tiworker', 'trustedinstaller', 'setup', 'setuphost', 'installer', 'winget')
    $installerPids = @{}
    foreach ($row in @($Second)) { if ((([string]$row.Name).ToLowerInvariant() -replace '\.exe$', '') -in $installerNames) { $installerPids[[int]$row.Pid] = $true } }
    $installerTrees = @{}
    foreach ($installer in $installerPids.Keys) { foreach ($member in (Get-FolegoProcessTree $Second $installer).Keys) { $installerTrees[$member] = $true } }
    $result = @()
    foreach ($row in @($Second)) {
        $name = (([string]$row.Name).ToLowerInvariant() -replace '\.exe$', '')
        $reasons = @()
        if ($row.Pid -le 4) { $reasons += 'núcleo do sistema' }
        elseif ($null -eq $row.SessionId -or $row.SessionId -eq 0) { $reasons += 'sessão de serviços/sistema' }
        if (-not $row.OwnerSid) { $reasons += 'dono não comprovado' }
        elseif ($row.OwnerSid -ne $Context.UserSid) { $reasons += 'outro usuário ou sistema' }
        if (-not $row.Path -or -not $row.Queried) { $reasons += 'caminho/início não legível' }
        if ($name -in $Rules.Protected) { $reasons += 'protegido pela lista' }
        if ($Context.SelfTree.ContainsKey([int]$row.Pid)) { $reasons += 'Fôlego ou a sessão que o iniciou' }
        $command = [string]$Commands[[int]$row.Pid]
        if ($command -match '(?i)Folego\.ps1') { $reasons += 'instância do Fôlego' }
        if ($installerTrees.ContainsKey([int]$row.Pid)) { $reasons += 'árvore de instalador ativo' }
        if ($Context.InstallerActive) { $reasons += 'instalação do Windows em andamento' }
        $parent = $byPid[[int]$row.ParentPid]
        $parentAlive = $null -ne $parent -and $parent.Pid -ne $row.Pid -and ($parent.StartTicks -le $row.StartTicks -or $parent.StartTicks -eq 0)
        $agent = $name -in $Rules.Agents
        $prior = $before[[string]$row.Pid + ':' + $row.StartTicks]
        $cores = $null; $ioKbps = $null
        if ($null -ne $prior -and $ElapsedMs -gt 0) {
            $cores = [Math]::Round([double]($row.CpuTicks - $prior.CpuTicks) / ($ElapsedMs * 10000), 2)
            $ioKbps = [Math]::Round(([double]($row.ReadBytes - $prior.ReadBytes) + [double]($row.WriteBytes - $prior.WriteBytes)) / 1024 / ($ElapsedMs / 1000), 1)
        }
        $ageMin = if ($row.StartTicks -gt 0) { [Math]::Round(($Context.NowTicks - $row.StartTicks) / 600000000, 1) } else { $null }
        $idleMin = $null
        $idle = $Context.Idle[[string]$row.Pid + ':' + $row.StartTicks]
        if ($null -ne $idle -and [long]$idle.cpu -eq $row.CpuTicks) { $idleMin = [Math]::Round(($Context.NowTicks - [long]$idle.since) / 600000000, 1) }
        $class = 'consumidor'; $notes = @()
        if ($reasons.Count) { $class = 'protegido' }
        elseif ($agent -and ($parentAlive -or $row.HasWindow)) { $class = 'protegido'; $reasons += 'agente com responsável vivo ou janela' }
        elseif ($agent) {
            $class = 'agente-orfao'; $notes += 'pai encerrado'
            if ($null -ne $cores -and $cores -ge [double]$settings.busy_cores) { $notes += 'em loop/ocupado' }
            if ($null -ne $idleMin -and $idleMin -ge [double]$settings.orphan_idle_minutes) { $notes += ('ocioso há ' + $idleMin + ' min') }
        }
        $result += [pscustomobject]@{
            id = [Guid]::NewGuid().ToString(); pid = [int]$row.Pid; start = [long]$row.StartTicks; name = [string]$row.Name; path = [string]$row.Path
            owner = [string]$row.OwnerSid; parent_pid = [int]$row.ParentPid; parent_alive = [bool]$parentAlive; has_window = [bool]$row.HasWindow
            cores = $cores; io_kbps = $ioKbps; age_min = $ageMin; idle_min = $idleMin; class = $class
            killable = ($class -in @('agente-orfao', 'consumidor'))
            reasons = @($reasons + $notes); command = (Protect-FolegoCommandLine $command)
        }
    }
    return $result
}
function Get-FolegoProcessGroups($Triage) {
    return @($Triage | Group-Object { ([string]$_.name).ToLowerInvariant() } | ForEach-Object {
        [pscustomobject]@{ name = $_.Name; count = $_.Count; cores = [Math]::Round((@($_.Group | Where-Object { $null -ne $_.cores } | Measure-Object cores -Sum).Sum) + 0, 2); io_kbps = [Math]::Round((@($_.Group | Where-Object { $null -ne $_.io_kbps } | Measure-Object io_kbps -Sum).Sum) + 0, 1) }
    } | Sort-Object cores, io_kbps -Descending)
}
function Get-FolegoProcessState([string]$DataRoot, $HostInfo) {
    $state = Read-FolegoJson (Join-Path $DataRoot ('processes-' + $HostInfo.Id + '.json'))
    if ($null -eq $state) { return [pscustomobject]@{ schema = 1; receipts = @(); idle = @() } }
    if (-not (Test-FolegoInt $state.schema) -or $state.schema -ne 1 -or @($state.receipts).Count -gt 20 -or @($state.idle).Count -gt 200) { throw 'Estado de processos desconhecido; nenhuma ação será executada.' }
    foreach ($r in @($state.receipts)) { if ($r.state -notin @('intended', 'ended', 'still-running', 'gentle-refused', 'unknown') -or $r.mode -notin @('Gentle', 'Force')) { throw 'Recibo de processo inválido.' } }
    return $state
}
function Save-FolegoProcessState([string]$DataRoot, $HostInfo, $State) { Write-FolegoJson (Join-Path $DataRoot ('processes-' + $HostInfo.Id + '.json')) $State }
function Get-FolegoProcessContext([string]$DataRoot, $HostInfo, $Rows) {
    $state = Get-FolegoProcessState $DataRoot $HostInfo
    $idle = @{}; foreach ($i in @($state.idle)) { $idle[[string]$i.key] = $i }
    return [pscustomobject]@{
        UserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        SelfTree = (Get-FolegoProcessTree $Rows $PID)
        InstallerActive = (Test-FolegoInstallerMutex)
        NowTicks = [DateTime]::UtcNow.ToFileTimeUtc()
        Idle = $idle
    }
}
function Invoke-FolegoProcessTriage([string]$DataRoot, $HostInfo, $Policy) {
    $rules = Get-FolegoProcessRules $DataRoot $Policy
    $first = Get-FolegoProcessSnapshot
    $watch = [Diagnostics.Stopwatch]::StartNew()
    Start-Sleep -Milliseconds ([int]$Policy.windows.processes.sample_ms)
    $second = Get-FolegoProcessSnapshot; $elapsed = $watch.Elapsed.TotalMilliseconds
    $commands = @{}; $note = ''
    try { $commands = Get-FolegoCommandLines } catch { $note = 'Linhas de comando indisponíveis; itens sem linha permanecem elegíveis só pela identidade.' }
    $context = Get-FolegoProcessContext $DataRoot $HostInfo $second
    $triage = Get-FolegoProcessTriage $first $second $elapsed $commands $rules $context $Policy
    # Bounded idle tracking for agent-named processes only (one write per manual triage).
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoProcessState $DataRoot $HostInfo
        $idle = @()
        foreach ($row in @($second | Where-Object { ((([string]$_.Name).ToLowerInvariant() -replace '\.exe$', '') -in $rules.Agents) -and $_.StartTicks -gt 0 } | Select-Object -First 200)) {
            $key = [string]$row.Pid + ':' + $row.StartTicks
            $old = $context.Idle[$key]
            $since = if ($null -ne $old -and [long]$old.cpu -eq $row.CpuTicks) { [long]$old.since } else { $context.NowTicks }
            $idle += [pscustomobject]@{ key = $key; cpu = [long]$row.CpuTicks; since = $since }
        }
        $state.idle = $idle
        Save-FolegoProcessState $DataRoot $HostInfo $state
    } finally { $lock.Dispose() }
    $top = [int]$Policy.windows.processes.top
    $shown = @(@($triage | Where-Object { $_.class -eq 'agente-orfao' }) + @($triage | Where-Object { $_.class -ne 'agente-orfao' -and ($null -ne $_.cores -or $null -ne $_.io_kbps) } | Sort-Object @{ Expression = { [double]$_.cores }; Descending = $true }, @{ Expression = { [double]$_.io_kbps }; Descending = $true } | Select-Object -First $top))
    return [pscustomobject]@{ Rows = $shown; Groups = @(Get-FolegoProcessGroups $triage | Select-Object -First 12); InstallerActive = $context.InstallerActive; Note = $note; ElapsedMs = [Math]::Round($elapsed) }
}
function Invoke-FolegoProcessAction([string]$DataRoot, $HostInfo, $Record, [ValidateSet('Gentle', 'Force')][string]$Mode, $Confirmation, $Policy) {
    if ($null -eq $Record) { throw 'Selecione um processo da triagem.' }
    Assert-FolegoConfirmation $Confirmation ('process:' + $Record.id) $Mode
    if (-not $Record.killable) { throw 'Processo protegido. Nenhum sinal foi enviado.' }
    $lock = Open-FolegoLock $DataRoot
    try {
        Assert-FolegoSameHost $HostInfo
        $state = Get-FolegoProcessState $DataRoot $HostInfo
        if ($Mode -eq 'Force') {
            $gentle = @($state.receipts | Where-Object { $_.pid -eq $Record.pid -and [long]$_.start -eq [long]$Record.start -and $_.mode -eq 'Gentle' -and $_.state -in @('still-running', 'gentle-refused') })
            if (-not $gentle.Count) { throw 'Forçar exige antes uma tentativa gentil registrada para este mesmo processo.' }
        }
        # Revalidate identity, owner and protections on a fresh snapshot, at the act.
        $rows = Get-FolegoProcessSnapshot
        $fresh = @($rows | Where-Object { $_.Pid -eq $Record.pid })
        if ($fresh.Count -ne 1 -or $fresh[0].StartTicks -ne [long]$Record.start -or [string]$fresh[0].Path -ne [string]$Record.path -or [string]$fresh[0].OwnerSid -ne [string]$Record.owner) { throw 'O processo mudou ou já terminou; nada foi encerrado.' }
        $commands = @{}; try { $commands = Get-FolegoCommandLines } catch { }
        $check = @(Get-FolegoProcessTriage $rows $rows 0 $commands (Get-FolegoProcessRules $DataRoot $Policy) (Get-FolegoProcessContext $DataRoot $HostInfo $rows) $Policy | Where-Object { $_.pid -eq $Record.pid })
        if ($check.Count -ne 1 -or -not $check[0].killable) { throw ('Revalidação protegeu o processo: ' + (@($check | ForEach-Object { $_.reasons }) -join ', ')) }
        $receipt = [pscustomobject]@{ id = [Guid]::NewGuid().ToString(); pid = [int]$Record.pid; start = [long]$Record.start; name = [string]$Record.name; path = [string]$Record.path; mode = $Mode; class = [string]$Record.class; state = 'intended'; at = [DateTimeOffset]::UtcNow.ToString('o') }
        $state.receipts = @(@(@($state.receipts) + @($receipt)) | Select-Object -Last 20)
        Save-FolegoProcessState $DataRoot $HostInfo $state
        try {
            if ($Mode -eq 'Gentle') {
                $code = Invoke-FolegoGentleClose $Record.pid
                $deadline = [DateTime]::UtcNow.AddSeconds([int]$Policy.windows.processes.wait_seconds)
                while ((Test-FolegoSameProcess $Record.pid $Record.start) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 300 }
                $receipt.state = if (-not (Test-FolegoSameProcess $Record.pid $Record.start)) { 'ended' } elseif ($code -ne 0) { 'gentle-refused' } else { 'still-running' }
            } else {
                Stop-FolegoProcessForce $Record.pid $Record.start
                $deadline = [DateTime]::UtcNow.AddSeconds([int]$Policy.windows.processes.wait_seconds)
                while ((Test-FolegoSameProcess $Record.pid $Record.start) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 200 }
                $receipt.state = if (Test-FolegoSameProcess $Record.pid $Record.start) { 'unknown' } else { 'ended' }
            }
            Save-FolegoProcessState $DataRoot $HostInfo $state
        } catch {
            $receipt.state = 'unknown'; Save-FolegoProcessState $DataRoot $HostInfo $state
            throw
        }
        $texts = @{ ended = 'encerrado e confirmado'; 'still-running' = 'ainda em execução após o pedido gentil; forçar exige nova confirmação'; 'gentle-refused' = 'recusou o pedido gentil (processo sem janela); forçar exige nova confirmação'; unknown = 'resultado incerto; nada será repetido automaticamente' }
        return ($Record.name + ' (PID ' + $Record.pid + '): ' + $texts[$receipt.state] + '. Recibo ' + $receipt.id)
    } finally { $lock.Dispose() }
}

# ---------------------------------------------------------------- startup approval
$script:FolegoRunSubkey = 'Software\Microsoft\Windows\CurrentVersion\Run'
$script:FolegoApprovedSubkey = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved'
$script:FolegoPackagedTasksKey = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData'
function Get-FolegoRegistryValues([string]$Key) {
    $map = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Key)) { return $map }
    $item = Get-Item -LiteralPath $Key -ErrorAction Stop
    foreach ($name in $item.GetValueNames()) { if ($name) { $map[$name] = $item.GetValue($name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) } }
    return $map
}
function Get-FolegoStartupFolderItems([string]$Folder) {
    if (-not $Folder -or -not (Test-Path -LiteralPath $Folder)) { return @() }
    return @(Get-ChildItem -LiteralPath $Folder -File -ErrorAction Stop | Where-Object { $_.Name -ne 'desktop.ini' } | ForEach-Object { [pscustomobject]@{ Name = $_.Name; Command = $_.FullName } })
}
function Get-FolegoPackagedStartupTasks {
    $rows = @()
    if (-not (Test-Path -LiteralPath $script:FolegoPackagedTasksKey)) { return $rows }
    foreach ($package in @(Get-ChildItem -LiteralPath $script:FolegoPackagedTasksKey -ErrorAction Stop)) {
        foreach ($task in @(Get-ChildItem -LiteralPath $package.PSPath -ErrorAction SilentlyContinue)) {
            if ($task.GetValueNames() -contains 'State') { $rows += [pscustomobject]@{ Family = $package.PSChildName; Task = $task.PSChildName; Key = ($script:FolegoPackagedTasksKey + '\' + $package.PSChildName + '\' + $task.PSChildName) } }
        }
    }
    return $rows
}
function Get-FolegoStartupRaw($Item) {
    # Canonical text: 'bin:<hex>' for StartupApproved, 'dword:<n>' for packaged tasks, null if absent.
    $values = Get-FolegoRegistryValues $Item.approved_key
    if (-not $values.Contains($Item.value_name)) { return $null }
    $value = $values[$Item.value_name]
    if ($Item.kind -eq 'dword') { return 'dword:' + [int]$value }
    if ($value -is [byte[]]) { return 'bin:' + (($value | ForEach-Object { $_.ToString('x2') }) -join '') }
    return 'other:' + [string]$value
}
function Set-FolegoStartupRaw($Item, $Raw) {
    if ($null -eq $Raw) { Remove-ItemProperty -LiteralPath $Item.approved_key -Name $Item.value_name -ErrorAction Stop; return }
    if (-not (Test-Path -LiteralPath $Item.approved_key)) { New-Item -Path $Item.approved_key -Force | Out-Null }
    if ($Raw -like 'dword:*') { New-ItemProperty -LiteralPath $Item.approved_key -Name $Item.value_name -Value ([int]$Raw.Substring(6)) -PropertyType DWord -Force | Out-Null; return }
    if ($Raw -notlike 'bin:*') { throw 'Formato de aprovação desconhecido; preservado.' }
    $hex = $Raw.Substring(4); $bytes = New-Object byte[] ($hex.Length / 2)
    for ($i = 0; $i -lt $bytes.Length; $i++) { $bytes[$i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16) }
    New-ItemProperty -LiteralPath $Item.approved_key -Name $Item.value_name -Value $bytes -PropertyType Binary -Force | Out-Null
}
function Get-FolegoStartupStateText($Item, $Raw) {
    if ($Item.kind -eq 'dword') {
        switch ($Raw) { 'dword:0' { return 'disabled' } 'dword:1' { return 'disabled' } 'dword:2' { return 'enabled' } 'dword:3' { return 'policy' } 'dword:4' { return 'policy' } default { return 'unknown' } }
    }
    if ($null -eq $Raw) { return 'enabled' }
    if ($Raw -notmatch '^bin:([0-9a-f]{2})[0-9a-f]{22}$') { return 'unknown' }
    if (([Convert]::ToByte($Matches[1], 16) -band 1) -eq 1) { return 'disabled' }
    return 'enabled'
}
function Get-FolegoStartupApp([string]$Name, [string]$Command) {
    $text = ($Name + ' ' + $Command).ToLowerInvariant()
    if ($text -match 'copilot') { return 'Copilot' }
    if ($Name -like 'MicrosoftEdgeAutoLaunch_*' -or $text -match 'msedge\.exe') { return 'Edge' }
    if ($text -match 'onedrive') { return 'OneDrive' }
    if ($text -match 'everything\.exe') { return 'Everything' }
    if ($Name -in @('Steam Deck', 'Steam Deck.lnk')) { return 'Steam Deck' }
    if ($Name -eq 'Folego' -or $text -match 'folego\.ps1') { return 'Fôlego' }
    if ($Name -eq 'SecurityHealth' -or $text -match 'securityhealthsystray') { return 'Segurança do Windows' }
    return ''
}
function Get-FolegoStartupItems($Policy) {
    $protected = @($Policy.windows.startup.protected_names)
    $sources = @(
        @{ scope = 'HKCU'; values = "HKCU:\$script:FolegoRunSubkey"; approved = "HKCU:\$script:FolegoApprovedSubkey\Run"; admin = $false },
        @{ scope = 'HKLM'; values = "HKLM:\$script:FolegoRunSubkey"; approved = "HKLM:\$script:FolegoApprovedSubkey\Run"; admin = $true },
        @{ scope = 'HKLM32'; values = 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'; approved = "HKLM:\$script:FolegoApprovedSubkey\Run32"; admin = $true },
        @{ scope = 'PastaUsuario'; folder = [Environment]::GetFolderPath('Startup'); approved = "HKCU:\$script:FolegoApprovedSubkey\StartupFolder"; admin = $false },
        @{ scope = 'PastaComum'; folder = [Environment]::GetFolderPath('CommonStartup'); approved = "HKLM:\$script:FolegoApprovedSubkey\StartupFolder"; admin = $true }
    )
    $items = @()
    foreach ($source in $sources) {
        $entries = @()
        if ($source.ContainsKey('values')) { $values = Get-FolegoRegistryValues $source.values; foreach ($name in @($values.Keys)) { $entries += [pscustomobject]@{ Name = $name; Command = [string]$values[$name] } } }
        else { $entries = Get-FolegoStartupFolderItems $source.folder }
        foreach ($entry in $entries) {
            $item = [pscustomobject]@{ key = $source.scope + '|' + $entry.Name; scope = $source.scope; name = $entry.Name; command = (Protect-FolegoCommandLine $entry.Command); kind = 'binary'; approved_key = $source.approved; value_name = $entry.Name; admin = $source.admin; app = (Get-FolegoStartupApp $entry.Name $entry.Command); state = ''; raw = $null; protected = '' }
            $items += $item
        }
    }
    foreach ($task in @(Get-FolegoPackagedStartupTasks)) {
        $items += [pscustomobject]@{ key = 'Pacote|' + $task.Family + '\' + $task.Task; scope = 'Pacote'; name = $task.Family + '\' + $task.Task; command = $task.Family; kind = 'dword'; approved_key = $task.Key; value_name = 'State'; admin = $false; app = (Get-FolegoStartupApp $task.Family ''); state = ''; raw = $null; protected = '' }
    }
    foreach ($item in $items) {
        $item.raw = Get-FolegoStartupRaw $item
        $item.state = Get-FolegoStartupStateText $item $item.raw
        if ($item.app -in @('Steam Deck', 'Fôlego')) { $item.protected = 'entrada do cartão/Fôlego preservada' }
        elseif ($item.app -eq 'Segurança do Windows') { $item.protected = 'segurança do Windows: somente a tela oficial' }
        elseif ($item.name -in $protected) { $item.protected = 'protegido pela política' }
        elseif ($item.state -in @('unknown', 'policy')) { $item.protected = 'estado desconhecido ou definido por política' }
    }
    return $items
}
function Get-FolegoStartupState([string]$DataRoot, $HostInfo) {
    $state = Read-FolegoJson (Join-Path $DataRoot ('startup-' + $HostInfo.Id + '.json'))
    if ($null -eq $state) { return [pscustomobject]@{ schema = 1; paused = $false; review = $null; receipts = @() } }
    if (-not (Test-FolegoInt $state.schema) -or $state.schema -ne 1 -or $state.paused -isnot [bool] -or @($state.receipts).Count -gt 30) { throw 'Estado de inicialização desconhecido; nada será alterado.' }
    foreach ($r in @($state.receipts)) { if ($r.state -notin @('intended', 'applied', 'unknown', 'restored') -or $r.action -notin @('Disable', 'Enable', 'Restore') -or $r.host_id -ne $HostInfo.Id) { throw 'Recibo de inicialização inválido.' }; $null = [Guid]::Parse($r.id) }
    return $state
}
function Save-FolegoStartupState([string]$DataRoot, $HostInfo, $State) { Write-FolegoJson (Join-Path $DataRoot ('startup-' + $HostInfo.Id + '.json')) $State }
function Test-FolegoElevated { return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
function New-FolegoStartupTarget($Item, [bool]$Enabled) {
    if ($Item.kind -eq 'dword') { if ($Enabled) { return 'dword:2' } else { return 'dword:1' } }
    if ($Enabled) { return 'bin:02' + ('0' * 22) }
    $stamp = [BitConverter]::GetBytes([DateTime]::UtcNow.ToFileTimeUtc())
    return 'bin:03000000' + (($stamp | ForEach-Object { $_.ToString('x2') }) -join '')
}
function Set-FolegoStartupItem([string]$DataRoot, $HostInfo, [string]$Key, [bool]$Enabled, $Confirmation, $Policy) {
    $mode = if ($Enabled) { 'Enable' } else { 'Disable' }
    Assert-FolegoConfirmation $Confirmation ('startup:' + $Key) $mode
    $lock = Open-FolegoLock $DataRoot
    try {
        # Startup approval persists across boots by design; the value itself is the evidence.
        Assert-FolegoSameHost $HostInfo -IgnoreBoot
        $state = Get-FolegoStartupState $DataRoot $HostInfo
        if ($state.paused -or @($state.receipts | Where-Object { $_.state -in @('intended', 'unknown') }).Count) { throw 'Há recibo de inicialização incerto. Confira-o antes de outra alteração.' }
        $item = @(Get-FolegoStartupItems $Policy | Where-Object { $_.key -ceq $Key })
        if ($item.Count -ne 1) { throw 'A entrada mudou ou não existe mais; nada foi alterado.' }
        $item = $item[0]
        if ($item.protected) { throw ('Entrada preservada: ' + $item.protected) }
        if ($item.admin -and -not (Test-FolegoElevated)) { throw 'ELEVATION: entrada da máquina; requer confirmação de administrador desta conta.' }
        if (($Enabled -and $item.state -eq 'enabled') -or (-not $Enabled -and $item.state -eq 'disabled')) { return ($item.name + ' já está nesse estado; nada foi alterado.') }
        $target = New-FolegoStartupTarget $item $Enabled
        $receipt = [pscustomobject]@{ id = [Guid]::NewGuid().ToString(); host_id = $HostInfo.Id; boot = $HostInfo.Boot; key = $item.key; app = $item.app; approved_key = $item.approved_key; value_name = $item.value_name; kind = $item.kind; action = $mode; original = $item.raw; target = $target; state = 'intended'; at = [DateTimeOffset]::UtcNow.ToString('o') }
        $state.receipts = @(@(@($state.receipts) + @($receipt)) | Select-Object -Last 30)
        Save-FolegoStartupState $DataRoot $HostInfo $state
        try {
            if ((Get-FolegoStartupRaw $item) -cne $item.raw) { throw 'A aprovação mudou após registrar a intenção.' }
            Set-FolegoStartupRaw $item $target
            if ((Get-FolegoStartupRaw $item) -cne $target) { throw 'O Windows não confirmou a alteração da inicialização.' }
            $receipt.state = 'applied'
            Save-FolegoStartupState $DataRoot $HostInfo $state
        } catch {
            $receipt.state = 'unknown'; $state.paused = $true; Save-FolegoStartupState $DataRoot $HostInfo $state
            throw
        }
        $word = if ($Enabled) { 'habilitada' } else { 'desabilitada pelo mesmo mecanismo das Configurações' }
        return ($item.name + ': inicialização ' + $word + '. Instâncias abertas não foram encerradas. Recibo ' + $receipt.id)
    } finally { $lock.Dispose() }
}
function Restore-FolegoStartupItem([string]$DataRoot, $HostInfo, [string]$ReceiptId, $Confirmation) {
    Assert-FolegoConfirmation $Confirmation ('startup-restore:' + $ReceiptId) 'Restore'
    $lock = Open-FolegoLock $DataRoot
    try {
        Assert-FolegoSameHost $HostInfo -IgnoreBoot
        $state = Get-FolegoStartupState $DataRoot $HostInfo
        $r = @($state.receipts | Where-Object { $_.id -eq $ReceiptId })
        if ($r.Count -ne 1 -or $r[0].state -ne 'applied' -or $r[0].action -eq 'Restore') { throw 'Recibo aplicado não encontrado.' }
        $r = $r[0]
        $item = [pscustomobject]@{ approved_key = $r.approved_key; value_name = $r.value_name; kind = $r.kind }
        if ($item.approved_key -like 'HKLM:*' -and -not (Test-FolegoElevated)) { throw 'ELEVATION: entrada da máquina; requer confirmação de administrador desta conta.' }
        $current = Get-FolegoStartupRaw $item
        if ($current -cne $r.target) { throw 'Outro programa ou as Configurações alteraram a entrada depois do Fôlego. O valor atual foi preservado.' }
        $restore = [pscustomobject]@{ id = [Guid]::NewGuid().ToString(); host_id = $HostInfo.Id; boot = $HostInfo.Boot; key = $r.key; app = $r.app; approved_key = $r.approved_key; value_name = $r.value_name; kind = $r.kind; action = 'Restore'; original = $current; target = $r.original; restores = $r.id; state = 'intended'; at = [DateTimeOffset]::UtcNow.ToString('o') }
        $state.receipts = @(@(@($state.receipts) + @($restore)) | Select-Object -Last 30)
        Save-FolegoStartupState $DataRoot $HostInfo $state
        try {
            Set-FolegoStartupRaw $item $r.original
            if ((Get-FolegoStartupRaw $item) -cne $r.original) { throw 'O Windows não confirmou a restauração.' }
            $restore.state = 'applied'; $r.state = 'restored'
            Save-FolegoStartupState $DataRoot $HostInfo $state
        } catch {
            $restore.state = 'unknown'; $state.paused = $true; Save-FolegoStartupState $DataRoot $HostInfo $state
            throw
        }
        return ('Estado original de ' + $r.key + ' restaurado e confirmado por leitura.')
    } finally { $lock.Dispose() }
}
function Repair-FolegoStartupReceipts([string]$DataRoot, $HostInfo) {
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoStartupState $DataRoot $HostInfo
        foreach ($r in @($state.receipts | Where-Object { $_.state -in @('intended', 'unknown') })) {
            $current = Get-FolegoStartupRaw ([pscustomobject]@{ approved_key = $r.approved_key; value_name = $r.value_name; kind = $r.kind })
            if ($current -ceq $r.target) { $r.state = 'applied' }
            elseif ($current -ceq $r.original) { $r.state = 'restored' }
            else { throw ('Entrada ' + $r.key + ' difere do original e do alvo; preserve o recibo e revise.') }
        }
        $state.paused = $false
        Save-FolegoStartupState $DataRoot $HostInfo $state
        return 'Recibos de inicialização reconciliados por leitura; nada foi repetido.'
    } finally { $lock.Dispose() }
}
function Compare-FolegoStartupReview($Items, $Review) {
    if ($null -eq $Review) { return @('Sem revisão anterior: todas as entradas abaixo são a linha de base.') }
    $old = @{}; foreach ($i in @($Review.items)) { $old[[string]$i.key] = $i }
    $now = @{}; foreach ($i in @($Items)) { $now[[string]$i.key] = $i }
    $lines = @()
    foreach ($i in @($Items)) {
        if (-not $old.ContainsKey($i.key)) { $lines += ('NOVA: ' + $i.key + ' -> ' + $i.command) }
        elseif ($old[$i.key].command -cne $i.command) { $lines += ('COMANDO ALTERADO: ' + $i.key) }
        elseif ($old[$i.key].state -cne $i.state) { $lines += ('ESTADO ALTERADO: ' + $i.key + ' ' + $old[$i.key].state + ' -> ' + $i.state) }
    }
    foreach ($key in $old.Keys) { if (-not $now.ContainsKey($key)) { $lines += ('REMOVIDA: ' + $key) } }
    if (-not $lines.Count) { $lines = @('Nenhuma mudança desde a revisão de ' + $Review.at + '.') }
    return $lines
}
function Save-FolegoStartupReview([string]$DataRoot, $HostInfo, $Items) {
    $lock = Open-FolegoLock $DataRoot
    try {
        $state = Get-FolegoStartupState $DataRoot $HostInfo
        Set-FolegoValue $state review ([pscustomobject]@{ at = [DateTimeOffset]::UtcNow.ToString('o'); items = @($Items | Select-Object key, command, state) })
        Save-FolegoStartupState $DataRoot $HostInfo $state
    } finally { $lock.Dispose() }
    return 'Revisão registrada; próximas mudanças serão destacadas.'
}
function Get-FolegoCopilotReport($Items, $Commands) {
    $lines = @()
    $installed = Test-Path -LiteralPath (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Copilot\Application')
    $entries = @($Items | Where-Object { $_.app -eq 'Copilot' })
    $lines += ('App desktop Copilot instalado: ' + $installed + '. Entradas de início: ' + $entries.Count)
    foreach ($e in $entries) { $lines += ('  ' + $e.key + ' [' + $e.state + ']') }
    $running = @($Commands.Keys | Where-Object { [string]$Commands[$_] -match '(?i)copilot(app)?\.exe' })
    $session = @($running | Where-Object { [string]$Commands[$_] -match '--win-session-start' })
    $lines += ('Instâncias em execução: ' + $running.Count + ' (iniciadas com a sessão: ' + $session.Count + ')')
    if (-not $entries.Count -and $session.Count) { $lines += 'A instância veio da sessão, mas não há entrada visível agora: o app pode recriá-la ao iniciar. Revise após o próximo login.' }
    $lines += 'Desinstalação: use a tela oficial Aplicativos instalados (o desinstalador é do sistema e pede administrador).'
    return $lines
}
function Get-FolegoSystemLoadReport {
    # Detect-only. Services, Update, Delivery Optimization, Defender and UAC are never changed here.
    $lines = @('Itens de sistema/segurança: somente detecção; use a página oficial correspondente.')
    foreach ($name in @('wuauserv', 'UsoSvc', 'DoSvc', 'BITS', 'WSearch', 'WinDefend')) {
        try { $s = Get-Service -Name $name -ErrorAction Stop; $lines += ('  {0} ({1}): {2}' -f $s.DisplayName, $name, $s.Status) } catch { $lines += ('  ' + $name + ': estado indisponível') }
    }
    return $lines
}
