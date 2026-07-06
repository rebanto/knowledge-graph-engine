#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/deploy_hf.sh <user>/<space> [--force]

Pushes the current Git HEAD to the Hugging Face Docker Space main branch.
Requires HF_TOKEN in the environment. Secrets are configured in the Space UI;
.env files are excluded by .dockerignore/.gitignore and are not pushed.
USAGE
}

space_id=""
force=false

for arg in "$@"; do
  case "$arg" in
    --force)
      force=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ -z "$space_id" ]; then
        space_id="$arg"
      else
        usage
        exit 2
      fi
      ;;
  esac
done

if [ -z "$space_id" ]; then
  space_id="${HF_SPACE_ID:-}"
fi
if [ -z "$space_id" ] || [[ "$space_id" != */* ]]; then
  usage
  exit 2
fi
if [ -z "${HF_TOKEN:-}" ]; then
  echo "HF_TOKEN is required." >&2
  exit 1
fi

owner="${space_id%%/*}"
remote_url="https://${owner}:${HF_TOKEN}@huggingface.co/spaces/${space_id}.git"

echo "Pushing current HEAD to Hugging Face Space ${space_id}..."
push_args=("HEAD:main")
if [ "$force" = true ]; then
  push_args+=("--force")
fi
git push "$remote_url" "${push_args[@]}"
echo "Deploy pushed. Watch the Space build logs in Hugging Face."
