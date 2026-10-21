# Prüfungen unter Windows

`with sqlite3.connect(...)` beendet eine Transaktion, schließt die Verbindung
aber nicht. Testdatenbanken zusätzlich mit `contextlib.closing` schließen;
sonst können alle Funktionsprüfungen bestehen und das anschließende Entfernen
des temporären Profils dennoch an einer gesperrten Datei scheitern.

Ein Update gilt erst nach echter Dateiübernahme und geprüftem Start des neuen
Dienstes als erfolgreich. Die Tests decken deshalb auch einen absichtlich
fehlgeschlagenen Start, ein getrenntes Datenupdate und die Wiederherstellung
über die EXE nach einer unterbrochenen Installation ab. Der kleine EXE-Starter
bleibt bei Programmupdates erhalten, damit er die Wiederherstellung auch dann
starten kann, wenn `app` oder `runtime` gerade ausgetauscht wurden.
