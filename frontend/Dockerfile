# ── Build stage ──────────────────────────────────────────────
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ── Serve stage ──────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Template (not a static conf): the nginx entrypoint runs envsubst on
# /etc/nginx/templates/*.template at startup, injecting CORPUS_API_KEY.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
