# The website (web/), in a container for repeatable builds and local development.
#
#   docker compose up web                       dev server with live reload, http://localhost:5173
#   docker build -f docker/web.Dockerfile --target site --build-arg VITE_API_URL=https://... \
#     --output type=local,dest=web/build/client .
#                                               production build, exported as static files
#
# The site is static (S3 + CloudFront); the container builds it, it doesn't serve it.

FROM node:24.14-alpine AS deps
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM deps AS dev
# The source is bind-mounted from the host (see docker-compose.yml); file events from a
# Windows host don't reach the container, so Vite polls.
ENV VITE_POLL=1
EXPOSE 5173
CMD ["sh", "-c", "npm run data && npx react-router dev --host 0.0.0.0 --port 5173"]

FROM deps AS build
# build-data.mjs reads these two seeds (the hospital list and CMS's shoppable services).
COPY warehouse/seeds/hospitals.csv warehouse/seeds/shoppable_services.csv /app/warehouse/seeds/
COPY web/ ./
ARG VITE_API_URL
RUN test -n "$VITE_API_URL" || (echo "pass --build-arg VITE_API_URL=..." >&2; exit 1)
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build && npm test

FROM scratch AS site
COPY --from=build /app/web/build/client/ /
