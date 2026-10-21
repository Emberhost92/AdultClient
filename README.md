# Adult Client

Eine portable Windows-Oberfläche für Tube-Seiten, Live-Cams und den Star Finder mit separat aktualisierbarer Modelldatenbank.

A portable Windows interface for tube sites, live cams and the Star Finder, with an independently updatable model database.

**[Deutsch: Installation und Updates](#deutsch)** · **[English: Installation and updates](#english)**

## Downloads

**Aktuelle Programmversion / Current program version: 0.3.1-beta.1**  
**Modelldaten / Model data: 2026-10-21**

| Download | Inhalt / Contents | Größe / Size |
| --- | --- | --- |
| **[Windows-Komplett.zip](https://github.com/Emberhost92/AdultClient/releases/download/v0.3.1-beta.1/AdultClient-0.3.1-beta.1-Windows-Komplett.zip)** | Programm + Modelldaten / Program + model data | ca. / approx. 405 MB |
| **[Windows.zip](https://github.com/Emberhost92/AdultClient/releases/download/v0.3.1-beta.1/AdultClient-0.3.1-beta.1-Windows.zip)** | Nur das Programm / Program only | ca. / approx. 36 MB |
| **[star-data.sqlite3.gz](https://github.com/Emberhost92/AdultClient/releases/download/data-2026-10-21/star-data.sqlite3.gz)** | Separates Modelldatenpaket / Separate model data package | ca. / approx. 369 MB |
| **[star-data.sqlite3.json](https://github.com/Emberhost92/AdultClient/releases/download/data-2026-10-21/star-data.sqlite3.json)** | Beschreibung und Prüfsumme des Datenpakets / Data package metadata and checksum | kleiner als / less than 1 KB |

[Alle Veröffentlichungen / All releases](https://github.com/Emberhost92/AdultClient/releases) · [Aktuelles Programm-Release / Current program release](https://github.com/Emberhost92/AdultClient/releases/tag/v0.3.1-beta.1) · [Modelldaten-Release / Model data release](https://github.com/Emberhost92/AdultClient/releases/tag/data-2026-10-21)

## Deutsch

### 1. Voraussetzungen

- Windows 64 Bit mit .NET Framework 4, das auf aktuellen Windows-Versionen normalerweise vorhanden ist.
- Einen beschreibbaren Ordner, zum Beispiel `C:\AdultClient` oder einen Ordner unter „Dokumente“.
- Mehrere GB freien Speicherplatz: Das Modelldatenpaket wächst beim Entpacken auf etwa 1,6 GB. Für Downloads, Updates und Sicherungen wird zusätzlicher Platz benötigt.
- Internet für Live-Streams, Tube-Seiten, das Laden externer Bilder und Updates. Lokal gespeicherte Modelldaten bleiben ohne Internet durchsuchbar.

**Python und Kodi müssen nicht separat installiert werden.** Die benötigte Laufzeit ist enthalten. Die Oberfläche öffnet sich im Browser; das Programm läuft lokal auf deinem PC.

### 2. Empfohlen: Programm und Modelldaten gemeinsam installieren

1. Lade oben **Windows-Komplett.zip** herunter. Alternativ öffne das Programm-Release und klappe **Assets** auf.
2. Klicke im Windows-Explorer mit der rechten Maustaste auf die ZIP-Datei und wähle **Alle extrahieren…**.
3. Öffne den vollständig entpackten Programmordner.
4. Doppelklicke auf **`AdultClient.exe`**.
5. Warte beim ersten Start, bis die Modelldaten geprüft und entpackt sind. Danach öffnet sich die Oberfläche automatisch im Standardbrowser.

Es gibt keinen zusätzlichen Installationsassistenten. Starte die EXE **nicht direkt aus der ZIP-Datei**. Behalte die Unterordner neben der EXE bei; die EXE allein reicht nicht aus. Verwende einen beschreibbaren Ordner statt `C:\Programme`.

**Für diese Variante musst du das separate Modelldatenpaket nicht zusätzlich herunterladen.**

### 3. Alternative: Erst das Programm, dann die Modelldaten

Diese Variante ist praktisch, wenn du zunächst nur das kleine Programm herunterladen möchtest.

1. Lade **Windows.zip** herunter und entpacke die gesamte ZIP-Datei mit **Alle extrahieren…**.
2. Starte `AdultClient.exe`.
3. Öffne **Einstellungen → Updates & Modellbilder**.
4. Klicke auf **Nach Updates suchen**.
5. Klicke im Bereich **Modelldaten** auf **Modelldaten herunterladen** und warte, bis das Paket heruntergeladen und geprüft ist.
6. Klicke auf **Modelldaten übernehmen und neu starten**. Alternativ wird das vorbereitete Datenpaket beim nächsten normalen Programmstart übernommen.

Das Programm lädt dabei die passende Datendatei und ihre Prüfinformationen selbst. Du musst die beiden Daten-Dateien nicht von Hand zusammensuchen. Vor dem Import ist noch kein mitgelieferter Modellbestand installiert.

### 4. Alternative: Programm und Modelldaten von Hand zusammenstellen

Das ist auch geeignet, wenn du die Dateien auf einem anderen PC herunterladen und beispielsweise per USB-Stick übertragen möchtest.

1. Lade **Windows.zip** herunter und entpacke sie vollständig.
2. Lade zusätzlich **beide** Dateien aus dem Modelldaten-Release herunter: `star-data.sqlite3.gz` und `star-data.sqlite3.json`.
3. Lege beide Dateien **vor dem allerersten Start** in den Ordner `data` neben `AdultClient.exe`. Erstelle den Ordner, falls er noch nicht vorhanden ist.
4. Lass die Datendatei als `.gz` bestehen. Adult Client prüft und entpackt sie selbst.
5. Starte `AdultClient.exe` und warte auf die erste Datenübernahme.

Die Ordnerstruktur sieht dann so aus; weitere mitgelieferte Ordner und Dateien bleiben ebenfalls liegen:

```text
AdultClient/
├── AdultClient.exe
├── release.json
├── app/
├── runtime/
├── addon/
└── data/
    ├── star-data.sqlite3.gz
    └── star-data.sqlite3.json
```

**Bereits gestartet?** Wenn bereits eine lokale Datenbank angelegt wurde, importiert das Programm den Inhalt von `data` nicht erneut als Erstinstallation. Nutze dann den Download über **Einstellungen → Updates & Modellbilder**, wie in Abschnitt 3 beschrieben. Lösche dafür nicht deinen `userdata`-Ordner.

### 5. Programm und Modelldaten getrennt aktualisieren

Öffne **Einstellungen → Updates & Modellbilder → Nach Updates suchen**. Die installierte Programmversion und der Datenstand werden dort getrennt angezeigt.

| Was möchtest du aktualisieren? | Vorgehen |
| --- | --- |
| **Programm** | **Programmupdate herunterladen** → Prüfung abwarten → **Installieren und neu starten** |
| **Modelldaten** | **Modelldaten herunterladen** → Prüfung abwarten → **Modelldaten übernehmen und neu starten** |

- Aktiviere **Auch Betaversionen anbieten**, um die aktuellen Programm-Betas zu erhalten.
- Die Option **Automatisch beim Start und einmal täglich nach Updates suchen** informiert über verfügbare Updates. Herunterladen und Installieren startest du selbst per Button.
- Für ein Programmupdate musst du die große Modelldatenbank nicht erneut herunterladen. Ein Datenupdate tauscht umgekehrt nicht das Programm aus.
- Wenn beides bereitliegt, installiere zuerst das Programm und übernimm danach die Modelldaten über deren eigenen Neustartbutton.
- Eigene Einstellungen, API-Schlüssel, Cookies, Notizen, Favoriten, Verlauf und Downloads bleiben erhalten. Ein Programmupdate verwendet weiterhin deinen bisherigen `userdata`-Ordner.
- Ein GitHub-Konto ist für öffentliche Downloads und die Updatefunktion nicht erforderlich.

**Hinweis zur GitHub-Seite:** Programm- und Daten-Releases können unabhängig voneinander erscheinen. Ein als „Latest“ markiertes Release kann deshalb nur Modelldaten enthalten. Für die Erstinstallation wähle ausdrücklich das Programm-Release und die passende **Windows.zip** oder **Windows-Komplett.zip**. **Code → Download ZIP**, **Source code** und **Source.zip** sind Quellcode-Downloads und nicht das fertige Windows-Programm.

### 6. Sprache, Bilder und eigene Zugänge

- **Sprache:** Links im Menü über **Deutsch / English** wechseln. Die Oberfläche lässt sich umschalten; Namen, Tags, Biografien und andere Modelldaten behalten ihre gespeicherte Sprache.
- **Bilder:** Das Modelldatenpaket enthält Bildverweise, keine vollständige Offline-Fotosammlung. Bilder werden zunächst bei Bedarf aus dem Internet geladen. Unter **Einstellungen → Updates & Modellbilder → Alle Modellbilder offline laden / fortsetzen** kannst du sie zusätzlich speichern. Der Bilddownload lässt sich pausieren und fortsetzen und kann sehr viel Speicher benötigen. Nicht mehr erreichbare oder geschützte Bilder können fehlen.
- **Eigene Zugänge:** Persönliche API-Schlüssel und Website-Anmeldungen des Herausgebers werden nicht mitgeliefert. Manche Anbieter benötigen deinen eigenen Zugang. Für die öffentliche Chaturbate-Liste findest du unter **Einstellungen → Live & Arbeitsbereiche → Chaturbate einrichten · Anleitung** eine bebilderte Anleitung zum eigenen Affiliate-Code.

### 7. Beenden und Hilfe beim Start

Beende das Programm über **Einstellungen → Updates & Modellbilder → Programm beenden**. Nur das Browserfenster zu schließen beendet den lokalen Hintergrunddienst nicht.

Wenn sich die Oberfläche nicht öffnet: Prüfe zuerst, ob die ZIP vollständig entpackt ist und alle Unterordner vorhanden sind. Beim ersten Start mit Modelldaten kann die Vorbereitung länger dauern. Läuft das Programm bereits, öffnet ein erneuter Doppelklick auf `AdultClient.exe` seine Oberfläche. Bei einem Startfehler stehen Details gegebenenfalls unter `userdata\startup-error.txt` oder `userdata\startup.log`. Teile solche Dateien nur nach Prüfung auf persönliche Informationen.

## English

### 1. Requirements

- 64-bit Windows with .NET Framework 4, which is normally available on current Windows versions.
- A writable folder, such as `C:\AdultClient` or a folder inside Documents.
- Several GB of free disk space: The model data package expands to approximately 1.6 GB. Downloads, updates and backups require additional space.
- Internet access for live streams, tube sites, external images and updates. Locally stored model data remains searchable without an internet connection.

**You do not need to install Python or Kodi separately.** The required runtime is included. The interface opens in your browser; the application runs locally on your PC.

### 2. Recommended: Install the program and model data together

1. Download **Windows-Komplett.zip** using the link above. Alternatively, open the program release and expand **Assets**.
2. In Windows File Explorer, right-click the ZIP file and choose **Extract All…**.
3. Open the fully extracted application folder.
4. Double-click **`AdultClient.exe`**.
5. On the first launch, wait while the model data is verified and extracted. The interface then opens automatically in your default browser.

There is no additional installation wizard. **Do not run the EXE from inside the ZIP file.** Keep the included subfolders next to the EXE; the EXE alone is not sufficient. Use a writable folder rather than `C:\Program Files`.

**With this option, you do not need to download the separate model data package as well.**

### 3. Alternative: Install the program first, then download model data

Choose this option if you want to start with the smaller program download.

1. Download **Windows.zip** and extract the entire archive using **Extract All…**.
2. Launch `AdultClient.exe`.
3. Open **Settings → Updates & model images**.
4. Click **Check for updates**.
5. Under **Model data**, click **Download model data**. Wait for the package to finish downloading and verifying.
6. Click **Apply model data and restart**. Alternatively, the prepared package will be applied at the next normal application startup.

The application downloads the matching data file and its verification information automatically. You do not need to select the two data files manually. Until you import the package, the supplied model collection is not installed.

### 4. Alternative: Combine the program and model data manually

This also works if you download the files on another computer and transfer them with a USB drive.

1. Download **Windows.zip** and extract it completely.
2. Download **both** files from the model data release: `star-data.sqlite3.gz` and `star-data.sqlite3.json`.
3. **Before the very first launch**, put both files in the `data` folder next to `AdultClient.exe`. Create that folder if necessary.
4. Keep the data file compressed as `.gz`. Adult Client verifies and extracts it automatically.
5. Start `AdultClient.exe` and wait for the initial data import.

Your folder should look like this. Keep all other included folders and files as well:

```text
AdultClient/
├── AdultClient.exe
├── release.json
├── app/
├── runtime/
├── addon/
└── data/
    ├── star-data.sqlite3.gz
    └── star-data.sqlite3.json
```

**Already launched the application?** If a local database already exists, the application does not repeat the initial import from `data`. Use the in-app download under **Settings → Updates & model images**, as described in section 3. Do not delete your `userdata` folder to import the package.

### 5. Update the program and model data independently

Open **Settings → Updates & model images → Check for updates**. Your installed program version and model data date are shown separately.

| What do you want to update? | Steps |
| --- | --- |
| **Program** | **Download program update** → wait for verification → **Install and restart** |
| **Model data** | **Download model data** → wait for verification → **Apply model data and restart** |

- Enable **Include beta releases** to receive the current program betas.
- Enable **Check for updates automatically on startup and once a day** to be notified about updates. You still start downloads and installation yourself by clicking the corresponding button.
- A program update does not require downloading the large model database again. A model data update does not replace the application.
- If both updates are ready, install the program first, then apply the model data using its separate restart button.
- Personal settings, API keys, cookies, notes, favorites, history and downloads are preserved. Program updates continue using your existing `userdata` folder.
- You do not need a GitHub account for public downloads or in-app updates.

**About the GitHub release page:** Program and data releases can be published independently. A release marked “Latest” may therefore contain model data only. For installation, explicitly choose the program release and its **Windows.zip** or **Windows-Komplett.zip** asset. **Code → Download ZIP**, **Source code** and **Source.zip** contain source code, not the ready-to-run Windows application.

### 6. Language, images and personal connections

- **Language:** Switch using **Deutsch / English** in the sidebar. Interface labels switch language; names, tags, biographies and other model data keep their stored language.
- **Images:** The model package contains image links, not a complete offline photo collection. Images initially load from the internet as needed. To store them locally, open **Settings → Updates & model images → Download / resume all model images**. You can pause and resume this optional download; it may need substantial storage. Unavailable or protected images may be missing.
- **Personal connections:** The publisher's personal API keys and website sign-ins are not included. Some providers require your own connection. For the public Chaturbate list, open **Settings → Live & workspaces → Set up Chaturbate · Tutorial** for a guide with screenshots explaining your own affiliate code.

### 7. Quit and troubleshoot startup

Use **Settings → Updates & model images → Quit program** to stop the application. Closing the browser window alone does not stop the local background service.

If the interface does not open, first check that the ZIP was fully extracted and all included subfolders are present. Initial preparation can take longer when installing model data. If the application is already running, double-clicking `AdultClient.exe` again opens its interface. Startup error details may be available in `userdata\startup-error.txt` or `userdata\startup.log`. Check these files for personal information before sharing them.
