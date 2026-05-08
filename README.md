# Antarctica

MVP детектора асимметрии ликвидности для Московской биржи. Проект анализирует Level II стакан и ленту сделок, ищет bid/ask-стены, отличает удержание стены от резкого снятия и выдает торговые сигналы.

Это исследовательский прототип, не готовый торговый робот. Для реальной торговли нужны проверка качества данных, задержки, исполнение заявок, риск-лимиты брокера и отдельный контур аварийной остановки.

## Формат данных

Стакан: `timestamp_ms,bid_px_1,bid_sz_1,ask_px_1,ask_sz_1,...`

Сделки: `timestamp_ms,price,size,aggressor`, где `aggressor` равен `buy`, `sell` или `unknown`.

Для MOEX задавайте тик-сайз и размер лота конкретного инструмента. Например, для SBER шаг цены обычно `0.01`, лот `10`.

## Запуск примера

```bash
python3 -m antarctica.cli --symbol SBER --tick-size 0.01 --lot-size 10 --book examples/book.csv --trades examples/trades.csv
```

## Реальные данные MOEX ISS

Загрузка публичных данных Московской биржи через ISS:

```bash
python3 -m antarctica.cli --source moex --symbol SBER --board TQBR --polls 3 --interval-sec 1 --top-of-book --dump-events
```

По умолчанию `--source moex` пытается использовать endpoint стакана Level II:

```bash
python3 -m antarctica.cli --source moex --symbol SBER --board TQBR
```

Если ISS возвращает HTML вместо JSON, значит для полного стакана по этому endpoint нет доступа к market-data подписке. В этом случае `--top-of-book` использует публичную таблицу `marketdata` с лучшим Bid/Offer и реальные анонимные сделки, но это не полноценный стакан и не подходит для финальной версии стратегии «Антарктида».

## Постоянный режим

Live-режим работает до `Ctrl+C`, сохраняет состояние детектора между опросами и печатает JSON lines:

```bash
python3 -m antarctica.live --symbol SBER --board TQBR --interval-sec 1 --top-of-book --dump-events
```

Для короткой проверки без бесконечного цикла:

```bash
python3 -m antarctica.live --symbol SBER --board TQBR --interval-sec 1 --top-of-book --max-polls 3
```

Если появляется сигнал, строка будет иметь `"kind": "signal"`. Строки `"kind": "status"` показывают запуск, периодическую работу и остановку. Без `--top-of-book` live-режим пытается читать Level II стакан и завершится с понятной ошибкой, если у ISS endpoint нет доступа.

## Запись истории

Recorder копит сырые события в JSONL-файлы, чтобы потом прогонять стратегию replay-режимом или анализировать микроструктуру отдельно:

```bash
python3 -m antarctica.recorder --symbol SBER --board TQBR --interval-sec 1 --top-of-book
```

Короткая проверка:

```bash
python3 -m antarctica.recorder --symbol SBER --board TQBR --interval-sec 1 --top-of-book --max-polls 3
```

Файлы пишутся в `data/raw/<SYMBOL>/<BOARD>/<YYYY-MM-DD>.jsonl`. Каждая строка содержит одно событие `book` или `trade`, `timestamp_ms`, `symbol`, `board` и источник. Папка `data/` добавлена в `.gitignore`, чтобы не коммитить большие рыночные записи.

## Replay Записанной Истории

Прогон стратегии по JSONL-файлу, записанному recorder:

```bash
python3 -m antarctica.replay_jsonl data/raw/SBER/TQBR/2026-05-08.jsonl --symbol SBER --tick-size 0.01 --lot-size 1 --summary
```

Если стратегия найдет сигнал, он будет напечатан строкой JSON с `"kind": "signal"`. С `--summary` в конце печатается количество обработанных событий и сигналов.

Проверка на нескольких MOEX-подобных инструментах с разными шагами цены:

```bash
python3 examples/multi_symbol_demo.py
```

Пресеты в `examples/multi_symbol_demo.py` нужны для smoke test логики. Перед реальным прогоном берите актуальные `tick_size`, `lot_size` и режим торгов из брокера, QUIK или MOEX ISS для конкретного инструмента и board.

## Логика сигналов

`wall_held`: цена подошла к стене, агрессивные сделки били в нее, часть объема исполнилась, но стена не была снята. Для bid-стены это long, для ask-стены short.

`wall_removed`: стена была рядом с ценой, затем быстро исчезла, и цена пробила ее уровень. Для снятой bid-стены это short, для снятой ask-стены long.

Ключевые пороги находятся в `antarctica/config.py`: отношение bid/ask, размер стены к локальному среднему, время жизни стены, окно удержания, доля исполненного и снятого объема.
