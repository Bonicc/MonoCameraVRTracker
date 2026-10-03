# Third-party components

This repository contains original integration code. It does not redistribute SAM 3D Body source, checkpoints, MHR assets, YOLO checkpoints, or TensorRT engines. Downloaded external components retain their upstream licenses; the license of this project's own code does not replace them.

| Component | Source | Terms |
|---|---|---|
| Fast SAM 3D Body acceleration code | [yangtiming/Fast-SAM-3D-Body](https://github.com/yangtiming/Fast-SAM-3D-Body) | The upstream root [LICENSE](https://github.com/yangtiming/Fast-SAM-3D-Body/blob/main/LICENSE) states MIT, copyright 2026 Fast SAM 3D Body Authors. |
| Meta SAM 3D Body code and model materials | [facebookresearch/sam-3d-body](https://github.com/facebookresearch/sam-3d-body) | [SAM License](https://github.com/facebookresearch/sam-3d-body/blob/main/LICENSE). This includes the pretrained SAM checkpoint and associated model assets downloaded from Meta's model repository. |
| DINOv3 backbone source used by upstream | [facebookresearch/dinov3](https://github.com/facebookresearch/dinov3) | [DINOv3 License](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md). The upstream backbone may fetch this through torch.hub at runtime. |
| Optional Ultralytics detector and YOLO11 weights | [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics) | [AGPL-3.0 or Enterprise terms](https://docs.ultralytics.com/models/yolo11/#citations-and-acknowledgments). It is not installed or downloaded by the model setup script. |
| Valve OpenVR driver header and compiled inline helpers | [ValveSoftware/openvr](https://github.com/ValveSoftware/openvr/tree/91825305130f446f82054c1ec3d416321ace0072) | [BSD-3-Clause license](https://github.com/ValveSoftware/openvr/blob/91825305130f446f82054c1ec3d416321ace0072/LICENSE), copyright 2015 Valve Corporation. The build fetches the checksum-pinned header; the distributable driver package includes the complete Valve license in `THIRD_PARTY_NOTICES.txt`. |

Fast SAM 3D Body builds on Meta's SAM 3D Body. Its root MIT license should not be interpreted as relicensing the inherited Meta materials or checkpoints. Preserve the applicable upstream notices and license agreements if distributing those materials.

The checkpoint repository [facebook/sam-3d-body-dinov3](https://huggingface.co/facebook/sam-3d-body-dinov3) requires a model access request and local authentication. The setup script uses the user's existing Hugging Face login and keeps model files out of Git. It does not bypass the model gate.

References were checked on 2026-10-03. Source and model revisions used by the setup script are documented in [docs/sam3d.md](docs/sam3d.md). Other runtime dependencies retain their own licenses.
