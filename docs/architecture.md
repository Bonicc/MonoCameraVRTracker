# 구조와 데이터 계약

```text
Webcam 최신 프레임 / Video / Demo / Skeleton JSONL
                 ↓
       Backend.infer(frame, timestamp)
                 ↓
         Canonical Skeleton
                 ↓
   유효성·관측 나이 검사 → Calibration
                 ↓
    JointMapper: waist / left_foot / right_foot
                 ↓
    One Euro 위치·회전 필터 → 선택적 Foot Lock
                 ↓
           UDP 236바이트
                 ↓
   OpenVR DLL → SteamVR GenericTracker × 3
```

카메라·GPU 추론은 Python에서 실행하고 SteamVR 프로세스에는 소켓 수신과 장치 상태 보고만 넣습니다. DLL은 포즈를 예측하거나 모델을 로드하지 않습니다.

## 모듈

| 위치 | 역할 |
|---|---|
| `src/monovrtrack/cli.py` | 데모·카메라·재생·보정·진단 실행 |
| `camera.py` | 웹캠을 계속 읽고 하나의 최신 프레임만 유지 |
| `tracking/backend.py` | 추론 인터페이스와 데모·JSONL 백엔드 |
| `tracking/sam3d_backend.py` | 외부 Fast SAM 3D Body API와 MHR70 매핑 |
| `tracking/calibration.py` | 미터 배율·바닥·yaw·방 원점 변환 |
| `tracking/joint_mapper.py` | 골반·발목 위치와 관절 방향에서 세 트래커 생성 |
| `tracking/smoothing.py` | 적응형 One Euro 위치 및 quaternion 필터 |
| `tracking/foot_lock.py` | 바닥 근처·낮은 속도의 선택적 발목 고정 |
| `tracking/pipeline.py` | 검증·변환·필터 순서와 추적 상실 상태 관리 |
| `transport/udp_bridge.py` | OpenVR와 공유하는 바이너리 전송 |
| `transport/zmq_bridge.py` | 별도 분석 도구용 선택적 JSON PUB |
| `driver/openvr/` | Windows x64 네이티브 SteamVR 드라이버 |

## 포즈

`Joint.position = (x,y,z)`는 m 단위이며 +X는 카메라 오른쪽, +Y는 위쪽, +Z는 카메라 쪽입니다. 보정한 뒤 같은 축 표기에서 SteamVR 방 좌표가 됩니다. `Skeleton.timestamp`는 Python `time.monotonic()` 초 단위입니다. quaternion은 **w,x,y,z** 순서이고 정규화합니다.

최소 관절은 pelvis, 양쪽 hip/knee/ankle입니다. 어깨를 사용할 수 있으면 허리 위 방향을 추정하고, heel/toe가 있으면 발 방향에 사용합니다. 발의 위치는 발목, 허리는 두 hip의 중심입니다. 이 회전은 관절에서 계산한 근사치이며 트래커 실물 부착 방향 측정값은 아닙니다.

관절이나 시간이 잘못되었거나 필수 관절이 없으면 해당 프레임을 보내지 않고 필터 상태를 초기화합니다. 너무 오래된 관측을 계속 재전송하지 않습니다. 카메라·Python 앱이 중단되면 드라이버는 마지막 정상 수신 이후 0.5초에 포즈를 무효화합니다. SAM 기본값에는 보정된 관절별 confidence가 없으므로 유한한 결과의 confidence 1.0이 추정 정확도를 의미하지 않습니다.

## 지연과 보정

웹캠 reader는 추론 중에도 영상을 계속 읽으며 새로운 프레임이 기존 프레임을 덮어씁니다. 사용자 공간에 영상 큐를 쌓지 않습니다. 기록한 시각은 카메라 API가 프레임을 반환한 시각이며 하드웨어 노출 시각은 아닙니다. OS/카메라 내부 버퍼의 지연까지 측정하지는 못합니다. 영상 파일과 JSONL은 한 번 호출할 때 한 프레임씩 진행합니다. JSONL의 옛 timestamp는 현재 단조 시계로 다시 설정되며 원래 기록 속도는 자동 재현하지 않습니다. `--rate`로 재생 속도를 정하세요.

보정은 서 있는 포즈의 heel/toe 최저 높이를 바닥으로 잡고 pelvis의 수평 위치를 지정한 방 원점에 맞춥니다. HMD나 Chaperone에 자동 정렬하지 않습니다. 적용 식은 `room_position = scale * yaw_rotation(camera_position) + translation`입니다. `calibration.json`의 좌표계·버전을 검사한 뒤 불러옵니다.

UDP 포트와 정확한 바이트 오프셋은 [SteamVR 문서](steamvr.md)에 있습니다. 드라이버 포트는 39570으로 고정되어 있으므로 Python 설정의 기본 포트와 맞추세요. 헤더 timestamp와 C++ 단조 시계의 기준점은 같다고 가정하지 않으며 드라이버는 수신 경과 시간으로 만료를 계산합니다.

필터는 [One Euro Filter 저자 구현](https://github.com/casiez/OneEuroFilter)의 적응형 cutoff 방식을 독립적으로 구현했습니다. 회전에는 부호 연속성과 짧은 호의 spherical interpolation을 적용합니다. 측정이 끊기거나 시간이 역전되면 이전 포즈와 섞지 않습니다.

## 후속 검증

먼저 실제 RTX 4080에서 모델을 설치하고 지속 지연·발 위치·돌아서는 동작·가림·빈 화면을 측정해야 합니다. 그다음 HMD와 SteamVR에서 방 보정 및 세 역할을 확인하고 VRChat 전신 보정을 진행합니다. TensorRT/ONNX, 자동 HMD 정렬, 사용자 ID 유지, GUI 설정·배포 설치 프로그램은 현재 범위 밖입니다.
