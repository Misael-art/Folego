# Forms surfaces for the shared catalog, the private editor and the opt-in text companion.
$script:PromptWatcher = $null
$script:PromptFlyout = $null
$script:PromptFlyoutMenu = $null
$script:PromptFlyoutTimer = $null
$script:PromptShortcutTimer = $null
$script:PendingPromptShortcut = $null
$script:PromptFlyoutFeedback = $false
$script:UpdatingPromptPreference = $false

function Copy-FolegoPromptText([string]$Text) {
    [Windows.Forms.Clipboard]::SetDataObject($Text, $true, 2, 30)
    $status.Text = 'Copiado. Cole no aplicativo desejado.'
}
function Show-FolegoPromptFeedback([string]$Message, [string]$Brief) {
    $status.Text = $Message
    if ($null -eq $script:PromptFlyout) { return }
    $script:PromptFlyoutFeedback = $true
    $script:PromptFlyout.Controls[0].Text = $Brief
    $script:PromptFlyout.Controls[0].Enabled = $false
    $script:PromptFlyout.Show()
    $script:PromptFlyoutTimer.Stop()
    $script:PromptFlyoutTimer.Interval = 1600
    $script:PromptFlyoutTimer.Start()
}
function Initialize-FolegoTextContext {
    if ($null -ne ('Folego.Windows.TextContextWatcher' -as [type])) { return }
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, WindowsBase
    $references = @(
        'System.Windows.Forms', 'System.Drawing',
        [Windows.Automation.AutomationElement].Assembly.Location,
        [Windows.Automation.ControlType].Assembly.Location,
        [Windows.Point].Assembly.Location
    )
    Add-Type -Path (Join-Path $script:FolegoRoot 'TextContext.cs') -ReferencedAssemblies $references
}
function Invoke-FolegoPromptCommand($Command) {
    try {
        if ($Command.Action -eq 'desktop') { Switch-FolegoDesktop; return }
        if ($Command.Action -eq 'keys') {
            if ($null -eq $script:PromptWatcher -or $null -eq $Command.Target) { throw 'Abra Prompts e atalhos em um campo editável do aplicativo de destino.' }
            $script:PendingPromptShortcut = [pscustomobject]@{ Target = $Command.Target; Keys = [int[]]@(Get-FolegoShortcutKeys $Command.Value) }
            $script:PromptShortcutTimer.Stop()
            $script:PromptShortcutTimer.Start()
            return
        }
        if ($Command.Target -is [Windows.Forms.TextBoxBase]) {
            $box = $Command.Target
            if ($box.IsDisposed -or $box.ReadOnly -or -not $box.Enabled) { throw 'O campo já não pode ser editado.' }
            if (-not $box.Multiline -and $Command.Value -match '[\r\n]') { throw 'Use um campo de várias linhas para inserir este texto.' }
            if ($box.MaxLength -gt 0 -and $box.TextLength - $box.SelectionLength + $Command.Value.Length -gt $box.MaxLength) { throw 'O texto ultrapassa o limite deste campo.' }
            $box.SelectedText = $Command.Value
            $status.Text = 'Texto inserido.'
        } else {
            Copy-FolegoPromptText $Command.Value
            if ($null -ne $Command.Target) { Show-FolegoPromptFeedback $status.Text 'Copiado · Cole no campo' }
        }
    } catch {
        if ($null -ne $Command.Target -and $Command.Target -isnot [Windows.Forms.TextBoxBase]) { Show-FolegoPromptFeedback $_.Exception.Message 'Confira a Central do Fôlego' }
        else { $status.Text = $_.Exception.Message }
    }
}
function Add-FolegoPromptChoice($Items, [string]$Title, [string]$Action, [string]$Value, $Target) {
    $item = New-Object Windows.Forms.ToolStripMenuItem
    $item.Text = $Title.Replace('&', '&&')
    $item.AccessibleName = $Title
    $item.Tag = [pscustomobject]@{ Action = $Action; Value = $Value; Target = $Target }
    $item.Add_Click({ param($sender, $eventArgs) Invoke-FolegoPromptCommand $sender.Tag })
    $null = $Items.Add($item)
}
function Add-FolegoExternalShortcutGroups($Items, $Target) {
    $groups = [ordered]@{
        'Janelas' = @(
            @('Alternar aplicativo', 'Alt+Tab'), @('Visão geral das janelas', 'Win+Tab'),
            @('Janela à esquerda', 'Win+Left'), @('Janela à direita', 'Win+Right')
        )
        'Edição' = @(
            @('Selecionar tudo', 'Ctrl+A'), @('Copiar', 'Ctrl+C'), @('Colar', 'Ctrl+V'),
            @('Desfazer', 'Ctrl+Z'), @('Refazer', 'Ctrl+Y'), @('Salvar', 'Ctrl+S'), @('Buscar', 'Ctrl+F')
        )
        'Terminal' = @(
            @('Copiar no terminal', 'Ctrl+Shift+C'), @('Colar no terminal', 'Ctrl+Shift+V')
        )
    }
    foreach ($name in $groups.Keys) {
        $section = New-Object Windows.Forms.ToolStripMenuItem $name
        foreach ($row in $groups[$name]) { Add-FolegoPromptChoice $section.DropDownItems ($row[0] + ' · ' + $row[1]) keys $row[1] $Target }
        $null = $Items.Add($section)
    }
}
function Update-FolegoPersonalMenu($Menu) {
    foreach ($previous in @($Menu.DropDownItems)) { $previous.Dispose() }
    $target = $Menu.Tag
    try {
        $snapshot = Get-FolegoCustomPrompts $DataRoot
        foreach ($row in $snapshot.Entries) {
            $item = New-Object Windows.Forms.ToolStripMenuItem
            $item.Text = $row.title.Replace('&', '&&')
            $item.AccessibleName = $row.title
            $item.Tag = [pscustomobject]@{ Id = $row.id; Revision = $snapshot.Revision; Target = $target }
            if ($row.kind -eq 'macro' -and $row.action -eq 'keys' -and ($null -eq $target -or $target -is [Windows.Forms.TextBoxBase])) {
                $item.Enabled = $false
                $item.Text += ' · ' + $row.shortcut
                $item.ToolTipText = 'Abra o painel em um campo de outro aplicativo ou use o teclado virtual.'
            }
            $item.Add_Click({
                param($sender, $eventArgs)
                try {
                    $fresh = Get-FolegoCustomPrompts $DataRoot
                    if ($fresh.Revision -cne $sender.Tag.Revision) { throw 'A biblioteca mudou. Reabra o menu.' }
                    $entry = @($fresh.Entries | Where-Object { $_.id -ceq $sender.Tag.Id })[0]
                    if ($null -eq $entry) { throw 'O item foi removido. Reabra o menu.' }
                    $action = if ($entry.kind -eq 'text') { 'text' } else { $entry.action }
                    $content = if ($action -eq 'text') { $entry.text } elseif ($action -eq 'keys') { $entry.shortcut } else { '' }
                    Invoke-FolegoPromptCommand ([pscustomobject]@{ Action = $action; Value = $content; Target = $sender.Tag.Target })
                } catch { $status.Text = $_.Exception.Message }
            })
            $null = $Menu.DropDownItems.Add($item)
        }
    } catch {
        $unavailable = $Menu.DropDownItems.Add('Biblioteca indisponível · confira na Central')
        $unavailable.Enabled = $false
    }
    if ($Menu.DropDownItems.Count) { $null = $Menu.DropDownItems.Add('-') }
    $null = $Menu.DropDownItems.Add('Editar textos e macros…', $null, { Open-FolegoCentralTab 'Prompts e atalhos' })
    Set-FolegoMenuTheme $Menu.DropDownItems
}
function Add-FolegoPromptMenu($Items, $Target = $null) {
    $parent = New-Object Windows.Forms.ToolStripMenuItem 'Prompts e atalhos'
    $catalogTarget = if ($Target -is [Windows.Forms.TextBoxBase] -and -not $Target.Multiline) { $null } else { $Target }
    $promptsTitle = if ($catalogTarget -is [Windows.Forms.TextBoxBase]) { 'Inserir prompt' } else { 'Copiar prompt' }
    $catalog = New-Object Windows.Forms.ToolStripMenuItem $promptsTitle
    foreach ($category in @($policy.windows.prompts)) {
        $group = New-Object Windows.Forms.ToolStripMenuItem ([string]$category.name)
        foreach ($prompt in @($category.items)) { Add-FolegoPromptChoice $group.DropDownItems $prompt.title text $prompt.text $catalogTarget }
        $null = $catalog.DropDownItems.Add($group)
    }
    $null = $parent.DropDownItems.Add($catalog)
    $shortcuts = New-Object Windows.Forms.ToolStripMenuItem 'Atalhos de teclado'
    if ($null -ne $Target -and $Target -isnot [Windows.Forms.TextBoxBase]) { Add-FolegoExternalShortcutGroups $shortcuts.DropDownItems $Target }
    Add-FolegoDesktopItems $shortcuts.DropDownItems
    $null = $parent.DropDownItems.Add($shortcuts)
    $custom = New-Object Windows.Forms.ToolStripMenuItem 'Personalizados'
    $custom.Tag = $Target
    $null = $custom.DropDownItems.Add('Carregar biblioteca')
    $custom.Add_DropDownOpening({ param($sender, $eventArgs) Update-FolegoPersonalMenu $sender })
    $null = $parent.DropDownItems.Add($custom)
    $null = $Items.Add($parent)
}
function Add-FolegoEditContext($Field) {
    $strip = New-Object Windows.Forms.ContextMenuStrip
    $strip.Tag = $Field
    $commands = [ordered]@{
        'Desfazer' = 'Undo'; 'Recortar' = 'Cut'; 'Copiar' = 'Copy'; 'Colar' = 'Paste'
        'Excluir seleção' = 'Delete'; 'Selecionar tudo' = 'SelectAll'
    }
    foreach ($name in $commands.Keys) {
        $item = $strip.Items.Add($name)
        $item.Tag = $commands[$name]
        $item.Add_Click({
            param($sender, $eventArgs)
            $box = $sender.Owner.Tag
            if ($box.IsDisposed -or $box.ReadOnly) { return }
            if ($sender.Tag -eq 'Delete') { $box.SelectedText = '' }
            else { $method = [string]$sender.Tag; $box.$method() }
        })
    }
    $null = $strip.Items.Add('-')
    Add-FolegoPromptMenu $strip.Items $Field
    $strip.Add_Opening({
        param($sender, $eventArgs)
        $box = $sender.Tag
        if ($box.ReadOnly -or $box.IsDisposed) { $eventArgs.Cancel = $true; return }
        $sender.Items[0].Enabled = $box.CanUndo
        foreach ($index in @(1, 2, 4)) { $sender.Items[$index].Enabled = $box.SelectionLength -gt 0 }
        $sender.Items[3].Enabled = $false
        try { $sender.Items[3].Enabled = [Windows.Forms.Clipboard]::ContainsText() } catch { }
        $sender.Items[5].Enabled = $box.TextLength -gt 0
        Set-FolegoMenuTheme $sender.Items
    })
    $Field.ContextMenuStrip = $strip
    $Field.Add_Disposed({ param($sender, $eventArgs) if ($null -ne $sender.ContextMenuStrip) { $sender.ContextMenuStrip.Dispose() } })
}
function Close-FolegoPromptFlyout {
    if ($null -ne $script:PromptFlyoutTimer) { $script:PromptFlyoutTimer.Stop() }
    if ($null -ne $script:PromptFlyoutMenu) { $script:PromptFlyoutMenu.Dispose(); $script:PromptFlyoutMenu = $null }
    if ($null -ne $script:PromptFlyout) { $script:PromptFlyout.Dispose(); $script:PromptFlyout = $null }
    $script:PromptFlyoutFeedback = $false
}
function Show-FolegoPromptFlyout($Target) {
    Close-FolegoPromptFlyout
    $panel = New-Object Folego.Windows.WidgetForm
    $panel.Text = 'Prompts e atalhos do Fôlego'
    $button = New-Object Windows.Forms.Button
    $button.Text = 'Prompts e atalhos  ›'
    $button.AccessibleName = 'Abrir prompts e atalhos do Fôlego'
    $button.Tag = $Target
    $button.Dock = 'Fill'
    $panel.ClientSize = New-Object Drawing.Size((S 174), (S 38))
    $panel.Controls.Add($button)
    $bounds = [Windows.Forms.Screen]::FromPoint($Target.Position).WorkingArea
    $x = [Math]::Max($bounds.Left, [Math]::Min($Target.Position.X + (S 10), $bounds.Right - $panel.Width))
    $y = $Target.Position.Y - $panel.Height - (S 8)
    if ($y -lt $bounds.Top) { $y = [Math]::Min($Target.Position.Y + (S 12), $bounds.Bottom - $panel.Height) }
    $panel.Location = New-Object Drawing.Point($x, [Math]::Max($bounds.Top, $y))
    $script:PromptFlyout = $panel
    $button.Add_Click({
        param($sender, $eventArgs)
        if ($null -eq $script:PromptFlyoutMenu) {
            $script:PromptFlyoutMenu = New-Object Windows.Forms.ContextMenuStrip
            Add-FolegoPromptMenu $script:PromptFlyoutMenu.Items $sender.Tag
            Set-FolegoMenuTheme $script:PromptFlyoutMenu.Items
            $script:PromptFlyoutMenu.Add_Closed({
                if ($null -ne $script:PromptFlyout -and -not $script:PromptFlyoutFeedback) { $script:PromptFlyout.Hide() }
            })
        }
        $script:PromptFlyoutMenu.Show($sender, (New-Object Drawing.Point(0, 0)), 'AboveRight')
    })
    Set-FolegoControlTheme $panel
    $panel.Show()
    $script:PromptFlyoutTimer.Interval = 8000
    $script:PromptFlyoutTimer.Start()
}
function Set-FolegoExternalPromptMenu([bool]$Enabled) {
    if (-not $Enabled) {
        $script:PendingPromptShortcut = $null
        if ($null -ne $script:PromptShortcutTimer) { $script:PromptShortcutTimer.Stop() }
        if ($null -ne $script:PromptWatcher) { $script:PromptWatcher.Dispose(); $script:PromptWatcher = $null }
        Close-FolegoPromptFlyout
        return
    }
    if ($null -ne $script:PromptWatcher) { return }
    Initialize-FolegoTextContext
    $null = $form.Handle
    $script:PromptWatcher = New-Object Folego.Windows.TextContextWatcher $form
    $script:PromptWatcher.Add_Found({ param($sender, $target) Show-FolegoPromptFlyout $target })
    $script:PromptWatcher.Add_ShortcutCompleted({
        param($sender, $result)
        $message = if ($result.Sent) { 'Atalho enviado ao aplicativo.' } else { 'O campo ou o foco mudou. Reabra o painel no destino ou use o teclado virtual.' }
        if ($null -ne $script:PromptFlyout -and [object]::ReferenceEquals($script:PromptFlyout.Controls[0].Tag, $result.Target)) {
            Show-FolegoPromptFeedback $message $(if ($result.Sent) { 'Atalho enviado' } else { 'Foco indisponível' })
        } else { $status.Text = $message }
    })
}
function Initialize-FolegoPromptTimers {
    $script:PromptFlyoutTimer = New-Object Windows.Forms.Timer
    $script:PromptFlyoutTimer.Interval = 8000
    $script:PromptFlyoutTimer.Add_Tick({ if ($null -eq $script:PromptFlyoutMenu -or -not $script:PromptFlyoutMenu.Visible) { Close-FolegoPromptFlyout } })
    $script:PromptShortcutTimer = New-Object Windows.Forms.Timer
    $script:PromptShortcutTimer.Interval = 100
    $script:PromptShortcutTimer.Add_Tick({
        $script:PromptShortcutTimer.Stop()
        $job = $script:PendingPromptShortcut
        $script:PendingPromptShortcut = $null
        if ($null -ne $script:PromptWatcher -and $null -ne $job) { $script:PromptWatcher.ApplyShortcut($job.Target, $job.Keys) }
    })
}
function Stop-FolegoPromptSurface {
    Set-FolegoExternalPromptMenu $false
    foreach ($timer in @($script:PromptShortcutTimer, $script:PromptFlyoutTimer)) {
        if ($null -ne $timer) { $timer.Stop(); $timer.Dispose() }
    }
}

function Set-FolegoPromptEditorRow($Entry) {
    $editor = $script:PromptEditor
    $editor.Id = Get-FolegoValue $Entry id
    $editor.Title.Text = [string](Get-FolegoValue $Entry title)
    if ((Get-FolegoValue $Entry kind) -ne 'macro') {
        $editor.Kind.SelectedIndex = 0
        $editor.Body.Text = [string](Get-FolegoValue $Entry text)
    } elseif ($Entry.action -eq 'keys') {
        $editor.Kind.SelectedIndex = 1
        $editor.Body.Text = $Entry.shortcut
    } else {
        $editor.Kind.SelectedIndex = 2
        $editor.Body.Text = ''
    }
}
function Update-FolegoPromptEditor([string]$Id = '') {
    $editor = $script:PromptEditor
    $editor.Snapshot = $null
    $editor.List.Items.Clear()
    try {
        $editor.Snapshot = Get-FolegoCustomPrompts $DataRoot
        for ($index = 0; $index -lt $editor.Snapshot.Entries.Count; $index++) {
            $entry = $editor.Snapshot.Entries[$index]
            $null = $editor.List.Items.Add($entry.title)
            if ($entry.id -ceq $Id) { $editor.List.SelectedIndex = $index }
        }
        $editor.Note.Text = ('{0} de 32 itens pessoais' -f $editor.Snapshot.Entries.Count)
        if ($editor.List.SelectedIndex -lt 0) { Set-FolegoPromptEditorRow $null }
    } catch { $editor.Note.Text = $_.Exception.Message }
    $editor.Loaded = $true
}
function Save-FolegoPromptEditor {
    $editor = $script:PromptEditor
    try {
        if ($null -eq $editor.Snapshot) { throw 'Recarregue a biblioteca antes de salvar.' }
        $id = if ($editor.Id) { $editor.Id } else { [Guid]::NewGuid().ToString('N') }
        $title = $editor.Title.Text.Trim()
        $entry = switch ($editor.Kind.SelectedIndex) {
            0 { [pscustomobject]@{ id = $id; title = $title; kind = 'text'; text = $editor.Body.Text } }
            1 { [pscustomobject]@{ id = $id; title = $title; kind = 'macro'; action = 'keys'; shortcut = $editor.Body.Text.Trim() } }
            2 { [pscustomobject]@{ id = $id; title = $title; kind = 'macro'; action = 'desktop' } }
        }
        $entries = @($editor.Snapshot.Entries | ForEach-Object { if ($_.id -ceq $id) { $entry } else { $_ } })
        if (-not $editor.Id) { $entries += $entry }
        $null = Save-FolegoCustomPrompts $DataRoot $entries $editor.Snapshot.Revision
        Update-FolegoPromptEditor $id
        $status.Text = 'Item pessoal salvo.'
    } catch { $status.Text = $_.Exception.Message }
}
function New-FolegoPromptPage {
    $page = New-FolegoPage 'Prompts e atalhos'
    $tab = $tabs.TabPages[$tabs.TabPages.Count - 1]
    $null = Add-FolegoLabel $page 'A biblioteca completa está no menu da bandeja e do widget. Nos campos desta página, o clique direito permite inserir texto no local selecionado.' 52
    $external = New-Object Windows.Forms.CheckBox
    $external.Text = 'Abrir painel ao clicar com o botão direito em campos editáveis de outros aplicativos'
    $external.AutoSize = $true
    $external.MaximumSize = New-Object Drawing.Size([Math]::Min(680, $form.ClientSize.Width - 62), 0)
    $external.Checked = Get-FolegoValue $script:Appearance external_prompt_menu $false
    $external.Add_CheckedChanged({
        param($sender, $eventArgs)
        if ($script:UpdatingPromptPreference) { return }
        $script:UpdatingPromptPreference = $true
        $previous = Get-FolegoValue $script:Appearance external_prompt_menu $false
        try {
            Set-FolegoExternalPromptMenu $sender.Checked
            try { Save-FolegoAppearanceChange (Set-FolegoAppearanceField $script:Appearance external_prompt_menu $sender.Checked $policy) }
            catch { Set-FolegoExternalPromptMenu $previous; throw }
            $status.Text = if ($sender.Checked) { 'Painel externo ligado. Clique com o botão direito em um campo editável compatível.' } else { 'Painel externo desligado.' }
        } catch {
            $sender.Checked = $previous
            $status.Text = $_.Exception.Message
        } finally { $script:UpdatingPromptPreference = $false }
    })
    $page.Controls.Add($external)
    $header = Add-FolegoLabel $page 'Textos e macros pessoais' 36
    $header.Font = New-Object Drawing.Font('Segoe UI', 15, [Drawing.FontStyle]::Bold)
    $note = Add-FolegoLabel $page '' 40
    $width = [Math]::Min(670, $form.ClientSize.Width - 60)
    $list = New-Object Windows.Forms.ListBox
    $list.AccessibleName = 'Itens pessoais'
    $list.Size = New-Object Drawing.Size($width, (S 112))
    $page.Controls.Add($list)
    Add-FolegoButton $page 'Novo item' { $script:PromptEditor.List.ClearSelected(); Set-FolegoPromptEditorRow $null; $script:PromptEditor.Title.Focus() | Out-Null }
    $null = Add-FolegoLabel $page 'Título' 26
    $title = New-Object Windows.Forms.TextBox
    $title.AccessibleName = 'Título do item'; $title.Width = $width; $title.MaxLength = 80
    $page.Controls.Add($title)
    $null = Add-FolegoLabel $page 'Tipo de item' 26
    $kind = New-Object Windows.Forms.ComboBox
    $kind.AccessibleName = 'Tipo de item'; $kind.DropDownStyle = 'DropDownList'; $kind.Width = $width
    $kind.Items.AddRange(@('Texto', 'Atalho de teclado', 'Mostrar área de trabalho'))
    $kind.SelectedIndex = 0
    $page.Controls.Add($kind)
    $bodyLabel = Add-FolegoLabel $page 'Texto a inserir ou copiar' 28
    $body = New-Object Windows.Forms.TextBox
    $body.AccessibleName = 'Texto a inserir ou copiar'; $body.Multiline = $true; $body.ScrollBars = 'Vertical'; $body.WordWrap = $true
    $body.Size = New-Object Drawing.Size($width, (S 102)); $body.MaxLength = 16000
    $page.Controls.Add($body)
    $script:PromptEditor = [pscustomobject]@{ Tab = $tab; Loaded = $false; Snapshot = $null; Id = $null; List = $list; Title = $title; Kind = $kind; Body = $body; BodyLabel = $bodyLabel; Note = $note }
    $list.Add_SelectedIndexChanged({
        $editor = $script:PromptEditor
        if ($editor.List.SelectedIndex -ge 0 -and $null -ne $editor.Snapshot) { Set-FolegoPromptEditorRow $editor.Snapshot.Entries[$editor.List.SelectedIndex] }
    })
    $kind.Add_SelectedIndexChanged({
        $editor = $script:PromptEditor
        $isText = $editor.Kind.SelectedIndex -eq 0
        $editor.Body.Visible = $editor.BodyLabel.Visible = $editor.Kind.SelectedIndex -ne 2
        $editor.BodyLabel.Text = if ($isText) { 'Texto a inserir ou copiar' } else { 'Combinação de teclas, por exemplo Ctrl+Shift+F5' }
        $editor.Body.AccessibleName = $editor.BodyLabel.Text
    })
    Add-FolegoEditContext $title
    Add-FolegoEditContext $body
    Add-FolegoButton $page 'Salvar item' { Save-FolegoPromptEditor }
    Add-FolegoButton $page 'Remover item…' {
        $editor = $script:PromptEditor
        if (-not $editor.Id -or $null -eq $editor.Snapshot) { $status.Text = 'Selecione um item pessoal.'; return }
        if (-not (Confirm-Folego 'Remover item pessoal' ('Remover “' + $editor.Title.Text + '” da biblioteca?'))) { return }
        try {
            $entries = @($editor.Snapshot.Entries | Where-Object { $_.id -cne $editor.Id })
            $null = Save-FolegoCustomPrompts $DataRoot $entries $editor.Snapshot.Revision
            Update-FolegoPromptEditor
        } catch { $status.Text = $_.Exception.Message }
    }
    Add-FolegoButton $page 'Recarregar biblioteca' { Update-FolegoPromptEditor }
    $tabs.Add_SelectedIndexChanged({
        if (-not $script:PromptEditor.Loaded -and $tabs.SelectedTab -eq $script:PromptEditor.Tab) { Update-FolegoPromptEditor }
    })
}
