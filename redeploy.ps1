# redeploy.ps1 (ASCII-only) - attempt 2: redeploy Weasel with full diagnostics.
# Differences vs attempt 1 (which timed out at 180s with WeaselServer stopped):
#   - WeaselDeployer runs VISIBLE and with the server RUNNING (designed maintenance flow)
#   - up to 600s, polling every 5s: process CPU, main window title, build file progress
#   - auto-dismisses a blocking MessageBox if one appears (mutex / help dialogs)
#   - afterwards: find + tail any Weasel logs, verify build, (re)start WeaselServer
$ErrorActionPreference = 'Continue'
$ws = 'D:\MiniPrograms\RimeData'
$installDir = 'C:\Program Files\Rime\weasel-0.17.4'
$dep = Join-Path $installDir 'WeaselDeployer.exe'
$srv = Join-Path $installDir 'WeaselServer.exe'
$buildFile = Join-Path $ws 'build\luna_pinyin_simp.schema.yaml'
$log = @()
function Say([string]$m) { $script:log += $m; Write-Output $m }

Add-Type -Namespace RimeHelp -Name Win -MemberDefinition @'
[DllImport("user32.dll", CharSet = CharSet.Unicode)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, IntPtr lParam, uint flags, uint timeout, out UIntPtr result);
[DllImport("user32.dll")]
public static extern bool PostMessage(IntPtr hWnd, uint Msg, UIntPtr wParam, IntPtr lParam);
'@ -ErrorAction SilentlyContinue

function Close-Dialogs([int]$procId) {
  try {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    $h = $p.MainWindowHandle
    if ($h -eq [IntPtr]::Zero) { return $false }
    Say ("  dialog detected, hwnd=" + $h + " title=[" + $p.MainWindowTitle + "] - trying to close it")
    [uint32]$smto = 2 -bor 1  # SMTO_ABORTIFHUNG + SMTO_BLOCK
    $r = [UIntPtr]::Zero
    [void][RimeHelp.Win]::SendMessageTimeout($h, 0x0010, [UIntPtr]::Zero, [IntPtr]::Zero, $smto, 800, [ref]$r) # WM_CLOSE
    [void][RimeHelp.Win]::PostMessage($h, 0x0111, [UIntPtr]::new(2), [IntPtr]::Zero)                          # WM_COMMAND IDCANCEL
    return $true
  } catch { return $false }
}

function Build-State {
  try {
    if (-not (Test-Path $buildFile)) { return 'missing' }
    $item = Get-Item $buildFile
    $has = $false
    try { $has = Select-String -Path $buildFile -Pattern 'input_count' -SimpleMatch -Quiet } catch { }
    return ($item.LastWriteTimeUtc.ToString('HH:mm:ss') + ' has_input=' + $has)
  } catch { return 'error' }
}

Say '==== redeploy attempt 2 (server running, visible, 600s, polling)'
Say ('build BEFORE: ' + (Build-State))

# clean up any stray deployer from attempt 1
Get-Process WeaselDeployer -ErrorAction SilentlyContinue | ForEach-Object {
  Say ('killing stray process: ' + $_.Id)
  Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

# make sure the server is up (designed flow: maintenance mode + EndMaintenance reload)
$srvProc = Get-Process WeaselServer -ErrorAction SilentlyContinue
if (-not $srvProc) {
  Say 'WeaselServer not running - starting it first ...'
  Start-Process -FilePath $srv -WorkingDirectory $installDir
  Start-Sleep -Seconds 4
  $srvProc = Get-Process WeaselServer -ErrorAction SilentlyContinue
}
Say ('WeaselServer running: ' + [bool]$srvProc)

$deployed = $false
$exitInfo = 'not-run'
for ($attempt = 1; $attempt -le 2 -and -not $deployed; $attempt++) {
  Say ("---- deploy attempt #" + $attempt)
  try {
    $p = Start-Process -FilePath $dep -ArgumentList '/deploy' -WorkingDirectory $installDir -PassThru
  } catch {
    Say ('FAILED to start deployer: ' + $_.Exception.Message)
    break
  }
  $deadline = (Get-Date).AddSeconds(600)
  $closedDialog = $false
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $state = Build-State
    if ($state -like '*has_input=True*') { $deployed = $true }
    if ($p.HasExited) {
      $exitInfo = ('exit code = ' + $p.ExitCode)
      Say ('deployer exited: ' + $exitInfo + '  build=' + $state)
      break
    }
    $cpu = -1.0; $title = ''
    try {
      $pr = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
      if ($pr) { $cpu = [math]::Round($pr.TotalProcessorTime.TotalSeconds, 1); $title = $pr.MainWindowTitle }
    } catch { }
    Say ('poll: cpu=' + $cpu + 's title=[' + $title + '] build=' + $state)
    if ($title -ne '' -and -not $closedDialog) {
      if (Close-Dialogs $p.Id) { $closedDialog = $true }
    }
    if ($state -like '*has_input=True*') { $deployed = $true; break }
  }
  if ($deployed) { break }
  if (-not $p.HasExited) {
    Say 'deployer still running after 600s - killing it.'
    try { $p.Kill() } catch { }
    Start-Sleep -Seconds 2
  }
  if ($state -like '*has_input=True*') { $deployed = $true }
}
Say ('deployed = ' + $deployed)
Say ('build AFTER : ' + (Build-State))

# hunt for logs from this session (deployer/server), tail the newest
Say '---- log hunt'
$logDirs = @(
  (Join-Path $installDir 'log'),
  (Join-Path $ws 'log'),
  (Join-Path $env:TEMP 'rime'),
  (Join-Path $env:LOCALAPPDATA 'Rime'),
  $env:TEMP
)
$foundLogs = @()
foreach ($d in $logDirs) {
  if (-not (Test-Path $d)) { continue }
  $foundLogs += Get-ChildItem -Path $d -Filter '*.log*' -Recurse -Depth 2 -ErrorAction SilentlyContinue |
    Where-Object { $_ -and $_.LastWriteTime -gt (Get-Date).AddHours(-2) -and $_.Length -gt 0 } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 4
}
$foundLogs = @($foundLogs | Where-Object { $_ })
foreach ($lf in ($foundLogs | Sort-Object FullName -Unique)) {
  Say ('log: ' + $lf.FullName + ' (' + $lf.Length + ' bytes)')
  try {
    Get-Content -LiteralPath $lf.FullName -Tail 25 -ErrorAction Stop | ForEach-Object { Say ('    | ' + $_) }
  } catch { Say '    | (unreadable)' }
}
if (-not $foundLogs) { Say 'no recent logs found' }

# restart server so the new build is definitely loaded
if ($deployed) {
  Say 'restarting WeaselServer to load the new build ...'
  Stop-Process -Name WeaselServer -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  Start-Process -FilePath $srv -WorkingDirectory $installDir
  Start-Sleep -Seconds 4
}
$alive = [bool](Get-Process WeaselServer -ErrorAction SilentlyContinue)
Say ('WeaselServer running now: ' + $alive)

$final = Build-State
$ok = $deployed -and ($final -like '*has_input=True*')
Say ''
Say ('[' + $(if ($ok) { 'PASS' } else { 'FAIL' }) + '] redeploy: build contains lua_translator@*input_count = ' + $ok)
if (-not $ok) {
  Say 'MANUAL FALLBACK: right-click the Weasel tray icon -> Redeploy (re-deploy), then type ii to test.'
  Say '(If a dialog blocked the deployer, the tray action does the same job in-process.)'
}
$reportPath = Join-Path $ws 'REDEPLOY_RESULT.txt'
try {
  [System.IO.File]::WriteAllLines($reportPath, $script:log, [System.Text.UTF8Encoding]::new($false))
  Write-Output ('REPORT SAVED: ' + $reportPath)
} catch { Write-Output ('report save failed: ' + $_.Exception.Message) }
