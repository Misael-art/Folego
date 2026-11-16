# Isolated contracts, including on Windows: effect APIs are mocked below.
param([string]$PolicyPath)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Folego.Core.ps1')
Set-StrictMode -Version 2
$script:Checks = 0
function Check([bool]$Value, [string]$Message) { if (-not $Value) { throw ('FAIL: ' + $Message) }; $script:Checks++ }
function Reject([scriptblock]$Operation, [string]$Message) { $failed = $false; try { & $Operation | Out-Null } catch { $failed = $true }; Check $failed $Message }
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('folego-windows-tests-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($fixture) | Out-Null
try {
    foreach ($file in @('Folego.ps1', 'Folego.Core.ps1', 'Collect.ps1', 'Test-Folego.ps1', 'DeckBootstrap.ps1')) {
        $tokens = $null; $errors = $null
        $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file), [ref]$tokens, [ref]$errors)
        Check ($errors.Count -eq 0) ('Syntax ' + $file + ': ' + ($errors | Out-String))
    }
    Add-Type -Path (Join-Path $PSScriptRoot 'Native.cs')
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
    'PASS: ' + $script:Checks + ' Windows contracts; effect APIs mocked. Native hardware validation remains separate.'
} finally {
    [IO.Directory]::Delete($fixture, $true)
}
