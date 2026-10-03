# MonoCameraVRTracker SteamVR 드라이버

Windows x64 SteamVR용 허리·왼발·오른발 가상 트래커 DLL입니다.
카메라와 모델을 실행하는 Python 앱은 별도로 저장소에서 실행해야 합니다.

1. ZIP을 풀고 `monocameravrtracker` 폴더 이름을 유지하세요.
2. SteamVR을 종료하고 이 폴더의 PowerShell에서 `./register-driver.ps1`을 실행하세요.
3. SteamVR을 다시 시작하고 필요하면 추가 기능 관리에서 드라이버를 활성화하세요.
4. Python 카메라 앱을 실행하고 좌표 보정을 완료하세요.
5. SteamVR 트래커 관리에서 다음 역할을 지정하세요.

| 일련번호 | 역할 |
|---|---|
| MONOCAMERA-WAIST | Waist |
| MONOCAMERA-LEFT-FOOT | Left Foot |
| MONOCAMERA-RIGHT-FOOT | Right Foot |

설치 경로를 자동으로 찾지 못하면 실제 SteamVR 설치 위치를 지정하세요:

```powershell
./register-driver.ps1 -SteamVRPath 'D:\SteamLibrary\steamapps\common\SteamVR'
```

등록 해제는 `./register-driver.ps1 -Unregister`를 실행하고 SteamVR을 다시 시작하세요.
등록된 폴더를 이동했다면 이전 전체 경로를 `-DriverPath`로 지정하여 먼저 등록을 해제하세요.

앱은 UDP 127.0.0.1:39570으로 유효한 포즈를 보내야 합니다. 0.5초 동안 데이터가 없으면
트래커가 연결 해제됩니다. 단일 카메라의 가림과 깊이 오차는 별도의 보정이 필요합니다.

네이티브 빌드와 UDP 파서/수신 검사를 통과한 패키지입니다.
실제 HMD·SteamVR·VRChat에서의 동작은 사용자 장비에서 확인해야 합니다.
자세한 설정과 프로토콜은 저장소의 docs/steamvr.md를 참조하세요.
Valve OpenVR의 BSD-3-Clause 고지는 THIRD_PARTY_NOTICES.txt에 포함되어 있습니다.
