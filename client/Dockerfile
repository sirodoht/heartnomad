FROM node:20

RUN mkdir -p /app/client
WORKDIR /app/client
COPY package.json package-lock.json /app/client/
RUN npm install

COPY . /app/client
RUN cd /app/client && node_modules/.bin/webpack --config webpack.prod.config.js
