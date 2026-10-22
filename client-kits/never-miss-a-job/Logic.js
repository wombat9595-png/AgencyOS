// Never Miss a Job: the decisions, kept free of Gmail calls so they can be tested in Node.
// Main.js feeds these plain objects built from Gmail messages.

var URGENT_WORDS = ['urgent', 'asap', 'emergency', 'today', 'tonight', 'flooding', 'burst', 'no hot water', 'leaking'];
var SPAM_WORDS = ['seo', 'backlink', 'guest post', 'first page of google', 'crypto', 'bitcoin', 'loan',
  'web design services', 'increase your traffic', 'dear sir/madam', 'unsubscribe from this list'];
var AUTOMATED_SENDERS = ['noreply', 'no-reply', 'donotreply', 'do-not-reply', 'mailer-daemon', 'notifications@', 'postmaster'];

function lower(s) { return String(s || '').toLowerCase(); }

function hasWord(text, word) {
  var escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp('(^|[^a-z0-9])' + escaped + '($|[^a-z0-9])').test(text);
}

function emailAddress(from) {
  var m = String(from || '').match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/);
  return m ? m[0].toLowerCase() : '';
}

// Website form notifications come from the form service; everything else is a person.
function isFormNotification(msg, config) {
  var sender = emailAddress(msg.from);
  return (config.formSenders || []).some(function (f) { return lower(f) === sender; });
}

// Newsletters, receipts and bounces never get an automatic reply.
function isAutomated(msg, config) {
  if (isFormNotification(msg, config)) return false;
  var sender = emailAddress(msg.from);
  if (AUTOMATED_SENDERS.some(function (a) { return sender.indexOf(a) !== -1; })) return true;
  var h = msg.headers || {};
  if (h['List-Unsubscribe'] || h['List-Id']) return true;
  if (h['Auto-Submitted'] && lower(h['Auto-Submitted']) !== 'no') return true;
  if (/^(bulk|list|junk)$/.test(lower(h['Precedence']))) return true;
  return false;
}

function isFromOwner(msg, config) {
  return emailAddress(msg.from) === lower(config.ownerEmail);
}

// 01 Lead qualification: rules, not a paid AI model, so it costs nothing to run.
function qualify(msg, config) {
  var text = lower(msg.subject) + '\n' + lower(msg.body);
  var reasons = [];
  var spamHits = SPAM_WORDS.filter(function (w) { return text.indexOf(w) !== -1; });
  var links = (text.match(/https?:\/\//g) || []).length;
  if (spamHits.length >= 2 || (spamHits.length === 1 && links >= 2) || links >= 5) {
    return { grade: 'spam', score: 0, reasons: ['looks like a sales pitch or spam'], has: {} };
  }
  var has = {
    service: (config.services || []).some(function (w) { return hasWord(text, lower(w)); }),
    area: !(config.serviceAreas || []).length ||
      config.serviceAreas.some(function (a) { return hasWord(text, lower(a)); }),
    phone: /(\+?61[\s-]?|0)[2-478](?:[\s-]?\d){8}\b/.test(text),
    urgent: URGENT_WORDS.some(function (w) { return hasWord(text, w); }),
  };
  var score = 0;
  if (has.service) { score += 2; reasons.push('asks for work you do'); }
  if (has.area && (config.serviceAreas || []).length) { score += 2; reasons.push('in your area'); }
  if (has.phone) { score += 1; reasons.push('left a phone number'); }
  if (has.urgent) { score += 2; reasons.push('sounds urgent'); }
  var grade = score >= 5 || (has.urgent && has.service) ? 'hot' : score >= 2 ? 'warm' : 'check';
  return { grade: grade, score: score, reasons: reasons, has: has };
}

function firstName(from) {
  var name = String(from || '').replace(/<.*>/, '').replace(/"/g, '').trim();
  if (!name || name.indexOf('@') !== -1) return '';
  return name.split(/\s+/)[0];
}

// 03 Email responder: the instant reply, asking only for what's missing.
function buildInstantReply(msg, result, config) {
  var name = msg.customerName || firstName(msg.from);
  var asks = [];
  if (!result.has.area && (config.serviceAreas || []).length) asks.push('your suburb');
  if (!result.has.phone) asks.push('the best number to reach you on');
  asks.push('a photo or two of the job, if you have them');
  var lines = [
    (name ? 'Hi ' + name + ',' : 'Hi there,'),
    '',
    'Thanks for getting in touch with ' + config.businessName + '. We\'ve got your message and ' +
      config.ownerName + ' will get back to you personally ' + config.replyPromise + '.',
    '',
    'To help us quote faster, could you reply with ' + joinList(asks) + '?',
  ];
  if (result.grade === 'hot') {
    lines.push('', 'If it can\'t wait, call ' + config.ownerName + ' on ' + config.phone + '.');
  }
  lines.push('', 'Cheers,', config.ownerName, config.businessName, config.phone, '',
    '(This is an automatic reply so you\'re not left waiting.)');
  return { body: lines.join('\n') };
}

function joinList(items) {
  if (items.length <= 1) return items.join('');
  return items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
}

function daysBetween(a, b) {
  return (b.getTime() - a.getTime()) / 86400000;
}

// 04 Follow-up automation: what the quote chaser should do with one quote thread.
// messages: [{fromOwner, date}] oldest first. stage: 0 none sent, 1 nudge 1 sent, 2 nudge 2 sent.
function chaseDecision(messages, stage, now, config) {
  if (!messages.length) return 'wait';
  var last = messages[messages.length - 1];
  if (!last.fromOwner) return 'replied';
  var gaps = config.chaseGaps || [2, 5, 7];
  var waited = daysBetween(last.date, now);
  if (stage === 0 && waited >= gaps[0]) return 'nudge1';
  if (stage === 1 && waited >= gaps[1]) return 'nudge2';
  if (stage === 2 && waited >= gaps[2]) return 'cold';
  return 'wait';
}

function buildNudge(step, customerName, config) {
  var hi = customerName ? 'Hi ' + customerName + ',' : 'Hi there,';
  var body = step === 'nudge1'
    ? 'Just checking the quote came through OK. Happy to answer any questions or adjust anything.'
    : 'Last check-in on the quote. If the timing\'s not right, no worries at all. ' +
      'If you\'d like to go ahead, just reply here and we\'ll lock in a time.';
  return { body: [hi, '', body, '', 'Cheers,', config.ownerName, config.businessName, config.phone].join('\n') };
}

// 28 Survey + 13 Review manager: one email after every finished job.
// Every customer gets the review link, whatever they might think. Google's policy bans
// "selectively soliciting positive reviews", so we never hold the link back from anyone.
function buildAfterJobEmail(customerName, config) {
  var hi = customerName ? 'Hi ' + customerName + ',' : 'Hi there,';
  return {
    subject: 'How did we go? - ' + config.businessName,
    body: [hi, '',
      'Thanks for choosing ' + config.businessName + '. How did we go, from 1 (poor) to 5 (great)? Just reply with a number.',
      '',
      'If anything wasn\'t right, reply and tell us. ' + config.ownerName + ' reads every one and will sort it out.',
      '',
      'If you have a minute, a Google review helps a small local business like ours more than anything:',
      config.reviewUrl,
      '', 'Cheers,', config.ownerName, config.businessName].join('\n'),
  };
}

// Drops quoted history so "On Mon, Sam wrote: ... 5 ..." doesn't count as the answer.
function newText(body) {
  var out = [];
  var lines = String(body || '').split(/\r?\n/);
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (/^On .+wrote:\s*$/.test(line.trim()) || /^-{2,}\s*Original Message/i.test(line.trim())) break;
    if (/^\s*>/.test(line)) continue;
    out.push(line);
  }
  return out.join('\n');
}

// 27 Feedback analyser: reads the customer's answer to "How did we go?".
function readScore(body) {
  var text = lower(newText(body));
  var m = text.match(/(?:^|[^0-9])([1-5])\s*(?:\/\s*5|out of 5|stars?)?(?![0-9])/);
  var score = m ? Number(m[1]) : null;
  if (score === null) {
    if (/\b(terrible|awful|poor|bad|disappointed|not happy|unhappy|rubbish)\b/.test(text)) score = 1;
    else if (/\b(excellent|amazing|fantastic|great|brilliant|awesome|perfect)\b/.test(text)) score = 5;
    else if (/\b(good|happy|thanks|thank you)\b/.test(text)) score = 4;
  }
  var mood = score === null ? 'unclear' : score >= 4 ? 'happy' : 'unhappy';
  return { score: score, mood: mood };
}

function buildThanks(mood, customerName, config) {
  var hi = customerName ? 'Hi ' + customerName + ',' : 'Hi there,';
  var body = mood === 'happy'
    ? 'Thanks so much, that means a lot to us.'
    : 'Thanks for telling us. ' + config.ownerName + ' will be in touch shortly to make it right.';
  return { body: [hi, '', body, '', 'Cheers,', config.ownerName, config.businessName].join('\n') };
}

function inSendHours(hour, config) {
  var h = config.sendHours || [8, 18];
  return hour >= h[0] && hour < h[1];
}

// Gmail search spells label "A/B c" as "a-b-c".
function searchLabel(name) {
  return 'label:' + lower(name).replace(/[\s/]+/g, '-');
}

if (typeof module !== 'undefined') {
  module.exports = {
    isAutomated: isAutomated, isFromOwner: isFromOwner, isFormNotification: isFormNotification,
    qualify: qualify, buildInstantReply: buildInstantReply, chaseDecision: chaseDecision,
    buildNudge: buildNudge, buildAfterJobEmail: buildAfterJobEmail, readScore: readScore,
    newText: newText, buildThanks: buildThanks, inSendHours: inSendHours, searchLabel: searchLabel,
    firstName: firstName, emailAddress: emailAddress,
  };
}
