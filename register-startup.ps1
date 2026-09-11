# One-time setup: drops a launcher into your per-user Startup folder so
# start-backend.ps1 runs automatically whenever you log in -- no admin
# rights needed (unlike Task Scheduler, which this account can't use).
# Run this once yourself.

$startupDir = [Environment]::GetFolderPath('Startup')
$launcher = Join-Path $startupDir 'ScratchBriefIndBackend.vbs'

$vbs = 'CreateObject("Wscript.Shell").Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\Users\HP-LT\scratchbrief-ind-mcp\start-backend.ps1""", 0, False'
Set-Content -Path $launcher -Value $vbs -Encoding ASCII

Write-Output "Installed: $launcher"
Write-Output "It'll run hidden at your next logon. To start it now instead:"
Write-Output "  powershell -NoProfile -ExecutionPolicy Bypass -File `"C:\Users\HP-LT\scratchbrief-ind-mcp\start-backend.ps1`""
