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
  await loadMethodology();
  setupNavHighlight();

  $('explore-btn').addEventListener('click', runExplorer);
  $('signals-btn').addEventListener('click', loadSignals);
  $('ticker-input').addEventListener('keydown', e => { if (e.key === 'Enter') runExplorer(); });

  // Auto-load signals on page load
  loadSignals();
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
  const { summary, timeline, car_by_quintile } = data;

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

  renderTimeline(timeline);
  renderCarByQuintile(car_by_quintile);
  renderWindowComparison(car_by_quintile);
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

  const labels = QUINTILE_ORDER.filter(q => car_by_quintile[q]);
  const values = labels.map(q => {
    const v = car_by_quintile[q]?.car_0_p60;
    return v != null ? +(v * 100).toFixed(2) : 0;
  });
  const colors = labels.map(q => QUINTILE_COLORS[q] + 'CC');
  const borders = labels.map(q => QUINTILE_COLORS[q]);

  charts['car'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
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
document.addEventListener('DOMContentLoaded', init);
