# XAUUSD Trader - Plano Completo de Implementacao

## Objetivo

Implementar um executor MT5 para XAUUSD no repositorio `xauusd-trader`, unificando demo/live no mesmo codigo, consumindo artefato combinado de estrategia e aplicando risco em runtime com safeguards operacionais.

## Escopo End-to-End

1. Ingestao de configuracao e credenciais.
2. Conexao MT5, login e validacao de simbolo.
3. Carregamento de artefato combinado.
4. Pipeline de features e adaptador da estrategia.
5. Gating de execucao (spread, sessao, lock de posicao, cooldown).
6. Position sizing por risco com metadados MT5.
7. Envio de ordem com SL/TP e rastreio de retorno.
8. Persistencia de estado operacional.
9. Logging deterministico e relatorios.
10. Modo demo/live com mesmo fluxo.

## Dependencias e Bibliotecas

### Runtime principal

- `MetaTrader5>=5.0.45`: integracao com terminal MT5.
- `numpy>=1.26.0`: calculos numericos para features e risco.
- `pydantic>=2.7.0`: validacao forte de configuracao.
- `PyYAML>=6.0.1`: leitura de `runtime.yaml` e perfis de conta.

### Utilitarios

- `python-dotenv>=1.0.1`: carregar `.env`.
- `typing-extensions>=4.12.0`: compatibilidade typing.

### Desenvolvimento (opcional, recomendado)

- `pytest>=8.2.0`: testes unitarios e integracao simulada.
- `ruff>=0.5.0`: lint.
- `mypy>=1.10.0`: checagem de tipos.

## Estrutura de Repositorio Alvo

```text
xauusd-trader/
  README.md
  pyproject.toml
  .env
  .env.example
  IMPLEMENTATION_PLAN.md
  xauusd_trader.md
  config/
    runtime.yaml
    accounts/
      demo.yaml
      live.yaml
  artifacts/
    trader/
      .gitkeep
  logs/
    .gitkeep
  reports/
    .gitkeep
  src/
    xau_trader/
      __init__.py
      main.py
      runner.py
      config.py
      types.py
      mt5_client.py
      market_data.py
      features.py
      strategy_adapter.py
      risk.py
      safeguards.py
      execution.py
      state_store.py
      reporting.py
```

## Requisitos Funcionais

1. CLI:
   - `python -m xau_trader.main --account demo`
   - `python -m xau_trader.main --account live`
   - `python -m xau_trader.main --account demo --risk-per-trade-pct 0.01`
2. Suporte a `dry_run`.
3. Leitura do artefato combinado em schema estavel.
4. Lock de posicao unica por simbolo.
5. Checagens de spread e sessao.
6. Sizing normalizado por `volume_min/step/max`.
7. Persistencia de estado para reinicio seguro.
8. Logs de decisao, bloqueios e execucao.

## Requisitos Nao Funcionais

1. Determinismo de logs com timestamp UTC.
2. Falha segura em desconexao MT5 ou simbolo invalido.
3. Codigo tipado e modular.
4. Configuracao separada de credenciais.

## Modelo de Configuracao

### `.env` e `.env.example`

Campos base:

- `MT5_LOGIN`
- `MT5_PASSWORD`
- `MT5_INVESTOR_PASSWORD` (opcional)
- `MT5_SERVER`
- `MT5_PATH`
- `MT5_SYMBOL`
- `MT5_TIMEFRAMES`
- `MT5_CANDLES_PER_TIMEFRAME`

### `config/runtime.yaml`

Campos minimos:

- `symbol`
- `timeframe`
- `artifact_path`
- `risk_per_trade_pct`
- `max_daily_loss_pct`
- `max_open_positions`
- `max_spread_points`
- `slippage_points`
- `commission_per_lot_per_side`
- `swap_per_lot_per_day`
- `session_hours`
- `magic_number`
- `dry_run`
- `cooldown_seconds`
- `kill_switch_path`
- `poll_interval_seconds`

### `config/accounts/*.yaml`

Por perfil (demo/live):

- `name`
- `login_env`
- `password_env`
- `server_env`
- `path_env`
- `allow_live`

## Contrato de Artefato

Arquivo esperado: `artifacts/trader/combined_trader_artifact.json`

Secoes:

- `supervised`
- `unsupervised_gate`
- `runtime_defaults`
- `provenance`

Fallback:

- se `unsupervised_gate.enabled=false`, trader ignora gate de cluster.

## Fluxo de Execucao

1. Ler `.env`, `runtime.yaml` e perfil de conta.
2. Validar permissao de live (`allow_live`).
3. Conectar e logar MT5.
4. Validar simbolo e selecionar no terminal.
5. Carregar estado anterior (se existir).
6. Carregar artefato e preparar adaptador.
7. Loop:
   - coletar dados recentes,
   - montar features,
   - inferir sinal,
   - aplicar safeguards/gates,
   - calcular lote e ordem,
   - executar (ou simular),
   - persistir estado e logar.
8. Encerrar com `mt5.shutdown()` em bloco seguro.

## Safeguards Obrigatorios

1. Kill switch por arquivo.
2. Max erros consecutivos com shutdown seguro.
3. Stale data cutoff.
4. Bloqueio por spread alto.
5. Bloqueio por margem insuficiente.
6. Bloqueio fora de sessao.
7. One-position lock.

## Logging e Relatorios

1. `logs/decisions.jsonl`: sinal, gates, motivo.
2. `logs/executions.jsonl`: request/response de ordem.
3. `reports/daily_summary.json`: pnl, drawdown, taxa de execucao.

## Testes Planejados

1. Unitarios:
   - sizing e normalizacao de lote,
   - validacao de config,
   - gates de sessao e spread.
2. Integracao simulada:
   - fluxo completo em `dry_run`.
3. Smoke manual:
   - login MT5 demo, leitura de simbolo e loop minimo.

## Fases de Implementacao

### Fase 1 (base executavel)

- scaffold do pacote, configs e CLI.
- cliente MT5, leitura de artefato, strategy adapter baseline.
- safeguards principais e dry-run.

### Fase 2 (robustez operacional)

- persistencia completa de estado.
- reporting diario e codigos de razao detalhados.
- retries controlados e melhorias de telemetria.

### Fase 3 (paridade com treino)

- alinhar features exatamente ao pipeline de treino.
- integrar gate nao supervisionado.
- validacao cruzada de sinais com artefatos historicos.

## Execucao Imediata deste Plano

Nesta thread, sera executada a Fase 1 completa com:

1. Estrutura do repositorio.
2. `pyproject.toml` com dependencias.
3. `.env` e `.env.example`.
4. Configs runtime/account.
5. Modulos principais de execucao.
6. Validacao de build por compilacao Python.

