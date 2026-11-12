param([switch]$StartMinimized, [switch]$NoStartup, [switch]$Probe, [ValidateRange(0,120)][int]$DelaySeconds = 0, [ValidateRange(0,60)][int]$SmokeSeconds = 0, [string]$DataRoot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Folego.Core.ps1')
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Use Fôlego Windows no Windows nativo. No Linux, use o launcher oficial ./dev.' }
$policy = Get-FolegoPolicy
if (-not $DataRoot) { $DataRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Folego' }
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$startupNote = ''
try { $settings = Get-FolegoSettings $DataRoot }
catch { $startupNote = [string]$_; $settings = [pscustomobject]@{ startup = $false; commissioned = $true } }
if ($StartMinimized -and -not $settings.startup -and -not $NoStartup) { return }
if ($DelaySeconds) {
    Start-Sleep -Seconds $DelaySeconds
    $settings = Get-FolegoSettings $DataRoot
    if ($StartMinimized -and -not $settings.startup -and -not $NoStartup) { return }
}
Add-Type -Path (Join-Path $PSScriptRoot 'Native.cs')
$collector = New-Object Folego.Windows.Native
if ($Probe) {
    $null = $collector.Read([IO.Path]::GetPathRoot($PSScriptRoot))
    Start-Sleep -Milliseconds 250
    [pscustomobject]@{ Sample = $collector.Read([IO.Path]::GetPathRoot($PSScriptRoot)); ActivePlan = [Folego.Windows.Native]::ActivePlan(); AvailablePlans = [Folego.Windows.Native]::Plans() } | ConvertTo-Json -Depth 8
    return
}
[IO.Directory]::CreateDirectory($DataRoot) | Out-Null
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$mutex = New-Object Threading.Mutex($false, ('Local\Folego.Windows.' + $sid))
$ownsMutex = $false
try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
$activate = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::AutoReset, ('Local\Folego.Activate.' + $sid))
if (-not $ownsMutex) { if (-not $StartMinimized) { $null = $activate.Set() }; $activate.Dispose(); $mutex.Dispose(); return }
try {
    if (-not $NoStartup -and -not $settings.commissioned) {
        try { $startupNote = Set-FolegoStartup $DataRoot $settings.startup; Install-FolegoShortcuts } catch { $startupNote = [string]$_ }
    }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $script:Worker = $null; $script:Handle = $null; $script:HostInfo = $null; $script:Extended = $null
    $script:LastSample = $null; $script:LastPower = $null; $script:NextPoll = 0L; $script:PersistAt = 0L
    $script:Paused = $false; $script:Leaving = $false; $script:Notices = @{}; $script:LastAc = $null; $script:LowStreak = 0
    $script:Health = [pscustomobject]@{ Level = 'unknown'; Candidate = ''; Streak = 0 }
    $script:SamplesReceived = 0
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
    function Request-Folego([string]$Action = 'Sample') {
        if ($null -ne $script:Worker) { $status.Text = 'Uma coleta/operação já está em andamento. Aguarde.'; return }
        $script:Worker = [powershell]::Create()
        $null = $script:Worker.AddCommand((Join-Path $PSScriptRoot 'Collect.ps1')).AddParameter('DataRoot', $DataRoot).AddParameter('Collector', $collector).AddParameter('HostInfo', $script:HostInfo).AddParameter('Extended', $script:Extended).AddParameter('Action', $Action)
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
    Add-FolegoButton $page 'Pausar / retomar monitoramento' { $script:Paused = -not $script:Paused; $status.Text = 'Monitoramento pausado: ' + $script:Paused; $script:NextPoll = 0L }

    $page = New-FolegoPage 'Trabalho e disco'
    $null = Add-FolegoLabel $page 'Agentes, projetos, Git, credenciais, bancos e volumes permanecem protegidos. Este port não encerra processos, esvazia memória, apaga temporários nem interrompe WSL ou serviços. Revise a carga antes de iniciar mais trabalho.' 85
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
    Add-FolegoButton $page 'Desabilitar início com a sessão' { try { $status.Text = Set-FolegoStartup $DataRoot $false } catch { $status.Text = [string]$_ } }
    Add-FolegoButton $page 'Revisar aplicativos de inicialização do Windows' { Start-Process 'ms-settings:startupapps' }
    Add-FolegoButton $page 'Criar ou conferir atalhos deste usuário' { try { Install-FolegoShortcuts; $status.Text = 'Atalhos conferidos.' } catch { $status.Text = [string]$_ } }
    Add-FolegoButton $page 'Abrir estado e recibos do Fôlego' { Start-Process explorer.exe -ArgumentList ('"' + $DataRoot + '"') }
    Add-FolegoButton $page 'Guia Windows e capacidades' { Start-Process notepad.exe -ArgumentList ('"' + (Join-Path $PSScriptRoot 'LEIA-ME.md') + '"') }
    $null = Add-FolegoLabel $page 'Linux PSI/zram/tmpfs, KWin, systemd, autorreparo de entrada/áudio, integração com contas/owners de IA e encerramento de apps ainda não têm adaptadores Windows validados. Não são acionados por equivalência de nome. Btrfs/SD/EFI continuam com seus responsáveis.' 100
    Add-FolegoButton $page 'Sair do Fôlego nesta sessão' { $script:Leaving = $true; $form.Close() }

    $tray = New-Object Windows.Forms.NotifyIcon
    $tray.Icon = [Drawing.SystemIcons]::Information; $tray.Text = 'Fôlego — aguardando coleta'; $tray.Visible = $true
    $menu = New-Object Windows.Forms.ContextMenuStrip
    $open = $menu.Items.Add('Abrir Fôlego'); $open.Add_Click({ Show-Folego })
    $pause = $menu.Items.Add('Pausar / retomar'); $pause.Add_Click({ $script:Paused = -not $script:Paused; $script:NextPoll = 0L })
    $exit = $menu.Items.Add('Sair'); $exit.Add_Click({ $script:Leaving = $true; $form.Close() })
    $tray.ContextMenuStrip = $menu; $tray.Add_DoubleClick({ Show-Folego })
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
                    $headline.ForeColor = switch ($level) { 'red' { [Drawing.Color]::Firebrick } 'yellow' { [Drawing.Color]::DarkGoldenrod } 'green' { [Drawing.Color]::DarkGreen } default { [Drawing.Color]::DimGray } }
                    $cpu = if ($null -ne $sample.CpuPercent) { '{0:N0}%' -f $sample.CpuPercent } else { 'desconhecida' }
                    $battery = if ($null -ne $sample.BatteryPercent) { [string]$sample.BatteryPercent + '% (' + $policy.battery_bands[[int]$sample.BatteryPercent] + ')' } else { 'indisponível' }
                    $ac = if ($null -eq $sample.ExternalPower) { 'desconhecida' } elseif ($sample.ExternalPower) { 'conectada' } else { 'desconectada' }
                    $space = if ($null -ne $sample.DiskAvailable) { '{0:N1} / {1:N1} GiB' -f ($sample.DiskAvailable / 1GB), ($sample.DiskTotal / 1GB) } else { 'desconhecido' }
                    $metrics.Text = ('RAM disponível: {0:N1} / {1:N1} GiB | CPU: {2}' -f ($sample.AvailablePhysical / 1GB), ($sample.TotalPhysical / 1GB), $cpu) + "`r`n" + ('Commit: {0:N1} / {1:N1} GiB | Espaço livre: {2}' -f ($sample.CommitUsed / 1GB), ($sample.CommitLimit / 1GB), $space) + "`r`n" + ('Bateria: ' + $battery + ' | Energia externa: ' + $ac) + "`r`n" + ('Fôlego: {0:N0} MiB RSS | amostra UTC: {1:o}' -f ($sample.SelfRss / 1MB), $sample.AtUtc)
                    $thermal = @($result.Extended.Thermal | ForEach-Object { '{0}: {1:N1} °C (ACPI)' -f $_.Name, $_.Celsius })
                    if (-not $thermal.Count) { $thermal = @('Temperatura: sem sensor ACPI legível. Não é leitura confirmada da APU/GPU.') }
                    $energy.Text = ('Plano ativo: ' + $result.Plan) + "`r`nGuarda por carga habilitado: " + (Get-FolegoValue $result.Power enabled $false) + "`r`n" + ($thermal -join "`r`n") + "`r`nSaúde do volume: " + $result.Extended.VolumeHealth + "`r`n" + ($result.Extended.Notes -join "`r`n")
                    if ($result.Result) { $diagnostic.Text = $result.Result }
                    $status.Text = if ($result.Notes.Count) { $result.Notes -join ' | ' } else { 'Coleta concluída. Atualização a cada 10 s; sensores/disco detalhado a cada 60 s.' }
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
                } catch { $status.Text = [string]$_; $headline.Text = 'Coleta/operação incompleta — confira o estado'; $script:Health.Level = 'unknown'; $script:LowStreak = 0 }
                finally { $script:Worker.Dispose(); $script:Worker = $null; $script:Handle = $null; $script:NextPoll = $now + 10000 }
            }
            if ($null -ne $script:LastSample -and ($now - $script:LastSample.MonotonicMs) -gt 15000) { $headline.Text = if ($script:Paused) { 'Monitoramento pausado — amostra antiga' } else { 'Amostra antiga — aguardando coleta' }; $script:LowStreak = 0 }
            if (-not $script:Paused -and $null -eq $script:Worker -and $now -ge $script:NextPoll) {
                $action = 'Sample'
                if ($null -ne $script:LastPower -and $script:LastPower.enabled -and -not $script:LastPower.paused) {
                    if ($script:LowStreak -ge 2 -or ($script:LastAc -eq $true -and $null -ne $script:LastPower.receipt -and $script:LastPower.receipt.state -eq 'applied')) { $action = 'AutoPower' }
                }
                Request-Folego $action
            }
        } catch { $status.Text = [string]$_ }
    })
    $form.Add_Shown({ if ($StartMinimized) { $form.Hide() }; $timer.Start(); Request-Folego Sample })
    [Windows.Forms.Application]::Run($form)
    if ($SmokeSeconds -gt 0 -and $script:SamplesReceived -lt 1) { throw 'A janela abriu, mas nenhuma coleta completa chegou à interface no smoke.' }
} finally {
    if ($null -ne (Get-Variable timer -ErrorAction SilentlyContinue)) { $timer.Stop(); $timer.Dispose() }
    if ($null -ne $script:Worker) { try { $script:Worker.Stop() } finally { $script:Worker.Dispose() } }
    if ($null -ne (Get-Variable tray -ErrorAction SilentlyContinue)) { $tray.Visible = $false; $tray.Dispose() }
    if ($null -ne (Get-Variable form -ErrorAction SilentlyContinue)) { $form.Dispose() }
    $activate.Dispose(); if ($ownsMutex) { $mutex.ReleaseMutex() }; $mutex.Dispose()
}
