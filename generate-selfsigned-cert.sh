#!/bin/bash
# Generate self-signed certificate for Traefik
# Run this script once before starting docker-compose on Linux/Mac

set -e

CERTS_DIR="./traefik/certs"
CERT_FILE="$CERTS_DIR/scribe.crt"
KEY_FILE="$CERTS_DIR/scribe.key"

# Create directory if it doesn't exist
mkdir -p "$CERTS_DIR"
echo "Certificates directory: $CERTS_DIR"

# Check if certificates already exist
if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "Certificates already exist, skipping generation"
    exit 0
fi

# Generate self-signed certificate using OpenSSL
if command -v openssl &> /dev/null; then
    echo "Generating self-signed certificate..."
    openssl req -x509 -newkey rsa:2048 -keyout "$KEY_FILE" -out "$CERT_FILE" \
        -days 365 -nodes \
        -subj "/C=FR/ST=Local/L=Hospital/O=Healthcare/CN=scribe"
    
    echo "Self-signed certificate generated successfully"
    echo "Certificate: $CERT_FILE"
    echo "Key: $KEY_FILE"
else
    echo "Error: OpenSSL not found. Please install OpenSSL to generate certificates."
    echo "On Ubuntu/Debian: sudo apt-get install openssl"
    echo "On Alpine: apk add openssl"
    echo "On macOS: brew install openssl"
    exit 1
fi
