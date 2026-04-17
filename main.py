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

# Load API Key
load_dotenv()
API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    raise Exception("YOUTUBE_API_KEY not found in environment")

app = FastAPI(title="NextWatch API")

# Frontend setup
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

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

# YouTube API
youtube = build("youtube", "v3", developerKey=API_KEY)

# Request model
class VideoRequest(BaseModel):
    url: str
    count: int = 1
    direction: str = "next"   # "next" or "previous"

# Helpers
def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    if "v" in query:
        return query["v"][0]

    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/")

    raise HTTPException(status_code=400, detail="Invalid YouTube URL")

def get_video_snippet(video_id: str):
    res = youtube.videos().list(
        part="snippet",
        id=video_id
    ).execute()

    items = res.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="Video not found")

    return items[0]["snippet"]

def get_uploads_playlist_id(channel_id: str) -> str:
    res = youtube.channels().list(
        part="contentDetails",
        id=channel_id
    ).execute()

    items = res.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="Channel not found")

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

    # oldest → newest
    return videos[::-1]

# MAIN ENDPOINT (handles BOTH next + previous)
@app.post("/videos")
def get_videos(data: VideoRequest):

    if data.count < 1 or data.count > 15:
        raise HTTPException(status_code=400, detail="Count must be between 1 and 15")

    direction = data.direction.lower().strip()

    if direction not in ["next", "previous"]:
        raise HTTPException(status_code=400, detail="Direction must be 'next' or 'previous'")

    # Get current video info
    video_id = extract_video_id(data.url)
    snippet = get_video_snippet(video_id)

    channel_name = snippet.get("channelTitle", "")
    channel_id = snippet.get("channelId")

    # Get uploads
    playlist_id = get_uploads_playlist_id(channel_id)
    uploads = get_all_uploads(playlist_id)

    # Find current video index
    index = next(
        (i for i, item in enumerate(uploads)
         if item["contentDetails"]["videoId"] == video_id),
        None
    )

    if index is None:
        return {"channel": channel_name, "videos": []}

    results = []

    for i in range(1, data.count + 1):

        # KEY LOGIC (this is the feature)
        target_index = index + i if direction == "next" else index - i

        if 0 <= target_index < len(uploads):
            vid = uploads[target_index]["contentDetails"]["videoId"]

            info = youtube.videos().list(
                part="snippet",
                id=vid
            ).execute()

            items = info.get("items", [])
            if not items:
                continue

            s = items[0]["snippet"]

            thumb = (
                s.get("thumbnails", {}).get("medium", {}).get("url")
                or s.get("thumbnails", {}).get("default", {}).get("url", "")
            )

            results.append({
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": s.get("title", "No title"),
                "thumbnail": thumb
            })
        else:
            break

    return {
        "channel": channel_name,
        "direction": direction,
        "videos": results
    }