FROM node:20-alpine AS build
WORKDIR /app
COPY package.json .
RUN npm install
COPY astro.config.mjs .
COPY tailwind.config.mjs .
COPY src src
RUN npm run build

# Development stage with full deps and source for hot reload
FROM node:20-alpine AS dev
WORKDIR /app
COPY package.json .
RUN npm install
COPY astro.config.mjs .
COPY tailwind.config.mjs .
COPY src src
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

FROM node:20-alpine AS runner
WORKDIR /app
COPY --from=build /app/dist dist
RUN npm install -g serve
EXPOSE 3000
CMD ["serve", "-s", "dist", "-l", "3000"]
