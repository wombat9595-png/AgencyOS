"""Phase 6 website lifecycle tests use synthetic accepted briefs only."""
import json
import os
import unittest
from contextlib import closing
from unittest.mock import patch
from pathlib import Path
import test_phase5 as fixtures
import app as application
import sales_engine as engine
import website_builder
import sales_ai
from phase3_store import connect


class WebsiteBuilderTest(unittest.TestCase):
    def setUp(self):
        fixtures.SalesTest.setUp(self)
        self._new_defaults={'lead_id':'1','package_ids':['1']}
    tearDown=fixtures.SalesTest.tearDown
    post=fixtures.SalesTest.post
    rows=fixtures.SalesTest.rows
    sql=fixtures.SalesTest.sql
    settings=fixtures.SalesTest.settings
    package=fixtures.SalesTest.package
    def new(self, **changes):
        values=dict(lead_id=self._new_defaults['lead_id'],package_ids=self._new_defaults['package_ids'])
        values.update(changes)
        return fixtures.SalesTest.new(self,**values)
    work=fixtures.SalesTest.work
    outreach=fixtures.SalesTest.outreach
    prepare_message=fixtures.SalesTest.prepare_message
    approve_quote=fixtures.SalesTest.approve_quote
    accept=fixtures.SalesTest.accept

    def proposal_quote(self):
        self.prepare_message()
        flow_id=max(row['id'] for row in self.rows('p5_flows'))
        response=self.post(f'/sales/{flow_id}/proposal',dict(requirements='Fictional customer requested one service page',requirements_source='Synthetic fixture only',branding='Fictional blue branding',confirm='yes',mode='local'))
        self.assertEqual(response.status_code,302,response.data)
        self.work()
        proposal=max((row for row in self.rows('p5_drafts') if row['kind']=='proposal'),key=lambda row:row['id'])
        self.assertEqual(self.post(f"/sales/drafts/{proposal['id']}/approve",{'confirm':'yes'}).status_code,302)
        self.work()
        return max(self.rows('p5_quotes'),key=lambda row:row['id'])

    def accepted_project(self, category='one-page'):
        if category!='one-page':
            self.package(name='Fictional multi-page package',category=category,scope='A multi-page service website with a services page and contact page.')
            self.new(package_ids=['2'])
        quote=self.proposal_quote()
        self.approve_quote(quote)
        self.accept(quote)
        return self.rows('projects')[-1]['id']

    def build(self, project_id, **fields):
        values={'confirm':'yes','theme':'coastal'}; values.update(fields)
        response=self.post(f'/projects/{project_id}/website/generate',values)
        self.assertEqual(response.status_code,302,response.data)
        self.assertEqual(self.post(f'/projects/{project_id}/website/generate',values).status_code,400)
        self.assertTrue(self.work())
        return self.rows('p6_site_versions')[-1]

    def test_one_page_build_runs_worker_and_static_qa_passes(self):
        project_id=self.accepted_project()
        page=self.client.get(f'/projects/{project_id}/website')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Generate website',page.data)
        self.assertEqual(self.post(f'/projects/{project_id}/website/generate',{'theme':'coastal'}).status_code,400)
        version=self.build(project_id)
        self.assertEqual(version['version'],1)
        self.assertEqual(version['status'],'Needs review')
        self.assertEqual(json.loads(version['qa_json'])['passed'],True,version['qa_json'])
        pages=json.loads(version['pages_json'])
        self.assertEqual(set(pages),{'index'})
        self.assertIn('<form',pages['index'])
        self.assertIn('required',pages['index'])
        self.assertIn('name="viewport"',pages['index'])
        self.assertNotIn('<script',pages['index'])
        self.assertEqual(len(self.rows('invoices')),0)

    def test_multi_page_navigation_preview_and_owner_isolation(self):
        self.sql("UPDATE leads SET industry='Landscaping' WHERE id=1")
        project_id=self.accepted_project('multi-page')
        version=self.build(project_id,theme='earth')
        pages=json.loads(version['pages_json'])
        self.assertEqual(set(pages),{'index','services','about','contact'})
        self.assertIn('?page=services',pages['index'])
        self.assertIn('?page=contact',pages['services'])
        self.assertIn('Landscaping',json.loads(version['content_json'])['industry'])
        self.assertEqual(json.loads(version['qa_json'])['passed'],True,version['qa_json'])
        site=self.rows('p6_sites')[0]
        preview=self.client.get(f"/websites/{site['id']}/preview/1?viewport=mobile")
        self.assertEqual(preview.status_code,200)
        self.assertIn(b'sandbox="allow-forms"',preview.data)
        source=self.client.get(f"/websites/{site['id']}/source/1?page=services")
        self.assertEqual(source.status_code,200)
        self.assertIn('Content-Security-Policy',source.headers)
        self.assertIn('sandbox;',source.headers['Content-Security-Policy'])
        self.assertIn(b'Services',source.data)
        self.assertEqual(self.client.get(f"/websites/{site['id']}/source/1?page=missing").status_code,404)
        with self.client.session_transaction() as session:
            session['user_id']=2
        self.assertEqual(self.client.get(f"/websites/{site['id']}/preview/1").status_code,404)

    def test_two_fictional_industries_generate_independent_sites(self):
        first_project=self.accepted_project()
        self.build(first_project)
        self.post('/leads',dict(business_name='Fictional Canberra Landscapes',industry='Landscaping',location='Canberra',website='https://landscapes.example/',email='landscapes@example.com'))
        self.package(name='Fictional landscaping multi-page',category='multi-page',scope='A multi-page landscaping service website.',exclusions='Hosting, domain and publication')
        self._new_defaults={'lead_id':'2','package_ids':['2']}
        second_project=self.accepted_project()
        self.build(second_project,theme='earth')
        sites=self.rows('p6_sites')
        self.assertEqual(len(sites),2)
        contents=[json.loads(row['content_json']) for row in self.rows('p6_site_versions')]
        self.assertEqual({item['industry'] for item in contents},{'Design','Landscaping'})

    def test_revision_restore_and_approval_are_versioned_and_gated(self):
        project_id=self.accepted_project()
        first=self.build(project_id)
        site=self.rows('p6_sites')[0]
        self.assertEqual(self.post(f"/websites/{site['id']}/approve/1",{'confirm':'yes'}).status_code,302)
        self.assertEqual(self.rows('p6_site_versions')[0]['status'],'Approved')
        self.assertEqual(self.post(f"/websites/{site['id']}/revise",{'revision_note':'headline: A clearer service headline','theme':'studio'}).status_code,302)
        self.assertTrue(self.work())
        version2=self.rows('p6_site_versions')[1]
        self.assertEqual(version2['version'],2)
        self.assertIn('A clearer service headline',json.loads(version2['content_json'])['pages'][0]['heading'])
        self.assertEqual(version2['theme'],'studio')
        self.assertEqual(self.post(f"/websites/{site['id']}/restore/1",{}).status_code,302)
        version3=max(self.rows('p6_site_versions'),key=lambda row:row['version'])
        self.assertEqual(version3['version'],3)
        self.assertEqual(version3['status'],'Needs review')
        self.assertEqual(version3['html'],first['html'])
        self.sql("UPDATE p6_site_versions SET qa_json=? WHERE site_id=? AND version=3",(json.dumps({'passed':False,'critical_errors':['synthetic blocker']}),site['id']))
        self.assertEqual(self.post(f"/websites/{site['id']}/approve/3",{'confirm':'yes'}).status_code,400)
        self.assertEqual(max(self.rows('p6_site_versions'),key=lambda row:row['version'])['status'],'Needs review')

    def test_generated_markup_escapes_brief_text_and_never_executes_it(self):
        self.sql("UPDATE leads SET business_name=? WHERE id=1",('<script>alert(1)</script> & Studio',))
        project_id=self.accepted_project()
        version=self.build(project_id)
        html=version['html']
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
        self.assertEqual(json.loads(version['qa_json'])['passed'],True,version['qa_json'])

    def test_ai_assisted_copy_requires_existing_exact_approval_and_renders_only_text(self):
        project_id=self.accepted_project()
        with patch.dict(os.environ,fixtures.CONFIG):
            self.settings(daily_cents='100',daily_requests='1',input_rate='1000000',output_rate='1000000',pricing_model='synthetic-model',pricing_review='yes')
            response=self.post(f'/projects/{project_id}/website/generate',{'confirm':'yes','theme':'coastal','mode':'ai'})
            self.assertEqual(response.status_code,302)
            job=self.rows('p5_jobs')[-1]
            self.assertEqual(job['status'],'Awaiting approval')
            with closing(connect(application.DB_PATH)) as conn:
                hashed,cents=sales_ai.approval(conn,job)
            self.assertEqual(self.post(f"/sales/jobs/{job['id']}/decision",{'decision':'Approve AI','confirm':'yes','approval_hash':hashed,'maximum_cents':str(cents)}).status_code,302)
            with patch('sales_engine.sales_ai.execute',return_value={'subject':'A clear home headline','body':'Ask about the services in this accepted brief.','evidence_ids':[],'limitation':'Synthetic mocked copy; not verified.'}):
                self.assertTrue(self.work())
        version=self.rows('p6_site_versions')[0]
        html=json.loads(version['pages_json'])['index']
        self.assertIn('A clear home headline',html)
        self.assertNotIn('<script',html)
        self.assertEqual(json.loads(version['qa_json'])['passed'],True)

    def test_qa_blocks_missing_navigation_and_unsupported_claims(self):
        brief={'requirements':'A synthetic page only.'}
        content={'services':[{'title':'Service','description':'Supplied service'}],'testimonials':[],
                 'limitations':['No address or credentials were invented.']}
        unsafe='<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width"><meta name="description" content="x"></head><body><nav><a href="#missing">Missing</a></nav><main><h1>Guaranteed results</h1></main><footer></footer><form action="#"></form></body></html>'
        result=website_builder.quality_check({'index':unsafe},brief,content)
        self.assertFalse(result['passed'])
        self.assertTrue(any('missing section' in issue for issue in result['critical_errors']))
        self.assertTrue(any('Unsupported business claim' in issue for issue in result['critical_errors']))

