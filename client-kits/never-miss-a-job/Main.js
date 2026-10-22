// Never Miss a Job: the Gmail side. Runs inside the client's own Google account
// (Apps Script, free), so it keeps working when Benji's Mac is asleep and costs nothing.
// The decisions live in Logic.js; this file only reads and writes Gmail.

var ROOT = 'Never Miss a Job';
var L = {
  seen: ROOT + '/Seen',
  replied: ROOT + '/Replied',
  hot: ROOT + '/Hot lead',
  warm: ROOT + '/Warm lead',
  check: ROOT + '/Check this one',
  spam: ROOT + '/Spam',
  quoteSent: ROOT + '/Quote sent',       // the client adds this to a thread after sending a quote
  chase1: ROOT + '/Chase 1 sent',
  chase2: ROOT + '/Chase 2 sent',
  quoteReplied: ROOT + '/Quote replied',
  quoteCold: ROOT + '/Quote gone cold',
  jobDone: ROOT + '/Job done',           // the client adds this when a job is finished
  asked: ROOT + '/Asked how we went',
  happy: ROOT + '/Happy customer',
  unhappy: ROOT + '/Unhappy customer',
  feedbackCheck: ROOT + '/Check feedback',
};

// Run once from the editor. Creates the labels and the timers.
function setup() {
  Object.keys(L).forEach(function (k) { label_(L[k]); });
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('startedAt')) props.setProperty('startedAt', String(Date.now()));
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('checkEnquiries').timeBased().everyMinutes(5).create();
  ScriptApp.newTrigger('runHourly').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('weeklySummary').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(8).create();
}

function runHourly() {
  chaseQuotes();
  sendAfterJob();
  checkFeedback();
}

// 01 + 03: answer every new enquiry within minutes and sort it.
function checkEnquiries() {
  var startedAt = Number(PropertiesService.getScriptProperties().getProperty('startedAt') || Date.now());
  var threads = GmailApp.search('in:inbox newer_than:2d -from:me -' + searchLabel(L.seen), 0, 30);
  threads.forEach(function (thread) {
    seen_(thread);
    if (thread.getMessageCount() !== 1) return; // an ongoing conversation, not a new enquiry
    var m = thread.getMessages()[0];
    if (m.getDate().getTime() < startedAt) return; // never answer mail from before setup
    var msg = plain_(m);
    if (isFromOwner(msg, CONFIG) || isAutomated(msg, CONFIG)) return;
    if (isFormNotification(msg, CONFIG)) {
      if (!m.getReplyTo()) { thread.addLabel(label_(L.check)); return; } // no customer address to reply to
      msg.customerName = firstName(m.getReplyTo());
    }
    var result = qualify(msg, CONFIG);
    if (result.grade === 'spam') { thread.addLabel(label_(L.spam)); return; }
    var labelFor = { hot: L.hot, warm: L.warm, check: L.check };
    thread.addLabel(label_(labelFor[result.grade]));
    reply_(m, buildInstantReply(msg, result, CONFIG).body);
    thread.addLabel(label_(L.replied));
    if (result.grade === 'hot') {
      alert_('Hot lead: ' + m.getSubject(),
        'Why it looks hot: ' + result.reasons.join(', ') + '.\n\nOpen it: ' + thread.getPermalink());
    }
  });
}

// 04: chase quotes that went quiet, then mark them cold.
function chaseQuotes() {
  if (!inSendHours(hourNow_(), CONFIG)) return;
  var q = searchLabel(L.quoteSent) + ' -' + searchLabel(L.quoteReplied) + ' -' + searchLabel(L.quoteCold);
  GmailApp.search(q, 0, 50).forEach(function (thread) {
    var msgs = realMessages_(thread);
    var stage = hasLabel_(thread, L.chase2) ? 2 : hasLabel_(thread, L.chase1) ? 1 : 0;
    var shape = msgs.map(function (m) { return { fromOwner: isFromOwner(plain_(m), CONFIG), date: m.getDate() }; });
    var step = chaseDecision(shape, stage, new Date(), CONFIG);
    if (step === 'replied') thread.addLabel(label_(L.quoteReplied));
    if (step === 'cold') thread.addLabel(label_(L.quoteCold));
    if (step === 'nudge1' || step === 'nudge2') {
      toCustomer_(thread, buildNudge(step, customerName_(thread), CONFIG).body);
      thread.addLabel(label_(step === 'nudge1' ? L.chase1 : L.chase2));
    }
  });
}

// 28 + 13: after every finished job, ask how it went and share the review link.
function sendAfterJob() {
  if (!inSendHours(hourNow_(), CONFIG)) return;
  var props = PropertiesService.getScriptProperties();
  GmailApp.search(searchLabel(L.jobDone) + ' -' + searchLabel(L.asked), 0, 50).forEach(function (thread) {
    var email = buildAfterJobEmail(customerName_(thread), CONFIG);
    toCustomer_(thread, email.body);
    props.setProperty('asked_' + thread.getId(), String(Date.now()));
    thread.addLabel(label_(L.asked));
  });
}

// 27: read the answer. Unhappy customers go straight to the owner.
function checkFeedback() {
  var props = PropertiesService.getScriptProperties();
  var q = searchLabel(L.asked) + ' -' + searchLabel(L.happy) + ' -' + searchLabel(L.unhappy) +
    ' -' + searchLabel(L.feedbackCheck);
  GmailApp.search(q, 0, 50).forEach(function (thread) {
    var askedAt = Number(props.getProperty('asked_' + thread.getId()) || 0);
    var answers = realMessages_(thread).filter(function (m) {
      return !isFromOwner(plain_(m), CONFIG) && m.getDate().getTime() > askedAt;
    });
    if (!answers.length) return;
    var last = answers[answers.length - 1];
    var read = readScore(last.getPlainBody());
    if (read.mood === 'unclear') { thread.addLabel(label_(L.feedbackCheck)); return; }
    thread.addLabel(label_(read.mood === 'happy' ? L.happy : L.unhappy));
    reply_(last, buildThanks(read.mood, firstName(last.getFrom()), CONFIG).body);
    if (read.mood === 'unhappy') {
      alert_('Unhappy customer - please call them',
        'They scored the job ' + (read.score || '?') + ' out of 5.\n\nOpen it: ' + thread.getPermalink());
    }
  });
}

// Monday 8 am: what the system did last week, so the client sees the value.
function weeklySummary() {
  function count(name) { return GmailApp.search(searchLabel(name) + ' newer_than:7d', 0, 500).length; }
  var lines = [
    'Last 7 days from Never Miss a Job:',
    '',
    'Enquiries answered within minutes: ' + count(L.replied) + ' (' + count(L.hot) + ' hot)',
    'Quotes chased: ' + (count(L.chase1) + count(L.chase2)) + ', of which ' + count(L.quoteReplied) + ' replied',
    'Customers asked for a review: ' + count(L.asked),
    'Happy: ' + count(L.happy) + '   Unhappy (call them): ' + count(L.unhappy),
  ];
  GmailApp.sendEmail(CONFIG.alertEmail, 'Your week: Never Miss a Job', lines.join('\n'));
}

// ---- helpers ----

function label_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

function hasLabel_(thread, name) {
  return thread.getLabels().some(function (l) { return l.getName() === name; });
}

function seen_(thread) { thread.addLabel(label_(L.seen)); }

function plain_(m) {
  var headers = {};
  ['List-Unsubscribe', 'List-Id', 'Auto-Submitted', 'Precedence'].forEach(function (h) {
    var v = m.getHeader(h);
    if (v) headers[h] = v;
  });
  return { from: m.getFrom(), subject: m.getSubject(), body: m.getPlainBody(), headers: headers };
}

function realMessages_(thread) {
  return thread.getMessages().filter(function (m) { return !m.isDraft(); });
}

function lastCustomerMessage_(thread) {
  var msgs = realMessages_(thread).filter(function (m) { return !isFromOwner(plain_(m), CONFIG); });
  return msgs.length ? msgs[msgs.length - 1] : null;
}

function customerName_(thread) {
  var c = lastCustomerMessage_(thread);
  return c ? firstName(c.getReplyTo() || c.getFrom()) : '';
}

// Replies to a customer's own message, keeping the thread together.
function reply_(message, body) {
  if (CONFIG.mode === 'send') message.reply(body);
  else message.createDraftReply(body);
}

// For threads that may only hold the client's own messages (a quote they sent first).
function toCustomer_(thread, body) {
  var c = lastCustomerMessage_(thread);
  if (c) return reply_(c, body);
  var first = realMessages_(thread)[0];
  var to = first.getTo();
  var subject = /^re:/i.test(first.getSubject()) ? first.getSubject() : 'Re: ' + first.getSubject();
  if (CONFIG.mode === 'send') GmailApp.sendEmail(to, subject, body);
  else GmailApp.createDraft(to, subject, body);
}

// Alerts go to the client only, so they send even in drafts mode.
function alert_(subject, body) {
  if (CONFIG.alertEmail) GmailApp.sendEmail(CONFIG.alertEmail, subject, body);
}

function hourNow_() {
  return Number(Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'H'));
}
