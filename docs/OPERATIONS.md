# Operacao Demo Tickmill

## Pre-check

1. Confirmar MT5 aberto e logado na conta demo Tickmill.
2. Validar credenciais em `.env`.
3. Confirmar artefato em `artifacts/trader/combined_trader_artifact.json`.
4. Confirmar `config/runtime.yaml` com `dry_run: false`.

## Comandos

```powershell
scripts\sync_artifact_from_bot.ps1
scripts\run_demo.cmd
```

## Logs

- `logs/decisions.jsonl`
- `logs/executions.jsonl`
- `logs/state.json`
- `reports/daily_summary.json`

## Kill switch

Criar arquivo `logs/KILL_SWITCH` para parada de emergencia.

