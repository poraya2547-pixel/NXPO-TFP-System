"""New acc64ee behavior against the original code; snapshots and synthetic inputs only."""
import json
import numpy as np
import pandas as pd
import pytest

import parity
from test_parity_cases import load_original, load_new, pipeline, outcome
from app import codec, compute, page_api
from app.modeling import tfp


def test_new_variable_numerical_paths():
    from ui_parity import load_snapshot_df
    old, new = load_original(), load_new()
    raw = load_snapshot_df()
    # Explicit synthetic coverage for INDUS when the frozen sheet does not contain it.
    raw['INDUS_GDP'] = np.linspace(.21, .34, len(raw))
    for var in tfp.CANDIDATE_VARS:
        if var in tfp.LONG_RUN_VARS:
            continue
        for diff, lag in [(1, 0), (2, 2)]:
            lr = [*tfp.LONG_RUN_VARS, var]
            sr = [s for s in tfp.SHORT_RUN_SPEC if s[0] != var] + [(var, diff, lag)]
            a, b = pipeline(old, raw.copy(), lr, sr), pipeline(new, raw.copy(), lr, sr)
            assert a == b, (var, diff, lag)
    # Exercise the new cointegration limitation branch with many regressors.
    lr = [v for v in tfp.CANDIDATE_VARS if v in tfp.build_model_frame(raw).columns][:8]
    assert pipeline(old, raw.copy(), lr, tfp.SHORT_RUN_SPEC) == pipeline(new, raw.copy(), lr, tfp.SHORT_RUN_SPEC)
    frame = old['T'].build_model_frame(raw)
    assert outcome(old['T'].adf_skv_compare, frame) == outcome(tfp.adf_skv_compare, frame)


def test_dataframe_attributes_and_old_payload():
    frame = pd.DataFrame({'value': [0.1]})
    frame.attrs['codes'] = ['ln_TFPI']
    packed = codec.encode(frame)
    assert codec.decode(packed).attrs == frame.attrs
    del packed['df']['attrs']
    assert codec.decode(packed).attrs == {}


def test_added_variable_ui_matches_original(tmp_path, monkeypatch):
    # Kept after isolation checks; no Streamlit import during collection.
    from streamlit.testing.v1 import AppTest
    import ui_capture, ui_parity, stage
    from app.store_memory import MemoryStore
    import csv

    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(parity.REPO))
    app_stage = stage.make_stage(tmp_path/'original')
    raw = ui_parity.load_snapshot_df()
    raw['INDUS_GDP'] = np.linspace(.21, .34, len(raw))
    values = {'portal_role':'research', 'research_authenticated':True, 'page':'home',
              'gsheet_loaded_at':ui_capture.FIXED_LOADED_AT}
    at = AppTest.from_file(str(app_stage/stage.APP_FILE), default_timeout=900)
    for k,v in ui_capture.TEST_SECRETS.items():at.secrets[k]=v
    for k,v in dict(values,gsheet_raw_df=raw.copy()).items():at.session_state[k]=v
    rows=list(csv.DictReader(ui_parity.FETCH_LOG.open(encoding='utf-8-sig')))
    store=MemoryStore(fetch_log=rows)
    d=ui_parity.Driver(store,store.add_dataset(raw))
    d.state={'dataset_id':d.dataset_id,'values':codec.encode(values)}
    rec=ui_capture.Recorder(tmp_path/'captures')

    def compare(name, action=None, event=None, no_fit=False):
        if action:action(at)
        at.run()
        assert not at.exception
        rec.snap(at,name,0)
        # Populate only worker results before disallowing model fits in the page.
        if no_fit:
            calls=[]
            def fail(*a,**k):
                calls.append(True)
                raise AssertionError('API must not fit ADF')
            with monkeypatch.context() as m:
                m.setattr(tfp,'adf_report',fail)
                d.run(event)
            assert not calls
        else:d.run(event)
        cap=json.loads((tmp_path/'captures'/f'{name}.json').read_text())
        diffs=ui_parity.compare_state(cap,d.tree,d.values(),store._downloads_by_ref())
        assert not diffs, diffs

    compare('initial')
    variable='ln_PATENT_GDP'
    selected=[s[0] for s in tfp.SHORT_RUN_SPEC]+[variable]
    event={'values':{'ms_sr_vars':[d.option_index('ms_sr_vars',v) for v in selected]}}
    compare('new_variable_defaults',lambda a:a.multiselect(key='ms_sr_vars').set_value(selected),event,no_fit=True)
    compare('difference_and_lag',lambda a:(a.selectbox(key=f'sr_diff_{variable}').set_value(2),
            a.selectbox(key=f'sr_lag_{variable}').set_value(2)),
            {'values':{f'sr_diff_{variable}':1,f'sr_lag_{variable}':2}},no_fit=True)
    compare('reason',lambda a:(a.text_area(key='var_change_reason').input('ทดสอบตัวแปรใหม่'),
            a.text_input(key='confirm_phrase_input').input('ยืนยันการปรับตัวแปร')),
            {'values':{'var_change_reason':'ทดสอบตัวแปรใหม่','confirm_phrase_input':'ยืนยันการปรับตัวแปร'}},no_fit=True)
    confirm=d.by_label('button','✅')['id']
    compare('confirmed',lambda a:ui_capture.by_label(a.button,'✅').click(),{'trigger':confirm})
    assert (variable,2,2) in d.values()['active_short_run_spec']
    reset=d.by_label('button','↩️')['id']
    compare('reset',lambda a:ui_capture.by_label(a.button,'↩️').click(),{'trigger':reset})
    assert d.values()['active_short_run_spec']==tfp.SHORT_RUN_SPEC
