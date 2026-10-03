# Fast SAM 3D Body 백엔드

이 프로젝트는 외부 Fast SAM 3D Body의 실제 추론 API를 연결합니다. 모델 코드와 체크포인트는 Git 저장소에 포함하지 않습니다. 기본 모드는 `body`이며 허리/무릎/발/어깨를 추정합니다. 손 전용 decoder는 실행하지 않습니다. RTX 4080에서의 FPS와 지연 시간은 아직 측정하지 않았습니다.

## 준비

Python 3.11 환경과 NVIDIA 드라이버가 필요합니다. [PyTorch 공식 설치 안내](https://pytorch.org/get-started/locally/)에 따라 CUDA가 활성화된 PyTorch와 torchvision을 설치한 뒤 확인합니다.

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
python -m pip install -e ".[camera]"
python -m pip install pytorch-lightning yacs omegaconf einops timm roma braceexpand huggingface_hub
python scripts/setup_models.py
```

위 명령은 외부 소스만 `external/Fast-SAM-3D-Body`에 준비합니다. 설치 기준 commit은 `d72aa36913a1673ace029d345f437561a85ec9e2`입니다. 이미 다른 버전의 checkout이 있으면 덮어쓰지 않고 중단합니다.

[Meta의 모델 페이지](https://huggingface.co/facebook/sam-3d-body-dinov3)에서 접근 권한을 신청하고 승인받은 다음, 개인 컴퓨터에서 로그인합니다.

```powershell
hf auth login
python scripts/setup_models.py --download
```

토큰을 설정 파일, Git 저장소, 명령 인수에 넣지 마세요. 다운로드 기준 모델 revision은 `11aaa346c7204874a1cbafe3d39a979080b2c55a`입니다. 필요한 파일은 다음과 같습니다.

```text
models/sam-3d-body-dinov3/
  model.ckpt
  model_config.yaml
  assets/mhr_model.pt
```

첫 모델 로딩 시 upstream DINOv3 backbone은 `torch.hub`를 통해 추가 소스 코드를 가져올 수 있습니다. 초기 실행에는 인터넷 연결이 필요할 수 있습니다. 원본 [설치 안내](https://github.com/facebookresearch/sam-3d-body/blob/main/INSTALL.md)에는 시각화/학습/다른 검출기에 필요한 추가 패키지도 나와 있습니다. 이 adapter의 기본 전체 화면 추론에는 Detectron2, MoGe, SAM3, TensorRT가 필요하지 않습니다. Windows 네이티브 실행과 GPU 추론은 이 저장소의 CPU 단위 테스트만으로 검증되지 않았습니다.

## API

```python
from monovrtrack.tracking.sam3d_backend import SAM3DBackend

backend = SAM3DBackend(
    upstream_dir="external/Fast-SAM-3D-Body",
    checkpoint_path="models/sam-3d-body-dinov3/model.ckpt",
    mhr_path="models/sam-3d-body-dinov3/assets/mhr_model.pt",
    device="cuda",
    inference_type="body",
)
# frame: OpenCV BGR uint8 HxWx3; timestamp: monotonic seconds
skeleton = backend.infer(frame, timestamp)
backend.close()
```

한 추론 스레드에서 호출해야 합니다. `bbox=[x1,y1,x2,y2]`는 원본 카메라 영상의 픽셀 좌표입니다. 기본값은 한 사람이 몸 전체를 화면 안에 넣는 구도이며 전체 영상을 한 사람 영역으로 처리합니다. 검출기를 사용하지 않으면 빈 화면에서도 모델이 포즈를 만들어 낼 수 있으므로 사용자가 화면을 떠났는지 판정하는 기능은 제공하지 않습니다.

사람 검출이 필요하면 Ultralytics를 별도로 설치하고 본인이 준비한 YOLO checkpoint 파일 경로를 `detector_model_path`에 넘깁니다. 검출기가 사람을 찾지 못하면 `None`을 반환합니다. 여러 사람이 있으면 가장 큰 bbox를 고르며 사람의 ID를 유지하는 추적은 구현하지 않았습니다. Ultralytics 패키지와 YOLO11 모델의 라이선스는 [AGPL-3.0 또는 Enterprise](https://docs.ultralytics.com/models/yolo11/#citations-and-acknowledgments)입니다.

## 관절과 좌표

[upstream estimator](https://github.com/yangtiming/Fast-SAM-3D-Body/blob/d72aa36913a1673ace029d345f437561a85ec9e2/sam_3d_body/sam_3d_body_estimator.py)는 각 사람의 `pred_keypoints_3d` `(70,3)`, `pred_cam_t` `(3,)`, `bbox` 등을 반환합니다. [MHR head](https://github.com/yangtiming/Fast-SAM-3D-Body/blob/d72aa36913a1673ace029d345f437561a85ec9e2/sam_3d_body/models/heads/mhr_head.py)는 이미 cm를 m로 변환합니다. [projection 구현](https://github.com/yangtiming/Fast-SAM-3D-Body/blob/d72aa36913a1673ace029d345f437561a85ec9e2/sam_3d_body/models/meta_arch/sam3d_body.py)에 따라 카메라 translation을 keypoint에 한 번 더한 뒤 `(x, -y, -z)`로 변환합니다. 결과 축은 카메라 기준 오른쪽 `+X`, 위쪽 `+Y`, 카메라 쪽 `+Z`입니다. 바닥/VR 공간 원점은 별도 calibration에서 결정합니다. 모델의 깊이와 신체 크기는 단안 영상으로 추정한 값이며 실제 측정값이 아닙니다.

[MHR70 관절 정의](https://github.com/yangtiming/Fast-SAM-3D-Body/blob/d72aa36913a1673ace029d345f437561a85ec9e2/sam_3d_body/metadata/mhr70.py)에 따른 주요 mapping입니다.

| 이름 | MHR70 index |
|---|---:|
| left_hip / right_hip | 9 / 10 |
| left_knee / right_knee | 11 / 12 |
| left_ankle / right_ankle | 13 / 14 |
| left_toe / right_toe | 15 / 18 |
| left_heel / right_heel | 17 / 20 |
| left_shoulder / right_shoulder | 5 / 6 |
| neck | 69 |
| pelvis | 양쪽 hip의 평균 |

upstream은 보정된 관절별 confidence를 반환하지 않습니다. adapter의 `confidence=1.0`은 유한한 좌표를 받았다는 의미입니다. 가림/오차 확률을 나타내지 않으며, 핵심 관절이나 translation이 NaN/Inf이면 해당 프레임은 `None` 처리합니다. 관절 개수 등 API schema가 바뀌면 명확한 오류로 중단합니다.

## 성능 설정과 검증 범위

먼저 기본 PyTorch/body 추론으로 측정하세요. 모델 설정의 `TRAIN.USE_FP16` 값에 따라 backbone은 FP16을 사용할 수 있으며 전체 모델이 FP32라는 의미는 아닙니다. Fast upstream의 `LAYER_DTYPE=fp16` 또는 `bf16`은 decoder autocast 설정이고, `USE_COMPILE=1`과 함께 별도 실험이 가능하지만 이 adapter가 성능이나 수치 안정성을 보장하지 않습니다. TensorRT engine은 모델, GPU, TensorRT 환경에 맞춰 별도로 생성해야 하며 이 프로젝트에는 포함되어 있지 않습니다. upstream이 보고한 RTX 5090 성능을 RTX 4080 성능으로 옮겨 적지 않았습니다.

CPU 테스트는 RGB 변환, 관절 mapping, 단위/축/translation, person 선택, 입력/출력 검증, 추적 상실 처리를 검증합니다. 실제 카메라 영상과 RTX 4080에서의 모델 정확도, GPU 메모리 사용량, 실시간 처리율은 권한 승인과 모델 설치 이후 확인해야 합니다.
