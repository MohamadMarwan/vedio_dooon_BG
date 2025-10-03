# ==============================================================================
#     أداة الفيديو الإخبارية - إصدار 10.0 (تطبيق ويب متكامل)
#     - يقدم الواجهة الأمامية (index.html) مباشرة من Flask.
#     - لا حاجة لـ CORS أو حيل HTTPS لأن كل شيء على نفس النطاق.
#     - يستخدم مسارات نسبية في الواجهة لزيادة الموثوقية.
#     - يتضمن جميع إصلاحات النص العربي وميزات المعاينة.
# ==============================================================================
import os
import random
import traceback
from flask import Flask, request, jsonify, render_template
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
from gtts import gTTS

# ==============================================================================
#                             الإعدادات والتكوين
# ==============================================================================
# إعدادات Flask
UPLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "mysite", "temp_uploads")
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# إعدادات تليجرام (يتم تعيينها في متغيرات البيئة في PythonAnywhere)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')

# إعدادات الملفات (باستخدام مسارات مطلقة لضمان العثور عليها)
PROJECT_PATH = os.path.dirname(os.path.abspath(__file__))
FONT_FILE = os.path.join(PROJECT_PATH, "Amiri-Bold.ttf")
LOGO_FILE = os.path.join(PROJECT_PATH, "logo.png")
DEFAULT_SOUND_FILE = os.path.join(PROJECT_PATH, "news_alert.mp3")
DEFAULT_MUSIC_FILE = os.path.join(PROJECT_PATH, "background_music.mp3")

# إعدادات الفيديو والتصميم
SECONDS_PER_PAGE = 8
OUTRO_DURATION_SECONDS = 6.5
FPS = 30
KEN_BURNS_ZOOM_FACTOR = 1.05
MAX_LINES_PER_PAGE = 3
TEXT_COLOR = "#FFFFFF"
SHADOW_COLOR = "#000000"
TEXT_PLATE_COLOR = (0, 0, 0, 160)
BACKGROUND_MUSIC_VOLUME = 0.15

# قوالب وأبعاد
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
# ==============================================================================
#                      دوال النص العربي المُصححة
# ==============================================================================
def process_arabic_text(text):
    reshaped_text = arabic_reshaper.reshape(text)
    bidi_text = get_display(reshaped_text)
    return bidi_text

def wrap_text_for_arabic(text, font, max_width):
    lines = []
    if not text: return lines
    words = text.split()
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        if font.getbbox(process_arabic_text(test_line))[2] <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return [line for line in lines if line]

def draw_multiline_arabic_text(draw, box_coords, text_lines, font, fill_color, shadow_color=None):
    x_right, y_start, box_width, box_height = box_coords
    line_height = font.getbbox("أ")[3] + 20
    processed_lines = [process_arabic_text(line) for line in text_lines]
    total_text_height = (len(processed_lines) * line_height) - 20
    y = y_start + (box_height - total_text_height) / 2

    for line in processed_lines:
        line_width = font.getbbox(line)[2]
        line_x = x_right - (box_width - line_width) / 2
        
        if shadow_color:
            shadow_offset = 3
            draw.text((line_x + shadow_offset, y + shadow_offset), line, font=font, fill=shadow_color, anchor="ra")
        
        draw.text((line_x, y), line, font=font, fill=fill_color, anchor="ra")
        y += line_height

# ==============================================================================
#                               الدوال المساعدة
# ==============================================================================
def fit_image_to_box(img, box_width, box_height):
    img_ratio = img.width / img.height; box_ratio = box_width / box_height
    if img_ratio > box_ratio:
        new_height = box_height; new_width = int(new_height * img_ratio)
    else:
        new_width = box_width; new_height = int(new_width / img_ratio)
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    left = (new_width - box_width) / 2; top = (new_height - box_height) / 2
    return img.crop((left, top, left + box_width, top + box_height))
    
def render_design(draw, W, H, design_type, template, lines_to_draw, news_font, logo_img):
    if design_type == 'classic':
        header_height = int(H * 0.1)
        dark_color, light_color = template['color'], tuple(min(c+30, 255) for c in template['color'])
        for i in range(header_height):
            ratio = i / header_height; r,g,b = [int(dark_color[j]*(1-ratio) + light_color[j]*ratio) for j in range(3)]
            draw.line([(0, i), (W, i)], fill=(r,g,b))
        draw.rectangle([(0,0), (W, header_height//3)], fill=(255,255,255,50))
        header_font = ImageFont.truetype(FONT_FILE, int(W / 14.5))
        processed_header = process_arabic_text(template['name'])
        header_height_font = header_font.getbbox(processed_header)[3]
        draw_multiline_arabic_text(draw, (W, (header_height - header_height_font) / 2, W, 0), [template['name']], header_font, TEXT_COLOR, SHADOW_COLOR)

    elif design_type == 'cinematic':
        tag_font = ImageFont.truetype(FONT_FILE, int(W / 24))
        processed_tag = process_arabic_text(template['name'])
        tag_bbox = tag_font.getbbox(processed_tag); tag_width = tag_bbox[2] - tag_bbox[0] + 60; tag_height = tag_bbox[3] - tag_bbox[1] + 30
        tag_x, tag_y = W - tag_width - 40, 40
        draw.rounded_rectangle([tag_x, tag_y, tag_x + tag_width, tag_y + tag_height], radius=tag_height/2, fill=template['color'])
        draw.text((tag_x + tag_width/2, tag_y + tag_height/2), processed_tag, font=tag_font, fill=TEXT_COLOR, anchor="mm")

    if lines_to_draw:
        line_heights = [news_font.getbbox(process_arabic_text(line))[3] + 20 for line in lines_to_draw]
        plate_height = sum(line_heights) + 20
        plate_y0 = (H - plate_height) / 2
        draw.rectangle([(0, plate_y0), (W, plate_y0 + plate_height)], fill=TEXT_PLATE_COLOR)
        draw_multiline_arabic_text(draw, (W - 60, plate_y0, W - 120, plate_height), lines_to_draw, news_font, TEXT_COLOR, SHADOW_COLOR)
        
def scrape_article_page(url):
    try:
        proxies = { "http": "http://proxy.server:3128", "https": "http://proxy.server:3128" }
        headers = {'User-Agent': 'Mozilla/5.0'}; response = requests.get(url, headers=headers, timeout=15, proxies=proxies); response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser');
        title = (soup.find('h1', class_='entry-title') or soup.find('h1')).get_text(strip=True)
        image_url = (soup.find('meta', property='og:image')).get('content')
        if title and image_url: return {'title': title, 'image_url': image_url}
    except Exception as e: print(f"!! خطأ في تحليل الرابط: {e}"); return None
def download_image(url, save_path):
    try:
        proxies = { "http": "http://proxy.server:3128", "https": "http://proxy.server:3128" }
        response = requests.get(url, stream=True, timeout=15, proxies=proxies); response.raise_for_status()
        with open(save_path, 'wb') as f: f.write(response.content)
        return save_path
    except Exception as e: print(f"!! فشل تنزيل الصورة: {e}"); return None
def generate_tts_audio(text, filepath):
    try:
        tts = gTTS(text=text, lang='ar', slow=False); tts.save(filepath)
        print(f"✅ تم إنشاء ملف الصوت من النص: {filepath}"); return filepath
    except Exception as e: print(f"!! فشل في إنشاء الصوت من النص: {e}"); return None
    
def create_video(params):
    design_type = params['design_type']; news_title = params['text']
    template = params['template']; background_image_path = params['image_path']
    W, H = params['dimensions']; tts_enabled = params['tts_enabled']
    intro_path = params['intro_path']; outro_path = params['outro_path']
    music_path = params['music_path']
    unique_id = random.randint(1000, 9999)
    temp_files = []
    try:
        font_size_base = int(W / 12)
        news_font = ImageFont.truetype(FONT_FILE, font_size_base if len(news_title) < 50 else font_size_base - 20)
        if background_image_path and os.path.exists(background_image_path):
            base_image = fit_image_to_box(Image.open(background_image_path).convert("RGB"), W, H)
        else:
            base_image = Image.open(LOGO_FILE).convert("RGB").resize((W,H)).filter(ImageFilter.GaussianBlur(15))
        logo_img = Image.open(LOGO_FILE).convert("RGBA") if os.path.exists(LOGO_FILE) else None
        
        text_pages = [wrap_text_for_arabic(news_title, news_font, W-120)]
        num_pages = len(text_pages)
        
        silent_video_path = os.path.join(app.config['UPLOAD_FOLDER'], f"silent_{unique_id}.mp4"); temp_files.append(silent_video_path)
        video_writer = cv2.VideoWriter(silent_video_path, cv2.VideoWriter_fourcc(*'mp4v'), FPS, (W, H))
        
        for page_lines in text_pages:
            for i in range(int(SECONDS_PER_PAGE * FPS)):
                progress = i / (SECONDS_PER_PAGE * FPS)
                zoom = 1 + progress * (KEN_BURNS_ZOOM_FACTOR - 1)
                zoomed_bg = base_image.resize((int(W*zoom), int(H*zoom)), Image.Resampling.LANCZOS)
                x, y = (zoomed_bg.width - W) // 2, (zoomed_bg.height - H) // 2
                frame_bg = zoomed_bg.crop((x, y, x + W, y + H))
                draw = ImageDraw.Draw(frame_bg, 'RGBA')
                render_design(draw, W, H, design_type, template, page_lines, news_font, logo_img)
                video_writer.write(cv2.cvtColor(np.array(frame_bg), cv2.COLOR_RGB2BGR))
        
        outro_font = ImageFont.truetype(FONT_FILE, int(W / 18))
        for i in range(int(OUTRO_DURATION_SECONDS * FPS)):
            image = Image.new('RGB', (W, H), (10, 10, 10)); draw = ImageDraw.Draw(image, 'RGBA')
            draw_multiline_arabic_text(draw, (W, H/2 - 50, W, 0), [FOOTER_TEXT], outro_font, TEXT_COLOR, SHADOW_COLOR)
            video_writer.write(cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR))
        video_writer.release()
        
        main_video_stream = ffmpeg.input(silent_video_path)
        audio_inputs = []
        if os.path.exists(DEFAULT_SOUND_FILE): audio_inputs.append(ffmpeg.input(DEFAULT_SOUND_FILE))
        if tts_enabled:
            tts_path = os.path.join(app.config['UPLOAD_FOLDER'], f"tts_{unique_id}.mp3"); temp_files.append(tts_path)
            if generate_tts_audio(news_title, tts_path):
                audio_inputs.append(ffmpeg.input(tts_path).filter('adelay', '1000|1000'))
        
        final_music_path = music_path if music_path and os.path.exists(music_path) else DEFAULT_MUSIC_FILE
        if os.path.exists(final_music_path):
            total_duration = (num_pages * SECONDS_PER_PAGE) + OUTRO_DURATION_SECONDS
            music_stream = ffmpeg.input(final_music_path, stream_loop=-1, t=total_duration).filter('volume', BACKGROUND_MUSIC_VOLUME)
            audio_inputs.append(music_stream)
        
        generated_video_path = os.path.join(app.config['UPLOAD_FOLDER'], f"generated_{unique_id}.mp4"); temp_files.append(generated_video_path)
        if audio_inputs:
            mixed_audio = ffmpeg.filter(audio_inputs, 'amix', duration='first', inputs=len(audio_inputs))
            (ffmpeg.output(main_video_stream.video, mixed_audio, generated_video_path, vcodec='libx264', acodec='aac', pix_fmt='yuv420p', preset='fast', crf=28)
             .overwrite_output().run(capture_stdout=True, capture_stderr=True))
        else:
            (ffmpeg.output(main_video_stream.video, generated_video_path, vcodec='copy')
             .run(capture_stdout=True, capture_stderr=True))
        
        videos_to_concat = []
        if intro_path: videos_to_concat.append(ffmpeg.input(intro_path))
        videos_to_concat.append(ffmpeg.input(generated_video_path))
        if outro_path: videos_to_concat.append(ffmpeg.input(outro_path))
        
        final_video_path = os.path.join(app.config['UPLOAD_FOLDER'], f"final_{unique_id}.mp4"); temp_files.append(final_video_path)
        if len(videos_to_concat) > 1:
            print("🔗 دمج المقدمة/الخاتمة...")
            processed_clips = [v.video.filter('scale', W, H).filter('setsar', 1) for v in videos_to_concat]
            processed_audio = [v.audio for v in videos_to_concat]
            (ffmpeg.concat(*processed_clips, *processed_audio, v=1, a=1)
             .output(final_video_path, vcodec='libx264', acodec='aac', crf=28, preset='fast')
             .overwrite_output().run(capture_stdout=True, capture_stderr=True))
        else:
            os.rename(generated_video_path, final_video_path)
            
        thumbnail_path = os.path.join(app.config['UPLOAD_FOLDER'], f"thumb_{unique_id}.jpg"); temp_files.append(thumbnail_path)
        thumb_image = base_image.copy()
        render_design(ImageDraw.Draw(thumb_image, 'RGBA'), W, H, design_type, template, text_pages[0], news_font, logo_img)
        thumb_image.convert('RGB').save(thumbnail_path, quality=85)
        
        return final_video_path, thumbnail_path, temp_files
    except Exception as e:
        print(f"!! خطأ فادح أثناء إنشاء الفيديو: {e}")
        traceback.print_exc()
        return None, None, temp_files
def send_video_to_telegram(video_path, thumb_path, caption, hashtag):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        full_caption = f"{caption}\n\n<b>{hashtag}</b>"
        with open(video_path, 'rb') as vf, open(thumb_path, 'rb') as tf:
            files = {'video': vf, 'thumb': tf}
            data = {'chat_id': TELEGRAM_CHANNEL_ID, 'caption': full_caption, 'parse_mode': 'HTML', 'supports_streaming': True}
            response = requests.post(url, files=files, data=data, timeout=1800)
            if response.status_code == 200: print("✅ تم النشر بنجاح!")
            else: print(f"!! فشل النشر: {response.status_code} - {response.text}")
    except Exception as e: print(f"!! خطأ في الإرسال إلى تليجرام: {e}")

# ==============================================================================
#                      نقاط النهاية (API Endpoints)
# ==============================================================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/scrape-url', methods=['POST'])
def scrape_url_for_preview():
    data = request.get_json()
    url = data.get('url')
    if not url: return jsonify({"error": "URL is required"}), 400
    scraped_data = scrape_article_page(url)
    if scraped_data:
        return jsonify({"title": scraped_data.get('title'), "imageUrl": scraped_data.get('image_url')})
    else:
        return jsonify({"error": "فشل تحليل الرابط. قد يكون غير صالح أو الموقع محمي."}), 404

@app.route('/create-video', methods=['POST'])
def handle_create_video_directly():
    temp_files_to_clean = []
    try:
        form_data = request.form
        source_url = form_data.get('url')
        manual_text = form_data.get('text')
        template_choice = form_data.get('template', '1')
        design_type = form_data.get('design', 'classic')
        video_format = form_data.get('video_format', 'reels')
        tts_enabled = form_data.get('tts_enabled') == 'true'
        W, H = VIDEO_DIMENSIONS[video_format]['size']
        selected_template = NEWS_TEMPLATES[template_choice]

        saved_file_paths = {}
        for key in ['intro_video', 'outro_video', 'music_file', 'background_image']:
            if key in request.files:
                file = request.files[key]
                if file and file.filename:
                    filename = secure_filename(f"{key}_{random.randint(1000,9999)}_{file.filename}")
                    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(path)
                    saved_file_paths[key] = path
                    temp_files_to_clean.append(path)
        
        intro_path = saved_file_paths.get('intro_video')
        outro_path = saved_file_paths.get('outro_video')
        music_path = saved_file_paths.get('music_file')
        
        data = {}
        if source_url and source_url.strip():
            print(f"🔍 محاولة تحليل الرابط: {source_url}")
            article_data = scrape_article_page(source_url)
            if article_data:
                image_save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"bg_{random.randint(1000,9999)}.jpg")
                temp_files_to_clean.append(image_save_path)
                temp_image_path = download_image(article_data['image_url'], image_save_path)
                data = {'text': article_data['title'], 'image_path': temp_image_path, 'url': source_url}
            else:
                 if manual_text and manual_text.strip():
                     print("⚠️ فشل تحليل الرابط، سيتم استخدام النص اليدوي كبديل.")
                     manual_bg_path = saved_file_paths.get('background_image')
                     data = {'text': manual_text, 'image_path': manual_bg_path, 'url': None}
                 else:
                     return jsonify({"status": "error", "message": "فشل تحليل الرابط ولم يتم توفير نص بديل."}), 400
        elif manual_text and manual_text.strip():
            manual_bg_path = saved_file_paths.get('background_image')
            data = {'text': manual_text, 'image_path': manual_bg_path, 'url': None}
        else:
            return jsonify({"status": "error", "message": "يرجى توفير رابط أو نص يدوي."}), 400
            
        params = {**data, 'design_type': design_type, 'template': selected_template, 'dimensions': (W, H), 
                  'tts_enabled': tts_enabled, 'intro_path': intro_path, 'outro_path': outro_path, 'music_path': music_path}
        
        final_video, final_thumb, created_files = create_video(params)
        if created_files: temp_files_to_clean.extend(created_files)
        
        if final_video and final_thumb:
            caption_parts = [data['text']]
            if data.get('url'): caption_parts.extend(["", f"<b>{DETAILS_TEXT}</b> {data['url']}"])
            caption = "\n".join(caption_parts)
            send_video_to_telegram(final_video, final_thumb, caption, selected_template['hashtag'])
            return jsonify({"status": "success", "message": "تم إنشاء الفيديو ونشره بنجاح!"}), 200
        else:
            raise RuntimeError("فشلت عملية إنشاء الفيديو النهائية.")

    except Exception as e:
        print(f"!! حدث خطأ غير متوقع في معالجة الطلب: {e}")
        traceback.print_exc()
        error_message = str(e)
        return jsonify({"status": "error", "message": f"حدث خطأ فادح في الخادم: {error_message}"}), 500
    finally:
        print(f"🧹 تنظيف {len(temp_files_to_clean)} ملف مؤقت...")
        for f in temp_files_to_clean:
            if f and os.path.exists(f):
                try: os.remove(f)
                except Exception as e: print(f"  - لم يتمكن من حذف {f}: {e}")