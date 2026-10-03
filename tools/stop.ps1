$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPidPath = Join-Path $taskRoot 'data\local-processes.json'
if (-not (Test-Path -LiteralPath $taskPidPath)) { Write-Host 'No recorded local processes.'; exit 0 }
$taskSaved = Get-Content -LiteralPath $taskPidPath -Raw | ConvertFrom-Json
if ($taskSaved.workspace -ne $taskRoot) { throw 'Process record belongs to another workspace.' }
foreach ($taskId in @($taskSaved.api, $taskSaved.worker)) {
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskId"
    if ($taskProcess -and $taskProcess.CommandLine.Contains($taskRoot) -and ($taskProcess.CommandLine.Contains('grid_twin.api:app') -or $taskProcess.CommandLine.Contains('grid_twin.worker'))) {
        # Stop child interpreter as well as the Windows venv launcher.
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $taskId" | Where-Object { $_.Name -eq 'python.exe' -and ($_.CommandLine.Contains('grid_twin.api:app') -or $_.CommandLine.Contains('grid_twin.worker')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Stop-Process -Id $taskId -Force -ErrorAction SilentlyContinue
    }
}
Remove-Item -LiteralPath $taskPidPath
Write-Host 'Stopped recorded application processes. Database and files retained.'
