# Wareneingang App für den Maschinenbau

Diese Flask-Anwendung digitalisiert den Wareneingang in einem Maschinenbauunternehmen. Sie unterstützt Einkauf, Wareneingang und Qualitätssicherung bei der Erfassung von Anlieferungen sowie der Dokumentation von Prüfungen und Nacharbeit.

## Funktionsumfang

- **Dashboard** mit Status-Kacheln und Filterfunktion (angemeldet, in Prüfung, freigegeben, Nacharbeit, gesperrt)
- **Erfassung neuer Anlieferungen** inkl. Pflichtfeldern, Mengen, Priorität, Prüfpflicht und Zeugnisstatus
- **Wareneingangsprüfung** mit Dokumentation von Prüfer, geprüfter Menge, Lagerort, Kommentaren und nächsten Schritten
- **Statusverfolgung** mit Zeitstempeln für Erfassung und Prüfung
- Responsives Layout für Tablets / mobile Geräte

## Projektstruktur

```
app.py                # Einstiegspunkt
waren_eingang/        # Flask-Anwendung
├── __init__.py       # App-Factory, Routen, DB-Setup
├── templates/        # HTML-Templates (Jinja)
└── static/css/       # Stylesheet
```

## Installation & Start

1. Virtuelle Umgebung anlegen (optional):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
3. Anwendung starten:
   ```bash
   flask --app app run
   ```

Die SQLite-Datenbank wird automatisch erzeugt (`waren_eingang/waren_eingang.sqlite`).

## Tests

Automatisierte Tests prüfen das Anlegen und Aktualisieren von Wareneingängen:

```bash
pytest
```

## Anpassungsmöglichkeiten

- In `waren_eingang/__init__.py` kann über `COMPANY_NAME` der Firmenname angepasst werden.
- Status-Optionen und Farbkennzeichnungen lassen sich über `STATUS_CHOICES` / `STATUS_CLASSES` erweitern.
- Weitere Felder können in der Tabelle `deliveries` ergänzt werden (z. B. Chargennummern, Dokumentenlinks).

## Lizenz

Dieses Beispielprojekt kann frei erweitert und an individuelle Prozesse angepasst werden.
