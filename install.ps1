# install.ps1 (ASCII-only on purpose)
# Generic installer for the Rime-input-count plugin + chart tools.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
#
# Steps: detect Rime user dir -> install lua/input_count.lua -> merge rime.lua
#        -> patch the schema custom yaml -> copy chart tools into the data dir
#        -> static checks + usage hints. Existing files are backed up as *.bak.
#
# Parameters:
#   -UserDir <path>   Rime user directory (default: registry RimeUserDir, else %APPDATA%\Rime)
#   -DataDir <path>   data + chart tools directory (default: <UserDir>\Rime-input-count)
#                     When given explicitly, lua's data_dir_override is set to this path.
#   -Schema <name>    schema to patch (default: luna_pinyin_simp)
#   -NoToolsCopy      do not copy chart tools into the data directory
#   -Deploy           also try WeaselDeployer.exe /deploy afterwards (best effort)
#   -DryRun           print planned actions without writing anything

param(
  [string]$UserDir = '',
  [string]$DataDir = '',
  [string]$Schema = 'luna_pinyin_simp',
  [switch]$NoToolsCopy,
  [switch]$Deploy,
  [switch]$DryRun
)
$ErrorActionPreference = 'Continue'
$src = $PSScriptRoot
$script:log = @()
$script:fail = 0

function Say([string]$m) {
  $script:log += $m
  Write-Output $m
}
function Sec([string]$m) {
  Say ''
  Say ('==== ' + $m)
}
function Note([string]$m) {
  if ($DryRun) { Say ('  [dry-run] ' + $m) } else { Say ('  ' + $m) }
}
function Fail([string]$m) {
  $script:fail++
  Say ('  [FAIL] ' + $m)
}
function Backup-File([string]$path) {
  if (Test-Path -LiteralPath $path) {
    $bak = $path + '.bak'
    if (-not $DryRun) { Copy-Item -LiteralPath $path -Destination $bak -Force }
    Say ('  backed up: ' + $path + ' -> ' + (Split-Path -Leaf $bak))
  }
}
function Copy-FileX([string]$from, [string]$to) {
  if (-not (Test-Path -LiteralPath $from)) {
    Fail ('source missing: ' + $from)
    return
  }
  $dir = Split-Path -Parent $to
  if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Note ('mkdir: ' + $dir)
  }
  Backup-File $to
  if (-not $DryRun) { Copy-Item -LiteralPath $from -Destination $to -Force }
  Say ('  installed: ' + $to)
}
function Write-TextX([string]$path, [string[]]$lines, [switch]$Append) {
  $dir = Split-Path -Parent $path
  if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  }
  if (-not $DryRun) {
    $enc = [System.Text.UTF8Encoding]::new($false)
    if ($Append) {
      [System.IO.File]::AppendAllLines($path, [string[]]$lines, $enc)
    } else {
      [System.IO.File]::WriteAllLines($path, [string[]]$lines, $enc)
    }
  }
}
function Norm([string]$p) {
  if (-not $p) { return '' }
  return $p.Trim().TrimEnd('\').ToLowerInvariant()
}

# ---------------------------------------------------------------- 1. user dir
Sec '1. Detect Rime user directory'
$regDir = $null
try {
  $regDir = (Get-ItemProperty -Path 'HKCU:\SOFTWARE\Rime\Weasel' -Name 'RimeUserDir' -ErrorAction Stop).RimeUserDir
} catch { }
$defaultUserDir = Join-Path $env:APPDATA 'Rime'
Say ('registry RimeUserDir = [' + [string]$regDir + ']')
Say ('default user dir    = [' + $defaultUserDir + ']')
$target = $UserDir
if (-not $target) {
  if ($regDir -and $regDir.Trim()) { $target = $regDir.Trim() } else { $target = $defaultUserDir }
}
$target = $target.Trim().TrimEnd('\')
Say ('using user dir      = [' + $target + ']')
if (Test-Path -LiteralPath $target) {
  Say '  user dir exists: yes'
} else {
  Say '  WARN: user dir does not exist yet (fresh install?) - continuing anyway.'
}

# ---------------------------------------------------------------- 2. data dir
$explicitDataDir = $PSBoundParameters.ContainsKey('DataDir')
if (-not $DataDir) { $DataDir = Join-Path $target 'Rime-input-count' }
$DataDir = $DataDir.Trim().TrimEnd('\')
Sec '2. Data + chart tools directory'
Say ('data dir = [' + $DataDir + ']')
if ($explicitDataDir) {
  Say '  (explicit -DataDir: lua data_dir_override will be set to this path)'
} else {
  Say '  (default: lua auto-locates <user dir>\Rime-input-count via rime_api.get_user_data_dir())'
}
if (-not (Test-Path -LiteralPath $DataDir)) {
  if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $DataDir | Out-Null }
  Note ('mkdir: ' + $DataDir)
}

# ---------------------------------------------------------------- 3. lua module
Sec '3. Install lua/input_count.lua'
$luaSrc = Join-Path $src 'lua\input_count.lua'
$luaDst = Join-Path $target 'lua\input_count.lua'
Copy-FileX $luaSrc $luaDst
if ($explicitDataDir -and -not $DryRun -and (Test-Path -LiteralPath $luaDst)) {
  try {
    $txt = [System.IO.File]::ReadAllText($luaDst)
    # Lua string literal: backslash -> \\ , quote -> \"
    $esc = $DataDir.Replace('\', '\\').Replace('"', '\"')
    $txt = [regex]::Replace($txt, '(?m)^local data_dir_override = ".*"$',
      ('local data_dir_override = "' + $esc + '"'))
    [System.IO.File]::WriteAllText($luaDst, $txt, [System.Text.UTF8Encoding]::new($false))
    Say ('  data_dir_override rewritten -> ' + $DataDir)
  } catch {
    Fail ('could not rewrite data_dir_override: ' + $_.Exception.Message)
  }
}
if ($explicitDataDir) {
  Note 'check: lua data_dir_override should point to the data dir (edit by hand if needed)'
} else {
  Note 'check: lua data path resolves to <user dir>\Rime-input-count automatically'
}

# ---------------------------------------------------------------- 4. rime.lua
Sec '4. Merge rime.lua (old-style librime fallback entry)'
$rimeSrc = Join-Path $src 'rime.lua'
$rimeDst = Join-Path $target 'rime.lua'
if (Test-Path -LiteralPath $rimeDst) {
  $cur = ''
  try { $cur = [System.IO.File]::ReadAllText($rimeDst) } catch { }
  if ($cur -match 'input_count') {
    Say '  rime.lua already references input_count - skip.'
  } else {
    Backup-File $rimeDst
    Write-TextX $rimeDst @(
      '',
      '-- ===== Rime-input-count (added by install.ps1) =====',
      'local ok_ic, mod_ic = pcall(require, "input_count")',
      'if ok_ic and mod_ic then',
      '  input_count = mod_ic',
      'end'
    ) -Append
    Say '  appended input_count binding to existing rime.lua'
  }
} else {
  Copy-FileX $rimeSrc $rimeDst
}

# ---------------------------------------------------------------- 5. schema patch
Sec ('5. Patch schema custom yaml (' + $Schema + ')')
$custom = Join-Path $target ($Schema + '.custom.yaml')
$translators = @(
  '  engine/translators:',
  '    - punct_translator',
  '    - "table_translator@custom_phrase"',
  '    - reverse_lookup_translator',
  '    - script_translator',
  '    - "lua_translator@*input_count"'
)
if (Test-Path -LiteralPath $custom) {
  $txt = ''
  try { $txt = [System.IO.File]::ReadAllText($custom) } catch { }
  if ($txt -match 'input_count') {
    Say '  custom yaml already contains input_count - skip.'
  } elseif ($txt -match 'engine/translators') {
    Fail 'custom yaml already defines engine/translators WITHOUT input_count.'
    Say '  -> add this item to your engine/translators list by hand:'
    Say '       "lua_translator@*input_count"'
    Say '     (see README, section: manual installation)'
  } else {
    Backup-File $custom
    if (-not $DryRun) {
      $lines = [System.IO.File]::ReadAllLines($custom)
      $out = New-Object System.Collections.Generic.List[string]
      $inserted = $false
      foreach ($l in $lines) {
        $out.Add($l)
        if ((-not $inserted) -and ($l -match '^patch:\s*$')) {
          foreach ($b in $translators) { $out.Add($b) }
          $inserted = $true
        }
      }
      if ($inserted) {
        [System.IO.File]::WriteAllLines($custom, $out, [System.Text.UTF8Encoding]::new($false))
        Say '  patched existing custom yaml (engine/translators block inserted).'
      } else {
        Fail 'no "^patch:" line found in custom yaml - patch it by hand (see README).'
      }
    } else {
      Note ('would insert engine/translators block into ' + $custom)
    }
  }
} else {
  if ($Schema -eq 'luna_pinyin_simp') {
    Copy-FileX (Join-Path $src 'luna_pinyin_simp.custom.yaml') $custom
  } else {
    Fail ('no ' + $Schema + '.custom.yaml found and this installer only ships one for luna_pinyin_simp.')
    Say '  -> create it by hand with a patch that adds "lua_translator@*input_count"'
    Say '     to engine/translators (copy luna_pinyin_simp.custom.yaml as a model).'
  }
}

# ---------------------------------------------------------------- 6. chart tools
Sec '6. Copy chart tools into the data directory'
if ($NoToolsCopy) {
  Say '  skipped (-NoToolsCopy).'
} elseif ((Norm $src) -eq (Norm $DataDir)) {
  Say '  this folder IS the data dir - nothing to copy.'
} else {
  foreach ($n in @('plot_input_count.py', 'chart_powershell.ps1', 'sample_input_count.txt', 'sample_input_count_raw.txt')) {
    Copy-FileX (Join-Path $src $n) (Join-Path $DataDir $n)
  }
  # the launcher .bat has a non-ASCII file name -> match it by pattern
  $bat = Get-ChildItem -LiteralPath $src -Filter '*.bat' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($bat) {
    Copy-FileX $bat.FullName (Join-Path $DataDir $bat.Name)
  } else {
    Fail 'launcher .bat not found in the package folder.'
  }
}

# ---------------------------------------------------------------- 7. checks
Sec '7. Static checks'
function Check([string]$name, [bool]$ok) {
  if ($ok) { Say ('  [PASS] ' + $name) } else { Say ('  [FAIL] ' + $name); $script:fail++ }
}
if ($DryRun) {
  Say '  (skipped in -DryRun mode)'
} else {
  Check 'lua module installed' (Test-Path -LiteralPath $luaDst)
  $cTxt = ''
  if (Test-Path -LiteralPath $custom) { try { $cTxt = [System.IO.File]::ReadAllText($custom) } catch { } }
  Check 'custom yaml wires lua_translator@*input_count' ($cTxt -match 'lua_translator@\*input_count')
  $rTxt = ''
  if (Test-Path -LiteralPath $rimeDst) { try { $rTxt = [System.IO.File]::ReadAllText($rimeDst) } catch { } }
  Check 'rime.lua exists (fallback entry)' ([bool](Test-Path -LiteralPath $rimeDst))
  Check 'data dir exists' (Test-Path -LiteralPath $DataDir)
  if (-not $NoToolsCopy) {
    Check 'chart tools present in data dir' (Test-Path -LiteralPath (Join-Path $DataDir 'plot_input_count.py'))
  }
}

# ---------------------------------------------------------------- 8. optional deploy
if ($Deploy) {
  Sec '8. Redeploy Weasel (best effort)'
  $installDir = $null
  $srv = Get-Process WeaselServer -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($srv) {
    try { $installDir = Split-Path -Parent $srv.Path } catch { }
  }
  if (-not $installDir) {
    foreach ($r in @((Join-Path $env:ProgramFiles 'Rime'), (Join-Path ${env:ProgramFiles(x86)} 'Rime'))) {
      if ($installDir -or -not $r -or -not (Test-Path $r)) { continue }
      $d = Get-ChildItem -Path $r -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'weasel-*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($d) { $installDir = $d.FullName }
    }
  }
  $deployer = $null
  if ($installDir) { $deployer = Join-Path $installDir 'WeaselDeployer.exe' }
  if ($deployer -and (Test-Path $deployer) -and -not $DryRun) {
    Say ('running: ' + $deployer + ' /deploy')
    try {
      $p = Start-Process -FilePath $deployer -ArgumentList '/deploy' -WorkingDirectory $installDir -PassThru -WindowStyle Hidden
      if ($p.WaitForExit(120000)) { Say ('deployer finished, exit code = ' + $p.ExitCode) }
      else { Say 'WARN: deployer timed out after 120s (a settings dialog may be open) - use the tray menu instead.'; try { $p.Kill() } catch { } }
    } catch {
      Say ('WARN: deployer failed: ' + $_.Exception.Message)
    }
  } else {
    Say '  deployer not found (or -DryRun) - deploy manually (see below).'
  }
} else {
  Sec '8. Redeploy (manual)'
  Say '  skipped (default). Run with -Deploy to attempt it automatically.'
}

# ---------------------------------------------------------------- summary
Sec 'RESULT SUMMARY'
Say ('failures = ' + $script:fail)
Say ''
Say 'NEXT STEPS:'
Say '  1. Right-click the Weasel tray icon and choose Redeploy.'
Say '  2. In Chinese mode type: i i   -> stats appear in the candidate list; Esc closes it.'
Say '  3. Double-click the launcher .bat (Chinese name) in the data dir to generate + open the chart.'
Say '  4. Demo chart without typing: python plot_input_count.py --demo --output demo_chart.html'
Say ''
Say 'NOTES:'
Say '  - Data files (input_count*.txt) are written to the data dir; they contain only'
Say '    timestamps + counts, never the text you typed.'
Say '  - Changing lua/input_count.lua later needs a WeaselServer restart (or redeploy).'
Say '  - If "ii" does nothing: check engine/translators in your schema build, redeploy,'
Say '    and make sure you commit text in Chinese mode.'
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
