# Connecting Open WebUI to CerberAI

This example provides a pre-configured [docker-compose.yml](file:///home/tonym/Projects/cerberai/example/docker-compose.yml) file to launch **Open WebUI** in a Docker container and hook it up to a running **CerberAI** instance on your host system.

---

## ⚙️ Networking Setup Options

To allow Open WebUI (running inside a Docker container) to communicate with CerberAI (running on the host), you must choose one of the following networking patterns:

### Option A: Host Networking (Active & Recommended for Linux Hosts)
This is the default configuration active in [docker-compose.yml](file:///home/tonym/Projects/cerberai/example/docker-compose.yml). It shares the host's network namespace directly with the container, allowing it to securely connect to CerberAI on `127.0.0.1:8000` without requiring you to expose CerberAI to the external network (`0.0.0.0`).

* Open WebUI is configured to run on port `3000` using the `PORT=3000` environment variable (avoiding conflicts with other services on port `8080`).
* **URL**: **`http://localhost:3000`**
* **Launch command**:
  ```bash
  docker compose up -d
  ```

---

### Option B: Standard Bridge Network (Alternative)
If you prefer running Open WebUI on a standard isolated Docker bridge network, follow these steps:

1. **Configure CerberAI**:
   In your root [config.yaml](file:///home/tonym/Projects/cerberai/config.yaml), you must configure the server host to bind to `0.0.0.0` so it accepts connections from the Docker bridge network interface:
   ```yaml
   server:
     host: 0.0.0.0
     port: 8000
   ```
2. **Modify docker-compose.yml**:
   Edit [docker-compose.yml](file:///home/tonym/Projects/cerberai/example/docker-compose.yml):
   - Comment out the `network_mode: host` line.
   - Comment out the `PORT=3000` environment variable line.
   - Uncomment the `ports` block:
     ```yaml
     ports:
       - "3000:8080"
     ```
   - Uncomment the `extra_hosts` block:
     ```yaml
     extra_hosts:
       - "host.docker.internal:host-gateway"
     ```
   - Change the API Base URLs from `127.0.0.1` to `host.docker.internal`.
3. **Launch**:
   ```bash
   docker compose up -d
   ```

---

## 🚀 Features Configured

This Docker Compose setup automatically configures Open WebUI to use CerberAI's multi-modal endpoints:

### 1. 🤖 Intelligent Model Routing (`auto`)
When you select the model named **`auto`** in the Open WebUI interface, your queries are processed by CerberAI's **Dynamic Purpose Intent Router**. 
* The router classifies your prompt and dynamically spins up the best-suited model (e.g., loading `coding-qwen` for code development, or `general-llama3` for conversational text) while automatically managing VRAM.

### 2. 🎙️ Speech-to-Text (STT)
Clicking the microphone icon in Open WebUI will use CerberAI's `/v1/audio/transcriptions` endpoint running Whisper.

### 3. 🔊 Text-to-Speech (TTS)
Reading responses aloud will call CerberAI's `/v1/audio/speech` endpoint running the local Kokoro TTS engine.

### 4. 🎨 Image Generation
You can prompt for images directly inside the chat. This connects to CerberAI's `/v1/images/generations` endpoint running Stable Diffusion XL / LCM.
* **To trigger**: Click the "+" button in the chat input or use the image generation toggle in the interface.

---

## 🧹 Maintenance Commands

* **View Logs**:
  ```bash
  docker compose logs -f open-webui
  ```
* **Stop Container**:
  ```bash
  docker compose down
  ```
* **Update Open WebUI**:
  ```bash
  docker compose pull
  docker compose up -d
  ```
