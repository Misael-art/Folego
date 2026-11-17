# Isolated contracts, including on Windows: effect APIs are mocked below.
param([string]$PolicyPath, [string[]]$ReplayCsv)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Folego.Core.ps1')
Set-StrictMode -Version 2
$script:Checks = 0
$script:Replay = @()
function Check([bool]$Value, [string]$Message) { if (-not $Value) { throw ('FAIL: ' + $Message) }; $script:Checks++ }
function Reject([scriptblock]$Operation, [string]$Message) { $failed = $false; try { & $Operation | Out-Null } catch { $failed = $true }; Check $failed $Message }
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('folego-windows-tests-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($fixture) | Out-Null
try {
    foreach ($file in @('Folego.ps1', 'Folego.Core.ps1', 'Folego.Manage.ps1', 'Folego.View.ps1', 'Folego.Widget.ps1', 'Collect.ps1', 'Test-Folego.ps1', 'DeckBootstrap.ps1')) {
        $tokens = $null; $errors = $null
        $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file), [ref]$tokens, [ref]$errors)
        Check ($errors.Count -eq 0) ('Syntax ' + $file + ': ' + ($errors | Out-String))
    }
    Add-Type -Path @((Join-Path $PSScriptRoot 'Native.cs'), (Join-Path $PSScriptRoot 'Widget.cs')) -ReferencedAssemblies System.Windows.Forms, System.Drawing
    Check ($null -ne ('Folego.Windows.Native' -as [type])) 'Native C# backend compiles; no Win32 call made by compilation'
    $policy = if ($PolicyPath) { Read-FolegoJson $PolicyPath } else { Get-FolegoPolicy }
    $sample = [pscustomobject]@{ MonotonicMs = 1000L; TotalPhysical = 16GB; AvailablePhysical = 8GB; CommitLimit = 20GB; CommitUsed = 8GB; CpuPercent = 15; DiskAvailable = 30GB; DiskTotal = 120GB; Errors = @() }
    Check ((Get-FolegoRawHealth $sample $policy 1000).Level -eq 'green') 'Healthy known resources'
    Check ((Get-FolegoRawHealth $sample $policy 20000).Level -eq 'unknown') 'Old sample never becomes green'
    $sample.CpuPercent = $null
    Check ((Get-FolegoRawHealth $sample $policy 1000).Level -eq 'unknown') 'Missing CPU is unknown'
    $sample.CpuPercent = 15; $sample.AvailablePhysical = 1GB
    Check ((Get-FolegoRawHealth $sample $policy 1000).Level -eq 'red') 'Shared RAM critical threshold'
    $sample.AvailablePhysical = 8GB; $sample.CommitUsed = 19.5GB
    Check ((Get-FolegoRawHealth $sample $policy 1000).Level -eq 'red') 'Commit pressure distinct from RAM'
    $stabilizer = [pscustomobject]@{ Level = 'red'; Candidate = ''; Streak = 0 }
    $null = Update-FolegoHealth $stabilizer green 3; $null = Update-FolegoHealth $stabilizer green 3
    Check ($stabilizer.Level -eq 'red') 'Two good samples do not erase pressure'
    Check ((Update-FolegoHealth $stabilizer green 3) -eq 'green') 'Three good samples recover'
    $extended = [pscustomobject]@{ Mono = 1000L; Thermal = @([pscustomobject]@{ Celsius = 100; Passive = 100; Critical = 105 }); VolumeHealth = 'Healthy'; DiskQueue = 0 }
    Check ((Get-FolegoExtendedHealth $extended $policy 1000).Level -eq 'red') 'Thermal limit comes from sensor'
    $extended.Thermal[0].Passive = $null; $extended.Thermal[0].Critical = $null
    Check ((Get-FolegoExtendedHealth $extended $policy 1000).Level -eq 'unknown') 'No invented thermal threshold'
    $extended.VolumeHealth = 'Warning'
    Check ((Get-FolegoExtendedHealth $extended $policy 1000).Level -eq 'yellow') 'Windows volume warning preserved'
    Check ((Get-FolegoExtendedHealth $extended $policy 100000).Level -eq 'unknown') 'Old disk/sensor detail ignored'
    $settings = Get-FolegoSettings $fixture
    Check ($settings.startup -and -not $settings.commissioned) 'Startup defaults on without treating it as already installed'
    Write-FolegoJson (Join-Path $fixture 'settings.json') ([pscustomobject]@{ schema = 99; startup = $true; commissioned = $false })
    Reject { Get-FolegoSettings $fixture } 'Unknown settings block mutation'
    Write-FolegoJson (Join-Path $fixture 'settings.json') ([pscustomobject]@{ schema = 1; startup = $false; commissioned = $true; preserve = 42 })
    Check ((Get-FolegoSettings $fixture).preserve -eq 42) 'Atomic writes preserve unrelated fields'

    Check ((Get-FolegoIdentitySeed '4C4C4544-0000-1111-2222-333344445555' 'ABC123' '') -eq '4C4C4544-0000-1111-2222-333344445555') 'Valid SMBIOS UUID keeps the previous identity'
    Check ((Get-FolegoIdentitySeed 'FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF' 'FVAA12345678' 'X') -eq 'bios:FVAA12345678') 'Placeholder UUID falls back to the BIOS serial'
    Check ((Get-FolegoIdentitySeed '00000000-0000-0000-0000-000000000000' 'Default string' 'MB98765432') -eq 'board:MB98765432') 'Placeholder BIOS serial falls back to the board serial'
    Reject { Get-FolegoIdentitySeed 'FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF' 'To be filled by O.E.M.' '0000' } 'No proven physical identity blocks effects'
    $hostInfo = [pscustomobject]@{ Id = 'fixture-host'; Boot = 'fixture-boot' }
    function Get-FolegoHost { return $hostInfo }
    $script:Active = $script:BalancedPlan; $script:Effects = @(); $script:FailConfirmation = $false
    function Get-FolegoActivePlan { return $script:Active }
    function Get-FolegoPlans { return @($script:BalancedPlan, $script:EconomyPlan, $script:PerformancePlan) }
    function Set-FolegoActivePlan([string]$Plan) {
        $receipt = (Get-FolegoPowerState $fixture $hostInfo).receipt
        Check ($receipt.state -eq 'intended' -and $receipt.target -eq $Plan) 'Durable intent precedes native effect'
        $script:Effects += $Plan
        if (-not $script:FailConfirmation) { $script:Active = $Plan }
    }
    $power = Get-FolegoPowerState $fixture $hostInfo
    Check (-not $power.enabled) 'Automatic Windows charge guard starts opt-in'
    Reject { Invoke-FolegoPower $fixture $hostInfo Economy -Automatic } 'Automatic effect requires own enablement'
    $null = Invoke-FolegoPower $fixture $hostInfo Economy
    Check ($script:Active -eq $script:EconomyPlan -and (Get-FolegoPowerState $fixture $hostInfo).receipt.state -eq 'applied') 'Economy confirmed by readback'
    $script:Active = $script:PerformancePlan
    Reject { Invoke-FolegoPower $fixture $hostInfo Restore } 'Other application plan change protected'
    $script:Active = $script:EconomyPlan
    $null = Invoke-FolegoPower $fixture $hostInfo Restore
    Check ($script:Active -eq $script:BalancedPlan) 'Original plan restored with same host/boot'
    $script:FailConfirmation = $true
    Reject { Invoke-FolegoPower $fixture $hostInfo Economy } 'Unconfirmed effect reported as failure'
    $power = Get-FolegoPowerState $fixture $hostInfo
    Check ($power.paused -and $power.receipt.state -eq 'unknown') 'Uncertain result pauses further effects'
    $count = $script:Effects.Count
    Reject { Invoke-FolegoPower $fixture $hostInfo Economy } 'Unknown result never retried blindly'
    Check ($script:Effects.Count -eq $count) 'Blocked retry invokes no effect'
    $null = Repair-FolegoPowerReceipt $fixture $hostInfo
    Check (-not (Get-FolegoPowerState $fixture $hostInfo).paused -and $script:Effects.Count -eq $count) 'Reconcile reads only and does not repeat'
    $power = Get-FolegoPowerState $fixture $hostInfo
    $power.requests = @((1..4) | ForEach-Object { [DateTimeOffset]::UtcNow.ToString('o') })
    Save-FolegoPowerState $fixture $hostInfo $power
    Reject { Invoke-FolegoPower $fixture $hostInfo Economy } 'Four requests per hour cap'
    $power.requests = @(); Save-FolegoPowerState $fixture $hostInfo $power
    $script:Active = '12345678-1234-1234-1234-123456789abc'
    Reject { Invoke-FolegoPower $fixture $hostInfo Economy } 'Vendor/custom plan protected'
    $script:Active = $script:BalancedPlan
    function Get-FolegoPlans { return @($script:BalancedPlan) }
    Reject { Invoke-FolegoPower $fixture $hostInfo Economy } 'Absent economy plan is not created'
    function Get-FolegoHost { [pscustomobject]@{ Id = 'other-host'; Boot = 'other-boot' } }
    Reject { Invoke-FolegoPower $fixture $hostInfo Economy } 'Changed physical host/boot blocks effect'

    function Get-FolegoStartupCommand { return 'fixture-owned-command' }
    $script:RunValue = 'other-command'
    function Get-FolegoStartupValue { return $script:RunValue }
    function New-Item { [CmdletBinding()]param([string]$Path, [switch]$Force) }
    function New-ItemProperty { [CmdletBinding()]param([string]$LiteralPath,[string]$Name,$Value,[string]$PropertyType,[switch]$Force) $script:RunValue = $Value }
    function Remove-ItemProperty { [CmdletBinding()]param([string]$LiteralPath,[string]$Name) $script:RunValue = $null }
    Reject { Set-FolegoStartup $fixture $true } 'Unowned startup entry preserved'
    $script:RunValue = $null
    $null = Set-FolegoStartup $fixture $true
    Check ($script:RunValue -eq 'fixture-owned-command' -and (Get-FolegoSettings $fixture).commissioned) 'Single own startup commissioned'
    $null = Set-FolegoStartup $fixture $false
    Check ($null -eq $script:RunValue -and -not (Get-FolegoSettings $fixture).startup) 'Disabling startup preserves explicit preference'

    # ------------------------------------------------ active management (all effect APIs mocked)
    $bad = $policy | ConvertTo-Json -Depth 20 | ConvertFrom-Json
    $bad.windows.thermal.automatic_default = $true
    Reject { Assert-FolegoManagePolicy $bad } 'Automatic thermal guard can never ship enabled'
    $bad = $policy | ConvertTo-Json -Depth 20 | ConvertFrom-Json
    $bad.windows.thermal.recover_c = 95
    Reject { Assert-FolegoManagePolicy $bad } 'Hysteresis requires recover below raise threshold'
    $bad = $policy | ConvertTo-Json -Depth 20 | ConvertFrom-Json
    $bad.windows.thermal.max_switches_per_hour = 10
    Reject { Assert-FolegoManagePolicy $bad } 'Thermal switch budget capped at four per hour'
    Assert-FolegoManagePolicy $policy
    Check (-not $policy.windows.thermal.automatic_default -and -not $policy.windows.processes.automatic_executor) 'Shipped policy keeps automation opt-in'
    $fast = $policy | ConvertTo-Json -Depth 20 | ConvertFrom-Json
    $fast.windows.processes.wait_seconds = 0

    function Get-FolegoHost { return $hostInfo }
    $script:Active = $script:BalancedPlan
    $script:Proc = @{}; $script:ProcWrites = 0; $script:FailWrite = $false; $script:Reapplied = 0
    function Seed-Thermal([int]$Throttle, [int]$Boost) {
        foreach ($ac in @($true, $false)) {
            $script:Proc[$script:BalancedPlan + '|' + $script:ThrottleMaxSetting + '|' + $ac] = $Throttle
            $script:Proc[$script:BalancedPlan + '|' + $script:BoostModeSetting + '|' + $ac] = $Boost
        }
    }
    function Get-FolegoPowerSetting([string]$Scheme, [string]$Setting, [bool]$Ac) { return [int]$script:Proc[$Scheme + '|' + $Setting + '|' + $Ac] }
    function Set-FolegoPowerSetting([string]$Scheme, [string]$Setting, [bool]$Ac, [int]$Value) {
        $receipt = (Get-FolegoThermalState $fixture $hostInfo).receipt
        Check ($receipt.state -eq 'intended') 'Thermal intent is durable before the native write'
        $script:ProcWrites++
        if (-not $script:FailWrite) { $script:Proc[$Scheme + '|' + $Setting + '|' + $Ac] = $Value }
    }
    function Update-FolegoActiveScheme([string]$Scheme) { $script:Reapplied++ }
    function Reset-ThermalBudget { $s = Get-FolegoThermalState $fixture $hostInfo; $s.requests = @(); Save-FolegoThermalState $fixture $hostInfo $s }
    Seed-Thermal 99 2
    Check (-not (Get-FolegoThermalState $fixture $hostInfo).enabled) 'Thermal guard starts disabled'
    Reject { Invoke-FolegoThermal $fixture $hostInfo Fresco $policy -Automatic } 'Automatic thermal effect requires own enablement'
    $null = Invoke-FolegoThermal $fixture $hostInfo Fresco $policy
    $t = Get-FolegoThermalState $fixture $hostInfo
    Check ($t.receipt.state -eq 'applied' -and (Get-FolegoThermalValues $script:BalancedPlan).ac_boost -eq 0 -and $t.receipt.original.ac_boost -eq 2 -and $t.receipt.original.ac_throttle -eq 99) 'Fresco confirmed by readback with AC/DC originals recorded'
    Check ($script:Reapplied -ge 1) 'Active scheme re-applied after writing its settings'
    $writes = $script:ProcWrites
    $null = Invoke-FolegoThermal $fixture $hostInfo Fresco $policy
    Check ($script:ProcWrites -eq $writes) 'Profile already in effect writes nothing'
    $script:Proc[$script:BalancedPlan + '|' + $script:ThrottleMaxSetting + '|True'] = 100
    Reject { Invoke-FolegoThermal $fixture $hostInfo Restore $policy } 'Third-party change blocks thermal restore'
    Check ((Get-FolegoThermalValues $script:BalancedPlan).ac_throttle -eq 100 -and (Get-FolegoThermalState $fixture $hostInfo).receipt.state -eq 'applied') 'Third-party value preserved with receipt kept for review'
    Reject { Invoke-FolegoThermal $fixture $hostInfo Contencao $policy } 'Third-party change blocks a new profile too'
    $script:Proc[$script:BalancedPlan + '|' + $script:ThrottleMaxSetting + '|True'] = 99
    $null = Invoke-FolegoThermal $fixture $hostInfo Contencao $policy
    $t = Get-FolegoThermalState $fixture $hostInfo
    Check ((Get-FolegoThermalValues $script:BalancedPlan).ac_throttle -eq $policy.windows.thermal.profiles.Contencao.throttle_max -and $t.receipt.original.ac_boost -eq 2) 'Profile chain keeps the first original values'
    $null = Invoke-FolegoThermal $fixture $hostInfo Restore $policy
    $v = Get-FolegoThermalValues $script:BalancedPlan
    Check ($v.ac_throttle -eq 99 -and $v.dc_boost -eq 2 -and (Get-FolegoThermalState $fixture $hostInfo).receipt.state -eq 'restored') 'Originals restored on same host/boot'
    Reset-ThermalBudget
    $null = Invoke-FolegoThermal $fixture $hostInfo Fresco $policy
    $nextBoot = [pscustomobject]@{ Id = 'fixture-host'; Boot = 'fixture-boot-2' }
    function Get-FolegoHost { return $nextBoot }
    Reject { Invoke-FolegoThermal $fixture $nextBoot Restore $policy } 'Receipt from another boot is never restored blindly'
    Reject { Confirm-FolegoThermalBoot $fixture $nextBoot $null } 'Adopting a foreign-boot receipt requires confirmation'
    Check ((Get-FolegoThermalProfile (Get-FolegoThermalState $fixture $nextBoot) $nextBoot) -eq 'Manual') 'Foreign-boot receipt is never driven by the automatic guard'
    $null = Confirm-FolegoThermalBoot $fixture $nextBoot (New-FolegoConfirmation 'thermal-adopt' 'Adopt')
    $null = Invoke-FolegoThermal $fixture $nextBoot Restore $policy
    Check ((Get-FolegoThermalValues $script:BalancedPlan).ac_boost -eq 2) 'Adopted receipt restores after manual review'
    function Get-FolegoHost { return $hostInfo }
    Reset-ThermalBudget
    $t = Get-FolegoThermalState $fixture $hostInfo; $t.receipt = $null; Save-FolegoThermalState $fixture $hostInfo $t
    $script:FailWrite = $true
    Reject { Invoke-FolegoThermal $fixture $hostInfo Fresco $policy } 'Unconfirmed thermal write reported as failure'
    $t = Get-FolegoThermalState $fixture $hostInfo
    Check ($t.paused -and $t.receipt.state -eq 'unknown') 'Uncertain thermal result pauses further effects'
    $writes = $script:ProcWrites
    Reject { Invoke-FolegoThermal $fixture $hostInfo Fresco $policy } 'Unknown thermal result never retried blindly'
    Check ($script:ProcWrites -eq $writes) 'Blocked thermal retry writes nothing'
    $script:FailWrite = $false
    $null = Repair-FolegoThermalReceipt $fixture $hostInfo
    $t = Get-FolegoThermalState $fixture $hostInfo
    Check (-not $t.paused -and $t.receipt.state -eq 'restored' -and $script:ProcWrites -eq $writes) 'Thermal reconcile reads only'
    $t.requests = @((1..4) | ForEach-Object { [DateTimeOffset]::UtcNow.ToString('o') }); Save-FolegoThermalState $fixture $hostInfo $t
    Reject { Invoke-FolegoThermal $fixture $hostInfo Fresco $policy } 'Four thermal switches per hour cap'
    Reset-ThermalBudget
    Reject { Set-FolegoThermalGuard $fixture $hostInfo $true $null } 'Enabling the guard requires confirmation'
    $old = [pscustomobject]@{ subject = 'thermal-guard'; mode = 'Enable'; at = [DateTimeOffset]::UtcNow.AddMinutes(-10).ToString('o') }
    Reject { Set-FolegoThermalGuard $fixture $hostInfo $true $old } 'Expired confirmation rejected'
    $null = Set-FolegoThermalGuard $fixture $hostInfo $true (New-FolegoConfirmation 'thermal-guard' 'Enable')
    $null = Invoke-FolegoThermal $fixture $hostInfo Fresco $policy
    Reject { Invoke-FolegoThermal $fixture $hostInfo Restore $policy -Automatic } 'Automatic guard never undoes a manual profile'
    Reject { Invoke-FolegoThermal $fixture $hostInfo Contencao $policy -Automatic } 'Automatic guard never escalates a manual profile'
    $null = Invoke-FolegoThermal $fixture $hostInfo Restore $policy
    $null = Invoke-FolegoThermal $fixture $hostInfo Fresco $policy -Automatic -Trigger ([pscustomobject]@{ celsius = 93 })
    $t = Get-FolegoThermalState $fixture $hostInfo
    Check ((Get-FolegoThermalProfile $t $hostInfo) -eq 'Fresco' -and $t.receipt.trigger.celsius -eq 93) 'Automatic profile records its thermal evidence'
    $null = Invoke-FolegoThermal $fixture $hostInfo Restore $policy -Automatic
    Check ((Get-FolegoThermalValues $script:BalancedPlan).ac_boost -eq 2) 'Automatic restore returns originals'
    $null = Set-FolegoThermalGuard $fixture $hostInfo $false $null

    $rule = [pscustomobject]@{ raise_average_c = 80; raise_samples = 3; spike_c = 90; recover_c = 70; recover_samples = 4 }
    $g = New-FolegoThermalGuard
    Check ((Step-FolegoThermalGuard $g 79 $rule Normal) -eq 'None' -and (Step-FolegoThermalGuard $g 81 $rule Normal) -eq 'None') 'Two warm samples are not enough'
    Check ((Step-FolegoThermalGuard $g 82 $rule Normal) -eq 'Fresco') 'Moving average over three samples raises to Fresco'
    $g = New-FolegoThermalGuard
    $null = Step-FolegoThermalGuard $g 85 $rule Normal; $null = Step-FolegoThermalGuard $g 85 $rule Normal
    Check ((Step-FolegoThermalGuard $g $null $rule Normal) -eq 'None' -and (Step-FolegoThermalGuard $g 85 $rule Normal) -eq 'None') 'Unknown temperature resets evidence and never acts'
    Check ((Step-FolegoThermalGuard (New-FolegoThermalGuard) 93 $rule Normal) -eq 'Fresco') 'Single spike at or above limit raises'
    Check ((Step-FolegoThermalGuard (New-FolegoThermalGuard) 99 $rule Manual) -eq 'None') 'Manual profile is never changed by the guard'
    $g = New-FolegoThermalGuard
    $decisions = @(60, 60, 60, 71, 60, 60, 60) | ForEach-Object { Step-FolegoThermalGuard $g $_ $rule Fresco }
    Check (-not ($decisions -contains 'Restore')) 'Cool streak broken by a warm sample (hysteresis)'
    Check ((Step-FolegoThermalGuard $g 60 $rule Fresco) -eq 'Restore') 'Restore only after N cool samples'
    $g = New-FolegoThermalGuard
    $null = Step-FolegoThermalGuard $g 85 $rule Fresco; $null = Step-FolegoThermalGuard $g 85 $rule Fresco
    Check ((Step-FolegoThermalGuard $g 85 $rule Fresco) -eq 'Contencao') 'Sustained heat in Fresco escalates to Contencao'
    Check ((Step-FolegoThermalGuard (New-FolegoThermalGuard) 99 $rule Contencao) -eq 'None') 'No escalation beyond Contencao'

    $csv = Join-Path $fixture 'monitor-fixture.csv'
    $text = "hora,cpu_pct,ram_livre_mb,commit_pct,disco_fila,disco_ocioso_pct,disco_kbps,temp_c,tomada,bateria_pct,top_cpu`r`n22:27:17,58,8341,43,0,95,336,58,Online,94,claude(7,3s)`r`n22:27:34,69,8323,43,0,100,0,x,Online,94,powershell(7,4s)`r`n22:27:50,44,8199,44,0,99,0,93,Online,94,claude(3,1s)`r`n" + ([string][char]0 * 64)
    [IO.File]::WriteAllText($csv, $text)
    $rows = @(Read-FolegoMonitorCsv $csv)
    Check ($rows.Count -eq 3 -and $null -eq $rows[1].Celsius -and $rows[2].Celsius -eq 93) 'Monitor CSV replay tolerates NUL padding, decimal commas and bad cells'
    $events = @(Invoke-FolegoThermalReplay $rows $policy.windows.thermal)
    Check ($events.Count -eq 1 -and $events[0].Time -eq '22:27:50' -and $events[0].Decision -eq 'Fresco') 'Replay of the 22:28 reset raises Fresco at the 93 C spike'
    $swing = @(58, 91, 60, 59, 90, 58, 92, 57) | ForEach-Object { [pscustomobject]@{ Time = 't'; Celsius = $_ } }
    $events = @(Invoke-FolegoThermalReplay $swing $rule 4)
    Check (@($events | Where-Object { $_.Result -eq 'applied' }).Count -le 4) 'Replay respects the hourly budget'
    foreach ($path in @($ReplayCsv)) {
        if (-not $path) { continue }
        $real = @(Read-FolegoMonitorCsv $path)
        Check ($real.Count -gt 0) ('Real monitor CSV readable: ' + $path)
        $events = @(Invoke-FolegoThermalReplay $real $policy.windows.thermal)
        $max = ($real | Where-Object { $null -ne $_.Celsius } | Measure-Object Celsius -Maximum).Maximum
        $script:Replay += ('REPLAY ' + [IO.Path]::GetFileName($path) + ': ' + $real.Count + ' amostras, máx ' + $max + ' C, decisões: ' + ((@($events) | ForEach-Object { $_.Time + '=' + $_.Decision + '/' + $_.Result }) -join ' '))
    }

    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    function New-FakeProc([int]$ProcessId, [int]$Parent, [string]$Name, [long]$Start, [long]$Cpu = 0, [string]$Owner = $sid, $Session = 1, [bool]$Window = $false) {
        [pscustomobject]@{ Pid = $ProcessId; ParentPid = $Parent; Name = $Name; Path = ('C:\fixture\' + $Name); OwnerSid = $Owner; SessionId = $Session; StartTicks = $Start; CpuTicks = $Cpu; ReadBytes = [uint64]0; WriteBytes = [uint64]0; HasWindow = $Window; Queried = $true; Threads = 1 }
    }
    function New-FakeRows([long]$OrphanCpu) {
        @(
            (New-FakeProc 100 50 'explorer.exe' 1000), (New-FakeProc 200 100 'claude.exe' 2000), (New-FakeProc 301 200 'node.exe' 2100),
            (New-FakeProc 300 999 'node.exe' 3000 $OrphanCpu), (New-FakeProc 500 100 'cmd.exe' 9000), (New-FakeProc 400 500 'powershell.exe' 4000),
            (New-FakeProc 600 4 'svchost.exe' 500 0 'S-1-5-18' 0), (New-FakeProc 700 999 'codex.exe' 3000 0 'S-1-5-21-1-2-3-9999'),
            (New-FakeProc 800 100 'msiexec.exe' 5000), (New-FakeProc 801 800 'conhost.exe' 5100), (New-FakeProc 900 100 'copilotapp.exe' 6000),
            (New-FakeProc 950 999 'claude.exe' 7000 0 $sid 1 $true), (New-FakeProc 1234 999 'powershell.exe' 7100)
        )
    }
    $rules = Get-FolegoProcessRules $fixture $policy
    $now = [long]3000 + 20 * 600000000
    $context = [pscustomobject]@{ UserSid = $sid; SelfTree = @{ 1234 = $true }; InstallerActive = $false; NowTicks = $now; Idle = @{ '300:3000' = [pscustomobject]@{ cpu = 20000000; since = $now - 15 * 600000000 } } }
    $triage = @(Get-FolegoProcessTriage (New-FakeRows 0) (New-FakeRows 20000000) 2000 @{ 300 = 'node agent.js --token=abc123' } $rules $context $policy)
    function Row([int]$ProcessId) { return @($triage | Where-Object { $_.pid -eq $ProcessId })[0] }
    Check ((Row 300).class -eq 'agente-orfao' -and (Row 300).killable) 'Agent whose parent exited is an orphan candidate'
    Check ((Row 300).cores -eq 1 -and (@((Row 300).reasons) -join ',') -match 'loop' -and (@((Row 300).reasons) -join ',') -match 'ocioso') 'CPU delta and idle tracking describe the orphan'
    Check ((Row 300).command -notmatch 'abc123') 'Command line shown without secrets'
    Check ((Row 400).class -eq 'agente-orfao') 'Parent PID reused by a newer process counts as orphan'
    Check (-not (Row 200).killable -and -not (Row 301).killable -and -not (Row 500).killable) 'Agents with a live parent are protected'
    Check (-not (Row 600).killable -and -not (Row 700).killable) 'System session and other users are protected'
    Check (-not (Row 800).killable -and -not (Row 801).killable) 'Active installer tree is protected'
    Check (-not (Row 950).killable -and -not (Row 1234).killable -and -not (Row 100).killable) 'Windowed agent, own session tree and shell are protected'
    Check ((Row 900).class -eq 'consumidor' -and (Row 900).killable) 'Other same-user consumer is eligible only for confirmed closing'
    $context.InstallerActive = $true
    Check (-not @(Get-FolegoProcessTriage (New-FakeRows 0) (New-FakeRows 0) 2000 @{} $rules $context $policy | Where-Object { $_.killable }).Count) 'Windows installer in progress blocks every process action'
    $context.InstallerActive = $false
    $tree = Get-FolegoProcessTree (New-FakeRows 0) 100
    Check ($tree.ContainsKey(301) -and $tree.ContainsKey(500) -and -not $tree.ContainsKey(400)) 'Process tree validates creation time on PID reuse'
    Write-FolegoJson (Join-Path $fixture 'process-rules.json') ([pscustomobject]@{ schema = 1; agent_names = @('myagent'); protected_names = @('copilotapp') })
    $custom = Get-FolegoProcessRules $fixture $policy
    Check ('myagent' -in $custom.Agents -and 'copilotapp' -in $custom.Protected) 'User allow/deny lists extend the package lists'
    Check (-not @(Get-FolegoProcessTriage (New-FakeRows 0) (New-FakeRows 0) 2000 @{} $custom $context $policy | Where-Object { $_.pid -eq 900 })[0].killable) 'User denylist protects a consumer'
    Write-FolegoJson (Join-Path $fixture 'process-rules.json') ([pscustomobject]@{ schema = 1; agent_names = @('bad;name') })
    Reject { Get-FolegoProcessRules $fixture $policy } 'Invalid user list blocks triage'
    [IO.File]::Delete((Join-Path $fixture 'process-rules.json'))
    Check ((Protect-FolegoCommandLine 'x --api-key "a b" Authorization Bearer eyJhbGciOi sk-ABCDEFGHIJKLMN') -notmatch 'ABCDEFGHIJKLMN|eyJhbGciOi|"a b"') 'Secrets redacted from command lines'

    $script:FakeRows = New-FakeRows 0; $script:Gentle = 0; $script:Forced = 0; $script:Alive = $true; $script:GentleCode = 128
    function Get-FolegoProcessSnapshot { return $script:FakeRows }
    function Get-FolegoCommandLines { return @{} }
    function Test-FolegoInstallerMutex { return $false }
    function Test-FolegoSameProcess([int]$ProcessId, [long]$StartTicks) { return $script:Alive }
    function Invoke-FolegoGentleClose([int]$ProcessId) { $script:Gentle++; return $script:GentleCode }
    function Stop-FolegoProcessForce([int]$ProcessId, [long]$StartTicks) {
        $last = @((Get-FolegoProcessState $fixture $hostInfo).receipts)[-1]
        Check ($last.state -eq 'intended' -and $last.mode -eq 'Force') 'Force intent recorded before termination'
        $script:Forced++; $script:Alive = $false
    }
    $orphan = Row 300
    Reject { Invoke-FolegoProcessAction $fixture $hostInfo $orphan Gentle $null $fast } 'Closing without confirmation is impossible'
    Reject { Invoke-FolegoProcessAction $fixture $hostInfo $orphan Gentle (New-FolegoConfirmation 'process:other' 'Gentle') $fast } 'Confirmation for another item rejected'
    Reject { Invoke-FolegoProcessAction $fixture $hostInfo $orphan Force (New-FolegoConfirmation ('process:' + $orphan.id) 'Force') $fast } 'Force requires a prior gentle attempt'
    Reject { Invoke-FolegoProcessAction $fixture $hostInfo (Row 200) Gentle (New-FolegoConfirmation ('process:' + (Row 200).id) 'Gentle') $fast } 'Protected process never signalled'
    Check ($script:Gentle -eq 0 -and $script:Forced -eq 0) 'Rejected requests sent no signal'
    $script:FakeRows = @($script:FakeRows | ForEach-Object { if ($_.Pid -eq 300) { $c = $_.PSObject.Copy(); $c.StartTicks = 99999; $c } else { $_ } })
    Reject { Invoke-FolegoProcessAction $fixture $hostInfo $orphan Gentle (New-FolegoConfirmation ('process:' + $orphan.id) 'Gentle') $fast } 'PID reuse detected at the act'
    $script:FakeRows = New-FakeRows 0
    $message = Invoke-FolegoProcessAction $fixture $hostInfo $orphan Gentle (New-FolegoConfirmation ('process:' + $orphan.id) 'Gentle') $fast
    Check ($script:Gentle -eq 1 -and @((Get-FolegoProcessState $fixture $hostInfo).receipts)[-1].state -eq 'gentle-refused') 'Gentle refusal recorded; nothing forced'
    Reject { Invoke-FolegoProcessAction $fixture $hostInfo $orphan Force (New-FolegoConfirmation ('process:' + $orphan.id) 'Gentle') $fast } 'Force needs its own confirmation'
    $null = Invoke-FolegoProcessAction $fixture $hostInfo $orphan Force (New-FolegoConfirmation ('process:' + $orphan.id) 'Force') $fast
    Check ($script:Forced -eq 1 -and @((Get-FolegoProcessState $fixture $hostInfo).receipts)[-1].state -eq 'ended') 'Forced closing confirmed and receipted'
    $script:Alive = $false; $consumer = Row 900
    $null = Invoke-FolegoProcessAction $fixture $hostInfo $consumer Gentle (New-FolegoConfirmation ('process:' + $consumer.id) 'Gentle') $fast
    Check (@((Get-FolegoProcessState $fixture $hostInfo).receipts)[-1].state -eq 'ended') 'Gentle close confirmed by identity readback'

    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $approvedRun = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
    $script:Reg = @{
        $runKey = [ordered]@{ Folego = 'fixture-folego'; MicrosoftCopilotAutoLaunch_X = '"C:\Program Files (x86)\Microsoft\Copilot\Application\copilotapp.exe" --win-session-start'; OneDrive = '"C:\fixture\OneDrive.exe" /background'; Weird = 'C:\fixture\weird.exe' }
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' = [ordered]@{ Everything = '"C:\Program Files\Everything\Everything.exe" -startup'; SecurityHealth = 'C:\Windows\system32\SecurityHealthSystray.exe' }
        $approvedRun = [ordered]@{ Weird = [byte[]](3, 0, 0) }
        'HKCU:\fixture\pkg\task' = [ordered]@{ State = 2 }
    }
    $script:FailStartup = $false
    function Get-FolegoRegistryValues([string]$Key) { if ($script:Reg.ContainsKey($Key)) { return $script:Reg[$Key] }; return [ordered]@{} }
    function Get-FolegoStartupFolderItems([string]$Folder) { if ($Folder -eq [Environment]::GetFolderPath('Startup')) { return @([pscustomobject]@{ Name = 'Steam Deck.lnk'; Command = 'C:\fixture\Steam Deck.lnk' }) }; return @() }
    function Get-FolegoPackagedStartupTasks { return @([pscustomobject]@{ Family = 'Microsoft.Copilot_8wekyb3d8bbwe'; Task = 'CopilotStartupTask'; Key = 'HKCU:\fixture\pkg\task' }) }
    function Test-FolegoElevated { return $false }
    function Set-FolegoStartupRaw($Item, $Raw) {
        $intended = @((Get-FolegoStartupState $fixture $hostInfo).receipts | Where-Object { $_.state -eq 'intended' })
        Check ($intended.Count -eq 1) 'Startup intent is durable before the registry write'
        if ($script:FailStartup) { throw 'fixture write failure' }
        if (-not $script:Reg.ContainsKey($Item.approved_key)) { $script:Reg[$Item.approved_key] = [ordered]@{} }
        $map = $script:Reg[$Item.approved_key]
        if ($null -eq $Raw) { $map.Remove($Item.value_name) }
        elseif ($Raw -like 'dword:*') { $map[$Item.value_name] = [int]$Raw.Substring(6) }
        else { $hex = $Raw.Substring(4); $map[$Item.value_name] = [byte[]](0..($hex.Length / 2 - 1) | ForEach-Object { [Convert]::ToByte($hex.Substring($_ * 2, 2), 16) }) }
    }
    $items = @(Get-FolegoStartupItems $policy)
    function Item([string]$Key) { return @($items | Where-Object { $_.key -ceq $Key })[0] }
    Check ((Item 'HKCU|MicrosoftCopilotAutoLaunch_X').app -eq 'Copilot' -and (Item 'HKCU|MicrosoftCopilotAutoLaunch_X').state -eq 'enabled') 'Copilot session autostart detected through Run + StartupApproved'
    Check ((Item 'PastaUsuario|Steam Deck.lnk').protected -and (Item 'HKCU|Folego').protected -and (Item 'HKLM|SecurityHealth').protected) 'Steam Deck, Folego and Windows Security entries preserved'
    Check ((Item 'HKCU|Weird').protected -and (Item 'HKCU|Weird').state -eq 'unknown') 'Unknown approval format protects the entry'
    $key = 'HKCU|MicrosoftCopilotAutoLaunch_X'
    Reject { Set-FolegoStartupItem $fixture $hostInfo $key $false $null $policy } 'Startup change requires confirmation'
    Reject { Set-FolegoStartupItem $fixture $hostInfo 'HKCU|Folego' $false (New-FolegoConfirmation 'startup:HKCU|Folego' 'Disable') $policy } 'Own startup entry cannot be disabled here'
    $null = Set-FolegoStartupItem $fixture $hostInfo $key $false (New-FolegoConfirmation ('startup:' + $key) 'Disable') $policy
    $stored = $script:Reg[$approvedRun]['MicrosoftCopilotAutoLaunch_X']
    Check ($stored.Length -eq 12 -and $stored[0] -eq 3 -and $script:Reg[$runKey].Contains('MicrosoftCopilotAutoLaunch_X')) 'Disabled like Settings: StartupApproved 03 + time, Run entry intact'
    Check ((@(Get-FolegoStartupItems $policy) | Where-Object { $_.key -eq $key }).state -eq 'disabled') 'Disabled state read back'
    $receipt = @((Get-FolegoStartupState $fixture $hostInfo).receipts)[-1]
    Check ($receipt.state -eq 'applied' -and $null -eq $receipt.original) 'Receipt keeps the original absent value'
    $script:Reg[$approvedRun]['MicrosoftCopilotAutoLaunch_X'] = [byte[]](2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    Reject { Restore-FolegoStartupItem $fixture $hostInfo $receipt.id (New-FolegoConfirmation ('startup-restore:' + $receipt.id) 'Restore') } 'Startup restore blocked after a third-party change'
    $script:Reg[$approvedRun]['MicrosoftCopilotAutoLaunch_X'] = $stored
    Reject { Restore-FolegoStartupItem $fixture $hostInfo $receipt.id $null } 'Startup restore requires confirmation'
    $null = Restore-FolegoStartupItem $fixture $hostInfo $receipt.id (New-FolegoConfirmation ('startup-restore:' + $receipt.id) 'Restore')
    Check (-not $script:Reg[$approvedRun].Contains('MicrosoftCopilotAutoLaunch_X')) 'Copilot startup round trip restores the original absent value'
    $later = [pscustomobject]@{ Id = 'fixture-host'; Boot = 'later-boot' }
    function Get-FolegoHost { return $later }
    $null = Set-FolegoStartupItem $fixture $later 'HKCU|OneDrive' $false (New-FolegoConfirmation 'startup:HKCU|OneDrive' 'Disable') $policy
    $receipt = @((Get-FolegoStartupState $fixture $later).receipts)[-1]
    function Get-FolegoHost { return $hostInfo }
    $null = Restore-FolegoStartupItem $fixture $hostInfo $receipt.id (New-FolegoConfirmation ('startup-restore:' + $receipt.id) 'Restore')
    Check (-not $script:Reg[$approvedRun].Contains('OneDrive')) 'Startup restore works after a reboot when the value is unchanged'
    $failed = $false
    try { $null = Set-FolegoStartupItem $fixture $hostInfo 'HKLM|Everything' $false (New-FolegoConfirmation 'startup:HKLM|Everything' 'Disable') $policy } catch { $failed = ([string]$_) -like 'ELEVATION:*' }
    Check $failed 'Machine-wide entry asks for one-off elevation instead of failing silently'
    $pkg = 'Pacote|Microsoft.Copilot_8wekyb3d8bbwe\CopilotStartupTask'
    Check ((Item $pkg).app -eq 'Copilot' -and (Item $pkg).state -eq 'enabled') 'Packaged Copilot startup task detected'
    $null = Set-FolegoStartupItem $fixture $hostInfo $pkg $false (New-FolegoConfirmation ('startup:' + $pkg) 'Disable') $policy
    Check ($script:Reg['HKCU:\fixture\pkg\task'].State -eq 1) 'Packaged task disabled by user state'
    $receipt = @((Get-FolegoStartupState $fixture $hostInfo).receipts)[-1]
    $null = Restore-FolegoStartupItem $fixture $hostInfo $receipt.id (New-FolegoConfirmation ('startup-restore:' + $receipt.id) 'Restore')
    Check ($script:Reg['HKCU:\fixture\pkg\task'].State -eq 2) 'Packaged task round trip'
    $script:FailStartup = $true
    Reject { Set-FolegoStartupItem $fixture $hostInfo 'HKCU|OneDrive' $false (New-FolegoConfirmation 'startup:HKCU|OneDrive' 'Disable') $policy } 'Failed startup write reported'
    $script:FailStartup = $false
    Reject { Set-FolegoStartupItem $fixture $hostInfo 'HKCU|OneDrive' $false (New-FolegoConfirmation 'startup:HKCU|OneDrive' 'Disable') $policy } 'Uncertain startup receipt blocks new changes'
    $null = Repair-FolegoStartupReceipts $fixture $hostInfo
    Check (-not (Get-FolegoStartupState $fixture $hostInfo).paused -and @((Get-FolegoStartupState $fixture $hostInfo).receipts)[-1].state -eq 'restored') 'Startup reconcile reads only'
    $null = Save-FolegoStartupReview $fixture $hostInfo @(Get-FolegoStartupItems $policy)
    $script:Reg[$runKey]['NewTool'] = 'C:\fixture\new.exe'
    $diff = @(Compare-FolegoStartupReview @(Get-FolegoStartupItems $policy) (Get-FolegoStartupState $fixture $hostInfo).review)
    Check (($diff -join ' ') -match 'NOVA: HKCU\|NewTool') 'Changes since the last review are highlighted'
    $report = @(Get-FolegoCopilotReport @() @{ 42 = 'copilotapp.exe --no-startup-window --win-session-start' })
    Check (($report -join ' ') -match 'recriá-la' -and ($report -join ' ') -match 'Aplicativos instalados') 'Copilot report explains session start and official uninstall'

    # ------------------------------------------------ views and colour themes (pure rules)
    Check ((Get-FolegoViewKeys $policy) -join ',' -eq 'central,taskbar,mini,compact,left,right,top') 'Linux views plus the Windows taskbar indicators'
    $themeKeys = @(Get-FolegoThemeKeys $policy)
    Check ($themeKeys.Count -eq 8 -and $policy.windows.appearance.default_theme -in $themeKeys) 'Eight Linux console themes with a valid default'
    foreach ($key in $themeKeys) {
        $tokens = (Get-FolegoTheme $policy $key).tokens
        foreach ($role in @('background', 'surface', 'surface_alt', 'text', 'muted', 'accent', 'accent_text', 'ok', 'warning', 'danger', 'border')) {
            Check ([string](Get-FolegoValue $tokens $role '') -match '^#[0-9A-Fa-f]{6}$') ('Theme ' + $key + ' defines ' + $role)
        }
    }
    Reject { Get-FolegoTheme $policy 'neon' } 'Unknown theme rejected'
    $look = Get-FolegoAppearance $fixture $policy
    Check ($look.theme -eq $policy.windows.appearance.default_theme -and $look.startup_view -eq 'taskbar' -and $look.transparency -eq 0) 'Appearance defaults: taskbar indicators, default theme, opaque'
    $look = Set-FolegoAppearanceField $look theme 'ps2' $policy
    $look = Set-FolegoAppearanceField $look startup_view 'mini' $policy
    $look = Set-FolegoWidgetPosition $look 'compact' 40 50 $policy
    Save-FolegoAppearance $fixture $policy $look
    $read = Get-FolegoAppearance $fixture $policy
    Check ($read.theme -eq 'ps2' -and $read.startup_view -eq 'mini' -and $read.positions.compact.x -eq 40) 'Theme, opening view and position round trip'
    Reject { Set-FolegoAppearanceField $read theme 'neon' $policy } 'Unknown theme never saved'
    Reject { Set-FolegoAppearanceField $read transparency 61 $policy } 'Transparency capped so text stays legible'
    Check ((Set-FolegoAppearanceField $read transparency 60 $policy).transparency -eq 60) 'Maximum transparency accepted'
    Reject { Set-FolegoAppearanceField $read startup_view 'sidebar' $policy } 'Unknown opening view rejected'
    Reject { Set-FolegoWidgetPosition $read 'top' 1 1 $policy } 'Docked views keep no free position'
    [IO.File]::WriteAllText((Join-Path $fixture 'appearance.json'), '{"schema":1,"theme":"neon","transparency":0,"startup_view":"central","last_widget":"mini","positions":{}}')
    Reject { Get-FolegoAppearance $fixture $policy } 'Unknown saved appearance is reported, not coerced'
    Check (([IO.File]::ReadAllText((Join-Path $fixture 'appearance.json'))) -match 'neon') 'Unknown saved appearance preserved for review'
    [IO.File]::Delete((Join-Path $fixture 'appearance.json'))
    $area = [pscustomobject]@{ X = 0; Y = 0; Width = 1280; Height = 752 }
    $b = Get-FolegoDockBounds 'left' $area
    Check ($b.X -eq 0 -and $b.Width -eq 112 -and $b.Height -eq 752) 'Left bar uses the work area edge (Linux width rule)'
    $b = Get-FolegoDockBounds 'right' $area
    Check ($b.X -eq 1168 -and $b.Width -eq 112) 'Right bar anchored to the right edge'
    Check ((Get-FolegoDockBounds 'top' $area).Height -eq 120 -and (Get-FolegoDockBounds 'top' ([pscustomobject]@{ X = 0; Y = 0; Width = 800; Height = 600 })).Height -eq 190) 'Top bar is slim on wide screens'
    Reject { Get-FolegoDockBounds 'mini' $area } 'Floating views have no dock geometry'
    $p = Get-FolegoFloatPosition $null 384 46 $area
    Check ($p.X -eq 872 -and $p.Y -eq 682) 'Default float position bottom-right with margin'
    $p = Get-FolegoFloatPosition ([pscustomobject]@{ x = 5000; y = -40 }) 384 46 $area
    Check ($p.X -eq 896 -and $p.Y -eq 0) 'Saved position clamped into the live work area'
    $healthy = [pscustomobject]@{ TotalPhysical = 16GB; AvailablePhysical = 8GB; CommitLimit = 20GB; CommitUsed = 15GB; CpuPercent = 20; BatteryPercent = 80; ExternalPower = $true }
    $m = Get-FolegoMiniMetrics $healthy ([pscustomobject]@{ Celsius = 59.1 }) 'green' $policy $false
    Check ($m.Status.Text -eq 'Saudável' -and $m.Cpu.Role -eq 'ok' -and $m.Temp.Text -match '^59' -and $m.Bat.Caption -eq 'TOMADA' -and $m.Headroom -eq 25) 'Mini metrics, power caption and headroom (RAM vs commit)'
    $m = Get-FolegoMiniMetrics $healthy ([pscustomobject]@{ Celsius = 92 }) 'green' $policy $false
    Check ($m.Status.Text -eq 'Calor alto' -and $m.Status.Role -eq 'danger' -and $m.Temp.Role -eq 'danger') 'Spike temperature turns the widget status red'
    Check ((Get-FolegoMiniMetrics $healthy ([pscustomobject]@{ Celsius = 82 }) 'green' $policy $false).Status.Text -eq 'Quente') 'Guard threshold shows Quente'
    $hot = [pscustomobject]@{ TotalPhysical = 16GB; AvailablePhysical = 1GB; CommitLimit = 20GB; CommitUsed = 8GB; CpuPercent = 97; BatteryPercent = 5; ExternalPower = $false }
    $m = Get-FolegoMiniMetrics $hot $null 'red' $policy $false
    Check ($m.Cpu.Role -eq 'danger' -and $m.Ram.Role -eq 'danger' -and $m.Bat.Role -eq 'danger' -and $m.Temp.Role -eq 'muted' -and $m.Status.Text -eq 'Bateria 5%') 'Critical CPU, RAM and battery; unknown temperature stays neutral'
    Check ((Get-FolegoMiniMetrics $hot $null 'red' $policy $true).Status.Text -eq 'Pausado') 'Paused monitoring is shown as paused'
    $m = Get-FolegoMiniMetrics $null $null 'unknown' $policy $false
    Check ($m.Status.Role -eq 'muted' -and $m.Cpu.Text -eq '—' -and -not $m.Bat.Visible -and $null -eq $m.Headroom) 'Missing sample never looks healthy'
    Check ($null -ne ('Folego.Windows.WidgetForm' -as [type]) -and $null -ne ('Folego.Windows.HealthRing' -as [type]) -and $null -ne ('Folego.Windows.TrayGlyph' -as [type])) 'Widget window, health ring and tray glyphs compile with Windows Forms'
    $tray = @(Get-FolegoTrayIndicators (Get-FolegoMiniMetrics $healthy ([pscustomobject]@{ Celsius = 59.1 }) 'green' $policy $false))
    Check (($tray | ForEach-Object { $_.Key }) -join ',' -eq 'Cpu,Temp,Ram,Bat') 'Taskbar shows CPU, temperature, RAM and battery'
    Check ((@($tray | Where-Object { $_.Key -eq 'Temp' })[0].Text -eq '59') -and (@($tray | Where-Object { $_.Key -eq 'Ram' })[0].Text -eq '50')) 'Indicator numbers fit a small icon'
    Check (@($tray | Where-Object { $_.Key -eq 'Bat' })[0].Tip -match 'tomada') 'Battery tooltip says when on external power'
    Check (@($tray | Where-Object { $_.Text.Length -gt 3 -or $_.Tip.Length -gt 63 }).Count -eq 0) 'Icon text and tooltip fit Windows limits'
    $tray = @(Get-FolegoTrayIndicators (Get-FolegoMiniMetrics $null $null 'unknown' $policy $false))
    Check (($tray | ForEach-Object { $_.Key }) -join ',' -eq 'Cpu,Temp,Ram' -and @($tray | Where-Object { $_.Role -ne 'muted' -or $_.Text -ne '–' }).Count -eq 0) 'Unknown readings stay neutral and battery icon hides without a battery'
    $tray = @(Get-FolegoTrayIndicators (Get-FolegoMiniMetrics $hot $null 'red' $policy $false))
    Check (@($tray | Where-Object { $_.Key -eq 'Cpu' })[0].Role -eq 'danger' -and @($tray | Where-Object { $_.Key -eq 'Bat' })[0].Text -eq '5') 'Critical readings colour the indicators'
    $script:Replay
    'PASS: ' + $script:Checks + ' Windows contracts; effect APIs mocked. Native hardware validation remains separate.'
} finally {
    [IO.Directory]::Delete($fixture, $true)
}
