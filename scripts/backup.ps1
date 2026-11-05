# OPS-02: Windows convenience wrapper around pg_dump custom-format backup.
# Reads DATABASE_URL from the environment; never hardcode credentials here.
[CmdletBinding()]
param(
    [string]$BackupDir = $env:BACKUP_DIR,
    [string]$DatabaseUrl = $env:DATABASE_URL
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($BackupDir)) {
    $BackupDir = './backups'
}

if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    Write-Error 'DATABASE_URL is not set'
    exit 1
}

if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
    Write-Error 'pg_dump not found in PATH'
    exit 1
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$dumpPath = Join-Path $BackupDir "violencia-$timestamp.dump"

& pg_dump `
    --dbname="$DatabaseUrl" `
    --format=custom `
    --no-owner `
    --no-privileges `
    --file="$dumpPath"

if ($LASTEXITCODE -ne 0) {
    Write-Error "pg_dump failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash.ToLowerInvariant()
"$hash  $dumpPath" | Out-File -FilePath "$dumpPath.sha256" -Encoding ascii -NoNewline

Write-Output "backup written: $dumpPath"
Write-Output "checksum written: $dumpPath.sha256"
