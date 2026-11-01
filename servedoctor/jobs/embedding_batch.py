"""A neighbouring GPU batch job used to inject compute contention.

It runs dense matmuls on the serving GPU with a duty cycle and a small, fixed
memory footprint. The name is deliberately ordinary: an agent must infer from
telemetry that it competes with serving, not from a revealing process name.
"""
import argparse
import math
import time


def run_batch(torch, a, b, *, seconds, duty, period, clock=time.monotonic, sleeper=time.sleep):
    """Time completed GPU work, keeping at most one matrix operation in flight.

    CUDA launches are asynchronous. Synchronizing each iteration prevents a
    short CPU enqueue window from building seconds of queued GPU work. Reuse
    the two output buffers so the job's matrix memory stays fixed.
    """
    work = torch.empty_like(a)
    torch.cuda.synchronize()
    end = clock() + seconds
    while clock() < end:
        cycle_start = clock()
        busy_until = min(end, cycle_start + period * duty)
        while clock() < busy_until:
            torch.matmul(a, b, out=work)
            work.div_(work.norm())
            torch.cuda.synchronize()
            a, work = work, a
        # Account for any final-matmul overshoot instead of adding a full idle
        # interval after it. Clip the last sleep to the overall deadline.
        idle = min(end, cycle_start + period) - clock()
        if idle > 0:
            sleeper(idle)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nightly embedding batch job")
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--duty", type=float, default=1.0)
    parser.add_argument("--size", type=int, default=8192)
    parser.add_argument("--period", type=float, default=0.2)
    args = parser.parse_args(argv)
    if (not 0 < args.duty <= 1 or not 256 <= args.size <= 16384 or not 0 < args.seconds <= 7200
            or not math.isfinite(args.period) or args.period <= 0):
        raise SystemExit("invalid arguments")
    import torch
    device = torch.device("cuda")
    a = torch.randn(args.size, args.size, device=device, dtype=torch.bfloat16)
    b = torch.randn(args.size, args.size, device=device, dtype=torch.bfloat16)
    run_batch(torch, a, b, seconds=args.seconds, duty=args.duty, period=args.period)


if __name__ == "__main__":
    main()
