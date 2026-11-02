const appEl = document.getElementById('app');
const toastRegion = document.getElementById('toast-region');
const state = { user: null, page: 'dashboard', trips: [], dashboard: null, selectedTrip: null, photo: null, captureStamp: null, location: null, reviewId: null, loading: false, smsTrip: null, smsLink: null };

const escapeHtml = (value = '') => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[ch]));
const money = value => `₹${Number(value || 0).toLocaleString('en-IN')}`;
const fmtDate = value => value ? new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value)) : '—';
const fmtDateTime = value => value ? new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '—';
const statusText = status => ({ verified: 'Verified', needs_review: 'Needs review', retake_requested: 'Retake requested', missing: 'Missing POD', uploaded: 'Checking' }[status] || status);
const statusClass = status => ({ verified: 'verified', needs_review: 'review', retake_requested: 'retake', missing: 'missing', uploaded: 'uploaded' }[status] || 'missing');
const statusPill = status => `<span class="status status--${statusClass(status)}">${escapeHtml(statusText(status))}</span>`;

async function api(url, options = {}) {
  const init = { credentials: 'same-origin', ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) } };
  const response = await fetch(url, init);
  const type = response.headers.get('content-type') || '';
  const body = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const error = new Error(body?.detail || body?.message || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return body;
}
const post = (url, data = {}) => api(url, { method: 'POST', body: JSON.stringify(data) });

function toast(message, kind = 'ok') {
  const item = document.createElement('div');
  item.className = `toast ${kind === 'error' ? 'toast--error' : ''}`;
  item.textContent = message;
  toastRegion.append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function cachedUser() {
  try { return JSON.parse(localStorage.getItem('fleetpod-user') || 'null'); } catch { return null; }
}
function cacheTrips() { if (state.user?.role !== 'driver') return; try { localStorage.setItem('fleetpod-trips', JSON.stringify(state.trips)); } catch {} }
function readCachedTrips() { try { return JSON.parse(localStorage.getItem('fleetpod-trips') || '[]'); } catch { return []; } }

async function boot() {
  const path = window.location.pathname;
  if (path.startsWith('/share/')) return renderShare(path.split('/')[2]);
  if (path.startsWith('/upload/')) return renderSmsUpload(path.split('/')[2]);
  try {
    state.user = await api('/api/me');
    if (state.user.role === 'driver') localStorage.setItem('fleetpod-user', JSON.stringify(state.user));
    else localStorage.removeItem('fleetpod-user');
    await loadTrips();
    if (state.user.role === 'billing') await loadDashboard();
    state.page = state.user.role === 'driver' ? 'capture' : 'dashboard';
    await renderApp();
  } catch (error) {
    const user = cachedUser();
    if (!navigator.onLine && user) {
      state.user = user;
      state.trips = readCachedTrips();
      state.page = user.role === 'driver' ? 'capture' : 'dashboard';
      renderApp();
      return;
    }
    renderLogin();
  }
  updateOfflineBadge();
  flushOfflineQueue();
}

async function loadTrips() {
  state.trips = await api('/api/trips');
  cacheTrips();
}
async function loadDashboard() {
  state.dashboard = await api('/api/dashboard');
}

function renderLogin(errorText = '') {
  appEl.innerHTML = `
    <main class="login-screen">
      <section class="login-art" aria-label="FleetPOD product introduction">
        <div class="brand"><div class="brand-mark" aria-hidden="true">↗</div><div><div class="brand-name">FLEETPOD</div><div class="brand-subtitle">Proof, from the gate</div></div></div>
        <div class="login-message"><div class="eyebrow">Delivery proof, in the same trip</div><h1>Close the gap between <span>delivery</span> and billing.</h1><p>Capture a signed POD at the destination. Check it while the truck is still there. Keep every verified trip ready for billing.</p></div>
        <div class="login-foot">A secure operations workspace · Demo data only</div>
      </section>
      <section class="login-panel">
        <form class="login-card" id="login-form">
          <div class="eyebrow">Welcome back</div><h2>Sign in to FleetPOD</h2><p>Use a demo role to explore the delivery and billing flow.</p>
          <div class="login-fields">
            <label class="field"><span class="field-label">Work email</span><input class="input" name="email" type="email" autocomplete="username" required value="billing@fleetpod.demo" /></label>
            <label class="field"><span class="field-label">Password</span><input class="input" name="password" type="password" autocomplete="current-password" required value="BillingDemo26!" /></label>
          </div>
          ${errorText ? `<div class="login-error" role="alert">${escapeHtml(errorText)}</div>` : ''}
          <button class="button login-submit" type="submit">Sign in <span aria-hidden="true">→</span></button>
          <div class="demo-accounts"><p>DEMO ACCESS</p>
            <button class="demo-account" type="button" data-demo="billing"><span><strong>Billing executive</strong> · review and invoice queue</span><span>↗</span></button>
            <button class="demo-account" type="button" data-demo="driver"><span><strong>Driver</strong> · POD capture and retake</span><span>↗</span></button>
          </div>
        </form>
      </section>
    </main>`;
  document.getElementById('login-form').addEventListener('submit', onLogin);
  appEl.querySelectorAll('[data-demo]').forEach(button => button.addEventListener('click', () => {
    const driver = button.dataset.demo === 'driver';
    document.querySelector('[name=email]').value = driver ? 'driver@fleetpod.demo' : 'billing@fleetpod.demo';
    document.querySelector('[name=password]').value = driver ? 'DriverDemo26!' : 'BillingDemo26!';
    document.getElementById('login-form').requestSubmit();
  }));
}

async function onLogin(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const button = event.currentTarget.querySelector('button[type=submit]');
  button.disabled = true; button.textContent = 'Signing in…';
  try {
    state.user = await post('/api/login', { email: form.get('email'), password: form.get('password') });
    if (state.user.role === 'driver') localStorage.setItem('fleetpod-user', JSON.stringify(state.user));
    else localStorage.removeItem('fleetpod-user');
    await loadTrips();
    if (state.user.role === 'billing') await loadDashboard();
    state.page = state.user.role === 'driver' ? 'capture' : 'dashboard';
    await renderApp();
  } catch (error) {
    renderLogin(error.message);
  }
}

function navItem(page, icon, label, badge = '') {
  const active = state.page === page ? 'aria-current="page"' : '';
  return `<button class="nav-link" ${active} data-nav="${page}"><span class="nav-icon" aria-hidden="true">${icon}</span><span>${label}</span>${badge ? `<span class="nav-badge">${badge}</span>` : ''}</button>`;
}

async function renderApp() {
  if (!state.user) return renderLogin();
  const billing = state.user.role === 'billing';
  const title = ({ dashboard: 'Operations overview', capture: 'Driver capture', review: 'POD review', billing: 'Billing queue' }[state.page] || 'FleetPOD');
  let content = '<div class="loading-state"><span class="spinner"></span>Loading your workspace…</div>';
  appEl.innerHTML = shell(title, content);
  bindShell();
  try {
    if (state.page === 'dashboard') {
      if (!state.dashboard) await loadDashboard();
      content = renderDashboard();
    } else if (state.page === 'capture') content = renderCapture();
    else if (state.page === 'review') content = await renderReview();
    else if (state.page === 'billing') content = await renderBilling();
    else content = renderDashboard();
  } catch (error) {
    content = `<section class="card"><div class="empty"><div class="empty-icon">⚠</div><strong>Could not load this view</strong><p>${escapeHtml(error.message)}</p><button class="button button--ghost button--small" data-action="retry">Try again</button></div></section>`;
  }
  const contentNode = appEl.querySelector('#content');
  if (contentNode) contentNode.innerHTML = content;
  bindContent();
  updateOfflineBadge();
}

function shell(title, content) {
  const billing = state.user.role === 'billing';
  const reviewCount = state.trips.filter(t => ['needs_review','retake_requested'].includes(t.status)).length;
  return `<div class="layout">
    <aside class="sidebar" aria-label="Main navigation">
      <div class="brand"><div class="brand-mark" aria-hidden="true">↗</div><div><div class="brand-name">FLEETPOD</div><div class="brand-subtitle">Proof, from the gate</div></div></div>
      <div class="workspace-label">Workspace</div>
      <nav class="nav-list ${billing ? 'nav-list--billing' : 'nav-list--driver'}" aria-label="Workspace">
        ${billing ? navItem('dashboard','◫','Overview') : ''}
        ${!billing ? navItem('capture','▣','My trips') : ''}
        ${billing ? navItem('review','◎','POD review', reviewCount ? String(reviewCount) : '') : ''}
        ${billing ? navItem('billing','↗','Billing queue') : ''}
      </nav>
      <div class="sidebar-bottom">
        <div class="status-note"><strong>Proof stays the source</strong><p>AI checks the photo. People resolve uncertainty and approve invoices.</p></div>
        <div class="user-chip"><div class="avatar" aria-hidden="true">${escapeHtml(state.user.name.split(' ').map(n => n[0]).slice(0,2).join('').toUpperCase())}</div><div><div class="user-name">${escapeHtml(state.user.name)}</div><div class="user-role">${escapeHtml(state.user.role)}</div></div><button class="logout" type="button" aria-label="Sign out" title="Sign out" data-action="logout">↗</button></div>
      </div>
    </aside>
    <main class="main">
      <header class="topbar"><div><div class="eyebrow">Company A · Operations</div><div class="page-title">${title}</div></div><div class="top-actions"><div class="live-pill"><span class="live-dot"></span><span>${navigator.onLine ? 'Workspace live' : 'Offline mode'}</span></div><div class="date-label">${new Intl.DateTimeFormat('en-IN',{weekday:'short',day:'2-digit',month:'short'}).format(new Date())}</div><button class="icon-button mobile-signout" type="button" aria-label="Sign out" title="Sign out" data-action="logout">↗</button></div></header>
      <div class="content" id="content">${content}</div>
    </main>
  </div><input id="pod-file" type="file" accept="image/*" capture="environment" class="hidden" aria-label="Photograph or choose a proof-of-delivery image" /><div id="offline-badge" class="offline-queue hidden" role="status"></div>`;
}

function renderDashboard() {
  const d = state.dashboard || { total_trips: 0, without_pod: 0, review_count: 0, verified_count: 0, avg_delivery_to_pod_days: null, avg_pod_to_invoice_days: null, branches: {}, missing_trips: [] };
  const rows = d.missing_trips || [];
  const maxBranch = Math.max(1, ...Object.values(d.branches || {}).map(item => item.trips));
  return `<section class="page-heading"><div><h1>Good evening, ${escapeHtml(state.user.name.split(' ')[0])}</h1><p>Proof is moving closer to the delivery gate. Here’s what needs attention across today’s trips.</p></div><div class="heading-actions"><button class="button button--ghost" data-nav="review">Review PODs <span aria-hidden="true">→</span></button><button class="button" data-nav="billing">Open billing queue <span aria-hidden="true">↗</span></button></div></section>
    <section class="grid stats-grid" aria-label="Operations summary">
      <article class="card stat-card accent-gold"><div class="stat-label">Trips without a verified POD</div><div class="stat-value">${d.without_pod}</div><div class="stat-foot">${d.review_count} need review or retake</div></article>
      <article class="card stat-card accent-green"><div class="stat-label">Verified and ready</div><div class="stat-value">${d.verified_count}</div><div class="stat-foot">Across ${d.total_trips} sample trips</div></article>
      <article class="card stat-card accent-blue"><div class="stat-label">Delivery → POD</div><div class="stat-value">${d.avg_delivery_to_pod_days ?? '—'}<span style="font-size:14px;color:#8893a1"> days</span></div><div class="stat-foot">Average for trips with a POD</div></article>
      <article class="card stat-card accent-purple"><div class="stat-label">POD → invoice</div><div class="stat-value">${d.avg_pod_to_invoice_days ?? '—'}<span style="font-size:14px;color:#8893a1"> days</span></div><div class="stat-foot">Human-marked invoice exports</div></article>
    </section>
    <section class="grid dashboard-grid">
      <article class="card"><div class="card-head"><div><h2>Trips to follow up</h2><p>Missing proof, retakes, and items waiting for a person</p></div><button class="text-link" data-nav="review">Open review queue →</button></div>
        ${rows.length ? `<div class="table-wrap"><table><thead><tr><th>Trip / client</th><th>Destination</th><th>Delivery</th><th>Status</th></tr></thead><tbody>${rows.slice(0,6).map(t=>`<tr><td><div class="row-title">${escapeHtml(t.id)}</div><div class="subtext">${escapeHtml(t.client)}</div></td><td>${escapeHtml(t.destination)}</td><td>${fmtDate(t.delivered_at)}</td><td>${statusPill(t.status)}</td></tr>`).join('')}</tbody></table></div>` : `<div class="empty"><div class="empty-icon accent-green">✓</div>All trips have a verified POD.</div>`}
      </article>
      <article class="card"><div class="card-head"><div><h2>By branch</h2><p>Trips needing proof or review</p></div><span class="accent-gold" aria-hidden="true">◌</span></div>
        <div class="branch-list">${Object.entries(d.branches || {}).map(([name, item])=>`<div class="branch-row"><div class="branch-name">${escapeHtml(name)}</div><div class="branch-count">${item.missing + item.review} / ${item.trips}</div><div class="progress" role="img" aria-label="${escapeHtml(name)}: ${item.missing + item.review} trips need attention out of ${item.trips}"><span style="width:${Math.max(4,((item.missing+item.review)/maxBranch)*100)}%"></span></div></div>`).join('')}</div>
        <div class="branch-legend"><span>Needs attention</span><span class="accent-gold">● &nbsp;Follow-up required</span></div>
      </article>
    </section>`;
}

function renderCapture() {
  const items = state.trips.filter(t => t.status !== 'verified');
  const selected = state.trips.find(t => t.id === state.selectedTrip);
  return `<section class="page-heading"><div><h1>One photo, and the trip keeps moving.</h1><p>Choose a trip, photograph the signed POD at the gate, then check the result before you leave.</p></div><div class="live-pill"><span class="live-dot"></span>Capture works offline</div></section>
    <div class="notice"><span class="notice-mark" aria-hidden="true">ⓘ</span><span>Photo time is saved automatically. Location is attached when you allow it. The image stays on this device until it is compressed under 300 KB and sent or queued.</span></div>
    <section class="capture-list" aria-label="Trips that need a POD">${items.length ? items.map(t=>`<article class="card capture-card"><div class="capture-info"><div class="trip-icon" aria-hidden="true">▣</div><div><h3>${escapeHtml(t.id)} <span style="color:#788291;font-weight:500">·</span> ${escapeHtml(t.destination)}</h3><p>${escapeHtml(t.client)} &nbsp;·&nbsp; ${escapeHtml(t.vehicle)} &nbsp;·&nbsp; LR ${escapeHtml(t.lr_number)}</p><div style="margin-top:8px">${statusPill(t.status)}</div></div></div><div class="capture-actions">${['missing','retake_requested'].includes(t.status) ? `<button class="button ${t.status === 'retake_requested' ? 'button--ghost' : ''}" data-capture="${escapeHtml(t.id)}"><span aria-hidden="true">▣</span> ${t.status === 'retake_requested' ? 'Retake POD' : 'Capture POD'}</button>` : `<span class="subtext">Billing review in progress</span>`}</div></article>`).join('') : `<div class="empty"><div class="empty-icon accent-green">✓</div>No trips are waiting for a POD.</div>`}</section>
    ${selected ? `<section class="capture-panel" aria-label="POD photo capture"><div class="camera-stage">${state.photo ? `<img src="${state.photo.preview}" alt="Selected POD photo preview" />` : `<div class="camera-placeholder"><strong aria-hidden="true">▣</strong>Photo preview will appear here</div>`}</div><div class="capture-copy"><div class="eyebrow">${escapeHtml(selected.id)} · ${escapeHtml(selected.destination)}</div><h2>${selected.status === 'retake_requested' ? 'Take a clearer photo' : 'Photograph the signed POD'}</h2><p>Keep the LR number, consignee stamp, delivered quantity, date, remarks and signature in frame.</p><button class="button capture-big" data-capture="${escapeHtml(selected.id)}"><span aria-hidden="true">▣</span>${state.photo ? 'Choose another photo' : 'Open camera'}</button><button class="button button--ghost capture-big" style="margin-top:8px" data-action="upload-photo" ${state.photo ? '' : 'disabled'}>${state.photo ? 'Send for check' : 'Choose a photo first'} <span aria-hidden="true">→</span></button><div class="lang-actions"><button class="lang-button" data-voice="hi" aria-label="Play Hindi capture instructions">🔊 हिन्दी</button><button class="lang-button" data-voice="mr" aria-label="Play Marathi capture instructions">🔊 मराठी</button></div><div class="upload-meta">${state.photo ? `<strong>${Math.round(state.photo.size/1024)} KB</strong> · Compressed photo · ${state.captureStamp ? fmtDateTime(state.captureStamp) : 'just now'}${state.location ? ` · GPS ${state.location.latitude.toFixed(3)}, ${state.location.longitude.toFixed(3)}` : ' · Location not available'}` : 'JPG photo · under 300 KB · GPS optional'}</div></div></section>` : ''}`;
}

async function renderReview() {
  const queue = await api('/api/review-queue');
  const selected = queue.find(t => t.id === state.reviewId) || queue[0];
  if (selected) state.reviewId = selected.id;
  return `<section class="page-heading"><div><h1>Check what needs a person.</h1><p>Shortage and damage remarks, unclear photos, and low confidence stay here. Edit fields against the original POD before approving.</p></div><div class="live-pill"><span class="live-dot" style="background:var(--oled-gold);box-shadow:0 0 12px rgba(255,215,0,.4)"></span>${queue.length} waiting</div></section>
    ${queue.length ? `<section class="review-list" aria-label="PODs waiting for review">${queue.map(t=>`<button class="card review-card" data-review-select="${escapeHtml(t.id)}" style="text-align:left;color:inherit"><div><h3>${escapeHtml(t.id)} <span style="color:#788291;font-weight:500">· ${escapeHtml(t.client)}</span></h3><p>${escapeHtml(t.remarks || 'Check the photo and extracted fields')}</p></div>${statusPill(t.status)}</button>`).join('')}</section>
    ${selected ? renderReviewDetail(selected) : ''}` : `<section class="card"><div class="empty"><div class="empty-icon accent-green">✓</div><strong>Review queue is clear</strong><p>Uncertain and exception PODs will show up here.</p></div></section>`}`;
}

function renderReviewDetail(t) {
  const a = t.ai_result || {};
  const confidence = Math.round((a.confidence || 0) * 100);
  const note = a.issues?.length ? a.issues.join(' · ') : (t.remarks || 'No machine reading is available. Review the image manually.');
  return `<section class="review-layout"><article class="card"><div class="card-head"><div><h2>Original POD</h2><p>The photo remains the source of truth</p></div><button class="icon-button" data-action="open-image" data-url="${escapeHtml(t.pod_url || '')}" aria-label="Open original POD photo in a new tab" title="Open image">↗</button></div>${t.pod_url ? `<img class="review-image" src="${escapeHtml(t.pod_url)}" alt="Original proof of delivery for ${escapeHtml(t.id)}" />` : `<div class="empty">No POD photo is attached.</div>`}<div class="subtext" style="margin-top:12px">Captured ${fmtDateTime(t.pod_at)} · LR ${escapeHtml(t.lr_number)}</div><div style="margin-top:10px"><button class="button button--ghost button--small" data-sms="${escapeHtml(t.id)}">Create mock SMS upload link</button>${state.smsTrip === t.id && state.smsLink ? `<div class="notice" style="margin-top:10px;margin-bottom:0"><span>Mock SMS link: <a href="${escapeHtml(state.smsLink)}">${escapeHtml(state.smsLink)}</a> <button class="text-link" data-copy="${escapeHtml(state.smsLink)}">Copy link</button></span></div>` : ''}</div></article>
    <article class="card"><div class="card-head"><div><h2>Extracted fields</h2><p>Correct anything the check got wrong</p></div><span class="ai-confidence">${a.confidence == null ? 'Manual' : `${confidence}%`}</span></div><div class="ai-note"><strong>AI check:</strong> ${escapeHtml(note)} ${a.confidence == null ? '<span>· Vision AI is unavailable, so this item needs a human check.</span>' : ''}</div>
      <form id="review-form" data-trip="${escapeHtml(t.id)}"><div class="field-grid">
        <label class="field"><span class="field-label">LR number</span><input class="input" name="lr_number" value="${escapeHtml(a.lr_number || t.lr_number)}" required /></label>
        <label class="field"><span class="field-label">Delivered quantity</span><input class="input" name="quantity_received" value="${escapeHtml(a.quantity_received || t.expected_qty)}" required /></label>
        <label class="field"><span class="field-label">Delivery date</span><input class="input" type="date" name="delivery_date" value="${escapeHtml(a.delivery_date || '')}" required /></label>
        <label class="toggle-field"><input type="checkbox" name="consignee_stamp_visible" ${a.consignee_stamp_visible ? 'checked' : ''} /> Consignee stamp is visible</label>
        <label class="toggle-field"><input type="checkbox" name="signature_visible" ${a.signature_visible ? 'checked' : ''} /> Consignee signature is visible</label>
        <label class="field span-two"><span class="field-label">Shortage or damage remarks</span><textarea class="textarea" name="shortage_or_damage_remarks" rows="2" placeholder="Nil">${escapeHtml(a.shortage_or_damage_remarks || (t.status === 'needs_review' ? t.remarks : ''))}</textarea></label>
        <label class="field span-two"><span class="field-label">Correction note (audit trail)</span><input class="input" name="correction_note" placeholder="Optional · why you changed a field" /></label>
      </div><div class="review-actions"><button class="button button--ghost" type="button" data-action="retake" data-trip="${escapeHtml(t.id)}">Request retake</button><button class="button" type="submit">Verify POD and release to billing <span aria-hidden="true">→</span></button></div></form>
    </article></section>`;
}

async function renderBilling() {
  const queue = await api('/api/billing-queue');
  return `<section class="page-heading"><div><h1>Ready for Tally.</h1><p>Only verified proof reaches this queue. Export a CSV with the POD image link, then mark the invoice when billing is done.</p></div><div class="heading-actions"><button class="button" data-action="export"><span aria-hidden="true">⇩</span> Export to Tally</button></div></section>
    <div class="notice"><span class="notice-mark" aria-hidden="true">ⓘ</span><span>Exporting creates a CSV for Tally; it does not send invoices to clients. Billing staff mark each invoice after it is posted.</span></div>
    <section class="card"><div class="card-head"><div><h2>Verified billing queue</h2><p>${queue.length} trip${queue.length===1?'':'s'} ready with attached proof</p></div><span class="accent-green">● Verified only</span></div>
    ${queue.length ? `<div class="table-wrap"><table class="billing-table"><thead><tr><th>Trip / client</th><th>LR + e-way bill</th><th>Freight</th><th>POD</th><th>Client link</th><th>Invoice</th></tr></thead><tbody>${queue.map(t=>`<tr><td><div class="row-title">${escapeHtml(t.id)}</div><div class="subtext">${escapeHtml(t.client)} · ${escapeHtml(t.destination)}</div></td><td><div>LR ${escapeHtml(t.lr_number)}</div><div class="subtext">${escapeHtml(t.eway_bill)}</div></td><td class="money">${money(t.freight)}</td><td>${t.pod_url ? `<a href="${escapeHtml(t.pod_url)}" target="_blank" rel="noopener">View POD ↗</a>` : '—'}<div class="subtext">${fmtDate(t.pod_at)}</div></td><td><button class="client-link" data-copy="${escapeHtml(window.location.origin + t.share_url)}">Copy client link ↗</button></td><td><button class="button button--ghost button--small" data-invoice="${escapeHtml(t.id)}">Mark invoiced</button></td></tr>`).join('')}</tbody></table></div>` : `<div class="empty"><div class="empty-icon accent-green">✓</div><strong>Billing queue is clear</strong><p>Verified trips appear here with their POD attached.</p></div>`}</section>
    <div class="subtext" style="margin-top:13px">The read-only client link shows this trip’s delivery status and POD image.</div>`;
}

function bindShell() {
  appEl.querySelectorAll('[data-nav]').forEach(button => button.addEventListener('click', async () => {
    state.page = button.dataset.nav;
    if (state.page === 'dashboard') await loadDashboard();
    await renderApp();
  }));
  appEl.querySelectorAll('[data-action=logout]').forEach(button => button.addEventListener('click', logout));
}
function bindContent() {
  appEl.querySelectorAll('[data-nav]').forEach(button => button.addEventListener('click', async () => {
    state.page = button.dataset.nav;
    if (state.page === 'dashboard') await loadDashboard();
    await renderApp();
  }));
  appEl.querySelectorAll('[data-capture]').forEach(button => button.addEventListener('click', () => {
    state.selectedTrip = button.dataset.capture;
    state.photo = null; state.location = null; state.captureStamp = null;
    appEl.querySelector('#pod-file').click();
  }));
  appEl.querySelector('#pod-file')?.addEventListener('change', onPhotoSelected);
  appEl.querySelector('[data-action=upload-photo]')?.addEventListener('click', uploadSelectedPhoto);
  appEl.querySelectorAll('[data-voice]').forEach(button => button.addEventListener('click', () => speak(button.dataset.voice)));
  appEl.querySelectorAll('[data-review-select]').forEach(button => button.addEventListener('click', async () => { state.reviewId = button.dataset.reviewSelect; await renderApp(); }));
  appEl.querySelector('#review-form')?.addEventListener('submit', submitReview);
  appEl.querySelector('[data-action=retake]')?.addEventListener('click', requestRetake);
  appEl.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', () => copyText(button.dataset.copy)));
  appEl.querySelectorAll('[data-invoice]').forEach(button => button.addEventListener('click', () => invoiceTrip(button.dataset.invoice)));
  appEl.querySelector('[data-action=export]')?.addEventListener('click', exportBilling);
  appEl.querySelector('[data-action=retry]')?.addEventListener('click', () => { if (state.page === 'dashboard') loadDashboard().then(renderApp); else renderApp(); });
  appEl.querySelector('[data-action=open-image]')?.addEventListener('click', event => window.open(event.currentTarget.dataset.url, '_blank', 'noopener'));
  appEl.querySelectorAll('[data-sms]').forEach(button => button.addEventListener('click', () => createSmsLink(button.dataset.sms)));
}

async function logout() {
  try { await post('/api/logout'); } catch {}
  state.user = null; state.trips = []; state.dashboard = null;
  localStorage.removeItem('fleetpod-user');
  renderLogin();
}

async function onPhotoSelected(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    const compressed = await compressImage(file);
    state.photo = compressed;
    state.captureStamp = new Date().toISOString();
    state.location = await getLocation();
    await renderApp();
  } catch (error) { toast(error.message || 'This photo could not be prepared.', 'error'); }
}

async function compressImage(file) {
  if (!file.type.startsWith('image/')) throw new Error('Choose an image file for the POD.');
  const bitmap = await createImageBitmap(file);
  let width = bitmap.width, height = bitmap.height;
  const maxSide = 1800;
  if (Math.max(width, height) > maxSide) { const scale = maxSide / Math.max(width, height); width = Math.round(width * scale); height = Math.round(height * scale); }
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  canvas.getContext('2d', { alpha: false }).drawImage(bitmap, 0, 0, width, height);
  bitmap.close();
  let quality = .78;
  let blob = await canvasBlob(canvas, quality);
  while (blob.size > 300_000 && quality > .38) { quality -= .1; blob = await canvasBlob(canvas, quality); }
  if (blob.size > 300_000) {
    const scaled = document.createElement('canvas');
    scaled.width = Math.max(1, Math.round(width * .68)); scaled.height = Math.max(1, Math.round(height * .68));
    scaled.getContext('2d', { alpha: false }).drawImage(canvas, 0, 0, scaled.width, scaled.height);
    blob = await canvasBlob(scaled, .4);
  }
  if (blob.size > 300_000) throw new Error('This photo is still over 300 KB. Try another photo in better light.');
  const dataUrl = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('Photo could not be read.')); reader.readAsDataURL(blob); });
  return { dataUrl, preview: URL.createObjectURL(blob), size: blob.size };
}
function canvasBlob(canvas, quality) { return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Photo compression failed.')), 'image/jpeg', quality)); }
function getLocation() { return new Promise(resolve => {
  if (!navigator.geolocation) return resolve(null);
  navigator.geolocation.getCurrentPosition(pos => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }), () => resolve(null), { enableHighAccuracy: false, timeout: 4500, maximumAge: 120000 });
}); }

async function uploadSelectedPhoto() {
  if (!state.photo || !state.selectedTrip) return;
  const payload = { image_data: state.photo.dataUrl, captured_at: state.captureStamp, latitude: state.location?.latitude ?? null, longitude: state.location?.longitude ?? null };
  if (!navigator.onLine) { await queueOffline(state.selectedTrip, payload); state.photo = null; toast('Saved on this device. It will send when you are back online.'); await renderApp(); return; }
  const button = appEl.querySelector('[data-action=upload-photo]');
  if (button) { button.disabled = true; button.textContent = 'Checking the POD…'; }
  try {
    const result = await post(`/api/trips/${encodeURIComponent(state.selectedTrip)}/pod`, payload);
    replaceTrip(result.trip); state.photo = null; state.captureStamp = null;
    toast(result.trip.status === 'verified' ? 'POD verified and added to billing.' : result.trip.status === 'retake_requested' ? result.trip.remarks : 'POD sent to a billing executive for review.');
    await renderApp();
  } catch (error) {
    if (!error.status || error.status >= 500) {
      await queueOffline(state.selectedTrip, payload); state.photo = null;
      toast('Connection lost. Photo saved here and queued for upload.');
      await renderApp();
    } else { toast(error.message, 'error'); if (button) { button.disabled = false; button.textContent = 'Send for check →'; } }
  }
}
function replaceTrip(trip) { state.trips = state.trips.map(old => old.id === trip.id ? trip : old); if (!state.trips.some(old => old.id === trip.id)) state.trips.unshift(trip); cacheTrips(); }
function speak(language) {
  if (!('speechSynthesis' in window)) return toast('Voice prompts are not supported on this device.', 'error');
  const text = language === 'mr' ? 'स्वाक्षरी केलेल्या पावतीचा स्पष्ट फोटो घ्या. क्रमांक, शिक्का आणि स्वाक्षरी चित्रात ठेवा.' : 'हस्ताक्षर और मुहर के साथ डिलीवरी रसीद की साफ़ तस्वीर लें। नंबर, मुहर और हस्ताक्षर फ्रेम में रखें।';
  const utterance = new SpeechSynthesisUtterance(text); utterance.lang = language === 'mr' ? 'mr-IN' : 'hi-IN'; window.speechSynthesis.cancel(); window.speechSynthesis.speak(utterance);
}

function dbOpen() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('fleetpod-offline', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('pending', { keyPath: 'id' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function queueOffline(tripId, payload) {
  const db = await dbOpen();
  await new Promise((resolve, reject) => { const tx = db.transaction('pending', 'readwrite'); tx.objectStore('pending').put({ id: crypto.randomUUID(), tripId, payload, queuedAt: new Date().toISOString() }); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); });
  db.close(); updateOfflineBadge();
}
async function getOfflineQueue() {
  const db = await dbOpen();
  const items = await new Promise((resolve, reject) => { const request = db.transaction('pending').objectStore('pending').getAll(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
  db.close(); return items;
}
async function removeOfflineItem(id) {
  const db = await dbOpen();
  await new Promise((resolve, reject) => { const tx = db.transaction('pending', 'readwrite'); tx.objectStore('pending').delete(id); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); });
  db.close();
}
async function flushOfflineQueue() {
  if (!navigator.onLine || !state.user) return updateOfflineBadge();
  let items;
  try { items = await getOfflineQueue(); } catch { return; }
  if (!items.length) return updateOfflineBadge();
  for (const item of items) {
    try { const result = await post(`/api/trips/${encodeURIComponent(item.tripId)}/pod`, item.payload); replaceTrip(result.trip); await removeOfflineItem(item.id); }
    catch (error) { if (error.status && error.status < 500) { await removeOfflineItem(item.id); toast(`Queued photo for ${item.tripId} needs a fresh capture: ${error.message}`, 'error'); } else break; }
  }
  updateOfflineBadge();
  if ((await getOfflineQueue()).length === 0) { toast('Queued PODs synced.'); if (state.page === 'capture') await renderApp(); }
}
async function updateOfflineBadge() {
  const badge = document.getElementById('offline-badge');
  if (!badge) return;
  let count = 0;
  try { count = (await getOfflineQueue()).length; } catch {}
  badge.textContent = `${count} POD${count === 1 ? '' : 's'} waiting to sync`;
  badge.classList.toggle('hidden', count === 0);
}

async function submitReview(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const payload = {
    action: 'verify', lr_number: values.get('lr_number'), quantity_received: values.get('quantity_received'), delivery_date: values.get('delivery_date'),
    consignee_stamp_visible: values.has('consignee_stamp_visible'), signature_visible: values.has('signature_visible'),
    shortage_or_damage_remarks: values.get('shortage_or_damage_remarks'), correction_note: values.get('correction_note'),
  };
  try { await post(`/api/trips/${encodeURIComponent(form.dataset.trip)}/review`, payload); toast('POD verified. It is now in the billing queue.'); state.reviewId = null; await loadTrips(); await loadDashboard(); await renderApp(); }
  catch (error) { toast(error.message, 'error'); }
}
async function requestRetake(event) {
  const tripId = event.currentTarget.dataset.trip;
  const form = document.getElementById('review-form');
  const values = new FormData(form);
  try {
    await post(`/api/trips/${encodeURIComponent(tripId)}/review`, { action: 'retake', lr_number: values.get('lr_number'), quantity_received: values.get('quantity_received'), delivery_date: values.get('delivery_date'), consignee_stamp_visible: values.has('consignee_stamp_visible'), signature_visible: values.has('signature_visible'), shortage_or_damage_remarks: values.get('shortage_or_damage_remarks'), correction_note: values.get('correction_note') });
    toast('Retake requested. The driver will see it on their trip list.'); await loadTrips(); await loadDashboard(); await renderApp();
  } catch (error) { toast(error.message, 'error'); }
}
async function invoiceTrip(tripId) {
  try { await post(`/api/trips/${encodeURIComponent(tripId)}/invoice`); toast(`${tripId} marked as invoiced.`); await loadDashboard(); await renderApp(); }
  catch (error) { toast(error.message, 'error'); }
}
async function exportBilling() {
  try {
    const response = await fetch('/api/billing/export.csv', { credentials: 'same-origin' });
    if (!response.ok) { const body = await response.json(); throw new Error(body.detail || 'Export failed'); }
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'fleetpod-tally-export.csv'; link.click(); URL.revokeObjectURL(url); toast('Tally CSV downloaded with a link to each POD image.');
  } catch (error) { toast(error.message, 'error'); }
}
async function createSmsLink(tripId) {
  try { const result = await post(`/api/trips/${encodeURIComponent(tripId)}/upload-link`); state.smsTrip = tripId; state.smsLink = window.location.origin + result.url; await renderApp(); toast('Mock upload link created. Copy it to simulate the SMS.'); }
  catch (error) { toast(error.message, 'error'); }
}
async function copyText(value) {
  try { await navigator.clipboard.writeText(value); toast('Link copied.'); }
  catch { window.prompt('Copy this link', value); }
}

async function renderShare(token) {
  try {
    const t = await api(`/api/share/${encodeURIComponent(token)}`);
    appEl.innerHTML = `<main class="share-shell"><header class="share-top"><div class="brand"><div class="brand-mark" aria-hidden="true">↗</div><div><div class="brand-name">FLEETPOD</div><div class="brand-subtitle">Client POD view</div></div></div><span class="live-pill">Read only</span></header><section class="card share-card"><div class="eyebrow">${escapeHtml(t.client)}</div><h1 style="font-size:28px;margin-top:7px">${escapeHtml(t.id)} <span style="color:#7d8795;font-size:17px">· ${escapeHtml(t.destination)}</span></h1><p>${statusPill(t.status)} <span style="margin-left:10px;color:#7d8795">LR ${escapeHtml(t.lr_number)} · E-way ${escapeHtml(t.eway_bill)}</span></p><p style="color:#8a95a4">POD received ${fmtDateTime(t.pod_at)}</p>${t.pod_url ? `<img src="${escapeHtml(t.pod_url)}" alt="Proof of delivery for ${escapeHtml(t.id)}" />` : `<div class="empty">POD image is not available yet.</div>`}<p class="subtext">This read-only link shows delivery proof for this trip only.</p></section></main>`;
  } catch (error) { appEl.innerHTML = `<main class="share-shell"><div class="card empty"><div class="empty-icon">ⓘ</div><strong>Link unavailable</strong><p>${escapeHtml(error.message)}</p></div></main>`; }
}

async function renderSmsUpload(token) {
  let trip;
  try { trip = await api(`/api/upload-link/${encodeURIComponent(token)}`); }
  catch (error) { appEl.innerHTML = `<main class="share-shell"><div class="card empty"><div class="empty-icon">ⓘ</div><strong>Upload link expired</strong><p>${escapeHtml(error.message)}</p></div></main>`; return; }
  state.smsTrip = trip.id;
  appEl.innerHTML = `<main class="share-shell"><header class="share-top"><div class="brand"><div class="brand-mark" aria-hidden="true">↗</div><div><div class="brand-name">FLEETPOD</div><div class="brand-subtitle">Driver photo upload</div></div></div><span class="live-pill">Secure one-time link</span></header><section class="card" style="margin-top:25px"><div class="eyebrow">${escapeHtml(trip.client)} · ${escapeHtml(trip.destination)}</div><h1 style="font-size:27px;margin-top:8px">${escapeHtml(trip.id)}</h1><p style="color:#8a95a4">LR ${escapeHtml(trip.lr_number)} · Take a clear photo of the signed delivery receipt.</p><input id="pod-file" type="file" accept="image/*" capture="environment" class="hidden" aria-label="Photograph proof of delivery" /><div class="camera-stage" id="sms-preview"><div class="camera-placeholder"><strong aria-hidden="true">▣</strong>Photo preview</div></div><div style="display:grid;gap:9px;margin-top:15px"><button class="button capture-big" data-action="sms-camera">▣ &nbsp;Open camera</button><button class="button button--ghost capture-big" data-action="sms-send" disabled>Send proof</button></div><div class="upload-meta" id="sms-meta">Photo is compressed before upload.</div></section></main>`;
  appEl.querySelector('[data-action=sms-camera]').addEventListener('click', () => appEl.querySelector('#pod-file').click());
  appEl.querySelector('#pod-file').addEventListener('change', async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try { state.photo = await compressImage(file); state.captureStamp = new Date().toISOString(); state.location = await getLocation(); document.getElementById('sms-preview').innerHTML = `<img src="${state.photo.preview}" alt="Selected POD preview" />`; document.querySelector('[data-action=sms-send]').disabled = false; document.getElementById('sms-meta').textContent = `${Math.round(state.photo.size/1024)} KB · ready to send`; }
    catch (error) { toast(error.message, 'error'); }
  });
  appEl.querySelector('[data-action=sms-send]').addEventListener('click', async event => {
    if (!state.photo) return;
    const button = event.currentTarget; button.disabled = true; button.textContent = 'Sending…';
    try { await post(`/api/upload-link/${encodeURIComponent(token)}/pod`, { image_data: state.photo.dataUrl, captured_at: state.captureStamp, latitude: state.location?.latitude ?? null, longitude: state.location?.longitude ?? null }); appEl.innerHTML = `<main class="share-shell"><div class="card empty"><div class="empty-icon accent-green">✓</div><strong>Photo sent</strong><p>The delivery team will check this POD and follow up if anything needs attention.</p></div></main>`; }
    catch (error) { button.disabled = false; button.textContent = 'Send proof'; toast(error.message, 'error'); }
  });
}

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {}));
window.addEventListener('online', () => { updateOfflineBadge(); flushOfflineQueue(); });
window.addEventListener('offline', updateOfflineBadge);
boot();
