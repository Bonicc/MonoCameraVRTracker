# SteamVR 가상 트래커 드라이버

Python 앱은 카메라 포즈를 계산하고, 네이티브 DLL은 UDP 데이터를 받아 SteamVR에 **허리·왼발·오른발 세 개의 GenericTracker**를 등록합니다. HMD와 컨트롤러는 기존 SteamVR 드라이버를 사용합니다. 입력 포즈는 SteamVR 방 좌표로 보정된 미터 단위여야 합니다: +X 오른쪽, +Y 위쪽, -Z 앞쪽. 이 DLL 자체는 카메라 좌표 보정을 수행하지 않습니다.

## Windows x64 빌드

필요 사항: CMake 3.21 이상과 Visual Studio C++ Build Tools 또는 x64 MinGW. 첫 구성 시 Valve의 공식 `openvr_driver.h`를 다운로드합니다. OpenVR v2.12.14 커밋 `91825305130f446f82054c1ec3d416321ace0072`와 SHA-256 체크섬을 고정했습니다. 추적용 드라이버 API만 사용하며 애플리케이션용 `openvr.h`는 함께 포함하지 않습니다.

저장소 루트의 PowerShell에서:

```powershell
.\driver\openvr\build-driver.ps1
# MinGW 사용 시:
.\driver\openvr\build-driver.ps1 -Toolchain MinGW
```

생성 결과:

```text
driver/openvr/build/monocameravrtracker/
  driver.vrdrivermanifest
  bin/win64/driver_monocameravrtracker.dll
  resources/settings/default.vrsettings
```

MinGW 빌드는 C++ 런타임을 정적으로 연결합니다. 빌드된 DLL·빌드 폴더는 소스 저장소에 포함하지 않습니다. Debug/Release 구성은 같은 패키지 위치에 생성되므로 사용할 구성을 다시 빌드하세요.

## SteamVR에 등록

SteamVR을 종료한 상태에서:

```powershell
.\driver\openvr\register-driver.ps1
```

스크립트가 `%LOCALAPPDATA%\openvr\openvr.vrpaths`에서 실제 SteamVR 설치 경로를 찾고 그 설치의 `bin\win64\vrpathreg.exe`를 호출합니다. 설치 위치를 자동으로 찾지 못하면 다음처럼 실제 경로를 지정합니다:

```powershell
.\driver\openvr\register-driver.ps1 -SteamVRPath 'D:\SteamLibrary\steamapps\common\SteamVR'
```

SteamVR을 다시 시작하고, 드라이버가 차단되어 있으면 SteamVR 추가 기능 관리에서 `monocameravrtracker`를 활성화하세요. 카메라 앱을 실행하고 보정을 완료한 후 SteamVR의 트래커 관리(Manage Trackers)에서 다음 역할을 직접 지정합니다.

| 일련번호 | SteamVR 역할 |
|---|---|
| `MONOCAMERA-WAIST` | Waist |
| `MONOCAMERA-LEFT-FOOT` | Left Foot |
| `MONOCAMERA-RIGHT-FOOT` | Right Foot |

일련번호는 실행마다 동일합니다. 드라이버가 역할 설정을 덮어쓰지 않으므로 SteamVR에서 지정한 역할을 유지할 수 있습니다. VRChat 등 앱에서 별도 전신 보정도 진행해야 합니다.

등록 해제:

```powershell
.\driver\openvr\register-driver.ps1 -Unregister
```

별도 빌드 경로로 만든 패키지는 등록과 해제 모두 `-DriverPath '전체\경로\monocameravrtracker'`를 지정합니다. 등록 스크립트는 SteamVR 등록 목록만 수정하며 앱과 빌드 파일은 삭제하지 않습니다.

## UDP 계약과 포즈 상태

IPv4 `127.0.0.1:39570`에 정확히 **236바이트**를 전송합니다. 모든 수치는 little-endian이며 구조체 메모리를 직접 전송하지 않습니다.

| 구간 | Python struct 형식 | 바이트 | 내용 |
|---|---|---:|---|
| 헤더 | `<4sHHId` | 20 | `MVR1`, 버전 1, 개수 3, sequence uint32, monotonic timestamp double |
| 트래커 × 3 | `<B7x3d4df4x` | 72 × 3 | role uint8, padding 7, 위치 xyz double, 회전 wxyz double, confidence float32, padding 4 |

role은 허리 0, 왼발 1, 오른발 2입니다. 레코드 순서는 자유롭지만 세 역할은 각각 정확히 한 번 있어야 합니다. 잘못된 크기·버전·역할, 비유한 값, [0,1] 밖 confidence, 길이가 [0.9,1.1] 밖인 quaternion은 패킷 전체를 거부합니다. 허용된 quaternion은 정규화합니다. 거부된 패킷은 이전 유효 데이터의 시간 제한을 갱신하지 않습니다.

수신은 SteamVR 프레임 콜백에서 비차단 소켓으로 처리하며, 매 콜백 최대 256개의 패킷 중 마지막 유효 패킷을 사용합니다. 시퀀스는 진단 정보이며 UDP 수신 순서로 적용합니다. Python 프로세스 재시작 시 시퀀스가 초기화되어도 계속 받을 수 있습니다. 카메라를 놓친 트래커는 confidence를 0으로 전송해야 합니다.

마지막 유효 패킷을 받은 뒤 **0.5초 이상** 지나면 세 트래커 모두 연결 해제·포즈 무효로 보고합니다. 그 전에도 confidence가 기본 임계값 0.5 미만인 트래커는 연결됨·추적 범위 밖으로 보고합니다. 임계값은 SteamVR `driver_monocameravrtracker.minimum_confidence` 설정으로 변경할 수 있습니다.

Python과 C++ 단조 시계의 기준점이 같다고 가정하지 않습니다. 헤더 timestamp는 유효성 검사 후 진단용으로 보관하며, 만료 시간은 C++에서 받은 시각을 기준으로 계산합니다. 따라서 추론/전송 전 지연은 DLL에서 측정하거나 예측하지 않습니다. 애플리케이션도 오래된 카메라 포즈를 재전송하지 않아야 합니다.

## 검증과 한계

빌드 스크립트는 CTest로 네이티브 UDP 파서와 실제 localhost 수신을 검증합니다. OpenVR 또는 SteamVR 설치 없이 파서만 검사하려면:

```powershell
g++ -std=c++17 -I driver/openvr/src tests/native/protocol_test.cpp -o protocol_test.exe
.\protocol_test.exe tests/native/valid_packet.hex
```

`valid_packet.hex`는 Python `struct.pack`으로 만든 교차 언어 기준 데이터입니다. 잘린 패킷 전체, 역할 중복, 비유한 값, confidence, quaternion, 비정렬 메모리, 0.5초 만료 조건을 검증합니다. Windows 수신 검사는 별도 포트 39571에서 실제 datagram, 잘못된 데이터의 시간 제한, 다시 연결, 포트 정리를 검증합니다. 실제 SteamVR의 장치 등록·트래커 역할·VRChat 동작은 SteamVR과 HMD를 연결한 PC에서 확인해야 합니다. 단일 카메라의 가림/깊이/발 회전 오차가 있으며, 이 드라이버가 이를 해결하지는 않습니다.

포트 충돌이면 SteamVR 로그에 `UDP 127.0.0.1:39570 bind failed`가 표시됩니다. 다른 수신 프로그램을 종료하고 SteamVR을 다시 시작하세요. SteamVR 개발자 웹 콘솔에서 `monocameravrtracker`를 검색하면 드라이버 시작 로그를 확인할 수 있습니다.

API 및 설치 형식 근거: [Valve OpenVR 드라이버 문서](https://github.com/ValveSoftware/openvr/blob/master/docs/Driver_API_Documentation.md), [Valve simpletrackers 예제](https://github.com/ValveSoftware/openvr/tree/master/samples/drivers/drivers/simpletrackers), [고정된 OpenVR 헤더](https://github.com/ValveSoftware/openvr/blob/91825305130f446f82054c1ec3d416321ace0072/headers/openvr_driver.h).
