# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.
#
# Maintainer script: download ASWF MaterialX Windows prebuilt into
# vredx/baking/third_party/materialx/ (read-only vendor bundle).

param(
    [string]$Version = "1.39.5",
    [string]$PythonTag = "Python313"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $Root "vredx\baking\third_party\materialx"
$ZipName = "MaterialX_Windows_VS2022_x64_$PythonTag.zip"
$Url = "https://github.com/AcademySoftwareFoundation/MaterialX/releases/download/v$Version/$ZipName"

Write-Host "VredX: fetching ASWF MaterialX $Version for texture baking..."
Write-Host "URL: $Url"

$TempZip = Join-Path $env:TEMP $ZipName
$TempExtract = Join-Path $env:TEMP ("MaterialX_extract_" + [guid]::NewGuid().ToString())

Invoke-WebRequest -Uri $Url -OutFile $TempZip
Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force

# Release zips extract flat (bin/, python/, libraries/, … at archive root).
$SourceRoot = $TempExtract
if (Test-Path (Join-Path $TempExtract "python")) {
    $SourceRoot = $TempExtract
} else {
    $Inner = Get-ChildItem -Path $TempExtract -Directory | Select-Object -First 1
    if ($Inner) { $SourceRoot = $Inner.FullName }
}

if (Test-Path $Target) {
    Remove-Item -Recurse -Force $Target
}
New-Item -ItemType Directory -Path $Target -Force | Out-Null
Copy-Item -Path (Join-Path $SourceRoot "*") -Destination $Target -Recurse -Force

# ASWF ships cp313 PyMaterialX wheels without python.exe — bundle embeddable 3.13.
$PyEmbedVersion = "3.13.7"
$PyEmbedZip = "python-$PyEmbedVersion-embed-amd64.zip"
$PyEmbedUrl = "https://www.python.org/ftp/python/$PyEmbedVersion/$PyEmbedZip"
$PyTarget = Join-Path $Target "python313"
Write-Host "VredX: fetching embeddable Python $PyEmbedVersion..."
$PyTempZip = Join-Path $env:TEMP $PyEmbedZip
Invoke-WebRequest -Uri $PyEmbedUrl -OutFile $PyTempZip
if (Test-Path $PyTarget) { Remove-Item -Recurse -Force $PyTarget }
New-Item -ItemType Directory -Path $PyTarget -Force | Out-Null
Expand-Archive -Path $PyTempZip -DestinationPath $PyTarget -Force
Remove-Item -Force $PyTempZip

# Allow embedded interpreter to import bundled PyMaterialX modules.
$PthFile = Join-Path $PyTarget ("python" + ($PyEmbedVersion -replace '\.','') + "._pth")
if (-not (Test-Path $PthFile)) {
    $PthFile = Get-ChildItem $PyTarget -Filter "*._pth" | Select-Object -First 1 -ExpandProperty FullName
}
if ($PthFile) {
    Add-Content -Path $PthFile -Value "..\\python\\build\\lib"
    Add-Content -Path $PthFile -Value "import site"
}

Remove-Item -Recurse -Force $TempExtract
Remove-Item -Force $TempZip

Write-Host "MaterialX runtime installed to:"
Write-Host "  $Target"
Write-Host "Rebuild vredx.zip to bundle the runtime for VRED."
