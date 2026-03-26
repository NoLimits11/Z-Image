import runpod
from runpod.serverless.utils import rp_upload
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.parse
import binascii
import time
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1')
client_id = str(uuid.uuid4())

def save_data_if_base64(data_input, temp_dir, output_filename):
    if not isinstance(data_input, str):
        return data_input
    try:
        decoded_data = base64.b64decode(data_input)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        with open(file_path, 'wb') as f:
            f.write(decoded_data)
        logger.info(f"✅ Base64 saved to '{file_path}'")
        return file_path
    except (binascii.Error, ValueError):
        logger.info(f"➡️ '{data_input}' treated as file path.")
        return data_input
    
def queue_prompt(prompt):
    url = f"http://{server_address}:8188/prompt"
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_image(filename, subfolder, folder_type):
    url = f"http://{server_address}:8188/view"
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{url}?{url_values}") as response:
        return response.read()

def get_history(prompt_id):
    url = f"http://{server_address}:8188/history/{prompt_id}"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())

def get_images(ws, prompt):
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_images = {}
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break
        else:
            continue

    history = get_history(prompt_id)[prompt_id]
    for node_id in history['outputs']:
        node_output = history['outputs'][node_id]
        images_output = []
        if 'images' in node_output:
            for image in node_output['images']:
                image_data = get_image(image['filename'], image['subfolder'], image['type'])
                if isinstance(image_data, bytes):
                    image_data = base64.b64encode(image_data).decode('utf-8')
                images_output.append(image_data)
        output_images[node_id] = images_output

    return output_images

def load_workflow(workflow_path):
    with open(workflow_path, 'r') as file:
        return json.load(file)

def handler(job):
    job_input = job.get("input", {})
    logger.info(f"Received job input: {job_input}")

    # Load single universal workflow
    workflow_file = "/workflow.json"
    logger.info(f"Loading workflow: {workflow_file}")
    prompt = load_workflow(workflow_file)

    # 1. Handle Input Image (Your workflow requires LoadImage node 117)
    # If API provides input_image, use it. Otherwise create a blank placeholder using width/height
    input_image_data = job_input.get("input_image")
    input_dir = "/ComfyUI/input"
    os.makedirs(input_dir, exist_ok=True)
    
    if input_image_data:
        save_data_if_base64(input_image_data, input_dir, "api_input.png")
        prompt["117"]["inputs"]["image"] = "api_input.png"
    else:
        # Fallback for old API requests (Creates a solid black image so workflow doesn't crash)
        w = job_input.get("width", 1024)
        h = job_input.get("height", 1024)
        blank_image = Image.new('RGB', (w, h), color='black')
        blank_image.save(os.path.join(input_dir, "api_input.png"))
        prompt["117"]["inputs"]["image"] = "api_input.png"

    # 2. Map standard settings to new Node IDs
    if "prompt" in job_input:
        prompt["75:74"]["inputs"]["text"] = job_input["prompt"]
    if "seed" in job_input:
        prompt["75:73"]["inputs"]["noise_seed"] = job_input["seed"]
    if "guidance" in job_input:
        prompt["75:63"]["inputs"]["cfg"] = job_input["guidance"]
    
    # 3. Model Override
    if "model" in job_input:
        prompt["101"]["inputs"]["unet_name"] = job_input["model"]
        logger.info(f"Model changed to: {job_input['model']}")
    
    # 4. LoRA Dynamic toggling using Power Lora Loader (Node 111)
    lora_list = job_input.get("lora", [])
    
    # First turn off all predefined LoRAs in the JSON
    for i in range(1, 15):
        lora_key = f"lora_{i}"
        if lora_key in prompt["111"]["inputs"]:
            prompt["111"]["inputs"][lora_key]["on"] = False
            
    # Then turn on the requested ones dynamically
    for i, (lora_name, weight) in enumerate(lora_list):
        slot = i + 1
        lora_key = f"lora_{slot}"
        if lora_key not in prompt["111"]["inputs"]:
            prompt["111"]["inputs"][lora_key] = {}
            
        prompt["111"]["inputs"][lora_key]["on"] = True
        prompt["111"]["inputs"][lora_key]["lora"] = lora_name
        prompt["111"]["inputs"][lora_key]["strength"] = weight
        logger.info(f"LoRA {slot} applied: {lora_name} with weight {weight}")

    # Connect and Execute
    ws_url = f"ws://{server_address}:8188/ws?clientId={client_id}"
    http_url = f"http://{server_address}:8188/"
    
    for http_attempt in range(180):
        try:
            urllib.request.urlopen(http_url, timeout=5)
            break
        except Exception:
            if http_attempt == 179:
                raise Exception("ComfyUI server unreachable.")
            time.sleep(1)
    
    ws = websocket.WebSocket()
    for attempt in range(36):
        try:
            ws.connect(ws_url)
            break
        except Exception:
            if attempt == 35:
                raise Exception("WebSocket connection timeout")
            time.sleep(5)
            
    images = get_images(ws, prompt)
    ws.close()

    if not images:
        return {"error": "Failed to generate image."}
    
    for node_id in images:
        if images[node_id]:
            return {"image": images[node_id][0]}
    
    return {"error": "Image not found."}

runpod.serverless.start({"handler": handler})
