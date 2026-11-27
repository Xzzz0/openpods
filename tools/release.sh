#!/bin/bash
# Publishes a new OpenPods version – everyone running OpenPods then gets the update offered.
#
#   tools/release.sh 1.1.0            bump the version, merge that through a pull request, tag v1.1.0, GitHub release
#   tools/release.sh 1.1.0 notes.md   same, with your own release notes (default: generated from the merged PRs)
#   tools/release.sh 1.0.0            the version the code already has: only tag + release (first release)
#
# Needs: gh (logged in), a clean checkout on main that matches origin/main.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

VERSION="${1:-}"
NOTES="${2:-}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "usage: tools/release.sh X.Y.Z [notes.md]" >&2; exit 2; }
[ -z "$NOTES" ] || [ -f "$NOTES" ] || { echo "notes file not found: $NOTES" >&2; exit 2; }
CURRENT="$(python3 -c 'import openpods; print(openpods.__version__)')"
python3 - "$CURRENT" "$VERSION" <<'PY' || { echo "version must not be lower than $CURRENT" >&2; exit 2; }
import sys
a, b = (tuple(map(int, v.split("."))) for v in sys.argv[1:])
sys.exit(0 if b >= a else 1)
PY
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "switch to main first" >&2; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "the checkout has uncommitted changes" >&2; exit 1; }
git fetch -q origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main is not equal to origin/main (git pull?)" >&2; exit 1; }
git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null && { echo "tag v$VERSION exists already" >&2; exit 1; }

if [ "$VERSION" != "$CURRENT" ]; then
echo "==> OpenPods $CURRENT -> $VERSION"
BRANCH="release-v$VERSION"
git checkout -q -b "$BRANCH"
sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" openpods/__init__.py
git commit -q -am "Release $VERSION"
git push -q -u origin "$BRANCH"
gh pr create --base main --head "$BRANCH" --title "Release $VERSION" --body "Version $CURRENT → $VERSION." >/dev/null
# GitHub needs a moment to compute whether the PR can be merged
for i in 1 2 3 4 5 6 7 8 9 10; do
  gh pr merge "$BRANCH" --merge --delete-branch && break
  [ "$i" -eq 10 ] && { echo "merging the release PR failed – merge it on GitHub, then run: gh release create v$VERSION" >&2; exit 1; }
  sleep 3
done
git checkout -q main
git pull -q --ff-only origin main
git branch -q -D "$BRANCH" 2>/dev/null || true
fi

echo "==> GitHub release v$VERSION"
if [ -n "$NOTES" ]; then
  gh release create "v$VERSION" --target "$(git rev-parse HEAD)" --title "OpenPods $VERSION" --notes-file "$NOTES"
else
  gh release create "v$VERSION" --target "$(git rev-parse HEAD)" --title "OpenPods $VERSION" --generate-notes
fi
git fetch -q --tags origin
echo "Done. OpenPods installations offer the update within 6 hours (or at their next start)."
