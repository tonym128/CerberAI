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

// Handle Ctrl+Enter to submit prompt
promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendBtn.click();
    }
});
// Theme management (Dark / Light mode toggle)
function initTheme() {
    const themeToggle = document.getElementById("theme-toggle");
    const sunIcon = document.getElementById("sun-icon");
    const moonIcon = document.getElementById("moon-icon");
    
    if (!themeToggle) return;
    
    // Check saved preference or default to dark (since app is dark by default)
    const savedTheme = localStorage.getItem("theme") || "dark";
    
    if (savedTheme === "light") {
        document.documentElement.classList.add("light-theme");
        if (sunIcon) sunIcon.style.display = "none";
        if (moonIcon) moonIcon.style.display = "block";
    } else {
        document.documentElement.classList.remove("light-theme");
        if (sunIcon) sunIcon.style.display = "block";
        if (moonIcon) moonIcon.style.display = "none";
    }
    
    themeToggle.addEventListener("click", () => {
        const isCurrentlyLight = document.documentElement.classList.contains("light-theme");
        
        if (isCurrentlyLight) {
            // Switch to Dark Theme
            document.documentElement.classList.remove("light-theme");
            localStorage.setItem("theme", "dark");
            if (sunIcon) sunIcon.style.display = "block";
            if (moonIcon) moonIcon.style.display = "none";
        } else {
            // Switch to Light Theme
            document.documentElement.classList.add("light-theme");
            localStorage.setItem("theme", "light");
            if (sunIcon) sunIcon.style.display = "none";
            if (moonIcon) moonIcon.style.display = "block";
        }
    });
}

function adjustTextareaHeight() {
    promptInput.style.height = "auto";
    promptInput.style.height = (promptInput.scrollHeight) + "px";
}

// Initialize on load
window.addEventListener("DOMContentLoaded", () => {
    initTheme();
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

        // Check for onboarding / first run
        if (status.is_first_run && typeof checkOnboarding === "function") {
            checkOnboarding(status);
        }

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

// Render model catalog sidebar
function renderCatalog(allModels, activeModels, loadingStatus) {
    const formatTimeAgo = (ts) => {
        if (!ts) return "Never";
        const diff = Math.floor(Date.now() / 1000 - ts);
        if (diff < 5) return "Just now";
        if (diff < 60) return `${diff}s ago`;
        const mins = Math.floor(diff / 60);
        if (mins < 60) return `${mins}m ago`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours}h ago`;
        return new Date(ts * 1000).toLocaleDateString();
    };

    modelsList.innerHTML = "";
    
    // Create lookup map for active models
    const activeMap = new Map(activeModels.map(m => [m.id, m]));

    allModels.forEach(model => {
        const isActive = activeMap.has(model.id);
        const isLoading = loadingStatus && loadingStatus[model.id];
        
        const card = document.createElement("div");
        card.className = `catalog-card ${model.id === activeModelId ? 'active' : ''}`;
        
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

        // Get emoji/style for modality
        let emoji = "🤖";
        let modalityClass = "modality-llm";
        if (model.type === "image") {
            emoji = "🎨";
            modalityClass = "modality-image";
        } else if (model.type === "vision") {
            emoji = "👁";
            modalityClass = "modality-vision";
        } else if (model.type === "tts") {
            emoji = "🎙";
            modalityClass = "modality-tts";
        } else if (model.type === "stt") {
            emoji = "🔊";
            modalityClass = "modality-stt";
        } else if (model.type === "video") {
            emoji = "🎬";
            modalityClass = "modality-video";
        }

        // Build telemetry html
        const diag = model.diagnostics || {};
        const stats = model.stats || { calls: 0, avg_load: 0.0, avg_ttft: 0.0, tps: 0.0 };
        const showDiagnostics = stats.calls > 0 || diag.load_time_seconds > 0 || diag.last_error;
        
        let telemetryHtml = "";
        if (showDiagnostics) {
            telemetryHtml = `
                <div class="model-telemetry-container" style="margin-top: 6px; padding-top: 6px; border-top: 1px dashed rgba(255,255,255,0.06); font-size: 10.5px; color: var(--text-secondary); display: flex; flex-direction: column; gap: 4px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span>All-Time Calls:</span>
                        <span style="color: var(--text-primary); font-weight: 600;">${stats.calls}</span>
                    </div>
                    ${stats.calls > 0 
                        ? `
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span>Avg Speed (TPS):</span>
                            <span style="color: var(--accent); font-weight: 600;">${stats.tps.toFixed(1)} tok/s</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span>Avg Load:</span>
                            <span style="color: var(--text-primary); font-weight: 600;">${stats.avg_load.toFixed(2)}s</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span>Avg TTFT:</span>
                            <span style="color: var(--text-primary); font-weight: 600;">${stats.avg_ttft.toFixed(2)}s</span>
                        </div>
                        ` : ''
                    }
                    ${diag.load_time_seconds > 0 
                        ? `
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span>Active Load Speed:</span>
                            <span style="color: var(--text-primary); font-weight: 600;">${diag.load_time_seconds.toFixed(2)}s</span>
                        </div>
                        ` : ''
                    }
                    ${diag.last_active_timestamp > 0 
                        ? `
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span>Last Active:</span>
                            <span style="color: var(--text-primary); font-weight: 600;" title="${new Date(diag.last_active_timestamp * 1000).toLocaleString()}">${formatTimeAgo(diag.last_active_timestamp)}</span>
                        </div>
                        ` : ''
                    }
                    ${diag.last_error 
                        ? `
                        <div style="margin-top: 4px; padding: 6px; border-radius: 6px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); color: #f87171; word-break: break-all; font-size: 9.5px; line-height: 1.3;" title="${diag.last_error}">
                            <strong>Error:</strong> ${diag.last_error}
                        </div>
                        ` : ''
                    }
                </div>
            `;
        }

        const isDownloaded = model.downloaded !== false;
        let downloadBadge = "";
        if (!isDownloaded && model.backend === "llama.cpp") {
            downloadBadge = `<span style="display: inline-flex; align-items: center; gap: 4px; font-size: 10px; padding: 2px 8px; border-radius: 10px; background: rgba(239, 68, 68, 0.1); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.2); font-weight: 600;">⬇ Not Downloaded</span>`;
        } else if (model.backend === "llama.cpp") {
            downloadBadge = `<span style="display: inline-flex; align-items: center; gap: 4px; font-size: 10px; padding: 2px 8px; border-radius: 10px; background: rgba(16, 185, 129, 0.1); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.2); font-weight: 600;">✓ Cached</span>`;
        }

        card.innerHTML = `
            <div class="catalog-card-header">
                <span class="catalog-card-title" title="${model.id}">${model.id}</span>
                <span class="modality-badge ${modalityClass}">${emoji} ${model.type.toUpperCase()}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
                <span style="font-size: 11px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;" title="${model.model_name || ''}">${model.model_name || ''}</span>
                ${downloadBadge}
            </div>
            <div class="catalog-card-details">
                <div class="status-indicator">
                    <span class="status-dot ${dotClass}"></span>
                    <span style="font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px;" title="${statusText}">${statusText}</span>
                </div>
                <span class="vram-pill">${model.vram_estimate_gb.toFixed(1)} GB</span>
            </div>
            ${telemetryHtml}
            <div class="catalog-card-actions">
                ${isActive 
                    ? `<button class="card-action-btn btn-unload" onclick="event.stopPropagation(); unloadModel('${model.id}')">Purge VRAM</button>`
                    : `<button class="card-action-btn btn-load" ${isLoading ? 'disabled' : ''} onclick="event.stopPropagation(); loadModel('${model.id}')">${isLoading ? 'Loading...' : 'Force Load'}</button>`
                }
            </div>
        `;
        
        card.addEventListener("click", (e) => {
            // Avoid selecting model if user clicked on action buttons
            if (e.target.closest('.card-action-btn')) return;
            
            activeModelId = model.id;
            modelSelect.value = model.id;
            
            // Trigger change event logic manually
            currentChatModelLabel.textContent = `📦 ${activeModelId}`;
            routingDescLabel.textContent = `Strict routing enabled. All requests are routed to ${activeModelId}.`;
            
            document.querySelectorAll(".catalog-card").forEach(c => c.classList.remove("active"));
            card.classList.add("active");
            
            pollStatus();
        });
        
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
            ${sender === 'assistant' ? '<div class="tts-wrapper" style="display: flex; gap: 8px; align-items: center; margin-top: 8px;"><button class="tts-play-btn" style="margin-top: 0;">🔊 Listen</button></div>' : ''}
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
        
        let downloadBtn = playBtn.parentElement.querySelector(".tts-download-btn");
        if (downloadBtn) {
            const oldUrl = downloadBtn.getAttribute("href");
            if (oldUrl) URL.revokeObjectURL(oldUrl);
            downloadBtn.href = audioUrl;
        } else {
            downloadBtn = document.createElement("a");
            downloadBtn.className = "tts-download-btn";
            downloadBtn.innerHTML = "📥 Download";
            downloadBtn.href = audioUrl;
            downloadBtn.download = `speech_${messageId}.mp3`;
            downloadBtn.style.background = "rgba(255, 255, 255, 0.04)";
            downloadBtn.style.border = "1px solid var(--border-color)";
            downloadBtn.style.borderRadius = "6px";
            downloadBtn.style.padding = "4px 10px";
            downloadBtn.style.color = "var(--text-secondary)";
            downloadBtn.style.fontSize = "12px";
            downloadBtn.style.cursor = "pointer";
            downloadBtn.style.display = "flex";
            downloadBtn.style.alignItems = "center";
            downloadBtn.style.gap = "6px";
            downloadBtn.style.textDecoration = "none";
            downloadBtn.style.transition = "all 0.2s";
            
            downloadBtn.onmouseenter = () => {
                downloadBtn.style.background = "rgba(139, 92, 246, 0.1)";
                downloadBtn.style.borderColor = "var(--primary)";
                downloadBtn.style.color = "var(--primary)";
            };
            downloadBtn.onmouseleave = () => {
                downloadBtn.style.background = "rgba(255, 255, 255, 0.04)";
                downloadBtn.style.borderColor = "var(--border-color)";
                downloadBtn.style.color = "var(--text-secondary)";
            };
            
            playBtn.parentElement.appendChild(downloadBtn);
        }
        
        audio.onended = () => {
            playBtn.disabled = false;
            playBtn.innerHTML = `🔊 Listen`;
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

const btnNewsHistory = document.getElementById("btn-news-history");
const newsVideoHistoryContainer = document.getElementById("news-video-history-container");
const newsVideoHistoryList = document.getElementById("news-video-history-list");
const btnCloseHistory = document.getElementById("btn-close-history");

if (btnNewsVideo) {
    let pollInterval = null;

    const checkAutomationStatus = async () => {
        try {
            const res = await fetch("/v1/automate/news-video/status");
            if (!res.ok) return;
            const data = await res.json();

            if (data.status === "running" || data.status === "pending") {
                btnNewsVideo.disabled = true;
                btnNewsVideo.textContent = "Processing...";
                newsVideoStatusContainer.classList.remove("hidden");
                newsVideoProgress.style.width = `${data.progress || 0}%`;
                newsVideoStatusMsg.textContent = data.message || "Enqueued in Orchestrator...";
                
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
                newsVideoPlayer.load();
                renderVideoStories(data.stories);

                // Refresh history list if it is currently open
                if (newsVideoHistoryContainer && !newsVideoHistoryContainer.classList.contains("hidden")) {
                    fetchVideoHistory();
                }
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

        const topicInput = document.getElementById("auto-topic");
        const dateInput = document.getElementById("auto-date");
        const videoModeSelect = document.getElementById("auto-video-mode");
        const payload = {};
        if (topicInput && topicInput.value && topicInput.value.trim()) {
            payload.topic = topicInput.value.trim();
        }
        if (dateInput && dateInput.value) {
            payload.date = dateInput.value;
        }
        if (videoModeSelect) {
            payload.video_mode = videoModeSelect.value;
        }

        try {
            const res = await fetch("/v1/automate/news-video", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            });
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

    if (btnNewsHistory && newsVideoHistoryContainer) {
        btnNewsHistory.addEventListener("click", () => {
            const isHidden = newsVideoHistoryContainer.classList.toggle("hidden");
            if (!isHidden) {
                fetchVideoHistory();
            }
        });
    }

    if (btnCloseHistory && newsVideoHistoryContainer) {
        btnCloseHistory.addEventListener("click", () => {
            newsVideoHistoryContainer.classList.add("hidden");
        });
    }

    function renderVideoStories(stories) {
        const container = document.getElementById("news-video-sources");
        const list = document.getElementById("news-video-sources-list");
        if (!container || !list) return;
        
        if (!stories || stories.length === 0) {
            container.classList.add("hidden");
            return;
        }
        
        list.innerHTML = "";
        stories.forEach(story => {
            const item = document.createElement("div");
            item.style.cssText = "font-size: 11px; display: flex; flex-direction: column; gap: 2px; padding: 4px 6px; background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 6px; margin-bottom: 2px;";
            
            let domain = "";
            if (story.source_url) {
                try {
                    const urlObj = new URL(story.source_url);
                    domain = urlObj.hostname.replace("www.", "");
                } catch (e) {
                    domain = "Source";
                }
            }
            
            const linkHtml = story.source_url 
                ? `<a href="${story.source_url}" target="_blank" style="color: var(--primary); text-decoration: none; font-size: 10px; font-weight: 600; display: inline-flex; align-items: center; gap: 2px;">🔗 Read on ${domain}</a>`
                : `<span style="color: var(--text-secondary); font-size: 10px; font-style: italic;">No source URL</span>`;
                
            item.innerHTML = `
                <div style="font-weight: 600; color: var(--text-primary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${story.title}</div>
                <div style="font-size: 10px; color: var(--text-secondary); line-height: 1.3;">${story.summary}</div>
                <div style="margin-top: 2px;">${linkHtml}</div>
            `;
            list.appendChild(item);
        });
        
        container.classList.remove("hidden");
    }

    function formatHistoryTimestamp(item) {
        if (item.timestamp) {
            return {
                date: item.timestamp.split(" ")[0],
                time: item.timestamp.split(" ")[1] || ""
            };
        }
        if (item.created_at) {
            const d = new Date(item.created_at * 1000);
            const pad = (n) => String(n).padStart(2, '0');
            const dateStr = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
            const timeStr = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
            return { date: dateStr, time: timeStr };
        }
        return { date: "", time: "" };
    }

    async function fetchVideoHistory() {
        if (!newsVideoHistoryList) return;
        try {
            const res = await fetch("/v1/automate/news-video/history");
            if (!res.ok) throw new Error("Failed to fetch history");
            const data = await res.json();
            
            newsVideoHistoryList.innerHTML = "";
            if (data.length === 0) {
                newsVideoHistoryList.innerHTML = `<div style="font-size: 11px; color: var(--text-secondary); text-align: center; padding: 10px 0;">No generated videos found.</div>`;
                return;
            }
            
            data.forEach(item => {
                const el = document.createElement("div");
                el.style.cssText = `
                    background: rgba(255, 255, 255, 0.03);
                    border: 1px solid var(--border-color);
                    border-radius: 6px;
                    padding: 8px;
                    cursor: pointer;
                    transition: background 0.2s, border-color 0.2s;
                    display: flex;
                    flex-direction: column;
                    gap: 2px;
                    margin-bottom: 2px;
                `;
                const ts = formatHistoryTimestamp(item);
                el.innerHTML = `
                    <div style="font-size: 11px; font-weight: 600; color: var(--text-primary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
                        🎬 ${item.topic}
                    </div>
                    <div style="font-size: 9px; color: var(--text-secondary); display: flex; justify-content: space-between;">
                        <span>Date: ${item.date || ts.date}</span>
                        <span>${ts.date}</span>
                    </div>
                `;
                
                el.addEventListener("mouseenter", () => {
                    el.style.background = "rgba(255, 255, 255, 0.08)";
                    el.style.borderColor = "var(--primary)";
                });
                el.addEventListener("mouseleave", () => {
                    el.style.background = "rgba(255, 255, 255, 0.03)";
                    el.style.borderColor = "var(--border-color)";
                });
                
                el.addEventListener("click", () => {
                    newsVideoPlayer.src = item.video_url;
                    newsVideoPlayerContainer.classList.remove("hidden");
                    newsVideoPlayer.load();
                    newsVideoPlayer.play().catch(err => console.log("Auto-play blocked:", err));
                    renderVideoStories(item.stories);
                });
                
                newsVideoHistoryList.appendChild(el);
            });
        } catch (err) {
            newsVideoHistoryList.innerHTML = `<div style="font-size: 11px; color: var(--accent-red); text-align: center; padding: 10px 0;">Error: ${err.message}</div>`;
        }
    }

    // Check status on load in case a task is already running
    checkAutomationStatus();
}

// Deep Research Agent
const btnStartResearch = document.getElementById("btn-start-research");
const researchStatusContainer = document.getElementById("research-status-container");
const researchProgress = document.getElementById("research-progress");
const researchStatusMsg = document.getElementById("research-status-msg");
const researchResultContainer = document.getElementById("research-result-container");
const linkResearchMd = document.getElementById("link-research-md");
const linkResearchPdf = document.getElementById("link-research-pdf");

const btnResearchHistory = document.getElementById("btn-research-history");
const researchHistoryContainer = document.getElementById("research-history-container");
const researchHistoryList = document.getElementById("research-history-list");
const btnCloseResearchHistory = document.getElementById("btn-close-research-history");

if (btnStartResearch) {
    let researchPollInterval = null;

    const checkResearchStatus = async () => {
        try {
            const res = await fetch("/v1/automate/deep-research/status");
            if (!res.ok) return;
            const data = await res.json();

            if (data.status === "running" || data.status === "pending") {
                btnStartResearch.disabled = true;
                btnStartResearch.textContent = "Researching...";
                researchStatusContainer.classList.remove("hidden");
                researchProgress.style.width = `${data.progress || 0}%`;
                researchStatusMsg.textContent = data.message || "Enqueued in Orchestrator...";
                
                // If pollInterval is not active, start it
                if (!researchPollInterval) {
                    researchPollInterval = setInterval(checkResearchStatus, 2500);
                }
            } else if (data.status === "success") {
                if (researchPollInterval) {
                    clearInterval(researchPollInterval);
                    researchPollInterval = null;
                }
                btnStartResearch.disabled = false;
                btnStartResearch.textContent = "Start Research";
                researchStatusContainer.classList.add("hidden");
                
                linkResearchMd.href = data.report_url;
                linkResearchPdf.href = data.pdf_url;
                researchResultContainer.classList.remove("hidden");

                // Refresh history list if it is currently open
                if (researchHistoryContainer && !researchHistoryContainer.classList.contains("hidden")) {
                    fetchResearchHistory();
                }
            } else if (data.status === "failed") {
                if (researchPollInterval) {
                    clearInterval(researchPollInterval);
                    researchPollInterval = null;
                }
                btnStartResearch.disabled = false;
                btnStartResearch.textContent = "Start Research";
                researchStatusContainer.classList.add("hidden");
                alert(`Research failed: ${data.message}`);
            }
        } catch (err) {
            console.error("Research status check failed", err);
        }
    };

    btnStartResearch.addEventListener("click", async () => {
        console.log("Start Research button clicked!");
        const queryInput = document.getElementById("research-query");
        if (!queryInput || !queryInput.value || !queryInput.value.trim()) {
            alert("Please enter a research topic or query first.");
            return;
        }

        btnStartResearch.disabled = true;
        btnStartResearch.textContent = "Initiating...";
        researchStatusContainer.classList.remove("hidden");
        researchResultContainer.classList.add("hidden");
        researchProgress.style.width = "0%";
        researchStatusMsg.textContent = "Starting deep research agent...";

        try {
            const res = await fetch("/v1/automate/deep-research", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ query: queryInput.value.trim() })
            });
            if (!res.ok) throw new Error("Could not start research task");
            
            // Start polling status
            researchPollInterval = setInterval(checkResearchStatus, 2500);
        } catch (err) {
            alert(`Failed to start deep research: ${err.message}`);
            btnStartResearch.disabled = false;
            btnStartResearch.textContent = "Start Research";
            researchStatusContainer.classList.add("hidden");
        }
    });

    if (btnResearchHistory && researchHistoryContainer) {
        btnResearchHistory.addEventListener("click", () => {
            const isHidden = researchHistoryContainer.classList.toggle("hidden");
            if (!isHidden) {
                fetchResearchHistory();
            }
        });
    }

    if (btnCloseResearchHistory && researchHistoryContainer) {
        btnCloseResearchHistory.addEventListener("click", () => {
            researchHistoryContainer.classList.add("hidden");
        });
    }

    async function fetchResearchHistory() {
        if (!researchHistoryList) return;
        try {
            const res = await fetch("/v1/automate/deep-research/history");
            if (!res.ok) throw new Error("Failed to fetch history");
            const data = await res.json();
            
            researchHistoryList.innerHTML = "";
            if (data.length === 0) {
                researchHistoryList.innerHTML = `<div style="font-size: 11px; color: var(--text-secondary); text-align: center; padding: 10px 0;">No reports found.</div>`;
                return;
            }
            
            data.forEach(item => {
                const el = document.createElement("div");
                el.style.cssText = `
                    background: rgba(255, 255, 255, 0.03);
                    border: 1px solid var(--border-color);
                    border-radius: 6px;
                    padding: 8px;
                    transition: background 0.2s, border-color 0.2s;
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                    margin-bottom: 2px;
                `;
                
                const ts = formatHistoryTimestamp(item);
                el.innerHTML = `
                    <div style="font-size: 11px; font-weight: 600; color: var(--text-primary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;" title="${item.query}">
                        🔬 ${item.query}
                    </div>
                    <div style="display: flex; gap: 4px; align-items: center; justify-content: space-between;">
                        <span style="font-size: 9px; color: var(--text-secondary);">${ts.date}</span>
                        <div style="display: flex; gap: 4px;">
                            <a href="${item.report_url}" target="_blank" style="font-size: 9px; color: var(--text-secondary); text-decoration: none; padding: 2px 4px; background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 4px;">MD</a>
                            <a href="${item.pdf_url}" target="_blank" style="font-size: 9px; color: var(--primary); text-decoration: none; padding: 2px 4px; background: rgba(139, 92, 246, 0.1); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 4px; font-weight: 600;">PDF</a>
                        </div>
                    </div>
                `;
                
                el.addEventListener("mouseenter", () => {
                    el.style.background = "rgba(255, 255, 255, 0.08)";
                    el.style.borderColor = "var(--primary)";
                });
                el.addEventListener("mouseleave", () => {
                    el.style.background = "rgba(255, 255, 255, 0.03)";
                    el.style.borderColor = "var(--border-color)";
                });
                
                researchHistoryList.appendChild(el);
            });
        } catch (err) {
            researchHistoryList.innerHTML = `<div style="font-size: 11px; color: var(--accent-red); text-align: center; padding: 10px 0;">Error: ${err.message}</div>`;
        }
    }

    // Check status on load in case a task is already running
    checkResearchStatus();
}

// Daily Podcast Briefing Agent
const btnStartPodcast = document.getElementById("btn-start-podcast");
const podcastStatusContainer = document.getElementById("podcast-status-container");
const podcastProgress = document.getElementById("podcast-progress");
const podcastStatusMsg = document.getElementById("podcast-status-msg");
const podcastPlayerContainer = document.getElementById("podcast-player-container");
const podcastAudioPlayer = document.getElementById("podcast-audio-player");

const btnPodcastHistory = document.getElementById("btn-podcast-history");
const podcastHistoryContainer = document.getElementById("podcast-history-container");
const podcastHistoryList = document.getElementById("podcast-history-list");
const btnClosePodcastHistory = document.getElementById("btn-close-podcast-history");

if (btnStartPodcast) {
    let podcastPollInterval = null;

    const checkPodcastStatus = async () => {
        try {
            const res = await fetch("/v1/automate/podcast/status");
            if (!res.ok) return;
            const data = await res.json();

            if (data.status === "running" || data.status === "pending") {
                btnStartPodcast.disabled = true;
                btnStartPodcast.textContent = "Generating...";
                podcastStatusContainer.classList.remove("hidden");
                podcastProgress.style.width = `${data.progress || 0}%`;
                podcastStatusMsg.textContent = data.message || "Enqueued in Orchestrator...";
                
                // If pollInterval is not active, start it
                if (!podcastPollInterval) {
                    podcastPollInterval = setInterval(checkPodcastStatus, 2500);
                }
            } else if (data.status === "success") {
                if (podcastPollInterval) {
                    clearInterval(podcastPollInterval);
                    podcastPollInterval = null;
                }
                btnStartPodcast.disabled = false;
                btnStartPodcast.textContent = "Generate Podcast";
                podcastStatusContainer.classList.add("hidden");
                
                podcastAudioPlayer.src = data.podcast_url;
                podcastPlayerContainer.classList.remove("hidden");
                podcastAudioPlayer.load();

                // Refresh history list if open
                if (podcastHistoryContainer && !podcastHistoryContainer.classList.contains("hidden")) {
                    fetchPodcastHistory();
                }
            } else if (data.status === "failed") {
                if (podcastPollInterval) {
                    clearInterval(podcastPollInterval);
                    podcastPollInterval = null;
                }
                btnStartPodcast.disabled = false;
                btnStartPodcast.textContent = "Generate Podcast";
                podcastStatusContainer.classList.add("hidden");
                alert(`Podcast briefing failed: ${data.message}`);
            }
        } catch (err) {
            console.error("Podcast status check failed", err);
        }
    };

    btnStartPodcast.addEventListener("click", async () => {
        console.log("Start Podcast button clicked!");
        btnStartPodcast.disabled = true;
        btnStartPodcast.textContent = "Initiating...";
        podcastStatusContainer.classList.remove("hidden");
        podcastPlayerContainer.classList.add("hidden");
        podcastProgress.style.width = "0%";
        podcastStatusMsg.textContent = "Starting daily news podcast generator...";

        const topicInput = document.getElementById("podcast-topic");
        const dateInput = document.getElementById("podcast-date");
        const payload = {};
        if (topicInput && topicInput.value && topicInput.value.trim()) {
            payload.topic = topicInput.value.trim();
        }
        if (dateInput && dateInput.value) {
            payload.date = dateInput.value;
        }

        try {
            const res = await fetch("/v1/automate/podcast", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error("Could not start podcast briefing");
            
            // Start polling status
            podcastPollInterval = setInterval(checkPodcastStatus, 2500);
        } catch (err) {
            alert(`Failed to start podcast generation: ${err.message}`);
            btnStartPodcast.disabled = false;
            btnStartPodcast.textContent = "Generate Podcast";
            podcastStatusContainer.classList.add("hidden");
        }
    });

    if (btnPodcastHistory && podcastHistoryContainer) {
        btnPodcastHistory.addEventListener("click", () => {
            const isHidden = podcastHistoryContainer.classList.toggle("hidden");
            if (!isHidden) {
                fetchPodcastHistory();
            }
        });
    }

    if (btnClosePodcastHistory && podcastHistoryContainer) {
        btnClosePodcastHistory.addEventListener("click", () => {
            podcastHistoryContainer.classList.add("hidden");
        });
    }

    async function fetchPodcastHistory() {
        if (!podcastHistoryList) return;
        try {
            const res = await fetch("/v1/automate/podcast/history");
            if (!res.ok) throw new Error("Failed to fetch history");
            const data = await res.json();
            
            podcastHistoryList.innerHTML = "";
            if (data.length === 0) {
                podcastHistoryList.innerHTML = `<div style="font-size: 11px; color: var(--text-secondary); text-align: center; padding: 10px 0;">No podcasts found.</div>`;
                return;
            }
            
            data.forEach(item => {
                const el = document.createElement("div");
                el.style.cssText = `
                    background: rgba(255, 255, 255, 0.03);
                    border: 1px solid var(--border-color);
                    border-radius: 6px;
                    padding: 8px;
                    cursor: pointer;
                    transition: background 0.2s, border-color 0.2s;
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                    margin-bottom: 2px;
                `;
                
                const ts = formatHistoryTimestamp(item);
                el.innerHTML = `
                    <div style="font-size: 11px; font-weight: 600; color: var(--text-primary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;" title="${item.query}">
                        🎙️ ${item.query}
                    </div>
                    <div style="font-size: 9px; color: var(--text-secondary); display: flex; justify-content: space-between;">
                        <span>${ts.date}</span>
                        <span style="color: var(--primary); font-weight: 600;">Play Audio</span>
                    </div>
                `;
                
                el.addEventListener("mouseenter", () => {
                    el.style.background = "rgba(255, 255, 255, 0.08)";
                    el.style.borderColor = "var(--primary)";
                });
                el.addEventListener("mouseleave", () => {
                    el.style.background = "rgba(255, 255, 255, 0.03)";
                    el.style.borderColor = "var(--border-color)";
                });
                
                el.addEventListener("click", () => {
                    podcastAudioPlayer.src = item.podcast_url;
                    podcastPlayerContainer.classList.remove("hidden");
                    podcastAudioPlayer.load();
                    podcastAudioPlayer.play().catch(err => console.log("Auto-play blocked:", err));
                });
                
                podcastHistoryList.appendChild(el);
            });
        } catch (err) {
            podcastHistoryList.innerHTML = `<div style="font-size: 11px; color: var(--accent-red); text-align: center; padding: 10px 0;">Error: ${err.message}</div>`;
        }
    }

    // Check status on load in case a task is already running
    checkPodcastStatus();
}

// ==========================================================================
// SETUP MODAL OPERATIONS
// ==========================================================================
let currentlyConfiguredModels = [];
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
            const isFallback = (model.id === "general-llama3" || model.id === "general-qwen3");
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
        } else if (model.type === "vision") {
            card.innerHTML = `
                <h4>👁️ Vision Model (Multimodal): ${model.id}</h4>
                <div class="form-row">
                    <div class="form-group">
                        <label>Model ID</label>
                        <input type="text" class="model-id" value="${model.id}" readonly style="opacity: 0.7;" required>
                    </div>
                    <div class="form-group">
                        <label>Specifier / Purpose</label>
                        <input type="text" class="model-purpose" value="${model.purpose || ""}" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>HF Repo ID</label>
                        <input type="text" class="model-repo" value="${model.backend_config.repo_id || ""}" required>
                    </div>
                    <div class="form-group">
                        <label>HF Filename</label>
                        <input type="text" class="model-filename" value="${model.backend_config.filename || ""}" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>mmproj Repo ID</label>
                        <input type="text" class="model-mmproj-repo" value="${model.backend_config.mmproj_repo_id || ""}" required>
                    </div>
                    <div class="form-group">
                        <label>mmproj Filename</label>
                        <input type="text" class="model-mmproj-filename" value="${model.backend_config.mmproj_filename || ""}" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>VRAM Estimate (GB)</label>
                        <input type="number" class="model-vram" step="0.1" value="${model.vram_estimate_gb}" required>
                    </div>
                    <div class="form-group">
                        <label>Port</label>
                        <input type="number" class="model-port" value="${model.backend_config.port || 8084}" required>
                    </div>
                </div>
            `;
        } else if (model.type === "tts") {
            card.innerHTML = `
                <h4>🗣️ Text-to-Speech (TTS): ${model.id}</h4>
                <div class="form-row">
                    <div class="form-group">
                        <label>TTS Engine</label>
                        <select class="model-tts-engine">
                            <option value="kokoro" ${model.backend_config.engine === "kokoro" ? "selected" : ""}>Kokoro (Offline / High Quality)</option>
                            <option value="pyttsx3" ${model.backend_config.engine === "pyttsx3" ? "selected" : ""}>PyTTSx3 (System Native / Low Resource)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Voice Speaker Name</label>
                        <input type="text" class="model-tts-voice" value="${model.backend_config.voice || ""}" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>VRAM Estimate (GB)</label>
                        <input type="number" class="model-vram" step="0.1" value="${model.vram_estimate_gb}" required>
                    </div>
                </div>
            `;
        } else if (model.type === "video") {
            card.innerHTML = `
                <h4>🎬 Video Generator: ${model.id}</h4>
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
        } else {
            // Unhandled models return empty or keep properties statically
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
            router_model: "routing",
            models: [
                { id: "general", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-1.5B-Instruct-GGUF", filename: "qwen3-1.5b-instruct-q4_k_m.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 1.2, purpose: "general reasoning", n_ctx: null },
                { id: "coding", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-Coder-1.5B-Instruct-GGUF", filename: "qwen3-coder-1.5b-instruct-q4_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 1.2, purpose: "general coding", n_ctx: null },
                { id: "image", type: "image", backend: "diffusers", backend_config: { model_name: "Lykon/dreamshaper-8-lcm" }, vram_estimate_gb: 4.0 },
                { id: "stt", type: "stt", backend: "whisper", backend_config: { model_name: "tiny" }, vram_estimate_gb: 0.5 },
                { id: "tts", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 },
                { id: "reasoning", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF", filename: "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf", port: 8084, n_gpu_layers: 99 }, vram_estimate_gb: 1.2, purpose: "step-by-step logic, math, multi-step planning, complex reasoning, algorithms, and deep analysis", n_ctx: null },
                { id: "story", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-1.5B-Instruct-GGUF", filename: "qwen3-1.5b-instruct-q4_k_m.gguf", port: 8085, n_gpu_layers: 99 }, vram_estimate_gb: 1.2, purpose: "creative writing, storytelling, fiction, prose, novel drafting, character description, roleplay, and creative brainstorming", n_ctx: null },
                { id: "agent", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-1.5B-Instruct-GGUF", filename: "qwen3-1.5b-instruct-q4_k_m.gguf", port: 8086, n_gpu_layers: 99 }, vram_estimate_gb: 1.2, purpose: "agentic workflows, function calling, tool calling, JSON formatting, structured output, and following system instructions", n_ctx: null },
                { id: "multilingual", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-1.5B-Instruct-GGUF", filename: "qwen3-1.5b-instruct-q4_k_m.gguf", port: 8087, n_gpu_layers: 99 }, vram_estimate_gb: 1.2, purpose: "multilingual translation, localized text generation, non-English languages, and multi-language conversation", n_ctx: null },
                { id: "video-generation", type: "video", backend: "comfyui", backend_config: { server_url: "http://127.0.0.1:8188", workflow_path: "workflows/default_t2v.json" }, vram_estimate_gb: 4.0, purpose: "text-to-video scene generation via ComfyUI" }
            ]
        },
        "6": {
            vram: 6.0,
            ram: 16.0,
            router_type: "llm",
            router_model: "routing",
            models: [
                { id: "general", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-3B-Instruct-GGUF", filename: "qwen3-3b-instruct-q4_k_m.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "general reasoning", n_ctx: null },
                { id: "coding", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-Coder-3B-Instruct-GGUF", filename: "qwen3-coder-3b-instruct-q4_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "general coding", n_ctx: null },
                { id: "image", type: "image", backend: "diffusers", backend_config: { model_name: "Lykon/dreamshaper-8-lcm" }, vram_estimate_gb: 4.0 },
                { id: "stt", type: "stt", backend: "whisper", backend_config: { model_name: "base" }, vram_estimate_gb: 0.7 },
                { id: "tts", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 },
                { id: "reasoning", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF", filename: "DeepSeek-R1-Distill-Qwen-1.5B-Q5_K_M.gguf", port: 8084, n_gpu_layers: 99 }, vram_estimate_gb: 1.4, purpose: "step-by-step logic, math, multi-step planning, complex reasoning, algorithms, and deep analysis", n_ctx: null },
                { id: "story", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-3B-Instruct-GGUF", filename: "qwen3-3b-instruct-q4_k_m.gguf", port: 8085, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "creative writing, storytelling, fiction, prose, novel drafting, character description, roleplay, and creative brainstorming", n_ctx: null },
                { id: "agent", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-3B-Instruct-GGUF", filename: "qwen3-3b-instruct-q4_k_m.gguf", port: 8086, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "agentic workflows, function calling, tool calling, JSON formatting, structured output, and following system instructions", n_ctx: null },
                { id: "multilingual", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-3B-Instruct-GGUF", filename: "qwen3-3b-instruct-q4_k_m.gguf", port: 8087, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "multilingual translation, localized text generation, non-English languages, and multi-language conversation", n_ctx: null },
                { id: "video-generation", type: "video", backend: "comfyui", backend_config: { server_url: "http://127.0.0.1:8188", workflow_path: "workflows/default_t2v.json" }, vram_estimate_gb: 5.0, purpose: "text-to-video scene generation via ComfyUI" }
            ]
        },
        "8": {
            vram: 8.0,
            ram: 16.0,
            router_type: "llm",
            router_model: "routing",
            models: [
                { id: "general", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/granite-3.1-8b-instruct-GGUF", filename: "granite-3.1-8b-instruct-Q8_0.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 4.8, purpose: "general reasoning", n_ctx: null },
                { id: "coding", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-Coder-7B-Instruct-GGUF", filename: "qwen3-coder-7b-instruct-q4_k_m.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 4.7, purpose: "general coding", n_ctx: null },
                { id: "image", type: "image", backend: "diffusers", backend_config: { model_name: "Lykon/dreamshaper-8-lcm" }, vram_estimate_gb: 4.0 },
                { id: "stt", type: "stt", backend: "whisper", backend_config: { model_name: "small" }, vram_estimate_gb: 1.5 },
                { id: "tts", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 },
                { id: "reasoning", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/DeepSeek-R1-Distill-Qwen-8B-GGUF", filename: "DeepSeek-R1-Distill-Qwen-8B-Q4_K_M.gguf", port: 8084, n_gpu_layers: 99 }, vram_estimate_gb: 4.8, purpose: "step-by-step logic, math, multi-step planning, complex reasoning, algorithms, and deep analysis", n_ctx: null },
                { id: "story", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/granite-3.1-8b-instruct-GGUF", filename: "granite-3.1-8b-instruct-Q8_0.gguf", port: 8085, n_gpu_layers: 99 }, vram_estimate_gb: 4.8, purpose: "creative writing, storytelling, fiction, prose, novel drafting, character description, roleplay, and creative brainstorming", n_ctx: null },
                { id: "agent", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/granite-3.1-8b-instruct-GGUF", filename: "granite-3.1-8b-instruct-Q8_0.gguf", port: 8086, n_gpu_layers: 99 }, vram_estimate_gb: 4.8, purpose: "agentic workflows, function calling, tool calling, JSON formatting, structured output, and following system instructions", n_ctx: null },
                { id: "multilingual", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "Qwen/Qwen3-7B-Instruct-GGUF", filename: "qwen3-7b-instruct-q4_k_m.gguf", port: 8087, n_gpu_layers: 99 }, vram_estimate_gb: 4.8, purpose: "multilingual translation, localized text generation, non-English languages, and multi-language conversation", n_ctx: null },
                { id: "video-generation", type: "video", backend: "comfyui", backend_config: { server_url: "http://127.0.0.1:8188", workflow_path: "workflows/default_t2v.json" }, vram_estimate_gb: 6.0, purpose: "text-to-video scene generation via ComfyUI" }
            ]
        },
        "16": {
            vram: 16.0,
            ram: 16.0,
            router_type: "llm",
            router_model: "routing",
            models: [
                { id: "general", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen_Qwen3-14B-GGUF", filename: "Qwen_Qwen3-14B-Q5_K_M.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 11.5, purpose: "general reasoning", n_ctx: null },
                { id: "coding", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-Coder-14B-Instruct-GGUF", filename: "Qwen3-Coder-14B-Instruct-Q5_K_M.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 11.5, purpose: "general coding", n_ctx: null },
                { id: "image", type: "image", backend: "diffusers", backend_config: { model_name: "stabilityai/sdxl-turbo" }, vram_estimate_gb: 5.5 },
                { id: "stt", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 },
                { id: "reasoning", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF", filename: "DeepSeek-R1-Distill-Qwen-14B-Q5_K_M.gguf", port: 8084, n_gpu_layers: 99 }, vram_estimate_gb: 11.3, purpose: "step-by-step logic, math, multi-step planning, complex reasoning, algorithms, and deep analysis", n_ctx: null },
                { id: "story", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/phi-4-GGUF", filename: "phi-4-Q5_K_M.gguf", port: 8085, n_gpu_layers: 99 }, vram_estimate_gb: 11.0, purpose: "creative writing, storytelling, fiction, prose, novel drafting, character description, roleplay, and creative brainstorming", n_ctx: null },
                { id: "agent", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/granite-3.1-8b-instruct-GGUF", filename: "granite-3.1-8b-instruct-Q8_0.gguf", port: 8086, n_gpu_layers: 99 }, vram_estimate_gb: 9.5, purpose: "agentic workflows, function calling, tool calling, JSON formatting, structured output, and following system instructions", n_ctx: null },
                { id: "multilingual", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen_Qwen3-14B-GGUF", filename: "Qwen_Qwen3-14B-Q5_K_M.gguf", port: 8087, n_gpu_layers: 99 }, vram_estimate_gb: 11.5, purpose: "multilingual translation, localized text generation, non-English languages, and multi-language conversation", n_ctx: null },
                { id: "video-generation", type: "video", backend: "comfyui", backend_config: { server_url: "http://127.0.0.1:8188", workflow_path: "workflows/default_t2v.json" }, vram_estimate_gb: 9.0, purpose: "text-to-video scene generation via ComfyUI" }
            ]
        },
        "24": {
            vram: 24.0,
            ram: 32.0,
            router_type: "llm",
            router_model: "routing",
            models: [
                { id: "general", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-32B-Instruct-GGUF", filename: "Qwen3-32B-Instruct-Q4_K_M.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 20.3, purpose: "general reasoning", n_ctx: null },
                { id: "coding", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-Coder-32B-Instruct-GGUF", filename: "Qwen3-Coder-32B-Instruct-Q4_K_M.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 20.3, purpose: "general coding", n_ctx: null },
                { id: "image", type: "image", backend: "diffusers", backend_config: { model_name: "black-forest-labs/FLUX.1-schnell" }, vram_estimate_gb: 11.5 },
                { id: "stt", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 },
                { id: "reasoning", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF", filename: "DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf", port: 8084, n_gpu_layers: 99 }, vram_estimate_gb: 20.3, purpose: "step-by-step logic, math, multi-step planning, complex reasoning, algorithms, and deep analysis", n_ctx: null },
                { id: "story", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/phi-4-GGUF", filename: "phi-4-Q5_K_M.gguf", port: 8085, n_gpu_layers: 99 }, vram_estimate_gb: 11.0, purpose: "creative writing, storytelling, fiction, prose, novel drafting, character description, roleplay, and creative brainstorming", n_ctx: null },
                { id: "agent", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/granite-3.1-8b-instruct-GGUF", filename: "granite-3.1-8b-instruct-Q8_0.gguf", port: 8086, n_gpu_layers: 99 }, vram_estimate_gb: 9.5, purpose: "agentic workflows, function calling, tool calling, JSON formatting, structured output, and following system instructions", n_ctx: null },
                { id: "multilingual", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-32B-Instruct-GGUF", filename: "Qwen3-32B-Instruct-Q4_K_M.gguf", port: 8087, n_gpu_layers: 99 }, vram_estimate_gb: 20.3, purpose: "multilingual translation, localized text generation, non-English languages, and multi-language conversation", n_ctx: null },
                { id: "video-generation", type: "video", backend: "comfyui", backend_config: { server_url: "http://127.0.0.1:8188", workflow_path: "workflows/default_t2v.json" }, vram_estimate_gb: 9.0, purpose: "text-to-video scene generation via ComfyUI" }
            ]
        },
        "32": {
            vram: 32.0,
            ram: 32.0,
            router_type: "llm",
            router_model: "routing",
            models: [
                { id: "general", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-32B-Instruct-GGUF", filename: "Qwen3-32B-Instruct-Q5_K_M.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 24.5, purpose: "general reasoning", n_ctx: null },
                { id: "coding", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-Coder-32B-Instruct-GGUF", filename: "Qwen3-Coder-32B-Instruct-Q5_K_M.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 24.5, purpose: "general coding", n_ctx: null },
                { id: "image", type: "image", backend: "diffusers", backend_config: { model_name: "black-forest-labs/FLUX.1-dev" }, vram_estimate_gb: 12.0 },
                { id: "stt", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 },
                { id: "reasoning", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF", filename: "DeepSeek-R1-Distill-Qwen-32B-Q5_K_M.gguf", port: 8084, n_gpu_layers: 99 }, vram_estimate_gb: 24.5, purpose: "step-by-step logic, math, multi-step planning, complex reasoning, algorithms, and deep analysis", n_ctx: null },
                { id: "story", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-32B-Instruct-GGUF", filename: "Qwen3-32B-Instruct-Q5_K_M.gguf", port: 8085, n_gpu_layers: 99 }, vram_estimate_gb: 24.5, purpose: "creative writing, storytelling, fiction, prose, novel drafting, character description, roleplay, and creative brainstorming", n_ctx: null },
                { id: "agent", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/granite-3.1-8b-instruct-GGUF", filename: "granite-3.1-8b-instruct-Q8_0.gguf", port: 8086, n_gpu_layers: 99 }, vram_estimate_gb: 9.5, purpose: "agentic workflows, function calling, tool calling, JSON formatting, structured output, and following system instructions", n_ctx: null },
                { id: "multilingual", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-32B-Instruct-GGUF", filename: "Qwen3-32B-Instruct-Q5_K_M.gguf", port: 8087, n_gpu_layers: 99 }, vram_estimate_gb: 24.5, purpose: "multilingual translation, localized text generation, non-English languages, and multi-language conversation", n_ctx: null },
                { id: "video-generation", type: "video", backend: "comfyui", backend_config: { server_url: "http://127.0.0.1:8188", workflow_path: "workflows/default_t2v.json" }, vram_estimate_gb: 9.0, purpose: "text-to-video scene generation via ComfyUI" }
            ]
        },
        "64": {
            vram: 64.0,
            ram: 64.0,
            router_type: "llm",
            router_model: "routing",
            models: [
                { id: "general", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", filename: "Llama-3.3-70B-Instruct-Q5_K_S.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "general reasoning", n_ctx: null },
                { id: "coding", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-Coder-32B-Instruct-GGUF", filename: "Qwen3-Coder-32B-Instruct-Q8_0.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 35.0, purpose: "general coding", n_ctx: null },
                { id: "image", type: "image", backend: "diffusers", backend_config: { model_name: "black-forest-labs/FLUX.1-dev" }, vram_estimate_gb: 16.0 },
                { id: "stt", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 },
                { id: "reasoning", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF", filename: "DeepSeek-R1-Distill-Llama-70B-Q5_K_M.gguf", port: 8084, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "step-by-step logic, math, multi-step planning, complex reasoning, algorithms, and deep analysis", n_ctx: null },
                { id: "story", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", filename: "Llama-3.3-70B-Instruct-Q5_K_S.gguf", port: 8085, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "creative writing, storytelling, fiction, prose, novel drafting, character description, roleplay, and creative brainstorming", n_ctx: null },
                { id: "agent", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-Coder-32B-Instruct-GGUF", filename: "Qwen3-Coder-32B-Instruct-Q8_0.gguf", port: 8086, n_gpu_layers: 99 }, vram_estimate_gb: 35.0, purpose: "agentic workflows, function calling, tool calling, JSON formatting, structured output, and following system instructions", n_ctx: null },
                { id: "multilingual", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", filename: "Llama-3.3-70B-Instruct-Q5_K_S.gguf", port: 8087, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "multilingual translation, localized text generation, non-English languages, and multi-language conversation", n_ctx: null },
                { id: "video-generation", type: "video", backend: "comfyui", backend_config: { server_url: "http://127.0.0.1:8188", workflow_path: "workflows/default_t2v.json" }, vram_estimate_gb: 9.0, purpose: "text-to-video scene generation via ComfyUI" }
            ]
        },
        "128": {
            vram: 128.0,
            ram: 128.0,
            router_type: "llm",
            router_model: "routing",
            models: [
                { id: "general", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", filename: "Llama-3.3-70B-Instruct-Q5_K_S.gguf", port: 8081, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "general reasoning", n_ctx: null },
                { id: "coding", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-Coder-32B-Instruct-GGUF", filename: "Qwen3-Coder-32B-Instruct-Q8_0.gguf", port: 8082, n_gpu_layers: 99 }, vram_estimate_gb: 35.0, purpose: "general coding", n_ctx: null },
                { id: "image", type: "image", backend: "diffusers", backend_config: { model_name: "black-forest-labs/FLUX.1-dev" }, vram_estimate_gb: 22.0 },
                { id: "stt", type: "stt", backend: "whisper", backend_config: { model_name: "large-v3" }, vram_estimate_gb: 4.8 },
                { id: "tts", type: "tts", backend: "tts", backend_config: { engine: "kokoro", voice: "af_sarah" }, vram_estimate_gb: 0.5 },
                { id: "routing", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "microsoft/Phi-3-mini-4k-instruct-gguf", filename: "Phi-3-mini-4k-instruct-q4.gguf", port: 8083, n_gpu_layers: 99 }, vram_estimate_gb: 2.2, purpose: "routing classification", n_ctx: 4096 },
                { id: "reasoning", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF", filename: "DeepSeek-R1-Distill-Llama-70B-Q5_K_M.gguf", port: 8084, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "step-by-step logic, math, multi-step planning, complex reasoning, algorithms, and deep analysis", n_ctx: null },
                { id: "story", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", filename: "Llama-3.3-70B-Instruct-Q5_K_S.gguf", port: 8085, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "creative writing, storytelling, fiction, prose, novel drafting, character description, roleplay, and creative brainstorming", n_ctx: null },
                { id: "agent", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Qwen3-Coder-32B-Instruct-GGUF", filename: "Qwen3-Coder-32B-Instruct-Q8_0.gguf", port: 8086, n_gpu_layers: 99 }, vram_estimate_gb: 35.0, purpose: "agentic workflows, function calling, tool calling, JSON formatting, structured output, and following system instructions", n_ctx: null },
                { id: "multilingual", type: "llm", backend: "llama.cpp", backend_config: { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", filename: "Llama-3.3-70B-Instruct-Q5_K_S.gguf", port: 8087, n_gpu_layers: 99 }, vram_estimate_gb: 48.0, purpose: "multilingual translation, localized text generation, non-English languages, and multi-language conversation", n_ctx: null },
                { id: "video-generation", type: "video", backend: "comfyui", backend_config: { server_url: "http://127.0.0.1:8188", workflow_path: "workflows/default_t2v.json" }, vram_estimate_gb: 9.0, purpose: "text-to-video scene generation via ComfyUI" }
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
            const presetModelIds = new Set(preset.models.map(m => m.id));
            preset.models.forEach(model => {
                renderSetupCard(model);
            });
            currentlyConfiguredModels.forEach(model => {
                if (!presetModelIds.has(model.id)) {
                    renderSetupCard(model);
                }
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
            currentlyConfiguredModels = config.models || [];

            // Populate resource limits
            document.getElementById("setup-vram").value = config.resource_limits.max_vram_gb;
            document.getElementById("setup-ram").value = config.resource_limits.max_ram_gb;
            document.getElementById("setup-hf-token").value = config.hf_token || "";
            document.getElementById("setup-tg-token").value = config.telegram_bot_token || "";
            document.getElementById("setup-tg-chat").value = config.telegram_chat_id || "";

            // Populate search settings
            const searchProviderSelect = document.getElementById("setup-search-provider");
            const searchSearxngUrl = document.getElementById("setup-search-searxng-url");
            const searchTavilyKey = document.getElementById("setup-search-tavily-key");
            const searchGoogleKey = document.getElementById("setup-search-google-key");
            const searchGoogleCx = document.getElementById("setup-search-google-cx");
            
            const searchConfig = config.search || { provider: "duckduckgo", searxng_url: "", tavily_api_key: "", google_api_key: "", google_cse_id: "" };
            searchProviderSelect.value = searchConfig.provider || "duckduckgo";
            searchSearxngUrl.value = searchConfig.searxng_url || "";
            searchTavilyKey.value = searchConfig.tavily_api_key || "";
            searchGoogleKey.value = searchConfig.google_api_key || "";
            searchGoogleCx.value = searchConfig.google_cse_id || "";
            
            const updateSearchFields = () => {
                const prov = searchProviderSelect.value;
                document.getElementById("setup-search-searxng-group").classList.toggle("hidden", prov !== "searxng");
                document.getElementById("setup-search-tavily-group").classList.toggle("hidden", prov !== "tavily");
                document.getElementById("setup-search-google-group").classList.toggle("hidden", prov !== "google");
            };
            searchProviderSelect.onchange = updateSearchFields;
            updateSearchFields();

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

    // Download All Models Button
    const btnDownloadAll = document.getElementById("btn-download-all");
    const downloadAllProgress = document.getElementById("download-all-progress");
    const downloadAllLabel = document.getElementById("download-all-label");
    const downloadAllCounter = document.getElementById("download-all-counter");
    const downloadAllBar = document.getElementById("download-all-bar");
    const downloadAllDesc = document.getElementById("download-all-desc");
    let downloadPollInterval = null;

    function pollDownloadStatus() {
        fetch("/api/models/download-all/status")
            .then(res => res.json())
            .then(data => {
                if (data.total > 0) {
                    downloadAllProgress.style.display = "block";
                    downloadAllCounter.textContent = `${data.completed}/${data.total}`;
                    const pct = (data.completed / data.total) * 100;
                    downloadAllBar.style.width = `${pct}%`;
                    
                    if (data.running && data.current_model) {
                        downloadAllLabel.textContent = `Downloading: ${data.current_model}...`;
                        btnDownloadAll.disabled = true;
                        btnDownloadAll.textContent = "⏳ Downloading...";
                    }
                    
                    if (!data.running) {
                        clearInterval(downloadPollInterval);
                        downloadPollInterval = null;
                        btnDownloadAll.disabled = false;
                        btnDownloadAll.textContent = "⬇ Download All";
                        
                        if (data.errors && data.errors.length > 0) {
                            downloadAllLabel.textContent = `Done with ${data.errors.length} error(s)`;
                            downloadAllBar.style.background = "linear-gradient(90deg, #f59e0b 0%, #ef4444 100%)";
                        } else {
                            downloadAllLabel.textContent = "All models downloaded successfully!";
                            downloadAllBar.style.background = "linear-gradient(90deg, #10b981 0%, #3b82f6 100%)";
                        }
                        pollStatus(); // Refresh sidebar catalog badges
                    }
                }
            })
            .catch(err => console.error("Failed to poll download status:", err));
    }

    if (btnDownloadAll) {
        btnDownloadAll.addEventListener("click", async () => {
            btnDownloadAll.disabled = true;
            btnDownloadAll.textContent = "⏳ Starting...";
            downloadAllBar.style.background = "linear-gradient(90deg, #8b5cf6 0%, #3b82f6 100%)";
            
            try {
                const res = await fetch("/api/models/download-all", { method: "POST" });
                const data = await res.json();
                downloadAllDesc.textContent = data.message;
                
                if (data.status && data.status.running) {
                    downloadAllProgress.style.display = "block";
                    downloadAllLabel.textContent = "Starting download...";
                    downloadAllCounter.textContent = `0/${data.status.total}`;
                    downloadAllBar.style.width = "0%";
                    
                    if (!downloadPollInterval) {
                        downloadPollInterval = setInterval(pollDownloadStatus, 2000);
                    }
                } else {
                    btnDownloadAll.disabled = false;
                    btnDownloadAll.textContent = "⬇ Download All";
                }
            } catch (err) {
                console.error("Failed to trigger bulk download:", err);
                btnDownloadAll.disabled = false;
                btnDownloadAll.textContent = "⬇ Download All";
            }
        });
    }

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
            } else if (type === "vision") {
                const id = card.querySelector(".model-id").value.trim();
                const purpose = card.querySelector(".model-purpose").value.trim();
                const repo = card.querySelector(".model-repo").value.trim();
                const filename = card.querySelector(".model-filename").value.trim();
                const mmprojRepo = card.querySelector(".model-mmproj-repo").value.trim();
                const mmprojFilename = card.querySelector(".model-mmproj-filename").value.trim();
                const vram = parseFloat(card.querySelector(".model-vram").value);
                const port = parseInt(card.querySelector(".model-port").value);
                modelPayloads.push({
                    id: id,
                    type: "vision",
                    backend: "llama.cpp",
                    backend_config: {
                        repo_id: repo,
                        filename: filename,
                        mmproj_repo_id: mmprojRepo,
                        mmproj_filename: mmprojFilename,
                        port: port,
                        n_gpu_layers: 99
                    },
                    vram_estimate_gb: vram,
                    purpose: purpose
                });
            } else if (type === "tts") {
                const engine = card.querySelector(".model-tts-engine").value;
                const voice = card.querySelector(".model-tts-voice").value.trim();
                const vram = parseFloat(card.querySelector(".model-vram").value);
                modelPayloads.push({
                    id: "tts-offline",
                    type: "tts",
                    backend: "tts",
                    backend_config: {
                        engine: engine,
                        voice: voice
                    },
                    vram_estimate_gb: vram
                });
            } else if (type === "video") {
                const modelName = card.querySelector(".model-repo").value.trim();
                const vram = parseFloat(card.querySelector(".model-vram").value);
                modelPayloads.push({
                    id: "video-generation",
                    type: "video",
                    backend: "video",
                    backend_config: {
                        model_name: modelName
                    },
                    vram_estimate_gb: vram,
                    purpose: "text-to-video scene generation"
                });
            } else {
                // Parse hidden/raw model (e.g. tts-offline)
                const rawData = JSON.parse(card.querySelector(".model-raw-json").value);
                modelPayloads.push(rawData);
            }
        });

        // Reconstruct the exact AppConfig structure
        const hfTokenVal = document.getElementById("setup-hf-token").value.trim();
        const tgTokenVal = document.getElementById("setup-tg-token").value.trim();
        const tgChatVal = document.getElementById("setup-tg-chat").value.trim();
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
                fallback_model: "general-qwen3"
            },
            search: {
                provider: document.getElementById("setup-search-provider").value,
                searxng_url: document.getElementById("setup-search-searxng-url").value.trim(),
                tavily_api_key: document.getElementById("setup-search-tavily-key").value.trim(),
                google_api_key: document.getElementById("setup-search-google-key").value.trim(),
                google_cse_id: document.getElementById("setup-search-google-cx").value.trim()
            },
            models: modelPayloads,
            hf_token: hfTokenVal || null,
            telegram_bot_token: tgTokenVal || null,
            telegram_chat_id: tgChatVal || null
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
// SETTINGS MODAL TAB OPERATIONS & DISK CACHE MANAGEMENT
// ==========================================================================
const modalTabBtns = document.querySelectorAll(".modal-tab-btn");
const modalTabContents = document.querySelectorAll(".modal-tab-content");
const cacheGgufSize = document.getElementById("cache-gguf-size");
const cacheHfSize = document.getElementById("cache-hf-size");
const cacheTotalSize = document.getElementById("cache-total-size");
const cacheSearchInput = document.getElementById("cache-search");
const cacheFilterConfigured = document.getElementById("cache-filter-configured");
const cacheFilterDownloaded = document.getElementById("cache-filter-downloaded");
const cacheSortSelect = document.getElementById("cache-sort");
const cacheModelsList = document.getElementById("cache-models-list");
const btnRefreshCache = document.getElementById("btn-refresh-cache");

let cachedModelsData = [];

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function formatTimestamp(timestamp) {
    if (!timestamp) return "Never";
    const date = new Date(timestamp * (timestamp < 10000000000 ? 1000 : 1));
    return date.toLocaleDateString() + " " + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

if (modalTabBtns.length > 0) {
    modalTabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            modalTabBtns.forEach(b => {
                b.classList.remove("active");
                b.style.color = "var(--text-secondary)";
                b.style.borderBottomColor = "transparent";
            });
            modalTabContents.forEach(c => c.classList.add("hidden"));

            btn.classList.add("active");
            btn.style.color = "var(--text-primary)";
            btn.style.borderBottomColor = "var(--primary)";
            
            const targetTab = btn.getAttribute("data-modal-tab");
            const element = document.getElementById(targetTab);
            if (element) {
                element.classList.remove("hidden");
            }

            if (targetTab === "modal-tab-cache") {
                loadCacheStats();
            }
        });
    });
}

async function loadCacheStats() {
    if (!cacheModelsList) return;
    cacheModelsList.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 20px; color: var(--text-secondary);">⏳ Loading cache and model statistics...</td></tr>`;
    
    try {
        const res = await fetch("/api/cache/stats");
        if (!res.ok) throw new Error("Failed to fetch cache stats.");
        const data = await res.json();
        
        if (cacheGgufSize) cacheGgufSize.textContent = formatBytes(data.total_gguf_size_bytes);
        if (cacheHfSize) cacheHfSize.textContent = formatBytes(data.total_hf_size_bytes);
        if (cacheTotalSize) cacheTotalSize.textContent = formatBytes(data.total_cache_size_bytes);
        
        cachedModelsData = data.models || [];
        renderCacheModels();
    } catch (err) {
        cacheModelsList.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 20px; color: var(--accent-red);">❌ Error: ${err.message}</td></tr>`;
    }
}

function renderCacheModels() {
    if (!cacheModelsList) return;
    
    const searchQuery = cacheSearchInput ? cacheSearchInput.value.toLowerCase().trim() : "";
    const configFilter = cacheFilterConfigured ? cacheFilterConfigured.value : "all";
    const downloadFilter = cacheFilterDownloaded ? cacheFilterDownloaded.value : "all";
    const sortBy = cacheSortSelect ? cacheSortSelect.value : "size_desc";
    
    let filtered = cachedModelsData.filter(model => {
        const nameMatch = (model.display_name || "").toLowerCase().includes(searchQuery) || 
                          (model.repo_id || "").toLowerCase().includes(searchQuery) ||
                          (model.filename || "").toLowerCase().includes(searchQuery) ||
                          (model.backend || "").toLowerCase().includes(searchQuery) ||
                          (model.type || "").toLowerCase().includes(searchQuery);
                          
        let configMatch = true;
        if (configFilter === "configured") configMatch = model.is_configured;
        if (configFilter === "unconfigured") configMatch = !model.is_configured;
        
        let downloadMatch = true;
        if (downloadFilter === "downloaded") downloadMatch = model.is_downloaded;
        if (downloadFilter === "not_downloaded") downloadMatch = !model.is_downloaded;
        
        return nameMatch && configMatch && downloadMatch;
    });
    
    filtered.sort((a, b) => {
        if (sortBy === "size_desc") {
            return (b.size_bytes || 0) - (a.size_bytes || 0);
        }
        if (sortBy === "size_asc") {
            return (a.size_bytes || 0) - (b.size_bytes || 0);
        }
        if (sortBy === "configured_first") {
            if (a.is_configured !== b.is_configured) {
                return a.is_configured ? -1 : 1;
            }
            return (b.size_bytes || 0) - (a.size_bytes || 0);
        }
        if (sortBy === "last_used_newest") {
            return (b.last_used || 0) - (a.last_used || 0);
        }
        if (sortBy === "last_used_oldest") {
            return (a.last_used || 9999999999) - (b.last_used || 9999999999);
        }
        if (sortBy === "name_asc") {
            return (a.display_name || "").localeCompare(b.display_name || "");
        }
        return 0;
    });
    
    if (filtered.length === 0) {
        cacheModelsList.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 20px; color: var(--text-secondary);">No models found matching the filters.</td></tr>`;
        return;
    }
    
    cacheModelsList.innerHTML = "";
    filtered.forEach(model => {
        const tr = document.createElement("tr");
        tr.style.borderBottom = "1px solid rgba(255,255,255,0.05)";
        
        const detailsHtml = `
            <div style="font-weight: 600; color: var(--text-primary); font-size: 12.5px;">${model.display_name}</div>
            <div style="font-size: 10px; color: var(--text-secondary); margin-top: 2px; word-break: break-all;">
                ${model.repo_id ? `HF: ${model.repo_id}` : (model.filename ? `File: ${model.filename}` : 'Local Model')}
            </div>
        `;
        
        const backendBadge = `<span class="badge" style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); font-size: 10px; padding: 2px 6px; border-radius: 4px;">${model.backend || model.type}</span>`;
        
        const sizeText = model.is_downloaded ? formatBytes(model.size_bytes) : '<span style="color: var(--text-secondary); font-style: italic;">Not Cached</span>';
        
        const configBadge = model.is_configured 
            ? `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600;">Yes</span>` 
            : `<span style="background: rgba(255,255,255,0.05); color: var(--text-secondary); border: 1px solid rgba(255,255,255,0.1); font-size: 10px; padding: 2px 6px; border-radius: 4px;">No</span>`;
            
        const lastUsedText = formatTimestamp(model.last_used);
        
        let actionHtml = "";
        if (model.is_configured) {
            actionHtml = `<button type="button" class="btn btn-secondary" disabled title="Cannot delete configured model" style="font-size: 10px; padding: 4px 8px; opacity: 0.4; cursor: not-allowed; width: 60px;">Active</button>`;
        } else if (model.is_downloaded) {
            actionHtml = `<button type="button" class="btn btn-delete-cache" style="font-size: 10px; padding: 4px 8px; background: rgba(239, 68, 68, 0.15); color: var(--accent-red); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; cursor: pointer; transition: all 0.2s ease; width: 60px;">Delete</button>`;
        } else {
            actionHtml = `<span style="color: var(--text-secondary); font-style: italic; font-size: 10px;">None</span>`;
        }
        
        tr.innerHTML = `
            <td style="padding: 10px 14px; vertical-align: middle;">${detailsHtml}</td>
            <td style="padding: 10px 14px; vertical-align: middle;">${backendBadge}</td>
            <td style="padding: 10px 14px; vertical-align: middle; text-align: right; font-family: monospace;">${sizeText}</td>
            <td style="padding: 10px 14px; vertical-align: middle; text-align: center;">${configBadge}</td>
            <td style="padding: 10px 14px; vertical-align: middle; color: var(--text-secondary); font-size: 11px;">${lastUsedText}</td>
            <td style="padding: 10px 14px; vertical-align: middle; text-align: center;">${actionHtml}</td>
        `;
        
        const deleteBtn = tr.querySelector(".btn-delete-cache");
        if (deleteBtn) {
            deleteBtn.addEventListener("click", async () => {
                const confirmMsg = `Are you sure you want to delete the cached files for "${model.display_name}"?\nThis will free up ${formatBytes(model.size_bytes)} of disk space.`;
                if (confirm(confirmMsg)) {
                    deleteBtn.disabled = true;
                    deleteBtn.textContent = "⏳ Deleting";
                    
                    try {
                        const delRes = await fetch("/api/cache/models", {
                            method: "DELETE",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                filename: model.filename,
                                repo_id: model.repo_id
                            })
                        });
                        
                        if (!delRes.ok) {
                            const errData = await delRes.json();
                            throw new Error(errData.detail || "Failed to delete cache files.");
                        }
                        
                        alert(`Successfully freed up ${formatBytes(model.size_bytes)}!`);
                        loadCacheStats();
                    } catch (delErr) {
                        alert(`Error deleting cache: ${delErr.message}`);
                        deleteBtn.disabled = false;
                        deleteBtn.textContent = "Delete";
                    }
                }
            });
        }
        
        cacheModelsList.appendChild(tr);
    });
}

if (cacheSearchInput) cacheSearchInput.addEventListener("input", renderCacheModels);
if (cacheFilterConfigured) cacheFilterConfigured.addEventListener("change", renderCacheModels);
if (cacheFilterDownloaded) cacheFilterDownloaded.addEventListener("change", renderCacheModels);
if (cacheSortSelect) cacheSortSelect.addEventListener("change", renderCacheModels);
if (btnRefreshCache) btnRefreshCache.addEventListener("click", loadCacheStats);

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

// ==========================================================================
// SCHEDULES MANAGEMENT (DAILY TRIGGERS & BOT WORKFLOWS)
// ==========================================================================
(function() {
    const schTypeSelect = document.getElementById("sch-type");
    const schTimeInput = document.getElementById("sch-time");
    const schTargetInput = document.getElementById("sch-target");
    const schTargetLabel = document.getElementById("sch-target-label");
    const schParamsGroup = document.getElementById("sch-params-group");
    const schParamsTopic = document.getElementById("sch-params-topic");
    const btnAddSchedule = document.getElementById("btn-add-schedule");
    const schedulesListContainer = document.getElementById("schedules-list-container");

    if (schTypeSelect) {
        schTypeSelect.addEventListener("change", () => {
            const schTargetGroup = document.getElementById("sch-target-group");
            const schVideoModeGroup = document.getElementById("sch-video-mode-group");
            if (schTypeSelect.value === "query") {
                schTargetLabel.textContent = "Query Prompt";
                schTargetInput.placeholder = "e.g. Explain quantum computing...";
                schTargetInput.value = "";
                if (schTargetGroup) schTargetGroup.style.display = "flex";
                schParamsGroup.style.display = "none";
                if (schVideoModeGroup) schVideoModeGroup.style.display = "none";
            } else {
                schTargetLabel.textContent = "Automation Target";
                schTargetInput.placeholder = "e.g. news-video";
                schTargetInput.value = schTypeSelect.value;
                if (schTargetGroup) schTargetGroup.style.display = "none";
                schParamsGroup.style.display = "flex";
                
                // Show video mode dropdown only if scheduling Daily Video Briefing
                if (schTypeSelect.value === "news-video") {
                    if (schVideoModeGroup) schVideoModeGroup.style.display = "flex";
                } else {
                    if (schVideoModeGroup) schVideoModeGroup.style.display = "none";
                }
            }
        });

        // Add daily schedule to API config
        btnAddSchedule.addEventListener("click", async () => {
            const typeSelectVal = schTypeSelect.value;
            let targetVal = schTargetInput.value.trim();
            if (typeSelectVal !== "query") {
                targetVal = typeSelectVal; // e.g. "news-video", "deep-research", "podcast"
            }
            
            if (!targetVal) {
                alert("Please enter a query prompt or select an automation target.");
                return;
            }

            const payload = {
                type: (typeSelectVal === "query") ? "query" : "automation",
                time: schTimeInput.value,
                target: targetVal
            };

            if (payload.type === "automation") {
                payload.parameters = {
                    topic: schParamsTopic.value.trim() || ""
                };
                if (targetVal === "news-video") {
                    const schVideoModeSelect = document.getElementById("sch-video-mode");
                    if (schVideoModeSelect) {
                        payload.parameters.video_mode = schVideoModeSelect.value;
                    }
                }
            }

            btnAddSchedule.disabled = true;
            try {
                const res = await fetch("/api/schedules", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                if (!res.ok) throw new Error("Failed to save schedule.");
                
                schTargetInput.value = "";
                schParamsTopic.value = "";
                
                fetchSchedules();
            } catch (err) {
                alert(`Error adding schedule: ${err.message}`);
            } finally {
                btnAddSchedule.disabled = false;
            }
        });

        // Load schedule list catalog from endpoints
        async function fetchSchedules() {
            if (!schedulesListContainer) return;
            try {
                const res = await fetch("/api/schedules");
                if (!res.ok) throw new Error("Could not list schedules.");
                const data = await res.json();

                schedulesListContainer.innerHTML = "";
                if (data.length === 0) {
                    schedulesListContainer.innerHTML = `<div style="font-size: 11px; color: var(--text-secondary); text-align: center; padding: 10px 0;">No active schedules.</div>`;
                    return;
                }

                data.forEach(item => {
                    const el = document.createElement("div");
                    el.style.cssText = `
                        background: rgba(255, 255, 255, 0.03);
                        border: 1px solid var(--border-color);
                        border-radius: 6px;
                        padding: 8px;
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        gap: 8px;
                        margin-bottom: 4px;
                    `;
                    
                    let displayName = item.target;
                    let extraDesc = "";
                    if (item.target === "news-video") {
                        displayName = "Video Briefing";
                        const modeLabel = item.parameters?.video_mode === "text_to_video" ? "Text2Vid" : (item.parameters?.video_mode === "image_to_video" ? "Img2Vid" : "Static");
                        extraDesc = ` (${modeLabel})`;
                    }
                    else if (item.target === "deep-research") displayName = "Deep Research";
                    else if (item.target === "podcast") displayName = "Podcast Briefing";
                    
                    const desc = item.type === "query" 
                        ? `💬 Prompt: "${item.target.length > 25 ? item.target.slice(0, 22) + '...' : item.target}"`
                        : `⚙️ Auto: "${displayName}"${extraDesc}${item.parameters?.topic ? ' (' + item.parameters.topic + ')' : ''}`;

                    el.innerHTML = `
                        <div style="flex-grow: 1; min-width: 0;">
                            <div style="font-size: 11px; font-weight: 600; color: var(--text-primary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
                                ${desc}
                            </div>
                            <div style="font-size: 9px; color: var(--text-secondary); margin-top: 2px;">
                                Time: ${item.time} (Daily)
                            </div>
                        </div>
                        <button type="button" class="btn-del-schedule" data-id="${item.id}" style="background: none; border: none; color: var(--accent-red); cursor: pointer; font-size: 14px; padding: 0 4px;">🗑️</button>
                    `;

                    // Bind delete listener
                    el.querySelector(".btn-del-schedule").addEventListener("click", async (e) => {
                        const id = e.target.dataset.id;
                        if (confirm("Are you sure you want to delete this schedule?")) {
                            try {
                                const delRes = await fetch(`/api/schedules/${id}`, { method: "DELETE" });
                                if (!delRes.ok) throw new Error("Could not delete.");
                                fetchSchedules();
                            } catch (err) {
                                alert(`Error deleting: ${err.message}`);
                            }
                        }
                    });

                    schedulesListContainer.appendChild(el);
                });
            } catch (err) {
                schedulesListContainer.innerHTML = `<div style="font-size: 11px; color: var(--accent-red); text-align: center; padding: 10px 0;">Error listing: ${err.message}</div>`;
            }
        }

        fetchSchedules();
    }

    // Telegram Bot Log history logic
    const headerTgHistory = document.getElementById("header-tg-history");
    const btnRefreshTgHistory = document.getElementById("btn-refresh-tg-history");
    const telegramHistoryList = document.getElementById("telegram-history-list");

    if (headerTgHistory) {
        headerTgHistory.addEventListener("click", () => {
            const isHidden = headerTgHistory.classList.contains("collapsed");
            if (!isHidden) {
                fetchTelegramHistory();
            }
        });
    }

    if (btnRefreshTgHistory) {
        btnRefreshTgHistory.addEventListener("click", (e) => {
            e.stopPropagation(); // Prevent toggling the collapsible header
            fetchTelegramHistory();
        });
    }

    async function fetchTelegramHistory() {
        if (!telegramHistoryList) return;
        try {
            const res = await fetch("/api/telegram/history");
            if (!res.ok) throw new Error("Failed to load Telegram log.");
            const data = await res.json();
            
            telegramHistoryList.innerHTML = "";
            if (data.length === 0) {
                telegramHistoryList.innerHTML = `<div style="font-size: 10px; color: var(--text-secondary); text-align: center; padding: 10px 0;">No messages logged yet.</div>`;
                return;
            }
            
            data.forEach(item => {
                const el = document.createElement("div");
                el.style.cssText = `
                    font-size: 11px;
                    padding: 6px 8px;
                    border-radius: 6px;
                    background: ${item.sender === 'User' ? 'rgba(139, 92, 246, 0.08)' : 'rgba(255, 255, 255, 0.02)'};
                    border-left: 3px solid ${item.sender === 'User' ? 'var(--primary)' : 'var(--text-secondary)'};
                    margin-bottom: 2px;
                `;
                
                const ts = formatHistoryTimestamp(item);
                const timeStr = ts.time;
                
                el.innerHTML = `
                    <div style="display: flex; justify-content: space-between; font-size: 9px; color: var(--text-secondary); margin-bottom: 2px; font-weight: 600;">
                        <span>${item.sender === 'User' ? '👤 User' : '🤖 Bot'}</span>
                        <span>${timeStr}</span>
                    </div>
                    <div style="word-break: break-word; line-height: 1.3; white-space: pre-wrap; font-family: var(--font-main); color: var(--text-primary);">
                        ${escapeHtml(item.message)}
                    </div>
                `;
                telegramHistoryList.appendChild(el);
            });
        } catch (err) {
            telegramHistoryList.innerHTML = `<div style="font-size: 10px; color: var(--accent-red); text-align: center; padding: 10px 0;">Error: ${err.message}</div>`;
        }
    }
})();

// ==========================================================================
// SIDEBAR POPOUT MANAGEMENT (POP OUT PANE TO MAIN VIEW)
// ==========================================================================
let currentPoppedElement = null;
let currentPoppedParent = null;

function popoutSection(header) {
    if (!header) return;
    const content = header.nextElementSibling;
    if (!content) return;
    
    // Extract title text cleanly
    const titleSpan = header.querySelector("span");
    const title = titleSpan ? titleSpan.textContent.trim() : "Details";
    
    // Find or create main-popout-view inside main
    let popoutView = document.getElementById("main-popout-view");
    if (!popoutView) {
        popoutView = document.createElement("div");
        popoutView.id = "main-popout-view";
        popoutView.style.cssText = `
            display: none;
            flex-direction: column;
            height: 100%;
            width: 100%;
            padding: 24px;
            background: #0f111a;
            overflow-y: auto;
            position: relative;
        `;
        
        const mainPane = document.querySelector(".chat-container");
        if (mainPane) {
            mainPane.appendChild(popoutView);
        }
    }
    
    // If something is already popped out, restore it first
    restorePoppedSection();
    
    // Hide chat messages and the input area
    const chatMessages = document.getElementById("chat-messages");
    const chatInputArea = document.querySelector(".chat-input-area");
    if (chatMessages) chatMessages.style.display = "none";
    if (chatInputArea) chatInputArea.style.display = "none";
    
    // Set up popout header inside main-popout-view
    popoutView.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color); padding-bottom: 16px; margin-bottom: 24px;">
            <h2 style="font-size: 20px; font-weight: 600; color: var(--text-primary); margin: 0; display: flex; align-items: center; gap: 8px;">
                ${title}
            </h2>
            <button type="button" id="btn-close-popout" class="btn btn-secondary" style="font-size: 11px; padding: 6px 12px; cursor: pointer; border-radius: 6px; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border-color); color: var(--text-primary);">Close & Back to Chat</button>
        </div>
        <div id="popout-content-body" style="flex-grow: 1; min-height: 0;">
        </div>
    `;
    
    // Keep track of the original parent so we can restore it
    currentPoppedParent = content;
    
    // Get the child card element of content (usually class .automation-card or .models-catalog or .conversations-history)
    const childCard = content.firstElementChild;
    if (childCard) {
        currentPoppedElement = childCard;
        // Make sure it has display block / visible
        childCard.style.display = "block";
        const body = document.getElementById("popout-content-body");
        if (body) {
            body.appendChild(childCard);
        }
    }
    
    // Collapse the sidebar content to avoid visual redundancy
    if (!content.classList.contains("collapsed")) {
        content.classList.add("collapsed");
        const chevron = header.querySelector(".chevron");
        if (chevron) chevron.textContent = "▶";
    }
    
    // Display the popout view
    popoutView.style.display = "flex";
    
    // Bind close handler
    const closeBtn = document.getElementById("btn-close-popout");
    if (closeBtn) {
        closeBtn.addEventListener("click", restorePoppedSection);
    }
}

function restorePoppedSection() {
    if (!currentPoppedElement || !currentPoppedParent) return;
    
    // Move the element back to its original parent in the sidebar
    currentPoppedParent.appendChild(currentPoppedElement);
    
    currentPoppedElement = null;
    currentPoppedParent = null;
    
    // Hide popout view
    const popoutView = document.getElementById("main-popout-view");
    if (popoutView) popoutView.style.display = "none";
    
    // Restore chat messages and input area
    const chatMessages = document.getElementById("chat-messages");
    const chatInputArea = document.querySelector(".chat-input-area");
    if (chatMessages) chatMessages.style.display = "flex";
    if (chatInputArea) chatInputArea.style.display = "flex";
}

// -------------------------------------------------------------------------
// MODEL LOAD/UNLOAD QUICK ACTIONS
// -------------------------------------------------------------------------
window.loadModel = async function(modelId) {
    try {
        const response = await fetch(`/api/models/${modelId}/load`, { method: "POST" });
        if (!response.ok) {
            const err = await response.json();
            alert("Load failed: " + err.detail);
        }
    } catch (e) {
        alert("Load failed: " + e);
    }
    pollStatus();
};

window.unloadModel = async function(modelId) {
    try {
        const response = await fetch(`/api/models/${modelId}/unload`, { method: "POST" });
        if (!response.ok) {
            const err = await response.json();
            alert("Unload failed: " + err.detail);
        }
    } catch (e) {
        alert("Unload failed: " + e);
    }
    pollStatus();
};

// -------------------------------------------------------------------------
// DEDICATED MEDIA DRAWER CONTROLLER
// -------------------------------------------------------------------------
const openMediaBtn = document.getElementById("open-media");
const closeMediaBtn = document.getElementById("close-media");
const mediaDrawer = document.getElementById("media-drawer");
const drawerContentPane = document.getElementById("drawer-content-pane");
let activeDrawerTab = "images";

if (openMediaBtn && closeMediaBtn && mediaDrawer) {
    openMediaBtn.addEventListener("click", () => {
        mediaDrawer.classList.remove("closed");
        loadDrawerTab(activeDrawerTab);
    });

    closeMediaBtn.addEventListener("click", () => {
        mediaDrawer.classList.add("closed");
    });
}

document.querySelectorAll(".drawer-tab").forEach(tab => {
    tab.addEventListener("click", (e) => {
        document.querySelectorAll(".drawer-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        activeDrawerTab = tab.getAttribute("data-tab");
        loadDrawerTab(activeDrawerTab);
    });
});

async function loadDrawerTab(tab) {
    if (!drawerContentPane) return;
    drawerContentPane.innerHTML = `<div style="text-align: center; color: var(--text-secondary); padding: 40px 10px; font-size: 13px;">Loading assets...</div>`;
    
    try {
        if (tab === "images") {
            const res = await fetch("/api/images");
            const images = await res.json();
            if (images.length === 0) {
                drawerContentPane.innerHTML = `<div class="drawer-no-data">No generated images found.</div>`;
                return;
            }
            let html = `<div class="drawer-grid">`;
            images.forEach(img => {
                html += `
                    <div class="drawer-img-card" style="position: relative;" onclick="window.open('${img.url}', '_blank')">
                        <img src="${img.url}" alt="${img.name}" title="Generated on: ${new Date(img.created * 1000).toLocaleString()}">
                        <button class="drawer-delete-btn" onclick="event.stopPropagation(); deleteImage('${img.name}')" title="Delete image">&times;</button>
                    </div>
                `;
            });
            html += `</div>`;
            drawerContentPane.innerHTML = html;
        } else if (tab === "videos") {
            const res = await fetch("/v1/automate/news-video/history");
            const videos = await res.json();
            if (videos.length === 0) {
                drawerContentPane.innerHTML = `<div class="drawer-no-data">No generated videos found.</div>`;
                return;
            }
            let html = "";
            videos.forEach(vid => {
                const fileUrl = vid.video_url || `/static/videos/${vid.filename}`;
                html += `
                    <div class="drawer-item-card" style="position: relative;">
                        <button class="drawer-delete-btn" onclick="deleteMedia('${vid.id}')" title="Delete video">&times;</button>
                        <span class="drawer-item-title" title="${vid.topic || 'General News'}">${vid.topic || 'General News'}</span>
                        <video src="${fileUrl}" controls style="width: 100%; border-radius: 6px; background: #000;"></video>
                        <div class="drawer-item-meta">
                            <span>${vid.date || ''}</span>
                            <a href="${fileUrl}" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">Download</a>
                        </div>
                    </div>
                `;
            });
            drawerContentPane.innerHTML = html;
        } else if (tab === "reports") {
            const res = await fetch("/v1/automate/deep-research/history");
            const reports = await res.json();
            if (reports.length === 0) {
                drawerContentPane.innerHTML = `<div class="drawer-no-data">No research reports found.</div>`;
                return;
            }
            let html = "";
            reports.forEach(rep => {
                const mdUrl = rep.report_url || `/static/reports/${rep.md_filename}`;
                const pdfUrl = rep.pdf_url || `/static/reports/${rep.pdf_filename}`;
                html += `
                    <div class="drawer-item-card" style="position: relative;">
                        <button class="drawer-delete-btn" onclick="deleteMedia('${rep.id}')" title="Delete report">&times;</button>
                        <span class="drawer-item-title" title="${rep.query}">${rep.query}</span>
                        <div class="drawer-item-meta">
                            <span>Research Report</span>
                            <div style="display: flex; gap: 10px;">
                                <a href="${mdUrl}" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">Markdown</a>
                                <a href="${pdfUrl}" target="_blank" style="color: var(--secondary); text-decoration: none; font-weight: 600;">PDF</a>
                            </div>
                        </div>
                    </div>
                `;
            });
            drawerContentPane.innerHTML = html;
        } else if (tab === "podcasts") {
            const res = await fetch("/v1/automate/podcast/history");
            const podcasts = await res.json();
            if (podcasts.length === 0) {
                drawerContentPane.innerHTML = `<div class="drawer-no-data">No podcast briefings found.</div>`;
                return;
            }
            let html = "";
            podcasts.forEach(pod => {
                const fileUrl = pod.podcast_url || `/static/podcasts/${pod.filename}`;
                html += `
                    <div class="drawer-item-card" style="position: relative;">
                        <button class="drawer-delete-btn" onclick="deleteMedia('${pod.id}')" title="Delete podcast">&times;</button>
                        <span class="drawer-item-title" title="${pod.topic || 'General briefing'}">${pod.topic || 'General briefing'}</span>
                        <audio src="${fileUrl}" controls style="width: 100%; height: 32px; outline: none;"></audio>
                        <div class="drawer-item-meta">
                            <span>${pod.date || ''}</span>
                            <a href="${fileUrl}" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">Download</a>
                        </div>
                    </div>
                `;
            });
            drawerContentPane.innerHTML = html;
        }
    } catch (err) {
        console.error(err);
        drawerContentPane.innerHTML = `<div style="color: var(--accent-red); text-align: center; padding: 20px; font-size: 13px;">Failed to load assets: ${err.message}</div>`;
    }
}

async function deleteImage(filename) {
    if (!confirm(`Are you sure you want to delete the image "${filename}"? This will delete the file from disk permanently.`)) {
        return;
    }
    try {
        const res = await fetch(`/api/images/${filename}`, { method: "DELETE" });
        const data = await res.json();
        if (res.ok && data.status === "success") {
            loadDrawerTab("images");
        } else {
            alert("Delete failed: " + (data.detail || data.message));
        }
    } catch (e) {
        alert("Error deleting image: " + e.message);
    }
}

async function deleteMedia(itemId) {
    if (!confirm(`Are you sure you want to delete this media briefing? This will remove it from database history and delete all associated files from disk permanently.`)) {
        return;
    }
    try {
        const res = await fetch(`/api/media/${itemId}`, { method: "DELETE" });
        const data = await res.json();
        if (res.ok && data.status === "success") {
            loadDrawerTab(activeDrawerTab);
        } else {
            alert("Delete failed: " + (data.detail || data.message));
        }
    } catch (e) {
        alert("Error deleting media: " + e.message);
    }
}

// -------------------------------------------------------------------------
// STATS DASHBOARD CONTROLLER
// -------------------------------------------------------------------------
let currentStatsPeriod = "session";
let cachedStatsData = null;

// Period selector click handlers
document.querySelectorAll(".stats-period-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".stats-period-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentStatsPeriod = btn.getAttribute("data-period");
        if (cachedStatsData) {
            renderStatsForPeriod(cachedStatsData, currentStatsPeriod);
        }
    });
});

async function loadStatsDashboard() {
    try {
        const [statsRes, registryRes] = await Promise.all([
            fetch("/api/stats"),
            fetch("/api/models/registry")
        ]);
        const statsData = await statsRes.json();
        const registryData = await registryRes.json();
        
        cachedStatsData = statsData;
        renderStatsForPeriod(statsData, currentStatsPeriod);
        renderModelRegistry(registryData);
    } catch (err) {
        console.error("Failed to load stats dashboard:", err);
    }
}

function formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return n.toLocaleString();
}

function renderStatsForPeriod(allData, period) {
    const data = allData[period];
    if (!data) return;
    
    document.getElementById("stat-total-requests").textContent = formatNumber(data.total_requests);
    document.getElementById("stat-prompt-tokens").textContent = formatNumber(data.total_prompt_tokens);
    document.getElementById("stat-completion-tokens").textContent = formatNumber(data.total_completion_tokens);
    document.getElementById("stat-avg-tps").textContent = data.avg_tokens_sec.toFixed(1);
    document.getElementById("stat-avg-load").textContent = data.avg_load_time.toFixed(2) + "s";
    document.getElementById("stat-avg-ttft").textContent = data.avg_time_to_first_token.toFixed(2) + "s";
    
    // Render per-model table
    const tbody = document.getElementById("stats-model-tbody");
    if (!data.models || data.models.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color: var(--text-secondary); padding: 40px;">No model usage data for this period.</td></tr>`;
        return;
    }
    
    // Sort by requests descending
    const sorted = [...data.models].sort((a, b) => b.requests - a.requests);
    let html = "";
    sorted.forEach(m => {
        html += `
            <tr>
                <td class="stats-model-id">
                    <div style="font-weight: 600; color: var(--primary);">${m.model_id}</div>
                    <div style="font-size: 11px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px;" title="${m.model_name || ''}">${m.model_name || ''}</div>
                </td>
                <td>${formatNumber(m.requests)}</td>
                <td>${formatNumber(m.prompt_tokens)}</td>
                <td>${formatNumber(m.completion_tokens)}</td>
                <td class="stats-tps-value">${m.avg_tokens_sec.toFixed(1)}</td>
                <td>${m.avg_load_time.toFixed(2)}s</td>
                <td>${m.avg_time_to_first_token.toFixed(2)}s</td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

function renderModelRegistry(models) {
    const container = document.getElementById("model-registry-grid");
    if (!models || models.length === 0) {
        container.innerHTML = `<div style="text-align:center; color: var(--text-secondary); padding: 40px; grid-column: 1/-1;">No models registered yet. Models are registered when the server starts.</div>`;
        return;
    }
    
    const typeIcons = {
        "llm": "🧠",
        "image": "🎨",
        "vision": "👁️",
        "tts": "🔊",
        "stt": "🎙️",
        "video": "🎬"
    };
    
    let html = "";
    models.forEach(m => {
        const isActive = m.is_active === 1;
        const badgeClass = isActive ? "active" : "historical";
        const badgeLabel = isActive ? "Active" : "Historical";
        const cardClass = isActive ? "" : "inactive";
        const icon = typeIcons[m.model_type] || "📦";
        const firstSeen = m.first_seen ? new Date(m.first_seen * 1000).toLocaleDateString() : "Unknown";
        const lastSeen = m.last_seen ? new Date(m.last_seen * 1000).toLocaleDateString() : "Unknown";
        
        html += `
            <div class="registry-card ${cardClass}">
                <div class="registry-card-header">
                    <span class="registry-card-name">${icon} ${m.display_name}</span>
                    <span class="registry-card-badge ${badgeClass}">${badgeLabel}</span>
                </div>
                <div class="registry-card-meta">
                    <span>🏷️ Function: <strong>${m.function_id}</strong></span>
                    <span>⚙️ Backend: <strong>${m.backend}</strong></span>
                    <span>📐 VRAM: <strong>${m.vram_estimate_gb.toFixed(1)} GB</strong></span>
                    <span>📅 First Seen: <strong>${firstSeen}</strong></span>
                    <span>🕐 Last Seen: <strong>${lastSeen}</strong></span>
                </div>
                ${m.purpose ? `<div class="registry-card-purpose">${m.purpose}</div>` : ''}
            </div>
        `;
    });
    container.innerHTML = html;
}

// Auto-load stats when Stats tab is activated
// Hook into existing tab click logic
let statsInterval = null;

const statsTabObserver = new MutationObserver(() => {
    const statsPane = document.getElementById("stats-pane");
    if (statsPane && statsPane.classList.contains("active")) {
        loadStatsDashboard();
        if (!statsInterval) {
            statsInterval = setInterval(loadStatsDashboard, 4000); // refresh stats every 4s
        }
    } else {
        if (statsInterval) {
            clearInterval(statsInterval);
            statsInterval = null;
        }
    }
});

const statsPane = document.getElementById("stats-pane");
if (statsPane) {
    statsTabObserver.observe(statsPane, { attributes: true, attributeFilter: ["class"] });
}

// -------------------------------------------------------------------------
// MCP HUB CONTROLLER
// -------------------------------------------------------------------------
let cachedMcpTools = [];

async function loadMcpHub() {
    try {
        const [serversRes, toolsRes] = await Promise.all([
            fetch("/api/mcp/servers"),
            fetch("/api/mcp/tools")
        ]);
        const serversData = await serversRes.json();
        const toolsData = await toolsRes.json();
        
        cachedMcpTools = toolsData.tools || [];
        renderMcpServers(serversData.servers || []);
        renderMcpTools(cachedMcpTools);
    } catch (err) {
        console.error("Failed to load MCP Hub:", err);
    }
}

function renderMcpServers(servers) {
    const container = document.getElementById("mcp-servers-grid");
    if (!container) return;
    
    if (servers.length === 0) {
        container.innerHTML = `<div style="text-align:center; color: var(--text-secondary); padding: 40px; grid-column: 1/-1;">No MCP servers configured. Add them under mcp_servers in config.yaml.</div>`;
        return;
    }
    
    let html = "";
    servers.forEach(srv => {
        const statusBadgeClass = srv.is_running ? "active" : "inactive";
        const statusLabel = srv.is_running ? "Running" : "Stopped";
        
        html += `
            <div class="mcp-server-card">
                <div class="mcp-server-card-header">
                    <span class="mcp-server-name">🔌 ${srv.name}</span>
                    <span class="mcp-status-badge ${statusBadgeClass}">${statusLabel}</span>
                </div>
                <div class="mcp-server-details">
                    <span>Command: <code>${srv.command}</code></span>
                    <span>Arguments: <code>${srv.args.join(" ")}</code></span>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

function renderMcpTools(tools) {
    const container = document.getElementById("mcp-tools-list");
    if (!container) return;
    
    if (tools.length === 0) {
        container.innerHTML = `<div style="text-align:center; color: var(--text-secondary); padding: 40px; grid-column: 1/-1;">No active tools. Boot a server to register tools.</div>`;
        return;
    }
    
    let html = "";
    tools.forEach((t, index) => {
        const schema = t.inputSchema || {};
        const props = schema.properties || {};
        const required = schema.required || [];
        
        let paramsHtml = "";
        const propKeys = Object.keys(props);
        if (propKeys.length > 0) {
            paramsHtml += `<div class="mcp-tool-params-title">Parameters:</div>`;
            paramsHtml += `<div class="mcp-tool-params-list">`;
            propKeys.forEach(k => {
                const isReq = required.includes(k) ? '<span style="color:#ef4444;" title="Required">*</span>' : '';
                const pType = props[k].type || "string";
                const pDesc = props[k].description ? ` - ${props[k].description}` : '';
                paramsHtml += `
                    <div class="mcp-tool-param-item">
                        <span class="mcp-param-name">${k}${isReq}</span>
                        <span class="mcp-param-type">${pType}${pDesc}</span>
                    </div>
                `;
            });
            paramsHtml += `</div>`;
        } else {
            paramsHtml += `<div class="mcp-tool-params-title">No parameters required.</div>`;
        }
        
        const testPlaceholderObj = {};
        propKeys.forEach(k => {
            testPlaceholderObj[k] = props[k].type === "number" ? 0 : props[k].type === "boolean" ? false : "";
        });
        const placeholderJson = JSON.stringify(testPlaceholderObj, null, 2);
        
        html += `
            <div class="mcp-tool-card" data-name="${t.name}" data-desc="${t.description || ''}">
                <div class="mcp-tool-header">
                    <span class="mcp-tool-title">${t.name}</span>
                    <span class="mcp-tool-namespace">Server: ${t.server_name}</span>
                </div>
                <div class="mcp-tool-desc">${t.description || 'No description provided.'}</div>
                ${paramsHtml}
                
                <!-- Testing Playground -->
                <div class="mcp-tool-test-area">
                    <div class="mcp-test-input-group">
                        <label>Test Arguments (JSON):</label>
                        <textarea id="test-args-${index}" class="mcp-test-textarea" placeholder='${placeholderJson}'>${placeholderJson}</textarea>
                    </div>
                    <button class="mcp-test-submit-btn" onclick="executeMcpToolTest('${t.server_name}', '${t.name}', ${index})">Test Tool</button>
                    <div id="test-output-${index}" class="mcp-test-output hidden"></div>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

async function executeMcpToolTest(serverName, toolName, index) {
    const textarea = document.getElementById(`test-args-${index}`);
    const outputDiv = document.getElementById(`test-output-${index}`);
    if (!textarea || !outputDiv) return;
    
    outputDiv.classList.remove("hidden");
    outputDiv.textContent = "Executing...";
    outputDiv.style.color = "var(--accent)";
    
    try {
        let args = {};
        const val = textarea.value.trim();
        if (val) {
            args = JSON.parse(val);
        }
        
        const response = await fetch("/api/mcp/call", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                server_name: serverName,
                tool_name: toolName,
                arguments: args
            })
        });
        
        const result = await response.json();
        
        if (result.isError) {
            outputDiv.style.color = "#ef4444";
        } else {
            outputDiv.style.color = "var(--accent)";
        }
        
        outputDiv.textContent = JSON.stringify(result, null, 2);
    } catch (err) {
        outputDiv.style.color = "#ef4444";
        outputDiv.textContent = `Error: ${err.message}`;
    }
}

// Search filtering logic
const toolSearchInput = document.getElementById("mcp-tool-search");
if (toolSearchInput) {
    toolSearchInput.addEventListener("input", (e) => {
        const query = e.target.value.toLowerCase().trim();
        document.querySelectorAll(".mcp-tool-card").forEach(card => {
            const name = card.getAttribute("data-name").toLowerCase();
            const desc = card.getAttribute("data-desc").toLowerCase();
            if (name.includes(query) || desc.includes(query)) {
                card.style.display = "flex";
            } else {
                card.style.display = "none";
            }
        });
    });
}

// Auto-load MCP tools when MCP tab is activated
const mcpTabObserver = new MutationObserver(() => {
    const mcpPane = document.getElementById("mcp-pane");
    if (mcpPane && mcpPane.classList.contains("active")) {
        loadMcpHub();
    }
});

const mcpPane = document.getElementById("mcp-pane");
if (mcpPane) {
    mcpTabObserver.observe(mcpPane, { attributes: true, attributeFilter: ["class"] });
}

// -------------------------------------------------------------------------
// AGENT JOB QUEUE CONTROLLER
// -------------------------------------------------------------------------
const btnToggleQueue = document.getElementById("btn-toggle-queue");

async function checkQueueStatus() {
    try {
        const res = await fetch("/api/jobs/queue/status");
        if (!res.ok) return;
        const data = await res.json();
        updateQueueToggleButton(data.paused);
    } catch (err) {
        console.error("Failed to check queue status:", err);
    }
}

function updateQueueToggleButton(isPaused) {
    if (!btnToggleQueue) return;
    if (isPaused) {
        btnToggleQueue.textContent = "▶️ Resume Queue";
        btnToggleQueue.style.background = "rgba(16, 185, 129, 0.1)";
        btnToggleQueue.style.color = "#10b981";
        btnToggleQueue.style.borderColor = "rgba(16, 185, 129, 0.25)";
    } else {
        btnToggleQueue.textContent = "⏸️ Pause Queue";
        btnToggleQueue.style.background = "rgba(245, 158, 11, 0.1)";
        btnToggleQueue.style.color = "#f59e0b";
        btnToggleQueue.style.borderColor = "rgba(245, 158, 11, 0.25)";
    }
}

if (btnToggleQueue) {
    btnToggleQueue.addEventListener("click", async () => {
        try {
            const res = await fetch("/api/jobs/queue/toggle", { method: "POST" });
            if (!res.ok) return;
            const data = await res.json();
            updateQueueToggleButton(data.paused);
            loadOrchestratorJobs();
        } catch (err) {
            console.error("Failed to toggle queue state:", err);
        }
    });
}

async function loadOrchestratorJobs() {
    try {
        const response = await fetch("/api/jobs");
        if (!response.ok) return;
        const jobs = await response.json();
        renderOrchestratorJobs(jobs);
        checkQueueStatus();
    } catch (err) {
        console.error("Failed to load orchestrator jobs:", err);
    }
}

async function cancelOrRemoveJob(jobId) {
    if (!confirm("Are you sure you want to cancel/remove this job?")) return;
    try {
        const res = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
        if (res.ok) {
            loadOrchestratorJobs();
        }
    } catch (err) {
        console.error("Failed to cancel job:", err);
    }
}

async function moveJob(jobId, direction) {
    try {
        const res = await fetch(`/api/jobs/${jobId}/move`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ direction })
        });
        if (res.ok) {
            loadOrchestratorJobs();
        }
    } catch (err) {
        console.error("Failed to move job:", err);
    }
}

function renderOrchestratorJobs(jobs) {
    const tbody = document.getElementById("orchestrator-jobs-tbody");
    if (!tbody) return;
    
    if (jobs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color: var(--text-secondary); padding: 20px;">No jobs enqueued yet. Start an automation to trigger a job.</td></tr>`;
        return;
    }
    
    let html = "";
    jobs.forEach(job => {
        let statusBadge = `<span class="mcp-status-badge inactive">${job.status}</span>`;
        if (job.status === "completed") {
            statusBadge = `<span class="mcp-status-badge active" style="background:rgba(16, 185, 129, 0.12); color:var(--accent); border:1px solid rgba(16, 185, 129, 0.25);">completed</span>`;
        } else if (job.status === "running") {
            statusBadge = `<span class="mcp-status-badge active" style="background:rgba(245, 158, 11, 0.12); color:#f59e0b; border:1px solid rgba(245, 158, 11, 0.25);">running</span>`;
        } else if (job.status === "pending") {
            statusBadge = `<span class="mcp-status-badge inactive" style="background:rgba(255,255,255,0.05); color:var(--text-secondary); border:1px solid var(--border-color);">pending</span>`;
        } else if (job.status === "failed") {
            statusBadge = `<span class="mcp-status-badge inactive" style="background:rgba(239, 68, 68, 0.12); color:#ef4444; border:1px solid rgba(239, 68, 68, 0.25);" title="${job.error || ''}">failed</span>`;
        }
        
        const progPct = Math.round(job.progress * 100);
        const progressHtml = `
            <div style="display:flex; align-items:center; gap:8px;">
                <div class="progress-bar-bg" style="width: 80px; height: 6px; margin: 0; background:rgba(255,255,255,0.05); border-radius:3px; overflow:hidden;">
                    <div class="progress-bar" style="width: ${progPct}%; height: 100%; background:var(--primary); transition: width 0.3s ease;"></div>
                </div>
                <span style="font-size:11px; font-weight:600; color:var(--text-secondary);">${progPct}%</span>
            </div>
        `;
        
        const createdDate = new Date(job.created_at * 1000).toLocaleTimeString();
        let durationStr = "-";
        if (job.started_at) {
            const end = job.completed_at || (Date.now() / 1000);
            const durSec = Math.max(0, Math.round(end - job.started_at));
            const min = Math.floor(durSec / 60);
            const sec = durSec % 60;
            durationStr = min > 0 ? `${min}m ${sec}s` : `${sec}s`;
        }
        
        const topic = job.parameters.topic || job.parameters.query || "-";
        
        let actionsHtml = `<div style="display:flex; gap:6px; justify-content:center; align-items:center;">`;
        if (job.status === "pending") {
            actionsHtml += `
                <button type="button" class="btn btn-secondary" style="padding: 2px 6px; font-size:10px;" onclick="moveJob('${job.id}', 'up')" title="Move Up">🔼</button>
                <button type="button" class="btn btn-secondary" style="padding: 2px 6px; font-size:10px;" onclick="moveJob('${job.id}', 'down')" title="Move Down">🔽</button>
            `;
        }
        if (job.status === "pending" || job.status === "running") {
            actionsHtml += `
                <button type="button" class="btn btn-secondary" style="padding: 2px 6px; font-size:10px; color:#ef4444; border-color:rgba(239,68,68,0.15); background:rgba(239,68,68,0.05);" onclick="cancelOrRemoveJob('${job.id}')" title="Cancel/Remove">❌</button>
            `;
        } else {
            if (job.status === "completed" && job.result) {
                let viewUrl = "";
                let viewLabel = "👁️ View";
                if (job.task_type === "news-video") {
                    viewUrl = job.result.video_url;
                    viewLabel = "🎬 Play";
                } else if (job.task_type === "deep-research") {
                    viewUrl = job.result.pdf_url || job.result.report_url;
                    viewLabel = "📄 PDF";
                } else if (job.task_type === "podcast") {
                    viewUrl = job.result.podcast_url;
                    viewLabel = "🎧 Listen";
                }
                if (viewUrl) {
                    actionsHtml += `
                        <a href="${viewUrl}" target="_blank" class="btn btn-secondary" style="padding: 2px 6px; font-size:10px; text-decoration: none; color: var(--primary); border-color: rgba(99, 102, 241, 0.25); display: inline-flex; align-items: center; gap: 2px;" title="View Output">${viewLabel}</a>
                    `;
                }
            }
            actionsHtml += `
                <button type="button" class="btn btn-secondary" style="padding: 2px 6px; font-size:10px; opacity: 0.6;" onclick="cancelOrRemoveJob('${job.id}')" title="Delete Log">🗑️</button>
            `;
        }
        actionsHtml += `</div>`;
        
        html += `
            <tr>
                <td style="font-weight:600; color:var(--text-primary);">${job.task_type}</td>
                <td>${statusBadge}</td>
                <td>${progressHtml}</td>
                <td style="font-family:var(--font-mono); font-weight:600; color:var(--primary);">${job.vram_required.toFixed(1)} GB</td>
                <td>${createdDate}</td>
                <td>${durationStr}</td>
                <td style="max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${topic}">${topic}</td>
                <td>${actionsHtml}</td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

window.moveJob = moveJob;
window.cancelOrRemoveJob = cancelOrRemoveJob;

const btnRefreshJobs = document.getElementById("btn-refresh-jobs");
if (btnRefreshJobs) {
    btnRefreshJobs.addEventListener("click", loadOrchestratorJobs);
}

let jobsInterval = null;
const automationsTabObserver = new MutationObserver(() => {
    const autoPane = document.getElementById("automations-pane");
    if (autoPane && autoPane.classList.contains("active")) {
        loadOrchestratorJobs();
        if (!jobsInterval) {
            jobsInterval = setInterval(loadOrchestratorJobs, 3000);
        }
    } else {
        if (jobsInterval) {
            clearInterval(jobsInterval);
            jobsInterval = null;
        }
    }
});

const autoPane = document.getElementById("automations-pane");
if (autoPane) {
    automationsTabObserver.observe(autoPane, { attributes: true, attributeFilter: ["class"] });
}

// ==========================================================================
// FIRST-RUN ONBOARDING SETUP WIZARD
// ==========================================================================
let onboardingOpened = false;
let onboardingInit = false;
let selectedPreset = null;
let onboardingDownloadInterval = null;

function checkOnboarding(status) {
    if (onboardingOpened) return;
    onboardingOpened = true;
    
    // Fetch raw config to get actual model configs for merging undefined models
    fetch("/api/config")
        .then(res => res.json())
        .then(config => {
            currentlyConfiguredModels = config.models || [];
        })
        .catch(err => console.error("Failed to fetch initial config models:", err));
        
    const modal = document.getElementById("onboarding-modal");
    if (!modal) return;
    
    // Show modal
    modal.classList.remove("hidden");
    
    // Populate VRAM
    const vramVal = status.limits.max_vram_gb;
    const vramLabel = document.getElementById("detected-vram-label");
    if (vramLabel) {
        vramLabel.textContent = `${vramVal.toFixed(1)} GB`;
    }
    
    // Determine recommended preset
    let recommendedPreset = "4";
    if (vramVal >= 15.0) {
        recommendedPreset = "16";
    } else if (vramVal >= 7.0) {
        recommendedPreset = "8";
    }
    
    // Show recommended badge
    const recommendedCard = document.querySelector(`.preset-card[data-preset="${recommendedPreset}"]`);
    if (recommendedCard) {
        recommendedCard.classList.add("recommended");
        const badge = recommendedCard.querySelector(".recommend-badge");
        if (badge) badge.classList.remove("hidden");
    }
    
    if (!onboardingInit) {
        onboardingInit = true;
        setupOnboardingEvents(vramVal);
    }
}

function setupOnboardingEvents(vramVal) {
    const step1 = document.getElementById("onboarding-step-1");
    const step2 = document.getElementById("onboarding-step-2");
    const step3 = document.getElementById("onboarding-step-3");
    
    const btnNext1 = document.getElementById("btn-onboarding-next-1");
    const btnNext2 = document.getElementById("btn-onboarding-next-2");
    const btnBack2 = document.getElementById("btn-onboarding-back-2");
    const btnBack3 = document.getElementById("btn-onboarding-back-3");
    
    const presetCards = document.querySelectorAll(".preset-card");
    const btnSkip = document.getElementById("btn-onboarding-skip-download");
    const btnDownload = document.getElementById("btn-onboarding-download");
    
    // Step 1 -> Step 2
    btnNext1.addEventListener("click", () => {
        step1.classList.add("hidden");
        step2.classList.remove("hidden");
    });
    
    // Preset Card Selection
    presetCards.forEach(card => {
        card.addEventListener("click", () => {
            presetCards.forEach(c => c.classList.remove("selected"));
            card.classList.add("selected");
            selectedPreset = card.getAttribute("data-preset");
            btnNext2.disabled = false;
        });
    });
    
    // Step 2 Back
    btnBack2.addEventListener("click", () => {
        step2.classList.add("hidden");
        step1.classList.remove("hidden");
    });
    
    // Step 2 -> Step 3
    btnNext2.addEventListener("click", () => {
        if (!selectedPreset) return;
        
        step2.classList.add("hidden");
        step3.classList.remove("hidden");
        
        // Update selected preset name
        const presetNameMap = {
            "4": "4 GB VRAM (Ultra-Lightweight)",
            "8": "8 GB VRAM (Standard)",
            "16": "16 GB VRAM (Pro / High-End)"
        };
        document.getElementById("onboarding-selected-preset-name").textContent = presetNameMap[selectedPreset] || selectedPreset;
        
        // Populate models list
        const preset = PRESETS[selectedPreset];
        const modelListEl = document.getElementById("onboarding-models-list");
        modelListEl.innerHTML = "";
        
        if (preset && preset.models) {
            preset.models.forEach(model => {
                const item = document.createElement("div");
                item.style.display = "flex";
                item.style.justifyContent = "space-between";
                item.style.alignItems = "center";
                item.style.padding = "8px 12px";
                item.style.background = "rgba(255,255,255,0.02)";
                item.style.border = "1px solid rgba(255,255,255,0.04)";
                item.style.borderRadius = "8px";
                
                const backendDetail = model.backend_config.filename || model.backend_config.model_name || model.id;
                const badgeClass = `modality-${model.type}`;
                
                item.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="modality-badge ${badgeClass}" style="font-size: 9px; padding: 2px 6px;">${model.type.toUpperCase()}</span>
                        <span style="font-weight: 600; color: var(--text-primary);">${model.id}</span>
                    </div>
                    <span style="font-size: 11px; color: var(--text-secondary); max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${backendDetail}">${backendDetail}</span>
                `;
                modelListEl.appendChild(item);
            });
        }
    });
    
    // Step 3 Back
    btnBack3.addEventListener("click", () => {
        step3.classList.add("hidden");
        step2.classList.remove("hidden");
    });
    
    // Action Buttons
    btnSkip.addEventListener("click", () => {
        saveOnboardingConfig(selectedPreset, false);
    });
    
    btnDownload.addEventListener("click", () => {
        saveOnboardingConfig(selectedPreset, true);
    });
}

async function saveOnboardingConfig(presetKey, startDownloads) {
    const preset = PRESETS[presetKey];
    if (!preset) return;
    
    const btnSkip = document.getElementById("btn-onboarding-skip-download");
    const btnDownload = document.getElementById("btn-onboarding-download");
    const btnBack3 = document.getElementById("btn-onboarding-back-3");
    
    btnSkip.disabled = true;
    btnDownload.disabled = true;
    btnBack3.disabled = true;
    
    try {
        // Fetch current config
        const configRes = await fetch("/api/config");
        if (!configRes.ok) throw new Error("Could not retrieve config from server.");
        const currentConfig = await configRes.json();
        
        // Modify limits
        currentConfig.resource_limits.max_vram_gb = preset.vram;
        currentConfig.resource_limits.max_ram_gb = preset.ram;
        
        // Modify router
        currentConfig.router.model_type = preset.router_type;
        currentConfig.router.model_name = preset.router_model;
        currentConfig.router.fallback_model = "general";
        
        // Overwrite models list, keeping any models not defined in the preset (retaining defaults)
        const presetModelIds = new Set(preset.models.map(m => m.id));
        const mergedModels = [
            ...preset.models,
            ...currentConfig.models.filter(m => !presetModelIds.has(m.id))
        ];
        currentConfig.models = mergedModels;
        
        // Save back config (will set is_first_run to False)
        const saveRes = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(currentConfig)
        });
        if (!saveRes.ok) throw new Error("Server rejected configuration save.");
        
        if (startDownloads) {
            // Trigger download-all
            const downloadSection = document.getElementById("onboarding-download-section");
            downloadSection.style.display = "block";
            
            const triggerRes = await fetch("/api/models/download-all", { method: "POST" });
            const triggerData = await triggerRes.json();
            
            // Start polling progress
            pollOnboardingDownloadStatus();
            onboardingDownloadInterval = setInterval(pollOnboardingDownloadStatus, 2000);
        } else {
            // Close and complete onboarding
            closeOnboardingWizard();
        }
    } catch (err) {
        alert(`Failed to configure CerberAI: ${err.message}`);
        btnSkip.disabled = false;
        btnDownload.disabled = false;
        btnBack3.disabled = false;
    }
}

function pollOnboardingDownloadStatus() {
    const label = document.getElementById("onboarding-download-label");
    const counter = document.getElementById("onboarding-download-counter");
    const bar = document.getElementById("onboarding-download-bar");
    
    fetch("/api/models/download-all/status")
        .then(res => res.json())
        .then(data => {
            if (data.total > 0) {
                counter.textContent = `${data.completed}/${data.total}`;
                const pct = (data.completed / data.total) * 100;
                bar.style.width = `${pct}%`;
                
                if (data.running && data.current_model) {
                    label.textContent = `Downloading: ${data.current_model}...`;
                }
                
                if (!data.running) {
                    clearInterval(onboardingDownloadInterval);
                    onboardingDownloadInterval = null;
                    
                    if (data.errors && data.errors.length > 0) {
                        label.textContent = `Done with ${data.errors.length} error(s)`;
                        bar.style.background = "linear-gradient(90deg, #f59e0b 0%, #ef4444 100%)";
                        setTimeout(() => {
                            closeOnboardingWizard();
                        }, 3000);
                    } else {
                        label.textContent = "All models downloaded successfully!";
                        bar.style.background = "linear-gradient(90deg, #10b981 0%, #3b82f6 100%)";
                        setTimeout(() => {
                            closeOnboardingWizard();
                        }, 2000);
                    }
                }
            } else {
                // No models to download or finished early
                clearInterval(onboardingDownloadInterval);
                closeOnboardingWizard();
            }
        })
        .catch(err => {
            console.error("Failed to poll onboarding download status:", err);
        });
}

function closeOnboardingWizard() {
    if (onboardingDownloadInterval) {
        clearInterval(onboardingDownloadInterval);
    }
    const modal = document.getElementById("onboarding-modal");
    if (modal) {
        modal.classList.add("hidden");
    }
    // Refresh application models and status
    fetchModels();
    pollStatus();
}





