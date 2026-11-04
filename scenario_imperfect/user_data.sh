#!/bin/bash
set -ex

# Update & install dependensi runtime PHP 8.3 & Nginx
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y git curl unzip nginx php8.3-fpm php8.3-mysql php8.3-mbstring php8.3-xml php8.3-bcmath php8.3-curl php8.3-zip

# Install Composer & Node.js/NPM (untuk build Vite asset)
export HOME=/root
export COMPOSER_HOME=/root/.composer
curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# Clone repositori resmi
APP_DIR="/var/www/techfest"
mkdir -p /var/www
git clone https://github.com/novraepe/techfest-11-v1.git $APP_DIR

cd $APP_DIR

# Setup file .env production
cat <<EOF > .env
APP_NAME="Techfest Participant Management"
APP_ENV=production
APP_KEY=
APP_DEBUG=false
APP_URL=http://${alb_dns}

LOG_CHANNEL=stack
LOG_LEVEL=info

DB_CONNECTION=mysql
DB_HOST=${db_host}
DB_PORT=3306
DB_DATABASE=techfest_database_salah
DB_USERNAME=tf11_app
DB_PASSWORD=${db_password}

SESSION_DRIVER=database
SESSION_LIFETIME=120
CACHE_STORE=database
QUEUE_CONNECTION=sync

FILESYSTEM_DISK=s3
AWS_DEFAULT_REGION=${region}
AWS_BUCKET=${s3_bucket}
AWS_USE_PATH_STYLE_ENDPOINT=false
EOF

# Install dependensi Laravel & generate key
composer install --no-dev --optimize-autoloader --no-interaction
php artisan key:generate --force

# Build frontend assets (Vite)
npm install --ignore-scripts
npm run build

# Set file permissions
chown -R www-data:www-data $APP_DIR
chmod -R 775 $APP_DIR/storage $APP_DIR/bootstrap/cache

# Tunggu RDS siap lalu jalankan migrasi
until php artisan migrate --force; do
  echo "Menunggu koneksi database RDS..."
  sleep 5
done

# Konfigurasi VirtualHost Nginx
cat <<'EOF' > /etc/nginx/sites-available/default
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    root /var/www/techfest/public;
    index index.php index.html;

    server_name _;

    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php8.3-fpm.sock;
    }

    location ~ /\.ht {
        deny all;
    }
}
EOF

systemctl restart php8.3-fpm
systemctl restart nginx
