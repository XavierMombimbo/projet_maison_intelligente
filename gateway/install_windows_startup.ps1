param(
    [string]$PythonPath = '',
    [ValidateSet('rtsp','webcam')][string]$Mode = 'rtsp',
    [string]$TaskName = 'SentinelleMaisonGateway',
    [string]$CredentialsFile = (Join-Path $env:LOCALAPPDATA 'SentinelleMaison\gateway.credentials'),
    [string]$EnvironmentFile = '',
    [string]$CacheRoot = 'E:\CodexCaches\sentinelle-gateway',
    [ValidateRange(0,10)][int]$Index = 0,
    [string]$ReleaseReceipt = '',
    [switch]$Recipe,
    [switch]$Disabled
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($Mode -eq 'webcam' -and -not $Recipe -and -not $PSBoundParameters.ContainsKey('EnvironmentFile')) {
    $EnvironmentFile = Join-Path $env:LOCALAPPDATA 'Sentinelle\production\current\.env.production'
}
if (-not $PythonPath) { $PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe' }
if ($TaskName -notmatch '^[A-Za-z0-9._ -]+$') { throw 'Nom de tache invalide.' }
if ($Recipe -and $TaskName -notlike 'SentinelleMaisonRecipe*') { throw 'Une recette exige un nom SentinelleMaisonRecipe distinct.' }
foreach ($required in @($PythonPath, $CredentialsFile)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw 'Prerequis Python ou identite absent.' }
}
if ($EnvironmentFile -and -not (Test-Path -LiteralPath $EnvironmentFile -PathType Leaf)) { throw 'Environnement absent.' }
if (-not [IO.Path]::IsPathRooted($CacheRoot)) { throw 'Chemin de cache absolu requis.' }
if ($Mode -eq 'webcam' -and -not $Recipe -and -not $Disabled -and -not (Test-Path -LiteralPath $ReleaseReceipt -PathType Leaf)) {
    throw 'Publication verifiee requise avant activation permanente.'
}
$homeDir = Join-Path $env:LOCALAPPDATA 'SentinelleMaison\startup'
New-Item -ItemType Directory -Path $homeDir -Force | Out-Null
$configPath = Join-Path $homeDir ($TaskName + '.json')
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'Tache existante : verifier et retirer explicitement avant installation.'
}
$config = [ordered]@{
    project_root=$ProjectRoot; python_path=$PythonPath; credentials_file=$CredentialsFile;
    env_file=$EnvironmentFile; cache_root=$CacheRoot; mode=$Mode; index=$Index;
    recipe=[bool]$Recipe; release_receipt=$ReleaseReceipt;
    installed_at_utc=[datetime]::UtcNow.ToString('o');
    status_file=(Join-Path $homeDir ($TaskName + '-status.json'))
}
$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
$runner = Join-Path $PSScriptRoot 'run_windows_gateway.ps1'
$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $runner + '" -ConfigPath "' + $configPath + '" -TaskName "' + $TaskName + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $ProjectRoot
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$trigger.Delay = 'PT30S'
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Description ('Sentinelle : passerelle ' + $Mode) `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
if ($Disabled) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
Write-Output ('Tache installee : ' + $TaskName + '. Declenchement a ouverture de session ; aucun mot de passe conserve.')

