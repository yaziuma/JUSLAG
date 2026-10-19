from datetime import datetime
from pathlib import Path

import yaml

from juslag.decision_scope import build_decision_scopes
from juslag.services.daily_report import build_daily_report
from juslag.services.backtest import BacktestParams
from juslag.services.notify import build_slack_summary
from juslag.services.site import _render_index, _summary_table


def manual_config():
    return yaml.safe_load((Path(__file__).resolve().parents[1]/'config/manual_strategy.yaml').read_text())


def daily():
    return {'execution_target_jp_date':'2026-10-15','signal_reference_us_date':'2026-10-14',
            'tradeable':False,'trade_block_reason':'strategy_rule_skip',
            'strategy_context':{'open_gap':None},
            'strategy_decision':{'rule_id':'rule_406_no_flip','action':'skip'},'rows':[]}


def test_missing_research_gap_is_not_a_new_manual_gate():
    scopes=build_decision_scopes(manual_config(),daily())
    operational=scopes['operational_manual']
    assert operational['requires_execution_day_open_gap'] is False
    assert operational['entry_submission_deadline_jst']=='08:55'
    assert operational['authorization']=='not_assessed_by_daily_research'
    assert operational['authoritative_preflight'].endswith('/2026-10-15.json')
    assert scopes['research_daily']['tradeable'] is False
    assert scopes['research_daily']['open_gap'] is None
    assert 'orders' not in scopes and 'intent' not in scopes


def test_report_keeps_legacy_result_but_labels_scope():
    ds=daily()
    report=build_daily_report(date='2026-10-15',bt={},ds=ds,fetch_result={},params=BacktestParams(),
        settings_name='fixture',history_entry={},slack_fallback_text='',
        generated_at_utc='2026-10-14T23:41:49Z',manual_config=manual_config())
    assert report['daily_signal']==ds
    assert report['decision_scopes']['research_daily']['trade_block_reason']=='strategy_rule_skip'
    assert report['decision_scopes']['operational_manual']['requires_execution_day_open_gap'] is False


def test_notification_does_not_present_research_skip_as_manual_skip():
    text=build_slack_summary({},daily(),datetime.fromisoformat('2026-10-15T08:42:00+09:00'),manual_config=manual_config())
    assert '研究用日次判定' in text and '研究比較バックテスト' in text
    assert 'pca_sub_long_5d_manual_v2' in text
    assert '当日open_gapは不要' in text
    assert '当日の手動戦略preflight' in text


def test_missing_operational_preflight_never_falls_back_to_research_authorization():
    ds=daily()
    ds['tradeable']=True
    ds['trade_block_reason']=None
    report={'date':'2026-10-15','daily_signal':ds,'backtest':{'judge':{'overall_decision':'pass'}}}
    html=_render_index([], [report])
    assert '運用プリフライト未確認' in html
    assert '研究用の日次判定は代用しません' in html
    assert '発注準備完了' not in html
    assert '日次研究比較' in _summary_table(report)


def test_operational_preflight_cannot_borrow_research_or_other_manual_judge():
    report={'date':'2026-10-15','daily_signal':daily(),
            'backtest':{'judge':{'overall_decision':'pass','overall_score':99}}}
    operational={'preflight':{'as_of':'2026-10-15','strategy_id':'pca_sub_long_5d_manual_v2',
                              'status':'READY','action':'ENTRY'}}
    html=_render_index([], [report], operational=operational,
        capital_simulation={'strategy_name':'pca_sub_long_5d_manual_v1',
                            'judge':{'overall_decision':'pass','overall_score':98}})
    assert '手動戦略のモデル審査情報未確認' in html
    assert '発注準備完了' not in html


def test_expiry_view_projection_compares_instants_across_timezones():
    # View-only expiry projection; no OrderIntent schema, orders, or builder.
    report={'date':'2026-10-15','daily_signal':daily()}
    view={'preflight':{'as_of':'2026-10-15','strategy_id':'pca_sub_long_5d_manual_v2',
                       'status':'READY','action':'ENTRY'},
          'intent':{'expires_at':'2026-10-15T08:55:00+09:00'},
          'rendered_at':'2026-10-15T07:00:00+00:00'}
    capital={'strategy_name':'pca_sub_long_5d_manual_v2',
             'judge':{'overall_decision':'pass','overall_score':78}}
    html=_render_index([], [report], capital_simulation=capital, operational=view)
    assert '期限切れ' in html
    assert '発注準備完了' not in html


def test_unknown_strategy_does_not_inherit_manual_gap_contract():
    config=manual_config()
    config['strategy_id']='unreviewed_strategy'
    scope=build_decision_scopes(config,daily())['operational_manual']
    assert scope['requires_execution_day_open_gap'] is None
    assert scope['authorization']=='not_assessed_by_daily_research'
