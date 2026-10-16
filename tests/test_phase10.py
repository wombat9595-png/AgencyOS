"""Phase 10 release checks use private synthetic staging artifacts only."""
import json
import tempfile
import unittest
from pathlib import Path

import test_phase5 as sales_fixtures
import test_phase6 as site_fixtures
import p10_release
import app as application
from phase3_store import WorkflowError


class LocalReleaseTest(unittest.TestCase):
    setUp=sales_fixtures.SalesTest.setUp
    tearDown=sales_fixtures.SalesTest.tearDown
    post=sales_fixtures.SalesTest.post
    rows=sales_fixtures.SalesTest.rows
    sql=sales_fixtures.SalesTest.sql
    settings=sales_fixtures.SalesTest.settings
    package=sales_fixtures.SalesTest.package
    work=sales_fixtures.SalesTest.work

    def setUp(self):
        sales_fixtures.SalesTest.setUp(self)
        self._new_defaults={'lead_id':'1','package_ids':['1']}
        self.stage_tmp=tempfile.TemporaryDirectory()
        self.old_root=application.app.config.get('AGENCYOS_STAGING_ROOT')
        application.app.config['AGENCYOS_STAGING_ROOT']=Path(self.stage_tmp.name)

    def tearDown(self):
        if self.old_root is None:application.app.config.pop('AGENCYOS_STAGING_ROOT',None)
        else:application.app.config['AGENCYOS_STAGING_ROOT']=self.old_root
        self.stage_tmp.cleanup()
        sales_fixtures.SalesTest.tearDown(self)

    def accepted_project(self):return site_fixtures.WebsiteBuilderTest.accepted_project(self)
    def build(self,project_id,**fields):return site_fixtures.WebsiteBuilderTest.build(self,project_id,**fields)
    def proposal_quote(self):return site_fixtures.WebsiteBuilderTest.proposal_quote(self)
    prepare_message=sales_fixtures.SalesTest.prepare_message
    outreach=sales_fixtures.SalesTest.outreach
    new=sales_fixtures.SalesTest.new
    approve_quote=sales_fixtures.SalesTest.approve_quote
    accept=sales_fixtures.SalesTest.accept

    def approve(self,site_id,version):
        return self.post(f'/websites/{site_id}/approve/{version}',{'confirm':'yes'})

    def stage(self,site_id,version):
        return self.post(f'/websites/{site_id}/stage/{version}',{'confirm':'yes'})

    def test_approved_release_stages_locally_checks_and_rolls_back_with_audit(self):
        project_id=self.accepted_project()
        self.build(project_id)
        site=self.rows('p6_sites')[0]
        self.assertEqual(self.approve(site['id'],1).status_code,302)
        self.assertEqual(self.stage(site['id'],1).status_code,302)
        first=self.rows('p10_releases')[0]
        self.assertEqual(first['status'],'Current')
        artifact=Path(self.stage_tmp.name)/first['artifact_path']
        self.assertTrue((artifact/'index.html').is_file())
        self.assertTrue((artifact/'manifest.json').is_file())
        self.assertEqual(self.post(f"/websites/releases/{first['id']}/check",{}).status_code,302)
        self.assertEqual(self.rows('p10_checks')[0]['result'],'passed')

        self.assertEqual(self.post(f"/websites/{site['id']}/revise",{'revision_note':'headline: Updated synthetic headline','theme':'studio'}).status_code,302)
        self.assertTrue(self.work())
        self.assertEqual(self.approve(site['id'],2).status_code,302)
        self.assertEqual(self.stage(site['id'],2).status_code,302)
        second=self.rows('p10_releases')[-1]
        self.assertEqual(second['status'],'Current')
        self.assertEqual(self.post(f"/websites/{site['id']}/rollback/{first['id']}",{'confirm':'yes'}).status_code,302)
        states={row['id']:row['status'] for row in self.rows('p10_releases')}
        self.assertEqual(states[first['id']],'Current')
        self.assertEqual(states[second['id']],'Staged')
        self.assertEqual(self.rows('p10_events')[-1]['kind'],'rollback')
        page=self.client.get(f'/projects/{project_id}/website')
        self.assertIn(b'does not publish',page.data.lower())

    def test_integrity_failure_creates_alert_and_does_not_repair_files(self):
        project_id=self.accepted_project();self.build(project_id)
        site=self.rows('p6_sites')[0];self.approve(site['id'],1);self.stage(site['id'],1)
        release=self.rows('p10_releases')[0]
        page=Path(self.stage_tmp.name)/release['artifact_path']/'index.html'
        original=page.read_bytes();page.write_bytes(original+b'<!-- changed -->')
        self.post(f"/websites/releases/{release['id']}/check",{})
        self.assertEqual(self.rows('p10_checks')[-1]['result'],'failed')
        self.assertEqual(page.read_bytes(),original+b'<!-- changed -->')
        self.assertEqual(len(self.rows('p10_alerts')),1)
        self.assertEqual(self.rows('p10_alerts')[0]['severity'],'attention')

    def test_adapter_rejects_scripts_traversal_and_invalid_manifest_paths(self):
        adapter=p10_release.LocalStagingAdapter(self.stage_tmp.name)
        for pages in ({'index':'<html><script>alert(1)</script></html>'},{'../escape':'<html></html>'},{'about':'<html></html>'}):
            with self.assertRaises(WorkflowError):adapter.stage(1,1,pages)
        self.assertFalse((Path(self.stage_tmp.name).parent/'escape.html').exists())
        with self.assertRaises(WorkflowError):p10_release.PublicDeploymentUnavailableAdapter().deploy('local/path',{})
        outside=Path(self.stage_tmp.name).parent/(Path(self.stage_tmp.name).name+'-outside')
        outside.mkdir()
        (Path(self.stage_tmp.name)/'site-9').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(WorkflowError):adapter.stage(9,1,{'index':'<html></html>'})
        self.assertEqual(list(outside.iterdir()),[])
        outside.rmdir()

    def test_non_owner_cannot_create_or_view_site_release(self):
        project_id=self.accepted_project();self.build(project_id)
        site=self.rows('p6_sites')[0];self.approve(site['id'],1)
        with self.client.session_transaction() as session:session['user_id']=2
        self.assertEqual(self.stage(site['id'],1).status_code,404)
        self.assertEqual(len(self.rows('p10_releases')),0)


if __name__=='__main__':unittest.main()
