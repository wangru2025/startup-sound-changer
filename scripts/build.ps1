param(
    [switch]$SkipVenv
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $ProjectRoot

if (-not $SkipVenv) {
    if (-not (Test-Path '.venv')) {
        py -3.12 -m venv .venv
    }
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

New-Item -ItemType Directory -Force -Path 'build-assets\helper' | Out-Null

gofmt -w helper-go\main.go service-go\main.go
go build -ldflags '-H windowsgui -s -w' -o build-assets\helper\Windows-Shutdown-Helper.exe .\helper-go\main.go
go build -ldflags '-H windowsgui -s -w' -o build-assets\helper\Windows-Shutdown-Service.exe .\service-go\main.go

.\.venv\Scripts\python.exe -m PyInstaller --clean startup_sound_changer.spec

Write-Host 'Built dist\startup-sound-changer.exe'
