// Run: node --test client-kits/never-miss-a-job/test/logic.test.js
const test = require('node:test');
const assert = require('node:assert');
const L = require('../Logic.js');

const config = {
  businessName: 'Example Plumbing', ownerName: 'Sam', ownerEmail: 'sam@example.com.au',
  phone: '0400 000 000', reviewUrl: 'https://g.page/r/EXAMPLE/review',
  services: ['plumber', 'leak', 'blocked drain', 'hot water'],
  serviceAreas: ['mona vale', '2103'], formSenders: ['notify@web3forms.com'],
  replyPromise: 'within one business day', chaseGaps: [2, 5, 7], sendHours: [8, 18],
};
const msg = (o) => Object.assign({ from: 'Jane Citizen <jane@gmail.com>', subject: '', body: '', headers: {} }, o);

test('urgent job in area with phone is hot', () => {
  const r = L.qualify(msg({ subject: 'Leak under sink', body: 'Burst pipe in Mona Vale, urgent. 0412 345 678' }), config);
  assert.strictEqual(r.grade, 'hot');
  assert.ok(r.has.phone && r.has.area && r.has.service);
});

test('vague message with nothing useful needs a look', () => {
  assert.strictEqual(L.qualify(msg({ body: 'Hi, are you around next month?' }), config).grade, 'check');
});

test('SEO pitches are spam and get no reply', () => {
  const r = L.qualify(msg({ body: 'We offer SEO and backlink packages to get you on the first page of Google' }), config);
  assert.strictEqual(r.grade, 'spam');
});

test('words only count as whole words', () => {
  // "leakage" should not count as "leak"; "2103" should not match "21030"
  const r = L.qualify(msg({ body: 'Question about leakage near 21030' }), config);
  assert.strictEqual(r.has.service, false);
  assert.strictEqual(r.has.area, false);
});

test('newsletters and no-reply senders are automated', () => {
  assert.ok(L.isAutomated(msg({ from: 'Bunnings <noreply@bunnings.com.au>' }), config));
  assert.ok(L.isAutomated(msg({ headers: { 'List-Unsubscribe': '<mailto:x>' } }), config));
  assert.ok(!L.isAutomated(msg({}), config));
  assert.ok(!L.isAutomated(msg({ from: 'notify@web3forms.com' }), config), 'form notifications are real enquiries');
});

test('instant reply asks only for what is missing', () => {
  const m = msg({ body: 'Blocked drain in Mona Vale please, call 0412 345 678' });
  const body = L.buildInstantReply(m, L.qualify(m, config), config).body;
  assert.match(body, /^Hi Jane,/);
  assert.doesNotMatch(body, /your suburb/);
  assert.doesNotMatch(body, /best number/);
  assert.match(body, /photo/);
  assert.match(body, /automatic reply/);

  const m2 = msg({ from: 'jane@gmail.com', body: 'Need a plumber' });
  const body2 = L.buildInstantReply(m2, L.qualify(m2, config), config).body;
  assert.match(body2, /^Hi there,/);
  assert.match(body2, /your suburb, the best number to reach you on and a photo/);
});

test('quote chaser timing', () => {
  const day = 86400000;
  const sent = new Date('2026-10-01T09:00:00+10:00');
  const at = (d) => new Date(sent.getTime() + d * day);
  const quote = [{ fromOwner: false, date: at(-1) }, { fromOwner: true, date: sent }];
  assert.strictEqual(L.chaseDecision(quote, 0, at(1), config), 'wait');
  assert.strictEqual(L.chaseDecision(quote, 0, at(2), config), 'nudge1');
  const afterNudge = quote.concat([{ fromOwner: true, date: at(2) }]);
  assert.strictEqual(L.chaseDecision(afterNudge, 1, at(6), config), 'wait');
  assert.strictEqual(L.chaseDecision(afterNudge, 1, at(7), config), 'nudge2');
  const afterNudge2 = afterNudge.concat([{ fromOwner: true, date: at(7) }]);
  assert.strictEqual(L.chaseDecision(afterNudge2, 2, at(14), config), 'cold');
  const replied = afterNudge.concat([{ fromOwner: false, date: at(3) }]);
  assert.strictEqual(L.chaseDecision(replied, 1, at(9), config), 'replied');
});

test('every customer gets the review link, no review gating', () => {
  const body = L.buildAfterJobEmail('Jane', config).body;
  assert.ok(body.includes(config.reviewUrl));
  assert.match(body, /1 \(poor\) to 5 \(great\)/);
});

test('reads scores and ignores quoted history', () => {
  assert.deepStrictEqual(L.readScore('5'), { score: 5, mood: 'happy' });
  assert.deepStrictEqual(L.readScore('4/5 thanks mate'), { score: 4, mood: 'happy' });
  assert.deepStrictEqual(L.readScore('2. Left a mess'), { score: 2, mood: 'unhappy' });
  assert.deepStrictEqual(L.readScore('Not happy, they were late'), { score: 1, mood: 'unhappy' });
  assert.deepStrictEqual(L.readScore('Great job!'), { score: 5, mood: 'happy' });
  assert.strictEqual(L.readScore('Call me about the invoice').mood, 'unclear');
  const quoted = 'Fantastic\n\nOn Mon, 1 Oct 2026, Sam wrote:\n> How did we go, from 1 (poor) to 5 (great)?';
  assert.deepStrictEqual(L.readScore(quoted), { score: 5, mood: 'happy' });
  assert.strictEqual(L.readScore('> 1 (poor) to 5\nok').mood, 'unclear');
  assert.strictEqual(L.readScore('call 0412 345 678').mood, 'unclear', 'phone numbers are not scores');
});

test('send hours and search labels', () => {
  assert.ok(L.inSendHours(8, config));
  assert.ok(!L.inSendHours(18, config));
  assert.strictEqual(L.searchLabel('Never Miss a Job/Quote sent'), 'label:never-miss-a-job-quote-sent');
});
