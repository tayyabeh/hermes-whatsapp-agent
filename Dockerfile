FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HOME=/root
ENV HERMES_HOME=/root/.hermes
ENV PATH="/root/.local/bin:${PATH}"

RUN apt-get update && apt-get install -y \
    curl git ca-certificates tar xz-utils procps \
    python3 python3-venv python3-pip libatomic1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Hermes Agent (latest stable, lightweight server mode)
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --non-interactive --skip-browser --skip-computer-use

# Install and enable the official WhatsApp Third-Party Agent plugin
RUN hermes plugins install whatsapp-agent-platform --enable

# Configure WhatsApp Agent display settings & Gemini provider
RUN hermes config set display.platforms.whatsapp_agent_platform.tool_progress off && \
    hermes config set display.platforms.whatsapp_agent_platform.interim_assistant_messages false && \
    hermes config set stt.echo_transcripts false && \
    hermes config set model.provider gemini && \
    hermes config set model.default gemini-2.5-flash

# Create startup script that loads Railway variables into ~/.hermes/.env and starts the gateway
RUN printf '#!/usr/bin/env bash\n\
set -e\n\
mkdir -p /root/.hermes\n\
cat > /root/.hermes/.env <<EOF\n\
WHATSAPP_AGENT_PLATFORM_API_KEY=${WHATSAPP_AGENT_PLATFORM_API_KEY}\n\
GOOGLE_API_KEY=${GEMINI_API_KEY:-${GOOGLE_API_KEY}}\n\
GEMINI_API_KEY=${GEMINI_API_KEY:-${GOOGLE_API_KEY}}\n\
OPENROUTER_API_KEY=${OPENROUTER_API_KEY}\n\
EOF\n\
chmod 600 /root/.hermes/.env\n\
python3 -m http.server ${PORT:-8080} --bind 0.0.0.0 &\n\
exec hermes gateway\n' > /start.sh && chmod +x /start.sh

CMD ["/start.sh"]
