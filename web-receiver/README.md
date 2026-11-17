# ChirpDrop - Web Acoustic Receiver (iPhone Safari & Mobile PWA)

A lightweight, self-contained, offline-first acoustic message receiver designed for **iPhone Safari** and modern mobile browsers.

Communicates with the ChirpDrop Python desktop sender across an **air-gap using only sound waves** (built-in laptop speaker → iPhone microphone).

---

## Features

- **No Native App Needed**: Runs directly in iPhone Safari as a Progressive Web App (PWA).
- **Embedded WebAssembly Modem**: Uses an offline-bundled GGWave WebAssembly decoder (`ggwave.js`). No external CDNs required at runtime.
- **Strict Packet Framing & CRC Verification**: Deserializes Base64 into binary packets (`CD\x01` magic preamble, Opcode `0x02` DATA, Sequence ID, CRC-16 checksum matching Python `zlib.crc32(...) & 0xFFFF`).
- **Feedback Suppression**: Feeds microphone PCM into Web Audio with a zero-gain mute node to prevent phone speaker feedback / howling.
- **Air-Gapped & Offline Ready**: Once cached by the Service Worker (`sw.js`), the receiver functions with **Wi-Fi, Cellular, and Bluetooth completely disabled**.

---

## File Structure

```text
web-receiver/
├── index.html           # Mobile UI (Header, Start Listening button, Message cards)
├── styles.css           # Mobile-first stylesheet with iOS dark aesthetic
├── app.js               # Web Audio API engine, microphone capture, UI controller
├── packet.js            # Binary packet deserializer & CRC-32/CRC-16 validation
├── ggwave.js            # Standalone WebAssembly acoustic modem engine
├── manifest.json        # PWA Web App Manifest for "Add to Home Screen"
├── sw.js                # Service Worker for offline caching
├── icon.svg             # Vector soundwave logo
├── icon-192.png         # 192x192 app icon
├── icon-512.png         # 512x512 app icon
├── serve.py             # Local development server script
└── README.md            # This documentation
```

---

## How to Run & Deploy

### Option 1: GitHub Pages via GitHub Actions (Recommended)

This repository includes an automated workflow (`.github/workflows/deploy-pages.yml`) that deploys only `web-receiver/` with an automatic, valid SSL certificate:

1. Push your repository to GitHub:
   ```bash
   git init
   git add .
   git commit -m "ChirpDrop v0.1.0 with Web Receiver"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```
2. In your GitHub repository:
   - Go to **Settings** → **Pages**.
   - Under **Build and deployment** → **Source**, select **GitHub Actions**.
3. The workflow will automatically build and publish `web-receiver/`.
4. Open the published GitHub Pages URL on iPhone Safari:
   ```text
   https://<your-username>.github.io/<your-repo>/
   ```

### Option 2: Local Network HTTPS (Local Development)

If testing on the same local Wi-Fi without deploying to GitHub:

1. Generate a temporary local SSL certificate in `web-receiver/`:
   ```powershell
   # Using openssl if available:
   openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
   ```
2. Start the local server:
   ```powershell
   .\.venv\Scripts\python.exe web-receiver/serve.py --ssl --port 8443
   ```
3. Open `https://<Laptop-LAN-IP>:8443` on iPhone Safari and accept the self-signed certificate warning.

---

## Testing Laptop → iPhone Acoustic Transmission

1. Open the receiver URL on your iPhone in Safari.
2. Tap **[ START LISTENING ]** and allow microphone access when prompted.
   - Status updates to: `Status: Listening for nearby transmissions...`
   - The acoustic level meter bar moves in real-time to ambient sound.
3. On your Windows laptop, open a terminal in the `ChirpDrop` folder and send a message:
   ```powershell
   .\.venv\Scripts\python.exe main.py send --text "Hello from ChirpDrop!"
   ```
4. Within 2-3 seconds of the chirp completing, your iPhone will display:
   ```text
   🔊 MESSAGE RECEIVED
   Hello from ChirpDrop!
   ✓ Packet validation: Successful
   Seq #1 | CRC: 0xCDBF | Size: 21 bytes | Opcode: DATA
   ```
5. You can now enable **Airplane Mode** on the iPhone and repeat the test — the web receiver continues to operate 100% offline.
