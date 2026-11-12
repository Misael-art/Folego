# Native Windows policy, storage and reversible actions. No Forms dependency.
$script:FolegoRoot = $PSScriptRoot
$script:BalancedPlan = '381b4222-f694-41f0-9685-ff5bb260df2e'
$script:EconomyPlan = 'a1841308-3541-4fab-bc81-f71556f20b4a'
$script:PerformancePlan = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'

function Get-FolegoValue($Object, [string]$Name, $Default = $null) {
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    return $Default
}
function Set-FolegoValue($Object, [string]$Name, $Value) { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force }
function Read-FolegoJson([string]$Path) {
    if (-not [IO.File]::Exists($Path)) { return $null }
    if ((Get-Item -LiteralPath $Path).Length -gt 1MB) { throw 'Estado excessivo. Preserve-o para revisão; nenhuma alteração foi feita.' }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop)
}
function Write-FolegoJson([string]$Path, $Value) {
    [IO.Directory]::CreateDirectory((Split-Path $Path -Parent)) | Out-Null
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 20))
        $stream = New-Object IO.FileStream($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, [Management.Automation.Language.NullString]::Value) }
        else { [IO.File]::Move($temporary, $Path) }
    } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
}
function Get-FolegoSettings([string]$DataRoot) {
    $value = Read-FolegoJson (Join-Path $DataRoot 'settings.json')
    if ($null -eq $value) { return [pscustomobject]@{ schema = 1; startup = $true; commissioned = $false } }
    if (($value.schema -isnot [int] -and $value.schema -isnot [long]) -or $value.schema -ne 1 -or $value.startup -isnot [bool] -or $value.commissioned -isnot [bool]) { throw 'Configuração desconhecida ou incompleta. Início e efeitos preservados para revisão.' }
    return $value
}
function Get-FolegoHost {
    $product = Get-CimInstance Win32_ComputerSystemProduct -OperationTimeoutSec 3 -ErrorAction Stop
    $computer = Get-CimInstance Win32_ComputerSystem -OperationTimeoutSec 3 -ErrorAction Stop
    $os = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 3 -ErrorAction Stop
    if (-not $product.UUID -or $product.UUID -match '^0{8}-|^F{8}-' -or -not $os.LastBootUpTime) { throw 'Identidade física/boot não comprovada.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $id = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(([string]$product.UUID + '|' + $computer.Manufacturer + '|' + $computer.Model))))).Replace('-', '').Substring(0, 20) }
    finally { $sha.Dispose() }
    return [pscustomobject]@{ Id = $id; Boot = $os.LastBootUpTime.ToUniversalTime().ToString('o'); Model = [string]$computer.Model; Manufacturer = [string]$computer.Manufacturer }
}
function Get-FolegoPolicy {
    $value = Read-FolegoJson (Join-Path $script:FolegoRoot 'policy.json')
    if ($null -eq $value -or $value.schema -ne 1 -or @($value.battery_bands).Count -ne 101 -or $value.health.recovery_samples -ne 3 -or $value.windows.automatic_resource_executor -isnot [bool] -or $value.windows.automatic_resource_executor -ne $false) { throw 'Pacote incompleto ou política desconhecida. Reconstrua pelo projeto oficial.' }
    return $value
}
function Get-FolegoRawHealth($Sample, $Policy, [long]$NowMs) {
    $reasons = New-Object 'Collections.Generic.List[string]'
    if ($null -eq $Sample -or ($NowMs - $Sample.MonotonicMs) -gt ($Policy.health.stale_after_s * 1000) -or $NowMs -lt $Sample.MonotonicMs) {
        return [pscustomobject]@{ Level = 'unknown'; Text = 'Amostra ausente ou antiga. Atualização em andamento ou coleta interrompida.' }
    }
    $rank = 0; $unknown = $false
    if ($Sample.TotalPhysical -gt 0) {
        $fraction = [double]$Sample.AvailablePhysical / $Sample.TotalPhysical
        if ($fraction -le $Policy.health.red_available_frac) { $rank = 2; $reasons.Add('RAM disponível abaixo de 10%. Salve o trabalho e reduza sua concorrência.') }
        elseif ($fraction -le $Policy.health.yellow_available_frac) { $rank = 1; $reasons.Add('RAM disponível abaixo de 20%. Adie instalações e builds concorrentes.') }
    } else { $unknown = $true; $reasons.Add('RAM desconhecida.') }
    if ($Sample.CommitLimit -gt 0) {
        $fraction = [double]$Sample.CommitUsed / $Sample.CommitLimit
        if ($fraction -ge $Policy.windows.commit_critical) { $rank = 2; $reasons.Add('Memória comprometida perto do limite de commit.') }
        elseif ($fraction -ge $Policy.windows.commit_attention) { $rank = [Math]::Max($rank, 1); $reasons.Add('Uso elevado do limite de commit.') }
    } else { $unknown = $true; $reasons.Add('Limite de commit desconhecido.') }
    if ($null -ne $Sample.CpuPercent) {
        if ($Sample.CpuPercent -ge $Policy.windows.cpu_critical) { $rank = 2; $reasons.Add('CPU muito ocupada. Aguarde antes de iniciar outra carga pesada.') }
        elseif ($Sample.CpuPercent -ge $Policy.windows.cpu_attention) { $rank = [Math]::Max($rank, 1); $reasons.Add('CPU ocupada.') }
    } else { $unknown = $true; $reasons.Add('CPU aguardando duas amostras válidas.') }
    if ($null -ne $Sample.DiskTotal -and $Sample.DiskTotal -gt 0 -and $null -ne $Sample.DiskAvailable) {
        $free = [double]$Sample.DiskAvailable / $Sample.DiskTotal
        if ($free -le $Policy.windows.disk_free_critical) { $rank = 2; $reasons.Add('Menos de 10% livre no volume da aplicação.') }
        elseif ($free -le $Policy.windows.disk_free_attention) { $rank = [Math]::Max($rank, 1); $reasons.Add('Margem de espaço abaixo de 20%.') }
    } else { $unknown = $true; $reasons.Add('Espaço livre desconhecido.') }
    if ($Sample.Errors.Count) { $unknown = $true; foreach ($errorText in $Sample.Errors) { $reasons.Add($errorText) } }
    $level = if ($rank -eq 2) { 'red' } elseif ($rank -eq 1) { 'yellow' } elseif ($unknown) { 'unknown' } else { 'green' }
    if (-not $reasons.Count) { $reasons.Add('Há margem nos recursos observados. Sensores ausentes continuam sem leitura.') }
    return [pscustomobject]@{ Level = $level; Text = ($reasons -join "`r`n") }
}
function Update-FolegoHealth($State, [string]$Raw, [int]$RecoverySamples) {
    if ($Raw -notin @('green', 'yellow', 'red', 'unknown')) { throw 'Estado de saúde desconhecido.' }
    $rank = @{ green = 0; yellow = 1; red = 2 }
    if ($Raw -eq 'unknown' -or $State.Level -eq 'unknown' -or $rank[$Raw] -ge $rank[$State.Level]) { $State.Level = $Raw; $State.Candidate = ''; $State.Streak = 0 }
    else {
        if ($State.Candidate -eq $Raw) { $State.Streak++ } else { $State.Candidate = $Raw; $State.Streak = 1 }
        if ($State.Streak -ge $RecoverySamples) { $State.Level = $Raw; $State.Streak = 0; $State.Candidate = '' }
    }
    return $State.Level
}
function Get-FolegoExtendedHealth($Extended, $Policy, [long]$NowMs) {
    $level = 'unknown'; $messages = @()
    if ($null -eq $Extended -or $NowMs - $Extended.Mono -gt 90000 -or $NowMs -lt $Extended.Mono) { return [pscustomobject]@{ Level = $level; Text = 'Sensores/contadores detalhados sem amostra recente.' } }
    foreach ($zone in @($Extended.Thermal)) {
        if (($null -ne $zone.Critical -and $zone.Celsius -ge $zone.Critical) -or ($null -ne $zone.Passive -and $zone.Celsius -ge $zone.Passive)) {
            $level = 'red'; $messages += 'Zona ACPI atingiu o limite informado pelo sensor. Reduza sua carga e confira a refrigeração.'
        } elseif ($null -ne $zone.Passive -and $zone.Celsius -ge ($zone.Passive - $Policy.health.thermal_margin_c)) {
            if ($level -ne 'red') { $level = 'yellow' }; $messages += 'Zona ACPI próxima do limite passivo informado pelo sensor.'
        }
    }
    if ($Extended.VolumeHealth -eq 'Unhealthy') { $level = 'red'; $messages += 'O Windows informa volume com saúde ruim. Preserve os dados antes de manutenção.' }
    elseif ($Extended.VolumeHealth -eq 'Warning') { if ($level -ne 'red') { $level = 'yellow' }; $messages += 'O Windows informa aviso de saúde no volume; requer investigação.' }
    if ($null -ne $Extended.DiskQueue -and $Extended.DiskQueue -gt 2) {
        if ($level -ne 'red') { $level = 'yellow' }; $messages += 'Fila de disco elevada nesta amostra. Adie gravações e instalações concorrentes.'
    }
    return [pscustomobject]@{ Level = $level; Text = ($messages -join "`r`n") }
}
function Get-FolegoPowerState([string]$DataRoot, $HostInfo) {
    $path = Join-Path $DataRoot ('power-' + $HostInfo.Id + '.json')
    $state = Read-FolegoJson $path
    if ($null -eq $state) { return [pscustomobject]@{ schema = 1; enabled = $false; paused = $false; receipt = $null; requests = @(); history = @() } }
    if (($state.schema -isnot [int] -and $state.schema -isnot [long]) -or $state.schema -ne 1 -or $state.enabled -isnot [bool] -or $state.paused -isnot [bool] -or @($state.requests).Count -gt 4) { throw 'Estado de energia desconhecido. Nenhuma troca será executada.' }
    foreach ($stamp in @($state.requests)) { $null = [DateTimeOffset]::Parse([string]$stamp) }
    $receipt = $state.receipt
    if ($null -ne $receipt) {
        if ($receipt.state -notin @('intended', 'applied', 'unknown', 'restored') -or $receipt.action -notin @('Economy', 'Restore') -or $receipt.host_id -ne $HostInfo.Id -or -not $receipt.boot) { throw 'Recibo de energia inválido.' }
        $null = [Guid]::Parse($receipt.id); $null = [Guid]::Parse($receipt.original); $null = [Guid]::Parse($receipt.target)
    }
    return $state
}
function Get-FolegoActivePlan { return [Folego.Windows.Native]::ActivePlan() }
function Get-FolegoPlans { return [Folego.Windows.Native]::Plans() }
function Set-FolegoActivePlan([string]$Plan) { [Folego.Windows.Native]::SetPlan($Plan) }
function Save-FolegoPowerState([string]$DataRoot, $HostInfo, $State) { Write-FolegoJson (Join-Path $DataRoot ('power-' + $HostInfo.Id + '.json')) $State }
function Assert-FolegoAutomaticPower([string]$Action) {
    $fresh = (New-Object Folego.Windows.Native).Read([IO.Path]::GetPathRoot($script:FolegoRoot))
    if ($Action -eq 'Economy' -and ($fresh.ExternalPower -ne $false -or $null -eq $fresh.BatteryPercent -or $fresh.BatteryPercent -gt 10)) { throw 'A condição de bateria baixa/descarga mudou. Nenhuma repetição automática.' }
    if ($Action -eq 'Restore' -and $fresh.ExternalPower -ne $true) { throw 'A energia externa não está mais comprovada.' }
}
function Invoke-FolegoPower([string]$DataRoot, $HostInfo, [ValidateSet('Economy', 'Restore')][string]$Action, [switch]$Automatic) {
    $lock = [IO.File]::Open((Join-Path $DataRoot 'operation.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        $fresh = Get-FolegoHost
        if ($fresh.Id -ne $HostInfo.Id -or $fresh.Boot -ne $HostInfo.Boot) { throw 'Host/boot mudou. Atualize antes de executar.' }
        $state = Get-FolegoPowerState $DataRoot $HostInfo
        if ($Automatic -and -not $state.enabled) { throw 'Proteção automática não habilitada.' }
        if ($state.paused -or ($null -ne $state.receipt -and $state.receipt.state -in @('intended', 'unknown'))) { throw 'Resultado anterior incerto. Reconcilie o recibo; não há repetição automática.' }
        $current = Get-FolegoActivePlan
        if ($Action -eq 'Restore') {
            $old = $state.receipt
            if ($null -eq $old -or $old.state -ne 'applied' -or $old.boot -ne $HostInfo.Boot -or $current -ne $old.target) { throw 'Restauração bloqueada: outro plano/boot foi observado ou não há recibo aplicado.' }
            $target = $old.original
        } else {
            if ($current -eq $script:EconomyPlan) { return 'Economia já está ativa; nenhum plano foi alterado.' }
            if ($current -notin @($script:BalancedPlan, $script:PerformancePlan)) { throw 'Plano personalizado/desconhecido preservado. Use as opções do responsável pela energia.' }
            if ($null -ne $state.receipt -and $state.receipt.state -eq 'applied') { throw 'Restaure ou revise a operação anterior primeiro.' }
            $target = $script:EconomyPlan
        }
        if ($target -notin @(Get-FolegoPlans)) { throw 'O fabricante não oferece o plano solicitado. Ele não será criado nem duplicado.' }
        $requests = @($state.requests | Where-Object { [DateTimeOffset]::Parse([string]$_) -gt [DateTimeOffset]::UtcNow.AddHours(-1) })
        if ($requests.Count -ge 4) { throw 'Orçamento de quatro trocas por hora atingido. Aguarde; não haverá repetição.' }
        if ((Get-FolegoActivePlan) -ne $current) { throw 'Outro programa alterou o plano. Ele foi preservado.' }
        if ($Automatic) { Assert-FolegoAutomaticPower $Action }
        $receipt = [pscustomobject]@{ id = [Guid]::NewGuid().ToString(); host_id = $HostInfo.Id; boot = $HostInfo.Boot; original = $current; target = $target; state = 'intended'; action = $Action; at = [DateTimeOffset]::UtcNow.ToString('o') }
        if ($null -ne $state.receipt) { Set-FolegoValue $state history @((@(Get-FolegoValue $state history @()) + @($state.receipt)) | Select-Object -Last 12) }
        $state.receipt = $receipt; $state.requests = @($requests) + @($receipt.at)
        Save-FolegoPowerState $DataRoot $HostInfo $state
        try {
            if ((Get-FolegoActivePlan) -ne $current) { throw 'Plano mudou após registrar intenção.' }
            if ($Automatic) { Assert-FolegoAutomaticPower $Action }
            Set-FolegoActivePlan $target
            if ((Get-FolegoActivePlan) -ne $target) { throw 'O Windows não confirmou o plano solicitado.' }
            $receipt.state = if ($Action -eq 'Restore') { 'restored' } else { 'applied' }
            Save-FolegoPowerState $DataRoot $HostInfo $state
        } catch {
            $receipt.state = 'unknown'; $state.paused = $true
            Save-FolegoPowerState $DataRoot $HostInfo $state
            throw
        }
        return 'Plano confirmado pelo Windows. Operação: ' + $receipt.id
    } finally { $lock.Dispose() }
}
function Repair-FolegoPowerReceipt([string]$DataRoot, $HostInfo) {
    $state = Get-FolegoPowerState $DataRoot $HostInfo
    $r = $state.receipt
    if ($null -eq $r) { return 'Não há recibo de energia.' }
    if ($r.boot -ne $HostInfo.Boot) { throw 'Recibo de outro boot: preserve-o para revisão. Não será restaurado automaticamente.' }
    $active = Get-FolegoActivePlan
    if ($active -eq $r.target) { $r.state = if ($r.action -eq 'Restore') { 'restored' } else { 'applied' } }
    elseif ($active -eq $r.original) { $r.state = 'restored' }
    else { throw 'Plano diferente do original e do alvo. Preserve o recibo e revise o responsável pela alteração.' }
    $state.paused = $false
    Save-FolegoPowerState $DataRoot $HostInfo $state
    return 'Recibo reconciliado por leitura; nenhuma troca foi repetida.'
}
function Get-FolegoStartupCommand {
    $exe = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
    return '"' + $exe + '" -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $script:FolegoRoot 'Folego.ps1') + '" -StartMinimized -DelaySeconds 30'
}
function Get-FolegoStartupValue {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    if (-not (Test-Path -LiteralPath $key -ErrorAction Stop)) { return $null }
    $registry = Get-Item -LiteralPath $key -ErrorAction Stop
    if ($registry.GetValueNames() -notcontains 'Folego') { return $null }
    return [string]$registry.GetValue('Folego', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
}
function Set-FolegoStartup([string]$DataRoot, [bool]$Enabled) {
    $settings = Get-FolegoSettings $DataRoot
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $current = Get-FolegoStartupValue
    $command = Get-FolegoStartupCommand
    if ($null -ne $current -and $current -cne $command) { throw 'A entrada Folego existente não pertence a esta instalação. Ela foi preservada.' }
    $settings.startup = $Enabled
    Write-FolegoJson (Join-Path $DataRoot 'settings.json') $settings
    if ($Enabled) { New-Item -Path $key -Force | Out-Null; New-ItemProperty -LiteralPath $key -Name Folego -Value $command -PropertyType String -Force | Out-Null }
    elseif ($null -ne $current) { Remove-ItemProperty -LiteralPath $key -Name Folego -ErrorAction Stop }
    $settings.commissioned = $true
    Write-FolegoJson (Join-Path $DataRoot 'settings.json') $settings
    return 'Início com a sessão: ' + $Enabled + '. Aplicativos abertos e serviços do sistema foram preservados.'
}
function Install-FolegoShortcuts {
    $shell = New-Object -ComObject WScript.Shell
    $powershell = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $script:FolegoRoot 'Folego.ps1') + '"'
    foreach ($directory in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        $path = Join-Path $directory 'Fôlego.lnk'
        if (Test-Path -LiteralPath $path) {
            $old = $shell.CreateShortcut($path)
            if ($old.TargetPath -cne $powershell -or $old.Arguments -cne $arguments) { throw 'Atalho personalizado Fôlego preservado: ' + $path }
        }
        $link = $shell.CreateShortcut($path); $link.TargetPath = $powershell; $link.Arguments = $arguments
        $link.WorkingDirectory = $script:FolegoRoot; $link.IconLocation = (Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\shell32.dll') + ',21'
        $link.Save()
    }
}
function Save-FolegoSample([string]$DataRoot, $Value) {
    # One bounded latest sample per user, at most once per minute from the UI.
    Write-FolegoJson (Join-Path $DataRoot 'latest-sample.json') $Value
}
