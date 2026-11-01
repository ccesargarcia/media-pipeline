FROM ghcr.io/ggerganov/llama.cpp:server

# Instala curl e baixa o modelo Qwen 2.5 7B Instruct (Q4_K_M)
RUN apt-get update && apt-get install -y curl && \
    mkdir -p /models && \
    curl -L -# "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf" \
    -o /models/qwen2.5-7b-instruct-q4_k_m.gguf && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PORT=8080
ENV HOST=0.0.0.0

ENTRYPOINT ["/llama-server"]
CMD ["-m", "/models/qwen2.5-7b-instruct-q4_k_m.gguf", "-c", "4096", "-t", "8", "--host", "0.0.0.0", "--port", "8080", "--flash-attn", "on"]
