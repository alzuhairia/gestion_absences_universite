# ============================================
# Dockerfile pour Nginx
# ============================================
# IMPORTANT POUR LA SOUTENANCE :
# Nginx sert de reverse proxy devant Gunicorn
# Il gère :
# - Les requêtes HTTP/HTTPS
# - Les fichiers statiques (CSS, JS, images)
# - Les fichiers média (documents uploadés)
# - La compression et le cache

FROM nginx:alpine

# Copier la configuration Nginx personnalisée
COPY nginx.conf /etc/nginx/nginx.conf

# Créer les répertoires pour les fichiers statiques et média
RUN mkdir -p /app/staticfiles /app/media

# Exposer les ports HTTP et HTTPS
EXPOSE 80 443

# Nginx démarre automatiquement (commande par défaut de l'image)
