import runpod
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.parse
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1')
client_id = str(uuid.uuid4())

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

    workflow_file = "/workflow.json"
    prompt = load_workflow(workflow_file)

    # 1. Map standard settings to the specific Nodes
    if "prompt" in job_input:
        prompt["6"]["inputs"]["text"] = job_input["prompt"]
    if "seed" in job_input:
        prompt["49"]["inputs"]["seed"] = job_input["seed"]
    if "guidance" in job_input:
        prompt["51"]["inputs"]["guidance"] = job_input["guidance"]
    if "width" in job_input:
        prompt["56"]["inputs"]["width"] = job_input["width"]
    if "height" in job_input:
        prompt["56"]["inputs"]["height"] = job_input["height"]
    
    # 2. Model Override
    if "model" in job_input:
        prompt["38"]["inputs"]["unet_name"] = job_input["model"]
        logger.info(f"Model changed to: {job_input['model']}")
    
    # 3. LoRA Dynamic toggling (Nodes 53, 54, and 57 are chained in this workflow)
    lora_list = job_input.get("lora", [])
    lora_nodes = ["53", "54", "57"]
    
    # First, reset all 3 LoRAs in the chain to 0.0 strength so they do nothing by default
    for node_id in lora_nodes:
        prompt[node_id]["inputs"]["strength_model"] = 0.0
        
    # Then apply the requested LoRAs (up to 3)
    for i, (lora_name, weight) in enumerate(lora_list):
        if i < len(lora_nodes):
            node_id = lora_nodes[i]
            prompt[node_id]["inputs"]["lora_name"] = lora_name
            prompt[node_id]["inputs"]["strength_model"] = weight
            logger.info(f"LoRA {i+1} applied: {lora_name} with weight {weight}")

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
    
    # Return output from SaveImage Node (Node 9)
    for node_id in images:
        if images[node_id]:
            return {"image": images[node_id][0]}
    
    return {"error": "Image not found."}

runpod.serverless.start({"handler": handler})
