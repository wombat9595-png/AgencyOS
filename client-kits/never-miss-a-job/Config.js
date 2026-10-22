// Never Miss a Job: one client's settings.
// Fill this in with the client, then run setup() once from the Apps Script editor.

var CONFIG = {
  businessName: 'Example Plumbing',
  ownerName: 'Sam',
  // The address the client sends quotes from. Messages from here count as "from the business".
  ownerEmail: 'sam@exampleplumbing.com.au',
  phone: '0400 000 000',
  // Where hot-lead and unhappy-customer alerts go. Can be the same as ownerEmail.
  alertEmail: 'sam@exampleplumbing.com.au',
  // The client's Google review link (Google Business Profile > Ask for reviews).
  reviewUrl: 'https://g.page/r/EXAMPLE/review',
  // Words that mean "this is work we do". Lower case.
  services: ['plumber', 'plumbing', 'leak', 'blocked drain', 'hot water', 'tap', 'toilet', 'gas fitting'],
  // Suburbs or postcodes the client covers. Leave empty to treat everywhere as in area.
  serviceAreas: ['mona vale', 'newport', 'dee why', '2103', '2106', '2099'],
  // Senders of website form notifications (Web3Forms, Squarespace, Wix and so on).
  formSenders: ['notify@web3forms.com', 'no-reply@squarespace.info', 'wix-forms@wix.com'],
  // How soon the owner promises a personal reply, in plain words.
  replyPromise: 'within one business day',
  // Quote chaser: days after the quote for nudge 1, then after nudge 1 for nudge 2,
  // then after nudge 2 before the quote is marked cold.
  chaseGaps: [2, 5, 7],
  // Only send nudges and job-done emails between these hours (24 h, client's time zone).
  sendHours: [8, 18],
  // 'drafts' = write every email as a Gmail draft for the client to check and send.
  // 'send'   = send automatically. Only switch after the client has seen a week of drafts.
  mode: 'drafts',
};
