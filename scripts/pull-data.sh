#!/usr/bin/env bash
# Download the latest scored database from the private data repo into out/.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p out
GH_TOKEN="$(gh auth token --user mindmelding)" \
  gh release download data-latest -R mindmelding/split-code-data \
  -p signals.db.gz -O out/signals.db.gz --clobber
rm -f out/signals.db-wal out/signals.db-shm
gunzip -f out/signals.db.gz
echo "out/signals.db updated"
