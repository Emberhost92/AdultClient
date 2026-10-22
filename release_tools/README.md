# Adult Client – portable Windows-Beta

Veröffentlicht unter https://github.com/Emberhost92/AdultClient.
Programm und Modelldaten werden getrennt aktualisiert.

## Starten

Für die erste Installation den gesamten `Windows-Komplett.zip`-Inhalt entpacken.
Das enthält das vorbereitete Modelldatenpaket bereits. `AdultClient.exe` doppelklicken.
Python und Kodi müssen nicht installiert sein. Windows x64 und .NET Framework 4
(auf aktuellen Windows-Versionen normalerweise vorhanden) werden benötigt.
Die Programmdateien müssen zusammenbleiben.

Das kleinere `Windows.zip` enthält nur das Programm. Das separate Modelldatenpaket besteht aus `star-data.sqlite3.gz` und
`star-data.sqlite3.json`. Beide Dateien vor dem ersten Start in den Ordner `data`
neben der EXE legen. Beim ersten Start wird die Datenbank geprüft und entpackt;
das kann etwas dauern. Danach öffnet sich die Oberfläche im Standardbrowser.

Persönliche Daten entstehen ausschließlich unter `userdata` neben der EXE.
Für den portablen Betrieb einen beschreibbaren Ordner verwenden, nicht
`Programme`. Die Arbeitsinstallation des Herausgebers wird nicht verwendet.
Zum Beenden: Einstellungen → Updates & Modellbilder → Programm beenden.
Das Schließen des Browserfensters allein beendet den Hintergrunddienst nicht.

## Deutsch / English

Die Oberflächensprache lässt sich jederzeit über `Deutsch / English` links im Menü
oder unter Einstellungen → Sprache & Models wechseln. Die Auswahl bleibt im
Browser gespeichert und wird zwischen geöffneten Fenstern desselben Profils
abgeglichen. Der Wechsel lädt die Seite und laufende Streams nicht neu.
Die Modelldatenbank, Namen, Tags, Biografien und eigene Notizen werden dadurch
nicht übersetzt. Die Sprachdateien sind mitgeliefert; beim Wechsel wird kein
Übersetzungsdienst aufgerufen.

Switch the interface instantly using `Deutsch / English` in the sidebar or
Settings → Language & models. Your choice persists in this browser and syncs
between open tabs. Switching does not reload the page or interrupt playback.
Model data and personal notes keep their original language. All interface
translations are shipped locally; switching does not contact a translation service.

## Modelldaten und Bilder

Das separate Datenpaket enthält Modellprofile, Originaltexte und gespeicherte
Übersetzungen, Quellenbelege, Szenen, Tags, Kategorien und alle gespeicherten
öffentlichen Bildverweise. Es enthält keine Fotos als Binärdateien.
Bilder werden standardmäßig bei Bedarf geladen, ohne dauerhaften Bildcache.
Über Einstellungen → Updates & Modellbilder lässt sich der vollständige
Bilddownload starten, pausieren und später fortsetzen. Bereits gespeicherte
Originalbilder werden für die Galerie und Vorschaubilder verwendet.
Nicht mehr erreichbare, geschützte oder zu große Bilder können fehlen.
Die Offline-Bilder können erheblich mehr Speicher als das Datenpaket benötigen.

Der automatische externe Quellenimport ist anfangs pausiert. Eigene Schlüssel
und Zugänge können individuell eingerichtet werden. Schlüssel, Cookies,
Notizen, Favoriten, Verlauf und Downloads des Herausgebers sind nicht enthalten.

## Updates

Unter Einstellungen → Updates & Modellbilder werden Programm und Modelldaten
getrennt angezeigt und aktualisiert. Die automatische Prüfung läuft nach dem
Start im Hintergrund und höchstens einmal täglich. Sie lässt sich ausschalten;
die manuelle Suche bleibt verfügbar. Betaversionen sind separat wählbar.
Ein sichtbarer Hinweis führt direkt zu den Updates. Es wird nichts ungefragt
heruntergeladen oder installiert. Öffentliche Releases benötigen keinen GitHub-Zugang.

Programm: herunterladen → Prüfung/Entpacken → Installieren und neu starten.
Ein separater Helfer wartet auf das beendete Programm, sichert die bisherigen
Programmdateien und die Modelldatenbank, tauscht die Programmdateien aus und prüft den neuen lokalen Dienst. Schlägt der
Start fehl, wird die vorherige Version wiederhergestellt und gestartet.
`userdata` und `data` werden vom Programmupdate nie ausgetauscht. Ein gleichzeitig
bereitgestelltes Datenupdate bleibt bei diesem Neustart zunächst unangetastet.
Die vorige Programmversion bleibt bis zum nächsten Programmupdate als Sicherung
unter `userdata/updates/program-backup` erhalten.
Eine zusätzliche SQLite-Sicherung vor Programmupdates schützt auch persönliche
Daten vor fehlgeschlagenen Datenbankmigrationen. Für Updates wird deshalb
ausreichend Platz für Paket, entpackte Dateien, Sicherung und Transaktionen geprüft.

Modelldaten: separat herunterladen → beim nächsten normalen Start übernehmen,
wahlweise über den eigenen Neustartbutton. Ein Datenupdate ersetzt keine EXE.
Aktuell wird das vollständige komprimierte Datenpaket geladen, kein Differenzpaket.

Release-Dateien für Programmupdates: `AdultClient-VERSION-Windows.zip` und die
beim Build erzeugte `program-update.json` (zusammen in derselben Veröffentlichung).
Für Datenupdates: `star-data.sqlite3.gz` und `star-data.sqlite3.json`.
Programm und Daten dürfen in unterschiedlichen Releases erscheinen, z. B.
`v0.3.0-beta.1` und `data-2026-11-01`. Daten werden nach dem UTC-Feld `created`,
Programme nach ihrer semantischen Versionsnummer verglichen. Die Suche beachtet
auch Betareleases und prüft die letzten 500 Veröffentlichungen.
Die SHA-256-Prüfsumme schützt vor unvollständigen/veränderten Downloads; die
Updatequelle muss ein vertrauenswürdiges, vom Herausgeber kontrolliertes Repo sein.
Prüfsummen ersetzen keine Signatur gegen eine kompromittierte Veröffentlichungsquelle.

Modelldatenupdates werden beim nächsten Start mit einer vorherigen SQLite-
Sicherung zusammengeführt. Private Metadaten, persönliche Tabellen, Dateien,
Favoriten, Notizen und eigene Cover bleiben bestehen. Ein Downloadfehler verändert
keine installierten Daten. Bei einem vorübergehenden Netzfehler bleibt die
Oberfläche bedienbar; der Fehler wird in den Updateeinstellungen angezeigt.

The program and model data have independent updates in Settings → Updates &
model images. Background checks run on startup and at most daily and can be
disabled. Downloads and restarts require a button click. Program replacement
preserves userdata, verifies startup and rolls back a failed launch. Model data
is merged separately at the next normal startup. The publishing repository and
first public release still need to be created before real online updates work.

## Herkunft und Veröffentlichung

AdultHideout-Anbieteradapter sind enthalten, einschließlich ursprünglichem
GPL-Lizenztext und Herkunft in `addon/addon.xml`. Der vollständige hier
verwendete Python-/JavaScript-Quellcode sowie die Buildwerkzeuge sind enthalten.
Weitere Bibliothekslizenzen liegen bei den Runtime-Paketen und unter `licenses`.
Die EXE ist derzeit nicht digital signiert.

Die Modelltexte und Bildverweise behalten ihre Quellen. Die technische
Exportierbarkeit ist keine pauschale Weiterveröffentlichungserlaubnis für
fremde Texte, Fotos oder Datenbanken. Vor einer öffentlichen Veröffentlichung
bleibt die Prüfung der jeweiligen Quellenbedingungen und Assetlizenzen offen.

## Feedback über GitHub / Feedback via GitHub

Unter Einstellungen → Feedback & Hilfe lassen sich Fehler, Wünsche und allgemeine
Rückmeldungen vorbereiten. Ein Klick öffnet den Entwurf im öffentlichen GitHub-Projekt;
erst dort wird er mit dem eigenen GitHub-Konto veröffentlicht. Die Kategorien sind
`bug`, `enhancement` und `feedback`; der betroffene Bereich steht zusätzlich im Titel.
Programmversion und Browser können optional beigefügt werden. Es werden keine
Zugangsdaten, Protokolle, Favoriten oder Verlaufsdaten automatisch übernommen.
Bei langen Meldungen „Text kopieren“ verwenden und die Beschreibung auf GitHub einfügen.

Settings → Feedback & help prepares bug reports, feature requests and general feedback.
The button opens a public GitHub draft; publishing requires your own GitHub account
and a separate click on GitHub. Program version and browser are optional. Credentials,
logs, favorites and history are never collected automatically. Use “Copy text” and
paste the report on GitHub if it exceeds the direct-link length limit.

## Erneut bauen (Herausgeber)

`python release_tools/build_portable.py distribution/AdultClient-NEUE-VERSION`

Der Build verwendet eine ausdrückliche Dateiauswahl und exportiert nur bekannte
Modelldatentabellen. HTTP-Anfragecaches, Benutzerkonfigurationen und Sitzungen
werden nicht kopiert. Das Quelldatenbankprofil wird ausschließlich gelesen.
Die Quellkopie und der Datenbankexport sind getrennte Downloadartefakte, damit
Programmupdates keinen erneuten Download der großen Modelldatenbank erfordern.
