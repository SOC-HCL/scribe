# Scribe Docker Compose Setup Guide

## Prerequisites

### Windows
- Docker Desktop for Windows (with WSL 2 backend recommended)
- PowerShell 5.1 or later
- OpenSSL (optional, for manual certificate generation)

### Linux/Mac
- Docker and Docker Compose installed
- OpenSSL (usually pre-installed)
- Bash shell

## Setup Steps

### 1. Generate Self-Signed Certificate

Run the appropriate script for your platform:

**Windows:**
```powershell
.\generate-selfsigned-cert.ps1
```

**Linux/Mac:**
```bash
bash ./generate-selfsigned-cert.sh
```

This creates a self-signed certificate valid for 1 year in `traefik/certs/`.

### 2. Configure Environment (Optional)

Create a `.env` file in the project root to customize settings:

```env
# Scribe Configuration
SCRIBE_HOST=localhost
SCRIBE_IA_PROVIDER=albert
SCRIBE_IA_KEY=your-key-here
SCRIBE_SECRET=your-secret-here
ADMIN_PASSWORD=your-password-here
LOG_LEVEL=info

# CORS Origins (add your server's IP/hostname)
CORS_ORIGINS=http://localhost,https://localhost,http://192.168.1.100,https://192.168.1.100
```

### 3. Start Services

```bash
docker compose up -d
```

### 4. Access Scribe

- **HTTP:** http://localhost
- **HTTPS:** https://localhost (with self-signed certificate warning)
- **Traefik Dashboard:** http://localhost:8080

## Accessing from Network

To access Scribe from other computers on your hospital LAN:

1. Find your server's IP address:
   - Windows: `ipconfig` 
   - Linux/Mac: `ip addr` or `ifconfig`

2. Set `SCRIBE_HOST` in `.env`:
   ```env
   SCRIBE_HOST=192.168.1.100
   ```

3. Update `CORS_ORIGINS` in `.env` to include your server's IP

4. Restart services:
   ```bash
   docker compose down
   docker compose up -d
   ```

5. Access from another computer:
   ```
   https://192.168.1.100
   ```

## Stopping Services

```bash
docker compose down
```

## Troubleshooting

### Certificate file not found
- Ensure you ran the certificate generation script before starting services
- On Windows, check that `traefik/certs/` directory exists with `scribe.crt` and `scribe.key`

### Network not found error
- This is normal on first run; services will eventually connect

### Connection refused on port 443
- Ensure port 443 is not blocked by firewall
- Check that the certificate files exist in `traefik/certs/`

### Containers not communicating
- Verify all services are on the same network: `docker network inspect scribe_default`
- Check service names in compose file match references

## Cross-Platform Compatibility

This setup is tested on:
- Windows 10/11 with Docker Desktop (WSL 2 backend)
- Ubuntu 20.04+ with Docker Engine

The configuration uses:
- Forward slashes in paths (compatible with all platforms)
- Standard Docker socket paths (abstracted by Docker Desktop on Windows)
- Portable shell commands

## Security Notes

- **Development Only:** The Traefik dashboard is exposed on port 8080
- **Self-Signed Certificates:** Browsers will show security warnings (expected)
- **Production Deployment:** 
  - Disable insecure Traefik API
  - Use proper HTTPS certificates (Let's Encrypt via ACME)
  - Restrict network access appropriately
  - Update default passwords in `.env`

## File Structure

```
scribe/
├── docker-compose.yml
├── .env                              (create manually)
├── generate-selfsigned-cert.ps1      (Windows)
├── generate-selfsigned-cert.sh       (Linux/Mac)
├── traefik/
│   ├── traefik.yml                  (Traefik configuration)
│   ├── dynamic.yml                  (Dynamic routing config)
│   ├── certs/                       (Generated certificates)
│   │   ├── scribe.crt
│   │   └── scribe.key
│   └── README.md
├── scribe/
│   ├── main.py
│   ├── Dockerfile
│   └── ...
└── ...
```
