# Build the uv environment on Windows.
#   scripts\setup_env.ps1           # pick the PyTorch backend from the NVIDIA GPU, if any
#   scripts\setup_env.ps1 cu126     # or name it: cpu | cu126 | cu130  (ROCm wheels are Linux only)
param([ValidateSet("cpu", "cu126", "cu130")][string]$Backend)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if (-not $Backend) {
    $Backend = "cpu"
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $cc = nvidia-smi --query-gpu=compute_cap --format=csv,noheader | Sort-Object | Select-Object -First 1
        $driverCuda = [regex]::Match((nvidia-smi | Out-String), 'CUDA Version: (\d+)').Groups[1].Value
        # cu130 needs Turing (7.5) or newer and a CUDA 13 driver; otherwise cu126.
        if ([double]$cc -ge 7.5 -and [int]("0$driverCuda") -ge 13) { $Backend = "cu130" } else { $Backend = "cu126" }
    }
}

Set-Content -Path .torch-backend -Value $Backend -Encoding ascii
uv sync --locked --extra $Backend
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-sync python -m sotonship26
Write-Host ""
Write-Host "Ready ($Backend). Run commands with:  uv run --extra $Backend <command>"
Write-Host "or activate the environment:          .venv\Scripts\Activate.ps1"
