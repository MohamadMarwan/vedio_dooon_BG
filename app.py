# ==============================================================================
#     أداة إنشاء الفيديو الإخباري كخدمة ويب (API) - إصدار 8.0
#     - تحويل الكود ليعمل كـ API باستخدام Flask.
#     - إضافة إمكانية دمج مقدمة وخاتمة مخصصتين.
#     - استقبال الإعدادات (نص، تصميم، ألوان) عبر الطلبات.
# ==============================================================================
import os
import random
import cv2
import numpy as np
import ffmpeg
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display
import time
import threading
import traceback
from flask import Flask, request, jsonify

# ==============================================================================
#                                   الإعدادات العامة
# ==============================================================================
app = Flask(__name__)

# إعدادات تليجرام
TELEGRAM_BOT_TOKEN = "7642666619:AAH3-MtRPnv4P9jFUnZW5zajArMwuWC-r-g"  # استبدل هذا بالتوكن الخاص بك
TELEGRAM_CHANNEL_ID = "-1002557612563"   # استبدل هذا بمعرف القناة (مثلاً @mychannel أو -100123456789)

# --- تأكد من وجود هذه الملفات في نفس المجلد ---
FONT_FILE = "Amiri-Bold.ttf"
LOGO_FILE = "logo.png"
BACKGROUND_MUSIC_FILES=["نغمه الجزيره عاجل للرسائل.mp3", "موسيقى نشرة الاخبار للمونتاج.mp3", "جديد  ... موسيقى نشرة الأخبار في قناة الجزيرة.mp3"]
TRANSITION_SFX_FILE="whoosh.mp3"

# --- إعدادات الفيديو ---
W, H = 1920, 1080
FPS = 30
MAX_VIDEO_DURATION_SECONDS = 60
MIN_SCENE_DURATION_S = 4.5
WORDS_PER_SECOND = 2.5
INTRO_DURATION_S = 4.0
OUTRO_DURATION_S = 7.0
BACKGROUND_MUSIC_VOLUME=0.1
TRANSITION_SFX_VOLUME=0.4

# --- قوالب التصاميم والأخبار ---
NEWS_CATEGORIES={"1":{"name":"عاجل","color":(211,47,47)}, "2":{"name":"أخبار","color":(0,128,212)}, "3":{"name":"رياضة","color":(76,175,80)}}
DESIGN_TEMPLATES={"1":{"name":"ديناميكي","render_function":"render_dynamic_split_scene"},"2":{"name":"سينمائي","render_function":"render_cinematic_overlay_scene"},"3":{"name":"عصري","render_function":"render_modern_grid_scene"}}

# ( ... هنا يتم نسخ جميع الدوال المساعدة من الكود الأصلي بدون تغيير ... )
#  process_text, draw_text, fit_image_ken_burns, wrap_text, 
#  scrape_article_data, download_images, send_video_to_telegram,
#  draw_text_word_by_word, render_dynamic_split_scene,
#  render_cinematic_overlay_scene, render_modern_grid_scene,
#  render_title_scene, render_source_outro_scene

# ==============================================================================
#                             الدوال المساعدة (نسخ ولصق من الكود الأصلي)
# ==============================================================================
def ease_in_out_quad(t): return 2*t*t if t<0.5 else 1-pow(-2*t+2,2)/2
def process_text(text): return get_display(arabic_reshaper.reshape(text))
def draw_text(draw, pos, text, font, fill, shadow, offset=(2,2)):
    proc_text=process_text(text); draw.text((pos[0]+offset[0],pos[1]+offset[1]),proc_text,font=font,fill=shadow); draw.text(pos,proc_text,font=font,fill=fill)
def fit_image_ken_burns(img, frame_idx, total_frames):
    zoom_factor=1.20; progress=frame_idx/total_frames; current_zoom=1+(zoom_factor-1)*ease_in_out_quad(progress)
    zoomed_w,zoomed_h=int(W*current_zoom),int(H*current_zoom); img=img.resize((zoomed_w,zoomed_h),Image.Resampling.LANCZOS)
    x_offset=(zoomed_w-W)/2; y_offset=(zoomed_h-H)*progress
    return img.crop((x_offset,y_offset,x_offset+W,y_offset+H))
def wrap_text(text, font, max_width):
    lines,words=[],text.split(); current_line=""
    for word in words:
        if font.getbbox(process_text(f"{current_line} {word}"))[2]<=max_width: current_line=f"{current_line} {word}".strip()
        else: lines.append(current_line); current_line=word
    lines.append(current_line)
    return [l for l in lines if l]

def scrape_article_data(url):
    print(f"🔍 تحليل الرابط: {url}");
    try:
        headers={'User-Agent':'Mozilla/5.0'}; res=requests.get(url,headers=headers,timeout=15); res.raise_for_status()
        soup=BeautifulSoup(res.content,'html.parser')
        title_tag=soup.find('h1') or soup.find('meta',property='og:title')
        title=title_tag.get_text(strip=True) if hasattr(title_tag,'get_text') else title_tag.get('content','')
        content_div=soup.find('div',class_='entry-content') or soup.find('article')
        content=" ".join([p.get_text(strip=True) for p in (content_div or soup).find_all('p')])
        image_urls=set()
        og_image=soup.find('meta',property='og:image')
        if og_image: image_urls.add(og_image['content'])
        for img_tag in (content_div or soup).find_all('img',limit=5):
            src=img_tag.get('src') or img_tag.get('data-src')
            if src and src.startswith('http'): image_urls.add(src)
        print(f"✅ تم العثور على العنوان و {len(image_urls)} رابط صورة.");
        return {'title':title,'content':content,'image_urls':list(image_urls)}
    except Exception as e: print(f"!! خطأ في تحليل الرابط: {e}"); return None

def download_file(url, prefix=""):
    try:
        res = requests.get(url, stream=True, timeout=20)
        res.raise_for_status()
        path = f"temp_{prefix}{random.randint(1000, 9999)}.tmp"
        with open(path, 'wb') as f:
            for chunk in res.iter_content(chunk_size=8192):
                f.write(chunk)
        return path
    except Exception as e:
        print(f"  !! فشل تنزيل الملف: {url[:50]}... ({e})")
        return None

def send_video_to_telegram(video_path, thumb_path, caption):
    print("--> جاري نشر الفيديو عبر Requests...")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        with open(video_path, 'rb') as video_file, open(thumb_path, 'rb') as thumb_file:
            payload={'chat_id':TELEGRAM_CHANNEL_ID,'caption':caption,'parse_mode':'HTML','supports_streaming':True}
            files={'video':video_file,'thumb':thumb_file}
            response = requests.post(url, data=payload, files=files, timeout=1800)
            if response.status_code == 200:
                print("✅ تم النشر بنجاح!"); return True
            else:
                print(f"!! فشل النشر. استجابة تليجرام: {response.status_code} - {response.text}"); return False
    except requests.exceptions.RequestException as e:
        print(f"!! خطأ فادح أثناء الاتصال بتليجرام: {e}"); return False

def draw_text_word_by_word(draw, box_coords, lines, words_to_show, font, fill, shadow):
    x, y, w, h = box_coords; line_height = font.getbbox("ا")[3] + 20
    total_text_height = len(lines) * line_height; current_y = y + (h - total_text_height) / 2
    words_shown = 0
    for line in lines:
        words_in_line = line.split(); words_to_draw_in_line = []
        for word in words_in_line:
            if words_shown < words_to_show: words_to_draw_in_line.append(word); words_shown += 1
            else: break
        if words_to_draw_in_line:
            partial_line = " ".join(words_to_draw_in_line)
            processed_partial_line = process_text(partial_line)
            line_width = font.getbbox(processed_partial_line)[2]
            draw_text(draw, (x + w - line_width, current_y), partial_line, font, fill, shadow)
        current_y += line_height
        if words_shown >= words_to_show: break

def render_dynamic_split_scene(frame_idx, total_frames, text_lines, image, cat, text_color, shadow_color):
    frame=Image.new('RGB',(W,H),(15,15,15)); img_w=W//2; frame.paste(image.resize((img_w,H)),(0,0))
    grad=Image.new('RGBA',(img_w,H),(0,0,0,0)); g_draw=ImageDraw.Draw(grad)
    for j in range(img_w//2): g_draw.line([(img_w-j,0),(img_w-j,H)],fill=(0,0,0,int(255*(j/(img_w//2)))),width=1)
    frame.paste(grad,(0,0),grad); draw=ImageDraw.Draw(frame)
    text_font=ImageFont.truetype(FONT_FILE,int(W/28))
    total_words = len(" ".join(text_lines).split()); words_to_show = int((frame_idx / total_frames) * total_words * 1.5) +1
    draw_text_word_by_word(draw,(W//2+50,0,(W//2)-100,H),text_lines,words_to_show,text_font,text_color,shadow_color)
    return frame

def render_cinematic_overlay_scene(frame_idx, total_frames, text_lines, image, cat, text_color, shadow_color):
    frame=fit_image_ken_burns(image,frame_idx,total_frames); draw=ImageDraw.Draw(frame,'RGBA')
    text_font=ImageFont.truetype(FONT_FILE,int(W/25)); line_height=text_font.getbbox("ا")[3]+20
    plate_height=(len(text_lines)*line_height)+60; draw.rectangle([(0,H-plate_height),(W,H)],fill=(0,0,0,180))
    total_words=len(" ".join(text_lines).split()); words_to_show = int((frame_idx / total_frames) * total_words * 1.5) +1
    draw_text_word_by_word(draw,(80,H-plate_height,W-160,plate_height),text_lines,words_to_show,text_font,text_color,shadow_color)
    return frame

def render_modern_grid_scene(frame_idx, total_frames, text_lines, image, cat, text_color, shadow_color):
    frame=fit_image_ken_burns(image,frame_idx,total_frames).point(lambda p:p*0.5); draw=ImageDraw.Draw(frame,'RGBA')
    padding=80; draw.rectangle([(padding,padding),(W-padding,H-padding)],outline=cat['color'],width=5)
    draw.rectangle([(padding+10,padding+10),(W-padding-10,H-padding-10)],fill=(0,0,0,190))
    text_font=ImageFont.truetype(FONT_FILE,int(W/26)); total_words=len(" ".join(text_lines).split()); words_to_show = int((frame_idx / total_frames) * total_words * 1.5) + 1
    box=(padding+40,padding+40,W-2*(padding+40),H-2*(padding+40))
    draw_text_word_by_word(draw,box,text_lines,words_to_show,text_font,text_color,shadow_color)
    return frame

def render_title_scene(writer,duration,text,image_path,cat,text_color,shadow_color):
    frames=int(duration*FPS); img=Image.open(image_path).convert("RGB"); title_font=ImageFont.truetype(FONT_FILE,int(W/18)); cat_font=ImageFont.truetype(FONT_FILE,int(W/35))
    for i in range(frames):
        frame=fit_image_ken_burns(img,i,frames); draw=ImageDraw.Draw(frame,'RGBA'); draw.rectangle([(0,H*0.6),(W,H)],fill=(0,0,0,180))
        draw_text(draw,(W-300,H*0.65),cat['name'],cat_font,cat['color'],(0,0,0,150))
        wrapped_lines=wrap_text(text,title_font,W-150); y=H*0.72
        for line in wrapped_lines: bbox=title_font.getbbox(process_text(line)); draw_text(draw,(W-bbox[2]-80,y),line,title_font,text_color,shadow_color); y+=bbox[3]*1.3
        writer.write(cv2.cvtColor(np.array(frame),cv2.COLOR_RGB2BGR))

def render_source_outro_scene(writer,duration,logo_path,text_color,shadow_color):
    frames=int(duration*FPS); font_big=ImageFont.truetype(FONT_FILE,int(W/28)); font_small=ImageFont.truetype(FONT_FILE,int(W/45))
    logo=Image.open(logo_path).convert("RGBA") if logo_path and os.path.exists(logo_path) else None
    text1="للتفاصيل الكاملة ومتابعة آخر الأخبار"
    text2="قــم بــزيــارة مــوقــعــنــا"
    for i in range(frames):
        progress=i/frames; frame=Image.new('RGB',(W,H),(10,10,10)); draw=ImageDraw.Draw(frame,'RGBA')
        if logo:
            size=int((W/4.5)*ease_in_out_quad(progress))
            if size>0: l=logo.resize((size,size),Image.Resampling.LANCZOS); frame.paste(l,((W-size)//2,H//2-size-20),l)
        if progress>0.2:
            alpha=int(255*ease_in_out_quad((progress-0.2)/0.8))
            final_text_color=(*tuple(int(text_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)), alpha)
            final_shadow_color=(*tuple(int(shadow_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)), int(alpha*0.8))
            y_pos=H//2+50
            bbox1=font_big.getbbox(process_text(text1)); draw_text(draw,((W-bbox1[2])/2,y_pos),text1,font_big,final_text_color,final_shadow_color)
            bbox2=font_small.getbbox(process_text(text2)); draw_text(draw,((W-bbox2[2])/2,y_pos+100),text2,font_small,final_text_color,final_shadow_color)
        writer.write(cv2.cvtColor(np.array(frame),cv2.COLOR_RGB2BGR))

# ==============================================================================
#                      الوظيفة الرئيسية لإنشاء الفيديو (معدلة)
# ==============================================================================
def create_story_video(params):
    article_data = params['article_data']
    cat = params['category']
    image_paths = params['image_paths']
    design_choice = params['design']
    text_color = params['text_color']
    shadow_color = params['shadow_color']
    intro_video_path = params.get('intro_video_path')
    outro_video_path = params.get('outro_video_path')
    
    if not image_paths:
        raise ValueError("لا يمكن إنشاء الفيديو بدون صور.")

    # الحصول على دالة التصيير الصحيحة من اسمها كنص
    render_function_name = DESIGN_TEMPLATES[design_choice]["render_function"]
    render_function = globals()[render_function_name]

    scenes=[]; current_duration=INTRO_DURATION_S+OUTRO_DURATION_S
    content_sentences=[s.strip() for s in article_data.get('content','').split('.') if len(s.strip())>20]
    available_images=image_paths[1:] if len(image_paths)>1 else list(image_paths)
    current_text_chunk=""
    
    for sentence in content_sentences:
        current_text_chunk+=sentence+". "
        words_in_chunk=len(current_text_chunk.split())
        if words_in_chunk>30 and available_images:
            estimated_scene_duration=max(MIN_SCENE_DURATION_S,words_in_chunk/WORDS_PER_SECOND)
            if current_duration+estimated_scene_duration > MAX_VIDEO_DURATION_SECONDS:
                print(f"⚠️ تم الوصول للحد الأقصى للمدة ({MAX_VIDEO_DURATION_SECONDS} ثانية)."); break 
            img_scene=available_images.pop(0)
            scenes.append({'duration':estimated_scene_duration,'text':current_text_chunk,'image':img_scene}); 
            current_duration+=estimated_scene_duration; current_text_chunk=""
            if not available_images: available_images=list(image_paths)
    
    silent_path=f"silent_v_{random.randint(1000,9999)}.mp4"; writer=cv2.VideoWriter(silent_path,cv2.VideoWriter_fourcc(*'mp4v'),FPS,(W,H))
    total_duration = INTRO_DURATION_S + sum(s['duration'] for s in scenes) + OUTRO_DURATION_S
    print(f"🎬 فيديو من {len(scenes)+2} مشاهد، بمدة نهائية: {total_duration:.1f} ثانية.")
    sfx_times=[INTRO_DURATION_S]
    
    render_title_scene(writer,INTRO_DURATION_S,article_data['title'],image_paths[0],cat,text_color,shadow_color)
    for scene in scenes:
        print(f"  -> تصيير مشهد نصي لمدة {scene['duration']:.1f} ثانية...")
        frames_scene=int(scene['duration']*FPS); image=Image.open(scene['image']).convert("RGB")
        text_font=ImageFont.truetype(FONT_FILE, int(W / 26))
        text_lines=wrap_text(scene['text'],text_font,W//2-120 if design_choice=="1" else W-160)
        for i in range(frames_scene):
            frame=render_function(i,frames_scene,text_lines,image,cat,text_color,shadow_color)
            writer.write(cv2.cvtColor(np.array(frame),cv2.COLOR_RGB2BGR))
        sfx_times.append(sfx_times[-1]+scene['duration'])
    
    render_source_outro_scene(writer,OUTRO_DURATION_S,LOGO_FILE,text_color,shadow_color); 
    writer.release()
    
    print("🔊 دمج الصوتيات...");
    output_video_name = f"news_{random.randint(1000, 9999)}.mp4"
    try:
        vid_stream=ffmpeg.input(silent_path); audio_inputs=[]
        music_file=random.choice([f for f in BACKGROUND_MUSIC_FILES if os.path.exists(f)] or [None])
        if music_file: audio_inputs.append(ffmpeg.input(music_file,stream_loop=-1,t=total_duration).filter('volume',BACKGROUND_MUSIC_VOLUME).filter('afade',type='out',start_time=total_duration-3,duration=3))
        
        if os.path.exists(TRANSITION_SFX_FILE) and sfx_times:
            sfx_input = ffmpeg.input(TRANSITION_SFX_FILE)
            sfx_vol = sfx_input.filter('volume', TRANSITION_SFX_VOLUME)
            sfx_streams = sfx_vol.asplit(len(sfx_times))
            for i, time_s in enumerate(sfx_times):
                audio_inputs.append(sfx_streams[i].filter('adelay',f'{int(time_s*1000)}ms|{int(time_s*1000)}ms'))

        if audio_inputs:
            mixed_audio=ffmpeg.filter(audio_inputs,'amix',duration='first',inputs=len(audio_inputs))
            (ffmpeg.output(vid_stream, mixed_audio, output_video_name, vcodec='libx264', acodec='aac',
                       pix_fmt='yuv420p', preset='fast', crf=28, audio_bitrate='96k')
             .overwrite_output().run(capture_stdout=True, capture_stderr=True))
        else:
            (ffmpeg.output(vid_stream, output_video_name, vcodec='copy')
             .run(capture_stdout=True, capture_stderr=True))
    except ffmpeg.Error as e:
        raise RuntimeError(f"FFMPEG Error: {e.stderr.decode()}")
    finally:
        if os.path.exists(silent_path): os.remove(silent_path)
    
    # --- دمج المقدمة والخاتمة ---
    final_video_path = f"final_{random.randint(1000,9999)}.mp4"
    videos_to_concat = []
    if intro_video_path:
        videos_to_concat.append(ffmpeg.input(intro_video_path))
    videos_to_concat.append(ffmpeg.input(output_video_name))
    if outro_video_path:
        videos_to_concat.append(ffmpeg.input(outro_video_path))

    if len(videos_to_concat) > 1:
        print("🔗 دمج المقدمة/الخاتمة...")
        try:
            # التأكد من تطابق الأبعاد والـ FPS (هذا مثال مبسط)
            processed_clips = []
            for v in videos_to_concat:
                # [v, a]
                processed_clips.append(v.video.filter('scale', W, H).filter('setsar', 1))
                processed_clips.append(v.audio)

            (ffmpeg.concat(*processed_clips, v=1, a=1)
                   .output(final_video_path, vcodec='libx264', acodec='aac', crf=28, preset='fast')
                   .overwrite_output().run(capture_stdout=True,capture_stderr=True))
        except ffmpeg.Error as e:
            raise RuntimeError(f"FFMPEG Concat Error: {e.stderr.decode()}")
        
        if os.path.exists(output_video_name): os.remove(output_video_name) # حذف الفيديو الوسيط
    else:
        final_video_path = output_video_name # لا يوجد دمج، استخدم الفيديو الأصلي

    # --- إنشاء الصورة المصغرة ---
    thumb_name = f"thumb_{random.randint(1000, 9999)}.jpg"
    thumb=Image.open(image_paths[0]).convert("RGB").resize((W,H)); draw_t=ImageDraw.Draw(thumb,'RGBA')
    draw_t.rectangle([(0,0),(W,H)],fill=(0,0,0,100)); font_t=ImageFont.truetype(FONT_FILE,int(W/15))
    lines=wrap_text(article_data['title'],font_t,W-100); y=H/2-(len(lines)*120)/2
    for line in lines: draw_text(draw_t,((W-font_t.getbbox(process_text(line))[2])/2,y),line,font_t,text_color,shadow_color); y+=120
    thumb.save(thumb_name,'JPEG',quality=85)
    
    return final_video_path, thumb_name

# ==============================================================================
#                          نقطة الدخول للـ API
# ==============================================================================
@app.route('/create-video', methods=['POST'])
def handle_create_video():
    # استخدام threading لتشغيل العملية في الخلفية وإرجاع استجابة فورية
    thread = threading.Thread(target=process_video_request, args=(request.json,))
    thread.start()
    
    # --- ميزة المعاينة (مبسطة) ---
    # بدلاً من الانتظار، يمكنك إرجاع معرف مهمة يمكن للواجهة الاستعلام عنه لاحقاً
    return jsonify({
        "status": "processing",
        "message": "بدأت عملية إنشاء الفيديو. سيتم النشر على تليجرام عند الانتهاء."
    }), 202

def process_video_request(data):
    # هذه الدالة تعمل في الخلفية
    source_url = data.get('url')
    manual_text = data.get('text')
    cat_choice = data.get('category', '1')
    design_choice = data.get('design', '1')
    text_color = data.get('textColor', '#FFFFFF')
    shadow_color = data.get('shadowColor', '#000000')
    intro_url = data.get('introUrl')
    outro_url = data.get('outroUrl')
    
    temp_files_to_clean = []
    try:
        # --- تحضير البيانات ---
        article_data, image_paths = None, []
        if source_url:
            scraped_data = scrape_article_data(source_url)
            if scraped_data:
                article_data = scraped_data
                img_urls = article_data.get('image_urls', [])
                for url in img_urls:
                    path = download_file(url, "img_")
                    if path:
                        image_paths.append(path)
                        temp_files_to_clean.append(path)
        elif manual_text:
            article_data = {'title': manual_text, 'content': ''}

        if not image_paths and os.path.exists(LOGO_FILE):
            image_paths = [LOGO_FILE]

        if not (article_data and image_paths):
            raise ValueError("فشل في تحضير البيانات أو الصور للفيديو.")

        # --- تحميل فيديو المقدمة والخاتمة ---
        intro_path = download_file(intro_url, "intro_") if intro_url else None
        if intro_path: temp_files_to_clean.append(intro_path)
        outro_path = download_file(outro_url, "outro_") if outro_url else None
        if outro_path: temp_files_to_clean.append(outro_path)

        params = {
            'article_data': article_data,
            'category': NEWS_CATEGORIES[cat_choice],
            'image_paths': image_paths,
            'design': design_choice,
            'text_color': text_color,
            'shadow_color': shadow_color,
            'intro_video_path': intro_path,
            'outro_video_path': outro_path
        }
        
        # --- إنشاء الفيديو ---
        video_file, thumb_file = create_story_video(params)
        temp_files_to_clean.extend([video_file, thumb_file])
        
        # --- إرسال إلى تليجرام ---
        if video_file and thumb_file:
            print(f"✅ نجاح! تم إنشاء '{video_file}' و '{thumb_file}'.")
            caption = [f"<b>{article_data['title']}</b>", ""]
            if source_url:
                caption.append(f"🔗 <b>المصدر:</b> {source_url}")
            send_video_to_telegram(video_file, thumb_file, "\n".join(caption))
        else:
            print("❌ فشلت عملية إنشاء الفيديو.")

    except Exception as e:
        print(f"!! خطأ فادح في معالجة الطلب: {e}")
        traceback.print_exc()
    finally:
        # --- تنظيف الملفات المؤقتة ---
        print("🧹 تنظيف الملفات المؤقتة...")
        for f in temp_files_to_clean:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception as e:
                    print(f"  - لم يتمكن من حذف {f}: {e}")

if __name__ == "__main__":
    # هذا الأمر لتشغيل الخادم محلياً للتجربة فقط
    # عند النشر على منصة استضافة، ستستخدم خادم ويب مثل Gunicorn
    app.run(host='0.0.0.0', port=5000, debug=True)