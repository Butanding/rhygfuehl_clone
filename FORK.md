# Test-Klon von rhygfuehl.ch

Dieses Repo ist ein Klon von [codeberg.org/chric/rhygfuehl](https://codeberg.org/chric/rhygfuehl).
Er dient dazu, eigene Änderungen über längere Zeit zu testen, ohne die Live-Seite zu berühren.

- **Test-Seite:** https://butanding.github.io/rhygfuehl_clone/
- **Live-Original:** https://rhygfuehl.ch

## Branches

| Branch     | Inhalt |
|------------|--------|
| `main`     | Eigener Stand: Original + eigene Änderungen. Wird auf GitHub Pages veröffentlicht. |
| `upstream` | Exakter Spiegel von Codeberg `main`. Nicht von Hand ändern. |

Eigene Änderungen gegenüber dem Original:
https://github.com/Butanding/rhygfuehl_clone/compare/upstream...main

## Automatisch

- **Deploy to GitHub Pages:** bei jedem Push auf `main` und planmässig alle 5 Minuten (das ist das
  Kürzeste, was GitHub erlaubt, zu ruhigen Minuten). Das Original macht dasselbe auf Codeberg alle
  15 Minuten mit einem zuverlässigen CI-Zeitplan; der von GitHub ist nur nach bestem Bemühen und lässt
  viele Läufe aus, darum der dichte Takt. Ein geplanter Lauf holt die Daten mit `data/aggregation.py`
  (direkt von MeteoSchweiz und data.bs.ch) und vergleicht einen Fingerabdruck (die neuesten Zeitstempel)
  mit dem, der neben der Seite liegt (`fingerprint.txt`). Gibt es nichts Neues, endet der Lauf nach
  etwa einer halben Minute, ohne zu bauen. Nur neue Daten (oder ein Push) bauen und veröffentlichen.
  Wie viele Läufe GitHub wirklich startet, entscheidet GitHub; darum gibt es zusätzlich **Keep fresh**.
  - Sind die Wetterdaten gerade lückenhaft (MeteoSchweiz ergänzt den Vortag erst gegen 02:50 UTC),
    wird nichts gebaut und nichts veröffentlicht: die Seite behält ihre letzte gute Version.
  - Schlägt die Aggregation anders fehl, schlägt der Lauf fehl, die Seite behält ihre letzte Version.
    Einen Rückfall auf die Daten des Originals gibt es nicht mehr (es rechnet mit dem alten, fehlerhaften Modell).
  Die committeten `data/data/*.json` werden daher nicht von Hand angefasst, sonst gibt es
  Konflikte mit den Daten-Commits des Originals.
- **Keep fresh:** verkettet sich selbst, ohne Abhängigkeit vom GitHub-Zeitplan. Ein Lauf dauert gut
  5½ Stunden, startet in dieser Zeit alle 5 Minuten `Deploy to GitHub Pages` (mit `only_if_new=true`:
  veröffentlicht nur bei neueren Daten) und startet am Ende den nächsten Lauf von sich selbst
  (`workflow_dispatch` mit dem eingebauten Token löst als einer der wenigen Auslöser weitere Workflows aus).
  Reisst die Kette (Fehler, Abbruch), startet der Zeitplan (alle 30 Minuten) sie wieder; es läuft nie
  mehr als einer, ein zweiter wartet. Einmal von Hand starten: Actions → Keep fresh → Run workflow.
  Abschalten: den Workflow in den Actions deaktivieren. Hinweis: Der Lauf ist dauernd aktiv; in
  einem öffentlichen Repository kostet das nichts, in einem privaten zählt es zu den Freiminuten.
- **Sync from upstream:** täglich. Aktualisiert `upstream` und merged es in `main`.
  Bei einem Merge-Konflikt schlägt der Job fehl (GitHub schickt eine Mail). Dann lokal:
  `git fetch origin && git checkout main && git merge origin/upstream`, Konflikte lösen, pushen.

## Unterschiede zur Live-Seite

Gesteuert über Umgebungsvariablen beim Build (siehe `.github/workflows/deploy-pages.yml`);
ohne diese baut der Code exakt wie das Original:

- `BASE_PATH` / `SITE_URL`: Seite läuft unter dem Unterpfad `/rhygfuehl_clone/`.
- `PUBLIC_IS_CLONE=true`: `noindex`-Meta-Tag, kein Umami-Tracking (verfälscht die Statistik des Originals nicht).
- `robots.txt` sperrt alles, `sitemap.xml` wird entfernt.

## Eigene Domain (optional)

1. Beim DNS-Anbieter einen CNAME-Eintrag anlegen, z. B. `test.example.ch` → `butanding.github.io`.
2. Im Repo unter *Settings → Pages → Custom domain* die Domain eintragen, *Enforce HTTPS* aktivieren.

Der Unterpfad fällt dann automatisch weg (der Workflow liest ihn aus der Pages-Konfiguration).
