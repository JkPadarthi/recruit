// Recruit app logic: tabs, feed/hits polling, register IDs, profile, admin,
// and Web Push (subject-only). Shared by /dashboard and /profile — every DOM
// lookup is guarded so a page only drives the parts it actually has.

const VAPID = window.RECRUIT_VAPID_KEY || "";
const POLL_MS = window.RECRUIT_POLL_MS || 15000;
const TABS = { feed: 'feed-sec', hits: 'hits-sec', ids: 'ids-sec', admin: 'admin-sec' };

const $ = (id) => document.getElementById(id);
const setText = (id, v) => { const el = $(id); if (el) el.textContent = v; };

// ---- helpers ----------------------------------------------------------------
function urlBase64ToUint8Array(base64) {
  const pad = base64.replace(/[-_]/g, (m) => (m === '-' ? '+' : '/')) + '='.repeat((4 - base64.length % 4) % 4);
  const bin = window.atob(pad);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { location.href = '/login'; throw new Error('session expired'); }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || r.statusText; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}
const postJSON = (url, body, method = 'POST') => getJSON(url, {
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
});

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;

// "5m ago" for today-ish, "Nov 19 · 5:00 PM" otherwise.
function when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins >= 0 && mins < 1) return 'just now';
  if (mins >= 0 && mins < 60) return `${mins}m ago`;
  if (mins >= 0 && mins < 12 * 60) return `${Math.round(mins / 60)}h ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' · ' +
         d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

// Only real web links from a mail become clickable — never javascript: etc.
function safeLink(u) {
  try {
    const url = new URL(u);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
    return { href: url.href, label: url.hostname.replace(/^www\./, '') };
  } catch (_) { return null; }
}

function kindTag(kind) {
  if (!kind) return '';
  const k = String(kind).toLowerCase();
  return `<span class="tag tag-${escapeHtml(k)}">${escapeHtml(k)}</span>`;
}

// ---- toasts -----------------------------------------------------------------
function toast(text, { error = false, action, onAction, ms = 4000 } = {}) {
  const box = $('toasts');
  if (!box) return;
  const el = document.createElement('div');
  el.className = 'toast' + (error ? ' is-error' : '');
  el.setAttribute('role', error ? 'alert' : 'status');
  const span = document.createElement('span');
  span.textContent = text;
  el.appendChild(span);
  let timer;
  const close = () => { clearTimeout(timer); el.classList.add('is-out'); setTimeout(() => el.remove(), 200); };
  if (action) {
    const b = document.createElement('button');
    b.textContent = action;
    b.onclick = () => { close(); onAction && onAction(); };
    el.appendChild(b);
  }
  box.appendChild(el);
  timer = setTimeout(close, ms);
}

// ---- live indicator ---------------------------------------------------------
function setLive(ok) {
  const el = $('live-indicator');
  if (!el) return;
  el.classList.toggle('is-off', !ok);
  el.querySelector('.live-label').textContent = ok ? 'Live' : 'Offline';
  el.title = ok
    ? 'Updated ' + new Date().toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : "Can't reach the server — retrying";
}

// ---- tabs -------------------------------------------------------------------
function showTab(go) {
  if (!$(TABS.feed)) return;                      // not the dashboard
  if (!TABS[go] || !$(TABS[go])) go = 'feed';     // unknown / non-admin → feed
  Object.entries(TABS).forEach(([k, id]) => { const el = $(id); if (el) el.hidden = k !== go; });
  document.querySelectorAll('.tabbar-btn[data-go]').forEach((l) => {
    const on = l.dataset.go === go;
    l.classList.toggle('is-on', on);
    if (on) l.setAttribute('aria-current', 'page'); else l.removeAttribute('aria-current');
  });
  if (location.hash !== '#' + go) history.replaceState(null, '', '#' + go);
  if (go === 'ids') setTimeout(() => { const i = $('new-id'); if (i && !state.me?.ids?.length) i.focus(); }, 50);
}
function initNav() {
  document.addEventListener('click', (e) => {
    const a = e.target.closest('[data-go]');
    if (!a || !$(TABS.feed)) return;              // off-dashboard: let the link navigate
    e.preventDefault();
    showTab(a.dataset.go);
    window.scrollTo({ top: 0 });
  });
  showTab((location.hash || '#feed').slice(1));
  window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));
}

// ---- shared state -----------------------------------------------------------
const state = { me: null, mails: [], mailsKey: '', hits: [], hitsKey: '', filter: 'all' };

// ---- me: name, IDs, profile -------------------------------------------------
async function loadMe() {
  const me = await getJSON('/api/me');
  state.me = me;
  setText('dash-name', me.name ? me.name.split(' ')[0] : 'there');
  setText('stat-ids', me.ids.length);
  const nudge = $('setup-nudge');
  if (nudge) nudge.hidden = me.ids.length > 0;
  renderIds();
  fillProfile();
  return me;
}

function renderIds() {
  const ul = $('id-list');
  if (!ul || !state.me) return;
  const ids = state.me.ids;
  if (!ids.length) {
    ul.innerHTML = `<li class="empty"><strong>No IDs yet</strong>
      <p>Add your register ID above — it's how we know a shortlist is about you.</p></li>`;
    return;
  }
  ul.innerHTML = ids.map((id) => `
    <li>
      <span class="id-badge">${icon('id')}</span>
      <span class="id-val">${escapeHtml(id.normalized_id)}</span>
      <button class="icon-btn is-danger" type="button" data-del-id="${escapeHtml(id.normalized_id)}"
              data-raw="${escapeHtml(id.register_id)}" aria-label="Remove ${escapeHtml(id.normalized_id)}">${icon('x')}</button>
    </li>`).join('');
}

async function addId(raw) {
  const r = await postJSON('/api/me/ids', { register_id: raw });
  await loadMe();
  return r;
}

function initIds() {
  const form = $('id-form');
  if (!form) return;
  const input = $('new-id'), err = $('id-error');
  input.addEventListener('input', () => { err.hidden = true; });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const val = input.value.trim();
    if (!val) { err.textContent = 'Type a register ID, like 23BAI0021.'; err.hidden = false; input.focus(); return; }
    const btn = form.querySelector('[type=submit]');
    btn.disabled = true; btn.classList.add('is-busy');
    try {
      const r = await addId(val);
      input.value = '';
      toast(r.added ? `Tracking ${r.normalized_id} — you'll be pinged when it's on a list.`
                    : `You're already tracking ${r.normalized_id}.`);
    } catch (ex) {
      err.textContent = /does not look like/.test(ex.message)
        ? `"${val}" doesn't look like a register ID. Check for typos — e.g. 23BAI0021.`
        : `Couldn't add that ID: ${ex.message}`;
      err.hidden = false;
    } finally {
      btn.disabled = false; btn.classList.remove('is-busy');
    }
  });
  $('id-list').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-del-id]');
    if (!b) return;
    const norm = b.dataset.delId, raw = b.dataset.raw || norm;
    b.disabled = true;
    try {
      await getJSON('/api/me/ids/' + encodeURIComponent(norm), { method: 'DELETE' });
      await loadMe();
      toast(`Stopped tracking ${norm}.`, {
        action: 'Undo', ms: 6000,
        onAction: () => addId(raw).catch((ex) => toast('Undo failed: ' + ex.message, { error: true })),
      });
    } catch (ex) {
      b.disabled = false;
      toast("Couldn't remove that ID: " + ex.message, { error: true });
    }
  });
}

// ---- profile ----------------------------------------------------------------
function setSeg(segId, hiddenId, value) {
  const seg = $(segId);
  if (!seg) return;
  $(hiddenId).value = value || '';
  seg.querySelectorAll('.seg-btn').forEach((b) => {
    const on = b.dataset.value === value;
    b.classList.toggle('is-on', on);
    b.setAttribute('aria-checked', String(on));
  });
}

function fillProfile() {
  const me = state.me;
  if (!me || !$('profile-form')) return;
  setText('pf-email', me.email);
  // Don't clobber what the user is typing during a background refresh.
  if ($('profile-form').dataset.dirty) return;
  $('pf-name').value = me.name || '';
  $('pf-branch').value = me.branch || '';
  setSeg('pf-division-seg', 'pf-division', me.division || '');
}

function initProfile() {
  const form = $('profile-form');
  if (!form) return;
  form.addEventListener('input', () => { form.dataset.dirty = '1'; });
  $('pf-division-seg').addEventListener('click', (e) => {
    const b = e.target.closest('.seg-btn');
    if (!b) return;
    form.dataset.dirty = '1';
    setSeg('pf-division-seg', 'pf-division', b.dataset.value);
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const note = $('pf-note'), btn = $('pf-save');
    btn.disabled = true; btn.classList.add('is-busy');
    try {
      // Send ALL fields — the API overwrites name/branch/division together, so
      // omitting name would silently blank it.
      await postJSON('/api/me/profile', {
        name: $('pf-name').value,
        division: $('pf-division').value,
        branch: $('pf-branch').value,
      }, 'PUT');
      delete form.dataset.dirty;
      await loadMe();
      note.textContent = 'Saved. Your feed now follows this division.';
      note.className = 'form-note is-good';
    } catch (ex) {
      note.textContent = "Couldn't save: " + ex.message;
      note.className = 'form-note is-bad';
    } finally {
      note.hidden = false;
      btn.disabled = false; btn.classList.remove('is-busy');
    }
  });
}

// ---- feed -------------------------------------------------------------------
function mailHtml(m) {
  const links = (m.links || []).map(safeLink).filter(Boolean)
    .map((l) => `<a class="link-chip" href="${escapeHtml(l.href)}" target="_blank" rel="noopener noreferrer">${icon('link')}<span>${escapeHtml(l.label)}</span></a>`)
    .join('');
  const summ = m.summary && m.summary.summary;
  return `
    <article class="mail">
      <div class="mail-top">${kindTag(m.kind)}<time>${escapeHtml(when(m.date))}</time></div>
      <h3 class="mail-subj">${escapeHtml(m.subject || '(no subject)')}</h3>
      ${summ ? `<p class="mail-summ">${escapeHtml(summ)}</p><button class="more-btn" type="button" hidden>Show more</button>` : ''}
      ${links ? `<div class="mail-links">${links}</div>` : ''}
    </article>`;
}

// A final 'selection' list is still a list with names on it — group it with shortlists.
const kindGroup = (k) => (k === 'selection' ? 'shortlist' : k);

function renderFeed() {
  const feed = $('feed');
  if (!feed) return;
  const counts = { all: state.mails.length, shortlist: 0, announcement: 0 };
  state.mails.forEach((m) => { const k = kindGroup(m.kind); if (k in counts) counts[k]++; });
  document.querySelectorAll('#feed-filter [data-count]').forEach((s) => {
    s.textContent = counts[s.dataset.count] || '';
  });
  const shown = state.filter === 'all' ? state.mails : state.mails.filter((m) => kindGroup(m.kind) === state.filter);
  feed.removeAttribute('aria-busy');
  if (!shown.length) {
    feed.innerHTML = state.mails.length
      ? `<div class="empty"><p>No ${state.filter}s in the latest mail.</p></div>`
      : `<div class="empty"><strong>Nothing yet</strong><p>New CDC mails show up here within a few minutes of arriving.</p></div>`;
    return;
  }
  feed.innerHTML = shown.map(mailHtml).join('');
  // Only offer "Show more" where the 3-line clamp actually cut text off.
  feed.querySelectorAll('.mail-summ').forEach((p) => {
    if (p.scrollHeight > p.clientHeight + 2) p.nextElementSibling.hidden = false;
  });
}

async function loadFeed() {
  if (!$('feed')) return;
  const data = await getJSON('/api/mails?limit=30');
  setText('stat-mails', data.mails.length);
  const key = JSON.stringify(data.mails);
  if (key === state.mailsKey) return;            // unchanged: keep expanded state & scroll
  state.mailsKey = key;
  state.mails = data.mails;
  renderFeed();
}

function initFeed() {
  const filter = $('feed-filter');
  if (!filter) return;
  filter.addEventListener('click', (e) => {
    const c = e.target.closest('.chip');
    if (!c) return;
    state.filter = c.dataset.kind;
    filter.querySelectorAll('.chip').forEach((x) => {
      const on = x === c;
      x.classList.toggle('is-on', on);
      x.setAttribute('aria-selected', String(on));
    });
    renderFeed();
  });
  $('feed').addEventListener('click', (e) => {
    const b = e.target.closest('.more-btn');
    if (!b) return;
    const p = b.previousElementSibling;
    const open = p.classList.toggle('is-open');
    b.textContent = open ? 'Show less' : 'Show more';
  });
}

// ---- hits -------------------------------------------------------------------
function renderHitCounts() {
  const total = state.hits.length;
  const unread = state.hits.filter((h) => !h.read).length;
  setText('stat-hits', total);
  setText('stat-unread', unread);
  setText('hero-caption', unread === 1 ? 'new shortlist for you' : 'new shortlists for you');
  const hero = document.querySelector('.hero');
  if (hero) hero.classList.toggle('has-new', unread > 0);
  const badge = $('tab-badge-hits');
  if (badge) { badge.hidden = !unread; badge.textContent = unread > 99 ? '99+' : unread; }
  const all = $('mark-all-read');
  if (all) all.hidden = unread < 2;
  document.title = (unread ? `(${unread}) ` : '') + document.title.replace(/^\(\d+\) /, '');
}

function renderHits() {
  const box = $('hits');
  if (!box) return;
  box.removeAttribute('aria-busy');
  if (!state.hits.length) {
    const noIds = state.me && !state.me.ids.length;
    box.innerHTML = `<div class="empty"><strong>No hits yet</strong>
      <p>${noIds ? "Add a register ID first — then you'll be pinged the moment it's on a shortlist."
                 : "You'll get a notification the moment one of your IDs is on a shortlist."}</p>
      ${noIds ? `<a class="btn btn-primary btn-sm" href="#ids" data-go="ids">${icon('plus')}Add an ID</a>` : ''}</div>`;
    return;
  }
  box.innerHTML = state.hits.map((h) => `
    <div class="hit ${h.read ? '' : 'is-unread'}">
      <span class="hit-dot" aria-hidden="true"></span>
      <div class="hit-main">
        <span class="hit-id">${escapeHtml(h.normalized_id)}</span>
        <span class="hit-subj">${escapeHtml(h.subject)}</span>
        <div class="mail-top">${kindTag(h.kind)}<time>${escapeHtml(when(h.first_seen_at))}</time>${h.read ? '' : '<span class="sr-only">unread</span>'}</div>
        ${h.summary && h.summary.summary ? `<p class="mail-summ">${escapeHtml(h.summary.summary)}</p>` : ''}
      </div>
      ${h.read ? '' : `<button class="icon-btn is-good" type="button" data-read="${h.id}" aria-label="Mark as read" title="Mark as read">${icon('check')}</button>`}
    </div>`).join('');
}

async function loadHits() {
  const data = await getJSON('/api/hits');
  const key = JSON.stringify(data.hits);
  state.hits = data.hits;
  renderHitCounts();
  if (key === state.hitsKey) return;
  state.hitsKey = key;
  renderHits();
}

async function markRead(ids) {
  // Optimistic: flip locally first so the tap feels instant.
  state.hits.forEach((h) => { if (ids.includes(h.id)) h.read = true; });
  state.hitsKey = '';
  renderHitCounts(); renderHits();
  const results = await Promise.allSettled(ids.map((id) => getJSON('/api/hits/' + id + '/read', { method: 'POST' })));
  if (results.some((r) => r.status === 'rejected')) toast("Couldn't mark everything read — try again.", { error: true });
  loadHits().catch(console.warn);
}

function initHits() {
  const box = $('hits');
  if (!box) return;
  box.addEventListener('click', (e) => {
    const b = e.target.closest('[data-read]');
    if (b) markRead([Number(b.dataset.read)]);
  });
  const all = $('mark-all-read');
  if (all) all.addEventListener('click', () => markRead(state.hits.filter((h) => !h.read).map((h) => h.id)));
}

// ---- Web Push (toggle: on/off for THIS device) -------------------------------
function pushSupported() { return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window; }

async function getCurrentSubscription() {
  const reg = await navigator.serviceWorker.getRegistration('/');
  return reg ? reg.pushManager.getSubscription() : null;
}

// One place that paints every push control for the given state:
// 'on' | 'off' | 'blocked' | 'unsupported' | 'novapid' | 'error'
function renderPush(st) {
  const isiOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const copy = {
    on:          ['Notifications are on', 'This device gets pinged for your hits.', 'Turn off'],
    off:         ['Notifications are off', "Turn them on so you don't miss a shortlist.", 'Turn on'],
    blocked:     ['Blocked by your browser', 'Allow notifications for this site in browser settings, then try again.', 'Try again'],
    unsupported: ['Not available here', isiOS ? 'On iPhone, add Recruit to your Home Screen first, then open it from there.'
                                              : "This browser can't receive push notifications.", null],
    novapid:     ['Not configured', 'Push keys are missing on the server.', null],
    error:       ['Something went wrong', 'Try again in a moment.', 'Try again'],
  }[st];
  document.querySelectorAll('.push-btn').forEach((b) => {
    b.hidden = !copy[2];
    b.classList.remove('is-busy');
    b.disabled = false;
    const label = b.querySelector('.push-label') || b;
    if (copy[2]) label.textContent = copy[2];
    b.classList.toggle('btn-secondary', st === 'on');
    b.classList.toggle('btn-primary', st !== 'on');
  });
  setText('push-state-title', copy[0]);
  setText('push-state-sub', copy[1]);
  const row = document.querySelector('.push-row');
  if (row) { row.classList.toggle('is-on', st === 'on'); row.classList.toggle('is-blocked', st === 'blocked' || st === 'error'); }
  const cta = $('push-cta');
  if (cta) cta.hidden = !(st === 'off' || st === 'blocked');
}

async function togglePush(e) {
  const btn = e && e.currentTarget;
  if (!pushSupported()) return renderPush('unsupported');
  if (!VAPID) return renderPush('novapid');
  if (btn) { btn.disabled = true; btn.classList.add('is-busy'); }
  try {
    let reg = await navigator.serviceWorker.getRegistration('/');
    if (!reg) reg = await navigator.serviceWorker.register('/sw.js?v=' + (window.RECRUIT_SW_VERSION || '20261001'));
    await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();

    if (sub) {
      // ON -> OFF (this device only)
      const endpoint = sub.endpoint;
      await sub.unsubscribe();
      try { await postJSON('/api/push/unsubscribe', { endpoint, platform: 'web' }); } catch (_) {}
      renderPush('off');
      toast('Notifications off for this device.');
      return;
    }

    // OFF -> ON
    if ((await Notification.requestPermission()) !== 'granted') return renderPush('blocked');
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID),
    });
    const keys = sub.toJSON().keys || {};
    await postJSON('/api/push/subscribe', { endpoint: sub.endpoint, keys, platform: 'web' });
    renderPush('on');
    toast("Notifications on — we'll ping this device.");
  } catch (err) {
    console.error('push toggle failed:', err);
    renderPush('error');
  }
}

async function restorePushState() {
  if (!document.querySelector('.push-btn')) return;
  if (!pushSupported()) return renderPush('unsupported');
  if (!VAPID) return renderPush('novapid');
  try {
    const sub = await getCurrentSubscription();
    if (sub) return renderPush('on');
    renderPush(Notification.permission === 'denied' ? 'blocked' : 'off');
  } catch (_) { renderPush('off'); }
}

// ---- admin ------------------------------------------------------------------
async function loadAdminStats() {
  if (!$('admin-sec')) return;
  const data = await getJSON('/api/admin/stats');
  setText('admin-stat-ingested', data.ingested);
  setText('admin-stat-hits', data.hits);
  setText('admin-stat-users', data.users.length);
  const box = $('admin-users');
  if (!box) return;
  state.adminUsers = data.users;
  box.innerHTML = data.users.map((u) => {
    const idLabel = u.ids.length ? u.ids.join(', ') : 'no IDs yet';
    const dev = u.devices > 0
      ? `<span class="tag tag-shortlist">${u.devices} device${u.devices > 1 ? 's' : ''}</span>`
      : '<span class="tag tag-off">no device</span>';
    return `
      <div class="admin-user">
        <div class="admin-user-info">
          <div class="admin-user-name">${escapeHtml(u.name || u.email)} ${u.admin ? '<span class="tag tag-admin">admin</span>' : ''} ${dev}</div>
          <div class="admin-user-meta">${escapeHtml(u.email)} · ${escapeHtml(idLabel)}</div>
        </div>
        <button class="btn btn-secondary btn-sm" type="button" data-test-push="${u.id}"
                ${u.devices ? '' : 'disabled'} aria-label="Send test notification to ${escapeHtml(u.name || u.email)}">${icon('bell')}Test</button>
      </div>`;
  }).join('');
}

function initAdmin() {
  const sec = $('admin-sec');
  if (!sec) return;
  $('admin-users').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-test-push]');
    if (!btn) return;
    const uid = Number(btn.dataset.testPush);
    const user = (state.adminUsers || []).find((u) => u.id === uid);
    const who = (user && (user.name || user.email)) || 'that user';
    btn.disabled = true; btn.classList.add('is-busy');
    try {
      const r = await postJSON('/api/admin/test-push', { user_id: uid, title: 'Recruit test', body: `Test ping for ${who}` });
      toast(`Sent to ${r.sent} of ${r.live_devices} device${r.live_devices === 1 ? '' : 's'} for ${who}.`);
    } catch (err) {
      toast('Test push failed: ' + err.message, { error: true });
    } finally {
      btn.disabled = false; btn.classList.remove('is-busy');
    }
  });
  const pollBtn = $('admin-poll'), out = $('admin-poll-result');
  pollBtn.addEventListener('click', async () => {
    pollBtn.disabled = true; pollBtn.classList.add('is-busy');
    try {
      const r = await getJSON('/api/admin/poll', { method: 'POST' });
      out.textContent = `Processed ${r.processed || 0} new · ${r.shortlists || 0} shortlist · ${r.announcements || 0} announcement`;
      out.className = 'form-note is-good';
      refreshAll();
    } catch (err) {
      out.textContent = 'Poll failed: ' + err.message;
      out.className = 'form-note is-bad';
    } finally {
      pollBtn.disabled = false; pollBtn.classList.remove('is-busy');
    }
  });
}

// ---- boot -------------------------------------------------------------------
async function refreshAll() {
  try {
    await Promise.all([loadFeed(), loadHits()]);
    setLive(true);
  } catch (err) {
    console.warn('refresh failed:', err);
    setLive(false);
  }
  loadAdminStats().catch(console.warn);
}

async function boot() {
  initNav();
  initIds();
  initProfile();
  initFeed();
  initHits();
  initAdmin();
  document.querySelectorAll('.push-btn').forEach((b) => b.addEventListener('click', togglePush));
  restorePushState();

  try { await loadMe(); } catch (err) { console.error('load /api/me failed:', err); }
  await refreshAll();
  setInterval(refreshAll, POLL_MS);

  // Refresh the moment the app is (re)opened or returns from background —
  // PWA pages don't reload by themselves. Throttled: focus, pageshow and
  // visibilitychange often fire together. Exposed on window so sw/push can ask.
  let last = Date.now();
  window.recruitRefresh = function () {
    if (Date.now() - last < 3000) return;
    last = Date.now();
    refreshAll();
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') window.recruitRefresh();
  });
  window.addEventListener('pageshow', () => window.recruitRefresh());
  window.addEventListener('focus', () => window.recruitRefresh());
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();

if ('serviceWorker' in navigator && VAPID) {
  navigator.serviceWorker.register('/sw.js?v=' + (window.RECRUIT_SW_VERSION || '20261002'))
    .catch(console.warn);
}
