$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tunnel_recovery.ps1')

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$start = [datetime]::new(2026, 10, 14, 8, 0, 0, [DateTimeKind]::Utc)
$state = @{ Failures = 0; StartedAt = $start; NextStart = $null }
$scheduled = Get-TunnelRecoveryAction -State $state -Running $false -Now $start
Assert-True ($scheduled.Action -eq 'Scheduled') 'La panne doit programmer une reprise.'
$wait = Get-TunnelRecoveryAction -State $state -Running $false -Now $start.AddSeconds(4)
Assert-True ($wait.Action -eq 'Wait' -and $state.Failures -eq 1) 'L attente ne doit ni relancer ni consommer une tentative.'
$restart = Get-TunnelRecoveryAction -State $state -Running $false -Now $start.AddSeconds(5)
Assert-True ($restart.Action -eq 'Restart') 'La reprise doit arriver apres le delai.'
$alive = Get-TunnelRecoveryAction -State $state -Running $true -Now $start.AddSeconds(6)
Assert-True ($alive.Action -eq 'None') 'Un tunnel vivant ne doit pas etre duplique.'
Write-Output 'OK : panne transitoire, delai respecte, aucune duplication.'

$nextFailure = Get-TunnelRecoveryAction -State $state -Running $false -Now $start.AddSeconds(7)
Assert-True ($nextFailure.Delay -gt $scheduled.Delay) 'Une panne repetee doit ralentir la reprise.'
$null = Get-TunnelRecoveryAction -State $state -Running $false -Now $state.NextStart
$null = Get-TunnelRecoveryAction -State $state -Running $true -Now $state.StartedAt.AddSeconds(300)
Assert-True ($state.Failures -eq 0) 'Cinq minutes stables doivent restaurer le budget de reprise.'
Write-Output 'OK : pannes rapprochees ralenties et budget restaure apres stabilite.'

$state = @{ Failures = 0; StartedAt = $start; NextStart = $null }
$instant = $start
for ($attempt = 1; $attempt -le 5; $attempt++) {
    $action = Get-TunnelRecoveryAction -State $state -Running $false -Now $instant
    Assert-True ($action.Action -eq 'Scheduled' -and $action.Delay -le 60) 'Le delai doit etre borne.'
    $instant = $state.NextStart
    $action = Get-TunnelRecoveryAction -State $state -Running $false -Now $instant
    Assert-True ($action.Action -eq 'Restart') 'Les reprises autorisees doivent se declencher.'
    $instant = $instant.AddSeconds(1)
}
$exhausted = Get-TunnelRecoveryAction -State $state -Running $false -Now $instant
Assert-True ($exhausted.Action -eq 'Stop') 'Une panne persistante doit revenir a la supervision Windows.'
Write-Output 'OK : cinq reprises bornees, puis retour au superviseur Windows.'

$parseErrors = $null
$tokens = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'run_local_production.ps1'), [ref]$tokens, [ref]$parseErrors
)
Assert-True ($parseErrors.Count -eq 0) 'Syntaxe du superviseur invalide.'
Write-Output 'OK : syntaxe PowerShell du superviseur.'
