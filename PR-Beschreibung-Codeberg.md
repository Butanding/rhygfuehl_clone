# Bade-Empfehlung überarbeitet: stündliche MeteoSchweiz-Daten, korrigierte Regeln, Diagramme, Tests

Dieser PR behebt die Probleme aus #1 (Regen angezeigt, obwohl es trocken war; Strahlung wirkt zu tief) und #3 (falsche Warnungen an heissen Tagen) und macht die Kachel wieder nutzbar. Sie bleibt standardmässig **ausgeblendet** und erscheint nur mit dem neuen Schalter „Beta“ neben DE/EN.

Testseite mit genau diesem Stand (läuft seit Mitte Oktober 2026): https://butanding.github.io/rhygfuehl_clone/?experiment=on

Die vollständige Herleitung mit Formeln, Beispielen, Rückrechnungen über 2026 und Entscheidungs-Historie steht in `docs/prognosis-logic.md`.

## Was vorher falsch lief

| Problem | Ursache | Lösung |
| :--- | :--- | :--- |
| Regen an trockenen Tagen (#1) | Stichproben aus einer rollenden 24-h-Summe, dadurch wurde derselbe Regen mehrfach gezählt | drei getrennte 24-h-Fenster aus Stundenwerten |
| Unzuverlässige Regenwerte | Einzelsensor St. Johann (Smart Climate, ungeprüft): am 11.10.2026 9.4 mm gemeldet bei 0.0 mm in Binningen, am 8.10. nur 5.4 statt 28.6 mm | MeteoSchweiz Basel-Binningen, Stundenwerte |
| Strahlung hinkt einen Tag hinterher (#1) | Tageswerte, die erst am Folgetag vorliegen | Stundenwerte, gleiche 72 Stunden wie der Regen |
| Falsche Warnung an heissen Tagen (#3) | 22-°C-Sperre; laut Kantonslabor unbegründet (fliessendes Gewässer). 2026 hätte sie an 77 von 121 Tagen gegriffen | Sperre entfernt |
| „Abgeraten“ im Winter fast immer | „Bedeckt“ = Strahlung unter 102 W/m², das erreicht von November bis Februar auch ein wolkenloser Tag nicht | „Bedeckt“ = weniger als 20 % der möglichen Sonnenscheindauer (jahreszeitunabhängig) |
| „Abgeraten“ ohne einen Tropfen Regen | Bedeckt-Regel senkte immer auf Stufe 1 | bedeckt **und** trocken: höchstens „Gut“; bedeckt nach Regen: weiter „Abgeraten“ |
| Bewertung springt von einer Stunde zur nächsten | Regen verlor nach genau 24 h auf einen Schlag die Hälfte seines Gewichts | glatter Abfall (Halbwertszeit 24 h), im Mittel gleich geeicht wie 1 / 0.5 / 0.25 |
| Falsches Ergebnis bei Datenlücken | fehlende Wassertemperatur wurde zu 0 °C („Abgeraten“), fehlende Regenstunden zu 0 mm, alte Daten wurden weitergerechnet | keine Berechnung bei fehlenden oder zu alten Eingangsdaten, siehe unten |

## Änderungen im Einzelnen

**Berechnung (`data/quality.py`, neu, ohne Netz- und Dateizugriff)**
- Regen-Wirkung `I`: jede Stunde der letzten 72 h, gewichtet nach Alter.
- Strahlungs-Bonus `B`: Mittel der letzten 72 h / 170 W/m² (Schwellen unverändert).
- Sonnenschein-Anteil: gemessene Minuten gegenüber der astronomisch möglichen Dauer (Sonne höher als 5°); weicht im Tagesmittel um 1.1 Prozentpunkte vom offiziellen MeteoSchweiz-Wert ab.
- Sicherheit unverändert: ab 18 °C sicher, 14 bis 18 °C Vorsicht, darunter abgeraten.
- Die Regen-Schwellen (0.5 / 1.0 / 1.5 / 2.0 / 3.5 / 5.0 mm) sind unverändert.

**Daten-Abruf (`data/aggregation.py`)**
- Regen, Strahlung und Sonnenschein direkt von MeteoSchweiz (offene Daten, CSV), der Rest wie bisher von data.bs.ch.
- Wassertemperatur: neuester nicht-leerer Wert aus 50 Messungen.
- **Keine Empfehlung bei schlechten Eingangsdaten** (Exit-Code 3, `qualityData.json` behält den letzten Stand): Wetterdaten älter als 3 h, mehr als 3 fehlende Stunden im 72-h-Fenster, eine fehlende Regenstunde in den letzten 24 h, Wassertemperatur fehlt oder ist älter als 6 h. Das passiert planmässig jede Nacht zwischen 00:00 und etwa 02:50 UTC, weil MeteoSchweiz den Vortag erst dann nachträgt.
- Abrufe werden bis zu viermal wiederholt.
- `qualityData.json` enthält zusätzlich `inputs` (womit gerechnet wurde), `reasons` (Begründungs-Codes) und die Zeitpunkte aller Diagrammwerte. Wasser-, Luft- und Pegeldaten bekommen `weekTimes` / `monthTimes`.

**Störungs-Log (`data/health.py`, neu)**
- Schreibt eine CSV-Zeile pro Statuswechsel einer Quelle (verspätet, Ausfall, Lücke, Abruf fehlgeschlagen, wieder gut, mit Dauer) nach `data/health-log.csv`. Eine gesunde Quelle schreibt nichts.

**Oberfläche**
- Kachel als letzte der vier, nur im Beta-Modus sichtbar (Schalter neben DE/EN, `?experiment=on`, bleibt gespeichert).
- Kurze Begründung unter „Wasserqualität“ und die Temperaturregel unter „Bade-Sicherheit“.
- Balkendiagramme (`BarChart.astro`) für Regen sowie Strahlung/Sonnenschein mit den Ansichten 3 Tage (Stundenwerte), Woche und Monat; Farben für helles und dunkles Design.
- Schild „Veraltet“ und Warnhinweis, wenn die Daten älter als 6 Stunden sind (prüft der Browser).
- Kompakte Hinweisbox statt mehrerer Textabsätze; einheitliche Stationsangaben in den drei Messwert-Kacheln.
- Alles deutsch und englisch.

**Tests und Doku**
- 56 Backend-Tests, unter anderem mit echten Stundenwerten vom 6. bis 12.10.2026; neue E2E-Tests für Beta-Schalter und „Veraltet“-Hinweis.
- `docs/prognosis-logic.md` komplett neu geschrieben.

## Bitte beim Review besonders ansehen

1. **`.woodpecker/pipeline.yml` (zwei Zeilen, von mir nicht testbar):** `fetch-data` wertet Exit-Code 3 nicht als Fehler, damit Wasser, Luft und Pegel weiter aktualisiert werden, während die Empfehlung ihren letzten Stand behält. `commit-data` nimmt `data/health-log.csv` mit, sobald die Datei existiert.
2. **Bis zum ersten Cron-Lauf** liegen in `data/data/` noch Dateien im alten Format. Die Kachel fällt dafür auf die bisherigen Liniendiagramme zurück.
3. **Neue Abhängigkeit zur Laufzeit:** `data.geo.admin.ch` (MeteoSchweiz). `data/requirements.txt` bekommt `tzdata`.
4. **Nebenbei enthalten, ohne Wirkung auf rhygfuehl.ch:** Die Seite lässt sich unter einem Unterpfad ausliefern (`SITE_URL`, `BASE_PATH`, `src/utils/base.ts`) und mit `PUBLIC_IS_CLONE=true` ohne Statistik und mit `noindex` bauen. Ohne diese Variablen ändert sich nichts. Kann ich auf Wunsch herausnehmen.

## Bekannte Grenzen

- Die Schwellen sind weiterhin **nicht an Labormessungen geeicht**. Dafür bräuchte es datierte Messwerte (E. coli, Enterokokken) vom Kantonslabor.
- Der Strahlungs-Bonus ist nur etwa von April bis September erreichbar (feste Schwelle 170 W/m²).
- Die Wassertemperatur stammt aus Weil am Rhein, rund 3.3 km flussabwärts.
- Strömung und Pegel fliessen nicht in die Sicherheits-Stufe ein.

## Getestet

- `PYTHONPATH=./data pytest tests/backend/`: 56 bestanden
- `npm run test:unit`: 13 bestanden
- `npm run test:e2e`: bestanden in Chromium (Desktop, Pixel 5 und 320 px Breite). **Nicht** gelaufen in WebKit (die iPhone-Projekte der Playwright-Konfiguration), das übernimmt die CI hier.
