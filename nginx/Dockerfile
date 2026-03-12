FROM nginx:alpine

# OpenSSL is used to generate a fallback self-signed certificate
# when real certificates are not provided yet.
RUN apk add --no-cache openssl

COPY nginx.conf /etc/nginx/nginx.conf
COPY docker-entrypoint.d/05-link-letsencrypt-certs.sh /docker-entrypoint.d/05-link-letsencrypt-certs.sh
COPY docker-entrypoint.d/10-generate-self-signed-cert.sh /docker-entrypoint.d/10-generate-self-signed-cert.sh
COPY docker-entrypoint.d/15-generate-htpasswd.sh /docker-entrypoint.d/15-generate-htpasswd.sh
COPY docker-entrypoint.d/20-generate-health-allowlist.sh /docker-entrypoint.d/20-generate-health-allowlist.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/05-link-letsencrypt-certs.sh && chmod +x /docker-entrypoint.d/05-link-letsencrypt-certs.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/10-generate-self-signed-cert.sh && chmod +x /docker-entrypoint.d/10-generate-self-signed-cert.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/15-generate-htpasswd.sh && chmod +x /docker-entrypoint.d/15-generate-htpasswd.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/20-generate-health-allowlist.sh && chmod +x /docker-entrypoint.d/20-generate-health-allowlist.sh

RUN mkdir -p /app/staticfiles /app/media /etc/nginx/certs /var/www/certbot

EXPOSE 80 443 8443
