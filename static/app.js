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
  links.forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const target = a.getAttribute('data-go');
      showPanel(target);
      history.replaceState(null, '', '#' + target);
      links.forEach((l) => l.classList.toggle('active', l === a));
    });
  });
}
function showPanel(go) {
  const map = { feed: 'feed-sec', hits: 'hits-sec', ids: 'ids-sec' };
  const id = map[go];
  if (!id) return;
  ['feed-sec', 'hits-sec', 'ids-sec'].forEach((s) => {
    const el = document.getElementById(s);
    if (el) el.style.display = (s === id) ? 'block' : 'none';
  });
}
function setActiveFromHash() {
  const g = (location.hash || '#feed').replace('#', '');
  const valid = ['feed', 'hits', 'ids'];
  showPanel(valid.includes(g) ? g : 'feed');
  document.querySelectorAll('.nav-link[data-go]').forEach((l) =>
    l.classList.toggle('active', l.getAttribute('data-go') === (valid.includes(g) ? g : 'feed')));
}

// ---- Web Push (toggle: click to enable, click again to disable THIS device) ----
async function getCurrentSubscription() {
  const reg = await navigator.serviceWorker.getRegistration('/');
  return reg ? reg.pushManager.getSubscription() : null;
}

async function togglePush() {
  const statusEl = document.getElementById('push-status');
  const label = statusEl.querySelector('span:last-child');
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
  const label = statusEl.querySelector('span:last-child');
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

// ---- Feed + hits ----
function feedItem(m) {
  const el = document.createElement('div');
  el.className = 'feed-item';
  el.innerHTML = `
    <div class="subj">${escapeHtml(m.subject)}</div>
    <div class="meta">${m.kind ? `<span class="badge ${m.kind}">${m.kind}</span>` : ''} ${shortDate(m.date)}</div>
    ${m.summary ? `<div class="summ">${escapeHtml(m.summary.summary || '')}</div>` : ''}`;
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
  initNav();
  setActiveFromHash();
  window.addEventListener('hashchange', setActiveFromHash);
  try {
    await Promise.all([loadIds(), loadFeed(), loadHits()]);
  } catch (err) {
    console.error('initial load failed:', err);
  }
  setInterval(() => { loadFeed().catch(console.warn); loadHits().catch(console.warn); }, POLL_MS);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();

if ('serviceWorker' in navigator && VAPID) {
  navigator.serviceWorker.register('/sw.js?v=' + (window.RECRUIT_SW_VERSION || '20261002'))
    .catch(console.warn);
}