# SENFONİ

Premium Discord müzik deneyimi için tasarlanmış, minimalist ve yüksek performanslı masaüstü kontrol paneli.

## ÖZELLİKLER

* **Gelişmiş Dashboard**: CustomTkinter ile optimize edilmiş, derin siyah (deep black) minimalist arayüz.
* **Hibrit Oynatma**: YouTube ve Instagram desteği ile URL veya arama sorgusu üzerinden anlık yayın.
* **Premium Favori Sistemi**:
    * Sık dinlenenler için otomatik yerel önbellekleme (Local Cache).
    * Sağ tık menüsü ile kolay isim değiştirme ve silme.
    * Cache üzerinden gecikmesiz (instant) başlatma.
* **Dinamik TTS (Metin Okuma)**:
    * Edge-TTS entegrasyonu ile doğal sesler.
    * Otomatik dil algılama ve cinsiyet seçimi.
    * Müzik sırasında akıllı duraklatma ve devam etme (Auto-Resume).
* **Global Kontrol**: Uygulama arka plandayken çalışabilen global kısayol tuşu desteği.
* **Akıllı Kuyruk**: Şarkı sırası yönetimi ve otomatik geçiş sistemi.

## KURULUM

1. **Bağımlılıklar**
   ```bash
   pip install -r requirements.txt
   ```

2. **FFmpeg**
   Sisteminizde FFmpeg yüklü olmalı ve yürütülebilir dosya yolu belirlenmelidir.

3. **Yapılandırma**
   `.env.example` dosyasını `.env` olarak kopyalayın ve bilgilerinizi girin:
   ```env
   DISCORD_TOKEN=your_token_here
   FFMPEG_PATH="C:\\ffmpeg\\bin\\ffmpeg.exe"
   OWNER_ID=your_discord_id
   HOTKEY=home
   PREFIX=!
   ```

## KULLANIM

* **Bağlan**: Botun ses kanalınıza katılması için sidebar'daki butonu kullanın.
* **Oynat**: Arama çubuğuna terim veya link girip `ENTER` veya `OYNAT` tuşuna basın.
* **Sıra**: Şarkıları sıraya eklemek için `+ SIRAYA EKLE` butonunu kullanın.
* **Favori**: Çalan şarkıyı `⭐` ile kaydedin. Favori listesinde:
    * **Sol Tık**: Şarkıyı direkt (cache üzerinden) başlatır.
    * **Sağ Tık**: İsim değiştirme veya silme menüsünü açar.
* **Hotkey**: Belirlenen tuş (varsayılan: `HOME`) ile global olarak oynat/duraklat yapabilirsiniz.

## TEKNİK DETAYLAR

* **Dil**: Python 3.10+
* **UI**: CustomTkinter (Modern Dark Theme)
* **Ses**: FFmpeg & discord.py
* **Streaming**: yt-dlp
* **Konfigürasyon**: python-dotenv
