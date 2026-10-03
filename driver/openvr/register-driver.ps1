param(
    [string]$DriverPath,
    [string]$SteamVRPath,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
if (-not $DriverPath) {
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'driver.vrdrivermanifest') -PathType Leaf) {
        $DriverPath = $PSScriptRoot
    } else {
        $DriverPath = Join-Path $PSScriptRoot 'build\monocameravrtracker'
    }
}
if (-not $SteamVRPath) {
    $pathsFile = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'openvr\openvr.vrpaths'
    if (Test-Path -LiteralPath $pathsFile) {
        $paths = Get-Content -LiteralPath $pathsFile -Raw | ConvertFrom-Json
        foreach ($runtime in $paths.runtime) {
            if (Test-Path -LiteralPath (Join-Path $runtime 'bin\win64\vrpathreg.exe')) {
                $SteamVRPath = $runtime
                break
            }
        }
    }
}
if (-not $SteamVRPath) {
    throw 'SteamVR runtime was not found. Install/start SteamVR once or pass -SteamVRPath its full installation path.'
}
$runtimePath = (Resolve-Path -LiteralPath $SteamVRPath).Path
$registrar = Join-Path $runtimePath 'bin\win64\vrpathreg.exe'
if (-not (Test-Path -LiteralPath $registrar -PathType Leaf)) { throw "vrpathreg.exe was not found: $registrar" }
$packagePath = [IO.Path]::GetFullPath($DriverPath)
if (-not $Unregister) {
    $packagePath = (Resolve-Path -LiteralPath $DriverPath).Path
    $manifestPath = Join-Path $packagePath 'driver.vrdrivermanifest'
    $dllPath = Join-Path $packagePath 'bin\win64\driver_monocameravrtracker.dll'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Build the driver first: manifest missing.' }
    if (-not (Test-Path -LiteralPath $dllPath -PathType Leaf)) { throw 'Build the driver first: compiled DLL missing.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.name -ne 'monocameravrtracker' -or (Split-Path -Leaf $packagePath) -ne 'monocameravrtracker') {
        throw 'Package folder and driver manifest must both be named monocameravrtracker.'
    }
}
Push-Location -LiteralPath $runtimePath
try {
    if ($Unregister) { & $registrar removedriver $packagePath }
    else { & $registrar adddriver $packagePath }
    if ($LASTEXITCODE -ne 0) { throw "SteamVR driver registration failed with exit code $LASTEXITCODE." }
    & $registrar show
    if ($LASTEXITCODE -ne 0) { throw 'SteamVR path verification failed.' }
} finally { Pop-Location }
Write-Output 'Restart SteamVR for the registration change to take effect.'
