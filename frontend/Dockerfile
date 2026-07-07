# Multi-stage build: compile TS+React with Node, serve static files with
# nginx (and proxy /api/* to the FastAPI container).

FROM node:20-alpine AS build
WORKDIR /app

# Build-time secrets/config that Vite must inline into the bundle. Pass via
# `docker compose build --build-arg VITE_SENTRY_DSN=...` or compose `args:`.
# Unset = Sentry disabled in the built bundle.
ARG VITE_SENTRY_DSN=""
ARG VITE_SENTRY_ENVIRONMENT="production"
ARG VITE_SENTRY_RELEASE=""
# VITE_BASE is the URL prefix all asset URLs get baked with — set to e.g.
# /conv-agent/ when serving under a path on a parent domain. Defaults to /.
ARG VITE_BASE="/"
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN \
    VITE_SENTRY_ENVIRONMENT=$VITE_SENTRY_ENVIRONMENT \
    VITE_SENTRY_RELEASE=$VITE_SENTRY_RELEASE \
    VITE_BASE=$VITE_BASE

COPY package.json package-lock.json* ./
# `npm ci` if a lockfile is present, otherwise `npm install` for first build.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
