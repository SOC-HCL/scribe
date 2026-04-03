# Generate self-signed certificate for Traefik
# Run this script once before starting docker-compose

$certsDir = ".\traefik\certs"
$certFile = "$certsDir\scribe.crt"
$keyFile = "$certsDir\scribe.key"

# Create directory if it doesn't exist
if (-not (Test-Path $certsDir)) {
    New-Item -ItemType Directory -Path $certsDir -Force | Out-Null
    Write-Host "Created certificates directory: $certsDir"
}

# Check if certificates already exist
if ((Test-Path $certFile) -and (Test-Path $keyFile)) {
    Write-Host "Certificates already exist, skipping generation"
    exit 0
}

# Generate self-signed certificate using OpenSSL (if available in Windows)
try {
    # Try using openssl if available
    $env:OPENSSL_CONF = "NUL"
    openssl req -x509 -newkey rsa:2048 -keyout $keyFile -out $certFile -days 365 -nodes `
        -subj "/C=FR/ST=Local/L=Hospital/O=Healthcare/CN=scribe" 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Self-signed certificate generated successfully"
        Write-Host "Certificate: $certFile"
        Write-Host "Key: $keyFile"
        exit 0
    }
}
catch {
    Write-Host "OpenSSL not found, using PowerShell method..."
}

# Fallback: Use PowerShell to generate self-signed certificate
$cert = New-SelfSignedCertificate -DnsName "scribe", "localhost", "traefik" `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -NotAfter (Get-Date).AddYears(1) `
    -KeyExportPolicy Exportable `
    -Type SSLAuthenticationBinding

# Export certificate and private key
$pwd = ConvertTo-SecureString -String "temporary" -AsPlainText -Force
Export-PfxCertificate -Cert $cert -FilePath "$certsDir\scribe.pfx" -Password $pwd -Force | Out-Null

# Convert PFX to PEM format (certificate)
openssl pkcs12 -in "$certsDir\scribe.pfx" -out $certFile -nodes -nokeys -passin pass:temporary 2>$null

# Convert PFX to PEM format (key)
openssl pkcs12 -in "$certsDir\scribe.pfx" -out $keyFile -nodes -nocerts -passin pass:temporary 2>$null

# Clean up temporary PFX file
Remove-Item "$certsDir\scribe.pfx" -Force -ErrorAction SilentlyContinue

Write-Host "Self-signed certificate generated successfully"
Write-Host "Certificate: $certFile"
Write-Host "Key: $keyFile"
