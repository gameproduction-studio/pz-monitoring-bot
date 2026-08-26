# pz monitoring bot

Hybrid resource monitor for Project Zomboid 42.20.3 Stable:

```text
in-game mod -> Zomboid/Lua JSON -> local relay -> live JSON -> ordinary ChatGPT
                                      |
                                      +-> local browser dashboard
```

No OpenAI API is required. The mod reads live game objects, the relay keeps
history and produces a stable public contract, and ChatGPT reads fresh files
before each gameplay answer.

## Implemented

- character inventory, hands, worn and attached items;
- nested portable containers;
- stationary containers inside saved base zones; external containers, corpses, and ground loot are excluded;
- per-save registration of keyed vehicles with rename/update/remove actions;
- vehicle fuel, battery, engine, overall/part condition, position and cargo;
- itemId, FullType, condition, uses, food state, and weapon ammunition;
- incoming, outgoing, movement, condition, food, and ammunition events;
- human container names, coordinates, ownership, and stale-data markers;
- food/calorie/spoilage views with exact fresh/stale/rotten semantics, freezer protection, and compost/disposal handling;
- compact named quantity/location summaries plus low-fuel/weak-part vehicle alerts for ChatGPT;
- nearest-known-item search with bag capacity, distance, and direction;
- durable local comparison state;
- direct Git push of only the approved `chatgpt_state.json` file.
- private browser dashboard on `http://127.0.0.1:8765/` with overview,
  bases, vehicles, food, resources, history, search, and responsive fullscreen layout;
- dashboard language auto-detection from the game plus a local manual override.

## Honest search boundary

Persistent search covers only the character, stationary storage inside saved
bases, and cargo of registered vehicles. Random world containers, corpses, and
ground loot are intentionally not accumulated. A separate one-shot external
search can be added later without expanding the permanent public snapshot.

## Install the test version

```powershell
.\scripts\install.ps1
```

Then enable `pz monitoring bot` in Project Zomboid, load any single-player
save, right-click in the world, and open `Органайзер выжившего`:

- `Установить базу здесь` offers a radius of 10, 20, 30, or 40 tiles;
- `Мои базы` lists every zone for the current save with coordinates and radius;
- each base submenu can rename it, change its radius without creating a copy,
  scan resources on demand, or safely delete only the organizer entry;
- right-click a vehicle while carrying its key, then choose
  `Закрепить автомобиль за собой`;
- `Текущее авто` and `Мои автомобили` rename, refresh, or safely forget a
  registered vehicle without modifying the vehicle itself;
- `Сделать опись` вручную сканирует персонажа, базы и закреплённые автомобили;
- `Сделать расчёты` передаёт уже готовую опись внешней программе: она считает остатки, калории, дубликаты и точные планы блюд по локальным правилам установленного Build 42.20.3. Для каждого блюда публикуются ингредиенты, места хранения, расход, вода, число мисок и пищевая ценность; ChatGPT получает готовый расчёт вместо угадывания рецепта.

Multiple zones such as a bunker, farm, and main home may coexist. Registered
vehicles are scoped to the active save and tracked by vehicleId with keyId as
supporting identity.

For stable gameplay, the mod never scans, serializes, or writes telemetry in the
background and does not hook inventory transfers. Use `Сделать опись` in a safe
place when you want a fresh complete snapshot. Then use `Сделать расчёты`; the
external relay performs the heavy work outside the game and pushes the result
automatically. A temporary lightweight acknowledgement check exists only while
that explicit calculation request is pending and removes itself on completion or timeout.

Start the foreground relay:

```powershell
.\scripts\run-relay.ps1
```

The same process also serves the private dashboard:

```text
http://127.0.0.1:8765/
```

Open that address in a browser and use `F11` for a clean fullscreen panel.
The browser polls only a tiny local health record and reloads the large tables
when the inventory sequence or scan time changes. It never scans the game.

Stop the foreground process with `Ctrl+C`. It is not installed as a service
or left running.

## Automatic one-button mode

Install the background relay once:

```powershell
.\scripts\install-autostart.ps1
```

It starts immediately and again at Windows sign-in. From then on the normal
workflow is only:

1. play normally without background world scans;
2. choose `Сделать опись` when you want to refresh monitored resources;
3. choose `Сделать расчёты` and wait for `Расчёты припасов завершены`;
4. the relay calculates outside the game from the stable snapshot and installed Build 42.20.3 data;
5. it pushes the bootstrap, manifest, thematic pages and calculation pages automatically;
6. ChatGPT rereads the manifest and only the sections needed for the next answer.

The relay polls two file timestamps every five seconds; it never scans game
containers and therefore does not affect in-game FPS. Stop it with
`.\scripts\stop-relay.ps1`. Remove Windows autostart with
`.\scripts\uninstall-autostart.ps1`.

Dashboard defaults live in `app/config.json`:

```json
{
  "dashboard": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8765,
    "language": "auto"
  }
}
```

Keep the host on a loopback address. The server rejects non-loopback binds.
Use the selector in the panel for a temporary language override; `auto`
follows the language exported by Project Zomboid.

## Test

```powershell
.\scripts\test.ps1
```

Current result: 46 passing tests, including the loopback dashboard, scoped sequential snapshots,
registered-vehicle cargo, stale carry-forward, removal, fuel/condition events,
alerts, bounded journal preservation, and base-only item search.

## Ordinary ChatGPT

Use [the Russian ChatGPT playbook](docs/CHATGPT_PLAYBOOK_RU.md). Give ChatGPT
the GitHub URL for:

- `live/chatgpt_state.json` (small v4 bootstrap);
- `live/chatgpt/manifest.json` (authoritative index for one snapshot);
- connector-safe thematic pages for character, bases, vehicles, food, changes,
  resources, and precomputed supply/recipe calculations (each at most 32 KB).

`live/current_state.json`, `status.json`, and `changes.jsonl` remain local diagnostic
files. Ordinary ChatGPT reads the bootstrap, then the manifest, then only the
thematic files needed for the question. Large lists are deterministically paged,
so inventory growth cannot make one response exceed the connector limit.

Ordinary ChatGPT does not receive background push events; practical realtime means the relay publishes automatically and ChatGPT rereads `chatgpt_state.json` on every user turn.

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

