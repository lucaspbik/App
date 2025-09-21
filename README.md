# Wareneingang App für den Maschinenbau

Diese Anwendung digitalisiert den Wareneingang in einem Maschinenbauunternehmen. Sie basiert vollständig auf der Python-Standardbibliothek und benötigt keine externen Web-Frameworks. Die Geschäftslogik und die Tests laufen damit auch in Umgebungen ohne Internetzugang zuverlässig.

## Funktionsumfang

- **Erfassung neuer Anlieferungen** über `POST /deliveries/new`
- **Aktualisierung und Prüfprotokoll** bestehender Wareneingänge über `POST /deliveries/<id>/inspect`
- **Übersichtsseite** (`GET /`) mit Statussummen und optionaler Filterung per `?status=...`
- Speicherung aller Datensätze in einer SQLite-Datenbank

## Projektstruktur

```
app.py                # Einstiegspunkt mit Serverstart
waren_eingang/        # Mini-Webframework + Geschäftslogik
└── __init__.py       # Application-Factory, Routing und DB-Zugriff
```

Die vorhandenen HTML- und CSS-Dateien können für spätere UI-Erweiterungen genutzt werden, sind für den Betrieb jedoch nicht erforderlich.

## Installation & Start

1. Stellen Sie sicher, dass Python 3.11 oder höher installiert ist.
2. Weitere Pakete müssen nicht installiert werden.
3. Starten Sie den integrierten Entwicklungsserver:
   ```bash
   python app.py
   ```
4. Die Anwendung lauscht standardmäßig auf `http://127.0.0.1:8000`.

Beim ersten Start wird automatisch eine SQLite-Datenbank (`waren_eingang.sqlite`) im Projektverzeichnis erzeugt.

## API-Beispiele

### Neuen Wareneingang anlegen

```bash
curl -X POST http://127.0.0.1:8000/deliveries/new   -d "supplier=Bosch"   -d "delivery_note=LS-42"   -d "purchase_order=PO-42"   -d "part_number=AB-123"   -d "quantity_expected=10"
```

### Wareneingang aktualisieren

```bash
curl -X POST http://127.0.0.1:8000/deliveries/1/inspect   -d "status=accepted"   -d "inspector=QS-Meyer"   -d "quantity_received=10"
```

## Tests

```bash
python -m pytest
```

Pytest ist in vielen Python-Distributionen bereits enthalten. Falls nicht, kann es optional nachinstalliert werden.

## Lizenz

Dieses Beispielprojekt darf frei erweitert und an individuelle Abläufe angepasst werden.
