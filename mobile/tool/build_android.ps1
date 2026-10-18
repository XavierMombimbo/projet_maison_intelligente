[CmdletBinding()]
param(
    [string]$ApiBaseUrl = 'https://sentinelle.smartxcongo.com',
    [string]$GradleUserHome = $env:SENTINELLE_GRADLE_USER_HOME,
    [string]$BuildDir = $env:SENTINELLE_MOBILE_BUILD_DIR,
    [string]$JavaHome = $env:SENTINELLE_JAVA_HOME,
    [string]$JavaSocketTemp = $env:SENTINELLE_JAVA_SOCKET_TMP,
    [switch]$WithoutFirebase,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$mobileRoot = Split-Path -Parent $PSScriptRoot
$packageConfig = Join-Path $mobileRoot '.dart_tool\package_config.json'
$requiredFirebaseVariables = @(
    'FIREBASE_API_KEY',
    'FIREBASE_APP_ID',
    'FIREBASE_MESSAGING_SENDER_ID',
    'FIREBASE_PROJECT_ID'
)

$apiUri = $null
if (-not [Uri]::TryCreate($ApiBaseUrl, [UriKind]::Absolute, [ref]$apiUri) -or
    $apiUri.Scheme -notin @('http', 'https')) {
    throw 'ApiBaseUrl doit etre une adresse HTTP ou HTTPS absolue.'
}

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw 'Flutter est introuvable dans PATH.'
}

if (-not (Test-Path -LiteralPath $packageConfig)) {
    throw "Les dependances Flutter manquent. Executez d'abord 'flutter pub get' dans mobile/."
}

if ([string]::IsNullOrWhiteSpace($GradleUserHome)) {
    if (Test-Path -LiteralPath 'E:\') {
        $GradleUserHome = 'E:\CodexCaches\sentinelle-gradle'
    } else {
        $GradleUserHome = Join-Path $env:LOCALAPPDATA 'SentinelleMaison\gradle-cache'
    }
}

if ([string]::IsNullOrWhiteSpace($BuildDir)) {
    if (Test-Path -LiteralPath 'E:\') {
        $BuildDir = 'E:\CodexCaches\sentinelle-mobile-build'
    } else {
        $BuildDir = Join-Path $env:LOCALAPPDATA 'SentinelleMaison\mobile-build'
    }
}
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null

if ([string]::IsNullOrWhiteSpace($JavaHome)) {
    $portableJavaHome = 'E:\CodexCaches\microsoft-jdk-21\jdk-21.0.12.1+1'
    # Directory.Exists returns false when the optional cache volume is not mounted.
    # Join-Path would instead raise before the Gradle cache fallback can run.
    if ([System.IO.Directory]::Exists($portableJavaHome) -and
        (Test-Path -LiteralPath (Join-Path $portableJavaHome 'bin\java.exe'))) {
        $JavaHome = $portableJavaHome
    }
}

if (-not [string]::IsNullOrWhiteSpace($JavaHome) -and
    -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin\java.exe'))) {
    throw "JavaHome ne contient pas bin\java.exe : $JavaHome"
}

if ([string]::IsNullOrWhiteSpace($JavaSocketTemp)) {
    $JavaSocketTemp = Join-Path (Split-Path -Parent $GradleUserHome) 'java-sockets'
}
New-Item -ItemType Directory -Path $JavaSocketTemp -Force | Out-Null

$cacheRoot = [System.IO.Path]::GetPathRoot($GradleUserHome)
if (-not [string]::IsNullOrWhiteSpace($cacheRoot)) {
    $driveName = $cacheRoot.TrimEnd('\').TrimEnd(':')
    $drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
    if ($null -ne $drive -and $drive.Free -lt 4GB) {
        $freeGb = [Math]::Round($drive.Free / 1GB, 1)
        throw "Espace insuffisant sur $cacheRoot ($freeGb Go libres). Il faut au moins 4 Go."
    }
}

$firebaseValues = @{}
foreach ($name in $requiredFirebaseVariables) {
    $firebaseValues[$name] = [Environment]::GetEnvironmentVariable($name)
}

$configuredFirebaseVariables = @(
    $requiredFirebaseVariables | Where-Object {
        -not [string]::IsNullOrWhiteSpace($firebaseValues[$_])
    }
)

if ($WithoutFirebase) {
    if ($configuredFirebaseVariables.Count -gt 0) {
        Write-Warning 'WithoutFirebase ignore les variables Firebase presentes.'
    }
} elseif ($configuredFirebaseVariables.Count -ne $requiredFirebaseVariables.Count) {
    $missing = @(
        $requiredFirebaseVariables | Where-Object {
            [string]::IsNullOrWhiteSpace($firebaseValues[$_])
        }
    )
    throw "Configuration Firebase incomplete. Variables manquantes : $($missing -join ', '). Utilisez -WithoutFirebase uniquement pour un APK sans notifications push."
}

$previousJavaHome = $env:JAVA_HOME
$previousJavaToolOptions = $env:JAVA_TOOL_OPTIONS
$previousGradleUserHome = $env:GRADLE_USER_HOME
$previousBuildDir = $env:SENTINELLE_MOBILE_BUILD_DIR
$previousPath = $env:PATH
$socketOption = "-Djdk.net.unixdomain.tmpdir=`"$JavaSocketTemp`""
$flutterArguments = @(
    'build',
    'apk',
    '--debug',
    '--no-pub',
    "--dart-define=SENTINELLE_API_BASE_URL=$ApiBaseUrl"
)

if (-not $WithoutFirebase) {
    foreach ($name in $requiredFirebaseVariables) {
        $flutterArguments += "--dart-define=$name=$($firebaseValues[$name])"
    }
}

Write-Host "Projet mobile : $mobileRoot"
Write-Host "Cache Gradle : $GradleUserHome"
Write-Host "Artefacts Android : $BuildDir"
Write-Host "Java : $(if ([string]::IsNullOrWhiteSpace($JavaHome)) { 'configuration Flutter' } else { $JavaHome })"
Write-Host "Sockets Java : $JavaSocketTemp"
Write-Host "Serveur integre : $ApiBaseUrl"
Write-Host "Firebase : $(if ($WithoutFirebase) { 'desactive' } else { 'configure' })"

if ($CheckOnly) {
    $visibleDefines = @('SENTINELLE_API_BASE_URL')
    if (-not $WithoutFirebase) {
        $visibleDefines += $requiredFirebaseVariables
    }
    Write-Host "Verification terminee. Variables injectees : $($visibleDefines -join ', ')."
    return
}

# Flutter 3.41 still discovers APKs under <project>/build even when Gradle's
# output directory is overridden. Keep that entry point on the same volume.
$flutterBuildPath = Join-Path $mobileRoot 'build'
$resolvedBuildDir = (Get-Item -LiteralPath $BuildDir).FullName.TrimEnd('\')
if ($resolvedBuildDir -ne $flutterBuildPath.TrimEnd('\')) {
    if ($resolvedBuildDir.StartsWith("$flutterBuildPath\", [StringComparison]::OrdinalIgnoreCase)) {
        throw 'BuildDir ne peut pas etre un sous-dossier de mobile/build.'
    }
    $existingBuildEntry = Get-Item -LiteralPath $flutterBuildPath -Force -ErrorAction SilentlyContinue
    $previousBuildTarget = $null
    if ($null -ne $existingBuildEntry) {
        if ($existingBuildEntry.LinkType -ne 'Junction') {
            throw 'mobile/build existe sans etre une jonction. Aucun fichier existant ne sera deplace.'
        }
        $previousBuildTarget = @($existingBuildEntry.Target)[0]
    }
    if ($previousBuildTarget -ne $resolvedBuildDir) {
        if ($null -ne $existingBuildEntry) {
            # Delete only the checked junction itself, never its target directory.
            [System.IO.Directory]::Delete($flutterBuildPath)
        }
        try {
            New-Item -ItemType Junction -Path $flutterBuildPath -Target $resolvedBuildDir | Out-Null
        } catch {
            if ($null -ne $previousBuildTarget -and -not (Test-Path -LiteralPath $flutterBuildPath)) {
                New-Item -ItemType Junction -Path $flutterBuildPath -Target $previousBuildTarget | Out-Null
            }
            throw
        }
    }
}

$env:GRADLE_USER_HOME = $GradleUserHome
$env:SENTINELLE_MOBILE_BUILD_DIR = $BuildDir
if (-not [string]::IsNullOrWhiteSpace($JavaHome)) {
    $env:JAVA_HOME = $JavaHome
    $env:PATH = "$(Join-Path $JavaHome 'bin');$previousPath"
}
$env:JAVA_TOOL_OPTIONS = "$previousJavaToolOptions $socketOption".Trim()

Push-Location $mobileRoot
try {
    & flutter @flutterArguments
    if ($LASTEXITCODE -ne 0) {
        throw "La compilation Flutter a echoue avec le code $LASTEXITCODE."
    }
} finally {
    Pop-Location
    $env:GRADLE_USER_HOME = $previousGradleUserHome
    $env:SENTINELLE_MOBILE_BUILD_DIR = $previousBuildDir
    $env:JAVA_HOME = $previousJavaHome
    $env:JAVA_TOOL_OPTIONS = $previousJavaToolOptions
    $env:PATH = $previousPath
}

$apkPath = Join-Path $BuildDir 'app\outputs\flutter-apk\app-debug.apk'
if (-not (Test-Path -LiteralPath $apkPath)) {
    throw "Flutter a termine sans produire l'APK attendu : $apkPath"
}

$apk = Get-Item -LiteralPath $apkPath
$sha256 = (Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "APK : $apkPath"
Write-Host "Taille : $([Math]::Round($apk.Length / 1MB, 1)) Mo"
Write-Host "SHA-256 : $sha256"
