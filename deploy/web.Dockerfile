# The hosted `rakin-web` image: the SPA, built, served by Caddy with
# deploy/Caddyfile, which also proxies /api and /healthz to the api.
# Built from the repo root: docker build -f deploy/web.Dockerfile .
FROM node:24.22.2-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM caddy:2
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
