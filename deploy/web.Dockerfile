# The hosted `rakin-web` image: the SPA, built, served by Caddy with
# deploy/Caddyfile, which also proxies /api and /healthz to the api, and the
# landing page under /srv/site.
# Built from the repo root: docker build -f deploy/web.Dockerfile .
FROM node:24.22.2-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# rakin.app, the landing page (#343), with the app's fonts from the stage above.
FROM python:3.13-alpine AS site
RUN pip install --no-cache-dir markdown==3.9
WORKDIR /repo
COPY site/ site/
COPY docs/brand/lockup-dark.svg docs/brand/
COPY docs/legal/aviso-de-privacidad-rakin.md docs/legal/
COPY frontend/public/ frontend/public/
COPY --from=build /app/node_modules/@fontsource /fontsource
RUN python site/build.py --fonts /fontsource --out /site

FROM caddy:2
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
COPY --from=site /site /srv/site
