# XAUUSD MT5 Trader (Execution Repo Blueprint)

## Goal

Build one MT5 execution bot for XAUUSD that runs in both demo and live using the same codebase, loading a trained strategy artifact and applying configurable runtime risk.

## Core Principles

- One executor for demo/live (account decides environment).
- Strategy logic comes from artifact (not hardcoded rules).
- Risk is runtime-configurable (`risk_per_trade_pct` override).
- Costs and sizing in account currency, MT5 symbol metadata-aware.
- Safety first: pre-trade checks, kill-switches, and deterministic logs.

## Suggested Repository Layout

```text
xau-mt5-execution/
  README.md
  pyproject.toml
  .env.example
  config/
    runtime.yaml
    accounts/
      demo.yaml
      live.yaml
  artifacts/
    combined_trader_artifact.json
  src/
    xau_trader/
      main.py
      runner.py
      mt5_client.py
      market_data.py
      features.py
      strategy_adapter.py
      risk.py
      execution.py
      safeguards.py
      state_store.py
      reporting.py
      types.py
  logs/
  reports/
  scripts/
    run_demo.cmd
    run_live.cmd
```

## Runtime Flow

1. Start bot with selected account profile (`demo` or `live`).
2. Connect/login MT5 terminal and validate symbol (`XAUUSD`).
3. Load artifact (champion JSON).
4. Load runtime config (risk override, execution params, session rules).
5. Pull recent candles/ticks, build same features used in training.
6. Generate signal from artifact strategy adapter.
7. Apply execution gates (spread, session, one-position lock, cooldown).
8. Compute lot by risk and stop distance using MT5 symbol properties.
9. Send order (with SL/TP, slippage/deviation, comment/magic).
10. Track lifecycle and write trade/report logs.

## MT5 Integration

Use Python package `MetaTrader5`:

- Initialize terminal and login.
- Pull symbol info:
  - `trade_contract_size`
  - `trade_tick_size`
  - `trade_tick_value`
  - `volume_min`, `volume_step`, `volume_max`
- Pull account info (equity/balance/currency/margin).
- Pull rates/ticks and open positions/orders.
- Send `order_send` with strict validation.

## Combined Artifact (Execution Contract)

The trader should consume a single artifact:

- `artifacts/trader/combined_trader_artifact.json`

This file always exists in the same schema, even when unsupervised gate is disabled.

### Combined Artifact Sections

- `supervised`: full champion strategy payload.
- `unsupervised_gate`:
  - `enabled` (`true/false`)
  - `model` (`kmeans`)
  - `k`
  - `min_cluster_trades`
  - `allow_score_threshold_bps`
- `runtime_defaults`:
  - `symbol`
  - `risk_per_trade_pct`
  - `one_position_lock`
- `provenance`:
  - source files used to assemble the artifact.

## How To Build Combined Artifact

Run:

```bash
run_build_combined_artifact.cmd
```

Behavior:

- pulls champion strategy,
- optionally pulls latest unsup grid/eval/pro-motion decision,
- writes one execution artifact for the MT5 trader.

If unsupervised is not approved or not available, it still writes the same artifact with:

- `unsupervised_gate.enabled = false`

Supervised artifact fields used:

- `strategy_name`
- `params.strategy_kwargs`
- `horizon_steps`
- `move_threshold_bps`
- `sample_every_updates`
- confidence/spread gates

Adapter responsibilities:

- Rebuild model object from artifact params.
- Compute same feature vector schema as training.
- Output action `{long, short, hold}` + confidence.

## Risk Override (Runtime)

Keep artifact fixed; allow runtime override:

- `risk_per_trade_pct` (default `0.005`, optional `0.01`, etc.)
- `max_daily_loss_pct`
- `max_open_positions` (for now `1`)
- `max_spread_points`

### Important note

Changing 0.5% to 1% mostly scales lot/PnL/DD, but not perfectly linear due to:

- lot step rounding,
- min/max lot limits,
- margin constraints,
- real slippage behavior.

## Position Sizing (XAUUSD)

Lot calculation should use:

- stop distance in price units,
- value-per-price-unit from tick info,
- risk amount = `equity * risk_per_trade_pct`.

Then normalize to:

- min lot,
- lot step,
- max lot.

## Execution Logic

- Single active position lock.
- Intraday/scalping profile:
  - no multi-day holding by default,
  - optional max holding time cutoff.
- Dynamic SL/TP from volatility logic (same family used in training).
- Order fill policy compatible with broker/symbol.

## Demo/Live Unification

Same bot, different account profile:

- `config/accounts/demo.yaml`
- `config/accounts/live.yaml`

Only credentials/terminal/account flags differ.

## Safeguards

- Hard stop on:
  - MT5 disconnect,
  - stale market data,
  - symbol not tradable,
  - spread above threshold,
  - margin check fail.
- Kill switch file flag (manual emergency stop).
- Max consecutive errors before safe shutdown.

## State and Persistence

Store:

- last processed timestamp,
- open position context,
- cooldown timers,
- recent decisions.

This allows controlled restart without blind duplicate orders.

## Logging and Reporting

Log every decision with reason codes:

- signal generated / blocked / executed,
- confidence, spread, risk, lot, SL/TP,
- order result code and server message.

Outputs:

- trade log (jsonl/csv),
- execution quality summary,
- daily PnL/DD dashboard file.

## Required Config Fields (`runtime.yaml`)

- `symbol: XAUUSD`
- `timeframe: M1`
- `artifact_path`
- `risk_per_trade_pct`
- `max_spread_points`
- `slippage_points`
- `commission_per_lot_per_side`
- `swap_per_lot_per_day`
- `session_hours`
- `magic_number`
- `dry_run` (optional simulation mode)

## Minimal CLI

```bash
python -m xau_trader.main --account demo
python -m xau_trader.main --account live
python -m xau_trader.main --account demo --risk-per-trade-pct 0.01
```

## Pre-Live Checklist

- [ ] Demo run stable for multiple sessions.
- [ ] Lot sizing validated against MT5 symbol constraints.
- [ ] Costs aligned with broker account type.
- [ ] One-position lock verified.
- [ ] SL/TP placement verified on server.
- [ ] Recovery after terminal restart verified.
- [ ] Kill switch tested.
- [ ] Decision logs auditable end-to-end.
