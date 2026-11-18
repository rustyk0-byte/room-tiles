#!/bin/sh
# Room Tiles' GitHub settings for outside contributions (the standard fork +
# pull request flow) - run once the repository is public (branch rules need
# a public repository or a paid plan):
#
#   tools/github/protect-main.sh <owner>/<repo>
#
# - main only changes through a pull request that the code owner
#   (.github/CODEOWNERS) approved - approval again after any new push;
#   never force-pushed or deleted. Repository admins (the maintainer) may
#   push directly (bypass).
# - Workflows on a pull request from anyone outside the repository wait for
#   the maintainer's OK before they run.
# - Merged branches are deleted.
# Status checks aren't required by the rule: the workflows only run when
# their files change, and a required check that never runs would block the
# merge. The reviewer sees them on the pull request.
# Safe to run again (the rule is updated, not added twice).
set -eu
REPO="${1:?usage: tools/github/protect-main.sh <owner>/<repo>}"
RULES="$(dirname "$0")/main-ruleset.json"

ID=$(gh api "repos/$REPO/rulesets" --jq '.[] | select(.name == "Protect main") | .id')
if [ -n "$ID" ]; then
  gh api -X PUT "repos/$REPO/rulesets/$ID" --input "$RULES" > /dev/null
  echo "Updated the main branch rule"
else
  gh api -X POST "repos/$REPO/rulesets" --input "$RULES" > /dev/null
  echo "Added the main branch rule"
fi
gh api -X PUT "repos/$REPO/actions/permissions/fork-pr-contributor-approval" \
  -f approval_policy=all_external_contributors > /dev/null
echo "Workflows from outside contributors wait for approval"
gh api -X PATCH "repos/$REPO" -F delete_branch_on_merge=true > /dev/null
echo "Merged branches are deleted"
