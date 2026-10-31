"""A neighbouring GPU batch job used to inject compute contention.

It runs dense matmuls on the serving GPU with a duty cycle and a small, fixed
memory footprint. The name is deliberately ordinary: an agent must infer from
telemetry that it competes with serving, not from a revealing process name.
"""
import argparse
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nightly embedding batch job")
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--duty", type=float, default=1.0)
    parser.add_argument("--size", type=int, default=8192)
    parser.add_argument("--period", type=float, default=0.2)
    args = parser.parse_args(argv)
    if not 0 < args.duty <= 1 or not 256 <= args.size <= 16384 or not 0 < args.seconds <= 7200:
        raise SystemExit("invalid arguments")
    import torch
    device = torch.device("cuda")
    a = torch.randn(args.size, args.size, device=device, dtype=torch.bfloat16)
    b = torch.randn(args.size, args.size, device=device, dtype=torch.bfloat16)
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        busy_until = time.monotonic() + args.period * args.duty
        while time.monotonic() < busy_until:
            a = torch.matmul(a, b)
            a = a / a.norm()
        torch.cuda.synchronize()
        idle = args.period * (1 - args.duty)
        if idle > 0:
            time.sleep(idle)


if __name__ == "__main__":
    main()
