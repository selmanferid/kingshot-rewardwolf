# WolfPack Design System

Bu doküman, **app.ks-wolfpack.com** üzerinde kullanılan tasarım dilini referans alır ve **gift.ks-wolfpack.com**'un buna göre revize edilmesi için tüm token, bileşen ve örüntü kurallarını tanımlar.

Mevcut gift paneli; `Inter` (body) + `Space Grotesk` (logo) font, sarı (`#F0A500`) vurgu, koyu mavi-gri (`#0C0E13` body, `#191B21` sidebar) yüzeyler, sol dikey navigation ve uppercase etiketler üzerine kurulu bir "admin command center" estetiğine sahip. Hedef sistem ise koyu, "ateş & kurt" temalı, **kırmızı/ember** vurgulu, **Rajdhani + Exo 2** tipografisine sahip aynı dilden askeri/gaming bir dashboard estetiğine dayanıyor.

**Önemli prensip**: Gift panelin mevcut yapısı (sol sidebar, sayfa düzeni, sayfa adlandırması, monospace estetik, uppercase etiketler, status indicator) korunacak; renkler, font'lar ve gradient'ler app.ks-wolfpack.com'a hizalanacak. Yani **mimari değil, dil değişiyor**.

---

## 1. Marka & Ton

- **Karakter**: Karanlık, sert, askeri/oyun (Whiteout Survival ittifak yönetimi). "Wolf", "Alliance", "Command Center", "Ember/Fire" gibi kavramlar.
- **Kontrast**: Çok koyu zemin üzerinde kırmızı vurgu. Beyaz ve gri tonlar metin için.
- **Hissiyat**: Net, fonksiyonel, "panel-vari". Süs yok; her bileşen veri taşır.

---

## 2. Renk Paleti (Token'lar)

Tüm renkler HSL bileşenleri olarak tanımlanır ve `hsl(var(--token))` ile tüketilir.

### 2.1 Temel
| Token | HSL | Hex Yaklaşık | Kullanım |
|---|---|---|---|
| `--background` | `0 0% 5%` | `#0D0D0D` | Sayfa zemini |
| `--foreground` | `0 0% 93%` | `#EDEDED` | Birincil metin |
| `--card` | `0 0% 8%` | `#141414` | Kart zemini |
| `--card-foreground` | `0 0% 93%` | `#EDEDED` | Kart metni |
| `--popover` | `0 0% 10%` | `#1A1A1A` | Dropdown, dialog |
| `--secondary` | `0 0% 12%` | `#1F1F1F` | İkincil yüzeyler, tab bar |
| `--muted` | `0 0% 14%` | `#242424` | Pasif yüzeyler |
| `--muted-foreground` | `0 0% 55%` | `#8C8C8C` | Pasif/yardımcı metin |
| `--border` | `0 0% 16%` | `#292929` | Sınırlar |
| `--input` | `0 0% 16%` | `#292929` | Input zemini/sınırı |

### 2.2 Vurgu
| Token | HSL | Hex Yaklaşık | Kullanım |
|---|---|---|---|
| `--primary` | `0 85% 50%` | `#EC1313` | CTA, marka kırmızısı, ikonlar |
| `--primary-foreground` | `0 0% 100%` | `#FFFFFF` | Primary üstünde metin |
| `--accent` | `0 70% 45%` | `#C32424` | Hover, koyu kırmızı vurgu |
| `--accent-foreground` | `0 0% 100%` | `#FFFFFF` | Accent üstünde metin |
| `--destructive` | `0 84% 60%` | `#EE3838` | Silme, hata |
| `--ring` | `0 85% 50%` | `#EC1313` | Focus ring |

### 2.3 Markaya Özel (Wolf & Ember)
| Token | HSL | Hex Yaklaşık | Kullanım |
|---|---|---|---|
| `--ember` | `15 90% 55%` | `#F25F22` | İkincil ateş vurgusu, gradient durağı |
| `--ember-glow` | `0 100% 40%` | `#CC0000` | Glow stop, parlak vurgu |
| `--wolf-gray` | `0 0% 70%` | `#B3B3B3` | Marka grisi (avatar/logo dolgu) |
| `--wolf-dark` | `0 0% 3%` | `#080808` | En koyu yüzey, footer/sidebar arka planı |

### 2.4 Sidebar (Ayrı Set)
| Token | HSL | Kullanım |
|---|---|---|
| `--sidebar-background` | `0 0% 6%` | Sol kenar / üst nav zemini |
| `--sidebar-foreground` | `0 0% 85%` | Nav metni |
| `--sidebar-primary` | `0 85% 50%` | Aktif nav vurgusu |
| `--sidebar-accent` | `0 0% 12%` | Hover zemini |
| `--sidebar-border` | `0 0% 14%` | Nav ayırıcı |
| `--sidebar-ring` | `0 85% 50%` | Nav focus |

### 2.5 Kategori/Etkinlik Renkleri
Etkinlik etiket badge'larında kullanılır (`gift` panelinde paket türlerine eşlenebilir):
- **Alliance Championship** → turuncu/sarı (`hsl(38 92% 60%)` civarı)
- **Vikings** → yeşil (`hsl(142 72% 45%)`)
- **KVK / Arena / Tri-Alliance** → mor-mavi (`hsl(244 75% 65%)`)
- **Bear Trap** → primary kırmızı (`hsl(0 85% 50%)`)
- **Sanctuaries & Fortress** → sarı (`hsl(50 95% 55%)`)

### 2.6 Gradient'ler
```css
--gradient-fire: linear-gradient(135deg, hsl(0 85% 50%), hsl(15 90% 55%), hsl(0 100% 40%));
--gradient-dark: linear-gradient(180deg, hsl(0 0% 8%), hsl(0 0% 3%));
--gradient-card: linear-gradient(145deg, hsl(0 0% 10%), hsl(0 0% 6%));
```
- `--gradient-fire`: Hero başlık, logo halo, "premium" CTA arka planı. Çok sık kullanma — vurgu için.
- `--gradient-card`: Kart arka planı için "sığ" varyant; standart `--card` yerine seçilebilir.
- `--gradient-dark`: Sayfa veya hero arka planı.

### 2.7 Shadow & Glow
```css
--shadow-fire: 0 0 30px -5px hsl(0 85% 50% / .4);
--shadow-ember: 0 0 60px -10px hsl(0 85% 50% / .2);
--glow-red: 0 0 20px hsl(0 85% 50% / .3);
```
- Kartlarda gölge **yok** (border yeterli).
- Glow yalnızca: aktif CTA hover, "ateşli" hero, login kartı kenarı için.

---

## 3. Tipografi

### 3.1 Aileler
- **Heading**: `"Rajdhani", sans-serif` — geniş, kondanse, askeri/teknik karakter. (`--font-heading`)
- **Body**: `"Exo 2", sans-serif` — modern, geometric humanist. (`--font-body`)
- **Mevcut gift sitesi `Inter` kullanıyor → bunu Exo 2 ile değiştir.**
- Fallback: `ui-sans-serif, system-ui, sans-serif`.

CSS import:
```html
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Exo+2:wght@400;500;600;700&display=swap" rel="stylesheet">
```

### 3.2 Ölçek (Dashboard'dan ölçüldü)
| Rol | Boyut | Ağırlık | Aile |
|---|---|---|---|
| Page H1 (`Profil Ayarları`, `Etkinlikler`) | 24px | 700 | Rajdhani |
| Card Title (H2) | ~18–20px | 600–700 | Rajdhani |
| Section Sub (H3) | 16px | 400 | Rajdhani |
| Body | 14–16px | 400 | Exo 2 |
| Small / Meta | 12–13px | 400–500 | Exo 2, `text-muted-foreground` |
| Button | 14px | 500–600 | Exo 2 |
| Stat Number (KPI) | 28–32px | 700 | Rajdhani |
| Mono / ID | 13–14px | 400 | system mono fallback (örn. `Player ID: 42147388`) |

### 3.3 Davranış
- Heading'lerde `letter-spacing: normal` veya hafif `0.01em`. **All-caps** sadece küçük etiketlerde / nav öğelerinde (`COMMAND CENTER • SECURE ACCESS` stilinde).
- Vurgu kelimesi heading içinde `--primary` renkle (örn. "Tekrar hoş geldin, **Papa Smurf**" — Papa Smurf kırmızı).
- Body satır yüksekliği: 1.5.

---

## 4. Layout & Spacing

- **Sayfa genişliği**: maksimum ~`max-w-7xl` (1280px) içeriden ortalanır.
- **Üst navigation**: yatay, tek sıra, ~64px yüksek; `--sidebar-background` (`#0F0F0F`) zeminli, alt `1px solid --border`.
- **İçerik padding**: dikey ~32px (`py-8`), yatay ~24–32px.
- **Spacing skalası** (Tailwind ile uyumlu): `4 / 8 / 12 / 16 / 20 / 24 / 32 / 48` px.
- **Grid**:
  - KPI satırı: 5 sütun (lg), 2 (sm), 1 (xs).
  - 2 sütunlu yan yana kart bloku: `lg:grid-cols-2`.
- **Radius**: `--radius: .5rem` (8px). Kartlar **12px** (`rounded-xl`), butonlar **6px** (`rounded-md`), badge **9999px** (pill).

---

## 5. Bileşenler

### 5.1 Card
```
background: transparent (veya var(--card) #141414)
border: 1px solid hsl(var(--border))  /* #292929 */
border-radius: 12px
padding: 20px
box-shadow: none
```
- Başlık ikonla başlar: `<icon className="text-primary" /> Title` — ikon **her zaman primary kırmızı**.
- Kart başlık ile içerik arasında ~12–16px boşluk.

### 5.2 Button — Variants

**Primary (Solid Red)**
```
background: hsl(var(--primary))     /* #EC1313 */
color: #FFFFFF
font-weight: 600
padding: 8px 16px (sm) / 10px 20px (md)
border-radius: 6px
hover: background hsl(var(--accent))  /* #C32424 */
focus: outline 2px hsl(var(--ring))
disabled: opacity .5
```
Örnek: Etkinlikler'deki "Yaklaşan", Profil'deki "Kaydet", "Şifre Değiştir".

**Secondary / Outline**
```
background: transparent
border: 1px solid hsl(var(--border))
color: hsl(var(--foreground))
hover: background hsl(var(--secondary))
```
Örnek: Etkinlikler'deki "Calendar".

**Ghost / Nav**
```
background: transparent
color: hsl(var(--muted-foreground))
hover: background hsl(var(--secondary)) / color hsl(var(--foreground))
```

**Active Nav (özel hal)**
```
background: hsl(var(--primary) / 0.10)
color: hsl(var(--primary))
border-radius: 6px
```
Aktif nav öğesi `bg-primary/10 text-primary` — bu kombinasyonu **tab-bar**'ın aktif tabında da kullan.

**Destructive**
```
background: hsl(var(--destructive))
color: #FFFFFF
```

### 5.3 Input / Form
```
background: hsl(var(--input))    /* #292929 */
border: 1px solid hsl(var(--input))
border-radius: 6px
padding: 10px 12px
color: hsl(var(--foreground))
placeholder: hsl(var(--muted-foreground))  /* #8C8C8C */
focus: border-color hsl(var(--ring)), ring 2px hsl(var(--ring) / .4)
```
- Label üstte, `text-sm font-medium`, alt 4–6px boşluk.
- Input grupları arasında 16–20px dikey boşluk.

### 5.4 Tabs
- Tab bar: `background: hsl(var(--secondary))` (#1F1F1F), padding 4px, radius 8px.
- Tab item: padding 8px 16px, radius 6px.
- Aktif tab: `background: hsl(var(--background))` veya `hsl(var(--card))` + `color: --foreground`, gölgesiz.
- Pasif tab: `color: hsl(var(--muted-foreground))`, hover'da `--foreground`.

### 5.5 Badge (Pill)
```
border-radius: 9999px
padding: 2px 10px
font-size: 11–12px
font-weight: 500
```
Varyantlar:
- **Rank/Role** (R3, R4, R5): `background: hsl(0 85% 50% / .15); color: hsl(0 85% 65%); border: 1px solid hsl(var(--primary) / .3)`.
- **Category dot**: Renkli daire (•) + kategori adı, başlı kart için `hsl(var(--secondary))` zeminli pill.
- **Status — Önemli**: Solid `--primary` zemin + beyaz metin.
- **Status — Genel**: `--muted` zemin + `--foreground` metin.

### 5.6 Table
```
header: text-sm font-medium text-muted-foreground, uppercase letter-spacing .02em opsiyonel
row: border-bottom 1px solid hsl(var(--border))
row hover: background hsl(var(--secondary) / .5)
cell padding: 12–16px dikey, 16–20px yatay
```
- Sıralanabilir sütunlarda ikinci satırda `↕` ikonu.
- Sağa hizalı: numeric sütunlar (Güç, Seviye).

### 5.7 Accordion (SSS pattern)
```
item border-bottom: 1px solid hsl(var(--border))
trigger: padding 16px 0, font Rajdhani 16px
chevron: rotate 180° açıkken
```

### 5.8 Chart (Recharts)
- Çizgi grafik: line color `hsl(var(--primary))`, dolgu yok, dot yarıçap 3, hover 5.
- Bar grafik: kategori renkleri (§2.5).
- Grid: `stroke hsl(var(--border))`, dashed `3 3`.
- Eksen etiket: `fill hsl(var(--muted-foreground))`, font 12px.

### 5.9 Toast / Alert
- Başarı: kırmızı yerine yeşil (`hsl(142 72% 45%)`) — kırmızı zaten primary, başarı için karışmasın.
- Hata: `--destructive`.
- Bilgi: `--secondary` zemin + `--primary` ikon.

---

## 6. İkonografi

- **Kütüphane**: `lucide-react`.
- **Boyut**: 16px (inline), 20px (kart başlığı yanı), 24px (büyük vurgu).
- **Renk kuralı**: Kart/section başlık ikonları **her zaman `--primary` kırmızı**. Body içinde dekoratif ikonlar `--muted-foreground`.
- **Stroke**: 2 (varsayılan). Kalın hat çağrışımı için `2.25` denenebilir.
- **Sembolik motifler**: Kurt başı (logo), alev/ateş, kalkan, ok, hedef. Emoji'ler (🚨🐺) duyuru/başlıkta kullanılabilir ama UI bileşenlerinde değil.

---

## 7. Navigation Pattern

Üst nav (gift panelinin login sonrası ekranı için):
- Sol: marka logosu (32–40px yüksek, gradient-fire halo).
- Orta: nav linkleri yatay — her biri ikon + label, `gap-2`, ghost varyant.
- Sağ: dil seçici (globe ikon), logout (logout ikon, ghost).
- Aktif link: `bg-primary/10 text-primary`.

---

## 8. Sayfa Şablonları (gift panelinde uyarlanabilir karşılıklar)

| App.ks-wolfpack | Gift panel karşılığı |
|---|---|
| Dashboard (KPI + line chart + son etkinlik/duyuru) | Genel bakış: gönderilen kod sayısı, aktif kampanya, son redeem'ler |
| Üyeler (sortable tablo + filtre) | Oyuncular / Redeem geçmişi tablosu |
| Etkinlikler (kategorili liste + tarih) | Gift kodları listesi (kategori = paket türü, tarih = bitiş) |
| Duyurular (uzun içerik kartları + etiketler) | Kampanya açıklamaları |
| Profil (tab'lı form: Genel / Şifre / Tercihler) | Admin profili & ayarlar |
| SSS (accordion + tab) | Yardım |

---

## 9. Login Ekranı (gift panelinin en görünür ekranı)

Mevcut yapı korunabilir ama tema şu şekilde değişir:

- Sayfa zemini: `--gradient-dark` (#141414 → #080808 dikey).
- Kart genişlik: 440px max, padding 32px, border 1px `--border`, radius 12px, `--gradient-card`.
- Kart üstünde 2px ince **gradient-fire** bandı (zaten gift'te sarı var — bunu kırmızı/ember yap).
- Logo: 80–96px kare, alt yuvarlatılmış köşe; arkasında `--shadow-ember` glow.
- Başlık: Rajdhani 700, 28–32px, **`bg-clip-text` + `--gradient-fire`** ile kırmızı→turuncu geçişli. (Mevcut sarı yerine.)
- Subtitle (`COMMAND CENTER • SECURE ACCESS`): Exo 2 600, 11–12px, `letter-spacing: 0.2em`, `--muted-foreground`.
- Label (`USERNAME`, `PASSWORD`): Exo 2 500, 11px, uppercase, `letter-spacing: 0.1em`, `--muted-foreground`.
- Input: §5.3.
- CTA "ACCESS SYSTEM": Primary button, **tam genişlik**, 12px dikey padding, uppercase, `letter-spacing: 0.05em`, hover'da `--shadow-fire`.

---

## 10. Erişilebilirlik & State

- **Kontrast**: Tüm metin AA standartlarını tutmalı. `--muted-foreground` (#8C8C8C) #141414 üzerinde ≈ 4.6:1 → OK.
- **Focus**: Her interaktif öğede `outline: 2px solid hsl(var(--ring))` ya da `ring-2 ring-primary`.
- **Hover**: Subtle (zemin tonu shift + ~150ms transition).
- **Disabled**: `opacity: 0.5; cursor: not-allowed`.
- **Loading**: `Yükleniyor...` metni `--muted-foreground`. Spinner rengi `--primary`.
- **Motion**: 150–200ms `ease-out`. Aşırı animasyon yok; "askeri panel" hissi durağan.

---

## 11. Mevcut Gift Paneliyle Karşılaştırma (özet değişiklikler)

Gift panelin her sayfası tek tek incelendi: **Dashboard, Players, Codes, Rewardwolf Control, Logs, File Editor, Settings, Notifications, API Keys** + login. Aşağıdaki değişiklikler tüm sayfalara uygulanır.

| Alan | Mevcut (gift) | Hedef (app uyumlu) |
|---|---|---|
| Body background | `#0C0E13` (mavi-gri) | `#0D0D0D` (`--background`, nötr koyu) |
| Sidebar background | `#191B21` | `hsl(var(--sidebar-background))` = `#0F0F0F` |
| Birincil vurgu | Sarı `#F0A500` | **Kırmızı** `#EC1313` (+ ember `#F25F22` ikincil) |
| Logo (Space Grotesk 900 sarı) | "WLF GİFT PANEL" sarı | Aynı metin, **Rajdhani 700** + `bg-clip-text` `--gradient-fire` |
| Sayfa H1 (Inter 800 beyaz, ~48px) | "Dashboard", "Players" | **Rajdhani 700**, 36–40px, `--foreground` |
| Section label ("OVERVIEW", "MANAGEMENT", "SYSTEM") | Inter uppercase gri | Exo 2 uppercase 11px, `letter-spacing: .2em`, `--muted-foreground` |
| Body font | `Inter, sans-serif` | **Exo 2** |
| Heading font | `Inter` veya `Space Grotesk` | **Rajdhani** |
| Card border | `border` koyu mavi | `1px solid hsl(var(--border))` (`#292929`) |
| KPI sayı renkleri | Kategoriye göre (sarı/mavi/yeşil) | App'teki gibi: ana KPI `--foreground` beyaz, vurgu KPI `--primary`. Sistem metrikleri (CPU/RAM/TEMP) korunabilir ama yeşil/sarı yerine: OK=yeşil `hsl(142 72% 45%)`, warn=ember `--ember`, danger=`--destructive` |
| Aktif sidebar item | Sarı zemin + sarı text | `bg-primary/10 text-primary` (§5.2 Active Nav) |
| Sidebar hover | Düz mavi-gri | `bg-sidebar-accent` (`#1F1F1F`) + `text-foreground` |
| Status pill (ACTIVE yeşil, EXPIRED gri, COMPLETE mavi) | Korunur | Aynı semantik kalır, sadece gri tonu `--secondary`, mavi yerine `hsl(220 75% 60%)` (App'te KVK rengiyle uyumlu) |
| Role pill (R3/R4/R5 mor) | Mor (mavi-mor) | App'in §5.5 Rank badge varyantı: `bg-primary/15 text-primary border-primary/30` (kırmızı tonlu) |
| Process butonları | START yeşil, STOP kırmızı, RESTART sarı, REBUILD mavi | Renkler korunur (semantik); ancak STOP & RESTART, app'in palet tonlarına çekilir: STOP=`--destructive`, RESTART=`--ember` (sarı yerine), REBUILD=mavi (`hsl(220 75% 55%)`), START=yeşil (`hsl(142 72% 45%)`). Tüm butonlar §5.2 boyut/radius kurallarına uyar. |
| "REMOVE" butonu | Sarı | `--destructive` kırmızı (silme aksiyonu için doğru semantik) |
| "+VIP" butonu | Sarı solid | `--ember` solid (turuncu — "premium" hissi) ya da sarı korunabilir (gift codes "ödül" sarı'sı) |
| Sol alt status ("Rewardwolf Running" yeşil) | Korunur | Korunur; sadece punto Exo 2, monospace yardımcı satır kaldırılmaz (terminal hissi marka için iyi) |
| Logout butonu (sol alt) | Ghost beyaz | Aynı; hover'da `bg-secondary` |
| Tipografi etiketleri (CHECK INTERVAL, RAM ALERT) | Inter uppercase 11px | Exo 2 uppercase 11px, `letter-spacing: .15em` |
| Input | Koyu zemin, ince border | §5.3 input — `bg-input`, focus ring `--primary` |
| Terminal kart (Rewardwolf > wolf_terminal) | Mevcut estetik (3 nokta + monospace) | Aynen korunur, monospace ailesi: `"JetBrains Mono", ui-monospace, monospace` |
| Progress bar (Codes sayfası) | Sarı-yeşil gradient | `--gradient-fire` (kırmızı→turuncu) |
| Login üst bant | Sarı çizgi | `--gradient-fire` (kırmızı→turuncu) |
| Sayfa başlığı üstündeki "OVERVIEW / MANAGEMENT / SYSTEM" mini-label | Korunur | Mini-label sistemi `--muted-foreground` ile devam eder |

---

## 12. Hızlı CSS Variable Bloku (kopyalanabilir)

```css
:root {
  --font-heading: "Rajdhani", sans-serif;
  --font-body: "Exo 2", sans-serif;

  --background: 0 0% 5%;
  --foreground: 0 0% 93%;
  --card: 0 0% 8%;
  --card-foreground: 0 0% 93%;
  --popover: 0 0% 10%;
  --popover-foreground: 0 0% 93%;
  --primary: 0 85% 50%;
  --primary-foreground: 0 0% 100%;
  --secondary: 0 0% 12%;
  --secondary-foreground: 0 0% 90%;
  --muted: 0 0% 14%;
  --muted-foreground: 0 0% 55%;
  --accent: 0 70% 45%;
  --accent-foreground: 0 0% 100%;
  --destructive: 0 84% 60%;
  --destructive-foreground: 0 0% 100%;
  --border: 0 0% 16%;
  --input: 0 0% 16%;
  --ring: 0 85% 50%;
  --radius: 0.5rem;

  --ember: 15 90% 55%;
  --ember-glow: 0 100% 40%;
  --wolf-gray: 0 0% 70%;
  --wolf-dark: 0 0% 3%;

  --gradient-fire: linear-gradient(135deg, hsl(0 85% 50%), hsl(15 90% 55%), hsl(0 100% 40%));
  --gradient-dark: linear-gradient(180deg, hsl(0 0% 8%), hsl(0 0% 3%));
  --gradient-card: linear-gradient(145deg, hsl(0 0% 10%), hsl(0 0% 6%));

  --shadow-fire: 0 0 30px -5px hsl(0 85% 50% / .4);
  --shadow-ember: 0 0 60px -10px hsl(0 85% 50% / .2);
  --glow-red: 0 0 20px hsl(0 85% 50% / .3);

  --sidebar-background: 0 0% 6%;
  --sidebar-foreground: 0 0% 85%;
  --sidebar-primary: 0 85% 50%;
  --sidebar-primary-foreground: 0 0% 100%;
  --sidebar-accent: 0 0% 12%;
  --sidebar-accent-foreground: 0 0% 90%;
  --sidebar-border: 0 0% 14%;
  --sidebar-ring: 0 85% 50%;
}

body {
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  font-family: var(--font-body);
}

h1, h2, h3, h4, h5, h6 {
  font-family: var(--font-heading);
  font-weight: 700;
}
```

---

## 13. Uygulama Sırası (gift panelini revize ederken)

1. Font'ları (`Rajdhani`, `Exo 2`) ekle, `Inter`'i kaldır.
2. CSS variable bloğunu projeye taşı (`globals.css` veya `theme.css`).
3. Login kartında: sarı → kırmızı, başlık `bg-clip-text gradient-fire`, label'ları uppercase.
4. Buton sistemini §5.2'ye göre yeniden tanımla.
5. Form input'larını §5.3'e göre tek tipleştir.
6. Login sonrası ekranlar için: navigation §7, kart §5.1, tablo §5.6 örüntülerini uygula.
7. İkonları `lucide-react`'e geçir; kart başlık ikonları `text-primary`.
8. Tüm yerleşimleri 8px tabanlı spacing'e oturt.

---

## 14. Referans Sayfalar (incelenenler)

### app.ks-wolfpack.com — Member
- `/member/dashboard` — KPI + line chart + son etkinlik/duyuru kartları
- `/member/members` — sortable tablo + arama + filter dropdown
- `/member/events` — kategorili liste + iki CTA (liste/takvim)
- `/member/announcements` — etiketli içerik kartları
- `/member/profile` — tab'lı form (Genel/Güç/İstatistikler/Transfer) + iki ayrı form bölümü
- `/member/attendance` — özet KPI + bar chart + dağılım tablosu
- `/member/history` — tarih filtreleri + tab + line chart + liste
- `/member/faq` — accordion + üst seviye tab
- `/member/contact` — basit form (Başlık + Mesaj textarea + Gönder primary)

### app.ks-wolfpack.com — Admin
- `/admin/dashboard` — **10 KPI kart 2 sütun**, her biri kırmızı ikon + büyük rakam + alt açıklama; ayrıca sistem metrikleri (CPU/RAM/Temperature) burada da var → gift panelinin metrik kartlarına birebir referans
- `/admin/users` (varsa) — admin yetkili üye listesi (404 döndü)
- `/admin/announcements` — duyuru kartı + edit (kalem) / sessize alma (zil-kapalı) / sil (kırmızı çöp) ikon butonları + sağ üstte `+ Yeni Duyuru` primary
- `/admin/events` — list/calendar toggle + `+ Ekle` primary + her kartta 3 ghost button (Oluşumları göster / Oluştur / Yeniden oluştur) + edit/archive/delete ikon butonları + duration badge (`30 min`, `720 min`) + `Herkese Açık` badge
- `/admin/attendance` — üç sekme (Giriş / İstatistikler / Score entry and calculation) + 4 dropdown filter
- `/admin/progression` — inline editable tablo (Rank dropdown + Power input + Level input + Update date input)
- `/admin/transfers` — 4 KPI özet + arama + 6 dropdown filter + boş tablo placeholder + sağ üstte `+ Nouvelle analyse` primary
- `/admin/sanctuaries` — **complex matrix tablo**: 9 satır (S1-S9 konum) × 6 sütun (S1-S6 sezon), her hücrede 2 badge (kategori dot pill + alliance kodu pill) + alt küçük metin
- `/admin/imports` — sekme (İçe/Dışa) + dropdown + kolon badge'leri (`game_id` aktif kırmızı) + dropzone (`Dosya seçmek için tıklayın`) + history kartları (success/warning ikon + dosya adı + tag pill'leri + sayaç linkleri + 3 outline button)
- `/admin/history` — 4 sekme (Güç&Seviyeler / İsim Değişiklikleri / Rütbeler / Durum Değişiklikleri) + 3 tarih input + liste (mini sparkline ikon + isim + ID + büyük sayı + Lv badge + tarih)

### gift.ks-wolfpack.com — Mevcut Sayfalar
- `/` (login) — wolf logo + sarı bant + Username/Password + ACCESS SYSTEM sarı button
- `/` (dashboard) — 4 üst KPI (Players/Total Redemptions/All-Time Success/Active Codes, her biri farklı renk) + 3 sistem metrik (CPU/RAM/Temperature) + GIFT CODES tablo
- Players — Ara input + All Players filter + tablo (ID/Name/VIP/Role/Since/Status + Action: +VIP yellow, R3 input, REMOVE red) + sağ üst Sync Sheets/Sync Names ghost + ADD PLAYER yellow
- Codes — Code/Status/Created/Expires/Success/Already/Failed/Progress/Detail tablo + Refresh ghost
- Rewardwolf Control — Process kartı (4 büyük buton: START yeşil / STOP kırmızı / RESTART sarı / REBUILD mavi) + Status kartı (Running göstergesi + CPU/RAM/TEMP mini bar) + macOS-stil Terminal kartı + Distribution Status + Trigger Distribution + Add Code Manually + Send Message + System Check + Test All Channels
- Logs — terminal-style log viewer + 100 lines/All Levels filter + Filter logs input + reload + Auto-scroll checkbox + sağ üst `● LIVE` indicator
- File Editor — macOS-stil editör başlık (3 nokta) + dosya adı + Reload/Confirm password disabled/Save/SAVE & REBUILD primary
- Settings — 6 input + alt yardımcı metin grid (2 sütun) + SAVE SETTINGS sarı button
- Notifications — kanal kart listesi (telegram/discord ikonu + isim + Active pill + Chat ID/Webhook + event badge'leri) + 4 ikon button (gönder/sessiz/edit/sil) + sağ üst `+ ADD CHANNEL`
- API Keys — Yeni Anahtar Oluştur (input + OLUŞTUR sarı) + Aktif Anahtarlar kartı (kopyala + SİL) + Public Endpoint Referansı (GET method badge yeşil + URL + JSON kod blokları + curl kullanım kartı)

### Tutarlılık Notu
Member ve Admin ekranları **aynı navigation çubuğunu, aynı palet ve aynı kart yapısını** paylaşır; Admin'de sadece daha fazla aksiyon butonu (edit/archive/delete) ve "+ Yeni" CTA'sı vardır. **Hedef bütünlük budur.**

---

## 15. Sayfa-Sayfa Gift Panel Revizyon Talimatı

Aşağıda gift panelin **her sayfası için** spesifik değişiklikler. §11'deki global eşleme + §5'teki bileşen kuralları varsayılır.

### 15.1 Login (`/`)
- Logo kutusunun arkasındaki **sarı çerçeve gradient** → `--gradient-fire` ile değiştir.
- "WLF GİFT PANEL" başlığı: `Rajdhani 700, 32px, bg-clip-text gradient-fire` (sarı düz renk değil).
- "COMMAND CENTER • SECURE ACCESS" subtitle: aynı, sadece font Exo 2 + `letter-spacing: 0.2em`.
- "ACCESS SYSTEM" button: solid `--primary` kırmızı, uppercase, `letter-spacing: 0.05em`, hover'da `--shadow-fire`.
- Card border: `1px solid hsl(var(--border))`; üst kenarda 2px gradient-fire bant.

### 15.2 Sidebar (her sayfada)
- Logo kutusu (sol üst): sarı yerine `bg-clip-text gradient-fire`.
- Section header (`OVERVIEW / MANAGEMENT / SYSTEM`): aynen kalır, sadece punto Exo 2.
- Aktif item: §5.2 "Active Nav" → `bg-primary/10 text-primary`.
- "Rewardwolf Running" badge: yeşil nokta + monospace metin korunur (terminal hissi marka için iyi).
- Tarih satırı: monospace, `--muted-foreground`.
- LOGOUT button: ghost, hover'da `--secondary` zemin.

### 15.3 Dashboard
- 4 üst KPI kartı (PLAYERS/TOTAL REDEMPTIONS/ALL-TIME SUCCESS/ACTIVE CODES):
  - Mevcut "her biri farklı renkli sayı" yerine **§5.1 standart kart** kullan: rakam beyaz (`--foreground`), üst KPI label `--muted-foreground` uppercase 11px.
  - "PLAYERS" ana KPI'si ise opsiyonel olarak `--primary` ile vurgulanabilir (app dashboard'unda 311.578M güç beyaz çıkıyor → biz de beyaz tutalım).
  - Sağ üstte büyük şeffaf ikon (people/gift/check/grid) korunur; rengi `--primary/30` (alpha düşük).
- 3 sistem metrik kartı (CPU LOAD/RAM USAGE/TEMPERATURE):
  - **Admin dashboard'daki CPU/RAM/Temp kartına eşle**: kırmızı ikon başlık yanında + büyük rakam beyaz + alt küçük metin (`1247 / 1846 MB` gibi) muted.
  - Progress bar altta: track `--secondary`, fill `--gradient-fire` ya da threshold'a göre yeşil/ember/destructive.
- GIFT CODES tablosu: §5.6 table kuralı + status pill (ACTIVE=yeşil, EXPIRED=`--muted` zemin/`--muted-foreground` metin, COMPLETE=`hsl(220 75% 60%)`); progress bar `--gradient-fire`.

### 15.4 Players
- Üst toolbar: Search input (§5.3), `All Players` outline filter, Refresh icon ghost. Sağda `Sync Sheets`, `Sync Names` ghost; `ADD PLAYER` primary.
- ID sütunu: sarı yerine `--primary` (kırmızı tonlu) numerik.
- VIP sütunu: değer yoksa `—` muted; varsa "✓" primary.
- Role pill (R3/R4/R5): §5.5 Rank badge varyantı.
- Status pill `ACTIVE`: yeşil `hsl(142 72% 45%)`, pill dot ile.
- Aksiyon sütunu:
  - `+VIP`: solid `--ember` (turuncu/sarı arası — premium hissi).
  - Role input: §5.3 input compact.
  - `REMOVE`: solid `--destructive` kırmızı.

### 15.5 Codes
- Tablo şeması §5.6.
- Status pill `ACTIVE · COMPLETE`: mavi (`hsl(220 75% 60%)`) + nokta.
- Status pill `EXPIRED`: `--muted` zemin + `--muted-foreground` metin.
- Success sayısı: yeşil `hsl(142 72% 45%)`; Already: ember; Failed: `--destructive`.
- Progress bar: `--gradient-fire`; %100 üstü "overflow" hali için ember vurgu.
- `VIEW` button her satırda: ghost outline.
- Code metni: monospace (`JetBrains Mono` veya `ui-monospace`).

### 15.6 Rewardwolf Control
- 4 büyük process button (START / STOP / RESTART / REBUILD):
  - START: solid yeşil `hsl(142 72% 45%)` + beyaz metin.
  - STOP: solid `--destructive` kırmızı.
  - RESTART: solid `--ember` (sarı yerine).
  - REBUILD: solid `hsl(220 75% 55%)` mavi.
  - Tümü tam genişlik dikey stack, padding `12px 16px`, radius 8px, font Exo 2 600 uppercase.
- Status kartı: "Running" yeşil nokta, alt CPU/RAM/TEMP mini progress (dashboard mantığıyla).
- Terminal kartı (`wolf_terminal`): macOS-stil 3 nokta (red/yellow/green) korunur; başlık monospace 12px muted; içerik monospace `--foreground`; alt input + Run button (`--ember` ya da primary).
- Distribution Status: progress satırı + Retry ghost + status pill (COMPLETE mavi).
- "Trigger Distribution / Add Code Manually": form alanı + Run yeşil button (success aksiyonu yeşil).
- "Send Message": dropdown (kanal seç) + textarea + SEND primary kırmızı (sarı yerine — bu bir "gönderme" aksiyonu, primary CTA).
- "System Check / Test All Channels": placeholder metin + Run/Test All button (mavi `hsl(220 75% 55%)` ya da `--ember`).

### 15.7 Logs
- Filtre satırı: `100 lines` outline, `All Levels` outline, Filter input (§5.3), Refresh ghost, "Auto-scroll" checkbox + label.
- Sağ üst `● LIVE`: yeşil nokta + Exo 2 uppercase 11px `letter-spacing: 0.15em`.
- Log içeriği: monospace 12px, timestamp `--muted-foreground`, `[INFO]` ember, `[ERROR]` destructive, `[WARN]` ember-glow. Satır arası 6px.
- Scroll container: `--card` zemin, `1px solid --border`, içeride 16px padding.

### 15.8 File Editor
- Üst toolbar (sağ tarafta): Reload outline, "Confirm password" input (disabled görünüm, password için), Save outline, `SAVE & REBUILD` primary (zaten gift'te kırmızı — bu doğru, primary'a hizalanır).
- Editör kartı: macOS-stil 3 nokta korunur (red/yellow/green); başlık `daemon.py — Python` monospace 12px `--muted-foreground`; sağda uyarı satırı `⚠ Save & Rebuild restarts the container` `--ember` rengi 11px.
- Kod içeriği: monospace 13px, koyu (`hsl(0 0% 4%)`), syntax highlighting opsiyonel (`--primary` keyword, `--ember` string).

### 15.9 Settings
- Grid 2 sütun, gap 16px.
- Her input kartı:
  - Üst label uppercase 11px `--muted-foreground`.
  - Input §5.3.
  - Alt yardımcı metin 12px `--muted-foreground` italic veya normal.
- `SAVE SETTINGS` button: §5.2 primary kırmızı, uppercase, ikon (save) solda, margin-top 24px.

### 15.10 Notifications
- Kanal kart listesi: §5.1 card + sol avatar/ikon (telegram = mavi, discord = mor, varsayılan kurt avatar).
- Başlık: Rajdhani 700 16px + sağında **`● Active` pill** (yeşil dot + yeşil metin).
- Alt meta: `Chat ID:` veya `Webhook URL:` monospace 12px `--muted-foreground`.
- Event badge'leri (`New Code`, `Distribution`, `Expiry`): kategori pill — her biri kategoriye özel renkli dot + secondary zemin.
- Sağdaki 4 ikon button (paper-plane / mute / pencil / trash): Ghost, `gap-1`. Trash hover'da `--destructive`.
- Sağ üst `+ ADD CHANNEL`: primary kırmızı.

### 15.11 API Keys
- `YENİ ANAHTAR OLUŞTUR` kartı: 2 input yan yana + `OLUŞTUR` primary kırmızı (sarı yerine) — uppercase, ikon + key.
- `AKTİF ANAHTARLAR` kartı: tek satır kart, "hati" başlık + `aktif` yeşil pill + sağda `SİL` destructive button. Anahtar metni: monospace input + sağda kopyala ikon (ghost) + alt metadata 12px muted (`Oluşturuldu: ... · Son kullanım: ...`).
- `PUBLIC ENDPOINT REFERANSI`:
  - Her endpoint kartı: `GET` method badge yeşil + monospace URL + sağda açıklama 12px muted.
  - Kod bloku: `bg-wolf-dark` (#080808), monospace, padding 16px, radius 8px, syntax minimal.
- `KULLANIM` örneği: en alta küçük kart, monospace curl komutu.

---

## 16. Bonus: Mevcut "WLF GİFT PANEL" yazısı için inline CSS

```css
.brand {
  font-family: var(--font-heading);
  font-weight: 700;
  font-size: 24px;
  background: var(--gradient-fire);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  letter-spacing: 0.02em;
}
.brand-sub {
  font-family: var(--font-body);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: hsl(var(--muted-foreground));
  text-transform: uppercase;
}
```

Bu, mevcut "WLF GİFT PANEL / v2.1.0 - REWARDWOLF" başlığını app'in marka kimliğiyle birebir aynı dile çevirir.
