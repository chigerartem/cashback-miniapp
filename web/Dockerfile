FROM node:22-alpine AS builder
WORKDIR /app

# Build-time config baked into the bundle by Vite.
ARG VITE_API_BASE
ARG VITE_BOT_USERNAME
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_BOT_USERNAME=$VITE_BOT_USERNAME

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# Processed by the nginx image entrypoint (envsubst) → /etc/nginx/conf.d/default.conf.
# ${API_ORIGIN} is injected at container start so the CSP allows the API.
COPY default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
