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
  if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
  return r.json();
}

// ---- Web Push ----
async function enablePush() {
  const statusEl = document.getElementById('push-status');
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    statusEl.textContent = 'push unsupported';
    return;
  }
  if (!(await Notification.requestPermission()) === 'granted') {
    statusEl.textContent = 'permission blocked';
    return;
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(VAPID),
  });
  await getJSON('/api/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint: sub.endpoint, keys: sub.toJSON().keys || {}, platform: 'web' }),
  });
  statusEl.textContent = 'push on ✓';
}

// ---- Register IDs ----
async function loadIds() {
  const me = await getJSON('/api/me');
  const ul = document.getElementById('id-list');
  ul.innerHTML = '';
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
    <div class="meta">${m.kind ? `<span class="badge ${m.kind}">${m.kind}</span>` : ''} ${m.date || ''}</div>
    ${m.summary ? `<div class="summ">${escapeHtml(m.summary.summary || '')}</div>` : ''}`;
  return el;
}

async function loadFeed() {
  const data = await getJSON('/api/mails?limit=30');
  const feed = document.getElementById('feed');
  feed.innerHTML = '';
  data.mails.forEach((m) => feed.appendChild(feedItem(m)));
}

async function loadHits() {
  const data = await getJSON('/api/hits');
  const box = document.getElementById('hits');
  box.innerHTML = '';
  data.hits.forEach((h) => {
    const el = document.createElement('div');
    el.className = 'hit ' + (h.read ? '' : 'unread');
    el.innerHTML = `<div class="subj">${h.normalized_id} — ${escapeHtml(h.subject)}</div>`;
    el.onclick = async () => {
      await fetch('/api/hits/' + h.id + '/read', { method: 'POST' });
      loadHits();
    };
    box.appendChild(el);
  });
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---- Boot ----
document.addEventListener('DOMContentLoaded', async () => {
  const idForm = document.getElementById('id-form');
  if (idForm) {
    idForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await getJSON('/api/me/ids', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                     body: JSON.stringify({ register_id: new_id.value }) });
      new_id.value = ''; loadIds();
    });
  }
  const ps = document.getElementById('push-status');
  if (ps) ps.addEventListener('click', enablePush);
  await Promise.all([loadIds(), loadFeed(), loadHits()]);
  setInterval(() => { loadFeed(); loadHits(); }, POLL_MS);
});

if ('serviceWorker' in navigator && window.RECRUIT_VAPID_KEY) {
  navigator.serviceWorker.register('/static/sw.js').catch(console.warn);
}