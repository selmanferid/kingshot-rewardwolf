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
- `POST /api/codes/add` — Manuel kod ekleme veya tamamlanmış kodu sıfırlama.
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

## 3. Browser Otomasyonu (Playwright)

Redemption işlemi `kingshot_giftcode_daemon.py` içindeki `_attempt_redeem()` ve `redeem_code_for_player()` fonksiyonlarıyla yapılır.

- `launch_browser()` — Host Chromium binary'sini (`/usr/bin/chromium`) kullanarak dağıtım süresince tek bir browser instance başlatır.
- `create_context()` — Her oyuncu için ayrı bir `BrowserContext` oluşturur (farklı fingerprint, viewport, user-agent).
- `_attempt_redeem()` — `https://ks-giftcode.centurygame.com/` adresine gider, Player ID ve kodu girer, sonucu okur.
- `parse_message()` — Ekranda dönen string'i küçük harfe çevirerek `SUCCESS / ALREADY_USED / INVALID_CODE / SERVER_BUSY / UNKNOWN` durumlarına sınıflandırır.

Eğer gift code portalının arayüzü değişirse:
- Player ID input XPath: `//input[@placeholder="Player ID"]`
- Gift code input XPath: `//input[@placeholder="Gift Code"]`
- `parse_message()` içindeki anahtar kelimeler güncellenmeli.

## 4. Webhook / Rebuild Server

Web container'dan host Docker'a doğrudan erişim olmadığı için "Sunucuyu Yeniden Başlat" gibi istekler `rebuild_server.py` üzerinden geçer. Bu araç localhost'ta çalışır ve host bash yetkisine sahiptir. Yeni komut eklerken RCE (Remote Code Execution) riskine karşı dikkatli olunmalıdır.

## 5. Branch Stratejisi

- UI güncellemeleri için: `feat/ui`
- Bug düzeltmeleri için: `fix/x-bug`
- `main` branch'e doğrudan push atmaktan kaçının.
