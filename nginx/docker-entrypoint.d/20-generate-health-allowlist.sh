#!/bin/sh
set -eu

OUTPUT_FILE="/etc/nginx/conf.d/health-allowlist-map.conf"
ALLOWLIST="${HEALTHCHECK_ALLOWLIST_CIDRS:-127.0.0.1/32,::1/128}"

{
  echo "# Generated at container startup"
  echo "geo \$health_allowlisted {"
  echo "    default 0;"
} > "$OUTPUT_FILE"

valid_count=0
IFS=','
for cidr in $ALLOWLIST; do
  cidr_trimmed="$(echo "$cidr" | xargs)"
  if [ -z "$cidr_trimmed" ]; then
    continue
  fi

  case "$cidr_trimmed" in
    *[!0-9A-Fa-f:./]*)
      echo "[nginx] Skipping invalid CIDR token in HEALTHCHECK_ALLOWLIST_CIDRS: $cidr_trimmed" >&2
      continue
      ;;
  esac

  echo "    $cidr_trimmed 1;" >> "$OUTPUT_FILE"
  valid_count=$((valid_count + 1))
done
unset IFS

echo "}" >> "$OUTPUT_FILE"

if [ "$valid_count" -eq 0 ]; then
  echo "[nginx] No valid HEALTHCHECK_ALLOWLIST_CIDRS values were provided." >&2
  exit 1
fi
