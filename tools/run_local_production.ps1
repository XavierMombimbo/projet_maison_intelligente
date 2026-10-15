param(
    [string]$ProductionHome = (Join-Path $env:LOCALAPPDATA 'Sentinelle\production\current')
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tunnel_recovery.ps1')
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$daphne = Join-Path $root '.venv\Scripts\daphne.exe'
$cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$garnet = Join-Path $env:LOCALAPPDATA 'Sentinelle\garnet-2.1.8\net10.0\GarnetServer.exe'
$env:DOTNET_ROOT = Join-Path $env:LOCALAPPDATA 'Sentinelle\dotnet-10.0.12'
$env:SENTINELLE_ENV_FILE = Join-Path $ProductionHome '.env.production'
$logs = Join-Path $env:LOCALAPPDATA 'Sentinelle\logs'

foreach ($required in @($python, $daphne, $cloudflared, $garnet, $env:SENTINELLE_ENV_FILE)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Prerequis absent : $required"
    }
}

$mutex = New-Object System.Threading.Mutex($false, 'Local\SentinelleMaisonProduction')
if (-not $mutex.WaitOne(0)) {
    throw 'Un superviseur Sentinelle est deja actif pour cet utilisateur.'
}

$processes = @{}

function Start-ManagedProcess([string]$name, [string]$file, [string[]]$arguments, [string]$directory) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdout = Join-Path $logs "$name-$stamp-out.log"
    $stderr = Join-Path $logs "$name-$stamp-err.log"
    $processes[$name] = Start-Process -FilePath $file -ArgumentList $arguments `
        -WorkingDirectory $directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Write-Output "$name demarre (PID $($processes[$name].Id))."
}

function Test-LocalPort([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(2000)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

try {
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $check = "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); from django.conf import settings; assert not settings.DEBUG; assert settings.REDIS_URL == 'redis://127.0.0.1:6380/0'"
    & $python -c $check
    if ($LASTEXITCODE -ne 0) { throw 'Configuration de production invalide.' }
    & $python (Join-Path $root 'manage.py') check --deploy
    if ($LASTEXITCODE -ne 0) { throw 'Verification Django de production echouee.' }

    if (Test-LocalPort 8001) { throw 'Le port HTTP 8001 est deja occupe.' }
    if (Test-LocalPort 6380) { throw 'Le port Garnet 6380 est deja occupe.' }

    Start-ManagedProcess 'garnet' $garnet @('--bind', '127.0.0.1', '--port', '6380', '-m', '256m', '-i', '16m', '--lua') (Split-Path $garnet)
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-LocalPort 6380) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Garnet ne repond pas sur 6380.' }

    Start-ManagedProcess 'daphne' $daphne @('-b', '127.0.0.1', '-p', '8001', 'config.asgi:application') $root
    Start-ManagedProcess 'outbox' $python @('manage.py', 'dispatch_event_outbox', '--watch', '--interval', '5') $root
    Start-ManagedProcess 'push' $python @('manage.py', 'dispatch_push_deliveries', '--watch', '--interval', '5') $root
    $tunnelConfig = '"' + (Join-Path $root 'tools\cloudflared-sentinelle.yml') + '"'
    Start-ManagedProcess 'tunnel' $cloudflared @('tunnel', '--config', $tunnelConfig, 'run') $root
    $tunnelRecovery = @{ Failures = 0; StartedAt = [datetime]::UtcNow; NextStart = $null }

    while ($true) {
        Start-Sleep -Seconds 10
        foreach ($name in @('garnet', 'daphne', 'outbox', 'push')) {
            if (-not (Get-Process -Id $processes[$name].Id -ErrorAction SilentlyContinue)) {
                throw "$name s'est arrete ; intervention requise."
            }
        }
        $processes['tunnel'].Refresh()
        $recovery = Get-TunnelRecoveryAction -State $tunnelRecovery -Running (-not $processes['tunnel'].HasExited)
        switch ($recovery.Action) {
            'Scheduled' {
                Write-Output "Tunnel interrompu ; reprise $($recovery.Attempt)/5 dans $($recovery.Delay) s. Les services locaux restent actifs."
            }
            'Restart' {
                $oldTunnel = $processes['tunnel']
                Start-ManagedProcess 'tunnel' $cloudflared @('tunnel', '--config', $tunnelConfig, 'run') $root
                $oldTunnel.Dispose()
            }
            'Stop' {
                throw 'Tunnel indisponible apres cinq reprises ; la tache Windows prendra le relais.'
            }
        }
    }
} finally {
    foreach ($name in @('tunnel', 'push', 'outbox', 'daphne', 'garnet')) {
        if ($processes.ContainsKey($name)) {
            Stop-Process -Id $processes[$name].Id -ErrorAction SilentlyContinue
        }
    }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
