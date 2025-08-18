FROM node:20-alpine AS build
WORKDIR /app
COPY package.json .
RUN npm install
COPY astro.config.mjs .
COPY src src
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
COPY --from=build /app/dist dist
RUN npm install -g serve
EXPOSE 3000
CMD ["serve", "-s", "dist", "-l", "3000"]
