#include "Camera.h"
#include <opencv2/opencv.hpp>
#include <iostream>

int main() {
    Camera cam(0);  // Instantiate camera object
    if (!cam.openCamera()) {
        return -1;
    }

    cv::Mat frame;
    while (true) {
        if (!cam.captureFrame(frame)) {
            std::cerr << "Error: Blank frame grabbed." << std::endl;
            break;
        }

        cam.displayFrame(frame);  // Show the camera feed

        // Other functionalities can be added here
        // For example, you can process the frame, detect objects, etc.
        if (cv::waitKey(30) >= 0) {
            break;  // Exit loop if a key is pressed
        }
    }

    cam.closeCamera();  // Clean up
    return 0;
}
