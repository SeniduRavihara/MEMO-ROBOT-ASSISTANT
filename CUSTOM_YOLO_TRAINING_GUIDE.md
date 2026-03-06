# Custom YOLOv4 Training Guide for Electronics Workbench

## Overview
Train YOLOv4 to detect your specific objects: soldering iron, multimeter, screwdrivers, tweezers, breadboard, resistors, etc.

## Step 1: Collect Images (200-500 images minimum)

### Option A: Using Your Robot Camera
```python
# Create image_collector.py to capture training images
import cv2
import os
from datetime import datetime

URL = "http://192.168.43.223"
cap = cv2.VideoCapture(URL + ":81/stream")

save_dir = "training_data/images"
os.makedirs(save_dir, exist_ok=True)

counter = 0
while True:
    ret, frame = cap.read()
    if ret:
        cv2.imshow('Capture - Press SPACE to save, ESC to quit', frame)
        
        key = cv2.waitKey(1)
        if key == 32:  # SPACE
            filename = f"{save_dir}/img_{counter:04d}.jpg"
            cv2.imwrite(filename, frame)
            print(f"Saved: {filename}")
            counter += 1
        elif key == 27:  # ESC
            break

cap.release()
cv2.destroyAllWindows()
```

**Tips:**
- Take photos from different angles
- Vary lighting conditions
- Include multiple objects in some images
- Move objects to different positions
- Capture 200-500 images minimum (more is better)

### Option B: Download Similar Images
- Search Google Images for "electronics workbench", "soldering iron", "multimeter"
- Use tools like `google-images-download` or manually download
- Aim for variety in backgrounds and lighting

## Step 2: Label Your Images

### Install LabelImg (Best annotation tool)
```bash
pip install labelImg
```

### Run LabelImg
```bash
labelImg training_data/images training_data/labels
```

**How to use:**
1. Click "Open Dir" → select your images folder
2. Click "Change Save Dir" → select labels folder
3. Press 'W' to draw bounding box around object
4. Type object name (e.g., "soldering_iron", "multimeter")
5. Press 'D' to go to next image
6. **Use YOLO format** (not PascalVOC)

### Your Custom Classes
Create `training_data/classes.txt`:
```
soldering_iron
multimeter
screwdriver
tweezers
breadboard
resistor
capacitor
wire
pliers
wire_stripper
flux
solder
oscilloscope
power_supply
```

## Step 3: Organize Dataset

```
training_data/
├── images/
│   ├── train/      # 80% of images
│   └── val/        # 20% of images
├── labels/
│   ├── train/      # Corresponding .txt files
│   └── val/
└── classes.txt
```

### Split Dataset Script
```python
# split_dataset.py
import os
import shutil
import random

images_dir = "training_data/images"
labels_dir = "training_data/labels"

# Get all images
images = [f for f in os.listdir(images_dir) if f.endswith('.jpg')]
random.shuffle(images)

# 80-20 split
split_idx = int(len(images) * 0.8)
train_images = images[:split_idx]
val_images = images[split_idx:]

# Create directories
for split in ['train', 'val']:
    os.makedirs(f"{images_dir}/{split}", exist_ok=True)
    os.makedirs(f"{labels_dir}/{split}", exist_ok=True)

# Move files
for img in train_images:
    shutil.move(f"{images_dir}/{img}", f"{images_dir}/train/{img}")
    label = img.replace('.jpg', '.txt')
    if os.path.exists(f"{labels_dir}/{label}"):
        shutil.move(f"{labels_dir}/{label}", f"{labels_dir}/train/{label}")

for img in val_images:
    shutil.move(f"{images_dir}/{img}", f"{images_dir}/val/{img}")
    label = img.replace('.jpg', '.txt')
    if os.path.exists(f"{labels_dir}/{label}"):
        shutil.move(f"{labels_dir}/{label}", f"{labels_dir}/val/{label}")

print(f"Train: {len(train_images)}, Val: {len(val_images)}")
```

## Step 4: Setup Training Environment

### Option A: Google Colab (Recommended - FREE GPU)

1. Go to [Google Colab](https://colab.research.google.com)
2. Create new notebook
3. Runtime → Change runtime type → GPU

```python
# Colab Notebook Code

# Clone Darknet
!git clone https://github.com/AlexeyAB/darknet
%cd darknet

# Compile with GPU support
!sed -i 's/OPENCV=0/OPENCV=1/' Makefile
!sed -i 's/GPU=0/GPU=1/' Makefile
!sed -i 's/CUDNN=0/CUDNN=1/' Makefile
!make

# Upload your training_data folder to Colab or Google Drive
from google.colab import drive
drive.mount('/content/drive')

# Copy data
!cp -r /content/drive/MyDrive/training_data /content/darknet/
```

### Option B: Local Training (if you have GPU)
```bash
git clone https://github.com/AlexeyAB/darknet
cd darknet

# Edit Makefile
# Set GPU=1, CUDNN=1, OPENCV=1

make
```

## Step 5: Configure Training Files

### Create `obj.data`
```
classes = 14
train = training_data/train.txt
valid = training_data/val.txt
names = training_data/classes.txt
backup = backup/
```

### Create train.txt and val.txt
```bash
# Generate file lists
ls training_data/images/train/*.jpg > training_data/train.txt
ls training_data/images/val/*.jpg > training_data/val.txt
```

### Modify yolov4-custom.cfg
```bash
# Download base config
wget https://raw.githubusercontent.com/AlexeyAB/darknet/master/cfg/yolov4-custom.cfg

# Edit these values:
# - batch=64
# - subdivisions=16 (or 32/64 if out of memory)
# - max_batches = (classes * 2000, minimum 6000)
#   For 14 classes: max_batches=28000
# - steps=80% and 90% of max_batches
#   steps=22400,25200
# - width=416, height=416
# - Search for [yolo] (appears 3 times)
#   - classes=14 (your number of classes)
#   - Search backwards for [convolutional] before each [yolo]
#   - filters=(classes + 5) * 3 = (14 + 5) * 3 = 57
```

### Download Pre-trained Weights
```bash
wget https://github.com/AlexeyAB/darknet/releases/download/darknet_yolo_v3_optimal/yolov4.conv.137
```

## Step 6: Train the Model

```bash
# Start training
./darknet detector train obj.data yolov4-custom.cfg yolov4.conv.137 -dont_show -map

# Training will create backups in backup/ folder
# Continue interrupted training:
./darknet detector train obj.data yolov4-custom.cfg backup/yolov4-custom_last.weights -dont_show -map
```

**Training time:**
- With GPU: 2-12 hours (depending on images)
- With CPU: Days (not recommended)

**Monitor progress:**
- mAP (mean Average Precision) should increase
- Loss should decrease
- Stop when avg loss < 0.5 and mAP plateaus

## Step 7: Test Your Model

```bash
# Test on image
./darknet detector test obj.data yolov4-custom.cfg backup/yolov4-custom_best.weights test_image.jpg

# Test on video
./darknet detector demo obj.data yolov4-custom.cfg backup/yolov4-custom_best.weights video.mp4
```

## Step 8: Use in Your Robot

Download your trained weights and config, then update main.py:

```python
# In main.py, change:
weights = "/path/to/yolov4-custom_best.weights"
config = "/path/to/yolov4-custom.cfg"
classes_file = "/path/to/classes.txt"
```

## Quick Start Timeline

1. **Day 1-2**: Collect & label 200-500 images (4-8 hours)
2. **Day 3**: Setup Colab, configure files (1-2 hours)
3. **Day 3-4**: Train model on Colab GPU (2-12 hours)
4. **Day 4**: Test and integrate (1-2 hours)

## Resources

- **Darknet GitHub**: https://github.com/AlexeyAB/darknet
- **YOLOv4 Paper**: https://arxiv.org/abs/2004.10934
- **Training Tutorial**: https://github.com/AlexeyAB/darknet#how-to-train-to-detect-your-custom-objects
- **LabelImg**: https://github.com/tzutalin/labelImg
- **Colab GPU**: Free 12-hour sessions

## Alternative: Faster Options

### Option 1: Roboflow (Easiest)
1. Upload images to [Roboflow](https://roboflow.com)
2. Label online (has smart labeling)
3. Train with one click
4. Export custom model

### Option 2: YOLOv5 (Easier to train)
```bash
git clone https://github.com/ultralytics/yolov5
cd yolov5
pip install -r requirements.txt

# Train (much simpler)
python train.py --data custom.yaml --weights yolov5s.pt --epochs 100
```

### Option 3: Transfer Learning Services
- **Google AutoML Vision**: Upload, label, train automatically
- **Microsoft Custom Vision**: Similar, easy to use
- Both cost money but very fast

## Pro Tips

1. **Start small**: Begin with 3-5 objects, add more later
2. **Quality > Quantity**: 300 good labels better than 1000 poor ones
3. **Augmentation**: Use rotation, brightness, flip during training
4. **Class balance**: Similar number of examples per class
5. **Background images**: Include some images with no objects
6. **Iterations**: First model won't be perfect, retrain with corrections

Would you like me to create the image collection script or help you set up Colab training?
