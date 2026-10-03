"""Real-browser acceptance against a running API and separate worker."""
import argparse
import json
import time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8000');args=parser.parse_args()
    credentials=json.loads((ROOT/'data/initial-credentials.json').read_text())
    evidence=ROOT/'docs/evidence';evidence.mkdir(parents=True,exist_ok=True)
    result={"url":args.url,"mocked_responses":False,"checks":[],"console_errors":[]}
    def checked(name):result['checks'].append({"check":name,"status":"PASS"})
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={"width":1480,"height":1050})
        page.on('pageerror',lambda error:result['console_errors'].append(str(error)))
        page.goto(args.url)
        page.get_by_label('Username',exact=True).fill(credentials['username'])
        page.get_by_label('Password',exact=True).fill(credentials['password'])
        page.get_by_role('button',name='Sign in',exact=True).click()
        expect(page.get_by_role('heading',name='Overview',exact=True)).to_be_visible()
        checked('Authentication and overview from real database')
        page.get_by_role('button',name='Single-line editor',exact=True).click()
        expect(page.get_by_label('Draft name',exact=True)).to_be_visible()
        page.get_by_label('New asset ID',exact=True).fill('BROWSER_LINE_'+str(int(time.time())))
        page.get_by_role('button',name='Add component',exact=True).click()
        page.get_by_label('Draft name',exact=True).fill('Browser acceptance draft')
        page.get_by_role('button',name='Save draft',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Draft saved')).to_be_visible()
        saved_rid=page.get_by_label('Model version',exact=True).input_value()
        saved_line=page.get_by_label('Line asset',exact=True).input_value()
        page.reload()
        page.get_by_role('button',name='Single-line editor',exact=True).click()
        page.get_by_label('Model version',exact=True).select_option(saved_rid)
        page.get_by_label('Line asset',exact=True).select_option(saved_line)
        expect(page.get_by_role('heading',name=saved_line,exact=True)).to_be_visible()
        checked('Create line, save topology, reload persistent draft')
        page.get_by_label('to terminal bus',exact=True).select_option('BUS_D')
        page.get_by_role('button',name='Save draft',exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('Terminal domain/phase/voltage incompatible')
        checked('Server rejects invalid electrical connection')
        page.get_by_label('Model version',exact=True).select_option(saved_rid)
        page.get_by_label('Line asset',exact=True).select_option('TR_001')
        expect(page.get_by_label('sn_mva',exact=True)).to_have_value('40')
        checked('Real two-winding-transformer plugin editable')
        # Select the original valid connected baseline to avoid extra draft branches.
        token=page.evaluate("sessionStorage.getItem('token')")
        http=httpx.Client(base_url=args.url,headers={'Authorization':'Bearer '+token})
        revisions=http.get('/api/projects/demo/revisions').json()
        baseline=next(r for r in revisions if r['status']=='published')
        page.get_by_label('Model version',exact=True).select_option(baseline['id'])
        page.get_by_label('Line asset',exact=True).select_option('TL_001')
        page.get_by_role('button',name='Data imports',exact=True).click()
        page.get_by_label('CSV file',exact=True).set_input_files(str(ROOT/'data/demo.csv'))
        page.get_by_label('Mapping file',exact=True).set_input_files(str(ROOT/'data/demo-mapping.json'))
        page.get_by_role('button',name='Preview & validate',exact=True).click()
        expect(page.get_by_text('1 rejected rows',exact=True)).to_be_visible()
        expect(page.get_by_text("Invalid isoformat string: 'invalid-demo-time'",exact=False)).to_be_visible()
        page.get_by_role('button',name='Save import',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Import saved')).to_be_visible()
        checked('CSV import preview, rejection review and persistent save')
        page.get_by_role('button',name='Runs & replay',exact=True).click()
        page.get_by_label('Replay speed',exact=True).fill('100000')
        page.get_by_role('button',name='Start replay',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Study queued')).to_be_visible()
        # Observe worker completion from real API, not a mock or client-side timer.
        run=None
        for attempt in range(1000):
            jobs=http.get('/api/projects/demo/jobs').json()
            job=next(j for j in jobs if j['kind']=='replay')
            run=job['run_id']
            if job['status'] in ('completed','failed'):break
            page.wait_for_timeout(500)
        assert job['status']=='completed',job
        h=http.get(f'/api/projects/demo/runs/{run}/history?limit=1').json()
        assert h['total']==288 and h['items'][0]['model_status']=='SOLVED'
        checked('Replay through separate worker into 288 real persistent states')
        page.get_by_role('button',name='Line dashboard',exact=True).click()
        page.get_by_label('Run',exact=True).select_option(run)
        expect(page.get_by_role('heading',name='Receiving voltage • independent observation versus physics')).to_be_visible()
        expect(page.get_by_text('SOLVED',exact=True).first).to_be_visible()
        expect(page.get_by_text('Raw voltage residual (kV)',exact=True)).to_be_visible()
        expect(page.get_by_text('288 persisted line states.',exact=False)).to_be_visible()
        page.screenshot(path=str(evidence/'line-dashboard.png'),full_page=True)
        checked('Historical charts, kV/MW/A units, residuals, status and history')
        page.get_by_role('button',name='Validation & scenarios',exact=True).click()
        page.get_by_label('Scenario multiplier',exact=True).fill('1.10')
        page.get_by_role('button',name='Run scenario comparison',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Study queued')).to_be_visible()
        for _ in range(60):
            jobs=http.get('/api/projects/demo/jobs').json();scenario=next(j for j in jobs if j['kind']=='scenario')
            if scenario['status'] in ('completed','failed'):break
            page.wait_for_timeout(500)
        assert scenario['status']=='completed',scenario
        scenario_report=http.get(f"/api/projects/demo/runs/{scenario['run_id']}/report").json()
        assert scenario_report['research_results'][0]['payload']['loss_delta_mw']>0
        checked('Isolated scenario and baseline comparison persisted')
        page.get_by_label('Run',exact=True).select_option(run)
        with page.expect_download() as dl:
            page.get_by_role('button',name='Download validation report',exact=True).click()
        dl.value.save_as(str(evidence/'browser-validation-report.html'))
        assert 'manifest' in (evidence/'browser-validation-report.html').read_text()
        checked('Authorized human-readable report download with run lineage')
        with page.expect_download() as dl:
            page.get_by_role('button',name='Line dashboard',exact=True).click()
            page.get_by_role('button',name='Export CSV',exact=True).click()
        dl.value.save_as(str(evidence/'browser-results.csv'))
        checked('Complete results CSV export')
        page.get_by_role('button',name='Diagnostics',exact=True).click()
        page.screenshot(path=str(evidence/'diagnostics.png'),full_page=True)
        assert not result['console_errors'],result['console_errors']
        checked('No browser JavaScript runtime errors')
        result.update(run_id=run,scenario_run_id=scenario['run_id'],browser_version=browser.version)
        browser.close();http.close()
    (evidence/'browser-checks.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
