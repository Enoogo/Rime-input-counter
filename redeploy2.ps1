# redeploy2.ps1 (ASCII-only) - attempt 3.
# Root cause from run 2: the deployer opened the settings dialog (title "Weasel schema
# list settings"), which means lpCmdLine was NOT exactly /deploy -> PS5.1 Start-Process
# quoted the argument. Two independent fixes combined here:
#   1) start via cmd with a verbatim command line (no PS argument quoting)
#   2) if the settings dialogs still appear, auto-click OK on them: per upstream source,
#      OK => reconfigured=true => Configurator::Run calls UpdateWorkspace => DEPLOY.
# Polls build file for lua input_count up to 300s, restarts server, writes report.
$ErrorActionPreference = 'Continue'
$ws = 'D:\MiniPrograms\RimeData'
$installDir = 'C:\Program Files\Rime\weasel-0.17.4'
$dep = Join-Path $installDir 'WeaselDeployer.exe'
$srv = Join-Path $installDir 'WeaselServer.exe'
$buildFile = Join-Path $ws 'build\luna_pinyin_simp.schema.yaml'
$log = @()
function Say([string]$m) { $script:log += $m; Write-Output $m }

Add-Type -Namespace RimeHelp2 -Name Win -MemberDefinition @'
[DllImport("user32.dll", CharSet = CharSet.Unicode)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, IntPtr lParam, uint flags, uint timeout, out UIntPtr result);
[DllImport("user32.dll")]
public static extern bool PostMessage(IntPtr hWnd, uint Msg, UIntPtr wParam, IntPtr lParam);
[DllImport("user32.dll")]
public static extern bool SetForegroundWindow(IntPtr hWnd);
[DllImport("user32.dll")]
public static extern IntPtr GetForegroundWindow();
'@ -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue

function Build-State {
  try {
    if (-not (Test-Path $buildFile)) { return 'missing' }
    $item = Get-Item $buildFile
    $has = $false
    try { $has = Select-String -Path $buildFile -Pattern 'input_count' -SimpleMatch -Quiet } catch { }
    return ($item.LastWriteTimeUtc.ToString('HH:mm:ss') + ' has_input=' + $has)
  } catch { return 'error' }
}

function Auto-OK([int]$procId, [string]$title) {
  try {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    $p.Refresh()
    $h = $p.MainWindowHandle
    if ($h -eq [IntPtr]::Zero) {
      Say '  (dialog window handle not found yet)'
      return $false
    }
    Say ('  auto-OK dialog hwnd=' + $h + ' title=[' + $title + ']')
    [uint32]$smto = 2
    $r = [UIntPtr]::Zero
    # WTL dialog: WM_COMMAND with wParam=IDOK(1) -> OnOK -> EndDialog(IDOK)
    [void][RimeHelp2.Win]::SendMessageTimeout($h, 0x0111, [UIntPtr]::new(1), [IntPtr]::Zero, $smto, 1000, [ref]$r)
    Start-Sleep -Milliseconds 700
    $p.Refresh()
    if ($p.HasExited) { Say '  dialog accepted OK (process moved on)'; return $true }
    if ($p.MainWindowHandle -ne [IntPtr]::Zero -and $p.MainWindowTitle -eq $title) {
      # fallback: focus it and press Enter (OK is the default button)
      [void][RimeHelp2.Win]::SetForegroundWindow($p.MainWindowHandle)
      Start-Sleep -Milliseconds 300
      [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
      Start-Sleep -Milliseconds 700
      $p.Refresh()
      Say ('  SendKeys fallback, still alive=' + (-not $p.HasExited))
    }
    return $true
  } catch {
    Say ('  auto-OK error: ' + $_.Exception.Message)
    return $false
  }
}

function Invoke-Deployer([string]$style) {
  if ($style -eq 'psi') {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $dep
    $psi.Arguments = '/deploy'
    $psi.WorkingDirectory = $installDir
    $psi.UseShellExecute = $false
    Say 'starting via ProcessStartInfo (verbatim arguments, no shell quoting)'
    return [System.Diagnostics.Process]::Start($psi)
  }
  Say 'starting via direct exe /deploy (Start-Process)'
  return Start-Process -FilePath $dep -ArgumentList '/deploy' -WorkingDirectory $installDir -PassThru
}

Say '==== redeploy attempt 3 (verbatim cmdline + auto-OK on settings dialogs)'
Say ('build BEFORE: ' + (Build-State))
Get-Process WeaselDeployer -ErrorAction SilentlyContinue | ForEach-Object {
  Say ('killing stray deployer: ' + $_.Id)
  Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
$srvProc = Get-Process WeaselServer -ErrorAction SilentlyContinue
if (-not $srvProc) {
  Say 'WeaselServer not running - starting it ...'
  Start-Process -FilePath $srv -WorkingDirectory $installDir
  Start-Sleep -Seconds 4
}
Say ('WeaselServer running: ' + [bool](Get-Process WeaselServer -ErrorAction SilentlyContinue))

$deployed = $false
foreach ($style in @('direct', 'psi')) {
  if ($deployed) { break }
  Say ('---- style: ' + $style)
  try { $p = Invoke-Deployer $style } catch { Say ('start failed: ' + $_.Exception.Message); continue }
  Start-Sleep -Seconds 2
  try {
    $ci = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $p.Id) -ErrorAction SilentlyContinue
    if ($ci) { Say ('actual command line: ' + $ci.CommandLine) } else { Say 'deployer already gone' }
  } catch { }
  $deadline = (Get-Date).AddSeconds(300)
  $okdSwitcher = $false; $okdUi = $false; $okdOther = $false
  $sigFangan = '*' + [string][char]0x65B9 + [string][char]0x6848 + '*'      # *方案*
  $sigJiemian = '*' + [string][char]0x754C + [string][char]0x9762 + '*'     # *界面*
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $state = Build-State
    if ($state -like '*has_input=True*') { $deployed = $true; Say 'build updated - DEPLOYED'; break }
    $alive = -not $p.HasExited
    if (-not $alive) { Say ('deployer exited, exit code = ' + $p.ExitCode + '  build=' + $state); break }
    $p.Refresh()
    $title = $p.MainWindowTitle
    if ($title -like $sigFangan -and -not $okdSwitcher) {
      $okdSwitcher = $true; Say ('  switcher dialog: [' + $title + ']'); Auto-OK $p.Id $title
    } elseif ($title -like $sigJiemian -and -not $okdUi) {
      $okdUi = $true; Say ('  UI style dialog: [' + $title + ']'); Auto-OK $p.Id $title
    } elseif ($title -ne '' -and -not $okdOther) {
      $okdOther = $true
      Say ('  other dialog title=[' + $title + '] - auto-OK anyway')
      Auto-OK $p.Id $title
    }
    Say ('poll: alive=' + $alive + ' title=[' + $title + '] build=' + $state)
    if ($state -like '*has_input=True*') { $deployed = $true; break }
  }
  if ($deployed) { break }
  if (-not $p.HasExited) {
    Say 'deployer did not finish in 300s - killing it'
    try { $p.Kill() } catch { }
    Start-Sleep -Seconds 2
  }
}

$final = Build-State
$deployed = $final -like '*has_input=True*'
Say ('deployed = ' + $deployed + '  build AFTER: ' + $final)

if ($deployed) {
  Say 'restarting WeaselServer so the new build loads ...'
  Stop-Process -Name WeaselServer -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}
if (-not (Get-Process WeaselServer -ErrorAction SilentlyContinue)) {
  Start-Process -FilePath $srv -WorkingDirectory $installDir
  Start-Sleep -Seconds 4
}
$alive = [bool](Get-Process WeaselServer -ErrorAction SilentlyContinue)
Say ('WeaselServer running now: ' + $alive)

# show newest rime/weasel glog tail for the record
$glogDir = Join-Path $env:TEMP 'rime.weasel'
if (Test-Path $glogDir) {
  $newest = Get-ChildItem -Path $glogDir -Filter '*.log' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($newest) {
    Say ('newest rime log: ' + $newest.FullName)
    Get-Content -LiteralPath $newest.FullName -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object { Say ('    | ' + $_) }
  }
}

Say ''
Say ('[' + $(if ($deployed) { 'PASS' } else { 'FAIL' }) + '] redeploy: build contains lua_translator@*input_count = ' + $deployed)
if (-not $deployed) {
  Say 'MANUAL FALLBACK: right-click tray icon -> Redeploy (re-deploy), then type ii.'
}
$reportPath = Join-Path $ws 'REDEPLOY_RESULT.txt'
try {
  [System.IO.File]::WriteAllLines($reportPath, $script:log, [System.Text.UTF8Encoding]::new($false))
  Write-Output ('REPORT SAVED: ' + $reportPath)
} catch { Write-Output ('report save failed: ' + $_.Exception.Message) }
