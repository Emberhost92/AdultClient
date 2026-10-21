# Star Finder und Profilpflege – 18.10.2026

## Bedienung

Der Star Finder öffnet Profile innerhalb seines eigenen Menüs. Die lokale Suche lädt keine Anbieterseiten; eine Videosuche ist eine eigene ausdrückliche Aktion. Merkmale, Datenumfang und Profilherkunft lassen sich kombinieren. Benannte Filteransichten, Karten-/Listendarstellung, Seitensprung und zusätzliche Sortierungen nach Bildern, Ergänzungsdatum und Neuzugang sind verfügbar.

Ein Profil hat die Bereiche Übersicht, Bilder, Fakten, Zahlen & Filme, Quellen & Abweichungen und Meine Notizen. Die Biografieauswahl erhält Originaltexte und deutsche Fassungen. Fakten haben Quelle und Abrufdatum. Unterschiedliche Quellenwerte bleiben getrennt; gleichwertige metrische Größen und Datumsformate werden für den Vergleich normalisiert. „7 von 7 Datenbereichen“ bedeutet vorhandene Bereiche, keine vollständig recherchierte Person. Bibliotheksfilme, Szenenzahlen eines Anbieters und dessen Bewertungen sind unterschiedliche Bezugsgrößen.

Die Galerie lädt jeweils 24 Einträge. Vorschauen sind verkleinert, der Betrachter lädt die Originaldatei mit den nötigen Quellheaders. Er unterstützt Weiterblättern über die Seitengrenze, Zoom, 1:1, Drehen, Spiegeln, Vollbild und Diashow. Bilder lassen sich als eigenes Cover übernehmen; der Upload vom PC und das Zurücksetzen bleiben verfügbar. Quellen-, Urheber- und Lizenzangaben werden angezeigt, soweit veröffentlicht.

Notizen haben lokale Entwürfe und serverseitige Revisionen. Gleichzeitiges Speichern in zwei Fenstern meldet einen Konflikt. Auch während einer langsamen Speicherung neu eingetippter Text bleibt als Entwurf erhalten. Der JSON-Profilexport lässt persönliche Notizen standardmäßig aus; er ist kein vollständiges Datenbank-/Bildarchiv.

Unter **Einstellungen → Sprache & Models** liegen die Aktualisierungsläufe. Einzelne Läufe oder alle gemeinsam können pausieren, fortsetzen oder fällige Arbeit prüfen. Hintergrundtempo, Prüfintervall und Galerie-Vorlauf werden sofort dauerhaft übernommen. Laufkarten bleiben bei der Statusaktualisierung erhalten. „Geprüft“, erfolgreiche Übersetzungen und offene Versuche sind getrennte Zahlen. Bereits laufende Antworten dürfen beim Pausieren noch fertig werden. Explizit angeforderte einzelne Profilabrufe bleiben unabhängig von der Pause der automatischen Läufe möglich.

Unter **Speicher & Extras** werden SQLite einschließlich WAL und Star-Vorschauen mitgezählt. Die Profilbibliothek ist dauerhaft; die bisher wirkungslose „behalten“-Checkbox für Stars wird nicht mehr angeboten. Das ausdrückliche Leeren entfernt Zusatzprofile und deren Übersetzungen; Notizen, gespeicherte externe Quellenbelege, Namen und eigene Cover bleiben erhalten. Vorschaubilder leeren umfasst beide Bildcache-Verzeichnisse.

## Daten und Wiederaufnahme

- `star_store.py`: `profile/star_data.sqlite3`, SQLite/WAL, vollständige Transaktionen. Profile, Übersetzungen und Personen werden einzeln geändert. Metadaten, Einstellungen, Notizen und Quellantworten werden getrennt gespeichert. Unbekannte zusätzliche Legacy-Metadaten bleiben erhalten.
- Die erste Übernahme liest `star_extra.json` vollständig und legt `star_extra.json.before-sqlite.bak` an. Die ursprüngliche JSON-Datei wird anschließend nicht weiter beschrieben. Ungültiges JSON erzeugt einen Fehler statt einer leeren Ersatzbibliothek. Für neue Sicherungen SQLite verwenden; bei laufendem Server mit der SQLite-Backup-Funktion, nicht ausschließlich die alte JSON-Datei kopieren.
- Erfolgreiche Profile/Übersetzungen werden nicht mehr durch frühere Mengenbegrenzungen entfernt. Änderungen werden spätestens beim nächsten Hintergrund-Flush gesichert; vor einem späteren Cursorstand werden die zugehörigen Ergebnisse verbindlich geschrieben. Der Serverneustart sichert ebenfalls den aktuellen Stand.
- Profil-/Bildläufe nehmen an stabilen Kennungen wieder auf. Die Namenssuche nutzt `star_discovery.py`: jede Sitemap-Adresse hat einen eigenen dauerhaften Zustand, inklusive Wiederholungszeit. Unterbrochene Aufgaben werden erneut aufgenommen, fertige Adressen bleiben fertig. Neue Einträge und geänderte `lastmod`-Werte werden ergänzt. Fehlende Profile werden später erneut geprüft, vorübergehende Fehler mit wachsendem Abstand.
- Der veröffentlichte Babepedia-Sitemap-Index kann neue `sitemapmain*.xml`-Listen ergänzen. Wenn der Index nicht erreichbar ist, bleibt die bekannte Liste erhalten. Ein neuer XML-Download wird vor dem Austausch vollständig geprüft; bei Quellfehlern kann die letzte vollständige lokale Liste weiterverwendet werden.
- Übersetzungen sichern erfolgreiche Textabschnitte und Teilresultate. Der kürzere MyMemory-Ersatzweg verarbeitet den gesamten Text in UTF-8-gerechten Teilen. Fehler werden nicht als erfolgreiche Übersetzungen gezählt; ein Wiederanlauf überspringt bereits erfolgreiche Arbeit.

## Quellen

Die vorhandenen Verbindungen zu Babepedia, FreeOnes, IAFD, Grokipedia und AnalVids bleiben bestehen. Neue Quellfakten und ergänzende Originalbiografien behalten ihren eigenen Herkunftsnachweis. Ein fehlgeschlagener neuer Abruf überschreibt keine vorher erfolgreichen Angaben. Historische Datensätze ohne Einzelbelege können nachträglich keinen erfundenen Herkunfts- oder Aktualitätsnachweis erhalten.

`star_sources.py` ergänzt:

| Quelle | Umsetzung | Voraussetzung und Grenze |
|---|---|---|
| Wikidata | Namen/Aliasse, Geburtsangaben, öffentliche berufliche Fakten, Auszeichnungen, Karriere, offizielle Website | Ohne Schlüssel. Zuordnung über Namen und passende Geburtsangabe bzw. bereits bestätigte Quell-ID. Mehrdeutige Treffer werden nicht zusammengeführt. |
| Wikipedia | Deutsche Einleitung bevorzugt, sonst englisches Original mit zusätzlicher gespeicherter Übersetzungsmöglichkeit | Nur zum bestätigten Wikidata-Eintrag verlinkte Artikel. |
| Wikimedia Commons | Explizites Porträt `P18` und weitere Dateien mit `depicts/P180` für dieselbe bestätigte Person; weitere Seiten auf Anforderung | Keine beliebige Namens-Bildersuche. Originaladresse, Bildseite, Urheber und Lizenz, soweit vorhanden. |
| ThePornDB | Performer-Suche, Zusatzfakten, Biografie, Porträts und veröffentlichte Links | Optionaler eigener API-Schlüssel in `AH_TPDB_KEY` im Serverprozess. Es wird kein Konto erstellt. Ohne Schlüssel bleibt die Quelle inaktiv. |
| StashDB | Aktive lesende GraphQL-Anbindung für Profile, vollständige Szenenseiten, Tags und Quellkategorien | Eigener Schlüssel unter „Aktualisierungen & Quellen“; auf diesem PC verbunden. |
| FansDB | Derselbe vorbereitete Adapter mit getrennten Schlüsseln, Daten und Fortschritt | Eigener FansDB-Schlüssel fehlt noch; deshalb bislang nur synthetisch geprüft. |

Der Lauf „Fakten & Bilder“ prüft zusätzliche Quellen für den gesamten bekannten Profilbestand. Er setzt keinen vorherigen manuellen Profilaufruf voraus. Erfolgreiche Quellen werden entsprechend dem Intervall, mindestens täglich, erneut geprüft; fehlende oder mehrdeutige Zuordnungen nach sieben Tagen. Vorübergehende Quellfehler bleiben wiederholbar. Neue Namen kommen aus der Sitemap-Pflege und dem AnalVids-Katalog; außerdem gibt es eine ausdrücklich gestartete externe Namenssuche. Neue englische Zusatztexte werden in die gespeicherte Übersetzungsarbeit aufgenommen.

Öffentliche Datenbanken decken nicht jede Person und jedes gewünschte Feld ab. Fehlende Angaben bleiben unbekannt. Aus Quellen werden keine privaten Kontaktdaten oder zusätzlichen unbelegten Aussagen abgeleitet. Eine Quellensperre, ein API-Limit oder fehlender Zugang lässt sich durch höhere lokale Parallelität nicht zuverlässig beheben. Es gibt keine CAPTCHA-, Login- oder Zugriffssperren-Umgehung.

Offizielle Schnittstellenreferenzen:

- [Wikibase API](https://www.mediawiki.org/wiki/Wikibase/API), [Wikidata Datenzugriff](https://www.wikidata.org/wiki/Help:Linked_Data_Interface)
- [MediaWiki imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo), [API-Suche](https://www.mediawiki.org/wiki/API:Search/en), [Commons depicts-Suche](https://commons.wikimedia.org/wiki/Template:Search_link_haswbs_P180/doc)
- [ThePornDB-Dokumentation](https://api.theporndb.net/docs), [OpenAPI-Spezifikation](https://api.theporndb.net/specs?openapi.json)
- [Stash-Box-Quellen einschließlich StashDB/FansDB](https://docs.stashapp.cc/metadata-sources/stash-box-instances/)
- [Babepedia robots.txt](https://www.babepedia.com/robots.txt) veröffentlicht den Sitemap-Index. Dessen direkter Testabruf wurde mit HTTP 403 abgelehnt; deshalb bleibt der Rückfall auf bekannte lokale Listen wichtig.

## Leistung und technische Grenzen

### StashDB/FansDB – Szenen und Inhalts-Tags (19.10.2026)

`star_stashbox.py` liest ausschließlich `https://stashdb.org/graphql` bzw. `https://fansdb.cc/graphql` mit `ApiKey`-Header. Schlüssel liegen getrennt von den normalen Einstellungen in `profile/star_source_credentials.json`, unter Windows mit benutzergebundener DPAPI verschlüsselt. Die Oberfläche gibt gespeicherte Schlüssel niemals zurück. Der Verbindungstest erfolgt vor dem Ersatz eines bestehenden Schlüssels. Authentifizierte API-POSTs verfolgen keine Redirects.

Ein eigener Hintergrundlauf „StashDB & FansDB · Szenen und Tags“ prüft den lokalen Profilbestand. Geöffnete Profile erhalten Vorrang. Die Zuordnung benötigt passende Namen/Aliasse und Geburtsangaben oder einen übereinstimmenden personenspezifischen Quellenlink. Mehrdeutige Kandidaten bleiben ohne Szenenzuordnung, bis der Nutzer einen angebotenen Treffer ausdrücklich bestätigt.

Szenen werden seitenweise bis zum veröffentlichten Gesamtbestand gelesen. Gespeichert werden die tatsächliche Performer-ID, Titel, Studio, Veröffentlichungsdatum, Laufzeit, Besetzung, originale Tags einschließlich Quellkategorien, Quellen-URL und Abrufzeit. Seiteninhalt und nächster Seitenstand werden gemeinsam geschrieben. Unterbrochene Seiten werden wiederholt. Bei einer erneuten Recherche bleiben alte Szenen bis zum erfolgreichen Abschluss der ganzen Runde erhalten. Fehler, fehlende Treffer und Mehrdeutigkeiten bleiben unterscheidbar und werden später erneut geprüft.

Der Profilreiter **Szenen & Inhalts-Tags** zeigt den Quellenstand mit gespeicherter/erwarteter Szenenzahl, sämtliche Tags mit Szenenzahlen, Tagsuche, Quellkategorien und durchblätterbare Szenenbelege. Ein Tagklick zeigt seine Szenen. Quellkategorien sind veröffentlichte Taggruppen, keine geratenen Filmgenres. Szenentags beziehen sich auf die Szene insgesamt und belegen nicht automatisch die Handlungen oder persönlichen Vorlieben jeder einzelnen Person. Szenen ohne Tags bleiben sichtbar.

Der Katalogfilter **Inhalts-Tags aus Szenen** verwendet ausschließlich bestätigte Szenenzuordnungen. **Profil-Tags** bleiben getrennt und werden jetzt auch in der Profilübersicht angezeigt. **Kategorien (Filme & Szenen)** berücksichtigt vorhandene belegte Filmkategorien sowie die ausdrücklich bezeichneten Quellkategorien. Die erste Recherche ergänzt die Filter schrittweise. Die ältere Angabe weiter unten, dass noch keine Kategorien vorlagen, dokumentiert den Stand vor dieser Anbindung.

Automatische Regressionen prüfen mehrseitige Wiederaufnahme nach Fehler/Neustart, Dublettenfreiheit, abweichende Besetzung, mehrdeutige Personen/manuelle Bestätigung, unvollständige Seiten, leere Quellbestände, Erhalt bestehender Belege, getrennte FansDB-Herkunft, tatsächliche Filtertreffer/Ausschlüsse, GraphQL-Fehler trotz HTTP 200 und den Schlüsselschutz. FansDB verwendet denselben geprüften Vertrag; ein echter FansDB-Test benötigt dessen eigenen Schlüssel.

Echter StashDB-Test: Angela White wurde anhand der vorhandenen Geburtsangabe zugeordnet. Alle 1.065 veröffentlichten Szenen wurden über mehrere Seiten eingelesen; daraus sind 974 unterschiedliche Quelltags gespeichert. Das ist eine Momentaufnahme des Quellbestands, keine Vollständigkeitszusage für die gesamte Karriere oder alle anderen Profile.

Abschlussprüfung: 64 Python-Regressionen und fünf JavaScript-Prüfungen bestanden. Im echten Browser lieferte der Tag „4K Available“ 150 zugehörige Szenen; die zweite Belegseite enthielt andere Szenen. Das Öffnen der Original-Tags funktionierte. Der Katalogeinschluss enthielt das geprüfte Profil, der Ausschluss entfernte es; anschließend wurden beide Testregeln zurückgenommen. Nach dem Serverneustart waren Quelle, 1.065 Szenen, 974 Tags und 28 Quellkategorien weiterhin vorhanden, und der Hintergrundlauf wurde fortgesetzt. Der frühe Direktsprung zur Quellenverwaltung wurde nach einem Neuladen ebenfalls geprüft. Ein Bildschirmnachweis liegt unter `../output/star-finder/stashdb-verbunden.png`.

`star_runtime.py` begrenzt gleichzeitige Metadatenabrufe auf 2/4/6 und hält zusätzlich Abstand zwischen Abrufen derselben Quelle. Gleiche Anfragen werden zusammengeführt. 429/503 und API-Auslastungsantworten bekommen Quellpausen. Ein 404 oder eine gesperrte Sitemap betrifft die jeweilige Adresse. HTTP-200-API-Fehler, insbesondere Wikidata `maxlag`, werden aus dem Erfolgscache entfernt.

Große HTTP-Antworten werden komprimiert zwischengespeichert; der HTTP-Antwortcache ist auf ungefähr 256 MiB Nutzinhalt begrenzt. Gespeicherte Quellbelege/Notizen sind davon getrennt. Vorschauen werden mit maximal vier gleichzeitigen Bildverarbeitungen erzeugt. Vorschauadressen sind wiederverwendbar und getrennt von den Wiedergabetokens; auch große Galerien verdrängen keine laufende Wiedergabe. Der Vorschaucache wird bei weiterer Nutzung auf ungefähr 1 GiB begrenzt. SQLite kann freie Seiten nach Löschungen intern weiterverwenden; die Dateigröße schrumpft dadurch nicht sofort.

Eine vollständige erste Online-Recherche kann trotz dieser Verbesserungen lange dauern, abhängig von Quellantworten und deren Limits. Sie läuft gespeichert im Hintergrund. Prozentanzeigen beschreiben einen Durchlauf, keine Garantie, dass alle gewünschten Angaben öffentlich verfügbar sind.

### Vollständige Quellenansicht und Modellfilter (19.10.2026)

Der zusätzliche Profilreiter **StashDB & FansDB** zeigt die gespeicherten öffentlichen Modellangaben je Quelle: Merkmale, weitere Namen, Szenen- und Bilderzahlen, alle Studiozuordnungen mit Szenenzahlen, veröffentlichte Links sowie Erstellungs-/Änderungszeit. Bilder öffnen die vorhandene Profilgalerie. Die Szenenbelege enthalten außerdem Beschreibung, Produktionsdatum, Regie, Szenencode, übergeordnetes Studio/Netzwerk, Links und Bildverweise mit Abmessungen, soweit die Quelle diese Angaben liefert. Fehlende Quellangaben werden nicht ergänzt oder geraten.

Die Filter umfassen jetzt auch Studios, Netzwerke, Regie, verbundene Modellquellen und verfügbare Quellmerkmale wie Land, Herkunft, Geschlecht, Cup, Geburtsjahr, Größe, Karrierejahre, Tätowierungen und Piercings. Ein Klick auf **Modelle** neben einem Inhalts-Tag oder auf ein Studio öffnet den Katalog mit einer eigenen passenden Regel und entfernt die vorherige Namenssuche und andere Einschränkungen. Tagklicks zeigen weiterhin Szenen; die zusätzliche Kategorienauswahl grenzt die Tags im Profil ein. Ein-/Ausschluss, UND/ODER und gespeicherte Ansichten bleiben verwendbar.

Schema 2 ergänzt bereits recherchierte Profile schrittweise im bestehenden Hintergrundlauf. Bis zum vollständig abgeschlossenen erneuten Szenenabruf bleiben vorhandene Belege erhalten. Ein eindeutig passender Hauptname mit identischem vollständigem Geburtsdatum hat bei der Zuordnung Vorrang vor schwächeren Alias-/Jahrestreffern; gleich starke widersprüchliche Kandidaten bleiben mehrdeutig.

Echtprüfung mit Mia Malkova: 580/580 Szenen, 694 unterschiedliche Tags, 28 Quellkategorien, 194 Studiozuordnungen und 43 Bilder aus StashDB. Die neue Quellenansicht und der Sprung vom Studio in den Katalog funktionieren. „Modelle“ beim Tag „4K Available“ lieferte 448 Profile einschließlich Mia Malkova; dessen Ausschluss zusammen mit ihrer Namenssuche lieferte null Profile. Danach wurden die Testregeln entfernt. Die Kategorie „Misc“ ließ den passenden Tag sichtbar; geöffnete Szenendetails zeigten Beschreibung, Code, Netzwerk, Original-Link und Bildabmessungen. Ein Bildschirmnachweis liegt unter `../output/star-finder/mia-stashdb-profil.png`. Dies ist der zum Prüfzeitpunkt vorhandene Bestand; die weitere Recherche ergänzt andere Profile. 67 Python- und sechs JavaScript-Regressionen bestanden. FansDB bleibt bis zur Einrichtung eines eigenen Schlüssels unverbunden.

### Gesamte Quellkataloge statt nur vorhandener Stars (19.10.2026)

`star_library.py` übernimmt nun die veröffentlichten Personenkataloge von StashDB, FansDB und ThePornDB sowie den Data18-Katalog und den abgegrenzten Wikidata-Bestand mit Beruf Q488111. FansDB/ThePornDB starten erst mit eigenem Schlüssel; Data18 verwendet die vorhandene lokale Freigabe aus dem getrennten Metadatenadapter. Babepedia-Sitemaps und AnalVids laufen weiterhin über ihre eigenen Katalogläufe. FreeOnes, IAFD und Grokipedia ergänzen bekannte beziehungsweise bestätigte Profile; ein vollständiger Quellkatalog dieser drei Quellen ist weiterhin offen und wird ausdrücklich so im Dashboard angezeigt. Eine blockierte Quelle gilt nicht als erfolgreich synchronisiert.

Jeder Quellkatalog besitzt einen eigenen Hintergrundarbeiter und dauerhaft gespeicherte Seitenstände. Neue Personen erhalten sofort einen Bibliothekseintrag und verfügbare Bildadressen. Bestehende Personen werden ausschließlich über bestätigte Personenlinks oder eindeutigen vollständigen Namen plus vollständigem Geburtsdatum zugeordnet. Andernfalls bleibt die stabile Kennung `src:<quelle>:<quellkennung>` eigenständig; auch Namensvetter müssen sichtbar bleiben. Ein fehlendes `src:`-Profil darf nicht nach Namen auf eine andere Person zurückfallen. Quellenlinks werden in beiden Richtungen berücksichtigt, beispielsweise ein von StashDB veröffentlichter Data18-Personenlink.

StashDB/FansDB bekommen zusätzlich eine Änderungsrunde über UPDATED_AT, spätestens alle sechs Stunden, auch während eines langen Erstimports. Die vollständigen Katalogrunden wiederholen sich nach dem eingestellten Prüfintervall. Der Erstbestand von StashDB meldete 112.686 Profile, Data18 22.333. Das sind veröffentlichte Quellgrößen, keine Anzahl bereits vollständig zusammengeführter oder ergänzter Personen. Es gibt keinen pauschalen Erfolgszustand für alle Quellen zusammen.

Die echte StashDB-Sortierung CREATED_AT lieferte in zwei aufeinanderfolgenden 100er-Seiten 74 beziehungsweise 67 bereits gesehene IDs. Der Kataloglauf verwendet deshalb die live geprüfte Namenssortierung, zählt eindeutige Quell-IDs und überprüft bei Lücken von der anderen Richtung im selben Durchlauf weiter. Quelländerungen, doppelte Seiten und fehlende Antworten dürfen keinen falschen Abschluss erzeugen. Daten und Seitenstand werden gemeinsam gespeichert; vorhandene Personen/Bilder bleiben bei Wiederholungen erhalten.

Ein eigener Lauf **Alle Stars · Quellen & vollständige Galerien** ergänzt sowohl neue Quellprofile als auch den gesamten bisherigen Bestand. Neue und bisherige Personen wechseln sich ab, damit Neuzugänge nicht hinter dem kompletten Altbestand warten. Weitere veröffentlichte Commons- und FreeOnes-Galerieseiten werden dauerhaft nachgeladen. Die früheren Grenzen von 60 FreeOnes-Alben, 2.400 Bildern und 96 Babepedia-Bildadressen sind entfernt. Seitenschleifen werden über besuchte Seiten verhindert; fehlgeschlagene Seiten bleiben offen. Quellenporträts und gespeicherte Szenenbilder sind mit Herkunft über die Profilgalerie erreichbar. Große Galerien bleiben seitenweise bedienbar. Originalbilder werden bei Bedarf geladen; die Vorschaucache-Begrenzung bleibt erhalten.

`star_models_sources.py` bindet den vorhandenen Data18-/IAFD-Metadatenadapter ein. Er verwendet bestätigte Personen-IDs/Links und öffnet im Hintergrund keinen Browser. Die Quellenansicht zeigt auch dessen gespeicherte Film-/Szenentitel, Studios, Tags, Mengenprüfungen, Merkmale und Porträts. Titelsuche und Nachladen haben keine feste Gesamtobergrenze. Tags und Studios fließen in die Modellfilter ein; unvollständige Abrufe bleiben erkennbar und werden erneut versucht. Erfolgreich gespeicherte ältere Titel/Bilder gehen durch eine unvollständige Antwort nicht verloren.

Unter realer Importlast wurden langsame Katalogabfragen gefunden: Ein fehlender Namensindex verursachte wiederholte vollständige Tabellenscans. Hinzu kam ein vollständiger Neuaufbau der Filterprojektion nach praktisch jeder Importseite. Der Namensindex ist ergänzt; normalisierte wiederkehrende Werte werden wiederverwendet. Große Filterübersichten werden im Hintergrund erneuert und können bis zu 30 Sekunden hinter dem Import liegen. Explizite Filter verlangen eine aktuelle Projektion. Importarbeiter warten nicht mehr auf deren vollständigen Aufbau. Prüfungen vor Abschluss: Status-/Suchabfragen unter aktivem Import wieder im Sekundenbereich, neue Data18-Person über Katalog und Profil erreichbar, eigenes Porträt über die lokale Vorschau mit HTTP 200 geladen. Ein neues StashDB-Profil zeigte 77 Szenen und zunächst 81 Bilder, davon vier Porträts; im Browser waren alle ersten 24 Bilder geladen, danach 48 Bilder nachgeladen, während der Bestand weiter wuchs.

Der Import und die Aktualisierung laufen, solange die lokale Anwendung gestartet ist. Nach einem Neustart werden gespeicherte Aufgaben fortgesetzt. Ausgeschalteter PC, fehlende Schlüssel, externe Sperren, unveröffentlichte Angaben und nicht angebundene Gesamtkataloge werden damit nicht aufgehoben. Der Erstimport ist zum Abschluss dieser Umsetzung weiterhin aktiv. 100 Python- und sechs JavaScript-Prüfungen bestanden. Nach dem Neustart waren über 81.000 Quellprofile und 229.000 Bildadressen vorhanden; Katalogfortschritt und bestehende Bilder blieben erhalten. Der praktische Bildweg wurde zusätzlich unabhängig mit einem neu übernommenen Data18-Profil bis zur geladenen lokalen WebP-Vorschau geprüft.

### FreeOnes und Grokipedia als eigene Profilquellen (19.10.2026)

`star_reference_sources.py` ergänzt beide Quellen im gemeinsamen automatischen
Quellenlauf. Sie sind unter **Aktualisierungen & Quellen** aufgeführt. In einem
Profil stehen zusätzliche Biografien unter **Übersicht → Biografiequelle**,
Merkmale unter **Fakten** und Herkunft/Warnungen unter **Quellen & Abweichungen**.
Grokipedia-Literaturverweise lassen sich dort aufklappen. Das ist eine Ergänzung
zu bestehenden Profilen, kein neuer vollständiger Personenkatalog.

FreeOnes liefert veröffentlichte strukturierte Merkmale, weitere Namen,
Karriere-/Auszeichnungsnotizen und eindeutig beschriftete Profilporträts. Die
bestehende gesonderte Galeriepflege bleibt erhalten. Grokipedia liefert die
Einleitung des Artikels, ausdrücklich genannte Geburtsdaten und Literaturverweise.
Seine KI-verfassten Texte bleiben getrennt gekennzeichnet; Titelgrafiken werden
nicht als Personenfoto übernommen. Literaturverweise begründen keine Zuordnung
zu anderen Personenquellen.

Zuordnung erfordert einen veröffentlichten eindeutigen Personenlink bzw. eine
bestätigte Quellenkennung oder eine passende Namens- und Geburtsangabe. Ein
aus dem Namen erzeugter Abrufpfad allein genügt nicht. Andere Geburtstage,
Namenskonflikte, fremde Weiterleitungen und unbekannte Seitenstrukturen führen
zu einem offenen Quellenstatus. Unplausible Größen/Gewichte werden als
Quellwarnung mit Originalwert erhalten und nicht als Merkmal übernommen.

Die Abrufe verwenden den bestehenden lokalen HTTP-Cache (zwölf Stunden),
Quellenlimits und gespeicherte Wiederholungszustände. Es ist kein zusätzlicher
Schlüssel und kein Browser für diese beiden aktuellen HTML-Abrufe nötig.
Live geprüft mit Mia Malkova: FreeOnes 25 plausible Merkmalsangaben, drei Aliase
und ein Porträt; Grokipedia 1.466 Zeichen Einleitung und 37 Literaturverweise.
Die von FreeOnes gemeldeten 12 cm Körpergröße wurden ausdrücklich verworfen und
als Warnung erhalten. 17 neue Regressionen prüfen zusätzlich Cache,
Weiterleitungen, Zuordnung, Teilfehler und die Registrierung im Quellenlauf.
Nach dem Neustart sind beide Quellen im laufenden Server registriert. Der echte
Ablauf **Angaben ergänzen** speicherte beide Ergebnisse. Im Browser wurden die
Biografieauswahl, 80 Faktenzeilen des Testprofils einschließlich bisheriger
Quellen, die Größenwarnung und alle 37 aufklappbaren Literaturverweise geprüft.
Das neue FreeOnes-Porträt wird über die lokale Vorschau mit HTTP 200 image/webp
ausgeliefert. Gesamtprüfung: 117 Python- und sechs JavaScript-Tests bestanden.

## Prüfungen

Automatisch: Migration und exakter Inhaltserhalt, einzelne statt vollständige Schreibvorgänge, fehlgeschlagene Transaktionen, Cachekompression, stabile Wiederaufnahme, Sitemap-Neuzugänge/Änderungen/Unterbrechung, unvollständiges XML, Pausen, gespeicherte Optionen, Quellzuordnung einschließlich abweichendem vollständigem Geburtsdatum, Originaldatenstand aus dem Cache, API-200-Auslastungsfehler, adressbezogene Fehler, Commons-Fortsetzung, Filter/Sortierungen, vollständige Übersetzungsabschnitte, Übersetzungsfehler und Wiederaufnahme, gleichzeitige Notizrevisionen, Erhalt guter Quellwerte und Übersetzungen, große Galerien und Profilexport.

Praktisch im echten Browser mit synthetischen Profilen/Bildern und separatem temporärem Datenverzeichnis: Filteransicht speichern/wiederherstellen, Karten-/Listendarstellung, sofortiges Profilöffnen ohne Videosuche, Hintergrundergänzung, Faktenabweichungen, Bilder im Original 720×960 bzw. 1280×720, Weiterblättern von Bild 24 zu 25 mit automatischem Nachladen, Galerie-Nachladen, Cover setzen/zurücksetzen, Notizkonflikt zwischen zwei Schreibern, weiterer Entwurf während einer langsamen Speicherung, Einzel-/Gesamtpause, Einstellungen und schmale 420-Pixel-Ansicht. Ein veralteter Direktsprung in die parallel erneuerten Einstellungen wurde dabei gefunden und korrigiert.

Messung an einer ausschließlich temporären Kopie der echten JSON-Daten: 62,5 MiB, 22.583 Profile, 1.166 Übersetzungen, 25.105 zusätzliche Personen. Import 1,67 s; Median einer Änderung mit SQLite-Commit 6,88 ms, gegenüber 464,70 ms allein für die vollständige bisherige JSON-Serialisierung. Inhalt nach erneutem Öffnen geprüft. Echter Katalog mit 49.439 zusammengeführten Profilen: lokale warme Abfragen rund 187–338 ms, erste Abfrage einschließlich Import/Index ungefähr 2,78 s. Das sind lokale Messwerte, keine Garantie für die Dauer externer Abrufe.

Ein echter neutraler Testprofilabruf lieferte 20 Wikidata-Fakten, einen deutschen Wikipedia-Text und ein Commons-Porträt. Weitere Versuche meldeten Wikidata-Auslastung; sie wurden als Wiederholungszustand behandelt. Die erweiterte Commons-Suche und ThePornDB sind zusätzlich gegen synthetische API-Antworten geprüft. ThePornDB konnte ohne eigenen Schlüssel nicht live geprüft werden.

Wichtige Dateien: `star_store.py`, `star_runtime.py`, `star_sources.py`, `star_discovery.py`, `star_finder.py`, `static/star_finder.js`, `static/star_finder.css`, die gezielten Verbindungen in `server.py`/`static/app.html` sowie die Galerieanbindung in `media_library.py`/`static/media_library.js`. Live-Cam- und Multitube-Funktionen werden weiterhin von ihren eigenen Modulen verwaltet.

## Aktivierter Stand

Der abschließende Serverneustart war erfolgreich. Die echte Oberfläche liefert 49.439 Katalogprofile; Profil-, Bilder- und Job-Schnittstellen wurden nach dem Neustart erfolgreich geprüft. Der aktuelle Bestand enthält unter anderem 187.371 gespeicherte Bildadressen; die laufende Pflege ergänzt ihn weiter. Vor dem Neustart wurde zusätzlich eine konsistente Online-Sicherung der neuen SQLite-Datenbank mit erfolgreichem `quick_check` und den Job-Cursorn unter `../.backups/2026-10-18-star-finder-final/` angelegt. Die Tests nutzten eigene temporäre Bestände und separate Ports; der temporäre Browser und Testserver wurden beendet.

## Ein- und Ausschlussfilter

Unter „Merkmale, Quellen & Datenstand filtern“ gibt es getrennte Mehrfachauswahlen für Haarfarben, Tags und Filmkategorien. Zeigen kombiniert ausgewählte Werte standardmäßig mit ODER; optional müssen alle gewählten Werte vorhanden sein. Zwischen den drei Gruppen gilt UND. Ein passender Ausschluss entfernt das Profil immer. Unbekannte Angaben werden bei bloßen Ausschlüssen standardmäßig beibehalten; „Nur Profile mit Angabe“ und „Nur Profile ohne Angabe“ sind ausdrücklich wählbar. Aktive Regeln sind als einzeln entfernbare Chips sichtbar, werden lokal gespeichert und gehören zu benannten Filteransichten. Zurücksetzen und der eigene Löschknopf entfernen sie.

`star_filters.py` hält eine lokale, kurzzeitig zwischengespeicherte Merkmalsprojektion. Sie verwendet lokale Profilfelder, gespeicherte zusätzliche Haarangaben und belegte Filmkategorien aus eindeutig zugeordneter Besetzung. Tags werden nicht als Filmkategorien ausgegeben, Kategorien nicht aus Namen oder Filmtiteln geraten. Mehrdeutige Besetzungsaliasse erzeugen keine Zuordnung. Die Auswahl greift vor Trefferzählung und Seiteneinteilung auf den ganzen Bestand. Facettenzahlen zeigen den Gesamtbestand, nicht ausschließlich die aktuelle Ergebnisliste.

Beim geprüften echten Stand waren 12 Haarfarben und 129 Tags vorhanden, aber noch keine zugeordneten Filmkategorien. Die kompakte Filmbibliothek enthält bisher nur Titel, Jahr und Laufzeit. Neue gespeicherte Filmdetails können belegte Kategorien ergänzen. Bei älteren bereits gespeicherten Filmdetails werden höchstens zehn fehlende Kategoriedatensätze pro Serverlauf im Hintergrund nachgeprüft; eine Zugriffs-/Vorschaltseite wird nicht als Filmdetail übernommen. Navigationskategorien werden ausdrücklich ignoriert. Der tatsächliche Abruf eines vorhandenen Quellfilms führte auf eine Vorschaltseite; es wurden daraus keine Kategorien erfunden.

Geprüft: elf Python-Regressionen für Kombinationen, Ausschlussvorrang, unbekannte Werte, ungültige Regeln, Quellenzuordnung, Besetzungsaliasse, neue Filmdaten, echte Zählung/Seitenteilung und Filmparser. JavaScript prüft gespeicherte Regelkopien und deren Validierung. Der Browser prüfte kombinierte Filter (drei erwartete Testprofile), Speichern/Löschen/Wiederherstellen, dauerhafte Auswahl nach Neuladen, UND-Verknüpfung, Tastaturfokus und 420 Pixel Breite ohne horizontalen Überlauf. Warme echte Abfragen über knapp 50.000 Profile lagen im Test bei rund 200 ms.

Die Ein-/Ausblendfilter sind im laufenden Server aktiviert und nach dem Neustart über die echten Schnittstellen geprüft: 49.446 Profile insgesamt, 45.776 nach Ausschluss von blond; 15.702 mit und 33.744 ohne Haarangabe. Die Tag-Einschlussprüfung lieferte echte Treffer; die neue Filmkategorien-Zuordnung ist aktuell noch leer. Der separate Testserver wurde beendet.


Die Live-Modelbibliothek verwendet dieselbe Wikimedia-Anbindung seit 19.10.2026 auch für zusätzliche öffentliche Biografien. Direkte bestätigte Wikidata-IDs und ein Abruf nur von Text/Fakten vermeiden dort unnötige Galeriesuchen; die bisherigen Star-Finder-Aufrufe behalten ihr Verhalten. Bedienung, Zuordnungsregeln und Tests stehen in [LIVE_BIOGRAFIEN.md](LIVE_BIOGRAFIEN.md).


## Vollständiger Abruf eines geöffneten Profils (19.10.2026)

„Jetzt vollständig aktualisieren“ startet einen bevorzugten Einzelabruf mit zwei eigenen Arbeitsplätzen, ohne hinter der normalen Profilwarteschlange zu warten. Die gemeinsamen HTTP-Grenzen, Einzel-/Gesamtpausen und Quellenfehlerpausen gelten weiterhin. Er prüft Basisprofil/Babepedia, jede angebundene Profilquelle, alle Szenenseiten der verbundenen StashBox-Quellen, verfügbare Galerie-Fortsetzungen und vorhandene übersetzbare Texte. Erfolgreiche HTTP-Antworten werden für diesen Auftrag neu abgefragt; Fehlerpausen werden nicht umgangen. Gute gespeicherte Angaben bleiben bei Fehlern erhalten.

Der Balken misst abgeschlossene Prüfschritte. Szenen- und Galerieschritte zeigen zusätzlich laufende Seitenzahlen. 100 Prozent bedeutet, dass der Prüflauf beendet ist; fehlende Zugänge, uneindeutige Identitäten, Abrufsperren und Teilbestände werden separat ausgewiesen. Ein vollständiger Datenbestand wird bei offenen Quellen nicht behauptet. Bildadressen werden gesammelt; Originalbilder werden weiterhin bedarfsgesteuert geöffnet.

Mehrfachklicks starten keinen doppelten Vollabruf. Fortschritt wird unter `profile-refresh` gespeichert und beim erneuten Öffnen des Profils angezeigt. Nach einem Serverneustart wird ein unterbrochener Auftrag als unterbrochen markiert; ein erneuter Klick nutzt die bereits gespeicherten Daten. Der persönliche Notizentwurf wird beim Fortschrittspolling nicht überschrieben.

Geprüft: 131 Python- und 6 JavaScript-Prüfungen, einschließlich vollständiger Seitentraversierung, Priorität bei ausgelastetem Profilpool, Pause/Fortsetzen, Mehrfachklicks, Neustartstatus, frischem HTTP-Cache und Fehlerpausen. Echter Browserlauf an Alice Menezes: fünf StashDB-Szenen und 56 Inhalts-Tags gespeichert, sieben Bildadressen sichtbar; alle elf Schritte beendet mit ausdrücklich offenen bzw. nicht verbundenen Quellen.

## Turbo und Maximalmodus (19.10.2026)

Unter Einstellungen → Sprache & Models bietet das Hintergrundtempo zusätzlich Turbo und Maximal. Turbo erlaubt 12 zentrale HTTP-Abrufe, 4 Profilpflegen, 3 Szenenimporte und 4 Übersetzungsaufträge gleichzeitig. Maximal erlaubt 20 HTTP-Abrufe, 6 Profilpflegen, 4 Szenenimporte und 6 Übersetzungsaufträge; zusätzlich bis zu 8 bedarfsgesteuerte Profilaufträge. Die zentrale HTTP-Grenze gilt gemeinsam für diese Aufgaben. Data18/IAFD behalten ihre eigene Adapter-Drosselung.

Die Warteschlangen reservieren Einträge atomar. Übersetzungsfortschritt wird erst nach Abschluss eines begrenzten Stapels weitergesetzt; fehlgeschlagene Identitäten bleiben zur Wiederaufnahme gespeichert. Herabsetzen und Pausieren verhindern neue Aufgaben oberhalb der Grenze; begonnene Arbeit darf abschließen.

Turbo und Maximal verkürzen den Mindestabstand je Quelle gegenüber Zügig nicht weiter (0,3 Sekunden). Wartende Abrufe beachten neu gemeldete Quellensperren. Mehr Parallelität garantiert weder proportionalen Durchsatz noch volle CPU-Auslastung.

Maximal wurde auf dem geprüften PC mit 16 logischen Prozessoren und rund 16 GB RAM aktiviert, mit Galerie-Vorlauf 96 und unverändertem Prüfintervall. 124 Python- und 6 JavaScript-Tests bestanden; darunter parallele Reservierung von sechs Profilen und vier Szenenaufträgen sowie parallele Übersetzung mit Fehler und Wiederaufnahme. Mehrere unterschiedliche Profile und Szenenimporte wurden im laufenden Bestand gleichzeitig beobachtet.

## Gesamtpause für Leistung (19.10.2026)

Unter Einstellungen → Sprache & Models stoppen „Volle Leistung · alle Recherchen pausieren“ und „Recherchen fortsetzen“ gemeinsam die Star-Hintergrundpflege: Kataloge, Profilquellen einschließlich FreeOnes/Grokipedia, Szenen, Galerie-Erweiterung und Übersetzungen. Neue Profilaufträge bleiben in der begrenzten Warteschlange. Bereits begonnene Arbeit darf abschließen. Lokale Suche, gespeicherte Bilder und Wiedergabe bleiben bedienbar; Live-Statusaktualisierungen und ausdrücklich gestartete Videosuchen haben eigene Steuerungen. Dies ist keine Zusage von null CPU-Verbrauch.

Gesamtpause und Einzelpausen werden gespeichert. Fortsetzen entfernt ausschließlich die Gesamtpause. „Jetzt prüfen“ merkt während der Gesamtpause einen Lauf vor, hebt sie jedoch nicht auf. HTTP-Aufträge prüfen die Pause nach Wartezeiten auf Schlüssel, Quelltempo und Parallelplätze erneut; Pool-Aufträge prüfen sie vor der Ausführung. Filter-Hintergrundprojektionen und ergänzende Filmdaten warten ebenfalls.

Geprüft: 119 Python-Regressionen und 6 JavaScript-Prüfungen; echte Oberfläche mit Gesamtpause, acht pausierten Läufen und null aktiven zentralen HTTP-Abrufen. Die Bildschirmaufnahme scheiterte am Browser-Aufnahmedienst; die sichtbare Statusanzeige wurde über den Browser geprüft.
