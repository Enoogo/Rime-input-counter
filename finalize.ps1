# finalize.ps1 (ASCII-only) - one-shot: build charts (Python + PS fallback test),
# then redeploy/restart Weasel to activate the new minute-level lua, then verify.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File finalize.ps1 [-SkipDeploy]
param([switch]$SkipDeploy)
$ErrorActionPreference = 'Continue'
$ws = 'D:\MiniPrograms\RimeData'
$installDir = 'C:\Program Files\Rime\weasel-0.17.4'
$srv = Join-Path $installDir 'WeaselServer.exe'
$buildFile = Join-Path $ws 'build\luna_pinyin_simp.schema.yaml'
$chartPy = Join-Path $ws 'plot_input_count.py'
$chartPs = Join-Path $ws 'chart_powershell.ps1'
$luaFile = Join-Path $ws 'lua\input_count.lua'
$realHtml = Join-Path $ws 'input_count_chart.html'
$demoHtml = Join-Path $ws 'demo_chart.html'
$psCheck = Join-Path $ws '_ps_fallback_check.html'
$reportPath = Join-Path $ws 'FINALIZE_RESULT.txt'
$script:log = @()
function Say([string]$m) { $script:log += $m; Write-Output $m }

function Ensure-Bom([string]$path) {
  try {
    $b = [System.IO.File]::ReadAllBytes($path)
    if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { return }
    $nb = [byte[]]::new($b.Length + 3)
    $nb[0] = 0xEF; $nb[1] = 0xBB; $nb[2] = 0xBF
    [Array]::Copy($b, 0, $nb, 3, $b.Length)
    [System.IO.File]::WriteAllBytes($path, $nb)
    Say ('BOM added: ' + $path)
  } catch { Say ('WARN BOM: ' + $_.Exception.Message) }
}

function Html-Has([string]$path, [string]$needle) {
  try { return (([System.IO.File]::ReadAllText($path)).Contains($needle)) } catch { return $false }
}

# One-time/idempotent: collapse input_count_raw.txt to exactly one line per minute.
function Compact-Raw([string]$path) {
  try {
    if (-not (Test-Path -LiteralPath $path)) { return 'no file' }
    $re = [regex]'^\s*e=(\d{12})\s+w=(-?\d+)\s+k=(-?\d+)\s*$'
    $agg = @{}
    foreach ($raw in [System.IO.File]::ReadAllLines($path)) {
      $m = $re.Match($raw.Trim())
      if (-not $m.Success) { continue }
      $key = $m.Groups[1].Value
      $w = [int]$m.Groups[2].Value
      $k = [int]$m.Groups[3].Value
      if ($agg.ContainsKey($key)) { $agg[$key] = @(($agg[$key][0] + $w), ($agg[$key][1] + $k)) }
      else { $agg[$key] = @($w, $k) }
    }
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($key in ($agg.Keys | Sort-Object)) {
      $lines.Add(('e={0} w={1} k={2}' -f $key, $agg[$key][0], $agg[$key][1]))
    }
    [System.IO.File]::WriteAllLines($path, $lines, [System.Text.UTF8Encoding]::new($false))
    return ('compacted to ' + $lines.Count + ' minute line(s)')
  } catch { return ('compact error: ' + $_.Exception.Message) }
}

Say '==== STEP 1: chart generators (Python primary, PowerShell fallback)'
Ensure-Bom $chartPs
$pyExe = $null; $pyPre = @()
foreach ($c in @(@('py','-3'), @('python',''), @('python3',''))) {
  $cmd = Get-Command $c[0] -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $cmd) { continue }
  $src = $null
  if ($cmd.PSObject.Properties['Path'] -and $cmd.Path) { $src = $cmd.Path }
  elseif ($cmd.PSObject.Properties['Definition'] -and $cmd.Definition) { $src = $cmd.Definition }
  if (-not $src) { continue }
  $argList = @(); if ($c[1]) { $argList += $c[1] }; $argList += '--version'
  try {
    $v = (& $src @argList 2>&1 | Out-String)
    if (($LASTEXITCODE -eq 0) -and ($v -match 'Python\s+3')) { $pyExe = $src; if ($c[1]) { $pyPre = @($c[1]) }; break }
  } catch { }
}
if ($pyExe) { Say ('Python: ' + $pyExe) } else { Say 'WARN: Python 3 not found - Python chart skipped, PowerShell fallback will be used' }

$pyReal = $false; $pyDemo = $false; $psDemo = $false
if ($pyExe) {
  $baseArgs = @(); foreach ($a in $pyPre) { $baseArgs += $a }; $baseArgs += $chartPy
  Say '--- python real chart'
  try { & $pyExe @baseArgs; Say ('exit=' + $LASTEXITCODE) } catch { Say ('ERR ' + $_.Exception.Message) }
  Say '--- python demo chart'
  try {
    $d = @(); foreach ($a in $baseArgs) { $d += $a }; $d += @('--demo','--output',$demoHtml)
    & $pyExe @d; Say ('exit=' + $LASTEXITCODE)
  } catch { Say ('ERR ' + $_.Exception.Message) }
  $pyReal = (Test-Path $realHtml) -and ((Get-Item $realHtml).Length -gt 800)
  $pyDemo = (Test-Path $demoHtml) -and ((Get-Item $demoHtml).Length -gt 800)
}

Say '--- PowerShell fallback self-test (demo)'
try {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $chartPs -Demo -OutputPath $psCheck
  Say ('ps exit=' + $LASTEXITCODE)
  if ((Test-Path $psCheck) -and ((Get-Item $psCheck).Length -gt 800)) {
    $hasTabs = (Html-Has $psCheck 'id="s-dagg"') -and (Html-Has $psCheck 'pane-min')
    $hasSvg = Html-Has $psCheck '<svg'
    $hasTip = (Html-Has $psCheck 'id="tt"') -and (Html-Has $psCheck 'class="hit"')
    $hasInter = (Html-Has $psCheck 'MIN_RAW=') -and (Html-Has $psCheck 'renderMin') -and (Html-Has $psCheck 'minDensityLabel')
    Say ('ps fallback: tabs=' + $hasTabs + ' svg=' + $hasSvg + ' tooltip=' + $hasTip + ' interactive=' + $hasInter)
    $psDemo = $hasTabs -and $hasSvg -and $hasTip -and $hasInter
    Remove-Item -Path $psCheck -Force -ErrorAction SilentlyContinue
  } else { Say 'ps fallback: output missing or too small' }
} catch { Say ('ps fallback ERR: ' + $_.Exception.Message) }

Say ''
Say '==== STEP 2: redeploy + restart to activate new minute-level lua'
if ($SkipDeploy) {
  Say 'skipped (-SkipDeploy): lua/schema unchanged this run'
} else {
  $redeploy = Join-Path $ws 'redeploy2.ps1'
  try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $redeploy
    Say ('redeploy exit=' + $LASTEXITCODE)
  } catch { Say ('redeploy ERR: ' + $_.Exception.Message) }
}

# 把已有的 input_count_raw.txt 压成“每分钟一行”（幂等；新数据由 Lua 也按此写入）
Say ('compact raw: ' + (Compact-Raw (Join-Path $ws 'input_count_raw.txt')))

Say ''
Say '==== STEP 3: verify'
$checks = @()
$luaRaw = Html-Has $luaFile 'input_count_raw.txt'
$checks += @('lua records minute-level raw (input_count_raw.txt): ' + $luaRaw)
$realTabs = (Html-Has $realHtml 'id="s-day"') -and (Html-Has $realHtml 'id="s-dagg"') -and (Html-Has $realHtml 'id="s-min"')
$checks += @('real chart has day/by-day/by-min tabs: ' + $realTabs)
$realTip = (Html-Has $realHtml 'id="tt"') -and (Html-Has $realHtml 'class="hit"')
$checks += @('real chart has hover tooltip: ' + $realTip)
$realInter = (Html-Has $realHtml 'MIN_RAW=') -and (Html-Has $realHtml 'renderMin') -and (Html-Has $realHtml 'minDensityLabel') -and (Html-Has $realHtml 'class="scroll"')
$checks += @('real chart has scroll + density controls: ' + $realInter)
$demoTabs = (Html-Has $demoHtml 'id="s-min"') -and (Html-Has $demoHtml '<svg')
$checks += @('demo chart has tabs + svg: ' + $demoTabs)
$buildOk = $false
try { $buildOk = (Select-String -Path $buildFile -Pattern 'input_count' -SimpleMatch -Quiet) } catch { }
$checks += @('build schema contains input_count: ' + $buildOk)
$srvUp = [bool](Get-Process WeaselServer -ErrorAction SilentlyContinue)
$checks += @('WeaselServer running: ' + $srvUp)

# Fix verification: today's summary value must appear in the real chart (not the raw partial).
$todayKey = (Get-Date).ToString('yyyyMMdd')
$todayW = $null
try {
  foreach ($line in [System.IO.File]::ReadAllLines((Join-Path $ws 'input_count.txt'))) {
    $m = [regex]::Match($line, ('^day=' + $todayKey + '\s+day_words=(-?\d+)'))
    if ($m.Success) { $todayW = [int]$m.Groups[1].Value }
  }
} catch { }
$todayMatch = $true
if ($null -ne $todayW -and $todayW -gt 0) {
  $fmtW = '{0:N0}' -f $todayW
  $todayMatch = Html-Has $realHtml $fmtW
  $checks += @(('today summary words=' + $todayW + ' shown in chart as ' + $fmtW + ': ' + $todayMatch))
} else {
  $checks += @('today consistency: no typed data yet (skipped)')
}
foreach ($c in $checks) { Say ('  ' + $c) }

$allOk = $luaRaw -and $realTabs -and $realTip -and $realInter -and $demoTabs -and $buildOk -and $srvUp -and $todayMatch -and ($psDemo -or $pyReal)
Say ''
Say ('[' + $(if ($allOk) { 'PASS' } else { 'FAIL' }) + '] finalize complete')
Say 'USAGE: Chinese mode -> type "ii" for live stats; double-click 查看每日统计.bat for the chart.'
Say 'The HTML chart has tabs at top: Daily / By-day / By-minute. Both aggregate tabs come from input_count_raw.txt.'

try {
  [System.IO.File]::WriteAllLines($reportPath, $script:log, [System.Text.UTF8Encoding]::new($false))
  Write-Output ('REPORT SAVED: ' + $reportPath)
} catch { Write-Output ('report save failed: ' + $_.Exception.Message) }

# Open the demo chart so the result is visible
try { if (Test-Path $demoHtml) { Start-Process $demoHtml; Write-Output ('OPENED: ' + $demoHtml) } } catch { }
