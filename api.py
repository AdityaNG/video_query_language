import os
import asyncio
import shutil
import tempfile
import uuid
from typing import Dict, List, Optional, Any
import yaml
import json
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Video Query Language API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create directories if they don't exist
UPLOAD_DIR = Path("uploads")
RESULTS_DIR = Path("results")
FRAMES_DIR = RESULTS_DIR / "frames"

for dir_path in [UPLOAD_DIR, RESULTS_DIR, FRAMES_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Models for request validation
class QueryOption(BaseModel):
    query: str
    options: List[str]

class ConfigData(BaseModel):
    queries: List[QueryOption]
    context: str = "Answer the following"
    fps: float = 1.0
    frame_stride: int = 1
    max_resolution: List[int] = [640, 360]
    tile_frames: Optional[List[int]] = [3, 3]

class ProcessStatus(BaseModel):
    id: str
    status: str
    message: Optional[str] = None
    progress: Optional[float] = None
    results_url: Optional[str] = None
    frames_dir: Optional[str] = None
    video_url: Optional[str] = None

# Dictionary to store process status
process_statuses = {}

@app.post("/api/upload", response_model=ProcessStatus)
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    config_data: str = Form(...),
):
    """
    Upload a video file and configuration data to process
    """
    try:
        # Generate unique ID for this process
        process_id = str(uuid.uuid4())
        
        # Create process directory
        process_dir = UPLOAD_DIR / process_id
        process_dir.mkdir(parents=True, exist_ok=True)
        
        # Save the video file
        video_path = process_dir / video.filename
        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
        
        # Parse and save config
        config = json.loads(config_data)
        config_path = process_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        
        # Set initial status
        process_statuses[process_id] = {
            "id": process_id,
            "status": "uploading",
            "message": "Files uploaded successfully. Processing will start soon.",
            "progress": 0.0
        }
        
        # Start processing in background
        background_tasks.add_task(
            process_video,
            process_id,
            str(video_path), 
            str(config_path)
        )
        
        return ProcessStatus(**process_statuses[process_id])
    
    except Exception as e:
        logger.error(f"Error in upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_video(process_id: str, video_path: str, config_path: str):
    """
    Process the video using the main.py script
    """
    try:
        # Update status
        process_statuses[process_id].update({
            "status": "processing",
            "message": "Video processing started",
            "progress": 10.0
        })
        
        # Create output directory
        output_dir = RESULTS_DIR / process_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "output.json"
        
        # Run the main.py script
        cmd = [
            "python", "main.py", 
            "--video", video_path, 
            "--config", config_path, 
            "--output", str(output_path),
            "--save-frames"
        ]
        
        logger.info(f"Running command: {' '.join(cmd)}")
        
        # Run the process and capture output
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Wait for the process to complete
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            logger.error(f"Process failed: {error_msg}")
            process_statuses[process_id].update({
                "status": "failed",
                "message": f"Processing failed: {error_msg}",
                "progress": 100.0
            })
            return
        
        # Move frames to results directory
        source_frames_dir = Path(output_path).parent / "frames"
        if source_frames_dir.exists():
            dest_frames_dir = FRAMES_DIR / process_id
            dest_frames_dir.mkdir(parents=True, exist_ok=True)
            
            for frame_file in source_frames_dir.glob("*.jpg"):
                shutil.copy(frame_file, dest_frames_dir / frame_file.name)
        
        # Update status to completed
        process_statuses[process_id].update({
            "status": "completed",
            "message": "Video processing completed successfully",
            "progress": 100.0,
            "results_url": f"/api/results/{process_id}",
            "frames_dir": f"/api/frames/{process_id}",
            "video_url": f"/api/video/{process_id}"
        })
        
        logger.info(f"Process {process_id} completed successfully")
    
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}")
        process_statuses[process_id].update({
            "status": "failed",
            "message": f"Processing failed: {str(e)}",
            "progress": 100.0
        })

@app.get("/api/status/{process_id}", response_model=ProcessStatus)
async def get_process_status(process_id: str):
    """
    Get the status of a processing job
    """
    if process_id not in process_statuses:
        raise HTTPException(status_code=404, detail="Process not found")
    
    return ProcessStatus(**process_statuses[process_id])

@app.get("/api/results/{process_id}")
async def get_results(process_id: str):
    """
    Get the results JSON for a completed process
    """
    results_path = RESULTS_DIR / process_id / "output.json"
    if not results_path.exists():
        raise HTTPException(status_code=404, detail="Results not found")
    
    with open(results_path, "r") as f:
        results = json.load(f)
    
    return results

@app.get("/api/frames/{process_id}")
async def list_frames(process_id: str):
    """
    List all frame images for a process
    """
    frames_dir = FRAMES_DIR / process_id
    if not frames_dir.exists():
        raise HTTPException(status_code=404, detail="Frames not found")
    
    frames = []
    for frame_file in sorted(frames_dir.glob("*.jpg")):
        frames.append({
            "name": frame_file.name,
            "url": f"/api/frames/{process_id}/{frame_file.name}"
        })
    
    return frames

@app.get("/api/frames/{process_id}/{frame_name}")
async def get_frame(process_id: str, frame_name: str):
    """
    Get a specific frame image
    """
    frame_path = FRAMES_DIR / process_id / frame_name
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="Frame not found")
    
    return FileResponse(frame_path)

@app.get("/api/video/{process_id}")
async def get_video(process_id: str):
    """
    Get the original video file
    """
    # Find the video file in the upload directory
    video_files = list((UPLOAD_DIR / process_id).glob("*.mp4"))
    video_files.extend(list((UPLOAD_DIR / process_id).glob("*.avi")))
    video_files.extend(list((UPLOAD_DIR / process_id).glob("*.mov")))
    
    if not video_files:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return FileResponse(video_files[0])

@app.post("/api/query")
async def query_video(
    background_tasks: BackgroundTasks,
    process_id: str = Form(...),
    query_data: str = Form(...)
):
    """
    Query the processed video results with a specific query
    """
    try:
        # Generate a new process ID for this query
        query_id = str(uuid.uuid4())
        
        # Get the original video path
        video_files = list((UPLOAD_DIR / process_id).glob("*.mp4"))
        video_files.extend(list((UPLOAD_DIR / process_id).glob("*.avi")))
        video_files.extend(list((UPLOAD_DIR / process_id).glob("*.mov")))
        
        if not video_files:
            raise HTTPException(status_code=404, detail="Original video not found")
        
        video_path = video_files[0]
        
        # Get the config path
        config_path = UPLOAD_DIR / process_id / "config.yaml"
        if not config_path.exists():
            raise HTTPException(status_code=404, detail="Config file not found")
        
        # Get the results path
        results_path = RESULTS_DIR / process_id / "output.json"
        if not results_path.exists():
            raise HTTPException(status_code=404, detail="Results file not found")
        
        # Save the query data
        query = json.loads(query_data)
        query_dir = RESULTS_DIR / "queries" / query_id
        query_dir.mkdir(parents=True, exist_ok=True)
        
        query_path = query_dir / "query.yaml"
        with open(query_path, "w") as f:
            yaml.dump(query, f)
        
        # Set initial status
        process_statuses[query_id] = {
            "id": query_id,
            "status": "querying",
            "message": "Query processing started",
            "progress": 0.0
        }
        
        # Start querying in background
        background_tasks.add_task(
            run_query,
            query_id,
            str(video_path),
            str(config_path),
            str(results_path),
            str(query_path)
        )
        
        return ProcessStatus(**process_statuses[query_id])
    
    except Exception as e:
        logger.error(f"Error in query: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def run_query(
    query_id: str, 
    video_path: str, 
    config_path: str, 
    results_path: str, 
    query_path: str
):
    """
    Run the query.py script to query the video
    """
    try:
        # Update status
        process_statuses[query_id].update({
            "status": "querying",
            "message": "Query processing started",
            "progress": 10.0
        })
        
        # Output video path
        output_dir = RESULTS_DIR / "queries" / query_id
        output_video = output_dir / "output_query.mp4"
        
        # Run the query.py script
        cmd = [
            "python", "query.py",
            "--video", video_path,
            "--config", config_path,
            "--results", results_path,
            "--query", query_path,
            "--output-video", str(output_video)
        ]
        
        logger.info(f"Running query command: {' '.join(cmd)}")
        
        # Run the process and capture output
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Wait for the process to complete
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            logger.error(f"Query process failed: {error_msg}")
            process_statuses[query_id].update({
                "status": "failed",
                "message": f"Query processing failed: {error_msg}",
                "progress": 100.0
            })
            return
        
        # Update status to completed
        process_statuses[query_id].update({
            "status": "completed",
            "message": "Query processing completed successfully",
            "progress": 100.0,
            "video_url": f"/api/query-video/{query_id}"
        })
        
        logger.info(f"Query {query_id} completed successfully")
    
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        process_statuses[query_id].update({
            "status": "failed",
            "message": f"Query processing failed: {str(e)}",
            "progress": 100.0
        })

@app.get("/api/query-video/{query_id}")
async def get_query_video(query_id: str):
    """
    Get the query result video
    """
    video_path = RESULTS_DIR / "queries" / query_id / "output_query.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Query video not found")
    
    return FileResponse(video_path)

# Mount static files for the frontend
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
