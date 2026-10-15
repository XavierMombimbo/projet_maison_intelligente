param([Parameter(Mandatory=$true)][string]$ConfigPath, [Parameter(Mandatory=$true)][string]$TaskName)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$mutex = New-Object System.Threading.Mutex($false, ('Local\SentinelleGateway-' + $TaskName))
if (-not $mutex.WaitOne(0)) { exit 0 }
try {
    Set-Location -LiteralPath $config.project_root
    & $config.python_path -u -m gateway.startup --config $ConfigPath
    $result = $LASTEXITCODE
    if ($result -eq 2) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
    exit $result
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
