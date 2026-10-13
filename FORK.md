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

- **Deploy to GitHub Pages:** bei jedem Push auf `main` und planmässig alle 30 Minuten (zu ruhigen
  Minuten, GitHub lässt volle und halbe Stunden gern aus). Führt vorher `data/aggregation.py` aus und
  holt die Messdaten damit direkt von MeteoSchweiz und data.bs.ch, die Test-Seite zeigt also die Wirkung
  der eigenen Berechnung.
  - Sind die Wetterdaten gerade lückenhaft (MeteoSchweiz ergänzt den Vortag erst gegen 02:50 UTC),
    wird nichts gebaut und nichts veröffentlicht: die Seite behält ihre letzte gute Version.
  - Schlägt die Aggregation anders fehl, schlägt der Lauf fehl, die Seite behält ihre letzte Version.
    Einen Rückfall auf die Daten des Originals gibt es nicht mehr (es rechnet mit dem alten, fehlerhaften Modell).
  Die committeten `data/data/*.json` werden daher nicht von Hand angefasst, sonst gibt es
  Konflikte mit den Daten-Commits des Originals.
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
