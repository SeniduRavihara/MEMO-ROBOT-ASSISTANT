import os
import queue
import threading
import time

import cv2
import numpy as np
import requests

# Suppress FFmpeg warnings
os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
cv2.setLogLevel(0)


class VideoCapture:

    def __init__(self, name):
        self.cap = cv2.VideoCapture(name)
        self.q = Queue.Queue()
        t = threading.Thread(target=self._reader)
        t.daemon = True
        t.start()

    def _reader(self):
        while True:
            ret, frame = self.cap.read()
            if not ret:
                break
            if not self.q.empty():
                try:
                    self.q.get_nowait()
                except Queue.Empty:
                    pass
            self.q.put(frame)

    def read(self):
        return self.q.get()


URL = "http://192.168.43.223"
cap = cv2.VideoCapture(URL + ":81/stream")

# Load YOLO model
model_path = os.path.expanduser("~/.cvlib/object_detection/yolo/yolov3")
weights = os.path.join(model_path, "yolov4-tiny.weights")
config = os.path.join(model_path, "yolov4-tiny.cfg")
classes_file = os.path.join(model_path, "yolov3_classes.txt")

# Load class names
with open(classes_file, 'r') as f:
    classes = [line.strip() for line in f.readlines()]

# Load YOLO network
net = cv2.dnn.readNet(weights, config)
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

layer_names = net.getLayerNames()
output_layers = [layer_names[i - 1] for i in net.getUnconnectedOutLayers()]


def detect_objects(frame, confidence_threshold=0.5, nms_threshold=0.4):
    height, width = frame.shape[:2]

    # Create blob from image
    blob = cv2.dnn.blobFromImage(
        frame, 1/255.0, (416, 416), swapRB=True, crop=False)
    net.setInput(blob)
    outputs = net.forward(output_layers)

    # Process detections
    boxes = []
    confidences = []
    class_ids = []

    for output in outputs:
        for detection in output:
            scores = detection[5:]
            class_id = np.argmax(scores)
            confidence = scores[class_id]

            if confidence > confidence_threshold:
                # Scale bbox coordinates back to original image
                center_x = int(detection[0] * width)
                center_y = int(detection[1] * height)
                w = int(detection[2] * width)
                h = int(detection[3] * height)

                # Rectangle coordinates
                x = int(center_x - w / 2)
                y = int(center_y - h / 2)

                boxes.append([x, y, w, h])
                confidences.append(float(confidence))
                class_ids.append(class_id)

    # Apply non-maximum suppression
    indices = cv2.dnn.NMSBoxes(
        boxes, confidences, confidence_threshold, nms_threshold)

    # Draw boxes
    if len(indices) > 0:
        for i in indices.flatten():
            x, y, w, h = boxes[i]
            label = f"{classes[class_ids[i]]}: {confidences[i]:.2f}"
            color = (0, 255, 0)

            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, label, (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    return frame


if __name__ == '__main__':
    requests.get(URL + "/control?var=framesize&val={}".format(8))

    while True:

        if cap.isOpened():
            ret, frame = cap.read()

            if ret and frame is not None:
                # Ensure frame has valid dimensions
                h, w = frame.shape[:2]
                if h > 0 and w > 0:
                    # Resize to even dimensions if needed
                    if h % 2 != 0 or w % 2 != 0:
                        h = h if h % 2 == 0 else h - 1
                        w = w if w % 2 == 0 else w - 1
                        frame = cv2.resize(frame, (w, h))

                    # Detect objects
                    frame_with_detections = detect_objects(frame.copy())
                    cv2.imshow('Output', frame_with_detections)

            key = cv2.waitKey(3)

            if key == 27:
                break

    cv2.destroyAllWindows()
    cap.release()
