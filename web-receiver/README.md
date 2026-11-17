# ChirpDrop - Web Acoustic Receiver (Android Chrome & iPhone Safari PWA)

A lightweight, self-contained, offline-first acoustic message receiver designed for **Android Google Chrome**, **iPhone Safari**, and modern mobile browsers.

Communicates with the ChirpDrop Python desktop sender across an **air-gap using only sound waves** (built-in laptop speaker → smartphone microphone).

---

## Features

- **Cross-Platform Mobile PWA**: Runs directly in Android Chrome and iPhone Safari without installing native apps.
- **Embedded WebAssembly Modem**: Uses an offline-bundled GGWave WebAssembly decoder (`ggwave.js`). No external CDNs required at runtime.
- **Sample-Rate Adaptation (44.1 kHz & 48 kHz)**: Includes a phase-continuous streaming resampler that transparently converts hardware microphone rates to 48 kHz.
- **Strict Packet Framing & CRC Verification**: Deserializes Base64 into binary packets (`CD\x01` magic preamble, Opcode `0x02` DATA, Sequence ID, CRC-16 checksum matching Python `zlib.crc32(...) & 0xFFFF`).
- **Feedback Suppression**: Feeds microphone PCM into Web Audio with a zero-gain mute node to prevent phone speaker feedback / howling.
- **Background Interruption Recovery**: Automatically resumes the audio engine and re-acquires screen wake locks when returning to the browser tab.
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

## Testing Laptop → Smartphone Acoustic Transmission (Android & iPhone)

1. **Open the Receiver URL**:
   - On Android: Open Google Chrome and navigate to your deployed HTTPS URL (or local HTTPS server).
   - On iPhone: Open Safari and navigate to your deployed HTTPS URL.
2. **Start Listening**:
   - Tap **[ START LISTENING ]** and allow microphone access when prompted.
   - Status updates to: `Status: Listening for nearby transmissions...`
   - The green dot pulses and the **Acoustic Input Level** bar responds dynamically to ambient sound.
3. **Send from Windows Laptop**:
   - In your Windows terminal inside `ChirpDrop`:
     ```powershell
     .\.venv\Scripts\python.exe main.py send --text "Hello from ChirpDrop!"
     ```
4. **Immediate Reception**:
   - Within 1–2 seconds of the acoustic chirp ending, the smartphone screen will display:
     ```text
     🔊 MESSAGE RECEIVED
     Hello from ChirpDrop!
     ✓ Packet validation: Successful
     Seq #1 | CRC: 0xCDBF | Size: 21 bytes | Opcode: DATA
     ```
5. **Offline Verification**:
   - Turn on **Airplane Mode** on the Android phone or iPhone (disable Wi-Fi, Cellular, and Bluetooth).
   - Re-send any text message from the laptop — the phone receives, decodes, and validates the packet completely offline.
