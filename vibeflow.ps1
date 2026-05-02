param(
    [string]$ProjectRoot = (Get-Location).Path,
    [int]$Port = 7400,
    [switch]$NoInstall,
    [switch]$NoWatch
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Find-Python {
    if (Test-Path $VenvPython) {
        return $VenvPython
    }

    $candidates = @("python", "py", "python3")
    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            if ($candidate -eq "py") {
                return "py -3"
            }
            return $candidate
        }
    }

    return $null
}

function Invoke-Python {
    param(
        [string]$PythonCommand,
        [string[]]$Arguments
    )

    if ($PythonCommand -eq "py -3") {
        & py -3 @Arguments
    } else {
        & $PythonCommand @Arguments
    }
}

$Python = Find-Python
if ($null -eq $Python) {
    Write-Host "Python bulunamadi. Python 3.11+ kurup PATH'e eklemen gerekiyor."
    Write-Host "Kurulum: https://www.python.org/downloads/windows/"
    exit 1
}

Set-Location $RepoRoot

if (-not (Test-Path $VenvPython)) {
    Write-Host "Sanal ortam olusturuluyor: .venv"
    Invoke-Python $Python @("-m", "venv", ".venv")
}

$Python = $VenvPython

if (-not $NoInstall) {
    Write-Host "Bagimliliklar kontrol ediliyor/yukleniyor..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements.txt
}

$watchArgs = @()
if ($NoWatch) {
    $watchArgs += "--no-watch"
}

Write-Host ""
Write-Host "VibeFlow Core baslatiliyor"
Write-Host "API: http://127.0.0.1:$Port"
Write-Host "Indexlenen proje: $ProjectRoot"
Write-Host "Durdurmak icin Ctrl+C"
Write-Host ""

& $Python run.py --host 127.0.0.1 --port $Port --project-root $ProjectRoot @watchArgs
