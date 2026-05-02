param(
    [string]$Source = "https://github.com/alperensu/VibeFlow",
    [string]$Dir = "",
    [switch]$Start,
    [string]$ProjectRoot = (Get-Location).Path,
    [int]$Port = 7400
)

$ErrorActionPreference = "Stop"

function Find-Python {
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
        [string[]]$Arguments,
        [string]$WorkingDirectory = (Get-Location).Path
    )

    Push-Location $WorkingDirectory
    try {
        if ($PythonCommand -eq "py -3") {
            & py -3 @Arguments
        } else {
            & $PythonCommand @Arguments
        }
    } finally {
        Pop-Location
    }
}

function Normalize-Repo {
    param([string]$Value)
    if ($Value.StartsWith("https://github.com/")) {
        if ($Value.EndsWith(".git")) {
            return $Value
        }
        return "$($Value.TrimEnd('/')).git"
    }
    if ($Value.Contains("/") -and -not $Value.StartsWith("http")) {
        return "https://github.com/$($Value.Trim('/')).git"
    }
    return $Value
}

$Python = Find-Python
if ($null -eq $Python) {
    Write-Host "Python bulunamadi. Python 3.11+ kurup PATH'e eklemen gerekiyor."
    exit 1
}

$Repo = Normalize-Repo $Source
if ([string]::IsNullOrWhiteSpace($Dir)) {
    $Name = [System.IO.Path]::GetFileNameWithoutExtension($Repo.TrimEnd('/'))
    $Dir = Join-Path $HOME ".vibeflow\$Name"
}

if ((Test-Path $Dir) -and (Test-Path (Join-Path $Dir ".git"))) {
    git -C $Dir pull --ff-only
} elseif (Test-Path $Dir) {
    throw "Kurulum klasoru bos degil ve git repo degil: $Dir"
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dir) | Out-Null
    git clone $Repo $Dir
}

$VenvPython = Join-Path $Dir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Invoke-Python -PythonCommand $Python -Arguments @("-m", "venv", ".venv") -WorkingDirectory $Dir
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e ".[dev]"

Write-Host ""
Write-Host "VibeFlow kuruldu: $Dir"
Write-Host "CLI: $Dir\.venv\Scripts\vibeflow.exe"
Write-Host "Baslat:"
Write-Host "  $Dir\.venv\Scripts\vibeflow.exe start --project-root `"$ProjectRoot`" --port $Port"

if ($Start) {
    & (Join-Path $Dir ".venv\Scripts\vibeflow.exe") start --project-root $ProjectRoot --port $Port
}
