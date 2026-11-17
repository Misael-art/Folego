# Windows Forms views: mini horizontal, compact widget, side bars, top bar, and colour themes.
# Dot-sourced by Folego.ps1 after Forms is loaded; uses its $form, $tray, $policy, $DataRoot,
# $status, Request-Folego and Show-Folego. Pure rules live in Folego.View.ps1.
$script:Appearance = $null; $script:AppearanceLocked = $false; $script:AppearanceNote = ''
$script:Tokens = $null; $script:Widget = $null; $script:WidgetView = ''; $script:WidgetControls = @{}
$script:WidgetData = $null; $script:WidgetStale = $false; $script:AppearanceItems = New-Object 'Collections.Generic.List[object]'
$script:WidgetScale = 1.0; $script:WidgetMenu = $null
$script:WidgetTips = New-Object Windows.Forms.ToolTip

function ConvertTo-FolegoColor([string]$Hex) { return [Drawing.ColorTranslator]::FromHtml($Hex) }
function Get-FolegoRoleColor([string]$Role) {
    $hex = Get-FolegoValue $script:Tokens $Role
    if (-not $hex) { $hex = $script:Tokens.text }
    return (ConvertTo-FolegoColor $hex)
}
function Initialize-FolegoAppearance {
    try { $script:Appearance = Get-FolegoAppearance $DataRoot $policy }
    catch { $script:Appearance = New-FolegoAppearance $policy; $script:AppearanceLocked = $true; $script:AppearanceNote = [string]$_ }
    $script:Tokens = (Get-FolegoTheme $policy $script:Appearance.theme).tokens
    $graphics = [Drawing.Graphics]::FromHwnd([IntPtr]::Zero)
    try { $script:WidgetScale = [Math]::Max(1.0, $graphics.DpiX / 96.0) } finally { $graphics.Dispose() }
}
function S([double]$Pixels) { return [int][Math]::Round($Pixels * $script:WidgetScale) }
function Save-FolegoAppearanceChange($Value) {
    $script:Appearance = $Value
    if ($script:AppearanceLocked) { $status.Text = 'Aparência aplicada só nesta sessão: ' + $script:AppearanceNote; return }
    try { Save-FolegoAppearance $DataRoot $policy $Value } catch { $status.Text = [string]$_ }
}

# ------------------------------------------------------------------ theming
function Set-FolegoControlTheme($Control) {
    $t = $script:Tokens
    $role = if ($Control.Tag -is [string] -and $Control.Tag -like 'role:*') { $Control.Tag.Substring(5) } else { '' }
    switch -Regex ($Control.GetType().Name) {
        '^(Form|WidgetForm)$' { $Control.BackColor = ConvertTo-FolegoColor $t.background; $Control.ForeColor = ConvertTo-FolegoColor $t.text }
        '^(TabPage|FlowLayoutPanel|TableLayoutPanel|Panel)$' {
            $Control.BackColor = if ($Control.Tag -eq 'cell') { ConvertTo-FolegoColor $t.surface_alt } elseif ($Control.Tag -eq 'surface') { ConvertTo-FolegoColor $t.surface } else { ConvertTo-FolegoColor $t.background }
            $Control.ForeColor = ConvertTo-FolegoColor $t.text
        }
        '^Label$' { $Control.BackColor = [Drawing.Color]::Transparent; $Control.ForeColor = if ($role) { Get-FolegoRoleColor $role } else { ConvertTo-FolegoColor $t.text } }
        '^Button$' {
            $Control.FlatStyle = 'Flat'; $Control.UseVisualStyleBackColor = $false
            $Control.BackColor = ConvertTo-FolegoColor $t.surface_alt; $Control.ForeColor = ConvertTo-FolegoColor $t.text
            $Control.FlatAppearance.BorderColor = ConvertTo-FolegoColor $t.border
            $Control.FlatAppearance.MouseOverBackColor = ConvertTo-FolegoColor $t.surface
        }
        '^(TextBox|ListView|ComboBox)$' { $Control.BackColor = ConvertTo-FolegoColor $t.surface; $Control.ForeColor = ConvertTo-FolegoColor $t.text }
        '^HealthRing$' {
            $Control.TrackColor = ConvertTo-FolegoColor $t.surface_alt; $Control.TextColor = ConvertTo-FolegoColor $t.text
            $Control.MutedColor = ConvertTo-FolegoColor $t.muted; $Control.Invalidate()
        }
        '^(MenuStrip|ContextMenuStrip)$' { Set-FolegoMenuTheme $Control.Items; $Control.BackColor = ConvertTo-FolegoColor $t.surface; $Control.ForeColor = ConvertTo-FolegoColor $t.text }
    }
    foreach ($child in $Control.Controls) { Set-FolegoControlTheme $child }
}
function Set-FolegoMenuTheme($Items) {
    foreach ($item in $Items) {
        $item.BackColor = ConvertTo-FolegoColor $script:Tokens.surface; $item.ForeColor = ConvertTo-FolegoColor $script:Tokens.text
        if ($item -is [Windows.Forms.ToolStripMenuItem]) { Set-FolegoMenuTheme $item.DropDownItems; $item.DropDown.BackColor = ConvertTo-FolegoColor $script:Tokens.surface }
    }
}
function Update-FolegoTabTheme {
    $tabs.Invalidate()
}
function Set-FolegoThemeEverywhere {
    $script:Tokens = (Get-FolegoTheme $policy $script:Appearance.theme).tokens
    Set-FolegoControlTheme $form
    Set-FolegoMenuTheme $menu.Items; $menu.BackColor = ConvertTo-FolegoColor $script:Tokens.surface
    Update-FolegoTabTheme
    if ($null -ne $script:WidgetMenu) { Set-FolegoMenuTheme $script:WidgetMenu.Items }
    $script:TrayDrawn = ''; $script:TaskbarDrawn = @{}
    if ($null -ne $script:Widget) { Set-FolegoControlTheme $script:Widget }
    Update-FolegoWidget
    Sync-FolegoAppearanceChecks
}
function Set-FolegoThemeChoice([string]$Key) {
    try { Save-FolegoAppearanceChange (Set-FolegoAppearanceField $script:Appearance theme $Key $policy) } catch { $status.Text = [string]$_; return }
    Set-FolegoThemeEverywhere
    $status.Text = 'Tema aplicado na central, no widget e nos menus: ' + (Get-FolegoTheme $policy $Key).name
}
function Set-FolegoTransparencyChoice([int]$Value) {
    try { Save-FolegoAppearanceChange (Set-FolegoAppearanceField $script:Appearance transparency $Value $policy) } catch { $status.Text = [string]$_; return }
    if ($null -ne $script:Widget) { $script:Widget.Opacity = 1 - $Value / 100.0 }
    Sync-FolegoAppearanceChecks
}
function Set-FolegoStartupViewChoice([string]$View) {
    try { Save-FolegoAppearanceChange (Set-FolegoAppearanceField $script:Appearance startup_view $View $policy) } catch { $status.Text = [string]$_; return }
    $status.Text = 'Modo de abertura salvo: ' + (Get-FolegoViewName $policy $View) + '. Vale na próxima abertura do Fôlego.'
}
function New-FolegoThemeSwatch($Theme) {
    $bitmap = New-Object Drawing.Bitmap 60, 14
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $index = 0
        foreach ($hex in @($Theme.actions)) {
            $brush = New-Object Drawing.SolidBrush (ConvertTo-FolegoColor $hex)
            try { $graphics.FillRectangle($brush, $index * 10, 0, 10, 14) } finally { $brush.Dispose() }
            $index++
        }
    } finally { $graphics.Dispose() }
    return $bitmap
}

# ------------------------------------------------------------------ menus
function Add-FolegoAppearanceItems($Items) {
    # Same destinations as the Linux widget menu, plus colour theme and transparency.
    $views = New-Object Windows.Forms.ToolStripMenuItem 'Visualizações'
    foreach ($row in @($policy.windows.appearance.views)) {
        $item = New-Object Windows.Forms.ToolStripMenuItem ([string]$row.name)
        $item.Tag = [string]$row.key
        if ($row.key -eq 'compact') { $item.ShortcutKeyDisplayString = 'Ctrl+Shift+F' }
        $item.Add_Click({ param($sender, $e) Show-FolegoView ([string]$sender.Tag) })
        $null = $views.DropDownItems.Add($item); $script:AppearanceItems.Add([pscustomobject]@{ Kind = 'view'; Item = $item })
    }
    $themes = New-Object Windows.Forms.ToolStripMenuItem 'Tema de cores'
    foreach ($key in (Get-FolegoThemeKeys $policy)) {
        $theme = Get-FolegoTheme $policy $key
        $item = New-Object Windows.Forms.ToolStripMenuItem ([string]$theme.name)
        $item.Image = New-FolegoThemeSwatch $theme; $item.Tag = $key; $item.ToolTipText = [string]$theme.description
        $item.Add_Click({ param($sender, $e) Set-FolegoThemeChoice ([string]$sender.Tag) })
        $null = $themes.DropDownItems.Add($item); $script:AppearanceItems.Add([pscustomobject]@{ Kind = 'theme'; Item = $item })
    }
    $alpha = New-Object Windows.Forms.ToolStripMenuItem 'Transparência do widget'
    foreach ($value in @($policy.windows.appearance.transparency_steps)) {
        $item = New-Object Windows.Forms.ToolStripMenuItem ([string]$value + '%')
        $item.Tag = [int]$value
        $item.Add_Click({ param($sender, $e) Set-FolegoTransparencyChoice ([int]$sender.Tag) })
        $null = $alpha.DropDownItems.Add($item); $script:AppearanceItems.Add([pscustomobject]@{ Kind = 'alpha'; Item = $item })
    }
    foreach ($entry in @($views, $themes, $alpha)) { $null = $Items.Add($entry) }
}
function Sync-FolegoAppearanceChecks {
    $current = if ($script:WidgetView) { $script:WidgetView } elseif ($script:TaskbarActive) { 'taskbar' } else { 'central' }
    foreach ($row in $script:AppearanceItems) {
        $row.Item.Checked = switch ($row.Kind) {
            'view' { $row.Item.Tag -eq $current }
            'theme' { $row.Item.Tag -eq $script:Appearance.theme }
            'alpha' { [int]$row.Item.Tag -eq [int]$script:Appearance.transparency }
        }
    }
}
function New-FolegoWidgetMenu {
    $strip = New-Object Windows.Forms.ContextMenuStrip
    Add-FolegoAppearanceItems $strip.Items
    $null = $strip.Items.Add('-')
    $null = $strip.Items.Add('Pausar / retomar monitoramento', $null, { Switch-FolegoPause })
    $null = $strip.Items.Add('Abrir a central', $null, { Show-FolegoView central })
    $null = $strip.Items.Add('Ocultar widget (bandeja continua)', $null, { Hide-FolegoWidget })
    $null = $strip.Items.Add('Sair do Fôlego', $null, { $script:Leaving = $true; $form.Close() })
    $strip.Add_Opening({ Sync-FolegoAppearanceChecks })
    return $strip
}
function Switch-FolegoPause {
    $script:Paused = -not $script:Paused; $script:NextPoll = 0L
    $status.Text = 'Monitoramento pausado: ' + $script:Paused
    Update-FolegoWidget
}

# ------------------------------------------------------------------ widget construction
function New-FolegoWidgetLabel([string]$Text, [double]$Size = 9, [bool]$Bold = $false, [string]$Role = 'text') {
    $label = New-Object Windows.Forms.Label
    $label.Text = $Text; $label.AutoSize = $true; $label.Tag = 'role:' + $Role
    $style = if ($Bold) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }
    $label.Font = New-Object Drawing.Font('Segoe UI', [single]$Size, $style)
    $label.Margin = New-Object Windows.Forms.Padding (S 2)
    return $label
}
function New-FolegoWidgetButton([string]$Text, [string]$Tip, [scriptblock]$Action, [int]$Width = 30, [int]$Height = 28) {
    $button = New-Object Windows.Forms.Button
    $button.Text = $Text; $button.TabStop = $false; $button.Size = New-Object Drawing.Size((S $Width), (S $Height))
    $button.Font = New-Object Drawing.Font('Segoe UI Symbol', [single]10.5)
    $button.Margin = New-Object Windows.Forms.Padding (S 2)
    $button.Add_Click($Action)
    $script:WidgetTips.SetToolTip($button, $Tip)
    $button.AccessibleName = $Tip
    return $button
}
function New-FolegoWidgetCell([string]$Caption, [string]$Key, [int]$Width, [int]$Height, [string]$Name) {
    $cell = New-Object Windows.Forms.Panel
    $cell.Tag = 'cell'; $cell.Size = New-Object Drawing.Size((S $Width), (S $Height)); $cell.Margin = New-Object Windows.Forms.Padding (S 2)
    $title = New-FolegoWidgetLabel $Caption 6.5 $false 'muted'; $title.Location = New-Object Drawing.Point((S 5), (S 1))
    $value = New-FolegoWidgetLabel '—' 9.5 $true 'muted'; $value.Location = New-Object Drawing.Point((S 5), (S 13)); $value.AccessibleName = $Name
    $cell.Controls.Add($title); $cell.Controls.Add($value)
    $script:WidgetControls[$Key] = $value; $script:WidgetControls[$Key + 'Caption'] = $title; $script:WidgetControls[$Key + 'Cell'] = $cell
    return $cell
}
function New-FolegoFlow([string]$Direction, [bool]$Wrap = $false) {
    $flow = New-Object Windows.Forms.FlowLayoutPanel
    $flow.FlowDirection = $Direction; $flow.WrapContents = $Wrap; $flow.AutoSize = $true; $flow.AutoSizeMode = 'GrowAndShrink'
    $flow.Margin = New-Object Windows.Forms.Padding 0; $flow.Padding = New-Object Windows.Forms.Padding 0
    return $flow
}
function Add-FolegoMetricCells($Parent, [int]$Width, [int]$Height) {
    foreach ($row in @(@('CPU', 'Cpu', 'Uso da CPU'), @('TEMP', 'Temp', 'Temperatura da zona ACPI'), @('RAM', 'Ram', 'RAM em uso'), @('BAT', 'Bat', 'Bateria'))) {
        $Parent.Controls.Add((New-FolegoWidgetCell $row[0] $row[1] $Width $Height $row[2]))
    }
}
function New-FolegoRing([int]$Side) {
    $ring = New-Object Folego.Windows.HealthRing
    $ring.Size = New-Object Drawing.Size((S $Side), (S $Side)); $ring.Font = New-Object Drawing.Font('Segoe UI', [single]9)
    $ring.Margin = New-Object Windows.Forms.Padding (S 2); $ring.AccessibleName = 'Saúde geral'
    $script:WidgetControls['Ring'] = $ring
    return $ring
}
function New-FolegoStandardButtons($Parent, [string]$View) {
    $Parent.Controls.Add((New-FolegoWidgetButton '⏯' 'Pausar ou retomar o monitoramento' { Switch-FolegoPause }))
    $Parent.Controls.Add((New-FolegoWidgetButton '⊞' 'Abrir a central do Fôlego' { Show-FolegoView central }))
    if ($View -ne 'compact') { $Parent.Controls.Add((New-FolegoWidgetButton '▣' 'Voltar ao widget compacto' { Show-FolegoView compact })) }
    if ($View -eq 'compact') { $Parent.Controls.Add((New-FolegoWidgetButton '▬' 'Mini horizontal' { Show-FolegoView mini })) }
    $menuButton = New-FolegoWidgetButton '☰' 'Visualizações, tema de cores e outros controles' { param($sender, $e) $script:Widget.ContextMenuStrip.Show($sender, (New-Object Drawing.Point(0, $sender.Height))) }
    $Parent.Controls.Add($menuButton)
}
function Build-FolegoWidget([string]$View) {
    $script:WidgetControls = @{}
    $widget = New-Object Folego.Windows.WidgetForm
    $widget.Text = 'Fôlego — widget'; $widget.AccessibleName = 'Widget do Fôlego'
    $widget.Font = New-Object Drawing.Font('Segoe UI', [single]9)
    $widget.Padding = New-Object Windows.Forms.Padding (S 6)
    # One menu for every view: rebuilding a view never duplicates menu items.
    if ($null -eq $script:WidgetMenu) { $script:WidgetMenu = New-FolegoWidgetMenu }
    $widget.ContextMenuStrip = $script:WidgetMenu
    $root = $null
    switch ($View) {
        'mini' {
            $root = New-FolegoFlow 'LeftToRight'
            $grip = New-FolegoWidgetLabel '⋮⋮' 10 $true 'muted'; $grip.Cursor = 'SizeAll'; $grip.Padding = New-Object Windows.Forms.Padding 0, (S 7), 0, 0
            $script:WidgetTips.SetToolTip($grip, 'Arraste para mover a mini horizontal')
            $statusLabel = New-FolegoWidgetLabel '● Aguardando' 9 $true 'muted'
            $statusLabel.AutoSize = $false; $statusLabel.Size = New-Object Drawing.Size((S 104), (S 34)); $statusLabel.TextAlign = 'MiddleLeft'
            $script:WidgetControls['Status'] = $statusLabel
            $root.Controls.Add($grip); $root.Controls.Add($statusLabel)
            Add-FolegoMetricCells $root 54 34
            $root.Controls.Add((New-FolegoWidgetButton '▣' 'Expandir para o widget compacto' { Show-FolegoView compact } 30 34))
            $root.Controls.Add((New-FolegoWidgetButton '☰' 'Visualizações, tema de cores e outros controles' { param($sender, $e) $script:Widget.ContextMenuStrip.Show($sender, (New-Object Drawing.Point(0, $sender.Height))) } 30 34))
        }
        'compact' {
            $root = New-FolegoFlow 'TopDown'
            $header = New-FolegoFlow 'LeftToRight'
            $brand = New-FolegoWidgetLabel 'FÔLEGO' 11 $true 'text'; $brand.AutoSize = $false; $brand.Size = New-Object Drawing.Size((S 132), (S 28)); $brand.TextAlign = 'MiddleLeft'
            $header.Controls.Add($brand); New-FolegoStandardButtons $header 'compact'
            $body = New-FolegoFlow 'LeftToRight'
            $body.Controls.Add((New-FolegoRing 76))
            $readings = New-FolegoFlow 'TopDown'
            foreach ($key in @('Status', 'RamLine', 'CpuLine', 'TempLine', 'BatLine', 'Profile')) {
                $label = New-FolegoWidgetLabel '—' $(if ($key -eq 'Status') { 10 } else { 8.5 }) ($key -eq 'Status') $(if ($key -eq 'Status') { 'muted' } else { 'text' })
                $label.MaximumSize = New-Object Drawing.Size((S 160), 0)
                $script:WidgetControls[$key] = $label; $readings.Controls.Add($label)
            }
            $body.Controls.Add($readings)
            $root.Controls.Add($header); $root.Controls.Add($body)
            $root.MinimumSize = New-Object Drawing.Size((S ($script:FolegoCompactWidth - 12)), 0)
        }
        { $_ -in @('left', 'right') } {
            $root = New-FolegoFlow 'TopDown'
            $root.Controls.Add((New-FolegoWidgetLabel 'FÔLEGO' 10 $true 'text'))
            $root.Controls.Add((New-FolegoRing 76))
            $statusLabel = New-FolegoWidgetLabel 'Aguardando' 9 $true 'muted'; $statusLabel.MaximumSize = New-Object Drawing.Size((S 100), 0)
            $script:WidgetControls['Status'] = $statusLabel; $root.Controls.Add($statusLabel)
            Add-FolegoMetricCells $root 96 36
            $buttons = New-FolegoFlow 'LeftToRight' $true; $buttons.MaximumSize = New-Object Drawing.Size((S 104), 0)
            New-FolegoStandardButtons $buttons $View
            $root.Controls.Add($buttons)
        }
        'top' {
            $root = New-FolegoFlow 'LeftToRight'
            $title = New-FolegoFlow 'TopDown'
            $title.Controls.Add((New-FolegoWidgetLabel 'FÔLEGO' 11 $true 'text'))
            $statusLabel = New-FolegoWidgetLabel 'Aguardando' 10 $true 'muted'; $script:WidgetControls['Status'] = $statusLabel; $title.Controls.Add($statusLabel)
            $root.Controls.Add($title)
            $root.Controls.Add((New-FolegoRing 92))
            Add-FolegoMetricCells $root 72 44
            $detail = New-FolegoWidgetLabel '' 8.5 $false 'text'; $detail.MaximumSize = New-Object Drawing.Size((S 360), (S 96))
            $script:WidgetControls['Reasons'] = $detail; $root.Controls.Add($detail)
            $buttons = New-FolegoFlow 'TopDown' $true; $buttons.MaximumSize = New-Object Drawing.Size(0, (S 100))
            New-FolegoStandardButtons $buttons 'top'
            $root.Controls.Add($buttons)
        }
    }
    $widget.Controls.Add($root)
    # Drag from any surface that is not a button; buttons keep their own click.
    $queue = New-Object 'Collections.Generic.Queue[object]'; $queue.Enqueue($widget)
    while ($queue.Count) {
        $control = $queue.Dequeue()
        if ($control -isnot [Windows.Forms.Button]) { $widget.MakeDraggable($control); $control.ContextMenuStrip = $widget.ContextMenuStrip }
        foreach ($child in $control.Controls) { $queue.Enqueue($child) }
    }
    $widget.Add_DragFinished({ Save-FolegoWidgetPosition })
    Set-FolegoControlTheme $widget
    Set-FolegoMenuTheme $script:WidgetMenu.Items
    $widget.Opacity = 1 - [int]$script:Appearance.transparency / 100.0
    return $widget
}
function Get-FolegoWorkArea {
    $screen = if ($null -ne $script:Widget -and $script:Widget.Visible) { [Windows.Forms.Screen]::FromControl($script:Widget) } else { [Windows.Forms.Screen]::PrimaryScreen }
    return $screen.WorkingArea
}
function Set-FolegoWidgetBounds([string]$View) {
    $widget = $script:Widget; $area = Get-FolegoWorkArea
    if ($View -in $script:FolegoFloatViews) {
        $root = $widget.Controls[0]; $size = $root.GetPreferredSize([Drawing.Size]::Empty)
        $widget.ClientSize = New-Object Drawing.Size(($size.Width + $widget.Padding.Horizontal), ($size.Height + $widget.Padding.Vertical))
        $saved = Get-FolegoValue $script:Appearance.positions $View
        $point = Get-FolegoFloatPosition $saved $widget.Width $widget.Height $area
        $widget.Location = New-Object Drawing.Point($point.X, $point.Y)
    } else {
        $bounds = Get-FolegoDockBounds $View $area
        if ($View -ne 'top') { $bounds.Width = [Math]::Max($bounds.Width, (S 112)) } else { $bounds.Height = [Math]::Max($bounds.Height, (S 120)) }
        $widget.Bounds = New-Object Drawing.Rectangle($bounds.X, $bounds.Y, $bounds.Width, $bounds.Height)
        $widget.Controls[0].AutoSize = $false; $widget.Controls[0].Dock = 'Fill'; $widget.Controls[0].AutoScroll = $true
    }
}
function Save-FolegoWidgetPosition {
    if ($script:WidgetView -notin $script:FolegoFloatViews -or $null -eq $script:Widget) { return }
    try { Save-FolegoAppearanceChange (Set-FolegoWidgetPosition $script:Appearance $script:WidgetView $script:Widget.Left $script:Widget.Top $policy) } catch { $status.Text = [string]$_ }
}
function Hide-FolegoWidget {
    if ($null -ne $script:Widget) { $script:Widget.ContextMenuStrip = $null; $script:Widget.Hide(); $script:Widget.Dispose(); $script:Widget = $null }
    $script:WidgetView = ''; $script:WidgetControls = @{}
    Sync-FolegoAppearanceChecks
}
function Show-FolegoView([string]$View) {
    # Central shows the main window; any widget view collapses the central window to the tray.
    if ($View -notin (Get-FolegoViewKeys $policy)) { $status.Text = 'Visualização desconhecida.'; return }
    if ($View -eq 'central') { Hide-FolegoWidget; Hide-FolegoTaskbarIndicators; Show-Folego; Sync-FolegoAppearanceChecks; return }
    if ($View -eq 'taskbar') { Hide-FolegoWidget; $form.Hide(); Show-FolegoTaskbarIndicators; Sync-FolegoAppearanceChecks; return }
    try {
        $old = $script:Widget
        $script:Widget = Build-FolegoWidget $View; $script:WidgetView = $View
        Set-FolegoWidgetBounds $View
        $script:Widget.Show()
        if ($null -ne $old) { $old.ContextMenuStrip = $null; $old.Hide(); $old.Dispose() }
        $form.Hide(); Hide-FolegoTaskbarIndicators
        if ($script:Appearance.last_widget -ne $View) { Save-FolegoAppearanceChange (Set-FolegoAppearanceField $script:Appearance last_widget $View $policy) }
        Update-FolegoWidget
    } catch { $status.Text = 'Widget indisponível: ' + [string]$_; Hide-FolegoWidget; Show-Folego }
    Sync-FolegoAppearanceChecks
}
function Switch-FolegoWidget {
    if ($script:WidgetView) { Show-FolegoView central } else { Show-FolegoView $script:Appearance.last_widget }
}

# ------------------------------------------------------------------ live data
function Set-FolegoWidgetText([string]$Key, [string]$Text, [string]$Role) {
    $control = $script:WidgetControls[$Key]
    if ($null -eq $control) { return }
    $control.Text = $Text
    if ($Role) { $control.Tag = 'role:' + $Role; $control.ForeColor = Get-FolegoRoleColor $Role }
}
function Update-FolegoWidget {
    Update-FolegoTrayStatus; Update-FolegoTaskbarIndicators
    if ($null -eq $script:Widget -or $null -eq $script:WidgetData) { return }
    $d = $script:WidgetData; $m = $d.Metrics
    $statusText = $m.Status.Text; $statusRole = $m.Status.Role
    if ($script:Paused) { $statusText = 'Pausado'; $statusRole = 'muted' }
    elseif ($script:WidgetStale) { $statusText = 'Amostra antiga'; $statusRole = 'muted' }
    Set-FolegoWidgetText 'Status' $(if ($script:WidgetView -eq 'mini') { '● ' + $statusText } else { $statusText }) $statusRole
    foreach ($key in @('Cpu', 'Temp', 'Ram', 'Bat')) { Set-FolegoWidgetText $key $m.$key.Text $m.$key.Role }
    Set-FolegoWidgetText 'BatCaption' $m.Bat.Caption ''
    $cell = $script:WidgetControls['BatCell']; if ($null -ne $cell) { $cell.Visible = [bool]$m.Bat.Visible }
    Set-FolegoWidgetText 'RamLine' $d.RamLine $m.Ram.Role
    Set-FolegoWidgetText 'CpuLine' ('CPU ' + $m.Cpu.Text) $m.Cpu.Role
    Set-FolegoWidgetText 'TempLine' ('Zona ' + $m.Temp.Text) $m.Temp.Role
    Set-FolegoWidgetText 'BatLine' $(if ($m.Bat.Visible) { 'Bateria ' + $m.Bat.Text + $(if ($m.Bat.Caption -eq 'TOMADA') { ' · tomada' } else { '' }) } else { 'Bateria indisponível' }) $m.Bat.Role
    Set-FolegoWidgetText 'Profile' $d.Profile 'muted'
    Set-FolegoWidgetText 'Reasons' $d.Reasons ''
    $ring = $script:WidgetControls['Ring']
    if ($null -ne $ring) {
        $ring.Value = if ($script:WidgetStale) { $null } else { $m.Headroom }
        $ring.Verdict = $statusText; $ring.RingColor = Get-FolegoRoleColor $statusRole; $ring.Invalidate()
    }
    $tip = $statusText + ' | CPU ' + $m.Cpu.Text + ' | ' + $m.Temp.Text + ' | RAM ' + $m.Ram.Text
    $script:WidgetTips.SetToolTip($script:Widget, $tip)
}

# ------------------------------------------------------------------ taskbar indicators
# Windows 11 has no deskbands; injecting a window into explorer.exe would be fragile on a
# host where the shell already restarts. Native notification-area icons are re-added by
# Windows after an explorer restart and need no privilege.
$script:TaskbarActive = $false; $script:TaskbarIcons = [ordered]@{}; $script:TaskbarDrawn = @{}; $script:TrayDrawn = ''
function Get-FolegoInk([string]$Hex) {
    $c = ConvertTo-FolegoColor $Hex
    $channel = { param($v) $x = $v / 255.0; if ($x -le 0.04045) { $x / 12.92 } else { [Math]::Pow(($x + 0.055) / 1.055, 2.4) } }
    $l = 0.2126 * (& $channel $c.R) + 0.7152 * (& $channel $c.G) + 0.0722 * (& $channel $c.B)
    # Same rule as palettes.on_color: the ink with the higher contrast wins.
    if ((($l + 0.05) / 0.0555) -ge (1.05 / ($l + 0.05))) { return [Drawing.Color]::FromArgb(16, 16, 16) }
    return [Drawing.Color]::White
}
function Set-FolegoNotifyIcon($Notify, $Icon) {
    $old = $Notify.Icon; $Notify.Icon = $Icon
    if ($null -ne $old -and $old -ne [Drawing.SystemIcons]::Information) { $old.Dispose() }
}
function Get-FolegoShortTip([string]$Text) { if ($Text.Length -le 63) { return $Text }; return $Text.Substring(0, 62) + '…' }
function Update-FolegoTrayStatus {
    # The main tray icon is always a status dot in the current health colour.
    if ($null -eq $script:WidgetData) { return }
    $role = $script:WidgetData.Metrics.Status.Role
    if ($script:Paused -or $script:WidgetStale) { $role = 'muted' }
    $key = $role + '|' + $script:Appearance.theme
    if ($key -eq $script:TrayDrawn) { return }
    $size = [Windows.Forms.SystemInformation]::SmallIconSize.Width
    Set-FolegoNotifyIcon $tray ([Folego.Windows.TrayGlyph]::Dot((Get-FolegoRoleColor $role), (ConvertTo-FolegoColor $script:Tokens.border), $size))
    $script:TrayDrawn = $key
}
function Show-FolegoQuickMenu($Notify) { [Folego.Windows.TrayGlyph]::ShowMenu($Notify) }
function New-FolegoTaskbarIcon([string]$Key) {
    $notify = New-Object Windows.Forms.NotifyIcon
    $notify.ContextMenuStrip = $menu
    $notify.Text = 'Fôlego'
    $notify.Add_MouseUp({ param($sender, $e) if ($e.Button -eq [Windows.Forms.MouseButtons]::Left) { Show-FolegoQuickMenu $sender } })
    return $notify
}
function Update-FolegoTaskbarIndicators {
    if (-not $script:TaskbarActive -or $null -eq $script:WidgetData) { return }
    $metrics = $script:WidgetData.Metrics
    $rows = @(Get-FolegoTrayIndicators $metrics)
    $actions = @((Get-FolegoTheme $policy $script:Appearance.theme).actions)
    $size = [Windows.Forms.SystemInformation]::SmallIconSize.Width
    $wanted = @($rows | ForEach-Object { $_.Key })
    foreach ($key in @($script:TaskbarIcons.Keys)) {
        if ($key -notin $wanted) { $gone = $script:TaskbarIcons[$key]; $gone.Visible = $false; $gone.Dispose(); $script:TaskbarIcons.Remove($key); $script:TaskbarDrawn.Remove($key) }
    }
    foreach ($row in $rows) {
        if (-not $script:TaskbarIcons.Contains($row.Key)) { $script:TaskbarIcons[$row.Key] = New-FolegoTaskbarIcon $row.Key }
        $notify = $script:TaskbarIcons[$row.Key]
        $role = if ($script:Paused -or $script:WidgetStale) { 'muted' } else { $row.Role }
        $drawn = $row.Text + '|' + $role + '|' + $script:Appearance.theme + '|' + $size
        if ($script:TaskbarDrawn[$row.Key] -ne $drawn) {
            $background = Get-FolegoValue $script:Tokens $role $script:Tokens.muted
            $icon = [Folego.Windows.TrayGlyph]::Text($row.Text, (ConvertTo-FolegoColor $background), (Get-FolegoInk $background), (ConvertTo-FolegoColor $actions[$row.Strip % $actions.Count]), $size)
            Set-FolegoNotifyIcon $notify $icon
            $script:TaskbarDrawn[$row.Key] = $drawn
        }
        $suffix = if ($script:Paused) { ' (pausado)' } elseif ($script:WidgetStale) { ' (amostra antiga)' } else { '' }
        $notify.Text = Get-FolegoShortTip ($row.Tip + $suffix)
        if (-not $notify.Visible) { $notify.Visible = $true }
    }
}
function Show-FolegoTaskbarIndicators {
    $script:TaskbarActive = $true; $script:TaskbarDrawn = @{}
    # Show neutral placeholders at once; the first collection can take tens of seconds cold.
    if ($null -eq $script:WidgetData) { $script:WidgetData = [pscustomobject]@{ Metrics = (Get-FolegoMiniMetrics $null $null 'unknown' $policy $false); RamLine = 'RAM —'; Profile = 'Perfil desconhecido'; Reasons = '' } }
    Update-FolegoTrayStatus; Update-FolegoTaskbarIndicators
    if (-not (Get-FolegoValue $script:Appearance taskbar_hint $false)) {
        $tray.BalloonTipTitle = 'Fôlego na barra de tarefas'
        $tray.BalloonTipText = 'Clique em um indicador para as funções. O Windows 11 pode guardar ícones novos em ^: para deixá-los sempre visíveis, use Configurações → Barra de tarefas → Outros ícones da bandeja.'
        $tray.BalloonTipIcon = 'Info'; $tray.ShowBalloonTip(10000)
        try { Save-FolegoAppearanceChange (Set-FolegoAppearanceField $script:Appearance taskbar_hint $true $policy) } catch { }
    }
}
function Hide-FolegoTaskbarIndicators {
    $script:TaskbarActive = $false
    foreach ($notify in @($script:TaskbarIcons.Values)) { $notify.Visible = $false; $notify.Dispose() }
    $script:TaskbarIcons = [ordered]@{}; $script:TaskbarDrawn = @{}
}
function Open-FolegoCentralTab([string]$Name, [string]$Action = '') {
    # Opening the central window from the taskbar menu keeps the indicators in place.
    Show-Folego
    foreach ($page in $tabs.TabPages) { if ($page.Text -eq $Name) { $tabs.SelectedTab = $page } }
    if ($Action) { Request-Folego $Action }
}
function New-FolegoQuickMenu {
    $strip = New-Object Windows.Forms.ContextMenuStrip
    $summary = $strip.Items.Add('Fôlego — aguardando leitura'); $summary.Enabled = $false
    $null = $strip.Items.Add('-')
    $null = $strip.Items.Add('Abrir a central', $null, { Show-Folego })
    $thermal = New-Object Windows.Forms.ToolStripMenuItem 'Temperatura e CPU'
    $null = $thermal.DropDownItems.Add('Aplicar perfil Fresco (turbo desligado)…', $null, {
        if (Confirm-Folego 'Perfil térmico' ('Aplicar Fresco ao plano ativo? CPU máxima ' + $policy.windows.thermal.profiles.Fresco.throttle_max + '% e turbo desligado. Os valores atuais serão registrados antes da troca.')) { Request-Folego Fresco }
    })
    $null = $thermal.DropDownItems.Add('Aplicar perfil Contenção…', $null, {
        if (Confirm-Folego 'Perfil térmico' ('Aplicar Contenção ao plano ativo? CPU máxima ' + $policy.windows.thermal.profiles.Contencao.throttle_max + '% e turbo desligado. Os valores atuais serão registrados antes.')) { Request-Folego Contencao }
    })
    $null = $thermal.DropDownItems.Add('Restaurar os valores originais…', $null, {
        if (Confirm-Folego 'Perfil térmico' 'Devolver os limites originais do recibo? Só ocorre no mesmo host/boot e se ninguém os alterou.') { Request-Folego ThermalRestore }
    })
    $null = $thermal.DropDownItems.Add('Ver temperatura, perfil e recibo', $null, { Open-FolegoCentralTab 'Temperatura e CPU' })
    $null = $strip.Items.Add($thermal)
    $null = $strip.Items.Add('Analisar consumidores e órfãos', $null, { $script:TriageFilter = ''; Open-FolegoCentralTab 'Consumidores' 'Consumers' })
    $null = $strip.Items.Add('Inicialização do Windows', $null, { Open-FolegoCentralTab 'Inicialização' 'StartupList' })
    $null = $strip.Items.Add('Pausar / retomar monitoramento', $null, { Switch-FolegoPause })
    $null = $strip.Items.Add('-')
    Add-FolegoAppearanceItems $strip.Items
    $null = $strip.Items.Add('Deixar os indicadores sempre visíveis…', $null, { Start-Process 'ms-settings:taskbar'; $status.Text = 'Em Outros ícones da bandeja, ligue os ícones do Fôlego (Windows PowerShell).' })
    $null = $strip.Items.Add('Gerenciador de Tarefas', $null, { Start-Process taskmgr.exe })
    $null = $strip.Items.Add('-')
    $null = $strip.Items.Add('Sair do Fôlego', $null, { $script:Leaving = $true; $form.Close() })
    $strip.Add_Opening({
        param($sender, $e)
        Sync-FolegoAppearanceChecks
        if ($null -ne $script:WidgetData) {
            $m = $script:WidgetData.Metrics
            $sender.Items[0].Text = Get-FolegoShortTip ('Fôlego — ' + $m.Status.Text + ' · CPU ' + $m.Cpu.Text + ' · ' + $m.Temp.Text + ' · RAM ' + $m.Ram.Text)
        }
    })
    return $strip
}

# ------------------------------------------------------------------ startup progress
# Visible, non-blocking notice while Fôlego serializes the logon; ends with the completion time.
$script:Progress = $null; $script:ProgressControls = @{}; $script:ProgressCloseAt = 0L
function Get-FolegoBootElapsed {
    try { return ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse([string]$script:HostInfo.Boot)).TotalSeconds } catch { return $null }
}
function Show-FolegoProgress([int]$Total) {
    if ($null -ne $script:Progress) { return }
    $window = New-Object Folego.Windows.WidgetForm
    $window.Text = 'Fôlego — organizando a inicialização'; $window.AccessibleName = 'Progresso da inicialização do Fôlego'
    $window.Font = New-Object Drawing.Font('Segoe UI', [single]9.5)
    $window.Padding = New-Object Windows.Forms.Padding (S 10)
    $flow = New-FolegoFlow 'TopDown'
    $script:ProgressControls = @{}
    foreach ($row in @(@('Title', 'Fôlego está organizando a inicialização', 11, $true, 'text'), @('Hint', 'Aguarde: os programas de início sobem um de cada vez para não sobrecarregar o Deck.', 9, $false, 'muted'), @('Timer', 'Desde o boot: —', 14, $true, 'accent'), @('Items', '', 9.5, $false, 'text'), @('Wait', '', 8.5, $false, 'muted'))) {
        $label = New-FolegoWidgetLabel $row[1] $row[2] $row[3] $row[4]
        $label.MaximumSize = New-Object Drawing.Size((S 340), 0)
        $script:ProgressControls[$row[0]] = $label; $flow.Controls.Add($label)
    }
    $hide = New-FolegoWidgetButton 'Ocultar' 'Ocultar este aviso; a organização continua' { if ($null -ne $script:Progress) { $script:Progress.Hide() } } 80 28
    $flow.Controls.Add($hide)
    $window.Controls.Add($flow)
    $queue = New-Object 'Collections.Generic.Queue[object]'; $queue.Enqueue($window)
    while ($queue.Count) { $c = $queue.Dequeue(); if ($c -isnot [Windows.Forms.Button]) { $window.MakeDraggable($c) }; foreach ($child in $c.Controls) { $queue.Enqueue($child) } }
    Set-FolegoControlTheme $window
    $size = $flow.GetPreferredSize([Drawing.Size]::Empty)
    $window.ClientSize = New-Object Drawing.Size(($size.Width + $window.Padding.Horizontal), ($size.Height + $window.Padding.Vertical))
    $area = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $window.Location = New-Object Drawing.Point(($area.Right - $window.Width - 24), ($area.Bottom - $window.Height - 24))
    $script:Progress = $window
    $script:ProgressControls['Items'].Text = $(if ($Total) { ('Itens: 0 de ' + $Total) } else { 'Nenhum programa adotado; aguardando o sistema assentar.' })
    $window.Show()
}
function Update-FolegoProgress {
    if ($null -eq $script:Progress -or $script:Progress.IsDisposed) { return }
    $elapsed = Get-FolegoBootElapsed
    if ($null -ne $script:SequenceRun) {
        if ($null -ne $elapsed) { $script:ProgressControls['Timer'].Text = 'Desde o boot: ' + (Format-FolegoElapsed $elapsed) }
        $run = $script:SequenceRun; $total = @($run.Keys).Count; $done = [Math]::Min($run.Index, $total)
        $current = if ($done -lt $total) { [string]@($run.Keys)[$done] } else { '' }
        $left = $total - $done
        $estimate = if ($left -gt 0) { ' — restante estimado ≈ ' + (Format-FolegoElapsed ($left * ([double]$policy.windows.sequence.gap_seconds + [double]$policy.windows.sequence.poll_seconds * [double]$policy.windows.sequence.calm_samples))) } else { '' }
        $script:ProgressControls['Items'].Text = $(if ($total) { ('Itens: ' + $done + ' de ' + $total + $(if ($current) { ' — próximo: ' + ($current -replace '^[^|]*\|', '') } else { ' — confirmando que o sistema assentou' }) + $estimate) } else { 'Nenhum programa adotado; confirmando que o sistema assentou.' })
        $waiting = @($run.Waiting)
        $script:ProgressControls['Wait'].Text = $(if ($waiting.Count) { 'Aguardando: ' + ($waiting -join ', ') } else { '' })
    }
    if ($script:ProgressCloseAt -gt 0 -and [long][Folego.Windows.Native]::GetTickCount64() -ge $script:ProgressCloseAt) { Close-FolegoProgress }
}
function Complete-FolegoProgress([bool]$Calm, $Reasons, [int]$Launched, [int]$Total) {
    $elapsed = Get-FolegoBootElapsed
    $time = if ($null -ne $elapsed) { Format-FolegoElapsed $elapsed } else { '—' }
    $title = if ($Calm) { 'Sistema completamente inicializado em ' + $time } else { 'Inicialização concluída em ' + $time }
    $detail = ('{0} de {1} programas iniciados em série.' -f $Launched, $Total) + $(if (-not $Calm -and @($Reasons).Count) { ' O sistema ainda não ficou calmo: ' + (@($Reasons) -join ', ') } else { '' })
    if ($null -ne $script:Progress -and -not $script:Progress.IsDisposed) {
        Set-FolegoWidgetTextOn $script:ProgressControls['Title'] $title $(if ($Calm) { 'ok' } else { 'warning' })
        $script:ProgressControls['Hint'].Text = 'Pode usar o Deck normalmente.'
        $script:ProgressControls['Timer'].Text = $time
        $script:ProgressControls['Items'].Text = $detail; $script:ProgressControls['Wait'].Text = 'Registro em Inicialização → Sequência de início.'
        if (-not $script:Progress.Visible) { $script:Progress.Show() }
        $script:ProgressCloseAt = [long][Folego.Windows.Native]::GetTickCount64() + 20000
    }
    $tray.BalloonTipTitle = 'Fôlego'; $tray.BalloonTipIcon = 'Info'; $tray.BalloonTipText = $title + '. ' + $detail; $tray.ShowBalloonTip(10000)
    return ($title + '. ' + $detail)
}
function Set-FolegoWidgetTextOn($Control, [string]$Text, [string]$Role) { $Control.Text = $Text; $Control.Tag = 'role:' + $Role; $Control.ForeColor = Get-FolegoRoleColor $Role }
function Close-FolegoProgress {
    if ($null -ne $script:Progress) { $script:Progress.Hide(); $script:Progress.Dispose(); $script:Progress = $null }
    $script:ProgressCloseAt = 0L
}
