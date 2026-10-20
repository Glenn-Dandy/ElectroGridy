# SLDGridy

[![Release](https://img.shields.io/github/v/release/Glenn-Dandy/SLDGridy)](https://github.com/Glenn-Dandy/SLDGridy/releases/latest)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Snap Store](https://img.shields.io/badge/Snap%20Store-sldgridy-82BEA0?logo=snapcraft)](https://snapcraft.io/sldgridy)
[![Support](https://img.shields.io/badge/♥-Support%20the%20project-c62828)](https://paypal.me/GlennDandy)

**[English](#english) · [Deutsch](#deutsch)**

---

## English

CAD-style editor for single-line electrical diagrams on Linux: photovoltaic systems, transformer stations and low-voltage distribution. Drawing in real millimetres with model space and sheet layouts, grid and object snap, layers, blocks with attributes and connection points, a symbol library to DIN EN 60617, and printing up to A0.

The user interface is available in **English and German** (Settings > Sprache / Language); the Settings menu also holds “Fast display”, the window system (Wayland or X11) and what to show when a drawing is opened (whole drawing, last view of the file, or sheet 1 from the origin).

License: GPL-3.0-or-later. Target system: Ubuntu 24.04 LTS and 26.04 LTS (X11 and Wayland).

### Installation

**Snap Store** (Ubuntu App Center, automatic updates):

```bash
sudo snap install sldgridy
```

Or as **.deb package**: download `sldgridy_<version>_all.deb` from the [releases](https://github.com/Glenn-Dandy/SLDGridy/releases/latest) and install it:

```bash
sudo apt install ./sldgridy_<version>_all.deb
```

SLDGridy then appears in the application menu and `.sldg` files open with a double click. Remove it with `sudo apt remove sldgridy`.

The snap keeps its own settings and symbols under `~/snap/sldgridy/`.

#### Double-click on .sldg files (snap)

A snap cannot register its file type with the system. Without this step the file manager treats `.sldg` drawings as plain text; then do **not** choose “always open with SLDGridy”, as that would apply to all text files. Run once (no sudo needed):

```bash
mkdir -p ~/.local/share/mime/packages
cp /snap/sldgridy/current/usr/share/mime/packages/sldgridy.xml ~/.local/share/mime/packages/
update-mime-database ~/.local/share/mime
xdg-mime default sldgridy_sldgridy.desktop application/x-sldgridy
```

After that a double click opens `.sldg` files in SLDGridy. The `.deb` package does this by itself.

### Quick start

1. Draw in the **Model** tab. The origin is marked with axes; 1 unit = 1 mm.
2. Drag symbols from the **Library** dock (left) into the drawing or double-click them. The shipped library “Symbols to DIN EN 60617” contains 42 symbols for PV, transformer stations and low voltage; a second library “Further SLD symbols” holds common symbols without a standard drawing (selective main switches SHU/SHA, PV module, DC solar storage, AC-coupled wallbox, Internet cloud). After inserting, the program asks for the attributes `BMK` (reference designation), `TYP` and `WERT`; PV module, inverter, wallbox and DC solar storage also have `HERSTELLER` (manufacturer). Shift+Enter in a value starts a new line; the attributes below move down.
3. Connect connection points with **Draw > Wire** (Ctrl+W). Wires snap to connection points (magenta markers) and bend at right angles automatically. **Bus bar** draws a 0.7 mm bar that can be connected anywhere. Connection dots appear automatically.
4. Label wires by double-clicking them or in the Properties dock, e.g. “NYY-J 5x16”; the dock also sets side, position (automatic, start, end, free), alignment (left, centre, right) and size of the label. A selected labelled wire has an orange diamond grip at its label: drag it along the wire to place the label on any segment. Hollow square grips in the middle of each segment shift just that segment; the wire ends stay connected. Grips can be dragged (press, drag, release) or clicked and then placed with a second click; the grip under the mouse turns red.
- Right-click on a wire end at the edge of a block: “Set docking point here” makes it a connection point of this block instance, so the wire follows when the block is moved.
- Wires attached to another wire or bus bar (T branch or end to end) follow when that wire is moved, rotated or reshaped; points separated with right-click “Separate” stay put. This also travels along: a moved block pulls its wire, the wire pulls its branches.
- Right-click inside a wire segment: “Add point” splits it, so each part gets its own segment grip and can be offset on its own.
5. The **Sheet 1** tab holds an A0 landscape frame with title block. **Sheet > Fill in title block** sets project, company, title and so on.
6. **File > Print** (Ctrl+P) or **File > Export** to PDF, SVG or PNG.

### Mouse and keyboard

| Action | How |
|---|---|
| Zoom | mouse wheel (towards the cursor) |
| Pan | drag with the middle mouse button |
| Zoom extents | Home |
| Select | click; Shift+click adds or removes |
| Window / crossing | drag left to right: fully inside; right to left: touching |
| Move objects | drag selected objects or **Modify > Move** |
| Grips | click a blue grip, then click the new position |
| Cancel command | Esc |
| End command | Enter or right click |
| Repeat last command | Space |
| Delete | Del |
| Undo / Redo | Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z), mouse back / forward button |
| Cut / Copy / Paste | Ctrl+X / Ctrl+C / Ctrl+V |
| Object snap / grid / ortho / grid snap / snap tracking | F3 / F7 / F8 / F9 / F11 |

Modify commands without a selection first ask for objects: select them and press Enter.

**Choosing snap modes:** rest on the **OSNAP** button at the bottom or click its small arrow, or **Shift+right click** on the drawing. **Nearest** catches any point on a line, also a sloped one, or on a circle or arc (hourglass marker). While drawing a polyline its own points snap too, so it can be closed on its start point. **Perpendicular** snaps the right-angle point from the last point, e.g. a wire straight onto the bus bar.

**Right click on a point** (no command running): **Connect** places a connection dot, **Separate** suppresses an automatic dot (shown on screen as an orange ring, not printed), **Remove point** deletes a bend or corner of a wire or polyline, **Extend** continues drawing at an end.

**Object snap tracking:** during a command, rest the cursor on a snap point (e.g. a connection point) until a green + appears. Moving horizontally or vertically away from it shows a dotted alignment line and the point snaps onto it, on the grid. Two acquired points give the intersection of their alignments.

**Typed coordinates:** during a drawing command just start typing; input goes to the **Command** line: `120,45` absolute, `@25,0` relative to the last point, `30` length towards the cursor (ortho only). With a decimal comma separate the values with a semicolon: `12,5;7,5`.

### Dimensions and scaled drawings

- **Workspace** (first box in the toolbar): *Circuit diagram (SLD)* or *Drawing*. It only changes tools and grid, not the drawing: *Drawing* hides wire and bus bar and the circuit diagram libraries. Each workspace has its own layers (layer 0 is shared) and remembers its grid. The program always starts in *Circuit diagram (SLD)*. Rest on the GRID or SNAP button (or use its arrow) to type grid and snap spacing.
- **Typed values at the cursor:** while drawing, the length sits on the line and the angle at its start. Just type a number for the length, **Tab** switches to the angle, **Enter** sets the point. A typed value stays fixed while the mouse decides the other one. Rectangles take width and height, the first point X and Y. Typing `@` still opens the command line. Switch off under Settings > Dimension input at the cursor.
- **Fixed length, free direction:** type a length and move the mouse. The line end then snaps onto edges of nearby objects (marked ×) and otherwise turns in steps of the angle snap (15°, dotted guide). Set the angle snap in the GRID/SNAP popup ("off" = 0). Without a typed length the angle snap only works with grid snap off.
- **Rotate** (toolbar button with arrow, Modify menu): *Rotate (any angle)* turns around a base point by mouse or typed angle; *Rotate 90°* keeps the quarter steps. Blocks, wires and bus bars only turn in 90° steps; rectangles become closed polylines.
- **Scale** (Modify menu): select, pick a base point, then type a factor and press Enter (e.g. `2` or `0,5`), or click a reference point (e.g. the end of a known length) and show or type the new length; a line drawn 4.2 m long becomes exactly 5 m. Symbols and PV modules scale too, text heights grow along.
- **Mirror:** a point on the axis, then its direction (horizontal or vertical). A small menu at the mouse then asks: *Replace original* or *Keep original, copy*. The last choice is preselected, Enter takes it.
- **Draw > Dimension:** pick two points, then where the dimension line goes; horizontal or vertical follows the side you drag to. **Dimension parallel** (arrow on the Dimension button) runs parallel to the line between the points and measures its true length. **Dimension angle**: click the vertex, a point on each leg, then where the arc goes; the side you drag to decides which angle is measured (across a leg gives the supplementary angle). A click near a drawn line through the vertex snaps onto it, also on sloped edges between grid points. Value text, text height and direction can be changed in the Properties dock (an empty text shows the measured value). With several dimensions (or wires) selected the dock edits all of them: differing values show *varies*, a value you enter applies to all, untouched fields keep their own values.
- **Roof layout** (Drawing workspace): draw the roof face with your measured lengths (rectangle or closed polyline, e.g. trapezoid) and obstacles inside it (rectangles, circles, closed polylines). **Draw > Module field …**: module size and power from the data sheet, portrait or landscape, number of modules (empty: as many as fit; otherwise rows are filled from the top, the last partial row centred), distances between modules (20 mm), to the roof edge (300 mm) and to obstacles (200 mm). Then click into the roof face: it is filled with as many modules as fit, centred; the status bar shows the count and kWp. Each module is a block in real size and can be moved or deleted.
- Text heights (text, wire labels, attributes) can be picked from 2.5/3.5/5/7 mm or typed freely, e.g. `125` for 2.5 mm on paper at 1:50.
- Scaled drawings (e.g. a roof plan at 1:50 on a sheet): line widths always apply on paper, and a new dimension inside a viewport gets a value that is 2.5 mm high on the sheet.

### Blocks, libraries and DXF import

- **Block > Create block** (Ctrl+B): select objects (or select them when asked and press Enter), name the block; the block editor opens right away to add connection points and attributes (the base point jumps to the first connection point until you set it yourself), and **Save and close** creates the block. Untick the editor option in the dialog to just click a base point instead. **Block > Edit block** (block editor with yellow bar), **Modify > Explode**.
- **Define attribute** and **Place connection point** create placeholders and terminals, best in the block editor.
- When a block is moved, rotated or mirrored, wire ends on its connection points follow.
- **Block > Save to user library** stores the block in `~/.local/share/sldgridy/library/eigene.sldglib`; libraries can be imported and exported.
- Right-click a symbol in the library dock to open it in the block editor (changes to user library symbols are written back to the library file when you save), to edit its name, category and description or to delete it. This works for blocks of the drawing (undoable; renaming updates all references, deleting only unused blocks) and for user libraries. Shipped libraries are read only.
- **Block > Import symbols from DXF** reads ASCII DXF files: each named block becomes a symbol; lines, polylines (with arcs), circles, arcs, ellipses, texts and attributes (ATTDEF) are taken over, nested blocks are resolved, **POINT** objects become connection points, units are converted to mm. The symbols are stored as a library named after the DXF file.

### Sheets, printing and export

- Tabs at the bottom: model and sheets (new, rename, duplicate, delete, format, templates via right click).
- Click the **Model** tab again (or right-click it, or **Sheet > Align model on sheet**): *Align on Sheet 1, 2, …* shows exactly the model area that sheet shows.
- Formats A4 to A0, portrait and landscape, frame to DIN EN ISO 5457, title block to DIN EN ISO 7200 (180 mm; the block “Schriftfeld” can be changed in the block editor).
- Double-click into a viewport activates it: the wheel zooms, the middle button pans, Esc ends. Scale, position of the area's top left corner in the model (X/Y, button “Top left to 0,0”), lock and “Fit model extents” in the Properties dock.
- Printing **1:1** (A0 on the plotter), **fit to paper** (e.g. A0 on A3) or **tiles** (1:1 on smaller sheets with 10 mm overlap, cut marks and tile numbers); quick print of the model; black and white; printable layers only.
- Vector PDF with exact sheet size and one page per sheet, SVG in mm, PNG with selectable resolution.

### Files and locations

| What | Where |
|---|---|
| Drawing | `*.sldg` (JSON, versioned; saving keeps `*.sldg.bak`) |
| Library | `*.sldglib`; shipped in `/usr/share/sldgridy/library/`, own ones in `~/.local/share/sldgridy/library/` |
| Frame template | `*.sldgframe`; shipped in `/usr/share/sldgridy/templates/`, own ones in `~/.local/share/sldgridy/templates/` |
| Automatic backup | every 5 minutes to `~/.cache/sldgridy/`; after a crash the next start offers recovery |
| Settings | `~/.config/sldgridy/sldgridy.conf` |

### Development

```bash
sudo apt install python3-venv python3-pyqt6 python3-pyqt6.qtsvg lintian
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m sldgridy                     # run
QT_QPA_PLATFORM=offscreen .venv/bin/pytest       # tests without a display
.venv/bin/ruff check . && .venv/bin/ruff format --check .
./packaging/build-deb.sh                         # builds dist/sldgridy_<version>_all.deb
lintian dist/sldgridy_*.deb
```

German is the source language of the user interface; English translations live in `src/sldgridy/resources/i18n/en.json` (a test checks that every text is translated). The specification and all design decisions are in `CLAUDE.md` (German).

### Feedback and support

- Bugs and ideas: [issues](https://github.com/Glenn-Dandy/SLDGridy/issues) (in the program: Help > Report a bug, prefilled with version details)
- Like SLDGridy? Give the project a ⭐ on GitHub.
- [♥ Support the project](https://paypal.me/GlennDandy)

### Notice

SLDGridy is an independent project. It is not affiliated with or endorsed by DIN, IEC, VDE, Autodesk, EPLAN or the LibreCAD project. DIN is a registered trademark of DIN Deutsches Institut für Normung e.V.; AutoCAD and DXF are trademarks of Autodesk, Inc. The symbols were drawn for this project following the standards mentioned; the standards themselves are not included.

### License

GPL-3.0-or-later, see [LICENSE](LICENSE). © Glenn-Dandy

---

## Deutsch

Einpolige Übersichtsschaltpläne (Single-Line-Diagramme) für Photovoltaikanlagen, Transformatorstationen und Niederspannungsverteilungen unter Linux, gezeichnet wie in einem CAD-Programm: maßhaltig in Millimetern, mit Modell und Zeichnungsrahmen, Raster und Objektfang, Ebenen, Blöcken mit Attributen und Anschlusspunkten, einer Symbolbibliothek nach DIN EN 60617 und Drucken bis A0.

Die Oberfläche gibt es auf **Deutsch und Englisch** (Einstellungen > Sprache / Language); im Menü Einstellungen stehen außerdem „Schnelle Darstellung“, das Fenstersystem (Wayland oder X11) und was beim Öffnen einer Zeichnung gezeigt wird (ganze Zeichnung, letzte Ansicht der Datei oder Blatt 1 ab Nullpunkt).

Lizenz: GPL-3.0-or-later. Zielsystem: Ubuntu 24.04 LTS und 26.04 LTS (X11 und Wayland).

### Installation

**Snap Store** (Ubuntu App Center, automatische Updates):

```bash
sudo snap install sldgridy
```

Oder als **.deb-Paket**: `sldgridy_<version>_all.deb` aus den [Releases](https://github.com/Glenn-Dandy/SLDGridy/releases/latest) herunterladen und installieren:

```bash
sudo apt install ./sldgridy_<version>_all.deb
```

Danach steht „SLDGridy“ im Anwendungsmenü, und `.sldg`-Dateien öffnen sich per Doppelklick. Deinstallation mit `sudo apt remove sldgridy`.

Das Snap hat eigene Einstellungen und Symbole unter `~/snap/sldgridy/`.

#### Doppelklick auf .sldg-Dateien (Snap)

Ein Snap kann seinen Dateityp nicht selbst beim System anmelden. Ohne diesen Schritt hält der Dateimanager `.sldg`-Zeichnungen für Text; dann **nicht** „immer mit SLDGridy öffnen“ wählen, das gälte sonst für alle Textdateien. Einmal ausführen (ohne sudo):

```bash
mkdir -p ~/.local/share/mime/packages
cp /snap/sldgridy/current/usr/share/mime/packages/sldgridy.xml ~/.local/share/mime/packages/
update-mime-database ~/.local/share/mime
xdg-mime default sldgridy_sldgridy.desktop application/x-sldgridy
```

Danach öffnet ein Doppelklick `.sldg`-Dateien in SLDGridy. Das `.deb`-Paket erledigt das selbst.

### Kurzanleitung

1. Im Reiter **Modell** zeichnen. Der Nullpunkt ist mit einem Achsenkreuz markiert, 1 Einheit = 1 mm.
2. Symbole aus dem Dock **Bibliothek** (links) in die Zeichnung ziehen oder doppelklicken. Die mitgelieferte Bibliothek „Symbole nach DIN EN 60617“ enthält 42 Symbole für PV, Trafostation und Niederspannung; eine zweite Bibliothek „Weitere SLD-Symbole“ enthält übliche Symbole ohne Norm-Schaltzeichen (selektive Hauptschalter netzunabhängig/netzabhängig, PV-Modul, DC-Solarspeicher, Wallbox AC-gekoppelt, Internet-Wolke). Nach dem Einfügen fragt das Programm die Attribute `BMK`, `TYP` und `WERT` ab; PV-Modul, Wechselrichter, Wallbox und DC-Solarspeicher zusätzlich `HERSTELLER`. Umschalt+Enter in einem Wert beginnt eine neue Zeile, die Attribute darunter rutschen nach unten.
3. Mit **Zeichnen > Leitung** (Strg+W) Anschlusspunkte verbinden. Die Leitung rastet auf Anschlusspunkte (magentafarbene Marker) und knickt automatisch rechtwinklig. **Sammelschiene** zeichnet eine 0,7-mm-Schiene, an die überall angeschlossen werden kann. Verbindungspunkte entstehen automatisch.
4. Leitungen beschriften: Doppelklick auf die Leitung oder Eigenschaften-Dock, z. B. „NYY-J 5x16“; im Dock auch Lage, Position (automatisch, Anfang, Ende, frei), Ausrichtung (links, mitte, rechts) und Größe der Beschriftung. Eine ausgewählte beschriftete Leitung hat einen orangen Rautengriff an der Beschriftung: entlang der Leitung ziehen, um sie auf einen beliebigen Abschnitt zu setzen. Hohle Quadratgriffe in der Mitte jedes Abschnitts verschieben nur diesen Abschnitt, die Leitungsenden bleiben angeschlossen. Griffe lassen sich ziehen (drücken, ziehen, loslassen) oder anklicken und mit einem zweiten Klick absetzen; der Griff unter der Maus wird rot.
- Rechtsklick auf ein Leitungsende am Rand eines Blocks: „Andockpunkt hier setzen“ macht die Stelle zum Anschlusspunkt dieses einen Blocks, die Leitung folgt dann beim Verschieben.
- Leitungen, die an einer anderen Leitung oder Sammelschiene hängen (T-Abzweig oder Ende an Ende), wandern mit, wenn diese verschoben, gedreht oder umgeformt wird; per Rechtsklick „Trennen“ getrennte Stellen bleiben stehen. Das setzt sich fort: Ein verschobener Block zieht seine Leitung, die Leitung ihre Abzweige.
- Rechtsklick in einen Leitungsabschnitt: „Punkt hinzufügen“ teilt ihn, jeder Teil bekommt seinen eigenen Abschnittsgriff und lässt sich einzeln versetzen.
5. Im Reiter **Blatt 1** liegt der Zeichnungsrahmen A0 quer mit Schriftfeld. **Blatt > Schriftfeld ausfüllen** setzt Projekt, Firma, Titel usw.
6. **Datei > Drucken** (Strg+P) oder **Datei > Exportieren** als PDF, SVG oder PNG.

### Maus und Tastatur

| Aktion | Bedienung |
|---|---|
| Zoomen | Mausrad (auf den Cursor) |
| Verschieben der Ansicht | mittlere Maustaste ziehen |
| Grenzen zoomen | Pos1 |
| Auswählen | Klick; Umschalt+Klick fügt hinzu oder nimmt weg |
| Fenster / Kreuzen | links nach rechts ziehen: vollständig innen; rechts nach links: berührt |
| Objekte verschieben | ausgewählte Objekte direkt ziehen oder **Ändern > Verschieben** |
| Griffe | Klick auf einen blauen Griff, dann neue Position klicken |
| Befehl abbrechen | Esc |
| Befehl beenden | Enter oder Rechtsklick |
| Letzten Befehl wiederholen | Leertaste |
| Löschen | Entf |
| Rückgängig / Wiederholen | Strg+Z / Strg+Y (oder Strg+Umschalt+Z), Maustaste zurück / vor |
| Ausschneiden / Kopieren / Einfügen | Strg+X / Strg+C / Strg+V |
| Objektfang / Raster / Ortho / Rasterfang / Objektfangspur | F3 / F7 / F8 / F9 / F11 |

Ändern-Befehle ohne Auswahl fragen zuerst nach Objekten: wählen und mit Enter bestätigen.

**Objektfang wählen:** am Knopf **OFANG** unten kurz verweilen oder den kleinen Pfeil anklicken, oder **Umschalt+Rechtsklick** auf der Zeichenfläche. **Nächster Punkt** fängt jeden Punkt auf einer Linie, auch einer schrägen, oder auf Kreis und Bogen (Sanduhr-Markierung). Beim Zeichnen einer Polylinie fangen auch ihre eigenen Punkte, so lässt sie sich am Startpunkt schließen. Der **Lotfußpunkt** fängt den rechtwinkligen Punkt vom letzten Punkt aus, z. B. eine Leitung senkrecht auf die Sammelschiene.

**Rechtsklick auf einen Punkt** (ohne laufenden Befehl): **Verbinden** setzt einen Verbindungspunkt, **Trennen** unterdrückt einen automatischen Punkt (am Bildschirm als oranger Ring sichtbar, nicht im Druck), **Punkt entfernen** löscht einen Knick oder Eckpunkt einer Leitung oder Polylinie, **Verlängern** zeichnet an einem Ende weiter.

**Objektfangspur (Hilfslinien):** Während eines Befehls den Cursor kurz auf einem Fangpunkt (z. B. Anschlusspunkt) ruhen lassen, bis ein grünes + erscheint. Bewegt man sich danach waagerecht oder senkrecht davon weg, zeigt eine gepunktete Linie die Flucht, und der Punkt rastet darauf ein, im Raster. Zwei vorgemerkte Punkte ergeben den Kreuzungspunkt ihrer Fluchten.

**Koordinaten eingeben:** Während eines Zeichenbefehls einfach lostippen, die Eingabe landet in der Zeile **Befehl**: `120,45` absolut, `@25,0` relativ zum letzten Punkt, `30` Länge in Cursorrichtung (nur bei Ortho). Mit Dezimalkomma die Werte mit Semikolon trennen: `12,5;7,5`.

### Bemaßung und Maßstabszeichnungen

- **Arbeitsbereich** (erstes Auswahlfeld in der Werkzeugleiste): *Schaltplan (SLD)* oder *Zeichnung*. Er ändert nur Werkzeuge und Raster, nicht die Zeichnung: *Zeichnung* blendet Leitung, Sammelschiene und die Schaltplan-Bibliotheken aus. Jeder Arbeitsbereich hat eigene Ebenen (Ebene 0 gilt für beide) und merkt sich sein Raster. Das Programm startet immer in *Schaltplan (SLD)*. Verweilen auf dem Knopf RASTER oder FANG (oder sein Pfeil) öffnet ein Feld zum direkten Eintragen von Raster und Fang.
- **Maßeingabe am Fadenkreuz:** Beim Zeichnen steht die Länge auf der Linie und der Winkel an ihrem Anfang. Einfach eine Zahl tippen setzt die Länge, **Tab** wechselt zum Winkel, **Enter** setzt den Punkt. Ein getippter Wert bleibt fest, die Maus bestimmt nur noch den anderen. Beim Rechteck gelten Breite und Höhe, beim ersten Punkt X und Y. Mit `@` geht es weiter in die Befehlszeile. Abschaltbar unter Einstellungen > Maßeingabe am Fadenkreuz.
- **Feste Länge, freie Richtung:** Länge tippen und die Maus bewegen. Das Linienende rastet dann auf Kanten benachbarter Objekte ein (Markierung ×) und dreht sonst in Schritten des Winkelfangs (15°, gepunktete Hilfslinie). Den Winkelfang stellt man im Feld von RASTER/FANG ein („aus“ = 0). Ohne getippte Länge wirkt der Winkelfang nur bei ausgeschaltetem Rasterfang.
- **Drehen** (Knopf mit Pfeil in der Werkzeugleiste, Menü Ändern): *Drehen (beliebiger Winkel)* dreht um einen Basispunkt per Maus oder getipptem Winkel, *Drehen 90°* bleibt bei Vierteldrehungen. Blöcke, Leitungen und Sammelschienen drehen nur in 90°-Schritten; Rechtecke werden zu geschlossenen Polylinien.
- **Skalieren** (Menü Ändern): markieren, Basispunkt klicken, dann Faktor eintippen und Enter (z. B. `2` oder `0,5`), oder einen Bezugspunkt klicken (z. B. das Ende einer bekannten Strecke) und die neue Länge zeigen oder eintippen; so wird aus einer mit 4,2 m gezeichneten Kante genau 5 m. Symbole und PV-Module werden mitskaliert, Texthöhen wachsen mit.
- **Spiegeln:** Punkt auf der Achse, dann die Richtung (waagerecht oder senkrecht). Danach fragt ein kleines Menü am Mauszeiger: *Original ersetzen* oder *Kopie, Original bleibt*. Die letzte Wahl ist vorausgewählt, Enter übernimmt sie.
- **Zeichnen > Bemaßen:** zwei Punkte anklicken, dann die Lage der Maßlinie; waagerecht oder senkrecht ergibt sich aus der Richtung, in die man zieht. **Bemaßen parallel** (Pfeil am Knopf Bemaßen) liegt parallel zur Strecke zwischen den Punkten und misst ihre wahre Länge. **Bemaßen Winkel**: Scheitelpunkt anklicken, dann je einen Punkt auf beiden Schenkeln, dann die Lage des Maßbogens; wohin man zieht, bestimmt den gemessenen Winkel (über einen Schenkel hinaus ergibt den Nebenwinkel). Ein Klick in die Nähe einer gezeichneten Linie durch den Scheitel rastet auf ihr ein, auch bei schrägen Kanten zwischen den Rasterpunkten. Maßtext, Texthöhe und Richtung im Eigenschaften-Dock (leerer Maßtext zeigt den gemessenen Wert). Sind mehrere Bemaßungen (oder Leitungen) markiert, gilt das Dock für alle: verschiedene Werte zeigen *verschieden*, ein eingetragener Wert gilt für alle, nicht angefasste Felder behalten ihre eigenen Werte.
- **Dachbelegung** (Arbeitsbereich Zeichnung): Dachfläche mit den gemessenen Längen zeichnen (Rechteck oder geschlossene Polylinie, z. B. Trapez) und Hindernisse darin (Rechtecke, Kreise, geschlossene Polylinien). **Zeichnen > Modulfeld …**: Modulmaß und Leistung laut Datenblatt, Hoch- oder Querformat, Anzahl (leer: so viele wie passen; sonst werden Reihen von oben gefüllt, die letzte angefangene Reihe mittig), Abstände zwischen den Modulen (20 mm), zur Dachkante (300 mm) und zu Hindernissen (200 mm). Dann in die Dachfläche klicken: Sie wird mit so vielen Modulen wie möglich mittig belegt, die Statuszeile zeigt Anzahl und kWp. Jedes Modul ist ein Block in echter Größe und lässt sich verschieben oder löschen.
- Texthöhen (Text, Leitungsbeschriftung, Attribute) aus 2,5/3,5/5/7 mm wählen oder frei eintragen, z. B. `125` für 2,5 mm auf dem Papier bei 1:50.
- Maßstabszeichnungen (z. B. Dachplan 1:50 auf einem Blatt): Linienbreiten gelten immer auf dem Papier, und eine neue Bemaßung im Bereich eines Ansichtsfensters bekommt eine Maßzahl, die auf dem Blatt 2,5 mm hoch ist.

### Ebenen und Eigenschaften

Im Dock **Ebenen**: Name, Farbe, Linienbreite (ISO 128: 0,18 bis 0,7 mm), Linienart, sichtbar, gesperrt, druckbar. Doppelklick setzt die aktuelle Ebene. Das Dock **Eigenschaften** ändert Ebene, Farbe, Breite, Linienart, Text, Blockattribute, Leitungsbeschriftung und Ansichtsfenster der Auswahl.

### Blöcke, Bibliotheken und DXF-Import

- **Block > Block erstellen** (Strg+B): Objekte auswählen (oder auf Nachfrage auswählen und Enter drücken), Namen vergeben; danach öffnet sich gleich der Blockeditor für Anschlusspunkte und Attribute (der Basispunkt springt auf den ersten Anschlusspunkt, bis du ihn selbst setzt), **Speichern und schließen** legt den Block an. Ohne den Haken für den Blockeditor im Dialog wird stattdessen nur der Basispunkt geklickt.
- **Block > Attribut definieren** und **Anschlusspunkt setzen** legen Platzhalter und Anschlüsse an, am besten im Blockeditor.
- **Block > Block bearbeiten** öffnet den Blockeditor mit gelber Leiste. „Speichern und schließen“ aktualisiert alle Referenzen.
- **Ändern > Auflösen** ersetzt eine Referenz durch ihre Einzelobjekte.
- **Block > In Benutzerbibliothek speichern** legt den Block in `~/.local/share/sldgridy/library/eigene.sldglib` ab. Bibliotheken lassen sich importieren und exportieren.
- Rechtsklick auf ein Symbol im Bibliotheks-Dock: im Blockeditor öffnen (Symbole der Benutzerbibliothek werden beim Speichern zurück in die Bibliotheksdatei geschrieben), Name, Kategorie und Beschreibung bearbeiten oder löschen. Das geht für Blöcke der Zeichnung (rückgängig machbar; Umbenennen ändert alle Referenzen mit, gelöscht werden nur unbenutzte Blöcke) und für Benutzerbibliotheken. Mitgelieferte Bibliotheken sind schreibgeschützt.
- Wird ein Block verschoben, gedreht oder gespiegelt, wandern die Leitungsenden auf seinen Anschlusspunkten mit.
- **Block > Symbole aus DXF importieren** liest ASCII-DXF-Dateien (z. B. Herstellersymbole oder Exporte aus AutoCAD, EPLAN, LibreCAD): Jeder benannte Block wird ein Symbol; Linien, Polylinien (auch mit Bögen), Kreise, Bögen, Ellipsen, Texte und Attribute (ATTDEF) werden übernommen, verschachtelte Blöcke aufgelöst, **POINT**-Objekte werden zu Anschlusspunkten, die Einheit wird in mm umgerechnet. Die Symbole landen als eigene Bibliothek mit dem Namen der DXF-Datei.

### Zeichnungsrahmen

- Reiter unten: Modell und Blätter. Rechtsklick auf einen Reiter bietet Neu, Umbenennen, Duplizieren, Löschen, Format und Vorlagen. Reiter lassen sich verschieben.
- Formate A4 bis A0, hoch und quer, Rahmen nach DIN EN ISO 5457, Schriftfeld nach DIN EN ISO 7200 (180 mm). Das Schriftfeld ist der Block „Schriftfeld“ und kann im Blockeditor angepasst werden.
- Doppelklick in ein Ansichtsfenster aktiviert es: Mausrad zoomt, mittlere Taste verschiebt den Ausschnitt, Esc beendet. Maßstab (1:1, 2:1, 1:2, 1:5, 1:10 oder frei), Lage der linken oberen Ecke des Ausschnitts im Modell (X/Y, Knopf „Links oben auf 0,0“), Sperre und „Modellgrenzen einpassen“ im Eigenschaften-Dock.
- Im Modell zeigen gestrichelte Umrisse, was auf welches Blatt passt (**Blatt > Blattumrisse im Modell**).
- Ein Klick auf den Reiter **Modell**, wenn das Modell schon offen ist (oder Rechtsklick darauf, oder **Blatt > Modell auf Blatt ausrichten**): *Ausrichten auf Blatt 1, 2, …* zeigt genau den Modellbereich, den dieses Blatt zeigt.
- **Blatt > Als Vorlage speichern** legt eigene Rahmen in `~/.local/share/sldgridy/templates/` ab.

### Drucken und Export

- **1:1**: Blattformat gleich Papierformat (A0 auf dem Plotter). Ist das Format am Drucker nicht verfügbar, ist 1:1 gesperrt.
- **Einpassen**: Blatt auf das gewählte Papier skaliert (z. B. A0 auf A3).
- **Kacheln**: 1:1 auf kleinere Bögen mit 10 mm Überlappung, Schnittmarken und Kachelnummer `Z1/S2`.
- Im Reiter Modell gibt es zusätzlich den Schnelldruck, der die Modellgrenzen auf das Papier einpasst.
- Optionen: Schwarz-weiß, nur druckbare Ebenen. Die Vorschau warnt, wenn der Drucker nicht bis in den Rahmen drucken kann.
- PDF als Vektor mit exakter Blattgröße und einer Seite je Blatt, SVG in mm, PNG mit wählbarer Auflösung.

### Dateien und Speicherorte

| Was | Wo |
|---|---|
| Zeichnung | `*.sldg` (JSON, versioniert; beim Speichern bleibt `*.sldg.bak`) |
| Bibliothek | `*.sldglib`; mitgeliefert in `/usr/share/sldgridy/library/`, eigene in `~/.local/share/sldgridy/library/` |
| Rahmenvorlage | `*.sldgframe`; mitgeliefert in `/usr/share/sldgridy/templates/`, eigene in `~/.local/share/sldgridy/templates/` |
| Automatische Sicherung | alle 5 Minuten nach `~/.cache/sldgridy/`; nach einem Absturz bietet der nächste Start die Wiederherstellung an |
| Einstellungen | `~/.config/sldgridy/sldgridy.conf` |

### Entwicklung

Befehle wie im englischen Teil unter *Development*. Deutsch ist die Quellsprache der Oberfläche, die englischen Texte stehen in `src/sldgridy/resources/i18n/en.json` (ein Test prüft, dass jeder Text übersetzt ist). Die Spezifikation und alle Festlegungen stehen in `CLAUDE.md`.

### Feedback und Unterstützung

- Fehler und Wünsche: [Issues](https://github.com/Glenn-Dandy/SLDGridy/issues) (im Programm unter Hilfe > Fehler melden, mit Versionsangaben vorausgefüllt)
- Gefällt dir SLDGridy? Gib dem Projekt einen ⭐ auf GitHub.
- [♥ Projekt unterstützen](https://paypal.me/GlennDandy)

### Hinweis

SLDGridy ist ein unabhängiges Projekt und steht in keiner Verbindung zu DIN, IEC, VDE, Autodesk, EPLAN oder dem LibreCAD-Projekt. DIN ist eine eingetragene Marke des DIN Deutsches Institut für Normung e.V.; AutoCAD und DXF sind Marken der Autodesk, Inc. Die Symbole wurden für dieses Projekt nach den genannten Normen gezeichnet; die Normen selbst sind nicht enthalten.

### Lizenz

GPL-3.0-or-later, siehe [LICENSE](LICENSE). © Glenn-Dandy
