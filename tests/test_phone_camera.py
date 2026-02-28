"""
Test: Phone Camera Stream

Supports two modes:
  1. Continuity Camera (iPhone + macOS) — zero setup, iPhone as native webcam
  2. IP camera app (any phone) — HTTP stream via IP Webcam / IP Camera Lite

Usage:
  # Auto-detect cameras (lists all available, including iPhone via Continuity Camera)
  uv run python tests/test_phone_camera.py

  # Use a specific camera index (e.g. 1 for iPhone Continuity Camera)
  uv run python tests/test_phone_camera.py --index 1

  # Use IP camera app URL
  uv run python tests/test_phone_camera.py --url http://192.168.1.15:8080/video

Controls:
  - Press 'q' in the preview window to quit
  - Press 'n' to cycle to next camera
"""

import os
import sys
import time

import cv2

FRAMES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frames")


def list_cameras(max_index=5):
    """Probe camera indices to find available cameras."""
    available = []
    print("[SCAN] Scanning for cameras...")
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                h, w = frame.shape[:2]
                # Try to get backend name
                backend = cap.getBackendName()
                available.append({"index": i, "width": w, "height": h, "backend": backend})
                print(f"  [{i}] {w}x{h} ({backend})")
            cap.release()
        else:
            cap.release()

    if not available:
        print("  No cameras found!")
    return available


def stream_camera(source, label="Camera"):
    """Stream from a camera source (index or URL) with preview window."""
    print(f"\n[CAMERA] Opening: {source}")

    if isinstance(source, int):
        cap = cv2.VideoCapture(source)
    else:
        cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"ERROR: Could not open camera source: {source}")
        return False

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[CAMERA] Opened! Resolution: {w}x{h}")
    print("[CAMERA] Press 'q' to quit, 'n' for next camera\n")

    os.makedirs(FRAMES_DIR, exist_ok=True)
    frame_count = 0
    last_save = 0.0
    fps_count = 0
    fps_time = time.monotonic()

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[CAMERA] Failed to grab frame, retrying...")
            time.sleep(0.1)
            continue

        frame_count += 1
        fps_count += 1

        now = time.monotonic()
        if now - fps_time >= 2.0:
            fps = fps_count / (now - fps_time)
            print(f"  {fps:.1f} FPS | Frame {frame_count}")
            fps_count = 0
            fps_time = now

        # Save a frame every 5 seconds
        if now - last_save >= 5.0:
            path = os.path.join(FRAMES_DIR, f"frame_{frame_count:04d}.jpg")
            cv2.imwrite(path, frame)
            print(f"  [SAVED] {path}")
            last_save = now

        display = cv2.resize(frame, (640, 480))
        cv2.imshow(f"{label} (q=quit, n=next)", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            cap.release()
            cv2.destroyAllWindows()
            return None  # quit entirely
        if key == ord("n"):
            cap.release()
            cv2.destroyAllWindows()
            return True  # next camera

    cap.release()
    cv2.destroyAllWindows()
    return None


def main():
    print("=" * 60)
    print("  PHONE CAMERA STREAM TEST")
    print("=" * 60)
    print()

    # Parse args — default to index 1 (iPhone Continuity Camera)
    source = 1
    if "--url" in sys.argv:
        idx = sys.argv.index("--url")
        if idx + 1 < len(sys.argv):
            source = sys.argv[idx + 1]
    elif "--index" in sys.argv:
        idx = sys.argv.index("--index")
        if idx + 1 < len(sys.argv):
            source = int(sys.argv[idx + 1])
    elif "--scan" in sys.argv:
        source = None  # scan mode

    if source is not None:
        stream_camera(source, f"Camera {source}")
        print(f"\n[DONE]")
        return

    # Scan mode (--scan) — list all cameras and cycle through
    print("  iPhone users: your phone may appear as a Continuity Camera")
    print("  (same Apple ID, WiFi + Bluetooth on, iPhone nearby)\n")

    cameras = list_cameras()

    if not cameras:
        print("\nNo cameras detected. Options:")
        print("  - iPhone: ensure same Apple ID, WiFi & Bluetooth on, phone nearby")
        print("  - IP cam app: use --url http://phone-ip:port/video")
        return

    print(f"\nFound {len(cameras)} camera(s). Press 'n' to cycle, 'q' to quit.\n")

    # Cycle through cameras
    cam_idx = 0
    while cam_idx < len(cameras):
        cam = cameras[cam_idx]
        result = stream_camera(
            cam["index"],
            f"Camera [{cam['index']}] {cam['width']}x{cam['height']}"
        )
        if result is None:
            break  # user pressed q
        cam_idx = (cam_idx + 1) % len(cameras)

    print("\n[DONE]")


if __name__ == "__main__":
    main()
