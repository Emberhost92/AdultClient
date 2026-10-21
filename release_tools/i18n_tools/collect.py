"""Build the finite UI translation inventory; never opens profiles or user data."""
import ast
from html.parser import HTMLParser
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
APP=HERE.parents[1]/'AdultHideoutWeb'
extracted=json.loads((HERE/'extracted-js.json').read_text(encoding='utf-8'))
strings=set(extracted['strings'])
javascript_strings=set(extracted['strings'])
patterns=set(extracted['patterns'])


class HTMLCopy(HTMLParser):
    def __init__(self):super().__init__();self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if not self.skip:
            for k,v in attrs:
                if k in ('title','aria-label','placeholder','alt') and v:strings.add(v)
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip and data.strip():strings.add(data.strip())


HTMLCopy().feed((APP/'static'/'app.html').read_text(encoding='utf-8'))
for file in list(APP.glob('*.py'))+[HERE.parent/'portable_support.py',HERE.parent/'portable_entry.py']:
    tree=ast.parse(file.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str):
            s=node.value
            if len(s)<5000 and not any(x in s for x in ('SELECT ','CREATE TABLE','INSERT INTO','UPDATE ','<!doctype','<script','</html>','https://','http://')):strings.add(s)
            if re.search(r'%(?:\([^)]+\))?[#0+ .\-]*\d*(?:\.\d+)?[sdif]',s):
                index=[0]
                def placeholder(_):
                    value='{'+str(index[0])+'}';index[0]+=1;return value
                template=re.sub(r'%(?:\([^)]+\))?[#0+ .\-]*\d*(?:\.\d+)?[sdif]',placeholder,s)
                strings.add(template);patterns.add(template)
        elif isinstance(node,ast.JoinedStr):
            i=0;parts=[]
            for part in node.values:
                if isinstance(part,ast.Constant):parts.append(str(part.value))
                else:parts.append('{'+str(i)+'}');i+=1
            s=''.join(parts)
            if len(s)<3000:strings.add(s);patterns.add(s)

# German prose and standalone UI labels. Technical identifiers never enter the catalogue.
GERMAN=set('ab abbrechen abrufen abruf abrufe aktuell aktualisieren aktualisierung aktualisierungen aktiv alle alles als am an andere andern anzeigen antwort antworten anzahl arbeiten auf aus auswählen auswahl ausgewählt automatisch beginnen bereits beschreibung bereich bereiche bestätigen bild bilder bitte bleibt browser datei dateien daten datum dauert deine deinen deinem deiner dein der des den dem die dialog diese dieser dieses durch ein eine einen einem einer eines eintrag einträge erneut erstellen erweitert entfernen entfernt erlauben fehler fertig filter fehlt fortsetzen frei für ganz ganze gespeicherte gespeichert geschlecht gesamt gesperrt geändert größe groß gruppen gruppe größe gültig hat haben hier hinzu hinzufügen hintergrund hilfe hoch ich im import in info infos ist ja jahr jahre jetzt kann kanal kanäle karriere katalog kategorie kategorien kein keine keinen keinem kleiner kommt konnte kontrollieren kopieren kurz laden lädt ladezeit land lang lauf laufende laufenden läuft letzte letzten letzter löschen mehr meine meldung meldungen mit modelle modell models möglich muss müssen nach nachladen name namen neben neue neuen neuer neues neu nächste nächsten nicht nichts noch notizen nutzen nur oder ohne offen ordner passt pausieren pausiert pfad profil profile prüfen prüfen quelle quellen raum räume rechts regel regeln speichern gespeichert seite seiten sekunden selbst setzen sind so sofort soll sortierung sprache starten stand statt status stunde stunden suchen suche synchronisieren tag tags tage teilen text texte ton um und unbekannt unten unter unterstützt verfügbar verbergen verbindung verbinden vergleichen verlauf verschieben version verwalten verwenden video videos vom von vor vorschau weiter wenn werden wert werte wie wieder wiedergeben wiederholung wird wurde wurden wählen zahl zeit zeiten zeigen ziel zu zuletzt zum zur zurück zusammen zwischen zugriff'.split())
GERMAN.update('start anbieter weiblich männlich paar paare beendet fehlgeschlagen erfolgreich abwesend verbindung benachrichtigungen gleich dunkel hell leistung zuletzt bildschirmvollbild ansicht ton einstellungen länge breite höhe links rechts oben unten ja nein lesen schreiben eingabe ausgabe abbrechen'.split())
existing=HERE/'translations.json'
if existing.exists():
    for de,en in json.loads(existing.read_text(encoding='utf-8')).items():
        if de.strip().lower()!=en.strip().lower():GERMAN.update(re.findall(r'[a-zäöüß]{3,}',de.lower()))
def candidate(s):
    if not 1<len(s)<5000 or not re.search('[A-Za-zÄÖÜäöüß]',s):return False
    if re.search(r'(?:https?://|plugin://|SELECT |CREATE TABLE|INSERT |DELETE FROM|UPDATE |ORDER BY|function\(|=>|\[\^|\\[dws]|</?\w+)',s):return False
    if s in javascript_strings:return True
    if re.fullmatch(r'[a-z0-9_./:#-]+',s) and s.lower() not in GERMAN:return False
    if re.search(r'[äöüßÄÖÜ]',s):return True
    if re.fullmatch(r'[A-Z][a-z]+(?:[ -][A-Za-z]+)*',s):return True
    words=re.findall(r'[A-Za-zÄÖÜäöüß]+',s.lower())
    return any(w in GERMAN for w in words)

strings=sorted(s for s in strings if candidate(s))
result={'strings':strings,'patterns':sorted(p for p in patterns if p in strings),'issues':extracted['issues']}
(HERE/'inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('UI_STRINGS',len(strings),'PATTERNS',len(result['patterns']),'CHARACTERS',sum(map(len,strings)))
