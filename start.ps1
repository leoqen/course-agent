param([switch]$Offline, [int]$Port=8000)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Offline) { $env:RESEARCH_MODE='offline' } else { $env:RESEARCH_MODE='live' }
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn korean.server:app --host 127.0.0.1 --port $Port
