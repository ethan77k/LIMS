/* 轻量 SVG 图表（内网离线，零依赖）。
 * 三个函数均返回 SVG 字符串，配合 v-html 使用：
 *   barChart(data, {ctype})    data = [{label, value}]，ctype 用于下钻明细
 *   lineChart(labels, lines, {ctype})   lines = [{name, data:[...]}]
 *   donutChart(data, {ctype})  data = [{label, value}]
 *
 * 每个可点击元素带 data-ctype / data-ckey 属性，配合文档级委托：
 * 点击后调用 window.__chartClick(ctype, key)，由页面组件接管下钻。
 */
function _svg(w, h, body) {
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" xmlns="http://www.w3.org/2000/svg" style="font-family:'Microsoft YaHei',Arial,sans-serif;display:block">${body}</svg>`;
}

function _short(s, n) {
  s = String(s == null ? '' : s);
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function _attr(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const _COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#14b8a6', '#f472b6', '#64748b'];

function barChart(data, opts = {}) {
  const items = (data || []).filter(d => d.value != null && d.value !== 0);
  if (!items.length) return '<div class="chart-empty">暂无数据</div>';
  const w = opts.width || 620, h = opts.height || 230;
  const ctype = opts.ctype || '';
  const padL = 40, padR = 10, padT = 18, padB = 40;
  const max = Math.max(...items.map(d => d.value), 1);
  const cw = w - padL - padR, ch = h - padT - padB;
  const slot = cw / items.length;
  const bw = Math.min(slot * 0.62, 46);
  let bars = '', labels = '', hit = '';
  items.forEach((d, i) => {
    const x = padL + i * slot + (slot - bw) / 2;
    const bh = Math.max(ch * (d.value / max), 1.5);
    const y = padT + ch - bh;
    const color = _COLORS[i % _COLORS.length];
    bars += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${color}" rx="3"></rect>`;
    bars += `<text x="${(x + bw / 2).toFixed(1)}" y="${(y - 5).toFixed(1)}" text-anchor="middle" font-size="11" fill="#333">${d.value}</text>`;
    labels += `<text x="${(x + bw / 2).toFixed(1)}" y="${(h - 16).toFixed(1)}" text-anchor="middle" font-size="11" fill="#666">${_short(d.label, 8)}</text>`;
    hit += `<rect x="${(padL + i * slot).toFixed(1)}" y="${padT}" width="${slot.toFixed(1)}" height="${ch}" fill="transparent" data-ctype="${_attr(ctype)}" data-ckey="${_attr(d.label)}" style="cursor:pointer"><title>${_attr(d.label)}：${d.value}（点击查看明细）</title></rect>`;
  });
  return _svg(w, h, bars + labels + hit);
}

function lineChart(labels, lines, opts = {}) {
  const ls = labels || [];
  const series = (lines || []).map((l, i) => ({ name: l.name, data: l.data || [], color: l.color || _COLORS[i % _COLORS.length] }));
  if (!ls.length) return '<div class="chart-empty">暂无数据</div>';
  const w = opts.width || 640, h = opts.height || 240;
  const ctype = opts.ctype || '';
  const padL = 38, padR = 12, padT = 18, padB = 30;
  const cw = w - padL - padR, ch = h - padT - padB;
  const max = Math.max(...series.flatMap(s => s.data), 1);
  const px = i => padL + (ls.length === 1 ? cw / 2 : cw * i / (ls.length - 1));
  const py = v => padT + ch - ch * v / max;

  let grid = '';
  for (let g = 0; g <= 4; g++) {
    const v = max * g / 4;
    const y = py(v).toFixed(1);
    grid += `<line x1="${padL}" y1="${y}" x2="${w - padR}" y2="${y}" stroke="#eef1f5" stroke-width="1"></line>`;
    grid += `<text x="${padL - 6}" y="${(parseFloat(y) + 4).toFixed(1)}" text-anchor="end" font-size="10" fill="#999">${Math.round(v)}</text>`;
  }
  let paths = '', dots = '';
  series.forEach(s => {
    const pts = s.data.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(' ');
    paths += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"></polyline>`;
    s.data.forEach((v, i) => {
      const cx = px(i).toFixed(1), cy = py(v).toFixed(1);
      dots += `<circle cx="${cx}" cy="${cy}" r="7" fill="transparent" data-ctype="${_attr(ctype)}" data-ckey="${_attr(ls[i])}" style="cursor:pointer"><title>${_attr(ls[i])}：${s.name} ${v}（点击查看明细）</title></circle>`;
      dots += `<circle cx="${cx}" cy="${cy}" r="3" fill="${s.color}" pointer-events="none"></circle>`;
    });
  });
  const step = Math.max(1, Math.ceil(ls.length / 6));
  let xlabels = '';
  ls.forEach((d, i) => {
    if (i % step === 0 || i === ls.length - 1) {
      xlabels += `<text x="${px(i).toFixed(1)}" y="${h - 10}" text-anchor="middle" font-size="10" fill="#888">${_short(d.slice(5), 5)}</text>`;
    }
  });
  let legend = '';
  series.forEach((s, i) => {
    legend += `<text x="${(padL + i * 88).toFixed(1)}" y="13" font-size="11" fill="${s.color}">● ${_short(s.name, 6)}</text>`;
  });
  return _svg(w, h, grid + paths + dots + xlabels + legend);
}

function donutChart(data, opts = {}) {
  const items = (data || []).filter(d => d.value > 0);
  const total = items.reduce((s, d) => s + d.value, 0);
  if (!total) return '<div class="chart-empty">暂无数据</div>';
  const size = opts.size || 180;
  const ctype = opts.ctype || '';
  const cx = size / 2, cy = size / 2, r = size / 2 - 10, r2 = r * 0.56;
  let a0 = -Math.PI / 2, segs = '';
  items.forEach((d, i) => {
    const angle = d.value / total * Math.PI * 2;
    const a1 = a0 + angle;
    const large = angle > Math.PI ? 1 : 0;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    segs += `<path d="M${cx.toFixed(1)},${cy.toFixed(1)} L${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 ${large} 1 ${x1.toFixed(1)},${y1.toFixed(1)} Z" fill="${_COLORS[i % _COLORS.length]}" data-ctype="${_attr(ctype)}" data-ckey="${_attr(d.label)}" style="cursor:pointer"><title>${_attr(d.label)}：${d.value}（点击查看明细）</title></path>`;
    a0 = a1;
  });
  segs += `<circle cx="${cx}" cy="${cy}" r="${r2}" fill="#fff"></circle>`;
  segs += `<text x="${cx}" y="${cy + 5}" text-anchor="middle" font-size="16" font-weight="bold" fill="#333">${total}</text>`;
  const lx = size + 14;
  let legend = '';
  items.forEach((d, i) => {
    const y = cy - (items.length - 1) * 9 + i * 18;
    legend += `<text x="${lx}" y="${y.toFixed(1)}" font-size="12" fill="#333"><tspan fill="${_COLORS[i % _COLORS.length]}">●</tspan> ${_short(d.label, 8)} ${d.value}</text>`;
  });
  return _svg(size + 150, size, segs + legend);
}

/* 文档级点击委托：命中带 data-ckey 的图表元素时回调 window.__chartClick */
document.addEventListener('click', function (e) {
  const t = e.target;
  const el = t && typeof t.closest === 'function' ? t.closest('[data-ckey]') : null;
  if (!el) return;
  if (typeof window.__chartClick === 'function') {
    window.__chartClick(el.getAttribute('data-ctype'), el.getAttribute('data-ckey'));
  }
});

/* 挂到 window 便于其它脚本引用 */
window.lineChart = lineChart;
window.barChart = barChart;
window.donutChart = donutChart;
