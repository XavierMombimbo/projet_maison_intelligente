function Get-TunnelRecoveryAction {
    param(
        [Parameter(Mandatory = $true)][hashtable]$State,
        [Parameter(Mandatory = $true)][bool]$Running,
        [datetime]$Now = [datetime]::UtcNow,
        [ValidateRange(1, 20)][int]$MaximumAttempts = 5
    )

    if ($Running) {
        if (($Now - $State.StartedAt).TotalSeconds -ge 300) {
            $State.Failures = 0
        }
        return [pscustomobject]@{ Action = 'None'; Delay = 0; Attempt = $State.Failures }
    }

    if ($null -eq $State.NextStart) {
        if ($State.Failures -ge $MaximumAttempts) {
            return [pscustomobject]@{ Action = 'Stop'; Delay = 0; Attempt = $State.Failures }
        }
        $State.Failures += 1
        $delay = [math]::Min(60, 5 * [math]::Pow(2, $State.Failures - 1))
        $State.NextStart = $Now.AddSeconds($delay)
        return [pscustomobject]@{ Action = 'Scheduled'; Delay = $delay; Attempt = $State.Failures }
    }

    if ($Now -lt $State.NextStart) {
        return [pscustomobject]@{ Action = 'Wait'; Delay = 0; Attempt = $State.Failures }
    }

    $State.StartedAt = $Now
    $State.NextStart = $null
    return [pscustomobject]@{ Action = 'Restart'; Delay = 0; Attempt = $State.Failures }
}
