"""Design rules for client websites: niche looks from design/niches/*.md and the anti-slop checks.

The niche files use the DESIGN.md format (YAML front matter with tokens, then prose).
Only a small, validated token vocabulary is read, so a bad edit fails loudly here
instead of reaching a client's page.
"""
import os
import re

ROOT=os.path.dirname(os.path.abspath(__file__))
NICHES=os.path.join(ROOT,'design','niches')

# Phrases that make a site or email read as machine-written. Matched case-insensitively.
SLOP_PHRASES=('welcome to our website','look no further','one-stop shop','one stop shop','elevate','unlock',
  'unleash','seamless','cutting-edge','cutting edge','state-of-the-art','state of the art','next level',
  'next-level','game-changer','game changer','revolutionise','revolutionize',"in today's fast-paced",
  'in today’s fast-paced','we pride ourselves','passionate about','tailored solutions','your vision, our mission',
  'bring your vision to life','delve','nestled','lorem ipsum','solutions provider')

_COLOR=re.compile(r'#[0-9a-f]{6}')
_FONT=re.compile(r"[A-Za-z0-9 ',-]{1,200}")
_RADIUS=re.compile(r'[0-9]{1,3}px')


def _front_matter(text):
    """The two-level YAML subset the niche files use: `key: value` and one level of nesting."""
    if not text.startswith('---\n'):raise ValueError('missing front matter')
    block=text[4:text.index('\n---',4)]
    data={};section=None
    for line in block.splitlines():
        if not line.strip():continue
        key,_,value=line.strip().partition(':')
        value=value.strip()
        if len(value)>=2 and value[0]==value[-1]=='"':value=value[1:-1]
        if line.startswith('  '):
            if section is None:raise ValueError('nested key outside a section: '+key)
            data[section][key]=value
        elif value:
            data[key]=value;section=None
        else:
            data[key]={};section=key
    return data


def load_niche(path):
    with open(path,encoding='utf-8') as handle:data=_front_matter(handle.read())
    colors,type_,rounded=data['colors'],data['typography'],data['rounded']
    theme=dict(label=data['label'],layout=data['layout'],description=data['description'],
      ink=colors['ink'],paper=colors['paper'],accent=colors['accent'],muted=colors['muted'],line=colors['line'],
      display=type_['display'],body=type_['body'],display_weight=type_['display-weight'],display_case=type_['display-case'],
      card_radius=rounded['card'],button_radius=rounded['button'])
    for key in ('ink','paper','accent','muted','line'):
        if not _COLOR.fullmatch(theme[key]):raise ValueError(path+': bad colour '+key)
    for key in ('display','body'):
        if not _FONT.fullmatch(theme[key]):raise ValueError(path+': bad font stack '+key)
    if not re.fullmatch(r'[1-9]00',theme['display_weight']) or theme['display_case'] not in ('uppercase','none'):
        raise ValueError(path+': bad display type settings')
    for key in ('card_radius','button_radius'):
        if not _RADIUS.fullmatch(theme[key]):raise ValueError(path+': bad radius '+key)
    if not re.fullmatch(r'[a-z]{1,20}',theme['layout']):raise ValueError(path+': bad layout')
    return theme


def niche_themes():
    """{'builder': {...}, 'landscaper': {...}, ...} in a stable order."""
    return {name[:-3]:load_niche(os.path.join(NICHES,name)) for name in sorted(os.listdir(NICHES)) if name.endswith('.md')}


# Trade words from leads and briefs, matched to a niche look.
TRADE_HINTS=(('builder',('build','renovat','carpent','construct','extension','deck')),
  ('landscaper',('landscap','garden','lawn','mow','turf','tree','hedge')),
  ('salon',('salon','hair','beauty','barber','nail','lash','brow','spa')))


def niche_for(industry):
    text=(industry or '').casefold()
    for niche,words in TRADE_HINTS:
        if any(word in text for word in words):return niche
    return 'trades'


def slop_problems(text):
    text=(text or '').casefold()
    return [phrase for phrase in SLOP_PHRASES if phrase in text]


def _luminance(color):
    channels=[int(color[i:i+2],16)/255 for i in (1,3,5)]
    channels=[c/12.92 if c<=0.03928 else ((c+0.055)/1.055)**2.4 for c in channels]
    return 0.2126*channels[0]+0.7152*channels[1]+0.0722*channels[2]


def contrast(a,b):
    a,b=_luminance(a),_luminance(b)
    return (max(a,b)+0.05)/(min(a,b)+0.05)


def contrast_problems(theme):
    """Text pairs the site templates actually use, each held to WCAG AA (4.5:1)."""
    pairs=(('ink','paper','body text'),('muted','paper','secondary text'),('accent','paper','links and labels'),
      ('#ffffff','accent','button text'),('ink','#ffffff','text on white cards'),('muted','#ffffff','secondary text on white cards'),
      ('#ffffff','ink','footer text'))
    problems=[]
    for fg,bg,label in pairs:
        ratio=contrast(theme.get(fg,fg),theme.get(bg,bg))
        if ratio<4.5:problems.append(f'{label} contrast is {ratio:.1f}:1 (needs 4.5:1)')
    return problems
