"""House style (design/DESIGN.md): niche looks, colour checks and the anti-slop phrase list."""
import unittest
import design_system
import playbook
import website_builder
from phase3_store import WorkflowError
from static_safety import static_errors


def content(theme='builder',phone='0412 345 678',intro='Decks, extensions and bathroom renovations across the Northern Beaches.'):
    return dict(name='Harbour Build Co',industry='Builder',theme=theme,
      pages=[dict(slug='index',label='Home',title='Harbour Build Co',heading='Harbour Build Co',intro=intro,kind='home',sections=['services','about','contact'])],
      services=[dict(title='Deck repairs',description='Fix or replace tired decking.'),dict(title='Extensions',description='Extra rooms, done properly.')],
      contact_email='',contact_phone=phone,about='',testimonials=[],limitations=[])


class DesignSystemTest(unittest.TestCase):
    def test_niche_looks_load_and_pass_contrast(self):
        themes=design_system.niche_themes()
        self.assertEqual(set(themes),{'builder','landscaper','salon','trades'})
        for key,theme in website_builder.THEMES.items():
            self.assertEqual(design_system.contrast_problems(theme),[],key)

    def test_contrast_check_catches_weak_colours(self):
        weak=dict(design_system.niche_themes()['trades'],muted='#bbbbbb')
        self.assertTrue(any('secondary text' in p for p in design_system.contrast_problems(weak)))

    def test_every_look_renders_safe_markup_with_tap_to_call(self):
        for key in website_builder.THEMES:
            pages=website_builder.render_site(content(key))
            self.assertEqual(static_errors(pages['index']),[],key)
            self.assertIn('href="tel:0412345678">Call 0412 345 678</a>',pages['index'])
            self.assertTrue(website_builder.quality_check(pages,{},content(key))['checks']['design_rules'],key)
        no_phone=website_builder.render_site(content(phone=''))['index']
        self.assertIn('>Get in touch</a>',no_phone)

    def test_quality_check_blocks_stock_phrases(self):
        sloppy=content(intro='Look no further: we elevate your outdoor space.')
        qa=website_builder.quality_check(website_builder.render_site(sloppy),{},sloppy)
        self.assertFalse(qa['passed']);self.assertFalse(qa['checks']['design_rules'])
        self.assertTrue(any('"look no further"' in e for e in qa['critical_errors']))

    def test_ai_copy_with_stock_phrases_is_refused(self):
        result=dict(content=content(),brief={})
        with self.assertRaises(WorkflowError):
            website_builder.apply_ai_copy(result,dict(subject='Unlock your dream home',body='Seamless renovations.',evidence_ids=[],limitation=''))

    def test_niche_for_trade(self):
        self.assertEqual(design_system.niche_for('Home builder'),'builder')
        self.assertEqual(design_system.niche_for('Gardeners and landscapers'),'landscaper')
        self.assertEqual(design_system.niche_for('Hair salon'),'salon')
        self.assertEqual(design_system.niche_for('Plumber'),'trades')

    def test_email_review_flags_machine_written_phrases(self):
        p=dict(name='Harbour Build Co',email='a@b.com');s=dict(name='Benji Price',business='Benji Price Web Design')
        body='Hi Harbour Build Co team,\n\nI can help you unlock more jobs.\n\nCheers, Benji Price, Benji Price Web Design. Reply "no thanks" to stop.'
        self.assertIn('sounds machine-written ("unlock")',playbook.review('Quick idea',body,p,s))


if __name__=='__main__':
    unittest.main()
