"""GPU-accelerated camera service for the Jetson.

Drop-in replacement for the CPU `cameras` service: same RTSP agents,
same MQTT events, same recognition database. Only the inference path
changes - detection (SCRFD) and recognition (ArcFace) run as TensorRT
engines on the Volta GPU instead of CPU onnxruntime.

The CPU pipeline (`cameras/`) stays untouched for non-Jetson machines;
this package is an independent module.
"""