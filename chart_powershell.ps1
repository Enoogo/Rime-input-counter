# chart_powershell.ps1 - Fallback chart generator (same output as plot_input_count.py)
# Used automatically when Python 3 is not available. Reads input_count.txt (daily summary,
# authoritative) + input_count_raw.txt (minute raw) and writes an HTML chart with
# day/by-day/by-minute scale tabs and a hover tooltip.
param(
  [string]$SummaryPath = (Join-Path $PSScriptRoot 'input_count.txt'),
  [string]$RawPath = (Join-Path $PSScriptRoot 'input_count_raw.txt'),
  [string]$OutputPath = (Join-Path $PSScriptRoot 'input_count_chart.html'),
  [switch]$Demo
)

$ErrorActionPreference = 'Stop'
$COLOR_WORDS = '#2563eb'
$COLOR_KEYS = '#f59e0b'
$MAX_DAY = 365
# Static no-JS fallback SVG length cap; the live chart is drawn by JS with ALL points.
$MAX_MIN = 300

function Fmt($n) {
  try { return ('{0:N0}' -f [math]::Floor([double]$n)) } catch { return [string]$n }
}

function NiceMax($value) {
  $v = 0.0
  try { $v = [double]$value } catch { return 10 }
  if ($v -le 0) { return 10 }
  $exp = [math]::Floor([math]::Log10($v))
  $base = [math]::Pow(10, $exp)
  foreach ($mult in @(1, 2, 5, 10)) {
    if ($v -le ($mult * $base)) { return [int]($mult * $base) }
  }
  return [int](10 * $base)
}

function Read-Summary([string]$path) {
  $r = @{ start = ''; tw = 0; tk = 0; days = @{} }
  if (-not (Test-Path -LiteralPath $path)) { return $r }
  $dayRe = [regex]'^\s*day=(\d{8})\s+day_words=(-?\d+)\s+day_keys=(-?\d+)\s*$'
  $totalRe = [regex]'^\s*total_words=(-?\d+)\s+total_keys=(-?\d+)\s*$'
  $startRe = [regex]'^\s*start_iso=(\S.*)$'
  foreach ($raw in [System.IO.File]::ReadAllLines($path)) {
    $line = $raw.Trim()
    $m = $dayRe.Match($line)
    if ($m.Success) { $r.days[$m.Groups[1].Value] = @([int]$m.Groups[2].Value, [int]$m.Groups[3].Value); continue }
    $m = $totalRe.Match($line)
    if ($m.Success) { $r.tw = [int]$m.Groups[1].Value; $r.tk = [int]$m.Groups[2].Value; continue }
    $m = $startRe.Match($line)
    if ($m.Success -and $r.start -eq '') { $r.start = $m.Groups[1].Value.Trim() }
  }
  return $r
}

function Read-Raw([string]$path) {
  $minutes = @{}
  if (-not (Test-Path -LiteralPath $path)) { return $minutes }
  $re = [regex]'^\s*e=(\d{12})\s+w=(-?\d+)\s+k=(-?\d+)\s*$'
  $tmpPath = [System.IO.Path]::ChangeExtension($path, '.tmp')
  foreach ($src in @($path, $tmpPath)) {
    if (-not (Test-Path -LiteralPath $src)) { continue }
    foreach ($raw in [System.IO.File]::ReadAllLines($src)) {
      $m = $re.Match($raw.Trim())
      if (-not $m.Success) { continue }
      $key = $m.Groups[1].Value
      $w = [int]$m.Groups[2].Value
      $k = [int]$m.Groups[3].Value
      if ($minutes.ContainsKey($key)) {
        $minutes[$key] = @(($minutes[$key][0] + $w), ($minutes[$key][1] + $k))
      } else {
        $minutes[$key] = @($w, $k)
      }
    }
  }
  return $minutes
}

function Aggregate($minutes, [int]$width) {
  $acc = @{}
  foreach ($key in $minutes.Keys) {
    $b = $key.Substring(0, $width)
    $v = $minutes[$key]
    if ($acc.ContainsKey($b)) { $acc[$b] = @(($acc[$b][0] + $v[0]), ($acc[$b][1] + $v[1])) }
    else { $acc[$b] = @($v[0], $v[1]) }
  }
  return $acc
}

function Key-ToDate([string]$key, [string]$kind) {
  if ($kind -eq 'day') { return [datetime]::ParseExact($key, 'yyyyMMdd', $null) }
  else { return [datetime]::ParseExact($key, 'yyyyMMddHHmm', $null) }
}

function Date-ToKey([datetime]$d, [string]$kind) {
  if ($kind -eq 'day') { return $d.ToString('yyyyMMdd') }
  else { return $d.ToString('yyyyMMddHHmm') }
}

function Make-Items($map, [int]$maxn, [string]$kind) {
  $items = New-Object System.Collections.Generic.List[object]
  $keys = @($map.Keys | Sort-Object)
  if ($keys.Count -eq 0) { return $items }
  if ($kind -eq 'day') { $step = [timespan]::FromDays(1) }
  else { $step = [timespan]::FromMinutes(1) }
  $lastD = Key-ToDate $keys[-1] $kind
  $firstD = Key-ToDate $keys[0] $kind
  $earliest = $lastD.AddTicks(-($step.Ticks * ($maxn - 1)))
  $startD = $firstD
  if ($firstD -lt $earliest) { $startD = $earliest }
  $cur = $startD
  while ($cur -le $lastD) {
    $key = Date-ToKey $cur $kind
    $w = 0; $kk = 0
    if ($map.ContainsKey($key)) { $w = $map[$key][0]; $kk = $map[$key][1] }
    $lab = ''; $tlabel = ''; $dlab = ''
    if ($kind -eq 'day') {
      $lab = '{0}-{1}' -f $key.Substring(4,2), $key.Substring(6,2)
      $tlabel = '{0}-{1}-{2}' -f $key.Substring(0,4), $key.Substring(4,2), $key.Substring(6,2)
    } else {
      $lab = '{0}:{1}' -f $key.Substring(8,2), $key.Substring(10,2)
      $tlabel = '{0}-{1}-{2} {3}:{4}' -f $key.Substring(0,4), $key.Substring(4,2), $key.Substring(6,2), $key.Substring(8,2), $key.Substring(10,2)
      # 日期只标在每天 0:00 的数据点正下方（= 此点以右当天数据的日期）
      if ($key.Substring(8,4) -eq '0000') {
        $dlab = '{0}-{1}-{2}' -f $key.Substring(0,4), $key.Substring(4,2), $key.Substring(6,2)
      }
    }
    $items.Add([pscustomobject]@{ Key = $key; W = $w; K = $kk; Lab = $lab; TLabel = $tlabel; DateLab = $dlab })
    $cur = $cur.Add($step)
  }
  return $items
}

function Text-W([string]$s) {
  # rough 11px text width: ASCII ~0.62em, CJK ~1em (x-axis anti-overlap sizing)
  $w = 0.0
  foreach ($ch in $s.ToCharArray()) {
    if ([int]$ch -gt 0x2E80) { $w += 11.0 } else { $w += 6.82 }
  }
  return $w
}

function Build-Svg($items, [switch]$withDates) {
  $n = $items.Count
  $width = 1000; $height = 430
  $ml = 78; $mr = 78; $mt = 58; $mb = 64
  $pw = $width - $ml - $mr
  $ph = $height - $mt - $mb
  $wmax = NiceMax (($items | Measure-Object -Property W -Maximum).Maximum)
  $kmax = NiceMax (($items | Measure-Object -Property K -Maximum).Maximum)

  $out = New-Object System.Collections.Generic.List[string]
  $out.Add(('<svg class="chart" viewBox="0 0 {0} {1}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">' -f $width, $height))

  $steps = 5
  for ($s = 0; $s -le $steps; $s++) {
    $frac = $s / [double]$steps
    $y = $mt + $ph * (1.0 - $frac)
    $out.Add(('<line x1="{0}" y1="{1:F1}" x2="{2}" y2="{3:F1}" stroke="#e5e7eb" stroke-width="1"/>' -f $ml, $y, ($ml + $pw), $y))
    $out.Add(('<text x="{0}" y="{1:F1}" class="yl yl-left" text-anchor="end">{2}</text>' -f ($ml - 10), ($y + 4), (Fmt ($wmax * $frac))))
    $out.Add(('<text x="{0}" y="{1:F1}" class="yl yl-right" text-anchor="start">{2}</text>' -f ($ml + $pw + 10), ($y + 4), (Fmt ($kmax * $frac))))
  }
  $out.Add(('<line x1="{0}" y1="{1}" x2="{2}" y2="{3}" stroke="#9ca3af" stroke-width="1.2"/>' -f $ml, ($mt + $ph), ($ml + $pw), ($mt + $ph)))

  $yTime = $mt + $ph + 22
  $yDate = $mt + $ph + 42

  # day separators + date labels (under each day's 0:00 point = date of data to its right)
  if ($withDates) {
    for ($i = 0; $i -lt $n; $i++) {
      $dlab = [string]$items[$i].DateLab
      if (-not $dlab) { continue }
      if ($n -le 1) { $x = $ml + $pw * 0.5 } else { $x = $ml + $pw * [double]$i / [double]($n - 1) }
      $out.Add(('<line x1="{0:F1}" y1="{1}" x2="{0:F1}" y2="{2}" stroke="#d1d5db" stroke-width="1" stroke-dasharray="3 4"/>' -f $x, $mt, ($mt + $ph)))
      $out.Add(('<text x="{0:F1}" y="{1}" class="xl xd" text-anchor="middle">{2}</text>' -f $x, $yDate, [System.Net.WebUtility]::HtmlEncode($dlab)))
    }
  }

  # time ticks: stride from real text width vs point spacing -> never overlaps at any class width
  $dx = if ($n -gt 1) { [double]$pw / [double]($n - 1) } else { [double]$pw }
  $maxW = 0.0
  foreach ($it in $items) { $tw = Text-W ([string]$it.Lab); if ($tw -gt $maxW) { $maxW = $tw } }
  if ($dx -le 0) { $stride = [math]::Max(1, $n) } else { $stride = [math]::Max(1, [int][math]::Ceiling(($maxW + 12) / $dx)) }
  if ($stride -gt $n) { $stride = [math]::Max(1, $n) }
  for ($i = 0; $i -lt $n; $i += $stride) {
    if ($n -le 1) { $x = $ml + $pw * 0.5 } else { $x = $ml + $pw * [double]$i / [double]($n - 1) }
    $out.Add(('<text x="{0:F1}" y="{1}" class="xl" text-anchor="middle">{2}</text>' -f $x, $yTime, $items[$i].Lab))
  }

  $kpts = New-Object System.Collections.Generic.List[string]
  $wpts = New-Object System.Collections.Generic.List[string]
  for ($i = 0; $i -lt $n; $i++) {
    if ($n -le 1) { $x = $ml + $pw * 0.5 } else { $x = $ml + $pw * [double]$i / [double]($n - 1) }
    $yk = $mt + $ph * (1.0 - [double]$items[$i].K / [double]$kmax)
    $yw = $mt + $ph * (1.0 - [double]$items[$i].W / [double]$wmax)
    $kpts.Add(('{0:F1},{1:F1}' -f $x, $yk))
    $wpts.Add(('{0:F1},{1:F1}' -f $x, $yw))
  }
  $out.Add(('<polyline points="{0}" fill="none" stroke="{1}" stroke-width="2" stroke-dasharray="6 4" stroke-linejoin="round"/>' -f ($kpts -join ' '), $COLOR_KEYS))
  $out.Add(('<polyline points="{0}" fill="none" stroke="{1}" stroke-width="2.5" stroke-linejoin="round"/>' -f ($wpts -join ' '), $COLOR_WORDS))

  # visible dots
  for ($i = 0; $i -lt $n; $i++) {
    if ($n -le 1) { $x = $ml + $pw * 0.5 } else { $x = $ml + $pw * [double]$i / [double]($n - 1) }
    $yk = $mt + $ph * (1.0 - [double]$items[$i].K / [double]$kmax)
    $yw = $mt + $ph * (1.0 - [double]$items[$i].W / [double]$wmax)
    $out.Add(('<circle cx="{0:F1}" cy="{1:F1}" r="3.2" fill="{2}"/>' -f $x, $yk, $COLOR_KEYS))
    $out.Add(('<circle cx="{0:F1}" cy="{1:F1}" r="3.2" fill="{2}"/>' -f $x, $yw, $COLOR_WORDS))
  }

  # hover hit areas (transparent, carry data for the JS tooltip)
  for ($i = 0; $i -lt $n; $i++) {
    if ($n -le 1) { $x = $ml + $pw * 0.5 } else { $x = $ml + $pw * [double]$i / [double]($n - 1) }
    $yk = $mt + $ph * (1.0 - [double]$items[$i].K / [double]$kmax)
    $yw = $mt + $ph * (1.0 - [double]$items[$i].W / [double]$wmax)
    $tl = [System.Net.WebUtility]::HtmlEncode($items[$i].TLabel)
    $attrs = 'data-label="{0}" data-w="{1}" data-k="{2}"' -f $tl, (Fmt $items[$i].W), (Fmt $items[$i].K)
    $out.Add(('<circle class="hit" cx="{0:F1}" cy="{1:F1}" r="14" {2}/>' -f $x, $yw, $attrs))
    $out.Add(('<circle class="hit" cx="{0:F1}" cy="{1:F1}" r="14" {2}/>' -f $x, $yk, $attrs))
  }

  $out.Add(('<line x1="{0}" y1="24" x2="{1}" y2="24" stroke="{2}" stroke-width="3"/>' -f $ml, ($ml + 28), $COLOR_WORDS))
  $out.Add(('<text x="{0}" y="29" class="legend">上屏字数（左轴）</text>' -f ($ml + 36)))
  $out.Add(('<line x1="{0}" y1="24" x2="{1}" y2="24" stroke="{2}" stroke-width="3" stroke-dasharray="6 4"/>' -f ($ml + 190), ($ml + 218), $COLOR_KEYS))
  $out.Add(('<text x="{0}" y="29" class="legend">按键数（右轴）</text>' -f ($ml + 226)))
  $out.Add(('<text x="{0}" y="{1}" class="axis-title" text-anchor="middle">字</text>' -f ($ml - 44), ($mt - 12)))
  $out.Add(('<text x="{0}" y="{1}" class="axis-title" text-anchor="middle">键</text>' -f ($ml + $pw + 46), ($mt - 12)))
  $out.Add('</svg>')
  return ($out -join "`n")
}

$CSS = @'
* { box-sizing: border-box; }
body { margin: 0; background: #f3f4f6; color: #111827;
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 26px 16px 56px; }
h1 { font-size: 22px; margin: 0 0 6px; }
.sub { color: #6b7280; font-size: 13px; margin-bottom: 18px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
  padding: 12px 16px; min-width: 150px; flex: 1 1 150px; }
.card .k { font-size: 12px; color: #6b7280; }
.card .v { font-size: 20px; font-weight: 600; margin-top: 4px; }
.card .v small { font-size: 12px; font-weight: 400; color: #6b7280; }
.panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px 16px; }
svg.chart { width: 100%; height: auto; display: block; }
svg.chart text { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }
.yl { font-size: 11px; fill: #6b7280; }
.yl-left { fill: #2563eb; }
.yl-right { fill: #d97706; }
.xl { font-size: 11px; fill: #6b7280; }
.xd { fill: #4b5563; font-weight: 600; }
.legend { font-size: 13px; fill: #374151; }
.axis-title { font-size: 12px; fill: #9ca3af; }
details { margin-top: 14px; }
summary { cursor: pointer; color: #2563eb; font-size: 14px; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 13px; }
th, td { border: 1px solid #e5e7eb; padding: 6px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
tr:nth-child(even) td { background: #f9fafb; }
.empty { text-align: center; padding: 44px 16px; color: #6b7280; line-height: 1.9; }
.empty strong { color: #111827; font-size: 16px; }
.banner { background: #fef3c7; border: 1px solid #fcd34d; color: #92400e;
  padding: 10px 14px; border-radius: 8px; margin-bottom: 14px;
  font-size: 14px; text-align: center; }
code { background: #eef2ff; padding: 1px 6px; border-radius: 4px; font-size: 12px; }
.foot { color: #9ca3af; font-size: 12px; margin-top: 16px; line-height: 1.8; }
.note { color: #6b7280; font-size: 12px; margin-top: 10px; line-height: 1.7; }
.tabs input[type=radio] { position: absolute; opacity: 0; pointer-events: none; }
.tabbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.tabbar label { cursor: pointer; padding: 8px 18px; border: 1px solid #e5e7eb;
  border-radius: 8px; background: #fff; color: #374151; font-size: 13px; }
#s-day:checked ~ .tabbar label[for="s-day"],
#s-dagg:checked ~ .tabbar label[for="s-dagg"],
#s-min:checked ~ .tabbar label[for="s-min"] {
  background: #2563eb; color: #fff; border-color: #2563eb; }
.pane { display: none; }
#s-day:checked ~ .pane-day,
#s-dagg:checked ~ .pane-dagg,
#s-min:checked ~ .pane-min { display: block; }
circle.hit { fill: rgba(0,0,0,0); pointer-events: all; cursor: pointer; }
.minctl { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.minctl .minctl-label { font-size: 13px; color: #6b7280; }
.bm-input { width: 88px; padding: 6px 8px; border: 1px solid #e5e7eb; border-radius: 6px;
  font-size: 13px; color: #111827; background: #fff; }
.bm-input:focus { outline: none; border-color: #2563eb; }
.bkt { cursor: pointer; padding: 6px 14px; border: 1px solid #2563eb; border-radius: 6px;
  background: #2563eb; color: #fff; font-size: 12px; }
.bkt:hover { background: #1d4ed8; }
.minctl-hint { font-size: 12px; color: #b45309; }
.minwrap { position: relative; }
.scroll { overflow-x: auto; overflow-y: hidden; border: 1px solid #f1f5f9; border-radius: 8px;
  padding-bottom: 6px; }
/* 固定在滚动容器左右两侧的纵轴刻度（不随图表横向滚动） */
.yax { position: absolute; top: 0; width: 78px; height: 431px; pointer-events: none;
  border-radius: 8px 8px 0 0; }
.yax-l { left: 0; background: linear-gradient(to right, #fff 62%, rgba(255,255,255,0)); }
.yax-r { right: 0; background: linear-gradient(to left, #fff 62%, rgba(255,255,255,0)); }
.yax .yt { position: absolute; transform: translateY(-50%); font-size: 11px;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.yax-l .yt { right: 10px; text-align: right; }
.yax-r .yt { left: 10px; }
.yt-l { color: #2563eb; }
.yt-r { color: #d97706; }
.yt-title { font-size: 12px; color: #9ca3af; }
/* fixed date badge (bottom-left, under the left y-axis) once 0:00 scrolls out of view */
.datefix { position: absolute; left: 3px; top: 412px; z-index: 4; display: none;
  background: #fff; border: 1px solid #d1d5db; border-radius: 6px; padding: 1px 6px;
  font-size: 11px; font-weight: 600; color: #374151; white-space: nowrap;
  font-variant-numeric: tabular-nums; pointer-events: none;
  box-shadow: 0 1px 3px rgba(0,0,0,0.10); }
#minsvg, #dagsvg { display: block; }
.scroll-hint { color: #9ca3af; font-size: 12px; margin-top: 6px; }
.tooltip { position: fixed; z-index: 100; display: none; background: #1f2937; color: #f9fafb;
  padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.7;
  box-shadow: 0 6px 20px rgba(0,0,0,0.28); pointer-events: none; white-space: nowrap; }
.tooltip .tt-time { font-weight: 600; color: #fff; margin-bottom: 4px; }
.tooltip .tt-row { display: flex; align-items: center; gap: 7px; }
.tooltip .tt-sw, .tooltip .tt-sk { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }
.tooltip .tt-sw { background: #2563eb; }
.tooltip .tt-sk { background: #f59e0b; }
.tooltip .tt-row b { margin-left: auto; padding-left: 16px; font-variant-numeric: tabular-nums; }
.tooltip .tt-empty { color: #9ca3af; font-size: 12px; margin-top: 4px; }
'@

$CHART_JS = @'
(function(){
  var tt = document.getElementById('tt');
  function show(el, e){
    if(!tt) return;
    var w = el.getAttribute('data-w'), k = el.getAttribute('data-k');
    var extra = (w === '0' && k === '0') ? '<div class="tt-empty">该时段无输入</div>' : '';
    tt.innerHTML = '<div class="tt-time">'+el.getAttribute('data-label')+'</div>'
      + '<div class="tt-row"><span class="tt-sw"></span>上屏字数<b>'+w+'</b></div>'
      + '<div class="tt-row"><span class="tt-sk"></span>按键数<b>'+k+'</b></div>'
      + extra;
    tt.style.display = 'block';
    move(e);
  }
  function move(e){
    if(!tt) return;
    var x = e.clientX + 16, y = e.clientY + 16;
    var r = tt.getBoundingClientRect();
    if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - 16;
    if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - 16;
    tt.style.left = x + 'px';
    tt.style.top = y + 'px';
  }
  function hide(){ if(tt) tt.style.display = 'none'; }
  function isHit(t){ return t && t.getAttribute && t.getAttribute('class') === 'hit'; }
  document.addEventListener('mouseover', function(e){ if(isHit(e.target)) show(e.target, e); });
  document.addEventListener('mousemove', function(e){ if(tt && tt.style.display === 'block') move(e); });
  document.addEventListener('mouseout', function(e){ if(isHit(e.target)) hide(); });

  function pad(n){ return (n < 10 ? '0' : '') + n; }
  function fmtN(n){ return Number(n).toLocaleString(); }
  function niceMax(v){ v = +v; if (v <= 0) return 10;
    var e = Math.floor(Math.log(v) / Math.LN10); var base = Math.pow(10, e);
    var m = [1,2,5,10];
    for (var i = 0; i < m.length; i++){ if (v <= m[i] * base) return m[i] * base; }
    return 10 * base;
  }
  function keyDate(s){ return new Date(+s.substr(0,4), (+s.substr(4,2)) - 1, +s.substr(6,2), +s.substr(8,2), +s.substr(10,2)); }
  // ---- x-axis labels: times on the tick row; date under each day's 0:00 point ----
  function fLabel(d){ return pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  function fDate(d){ return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()); }
  function fTip(d){ return fDate(d) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  // ---- 按天聚合：横轴标每点起始日期（MM-DD），悬停显示该点覆盖的日期范围 ----
  function fLabelD(d){ return pad(d.getMonth()+1) + '-' + pad(d.getDate()); }
  function fTipD(d, bw){
    if (bw <= 1) return fDate(d);
    var e = new Date(d.getFullYear(), d.getMonth(), d.getDate() + (bw - 1));
    return fDate(d) + ' ~ ' + fDate(e) + '（' + bw + ' 天）';
  }

  // text width (canvas measure first, char-width estimate as fallback) for anti-overlap
  var _mc = null;
  function textW(s){
    try {
      if (_mc === null){
        var cv = document.createElement('canvas');
        _mc = (cv && cv.getContext) ? cv.getContext('2d') : false;
      }
      if (_mc){ _mc.font = '11px "Segoe UI", "Microsoft YaHei", sans-serif'; return _mc.measureText(s).width; }
    } catch (e) { _mc = false; }
    var w = 0;
    for (var wi = 0; wi < s.length; wi++){ w += s.charCodeAt(wi) > 0x2E80 ? 11 : 6.4; }
    return w;
  }
  // tick stride: smallest >= sMin that (ideally) repeats at the same clock time every day.
  // sMin comes from "label width + gap <= stride * point spacing", so labels never overlap.
  function pickStride(sMin, bm){
    if (sMin <= 1) return 1;
    var perDay = Math.ceil(1440 / bm);
    if (sMin >= perDay) return perDay;
    for (var s = sMin; s < perDay; s++){
      if (1440 % (s * bm) === 0) return s;
    }
    return sMin;
  }

  // 初始显示位置 = 最右侧（最近的数据）：所有可横向滚动的图表容器滚到最右
  function scrollChartsRight(){
    var scs = document.querySelectorAll('.scroll');
    for (var si = 0; si < scs.length; si++){
      scs[si].scrollLeft = scs[si].scrollWidth;
    }
  }

  // ---- bucketing aligned to the LOCAL calendar day, so every class width has a
  // data point exactly at 0:00 each day (the anchor for the date labels) ----
  var DAYMS = 86400000;
  function dayNumber(d){ return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAYMS); }
  function dayStartMs(dn){ var u = new Date(dn * DAYMS); return new Date(u.getUTCFullYear(), u.getUTCMonth(), u.getUTCDate()).getTime(); }

  // fixed date badge (under the left y-axis): shows the date of the leftmost visible
  // point whenever that date's 0:00 label is not on screen; hidden when 0:00 is visible.
  var MIN_N = 0, MIN_DX = 0, MIN_X0 = 78, MIN_PWD = 0, MIN_PTS = null, MIN_BIDX = null;
  function minX(j){ return MIN_X0 + (MIN_N <= 1 ? MIN_PWD * 0.5 : MIN_DX * j); }
  function updateDateFix(){
    var box = document.getElementById('dateFix');
    if (!box) return;
    var sc = document.getElementById('minScroll');
    if (!sc || !MIN_PTS || !MIN_PTS.length){ box.style.display = 'none'; return; }
    var sl = sc.scrollLeft, cw = sc.clientWidth;
    var j = Math.ceil((sl - MIN_X0) / (MIN_DX || 1));
    if (j < 0) j = 0;
    if (j > MIN_PTS.length - 1) j = MIN_PTS.length - 1;
    var d = MIN_PTS[j][0];
    var ds = fDate(d);
    var bi = MIN_BIDX ? MIN_BIDX[ds] : undefined;
    if (bi !== undefined){
      var cx = minX(bi) - sl;
      if (cx >= 46 && cx <= cw - 30){ box.style.display = 'none'; return; }
    }
    box.textContent = ds;
    box.style.display = 'block';
  }

  function renderMin(bm){
    var svg = document.getElementById('minsvg');
    if(!svg) return;
    var raw = window.MIN_RAW || [];
    if(!raw.length){ MIN_PTS = null; updateDateFix(); return; }
    var bms = bm * 60000, acc = {}, minB = Infinity, maxB = -Infinity, i;
    var perDay = Math.ceil(1440 / bm);   // buckets per day (last one may be shorter)
    for (i = 0; i < raw.length; i++){
      var d0 = keyDate(raw[i][0]);
      var dn = dayNumber(d0);
      var slot = Math.floor((d0.getTime() - dayStartMs(dn)) / bms);
      if (slot > perDay - 1) slot = perDay - 1;
      var b = dn * perDay + slot;
      if (!acc[b]) acc[b] = [0, 0];
      acc[b][0] += raw[i][1]; acc[b][1] += raw[i][2];
      if (b < minB) minB = b;
      if (b > maxB) maxB = b;
    }
    var pts = [];
    for (var b2 = minB; b2 <= maxB; b2++){
      var v = acc[b2] || [0, 0];
      var dn2 = Math.floor(b2 / perDay), slot2 = b2 - dn2 * perDay;
      pts.push([new Date(dayStartMs(dn2) + slot2 * bms), v[0], v[1]]);
    }
    var n = pts.length;
    var SP = 9, H = 430, ml = 78, mr = 78, mt = 58, mb = 64;
    // 宽度至少填满滚动容器可见区，保证左右固定纵轴贴着图表两侧
    var cw = (svg.parentNode && svg.parentNode.clientWidth) ? svg.parentNode.clientWidth : 0;
    var W = Math.max(n * SP + ml + mr, cw, 360);
    var pw = W - ml - mr, ph = H - mt - mb;
    var mw = 0, mk = 0;
    for (i = 0; i < n; i++){ if (pts[i][1] > mw) mw = pts[i][1]; if (pts[i][2] > mk) mk = pts[i][2]; }
    var wmax = niceMax(mw), kmax = niceMax(mk);
    function X(j){ return ml + (n <= 1 ? pw * 0.5 : pw * j / (n - 1)); }
    function Y(v, vm){ return mt + ph * (1 - v / vm); }
    var s = [];
    var yl = [], yr = [];
    for (var g = 0; g <= 5; g++){
      var fr = g / 5, y = mt + ph * (1 - fr);
      s.push('<line x1="'+ml+'" y1="'+y.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+y.toFixed(1)+'" stroke="#e5e7eb" stroke-width="1"/>');
      yl.push('<span class="yt yt-l" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(wmax*fr))+'</span>');
      yr.push('<span class="yt yt-r" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(kmax*fr))+'</span>');
    }
    yl.push('<span class="yt yt-l yt-title" style="top:'+(mt-11)+'px">字</span>');
    yr.push('<span class="yt yt-r yt-title" style="top:'+(mt-11)+'px">键</span>');
    // 纵轴刻度固定显示在滚动区左右两侧，不随图表横向滚动
    var boxL = document.getElementById('yaxL'), boxR = document.getElementById('yaxR');
    if (boxL) boxL.innerHTML = yl.join('');
    if (boxR) boxR.innerHTML = yr.join('');
    s.push('<line x1="'+ml+'" y1="'+(mt+ph)+'" x2="'+(ml+pw)+'" y2="'+(mt+ph)+'" stroke="#9ca3af" stroke-width="1.2"/>');
    // day separators + date labels: date drawn directly under each day's 0:00 point
    // (= the date of the data to the right of that point)
    var bidx = {};
    for (i = 0; i < n; i++){
      var dd = pts[i][0];
      if (dd.getHours() === 0 && dd.getMinutes() === 0){
        var x3 = X(i), ds3 = fDate(dd);
        s.push('<line x1="'+x3.toFixed(1)+'" y1="'+mt+'" x2="'+x3.toFixed(1)+'" y2="'+(mt+ph)+'" stroke="#d1d5db" stroke-width="1" stroke-dasharray="3 4"/>');
        s.push('<text x="'+x3.toFixed(1)+'" y="'+(mt+ph+42)+'" class="xl xd" text-anchor="middle">'+ds3+'</text>');
        bidx[ds3] = i;
      }
    }
    // time ticks: stride from measured label width vs point spacing -> never overlaps
    var dxp = (n > 1) ? pw / (n - 1) : pw;
    var labW = Math.max(textW('00:00'), textW('12:34'), textW('23:59'));
    var stride = pickStride(Math.max(1, Math.ceil((labW + 12) / dxp)), bm);
    if (stride > n) stride = n;
    for (i = 0; i < n; i += stride){
      s.push('<text x="'+X(i).toFixed(1)+'" y="'+(mt+ph+22)+'" class="xl" text-anchor="middle">'+fLabel(pts[i][0])+'</text>');
    }
    var wp = [], kp = [];
    for (i = 0; i < n; i++){ wp.push(X(i).toFixed(1) + ',' + Y(pts[i][1], wmax).toFixed(1)); kp.push(X(i).toFixed(1) + ',' + Y(pts[i][2], kmax).toFixed(1)); }
    s.push('<polyline points="'+kp.join(' ')+'" fill="none" stroke="#f59e0b" stroke-width="2" stroke-dasharray="6 4" stroke-linejoin="round"/>');
    s.push('<polyline points="'+wp.join(' ')+'" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>');
    for (i = 0; i < n; i++){
      var x = X(i);
      s.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="3.2" fill="#f59e0b"/>');
      s.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="3.2" fill="#2563eb"/>');
    }
    for (i = 0; i < n; i++){
      var x2 = X(i);
      var at = 'data-label="'+fTip(pts[i][0])+'" data-w="'+fmtN(pts[i][1])+'" data-k="'+fmtN(pts[i][2])+'"';
      s.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="14" '+at+'/>');
      s.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="14" '+at+'/>');
    }
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.style.width = W + 'px'; svg.style.height = H + 'px';
    svg.innerHTML = s.join('');
    var lbl = document.getElementById('minDensityLabel');
    if (lbl) lbl.textContent = ('每点 ' + bm + ' 分钟 · 共 ' + n + ' 点 · 默认显示最右侧（最近数据）');
    // state for the fixed bottom-left date badge while scrolling
    MIN_N = n; MIN_DX = dxp; MIN_X0 = ml; MIN_PWD = pw; MIN_PTS = pts; MIN_BIDX = bidx;
    // 每次重绘（含切换 1 分钟/…/1440 分钟组距）后都回到最右侧
    scrollChartsRight();
    updateDateFix();
  }

  // 可输入值的组距下拉列表：选项 1/5/10/15/30/60/120/360/720/1440，也允许输入 1–1440 之间的任意整数
  function applyBm(){
    var inp = document.getElementById('bmInput');
    if (!inp){ renderMin(1); return; }
    var hint = document.getElementById('bmHint');
    var v = parseInt(inp.value, 10);
    var msg = '';
    if (isNaN(v)){ v = 1; msg = '请输入 1–1440 之间的整数，已按 1 分钟绘图'; }
    else {
      var c = Math.min(1440, Math.max(1, v));
      if (c !== v){ msg = '输入超出 1–1440 范围，已按 ' + c + ' 分钟绘图'; }
      v = c;
    }
    inp.value = v;
    if (hint) hint.textContent = msg;
    renderMin(v);
  }

  // ---- 按天聚合：每 bw 天（1–365）一个点，按自然日序号整除对齐（数据不随日期漂移） ----
  function renderDayAgg(bw){
    var svg = document.getElementById('dagsvg');
    if(!svg) return;
    var raw = window.MIN_RAW || [];
    if(!raw.length) return;
    var acc = {}, minB = Infinity, maxB = -Infinity, i;
    for (i = 0; i < raw.length; i++){
      var dn = dayNumber(keyDate(raw[i][0]));
      var b = Math.floor(dn / bw);
      if (!acc[b]) acc[b] = [0, 0];
      acc[b][0] += raw[i][1]; acc[b][1] += raw[i][2];
      if (b < minB) minB = b;
      if (b > maxB) maxB = b;
    }
    var pts = [];
    for (var b2 = minB; b2 <= maxB; b2++){
      var v = acc[b2] || [0, 0];
      pts.push([new Date(dayStartMs(b2 * bw)), v[0], v[1]]);
    }
    var n = pts.length;
    var SP = 9, H = 430, ml = 78, mr = 78, mt = 58, mb = 64;
    // 宽度至少填满滚动容器可见区，保证左右固定纵轴贴着图表两侧
    var cw = (svg.parentNode && svg.parentNode.clientWidth) ? svg.parentNode.clientWidth : 0;
    var W = Math.max(n * SP + ml + mr, cw, 360);
    var pw = W - ml - mr, ph = H - mt - mb;
    var mw = 0, mk = 0;
    for (i = 0; i < n; i++){ if (pts[i][1] > mw) mw = pts[i][1]; if (pts[i][2] > mk) mk = pts[i][2]; }
    var wmax = niceMax(mw), kmax = niceMax(mk);
    function X(j){ return ml + (n <= 1 ? pw * 0.5 : pw * j / (n - 1)); }
    function Y(v, vm){ return mt + ph * (1 - v / vm); }
    var s = [];
    var yl = [], yr = [];
    for (var g = 0; g <= 5; g++){
      var fr = g / 5, y = mt + ph * (1 - fr);
      s.push('<line x1="'+ml+'" y1="'+y.toFixed(1)+'" x2="'+(ml+pw)+'" y2="'+y.toFixed(1)+'" stroke="#e5e7eb" stroke-width="1"/>');
      yl.push('<span class="yt yt-l" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(wmax*fr))+'</span>');
      yr.push('<span class="yt yt-r" style="top:'+(y+1).toFixed(1)+'px">'+fmtN(Math.round(kmax*fr))+'</span>');
    }
    yl.push('<span class="yt yt-l yt-title" style="top:'+(mt-11)+'px">字</span>');
    yr.push('<span class="yt yt-r yt-title" style="top:'+(mt-11)+'px">键</span>');
    // 纵轴刻度固定显示在滚动区左右两侧，不随图表横向滚动
    var boxL = document.getElementById('yaxL2'), boxR = document.getElementById('yaxR2');
    if (boxL) boxL.innerHTML = yl.join('');
    if (boxR) boxR.innerHTML = yr.join('');
    s.push('<line x1="'+ml+'" y1="'+(mt+ph)+'" x2="'+(ml+pw)+'" y2="'+(mt+ph)+'" stroke="#9ca3af" stroke-width="1.2"/>');
    // 横轴刻度 = 每点起始日期；步长按实际文本宽度自动稀疏，任何组距都不重叠
    var dxp = (n > 1) ? pw / (n - 1) : pw;
    var labW = Math.max(textW('01-02'), textW('12-31'));
    var stride = Math.max(1, Math.ceil((labW + 12) / (dxp || 1)));
    if (stride > n) stride = n;
    for (i = 0; i < n; i += stride){
      s.push('<text x="'+X(i).toFixed(1)+'" y="'+(mt+ph+22)+'" class="xl" text-anchor="middle">'+fLabelD(pts[i][0])+'</text>');
    }
    var wp = [], kp = [];
    for (i = 0; i < n; i++){ wp.push(X(i).toFixed(1) + ',' + Y(pts[i][1], wmax).toFixed(1)); kp.push(X(i).toFixed(1) + ',' + Y(pts[i][2], kmax).toFixed(1)); }
    s.push('<polyline points="'+kp.join(' ')+'" fill="none" stroke="#f59e0b" stroke-width="2" stroke-dasharray="6 4" stroke-linejoin="round"/>');
    s.push('<polyline points="'+wp.join(' ')+'" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>');
    for (i = 0; i < n; i++){
      var x = X(i);
      s.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="3.2" fill="#f59e0b"/>');
      s.push('<circle cx="'+x.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="3.2" fill="#2563eb"/>');
    }
    for (i = 0; i < n; i++){
      var x2 = X(i);
      var at = 'data-label="'+fTipD(pts[i][0], bw)+'" data-w="'+fmtN(pts[i][1])+'" data-k="'+fmtN(pts[i][2])+'"';
      s.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][1], wmax).toFixed(1)+'" r="14" '+at+'/>');
      s.push('<circle class="hit" cx="'+x2.toFixed(1)+'" cy="'+Y(pts[i][2], kmax).toFixed(1)+'" r="14" '+at+'/>');
    }
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.style.width = W + 'px'; svg.style.height = H + 'px';
    svg.innerHTML = s.join('');
    var lbl = document.getElementById('dDensityLabel');
    if (lbl) lbl.textContent = ('每点 ' + bw + ' 天 · 共 ' + n + ' 点 · 默认显示最右侧（最近数据）');
    scrollChartsRight();
  }

  // 按天聚合的组距输入：选项 1/2/3/7/14/30/90/180/365，也允许输入 1–365 之间的任意整数
  function applyDagg(){
    var inp = document.getElementById('dInput');
    if (!inp){ renderDayAgg(1); return; }
    var hint = document.getElementById('dHint');
    var v = parseInt(inp.value, 10);
    var msg = '';
    if (isNaN(v)){ v = 1; msg = '请输入 1–365 之间的整数，已按 1 天绘图'; }
    else {
      var c = Math.min(365, Math.max(1, v));
      if (c !== v){ msg = '输入超出 1–365 范围，已按 ' + c + ' 天绘图'; }
      v = c;
    }
    inp.value = v;
    if (hint) hint.textContent = msg;
    renderDayAgg(v);
  }

  function bindCtl(inpId, btnId, fn){
    var inp = document.getElementById(inpId);
    var btn = document.getElementById(btnId);
    if (btn) btn.addEventListener('click', fn);
    if (inp){
      inp.addEventListener('change', fn);
      inp.addEventListener('keydown', function(e){
        var k = e.key !== undefined ? e.key : e.keyCode;
        if (k === 'Enter' || k === 13){ e.preventDefault(); fn(); }
      });
    }
  }
  try {
    bindCtl('bmInput', 'bmApply', applyBm);
    bindCtl('dInput', 'dApply', applyDagg);
    // update the fixed bottom-left date badge on scroll / resize
    var sc0 = document.getElementById('minScroll');
    if (sc0) sc0.addEventListener('scroll', updateDateFix);
    window.addEventListener('resize', updateDateFix);
    // 切换 每日/按天聚合/按分钟聚合 标签页时重新绘制并定位到最右侧（面板显示后才量得到宽度）
    var radios = document.querySelectorAll('input[name=scale]');
    for (var ri = 0; ri < radios.length; ri++){
      (function(rd){
        rd.addEventListener('change', function(){
          setTimeout(function(){
            var smin = document.getElementById('s-min');
            var sdagg = document.getElementById('s-dagg');
            if (smin && smin.checked){ applyBm(); }
            else if (sdagg && sdagg.checked){ applyDagg(); }
            else { scrollChartsRight(); }
          }, 0);
        });
      })(radios[ri]);
    }
    applyBm();     // 按分钟聚合：默认 1 分钟
    applyDagg();   // 按天聚合：默认 1 天
    scrollChartsRight();
    window.addEventListener('load', function(){ applyBm(); applyDagg(); });
  } catch (err) {
    if (window.console) console.log('chart js error', err);
  }
})();
'@

function New-Card([string]$k, [string]$v, [string]$note) {
  $nh = ''
  if ($note) { $nh = ' <small>' + [System.Net.WebUtility]::HtmlEncode($note) + '</small>' }
  return '<div class="card"><div class="k">' + [System.Net.WebUtility]::HtmlEncode($k) + '</div><div class="v">' + $v + $nh + '</div></div>'
}

function New-Pane([string]$name, [string]$label, $items, [string]$extra) {
  if ($items.Count -gt 0) {
    $body = '<div class="panel">' + (Build-Svg $items) + '</div>'
  } else {
    $body = '<div class="panel"><div class="empty"><p><strong>暂无' + $label + '数据</strong></p><p>开始用小狼毫打字后自动记录；按天/按分钟聚合来自 <code>input_count_raw.txt</code>。</p></div></div>'
  }
  $note = '<div class="note">' + $label + ' 共 ' + $items.Count + ' 个数据点'
  if ($extra) { $note += ('；' + $extra) }
  $note += '</div>'
  return '<div class="pane pane-' + $name + '">' + $body + $note + '</div>'
}

function Synthesize-Demo {
  $rnd = New-Object System.Random 42
  $now = (Get-Date).Date.AddHours((Get-Date).Hour).AddMinutes((Get-Date).Minute)
  $minutes = @{}
  for ($back = 0; $back -lt 21; $back++) {
    $base = $now.AddDays(-$back).Date
    for ($h = 7; $h -lt 23; $h++) {
      $density = 0.62
      if ($h -lt 9 -or $h -gt 21) { $density = 0.30 }
      if ($rnd.NextDouble() -gt $density) { continue }
      for ($mi = 0; $mi -lt 60; $mi++) {
        if ($rnd.NextDouble() -gt 0.55) { continue }
        $dt = $base.AddHours($h).AddMinutes($mi)
        if ($dt -gt $now) { continue }
        $w = $rnd.Next(3, 47)
        $k = $w * $rnd.Next(2, 5) + $rnd.Next(0, 15)
        $key = $dt.ToString('yyyyMMddHHmm')
        if ($minutes.ContainsKey($key)) { $minutes[$key] = @(($minutes[$key][0] + $w), ($minutes[$key][1] + $k)) }
        else { $minutes[$key] = @($w, $k) }
      }
    }
  }
  return $minutes
}

try {
  if ($Demo) {
    $minutes = Synthesize-Demo
    $summary = @{ start = ((Get-Date).AddDays(-20).ToString('yyyy-MM-dd HH:mm:ss')); tw = 0; tk = 0; days = @{} }
    $summaryName = '(synthesized)'; $rawName = '(synthesized)'
  } else {
    $summary = Read-Summary $SummaryPath
    $minutes = Read-Raw $RawPath
    $summaryName = $SummaryPath; $rawName = $RawPath
    if ($minutes.Count -eq 0) { Write-Output ('NOTE: raw file not found or empty: ' + $RawPath) }
  }

  $rawDays = Aggregate $minutes 8
  # day map: summary (authoritative) wins over raw
  $dayMap = @{}
  foreach ($k in $rawDays.Keys) { $dayMap[$k] = $rawDays[$k] }
  foreach ($k in $summary.days.Keys) { $dayMap[$k] = $summary.days[$k] }

  $tw = $summary.tw; $tk = $summary.tk
  if ($tw -eq 0 -and $tk -eq 0) {
    $tw = ($dayMap.Values | ForEach-Object { $_[0] } | Measure-Object -Sum).Sum
    $tk = ($dayMap.Values | ForEach-Object { $_[1] } | Measure-Object -Sum).Sum
  }

  $dayItems = Make-Items $dayMap $MAX_DAY 'day'
  $dayaggItems = Make-Items $rawDays $MAX_DAY 'day'
  $minItems = Make-Items $minutes $MAX_MIN 'min'
  # 卡片汇总用「有数据」的观测值，避免被补 0 的空档拉低
  $dayObs = New-Object System.Collections.Generic.List[object]
  foreach ($k in $dayMap.Keys) {
    $dayObs.Add([pscustomobject]@{ W = $dayMap[$k][0]; K = $dayMap[$k][1]; Key = $k })
  }

  $cards = New-Object System.Collections.Generic.List[string]
  $cards.Add((New-Card '累计上屏' (Fmt $tw) '字'))
  $cards.Add((New-Card '累计按键' (Fmt $tk) '键'))
  $cards.Add((New-Card '记录天数' (Fmt $dayMap.Count) '天'))
  $todayKey = (Get-Date).ToString('yyyyMMdd')
  if ($dayMap.ContainsKey($todayKey)) {
    $cards.Add((New-Card '今日' ((Fmt $dayMap[$todayKey][0]) + ' <small>字 / ' + (Fmt $dayMap[$todayKey][1]) + ' 键</small>') ''))
  } else {
    $cards.Add((New-Card '今日' '<small>尚未记录</small>' ''))
  }
  if ($dayObs.Count -gt 0) {
    $peak = ($dayObs | Sort-Object W -Descending | Select-Object -First 1)
    $avg = ($dayObs | Measure-Object -Property W -Average).Average
    $peakKey = $peak.Key
    $peakLab = '{0}-{1}' -f $peakKey.Substring(4,2), $peakKey.Substring(6,2)
    $cards.Add((New-Card '单日最高' (Fmt $peak.W) ('字 · ' + $peakLab)))
    $cards.Add((New-Card '日均上屏' (Fmt $avg) '字'))
  } else {
    $cards.Add((New-Card '单日最高' '<small>—</small>' ''))
    $cards.Add((New-Card '日均上屏' '<small>—</small>' ''))
  }
  $cards.Add((New-Card '分钟级记录' (Fmt $minutes.Count) '条'))

  $parts = New-Object System.Collections.Generic.List[string]
  $parts.Add('<!DOCTYPE html>')
  $parts.Add('<html lang="zh-CN">')
  $parts.Add('<head>')
  $parts.Add('<meta charset="utf-8">')
  $parts.Add('<meta name="viewport" content="width=device-width, initial-scale=1">')
  $parts.Add('<title>小狼毫 · 输入统计</title>')
  $parts.Add('<style>' + $CSS + '</style>')
  $parts.Add('</head>')
  $parts.Add('<body><div class="wrap">')
  $parts.Add('<h1>小狼毫 · 输入统计折线图（每日 / 按天聚合 / 按分钟聚合）</h1>')
  if ($Demo) {
    $parts.Add('<div class="banner">演示图：为合成的示例数据（非真实统计）。真实图表见 <code>input_count_chart.html</code>。</div>')
  }
  $parts.Add('<div class="sub">数据源：<code>' + [System.Net.WebUtility]::HtmlEncode((Split-Path -Leaf $summaryName)) + '</code>（日汇总）+ <code>' + [System.Net.WebUtility]::HtmlEncode((Split-Path -Leaf $rawName)) + '</code>（分钟级原始） — 由 Rime-input-count 插件自动记录。悬停数据点看具体数值。</div>')
  $parts.Add('<div class="cards">' + ($cards -join '') + '</div>')

  $parts.Add('<div class="tabs">')
  $parts.Add('<input type="radio" name="scale" id="s-day" checked>')
  $parts.Add('<input type="radio" name="scale" id="s-dagg">')
  $parts.Add('<input type="radio" name="scale" id="s-min">')
  $parts.Add('<div class="tabbar"><label for="s-day">每日</label><label for="s-dagg">按天聚合</label><label for="s-min">按分钟聚合</label></div>')
  $parts.Add((New-Pane 'day' '每日' $dayItems '以日汇总为准，与 ii 弹窗一致'))
  # 按天聚合面板：可滚动 + 组距可输入（JS 渲染；无 JS 时按 1 天静态 SVG 兜底）
  $dbody = New-Object System.Collections.Generic.List[string]
  $dbody.Add('<div class="minctl">')
  $dbody.Add('<span class="minctl-label">组距（每点覆盖天数，1–365）：</span>')
  $dbody.Add('<input id="dInput" class="bm-input" type="number" min="1" max="365" step="1" value="1" list="dOpts" placeholder="1-365">')
  $dbody.Add('<datalist id="dOpts">')
  foreach ($dk in @(@(1,'1 天'), @(2,'2 天'), @(3,'3 天'), @(7,'7 天（一周）'), @(14,'14 天'), @(30,'30 天（约一个月）'), @(90,'90 天（约一季）'), @(180,'180 天（半年）'), @(365,'365 天（一年）'))) {
    $dbody.Add(('<option value="{0}">{1}</option>' -f $dk[0], $dk[1]))
  }
  $dbody.Add('</datalist>')
  $dbody.Add('<button type="button" id="dApply" class="bkt">绘图</button>')
  $dbody.Add('<span id="dHint" class="minctl-hint"></span>')
  $dbody.Add('<span id="dDensityLabel" class="minctl-label"></span>')
  $dbody.Add('</div>')
  $dbody.Add('<div class="minwrap">')
  $dbody.Add('<div class="scroll" id="dScroll">')
  $daggSvg = Build-Svg $dayaggItems
  $daggSvg = $daggSvg.Replace('<svg class="chart"', '<svg id="dagsvg" class="chart"')
  $dbody.Add($daggSvg)
  $dbody.Add('</div>')
  $dbody.Add('<div class="yax yax-l" id="yaxL2"></div>')
  $dbody.Add('<div class="yax yax-r" id="yaxR2"></div>')
  $dbody.Add('</div>')
  $dbody.Add('<div class="scroll-hint">默认每点 1 天并定位至最近的数据；向左滚动查看更早的数据。左右两侧纵轴刻度始终固定显示（左轴=字、右轴=键）；横轴标出每点的起始日期，悬停数据点看该组覆盖的日期范围与数值。</div>')
  $dbody.Add('<div class="note">由 <code>input_count_raw.txt</code> 按天聚合；在上方下拉框选 1/2/3/7/14/30/90/180/365，或直接输入 1–365 的任意天数后回车/点「绘图」。</div>')
  $parts.Add('<div class="pane pane-dagg">' + ($dbody -join '') + '</div>')
  # 按分钟聚合面板：可滚动 + 组距可输入（JS 渲染；无 JS 时静态 SVG 兜底）
  $minRawArr = New-Object System.Collections.Generic.List[string]
  foreach ($mk in ($minutes.Keys | Sort-Object)) {
    $minRawArr.Add(('[{0},{1},{2}]' -f ('"' + $mk + '"'), $minutes[$mk][0], $minutes[$mk][1]))
  }
  $minRawJson = '[' + ($minRawArr -join ',') + ']'
  $mbody = New-Object System.Collections.Generic.List[string]
  $mbody.Add('<div class="minctl">')
  $mbody.Add('<span class="minctl-label">组距（每点覆盖分钟数，1–1440）：</span>')
  $mbody.Add('<input id="bmInput" class="bm-input" type="number" min="1" max="1440" step="1" value="1" list="bmOpts" placeholder="1-1440">')
  $mbody.Add('<datalist id="bmOpts">')
  foreach ($bk in @(@(1,'1 分钟'), @(5,'5 分钟'), @(10,'10 分钟'), @(15,'15 分钟'), @(30,'30 分钟'), @(60,'60 分钟（1 小时）'), @(120,'120 分钟（2 小时）'), @(360,'360 分钟（6 小时）'), @(720,'720 分钟（12 小时）'), @(1440,'1440 分钟（1 天）'))) {
    $mbody.Add(('<option value="{0}">{1}</option>' -f $bk[0], $bk[1]))
  }
  $mbody.Add('</datalist>')
  $mbody.Add('<button type="button" id="bmApply" class="bkt">绘图</button>')
  $mbody.Add('<span id="bmHint" class="minctl-hint"></span>')
  $mbody.Add('<span id="minDensityLabel" class="minctl-label"></span>')
  $mbody.Add('</div>')
  $mbody.Add('<div class="minwrap">')
  $mbody.Add('<div class="scroll" id="minScroll">')
  $fallbackSvg = Build-Svg $minItems -withDates
  $fallbackSvg = $fallbackSvg.Replace('<svg class="chart"', '<svg id="minsvg" class="chart"')
  $mbody.Add($fallbackSvg)
  $mbody.Add('</div>')
  $mbody.Add('<div class="yax yax-l" id="yaxL"></div>')
  $mbody.Add('<div class="yax yax-r" id="yaxR"></div>')
  $mbody.Add('<div class="datefix" id="dateFix"></div>')
  $mbody.Add('</div>')
  $mbody.Add('<div class="scroll-hint">默认按 1 分钟绘图并显示最右侧（最近的数据）；向左拖动/滚动查看更早的数据；左右两侧纵轴始终固定显示，不随滚动移动。日期标注在每天 0:00 数据点的正下方（覆盖该点以右当天的数据）；滚动到看不到 0:00 时，当前日期固定显示在左下角（左侧纵轴下方）。</div>')
  $mbody.Add('<div class="note">由 <code>input_count_raw.txt</code> 聚合；在上方下拉框选 1/5/10/15/30/60/120/360/720/1440，或直接输入 1–1440 的任意分钟数后回车/点「绘图」。</div>')
  $parts.Add('<div class="pane pane-min">' + ($mbody -join '') + '</div>')
  $parts.Add('</div>')

  if ($dayObs.Count -gt 0) {
    $parts.Add('<details>')
    $parts.Add(('<summary>每日明细数据（{0} 天）</summary>' -f $dayObs.Count))
    $parts.Add('<table>')
    $parts.Add('<tr><th>日期</th><th>上屏字数</th><th>按键数</th></tr>')
    foreach ($d in ($dayObs | Sort-Object Key -Descending)) {
      $tl = '{0}-{1}-{2}' -f $d.Key.Substring(0,4), $d.Key.Substring(4,2), $d.Key.Substring(6,2)
      $parts.Add(('<tr><td>{0}</td><td>{1}</td><td>{2}</td></tr>' -f $tl, (Fmt $d.W), (Fmt $d.K)))
    }
    $parts.Add('</table>')
    $parts.Add('</details>')
  }

  $foot = @()
  $foot += ('生成时间：' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))
  if ($summary.start) { $foot += ('统计起始：' + [System.Net.WebUtility]::HtmlEncode($summary.start)) }
  $foot += ('日汇总文件：' + [System.Net.WebUtility]::HtmlEncode($summaryName))
  $foot += ('分钟级原始文件：' + [System.Net.WebUtility]::HtmlEncode($rawName))
  $foot += '口径：每日=日汇总（权威，等于 ii 弹窗）；按天聚合/按分钟聚合=分钟级原始，只含开始记录分钟级之后的输入。'
  $foot += '刷新方式：双击 <code>查看每日统计.bat</code>。'
  $parts.Add('<div class="foot">' + ($foot -join '<br>') + '</div>')
  $parts.Add('<div id="tt" class="tooltip"></div>')
  $parts.Add('<script>window.MIN_RAW=' + $minRawJson + ';</script>')
  $parts.Add('<script>' + $CHART_JS + '</script>')
  $parts.Add('</div></body></html>')

  $doc = $parts -join "`n"
  $outFull = [System.IO.Path]::GetFullPath($OutputPath)
  $outDir = Split-Path -Parent $outFull
  if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
  [System.IO.File]::WriteAllText($outFull, $doc, [System.Text.UTF8Encoding]::new($false))

  $size = (Get-Item -LiteralPath $OutputPath).Length
  Write-Output ('OK: ' + $minutes.Count + ' minute bucket(s) -> ' + $OutputPath)
  Write-Output ('OK: chart written: ' + $OutputPath + ' (' + $size + ' bytes)')
  if ($size -lt 500) { Write-Output 'ERROR: chart file too small'; exit 1 }
  exit 0
} catch {
  Write-Output ('ERROR: ' + $_.Exception.Message)
  exit 1
}
