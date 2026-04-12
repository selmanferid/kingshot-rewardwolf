# 🛠️ Kurulum ve Bakım Rehberi

Bu belge, WLF Rewardwolf'un Raspberry Pi 4 (veya diğer Linux cihazlar) üzerindeki kurulum aşamalarını, ortam değişkenlerini ve temel hata ayıklama işlemlerini açıklar.

## 1. Sistem Gereksinimleri

- Raspberry Pi 4 (min. 4GB RAM önerilir)
- DietPi veya Raspberry Pi OS (Debian tabanlı, güncel)
- Docker & Docker Compose
- Chromium Browser — host makinede kurulu olmalı:
  ```bash
  sudo apt install chromium-browser
  ```

## 2. Ortam Değişkenleri (.env Konfigürasyonu)

Projenin kök dizinine `.env` dosyası oluşturun:

```ini
KINGSHOT_API=https://kingshot.net/api
TELEGRAM_TOKEN=123456:ABC-DEF1234...
TELEGRAM_CHAT_ID=-100123...
CHECK_INTERVAL_MIN=5

# Dashboard JWT ve Admin Güvenliği
JWT_SECRET=cok-gizli-bir-sifre-girin
ADMIN_USER=kingshotadmin
ADMIN_PASS=kingshotpanel123
```

> `SHEETS_WEB_APP_URL` artık kullanılmıyor. Oyuncular Dashboard üzerinden yönetilir.

## 3. Üretime Alma

### Rebuild Server'ı Başlatma

Güvenlik nedeniyle Docker içinden host'a müdahaleye izin verilmediğinden `rebuild_server.py` kullanılır:

```bash
nohup python3 rebuild_server.py > /dev/null 2>&1 &
```

Her Pi yeniden başlatıldığında otomatik çalıştırmak için crontab'a ekleyin:

```bash
(crontab -l 2>/dev/null; echo "@reboot python3 /home/YOUR_USER/kingshot/rebuild_server.py > /dev/null 2>&1 &") | crontab -
```

### Docker ile Başlatma

```bash
docker compose up -d --build
```

Canlı log takibi:
```bash
docker compose logs -f daemon
```

## 4. Olası Hatalar ve Çözümleri

### Zombie Chromium Süreçleri

Düşük bellekli cihazlarda Chromium askıda kalabilir. RAM kullanımının sürekli arttığını görürseniz Telegram'dan `/restart` gönderin. `rebuild_server.py` arka planda şu komutu çalıştırır:

```bash
pkill -f chromium
```

### Playwright Chromium Bulunamıyor

`/usr/bin/chromium` yolunun docker-compose.yml'de volume olarak doğru map edildiğinden emin olun:

```yaml
volumes:
  - /usr/bin/chromium:/usr/bin/chromium:ro
  - /usr/lib/chromium:/usr/lib/chromium:ro
  - /usr/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu:ro
```

### Log Şişmeleri

Sistem `data/kingshot_daemon.log` dosyasına detaylı kayıt atar. Uzun süre çalışırsa boyut GB seviyelerine ulaşabilir. `logrotate` ile haftalık temizleme yapılandırmanız SD kart ömrünü korur:

```
/home/YOUR_USER/kingshot/data/kingshot_daemon.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```
