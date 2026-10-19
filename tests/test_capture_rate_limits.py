from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sqlite3
import sys

import pandas as pd
import pytest
from yfinance.exceptions import YFPricesMissingError, YFRateLimitError

ROOT=Path(__file__).resolve().parents[1]
spec=spec_from_file_location('capture_rate_limits',ROOT/'scripts/ops/capture_intraday.py')
assert spec is not None and spec.loader is not None
cap=module_from_spec(spec)
spec.loader.exec_module(cap)


def frame(day='2026-10-16'):
    return pd.DataFrame({'Open':[100.], 'High':[101.], 'Low':[99.], 'Close':[100.], 'Volume':[0]},index=pd.DatetimeIndex([f'{day} 09:00:00+09:00']))


def install(monkeypatch, responses, tickers=('1617.T','1620.T')):
    calls: list[str]=[]
    monkeypatch.setattr(cap,'JP_TICKERS',list(tickers))
    class Ticker:
        def __init__(self,ticker):
            self.ticker=ticker
        def history(self,**kwargs):
            assert kwargs['raise_errors'] is True
            calls.append(self.ticker)
            item=responses.pop(0)
            if isinstance(item,Exception):
                raise item
            return item
    monkeypatch.setattr(cap.yf,'Ticker',Ticker)
    monkeypatch.setattr(cap.time,'sleep',lambda _:None)
    return calls


def test_missing_retries_only_missing_and_keeps_real_bar(monkeypatch):
    calls=install(monkeypatch,[frame(),YFPricesMissingError('1620.T','no data'),frame()])
    bars=cap.download_with_retries('1d',target_day='2026-10-16')
    assert calls==['1617.T','1620.T','1620.T']
    assert cap._tickers_with_valid_rows(bars,'2026-10-16')=={'1617.T','1620.T'}
    assert bars[('1620.T','Volume')].iloc[0]==0


def test_rate_limit_stops_all_requests_and_preserves_partial(monkeypatch,tmp_path):
    calls=install(monkeypatch,[frame(),YFRateLimitError()])
    bars=cap.download_with_retries('1d',target_day='2026-10-16')
    assert calls==['1617.T','1620.T']
    assert bars.attrs['provider_rate_limited']
    db=tmp_path/'isolated.sqlite'
    cap.store_capture(db,bars,datetime(2026,10,16,12,tzinfo=timezone.utc))
    with sqlite3.connect(db) as conn:
        assert conn.execute('select ticker,open from intraday_bars').fetchall()==[('1617.T',100.)]


def test_first_request_rate_limit_does_not_retry(monkeypatch):
    calls=install(monkeypatch,[YFRateLimitError()])
    bars=cap.download_with_retries('1d')
    assert bars.empty and bars.attrs['provider_rate_limited']
    assert calls==['1617.T']


def test_previous_day_never_satisfies_current_day(monkeypatch):
    calls=install(monkeypatch,[frame('2026-10-15'),frame('2026-10-15')],tickers=('1620.T',))
    bars=cap.download_with_retries('1d',attempts=2,target_day='2026-10-16')
    assert calls==['1620.T','1620.T']
    assert cap._tickers_with_valid_rows(bars,'2026-10-16')==set()


def test_unknown_error_not_reported_as_missing(monkeypatch):
    install(monkeypatch,[RuntimeError('unexpected')])
    with pytest.raises(RuntimeError,match='unexpected'):
        cap.download_with_retries('1d')


def test_cooldown_survives_invocations_and_expires(tmp_path):
    from datetime import timedelta
    now=datetime(2026,10,16,12,tzinfo=timezone.utc)
    state=tmp_path/'cooldown.json'
    assert not cap.provider_cooldown_active(state,now)
    cap.record_provider_cooldown(state,now)
    assert cap.provider_cooldown_active(state,now+timedelta(minutes=59))
    assert not cap.provider_cooldown_active(state,now+timedelta(hours=1))


def test_malformed_cooldown_fails_closed(tmp_path):
    state=tmp_path/'cooldown.json'
    state.write_text('{}')
    with pytest.raises(KeyError):
        cap.provider_cooldown_active(state,datetime.now(timezone.utc))


def test_main_cooldown_makes_zero_requests(monkeypatch,tmp_path):
    db=tmp_path/'prices.sqlite'
    state=db.with_suffix('.provider-cooldown.json')
    cap.record_provider_cooldown(state,datetime.now(timezone.utc))
    monkeypatch.setattr(sys,'argv',['capture','--db',str(db)])
    def forbidden(*args,**kwargs):
        raise AssertionError('network attempted during cooldown')
    monkeypatch.setattr(cap,'download_with_retries',forbidden)
    with pytest.raises(SystemExit,match='cooldown active'):
        cap.main()
    assert not db.exists()


def test_main_partial_rate_limit_saves_data_then_fails(monkeypatch,tmp_path):
    db=tmp_path/'prices.sqlite'
    bars=pd.concat({'1617.T':frame()},axis=1)
    bars.attrs['provider_rate_limited']=True
    monkeypatch.setattr(sys,'argv',['capture','--db',str(db)])
    monkeypatch.setattr(cap,'download_with_retries',lambda *args,**kwargs:bars)
    with pytest.raises(SystemExit,match='partial data saved'):
        cap.main()
    assert db.exists()
    assert db.with_suffix('.provider-cooldown.json').exists()
