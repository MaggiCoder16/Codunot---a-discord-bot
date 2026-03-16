import discord
from discord import app_commands
from discord.ext import commands
import os
import ssl
import subprocess
import time
import io
import json
import aiohttp
import asyncio
import random
import traceback
import tempfile
import re
from datetime import datetime, timezone
from typing import Optional
from collections import deque
from urllib.parse import urlparse, quote_plus, parse_qs

from bs4 import BeautifulSoup
import trafilatura

import wavelink
import yt_dlp

from memory import MemoryManager
from test_api import generate_image, ImageAPIError
import requests
from deAPI_client_text2vid import generate_video as text_to_video_512
from edge_tts_client import generate_tts_mp3
from deAPI_client_video_to_text import transcribe_video, wait_for_transcription_text, VideoToTextError
from google_ai_studio_client import call_google_ai_studio
from cerebras_client import call_cerebras
from tts_text_polisher import polish_text_for_tts

from usage_manager import (
	check_limit,
	check_total_limit,
	consume,
	consume_total,
	save_usage,
	get_tier_from_message,
)

from topgg_utils import has_voted
import playlist_manager

memory = None
channel_modes = {}
channel_chess = {}
user_vote_unlocks = {}
chess_engine = None
OWNER_IDS = set()
VOTE_DURATION = 12 * 60 * 60
BYPASS_IDS = {1220934047794987048, 1167443519070290051}
BOT_NAME = "Codunot"

EDGE_TTS_LANGUAGE_NAMES: dict[str, str] = {
	"af": "Afrikaans",
	"am": "Amharic",
	"ar": "Arabic",
	"az": "Azerbaijani",
	"bg": "Bulgarian",
	"bn": "Bengali",
	"bs": "Bosnian",
	"ca": "Catalan",
	"cs": "Czech",
	"cy": "Welsh",
	"da": "Danish",
	"de": "German",
	"el": "Greek",
	"en": "English",
	"es": "Spanish",
	"et": "Estonian",
	"fa": "Persian",
	"fi": "Finnish",
	"fil": "Filipino",
	"fr": "French",
	"ga": "Irish",
	"gl": "Galician",
	"gu": "Gujarati",
	"he": "Hebrew",
	"hi": "Hindi",
	"hr": "Croatian",
	"hu": "Hungarian",
	"id": "Indonesian",
	"is": "Icelandic",
	"it": "Italian",
	"iu": "Inuktitut",
	"ja": "Japanese",
	"jv": "Javanese",
	"ka": "Georgian",
	"kk": "Kazakh",
	"km": "Khmer",
	"kn": "Kannada",
	"ko": "Korean",
	"lo": "Lao",
	"lt": "Lithuanian",
	"lv": "Latvian",
	"mk": "Macedonian",
	"ml": "Malayalam",
	"mn": "Mongolian",
	"mr": "Marathi",
	"ms": "Malay",
	"mt": "Maltese",
	"my": "Burmese",
	"nb": "Norwegian Bokmål",
	"ne": "Nepali",
	"nl": "Dutch",
	"pl": "Polish",
	"ps": "Pashto",
	"pt": "Portuguese",
	"ro": "Romanian",
	"ru": "Russian",
	"si": "Sinhala",
	"sk": "Slovak",
	"sl": "Slovenian",
	"so": "Somali",
	"sq": "Albanian",
	"sr": "Serbian",
	"su": "Sundanese",
	"sv": "Swedish",
	"sw": "Swahili",
	"ta": "Tamil",
	"te": "Telugu",
	"th": "Thai",
	"tr": "Turkish",
	"uk": "Ukrainian",
	"ur": "Urdu",
	"uz": "Uzbek",
	"vi": "Vietnamese",
	"zh": "Chinese",
	"zu": "Zulu",
}

_EDGE_TTS_VOICE_CODES: list[str] = [
	"af-ZA-AdriNeural",
	"af-ZA-WillemNeural",
	"am-ET-AmehaNeural",
	"am-ET-MekdesNeural",
	"ar-AE-FatimaNeural",
	"ar-AE-HamdanNeural",
	"ar-BH-AliNeural",
	"ar-BH-LailaNeural",
	"ar-DZ-AminaNeural",
	"ar-DZ-IsmaelNeural",
	"ar-EG-SalmaNeural",
	"ar-EG-ShakirNeural",
	"ar-IQ-BasselNeural",
	"ar-IQ-RanaNeural",
	"ar-JO-SanaNeural",
	"ar-JO-TaimNeural",
	"ar-KW-FahedNeural",
	"ar-KW-NouraNeural",
	"ar-LB-LaylaNeural",
	"ar-LB-RamiNeural",
	"ar-LY-ImanNeural",
	"ar-LY-OmarNeural",
	"ar-MA-JamalNeural",
	"ar-MA-MounaNeural",
	"ar-OM-AbdullahNeural",
	"ar-OM-AyshaNeural",
	"ar-QA-AmalNeural",
	"ar-QA-MoazNeural",
	"ar-SA-HamedNeural",
	"ar-SA-ZariyahNeural",
	"ar-SY-AmanyNeural",
	"ar-SY-LaithNeural",
	"ar-TN-HediNeural",
	"ar-TN-ReemNeural",
	"ar-YE-MaryamNeural",
	"ar-YE-SalehNeural",
	"az-AZ-BabekNeural",
	"az-AZ-BanuNeural",
	"bg-BG-BorislavNeural",
	"bg-BG-KalinaNeural",
	"bn-BD-NabanitaNeural",
	"bn-BD-PradeepNeural",
	"bn-IN-BashkarNeural",
	"bn-IN-TanishaaNeural",
	"bs-BA-GoranNeural",
	"bs-BA-VesnaNeural",
	"ca-ES-EnricNeural",
	"ca-ES-JoanaNeural",
	"cs-CZ-AntoninNeural",
	"cs-CZ-VlastaNeural",
	"cy-GB-AledNeural",
	"cy-GB-NiaNeural",
	"da-DK-ChristelNeural",
	"da-DK-JeppeNeural",
	"de-AT-IngridNeural",
	"de-AT-JonasNeural",
	"de-CH-JanNeural",
	"de-CH-LeniNeural",
	"de-DE-AmalaNeural",
	"de-DE-ConradNeural",
	"de-DE-FlorianMultilingualNeural",
	"de-DE-KatjaNeural",
	"de-DE-KillianNeural",
	"de-DE-SeraphinaMultilingualNeural",
	"el-GR-AthinaNeural",
	"el-GR-NestorasNeural",
	"en-AU-NatashaNeural",
	"en-AU-WilliamMultilingualNeural",
	"en-CA-ClaraNeural",
	"en-CA-LiamNeural",
	"en-GB-LibbyNeural",
	"en-GB-MaisieNeural",
	"en-GB-RyanNeural",
	"en-GB-SoniaNeural",
	"en-GB-ThomasNeural",
	"en-HK-SamNeural",
	"en-HK-YanNeural",
	"en-IE-ConnorNeural",
	"en-IE-EmilyNeural",
	"en-IN-NeerjaExpressiveNeural",
	"en-IN-NeerjaNeural",
	"en-IN-PrabhatNeural",
	"en-KE-AsiliaNeural",
	"en-KE-ChilembaNeural",
	"en-NG-AbeoNeural",
	"en-NG-EzinneNeural",
	"en-NZ-MitchellNeural",
	"en-NZ-MollyNeural",
	"en-PH-JamesNeural",
	"en-PH-RosaNeural",
	"en-SG-LunaNeural",
	"en-SG-WayneNeural",
	"en-TZ-ElimuNeural",
	"en-TZ-ImaniNeural",
	"en-US-AnaNeural",
	"en-US-AndrewMultilingualNeural",
	"en-US-AndrewNeural",
	"en-US-AriaNeural",
	"en-US-AvaMultilingualNeural",
	"en-US-AvaNeural",
	"en-US-BrianMultilingualNeural",
	"en-US-BrianNeural",
	"en-US-ChristopherNeural",
	"en-US-EmmaMultilingualNeural",
	"en-US-EmmaNeural",
	"en-US-EricNeural",
	"en-US-GuyNeural",
	"en-US-JennyNeural",
	"en-US-MichelleNeural",
	"en-US-RogerNeural",
	"en-US-SteffanNeural",
	"en-ZA-LeahNeural",
	"en-ZA-LukeNeural",
	"es-AR-ElenaNeural",
	"es-AR-TomasNeural",
	"es-BO-MarceloNeural",
	"es-BO-SofiaNeural",
	"es-CL-CatalinaNeural",
	"es-CL-LorenzoNeural",
	"es-CO-GonzaloNeural",
	"es-CO-SalomeNeural",
	"es-CR-JuanNeural",
	"es-CR-MariaNeural",
	"es-CU-BelkysNeural",
	"es-CU-ManuelNeural",
	"es-DO-EmilioNeural",
	"es-DO-RamonaNeural",
	"es-EC-AndreaNeural",
	"es-EC-LuisNeural",
	"es-ES-AlvaroNeural",
	"es-ES-ElviraNeural",
	"es-ES-XimenaNeural",
	"es-GQ-JavierNeural",
	"es-GQ-TeresaNeural",
	"es-GT-AndresNeural",
	"es-GT-MartaNeural",
	"es-HN-CarlosNeural",
	"es-HN-KarlaNeural",
	"es-MX-DaliaNeural",
	"es-MX-JorgeNeural",
	"es-NI-FedericoNeural",
	"es-NI-YolandaNeural",
	"es-PA-MargaritaNeural",
	"es-PA-RobertoNeural",
	"es-PE-AlexNeural",
	"es-PE-CamilaNeural",
	"es-PR-KarinaNeural",
	"es-PR-VictorNeural",
	"es-PY-MarioNeural",
	"es-PY-TaniaNeural",
	"es-SV-LorenaNeural",
	"es-SV-RodrigoNeural",
	"es-US-AlonsoNeural",
	"es-US-PalomaNeural",
	"es-UY-MateoNeural",
	"es-UY-ValentinaNeural",
	"es-VE-PaolaNeural",
	"es-VE-SebastianNeural",
	"et-EE-AnuNeural",
	"et-EE-KertNeural",
	"fa-IR-DilaraNeural",
	"fa-IR-FaridNeural",
	"fi-FI-HarriNeural",
	"fi-FI-NooraNeural",
	"fil-PH-AngeloNeural",
	"fil-PH-BlessicaNeural",
	"fr-BE-CharlineNeural",
	"fr-BE-GerardNeural",
	"fr-CA-AntoineNeural",
	"fr-CA-JeanNeural",
	"fr-CA-SylvieNeural",
	"fr-CA-ThierryNeural",
	"fr-CH-ArianeNeural",
	"fr-CH-FabriceNeural",
	"fr-FR-DeniseNeural",
	"fr-FR-EloiseNeural",
	"fr-FR-HenriNeural",
	"fr-FR-RemyMultilingualNeural",
	"fr-FR-VivienneMultilingualNeural",
	"ga-IE-ColmNeural",
	"ga-IE-OrlaNeural",
	"gl-ES-RoiNeural",
	"gl-ES-SabelaNeural",
	"gu-IN-DhwaniNeural",
	"gu-IN-NiranjanNeural",
	"he-IL-AvriNeural",
	"he-IL-HilaNeural",
	"hi-IN-MadhurNeural",
	"hi-IN-SwaraNeural",
	"hr-HR-GabrijelaNeural",
	"hr-HR-SreckoNeural",
	"hu-HU-NoemiNeural",
	"hu-HU-TamasNeural",
	"id-ID-ArdiNeural",
	"id-ID-GadisNeural",
	"is-IS-GudrunNeural",
	"is-IS-GunnarNeural",
	"it-IT-DiegoNeural",
	"it-IT-ElsaNeural",
	"it-IT-GiuseppeMultilingualNeural",
	"it-IT-IsabellaNeural",
	"iu-Cans-CA-SiqiniqNeural",
	"iu-Cans-CA-TaqqiqNeural",
	"iu-Latn-CA-SiqiniqNeural",
	"iu-Latn-CA-TaqqiqNeural",
	"ja-JP-KeitaNeural",
	"ja-JP-NanamiNeural",
	"jv-ID-DimasNeural",
	"jv-ID-SitiNeural",
	"ka-GE-EkaNeural",
	"ka-GE-GiorgiNeural",
	"kk-KZ-AigulNeural",
	"kk-KZ-DauletNeural",
	"km-KH-PisethNeural",
	"km-KH-SreymomNeural",
	"kn-IN-GaganNeural",
	"kn-IN-SapnaNeural",
	"ko-KR-HyunsuMultilingualNeural",
	"ko-KR-InJoonNeural",
	"ko-KR-SunHiNeural",
	"lo-LA-ChanthavongNeural",
	"lo-LA-KeomanyNeural",
	"lt-LT-LeonasNeural",
	"lt-LT-OnaNeural",
	"lv-LV-EveritaNeural",
	"lv-LV-NilsNeural",
	"mk-MK-AleksandarNeural",
	"mk-MK-MarijaNeural",
	"ml-IN-MidhunNeural",
	"ml-IN-SobhanaNeural",
	"mn-MN-BataaNeural",
	"mn-MN-YesuiNeural",
	"mr-IN-AarohiNeural",
	"mr-IN-ManoharNeural",
	"ms-MY-OsmanNeural",
	"ms-MY-YasminNeural",
	"mt-MT-GraceNeural",
	"mt-MT-JosephNeural",
	"my-MM-NilarNeural",
	"my-MM-ThihaNeural",
	"nb-NO-FinnNeural",
	"nb-NO-PernilleNeural",
	"ne-NP-HemkalaNeural",
	"ne-NP-SagarNeural",
	"nl-BE-ArnaudNeural",
	"nl-BE-DenaNeural",
	"nl-NL-ColetteNeural",
	"nl-NL-FennaNeural",
	"nl-NL-MaartenNeural",
	"pl-PL-MarekNeural",
	"pl-PL-ZofiaNeural",
	"ps-AF-GulNawazNeural",
	"ps-AF-LatifaNeural",
	"pt-BR-AntonioNeural",
	"pt-BR-FranciscaNeural",
	"pt-BR-ThalitaMultilingualNeural",
	"pt-PT-DuarteNeural",
	"pt-PT-RaquelNeural",
	"ro-RO-AlinaNeural",
	"ro-RO-EmilNeural",
	"ru-RU-DmitryNeural",
	"ru-RU-SvetlanaNeural",
	"si-LK-SameeraNeural",
	"si-LK-ThiliniNeural",
	"sk-SK-LukasNeural",
	"sk-SK-ViktoriaNeural",
	"sl-SI-PetraNeural",
	"sl-SI-RokNeural",
	"so-SO-MuuseNeural",
	"so-SO-UbaxNeural",
	"sq-AL-AnilaNeural",
	"sq-AL-IlirNeural",
	"sr-RS-NicholasNeural",
	"sr-RS-SophieNeural",
	"su-ID-JajangNeural",
	"su-ID-TutiNeural",
	"sv-SE-MattiasNeural",
	"sv-SE-SofieNeural",
	"sw-KE-RafikiNeural",
	"sw-KE-ZuriNeural",
	"sw-TZ-DaudiNeural",
	"sw-TZ-RehemaNeural",
	"ta-IN-PallaviNeural",
	"ta-IN-ValluvarNeural",
	"ta-LK-KumarNeural",
	"ta-LK-SaranyaNeural",
	"ta-MY-KaniNeural",
	"ta-MY-SuryaNeural",
	"ta-SG-AnbuNeural",
	"ta-SG-VenbaNeural",
	"te-IN-MohanNeural",
	"te-IN-ShrutiNeural",
	"th-TH-NiwatNeural",
	"th-TH-PremwadeeNeural",
	"tr-TR-AhmetNeural",
	"tr-TR-EmelNeural",
	"uk-UA-OstapNeural",
	"uk-UA-PolinaNeural",
	"ur-IN-GulNeural",
	"ur-IN-SalmanNeural",
	"ur-PK-AsadNeural",
	"ur-PK-UzmaNeural",
	"uz-UZ-MadinaNeural",
	"uz-UZ-SardorNeural",
	"vi-VN-HoaiMyNeural",
	"vi-VN-NamMinhNeural",
	"zh-CN-XiaoxiaoNeural",
	"zh-CN-XiaoyiNeural",
	"zh-CN-YunjianNeural",
	"zh-CN-YunxiNeural",
	"zh-CN-YunxiaNeural",
	"zh-CN-YunyangNeural",
	"zh-CN-liaoning-XiaobeiNeural",
	"zh-CN-shaanxi-XiaoniNeural",
	"zh-HK-HiuGaaiNeural",
	"zh-HK-HiuMaanNeural",
	"zh-HK-WanLungNeural",
	"zh-TW-HsiaoChenNeural",
	"zh-TW-HsiaoYuNeural",
	"zh-TW-YunJheNeural",
	"zu-ZA-ThandoNeural",
	"zu-ZA-ThembaNeural",
]

EDGE_TTS_LANG_VOICES: dict[str, list[str]] = {}
for voice_code in _EDGE_TTS_VOICE_CODES:
	lang_code = voice_code.split("-", 1)[0]
	language_name = EDGE_TTS_LANGUAGE_NAMES.get(lang_code, lang_code)
	EDGE_TTS_LANG_VOICES.setdefault(language_name, []).append(voice_code)

EDGE_TTS_LANG_VOICES = dict(sorted(EDGE_TTS_LANG_VOICES.items(), key=lambda item: item[0].lower()))

EDGE_TTS_ALL_VOICES: list[str] = [v for voices in EDGE_TTS_LANG_VOICES.values() for v in voices]

boost_image_prompt = None
boost_video_prompt = None
save_vote_unlocks = None
set_server_mode = None
set_channels_mode = None
get_guild_config = None
clear_runtime_channel_memory = None
pending_transcriptions: dict[str, int] = {}
guild_history: dict[int, list] = {}
guild_now_message: dict[int, dict] = {}
guild_queue_messages: dict[int, list] = {}
guild_ytdl_queue: dict[int, list] = {}
guild_last_text_channel: dict[int, int] = {}
guild_volume: dict[int, int] = {}
guild_filters: dict[int, str] = {}
guild_now_playing_track: dict[int, dict] = {}
guild_last_activity = {}
guild_autoplay: dict[int, bool] = {}

# ── New music feature state ───────────────────────────────────────────────────
guild_loop_mode:           dict[int, str]            = {}   # "off" | "song" | "queue"
guild_saved_queue:         dict[int, list]           = {}   # snapshot for loop-queue
guild_recent_titles:       dict[int, "deque"]        = {}   # last-N played titles (dedup)
guild_recent_ids:          dict[int, "deque"]        = {}   # last-N played video IDs (dedup)
guild_prefetched_autoplay: dict[int, Optional[dict]] = {}   # pre-fetched autoplay track

_RECENT_TITLES_LIMIT = 10

MODEL_CHOICES = [
	"openai/gpt-oss-120b",
	"moonshotai/kimi-k2-instruct",
	"allam-2-7b",
	"qwen/qwen3-32b",
	"llama-3.3-70b-versatile",
	"meta-llama/llama-4-scout-17b-16e-instruct",
	"llama-3.1-8b-instant",
]
MODEL_LABELS = {
	"openai/gpt-oss-120b": "GPT-OSS-120B",
	"moonshotai/kimi-k2-instruct": "moonshotai/kimi-k2-instruct",
	"allam-2-7b": "allam-2-7b",
	"qwen/qwen3-32b": "qwen/qwen3-32b",
	"llama-3.3-70b-versatile": "llama-3.3-70b-versatile",
	"meta-llama/llama-4-scout-17b-16e-instruct": "meta-llama/llama-4-scout-17b-16e-instruct",
	"llama-3.1-8b-instant": "llama-3.1-8b-instant",
}
_COOKIE_TEMP_FILE = None
_COOKIE_TEMP_PATH: str = ""

# ── Lavalink node ─────────────────────────────────────────────────────────────
LAVALINK_HOST = os.getenv("LAVALINK_HOST", "").strip()
try:
	LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "443"))
except ValueError:
	print("[LAVALINK] Invalid LAVALINK_PORT value, defaulting to 443")
	LAVALINK_PORT = 443
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "")
LAVALINK_SECURE = os.getenv("LAVALINK_SECURE", "true").strip().lower() in ("true", "1", "yes")

# ── yt-dlp fallback ───────────────────────────────────────────────────────────

def _init_cookie_file() -> str:
	global _COOKIE_TEMP_FILE, _COOKIE_TEMP_PATH
	content = os.getenv("YTDL_COOKIE_CONTENT", "").strip()
	if not content:
		return os.getenv("YTDL_COOKIES_TXT", "").strip()
	if _COOKIE_TEMP_PATH:
		return _COOKIE_TEMP_PATH
	tmp = tempfile.NamedTemporaryFile(
		mode="w", suffix=".txt", delete=False, encoding="utf-8"
	)
	tmp.write(content)
	tmp.flush()
	tmp.close()
	_COOKIE_TEMP_FILE = tmp
	_COOKIE_TEMP_PATH = tmp.name
	return _COOKIE_TEMP_PATH

COOKIE_PATH: str = _init_cookie_file()

YTDL_OPTIONS = {
	"format": "bestaudio/best",
	"noplaylist": True,
	"quiet": True,
	"nocheckcertificate": True,
	"default_search": "ytsearch",
	"source_address": "0.0.0.0",
	"extractor_args": {"youtube": {"player_client": ["mweb", "web"]}},
}
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

AUDIO_FILTERS = {
	"normal": "",
	"bass": "bass=g=10,dynaudnorm",
	"nightcore": "asetrate=48000*1.25,aresample=48000,atempo=1.06",
	"slowed": "asetrate=48000*0.8,aresample=48000,atempo=0.9",
	"8d": "apulsator=hz=0.125",
	"treble": "treble=g=8",
	"lofi": "asetrate=48000*0.94,aresample=48000,lowpass=f=3000",
	"vaporwave": "asetrate=48000*0.85,aresample=48000",
}

_NODE_CANDIDATES = [
	"/opt/hostedtoolcache/node/20.20.0/x64/bin/node",
	"/usr/local/bin/node",
	"/usr/bin/node",
]

def _find_node_path() -> str | None:
	for path in _NODE_CANDIDATES:
		if os.path.isfile(path):
			return path
	import shutil
	return shutil.which("node")

_NODE_PATH = _find_node_path()

def _get_ytdl_options(tier: str, allow_playlist: bool = False) -> dict:
	options = dict(YTDL_OPTIONS)
	options["format"] = "bestaudio/best" if tier in {"premium", "gold"} else "bestaudio[abr<=192]/bestaudio/best"
	if allow_playlist:
		options["noplaylist"] = False
	if COOKIE_PATH:
		options["cookiefile"] = COOKIE_PATH
	if _NODE_PATH:
		options["js_runtimes"] = {"node": {"path": _NODE_PATH}}
	return options

def _get_quality_label(tier: str) -> str:
	return "320kbps" if tier in {"premium", "gold"} else "HD"

def _get_ffmpeg_options(filter_name: str = "normal") -> dict:
	"""Get FFmpeg options with optional audio filter."""
	audio_filter = AUDIO_FILTERS.get(filter_name, "")
	if audio_filter:
		return {"before_options": FFMPEG_BEFORE_OPTIONS, "options": f"-vn -af {audio_filter}"}
	return {"before_options": FFMPEG_BEFORE_OPTIONS, "options": "-vn"}

_BOOST_BITRATE_CAPS = {0: 96, 1: 128, 2: 256, 3: 384}

def _get_target_bitrate(tier: str, voice_channel: discord.VoiceChannel) -> int:
	
	tier_lower = tier.lower()
	if tier_lower == "basic":
		return 96
	if tier_lower == "premium":
		return 128
	if tier_lower == "gold":
		boost_level  = getattr(voice_channel.guild, "premium_tier", 0)
		boost_cap    = _BOOST_BITRATE_CAPS.get(boost_level, 96)
		channel_kbps = (getattr(voice_channel, "bitrate", 96000) or 96000) // 1000
		return min(channel_kbps, boost_cap, 384)
	# fallback for legacy "free" tier — same as Basic
	return 96

def _apply_bitrate(voice_client: discord.VoiceClient, tier: str) -> None:
	"""Set the Opus encoder bitrate on the voice client right after vc.play()."""
	channel = getattr(voice_client, "channel", None)
	if not isinstance(channel, discord.VoiceChannel):
		return
	kbps = _get_target_bitrate(tier, channel)
	try:
		encoder = getattr(voice_client, "encoder", None)
		if encoder is not None:
			encoder.set_bitrate(kbps)
	except Exception as e:
		print(f"[BITRATE] Could not set encoder bitrate: {e}")

async def _ytdl_extract(queries: list[str], tier: str) -> dict:
	loop = asyncio.get_running_loop()
	last_error: Exception | None = None
	for query in queries:
		def _extract(q=query):
			opts = _get_ytdl_options(tier)
			with yt_dlp.YoutubeDL(opts) as ytdl:
				return ytdl.extract_info(q, download=False)
		try:
			data = await loop.run_in_executor(None, _extract)
			if not data:
				raise Exception("No data returned.")
			if "entries" in data:
				entries = [e for e in data.get("entries", []) if e]
				if not entries:
					raise Exception("No results found.")
				data = _pick_best_entry(entries)
			return data
		except Exception as e:
			last_error = e
			continue
	raise last_error or Exception("No results found.")

async def _ytdl_extract_playlist(url: str, tier: str) -> list[dict]:
	"""Extract all tracks from a playlist URL via yt-dlp."""
	loop = asyncio.get_running_loop()
	def _extract():
		opts = _get_ytdl_options(tier, allow_playlist=True)
		with yt_dlp.YoutubeDL(opts) as ytdl:
			return ytdl.extract_info(url, download=False)
	data = await loop.run_in_executor(None, _extract)
	if not data:
		raise Exception("No data returned.")
	if "entries" in data:
		entries = [e for e in data.get("entries", []) if e]
		if not entries:
			raise Exception("No results found in playlist.")
		return entries
	return [data]


async def _ytdl_extract_different_track(query: str, tier: str, current_title: str) -> dict | None:
	"""Search multiple candidates and return first track with a different normalized title."""
	loop = asyncio.get_running_loop()
	current_norm = _normalized_title(current_title)

	def _extract():
		opts = _get_ytdl_options(tier)
		with yt_dlp.YoutubeDL(opts) as ytdl:
			return ytdl.extract_info(query, download=False)

	data = await loop.run_in_executor(None, _extract)
	if not data:
		return None

	entries = [e for e in data.get("entries", []) if e] if isinstance(data, dict) and "entries" in data else [data]
	for entry in entries:
		candidate_norm = _normalized_title(entry.get("title"))
		if candidate_norm and candidate_norm != current_norm and entry.get("url"):
			return entry
	return None


def _extract_yt_video_id(url: str | None) -> str | None:
	"""Extract YouTube video ID from a watch URL."""
	if not url:
		return None
	try:
		parsed = urlparse(url)
		if parsed.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
			vid = parse_qs(parsed.query).get("v", [None])[0]
			return vid
		if parsed.hostname in ("youtu.be",):
			return parsed.path.lstrip("/").split("?")[0] or None
	except Exception:
		pass
	return None


async def _ytdl_fetch_yt_mix(video_id: str, tier: str, exclude_ids: set[str]) -> dict | None:
	"""
	Fetch YouTube Radio/Mix for a video and return the first track not in exclude_ids.
	The mix URL gives genuinely related songs, not just other uploads of the same track.
	"""
	mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
	loop = asyncio.get_running_loop()

	def _extract():
		opts = dict(YTDL_OPTIONS)
		opts["noplaylist"] = False
		opts["playlistend"] = 10
		if COOKIE_PATH:
			opts["cookiefile"] = COOKIE_PATH
		if _NODE_PATH:
			opts["js_runtimes"] = {"node": {"path": _NODE_PATH}}
		with yt_dlp.YoutubeDL(opts) as ytdl:
			return ytdl.extract_info(mix_url, download=False)

	try:
		data = await loop.run_in_executor(None, _extract)
	except Exception as e:
		print(f"[AUTOPLAY] YT mix fetch failed: {e}")
		return None

	if not data:
		return None

	entries = [e for e in data.get("entries", []) if e] if "entries" in data else [data]
	for entry in entries:
		eid = entry.get("id") or _extract_yt_video_id(entry.get("webpage_url") or entry.get("url") or "")
		if eid and eid in exclude_ids:
			continue
		if entry.get("url") or entry.get("webpage_url"):
			return entry
	return None


# ── Transcription config ──────────────────────────────────────────────────────

ALLOWED_TRANSCRIBE_HOSTS = (
	"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
	"twitch.tv", "www.twitch.tv", "x.com", "www.x.com",
	"twitter.com", "www.twitter.com", "kick.com", "www.kick.com",
)
ALLOWED_TRANSCRIBE_HOST_SUFFIXES = ("youtube.com", "twitch.tv", "x.com", "twitter.com", "kick.com")
TRANSCRIBE_HOST_NORMALIZATION = {
	"m.youtube.com": "www.youtube.com", "music.youtube.com": "www.youtube.com",
	"m.twitch.tv": "www.twitch.tv", "m.x.com": "x.com", "mobile.x.com": "x.com",
	"m.twitter.com": "twitter.com", "mobile.twitter.com": "twitter.com",
	"m.kick.com": "www.kick.com",
}

# ── URL helpers ───────────────────────────────────────────────────────────────

_SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}
_YT_PLAYLIST_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_SC_PLAYLIST_HOSTS = {"soundcloud.com", "www.soundcloud.com"}

def _looks_like_url(value: str) -> bool:
	try:
		parsed = urlparse(value)
		return parsed.scheme in ("http", "https") and bool(parsed.netloc)
	except Exception:
		return False

def _is_spotify_url(url: str) -> bool:
	return (urlparse(url).hostname or "").lower() in _SPOTIFY_HOSTS

def _is_playlist_url(url: str) -> bool:
	try:
		parsed = urlparse(url)
	except Exception:
		return False
	host = (parsed.hostname or "").lower()
	query = parsed.query or ""
	if host in _YT_PLAYLIST_HOSTS:
		if "v=" in query and "list=" in query:
			return False
		return "list=" in query
	if host in _SC_PLAYLIST_HOSTS:
		return "/sets/" in parsed.path
	if host in _SPOTIFY_HOSTS:
		path = parsed.path.lower()
		return path.startswith("/playlist/") or path.startswith("/album/")
	return False

_COLLECTION_KEYWORDS = {
	"songs", "music", "mix", "playlist", "hits", "collection", "best", "top",
	"compilation", "hour", "phonk", "lofi", "chill", "vibes", "rap", "rnb",
	"edm", "pop", "rock", "jazz", "classical", "country", "metal", "indie",
}

def _looks_like_collection_query(query: str) -> bool:
	"""True if the query sounds like a request for a mix/playlist rather than one song."""
	words = set(query.lower().split())
	return bool(words & _COLLECTION_KEYWORDS)

_MIX_TITLE_KEYWORDS = {"mix", "playlist", "compilation", "hour", "songs", "hits", "collection", "best", "top"}

def _pick_best_entry(entries: list[dict]) -> dict:
	"""
	From a list of yt-dlp search results, prefer long compilation/mix videos.
	Scores on: (has mix/compilation keyword in title, duration).
	"""
	def _score(e: dict):
		title_words = set((e.get("title") or "").lower().split())
		keyword_hit = bool(title_words & _MIX_TITLE_KEYWORDS)
		duration    = e.get("duration") or 0
		return (keyword_hit, duration)
	return max(entries, key=_score)

def _build_query_candidates(song: str) -> list[str]:
	query = (song or "").strip()
	if _looks_like_url(query):
		return [query]
	if query.startswith("www."):
		return [f"https://{query}"]
	if _looks_like_collection_query(query):
		return [f"ytsearch5:{query}", f"scsearch1:{query}"]
	return [f"ytsearch1:{query}", f"scsearch1:{query}"]

def _format_duration_seconds(seconds: int | None) -> str:
	if not seconds or seconds <= 0:
		return "Unknown"
	seconds = int(seconds)
	minutes, secs = divmod(seconds, 60)
	hours, minutes = divmod(minutes, 60)
	if hours:
		return f"{hours}:{minutes:02d}:{secs:02d}"
	return f"{minutes}:{secs:02d}"


def _normalized_title(value: str | None) -> str:
	text = (value or "").lower().strip()
	text = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", text)
	text = re.sub(r"[^a-z0-9\s]", " ", text)
	text = re.sub(r"\s+", " ", text)
	return text.strip()


# ── Music dedup / prefetch helpers ────────────────────────────────────────────

def _add_to_recent_titles(guild_id: int, title: str, web_url: str | None = None) -> None:
	"""Push a track title (and video ID if available) into the per-guild recent deques."""
	guild_recent_titles.setdefault(guild_id, deque(maxlen=_RECENT_TITLES_LIMIT)).append(title)
	vid = _extract_yt_video_id(web_url)
	if vid:
		guild_recent_ids.setdefault(guild_id, deque(maxlen=_RECENT_TITLES_LIMIT)).append(vid)


def _is_duplicate_track(title: str, recent: "deque") -> bool:
	"""
	Return True if 'title' is too similar to any entry in 'recent'.
	Checks direct substring containment and 70%+ word-overlap.
	"""
	if not title:
		return False
	title_lower = title.lower().strip()
	title_norm  = _normalized_title(title)
	t_words     = set(title_norm.split())

	for recent_title in recent:
		r = (recent_title or "").lower().strip()
		if not r:
			continue
		if r in title_lower or title_lower in r:
			return True
		r_words = set(_normalized_title(recent_title).split())
		if t_words and r_words:
			overlap = len(t_words & r_words)
			shorter = min(len(t_words), len(r_words))
			if shorter >= 2 and overlap / shorter >= 0.70:
				return True
	return False


def _fmt_duration(seconds: int | None) -> str:
	"""Seconds → MM:SS or HH:MM:SS.  Returns '—' if None."""
	if not seconds or seconds <= 0:
		return "—"
	s = int(seconds)
	m, s = divmod(s, 60)
	h, m = divmod(m, 60)
	return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── GIF / Meme data ───────────────────────────────────────────────────────────

ACTION_GIF_SOURCES = {
	"hug": [
		"https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExYjFxbWd0djU0Y240MHE3d2t3dnIyZWtsaGI0aTFleGVncWswcDdkYyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/uakdGGShmMS0KYfTgp/giphy.gif",
		"https://media.tenor.com/bVN5MdTrelYAAAAj/yaseen1.gif",
		"https://media.tenor.com/FNX3Xvr6yGwAAAAi/snek-bubu.gif",
		"https://i.imgur.com/uXL0iTg.gif",
		"https://i.giphy.com/IzXiddo2twMmdmU8Lv.webp",
		"https://i.giphy.com/VbawWIGNtKYwOFXF7U.webp",
	],
	"kiss": [
		"https://i.giphy.com/G3va31oEEnIkM.webp", "https://i.giphy.com/bGm9FuBCGg4SY.webp",
		"https://c.tenor.com/dd4mZNppytYAAAAd/tenor.gif", "https://c.tenor.com/Y2AdPDiQoK8AAAAC/tenor.gif",
		"https://i.giphy.com/PBbFIL4bF8uS4.webp", "https://i.giphy.com/rFdqmnaIxx6qk.webp",
		"https://i.giphy.com/MqbZjCY1ghSAo.webp", "https://i.giphy.com/6Q9P2ry85GGOKbxKiC.webp",
	],
	"kick": [
		"https://i.giphy.com/DfI1LsaCkWD20xRc4r.webp", "https://i.giphy.com/3o7TKwVQMoQh2At9qU.webp",
		"https://media.tenor.com/TDQXdEBNNjUAAAAi/milk-and-mocha.gif",
		"https://media.tenor.com/ztHpFwsax84AAAAi/hau-zozo-smile.gif",
		"https://i.giphy.com/l3V0j3ytFyGHqiV7W.webp", "https://i.giphy.com/k3j9oaRV4FAT3ksIG1.webp",
		"https://i.giphy.com/xr9FpQBn2sPUOVtnNZ.webp", "https://i.giphy.com/RN96CaqhRoRHk4DlLV.webp",
		"https://i.giphy.com/qiiimDJtLj4XK.webp",
	],
	"slap": [
		"https://media.tenor.com/TVPYqh_E1JYAAAAj/peach-goma-peach-and-goma.gif",
		"https://media.tenor.com/tMVS_yML7t0AAAAj/slap-slaps.gif",
		"https://c.tenor.com/OTr4wv64hwwAAAAd/tenor.gif", "https://c.tenor.com/4Ut_QPbeCZIAAAAd/tenor.gif",
		"https://c.tenor.com/LHlITawhrEcAAAAd/tenor.gif", "https://i.giphy.com/3oriNXBCGHrzCYIbZK.webp",
		"https://i.giphy.com/qyjexFwQwJp9yUvMxq.webp", "https://i.giphy.com/RYOYNPbKoRORepL80E.webp",
	],
	"wish_goodmorning": [
		"https://media.tenor.com/xwlZJGC0EqwAAAAj/pengu-pudgy.gif",
		"https://media.tenor.com/4pnZsJP06XMAAAAj/have-a-great-day-good-day.gif",
		"https://media.tenor.com/xlwtvJtC6FAAAAAM/jjk-jujutsu-kaisen.gif",
		"https://c.tenor.com/6VbeqshMfkEAAAAd/tenor.gif",
		"https://i.giphy.com/jhQ6s2Qwjhqpivlitm.webp", "https://i.giphy.com/GjfNsZPvCFs9dQrw36.webp",
	],
}

ACTION_MESSAGES = {
	"hug": [
		"🤗 {user} wrapped {target} in a giant cozy hug!",
		"💞 {user} gave {target} the warmest cuddle ever.",
		"🐻 {user} bear-hugged {target} with max affection.",
		"✨ {user} hugged {target} and instantly improved the vibe.",
		"🌈 {user} sent a comfort hug straight to {target}.",
		"🫶 {user} gave {target} a wholesome squeeze.",
		"☁️ {user} hugged {target} like a fluffy cloud.",
		"🎉 {user} rushed over and hugged {target} in celebration!",
		"💖 {user} shared a heart-melting hug with {target}.",
		"🌟 {user} delivered a legendary friendship hug to {target}.",
	],
	"kiss": [
		"💋🥰{user} gave {target} a sweet kiss!",
		"🌹💋 {user} kissed {target} and left everyone blushing.",
		"✨💋 {user} sent {target} a dramatic movie-scene kiss.",
		"💕💋 {user} gave {target} a soft little kiss.",
		"🥰💋 {user} kissed {target} with pure wholesome energy.",
		"🎀💋 {user} surprised {target} with an adorable kiss.",
		"💞💋 {user} planted a lovely kiss on {target}.",
		"🌟💋 {user} kissed {target} and sparkles appeared everywhere.",
		"🫣💋 {user} stole a quick kiss from {target}!",
		"🍓💋 {user} gave {target} a super cute kiss.",
	],
	"kick": [
		"🥋 {user} launched a playful kick at {target}!",
		"💥 {user} drop-kicked {target} into cartoon physics.",
		"⚡ {user} gave {target} a turbo ninja kick.",
		"🎯 {user} landed a clean anime kick on {target}.",
		"🌀 {user} spin-kicked {target} with style.",
		"🔥 {user} kicked {target} straight into next week.",
		"😤 {user} delivered a dramatic boss-fight kick to {target}.",
		"👟 {user} punted {target} with comedic precision.",
		"📢 {user} yelled 'HIYAA!' and kicked {target}.",
		"🏆 {user} scored a perfect kick combo on {target}.",
	],
	"slap": [
		"🖐️ {user} slapped {target} with cartoon force!",
		"💢 {user} delivered a dramatic anime slap to {target}.",
		"⚡ {user} gave {target} a lightning-fast slap.",
		"🎬 {user} slapped {target} like a soap-opera finale.",
		"👋 {user} landed a playful slap on {target}.",
		"🌪️ {user} windmill-slapped {target} into silence.",
		"😳 {user} gave {target} a surprise slap for the plot.",
		"🎯 {user} slapped {target} with perfect timing.",
		"🔥 {user} unleashed a spicy slap on {target}.",
		"📢 {user} slapped {target} and the crowd went wild.",
	],
	"wish_goodmorning": [
		"🌅 {user} wished {target} a bright and beautiful morning!",
		"☀️ {user} sent {target} a cheerful good morning wish.",
		"🌼 {user} told {target}: good morning, sunshine!",
		"☕ {user} handed {target} a coffee and said good morning.",
		"🐣 {user} wished {target} the happiest morning ever.",
		"🌞 {user} greeted {target} with a warm good morning.",
		"✨ {user} wished {target} a fresh start and good vibes.",
		"🍳 {user} served breakfast vibes and wished {target} good morning!",
		"🎶 {user} sang a tiny good morning song for {target}.",
		"💛 {user} wished {target} a cozy, wonderful morning.",
	],
}

MEME_SOURCES = [
	"https://i.imgur.com/giaxzSP.jpeg", "https://i.imgur.com/ELuCb1H.jpeg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-10-677cf9f8b57aa__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-35-677e714a64c1c__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-32-677e7089d37ed__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-37-677e71d07e283__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-19-677d015a22631__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-4-677cf70d35587__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-2-677cf62608ccb__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-6-677cf836e20bd__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-14-677cfece125a2__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-27-677d12eff1187__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-39-677e72289295d__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-30-677d14da83f61__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/Cw95ZfXSSkf-png__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/CyGhEAHSRoY-png__700.jpg",
	"https://static.boredpanda.com/blog/wp-content/uploads/2025/01/relatable-memes-jokes-memespointt-43-677e7303d7dd4__700.jpg",
]


async def fetch_bytes(url: str) -> bytes:
	async with aiohttp.ClientSession() as session:
		async with session.get(url) as resp:
			if resp.status != 200:
				raise Exception(f"Failed to fetch: HTTP {resp.status}")
			return await resp.read()


# ── Music Controls View ───────────────────────────────────────────────────────

class MusicControls(discord.ui.View):
	def __init__(self, cog, guild_id: int):
		super().__init__(timeout=None)
		self.cog = cog
		self.guild_id = guild_id

	async def interaction_check(self, interaction: discord.Interaction) -> bool:
		await interaction.response.defer()
		return await self.cog._ensure_music_control(interaction)

	@discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
	async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_previous(interaction)

	@discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary)
	async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_pause(interaction)

	@discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
	async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_resume(interaction)

	@discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
	async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_next(interaction)

	@discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
	async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.cog._music_stop(interaction)


# ── Vote helpers ──────────────────────────────────────────────────────────────

def _build_vote_embed() -> discord.Embed:
	embed = discord.Embed(
		title="🔒 Vote Required to Unlock This Feature",
		description=(
			"This feature is locked behind a **free vote** on Top.gg!\n"
			"Vote once every 12 hours to unlock a ton of powerful features 💙"
		),
		color=0x5865F2
	)
	embed.add_field(name="🎨 Creative Tools", value=(
		"• 🖼️ **Image Analysis** — send any image\n"
		"• 🎨 **Generate Image** — `/generate_image`\n"
		"• 🖌️ **Edit Images** — send image + instruction\n"
		"• 🖼️ **Merge Images** — attach 2+ images + say merge\n"
		"• 🎬 **Generate Video** — `/generate_video`\n"
		"• 🔊 **Text-to-Speech** — `/generate_tts` (voice & language)\n"
		"• 🎵 **Play Music** — `/play [song/URL]` in voice channels"
	), inline=False)
	embed.add_field(name="📁 File Tools", value=(
		"• 📄 **PDF Reading** — upload any PDF\n"
		"• 📝 **DOCX Reading** — upload Word documents\n"
		"• 📃 **TXT Reading** — upload text files\n"
		"• 🔍 **Smart Summaries** — get instant file summaries"
	), inline=False)
	embed.add_field(name="⏱️ How It Works", value=(
		"1️⃣ Click **Vote Now** below\n"
		"2️⃣ Vote on Top.gg (takes 10 seconds!)\n"
		"3️⃣ Your vote gets registered instantly!\n"
		"4️⃣ All features unlock for **12 hours** 🎉\n"
		"5️⃣ Vote again after 12 hours to keep access"
	), inline=False)
	embed.set_footer(text="🗳️ Voting is completely free and takes 10 seconds!")
	return embed

def _build_vote_view() -> discord.ui.View:
	view = discord.ui.View(timeout=None)
	view.add_item(discord.ui.Button(
		label="🗳️ Vote Now",
		url="https://top.gg/bot/1435987186502733878/vote",
		style=discord.ButtonStyle.link
	))
	return view

async def check_vote_status(user_id: int) -> bool:
	if user_id in OWNER_IDS:
		return True
	if user_id in BYPASS_IDS:
		return True
	now = time.time()
	unlock_time = user_vote_unlocks.get(user_id)
	if unlock_time and (now - unlock_time) < VOTE_DURATION:
		return True
	if await has_voted(user_id):
		user_vote_unlocks[user_id] = now
		if save_vote_unlocks:
			save_vote_unlocks()
		return True
	return False

async def require_vote_deferred(interaction: discord.Interaction) -> bool:
	voted = await check_vote_status(interaction.user.id)
	if not voted:
		await interaction.edit_original_response(
			content=None, embed=_build_vote_embed(), view=_build_vote_view()
		)
	return voted

async def require_vote_slash(interaction: discord.Interaction) -> bool:
	voted = await check_vote_status(interaction.user.id)
	if not voted:
		await interaction.response.send_message(
			embed=_build_vote_embed(), view=_build_vote_view(), ephemeral=False
		)
	return voted


# ── Configure group ───────────────────────────────────────────────────────────

class ConfigureGroup(app_commands.Group):
	def __init__(self):
		super().__init__(name="configure", description="Configure where the bot can chat in this server")

	async def _ensure_guild_owner(self, interaction: discord.Interaction) -> bool:
		if interaction.guild is None:
			await interaction.response.send_message("❌ This command can only be used inside a server.", ephemeral=True)
			return False
		if interaction.guild.owner_id != interaction.user.id:
			if interaction.response.is_done():
				await interaction.followup.send("❌ You are not the server owner.", ephemeral=True)
			else:
				await interaction.response.send_message("❌ You are not the server owner.", ephemeral=True)
			return False
		if set_server_mode is None or set_channels_mode is None or get_guild_config is None:
			await interaction.response.send_message("⚠️ Configuration system is not ready.", ephemeral=True)
			return False
		return True

	@app_commands.command(name="server", description="Allow the bot to chat in all channels in this server")
	async def configure_server(self, interaction: discord.Interaction):
		if not await self._ensure_guild_owner(interaction):
			return
		channel_ids = [ch.id for ch in interaction.guild.text_channels]
		set_server_mode(interaction.guild.id, channel_ids)
		await interaction.response.send_message(
			"✅ Configuration updated: I can now chat in **the whole server** when pinged.", ephemeral=False
		)

	@app_commands.command(name="channels", description="Restrict bot chat to selected channel(s) in this server")
	@app_commands.describe(
		channel_1="Required channel", channel_2="Optional channel",
		channel_3="Optional channel", channel_4="Optional channel", channel_5="Optional channel",
	)
	async def configure_channels(
		self, interaction: discord.Interaction,
		channel_1: app_commands.AppCommandChannel,
		channel_2: Optional[app_commands.AppCommandChannel] = None,
		channel_3: Optional[app_commands.AppCommandChannel] = None,
		channel_4: Optional[app_commands.AppCommandChannel] = None,
		channel_5: Optional[app_commands.AppCommandChannel] = None,
	):
		if not await self._ensure_guild_owner(interaction):
			return
		selected_channels = [ch for ch in [channel_1, channel_2, channel_3, channel_4, channel_5] if ch is not None]
		channel_ids = [ch.id for ch in selected_channels]
		set_channels_mode(interaction.guild.id, channel_ids)
		mentions = ", ".join(f"<#{ch.id}>" for ch in selected_channels)
		await interaction.response.send_message(
			f"✅ Configuration updated: I will now only chat in these channel(s): {mentions}", ephemeral=False
		)

	@configure_server.error
	@configure_channels.error
	async def configure_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
		print(f"[CONFIGURE ERROR] {error}")
		msg = "❌ Couldn't complete this configure request."
		if interaction.response.is_done():
			await interaction.followup.send(msg, ephemeral=True)
		else:
			await interaction.response.send_message(msg, ephemeral=True)


# ── Code Runner ───────────────────────────────────────────────────────────────

_CODE_TIMEOUT = 10  # seconds

_BLOCKED_CODE_PATTERNS = re.compile(
	r"(?:import\s+(?:os|sys|subprocess|shutil|socket|ctypes|signal|pathlib)"
	r"|from\s+(?:os|sys|subprocess|shutil|socket|ctypes|signal|pathlib)\s+import"
	r"|__import__\s*\("
	r"|exec\s*\(|eval\s*\("
	r"|open\s*\(|compile\s*\("
	r"|globals\s*\(|locals\s*\(|vars\s*\("
	r"|getattr\s*\(|setattr\s*\(|delattr\s*\("
	r")",
	re.IGNORECASE,
)

async def run_python_code(code: str) -> dict:
	"""
	Execute Python code in a subprocess with a timeout.
	Returns dict with keys: success (bool), output (str), error (str).
	Blocks code that uses dangerous modules or built-in functions.
	"""
	blocked = _BLOCKED_CODE_PATTERNS.search(code)
	if blocked:
		return {
			"success": False,
			"output": "",
			"error": f"🚫 Blocked: use of `{blocked.group()}` is not allowed for security reasons.",
		}

	loop = asyncio.get_running_loop()

	def _execute():
		try:
			result = subprocess.run(
				["python3", "-c", code],
				capture_output=True,
				text=True,
				timeout=_CODE_TIMEOUT,
				env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
			)
			stdout = result.stdout.strip()
			stderr = result.stderr.strip()
			if result.returncode == 0:
				return {"success": True, "output": stdout or "(no output)", "error": ""}
			return {"success": False, "output": stdout, "error": stderr or f"Exit code {result.returncode}"}
		except subprocess.TimeoutExpired:
			return {"success": False, "output": "", "error": "⏱️ Code timed out (10 s limit)."}
		except Exception as e:
			return {"success": False, "output": "", "error": str(e)}

	return await loop.run_in_executor(None, _execute)



# ── URL Browser / Web Scraper ─────────────────────────────────────────────────

import ipaddress

def _is_private_url(url: str) -> bool:
	"""Return True if the URL points to a private/internal IP range."""
	try:
		hostname = urlparse(url).hostname or ""
		import socket
		addr = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
		for family, _, _, _, sockaddr in addr:
			ip = ipaddress.ip_address(sockaddr[0])
			if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
				return True
	except Exception:
		pass
	return False

async def fetch_url_content(url: str, max_chars: int = 2000) -> str:
	"""
	Fetch a webpage and extract its main text content.
	Uses trafilatura first; falls back to BeautifulSoup.
	Returns extracted text truncated to *max_chars*.
	Blocks private/internal IP ranges to prevent SSRF.
	"""
	parsed = urlparse(url)
	if parsed.scheme not in ("http", "https"):
		return "❌ Only http and https URLs are supported."
	if _is_private_url(url):
		return "❌ Cannot access internal/private network addresses."
	headers = {
		"User-Agent": (
			"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
			"AppleWebKit/537.36 (KHTML, like Gecko) "
			"Chrome/120.0.0.0 Safari/537.36"
		)
	}
	try:
		async with aiohttp.ClientSession() as session:
			async with session.get(
				url,
				headers=headers,
				timeout=aiohttp.ClientTimeout(total=15),
				allow_redirects=True,
			) as resp:
				if resp.status != 200:
					return f"❌ Could not fetch URL (HTTP {resp.status})."
				html = await resp.text(errors="replace")
	except asyncio.TimeoutError:
		return "❌ URL request timed out."
	except aiohttp.ClientError as e:
		return f"❌ Network error: {e}"
	except Exception as e:
		return f"❌ Failed to fetch URL: {e}"

	# Try trafilatura first (best for articles/news)
	loop = asyncio.get_running_loop()
	text = await loop.run_in_executor(
		None, lambda: trafilatura.extract(html, include_links=False, include_comments=False) or ""
	)

	# Fallback to BeautifulSoup
	if not text.strip():
		def _bs_extract():
			soup = BeautifulSoup(html, "html.parser")
			for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
				tag.decompose()
			return soup.get_text(separator="\n", strip=True)
		text = await loop.run_in_executor(None, _bs_extract)

	if not text.strip():
		return "❌ Could not extract readable text from this page."

	if len(text) > max_chars:
		text = text[:max_chars - 3] + "..."
	return text


# ── Playlist Modals ───────────────────────────────────────────────────────────

class PlaylistCreateModal(discord.ui.Modal, title="🎵 Create New Playlist"):
	name_field = discord.ui.TextInput(
		label="Playlist name",
		placeholder="e.g. Summer Vibes",
		max_length=50,
		required=True,
	)
	songs_field = discord.ui.TextInput(
		label="Songs — one per line (URL or search query)",
		style=discord.TextStyle.paragraph,
		placeholder=(
			"https://youtube.com/watch?v=...\n"
			"Blinding Lights The Weeknd\n"
			"Stay The Kid LAROI"
		),
		max_length=2000,
		required=True,
	)

	def __init__(self, cog):
		super().__init__()
		self.cog = cog

	async def on_submit(self, interaction: discord.Interaction):
		name    = self.name_field.value.strip()
		queries = [l.strip() for l in self.songs_field.value.splitlines() if l.strip()]
		if not queries:
			await interaction.response.send_message("❌ No songs provided.", ephemeral=True)
			return
		await interaction.response.defer()
		msg = await interaction.followup.send(
			content=f"🎵 Creating **{name}** — resolving {min(len(queries), 50)} song(s)…",
			wait=True,
		)
		pid, err = playlist_manager.create_playlist(
			interaction.guild.id, name, interaction.user.id, str(interaction.user)
		)
		if err:
			await msg.edit(content=f"❌ {err}")
			return
		tier     = get_tier_from_message(interaction)
		resolved = await self.cog._resolve_songs(queries[:50], tier)
		added, skip = playlist_manager.add_tracks(interaction.guild.id, pid, resolved)
		embed = discord.Embed(title="✅ Playlist Created", color=0x1DB954,
							  timestamp=datetime.now(timezone.utc))
		embed.add_field(name="Name",         value=name,       inline=True)
		embed.add_field(name="Tracks added", value=str(added), inline=True)
		if skip:
			embed.add_field(name="Skipped", value=f"{skip} (limit reached)", inline=True)
		embed.add_field(
			name="How to play",
			value=f"Run `/playlist` → select **{name}** → press **▶ Play**",
			inline=False,
		)
		embed.set_footer(text=f"Playlist ID: {pid} • max {playlist_manager.MAX_TRACKS_PER_PLAYLIST} tracks")
		await msg.edit(content=None, embed=embed)


class PlaylistAddSongsModal(discord.ui.Modal):
	songs_field = discord.ui.TextInput(
		label="Songs — one per line (URL or search query)",
		style=discord.TextStyle.paragraph,
		placeholder="https://youtube.com/watch?v=...\nArtist – Song title",
		max_length=2000,
		required=True,
	)

	def __init__(self, cog, guild_id: int, playlist_id: str, playlist_name: str):
		super().__init__(title=f"Add Songs to {playlist_name[:40]}")
		self.cog          = cog
		self.guild_id     = guild_id
		self.playlist_id  = playlist_id
		self.playlist_name = playlist_name

	async def on_submit(self, interaction: discord.Interaction):
		queries = [l.strip() for l in self.songs_field.value.splitlines() if l.strip()]
		if not queries:
			await interaction.response.send_message("❌ No songs provided.", ephemeral=True)
			return
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl:
			await interaction.response.send_message("❌ Playlist not found.", ephemeral=True)
			return
		await interaction.response.defer()
		status = await interaction.followup.send(
			content=f"🔍 Resolving {min(len(queries), 50)} song(s)…",
			wait=True,
		)
		tier     = get_tier_from_message(interaction)
		resolved = await self.cog._resolve_songs(queries[:50], tier)
		added, skip = playlist_manager.add_tracks(self.guild_id, self.playlist_id, resolved)
		pl    = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		embed = self.cog._build_playlist_manage_embed(pl, self.playlist_id)
		result_msg = (f"✅ Added **{added}** track(s) to **{self.playlist_name}**."
					  + (f"  {skip} skipped (limit reached)." if skip else ""))
		view  = PlaylistManageView(self.cog, self.guild_id, interaction.user.id, self.playlist_id)
		await status.edit(content=result_msg, embed=embed, view=view)


# ── Playlist Views ────────────────────────────────────────────────────────────

class PlaylistBrowserView(discord.ui.View):
	def __init__(self, cog, guild_id: int, user_id: int):
		super().__init__(timeout=120)
		self.cog      = cog
		self.guild_id = guild_id
		self.user_id  = user_id
		self._build_select()

	def _build_select(self):
		playlists = playlist_manager.get_guild_playlists(self.guild_id)
		if not playlists:
			return
		options = []
		for pid, pl in list(playlists.items())[:25]:
			tc       = len(pl.get("tracks", []))
			dur_secs = sum(t.get("duration") or 0 for t in pl.get("tracks", []))
			dur_str  = _fmt_duration(dur_secs)
			options.append(discord.SelectOption(
				label=pl["name"][:100],
				value=pid,
				description=f"{tc} track{'s' if tc != 1 else ''} · {dur_str} · by {pl['creator_name'][:40]}",
			))
		sel = discord.ui.Select(placeholder="Choose a playlist to manage…", options=options, row=0)
		sel.callback = self._on_select
		self.add_item(sel)

	async def _on_select(self, interaction: discord.Interaction):
		if interaction.user.id != self.user_id:
			await interaction.response.send_message("This menu isn't for you.", ephemeral=True)
			return
		pid = interaction.data["values"][0]
		pl  = playlist_manager.get_playlist(self.guild_id, pid)
		if not pl:
			await interaction.response.send_message("❌ Playlist not found.", ephemeral=True)
			return
		embed = self.cog._build_playlist_manage_embed(pl, pid)
		view  = PlaylistManageView(self.cog, self.guild_id, self.user_id, pid)
		await interaction.response.edit_message(embed=embed, view=view)


class PlaylistManageView(discord.ui.View):
	def __init__(self, cog, guild_id: int, user_id: int, playlist_id: str):
		super().__init__(timeout=120)
		self.cog         = cog
		self.guild_id    = guild_id
		self.user_id     = user_id
		self.playlist_id = playlist_id
		self._add_switch_select()

	def _add_switch_select(self):
		playlists = playlist_manager.get_guild_playlists(self.guild_id)
		if len(playlists) <= 1:
			return
		options = []
		for pid, pl in list(playlists.items())[:25]:
			tc = len(pl.get("tracks", []))
			options.append(discord.SelectOption(
				label=pl["name"][:100], value=pid,
				description=f"{tc} tracks", default=(pid == self.playlist_id),
			))
		sel = discord.ui.Select(placeholder="Switch playlist…", options=options, row=1)
		sel.callback = self._on_switch
		self.add_item(sel)

	async def _on_switch(self, interaction: discord.Interaction):
		if interaction.user.id != self.user_id:
			await interaction.response.send_message("Not your menu.", ephemeral=True)
			return
		pid = interaction.data["values"][0]
		pl  = playlist_manager.get_playlist(self.guild_id, pid)
		if not pl:
			await interaction.response.send_message("❌ Playlist not found.", ephemeral=True)
			return
		embed = self.cog._build_playlist_manage_embed(pl, pid)
		view  = PlaylistManageView(self.cog, self.guild_id, self.user_id, pid)
		await interaction.response.edit_message(embed=embed, view=view)

	async def interaction_check(self, interaction: discord.Interaction) -> bool:
		if interaction.user.id != self.user_id:
			await interaction.response.send_message("Not your command.", ephemeral=True)
			return False
		return True

	@discord.ui.button(label="Play", style=discord.ButtonStyle.success, emoji="▶️", row=0)
	async def play_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		if not interaction.guild:
			await interaction.response.send_message("Server only.", ephemeral=True)
			return
		if not interaction.user.voice or not interaction.user.voice.channel:
			await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
			return
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl or not pl.get("tracks"):
			await interaction.response.send_message("This playlist is empty.", ephemeral=True)
			return
		await interaction.response.defer()
		channel = interaction.user.voice.channel
		vc      = interaction.guild.voice_client
		if not vc or not vc.is_connected():
			vc = await channel.connect()
		elif hasattr(vc, "channel") and vc.channel.id != channel.id:
			await interaction.followup.send(f"I'm already in {vc.channel.mention}.", ephemeral=True)
			return
		guild_last_text_channel[interaction.guild.id] = interaction.channel.id
		tier = get_tier_from_message(interaction)
		tracks_to_queue = [
			{
				"title":        t.get("title") or "Unknown",
				"web_url":      t.get("web_url"),
				"uploader":     t.get("uploader") or "Unknown",
				"duration":     t.get("duration"),
				"thumbnail":    t.get("thumbnail"),
				"needs_resolve": True,
				"requested_by": interaction.user.mention,
				"tier":         tier,
				"filter":       "normal",
			}
			for t in pl["tracks"]
		]
		existing_queue = guild_ytdl_queue.setdefault(interaction.guild.id, [])
		if not (getattr(vc, "is_playing", lambda: False)() or getattr(vc, "is_paused", lambda: False)()):
			first = tracks_to_queue[0]
			try:
				info = await _ytdl_extract([first["web_url"]], tier)
				first["stream_url"]    = info.get("url")
				first["needs_resolve"] = False

				def _after_cb(error):
					if error:
						print(f"[PLAYLIST PLAY] {error}")
					asyncio.run_coroutine_threadsafe(
						self.cog._ytdl_auto_advance(interaction.guild.id),
						self.cog.bot.loop,
					)

				volume = guild_volume.get(interaction.guild.id, 100) / 100
				src    = discord.PCMVolumeTransformer(
					discord.FFmpegPCMAudio(first["stream_url"], **_get_ffmpeg_options("normal")),
					volume=volume,
				)
				vc.play(src, after=_after_cb)
				_apply_bitrate(vc, first.get("tier", "basic"))
				guild_last_activity[interaction.guild.id] = asyncio.get_event_loop().time()
				guild_now_playing_track[interaction.guild.id] = first
				_add_to_recent_titles(interaction.guild.id, first.get("title", ""), first.get("web_url"))
				existing_queue.extend(tracks_to_queue[1:])
				if guild_loop_mode.get(interaction.guild.id) == "queue":
					guild_saved_queue[interaction.guild.id] = [dict(t) for t in tracks_to_queue]
				np_embed = self.cog._build_now_playing_embed_from_ytdl(
					{"title": first["title"], "webpage_url": first["web_url"],
					 "uploader": first["uploader"], "duration": first["duration"],
					 "thumbnail": first["thumbnail"]},
					first["requested_by"], tier,
				)
				np_embed.add_field(name="Playlist", value=pl["name"], inline=True)
				if len(tracks_to_queue) > 1:
					np_embed.add_field(name="Queued", value=f"{len(tracks_to_queue)-1} more", inline=True)
				controls = MusicControls(self.cog, interaction.guild.id)
				msg = await interaction.followup.send(embed=np_embed, view=controls, wait=True)
				guild_now_message[interaction.guild.id] = {
					"channel_id": msg.channel.id, "message_id": msg.id,
					"title":      np_embed.description or "Unknown",
				}
				asyncio.create_task(self.cog._prefetch_next_track(interaction.guild.id))
			except Exception as e:
				print(f"[PLAYLIST PLAY] {e}")
				await interaction.followup.send(f"❌ Couldn't play the first track: {e}")
		else:
			existing_queue.extend(tracks_to_queue)
			await interaction.followup.send(
				f"✅ Queued **{len(tracks_to_queue)}** tracks from **{pl['name']}**."
			)

	@discord.ui.button(label="Add songs", style=discord.ButtonStyle.secondary, emoji="➕", row=0)
	async def add_songs_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl:
			await interaction.response.send_message("❌ Playlist not found.", ephemeral=True)
			return
		await interaction.response.send_modal(
			PlaylistAddSongsModal(self.cog, self.guild_id, self.playlist_id, pl["name"])
		)

	@discord.ui.button(label="View tracks", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
	async def view_tracks_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl:
			await interaction.response.send_message("❌ Playlist not found.", ephemeral=True)
			return
		embed = self.cog._build_tracks_embed(pl, page=0)
		view  = PlaylistTracksView(self.cog, self.guild_id, self.user_id, self.playlist_id, page=0)
		await interaction.response.edit_message(embed=embed, view=view)

	@discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", row=0)
	async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl:
			await interaction.response.send_message("❌ Playlist not found.", ephemeral=True)
			return
		embed = discord.Embed(
			title="⚠️ Delete Playlist?",
			description=(
				f"Are you sure you want to delete **{pl['name']}** "
				f"({len(pl.get('tracks', []))} tracks)?\n\n**This cannot be undone.**"
			),
			color=0xED4245,
		)
		view = PlaylistConfirmDeleteView(self.cog, self.guild_id, self.user_id, self.playlist_id)
		await interaction.response.edit_message(embed=embed, view=view)


class PlaylistTracksView(discord.ui.View):
	TRACKS_PER_PAGE = 10

	def __init__(self, cog, guild_id: int, user_id: int, playlist_id: str, page: int = 0):
		super().__init__(timeout=120)
		self.cog         = cog
		self.guild_id    = guild_id
		self.user_id     = user_id
		self.playlist_id = playlist_id
		self.page        = page
		pl               = playlist_manager.get_playlist(guild_id, playlist_id)
		total            = len(pl.get("tracks", [])) if pl else 0
		self.total_pages = max(1, (total + self.TRACKS_PER_PAGE - 1) // self.TRACKS_PER_PAGE)
		self.prev_btn.disabled = page <= 0
		self.next_btn.disabled = page >= self.total_pages - 1

	async def interaction_check(self, interaction: discord.Interaction) -> bool:
		if interaction.user.id != self.user_id:
			await interaction.response.send_message("Not your menu.", ephemeral=True)
			return False
		return True

	@discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, emoji="⬅️", row=0)
	async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl:
			await interaction.response.send_message("Playlist not found.", ephemeral=True)
			return
		embed = self.cog._build_tracks_embed(pl, self.page - 1)
		view  = PlaylistTracksView(self.cog, self.guild_id, self.user_id, self.playlist_id, self.page - 1)
		await interaction.response.edit_message(embed=embed, view=view)

	@discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️", row=0)
	async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl:
			await interaction.response.send_message("Playlist not found.", ephemeral=True)
			return
		embed = self.cog._build_tracks_embed(pl, self.page + 1)
		view  = PlaylistTracksView(self.cog, self.guild_id, self.user_id, self.playlist_id, self.page + 1)
		await interaction.response.edit_message(embed=embed, view=view)

	@discord.ui.button(label="Back", style=discord.ButtonStyle.primary, row=0)
	async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl:
			await interaction.response.send_message("Playlist not found.", ephemeral=True)
			return
		embed = self.cog._build_playlist_manage_embed(pl, self.playlist_id)
		view  = PlaylistManageView(self.cog, self.guild_id, self.user_id, self.playlist_id)
		await interaction.response.edit_message(embed=embed, view=view)


class PlaylistConfirmDeleteView(discord.ui.View):
	def __init__(self, cog, guild_id: int, user_id: int, playlist_id: str):
		super().__init__(timeout=60)
		self.cog         = cog
		self.guild_id    = guild_id
		self.user_id     = user_id
		self.playlist_id = playlist_id

	async def interaction_check(self, interaction: discord.Interaction) -> bool:
		if interaction.user.id != self.user_id:
			await interaction.response.send_message("Not your command.", ephemeral=True)
			return False
		return True

	@discord.ui.button(label="Yes, delete it", style=discord.ButtonStyle.danger, emoji="🗑️")
	async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		pl   = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		name = pl["name"] if pl else "Unknown"
		playlist_manager.delete_playlist(self.guild_id, self.playlist_id)
		await interaction.response.edit_message(
			content=f"🗑️ **{name}** has been deleted.", embed=None, view=None,
		)

	@discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
	async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		pl = playlist_manager.get_playlist(self.guild_id, self.playlist_id)
		if not pl:
			await interaction.response.edit_message(
				content="Playlist no longer exists.", embed=None, view=None
			)
			return
		embed = self.cog._build_playlist_manage_embed(pl, self.playlist_id)
		view  = PlaylistManageView(self.cog, self.guild_id, self.user_id, self.playlist_id)
		await interaction.response.edit_message(embed=embed, view=view)


# ── Code Test Modal ───────────────────────────────────────────────────────────

class CodeTestModal(discord.ui.Modal, title="🧪 Test Your Python Code"):
	"""Modal for multi-line code input"""

	code_input = discord.ui.TextInput(
		label="Paste your Python code here",
		style=discord.TextStyle.paragraph,
		placeholder="def hello():\n    print('Hello, World!')\n\nhello()",
		required=True,
		max_length=4000,
	)

	async def on_submit(self, interaction: discord.Interaction):
		await interaction.response.send_message("🧪 **Testing the code...**", ephemeral=False)
	
		try:
			code = self.code_input.value
	
			result = await run_python_code(code)
	
			if result["success"]:
				output_preview = result["output"][:500] or "(no output)"
				embed = discord.Embed(title="✅ Code ran successfully!", color=0x00FF00)
				embed.add_field(name="📋 Summary", value="Your code executed without errors.", inline=False)
				embed.add_field(name="📤 Output", value=f"```\n{output_preview}\n```", inline=False)
				await interaction.edit_original_response(content=None, embed=embed)
			else:
				error_preview = result["error"][:500] or "Unknown error"
				embed = discord.Embed(title="❌ Code failed", color=0xFF0000)
				embed.add_field(name="🐛 Error", value=f"```\n{error_preview}\n```", inline=False)
	
				embed.add_field(name="🔧 Attempting AI fix...", value="Please wait...", inline=False)
				await interaction.edit_original_response(content=None, embed=embed)
	
				fix_prompt = (
					"You are a Python code fixer. The following Python code produced an error.\n"
					"Fix the code and return ONLY the corrected Python code, nothing else. "
					"Do NOT include markdown fences or explanations.\n\n"
					f"Original code:\n{code}\n\n"
					f"Error:\n{result['error']}\n\n"
					"Fixed code:"
				)
				try:
					fixed_code = await call_cerebras(prompt=fix_prompt, temperature=0.2)
					fixed_code = (fixed_code or "").strip()
					
					if fixed_code.startswith("```"):
						fixed_code = re.sub(r"^```(?:python)?\n?", "", fixed_code)
						fixed_code = re.sub(r"\n?```$", "", fixed_code)
	
					if fixed_code:
						retest = await run_python_code(fixed_code)
						if retest["success"]:
							retest_output = retest["output"][:300] or "(no output)"
							embed.set_field_at(1, name="✅ AI-Fixed Code", value=f"```python\n{fixed_code[:800]}\n```", inline=False)
							embed.add_field(name="✅ Fixed code output", value=f"```\n{retest_output}\n```", inline=False)
						else:
							embed.set_field_at(1, name="🔧 AI Fix Attempted", value=f"```python\n{fixed_code[:800]}\n```", inline=False)
							embed.add_field(name="⚠️ Fix still has errors", value=f"```\n{retest['error'][:300]}\n```", inline=False)
					else:
						embed.set_field_at(1, name="🔧 AI Fix", value="Could not generate a fix.", inline=False)
				except Exception as e:
					print(f"[TEST_CODE AI FIX ERROR] {e}")
					embed.set_field_at(1, name="🔧 AI Fix", value="AI fixer unavailable right now.", inline=False)
	
				await interaction.edit_original_response(content=None, embed=embed)
				
		except Exception as e:
			print(f"[TEST_CODE ERROR] {e}")
			traceback.print_exc()
			try:
				await interaction.edit_original_response(
					content="⚠️ Something went wrong while testing your code. Please try again."
				)
			except Exception as fallback_err:
				print(f"[TEST_CODE ERROR] Could not send error response: {fallback_err}")

# ── Main Cog ──────────────────────────────────────────────────────────────────

class Codunot(commands.Cog):
	def __init__(self, bot: commands.Bot):
		self.bot = bot
		self.bot.tree.add_command(ConfigureGroup())
		self._lavalink_session: aiohttp.ClientSession | None = None

	# ── Lavalink connect ──────────────────────────────────────────────────────

	async def cog_load(self):
		if not LAVALINK_HOST:
			print("[LAVALINK] No LAVALINK_HOST configured — Lavalink disabled, Spotify will use yt-dlp fallback")
			return
		# Build a custom session with relaxed SSL to work around
		# TLSV1_UNRECOGNIZED_NAME errors on some Lavalink hosts.
		session: aiohttp.ClientSession | None = None
		if LAVALINK_SECURE:
			ctx = ssl.create_default_context()
			ctx.check_hostname = False
			ctx.verify_mode = ssl.CERT_NONE
			connector = aiohttp.TCPConnector(ssl=ctx)
			session = aiohttp.ClientSession(connector=connector)
			self._lavalink_session = session
		node = wavelink.Node(
			uri=f"{'https' if LAVALINK_SECURE else 'http'}://{LAVALINK_HOST}:{LAVALINK_PORT}",
			password=LAVALINK_PASSWORD,
			session=session,
			retries=3,
		)
		try:
			await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)
			print(f"[LAVALINK] Connected to {LAVALINK_HOST}")
		except Exception as e:
			print(f"[LAVALINK] Failed to connect: {e} — Spotify will use yt-dlp fallback")
			try:
				await wavelink.Pool.close()
			except Exception as close_err:
				print(f"[LAVALINK] Pool cleanup error: {close_err}")

	async def cog_unload(self):
		try:
			await wavelink.Pool.close()
		except Exception:
			pass
		if self._lavalink_session and not self._lavalink_session.closed:
			await self._lavalink_session.close()

	def _lavalink_available(self) -> bool:
		try:
			nodes = wavelink.Pool.nodes
			return bool(nodes)
		except Exception:
			return False

	# ── Wavelink event ────────────────────────────────────────────────────────

	@commands.Cog.listener()
	async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
		player: wavelink.Player = payload.player
		if not player:
			return
		guild_id = player.guild.id
		print(f"[WAVELINK] Track ended for guild {guild_id}, reason={payload.reason}")
		if payload.reason in ("finished", "loadFailed"):
			await self._wavelink_auto_advance(guild_id, player)

	async def _wavelink_auto_advance(self, guild_id: int, player: wavelink.Player):
		loop_mode = guild_loop_mode.get(guild_id, "off")

		# ── Loop song: re-play current track ──────────────────────────────────
		if loop_mode == "song":
			current_info = guild_now_playing_track.get(guild_id, {})
			seed         = current_info.get("title")
			url          = current_info.get("web_url") or seed
			if url:
				try:
					results = await wavelink.Playable.search(url)
					if results:
						track = results[0] if isinstance(results, list) else results
						await player.play(track)
						guild_now_playing_track[guild_id] = {
							"title":    track.title or seed,
							"uploader": track.author or "Unknown",
							"web_url":  current_info.get("web_url"),
						}
						embed = self._build_now_playing_embed_from_wl(track, guild_id)
						embed.add_field(name="Loop", value="🔂 Song", inline=True)
						view  = MusicControls(self, guild_id)
						await self._post_now_playing(guild_id, embed, view)
						return
				except Exception as e:
					print(f"[WAVELINK LOOP SONG] {e}, falling through")

		await self._mark_now_playing_as_ended(guild_id)

		# Record finished title for dedup
		fi = guild_now_playing_track.get(guild_id, {})
		if fi.get("title"):
			_add_to_recent_titles(guild_id, fi["title"], fi.get("web_url"))

		queue = player.queue

		# ── Loop queue: rebuild from snapshot when empty ───────────────────
		if loop_mode == "queue" and queue.is_empty:
			saved = guild_saved_queue.get(guild_id, [])
			for t_info in saved:
				url = t_info.get("web_url") or t_info.get("title", "")
				try:
					results = await wavelink.Playable.search(url)
					if results:
						t = results[0] if isinstance(results, list) else results
						queue.put(t)
				except Exception:
					pass

		# ── Autoplay when queue is still empty ────────────────────────────
		if queue.is_empty:
			if guild_autoplay.get(guild_id, False):
				seed   = fi.get("title")
				recent = guild_recent_titles.get(guild_id, deque())

				# Try pre-fetched candidate first (fastest path)
				prefetched = guild_prefetched_autoplay.pop(guild_id, None)
				search_url = None
				if prefetched and not _is_duplicate_track(prefetched.get("title", ""), recent):
					search_url = prefetched.get("web_url") or prefetched.get("title", seed or "top hits")
				else:
					search_url = seed or "top hits"

				try:
					results = await wavelink.Playable.search(search_url)
					if results:
						candidates = results if isinstance(results, list) else [results]
						next_track = None
						for c in candidates:
							if not _is_duplicate_track(getattr(c, "title", ""), recent):
								next_track = c
								break
						if next_track is None:
							next_track = candidates[0]
						await player.play(next_track)
						guild_now_playing_track[guild_id] = {
							"title":    next_track.title or (seed or "Unknown"),
							"uploader": next_track.author or "Unknown",
						}
						embed = self._build_now_playing_embed_from_wl(next_track, guild_id)
						view  = MusicControls(self, guild_id)
						await self._post_now_playing(guild_id, embed, view)
						asyncio.create_task(self._prefetch_next_track(guild_id))
						return
				except Exception as e:
					print(f"[WAVELINK] Autoplay dedup failed: {e}")

			print(f"[WAVELINK] Queue empty, going idle for guild {guild_id}")
			guild_last_activity[guild_id] = asyncio.get_event_loop().time()
			asyncio.create_task(self._start_idle_timer(guild_id))
			return

		next_track = queue.get()
		try:
			await player.play(next_track)
			guild_now_playing_track[guild_id] = {
				"title":    next_track.title or "Unknown",
				"uploader": next_track.author or "Unknown",
			}
			embed = self._build_now_playing_embed_from_wl(next_track, guild_id)
			lm    = guild_loop_mode.get(guild_id, "off")
			if lm != "off":
				embed.add_field(name="Loop", value={"song": "🔂 Song", "queue": "🔁 Queue"}.get(lm, lm), inline=True)
			view = MusicControls(self, guild_id)
			await self._post_now_playing(guild_id, embed, view)
			asyncio.create_task(self._prefetch_next_track(guild_id))
		except Exception as e:
			print(f"[WAVELINK] Auto-advance error: {e}")

	@app_commands.command(name="shard", description="Show the shard info for this server")
	async def shard_slash(self, interaction: discord.Interaction):
		guild = interaction.guild
		if guild is None:
			await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
			return

		shard_id = guild.shard_id
		total_shards = interaction.client.shard_count if interaction.client.shard_count else "unknown"
		server_count = len(interaction.client.guilds)
		member_count = guild.member_count
		shard_guild_count = sum(g.shard_id == shard_id for g in interaction.client.guilds)

		embed = discord.Embed(title="Shard Information", color=discord.Color.blurple())
		embed.add_field(name="Shard ID", value=str(shard_id))
		embed.add_field(name="Total Shards", value=str(total_shards))
		embed.add_field(name="Servers on this shard", value=str(shard_guild_count))
		embed.add_field(name="This Server", value=f"{guild.name}\n(ID: {guild.id})")
		embed.add_field(name="Member Count", value=str(member_count))
		await interaction.response.send_message(embed=embed, ephemeral=True)

	async def _start_idle_timer(self, guild_id: int):
		await asyncio.sleep(600)
		guild = self.bot.get_guild(guild_id)
		if guild is None:
			return
		voice_client = guild.voice_client
		if not voice_client:
			return
		if hasattr(voice_client, 'is_playing') and (voice_client.is_playing() or voice_client.is_paused()):
			return
		last = guild_last_activity.get(guild_id, 0)
		now = asyncio.get_event_loop().time()
		if now - last >= 600:
			try:
				await voice_client.disconnect()
				print(f"[MUSIC] Disconnected due to 10m inactivity guild={guild_id}")
			except Exception as e:
				print(f"[MUSIC] Disconnect error: {e}")

	async def _mark_now_playing_as_ended(self, guild_id: int):
		from collections import defaultdict
		message_info = guild_now_message.get(guild_id)
		if not message_info:
			return
		channel_id = message_info.get("channel_id")
		message_id = message_info.get("message_id")
		title = message_info.get("title", "Unknown")
		try:
			guild = self.bot.get_guild(guild_id)
			if guild is None:
				return
			channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
			message = await channel.fetch_message(message_id)
			ended_embed = discord.Embed(title="⏹️ Ended", description=title, color=0x5C5C5C)
			ended_embed.set_footer(text="Song finished playing")
			await message.edit(embed=ended_embed, view=None)
		except Exception as e:
			print(f"[MUSIC] Failed to mark now-playing as ended: {e}")

	async def _post_now_playing(self, guild_id: int, embed: discord.Embed, view: discord.ui.View):
		queue_messages = guild_queue_messages.setdefault(guild_id, [])
		guild = self.bot.get_guild(guild_id)
		promoted = False

		if queue_messages:
			queued_msg_info = queue_messages.pop(0)
			try:
				channel = guild.get_channel(queued_msg_info["channel_id"]) or await self.bot.fetch_channel(queued_msg_info["channel_id"])
				message = await channel.fetch_message(queued_msg_info["message_id"])
				await message.edit(content=None, embed=embed, view=view)
				guild_now_message[guild_id] = {
					"channel_id": channel.id, "message_id": message.id,
					"title": embed.description or "Unknown"
				}
				promoted = True
			except Exception as e:
				print(f"[MUSIC] Failed to promote queued message: {e}")

		if not promoted:
			channel_id = guild_last_text_channel.get(guild_id)
			if channel_id:
				try:
					channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
					message = await channel.send(embed=embed, view=view)
					guild_now_message[guild_id] = {
						"channel_id": channel.id, "message_id": message.id,
						"title": embed.description or "Unknown"
					}
				except Exception as e:
					print(f"[MUSIC] Failed to send now-playing: {e}")

	# ── Embed builders ────────────────────────────────────────────────────────

	def _build_now_playing_embed_from_wl(self, track: wavelink.Playable, guild_id: int) -> discord.Embed:
		title = track.title or "Unknown title"
		url = track.uri
		author = track.author or "Unknown"
		duration = _format_duration_seconds(track.length // 1000 if track.length else None)
		artwork = track.artwork

		description = f"[{title}]({url})" if url else title
		embed = discord.Embed(title="🎵 Now Playing", description=description, color=0x1DB954)
		if artwork:
			embed.set_thumbnail(url=artwork)
		embed.add_field(name="Artist", value=author, inline=True)
		embed.add_field(name="Duration", value=duration, inline=True)
		embed.add_field(name="Source", value="Lavalink", inline=True)
		embed.set_footer(text="Powered by Lavalink • nextgencoders.xyz")
		return embed

	def _build_now_playing_embed_from_ytdl(self, info: dict, requested_by: str, tier: str) -> discord.Embed:
		title = info.get("title") or "Unknown title"
		web_url = info.get("webpage_url") or info.get("url")
		uploader = info.get("uploader") or info.get("channel") or "Unknown"
		duration = _format_duration_seconds(info.get("duration"))
		thumbnail = info.get("thumbnail")
		quality = _get_quality_label(tier)

		description = f"[{title}]({web_url})" if web_url else title
		embed = discord.Embed(title="🎵 Now Playing", description=description, color=0x1DB954)
		if thumbnail:
			embed.set_thumbnail(url=thumbnail)
		embed.add_field(name="Artist/Channel", value=uploader, inline=True)
		embed.add_field(name="Duration", value=duration, inline=True)
		embed.add_field(name="Requested By", value=requested_by, inline=True)
		embed.add_field(name="Quality", value=quality, inline=True)
		embed.set_footer(text="HD free • 320kbps for Premium/Gold")
		return embed

	# ── Music control helpers ─────────────────────────────────────────────────

	def _dm_usage_key(self, interaction: discord.Interaction) -> str:
		return f"dm_{interaction.user.id}"

	def _bot_missing_from_guild(self, interaction: discord.Interaction) -> bool:
		if interaction.guild_id is None:
			return False
		guild = self.bot.get_guild(interaction.guild_id)
		if guild is None:
			return True
		return guild.get_member(self.bot.user.id) is None

	async def _resolve_paid_usage_key(self, interaction: discord.Interaction) -> str | None:
		if not self._bot_missing_from_guild(interaction):
			return None
		try:
			dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
			if dm_channel is not None:
				return str(dm_channel.id)
		except Exception as e:
			print(f"[PAID USAGE KEY] {e}")
		return self._dm_usage_key(interaction)

	def _should_deliver_paid_output_in_dm(self, interaction: discord.Interaction) -> bool:
		return self._bot_missing_from_guild(interaction)

	async def _deliver_paid_attachment(self, interaction, content, filename, payload_bytes):
		if not self._should_deliver_paid_output_in_dm(interaction):
			await interaction.followup.send(
				content=content, file=discord.File(io.BytesIO(payload_bytes), filename=filename)
			)
			return
		try:
			await interaction.user.send(
				f"{content}\n\n📩 Sent to DMs since I'm not in that server.",
				file=discord.File(io.BytesIO(payload_bytes), filename=filename),
			)
			await interaction.followup.send("📩 Result sent to your DMs.")
		except discord.Forbidden:
			await interaction.followup.send("⚠️ Couldn't DM you — please enable DMs and try again.")

	async def _ensure_music_control(self, interaction: discord.Interaction) -> bool:
		if interaction.guild is None:
			await interaction.followup.send("❌ This can only be used in a server.", ephemeral=False)
			return False
		voice_client = interaction.guild.voice_client
		if not voice_client or not voice_client.is_connected():
			await interaction.followup.send("❌ I'm not connected to a voice channel.", ephemeral=False)
			return False
		user_voice = interaction.user.voice
		if not user_voice or user_voice.channel.id != voice_client.channel.id:
			await interaction.followup.send(f"🎧 Join {voice_client.channel.mention} to control playback.", ephemeral=False)
			return False
		return True

	# ── Queue command ─────────────────────────────────────────────────────────

	@app_commands.command(name="queue", description="📋 Show the current music queue")
	async def queue_slash(self, interaction: discord.Interaction):
		if interaction.guild is None:
			await interaction.response.send_message("❌ This can only be used in a server.", ephemeral=True)
			return

		player: wavelink.Player | None = interaction.guild.voice_client if self._lavalink_available() else None
		embed = discord.Embed(title="📋 Music Queue", color=0x1DB954)

		if player and isinstance(player, wavelink.Player):
			current = player.current
			queue = player.queue
			if not current and queue.is_empty:
				await interaction.response.send_message("❌ The queue is empty and nothing is playing.", ephemeral=False)
				return
			if current:
				duration = _format_duration_seconds(current.length // 1000 if current.length else None)
				url = current.uri
				display = f"[{current.title}]({url})" if url else current.title
				embed.add_field(name="🎵 Now Playing", value=f"{display} `{duration}`", inline=False)
			if not queue.is_empty:
				lines = []
				for i, track in enumerate(list(queue)[:15], start=1):
					duration = _format_duration_seconds(track.length // 1000 if track.length else None)
					url = track.uri
					display = f"[{track.title}]({url})" if url else track.title
					lines.append(f"`{i}.` {display} `{duration}`")
				count = len(queue)
				if count > 15:
					lines.append(f"*...and {count - 15} more*")
				embed.add_field(name=f"⏳ Up Next ({count} tracks)", value="\n".join(lines), inline=False)
			else:
				embed.add_field(name="⏳ Up Next", value="Queue is empty.", inline=False)
		else:
			await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=False)
			return

		await interaction.response.send_message(embed=embed, ephemeral=False)

	@app_commands.command(name="volume_up", description="🔊 Increase music volume by 10%")
	async def volume_up_slash(self, interaction: discord.Interaction):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		await interaction.response.defer(ephemeral=False)
		if not await self._ensure_music_control(interaction):
			return
		await self._music_adjust_volume(interaction, 10)

	@app_commands.command(name="volume_down", description="🔉 Decrease music volume by 10%")
	async def volume_down_slash(self, interaction: discord.Interaction):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		await interaction.response.defer(ephemeral=False)
		if not await self._ensure_music_control(interaction):
			return
		await self._music_adjust_volume(interaction, -10)

	@app_commands.command(name="autoplay", description="🔁 Toggle autoplay when queue ends")
	@app_commands.describe(enabled="Enable or disable autoplay")
	async def autoplay_slash(self, interaction: discord.Interaction, enabled: bool):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		guild_autoplay[interaction.guild.id] = enabled
		status = "enabled ✅" if enabled else "disabled ⏹️"
		await interaction.response.send_message(f"🔁 Autoplay is now **{status}**.", ephemeral=False)

		# If the user just enabled autoplay and the bot is connected but idle
		# (queue empty, nothing playing), kick the advance loop immediately —
		# otherwise autoplay only fires on the *next* song end, not right now.
		if enabled:
			guild_id = interaction.guild.id
			vc = interaction.guild.voice_client
			queue_empty = not guild_ytdl_queue.get(guild_id)
			bot_idle = not vc or not (vc.is_playing() or vc.is_paused())
			if vc and vc.is_connected() and queue_empty and bot_idle:
				asyncio.create_task(self._ytdl_auto_advance(guild_id))

	@app_commands.command(name="lyrics", description="📝 Show full lyrics for the current track")
	async def lyrics_slash(self, interaction: discord.Interaction):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		track = guild_now_playing_track.get(interaction.guild.id)
		if not track:
			await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=False)
			return
		title = (track.get("title") or "").strip()
		artist = (track.get("uploader") or "").strip()
		if not title:
			await interaction.response.send_message("❌ Couldn't determine the current track title.", ephemeral=False)
			return
		await interaction.response.defer()
		params = {"track_name": title}
		if artist and artist.lower() != "unknown":
			params["artist_name"] = artist
		try:
			async with aiohttp.ClientSession() as session:
				async with session.get("https://lrclib.net/api/get", params=params, timeout=aiohttp.ClientTimeout(total=12)) as resp:
					if resp.status != 200:
						await interaction.followup.send(f"❌ Lyrics not found for **{title}**.")
						return
					data = await resp.json()
			lyrics = (data.get("plainLyrics") or "").strip()
			if not lyrics:
				await interaction.followup.send(f"❌ No static full lyrics available for **{title}**.")
				return
			content = f"📝 **Lyrics: {title}**\n"
			if artist and artist.lower() != "unknown":
				content += f"👤 **Artist:** {artist}\n"
			content += "\n" + lyrics
			for i in range(0, len(content), 1900):
				await interaction.followup.send(content[i:i+1900])
		except Exception as e:
			print(f"[LYRICS] Error: {e}")
			await interaction.followup.send("❌ Failed to fetch lyrics right now.")

	@app_commands.command(name="image_search", description="🖼️ Search free images by text query")
	@app_commands.describe(query="What image do you want to find?")
	async def image_search_slash(self, interaction: discord.Interaction, query: str):
		await interaction.response.defer()
		wikimedia_url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={quote_plus(query)}&gsrnamespace=6&gsrlimit=8&prop=imageinfo&iiprop=url&format=json"
		openverse_url = f"https://api.openverse.org/v1/images/?q={quote_plus(query)}&page_size=8"
		try:
			results = []
			async with aiohttp.ClientSession() as session:
				async with session.get(wikimedia_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
					if resp.status == 200:
						data = await resp.json()
						pages = (data.get("query") or {}).get("pages") or {}
						for page in pages.values():
							info = (page.get("imageinfo") or [{}])[0]
							img = info.get("url")
							title = page.get("title", "Image")
							if img:
								results.append((f"Wikimedia • {title.replace('File:', '')}", img))

				async with session.get(openverse_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
					if resp.status == 200:
						data = await resp.json()
						for item in data.get("results", []):
							img = item.get("url")
							title = item.get("title") or "Openverse image"
							if img:
								results.append((f"Openverse • {title}", img))

			if not results:
				await interaction.followup.send(f"❌ No images found for **{query}**.")
				return
			embed = discord.Embed(title=f"🖼️ Image search: {query}", description="Free images from Wikimedia Commons + Openverse", color=0x4DA3FF)
			embed.set_image(url=results[0][1])
			lines = [f"`{i + 1}.` [{t}]({u})" for i, (t, u) in enumerate(results[:5])]
			embed.add_field(name="Results", value="\n".join(lines), inline=False)
			await interaction.followup.send(embed=embed)
		except Exception as e:
			print(f"[IMAGE SEARCH] Error: {e}")
			await interaction.followup.send("❌ Failed to search images right now.")

	@app_commands.command(name="model", description="🧠 Change chat model for this channel/DM")
	@app_commands.describe(model="Choose the model")
	@app_commands.choices(model=[
		app_commands.Choice(name="GPT-OSS-120B (DEFAULT)", value="openai/gpt-oss-120b"),
		app_commands.Choice(name="moonshotai/kimi-k2-instruct", value="moonshotai/kimi-k2-instruct"),
		app_commands.Choice(name="allam-2-7b", value="allam-2-7b"),
		app_commands.Choice(name="qwen/qwen3-32b", value="qwen/qwen3-32b"),
		app_commands.Choice(name="llama-3.3-70b-versatile", value="llama-3.3-70b-versatile"),
		app_commands.Choice(name="meta-llama/llama-4-scout-17b-16e-instruct", value="meta-llama/llama-4-scout-17b-16e-instruct"),
		app_commands.Choice(name="llama-3.1-8b-instant", value="llama-3.1-8b-instant"),
	])
	async def model_slash(self, interaction: discord.Interaction, model: app_commands.Choice[str]):
		if memory is None:
			await interaction.response.send_message("❌ Memory system is not ready.", ephemeral=True)
			return
		chan_id = f"dm_{interaction.user.id}" if isinstance(interaction.channel, discord.DMChannel) else str(interaction.channel.id)
		old_model = memory.get_channel_model(chan_id)
		new_model = model.value
		memory.save_channel_model(chan_id, new_model)
		memory.clear_channel_messages(chan_id)
		if clear_runtime_channel_memory is not None:
			clear_runtime_channel_memory(chan_id)
		memory.persist()
		await interaction.response.send_message(
			f"🧠✨ **Model switched!**\n"
			f"🔁 The model has been changed to **{MODEL_LABELS.get(new_model, new_model)}** from **{MODEL_LABELS.get(old_model, old_model)}**!\n"
			"🧹 Previous memory has been cleared - this chat is now fresh! 🚀"
		)

	# ── Music controls ────────────────────────────────────────────────────────

	async def _music_pause(self, interaction: discord.Interaction):
		player: wavelink.Player = interaction.guild.voice_client
		if player and isinstance(player, wavelink.Player):
			if player.playing and not player.paused:
				await player.pause(True)
				await interaction.followup.send("⏸️ Paused.", ephemeral=False)
				return
			if player.paused:
				await interaction.followup.send("⏸️ Already paused.", ephemeral=False)
				return

		vc = interaction.guild.voice_client
		if vc and hasattr(vc, "is_playing") and vc.is_playing() and hasattr(vc, "pause"):
			vc.pause()
			await interaction.followup.send("⏸️ Paused.", ephemeral=False)
		else:
			await interaction.followup.send("❌ Nothing is playing.", ephemeral=False)

	async def _music_resume(self, interaction: discord.Interaction):
		player: wavelink.Player = interaction.guild.voice_client
		if player and isinstance(player, wavelink.Player):
			if player.paused:
				await player.pause(False)
				await interaction.followup.send("▶️ Resumed.", ephemeral=False)
				return
			if player.playing:
				await interaction.followup.send("▶️ Already playing.", ephemeral=False)
				return

		vc = interaction.guild.voice_client
		if vc and hasattr(vc, "is_paused") and vc.is_paused() and hasattr(vc, "resume"):
			vc.resume()
			await interaction.followup.send("▶️ Resumed.", ephemeral=False)
		else:
			await interaction.followup.send("❌ Nothing is paused.", ephemeral=False)

	async def _music_stop(self, interaction: discord.Interaction):
		player: wavelink.Player = interaction.guild.voice_client
		if player and isinstance(player, wavelink.Player):
			player.queue.clear()
			await player.stop()
			await player.disconnect()
		elif player:
			guild_ytdl_queue.pop(interaction.guild.id, None)
			player.stop()
			try:
				await player.disconnect(force=True)
			except Exception:
				pass
		guild_queue_messages.pop(interaction.guild.id, None)
		guild_now_message.pop(interaction.guild.id, None)
		guild_now_playing_track.pop(interaction.guild.id, None)
		ended_embed = discord.Embed(title="⏹️ Ended", description="Playback stopped.", color=0x5C5C5C)
		ended_embed.set_footer(text="Playback stopped • Queue cleared")
		try:
			await interaction.message.edit(embed=ended_embed, view=None)
		except Exception:
			await interaction.followup.send("⏹️ Stopped and disconnected.", ephemeral=False)

	async def _music_next(self, interaction: discord.Interaction):
		player: wavelink.Player = interaction.guild.voice_client
		if not player or not isinstance(player, wavelink.Player):
			# yt-dlp fallback skip
			vc = interaction.guild.voice_client
			if vc and hasattr(vc, 'is_playing') and vc.is_playing():
				queue = guild_ytdl_queue.get(interaction.guild.id, [])
				if not queue:
					await interaction.followup.send("❌ Queue is empty.", ephemeral=False)
					return
				vc.stop()  # triggers _after_playback → _ytdl_auto_advance
				await interaction.followup.send("⏭️ Skipped.", ephemeral=False)
				return
			await interaction.followup.send("❌ Not connected.", ephemeral=False)
			return
		if player.queue.is_empty:
			await interaction.followup.send("❌ Queue is empty.", ephemeral=False)
			return
		await player.stop()
		await interaction.followup.send("⏭️ Skipped.", ephemeral=False)

	async def _music_previous(self, interaction: discord.Interaction):
		history = guild_history.get(interaction.guild.id, [])
		if not history:
			await interaction.followup.send("❌ No previous tracks.", ephemeral=False)
			return
		previous_track = history.pop()
		player: wavelink.Player = interaction.guild.voice_client
		if not player or not isinstance(player, wavelink.Player):
			await interaction.followup.send("❌ Not connected.", ephemeral=False)
			return
		# Re-insert current track at front of queue
		if player.current:
			player.queue.put_at(0, player.current)
		await player.play(previous_track)
		embed = self._build_now_playing_embed_from_wl(previous_track, interaction.guild.id)
		view = MusicControls(self, interaction.guild.id)
		guild_last_text_channel[interaction.guild.id] = interaction.channel.id
		guild_now_message[interaction.guild.id] = {
			"channel_id": interaction.channel.id,
			"message_id": interaction.message.id,
			"title": embed.description or "Unknown",
		}
		try:
			await interaction.message.edit(embed=embed, view=view)
		except Exception:
			await interaction.followup.send(embed=embed, view=view)

	async def _music_adjust_volume(self, interaction: discord.Interaction, delta: int):
		"""Adjust guild playback volume by delta percentage points within 10%-200%."""
		voice_client = interaction.guild.voice_client
		if not voice_client or not voice_client.is_connected():
			await interaction.followup.send("❌ I'm not connected to a voice channel.", ephemeral=False)
			return

		guild_id = interaction.guild.id
		current = guild_volume.get(guild_id, 100)
		new_volume = max(10, min(200, current + delta))
		if new_volume == current:
			await interaction.followup.send(f"🔊 Volume is already at **{new_volume}%**.", ephemeral=False)
			return

		guild_volume[guild_id] = new_volume
		if isinstance(voice_client, wavelink.Player):
			await voice_client.set_volume(new_volume)
		elif isinstance(getattr(voice_client, "source", None), discord.PCMVolumeTransformer):
			voice_client.source.volume = new_volume / 100

		await interaction.followup.send(f"🔊 Volume set to **{new_volume}%**.", ephemeral=False)

	# ── Play command ──────────────────────────────────────────────────────────

	_FILTER_CHOICES = [
		app_commands.Choice(name="🎵 Normal (No Filter)", value="normal"),
		app_commands.Choice(name="🔊 Bass Boost", value="bass"),
		app_commands.Choice(name="🎤 Nightcore (Fast + High Pitch)", value="nightcore"),
		app_commands.Choice(name="🐌 Slowed + Reverb", value="slowed"),
		app_commands.Choice(name="🎧 8D Audio", value="8d"),
		app_commands.Choice(name="🎸 Treble Boost", value="treble"),
		app_commands.Choice(name="📻 Lo-Fi", value="lofi"),
		app_commands.Choice(name="🎭 Vaporwave", value="vaporwave"),
	]

	@app_commands.command(
		name="play",
		description="🎵 Play a song or playlist with audio filter"
	)
	@app_commands.describe(song="Song name, URL, or playlist URL", filter="Audio filter to apply")
	@app_commands.choices(filter=_FILTER_CHOICES)
	async def play_slash(self, interaction: discord.Interaction, song: str, filter: app_commands.Choice[str]):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		if not interaction.user.voice or not interaction.user.voice.channel:
			await interaction.response.send_message("🤔 Join a voice channel first, then use `/play [song name]` to start jamming! 🎵", ephemeral=True)
			return

		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ Checking your vote status...")

		if not await require_vote_deferred(interaction):
			return

		# Store filter preference for this guild
		guild_filters[interaction.guild.id] = filter.value

		await interaction.edit_original_response(content="🎵 Joining voice channel...")

		channel = interaction.user.voice.channel
		tier = get_tier_from_message(interaction)
		guild_last_text_channel[interaction.guild.id] = interaction.channel.id

		# ── Spotify → Lavalink ───────────────────────────────────────────────
		if _is_spotify_url(song) and self._lavalink_available():
			try:
				player: wavelink.Player = interaction.guild.voice_client
				if not player or not isinstance(player, wavelink.Player):
					player = await channel.connect(cls=wavelink.Player)
				elif player.channel.id != channel.id:
					await interaction.edit_original_response(
						content=f"❌ I'm already in {player.channel.mention}."
					)
					return
				await player.set_volume(guild_volume.get(interaction.guild.id, 100))

				await interaction.edit_original_response(content="🔍 Searching Spotify via Lavalink...")

				tracks = await wavelink.Playable.search(song)
				if not tracks:
					raise Exception("No results found.")

				if isinstance(tracks, wavelink.Playlist):
					added = 0
					first_track = None
					for track in tracks.tracks:
						if first_track is None and not player.playing:
							first_track = track
							await player.play(track)
						else:
							player.queue.put(track)
						added += 1

					embed = self._build_now_playing_embed_from_wl(
						first_track or tracks.tracks[0], interaction.guild.id
					)
					view = MusicControls(self, interaction.guild.id)
					status = f"📋 Playlist loaded! Playing first track, **{added - 1}** more queued."
					message = await interaction.followup.send(content=status, embed=embed, view=view, wait=True)
					guild_now_message[interaction.guild.id] = {
						"channel_id": message.channel.id, "message_id": message.id,
						"title": embed.description or "Unknown",
					}
				else:
					track = tracks[0] if isinstance(tracks, list) else tracks
					if player.playing:
						player.queue.put(track)
						position = len(player.queue)
						queued_msg = await interaction.followup.send(
							f"✅ Queued **{track.title}** at position {position}.", wait=True
						)
						queue_messages = guild_queue_messages.setdefault(interaction.guild.id, [])
						queue_messages.append({"channel_id": queued_msg.channel.id, "message_id": queued_msg.id})
					else:
						await player.play(track)
						guild_now_playing_track[interaction.guild.id] = {
							"title": track.title or "Unknown",
							"uploader": track.author or "Unknown",
						}
						history = guild_history.setdefault(interaction.guild.id, [])
						if len(history) > 25:
							history.pop(0)

						embed = self._build_now_playing_embed_from_wl(track, interaction.guild.id)
						view = MusicControls(self, interaction.guild.id)
						message = await interaction.followup.send(embed=embed, view=view, wait=True)
						guild_now_message[interaction.guild.id] = {
							"channel_id": message.channel.id, "message_id": message.id,
							"title": embed.description or "Unknown",
						}
				return

			except Exception as e:
				print(f"[LAVALINK] Spotify play error: {e}")
				await interaction.edit_original_response(
					content=f"❌ Lavalink failed to load this Spotify link: {e}"
				)
				return

		# ── Everything else → yt-dlp ─────────────────────────────────────────

		voice_client = interaction.guild.voice_client
		try:
			if voice_client and voice_client.is_connected():
				if hasattr(voice_client, 'channel') and voice_client.channel.id != channel.id:
					await interaction.edit_original_response(
						content=f"❌ I'm already in {voice_client.channel.mention}."
					)
					return
			else:
				if voice_client:
					try:
						await voice_client.disconnect(force=True)
					except Exception:
						pass
				voice_client = await channel.connect()
		except Exception as e:
			print(f"[YTDL] Voice connect error: {e}")
			await interaction.edit_original_response(content="❌ Couldn't connect to your voice channel.")
			return

		await interaction.edit_original_response(content="🔍 Searching...")

		# ── Playlist handling ────────────────────────────────────────────
		if _is_playlist_url(song):
			try:
				entries = await _ytdl_extract_playlist(song, tier)
			except Exception as e:
				print(f"[YTDL] Playlist extraction error: {e}")
				await interaction.edit_original_response(content="❌ Couldn't load that playlist.")
				return

			if not entries:
				await interaction.edit_original_response(content="❌ Playlist appears to be empty.")
				return

			first = entries[0]
			stream_url = first.get("url")
			if not stream_url:
				await interaction.edit_original_response(content="❌ Couldn't get a stream URL for the first track.")
				return

			# Queue remaining tracks
			remaining = entries[1:]
			queue = guild_ytdl_queue.setdefault(interaction.guild.id, [])
			for entry in remaining:
				if entry.get("url"):
					queue.append({
						"title": entry.get("title") or "Unknown",
						"web_url": entry.get("webpage_url") or entry.get("url"),
						"uploader": entry.get("uploader") or entry.get("channel") or "Unknown",
						"duration": entry.get("duration"),
						"thumbnail": entry.get("thumbnail"),
						"stream_url": entry.get("url"),
						"requested_by": interaction.user.mention,
						"tier": tier,
						"filter": filter.value,
					})

			def _after_playback(error):
				if error:
					print(f"[YTDL] Playback error: {error}")
				asyncio.run_coroutine_threadsafe(
					self._ytdl_auto_advance(interaction.guild.id),
					self.bot.loop
				)

			volume = guild_volume.get(interaction.guild.id, 100) / 100
			selected_filter = guild_filters.get(interaction.guild.id, "normal")
			source = discord.PCMVolumeTransformer(
				discord.FFmpegPCMAudio(stream_url, **_get_ffmpeg_options(selected_filter)),
				volume=volume,
			)
			voice_client.play(source, after=_after_playback)
			_apply_bitrate(voice_client, tier)
			guild_last_activity[interaction.guild.id] = asyncio.get_event_loop().time()
			guild_now_playing_track[interaction.guild.id] = {
				"title": first.get("title") or "Unknown",
				"web_url": first.get("webpage_url") or first.get("url"),
				"uploader": first.get("uploader") or first.get("channel") or "Unknown",
				"duration": first.get("duration"),
				"thumbnail": first.get("thumbnail"),
				"stream_url": stream_url,
				"requested_by": interaction.user.mention,
				"tier": tier,
				"filter": filter.value,
			}

			embed = self._build_now_playing_embed_from_ytdl(first, interaction.user.mention, tier)
			view = MusicControls(self, interaction.guild.id)
			total = len(entries)
			queued = len(remaining)
			status = f"📋 Playlist loaded! Playing first track, **{queued}** more queued." if queued else None
			message = await interaction.followup.send(content=status, embed=embed, view=view, wait=True)
			guild_now_message[interaction.guild.id] = {
				"channel_id": message.channel.id, "message_id": message.id,
				"title": embed.description or "Unknown",
			}
			return

		# ── Single track ─────────────────────────────────────────────────
		queries = _build_query_candidates(song)

		try:
			info = await _ytdl_extract(queries, tier)
		except Exception as e:
			print(f"[YTDL] Extraction error: {e}")
			await interaction.edit_original_response(content="❌ Couldn't find that song.")
			return

		stream_url = info.get("url")
		if not stream_url:
			await interaction.edit_original_response(content="❌ Found the song but couldn't get a stream URL.")
			return

		# Store track info for controls
		track_info = {
			"title": info.get("title") or "Unknown",
			"web_url": info.get("webpage_url") or info.get("url"),
			"uploader": info.get("uploader") or info.get("channel") or "Unknown",
			"duration": info.get("duration"),
			"thumbnail": info.get("thumbnail"),
			"stream_url": stream_url,
			"requested_by": interaction.user.mention,
			"tier": tier,
			"filter": filter.value,
		}

		def _after_playback(error):
			if error:
				print(f"[YTDL] Playback error: {error}")
			asyncio.run_coroutine_threadsafe(
				self._ytdl_auto_advance(interaction.guild.id),
				self.bot.loop
			)

		volume = guild_volume.get(interaction.guild.id, 100) / 100
		selected_filter = guild_filters.get(interaction.guild.id, "normal")
		source = discord.PCMVolumeTransformer(
			discord.FFmpegPCMAudio(stream_url, **_get_ffmpeg_options(selected_filter)),
			volume=volume,
		)
		voice_client.play(source, after=_after_playback)
		_apply_bitrate(voice_client, tier)
		guild_last_activity[interaction.guild.id] = asyncio.get_event_loop().time()
		guild_now_playing_track[interaction.guild.id] = track_info
		_add_to_recent_titles(interaction.guild.id, track_info.get("title", ""), track_info.get("web_url"))
		asyncio.create_task(self._prefetch_next_track(interaction.guild.id))

		embed = self._build_now_playing_embed_from_ytdl(info, interaction.user.mention, tier)
		view = MusicControls(self, interaction.guild.id)
		message = await interaction.followup.send(embed=embed, view=view, wait=True)
		guild_now_message[interaction.guild.id] = {
			"channel_id": message.channel.id, "message_id": message.id,
			"title": embed.description or "Unknown",
		}

	async def _ytdl_auto_advance(self, guild_id: int):
		"""yt-dlp fallback auto-advance with loop, dedup, prefetch, and lazy playlist resolve."""
		loop_mode = guild_loop_mode.get(guild_id, "off")
		print(f"[AUTOPLAY DEBUG] _ytdl_auto_advance called guild={guild_id} loop_mode={loop_mode} autoplay={guild_autoplay.get(guild_id, False)}")

		# ── Loop song: re-stream current track ────────────────────────────────
		if loop_mode == "song":
			current = guild_now_playing_track.get(guild_id, {})
			if current and current.get("web_url"):
				guild = self.bot.get_guild(guild_id)
				if not guild:
					return
				vc = guild.voice_client
				if not vc or not vc.is_connected():
					return
				try:
					info       = await _ytdl_extract([current["web_url"]], current.get("tier", "free"))
					stream_url = info.get("url")
					if not stream_url:
						raise ValueError("No stream URL")
					current["stream_url"] = stream_url

					def _after_loop(err):
						if err:
							print(f"[YTDL LOOP SONG] {err}")
						asyncio.run_coroutine_threadsafe(
							self._ytdl_auto_advance(guild_id), self.bot.loop
						)

					sel_filter = guild_filters.get(guild_id, "normal")
					volume     = guild_volume.get(guild_id, 100) / 100
					src = discord.PCMVolumeTransformer(
						discord.FFmpegPCMAudio(stream_url, **_get_ffmpeg_options(sel_filter)),
						volume=volume,
					)
					vc.play(src, after=_after_loop)
					_apply_bitrate(vc, current.get("tier", "basic"))
					guild_last_activity[guild_id] = asyncio.get_event_loop().time()
					return
				except Exception as e:
					print(f"[YTDL LOOP SONG] Re-play failed ({e}), falling through")

		await self._mark_now_playing_as_ended(guild_id)
		guild_now_message.pop(guild_id, None)

		# Record finished title for dedup
		finished = guild_now_playing_track.get(guild_id, {})
		if finished.get("title"):
			_add_to_recent_titles(guild_id, finished["title"], finished.get("web_url"))

		queue = guild_ytdl_queue.get(guild_id, [])
		print(f"[AUTOPLAY DEBUG] queue length={len(queue)} after loop checks")
		if loop_mode == "queue" and not queue:
			saved = guild_saved_queue.get(guild_id, [])
			if saved:
				guild_ytdl_queue[guild_id] = [dict(t) for t in saved]
				queue = guild_ytdl_queue[guild_id]

		# ── Autoplay when queue still empty ───────────────────────────────
		if not queue:
			if guild_autoplay.get(guild_id, False):
				seed   = finished.get("title")
				print(f"[AUTOPLAY DEBUG] Queue empty, autoplay ON, seed={seed!r}")
				recent = guild_recent_titles.get(guild_id, deque())

				# Try pre-fetched candidate first (fastest path — ~0 s delay)
				prefetched = guild_prefetched_autoplay.pop(guild_id, None)
				candidate  = None

				# Build a set of ALL recently played video IDs — not just the last one
				played_ids: set[str] = set(guild_recent_ids.get(guild_id, deque()))
				finished_id = _extract_yt_video_id(finished.get("web_url"))
				if finished_id:
					played_ids.add(finished_id)
				print(f"[AUTOPLAY] Excluding {len(played_ids)} already-played video IDs")

				if prefetched:
					p_id = _extract_yt_video_id(prefetched.get("webpage_url") or prefetched.get("web_url"))
					if p_id not in played_ids:
						candidate = prefetched
						print(f"[AUTOPLAY] Using prefetched: {prefetched.get('title')}")

				if not candidate:
					# Strategy 1: YouTube Radio mix — gives genuinely related tracks
					if finished_id:
						print(f"[AUTOPLAY] Trying YT mix for video_id={finished_id}")
						try:
							c = await _ytdl_fetch_yt_mix(finished_id, "free", played_ids)
							if c:
								candidate = c
								print(f"[AUTOPLAY] YT mix found: {c.get('title')}")
						except Exception as e:
							print(f"[AUTOPLAY] YT mix failed: {e}")

				if not candidate:
					# Strategy 2: search by artist name only (avoids getting the same song back)
					artist = ""
					if seed and " - " in seed:
						# "ARTIST - TITLE" → search by title part to find similar songs
						parts = seed.split(" - ", 1)
						artist = parts[0].strip()
					fallback_query = f"ytsearch15:{artist} mix" if artist else f"ytsearch15:songs similar to {seed or 'top hits'}"
					print(f"[AUTOPLAY] Fallback search: {fallback_query!r}")
					try:
						c = await _ytdl_extract_different_track(fallback_query, "free", seed or "")
						if c:
							c_id = _extract_yt_video_id(c.get("webpage_url") or c.get("url") or "")
							if c_id not in played_ids:
								candidate = c
								print(f"[AUTOPLAY] Fallback found: {c.get('title')}")
					except Exception as e:
						print(f"[AUTOPLAY] Fallback search failed: {e}")

				web_url    = (candidate.get("webpage_url") or candidate.get("url")) if candidate else None
				stream_url = candidate.get("url") if candidate else None
				if candidate and web_url:
					print(f"[AUTOPLAY] Playing next: {candidate.get('title')}")
					needs_resolve = not stream_url
					queue.append({
						"title":         candidate.get("title") or seed or "Unknown",
						"web_url":       web_url,
						"uploader":      candidate.get("uploader") or candidate.get("channel") or "Unknown",
						"duration":      candidate.get("duration"),
						"thumbnail":     candidate.get("thumbnail"),
						"stream_url":    stream_url,
						"needs_resolve": needs_resolve,
						"requested_by":  "Autoplay",
						"tier":          "free",
						"filter":        guild_filters.get(guild_id, "normal"),
					})
				else:
					print(f"[AUTOPLAY] No candidate found after all strategies, going idle")
					asyncio.create_task(self._start_idle_timer(guild_id))
					return
			else:
				asyncio.create_task(self._start_idle_timer(guild_id))
				return

		if not queue:
			asyncio.create_task(self._start_idle_timer(guild_id))
			return

		next_track = queue.pop(0)

		# ── Lazy resolve for playlist tracks ──────────────────────────────
		if next_track.get("needs_resolve") and next_track.get("web_url"):
			try:
				info = await _ytdl_extract([next_track["web_url"]], next_track.get("tier", "free"))
				next_track["stream_url"]    = info.get("url")
				next_track["needs_resolve"] = False
				if not next_track.get("title") and info.get("title"):
					next_track["title"] = info["title"]
			except Exception as e:
				print(f"[YTDL LAZY RESOLVE] {e} — skipping track")
				asyncio.create_task(self._ytdl_auto_advance(guild_id))
				return

		stream_url = next_track.get("stream_url")
		print(f"[AUTOPLAY DEBUG] next_track={next_track.get('title')!r} stream_url={'SET' if stream_url else 'MISSING'}")
		if not stream_url:
			print(f"[AUTOPLAY DEBUG] stream_url missing, skipping to next")
			asyncio.create_task(self._ytdl_auto_advance(guild_id))
			return

		guild = self.bot.get_guild(guild_id)
		if guild is None:
			print(f"[AUTOPLAY DEBUG] guild not found, aborting")
			return
		voice_client = guild.voice_client
		print(f"[AUTOPLAY DEBUG] voice_client={voice_client} connected={voice_client.is_connected() if voice_client else False}")
		if not voice_client or not voice_client.is_connected():
			guild_ytdl_queue.pop(guild_id, None)
			return

		def _after_playback(error):
			if error:
				print(f"[YTDL] Playback error: {error}")
			print(f"[AUTOPLAY DEBUG] _after_playback fired guild={guild_id} error={error}")
			asyncio.run_coroutine_threadsafe(
				self._ytdl_auto_advance(guild_id),
				self.bot.loop
			)

		try:
			sel_filter = next_track.get("filter") or guild_filters.get(guild_id, "normal")
			if next_track.get("requested_by") == "Autoplay":
				sel_filter = "normal"
			volume = guild_volume.get(guild_id, 100) / 100
			source = discord.PCMVolumeTransformer(
				discord.FFmpegPCMAudio(stream_url, **_get_ffmpeg_options(sel_filter)),
				volume=volume,
			)
			print(f"[AUTOPLAY DEBUG] Calling voice_client.play() for {next_track.get('title')!r}")
			voice_client.play(source, after=_after_playback)
			_apply_bitrate(voice_client, next_track.get("tier", "basic"))
			guild_last_activity[guild_id] = asyncio.get_event_loop().time()
			guild_now_playing_track[guild_id] = next_track
			asyncio.create_task(self._prefetch_next_track(guild_id))

			info = {
				"title":       next_track.get("title"),
				"webpage_url": next_track.get("web_url"),
				"uploader":    next_track.get("uploader"),
				"duration":    next_track.get("duration"),
				"thumbnail":   next_track.get("thumbnail"),
			}
			embed = self._build_now_playing_embed_from_ytdl(
				info, next_track.get("requested_by", "Unknown"), next_track.get("tier", "free")
			)
			lm = guild_loop_mode.get(guild_id, "off")
			if lm != "off":
				embed.add_field(name="Loop", value={"song": "🔂 Song", "queue": "🔁 Queue"}.get(lm, lm), inline=True)
			view = MusicControls(self, guild_id)
			await self._post_now_playing(guild_id, embed, view)
		except Exception as e:
			print(f"[YTDL] Auto-advance error: {e}", exc_info=True)
			asyncio.create_task(self._ytdl_auto_advance(guild_id))

	# ── Mode commands ─────────────────────────────────────────────────────────

	@app_commands.command(name="funmode", description="😎 Activate Fun Mode - jokes, memes & chill vibes")
	async def funmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "funny"
		memory.save_channel_mode(chan_id, "funny")
		channel_chess[chan_id] = False
		await interaction.response.send_message(
			"😎 **Fun mode activated!**\n"
			"🎮 **How to chat:**\n"
			"📍 In servers: `@Codunot AI your message`\n"
			"💬 In DMs: Just talk normally!\n\n"
			"I'll keep it fun, use emojis, and match your vibe. Try asking me anything! 💬✨",
			ephemeral=False
		)

	@app_commands.command(name="seriousmode", description="🤓 Activate Serious Mode - clean, fact-based help")
	async def seriousmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "serious"
		memory.save_channel_mode(chan_id, "serious")
		channel_chess[chan_id] = False
		await interaction.response.send_message(
			"🤓 **Serious mode ON.**\n"
			"📍 In servers: `@Codunot AI your question`\n"
			"💬 In DMs: Just type your question directly.\n\n"
			"I'll give clear, structured answers — great for homework, research, or coding help.",
			ephemeral=False
		)

	@app_commands.command(name="roastmode", description="🔥 Activate Roast Mode - playful burns")
	async def roastmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_modes[chan_id] = "roast"
		memory.save_channel_mode(chan_id, "roast")
		channel_chess[chan_id] = False
		await interaction.response.send_message(
			"🔥 **ROAST MODE ACTIVATED!**\n"
			"📍 In servers: `@Codunot AI roast me` or `@Codunot AI roast @someone`\n"
			"💬 In DMs: Just type who or what to roast!\n\n"
			"Brace yourself — I don't hold back (much) 😈",
			ephemeral=False
		)

	@app_commands.command(name="teachmerizz", description="💬 Activate Rizz Coach mode")
	@app_commands.describe(mode="Choose online (texting/DMs) or irl (real life)")
	@app_commands.choices(mode=[
		app_commands.Choice(name="online", value="online"),
		app_commands.Choice(name="irl", value="irl"),
	])
	async def teachmerizz_slash(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		if mode.value == "online":
			channel_modes[chan_id] = "rizz_online"
			memory.save_channel_mode(chan_id, "rizz_online")
			channel_chess[chan_id] = False
			await interaction.response.send_message(
				"💬 **Rizz Coach (Online) activated!**\n"
				"📍 In servers: `@Codunot AI` + your situation or screenshot\n"
				"💬 In DMs: Just type or paste your convo directly!\n\n"
				"Send a screenshot, paste a convo, or describe what's happening — I'll coach you through it 👇"
			)
		elif mode.value == "irl":
			channel_modes[chan_id] = "rizz_irl"
			memory.save_channel_mode(chan_id, "rizz_irl")
			channel_chess[chan_id] = False
			await interaction.response.send_message(
				"🗣️ **Rizz Coach (IRL) activated!**\n"
				"📍 In servers: `@Codunot AI` + describe your situation\n"
				"💬 In DMs: Just type what's going on!\n\n"
				"Describe the situation, ask for tips, or tell me what happened — I got you 👇"
			)

	@app_commands.command(name="chessmode", description="♟️ Activate Chess Mode - play chess with Codunot")
	async def chessmode_slash(self, interaction: discord.Interaction):
		is_dm = isinstance(interaction.channel, discord.DMChannel)
		chan_id = f"dm_{interaction.user.id}" if is_dm else str(interaction.channel.id)
		channel_chess[chan_id] = True
		channel_modes[chan_id] = "funny"
		chess_engine.new_board(chan_id)
		await interaction.response.send_message(
			"♟️ **Chess mode ACTIVATED!** You're playing white, I'm black.\n"
			"📍 **In servers:** Ping me with your move: `@Codunot AI e4`\n"
			"💬 **In DMs:** Just type your move directly: `e4`\n\n"
			"🎯 **Try these opening moves:**\n"
			"• `e4` — King's pawn\n"
			"• `d4` — Queen's pawn\n"
			"• `Nf3` — Knight to f3\n\n"
			"💡 Move formats: `e4`, `Nf3`, `Bxc4`, `O-O` (castle kingside), `O-O-O` (queenside)\n"
			"You can also ask for hints, resign, or chat about the position!\n"
			"Your move! ♟️",
			ephemeral=False
		)

	# ── AI generation commands ────────────────────────────────────────────────

	@app_commands.command(name="generate_image", description="🖼️ Generate an AI image from a text prompt")
	@app_commands.describe(prompt="Describe the image you want to generate")
	async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
		usage_key = await self._resolve_paid_usage_key(interaction)
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")
		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **daily attachments limit**. Either wait for the limits to renew, or contact my owner aarav_2022 on discord, for an upgrade!")
			return
		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **2 months' attachments limit**. Either wait for the limits to renew, or contact my owner aarav_2022 on discord, for an upgrade!")
			return
		await interaction.followup.send("🎨 **Cooking up your image... hang tight ✨**")
		try:
			boosted_prompt = await boost_image_prompt(prompt)
			image_bytes, balance = await generate_image(boosted_prompt, aspect_ratio="1:1")
			output_text = f"{interaction.user.mention} 🖼️ Generated: `{prompt[:150]}{'...' if len(prompt) > 150 else ''}`"
			await self._deliver_paid_attachment(interaction, output_text, "generated_image.png", image_bytes)
			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key, money_left=balance)
			save_usage()
		except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
			print(f"[SLASH IMAGE ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} ⏱️ The image API timed out after multiple attempts. The server may be busy — please try again in a moment.")
		except ImageAPIError as e:
			print(f"[SLASH IMAGE ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} ⏱️ The image API returned a server error after multiple attempts. The server may be busy — please try again in a moment.")
		except Exception as e:
			print(f"[SLASH IMAGE ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} 🤔 Couldn't generate image right now.")

	@app_commands.command(name="generate_video", description="🎬 Generate an AI video from a text prompt")
	@app_commands.describe(prompt="Describe the video you want to generate")
	async def generate_video_slash(self, interaction: discord.Interaction, prompt: str):
		usage_key = await self._resolve_paid_usage_key(interaction)
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")
		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **daily attachments limit**. Either wait for the limits to renew, or contact my owner aarav_2022 on discord, for an upgrade!")
			return
		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **2 months' attachments limit**. Either wait for the limits to renew, or contact my owner aarav_2022 on discord, for an upgrade!")
			return
		await interaction.followup.send("🎬 **Rendering your video... this may take up to ~1 min ⏳**")
		try:
			boosted_prompt = await boost_video_prompt(prompt)
			video_bytes = await text_to_video_512(prompt=boosted_prompt)
			output_text = f"{interaction.user.mention} 🎬 Generated: `{prompt[:150]}{'...' if len(prompt) > 150 else ''}`"
			await self._deliver_paid_attachment(interaction, output_text, "generated_video.mp4", video_bytes)
			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()
		except Exception as e:
			print(f"[SLASH VIDEO ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} 🤔 Couldn't generate video right now.")

	@app_commands.command(name="generate_tts", description="🔊 Generate text-to-speech audio — pick a voice & language")
	@app_commands.describe(
		text="The text you want to convert to speech",
		language="Choose the language for the speech",
		voice="Choose a voice (pick language first for filtered list)",
	)
	async def generate_tts_slash(
		self,
		interaction: discord.Interaction,
		text: str,
		language: str,
		voice: str,
	):
		lang = language
		if lang not in EDGE_TTS_LANG_VOICES:
			await interaction.response.send_message(
				f"🚫 Unknown language **{lang}**. Use the autocomplete to pick a valid language.",
				ephemeral=True,
			)
			return

		voices = EDGE_TTS_LANG_VOICES[lang]
		if voice not in voices:
			await interaction.response.send_message(
				f"🚫 Unknown voice **{voice}** for **{lang}**. Use the autocomplete to pick a valid voice.",
				ephemeral=True,
			)
			return
		voice_code = voice

		usage_key = await self._resolve_paid_usage_key(interaction)
		await interaction.response.defer()
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		await interaction.edit_original_response(content="✅ **Vote verified! You're good to go.**")
		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **daily attachments limit**. Either wait for the limits to renew, or contact my owner aarav_2022 on discord, for an upgrade!")
			return
		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.followup.send("🚫 You've hit your **2 months' attachments limit**. Either wait for the limits to renew, or contact my owner aarav_2022 on discord, for an upgrade!")
			return
		await interaction.followup.send(
			f"🔊 **Generating your audio** (voice: **{voice_code}**, language: **{lang}**)... almost there 🎙️"
		)
		try:
			polished_text = await polish_text_for_tts(text)
			audio_bytes = await generate_tts_mp3(polished_text, voice_code)
			output_text = f"{interaction.user.mention} 🔊 TTS ({voice_code} / {lang}): `{text[:200]}{'...' if len(text) > 200 else ''}`"
			await self._deliver_paid_attachment(interaction, output_text, "speech.mp3", audio_bytes)
			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()
		except Exception as e:
			print(f"[SLASH TTS ERROR] {e}")
			traceback.print_exc()
			await interaction.followup.send(f"{interaction.user.mention} 🤔 Couldn't generate speech right now.")

	@generate_tts_slash.autocomplete("language")
	async def _tts_language_autocomplete(
		self,
		interaction: discord.Interaction,
		current: str,
	) -> list[app_commands.Choice[str]]:
		return [
			app_commands.Choice(name=lang, value=lang)
			for lang in EDGE_TTS_LANG_VOICES
			if current.lower() in lang.lower()
		][:25]

	@generate_tts_slash.autocomplete("voice")
	async def _tts_voice_autocomplete(
		self,
		interaction: discord.Interaction,
		current: str,
	) -> list[app_commands.Choice[str]]:
		lang_choice = getattr(interaction.namespace, "language", None)
		if isinstance(lang_choice, app_commands.Choice):
			lang_name = lang_choice.value
		elif isinstance(lang_choice, str):
			lang_name = lang_choice
		else:
			lang_name = None
		if lang_name and lang_name in EDGE_TTS_LANG_VOICES:
			voices = EDGE_TTS_LANG_VOICES[lang_name]
		else:
			voices = EDGE_TTS_ALL_VOICES
		return [
			app_commands.Choice(name=v, value=v)
			for v in voices
			if current.lower() in v.lower()
		][:25]

	# ── Utility ───────────────────────────────────────────────────────────────

	async def _send_long_interaction_message(self, interaction: discord.Interaction, text: str):
		max_len = 2000
		remaining = (text or "").strip()
		while remaining:
			if len(remaining) <= max_len:
				await interaction.followup.send(remaining, ephemeral=False)
				break
			split_at = max(remaining.rfind("\n", 0, max_len), remaining.rfind(" ", 0, max_len))
			if split_at <= 0:
				split_at = max_len
			else:
				split_at += 1
			await interaction.followup.send(remaining[:split_at], ephemeral=False)
			remaining = remaining[split_at:]

	def _safe_json_parse(self, payload: str) -> dict | None:
		if not payload:
			return None
		cleaned = payload.strip()
		if cleaned.startswith("```"):
			cleaned = cleaned.strip("`")
			if cleaned.lower().startswith("json"):
				cleaned = cleaned[4:]
			cleaned = cleaned.strip()
		try:
			return json.loads(cleaned)
		except Exception:
			start = cleaned.find("{")
			end = cleaned.rfind("}")
			if start != -1 and end != -1 and start < end:
				try:
					return json.loads(cleaned[start:end + 1])
				except Exception:
					return None
		return None

	def _compact_message_for_prompt(self, text: str, max_len: int = 180) -> str:
		clean = " ".join((text or "").split())
		if not clean:
			return ""
		tokens = clean.split(" ")
		compacted: list[str] = []
		last = None
		repeat_count = 0
		for token in tokens:
			if token == last:
				repeat_count += 1
				if repeat_count <= 3:
					compacted.append(token)
				continue
			last = token
			repeat_count = 1
			compacted.append(token)
		result = " ".join(compacted)
		if len(result) > max_len:
			return result[:max_len].rstrip() + "..."
		return result

	def _clean_reasoning_items(self, items: list[str]) -> list[str]:
		seen = set()
		cleaned: list[str] = []
		for item in items:
			line = self._compact_message_for_prompt(str(item), max_len=170)
			if not line:
				continue
			key = line.lower()
			if key in seen:
				continue
			seen.add(key)
			cleaned.append(line)
			if len(cleaned) >= 4:
				break
		return cleaned

	async def _collect_recent_user_messages(self, channel, user_id, limit=60, max_scan=4000):
		messages: list[str] = []
		scanned = 0
		fetch_failed = False
		try:
			async for message in channel.history(limit=max_scan):
				scanned += 1
				if message.author.bot:
					continue
				if message.author.id != user_id:
					continue
				content = self._compact_message_for_prompt((message.content or "").strip(), max_len=180)
				if not content or len(content) < 3:
					continue
				messages.append(content)
				if len(messages) >= limit:
					break
		except Exception as e:
			fetch_failed = True
			print(f"[GUESSAGE FETCH ERROR] {e}")
		messages.reverse()
		return messages, scanned, fetch_failed

	async def _collect_recent_user_messages_across_guild(self, guild, user_id, exclude_channel_ids=None, limit=60, max_scan_per_channel=1200):
		messages: list[str] = []
		scanned_total = 0
		fetch_failed = False
		channels_used = 0
		exclude_ids = exclude_channel_ids or set()
		for channel in guild.text_channels:
			if channel.id in exclude_ids:
				continue
			channel_messages, scanned_count, failed = await self._collect_recent_user_messages(
				channel, user_id, limit=max(1, limit - len(messages)), max_scan=max_scan_per_channel,
			)
			scanned_total += scanned_count
			fetch_failed = fetch_failed or failed
			if channel_messages:
				channels_used += 1
				messages.extend(channel_messages)
			if len(messages) >= limit:
				break
		if len(messages) > limit:
			messages = messages[-limit:]
		return messages, scanned_total, fetch_failed, channels_used

	@app_commands.command(name="guessage", description="🔍 Guess a user's age range from recent messages (AI estimate)")
	@app_commands.describe(target_user="The user whose age you want estimated")
	async def guessage_slash(self, interaction: discord.Interaction, target_user: discord.User):
		if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
			await interaction.response.send_message("❌ Can't use this here.", ephemeral=False)
			return
		await interaction.response.defer(ephemeral=False)
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		await interaction.edit_original_response(content="🔎 **Collecting recent messages...**")
		recent_messages, scanned_count, fetch_failed = await self._collect_recent_user_messages(
			interaction.channel, target_user.id, limit=60,
		)
		source_channels_used = 1 if recent_messages else 0
		if len(recent_messages) == 0 and interaction.guild is not None:
			await interaction.edit_original_response(content="🔎 **Searching other channels...**")
			exclude_channel_ids: set[int] = set()
			if interaction.channel_id is not None:
				exclude_channel_ids.add(interaction.channel_id)
			alt_messages, alt_scanned, alt_fetch_failed, alt_channels_used = await self._collect_recent_user_messages_across_guild(
				interaction.guild, target_user.id, exclude_channel_ids=exclude_channel_ids, limit=60,
			)
			scanned_count += alt_scanned
			fetch_failed = fetch_failed or alt_fetch_failed
			if alt_messages:
				recent_messages = alt_messages
				source_channels_used = alt_channels_used
		sample_count = len(recent_messages)
		if sample_count < 10:
			error_hint = " Missing **Read Message History** permission?" if fetch_failed else ""
			await interaction.followup.send(
				f"⚠️ Only **{sample_count}** messages found after scanning **{scanned_count}**. Need at least 10.{error_hint}"
			)
			return
		await interaction.edit_original_response(content="🧠 **Analyzing...**")
		joined_messages = "\n".join(f"- {line}" for line in recent_messages)
		prompt = (
			"You estimate an approximate age range from message-writing style only. "
			"Never claim certainty and keep it strictly as a moderation insight.\n\n"
			"Return ONLY strict JSON:\n"
			"{\n  \"age_range\": \"13-18\",\n  \"exact_guess\": 16,\n  \"confidence\": \"low|medium|high\",\n"
			"  \"reasoning\": [\"reason 1\", \"reason 2\", \"reason 3\"]\n}\n\n"
			f"Sample count: {sample_count}\n\nUser messages:\n{joined_messages}"
		)
		result_text = await call_google_ai_studio(prompt=prompt, temperature=0.2)
		payload = self._safe_json_parse(result_text or "")
		if not payload:
			await interaction.followup.send("🤔 Couldn't parse AI output. Try again.")
			return
		age_range = str(payload.get("age_range") or "Unknown")
		exact_guess = payload.get("exact_guess")
		confidence = str(payload.get("confidence") or "unknown").capitalize()
		reasoning = payload.get("reasoning") or []
		if not isinstance(reasoning, list):
			reasoning = [str(reasoning)]
		reasoning = self._clean_reasoning_items([str(i) for i in reasoning])
		reasoning_lines = "\n".join(f"• {item}" for item in reasoning) or "• Not enough signal."
		confidence_badge = {"high": "🟢 High", "medium": "🟡 Medium", "low": "🔴 Low"}.get(confidence.lower(), "⚪ Unknown")
		guess_display = str(exact_guess) if exact_guess is not None else "Unknown"
		embed = discord.Embed(
			title="🧭 Message Style Insight Panel",
			description=f"Target: {target_user.mention}\n**Range:** `{age_range}` • **Best Guess:** `{guess_display}` • **Confidence:** {confidence_badge}",
			color=0x8A63D2,
		)
		embed.add_field(name="📊 Stats", value=f"• Messages: **{sample_count}**\n• Scanned: **{scanned_count}**\n• Channels: **{source_channels_used}**", inline=False)
		embed.add_field(name="🧠 Why", value=reasoning_lines, inline=False)
		embed.add_field(name="⚠️ Important", value="Style-based estimate only. Never use for verification.", inline=False)
		embed.set_footer(text=f"Requested by {interaction.user.display_name} • /guessage")
		if target_user.display_avatar:
			embed.set_thumbnail(url=target_user.display_avatar.url)
		await interaction.edit_original_response(content=None, embed=embed)

	def _normalize_transcribe_url(self, url: str) -> str | None:
		from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
		try:
			parsed = urlparse((url or "").strip())
		except Exception:
			return None
		if parsed.scheme not in {"http", "https"}:
			return None
		host = (parsed.hostname or "").lower()
		if not host:
			return None
		host = TRANSCRIBE_HOST_NORMALIZATION.get(host, host)
		host_for_check = host[4:] if host.startswith("www.") else host
		allowed = host in ALLOWED_TRANSCRIBE_HOSTS or any(
			host_for_check == suffix or host_for_check.endswith(f".{suffix}")
			for suffix in ALLOWED_TRANSCRIBE_HOST_SUFFIXES
		)
		if not allowed:
			return None
		query_items = parse_qsl(parsed.query, keep_blank_values=True)
		filtered_query = urlencode([
			(k, v) for (k, v) in query_items
			if not k.lower().startswith("utm_") and k.lower() not in {"si", "feature", "pp"}
		])
		netloc = host
		if parsed.port:
			netloc = f"{host}:{parsed.port}"
		return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, filtered_query, ""))

	def _transcribe_register_base(self) -> str:
		from urllib.parse import urlparse
		webhook_url = os.getenv("DEAPI_WEBHOOK_URL", "").strip()
		if webhook_url:
			parsed = urlparse(webhook_url)
			if parsed.scheme and parsed.netloc:
				return f"{parsed.scheme}://{parsed.netloc}"
		deapi_base = os.getenv("DEAPI_BASE_URL", "").strip().rstrip("/")
		if deapi_base:
			parsed = urlparse(deapi_base)
			if parsed.scheme and parsed.netloc:
				return f"{parsed.scheme}://{parsed.netloc}"
		return ""

	async def _send_transcription_fallback_result(self, *, request_id, channel_id, user_id, deliver_in_dm):
		try:
			transcript_text = await wait_for_transcription_text(request_id=request_id)
		except Exception as e:
			print(f"[TRANSCRIBE FALLBACK] {e}")
			return
		message = f"✅ **Transcription complete:**\n{transcript_text[:1900]}"
		try:
			if deliver_in_dm:
				user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
				await user.send(message)
			else:
				channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
				await channel.send(message)
		except Exception as e:
			print(f"[TRANSCRIBE FALLBACK] Discord send failed: {e}")

	@app_commands.command(name="transcribe", description="📝 Transcribe a supported video URL (max 30 mins)")
	@app_commands.describe(video_url="Supported: YouTube, Twitch VOD, X, Kick")
	async def transcribe_slash(self, interaction: discord.Interaction, video_url: str):
		usage_key = await self._resolve_paid_usage_key(interaction)
		normalized_video_url = self._normalize_transcribe_url(video_url)
		if not normalized_video_url:
			await interaction.response.send_message("❌ Only YouTube, Twitch VODs, X, and Kick URLs are allowed.", ephemeral=False)
			return
		await interaction.response.defer(ephemeral=False)
		await interaction.edit_original_response(content="🗳️ **Checking your vote status...**")
		if not await require_vote_deferred(interaction):
			return
		if not check_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.edit_original_response(content="🚫 Daily transcription limit hit.")
			return
		if not check_total_limit(interaction, "attachments", usage_key=usage_key):
			await interaction.edit_original_response(content="🚫 2-month transcription limit hit.")
			return
		await interaction.edit_original_response(content="✅ **Submitting transcription...**")
		deliver_in_dm = self._should_deliver_paid_output_in_dm(interaction)
		try:
			request_id = await transcribe_video(video_url=normalized_video_url, max_minutes=30)
			register_base = self._transcribe_register_base()
			register_channel_id = interaction.channel.id
			if deliver_in_dm:
				if usage_key and usage_key.isdigit():
					register_channel_id = int(usage_key)
				else:
					try:
						dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
						if dm_channel is not None:
							register_channel_id = dm_channel.id
					except Exception as e:
						print(f"[TRANSCRIBE REGISTER] {e}")
			if register_base:
				try:
					async with aiohttp.ClientSession() as session:
						async with session.post(
							f"{register_base}/register-transcription",
							json={"request_id": request_id, "channel_id": register_channel_id, "user_id": interaction.user.id, "deliver_in_dm": deliver_in_dm},
							timeout=aiohttp.ClientTimeout(total=15),
						) as register_resp:
							if register_resp.status >= 300:
								print(f"[TRANSCRIBE REGISTER] failed ({register_resp.status})")
				except Exception as e:
					print(f"[TRANSCRIBE REGISTER] {e}")
			consume(interaction, "attachments", usage_key=usage_key)
			consume_total(interaction, "attachments", usage_key=usage_key)
			save_usage()
			asyncio.create_task(self._send_transcription_fallback_result(
				request_id=request_id, channel_id=register_channel_id,
				user_id=interaction.user.id, deliver_in_dm=deliver_in_dm,
			))
		except VideoToTextError as e:
			await interaction.edit_original_response(content=f"❌ {e}")
			return
		except Exception as e:
			print(f"[SLASH TRANSCRIBE ERROR] {e}")
			await interaction.edit_original_response(content="🤔 Couldn't transcribe this video right now.")
			return
		if deliver_in_dm:
			await interaction.edit_original_response(content="📝 Transcription submitted! Result coming to your DMs.")
		else:
			await interaction.edit_original_response(content="📝 Transcription submitted! I'll post the result here.")

	# ── Action GIFs ───────────────────────────────────────────────────────────

	async def _send_action_gif(self, interaction: discord.Interaction, action: str, target_user: discord.User):
		if target_user.id == interaction.user.id:
			await interaction.response.send_message(f"😅 You can't /{action} yourself!", ephemeral=False)
			return
		await interaction.response.defer()
		loading_msg = await interaction.followup.send("🎉 **Loading your GIF...**", wait=True)
		try:
			source_url = random.choice(ACTION_GIF_SOURCES[action])
			text = random.choice(ACTION_MESSAGES[action]).format(user=interaction.user.mention, target=target_user.mention)
			embed = discord.Embed(description=text, color=0xFFA500)
			embed.set_image(url=source_url)
			await asyncio.sleep(3)
			await loading_msg.edit(content=None, embed=embed)
		except Exception as e:
			print(f"[SLASH {action.upper()} ERROR] {e}")
			await loading_msg.edit(content=f"🤔 Couldn't load a {action} GIF right now.")

	@app_commands.command(name="hug", description="🤗 Hug any user with a random GIF")
	@app_commands.describe(target_user="The user you want to hug")
	async def hug_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "hug", target_user)

	@app_commands.command(name="kiss", description="💋 Kiss any user with a random GIF")
	@app_commands.describe(target_user="The user you want to kiss")
	async def kiss_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "kiss", target_user)

	@app_commands.command(name="kick", description="🥋 Kick any user with a random anime GIF")
	@app_commands.describe(target_user="The user you want to kick")
	async def kick_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "kick", target_user)

	@app_commands.command(name="slap", description="🖐️ Slap any user with a random anime GIF")
	@app_commands.describe(target_user="The user you want to slap")
	async def slap_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "slap", target_user)

	@app_commands.command(name="wish_goodmorning", description="🌅 Wish someone a good morning with a GIF")
	@app_commands.describe(target_user="The user you want to wish good morning")
	async def wish_goodmorning_slash(self, interaction: discord.Interaction, target_user: discord.User):
		await self._send_action_gif(interaction, "wish_goodmorning", target_user)

	@app_commands.command(name="bet", description="🪙 Bet on heads or tails with a coin flip")
	@app_commands.describe(side="Choose heads or tails")
	@app_commands.choices(side=[
		app_commands.Choice(name="heads", value="heads"),
		app_commands.Choice(name="tails", value="tails"),
	])
	async def bet_slash(self, interaction: discord.Interaction, side: app_commands.Choice[str]):
		await interaction.response.defer()
		await interaction.followup.send("🪙 **Flipping the coin...**")
		result = random.choice(["heads", "tails"])
		did_win = side.value == result
		if did_win:
			msg = f"🪙 The coin landed on **{result}**! {interaction.user.mention} guessed correctly and wins! 🎉"
		else:
			msg = f"🪙 The coin landed on **{result}**! {interaction.user.mention} guessed **{side.value}** and lost this round."
		await interaction.followup.send(msg)

	@app_commands.command(name="meme", description="😂 Send a random meme")
	async def meme_slash(self, interaction: discord.Interaction):
		await interaction.response.defer()
		await interaction.followup.send("😂 **Loading your meme...**")
		meme_url = random.choice(MEME_SOURCES)
		embed = discord.Embed(title="😂 Random Meme", color=0x00BFFF)
		embed.set_image(url=meme_url)
		await interaction.followup.send(embed=embed)

	# ── Code Runner ───────────────────────────────────────────────────────────

	@app_commands.command(name="test_code", description="🧪 Test and validate Python code")
	async def test_code_slash(self, interaction: discord.Interaction):
		"""Open a modal for code input"""
		await interaction.response.send_modal(CodeTestModal())

	# ── Playlist helpers ──────────────────────────────────────────────────────

	async def _resolve_songs(self, queries: list[str], tier: str) -> list[dict]:
		"""Resolve search queries / URLs into track dicts concurrently (max 5 parallel)."""
		sem = asyncio.Semaphore(5)

		async def _one(q: str) -> Optional[dict]:
			async with sem:
				try:
					candidates = _build_query_candidates(q)
					info = await _ytdl_extract(candidates, tier)
					return {
						"title":    info.get("title") or q,
						"uploader": info.get("uploader") or info.get("channel") or "Unknown",
						"duration": info.get("duration"),
						"thumbnail": info.get("thumbnail"),
						"web_url":  info.get("webpage_url") or info.get("url"),
					}
				except Exception as e:
					print(f"[PLAYLIST RESOLVE] {q!r}: {e}")
					return None

		raw = await asyncio.gather(*[_one(q) for q in queries], return_exceptions=True)
		return [r for r in raw if isinstance(r, dict) and r]

	async def _prefetch_next_track(self, guild_id: int) -> None:
		"""
		20 s after a track starts, pre-resolve the next queued track (if it still
		needs a stream URL) or fetch an autoplay candidate so it's ready immediately
		when the current song ends.
		"""
		await asyncio.sleep(20)
		if guild_loop_mode.get(guild_id) == "song":
			return
		queue = guild_ytdl_queue.get(guild_id, [])
		if queue and queue[0].get("needs_resolve") and queue[0].get("web_url"):
			try:
				info = await _ytdl_extract([queue[0]["web_url"]], queue[0].get("tier", "free"))
				queue[0]["stream_url"]    = info.get("url")
				queue[0]["needs_resolve"] = False
				print(f"[PREFETCH] Queue head resolved: {queue[0].get('title')}")
			except Exception as e:
				print(f"[PREFETCH] Queue head resolve failed: {e}")
			return
		if not guild_autoplay.get(guild_id, False):
			return
		current = guild_now_playing_track.get(guild_id, {})
		seed    = current.get("title")
		if not seed:
			return
		recent     = guild_recent_titles.get(guild_id, deque())
		video_id   = _extract_yt_video_id(current.get("web_url"))
		played_ids: set[str] = set(guild_recent_ids.get(guild_id, deque()))
		if video_id:
			played_ids.add(video_id)

		# Try YT mix first — most relevant related songs
		c = None
		if video_id:
			try:
				c = await _ytdl_fetch_yt_mix(video_id, "free", played_ids)
				if c:
					print(f"[PREFETCH] YT mix candidate: {c.get('title')}")
			except Exception as e:
				print(f"[PREFETCH] YT mix failed: {e}")

		# Fall back to artist-mix search
		if not c:
			try:
				artist = seed.split(" - ", 1)[0].strip() if " - " in seed else ""
				fallback = f"ytsearch15:{artist} mix" if artist else f"ytsearch15:songs similar to {seed}"
				c = await _ytdl_extract_different_track(fallback, "free", seed)
			except Exception as e:
				print(f"[PREFETCH] Fallback search failed: {e}")

		if c:
			c_id = _extract_yt_video_id(c.get("webpage_url") or c.get("url") or "")
			if c_id not in played_ids and not _is_duplicate_track(c.get("title", ""), recent):
				guild_prefetched_autoplay[guild_id] = c
				print(f"[PREFETCH] Autoplay cached: {c.get('title')}")

	def _build_playlist_browser_embed(self, guild_id: int) -> discord.Embed:
		playlists = playlist_manager.get_guild_playlists(guild_id)
		count     = len(playlists)
		embed     = discord.Embed(title="🎵 Server Playlists", color=0x1DB954,
								  timestamp=datetime.now(timezone.utc))
		if not playlists:
			embed.description = "No playlists yet.  Use `/playlistcreate` to make one."
			return embed
		embed.description = f"**{count}** playlist{'s' if count != 1 else ''} saved in this server"
		lines = []
		for pid, pl in list(playlists.items()):
			tc       = len(pl.get("tracks", []))
			dur_secs = sum(t.get("duration") or 0 for t in pl.get("tracks", []))
			dur_str  = _fmt_duration(dur_secs)
			lines.append(
				f"**{pl['name']}**  ·  {tc} track{'s' if tc!=1 else ''}  ·  {dur_str}  ·  by {pl['creator_name']}"
			)
		embed.add_field(name="Playlists", value="\n".join(lines[:10]), inline=False)
		embed.set_footer(text="Select a playlist below to manage it")
		return embed

	def _build_playlist_manage_embed(self, pl: dict, playlist_id: str) -> discord.Embed:
		tracks   = pl.get("tracks", [])
		tc       = len(tracks)
		dur_secs = sum(t.get("duration") or 0 for t in tracks)
		embed    = discord.Embed(title=f"🎵 {pl['name']}", color=0x1DB954,
								 timestamp=datetime.now(timezone.utc))
		embed.description = f"Created by **{pl['creator_name']}**"
		embed.add_field(name="Tracks",   value=str(tc),            inline=True)
		embed.add_field(name="Duration", value=_fmt_duration(dur_secs), inline=True)
		embed.add_field(name="ID",       value=playlist_id,        inline=True)
		if tracks:
			preview = []
			for i, t in enumerate(tracks[:5], 1):
				d = _fmt_duration(t.get("duration"))
				preview.append(f"`{i}.` {t.get('title','?')} — {t.get('uploader','?')} `{d}`")
			if tc > 5:
				preview.append(f"*… and {tc-5} more*")
			embed.add_field(name="Tracks preview", value="\n".join(preview), inline=False)
		embed.set_footer(text="Use the buttons below to play, edit, or delete")
		return embed

	def _build_tracks_embed(self, pl: dict, page: int) -> discord.Embed:
		tracks  = pl.get("tracks", [])
		total   = len(tracks)
		per_p   = PlaylistTracksView.TRACKS_PER_PAGE
		pages   = max(1, (total + per_p - 1) // per_p)
		page    = max(0, min(page, pages - 1))
		start   = page * per_p
		chunk   = tracks[start:start + per_p]
		dur_all = sum(t.get("duration") or 0 for t in tracks)
		embed   = discord.Embed(title=f"📋 {pl['name']} — Track list", color=0x1DB954,
								timestamp=datetime.now(timezone.utc))
		embed.description = (
			f"Page {page+1} of {pages}  ·  {total} tracks total  ·  {_fmt_duration(dur_all)}"
		)
		lines = []
		for i, t in enumerate(chunk, start + 1):
			d = _fmt_duration(t.get("duration"))
			lines.append(f"`{i:>2}.` **{t.get('title','?')}**\n      {t.get('uploader','?')} · `{d}`")
		embed.add_field(name="\u200b", value="\n".join(lines) or "Empty", inline=False)
		embed.set_footer(text=f"Total: {_fmt_duration(dur_all)} · {total} tracks")
		return embed

	# ── New slash commands ────────────────────────────────────────────────────

	@app_commands.command(
		name="playlistcreate",
		description="🎵 Create a new server playlist from song URLs or search queries",
	)
	async def playlistcreate_slash(self, interaction: discord.Interaction):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		await interaction.response.send_modal(PlaylistCreateModal(self))

	@app_commands.command(
		name="playlist",
		description="🎵 Browse, play, and manage server playlists",
	)
	async def playlist_slash(self, interaction: discord.Interaction):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		playlists = playlist_manager.get_guild_playlists(interaction.guild.id)
		if not playlists:
			embed = discord.Embed(
				title="🎵 Server Playlists",
				description="No playlists saved yet.\n\nUse `/playlistcreate` to create your first playlist!",
				color=0x1DB954,
			)
			await interaction.response.send_message(embed=embed)
			return
		embed = self._build_playlist_browser_embed(interaction.guild.id)
		view  = PlaylistBrowserView(self, interaction.guild.id, interaction.user.id)
		await interaction.response.send_message(embed=embed, view=view)

	@app_commands.command(name="loop", description="🔁 Set loop mode: off · song · queue")
	@app_commands.describe(mode="off = normal | song = repeat current track | queue = loop whole queue")
	@app_commands.choices(mode=[
		app_commands.Choice(name="off — normal playback",        value="off"),
		app_commands.Choice(name="song — repeat current track",  value="song"),
		app_commands.Choice(name="queue — loop the whole queue", value="queue"),
	])
	async def loop_slash(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
		if interaction.guild is None:
			await interaction.response.send_message("❌ Server only.", ephemeral=True)
			return
		guild_id = interaction.guild.id
		prev     = guild_loop_mode.get(guild_id, "off")
		guild_loop_mode[guild_id] = mode.value

		if mode.value == "queue":
			current   = guild_now_playing_track.get(guild_id, {})
			queue_now = list(guild_ytdl_queue.get(guild_id, []))
			snapshot  = ([dict(current)] if current else []) + queue_now
			guild_saved_queue[guild_id] = snapshot

		labels   = {"off": "⏹ Off", "song": "🔂 Song", "queue": "🔁 Queue"}
		colors   = {"off": 0x5C5C5C, "song": 0xF0B232, "queue": 0x1DB954}
		desc_map = {
			"off":   "Playback will stop when the queue is empty.",
			"song":  "The current track will repeat indefinitely.",
			"queue": (
				"The queue will restart from the beginning when it ends.\n"
				f"Snapshot saved: **{len(guild_saved_queue.get(guild_id, []))}** track(s)."
			),
		}
		embed = discord.Embed(
			title=f"Loop mode set to {labels[mode.value]}",
			description=desc_map[mode.value],
			color=colors[mode.value],
			timestamp=datetime.now(timezone.utc),
		)
		embed.add_field(name="Previous", value=labels.get(prev, prev), inline=True)
		embed.add_field(name="Current",  value=labels[mode.value],     inline=True)
		await interaction.response.send_message(embed=embed)

	# ── URL Browser ───────────────────────────────────────────────────────────

	@app_commands.command(name="browse", description="🌐 Fetch and read the content of a webpage URL")
	@app_commands.describe(url="The URL of the webpage you want to read")
	async def browse_slash(self, interaction: discord.Interaction, url: str):
		if not _looks_like_url(url):
			await interaction.response.send_message("❌ That doesn't look like a valid URL. Please include `http://` or `https://`.", ephemeral=False)
			return
		await interaction.response.defer()
		await interaction.edit_original_response(content="🌐 **Fetching page content...**")

		text = await fetch_url_content(url, max_chars=3900)

		if text.startswith("❌"):
			await interaction.edit_original_response(content=text)
			return

		embed = discord.Embed(
			title=f"🌐 Content from URL",
			description=text[:4000],
			color=0x00BFFF,
		)
		embed.set_footer(text=url[:200])
		await interaction.edit_original_response(content=None, embed=embed)


async def setup(bot: commands.Bot):
	cog = Codunot(bot)
	await bot.add_cog(cog)
	print(f"[COG] Loaded Codunot cog with {len(cog.get_app_commands())} app commands")
