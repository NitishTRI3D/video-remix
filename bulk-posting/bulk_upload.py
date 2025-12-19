from moviepy import VideoFileClip
from PIL import Image
import os
import requests
import time
import json
import sys
import argparse

JOB_NAME='sharechat-trending-posts'

def get_details_moviepy(file_path):
    size_bytes = os.path.getsize(file_path)
    size_mb = size_bytes / (1024 * 1024)

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
        clip.close() 

        return {
            'height': height,
            'width': width,
            'duration': duration,
            'size': size
        }
        
    except Exception as e:
        print(f"Error reading file: {e}")

def get_image_details(file_path):
    size_bytes = os.path.getsize(file_path)
    size_mb = size_bytes / (1024 * 1024)
    
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            
        print(f"--- Details for: {file_path} ---")
        print(f"Dimensions: {width} x {height}")
        print(f"File Size:  {size_mb:.2f} MB")
        
        return {
            'height': height,
            'width': width,
            'size': size_bytes
        }
    except Exception as e:
        print(f"Error reading image file: {e}")

def generate_payload(title, contentType, fileUrl, language, thumbnail, thumbnailBase64, height, width, size, duration, tagId, tagName, userId, userName):
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
        file_type = f"image/{fileUrl.split('.')[-1]}"
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
            "d": int(duration) if duration else 0,
            "skipVideoCodecEncodings": False,
            **post_url_to_add
        }
    }

    return req_body

def post_content(url, payload):
    try:
        response = requests.post(
            url,
            headers={
                'X-SHARECHAT-CALLER': JOB_NAME,
                'accept-encoding': 'gzip',
                'X-SHARECHAT-AUTHORIZED-USERID': payload["userId"]
            },
            json=payload
        )
        return response.json()
    except Exception as err:
        print(f"[ERROR] Request to {url} failed: {err}")

def upload_file(userId, file_path, media_type, thumb_not_required=False):
    headers = {
        "X-SHARECHAT-AUTHORIZED-USERID": userId,
        'X-SHARECHAT-CALLER': JOB_NAME
    }

    url='http://media-upload-service.sharechat.internal/media-upload-service/v1.0.0/fileUpload'

    try:
        with open(file_path, 'rb') as f:
            files = {
                'userfile': (f.name, f, media_type),
                "thumbNotRequired": (None, "true" if thumb_not_required else "false")
            }
            response = requests.post(url, headers=headers, files=files)
            return response.json()
    except Exception as e:
        print("Failed uploading media", e)

def process_upload(entry, index, uploads, json_file):
    print(f"\n{'='*60}")
    print(f"Processing upload for user: {entry['userName']} ({entry['userId']})")
    print(f"Asset: {entry['assetPath']}")
    print(f"Type: {entry['assetType']}")
    print(f"Tag: {entry['tagName']} ({entry['tagId']})")
    
    # Check if already uploaded
    if 'postId' in entry and entry['postId']:
        print(f"[SKIP] Already uploaded. Post ID: {entry['postId']}")
        print(f"{'='*60}\n")
        return True
    
    print(f"{'='*60}\n")
    
    try:
        if entry['assetType'] == 'image':
            media_response = upload_file(entry['userId'], entry['assetPath'], 'image/jpeg', False)
            media_details = get_image_details(entry['assetPath'])
            duration = 0
        else:
            media_response = upload_file(entry['userId'], entry['assetPath'], 'video/mp4', False)
            media_details = get_details_moviepy(entry['assetPath'])
            duration = media_details['duration']
        
        if not media_response or 'fileUrl' not in media_response:
            print(f"[ERROR] Failed to upload media for {entry['userName']}")
            return False
            
        print(f"Media uploaded successfully: {media_response['fileUrl']}")
        
        payload = generate_payload(
            entry['title'],
            entry['assetType'],
            media_response['fileUrl'],
            entry['language'],
            media_response.get('thumbUrl', ''),
            media_response.get('thumbByte', ''),
            media_details['height'],
            media_details['width'],
            media_details['size'],
            duration,
            entry['tagId'],
            entry['tagName'],
            entry['userId'],
            entry['userName']
        )
        
        url = "http://compose-service-v2.sharechat.internal/compose-service/v1.0.0/uploadugc"
        response = post_content(url, payload)
        
        if response and 'data' in response and 'p' in response['data']:
            post_id = response['data']['p']
            print(f"[SUCCESS] Post created! Post ID: {post_id}")
            
            # Update the entry with postId
            uploads[index]['postId'] = post_id
            
            # Save back to JSON file
            with open(json_file, 'w') as f:
                json.dump(uploads, f, indent=2, ensure_ascii=False)
            print(f"[INFO] Updated {json_file} with postId")
            
            return True
        else:
            print(f"[ERROR] Failed to create post for {entry['userName']}")
            print(f"Response: {response}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Exception while processing upload for {entry['userName']}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Bulk upload posts to ShareChat')
    parser.add_argument('json_file', nargs='?', default='to_be_uploaded.json', help='JSON file with upload entries')
    parser.add_argument('--index', type=int, help='Process only a specific index (0-based)')
    parser.add_argument('--max-index', type=int, help='Process only up to this index (0-based)')
    
    args = parser.parse_args()
    
    print(f"Loading uploads from: {args.json_file}")
    
    try:
        with open(args.json_file, 'r') as f:
            uploads = json.load(f)
    except Exception as e:
        print(f"Error loading JSON file: {e}")
        return
    
    print(f"Found {len(uploads)} uploads in file")
    
    # If specific index is provided, process only that entry
    if args.index is not None:
        if 0 <= args.index < len(uploads):
            print(f"Processing only index {args.index}")
            entry = uploads[args.index]
            print(f"\n[{args.index+1}/{len(uploads)}] Processing...")
            process_upload(entry, args.index, uploads, args.json_file)
        else:
            print(f"Error: Index {args.index} is out of range (0-{len(uploads)-1})")
        return
    
    # Otherwise, process all entries
    successful = 0
    failed = 0
    skipped = 0
    
    # Determine the range to process
    max_index = args.max_index if args.max_index is not None else len(uploads) - 1
    max_index = min(max_index, len(uploads) - 1)  # Ensure we don't exceed list bounds
    
    print(f"Processing entries 0 to {max_index} (total: {max_index + 1} entries)")
    
    for i in range(max_index + 1):
        entry = uploads[i]
        print(f"\n[{i+1}/{max_index + 1}] Processing...")
        
        # Check if already has postId
        if 'postId' in entry and entry['postId']:
            skipped += 1
            print(f"[SKIP] Entry {i} already has postId: {entry['postId']}")
            continue
            
        if process_upload(entry, i, uploads, args.json_file):
            successful += 1
        else:
            failed += 1
        
        time.sleep(2)
    
    print(f"\n{'='*60}")
    print(f"BULK UPLOAD COMPLETE")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Skipped: {skipped}")
    print(f"Total: {len(uploads)}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()