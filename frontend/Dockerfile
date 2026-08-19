FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html app.js styles.css /usr/share/nginx/html/
COPY config.container.js /usr/share/nginx/html/config.js

RUN rm -f /etc/nginx/conf.d/default.conf \
    && chown -R nginx:nginx /var/cache/nginx /usr/share/nginx/html

USER nginx

EXPOSE 8080
