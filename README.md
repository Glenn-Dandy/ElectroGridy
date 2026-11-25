# ElectroGridy

[![Release](https://img.shields.io/github/v/release/Glenn-Dandy/ElectroGridy)](https://github.com/Glenn-Dandy/ElectroGridy/releases/latest)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Snap Store](https://img.shields.io/badge/Snap%20Store-electrogridy-82BEA0?logo=snapcraft)](https://snapcraft.io/electrogridy)

**[Deutsch](#deutsch) · [English](#english)**

## Deutsch

Programm zum Zeichnen von Übersichtsschaltplänen (PV-Anlagen, Trafostationen, Niederspannung), Schaltplanprojekten mit Klemmenplan und Kabelliste sowie maßstäblichen Zeichnungen. Symbole nach DIN EN 60617, Druck bis A0, PDF-Export, Import von PDF-Plänen und Fotos. Für Linux und Windows, Deutsch und Englisch.

### Installation

```bash
sudo snap install electrogridy
```

oder das `.deb` aus den [Releases](https://github.com/Glenn-Dandy/ElectroGridy/releases/latest):

```bash
sudo apt install ./electrogridy_<version>_all.deb
```

Windows: `ElectroGridy-<version>-setup.exe` aus den Releases. Das Installationsprogramm ist nicht signiert, bei der Warnung „Weitere Informationen“ und „Trotzdem ausführen“ wählen.

Beim Snap öffnen `.grdy`-Dateien erst nach diesen Befehlen per Doppelklick:

```bash
mkdir -p ~/.local/share/mime/packages
cp /snap/electrogridy/current/usr/share/mime/packages/electrogridy.xml ~/.local/share/mime/packages/
update-mime-database ~/.local/share/mime
xdg-mime default electrogridy_electrogridy.desktop application/x-electrogridy
```

### Tasten

| | |
|---|---|
| Abbrechen / Beenden / Wiederholen | Esc / Enter oder Rechtsklick / Leertaste |
| Objektfang / Raster / Ortho / Rasterfang / Spur | F3 / F7 / F8 / F9 / F11 |
| Alles zeigen | Pos1 |
| Auswahl schieben | Umschalt + Pfeil (1 mm), Strg + Umschalt + Pfeil (0,1 mm) |

### Entwicklung

```bash
sudo apt install python3-venv python3-pyqt6 python3-pyqt6.qtsvg python3-pyqt6.qtpdf python3-pdfminer tesseract-ocr tesseract-ocr-deu
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m electrogridy
QT_QPA_PLATFORM=offscreen .venv/bin/pytest
./packaging/build-deb.sh
```

### Lizenz

GPL-3.0-or-later. Die mitgelieferten Texterkennungsmodelle sind [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) 4.1.0 (Apache-2.0).

Unabhängiges Projekt, nicht verbunden mit DIN, IEC oder VDE. DIN ist eine eingetragene Marke des DIN e.V., DXF eine Marke von Autodesk, Inc. Die Normen selbst sind nicht enthalten.

## English

Draws single-line diagrams (PV systems, transformer stations, low voltage), circuit diagram projects with terminal plan and cable list, and scaled drawings. Symbols to DIN EN 60617, printing up to A0, PDF export, import of PDF plans and photos. Linux and Windows, English and German.

### Installation

```bash
sudo snap install electrogridy
```

or the `.deb` from the [releases](https://github.com/Glenn-Dandy/ElectroGridy/releases/latest):

```bash
sudo apt install ./electrogridy_<version>_all.deb
```

Windows: `ElectroGridy-<version>-setup.exe` from the releases. The installer is not signed; at the warning choose "More info" and "Run anyway".

With the snap, `.grdy` files open by double click only after:

```bash
mkdir -p ~/.local/share/mime/packages
cp /snap/electrogridy/current/usr/share/mime/packages/electrogridy.xml ~/.local/share/mime/packages/
update-mime-database ~/.local/share/mime
xdg-mime default electrogridy_electrogridy.desktop application/x-electrogridy
```

### Keys

| | |
|---|---|
| Cancel / End / Repeat | Esc / Enter or right click / Space |
| Object snap / Grid / Ortho / Grid snap / Tracking | F3 / F7 / F8 / F9 / F11 |
| Zoom extents | Home |
| Nudge selection | Shift + arrow (1 mm), Ctrl + Shift + arrow (0.1 mm) |

### Development

See [Entwicklung](#entwicklung).

### License

GPL-3.0-or-later. The shipped text recognition models are [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) 4.1.0 (Apache-2.0).

Independent project, not affiliated with DIN, IEC or VDE. DIN is a registered trademark of DIN e.V., DXF a trademark of Autodesk, Inc. The standards themselves are not included.
