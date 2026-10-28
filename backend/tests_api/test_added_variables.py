"""acc64ee variable controls through HTTP, persisted session and real Postgres jobs."""
from conftest import find, nodes, post_event, run_jobs
from test_reports import _research_home_with_data
from app.modeling import core, tfp


def test_new_short_run_variable_survives_http_and_database(client, fresh_db, monkeypatch):
    csrf = _research_home_with_data(client, fresh_db)
    view = client.get('/api/v1/view').json()
    widget = find(view, id='ms_sr_vars')[0]
    variable = 'ln_PATENT_GDP'
    codes = [s[0] for s in tfp.SHORT_RUN_SPEC] + [variable]
    indices = [widget['options'].index(core.var_label_with_abbr(v)) for v in codes]
    calls=[]
    def fail(*a, **kw):
        calls.append(True)
        raise AssertionError('HTTP page must read ADF from worker results')
    with monkeypatch.context() as m:
        m.setattr(tfp, 'adf_report', fail)
        r=post_event(client, csrf, values={'ms_sr_vars':indices})
        assert r.status_code==200 and not r.json()['pending']
        assert find(r.json(), id=f'sr_diff_{variable}') and find(r.json(), id=f'sr_lag_{variable}')
        r=post_event(client, csrf, values={f'sr_diff_{variable}':1,f'sr_lag_{variable}':2,
                    'var_change_reason':'ทดสอบ HTTP ตัวแปรใหม่','confirm_phrase_input':'ยืนยันการปรับตัวแปร'})
        assert r.status_code==200 and not calls
    confirm=next(n['id'] for n in nodes(r.json()) if n['type']=='button' and n['label'].startswith('✅'))
    v=post_event(client,csrf,trigger=confirm).json()
    while v['pending']:
        assert run_jobs(fresh_db)>0
        v=post_event(client,csrf,resume=True).json()
    # Reload through a new HTTP request: options and downloads come from persisted state/results.
    v=client.get('/api/v1/view').json()
    assert not v['pending']
    adf=find(v,id='dl_adf_detail')[0]
    assert client.get(adf['url']).status_code==200
    from app import codec, db
    with db.tx(fresh_db) as conn:
        rows=conn.execute('SELECT state FROM sessions').fetchall()
    states=[codec.decode(row[0]['values']) for row in rows if row[0].get('values')]
    assert any((variable,2,2) in state.get('active_short_run_spec',[]) for state in states)
