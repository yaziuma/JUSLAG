import json
import sqlite3
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from juslag.turso_store import SnapshotError, ensure_schema, load_snapshot, publish_snapshot, read_snapshot

ROOT=Path(__file__).resolve().parents[1]
spec=spec_from_file_location('daily_candidate',ROOT/'scripts/ops/turso_daily.py')
assert spec is not None and spec.loader is not None
m=module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def inputs(tmp_path,monkeypatch):
    report=tmp_path/'report.json'
    history=tmp_path/'history.jsonl'
    report.write_text(json.dumps({'date':'2026-10-19','generated_at_utc':'2026-10-18T22:37:47Z'}))
    history.write_text(json.dumps({'jst_date':'2026-10-19','report':'data/reports/2026-10-19.json','summary':'offline','llm_status':'failed'})+'\n')
    monkeypatch.setenv('JUSLAG_WRITE_TURSO','1')
    monkeypatch.setenv('GITHUB_SHA','offline-test')
    return report,history


def args(monkeypatch,inputs,command='publish'):
    report,history=inputs
    monkeypatch.setattr(sys,'argv',['turso_daily',command,'--report',str(report),'--history',str(history)]+(['--run-id','actions:39172981424:1'] if command=='publish' else []))


class DB:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.closed=False
    def __getattr__(self,name):
        return getattr(self.db,name)
    def push(self):
        pass
    def close(self):
        self.closed=True
        self.db.close()


def connections(monkeypatch,tmp_path):
    made=[]
    def connect(_):
        conn=DB(tmp_path/'isolated.sqlite')
        made.append(conn)
        return conn
    monkeypatch.setattr(m,'connect',connect)
    return made


def diagnostic(exc):
    return json.loads(str(exc.value).split(' failed: ',1)[1])


def test_invalid_input_never_connects(inputs,monkeypatch):
    inputs[1].write_text('')
    args(monkeypatch,inputs)
    monkeypatch.setattr(m,'connect',lambda _:pytest.fail('must not connect for invalid input'))
    with pytest.raises(SystemExit) as exc:
        m.main()
    d=diagnostic(exc)
    assert d['stage']=='input_validation' and d['code']=='summary_missing'
    assert d['snapshot_state']=='not_attempted' and d['schema_state']=='not_attempted'


def test_local_check_never_connects_even_when_writes_disabled(inputs,monkeypatch,capsys):
    args(monkeypatch,inputs,'check')
    monkeypatch.delenv('JUSLAG_WRITE_TURSO')
    monkeypatch.setattr(m,'connect',lambda _:pytest.fail('check cannot connect'))
    m.main()
    assert 'PASS: local input date=2026-10-19' in capsys.readouterr().out


def test_publish_readback_and_retry_idempotence(inputs,monkeypatch,tmp_path,capsys):
    args(monkeypatch,inputs)
    made=connections(monkeypatch,tmp_path)
    m.main()
    assert 'PASS: published' in capsys.readouterr().out
    m.main()
    assert 'already published' in capsys.readouterr().out
    assert all(c.closed for c in made)
    with sqlite3.connect(tmp_path/'isolated.sqlite') as db:
        assert db.execute('select count(*) from juslag_daily_snapshots').fetchone()[0]==1


def test_verifier_connection_failure_marks_committed_unverified_and_redacts(inputs,monkeypatch,tmp_path):
    args(monkeypatch,inputs)
    made=connections(monkeypatch,tmp_path)
    base=m.connect
    def connect(path):
        if len(made)==1:
            raise ValueError('token=SYNTHETIC_SECRET_DO_NOT_LOG https://private.invalid')
        return base(path)
    monkeypatch.setattr(m,'connect',connect)
    with pytest.raises(SystemExit) as exc:
        m.main()
    d=diagnostic(exc)
    assert d['stage']=='verifier_connect' and d['snapshot_state']=='committed_unverified'
    assert 'SYNTHETIC_SECRET' not in str(exc.value) and 'private.invalid' not in str(exc.value)
    assert made[0].closed
    with sqlite3.connect(tmp_path/'isolated.sqlite') as db:
        assert db.execute('select count(*) from juslag_daily_snapshots').fetchone()[0]==1


def test_write_ack_failure_is_commit_unconfirmed(inputs,monkeypatch,tmp_path):
    args(monkeypatch,inputs)
    connections(monkeypatch,tmp_path)
    real=m.publish_snapshot
    def uncertain(*a,**kw):
        real(*a,**kw)
        raise ValueError('SDK opaque error')
    monkeypatch.setattr(m,'publish_snapshot',uncertain)
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert diagnostic(exc)['snapshot_state']=='commit_unconfirmed'
    with sqlite3.connect(tmp_path/'isolated.sqlite') as db:
        assert db.execute('select count(*) from juslag_daily_snapshots').fetchone()[0]==1


@pytest.mark.parametrize('value,code',[(None,'readback_missing'),({'content_hash':'different'},'readback_content_mismatch')])
def test_readback_failure_is_not_publish_success(inputs,monkeypatch,tmp_path,value,code):
    args(monkeypatch,inputs)
    made=connections(monkeypatch,tmp_path)
    monkeypatch.setattr(m,'read_snapshot',lambda *a,**kw:value)
    with pytest.raises(SystemExit) as exc:
        m.main()
    d=diagnostic(exc)
    assert d['stage']=='readback' and d['code']==code
    assert d['snapshot_state']=='committed_unverified'
    assert all(c.closed for c in made)


def test_conflicting_run_id_never_overwrites(inputs,monkeypatch,tmp_path):
    args(monkeypatch,inputs)
    connections(monkeypatch,tmp_path)
    m.main()
    inputs[0].write_text('{"date":"2026-10-19","changed":true}')
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert diagnostic(exc)['code']=='run_id_content_conflict'
    assert diagnostic(exc)['snapshot_state']=='not_written_this_attempt'
    with sqlite3.connect(tmp_path/'isolated.sqlite') as db:
        stored=read_snapshot(db,run_id='actions:39172981424:1')
        assert stored is not None
        assert 'changed' not in stored['report']


def test_read_by_exact_run_is_read_only_and_output_is_private(inputs,monkeypatch,tmp_path):
    report,history=inputs
    dbpath=tmp_path/'isolated.sqlite'
    with sqlite3.connect(dbpath) as db:
        ensure_schema(db)
        publish_snapshot(db,load_snapshot(report,history),run_id='actions:39172981424:1',source_commit='test',published_at_utc='2026-10-19T00:00Z')
    conn=DB(dbpath)
    statements: list[str]=[]
    conn.db.set_trace_callback(statements.append)
    monkeypatch.setattr(m,'connect',lambda _:conn)
    out=tmp_path/'read.json'
    monkeypatch.setattr(sys,'argv',['turso_daily','read','--run-id','actions:39172981424:1','--out',str(out)])
    m.main()
    assert all(s.lstrip().startswith('SELECT') for s in statements)
    assert out.stat().st_mode & 0o777==0o600
    assert json.loads(out.read_text())['run_id']=='actions:39172981424:1'
    assert conn.closed


def test_nonfinite_input_is_typed_without_dumping_values(inputs):
    report,history=inputs
    report.write_text('{"date":"2026-10-19","metric":NaN}')
    with pytest.raises(SnapshotError) as exc:
        load_snapshot(report,history)
    assert exc.value.code=='noncanonical_json'


def test_run_id_point_read_uses_primary_key():
    with sqlite3.connect(':memory:') as db:
        ensure_schema(db)
        plan=db.execute('EXPLAIN QUERY PLAN SELECT * FROM juslag_daily_snapshots WHERE run_id=?',('actions:39172981424:1',)).fetchall()
    assert any('SEARCH' in row[3] and 'INDEX' in row[3] for row in plan)


def test_schema_failure_reports_possible_schema_change_not_snapshot_write(inputs,monkeypatch,tmp_path):
    args(monkeypatch,inputs)
    made=connections(monkeypatch,tmp_path)
    def fail(_):
        raise ValueError('private SDK message')
    monkeypatch.setattr(m,'ensure_schema',fail)
    with pytest.raises(SystemExit) as exc:
        m.main()
    d=diagnostic(exc)
    assert d['stage']=='schema' and d['schema_state']=='change_unconfirmed'
    assert d['snapshot_state']=='not_attempted'
    assert made[0].closed


def test_readback_integrity_failure_is_typed(inputs,monkeypatch,tmp_path):
    args(monkeypatch,inputs)
    connections(monkeypatch,tmp_path)
    def fail(*a,**kw):
        raise SnapshotError('stored_hash_mismatch','snapshot hash mismatch')
    monkeypatch.setattr(m,'read_snapshot',fail)
    with pytest.raises(SystemExit) as exc:
        m.main()
    d=diagnostic(exc)
    assert d['stage']=='readback' and d['code']=='stored_hash_mismatch'
    assert d['snapshot_state']=='committed_unverified'


@pytest.mark.parametrize('status,label,code',[(401,'Unauthorized','remote_auth_rejected'),(403,'Forbidden','remote_access_forbidden')])
def test_sdk_auth_failure_is_bounded_and_redacted(inputs,monkeypatch,tmp_path,status,label,code):
    args(monkeypatch,inputs)
    connections(monkeypatch,tmp_path)
    def fail(_):
        raise ValueError(f'HTTP status {status} {label}; token=SYNTHETIC_SECRET_123')
    monkeypatch.setattr(m,'ensure_schema',fail)
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert diagnostic(exc)['code']==code
    assert diagnostic(exc)['stage']=='schema'
    assert 'SYNTHETIC_SECRET' not in str(exc.value)
