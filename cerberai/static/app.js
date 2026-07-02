// UI State
let chatHistory = [];
let configuredModels = [];
let activeModelId = "auto";
let isGenerating = false;
let uploadedImages = []; // Stores base64 data URLs of uploaded images

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
const imageUploadBtn = document.getElementById("image-upload-btn");
const imageFileInput = document.getElementById("image-file-input");
const imagePreviewContainer = document.getElementById("image-preview-container");


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
    setInterval(pollStatus, 3000);
    initConversations();
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

        // Update Context & KV Cache Monitor
        const contextMonitor = document.getElementById("context-monitor");
        if (contextMonitor) {
            const ctxBar = document.getElementById("ctx-bar");
            const ctxUsed = document.getElementById("ctx-used");
            const ctxMax = document.getElementById("ctx-max");
            const cachePct = document.getElementById("cache-pct");
            const ctxModelLimit = document.getElementById("ctx-model-limit");

            let activeLLM = null;
            if (activeModelId && activeModelId !== "auto") {
                activeLLM = status.all_configured_models.find(m => m.id === activeModelId && m.type === "llm");
            } else {
                activeLLM = status.active_models.find(m => m.type === "llm");
            }

            if (activeLLM) {
                contextMonitor.style.display = "block";
                
                // Calculate context in use from chatHistory
                let totalChars = 0;
                chatHistory.forEach(msg => {
                    totalChars += (msg.content || "").length;
                });
                const currentTokens = Math.max(0, Math.floor(totalChars / 4));
                const maxTokens = activeLLM.n_ctx || 4096;
                const cachePctVal = Math.min((currentTokens / maxTokens) * 100, 100);
                
                ctxUsed.textContent = `${currentTokens.toLocaleString()} tokens`;
                ctxMax.textContent = `${maxTokens.toLocaleString()} tokens`;
                cachePct.textContent = `${cachePctVal.toFixed(1)}%`;
                ctxModelLimit.textContent = maxTokens >= 1000 ? `${(maxTokens / 1000).toFixed(0)}K` : maxTokens;
                ctxBar.style.width = `${cachePctVal}%`;
                
                if (cachePctVal > 80) {
                    ctxBar.style.background = "linear-gradient(90deg, #f59e0b 0%, #ef4444 100%)";
                } else {
                    ctxBar.style.background = "linear-gradient(90deg, #3b82f6 0%, #10b981 100%)";
                }
            } else {
                contextMonitor.style.display = "none";
            }
        }

        // Update thinking bubble if there is an active model loading operation
        const thinkingBubble = document.querySelector(".assistant-row:last-child .msg-bubble");
        if (thinkingBubble && (thinkingBubble.textContent === "Thinking..." || thinkingBubble.textContent.startsWith("Downloading") || thinkingBubble.textContent.startsWith("Initializing") || thinkingBubble.innerHTML.includes("pulse"))) {
            const loadingModelId = Object.keys(status.loading_status || {})[0];
            if (loadingModelId) {
                const op = status.loading_status[loadingModelId];
                thinkingBubble.innerHTML = `<span style="color: var(--text-secondary); display: inline-flex; align-items: center; gap: 8px;"><span class="status-dot orange loading-pulse" style="display: inline-block; width: 8px; height: 8px; border-radius: 50%;"></span>${op.message}</span>`;
            }
        }

        // Render models catalog list
        renderCatalog(status.all_configured_models, status.active_models, status.loading_status || {});
    } catch (err) {
        console.error("Connection lost/failed to poll status:", err);
    }
}

// Render model catalog sidebar items
function renderCatalog(allModels, activeModels, loadingStatus) {
    modelsList.innerHTML = "";
    
    // Create lookup map for active models
    const activeMap = new Map(activeModels.map(m => [m.id, m]));

    allModels.forEach(model => {
        const isActive = activeMap.has(model.id);
        const isLoading = loadingStatus && loadingStatus[model.id];
        
        const card = document.createElement("div");
        card.className = `catalog-item ${model.id === activeModelId ? 'active' : ''}`;
        
        let statusText = "Unloaded";
        let dotClass = "gray";
        if (isActive) {
            statusText = "Active";
            dotClass = "green";
        }
        if (isLoading) {
            statusText = loadingStatus[model.id].message;
            dotClass = "orange loading-pulse";
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
                <span style="font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px;" title="${statusText}">${statusText}</span>
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
    chatMessages.innerHTML = "";
    displayWelcome();
    syncActiveConversation();
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
    appendMessage("user", prompt, null, uploadedImages);
    
    if (uploadedImages.length > 0) {
        const contentList = [{ type: "text", text: prompt }];
        uploadedImages.forEach(img => {
            contentList.push({
                type: "image_url",
                image_url: { url: img }
            });
        });
        chatHistory.push({ role: "user", content: contentList });
    } else {
        chatHistory.push({ role: "user", content: prompt });
    }
    
    // Clear preview state
    uploadedImages = [];
    if (imagePreviewContainer) {
        imagePreviewContainer.innerHTML = "";
        imagePreviewContainer.classList.add("hidden");
    }
    
    syncActiveConversation(); // Save user message
    
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
            let metrics = null;
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
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
                            if (parsed.metrics) {
                                metrics = parsed.metrics;
                                // Append metrics bubble
                                const wrapper = assistantBubble.parentElement;
                                const metricsBubble = document.createElement("div");
                                metricsBubble.className = "metrics-bubble";
                                const modelText = metrics.model ? `[${metrics.model}] &middot; ` : "";
                 metricsBubble.innerHTML = `⚡ ${modelText}${metrics.tokens_per_second.toFixed(1)} t/s &middot; ${metrics.wall_time_sec.toFixed(2)}s wall time &middot; ${metrics.completion_tokens} tokens`;
                                wrapper.appendChild(metricsBubble);
                            } else {
                                const delta = parsed.choices[0].delta.content;
                                if (delta) {
                                    accumulatedContent += delta;
                                    assistantBubble.innerHTML = marked.parse(accumulatedContent);
                                    scrollChatToBottom();
                                }
                            }
                        } catch (e) {
                            // ignore json error
                        }
                    }
                }
            }
            
            chatHistory.push({ role: "assistant", content: accumulatedContent, metrics: metrics });
            syncActiveConversation(); // Save assistant message & metrics
        } else {
            const data = await response.json();
            const text = data.choices[0].message.content;
            const metrics = data.metrics || null;
            
            assistantBubble.innerHTML = marked.parse(text);
            
            if (metrics) {
                const wrapper = assistantBubble.parentElement;
                const metricsBubble = document.createElement("div");
                metricsBubble.className = "metrics-bubble";
                const modelText = metrics.model ? `[${metrics.model}] &middot; ` : "";
                metricsBubble.innerHTML = `⚡ ${modelText}${metrics.tokens_per_second.toFixed(1)} t/s &middot; ${metrics.wall_time_sec.toFixed(2)}s wall time &middot; ${metrics.completion_tokens} tokens`;
                wrapper.appendChild(metricsBubble);
            }
            
            chatHistory.push({ role: "assistant", content: text, metrics: metrics });
            syncActiveConversation(); // Save assistant message & metrics
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
function appendMessage(sender, text, metrics = null, images = []) {
    const messageId = `msg-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const row = document.createElement("div");
    row.id = messageId;
    row.className = `message-row ${sender}-row`;

    const avatar = sender === "user" ? "👤" : "⚡";
    const displayName = sender === "user" ? "You" : "CerberAI";
    const timeString = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    let displayText = "";
    let displayImages = [...images];

    if (Array.isArray(text)) {
        text.forEach(part => {
            if (part && part.type === "text") {
                displayText += part.text;
            } else if (part && part.type === "image_url" && part.image_url) {
                displayImages.push(part.image_url.url);
            }
        });
    } else {
        displayText = text;
    }

    // Parse markdown initially (only for non-empty texts)
    const formattedText = sender === "assistant" && displayText === "Thinking..." ? displayText : marked.parse(displayText || "");

    let imagesHtml = "";
    if (displayImages.length > 0) {
        imagesHtml = `<div class="msg-attached-images" style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px;">`;
        displayImages.forEach(img => {
            imagesHtml += `<img src="${img}" class="msg-attached-image" style="max-width: 250px; max-height: 250px; border-radius: 8px; border: 1px solid var(--border-color); cursor: pointer; transition: transform 0.2s;" onclick="window.open(this.src, '_blank')">`;
        });
        imagesHtml += `</div>`;
    }

    let metricsHtml = "";
    if (sender === "assistant" && metrics) {
        const modelText = metrics.model ? `[${metrics.model}] &middot; ` : "";
        metricsHtml = `
            <div class="metrics-bubble">
                ⚡ ${modelText}${metrics.tokens_per_second.toFixed(1)} t/s &middot; ${metrics.wall_time_sec.toFixed(2)}s wall time &middot; ${metrics.completion_tokens} tokens
            </div>
        `;
    }

    row.innerHTML = `
        <div class="msg-avatar">${avatar}</div>
        <div class="msg-content-wrapper">
            <span class="msg-meta">${displayName} &bull; ${timeString}</span>
            <div class="msg-bubble">${formattedText}${imagesHtml}</div>
            ${sender === 'assistant' ? '<button class="tts-play-btn">🔊 Listen</button>' : ''}
            ${metricsHtml}
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

// Image Upload handler
console.log("CerberAI: Initializing image upload elements...");
console.log("CerberAI: imageUploadBtn:", imageUploadBtn);
console.log("CerberAI: imageFileInput:", imageFileInput);
console.log("CerberAI: imagePreviewContainer:", imagePreviewContainer);

if (imageUploadBtn && imageFileInput && imagePreviewContainer) {
    imageUploadBtn.addEventListener("click", () => {
        console.log("CerberAI: imageUploadBtn clicked, triggering file input");
        imageFileInput.click();
    });

    imageFileInput.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        console.log("CerberAI: file selected:", file ? file.name : "none");
        if (!file) return;

        // Reset input value so it can be re-triggered
        imageFileInput.value = "";

        const reader = new FileReader();
        reader.onload = function(event) {
            console.log("CerberAI: file read finished");
            const base64Data = event.target.result;
            uploadedImages.push(base64Data);
            renderImagePreviews();
        };
        reader.readAsDataURL(file);
    });

    function renderImagePreviews() {
        imagePreviewContainer.innerHTML = "";
        if (uploadedImages.length === 0) {
            imagePreviewContainer.classList.add("hidden");
            return;
        }

        imagePreviewContainer.classList.remove("hidden");
        uploadedImages.forEach((imgData, index) => {
            const previewItem = document.createElement("div");
            previewItem.className = "image-preview-item";

            const img = document.createElement("img");
            img.src = imgData;
            previewItem.appendChild(img);

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "image-preview-remove";
            removeBtn.innerHTML = "&times;";
            removeBtn.addEventListener("click", () => {
                uploadedImages.splice(index, 1);
                renderImagePreviews();
            });
            previewItem.appendChild(removeBtn);

            imagePreviewContainer.appendChild(previewItem);
        });
    }
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
const setupContainer = document.getElementById("models-setup-container");
const addCustomLlmBtn = document.getElementById("btn-add-custom-llm");

if (openSetupBtn && setupModal) {
    // Helper to render a single model setup card dynamically
    const renderSetupCard = (model) => {
        const card = document.createElement("div");
        card.className = "model-setup-card";
        card.dataset.type = model.type;
        
        if (model.type === "llm") {
            const isFallback = (model.id === "general-llama3");
            const removeBtnHtml = isFallback ? "" : `<button type="button" class="btn-remove-model" style="background: rgba(239, 68, 68, 0.15); color: var(--accent-red); padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(239, 68, 68, 0.3); font-size: 11px; cursor: pointer; float: right;">Remove Model</button>`;

            card.innerHTML = `
                <div style="margin-bottom: 12px; overflow: auto;">
                    <h4 style="margin-bottom: 0; float: left;">${isFallback ? "🧠 General LLM (Fallback)" : "🤖 LLM Model"}</h4>
                    ${removeBtnHtml}
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Model ID</label>
                        <input type="text" class="model-id" value="${model.id}" ${isFallback ? "readonly style='opacity: 0.7;'" : ""} required>
                    </div>
                    <div class="form-group">
                        <label>Specifier / Purpose</label>
                        <input type="text" class="model-purpose" value="${model.purpose || ""}" placeholder="e.g. for general reasoning, for coding, for roleplay" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>HF Repo ID</label>
                        <input type="text" class="model-repo" value="${model.backend_config.repo_id || ""}" required>
                    </div>
                    <div class="form-group">
                        <label>HF Filename (GGUF only)</label>
                        <input type="text" class="model-filename" value="${model.backend_config.filename || ""}" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>VRAM Estimate (GB)</label>
                        <input type="number" class="model-vram" step="0.1" value="${model.vram_estimate_gb}" required>
                    </div>
                    <div class="form-group">
                        <label>Port</label>
                        <input type="number" class="model-port" value="${model.backend_config.port || 8081}" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Context Size (n_ctx)</label>
                        <select class="model-n-ctx custom-select">
                            <option value="0" ${!model.n_ctx ? 'selected' : ''}>✨ Auto-calculate from VRAM</option>
                            <option value="2048" ${model.n_ctx === 2048 ? 'selected' : ''}>2048 tokens</option>
                            <option value="4096" ${model.n_ctx === 4096 ? 'selected' : ''}>4096 tokens</option>
                            <option value="8192" ${model.n_ctx === 8192 ? 'selected' : ''}>8192 tokens</option>
                            <option value="16384" ${model.n_ctx === 16384 ? 'selected' : ''}>16384 tokens</option>
                            <option value="32768" ${model.n_ctx === 32768 ? 'selected' : ''}>32768 tokens</option>
                        </select>
                    </div>
                </div>
            `;
            
            // Add remove event listener
            if (!isFallback) {
                card.querySelector(".btn-remove-model").addEventListener("click", () => {
                    card.remove();
                });
            }
        } else if (model.type === "image") {
            card.innerHTML = `
                <h4>🎨 Image Generator: ${model.id}</h4>
                <div class="form-row">
                    <div class="form-group">
                        <label>HF Repo ID / Model Name</label>
                        <input type="text" class="model-repo" value="${model.backend_config.model_name || ""}" required>
                    </div>
                    <div class="form-group">
                        <label>VRAM Estimate (GB)</label>
                        <input type="number" class="model-vram" step="0.1" value="${model.vram_estimate_gb}" required>
                    </div>
                </div>
            `;
        } else if (model.type === "stt") {
            card.innerHTML = `
                <h4>🎙️ Speech to Text (STT): ${model.id}</h4>
                <div class="form-row">
                    <div class="form-group">
                        <label>Model Size / Name</label>
                        <input type="text" class="model-repo" value="${model.backend_config.model_name || ""}" required>
                    </div>
                    <div class="form-group">
                        <label>VRAM Estimate (GB)</label>
                        <input type="number" class="model-vram" step="0.1" value="${model.vram_estimate_gb}" required>
                    </div>
                </div>
            `;
        } else {
            // Unhandled models (like tts-offline) return empty or keep properties statically
            card.style.display = "none";
            card.innerHTML = `<input type="hidden" class="model-raw-json" value='${JSON.stringify(model)}'>`;
        }

        setupContainer.appendChild(card);
    };

    // Hardware Tier Configuration Presets
    const PRESETS = {
        "4": {
            vram: 4.0,
            ram: 16.0,
            router_type: "llm",
            router_model: "routing-phi",
            models: [
                { id: "general-llama3", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-1.5B-Instruct-GGUF", filename: "qwen2.5-1.5b-instruct-q4_k_m.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 1.2, purpose: "general reasoning", n_ctx: null },
                { id: "coding-qwen", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF", filename: "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 1.2, purpose: "general coding", n_ctx: null },
                { id: "image-lcm", type: "image", backend: "diffusers", backend_config: { model_name: "Lykon/dreamshaper-8-lcm" }, vram_estimate_gb: 4.0 },
                { id: "stt-whisper", type: "stt", backend: "whisper", backend_config: { model_name: "tiny" }, vram_estimate_gb: 0.5 },
                { id: "tts-offline", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing-phi", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 }
            ]
        },
        "6": {
            vram: 6.0,
            ram: 16.0,
            router_type: "llm",
            router_model: "routing-phi",
            models: [
                { id: "general-llama3", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-3B-Instruct-GGUF", filename: "qwen2.5-3b-instruct-q4_k_m.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "general reasoning", n_ctx: null },
                { id: "coding-qwen", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF", filename: "qwen2.5-coder-3b-instruct-q4_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "general coding", n_ctx: null },
                { id: "image-lcm", type: "image", backend: "diffusers", backend_config: { model_name: "Lykon/dreamshaper-8-lcm" }, vram_estimate_gb: 4.0 },
                { id: "stt-whisper", type: "stt", backend: "whisper", backend_config: { model_name: "base" }, vram_estimate_gb: 0.7 },
                { id: "tts-offline", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing-phi", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 }
            ]
        },
        "8": {
            vram: 8.0,
            ram: 16.0,
            router_type: "llm",
            router_model: "routing-phi",
            models: [
                { id: "general-llama3", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "QuantFactory/Meta-Llama-3.1-8B-Instruct-GGUF", filename: "Meta-Llama-3.1-8B-Instruct.Q4_K_M.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 4.8, purpose: "general reasoning", n_ctx: null },
                { id: "coding-qwen", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF", filename: "qwen2.5-coder-7b-instruct-q4_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 4.7, purpose: "general coding", n_ctx: null },
                { id: "image-lcm", type: "image", backend: "diffusers", backend_config: { model_name: "Lykon/dreamshaper-8-lcm" }, vram_estimate_gb: 4.0 },
                { id: "stt-whisper", type: "stt", backend: "whisper", backend_config: { model_name: "small" }, vram_estimate_gb: 1.5 },
                { id: "tts-offline", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing-phi", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 }
            ]
        },
        "16": {
            vram: 16.0,
            ram: 16.0,
            router_type: "llm",
            router_model: "routing-phi",
            models: [
                { id: "general-llama3", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen2.5-14B-Instruct-GGUF", filename: "Qwen2.5-14B-Instruct-Q4_K_M.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 9.5, purpose: "general reasoning", n_ctx: null },
                { id: "coding-qwen", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF", filename: "qwen2.5-coder-14b-instruct-q4_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 9.5, purpose: "general coding", n_ctx: null },
                { id: "image-lcm", type: "image", backend: "diffusers", backend_config: { model_name: "stabilityai/sdxl-turbo" }, vram_estimate_gb: 5.5 },
                { id: "stt-whisper", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts-offline", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing-phi", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 }
            ]
        },
        "24": {
            vram: 24.0,
            ram: 32.0,
            router_type: "llm",
            router_model: "routing-phi",
            models: [
                { id: "general-llama3", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen2.5-32B-Instruct-GGUF", filename: "Qwen2.5-32B-Instruct-Q4_K_M.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 20.3, purpose: "general reasoning", n_ctx: null },
                { id: "coding-qwen", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-Coder-32B-Instruct-GGUF", filename: "qwen2.5-coder-32b-instruct-q4_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 20.3, purpose: "general coding", n_ctx: null },
                { id: "image-lcm", type: "image", backend: "diffusers", backend_config: { model_name: "black-forest-labs/FLUX.1-schnell" }, vram_estimate_gb: 11.5 },
                { id: "stt-whisper", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts-offline", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing-phi", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 }
            ]
        },
        "32": {
            vram: 32.0,
            ram: 32.0,
            router_type: "llm",
            router_model: "routing-phi",
            models: [
                { id: "general-llama3", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen2.5-32B-Instruct-GGUF", filename: "Qwen2.5-32B-Instruct-Q5_K_M.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 24.5, purpose: "general reasoning", n_ctx: null },
                { id: "coding-qwen", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-Coder-32B-Instruct-GGUF", filename: "qwen2.5-coder-32b-instruct-q5_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 24.5, purpose: "general coding", n_ctx: null },
                { id: "image-lcm", type: "image", backend: "diffusers", backend_config: { model_name: "black-forest-labs/FLUX.1-dev" }, vram_estimate_gb: 12.0 },
                { id: "stt-whisper", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts-offline", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing-phi", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 }
            ]
        },
        "64": {
            vram: 64.0,
            ram: 64.0,
            router_type: "llm",
            router_model: "routing-phi",
            models: [
                { id: "general-llama3", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", filename: "Llama-3.3-70B-Instruct-Q5_K_S.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "general reasoning", n_ctx: null },
                { id: "coding-qwen", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-Coder-32B-Instruct-GGUF", filename: "qwen2.5-coder-32b-instruct-q8_0.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 35.0, purpose: "general coding", n_ctx: null },
                { id: "image-lcm", type: "image", backend: "diffusers", backend_config: { model_name: "black-forest-labs/FLUX.1-dev" }, vram_estimate_gb: 16.0 },
                { id: "stt-whisper", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts-offline", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing-phi", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 }
            ]
        },
        "128": {
            vram: 128.0,
            ram: 128.0,
            router_type: "llm",
            router_model: "routing-phi",
            models: [
                { id: "general-llama3", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", filename: "Llama-3.3-70B-Instruct-Q5_K_S.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "general reasoning", n_ctx: null },
                { id: "coding-qwen", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen2.5-Coder-32B-Instruct-GGUF", filename: "qwen2.5-coder-32b-instruct-q8_0.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 35.0, purpose: "general coding", n_ctx: null },
                { id: "image-lcm", type: "image", backend: "diffusers", backend_config: { model_name: "black-forest-labs/FLUX.1-dev" }, vram_estimate_gb: 22.0 },
                { id: "stt-whisper", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts-offline", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing-phi", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 }
            ]
        }
    };

    const setupPresetSelect = document.getElementById("setup-preset");
    if (setupPresetSelect) {
        setupPresetSelect.addEventListener("change", (e) => {
            const val = e.target.value;
            if (!val || !PRESETS[val]) return;

            const preset = PRESETS[val];
            if (!confirm(`Are you sure you want to load the ${val} GB VRAM preset? This will overwrite your current settings and model catalog configuration cards.`)) {
                setupPresetSelect.value = "";
                return;
            }

            // Overwrite VRAM / RAM
            document.getElementById("setup-vram").value = preset.vram;
            document.getElementById("setup-ram").value = preset.ram;

            // Overwrite router
            const routerTypeSelect = document.getElementById("setup-router-type");
            const routerModelSelect = document.getElementById("setup-router-model");

            routerTypeSelect.value = preset.router_type;
            
            // Re-populate router model dropdown with preset LLMs
            routerModelSelect.innerHTML = "";
            preset.models.forEach(model => {
                if (model.type === "llm") {
                    const opt = document.createElement("option");
                    opt.value = model.id;
                    opt.textContent = `${model.id} (${model.purpose || 'LLM reasoning'})`;
                    routerModelSelect.appendChild(opt);
                }
            });
            routerModelSelect.value = preset.router_model;
            routerModelSelect.disabled = false;

            // Clear and render new cards
            setupContainer.innerHTML = "";
            preset.models.forEach(model => {
                renderSetupCard(model);
            });

            // Reset selection box back to default
            setupPresetSelect.value = "";
        });
    }

    // Open Setup Modal & Fetch Config
    openSetupBtn.addEventListener("click", async () => {
        try {
            const res = await fetch("/api/config");
            if (!res.ok) throw new Error("Could not retrieve config.");
            const config = await res.json();

            // Populate resource limits
            document.getElementById("setup-vram").value = config.resource_limits.max_vram_gb;
            document.getElementById("setup-ram").value = config.resource_limits.max_ram_gb;
            document.getElementById("setup-hf-token").value = config.hf_token || "";

            // Populate router settings
            const routerTypeSelect = document.getElementById("setup-router-type");
            const routerModelSelect = document.getElementById("setup-router-model");
            
            routerTypeSelect.value = config.router.model_type || "heuristics";
            
            // Populate router model options
            routerModelSelect.innerHTML = "";
            config.models.forEach(model => {
                if (model.type === "llm") {
                    const opt = document.createElement("option");
                    opt.value = model.id;
                    opt.textContent = `${model.id} (${model.purpose || 'LLM reasoning'})`;
                    routerModelSelect.appendChild(opt);
                }
            });
            
            routerModelSelect.value = config.router.model_name || (config.models.find(m => m.type === "llm")?.id || "");
            
            const updateRouterFields = () => {
                routerModelSelect.disabled = (routerTypeSelect.value !== "llm");
            };
            
            routerTypeSelect.onchange = updateRouterFields;
            updateRouterFields();

            // Clear dynamic cards
            setupContainer.innerHTML = "";

            // Populate models
            config.models.forEach(model => {
                renderSetupCard(model);
            });

            // Show modal
            setupModal.classList.remove("hidden");
        } catch (err) {
            alert(`Failed to load server settings: ${err.message}`);
        }
    });

    // Add Custom LLM Card on click
    addCustomLlmBtn.addEventListener("click", () => {
        const customCount = setupContainer.querySelectorAll(".model-setup-card[data-type='llm']").length + 1;
        const newLlm = {
            id: `custom-llm-${customCount}`,
            type: "llm",
            backend: "llama.cpp",
            backend_config: {
                repo_id: "",
                filename: "",
                port: 8080 + customCount,
                n_gpu_layers: 99
            },
            vram_estimate_gb: 4.5,
            purpose: ""
        };
        renderSetupCard(newLlm);
        setupContainer.lastElementChild.scrollIntoView({ behavior: "smooth" });
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

        // Extract models dynamically from rendered cards
        const modelPayloads = [];
        const cards = setupContainer.querySelectorAll(".model-setup-card");
        
        cards.forEach(card => {
            const type = card.dataset.type;
            if (type === "llm") {
                const id = card.querySelector(".model-id").value.trim();
                const purpose = card.querySelector(".model-purpose").value.trim();
                const repo = card.querySelector(".model-repo").value.trim();
                const filename = card.querySelector(".model-filename").value.trim();
                const vram = parseFloat(card.querySelector(".model-vram").value);
                const port = parseInt(card.querySelector(".model-port").value);
                const nCtxVal = parseInt(card.querySelector(".model-n-ctx").value);
                const nCtx = nCtxVal > 0 ? nCtxVal : null;

                modelPayloads.push({
                    id: id,
                    type: "llm",
                    backend: "llama.cpp",
                    backend_config: {
                        repo_id: repo,
                        filename: filename,
                        port: port,
                        n_gpu_layers: 99
                    },
                    vram_estimate_gb: vram,
                    purpose: purpose,
                    n_ctx: nCtx
                });
            } else if (type === "image") {
                const modelName = card.querySelector(".model-repo").value.trim();
                const vram = parseFloat(card.querySelector(".model-vram").value);
                modelPayloads.push({
                    id: "image-lcm",
                    type: "image",
                    backend: "diffusers",
                    backend_config: {
                        model_name: modelName
                    },
                    vram_estimate_gb: vram
                });
            } else if (type === "stt") {
                const modelName = card.querySelector(".model-repo").value.trim();
                const vram = parseFloat(card.querySelector(".model-vram").value);
                modelPayloads.push({
                    id: "stt-whisper",
                    type: "stt",
                    backend: "whisper",
                    backend_config: {
                        model_name: modelName
                    },
                    vram_estimate_gb: vram
                });
            } else {
                // Parse hidden/raw model (e.g. tts-offline)
                const rawData = JSON.parse(card.querySelector(".model-raw-json").value);
                modelPayloads.push(rawData);
            }
        });

        // Reconstruct the exact AppConfig structure
        const hfTokenVal = document.getElementById("setup-hf-token").value.trim();
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
                model_type: document.getElementById("setup-router-type").value,
                model_name: document.getElementById("setup-router-type").value === "llm" ? document.getElementById("setup-router-model").value : null,
                fallback_model: "general-llama3"
            },
            models: modelPayloads,
            hf_token: hfTokenVal || null
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

// ==========================================================================
// CONVERSATION HISTORY OPERATIONS
// ==========================================================================
let currentConvId = null;
let conversationsList = [];

const conversationsContainer = document.getElementById("conversations-list");
const newChatBtn = document.getElementById("btn-new-chat");

async function initConversations() {
    await fetchConversations();
    
    // Select first conversation, or create one if none exist
    if (conversationsList.length > 0) {
        await loadConversation(conversationsList[0].id);
    } else {
        await createNewChat();
    }
    
    // Set up New Chat click event
    if (newChatBtn) {
        newChatBtn.addEventListener("click", createNewChat);
    }
}

async function fetchConversations() {
    try {
        const res = await fetch("/api/conversations");
        if (!res.ok) throw new Error("Could not retrieve conversations list");
        conversationsList = await res.json();
        renderConversationsList();
    } catch (err) {
        console.error("Failed to load conversations:", err);
    }
}

function renderConversationsList() {
    if (!conversationsContainer) return;
    conversationsContainer.innerHTML = "";
    conversationsList.forEach(conv => {
        const item = document.createElement("div");
        item.className = `conv-item ${conv.id === currentConvId ? 'active' : ''}`;
        item.innerHTML = `
            <span class="conv-title">${escapeHtml(conv.title)}</span>
            <button class="conv-delete-btn" title="Delete Chat">&times;</button>
        `;
        
        // Click item to load conversation
        item.addEventListener("click", (e) => {
            if (e.target.classList.contains("conv-delete-btn")) return;
            loadConversation(conv.id);
        });
        
        // Click delete button to delete conversation
        item.querySelector(".conv-delete-btn").addEventListener("click", async (e) => {
            e.stopPropagation();
            if (confirm(`Are you sure you want to delete this chat thread?`)) {
                await deleteConversation(conv.id);
            }
        });
        
        conversationsContainer.appendChild(item);
    });
}

async function loadConversation(id) {
    currentConvId = id;
    renderConversationsList(); // Update active selection highlight
    
    try {
        const res = await fetch(`/api/conversations/${id}`);
        if (!res.ok) throw new Error("Could not load conversation");
        const conv = await res.json();
        
        // Set chatHistory state
        chatHistory = conv.messages || [];
        
        // Clear chat display
        chatMessages.innerHTML = "";
        
        // If no messages, display welcome card
        if (chatHistory.length === 0) {
            displayWelcome();
        } else {
            // Populate messages in UI
            chatHistory.forEach(msg => {
                appendMessage(msg.role, msg.content, msg.metrics);
            });
        }
    } catch (err) {
        console.error("Error loading conversation:", err);
    }
}

async function createNewChat() {
    try {
        const res = await fetch("/api/conversations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: "New Chat" })
        });
        if (!res.ok) throw new Error("Could not create new conversation");
        const conv = await res.json();
        
        currentConvId = conv.id;
        chatHistory = [];
        
        // Reload list and highlight new active conversation
        await fetchConversations();
        
        // Reset UI chat screen
        chatMessages.innerHTML = "";
        displayWelcome();
        promptInput.value = "";
        promptInput.focus();
        adjustTextareaHeight();
    } catch (err) {
        console.error("Failed to create new chat:", err);
    }
}

async function deleteConversation(id) {
    try {
        const res = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
        if (!res.ok) throw new Error("Failed to delete");
        
        // If we deleted the active conversation, find the next one or create a new one
        if (id === currentConvId) {
            const remaining = conversationsList.filter(c => c.id !== id);
            if (remaining.length > 0) {
                await loadConversation(remaining[0].id);
            } else {
                await createNewChat();
                return; // createNewChat calls fetchConversations internally
            }
        }
        await fetchConversations();
    } catch (err) {
        console.error("Delete conversation failed:", err);
    }
}

// Helper to sync local messages list with backend
async function syncActiveConversation() {
    if (!currentConvId) return;
    
    // Generate a dynamic title if the title is still default and we have messages
    let title = "New Chat";
    const activeConv = conversationsList.find(c => c.id === currentConvId);
    if (activeConv) {
        title = activeConv.title;
    }
    
    if (title === "New Chat" && chatHistory.length > 0) {
        // Use a snippet of the first user message
        const firstUserMsg = chatHistory.find(m => m.role === "user");
        if (firstUserMsg) {
            title = firstUserMsg.content.trim().slice(0, 30);
            if (firstUserMsg.content.length > 30) title += "...";
        }
    }
    
    const payload = {
        id: currentConvId,
        title: title,
        messages: chatHistory
    };
    
    try {
        const res = await fetch(`/api/conversations/${currentConvId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            // Update local active title list representation without full reload
            const updatedList = conversationsList.map(c => {
                if (c.id === currentConvId) {
                    return { ...c, title: title, updated_at: Date.now() / 1000 };
                }
                return c;
            });
            // Re-sort list by updated_at descending
            updatedList.sort((a, b) => b.updated_at - a.updated_at);
            conversationsList = updatedList;
            renderConversationsList();
        }
    } catch (err) {
        console.error("Failed to sync conversation:", err);
    }
}

function displayWelcome() {
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
}

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}



