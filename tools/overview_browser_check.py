"""Real API/worker/browser qualification, applying changes only to a new test project."""
import json
import time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]

def main():
    credentials=json.loads((ROOT/'data/initial-credentials.json').read_text())
    evidence=ROOT/'docs/evidence';result={'mocked_backend_responses':False,'checks':[],'console_errors':[]}
    def checked(name):result['checks'].append({'check':name,'status':'PASS'})
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=20) as client:
        response=client.post('/api/auth/login',json={k:credentials[k] for k in ('username','password')});response.raise_for_status()
        client.headers['Authorization']='Bearer '+response.json()['token']
        demo=client.get('/api/projects/demo/overview').json()
        project=client.post('/api/projects',json={'name':'Overview browser qualification '+str(int(time.time()))});project.raise_for_status();pid=project.json()['id']
        base='/api/projects/'+pid
        response=client.post(base+'/revisions',json={'name':'Overview test baseline','network':demo['network'],'valid_from':'2020-01-01T00:00:00Z'});response.raise_for_status();rid=response.json()['id']
        client.post(base+'/revisions/'+rid+'/publish').raise_for_status()
        client.put(base+'/locations',json={'locations':[{k:c['location'][k] for k in ('asset_id','latitude','longitude','label','provenance')} for c in demo['components'] if c['location']]}).raise_for_status()
        def sample(revision):
            response=client.post(base+'/grid-observations',json={'snapshot_id':'browser-'+str(time.time_ns()),'revision_id':revision,
                'event_time':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                'source_id':'browser.synthetic.reference','data_origin':'synthetic',
                'frequency_hz':{'value':49.99,'quality':'GOOD'},'total_demand_mw':{'value':68.25,'quality':'GOOD'},
                'bus_voltages_kv':[{'asset_id':'BUS_A','value':132.1,'quality':'GOOD'},{'asset_id':'BUS_D','value':32.2,'quality':'GOOD'}]});response.raise_for_status()
        sample(rid)
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1536,'height':1100})
            page.on('pageerror',lambda error:result['console_errors'].append(str(error)))
            page.goto('http://127.0.0.1:8000');page.get_by_label('Username',exact=True).fill(credentials['username']);page.get_by_label('Password',exact=True).fill(credentials['password']);page.get_by_role('button',name='Sign in',exact=True).click()
            expect(page.get_by_role('heading',name='Overview',exact=True)).to_be_visible()
            expect(page.get_by_role('img',name='Geographic component coordinate map')).to_be_visible()
            expect(page.get_by_test_id('grid-demand')).not_to_contain_text('Unavailable',timeout=15000)
            expect(page.get_by_test_id('grid-frequency')).to_contain_text('Hz')
            checked('Admin lands on geographic overview with demand, frequency and voltage units')
            before=client.get('/api/projects/demo/overview').json()['telemetry']['event_time']
            for _ in range(30):
                page.wait_for_timeout(500)
                after=client.get('/api/projects/demo/overview').json()['telemetry']['event_time']
                if after!=before:break
            assert after!=before
            checked('Separate worker generates a new synthetic connected-grid snapshot at automatic cadence')
            page.get_by_role('button',name='Locate BUS_D',exact=True).click()
            expect(page.get_by_label('Inspect component',exact=True)).to_have_value('BUS_D')
            page.screenshot(path=str(evidence/'overview.png'),full_page=True)
            checked('Geographic map markers select the component inspector')
            page.get_by_label('Project',exact=True).select_option(pid)
            expect(page.get_by_test_id('grid-demand')).to_contain_text('68.25',timeout=10000)
            page.get_by_role('button',name='Edit locations',exact=True).click()
            page.get_by_label('Inspect component',exact=True).select_option('BUS_A')
            page.get_by_label('Asset latitude',exact=True).fill('6.9321')
            page.get_by_label('Location label',exact=True).fill('Browser test location')
            page.get_by_role('button',name='Save location',exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Location saved.')).to_be_visible()
            saved=client.get(base+'/overview').json();assert next(c for c in saved['components'] if c['id']=='BUS_A')['location']['latitude']==6.9321
            page.reload();page.get_by_label('Project',exact=True).select_option(pid)
            expect(page.locator('.asset-inspector')).to_contain_text('6.9321')
            checked('Location editor saves to real database and survives browser reload')
            page.locator('.simulation-choice').click()
            expect(page.get_by_role('heading',name='Simulate changes',exact=True)).to_be_visible()
            page.get_by_label('Demand multiplier (%)',exact=True).fill('120')
            page.get_by_label('Simulation tap TR_001',exact=True).fill('1')
            page.get_by_role('button',name='Run simulation',exact=True).click()
            expect(page.get_by_role('heading',name='Baseline versus proposed system',exact=True)).to_be_visible(timeout=30000)
            expect(page.locator('.simulation-results')).to_contain_text('81.60 MW')
            apply=page.get_by_role('button',name='Apply to platform model',exact=True)
            expect(apply).to_be_enabled()
            page.screenshot(path=str(evidence/'simulation.png'),full_page=True)
            checked('Simulation runs real baseline/candidate network solves including changed transformer tap')
            page.get_by_label('Demand multiplier (%)',exact=True).fill('125');expect(apply).to_be_disabled()
            checked('Editing the candidate invalidates the previous simulation review')
            page.get_by_role('button',name='Run simulation',exact=True).click()
            expect(page.locator('.simulation-results')).to_contain_text('85.00 MW',timeout=30000)
            jobs=client.get(base+'/jobs').json();run=next(j['run_id'] for j in jobs if j['kind']=='scenario' and j['status']=='completed')
            manifest=client.get(base+'/runs/'+run+'/report').json()['manifest']
            apply.click()
            expect(page.get_by_role('status').filter(has_text='Simulation published to the platform model.')).to_be_visible(timeout=15000)
            current=client.get(base+'/overview').json()['revision_id'];assert current!=rid
            assert client.get(base+'/runs/'+run+'/report').json()['manifest']==manifest
            assert client.get(base+'/revisions/'+current).json()['status']=='published'
            result.update(test_project_id=pid,applied_revision_id=current,simulation_run_id=run)
            checked('Administrator publishes the exact tested candidate into a new model version; prior run stays immutable')
            sample(current)
            page.get_by_role('button',name='Back to overview',exact=False).click()
            page.locator('.inspection-choice').click()
            expect(page.get_by_role('heading',name='Inspect operating data',exact=True)).to_be_visible()
            expect(page.get_by_role('heading',name='Operating observations',exact=True)).to_be_visible()
            page.get_by_label('Telemetry source',exact=True).select_option('live')
            expect(page.get_by_test_id('grid-demand')).to_contain_text('Unavailable',timeout=10000)
            expect(page.get_by_text('No live field source is connected.',exact=False)).to_be_visible()
            page.screenshot(path=str(evidence/'inspection.png'),full_page=True)
            checked('Inspection separates live field source from demo and keeps missing field readings unavailable')
            page.get_by_label('Project',exact=True).select_option('demo')
            page.get_by_label('Inspection view',exact=True).select_option('history')
            runs=client.get('/api/projects/demo/runs').json();recorded=next(r for r in runs if r['kind']=='replay' and client.get('/api/projects/demo/runs/'+r['id']+'/report').json()['states']>0)
            page.get_by_label('Recorded operating run',exact=True).select_option(recorded['id'])
            expect(page.get_by_text('persisted line states',exact=False)).to_be_visible()
            page.get_by_role('button',name='Inspect charts and detailed history',exact=True).click()
            expect(page.get_by_label('Run',exact=True)).to_have_value(recorded['id'])
            checked('Recorded-history inspection reads persistent run summaries')
            page.get_by_role('button',name='Sign out',exact=True).click()
            page.get_by_label('Password',exact=True).fill(credentials['password'])
            page.get_by_role('button',name='Sign in',exact=True).click()
            expect(page.get_by_role('heading',name='Overview',exact=True)).to_be_visible()
            checked('Fresh administrator login always returns to Overview')
            assert result['console_errors']==[],result['console_errors']
            checked('No browser JavaScript runtime errors')
            result['browser_version']=browser.version;result['google_maps']='NOT RUN: no supplied browser API key'
            browser.close()
        client.post('/api/auth/logout').raise_for_status()
    (evidence/'overview-browser-checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
