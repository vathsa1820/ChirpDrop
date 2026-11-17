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

    // DOM Elements - Main Controls
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

    // DOM Elements - Live Diagnostics (Step 5)
    const diagEngineStatus = document.getElementById('diagEngineStatus');
    const diagMicStatus = document.getElementById('diagMicStatus');
    const diagAudioState = document.getElementById('diagAudioState');
    const diagInRate = document.getElementById('diagInRate');
    const diagOutRate = document.getElementById('diagOutRate');
    const diagDbLevel = document.getElementById('diagDbLevel');
    const diagBlocksCount = document.getElementById('diagBlocksCount');
    const diagDecodeAttempts = document.getElementById('diagDecodeAttempts');
    const diagMessagesCount = document.getElementById('diagMessagesCount');
    const diagDspFilters = document.getElementById('diagDspFilters');

    // DOM Elements - Footer Status
    const diagModem = document.getElementById('diagModem');
    const diagSampleRate = document.getElementById('diagSampleRate');
    const diagPlatform = document.getElementById('diagPlatform');
    const diagOffline = document.getElementById('diagOffline');

    // Web Audio Graph State
    let audioContext = null;
    let mediaStream = null;
    let mediaSource = null;
    let recorderNode = null;
    let muteGainNode = null;
    let wakeLock = null;
    let isListening = false;

    // GGWave State
    let ggwave = null;
    let ggwaveParameters = null;
    let ggwaveInstance = null;
    let audioPipeline = null;

    // Live Metrics Counters
    let blocksProcessedCount = 0;
    let decodeAttemptsCount = 0;
    let messagesReceivedCount = 0;
    let lastUiThrottleTime = 0;

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
     * High-performance audio stream pipeline and phase-continuous resampler.
     * Converts arbitrary hardware microphone rates (e.g. 44.1 kHz, 48 kHz, 16 kHz)
     * to 48.0 kHz and guarantees emission of exact 1024-sample blocks (TARGET_BLOCK_SIZE)
     * required by the GGWave WebAssembly engine.
     *
     * Uses preallocated typed arrays and zero-copy slicing to prevent V8 garbage
     * collection pauses on Android Chrome.
     */
    class AudioStreamPipeline {
        constructor(inRate, outRate, targetBlockSize = TARGET_BLOCK_SIZE) {
            this.inRate = inRate;
            this.outRate = outRate;
            this.targetBlockSize = targetBlockSize;
            this.ratio = inRate / outRate;
            this.pos = 0.0;
            this.inBuffer = new Float32Array(0);

            // Ring accumulator buffer for exact 1024-block chunking
            this.outBuffer = new Float32Array(32768);
            this.outLength = 0;
        }

        pushToOut(samples) {
            if (this.outLength + samples.length > this.outBuffer.length) {
                const bigger = new Float32Array(Math.max(this.outBuffer.length * 2, this.outLength + samples.length));
                bigger.set(this.outBuffer.subarray(0, this.outLength));
                this.outBuffer = bigger;
            }
            this.outBuffer.set(samples, this.outLength);
            this.outLength += samples.length;
        }

        process(inChunk) {
            if (this.inRate === this.outRate) {
                // Same rate: directly accumulate chunk
                this.pushToOut(inChunk);
            } else {
                // Continuous linear interpolation resampling
                const newBuf = new Float32Array(this.inBuffer.length + inChunk.length);
                newBuf.set(this.inBuffer, 0);
                newBuf.set(inChunk, this.inBuffer.length);

                const estOutCount = Math.floor((newBuf.length - 1 - this.pos) / this.ratio) + 2;
                const resampled = new Float32Array(Math.max(0, estOutCount));
                let outIdx = 0;

                while (this.pos + 1 < newBuf.length) {
                    const i0 = Math.floor(this.pos);
                    const frac = this.pos - i0;
                    const s0 = newBuf[i0];
                    const s1 = newBuf[i0 + 1];
                    resampled[outIdx++] = s0 * (1.0 - frac) + s1 * frac;
                    this.pos += this.ratio;
                }

                const consumed = Math.floor(this.pos);
                this.pos -= consumed;
                this.inBuffer = newBuf.slice(consumed);

                if (outIdx > 0) {
                    this.pushToOut(resampled.subarray(0, outIdx));
                }
            }

            // Slice out exact 1024-sample blocks
            const readyBlocks = [];
            while (this.outLength >= this.targetBlockSize) {
                const block = this.outBuffer.slice(0, this.targetBlockSize);
                this.outBuffer.copyWithin(0, this.targetBlockSize, this.outLength);
                this.outLength -= this.targetBlockSize;
                readyBlocks.push(block);
            }

            return readyBlocks;
        }

        reset() {
            this.pos = 0.0;
            this.inBuffer = new Float32Array(0);
            this.outLength = 0;
        }
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
            if (insecureBanner) {
                insecureBanner.style.display = 'block';
            }
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
            if (diagModem) diagModem.textContent = 'Loading WebAssembly...';
            ggwave = await ggwave_factory();
            if (diagModem) diagModem.textContent = 'GGWave Wasm Ready';
            console.log('[ChirpDrop] GGWave WebAssembly initialized successfully.');
        } catch (err) {
            console.error('[ChirpDrop] Failed to load GGWave:', err);
            if (diagModem) diagModem.textContent = 'Modem Error: ' + err.message;
            if (statusText) statusText.textContent = 'Status: Modem initialization failed';
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
        if (meterBar) meterBar.style.width = percent + '%';

        let dbStr = '-∞ dB';
        if (rms > 0.0001) {
            const db = Math.round(20 * Math.log10(rms));
            dbStr = `${db} dB`;
        }
        if (meterDb) meterDb.textContent = dbStr;
        return dbStr;
    }

    /**
     * Update Live Diagnostics UI (throttled to ~10 Hz to prevent DOM rendering overhead on mobile).
     */
    function updateLiveDiagnostics(dbStr) {
        const now = performance.now();
        if (now - lastUiThrottleTime < 100) return; // 100ms throttle
        lastUiThrottleTime = now;

        if (diagBlocksCount) diagBlocksCount.textContent = blocksProcessedCount.toLocaleString();
        if (diagDecodeAttempts) diagDecodeAttempts.textContent = decodeAttemptsCount.toLocaleString();
        if (diagMessagesCount) diagMessagesCount.textContent = messagesReceivedCount.toLocaleString();
        if (diagAudioState && audioContext) diagAudioState.textContent = audioContext.state;
        if (diagDbLevel) diagDbLevel.textContent = dbStr;
    }

    /**
     * Set active status message with optional auto-revert to listening state.
     */
    function setStatus(text, revertDelayMs = 0) {
        if (statusResetTimer) {
            clearTimeout(statusResetTimer);
            statusResetTimer = null;
        }

        if (statusText) statusText.textContent = text;

        if (revertDelayMs > 0 && isListening) {
            statusResetTimer = setTimeout(() => {
                if (isListening && audioContext) {
                    const rateText = audioContext.sampleRate === TARGET_SAMPLE_RATE ? '48,000 Hz' : `resampled from ${audioContext.sampleRate.toLocaleString()} Hz`;
                    if (statusText) statusText.textContent = `Status: Listening for nearby transmissions... (${rateText})`;
                }
            }, revertDelayMs);
        }
    }

    /**
     * Render a verified ChirpDrop message card in the UI.
     * Strictly rejects and does not display invalid/corrupted packets.
     */
    function renderMessageCard(packetResult) {
        if (!packetResult || !packetResult.isValid) {
            console.warn('[ChirpDrop] Ignored invalid/corrupted packet:', packetResult ? packetResult.error : 'Null packet');
            setStatus('Status: Discarded invalid acoustic packet (checksum failed)', 2500);
            return;
        }

        messagesReceivedCount++;
        if (diagMessagesCount) diagMessagesCount.textContent = messagesReceivedCount.toLocaleString();

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
        if (messagesList) {
            messagesList.insertBefore(card, messagesList.firstChild);
        }

        // Update status badge
        setStatus(`Status: Message received and validated! (Seq #${packetResult.sequenceId})`, 3000);

        // Haptic feedback (supported natively on Android Chrome and modern iOS)
        if ('vibrate' in navigator) {
            try { navigator.vibrate([60, 40, 80]); } catch { /* ignore */ }
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
        if (permissionBanner) permissionBanner.style.display = 'none';

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

            // Mobile Audio Unlock: Play 1-sample silent buffer to awaken hardware audio layer on Android & iOS
            try {
                const silentSource = audioContext.createBufferSource();
                silentSource.buffer = audioContext.createBuffer(1, 1, audioContext.sampleRate);
                silentSource.connect(audioContext.destination);
                silentSource.start(0);
            } catch (e) {
                console.debug('[ChirpDrop] Silent unlock buffer note:', e);
            }

            // Handle system interruptions on mobile (e.g. phone call or backgrounding)
            audioContext.onstatechange = () => {
                console.log('[ChirpDrop] AudioContext state changed to:', audioContext.state);
                if (diagAudioState) diagAudioState.textContent = audioContext.state;
                if (audioContext.state === 'suspended' && isListening) {
                    if (statusText) statusText.textContent = 'Status: Audio paused by system (tap to resume)';
                    if (diagEngineStatus) {
                        diagEngineStatus.textContent = 'Suspended';
                        diagEngineStatus.classList.remove('active');
                    }
                } else if (audioContext.state === 'running' && isListening) {
                    if (diagEngineStatus) {
                        diagEngineStatus.textContent = 'Listening';
                        diagEngineStatus.classList.add('active');
                    }
                }
            };

            const actualRate = audioContext.sampleRate;
            if (diagInRate) diagInRate.textContent = `${actualRate.toLocaleString()} Hz`;
            if (diagOutRate) diagOutRate.textContent = `${TARGET_SAMPLE_RATE.toLocaleString()} Hz`;

            if (actualRate === TARGET_SAMPLE_RATE) {
                if (diagSampleRate) diagSampleRate.textContent = `${actualRate.toLocaleString()} Hz (Native)`;
            } else {
                if (diagSampleRate) diagSampleRate.textContent = `${actualRate.toLocaleString()} Hz → ${TARGET_SAMPLE_RATE.toLocaleString()} Hz`;
            }

            // Initialize or reset robust audio stream pipeline
            audioPipeline = new AudioStreamPipeline(actualRate, TARGET_SAMPLE_RATE, TARGET_BLOCK_SIZE);
            console.log(`[ChirpDrop] Audio pipeline configured: ${actualRate} Hz -> ${TARGET_SAMPLE_RATE} Hz (Block size: ${TARGET_BLOCK_SIZE})`);

            // 2. Request microphone stream with clean acoustic constraints (Step 1 & Step 2)
            // On Android Chrome, echo cancellation and noise suppression aggressively notch out
            // continuous FSK acoustic chirps unless explicitly disabled.
            let stream = null;
            const preferredConstraints = {
                audio: {
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false,
                    channelCount: { ideal: 1 },
                    sampleRate: { ideal: TARGET_SAMPLE_RATE },
                    // Chromium vendor flags to prevent WebRTC APM from filtering acoustic carriers
                    googEchoCancellation: false,
                    googAutoGainControl: false,
                    googNoiseSuppression: false,
                    googHighpassFilter: false,
                    googAudioMirroring: false,
                    latency: 0
                }
            };

            try {
                stream = await navigator.mediaDevices.getUserMedia(preferredConstraints);
            } catch (constraintErr) {
                console.warn('[ChirpDrop] Preferred acoustic constraints rejected, retrying with standard constraints:', constraintErr);
                try {
                    // Fallback 1: Standard W3C disable flags
                    stream = await navigator.mediaDevices.getUserMedia({
                        audio: {
                            echoCancellation: false,
                            noiseSuppression: false,
                            autoGainControl: false
                        }
                    });
                } catch (fallbackErr) {
                    console.warn('[ChirpDrop] Standard constraints rejected, retrying basic audio:', fallbackErr);
                    // Fallback 2: Basic audio
                    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                }
            }
            mediaStream = stream;

            // Inspect and enforce track settings where supported
            const audioTrack = stream.getAudioTracks()[0];
            if (audioTrack) {
                if (typeof audioTrack.applyConstraints === 'function') {
                    try {
                        await audioTrack.applyConstraints({
                            echoCancellation: false,
                            noiseSuppression: false,
                            autoGainControl: false
                        });
                    } catch (e) {
                        console.debug('[ChirpDrop] track.applyConstraints note:', e);
                    }
                }

                const settings = audioTrack.getSettings ? audioTrack.getSettings() : {};
                const aecStr = settings.echoCancellation === true ? 'AEC: On ⚠️' : 'AEC: Off';
                const nsStr = settings.noiseSuppression === true ? 'NS: On ⚠️' : 'NS: Off';
                const agcStr = settings.autoGainControl === true ? 'AGC: On ⚠️' : 'AGC: Off';
                if (diagDspFilters) diagDspFilters.textContent = `${aecStr} | ${nsStr} | ${agcStr}`;
                console.log('[ChirpDrop] Active audio track settings:', settings);
            }

            if (diagMicStatus) diagMicStatus.textContent = 'Active (Live)';

            // 3. Initialize GGWave instance with native 48,000 Hz processing parameters (Step 4)
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
            } else if (audioPipeline) {
                audioPipeline.reset();
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
            // Pin mediaSource and recorderNode to prevent Chromium V8 garbage collection (crbug.com/121404)
            mediaSource = audioContext.createMediaStreamSource(mediaStream);
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

            // Connect nodes: MediaStream -> Recorder -> MuteGain -> Destination
            mediaSource.connect(recorderNode);
            recorderNode.connect(muteGainNode);
            muteGainNode.connect(audioContext.destination);

            // Pin to window to prevent V8 GC collection on mobile Chrome
            window.__chirpdropMediaSource = mediaSource;
            window.__chirpdropRecorderNode = recorderNode;
            window.__chirpdropMuteGainNode = muteGainNode;
            window.__chirpdropAudioContext = audioContext;

            // Audio processing loop
            recorderNode.onaudioprocess = function (e) {
                if (!isListening) return;

                blocksProcessedCount++;
                const channelData = e.inputBuffer.getChannelData(0);

                // Compute RMS for live meter
                let sum = 0.0;
                for (let i = 0; i < channelData.length; i++) {
                    sum += channelData[i] * channelData[i];
                }
                const rms = Math.sqrt(sum / channelData.length);
                const dbStr = updateMeter(rms);
                updateLiveDiagnostics(dbStr);

                // Show transient signal detection status if sound is above ambient threshold
                if (rms > 0.04 && (!statusResetTimer)) {
                    if (statusText) statusText.textContent = 'Status: Acoustic signal detected, analyzing...';
                }

                // Process audio through pipeline (resample to 48kHz if needed, emit exact 1024-sample blocks)
                const blocks = audioPipeline ? audioPipeline.process(channelData) : [channelData];

                for (const block of blocks) {
                    decodeAttemptsCount++;
                    try {
                        // Zero-copy Int8Array view over Float32Array block buffer
                        const int8Buffer = new Int8Array(block.buffer, block.byteOffset, block.byteLength);
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

            // Update UI State
            isListening = true;
            if (toggleBtn) toggleBtn.classList.add('listening');
            if (btnIcon) btnIcon.textContent = '⏹️';
            if (btnText) btnText.textContent = 'STOP LISTENING';

            if (statusBadge) statusBadge.classList.add('listening');
            const rateLabel = actualRate === TARGET_SAMPLE_RATE ? '48,000 Hz' : `resampled from ${actualRate.toLocaleString()} Hz`;
            if (statusText) statusText.textContent = `Status: Listening for nearby transmissions... (${rateLabel})`;

            if (diagEngineStatus) {
                diagEngineStatus.textContent = 'Listening';
                diagEngineStatus.classList.add('active');
            }
            if (diagAudioState) diagAudioState.textContent = audioContext.state;

            console.log(`[ChirpDrop] Acoustic receiver started. Hardware rate: ${actualRate} Hz`);

        } catch (err) {
            console.error('[ChirpDrop] Microphone activation error:', err);
            isListening = false;
            updateMeter(0);

            if (diagMicStatus) diagMicStatus.textContent = 'Denied / Error';
            if (diagEngineStatus) {
                diagEngineStatus.textContent = 'Error';
                diagEngineStatus.classList.remove('active');
            }

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
                if (permissionBanner) permissionBanner.style.display = 'block';
                if (statusText) statusText.textContent = 'Status: Microphone access denied';
            } else if (err.name === 'NotFoundError') {
                if (permMsg) {
                    permMsg.innerHTML = `No microphone hardware detected on this device. Please connect an audio input device and try again.`;
                }
                if (permissionBanner) permissionBanner.style.display = 'block';
                if (statusText) statusText.textContent = 'Status: Microphone not found';
            } else if (err.name === 'NotReadableError') {
                if (permMsg) {
                    permMsg.innerHTML = `The microphone is currently busy or locked by another app (e.g. active phone call, voice recorder, or meeting). Please close other audio apps and try again.`;
                }
                if (permissionBanner) permissionBanner.style.display = 'block';
                if (statusText) statusText.textContent = 'Status: Microphone busy';
            } else {
                alert(`Could not start acoustic listener: ${err.message}`);
                if (statusText) statusText.textContent = `Status: Error (${err.name || 'Unknown'})`;
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

        if (mediaSource) {
            try { mediaSource.disconnect(); } catch { /* ignore */ }
            mediaSource = null;
        }

        if (mediaStream) {
            try { mediaStream.getTracks().forEach(track => track.stop()); } catch { /* ignore */ }
            mediaStream = null;
        }

        if (audioPipeline) {
            audioPipeline.reset();
        }

        // Clean up global references
        window.__chirpdropMediaSource = null;
        window.__chirpdropRecorderNode = null;
        window.__chirpdropMuteGainNode = null;

        updateMeter(0);

        // Update UI
        if (toggleBtn) toggleBtn.classList.remove('listening');
        if (btnIcon) btnIcon.textContent = '🎙️';
        if (btnText) btnText.textContent = 'START LISTENING';

        if (statusBadge) statusBadge.classList.remove('listening');
        if (statusText) statusText.textContent = 'Status: Not listening';

        if (diagEngineStatus) {
            diagEngineStatus.textContent = 'Idle';
            diagEngineStatus.classList.remove('active');
        }
        if (diagMicStatus) diagMicStatus.textContent = 'Inactive';
        if (diagDbLevel) diagDbLevel.textContent = '-∞ dB';

        console.log('[ChirpDrop] Acoustic receiver stopped.');
    }

    // Toggle button listener
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function () {
            if (!isListening) {
                startListening();
            } else {
                stopListening();
            }
        });
    }

    // Clear messages listener
    if (clearBtn) {
        clearBtn.addEventListener('click', function () {
            if (messagesList) messagesList.innerHTML = '';
            if (emptyState) {
                emptyState.style.display = 'flex';
                if (messagesList) messagesList.appendChild(emptyState);
            }
            messagesReceivedCount = 0;
            if (diagMessagesCount) diagMessagesCount.textContent = '0';
        });
    }

    // Mobile backgrounding & tab switching recovery (Android Chrome & iOS Safari)
    document.addEventListener('visibilitychange', async () => {
        if (document.visibilityState === 'visible' && isListening) {
            console.log('[ChirpDrop] App returned to foreground. Checking audio state...');
            if (audioContext && audioContext.state === 'suspended') {
                try {
                    await audioContext.resume();
                    console.log('[ChirpDrop] AudioContext successfully resumed after visibility change.');
                    if (diagAudioState) diagAudioState.textContent = audioContext.state;
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
                    if (diagOffline) {
                        diagOffline.textContent = 'Offline Ready (PWA)';
                        diagOffline.style.color = 'var(--accent-emerald)';
                    }
                })
                .catch((err) => {
                    console.warn('[ChirpDrop] Service Worker registration failed:', err);
                    if (diagOffline) diagOffline.textContent = 'Online Only';
                });
        } else {
            if (diagOffline) diagOffline.textContent = 'ServiceWorker unsupported';
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
