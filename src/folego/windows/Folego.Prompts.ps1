# Data contracts for the prompt library. This module has no Forms dependencies.
function Get-FolegoShortcutKeys([string]$Shortcut) {
    if (-not $Shortcut -or $Shortcut.Length -gt 80) { throw 'Use uma combinação como Ctrl+Shift+F5.' }
    $parts = @($Shortcut.ToLowerInvariant().Split('+') | ForEach-Object { $_.Trim() })
    if ($parts.Count -gt 5 -or @($parts | Select-Object -Unique).Count -ne $parts.Count) { throw 'Atalho inválido.' }
    $modifiers = @{ ctrl = 17; alt = 18; shift = 16; meta = 91; win = 91 }
    $keys = @{ esc = 27; tab = 9; space = 32; backspace = 8; enter = 13; insert = 45; delete = 46;
               home = 36; end = 35; left = 37; up = 38; right = 39; down = 40; pgup = 33; pgdown = 34 }
    $primary = $parts[-1]
    $codes = New-Object 'Collections.Generic.List[int]'
    for ($i = 0; $i -lt $parts.Count - 1; $i++) {
        $modifier = $parts[$i]
        if (-not $modifiers.ContainsKey($modifier) -or $codes.Contains($modifiers[$modifier])) { throw 'Modificador inválido ou repetido.' }
        $codes.Add($modifiers[$modifier])
    }
    if ($primary -cmatch '^[a-z0-9]$') { $codes.Add([int][char]$primary.ToUpperInvariant()) }
    elseif ($primary -match '^f([1-9]|1[0-2])$') { $codes.Add(111 + [int]$Matches[1]) }
    elseif ($keys.ContainsKey($primary)) { $codes.Add($keys[$primary]) }
    else { throw 'Tecla não reconhecida. Use letras, números, F1–F12 ou uma tecla de navegação.' }
    return $codes.ToArray()
}
function Test-FolegoPromptShape($Value, [string[]]$Expected) {
    if ($null -eq $Value -or $Value -isnot [pscustomobject]) { return $false }
    $properties = @($Value.PSObject.Properties | ForEach-Object { $_.Name })
    return $properties.Count -eq $Expected.Count -and @($properties | Where-Object { $_ -cnotin $Expected }).Count -eq 0
}
function Assert-FolegoCustomPrompts([object[]]$Entries) {
    if ($Entries.Count -gt 32) { throw 'A biblioteca aceita até 32 itens.' }
    $seen = @{}
    foreach ($entry in $Entries) {
        $id = Get-FolegoValue $entry id
        $title = Get-FolegoValue $entry title
        if ($id -isnot [string] -or $id -cnotmatch '^[a-zA-Z0-9-]{1,64}$' -or $seen.ContainsKey($id)) { throw 'Identidade de item inválida ou repetida.' }
        $seen[$id] = $true
        if ($title -isnot [string] -or -not $title.Trim() -or $title.Length -gt 80 -or $title -match '[\x00-\x1f]') { throw 'Informe um título de até 80 caracteres em uma linha.' }
        $kind = Get-FolegoValue $entry kind
        $action = Get-FolegoValue $entry action
        if ($kind -ceq 'text' -and (Test-FolegoPromptShape $entry @('id', 'kind', 'title', 'text'))) {
            if ($entry.text -isnot [string] -or -not $entry.text.Length -or $entry.text.Length -gt 16000 -or $entry.text.Contains([char]0)) { throw 'Informe um texto de até 16.000 caracteres.' }
        } elseif ($kind -ceq 'macro' -and $action -ceq 'desktop' -and (Test-FolegoPromptShape $entry @('id', 'kind', 'title', 'action'))) {
            continue
        } elseif ($kind -ceq 'macro' -and $action -ceq 'keys' -and (Test-FolegoPromptShape $entry @('id', 'kind', 'title', 'action', 'shortcut')) -and $entry.shortcut -is [string]) {
            $null = Get-FolegoShortcutKeys $entry.shortcut
        } else { throw 'Item personalizado desconhecido.' }
    }
}
function Get-FolegoCustomPromptPath([string]$DataRoot) {
    $path = Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'custom-prompts.json'
    foreach ($candidate in @($DataRoot, $path)) {
        $item = Get-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
        if ($null -ne $item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Biblioteca redirecionada. Arquivo preservado.' }
    }
    if ([IO.Directory]::Exists($path)) { throw 'O caminho da biblioteca aponta para uma pasta.' }
    return $path
}
function Get-FolegoCustomPrompts([string]$DataRoot) {
    $path = Get-FolegoCustomPromptPath $DataRoot
    if (-not [IO.File]::Exists($path)) {
        return [pscustomobject]@{ Revision = 'missing'; Entries = @(
            [pscustomobject]@{ id = 'example-text'; kind = 'text'; title = '123'; text = '123' },
            [pscustomobject]@{ id = 'example-desktop'; kind = 'macro'; title = 'Mostrar área de trabalho'; action = 'desktop' }
        ) }
    }
    $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        $reader = [IO.BinaryReader]::new($stream)
        $bytes = $reader.ReadBytes(512KB + 1)
    } finally { $stream.Dispose() }
    if ($bytes.Length -gt 512KB) { throw 'Biblioteca acima do limite. Arquivo preservado.' }
    try {
        $decoder = [Text.UTF8Encoding]::new($false, $true)
        $raw = $decoder.GetString($bytes).TrimStart([char]0xFEFF)
        $value = $raw | ConvertFrom-Json -ErrorAction Stop
        if (-not (Test-FolegoPromptShape $value @('schema', 'entries')) -or -not (Test-FolegoInt $value.schema) -or $value.schema -ne 1 -or $value.entries -isnot [Array]) {
            throw 'Versão da biblioteca desconhecida.'
        }
        Assert-FolegoCustomPrompts @($value.entries)
    } catch { throw 'Biblioteca inválida ou incompatível. Arquivo preservado.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $revision = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '') }
    finally { $sha.Dispose() }
    return [pscustomobject]@{ Revision = $revision; Entries = @($value.entries) }
}
function Save-FolegoCustomPrompts([string]$DataRoot, [object[]]$Entries, [string]$Revision) {
    Assert-FolegoCustomPrompts $Entries
    $value = [pscustomobject]@{ schema = 1; entries = @($Entries) }
    if ([Text.Encoding]::UTF8.GetByteCount(($value | ConvertTo-Json -Depth 20)) -gt 512KB) { throw 'Biblioteca acima do limite. Reduza os textos.' }
    $path = Get-FolegoCustomPromptPath $DataRoot
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $lockId = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($path.ToUpperInvariant()))).Replace('-', '') }
    finally { $sha.Dispose() }
    $mutex = New-Object Threading.Mutex($false, ('Local\Folego.Prompts.' + $lockId))
    $locked = $false
    try {
        try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
        if (-not $locked) { throw 'Biblioteca em edição. Atualize e tente novamente.' }
        $current = Get-FolegoCustomPrompts $DataRoot
        if ($current.Revision -cne $Revision) { throw 'A biblioteca mudou. Atualize antes de salvar.' }
        Write-FolegoJson $path $value
        return Get-FolegoCustomPrompts $DataRoot
    } finally {
        if ($locked) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}
