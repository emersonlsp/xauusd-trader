# XAUUSD Trader

Executor MT5 para XAUUSD com codigo unico para demo/live, consumindo `combined_trader_artifact.json` e aplicando risco configuravel em runtime.

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

## Run

```powershell
.\.venv\Scripts\python.exe -m xau_trader.main --account demo
.\.venv\Scripts\python.exe -m xau_trader.main --account live
.\.venv\Scripts\python.exe -m xau_trader.main --account demo --risk-per-trade-pct 0.01
```

