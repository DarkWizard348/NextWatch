import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from googleapiclient.discovery import build
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

# Load API Key from .env
load_dotenv()
API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    raise Exception("YOUTUBE_API_KEY not found in environment")

app = FastAPI(title="Next Vlog Finder API")

# FRONTEND SUPPORT
templates_dir = "templates"
templates = Jinja2Templates(directory=templates_dir)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Safety check for index.html
index_path = os.path.join(templates_dir, "index.html")
if not os.path.exists(index_path):
    print(f"Warning: index.html not found in {templates_dir} folder! Server will still run.")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# YouTube API setup
youtube = build("youtube", "v3", developerKey=API_KEY)

class VideoRequest(BaseModel):
    url: str
    count: int = 1

def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "v" in query:
        return query["v"][0]
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/")
    raise HTTPException(400, "Invalid YouTube URL")

def get_video_snippet(video_id: str):
    res = youtube.videos().list(part="snippet,contentDetails,statistics", id=video_id).execute()
    items = res.get("items", [])
    if not items:
        raise HTTPException(404, "Video not found")
    return items[0]["snippet"]

def get_uploads_playlist_id(channel_id: str) -> str:
    res = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    items = res.get("items", [])
    if not items:
        raise HTTPException(404, "Channel not found")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

def get_all_uploads(playlist_id: str):
    videos = []
    token = None
    while True:
        res = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=token
        ).execute()

        videos.extend(res.get("items", []))
        token = res.get("nextPageToken")
        if not token:
            break

    return videos[::-1]  # oldest → newest

@app.post("/nextvideos")
def next_videos(data: VideoRequest):
    if data.count < 1 or data.count > 15:
        raise HTTPException(400, "Count must be between 1 and 15")

    current_video = extract_video_id(data.url)
    current_snippet = get_video_snippet(current_video)
    channel_name = current_snippet.get("channelTitle", "")
    channel_id = current_snippet.get("channelId")

    playlist_id = get_uploads_playlist_id(channel_id)
    uploads = get_all_uploads(playlist_id)

    results = []
    index = next(
        (i for i, item in enumerate(uploads) if item["contentDetails"]["videoId"] == current_video),
        None
    )

    if index is None:
        return {"message": "Video not found in uploads"}

    for j in range(1, data.count + 1):
        if index + j < len(uploads):
            vid = uploads[index + j]["contentDetails"]["videoId"]
            info = youtube.videos().list(part="snippet", id=vid).execute()
            items = info.get("items", [])
            if not items:
                continue

            s = items[0]["snippet"]
            thumb = s.get("thumbnails", {}).get("medium", {}).get("url") or \
                    s.get("thumbnails", {}).get("default", {}).get("url", "")

            results.append({
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": s.get("title", "No title"),
                "thumbnail": thumb
            })
        else:
            break

    return {
        "channel": channel_name,
        "videos": results
    }




