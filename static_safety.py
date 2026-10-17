"""Validate the deliberately small inert website output vocabulary."""
import re
from html.parser import HTMLParser


def static_errors(html):
    errors=[]
    class Parser(HTMLParser):
        def handle_starttag(self,tag,attrs):
            if tag in ('script','iframe','object','embed','base','svg','math','link'):
                errors.append('Active or external element: '+tag)
            for key,value in attrs:
                if key.startswith('on') or key in ('srcdoc','formaction'):
                    errors.append('Active attribute: '+key)
                if key in ('href','src','action') and value:
                    if not (value.startswith('#') or re.fullmatch(r'\?page=[a-z0-9-]{1,40}',value) or re.fullmatch(r'[a-z0-9-]{1,40}\.html(?:#[a-z0-9-]+)?',value) or (key=='href' and (re.fullmatch(r'mailto:[a-zA-Z0-9.!#$%&\x27*+/=_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+',value) or re.fullmatch(r'tel:\+?[0-9]{6,15}',value)))):
                        errors.append('Unapproved URL in '+key)
            if tag=='meta' and dict(attrs).get('http-equiv'):
                errors.append('Meta redirect/control is prohibited')
        handle_startendtag=handle_starttag
    try:Parser().feed(html)
    except Exception:errors.append('Invalid HTML')
    if re.search(r'url\s*\(|@import|expression\s*\(',html,re.I):errors.append('External or executable CSS is prohibited')
    return errors
