# Builds the static frontend, then copies it into the shared volume Caddy serves from.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM busybox:1.36
COPY --from=build /src/dist /dist
CMD ["sh", "-c", "rm -rf /out/* && cp -r /dist/. /out/"]
