# Third-party sources

ServeTune source is MIT-licensed. That license does not relicense its model,
datasets, dependencies, or cited research.

- Workload and evaluation data: [GSM8K](https://github.com/openai/grade-school-math),
  MIT license, pinned source commit and retained license in each prepared data
  directory. Dev/final/performance splits and source selection are hashed.
- Model: [Meta Muse Glimmer 30B](https://huggingface.co/meta-models/Muse-Glimmer-30B),
  revision `cec94fcfd6512f2cfe708138c32533b346ea4f69`. Model weights are not
  included in this repository or the source/recovery bundles. Consult the
  checkpoint's own license before downloading or redistributing weights.
- Runtime: [vLLM](https://github.com/vllm-project/vllm), PyTorch and NVIDIA NVML,
  under their respective licenses; exact deployed versions are captured in the
  environment and per-trial manifests. No NVIDIA drivers or model weights ship
  with the source.
- Optional demo rendering: Pillow and imageio-ffmpeg under their respective
  licenses. FFmpeg builds carry their own licensing terms.
- Prior work: [InferenceBench](https://arxiv.org/abs/2607.20468) and
  [AutoTuneBench](https://arxiv.org/abs/2609.18123). Their code or data are not
  copied into ServeTune.

No employer code, internal configuration, private dataset, or provider credential
is part of the released source.
