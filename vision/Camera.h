#ifndef CAMERA_H
#define CAMERA_H

#include <opencv2/opencv.hpp>

class Camera {
public:
    Camera(int cameraID = 0);
    ~Camera();
    bool openCamera();
    bool captureFrame(cv::Mat& frame);
    void displayFrame(const cv::Mat& frame);
    void closeCamera();

private:
    int cameraID;
    cv::VideoCapture cap;
};

#endif // CAMERA_H
