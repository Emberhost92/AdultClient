# Adult Client: Multicam

Stand: 19.10.2026.

## Bedienung und Streamfläche

Das Hauptmenü kann über das immer erreichbare ☰-Symbol ein- und ausgeklappt werden. Diese Browserpräferenz gilt über Menüwechsel und Neuladen hinweg. In der Live-Sektion entfallen die Tube-Suchleiste, die Live-Überschrift und der Beschreibungstext. Live-Untermenüs besitzen einen eigenen Einklappschalter.

Multicam zeigt eine kompakte Leiste zum getrennten Ein-/Ausklappen von Arbeitsbereich, Anbietern, Filtern/Ton, Modellliste und Werkzeugen. „Mehr Streamfläche“ klappt diese Bereiche, die Hauptnavigation und die Live-Untermenüs ein. „Bedienung“ versteckt zusätzlich die kompakte Leiste; der über den Streams bleibende Einblendknopf holt sie zurück. Die Zustände bleiben je Arbeitsbereich unter `settings.panels` erhalten. Die Leistenpräferenzen löschen keine Belegungen.

Das normale Raster besitzt gleich große Zellen und vollständig gefüllte Reihen. Vier Plätze ergeben 2×2, zwölf Plätze auf ausreichend breiten Flächen 6×2. Bei geringerer Breite wird eine passende kleinere Spaltenzahl gewählt, die die Platzzahl ohne Rest teilt. Auf sehr schmalen Flächen scrollt die Kamerafläche vertikal, statt winzige Zellen zu erzwingen. Mosaik, Fokus und eigene Raster bleiben ausdrücklich wählbare Alternativen. Frühere automatisch angelegte Mosaikansichten werden einmalig auf das neue Raster umgestellt (`symmetricVersion: 1`); danach bleibt eine bewusst gewählte Alternative erhalten.

Die Größenberechnung berücksichtigt die tatsächlich sichtbare Oberkante und die aktuelle Fußleistenhöhe, auch nach Scrollen, Größenänderung oder Einklappen. Leere Kacheln werden nicht länger als fokussiert markiert. Das Videoformat bleibt separat einstellbar: „Ganzes Bild“ erhält das gesamte Bild, „Fläche ausfüllen / beschneiden“ füllt die Kachel.

## Modellliste, Vorschau und Verfügbarkeit

Suche und farbige Statusschalter bleiben oben sichtbar. Weitere Filter/Sortierung und Gruppen/Following sind getrennt einklappbar; die restliche Höhe erhält die Modellliste. Zeilen besitzen Cover, Namen, Status, Anbieter und Platzmarkierung. Statusfarben werden stets von Symbol und Text ergänzt: Grün = live, Rot = offline, Orange = privat, Grau = unbekannt.

Eine Vorschau startet nach 180 ms über der ganzen Modellzeile beziehungsweise über einem Modelnamen in einer Gruppe. Beim Übergang zum Vorschaufenster bleibt Zeit, um dessen Schaltflächen zu bedienen; sie kann angeheftet werden. Bei einem Abruffehler bleiben ein vorhandenes Cover, eine Fehlerangabe und ein manueller Wiederholungsbutton sichtbar. Ein Fehler setzt den Vorschauplayer ausdrücklich auf `failed`, beendet HLS und löst keine Endlosschleife aus.

Statusmeldungen aus `seen`/`_observedAt` verfallen nach zwei Minuten zu unbekannt. Eine fehlende Statusbestätigung gilt weder als live noch als offline. Eine bestätigte öffentliche Streamantwort beziehungsweise laufende Wiedergabe kann einen alten Eintrag korrigieren. Ein gespeicherter Offline-/Privatstatus blockiert nicht mehr vorab den vom Benutzer gestarteten Aufruf: Die vorhandene serverseitige öffentliche Raumprüfung bleibt maßgeblich und lehnt nicht öffentliche Inhalte weiterhin ab. Eine Meldung „nicht öffentlich“ wird nicht durch wiederholte automatische Startversuche übergangen.

Beim Ziehen mit Maus oder Touch zeigt eine direkte Pointer-Bedienung einen Ziehhinweis und hebt das Ziel hervor. Sie arbeitet auch in Browsern ohne zuverlässige HTML-Drag-Übertragung. Zusätzlich werden qualifizierte Anbieter-/Modelkennungen übertragen; Zielplätze akzeptieren sowohl den eigenen Drag-Datentyp als auch Browsertext und öffentliche Raumlinks. Bestehende Belegungen und freie Zwischenplätze bleiben beim Einsetzen und Tauschen erhalten. „Einsetzen“ und der Modelname bieten zusätzlich eine direkte Bedienung ohne Ziehen.

## Relevante Dateien und Prüfungen

- `static/app.html`: Hauptnavigation und Live-Menüs einklappen, Live-Bereich markieren.
- `static/live_cam_domain.js`: Raster, Statusalterung und kompatible Wiederherstellung.
- `static/live_cam_studio.js`: Leisten, Listen, Vorschau, Einsetzen und Statusrückmeldungen.
- `static/live_cam_studio.css`: platzsparende, responsive Darstellung und Statusfarben.
- `tests/test_live_cam_studio.js`: symmetrische Reihen, Statusalterung, terminale Vorschaufehler, Drag-Datentypen und Wiederherstellung.
- `tests/live_cam_browser_fixture.py`: synthetische Räume, lokale bewegte Hoch-/Querformatvideos und optional `--stale-status` für einen inzwischen wieder öffentlichen Raum mit Offline-Eintrag.

Praktisch im isolierten Browserprofil geprüft: Vier und zwölf laufende Videos mit tatsächlich präsentierten Frames, 2×2 und 6×2, Größenwechsel, 420-Pixel-Ansicht ohne horizontalen Seitenüberlauf, Einklappen/Einblenden, Beibehaltung nach Neuladen, Vorschau und erneute öffentliche Prüfung eines zuvor als offline gespeicherten Raums. Der Drop-Übergabepfad ist automatisiert geprüft. Die direkte Maus-Ziehbewegung vom Modellnamen auf eine belegte Kachel wurde im Browser erfolgreich geprüft: Die beiden Bibliotheksmodelle tauschten die Plätze, alle vier Videos liefen mit weitergezählten Frames weiter. Ein normaler Klick auf den Namen funktioniert ebenfalls weiterhin. Der reguläre Einstieg wurde ebenfalls auf Raster, verborgene Platzverbraucher und Browserfehler geprüft. Echte Anbieter können weiterhin Browserprüfungen verlangen oder Räume zwischenzeitlich schließen.

Automatisierte Schlussprüfung: 230 JavaScript-Prüfungen sowie 16 Python-Integrationsprüfungen erfolgreich; geänderte Module und Inline-Skripte ohne Syntaxfehler. Die automatische Vorschau über dem Avatar zeigte im Browser tatsächlich präsentierte Videoframes; keine Browserfehler in der isolierten oder regulären Prüfung.

## Nachbesserung der Verbindungsstabilität (19.10.2026)

Multicam nutzt adaptive Bandbreitenauswahl innerhalb der maximalen Qualität, einen 20-Sekunden-Zielpuffer (maximal 40 Sekunden/12 MiB je Player), vier Sekunden Rückpuffer und keine erzwungene Niedriglatenz. Dekodierfehler werden höchstens zweimal in derselben HLS-Instanz repariert. Nach ausgeschöpften Netzwerkversuchen wird mit 5/10/20/40/60 Sekunden Abstand eine neue öffentliche Quelle angefordert; manuell pausierte Kameras starten dadurch nicht. 45 Sekunden ohne Bild im Pufferzustand führen ebenfalls zu einer begrenzten Wiederverbindung. Tatsächlich geschlossene/private Räume bleiben geschlossen.

Aktuelle Anbieterlisten werden vor dem großen gespeicherten Bestand aktualisiert. Der komplette Bestand wird automatisch höchstens alle zehn Minuten erneut gelesen; ausdrückliche Aktualisierung liest ihn weiterhin vollständig. Die ungeänderte Standardreihenfolge bevorzugt aktuell bestätigte öffentliche Räume vor alten unbekannten Einträgen.

Praktische Nachprüfung der Stabilitätsänderung: vier echte öffentliche Streams gleichzeitig (zweimal Chaturbate, einmal CamSoda, einmal CAM4), über mindestens eine Minute gemeinsam, mit fortschreitenden Videozeiten, `readyState=4`, ohne Video- oder Browserfehler. Der zuerst gestartete Stream lief in dieser Messung über 140 Sekunden. Aktuelle Raumlisten, Masterplaylist, Medienplaylist und echtes Segment wurden zusätzlich geprüft. 191 automatische Live-JavaScript-Prüfungen einschließlich der neuen Regressionen erfolgreich. Kein Langzeitnachweis für sämtliche Räume oder alle sechs Anbieter.

## Schnellere Vorschauübernahme und Vollbild (19.10.2026)

Hover-Vorschauen werden im aktiven Vollbildelement geöffnet, laden mit einer adaptiven Obergrenze von 360p und melden „Live“ erst bei laufender Wiedergabe. Bis dahin bleibt das gespeicherte Vorschaubild sichtbar. Ausbleibende Bilder erhalten nach 30 Sekunden eine Fehlermeldung mit erneutem Versuch. Der Mausübergang zwischen Karte und Popup hat 350 ms Toleranz.

Beim Einsetzen oder Ziehen einer Vorschau wird die bestehende HLS-Verbindung samt Video übernommen. Es gibt keinen zweiten Quellenabruf und keinen absichtlichen Puffer-Neustart. Der Übergabezustand wird bei Abbruch oder spätestens nach 15 Sekunden freigegeben. Neue Streams können den ersten Abschnitt früher vorladen; das Live-Ziel liegt bei drei Segmenten, die bisherigen Puffergrenzen bleiben erhalten.

Modellprofile werden aus einem Index gelesen, Filter teilen sich dieselbe Gruppenzuordnung und eine unveränderte sichtbare Seitenliste wird nicht erneut aufgebaut. Das reduziert Arbeit bei großen Beständen und vermeidet unnötige Hover-Unterbrechungen.

Praktisch im echten Vollbild geprüft: sichtbare bewegte Vorschau und nahtlose Übernahme per Button sowie Maus-Drag-and-drop, jeweils gleiche Videoquelle und fortlaufende Videozeit ohne zusätzlichen Quellenabruf. 196 Live-JavaScript-Prüfungen bestanden; geänderte Inline-Skripte und Modulsyntax geprüft.

## Browser-Tabwechsel und Minimieren (19.10.2026)

Multicam pausiert wegen eines unsichtbaren Browser-Tabs weder stumme noch hörbare Kameras. Quellenabrufe werden beim Minimieren nicht abgebrochen, Warteschlangen und begrenzte Wiederholungen arbeiten weiter. Manuelle Pausen sowie bewusst gesetzte aktive Kamera-/Fokusgrenzen gelten weiter. Beim Zurückkehren schützt eine kurze Anlaufzeit vor einer falschen Stillstandserkennung durch im Hintergrund ausgesetzte Frame-Callbacks. Die auf kleine Katalogkarten begrenzte Vorschau-Energiesparregel bleibt davon getrennt.

## Performancekorrektur für große Bibliotheken (19.10.2026)

Der Studio-Abruf liest kompakte Seiten mit je 2.000 Models aus einem kurzlebigen, stabilen Listenstand. Anbieterlisten starten parallel. Der vollständige Abruf bleibt erhalten; große Profiltexte und Bildsammlungen werden für das Multicam-Auswahlmenü nicht erneut übertragen. Modellzugriffe und Statushistorie vermeiden wiederholte vollständige Suchen.

Die aktuellen HLS-Puffer ersetzen die zuvor beschriebenen großen Grenzen: Vorschau 3 Sekunden Ziel, maximal 6 Sekunden/2 MiB und kein Rückpuffer; Hauptplayer 8 Sekunden Ziel, maximal 16 Sekunden/6 MiB und 2 Sekunden Rückpuffer. Vorschauen erhalten Vorrang beim Start. Nach dem Verlassen wird höchstens eine laufende Vorschau acht Sekunden pausiert gehalten, ohne weiteres Nachladen; erneutes Öffnen übernimmt dieselbe Verbindung. Danach oder bei ausdrücklichem Schließen wird sie freigegeben. Einsetzen übernimmt weiterhin denselben Player. Chaturbate erhält bei jedem neuen Auflösungsversuch eine frische Adresse.

Messung am tatsächlichen Bestand: 39.917 eindeutige Models, 20 Anfragen statt ungefähr 160, insgesamt 1,959 Sekunden. Erste echte Videowiedergabe einer öffentlichen Vorschau nach 1,652 Sekunden. Anbieterantworten, Verbindung und verfügbare Rechenleistung bestimmen weiterhin die tatsächliche Startzeit.
