import threading
import asyncio
import discord
from discord.ext import commands
import customtkinter as ctk
import tkinter as tk
import yt_dlp
import os
import time
import logging
import sys
import json
import hashlib
from pynput import keyboard
from pynput.keyboard import Key
import edge_tts
import tempfile
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger('MusicBot')

def load_config():
    config = {
        'TOKEN': os.getenv('DISCORD_TOKEN'),
        'FFMPEG_PATH': os.getenv('FFMPEG_PATH', r"C:\ffmpeg\bin\ffmpeg.exe"),
        'OWNER_ID': os.getenv('OWNER_ID', ''),
        'HOTKEY': os.getenv('HOTKEY', 'home'),
        'PREFIX': os.getenv('PREFIX', '!'),
        'TTS': {
            'VOICE_TR': os.getenv('VOICE_TR', "tr-TR-EmelNeural"),
            'VOICE_EN': os.getenv('VOICE_EN', "en-US-AriaNeural")
        }
    }
    
    if not config['TOKEN']:
        logger.error("❌ HATA: .env dosyasında DISCORD_TOKEN bulunamadı!")
        sys.exit(1)
    
    logger.info("✅ Yapılandırma .env dosyasından yüklendi.")
    return config

CONFIG = load_config()
TOKEN = CONFIG['TOKEN']
FFMPEG_PATH = CONFIG['FFMPEG_PATH']
CACHE_DIR = "songs_cache" 

FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch1',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web']
        }
    }
}

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        prefix = CONFIG.get('PREFIX', '!')
        super().__init__(command_prefix=prefix, intents=intents)
        self.voice_client = None
        self.loop_mode = False
        self.current_url = None
        self.current_title = "Beklemede..."
        self.volume = 1.0
        self.duration = 0
        self.start_offset = 0
        self.playback_start_time = 0
        self.accumulated_time = 0
        self.play_lock = asyncio.Lock()
        self.queue = []
        self.current_data = None
        self._manual_stop = False
        self.is_playing_from_cache = False
        self.favorites = self.load_favorites()
        self.clean_orphaned_cache()
        self._cache_check_done = False

    def load_favorites(self):
        try:
            with open('favorites.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def save_favorites(self):
        try:
            with open('favorites.json', 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Favori kaydetme hatası: {e}")

    def get_cache_filename(self, url, title=None):
        if title:
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_title = safe_title.replace(' ', '_')[:100]
            return f"{safe_title}.mp3"
        else:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            return f"{url_hash}.mp3"

    def get_cached_file_path(self, url, title=None):
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)
        return os.path.join(CACHE_DIR, self.get_cache_filename(url, title))

    def is_favorite_cached(self, url, title=None):
        cache_path = self.get_cached_file_path(url, title)
        return os.path.exists(cache_path)

    async def download_favorite_to_cache(self, url, title):
        try:
            cache_path = self.get_cached_file_path(url, title)
            if os.path.exists(cache_path):
                return cache_path
            ffmpeg_location = os.path.dirname(FFMPEG_PATH) if os.path.exists(FFMPEG_PATH) else None
            cache_path_without_ext = cache_path.replace('.mp3', '')
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': cache_path_without_ext,
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web']
                    }
                },
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
            if ffmpeg_location:
                ydl_opts['ffmpeg_location'] = ffmpeg_location
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                await loop.run_in_executor(None, lambda: ydl.download([url]))
            return cache_path
        except Exception as e:
            logger.error(f"Cache indirme hatası: {e}")
            return None

    def clean_orphaned_cache(self):
        try:
            if not os.path.exists(CACHE_DIR):
                return
            valid_filenames = set()
            for fav in self.favorites:
                url = fav.get('url')
                title = fav.get('title')
                if url and title:
                    valid_filenames.add(self.get_cache_filename(url, title))
            cleaned = 0
            for filename in os.listdir(CACHE_DIR):
                if filename not in valid_filenames:
                    file_path = os.path.join(CACHE_DIR, filename)
                    try:
                        os.remove(file_path)
                        cleaned += 1
                    except Exception as e:
                        logger.error(f"Cache silme hatası: {e}")
            if cleaned > 0:
                logger.info(f"🧹 {cleaned} orphaned cache dosyası temizlendi")
        except Exception as e:
            logger.error(f"Cache temizleme hatası: {e}")

    def add_to_favorites(self):
        if not self.current_url or not self.current_title:
            return False
        for fav in self.favorites:
            if fav.get('url') == self.current_url:
                return False
        fav_data = {
            'title': self.current_title,
            'url': self.current_url,
            'duration': self.duration
        }
        self.favorites.append(fav_data)
        self.save_favorites()
        logger.info(f"⭐ Favorilere eklendi: {self.current_title}")
        asyncio.run_coroutine_threadsafe(
            self.download_favorite_to_cache(self.current_url, self.current_title),
            self.loop
        )
        return True

    def remove_from_favorites(self, url):
        fav = next((f for f in self.favorites if f.get('url') == url), None)
        title = fav.get('title') if fav else None
        self.favorites = [f for f in self.favorites if f.get('url') != url]
        self.save_favorites()
        try:
            cache_path = self.get_cached_file_path(url, title)
            if os.path.exists(cache_path):
                os.remove(cache_path)
                logger.info(f"🗑 Cache dosyası silindi")
        except Exception as e:
            logger.error(f"Cache silme hatası: {e}")

    async def check_favorites_cache(self):
        if not self.favorites:
            return
        logger.info(f"🔍 Favoriler kontrol ediliyor ({len(self.favorites)} adet)...")
        missing_count = 0
        cached_count = 0
        for fav in self.favorites:
            url = fav.get('url')
            title = fav.get('title')
            if not url or not title:
                continue
            if self.is_favorite_cached(url, title):
                cached_count += 1
            else:
                missing_count += 1
                await self.download_favorite_to_cache(url, title)
        if missing_count > 0:
            logger.info(f"✅ Cache hazır: {cached_count} mevcut, {missing_count} indirildi")

    async def on_ready(self):
        print(f"\n⚡ SİSTEM HAZIR: {self.user}\n")
        await self.update_presence()
        if not self._cache_check_done:
            self._cache_check_done = True
            asyncio.create_task(self.check_favorites_cache())
    
    async def update_presence(self, status_text=None):
        try:
            if status_text is None:
                status_text = self.current_title if self.current_title != "Beklemede..." else "Beklemede..."
            if len(status_text) > 100:
                status_text = status_text[:97] + "..."
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.listening,
                    name=status_text
                )
            )
        except Exception as e:
            logger.error(f"Durum güncelleme hatası: {e}")

    async def play_from_cache(self, url, title, duration, start_sec=0):
        try:
            cache_path = self.get_cached_file_path(url, title)
            if not os.path.exists(cache_path):
                logger.warning(f"Cache dosyası bulunamadı, stream'e geçiliyor")
                return await self.play_music(url, start_sec)
            if not self.voice_client or not self.voice_client.is_connected():
                owner_id = CONFIG.get('OWNER_ID', '')
                if owner_id:
                    logger.info("Bot bağlı değil, otomatik katılıyor...")
                    channel_name = await self.join_user_channel(owner_id)
                    if not channel_name:
                        logger.error("Kullanıcı ses kanalında değil!")
                        return None
                else:
                    logger.error("OWNER_ID config'de tanımlı değil!")
                    return None
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self._manual_stop = True
                self.voice_client.stop()
                await asyncio.sleep(0.5)
                self._manual_stop = False
            self.current_title = title
            self.current_url = url
            self.duration = duration
            self.start_offset = start_sec
            self.accumulated_time = 0
            self.is_playing_from_cache = True
            logger.info(f"Cache'den oynatılıyor: {title} (başlangıç: {start_sec}s)")
            def after_playing(error):
                if error: logger.error(f"HATA: {error}")
                if self._manual_stop: return
                if self.loop_mode and self.current_data:
                    asyncio.run_coroutine_threadsafe(self._play_url(self.current_data), self.loop)
                elif self.queue:
                    next_song = self.queue.pop(0)
                    asyncio.run_coroutine_threadsafe(self._play_url(next_song), self.loop)
                else:
                    self.current_title = "Beklemede..."
                    self.current_url = None
                    self.duration = 0
                    self.start_offset = 0
                    self.accumulated_time = 0
                    self.current_data = None
                    self.is_playing_from_cache = False
                    asyncio.run_coroutine_threadsafe(self.update_presence(), self.loop)
            before_args = f'-ss {start_sec}' if start_sec > 0 else ''
            if before_args:
                source = discord.FFmpegPCMAudio(cache_path, executable=FFMPEG_PATH, before_options=before_args, options=FFMPEG_OPTIONS['options'])
            else:
                source = discord.FFmpegPCMAudio(cache_path, executable=FFMPEG_PATH, options=FFMPEG_OPTIONS['options'])
            source = discord.PCMVolumeTransformer(source)
            source.volume = self.volume
            self.voice_client.play(source, after=after_playing)
            self.playback_start_time = time.time()
            await self.update_presence(title)
            return title
        except Exception as e:
            logger.error(f"Cache oynatma hatası: {e}")
            self.is_playing_from_cache = False
            return None

    async def join_user_channel(self, user_id):
        if not self.is_ready(): await self.wait_until_ready()
        for guild in self.guilds:
            member = guild.get_member(int(user_id))
            if member and member.voice:
                channel = member.voice.channel
                if self.voice_client and self.voice_client.is_connected():
                    await self.voice_client.move_to(channel)
                else:
                    self.voice_client = await channel.connect()
                return channel.name
        return None

    async def play_music(self, query, start_sec=0):
        async with self.play_lock:
            if not self.voice_client or not self.voice_client.is_connected():
                owner_id = CONFIG.get('OWNER_ID', '')
                if owner_id:
                    logger.info("Bot bağlı değil, otomatik katlıyor...")
                    channel_name = await self.join_user_channel(owner_id)
                    if not channel_name:
                        logger.error("Kullanıcı ses kanalında değil!")
                        return None
                else:
                    logger.error("OWNER_ID config'de tanımlı değil!")
                    return None
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self._manual_stop = True
                self.voice_client.stop()
                await asyncio.sleep(0.5)
                self._manual_stop = False
            self.start_offset = start_sec
            self.accumulated_time = 0
            try:
                loop = asyncio.get_event_loop()
                search_str = query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}"
                logger.info(f"Yükleniyor: {query}")
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    data = await loop.run_in_executor(None, lambda: ydl.extract_info(search_str, download=False))
                if 'entries' in data:
                    if not data['entries'] or len(data['entries']) == 0:
                        logger.error("Arama sonuç bulunamadı!")
                        return None
                    data = data['entries'][0]
                if not data or 'url' not in data:
                    logger.error("Geçersiz video verisi!")
                    return None
                return await self._play_url(data, start_sec)
            except Exception as e:
                logger.error(f"HATA: {e}")
                self._manual_stop = False
                return None

    async def _play_url(self, data, start_sec=0):
        self.current_data = data
        stream_url = data['url']
        self.current_title = data.get('title', 'Bilinmiyor')
        self.current_url = data.get('webpage_url', None)
        self.duration = data.get('duration', 0)
        self.is_playing_from_cache = False
        header_str = "".join([f"{k}: {v}\r\n" for k, v in data.get('http_headers', {}).items()])
        before_args = FFMPEG_OPTIONS['before_options'] + f' -headers "{header_str}" -ss {start_sec}'
        def after_playing(error):
            if error: logger.error(f"HATA: {error}")
            if self._manual_stop: return
            if self.loop_mode and self.current_data:
                asyncio.run_coroutine_threadsafe(self._play_url(self.current_data), self.loop)
            elif self.queue:
                next_song = self.queue.pop(0)
                asyncio.run_coroutine_threadsafe(self._play_url(next_song), self.loop)
            else:
                self.current_title = "Beklemede..."
                self.current_url = None
                self.duration = 0
                self.start_offset = 0
                self.accumulated_time = 0
                self.current_data = None
                asyncio.run_coroutine_threadsafe(self.update_presence(), self.loop)
        source = discord.FFmpegPCMAudio(stream_url, executable=FFMPEG_PATH, before_options=before_args, options=FFMPEG_OPTIONS['options'])
        source = discord.PCMVolumeTransformer(source)
        source.volume = self.volume
        self.voice_client.play(source, after=after_playing)
        self.playback_start_time = time.time()
        await self.update_presence(self.current_title)
        return self.current_title

    async def skip_track(self):
        if self.voice_client and self.voice_client.is_playing():
            old_loop = self.loop_mode
            self.loop_mode = False 
            self.voice_client.stop()
            self.loop_mode = old_loop

    async def add_to_queue(self, query):
        try:
            loop = asyncio.get_event_loop()
            search_str = query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}"
            logger.info(f"Sıraya ekleniyor: {query}")
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                data = await loop.run_in_executor(None, lambda: ydl.extract_info(search_str, download=False))
            if 'entries' in data:
                if not data['entries'] or len(data['entries']) == 0:
                    logger.error("Arama sonuç bulunamadı!")
                    return None
                data = data['entries'][0]
            if not data or 'url' not in data:
                logger.error("Geçersiz video verisi!")
                return None
            self.queue.append(data)
            title = data.get('title', 'Bilinmiyor')
            logger.info(f"✓ Sıraya eklendi: {title}")
            short_title = title[:40] + "..." if len(title) > 40 else title
            return f"Sırada #{len(self.queue)}: {short_title}"
        except Exception as e:
            logger.error(f"Sıraya ekleme hatası: {e}")
            return None

    def get_elapsed_time(self):
        elapsed = self.accumulated_time + self.start_offset
        if self.voice_client and self.voice_client.is_playing():
            elapsed += (time.time() - self.playback_start_time)
        return int(elapsed)

    def pause_music(self):
        if self.voice_client and self.voice_client.is_playing():
            self.accumulated_time += (time.time() - self.playback_start_time)
            self.voice_client.pause()

    def resume_music(self):
        if self.voice_client and self.voice_client.is_paused():
            self.playback_start_time = time.time()
            self.voice_client.resume()

    async def set_volume(self, volume):
        self.volume = volume
        if self.voice_client and self.voice_client.source:
            self.voice_client.source.volume = volume

    async def speak_text(self, text, language='auto', gender='female'):
        try:
            if not self.voice_client or not self.voice_client.is_connected():
                owner_id = CONFIG.get('OWNER_ID', '')
                if owner_id:
                    channel_name = await self.join_user_channel(owner_id)
                    if not channel_name:
                        logger.error("Kullanıcı ses kanalında değil!")
                        return False
                else:
                    logger.error("OWNER_ID config'de tanımlı değil!")
                    return False
            if not self.voice_client or not self.voice_client.is_connected():
                logger.error("Voice client bağlı değil!")
                return False
            was_playing = self.voice_client.is_playing()
            was_paused = self.voice_client.is_paused()
            saved_url = self.current_url
            saved_title = self.current_title
            saved_duration = self.duration
            saved_elapsed = self.get_elapsed_time() if (was_playing or was_paused) else 0
            saved_is_cache = self.is_playing_from_cache
            if was_playing or was_paused:
                self._manual_stop = True
                self.voice_client.stop()
                await asyncio.sleep(0.5)
                self._manual_stop = False
            voice_tr_female = CONFIG.get('TTS', {}).get('VOICE_TR', "tr-TR-EmelNeural")
            voice_en_female = CONFIG.get('TTS', {}).get('VOICE_EN', "en-US-AriaNeural")
            voice_tr_male = CONFIG.get('TTS', {}).get('VOICE_TR_MALE', "tr-TR-AhmetNeural")
            voice_en_male = CONFIG.get('TTS', {}).get('VOICE_EN_MALE', "en-US-GuyNeural")
            target_voice_tr = voice_tr_male if gender == 'male' else voice_tr_female
            target_voice_en = voice_en_male if gender == 'male' else voice_en_female
            if language == 'auto':
                turkish_chars = set('çğıöşüÇĞİÖŞÜ')
                if any(char in text for char in turkish_chars):
                    voice = target_voice_tr
                else:
                    voice = target_voice_en
            elif language == 'tr':
                voice = target_voice_tr
            else:
                voice = target_voice_en
            temp_file = os.path.join(tempfile.gettempdir(), f"tts_{int(time.time())}.mp3")
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(temp_file)
            if not os.path.exists(temp_file):
                logger.error("TTS dosyası oluşturulamadı!")
                return False
            def after_playing(error):
                if error:
                    logger.error(f"TTS Oynatma Hatası: {error}")
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as e:
                    logger.error(f"Dosya silme hatası: {e}")
                if saved_url and was_playing:
                    if saved_is_cache and self.is_favorite_cached(saved_url, saved_title):
                        asyncio.run_coroutine_threadsafe(
                            self.play_from_cache(saved_url, saved_title, saved_duration, start_sec=saved_elapsed),
                            self.loop
                        )
                    else:
                        asyncio.run_coroutine_threadsafe(
                            self.play_music(saved_url, start_sec=saved_elapsed),
                            self.loop
                        )
                self._manual_stop = False
            source = discord.FFmpegPCMAudio(temp_file, executable=FFMPEG_PATH)
            source = discord.PCMVolumeTransformer(source)
            source.volume = self.volume
            self.voice_client.play(source, after=after_playing)
            await asyncio.sleep(0.3)
            if self.voice_client.is_playing():
                return True
            else:
                logger.error("TTS başlatılamadı")
                return False
        except Exception as e:
            logger.error(f"TTS Hatası: {e}")
            return False

bot = MusicBot()

def run_bot_thread():
    bot.run(TOKEN)

class MediaKeyListener:
    def __init__(self, app_instance):
        self.app = app_instance
        self.listener = None
        self.last_press_time = 0
        self.debounce_delay = 0.2
        hotkey_name = CONFIG.get('HOTKEY', 'home').lower()
        key_map = {
            'home': Key.home,
            'end': Key.end,
            'insert': Key.insert,
            'page_down': Key.page_down,
            'page_up': Key.page_up,
            'delete': Key.delete,
            'f1': Key.f1,
            'f2': Key.f2,
            'f3': Key.f3,
            'f4': Key.f4,
            'f5': Key.f5,
            'f6': Key.f6,
            'f7': Key.f7,
            'f8': Key.f8,
            'f9': Key.f9,
            'f10': Key.f10,
            'f11': Key.f11,
            'f12': Key.f12,
        }
        self.hotkey = key_map.get(hotkey_name, Key.home)
        logger.info(f"🎹 Hotkey ayarlandı: {hotkey_name.upper()}")
        
    def on_press(self, key):
        try:
            if key == self.hotkey:
                current_time = time.time()
                if current_time - self.last_press_time < self.debounce_delay:
                    return
                self.last_press_time = current_time
                logger.info("⏯ Hotkey: Play/Pause")
                if bot.voice_client:
                    if bot.voice_client.is_playing():
                        bot.pause_music()
                        self.app.update_play_button_state("▶")
                    elif bot.voice_client.is_paused():
                        bot.resume_music()
                        self.app.update_play_button_state("⏸")
        except AttributeError:
            pass
    
    def start(self):
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()
        logger.info("⌨️ Medya tuşu dinleyicisi başlatıldı")
    
    def stop(self):
        if self.listener:
            self.listener.stop()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Senfoni")
        self.geometry("850x650")
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")
        self.colors = {
            'bg': '#0a0a0a',
            'sidebar': '#141414',
            'card': '#1a1a1a',
            'accent': '#ffffff',
            'accent_dim': '#888888',
            'button': '#252525',
            'button_hover': '#303030'
        }
        self.configure(fg_color=self.colors['bg'])
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=self.colors['sidebar'])
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="♪ SENFONİ", 
                                       font=ctk.CTkFont(size=20, weight="bold"),
                                       text_color=self.colors['accent'])
        self.logo_label.grid(row=0, column=0, padx=20, pady=(25, 10))
        self.sidebar_button_1 = ctk.CTkButton(self.sidebar_frame, text="Bağlan", 
                                             command=self.join_voice,
                                             fg_color=self.colors['button'],
                                             hover_color=self.colors['button_hover'],
                                             border_width=0,
                                             height=32,
                                             corner_radius=6)
        self.sidebar_button_1.grid(row=1, column=0, padx=20, pady=10)
        self.lbl_status = ctk.CTkLabel(self.sidebar_frame, text="Çevrimdışı", 
                                      text_color=self.colors['accent_dim'], 
                                      wraplength=180,
                                      font=ctk.CTkFont(size=10))
        self.lbl_status.grid(row=2, column=0, padx=20, pady=(0, 15))
        self.lbl_queue_title = ctk.CTkLabel(self.sidebar_frame, text="SIRA", 
                                           font=ctk.CTkFont(size=10, weight="bold"),
                                           text_color=self.colors['accent_dim'])
        self.lbl_queue_title.grid(row=3, column=0, padx=20, pady=(10, 5), sticky="w")
        self.queue_textbox = ctk.CTkTextbox(self.sidebar_frame, height=130, width=180, 
                                           fg_color=self.colors['bg'],
                                           border_width=1,
                                           border_color=self.colors['button'],
                                           corner_radius=6,
                                           cursor="hand2")
        self.queue_textbox.grid(row=4, column=0, padx=20, pady=(0, 12))
        self.queue_textbox.configure(state="disabled")
        self.lbl_fav_title = ctk.CTkLabel(self.sidebar_frame, text="FAVORİLER", 
                                         font=ctk.CTkFont(size=10, weight="bold"),
                                         text_color=self.colors['accent_dim'])
        self.lbl_fav_title.grid(row=5, column=0, padx=20, pady=(5, 5), sticky="w")
        self.fav_textbox = ctk.CTkTextbox(self.sidebar_frame, height=110, width=180, 
                                         fg_color=self.colors['bg'],
                                         border_width=1,
                                         border_color=self.colors['button'],
                                         corner_radius=6,
                                         font=ctk.CTkFont(family="Consolas", size=10),
                                         wrap="none",
                                         cursor="hand2")
        self.fav_textbox.grid(row=6, column=0, padx=20, pady=(0, 12))
        self.fav_textbox.configure(state="disabled")
        self.fav_textbox.bind("<Button-1>", self.on_favorite_click)
        self.fav_textbox.bind("<Button-3>", self.on_favorite_click)
        self.lbl_vol = ctk.CTkLabel(self.sidebar_frame, text="SES", 
                                   font=ctk.CTkFont(size=10, weight="bold"),
                                   text_color=self.colors['accent_dim'])
        self.lbl_vol.grid(row=7, column=0, padx=20, pady=(5, 5), sticky="w")
        self.slider_vol = ctk.CTkSlider(self.sidebar_frame, from_=0, to=1, 
                                       command=self.change_volume,
                                       fg_color=self.colors['button'],
                                       progress_color=self.colors['accent'],
                                       button_color=self.colors['accent'],
                                       button_hover_color=self.colors['accent_dim'],
                                       height=14)
        self.slider_vol.grid(row=8, column=0, padx=20, pady=(0, 20))
        self.slider_vol.set(1.0)
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=self.colors['bg'])
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_rowconfigure(2, weight=1)
        self.entry_search = ctk.CTkEntry(self.main_frame, 
                                        placeholder_text="Şarkı ara, YouTube/Instagram linki...", 
                                        height=42,
                                        fg_color=self.colors['card'],
                                        border_width=0,
                                        corner_radius=8,
                                        font=ctk.CTkFont(size=13))
        self.entry_search.pack(fill="x", pady=(0, 12))
        self.entry_search.bind("<Return>", lambda e: self.play_track())
        self.search_btn_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.search_btn_frame.pack(fill="x", pady=(0, 18))
        self.btn_search = ctk.CTkButton(self.search_btn_frame, text="▶ OYNAT", 
                                       fg_color=self.colors['accent'], 
                                       hover_color=self.colors['accent_dim'],
                                       text_color="#000000",
                                       height=38,
                                       corner_radius=8,
                                       font=ctk.CTkFont(size=13, weight="bold"),
                                       command=self.play_track)
        self.btn_search.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_add_queue = ctk.CTkButton(self.search_btn_frame, text="+ SIRAYA EKLE", 
                                          fg_color=self.colors['button'], 
                                          hover_color=self.colors['button_hover'],
                                          text_color=self.colors['accent'],
                                          border_width=0,
                                          height=38,
                                          corner_radius=8,
                                          font=ctk.CTkFont(size=12),
                                          command=self.add_to_queue)
        self.btn_add_queue.pack(side="right", fill="x", expand=True, padx=(6, 0))
        self.track_card = ctk.CTkFrame(self.main_frame, fg_color=self.colors['card'], corner_radius=10)
        self.track_card.pack(fill="both", expand=True)
        self.lbl_playing = ctk.CTkLabel(self.track_card, text="NOW PLAYING", 
                                       font=ctk.CTkFont(size=10, weight="bold"),
                                       text_color=self.colors['accent_dim'])
        self.lbl_playing.pack(pady=(25, 5))
        self.lbl_title = ctk.CTkLabel(self.track_card, text="---", 
                                     font=ctk.CTkFont(size=19, weight="bold"), 
                                     wraplength=450,
                                     text_color=self.colors['accent'])
        self.lbl_title.pack(pady=(5, 12))
        self.lbl_timer = ctk.CTkLabel(self.track_card, text="00:00 / 00:00", 
                                     font=ctk.CTkFont(family="Consolas", size=12),
                                     text_color=self.colors['accent_dim'])
        self.lbl_timer.pack(pady=(0, 10))
        self.slider_seek = ctk.CTkSlider(self.track_card, from_=0, to=100, 
                                        command=self.on_seek_drag, 
                                        height=5,
                                        fg_color=self.colors['button'],
                                        progress_color=self.colors['accent'],
                                        button_color=self.colors['accent'],
                                        button_hover_color=self.colors['accent_dim'])
        self.slider_seek.pack(fill="x", padx=45, pady=(0, 22))
        self.slider_seek.bind("<Button-1>", lambda e: setattr(self, 'is_seeking', True))
        self.slider_seek.bind("<ButtonRelease-1>", self.on_seek_release)
        self.is_seeking = False
        self.controls_frame = ctk.CTkFrame(self.track_card, fg_color="transparent")
        self.controls_frame.pack(pady=(0, 25))
        self.btn_play = ctk.CTkButton(self.controls_frame, text="▶", 
                                     width=52, height=52, 
                                     fg_color=self.colors['accent'], 
                                     hover_color=self.colors['accent_dim'],
                                     text_color="#000000",
                                     corner_radius=26,
                                     font=ctk.CTkFont(size=16),
                                     command=self.toggle_pause)
        self.btn_play.pack(side="left", padx=10)
        self.btn_skip = ctk.CTkButton(self.controls_frame, text="⏭", 
                                     width=40, height=40, 
                                     fg_color=self.colors['button'], 
                                     hover_color=self.colors['button_hover'],
                                     text_color=self.colors['accent'],
                                     corner_radius=20,
                                     font=ctk.CTkFont(size=14),
                                     command=self.skip_track)
        self.btn_skip.pack(side="left", padx=6)
        self.btn_favorite = ctk.CTkButton(self.controls_frame, text="⭐", 
                                         width=40, height=40,
                                         fg_color=self.colors['button'], 
                                         hover_color=self.colors['button_hover'],
                                         text_color="#FFD700",
                                         corner_radius=20,
                                         font=ctk.CTkFont(size=14),
                                         command=self.toggle_favorite)
        self.btn_favorite.pack(side="left", padx=6)
        self.switch_loop = ctk.CTkSwitch(self.controls_frame, text="Döngü", 
                                        command=self.toggle_loop,
                                        fg_color=self.colors['button'],
                                        progress_color=self.colors['accent'],
                                        button_color=self.colors['accent'],
                                        button_hover_color=self.colors['accent_dim'],
                                        text_color=self.colors['accent_dim'],
                                        font=ctk.CTkFont(size=11))
        self.switch_loop.pack(side="left", padx=12)
        self.tts_card = ctk.CTkFrame(self.main_frame, fg_color=self.colors['card'], corner_radius=10, height=170)
        self.tts_card.pack(fill="x", pady=(15, 0))
        self.tts_card.pack_propagate(False)
        self.lbl_tts_title = ctk.CTkLabel(self.tts_card, text="🗣️ TEXT-TO-SPEECH", 
                                         font=ctk.CTkFont(size=10, weight="bold"),
                                         text_color=self.colors['accent_dim'])
        self.lbl_tts_title.pack(pady=(15, 8))
        self.entry_tts = ctk.CTkEntry(self.tts_card, 
                                     placeholder_text="Seslendirilecek metni yazın...", 
                                     height=36,
                                     fg_color=self.colors['bg'],
                                     border_width=1,
                                     border_color=self.colors['button'],
                                     corner_radius=6,
                                     font=ctk.CTkFont(size=12))
        self.entry_tts.pack(fill="x", padx=25, pady=(0, 10))
        self.entry_tts.bind("<Return>", lambda e: self.speak_text())
        self.tts_control_frame = ctk.CTkFrame(self.tts_card, fg_color="transparent")
        self.tts_control_frame.pack(fill="x", padx=25, pady=(0, 15))
        self.tts_lang_var = ctk.StringVar(value="auto")
        self.radio_auto = ctk.CTkRadioButton(self.tts_control_frame, text="Otomatik", 
                                            variable=self.tts_lang_var, value="auto",
                                            fg_color=self.colors['accent'],
                                            hover_color=self.colors['accent_dim'],
                                            text_color=self.colors['accent_dim'],
                                            font=ctk.CTkFont(size=10))
        self.radio_auto.pack(side="left", padx=(0, 10))
        self.radio_tr = ctk.CTkRadioButton(self.tts_control_frame, text="🇹🇷 Türkçe", 
                                          variable=self.tts_lang_var, value="tr",
                                          fg_color=self.colors['accent'],
                                          hover_color=self.colors['accent_dim'],
                                          text_color=self.colors['accent_dim'],
                                          font=ctk.CTkFont(size=10))
        self.radio_tr.pack(side="left", padx=10)
        self.radio_en = ctk.CTkRadioButton(self.tts_control_frame, text="🇺🇸 İngilizce", 
                                          variable=self.tts_lang_var, value="en",
                                          fg_color=self.colors['accent'],
                                          hover_color=self.colors['accent_dim'],
                                          text_color=self.colors['accent_dim'],
                                          font=ctk.CTkFont(size=10))
        self.radio_en.pack(side="left", padx=10)
        self.switch_male_voice = ctk.CTkSwitch(self.tts_control_frame, text="Erkek Sesi", 
                                              progress_color=self.colors['accent'],
                                              button_color=self.colors['accent'],
                                              button_hover_color=self.colors['accent_dim'],
                                              text_color=self.colors['accent_dim'],
                                              font=ctk.CTkFont(size=10))
        self.switch_male_voice.pack(side="left", padx=10)
        self.btn_speak = ctk.CTkButton(self.tts_control_frame, text="🔊", 
                                      width=32,
                                      fg_color=self.colors['accent'], 
                                      hover_color=self.colors['accent_dim'],
                                      text_color="#000000",
                                      height=32,
                                      corner_radius=6,
                                      font=ctk.CTkFont(size=16),
                                      command=self.speak_text)
        self.btn_speak.pack(side="right", padx=(15, 0))
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.media_listener = MediaKeyListener(self)
        self.media_listener.start()

    def update_play_button_state(self, state):
        try:
            self.after(0, lambda: self.btn_play.configure(text=state))
        except Exception as e:
            logger.error(f"Buton güncelleme hatası: {e}")
    
    def update_ui_loop(self):
        try:
            if bot.voice_client:
                if bot.voice_client.is_playing():
                    if self.btn_play.cget("text") != "⏸":
                        self.btn_play.configure(text="⏸")
                elif bot.voice_client.is_paused():
                    if self.btn_play.cget("text") != "▶":
                        self.btn_play.configure(text="▶")
                else:
                    if self.btn_play.cget("text") != "▶":
                        self.btn_play.configure(text="▶")
            if bot.voice_client and bot.voice_client.is_playing() and not self.is_seeking:
                elapsed = bot.get_elapsed_time()
                total = bot.duration
                if total > 0:
                    self.slider_seek.set((elapsed / total) * 100)
                    e_m, e_s = divmod(elapsed, 60)
                    t_m, t_s = divmod(total, 60)
                    self.lbl_timer.configure(text=f"{e_m:02d}:{e_s:02d} / {t_m:02d}:{t_s:02d}")
            title_text = bot.current_title[:60] + "..." if len(bot.current_title) > 60 else bot.current_title
            self.lbl_title.configure(text=title_text)
            self.update_queue_display()
            self.update_favorites_display()
        except: pass
        self.after(1000, self.update_ui_loop)

    def update_queue_display(self):
        self.queue_textbox.configure(state="normal")
        self.queue_textbox.delete("1.0", "end")
        if not bot.queue:
            self.queue_textbox.insert("1.0", "Sıra boş")
        else:
            for i, song_data in enumerate(bot.queue, 1):
                title = song_data.get('title', 'Bilinmiyor')[:35]
                self.queue_textbox.insert("end", f"{i}. {title}\n")
        self.queue_textbox.configure(state="disabled")

    def update_favorites_display(self):
        try:
            scroll_pos = self.fav_textbox.yview()
        except:
            scroll_pos = None
        self.fav_textbox.configure(state="normal")
        self.fav_textbox.delete("1.0", "end")
        if not bot.favorites:
            self.fav_textbox.insert("1.0", "Favori yok\n\nÇalan şarkıyı ⭐ ile ekle")
        else:
            for i, fav in enumerate(bot.favorites, 1):
                title = fav.get('title', 'Bilinmiyor')[:30]
                self.fav_textbox.insert("end", f"{i:2d}. {title}\n")
        self.fav_textbox.configure(state="disabled")
        if scroll_pos:
            try:
                self.fav_textbox.yview_moveto(scroll_pos[0])
            except:
                pass

    def on_favorite_click(self, event):
        try:
            if not bot.favorites:
                return
            index = self.fav_textbox.index("@%s,%s" % (event.x, event.y))
            line_num = int(index.split('.')[0]) - 1
            if line_num < 0 or line_num >= len(bot.favorites):
                return
            fav = bot.favorites[line_num]
            url = fav.get('url')
            title = fav.get('title', 'Bilinmiyor')
            duration = fav.get('duration', 0)
            if not url:
                return
            if event.num == 1:
                self.lbl_status.configure(text="Favoriden yükleniyor...", text_color="gold")
                if bot.is_favorite_cached(url, title):
                    asyncio.run_coroutine_threadsafe(
                        self.play_from_cache_task(url, title, duration), 
                        bot.loop
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        self.update_info_task(url), 
                        bot.loop
                    )
            elif event.num == 3:
                self.show_favorite_context_menu(event, line_num, url, title)
        except ValueError as e:
            pass
        except Exception as e:
            logger.error(f"Favori tıklama hatası: {e}")
    
    def show_favorite_context_menu(self, event, line_num, url, title):
        try:
            context_menu = tk.Menu(self, tearoff=0, 
                                  bg=self.colors['card'], 
                                  fg=self.colors['accent'],
                                  activebackground=self.colors['accent'],
                                  activeforeground='#000000',
                                  borderwidth=0,
                                  relief='flat')
            context_menu.add_command(
                label="📝 İsim Değiştir",
                command=lambda: self.rename_favorite(line_num, url, title)
            )
            context_menu.add_separator()
            context_menu.add_command(
                label="🗑️ Sil",
                command=lambda: self.delete_favorite(url, title)
            )
            context_menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            logger.error(f"Context menu hatası: {e}")
        finally:
            try:
                context_menu.grab_release()
            except:
                pass
    
    def rename_favorite(self, line_num, url, old_title):
        try:
            dialog = ctk.CTkInputDialog(
                text=f"Yeni isim girin:\n\nEski: {old_title[:50]}...",
                title="İsim Değiştir"
            )
            new_title = dialog.get_input()
            if new_title and new_title.strip():
                if 0 <= line_num < len(bot.favorites):
                    bot.favorites[line_num]['title'] = new_title.strip()
                    bot.save_favorites()
                    old_cache_path = bot.get_cached_file_path(url, old_title)
                    new_cache_path = bot.get_cached_file_path(url, new_title)
                    if os.path.exists(old_cache_path) and old_cache_path != new_cache_path:
                        try:
                            os.rename(old_cache_path, new_cache_path)
                            logger.info(f"📝 Cache dosyası yeniden adlandırıldı")
                        except Exception as e:
                            logger.warning(f"Cache yeniden adlandırma hatası: {e}")
                    self.lbl_status.configure(text="İsim değiştirildi", text_color="green")
                    logger.info(f"Favori yeniden adlandırıldı: {old_title} → {new_title}")
        except Exception as e:
            logger.error(f"İsim değiştirme hatası: {e}")
    
    def delete_favorite(self, url, title):
        try:
            bot.remove_from_favorites(url)
            self.lbl_status.configure(text="Favorilerden silindi", text_color="orange")
            logger.info(f"🗑 Favoriden silindi: {title}")
        except Exception as e:
            logger.error(f"Silme hatası: {e}")

    def toggle_favorite(self):
        if bot.add_to_favorites():
            self.lbl_status.configure(text="⭐ Favorilere eklendi", text_color="gold")
        else:
            self.lbl_status.configure(text="Zaten favorilerde", text_color="orange")

    def on_seek_drag(self, value):
        if bot.duration > 0:
            elapsed = int((value / 100) * bot.duration)
            e_m, e_s = divmod(elapsed, 60)
            self.lbl_timer.configure(text=f"{e_m:02d}:{e_s:02d} / --:--")

    def on_seek_release(self, event):
        value = self.slider_seek.get()
        if bot.current_url and bot.duration > 0:
            target_sec = int((value / 100) * bot.duration)
            if bot.is_playing_from_cache and bot.is_favorite_cached(bot.current_url, bot.current_title):
                fav = next((f for f in bot.favorites if f.get('url') == bot.current_url), None)
                if fav:
                    asyncio.run_coroutine_threadsafe(
                        bot.play_from_cache(bot.current_url, fav.get('title'), fav.get('duration', 0), start_sec=target_sec),
                        bot.loop
                    )
                else:
                    asyncio.run_coroutine_threadsafe(bot.play_music(bot.current_url, start_sec=target_sec), bot.loop)
            else:
                asyncio.run_coroutine_threadsafe(bot.play_music(bot.current_url, start_sec=target_sec), bot.loop)
        self.after(500, lambda: setattr(self, 'is_seeking', False))

    def change_volume(self, value):
        asyncio.run_coroutine_threadsafe(bot.set_volume(value), bot.loop)

    def toggle_pause(self):
        if self.btn_play.cget("text") == "⏸": 
            self.btn_play.configure(text="▶")
            bot.pause_music()
        else:
            self.btn_play.configure(text="⏸")
            bot.resume_music()

    def toggle_loop(self):
        bot.loop_mode = bool(self.switch_loop.get())

    def stop_track(self):
        if bot.voice_client:
            bot._manual_stop = True
            bot.voice_client.stop()
            bot.current_url = None
            threading.Timer(1.0, lambda: setattr(bot, '_manual_stop', False)).start()
        self.btn_play.configure(text="▶")
        self.slider_seek.set(0)
        self.lbl_timer.configure(text="00:00 / 00:00")

    def skip_track(self):
        asyncio.run_coroutine_threadsafe(bot.skip_track(), bot.loop)

    def join_voice(self):
        owner_id = CONFIG.get('OWNER_ID', "")
        self.lbl_status.configure(text="Aranıyor...", text_color="orange")
        asyncio.run_coroutine_threadsafe(self.update_join_task(owner_id), bot.loop)

    async def update_join_task(self, user_id):
        name = await bot.join_user_channel(user_id)
        if name: 
            short_name = name[:25] + "..." if len(name) > 25 else name
            self.lbl_status.configure(text=f"Bağlı: {short_name}", text_color="#3B8ED0")
        else: 
            self.lbl_status.configure(text="Kanal bulunamadı", text_color="red")

    def add_to_queue(self):
        query = self.entry_search.get()
        if query:
            self.lbl_status.configure(text="Sıraya ekleniyor...", text_color="orange")
            asyncio.run_coroutine_threadsafe(self.update_queue_task(query), bot.loop)

    async def update_queue_task(self, query):
        result = await bot.add_to_queue(query)
        if result:
            short_result = result[:50] + "..." if len(result) > 50 else result
            self.lbl_status.configure(text=short_result, text_color="#3B8ED0")
        else:
            self.lbl_status.configure(text="Sıraya eklenemedi", text_color="red")

    def play_track(self):
        query = self.entry_search.get()
        if query:
            self.lbl_status.configure(text="Yükleniyor...", text_color=self.colors['accent_dim'])
            self.btn_play.configure(text="⏸")
            asyncio.run_coroutine_threadsafe(self.update_info_task(query), bot.loop)

    async def update_info_task(self, query):
        title = await bot.play_music(query)
        if title:
            self.lbl_status.configure(text="Oynatılıyor", text_color=self.colors['accent'])
        else:
            self.lbl_status.configure(text="Hata: Sonuç bulunamadı", text_color="#ff4444")
            self.btn_play.configure(text="▶")

    async def play_from_cache_task(self, url, title, duration):
        result = await bot.play_from_cache(url, title, duration)
        if result:
            self.lbl_status.configure(text="Cache'den oynatılıyor", text_color=self.colors['accent'])
            self.btn_play.configure(text="⏸")
        else:
            self.lbl_status.configure(text="Cache hatası", text_color="#ff4444")

    def speak_text(self):
        text = self.entry_tts.get().strip()
        if not text:
            self.lbl_status.configure(text="TTS: Metin giriniz", text_color="orange")
            return
        language = self.tts_lang_var.get()
        gender = 'male' if self.switch_male_voice.get() else 'female'
        self.lbl_status.configure(text=f"🗣️ Seslendiriliyor ({gender})...", text_color=self.colors['accent_dim'])
        asyncio.run_coroutine_threadsafe(self.speak_text_task(text, language, gender), bot.loop)

    async def speak_text_task(self, text, language, gender):
        success = await bot.speak_text(text, language, gender)
        if success:
            self.lbl_status.configure(text="✓ Seslendirildi", text_color=self.colors['accent'])
            self.entry_tts.delete(0, 'end')
        else:
            self.lbl_status.configure(text="TTS Hatası", text_color="#ff4444")

    def on_closing(self):
        try:
            if hasattr(self, 'media_listener'):
                self.media_listener.stop()
            if bot.voice_client: asyncio.run_coroutine_threadsafe(bot.voice_client.disconnect(), bot.loop)
            asyncio.run_coroutine_threadsafe(bot.close(), bot.loop)
        except: pass
        self.destroy()
        os._exit(0)

if __name__ == "__main__":
    t = threading.Thread(target=run_bot_thread, daemon=True)
    t.start()
    app = App()
    app.after(1000, app.update_ui_loop)
    app.mainloop()