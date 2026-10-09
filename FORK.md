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

- **Deploy to GitHub Pages:** bei jedem Push auf `main` und alle 30 Minuten. Holt vorher
  die aktuellen Messdaten (`data/data/*.json`) vom Original, damit die Test-Seite dieselben
  Daten wie rhygfuehl.ch zeigt.
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
