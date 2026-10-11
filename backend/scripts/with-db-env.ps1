<#
.SYNOPSIS
  Runs a command (Maven, java -jar, ...) with the backend's database credentials loaded from mysql.env.

.DESCRIPTION
  Reads the project-root mysql.env located relative to THIS SCRIPT (not the current directory),
  or the file named by $env:EVCHARGE_DB_ENV_FILE. Only the application account is loaded:
      MYSQL_USER     -> DB_USERNAME
      MYSQL_PASSWORD -> DB_PASSWORD
  MYSQL_ROOT_PASSWORD is never read into the environment. Values are never printed, are set only
  for this PowerShell process and its children, and are removed again when the command finishes.
  The command runs from the backend directory.

.EXAMPLE
  .\scripts\with-db-env.ps1 mvn spring-boot:run
.EXAMPLE
  .\scripts\with-db-env.ps1 mvn verify
#>
param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]] $Command
)
$ErrorActionPreference = 'Stop'

$backendDir = Split-Path -Parent $PSScriptRoot
$envFile = if ($env:EVCHARGE_DB_ENV_FILE) { $env:EVCHARGE_DB_ENV_FILE } else { Join-Path (Split-Path -Parent $backendDir) 'mysql.env' }
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Database env file not found: $envFile (copy mysql.env.example to mysql.env in the project root)"
}

$map = @{ 'MYSQL_USER' = 'DB_USERNAME'; 'MYSQL_PASSWORD' = 'DB_PASSWORD' }
$loaded = @{}
foreach ($line in [IO.File]::ReadAllLines($envFile)) {
    $line = $line.Trim()
    if ($line -eq '' -or $line.StartsWith('#')) { continue }
    $i = $line.IndexOf('=')
    if ($i -lt 1) { continue }
    $key = $line.Substring(0, $i).Trim()
    if ($map.ContainsKey($key)) { $loaded[$map[$key]] = $line.Substring($i + 1).Trim() }
}
foreach ($required in 'DB_USERNAME', 'DB_PASSWORD') {
    if (-not $loaded[$required]) { throw "$envFile does not define the value needed for $required" }
}

$previous = @{}
try {
    foreach ($name in $loaded.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $loaded[$name], 'Process')
    }
    Write-Host "Loaded DB_USERNAME and DB_PASSWORD from $envFile (values not shown)"
    Push-Location $backendDir
    try {
        # Windows PowerShell turns a native program's stderr lines into error records; with 'Stop'
        # a harmless warning (e.g. from the JVM) would abort the command, so relax it for the call.
        $ErrorActionPreference = 'Continue'
        & $Command[0] @($Command | Select-Object -Skip 1)
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }
}
finally {
    foreach ($name in $loaded.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    $loaded.Clear()
}
exit $exitCode
