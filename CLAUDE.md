# Regeln für Murmel

## Design
- Neue Oberflächen und Funktionen übernehmen den bestehenden Murmel-Stil: die Farb- und Abstands-Tokens aus `app/renderer/css/app.css`, Figtree für UI-Text, EB Garamond für Überschriften und Lucide-Icons über `app/scripts/make-icons-css.js`. Keine eigenen Design-Richtungen oder abweichenden Looks, auch nicht für einzelne Seiten. (Vorgabe des Nutzers, 12.11.2026)
- Die App-CSP verbietet Inline-`style`-Attribute in HTML-Strings. Dynamische Werte wie Breiten werden über `element.style` gesetzt.

## Tests
- `pytest tests` läuft unter Windows vollständig (CI: `.github/workflows/windows-build.yml`). Unter Linux brauchen die Tests Stubs für `pyaudiowpatch`, `sounddevice`, `comtypes`, `pycaw` und `ctypes.WinDLL`; die drei Hotkey-Tests scheitern dort an `keyboard` (fehlendes `dumpkeys`).
