# Adult Client

Lokale Medienoberfläche für Windows. Projektersteller: **emberhost**.

Die Bedienoberfläche ist auf Deutsch und Englisch umschaltbar: links im Menü
über **Deutsch / English** oder unter **Einstellungen → Sprache & Models →
Oberflächensprache**. Der Wechsel erfolgt ohne Neuladen und bleibt im Browser
gespeichert. Modellbiografien, Tags, Quelleninhalte und persönliche Notizen
behalten ihre eigene Sprache. Die Übersetzungen der Oberfläche sind lokal
mitgeliefert und benötigen beim Wechsel keinen Übersetzungsdienst.

Start: `start.bat`, anschließend `http://127.0.0.1:8765` im Browser öffnen. Das Serverfenster muss geöffnet bleiben. Für den Betrieb werden die vorhandenen Anbieteradapter des installierten Kodi-Addons benötigt.

Die Bedienungsanleitung erreichst du über **Einstellungen → Hilfe** oder den Hilfe-Button im Einstellungskopf. **Einstellungen → Über Adult Client** erklärt Projekt, Speicherung und Bestandteile. Gestaltungsoptionen stehen in [EINSTELLUNGEN.md](EINSTELLUNGEN.md).

Eigene Schriften lassen sich global, pro Schriftrolle oder je Menü festlegen. **Camclient Script** wird lokal mitgeliefert. Änderungen im Design werden zunächst als Vorschau angezeigt und mit **Änderungen speichern** übernommen.

Die bisherigen Ordnernamen, Addonkennungen und Browserdatenbanken bleiben als technische Kompatibilitätsnamen erhalten. Lizenz- und Herkunftsangaben der eingebundenen Drittanbieterbestandteile stehen weiterhin in deren Originalquellen.


## Tube-Videoplayer

Über dem Tube-Video stehen Regler für **Playergröße**, **Maximale Breite** und **Bildzoom**. Der Rahmen folgt dem tatsächlichen Videoformat, sodass ein ultrabreites Browserfenster keine zusätzlichen breiten schwarzen Seitenflächen im Player erzeugt. Am Pfeilgriff rechts lässt sich die Größe ziehen oder mit den Pfeiltasten ändern. **Ganzes Bild** erhält den vollständigen Ausschnitt; **Rahmen füllen** und Bildzoom beschneiden die Ränder. Die Auswahl bleibt auf diesem Browser gespeichert; **Größe zurücksetzen** stellt den Ausgangszustand wieder her. Die Größenänderung lädt den Stream nicht neu.

Das Upload-Datum steht oberhalb des Players. Genaue veröffentlichte Datumsangaben haben Vorrang vor relativen Angaben wie „vor zwölf Jahren“. Uhrzeit und Quellenzeitzone bleiben erhalten. Wenn eine Quelle nur den Tag oder keine genaue Angabe veröffentlicht, wird das ausdrücklich angezeigt. Ein Film-Veröffentlichungsdatum wird nicht aus einer Titelsuche als Upload-Datum übernommen.

Unter dem Player steht zusätzlich **Videoinformationen** mit allen ausgelesenen Angaben zum aktuellen Video: Upload samt veröffentlichter Uhrzeit und Zeitzone, Originaltitel, Quelle und Originallink, Uploader, Video-ID, Dauer, Aufrufe, Bewertung, Kommentare, Sprache sowie weitere veröffentlichte Größen und Daten. Models, Kategorien und Tags stehen ebenfalls darunter. Nicht gelieferte Zusatzangaben werden nicht ergänzt. **Aktuelle Wiedergabe** zeigt die tatsächlich geladene Bildgröße, Dauer, Qualitätsauswahl und das Tempo; die vom Anbieter genannte Qualität bleibt davon getrennt. Während des ersten Abrufs wird der Ladevorgang ausdrücklich angezeigt.

Die Tube-Anbieter verwenden denselben abgesicherten Medienzugang, einschließlich lokaler Addon-Zwischenserver. HLS-Wiedergabelisten werden auch anhand ihres Medientyps erkannt; relative Teiladressen beziehen sich auf das endgültige Ziel einer Weiterleitung. Bei 30 Sekunden ohne Lade- oder Wiedergabefortschritt versucht der normale Player eine noch nicht gescheiterte Alternativquelle. Sind keine Alternativen mehr vorhanden, beendet er den Versuch mit einer sichtbaren Meldung. Ein Qualitätswechsel erhält die Spielposition. Verlassene Player beenden ihre Abfragen und verspätete Antworten dürfen die Wiedergabe nicht wiederbeleben. Multitube zeigt bei 30 Sekunden Stillstand einen erneuten Versuch an; absichtlich pausierte Plätze zählen dabei nicht mit. Gelöschte Videos, Anmeldesperren, Anbieteränderungen und Netzausfälle bleiben mögliche externe Ursachen.

## Live-Karten und Vorschaubilder

Die Modelkarten in Räume/Entdecken, Models und den gemeinsamen Live-Listen zeigen drei Aktionsbuttons: **Details**, **+ Multicam** und **Zu Gruppe**. Die Gruppenauswahl ergänzt eine oder mehrere eigene, nicht archivierte manuelle Gruppen; bestehende Zuordnungen bleiben erhalten. Favoriten, Merkliste und weitere Organisationsaktionen bleiben in den Modeldetails erreichbar.

Sichtbare Karten bestätigter Live-Räume bevorzugen das aktuelle Anbietervorschaubild und laden es ungefähr einmal pro Minute neu. Der bestehende Live-Bildabruf umgeht dabei den normalen Bild-Langzeitcache. Der Anbieter kann trotzdem dasselbe Bild zurückgeben. Ausgeblendete Karten und verborgene Browserseiten erzeugen keine zusätzlichen Bildabrufe. Selbst gewählte Cover bleiben erhalten; für ältere/offline beobachtete Räume gibt es weiterhin gespeicherte Bibliothekscover, die der Hintergrundlauf frühestens nach sechs Stunden erneut prüft. Das ist kein sekündliches Streambild; die zusätzliche Live-Vorschau bleibt gesondert einstellbar.


## Mindestqualität in Anbieteransichten

Unter **Seiten → Anbieter** steht **Video-Mindestqualität** mit Stufen von 240p bis 8K. „Ab 1080p“ enthält beispielsweise auch 1440p und 4K. Die Auswahl bleibt pro Anbieter gespeichert und gilt vor der lokalen Seiteneinteilung auch für nachgeladene Einträge. Mit „Alle Qualitäten“ oder „Filter zurücksetzen“ erscheinen wieder alle Medien. Bei aktivem Qualitätsfilter werden nur Videos mit passender veröffentlichter Auflösung angezeigt; unbekannte Werte werden gezählt und ausgeblendet. Ein allgemeines „HD“, ein Videotitel oder eine große Vorschaugrafik bestätigen keine genaue Auflösung. Die Auswahl filtert die geladenen Anbieter-Seiten, nicht den gesamten entfernten Katalog auf einmal.

XVideos-Qualitätsmarkierungen werden direkt aus der jeweils zugehörigen Kachel der ohnehin abgerufenen Übersicht übernommen. Dafür werden keine einzelnen Filme zusätzlich aufgelöst. Andere Anbieter verwenden ihre gelieferten Qualitäts- bzw. Größenangaben; ohne diese Angaben kann eine Mindestauflösung nicht bestätigt werden. Vorladen bleibt begrenzt und pausierbar.

## Statusfilter im Live-Bereich

Gruppen, Räume/Entdecken, Modelansichten und die gemeinsamen Filterdialoge verwenden dieselben Statusfarben wie Multicam: Grün für live, Rot für offline, Orange für privat und Grau für unbekannt. Die Auswahl enthält zusätzlich lesbare Symbole und Beschriftungen. In Gruppen lassen sich Offline und Privat getrennt auswählen.

Eine tatsächlich fortschreitende Wiedergabe aus Multicam, Singlecam oder einer Live-Vorschau bestätigt den Live-Status auch dann, wenn der Anbieter das Gruppenmitglied gerade nicht im öffentlichen Katalogausschnitt liefert. Die offenen normalen Live-Fenster melden diese Belege über den bestehenden gemeinsamen Kollektor; sie werden spätestens nach 95 Sekunden ohne neuen Beleg verworfen. Die öffentliche Katalogbeobachtung und ihre Zeit werden dabei nicht überschrieben. Eine fehlgeschlagene Verbindung oder das Verlassen einer Liste erzeugen keinen Offlinebeleg. Private Live-Sitzungen melden keine Wiedergabebelege.

## Reaktionszeit und lokaler Datenbestand

Die Live-Menüs zeigen ihren Ladezustand und bieten bei einem fehlgeschlagenen Einstieg **Live-Bereich erneut laden** direkt in der Ansicht an. Beim schnellen Wechsel dürfen verspätete Initialisierungen keine verlassene Liste oder zusätzliche Abfrageschleife starten. Persönliche Merkmale stehen bereits bei der ersten Modelsuche zur Verfügung. **Mein Nutzer** liest den vollständigen Bestand über kompakte, zusammengehörige Seiten; währenddessen wird der Fortschritt angezeigt. Ein unvollständiger Abruf ersetzt keinen zuvor vollständig gelesenen Bestand.

Beim Einstieg erscheint zunächst der gespeicherte Bestand. Nach einer Erfassungspause werden zuerst aktuelle öffentliche Startlisten gelesen, anschließend weitere Katalogseiten. Der gemeinsame Abruf läuft bei sichtbarem Live-Bereich; ausgeblendete Tabs geben ihre Erfassung frei. Anbieterfehler behalten ihre Wiederholungspause. Räume und Modelansichten prüfen während der ersten Minute alle fünf Sekunden, danach alle 15 Sekunden auf geänderte lokale Daten. Die gemeinsame Veröffentlichung bündelt Änderungen bis zu 20 Sekunden. Eine Mausvorschau verhindert diese Prüfung nicht. Archivierte Einträge ohne frische Beobachtung bleiben unbekannt; der gesamte historische Bestand wird nicht als gleichzeitig live bestätigt.

Statistik und Speicherübersicht zeigen die Bibliotheksdaten sofort und ermitteln große Verzeichnisgrößen im Hintergrund. Währenddessen steht bei noch unbekannten Werten „Wird gezählt“. Fertige Größen erscheinen automatisch. Ein kurzer gespeicherter Zählstand vermeidet wiederholte vollständige Festplattenläufe.

Große Star-Finder-Quelllisten verwenden einen vollständigen kompakten Listenstand, der während einer Aktualisierung sichtbar bleibt und nach einem Serverneustart wiederverwendet wird. Die Erneuerung läuft gebündelt im Hintergrund. Lokale Filter bleiben auch bei pausierten externen Abrufen verfügbar; ihre Optionen werden beim Öffnen der jeweiligen Gruppe aufgebaut. Die externe Hintergrundpause wird dadurch nicht aufgehoben.

Verlassene Suchen und Profilansichten beenden ihre Fortschrittsabfragen. Die Oberfläche prüft ihre Dateien beim Laden auf Änderungen und überträgt große Textantworten komprimiert. Bei einem bereits geöffneten alten Tab einmal Strg + F5 verwenden.


### Ladeverhalten und Playerprozesse

Anbieterlisten starten unabhängig vom Abruf ihrer Sortieroptionen. Ein späteres Ergebnis darf einen anderen inzwischen gewählten Anbieter nicht verändern. Beim Nachladen bleiben unveränderte sichtbare Videokacheln und ihre Vorschauen erhalten. Multicam beendet auch einen noch nicht abgeschlossenen Einstieg beim Verlassen; Gruppenfilter verwenden vorbereitete Mitgliedermengen und wiederverwendete Ergebnisse.

Multitube übergibt Medien aus isolierten Anbieterprozessen an den dauerhaften Medienzugang, statt kurzlebige Hilfsserveradressen weiterzugeben. HLS-Player starten nach dem Manifest. Startdateien und kleine Navigationsabrufe besitzen eine eigene begrenzte Serverreserve neben den normalen Abrufen. Das beschleunigt und stabilisiert lokale Abläufe; externe Anbieter und die Internetverbindung bestimmen weiterhin einen Teil der Streamstartzeit.


### Downloads und Offline-Videos

Tube-Videos lassen sich über „Download“ mit Qualität und Zielordner speichern. „Downloads“ zeigt Fortschritt, Abbrechen/Fortsetzen und bei fertigen Dateien „Offline abspielen“. „Offline“ liest die gewählten Downloadordner sowie vorhandene Offline-Ordner des Addons ohne Listen-Langzeitcache. Unfertige Dateien bleiben verborgen. Lokale Videos werden mit Byte-Bereichen vom getrennten Medienserver geladen; Pfade außerhalb dieser Ordner sind gesperrt.

Ohne FFmpeg werden einfache, abgeschlossene HLS-Streams weiterhin als TS gespeichert. Die Offline-Wiedergabe verwendet dafür eine lokale Playlist und den mitgelieferten HLS-Decoder (unverändert Version 1.5.15, Lizenzdateien unter static/hls.*.txt). Zum Abspielen dieser Downloads ist damit kein CDN-Abruf erforderlich. Browserunterstützung des jeweiligen Video-/Audiocodecs bleibt erforderlich; der Dienst muss lokal laufen.


In der Live-Singlecam stehen über dem Player die Regler „Playergröße %“ (20–150) und „Maximale Breite %“ (25–100). Sie gelten für alle sechs Plattformen, ändern die vorhandene Playerfläche unmittelbar und speichern die Auswahl. „Größe zurücksetzen“ stellt das vollständige Bild im Fenster wieder her. Bildzoom, Ton und Streamverbindung bleiben beim Verstellen erhalten. Die vorhandenen Größendialoge verwenden dieselben Werte.


Die Offline-Ansicht zeigt außerdem die Dateigröße pro Video, die Gesamtbelegung jedes eingerichteten Downloadordners einschließlich Unterordnern und die belegte/freie Kapazität jedes zugehörigen Laufwerks. Überlappende Ordner werden in der Gesamtsumme nicht doppelt gezählt. Größere Ordner werden im Hintergrund vermessen; „Speicherübersicht aktualisieren“ stößt eine neue Messung an. Explorer-Buttons öffnen den ausgewählten Ordner direkt.

Sichtbare Offline-Kacheln erzeugen ihre Vorschaubilder aus dem gespeicherten Video, höchstens eine gleichzeitig. Bis zu 200 Poster bleiben im lokalen Browsercache; geänderte Dateien erhalten neue Cachekennungen. Beim Darüberfahren läuft genau eine stumme lokale Videovorschau. Beim Verlassen der Kachel, Wechsel des Bereichs oder Verbergen des Tabs wird der Vorschauplayer freigegeben. Die erste Posterberechnung kann je nach Datei und Codec kurz dauern.
