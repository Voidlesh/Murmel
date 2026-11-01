# Notizen-Feature (Meeting-Aufnahme, Transkript, Zusammenfassung)

Status: Entwurf, nach Prüfung gegen den Engine-Code überarbeitet. Die Anforderungen stammen aus dem beobachteten Verhalten von Wispr Flow (Feature-Umfang, Ablauf, Datenmodell). Der Code wird eigenständig geschrieben; Texte, Prompts und Assets der Vorlage werden nicht übernommen.

## Ziel

Neben dem Diktat per Taste eine **Sitzungsaufnahme**: Murmel nimmt ein Gespräch oder eine Vorlesung durchgehend auf, transkribiert es lokal und bietet danach Transkript, Zusammenfassung und eigene Notizen.

## Funktionsumfang (v1)

| Bereich | Verhalten |
|---|---|
| Sitzung starten/stoppen | Über Dashboard-Button und eigenen Hotkey. Während einer Sitzung ist der Diktier-Hotkey gesperrt. |
| Transkript | Segmente mit Zeitangabe, erscheinen während der Aufnahme. Suche innerhalb der Sitzung. |
| Zusammenfassung | Nach dem Stoppen: Kurzfassung und Aufgabenliste. Über den lokalen LM-Studio-Server. Ohne aktiviertes LLM bleibt das Transkript. |
| Eigene Notizen | Freitext pro Sitzung, während und nach der Aufnahme bearbeitbar. |
| Sitzungsliste | Titel (Standard: Datum und Uhrzeit), Dauer, Wortanzahl, Status. |

Nicht in v1: Sprechererkennung, Systemaudio (Gegenseite bei Videocalls), Kalender-Anbindung, Export.

## Ablauf

1. **Start:** Die Engine prüft, dass ein Account angemeldet ist (wie bei `start_recording`), und legt eine Sitzung mit `status = recording` an. Der Diktier-Hotkey wird für die Dauer der Sitzung abgeschaltet.
2. **Aufnahme:** Der Recorder liefert Audio in Abschnitten. Ein Abschnitt endet bei einer Pause (Stille) oder spätestens nach 30 Sekunden, damit kein Wort zerschnitten wird. Jeder Abschnitt wird über das bestehende `Transcriber.transcribe` transkribiert und als Segment gespeichert. Die Zeitangabe `start_s`/`end_s` kommt aus dem Offset des Abschnitts, nicht von Whisper, weil `transcribe` mit `without_timestamps=True` läuft.
3. **Ende:** Die Engine schreibt die Endzeit, setzt `status = processing` und startet die Zusammenfassung im Hintergrund. Danach `status = done`, bei Fehlern `status = error` mit Meldung im Log.

## Abgrenzung zur Diktat-Pipeline

Sitzungen nutzen die Diktat-Pipeline nur teilweise:

- **Kein Einfügen** in die aktive App. Das passiert nur bei Diktaten (`_transcribe_and_paste`); Sitzungen rufen diesen Pfad nicht auf.
- **Kein KI-Feinschliff pro Segment.** `pipeline.process` würde das LLM für jedes Segment aufrufen, und der Polish-Prompt verbietet Zusammenfassungen. Sitzungen nutzen nur Füllwort-Entfernung und Wörterbuch-Korrekturen.
- **Keine Snippets und keine Sprachbefehle** im Sitzungstext. Ein Kürzel-Expansion oder „neue Zeile“ in einem Gespräch wäre unerwünscht.
- **Nicht in der Diktat-Statistik.** Insights lesen die Tabelle `transcripts`; Sitzungen liegen in eigenen Tabellen und fließen nicht in Wörter oder Streaks ein.

## Änderungen am Recorder

`Recorder` (`engine/audio.py`) sammelt heute alle Blöcke bis `stop()`. Für Sitzungen braucht er einen Weg, Abschnitte während der Aufnahme abzuholen, etwa `drain()` unter dem bestehenden Lock. Bei einer Stunde Aufnahme sind das rund 230 MB Float32 im Speicher, deshalb sollten bereits verarbeitete Abschnitte verworfen werden.

## Datenmodell (SQLite)

Neue Tabellen gehören in `SCHEMA` in `engine/store.py` (`CREATE TABLE IF NOT EXISTS`). Die Liste `MIGRATIONS` ist nur für `ALTER TABLE ... ADD COLUMN` auf bestehenden Tabellen gedacht.

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    started_at REAL NOT NULL,
    ended_at REAL,
    status TEXT NOT NULL DEFAULT 'recording',  -- recording | processing | done | error
    notes TEXT NOT NULL DEFAULT '',            -- eigene Notizen (Markdown)
    summary TEXT,                              -- Zusammenfassung (Markdown), NULL bis erzeugt
    action_items TEXT,                         -- JSON-Liste, NULL bis erzeugt
    language TEXT NOT NULL DEFAULT '',
    audio_path TEXT                            -- nur gesetzt, wenn Audio behalten wird
);
CREATE TABLE IF NOT EXISTS session_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_session ON session_segments(session_id, start_s);
```

Hinweise:
- `ON DELETE CASCADE` wirkt nur mit `PRAGMA foreign_keys = ON`, und das ist im Store nicht gesetzt. Deshalb löscht die Methode `delete_session` die Segmente explizit.
- Die Tabelle `transcripts` wird nicht verändert.

## Audio

Die Spec ging vorher fälschlich davon aus, dass kein Audio gespeichert wird. Tatsächlich gilt für Diktate `keep_audio: True` mit einem Limit von 200 Dateien (`KEEP_AUDIO_FILES`, `_prune_audio`). Für Sitzungen gilt:

- Eigene Einstellung `session_keep_audio`, Standard `True`. Eine Stunde als WAV wären rund 115 MB.
- `_prune_audio` darf Sitzungsdateien nicht zählen oder löschen. Sitzungs-Audio hat eine eigene Obergrenze von 50 Sitzungen (Vorschlag, anpassbar). Die älteste Audiodatei wird zuerst gelöscht.

## Schnittstellen

- **WebSocket-API** (`engine/server.py`): Der Dispatcher ruft `api_<methode>` auf. Die Methoden heißen daher `api_session_start`, `api_session_stop`, `api_session_list`, `api_session_get`, `api_session_update_notes`, `api_session_delete`.
- **Push-Nachrichten** über `broadcast({"type": ...})`: `session_segment` während der Aufnahme, `session_status` bei Statuswechseln. Der bestehende Zustand `state` wird für Sitzungen nicht geändert.
- **Modul `engine/sessions.py`:** Aufnahmeschleife, Abschnitte und Zusammenfassung. Hält keinen Zustand außerhalb des Stores.
- **LLM:** `engine/llm.py` enthält nur `polish` und `check`. Die Zusammenfassung braucht eine neue Funktion `summarize_session` mit eigenem Prompt. Die Hilfsfunktionen `_post` und `list_models` werden wiederverwendet.
- **Dashboard:** `app/renderer/js/pages/notes.js`. Liste links, Detail rechts mit Tabs „Transkript“, „Zusammenfassung“, „Notizen“.

## Zusammenfassung bei langen Aufnahmen

Eine Stunde Transkript umfasst grob 8.000 bis 10.000 Wörter und passt nicht in jeden lokalen Kontext. Die Zusammenfassung arbeitet deshalb in zwei Stufen: Erst wird jeder Block von rund 2.000 Wörtern zusammengefasst, dann werden die Teilzusammenfassungen zu einer Endfassung verdichtet. Die Blockgröße ist eine Konstante, die vor der Umsetzung am echten Modell geprüft wird.

## Hotkey

Die Engine hat nur einen Hotkey (`hotkey` in `hotkey.py`, mit Tippen für Freihand). Ein zweiter Hotkey braucht eine Erweiterung dieser Klasse.

**Entschieden:** Der Sitzungs-Hotkey ist frei wählbar und hat ein eigenes Setting `session_hotkey`. Der Standard ist leer, damit kein Konflikt entsteht. Die Eingabe erfolgt wie beim Diktier-Hotkey im Dashboard.

**Warnung:** `Strg+Umschalt+M` ist in Microsoft Teams die Stummschalt-Taste. Teams ist in den Standardeinstellungen als Arbeits-App hinterlegt (`ms-teams.exe`), der Konflikt ist also wahrscheinlich.

## Entschieden

1. **Sitzungs-Hotkey:** frei wählbar, Setting `session_hotkey`, Standard leer (siehe Abschnitt Hotkey).
2. **Abschnitte:** Schnitt bei Stille, harte Grenze nach 30 s. Die Stille-Schwelle aus `audio.py` wird wiederverwendet.
3. **Ohne LLM:** nur Transkript und eigene Notizen. Keine Aufgabenerkennung per Regeln.
4. **Audio:** Sitzungs-Audio wird gespeichert, mit eigener Obergrenze von 50 Sitzungen.

Die Obergrenze von 50 ist ein Vorschlag von mir, du hast sie nicht bestätigt.
