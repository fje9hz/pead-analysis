/* ═══════════════════════════════════════════════════════
   PEAD Research App — Frontend Logic
   ═══════════════════════════════════════════════════════ */

const API = '';  // same origin

// ── Chart instances (kept for destroy on re-render)
const charts = {};

// ── Color palette
const TEAL  = '#00C9A7';
const RED   = '#FF4757';
const WHITE = '#F2F2F2';
const CREAM = '#F5E6C8';
const MUTED = '#666677';
const DIM   = '#AAAAAA';
const YELLOW= '#FFD166';

const QUINTILE_COLORS = {
  'Large Miss': '#FF4757',
  'Miss':       '#FF8C69',
  'Inline':     '#666677',
  'Beat':       '#4FC3D4',
  'Large Beat': '#00C9A7',
};
const QUINTILE_ORDER = ['Large Miss', 'Miss', 'Inline', 'Beat', 'Large Beat'];

// ── Utility
const $ = id => document.getElementById(id);
const show = id => $( id)?.classList.remove('hidden');
const hide = id => $( id)?.classList.add('hidden');
const fmt_pct = v => v == null ? '—' : (v * 100).toFixed(1) + '%';
const fmt_num = (v, d=2) => v == null ? '—' : Number(v).toFixed(d);

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

// ── Chart.js global defaults
Chart.defaults.color = MUTED;
Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';
Chart.defaults.font.family = "'JetBrains Mono', 'Fira Code', monospace";
Chart.defaults.font.size = 11;

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// INIT
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function init() {
  populateYearSelects();
  await loadSelectOptions();
  await loadDataStatus();
  await loadMethodology();
  setupNavHighlight();

  $('explore-btn').addEventListener('click', runExplorer);
  $('signals-btn').addEventListener('click', loadSignals);
  $('bt-btn').addEventListener('click', runBacktest);
  $('ticker-input').addEventListener('keydown', e => { if (e.key === 'Enter') runExplorer(); });

  loadSignals();
}

async function loadDataStatus() {
  try {
    const res = await fetch(`${API}/api/data-status`);
    const d = await res.json();

    // Track globally so runExplorer can gate ticker search
    window._isRealData = d.is_real_data;
    window._hasRowLevelData = true;  // features.csv is now deployed with the image

    const el = $('hero-data-status');
    if (el) {
      el.textContent = d.is_real_data ? 'WRDS Data' : 'Demo Data';
      el.style.color = d.is_real_data ? '#00C9A7' : '#FFD166';
    }

    // Update finding banner if real data
    if (d.is_real_data) {
      // Load explorer data to get actual quintile numbers for the banner
      const exRes = await fetch(`${API}/api/pead-explorer`);
      const exData = await exRes.json();
      const q = exData.car_by_quintile || {};
      const beatPct = q['Large Beat']?.car_0_p60;
      const missPct = q['Large Miss']?.car_0_p60;
      if (beatPct != null && $('finding-beat-pct'))
        $('finding-beat-pct').textContent = `+${(beatPct * 100).toFixed(1)}%`;
      if (missPct != null && $('finding-miss-pct'))
        $('finding-miss-pct').textContent = `${(missPct * 100).toFixed(1)}%`;

      // Hide demo banners
      ['demo-banner-explorer', 'demo-banner-signals'].forEach(id => {
        const el = $(id);
        if (el) el.style.display = 'none';
      });
    }
  } catch(e) {
    console.warn('Could not load data status', e);
  }
}

function populateYearSelects() {
  const years = Array.from({ length: 14 }, (_, i) => 2010 + i);
  ['year-start', 'year-end'].forEach(id => {
    const sel = $(id);
    years.forEach(y => {
      const opt = document.createElement('option');
      opt.value = y;
      opt.textContent = y;
      sel.appendChild(opt);
    });
  });
  $('year-start').value = '2010';
  $('year-end').value = '2023';
}

async function loadSelectOptions() {
  try {
    const [tickerRes, sectorRes] = await Promise.all([
      fetch(`${API}/api/tickers`),
      fetch(`${API}/api/sectors`),
    ]);
    const { tickers } = await tickerRes.json();
    const { sectors } = await sectorRes.json();

    // Populate sector selects
    [  'sector-select', 'signal-sector-select'].forEach(id => {
      const sel = $(id);
      sectors.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        sel.appendChild(opt);
      });
    });
  } catch (e) {
    console.warn('Could not load select options:', e);
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// NAV HIGHLIGHT
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function setupNavHighlight() {
  const sections = ['explorer', 'signals', 'methodology'];
  const observer = new IntersectionObserver(
    entries => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
          const link = document.querySelector(`.nav-link[data-section="${e.target.id}"]`);
          if (link) link.classList.add('active');
        }
      });
    },
    { rootMargin: '-40% 0px -40% 0px' }
  );
  sections.forEach(id => { const el = $(id); if (el) observer.observe(el); });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SECTION 1: PEAD EXPLORER
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function runExplorer() {
  const ticker = $('ticker-input').value.trim().toUpperCase();
  const sector = $('sector-select').value;
  const startYear = $('year-start').value;
  const endYear = $('year-end').value;

  hide('summary-stats');
  hide('charts-area');
  hide('explorer-error');
  hide('explorer-info');

  // Ticker search requires row-level data not available in the deployed version
  if (ticker && window._isRealData && !window._hasRowLevelData) {
    hide('explorer-error');
    show('explorer-info');
    $('explorer-info').innerHTML =
      `<strong>ℹ️ Ticker-level history isn't available in the public deployment</strong> — the full event dataset isn't hosted for licensing reasons. ` +
      `Clear the ticker field and hit Run Analysis to explore the S&P 500 aggregate drift pattern, ` +
      `or scroll to <strong>Signal Dashboard</strong> to find ${ticker}'s beat probability.`;
    return;
  }
  hide('explorer-info');

  show('explorer-loading');

  const params = new URLSearchParams({ start_year: startYear, end_year: endYear });
  if (ticker) params.set('ticker', ticker);
  else if (sector) params.set('sector', sector);

  try {
    const res = await fetch(`${API}/api/pead-explorer?${params}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'API error');
    }
    const data = await res.json();
    hide('explorer-loading');
    renderExplorer(data);
  } catch (e) {
    hide('explorer-loading');
    show('explorer-error');
    $('explorer-error').textContent = `Error: ${e.message}`;
  }
}

function renderExplorer(data) {
  const { summary, timeline, car_by_quintile, note } = data;

  // Stats
  $('stat-events').textContent = summary.n_events?.toLocaleString() ?? '—';
  $('stat-beat-rate').textContent = fmt_pct(summary.beat_rate);
  $('stat-avg-surprise').textContent = summary.avg_surprise != null
    ? ((summary.avg_surprise > 0 ? '+' : '') + fmt_pct(summary.avg_surprise)) : '—';
  $('stat-avg-car60').textContent = summary.avg_car_0_60 != null
    ? ((summary.avg_car_0_60 > 0 ? '+' : '') + fmt_pct(summary.avg_car_0_60)) : '—';
  $('stat-analysts').textContent = summary.median_analysts != null
    ? Math.round(summary.median_analysts) : '—';

  show('summary-stats');
  show('charts-area');

  // Show ticker-level note when row-level data isn't available
  const noteEl = $('insight-car');
  if (note && noteEl) {
    noteEl.innerHTML = `ℹ️ ${note} The CAR chart below shows the S&P 500 aggregate drift pattern — individual event history isn't available in the deployed version.`;
    noteEl.classList.add('visible');
  }

  renderTimeline(timeline);
  renderCarByQuintile(car_by_quintile);
  renderWindowComparison(car_by_quintile);
  renderInsight(car_by_quintile);
}

function renderTimeline(timeline) {
  destroyChart('timeline');
  const ctx = $('timeline-chart').getContext('2d');

  const beats = timeline.filter(d => d.beat === 1);
  const misses = timeline.filter(d => d.beat === 0);

  const toPoint = d => ({
    x: d.anndats,
    y: +(d.surprise * 100).toFixed(2),
    label: d.ticker,
    actual: d.actual_eps,
    est: d.medest,
  });

  charts['timeline'] = new Chart(ctx, {
    type: 'scatter',
    data: {
      datasets: [
        {
          label: 'Beat',
          data: beats.map(toPoint),
          backgroundColor: 'rgba(0,201,167,0.55)',
          borderColor: 'rgba(0,201,167,0.85)',
          pointRadius: 3,
          pointHoverRadius: 5,
        },
        {
          label: 'Miss',
          data: misses.map(toPoint),
          backgroundColor: 'rgba(255,71,87,0.5)',
          borderColor: 'rgba(255,71,87,0.8)',
          pointRadius: 3,
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { color: MUTED, boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: items => items[0]?.raw?.x ?? '',
            label: item => {
              const d = item.raw;
              return [
                `${d.label}: ${item.parsed.y > 0 ? '+' : ''}${item.parsed.y.toFixed(1)}% surprise`,
                `Actual EPS: $${d.actual}  Est: $${d.est}`,
              ];
            },
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: 'year', tooltipFormat: 'MMM yyyy' },
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: MUTED, font: { size: 10 } },
        },
        y: {
          title: { display: true, text: 'Earnings Surprise (%)', color: MUTED, font: { size: 10 } },
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: MUTED, font: { size: 10 }, callback: v => v + '%' },
        },
      },
    },
  });
}

function renderCarByQuintile(car_by_quintile) {
  destroyChart('car');
  const ctx = $('car-chart').getContext('2d');

  const PLAIN_LABELS = {
    'Large Miss': 'Badly Missed',
    'Miss':       'Missed',
    'Inline':     'In Line',
    'Beat':       'Beat',
    'Large Beat': 'Crushed It',
  };
  const labels = QUINTILE_ORDER.filter(q => car_by_quintile[q]);
  const plainLabels = labels.map(q => PLAIN_LABELS[q] || q);
  const values = labels.map(q => {
    const v = car_by_quintile[q]?.car_0_p60;
    return v != null ? +(v * 100).toFixed(2) : 0;
  });
  const colors = labels.map(q => QUINTILE_COLORS[q] + 'CC');
  const borders = labels.map(q => QUINTILE_COLORS[q]);

  charts['car'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: plainLabels,
      datasets: [{
        label: 'Avg 60-Day Drift (%)',
        data: values,
        backgroundColor: colors,
        borderColor: borders,
        borderWidth: 1.5,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: item => `${item.parsed.y > 0 ? '+' : ''}${item.parsed.y.toFixed(2)}%` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: MUTED, font: { size: 10 } } },
        y: {
          title: { display: true, text: 'Avg CAR [0, +60] (%)', color: MUTED, font: { size: 10 } },
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: MUTED, font: { size: 10 }, callback: v => v + '%' },
        },
      },
    },
  });
}

function renderInsight(car_by_quintile) {
  const el = $('insight-car');
  if (!el) return;
  if (el.classList.contains('visible')) return;  // already set by note
  const beat = car_by_quintile['Large Beat'];
  const miss = car_by_quintile['Large Miss'];
  if (!beat && !miss) return;

  const beatPct = beat?.car_0_p60 != null ? `+${(beat.car_0_p60 * 100).toFixed(1)}%` : null;
  const missPct = miss?.car_0_p60 != null ? `${(miss.car_0_p60 * 100).toFixed(1)}%` : null;
  const beatImm = beat?.car_m1_p1 != null ? `+${(beat.car_m1_p1 * 100).toFixed(1)}%` : null;

  let text = '📌 <strong>What this means in plain English:</strong> ';
  if (beatPct && missPct) {
    text += `Stocks that crushed analyst expectations drifted <strong>${beatPct}</strong> above the market over 60 days. `;
    text += `Stocks that badly missed fell <strong>${missPct}</strong>. `;
  }
  if (beatImm && beat?.car_0_p60 != null) {
    const delayed = (beat.car_0_p60 * 100).toFixed(1);
    const immediate = (beat.car_m1_p1 * 100).toFixed(1);
    text += `Of the ${beatPct} total drift for big beats, only <strong>${beatImm}</strong> happened on earnings day itself — the rest built up gradually over the following weeks. That delayed reaction is PEAD.`;
  }

  el.innerHTML = text;
  el.classList.add('visible');
}

function renderWindowComparison(car_by_quintile) {
  destroyChart('window');
  const ctx = $('window-chart').getContext('2d');

  const labels = QUINTILE_ORDER.filter(q => car_by_quintile[q]);
  const windows = ['car_m1_p1', 'car_0_p30', 'car_0_p60'];
  const windowLabels = ['Day [-1,+1]', 'Day [0,+30]', 'Day [0,+60]'];
  const windowColors = ['rgba(255,209,102,0.7)', 'rgba(79,195,212,0.7)', 'rgba(0,201,167,0.7)'];

  charts['window'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: windows.map((w, i) => ({
        label: windowLabels[i],
        data: labels.map(q => {
          const v = car_by_quintile[q]?.[w];
          return v != null ? +(v * 100).toFixed(2) : 0;
        }),
        backgroundColor: windowColors[i],
        borderRadius: 3,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: MUTED, boxWidth: 10, font: { size: 10 } } },
        tooltip: { callbacks: { label: item => `${item.dataset.label}: ${item.parsed.y > 0 ? '+' : ''}${item.parsed.y.toFixed(2)}%` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: MUTED, font: { size: 9 } } },
        y: {
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: MUTED, font: { size: 10 }, callback: v => v + '%' },
        },
      },
    },
  });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SECTION 2: SIGNAL DASHBOARD
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function loadSignals() {
  const sector = $('signal-sector-select').value;
  hide('signals-table-wrap');
  hide('signals-error');
  show('signals-loading');

  const params = new URLSearchParams({ n: 60 });
  if (sector) params.set('sector', sector);

  try {
    const res = await fetch(`${API}/api/signal-dashboard?${params}`);
    if (!res.ok) throw new Error('API error');
    const data = await res.json();
    hide('signals-loading');
    renderSignals(data.signals);
  } catch (e) {
    hide('signals-loading');
    show('signals-error');
    $('signals-error').textContent = `Error loading signals: ${e.message}`;
  }
}

function renderSignals(signals) {
  const tbody = $('signals-tbody');
  tbody.innerHTML = '';

  signals.forEach(s => {
    const prob = s.beat_prob ?? 0.5;
    const pct = Math.round(prob * 100);
    const fillColor = prob >= 0.65 ? TEAL : prob <= 0.35 ? RED : MUTED;
    const pillClass = s.signal === 'likely_beat' ? 'beat' : s.signal === 'likely_miss' ? 'miss' : 'uncertain';
    const pillText = s.signal === 'likely_beat' ? 'Likely Beat' : s.signal === 'likely_miss' ? 'Likely Miss' : 'Uncertain';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="ticker-cell">${s.ticker ?? '—'}</td>
      <td>${s.sector ?? '—'}</td>
      <td>${s.anndats ?? '—'}</td>
      <td>
        <div class="prob-bar-wrap">
          <div class="prob-bar">
            <div class="prob-bar-fill" style="width:${pct}%;background:${fillColor}"></div>
          </div>
          <span class="prob-num" style="color:${fillColor}">${pct}%</span>
        </div>
      </td>
      <td style="color:var(--text-muted)">${s.confidence != null ? Math.round(s.confidence * 100) + '%' : '—'}</td>
      <td>${s.numest != null ? Math.round(s.numest) : '—'}</td>
      <td style="color:var(--text-muted)">${s.mkcap_quintile ?? '—'}</td>
      <td><span class="signal-pill signal-pill--${pillClass}">${pillText}</span></td>
    `;
    tbody.appendChild(tr);
  });

  show('signals-table-wrap');
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SECTION 3: METHODOLOGY
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function loadMethodology() {
  try {
    const res = await fetch(`${API}/api/methodology`);
    if (!res.ok) throw new Error('API error');
    const data = await res.json();
    hide('methodology-loading');
    renderMethodology(data);
  } catch (e) {
    hide('methodology-loading');
    console.error('Methodology load failed:', e);
  }
}

function renderMethodology(data) {
  const texts = data.methodology_text ?? {};

  $('text-what-is-pead').textContent = texts.what_is_pead ?? '';
  $('text-why').textContent = texts.why_it_happens ?? '';
  $('text-data').textContent = texts.data_sources ?? '';
  $('text-surprise').textContent = texts.earnings_surprise ?? '';
  $('text-car').textContent = texts.car_calculation ?? '';
  $('text-ml').textContent = texts.ml_model ?? '';
  $('text-disclaimer').textContent = texts.disclaimer ?? '';

  // Metrics grid
  const m = data.metrics ?? {};
  const metricsGrid = $('metrics-grid');
  const metricItems = [
    { label: 'ROC AUC', value: m.roc_auc != null ? m.roc_auc.toFixed(3) : '—' },
    { label: 'Accuracy', value: m.accuracy != null ? (m.accuracy * 100).toFixed(1) + '%' : '—' },
    { label: 'Precision', value: m.precision != null ? (m.precision * 100).toFixed(1) + '%' : '—' },
    { label: 'Recall', value: m.recall != null ? (m.recall * 100).toFixed(1) + '%' : '—' },
    { label: 'F1 Score', value: m.f1 != null ? m.f1.toFixed(3) : '—' },
    { label: 'Beat Rate', value: data.beat_rate != null ? (data.beat_rate * 100).toFixed(1) + '%' : '—' },
    { label: 'Observations', value: data.n_observations?.toLocaleString() ?? '—' },
    { label: 'Best Model', value: data.model_name ?? '—' },
  ];
  metricsGrid.innerHTML = metricItems.map(item => `
    <div class="metric-item">
      <div class="metric-label">${item.label}</div>
      <div class="metric-value">${item.value}</div>
    </div>
  `).join('');

  // Feature importance chart
  renderFeatureImportance(data.feature_importance ?? []);

  // Model comparison chart
  renderModelComparison(data);

  show('methodology-content');
}

function renderFeatureImportance(features) {
  destroyChart('feat');
  if (!features.length) return;

  const ctx = $('feat-chart').getContext('2d');
  const sorted = [...features].sort((a, b) => b.importance - a.importance);
  const labels = sorted.map(f => f.feature.replace(/_/g, ' '));
  const values = sorted.map(f => +(f.importance * 100).toFixed(1));

  charts['feat'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Importance (%)',
        data: values,
        backgroundColor: labels.map((_, i) => `rgba(0,201,167,${0.85 - i * 0.08})`),
        borderColor: TEAL,
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: item => `${item.parsed.x.toFixed(1)}%` } },
      },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: MUTED, font: { size: 10 }, callback: v => v + '%' },
        },
        y: { grid: { display: false }, ticks: { color: CREAM, font: { size: 11 } } },
      },
    },
  });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// BOOT
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SECTION 3: BACKTEST
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function runBacktest() {
  const quintile = $('bt-quintile').value;
  hide('bt-results');
  hide('bt-error');
  show('bt-loading');

  try {
    const res = await fetch(`${API}/api/backtest?quintile=${encodeURIComponent(quintile)}&hold_days=60`);
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'API error'); }
    const data = await res.json();
    hide('bt-loading');
    renderBacktest(data);
  } catch(e) {
    hide('bt-loading');
    show('bt-error');
    $('bt-error').textContent = `Error: ${e.message}`;
  }
}

function renderBacktest(data) {
  const sign = v => v >= 0 ? '+' : '';

  $('bt-n-trades').textContent   = data.n_trades?.toLocaleString() ?? '—';
  $('bt-total-return').textContent = data.total_return != null ? `${sign(data.total_return)}${(data.total_return*100).toFixed(1)}%` : '—';
  $('bt-cagr').textContent        = data.cagr != null ? `${sign(data.cagr)}${(data.cagr*100).toFixed(1)}%/yr` : '—';
  $('bt-avg-trade').textContent   = data.avg_trade_return != null ? `${sign(data.avg_trade_return)}${(data.avg_trade_return*100).toFixed(2)}%` : '—';
  $('bt-win-rate').textContent    = data.win_rate != null ? `${(data.win_rate*100).toFixed(1)}%` : '—';

  const isPositive = (data.total_return ?? 0) >= 0;
  $('bt-total-return').style.color = isPositive ? TEAL : RED;
  $('bt-cagr').style.color         = isPositive ? TEAL : RED;

  renderWealthChart(data.annual);
  renderBtAnnualChart(data.annual);
  renderAnnualBeatChart();

  show('bt-results');
}

function renderWealthChart(annual) {
  destroyChart('bt-wealth');
  const ctx = $('bt-wealth-chart').getContext('2d');
  const labels = annual.map(r => r.year);
  const wealth  = annual.map(r => +((r.cumulative_wealth - 1) * 100).toFixed(2));

  const color = (wealth[wealth.length - 1] ?? 0) >= 0 ? TEAL : RED;

  charts['bt-wealth'] = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Cumulative Return vs Market (%)',
        data: wealth,
        borderColor: color,
        backgroundColor: color.replace(')', ', 0.08)').replace('rgb', 'rgba').replace('#00C9A7', 'rgba(0,201,167,0.08)').replace('#FF4757','rgba(255,71,87,0.08)'),
        fill: true,
        tension: 0.35,
        pointRadius: 4,
        pointHoverRadius: 6,
      }, {
        label: 'Market Benchmark (0%)',
        data: labels.map(() => 0),
        borderColor: 'rgba(255,255,255,0.15)',
        borderDash: [4, 4],
        pointRadius: 0,
        fill: false,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: MUTED, boxWidth: 10, font: { size: 10 } } },
        tooltip: { callbacks: { label: item => `${item.dataset.label}: ${item.parsed.y >= 0 ? '+' : ''}${item.parsed.y.toFixed(2)}%` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: MUTED } },
        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: MUTED, callback: v => v + '%' } },
      },
    },
  });
}

function renderBtAnnualChart(annual) {
  destroyChart('bt-annual');
  const ctx = $('bt-annual-chart').getContext('2d');
  charts['bt-annual'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: annual.map(r => r.year),
      datasets: [{
        label: 'Avg Abnormal Return per Trade',
        data: annual.map(r => +((r.avg_return ?? 0) * 100).toFixed(2)),
        backgroundColor: annual.map(r => (r.avg_return ?? 0) >= 0 ? 'rgba(0,201,167,0.7)' : 'rgba(255,71,87,0.65)'),
        borderRadius: 3,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: item => `${item.parsed.y >= 0 ? '+' : ''}${item.parsed.y.toFixed(2)}%` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: MUTED, font: { size: 9 } } },
        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: MUTED, callback: v => v + '%' } },
      },
    },
  });
}

async function renderAnnualBeatChart() {
  destroyChart('annual-beat');
  try {
    const res = await fetch(`${API}/api/annual-trend`);
    const data = await res.json();
    const annual = data.annual ?? [];
    const ctx = $('annual-beat-chart').getContext('2d');
    charts['annual-beat'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: annual.map(r => r.year),
        datasets: [{
          label: 'Beat Rate',
          data: annual.map(r => +((r.beat_rate ?? 0) * 100).toFixed(1)),
          borderColor: YELLOW,
          backgroundColor: 'rgba(255,209,102,0.08)',
          fill: true,
          tension: 0.35,
          pointRadius: 4,
          pointHoverRadius: 6,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: item => `Beat Rate: ${item.parsed.y.toFixed(1)}%` } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: MUTED } },
          y: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: MUTED, callback: v => v + '%' },
            min: 50, max: 80,
          },
        },
      },
    });
  } catch(e) { console.warn('Could not load annual trend', e); }
}

// ── Model comparison chart (rendered inside methodology)
function renderModelComparison(metrics) {
  destroyChart('model-compare');
  const ctx = $('model-compare-chart');
  if (!ctx || !metrics.lr_metrics || !metrics.rf_metrics) return;

  const metricLabels = ['AUC', 'Accuracy', 'Precision', 'Recall', 'F1'];
  const metricKeys   = ['roc_auc', 'accuracy', 'precision', 'recall', 'f1'];

  charts['model-compare'] = new Chart(ctx.getContext('2d'), {
    type: 'bar',
    data: {
      labels: metricLabels,
      datasets: [
        {
          label: 'Logistic Regression',
          data: metricKeys.map(k => +((metrics.lr_metrics[k] ?? 0) * 100).toFixed(1)),
          backgroundColor: 'rgba(255,209,102,0.7)',
          borderRadius: 3,
        },
        {
          label: 'Random Forest ✓ Selected',
          data: metricKeys.map(k => +((metrics.rf_metrics[k] ?? 0) * 100).toFixed(1)),
          backgroundColor: 'rgba(0,201,167,0.75)',
          borderRadius: 3,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: MUTED, boxWidth: 10, font: { size: 10 } } },
        tooltip: { callbacks: { label: item => `${item.dataset.label}: ${item.parsed.y.toFixed(1)}%` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: MUTED } },
        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: MUTED, callback: v => v + '%' }, min: 50, max: 100 },
      },
    },
  });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
document.addEventListener('DOMContentLoaded', init);
