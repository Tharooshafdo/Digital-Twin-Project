"""Exercise map network failure on a real isolated API, without contacting Google."""
import json
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
import httpx
import uvicorn
from playwright.sync_api import sync_playwright, expect
from grid_twin.api import create_app

ROOT=Path(__file__).resolve().parents[1]

def main():
    credentials=json.loads((ROOT/'data/initial-credentials.json').read_text())
    with tempfile.TemporaryDirectory(prefix='grid-map-qualification-') as folder:
        copied=Path(folder)/'platform.db'
        with closing(sqlite3.connect(ROOT/'data/platform.db')) as source,closing(sqlite3.connect(copied)) as target:
            source.backup(target)
        os.environ['GOOGLE_MAPS_BROWSER_KEY']='test-key-network-blocked'
        app=create_app('sqlite:///'+str(copied).replace('\\','/'))
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8104,log_level='error'))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.1)
            assert server.started
            errors=[];blocked=[]
            with sync_playwright() as p:
                browser=p.chromium.launch();page=browser.new_page()
                def block(route):
                    blocked.append('Google Maps script');route.abort()
                page.route('https://maps.googleapis.com/**',block)
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto('http://127.0.0.1:8104')
                page.get_by_label('Username',exact=True).fill(credentials['username']);page.get_by_label('Password',exact=True).fill(credentials['password'])
                page.get_by_role('button',name='Sign in',exact=True).click()
                expect(page.get_by_text('Google Maps could not load.',exact=False)).to_be_visible(timeout=15000)
                expect(page.get_by_role('img',name='Geographic component coordinate map')).to_be_visible()
                expect(page.get_by_label('Map view',exact=True)).to_have_value('offline')
                assert len(blocked)==1 and not errors
                page.get_by_role('button',name='Locate BUS_D',exact=True).click()
                expect(page.get_by_label('Inspect component',exact=True)).to_have_value('BUS_D')
                browser.close()
            result={'status':'PASS','database':'isolated SQLite copy','backend_responses_mocked':False,
                'external_google_request':'blocked before network delivery',
                'checks':['Google script load failure shows visible message','Fallback renders coordinate map',
                    'Fallback map selection remains usable','No browser JavaScript runtime errors'],
                'valid_key_google_service':'NOT RUN'}
            (ROOT/'docs/evidence/map-fallback.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
            print(json.dumps(result,indent=2))
        finally:
            server.should_exit=True;thread.join(timeout=10);app.state.engine.dispose()

if __name__=='__main__':main()
