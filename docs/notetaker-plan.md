# Plan: Notetaker für die Online-Vorlesung

Stand: 12.11.2026. Ziel für morgen: eine Online-Vorlesung (Zoom, Teams oder Stream) ohne Fehler aufnehmen, sauber transkribieren und als Markdown oder Text weiterverarbeiten. Die Zusammenfassung kommt später.

## Ausgangslage (aus dem Code)

Murmel hat schon eine Sitzungsaufnahme (`engine/server.py`, `engine/sessions.py`, `app/renderer/js/pages/notes.js`):

- Das Mikrofon läuft als „Du“, das Systemaudio über WASAPI-Loopback als „Gegenüber“.
- Das Audio wird an Pausen geschnitten, höchstens alle 30 s, und jeder Abschnitt einzeln mit `large-v3-turbo` auf der GPU transkribiert.
- Die Segmente landen sofort in SQLite, bei einem Absturz bleibt der bisherige Text also erhalten.
- Die Seite „Notizen“ hat eine Liste, die Tabs Transkript, Zusammenfassung und Notizen sowie ein optionales Live-Fenster.

Für morgen ist also kein Neubau nötig. Es geht darum, den Teil zu härten, der bei einer Online-Vorlesung zählt, also die Desktop-Spur.

## Deine Rahmenbedingungen (Interview)

| Frage | Antwort | Folge |
|---|---|---|
| Art der Vorlesung | Online | Die Systemaudio-Spur ist der Hauptinhalt. |
| Rechner | Desktop-PC mit NVIDIA (das Modell GTX 1660 Super stammt aus einem Code-Kommentar und ist nicht bestätigt) | Das große Modell läuft in Echtzeit. Kein Akku-Thema, aber der Standby kann zuschlagen. |
| Hören | Kopfhörer oder Headset | Kein Echo, deshalb kein Echo-Filter nötig. |
| Zusammenfassung | Erstmal keine | Sie wird morgen ausgeblendet, der Code bleibt. |
| Export | Markdown, Kopieren, .txt | Neue Funktion, gibt es heute noch nicht. |
| Update-Weg | Installer (.exe) | Er wird per GitHub Actions auf Windows gebaut, nicht in diesem Linux-Container. |
| Design | Vier Entwürfe noch heute | Die Entwürfe laufen parallel zur Stabilität, die Stabilität geht aber vor. |

## Blindspot-Pass

Format pro Punkt: **Was ist es**, **warum würde es dich erwischen**, **Satz für deinen Auftrag**.

### A. Aufnahme (kritisch für morgen)

1. **Die Desktop-Spur wird nicht gespeichert.**
   *Was:* `_session_feed` schreibt nur das Mikrofon in die WAV-Datei.
   *Warum:* Bei einer Online-Vorlesung ist die Audiodatei dann fast stumm, nur du bist zu hören. Ein schlechtes Transkript lässt sich damit nicht neu erzeugen.
   *Satz:* „Speichere die Desktop-Spur als eigene WAV-Datei und zusätzlich als Mischspur, damit ich das Transkript jederzeit neu erzeugen kann.“

2. **Der Loopback hängt am Standard-Ausgabegerät, das beim Start gilt.**
   *Was:* `get_default_wasapi_loopback()` wird einmal beim Start der Sitzung aufgerufen.
   *Warum:* Wenn Zoom oder Teams auf ein anderes Gerät ausgeben als der Windows-Standard, oder du das Headset erst nach dem Start einsteckst, nimmt Murmel Stille auf. Fehler zeigt es dabei nicht an.
   *Satz:* „Erkenne, wenn die Desktop-Spur länger als 20 s stumm ist, obwohl die Sitzung läuft. Zeig dann eine deutliche Warnung mit dem aktuell aufgenommenen Gerät, und verbinde den Loopback neu, wenn sich das Standardgerät ändert.“

3. **Bluetooth-Headsets wechseln das Profil.**
   *Was:* Sobald eine App das Headset-Mikro öffnet, schaltet Windows von A2DP (Stereo) auf das Freisprechprofil um. Dabei entsteht ein neues Ausgabegerät mit schlechtem Klang.
   *Warum:* Das Standardgerät wechselt mitten in der Aufnahme. Das ist Fall 2, nur ausgelöst durch Murmel selbst.
   *Satz:* „Biete den Modus ‚Nur Desktop-Audio‘ an, der das Mikro gar nicht öffnet, und mach ihn zum Vorschlag für Vorlesungen.“

3a. **Heute hängt die Sitzung am Mikro, und die Desktop-Spur ist nur optional.**
   *Was:* Kann das Mikro nicht starten, bricht die ganze Sitzung ab (`api_session_start`). Fällt dagegen der Loopback aus, läuft die Sitzung mit einer kleinen Meldung nur mit dem Mikro weiter (`_start_session_streams`).
   *Warum:* Bei einer Online-Vorlesung ist es genau umgekehrt richtig. Ohne Desktop-Spur ist die Aufnahme wertlos, ohne Mikro ist sie in Ordnung.
   *Satz:* „Im Modus ‚Nur Desktop-Audio‘ darf das Mikro nicht nötig sein. Wenn die Desktop-Spur nicht startet, muss die Sitzung laut fehlschlagen, statt still mit dem Mikro weiterzulaufen.“

4. **Ausfälle von Gerät oder Stream werden nicht erkannt.**
   *Was:* Beim Mikro landet der Status nur im Debug-Log. Beim Loopback wird er gar nicht ausgewertet (`LoopbackStream._on_audio`).
   *Warum:* Ein abgezogenes USB-Headset oder ein gestoppter Stream sieht aus wie Stille. Die Sitzung „läuft“ dann weiter und liefert nichts.
   *Satz:* „Überwache beide Streams. Starte einen Stream neu, wenn er einen echten Fehler meldet oder das Gerät verschwindet, und vermerke die Lücke als Hinweis im Transkript.“

4a. **WASAPI-Loopback liefert keine Samples, solange nichts abgespielt wird.**
   *Was:* Pausiert der Stream, kommen keine Daten, auch keine Stille. Der Segmenter zählt Samples statt Uhrzeit.
   *Warum:* Die Zeitmarken der Desktop-Spur verrutschen nach jeder Pause nach vorn, und Mischspur und Mikro laufen auseinander. Ein Watchdog, der auf fehlende Samples achtet, würde bei jeder Pause anschlagen.
   *Satz:* „Fülle Lücken im Loopback anhand der Uhrzeit mit Stille, damit Zeitmarken und Mischspur synchron bleiben. Als Ausfall zählt nur ein echter Stream-Fehler.“

5. **Der PC geht in den Standby.**
   *Was:* Bei einer Online-Vorlesung fasst du Maus und Tastatur oft lange nicht an. Electron blockiert den Standby nicht.
   *Warum:* Nach 30 bis 60 Minuten schläft der PC ein, und die Aufnahme bricht ab.
   *Satz:* „Verhindere Standby und Bildschirm-Sperre, solange eine Sitzung läuft (`powerSaveBlocker`).“

6. **Live-Pegel für die Desktop-Spur fehlen.**
   *Was:* Die Pegelbalken folgen nur dem Mikro (`if not self._loopback`).
   *Warum:* Du siehst nicht, ob der Prof gerade aufgenommen wird.
   *Satz:* „Zeig in der laufenden Sitzung je einen Pegel für Mikro und Desktop, damit ich auf einen Blick sehe, dass beide ankommen.“

### B. Transkript-Qualität

7. **Whisper erfindet Text bei Stille oder Musik.**
   *Was:* Bekannte deutsche Halluzinationen wie „Untertitel im Auftrag des ZDF“, „Vielen Dank fürs Zuschauen“ oder Wiederholungsschleifen.
   *Warum:* Wartezeit vor der Vorlesung, Pausen und Intro-Musik füllen dein Transkript mit Unsinn.
   *Stand:* `vad_filter=True` und `condition_on_previous_text=False` sind schon aktiv. Das hilft, reicht aber bei Musik und Applaus nicht.
   *Satz:* „Verwirf zusätzlich Segmente mit hohem `no_speech_prob` oder niedriger Konfidenz, filtere eine Liste bekannter Whisper-Halluzinationen und kürze Wiederholungsschleifen.“

8. **Der harte Schnitt nach 30 s trennt Wörter.**
   *Was:* Ohne Pause von 0,6 s schneidet der Segmenter exakt bei 30 s.
   *Warum:* Profs sprechen oft ohne Pausen. Am Schnitt fehlen dann Wörter oder sie sind verdoppelt.
   *Satz:* „Schneide bei fehlender Pause an der leisesten Stelle der letzten Sekunden statt hart bei 30 s.“

9. **Keine Fachbegriffe, keine Wahl der Sprache pro Sitzung.**
   *Was:* Die Sprache ist global auf „de“ gesetzt. Fachbegriffe kommen nur aus dem globalen Wörterbuch.
   *Warum:* Englische Vorlesungen oder Fachvokabular wie „Eigenwert“ oder „Lagrange“ werden falsch geschrieben.
   *Satz:* „Lass mich vor dem Start Titel, Sprache und ein paar Fachbegriffe für die Sitzung eintragen.“

10. **Rückstau bei der Verarbeitung.**
    *Was:* Die Transkription läuft im selben Takt wie die Aufnahme. Ist sie langsamer, wächst die Verzögerung.
    *Warum:* Nach dem Stoppen wartet die App dann lange ohne erkennbaren Grund und wirkt eingefroren.
    *Satz:* „Zeig an, wie weit die Transkription hinter der Aufnahme liegt, und beim Stoppen einen Fortschritt ‚Wird abgeschlossen …‘.“

10a. **Murmel weicht still auf die CPU aus.**
    *Was:* Lädt CUDA nicht, nimmt Murmel ohne Warnung das Modell „small“ auf der CPU (`Transcriber._load`).
    *Warum:* Fehlt im neuen Installer eine CUDA-DLL, wird das Transkript deutlich schlechter, und du merkst es erst danach.
    *Satz:* „Zeig in der Sitzung gut sichtbar Gerät und Modell an. Warne laut, wenn Murmel auf die CPU ausweicht, und prüfe in der CI, dass das Bundle die CUDA-DLLs enthält.“

10b. **Die Umrechnung von 48 kHz verfälscht den Klang.**
    *Was:* `_resample` interpoliert linear und filtert vorher nicht. Hohe Frequenzen spiegeln sich dadurch in den Sprachbereich (Aliasing).
    *Warum:* Das verursacht leichte Erkennungsfehler, besonders bei Musik oder Zischlauten.
    *Satz:* „Nimm für den Loopback einen Resampler mit Tiefpass.“ (niedrige Priorität)

### C. Absturz und Daten

11. **Die WAV-Datei ist nach einem Absturz kaputt.**
    *Was:* Die Dateilänge im WAV-Header wird erst beim Schließen geschrieben.
    *Warum:* Nach einem Absturz oder Stromausfall lässt sich die Datei nicht öffnen.
    *Satz:* „Aktualisiere den WAV-Header regelmäßig und repariere unterbrochene Dateien beim nächsten Start.“

12. **Eine unterbrochene Sitzung heißt „Fehler“.**
    *Was:* `mark_interrupted_sessions` setzt `status='error'`.
    *Warum:* Das Transkript ist eigentlich vollständig bis zum Abbruch, wirkt aber kaputt.
    *Satz:* „Markiere abgebrochene Sitzungen als ‚Unterbrochen‘, behalte alles, und lass mich das Transkript aus der Audiodatei neu erzeugen.“

### D. Weiterverarbeitung

13. **Es gibt keinen Export.**
    *Was:* Eine Sitzung lässt sich heute nur in der App ansehen. Es gibt weder Datei noch Zwischenablage.
    *Warum:* Dein eigentliches Ziel ist, den Text in Claude, Notion oder Lernzettel zu übernehmen. Ohne Export markierst du 90 Minuten von Hand.
    *Satz:* „Exportiere eine Sitzung als Markdown (Titel, Datum, Dauer, `[mm:ss]` und Sprecher, Absätze zusammengefasst) und als reinen Text, und biete ‚Alles kopieren‘ an.“

14. **Die Zusammenfassung erzeugt Fehlerstatus.**
    *Was:* Ist das LLM aus, zeigt der Tab nur einen Hinweis. Ist LM Studio an, aber nicht erreichbar, setzt `_run_summary` die ganze Sitzung auf `status='error'`.
    *Warum:* Eine vollständige Vorlesung erscheint dann in der Liste als „Fehler“, nur weil die Zusammenfassung nicht geklappt hat.
    *Satz:* „Blende Zusammenfassung und Aufgaben vorerst aus. Ein LLM-Fehler darf eine Sitzung nie als fehlerhaft markieren.“

### E. Auslieferung und Test

15. **Den Installer kann ich hier nicht bauen.**
    *Was:* PyInstaller und NSIS brauchen Windows. Das Repo hat keine CI.
    *Warum:* Ohne neuen Installer läuft morgen die alte Version.
    *Satz:* „Richte einen GitHub-Actions-Workflow auf `windows-latest` ein, der Tests ausführt, Engine und Installer baut und die .exe als Download anhängt.“
    *Risiko:* Der erste Build mit den CUDA-Wheels (rund 1,3 GB) kann scheitern. Ich prüfe die Logs selbst und behebe Fehler. Wenn die Zeit nicht reicht, schreibe ich dir die Befehle für den lokalen Build auf.

16. **Ich kann kein echtes Windows-Audio testen.**
    *Was:* Hier gibt es weder WASAPI noch GPU. Ich teste mit Unit-Tests, simulierten Streams und der deutschen Test-WAV-Datei.
    *Warum:* Ob Zoom wirklich in der Desktop-Spur ankommt, siehst nur du auf deinem PC.
    *Satz:* „Gib mir eine Checkliste für einen 10-Minuten-Probelauf heute Abend mit einem YouTube-Vortrag.“

16a. **Das Sprachmodell wird beim ersten Start geladen.**
    *Was:* Nach der Neuinstallation lädt Murmel einmalig rund 1,6 GB herunter.
    *Warum:* Startest du erst kurz vor der Vorlesung, wartest du, statt aufzunehmen.
    *Satz:* (kein Code) Der Probelauf heute Abend lädt das Modell gleich mit.

16b. **Es gibt keinen Plan B.**
    *Was:* Morgen ist der erste echte Einsatz, und ein unbekannter Fehler ist möglich.
    *Warum:* Eine verpasste Vorlesung lässt sich nicht wiederholen.
    *Satz:* „Schreib mir eine 2-Minuten-Anleitung für eine zweite Aufnahme als Sicherung, zum Beispiel mit OBS. Ihre Audiodatei kann Murmel danach über ‚Transkript neu erzeugen‘ verarbeiten.“

17. **Mitschnitte können verboten sein.**
    *Was:* Viele Unis verbieten Mitschnitte. Das nicht-öffentlich gesprochene Wort ist durch § 201 StGB geschützt, und Folien und Vortrag sind urheberrechtlich geschützt.
    *Warum:* Das Risiko liegt bei dir, nicht bei der Software.
    *Satz:* (kein Code) Kläre kurz die Regeln deiner Uni oder frag die Lehrperson. Murmel speichert ohnehin nur lokal.

## Reihenfolge

**Phase 0: STOPP. Du gibst den Plan frei.**

**Phase 1: Stabilität für morgen (P0)**, in dieser Reihenfolge:
0. Windows-CI zuerst aufsetzen (Tests, Engine-Bundle mit CUDA-Prüfung, Installer). Sie ist das größte Zeitrisiko und läuft im Hintergrund, während ich weiterbaue (15, 10a).
1. Desktop-Spur und Mischspur speichern, WAV-Header crashfest, Loopback-Lücken mit Stille füllen (1, 11, 4a)
2. Modus „Nur Desktop-Audio“ ohne Mikro-Zwang. Eine fehlende Desktop-Spur führt zu einem lauten Fehler (3, 3a).
3. Watchdog für Stream-Fehler, stumme Desktop-Spur und Gerätewechsel mit Neuverbindung (2, 4)
4. Standby blockieren (5)
5. Halluzinations-Filter und weicher Schnitt (7, 8)
6. „Unterbrochen“ statt „Fehler“, Zusammenfassung ausblenden (12, 14)
7. „Transkript neu erzeugen“ aus der WAV-Datei, aufbauend auf `api_transcribe_wav`. Das ist das Sicherheitsnetz, auch für die Sicherungsaufnahme (12, 16b).
8. Export als Markdown und .txt, „Alles kopieren“ (13)
9. Gerät und Modell anzeigen, laute Warnung bei CPU-Fallback (10a)

**Phase 2: Bedienung (P1)**
10. Startdialog mit Titel, Sprache, Fachbegriffen und Quelle (9, 3)
11. Pegel für beide Spuren, Rückstau-Anzeige, Fortschritt beim Stoppen (6, 10)
12. Resampler mit Tiefpass (10b)

**Parallel zu Phase 1: vier Design-Entwürfe**
- Es entstehen vier klickbare HTML-Entwürfe für die Notizen-Seite und die laufende Sitzung, jeweils mit echtem Beispieltext.
- **STOPP:** Du wählst einen aus. Umgesetzt wird er erst, wenn Phase 1 grün ist. Reicht die Zeit bis morgen nicht, kommt er nach der Vorlesung.

**Phase 3: Auslieferung**
13. Letzter grüner CI-Build, die .exe als Download (15)
14. Unabhängiger Prüf-Agent gegen diese Anforderungen
15. Checkliste für deinen 10-Minuten-Probelauf heute Abend, mit Modell-Download, und die Anleitung für die Sicherungsaufnahme (16, 16a, 16b)

**Später:** KI-Zusammenfassung (Claude-API oder lokal, mit einem Format für Vorlesungen: Themen, Definitionen, Prüfungsrelevantes), .docx und .srt, Sprechererkennung.

## Verbesserter Auftrag (zum Kopieren)

> Baue den Notetaker in Murmel für meine Online-Vorlesung morgen zuverlässig aus. Die Vorlesung kommt über Desktop-Audio, ich höre mit Kopfhörern, der PC hat eine NVIDIA-GPU.
>
> **Zeig mir zuerst den Plan und halte an, bis ich ihn freigebe.**
>
> Reihenfolge: Zuerst die Windows-CI für den Installer, weil sie das größte Zeitrisiko ist. Dann Stabilität, dann Bedienung. Parallel machst du vier Design-Entwürfe für die Notizen-Seite. **Du hältst an, bis ich einen ausgewählt habe**, und setzt ihn erst um, wenn die Stabilität steht.
>
> Muss:
> - Speichere die Desktop-Spur als eigene WAV-Datei und als Mischspur, crashfest. Fülle Loopback-Lücken mit Stille, damit die Zeitmarken stimmen.
> - Biete den Modus „Nur Desktop-Audio“ ohne Mikro-Zwang an. Fehlt die Desktop-Spur, soll das laut fehlschlagen.
> - Erkenne Stream-Fehler, eine stumme Desktop-Spur und Gerätewechsel. Warne mich und verbinde automatisch neu.
> - Blockiere den Standby während einer Sitzung.
> - Filtere Whisper-Halluzinationen und schneide weich statt hart nach 30 s.
> - Markiere abgebrochene Sitzungen als „Unterbrochen“, nicht als „Fehler“. Ein LLM-Fehler darf nie eine Sitzung als fehlerhaft markieren. Blende die Zusammenfassung vorerst aus.
> - Biete „Transkript neu erzeugen“ aus einer WAV-Datei an.
> - Exportiere als Markdown mit Zeitmarken und Sprecher, als reinen Text und per „Alles kopieren“.
> - Zeig Gerät und Modell an und warne laut beim CPU-Fallback.
>
> Danach: Startdialog mit Titel, Sprache und Fachbegriffen, Pegel für beide Spuren, Rückstau-Anzeige.
>
> Alles mit Tests. Zum Schluss prüft ein unabhängiger Agent das Ergebnis gegen diese Liste. Ich bekomme eine Checkliste für einen 10-Minuten-Probelauf und eine Anleitung für eine Sicherungsaufnahme.
