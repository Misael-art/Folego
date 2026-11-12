# Called by the card's existing session dispatcher only until first start.
param([string]$CardAdminRoot)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { return }
if (-not $CardAdminRoot) { throw 'Raiz administrativa do cartão não informada.' }
$windows = [Environment]::GetFolderPath('Windows')
$drive = [IO.Path]::GetPathRoot($CardAdminRoot)
if ($drive -ne [IO.Path]::GetPathRoot($windows)) { throw 'O Windows em execução não pertence ao cartão.' }
$inventory = Get-Content -LiteralPath (Join-Path $CardAdminRoot 'preparacao.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$part = Get-Partition -DriveLetter $drive.Substring(0, 1) -ErrorAction Stop
if (([string]$part.Guid).Trim('{}') -ne $inventory.optimization.deployment.partition_guid) { throw 'Identidade do cartão não confere; início preservado.' }
. (Join-Path $PSScriptRoot 'Folego.Core.ps1')
$dataRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Folego'
$settings = Get-FolegoSettings $dataRoot
if ($settings.commissioned -or -not $settings.startup) { return }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.product -ne 'Fôlego Windows' -or $manifest.schema -ne 1) { throw 'Pacote Fôlego não reconhecido.' }
foreach ($row in $manifest.files.PSObject.Properties) {
    if ([IO.Path]::GetFileName($row.Name) -cne $row.Name) { throw 'Caminho inválido no manifesto.' }
    $path = Join-Path $PSScriptRoot $row.Name
    if ((Get-Item -LiteralPath $path).Length -ne $row.Value.bytes -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $row.Value.sha256) { throw 'Integridade do pacote Fôlego não confere.' }
}
$exe = Join-Path $windows 'System32\WindowsPowerShell\v1.0\powershell.exe'
Start-Process -FilePath $exe -WindowStyle Hidden -ArgumentList ('-NoProfile -STA -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'Folego.ps1') + '" -StartMinimized -DelaySeconds 30')
