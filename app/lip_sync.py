import os
import json
import warnings
from typing import List, Tuple, Dict
import numpy as np
from pydub import AudioSegment
from langdetect import detect
from langdetect.detector_factory import DetectorFactory
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate


# FFmpeg setup
os.environ["PATH"] += os.pathsep + r"D:\inai\backend\INAI_Backend_MD_Final\Models\ffmpeg\bin"
AudioSegment.converter = r"D:\inai\backend\INAI_Backend_MD_Final\Models\ffmpeg\bin\ffmpeg.exe"

AudioSegment.converter = "ffmpeg"

DetectorFactory.seed = 0
warnings.filterwarnings("ignore")

# ------------------- PHONEME TO VISEME MAPPING -------------------
phoneme_to_viseme = {
    "A": ["m", "b", "p", "em", "bm", "i"],
    "B": ["d", "t", "n", "l", "s", "z", "e", "nd", "nt"],
    "C": ["k", "g", "gh", "kh", "ng"],
    "D": ["r", "rr", "ll", "ey", "er", "dh"],
    "E": ["u", "uw", "o", "w", "wh", "ch", "jh", "sh", "zh", "th"],
    "F": ["f", "v"],
    "G": ["hh", "h", "uh", "ih"],
    "H": ["aa", "ae", "ah", "ao", "aw", "ay", "a", "eh", "iy", "ee", "y"],
    "X": [" ", "sil", "sp", "pause"]
}

def map_to_viseme(phoneme: str) -> str:
    for viseme, phonemes in phoneme_to_viseme.items():
        if phoneme in phonemes:
            return viseme
    return "X"

def detect_language(text: str) -> str:
    return detect(text)

# ---------- English phoneme extractor ----------
def get_phonemes_en(text: str) -> List[str]:
    try:
        from eng_to_ipa import convert as ipa_convert
        ipa_text = ipa_convert(text)
        ipa_to_phoneme = {
            'i': 'iy', 'ɪ': 'ih', 'e': 'ey', 'ɛ': 'eh', 'æ': 'ae',
            'ɑ': 'aa', 'ʌ': 'ah', 'ɔ': 'ao', 'ʊ': 'uh', 'u': 'uw',
            'aʊ': 'aw', 'aɪ': 'ay', 'ɔɪ': 'oy', 'oʊ': 'ow',
            'p': 'p', 'b': 'b', 't': 't', 'd': 'd', 'k': 'k', 'ɡ': 'g',
            'm': 'm', 'n': 'n', 'ŋ': 'ng', 'f': 'f', 'v': 'v',
            'θ': 'th', 'ð': 'dh', 's': 's', 'z': 'z', 'ʃ': 'sh', 'ʒ': 'zh',
            'h': 'hh', 'l': 'l', 'r': 'r', 'j': 'y', 'w': 'w',
            'tʃ': 'ch', 'dʒ': 'jh', ' ': ' '
        }
        phonemes = []
        i = 0
        while i < len(ipa_text):
            found = False
            for length in [2, 1]:
                if i + length <= len(ipa_text):
                    substr = ipa_text[i:i + length]
                    if substr in ipa_to_phoneme:
                        phonemes.append(ipa_to_phoneme[substr])
                        i += length
                        found = True
                        break
            if not found:
                i += 1
        return phonemes
    except:
        return list(text)

# ---------- Hindi/Gujarati: normalize + phonemes ----------
def normalize_text(text: str, lang: str) -> str:
    """Convert Hindi/Gujarati native script → Romanized (ITRANS)"""
    try:
        if any('\u0900' <= ch <= '\u097F' for ch in text):  # Hindi
            return transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS).lower()
        elif any('\u0A80' <= ch <= '\u0AFF' for ch in text):  # Gujarati
            return transliterate(text, sanscript.GUJARATI, sanscript.ITRANS).lower()
        else:
            return text.lower()  # Already romanized
    except:
        return text.lower()

def get_phonemes_hi_gu(text: str) -> List[str]:
    clusters = [
        "kh", "gh", "ch", "jh", "ṭh", "ḍh", "th", "dh", "ph", "bh",
        "aa", "ii", "uu", "ai", "au", "sh", "ng", "ñ", "ṇ", "ṛ",
        "a", "e", "i", "o", "u", "k", "g", "c", "j", "ṭ", "ḍ", "t", "d",
        "n", "p", "b", "m", "y", "r", "l", "v", "s", "h"
    ]
    text = text.lower()
    phonemes = []
    i = 0
    while i < len(text):
        match = None
        for c in sorted(clusters, key=len, reverse=True):
            if text[i:i + len(c)] == c:
                match = c
                break
        if match:
            phonemes.append(match)
            i += len(match)
        else:
            if text[i].isalpha():
                phonemes.append(text[i])
            i += 1
    return phonemes

# ---------- Audio Analysis ----------
def analyze_audio_segment(audio: AudioSegment) -> Tuple[np.ndarray, int]:
    if audio.channels > 1:
        audio = audio.set_channels(1)
    if audio.sample_width != 2:
        audio = audio.set_sample_width(2)
    samples = np.array(audio.get_array_of_samples())
    return samples, audio.frame_rate

def detect_silences(audio: AudioSegment, threshold_db: float = -40.0, min_silence_duration: float = 0.1) -> List[Tuple[float, float]]:
    samples, sr = analyze_audio_segment(audio)
    samples = samples.astype(np.float32) / 32768.0
    window_size = int(0.02 * sr)
    hop_size = window_size // 2
    rms = []
    for i in range(0, len(samples), hop_size):
        window = samples[i:i + window_size]
        if len(window) == 0:
            continue
        rms_val = np.sqrt(np.mean(window**2))
        rms.append(20 * np.log10(max(rms_val, 1e-10)))
    silent_windows = [i for i, val in enumerate(rms) if val < threshold_db]
    silent_periods = []
    for window_idx in silent_windows:
        start_time = window_idx * hop_size / sr
        end_time = (window_idx * hop_size + window_size) / sr
        if silent_periods and start_time <= silent_periods[-1][1]:
            silent_periods[-1] = (silent_periods[-1][0], end_time)
        else:
            silent_periods.append((start_time, end_time))
    return [(s, e) for s, e in silent_periods if (e - s) >= min_silence_duration]

# ---------- Cue Creation ----------
def create_viseme_cues(phonemes: List[str], duration: float, silences: List[Tuple[float, float]]) -> List[Dict]:
    cues = []
    non_silent_ranges = []
    last = 0.0
    for s_start, s_end in silences:
        if last < s_start:
            non_silent_ranges.append((last, s_start))
        last = s_end
    if last < duration:
        non_silent_ranges.append((last, duration))
    total_active_duration = sum(e - s for s, e in non_silent_ranges)
    if total_active_duration <= 0 or not phonemes:
        return []
    phoneme_duration = max(total_active_duration / len(phonemes), 0.05)
    current_index = 0
    for seg_start, seg_end in sorted(non_silent_ranges + silences, key=lambda x: x[0]):
        seg_duration = seg_end - seg_start
        if (seg_start, seg_end) in silences:
            cues.append({"value": "X", "start": round(seg_start, 2), "end": round(seg_end, 2)})
        else:
            t = seg_start
            while t + phoneme_duration <= seg_end and current_index < len(phonemes):
                ph = phonemes[current_index]
                viseme = map_to_viseme(ph)
                end_time = min(t + phoneme_duration, duration)
                cues.append({
                    "value": viseme,
                    "start": round(t, 2),
                    "end": round(end_time, 2)
                })
                t += phoneme_duration
                current_index += 1
    return cues

def merge_repeated_visemes(cues: List[Dict]) -> List[Dict]:
    if not cues:
        return []
    merged = [cues[0]]
    for cue in cues[1:]:
        last = merged[-1]
        if cue["value"] == last["value"]:
            last["end"] = cue["end"]
        else:
            merged.append(cue)
    return merged

# ---------------- FINAL FUNCTION ----------------
def generate_lip_sync_json(input_audio_path: str, input_text_path: str, output_json_path: str):
    print(":rocket: Starting lip sync generation...")
    try:
        with open(input_text_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            raise ValueError("Text is empty!")

        lang = detect_language(text)

        # Normalize for Hindi/Gujarati
        if lang in ["hi", "gu"]:
            text = normalize_text(text, lang)
            phonemes = get_phonemes_hi_gu(text)
        else:
            phonemes = get_phonemes_en(text)

        audio = AudioSegment.from_file(input_audio_path).set_channels(1).set_sample_width(2).set_frame_rate(44100)
        duration = len(audio) / 1000.0
        silences = detect_silences(audio)
        cues = create_viseme_cues(phonemes, duration, silences)
        cues = merge_repeated_visemes(cues)
        for cue in cues:
            cue["start"] = max(0.0, min(cue["start"], duration))
            cue["end"] = max(cue["start"], min(cue["end"], duration))
        os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump({"mouthCues": cues}, f, indent=2)
        print(":white_check_mark: Lip sync JSON generated successfully!")
    except Exception as e:
        print(f":x: Error: {e}")
