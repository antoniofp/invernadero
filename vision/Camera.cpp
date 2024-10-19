#include "Camera.h"
#include <iostream>

Camera::Camera(int cameraID) : cameraID(cameraID) {}

Camera::~Camera() {
    closeCamera();
}

bool Camera::openCamera() {
    cap.open(cameraID);
    if (!cap.isOpened()) {
        std::cerr << "Error: Couldn't open the camera." << std::endl;
        return false;
    }
    return true;
}

bool Camera::captureFrame(cv::Mat& frame) {
    if (!cap.isOpened()) return false;
    cap >> frame;
    return !frame.empty();
}

void Camera::displayFrame(const cv::Mat& frame) {
    if (!frame.empty()) {
        cv::imshow("Camera Feed", frame);
    }
}

void Camera::closeCamera() {
    if (cap.isOpened()) {
        cap.release();
    }
}
