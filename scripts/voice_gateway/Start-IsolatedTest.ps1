$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
& (Join-Path $PSScriptRoot 'Start-Comparison.ps1') -Model parakeet
Start-Process -FilePath (Join-Path $repo '.venv\Scripts\pythonw.exe') -ArgumentList ('"'+(Join-Path $PSScriptRoot 'client.py')+'"') -WorkingDirectory $repo -WindowStyle Hidden
