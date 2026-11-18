# Views (central, mini, compact, side and top bars) and colour themes. No Forms dependency:
# geometry, preferences and metric roles are pure so the contract script can check them.
# Themes and views come from policy.json, generated from the Linux palettes.
$script:FolegoWidgetViews = @('mini', 'compact', 'left', 'right', 'top')
$script:FolegoFloatViews = @('mini', 'compact')
$script:FolegoMiniHeight = 46
$script:FolegoCompactWidth = 268
$script:FolegoSlimTopWidth = 900

function Get-FolegoViewKeys($Policy) { return @($Policy.windows.appearance.views | ForEach-Object { [string]$_.key }) }
function Get-FolegoViewName($Policy, [string]$View) { return [string](@($Policy.windows.appearance.views | Where-Object { $_.key -eq $View })[0].name) }
function Get-FolegoThemeKeys($Policy) { return @($Policy.windows.appearance.themes.PSObject.Properties | ForEach-Object { $_.Name }) }
function Get-FolegoTheme($Policy, [string]$Key) {
    $theme = Get-FolegoValue $Policy.windows.appearance.themes $Key
    if ($null -eq $theme) { throw 'Tema desconhecido.' }
    return $theme
}
function New-FolegoAppearance($Policy) {
    return [pscustomobject]@{ schema = 1; theme = [string]$Policy.windows.appearance.default_theme; transparency = 0; startup_view = [string]$Policy.windows.appearance.default_view; last_widget = 'compact'; positions = [pscustomobject]@{} }
}
function Test-FolegoAppearance($Value, $Policy) {
    # Returns '' when valid, otherwise the reason. Unknown values are never coerced.
    if ($null -eq $Value) { return 'Aparência ausente.' }
    if (-not (Test-FolegoInt (Get-FolegoValue $Value schema)) -or $Value.schema -ne 1) { return 'Aparência com schema desconhecido.' }
    if ([string](Get-FolegoValue $Value theme '') -notin (Get-FolegoThemeKeys $Policy)) { return 'Tema de cores desconhecido.' }
    $alpha = Get-FolegoValue $Value transparency
    if (-not (Test-FolegoInt $alpha) -or $alpha -lt 0 -or $alpha -gt [int]$Policy.windows.appearance.transparency_max) { return 'Transparência fora do intervalo permitido.' }
    if ([string](Get-FolegoValue $Value startup_view '') -notin (Get-FolegoViewKeys $Policy)) { return 'Modo de abertura desconhecido.' }
    if ([string](Get-FolegoValue $Value last_widget '') -notin $script:FolegoWidgetViews) { return 'Último widget desconhecido.' }
    $positions = Get-FolegoValue $Value positions
    if ($null -eq $positions) { return 'Posições ausentes.' }
    foreach ($row in @($positions.PSObject.Properties)) {
        if ($row.Name -notin $script:FolegoFloatViews -or -not (Test-FolegoInt (Get-FolegoValue $row.Value x)) -or -not (Test-FolegoInt (Get-FolegoValue $row.Value y))) { return 'Posição salva inválida.' }
    }
    return ''
}
function Get-FolegoAppearance([string]$DataRoot, $Policy) {
    $value = Read-FolegoJson (Join-Path $DataRoot 'appearance.json')
    if ($null -eq $value) { return (New-FolegoAppearance $Policy) }
    $reason = Test-FolegoAppearance $value $Policy
    if ($reason) { throw ($reason + ' O arquivo foi preservado; os padrões valem só nesta sessão.') }
    return $value
}
function Save-FolegoAppearance([string]$DataRoot, $Policy, $Value) {
    $reason = Test-FolegoAppearance $Value $Policy
    if ($reason) { throw ($reason + ' Nada foi salvo.') }
    # Written only when the user changes a view, theme, transparency or widget position.
    Write-FolegoJson (Join-Path $DataRoot 'appearance.json') $Value
}
function Set-FolegoAppearanceField($Appearance, [string]$Field, $Value, $Policy) {
    $copy = $Appearance | ConvertTo-Json -Depth 6 | ConvertFrom-Json
    Set-FolegoValue $copy $Field $Value
    $reason = Test-FolegoAppearance $copy $Policy
    if ($reason) { throw $reason }
    return $copy
}
function Set-FolegoWidgetPosition($Appearance, [string]$View, [int]$X, [int]$Y, $Policy) {
    if ($View -notin $script:FolegoFloatViews) { throw 'Somente o mini e o compacto guardam posição.' }
    $copy = $Appearance | ConvertTo-Json -Depth 6 | ConvertFrom-Json
    Set-FolegoValue $copy.positions $View ([pscustomobject]@{ x = $X; y = $Y })
    return $copy
}
function Get-FolegoDockBounds([string]$View, $Area) {
    # Same rule as the Linux dock_geometry: only the screen work area, never over the taskbar.
    if ($View -notin @('left', 'right', 'top') -or $Area.Width -le 0 -or $Area.Height -le 0) { throw 'Borda ou tela indisponível.' }
    if ($View -eq 'top') {
        $height = [Math]::Min($Area.Height, $(if ($Area.Width -ge $script:FolegoSlimTopWidth) { 120 } else { 190 }))
        return [pscustomobject]@{ X = [int]$Area.X; Y = [int]$Area.Y; Width = [int]$Area.Width; Height = [int]$height }
    }
    $width = [Math]::Min([Math]::Min(128, [Math]::Max(112, [Math]::Floor($Area.Width / 12))), $Area.Width)
    $x = if ($View -eq 'left') { $Area.X } else { $Area.X + $Area.Width - $width }
    return [pscustomobject]@{ X = [int]$x; Y = [int]$Area.Y; Width = [int]$width; Height = [int]$Area.Height }
}
function Get-FolegoFloatPosition($Saved, [int]$Width, [int]$Height, $Area) {
    # Saved position clamped into the live work area; default bottom-right, 24 px margin.
    if ($null -eq $Saved) { $x = $Area.X + $Area.Width - $Width - 24; $y = $Area.Y + $Area.Height - $Height - 24 }
    else { $x = [int]$Saved.x; $y = [int]$Saved.y }
    $x = [Math]::Max([int]$Area.X, [Math]::Min($x, [int]($Area.X + $Area.Width - $Width)))
    $y = [Math]::Max([int]$Area.Y, [Math]::Min($y, [int]($Area.Y + $Area.Height - $Height)))
    return [pscustomobject]@{ X = [int]$x; Y = [int]$y }
}
function Get-FolegoHeadroom($Sample) {
    # Smallest free share between physical RAM and commit (Windows analogue of RAM/swap/tmpfs).
    if ($null -eq $Sample -or $Sample.TotalPhysical -le 0 -or $Sample.CommitLimit -le 0) { return $null }
    $ram = [double]$Sample.AvailablePhysical / $Sample.TotalPhysical
    $commit = 1 - [double]$Sample.CommitUsed / $Sample.CommitLimit
    return [int][Math]::Round(100.0 * [Math]::Max(0.0, [Math]::Min($ram, $commit)))
}
function Get-FolegoBatteryEstimate($Sample) {
    $seconds = Get-FolegoValue $Sample BatterySeconds
    if ($Sample.ExternalPower -ne $false -or $null -eq $seconds -or $seconds -lt 0) { return '' }
    if ($seconds -lt 60) { return '<1 min restantes' }
    $time = [TimeSpan]::FromSeconds($seconds)
    if ($time.TotalHours -lt 1) { return ('{0} min restantes' -f $time.Minutes) }
    return ('{0} h {1:00} min restantes' -f [Math]::Floor($time.TotalHours), $time.Minutes)
}
function Get-FolegoMiniMetrics($Sample, $ThermalNow, [string]$Level, $Policy, [bool]$Paused) {
    # Text + colour role (ok/warning/danger/muted) for the mini, side and top views.
    $w = $Policy.windows; $t = $w.thermal; $h = $Policy.health
    $verdicts = @{ green = @('Saudável', 'ok'); yellow = @('Atenção', 'warning'); red = @('Crítico', 'danger'); unknown = @('Desconhecido', 'muted') }
    $verdict = $verdicts[$(if ($verdicts.ContainsKey($Level)) { $Level } else { 'unknown' })]
    $status = [pscustomobject]@{ Text = $verdict[0]; Role = $verdict[1] }
    $celsius = Get-FolegoValue $ThermalNow Celsius
    $temp = [pscustomobject]@{ Text = '— °C'; Role = 'muted' }
    if ($null -ne $celsius) {
        $temp.Text = ('{0:N0} °C' -f $celsius)
        $temp.Role = if ($celsius -ge [double]$t.spike_c) { 'danger' } elseif ($celsius -ge [double]$t.raise_average_c) { 'warning' } else { 'ok' }
    }
    $cpu = [pscustomobject]@{ Text = '—'; Role = 'muted' }
    $ram = [pscustomobject]@{ Text = '—'; Role = 'muted' }
    $bat = [pscustomobject]@{ Text = '—'; Role = 'muted'; Caption = 'BAT'; Visible = $false; Estimate = '' }
    if ($null -ne $Sample) {
        if ($null -ne $Sample.CpuPercent) {
            $cpu.Text = ('{0:N0}%' -f $Sample.CpuPercent)
            $cpu.Role = if ($Sample.CpuPercent -ge $w.cpu_critical) { 'danger' } elseif ($Sample.CpuPercent -ge $w.cpu_attention) { 'warning' } else { 'ok' }
        }
        if ($Sample.TotalPhysical -gt 0 -and $null -ne $Sample.AvailablePhysical -and $Sample.AvailablePhysical -le $Sample.TotalPhysical) {
            $available = [double]$Sample.AvailablePhysical / $Sample.TotalPhysical
            $ram.Text = ('{0:N0}%' -f (100 * (1 - $available)))
            $ram.Role = if ($available -le $h.red_available_frac) { 'danger' } elseif ($available -le $h.yellow_available_frac) { 'warning' } else { 'ok' }
        }
        if ($null -ne $Sample.BatteryPercent) {
            $band = [string]$Policy.battery_bands[[int]$Sample.BatteryPercent]
            $bat.Text = ([string]$Sample.BatteryPercent + '%'); $bat.Visible = $true
            $bat.Role = @{ green = 'ok'; yellow = 'warning'; orange = 'warning'; red = 'danger' }[$band]
            $bat.Estimate = Get-FolegoBatteryEstimate $Sample
            if ($Sample.ExternalPower -eq $true) { $bat.Caption = 'TOMADA' }
        }
    }
    if ($Paused) { $status.Text = 'Pausado'; $status.Role = 'muted' }
    elseif ($temp.Role -eq 'danger') { $status.Text = 'Calor alto'; $status.Role = 'danger' }
    elseif ($temp.Role -eq 'warning' -and $status.Role -ne 'danger') { $status.Text = 'Quente'; $status.Role = 'warning' }
    elseif ($null -ne $Sample -and $Sample.ExternalPower -eq $false -and $null -ne $Sample.BatteryPercent -and $Sample.BatteryPercent -le 10) { $status.Text = ('Bateria ' + $Sample.BatteryPercent + '%'); $status.Role = 'danger' }
    return [pscustomobject]@{ Status = $status; Cpu = $cpu; Temp = $temp; Ram = $ram; Bat = $bat; Headroom = (Get-FolegoHeadroom $Sample) }
}
function Update-FolegoTrayReadings([hashtable]$Readings, $Metrics, $Sample, $Thermal) {
    foreach ($key in @('Cpu', 'Temp', 'Ram', 'Bat')) {
        if ($key -eq 'Bat' -and (Get-FolegoValue $Sample HasBattery) -eq $false) { $Readings.Remove($key); continue }
        $source = if ($key -eq 'Temp') { $Thermal } else { $Sample }
        $mono = Get-FolegoValue $source $(if ($key -eq 'Temp') { 'Mono' } else { 'MonotonicMs' })
        $metric = $Metrics.$key
        $last = $Readings[$key]
        if ($null -ne $mono -and $metric.Role -ne 'muted') {
            if ($null -eq $last -or $mono -ge $last.Mono) {
                $Readings[$key] = [pscustomobject]@{ Metric = $metric; Mono = [long]$mono; Unconfirmed = $false }
            }
        } elseif ($null -ne $last) { $last.Unconfirmed = $true }
    }
}
function Get-FolegoTrayIndicators($Metrics, [bool]$Paused = $false, [bool]$Stale = $false,
                                  [hashtable]$Readings, [long]$NowMs = 0, [long]$FastFreshMs = 15000) {
    foreach ($spec in @(@('Cpu', 'CPU', 'CPU', 0), @('Temp', 'TEMP', 'Temperatura (zona ACPI)', 1), @('Ram', 'RAM', 'RAM em uso', 2), @('Bat', 'BAT', 'Bateria', 3))) {
        $key = $spec[0]; $metric = $Metrics.$key
        $state = if ($Stale) { 'expired' } else { 'current' }
        $nextChange = [long]::MaxValue
        $last = if ($null -ne $Readings) { $Readings[$key] } else { $null }
        if ($key -eq 'Bat' -and -not $metric.Visible -and $null -eq $last) { continue }
        if ($null -ne $last) {
            $metric = $last.Metric
            $fresh = if ($key -eq 'Temp') { 90000L } else { $FastFreshMs }
            $age = $NowMs - $last.Mono
            if ($age -lt 0 -or $age -gt $fresh + 30000L) { $state = 'expired' }
            elseif ($age -gt $fresh -or $last.Unconfirmed) { $state = 'delayed'; $nextChange = $last.Mono + $fresh + 30001L }
            else { $state = 'current'; $nextChange = $last.Mono + $fresh + 1L }
        }
        if ($Paused) { $state = 'paused'; $nextChange = [long]::MaxValue }
        $number = [string]$metric.Text -replace '(?:%| °C)$', ''
        $visible = $state -in @('current', 'delayed')
        $text = if ($visible -and $number.Length -le 3 -and $number -match '^-?[0-9]+$') { $number } else { '–' }
        $role = if ($text -eq '–' -or $state -eq 'delayed') { 'muted' } else { [string]$metric.Role }
        $caption = if ($key -eq 'Bat' -and $state -eq 'current' -and $metric.Caption -eq 'TOMADA') { 'Bateria (na tomada)' } else { $spec[2] }
        $reading = switch ($state) {
            'paused' { 'monitoramento pausado' }
            'expired' { 'amostra antiga' }
            'delayed' { $metric.Text + ' · leitura anterior' }
            default { if ($number -eq '—') { 'indisponível' } else { $metric.Text } }
        }
        if ($state -eq 'current' -and $key -eq 'Bat' -and $metric.Estimate) { $reading += ' · ' + $metric.Estimate }
        [pscustomobject]@{ Key = $key; Label = $spec[1]; Text = $text; Role = $role; Strip = [int]$spec[3]; Delayed = ($state -eq 'delayed'); NextChange = $nextChange; Tip = ($caption + ': ' + $reading + ' · Fôlego') }
    }
}
