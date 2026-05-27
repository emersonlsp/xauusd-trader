# Guia completo — Integração Python + MetaTrader 5 para enviar ordens no XAUUSD

> Objetivo: conectar Python ao terminal MetaTrader 5, diagnosticar a conta/símbolo, validar `order_check()` e finalmente enviar ordens reais/demonstrativas no XAUUSD com `order_send()`.

Este guia foi escrito para resolver o problema prático: **o bot já existe, as credenciais já existem, mas as ordens não estão saindo no XAUUSD**.

---

## 1. Visão geral da arquitetura

A biblioteca `MetaTrader5` para Python **não conversa diretamente com a corretora pela internet como uma API REST comum**. Ela conversa com o **terminal MetaTrader 5 instalado e aberto no computador/VPS**, e o terminal conversa com o servidor da corretora.

Fluxo real:

```text
Python script
    ↓
Pacote MetaTrader5
    ↓
Terminal MetaTrader 5 aberto/logado
    ↓
Servidor da corretora
    ↓
Execução/rejeição da ordem
```

Consequência prática:

- O MT5 precisa estar instalado.
- O terminal precisa conseguir logar na conta.
- A conta precisa permitir negociação automática.
- O símbolo precisa existir exatamente como a corretora nomeia.
- O ativo precisa estar visível no Market Watch.
- O volume precisa respeitar `volume_min`, `volume_max` e `volume_step`.
- O `type_filling` precisa ser aceito pelo símbolo.
- Stop Loss e Take Profit precisam respeitar a distância mínima do ativo.
- O mercado precisa estar aberto e com cotação atual.

---

## 2. Instalação do ambiente

### 2.1. Requisitos

Recomendado:

- Windows ou VPS Windows.
- MetaTrader 5 instalado.
- Python 3.10+ ou 3.11+.
- Terminal MT5 da corretora instalado, não apenas o MT5 genérico.
- Conta demo primeiro.
- Depois conta real, se tudo estiver validado.

Instalar pacotes:

```bash
pip install MetaTrader5 python-dotenv
```

Opcional:

```bash
pip install pandas
```

---

## 3. Configuração segura das credenciais

Crie um arquivo `.env` na raiz do projeto:

```env
MT5_LOGIN=12345678
MT5_PASSWORD=sua_senha_aqui
MT5_SERVER=NomeDoServidorDaCorretora
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

MT5_SYMBOL=XAUUSD
MT5_MAGIC=20260526
```

Importante:

- Não envie `.env` para GitHub.
- Adicione ao `.gitignore`:

```gitignore
.env
```

Exemplo de `.env.example` para o repositório:

```env
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MT5_PATH=
MT5_SYMBOL=XAUUSD
MT5_MAGIC=20260526
```

---

## 4. Checklist manual dentro do MT5 antes do Python

Antes de culpar o código, valide manualmente no terminal:

1. Abra o MetaTrader 5.
2. Faça login na conta correta.
3. Veja no canto inferior direito se há conexão.
4. Abra o Market Watch.
5. Procure o ouro:
   - `XAUUSD`
   - `XAUUSD.`
   - `XAUUSDm`
   - `XAUUSD#`
   - `GOLD`
   - `Gold`
   - outro nome específico da corretora.
6. Tente abrir uma ordem manual mínima no XAUUSD em conta demo.
7. Confirme se o botão de negociação algorítmica/automática está permitido no terminal.
8. Confirme se a conta aceita negociação nesse ativo.

Se você **não consegue abrir ordem manual**, o Python também não vai conseguir.

---

## 5. Estrutura recomendada de arquivos

```text
mt5_bot/
├─ .env
├─ .env.example
├─ mt5_connection.py
├─ mt5_diagnostics.py
├─ mt5_order_sender.py
├─ test_send_xauusd_order.py
└─ README_MT5_PYTHON_XAUUSD.md
```

---

## 6. Script de conexão: `mt5_connection.py`

```python
# mt5_connection.py

from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv
import MetaTrader5 as mt5


@dataclass(frozen=True)
class MT5Config:
    login: int
    password: str
    server: str
    path: str | None
    symbol: str
    magic: int


def load_mt5_config() -> MT5Config:
    """
    Load MT5 config from .env.
    Keep secrets outside the source code.
    """
    load_dotenv()

    login_raw = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")
    path = os.getenv("MT5_PATH") or None
    symbol = os.getenv("MT5_SYMBOL", "XAUUSD")
    magic_raw = os.getenv("MT5_MAGIC", "20260526")

    if not login_raw:
        raise RuntimeError("Missing MT5_LOGIN in .env")
    if not password:
        raise RuntimeError("Missing MT5_PASSWORD in .env")
    if not server:
        raise RuntimeError("Missing MT5_SERVER in .env")

    return MT5Config(
        login=int(login_raw),
        password=password,
        server=server,
        path=path,
        symbol=symbol,
        magic=int(magic_raw),
    )


def initialize_mt5(config: MT5Config) -> None:
    """
    Initialize and login to MetaTrader 5.
    Raises RuntimeError with mt5.last_error() when something fails.
    """

    if config.path:
        initialized = mt5.initialize(
            config.path,
            login=config.login,
            password=config.password,
            server=config.server,
            timeout=60_000,
        )
    else:
        initialized = mt5.initialize(
            login=config.login,
            password=config.password,
            server=config.server,
            timeout=60_000,
        )

    if not initialized:
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")

    account = mt5.account_info()
    if account is None:
        raise RuntimeError(f"mt5.account_info() failed: {mt5.last_error()}")

    if account.login != config.login:
        raise RuntimeError(
            f"Connected to wrong account. Expected {config.login}, got {account.login}"
        )

    terminal = mt5.terminal_info()
    if terminal is None:
        raise RuntimeError(f"mt5.terminal_info() failed: {mt5.last_error()}")

    if not terminal.connected:
        raise RuntimeError("MT5 terminal is not connected to the broker server.")

    if not terminal.trade_allowed:
        raise RuntimeError(
            "Terminal trading is not allowed. Check Algo Trading / AutoTrading permissions."
        )

    if not account.trade_allowed:
        raise RuntimeError("Account trade_allowed=False. Broker/account does not allow trading.")

    if not account.trade_expert:
        raise RuntimeError(
            "Account trade_expert=False. Expert/algorithmic trading may be disabled."
        )


def shutdown_mt5() -> None:
    """
    Close the MT5 connection.
    """
    mt5.shutdown()
```

---

## 7. Script de diagnóstico: `mt5_diagnostics.py`

Use este script antes de tentar enviar ordem.

Ele vai mostrar:

- se conectou;
- dados da conta;
- dados do terminal;
- possíveis nomes do XAUUSD;
- propriedades do símbolo;
- volume mínimo/máximo/passo;
- modo de execução;
- filling mode;
- distância mínima de stop;
- último tick.

```python
# mt5_diagnostics.py

from __future__ import annotations

import MetaTrader5 as mt5
from mt5_connection import load_mt5_config, initialize_mt5, shutdown_mt5


def print_dict(title: str, obj) -> None:
    print(f"\n========== {title} ==========")

    if obj is None:
        print("None")
        return

    data = obj._asdict() if hasattr(obj, "_asdict") else obj

    for key, value in data.items():
        print(f"{key}: {value}")


def find_gold_symbols() -> list[str]:
    """
    Search broker symbols that may represent gold.
    Different brokers use different names.
    """
    symbols = mt5.symbols_get()
    if symbols is None:
        raise RuntimeError(f"mt5.symbols_get() failed: {mt5.last_error()}")

    candidates = []

    keywords = [
        "XAU",
        "GOLD",
        "Gold",
        "gold",
    ]

    for symbol in symbols:
        name = symbol.name
        description = getattr(symbol, "description", "") or ""
        path = getattr(symbol, "path", "") or ""

        haystack = f"{name} {description} {path}"

        if any(keyword in haystack for keyword in keywords):
            candidates.append(name)

    return sorted(set(candidates))


def inspect_symbol(symbol: str) -> None:
    print(f"\n\n========== SYMBOL INSPECTION: {symbol} ==========")

    selected = mt5.symbol_select(symbol, True)
    print(f"symbol_select({symbol}, True): {selected}")

    if not selected:
        print(f"symbol_select failed: {mt5.last_error()}")
        return

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)

    print_dict("symbol_info", info)
    print_dict("symbol_info_tick", tick)

    if info is not None:
        print("\n--- Important trading fields ---")
        fields = [
            "name",
            "description",
            "path",
            "visible",
            "select",
            "trade_mode",
            "trade_exemode",
            "filling_mode",
            "order_mode",
            "digits",
            "point",
            "spread",
            "spread_float",
            "trade_stops_level",
            "trade_freeze_level",
            "trade_contract_size",
            "trade_tick_size",
            "trade_tick_value",
            "volume_min",
            "volume_max",
            "volume_step",
            "volume_limit",
            "currency_base",
            "currency_profit",
            "currency_margin",
        ]

        for field in fields:
            print(f"{field}: {getattr(info, field, None)}")


def main() -> None:
    config = load_mt5_config()

    try:
        initialize_mt5(config)

        print_dict("terminal_info", mt5.terminal_info())
        print_dict("account_info", mt5.account_info())
        print("MT5 version:", mt5.version())

        candidates = find_gold_symbols()

        print("\n========== POSSIBLE GOLD SYMBOLS ==========")
        if not candidates:
            print("No gold-like symbols found.")
        else:
            for item in candidates:
                print(item)

        inspect_symbol(config.symbol)

        for symbol in candidates:
            if symbol != config.symbol:
                inspect_symbol(symbol)

    finally:
        shutdown_mt5()


if __name__ == "__main__":
    main()
```

### Como usar

```bash
python mt5_diagnostics.py
```

Se `XAUUSD` não aparecer, mas aparecer `XAUUSDm`, `XAUUSD.`, `GOLD` etc., altere no `.env`:

```env
MT5_SYMBOL=XAUUSDm
```

ou o nome correto encontrado.

---

## 8. Entendendo os campos mais importantes do símbolo

Depois de rodar o diagnóstico, preste atenção nestes campos:

### `volume_min`

Volume mínimo permitido.

Exemplo:

```text
volume_min: 0.01
```

Então não adianta mandar `volume=0.001`.

### `volume_step`

Passo do volume.

Exemplo:

```text
volume_step: 0.01
```

Volumes válidos:

```text
0.01
0.02
0.03
0.10
1.00
```

Volumes inválidos:

```text
0.015
0.105
```

### `volume_max`

Volume máximo por ordem.

### `trade_stops_level`

Distância mínima de Stop Loss/Take Profit em pontos.

Se for:

```text
trade_stops_level: 50
point: 0.01
```

A distância mínima é:

```text
50 * 0.01 = 0.50 dólar no ouro
```

Se você mandar SL ou TP perto demais, pode receber:

```text
TRADE_RETCODE_INVALID_STOPS
```

### `filling_mode`

Campo crítico para o problema de ordem rejeitada.

Nem todo ativo aceita qualquer `type_filling`.

Possíveis políticas usadas no Python:

```python
mt5.ORDER_FILLING_FOK
mt5.ORDER_FILLING_IOC
mt5.ORDER_FILLING_RETURN
```

Se usar um filling incompatível, é comum receber:

```text
TRADE_RETCODE_INVALID_FILL
```

### `trade_mode`

Indica se o símbolo pode ser negociado, se está somente fechamento, desabilitado etc.

### `trade_exemode`

Indica o modo de execução: instant, request, market ou exchange.

---

## 9. Helper robusto para volume, preço e filling: `mt5_order_sender.py`

Este arquivo é a camada segura para enviar ordens.

Ele faz:

- seleção do símbolo;
- validação do símbolo;
- arredondamento do volume para `volume_step`;
- escolha de preço correto:
  - compra usa `ask`;
  - venda usa `bid`;
- cálculo de SL/TP por distância em pontos;
- tentativa de `order_check()`;
- envio por `order_send()`;
- fallback de `type_filling`;
- log detalhado do erro.

```python
# mt5_order_sender.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import MetaTrader5 as mt5


OrderSide = Literal["buy", "sell"]


@dataclass
class OrderResult:
    success: bool
    retcode: int | None
    comment: str
    raw: object | None


def normalize_volume(symbol_info, requested_volume: float) -> float:
    """
    Normalize volume according to broker constraints.
    """
    volume_min = float(symbol_info.volume_min)
    volume_max = float(symbol_info.volume_max)
    volume_step = float(symbol_info.volume_step)

    if requested_volume < volume_min:
        requested_volume = volume_min

    if requested_volume > volume_max:
        requested_volume = volume_max

    steps = round((requested_volume - volume_min) / volume_step)
    normalized = volume_min + steps * volume_step

    normalized = round(normalized, 8)

    return normalized


def get_available_filling_modes(symbol_info) -> list[int]:
    """
    Return a practical list of filling modes to try.

    Some brokers reject ORDER_FILLING_RETURN on market execution symbols.
    Some accept only IOC or FOK.
    """

    preferred: list[int] = []

    candidates = [
        mt5.ORDER_FILLING_IOC,
        mt5.ORDER_FILLING_FOK,
        mt5.ORDER_FILLING_RETURN,
    ]

    reported = getattr(symbol_info, "filling_mode", None)

    if reported in candidates:
        preferred.append(reported)

    for item in candidates:
        if item not in preferred:
            preferred.append(item)

    return preferred


def retcode_name(retcode: int | None) -> str:
    """
    Map common MT5 trade retcodes to readable names.
    """
    mapping = {
        10004: "TRADE_RETCODE_REQUOTE",
        10006: "TRADE_RETCODE_REJECT",
        10007: "TRADE_RETCODE_CANCEL",
        10008: "TRADE_RETCODE_PLACED",
        10009: "TRADE_RETCODE_DONE",
        10010: "TRADE_RETCODE_DONE_PARTIAL",
        10011: "TRADE_RETCODE_ERROR",
        10012: "TRADE_RETCODE_TIMEOUT",
        10013: "TRADE_RETCODE_INVALID",
        10014: "TRADE_RETCODE_INVALID_VOLUME",
        10015: "TRADE_RETCODE_INVALID_PRICE",
        10016: "TRADE_RETCODE_INVALID_STOPS",
        10017: "TRADE_RETCODE_TRADE_DISABLED",
        10018: "TRADE_RETCODE_MARKET_CLOSED",
        10019: "TRADE_RETCODE_NO_MONEY",
        10020: "TRADE_RETCODE_PRICE_CHANGED",
        10021: "TRADE_RETCODE_PRICE_OFF",
        10022: "TRADE_RETCODE_INVALID_EXPIRATION",
        10023: "TRADE_RETCODE_ORDER_CHANGED",
        10024: "TRADE_RETCODE_TOO_MANY_REQUESTS",
        10025: "TRADE_RETCODE_NO_CHANGES",
        10026: "TRADE_RETCODE_SERVER_DISABLES_AT",
        10027: "TRADE_RETCODE_CLIENT_DISABLES_AT",
        10028: "TRADE_RETCODE_LOCKED",
        10029: "TRADE_RETCODE_FROZEN",
        10030: "TRADE_RETCODE_INVALID_FILL",
        10031: "TRADE_RETCODE_CONNECTION",
        10032: "TRADE_RETCODE_ONLY_REAL",
        10033: "TRADE_RETCODE_LIMIT_ORDERS",
        10034: "TRADE_RETCODE_LIMIT_VOLUME",
        10035: "TRADE_RETCODE_INVALID_ORDER",
        10036: "TRADE_RETCODE_POSITION_CLOSED",
        10038: "TRADE_RETCODE_INVALID_CLOSE_VOLUME",
        10039: "TRADE_RETCODE_CLOSE_ORDER_EXIST",
        10040: "TRADE_RETCODE_LIMIT_POSITIONS",
        10041: "TRADE_RETCODE_REJECT_CANCEL",
        10042: "TRADE_RETCODE_LONG_ONLY",
        10043: "TRADE_RETCODE_SHORT_ONLY",
        10044: "TRADE_RETCODE_CLOSE_ONLY",
        10045: "TRADE_RETCODE_FIFO_CLOSE",
        10046: "TRADE_RETCODE_HEDGE_PROHIBITED",
    }

    if retcode is None:
        return "NO_RETCODE"

    return mapping.get(retcode, f"UNKNOWN_RETCODE_{retcode}")


def print_trade_result(prefix: str, result) -> None:
    """
    Print a full MT5 result object.
    """
    print(f"\n========== {prefix} ==========")

    if result is None:
        print("Result is None")
        print("last_error:", mt5.last_error())
        return

    print(result)

    if hasattr(result, "_asdict"):
        result_dict = result._asdict()
        for key, value in result_dict.items():
            print(f"{key}: {value}")

            if key == "request" and hasattr(value, "_asdict"):
                print("--- request ---")
                for req_key, req_value in value._asdict().items():
                    print(f"request.{req_key}: {req_value}")


def build_market_order_request(
    symbol: str,
    side: OrderSide,
    volume: float,
    deviation: int,
    magic: int,
    sl_points: int | None,
    tp_points: int | None,
    type_filling: int,
    comment: str,
) -> dict:
    """
    Build a market order request.
    """
    info = mt5.symbol_info(symbol)

    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) returned None: {mt5.last_error()}")

    tick = mt5.symbol_info_tick(symbol)

    if tick is None:
        raise RuntimeError(f"symbol_info_tick({symbol}) returned None: {mt5.last_error()}")

    point = float(info.point)

    if side == "buy":
        order_type = mt5.ORDER_TYPE_BUY
        price = float(tick.ask)

        sl = price - sl_points * point if sl_points else 0.0
        tp = price + tp_points * point if tp_points else 0.0

    elif side == "sell":
        order_type = mt5.ORDER_TYPE_SELL
        price = float(tick.bid)

        sl = price + sl_points * point if sl_points else 0.0
        tp = price - tp_points * point if tp_points else 0.0

    else:
        raise ValueError("side must be 'buy' or 'sell'")

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": round(sl, int(info.digits)) if sl else 0.0,
        "tp": round(tp, int(info.digits)) if tp else 0.0,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": type_filling,
    }

    return request


def ensure_symbol_ready(symbol: str):
    """
    Select symbol and return symbol_info.
    """
    info = mt5.symbol_info(symbol)

    if info is None:
        raise RuntimeError(
            f"Symbol {symbol} not found. "
            f"Run mt5_diagnostics.py and check broker-specific symbol name."
        )

    if not info.visible:
        selected = mt5.symbol_select(symbol, True)
        if not selected:
            raise RuntimeError(f"symbol_select({symbol}, True) failed: {mt5.last_error()}")

    info = mt5.symbol_info(symbol)

    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) failed after select: {mt5.last_error()}")

    return info


def send_market_order(
    symbol: str,
    side: OrderSide,
    volume: float,
    deviation: int,
    magic: int,
    sl_points: int | None = None,
    tp_points: int | None = None,
    comment: str = "python mt5 order",
    dry_run: bool = True,
) -> OrderResult:
    """
    Send a market order after running order_check.

    dry_run=True:
        Only validates with order_check().
    dry_run=False:
        Sends the real order with order_send().
    """

    info = ensure_symbol_ready(symbol)
    normalized_volume = normalize_volume(info, volume)

    print("\n========== ORDER INPUT ==========")
    print("symbol:", symbol)
    print("side:", side)
    print("requested_volume:", volume)
    print("normalized_volume:", normalized_volume)
    print("volume_min:", info.volume_min)
    print("volume_max:", info.volume_max)
    print("volume_step:", info.volume_step)
    print("trade_stops_level:", info.trade_stops_level)
    print("filling_mode:", info.filling_mode)
    print("trade_mode:", info.trade_mode)
    print("trade_exemode:", info.trade_exemode)

    if sl_points is not None and sl_points < int(info.trade_stops_level):
        raise RuntimeError(
            f"sl_points={sl_points} is below trade_stops_level={info.trade_stops_level}"
        )

    if tp_points is not None and tp_points < int(info.trade_stops_level):
        raise RuntimeError(
            f"tp_points={tp_points} is below trade_stops_level={info.trade_stops_level}"
        )

    filling_modes = get_available_filling_modes(info)

    last_result = None

    for filling in filling_modes:
        request = build_market_order_request(
            symbol=symbol,
            side=side,
            volume=normalized_volume,
            deviation=deviation,
            magic=magic,
            sl_points=sl_points,
            tp_points=tp_points,
            type_filling=filling,
            comment=comment,
        )

        print("\nTrying type_filling:", filling)
        print("Request:", request)

        check = mt5.order_check(request)
        print_trade_result("ORDER CHECK", check)

        if check is None:
            last_result = None
            continue

        if getattr(check, "retcode", None) != 0:
            print("order_check rejected request.")
            last_result = check
            continue

        if dry_run:
            return OrderResult(
                success=True,
                retcode=getattr(check, "retcode", None),
                comment="Dry run passed with order_check(). No real order sent.",
                raw=check,
            )

        result = mt5.order_send(request)
        print_trade_result("ORDER SEND", result)
        last_result = result

        if result is None:
            continue

        retcode = getattr(result, "retcode", None)

        if retcode == mt5.TRADE_RETCODE_DONE:
            return OrderResult(
                success=True,
                retcode=retcode,
                comment=f"Order sent successfully: {retcode_name(retcode)}",
                raw=result,
            )

        if retcode == 10030:
            print("Invalid filling mode. Trying next filling mode...")
            continue

        return OrderResult(
            success=False,
            retcode=retcode,
            comment=f"Order failed: {retcode_name(retcode)}",
            raw=result,
        )

    retcode = getattr(last_result, "retcode", None) if last_result is not None else None

    return OrderResult(
        success=False,
        retcode=retcode,
        comment=f"All attempts failed. Last retcode: {retcode_name(retcode)}",
        raw=last_result,
    )


def close_position(position_ticket: int, deviation: int, magic: int) -> OrderResult:
    """
    Close a position by ticket.
    """
    positions = mt5.positions_get(ticket=position_ticket)

    if not positions:
        return OrderResult(
            success=False,
            retcode=None,
            comment=f"No position found with ticket {position_ticket}",
            raw=None,
        )

    position = positions[0]
    symbol = position.symbol
    volume = position.volume
    info = ensure_symbol_ready(symbol)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"symbol_info_tick({symbol}) returned None: {mt5.last_error()}")

    if position.type == mt5.POSITION_TYPE_BUY:
        close_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        close_type = mt5.ORDER_TYPE_BUY
        price = tick.ask

    filling_modes = get_available_filling_modes(info)

    last_result = None

    for filling in filling_modes:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": close_type,
            "position": position_ticket,
            "price": price,
            "deviation": deviation,
            "magic": magic,
            "comment": "python mt5 close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        result = mt5.order_send(request)
        print_trade_result("CLOSE POSITION", result)
        last_result = result

        if result is None:
            continue

        retcode = getattr(result, "retcode", None)

        if retcode == mt5.TRADE_RETCODE_DONE:
            return OrderResult(
                success=True,
                retcode=retcode,
                comment=f"Position closed successfully: {retcode_name(retcode)}",
                raw=result,
            )

        if retcode == 10030:
            continue

        return OrderResult(
            success=False,
            retcode=retcode,
            comment=f"Close failed: {retcode_name(retcode)}",
            raw=result,
        )

    retcode = getattr(last_result, "retcode", None) if last_result is not None else None

    return OrderResult(
        success=False,
        retcode=retcode,
        comment=f"Close failed after all filling modes: {retcode_name(retcode)}",
        raw=last_result,
    )
```

---

## 10. Teste seguro com `dry_run`: `test_send_xauusd_order.py`

Primeiro rode em modo `dry_run=True`.

Isso executa `order_check()` sem enviar ordem real.

```python
# test_send_xauusd_order.py

from __future__ import annotations

from mt5_connection import load_mt5_config, initialize_mt5, shutdown_mt5
from mt5_order_sender import send_market_order


def main() -> None:
    config = load_mt5_config()

    try:
        initialize_mt5(config)

        result = send_market_order(
            symbol=config.symbol,
            side="buy",
            volume=0.01,
            deviation=50,
            magic=config.magic,
            sl_points=500,
            tp_points=500,
            comment="xauusd python dry run",
            dry_run=True,
        )

        print("\n========== FINAL RESULT ==========")
        print("success:", result.success)
        print("retcode:", result.retcode)
        print("comment:", result.comment)

    finally:
        shutdown_mt5()


if __name__ == "__main__":
    main()
```

Rodar:

```bash
python test_send_xauusd_order.py
```

Se o `dry_run` passar, você verá algo como:

```text
success: True
comment: Dry run passed with order_check(). No real order sent.
```

---

## 11. Enviar ordem real

Depois que o teste passar em conta demo, altere:

```python
dry_run=False
```

Exemplo:

```python
result = send_market_order(
    symbol=config.symbol,
    side="buy",
    volume=0.01,
    deviation=50,
    magic=config.magic,
    sl_points=500,
    tp_points=500,
    comment="xauusd python real order",
    dry_run=False,
)
```

Atenção:

- Isso envia ordem de verdade.
- Teste primeiro em demo.
- Use volume mínimo.
- Confirme se o símbolo é o correto.
- Confirme se `sl_points` e `tp_points` fazem sentido para o ouro na sua corretora.

---

## 12. Como adaptar para venda

Compra:

```python
side="buy"
```

Venda:

```python
side="sell"
```

Exemplo venda:

```python
result = send_market_order(
    symbol=config.symbol,
    side="sell",
    volume=0.01,
    deviation=50,
    magic=config.magic,
    sl_points=500,
    tp_points=500,
    comment="xauusd python sell",
    dry_run=False,
)
```

---

## 13. Como interpretar pontos no XAUUSD

No MT5, `point` depende da corretora.

Exemplos comuns:

```text
digits: 2
point: 0.01
```

Então:

```text
500 pontos = 500 * 0.01 = 5.00 dólares
```

Se o ouro está em:

```text
XAUUSD = 2350.00
```

Compra com:

```text
sl_points=500
tp_points=500
```

Gera aproximadamente:

```text
SL = 2345.00
TP = 2355.00
```

Outro exemplo:

```text
digits: 3
point: 0.001
```

Então:

```text
500 pontos = 0.500 dólar
```

Por isso o diagnóstico é obrigatório.

---

## 14. Principais erros e como resolver

### 14.1. `symbol_info(XAUUSD) returned None`

Causa provável:

- O nome do símbolo está errado para sua corretora.

Solução:

```bash
python mt5_diagnostics.py
```

Procure possíveis nomes:

```text
XAUUSD
XAUUSD.
XAUUSDm
XAUUSD#
GOLD
```

Depois ajuste:

```env
MT5_SYMBOL=nome_correto
```

---

### 14.2. `TRADE_RETCODE_INVALID_FILL` / código `10030`

Causa provável:

- `type_filling` incompatível com o ativo.

Solução:

- O script `send_market_order()` já tenta:
  - `ORDER_FILLING_IOC`
  - `ORDER_FILLING_FOK`
  - `ORDER_FILLING_RETURN`

Se ainda falhar, verifique:

```text
symbol_info.filling_mode
symbol_info.trade_exemode
```

Algumas corretoras exigem um modo específico.

---

### 14.3. `TRADE_RETCODE_INVALID_VOLUME` / código `10014`

Causas prováveis:

- Volume menor que `volume_min`.
- Volume maior que `volume_max`.
- Volume fora do passo `volume_step`.

Exemplo:

```text
volume_min: 0.01
volume_step: 0.01
```

Errado:

```python
volume=0.015
```

Certo:

```python
volume=0.01
volume=0.02
volume=0.10
```

O helper `normalize_volume()` corrige isso automaticamente.

---

### 14.4. `TRADE_RETCODE_INVALID_STOPS` / código `10016`

Causas prováveis:

- Stop Loss perto demais.
- Take Profit perto demais.
- SL/TP do lado errado.
- `trade_stops_level` maior do que você imaginou.

Solução:

Veja:

```text
trade_stops_level
point
```

Se:

```text
trade_stops_level: 100
point: 0.01
```

A distância mínima é:

```text
1.00 dólar
```

Use distância maior, por exemplo:

```python
sl_points=300
tp_points=300
```

ou teste sem SL/TP:

```python
sl_points=None
tp_points=None
```

---

### 14.5. `TRADE_RETCODE_MARKET_CLOSED` / código `10018`

Causa:

- Mercado fechado.
- Símbolo sem sessão ativa.
- Ouro fechado no horário da corretora.

Solução:

- Testar em horário de mercado.
- Ver se o ativo está cotando.
- Ver `symbol_info_tick`.

---

### 14.6. `TRADE_RETCODE_PRICE_OFF` / código `10021`

Causa:

- Sem preço/cotação atual para processar a ordem.

Solução:

- Abra o gráfico do ativo no MT5.
- Selecione o ativo no Market Watch.
- Aguarde ticks.
- Verifique:

```python
mt5.symbol_info_tick(symbol)
```

---

### 14.7. `TRADE_RETCODE_TRADE_DISABLED` / código `10017`

Causa:

- Trading desabilitado no símbolo, conta ou corretora.

Solução:

- Verificar se consegue ordem manual.
- Verificar se a conta é somente leitura/investor password.
- Verificar se o ativo permite negociação.
- Verificar se o servidor é correto.

---

### 14.8. `TRADE_RETCODE_CLIENT_DISABLES_AT` / código `10027`

Causa:

- Negociação automática desabilitada no terminal do cliente.

Solução:

- Ativar negociação algorítmica/automática no MT5.
- Verificar configurações do terminal.

---

### 14.9. `TRADE_RETCODE_NO_MONEY` / código `10019`

Causa:

- Margem livre insuficiente.

Solução:

- Reduzir lote.
- Verificar alavancagem.
- Verificar margem exigida para XAUUSD.

---

### 14.10. `TRADE_RETCODE_INVALID_PRICE` / código `10015`

Causas:

- Preço antigo.
- Usou `bid` para compra.
- Usou `ask` para venda.
- Cotação mudou muito rápido.
- Desvio pequeno.

Solução:

- Compra usa `ask`.
- Venda usa `bid`.
- Aumentar `deviation`.
- Pegar tick imediatamente antes da ordem.

---

## 15. Código mínimo para comprar XAUUSD

Este é o código mais simples possível, sem arquitetura:

```python
import MetaTrader5 as mt5

LOGIN = 12345678
PASSWORD = "sua_senha"
SERVER = "Servidor-Corretora"
SYMBOL = "XAUUSD"
LOT = 0.01

if not mt5.initialize(login=LOGIN, password=PASSWORD, server=SERVER):
    print("initialize failed:", mt5.last_error())
    quit()

if not mt5.symbol_select(SYMBOL, True):
    print("symbol_select failed:", mt5.last_error())
    mt5.shutdown()
    quit()

info = mt5.symbol_info(SYMBOL)
tick = mt5.symbol_info_tick(SYMBOL)

if info is None:
    print("symbol_info failed:", mt5.last_error())
    mt5.shutdown()
    quit()

if tick is None:
    print("symbol_info_tick failed:", mt5.last_error())
    mt5.shutdown()
    quit()

price = tick.ask

request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": SYMBOL,
    "volume": LOT,
    "type": mt5.ORDER_TYPE_BUY,
    "price": price,
    "deviation": 50,
    "magic": 20260526,
    "comment": "python xauusd buy",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}

check = mt5.order_check(request)
print("check:", check)

result = mt5.order_send(request)
print("result:", result)

if result is not None:
    print("retcode:", result.retcode)

mt5.shutdown()
```

Se isso falhar com `INVALID_FILL`, teste:

```python
"type_filling": mt5.ORDER_FILLING_FOK
```

ou:

```python
"type_filling": mt5.ORDER_FILLING_RETURN
```

---

## 16. Código mínimo para vender XAUUSD

```python
import MetaTrader5 as mt5

LOGIN = 12345678
PASSWORD = "sua_senha"
SERVER = "Servidor-Corretora"
SYMBOL = "XAUUSD"
LOT = 0.01

if not mt5.initialize(login=LOGIN, password=PASSWORD, server=SERVER):
    print("initialize failed:", mt5.last_error())
    quit()

if not mt5.symbol_select(SYMBOL, True):
    print("symbol_select failed:", mt5.last_error())
    mt5.shutdown()
    quit()

tick = mt5.symbol_info_tick(SYMBOL)

if tick is None:
    print("symbol_info_tick failed:", mt5.last_error())
    mt5.shutdown()
    quit()

price = tick.bid

request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": SYMBOL,
    "volume": LOT,
    "type": mt5.ORDER_TYPE_SELL,
    "price": price,
    "deviation": 50,
    "magic": 20260526,
    "comment": "python xauusd sell",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}

check = mt5.order_check(request)
print("check:", check)

result = mt5.order_send(request)
print("result:", result)

if result is not None:
    print("retcode:", result.retcode)

mt5.shutdown()
```

---

## 17. Como fechar posição aberta

Para fechar uma posição, você envia uma ordem oposta usando o ticket da posição.

Exemplo:

```python
import MetaTrader5 as mt5

POSITION_TICKET = 123456789
DEVIATION = 50
MAGIC = 20260526

positions = mt5.positions_get(ticket=POSITION_TICKET)

if not positions:
    print("Position not found")
    quit()

position = positions[0]
symbol = position.symbol
volume = position.volume

tick = mt5.symbol_info_tick(symbol)

if position.type == mt5.POSITION_TYPE_BUY:
    order_type = mt5.ORDER_TYPE_SELL
    price = tick.bid
else:
    order_type = mt5.ORDER_TYPE_BUY
    price = tick.ask

request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": symbol,
    "volume": volume,
    "type": order_type,
    "position": POSITION_TICKET,
    "price": price,
    "deviation": DEVIATION,
    "magic": MAGIC,
    "comment": "python close position",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}

result = mt5.order_send(request)
print(result)
```

---

## 18. Como listar posições abertas

```python
import MetaTrader5 as mt5

positions = mt5.positions_get()

if positions is None:
    print("positions_get failed:", mt5.last_error())
else:
    for position in positions:
        print(position)
```

Filtrar por símbolo:

```python
positions = mt5.positions_get(symbol="XAUUSD")
```

---

## 19. Como calcular margem antes da ordem

```python
import MetaTrader5 as mt5

symbol = "XAUUSD"
lot = 0.01
tick = mt5.symbol_info_tick(symbol)

margin = mt5.order_calc_margin(
    mt5.ORDER_TYPE_BUY,
    symbol,
    lot,
    tick.ask,
)

print("margin:", margin)
print("last_error:", mt5.last_error())
```

Se `margin` vier `None`, veja `mt5.last_error()`.

---

## 20. Como calcular lucro/prejuízo estimado

```python
import MetaTrader5 as mt5

symbol = "XAUUSD"
lot = 0.01
price_open = 2350.00
price_close = 2355.00

profit = mt5.order_calc_profit(
    mt5.ORDER_TYPE_BUY,
    symbol,
    lot,
    price_open,
    price_close,
)

print("profit:", profit)
print("last_error:", mt5.last_error())
```

---

## 21. Regras práticas específicas para XAUUSD

### 21.1. Não presuma que 1 lote é pequeno

Em muitos brokers, 1 lote de XAUUSD pode representar 100 onças de ouro.

Por isso, comece com:

```python
volume=0.01
```

ou o `volume_min` mostrado no diagnóstico.

### 21.2. O spread pode aumentar muito

Em notícia, abertura de mercado ou baixa liquidez, o spread pode aumentar.

Antes da ordem, monitore:

```python
info.spread
```

### 21.3. SL/TP precisam ser largos o bastante

O ouro se move rápido. Um SL de poucos pontos pode ser inválido ou inútil.

Use o diagnóstico:

```text
point
digits
trade_stops_level
spread
```

### 21.4. Símbolos variam por corretora

Nunca dependa cegamente de `XAUUSD`.

Sempre rode:

```python
mt5.symbols_get()
```

e procure candidatos.

---

## 22. Checklist para quando a ordem não sair

Use esta ordem de investigação:

### Etapa 1 — Conexão

```python
mt5.initialize()
mt5.account_info()
mt5.terminal_info()
```

Verifique:

```text
terminal.connected = True
terminal.trade_allowed = True
account.trade_allowed = True
account.trade_expert = True
```

### Etapa 2 — Símbolo

```python
mt5.symbol_info("XAUUSD")
```

Se vier `None`, o nome está errado.

Rode:

```bash
python mt5_diagnostics.py
```

### Etapa 3 — Market Watch

```python
mt5.symbol_select(symbol, True)
```

Precisa retornar:

```text
True
```

### Etapa 4 — Tick

```python
mt5.symbol_info_tick(symbol)
```

Precisa retornar `bid` e `ask`.

Se vier `None`, pode estar sem cotação.

### Etapa 5 — Volume

Compare:

```text
volume_min
volume_max
volume_step
```

### Etapa 6 — SL/TP

Compare:

```text
trade_stops_level
point
```

Teste primeiro sem SL/TP:

```python
sl_points=None
tp_points=None
```

### Etapa 7 — Filling

Teste:

```python
mt5.ORDER_FILLING_IOC
mt5.ORDER_FILLING_FOK
mt5.ORDER_FILLING_RETURN
```

### Etapa 8 — `order_check()`

Antes do envio real:

```python
check = mt5.order_check(request)
print(check)
```

### Etapa 9 — `order_send()`

Depois:

```python
result = mt5.order_send(request)
print(result)
print(result.retcode)
```

### Etapa 10 — Interpretar `retcode`

Use a tabela de retcodes no item 23.

---

## 23. Retcodes comuns

| Código | Nome | Significado prático |
|---:|---|---|
| 10009 | `TRADE_RETCODE_DONE` | Ordem executada |
| 10008 | `TRADE_RETCODE_PLACED` | Ordem pendente colocada |
| 10010 | `TRADE_RETCODE_DONE_PARTIAL` | Execução parcial |
| 10013 | `TRADE_RETCODE_INVALID` | Request inválido |
| 10014 | `TRADE_RETCODE_INVALID_VOLUME` | Volume inválido |
| 10015 | `TRADE_RETCODE_INVALID_PRICE` | Preço inválido |
| 10016 | `TRADE_RETCODE_INVALID_STOPS` | SL/TP inválido |
| 10017 | `TRADE_RETCODE_TRADE_DISABLED` | Trading desabilitado |
| 10018 | `TRADE_RETCODE_MARKET_CLOSED` | Mercado fechado |
| 10019 | `TRADE_RETCODE_NO_MONEY` | Margem insuficiente |
| 10020 | `TRADE_RETCODE_PRICE_CHANGED` | Preço mudou |
| 10021 | `TRADE_RETCODE_PRICE_OFF` | Sem cotação |
| 10024 | `TRADE_RETCODE_TOO_MANY_REQUESTS` | Requisições em excesso |
| 10027 | `TRADE_RETCODE_CLIENT_DISABLES_AT` | AutoTrading desabilitado no terminal |
| 10030 | `TRADE_RETCODE_INVALID_FILL` | Filling mode inválido |
| 10031 | `TRADE_RETCODE_CONNECTION` | Sem conexão |
| 10034 | `TRADE_RETCODE_LIMIT_VOLUME` | Limite de volume atingido |
| 10035 | `TRADE_RETCODE_INVALID_ORDER` | Tipo de ordem incorreto/proibido |
| 10044 | `TRADE_RETCODE_CLOSE_ONLY` | Símbolo aceita apenas fechamento |

---

## 24. Prompt para pedir ajuda para outra IA/thread

Use este prompt quando for continuar o desenvolvimento:

```text
Leia o arquivo README_MT5_PYTHON_XAUUSD.md.

Contexto:
- Já tenho bot em Python.
- Já tenho credenciais de uma conta no MetaTrader 5.
- O problema atual é que consigo conectar/consultar dados, mas não consigo enviar ordens reais no XAUUSD.
- Quero que você siga o checklist do guia e não pule o diagnóstico.
- Não presuma que o símbolo é exatamente XAUUSD; descubra o nome correto pela corretora.
- Antes de usar order_send(), rode order_check().
- Se houver erro de filling mode, teste IOC, FOK e RETURN.
- Se houver erro de volume, respeite volume_min, volume_max e volume_step.
- Se houver erro de stops, use trade_stops_level e point para ajustar SL/TP.
- Não exponha credenciais em logs, commits ou mensagens.

Tarefa:
1. Validar conexão com MT5.
2. Validar conta e terminal.
3. Descobrir símbolo correto do ouro.
4. Inspecionar propriedades do símbolo.
5. Fazer dry_run com order_check().
6. Enviar ordem mínima em demo.
7. Só depois adaptar para o bot principal.
```

---

## 25. Ordem recomendada de execução

Execute nesta sequência:

```bash
python mt5_diagnostics.py
```

Depois ajuste `.env` com o símbolo correto.

Em seguida:

```bash
python test_send_xauusd_order.py
```

Primeiro com:

```python
dry_run=True
```

Depois, em conta demo:

```python
dry_run=False
```

Somente depois de validar:

- símbolo correto;
- volume correto;
- filling correto;
- SL/TP válido;
- ordem mínima em demo;

integre ao bot principal.

---

## 26. Integração no bot principal

No seu bot, o fluxo de execução deve ser:

```python
from mt5_connection import load_mt5_config, initialize_mt5, shutdown_mt5
from mt5_order_sender import send_market_order

config = load_mt5_config()

try:
    initialize_mt5(config)

    signal = "buy"

    if signal == "buy":
        result = send_market_order(
            symbol=config.symbol,
            side="buy",
            volume=0.01,
            deviation=50,
            magic=config.magic,
            sl_points=500,
            tp_points=500,
            comment="bot xauusd buy",
            dry_run=False,
        )

    elif signal == "sell":
        result = send_market_order(
            symbol=config.symbol,
            side="sell",
            volume=0.01,
            deviation=50,
            magic=config.magic,
            sl_points=500,
            tp_points=500,
            comment="bot xauusd sell",
            dry_run=False,
        )

    print(result)

finally:
    shutdown_mt5()
```

---

## 27. Boas práticas para bot operando ordens reais

### 27.1. Use trava de ambiente

No `.env`:

```env
TRADING_ENV=demo
```

No código:

```python
import os

if os.getenv("TRADING_ENV") != "live":
    dry_run = True
else:
    dry_run = False
```

Assim você evita enviar ordem real sem querer.

### 27.2. Use limite máximo de lote

```python
MAX_LOT = 0.01

if volume > MAX_LOT:
    raise RuntimeError("Volume above safety limit")
```

### 27.3. Use limite de spread

```python
MAX_SPREAD_POINTS = 100

info = mt5.symbol_info(symbol)

if info.spread > MAX_SPREAD_POINTS:
    raise RuntimeError(f"Spread too high: {info.spread}")
```

### 27.4. Evite mandar muitas ordens em sequência

Se receber:

```text
TRADE_RETCODE_TOO_MANY_REQUESTS
```

adicione intervalo entre tentativas.

### 27.5. Logue tudo, menos senha

Registre:

- horário;
- símbolo;
- sinal;
- request;
- check result;
- send result;
- retcode;
- posição aberta;
- preço;
- spread.

Nunca logue:

- senha;
- token;
- `.env`;
- dados sensíveis da conta.

---

## 28. Diagnóstico rápido do caso XAUUSD

Se seu caso é especificamente:

> “Consigo conectar, mas não consigo mandar ordem no XAUUSD.”

A causa mais provável está entre estas:

1. O símbolo não se chama `XAUUSD` na sua corretora.
2. `XAUUSD` não está visível no Market Watch.
3. O ativo está sem cotação no momento.
4. `type_filling` está errado.
5. Volume está fora de `volume_min` / `volume_step`.
6. SL/TP está perto demais.
7. AutoTrading está desabilitado no terminal.
8. Conta conectada com senha de investidor/somente leitura.
9. Mercado fechado.
10. Servidor/conta incorretos.

A primeira coisa a fazer é rodar:

```bash
python mt5_diagnostics.py
```

Depois olhar:

```text
POSSIBLE GOLD SYMBOLS
symbol_info
symbol_info_tick
volume_min
volume_step
trade_stops_level
filling_mode
trade_mode
trade_exemode
```

---

## 29. Fontes oficiais úteis

- Documentação principal da integração Python com MetaTrader 5:
  - https://www.mql5.com/en/docs/python_metatrader5

- `initialize()`:
  - https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py

- `login()`:
  - https://www.mql5.com/en/docs/python_metatrader5/mt5login_py

- `symbol_info()`:
  - https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py

- `symbol_info_tick()`:
  - https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfotick_py

- `symbol_select()`:
  - https://www.mql5.com/en/docs/python_metatrader5/mt5symbolselect_py

- `order_check()`:
  - https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py

- `order_send()`:
  - https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py

- Trade server return codes:
  - https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes

---

## 30. Resumo final

Para fazer Python enviar ordem no XAUUSD via MT5, a ordem correta é:

```text
1. Inicializar MT5
2. Logar na conta
3. Verificar terminal_info e account_info
4. Descobrir nome real do símbolo
5. Selecionar símbolo no Market Watch
6. Obter symbol_info e symbol_info_tick
7. Normalizar volume
8. Ajustar SL/TP conforme trade_stops_level
9. Escolher type_filling aceito
10. Rodar order_check
11. Rodar order_send
12. Interpretar retcode
13. Registrar logs
14. Só depois integrar ao bot
```

A maioria dos problemas no XAUUSD não está na estratégia do bot, mas sim em **detalhes operacionais da corretora dentro do MT5**: nome do símbolo, lote mínimo, filling mode, stops mínimos e permissão de negociação automática.
