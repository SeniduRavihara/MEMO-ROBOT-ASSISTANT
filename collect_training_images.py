import cv2
import os
from datetime import datetime

# Configuration
URL = "http://192.168.43.223"
SAVE_DIR = "training_data/images"

# Create directory
os.makedirs(SAVE_DIR, exist_ok=True)

# Initialize camera
cap = cv2.VideoCapture(URL + ":81/stream")

counter = len([f for f in os.listdir(SAVE_DIR) if f.endswith('.jpg')])
print(f"Starting from image #{counter}")
print("\nControls:")
print("  SPACE - Save current frame")
print("  ESC   - Quit")
print("\nTips for good training data:")
print("  - Take 200-500 images minimum")
print("  - Vary angles and lighting")
print("  - Include multiple objects per image")
print("  - Move objects around")
print("  - Take some images with no target objects (background)")
print("\n")

saved_count = 0

while True:
    ret, frame = cap.read()
    
    if ret:
        # Display instructions on frame
        display_frame = frame.copy()
        cv2.putText(display_frame, f"Images collected: {saved_count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(display_frame, "Press SPACE to save, ESC to quit", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        cv2.imshow('Training Image Collector', display_frame)
        
        key = cv2.waitKey(1)
        
        if key == 32:  # SPACE
            filename = f"{SAVE_DIR}/img_{counter:04d}.jpg"
            cv2.imwrite(filename, frame)
            print(f"✓ Saved: {filename}")
            counter += 1
            saved_count += 1
            
        elif key == 27:  # ESC
            print(f"\n✓ Collection complete! {saved_count} new images saved.")
            print(f"Total images: {counter}")
            print(f"\nNext steps:")
            print(f"1. Install labelImg: pip install labelImg")
            print(f"2. Run: labelImg {SAVE_DIR}")
            print(f"3. Draw boxes around your objects")
            print(f"4. Save in YOLO format")
            break
    else:
        print("Error reading frame. Check camera connection.")
        break

cap.release()
cv2.destroyAllWindows()
