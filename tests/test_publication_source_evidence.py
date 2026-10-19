import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'scripts/ops/publish_operational_pages.py'
    spec=importlib.util.spec_from_file_location('publication_evidence',path)
    assert spec is not None and spec.loader is not None
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_publish_exact_attested_report_only(tmp_path):
    path=tmp_path/'data/reports/2026-10-15.json'
    path.parent.mkdir(parents=True)
    payload=json.dumps({'daily_signal':{'execution_target_jp_date':'2026-10-15'}}).encode()
    path.write_bytes(payload)
    metadata={'source_kind':'local','source_report':'data/reports/2026-10-15.json',
              'source_report_sha256':hashlib.sha256(payload).hexdigest()}
    result=module().referenced_source_evidence(tmp_path,{'as_of':'2026-10-15'},metadata)
    assert result=={'data/reports/2026-10-15.json':payload}
    path.write_text('{}')
    with pytest.raises(ValueError,match='checksum mismatch'):
        module().referenced_source_evidence(tmp_path,{'as_of':'2026-10-15'},metadata)


def test_signal_input_csv_is_included_only_with_matching_attestation(tmp_path):
    path=tmp_path/'data/manual_strategy/signals/2026-10-15.json'
    path.parent.mkdir(parents=True)
    payload=json.dumps({'daily_signal':{'execution_target_jp_date':'2026-10-15'}}).encode()
    path.write_bytes(payload)
    prices=path.with_suffix('.prices.csv')
    prices.write_text('ticker,date,open,close\n')
    meta={'source_kind':'local_signal','source_report':str(path.relative_to(tmp_path)),
          'source_report_sha256':hashlib.sha256(payload).hexdigest(),
          'source_prices_sha256':hashlib.sha256(prices.read_bytes()).hexdigest()}
    result=module().referenced_source_evidence(tmp_path,{'as_of':'2026-10-15'},meta)
    assert len(result)==2
    prices.write_text('changed')
    with pytest.raises(ValueError,match='sizing prices checksum mismatch'):
        module().referenced_source_evidence(tmp_path,{'as_of':'2026-10-15'},meta)


def test_reference_outside_report_tree_is_rejected_before_read(tmp_path):
    with pytest.raises(ValueError,match='outside allowed'):
        module().referenced_source_evidence(tmp_path,{'as_of':'2026-10-15'},
            {'source_kind':'local','source_report':'../private.json','source_report_sha256':'x'})


def test_symlinked_report_directory_cannot_read_another_source_tree(tmp_path):
    other=tmp_path/'other'
    other.mkdir()
    payload=json.dumps({'daily_signal':{'execution_target_jp_date':'2026-10-15'}}).encode()
    (other/'2026-10-15.json').write_bytes(payload)
    (tmp_path/'data').mkdir()
    (tmp_path/'data/reports').symlink_to(other,target_is_directory=True)
    with pytest.raises(ValueError,match='escapes its data directory'):
        module().referenced_source_evidence(tmp_path,{'as_of':'2026-10-15'},
            {'source_kind':'local','source_report':'data/reports/2026-10-15.json',
             'source_report_sha256':hashlib.sha256(payload).hexdigest()})


def test_unattested_remote_source_does_not_publish_local_files(tmp_path):
    assert module().referenced_source_evidence(tmp_path,{'as_of':'2026-10-15'},
        {'source_kind':'remote','source_report':'private.json'})=={}
