#!/bin/sh
set -eu

CERT_DIR="/etc/nginx/certs"
CERT_FILE="${SSL_CERT_FILE:-$CERT_DIR/fullchain.pem}"
KEY_FILE="${SSL_KEY_FILE:-$CERT_DIR/privkey.pem}"
SELF_SIGNED_CN="${SSL_SELF_SIGNED_CN:-localhost}"
SELF_SIGNED_DAYS="${SSL_SELF_SIGNED_DAYS:-365}"

if [ ! -s "$CERT_FILE" ] || [ ! -s "$KEY_FILE" ]; then
  echo "[nginx] TLS certificate not found. Generating fallback self-signed certificate for ${SELF_SIGNED_CN}."
  mkdir -p "$CERT_DIR"
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -days "$SELF_SIGNED_DAYS" \
    -subj "/CN=${SELF_SIGNED_CN}" >/dev/null 2>&1
fi
