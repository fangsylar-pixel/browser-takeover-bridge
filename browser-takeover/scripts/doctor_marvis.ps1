[CmdletBinding()]
param()

$ErrorActionPreference = 'SilentlyContinue'
$server = Join-Path $PSScriptRoot 'browser_takeover_mcp.py'
$extension = Join-Path (Split-Path -Parent $PSScriptRoot) 'extension\manifest.json'

$checks = @()
$checks += [pscustomobject]@{ Check = 'MCP server script'; OK = Test-Path -LiteralPath $server; Detail = $server }
$checks += [pscustomobject]@{ Check = 'Extension manifest'; OK = Test-Path -LiteralPath $extension; Detail = $extension }

$listener = Get-NetTCPConnection -State Listen -LocalPort 17321 | Select-Object -First 1
$checks += [pscustomobject]@{
    Check = 'Bridge listener'
    OK = [bool]$listener
    Detail = if ($listener) { "127.0.0.1:17321 (PID $($listener.OwningProcess))" } else { 'Not listening; save/restart the MARVIS MCP first.' }
}

$status = $null
if ($listener) {
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:17321/bridge/status' -TimeoutSec 3
}
$clientCount = if ($status) { @($status.clients).Count } else { 0 }
$tabCount = if ($status) { [int]$status.tabCount } else { 0 }
$checks += [pscustomobject]@{
    Check = 'Companion extension'
    OK = $clientCount -gt 0
    Detail = "$clientCount connected client(s)"
}
$checks += [pscustomobject]@{
    Check = 'Browser tabs'
    OK = $tabCount -gt 0
    Detail = "$tabCount synchronized tab(s)"
}

$checks | Format-Table -AutoSize
if ($checks.OK -contains $false) {
    Write-Host 'Not ready. Resolve the failed checks above.' -ForegroundColor Yellow
    exit 1
}
Write-Host 'Browser Takeover is ready for MARVIS.' -ForegroundColor Green

