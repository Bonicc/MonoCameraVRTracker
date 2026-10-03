param([int]$Frames = 120)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectDirectory
try {
    python -m monovrtrack demo --frames $Frames
    if ($LASTEXITCODE -ne 0) { throw 'Demo failed. Install the package with python -m pip install -e .' }
} finally {
    Pop-Location
}
