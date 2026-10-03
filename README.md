# MonoCameraVRTracker

단일 RGB 카메라의 인체 자세 추정값을 SteamVR의 **허리·왼발·오른발 가상 트래커**로 전송하는 초기 프로토타입입니다. 기존 HMD와 컨트롤러를 함께 사용합니다.

Fast SAM 3D Body의 실제 추론 API를 연결하고, 보정·필터·전송·OpenVR 드라이버를 구현했습니다. 모델 없이 데모와 기록 파일로 전체 데이터 경로를 검사할 수 있습니다. GPU 추론 정확도, RTX 4080 실시간 성능, 실제 SteamVR/VRChat 동작은 아직 검증하지 않았습니다.

## 모델 없이 바로 실행

Python 3.10 이상에서 저장소 루트 기준으로 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m monovrtrack demo --frames 120
```

데모는 합성 보행 포즈 120개를 약 30Hz로 로컬 UDP에 전송합니다. SteamVR이 없어도 실행됩니다. 처리 결과만 확인하려면:

```powershell
python -m monovrtrack demo --frames 60 --rate 0 --no-udp
python -m monovrtrack demo --frames 60 --no-udp --record captures.jsonl --output trackers.jsonl
python -m monovrtrack replay captures.jsonl --no-udp
```

마지막에 유효 프레임 수·거부 사유·평균 및 95백분위 추론 시간을 JSON으로 출력합니다. 시간 통계는 최근 최대 10,000프레임을 사용합니다. `--rate 0`은 속도 제한을 해제합니다. 데모 처리율은 GPU 모델 성능을 나타내지 않습니다. Linux/macOS에서도 Python 데모는 실행할 수 있고, 네이티브 드라이버는 Windows x64용입니다.

## 카메라와 모델

GPU 백엔드는 Python 3.11, NVIDIA CUDA PyTorch, 외부 Fast SAM 3D Body 소스와 Meta 모델 파일이 필요합니다. [설치 안내](docs/sam3d.md)에 따라 의존성 설치와 모델 접근 승인·다운로드를 완료하세요. 체크포인트는 이 Git 저장소에 포함하지 않습니다.

```powershell
python -m pip install -e ".[camera]"
python scripts/setup_models.py
# Hugging Face 모델 접근 승인 및 hf auth login 이후:
python scripts/setup_models.py --download

python -m monovrtrack run --config config/rtx4080.yaml --preview
```

시작할 때 몸 전체와 양발을 화면에 넣고 똑바로 서세요. 첫 유효 포즈에서 임시 바닥과 중심을 정합니다. 카메라 preview 창에서 `Q` 또는 터미널에서 `Ctrl+C`로 종료합니다. 웹캠 대신 `--video path/to/video.mp4`도 사용할 수 있습니다. 기본값은 단일 인물·전체 화면 추론입니다. **사람 검출기 없이 빈 화면을 구분하는 기능은 없습니다.** 필요하면 별도 YOLO 모델 경로를 설정에 넣을 수 있으며 외부 라이선스가 적용됩니다.

`config/rtx4080.yaml`은 body 추론·카메라 해상도·타임아웃 설정의 시작점입니다. `target_fps`는 최대 전송 루프 속도이며 측정된 RTX 4080 FPS가 아닙니다. TensorRT 엔진이나 검증되지 않은 성능 수치를 제공하지 않습니다. 모델 추론이 기본 0.5초보다 길면 포즈를 거부하고 `stale_observation`으로 보고합니다. 실제 지연을 측정해 조정하세요.

## SteamVR와 방 보정

[Windows 드라이버 빌드·등록 안내](docs/steamvr.md)를 따른 뒤 SteamVR의 Manage Trackers에서 세 장치의 역할을 지정합니다. 실물 SteamVR 설치·HMD와 함께 한 번 확인해야 합니다.

모델 좌표와 SteamVR 방 원점을 맞추려면 카메라를 고정하고 서 있는 포즈로 보정 파일을 저장하세요.

```powershell
python -m monovrtrack calibrate --config config/rtx4080.yaml --save calibration.json --origin 0 0 -1 --yaw-degrees 0 --scale 1
python -m monovrtrack run --config config/rtx4080.yaml --calibration calibration.json --preview
```

`--origin X Y Z`는 서 있는 골반의 바닥 투영점을 놓을 SteamVR 방 좌표입니다. 단위는 m, 축은 +X 오른쪽·+Y 위쪽·-Z 앞쪽입니다. `--yaw-degrees`는 카메라와 방의 방향 차이, `--scale`은 수동 크기 배율입니다. HMD를 이용한 자동 정렬은 제공하지 않습니다. 카메라를 옮기면 보정을 다시 하고, VRChat 내 전신 보정도 진행하세요. 단안 영상의 깊이·가림·발 회전 오차는 보정만으로 제거되지 않습니다.

One Euro 필터로 위치와 회전을 안정화합니다. 선택적 foot lock은 `tracking.foot_lock: true`로 켤 수 있으며 기본은 꺼져 있습니다. 바닥 근처에서 느리게 움직이는 발목을 잠깐 고정하는 보조 기능으로, 실제 접촉을 센서로 측정하지 않습니다.

## 개발과 검증

```powershell
python -m pip install -e ".[dev,camera]"
python -m pytest -q
python scripts/benchmark.py --source demo --frames 300
# 모델 설치 이후 실제 추론 측정:
python scripts/benchmark.py --source camera --frames 300
```

Python 테스트는 모델 출력의 단위/축/관절 매핑, 보정, 필터, 추적 상실, 패킷, 카메라의 최신 프레임 처리와 CLI 기록·재생을 검증합니다. 네이티브 CTest는 패킷 파서와 로컬 소켓을 검사합니다. GitHub Actions에서 Python 검사와 Windows 드라이버 빌드를 실행합니다. 실제 모델·SteamVR가 필요한 검증은 CI에 포함되지 않습니다.

구조와 데이터 계약은 [아키텍처 문서](docs/architecture.md)에 정리되어 있습니다. Python 도구용 ZeroMQ JSON publisher도 `python -m pip install -e ".[zmq]"` 후 `--zmq tcp://127.0.0.1:39571`로 사용할 수 있습니다. 네이티브 드라이버 연결에는 UDP를 사용합니다. 진단 수신기 `monovrtrack listen`은 SteamVR과 같은 포트이므로 SteamVR을 닫고 실행하세요.

## 라이선스

이 프로젝트의 코드: [MIT](LICENSE). 외부 SAM 모델·MHR 자산·DINOv3·선택적 검출기·OpenVR에는 각각의 라이선스가 적용됩니다. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하세요. 모델 소스/가중치와 생성된 DLL은 Git에 포함하지 않습니다.
