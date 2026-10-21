# Gemeinsame Medienbibliothek

Stand: 18.10.2026. Die Weboberfläche erhält eine gemeinsame Grenze zwischen Kodi-Anbietern und Darstellung. Die installierten Kodi-Quellen werden dadurch nicht verändert.

## Aufbau

- `media_library.py`: Dateitypen, Metadaten, Anbieterfähigkeiten, ergänzende Foto-Adapter und vollständige Originaldateien.
- `static/media_library.js` und `.css`: Anbieterübersicht, lokale Filter und Sortierung, Kacheln/Fotowand/Liste sowie Medienbetrachter.
- `server.py`: bindet diese Grenze an bestehende Anbieterabfragen und Merklisten an. Der vorhandene Videoplayer bleibt der Einstieg für normale Videos.
- `static/app.html`: übergibt den geladenen Bestand und bestehende Aktionen an die Bibliothek. Die globale Tube-Suche behält ihre bisherige Darstellung.

Jeder gelistete Eintrag besitzt `media.version=1`, `kind`, `extension`, `mime`, `provider` und, soweit veröffentlicht, `width`, `height`, `duration`, `date`, `rating`, `size`. Zulässige Typen sind `video`, `image`, `animation`, `audio`, `document`, `file`, `gallery`, `folder`, `live`. Vorschaubilder bestimmen niemals den Typ des eigentlichen Eintrags. Eine bekannte Dateiendung korrigiert falsche pauschale Videoangaben älterer Adapter. Bestehende Videoseiten ohne Dateiendung bleiben Videos.

Anbieter können über das Kodi-Infofeld `mediatype` oder die Property `web_media_type` den tatsächlichen Typ setzen. Ordner mit Typ `gallery` bleiben Navigation; Fotos, Animationen und andere Dateien sind abspielbare Einträge mit `mode=4`. Referer und nötige Anbieterheader gehören an die Originalquelle und werden beim Auflösen erhalten. Neue Sonderfälle gehören in den Adapterbereich des Medienmoduls, nicht in weitere Sonderabfragen im Frontend.

## Originale und Galeriebedienung

`GET /api/media/resolve?query=<Kodi-Abfrage>` liefert Typ, Originalansicht und Downloadadresse. Die Quellen und Header bleiben hinter kurzlebigen serverseitigen Tokens. Der Medienport überträgt Originale in Blöcken und übernimmt Range-Antworten. Er verwendet nicht den auf 500 KB beschränkten Vorschaubildpfad. Direkte Medienadressen im Ergebnis vermeiden eine fehlerhafte zusätzliche CORS-Weiterleitung bei der Textvorschau.

Der Betrachter unterstützt Bilder/Animationen, Audio/Video und sichere Textvorschauen. Für PDF gibt es eine Browseransicht. Andere Dateien erhalten einen Originaldownload; beispielsweise wird ein ZIP nicht als bereits entpackte Galerie ausgegeben. Browser und verfügbare Codecs bestimmen die tatsächliche Wiedergabefähigkeit.

Filter und Sortierungen betreffen ausdrücklich den bereits geladenen Bestand. Weitere Anbieterseiten lassen sich hinzufügen; unbekannte Metadaten bleiben unbekannt. Ansichten und Filterprofile werden je Browser gespeichert. Merkliste und Gruppen erhalten den Medientyp, damit ein gespeichertes Foto auch später wieder im Bildbetrachter öffnet. Die Galerieansicht verwendet nur Bilder/Animationen und behält beim Nachladen die gewählten Filter bei.

## Anbieter und Grenzen

Die Fähigkeiten werden aus den tatsächlich eingebundenen Adapterdateien und ihren gemeinsamen Basisklassen gelesen, ohne sämtliche Anbieter zu importieren. Änderungen an vorhandenen Dateien erneuern den Katalog. Die Kennzeichnung beschreibt den Parserumfang, keine aktuelle Erreichbarkeitsgarantie. Beim lokalen Abgleich waren alle 44 zuvor gefundenen fotoerzeugenden Adapter erfasst.

Zusätzlich bleiben bei Erome die Videos erhalten und Fotos kommen hinzu. LeakGallery verwirft Bildanhänge nicht mehr. BAlbums ergänzt die bisher ausgeschlossenen Dateien. Fapello, CherryGasp, MyLust und Feet9 erhalten einen zusätzlichen veröffentlichten Bild-/Galeriebereich. Dessen Abruf nutzt nach Möglichkeit die vorhandene HTTP-Anbindung des Anbieters. Galerie-Cover sind Navigation und werden nicht als Originalbilder ausgegeben.

Dies ersetzt keine Prüfung sämtlicher externer Anbieter. JavaScript-only-Seiten, Anmeldungen, entfernte Dateien oder geänderte HTML-/API-Strukturen brauchen weiterhin passende Anbieteradapter. Insbesondere wird aus einem reinen Video-Adapter wie Iwara nicht allein durch die neue Oberfläche eine vollständige Bilder-API. Die gemeinsame Schnittstelle ist dafür vorhanden; eine solche API-Erweiterung bleibt gesondert umzusetzen und zu prüfen.

Chaturbate, Stripchat, CAM4, XLoveCam, BongaCams und CamSoda sind aus dem Seitenkatalog ausgeschlossen. Alte Favoriten dieser Live-Anbieter führen ins vorhandene Live-Menü. Aufzeichnungsarchive bleiben unter Seiten. Die Live-Module, deren Konten und Bibliotheken werden von diesem Medienmodul nicht geändert.

## Prüfung und Start

Automatische Prüfungen: `python -B -m unittest discover -s tests -p "test_*.py"` und `node --test tests/test_*.js`. Die Medienregressionen prüfen unter anderem die tatsächliche Server-Payload, Bild-/Galerietrennung, Kategorieabfragen, gemischte Adapter, Dateigröße, Originalbytes, Range-Antworten, alte Playerzustände und den HTTP-Einstieg.

`python -B tests/media_browser_fixture.py` startet die echte Oberfläche mit synthetischen Medien auf 20081/20082 und einem temporären Profil. Sie ersetzt keine echten Anbieterzugänge und führt keine externen Suchen aus. Praktisch geprüft wurden Originalbildanzeige, Navigation/Zoom/Drehung/Diashow, Filter/Sortierung/Profile, weitere Seiten, Merken mit erneutem Laden, ein gültiger 2-MB-Download, Text/Audio/Video, Fehlerzustände, Wechsel zur bisherigen Videosuche sowie das 420-Pixel-Layout. Die PDF-Vorschau und sämtliche echten Anbieter wurden nicht einzeln praktisch geprüft.

Für die laufende normale Instanz muss nach Abschluss paralleler Arbeiten der Webserver neu gestartet und die Seite mit Strg+F5 geladen werden. Nur `start.bat` erneut zu öffnen startet einen bereits laufenden Server nicht neu. Die während der Umsetzung bereits laufende Instanz wurde wegen der parallelen Live-Arbeiten nicht beendet.


## Persönliche Anbieterübersicht (19.10.2026)

Unter **Seiten** besitzt jeder Hoster eigene Aktionen **Favorit** und **Ausblenden**. Der Filter **Anbieter anzeigen** wechselt zwischen sichtbaren, ausgeblendeten und allen Anbietern. **Nur Favoriten** lässt sich mit Suche, Medientypen und den übrigen Filtern kombinieren. Ausgeblendete Hoster können im entsprechenden Filter mit **Einblenden** wiederhergestellt werden; gespeicherte Medien und bestehende Favoriten bleiben erhalten. **Filter zurücksetzen** stellt die sichtbare Übersicht wieder her und blendet keine Hoster ungefragt ein.

Favoriten und ausgeblendete IDs werden im vorhandenen lokalen Profil gespeichert. Einzelaktionen laufen unter derselben Schreibsperre wie andere Profiländerungen und ersetzen keine fremden Einstellungen. Die Filterwahl bleibt pro Browser erhalten. Live-Anbieter sind davon getrennt. Ein Speicherfehler verändert die Karten nicht und erlaubt einen erneuten Versuch.

Prüfung: `test_site_preferences.py` verwendet ein temporäres Profil und prüft parallele Einzelaktionen, persistente Sichtbarkeit, Favoriten, Erhalt gespeicherter Medien sowie die Live-Trennung. `test_site_preferences_browser.cjs` nutzt die isolierte Multitube-Testumgebung auf 20181/20182 und prüft den tatsächlichen Ablauf einschließlich Neuladen, Favoritenfilter, Sichtbarkeit, Suche, Rücksetzen, Serverfehler und Wiederherstellung sowie Kacheln/Liste bei 360 Pixel Breite.

## Inhaltsvorschau für Hoster (19.10.2026)

In **Seiten** öffnet sich nach 450 ms Hover ein Vorschaufenster mit höchstens sechs vorhandenen Inhalten. Der Button **Vorschau** funktioniert auch mit Touch/Tastatur und bei abgeschaltetem **Hover-Vorschau mit Hoster-Inhalten**. Gelieferte Vorschauclips laufen stumm, Bildfolgen wechseln und Inhalte ohne bewegte Vorschau behalten ihr Bild. Es wird immer nur ein Vorschauclip gleichzeitig gestartet. Ein Inhaltsklick öffnet das originale Video oder den vorhandenen Medienbetrachter; **Anbieter öffnen** bleibt auch bei leerer Vorschau verfügbar. Verlassen, Escape, Navigation und Verbergen des Browser-Tabs stoppen die kleine Hoster-Vorschau. Multicam-Verbindungen bleiben davon getrennt.

`GET /api/site-preview?website=…` akzeptiert nur katalogisierte Anbieter außerhalb der Live-Sektion. `site_previews.py` begrenzt externe Vorschauarbeit auf einen Abruf gleichzeitig und höchstens eine Startliste plus zwei gewöhnliche Inhaltsverzeichnisse desselben Hosters. Such-, Aktions- und Videoauflösungsmodi werden nicht verfolgt. `run_plugin(..., preview=True)` verhindert Einträge in „Zuletzt geöffnet“ und unnötige Star-Anreicherungen. Verfügbare Listen-Caches werden wiederverwendet; ein eigener Speicher-Cache hält höchstens 32 Hoster für fünf Minuten, leere Ergebnisse für 30 Sekunden. Bereits gelieferte Clips vermeiden einen zusätzlichen HTML-Abruf; scheiternde Clip-Anreicherung verwirft vorhandene Bilder nicht. Der Browser hält ebenfalls höchstens 32 Stichproben und verwirft verspätete Antworten nach Anbieterwechsel.

Praktisch mit echten Xvideos-Inhalten geprüft: sechs Clips, laufendes stummes Video, automatischer Hover und Schließen beim Verlassen; der Web-Verlauf blieb unverändert. Mit neutralen lokalen Testmedien zusätzlich Inhaltsklick bis zur tatsächlichen Wiedergabe, reine Bildvorschau, leere Ergebnisse, Kacheln/Liste, Schalter und expliziter Button sowie 420-Pixel-Ansicht geprüft. Der Popup-Rand bleibt innerhalb der nutzbaren Breite einschließlich Scrollbar. Die isolierte Oberfläche startet mit `python -B tests/site_preview_browser_fixture.py --port 19880`; `/__test__/video-factory` erzeugt ihre bewegten Testmedien. Automatisch: 22 JavaScript-Prüfungen für Medienbibliothek/UI-Leistung, acht Vorschau-Backendprüfungen, 17 Medien- und 16 Live-Integrationsprüfungen erfolgreich. Nicht jeder der über 400 Hoster wurde einzeln geprüft; bei fehlenden Beispielen bleibt der reguläre Einstieg bedienbar.

## Sortierung und Vorladen (20.10.2026)

Die sichtbare Auswahl „Gesamten Anbieter sortieren“ verwendet die vorhandenen Anbieter-/Seitensortierungen und deren echten Abrufweg; lokale Sortierung bleibt getrennt und nutzt nur geladene Einträge. Ergänzt sind Aufrufzahlen (auch K/M/Mio.-Angaben), Uploader, Auflösung, Bewertung aufsteigend, Favoriten und vorhandene Vorschauen. Unbekannte Zahlen bleiben hinten. Es werden keine einzelnen Videoseiten nur zum Sortieren abgefragt. Standardmäßig drei Medienseiten voraus, wählbar eine oder sechs; maximal vier serielle Anbieterabrufe pro normalem Vorgang, maximal zehn bei sechs vorausgeladenen Seiten. Bereits vollständig geladene Medienseiten und Anbieter-Sortierungen bleiben während Hintergrundabrufen bedienbar.

Prüfung: 38 Medien-/Blätter-/UI-Tests bestanden. Im echten XVideos-Ablauf wurden 154 Einträge mit Standard-Vorladen und 262 mit sechs vorausgeladenen Seiten erreicht; Anbieter-Sortierung „Meistgesehen“ wechselte auf die Views-Liste. Testauswahl anschließend auf Anbieter-Reihenfolge/Relevanz und drei Seiten voraus zurückgestellt. Keine Browser-Konsolenfehler.

### Erweiterung großer Vorladeziele

Vorgaben jetzt Aus, 1, 3, 6, 10, 15, 25, 50, 100 und 250 Medienseiten voraus; eigene ganze Anzahl von 1 bis 250 bleibt pro Anbieter gespeichert. Das Standardziel bleibt drei Seiten. Die frühere Beschränkung auf vier/zehn Abrufe entfällt für fortlaufende Ziele: jeweils ein Abruf, kurze Pause dazwischen, zusammengefasste Fortschrittsanzeige statt Neuzeichnen nach jedem Abruf. Pausieren/Fortsetzen, Ausschalten, Zieländerung und Navigation beenden die weitere Folge; ein laufender Abruf darf noch fertig werden. Vier Antworten ohne neue passende Einträge stoppen die Folge. Browserbestände begrenzt auf 50.000 Einträge/2.000 Hoster-Seiten, damit auch 250 Medienseiten bei großer Seitengröße erreichbar sind.

Geprüft: 44 gezielte Tests bestanden, einschließlich tatsächlichem Erreichen des 250-Seiten-Ziels in der automatisierten Ablaufprüfung. Im Browser mit neutralem Testanbieter 3.340 Einträge geladen, pausiert, fortgesetzt und erneut pausiert; Aus blendet das eigene Eingabefeld aus. Eigene Anzahl wird mit „Anzahl übernehmen“ oder Enter übernommen. Keine Konsolenfehler. Große Bestände wurden zur UI-Prüfung lokal simuliert, kein Massenabruf bei echten Hostern.
