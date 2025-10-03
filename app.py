# ==============================================================================
#     أداة الفيديو الإخباري كخدمة ويب (API) - إصدار 9.0 (شامل)
#     - دمج الكود الجديد مع بنية Flask API.
#     - إضافة التعامل مع رفع ملفات الفيديو والصوت.
#     - إضافة ميزة تحويل النص إلى كلام (TTS) باللغة العربية.
#     - تحسينات شاملة على منطق دمج الصوتيات والفيديو.
# ==============================================================================
import os
import random
import traceback
import threading
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import time

# --- استيراد المكتبات الأساسية للكود ---
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import arabic_reshaper
from bidi.algorithm import get_display
import cv2
import numpy as np
import ffmpeg
import requests
from bs4 import BeautifulSoup
from gtts import gTTS # *** إضافة جديدة لتحويل النص إلى كلام ***

# ==============================================================================
#                                   الإعدادات
# ==============================================================================
# --- إعدادات Flask ---
UPLOAD_FOLDER = 'temp_uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- إعدادات تليجرام (سيتم قراءتها من متغيرات البيئة) ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_FALLBACK_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID', 'YOUR_FALLBACK_ID')

# --- إعدادات الملفات (يجب أن تكون موجودة في نفس المجلد) ---
FONT_FILE = "Amiri-Bold.ttf"
LOGO_FILE = "logo.png"
DEFAULT_SOUND_FILE = "news_alert.mp3"
DEFAULT_MUSIC_FILE = "background_music.mp3"

# --- إعدادات التوقيت والتصميم (من الكود الجديد) ---
SECONDS_PER_PAGE = 8
OUTRO_DURATION_SECONDS = 6.5
FPS = 30
WORDS_TO_REVEAL_PER_SECOND = 4
KEN_BURNS_ZOOM_FACTOR = 1.05
MAX_LINES_PER_PAGE = 3
TEXT_COLOR = "#FFFFFF"
SHADOW_COLOR = "#000000"
TEXT_PLATE_COLOR = (0, 0, 0, 160)
BACKGROUND_MUSIC_VOLUME = 0.15 # سيتم استخدامه إذا لم يتم رفع ملف صوتي

# --- قوالب الأخبار والأبعاد ---
NEWS_TEMPLATES = {
    "1": { "name": "دليلك في سوريا", "hashtag": "#عاجل #سوريا #سوريا_عاجل #syria", "color": (211, 47, 47) },
    "3": { "name": "دليلك في الأخبار", "hashtag": "#عاجل #أخبار #دليلك", "color": (200, 30, 30) },
    "4": { "name": "عاجل||نتائج", "hashtag": "#عاجل #نتائج #التعليم_الأساسي #التاسع", "color": (200, 30, 30) },
    "2": { "name": "دليلك في الرياضة", "hashtag": "#أخبار #رياضة", "color": (0, 128, 212) }
}
VIDEO_DIMENSIONS = {
    "reels": {"name": "Instagram Story/Reel (9:16)", "size": (1080, 1920)},
    "video": {"name": "YouTube Standard (16:9)", "size": (1920, 1080)}
}
DETAILS_TEXT = "الـتـفـاصـيـل:"
FOOTER_TEXT = "تابعنا عبر موقع دليلك نيوز الإخباري"
# ===================================================================

# ( ... هنا يتم نسخ جميع الدوال المساعدة من الكود الجديد ... )
#  process_text_for_image, wrap_text_to_pages, draw_text_with_shadow,
#  fit_image_to_box, render_design, scrape_article_page, etc.

def process_text_for_image(text): return get_display(arabic_reshaper.reshape(text))
def wrap_text_to_pages(text, font, max_width, max_lines_per_page):
    if not text: return [[]]
    lines, words, current_line = [], text.split(), ''
    for word in words:
        test_line = f"{current_line} {word}".strip()
        if font.getbbox(process_text_for_image(test_line))[2] <= max_width:
            current_line = test_line
        else:
            lines.append(current_line); current_line = word
    lines.append(current_line)
    return [lines[i:i + max_lines_per_page] for i in range(0, len(lines), max_lines_per_page)]
def draw_text_with_shadow(draw, position, text, font, fill_color, shadow_color):
    x, y = position; processed_text = process_text_for_image(text); shadow_offset = 3
    draw.text((x + shadow_offset, y + shadow_offset), processed_text, font=font, fill=shadow_color, stroke_width=2)
    draw.text((x, y), processed_text, font=font, fill=fill_color)
def fit_image_to_box(img, box_width, box_height):
    img_ratio = img.width / img.height; box_ratio = box_width / box_height
    if img_ratio > box_ratio:
        new_height = box_height; new_width = int(new_height * img_ratio)
    else:
        new_width = box_width; new_height = int(new_width / img_ratio)
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    left = (new_width - box_width) / 2; top = (new_height - box_height) / 2
    return img.crop((left, top, left + box_width, top + box_height))
def render_design(design_type, draw, W, H, template, lines_to_draw, news_font, logo_img):
    if design_type == 'classic':
        header_height = int(H * 0.1)
        dark_color, light_color = template['color'], tuple(min(c+30, 255) for c in template['color'])
        for i in range(header_height):
            ratio = i / header_height; r,g,b = [int(dark_color[j]*(1-ratio) + light_color[j]*ratio) for j in range(3)]
            draw.line([(0, i), (W, i)], fill=(r,g,b))
        draw.rectangle([(0,0), (W, header_height//3)], fill=(255,255,255,50))
        header_font = ImageFont.truetype(FONT_FILE, int(W / 14.5))
        header_text_proc = process_text_for_image(template['name'])
        draw_text_with_shadow(draw, ((W - header_font.getbbox(header_text_proc)[2]) / 2, (header_height - header_font.getbbox(header_text_proc)[3]) / 2 - 10), template['name'], header_font, TEXT_COLOR, SHADOW_COLOR)
    elif design_type == 'cinematic':
        tag_font = ImageFont.truetype(FONT_FILE, int(W / 24)); tag_text = process_text_for_image(template['name'])
        tag_bbox = tag_font.getbbox(tag_text); tag_width = tag_bbox[2] - tag_bbox[0] + 60; tag_height = tag_bbox[3] - tag_bbox[1] + 30
        tag_x, tag_y = W - tag_width - 40, 40
        draw.rounded_rectangle([tag_x, tag_y, tag_x + tag_width, tag_y + tag_height], radius=tag_height/2, fill=template['color'])
        draw.text((tag_x + tag_width/2, tag_y + tag_height/2), tag_text, font=tag_font, fill=TEXT_COLOR, anchor="mm")
    if lines_to_draw:
        line_heights = [news_font.getbbox(process_text_for_image(line))[3] + 20 for line in lines_to_draw]
        plate_height = sum(line_heights) + 60; plate_y0 = (H - plate_height) / 2
        draw.rectangle([(0, plate_y0), (W, plate_y0 + plate_height)], fill=TEXT_PLATE_COLOR)
        text_y_start = plate_y0 + 30
        for line in lines_to_draw:
            line_width = news_font.getbbox(process_text_for_image(line))[2]
            draw_text_with_shadow(draw, ((W - line_width) / 2, text_y_start), line, news_font, TEXT_COLOR, SHADOW_COLOR)
            text_y_start += news_font.getbbox(process_text_for_image(line))[3] + 20

def scrape_article_page(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}; response = requests.get(url, headers=headers, timeout=10); response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser'); 
        title = (soup.find('h1', class_='entry-title') or soup.find('h1')).get_text(strip=True)
        image_url = (soup.find('meta', property='og:image')).get('content')
        if title and image_url: return {'title': title, 'image_url': image_url}
    except Exception as e: print(f"!! خطأ في تحليل الرابط: {e}"); return None
def download_image(url, save_path):
    try:
        response = requests.get(url, stream=True, timeout=10); response.raise_for_status()
        with open(save_path, 'wb') as f: f.write(response.content)
        return save_path
    except Exception: return None
    
# *** دالة جديدة لإنشاء الصوت من النص ***
def generate_tts_audio(text, filepath):
    try:
        tts = gTTS(text=text, lang='ar', slow=False)
        tts.save(filepath)
        print(f"✅ تم إنشاء ملف الصوت من النص: {filepath}")
        return filepath
    except Exception as e:
        print(f"!! فشل في إنشاء الصوت من النص: {e}")
        return None

def create_video(params):
    # تفكيك المتغيرات لسهولة القراءة
    design_type = params['design_type']; news_title = params['text']
    template = params['template']; background_image_path = params['image_path']
    W, H = params['dimensions']; tts_enabled = params['tts_enabled']
    intro_path = params['intro_path']; outro_path = params['outro_path']
    music_path = params['music_path']
    
    unique_id = random.randint(1000, 9999)
    temp_files = [] # قائمة لتتبع كل الملفات المؤقتة

    try:
        font_size_base = int(W / 12)
        news_font = ImageFont.truetype(FONT_FILE, font_size_base if len(news_title) < 50 else font_size_base - 20)
        
        if background_image_path:
            base_image = fit_image_to_box(Image.open(background_image_path).convert("RGB"), W, H)
        else:
            base_image = Image.open(LOGO_FILE).convert("RGB").resize((W,H)).filter(ImageFilter.GaussianBlur(15))
            
        logo_img = Image.open(LOGO_FILE).convert("RGBA") if os.path.exists(LOGO_FILE) else None

        text_pages = wrap_text_to_pages(news_title, news_font, max_width=W-120, max_lines_per_page=MAX_LINES_PER_PAGE)
        num_pages = len(text_pages)

        # --- إنشاء الفيديو الصامت ---
        silent_video_path = f"silent_{unique_id}.mp4"; temp_files.append(silent_video_path)
        video_writer = cv2.VideoWriter(silent_video_path, cv2.VideoWriter_fourcc(*'mp4v'), FPS, (W, H))
        
        # ... (نفس منطق تصيير الفريمات من الكود الأصلي) ...
        for page_index, original_page_lines in enumerate(text_pages):
            page_text = " ".join(original_page_lines); words_on_page = page_text.split()
            for i in range(int(SECONDS_PER_PAGE * FPS)):
                progress = i / (SECONDS_PER_PAGE * FPS)
                zoom = 1 + progress * (KEN_BURNS_ZOOM_FACTOR - 1)
                zoomed_bg = base_image.resize((int(W*zoom), int(H*zoom)), Image.Resampling.LANCZOS)
                x, y = (zoomed_bg.width - W) // 2, (zoomed_bg.height - H) // 2
                frame_bg = zoomed_bg.crop((x, y, x + W, y + H))
                draw = ImageDraw.Draw(frame_bg, 'RGBA')
                words_to_show = min(len(words_on_page), int(progress * len(words_on_page) * 1.5) + 1)
                lines_to_draw = wrap_text_to_pages(" ".join(words_on_page[:words_to_show]), news_font, W-120, MAX_LINES_PER_PAGE)[0]
                render_design(design_type, draw, W, H, template, lines_to_draw, news_font, logo_img)
                video_writer.write(cv2.cvtColor(np.array(frame_bg), cv2.COLOR_RGB2BGR))
        
        # ... (نفس منطق الخاتمة من الكود الأصلي) ...
        outro_font = ImageFont.truetype(FONT_FILE, int(W / 18))
        for i in range(int(OUTRO_DURATION_SECONDS * FPS)):
            image = Image.new('RGB', (W, H), (10, 10, 10)); draw = ImageDraw.Draw(image, 'RGBA')
            text_width = outro_font.getbbox(process_text_for_image(FOOTER_TEXT))[2]
            draw_text_with_shadow(draw, ((W - text_width) / 2, H // 2), FOOTER_TEXT, outro_font, TEXT_COLOR, SHADOW_COLOR)
            video_writer.write(cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR))
        video_writer.release()

        # --- مرحلة الصوت (معدلة بالكامل) ---
        main_video_stream = ffmpeg.input(silent_video_path)
        audio_inputs = []
        
        # 1. صوت التنبيه الافتراضي
        if os.path.exists(DEFAULT_SOUND_FILE):
             audio_inputs.append(ffmpeg.input(DEFAULT_SOUND_FILE))

        # 2. صوت قراءة النص (TTS)
        if tts_enabled:
            tts_path = f"tts_{unique_id}.mp3"; temp_files.append(tts_path)
            if generate_tts_audio(news_title, tts_path):
                # تأخير صوت القراءة ليبدأ بعد صوت التنبيه
                audio_inputs.append(ffmpeg.input(tts_path).filter('adelay', '1000|1000'))
        
        # 3. موسيقى الخلفية (المرفوعة أو الافتراضية)
        final_music_path = music_path if music_path and os.path.exists(music_path) else DEFAULT_MUSIC_FILE
        if os.path.exists(final_music_path):
            total_duration = (num_pages * SECONDS_PER_PAGE) + OUTRO_DURATION_SECONDS
            music_stream = ffmpeg.input(final_music_path, stream_loop=-1, t=total_duration).filter('volume', BACKGROUND_MUSIC_VOLUME)
            audio_inputs.append(music_stream)

        # دمج الصوت مع الفيديو الصامت
        generated_video_path = f"generated_{unique_id}.mp4"; temp_files.append(generated_video_path)
        if audio_inputs:
            mixed_audio = ffmpeg.filter(audio_inputs, 'amix', duration='first', inputs=len(audio_inputs))
            (ffmpeg.output(main_video_stream.video, mixed_audio, generated_video_path, vcodec='libx264', acodec='aac', pix_fmt='yuv420p', preset='fast', crf=28)
             .overwrite_output().run(capture_stdout=True, capture_stderr=True))
        else:
            (ffmpeg.output(main_video_stream.video, generated_video_path, vcodec='copy')
             .run(capture_stdout=True, capture_stderr=True))

        # --- مرحلة دمج المقدمة والخاتمة ---
        videos_to_concat = []
        if intro_path: videos_to_concat.append(ffmpeg.input(intro_path))
        videos_to_concat.append(ffmpeg.input(generated_video_path))
        if outro_path: videos_to_concat.append(ffmpeg.input(outro_path))

        final_video_path = f"final_{unique_id}.mp4"; temp_files.append(final_video_path)
        if len(videos_to_concat) > 1:
            print("🔗 دمج المقدمة/الخاتمة...")
            processed_clips = [v.video.filter('scale', W, H).filter('setsar', 1) for v in videos_to_concat]
            processed_audio = [v.audio for v in videos_to_concat]
            (ffmpeg.concat(*processed_clips, *processed_audio, v=1, a=1)
             .output(final_video_path, vcodec='libx264', acodec='aac', crf=28, preset='fast')
             .overwrite_output().run(capture_stdout=True, capture_stderr=True))
        else:
            # إذا لم يكن هناك دمج، فقط أعد تسمية الملف
            os.rename(generated_video_path, final_video_path)

        # --- إنشاء الصورة المصغرة النهائية ---
        thumbnail_path = f"thumb_{unique_id}.jpg"; temp_files.append(thumbnail_path)
        thumb_image = base_image.copy()
        render_design(design_type, ImageDraw.Draw(thumb_image, 'RGBA'), W, H, template, text_pages[0], news_font, logo_img)
        thumb_image.convert('RGB').save(thumbnail_path, quality=85)

        return final_video_path, thumbnail_path, temp_files

    except Exception as e:
        print(f"!! خطأ فادح أثناء إنشاء الفيديو: {e}")
        traceback.print_exc()
        return None, None, temp_files # إرجاع الملفات المؤقتة للتنظيف

def send_video_to_telegram(video_path, thumb_path, caption, hashtag):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        full_caption = f"{caption}\n\n<b>{hashtag}</b>"
        with open(video_path, 'rb') as vf, open(thumb_path, 'rb') as tf:
            files = {'video': vf, 'thumb': tf}
            data = {'chat_id': TELEGRAM_CHANNEL_ID, 'caption': full_caption, 'parse_mode': 'HTML', 'supports_streaming': True}
            response = requests.post(url, files=files, data=data, timeout=1800)
            if response.status_code == 200:
                print("✅ تم النشر بنجاح!")
            else:
                print(f"!! فشل النشر: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"!! خطأ في الإرسال إلى تليجرام: {e}")

# ==============================================================================
#                          المنطق الرئيسي للـ API
# ==============================================================================
def process_video_request(form_data, files_data):
    temp_files_to_clean = []
    try:
        # --- 1. استخراج البيانات من الطلب ---
        source_url = form_data.get('url')
        manual_text = form_data.get('text')
        template_choice = form_data.get('template', '1')
        design_type = form_data.get('design', 'classic')
        video_format = form_data.get('video_format', 'reels')
        tts_enabled = form_data.get('tts_enabled') == 'true'

        W, H = VIDEO_DIMENSIONS[video_format]['size']
        selected_template = NEWS_TEMPLATES[template_choice]

        # --- 2. حفظ الملفات المرفوعة ---
        def save_uploaded_file(file_key):
            if file_key in files_data:
                file = files_data[file_key]
                filename = secure_filename(f"{file_key}_{random.randint(1000,9999)}_{file.filename}")
                path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(path)
                temp_files_to_clean.append(path)
                return path
            return None
        
        intro_path = save_uploaded_file('intro_video')
        outro_path = save_uploaded_file('outro_video')
        music_path = save_uploaded_file('music_file')

        # --- 3. تحضير نص وصورة الخبر ---
        data = {}
        if source_url:
            article_data = scrape_article_page(source_url)
            if article_data:
                image_save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"bg_{random.randint(1000,9999)}.jpg")
                temp_files_to_clean.append(image_save_path)
                temp_image_path = download_image(article_data['image_url'], image_save_path)
                data = {'text': article_data['title'], 'image_path': temp_image_path, 'url': source_url}
        elif manual_text:
            data = {'text': manual_text, 'image_path': None, 'url': None}

        if not data.get('text'):
            raise ValueError("لا يوجد نص لإنشاء الفيديو.")

        # --- 4. إنشاء الفيديو ---
        params = {**data, 'design_type': design_type, 'template': selected_template, 'dimensions': (W, H), 
                  'tts_enabled': tts_enabled, 'intro_path': intro_path, 'outro_path': outro_path, 'music_path': music_path}
        
        final_video, final_thumb, created_files = create_video(params)
        temp_files_to_clean.extend(created_files)

        # --- 5. النشر ---
        if final_video and final_thumb:
            caption_parts = [data['text']]
            if data.get('url'): caption_parts.extend(["", f"<b>{DETAILS_TEXT}</b> {data['url']}"])
            caption = "\n".join(caption_parts)
            send_video_to_telegram(final_video, final_thumb, caption, selected_template['hashtag'])
        else:
            print("❌ فشلت عملية إنشاء الفيديو النهائية.")

    except Exception as e:
        print(f"!! حدث خطأ غير متوقع في معالجة الطلب: {e}")
        traceback.print_exc()
    finally:
        # --- 6. تنظيف جميع الملفات المؤقتة ---
        print(f"🧹 تنظيف {len(temp_files_to_clean)} ملف مؤقت...")
        for f in temp_files_to_clean:
            if f and os.path.exists(f):
                try: os.remove(f)
                except Exception as e: print(f"  - لم يتمكن من حذف {f}: {e}")

@app.route('/create-video', methods=['POST'])
def handle_create_video():
    # استخدام thread لتشغيل العملية الطويلة في الخلفية وإرجاع استجابة فورية
    thread = threading.Thread(target=process_video_request, args=(request.form, request.files))
    thread.start()
    return jsonify({
        "status": "processing",
        "message": "تم استلام طلبك بنجاح. سيتم إنشاء الفيديو ونشره في الخلفية."
    }), 202

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)