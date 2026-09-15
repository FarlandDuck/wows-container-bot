# WoWS Container Bot

A Discord bot for **World of Warships** communities that simulates opening in-game containers (like Santa's Gifts, Coal Containers, Steel Containers, etc.), tracks drop pools defined in JSON, and can run a Monte Carlo simulation to estimate how many containers a player will need to complete a full collection (e.g., a full set of camouflages, commanders, or event ships).

Drops are modeled after real World of Warships reward types — premium/tech-tree ships, Coal, Steel, Doubloons, Free XP, Elite Commander XP, Research Points, Premium Account time, and themed XP/Credits boosters — but the container format is generic enough to represent any container Wargaming introduces.

## Features

- **`!open [container name]`** — Opens a container and returns a random drop, based on the drop rates and structure defined in that container's JSON file. Supports fuzzy name matching, so small typos in the container name still resolve to the closest match.
- **`!info`** — Lists all containers currently loaded by the bot.
- **`!collection [total items] [owned items] [tokens owned] [duplicates owned] [conversion rate]`** — Runs a 100,000-trial simulation of opening containers until a full collection is completed, and returns a chart showing how many containers are needed at each percentile of outcomes.
- **`!help`** — Displays an embedded list of all commands.

## Requirements

- Python 3.9+
- A Discord bot token
- The following Python packages:
  - `discord.py`
  - `matplotlib`
  - `numpy`

Install dependencies with:

```bash
pip install discord.py matplotlib numpy
```

## Setup

1. **Create a Discord bot application** at the [Discord Developer Portal](https://discord.com/developers/applications), and copy its bot token.
2. **Enable the Message Content Intent** for your bot in the Developer Portal (under Bot → Privileged Gateway Intents), since this bot reads message content to parse commands.
3. **Set the bot token as an environment variable** named `DISCORD_TOKEN`:

   ```bash
   export DISCORD_TOKEN="your-token-here"
   ```

   On Windows (PowerShell):

   ```powershell
   $env:DISCORD_TOKEN="your-token-here"
   ```

4. **Create a `containers` folder** in the same directory as the bot script, and add one `.json` file per container (see [Container File Format](#container-file-format) below).
5. **Run the bot:**

   ```bash
   python bot.py
   ```

6. **Invite the bot to your server** using an OAuth2 invite link generated in the Developer Portal, with at minimum the `bot` scope and permission to send messages, embed links, and attach files.

## Commands

### `!open [container name]`

Opens the named container and returns an embed with the resulting drop(s).

- Container names are matched with fuzzy matching, so `!open galaxy cas` will still match a container named "Galaxy Case."
- Containers can have either a single drop pool (legacy format) or multiple independent "slots," each producing its own drop (e.g., for containers that yield more than one item per opening).
- Drop pools can be nested — a drop can itself contain a sub-pool of further possible drops, which the bot will resolve recursively.

Example:
```
!open santa's ultra gift
```

### `!info`

Lists the nicknames of every container currently loaded from the `containers` folder.

Example:
```
!info
```

### `!collection [n] [k] [t] [d] [c]`

Simulates the process of completing a full in-game collection (e.g., a Yamamoto Isoroku commander collection, a camouflage set, or an event collection) by opening containers repeatedly, and returns a chart of containers-needed vs. percentile of players.

| Argument | Meaning |
|---|---|
| `n` | Total number of unique items in the collection (max 100) |
| `k` | Number of unique items already owned |
| `t` | Collection tokens already banked (tokens can be redeemed for any missing item) |
| `d` | Duplicate items currently owned toward the next token conversion |
| `c` | Number of duplicates required to convert into one token |

Notes:
- `d` must be less than `c` — the game is assumed to auto-convert duplicates into tokens as soon as the conversion threshold is hit, so `d` should reflect only the "leftover" duplicates below that threshold.
- The bot runs 100,000 simulated trials and plots the distribution of containers needed, so you can see not just an average but the full range of likely outcomes (e.g., "50% of players will need fewer than X containers").

Example:
```
!collection 50 30 2 3 5
```
This simulates a 50-item collection where the player owns 30 unique items, has 2 tokens banked, has 3 duplicates toward the next token, and needs 5 duplicates to earn a token.

### `!help`

Displays this list of commands directly in Discord.

## Container File Format

Each container is defined as its own `.json` file inside the `containers` folder. The bot loads every `.json` file in that folder at startup and indexes it by its lowercase `nickname`.

### Required fields

| Field | Type | Description |
|---|---|---|
| `nickname` | string | Short internal identifier used for lookup (case-insensitive) and fuzzy matching against `!open`. |
| `name` | string | Display name shown in the embed title. |
| `color` | string | Hex color code (e.g., `"#5865F2"`) used for the embed's side color. |

### Optional fields

| Field | Type | Description |
|---|---|---|
| `image` | string (URL) | Thumbnail image shown on the container's embed. |

### Drop structure

A container uses **one** of the following two structures:

#### Legacy single-slot format

```json
{
  "nickname": "coal15",
  "name": "15 Point Coal Container",
  "color": "#5865F2",
  "image": "https://example.com/coal-container.png",
  "drops": [
    { "name": "6,000 Coal", "rate": 70, "link": "https://example.com/coal.png" },
    { "name": "2,500 Doubloons", "rate": 25, "link": "https://example.com/doubloons.png" },
    { "name": "Premium Ship", "rate": 5, "link": "https://example.com/ship.png" }
  ]
}
```

- Produces exactly one drop from the `drops` list.
- If every entry includes a `rate` key, drops are weighted by that rate (rates should sum to 100).
- If no entry includes a `rate` key, all entries are treated as equally likely.

#### Multi-slot format

```json
{
  "nickname": "ultra",
  "name": "Santa's Ultra Gift 2025 Container",
  "color": "0xCF3A22",
  "image": "https://example.com/santas-gift.png",
  "slots": [
    { "drops": [ ... ] },
    { "drops": [ ... ] },
    { "drops": [ ... ] }
  ]
}
```

- Each entry in `slots` is resolved independently, so the container yields one drop per slot — for example, one slot resolving to a ship or resource reward, and separate slots each resolving to a bonus booster.
- The first slot's drop image is used as the embed's main image; all resulting drop names are listed in the embed description.
- `color` can be given as a `#RRGGBB` hex string or a `0xRRGGBB` literal — both are accepted.

#### Nested drop pools

Any individual drop entry can include its own `drops` sub-pool instead of being a final item. This is how WoWS-style tiered containers are represented — e.g., "container → reward category → specific ship":

```json
{
  "name": "Premium Ship",
  "rate": 32,
  "drops": [
    {
      "name": "Tier VI–VIII Pool",
      "rate": 62.5,
      "drops": [
        { "name": "Admiral Makarov", "link": "https://example.com/makarov.png" },
        { "name": "Arkhangelsk", "link": "https://example.com/arkhangelsk.png" },
        { "name": "Scharnhorst", "link": "https://example.com/scharnhorst.png" }
      ]
    }
  ]
}
```

You can nest this as deeply as needed — e.g. an ultra-rare "Golden Ship" sub-pool (with a very low `rate`, such as `0.01`) alongside a common "Tier X Ship" sub-pool (`rate: 99.99`), so that a single top-level "Golden Gift" outcome can resolve all the way down to one specific golden ship skin.

When a drop with a nested `drops` list is selected, the bot recurses into that sub-pool to determine the final item.

## Logging

Every container opening is logged to the console with a timestamp, the user who opened it, and the resulting drop(s), which is useful for auditing drop rates or debugging container files.

## Notes & Limitations

- `!collection` caps the total collection size at 100 items.
- The bot has no persistent storage — it does not track what any individual user actually owns; `!open` always draws independently from the container's odds, and `!collection` is a standalone simulation based on the numbers you provide, not live inventory tracking.
- Container data is loaded once at startup; if you add or edit files in the `containers` folder, restart the bot to pick up the changes.