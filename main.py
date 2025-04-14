import os
import base64
import argparse
import yaml
import cv2
import numpy as np
from PIL import Image
from typing import Dict, List, Any, Union, Optional
import io
from pydantic import BaseModel, Field, create_model
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import chain
from langchain.chains import TransformChain
import time


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Video perception analysis')
    parser.add_argument('--video', type=str, required=True, help='Path to the video file')
    parser.add_argument('--config', type=str, required=True, help='Path to the YAML config file')
    parser.add_argument('--output', type=str, default='results/output.json', help='Path to output JSON file')
    parser.add_argument('--display', action='store_true', help='Display frames with analysis results')
    parser.add_argument('--save-frames', action='store_true', help='Save frames with analysis results')
    return parser.parse_args()


def load_config(config_path: str) -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config


def create_frame_model(config: Dict) -> BaseModel:
    """Create a Pydantic model dynamically based on the queries in the config."""
    field_definitions = {}
    
    for query_item in config['queries']:
        query = query_item['query']
        options = query_item.get('options', None)
        
        # Create a field for each query
        field_name = query.lower().replace('?', '').replace(' ', '_')
        
        # If options are provided, make the field a specific enum type
        if options:
            field_definitions[field_name] = (
                str, 
                Field(description=f"{query} Choose from: {', '.join(options)}")
            )
        else:
            field_definitions[field_name] = (
                str, 
                Field(description=query)
            )
    
    # Add timestamp field
    field_definitions['timestamp'] = (
        float, 
        Field(description="Timestamp of the frame in seconds")
    )
    
    # Create and return the model
    FrameAnalysis = create_model(
        'FrameAnalysis',
        **field_definitions
    )
    
    return FrameAnalysis


def encode_image(image_array: np.ndarray) -> str:
    """Encode image array to base64 string."""
    # Convert array to PIL Image
    image = Image.fromarray(cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB))
    
    # Save to bytes buffer
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    buffer.seek(0)
    
    # Encode as base64
    image_bytes = buffer.getvalue()
    return base64.b64encode(image_bytes).decode('utf-8')


def load_frame(inputs: dict) -> dict:
    """Load frame and encode it as base64."""
    frame = inputs["frame"]
    image_base64 = encode_image(frame)
    return {"image": image_base64}


def create_prompt(config: Dict) -> str:
    """Create a prompt based on the queries in the config."""
    prompt = "Analyze this video frame and provide the following information:\n\n"
    
    for query_item in config['queries']:
        query = query_item['query']
        options = query_item.get('options', None)
        
        if options:
            prompt += f"- {query} Choose from: {', '.join(options)}\n"
        else:
            prompt += f"- {query}\n"
    
    return prompt


@chain
def image_model(inputs: dict) -> str | List[str] | Dict:
    """Invoke model with image and prompt."""
    model = ChatOpenAI(temperature=0.3, model="gpt-4o-mini", max_tokens=1024)
    msg = model.invoke(
        [HumanMessage(
            content=[
                {"type": "text", "text": inputs["prompt"]},
                {"type": "text", "text": inputs["parser"].get_format_instructions()},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{inputs['image']}"}}
            ]
        )]
    )
    return msg.content


def extract_frames(video_path: str, fps: float) -> List[Dict[str, Any]]:
    """Extract frames from video at the specified FPS."""
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_step = int(video_fps / fps)
    
    frames = []
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        
        if not ret:
            break
        
        if frame_count % frame_step == 0:
            timestamp = frame_count / video_fps
            frames.append({"frame": frame, "timestamp": timestamp})
        
        frame_count += 1
    
    cap.release()
    return frames


def visualize_results(frame: np.ndarray, analysis: dict) -> np.ndarray:
    """Overlay analysis results on the frame."""
    # Create a copy of the frame
    vis_frame = frame.copy()
    
    # Get frame dimensions
    h, w = vis_frame.shape[:2]
    
    # Add a semi-transparent overlay at the bottom for text
    overlay = vis_frame.copy()
    cv2.rectangle(overlay, (0, h - 200), (w, h), (0, 0, 0), -1)
    vis_frame = cv2.addWeighted(overlay, 0.6, vis_frame, 0.4, 0)
    
    # Add timestamp at the top
    timestamp = analysis.get('timestamp', 0)
    cv2.putText(vis_frame, f"Timestamp: {timestamp:.2f}s", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    
    # Add analysis results
    y_pos = h - 180
    for key, value in analysis.items():
        if key != 'timestamp' and key != 'error':
            text = f"{key.replace('_', ' ').title()}: {value}"
            # Wrap text if too long
            if len(text) > 60:
                wrapped_text = [text[i:i+60] for i in range(0, len(text), 60)]
                for line in wrapped_text:
                    cv2.putText(vis_frame, line, (10, y_pos), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                    y_pos += 25
            else:
                cv2.putText(vis_frame, text, (10, y_pos), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                y_pos += 25
    
    # Add error message if present
    if 'error' in analysis:
        cv2.putText(vis_frame, f"Error: {analysis['error']}", (10, y_pos), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)
    
    return vis_frame


def create_tile_image(frames: List[Dict[str, Any]], tile_shape: List[int]) -> np.ndarray:
    """Create a tiled image from multiple frames."""
    if not frames:
        return None
    
    # Get dimensions from the first frame
    frame_height, frame_width = frames[0]["frame"].shape[:2]
    
    # Calculate the dimensions of the tiled image
    rows, cols = tile_shape
    tile_height = rows * frame_height
    tile_width = cols * frame_width
    
    # Create an empty canvas
    tile_image = np.zeros((tile_height, tile_width, 3), dtype=np.uint8)
    
    # Fill the canvas with frames
    for i, frame_data in enumerate(frames[:rows*cols]):
        row = i // cols
        col = i % cols
        
        y_start = row * frame_height
        y_end = y_start + frame_height
        x_start = col * frame_width
        x_end = x_start + frame_width
        
        tile_image[y_start:y_end, x_start:x_end] = frame_data["frame"]
    
    return tile_image


def main():
    args = parse_args()
    config = load_config(args.config)
    
    # Create the Pydantic model based on config
    FrameAnalysis = create_frame_model(config)
    
    # Create parser
    parser = JsonOutputParser(pydantic_object=FrameAnalysis)
    
    # Extract frames from video
    frames = extract_frames(args.video, config.get('fps', 1.0))
    
    # Set up the vision chain
    load_frame_chain = TransformChain(
        input_variables=["frame"],
        output_variables=["image"],
        transform=load_frame
    )
    
    # Create the prompt based on config
    prompt = create_prompt(config)
    
    # Process each frame
    results = []
    
    # Create output directory for frames if needed
    if args.save_frames:
        frames_dir = os.path.join(os.path.dirname(args.output), 'frames')
        if not os.path.exists(frames_dir):
            os.makedirs(frames_dir)
    
    for i, frame_data in enumerate(frames):
        # Prepare inputs
        inputs = {
            'frame': frame_data['frame'],
            'timestamp': frame_data['timestamp'],
            'prompt': prompt,
            'parser': parser
        }
        
        # Process the frame
        vision_chain = load_frame_chain | image_model
        
        try:
            output = vision_chain.invoke(inputs)
            # Parse the output
            parsed_output = parser.parse(output)
            # Make sure timestamp is included
            if 'timestamp' not in parsed_output or parsed_output['timestamp'] != frame_data['timestamp']:
                parsed_output['timestamp'] = frame_data['timestamp']
            
            results.append(parsed_output)
            print(f"Processed frame at timestamp: {frame_data['timestamp']:.2f}s")
            
            # Visualize the results if display is enabled
            if args.display or args.save_frames:
                vis_frame = visualize_results(frame_data['frame'], parsed_output)
                
                if args.display:
                    cv2.imshow("Video Analysis", vis_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27:  # ESC key
                        break
                
                if args.save_frames:
                    frame_path = os.path.join(frames_dir, f"frame_{i:04d}_{frame_data['timestamp']:.2f}s.jpg")
                    cv2.imwrite(frame_path, vis_frame)
            
        except Exception as e:
            print(f"Error processing frame at {frame_data['timestamp']:.2f}s: {e}")
            # Add a minimal error entry
            error_output = {
                'timestamp': frame_data['timestamp'],
                'error': str(e)
            }
            results.append(error_output)
            
            # Visualize the error frame
            if args.display or args.save_frames:
                vis_frame = visualize_results(frame_data['frame'], error_output)
                
                if args.display:
                    cv2.imshow("Video Analysis", vis_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27:  # ESC key
                        break
                
                if args.save_frames:
                    frame_path = os.path.join(frames_dir, f"frame_{i:04d}_{frame_data['timestamp']:.2f}s_error.jpg")
                    cv2.imwrite(frame_path, vis_frame)
    
    # Close any open windows
    if args.display:
        cv2.destroyAllWindows()
    
    # Create sample tiled frames if specified
    if 'tile_frames' in config and len(frames) >= 2:
        tile_shape = config['tile_frames']
        sample_frames = frames[:tile_shape[0] * tile_shape[1]]
        tile_image = create_tile_image(sample_frames, tile_shape)
        
        # Save the tiled image
        output_dir = os.path.dirname(args.output)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        tile_path = os.path.join(output_dir, 'frame_tiles.jpg')
        cv2.imwrite(tile_path, tile_image)
        print(f"Saved tiled frames to {tile_path}")
    
    # Save results to JSON
    import json
    output_dir = os.path.dirname(args.output)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()