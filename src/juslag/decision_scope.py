"""Label operational and research decisions without issuing authorization."""
from __future__ import annotations


def build_decision_scopes(manual_config: dict, daily_signal: dict) -> dict:
    strategy = manual_config.get('strategy_id')
    known = strategy in {'pca_sub_long_5d_manual_v1', 'pca_sub_long_5d_manual_v2'}
    target = daily_signal.get('execution_target_jp_date') or '<JP-date>'
    decision = daily_signal.get('strategy_decision') or {}
    return {
        'operational_manual': {
            'strategy_id': strategy,
            'entry_submission_deadline_jst': manual_config['execution']['entry_order_deadline_jst'],
            'execution': manual_config['execution'].get('entry'),
            'requires_execution_day_open_gap': False if known else None,
            'signal_model': dict(manual_config.get('signal_model') or {}),
            'authoritative_preflight': f'data/manual_strategy/preflight/{target}.json',
            'authorization': 'not_assessed_by_daily_research',
        },
        'research_daily': {
            'rule_id': decision.get('rule_id'),
            'role': 'research_comparison_not_manual_entry_gate',
            'tradeable': bool(daily_signal.get('tradeable')),
            'trade_block_reason': daily_signal.get('trade_block_reason'),
            'open_gap': (daily_signal.get('strategy_context') or {}).get('open_gap'),
        },
    }
