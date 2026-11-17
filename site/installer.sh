#!/bin/sh
# Installe Sésame depuis le dépôt APT unique de mawena : https://apt.mawena.cloud/
#   curl -fsSL https://mawena.github.io/sesame/installer.sh | sudo sh
# Depuis la 2.0.3, Sésame est publié dans le dépôt unique : ce script lance son installateur avec le paquet sesame.
# Équivaut à : curl -fsSL https://apt.mawena.cloud/installer.sh | sudo sh -s -- sesame
set -eu

INSTALLATEUR=https://apt.mawena.cloud/installer.sh

if [ "$(id -u)" -ne 0 ]; then
  echo "Sésame : à lancer en administrateur, par exemple : curl -fsSL $INSTALLATEUR | sudo sh -s -- sesame" >&2
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "Sésame : apt-get introuvable ; Sésame s'installe sur Ubuntu." >&2
  exit 1
fi

if command -v curl >/dev/null 2>&1; then curl -fsSL "$INSTALLATEUR" | sh -s -- sesame
elif command -v wget >/dev/null 2>&1; then wget -qO- "$INSTALLATEUR" | sh -s -- sesame
else echo "Sésame : il faut curl ou wget." >&2; exit 1
fi
echo
echo "Sésame est installé. Pour commencer : sesame-assistant (ou la commande sesame)."
