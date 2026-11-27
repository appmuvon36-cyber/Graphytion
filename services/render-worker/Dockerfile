FROM node:22.14.0-bookworm-slim
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/remotion-studio ./apps/remotion-studio
COPY services/render-worker ./services/render-worker
RUN corepack enable \
    && pnpm install --filter @graphytion/render-worker... --filter @graphytion/remotion-studio... --frozen-lockfile \
    && pnpm --filter @graphytion/remotion-studio build \
    && pnpm --filter @graphytion/render-worker build
ENV REMOTION_SERVE_URL=/workspace/apps/remotion-studio/build
WORKDIR /workspace/services/render-worker
CMD ["pnpm","start"]
