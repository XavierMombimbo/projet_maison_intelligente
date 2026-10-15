param([string]$TaskName = 'SentinelleMaisonGateway')
$ErrorActionPreference = "Stop"
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Démarrage automatique retiré."

