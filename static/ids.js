// Client-side mirror of app/util.py (normalize_id + looks_like_id) so forms can
// say *which* kind of ID something is and catch typos before a round-trip.
// The server stays the source of truth — keep the two in sync.

function normalizeId(raw) {
  return String(raw || '').replace(/[\s\-_.]+/g, '').toUpperCase();
}

// 'register' (23BAI0021) | 'neo' (K3I6O4I8 — the codes some shortlists print) | null
function idKind(raw) {
  const n = normalizeId(raw);
  if (!n) return null;
  if (/^[0-9]{2}[A-Z]{2,5}[0-9]{4}$/.test(n)) return 'register';
  if (n.length < 6 || n.length > 10 || !/^[A-Z0-9]+$/.test(n)) return null;
  let letters = 0, digits = 0, alternations = 0, prev = null;
  for (const ch of n) {
    const cur = /[A-Z]/.test(ch) ? 'L' : 'D';
    if (cur === 'L') letters++; else digits++;
    if (prev && prev !== cur) alternations++;
    prev = cur;
  }
  return letters >= 2 && digits >= 2 && alternations >= 2 ? 'neo' : null;
}

const ID_KIND_LABEL = { register: 'Register number', neo: 'NEO ID' };

// ---- random example IDs (for placeholders) ----------------------------------
// Always valid for idKind(), so the example itself never contradicts the rules.
const pick = (s) => s[Math.floor(Math.random() * s.length)];
const ID_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ';   // no I/O — they read like 1/0
const ID_DIGITS = '23456789';                    // no 0/1 for the same reason

// e.g. 24BCE1187: 2-digit year, branch code, 4 digits.
function sampleRegisterNo() {
  const year = String(20 + Math.floor(Math.random() * 6));
  const branch = pick(['BAI', 'BCE', 'BIT', 'BEC', 'BCI', 'BDS', 'BME', 'BEE', 'BKT']);
  const num = String(1 + Math.floor(Math.random() * 1999)).padStart(4, '0');
  return year + branch + num;
}

// e.g. K3P6R4T8: alternating letter/digit, 8 chars.
function sampleNeoId() {
  let s = '';
  for (let i = 0; i < 8; i++) s += i % 2 ? pick(ID_DIGITS) : pick(ID_LETTERS);
  return idKind(s) === 'neo' ? s : 'K3P6R4T8';
}
