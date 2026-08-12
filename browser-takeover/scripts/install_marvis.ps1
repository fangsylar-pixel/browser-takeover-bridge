[CmdletBinding()]
param(
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $PSScriptRoot
$server = Join-Path $PSScriptRoot 'browser_takeover_mcp.py'

if (-not (Test-Path -LiteralPath $server)) {
    throw "MCP server not found: $server"
}

$python = Get-Command py.exe -ErrorAction SilentlyContinue
if ($python) {
    $command = $python.Source
    $arguments = @('-3', $server)
} else {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $python) {
        throw 'Python 3 was not found. Install Python 3, then run this script again.'
    }
    $command = $python.Source
    $arguments = @($server)
}

$config = [ordered]@{
    mcpServers = [ordered]@{
        'browser-takeover' = [ordered]@{
            command = $command
            args = $arguments
        }
    }
}

$json = $config | ConvertTo-Json -Depth 5
if (-not $OutputPath) {
    $OutputPath = Join-Path $pluginRoot 'marvis-mcp.json'
}
Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8

Write-Host ''
Write-Host 'MARVIS MCP configuration generated:' -ForegroundColor Green
Write-Host $OutputPath
Write-Host ''
Write-Host 'Paste the JSON below into MARVIS > Custom MCP configuration:' -ForegroundColor Cyan
Write-Output $json
Write-Host ''
Write-Host 'Then restart MARVIS and run scripts\doctor_marvis.ps1.'

