#!/bin/bash
# Build dist/sldgridy_<version>_all.deb from the source tree.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG=sldgridy
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/src/$PKG/__init__.py")"
[ -n "$VERSION" ] || { echo "cannot read __version__" >&2; exit 1; }
# Python "1.2.3.dev4" becomes Debian "1.2.3~dev4", which sorts before "1.2.3".
VERSION="${VERSION/.dev/~dev}"

BUILD="$ROOT/build/deb"
STAGE="$BUILD/${PKG}_${VERSION}_all"
OUT="$ROOT/dist/${PKG}_${VERSION}_all.deb"

umask 022
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$ROOT/dist"

# Python module, without bytecode caches.
mkdir -p "$STAGE/usr/share/$PKG"
cp -r "$ROOT/src/$PKG" "$STAGE/usr/share/$PKG/$PKG"
find "$STAGE/usr/share/$PKG" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$STAGE/usr/share/$PKG" -name '*.pyc' -delete
# Library and templates live next to the module, not inside it.
rm -rf "$STAGE/usr/share/$PKG/$PKG/resources/library" "$STAGE/usr/share/$PKG/$PKG/resources/templates"

# Shipped symbol library and frame templates (filled in later milestones).
mkdir -p "$STAGE/usr/share/$PKG/library" "$STAGE/usr/share/$PKG/templates"
for d in library templates; do
    if [ -d "$ROOT/src/$PKG/resources/$d" ]; then
        cp -r "$ROOT/src/$PKG/resources/$d/." "$STAGE/usr/share/$PKG/$d/"
    fi
done
rmdir --ignore-fail-on-non-empty "$STAGE/usr/share/$PKG/library" "$STAGE/usr/share/$PKG/templates"

install -D -m 0755 "$ROOT/packaging/$PKG.sh" "$STAGE/usr/bin/$PKG"
install -D -m 0644 "$ROOT/packaging/$PKG.desktop" "$STAGE/usr/share/applications/$PKG.desktop"
install -D -m 0644 "$ROOT/packaging/$PKG.xml" "$STAGE/usr/share/mime/packages/$PKG.xml"
install -D -m 0644 "$ROOT/src/$PKG/resources/icons/$PKG.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/$PKG.svg"
install -D -m 0644 "$ROOT/packaging/copyright" "$STAGE/usr/share/doc/$PKG/copyright"
# Help > README shows the user guide offline.
install -D -m 0644 "$ROOT/README.md" "$STAGE/usr/share/$PKG/$PKG/resources/README.md"
mkdir -p "$STAGE/usr/share/man/man1"
gzip -9n -c "$ROOT/packaging/$PKG.1" > "$STAGE/usr/share/man/man1/$PKG.1.gz"

# Native package changelog, required by Debian policy.
CHANGELOG="$STAGE/usr/share/doc/$PKG/changelog.gz"
{
    echo "$PKG ($VERSION) unstable; urgency=medium"
    echo
    echo "  * Release $VERSION."
    echo
    echo " -- Glenn-Dandy <kewl0@arcor.de>  $(date -R -d "@$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)")"
} | gzip -9n > "$CHANGELOG"
chmod 0644 "$CHANGELOG"

find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE/usr/share" -type f -exec chmod 0644 {} +

INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Architecture: all
Section: graphics
Priority: optional
Maintainer: Glenn-Dandy <kewl0@arcor.de>
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.12), python3-pyqt6, python3-pyqt6.qtsvg, python3-pyqt6.qtpdf, python3-pdfminer, tesseract-ocr, tesseract-ocr-deu
Homepage: https://github.com/Glenn-Dandy/SLDGridy
Description: CAD-style editor for single-line electrical diagrams
 SLDGridy draws single-line diagrams for photovoltaic systems,
 transformer stations and low-voltage distribution boards. It works in
 millimetres with separate model and sheet layouts, grid and object snap,
 layers, reusable blocks, and prints or plots up to A0.
CONTROL

dpkg-deb --build --root-owner-group "$STAGE" "$OUT" >/dev/null
echo "$OUT"
