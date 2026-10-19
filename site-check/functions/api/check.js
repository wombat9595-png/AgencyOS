// Cloudflare Pages Function: POST /api/check {url} -> {score, findings, title}. Fetches one public homepage.
import { scoreHtml, cleanUrl } from '../_lib/score.js';

const MAX_BYTES = 600000;

async function fetchPage(start) {
  let target = start;
  const began = Date.now();
  for (let hop = 0; hop < 4; hop++) {
    const response = await fetch(target, {
      redirect: 'manual',
      headers: { 'User-Agent': 'Mozilla/5.0 (free website check by Benji Price Web Design)', Accept: 'text/html' },
      signal: AbortSignal.timeout(8000),
    });
    const location = response.headers.get('Location');
    if (response.status >= 300 && response.status < 400 && location) {
      target = new URL(location, target).toString();
      if (!/^https?:/.test(target)) throw new Error('bad redirect');
      continue;
    }
    const reader = response.body ? response.body.getReader() : null;
    let html = '';
    const decoder = new TextDecoder();
    while (reader && html.length < MAX_BYTES) {
      const { done, value } = await reader.read();
      if (done) break;
      html += decoder.decode(value, { stream: true });
    }
    if (reader) reader.cancel().catch(() => {});
    return { finalUrl: target, status: response.status, html: html.slice(0, MAX_BYTES), ms: Date.now() - began };
  }
  throw new Error('too many redirects');
}

export async function onRequestPost({ request }) {
  let body;
  try { body = await request.json(); } catch { body = {}; }
  const url = cleanUrl(body.url);
  if (!url) return Response.json({ error: 'That does not look like a website address. Try something like yourbusiness.com.au' }, { status: 400 });
  let page;
  try { page = await fetchPage(url); } catch {
    try { page = await fetchPage(url.replace('https://', 'http://')); } catch { page = { finalUrl: url, status: 0, html: '', ms: 0 }; }
  }
  return Response.json({ url, ...scoreHtml(page) }, { headers: { 'Cache-Control': 'no-store' } });
}
