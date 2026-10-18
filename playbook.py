"""The shared playbook every agent reads: who we are, what we offer, the rules, and a page per niche.

Rule-based and local. The Writer (rules or the optional AI) drafts from it, and every draft is
checked against it before it reaches the owner. Nothing here sends anything.
"""
import re

VOICE=('Write like a friendly local tradie talking to another small-business owner: short sentences, plain Australian English, '
  'no hype, no jargon, no exclamation marks, no fake urgency. Mention one real thing about their business. Never promise results.')
OFFER='a free one-page mock-up of their new website, made before they pay anything, with no obligation'
PACKAGES=('Care: A$800 build + A$69 a month','Autopilot: A$1,400 build + A$149 a month','Signature (animated story site): A$2,400 build + A$149 a month')
TERMS='Monthly plans are month to month with 30 days notice, no lock-in.'
OPT_OUT='If you would rather not hear from me, just reply "no thanks" and I will not contact you again.'
# Words that read as spam, overpromise, or breach the "no guaranteed results" rule in the packages.
BANNED=('guarantee','guaranteed','100%','act now','limited time','risk-free','risk free','#1','number one','skyrocket','!!')
MAX_WORDS={'first':170,'followup1':90,'followup2':80}

# Each niche: the angle that matters to that customer, and which scroll story suits their mock-up.
NICHES={
 'Builders':('people want to see finished homes and extensions before they call','builder'),
 'Carpenters':('photos of decks and custom work win the job','builder'),
 'Roofers':('homeowners after storm damage search on their phone and call the first site that looks trustworthy','builder'),
 'Painters':('before-and-after photos sell the job','builder'),
 'Electricians':('people need a fast tap-to-call button and proof you are licensed',''),
 'Plumbers':('most calls are urgent and come from a phone search, so a tap-to-call button matters most',''),
 'Gardeners and landscapers':('a backyard transformation is the best advert there is','landscaper'),
 'Hairdressers and barbers':('clients want to see your work and book online at 10 pm','salon'),
 'Beauty salons':('clients want to see prices, results and book online without calling','salon'),
}
STORIES={
 'builder':dict(title='Blueprint to finished house',demo='builder',name='Northline Building Co.',mark='N'),
 'landscaper':dict(title='Messy yard to pool and garden',demo='landscaper',name='Greenhaven Landscapes',mark='G'),
 'salon':dict(title='Cut, curls and colour',demo='salon',name='Maison Rosé Hair &amp; Beauty',mark='M'),
}


def niche_angle(trade):
    return NICHES.get(trade,('most customers check a business on their phone before they call',''))[0]


def story_for(trade):
    """The scroll-story mock-up that suits this trade, or None (they get the standard one-page mock-up)."""
    key=NICHES.get(trade,('',''))[1]
    return STORIES.get(key)


def brief(p,s,kind):
    """Everything the AI Writer needs, from the playbook and the lead's own record. No secrets, no other leads."""
    import json
    check=json.loads(p['site_check']) if p['site_check'] else {}
    return '\n'.join([
      'You write one cold email for a one-person Australian web design business. '+VOICE,
      'Sender: '+s['name']+', '+s['business']+(', based in '+s['area'] if s['area'] else '')+'.',
      'Offer: '+OFFER+'. Ask them to reply "yes" if they want it.',
      'Business: '+p['name']+' ('+(p['trade'] or 'local business')+') in '+(p['suburb'] or 'their area')+'.',
      'What we noticed about their website: '+(', '.join(check.get('findings') or [p['reason']]))+(' (site title: '+check['title']+')' if check.get('title') else '')+'.',
      'Why it matters for this kind of business: '+niche_angle(p['trade'])+'.',
      'Message type: '+{'first':'first email','followup1':'short first follow-up (they have not replied)','followup2':'short last follow-up, friendly, no pressure'}[kind]+
        ', at most '+str(MAX_WORDS[kind])+' words in the body.',
      'Do not mention prices. Do not invent facts, reviews, awards or numbers about them. Do not use: '+', '.join(BANNED)+'.',
      'Start the body with "Hi '+p['name']+' team,". Do not write a sign-off, signature or opt-out line; those are added for you.',
      'Reply with exactly two parts: a first line "Subject: ..." then the body.'])


def review(subject,body,p,s,kind='first'):
    """Problems that stop a draft reaching the owner. Empty list means it follows the playbook."""
    problems=[]
    text=(subject+'\n'+body).casefold()
    if not 1<=len(subject.strip())<=120:problems.append('subject missing or too long')
    if p['email'] and 'no thanks' not in body.casefold():problems.append('missing the "no thanks" opt-out (Spam Act)')
    if s['name'].casefold() not in body.casefold() or s['business'].casefold() not in body.casefold():problems.append('does not say who it is from (Spam Act)')
    for word in BANNED:
        if word in text:problems.append('uses "'+word+'"')
    if '[' in body or '{' in body:problems.append('has a placeholder left in it')
    words=len(re.findall(r"\b[\w'’-]+\b",body.split('\n\nCheers,')[0]))
    if kind in MAX_WORDS and words>MAX_WORDS[kind]+40:problems.append('too long ('+str(words)+' words)')
    if p['name'].casefold() not in text:problems.append('does not name the business')
    return problems
