import os
import shutil
import tarfile
import httpx
from pathlib import Path

CACHE_DIR = Path(os.path.expanduser("~/.cache/cerberai/models"))
BIN_DIR = Path(os.path.expanduser("~/.cache/cerberai/bin"))

def get_model_cache_path(filename: str) -> Path:
    """Get the local cache path for a model file, ensuring the directory exists."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / filename

async def download_file(url: str, dest_path: Path, progress_callback=None):
    """Download a file with progress logging."""
    temp_path = dest_path.with_suffix(".tmp")
    print(f"Downloading from {url} to {dest_path}...")
    
    # Ensure parent dir exists
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True, timeout=600.0) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise RuntimeError(f"Failed to download file: HTTP {response.status_code}")
            
            total_bytes = int(response.headers.get("content-length", 0))
            bytes_downloaded = 0
            last_reported = 0.0
            
            with open(temp_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    
                    if total_bytes > 0:
                        percentage = (bytes_downloaded / total_bytes) * 100
                        # Report every 5%
                        if percentage - last_reported >= 5.0 or bytes_downloaded == total_bytes:
                            print(f"Download progress: {percentage:.1f}% ({bytes_downloaded / 1024 / 1024:.1f} MB / {total_bytes / 1024 / 1024:.1f} MB)")
                            last_reported = percentage
                            if progress_callback:
                                progress_callback(percentage)
                    else:
                        # If no content-length, report downloaded size every 10MB
                        mb_downloaded = bytes_downloaded / 1024 / 1024
                        if mb_downloaded - last_reported >= 10.0:
                            print(f"Downloaded: {mb_downloaded:.1f} MB")
                            last_reported = mb_downloaded

    # Atomic swap
    if os.path.exists(dest_path):
        os.remove(dest_path)
    os.rename(temp_path, dest_path)
    print(f"Successfully downloaded {dest_path.name}")

async def ensure_gguf_model(repo_id: str, filename: str, progress_callback=None) -> str:
    """
    Ensures a GGUF model is downloaded locally from Hugging Face.
    Returns the absolute path to the GGUF file.
    """
    dest_path = get_model_cache_path(filename)
    if dest_path.exists():
        return str(dest_path.resolve())

    # Build HuggingFace resolve URL
    url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
    
    try:
        await download_file(url, dest_path, progress_callback)
    except Exception as e:
        temp_path = dest_path.with_suffix(".tmp")
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Failed to auto-download model {repo_id}/{filename}: {e}")

    return str(dest_path.resolve())

async def get_latest_llama_tag() -> str:
    """Fetch the latest release tag from GitHub API for ggml-org/llama.cpp."""
    url = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            headers = {"User-Agent": "CerberAI-Downloader"}
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                tag = response.json().get("tag_name")
                if tag:
                    return tag
    except Exception as e:
        print(f"Warning: Failed to fetch latest tag from GitHub API ({e}). Using fallback tag.")
    return "b9852" # Reliable fallback tag

async def ensure_llama_server() -> str:
    """
    Check if llama-server is in path or cached.
    If not, download precompiled binary package for Linux x64 from GitHub and extract all assets.
    """
    # 1. Check system path
    system_path = shutil.which("llama-server")
    if system_path:
        return system_path
        
    # 2. Check local cache (recursively find it in case it's in a subdirectory like 'bin')
    if BIN_DIR.exists():
        for root, dirs, files in os.walk(BIN_DIR):
            if "llama-server" in files:
                # Verify that key shared libraries also exist, otherwise treat as corrupt cache and re-download
                if "libllama-server-impl.so" in files:
                    server_path = Path(root) / "llama-server"
                    if os.access(server_path, os.X_OK):
                        return str(server_path.resolve())


    # 3. Not found, download it! Get tag dynamically to prevent 404 on expired tags
    tag = await get_latest_llama_tag()
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-ubuntu-x64.tar.gz"
    
    if BIN_DIR.exists():
        shutil.rmtree(BIN_DIR)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    
    tar_path = BIN_DIR / f"llama-{tag}.tar.gz"
    
    try:

        # Download archive
        await download_file(url, tar_path)
        
        # Extract archive
        print("Extracting llama.cpp package (including dynamic libraries and symlinks)...")
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                # Preserve relative path but strip top-level directory prefix if there is one
                parts = Path(member.name).parts
                if len(parts) > 1:
                    member.name = str(Path(*parts[1:]))
                else:
                    member.name = parts[0]
                
                # Extract file, directory, or symbolic link natively
                tar.extract(member, path=BIN_DIR)

                            
        # Now find the extracted llama-server path
        for root, dirs, files in os.walk(BIN_DIR):
            if "llama-server" in files:
                server_path = Path(root) / "llama-server"
                os.chmod(server_path, 0o755)
                # Ensure dynamic libraries next to it are executable too
                for f in files:
                    if f.endswith(".so") or "libllama" in f:
                        try:
                            os.chmod(Path(root) / f, 0o755)
                        except Exception:
                            pass
                print(f"llama-server successfully installed to {server_path}")
                return str(server_path.resolve())
                
        raise RuntimeError("Could not find 'llama-server' binary in the extracted files.")
        
    except Exception as e:
        # Clean up cache on failure
        if BIN_DIR.exists():
            shutil.rmtree(BIN_DIR)
        raise RuntimeError(f"Failed to auto-download llama-server binary: {e}")
    finally:
        # Clean up archive
        if tar_path.exists():
            tar_path.unlink()

