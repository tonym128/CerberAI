// UI State
let chatHistory = [];
let configuredModels = [];
let activeModelId = "auto";
let isGenerating = false;

// DOM Elements
const modelSelect = document.getElementById("model-select");
const modelsList = document.getElementById("models-list");
const chatMessages = document.getElementById("chat-messages");
const chatForm = document.getElementById("chat-form");
const promptInput = document.getElementById("prompt-input");
const vramBar = document.getElementById("vram-bar");
const vramUsedLabel = document.getElementById("vram-used");
const vramMaxLabel = document.getElementById("vram-max");
const ramLimitLabel = document.getElementById("ram-limit");
const evictionLabel = document.getElementById("eviction-strategy");
const currentChatModelLabel = document.getElementById("current-chat-model");
const routingDescLabel = document.getElementById("routing-description");
const clearChatBtn = document.getElementById("clear-chat");
const streamCheck = document.getElementById("stream-check");
const toolsCheck = document.getElementById("tools-check");
const sendBtn = document.getElementById("send-btn");


// Suggestions click handler
function setPrompt(text) {
    promptInput.value = text;
    promptInput.focus();
    adjustTextareaHeight();
}

// Auto-grow textarea
promptInput.addEventListener("input", adjustTextareaHeight);
function adjustTextareaHeight() {
    promptInput.style.height = "auto";
    promptInput.style.height = (promptInput.scrollHeight) + "px";
}

// Initialize on load
window.addEventListener("DOMContentLoaded", () => {
    fetchModels();
    pollStatus();
    // Poll status every 3 seconds
    setInterval(pollStatus, 3000);
});

// Fetch all models
async function fetchModels() {
    try {
        const response = await fetch("/v1/models");
        const data = await response.json();
        configuredModels = data.data;

        // Clear select and add auto
        modelSelect.innerHTML = `<option value="auto" selected>✨ Intelligent Router (Auto)</option>`;
        
        configuredModels.forEach(model => {
            if (model.id !== "auto") {
                const opt = document.createElement("option");
                opt.value = model.id;
                opt.textContent = `📦 ${model.id}`;
                modelSelect.appendChild(opt);
            }
        });
    } catch (err) {
        console.error("Failed to load models list:", err);
    }
}

// Poll server resource status
async function pollStatus() {
    try {
        const response = await fetch("/status");
        const status = await response.json();

        // Update limits & strategy
        vramMaxLabel.textContent = `${status.limits.max_vram_gb.toFixed(1)} GB`;
        ramLimitLabel.textContent = `${status.limits.max_ram_gb.toFixed(1)} GB`;
        evictionLabel.textContent = status.limits.eviction_strategy.toUpperCase();

        // Update VRAM Bar
        const usage = status.vram_usage.estimated_active_gb;
        const limit = status.limits.max_vram_gb;
        const pct = status.vram_usage.percentage;
        
        vramUsedLabel.textContent = `${usage.toFixed(1)} GB`;
        vramBar.style.width = `${Math.min(pct, 100)}%`;
        
        if (pct > 85) {
            vramBar.style.background = "linear-gradient(90deg, #f59e0b 0%, #ef4444 100%)";
        } else {
            vramBar.style.background = "linear-gradient(90deg, #8b5cf6 0%, #3b82f6 100%)";
        }

        // Render models catalog list
        renderCatalog(status.all_configured_models, status.active_models);
    } catch (err) {
        console.error("Connection lost/failed to poll status:", err);
    }
}

// Render model catalog sidebar items
function renderCatalog(allModels, activeModels) {
    modelsList.innerHTML = "";
    
    // Create lookup map for active models
    const activeMap = new Map(activeModels.map(m => [m.id, m]));

    allModels.forEach(model => {
        const isActive = activeMap.has(model.id);
        const activeInfo = activeMap.get(model.id);
        
        const card = document.createElement("div");
        card.className = `catalog-item ${model.id === activeModelId ? 'active' : ''}`;
        
        let statusText = "Unloaded";
        let dotClass = "gray";
        if (isActive) {
            statusText = "Active";
            dotClass = "green";
        }

        card.innerHTML = `
            <div class="model-info-box">
                <span class="model-name-title">${model.id}</span>
                <div class="model-meta-tags">
                    <span class="model-tag">${model.type.toUpperCase()}</span>
                    <span class="model-tag">${model.vram_estimate_gb.toFixed(1)} GB</span>
                </div>
            </div>
            <div class="status-indicator">
                <span class="status-dot ${dotClass}"></span>
                <span>${statusText}</span>
            </div>
        `;
        
        modelsList.appendChild(card);
    });
}

// Model Selection change handler
modelSelect.addEventListener("change", (e) => {
    activeModelId = e.target.value;
    if (activeModelId === "auto") {
        currentChatModelLabel.textContent = "✨ Intelligent Router";
        routingDescLabel.textContent = "Automatically selects between coding and general models based on your request.";
    } else {
        currentChatModelLabel.textContent = `📦 ${activeModelId}`;
        routingDescLabel.textContent = `Strict routing enabled. All requests are routed to ${activeModelId}.`;
    }
    
    // Trigger UI catalog refresh
    pollStatus();
});

// Clear Chat
clearChatBtn.addEventListener("click", () => {
    chatHistory = [];
    chatMessages.innerHTML = `
        <div class="assistant-welcome">
            <div class="welcome-icon">⚡</div>
            <h2>Welcome to CerberAI</h2>
            <p>Ask a coding or general question. CerberAI will dynamically load the best model into memory and unload inactive ones to manage local hardware resources.</p>
            <div class="suggestions-grid">
                <div class="suggestion-card" onclick="setPrompt('Write a python script to sort a dictionary by its values')">
                    <h4>💻 Coding Request</h4>
                    <p>"Write a python script to sort a dictionary by its values"</p>
                </div>
                <div class="suggestion-card" onclick="setPrompt('Explain quantum physics in a single paragraph')">
                    <h4>🧠 General Query</h4>
                    <p>"Explain quantum physics in a single paragraph"</p>
                </div>
            </div>
        </div>
    `;
});

// Handle Form Submission
chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = promptInput.value.trim();
    if (!prompt || isGenerating) return;

    // Reset input
    promptInput.value = "";
    adjustTextareaHeight();
    
    // Add user message to UI
    appendMessage("user", prompt);
    chatHistory.push({ role: "user", content: prompt });
    
    // Remove welcome card if exists
    const welcomeCard = document.querySelector(".assistant-welcome");
    if (welcomeCard) welcomeCard.remove();

    // Start loading/generating state
    isGenerating = true;
    toggleInputState(true);
    
    // Append blank response bubble
    const bubbleId = appendMessage("assistant", "Thinking...");
    const assistantBubble = document.getElementById(bubbleId).querySelector(".msg-bubble");
    
    const stream = streamCheck.checked;

    try {
        const payload = {
            model: activeModelId,
            messages: chatHistory,
            stream: stream,
            tools_enabled: toolsCheck ? toolsCheck.checked : false
        };


        const response = await fetch("/v1/chat/completions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "Server error occurred");
        }

        if (stream) {
            assistantBubble.textContent = "";
            let accumulatedContent = "";
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                
                // Keep the last partial line in buffer
                buffer = lines.pop();
                
                for (const line of lines) {
                    const cleanLine = line.trim();
                    if (!cleanLine) continue;
                    
                    if (cleanLine.startsWith("data: ")) {
                        const dataStr = cleanLine.slice(6).trim();
                        if (dataStr === "[DONE]") {
                            break;
                        }
                        try {
                            const parsed = JSON.parse(dataStr);
                            const delta = parsed.choices[0].delta.content;
                            if (delta) {
                                accumulatedContent += delta;
                                assistantBubble.innerHTML = marked.parse(accumulatedContent);
                                scrollChatToBottom();
                            }
                        } catch (e) {
                            // Suppress JSON parsing errors on malformed chunks
                        }
                    }
                }
            }
            
            // Append final content
            chatHistory.push({ role: "assistant", content: accumulatedContent });
        } else {
            const data = await response.json();
            const text = data.choices[0].message.content;
            assistantBubble.innerHTML = marked.parse(text);
            chatHistory.push({ role: "assistant", content: text });
            scrollChatToBottom();
        }
        
    } catch (err) {
        console.error(err);
        assistantBubble.innerHTML = `<span style="color: var(--accent-red)">⚠️ Error: ${err.message}</span>`;
    } finally {
        isGenerating = false;
        toggleInputState(false);
        pollStatus(); // Refresh memory values after generation finishes
    }
});

// Append message to UI returning the unique row element ID
function appendMessage(sender, text) {
    const messageId = `msg-${Date.now()}`;
    const row = document.createElement("div");
    row.id = messageId;
    row.className = `message-row ${sender}-row`;

    const avatar = sender === "user" ? "👤" : "⚡";
    const displayName = sender === "user" ? "You" : "CerberAI";
    const timeString = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    // Parse markdown initially (only for non-empty texts)
    const formattedText = sender === "assistant" && text === "Thinking..." ? text : marked.parse(text);

    row.innerHTML = `
        <div class="msg-avatar">${avatar}</div>
        <div class="msg-content-wrapper">
            <span class="msg-meta">${displayName} &bull; ${timeString}</span>
            <div class="msg-bubble">${formattedText}</div>
            ${sender === 'assistant' ? '<button class="tts-play-btn">🔊 Listen</button>' : ''}
        </div>
    `;

    chatMessages.appendChild(row);
    
    if (sender === "assistant") {
        const playBtn = row.querySelector(".tts-play-btn");
        if (playBtn) {
            playBtn.addEventListener("click", () => playText(messageId));
        }
    }
    
    scrollChatToBottom();
    return messageId;
}

// Scroll chat window
function scrollChatToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Toggle Input components while loading/generating
function toggleInputState(disabled) {
    promptInput.disabled = disabled;
    sendBtn.disabled = disabled;
    if (disabled) {
        sendBtn.style.opacity = 0.5;
        sendBtn.innerHTML = `
            <span class="status-dot orange"></span>
        `;
    } else {
        sendBtn.style.opacity = 1;
        sendBtn.innerHTML = `
            <svg viewBox="0 0 24 24" width="24" height="24" class="send-icon">
                <path fill="currentColor" d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
        `;
    }
}

// Text to Speech synthesis handler
async function playText(messageId) {
    const bubble = document.getElementById(messageId).querySelector(".msg-bubble");
    const playBtn = document.getElementById(messageId).querySelector(".tts-play-btn");
    if (!bubble || !playBtn) return;

    // Get plain text content (stripping markdown HTML tags)
    const text = bubble.innerText.trim();
    if (!text) return;

    playBtn.disabled = true;
    playBtn.innerHTML = `⏳ Synthesizing...`;

    try {
        const response = await fetch("/v1/audio/speech", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                input: text,
                voice: "alloy"
            })
        });

        if (!response.ok) throw new Error("TTS generation failed");

        const blob = await response.blob();
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        audio.play();
        
        audio.onended = () => {
            playBtn.disabled = false;
            playBtn.innerHTML = `🔊 Listen`;
            URL.revokeObjectURL(audioUrl);
        };
    } catch (err) {
        console.error(err);
        playBtn.innerHTML = `⚠️ Error`;
        setTimeout(() => {
            playBtn.disabled = false;
            playBtn.innerHTML = `🔊 Listen`;
        }, 2000);
    }
}

// Speech to Text file upload handler
const audioUploadBtn = document.getElementById("audio-upload-btn");
const audioFileInput = document.getElementById("audio-file-input");

if (audioUploadBtn && audioFileInput) {
    audioUploadBtn.addEventListener("click", () => {
        audioFileInput.click();
    });

    audioFileInput.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        // Reset input
        audioFileInput.value = "";

        // Show status
        promptInput.value = "Transcribing voice message...";
        promptInput.disabled = true;
        audioUploadBtn.disabled = true;

        try {
            const formData = new FormData();
            formData.append("file", file);
            formData.append("model", "auto");

            const response = await fetch("/v1/audio/transcriptions", {
                method: "POST",
                body: formData
            });

            if (!response.ok) throw new Error("Transcription failed");

            const data = await response.json();
            const transcription = data.text;

            if (transcription) {
                promptInput.value = transcription;
                // Auto submit form
                chatForm.dispatchEvent(new Event("submit"));
            } else {
                promptInput.value = "";
            }
        } catch (err) {
            console.error(err);
            promptInput.value = `Error: ${err.message}`;
        } finally {
            promptInput.disabled = false;
            audioUploadBtn.disabled = false;
            promptInput.focus();
            adjustTextareaHeight();
        }
    });
}

// News Video Automation
const btnNewsVideo = document.getElementById("btn-news-video");
const newsVideoStatusContainer = document.getElementById("news-video-status-container");
const newsVideoProgress = document.getElementById("news-video-progress");
const newsVideoStatusMsg = document.getElementById("news-video-status-msg");
const newsVideoPlayerContainer = document.getElementById("news-video-player-container");
const newsVideoPlayer = document.getElementById("news-video-player");

if (btnNewsVideo) {
    let pollInterval = null;

    const checkAutomationStatus = async () => {
        try {
            const res = await fetch("/v1/automate/news-video/status");
            if (!res.ok) return;
            const data = await res.json();

            if (data.status === "running") {
                btnNewsVideo.disabled = true;
                btnNewsVideo.textContent = "Processing...";
                newsVideoStatusContainer.classList.remove("hidden");
                newsVideoProgress.style.width = `${data.progress}%`;
                newsVideoStatusMsg.textContent = data.message;
                
                // If pollInterval is not active, start it
                if (!pollInterval) {
                    pollInterval = setInterval(checkAutomationStatus, 2500);
                }
            } else if (data.status === "completed") {
                if (pollInterval) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                }
                btnNewsVideo.disabled = false;
                btnNewsVideo.textContent = "Generate Video";
                newsVideoStatusContainer.classList.add("hidden");
                
                // Load and play video
                newsVideoPlayer.src = data.video_url;
                newsVideoPlayerContainer.classList.remove("hidden");
            } else if (data.status === "failed") {
                if (pollInterval) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                }
                btnNewsVideo.disabled = false;
                btnNewsVideo.textContent = "Generate Video";
                newsVideoStatusContainer.classList.add("hidden");
                alert(`Automation failed: ${data.message}`);
            }
        } catch (err) {
            console.error("Status check failed", err);
        }
    };

    btnNewsVideo.addEventListener("click", async () => {
        btnNewsVideo.disabled = true;
        btnNewsVideo.textContent = "Initiating...";
        newsVideoStatusContainer.classList.remove("hidden");
        newsVideoPlayerContainer.classList.add("hidden");
        newsVideoProgress.style.width = "0%";
        newsVideoStatusMsg.textContent = "Starting automation task...";

        try {
            const res = await fetch("/v1/automate/news-video", { method: "POST" });
            if (!res.ok) throw new Error("Could not start automation");
            
            // Start polling status
            pollInterval = setInterval(checkAutomationStatus, 2500);
        } catch (err) {
            alert(`Failed to start news video generation: ${err.message}`);
            btnNewsVideo.disabled = false;
            btnNewsVideo.textContent = "Generate Video";
            newsVideoStatusContainer.classList.add("hidden");
        }
    });

    // Check status on load in case a task is already running
    checkAutomationStatus();
}

// ==========================================================================
// SETUP MODAL OPERATIONS
// ==========================================================================
const openSetupBtn = document.getElementById("open-setup");
const setupModal = document.getElementById("setup-modal");
const closeSetupBtn = document.getElementById("close-setup");
const cancelSetupBtn = document.getElementById("btn-cancel-setup");
const setupForm = document.getElementById("setup-form");

if (openSetupBtn && setupModal) {
    // Open Setup Modal & Fetch Config
    openSetupBtn.addEventListener("click", async () => {
        try {
            const res = await fetch("/api/config");
            if (!res.ok) throw new Error("Could not retrieve config.");
            const config = await res.json();

            // Populate resource limits
            document.getElementById("setup-vram").value = config.resource_limits.max_vram_gb;
            document.getElementById("setup-ram").value = config.resource_limits.max_ram_gb;

            // Populate models
            config.models.forEach(model => {
                if (model.id === "general-llama3") {
                    document.getElementById("setup-general-repo").value = model.backend_config.repo_id || "";
                    document.getElementById("setup-general-file").value = model.backend_config.filename || "";
                    document.getElementById("setup-general-vram").value = model.vram_estimate_gb;
                    document.getElementById("setup-general-port").value = model.backend_config.port || 8081;
                } else if (model.id === "coding-qwen") {
                    document.getElementById("setup-coding-repo").value = model.backend_config.repo_id || "";
                    document.getElementById("setup-coding-file").value = model.backend_config.filename || "";
                    document.getElementById("setup-coding-vram").value = model.vram_estimate_gb;
                    document.getElementById("setup-coding-port").value = model.backend_config.port || 8082;
                } else if (model.id === "image-lcm") {
                    document.getElementById("setup-image-repo").value = model.backend_config.model_name || "";
                    document.getElementById("setup-image-vram").value = model.vram_estimate_gb;
                } else if (model.id === "stt-whisper") {
                    document.getElementById("setup-stt-name").value = model.backend_config.model_name || "";
                    document.getElementById("setup-stt-vram").value = model.vram_estimate_gb;
                }
            });

            // Show modal
            setupModal.classList.remove("hidden");
        } catch (err) {
            alert(`Failed to load server settings: ${err.message}`);
        }
    });

    // Close Modal
    const closeModal = () => setupModal.classList.add("hidden");
    closeSetupBtn.addEventListener("click", closeModal);
    cancelSetupBtn.addEventListener("click", closeModal);

    // Save and Reload Config
    setupForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const submitBtn = setupForm.querySelector("button[type='submit']");
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = "Reloading...";

        // Construct config structure
        const payload = {
            server: {
                host: "127.0.0.1",
                port: 8000,
                timeout_keep_alive: 300
            },
            resource_limits: {
                max_vram_gb: parseFloat(document.getElementById("setup-vram").value),
                max_ram_gb: parseFloat(document.getElementById("setup-ram").value),
                eviction_strategy: "lru"
            },
            router: {
                model_type: "heuristics",
                fallback_model: "general-llama3"
            },
            models: [
                {
                    id: "general-llama3",
                    type: "llm",
                    backend: "llama.cpp",
                    backend_config: {
                        repo_id: document.getElementById("setup-general-repo").value,
                        filename: document.getElementById("setup-general-file").value,
                        port: parseInt(document.getElementById("setup-general-port").value),
                        n_gpu_layers: 99
                    },
                    vram_estimate_gb: parseFloat(document.getElementById("setup-general-vram").value)
                },
                {
                    id: "coding-qwen",
                    type: "llm",
                    backend: "llama.cpp",
                    backend_config: {
                        repo_id: document.getElementById("setup-coding-repo").value,
                        filename: document.getElementById("setup-coding-file").value,
                        port: parseInt(document.getElementById("setup-coding-port").value),
                        n_gpu_layers: 99
                    },
                    vram_estimate_gb: parseFloat(document.getElementById("setup-coding-vram").value)
                },
                {
                    id: "stt-whisper",
                    type: "stt",
                    backend: "whisper",
                    backend_config: {
                        model_name: document.getElementById("setup-stt-name").value
                    },
                    vram_estimate_gb: parseFloat(document.getElementById("setup-stt-vram").value)
                },
                {
                    id: "tts-offline",
                    type: "tts",
                    backend: "tts",
                    backend_config: {
                        engine: "kokoro",
                        voice: "af_sarah"
                    },
                    vram_estimate_gb: 0.5
                },
                {
                    id: "image-lcm",
                    type: "image",
                    backend: "diffusers",
                    backend_config: {
                        model_name: document.getElementById("setup-image-repo").value
                    },
                    vram_estimate_gb: parseFloat(document.getElementById("setup-image-vram").value)
                }
            ]
        };

        try {
            const res = await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error("Server rejected configuration reload.");
            const data = await res.json();
            
            alert(data.message || "Settings updated and server reloaded!");
            closeModal();
            
            // Refresh dashboard model catalog & limits
            fetchModels();
            pollStatus();
        } catch (err) {
            alert(`Failed to save configuration: ${err.message}`);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    });
}



