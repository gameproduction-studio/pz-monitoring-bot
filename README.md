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
- per-save registration of keyed vehicles with rename/update/remove actions;
- vehicle fuel, battery, engine, overall/part condition, position and cargo;
- itemId, FullType, condition, uses, food state, and weapon ammunition;
- incoming, outgoing, movement, condition, food, and ammunition events;
- human container names, coordinates, ownership, and stale-data markers;
- food/calorie/spoilage views and low-fuel/weak-part vehicle alerts for ChatGPT;
- nearest-known-item search with bag capacity, distance, and direction;
- durable local comparison state;
- direct Git push of only the approved `chatgpt_state.json` file.

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
- right-click a vehicle while carrying its key, then choose
  `Закрепить автомобиль за собой`;
- `Текущее авто` and `Мои автомобили` rename, refresh, or safely forget a
  registered vehicle without modifying the vehicle itself;
- `Обновить все записи о ресурсах` writes a fresh snapshot.

Multiple zones such as a bunker, farm, and main home may coexist. Registered
vehicles are scoped to the active save and tracked by vehicleId with keyId as
supporting identity. Heavy square and vehicle scanning runs only on save or an
explicit organizer command, never every frame.

Start the foreground relay:

```powershell
.\scripts\run-relay.ps1
```

Stop it with `Ctrl+C`. It is not installed as a service or left running.

## Automatic one-button mode

Install the background relay once:

```powershell
.\scripts\install-autostart.ps1
```

It starts immediately and again at Windows sign-in. From then on the normal
workflow is only:

1. use `Обновить все записи о ресурсах` in the in-game organizer;
2. the mod writes local telemetry;
3. the background relay waits for both JSON files to stabilize;
4. it updates four local `live` files and pushes only `chatgpt_state.json`;
5. ChatGPT rereads that GitHub file on the next user turn.

The relay polls two file timestamps every five seconds; it never scans game
containers and therefore does not affect in-game FPS. Stop it with
`.\scripts\stop-relay.ps1`. Remove Windows autostart with
`.\scripts\uninstall-autostart.ps1`.

## Test

```powershell
.\scripts\test.ps1
```

Current result: 32 passing tests, including sequential item snapshots,
registered-vehicle cargo, stale carry-forward, removal, fuel/condition events,
alerts, and the largest-then-nearest hiking-bag search.

## Ordinary ChatGPT

Use [the Russian ChatGPT playbook](docs/CHATGPT_PLAYBOOK_RU.md). Give ChatGPT
the GitHub URL for:

- `live/chatgpt_state.json` (connector-safe gameplay facts, normally below 1 MB);

`live/current_state.json`, `status.json`, and `changes.jsonl` remain local diagnostic
files. Ordinary ChatGPT reads `chatgpt_state.json`; it embeds synchronization
status and the most recent changes while staying below the connector limit.

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
under `app/runtime`. The relay reads only exported telemetry and never modifies the Project
Zomboid save.

See [data contract](docs/DATA_CONTRACT_RU.md) and
[test report](docs/TEST_REPORT_RU.md).

