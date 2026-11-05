# build_patient_manager_exe.ps1
#
# Builds the Patient Manager into a standalone exe (via patient_manager/rml_tools.spec,
# which bundles the vendored vlc_runtime/ folder so VLC doesn't need to be installed on
# the machine that runs it), then zips the resulting dist folder into a single archive
# that can be copied to another machine and unzipped -- no install step required there.
#
# Run from anywhere:  powershell -File build_patient_manager_exe.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PatientManagerDir = Join-Path $RepoRoot "RML_PYTHON_TOOLS\patient_manager"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SpecFile = Join-Path $PatientManagerDir "rml_tools.spec"

if (-not (Test-Path $VenvPython)) {
    throw "Could not find venv python at $VenvPython"
}
if (-not (Test-Path $SpecFile)) {
    throw "Could not find spec file at $SpecFile"
}

Push-Location $PatientManagerDir
try {
    Write-Host "Running PyInstaller ($SpecFile)..."
    & $VenvPython -m PyInstaller $SpecFile --noconfirm

    $DistDir = Join-Path $PatientManagerDir "dist\RML_Clinical_Tools"
    if (-not (Test-Path $DistDir)) {
        throw "Expected build output at $DistDir but it wasn't found"
    }

    $Timestamp = Get-Date -Format "yyyyMMdd"
    $ZipPath = Join-Path $PatientManagerDir "dist\RML_Clinical_Tools_$Timestamp.zip"
    if (Test-Path $ZipPath) {
        Remove-Item $ZipPath -Force
    }

    Write-Host "Zipping $DistDir -> $ZipPath ..."
    Compress-Archive -Path (Join-Path $DistDir '*') -DestinationPath $ZipPath

    Write-Host ""
    Write-Host "Done. Distributable zip:"
    Write-Host "  $ZipPath"
    Write-Host "Unzip it on the target machine and run RML_Clinical_Tools.exe -- VLC playback works without VLC installed."
}
finally {
    Pop-Location
}
