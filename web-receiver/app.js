/**
 * ChirpDrop - Browser Acoustic Receiver Application
 * --------------------------------------------------
 * Real-time audio demodulation, GGWave WebAssembly interface, and binary packet
 * validation optimized for Android Google Chrome and iPhone Safari.
 */

(function () {
    'use strict';

    // Target native sample rate required by GGWave engine
    const TARGET_SAMPLE_RATE = 48000;
    const TARGET_BLOCK_SIZE = 1024; // 1024 float32 samples = 4096 bytes

    // DOM Elements
    const toggleBtn = document.getElementById('toggleBtn');
    const btnIcon = document.getElementById('btnIcon');
    const btnText = document.getElementById('btnText');
    const statusBadge = document.getElementById('statusBadge');
    const statusText = document.getElementById('statusText');
    const meterBar = document.getElementById('meterBar');
    const meterDb = document.getElementById('meterDb');
    const messagesList = document.getElementById('messagesList');
    const emptyState = document.getElementById('emptyState');
    const clearBtn = document.getElementById('clearBtn');
    const insecureBanner = document.getElementById('insecureBanner');
    const insecureMessage = document.getElementById('insecureMessage');
    const permissionBanner = document.getElementById('permissionBanner');
    const permissionMessage = document.getElementById('permissionMessage');
    const diagModem = document.getElementById('diagModem');
    const diagSampleRate = document.getElementById('diagSampleRate');
    const diagPlatform = document.getElementById('diagPlatform');
    const diagOffline = document.getElementById('diagOffline');

    // Web Audio & GGWave State
    let audioContext = null;
    let mediaStream = null;
    let recorderNode = null;
    let muteGainNode = null;
    let wakeLock = null;
    let isListening = false;

    let ggwave = null;
    let ggwaveParameters = null;
    let ggwaveInstance = null;
    let resampler = null;

    // Deduplication tracking
    let lastDecodedStr = null;
    let lastDecodedTimestamp = 0;
    let lastDecodedSeq = -1;

    // Transient status timer
    let statusResetTimer = null;

    /**
     * Inspect platform and browser environment for tailored UX and diagnostics.
     */
    function getPlatformDetails() {
        const ua = navigator.userAgent || '';
        const isAndroid = /Android/i.test(ua);
        const isIOS = /iPhone|iPad|iPod/i.test(ua);
        let name = 'Desktop Browser';

        if (isAndroid) {
            name = /Chrome/i.test(ua) ? 'Android (Chrome)' : 'Android Browser';
        } else if (isIOS) {
            name = 'iPhone / iOS (Safari)';
        } else if (/Chrome/i.test(ua)) {
            name = 'Desktop (Chrome)';
        } else if (/Safari/i.test(ua)) {
            name = 'Desktop (Safari)';
        } else if (/Firefox/i.test(ua)) {
            name = 'Desktop (Firefox)';
        }
        return { isAndroid, isIOS, name };
    }

    /**
     * Phase-continuous audio stream resampler.
     * Converts arbitrary hardware microphone rates (e.g. 44.1 kHz, 16 kHz) to 48.0 kHz
     * and batches output samples into fixed 1024-sample blocks required by GGWave.
     */
    class AudioStreamResampler {
        constructor(inRate, outRate) {
            this.inRate = inRate;
            this.outRate = outRate;
            this.ratio = inRate / outRate;
            this.pos = 0.0;
            this.inBuffer = new Float32Array(0);
            this.outBuffer = [];
        }

        process(inChunk, targetBlockSize = TARGET_BLOCK_SIZE) {
            if (this.inRate === this.outRate) {
                return [inChunk];
            }

            const newBuf = new Float32Array(this.inBuffer.length + inChunk.length);
            newBuf.set(this.inBuffer, 0);
            newBuf.set(inChunk, this.inBuffer.length);

            while (this.pos + 1 < newBuf.length) {
                const i0 = Math.floor(this.pos);
                const frac = this.pos - i0;
                const s0 = newBuf[i0];
                const s1 = newBuf[i0 + 1];
                this.outBuffer.push(s0 * (1.0 - frac) + s1 * frac);
                this.pos += this.ratio;
            }

            const consumed = Math.floor(this.pos);
            this.pos -= consumed;
            this.inBuffer = newBuf.slice(consumed);

            const readyBlocks = [];
            while (this.outBuffer.length >= targetBlockSize) {
                const block = new Float32Array(this.outBuffer.splice(0, targetBlockSize));
                readyBlocks.push(block);
            }

            return readyBlocks;
        }

        reset() {
            this.pos = 0.0;
            this.inBuffer = new Float32Array(0);
            this.outBuffer = [];
        }
    }

    /**
     * Convert typed arrays to pass PCM data to Emscripten WebAssembly.
     */
    function convertTypedArray(src, TargetType) {
        const buffer = new ArrayBuffer(src.byteLength);
        new src.constructor(buffer).set(src);
        return new TargetType(buffer);
    }

    /**
     * Inspect security context. Both Android Chrome and iOS Safari strictly
     * deny getUserMedia over plain HTTP on LAN IPs.
     */
    function checkSecurityContext() {
        const isLocalhost = Boolean(
            location.hostname === 'localhost' ||
            location.hostname === '127.0.0.1' ||
            location.hostname === '[::1]'
        );
        const isSecure = window.isSecureContext || location.protocol === 'https:' || isLocalhost;
        if (!isSecure) {
            const { isAndroid } = getPlatformDetails();
            const browserName = isAndroid ? 'Android Chrome' : 'Mobile Safari';
            if (insecureMessage) {
                insecureMessage.innerHTML = `Microphone capture is blocked over unencrypted HTTP by ${browserName}. Please load this application via <strong>HTTPS</strong> or through <strong>GitHub Pages</strong>.`;
            }
            insecureBanner.style.display = 'block';
        }
    }

    /**
     * Initialize GGWave WebAssembly module.
     */
    async function initGgWaveModule() {
        try {
            if (typeof ggwave_factory !== 'function') {
                throw new Error('ggwave_factory is not defined. Ensure ggwave.js is loaded.');
            }
            diagModem.textContent = 'Loading WebAssembly...';
            ggwave = await ggwave_factory();
            diagModem.textContent = 'GGWave Wasm Ready';
            console.log('[ChirpDrop] GGWave WebAssembly initialized successfully.');
        } catch (err) {
            console.error('[ChirpDrop] Failed to load GGWave:', err);
            diagModem.textContent = 'Modem Error: ' + err.message;
            statusText.textContent = 'Status: Modem initialization failed';
        }
    }

    /**
     * Format timestamp as HH:MM:SS AM/PM.
     */
    function formatTime(date) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    /**
     * Update the live audio volume indicator bar.
     */
    function updateMeter(rms) {
        const clampedRms = Math.min(1.0, rms * 5.0);
        const percent = Math.round(clampedRms * 100);
        meterBar.style.width = percent + '%';

        if (rms > 0.0001) {
            const db = Math.round(20 * Math.log10(rms));
            meterDb.textContent = `${db} dB`;
        } else {
            meterDb.textContent = '-∞ dB';
        }
    }

    /**
     * Set active status message with optional auto-revert to listening state.
     */
    function setStatus(text, revertDelayMs = 0) {
        if (statusResetTimer) {
            clearTimeout(statusResetTimer);
            statusResetTimer = null;
        }

        statusText.textContent = text;

        if (revertDelayMs > 0 && isListening) {
            statusResetTimer = setTimeout(() => {
                if (isListening) {
                    const rateText = audioContext.sampleRate === TARGET_SAMPLE_RATE ? '48,000 Hz' : `resampled from ${audioContext.sampleRate.toLocaleString()} Hz`;
                    statusText.textContent = `Status: Listening for nearby transmissions... (${rateText})`;
                }
            }, revertDelayMs);
        }
    }

    /**
     * Render a verified ChirpDrop message card in the UI.
     * Strictly rejects and does not display invalid/corrupted packets.
     */
    function renderMessageCard(packetResult) {
        // Enforce: Display only packets that pass validation
        if (!packetResult || !packetResult.isValid) {
            console.warn('[ChirpDrop] Ignored invalid/corrupted packet:', packetResult ? packetResult.error : 'Null packet');
            setStatus('Status: Discarded invalid acoustic packet (checksum failed)', 2500);
            return;
        }

        if (emptyState && emptyState.parentElement) {
            emptyState.style.display = 'none';
        }

        const card = document.createElement('article');
        card.className = 'message-card';

        const timeStr = formatTime(packetResult.timestamp || new Date());
        const crcHex = '0x' + packetResult.checksum.toString(16).toUpperCase().padStart(4, '0');

        card.innerHTML = `
            <div class="card-top">
                <div class="card-title">
                    <span>🔊</span>
                    <span>MESSAGE RECEIVED</span>
                </div>
                <div class="card-time">${timeStr}</div>
            </div>
            <div class="card-body-text">${escapeHtml(packetResult.text)}</div>
            <div class="card-validation">
                <span>✓</span>
                <span>Packet validation: Successful</span>
            </div>
            <div class="card-meta">
                <span>Seq #${packetResult.sequenceId}</span>
                <span>CRC: ${crcHex}</span>
                <span>Size: ${packetResult.payloadSize} bytes</span>
                <span>Opcode: ${packetResult.opcodeName || 'DATA'}</span>
            </div>
        `;

        // Insert at the top of the message list
        messagesList.insertBefore(card, messagesList.firstChild);

        // Update status badge
        setStatus(`Status: Message received and validated! (Seq #${packetResult.sequenceId})`, 3000);

        // Haptic feedback (supported natively on Android Chrome and modern iOS)
        if ('vibrate' in navigator) {
            try { navigator.vibrate(80); } catch { /* ignore */ }
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    /**
     * Process raw text extracted by GGWave.
     */
    function handleDemodulatedText(text) {
        const now = Date.now();

        // Decode Base64 binary packet first to obtain sequence number
        const packetResult = window.ChirpDropPacket.decodePacket(text);

        // If invalid, do not display per requirement: "Display only packets that pass validation"
        if (!packetResult.isValid) {
            console.warn('[ChirpDrop] Acoustic packet validation error:', packetResult.error);
            setStatus(`Status: Corrupted packet ignored (${packetResult.error})`, 2500);
            return;
        }

        // Deduplication: prevent duplicate display if identical text within 2000ms
        // or same sequence ID within 2500ms
        if ((text === lastDecodedStr && (now - lastDecodedTimestamp) < 2000) ||
            (packetResult.sequenceId === lastDecodedSeq && (now - lastDecodedTimestamp) < 2500)) {
            console.log('[ChirpDrop] Ignored duplicate chirp within debounce window.');
            return;
        }

        lastDecodedStr = text;
        lastDecodedSeq = packetResult.sequenceId;
        lastDecodedTimestamp = now;

        console.log('[ChirpDrop] Demodulated validated packet from acoustic channel:', text);
        renderMessageCard(packetResult);
    }

    /**
     * Start acoustic listening via Web Audio API.
     * Only executed after direct user gesture (tap/click).
     */
    async function startListening() {
        permissionBanner.style.display = 'none';

        if (!ggwave) {
            alert('GGWave modem is still initializing. Please wait a moment and try again.');
            return;
        }

        try {
            // 1. Create or resume AudioContext following user gesture
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (!audioContext) {
                try {
                    audioContext = new AudioContextClass({ sampleRate: TARGET_SAMPLE_RATE });
                } catch {
                    audioContext = new AudioContextClass();
                }
            }
            if (audioContext.state === 'suspended') {
                await audioContext.resume();
            }

            // Handle system interruptions on mobile (e.g. phone call or backgrounding)
            audioContext.onstatechange = () => {
                console.log('[ChirpDrop] AudioContext state changed to:', audioContext.state);
                if (audioContext.state === 'suspended' && isListening) {
                    statusText.textContent = 'Status: Audio paused by system (tap to resume)';
                }
            };

            const actualRate = audioContext.sampleRate;
            if (actualRate === TARGET_SAMPLE_RATE) {
                diagSampleRate.textContent = `${actualRate.toLocaleString()} Hz (Native)`;
                resampler = null;
            } else {
                diagSampleRate.textContent = `${actualRate.toLocaleString()} Hz → ${TARGET_SAMPLE_RATE.toLocaleString()} Hz`;
                resampler = new AudioStreamResampler(actualRate, TARGET_SAMPLE_RATE);
                console.log(`[ChirpDrop] Software resampler active: ${actualRate} Hz -> ${TARGET_SAMPLE_RATE} Hz`);
            }

            // 2. Request microphone stream with clean acoustic constraints & Android fallback
            let stream = null;
            const preferredConstraints = {
                audio: {
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false,
                    channelCount: 1,
                }
            };

            try {
                stream = await navigator.mediaDevices.getUserMedia(preferredConstraints);
            } catch (constraintErr) {
                console.warn('[ChirpDrop] Preferred acoustic audio constraints failed, retrying with fallback audio constraints:', constraintErr);
                // Fallback for Android devices with strict OEM audio layers that reject constraint options
                stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            }
            mediaStream = stream;

            // 3. Initialize GGWave instance with native 48,000 Hz processing parameters
            if (!ggwaveInstance) {
                ggwaveParameters = ggwave.getDefaultParameters();
                ggwaveParameters.sampleRateInp = TARGET_SAMPLE_RATE;
                ggwaveParameters.sampleRate = TARGET_SAMPLE_RATE;
                ggwaveParameters.sampleRateOut = TARGET_SAMPLE_RATE;
                ggwaveInstance = ggwave.init(ggwaveParameters);

                // Enable Protocol 1 (Audible Fast) and Protocol 0 (Audible Normal)
                try {
                    ggwave.rxToggleProtocol(1, 1);
                    ggwave.rxToggleProtocol(0, 1);
                } catch (e) {
                    console.warn('[ChirpDrop] rxToggleProtocol note:', e);
                }
            } else if (resampler) {
                resampler.reset();
            }

            // 4. Request Screen WakeLock to keep Android Chrome and iOS Safari active
            if ('wakeLock' in navigator) {
                try {
                    wakeLock = await navigator.wakeLock.request('screen');
                    wakeLock.addEventListener('release', () => {
                        console.log('[ChirpDrop] Screen WakeLock was released.');
                    });
                    console.log('[ChirpDrop] Screen WakeLock acquired.');
                } catch (e) {
                    console.debug('[ChirpDrop] WakeLock not granted:', e);
                }
            }

            // 5. Set up Web Audio processing graph
            const mediaSource = audioContext.createMediaStreamSource(mediaStream);
            const bufferSize = TARGET_BLOCK_SIZE;
            const inputChannels = 1;
            const outputChannels = 1;

            if (audioContext.createScriptProcessor) {
                recorderNode = audioContext.createScriptProcessor(bufferSize, inputChannels, outputChannels);
            } else if (audioContext.createJavaScriptNode) {
                recorderNode = audioContext.createJavaScriptNode(bufferSize, inputChannels, outputChannels);
            } else {
                throw new Error('Web Audio ScriptProcessorNode is not supported in this browser.');
            }

            // Mute gain node (gain = 0) to prevent acoustic feedback loop on phone speakers
            muteGainNode = audioContext.createGain();
            muteGainNode.gain.setValueAtTime(0, audioContext.currentTime);

            // Audio processing loop
            recorderNode.onaudioprocess = function (e) {
                if (!isListening) return;

                const channelData = e.inputBuffer.getChannelData(0);

                // Compute RMS for live meter
                let sum = 0.0;
                for (let i = 0; i < channelData.length; i++) {
                    sum += channelData[i] * channelData[i];
                }
                const rms = Math.sqrt(sum / channelData.length);
                updateMeter(rms);

                // Show transient signal detection status if sound is above ambient threshold
                if (rms > 0.04 && (!statusResetTimer)) {
                    statusText.textContent = 'Status: Acoustic signal detected, analyzing...';
                }

                // Resample to 48 kHz if needed and slice into 1024-sample blocks
                const blocks = resampler ? resampler.process(channelData, TARGET_BLOCK_SIZE) : [channelData];

                for (const block of blocks) {
                    try {
                        const int8Buffer = convertTypedArray(new Float32Array(block), Int8Array);
                        const decodedBytes = ggwave.decode(ggwaveInstance, int8Buffer);

                        if (decodedBytes && decodedBytes.length > 0) {
                            const decodedStr = new TextDecoder('utf-8').decode(decodedBytes);
                            if (decodedStr && decodedStr.trim().length > 0) {
                                handleDemodulatedText(decodedStr.trim());
                            }
                        }
                    } catch (err) {
                        console.warn('[ChirpDrop] Demodulation decode cycle exception:', err);
                    }
                }
            };

            // Connect nodes: MediaStream -> Recorder -> MuteGain -> Destination
            mediaSource.connect(recorderNode);
            recorderNode.connect(muteGainNode);
            muteGainNode.connect(audioContext.destination);

            // Update UI State
            isListening = true;
            toggleBtn.classList.add('listening');
            btnIcon.textContent = '⏹️';
            btnText.textContent = 'STOP LISTENING';

            statusBadge.classList.add('listening');
            const rateLabel = actualRate === TARGET_SAMPLE_RATE ? '48,000 Hz' : `resampled from ${actualRate.toLocaleString()} Hz`;
            statusText.textContent = `Status: Listening for nearby transmissions... (${rateLabel})`;

            console.log(`[ChirpDrop] Acoustic receiver started. Hardware rate: ${actualRate} Hz`);

        } catch (err) {
            console.error('[ChirpDrop] Microphone activation error:', err);
            isListening = false;
            updateMeter(0);

            const { isAndroid, isIOS } = getPlatformDetails();
            const permMsg = document.getElementById('permissionMessage');

            if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                if (permMsg) {
                    if (isAndroid) {
                        permMsg.innerHTML = `Chrome blocked microphone access.<br>
                        • Tap the <strong>tune / lock icon 🔒</strong> in Chrome’s address bar → <strong>Permissions → Microphone → Allow</strong>.<br>
                        • Or open Android <strong>Settings → Apps → Chrome → Permissions → Microphone → Allow</strong>.<br>
                        Then tap <strong>Start Listening</strong> again.`;
                    } else if (isIOS) {
                        permMsg.innerHTML = `Safari blocked microphone access.<br>
                        Open iPhone <strong>Settings → Safari → Microphone → Allow</strong>, then refresh this page.`;
                    } else {
                        permMsg.innerHTML = `Microphone access was denied. Please allow microphone permissions in your browser’s site settings, then tap Start Listening again.`;
                    }
                }
                permissionBanner.style.display = 'block';
                statusText.textContent = 'Status: Microphone access denied';
            } else if (err.name === 'NotFoundError') {
                if (permMsg) {
                    permMsg.innerHTML = `No microphone hardware detected on this device. Please connect an audio input device and try again.`;
                }
                permissionBanner.style.display = 'block';
                statusText.textContent = 'Status: Microphone not found';
            } else if (err.name === 'NotReadableError') {
                if (permMsg) {
                    permMsg.innerHTML = `The microphone is currently busy or locked by another app (e.g. active phone call, voice recorder, or meeting). Please close other audio apps and try again.`;
                }
                permissionBanner.style.display = 'block';
                statusText.textContent = 'Status: Microphone busy';
            } else {
                alert(`Could not start acoustic listener: ${err.message}`);
                statusText.textContent = `Status: Error (${err.name || 'Unknown'})`;
            }
        }
    }

    /**
     * Stop acoustic listening.
     */
    function stopListening() {
        isListening = false;

        if (statusResetTimer) {
            clearTimeout(statusResetTimer);
            statusResetTimer = null;
        }

        if (wakeLock) {
            try { wakeLock.release(); } catch {}
            wakeLock = null;
        }

        if (recorderNode) {
            try { recorderNode.disconnect(); } catch { /* ignore */ }
            recorderNode = null;
        }

        if (muteGainNode) {
            try { muteGainNode.disconnect(); } catch { /* ignore */ }
            muteGainNode = null;
        }

        if (mediaStream) {
            try { mediaStream.getTracks().forEach(track => track.stop()); } catch { /* ignore */ }
            mediaStream = null;
        }

        if (resampler) {
            resampler.reset();
        }

        updateMeter(0);

        // Update UI
        toggleBtn.classList.remove('listening');
        btnIcon.textContent = '🎙️';
        btnText.textContent = 'START LISTENING';

        statusBadge.classList.remove('listening');
        statusText.textContent = 'Status: Not listening';

        console.log('[ChirpDrop] Acoustic receiver stopped.');
    }

    // Toggle button listener
    toggleBtn.addEventListener('click', function () {
        if (!isListening) {
            startListening();
        } else {
            stopListening();
        }
    });

    // Clear messages listener
    clearBtn.addEventListener('click', function () {
        messagesList.innerHTML = '';
        if (emptyState) {
            emptyState.style.display = 'flex';
            messagesList.appendChild(emptyState);
        }
    });

    // Mobile backgrounding & tab switching recovery (Android Chrome & iOS Safari)
    document.addEventListener('visibilitychange', async () => {
        if (document.visibilityState === 'visible' && isListening) {
            console.log('[ChirpDrop] App returned to foreground. Checking audio state...');
            if (audioContext && audioContext.state === 'suspended') {
                try {
                    await audioContext.resume();
                    console.log('[ChirpDrop] AudioContext successfully resumed after visibility change.');
                } catch (e) {
                    console.warn('[ChirpDrop] Could not resume AudioContext on visibility change:', e);
                }
            }
            // Re-acquire screen wake lock on Android/iOS if released
            if ('wakeLock' in navigator && (!wakeLock || wakeLock.released)) {
                try {
                    wakeLock = await navigator.wakeLock.request('screen');
                    console.log('[ChirpDrop] Re-acquired screen wake lock.');
                } catch (e) {}
            }
        }
    });

    // Offline Service Worker Registration
    function registerServiceWorker() {
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('./sw.js', { scope: './' })
                .then((reg) => {
                    console.log('[ChirpDrop] Service Worker registered with scope:', reg.scope);
                    diagOffline.textContent = 'Offline Ready (PWA)';
                    diagOffline.style.color = 'var(--accent-emerald)';
                })
                .catch((err) => {
                    console.warn('[ChirpDrop] Service Worker registration failed:', err);
                    diagOffline.textContent = 'Online Only';
                });
        } else {
            diagOffline.textContent = 'ServiceWorker unsupported';
        }
    }

    // Page Lifecycle Initialization
    window.addEventListener('DOMContentLoaded', () => {
        const platform = getPlatformDetails();
        if (diagPlatform) {
            diagPlatform.textContent = platform.name;
        }
        checkSecurityContext();
        initGgWaveModule();
        registerServiceWorker();
    });

})();
