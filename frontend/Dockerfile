FROM nginx:1.27-alpine

COPY frontend/ /usr/share/nginx/html/
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=4s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
