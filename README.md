# pz monitoring bot

Hybrid resource monitor for Project Zomboid 42.20.3 Stable:

```text
in-game mod -> Zomboid/Lua JSON -> local relay -> live JSON -> ordinary ChatGPT
```

No OpenAI API is required. The mod reads live game objects, the relay keeps
history and produces a stable public contract, and ChatGPT reads fresh files
before each gameplay answer.

## Implemented

- character inventory, hands, worn and attached items;
- nested portable containers;
- opened world containers, corpses, and loaded containers inside the base zone;
- itemId, FullType, condition, uses, food state, and weapon ammunition;
- incoming, outgoing, movement, condition, food, and ammunition events;
- human container names, coordinates, ownership, and stale-data markers;
- food/calorie/spoilage views for ChatGPT;
- nearest-known-item search with bag capacity, distance, and direction;
- durable local comparison state;
- optional direct Git push of the three live files.

## Honest search boundary

Search covers observed or last-known indexed items. It does not promise loot in
unexplored locations. A result with `last_known_stale` must be rechecked. The
save-file chunk auditor for unloaded remote areas is a later integration stage.

## Install the test version

```powershell
.\scripts\install.ps1
```

Then enable `pz monitoring bot` in Project Zomboid, load any single-player
save, right-click in the world, and open `Органайзер выжившего`:

- `Установить базу здесь (радиус 30 клеток)` creates a named monitoring zone;
- `Мои базы` lists every zone for the current save with coordinates and radius;
- each base submenu can rename it, scan its resources on demand, or safely delete
  only the organizer entry;
- `Запомнить открытый контейнер` records the currently selected world container;
- `Обновить все записи о ресурсах` writes a fresh snapshot.

Multiple zones such as a bunker, farm, and main home may coexist. Heavy square
scanning runs only on save or an explicit organizer command, never every frame.

Start the foreground relay:

```powershell
.\scripts\run-relay.ps1
```

Stop it with `Ctrl+C`. It is not installed as a service or left running.

## Test

```powershell
.\scripts\test.ps1
```

Current result: 17 passing tests, including four sequential snapshots and the
largest-then-nearest hiking-bag search.

## Ordinary ChatGPT

Use [the Russian ChatGPT playbook](docs/CHATGPT_PLAYBOOK_RU.md). Give ChatGPT
raw URLs for:

- `live/status.json`;
- `live/current_state.json`;
- `live/changes.jsonl`.

Before GitHub publishing, attach these files manually. Ordinary ChatGPT does
not receive background push events; practical realtime means it rereads them
on every user turn.

For a copy-paste connection check against a real snapshot, use
[the Russian test prompt](docs/CHATGPT_TEST_PROMPT_RU.md). It includes a
handshake that verifies the active save, character, base, coverage, totals,
and a user-renamed container without leaking those expected answers into the
prompt itself.

## Safety

The mod does not add private tags to the save. The first relay version does not
open save files at all. Telemetry lives in `Zomboid/Lua`; state and logs live
under `app/runtime`. Permanent watching and auto-push stay disabled until a
real in-game smoke test passes.

See [data contract](docs/DATA_CONTRACT_RU.md) and
[test report](docs/TEST_REPORT_RU.md).

