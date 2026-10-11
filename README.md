# AMPTemplates-TripleA — TripleA game bot for AMP

**AMP Generic Module** template for the **headless game server** ("bot") of **TripleA**, the free
(GPL-3.0) turn-based strategy game inspired by Axis & Allies. Written for TeamKit, a free French
game host, on 11 Oct 2026. CubeCoders ships no TripleA template (checked in
`CubeCoders/AMPTemplates`, 11 Oct 2026).

> Résumé en français à la fin du fichier.

## What runs

TripleA has no "dedicated server" in the usual sense: its multiplayer host is the **headless game
server** (module `game-app/game-headless`, main class `org.triplea.game.server.HeadlessGameRunner`),
the same program the TripleA team runs as its official bots (`Bot_01_…` in the lobby). It:

- registers with the **official lobby** (`https://prod.triplea-game.org`). This is **mandatory**:
  `HeadlessGameRunner` refuses to start without a lobby URI, and `ServerModel` posts the game to the
  lobby during start-up;
- is then **checked by the lobby**: the lobby opens a TCP connection back to the bot's public address
  and port (`ConnectivityCheck` in `triplea-game/lobby-server`, 10 s timeout). If that fails the bot
  logs *"Your computer is not reachable from the internet"* and exits (code 1);
- waits for players; they pick the map and options from their own game, each takes a nation, and the
  game starts by itself when every nation is taken. At the end it goes back to waiting.

**One port: 3300/TCP** (TripleA's default hosting port, `GameRunner.PORT`), and it **must be reachable
from the internet**.

## How it is installed (`scripts/installer-triplea.sh`, at each Update)

1. **TripleA**: `game-headless.zip` of the GitHub release — the latest one (`releases/latest`, the
   version the website hands to players) or a fixed one from the settings. TripleA publishes a
   release for every merge to `main` (calendar versions such as `2026-10.16.15815`, since June 2026).
   The archive is checked (zip, ≥ 10 MB, `bin/game-headless.jar`, and the version written in
   `META-INF/triplea/product.properties` must be the one requested). The two example scripts of the
   archive (`run_bot`, `run_bot.bat`) are removed: they no longer work with this version (old jar
   name, obsolete `-P` options).
2. **Java**: the jar of 2026-10 is compiled for **Java 25** (class file version 69, checked; the
   official Docker image uses `eclipse-temurin:25-jre`). The installer reads the class version from the
   jar, downloads the matching **Eclipse Temurin JRE** from `api.adoptium.net` and checks its
   **SHA-256**; it lives in `java/` inside the instance (same approach as CubeCoders' Mindustry
   template). No Java is needed in the Docker image.
3. **Maps**: download URL and last-change date come from the official catalogue
   `https://prod.triplea-game.org/support/maps/listing` (the one the official bots' `download_maps.py`
   uses). Only `https://github.com/triplea-maps/…` archives are accepted. Each zip is put in `cartes/`
   and **the server extracts it itself** at the next start (`ZippedMapsExtractor`: extracted to
   `cartes/<name>/`, zip deleted). A map is downloaded again only if the catalogue says it changed
   (and the setting allows it). Maps are never deleted.

Each step does nothing when already up to date, and keeps what is installed when the network fails.
`curl`, `unzip` and `perl` (JSON parsing with the core module `JSON::PP`) come from
`ExtraContainerPackages`; image `cubecoders/ampbase:debian`.

Licences: TripleA is **GPL-3.0**; this repository contains **no binary** — the game server, Java and
the maps are downloaded from their official sources at each Update.

## How it is started (`scripts/lancer-triplea.sh`)

`/bin/bash lancer-triplea.sh <port>` reads `reglages-triplea.txt` (rendered by AMP from
`scripts/AMP_reglages-triplea.txt`), filters the values, and starts:

```
java/bin/java -Xmx<memory>m -Xss1250k -Djava.awt.headless=true -Djava.net.preferIPv4Stack=true
  -Duser.home=<instance>/donnees -Djava.util.prefs.systemRoot=<instance>/donnees/.java-systeme
  -Dlogback.statusListenerClass=ch.qos.logback.core.status.NopStatusListener
  -Dtriplea.name=<bot name> -Dtriplea.port=<port> -Dtriplea.lobby.uri=https://prod.triplea-game.org
  -Dtriplea.lobby.game.comments=<comment> -Dtriplea.exit.on.game.end=false
  -jar triplea-serveur/bin/game-headless.jar          (environment: MAPS_FOLDER=<instance>/cartes)
```

- `MAPS_FOLDER` must be an **environment variable** (the code reads `System.getenv("MAPS_FOLDER")`).
- `user.home` keeps autosaves (`donnees/triplea/savedGames/`) and Java preferences inside the instance.
- `-Xss1250k` is the official bot setting; `preferIPv4Stack` makes the lobby see (and check) the IPv4
  address.
- `exit.on.game.end=false`: the bot waits for the next game instead of exiting (the official bots
  exit and are restarted by systemd; AMP would see a normal stop and not restart it).
- On SIGTERM from AMP the script forwards the signal: TripleA saves the running game (autosave
  reloaded at the next start) and exits; its own watchdog cuts after 60 s (`ExitTimeout` is 75 s).
- If the bot stops by itself, the script prints the known causes in French.

Values are never evaluated by the shell: they are filtered character by character and passed to Java
as separate array elements.

## Settings (AMP → Configuration)

| Setting | Default | Effect |
|---|---|---|
| Nom du bot dans le lobby | `Bot_TeamKit_FR` | `triplea.name`. TripleA requires it to **start with `Bot`** and be **7 to 21 characters**, otherwise it refuses to start: the launcher fixes the value (spaces → `_`, accents removed, `Bot_` added, cut at 21) |
| Commentaire dans le lobby | `TeamKit FR` | `triplea.lobby.game.comments`, **14 characters max** (TripleA limit), shown in the lobby's *Comments* column |
| Cartes à installer | `world_war_ii_classic, world_war_ii_revised, world_war_ii_v3, world_war_ii_global` | catalogue names (`mapName`), comma-separated; "World War II Classic" also works |
| Mettre à jour les cartes à chaque Update | ticked | re-download a map when the catalogue says it changed |
| Version de TripleA | empty (latest) | or an exact release tag, e.g. `2026-10.16.15815` |
| Mémoire de Java | 512 MB | `-Xmx` (official bots: 128 MB; more for very large maps) |

The four default maps are World War II **Classic** (4 MB), **Revised** (5 MB), **v3** (9 MB, 1941 and
1942 scenarios) and **Global 1940** (27 MB), all in the *BEST* category of TripleA's own map list
(`triplea_maps.yaml`). `App.MaxUsers` is 9: Global 1940 has nine nations.

**There is no game password.** `triplea.server.password` exists, but the headless server builds its
login validator without it (`HeadlessServerSetupModel`, unchanged since 2022, still so in
2026-10.16.15815): the lobby would show the game as passworded while anyone can join. So no password
setting is offered.

## How players join

Players need **TripleA** from https://triplea-game.org/download/ (Windows, macOS, Linux; the game is
in English) — ideally **the same version** as the bot (written in AMP's console at start), see
*Known limits*.

**Through the lobby (normal way):**

1. Main screen → **Play Online**. Log in with a lobby account, or tick **Login Without An Account**.
2. The lobby lists the games: our bot appears with its name (`Bot_TeamKit_FR`), the comment
   (`TeamKit FR`) and the number of players. Double-click it, or select it and click **Join Game**.
3. In the game set-up window, the first player chooses the map: **Select Game** (the list shows the
   maps installed on the server, and the bot's autosaves), then optionally **Game Options**
   (Low Luck, bids…). They can also load a save from their computer with **Saved Game**.
4. Each player clicks **Play** next to the nation(s) they want (*Played By* column). Nations the map
   allows to disable can be unticked (*Use*); the bot then plays them with its weak AI.
5. When every nation in use has a player, the bot starts the game on its own.

Each player must have **the same map installed** in their own game (main screen → *Download Maps*).

**Directly by address (without the lobby):** main screen → **Connect to Networked Game** → your name,
the server address and port (3300). Tested on 11 Oct 2026: the real game joined the real bot this way
(the bot still has to be registered with the lobby to be running).

## Adding a map

- **From the catalogue**: add its name to *Cartes à installer* (comma-separated), then **Update** and
  restart. Exact names: the `mapName` field of https://prod.triplea-game.org/support/maps/listing
  (313 maps on 11 Oct 2026), or the repository name on https://github.com/triplea-maps. Sizes range
  from 1 MB to 150 MB (UHD versions).
- **By hand** (a map not in the catalogue): put its `.zip` in the instance's `cartes/` folder with
  AMP's file manager and restart; the server extracts it and deletes the zip.
- **Removing**: delete the map folder in `cartes/` (the template never deletes a map: saved games may
  need it).

## Known limits

- **The lobby is mandatory** and the bot depends on it: if `prod.triplea-game.org` is down, the bot
  cannot start (*"Failed to run game server … Connection refused"*); AMP retries twice.
- **Port 3300/TCP must be reachable from the internet**, or the lobby's check fails and the bot stops
  with *"Your computer is not reachable from the internet"*. The bot announces the port it listens on:
  the container's port must be published under the **same number** (AMP does so).
- **Lobby moderators** (TripleA volunteers) can remove our game from the list, have banned players
  disconnected from it, or send it a **shutdown** signal (lobby actions *Boot Game* / *Shutdown*); a
  shutdown exits the bot with code 0, which AMP may treat as a normal stop (restart the instance).
- **No game password** (see above): anyone in the lobby can join.
- **Versions**: since June 2026 TripleA no longer checks that the player's game and the host have the
  same version (commit "Versioning: convert to 'calver' style", *Remove version requirements in P2P
  network games*), and a release is published for every merge. Close versions usually work together,
  distant ones may fail during a game. Keep the bot on the latest release (Update) or pin the version
  the community uses. The in-game update reminder does not work at the moment (the lobby answers 404 to
  `support/latest-version`, seen on 11 Oct 2026).
- **No chat or admin commands from AMP**: the server reads no console input (AMP's console is
  read-only); there is no in-game admin either. AMP's user list comes from the join/leave log lines.
- The game is in English (and German); there is no French translation.

## Tested (11 Oct 2026)

- Real `game-headless.zip` 2026-10.16.15815 with a Temurin 25 JRE (Windows), a **local fake lobby**
  (never the official one) and a real map: map extraction, start, game posted to the lobby, ready line;
  **the real TripleA game client joined the bot** (`-Dtriplea.client=true`), which gave the exact
  join/leave lines used by AMP's regexes; failure cases (lobby unreachable, reverse check failed, bad
  name) exit with code 1 within a second.
- `installer-triplea.sh` against the real GitHub release and the real map catalogue (Java faked, since
  a Linux JRE cannot run on Windows): 23 s for the server and two maps; second run does nothing.
- `verifier.py`: JSON, kvp, each setting down to its destination, ~35 real runs of the launcher with a
  fake Java (trapped values: `$( )`, backticks, quotes, newline injection, accents, CRLF, unreplaced
  variables), SIGTERM forwarding, the installer with a fake `curl` (latest/pinned/invalid versions,
  SHA-256 of Java, maps new/up-to-date/changed/unknown/foreign URL), console regexes.

**Not yet tested inside AMP / on Linux**: the Linux JRE in `cubecoders/ampbase:debian`, the reverse
check by the real lobby through AMP's Docker port mapping, a full game with several players.

---

## Résumé en français

Template AMP pour héberger un **bot de partie TripleA** (le serveur « headless » officiel, le même
programme que les bots officiels du lobby). À chaque **Update** : dernière version de TripleA (ou une
version fixée) depuis GitHub, **Java 25** (Eclipse Temurin, empreinte SHA-256 vérifiée) et les cartes
choisies depuis le catalogue officiel (par défaut World War II Classic, Revised, v3 et Global 1940).
Rien n'est stocké dans ce dépôt (TripleA est sous GPL-3.0).

- **Lobby obligatoire** : le bot s'inscrit au lobby officiel, qui vérifie qu'il est joignable sur le
  **port 3300/TCP** depuis internet ; sinon le bot s'arrête.
- **Rejoindre** : dans TripleA, *Play Online* → se connecter (ou *Login Without An Account*) →
  double-clic sur `Bot_TeamKit_FR` → *Select Game* pour choisir la carte → chacun clique *Play* à côté
  de sa nation → la partie démarre seule quand toutes les nations sont prises. Connexion directe
  aussi : *Connect to Networked Game*, adresse et port 3300. Chaque joueur doit avoir la même carte
  (*Download Maps*) et de préférence la même version que le bot.
- **Ajouter une carte** : ajouter son nom dans *Cartes à installer*, puis Update et redémarrage ; ou
  déposer le `.zip` dans `cartes/` avec le gestionnaire de fichiers d'AMP.
- **Limites** : pas de mot de passe de partie (TripleA ne l'applique pas en mode bot), les
  modérateurs du lobby peuvent arrêter le bot, pas de commande depuis la console d'AMP, jeu en
  anglais, versions client/serveur non vérifiées par TripleA depuis juin 2026.
