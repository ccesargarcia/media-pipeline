FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Instala dependências básicas (curl, certificados e OpenMP)
RUN apt-get update && apt-get install -y curl ca-certificates libgomp1 && \
    mkdir -p /llama-bin /models && \
    curl -sL https://github.com/ggerganov/llama.cpp/releases/download/b12032/llama-b12032-bin-ubuntu-x64.tar.gz | \
    tar -xzf - -C /llama-bin --strip-components=1 && \
    echo "==> Baixando modelo Qwen 2.5 7B GGUF..." && \
    curl -L -# "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf" \
    -o /models/qwen2.5-7b-instruct-q4_k_m.gguf && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV LD_LIBRARY_PATH=/llama-bin
ENV PORT=8080
ENV HOST=0.0.0.0

EXPOSE 8080

ENTRYPOINT ["/llama-bin/llama-server"]
CMD ["-m", "/models/qwen2.5-7b-instruct-q4_k_m.gguf", "-c", "4096", "-t", "8", "--host", "0.0.0.0", "--port", "8080", "--flash-attn", "on"]
