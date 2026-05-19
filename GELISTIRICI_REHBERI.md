# 🚀 Geliştirici Kılavuzu

Bu doküman projede geliştirme yapacak, yeni özellikler ekleyecek veya debug süreçleri işletecek yazılımcılar için hazırlanmıştır.

## 1. Lokalde Çalıştırma (Development Ortamı)

Proje hem Raspberry Pi (ARM64) üzerinde hem de Windows/Mac sistemlerde çalışabilmektedir. Lokal geliştirme için Docker Compose yerine doğrudan Python dosyaları üzerinden gitmek daha hızlıdır.

1. **Bağımlılıkların Kurulması**
   ```bash
   pip install -r requirements.txt
   pip install -r web/requirements.txt
   ```

2. **Playwright Chromium Kurulumu (Lokal)**
   Production'da host Chromium kullanılır; lokalde Playwright'ın kendi tarayıcısını kurabilirsiniz:
   ```bash
   playwright install chromium
   ```
   Ardından `launch_browser()` içindeki `executable_path` satırını geçici olarak kaldırın (Playwright kendi binary'sini kullansın).

3. **Headless Kapatma**
   `docker-compose.yml` veya doğrudan kodda `HEADLESS=false` yaparsanız tarayıcının ekranda nasıl çalıştığını izleyip hata ayıklayabilirsiniz. Üretim ortamında daima `true` olmalıdır.

## 2. API Tasarımı (Web Backend)

`web/main.py` içerisindeki tüm rotalar JWT tabanlı `/api/auth/login` tokeniyle korunmaktadır.

- `/api/dashboard` — Ana ekran istatistikleri.
- `/api/players` — Oyuncu işlemleri (CRUD); tüm oyuncu yönetimi buradan yapılır.
- `/api/logs` — Kuyruk (tail) tabanlı asenkron log takibi.
- `/api/settings` — Web üzerinden yapılandırmayı güncelleme.
- `/api/distribution/status` — Aktif kodlar, dağıtım ilerleme yüzdesi ve `paused` durumu. `{codes: [...], paused: bool}` döner.
- `POST /api/distribution/pause` — `daemon_control.dist_cmd = 'pause'` yazar.
- `POST /api/distribution/resume` — `dist_cmd = 'resume'`, `dist_paused = '0'` yazar.
- `POST /api/distribution/cancel` — `dist_cmd = 'cancel'` yazar.
- `POST /api/distribution/retry` — `dist_cmd = 'retry'` yazar; daemon RETRY_PENDING oyuncuları aktif dağıtıma enjekte eder.
- `POST /api/codes/add` — Manuel kod ekleme, tamamlanmış veya pasife alınmış kodu reaktive etme. Pasif koda tekrar girildiğinde `LIMIT_REACHED` kayıtları silinir ve dağıtım sıfırdan başlar.
- `GET /api/daemon/uptime` — Docker container StartedAt bilgisi.

Yeni bir endpoint eklerken:
```python
@app.get("/api/yeni-ozellik")
def yeni_endpoint(_=Depends(verify_token)):
    conn = db()
    # SQL sorguları ...
    return {"status": "ok"}
```
Her SQLite bağlantısını `try/finally` ile kapatmayı unutmayın.

## 3. Önemli Yardımcı Fonksiyonlar

- `deactivate_code(code, reason)` — `active_codes.is_currently_active=0` yazar; INVALID_CODE, expire ve LIMIT_REACHED x3 durumlarında çağrılır.
- `refresh_code_stats(code)` — `redemptions` tablosunu sorgulayarak `active_codes` istatistiklerini (success/already_used/failed/total) günceller. `results` listesi yerine DB'deki gerçek durumu yansıtır; retry tamamlandıktan sonra çağrılır.
- `_run_limit_retry(codes, players)` — LIMIT_REACHED retry'ını bağımsız bir thread'de çalıştırır. `_limit_retry_active` flag ile çift tetikleme önlenir; aktif bir normal dağıtım olsa da çalışır.

## 4. Browser Otomasyonu (Playwright)

Redemption işlemi `kingshot_giftcode_daemon.py` içindeki `_attempt_redeem()` ve `redeem_code_for_player()` fonksiyonlarıyla yapılır.

- `launch_browser()` — Host Chromium binary'sini (`/usr/bin/chromium`) kullanarak dağıtım süresince tek bir browser instance başlatır.
- `create_context()` — Her oyuncu için ayrı bir `BrowserContext` oluşturur (farklı fingerprint, viewport, user-agent).
- `_attempt_redeem()` — `https://ks-giftcode.centurygame.com/` adresine gider, Player ID ve kodu girer, sonucu okur.
- `parse_message()` — Ekranda dönen string'i küçük harfe çevirerek `SUCCESS / ALREADY_USED / INVALID_CODE / LIMIT_REACHED / SERVER_BUSY / UNKNOWN` durumlarına sınıflandırır.

Eğer gift code portalının arayüzü değişirse:
- Player ID input XPath: `//input[@placeholder="Player ID"]`
- Gift code input XPath: `//input[@placeholder="Gift Code"]`
- `parse_message()` içindeki anahtar kelimeler güncellenmeli.

## 5. Webhook / Rebuild Server

Web container'dan host Docker'a doğrudan erişim olmadığı için "Sunucuyu Yeniden Başlat" gibi istekler `rebuild_server.py` üzerinden geçer. Bu araç localhost'ta çalışır ve host bash yetkisine sahiptir. Yeni komut eklerken RCE (Remote Code Execution) riskine karşı dikkatli olunmalıdır.

## 6. Notification Channels

`send_to_channels(event, **kwargs)` ile tüm kanallar yönetilir. Yeni event eklemek için:

1. `DEFAULT_CHANNEL_TEMPLATES` sözlüğüne varsayılan şablonu ekle
2. `_build_discord_embed()` fonksiyonuna yeni `if event == "..."` bloğu ekle
3. `notification_channels` tablosuna `ev_<event>`, `tpl_<event>`, `mention_<event>` kolonlarını ekle (daemon ve web/main.py her ikisinde de)
4. Migration koduna ALTER TABLE satırlarını ekle
5. `ChannelCreate` / `ChannelUpdate` Pydantic modellerini güncelle
6. UI modal'ına event checkbox ve mention dropdown ekle

**Discord mention:** Her kanal için her event'e bağımsız mention tipi (`none` / `everyone` / `here`) atanabilir. `send_to_channels` bu değeri DB'den okur — hardcoded set yoktur.

**Önemli:** Daemon kodu ve `web/main.py` `COPY` ile image'a kopyalanır. Bu dosyalardan biri değiştiğinde sadece restart **yetmez** — her iki konteyneri da rebuild edip force-recreate yapın:
```bash
docker compose build && docker compose up -d --force-recreate
```

Yalnızca daemon değiştiyse:
```bash
docker compose build daemon && docker compose up -d --force-recreate daemon
```

## 7. Branch Stratejisi

- UI güncellemeleri için: `feat/ui`
- Bug düzeltmeleri için: `fix/x-bug`
- `main` branch'e doğrudan push atmaktan kaçının.
