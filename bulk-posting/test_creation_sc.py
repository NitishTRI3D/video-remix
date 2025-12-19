
from moviepy import VideoFileClip
import os
import requests
import time


JOB_NAME='sharechat-trending-posts'

# Content creator details
userId='3862309156'
userName='dileselikha'

# Sample video file
video_file="/Users/parvathi/Desktop/shayari_dist/outputs/test/shayari_002_20251213-0608PM.mp4"

# Sample tag
tagId= 10588444
tagName= '💔 हार्ट ब्रेक स्टेटस'

# Sample title
title = 'shayari' 

# Get video size, height etc required in payload
def get_details_moviepy(file_path):
    # Get file size
    size_bytes = os.path.getsize(file_path)
    size_mb = size_bytes / (1024 * 1024)

    # Load clip
    try:
        clip = VideoFileClip(file_path)
        
        print(f"--- Details for: {file_path} ---")
        print(f"Dimensions: {clip.w} x {clip.h}")
        print(f"Duration:   {clip.duration:.2f} seconds")
        print(f"File Size:  {size_mb:.2f} MB")
        height = clip.h
        width = clip.w
        duration = clip.duration
        size = size_bytes
        # Close the clip to release memory (important in loops)
        clip.close() 

        return {
            'height': height,
            'width': width,
            'duration': duration,
            'size': size
        }
        
    except Exception as e:
        print(f"Error reading file: {e}")


# Payload for content creation
def generate_payload(title, contentType, fileUrl, language, thumbnail, thumbnailBase64, height, width, size, duration=0):
    content_type = contentType
    curr_time = int(time.time() * 1000)
    
    caption_tags_list = [{
        "tagId": tagId,
        "tagName": tagName
    }]

    tt = [{
        "i": tagId,
        "n": tagName
    }]

    encoded_text_v2 = f"{{[{{{tagId}}}]}}"

    post_url_to_add = {}
    
    if content_type == 'image':
        post_url_to_add["g"] = fileUrl
        file_type = f"{constants['IMAGE']}/{fileUrl.split('.')[-1]}"
    else:
        post_url_to_add["v"] = fileUrl
        file_type = "video/mp4"

    req_body = {
        "userId": userId,
        "passCode": "-1",
        "message": {
            "tt": tt,
            "encodedTextV2": encoded_text_v2,
            "c": title,
            "captionTagsList": caption_tags_list,
            "a": userId,
            "m": language,
            "n": userName,
            "cd": "0",
            "q": file_type,
            "pi": curr_time,
            "h": height,
            "z": size,
            "t": content_type,
            "w": width,
            "sd": 0,
            "createdVia": "developer",
            "i": f"-{curr_time}",
            "thb": thumbnailBase64,
            "b": thumbnail,
            "urlList": [],
            "o": curr_time // 1000,
            "reviewer": JOB_NAME,
            "create_type": 'newsdataexternal',
            "d": int(duration),
            "skipVideoCodecEncodings": False,
            **post_url_to_add
        }
    }

    return req_body


# Post content
def post_content(url, payload):
    try:
        response = requests.post(
            url,
            headers={
                'X-SHARECHAT-CALLER': JOB_NAME,
                'accept-encoding': 'gzip',
                'X-SHARECHAT-AUTHORIZED-USERID': userId
            },
            json=payload
        )
        return response.json()
    except Exception as err:
        print(f"[ERROR] Request to {url} failed: {err}")


# Media upload
def upload_file(userId, file_path, media_type, thumb_not_required=False):
    headers = {
        "X-SHARECHAT-AUTHORIZED-USERID": userId,
        'X-SHARECHAT-CALLER': JOB_NAME
    }

    url='http://media-upload-service.sharechat.internal/media-upload-service/v1.0.0/fileUpload'

    try:
        # Open the file in binary mode
        with open(file_path, 'rb') as f:
            files = {
                'userfile': (f.name, f, media_type),  # or change MIME type if needed
                "thumbNotRequired": (None, "true" if thumb_not_required else "false")
            }
            response = requests.post(url, headers=headers, files=files)
            return response.json()
    except Exception as e:
        print("Failed uploading media", e)


# Uploading video
video=upload_file(userId, video_file, 'video/mp4', False)
# Fetching video details
video_details = get_details_moviepy(video_file)

# print(video_details)


payload = generate_payload(
    title, 
    'video', 
    video['fileUrl'], 
    'Hindi',
    video['thumbUrl'], 
    video['thumbByte'], 
    video_details['height'], 
    video_details['width'], 
    video_details['size'], 
    video_details['duration']
    )
    
url = "http://compose-service-v2.sharechat.internal/compose-service/v1.0.0/uploadugc"

response = post_content(url, payload)

print('post_id', response['data']['p'])