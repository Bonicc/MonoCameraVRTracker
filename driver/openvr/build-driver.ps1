param(
    [string]$BuildDirectory = (Join-Path $PSScriptRoot 'build'),
    [string]$CMake = 'cmake',
    [ValidateSet('VisualStudio', 'MinGW')][string]$Toolchain = 'VisualStudio'
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $PSScriptRoot).Path
if ($Toolchain -eq 'MinGW') {
    & $CMake -S $source -B $BuildDirectory -G 'MinGW Makefiles' -DCMAKE_BUILD_TYPE=Release
} else {
    & $CMake -S $source -B $BuildDirectory -A x64
}
if ($LASTEXITCODE -ne 0) { throw 'CMake configuration failed.' }
& $CMake --build $BuildDirectory --config Release
if ($LASTEXITCODE -ne 0) { throw 'Driver compilation failed.' }
$cmakeCommand = Get-Command $CMake -ErrorAction Stop
$ctest = Join-Path (Split-Path -Parent $cmakeCommand.Source) 'ctest.exe'
if (-not (Test-Path -LiteralPath $ctest -PathType Leaf)) { $ctest = 'ctest' }
& $ctest --test-dir $BuildDirectory -C Release --output-on-failure
if ($LASTEXITCODE -ne 0) { throw 'Native protocol tests failed.' }
Write-Output "Driver package: $([IO.Path]::GetFullPath((Join-Path $BuildDirectory 'monocameravrtracker')))"
