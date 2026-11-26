FROM node:22.14.0-bookworm-slim
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends chromium ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
COPY package.json pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY services/render-worker ./services/render-worker
RUN corepack enable && pnpm install --filter @graphytion/render-worker... --no-frozen-lockfile
WORKDIR /workspace/services/render-worker
CMD ["pnpm","start"]
