# Stage 1: Build Angular app
FROM node:20 AS build
WORKDIR /app

COPY nedvision-web/package*.json ./
RUN npm install

COPY nedvision-web/ .
RUN npm run build --prod

# Stage 2: Serve with Nginx
FROM nginx:alpine
COPY --from=build /app/dist/nedvision-web /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
