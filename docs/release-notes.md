## Murmel 1.1.0: Notizen für Vorlesungen und Calls

Die Notizen-Aufnahme ist jetzt für lange Online-Vorlesungen gebaut: zuverlässig, mit sauberem Transkript und Export.

### Neu
- **Startdialog:** Titel, Quelle, Sprache und Fachbegriffe pro Sitzung. Die Fachbegriffe verbessern die Schreibweise im Transkript.
- **Nur Desktop-Audio:** Für Online-Vorlesungen und Streams. Das Mikrofon bleibt aus.
- **Live-Ansicht:** Aufnahmedauer, Pegel für Desktop und Mikrofon und wie weit das Transkript hinter Live liegt.
- **Export:** Als Markdown mit Zeitmarken und Sprechern, als reiner Text oder per „Alles kopieren“.
- **Transkript neu erzeugen** aus der gespeicherten Audiodatei, zum Beispiel mit ergänzten Fachbegriffen.
- **Aufnahme importieren:** Audio- oder Videodateien (etwa aus OBS) werden zu einer Sitzung mit Transkript.
- **Umbenennen** einer Sitzung per Klick auf den Titel.

### Zuverlässiger
- Desktop-Audio, Mikrofon und eine Mischspur werden als eigene WAV-Dateien gespeichert. Nach einem Absturz bleiben sie abspielbar.
- Wechselt das Wiedergabegerät oder fällt ein Stream aus, verbindet Murmel automatisch neu und vermerkt das im Transkript.
- Eine Warnung erscheint, wenn das Desktop-Audio länger als 20 Sekunden stumm ist.
- Während einer Sitzung geht der PC nicht in den Standby.
- Whisper-Halluzinationen wie „Untertitel im Auftrag des ZDF“ und Wiederholungsschleifen werden herausgefiltert.
- Ohne Sprechpause wird an der leisesten Stelle geschnitten statt hart nach 30 Sekunden.
- Abgebrochene Sitzungen heißen „Unterbrochen“ und behalten ihr Transkript.
- Eine Warnung erscheint, wenn die Grafikkarte nicht nutzbar ist und Murmel auf das CPU-Modell ausweicht.

Die KI-Zusammenfassung ist vorerst ausgeblendet.

### Installation
`Murmel-Setup-1.1.0.exe` herunterladen und starten. Bestehende Accounts, Verläufe und Einstellungen bleiben erhalten. Der Installer ist nicht signiert: Windows-Warnung mit *Weitere Informationen → Trotzdem ausführen* bestätigen.
