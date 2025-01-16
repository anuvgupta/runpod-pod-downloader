# download.py

import os
import sys
import hashlib
import requests
from pathlib import Path
import subprocess
from typing import List, Tuple
import logging
import time
import signal
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def clone_comfyui() -> List[str]:
    """Clone ComfyUI repo and return list of model folder names."""
    if not os.path.exists("ComfyUI"):
        logger.info("Cloning ComfyUI repository...")
        subprocess.run(["git", "clone", "https://github.com/comfyanonymous/ComfyUI.git"], check=True)
    
    models_path = Path("ComfyUI/models")
    if not models_path.exists():
        raise RuntimeError("Models directory not found in ComfyUI repository")
    
    # Get folder names and filter out hidden folders
    model_folders = [f.name for f in models_path.iterdir() if f.is_dir() and not f.name.startswith('.')]
    logger.info(f"Found model folders: {', '.join(model_folders)}")
    return model_folders

def verify_hash(file_path: str, expected_hash: str) -> bool:
    """Verify SHA256 hash of downloaded file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    
    actual_hash = sha256_hash.hexdigest()
    return actual_hash.lower() == expected_hash.lower()

def download_file(url: str, destination: str):
    """Download file with progress indication and resume support."""
    # Check if file exists and get its size
    file_size = 0
    mode = 'wb'
    if os.path.exists(destination):
        file_size = os.path.getsize(destination)
        mode = 'ab'

    # First make a HEAD request to get the total size
    head = requests.head(url)
    total_size = int(head.headers.get('content-length', 0))

    # If we already have the complete file, no need to download
    if file_size == total_size and total_size > 0:
        logger.info("File is already complete. No need to resume.")
        return

    # Prepare headers for range request
    headers = {}
    if file_size > 0:
        headers['Range'] = f'bytes={file_size}-'
        logger.info(f"Resuming download from byte {file_size}")

    response = requests.get(url, stream=True, headers=headers)
    
    # Handle different response codes
    if response.status_code == 206:  # Partial content
        total_size = int(response.headers.get('content-range').split('/')[-1])
    elif response.status_code == 200:  # Full content
        total_size = int(response.headers.get('content-length', 0))
        # If we got a 200 when trying to resume, server doesn't support range requests
        # Start from beginning
        file_size = 0
        mode = 'wb'
    else:
        response.raise_for_status()

    block_size = 8192
    downloaded = file_size  # Start count from existing file size
    start_time = time.time()
    last_update_time = start_time
    
    with open(destination, mode) as f:
        for data in response.iter_content(block_size):
            downloaded += len(data)
            f.write(data)
            
            current_time = time.time()
            # Only update progress every 2 seconds
            if total_size > 0 and (current_time - last_update_time) >= 2:
                elapsed_time = current_time - start_time
                # Calculate speed based on new data downloaded, not total file size
                download_speed = (downloaded - file_size) / elapsed_time if elapsed_time > 0 else 0
                
                # Calculate ETA
                if download_speed > 0:
                    eta_seconds = (total_size - downloaded) / download_speed
                    eta_str = time.strftime('%M:%S', time.gmtime(eta_seconds))
                else:
                    eta_str = '--:--'
                
                # Calculate progress percentage and downloaded size in MB
                percent = (downloaded * 100) / total_size
                downloaded_mb = downloaded / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                speed_mb = download_speed / (1024 * 1024)
                
                # Create progress bar
                bar_length = 30
                filled_length = int(bar_length * downloaded / total_size)
                bar = '=' * filled_length + '-' * (bar_length - filled_length)
                
                # Print progress
                print(f'\rDownloading: [{bar}] {percent:5.1f}% | '
                      f'{downloaded_mb:.1f}/{total_mb:.1f} MB | '
                      f'{speed_mb:.1f} MB/s | ETA: {eta_str}', 
                      end='', flush=True)
                
                last_update_time = current_time
    
    # Print newline after completion
    if total_size > 0:
        print()
        # Print final stats
        elapsed_time = time.time() - start_time
        if elapsed_time > 0:
            final_speed = (downloaded - file_size) / (1024 * 1024) / elapsed_time
            logger.info(f"Download completed: {downloaded/(1024*1024):.1f}MB in {elapsed_time:.1f}s ({final_speed:.1f}MB/s)")

def parse_models_file(file_path: str) -> List[Tuple[str, str, str, str]]:
    """Parse models.txt file into list of (type, url, filename, hash) tuples."""
    models = []
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                model_type, url, filename, hash_value = line.split()
                models.append((model_type, url, filename, hash_value))
            except ValueError:
                logger.error(f"Invalid line format: {line}")
                raise ValueError(f"Each line must contain exactly four space-separated values: {line}")
    return models

def get_folder_name(model_type: str, comfy_folders: List[str]) -> str:
    """Get the correct folder name, handling singular/plural cases."""
    # Try plural version if singular version not found
    if model_type not in comfy_folders and f"{model_type}s" in comfy_folders:
        return f"{model_type}s"
    return model_type

def main():
    # Check environment variable
    model_cache_path = os.getenv('MODEL_CACHE_PATH')
    if not model_cache_path:
        raise RuntimeError("MODEL_CACHE_PATH environment variable not set")
    
    # Create base cache directory
    cache_path = Path(model_cache_path)
    cache_path.mkdir(parents=True, exist_ok=True)
    
    # Get ComfyUI model folders
    comfy_folders = clone_comfyui()
    
    # Parse models file
    models = parse_models_file('models.txt')
    
    # Process each model
    for model_type, url, filename, expected_hash in models:
        # Get correct folder name (handling singular/plural)
        folder_name = get_folder_name(model_type, comfy_folders)
        
        # Create type-specific subdirectory
        model_dir = cache_path / folder_name
        model_dir.mkdir(exist_ok=True)
        
        file_path = model_dir / filename
        
        # Check if file exists and hash matches
        if file_path.exists():
            logger.info(f"File already exists: {file_path}")
            if verify_hash(str(file_path), expected_hash):
                logger.info(f"Hash verified for existing file: {filename}")
                continue
            else:
                logger.warning(f"Hash mismatch for existing file: {filename}, attempting to resume download")
        
        # Download file
        logger.info(f"Downloading {url} to {file_path}")
        download_file(url, str(file_path))
        
        # Verify hash
        if not verify_hash(str(file_path), expected_hash):
            # Remove file if hash verification fails
            file_path.unlink()
            raise RuntimeError(f"Hash verification failed for downloaded file: {filename}")
        
        logger.info(f"Successfully downloaded and verified: {filename}")

# Global flag for handling graceful shutdown
running = True

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    logger.info("Shutdown signal received. Will exit after current cycle completes...")
    running = False

if __name__ == '__main__':
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    interval = 30 * 60  # 30 minutes in seconds
    
    while running:
        try:
            logger.info(f"Starting download cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            main()
            logger.info(f"Download cycle completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            if not running:
                break
                
            logger.info(f"Waiting {interval//60} minutes until next cycle...")
            # Break the sleep into smaller chunks to respond to signals more quickly
            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in download cycle: {str(e)}")
            # Don't exit on errors, just wait for next cycle
            logger.info(f"Will retry in {interval//60} minutes...")
            time.sleep(interval)

    logger.info("Shutting down gracefully...")
