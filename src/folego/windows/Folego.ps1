param([switch]$StartMinimized, [switch]$NoStartup, [switch]$Probe, [ValidateRange(0,120)][int]$DelaySeconds = 0, [ValidateRange(0,300)][int]$SmokeSeconds = 0, [string]$DataRoot,
      [ValidateSet('', 'Disable', 'Enable', 'Restore')][string]$StartupAction = '', [string]$StartupSubject, [switch]$RunSequence,
      [ValidateSet('', 'Apply', 'Restore')][string]$ServicePlan = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Folego.Core.ps1')
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Use Fôlego Windows no Windows nativo. No Linux, use o launcher oficial ./dev.' }
$policy = Get-FolegoPolicy
if (-not $DataRoot) { $DataRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Folego' }
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
if ($ServicePlan) {
    # One-shot elevated helper (same account) for the receipted delayed start of third-party services.
    Add-Type -AssemblyName System.Windows.Forms
    try {
        $hostInfo = Get-FolegoHost
        $text = if ($ServicePlan -eq 'Apply') { Set-FolegoServiceDelays $DataRoot $hostInfo @(Get-FolegoServiceCandidates) } else { Restore-FolegoServiceDelays $DataRoot $hostInfo }
    } catch { $text = [string]$_ }
    if ($ServicePlan -eq 'Restore') { $null = [Windows.Forms.MessageBox]::Show([string]$text, 'Fôlego — serviços') }
    return
}
if ($StartupAction) {
    # One-shot helper started through UAC (same account) for machine-wide startup entries.
    # The UI already asked; accepting the UAC prompt is the second confirmation.
    Add-Type -AssemblyName System.Windows.Forms
    try {
        $subject = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($StartupSubject))
        $hostInfo = Get-FolegoHost
        $text = switch ($StartupAction) {
            'Disable' { Set-FolegoStartupItem $DataRoot $hostInfo $subject $false (New-FolegoConfirmation ('startup:' + $subject) 'Disable') $policy }
            'Enable' { Set-FolegoStartupItem $DataRoot $hostInfo $subject $true (New-FolegoConfirmation ('startup:' + $subject) 'Enable') $policy }
            'Restore' { Restore-FolegoStartupItem $DataRoot $hostInfo $subject (New-FolegoConfirmation ('startup-restore:' + $subject) 'Restore') }
        }
    } catch { $text = [string]$_ }
    $null = [Windows.Forms.MessageBox]::Show([string]$text, 'Fôlego — inicialização')
    return
}
$startupNote = ''
try { $settings = Get-FolegoSettings $DataRoot }
catch { $startupNote = [string]$_; $settings = [pscustomobject]@{ startup = $false; commissioned = $true } }
if ($StartMinimized -and -not $settings.startup -and -not $NoStartup) { return }
if ($DelaySeconds) {
    Start-Sleep -Seconds $DelaySeconds
    $settings = Get-FolegoSettings $DataRoot
    if ($StartMinimized -and -not $settings.startup -and -not $NoStartup) { return }
}
Add-Type -Path @((Join-Path $PSScriptRoot 'Native.cs'), (Join-Path $PSScriptRoot 'Widget.cs')) -ReferencedAssemblies System.Windows.Forms, System.Drawing
$collector = New-Object Folego.Windows.Native
if ($Probe) {
    $null = $collector.Read([IO.Path]::GetPathRoot($PSScriptRoot))
    Start-Sleep -Milliseconds 250
    $plan = [Folego.Windows.Native]::ActivePlan()
    $processor = try { Get-FolegoThermalValues $plan } catch { 'ilegível: ' + [string]$_ }
    $zones = try { @(Get-FolegoThermalZones) } catch { 'ilegível: ' + [string]$_ }
    $processes = try { @(Get-FolegoProcessSnapshot).Count } catch { 'ilegível: ' + [string]$_ }
    [pscustomobject]@{ Sample = $collector.Read([IO.Path]::GetPathRoot($PSScriptRoot)); ActivePlan = $plan; AvailablePlans = [Folego.Windows.Native]::Plans(); Processor = $processor; ThermalZones = $zones; ProcessCount = $processes } | ConvertTo-Json -Depth 8
    return
}
[IO.Directory]::CreateDirectory($DataRoot) | Out-Null
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
# One instance per user and state folder. The default folder keeps the original lock name;
# a disposable -DataRoot (smoke/QA) gets its own, so it never wakes the user's real instance.
$instance = $sid
$defaultRoot = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Folego'))
if ($DataRoot.TrimEnd('\') -ne $defaultRoot.TrimEnd('\')) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $instance += '.' + ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($DataRoot.ToLowerInvariant())))).Replace('-', '').Substring(0, 12) } finally { $sha.Dispose() }
}
$mutex = New-Object Threading.Mutex($false, ('Local\Folego.Windows.' + $instance))
$ownsMutex = $false
try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
$activate = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::AutoReset, ('Local\Folego.Activate.' + $instance))
if (-not $ownsMutex) { if (-not $StartMinimized) { $null = $activate.Set() }; $activate.Dispose(); $mutex.Dispose(); return }
try {
    if (-not $NoStartup -and -not $settings.commissioned) {
        try { $startupNote = Set-FolegoStartup $DataRoot $settings.startup; Install-FolegoShortcuts } catch { $startupNote = [string]$_ }
    }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    . (Join-Path $PSScriptRoot 'Folego.Widget.ps1')
    Initialize-FolegoAppearance
    [Windows.Forms.Application]::EnableVisualStyles()
    $script:Worker = $null; $script:Handle = $null; $script:HostInfo = $null; $script:Extended = $null
    $script:LastSample = $null; $script:LastPower = $null; $script:NextPoll = 0L; $script:PersistAt = 0L
    $script:Paused = $false; $script:Leaving = $false; $script:Notices = @{}; $script:LastAc = $null; $script:LowStreak = 0
    $script:Health = [pscustomobject]@{ Level = 'unknown'; Candidate = ''; Streak = 0 }
    $script:SamplesReceived = 0
    $script:ThermalGuard = New-FolegoThermalGuard; $script:ThermalPeaks = @(); $script:LastThermal = $null
    $script:TriageRows = @(); $script:StartupItems = @(); $script:StartupReceipts = @(); $script:TriageFilter = ''
    $script:PendingAction = ''; $script:PendingTarget = $null
    # Serialized logon runs once per boot at session start (or on request with -RunSequence).
    $script:SequenceRun = $null; $script:SequencePending = [bool]($StartMinimized -or $RunSequence); $script:SequenceItems = @()
    $script:OrchestrationRequested = $false; $script:OrchestrationDone = $null; $script:ServiceNames = @()
    $form = New-Object Windows.Forms.Form
    $form.Text = 'Fôlego — espaço para o que importa'; $form.StartPosition = 'CenterScreen'
    $area = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $form.ClientSize = New-Object Drawing.Size([Math]::Min(940, $area.Width - 30), [Math]::Min(650, $area.Height - 65))
    $form.MinimumSize = New-Object Drawing.Size(440, 350)
    $form.Font = New-Object Drawing.Font('Segoe UI', 11); $form.AutoScaleMode = 'Dpi'
    $form.BackColor = [Drawing.Color]::FromArgb(245, 248, 249)
    $status = New-Object Windows.Forms.Label
    $status.Dock = 'Bottom'; $status.Height = 48; $status.Text = 'Aguardando coleta. ' + $startupNote; $form.Controls.Add($status)
    $tabs = New-Object Windows.Forms.TabControl
    $tabs.Dock = 'Fill'; $form.Controls.Add($tabs); $tabs.BringToFront()
    # Tab headers follow the colour theme (WinForms only paints them in owner-draw mode).
    $tabs.DrawMode = 'OwnerDrawFixed'; $tabs.ItemSize = New-Object Drawing.Size(120, 30)
    $tabs.Add_DrawItem({
        param($sender, $e)
        $selected = $e.Index -eq $sender.SelectedIndex
        $fill = New-Object Drawing.SolidBrush (ConvertTo-FolegoColor $(if ($selected) { $script:Tokens.accent } else { $script:Tokens.surface }))
        try { $e.Graphics.FillRectangle($fill, $e.Bounds) } finally { $fill.Dispose() }
        $ink = ConvertTo-FolegoColor $(if ($selected) { $script:Tokens.accent_text } else { $script:Tokens.text })
        [Windows.Forms.TextRenderer]::DrawText($e.Graphics, $sender.TabPages[$e.Index].Text, $sender.Font, $e.Bounds, $ink, [Windows.Forms.TextFormatFlags]'HorizontalCenter, VerticalCenter, EndEllipsis')
    })
    $viewStrip = New-Object Windows.Forms.MenuStrip
    $viewStrip.Dock = 'Top'
    Add-FolegoAppearanceItems $viewStrip.Items
    $form.MainMenuStrip = $viewStrip; $form.Controls.Add($viewStrip)
    $form.KeyPreview = $true
    $form.Add_KeyDown({
        param($sender, $e)
        if ($e.Control -and $e.Shift -and $e.KeyCode -eq 'F') { Switch-FolegoWidget; $e.Handled = $true }
        elseif ($e.Control -and $e.Shift -and $e.KeyCode -eq 'P') { Switch-FolegoPause; $e.Handled = $true }
    })
    function New-FolegoPage([string]$Name) {
        $tab = New-Object Windows.Forms.TabPage; $tab.Text = $Name; $tabs.Controls.Add($tab)
        $flow = New-Object Windows.Forms.FlowLayoutPanel
        $flow.Dock = 'Fill'; $flow.FlowDirection = 'TopDown'; $flow.WrapContents = $false; $flow.AutoScroll = $true
        $flow.Padding = New-Object Windows.Forms.Padding(12); $tab.Controls.Add($flow); return $flow
    }
    function Add-FolegoLabel($Page, [string]$Text, [int]$Height = 62) {
        $label = New-Object Windows.Forms.Label; $label.Text = $Text
        $label.Width = [Math]::Min(845, $form.ClientSize.Width - 60); $label.Height = $Height; $Page.Controls.Add($label); return $label
    }
    function Add-FolegoButton($Page, [string]$Text, [scriptblock]$Action) {
        $button = New-Object Windows.Forms.Button; $button.Text = $Text
        $button.Width = [Math]::Min(845, $form.ClientSize.Width - 60); $button.Height = 46
        $button.Add_Click($Action); $Page.Controls.Add($button)
    }
    function New-FolegoOutput($Page, [int]$Height = 200) {
        $box = New-Object Windows.Forms.TextBox
        $box.Multiline = $true; $box.ReadOnly = $true; $box.ScrollBars = 'Vertical'
        $box.Width = [Math]::Min(845, $form.ClientSize.Width - 60); $box.Height = $Height; $Page.Controls.Add($box); return $box
    }
    function New-FolegoList($Page, [string[]]$Columns, [int]$Height = 220) {
        $list = New-Object Windows.Forms.ListView
        $list.View = 'Details'; $list.FullRowSelect = $true; $list.MultiSelect = $false; $list.HideSelection = $false
        $list.Width = [Math]::Min(845, $form.ClientSize.Width - 60); $list.Height = $Height
        foreach ($column in $Columns) { $null = $list.Columns.Add($column, 110) }
        $Page.Controls.Add($list); return $list
    }
    function Confirm-Folego([string]$Title, [string]$Text) { return [Windows.Forms.MessageBox]::Show($Text, $Title, 'YesNo', 'Warning', 'Button2') -eq 'Yes' }
    function Request-Folego([string]$Action = 'Sample', $Target = $null, $Confirmation = $null) {
        if ($null -ne $script:Worker) { $status.Text = 'Uma coleta/operação já está em andamento. Aguarde.'; return }
        $script:PendingAction = $Action; $script:PendingTarget = $Target
        $script:Worker = [powershell]::Create()
        $null = $script:Worker.AddCommand((Join-Path $PSScriptRoot 'Collect.ps1')).AddParameter('DataRoot', $DataRoot).AddParameter('Collector', $collector).AddParameter('HostInfo', $script:HostInfo).AddParameter('Extended', $script:Extended).AddParameter('Action', $Action).AddParameter('Guard', $script:ThermalGuard).AddParameter('Target', $Target).AddParameter('Confirmation', $Confirmation).AddParameter('Policy', $policy)
        $script:Handle = $script:Worker.BeginInvoke()
        $status.Text = 'Atualizando: ' + $Action + '. Uma tarefa por vez.'
    }
    function Show-FolegoNotice([string]$Key, [string]$Title, [string]$Message) {
        $now = [long][Folego.Windows.Native]::GetTickCount64()
        if ($script:Notices.ContainsKey($Key) -and $now - $script:Notices[$Key] -lt 300000) { return }
        $script:Notices[$Key] = $now
        $tray.BalloonTipTitle = $Title; $tray.BalloonTipText = $Message
        $tray.BalloonTipIcon = 'Warning'; $tray.ShowBalloonTip(8000)
    }
    function Show-Folego {
        $form.Show(); $form.WindowState = 'Normal'; $form.Activate()
    }
    $page = New-FolegoPage 'Visão geral'
    $headline = Add-FolegoLabel $page 'Aguardando recursos do Windows' 45
    $headline.Font = New-Object Drawing.Font('Segoe UI', 18, [Drawing.FontStyle]::Bold)
    $metrics = New-FolegoOutput $page 150
    $reasons = New-FolegoOutput $page 110
    $null = Add-FolegoLabel $page 'Folga observada em RAM, CPU, commit e espaço. Commit é memória comprometida, não tamanho do pagefile. Dados antigos/ausentes permanecem desconhecidos. Sensores não fornecidos pelo hardware não são estimados.' 85
    Add-FolegoButton $page 'Atualizar agora' { Request-Folego Sample }
    Add-FolegoButton $page 'Pausar / retomar monitoramento (Ctrl+Shift+P)' { Switch-FolegoPause }
    Add-FolegoButton $page 'Abrir o widget (Ctrl+Shift+F)' { Show-FolegoView $script:Appearance.last_widget }

    $thermalPolicy = $policy.windows.thermal
    $page = New-FolegoPage 'Temperatura e CPU'
    $thermalBox = New-FolegoOutput $page 150
    $null = Add-FolegoLabel $page ('Perfis reversíveis no plano ativo: só limite máximo do processador (PROCTHROTTLEMAX) e turbo (PERFBOOSTMODE), em tomada e bateria. Fresco = {0}% sem turbo; Contenção = {1}% sem turbo. Os originais são registrados antes; a restauração exige o mesmo host/boot e que ninguém mais tenha mudado os valores. Não altera TDP, ventoinha, EC/SMU nem drivers e não comprova que evita reinícios.' -f $thermalPolicy.profiles.Fresco.throttle_max, $thermalPolicy.profiles.Contencao.throttle_max) 100
    Add-FolegoButton $page 'Aplicar perfil Fresco (turbo desligado)' {
        if (Confirm-Folego 'Perfil térmico' ('Aplicar Fresco ao plano ativo? CPU máxima ' + $thermalPolicy.profiles.Fresco.throttle_max + '% e turbo desligado em tomada e bateria. Os valores atuais serão registrados antes da troca.')) { Request-Folego Fresco }
    }
    Add-FolegoButton $page 'Aplicar perfil Contenção (CPU reduzida, turbo desligado)' {
        if (Confirm-Folego 'Perfil térmico' ('Aplicar Contenção ao plano ativo? CPU máxima ' + $thermalPolicy.profiles.Contencao.throttle_max + '% e turbo desligado. Tarefas pesadas ficarão mais lentas. Os valores atuais serão registrados antes.')) { Request-Folego Contencao }
    }
    Add-FolegoButton $page 'Restaurar os valores originais registrados' {
        if (Confirm-Folego 'Perfil térmico' 'Devolver os limites originais do recibo? Só ocorre se o host/boot forem os mesmos e ninguém tiver alterado os valores.') { Request-Folego ThermalRestore }
    }
    Add-FolegoButton $page 'Conferir recibo térmico interrompido (sem repetir)' { Request-Folego ThermalReconcile }
    Add-FolegoButton $page 'Adotar recibo de outro boot após revisão' {
        if (Confirm-Folego 'Recibo de outro boot' 'Os limites sobrevivem a reinícios. Adotar o recibo anterior neste boot como escolha manual, somente se os valores atuais ainda forem os aplicados pelo Fôlego?') { Request-Folego ThermalAdopt $null (New-FolegoConfirmation 'thermal-adopt' 'Adopt') }
    }
    Add-FolegoButton $page 'Habilitar guarda térmica automática neste hardware' {
        $text = 'Autorizar trocas automáticas? Fresco quando a zona ficar ≥{0} °C na média de {1} amostras ou tiver pico ≥{2} °C; Contenção se continuar quente em Fresco; volta após {3} amostras abaixo de {4} °C. Até {5} trocas por hora, amostra a cada {6} s enquanto ativa, recibo antes de cada troca e pausa após resultado incerto. Perfis escolhidos manualmente não são desfeitos.' -f $thermalPolicy.raise_average_c, $thermalPolicy.raise_samples, $thermalPolicy.spike_c, $thermalPolicy.recover_samples, $thermalPolicy.recover_c, $thermalPolicy.max_switches_per_hour, $thermalPolicy.poll_seconds
        if (Confirm-Folego 'Guarda térmica' $text) { Request-Folego EnableThermalGuard $null (New-FolegoConfirmation 'thermal-guard' 'Enable') }
    }
    Add-FolegoButton $page 'Desabilitar guarda térmica automática' { Request-Folego DisableThermalGuard }

    $page = New-FolegoPage 'Consumidores'
    $consumersPage = $tabs.TabPages[$tabs.TabPages.Count - 1]
    $null = Add-FolegoLabel $page 'Mede 2 s de CPU e E/S por processo. Órfão = agente cujo processo pai terminou, sem janela. Sistema, outros usuários, dono não comprovado, Fôlego e a sessão que o iniciou, agentes com responsável vivo e árvores de instalador ficam protegidos. Encerrar sempre pede confirmação; forçar só depois de um pedido gentil e com nova confirmação. Nada é encerrado automaticamente.' 100
    Add-FolegoButton $page 'Analisar consumidores e órfãos agora' { $script:TriageFilter = ''; Request-Folego Consumers }
    $procList = New-FolegoList $page @('PID', 'Processo', 'Classe', 'Núcleos', 'E/S KB/s', 'Idade min', 'Pai', 'Motivos') 230
    $procDetail = New-FolegoOutput $page 110
    function Get-FolegoSelectedProcess { if ($procList.SelectedItems.Count -ne 1) { return $null }; return $script:TriageRows[[int]$procList.SelectedItems[0].Tag] }
    function Format-FolegoProcess($Row) {
        return ('{0} (PID {1})' -f $Row.name, $Row.pid) + "`r`nCaminho: " + $Row.path + "`r`nLinha de comando (resumida, segredos ocultos): " + $Row.command + "`r`n" + ('Idade: {0} min | ocioso: {1} min | núcleos: {2} | E/S: {3} KB/s | pai {4} vivo: {5} | janela: {6}' -f $Row.age_min, $Row.idle_min, $Row.cores, $Row.io_kbps, $Row.parent_pid, $Row.parent_alive, $Row.has_window) + "`r`nClasse: " + $Row.class + ' — ' + (@($Row.reasons) -join ', ')
    }
    $procList.Add_SelectedIndexChanged({ $row = Get-FolegoSelectedProcess; if ($null -ne $row) { $procDetail.Text = Format-FolegoProcess $row } })
    Add-FolegoButton $page 'Encerrar selecionado com pedido gentil' {
        $row = Get-FolegoSelectedProcess
        if ($null -eq $row) { $status.Text = 'Selecione um processo da triagem.'; return }
        if (-not $row.killable) { $status.Text = 'Processo protegido: ' + (@($row.reasons) -join ', '); return }
        if (Confirm-Folego 'Encerrar processo' ('Pedir que este processo feche (sem forçar)? Trabalho não salvo dele pode ser perdido.' + "`r`n`r`n" + (Format-FolegoProcess $row))) { Request-Folego EndGentle $row (New-FolegoConfirmation ('process:' + $row.id) 'Gentle') }
    }
    Add-FolegoButton $page 'Forçar encerramento (somente após pedido gentil)' {
        $row = Get-FolegoSelectedProcess
        if ($null -eq $row -or -not $row.killable) { $status.Text = 'Selecione um processo elegível da triagem.'; return }
        if (Confirm-Folego 'Forçar encerramento' ('FORÇAR o encerramento imediato? Não há chance de salvar; use só se o pedido gentil falhou. A identidade (PID e horário de início) é conferida no ato.' + "`r`n`r`n" + (Format-FolegoProcess $row))) { Request-Folego EndForce $row (New-FolegoConfirmation ('process:' + $row.id) 'Force') }
    }
    Add-FolegoButton $page 'Editar listas de agentes e protegidos' {
        $rulesPath = Join-Path $DataRoot 'process-rules.json'
        if (-not (Test-Path -LiteralPath $rulesPath)) { Write-FolegoJson $rulesPath ([pscustomobject]@{ schema = 1; agent_names = @(); protected_names = @(); help = 'Nomes sem .exe. Protegidos vencem agentes. Somam-se às listas do pacote; nada é encerrado automaticamente.' }) }
        Start-Process notepad.exe -ArgumentList ('"' + $rulesPath + '"')
    }
    $consumersOut = New-FolegoOutput $page 170
    Add-FolegoButton $page 'Windows Update (página oficial)' { Start-Process 'ms-settings:windowsupdate' }
    Add-FolegoButton $page 'Otimização de Entrega (página oficial)' { Start-Process 'ms-settings:delivery-optimization' }
    Add-FolegoButton $page 'Segurança do Windows (página oficial)' { Start-Process 'windowsdefender:' }

    $page = New-FolegoPage 'Inicialização'
    $null = Add-FolegoLabel $page 'Desabilitar usa o mesmo registro StartupApproved da tela Configurações → Aplicativos → Inicialização: a entrada original fica intacta e pode ser reativada. Recibo antes da troca; restaurar exige que ninguém tenha mudado a entrada depois. Steam Deck, Fôlego e Segurança do Windows são preservados. Entradas da máquina pedem administrador desta conta.' 100
    Add-FolegoButton $page 'Atualizar lista e mudanças desde a revisão' { Request-Folego StartupList }
    $startList = New-FolegoList $page @('Entrada', 'Origem', 'App', 'Estado', 'Proteção', 'Comando') 220
    function Get-FolegoSelectedStartup { if ($startList.SelectedItems.Count -ne 1) { return $null }; return $script:StartupItems[[int]$startList.SelectedItems[0].Tag] }
    function Request-FolegoStartup([bool]$Enabled) {
        $item = Get-FolegoSelectedStartup
        if ($null -eq $item) { $status.Text = 'Selecione uma entrada.'; return }
        if ($item.protected) { $status.Text = 'Entrada preservada: ' + $item.protected; return }
        $verb = if ($Enabled) { 'Habilitar' } else { 'Desabilitar' }
        $mode = if ($Enabled) { 'Enable' } else { 'Disable' }
        if (Confirm-Folego 'Inicialização' ($verb + ' o início com a sessão de "' + $item.name + '" (' + $item.scope + ')? Instâncias abertas não são encerradas; o valor anterior fica no recibo.')) { Request-Folego ('Startup' + $mode) $item.key (New-FolegoConfirmation ('startup:' + $item.key) $mode) }
    }
    Add-FolegoButton $page 'Desabilitar início da entrada selecionada' { Request-FolegoStartup $false }
    Add-FolegoButton $page 'Habilitar início da entrada selecionada' { Request-FolegoStartup $true }
    Add-FolegoButton $page 'Restaurar a última alteração do Fôlego nesta entrada' {
        $item = Get-FolegoSelectedStartup
        if ($null -eq $item) { $status.Text = 'Selecione uma entrada.'; return }
        $receipt = @($script:StartupReceipts | Where-Object { $_.key -ceq $item.key -and $_.state -eq 'applied' -and $_.action -ne 'Restore' } | Select-Object -Last 1)
        if (-not $receipt.Count) { $status.Text = 'Não há alteração aplicada pelo Fôlego nesta entrada.'; return }
        if (Confirm-Folego 'Inicialização' ('Restaurar "' + $item.name + '" ao estado anterior à alteração de ' + $receipt[0].at + '?')) { Request-Folego StartupRestore $receipt[0].id (New-FolegoConfirmation ('startup-restore:' + $receipt[0].id) 'Restore') }
    }
    Add-FolegoButton $page 'Conferir recibos de inicialização interrompidos' { Request-Folego StartupReconcile }
    Add-FolegoButton $page 'Marcar revisão atual como linha de base' { Request-Folego StartupReview }
    Add-FolegoButton $page 'Mostrar instâncias do Copilot na triagem' { $script:TriageFilter = 'copilot'; $tabs.SelectedTab = $consumersPage; Request-Folego Consumers }
    Add-FolegoButton $page 'Desinstalação oficial (Aplicativos instalados)' { Start-Process 'ms-settings:appsfeatures' }
    Add-FolegoButton $page 'Tela oficial Aplicativos de inicialização' { Start-Process 'ms-settings:startupapps' }
    $startOut = New-FolegoOutput $page 170
    $null = Add-FolegoLabel $page 'Sequência de início: as entradas adotadas deixam de iniciar em paralelo pelo Windows e o Fôlego as inicia uma por vez depois do login, só com CPU ≤ 50%, disco ≤ 40% ocupado, zona < 80 °C em duas leituras seguidas, 20 s entre itens e nenhuma tarefa de logon de terceiros em execução (como as do Disco Linux do cartão). Sem calma em 10 min, o item não é iniciado sob estresse: fica registrado e avisado. Remover devolve a entrada ao Windows. Steam Deck, Fôlego e Segurança do Windows não entram.' 118
    $seqList = New-FolegoList $page @('Ordem', 'Entrada', 'Origem', 'App', 'Última execução') 150
    function Get-FolegoSelectedSequence { if ($seqList.SelectedItems.Count -ne 1) { return $null }; return $script:SequenceItems[[int]$seqList.SelectedItems[0].Tag] }
    Add-FolegoButton $page 'Adicionar a entrada selecionada (lista acima) à sequência' {
        $item = Get-FolegoSelectedStartup
        if ($null -eq $item) { $status.Text = 'Selecione uma entrada na lista de inicialização.'; return }
        if ($item.protected) { $status.Text = 'Entrada preservada: ' + $item.protected; return }
        if (Confirm-Folego 'Sequência de início' ('Iniciar "' + $item.name + '" pela sequência do Fôlego, em série e com calma, em vez de o Windows iniciá-la junto com as demais? A inicialização automática dela no Windows será desabilitada pelo mesmo mecanismo das Configurações, com recibo; remover da sequência a devolve.')) { Request-Folego SequenceAdd $item.key (New-FolegoConfirmation ('sequence-add:' + $item.key) 'Add') }
    }
    Add-FolegoButton $page 'Remover da sequência (devolver ao Windows)' {
        $row = Get-FolegoSelectedSequence
        if ($null -eq $row) { $status.Text = 'Selecione um item da sequência.'; return }
        if (Confirm-Folego 'Sequência de início' ('Tirar "' + $row.name + '" da sequência? Se o Fôlego a desabilitou no Windows, ela volta a iniciar sozinha no próximo login.')) { Request-Folego SequenceRemove $row.key (New-FolegoConfirmation ('sequence-remove:' + $row.key) 'Remove') }
    }
    Add-FolegoButton $page 'Subir item na sequência' { $row = Get-FolegoSelectedSequence; if ($null -ne $row) { Request-Folego SequenceUp $row.key } }
    Add-FolegoButton $page 'Descer item na sequência' { $row = Get-FolegoSelectedSequence; if ($null -ne $row) { Request-Folego SequenceDown $row.key } }
    Add-FolegoButton $page 'Outros itens de logon: tarefas, serviços e pacotes (somente leitura)' { Request-Folego LogonInventory }

    $page = New-FolegoPage 'Trabalho e disco'
    $null = Add-FolegoLabel $page 'Agentes, projetos, Git, credenciais, bancos e volumes permanecem protegidos. Esta aba não encerra processos, esvazia memória, apaga temporários nem interrompe WSL ou serviços; encerramentos confirmados ficam na aba Consumidores.' 85
    Add-FolegoButton $page 'Ver maiores consumidores de RAM' { Request-Folego Processes }
    Add-FolegoButton $page 'Diagnosticar temporários conhecidos (amostra limitada)' { Request-Folego Temps }
    Add-FolegoButton $page 'Eventos de reinício abrupto do Windows' { Request-Folego Events }
    $diagnostic = New-FolegoOutput $page 190
    Add-FolegoButton $page 'Abrir Gerenciador de Tarefas' { Start-Process taskmgr.exe }
    Add-FolegoButton $page 'Abrir armazenamento e manutenção' {
        $deckPanel = Join-Path ([IO.Path]::GetPathRoot($PSScriptRoot)) 'SteamDeck\scripts\otimizar-windows.ps1'
        if (Test-Path -LiteralPath $deckPanel) {
            $exe = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
            Start-Process $exe -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + $deckPanel + '"')
        } else { Start-Process 'ms-settings:storagesense' }
    }

    $page = New-FolegoPage 'Energia e sensores'
    $energy = New-FolegoOutput $page 145
    $null = Add-FolegoLabel $page 'Planos oficiais existentes, sem TDP, voltagem, ventoinha ou drivers. A proteção por carga é opt-in: após duas amostras com bateria ≤10% fora da tomada, pede Economia; restaura ao conectar somente se o recibo, host, boot e plano continuarem válidos. Não diagnostica queda de tensão.' 100
    Add-FolegoButton $page 'Aplicar Economia com recuperação' {
        if ([Windows.Forms.MessageBox]::Show('Trocar o plano conhecido atual para Economia, se o fabricante o oferece? O original será registrado antes do efeito.', 'Energia', 'YesNo', 'Question', 'Button2') -eq 'Yes') { Request-Folego Economy }
    }
    Add-FolegoButton $page 'Restaurar o plano registrado' { Request-Folego Restore }
    Add-FolegoButton $page 'Conferir recibo interrompido (sem repetir a troca)' { Request-Folego Reconcile }
    Add-FolegoButton $page 'Habilitar proteção por carga baixa neste hardware' {
        if ([Windows.Forms.MessageBox]::Show('Autorizar somente as trocas descritas acima? Limite de quatro por hora, confirmação por leitura e pausa após resultado incerto. Planos personalizados e alterações de outros programas serão preservados.', 'Proteção de energia', 'YesNo', 'Question', 'Button2') -eq 'Yes') { Request-Folego EnableGuard }
    }
    Add-FolegoButton $page 'Desabilitar proteção por carga baixa' { Request-Folego DisableGuard }
    Add-FolegoButton $page 'Opções de energia do Windows' { Start-Process 'ms-settings:powersleep' }

    $page = New-FolegoPage 'Opções e recuperação'
    $null = Add-FolegoLabel $page 'Início com a sessão ligado por padrão para este usuário, com atraso de 30 segundos e bandeja. Uma entrada própria, uma instância por sessão. Sair encerra só esta instância; não muda a preferência para o próximo login.' 85
    Add-FolegoButton $page 'Habilitar início com a sessão' { try { $status.Text = Set-FolegoStartup $DataRoot $true } catch { $status.Text = [string]$_ } }
    Add-FolegoButton $page 'Desabilitar início com a sessão' {
        # Adopted items start only through Fôlego: warn before leaving them without a launcher.
        $pending = 0; if ($null -ne $script:HostInfo) { try { $pending = @((Get-FolegoSequenceState $DataRoot $script:HostInfo).items).Count } catch { } }
        if ($pending -and -not (Confirm-Folego 'Sequência de início' ("$pending item(ns) da sequência só iniciam pelo Fôlego. Sem o Fôlego no login, eles não iniciarão; para devolvê-los ao Windows, remova-os da sequência na aba Inicialização. Desabilitar mesmo assim?"))) { return }
        try { $status.Text = Set-FolegoStartup $DataRoot $false } catch { $status.Text = [string]$_ }
    }
    Add-FolegoButton $page 'Revisar aplicativos de inicialização do Windows' { Start-Process 'ms-settings:startupapps' }
    $null = Add-FolegoLabel $page 'Orquestração do início (ligada por padrão): a cada login o Fôlego adota as entradas de início do usuário, inicia-as em série com janelas de calma, mostra o tempo e avisa quando o sistema está completamente inicializado. Uma vez, pede administrador para pôr serviços automáticos de terceiros em início atrasado. Tudo com recibo; Desfazer devolve itens e serviços ao Windows.' 85
    Add-FolegoButton $page 'Ligar a orquestração do início' { Request-Folego OrchestrationOn }
    Add-FolegoButton $page 'Desligar a orquestração automática (mantém o que já foi organizado)' { Request-Folego OrchestrationOff }
    Add-FolegoButton $page 'Desfazer a orquestração: devolver itens e serviços ao Windows' {
        if (Confirm-Folego 'Orquestração do início' 'Devolver ao Windows todas as entradas adotadas e os serviços com início atrasado, e desligar a orquestração automática? Os serviços pedem administrador.') { Request-Folego OrchestrationUndo }
    }
    Add-FolegoButton $page 'Aplicar agora o início atrasado dos serviços (administrador)' {
        $exe = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
        try { Start-Process -FilePath $exe -Verb RunAs -WindowStyle Hidden -ArgumentList ('-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $PSScriptRoot 'Folego.ps1') + '" -NoStartup -DataRoot "' + $DataRoot + '" -ServicePlan Apply'); $status.Text = 'Pedido enviado; o resultado aparece em Inicialização → Outros itens de logon.' } catch { $status.Text = 'Administrador recusado; nada foi alterado.' }
    }
    $null = Add-FolegoLabel $page 'Modo de abertura: central, mini horizontal, widget compacto, laterais ou barra superior. Vale na próxima abertura; o tema de cores e a transparência do widget ficam no menu Tema de cores e Transparência, no topo.' 62
    $startupView = New-Object Windows.Forms.ComboBox
    $startupView.DropDownStyle = 'DropDownList'; $startupView.Width = [Math]::Min(845, $form.ClientSize.Width - 60)
    $startupView.AccessibleName = 'Modo de abertura do Fôlego'
    foreach ($row in @($policy.windows.appearance.views)) { $null = $startupView.Items.Add([string]$row.name) }
    $startupView.SelectedIndex = [Array]::IndexOf((Get-FolegoViewKeys $policy), [string]$script:Appearance.startup_view)
    $startupView.Add_SelectionChangeCommitted({ Set-FolegoStartupViewChoice ((Get-FolegoViewKeys $policy)[$startupView.SelectedIndex]) })
    $page.Controls.Add($startupView)
    Add-FolegoButton $page 'Criar ou conferir atalhos deste usuário' { try { Install-FolegoShortcuts; $status.Text = 'Atalhos conferidos.' } catch { $status.Text = [string]$_ } }
    Add-FolegoButton $page 'Abrir estado e recibos do Fôlego' { Start-Process explorer.exe -ArgumentList ('"' + $DataRoot + '"') }
    Add-FolegoButton $page 'Guia Windows e capacidades' { Start-Process notepad.exe -ArgumentList ('"' + (Join-Path $PSScriptRoot 'LEIA-ME.md') + '"') }
    $null = Add-FolegoLabel $page 'Linux PSI/zram/tmpfs, KWin, systemd, autorreparo de entrada/áudio, integração com contas/owners de IA e fechamento automático de apps (Modo Desempenho) ainda não têm adaptadores Windows validados. Não são acionados por equivalência de nome; encerramentos no Windows são só manuais e confirmados. Btrfs/SD/EFI continuam com seus responsáveis.' 100
    Add-FolegoButton $page 'Sair do Fôlego nesta sessão' { $script:Leaving = $true; $form.Close() }

    $tray = New-Object Windows.Forms.NotifyIcon
    $tray.Icon = [Drawing.SystemIcons]::Information; $tray.Text = 'Fôlego — aguardando coleta'; $tray.Visible = $true
    # One quick-function menu for the tray icon and every taskbar indicator; left or right click.
    $menu = New-FolegoQuickMenu
    $tray.ContextMenuStrip = $menu
    $tray.Add_MouseUp({ param($sender, $e) if ($e.Button -eq [Windows.Forms.MouseButtons]::Left) { Show-FolegoQuickMenu $sender } })
    $form.Add_FormClosing({ param($sender, $event) if (-not $script:Leaving) { $event.Cancel = $true; $form.Hide() } })
    $form.Add_Resize({
        foreach ($tab in $tabs.TabPages) {
            foreach ($flow in $tab.Controls) {
                foreach ($control in $flow.Controls) { $control.Width = [Math]::Max(300, [Math]::Min(845, $form.ClientSize.Width - 60)) }
            }
        }
    })

    $timer = New-Object Windows.Forms.Timer; $timer.Interval = 500
    $startedMs = [long][Folego.Windows.Native]::GetTickCount64()
    $timer.Add_Tick({
        try {
            $now = [long][Folego.Windows.Native]::GetTickCount64()
            Update-FolegoProgress
            if ($activate.WaitOne(0)) { Show-Folego }
            if ($SmokeSeconds -gt 0 -and $now - $startedMs -ge $SmokeSeconds * 1000) { $script:Leaving = $true; $form.Close(); return }
            if ($null -ne $script:Worker -and $script:Handle.IsCompleted) {
                try {
                    $rows = @($script:Worker.EndInvoke($script:Handle))
                    if ($rows.Count -ne 1) { throw ('Coleta/operação incompleta: ' + ($script:Worker.Streams.Error | Out-String)) }
                    $result = $rows[0]
                    if ($result.Sample -isnot [Folego.Windows.Sample]) { throw 'Resultado de coleta desconhecido.' }
                    $script:LastSample = $result.Sample; $script:HostInfo = $result.HostInfo; $script:Extended = $result.Extended; $script:LastPower = $result.Power
                    $sample = $result.Sample
                    $raw = Get-FolegoRawHealth $sample $policy $now
                    $extraHealth = Get-FolegoExtendedHealth $result.Extended $policy $now
                    if ($extraHealth.Level -eq 'red') { $raw.Level = 'red' }
                    elseif ($extraHealth.Level -eq 'yellow' -and $raw.Level -ne 'red') { $raw.Level = 'yellow' }
                    if ($extraHealth.Text) { $raw.Text += "`r`n" + $extraHealth.Text }
                    $level = Update-FolegoHealth $script:Health $raw.Level $policy.health.recovery_samples
                    $names = @{ green = 'Há folga nos recursos observados'; yellow = 'Atenção à carga'; red = 'Pressão alta — preserve seu trabalho'; unknown = 'Dados incompletos ou antigos' }
                    $headline.Text = $names[$level]; $reasons.Text = $raw.Text
                    $headline.ForeColor = Get-FolegoRoleColor $(switch ($level) { 'red' { 'danger' } 'yellow' { 'warning' } 'green' { 'ok' } default { 'muted' } })
                    $cpu = if ($null -ne $sample.CpuPercent) { '{0:N0}%' -f $sample.CpuPercent } else { 'desconhecida' }
                    $battery = if ($null -ne $sample.BatteryPercent) { [string]$sample.BatteryPercent + '% (' + $policy.battery_bands[[int]$sample.BatteryPercent] + ')' } else { 'indisponível' }
                    $ac = if ($null -eq $sample.ExternalPower) { 'desconhecida' } elseif ($sample.ExternalPower) { 'conectada' } else { 'desconectada' }
                    $space = if ($null -ne $sample.DiskAvailable) { '{0:N1} / {1:N1} GiB' -f ($sample.DiskAvailable / 1GB), ($sample.DiskTotal / 1GB) } else { 'desconhecido' }
                    $metrics.Text = ('RAM disponível: {0:N1} / {1:N1} GiB | CPU: {2}' -f ($sample.AvailablePhysical / 1GB), ($sample.TotalPhysical / 1GB), $cpu) + "`r`n" + ('Commit: {0:N1} / {1:N1} GiB | Espaço livre: {2}' -f ($sample.CommitUsed / 1GB), ($sample.CommitLimit / 1GB), $space) + "`r`n" + ('Bateria: ' + $battery + ' | Energia externa: ' + $ac) + "`r`n" + ('Fôlego: {0:N0} MiB RSS | amostra UTC: {1:o}' -f ($sample.SelfRss / 1MB), $sample.AtUtc)
                    $thermal = @($result.Extended.Thermal | ForEach-Object { '{0}: {1:N1} °C (ACPI)' -f $_.Name, $_.Celsius })
                    if (-not $thermal.Count) { $thermal = @('Temperatura: sem sensor ACPI legível. Não é leitura confirmada da APU/GPU.') }
                    $energy.Text = ('Plano ativo: ' + $result.Plan) + "`r`nGuarda por carga habilitado: " + (Get-FolegoValue $result.Power enabled $false) + "`r`n" + ($thermal -join "`r`n") + "`r`nSaúde do volume: " + $result.Extended.VolumeHealth + "`r`n" + ($result.Extended.Notes -join "`r`n")
                    $script:LastThermal = $result.Thermal
                    if ($null -ne $result.ThermalNow -and -not @($script:ThermalPeaks | Where-Object { $_.Mono -eq $result.ThermalNow.Mono }).Count) {
                        $script:ThermalPeaks = @(@(@($script:ThermalPeaks) + @($result.ThermalNow)) | Where-Object { $now - $_.Mono -le 600000 } | Select-Object -Last 240)
                    }
                    $thermalLines = @()
                    if ($null -ne $result.ThermalNow) {
                        $peak = (@($script:ThermalPeaks) | Measure-Object Celsius -Maximum).Maximum
                        $thermalLines += ('Zona {0}: {1:N1} °C agora | máxima observada em 10 min: {2:N1} °C' -f $result.ThermalNow.Zone, $result.ThermalNow.Celsius, $peak)
                    } else { $thermalLines += 'Temperatura: sem zona legível. A guarda não age sem leitura.' }
                    if ($null -ne $result.Processor) {
                        $thermalLines += ('Plano ativo: ' + (Format-FolegoThermalValues $result.Processor))
                        $thermalLines += ('Turbo: ' + $(if ($result.Processor.ac_boost -eq 0 -and $result.Processor.dc_boost -eq 0) { 'desligado' } elseif ($result.Processor.ac_boost -eq 0 -or $result.Processor.dc_boost -eq 0) { 'desligado só em uma fonte' } else { 'permitido' }))
                    } else { $thermalLines += 'Limites do processador: ilegíveis neste momento.' }
                    if ($null -ne $result.Thermal) {
                        $thermalLevel = Get-FolegoThermalProfile $result.Thermal $script:HostInfo
                        $thermalLines += ('Perfil do Fôlego: ' + $thermalLevel + ' | guarda automática: ' + $(if ($result.Thermal.enabled) { 'habilitada' } else { 'desligada' }) + $(if ($result.Thermal.paused) { ' | PAUSADA: confira o recibo' } else { '' }))
                        $r = $result.Thermal.receipt
                        if ($null -ne $r) {
                            $origin = if ($r.automatic) { 'automático' } else { 'manual' }
                            $thermalLines += ('Último recibo: ' + $r.action + ' ' + $r.state + ' (' + $origin + ') em ' + $r.at + $(if ($r.boot -ne $script:HostInfo.Boot) { ' — OUTRO BOOT' } else { '' }))
                            $thermalLines += ('Originais registrados: ' + (Format-FolegoThermalValues $r.original))
                        }
                    }
                    $thermalBox.Text = $thermalLines -join "`r`n"
                    if ($result.Action -eq 'Consumers' -and $null -ne $result.Data) {
                        $script:TriageRows = @($result.Data.Rows | Where-Object { -not $script:TriageFilter -or ([string]$_.name) -match $script:TriageFilter })
                        $procList.BeginUpdate(); $procList.Items.Clear()
                        for ($i = 0; $i -lt $script:TriageRows.Count; $i++) {
                            $row = $script:TriageRows[$i]
                            $item = New-Object Windows.Forms.ListViewItem([string]$row.pid)
                            foreach ($cell in @($row.name, $row.class, $row.cores, $row.io_kbps, $row.age_min, $row.parent_pid, (@($row.reasons) -join ', '))) { $null = $item.SubItems.Add([string]$cell) }
                            $item.Tag = $i
                            if ($row.class -eq 'agente-orfao') { $item.ForeColor = Get-FolegoRoleColor warning } elseif (-not $row.killable) { $item.ForeColor = Get-FolegoRoleColor muted }
                            $null = $procList.Items.Add($item)
                        }
                        $procList.EndUpdate(); $procDetail.Text = ''
                        $consumersOut.Text = $result.Result
                    }
                    if ($result.Action -eq 'StartupList' -and $null -ne $result.Data) {
                        $script:StartupItems = @($result.Data.Items); $script:StartupReceipts = @($result.Data.Receipts)
                        $startList.BeginUpdate(); $startList.Items.Clear()
                        for ($i = 0; $i -lt $script:StartupItems.Count; $i++) {
                            $row = $script:StartupItems[$i]
                            $item = New-Object Windows.Forms.ListViewItem([string]$row.name)
                            foreach ($cell in @($row.scope, $row.app, $row.state, $row.protected, $row.command)) { $null = $item.SubItems.Add([string]$cell) }
                            $item.Tag = $i
                            if ($row.protected) { $item.ForeColor = Get-FolegoRoleColor muted } elseif ($row.state -eq 'disabled') { $item.ForeColor = Get-FolegoRoleColor ok }
                            $null = $startList.Items.Add($item)
                        }
                        $startList.EndUpdate()
                        $startOut.Text = $result.Result
                        $sequence = $result.Data.Sequence
                        $script:SequenceItems = if ($null -ne $sequence) { @($sequence.items) } else { @() }
                        $results = if ($null -ne $sequence -and $null -ne $sequence.last_run) { @($sequence.last_run.results) } else { @() }
                        $seqList.BeginUpdate(); $seqList.Items.Clear()
                        for ($i = 0; $i -lt $script:SequenceItems.Count; $i++) {
                            $row = $script:SequenceItems[$i]
                            $last = @($results | Where-Object { $_.key -ceq $row.key } | Select-Object -Last 1)
                            $item = New-Object Windows.Forms.ListViewItem([string]($i + 1))
                            foreach ($cell in @($row.name, $row.scope, $row.app, $(if ($last.Count) { $last[0].state + ' — ' + $last[0].detail } else { 'ainda não executada' }))) { $null = $item.SubItems.Add([string]$cell) }
                            $item.Tag = $i
                            $null = $seqList.Items.Add($item)
                        }
                        $seqList.EndUpdate()
                    }
                    if ($result.Action -eq 'OrchestrationStart' -and $null -ne $result.Data) {
                        $d = $result.Data
                        $script:ServiceNames = @($d.ServiceNames)
                        if ((-not $d.AlreadyDone -or $RunSequence) -and ($d.Enabled -or @($d.Keys).Count)) {
                            # Once per boot: a restarted Fôlego only continues what this boot has not handled.
                            $script:SequenceRun = New-FolegoSequenceRun @($d.Keys) $now $policy.windows.sequence
                            Add-Member -InputObject $script:SequenceRun -NotePropertyName TaskNames -NotePropertyValue $null
                            Show-FolegoProgress @($d.Keys).Count
                        }
                    }
                    if ($result.Action -eq 'SequenceTick' -and $null -ne $script:SequenceRun) {
                        $decision = $result.Data.Decision
                        $startOut.Text = $result.Result + "`r`n" + $startOut.Text.Substring(0, [Math]::Min(4000, $startOut.Text.Length))
                        if ($decision.Action -eq 'skip') { Show-FolegoNotice ('sequence-' + $decision.Key) 'Fôlego — item de início adiado' ($decision.Key + ': sem janela de calma; não foi iniciado sob estresse. Abra Inicialização para iniciar depois.') }
                        Update-FolegoProgress
                        if ($script:SequenceRun.Done) {
                            $launched = @($script:SequenceRun.Results | Where-Object { $_.State -eq 'launched' }).Count
                            $script:OrchestrationDone = Complete-FolegoProgress ([bool]$script:SequenceRun.DoneCalm) $decision.Reasons $launched @($script:SequenceRun.Keys).Count
                            $script:SequenceRun = $null
                        }
                    }
                    $outputs = @{ EndGentle = $consumersOut; EndForce = $consumersOut; StartupDisable = $startOut; StartupEnable = $startOut; StartupRestore = $startOut; StartupReconcile = $startOut; StartupReview = $startOut; OrchestrationStart = $startOut; OrchestrationOn = $startOut; OrchestrationOff = $startOut; OrchestrationUndo = $startOut; ServiceDeclined = $startOut; SequenceAdd = $startOut; SequenceRemove = $startOut; SequenceUp = $startOut; SequenceDown = $startOut; LogonInventory = $startOut; Fresco = $thermalBox; Contencao = $thermalBox; ThermalRestore = $thermalBox; ThermalReconcile = $thermalBox; ThermalAdopt = $thermalBox; EnableThermalGuard = $thermalBox; DisableThermalGuard = $thermalBox }
                    $message = if ($result.Error) { 'Nada foi alterado ou o resultado ficou registrado como incerto: ' + $result.Error } else { [string]$result.Result }
                    if ($outputs.ContainsKey($result.Action) -and $message) { $outputs[$result.Action].Text = $message + "`r`n`r`n" + $outputs[$result.Action].Text }
                    elseif ($result.Result -and $result.Action -notin @('Consumers', 'StartupList')) { $diagnostic.Text = $result.Result }
                    if ($result.Error -like 'ELEVATION:*' -and $result.Action -eq 'OrchestrationUndo') {
                        $exe = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
                        try { Start-Process -FilePath $exe -Verb RunAs -ArgumentList ('-NoProfile -STA -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'Folego.ps1') + '" -NoStartup -DataRoot "' + $DataRoot + '" -ServicePlan Restore') }
                        catch { $startOut.Text = 'Administrador recusado: os serviços continuam com início atrasado; tente de novo em Opções.' }
                    }
                    if ($result.Error -like 'ELEVATION:*' -and $result.Action -in @('StartupDisable', 'StartupEnable', 'StartupRestore')) {
                        if (Confirm-Folego 'Administrador' 'Esta entrada pertence à máquina. Pedir a confirmação de administrador do Windows (UAC) para esta única alteração? O recibo é gravado no mesmo estado do Fôlego.') {
                            $helperAction = $result.Action.Substring(7)
                            $subject = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$script:PendingTarget))
                            $exe = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
                            try { Start-Process -FilePath $exe -Verb RunAs -ArgumentList ('-NoProfile -STA -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'Folego.ps1') + '" -NoStartup -DataRoot "' + $DataRoot + '" -StartupAction ' + $helperAction + ' -StartupSubject ' + $subject) }
                            catch { $startOut.Text = 'Elevação cancelada; nada foi alterado.' }
                        }
                    }
                    $status.Text = if ($result.Error) { 'Operação não concluída: ' + $result.Error } elseif ($result.Notes.Count) { $result.Notes -join ' | ' } else { 'Coleta concluída. Atualização a cada 10 s (5 s com a guarda térmica); sensores/disco detalhado a cada 60 s.' }
                    if (-not $form.Visible -and $result.Action -notin @('Sample', 'AutoPower', 'Consumers', 'StartupList', 'Processes', 'Temps', 'Events', 'SequenceTick', 'LogonInventory', 'OrchestrationStart', 'OrchestrationDone', 'ServiceDeclined')) {
                        # Actions started from the taskbar menu report back without opening the central window.
                        $tray.BalloonTipTitle = 'Fôlego'; $tray.BalloonTipIcon = $(if ($result.Error) { 'Warning' } else { 'Info' })
                        $tray.BalloonTipText = $status.Text.Substring(0, [Math]::Min(250, $status.Text.Length)); $tray.ShowBalloonTip(8000)
                    }
                    $tray.Text = ('Fôlego | CPU ' + $cpu + ' | bateria ' + $battery).Substring(0, [Math]::Min(63, ('Fôlego | CPU ' + $cpu + ' | bateria ' + $battery).Length))
                    if ($level -eq 'red') { Show-FolegoNotice 'pressure' 'Fôlego — pressão alta' 'Salve o trabalho e adie novas cargas. Abra o painel para conferir RAM, CPU e espaço.' }
                    if ($null -ne $sample.BatteryPercent -and $sample.ExternalPower -eq $false -and $sample.BatteryPercent -le 25) { Show-FolegoNotice 'battery' 'Fôlego — bateria baixa' ('Bateria em ' + $sample.BatteryPercent + '%. Confira a alimentação e salve o trabalho.') }
                    if ($script:LastAc -eq $true -and $sample.ExternalPower -eq $false) { Show-FolegoNotice 'charger' 'Fôlego — carregador desconectado' 'O Windows deixou de detectar energia externa.' }
                    $script:LastAc = $sample.ExternalPower
                    if ($sample.ExternalPower -eq $false -and $null -ne $sample.BatteryPercent -and $sample.BatteryPercent -le 10) { $script:LowStreak++ } else { $script:LowStreak = 0 }
                    if ($now - $script:PersistAt -ge 60000) {
                        Save-FolegoSample $DataRoot ([pscustomobject]@{ schema = 1; host = $script:HostInfo; sample = $sample; level = $level; source = 'Win32 native; no stress test' })
                        $script:PersistAt = $now
                    }
                    $script:SamplesReceived++
                    $profileName = if ($null -ne $result.Thermal) { 'Perfil ' + (Get-FolegoThermalProfile $result.Thermal $script:HostInfo) } else { 'Perfil desconhecido' }
                    $freeText = if ($sample.TotalPhysical -gt 0) { ('{0:N1} GiB livres' -f ($sample.AvailablePhysical / 1GB)) } else { 'sem leitura' }
                    $metricsNow = Get-FolegoMiniMetrics $sample $result.ThermalNow $level $policy $script:Paused
                    $script:WidgetData = [pscustomobject]@{ Metrics = $metricsNow; RamLine = ('RAM ' + $metricsNow.Ram.Text + ' · ' + $freeText); Profile = $profileName; Reasons = (@($raw.Text -split "`r`n")[0..1] -join "`r`n") }
                    $script:WidgetStale = $false
                    Update-FolegoWidget
                    if ($script:SequencePending -and $null -ne $script:HostInfo) { $script:SequencePending = $false; $script:OrchestrationRequested = $true }
                } catch { $status.Text = [string]$_; $headline.Text = 'Coleta/operação incompleta — confira o estado'; $script:Health.Level = 'unknown'; $script:LowStreak = 0 }
                finally {
                    $script:Worker.Dispose(); $script:Worker = $null; $script:Handle = $null
                    $interval = if ($null -ne $script:LastThermal -and $script:LastThermal.enabled -and -not $script:LastThermal.paused) { [int]$policy.windows.thermal.poll_seconds * 1000 } else { 10000 }
                    if ($null -ne $script:SequenceRun) { $interval = [Math]::Min($interval, [int]$policy.windows.sequence.poll_seconds * 1000) }
                    $script:NextPoll = $now + $interval
                }
            }
            if ($null -ne $script:LastSample -and ($now - $script:LastSample.MonotonicMs) -gt 15000) {
                $headline.Text = if ($script:Paused) { 'Monitoramento pausado — amostra antiga' } else { 'Amostra antiga — aguardando coleta' }; $script:LowStreak = 0
                if (-not $script:WidgetStale) { $script:WidgetStale = $true; Update-FolegoWidget }
            }
            if (-not $script:Paused -and $null -eq $script:Worker -and $now -ge $script:NextPoll) {
                $action = 'Sample'
                if ($null -ne $script:LastPower -and $script:LastPower.enabled -and -not $script:LastPower.paused) {
                    if ($script:LowStreak -ge 2 -or ($script:LastAc -eq $true -and $null -ne $script:LastPower.receipt -and $script:LastPower.receipt.state -eq 'applied')) { $action = 'AutoPower' }
                }
                if ($action -eq 'Sample' -and $script:OrchestrationRequested) { $script:OrchestrationRequested = $false; Request-Folego OrchestrationStart }
                elseif ($action -eq 'Sample' -and $null -ne $script:OrchestrationDone) {
                    $summary = $script:OrchestrationDone; $script:OrchestrationDone = $null
                    Request-Folego OrchestrationDone $summary
                    # After "fully initialized", once: delayed start for third-party services needs administrator (UAC).
                    if (@($script:ServiceNames).Count) {
                        $script:ServiceNames = @()
                        $exe = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
                        try { Start-Process -FilePath $exe -Verb RunAs -WindowStyle Hidden -ArgumentList ('-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $PSScriptRoot 'Folego.ps1') + '" -NoStartup -DataRoot "' + $DataRoot + '" -ServicePlan Apply') }
                        catch { $script:ServiceDeclinedPending = $true }
                    }
                }
                elseif ($action -eq 'Sample' -and $script:ServiceDeclinedPending) { $script:ServiceDeclinedPending = $false; Request-Folego ServiceDeclined }
                elseif ($action -eq 'Sample' -and $null -ne $script:SequenceRun -and $null -ne $script:HostInfo) { Request-Folego SequenceTick $script:SequenceRun }
                else { Request-Folego $action }
            }
        } catch { $status.Text = [string]$_ }
    })
    $form.Add_Shown({
        Set-FolegoThemeEverywhere
        if ($script:AppearanceNote) { $status.Text = 'Aparência: ' + $script:AppearanceNote }
        # Keep the own Start menu entry: recreate it if it was removed (custom shortcuts are preserved).
        if (-not $NoStartup -and $settings.startup -and -not (Test-Path -LiteralPath (Join-Path ([Environment]::GetFolderPath('Programs')) 'Fôlego.lnk'))) { try { Install-FolegoShortcuts } catch { } }
        if ($script:Appearance.startup_view -ne 'central') { Show-FolegoView $script:Appearance.startup_view }
        elseif ($StartMinimized) { $form.Hide() }
        $timer.Start(); Request-Folego Sample
    })
    [Windows.Forms.Application]::Run($form)
    if ($SmokeSeconds -gt 0 -and $script:SamplesReceived -lt 1) { throw 'A janela abriu, mas nenhuma coleta completa chegou à interface no smoke.' }
} finally {
    if ($null -ne (Get-Variable timer -ErrorAction SilentlyContinue)) { $timer.Stop(); $timer.Dispose() }
    if ($null -ne $script:Worker) { try { $script:Worker.Stop() } finally { $script:Worker.Dispose() } }
    if ($null -ne (Get-Variable tray -ErrorAction SilentlyContinue)) { $tray.Visible = $false; $tray.Dispose() }
    if ($null -ne (Get-Command Hide-FolegoWidget -ErrorAction SilentlyContinue)) { Hide-FolegoWidget }
    if ($null -ne (Get-Command Hide-FolegoTaskbarIndicators -ErrorAction SilentlyContinue)) { Hide-FolegoTaskbarIndicators }
    if ($null -ne (Get-Command Close-FolegoProgress -ErrorAction SilentlyContinue)) { Close-FolegoProgress }
    if ($null -ne $script:WidgetMenu) { $script:WidgetMenu.Dispose() }
    if ($null -ne (Get-Variable form -ErrorAction SilentlyContinue)) { $form.Dispose() }
    $activate.Dispose(); if ($ownsMutex) { $mutex.ReleaseMutex() }; $mutex.Dispose()
}
