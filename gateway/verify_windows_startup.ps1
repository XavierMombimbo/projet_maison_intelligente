param([string]$TaskName = 'SentinelleMaisonGateway')
$ErrorActionPreference = 'Stop'
if ($TaskName -notmatch '^[A-Za-z0-9._ -]+$') { throw 'Nom de tache invalide.' }
$homeDir = Join-Path $env:LOCALAPPDATA 'SentinelleMaison\startup'
$config = Get-Content -LiteralPath (Join-Path $homeDir ($TaskName + '.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
$status = Get-Content -LiteralPath $config.status_file -Raw -Encoding UTF8 | ConvertFrom-Json
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
$installed = [datetime]::Parse($config.installed_at_utc).ToUniversalTime()
$reported = [DateTimeOffset]::FromUnixTimeSeconds([long]$status.updated_at).UtcDateTime
$task = Get-ScheduledTask -TaskName $TaskName
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
$expectedState = if ($config.recipe) {'completed_recipe'} else {'running'}
$expectedTaskState = if ($config.recipe) {3} else {4}
$afterBoot = ($boot -gt $installed) -and ($reported -gt $boot)
$trigger = @($task.Triggers | Where-Object {$_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger'}).Count -eq 1
$taskStateMatches = [int]$task.State -eq $expectedTaskState
$passed = $afterBoot -and $trigger -and $taskStateMatches -and $taskInfo.LastTaskResult -eq 0 -and $status.state -eq $expectedState
[pscustomobject]@{Task=$TaskName; State=$status.state; ExpectedState=$expectedState;
    LogonTrigger=$trigger; RebootSinceInstallation=($boot -gt $installed);
    ReportAfterBoot=($reported -gt $boot); TaskState=$task.State; ExpectedTaskState=$expectedTaskState;
    LastTaskResult=$taskInfo.LastTaskResult;
    Passed=$passed} | ConvertTo-Json -Compress
if (-not $passed) { exit 2 }
