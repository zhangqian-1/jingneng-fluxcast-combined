"use strict";
const $ = (id) => document.getElementById(id);
const C = {
  cyan: "#41cfde",
  green: "#77dba0",
  blue: "#629bfb",
  amber: "#edbd73",
  muted: "#899db7",
};
const colors = [
  "#41cfde",
  "#a390eb",
  "#edbd73",
  "#629bfb",
  "#77dba0",
  "#e38cac",
  "#83abc8",
];
const state = {
  data: null,
  index: 0,
  mode: "balance",
  station: null,
  prices: false,
  timer: null,
};
const clean = (n) => (Math.abs(Number(n)) < 1e-7 ? 0 : Number(n));
const fmt = (n, d = 2) =>
  n == null || !Number.isFinite(Number(n)) ? "—" : clean(n).toLocaleString("zh-CN", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
const sum = (a) => a.reduce((s, n) => s + Number(n), 0);
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const pct = (n, d) => (d > 0 ? (100 * n) / d : 0);
const hhmm = (s) => s.slice(11, 16);
const lastIndex = () => Math.max(1, (state.data?.rows.length || 8) - 1);
const actualPower = (row, code) => row[`same_period_actual_${code}_MW`];
const changePower = (row, code) => row[`${code}_MW`] - actualPower(row, code);
const stationEnergy = (code) => sum(state.data.rows.slice(0, state.index + 1)
  .map(r => r[`${code}_MW`])) * state.data.periodMinutes / 60;
function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.remove("show"), 3500);
}
const costs = [
  ["发电成本（含燃料）", "directGenerationCostYuan", C.cyan],
  ["主网购电成本", "gridCostYuan", "#8995db"],
  ["碳成本", "carbonCostYuan", C.green],
  ["启停成本", "startStopCostYuan", C.amber],
  ["弃电成本", "curtailCostYuan", "#ad90b5"],
];
const rateText = (n, d) => (d > 1e-7 ? `${fmt((100 * n) / d, 2)}%` : "—");
function intervalEnd(index) {
  const minutes = (index + 1) * state.data.periodMinutes;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}
function metric(id, label, value, unit, note, accent) {
  return `<article class="kpi" id="${id}" style="--accent:${accent}"><div class="kpi-label">${label}</div><div class="kpi-number"><strong>${value}</strong><em>${unit}</em></div><div class="kpi-sub">${note}</div></article>`;
}
function comparisonMetric(id, label, baseline, optimized, unit, note, accent) {
  const baseLabel = "实际运行基准";
  const optLabel = state.data?.isSinglePeriod ? "优化方案" : "优化后";
  return `<article class="kpi comparison-kpi" id="${id}" style="--accent:${accent}"><div class="kpi-label">${label}<em>${unit}</em></div><div class="kpi-comparison"><div class="comparison-baseline"><span>${baseLabel}</span><strong>${fmt(baseline)}</strong></div><div class="comparison-optimized"><span>${optLabel}</span><strong>${fmt(optimized)}</strong></div></div><div class="kpi-sub">${note}</div></article>`;
}
function renderSingleSummary() {
  const d = state.data, r = d.rows[state.index], p = d.periods[state.index];
  const s = state.cumulative[state.index];
  const start = hhmm(r.time), end = intervalEnd(state.index);
  const prefix = "累计";
  const range = `00:00–${end}`;
  document.querySelector(".mode-badge").textContent = "计算结果回放";
  $("generated").textContent = `更新于 ${d.comparison.version || "2026-09-23"}`;
  $("cumulative-window").textContent = `${prefix}区间 ${range} · 含所选时段`;
  $("period-window").textContent = `当前时段 ${start}–${end} · 15分钟`;
  $("analysis-window").textContent = `${prefix} ${range}`;
  $("cost-window").textContent = `${prefix}优化成本明细 / 万元`;
  document.querySelector(".economics-panel h2").textContent = `${prefix}调度分析`;
  $("zoom-time").textContent = `${start}–${end}`;
  $("zoom-range").value = state.index;
  const hasBaseline = d.comparison.status === "available";
  const saved = hasBaseline ? s.baselineCostYuan - s.objectiveYuan : null;
  const changeNote = (value, base, unit) => value == null ? "实际运行基准待核算" : Math.abs(value) < 0.005
    ? `与实际基准持平 · 变化 0.00 ${unit}`
    : `<span class="${value >= 0 ? "good" : "bad"}">较实际基准${value >= 0 ? "减少" : "增加"} ${fmt(Math.abs(value))} ${unit} · ${rateText(Math.abs(value), base)}</span>`;
  function cards(values, isCumulative) {
    const prefix = isCumulative ? "累计" : "本时段";
    const id = isCumulative ? "cumulative" : "period";
    const saved = hasBaseline ? values.baselineCostYuan - values.objectiveYuan : null;
    const reduced = hasBaseline ? values.baselineCarbonTon - values.carbonTon : null;
    return [
      metric(`${id}-renewable`, `${prefix}新能源接纳电量`, fmt(values.renewableAcceptedMWh), "MWh", `<span class="good">接纳率 ${rateText(values.renewableAcceptedMWh, values.renewableForecastMWh)}</span>`, C.green),
      comparisonMetric(`${id}-carbon`, `${prefix}碳排放量`, hasBaseline ? values.baselineCarbonTon : null, values.carbonTon, "tCO₂", changeNote(reduced, values.baselineCarbonTon, "tCO₂"), C.amber),
      metric(`${id}-grid`, `${prefix}主网购电量`, fmt(values.gridBuyMWh), "MWh", isCumulative ? `含所选时段 · 已累计 ${state.index + 1} 个时段` : `本时段购电功率 ${fmt(r.grid_buy_MW, 1)} MW`, C.blue),
      metric(`${id}-thermal`, `${prefix}燃机发电量`, fmt(values.thermalMWh), "MWh", isCumulative ? `七站合计 · 已累计 ${state.index + 1} 个时段` : "七站合计 · 功率 × 0.25小时", C.cyan),
      comparisonMetric(`${id}-cost`, `${prefix}综合成本`, hasBaseline ? values.baselineCostYuan / 10000 : null, values.objectiveYuan / 10000, "万元", changeNote(saved == null ? null : saved / 10000, values.baselineCostYuan / 10000, "万元"), C.cyan),
    ].join("");
  }
  $("kpis").innerHTML = cards(s, true);
  $("period-kpis").innerHTML = cards(p, false);
  const advice = [
    ["经济性", hasBaseline ? `实际运行基准 ${fmt(s.baselineCostYuan / 10000)} 万元，优化方案 ${fmt(s.objectiveYuan / 10000)} 万元，${saved >= 0 ? "节省" : "增加"} ${fmt(Math.abs(saved) / 10000)} 万元（${rateText(Math.abs(saved), s.baselineCostYuan)}）。` : `优化成本 ${fmt(s.objectiveYuan / 10000)} 万元。`],
    ["绿电消纳", `接纳 ${fmt(s.renewableAcceptedMWh)} MWh，接纳率 ${rateText(s.renewableAcceptedMWh, s.renewableForecastMWh)}，弃电 ${fmt(s.curtailMWh)} MWh。`],
    ["供能安排", `燃机发电 ${fmt(s.thermalMWh)} MWh，新能源接纳 ${fmt(s.renewableAcceptedMWh)} MWh，主网购电 ${fmt(s.gridBuyMWh)} MWh。`],
  ];
  $("dispatch-advice").innerHTML = advice.map(([title, text]) => `<li><strong>${title}：</strong>${esc(text)}</li>`).join("");
  $("cost-total").textContent = `合计 ${fmt(s.objectiveYuan / 10000)}`;
  $("cost-detail").innerHTML = costs.map(([name, key, color]) => `<div class="cost-item"><span><i style="background:${color}"></i>${name}</span><b>${fmt(s[key] / 10000)}</b></div>`).join("");
  $("accepted-rate").textContent = rateText(s.renewableAcceptedMWh, s.renewableForecastMWh);
  $("curtail-energy").innerHTML = `${fmt(s.curtailMWh)}<small> MWh</small>`;
  $("renewable-ring").style.setProperty("--rate", `${Math.min(100, pct(s.renewableAcceptedMWh, s.renewableForecastMWh))}%`);
  document.querySelector(".renewable-summary > div:nth-child(1) > span").textContent = `${prefix}接纳率`;
  document.querySelector(".renewable-summary > div:nth-child(2) > span").textContent = `${prefix}弃电量`;
  $("solver-label").textContent = "HiGHS · 逐时段优化";
  $("provenance").textContent = `离线情景 · 同期七站实测基准 ${d.summary.thermal_history_day} / 风光替代 ${d.summary.renewable_day} · 独立结果累计，非执行实绩`;
  $("provenance").title = d.comparison.note;
  document.querySelector(".timeline-note").textContent = "拖动时间轴联动查看";
  $("time-range").setAttribute("aria-label", "调度结果时刻");
}
function spark(values, color) {
  const max = Math.max(...values, 1),
    w = 80,
    h = 22;
  const points = values
    .map(
      (v, i) =>
        `${((i / lastIndex()) * w).toFixed(1)},${(h - (v / max) * (h - 3)).toFixed(1)}`,
    )
    .join(" ");
  return `<svg viewBox="0 0 80 26" aria-hidden="true"><line x1="0" y1="23" x2="80" y2="23" stroke="#263b51"/><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.25"/><line x1="${(state.index / lastIndex()) * 80}" y1="1" x2="${(state.index / lastIndex()) * 80}" y2="24" stroke="#66829b" stroke-width=".5"/></svg>`;
}
function renderStations() {
  const { rows, stations } = state.data,
    r = rows[state.index];
  const online = stations.filter((s) => r[`${s.name}_on`] > 0.5).length;
  $("online-count").textContent = `${online} / 7 站运行`;
  $("station-context").textContent =
    `当前时段 ${hhmm(r.time)}–${intervalEnd(state.index)} · 同期实测与优化对比 · 求解初值取上一时刻`;
  $("station-prices").textContent = state.prices ? "返回出力" : "计算单价";
  $("station-prices").setAttribute("aria-pressed", String(state.prices));
  const columns = state.prices
    ? [
        ["场站 / ID", ""],
        ["发电成本（含燃料）", "元/kWh"],
        ["购电价", "元/kWh"],
      ]
    : [
        ["场站 / ID", ""],
        ["全天出力", ""],
        ["同期实测", "MW"],
        ["优化出力", "MW"],
        ["出力调整", "MW"],
        ["累计电量", "MWh"],
        ["计划状态", ""],
      ];
  $("station-heading").innerHTML =
    `<tr>${columns.map(([label, unit], i) => `<th class="${i ? "number" : ""} ${!state.prices && i === 1 ? "spark-heading" : ""}">${label}${unit ? `<small>${unit}</small>` : ""}</th>`).join("")}</tr>`;
  document
    .querySelector(".station-panel")
    .classList.toggle("show-prices", state.prices);
  $("station-heading").title = state.prices
    ? "本次计算采用的价格参数"
    : state.data.isSinglePeriod ? "实际出力取同一目标时刻历史实测；调整量＝优化出力－同期实际出力；求解初值仍使用上一时刻实测" : "当前实测固定为本轮初始断面；首步调整＝首步优化出力－当前实测；后续时段不冒充实时调整";
  $("station-rows").innerHTML = stations
    .map((s, i) => {
      const on = r[`${s.name}_on`] > 0.5;
      const identity = `<td><div class="station-name" style="--accent:${colors[i]}"><i></i>${s.label}</div><div class="station-code">${s.name} · ID ${s.sourceId}</div></td>`;
      if (state.prices) {
        return `<tr tabindex="0" data-station="${s.name}" class="${state.station === s.name ? "selected" : ""}" aria-label="查看${s.label}出力" aria-selected="${state.station === s.name}">${identity}${["gen_cost_yuan_per_kwh", "buy_price_yuan_per_kwh"].map((key) => `<td class="number price-cell">${price(s[key], 4)}</td>`).join("")}</tr>`;
      }
      return `<tr tabindex="0" data-station="${s.name}" class="${state.station === s.name ? "selected" : ""}" aria-label="查看${s.label}出力" aria-selected="${state.station === s.name}"><td><div class="station-name" style="--accent:${colors[i]}"><i></i>${s.label}</div><div class="station-code">${s.name} · ID ${s.sourceId}</div></td><td class="spark-cell">${spark(
        rows.map((r) => r[`${s.name}_MW`]),
        colors[i],
      )}</td><td class="number baseline-power">${fmt(actualPower(r, s.name), 1)}</td><td class="number now-power" title="运行区间 ${fmt(s.pmin, 0)} – ${fmt(s.pmax, 0)} MW">${fmt(r[`${s.name}_MW`], 1)}</td><td class="number adjustment-power" title="优化出力－实际出力；正值上调，负值下调">${adjustment(changePower(r, s.name))}</td><td class="number energy-cell">${fmt(stationEnergy(s.name), 1)}</td><td class="number"><span class="state ${on ? "" : "off"}">${on ? "运行" : "停机"}</span></td></tr>`;
    })
    .join("");
}
function adjustment(value) {
  if (value == null) return "—";
  const rounded = Number(clean(value).toFixed(1));
  return `${rounded > 0 ? "+" : ""}${fmt(rounded, 1)}`;
}
function price(value, digits = 4) {
  return typeof value === "number" && Number.isFinite(value)
    ? fmt(value, digits)
    : "—";
}
function renderCurrent() {
  renderSingleSummary();
  const r = state.data.rows[state.index],
    time = hhmm(r.time),
    demand = r.equivalent_load_MW;
  $("selected-time").textContent = time;
  $("flow-time").textContent = time;
  $("period-label").textContent =
    `${String(state.index + 1).padStart(2, "0")} / ${state.data.rows.length}`;
  $("time-range").value = state.index;
  $("load-now").textContent = fmt(demand, 1);
  const balance =
    r.gas_total_MW +
    r.renewable_accepted_MW +
    r.grid_buy_MW -
    r.grid_sell_MW -
    demand;
  const valid = Math.abs(balance) < 1e-4;
  $("balance-check").textContent = valid
    ? "✓ 供需平衡"
    : `差额 ${fmt(balance, 3)} MW`;
  $("balance-check").style.color = valid ? C.green : "#ee8d8d";
  const supply = r.gas_total_MW + r.renewable_accepted_MW + r.grid_buy_MW;
  $("flow-list").innerHTML = [
    ["燃机出力", r.gas_total_MW, C.cyan, "▥"],
    ["新能源接纳", r.renewable_accepted_MW, C.green, "↗"],
    ["主网购电", r.grid_buy_MW, C.blue, "⇄"],
  ]
    .map(
      ([name, value, color, symbol]) =>
        `<div class="flow-row" style="--accent:${color};--percent:${Math.min(100, Math.max(0, pct(value, supply)))}%"><div class="flow-icon">${symbol}</div><div><div class="flow-name">${name}<span>${fmt(pct(value, supply), 1)}%</span></div><div class="flow-bar"><i></i></div></div><div class="flow-value">${fmt(value, 1)}<small>MW</small></div></div>`,
    )
    .join("");
  $("curtail-now").textContent = fmt(r.curtailment_MW, 1);
  const scroll = $("farm-list").scrollTop;
  $("farm-list").innerHTML = state.farms
    .map(
      (f, i) =>
        `<div class="farm-row"><span class="farm-name" title="${esc(f.station_name)} · farmId ${f.farm_id}"><small>${String(i + 1).padStart(2, "0")}</small>${esc(f.station_name)}</span><span class="farm-power">${fmt(f.accepted[state.index], 1)}</span><span class="farm-forecast">${fmt(f.forecast[state.index], 1)}</span><span class="farm-capacity">${fmt(f.capacity_mw, 1)}</span></div>`,
    )
    .join("");
  $("farm-list").scrollTop = scroll;
  renderStations();
  drawChart();
}
function legend(items) {
  return items
    .map(
      ([name, color, line]) =>
        `<span><i class="${line ? "line" : ""}" style="background:${color}"></i>${name}</span>`,
    )
    .join("");
}
function drawChart() {
  if (!state.data) return;
  const host = $("main-chart"),
    w = host.clientWidth || 900,
    h = host.clientHeight || 220;
  const pad = { left: 48, right: 18, top: 18, bottom: 26 },
    pw = w - pad.left - pad.right,
    ph = h - pad.top - pad.bottom;
  const { rows, stations } = state.data;
  let series = [],
    reference = null,
    limit = null,
    title = '全天供需平衡 <span class="muted">/ 96 时段</span>',
    labels = [];
  if (state.station) {
    const s = stations.find((s) => s.name === state.station),
      color = colors[stations.indexOf(s)];
    title = `${s.label}出力 <span class="muted">/ ID ${s.sourceId}</span>`;
    series = [
      { name: "优化出力", color, values: rows.map((r) => r[`${s.name}_MW`]) },
    ];
    reference = {
      name: "同期实际出力",
      color: C.muted,
      values: rows.map((r) => actualPower(r, s.name)),
      dash: true,
    };
    limit = s;
    labels = [
      ["优化出力", color],
      ["同期实际出力", C.muted, true],
      ["运行下限", C.amber, true],
    ];
  } else if (state.mode === "stations") {
    title = `七站计划出力构成 <span class="muted">/ ${rows.length} 时段</span>`;
    series = stations.map((s, i) => ({
      name: s.label.replace("热电", "").replace("燃气", ""),
      color: colors[i],
      values: rows.map((r) => r[`${s.name}_MW`]),
    }));
    labels = series.map((s) => [s.name, s.color]);
  } else {
    series = [
      {
        name: "燃机出力",
        color: C.cyan,
        values: rows.map((r) => r.gas_total_MW),
      },
      {
        name: "新能源",
        color: C.green,
        values: rows.map((r) => r.renewable_accepted_MW),
      },
      {
        name: "主网购电",
        color: C.blue,
        values: rows.map((r) => r.grid_buy_MW),
      },
    ];
    reference = {
      name: "等效供电目标",
      color: "#e2eaf4",
      values: rows.map((r) => r.equivalent_load_MW),
    };
    labels = [
      ...series.map((s) => [s.name, s.color]),
      ["等效供电目标", "#e2eaf4", true],
    ];
  }
  $("chart-title").innerHTML = title;
  $("main-legend").innerHTML = legend(labels);
  const totals = rows.map((_, i) => sum(series.map((s) => s.values[i])));
  let max = Math.max(
    ...totals,
    ...(reference ? reference.values : [0]),
    limit ? limit.pmax : 0,
    1,
  );
  const step =
    Math.pow(10, Math.floor(Math.log10(max / 4))) *
    ([1, 2, 5, 10].find(
      (n) => n * Math.pow(10, Math.floor(Math.log10(max / 4))) >= max / 4,
    ) || 10);
  max = Math.ceil(max / step) * step;
  const x = (i) => pad.left + (i / lastIndex()) * pw,
    y = (v) => pad.top + ph * (1 - v / max);
  const line = (values) =>
    values
      .map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
      .join(" ");
  let svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${state.station ? "单站优化与实际出力" : "供需功率"}曲线，当前时刻${hhmm(rows[state.index].time)}"><defs>`;
  series.forEach((s, i) => {
    svg += `<linearGradient id="area${i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity=".38"/><stop offset="1" stop-color="${s.color}" stop-opacity=".09"/></linearGradient>`;
  });
  svg += "</defs>";
  for (let value = 0; value <= max + step / 10; value += step) {
    svg += `<line x1="${pad.left}" y1="${y(value)}" x2="${w - pad.right}" y2="${y(value)}" stroke="#26364c" stroke-dasharray="3 5"/><text x="${pad.left - 9}" y="${y(value) + 3}" text-anchor="end">${fmt(value, 0)}</text>`;
  }
  [0, 16, 32, 48, 64, 80, 95].forEach((i) => {
    svg += `<text x="${x(i)}" y="${h - 7}" text-anchor="${i === lastIndex() ? "end" : i === 0 ? "start" : "middle"}">${hhmm(rows[i].time)}</text>`;
  });
  let base = rows.map(() => 0);
  series.forEach((s, i) => {
    const top = s.values.map((v, j) => v + base[j]);
    const path =
      line(top) +
      " " +
      base
        .map((_, j) => `L${x(lastIndex() - j).toFixed(1)},${y(base[lastIndex() - j]).toFixed(1)}`)
        .join(" ") +
      " Z";
    svg += `<path d="${path}" fill="url(#area${i})"/><path d="${line(top)}" stroke="${s.color}" stroke-width="1.6" fill="none"/>`;
    base = top;
  });
  if (reference)
    svg += `<path d="${line(reference.values)}" fill="none" stroke="${reference.color}" stroke-width="1.6" ${reference.dash ? 'stroke-dasharray="5 4"' : ""}/>`;
  if (limit) {
    svg += `<line x1="${pad.left}" y1="${y(limit.pmin)}" x2="${w - pad.right}" y2="${y(limit.pmin)}" stroke="${C.amber}" stroke-opacity=".65" stroke-dasharray="4 5"/><text x="${w - pad.right - 4}" y="${y(limit.pmin) - 5}" text-anchor="end" style="fill:${C.amber}">运行下限 ${fmt(limit.pmin, 0)} MW</text>`;
  }
  const cx = x(state.index),
    current =
      reference && !state.station
        ? reference.values[state.index]
        : totals[state.index];
  svg += `<line x1="${cx}" y1="${pad.top}" x2="${cx}" y2="${h - pad.bottom}" stroke="#9ac6d5" stroke-opacity=".6" stroke-dasharray="3 4"/><circle cx="${cx}" cy="${y(current)}" r="4" stroke="#e5f9ff" stroke-width="1.5" fill="${C.cyan}"/>`;
  const tipw = 122,
    tipx = Math.min(Math.max(pad.left, cx + 10), w - pad.right - tipw);
  svg += `<rect x="${tipx}" y="2" width="${tipw}" height="24" rx="4" fill="#20384a" stroke="#33556b"/><text x="${tipx + 8}" y="18" class="chart-readout">${hhmm(rows[state.index].time)} · ${fmt(current, 1)} MW</text></svg>`;
  host.innerHTML = svg;
}
function setIndex(index) {
  if (!state.data) return;
  state.index = Math.max(0, Math.min(lastIndex(), Math.round(index)));
  renderCurrent();
}
function setMode(mode, station = null) {
  state.mode = mode;
  state.station = station;
  document.querySelectorAll("[data-mode]").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
    b.setAttribute("aria-pressed", b.dataset.mode === mode);
  });
  if (state.data) renderCurrent();
}
function stop() {
  clearInterval(state.timer);
  state.timer = null;
  $("play").textContent = "▶";
  $("play").setAttribute("aria-label", "播放调度结果");
}
async function load(silent = false) {
  $("refresh").disabled = true;
  try {
    if (!window.SINGLE_PERIOD_DATA) throw new Error("单断面展示数据未加载");
    const data = JSON.parse(JSON.stringify(window.SINGLE_PERIOD_DATA));
    if (!data.isSinglePeriod || data.rows?.length !== 96 || data.stations?.length !== 7 ||
        data.farms?.length !== 19 || data.periods?.length !== data.rows.length)
      throw new Error("单断面展示结果不完整");
    const first = !state.data;
    const changed = state.data?.snapshotId !== data.snapshotId;
    stop();
    const stationOrder = [
      "JXRD",
      "JYRD",
      "JQRD",
      "GARD",
      "JFRD",
      "WLRD",
      "SZRD",
    ];
    data.stations.sort(
      (a, b) => stationOrder.indexOf(a.name) - stationOrder.indexOf(b.name),
    );
    state.data = data;
    if (changed) state.index = data.isSinglePeriod ? data.defaultIndex : 0;
    $("time-range").max = $("zoom-range").max = String(data.rows.length - 1);
    state.farms = [...data.farms].sort(
      (a, b) => sum(b.accepted) - sum(a.accepted),
    );
    let total = Object.fromEntries(
      Object.keys(data.periods[0]).map((k) => [k, 0]),
    );
    state.cumulative = data.periods.map((period) => {
      total = Object.fromEntries(
        Object.keys(total).map((k) => [k, total[k] + period[k]]),
      );
      return { ...total };
    });
    renderCurrent();
    if (!first && !silent) toast("已重新读取计算结果");
  } catch (error) {
    toast(error.message);
    if (!state.data) {
      $("kpis").innerHTML =
        `<div class="error-screen">${esc(error.message)}。请启动调度服务后刷新此页。</div>`;
      $("generated").textContent = "结果读取失败";
    } else {
      document.querySelector(".mode-badge").textContent = "更新暂不可用 · 保留上一结果参考";
    }
  } finally {
    $("refresh").disabled = false;
  }
}
$("time-range").addEventListener("input", (e) => {
  stop();
  setIndex(Number(e.target.value));
});
$("play").addEventListener("click", () => {
  if (!state.data) return;
  if (state.timer) {
    stop();
    return;
  }
  $("play").textContent = "Ⅱ";
  $("play").setAttribute("aria-label", "暂停回放");
  state.timer = setInterval(() => {
    if (state.index === lastIndex()) {
      stop();
      return;
    }
    setIndex(state.index + 1);
  }, 500);
  if (state.index === lastIndex()) setIndex(0);
});
$("main-chart").addEventListener("pointermove", (e) => {
  if (!state.data || state.timer || e.pointerType === "touch") return;
  const rect = e.currentTarget.getBoundingClientRect(),
    index = Math.round(((e.clientX - rect.left - 48) / (rect.width - 66)) * lastIndex());
  if (index !== state.index && index >= 0 && index <= lastIndex()) setIndex(index);
});
$("main-chart").addEventListener("click", (e) => {
  const rect = e.currentTarget.getBoundingClientRect();
  stop();
  setIndex(((e.clientX - rect.left - 48) / (rect.width - 66)) * lastIndex());
});
document
  .querySelectorAll("[data-mode]")
  .forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
$("reset-station").addEventListener("click", () => setMode("stations"));
$("station-prices").addEventListener("click", () => {
  if (!state.data) return;
  state.prices = !state.prices;
  renderStations();
});
const priceFields = ["gen_cost_yuan_per_kwh", "buy_price_yuan_per_kwh"];
const priceCodes = ["GARD", "JFRD", "JQRD", "JXRD", "JYRD", "SZRD", "WLRD"];
const priceEditor = { snapshot: null, busy: false, needsReload: true };
function priceControls() {
  $("price-fields").disabled = priceEditor.busy || !priceEditor.snapshot;
  $("price-save").disabled = priceEditor.busy || priceEditor.needsReload || !priceEditor.snapshot;
  $("price-reload").disabled = priceEditor.busy || location.protocol === "file:";
  $("price-close").disabled = priceEditor.busy;
}
function showPriceMessage(message, error = false) {
  $("price-message").textContent = message;
  $("price-message").classList.toggle("price-error", error);
}
function displayPriceSnapshot(snapshot) {
  if (!Number.isSafeInteger(snapshot.version) || snapshot.version < 0 ||
      !Array.isArray(snapshot.stations) || snapshot.stations.length !== 7 ||
      new Set(snapshot.stations.map(s => s.code)).size !== 7 ||
      snapshot.stations.some(s => !priceCodes.includes(s.code) ||
        priceFields.some(k => typeof s[k] !== "number" || !Number.isFinite(s[k]) || s[k] <= 0))) {
    throw new Error("价格响应不完整，请重新读取；当前不能保存。");
  }
  priceEditor.snapshot = snapshot;
  $("price-version").textContent = `配置版本 ${snapshot.version} · ${snapshot.updated_at || "初始配置"}`;
  $("price-inputs").innerHTML = priceCodes.map(code => {
    const row = snapshot.stations.find(s => s.code === code);
    const station = state.data?.stations.find(s => s.name.toUpperCase() === code);
    return `<tr><th>${esc(station?.label || code)}<small>${code}</small></th>${priceFields.map((key, i) =>
      `<td><input type="number" step="any" required data-code="${code}" data-price="${key}" value="${row[key]}" aria-label="${code} ${i ? "购电价" : "发电成本"}（元/kWh）"></td>`).join("")}</tr>`;
  }).join("");
  priceEditor.needsReload = false;
}
async function priceRequest(method, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch("/api/v1/fluxcast/config/prices", {
      method, cache: "no-store", signal: controller.signal,
      headers: { "Accept": "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : `请求失败（${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return data;
  } finally {
    clearTimeout(timeout);
  }
}
async function readEditorPrices() {
  if (priceEditor.busy) return;
  priceEditor.needsReload = true;
  priceEditor.snapshot = null;
  $("price-inputs").replaceChildren();
  $("price-version").textContent = "尚未读取当前配置";
  if (location.protocol === "file:") {
    showPriceMessage("离线文件不能修改服务价格，请从已部署服务的展示页打开。", true);
    priceControls();
    return;
  }
  priceEditor.busy = true;
  priceControls();
  showPriceMessage("正在读取当前价格…");
  try {
    displayPriceSnapshot(await priceRequest("GET"));
    showPriceMessage("已读取当前配置，可编辑后保存全部14项价格。");
  } catch (error) {
    showPriceMessage(`读取失败，不能保存。${error.message} 请重试或检查服务连接。`, true);
  } finally {
    priceEditor.busy = false;
    priceControls();
  }
}
$("edit-prices").addEventListener("click", () => {
  stop();
  $("price-dialog").showModal();
  readEditorPrices();
});
$("price-close").addEventListener("click", () => $("price-dialog").close());
$("price-dialog").addEventListener("cancel", e => {
  if (priceEditor.busy) e.preventDefault();
});
$("price-reload").addEventListener("click", readEditorPrices);
$("price-fields").addEventListener("input", e => e.target.setCustomValidity?.(""));
$("price-form").addEventListener("submit", async e => {
  e.preventDefault();
  if (priceEditor.busy || priceEditor.needsReload || !priceEditor.snapshot) return;
  const stations = priceCodes.map(code => ({ code }));
  for (const input of $("price-inputs").querySelectorAll("input")) {
    const value = input.valueAsNumber;
    if (!Number.isFinite(value) || value <= 0) {
      input.setCustomValidity("请输入大于0的有效价格，单位元/kWh");
      input.reportValidity();
      return;
    }
    stations.find(s => s.code === input.dataset.code)[input.dataset.price] = value;
  }
  priceEditor.busy = true;
  priceControls();
  showPriceMessage("正在保存，请稍候…");
  try {
    displayPriceSnapshot(await priceRequest("PUT", {
      expected_version: priceEditor.snapshot.version, stations,
    }));
    showPriceMessage("保存成功，新建调度断面将使用此价格；当前历史试算展示保持不变。");
  } catch (error) {
    priceEditor.needsReload = true;
    showPriceMessage(error.status === 409
      ? "价格已被其他人修改，本次未保存。请先记录需要保留的编辑，再点击“重新读取”核对最新价格后保存。"
      : error.status === 422 || error.status === 400
        ? `本次未保存：${error.message} 请重新读取并核对价格。`
        : "未收到保存成功确认，当前输入已保留。请重新读取，核对服务器价格后再保存，避免重复覆盖。", true);
  } finally {
    priceEditor.busy = false;
    priceControls();
  }
});
function chooseStation(e) {
  const row = e.target.closest("[data-station]");
  if (row) setMode("stations", row.dataset.station);
}
$("station-rows").addEventListener("click", chooseStation);
$("station-rows").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    chooseStation(e);
  }
});
$("refresh").addEventListener("click", () => load());
$("export").addEventListener("click", () => {
  if (!state.data) return;
  const rows = state.data.rows,
    keys = Object.keys(rows[0]);
  const quote = (v) => '"' + String(v).replace(/"/g, '""') + '"';
  const content =
    "\ufeff" +
    [
      keys.map(quote).join(","),
      ...rows.map((r) => keys.map((k) => quote(r[k])).join(",")),
    ].join("\r\n");
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `七站${"单断面离线试算_非执行指令"}_${state.data.snapshotId || state.data.summary.loadDay}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast(`已导出${rows.length}时段${"独立试算明细，不作为执行指令"}`);
});
function updateZoomButton(panel, expanded) {
  const button = panel.querySelector(".panel-zoom");
  if (button) {
    button.textContent = expanded ? "×" : "⛶";
    button.setAttribute(
      "aria-label",
      expanded
        ? "还原面板"
        : `放大${panel.querySelector("h2, .kpi-label")?.textContent || "面板"}`,
    );
  }
}
function closePanel() {
  const panel = state.expanded;
  if (!panel) return;
  panel.classList.remove("is-expanded");
  panel.removeAttribute("role");
  panel.removeAttribute("aria-modal");
  state.expanded = null;
  $("panel-backdrop").hidden = true;
  $("zoom-controls").hidden = true;
  document.body.classList.remove("panel-open");
  updateZoomButton(panel, false);
  panel.querySelector(".panel-zoom")?.focus();
}
document.querySelectorAll(".renewable-panel").forEach((panel, i) => {
  panel.id ||= `panel-${i}`;
  const button = document.createElement("button");
  button.className = "panel-zoom";
  button.title = "独立放大";
  panel.querySelector(".panel-head").append(button);
  updateZoomButton(panel, false);
});
document.addEventListener("click", (e) => {
  const button = e.target.closest(".panel-zoom");
  if (!button) return;
  const panel = button.closest(".panel, .kpi");
  if (state.expanded === panel) {
    closePanel();
    return;
  }
  closePanel();
  state.expanded = panel;
  panel.classList.add("is-expanded");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  $("panel-backdrop").hidden = false;
  $("zoom-controls").hidden = false;
  document.body.classList.add("panel-open");
  updateZoomButton(panel, true);
  button.focus();
});
$("panel-backdrop").addEventListener("click", closePanel);
$("zoom-close").addEventListener("click", closePanel);
$("zoom-prev").addEventListener("click", () => {
  stop();
  setIndex(state.index - 1);
});
$("zoom-next").addEventListener("click", () => {
  stop();
  setIndex(state.index + 1);
});
$("zoom-range").addEventListener("input", (e) => {
  stop();
  setIndex(Number(e.target.value));
});
document.addEventListener("keydown", (e) => {
  if (!state.expanded) return;
  if (e.key === "Escape") {
    e.preventDefault();
    closePanel();
  }
  if (e.key === "Tab") {
    const nodes = [
      ...state.expanded.querySelectorAll("button,input,[tabindex='0']"),
      ...$("zoom-controls").querySelectorAll("button,input"),
    ].filter((n) => n.getClientRects().length);
    const at = nodes.indexOf(document.activeElement);
    if (e.shiftKey && at <= 0) {
      e.preventDefault();
      nodes.at(-1)?.focus();
    } else if (!e.shiftKey && (at === nodes.length - 1 || at < 0)) {
      e.preventDefault();
      nodes[0]?.focus();
    }
  }
});
new ResizeObserver(() => drawChart()).observe($("main-chart"));
load();
setInterval(() => {
  if (state.data?.isSinglePeriod) return;
  if (!document.hidden && !state.timer && state.index === 0 && !$("refresh").disabled) load(true);
}, 30000);
