// 冒烟/回归测试：隐藏阈值输入框 + 指标切换按钮 + 滚轮步长、按显示数据的平均值、
// 面板移动/缩放（含手柄斜线方向与滚动条避让）、重复渲染短路、
// 横轴日期标注防重叠、星期底色（日期->星期映射 + 半透明色带）、频数分布直方图
// 用法：先 python plot_input_count.py 生成 input_count_chart.html，再 node _smoke2.js
// （PowerShell 版产物同样可测：node _smoke2.js <生成的 html>）
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(process.argv[2] || 'input_count_chart.html', 'utf8');
const m = html.match(/<script>\s*\(function\(\)\{[\s\S]*?\}\)\(\);\s*<\/script>/);
const js = m[0].replace(/^<script>/, '').replace(/<\/script>$/, '');
const rawM = html.match(/window\.MIN_RAW=(\[[\s\S]*?\]);/);
const MIN_RAW = JSON.parse(rawM[1]);

function el(id) {
  const listeners = {};
  const e = {
    id, innerHTML: '', textContent: '', value: '1', checked: false, className: '',
    style: {}, attrs: {}, listeners, children: [],
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    dispatch(type, ev) { (listeners[type] || []).forEach(fn => fn(ev || { preventDefault() {} })); },
    appendChild(n) { this.children.push(n); return n; },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 700, top: 24, width: 560, height: 400 }; },
    get firstChild() { return this.innerHTML ? {} : null; },
    clientWidth: 800, scrollWidth: 2000, scrollLeft: 0, parentNode: { clientWidth: 800 },
  };
  return e;
}
const els = {};
const ids = ['tt','minsvg','dagsvg','yaxL','yaxR','yaxL2','yaxR2','minDensityLabel','dDensityLabel',
  'minScroll','dScroll','dateFix','bmInput','bmApply','dInput','dApply','mAvgChk','minThresh','minThHint',
  'dAvgChk','dThresh','dThHint','minThMetric','dThMetric','klPanel','klPanelBody','klPanelTitle',
  'klPanelClose','klPanelHd','klPanelRz','s-min','s-dagg','mWdChk','dWdChk','hsvg','hBin','hApply',
  'ttl','setPanel','setMask','setClose','cfgBw','cfgBwAuto','cfgThr','cfgThrAuto','cfgHist',
  'cfgHistAuto','cfgYHalf','cfgYStep'];
ids.forEach(i => { els[i] = el(i); });
els.minThresh.value = '0';   // 模拟 HTML 里的默认值（= 原「隐藏0值」默认勾选）
els.dThresh.value = '0';
els.mAvgChk.checked = true;  // 平均线打开，便于校验平均值
els.cfgBw.value = '10'; els.cfgHist.value = '10'; els.cfgThr.value = '10';
els.cfgThrAuto.checked = true; els.cfgThr.disabled = true;   // 设置面板默认：只有阈值是「自适应」
els.cfgYHalf.checked = true;
els.minThMetric.attrs['data-metric'] = 'words';   // 模拟 HTML 里的默认指标按钮
els.dThMetric.attrs['data-metric'] = 'words';
els.minThMetric.textContent = '上屏字数';
els.dThMetric.textContent = '上屏字数';

const docListeners = {};
const sandbox = {
  window: { MIN_RAW, addEventListener() {}, innerWidth: 1200, innerHeight: 800, console },
  document: {
    getElementById: id => els[id] || null,
    addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
    querySelectorAll: () => [],
    createElement: () => el('tmp'),
    createTextNode: t => ({ text: t }),
    body: el('body'),
    activeElement: null,
  },
  console,
  setTimeout: fn => fn(),
};
sandbox.window.document = sandbox.document;
vm.createContext(sandbox);
vm.runInContext(js, sandbox);
// 平均线/星期底色是「两个标签页共用一个开关」，勾选要触发 change 才会写进页面状态
els.mAvgChk.checked = true; els.mAvgChk.dispatch('change');

function check(name, cond) {
  console.log((cond ? 'PASS' : 'FAIL') + '  ' + name);
  if (!cond) process.exitCode = 1;
}

// ---- 期望值推演（与页面 JS 同一套分组逻辑：bw=1、按本地自然日对齐）----
function dayNumber(d) { return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86400000); }
function dayStartMs(dn) { const u = new Date(dn * 86400000); return new Date(u.getUTCFullYear(), u.getUTCMonth(), u.getUTCDate()).getTime(); }
function keyDate(s) { return new Date(+s.substr(0, 4), +s.substr(4, 2) - 1, +s.substr(6, 2), +s.substr(8, 2), +s.substr(10, 2)); }
function rawPts() {
  const acc = {}; let minB = Infinity, maxB = -Infinity;
  for (const r of MIN_RAW) {
    const d0 = keyDate(r[0]); const dn = dayNumber(d0);
    const slot = Math.floor((d0.getTime() - dayStartMs(dn)) / 60000);
    const b = dn * 1440 + slot;
    if (!acc[b]) acc[b] = [0, 0];
    acc[b][0] += r[1]; acc[b][1] += r[2];
    if (b < minB) minB = b; if (b > maxB) maxB = b;
  }
  const pts = [];
  for (let b = minB; b <= maxB; b++) { const v = acc[b] || [0, 0]; pts.push([v[0], v[1]]); }
  return pts;
}
// midx：1=按上屏字数筛、2=按按键次数筛（与页面「指标按钮」一致）
function expectedPts(th, midx) {
  return rawPts().filter(p => (th <= -1) || (p[midx - 1] > th));
}
// 滚轮一格的期望阈值（默认「自适应」）：步长=「当前最小显示值 m」与「所有数值中离它最近的
// 数值」的差+1，向上至少隐藏最小显示值那组、向下至少显示最大隐藏值那组
function expWheel(th, up, midx) {
  const vals = rawPts().map(p => p[midx - 1]).sort((a, b) => a - b);
  if (!vals.length) return up ? th + 1 : th - 1;
  let j = 0; while (j < vals.length && vals[j] <= th) j++;
  const mv = j < vals.length ? vals[j] : null, hv = j > 0 ? vals[j - 1] : null;
  if (mv === null) return up ? th + 1 : hv - 1;
  let k = j; while (k < vals.length && vals[k] === mv) k++;
  let gap = Math.min(hv === null ? Infinity : mv - hv, k < vals.length ? vals[k] - mv : Infinity);
  if (!isFinite(gap)) gap = 0;
  return up ? Math.max(th + gap + 1, mv) : Math.min(th - gap - 1, hv === null ? th - 1 : hv - 1);
}
function shownPairs(svg) {
  // 命中圆分成「字」「键」两个 <g>（纵轴缩放动画用），每个点在两组里各有一个；
  // 只取「字」这一组 —— 每点恰好一条。
  const g = svg.match(/<g id="gw-[a-z]+">([\s\S]*?)<\/g>/);
  const src = g ? g[1] : '';
  const out = [];
  const re = /data-w="([^"]*)" data-k="([^"]*)"/g;
  let mm;
  while ((mm = re.exec(src)) !== null) out.push([mm[1], mm[2]]);
  return out;
}
function renderTh(v) {
  els.minThresh.value = '' + v;
  els.minThresh.dispatch('input');
}
function wheelMin(up) {
  const prev = sandbox.document.activeElement;
  sandbox.document.activeElement = els.minThresh;
  els.minThresh.dispatch('wheel', { deltaY: up ? -100 : 100, preventDefault() {} });
  sandbox.document.activeElement = prev;
  return parseInt(els.minThresh.value, 10);
}
function pair(p) {
  return [Number(p[0]).toLocaleString(), Number(p[1]).toLocaleString()];
}
function avgFromAxis() {
  const mm = els.yaxL.innerHTML.match(/class="yt yt-l avgv"[^>]*>([^<]*)</);
  return mm ? parseFloat(mm[1].replace(/,/g, '')) : NaN;
}

// 1. 默认阈值 0 + 默认指标「上屏字数」：不绘制字数 <= 0 的点（0/0 点必隐藏）
let svgMin = els.minsvg.innerHTML;
check('min 图正常出图', svgMin.includes('<polyline'));
check('阈值默认 0：无 0/0 点', !(svgMin.includes('data-w="0" data-k="0"')));
check('阈值默认 0（上屏字数）：显示点集合与期望一致',
  JSON.stringify(shownPairs(svgMin)) ===
  JSON.stringify(expectedPts(0, 1).map(pair)));

// 2. 阈值 -1：不隐藏任何点
renderTh(-1);
svgMin = els.minsvg.innerHTML;
check('阈值 -1：0/0 点回来', svgMin.includes('data-w="0" data-k="0"'));
check('阈值 -1：显示点集合与期望一致',
  JSON.stringify(shownPairs(svgMin)) ===
  JSON.stringify(expectedPts(-1, 1).map(pair)));

// 3. 阈值 5 + 上屏字数：只显示字数高于 5 的点
renderTh(5);
svgMin = els.minsvg.innerHTML;
const exp5 = expectedPts(5, 1);
check('阈值 5（上屏字数）：显示点集合与期望一致',
  JSON.stringify(shownPairs(svgMin)) === JSON.stringify(exp5.map(pair)));
check('阈值 5（上屏字数）：确实只剩字数高于 5 的点', exp5.every(p => p[0] > 5) && exp5.length > 0);

// 4. 平均值 = 当前显示数据的平均值（含显示中的 0 值点）
renderTh(-1);
let expAvgW = expectedPts(-1, 1).reduce((s, p) => s + p[0], 0) / expectedPts(-1, 1).length;
check('平均值=显示数据平均（阈值 -1，含 0 值点）', Math.abs(avgFromAxis() - expAvgW) < 0.1);
renderTh(0);
expAvgW = expectedPts(0, 1).reduce((s, p) => s + p[0], 0) / expectedPts(0, 1).length;
check('平均值=显示数据平均（阈值 0）', Math.abs(avgFromAxis() - expAvgW) < 0.1);

// 5. 输入框规整：-5 -> -1；2.5 -> 2；非数字 -> 0
els.minThresh.value = '-5'; els.minThresh.dispatch('change');
check('阈值越界收敛到 -1', els.minThresh.value === '-1' && els.minThHint.textContent.length > 0);
els.minThresh.value = '2.5'; els.minThresh.dispatch('change');
check('非整数收敛为整数', els.minThresh.value === '2');
els.minThresh.value = 'abc'; els.minThresh.dispatch('change');
check('非法输入回到默认 0', els.minThresh.value === '0');

// 6. 指标切换按钮：上屏字数 <-> 按键次数，筛选按所选指标
els.minThMetric.dispatch('click');
check('指标按钮点击后切到「按键次数」',
  els.minThMetric.textContent === '按键次数' && els.minThMetric.attrs['data-metric'] === 'keys');
renderTh(5);
svgMin = els.minsvg.innerHTML;
const exp5k = expectedPts(5, 2);
check('阈值 5（按键次数）：显示点集合与期望一致',
  JSON.stringify(shownPairs(svgMin)) === JSON.stringify(exp5k.map(pair)));
check('按键次数筛选：确实只剩键数高于 5 的点', exp5k.every(p => p[1] > 5) && exp5k.length > 0);
els.minThMetric.dispatch('click');
check('指标按钮再点切回「上屏字数」',
  els.minThMetric.textContent === '上屏字数' && els.minThMetric.attrs['data-metric'] === 'words');

// 6b. 「隐藏 m 及以下的 …」的 m 按指标分别记住：切指标互不覆盖，切回来原样恢复
els.minThMetric.dispatch('click');   // -> 按键次数（此时它自己的 m 还是默认 0）
els.minThresh.value = '0'; els.minThresh.dispatch('change');
els.minThMetric.dispatch('click');   // -> 上屏字数
renderTh(666);
els.minThMetric.dispatch('click');   // -> 按键次数
check('切到按键次数：m 用它自己的值（默认 0），不是上屏字数的 666', els.minThresh.value === '0');
renderTh(8888);
els.minThMetric.dispatch('click');   // -> 上屏字数
check('切回上屏字数：m 恢复为 666', els.minThresh.value === '666');
els.minThMetric.dispatch('click');   // -> 按键次数
check('再切到按键次数：m 恢复为 8888', els.minThresh.value === '8888');
els.minThMetric.dispatch('click');   // 回到上屏字数（m=666）
els.minThMetric.dispatch('click');   // 切到按键次数
renderTh(0);                          // 按键次数阈值归 0
els.minThMetric.dispatch('click');   // 回到上屏字数
renderTh(0);                          // 上屏字数阈值归 0

// 7. 「隐藏 m 及以下」的滚轮：默认自适应，滚一次至少隐藏/显示一组数据（步长=相邻数值差+1）
renderTh(0);
let thNow = 0, nNow = expectedPts(0, 1).length;
const th1 = wheelMin(true);
check('滚轮向上：阈值按跨度变大（不是 ±1 的箭头）', th1 > thNow);
check('滚轮向上：新阈值=文档口径（相邻数值差+1）', th1 === expWheel(0, true, 1));
check('滚轮向上：至少隐藏一个数据', expectedPts(th1, 1).length < nNow);
const th2 = wheelMin(true);
check('滚轮连续向上：每格都至少再隐藏一个数据', expectedPts(th2, 1).length < expectedPts(th1, 1).length);
const th3 = wheelMin(false);
check('滚轮向下：新阈值=文档口径（相邻数值差+1）', th3 === expWheel(th2, false, 1));
check('滚轮向下：至少显示一个数据', expectedPts(th3, 1).length > expectedPts(th2, 1).length);
// 换指标后步长随该指标数值变化
els.minThMetric.dispatch('click');                 // 切到按键次数（m 换成该指标自己记着的值）
const startK = parseInt(els.minThresh.value, 10);
const thK = wheelMin(true);
check('切到按键次数后滚轮步长按键数数值计算', thK === expWheel(startK, true, 2));
els.minThMetric.dispatch('click');                 // 切回上屏字数
// 未点进输入框时滚轮不改数值（与原生一致）
sandbox.document.activeElement = null;
const thBefore = els.minThresh.value;
els.minThresh.dispatch('wheel', { deltaY: -100, preventDefault() {} });
check('未点进输入框时滚轮不改数值', els.minThresh.value === thBefore);
renderTh(0);

// 8. 重复渲染短路：参数没变直接跳过重绘
els.dagsvg.innerHTML = 'SENTINEL';
els.dApply.dispatch('click');
check('参数未变时重绘被短路', els.dagsvg.innerHTML === 'SENTINEL');
els.dInput.value = '7'; els.dApply.dispatch('click');
check('参数变化时正常重绘', els.dagsvg.innerHTML.includes('<polyline'));

// 9. 面板：拖顶部移动
const mdown = (target, x, y) => ({ target, clientX: x, clientY: y, preventDefault() {} });
els.klPanelHd.dispatch('mousedown', mdown(els.klPanelHd, 800, 100));
(docListeners['mousemove'] || []).forEach(fn => fn({ clientX: 700, clientY: 160 }));
check('拖顶部移动面板（left/top 跟随）',
  els.klPanel.style.left === '600px' && els.klPanel.style.top === '84px');
check('移动后 right 改为 auto', els.klPanel.style.right === 'auto');

// 10. 面板：拖右下角调长宽
els.klPanelRz.dispatch('mousedown', mdown(els.klPanelRz, 1260, 424));
(docListeners['mousemove'] || []).forEach(fn => fn({ clientX: 1360, clientY: 524 }));
check('拖右下角调整长宽',
  els.klPanel.style.width === '660px' && els.klPanel.style.height === '500px');
check('调高后解除默认屏高上限', els.klPanel.style.maxHeight === 'none');

// 11. 单击/关闭/Esc（原有功能不回归）
const hits = [...svgMin.matchAll(/<circle class="hit"[^>]*>/g)];
check('min 图存在命中区', hits.length > 0);
const hitEl = el('hit');
const tag = hits[0][0];
for (const mm of tag.matchAll(/([a-z0-9-]+)="([^"]*)"/g)) hitEl.attrs[mm[1]] = mm[2];
hitEl.attrs['class'] = 'hit';
(docListeners['click'] || []).forEach(fn => fn({ target: hitEl }));
check('单击后面板显示', els.klPanel.className === 'klpanel show');
check('面板标题=数据点时间', els.klPanelTitle.textContent.length > 0);
check('关闭按钮已绑定', (els.klPanelClose.listeners['click'] || []).length === 1);
els.klPanelClose.dispatch('click');
check('关闭后面板隐藏', els.klPanel.className === 'klpanel');
els.klPanel.className = 'klpanel show';
(docListeners['keydown'] || []).forEach(fn => fn({ key: 'Escape' }));
check('Esc 关闭面板', els.klPanel.className === 'klpanel');

// 12. 静态 HTML/CSS 结构（控件语句/按钮/手柄样式、旧勾选框已移除）
check('HTML 含隐藏阈值输入框（min="-1"）', html.includes('id="minThresh"') && html.includes('id="dThresh"')
  && /id="minThresh"[^>]*min="-1"/.test(html) && /id="dThresh"[^>]*min="-1"/.test(html));
check('HTML 短语为「隐藏[…]及以下的[指标]」', html.includes('及以下的') && !html.includes('及以下的数值'));
check('HTML 含指标切换按钮（默认上屏字数）', html.includes('id="minThMetric"') && html.includes('id="dThMetric"')
  && html.includes('data-metric="words"') && html.includes('>上屏字数</button>'));
check('HTML 含面板移动/缩放挂点', html.includes('id="klPanelHd"') && html.includes('id="klPanelRz"'));
check('HTML 已无旧的隐藏0值勾选框', !html.includes('DropZero'));
check('手柄斜线方向已顺时针转 90°（135deg）',
  html.includes('linear-gradient(135deg') && !html.includes('linear-gradient(45deg'));
check('滚动条整体位于手柄上方（正文底部留白 18px）',
  /\.klpanel-bd \{ padding: 12px 14px; margin-bottom: 18px;/.test(html));
check('指标按钮样式存在', html.includes('.thr .thr-btn'));

// 14. 日期标注防重叠：任何组距下相邻日期文字都不重叠（组距很大时按距离稀疏，放不下就不标）
function dateLabelXs() {
  return [...(els.minsvg.innerHTML.matchAll(/<text x="([\d.]+)"[^>]*class="xl xd"[^>]*>([^<]*)</g))]
    .map(m => [parseFloat(m[1]), m[2]]);
}
function noOverlap(list) {
  for (let i = 1; i < list.length; i++) {
    // 日期是纯 ASCII：页面 textW 的兜底估算是 6.4px/字，这里再加 8px 最小间隙
    const wPrev = 6.4 * list[i - 1][1].length + 8;
    if (list[i][0] - list[i - 1][0] < wPrev) return false;
  }
  return true;
}
els.bmInput.value = '1440'; els.bmApply.dispatch('click');
let dls = dateLabelXs();
check('组距 1440（每点都是 0:00）日期标注不重叠', dls.length > 1 && noOverlap(dls));
check('组距 1440：日期确实被稀疏（不是每天一个）', dls.length < 28);
els.bmInput.value = '1'; els.bmApply.dispatch('click');
dls = dateLabelXs();
check('组距 1（每天 0:00）日期标注不重叠', dls.length > 1 && noOverlap(dls));

// 15. 星期底色：两个标签页共用一个开关（勾一个两个都勾），周日为每星期第一天，配色红橙黄绿青蓝紫
check('HTML 两个面板都有「星期底色」勾选框',
  html.includes('id="mWdChk"') && html.includes('id="dWdChk"'));
const wdM = html.match(/window\.WEEKDAY=(\{[\s\S]*?\});/);
check('HTML 内嵌日期->星期映射（Python calendar 计算）', !!wdM);
const WD = JSON.parse(wdM[1]);
const wdKeys = Object.keys(WD);
check('映射覆盖数据首尾之间的每一天', wdKeys.length >= 1 && Object.values(WD).every(v => v >= 0 && v <= 6));
check('映射正确：0=周日 … 6=周六（与本地日历一致）', wdKeys.every(k => {
  const d = new Date(+k.substr(0, 4), +k.substr(4, 2) - 1, +k.substr(6, 2));
  return WD[k] === d.getDay();
}));
// 现行配色（页面实际使用的 WD_FILL）：周日→周六 = 金 银 红 紫 蓝 绿 黑。
// 注：README 里「红橙黄绿青蓝紫」是旧说法；产物里一直是下面这 7 个颜色，本测试按产物校验。
const FILLS = ['rgba(255,215,0,0.10)', 'rgba(192,192,192,0.10)', 'rgba(188,39,49,0.10)',
  'rgba(128,0,128,0.10)', 'rgba(65,105,225,0.10)', 'rgba(46,204,113,0.10)', 'rgba(0,0,0,0.10)'];
check('配色表顺序为 金银红紫蓝绿黑（7 色）',
  /rgba\(255,215,0[\s\S]*rgba\(192,192,192[\s\S]*rgba\(188,39,49[\s\S]*rgba\(128,0,128[\s\S]*rgba\(65,105,225[\s\S]*rgba\(46,204,113[\s\S]*rgba\(0,0,0/.test(js));

// 默认勾选：开页就有底色
els.bmInput.value = '1'; els.bmApply.dispatch('click');
check('星期底色默认勾选时开页即上色', els.minsvg.innerHTML.includes('fill="rgba('));
els.mWdChk.checked = false; els.mWdChk.dispatch('change');
els.bmInput.value = '1'; els.bmApply.dispatch('click');
check('取消勾选后不画底色', !els.minsvg.innerHTML.includes('fill="rgba('));
els.mWdChk.checked = true; els.mWdChk.dispatch('change');

// 勾一个 -> 两个都勾（无需刷新另一个标签页的图，切页时会自行重绘）
els.mWdChk.checked = true; els.mWdChk.dispatch('change');
check('勾选任一「星期底色」两个标签页同步勾选',
  els.mWdChk.checked === true && els.dWdChk.checked === true);
els.bmInput.value = '1'; els.bmApply.dispatch('click');
const bands = [...els.minsvg.innerHTML.matchAll(/<rect [^>]*fill="rgba\([^)]*\)"/g)].length;
const bandDays = new Set(MIN_RAW.map(r => r[0].substr(0, 8))).size;
check('勾选后按自然日染色（按分钟聚合：一天一条底色带）', bands === bandDays);
check('底色为半透明 rgba（alpha < 1）',
  [...els.minsvg.innerHTML.matchAll(/fill="rgba\([^)]*,([\d.]+)\)"/g)].every(m => +m[1] > 0 && +m[1] < 1));

// 按天聚合：颜色必须严格按「周日红、周一橙…周六紫」对应
els.dInput.value = '1'; els.dApply.dispatch('click');
const dayKeys = [...new Set(MIN_RAW.map(r => r[0].substr(0, 8)))].sort();
const day0 = new Date(+dayKeys[0].substr(0, 4), +dayKeys[0].substr(4, 2) - 1, +dayKeys[0].substr(6, 2));
const daySpan = Math.round((new Date(+dayKeys[dayKeys.length - 1].substr(0, 4),
  +dayKeys[dayKeys.length - 1].substr(4, 2) - 1, +dayKeys[dayKeys.length - 1].substr(6, 2)) - day0) / 86400000) + 1;
const dFills = [...els.dagsvg.innerHTML.matchAll(/<rect [^>]*fill="(rgba\([^)]*\))"/g)].map(m => m[1]);
const expFills = [];
for (let i = 0; i < daySpan; i++) {
  const d = new Date(day0.getFullYear(), day0.getMonth(), day0.getDate() + i);
  const k = '' + d.getFullYear() + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
  expFills.push(FILLS[WD[k]]);
}
check('按天染色一天一条带，且顺序为 周日金/周一银/…/周六黑',
  dFills.length === daySpan && JSON.stringify(dFills) === JSON.stringify(expFills));

// 取消 -> 两个都取消，底色消失
els.dWdChk.checked = false; els.dWdChk.dispatch('change');
check('取消任一「星期底色」两个标签页同步取消',
  els.mWdChk.checked === false && els.dWdChk.checked === false);
els.bmInput.value = '1'; els.bmApply.dispatch('click');
check('取消后底色消失', !els.minsvg.innerHTML.includes('fill="rgba('));

// 15b. 平均线同样两个标签页共用一个开关
els.mAvgChk.checked = true; els.mAvgChk.dispatch('change');
check('勾选任一「平均线」两个标签页同步勾选',
  els.mAvgChk.checked === true && els.dAvgChk.checked === true);
els.bmInput.value = '1'; els.bmApply.dispatch('click');
check('同步勾选后按分钟页出现平均线',
  els.minsvg.innerHTML.includes('stroke="#93c5fd"') && els.minsvg.innerHTML.includes('stroke="#fcd34d"'));
els.dAvgChk.checked = false; els.dAvgChk.dispatch('change');
check('取消任一「平均线」两个标签页同步取消',
  els.mAvgChk.checked === false && els.dAvgChk.checked === false);
els.bmInput.value = '1'; els.bmApply.dispatch('click');

// 16. 频数分布直方图（「每日明细数据」上方）：上下分轴（上=字数、下=键数）
check('HTML 在「每日明细数据」上方有直方图栏目',
  html.includes('id="hsvg"') && html.indexOf('id="hsvg"') < html.indexOf('<summary>每日明细数据'));
check('直方图有可调组距输入框 + 绘图按钮', html.includes('id="hBin"') && html.includes('id="hApply"'));
els['s-min'].checked = true;                     // 直方图跟随当前标签页
els.minThresh.value = '0'; els.minThresh.dispatch('input');
els.bmInput.value = '1'; els.bmApply.dispatch('click');
const hsvg = els.hsvg.innerHTML;
const filtH = expectedPts(0, 1);
const hw = [...hsvg.matchAll(/data-s="w" data-n="(\d+)"/g)].map(m => +m[1]);
const hk = [...hsvg.matchAll(/data-s="k" data-n="(\d+)"/g)].map(m => +m[1]);
const sum = a => a.reduce((x, y) => x + y, 0);
check('直方图字、键各画一组柱', hw.length > 0 && hk.length > 0);
check('直方图频数合计=当前显示的数据点数（字）', sum(hw) === filtH.length);
check('直方图频数合计=当前显示的数据点数（键）', sum(hk) === filtH.length);

// 上下分离：蓝柱贴着中轴往上、橙柱贴着同一条中轴往下
function barRects(re) {
  return [...hsvg.matchAll(re)].map(m => ({ x: +m[1], y: +m[2], w: +m[3], h: +m[4] }))
    .filter(r => r.h > 12);                       // 排除图例小方块
}
const blueBars = barRects(/<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="#2563eb"/g);
const orangeBars = barRects(/<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="#f59e0b"/g);
const hhits = [...hsvg.matchAll(/<rect class="hhit"[^>]*>/g)].map(m => {
  const o = {};
  for (const a of m[0].matchAll(/([a-z-]+)="([^"]*)"/g)) o[a[1]] = a[2];
  return o;
});
const wHit = hhits.find(o => o['data-s'] === 'w'), kHit = hhits.find(o => o['data-s'] === 'k');
// 中轴 y：取「0」那条纵轴刻度的文字位置（y = 中轴 + 4）
const zeroM = hsvg.match(/<text x="48" y="([\d.]+)" class="xl" text-anchor="end">0<\/text>/);
const midY = zeroM ? (+zeroM[1] - 4) : NaN;
check('字数柱在中轴上方（顶在上、底边贴中轴）',
  blueBars.length > 0 && blueBars.every(r => r.y < midY && Math.abs(r.y + r.h - midY) < 0.6));
check('键数柱在中轴下方（顶边贴中轴、往下长）',
  orangeBars.length > 0 && orangeBars.every(r => Math.abs(r.y - midY) < 0.6 && r.h > 0));
// 上下两半对称：字 1/1 刻度到中轴的距离 = 键 1/1 刻度到中轴的距离
const tw = [...hsvg.matchAll(/data-haxis="w" data-f="1"[^>]*>([\d,]+)</g)].map(m => +m[1].replace(/,/g, ''))[0];
const tk = [...hsvg.matchAll(/data-haxis="k" data-f="1"[^>]*>([\d,]+)</g)].map(m => +m[1].replace(/,/g, ''))[0];
const yw1 = [...hsvg.matchAll(/<text x="48" y="([\d.]+)" class="xl hyt"[^>]*data-haxis="w" data-f="1"/g)].map(m => +m[1])[0];
const yk1 = [...hsvg.matchAll(/<text x="48" y="([\d.]+)" class="xl hyt"[^>]*data-haxis="k" data-f="1"/g)].map(m => +m[1])[0];
check('上下共用同一条中轴（两半高度相等）',
  Math.abs((midY - (yw1 - 4)) - ((yk1 - 4) - midY)) < 0.6 && tw > 0 && tk > 0);
// 命中区=柱子本身（柱间空白不弹提示）：每条命中区与一根柱子重合（宽度相同、贴中轴那一端相同）
const allBars = [...hsvg.matchAll(/<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="#(?:2563eb|f59e0b)"/g)]
  .map(m => ({ x: +m[1], y: +m[2], w: +m[3], h: +m[4] }))
  .filter(r => !(r.y === 5 && r.h === 11));        // 排除图例里的两个 11px 小方块
const hitsMatchBars = hhits.every(o => allBars.some(r =>
  Math.abs(r.x - (+o['x'])) < 0.6 && Math.abs(r.w - (+o['width'])) < 0.6
  // 贴中轴的那一端与柱子齐平（字柱比底边、键柱比顶边；极矮柱子的 6px 最小高度只会往远离中轴的方向多出几像素）
  && (Math.abs(r.y + r.h - (+o['y'] + (+o['height']))) < 0.6 || Math.abs(r.y - (+o['y'])) < 0.6)
  && Math.abs((+o['height']) - Math.max(6, r.h)) < 0.6));         // 高度=柱高（极矮的柱子给 6px）
check('直方图命中区只覆盖柱子本身（柱间空白不弹提示框）',
  hhits.length > 0 && hhits.length === allBars.length && hitsMatchBars);
check('每根柱子都有命中区、频数为 0 的区间没有命中区（两处数量一致）',
  hhits.length === allBars.length);

// 悬停：即时显示与折线图同一套提示框（不靠浏览器原生 title 的 1 秒延迟）
const hEl = el('hhit');
Object.keys(wHit).forEach(k => { hEl.attrs[k] = wHit[k]; });
hEl.attrs['class'] = 'hhit';
(docListeners['mouseover'] || []).forEach(fn => fn({ target: hEl, clientX: 100, clientY: 100 }));
check('悬停直方图柱子即时弹出提示框', els.tt.innerHTML.includes('个时段') && els.tt.innerHTML.includes('–'));
check('提示框里同时给出字/键频数', (els.tt.innerHTML.match(/tt-row/g) || []).length === 2);
(docListeners['mouseout'] || []).forEach(fn => fn({ target: hEl }));
check('移开即隐藏提示框', els.tt.style.display === 'none');

// 单击：在右侧面板里列出该区间的全部时段（数据全在页面里，不访问后端）
const hN = +wHit['data-n'];
(docListeners['click'] || []).forEach(fn => fn({ target: hEl, clientX: 100, clientY: 100 }));
const klText = (els.klPanelBody.children || []).map(c => c.text || '').join('');
check('单击直方图柱子打开明细面板', els.klPanel.className === 'klpanel show');
check('面板标题=该区间的指标与组数', els.klPanelTitle.textContent.indexOf('上屏字数') === 0
  && els.klPanelTitle.textContent.indexOf(String(hN)) > 0);
check('面板列出该区间的全部时段（条数=该柱频数）',
  hN > 0 && klText.split('\n').length === hN && klText.split('\n')[0].indexOf(' 字 / ') > 0);

// 组距默认/收敛
let hbin = parseInt(els.hBin.value, 10);
check('组距默认跟随折线图组距（点数放得下时等于 1）',
  (Math.floor(Math.max(...filtH.map(p => Math.max(p[0], p[1]))) / 1) + 1 > 120) || hbin === 1);
check('组数不超过 120、也不超过数据点数（组距过大时自动放大）',
  Math.floor(Math.max(...filtH.map(p => Math.max(p[0], p[1]))) / hbin) + 1
  <= Math.min(120, Math.max(8, filtH.length)));
check('所有箱子的下界都是组距的整数倍',
  [...hsvg.matchAll(/data-b="(\d+)"/g)].every(m => (+m[1] * hbin) % hbin === 0));

// 17. 峰值读数：去掉「每点 N 分钟 ·」；时间做成可点链接，点击把折线图滚到该点
const lblHtml = els.minDensityLabel.innerHTML;
check('峰值读数已去掉「每点 N 分钟 ·」', !lblHtml.includes('每点') && lblHtml.indexOf('共 ') === 0);
check('峰值时间是可点链接', (lblHtml.match(/class="pk"/g) || []).length === 2);
const pkTag = lblHtml.match(/<a class="pk"[^>]*>/g)[0];
const pkEl = el('pk');
for (const mm of pkTag.matchAll(/([a-z-]+)="([^"]*)"/g)) pkEl.attrs[mm[1]] = mm[2];
pkEl.attrs['class'] = 'pk';
els.minScroll.scrollLeft = 0;
(docListeners['click'] || []).forEach(fn => fn({ target: pkEl }));
const pkX = +pkEl.attrs['data-x'];
check('点击峰值链接把折线图滚到该点',
  els.minScroll.scrollLeft === Math.max(0, pkX - els.minScroll.clientWidth / 2));

// 18. 指标切换按钮：纯文字（无边框/底色），颜色=图表里的字色/键色
check('指标按钮为纯文字（无边框、无底色）',
  /\.thr \.thr-btn \{[^}]*border: 0/.test(html) && /\.thr \.thr-btn \{[^}]*background: none/.test(html)
  && /\.thr \.thr-btn \{[^}]*font: inherit/.test(html));
check('指标按钮颜色=字色（蓝）/键色（橙）',
  /\.thr \.thr-btn \{[^}]*color: #2563eb/.test(html)
  && /\.thr \.thr-btn\[data-metric="keys"\] \{ color: #f59e0b/.test(html));

// 19. 三组控件同一行、星期底色默认开、说明文字已删除、主题色占位符已替换
check('「平均线/星期底色/隐藏…」在同一行（.opts）',
  (html.match(/class="opts"/g) || []).length === 2 && /\.opts \{[^}]*display: flex/.test(html));
check('星期底色默认勾选（两个标签页）', /id="dWdChk" checked/.test(html) && /id="mWdChk" checked/.test(html));
check('已删掉「下拉框选项 / 向左滚动…」等说明文字',
  !html.includes('下拉框选项') && !html.includes('向左滚动查看更早的数据')
  && !html.includes('class="scroll-hint"') && !html.includes('class="note"'));
check('主题色占位符已全部替换', !html.includes('__CW__') && !html.includes('__CK__'));
check('悬停提示的时间后面带星期简称',
  (() => {
    const ah = [...els.minsvg.innerHTML.matchAll(/class="hit"[^>]*data-wd="([A-Za-z]{3})"/g)];
    return ah.length > 0;
  })());

// 20. 顶部卡片：已删掉「日均上屏 / 日均按键」（连同计算代码）
check('HTML 已无「日均上屏 / 日均按键」卡片', !html.includes('日均上屏') && !html.includes('日均按键'));
check('组距下拉候选列表（datalist）已删除',
  !html.includes('<datalist') && !html.includes('list="dOpts"') && !html.includes('list="bmOpts"')
  && !html.includes('id="dOpts"') && !html.includes('id="bmOpts"'));
check('组距输入框仍在（可直接输入 + 回车/绘图）',
  /id="dInput"[^>]*type="number"/.test(html) && /id="bmInput"[^>]*type="number"/.test(html)
  && html.includes('id="dApply"') && html.includes('id="bmApply"'));
check('按键次数折线为实线（无 dasharray，图例样线也是实线）',
  (() => {
    const g = els.minsvg.innerHTML.match(/<g id="gk-min">([\s\S]*?)<\/g>/);
    return !!g && g[1].includes('<polyline') && !g[1].includes('dasharray')
      && !html.includes('stroke-dasharray="6 4"');
  })());
check('其余卡片仍在（今天/记录天数/累计上屏/累计按键/分钟级记录）',
  ['今天', '记录天数', '累计上屏', '累计按键', '分钟级记录'].every(k => html.includes('>' + k + '<')));

// 21. 纵轴最大值可改（折线图）：点刻度数字 -> 该数字成为纵轴最大值；点最顶上那个 -> 减半
function ytSpans(box) {
  return [...box.innerHTML.matchAll(/<span class="([^"]*)"([^>]*)>([^<]*)<\/span>/g)];
}
function ytFind(box, f) {
  return ytSpans(box).find(m => m[1].includes('ytc') && new RegExp('data-f="' + f + '"').test(m[2]));
}
function ytVal(box, f) { const t = ytFind(box, f); return t ? +t[3].replace(/,/g, '') : NaN; }
function ytClick(box, f) {
  const t = ytFind(box, f);
  if (!t) return false;
  const e = el('ytick');
  e.attrs['class'] = t[1];
  for (const a of t[2].matchAll(/([a-z-]+)="([^"]*)"/g)) e.attrs[a[1]] = a[2];
  e.textContent = t[3];
  (docListeners['click'] || []).forEach(fn => fn({ target: e }));
  return true;
}
function minCircleY(svg) {
  const g = svg.match(/<g id="gw-min">([\s\S]*?)<\/g>/);
  if (!g) return NaN;
  const ys = [...g[1].matchAll(/<circle cx="[\d.]+" cy="([\d.]+)" r="3.2"/g)].map(m => +m[1]);
  return ys.length ? Math.min(...ys) : NaN;
}
els.bmInput.value = '1'; els.bmApply.dispatch('click');
const autoTop = ytVal(els.yaxL, '1');
const yTop0 = minCircleY(els.minsvg.innerHTML);
check('纵轴刻度数字可点（带 data-f / data-mode / data-axis）',
  autoTop > 0 && !!ytFind(els.yaxL, '0.4') && /data-axis="w"/.test(ytFind(els.yaxL, '0.4')[2]));
check('HTML 里纵轴刻度可点（CSS pointer-events 放行）', /\.yax \.ytc \{ pointer-events: auto/.test(html));
check('点纵轴第 4 档：该数字成为纵轴最大值（顶格数字=它）',
  ytClick(els.yaxL, '0.4') && ytVal(els.yaxL, '1') === Math.round(autoTop * 0.4));
check('其余刻度按新最大值重算（6 档刻度：0 / 1⁄5 … 5⁄5）',
  ytVal(els.yaxL, '0.6') === Math.round(Math.round(autoTop * 0.4) * 0.6)
  && ytVal(els.yaxL, '0.2') === Math.round(Math.round(autoTop * 0.4) * 0.2));
check('点位同步改变（纵向拉长：最高点向上移动）', minCircleY(els.minsvg.innerHTML) < yTop0 - 0.5);
check('超出绘图区的部分被裁剪（绘图区 clipPath）', /<clipPath id="cpl-min">/.test(els.minsvg.innerHTML));
const topNow = ytVal(els.yaxL, '1');
ytClick(els.yaxL, '1');
check('点最顶上那个数字：纵轴范围翻倍（那个数字落到正中间）',
  ytVal(els.yaxL, '1') === Math.round(topNow * 2) && ytVal(els.yaxL, '0.4') === Math.round(topNow * 0.8));
// 字、键两条轴各自独立
const kBefore = ytVal(els.yaxR, '1');
ytClick(els.yaxR, '0.6');
check('按键次数轴可单独改（字轴不受影响）',
  ytVal(els.yaxR, '1') === Math.round(kBefore * 0.6) && ytVal(els.yaxL, '1') === Math.round(topNow * 2));
// 改组距（数据口径变了）后回到自动算法
els.bmInput.value = '5'; els.bmApply.dispatch('click');
check('改组距后纵轴回到自动（不再沿用上次手动值）',
  ytVal(els.yaxL, '1') === ytVal(els.yaxL, '1') && ytVal(els.yaxL, '1') > 0
  && els.yaxL.innerHTML.indexOf('data-f="1"') > 0);
els.bmInput.value = '1'; els.bmApply.dispatch('click');

// 22. 纵轴最大值可改（直方图）：上下两半各自独立
function hTickVal(axis, f) {
  const m = els.hsvg.innerHTML.match(new RegExp('data-haxis="' + axis + '" data-f="' + f + '"[^>]*>([\\d,]+)<'));
  return m ? +m[1].replace(/,/g, '') : NaN;
}
function hTickClick(axis, f) {
  const e = el('htick');
  e.attrs['class'] = 'xl hyt';
  e.attrs['data-haxis'] = axis; e.attrs['data-f'] = f;
  (docListeners['click'] || []).forEach(fn => fn({ target: e }));
}
els.minThresh.value = '0'; els.minThresh.dispatch('input');
els.hBin.value = '1'; els.hApply.dispatch('click');
const hwTop = hTickVal('w', '1'), hkTop = hTickVal('k', '1');
check('直方图纵轴刻度可点（字/键各自带 data-haxis）', hwTop > 0 && hkTop > 0);
hTickClick('w', '1');
check('点直方图字轴顶端：纵轴范围翻倍', hTickVal('w', '1') === Math.round(hwTop * 2));
check('点直方图字轴不影响键轴', hTickVal('k', '1') === hkTop);
hTickClick('k', '0.5');
check('点直方图键轴中间档：最大值变成那一档', hTickVal('k', '1') === Math.round(hkTop * 0.5));

// 23. 按天聚合的数据点：单击也弹与「按分钟聚合」同一套提示框 + 按键明细面板
els['s-min'].checked = false; els['s-dagg'].checked = true;
els.dThresh.value = '0'; els.dThresh.dispatch('input');
els.dInput.value = '1'; els.dApply.dispatch('click');
const dHitTag = [...els.dagsvg.innerHTML.matchAll(/<circle class="hit"[^>]*>/g)];
check('按天聚合的数据点带起止日期（供取当天按键明细）',
  dHitTag.length > 0 && /data-kd1="\d{8}" data-kd2="\d{8}"/.test(dHitTag[0][0]));
const dHit = el('dhit');
for (const mm of dHitTag[0][0].matchAll(/([a-z0-9-]+)="([^"]*)"/g)) dHit.attrs[mm[1]] = mm[2];
dHit.attrs['class'] = 'hit';
(docListeners['click'] || []).forEach(fn => fn({ target: dHit, clientX: 200, clientY: 200 }));
check('按天聚合单击数据点也弹提示框（样式/内容与按分钟聚合同一套）',
  els.tt.style.display === 'block' && els.tt.innerHTML.includes('上屏字数') && els.tt.innerHTML.includes('按键次数'));
check('按天聚合单击同时打开按键明细面板', els.klPanel.className === 'klpanel show');
check('按天聚合面板标题=该点的日期范围', els.klPanelTitle.textContent.length >= 10);
(docListeners['keydown'] || []).forEach(fn => fn({ key: 'Escape' }));
check('Esc 可关闭（含按天聚合打开的）面板与提示框',
  els.klPanel.className === 'klpanel' && els.tt.style.display === 'none');

// 24. 设置面板：点左上角标题打开；三个输入框各自的滚轮增量 + 纵轴顶端行为
check('HTML 有设置面板（标题可点 + 遮罩 + 三个数值框 + 两个单选）',
  html.includes('id="ttl"') && html.includes('id="setPanel"') && html.includes('id="setMask"')
  && html.includes('id="cfgBw"') && html.includes('id="cfgThr"') && html.includes('id="cfgHist"')
  && html.includes('id="cfgYHalf"') && html.includes('id="cfgYStep"'));
check('设置默认值：组距 10、阈值自适应（且数值框被灰掉）、纵轴=减半',
  els.cfgBw.value === '10' && els.cfgHist.value === '10' && els.cfgThrAuto.checked === true
  && els.cfgThr.disabled === true && els.cfgYHalf.checked === true);
els.ttl.dispatch('click');
check('点标题打开设置面板', els.setPanel.className.indexOf('show') >= 0 && els.setMask.className.indexOf('show') >= 0);
els.setClose.dispatch('click');
check('× 关闭设置面板', els.setPanel.className.indexOf('show') < 0 && els.setMask.className.indexOf('show') < 0);
els.ttl.dispatch('click');
(docListeners['keydown'] || []).forEach(fn => fn({ key: 'Escape' }));
check('Esc 关闭设置面板', els.setPanel.className.indexOf('show') < 0);

// 24b. 折线图组距的滚轮：默认 ±10
function wheelEl(el2, up) {
  const prev = sandbox.document.activeElement;
  sandbox.document.activeElement = el2;
  el2.dispatch('wheel', { deltaY: up ? -100 : 100, preventDefault() {} });
  sandbox.document.activeElement = prev;
  return parseInt(el2.value, 10);
}
els.bmInput.value = '1'; els.bmApply.dispatch('click');
check('折线图组距滚轮：每格 +10', wheelEl(els.bmInput, true) === 11);
check('折线图组距滚轮：连续 +10 后下滚 -10', wheelEl(els.bmInput, true) === 21 && wheelEl(els.bmInput, false) === 11);
els.dInput.value = '1'; els.dApply.dispatch('click');
check('按天聚合的组距滚轮同样 ±10', wheelEl(els.dInput, true) === 11);
// 改设置里的增量 -> 立刻生效
els.cfgBw.value = '3'; els.cfgBw.dispatch('change');
els.bmInput.value = '1'; els.bmApply.dispatch('click');
check('设置里把组距增量改成 3 后滚轮每格 +3', wheelEl(els.bmInput, true) === 4);
els.cfgBw.value = '10'; els.cfgBw.dispatch('change');
// 组距的「自适应」= 跳到相邻好看档位（1/2/5×10^k）
els.cfgBwAuto.checked = true; els.cfgBwAuto.dispatch('change');
check('勾上「自适应」后组距数值框被灰掉', els.cfgBw.disabled === true);
els.bmInput.value = '1'; els.bmApply.dispatch('click');
const niceSeq = [wheelEl(els.bmInput, true), wheelEl(els.bmInput, true), wheelEl(els.bmInput, true)];
check('组距自适应：1 → 2 → 5 → 10（相邻好看档位）', JSON.stringify(niceSeq) === JSON.stringify([2, 5, 10]));
check('组距自适应下滚回到 5', wheelEl(els.bmInput, false) === 5);
els.cfgBwAuto.checked = false; els.cfgBwAuto.dispatch('change');
els.bmInput.value = '1'; els.bmApply.dispatch('click');

// 24c. 直方图组距的滚轮：同样按设置（默认 ±10）
els['s-min'].checked = true; els['s-dagg'].checked = false;   // 用按分钟聚合，组数少、组距不会被自动放大
els.minThresh.value = '0'; els.minThresh.dispatch('input');
els.hBin.value = '1'; els.hApply.dispatch('click');
const hb0 = parseInt(els.hBin.value, 10);      // 组距可能被「不超过 120 组」自动放大，起点以实际值为准
check('直方图组距滚轮：每格 +10', wheelEl(els.hBin, true) === hb0 + 10);
els.cfgHist.value = '5'; els.cfgHist.dispatch('change');
const hb1 = parseInt(els.hBin.value, 10);
check('设置里改直方图增量后生效（+5）', wheelEl(els.hBin, true) === hb1 + 5);
els.cfgHist.value = '10'; els.cfgHist.dispatch('change');

// 24d. 阈值框改成「固定增量」时用数值，取消自适应回到原算法
els.minThresh.value = '0'; els.minThresh.dispatch('change');
els.cfgThrAuto.checked = false; els.cfgThrAuto.dispatch('change');
check('取消「自适应」后阈值数值框可编辑', els.cfgThr.disabled === false);
check('阈值固定增量：每格 +10', wheelMin(true) === 10 && wheelMin(true) === 20);
els.cfgThrAuto.checked = true; els.cfgThrAuto.dispatch('change');
els.minThresh.value = '0'; els.minThresh.dispatch('change');
check('切回「自适应」后又是「跳到最近的数据值」', (() => {
  const v = wheelMin(true);
  return v === expWheel(0, true, 1) && v !== 10;
})());

// 25. 纵轴顶端行为：默认「减半」；设置里可改成「下移一格」
els.bmInput.value = '1'; els.bmApply.dispatch('click');
let topA = ytVal(els.yaxL, '1');
ytClick(els.yaxL, '1');
check('默认「减半」：点顶格 -> 范围翻倍（该数字落到正中间）', ytVal(els.yaxL, '1') === Math.round(topA * 2));
els.cfgYStep.checked = true; els.cfgYStep.dispatch('change');
els.bmInput.value = '5'; els.bmApply.dispatch('click');          // 换组距 -> 回到自动
els.bmInput.value = '1'; els.bmApply.dispatch('click');
topA = ytVal(els.yaxL, '1');
ytClick(els.yaxL, '1');
check('「下移一格」：点顶格 -> 它落到下面那一档（范围 ×1.25）',
  ytVal(els.yaxL, '1') === Math.round(topA / 0.8) && ytVal(els.yaxL, '0.8') === Math.round(topA));
els.cfgYHalf.checked = true; els.cfgYHalf.dispatch('change');

// 26. 布局：组距那一行进白卡片；标签页白底、只有左上/右上圆角、选中不变蓝
check('组距行与图表同在白卡片 .chartcard 里', (() => {
  const m = html.match(/<div class="chartcard">([\s\S]*?)<\/div>\s*<div class="opts">/);
  return !!m && m[1].includes('id="dInput"') && m[1].includes('id="dScroll"');
})());
check('按分钟聚合面板同样（组距行 + 图表都在 .chartcard 内）', (() => {
  const i = html.indexOf('class="pane pane-min"');
  if (i < 0) return false;
  const seg = html.slice(i, i + 6000);
  const card = seg.indexOf('class="chartcard"');
  return card > 0 && seg.indexOf('id="bmInput"') > card
    && seg.indexOf('id="minScroll"') > seg.indexOf('id="bmInput"');
})());
check('标签页白底、不再用主题蓝', /\.tabbar label \{[^}]*background: #fff/.test(html)
  && !/#s-dagg:checked ~ \.tabbar label\[for="s-dagg"\],[\s\S]{0,160}background: #2563eb/.test(html));
check('标签页只有左上/右上圆角（两个挨在一起）',
  /\.tabbar label:first-child \{ border-radius: 8px 0 0 0; \}/.test(html)
  && /\.tabbar label:last-child \{ border-radius: 0 8px 0 0; \}/.test(html)
  && /\.tabbar \{[^}]*gap: 0/.test(html));
check('选中的标签页压住卡片顶边（连成一体）', /border-bottom-color: #fff/.test(html));

// 27. 分钟级数据按月分文件：页脚指向文件夹
check('页脚写明「分钟级原始文件夹（每月一个 txt）」',
  html.includes('分钟级原始文件夹') && html.includes('input_count_raw（每月一个 txt）'));

console.log('done');
