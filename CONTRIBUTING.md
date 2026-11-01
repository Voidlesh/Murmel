# Mitwirken an Murmel

Danke, dass du Murmel verbessern möchtest! Fehlerberichte, Ideen und Pull Requests sind willkommen.

## Fehler melden oder Feature vorschlagen

1. Prüfe zuerst die [bestehenden Issues](https://github.com/Voidlesh/Murmel/issues), ob dein Anliegen schon bekannt ist.
2. Eröffne ein neues Issue mit:
   - Windows-Version, GPU (NVIDIA-Modell oder CPU) und Python-/Node-Version
   - Schritten zum Reproduzieren und dem erwarteten Verhalten
   - Auszügen aus `%APPDATA%\Murmel\engine.log`, falls relevant (**bitte vorher persönliche Inhalte entfernen**, z. B. Diktate und Pfade)

## Entwicklungsumgebung

Die Einrichtung steht in der [README](README.md#installation). Für die Entwicklung zusätzlich:

```powershell
.venv\Scripts\python.exe -m pip install pytest
```

## Pull Requests

- Erstelle einen Branch von `main` mit einem aussagekräftigen Namen, z. B. `fix/hotkey-release` oder `feat/neue-stilvorlage`.
- Halte PRs klein und auf ein Anliegen fokussiert.
- Schreibe für neue Logik Tests in `tests/` und stelle sicher, dass alle Tests grün sind:

  ```powershell
  .venv\Scripts\python.exe -m pytest tests
  ```

- Verwende [Conventional Commits](https://www.conventionalcommits.org/de/) für Commit-Nachrichten, z. B. `fix: Hotkey-Release bei Freihand-Modus`.
- Beschreibe im PR, was sich ändert und wie du es getestet hast.

## Code-Stil

- **Python:** PEP 8, Typannotationen wo sinnvoll, Kommentare nur, wo das *Warum* nicht offensichtlich ist.
- **JavaScript (Electron-Renderer):** Vanilla JS, kein Build-Schritt. Passe den Stil an die umgebende Datei an.
- Keine Secrets, Passwörter oder persönlichen Daten committen – auch nicht in Tests oder Beispieldaten.

## Lizenz

Mit deinem Beitrag stimmst du zu, dass er unter der [MIT-Lizenz](LICENSE) des Projekts veröffentlicht wird.
