<div align="center">

# Murmel

**Diktieren statt tippen – lokal, schnell und kostenlos.**

Eine Diktier-App für Windows, inspiriert von [Wispr Flow](https://wisprflow.ai/).
Taste halten, sprechen, loslassen – der Text landet dort, wo dein Cursor gerade steht.

[![Plattform: Windows](https://img.shields.io/badge/Plattform-Windows%2010%20%2F%2011-0078D6)](#voraussetzungen)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-green)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB)](https://www.python.org/)
[![Electron](https://img.shields.io/badge/UI-Electron-47848F)](https://www.electronjs.org/)

</div>

---

## Inhalt

- [Warum Murmel?](#warum-murmel)
- [Funktionen](#funktionen)
- [Screenshots](#screenshots)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Bedienung](#bedienung)
- [Konfiguration](#konfiguration)
- [Datenschutz](#datenschutz)
- [Technik und Aufbau](#technik-und-aufbau)
- [Entwicklung und Tests](#entwicklung-und-tests)
- [Fehlerbehebung](#fehlerbehebung)
- [Mitwirken](#mitwirken)
- [Lizenz](#lizenz)
- [Danksagung](#danksagung)

---

## Warum Murmel?

Wispr Flow zeigt, wie gut Diktieren mit KI sein kann – ist aber ein kostenpflichtiges Cloud-Produkt.
Murmel bietet einen ähnlichen Workflow **ohne Abo und ohne Cloud**:

- **Kostenlos** – keine Konten bei Drittanbietern, keine Abos, keine Limits.
- **Lokal** – die Spracherkennung läuft auf deinem Rechner. Deine Stimme verlässt deinen PC nicht.
- **Schnell** – [faster-whisper](https://github.com/SYSTRAN/faster-whisper) hält das Modell auf der NVIDIA-GPU (CUDA) warm; ein kurzer Satz ist meist nach etwa einer Sekunde eingefügt.
- **Überall einsetzbar** – Murmel schreibt in das Fenster, das gerade aktiv ist: Browser, Mail, Editor, Chat, Textverarbeitung.

> Murmel ist ein unabhängiges Open-Source-Projekt und steht in keiner Verbindung zu Wispr Flow.

## Funktionen

| | |
|---|---|
| 🎙️ **Diktieren per Taste** | Diktier-Taste (Standard: *Caps Lock*) halten, sprechen, loslassen. |
| 🙌 **Freihand-Modus** | Taste kurz antippen, um dauerhaft aufzunehmen – erneut tippen beendet die Aufnahme. |
| 🧠 **Lokale Spracherkennung** | Whisper-Modelle über faster-whisper, GPU-beschleunigt mit CPU-Fallback. |
| ✨ **Automatische Bereinigung** | Füllwörter („äh", „ähm") werden automatisch aus dem Text entfernt. |
| 🗣️ **Sprachbefehle** | „neue Zeile" und „neuer Absatz" werden als Formatierung umgesetzt. |
| 📚 **Wörterbuch** | Eigene Namen, Fachbegriffe und Korrekturen – einmal im Verlauf korrigieren, Murmel lernt es. |
| ⚡ **Snippets** | Kurze Kürzel, die zu ganzen Textbausteinen expandieren. |
| 🎨 **Stil pro App** | Unterschiedliche Tonalität für private Chats, Arbeits-Chats und E-Mails. |
| 🤖 **Optionaler KI-Feinschliff** | Anbindung an einen lokalen [LM Studio](https://lmstudio.ai/)-Server zum Umformulieren. Standardmäßig aus. |
| 📊 **Insights** | Wörter pro Minute, diktierte Wörter, Streaks, Zeitersparnis und Nutzung nach App. |
| 👤 **Mehrere Accounts** | Verlauf, Wörterbuch, Snippets und Statistiken sind pro Account getrennt (Passwörter per scrypt gehasht). |
| 🔈 **Audio-Ducking** | Systemlautstärke wird während des Diktierens automatisch abgesenkt. |
| 🏝️ **Island-Overlay** | Dezentes Status-Overlay zeigt Aufnahme, Verarbeitung und Ergebnis an. |

## Screenshots

<table>
  <tr>
    <td><img src="docs/screenshots/account.png" alt="Account erstellen" width="100%"></td>
    <td><img src="docs/screenshots/insights-nutzung.png" alt="Insights – Deine Nutzung" width="100%"></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/woerterbuch.png" alt="Wörterbuch" width="100%"></td>
    <td><img src="docs/screenshots/island-zustaende.png" alt="Island-Overlay Zustände" width="100%"></td>
  </tr>
</table>

---

## Voraussetzungen

| Komponente | Anforderung |
|---|---|
| Betriebssystem | **Windows 10 oder 11** (64 Bit). Murmel nutzt Windows-spezifische Schnittstellen (Hotkeys, Audio-Ducking, Fensterfokus) und läuft daher nicht unter macOS oder Linux. |
| Python | **3.12** (von [python.org](https://www.python.org/downloads/) oder den Python-Manager `py`) |
| Node.js | **LTS**, inkl. `npm` – von [nodejs.org](https://nodejs.org/) |
| Mikrofon | Beliebiges Eingabegerät |
| GPU (empfohlen) | NVIDIA-Grafikkarte mit aktuellem Treiber für CUDA 12 (z. B. GTX 16xx oder neuer). Ohne GPU läuft Murmel auf der CPU mit einem kleineren Modell – spürbar langsamer, aber voll funktionsfähig. |
| Speicher | Mehrere GB für Abhängigkeiten (inkl. CUDA-Bibliotheken), zzgl. des Whisper-Modells (large-v3-turbo: ca. 1,6 GB) |

## Installation

### 1. Repository klonen

```bash
git clone https://github.com/Voidlesh/Murmel.git
cd Murmel
```

Alternativ auf GitHub unter **Code → Download ZIP** herunterladen und entpacken.

### 2. Python-Umgebung einrichten

Im Projektordner in **PowerShell** ausführen:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> Die Pakete `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` und `nvidia-cuda-nvrtc-cu12` liefern die CUDA-Bibliotheken für die GPU-Beschleunigung. Ohne NVIDIA-GPU kannst du sie weglassen; Murmel fällt dann automatisch auf die CPU zurück.

### 3. Electron-Oberfläche installieren

```powershell
cd app
npm install
cd ..
```

### 4. Verknüpfungen anlegen (optional, empfohlen)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
```

Das legt eine Verknüpfung **Murmel** auf dem Desktop und im Startmenü an.

### 5. Starten

- Doppelklick auf **Murmel** (Desktop / Startmenü) oder auf `Murmel.vbs` im Projektordner.
- Beim **ersten Start** legst du einen Account an. Danach lädt Murmel das Whisper-Modell herunter (einmalig, ca. 1,6 GB). Der Status oben rechts zeigt „Bereit · CUDA“ bzw. „Bereit · CPU“, sobald es losgehen kann.

> **Tipp:** Wenn Murmel per `Murmel.vbs` startet, erscheint kein Konsolenfenster. Logs findest du unter `%APPDATA%\Murmel\engine.log`.

---

## Bedienung

| Aktion | Wie |
|---|---|
| Diktieren | Diktier-Taste (Standard: **Caps Lock**) gedrückt halten, sprechen, loslassen |
| Freihand-Diktat | Taste kurz antippen, zum Beenden erneut antippen (oder ■ im Island-Overlay klicken) |
| Abbrechen | `Esc` oder ✕ im Island-Overlay |
| Neue Zeile | Sag „neue Zeile“ |
| Neuer Absatz | Sag „neuer Absatz“ |
| Korrektur lernen | Eintrag im Verlauf bearbeiten – die Korrektur landet automatisch im Wörterbuch |
| Einstellungen | Zahnrad-Symbol bzw. Menüpunkt **Einstellungen** im Dashboard |

> **Hinweis:** Wispr Flow und Murmel sollten nicht gleichzeitig dieselbe Diktier-Taste verwenden.

---

## Konfiguration

Alle Einstellungen sind über das Dashboard änderbar und werden pro Account in `settings.json` gespeichert. Wichtige Optionen:

| Option | Standard | Bedeutung |
|---|---|---|
| `hotkey` | `caps lock` | Diktier-Taste (beliebige Taste, die von der Bibliothek [`keyboard`](https://github.com/boppreh/keyboard) erkannt wird) |
| `language` | `de` | Sprache der Spracherkennung |
| `model` | `large-v3-turbo` | Whisper-Modell (`tiny` bis `large-v3`); kleinere Modelle sind schneller, aber ungenauer |
| `device` | `auto` | `auto`, `cuda` oder `cpu` |
| `remove_fillers` | `true` | Füllwörter automatisch entfernen |
| `duck_audio` | `true` | Systemlautstärke beim Diktieren absenken |
| `llm.enabled` | `false` | KI-Feinschliff über einen lokalen LM-Studio-Server aktivieren |
| `llm.base_url` | `http://localhost:1234/v1` | Adresse des lokalen LM-Studio-Servers |

Die Felder `style` und `style_apps` legen fest, welcher Stil (`casual` oder `formal`) in welchen Anwendungen verwendet wird.

### Optionaler KI-Feinschliff (LM Studio)

1. [LM Studio](https://lmstudio.ai/) installieren und ein Modell laden.
2. Den lokalen Server in LM Studio starten (Standardport `1234`).
3. In Murmel unter den Einstellungen den KI-Feinschliff aktivieren.

Der Feinschliff läuft komplett lokal und nur, wenn er aktiviert ist.

---

## Datenschutz

- **Audio und Text bleiben auf deinem PC.** Die Spracherkennung läuft lokal mit faster-whisper.
- **Accounts sind lokal.** Passwörter werden mit scrypt gehasht; es gibt kein Cloud-Konto.
- **Daten liegen unter** `%APPDATA%\Murmel\accounts\<id>\` (`settings.json`, `murmel.db`, `audio/`). Du kannst den Ordner jederzeit löschen oder sichern.
- **Netzwerkzugriffe** erfolgen nur in zwei Fällen: der einmalige Download des Whisper-Modells von Hugging Face sowie – falls aktiviert – die Anfragen an deinen lokalen LM-Studio-Server.

## Technik und Aufbau

Murmel besteht aus zwei Teilen, die über einen lokalen WebSocket miteinander sprechen:

```
Murmel/
├── engine/     Python-Backend: Hotkey, Aufnahme, Whisper, Text-Pipeline,
│               SQLite-Speicher, Accounts, WebSocket-API (127.0.0.1:47821)
├── app/        Electron-Oberfläche: Dashboard (renderer/index.html)
│               und Island-Overlay (renderer/overlay.html)
├── tests/      pytest-Unit-Tests und End-to-End-Skripte gegen eine laufende Engine
├── scripts/    Hilfsskripte (Verknüpfungen, Benchmarks)
├── docs/       Screenshots
└── Murmel.vbs  Startskript ohne Konsolenfenster
```

**Ablauf eines Diktats:** Hotkey → Aufnahme (`sounddevice`) → Transkription (faster-whisper, GPU) → Text-Pipeline (Füllwörter, Wörterbuch, Snippets, Sprachbefehle, optional LM Studio) → Einfügen in das aktive Fenster (Zwischenablage wird danach wiederhergestellt).

Die Engine startet die Electron-Oberfläche nicht selbst – umgekehrt: Electron startet beim Öffnen die Engine, sofern sie nicht schon läuft.

## Entwicklung und Tests

```powershell
# Unit-Tests
.venv\Scripts\python.exe -m pytest tests

# Engine mit Testdaten starten (Daten landen in einem Temp-Ordner)
$env:MURMEL_DATA_DIR="$env:TEMP\murmel-test"
.venv\Scripts\python.exe -m engine

# Oberfläche direkt auf einer bestimmten Seite öffnen
cd app
npx electron . --page=insights --tab=voice
```

`pytest` wird für die Entwicklung zusätzlich benötigt: `.venv\Scripts\python.exe -m pip install pytest`.

Die End-to-End-Skripte in `tests/` (`e2e_engine.py`, `e2e_hotkey.py`) setzen eine laufende Engine voraus.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| Murmel startet nicht, Meldung „Python-Umgebung fehlt“ | Schritt 2 der Installation wiederholen; `.venv` muss im Projektordner liegen. |
| Keine GPU-Beschleunigung („Bereit · CPU“) | NVIDIA-Treiber aktualisieren und die `nvidia-*`-Pakete aus `requirements.txt` installieren. |
| Diktier-Taste reagiert nicht | Prüfen, ob eine andere Anwendung dieselbe Taste belegt (z. B. Wispr Flow). |
| Verknüpfung fehlt nach dem Verschieben des Ordners | `scripts\install_shortcut.ps1` erneut ausführen. |
| Fehler in der Spracherkennung | `%APPDATA%\Murmel\engine.log` öffnen und den Eintrag in einem Issue beilegen. |

Weitere Fragen gerne als [Issue](https://github.com/Voidlesh/Murmel/issues) stellen.

## Mitwirken

Beiträge sind willkommen – Fehlerberichte, Verbesserungsvorschläge und Pull Requests. Details stehen in [CONTRIBUTING.md](CONTRIBUTING.md).

## Lizenz

Murmel steht unter der [MIT-Lizenz](LICENSE). Du darfst es kostenlos nutzen, verändern und weitergeben – auch kommerziell. Die Lizenz enthält keine Gewährleistung.

## Danksagung

Murmel baut auf großartigen Open-Source-Projekten auf:

- [OpenAI Whisper](https://github.com/openai/whisper) und [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (SYSTRAN) – Spracherkennung
- [CTranslate2](https://github.com/OpenNMT/CTranslate2) – Inferenz-Engine
- [Electron](https://www.electronjs.org/) – Desktop-Oberfläche
- [websockets](https://github.com/python-websockets/websockets), [sounddevice](https://github.com/spatialaudio/python-sounddevice), [keyboard](https://github.com/boppreh/keyboard), [pycaw](https://github.com/AndreMiras/pycaw)
- [Fontsource](https://fontsource.org/) (Figtree, EB Garamond) und [Lucide](https://lucide.dev/) (Icons)
- Hintergrundfotos von [Unsplash](https://unsplash.com/license)

Die Idee des diktierbasierten Workflows stammt von [Wispr Flow](https://wisprflow.ai/).
