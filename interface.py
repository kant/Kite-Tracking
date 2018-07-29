import cv2
import sys
import os
import imageio
import glob
import copy
import time
import numpy as np
import threading
import signal

from MLP import MLP_Detection_MP
from video import Video
from matched_filters import MatchedFilter
from utils import * 
from config import *
from bs import BS
from CNN_Detection import CNN_Detection, CNN_Verify

class Interface:
    def __init__(self, init_bbox=None):
        # Set up tracker.
        self.tracker = creat_tracker(tracker_type)
        # Set up Matched Filter
        self.MF = MatchedFilter(KERNEL_PATH)
        # Initialize variables
        self.prev_angle = None
        self.init_bbox = None
        self.frame_num = -1
        self.fps = []
        self.cnn_pred = None
        # Create handler when press Ctrl + C
        # signal.signal(signal.SIGINT, signal_handler)

    def init_tracker(self, frame, init_bbox=None):
        """
        Initialize tracker given bbox and first frame

        Params: 
            frame: initial list of frames
            init_bbox: bounding box
        Return:
            ret: if initialization is successful (boolean)
        """
        # Use MLP find init_bbox if init_bbox is none
        if init_bbox is None: 
            init_bbox = CNN_Detection(frame)
            # Stop if both methods failed
            if init_bbox is None:
                # raise ValueError("Initial Tracking Failed!!!")
                print("Initial Tracking Failed!!!")
                return None

        print("init_bbox: ", init_bbox)
        self.init_bbox = copy.copy(init_bbox)

        # Initialize tracker with first frame and bounding box
        del self.tracker # release the object space
        self.tracker = creat_tracker(tracker_type)
        self.tracker.init(frame, init_bbox)
        return init_bbox

    def update(self, frame, verbose=False):
        """
        Compute bbox and angle given current frame

        Params:
            frame: current color image 
        Return:
            ret: if updating is successful (boolean)
            bbox: bounding bbox
            angle: float value
            center_loc: the center of target [x, y]
        """
        # Start timer
        timer = cv2.getTickCount()
        t_start = time.time()

        # Read a new frame
        self.frame_num += 1
        angle = None
        frame_original = frame.copy() # make a copy for result saving
        frame_tmp = frame.copy() # make a copy for result saving
 
        # Update tracker
        ok, bbox = self.tracker.update(frame)

        # bbox limitation (fixed w and h)
        if ok and (tracker_type == "KCF" or bbox[2] * bbox[3] <= 0):
            bbox = list(bbox)
            bbox[2:] = [self.init_bbox[2], self.init_bbox[3]]
            bbox = tuple(bbox)
        if verbose:
            print ("tracking: ", time.time() - t_start)

        if ok:
            # Crop patch and analysis using histogram
            t_start = time.time()
            ok = CNN_Verify(frame, bbox)
            if verbose:
                print ("post tracking: ", time.time() - t_start)

        # # Use decision buffer to make final decision.
        # ok = pushBuffer(ok)
 
        # Draw bounding box
        if not ok:
            # Tracking failure
            t_start = time.time()
            bbox = self.init_tracker(frame)
            if bbox is None:
                if verbose:
                    print("   !!! -> Tracking Failed! Skip current frame...")
                return False, None, None, None, None

            # Reinitialize tracker
            ok = True
            if verbose:
                print ("MLP: ", time.time() - t_start )
 
        # Apply matched filter to compute the angle of target
        t_start = time.time()
        angle = self.MF.getTargetAngle(frame_original.copy(), 
                                       copy.copy(bbox), self.prev_angle)
        center_loc = (np.array(bbox[:2]) + np.array(bbox[2:]) / 2).astype(int)
        if angle is not None:
            self.prev_angle = angle
        else:
            return False, None, None, None, None
        self.cnn_pred = self.MF.cnn_pred

        if verbose:
            print ("Angle: ", time.time() - t_start )

        # Calculate Frames per second (FPS)
        fps = cv2.getTickFrequency() / (cv2.getTickCount() - timer);
        self.fps.append(fps)
        if len(self.fps) > 5:
            self.fps = self.fps[-5:]

        if verbose:
            # Print out current info.
            print("image {:5d}  |  bbox: {:4d} {:4d} {:3d} {:3d}  |  FPS: {:2d}  |  anlge: {}".format(
                                                                                        self.frame_num, 
                                                                                        int(bbox[0]), int(bbox[1]), 
                                                                                        int(bbox[2]), int(bbox[3]),
                                                                                        int(np.mean(self.fps)),
                                                                                        angle)) 
        return ok, bbox, angle, center_loc, np.mean(self.fps)

# This is an example for using Interface
if __name__ == "__main__":
    # Read video
    files = glob.glob(IMAGE_PATH)
    assert len(files) > 0

    _, path_and_file = os.path.splitdrive(files[0])
    path, file = os.path.split(path_and_file)

    # Record variables
    image_name = path.split('/')[-1] + ".mp4"
    video_writer = imageio.get_writer(image_name, fps=RECORD_FPS)

    video = Video(files, FILE_FORMAT, START_FRAME)
    ok, frame = video.read()
    if not ok:
        print('Cannot read video file')
        sys.exit()

    tracker = Interface()

    ok, frame = video.read()
    tracker.init_tracker(frame)

    while True:
        # Read one frame
        ok, frame = video.read()
        if not ok:
            print('Cannot read video file')
            break
        frame_original = frame.copy()

        # Obtain results
        ok, bbox, angle, center_loc, fps = tracker.update(frame, verbose=False)
        if ok:
            cnn_pred = tracker.cnn_pred
            print("Frame: {:5d} | bbox: {:4d} {:4d} {:3d} {:3d}  | fps: {:3d} |  CNN predict: {}".format(
                                                    video.getFrameIdx(), 
                                                    int(bbox[0]), int(bbox[1]), 
                                                    int(bbox[2]), int(bbox[3]),
                                                    int(fps),
                                                    cnn_pred)) 
            drawBox(frame, bbox)
            drawAnlge(frame, angle, center_loc)
            drawPoint(frame, center_loc)
            cv2.putText(frame, "Angle : " + str(int(angle)), (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 
                        (0, 255, 0), 2)
            cv2.putText(frame, "FPS : " + str(int(fps)), (10,60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 
                        (0, 255, 0), 2)
            
        else:
            print("Fail on tracking!!!")
            cv2.putText(frame, "Fail!", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 
                        (0, 0, 255), 2);
        frame_resize = cv2.resize(frame, (512, 512))
        video_writer.append_data(swapChannels(frame_resize))
        cv2.imshow("frame", frame_resize)
        k = cv2.waitKey(1)
        if k == 32 : break

print("Save image to {}".format(image_name))
video_writer.close()





