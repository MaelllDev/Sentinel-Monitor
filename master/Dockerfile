FROM python:3.11-slim

LABEL org.opencontainers.image.source=https://github.com/MaelllDev/sentinel-monitor
LABEL org.opencontainers.image.description="Sentinel Monitor — master: bot do Telegram + servidor WebSocket"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

# Instala dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código
COPY . .

# Porta do servidor WebSocket
EXPOSE 8765

CMD ["python", "bot.py"]
