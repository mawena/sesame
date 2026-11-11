#!/usr/bin/env bash
# Construit dist/sesame_<version>_all.deb : tests, paquet, sommes SHA-256, lintian.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Une seule version partout : debian/changelog et sesame version
deb_version="$(dpkg-parsechangelog -S Version)"
cli_version="$(python3 bin/sesame version | awk '{print $NF}')"
if [[ "$deb_version" != "$cli_version" ]]; then
  echo "Versions différentes : debian/changelog=$deb_version, sesame=$cli_version" >&2
  exit 1
fi

# Fichiers de bureau et metainfo valides (sans réseau) avant de construire
desktop-file-validate data/applications/*.desktop
appstreamcli validate --no-net data/metainfo/*.metainfo.xml

make clean >/dev/null
make test
dpkg-buildpackage -us -uc -b
make clean >/dev/null

mkdir -p dist
mv -f "../sesame_${deb_version}_all.deb" dist/
rm -f "../sesame_${deb_version}_"*.buildinfo "../sesame_${deb_version}_"*.changes
(cd dist && sha256sum ./*.deb | sed 's| \./| |' > SHA256SUMS)

# Lintian sans erreur ni avertissement
lintian -I --fail-on error,warning "dist/sesame_${deb_version}_all.deb"
echo "Paquet : dist/sesame_${deb_version}_all.deb"
