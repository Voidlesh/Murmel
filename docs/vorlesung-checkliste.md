# Checkliste: Online-Vorlesung mit Murmel aufnehmen

## Heute Abend: Probelauf (10 Minuten)

1. **Installer holen:** Auf GitHub unter *Actions → Windows build* den neuesten grünen Lauf öffnen. Unten unter *Artifacts* die Datei **Murmel-Setup** herunterladen. Das ZIP entpacken und `Murmel-Setup-1.0.0.exe` starten. Windows warnt eventuell: *Weitere Informationen → Trotzdem ausführen*.
2. **Murmel starten und warten,** bis oben rechts „Bereit · CUDA“ steht. Beim ersten Start lädt Murmel das Sprachmodell (rund 1,6 GB). Steht dort „CPU“, die NVIDIA-Treiber aktualisieren, sonst wird das Transkript ungenauer.
3. **Kopfhörer anschließen,** dann ein deutsches Vortragsvideo auf YouTube starten und über die Kopfhörer hören.
4. **Notizen → Neue Sitzung:**
   - Titel: „Probelauf“
   - Quelle: **Nur Desktop-Audio**
   - Sprache: Deutsch
   - Fachbegriffe: zwei Begriffe aus dem Video
5. **Prüfen, während es läuft:**
   - Der Pegel „Desktop“ bewegt sich, wenn im Video gesprochen wird.
   - Nach einigen Sekunden erscheint Text als „Gegenüber“.
   - Unten steht „Transkript ist aktuell“ oder nur wenige Sekunden Verzug.
6. **Test für Gerätewechsel:** Das Video 30 Sekunden pausieren. Nach 20 Sekunden muss die Warnung „Desktop-Audio seit … s stumm“ erscheinen und verschwinden, sobald das Video weiterläuft.
7. **Aufnahme beenden,** dann **Markdown** speichern und **Alles kopieren** in einen Editor einfügen. Prüfen, ob Text und Zeitmarken stimmen.
8. **Ordner-Symbol** öffnen: Es sollte `session-<Nr>.wav` geben, die Datei lässt sich abspielen.

Wenn Schritt 5 keinen Pegel zeigt, ist meist das falsche Wiedergabegerät aktiv. In Windows unter *Einstellungen → System → Sound* die Kopfhörer als Ausgabe wählen. In Zoom oder Teams dieselbe Ausgabe einstellen wie in Windows („Gleich wie System“).

## Morgen vor der Vorlesung

- [ ] PC am Strom, Kopfhörer verbunden, **bevor** die Sitzung startet.
- [ ] Vorlesung (Zoom, Teams oder Stream) läuft schon, Ton ist hörbar.
- [ ] Sicherungsaufnahme starten (siehe unten).
- [ ] Murmel: Neue Sitzung → Titel, **Nur Desktop-Audio**, Fachbegriffe aus den Folien.
- [ ] Nach einer Minute kurz prüfen: Desktop-Pegel bewegt sich, erster Text steht da.
- [ ] Den PC laufen lassen. Murmel verhindert den Standby, solange die Sitzung läuft.

## Nach der Vorlesung

1. Aufnahme beenden und warten, bis „Wird abgeschlossen …“ verschwindet.
2. **Markdown** oder **Text** speichern, oder **Alles kopieren** und direkt in Claude, ChatGPT oder Notion einfügen.
3. Ist das Transkript schlecht (falsche Begriffe, falsche Sprache), die Fachbegriffe ergänzen und **Transkript neu erzeugen** (Pfeil-Symbol) wählen. Das alte Transkript bleibt, bis der neue Durchlauf fertig ist.

## Plan B: Sicherungsaufnahme mit OBS (einmalig 2 Minuten)

1. OBS Studio installieren (obsproject.com).
2. In OBS unter *Quellen* sicherstellen, dass **Desktop-Audio** vorhanden ist und sich der Pegel bewegt. Das Mikrofon kann stummgeschaltet bleiben.
3. *Aufnahme starten*. OBS speichert standardmäßig im Ordner *Videos*.
4. Falls bei Murmel etwas schiefgeht: In Murmel **Aufnahme importieren** wählen und die OBS-Datei (.mkv oder .mp4) auswählen. Murmel erstellt daraus eine neue Sitzung mit Transkript.

## Falls Murmel abstürzt

Murmel neu starten. Die Sitzung steht dann als „Unterbrochen“ in der Liste. Das Transkript bis zum Absturz ist gespeichert, und die Audiodatei wird automatisch repariert. Danach entweder eine neue Sitzung für den Rest starten oder später die OBS-Aufnahme importieren.

## Rechtlicher Hinweis

Viele Hochschulen erlauben Mitschnitte nur mit Zustimmung der Lehrperson. Kläre das kurz vorher. Murmel speichert Audio und Text nur lokal auf deinem PC.
