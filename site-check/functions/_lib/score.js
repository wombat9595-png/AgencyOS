// Scores a homepage the way a customer on a phone experiences it. Pure function: no network.
export const CHECKS = {
  loads: { points: 25, good: 'Your site loads', bad: 'Your site did not load when we tried it' },
  https: { points: 20, good: 'It is secure (https)', bad: 'Browsers show "Not secure" on your site' },
  mobile: { points: 20, good: 'It fits phone screens', bad: 'It does not resize for phones, so visitors pinch and zoom' },
  fast: { points: 10, good: 'It loaded quickly', bad: 'It took a while to load' },
  call: { points: 10, good: 'There is a tap-to-call link', bad: 'There is no tap-to-call button for phone visitors' },
  fresh: { points: 10, good: 'It looks recently updated', bad: 'It looks like it has not been updated in years' },
  described: { points: 5, good: 'It tells Google what you do', bad: 'It is missing a description for Google results' },
};

export function scoreHtml({ finalUrl = '', status = 0, html = '', ms = 0, year = new Date().getFullYear() }) {
  const results = {};
  const loaded = status >= 200 && status < 400 && html.length > 0;
  const lower = html.toLowerCase();
  results.loads = loaded;
  results.https = loaded && finalUrl.startsWith('https://');
  results.mobile = loaded && /<meta[^>]+name=["']?viewport/.test(lower);
  results.fast = loaded && ms > 0 && ms < 2500;
  results.call = loaded && /href=["']tel:/.test(lower);
  const years = [...lower.matchAll(/(?:©|&copy;|copyright)\s*(?:\d{4}\s*(?:-|–|&ndash;)\s*)?((?:19|20)\d\d)/g)].map((m) => Number(m[1]));
  const latest = years.length ? Math.max(...years) : 0;
  results.fresh = loaded && (latest === 0 || latest >= year - 2);
  results.described = loaded && /<meta[^>]+name=["']?description["']?[^>]+content=["'][^"']{20,}/.test(lower);
  let score = 0;
  const findings = [];
  for (const [key, check] of Object.entries(CHECKS)) {
    if (results[key]) score += check.points;
    findings.push({ key, ok: Boolean(results[key]), text: results[key] ? check.good : check.bad });
  }
  const title = (html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [, ''])[1].replace(/\s+/g, ' ').trim().slice(0, 120);
  return { score, findings, title, year: latest };
}

// Only public web addresses: no IP literals, no localhost, no odd ports or logins.
export function cleanUrl(value) {
  let text = String(value || '').trim();
  if (!text || text.length > 300 || /\s/.test(text)) return null;
  if (!/^https?:\/\//i.test(text)) text = 'https://' + text;
  let url;
  try { url = new URL(text); } catch { return null; }
  const host = url.hostname.toLowerCase();
  if (url.username || url.password || url.port || !host.includes('.')) return null;
  if (/^[\d.]+$/.test(host) || host.includes(':') || host.endsWith('.local') || host.endsWith('.internal') || host === 'localhost') return null;
  return 'https://' + host + '/';
}
