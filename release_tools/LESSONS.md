# Prüfungen unter Windows

Beim Kopieren einer portablen Testinstallation nur den obersten `data`-Ordner
auslassen. Ein Ausschluss aller Ordner dieses Namens entfernt auch
`addon/resources/data` mit dem Basis-Profilindex und verfälscht sichtbare
Bestandszahlen. Veröffentlichte Zahlen am unveränderten Paket mit separatem
Profil und dem tatsächlichen Katalogcode prüfen.

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
