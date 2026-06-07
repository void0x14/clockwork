# Clockwork — YouTube Otomatik Bölüm Zaman Damgası Üretici

Kanalınızdaki videoların altyazılarını (.srt) indirir, AI ile zaman damgası üretir ve video açıklamalarına otomatik olarak ekler.

---

## Gereksinimler

| Araç | Minimum Versiyon |
|------|-----------------|
| Python | 3.9+ |
| FFmpeg | Herhangi (PATH'de olmalı) |

FFmpeg kurulumu: https://ffmpeg.org/download.html  
macOS: `brew install ffmpeg` | Ubuntu: `sudo apt install ffmpeg`

---

## Kurulum

```bash
git clone [<repo>](https://github.com/void0x14/clockwork)
cd ytchapters
pip install -r requirements.txt
```

---

## Google Cloud Console Kurulumu (YouTube API)

> `auto` ve `generate --update` komutları için gerekli. `download` için gerekmez.

1. https://console.cloud.google.com → **New Project** oluştur
2. **APIs & Services → Library** → "YouTube Data API v3" → **Enable**
3. **APIs & Services → Credentials → + CREATE CREDENTIALS → OAuth client ID**
   - Application type: **Desktop app**
   - Name: ytchapters
4. İndirilen JSON'ı `client_secrets.json` olarak proje klasörüne kaydet

İlk çalıştırmada tarayıcı açılır, Google hesabınızla giriş yaparsınız. Token otomatik kaydedilir.

---

## Yapılandırma

`config.yaml` içindeki alanları doldurun:

```yaml
youtube:
  channel_url: "https://www.youtube.com/@void0x14"

ai:
  default_provider: "anthropic"   # veya openai, gemini, groq, ollama...
  providers:
    anthropic:
      api_key: "sk-ant-..."
    openai:
      api_key: "sk-..."
    gemini:
      api_key: "AI..."
    groq:
      api_key: "gsk_..."
    ollama:                        # Yerel model, API key gerekmez
      model: "llama3.2:latest"
```

---

## Kullanım

### 1. YouTube OAuth girişi (bir kez)
```bash
python main.py auth
```

### 2. Sadece SRT indir (AI olmadan)
```bash
# Tüm kanalı
python main.py download

# Tek video
python main.py download --video "https://www.youtube.com/watch?v=VIDEO_ID"

# Farklı çıktı klasörü
python main.py download --out ./my_subs
```

### 3. Tek SRT'den zaman damgası üret
```bash
# Sadece ekrana yaz
python main.py generate subtitles/VIDEO_ID/VIDEO_ID.tr.srt --title "Video Başlığı"

# Üret + YouTube açıklamasına ekle
python main.py generate subtitles/VIDEO_ID/VIDEO_ID.tr.srt \
  --title "Video Başlığı" \
  --update VIDEO_ID

# Önce test et
python main.py generate subtitles/VIDEO_ID/VIDEO_ID.tr.srt \
  --title "Video Başlığı" \
  --update VIDEO_ID --dry-run

# Farklı provider
python main.py generate subtitles/VIDEO_ID/VIDEO_ID.tr.srt \
  --provider ollama --title "Başlık"
```

### 4. Tam otonom mod (önerilen)
```bash
# Tüm kanal — SRT indir + AI + açıklama güncelle
python main.py auto

# Önce test et (YouTube'a yazmaz)
python main.py auto --dry-run

# Tek video
python main.py auto --video "https://www.youtube.com/watch?v=VIDEO_ID"

# Zaten işlenmiş videoları yeniden işle
python main.py auto --force

# Farklı provider
python main.py auto --provider groq
```

---

## Provider Önerileri

| Provider | Hız | Kalite | Maliyet |
|----------|-----|--------|---------|
| **claude-sonnet** | Orta | En iyi | ücretli |
| **gpt-4o** | Orta | Çok iyi | ücretli |
| **groq/llama-3.3-70b** | Çok hızlı | İyi | ücretsiz kota |
| **gemini-1.5-pro** | Hızlı | Çok iyi | ücretsiz kota |
| **ollama/llama3.2** | Yerel | Orta | ücretsiz |

---

## Dosya Çıktıları

```
subtitles/
  VIDEO_ID/
    VIDEO_ID.tr.srt      ← İndirilen altyazı
timestamps/
  VIDEO_ID.txt           ← Üretilen zaman damgaları
state.json               ← İşlem durumu (devam etme için)
token.json               ← YouTube OAuth token (otomatik)
```

---

## YouTube API Kota Kullanımı

| İşlem | Maliyet |
|-------|---------|
| Video listesi (50/istek) | ~1-5 birim |
| Video detayı (50/istek) | 1 birim |
| Açıklama güncelleme | 50 birim/video |

Günlük ücretsiz kota: 10.000 birim ≈ ~190 video güncellemesi.

---

## Sorun Giderme

**"FFmpeg not found"** → PATH'e ekleyin veya yükleyin  
**"Altyazı yok"** → Video otomatik altyazı desteklemiyor olabilir; manuel ekleyin  
**"Quota exceeded"** → Yarın devam edin (state.json işlenen videoları hatırlar)  
**"Token expired"** → `token.json` silin, `python main.py auth` tekrar çalıştırın
