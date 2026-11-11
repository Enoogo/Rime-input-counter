# restore_layout.ps1 - restore the original RimeData file layout (ASCII-only on purpose).
# Reverses the reorganization described in RESTORE_MANIFEST.txt:
#   1) moves statistics tooling + data + reports from Rime-input-count\ back to the root
#   2) restores the ORIGINAL copies of edited files (lua\input_count.lua, README.md)
#   3) restarts WeaselServer so the restored lua data paths take effect
# NOTE: the chart scripts keep the "initial view = newest (rightmost) data" improvement.
# Usage: double-click "restore_layout.bat" in the user-folder root, or run this file directly.

$ErrorActionPreference = 'Continue'
$ws  = 'D:\MiniPrograms\RimeData'
$bin = Join-Path $ws 'Rime-input-count'
$bak = Join-Path $bin 'restore_backup'

function Move-Back([string]$src, [string]$dst) {
    if (Test-Path -LiteralPath $src) {
        Move-Item -LiteralPath $src -Destination $dst -Force
        Write-Host ('restored: ' + (Split-Path -Leaf $dst))
    } else {
        Write-Host ('skip (not found): ' + $src)
    }
}

Write-Host '== 1/3 statistics tooling + data + reports back to root =='
foreach ($n in @('plot_input_count.py', 'chart_powershell.ps1', 'README.md',
                 'input_count.txt', 'input_count_raw.txt', 'input_count_raw.tmp',
                 'sample_input_count.txt', 'input_count_chart.html', 'demo_chart.html',
                 'setup_and_verify.ps1', 'finalize.ps1', 'redeploy.ps1', 'redeploy2.ps1',
                 'SETUP_RESULT.txt', 'FINALIZE_RESULT.txt', 'REDEPLOY_RESULT.txt',
                 'RESTORE_MANIFEST.txt')) {
    Move-Back (Join-Path $bin $n) (Join-Path $ws $n)
}
# the launcher .bat has a non-ASCII file name -> match it by pattern
Get-ChildItem -LiteralPath $bin -Filter '*.bat' -ErrorAction SilentlyContinue | ForEach-Object {
    Move-Back $_.FullName (Join-Path $ws $_.Name)
}

Write-Host '== 2/3 restore originals of edited files =='
if (Test-Path -LiteralPath (Join-Path $bak 'input_count.lua')) {
    Copy-Item -LiteralPath (Join-Path $bak 'input_count.lua') `
              -Destination (Join-Path $ws 'lua\input_count.lua') -Force
    Write-Host 'restored: lua\input_count.lua (original data paths -> root input_count*.txt)'
} else {
    Write-Host 'WARN: backup of lua\input_count.lua not found; edit the three data paths back by hand.'
}
if (Test-Path -LiteralPath (Join-Path $bak 'README.md')) {
    Copy-Item -LiteralPath (Join-Path $bak 'README.md') `
              -Destination (Join-Path $ws 'README.md') -Force
    Write-Host 'restored: README.md (original)'
}

Write-Host '== 3/3 restart WeaselServer =='
Get-Process -Name 'WeaselServer' -ErrorAction SilentlyContinue | Stop-Process -Force
$server = 'C:\Program Files\Rime\weasel-0.17.4\WeaselServer.exe'
if (Test-Path -LiteralPath $server) {
    Start-Process -FilePath $server
    Write-Host 'WeaselServer restarted.'
} else {
    Write-Host 'WARN: WeaselServer.exe not found - please start Weasel from the Start menu.'
}

Write-Host ''
Write-Host 'DONE. Original layout restored.'
Write-Host 'NOTE: the chart scripts keep the "initial view = newest (rightmost) data" improvement.'
Write-Host 'Optional cleanup: delete "restore_layout.bat" in the root and the'
Write-Host 'Rime-input-count\restore_layout.ps1 / restore_backup\ files if no longer needed.'
