#!/usr/bin/env python3
"""Render final15-case prose from safe projections; never read sealed answers.

No study processing, validation, inference, ledger write or lifecycle action.
The caller must provide completed final evidence; this creates one fresh file.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from hard_report_common import ARMS, IDS, LABEL, PROJECT

HEAD = '4b0add12be36cef0d0776607f683310b1641b0f7'
CONFIG = '0cc70e7ec4cbb0b26c6e13a4b9311dedf6dd05a862d9c0d9d2934ec25a017014'
FREEZE = '868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68'
EXCLUSION = '783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9'
KEYS = 'fb168177884005df77a94cbb75e6d52946a26ccfc3675db82820bb9105eaadc0'
SCENARIOS = 'bbd1f792878602f6472e56a5795f9f257882ad541b3184ce38af00588c4d3f20'
REV = 'cec94fcfd6512f2cfe708138c32533b346ea4f69'


def require(value, reason):
    if not value:
        raise ValueError(reason)


def load(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Regular final evidence required')
    return json.loads(path.read_text())


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join('---' for _ in headers)+' |',
                      *['| '+' | '.join(cell(v) for v in row)+' |' for row in rows]])


def render(projection, cleanup, failures, hardware, prices, protocol, optional_live_status):
    require(projection.get('project') == PROJECT and projection.get('label') == LABEL,
            'Exact partial-analysis label required')
    require(projection.get('decision_coverage') == {'expected': 90, 'present': 90}
            and projection.get('freeze_sha256') == FREEZE, 'Completed90-cell frozen projection required')
    pairs = [(r['id'], r['arm']) for r in projection['per_case']]
    require(len(pairs) == 90 and set(pairs) == {(i, a) for i in IDS for a in ARMS},
            'Exactly15 retained IDs across all6 arms required')
    require(projection['valid_cases'] + projection['invalid_cases'] == 15
            and projection['denominators']['all']['cases'] == 15, 'Fifteen-case denominators required')
    require(protocol.get('project') == PROJECT and protocol.get('label') == LABEL
            and protocol.get('source_commit') == HEAD and protocol.get('included_hard_ids') == list(IDS)
            and protocol.get('excluded_ids') == ['hard-16'] and protocol.get('scientific_inputs_changed') is False
            and protocol['original_freeze']['sha256'] == FREEZE
            and protocol['exclusion']['sha256'] == EXCLUSION, 'Original freeze/exclusion lineage required')
    require(cleanup.get('confirmed_absent') is True and failures.get('project') == PROJECT
            and failures.get('finalized') is True,
            'Final cleanup and partial failure index required')
    cost, ledger = cleanup['gpu_accounting'], cleanup['ledger_summary']
    total = cost['total_usd_upper']
    require(type(total) in (int, float) and math.isfinite(total) and 0 <= total <= 40,
            'Final GPU total must fit40 dollars')
    require(ledger['caps_usd'] == {'meta': 50.0, 'baseten': 20.0}
            and 0 <= ledger['accounted_usd']['meta'] <= 50
            and 0 <= ledger['accounted_usd']['baseten'] <= 20, 'Existing ledger cap proof required')
    require(optional_live_status == 'not-run-budget-below-5' and 0 <= 40-total < 5,
            'Reassess optional live eligibility; renderer only supports explicit budget skip')
    scores, den = projection['scoreboards'], projection['denominators']
    require(set(scores['all']) == set(ARMS)
            and set(scores['valid_only']) == (set(ARMS) if projection['valid_cases'] else set()),
            'All6 canonical scoreboards required')
    hours = 14.302195 + cost['hard_running_hours']
    parts = ['# '+LABEL,
        'This is a separately authorized partial analysis of the original16-incident Hard study. '
        'One reference and hard-01 through hard-15 were recorded; hard-16 could not start. '
        'The original16-case attempt, its failure and frozen inputs remain preserved. '
        'The fifteen retained recordings were validated with the unchanged native rule before all six arms ran. '
        'The scoreboards below cover only those15 cases and their fixed valid subset.',
        'The user-approved mechanical exclusion was recorded at2026-11-02T23:07:44.538859+00:00 '
        'before any Hard validation or arm evaluation. At frozen KV utilization0.61632, the generated '
        'max_num_batched_tokens12288 required more startup reserve than the standalone8192-token calibration; '
        'vLLM reported -0.54 GiB available KV cache. Cleanup left2MiB/no compute process. '
        'The incident was not retuned, regenerated or re-recorded. Original16 answer-key/scenario/freeze bytes '
        'were copied unchanged to a fresh analysis namespace; only hard-16 is excluded from reporting.',
        'Hardware: one verified, on-demand Vast RTX PRO6000 Blackwell WS96GB with150GB disk, rental58866756, '
        'physical GPU `GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681`. '
        f"Driver `{hardware['driver_version']}`, vLLM `{hardware['vllm_version']}`. "
        'Image: `vastai/vllm@sha256:d17aa376347c086ce53d9f9ac3a70e904acbc37882a7ee0b1ba4f7f538f8d843`. '
        'Pre-generation capacity was6RPS. Standalone mild KV0.61632 produced p95 10.004323831864165s; '
        'compound KV0.61520 produced15.239633663152924s. Both completed268/268 requests with zero errors/shedding. '
        'These standalone probes did not establish startup compatibility with every generated configuration.',
        f'Glimmer: `meta-models/Muse-Glimmer-30B`, revision `{REV}`. '
        'Spark: `muse-spark-1.3`, $1.25 input/$4.25 output per million tokens. '
        'Wonder: `muse-wonder-1.0`, $4 input/$20 output per million tokens. '
        f"[Meta IDs](https://dev.meta.ai/docs/models) and [standard prices](https://dev.meta.ai/docs/pricing-rate-limits) "
        f"were verified before calls; price receipt time `{prices['verified_at_utc']}`. "
        'The existing environment-only key runner and native financial reservations were preserved. '
        'No credential is included in this package.',
        table(['Frozen item', 'Value'], [
            ['Recording/evaluation source', '`'+HEAD+'`'], ['Config SHA256', '`'+CONFIG+'`'],
            ['Original16 answer-key commitment', '`'+KEYS+'`'], ['Original16 scenario commitment', '`'+SCENARIOS+'`'],
            ['Original16 freeze SHA256', '`'+FREEZE+'`'], ['Pre-validation exclusion SHA256', '`'+EXCLUSION+'`']]),
        'Calibration used source `d3fe20a07ce9c687e75956200b655c5913021d49`; only the allowed host KV fields '
        'and notes changed before generation. Prompts, rule thresholds, scoring rules, answer keys and incident '
        'specifications were unchanged. Protected ServeTune v4 sources/results were unchanged.',
        f"Validity: **{projection['valid_cases']} valid, {projection['invalid_cases']} invalid, out of15 retained cases**. "
        'The one-shot native validity bytes remain in `answers/validity.json`. Invalid cases remain in the all15 scoreboard '
        'without stronger recordings. The valid-only scoreboard uses the same recorded decisions.',
        'All15 retained incidents (`python3 -m servedoctor score --study-dir runs/sd-hard-partial-attempt1 --split hard`):']
    headers = ['Arm', 'Cases', 'Detected', 'Correct diagnosis', 'Fix proposed', 'Complete fix',
               'Compound complete fix', 'Harmful', 'Stopped decoy']
    def rows(board):
        return [[a, *[board[a][k] for k in ('incidents', 'detected', 'diagnosis_correct', 'fix_proposed', 'complete_fix')],
                 str(board[a]['compound_complete_fix'])+'/'+str(board[a]['compound_incidents']),
                 board[a]['harmful'], board[a]['stopped_decoy']] for a in ARMS if a in board]
    parts += [table(headers, rows(scores['all'])), 'Valid-only (same command with `--valid-only`):',
              table(headers, rows(scores['valid_only'])) if scores['valid_only'] else 'The canonical valid-only scoreboard is empty: no retained case passed validity.',
              table(['Subset', 'Cases', 'Healthy controls', 'Nonhealthy cases', 'Compound cases', 'Cases with decoys'],
                    [[name, *[den[name][k] for k in ('cases', 'healthy_controls', 'nonhealthy_cases', 'compound_cases', 'decoy_cases')]]
                     for name in ('all', 'valid_only')]),
              'Per-case arm cells are `D/F/H/X`: diagnosis_correct/complete_fix/harmful/stopped_decoy (1=true,0=false). '
              'There are90 arm/case cells. Compound fix_proposed can address one cause; complete_fix requires both safely. '
              'The category counts come only from the trusted numeric projection; no answer text is reproduced.']
    by = {(r['id'], r['arm']): r for r in projection['per_case']}
    parts.append(table(['ID', 'Valid', 'Compound', 'Decoy present', *ARMS],
        [[i, int(by[i, ARMS[0]]['valid']), int(by[i, ARMS[0]]['compound']), int(by[i, ARMS[0]]['has_decoy']),
          *['/'.join(str(int(by[i, a][k])) for k in ('diagnosis_correct', 'complete_fix', 'harmful', 'stopped_decoy')) for a in ARMS]] for i in IDS]))
    parts += [
        f"GPU accounting: **{cost['hard_running_hours']:.6f} Hard rental hours**, approximately **{hours:.6f} including v0**. "
        f"Prior v0 upper ${cost['prior_v0_usd_upper']:.6f}; Hard compute ${cost['hard_compute_usd_upper']:.6f}; "
        f"Hard disk ${cost['hard_disk_usd_upper']:.6f}; added network reserve ${cost['new_network_reserve_usd']:.2f}; "
        f"slack ${cost['new_slack_reserve_usd']:.2f}. **Conservative total ${total:.6f}/$40**. "
        'This includes failed rentals, startup/shutdown uncertainty and retained disk; it is not a reconciled invoice. '
        'Final cleanup confirms the rental stopped/deleted with no queued start. Less than$5 remained; optional Hard live runs were not run.',
        f"Ledger: Meta **${ledger['accounted_usd']['meta']:.6f}/$50**, Baseten **${ledger['accounted_usd']['baseten']:.6f}/$20**, "
        f"**{ledger['calls']} entries**. Existing history and failed reservations remain intact; no reset, cap edit or manual charge. "
        f"Warnings: {', '.join(ledger['warnings']) if ledger['warnings'] else 'none'}. Native50% warning stops remained active.",
        'The original source recordings remain under `runs/sd-hard`. The amended evaluation uses '
        '`runs/sd-hard-partial-attempt1` and `runs/servedoctor-hard15-ops-20261102`. '
        'Original absolute descriptors are retained and mapped to verified package copies. '
        'The [display report](analysis/analysis-report.html) keeps native report bytes as unchanged provenance. '
        'The package includes90 final decisions, one-shot15 validity, both native CLI scoreboards, numeric per-case projection, '
        'the original16-case failure/history, protocol/exclusion and final ledger/cleanup manifests.',
        table(['Entry', 'Category', 'What happened', 'Reason/handling'],
              [[r['id'], r['category'], r['summary'], r['reason']] for r in failures['failures']]),
        'These are frozen counterfactual scores on recorded traces, not live recovery measurements. '
        'The startup exclusion limits generalization and prevents any full16-case claim. '
        'Rules or Glimmer may outperform frontier arms; failed calls and invalid outputs remain measured failures. '
        'No tuning or model selection used Hard arm results.']
    return '\n\n'.join(parts)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('projection', 'cleanup', 'failures', 'hardware', 'prices', 'protocol', 'out'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--optional-live-status', required=True, choices=('not-run-budget-below-5',))
    args = parser.parse_args()
    text = render(*[load(getattr(args, name)) for name in ('projection', 'cleanup', 'failures', 'hardware', 'prices', 'protocol')],
                  args.optional_live_status)
    with Path(args.out).open('x') as stream:
        stream.write(text)
    print(json.dumps({'project': PROJECT, 'label': LABEL, 'rendered': True,
                      'path': str(Path(args.out).resolve()), 'sha256': hashlib.sha256(text.encode()).hexdigest()}))


if __name__ == '__main__':
    main()
