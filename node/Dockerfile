FROM python:3.11-slim

LABEL org.opencontainers.image.source=https://github.com/MaelllDev/sentinel-monitor
LABEL org.opencontainers.image.description="Sentinel Monitor — node: agente de métricas para VPS"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

# Instala dependências do sistema (para psutil compilar sensores)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código
COPY . .

CMD ["python", "agent.py"]
