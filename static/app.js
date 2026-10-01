// Recruit dashboard logic: IDs, feed/hits polling, Web Push (subject-only).

const VAPID = window.RECRUIT_VAPID_KEY || "";
const POLL_MS = window.RECRUIT_POLL_MS || 15000;

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

// ---- Page switching (sidebar nav) ----
function initNav() {
  const links = document.querySelectorAll('.nav-link[data-go]');
  const map = { feed: 'feed-sec', hits: 'hits-sec', ids: 'ids-sec', admin: 'admin-sec' };
  links.forEach((a) => {
    a.addEventListener('click', (e) => {
      const target = a.getAttribute('data-go');
      // If this page actually has the panel, switch in-place. Otherwise let the
      // <a href="/dashboard#..."> navigate normally (profile page -> dashboard).
      if (document.getElementById(map[target])) {
        e.preventDefault();
        showPanel(target);
        history.replaceState(null, '', '#' + target);
        links.forEach((l) => l.classList.toggle('active', l === a));
      }
      // else: default anchor navigation proceeds
    });
  });
}
function showPanel(go) {
  const map = { feed: 'feed-sec', hits: 'hits-sec', ids: 'ids-sec', admin: 'admin-sec' };
  const id = map[go];
  if (!id) return;
  let any = false;
  ['feed-sec', 'hits-sec', 'ids-sec', 'admin-sec'].forEach((s) => {
    const el = document.getElementById(s);
    if (el) { el.style.display = (s === id) ? 'block' : 'none'; if (s === id) any = true; }
  });
  if (!any && go === 'admin') history.replaceState(null, '', '#feed');
}
function setActiveFromHash() {
  const g = (location.hash || '#feed').replace('#', '');
  const valid = ['feed', 'hits', 'ids', 'admin'];
  const target = valid.includes(g) ? g : 'feed';
  showPanel(target);
  document.querySelectorAll('.nav-link[data-go]').forEach((l) =>
    l.classList.toggle('active', l.getAttribute('data-go') === target));
}

// ---- Web Push (toggle: click to enable, click again to disable THIS device) ----
async function getCurrentSubscription() {
  const reg = await navigator.serviceWorker.getRegistration('/');
  return reg ? reg.pushManager.getSubscription() : null;
}

async function togglePush() {
  const statusEl = document.getElementById('push-status');
  const label = statusEl.querySelector('.push-label');
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    statusEl.classList.add('unsupported'); label.textContent = 'unsupported'; return;
  }
  if (!VAPID) {
    statusEl.classList.add('blocked'); label.textContent = 'vapid missing'; return;
  }
  try {
    let reg = await navigator.serviceWorker.getRegistration('/');
    if (!reg) reg = await navigator.serviceWorker.register('/sw.js?v=' + (window.RECRUIT_SW_VERSION || '20261001'));
    await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();

    if (sub) {
      // ON -> OFF (this device only)
      const endpoint = sub.endpoint;
      await sub.unsubscribe();
      try { await getJSON('/api/push/unsubscribe', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint, platform: 'web' }),
      }); } catch (_) {}
      statusEl.classList.remove('on'); statusEl.classList.add('not-on');
      label.textContent = 'Enable Notifications';
      return;
    }

    // OFF -> ON
    if ((await Notification.requestPermission()) !== 'granted') {
      statusEl.classList.remove('not-on'); statusEl.classList.add('blocked');
      label.textContent = 'blocked'; return;
    }
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID),
    });
    const keys = sub.toJSON().keys || {};
    await getJSON('/api/push/subscribe', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint: sub.endpoint, keys, platform: 'web' }),
    });
    statusEl.classList.remove('not-on', 'blocked'); statusEl.classList.add('on');
    label.textContent = 'Notifications on';
  } catch (err) {
    console.error('push toggle failed:', err);
    statusEl.classList.add('blocked');
    label.textContent = 'push error';
  }
}
async function restorePushState() {
  const statusEl = document.getElementById('push-status');
  if (!statusEl) return;
  const label = statusEl.querySelector('.push-label');
  try {
    const sub = await getCurrentSubscription();
    if (sub) { statusEl.classList.add('on'); label.textContent = 'Notifications on'; }
  } catch (_) {}
}

// ---- Register IDs ----
async function loadIds() {
  const me = await getJSON('/api/me');
  const ul = document.getElementById('id-list');
  if (!ul) return;
  ul.innerHTML = '';
  const nameEl = document.getElementById('dash-name');
  if (nameEl) nameEl.textContent = me.name ? me.name.split(' ')[0] : 'friend';
  const avName = document.querySelector('#profile-btn .avatar-name');
  if (avName) avName.textContent = me.name ? me.name.split(' ')[0] : 'Menu';
  const sIds = document.getElementById('stat-ids');
  if (sIds) sIds.textContent = me.ids.length;
  document.getElementById('stat-hits').textContent = '?';
  if (me.ids.length === 0) {
    const li = document.createElement('li');
    li.className = 'empty'; li.textContent = 'No register IDs yet — add one above.';
    ul.appendChild(li);
  }
  for (const id of me.ids) {
    const li = document.createElement('li');
    li.textContent = id.normalized_id;
    const del = document.createElement('button');
    del.className = 'del'; del.textContent = '✕'; del.title = 'remove';
    del.onclick = async () => {
      await fetch('/api/me/ids/' + encodeURIComponent(id.normalized_id), { method: 'DELETE' });
      loadIds();
    };
    li.appendChild(del);
    ul.appendChild(li);
  }
}

// ---- Profile (division + branch subgroup) ----
async function loadProfile() {
  const me = await getJSON('/api/me');
  const div = document.getElementById('pf-division');
  const branch = document.getElementById('pf-branch');
  if (!div) return;
  div.value = me.division || '';
  if (branch) branch.value = me.branch || '';
  const divLabel = document.getElementById('pf-division-label');
  const branchLabel = document.getElementById('pf-branch-label');
  if (divLabel) divLabel.textContent = me.division === 'mba' ? 'MBA' : me.division === 'bt' ? 'B.Tech' : '—';
  if (branchLabel) branchLabel.textContent = me.branch || '—';
}

async function saveProfile() {
  const note = document.getElementById('pf-note');
  try {
    await fetch('/api/me/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        division: document.getElementById('pf-division').value,
        branch: document.getElementById('pf-branch').value,
      }),
    });
    if (note) { note.textContent = 'Saved ✓ — feed & notifications will now respect your division.'; note.style.color = 'var(--green-bg)'; }
    // refresh me + hit counts
    loadIds();
    loadFeed();
    loadHits();
  } catch (e) {
    if (note) { note.textContent = 'Save failed — try again.'; note.style.color = 'var(--red)'; }
    console.error(e);
  }
}

// ---- Feed + hits ----
function feedItem(m) {
  const el = document.createElement('div');
  el.className = 'feed-item';
  const links = (m.links || []).map((u) => `<a class="mail-link" href="${escapeHtml(u)}" target="_blank" rel="noopener">🔗 ${escapeHtml(u)}</a>`).join('');
  el.innerHTML = `
    <div class="subj">${escapeHtml(m.subject)}</div>
    <div class="meta">${m.kind ? `<span class="badge ${m.kind}">${m.kind}</span>` : ''} ${shortDate(m.date)}</div>
    ${m.summary ? `<div class="summ">${escapeHtml(m.summary.summary || '')}</div>` : ''}
    ${links ? `<div class="mail-links">${links}</div>` : ''}`;
  return el;
}

async function loadFeed() {
  const data = await getJSON('/api/mails?limit=30');
  const feed = document.getElementById('feed');
  if (!feed) return;
  feed.innerHTML = '';
  if (!data.mails.length) {
    feed.innerHTML = '<div class="feed-item muted-pad">No mails ingested yet. The poller will pick up new CDC mails.</div>';
  }
  data.mails.forEach((m) => feed.appendChild(feedItem(m)));
}

async function loadHits() {
  const data = await getJSON('/api/hits');
  const box = document.getElementById('hits');
  if (!box) return;
  box.innerHTML = '';
  const unread = data.hits.filter((h) => !h.read).length;
  document.getElementById('stat-hits').textContent = data.hits.length;
  document.getElementById('stat-unread').textContent = unread;
  if (!data.hits.length) {
    box.innerHTML = '<div class="feed-item muted-pad">No hits yet — you\'ll be notified the moment your ID appears on a shortlist.</div>';
  }
  data.hits.forEach((h) => {
    const el = document.createElement('div');
    el.className = 'hit ' + (h.read ? '' : 'unread');
    el.innerHTML = `<div class="subj">${h.normalized_id} — ${escapeHtml(h.subject)}</div>
      <div class="meta">${h.kind ? `<span class="badge ${h.kind}">${h.kind}</span>` : ''} ${h.first_seen_at ? escapeHtml(shortDate(h.first_seen_at)) : ''}</div>`;
    if (!h.read) {
      const mark = document.createElement('button');
      mark.className = 'mark-read'; mark.textContent = 'mark read';
      mark.onclick = async () => { await fetch('/api/hits/' + h.id + '/read', { method: 'POST' }); loadHits(); loadFeed(); };
      el.appendChild(mark);
    }
    box.appendChild(el);
  });
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function shortDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
      ' · ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  } catch (_) { return iso || ''; }
}

// ---- Admin ----
async function loadAdminStats() {
  const data = await getJSON('/api/admin/stats');
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('admin-stat-ingested', data.ingested);
  set('admin-stat-hits', data.hits);
  set('admin-stat-users', data.users.length);
  const box = document.getElementById('admin-users');
  if (!box) return;
  box.innerHTML = '';
  for (const u of data.users) {
    const row = document.createElement('div');
    row.className = 'admin-user';
    const idLabel = u.ids.length ? u.ids.map(escapeHtml).join(', ') : 'no IDs yet';
    const dot = u.devices > 0 ? `<span class="badge ok">${u.devices} live</span>` : `<span class="badge off">no device</span>`;
    const adminTag = u.admin ? '<span class="badge info">admin</span>' : '';
    row.innerHTML = `
      <div class="admin-user-info">
        <div class="admin-user-name">${escapeHtml(u.name || u.email)} ${adminTag}</div>
        <div class="admin-user-meta">${escapeHtml(u.email)} · ${escapeHtml(idLabel)} ${dot}</div>
      </div>
      <button class="btn small" data-test-push="${u.id}" title="Send test notification to ${escapeHtml(u.name || u.email)}">Test</button>`;
    box.appendChild(row);
  }
  box.querySelectorAll('[data-test-push]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const uid = btn.getAttribute('data-test-push');
      btn.disabled = true;
      btn.textContent = 'sending…';
      const user = data.users.find((u) => String(u.id) === uid);
      const who = (user && (user.name || user.email)) || 'that user';
      try {
        const r = await getJSON('/api/admin/test-push', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: Number(uid), title: 'Recruit test', body: `Test ping for ${who}` }),
        });
        btn.textContent = `sent ${r.sent}/${r.live_devices}`;
        btn.classList.add('sent');
      } catch (err) {
        btn.textContent = 'failed';
        alert(err.message);
      } finally {
        setTimeout(() => { btn.disabled = false; btn.textContent = 'Test'; btn.classList.remove('sent'); }, 2200);
      }
    });
  });
}

async function adminPoll() {
  const btn = document.getElementById('admin-poll');
  const out = document.getElementById('admin-poll-result');
  if (!btn) return;
  btn.disabled = true; btn.textContent = 'polling…';
  try {
    const r = await getJSON('/api/admin/poll', { method: 'POST' });
    const shortlists = r.shortlists || 0, anns = r.announcements || 0;
    out.textContent = `processed ${r.processed || 0} new · ${shortlists} shortlist · ${anns} announcement`;
  } catch (err) {
    out.textContent = 'poll failed';
    alert(err.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Poll now';
    setTimeout(() => { out.textContent = ''; }, 6000);
  }
}

// ---- Boot ----
async function boot() {
  const idForm = document.getElementById('id-form');
  if (idForm) {
    idForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = document.getElementById('new-id');
      const val = (input && input.value || '').trim();
      if (!val) return;
      try {
        await getJSON('/api/me/ids', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ register_id: val }),
        });
        if (input) input.value = '';
        await loadIds();
      } catch (err) {
        alert('Could not add ID: ' + err.message);
      }
    });
  }
  const ps = document.getElementById('push-status');
  if (ps) { ps.addEventListener('click', togglePush); restorePushState(); }
  // Profile dropdown (avatar) — open/close + position based on space + close on outside
  const pfBtn = document.getElementById('profile-btn');
  const pfMenu = document.getElementById('profile-menu');
  if (pfBtn && pfMenu) {
    const MARGIN = 8;
    function openMenu() {
      // Escape the sidebar's backdrop-filter/sticky containing block — reparent
      // to <body> so position:fixed is viewport-relative, else the menu gets
      // clipped (the mobile "half hidden" bug).
      if (pfMenu.parentNode !== document.body) document.body.appendChild(pfMenu);
      pfMenu.classList.add('open');
      const r = pfBtn.getBoundingClientRect();
      const mh = pfMenu.offsetHeight || 150;
      const spaceBelow = window.innerHeight - r.bottom - MARGIN;
      const spaceAbove = r.top - MARGIN;
      const above = spaceBelow < mh && spaceAbove >= spaceBelow;
      pfMenu.style.position = 'fixed';
      pfMenu.style.left = Math.max(8, r.left) + 'px';
      pfMenu.style.width = Math.max(r.width, 200) + 'px';
      if (above) { pfMenu.style.top = 'auto'; pfMenu.style.bottom = (window.innerHeight - r.top + MARGIN) + 'px'; }
      else { pfMenu.style.bottom = 'auto'; pfMenu.style.top = (r.bottom + MARGIN) + 'px'; }
    }
    pfBtn.addEventListener('click', (e) => {
      e.preventDefault(); e.stopPropagation();
      if (pfMenu.classList.contains('open')) pfMenu.classList.remove('open');
      else openMenu();
    });
    document.addEventListener('click', (e) => {
      if (!pfMenu.contains(e.target) && !pfBtn.contains(e.target)) pfMenu.classList.remove('open');
    });
    window.addEventListener('resize', () => pfMenu.classList.remove('open'));
    document.addEventListener('scroll', () => pfMenu.classList.remove('open'), true);
    pfMenu.querySelectorAll('.menu-item').forEach((it) => {
      it.addEventListener('click', () => pfMenu.classList.remove('open'));
    });
  }
  initNav();
  setActiveFromHash();
  window.addEventListener('hashchange', setActiveFromHash);
  try {
    await Promise.all([loadIds(), loadFeed(), loadHits()]);
    if (document.getElementById('admin-sec')) await loadAdminStats();
  } catch (err) {
    console.error('initial load failed:', err);
  }
  const pollBtn = document.getElementById('admin-poll');
  if (pollBtn) pollBtn.addEventListener('click', adminPoll);
  // Profile save
  const pfSave = document.getElementById('pf-save');
  if (pfSave) pfSave.addEventListener('click', saveProfile);
  if (document.getElementById('pf-division')) loadProfile();
  setInterval(() => { loadFeed().catch(console.warn); loadHits().catch(console.warn); }, POLL_MS);
  // Refresh the moment the app is (re)opened or returns from background —
  // PWA pages don't reload by themselves, so without this you'd stare at stale
  // feed/hits until the next poll fires. Exposed on window so sw/push can ask.
  window.recruitRefresh = function () {
    loadFeed().catch(console.warn);
    loadHits().catch(console.warn);
    if (document.getElementById('admin-sec')) loadAdminStats().catch(console.warn);
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