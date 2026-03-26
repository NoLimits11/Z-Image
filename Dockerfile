# Use specific version of nvidia cuda image
FROM wlsdml1114/multitalk-base:1.4 as runtime

RUN apt-get update && apt-get install -y wget && rm -rf /var/lib/apt/lists/*

RUN pip install -U "huggingface_hub[hf_transfer]"
RUN pip install runpod websocket-client gguf

WORKDIR /

RUN git clone https://github.com/comfyanonymous/ComfyUI.git && \
    cd /ComfyUI && \
    pip install -r requirements.txt

# Install ComfyUI-Manager
RUN cd /ComfyUI/custom_nodes && \
    git clone https://github.com/Comfy-Org/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && \
    pip install -r requirements.txt

# Install ComfyUI-GGUF (Required for Node 55: CLIPLoaderGGUF)
RUN cd /ComfyUI/custom_nodes && \
    git clone https://github.com/city96/ComfyUI-GGUF.git && \
    cd ComfyUI-GGUF && \
    pip install -r requirements.txt || true

# Download your required models into the proper folders
RUN wget "https://civitai.com/api/download/models/2617751?token=d829c3792b5143809703a8d9bad0e8ec" -O /ComfyUI/models/loras/SnapS.safetensors
RUN wget "https://civitai.com/api/download/models/2473179?token=d829c3792b5143809703a8d9bad0e8ec" -O /ComfyUI/models/loras/b4ddie.safetensors
RUN wget "https://civitai.com/api/download/models/2733536?token=d829c3792b5143809703a8d9bad0e8ec" -O /ComfyUI/models/loras/Airport.safetensors
RUN wget "https://huggingface.co/lodestones/Chroma/resolve/main/vae/diffusion_pytorch_model.safetensors" -O /ComfyUI/models/vae/ae.safetensors
RUN wget "https://civitai.com/api/download/models/2445746?token=d829c3792b5143809703a8d9bad0e8ec" -O /ComfyUI/models/diffusion_models/fp8_e4m3fnZIMAGE.safetensors
RUN wget "https://huggingface.co/Mungert/Qwen3-4B-abliterated-GGUF/resolve/main/Qwen3-4B-abliterated-iq4_nl.gguf" -O /ComfyUI/models/clip/Qwen3-4B-abliterated-iq4_nl.gguf

COPY . .
COPY extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
