import argparse
import json
import yaml
import cv2
import numpy as np
import os
from typing import Dict, List, Any, Tuple


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Query and visualize video segments')
    parser.add_argument('--video', type=str, required=True, help='Path to the original video file')
    parser.add_argument('--config', type=str, required=True, help='Path to the original config file')
    parser.add_argument('--results', type=str, required=True, help='Path to the output.json file')
    parser.add_argument('--query', type=str, required=True, help='Path to the query.yaml file')
    parser.add_argument('--output-video', type=str, help='Path to save the output video (optional)')
    return parser.parse_args()


def load_files(config_path: str, results_path: str, query_path: str) -> Tuple[Dict, List[Dict], Dict]:
    """Load configuration, results and query files."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    with open(results_path, 'r') as f:
        results = json.load(f)
    
    with open(query_path, 'r') as f:
        query = yaml.safe_load(f)
    
    return config, results, query


def evaluate_condition(frame_data: Dict, condition: Dict) -> bool:
    """Evaluate if a frame matches a single condition."""
    query_text = condition['query'].lower().replace('?', '').replace(' ', '_')
    options = condition['options']
    
    if query_text in frame_data:
        return frame_data[query_text] in options
    return False


def evaluate_and_conditions(frame_data: Dict, conditions: List[Dict]) -> bool:
    """Evaluate if a frame matches all conditions (AND)."""
    return all(evaluate_condition(frame_data, condition) for condition in conditions)


def evaluate_or_conditions(frame_data: Dict, conditions: List[Dict]) -> bool:
    """Evaluate if a frame matches any condition (OR)."""
    return any(evaluate_condition(frame_data, condition) for condition in conditions)


def evaluate_complex_query(frame_data: Dict, query_group: Dict) -> bool:
    """Recursively evaluate complex nested queries."""
    if 'query' in query_group:
        return evaluate_condition(frame_data, query_group)
    
    if 'AND' in query_group:
        conditions = query_group['AND']
        results = []
        for condition in conditions:
            if 'query' in condition:
                results.append(evaluate_condition(frame_data, condition))
            else:
                results.append(evaluate_complex_query(frame_data, condition))
        return all(results)
    
    if 'OR' in query_group:
        conditions = query_group['OR']
        results = []
        for condition in conditions:
            if 'query' in condition:
                results.append(evaluate_condition(frame_data, condition))
            else:
                results.append(evaluate_complex_query(frame_data, condition))
        return any(results)
    
    return False


def find_matching_frames(results: List[Dict], query: Dict) -> List[Dict]:
    """Find frames that match the query conditions."""
    matching_frames = []
    
    for frame_data in results:
        # Skip frames with errors
        if 'error' in frame_data:
            continue
            
        for query_group in query['queries']:
            if evaluate_complex_query(frame_data, query_group):
                matching_frames.append(frame_data)
                break
    
    return matching_frames


def find_matching_segments(matching_frames: List[Dict], fps: float) -> List[Tuple[float, float]]:
    """Identify continuous segments from matching frames."""
    if not matching_frames:
        return []
    
    # Sort frames by timestamp
    sorted_frames = sorted(matching_frames, key=lambda x: x['timestamp'])
    
    # Group into segments with a tolerance of 2 * frame interval
    frame_interval = 1.0 / fps
    tolerance = 2 * frame_interval
    
    segments = []
    current_segment_start = sorted_frames[0]['timestamp']
    prev_timestamp = sorted_frames[0]['timestamp']
    
    for i in range(1, len(sorted_frames)):
        current_timestamp = sorted_frames[i]['timestamp']
        
        # If there's a gap larger than tolerance, end the segment and start a new one
        if current_timestamp - prev_timestamp > tolerance:
            segments.append((current_segment_start, prev_timestamp))
            current_segment_start = current_timestamp
        
        prev_timestamp = current_timestamp
    
    # Add the last segment
    segments.append((current_segment_start, prev_timestamp))
    
    return segments


def visualize_results(frame: np.ndarray, frame_data: Dict) -> np.ndarray:
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
    timestamp = frame_data.get('timestamp', 0)
    cv2.putText(vis_frame, f"Timestamp: {timestamp:.2f}s", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    
    # Add analysis results
    y_pos = h - 180
    for key, value in frame_data.items():
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
    
    return vis_frame


def get_closest_frame_data(timestamp: float, results: List[Dict]) -> Dict:
    """Find the closest frame data to a given timestamp."""
    closest_frame = None
    min_diff = float('inf')
    
    for frame_data in results:
        diff = abs(frame_data['timestamp'] - timestamp)
        if diff < min_diff:
            min_diff = diff
            closest_frame = frame_data
    
    return closest_frame


def play_matching_segments(video_path: str, segments: List[Tuple[float, float]], 
                          results: List[Dict], output_path: str = None):
    """Play only the segments that match the query."""
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    
    # Get video properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Setup output video writer if requested
    writer = None
    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    # For each segment
    for start_time, end_time in segments:
        # Convert time to frame number
        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps)
        
        # Set frame position to start_frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        
        current_frame_num = start_frame
        while current_frame_num <= end_frame and current_frame_num < total_frames:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Get current timestamp
            current_time = current_frame_num / fps
            
            # Find closest frame data
            frame_data = get_closest_frame_data(current_time, results)
            
            # Add visualization
            if frame_data:
                vis_frame = visualize_results(frame, frame_data)
                
                # Add segment info
                cv2.putText(vis_frame, f"Segment: {start_time:.2f}s - {end_time:.2f}s", 
                            (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                
                # Display
                cv2.imshow("Query Results", vis_frame)
                
                # Write to output video if requested
                if writer:
                    writer.write(vis_frame)
                
                # Wait for key press
                key = cv2.waitKey(int(1000/fps)) & 0xFF
                if key == 27:  # ESC key
                    break
            
            current_frame_num += 1
        
        if cv2.waitKey(0) & 0xFF == 27:  # ESC key
            break
    
    # Release resources
    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()


def main():
    args = parse_args()
    
    # Load files
    config, results, query = load_files(args.config, args.results, args.query)
    
    # Find matching frames
    matching_frames = find_matching_frames(results, query)
    
    if not matching_frames:
        print("No frames matching the query were found.")
        return
    
    # Get fps from config
    fps = config.get('fps', 1.0)
    
    # Identify continuous segments
    segments = find_matching_segments(matching_frames, fps)
    
    # Print matching segments
    print(f"Found {len(segments)} matching segments:")
    for start, end in segments:
        print(f"  {start:.2f}s - {end:.2f}s")
    
    # Play the matching segments
    play_matching_segments(args.video, segments, results, args.output_video)
    
    if args.output_video:
        print(f"Output video saved to: {args.output_video}")


if __name__ == "__main__":
    main()