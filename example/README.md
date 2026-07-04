# Connecting Open WebUI to CerberAI

This example provides a pre-configured [docker-compose.yml](file:///home/tonym/Projects/cerberai/example/docker-compose.yml) file to launch **Open WebUI** in a Docker container and hook it up to a running **CerberAI** instance on your host system.

---

## ⚙️ Networking Setup Options

To allow Open WebUI (running inside a Docker container) to communicate with CerberAI (running on the host), you must choose one of the following networking patterns:

### Option A: Standard Bridge Network (Recommended & Default)
This is the default setup. The container runs on a bridge network, exposing Open WebUI on port `3000` (`http://localhost:3000`). It connects to the host machine via `host.docker.internal`.

1. **Configure CerberAI**:
   In your root [config.yaml](file:///home/tonym/Projects/cerberai/config.yaml), you must configure the server host to bind to `0.0.0.0` so it accepts connections from the Docker bridge network interface:
   ```yaml
   server:
     host: 0.0.0.0
     port: 8000
   ```
2. **Launch Open WebUI**:
   Keep [docker-compose.yml](file:///home/tonym/Projects/cerberai/example/docker-compose.yml) as-is and run:
   ```bash
   docker compose up -d
   ```

> [!IMPORTANT]
> If CerberAI is bound to `127.0.0.1` (the default), the Docker container will **not** be able to connect to it using `host.docker.internal`. Make sure to update your `config.yaml` to `0.0.0.0`.

---

### Option B: Host Networking (Linux Only)
This mode shares the host's network namespace directly with the container. It requires no changes to CerberAI's host config and lets Open WebUI access CerberAI via `127.0.0.1`.

1. **Configure CerberAI**:
   CerberAI can remain bound to `127.0.0.1` (localhost) in [config.yaml](file:///home/tonym/Projects/cerberai/config.yaml).
2. **Modify docker-compose.yml**:
   Edit [docker-compose.yml](file:///home/tonym/Projects/cerberai/example/docker-compose.yml):
   - Comment out the `ports` block (lines 14–15).
   - Comment out the `extra_hosts` block (lines 16–17).
   - Uncomment `network_mode: host` (line 25).
   - Change the environment variable URLs (lines 43, 49, 55, 62) from `host.docker.internal` to `127.0.0.1`.
3. **Launch Open WebUI**:
   Run:
   ```bash
   docker compose up -d
   ```
   *Note: Open WebUI will be exposed directly on the host's port `8080` (e.g., `http://localhost:8080`).*

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
