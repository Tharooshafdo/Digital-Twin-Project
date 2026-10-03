$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run the README installation commands first.' }
New-Item -ItemType Directory -Force data | Out-Null
& $taskPython -m grid_twin.cli init
if ($LASTEXITCODE -ne 0) { throw 'Initialization failed.' }
try { Invoke-RestMethod 'http://127.0.0.1:8000/api/ready' -TimeoutSec 2 | Out-Null; Write-Host 'Application already running at http://127.0.0.1:8000'; exit 0 } catch {}
$taskWorker = Start-Process -FilePath $taskPython -ArgumentList '-m','grid_twin.worker' -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput 'data\worker.log' -RedirectStandardError 'data\worker-error.log' -PassThru
$taskApi = Start-Process -FilePath $taskPython -ArgumentList '-m','uvicorn','grid_twin.api:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput 'data\api.log' -RedirectStandardError 'data\api-error.log' -PassThru
@{ api = $taskApi.Id; worker = $taskWorker.Id; workspace = $taskRoot } | ConvertTo-Json | Set-Content -LiteralPath 'data\local-processes.json'
for ($taskAttempt = 0; $taskAttempt -lt 40; $taskAttempt++) {
    try { Invoke-RestMethod 'http://127.0.0.1:8000/api/ready' -TimeoutSec 2 | Out-Null; Write-Host 'Open http://127.0.0.1:8000. Credentials: data\initial-credentials.json'; exit 0 } catch { Start-Sleep -Milliseconds 500 }
}
throw 'Application did not become ready. Check data\api-error.log.'
