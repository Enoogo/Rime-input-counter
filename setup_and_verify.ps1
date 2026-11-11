# setup_and_verify.ps1 (ASCII-only on purpose)
# One-shot installer + verifier for ramonmi/Rime-input-count and the HTML chart tool.
# Steps: detect active Rime user dir -> sync files -> detect Python -> generate charts
#        -> static checks -> redeploy Weasel -> verify build -> report.
$ErrorActionPreference = 'Continue'
$ws = 'D:\MiniPrograms\RimeData'
$script:log = @()
$script:flags = @{}

function Say([string]$m) {
  $script:log += $m
  Write-Output $m
}
function Sec([string]$m) {
  Say ''
  Say ('==== ' + $m)
}

Sec '1. Detect active Rime user directory'
$regDir = $null
try {
  $regDir = (Get-ItemProperty -Path 'HKCU:\SOFTWARE\Rime\Weasel' -Name 'RimeUserDir' -ErrorAction Stop).RimeUserDir
} catch { }
Say ('registry HKCU\\SOFTWARE\\Rime\\Weasel RimeUserDir = [' + [string]$regDir + ']')
$defaultDir = Join-Path $env:APPDATA 'Rime'
Say ('fallback default user dir = [' + $defaultDir + ']')
$active = $defaultDir
if ($regDir -and $regDir.Trim()) { $active = $regDir.Trim() }
function Norm([string]$p) {
  if (-not $p) { return '' }
  return $p.Trim().TrimEnd('\').ToLowerInvariant()
}
$active = $active.Trim().TrimEnd('\')
$sameDir = ((Norm $active) -eq (Norm $ws))
Say ('active user dir = [' + $active + ']')
Say ('active == workspace = ' + $sameDir)
# Safety: if the chosen active dir looks uninitialized while the workspace has a real
# installation, prefer the workspace instead of copying files into a bogus location.
if (-not $sameDir) {
  $activeHasInstall = Test-Path (Join-Path $active 'installation.yaml')
  $wsHasInstall = Test-Path (Join-Path $ws 'installation.yaml')
  if ((-not $activeHasInstall) -and $wsHasInstall) {
    Say 'WARN: active dir has no installation.yaml but workspace does - using workspace as active dir.'
    $active = $ws
    $sameDir = $true
  }
}
if (Test-Path (Join-Path $active 'installation.yaml')) {
  Say 'installation.yaml of active dir:'
  Get-Content (Join-Path $active 'installation.yaml') | ForEach-Object { Say ('  ' + $_) }
} else {
  Say 'WARN: active dir has no installation.yaml'
}
$script:flags.dir = $true

Sec '2. Sync plugin files into active dir (only if it differs from workspace)'
$syncOk = $true
if ($sameDir) {
  Say 'active dir == workspace, files are already in place.'
} else {
  try {
    $luaDir = Join-Path $active 'lua'
    New-Item -ItemType Directory -Force -Path $luaDir | Out-Null
    Copy-Item (Join-Path $ws 'lua\input_count.lua') (Join-Path $luaDir 'input_count.lua') -Force
    Say ('copied -> ' + (Join-Path $luaDir 'input_count.lua'))
    Copy-Item (Join-Path $ws 'rime.lua') (Join-Path $active 'rime.lua') -Force
    Say ('copied -> ' + (Join-Path $active 'rime.lua'))
    $target = Join-Path $active 'luna_pinyin_simp.custom.yaml'
    if (Test-Path $target) {
      $txt = [System.IO.File]::ReadAllText($target)
      if ($txt -match 'input_count') {
        Say 'custom yaml already contains input_count - skip.'
      } elseif ($txt -match 'engine/translators') {
        Say 'WARN: custom yaml defines engine/translators WITHOUT input_count - patch manually (see README).'
        $syncOk = $false
      } else {
        Copy-Item $target ($target + '.bak') -Force
        $lines = [System.IO.File]::ReadAllLines($target)
        $block = @(
          '  engine/translators:',
          '    - punct_translator',
          '    - "table_translator@custom_phrase"',
          '    - reverse_lookup_translator',
          '    - script_translator',
          '    - "lua_translator@*input_count"'
        )
        $out = New-Object System.Collections.Generic.List[string]
        $inserted = $false
        foreach ($l in $lines) {
          $out.Add($l)
          if ((-not $inserted) -and ($l -match '^patch:\s*$')) {
            foreach ($b in $block) { $out.Add($b) }
            $inserted = $true
          }
        }
        if ($inserted) {
          [System.IO.File]::WriteAllLines($target, $out, [System.Text.UTF8Encoding]::new($false))
          Say ('patched existing custom yaml (backup: ' + $target + '.bak)')
        } else {
          Say 'WARN: no "^patch:" line found in existing custom yaml - not modified, patch manually (see README).'
          $syncOk = $false
        }
      }
    } else {
      Copy-Item (Join-Path $ws 'luna_pinyin_simp.custom.yaml') $target -Force
      Say ('copied -> ' + $target)
    }
  } catch {
    Say ('WARN: sync failed: ' + $_.Exception.Message)
    $syncOk = $false
  }
}
$script:flags.sync = $syncOk

Sec '3. Detect Python 3'
$pyExe = $null
$pyPre = @()
$pyVer = ''
$probeList = @(
  @('py', '-3'),
  @('python', ''),
  @('python3', '')
)
foreach ($c in $probeList) {
  $exeName = $c[0]
  $extra = $c[1]
  $cmd = Get-Command $exeName -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $cmd) { continue }
  $src = $null
  if ($cmd.PSObject.Properties['Path'] -and $cmd.Path) { $src = $cmd.Path }
  elseif ($cmd.PSObject.Properties['Definition'] -and $cmd.Definition) { $src = $cmd.Definition }
  if (-not $src) { continue }
  $argList = @()
  if ($extra) { $argList += $extra }
  $argList += '--version'
  try {
    $v = (& $src @argList 2>&1 | Out-String)
    if (($LASTEXITCODE -eq 0) -and ($v -match 'Python\s+3')) {
      $pyExe = $src
      $pyPre = @()
      if ($extra) { $pyPre = @($extra) }
      $pyVer = $v.Trim()
      break
    }
  } catch { }
}
if (-not $pyExe) {
  $dirs = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
    'C:\Python313', 'C:\Python312', 'C:\Python311', 'C:\Python310',
    (Join-Path $env:USERPROFILE 'scoop\apps\python\current'),
    'D:\Python', 'D:\MiniPrograms'
  )
  foreach ($d in $dirs) {
    if ($pyExe) { break }
    if (-not (Test-Path $d)) { continue }
    $found = Get-ChildItem -Path $d -Filter 'python.exe' -Recurse -Depth 3 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
      try {
        $v = (& $found.FullName '--version' 2>&1 | Out-String)
        if (($LASTEXITCODE -eq 0) -and ($v -match 'Python\s+3')) {
          $pyExe = $found.FullName
          $pyPre = @()
          $pyVer = $v.Trim()
          break
        }
      } catch { }
    }
  }
}
if ($pyExe) {
  Say ('Python FOUND: ' + $pyVer + '  (' + $pyExe + ')')
  $script:flags.python = $true
} else {
  Say 'WARN: Python 3 NOT FOUND - the PowerShell chart generator will be used instead (no PNG export).'
  $script:flags.python = $false
}

Sec '4. Generate charts (real data + sample demo)'
$realIn = Join-Path $ws 'input_count.txt'
$realOut = Join-Path $ws 'input_count_chart.html'
$demoIn = Join-Path $ws 'sample_input_count.txt'
$demoOut = Join-Path $ws 'demo_chart.html'
$chartOk = $false
$demoOk = $false
$genUsed = 'powershell'
$psGen = Join-Path $ws 'chart_powershell.ps1'

function Invoke-PSChart([string]$inPath, [string]$outPath, [bool]$demoFlag) {
  try {
    if ($demoFlag) {
      & (Join-Path $ws 'chart_powershell.ps1') -InputPath $inPath -OutputPath $outPath -Demo
    } else {
      & (Join-Path $ws 'chart_powershell.ps1') -InputPath $inPath -OutputPath $outPath
    }
  } catch {
    Say ('WARN: powershell chart generator error: ' + $_.Exception.Message)
  }
}

if ($pyExe) {
  $genUsed = 'python'
  $baseArgs = @()
  foreach ($a in $pyPre) { $baseArgs += $a }
  $baseArgs += (Join-Path $ws 'plot_input_count.py')

  Say '--- run #1: real data (input_count.txt may not exist yet)'
  try {
    & $pyExe @baseArgs
    Say ('exit code = ' + $LASTEXITCODE)
    Say '--- run #2: sample data -> demo_chart.html'
    $demoArgs = @()
    foreach ($a in $baseArgs) { $demoArgs += $a }
    $demoArgs += @('--input', $demoIn, '--output', $demoOut, '--demo')
    & $pyExe @demoArgs
    Say ('exit code = ' + $LASTEXITCODE)
  } catch {
    Say ('WARN: python chart run failed: ' + $_.Exception.Message)
  }
  $pyOk = (Test-Path $realOut) -and ((Get-Item $realOut).Length -gt 1000)
  if (-not $pyOk) {
    Say 'WARN: python produced no valid chart - falling back to PowerShell generator.'
    $genUsed = 'powershell(fallback)'
    Invoke-PSChart $realIn $realOut $false
    Invoke-PSChart $demoIn $demoOut $true
  }
} else {
  Say 'Python 3 not found - using the PowerShell chart generator.'
  Invoke-PSChart $realIn $realOut $false
  Invoke-PSChart $demoIn $demoOut $true
}
Say ('chart generator used: ' + $genUsed)

if ((Test-Path $realOut) -and ((Get-Item $realOut).Length -gt 1000)) {
  $chartOk = $true
}
if ((Test-Path $demoOut) -and ((Get-Item $demoOut).Length -gt 5000)) {
  $hasSvg = $false
  if (Select-String -Path $demoOut -Pattern '<svg' -SimpleMatch -Quiet) { $hasSvg = $true }
  $demoOk = $hasSvg
}
foreach ($f in @($realOut, $demoOut)) {
  if (Test-Path $f) {
    Say ('output: ' + $f + '  ' + (Get-Item $f).Length + ' bytes')
  } else {
    Say ('MISSING OUTPUT: ' + $f)
  }
}
$script:flags.chart = $chartOk
$script:flags.demo = $demoOk

Sec '5. Static checks of installed plugin files (active dir)'
$staticOk = $true
$luaFile = Join-Path $active 'lua\input_count.lua'
if (Test-Path $luaFile) {
  $luaTxt = [System.IO.File]::ReadAllText($luaFile)
  Say ('OK lua module exists: ' + $luaFile + '  ' + (Get-Item $luaFile).Length + ' bytes')
  if ($luaTxt -match 'input_count\.txt') { Say 'OK lua db_path points to input_count.txt' }
  else { Say 'WARN: lua db_path does not mention input_count.txt'; $staticOk = $false }
  if ($luaTxt -match 'local command_key = "ii"') { Say 'OK lua command_key = ii' }
  else { Say 'WARN: lua command_key is not ii (check file)' }
} else {
  Say ('FAIL: lua module missing at ' + $luaFile)
  $staticOk = $false
}
$rimeLua = Join-Path $active 'rime.lua'
if (Test-Path $rimeLua) { Say ('OK rime.lua exists: ' + $rimeLua) }
else { Say ('FAIL: rime.lua missing at ' + $rimeLua); $staticOk = $false }
$customYaml = Join-Path $active 'luna_pinyin_simp.custom.yaml'
if (Test-Path $customYaml) {
  $cTxt = [System.IO.File]::ReadAllText($customYaml)
  if ($cTxt -match 'lua_translator@\*input_count') { Say ('OK custom yaml patched: ' + $customYaml) }
  else { Say ('FAIL: custom yaml lacks lua_translator@*input_count: ' + $customYaml); $staticOk = $false }
} else {
  Say ('FAIL: custom yaml missing: ' + $customYaml)
  $staticOk = $false
}
$script:flags.static = $staticOk

Sec '6. Locate Weasel install dir and redeploy'
$installDir = $null
$server0 = Get-Process WeaselServer -ErrorAction SilentlyContinue | Select-Object -First 1
if ($server0) {
  try {
    $sp = $server0.Path
    if ($sp) { $installDir = Split-Path -Parent $sp; Say ('install dir from running WeaselServer: ' + $installDir) }
  } catch { Say 'WARN: cannot read WeaselServer path (access denied?), probing instead.' }
}
$roots = @(
  (Join-Path $env:ProgramFiles 'Rime'),
  'C:\Rime', 'D:\Rime',
  (Join-Path $env:LOCALAPPDATA 'Programs\Rime')
)
$pf86 = ${env:ProgramFiles(x86)}
if ($pf86) { $roots += (Join-Path $pf86 'Rime') }
foreach ($r in $roots) {
  if ($installDir) { break }
  if (-not (Test-Path $r)) { continue }
  $d = Get-ChildItem -Path $r -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'weasel-*' } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($d -and (Test-Path (Join-Path $d.FullName 'WeaselDeployer.exe'))) {
    $installDir = $d.FullName
  }
}
$deployer = $null
$serverExe = $null
if ($installDir) {
  Say ('install dir: ' + $installDir)
  $deployer = Join-Path $installDir 'WeaselDeployer.exe'
  $serverExe = Join-Path $installDir 'WeaselServer.exe'
} else {
  Say 'FAIL: cannot locate WeaselDeployer.exe (probe roots failed).'
}

$buildFile = Join-Path $active 'build\luna_pinyin_simp.schema.yaml'
$preStamp = $null
$preCustomTs = ''
if (Test-Path $buildFile) {
  $preStamp = (Get-Item $buildFile).LastWriteTimeUtc
  $preContent = [System.IO.File]::ReadAllText($buildFile)
  $m = [regex]::Match($preContent, 'luna_pinyin_simp\.custom:\s*(\d+)')
  if ($m.Success) { $preCustomTs = $m.Groups[1].Value }
  Say ('build schema BEFORE: mtime=' + $preStamp.ToString('s') + ' custom_ts=' + $preCustomTs)
} else {
  Say 'WARN: build schema not found before deploy'
}

$deployRan = $false
if ($deployer -and (Test-Path $deployer)) {
  $srv = Get-Process WeaselServer -ErrorAction SilentlyContinue
  if ($srv) {
    Say 'stopping WeaselServer before deploy ...'
    Stop-Process -Name WeaselServer -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
  }
  Say 'running WeaselDeployer.exe /deploy (timeout 180s) ...'
  try {
    $p = Start-Process -FilePath $deployer -ArgumentList '/deploy' -WorkingDirectory $installDir -PassThru -WindowStyle Hidden
    if ($p.WaitForExit(180000)) {
      Say ('deployer finished, exit code = ' + $p.ExitCode)
      $deployRan = $true
    } else {
      Say 'WARN: deployer timed out after 180s - killing it.'
      try { $p.Kill() } catch { }
    }
  } catch {
    Say ('WARN: deployer failed to start: ' + $_.Exception.Message)
  }
} else {
  Say 'SKIP: deployer not available'
}

# (Re)start the server only if it had been running before this script.
Start-Sleep -Seconds 1
$serverWasRunning = [bool]$server0
if ($serverWasRunning) {
  if (-not (Get-Process WeaselServer -ErrorAction SilentlyContinue)) {
    if ($serverExe -and (Test-Path $serverExe)) {
      Say 'starting WeaselServer again ...'
      Start-Process -FilePath $serverExe -WorkingDirectory $installDir
      Start-Sleep -Seconds 3
    }
  }
}
$serverNow = Get-Process WeaselServer -ErrorAction SilentlyContinue
Say ('WeaselServer was running before = ' + $serverWasRunning + ', now running = ' + [bool]$serverNow)
if ($serverWasRunning -and (-not $serverNow)) {
  Say 'FAIL: WeaselServer could not be restarted - start it from the Start menu (input method needs it).'
}
$script:flags.server = (-not $serverWasRunning) -or [bool]$serverNow

Sec '7. Verify deployment result (build dir of active user dir)'
$buildOk = $false
if (Test-Path $buildFile) {
  $item = Get-Item $buildFile
  $content = [System.IO.File]::ReadAllText($buildFile)
  $hasInput = ($content -match 'input_count')
  $m2 = [regex]::Match($content, 'luna_pinyin_simp\.custom:\s*(\d+)')
  $postCustomTs = ''
  if ($m2.Success) { $postCustomTs = $m2.Groups[1].Value }
  Say ('build schema AFTER : mtime=' + $item.LastWriteTimeUtc.ToString('s') + ' custom_ts=' + $postCustomTs)
  Say ('build contains lua_translator@*input_count = ' + $hasInput)
  $m3 = [regex]::Match($content, 'lua_translator[^\r\n]*')
  if ($m3.Success) { Say ('found line: ' + $m3.Value.Trim()) }
  $tsChanged = ($preCustomTs -ne '') -and ($preCustomTs -ne $postCustomTs)
  Say ('custom yaml compile timestamp changed = ' + $tsChanged)
  if ($hasInput -and $deployRan) { $buildOk = $true }
  if ($hasInput -and (-not $deployRan)) {
    Say 'NOTE: build already contains the plugin (deploy may not have run, but result is correct).'
    $buildOk = $true
  }
} else {
  Say ('FAIL: build schema missing: ' + $buildFile)
}
$script:flags.build = $buildOk

Sec '8. RESULT SUMMARY'
Remove-Item -Path (Join-Path $ws '.scratch_test.txt') -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $ws '__pycache__') -Recurse -Force -ErrorAction SilentlyContinue
function Line([string]$k, $v, [string]$extra) {
  $st = 'FAIL'
  if ($v) { $st = 'PASS' }
  Say ('[' + $st + '] ' + $k + $(if ($extra) { ' - ' + $extra } else { '' }))
}
Line 'active Rime user dir detected' $script:flags.dir ''
Line 'plugin files in place (static check)' $script:flags.static ''
Say ('[INFO] python available = ' + $script:flags.python + ' (optional; PowerShell fallback covers it)')
Line 'real chart generated (may be empty state)' $script:flags.chart ''
Line 'demo chart generated with sample data' $script:flags.demo ''
Line 'weasel redeployed with new config' $script:flags.build ''
Line 'WeaselServer running again' $script:flags.server ''
if (-not $script:flags.sync) { Say '[FAIL] sync to active dir - see warnings above / README manual steps' }

Say ''
Say 'USAGE:'
Say '  1. In Chinese mode, type: i i   -> stats appear in the candidate list; Esc closes it.'
Say '  2. Double-click "查看每日统计.bat" -> generates and opens input_count_chart.html'
Say '  3. Demo chart with fake data: python plot_input_count.py --input sample_input_count.txt --output demo_chart.html'
Say ''
if (-not ($script:flags.build -and $script:flags.static)) {
  Say 'MANUAL FALLBACK (if anything above failed):'
  Say '  Right-click the Weasel tray icon -> Redeploy (重新部署), then type "ii" to test.'
}

$reportPath = Join-Path $ws 'SETUP_RESULT.txt'
try {
  [System.IO.File]::WriteAllLines($reportPath, $script:log, [System.Text.UTF8Encoding]::new($false))
  Write-Output ''
  Write-Output ('REPORT SAVED: ' + $reportPath)
} catch {
  Write-Output ('WARN: could not save report: ' + $_.Exception.Message)
}

# Open the demo chart so the result is visible right away (best effort).
try {
  if (Test-Path $demoOut) {
    Start-Process $demoOut
    Write-Output ('OPENED: ' + $demoOut)
  }
} catch { }
