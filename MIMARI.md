# 🏗️ KingShot Rewardwolf Mimari Dokümantasyonu

Bu doküman, projeyi oluşturan tüm bileşenleri, veri akışını ve sistemin genel çalışma mantığını açıklamaktadır.

## 1. Genel Bakış

Sistem, "KingShot" isimli mobil oyun için yayınlanan hediye kodlarını (gift codes) otomatik olarak yakalayıp, tüm oyunculara dağıtan (otomatik olarak "redeem" eden) bir bot sistemidir. Browser otomasyonu için Playwright kullanır ve Raspberry Pi gibi düşük kaynaklı sistemlerde uzun süre çalışabilmesi için özel olarak optimize edilmiştir. Oyuncu listesi Google Sheets'ten değil, doğrudan Dashboard üzerinden yönetilir.

## 2. Temel Bileşenler

### A. Core Daemon (`kingshot_giftcode_daemon.py`)

Sistemin kalbidir. Python ile yazılmıştır ve çoklu thread (iş parçacığı) yapısıyla çalışır:

- **Telegram Bot Thread:** Kullanıcılardan gelen komutları (`/status`, `/health`, vs.) dinler ve anında cevap verir.
- **Main Loop (Ana Döngü):** Belirli aralıklarla (örn: 5 dakika) şunları yapar:
  1. KingShot API'sinden güncel kodları çeker.
  2. Yeni bir kod varsa, tüm aktif oyuncular için Playwright aracılığıyla tek tek gönderim yapar (ban yememek için gönderimler arasına rastgele gecikmeler ekler, farklı User-Agent kullanır).
- **Health Monitoring:** CPU, RAM ve Raspberry Pi sıcaklık durumlarını takip eder. Limitlerin aşılması durumunda Telegram üzerinden uyarı mesajı yayınlar.
- **Recovery & Retry:** Eğer tarayıcı patlarsa (zombie process), süreçler temizlenir ve kaldığı oyuncudan tekrar denenir. Başarısız gönderimler (~2 saat sonra) tekrar denenir.

### B. Web Arayüzü (`web/main.py`)

Bağımsız bir container olarak çalışan dashboard sistemidir.

- **FastAPI:** Hızlı ve asenkron çalışan Python backend'idir.
- **SQLite Mapping:** Daemon tarafından kullanılan SQLite veritabanı dosyasını paylaşımlı olarak (`/app/data`) okur ve web arayüzüne JSON formatında sunar.
- **Auth (JWT):** Yalnızca yetkili `ADMIN_USER` ve `ADMIN_PASS` ile giriş izni verir.
- **Oyuncu Yönetimi:** Tüm oyuncu ekleme/çıkarma/VIP işlemleri Dashboard üzerinden yapılır.

### C. Host & Rebuild Server (`rebuild_server.py`)

Docker container içinden doğrudan Docker komutları çalıştırmak güvenlik zafiyeti yaratabileceği için, host üzerinde çalışan basit bir araçtır. Telegram bot veya Dashboard üzerinden gelen `rebuild` ya da `zombie process kill` gibi istekleri HTTP formatında karşılayarak host bash komutlarını çalıştırır.

### D. SQLite Veritabanı (`data/kingshot.db`)

Yoğun okuma/yazma işlemi için SQLite WAL (Write-Ahead Logging) modunda çalışır.

- `players`: Oyuncuların listesi, kayıt tarihi, soft-delete (`removed_at`) ve VIP statüleri.
- `redemptions`: Hangi koda, hangi oyuncuya ne zaman gönderim yapıldığının ve sonucun (SUCCESS, ALREADY_USED, FAILED vb.) kaydı.
- `active_codes`: Sisteme düşmüş kodlar, bitiş süreleri, gönderim istatistikleri ve `notified` bayrağı.
- `expiry_warnings`: Bitmek üzere olan kodlar için atılmış uyarı mesajlarının kaydı.
- `notification_channels`: Telegram grupları ve Discord webhook'larının tanımları, event toggle'ları ve özel şablonları.
- `api_keys`: Dışa açık API endpoint'leri için erişim anahtarları.

## 3. Redemption Durum Modeli

Her oyuncu-kod çifti için aşağıdaki durumlardan biri kaydedilir:

| Durum | Anlamı | Delivered sayılır mı? |
|-------|--------|----------------------|
| `SUCCESS` | Kod başarıyla işlendi | ✅ Evet |
| `ALREADY_USED` | Oyuncu kodu zaten almış | ✅ Evet |
| `FAILED` | Geçici hata — yeniden denenecek | ❌ Hayır |
| `INVALID_CODE` | Kod geçersiz veya süresi dolmuş | ❌ Hayır |
| `SERVER_BUSY` | Sunucu yanıt vermedi | ❌ Hayır |

`ALREADY_USED`, oyuncunun ödülü başka kanaldan aldığını teyit eder — bu durum "teslim edildi" olarak sayılır.

## 4. Akış Diyagramı

1. **Kod Kontrolü:** `Daemon` → `KingShot API` → Yeni kod bulunursa `active_codes` tablosuna eklenir. `notified=0` ise Telegram + notification channels'a bildirim gönderilir ve `notified=1` set edilir (spam önleme).
2. **Redeem Süreci:** `Daemon` → `Playwright (host Chromium)` → `https://ks-giftcode.centurygame.com/` → Yanıt parse edilir → Veritabanına kaydedilir.
3. **Retry:** `FAILED` statüsündeki kayıtlar, `RETRY_DELAY_HOURS` (varsayılan 2 saat) sonra tekrar denenir.
4. **Bildirim:** Dağıtım tamamlanınca, kod sona ermeden 72 saat önce ve her gece `send_to_channels()` ile tüm aktif kanallara ilgili event mesajı gönderilir.
5. **İzleme:** `Web Dashboard` veya `Telegram Bot` → O anki ilerleme ve istatistikler veritabanından okunur.

## 5. Özel Optimizasyonlar

- **Browser Fingerprint Rastgeleleştirme:** Her oyuncu için farklı viewport, user-agent ve dil başlığı seçilir. `navigator.webdriver` gizlenir.
- **Host Chromium Mapping:** Playwright'ın kendi tarayıcısını indirmek yerine host (Raspberry Pi) üzerindeki Chromium binary'si Docker volume ile read-only olarak map edilir. Bu sayede Docker imaj boyutu küçük tutulur ve ARM64 uyumluluğu sağlanır.
- **Tek Browser Instance:** Browser dağıtım süreci boyunca tek kez açılır; her oyuncu için yalnızca hafif bir `BrowserContext` oluşturulur (RAM optimizasyonu).
- **Resource Blocking:** Gereksiz network kaynakları (image, media, font) Playwright route kurallarıyla engellenir. Stylesheet engellenmez — Vue SPA input alanlarını CSS ile yönetir.
- **Notification Channels:** `send_to_channels(event, **kwargs)` fonksiyonu tüm aktif kanalları tek sorguda çeker, Telegram veya Discord'a platform'a göre gönderim yapar. Her kanalın şablonu özelleştirilebilir; boşsa varsayılan şablon kullanılır.
